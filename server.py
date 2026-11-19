import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import closing
from http.cookies import SimpleCookie
from http import HTTPStatus
from wsgiref.simple_server import make_server
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATABASE = Path(os.environ.get("BAKERY_DB", ROOT / "community.sqlite3"))
ADMIN = os.environ.get("BAKERY_ADMIN", "")
ADMIN_PASSWORD = os.environ.get("BAKERY_ADMIN_PASSWORD", "")
SESSION_AGE = 7 * 24 * 60 * 60
FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    **{f"/{page}.html": (f"{page}.html", "text/html; charset=utf-8")
       for page in ("index", "menu", "about", "community", "visit")},
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/assets/bread.webp": ("assets/bread.webp", "image/webp"),
}


def connect():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)


def initialize():
    with closing(connect()) as db, db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
                salt BLOB NOT NULL, password BLOB NOT NULL, admin INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS sessions (
                digest TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id),
                expires INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER REFERENCES users(id),
                kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
                created TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
            );
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER REFERENCES users(id),
                post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE, body TEXT NOT NULL,
                created TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
            );
        """)
        if ADMIN and ADMIN_PASSWORD:
            if not 2 <= len(ADMIN) <= 24 or not 8 <= len(ADMIN_PASSWORD) <= 128:
                raise ValueError("Invalid admin nickname or password length")
            salt = secrets.token_bytes(16)
            cursor = db.execute(
                "INSERT OR IGNORE INTO users(name, salt, password, admin) VALUES(?,?,?,1)",
                (ADMIN, salt, password_hash(ADMIN_PASSWORD, salt)),
            )
            if not cursor.rowcount and not db.execute(
                "SELECT admin FROM users WHERE name=?", (ADMIN,)
            ).fetchone()["admin"]:
                raise ValueError("Admin nickname already belongs to a customer")


class RequestError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


def field(data, key, low, high):
    value = data.get(key)
    if not isinstance(value, str):
        raise RequestError(400, "입력 내용을 확인해주세요.")
    if key != "password":
        value = value.strip()
    if not low <= len(value) <= high:
        raise RequestError(400, "입력한 글자 수를 확인해주세요.")
    return value


def identifier(data, key):
    value = data.get(key)
    if type(value) is not int or not 0 < value < 2**63:
        raise RequestError(400, "게시물을 확인해주세요.")
    return value


class Bakery:
    def __init__(self, environ, start_response):
        self.environ = environ
        self.path = environ["PATH_INFO"]
        self.start_response = start_response

    def reply(self, status, body, media, cookie=None):
        headers = [
            ("Content-Type", media),
            ("Content-Length", str(len(body))),
            ("X-Content-Type-Options", "nosniff"),
            ("Content-Security-Policy", "default-src 'self'; base-uri 'none'; frame-ancestors 'none'"),
            ("Cache-Control", "no-store"),
        ]
        if cookie:
            if os.environ.get("BAKERY_HTTPS") == "1":
                cookie += "; Secure"
            headers.append(("Set-Cookie", cookie))
        self.start_response(f"{status} {HTTPStatus(status).phrase}", headers)
        return [body]

    def json_reply(self, status, data, cookie=None):
        return self.reply(status, json.dumps(data, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8", cookie)

    def session_digest(self):
        cookies = SimpleCookie(self.environ.get("HTTP_COOKIE", ""))
        token = cookies.get("bakery_session")
        return hashlib.sha256(token.value.encode()).hexdigest() if token else ""

    def session_user(self, db):
        return db.execute(
            """SELECT u.id, u.name, u.admin FROM users u JOIN sessions s ON s.user_id=u.id
               WHERE s.digest=? AND s.expires > unixepoch()""",
            (self.session_digest(),),
        ).fetchone()

    def make_session(self, db, user_id):
        token = secrets.token_urlsafe(32)
        db.execute("DELETE FROM sessions WHERE expires <= unixepoch() OR digest=?",
                   (self.session_digest(),))
        db.execute("INSERT INTO sessions VALUES (?, ?, unixepoch()+?)",
                   (hashlib.sha256(token.encode()).hexdigest(), user_id, SESSION_AGE))
        return f"bakery_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_AGE}"

    def do_GET(self):
        path = self.path
        if path in FILES:
            name, media = FILES[path]
            return self.reply(200, (ROOT / "public" / name).read_bytes(), media)
        with closing(connect()) as db:
            if path == "/api/account":
                user = self.session_user(db)
                return self.json_reply(200, {"user": dict(user) if user else None})
            elif path == "/api/posts":
                posts = [dict(row) for row in db.execute("""
                    SELECT p.*, u.name, u.admin FROM posts p JOIN users u ON p.user_id=u.id
                    ORDER BY (p.kind='notice') DESC, p.id DESC
                """)]
                by_id = {post["id"]: post for post in posts}
                for post in posts:
                    post["comments"] = []
                for row in db.execute("""
                    SELECT c.*, u.name, u.admin FROM comments c JOIN users u ON c.user_id=u.id
                    ORDER BY c.id
                """):
                    if row["post_id"] in by_id:
                        by_id[row["post_id"]]["comments"].append(dict(row))
                return self.json_reply(200, posts)
            else:
                return self.json_reply(404, {"error": "페이지를 찾을 수 없습니다."})

    def do_POST(self):
        try:
            if self.environ.get("CONTENT_TYPE", "").split(";", 1)[0].strip().lower() != "application/json":
                raise RequestError(415, "요청 형식을 확인해주세요.")
            length = int(self.environ.get("CONTENT_LENGTH") or "0")
            if not 0 < length <= 16000:
                raise RequestError(400, "요청 크기를 확인해주세요.")
            data = json.loads(self.environ["wsgi.input"].read(length))
            if not isinstance(data, dict):
                raise RequestError(400, "입력 내용을 확인해주세요.")
            with closing(connect()) as db, db:
                result, cookie = self.mutate(db, self.path, data)
            return self.json_reply(200, result, cookie)
        except RequestError as error:
            return self.json_reply(error.status, {"error": error.message})
        except (ValueError, UnicodeError):
            return self.json_reply(400, {"error": "입력 내용을 확인해주세요."})

    def mutate(self, db, path, data):
        if path in {"/api/register", "/api/login"}:
            name = field(data, "name", 2, 24)
            password = field(data, "password", 8, 128)
            row = db.execute("SELECT * FROM users WHERE name=?", (name,)).fetchone()
            if path == "/api/register":
                if name == ADMIN:
                    raise RequestError(409, "이미 사용 중인 닉네임입니다.")
                salt = secrets.token_bytes(16)
                try:
                    user_id = db.execute(
                        "INSERT INTO users(name,salt,password) VALUES(?,?,?)",
                        (name, salt, password_hash(password, salt)),
                    ).lastrowid
                except sqlite3.IntegrityError:
                    raise RequestError(409, "이미 사용 중인 닉네임입니다.") from None
            else:
                if not row or not hmac.compare_digest(row["password"], password_hash(password, row["salt"])):
                    raise RequestError(401, "닉네임이나 비밀번호를 확인해주세요.")
                user_id = row["id"]
            return {}, self.make_session(db, user_id)

        if path == "/api/logout":
            db.execute("DELETE FROM sessions WHERE digest=?", (self.session_digest(),))
            return {}, "bakery_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"

        user = self.session_user(db)
        if not user:
            raise RequestError(401, "먼저 로그인해주세요.")

        if path == "/api/posts":
            kind = field(data, "kind", 1, 10)
            kinds = {"review", "question", "notice"} if user["admin"] else {"review", "question"}
            if kind not in kinds:
                raise RequestError(400, "게시판을 선택해주세요.")
            cursor = db.execute(
                "INSERT INTO posts(user_id,kind,title,body) VALUES(?,?,?,?)",
                (user["id"], kind, field(data, "title", 1, 80), field(data, "body", 1, 2000)),
            )
            return {"id": cursor.lastrowid}, None

        if path == "/api/comments":
            post_id = identifier(data, "post_id")
            body = field(data, "body", 1, 1000)
            cursor = db.execute(
                """INSERT INTO comments(user_id,post_id,body)
                   SELECT ?,id,? FROM posts WHERE id=?""", (user["id"], body, post_id),
            )
            if not cursor.rowcount:
                raise RequestError(404, "게시글을 찾을 수 없습니다.")
            return {}, None

        actions = {
            "/api/posts/edit": ("posts", "edit"),
            "/api/posts/delete": ("posts", "delete"),
            "/api/comments/edit": ("comments", "edit"),
            "/api/comments/delete": ("comments", "delete"),
        }
        if path not in actions:
            raise RequestError(404, "요청한 기능을 찾을 수 없습니다.")
        table, action = actions[path]
        item_id = identifier(data, "id")
        if action == "delete":
            cursor = db.execute(
                f"DELETE FROM {table} WHERE id=? AND (user_id=? OR ?=1)",
                (item_id, user["id"], user["admin"]),
            )
        elif table == "posts":
            cursor = db.execute(
                "UPDATE posts SET title=?, body=? WHERE id=? AND user_id=?",
                (field(data, "title", 1, 80), field(data, "body", 1, 2000), item_id, user["id"]),
            )
        else:
            cursor = db.execute(
                "UPDATE comments SET body=? WHERE id=? AND user_id=?",
                (field(data, "body", 1, 1000), item_id, user["id"]),
            )
        if not cursor.rowcount:
            raise RequestError(404, "게시물을 찾을 수 없거나 권한이 없습니다.")
        return {}, None


def application(environ, start_response):
    request = Bakery(environ, start_response)
    method = environ["REQUEST_METHOD"]
    if method == "GET":
        return request.do_GET()
    if method == "HEAD":
        request.do_GET()
        return []
    if method == "POST":
        return request.do_POST()
    return request.json_reply(405, {"error": "지원하지 않는 요청입니다."})


if __name__ == "__main__":
    initialize()
    if "PORT" in os.environ:
        from waitress import serve
        serve(application, host="0.0.0.0", port=int(os.environ["PORT"]),
              max_request_body_size=16000)
    else:
        port = int(os.environ.get("BAKERY_PORT", "8787"))
        with make_server("127.0.0.1", port, application) as server:
            print(f"동네오븐 베이커리 · http://127.0.0.1:{port}", flush=True)
            server.serve_forever()
