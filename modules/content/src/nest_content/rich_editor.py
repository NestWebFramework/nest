"""The rich text editor (Tiptap, editor/src) for any admin form: ``rich_editor()`` in a
template gives what loads it (``head``), the attributes a ``<textarea data-editor>``
needs (``attrs``: its words in the page's language and where pictures are listed and
uploaded) and those words (``labels``, for a picture picker). A module that wants it uses
it when it is defined, so it never depends on this one: without it, a plain textarea."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from markupsafe import Markup, escape


def labels(_: Any) -> dict[str, str]:
    """The editor's words, in the page's language."""
    return {
        "toolbar": _("Formatting"), "text": _("Text"), "placeholder": _("Write here…"),
        "block": _("Paragraph style"), "paragraph": _("Paragraph"), "h2": _("Heading"),
        "h3": _("Subheading"), "h4": _("Small heading"), "bold": _("Bold"),
        "italic": _("Italic"), "underline": _("Underline"), "strike": _("Strikethrough"),
        "sub": _("Subscript"), "sup": _("Superscript"), "bullet": _("Bulleted list"),
        "ordered": _("Numbered list"), "quote": _("Quote"), "rule": _("Dividing line"),
        "link": _("Link"), "unlink": _("Remove link"), "linkAsk": _("The link's address"),
        "image": _("Picture"), "video": _("Video"), "videoAsk": _("The video's YouTube address"),
        "table": _("Table"), "undo": _("Undo"), "redo": _("Redo"),
        "clear": _("Clear formatting"), "source": _("HTML"), "full": _("Full screen"),
        "alignLeft": _("Picture on the left"), "alignCenter": _("Picture centred"),
        "alignRight": _("Picture on the right"),
        "spotlight": _("Emphasize: framed, opens large; side by side, a mini-gallery"),
        "alt": _("Description of the picture (for those who cannot see it)"),
        "rowAdd": _("Add a row"), "colAdd": _("Add a column"), "rowDel": _("Delete the row"),
        "colDel": _("Delete the column"), "headRow": _("Header row"),
        "tableDel": _("Delete the table"), "media": _("Pictures"), "search": _("Search pictures"),
        "upload": _("Upload a picture"), "insert": _("Insert"), "noMedia": _("No pictures yet."),
        "loading": _("Loading…"), "uploading": _("Uploading…"),
        "failed": _("That did not work; try again."), "ok": _("OK"), "cancel": _("Cancel"),
        "choose": _("Choose a picture"), "remove": _("Remove"),
    }  # fmt: skip


@dataclass(frozen=True)
class RichEditor:
    head: Markup
    attrs: Markup
    labels: dict[str, str]
    media_list: str
    media_upload: str


def rich_editor(_: Any, asset: Any, admin_root: str | None) -> RichEditor:
    words = labels(_)
    root = admin_root or ""
    media_list, media_upload = f"{root}/content/media.json", f"{root}/content/media"
    head = Markup(
        f'<link rel="stylesheet" href="{escape(asset("content", "editor/editor.css"))}">\n'
        f'<script src="{escape(asset("content", "editor/editor.js"))}" defer></script>'
    )
    attrs = Markup(
        f'data-labels="{escape(json.dumps(words, ensure_ascii=False))}" '
        f'data-media-list="{escape(media_list)}" data-media-upload="{escape(media_upload)}"'
    )
    return RichEditor(head, attrs, words, media_list, media_upload)
