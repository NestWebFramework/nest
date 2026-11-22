/* consent.js: the visitor's choice about cookies, for every script of the page:
 *   window.nestConsent.allowed("statistics")              true once the visitor allowed it
 *   window.nestConsent.allowed("statistics", "service")   and did not refuse that service of it
 * The choice is the cookie nest_consent (the consent module sets it when a choice is sent;
 * the page then reloads, so a script asks once, at its start). */
(function () {
  "use strict";
  function read() {
    var m = document.cookie.match(/(?:^|;\s*)nest_consent=([^;]*)/);
    if (!m) return {};
    var out = {};
    decodeURIComponent(m[1]).split("&").forEach(function (kv) {
      var p = kv.split("=");
      out[p[0]] = decodeURIComponent((p[1] || "").replace(/\+/g, " "));
    });
    return out;
  }
  window.nestConsent = {
    managed: true,
    allowed: function (purpose, service) {
      if (purpose === "necessary") return true;
      var c = read();
      if ((c.ok || "").split(",").indexOf(purpose) < 0) return false;
      return !service || (c.no || "").split(",").indexOf(service) < 0;
    },
  };
})();
