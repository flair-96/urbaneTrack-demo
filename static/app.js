document.addEventListener("DOMContentLoaded", () => {
  const menuButton = document.getElementById("menuButton");
  const closeMenu = document.getElementById("closeMenu");
  const sidebar = document.getElementById("sidebar");
  const overlay = document.getElementById("menuOverlay");

  if (!menuButton || !sidebar || !overlay) {
    return;
  }

  function openMenu() {
    sidebar.classList.add("open");
    overlay.classList.add("open");
  }

  function closeSidebar() {
    sidebar.classList.remove("open");
    overlay.classList.remove("open");
  }

  menuButton.addEventListener("click", openMenu);
  overlay.addEventListener("click", closeSidebar);

  if (closeMenu) {
    closeMenu.addEventListener("click", closeSidebar);
  }
});