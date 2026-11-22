// nest-htmx.js — a request htmx could not complete is told, never silent: a server error
// or a proxy's timeout (htmx:responseError), no answer at all (htmx:sendError, htmx:timeout).
// Shown as a toast when the notifications module is there, else as a notice at the top.
(function () {
  "use strict";
  function said(name, code) {
    var m = document.querySelector('meta[name="nest-htmx-said"]');
    var text = (m && m.getAttribute("data-" + name)) || "The server could not answer.";
    return text.replace("{code}", String(code || ""));
  }
  function tell(text) {
    if (window.nest && typeof window.nest.toast === "function") {
      window.nest.toast(text, "error");
      return;
    }
    var p = document.getElementById("nest-htmx-failed");
    if (!p) {
      p = document.createElement("p");
      p.id = "nest-htmx-failed";
      p.className = "notice danger";
      p.setAttribute("role", "alert");
      var main = document.querySelector("main") || document.body;
      main.insertBefore(p, main.firstChild);
    }
    p.textContent = text;
  }
  document.addEventListener("htmx:responseError", function (e) {
    var xhr = e.detail && e.detail.xhr;
    tell(said("failed", xhr ? xhr.status : ""));
  });
  document.addEventListener("htmx:sendError", function () { tell(said("unreachable")); });
  document.addEventListener("htmx:timeout", function () { tell(said("unreachable")); });
})();
