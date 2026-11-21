"""What the application's modules translate: every ``translatable:`` in their manifests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Text


class TranslationsError(Exception):
    """A problem to tell an editor: ``message`` (to translate) with its ``params``."""

    def __init__(self, message: str, **params: Any):
        self.message, self.params = message, params
        super().__init__(message.format(**params) if params else message)


@dataclass(frozen=True)
class Kind:
    subject: str  # "content.entry": the module, then its kind of record
    module: str
    name: str
    model: type  # its text table
    label: str
    fields: dict[str, str]  # field → how it is edited: text, slug, textarea, html
    title: str  # the field that names a record in lists
    edit: str | None  # its own editor, "{admin}/content/entries/{id}"

    @property
    def unique(self) -> tuple[str, ...]:
        return tuple(self.model.__text_unique__)

    def edit_url(self, admin_root: str | None, owner_id: Any) -> str | None:
        if not self.edit:
            return None
        return self.edit.format(admin=admin_root or "", id=owner_id)


def _how(model: type, field: str) -> str:
    if field == "slug":
        return "slug"
    column = model.__table__.columns[field]
    return "textarea" if isinstance(column.type, Text) else "text"


def discover(manifests: list[Any], load: Callable[[str, str], Any]) -> dict[str, Kind]:
    """Every kind of record the given packages translate, by subject (``load(package,
    ref)`` finds a text table); a declaration that does not hold stops the start, saying
    which and why."""
    found: dict[str, Kind] = {}
    for manifest in manifests:
        for name, spec in manifest.translatable.items():
            subject = f"{manifest.name}.{name}"
            try:
                model = load(manifest.name, spec.model)
            except Exception as e:  # noqa: BLE001 - whatever stops it, said with its name
                raise TranslationsError(
                    "{subject}: its text table {model} cannot be found ({error})",
                    subject=subject,
                    model=spec.model,
                    error=e,
                ) from e
            own = getattr(model, "__text_fields__", None)
            if not own:
                raise TranslationsError(
                    "{subject}: {model} is not a text table (nest_db.text_table)",
                    subject=subject,
                    model=spec.model,
                )
            fields = dict(spec.fields) or {f: _how(model, f) for f in own}
            unknown = sorted(set(fields) - set(own))
            if unknown:
                raise TranslationsError(
                    "{subject}: {model} has no field {fields}",
                    subject=subject,
                    model=spec.model,
                    fields=", ".join(unknown),
                )
            title = spec.title or next(iter(fields))
            if title not in own:
                raise TranslationsError(
                    "{subject}: its title field {title} is not one of the table's",
                    subject=subject,
                    title=title,
                )
            found[subject] = Kind(
                subject=subject,
                module=manifest.name,
                name=name,
                model=model,
                label=spec.label or name.replace("_", " ").capitalize(),
                fields=fields,
                title=title,
                edit=spec.edit,
            )
    return found
