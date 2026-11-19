// The content module's editor: a WYSIWYG for an entry's body, on Tiptap (ProseMirror).
//
// It takes over a <textarea data-editor> and keeps it filled with the HTML, so the form
// posts as it always did, and works as a plain textarea where scripts do not run. The
// HTML it writes is what the module's sanitizer keeps (paragraphs, headings, lists,
// links, images with their alignment, figures, tables, quotes); a paste keeps only that,
// whatever it came from. Until something is changed, the stored HTML is left exactly as
// it was, so opening an old page and saving it rewrites nothing.
//
// No style is written into the page (the site's security policy allows none): Tiptap's
// own CSS is in editor.css, alignment is a class (alignleft, aligncenter, alignright,
// the WordPress names the site's stylesheets know), tables carry no widths.

import { Editor, Node, mergeAttributes } from "@tiptap/core";
import Image from "@tiptap/extension-image";
import Subscript from "@tiptap/extension-subscript";
import Superscript from "@tiptap/extension-superscript";
import { Table, TableCell, TableHeader, TableRow } from "@tiptap/extension-table";
import { Placeholder } from "@tiptap/extensions";
import StarterKit from "@tiptap/starter-kit";

const ALIGNS = ["alignleft", "aligncenter", "alignright"];

// An image that keeps what the site's pages use: its alignment and size classes, its
// width and height (no layout shift), its title.
const SiteImage = Image.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      class: { default: null },
      width: { default: null },
      height: { default: null },
    };
  },
});

// <figure> with an image and its caption (WordPress's captioned images come as these).
const Figure = Node.create({
  name: "figure",
  group: "block",
  content: "image figcaption?",
  draggable: true,
  isolating: true,
  addAttributes() {
    return { class: { default: null } };
  },
  parseHTML() {
    return [{ tag: "figure", contentElement: (el) => el }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["figure", mergeAttributes(HTMLAttributes), 0];
  },
});

const Figcaption = Node.create({
  name: "figcaption",
  content: "inline*",
  parseHTML() {
    return [{ tag: "figcaption" }];
  },
  renderHTML() {
    return ["figcaption", 0];
  },
});

// A table without the widths Tiptap writes as style attributes.
const SiteTable = Table.extend({
  renderHTML({ HTMLAttributes }) {
    return ["table", mergeAttributes(this.options.HTMLAttributes, HTMLAttributes), ["tbody", 0]];
  },
});

// --- the toolbar ---------------------------------------------------------------------

function button(label, icon, run, isActive, isEnabled) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "ed-btn";
  b.title = label;
  b.setAttribute("aria-label", label);
  b.innerHTML = icon; // our own SVG, below
  b.addEventListener("mousedown", (e) => e.preventDefault()); // keep the selection
  b.addEventListener("click", run);
  return { el: b, isActive, isEnabled };
}

const svg = (d) =>
  `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
const text = (t) => `<span class="ed-glyph" aria-hidden="true">${t}</span>`;

const ICONS = {
  bold: text("B"),
  italic: text("<i>I</i>"),
  underline: text("<u>U</u>"),
  strike: text("<s>S</s>"),
  sub: text("x<sub>2</sub>"),
  sup: text("x<sup>2</sup>"),
  bullet: svg('<line x1="9" y1="6" x2="20" y2="6"/><line x1="9" y1="12" x2="20" y2="12"/><line x1="9" y1="18" x2="20" y2="18"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/>'),
  ordered: svg('<line x1="10" y1="6" x2="20" y2="6"/><line x1="10" y1="12" x2="20" y2="12"/><line x1="10" y1="18" x2="20" y2="18"/><path d="M4 6h1v4"/><path d="M4 10h2"/><path d="M6 18H4c0-1 2-2 2-3s-1-1.5-2-1"/>'),
  quote: svg('<path d="M6 17h3l2-4V7H5v6h3"/><path d="M14 17h3l2-4V7h-6v6h3"/>'),
  rule: svg('<line x1="3" y1="12" x2="21" y2="12"/>'),
  link: svg('<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>'),
  unlink: svg('<path d="M18.84 12.25l1.72-1.71a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M5.17 11.75l-1.71 1.71a5 5 0 0 0 7.07 7.07l1.71-1.71"/><line x1="8" y1="2" x2="8" y2="5"/><line x1="2" y1="8" x2="5" y2="8"/><line x1="16" y1="19" x2="16" y2="22"/><line x1="19" y1="16" x2="22" y2="16"/>'),
  image: svg('<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>'),
  video: svg('<rect x="2" y="5" width="20" height="14" rx="3"/><polygon points="10 9 15 12 10 15 10 9"/>'),
  table: svg('<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="12" y1="3" x2="12" y2="21"/>'),
  left: svg('<rect x="3" y="5" width="8" height="8" rx="1"/><line x1="14" y1="6" x2="21" y2="6"/><line x1="14" y1="11" x2="21" y2="11"/><line x1="3" y1="17" x2="21" y2="17"/>'),
  center: svg('<rect x="8" y="4" width="8" height="8" rx="1"/><line x1="4" y1="16" x2="20" y2="16"/><line x1="6" y1="20" x2="18" y2="20"/>'),
  right: svg('<rect x="13" y="5" width="8" height="8" rx="1"/><line x1="3" y1="6" x2="10" y2="6"/><line x1="3" y1="11" x2="10" y2="11"/><line x1="3" y1="17" x2="21" y2="17"/>'),
  alt: text("Alt"),
  caption: text("Aa"),
  undo: svg('<path d="M9 14L4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>'),
  redo: svg('<path d="M15 14l5-5-5-5"/><path d="M20 9H9a5 5 0 0 0 0 10h3"/>'),
  clear: svg('<path d="M4 7V4h16v3"/><path d="M9 20h6"/><path d="M12 4l-3 16"/><line x1="3" y1="21" x2="21" y2="3"/>'),
  source: svg('<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>'),
  full: svg('<path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/>'),
  rowAdd: text("+▭"),
  colAdd: text("+▯"),
  rowDel: text("−▭"),
  colDel: text("−▯"),
  head: text("H▭"),
  tableDel: text("✕▦"),
};

// --- the media library ---------------------------------------------------------------

function mediaDialog(L, endpoints, csrf) {
  const dialog = document.createElement("dialog");
  dialog.className = "ed-dialog ed-media";
  dialog.innerHTML = `
    <form method="dialog" class="ed-dialog-body">
      <div class="ed-dialog-head"><strong></strong><button type="submit" class="ed-btn" value="cancel" aria-label="✕">✕</button></div>
      <div class="ed-media-tools">
        <input type="search" class="ed-media-q">
        <label class="button secondary ed-upload"><input type="file" accept="image/jpeg,image/png,image/webp,image/gif" hidden><span></span></label>
      </div>
      <p class="ed-media-status muted" role="status"></p>
      <div class="ed-media-grid"></div>
      <div class="ed-media-chosen" hidden>
        <img alt="">
        <label><span></span><input class="ed-media-alt" maxlength="300"></label>
        <button type="button" class="button ed-media-insert"></button>
      </div>
    </form>`;
  dialog.querySelector(".ed-dialog-head strong").textContent = L.media;
  dialog.querySelector(".ed-media-q").placeholder = L.search;
  dialog.querySelector(".ed-upload span").textContent = L.upload;
  dialog.querySelector(".ed-media-chosen label span").textContent = L.alt;
  dialog.querySelector(".ed-media-insert").textContent = L.insert;
  document.body.appendChild(dialog);

  const grid = dialog.querySelector(".ed-media-grid");
  const status = dialog.querySelector(".ed-media-status");
  const chosenBox = dialog.querySelector(".ed-media-chosen");
  let chosen = null;
  let resolver = null;

  function choose(item) {
    chosen = item;
    chosenBox.hidden = false;
    chosenBox.querySelector("img").src = item.thumb;
    dialog.querySelector(".ed-media-alt").value = item.alt || "";
    grid.querySelectorAll(".ed-media-item").forEach((el) => el.classList.toggle("chosen", el.dataset.key === item.key));
  }

  function show(items) {
    grid.textContent = "";
    if (!items.length) status.textContent = L.noMedia;
    for (const item of items) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "ed-media-item";
      b.dataset.key = item.key;
      b.title = item.filename;
      const img = document.createElement("img");
      img.src = item.thumb;
      img.alt = item.alt || "";
      img.loading = "lazy";
      b.appendChild(img);
      b.addEventListener("click", () => choose(item));
      b.addEventListener("dblclick", () => { choose(item); insert(); });
      grid.appendChild(b);
    }
  }

  let timer = null;
  async function load(q = "") {
    status.textContent = L.loading;
    try {
      const r = await fetch(`${endpoints.list}?q=${encodeURIComponent(q)}`, { credentials: "same-origin" });
      const data = await r.json();
      status.textContent = "";
      show(data.items || []);
    } catch {
      status.textContent = L.failed;
    }
  }
  dialog.querySelector(".ed-media-q").addEventListener("input", (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => load(e.target.value.trim()), 250);
  });

  dialog.querySelector(".ed-upload input").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    status.textContent = L.uploading;
    const body = new FormData();
    body.append("file", file);
    try {
      const r = await fetch(endpoints.upload, {
        method: "POST", body, credentials: "same-origin", headers: { "x-csrf-token": csrf() },
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || L.failed);
      status.textContent = "";
      await load("");
      choose(data);
    } catch (err) {
      status.textContent = err.message || L.failed;
    }
    e.target.value = "";
  });

  function insert() {
    if (!chosen || !resolver) return;
    const alt = dialog.querySelector(".ed-media-alt").value.trim();
    resolver({ ...chosen, alt });
    resolver = null;
    dialog.close();
  }
  dialog.querySelector(".ed-media-insert").addEventListener("click", insert);
  dialog.addEventListener("close", () => { if (resolver) { resolver(null); resolver = null; } });

  return {
    pick() {
      chosen = null;
      chosenBox.hidden = true;
      dialog.querySelector(".ed-media-q").value = "";
      load("");
      dialog.showModal();
      return new Promise((resolve) => { resolver = resolve; });
    },
  };
}

// A small dialog asking for one value (a link's address, an image's alt text).
function ask(L, title, value = "", placeholder = "") {
  return new Promise((resolve) => {
    const dialog = document.createElement("dialog");
    dialog.className = "ed-dialog ed-ask";
    dialog.innerHTML = `<form method="dialog" class="ed-dialog-body">
      <label><strong></strong><input name="v"></label>
      <div class="row"><button class="button" value="ok"></button><button class="button secondary" value="cancel"></button></div></form>`;
    dialog.querySelector("strong").textContent = title;
    const input = dialog.querySelector("input");
    input.value = value;
    input.placeholder = placeholder;
    const [ok, cancel] = dialog.querySelectorAll("button");
    ok.textContent = L.ok;
    cancel.textContent = L.cancel;
    dialog.addEventListener("close", () => {
      resolve(dialog.returnValue === "ok" ? input.value.trim() : null);
      dialog.remove();
    });
    document.body.appendChild(dialog);
    dialog.showModal();
    input.select();
  });
}

function safeHref(url) {
  url = (url || "").trim();
  if (!url) return "";
  if (/^(https?:|mailto:)/i.test(url) || (url.startsWith("/") && !url.startsWith("//"))) return url;
  if (/^[\w.-]+\.[a-z]{2,}(\/|$)/i.test(url)) return "https://" + url; // "morlaca.ro/x"
  return "";
}

// --- one editor ------------------------------------------------------------------------

function mount(textarea) {
  const L = JSON.parse(textarea.dataset.labels || "{}");
  const endpoints = { list: textarea.dataset.mediaList, upload: textarea.dataset.mediaUpload };
  const form = textarea.form;
  const csrf = () => form?.querySelector('input[name="csrf_token"]')?.value || "";
  const media = endpoints.list ? mediaDialog(L, endpoints, csrf) : null;

  const box = document.createElement("div");
  box.className = "ed";
  const bar = document.createElement("div");
  bar.className = "ed-bar";
  bar.setAttribute("role", "toolbar");
  bar.setAttribute("aria-label", L.toolbar || "Editor");
  const ctx = document.createElement("div");
  ctx.className = "ed-bar ed-context";
  ctx.hidden = true;
  const surface = document.createElement("div");
  surface.className = "ed-surface entry";
  textarea.parentNode.insertBefore(box, textarea);
  box.append(bar, ctx, surface, textarea);
  textarea.classList.add("ed-source");
  textarea.hidden = true;

  let changed = false;
  const editor = new Editor({
    element: surface,
    injectCSS: false,
    content: textarea.value,
    extensions: [
      StarterKit.configure({
        heading: { levels: [2, 3, 4] },
        codeBlock: false,
        link: { openOnClick: false, autolink: true, defaultProtocol: "https", HTMLAttributes: { rel: null, target: null } },
      }),
      Subscript,
      Superscript,
      SiteImage.configure({ inline: false, allowBase64: false }),
      Figure,
      Figcaption,
      SiteTable.configure({ resizable: false }),
      TableRow,
      TableHeader,
      TableCell,
      Placeholder.configure({ placeholder: L.placeholder || "" }),
    ],
    editorProps: { attributes: { class: "body", "aria-label": L.text || "Text", role: "textbox", "aria-multiline": "true" } },
    onUpdate: ({ editor }) => {
      changed = true;
      textarea.value = editor.isEmpty ? "" : editor.getHTML();
    },
    onSelectionUpdate: refresh,
    onTransaction: refresh,
  });

  const c = () => editor.chain().focus();
  const items = [];
  const group = (target, ...buttons) => {
    const g = document.createElement("span");
    g.className = "ed-group";
    for (const b of buttons) { g.appendChild(b.el); items.push(b); }
    target.appendChild(g);
  };

  // the kind of block: paragraph or a heading
  const block = document.createElement("select");
  block.className = "ed-block";
  block.setAttribute("aria-label", L.block || "Block");
  for (const [v, t] of [["p", L.paragraph], ["2", L.h2], ["3", L.h3], ["4", L.h4]]) {
    const o = document.createElement("option");
    o.value = v;
    o.textContent = t;
    block.appendChild(o);
  }
  block.addEventListener("change", () => {
    if (block.value === "p") c().setParagraph().run();
    else c().setHeading({ level: Number(block.value) }).run();
  });
  const bg = document.createElement("span");
  bg.className = "ed-group";
  bg.appendChild(block);
  bar.appendChild(bg);

  group(bar,
    button(L.bold, ICONS.bold, () => c().toggleBold().run(), () => editor.isActive("bold")),
    button(L.italic, ICONS.italic, () => c().toggleItalic().run(), () => editor.isActive("italic")),
    button(L.underline, ICONS.underline, () => c().toggleUnderline().run(), () => editor.isActive("underline")),
    button(L.strike, ICONS.strike, () => c().toggleStrike().run(), () => editor.isActive("strike")),
    button(L.sub, ICONS.sub, () => c().toggleSubscript().run(), () => editor.isActive("subscript")),
    button(L.sup, ICONS.sup, () => c().toggleSuperscript().run(), () => editor.isActive("superscript")),
  );
  group(bar,
    button(L.bullet, ICONS.bullet, () => c().toggleBulletList().run(), () => editor.isActive("bulletList")),
    button(L.ordered, ICONS.ordered, () => c().toggleOrderedList().run(), () => editor.isActive("orderedList")),
    button(L.quote, ICONS.quote, () => c().toggleBlockquote().run(), () => editor.isActive("blockquote")),
    button(L.rule, ICONS.rule, () => c().setHorizontalRule().run()),
  );
  group(bar,
    button(L.link, ICONS.link, async () => {
      const current = editor.getAttributes("link").href || "";
      const url = await ask(L, L.linkAsk, current, "https://");
      if (url === null) return editor.commands.focus();
      const href = safeHref(url);
      if (!href) return c().extendMarkRange("link").unsetLink().run();
      if (editor.state.selection.empty && !editor.isActive("link")) {
        c().insertContent({ type: "text", text: url, marks: [{ type: "link", attrs: { href } }] }).run();
      } else {
        c().extendMarkRange("link").setLink({ href }).run();
      }
    }, () => editor.isActive("link")),
    button(L.unlink, ICONS.unlink, () => c().extendMarkRange("link").unsetLink().run(), null, () => editor.isActive("link")),
    ...(media ? [button(L.image, ICONS.image, async () => {
      const item = await media.pick();
      if (!item) return editor.commands.focus();
      c().setImage({ src: item.url, alt: item.alt || "" }).run();
    })] : []),
    button(L.video, ICONS.video, async () => {
      const url = await ask(L, L.videoAsk, "", "https://www.youtube.com/watch?v=…");
      if (!url || !/^https?:\/\/(www\.|m\.)?(youtube\.com|youtu\.be)\//.test(url)) return editor.commands.focus();
      // a YouTube address alone in a paragraph is shown as the video
      c().insertContent([{ type: "paragraph", content: [{ type: "text", text: url }] }, { type: "paragraph" }]).run();
    }),
    button(L.table, ICONS.table, () => c().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(), null, () => !editor.isActive("table")),
  );
  group(bar,
    button(L.undo, ICONS.undo, () => c().undo().run(), null, () => editor.can().undo()),
    button(L.redo, ICONS.redo, () => c().redo().run(), null, () => editor.can().redo()),
    button(L.clear, ICONS.clear, () => c().unsetAllMarks().clearNodes().run()),
  );
  const sourceBtn = button(L.source, ICONS.source, () => toggleSource(), () => !textarea.hidden);
  const fullBtn = button(L.full, ICONS.full, () => box.classList.toggle("ed-full"), () => box.classList.contains("ed-full"));
  group(bar, sourceBtn, fullBtn);

  // what a selected image or a table can be told
  const setImageClass = (align) => {
    const cls = (editor.getAttributes("image").class || "").split(/\s+/).filter((x) => x && !ALIGNS.includes(x));
    if (align) cls.push(align);
    c().updateAttributes("image", { class: cls.join(" ") || null }).run();
  };
  const imageAligned = (a) => (editor.getAttributes("image").class || "").split(/\s+/).includes(a);
  const imageOnly = [];
  const tableOnly = [];
  const ig = [
    button(L.alignLeft, ICONS.left, () => setImageClass(imageAligned("alignleft") ? null : "alignleft"), () => imageAligned("alignleft")),
    button(L.alignCenter, ICONS.center, () => setImageClass(imageAligned("aligncenter") ? null : "aligncenter"), () => imageAligned("aligncenter")),
    button(L.alignRight, ICONS.right, () => setImageClass(imageAligned("alignright") ? null : "alignright"), () => imageAligned("alignright")),
    button(L.alt, ICONS.alt, async () => {
      const alt = await ask(L, L.alt, editor.getAttributes("image").alt || "");
      if (alt !== null) c().updateAttributes("image", { alt }).run();
      else editor.commands.focus();
    }),
  ];
  const tg = [
    button(L.rowAdd, ICONS.rowAdd, () => c().addRowAfter().run()),
    button(L.colAdd, ICONS.colAdd, () => c().addColumnAfter().run()),
    button(L.rowDel, ICONS.rowDel, () => c().deleteRow().run()),
    button(L.colDel, ICONS.colDel, () => c().deleteColumn().run()),
    button(L.headRow, ICONS.head, () => c().toggleHeaderRow().run()),
    button(L.tableDel, ICONS.tableDel, () => c().deleteTable().run()),
  ];
  group(ctx, ...ig);
  group(ctx, ...tg);
  imageOnly.push(...ig);
  tableOnly.push(...tg);

  function refresh() {
    if (!editor || editor.isDestroyed) return;
    for (const b of items) {
      if (b.isActive) b.el.setAttribute("aria-pressed", b.isActive() ? "true" : "false");
      if (b.isEnabled) b.el.disabled = !b.isEnabled();
    }
    const onImage = editor.isActive("image");
    const inTable = editor.isActive("table");
    for (const b of imageOnly) b.el.hidden = !onImage;
    for (const b of tableOnly) b.el.hidden = !inTable;
    ctx.hidden = !(onImage || inTable);
    const level = editor.getAttributes("heading").level;
    block.value = editor.isActive("heading") && level ? String(level) : "p";
  }

  function toggleSource() {
    if (textarea.hidden) {
      if (changed) textarea.value = editor.isEmpty ? "" : editor.getHTML();
      textarea.hidden = false;
      surface.hidden = true;
      box.classList.add("ed-showing-source");
      textarea.focus();
    } else {
      const before = editor.getHTML();
      editor.commands.setContent(textarea.value, { emitUpdate: false });
      if (editor.getHTML() !== before) changed = true;
      textarea.hidden = true;
      surface.hidden = false;
      box.classList.remove("ed-showing-source");
      editor.commands.focus();
    }
    refresh();
  }
  // edits made in the source view are what the form posts, as written
  textarea.addEventListener("input", () => { changed = true; });

  refresh();
  textarea._editor = editor;
  return editor;
}

// The featured-image field: a "choose" button beside it, opening the same library.
function mountPicker(input) {
  const L = JSON.parse(input.dataset.labels || "{}");
  const form = input.form;
  const csrf = () => form?.querySelector('input[name="csrf_token"]')?.value || "";
  const media = mediaDialog(L, { list: input.dataset.mediaList, upload: input.dataset.mediaUpload }, csrf);
  const preview = document.createElement("img");
  preview.className = "ed-pick-preview";
  preview.alt = "";
  const choose = document.createElement("button");
  choose.type = "button";
  choose.className = "button secondary";
  choose.textContent = L.choose;
  const clear = document.createElement("button");
  clear.type = "button";
  clear.className = "button secondary";
  clear.textContent = L.remove;
  const row = document.createElement("div");
  row.className = "row ed-pick";
  input.after(row);
  row.append(preview, choose, clear);
  const show = () => {
    preview.hidden = !input.value;
    clear.hidden = !input.value;
    if (input.value) preview.src = `${input.dataset.mediaBase}/${input.value.split("/").map(encodeURIComponent).join("/")}?w=320`;
  };
  choose.addEventListener("click", async () => {
    const item = await media.pick();
    if (item) { input.value = item.key; show(); }
  });
  clear.addEventListener("click", () => { input.value = ""; show(); });
  input.addEventListener("change", show);
  show();
}

function scan(root = document) {
  root.querySelectorAll("textarea[data-editor]:not([data-editor-ready])").forEach((t) => {
    t.setAttribute("data-editor-ready", "1");
    mount(t);
  });
  root.querySelectorAll("input[data-media-pick]:not([data-editor-ready])").forEach((i) => {
    i.setAttribute("data-editor-ready", "1");
    mountPicker(i);
  });
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => scan());
else scan();
// the form comes back from htmx after a failed save: the editor goes on in the new one
document.addEventListener("htmx:afterSettle", (e) => scan(e.target));
