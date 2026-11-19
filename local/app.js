const categories = { review: "빵 후기", question: "매장에 질문", notice: "매장 소식" };
const menuButtons = document.querySelectorAll("[data-menu]");
menuButtons.forEach(button => button.addEventListener("click", () => {
  menuButtons.forEach(item => item.setAttribute("aria-pressed", String(item === button)));
  document.querySelectorAll("[data-kind]").forEach(card => {
    card.hidden = button.dataset.menu !== "전체" && button.dataset.menu !== card.dataset.kind;
  });
}));

async function api(path, data) {
  if (location.protocol === "file:") throw new Error("커뮤니티를 사용하려면 사이트 서버를 실행해주세요.");
  const response = await fetch("/api/" + path, data === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data)
  });
  if (!response.headers.get("Content-Type")?.includes("application/json")) {
    throw new Error("커뮤니티 서버에 연결할 수 없습니다.");
  }
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error);
  return payload;
}

function element(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = content;
  return node;
}

const recent = document.querySelector("#recent");
if (recent) {
  api("posts").then(posts => {
    for (const post of posts.slice(0, 3)) {
      const link = element("a", "text-link", categories[post.kind] + " · " + post.title);
      link.href = "community.html#post-" + post.id;
      recent.append(link);
    }
    recent.hidden = recent.childElementCount === 0;
  }).catch(() => {});
}

const list = document.querySelector("#posts");
if (list) setupBoard();

function setupBoard() {
  const status = document.querySelector("#status");
  const account = document.querySelector("#account");
  const compose = document.querySelector("#compose");
  const filters = document.querySelectorAll("[data-filter]");
  const formData = form => Object.fromEntries(new FormData(form));
  const date = new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeZone: "Asia/Seoul" });
  let user = null;
  let posts = [];
  let filter = location.hash === "#question" ? "question" : "";
  const search = document.querySelector("#board-search");
  search.addEventListener("input", () => render());
  filters.forEach(button => button.setAttribute("aria-pressed", String(button.dataset.filter === filter)));
  if (filter === "question") compose.elements.kind.value = "question";

  async function run(action, button) {
    if (button) button.disabled = true;
    status.textContent = "";
    try {
      await action();
    } catch (error) {
      status.textContent = error.message;
    } finally {
      if (button) button.disabled = false;
    }
  }

  function refreshAccount() {
    account.hidden = Boolean(user);
    compose.hidden = !user;
    document.querySelector("#nickname").textContent = user ? user.name + (user.admin ? " · 매장" : "") : "";
    const notice = compose.elements.kind.querySelector('[value="notice"]');
    notice.disabled = notice.hidden = !user?.admin;
    if (!user?.admin && compose.elements.kind.value === "notice") compose.elements.kind.value = "review";
  }

  async function refreshPosts(openId) {
    posts = await api("posts");
    render(openId);
  }

  function label(record) {
    return record.name + (record.admin ? " · 매장" : "") + " · " + date.format(new Date(record.created));
  }

  function itemActions(record, type, postId, parent) {
    if (!user) return;
    const own = user.id === record.user_id;
    if (!own && !user.admin) return;
    const actions = element("div", "actions");
    if (own) {
      const edit = element("button", "link-button", "수정");
      edit.type = "button";
      edit.addEventListener("click", () => {
        if (parent.querySelector(".edit-form")) return;
        const form = element("form", "comment-form edit-form");
        let title;
        if (type === "posts") {
          title = element("input");
          title.setAttribute("aria-label", "수정할 제목");
          title.maxLength = 80;
          title.required = true;
          title.value = record.title;
          form.append(title);
        }
        const body = element("textarea");
        body.setAttribute("aria-label", "수정할 내용");
        body.maxLength = type === "posts" ? 2000 : 1000;
        body.required = true;
        body.rows = 4;
        body.value = record.body;
        const save = element("button", "button", "저장");
        const cancel = element("button", "button outline dark", "취소");
        cancel.type = "button";
        cancel.addEventListener("click", () => { form.remove(); edit.focus(); });
        form.append(body, save, cancel);
        parent.append(form);
        (title || body).focus();
        form.addEventListener("submit", event => {
          event.preventDefault();
          run(async () => {
            await api(type + "/edit", { id: record.id, title: title?.value, body: body.value });
            await refreshPosts(postId);
            status.textContent = "수정했습니다.";
          }, save);
        });
      });
      actions.append(edit);
    }
    const remove = element("button", "link-button", "삭제");
    remove.type = "button";
    remove.addEventListener("click", () => {
      if (!confirm("이 내용을 삭제할까요?")) return;
      run(async () => {
        await api(type + "/delete", { id: record.id });
        await refreshPosts(postId);
        status.textContent = "삭제했습니다.";
      }, remove);
    });
    actions.append(remove);
    parent.append(actions);
  }

  function render(openId) {
    const expanded = new Set([...list.querySelectorAll("details[open]")].map(item => item.id));
    if (openId) expanded.add("post-" + openId);
    if (location.hash.startsWith("#post-")) expanded.add(location.hash.slice(1));
    list.replaceChildren();
    const query = search.value.trim().toLocaleLowerCase();
    const visible = posts.filter(post => {
      const matchesCategory = !filter || post.kind === filter;
      const text = [post.title, post.body, post.name].join(" ").toLocaleLowerCase();
      return matchesCategory && text.includes(query);
    });
    if (!visible.length) list.append(element("p", "post", query ? "검색 결과가 없습니다. 다른 단어로 검색해보세요." : "아직 게시글이 없습니다."));
    for (const post of visible) {
      const article = element("details", "post");
      article.id = "post-" + post.id;
      article.open = expanded.has(article.id);
      const summary = element("summary");
      summary.append(element("span", "post-title", post.title),
        element("small", "", categories[post.kind] + " · " + label(post) + " · 댓글 " + post.comments.length));
      article.append(summary);
      const content = element("div");
      content.append(element("p", "post-body", post.body));
      itemActions(post, "posts", post.id, content);
      article.append(content);
      for (const comment of post.comments) {
        const block = element("div", "comment");
        block.append(element("small", "", label(comment)), element("p", "", comment.body));
        itemActions(comment, "comments", post.id, block);
        article.append(block);
      }
      if (user) {
        const form = element("form", "comment-form");
        const input = element("textarea");
        input.setAttribute("aria-label", "댓글 내용");
        input.placeholder = "댓글을 입력하세요";
        input.rows = 2;
        input.required = true;
        input.maxLength = 1000;
        const button = element("button", "button", "댓글 등록");
        form.append(input, button);
        form.addEventListener("submit", event => {
          event.preventDefault();
          run(async () => {
            await api("comments", { post_id: post.id, body: input.value });
            await refreshPosts(post.id);
            status.textContent = "댓글을 등록했습니다.";
          }, button);
        });
        article.append(form);
      }
      list.append(article);
    }
  }

  filters.forEach(button => button.addEventListener("click", () => {
    filter = button.dataset.filter;
    filters.forEach(item => item.setAttribute("aria-pressed", String(button === item)));
    render();
  }));

  account.addEventListener("submit", event => {
    event.preventDefault();
    const action = event.submitter?.value || "login";
    run(async () => {
      await api(action, formData(account));
      user = (await api("account")).user;
      account.reset();
      refreshAccount();
      render();
      status.textContent = action === "register" ? "가입했습니다." : "로그인했습니다.";
    }, event.submitter);
  });

  const logout = document.querySelector("#logout");
  logout.addEventListener("click", () => run(async () => {
    await api("logout", {});
    user = null;
    compose.reset();
    refreshAccount();
    render();
    status.textContent = "로그아웃했습니다.";
  }, logout));

  compose.addEventListener("submit", event => {
    event.preventDefault();
    run(async () => {
      const post = await api("posts", formData(compose));
      compose.reset();
      search.value = "";
      filters[0].click();
      await refreshPosts(post.id);
      status.textContent = "게시글을 등록했습니다.";
    }, event.submitter);
  });

  run(async () => {
    user = (await api("account")).user;
    refreshAccount();
    await refreshPosts();
    if (location.hash.startsWith("#post-")) {
      document.getElementById(location.hash.slice(1))?.scrollIntoView();
    }
  });
}
const navigationButton = document.querySelector(".nav-toggle");
const header = document.querySelector(".site-header");
header.classList.add("interactive-nav");
function setMenu(open) {
  navigationButton.setAttribute("aria-expanded", String(open));
  navigationButton.textContent = open ? "닫기" : "메뉴";
}
navigationButton.addEventListener("click", () => {
  setMenu(navigationButton.getAttribute("aria-expanded") !== "true");
});
header.addEventListener("keydown", event => {
  if (event.key === "Escape" && navigationButton.getAttribute("aria-expanded") === "true") {
    setMenu(false);
    navigationButton.focus();
  }
});
