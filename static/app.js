document.addEventListener("DOMContentLoaded", function () {
  const menuButton = document.getElementById("menuButton");
  const closeMenu = document.getElementById("closeMenu");
  const sidebar = document.getElementById("sidebar");
  const menuOverlay = document.getElementById("menuOverlay");

  if (!sidebar || !menuOverlay) {
    return;
  }

  function openMenu() {
    sidebar.classList.add("open");
    menuOverlay.classList.add("open");

    if (menuButton) {
      menuButton.setAttribute("aria-expanded", "true");
    }

    document.body.style.overflow = "hidden";
  }

  function closeSidebar() {
    sidebar.classList.remove("open");
    menuOverlay.classList.remove("open");

    if (menuButton) {
      menuButton.setAttribute("aria-expanded", "false");
    }

    document.body.style.overflow = "";
  }

  if (menuButton) {
    menuButton.addEventListener("click", openMenu);
  }

  if (closeMenu) {
    closeMenu.addEventListener("click", closeSidebar);
  }

  menuOverlay.addEventListener("click", closeSidebar);

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      closeSidebar();
    }
  });

  window.addEventListener("resize", function () {
    if (window.innerWidth > 1024) {
      closeSidebar();
    }
  });
});


// document.addEventListener("DOMContentLoaded", function () {
//   const sessionsTable = document.querySelector("#sessionsTable");

//   if (sessionsTable && typeof DataTable !== "undefined") {
//     new DataTable(sessionsTable, {
//       responsive: true,
//       pageLength: 10,
//       lengthMenu: [5, 10, 25, 50],
//       order: [[1, "desc"]],

//       language: {
//         search: "",
//         searchPlaceholder: "Search sessions...",
//         lengthMenu: "Show _MENU_ records",
//         info: "Showing _START_ to _END_ of _TOTAL_ sessions",
//         infoEmpty: "No sessions available",
//         zeroRecords: "No matching sessions found"
//       },

//       layout: {
//         topStart: "pageLength",
//         topEnd: "search",
//         bottomStart: "info",
//         bottomEnd: "paging"
//       },

//       columnDefs: [
//         {
//           targets: -1,
//           orderable: false,
//           searchable: false
//         }
//       ]
//     });
//   }
// });