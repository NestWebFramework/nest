"""Translations: JSON catalogs from every package, plural forms, a language per visitor.

A package lists its catalogs in module.yml, so an unfinished translation stays
out until it is listed:

    locales:
      - {locale: ro, file: locales/ro.json}

A catalog maps the English text to its translation; a plural is a list with one
form per plural category of the language (Romanian has three)::

    {"Wrong email or password.": "Email sau parolă greșită.",
     "{n} term": ["{n} termen", "{n} termeni", "{n} de termeni"]}

Catalogs merge in start order and the application's own come last, so an
application can reword any module. A visitor's language is their choice
(a cookie), else the best match of Accept-Language, else the default.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

log = logging.getLogger("nest.i18n")

LOCALE_COOKIE = "nest_locale"  # the language a visitor reads the site in
ADMIN_LOCALE_COOKIE = "nest_admin_locale"  # the language an editor reads the admin panel in

# Plural category index per language (CLDR rules for cardinal numbers).
PLURALS: dict[str, Callable[[int], int]] = {
    "en": lambda n: 0 if n == 1 else 1,
    "de": lambda n: 0 if n == 1 else 1,
    "it": lambda n: 0 if n == 1 else 1,
    "es": lambda n: 0 if n == 1 else 1,
    "fr": lambda n: 0 if n in (0, 1) else 1,
    "ro": lambda n: 0 if n == 1 else (1 if n == 0 or 1 <= n % 100 <= 19 else 2),
    "hu": lambda n: 0 if n == 1 else 1,
}

Entry = str | list[str]


class I18nError(Exception):
    pass


def _primary(tag: str) -> str:
    return tag.split("-")[0].split("_")[0].lower()


class Translator:
    """One language's view of the catalogs."""

    def __init__(self, locale: str, messages: dict[str, Entry]):
        self.locale = locale
        self._messages = messages
        self._plural = PLURALS.get(_primary(locale), PLURALS["en"])

    @staticmethod
    def _format(text: str, params: dict[str, Any]) -> str:
        if not params:
            return text
        try:
            return text.format(**params)
        except (KeyError, IndexError, ValueError):
            log.warning("cannot fill %r with %s", text, sorted(params))
            return text

    def gettext(self, message: str, **params: Any) -> str:
        entry = self._messages.get(message, message)
        if isinstance(entry, list):
            entry = entry[0] if entry else message
        return self._format(entry, params)

    __call__ = gettext

    def scoped(self, scope: str) -> tuple[Callable[..., str], Callable[..., str]]:
        """gettext and ngettext for one module's templates: an application's catalog may
        reword that module alone ("messages::Messages": "Letters"), else the text as anywhere."""

        def gettext(message: str, **params: Any) -> str:
            key = f"{scope}::{message}"
            if key in self._messages:
                return self.gettext(key, **params)
            return self.gettext(message, **params)

        def ngettext(singular: str, plural: str, n: int, **params: Any) -> str:
            key = f"{scope}::{singular}"
            if key in self._messages:
                return self.ngettext(key, plural, n, **params)
            return self.ngettext(singular, plural, n, **params)

        return gettext, ngettext

    def ngettext(self, singular: str, plural: str, n: int, **params: Any) -> str:
        entry = self._messages.get(singular)
        if isinstance(entry, list) and entry:
            text = entry[min(self._plural(n), len(entry) - 1)]
        elif isinstance(entry, str):
            text = entry
        else:
            text = singular if n == 1 else plural
        return self._format(text, {"n": n, **params})


class Catalogs:
    def __init__(self, languages: Iterable[str], default: str):
        self.languages = list(dict.fromkeys(languages)) or [default]
        if default not in self.languages:
            raise I18nError(f"the default language '{default}' is not among {self.languages}")
        self.default = default
        self._messages: dict[str, dict[str, Entry]] = {lang: {} for lang in self.languages}
        self._translators: dict[str, Translator] = {}

    def load(self, owner: str, locale: str, path: Path) -> None:
        if locale not in self._messages:
            return  # a language this application does not offer
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise I18nError(f"{owner}: catalog {path} is listed but missing") from None
        except json.JSONDecodeError as e:
            raise I18nError(f"{owner}: catalog {path} is not valid JSON: {e}") from None
        if not isinstance(data, dict):
            raise I18nError(f"{owner}: catalog {path} must be a JSON object")
        for key, value in data.items():
            ok = isinstance(value, str) or (
                isinstance(value, list) and value and all(isinstance(v, str) for v in value)
            )
            if not isinstance(key, str) or not ok:
                raise I18nError(f"{owner}: {path}: '{key}' must map to text or a list of texts")
        self._messages[locale].update(data)
        self._translators.pop(locale, None)

    def translator(self, locale: str | None = None) -> Translator:
        locale = locale if locale in self._messages else self.default
        if locale not in self._translators:
            self._translators[locale] = Translator(locale, self._messages[locale])
        return self._translators[locale]

    def negotiate(
        self, chosen: str | None, accept_language: str | None, among: list[str] | None = None
    ) -> str:
        """The language for a request: the one chosen, else the browser's best, among
        ``among`` (the site's, or the admin panel's) or all."""
        offered = among or self.languages
        if chosen in self._messages and chosen in offered:
            return chosen
        ranked: list[tuple[float, int, str]] = []
        for i, part in enumerate((accept_language or "").split(",")):
            tag, _, rest = part.strip().partition(";")
            if not tag or tag == "*":
                continue
            q = 1.0
            if rest.strip().startswith("q="):
                try:
                    q = float(rest.strip()[2:])
                except ValueError:
                    q = 0.0
            ranked.append((-q, i, tag.lower()))
        for _q, _i, tag in sorted(ranked):
            for lang in offered:
                if lang.lower() == tag or _primary(lang) == _primary(tag):
                    return lang
        return self.default if self.default in offered else offered[0]


class LocaleMiddleware:
    """Puts ``locale`` and ``translator`` on every request's state: in the admin panel
    (a path under ``admin_root()``), the editor's admin language; elsewhere the site's."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        catalogs: Catalogs,
        site: list[str] | None = None,
        admin: list[str] | None = None,
        admin_root: Any = None,
        browser: bool = True,
    ):
        self.app = app
        self.catalogs = catalogs
        self.site = site or catalogs.languages
        self.admin = admin or self.site
        self.admin_root = admin_root or (lambda: None)
        self.browser = browser

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            chosen = accept = admin_chosen = None
            for key, value in scope.get("headers", []):
                if key == b"accept-language":
                    accept = value.decode("latin-1")[:500]
                elif key == b"cookie":
                    for part in value.decode("latin-1").split(";"):
                        name, _, val = part.strip().partition("=")
                        if name == LOCALE_COOKIE:
                            chosen = val
                        elif name == ADMIN_LOCALE_COOKIE:
                            admin_chosen = val
            root = self.admin_root()
            path = scope.get("path", "")
            in_admin = bool(root) and (path == root or path.startswith(root.rstrip("/") + "/"))
            from_address = scope.get("state", {}).get("url_locale")  # /en/... (LanguageURLs)
            if in_admin:
                locale = self.catalogs.negotiate(admin_chosen or chosen, accept, self.admin)
            elif from_address:
                locale = from_address
            else:
                # the site: the browser's language, or (browser_language: false, for a
                # public site) its default until a visitor chooses: one address serving two
                # languages confuses search engines, whose crawler asks in English
                locale = self.catalogs.negotiate(
                    chosen, accept if self.browser else None, self.site
                )
            state = scope.setdefault("state", {})
            state["in_admin"] = in_admin
            state["locale"] = locale
            state["translator"] = self.catalogs.translator(locale)
        await self.app(scope, receive, send)


def translator(request: Any) -> Translator:
    """The translator for this request's visitor: ``t = translator(request); t("Saved.")``."""
    found = getattr(request.state, "translator", None)
    if found is not None:
        return found
    return request.app.state.nest.catalogs.translator()


# A language's own name for itself, for switches and the admin panel's lists.
LANGUAGE_NAMES = {
    "ro": "Română", "en": "English", "hu": "Magyar", "de": "Deutsch", "fr": "Français",
    "it": "Italiano", "es": "Español", "uk": "Українська", "pl": "Polski", "bg": "Български",
    "sr": "Српски", "sk": "Slovenčina", "cs": "Čeština", "pt": "Português", "nl": "Nederlands",
}  # fmt: skip


def language_name(code: str) -> str:
    """``ro`` → ``Română``; a code it does not know, as it is."""
    return LANGUAGE_NAMES.get(code, code)
