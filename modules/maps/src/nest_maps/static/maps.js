// maps.js — the maps module's maps. Leaflet (served by this module) is loaded only
// on a page that holds a map; each .map[data-map] gets OpenStreetMap's tiles and its
// markers from GeoJSON. Popups are built from text, never from markup.
(function () {
  "use strict";
  if (window.nestMaps) { window.nestMaps.scan(); return; }
  var me = document.currentScript && document.currentScript.src;
  var base = me ? me.replace(/maps\.js(\?.*)?$/, "") : "/assets/maps/";
  var version = me && me.indexOf("?") > 0 ? me.slice(me.indexOf("?")) : "";
  var waiting = null;

  function leaflet(done) {
    if (window.L) return done();
    if (waiting) { waiting.push(done); return; }
    waiting = [done];
    var css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = base + "leaflet/leaflet.css" + version;
    document.head.appendChild(css);
    var js = document.createElement("script");
    js.src = base + "leaflet/leaflet.js" + version;
    js.onload = function () {
      window.L.Icon.Default.imagePath = base + "leaflet/images/";
      var queue = waiting; waiting = null;
      queue.forEach(function (fn) { fn(); });
    };
    document.head.appendChild(js);
  }

  function safeUrl(url) {
    return typeof url === "string" && (/^\/(?!\/)/.test(url) || /^https?:\/\//.test(url));
  }

  function popup(p) {
    var box = document.createElement("div");
    box.className = "map-popup";
    var title = document.createElement(p.url && safeUrl(p.url) ? "a" : "strong");
    title.textContent = p.title || "";
    if (title.tagName === "A") title.href = p.url;
    box.appendChild(title);
    if (p.description) {
      var text = document.createElement("p");
      text.textContent = p.description;
      box.appendChild(text);
    }
    return box;
  }

  function draw(el) {
    if (el.getAttribute("data-ready")) return;
    el.setAttribute("data-ready", "1");
    var d = el.dataset;
    var zoom = parseInt(d.zoom, 10) || 13;
    el.innerHTML = "";
    var map = window.L.map(el, { scrollWheelZoom: false }).setView([+d.lat, +d.lng], zoom);
    // Tile servers want to know which site asks (OpenStreetMap blocks a tile asked for
    // without it); the site's pages send no referrer elsewhere, so the tiles ask with the
    // site's origin (never the page's address).
    window.L.tileLayer(d.tiles, {
      maxZoom: parseInt(d.maxZoom, 10) || 19,
      attribution: d.attribution,
      referrerPolicy: "strict-origin-when-cross-origin",
    }).addTo(map);
    var shown = null, first = true;
    function load() {
    fetch(d.map, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : { features: [] }; })
      .then(function (data) {
        if (shown) map.removeLayer(shown);
        var layer = shown = window.L.geoJSON(data, {
          // a line keeps its colour and weight; a point marked "dot" is a small circle (a
          // train's stops along its route), any other a marker
          style: function (f) {
            var p = f.properties || {};
            return { color: /^#[0-9a-f]{3,8}$/i.test(p.color || "") ? p.color : "#12355b", weight: +p.weight || 4, opacity: .85 };
          },
          pointToLayer: function (f, at) {
            var p = f.properties || {};
            if (!p.dot) return window.L.marker(at);
            return window.L.circleMarker(at, { radius: p.big ? 6 : 4, color: "#12355b", weight: 2, fillColor: p.big ? "#ffb400" : "#fff", fillOpacity: 1 });
          },
          onEachFeature: function (f, l) { if (f.properties && f.properties.title) l.bindPopup(popup(f.properties)); }
        }).addTo(map);
        if (first && d.fit && layer.getLayers().length > 1) map.fitBounds(layer.getBounds(), { padding: [24, 24], maxZoom: zoom });
        first = false;
      });
    }
    load();
    // a map of what moves (trains running now) asks again every so many seconds
    var every = parseInt(d.refresh, 10);
    if (every >= 10) setInterval(function () { if (!document.hidden) load(); }, every * 1000);
  }

  function scan() {
    var maps = document.querySelectorAll(".map[data-map]:not([data-ready])");
    if (maps.length) leaflet(function () { maps.forEach(draw); });
  }

  window.nestMaps = { scan: scan };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", scan);
  else scan();
  document.addEventListener("htmx:afterSettle", scan);
})();
