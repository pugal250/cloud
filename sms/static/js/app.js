/* Progressive enhancement only - every page works without JavaScript. */
(function () {
  "use strict";
  document.documentElement.classList.add("js");

  document.addEventListener("DOMContentLoaded", function () {
    // Mobile sidebar toggle
    var toggle = document.getElementById("menu-toggle");
    var sidebar = document.getElementById("sidebar");
    function closeMenu() {
      sidebar.classList.remove("open");
      toggle.setAttribute("aria-expanded", "false");
    }
    if (toggle && sidebar) {
      toggle.addEventListener("click", function () {
        var open = sidebar.classList.toggle("open");
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
      });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && sidebar.classList.contains("open")) { closeMenu(); toggle.focus(); }
      });
      document.querySelector("main").addEventListener("click", function () {
        if (sidebar.classList.contains("open")) closeMenu();
      });
    }

    // Dismiss flash messages
    document.querySelectorAll("[data-dismiss]").forEach(function (btn) {
      btn.addEventListener("click", function () { btn.closest(".alert").remove(); });
    });

    // Client-side file checks (the server re-validates everything)
    document.querySelectorAll("input[type=file][data-max-bytes]").forEach(function (input) {
      input.addEventListener("change", function () {
        var file = input.files[0];
        var max = parseInt(input.dataset.maxBytes, 10);
        var ok = /\.(pdf|png|jpe?g)$/i.test(file ? file.name : "x.pdf");
        input.setCustomValidity("");
        if (file && !ok) input.setCustomValidity("Only PDF, PNG or JPG files are allowed.");
        else if (file && file.size > max) input.setCustomValidity("The file is larger than " + Math.round(max / 1048576) + " MB.");
        if (!input.checkValidity()) input.reportValidity();
      });
    });

    // Keep leave end-date >= start-date
    var start = document.querySelector("[data-range-start]");
    var end = document.querySelector("[data-range-end]");
    if (start && end) {
      var sync = function () { if (start.value) end.min = start.value; };
      start.addEventListener("change", sync);
      sync();
    }

    // Prevent double submits
    document.querySelectorAll("form").forEach(function (form) {
      form.addEventListener("submit", function (e) {
        if (form.dataset.submitting) { e.preventDefault(); return; }
        form.dataset.submitting = "1";
        setTimeout(function () {
          form.querySelectorAll("button[type=submit]").forEach(function (b) { b.disabled = true; });
        }, 0);
      });
    });
    window.addEventListener("pageshow", function () {
      document.querySelectorAll("form").forEach(function (form) {
        delete form.dataset.submitting;
        form.querySelectorAll("button[type=submit]").forEach(function (b) { b.disabled = false; });
      });
    });
  });
})();
