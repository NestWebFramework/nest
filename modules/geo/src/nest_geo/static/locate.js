// locate.js: a "locate me" button for any module. It asks the browser where the reader is
// and loads the button's data-url (?lat=&lon=) into its data-target (htmx when the page
// has it, else a plain fetch). A static file, so it runs under the strict page policy.
(function () {
  "use strict";
  function status(button, text) {
    var s = button.parentNode.querySelector("[data-geo-status]");
    if (s) s.textContent = text || "";
  }
  document.addEventListener("click", function (e) {
    var button = e.target.closest("[data-geo-locate]");
    if (!button) return;
    if (!navigator.geolocation) { status(button, button.getAttribute("data-no") || "—"); return; }
    button.disabled = true;
    status(button, "…");
    navigator.geolocation.getCurrentPosition(function (pos) {
      var url = button.getAttribute("data-url");
      url += (url.indexOf("?") < 0 ? "?" : "&") + "lat=" + pos.coords.latitude.toFixed(5) + "&lon=" + pos.coords.longitude.toFixed(5);
      var target = button.getAttribute("data-target");
      var done = function () { button.disabled = false; status(button, ""); };
      if (window.htmx) {
        window.htmx.ajax("GET", url, { target: target, swap: "outerHTML" }).then(done, done);
      } else {
        fetch(url, { headers: { "HX-Request": "true" }, credentials: "same-origin" })
          .then(function (r) { return r.text(); })
          .then(function (html) { var el = document.querySelector(target); if (el) el.outerHTML = html; done(); }, done);
      }
    }, function () { button.disabled = false; status(button, ""); }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 });
  });
})();
