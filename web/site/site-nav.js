(function () {
  "use strict";
  var button = document.querySelector(".nav-toggle");
  var menu = document.getElementById("mobile-nav");
  if (!button || !menu) return;

  function setOpen(open) {
    menu.hidden = !open;
    button.setAttribute("aria-expanded", String(open));
    button.classList.toggle("is-open", open);
    document.body.classList.toggle("menu-open", open);
  }

  button.addEventListener("click", function () {
    setOpen(menu.hidden);
  });

  menu.addEventListener("click", function (event) {
    if (event.target.closest("a")) setOpen(false);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !menu.hidden) {
      setOpen(false);
      button.focus();
    }
  });

  window.addEventListener("resize", function () {
    if (window.innerWidth > 960 && !menu.hidden) setOpen(false);
  });
})();
