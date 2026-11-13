"""Forms: a Pydantic model in, what a page needs out.

class TermForm(Form):
    word: str = Field(max_length=80)
    definition: str = Field(min_length=10)
    public: bool = False

@router.post("/terms")
async def create(request: Request):
    form = await read(request, TermForm)
    if not form.ok:
        return render(request, "glossary/edit.html", form=form, fragment="form")
    save(form.data)
    ...

# in the template
{% import "forms/fields.html" as f %}
{{ f.field(form, "word", _("Word"), required=True) }}
"""

from __future__ import annotations

import types
import typing
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from nest.i18n import Translator, translator


class Form(BaseModel):
    """The base of every form: text is trimmed, unknown fields are ignored."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")


@dataclass
class Submission[F: BaseModel]:
    """A form as a page shows it: values as typed, a message per field, or the data."""

    data: F | None = None
    values: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.data is not None and not self.errors

    def error(self, name: str) -> str | None:
        return self.errors.get(name)


def _is_list(annotation: Any) -> bool:
    origin = typing.get_origin(annotation)
    if origin in (list, set, tuple, frozenset):
        return True
    if origin in (typing.Union, types.UnionType):
        return any(_is_list(arg) for arg in typing.get_args(annotation))
    return False


def _is_bool(annotation: Any) -> bool:
    if annotation is bool:
        return True
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        return bool in typing.get_args(annotation)
    return False


def _gather(model: type[BaseModel], raw: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """The fields as the model reads them, and the values to show again."""
    data: dict[str, Any] = {}
    shown: dict[str, Any] = {}
    getlist = getattr(raw, "getlist", None)
    for name, info in model.model_fields.items():
        key = info.alias or name
        if _is_list(info.annotation):
            items = getlist(key) if getlist else raw.get(key, [])
            items = [
                v for v in (items if isinstance(items, list) else [items]) if v not in ("", None)
            ]
            shown[name] = items
            if items:
                data[name] = items
            continue
        value = raw.get(key)
        if _is_bool(info.annotation):
            # An unticked checkbox is not sent at all: absence is False.
            checked = value not in (None, "", "0", "false", "off")
            shown[name] = checked
            data[name] = checked
            continue
        if isinstance(value, str):
            shown[name] = value
            if value.strip() == "":
                continue  # blank is "not given": a required field says so
        elif value is not None:
            shown[name] = value
        if value is not None:
            data[name] = value
    return data, shown


def _message(err: Mapping[str, Any], t: Translator) -> str:
    kind = err.get("type", "")
    ctx = err.get("ctx") or {}
    if kind == "missing":
        return t("This field is required.")
    if kind == "string_too_short":
        return t.ngettext(
            "Use at least {n} character.",
            "Use at least {n} characters.",
            int(ctx.get("min_length", 0)),
        )
    if kind == "string_too_long":
        return t.ngettext(
            "Use at most {n} character.",
            "Use at most {n} characters.",
            int(ctx.get("max_length", 0)),
        )
    if kind in ("int_parsing", "int_type", "int_from_float"):
        return t("Enter a whole number.")
    if kind in ("float_parsing", "float_type", "decimal_parsing"):
        return t("Enter a number.")
    if kind in ("greater_than_equal", "greater_than"):
        return t("Enter {n} or more.", n=ctx.get("ge", ctx.get("gt")))
    if kind in ("less_than_equal", "less_than"):
        return t("Enter {n} or less.", n=ctx.get("le", ctx.get("lt")))
    if kind in ("literal_error", "enum"):
        return t("Choose one of the options.")
    if kind == "string_pattern_mismatch":
        return t("This is not in the expected form.")
    if kind in ("too_short",):
        return t("Choose at least one.")
    if kind == "value_error":
        # A validator's own message, written in English and translated here.
        return t(str(err.get("msg", "")).removeprefix("Value error, "))
    return t("This value is not valid.")


def validate[F: BaseModel](model: type[F], raw: Any, t: Translator | None = None) -> Submission[F]:
    """Validate submitted fields (a dict or form data) against ``model``."""
    t = t or Translator("en", {})
    data, shown = _gather(model, raw)
    try:
        return Submission(data=model.model_validate(data), values=shown)
    except ValidationError as e:
        errors: dict[str, str] = {}
        for err in e.errors():
            loc = err.get("loc") or ()
            name = str(loc[0]) if loc else "__all__"
            errors.setdefault(name, _message(err, t))
        return Submission(values=shown, errors=errors)


async def read[F: BaseModel](request: Any, model: type[F]) -> Submission[F]:
    """Read and validate the request's form, with messages in the visitor's language."""
    return validate(model, await request.form(), translator(request))


def blank[F: BaseModel](model: type[F] | None = None, **initial: Any) -> Submission[F]:
    """A form not yet submitted, optionally filled with initial values."""
    return Submission(values=dict(initial))
