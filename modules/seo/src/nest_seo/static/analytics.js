/* Google Analytics 4, loaded by the site's own script (no inline code, so the page policy
 * stays strict): asks the visitor first when data-consent is 1, and remembers the answer
 * in this browser; then loads Google's gtag.js and configures it with data-ga. */
(function () {
  "use strict";
  var me = document.currentScript;
  if (!me) return;
  var id = me.getAttribute("data-ga");
  if (!/^G-[A-Z0-9]{4,20}$/.test(id || "")) return;
  var KEY = "nest-analytics";

  function remembered() {
    try { return window.localStorage.getItem(KEY); } catch (e) { return null; }
  }
  function remember(value) {
    try { window.localStorage.setItem(KEY, value); } catch (e) { /* private window: asked again */ }
  }
  function load() {
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag("js", new Date());
    window.gtag("config", id, { anonymize_ip: true });
    var s = document.createElement("script");
    s.async = true;
    s.src = "https://www.googletagmanager.com/gtag/js?id=" + encodeURIComponent(id);
    document.head.appendChild(s);
  }
  function ask() {
    var box = document.createElement("div");
    box.className = "nest-consent";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-live", "polite");
    var p = document.createElement("p");
    p.textContent = me.getAttribute("data-text") || "";
    var yes = document.createElement("button");
    yes.type = "button";
    yes.textContent = me.getAttribute("data-yes") || "OK";
    var no = document.createElement("button");
    no.type = "button";
    no.className = "secondary";
    no.textContent = me.getAttribute("data-no") || "No";
    yes.addEventListener("click", function () { remember("yes"); box.remove(); load(); });
    no.addEventListener("click", function () { remember("no"); box.remove(); });
    box.append(p, yes, no);
    document.body.appendChild(box);
  }

  // "given": the consent module asked, and the visitor allowed statistics
  if (me.getAttribute("data-consent") !== "1" || remembered() === "yes") load();
  else if (remembered() !== "no") ask();
})();
