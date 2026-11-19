// The content module's videos: a play link becomes YouTube's player (the nocookie one)
// only when a reader plays it, so a page that holds a video asks nothing of YouTube
// until then. The link stays a link where scripts do not run.
(function () {
  "use strict";
  document.addEventListener("click", function (e) {
    var link = e.target.closest && e.target.closest("figure.video > a.video-play");
    if (!link || e.ctrlKey || e.metaKey || e.shiftKey) return;
    var id = link.parentNode.getAttribute("data-video") || "";
    if (!/^[\w-]{11}$/.test(id)) return;
    e.preventDefault();
    var frame = document.createElement("iframe");
    frame.src = "https://www.youtube-nocookie.com/embed/" + id + "?autoplay=1&rel=0";
    frame.title = link.textContent.trim();
    frame.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
    frame.setAttribute("allowfullscreen", "");
    frame.referrerPolicy = "strict-origin-when-cross-origin";
    link.replaceWith(frame);
  });
})();
