"""Content types and taxonomies, declared in YAML rather than in a database.

Any package of the plan, and the application last, may declare them; a later
declaration of the same name replaces the earlier one. The content module
declares ``post`` and ``page`` with ``category`` and ``post_tag``, the
WordPress set, so a site gets those unless it says otherwise::

    content_types:
      event:
        title: Events
        path: "/events/{year}/{slug}/"
        taxonomies: [category]
        revisions: 5
        fields:
          starts: {type: datetime, label: Starts, required: true}
          place:  {type: text, label: Place, max_length: 200}

A field's value is stored in the entry's JSON ``fields`` column and checked by
a Pydantic model built from these declarations (the idea of Geticus's content
fields, without a column per field).
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model, field_validator

FieldType = Literal[
    "text",
    "textarea",
    "html",
    "integer",
    "decimal",
    "boolean",
    "date",
    "datetime",
    "select",
    "url",
    "media",
    "entry",
]
_TOKENS = {"slug", "path", "category", "year", "month", "day", "id", "type"}


class TypesError(ValueError):
    pass


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldSpec(_Spec):
    type: FieldType = "text"
    label: str = ""
    help: str = ""
    required: bool = False
    max_length: int | None = None
    choices: list[str] | None = None
    default: Any = None


class TaxonomySpec(_Spec):
    title: str
    hierarchical: bool = False
    path: str = "/{taxonomy}/{slug}/"

    @field_validator("path")
    @classmethod
    def _path(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("a path starts with '/'")
        return v


class TypeSpec(_Spec):
    title: str
    path: str = "/{type}/{slug}/"
    hierarchical: bool = False
    taxonomies: list[str] = Field(default_factory=list)
    revisions: int = 10
    fields: dict[str, FieldSpec] = Field(default_factory=dict)
    template: str | None = None

    @field_validator("path")
    @classmethod
    def _path(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("a path starts with '/'")
        unknown = set(re.findall(r"\{(\w+)\}", v)) - _TOKENS
        if unknown:
            raise ValueError(f"unknown path tokens {sorted(unknown)} (known: {sorted(_TOKENS)})")
        if "{slug}" not in v and "{path}" not in v:
            raise ValueError("a path needs {slug} or {path}, so entries are told apart")
        return v

    @field_validator("fields")
    @classmethod
    def _fields(cls, v: dict[str, FieldSpec]) -> dict[str, FieldSpec]:
        for name, spec in v.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", name):
                raise ValueError(f"field '{name}' must be snake_case")
            if spec.type == "select" and not spec.choices:
                raise ValueError(f"field '{name}' is a select without choices")
        return v


class Registry:
    def __init__(self, types: dict[str, TypeSpec], taxonomies: dict[str, TaxonomySpec]):
        self.types = types
        self.taxonomies = taxonomies
        # the site's languages: the default one's text is in the records' own columns (and
        # mirrored in their text tables), the others' only in the text tables
        self.default_language = ""
        self.languages: list[str] = []
        for name, t in types.items():
            missing = [x for x in t.taxonomies if x not in taxonomies]
            if missing:
                raise TypesError(f"content type '{name}' uses undeclared taxonomies {missing}")
        self._models = {name: _fields_model(name, t) for name, t in types.items()}

    @classmethod
    def from_sections(
        cls, types: list[tuple[str, Any]], taxonomies: list[tuple[str, Any]]
    ) -> Registry:
        declared_types: dict[str, TypeSpec] = {}
        declared_tax: dict[str, TaxonomySpec] = {}
        for owner, section in taxonomies:
            for name, raw in (section or {}).items():
                declared_tax[str(name)] = _validated(TaxonomySpec, raw, f"{owner}: taxonomy {name}")
        for owner, section in types:
            for name, raw in (section or {}).items():
                declared_types[str(name)] = _validated(
                    TypeSpec, raw, f"{owner}: content type {name}"
                )
        return cls(declared_types, declared_tax)

    def type(self, name: str) -> TypeSpec:
        if name not in self.types:
            raise TypesError(f"no content type '{name}'")
        return self.types[name]

    def validate_fields(
        self, type_name: str, values: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Clean field values for storage, or the errors per field."""
        model = self._models[type_name]
        spec = self.types[type_name].fields
        given = {k: v for k, v in values.items() if k in spec and v not in ("", None)}
        try:
            data = model.model_validate(given).model_dump(mode="json")
        except ValidationError as e:
            return {}, {str(x["loc"][0]): x["msg"] for x in e.errors() if x.get("loc")}
        return {k: v for k, v in data.items() if v is not None}, {}


def _validated(model: Any, raw: Any, where: str) -> Any:
    try:
        return model.model_validate(raw)
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
        raise TypesError(f"{where}: {problems}") from None


def _fields_model(type_name: str, t: TypeSpec) -> type[BaseModel]:
    kinds: dict[str, Any] = {
        "text": str,
        "textarea": str,
        "html": str,
        "url": str,
        "media": str,
        "integer": int,
        "decimal": float,
        "boolean": bool,
        "date": dt.date,
        "datetime": dt.datetime,
        "entry": int,
    }
    fields: dict[str, Any] = {}
    for name, spec in t.fields.items():
        kind: Any = Literal[tuple(spec.choices)] if spec.type == "select" else kinds[spec.type]
        constraint = (
            Field(spec.default if not spec.required else ..., max_length=spec.max_length)
            if spec.max_length and kind is str
            else Field(spec.default if not spec.required else ...)
        )
        fields[name] = (kind if spec.required else kind | None, constraint)
    return create_model(
        f"{type_name.title()}Fields", __config__=ConfigDict(extra="ignore"), **fields
    )


def build_path(
    template: str,
    *,
    slug: str,
    entry_id: int | None,
    type_name: str,
    parent_path: str = "",
    category: str = "",
    when: dt.datetime | None = None,
) -> str:
    """An entry's address from its type's template: /{category}/{slug}/ → /istorie/biserica/."""
    when = when or dt.datetime.now()
    values = {
        "slug": slug,
        "path": f"{parent_path.strip('/')}/{slug}".strip("/") if parent_path else slug,
        "category": category or "uncategorized",
        "year": f"{when.year:04d}",
        "month": f"{when.month:02d}",
        "day": f"{when.day:02d}",
        "id": str(entry_id or ""),
        "type": type_name,
    }
    path = re.sub(r"\{(\w+)\}", lambda m: values[m.group(1)], template)
    return re.sub(r"/{2,}", "/", path)


def term_path(template: str, *, taxonomy: str, slug: str, parent_path: str = "") -> str:
    path_value = f"{parent_path.strip('/')}/{slug}".strip("/") if parent_path else slug
    path = (
        template.replace("{taxonomy}", taxonomy)
        .replace("{path}", path_value)
        .replace("{slug}", slug)
    )
    return re.sub(r"/{2,}", "/", path)
