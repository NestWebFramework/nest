/* The site's service worker (the pwa module of Nest). Version __VERSION__.
 *
 * - First, the offline page and the files every page needs are kept (the "core" cache, one
 *   per version; the old ones go when a new version takes over).
 * - Pages: from the network; when it fails (or takes too long and a copy exists), the copy
 *   kept, else the offline page. Every page for anyone is kept, never one Nest marks
 *   Cache-Control private or no-store (made for a signed-in visitor), the newest `pages`.
 * - The site's files (/assets/, versioned): from the cache first, they never change.
 * - Maps (.geojson): from the network, the last copy when offline. Live data (.json):
 *   always from the network.
 * - Never touched: other sites, anything but GET, the admin panel, the account pages.
 * - A new version waits until the page says to take over (its "Reload" button).
 */
"use strict";

const VERSION = "__VERSION__";
const CONFIG = __CONFIG__;
const CORE = "nest-core-" + VERSION;
const ASSETS = "nest-assets";
const DATA = "nest-data";
const PAGES = CONFIG.pagesCache;
const SLOW = 5000; // ms: a page slower than this is answered from its copy, when there is one

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CORE).then((cache) =>
      Promise.all(
        CONFIG.precache.map((url) =>
          fetch(url, { cache: "reload", credentials: "same-origin" })
            .then((r) => (r.ok ? cache.put(url, r) : null))
            .catch(() => null)
        )
      )
    )
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(
          names
            .filter((n) => n.startsWith("nest-core-") && n !== CORE)
            .map((n) => caches.delete(n))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("message", (event) => {
  const data = event.data || {};
  if (data.type === "skip-waiting") self.skipWaiting();
  if (data.type === "forget-pages") event.waitUntil(caches.delete(PAGES));
});

function untouched(url) {
  return CONFIG.never.some((p) => url.pathname === p || url.pathname.startsWith(p + "/"));
}

async function trim(name, most) {
  const cache = await caches.open(name);
  const keys = await cache.keys(); // oldest first
  for (let i = 0; i < keys.length - most; i++) await cache.delete(keys[i]);
}

function keepable(response) {
  // a page for anyone: not one Nest marks private (made for a signed-in visitor) or
  // no-store; an HTML answer of this site that went well
  const cc = (response.headers.get("cache-control") || "").toLowerCase();
  const type = response.headers.get("content-type") || "";
  return (
    response.ok &&
    response.type === "basic" &&
    type.startsWith("text/html") &&
    !cc.includes("private") &&
    !cc.includes("no-store")
  );
}

async function keepPage(request, response) {
  // its title and when it was read go with it, for the offline page's list
  const text = await response.text();
  const m = text.match(/<title[^>]*>([^<]*)<\/title>/i);
  const headers = new Headers(response.headers);
  headers.set("x-pwa-title", encodeURIComponent((m ? m[1] : "").trim().slice(0, 140)));
  headers.set("x-pwa-saved", new Date().toISOString());
  const cache = await caches.open(PAGES);
  // the same page under one key, whatever came after a # or the source tag
  await cache.put(request.url.split("#")[0], new Response(text, { status: 200, headers }));
  await trim(PAGES, CONFIG.pages);
}

async function fromCopy(request) {
  const cache = await caches.open(PAGES);
  const copy = await cache.match(request.url.split("#")[0]);
  if (copy) {
    // the page reads this from its own navigation timing: "a copy, kept on <date>"
    const headers = new Headers(copy.headers);
    const saved = copy.headers.get("x-pwa-saved") || "";
    headers.set("server-timing", 'pwa-copy;desc="' + saved + '"');
    return new Response(copy.body, { status: 200, headers });
  }
  const offline = await caches.match(CONFIG.offline);
  return offline || new Response("Offline", { status: 503, headers: { "content-type": "text/plain" } });
}

async function page(event) {
  const request = event.request;
  const network = fetch(request).then(async (response) => {
    if (keepable(response)) event.waitUntil(keepPage(request, response.clone()));
    return response;
  });
  const cache = await caches.open(PAGES);
  const copy = await cache.match(request.url.split("#")[0]);
  if (!copy) {
    try {
      return await network;
    } catch (e) {
      return fromCopy(request);
    }
  }
  // a copy exists: the network if it answers in time, else the copy (the network still
  // refreshes it in the background)
  const slow = new Promise((resolve) => setTimeout(() => resolve("slow"), SLOW));
  try {
    const first = await Promise.race([network, slow]);
    if (first !== "slow") return first;
    event.waitUntil(network.catch(() => null));
    return fromCopy(request);
  } catch (e) {
    return fromCopy(request);
  }
}

async function asset(request) {
  const hit = await caches.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok && response.type === "basic") {
    const cache = await caches.open(ASSETS);
    await cache.put(request, response.clone());
    trim(ASSETS, 150);
  }
  return response;
}

async function data(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(DATA);
      await cache.put(request, response.clone());
      trim(DATA, 30);
    }
    return response;
  } catch (e) {
    const hit = await caches.match(request);
    if (hit) return hit;
    throw e;
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || untouched(url)) return;
  if (request.mode === "navigate") {
    event.respondWith(page(event));
  } else if (url.pathname.startsWith("/assets/")) {
    event.respondWith(asset(request));
  } else if (url.pathname.endsWith(".geojson")) {
    event.respondWith(data(request));
  }
  // anything else (live data, forms' answers, htmx fragments): the network, as without us
});
