const menuButtons = document.querySelectorAll("[data-menu]");
menuButtons.forEach(button => button.addEventListener("click", () => {
  menuButtons.forEach(item => item.setAttribute("aria-pressed", String(item === button)));
  document.querySelectorAll("[data-kind]").forEach(card => {
    card.hidden = button.dataset.menu !== "전체" && button.dataset.menu !== card.dataset.kind;
  });
}));

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
