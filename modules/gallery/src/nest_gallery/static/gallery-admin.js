// The gallery editor: photos uploaded one at a time with their progress (dropped on the
// box or chosen), and photos put in order by dragging or by their arrows, without a
// reload (the order is saved with the form). Without this script both still work: the
// upload form sends every chosen file, the arrows save and move.
(() => {
  const upload = document.querySelector(".gallery-upload");
  const form = upload && upload.querySelector("form");
  const input = form && form.querySelector('input[type="file"]');
  const drop = form && form.querySelector(".gallery-drop");
  const list = form && form.querySelector(".gallery-progress");

  function send(file, token) {
    return new Promise((resolve) => {
      const li = document.createElement("li");
      const bar = document.createElement("progress");
      bar.max = 100; bar.value = 0;
      li.textContent = file.name + " ";
      li.append(bar);
      list.append(li);
      const data = new FormData();
      data.append("files", file, file.name);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", form.action);
      xhr.setRequestHeader("Accept", "application/json");
      // the token in a header: the server checks who is sending before it reads the file
      xhr.setRequestHeader("X-CSRF-Token", token);
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) bar.value = Math.round((e.loaded / e.total) * 100); };
      xhr.onload = () => {
        let body = {};
        try { body = JSON.parse(xhr.responseText); } catch (_) { /* a page, not JSON */ }
        const ok = xhr.status < 300 && body.added && body.added.length;
        bar.remove();
        const said = document.createElement("span");
        said.className = ok ? "ok" : "danger";
        said.textContent = ok ? upload.dataset.done : `${upload.dataset.failed}: ${(body.problems || [xhr.statusText]).join("; ")}`;
        li.append(said);
        resolve(ok);
      };
      xhr.onerror = () => { bar.remove(); li.append(` ${upload.dataset.failed}`); resolve(false); };
      xhr.send(data);
    });
  }

  async function sendAll(files) {
    const token = form.querySelector('input[name="csrf_token"]').value;
    let any = false;
    for (const file of files) any = (await send(file, token)) || any;  // one at a time
    if (any) {
      const li = document.createElement("li");
      li.textContent = upload.dataset.reload;
      list.append(li);
      location.hash = "photos";
      location.reload();
    }
  }

  if (form && window.FormData && window.XMLHttpRequest) {
    form.addEventListener("submit", (e) => {
      if (!input.files.length) return;
      e.preventDefault();
      sendAll(Array.from(input.files));
    });
    input.addEventListener("change", () => { if (input.files.length) sendAll(Array.from(input.files)); });
    ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, () => drop.classList.remove("over")));
    drop.addEventListener("drop", (e) => {
      e.preventDefault();
      const files = Array.from(e.dataTransfer.files).filter((f) => f.type.startsWith("image/"));
      if (files.length) sendAll(files);
    });
  }

  // --- the photos' order ----------------------------------------------------------------
  const rows = document.querySelector("[data-sortable]");
  if (!rows) return;
  const arrows = () => {
    const items = Array.from(rows.children);
    items.forEach((li, i) => {
      li.querySelector('button[value$=":up"]').disabled = i === 0;
      li.querySelector('button[value$=":down"]').disabled = i === items.length - 1;
    });
  };
  rows.addEventListener("click", (e) => {
    const button = e.target.closest('button[name="move"]');
    if (!button) return;
    e.preventDefault();  // moved here; saved with the form
    const li = button.closest("li");
    if (button.value.endsWith(":up") && li.previousElementSibling) li.previousElementSibling.before(li);
    if (button.value.endsWith(":down") && li.nextElementSibling) li.nextElementSibling.after(li);
    arrows();
    if (!button.disabled) button.focus(); else li.querySelector('button[name="move"]:not([disabled])')?.focus();
  });
  let dragged = null;
  rows.addEventListener("dragstart", (e) => {
    if (e.target.closest("input, textarea, button, a")) return;
    dragged = e.target.closest("li");
    dragged.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
  });
  rows.addEventListener("dragover", (e) => {
    if (!dragged) return;
    e.preventDefault();
    const over = e.target.closest("li");
    if (!over || over === dragged) return;
    const after = e.clientY > over.getBoundingClientRect().top + over.offsetHeight / 2;
    (after ? over.after(dragged) : over.before(dragged));
  });
  rows.addEventListener("dragend", () => { if (dragged) dragged.classList.remove("dragging"); dragged = null; arrows(); });
})();
