// seo.js — the SEO fields: how many characters a title and a description have (and how
// many show in a search result), and a preview of the result, as they are typed.
(function () {
  "use strict";
  function each(box) {
    if (box.getAttribute("data-ready")) return;
    box.setAttribute("data-ready", "1");
    var title = box.querySelector("#seo_title");
    var desc = box.querySelector("#seo_description");
    var pTitle = box.querySelector(".seo-preview-title");
    var pDesc = box.querySelector(".seo-preview-desc");
    function count(input) {
      var out = input.parentNode.querySelector(".seo-count");
      var limit = parseInt(input.getAttribute("data-seo-count"), 10);
      var n = input.value.length;
      if (out) {
        out.textContent = n ? n + " / " + limit : "";
        out.classList.toggle("seo-long", n > limit);
      }
    }
    function preview() {
      pTitle.textContent = title.value || pTitle.getAttribute("data-default");
      var d = desc.value || pDesc.getAttribute("data-default");
      pDesc.textContent = d.length > 160 ? d.slice(0, 157) + "…" : d;
    }
    [title, desc].forEach(function (input) {
      input.addEventListener("input", function () { count(input); preview(); });
      count(input);
    });
  }
  function scan() { document.querySelectorAll("fieldset.seo-fields").forEach(each); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", scan);
  else scan();
  document.addEventListener("htmx:afterSettle", scan);
})();

// "Propose from the text": the page's title and text, as they are in the form now, go to
// the seo module, and its proposal fills the search fields (an empty one at once, a
// written one if the editor agrees). Nothing is saved until the form is.
(function () {
  "use strict";
  function texts(form) {
    var out = [];
    form.querySelectorAll('[name="excerpt"], [name="body"], [name="description"], [name^="caption_"], [name^="alt_"], [name^="field_"]').forEach(function (el) {
      if (el.type !== "checkbox" && el.value && el.value.trim()) out.push(el.value);
    });
    return out;
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("button.seo-propose");
    if (!b) return;
    var box = b.closest("fieldset.seo-fields");
    var form = b.closest("form");
    var status = box.querySelector(".seo-propose-status");
    var body = new FormData();
    var title = form.querySelector('[name="title"]') || form.querySelector('[name="name"]');  // a category has a name
    body.append("title", title ? title.value : "");
    if (b.getAttribute("data-subject")) body.append("subject", b.getAttribute("data-subject"));
    texts(form).forEach(function (t) { body.append("text", t); });
    // what the page is about besides its text: its categories (their names), if it has any
    form.querySelectorAll('input[name^="terms_"]:checked').forEach(function (el) {
      var label = el.closest("label");
      if (label && label.textContent.trim()) body.append("context", label.textContent.trim());
    });
    var token = form.querySelector('input[name="csrf_token"]');
    b.disabled = true;
    fetch(b.getAttribute("data-url"), {
      method: "POST", body: body, credentials: "same-origin",
      headers: { "x-csrf-token": token ? token.value : "" },
    }).then(function (r) { if (!r.ok) throw new Error(); return r.json(); }).then(function (p) {
      var fields = [["seo_title", p.title], ["seo_description", p.description], ["seo_keywords", p.keywords]];
      var names = JSON.parse(b.getAttribute("data-names") || "{}");
      var filled = [], offered = [];
      box.querySelectorAll(".seo-suggestion").forEach(function (el) { el.remove(); });
      var useAll = box.querySelector(".seo-use-all");
      if (useAll) useAll.remove();
      function put(el, value) {
        el.value = value;
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.classList.remove("seo-filled");
        void el.offsetWidth; // start the highlight again
        el.classList.add("seo-filled");
      }
      fields.forEach(function (f) {
        var el = box.querySelector("#" + f[0]);
        if (!f[1] || el.value.trim() === f[1]) return;
        if (!el.value.trim()) { put(el, f[1]); filled.push(names[f[0]] || f[0]); return; }
        // written already: the proposal goes under the field, to take with a click
        var tip = document.createElement("div");
        tip.className = "seo-suggestion";
        var label = document.createElement("span");
        label.className = "seo-suggestion-label";
        label.textContent = b.getAttribute("data-proposal") + " ";
        var text = document.createElement("span");
        text.textContent = f[1];
        var use = document.createElement("button");
        use.type = "button";
        use.className = "link seo-use";
        use.textContent = b.getAttribute("data-use");
        use.addEventListener("click", function () { put(el, f[1]); tip.remove(); if (!box.querySelector(".seo-suggestion") && box.querySelector(".seo-use-all")) box.querySelector(".seo-use-all").remove(); });
        tip.append(label, text, " ", use);
        el.closest(".field").appendChild(tip);
        offered.push(use);
      });
      if (offered.length > 1) {
        var all = document.createElement("button");
        all.type = "button";
        all.className = "button secondary seo-use-all";
        all.textContent = b.getAttribute("data-use-all");
        all.addEventListener("click", function () { offered.forEach(function (u) { if (u.isConnected) u.click(); }); all.remove(); });
        b.after(all);
      }
      var parts = [];
      if (filled.length) parts.push(b.getAttribute("data-filled").replace("{fields}", filled.join(", ")));
      if (offered.length) parts.push(b.getAttribute("data-kept"));
      var said = parts.join(" ") || b.getAttribute("data-nothing");
      status.textContent = said;
      if (window.nest && window.nest.toast) window.nest.toast(said, filled.length || offered.length ? "success" : "info");
    }).catch(function () {
      status.textContent = b.getAttribute("data-failed");
    }).finally(function () { b.disabled = false; });
  });
})();
