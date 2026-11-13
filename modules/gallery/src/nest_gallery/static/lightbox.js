// lightbox.js — opens a[data-lightbox] in a <dialog>; arrows to move, Esc to close.
// No inline script or style, so it runs under the site's strict CSP. Without
// JavaScript every thumbnail is still a link to its photo.
(() => {
  let dialog, img, caption, count, group = [], index = 0;

  function build() {
    dialog = document.createElement("dialog");
    dialog.className = "lightbox";
    dialog.setAttribute("aria-label", "Photo");
    dialog.innerHTML =
      '<figure><img alt=""><figcaption></figcaption></figure>' +
      '<div class="lightbox-bar"><button type="button" data-go="-1" aria-label="Previous">←</button>' +
      '<span class="lightbox-count"></span>' +
      '<button type="button" data-go="1" aria-label="Next">→</button>' +
      '<button type="button" data-close aria-label="Close">✕</button></div>';
    img = dialog.querySelector("img");
    caption = dialog.querySelector("figcaption");
    count = dialog.querySelector(".lightbox-count");
    dialog.addEventListener("click", (e) => {
      const go = e.target.closest("[data-go]");
      if (go) show(index + Number(go.dataset.go));
      else if (e.target.closest("[data-close]") || e.target === dialog) dialog.close();
    });
    dialog.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight") show(index + 1);
      if (e.key === "ArrowLeft") show(index - 1);
    });
    document.body.appendChild(dialog);
  }

  function show(i) {
    index = (i + group.length) % group.length;
    const link = group[index];
    const thumb = link.querySelector("img");
    img.src = link.href;
    img.alt = thumb ? thumb.alt : "";
    caption.textContent = link.dataset.caption || "";
    count.textContent = (index + 1) + " / " + group.length;
  }

  document.addEventListener("click", (e) => {
    const link = e.target.closest("a[data-lightbox]");
    if (!link || e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    if (!dialog) build();
    group = Array.from(document.querySelectorAll('a[data-lightbox="' + link.dataset.lightbox + '"]'));
    show(group.indexOf(link));
    if (!dialog.open) dialog.showModal();
  });
})();
