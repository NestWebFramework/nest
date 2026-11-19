// toasts.js — the notifications module's toasts. Those the page came with are already in
// #toasts; htmx brings more in its HX-Trigger header (the nest:toast event), and a page's
// scripts say one with window.nest.toast(text, level). Each closes by itself (an error
// stays until closed), waits while pointed at or focused, and closes with its × or Esc.
(function () {
  "use strict";
  var LIFE = { success: 4500, info: 6000, warning: 9000, error: 0 };
  var LEVELS = ["success", "info", "warning", "error"];

  function region() {
    var r = document.getElementById("toasts");
    if (!r) {
      r = document.createElement("div");
      r.id = "toasts";
      r.className = "toasts";
      r.setAttribute("role", "status");
      r.setAttribute("aria-live", "polite");
      document.body.appendChild(r);
    }
    return r;
  }

  function close(el) {
    if (!el || el.classList.contains("toast-leaving")) return;
    el.classList.add("toast-leaving");
    setTimeout(function () { el.remove(); }, 250);
  }

  function arm(el) {
    if (el.getAttribute("data-armed")) return;
    el.setAttribute("data-armed", "1");
    var level = LEVELS.filter(function (l) { return el.classList.contains("toast-" + l); })[0] || "info";
    var life = LIFE[level];
    var timer = null;
    var start = function () { if (life) timer = setTimeout(function () { close(el); }, life); };
    var stop = function () { clearTimeout(timer); };
    el.addEventListener("mouseenter", stop);
    el.addEventListener("mouseleave", start);
    el.addEventListener("focusin", stop);
    el.addEventListener("focusout", start);
    var x = el.querySelector(".toast-close");
    if (x) x.addEventListener("click", function () { close(el); });
    start();
  }

  function show(text, level) {
    level = LEVELS.indexOf(level) >= 0 ? level : "info";
    var r = region();
    var el = document.createElement("div");
    el.className = "toast toast-" + level;
    if (level === "error") el.setAttribute("role", "alert");
    var t = document.createElement("span");
    t.className = "toast-text";
    t.textContent = String(text).slice(0, 300); // text, never markup
    var x = document.createElement("button");
    x.type = "button";
    x.className = "toast-close";
    x.setAttribute("aria-label", r.getAttribute("data-close") || "Close");
    x.textContent = "×";
    el.appendChild(t);
    el.appendChild(x);
    r.appendChild(el);
    while (r.children.length > 5) r.removeChild(r.firstChild);
    arm(el);
    return el;
  }

  function armAll() { document.querySelectorAll("#toasts .toast").forEach(arm); }

  window.nest = window.nest || {};
  window.nest.toast = show;
  document.addEventListener("nest:toast", function (e) {
    var items = (e.detail && e.detail.items) || [];
    items.forEach(function (i) { show(i.text, i.level); });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      var last = document.querySelector("#toasts .toast:last-child");
      if (last) close(last);
    }
  });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", armAll);
  else armAll();
})();
