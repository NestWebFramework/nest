/* pwa.js: starts the site's service worker (/sw.js) and shows, when needed:
 *   - "Install the app" (when the browser offers it; on iPhone, how to add it),
 *   - "A new version is ready" with a Reload button (the new worker then takes over),
 *   - "You are offline", and when a page is a kept copy, from when.
 * On the offline page it lists the pages kept on this device.
 * window.nestPWA.ready: a promise of the worker's registration (for push, later).
 * Remembers only that the install button was dismissed (localStorage, 30 days). */
(function () {
  "use strict";
  var root = document.getElementById("nest-pwa");
  if (!root || !("serviceWorker" in navigator)) return;
  var sw = navigator.serviceWorker;
  var lang = document.documentElement.lang || "ro";
  var hadController = !!sw.controller;
  var fromCopy = false;
  var deferred = null;

  function part(sel) {
    return root.querySelector(sel);
  }
  function show(sel, on) {
    var el = part(sel);
    if (el) el.hidden = !on;
    return el;
  }
  function store(key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      window.localStorage.setItem(key, value);
    } catch (e) {
      return null;
    }
    return null;
  }
  function when(iso) {
    try {
      return new Date(iso).toLocaleString(lang, { dateStyle: "short", timeStyle: "short" });
    } catch (e) {
      return iso;
    }
  }

  // --- the worker, and its new versions ---------------------------------------------
  function offer(worker) {
    var el = show(".nest-pwa-update", true);
    el.querySelector("button").onclick = function () {
      el.hidden = true;
      worker.postMessage({ type: "skip-waiting" });
    };
  }
  function watch(reg) {
    if (reg.waiting && sw.controller) offer(reg.waiting);
    reg.addEventListener("updatefound", function () {
      var w = reg.installing;
      if (!w) return;
      w.addEventListener("statechange", function () {
        if (w.state === "installed" && sw.controller) offer(w);
      });
    });
    var checked = Date.now();
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible" && Date.now() - checked > 30 * 60 * 1000) {
        checked = Date.now();
        reg.update().catch(function () {});
      }
    });
  }
  var reloading = false;
  sw.addEventListener("controllerchange", function () {
    // the first worker taking a fresh page over needs no reload; a new version does
    if (reloading || !hadController) return;
    reloading = true;
    window.location.reload();
  });
  window.nestPWA = {
    ready: new Promise(function (resolve, reject) {
      window.addEventListener("load", function () {
        sw.register("/sw.js", { scope: "/" })
          .then(function (reg) {
            watch(reg);
            resolve(reg);
          })
          .catch(reject);
      });
    }),
  };
  window.nestPWA.ready.catch(function () {});

  // --- offline -----------------------------------------------------------------------
  function offlineBar(text) {
    var el = show(".nest-pwa-offline", true);
    el.querySelector("span").textContent = text;
  }
  function state() {
    if (!navigator.onLine) offlineBar(root.dataset.offline);
    else if (!fromCopy) show(".nest-pwa-offline", false);
  }
  window.addEventListener("online", state);
  window.addEventListener("offline", state);
  state();
  // a page the worker answered from its copy says so in its navigation timing
  try {
    var nav = performance.getEntriesByType("navigation")[0];
    (nav && nav.serverTiming ? nav.serverTiming : []).forEach(function (t) {
      if (t.name === "pwa-copy") {
        fromCopy = true;
        // a kept copy: its cookie notice cannot be answered offline
        var notice = document.querySelector(".nest-consent-bar");
        if (notice) notice.hidden = true;
        offlineBar(root.dataset.copy.replace("{time}", t.description ? when(t.description) : "?"));
      }
    });
  } catch (e) {}

  // --- installing --------------------------------------------------------------------
  var standalone =
    window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  var dismissed = Number(store("nest-pwa-dismissed") || 0);
  if (root.dataset.install === "1" && !standalone && Date.now() > dismissed) {
    // not while the cookie notice waits for an answer: one question at a time
    var asking = !!document.querySelector(".nest-consent-bar");
    window.addEventListener("beforeinstallprompt", function (event) {
      event.preventDefault();
      deferred = event;
      if (!asking) show(".nest-pwa-install", true);
    });
    var ua = navigator.userAgent;
    var ios = /iphone|ipad|ipod/i.test(ua) || (/macintosh/i.test(ua) && navigator.maxTouchPoints > 1);
    if (!asking && ios && /safari/i.test(ua) && !/crios|fxios|edgios/i.test(ua)) {
      show(".nest-pwa-ios", true);
    }
  }
  window.addEventListener("appinstalled", function () {
    show(".nest-pwa-install", false);
  });
  root.addEventListener("click", function (event) {
    var button = event.target.closest("[data-pwa]");
    if (!button) return;
    var action = button.dataset.pwa;
    if (action === "install" && deferred) {
      deferred.prompt();
      deferred.userChoice.finally(function () {
        deferred = null;
        show(".nest-pwa-install", false);
      });
    } else if (action === "dismiss") {
      store("nest-pwa-dismissed", String(Date.now() + 30 * 864e5));
      show(".nest-pwa-install", false);
      show(".nest-pwa-ios", false);
    }
  });

  // --- the offline page: the pages kept ------------------------------------------------
  var list = document.getElementById("nest-pwa-saved");
  if (list && "caches" in window) {
    var name = list.dataset.cache;
    caches
      .open(name)
      .then(function (cache) {
        return cache.keys().then(function (keys) {
          return Promise.all(
            keys.reverse().map(function (key) {
              return cache.match(key).then(function (r) {
                return {
                  url: key.url,
                  title: decodeURIComponent((r && r.headers.get("x-pwa-title")) || ""),
                  saved: (r && r.headers.get("x-pwa-saved")) || "",
                };
              });
            })
          );
        });
      })
      .then(function (items) {
        if (!items.length) return;
        list.hidden = false;
        var none = document.getElementById("nest-pwa-none");
        if (none) none.hidden = true;
        items.forEach(function (item) {
          var li = document.createElement("li");
          var a = document.createElement("a");
          a.href = item.url;
          a.textContent = item.title || new URL(item.url).pathname;
          li.appendChild(a);
          if (item.saved) {
            var small = document.createElement("small");
            small.textContent = " · " + when(item.saved);
            li.appendChild(small);
          }
          list.appendChild(li);
        });
      })
      .catch(function () {});
    document.addEventListener("click", function (event) {
      var button = event.target.closest("[data-pwa-page]");
      if (!button) return;
      if (button.dataset.pwaPage === "retry") window.location.reload();
      if (button.dataset.pwaPage === "forget") {
        caches.delete(name).then(function () {
          list.innerHTML = "";
          list.hidden = true;
          var none = document.getElementById("nest-pwa-none");
          if (none) none.hidden = false;
        });
      }
    });
  }
})();
