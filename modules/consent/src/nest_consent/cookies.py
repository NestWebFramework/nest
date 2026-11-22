"""The cookies a site sets, their purposes, and the visitor's choice.

Purposes, as the EU's rules sort them: ``necessary`` (the site cannot work without: the
CSRF token, a signed-in editor's session; set without asking), ``preferences`` (what the
visitor chose to keep: the language, a game's progress), ``statistics`` (counting visits),
``marketing`` (advertising). Only the last three are asked for.

The choice is the cookie ``nest_consent``: the purposes allowed, and a short fingerprint of
the cookies that needed consent when the visitor chose. When a module adds one, the
fingerprint changes and the visitor is asked again.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlencode

PURPOSES = ("necessary", "preferences", "statistics", "marketing")
ASKED = PURPOSES[1:]
COOKIE = "nest_consent"

# Nest's own cookies, and those of Nest's modules, declared for them (a module may also
# answer "consent.cookies" itself; an answer naming the same cookie wins)
CORE = [
    {
        "name": "nest_csrf",
        "purpose": "necessary",
        "duration": "session",
        "description": "Keeps the site's forms safe.",
    },
    {
        "name": "nest_locale",
        "purpose": "necessary",
        "duration": "1 year",
        "description": "Remembers the language you chose.",
    },
    {
        "name": COOKIE,
        "purpose": "necessary",
        "duration": "the setting's days",
        "description": "Remembers your choice about cookies.",
    },
]
MODULES = {
    "auth": [
        {
            "name": "nest_session",
            "purpose": "necessary",
            "duration": "the session's days",
            "description": "Keeps you signed in, if you have an account.",
        }
    ],
    "admin": [
        {
            "name": "nest_admin_locale",
            "purpose": "necessary",
            "duration": "1 year",
            "description": "Remembers the admin panel's language, for editors.",
        },
        {
            "name": "nest_theme_preview",
            "purpose": "necessary",
            "duration": "1 hour",
            "description": "Shows editors a theme they are trying out.",
        },
    ],
    "hangman": [
        {
            "name": "nest_hangman",
            "purpose": "preferences",
            "duration": "1 year",
            "description": "Remembers your game and its score.",
        }
    ],
}


@dataclass
class Cookie:
    name: str
    purpose: str
    duration: str
    description: str
    owner: str
    provider: str = ""
    service: str = (
        ""  # what the visitor allows or refuses as one (a module's feature); default: its owner
    )

    @property
    def key(self) -> str:
        return self.service or self.owner


def declared(host: Any) -> list[Cookie]:
    """Every cookie the application sets as it is configured now, by purpose."""
    found: dict[str, Cookie] = {}

    def add(owner: str, rows: Any) -> None:
        for r in rows or []:
            if not isinstance(r, dict) or not r.get("name"):
                continue
            purpose = r.get("purpose") if r.get("purpose") in PURPOSES else "necessary"
            found[str(r["name"])] = Cookie(
                str(r["name"]),
                purpose,
                str(r.get("duration") or ""),
                str(r.get("description") or ""),
                str(r.get("owner") or owner),
                str(r.get("provider") or ""),
                str(r.get("service") or ""),
            )

    add("nest", CORE)
    for module, rows in MODULES.items():
        if host.has_module(module):
            add(module, rows)
    for rows in host.gather("consent.cookies"):
        add("", rows)
    return sorted(found.values(), key=lambda c: (PURPOSES.index(c.purpose), c.owner, c.name))


def fingerprint(cookies: list[Cookie]) -> str:
    """What needs consent now: a choice made for something else is asked again."""
    asked = sorted(f"{c.name}:{c.purpose}:{c.key}" for c in cookies if c.purpose in ASKED)
    return hashlib.sha256("|".join(asked).encode()).hexdigest()[:10] if asked else ""


@dataclass
class Choice:
    fingerprint: str = ""
    allowed: set[str] = field(default_factory=set)  # purposes
    refused: set[str] = field(default_factory=set)  # services refused within the purposes allowed

    def encode(self) -> str:
        data = {"v": self.fingerprint, "ok": ",".join(sorted(self.allowed & set(ASKED)))}
        if self.refused:
            data["no"] = ",".join(sorted(self.refused))
        return urlencode(data)

    @classmethod
    def decode(cls, value: str | None) -> Choice | None:
        if not value:
            return None
        try:
            data = parse_qs(value, strict_parsing=False)
        except ValueError:
            return None
        ok = {p for p in (data.get("ok", [""])[0] or "").split(",") if p in ASKED}
        no = {x for x in (data.get("no", [""])[0] or "").split(",") if x}
        return cls(data.get("v", [""])[0], ok, no)


@dataclass
class State:
    """What a page knows: the cookies, the visitor's choice, whether to ask."""

    cookies: list[Cookie]
    choice: Choice | None
    current: str  # the fingerprint now

    @property
    def needed(self) -> list[str]:
        """The purposes some cookie of this site needs consent for."""
        return [p for p in ASKED if any(c.purpose == p for c in self.cookies)]

    @property
    def ask(self) -> bool:
        return bool(self.needed) and (
            self.choice is None or self.choice.fingerprint != self.current
        )

    def allowed(self, purpose: str, service: str = "") -> bool:
        """Whether the visitor allowed ``purpose`` (and, when given, that ``service`` of it)."""
        if purpose == "necessary":
            return True
        ok = (
            bool(self.choice)
            and self.choice.fingerprint == self.current
            and purpose in self.choice.allowed
        )
        return ok and not (service and service in self.choice.refused)

    def services(self, purpose: str) -> list[tuple[str, list[Cookie]]]:
        """The services of a purpose, each with its cookies (a switch each, when more than one)."""
        out: dict[str, list[Cookie]] = {}
        for c in self.cookies:
            if c.purpose == purpose:
                out.setdefault(c.key, []).append(c)
        return list(out.items())

    def by_purpose(self) -> dict[str, list[Cookie]]:
        out: dict[str, list[Cookie]] = {}
        for c in self.cookies:
            out.setdefault(c.purpose, []).append(c)
        return out
