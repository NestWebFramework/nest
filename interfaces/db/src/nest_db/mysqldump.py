"""Reading a mysqldump file without a MySQL server.

The PHP sites being moved to Nest (WordPress, Glossword, Geticus) come as
``mysqldump`` files. This reads one as data: each table's column names from
its ``CREATE TABLE``, and its rows from the ``INSERT INTO ... VALUES (...),
(...);`` statements, with MySQL's string escapes decoded. Nothing is executed;
a value is a ``str``, an ``int``, a ``float``, ``bytes`` (for ``0x...``) or None.

    dump = Dump.read(Path("morlaca.sql"))
    for post in dump.rows("wp_posts"):
        print(post["post_title"])
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_CREATE = re.compile(r"CREATE TABLE `([^`]+)` \((.*?)\n\)[^;]*;", re.S)
_COLUMN = re.compile(r"^\s*`([^`]+)`\s", re.M)
_INSERT = re.compile(r"INSERT INTO `([^`]+)`(?:\s*\(([^)]*)\))?\s+VALUES\s*", re.I)
_ESCAPES = {"0": "\0", "b": "\b", "n": "\n", "r": "\r", "t": "\t", "Z": "\x1a"}


class DumpError(ValueError):
    pass


@dataclass
class Dump:
    text: str
    columns: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def read(cls, path: Path, encoding: str = "utf-8") -> Dump:
        return cls.parse(Path(path).read_text(encoding=encoding, errors="replace"))

    @classmethod
    def parse(cls, text: str) -> Dump:
        dump = cls(text)
        for name, body in _CREATE.findall(text):
            dump.columns[name] = _COLUMN.findall(body)
        return dump

    def tables(self) -> list[str]:
        return sorted(self.columns)

    def rows(self, table: str) -> Iterator[dict[str, Any]]:
        """Every row of ``table``, as a mapping of column name to value."""
        for match in _INSERT.finditer(self.text):
            if match.group(1) != table:
                continue
            names = (
                [c.strip().strip("`") for c in match.group(2).split(",")]
                if match.group(2)
                else self.columns.get(table)
            )
            if not names:
                raise DumpError(f"{table}: no CREATE TABLE and no column list to name its values")
            for values in _tuples(self.text, match.end()):
                if len(values) != len(names):
                    raise DumpError(
                        f"{table}: a row has {len(values)} values for {len(names)} columns"
                    )
                yield dict(zip(names, values, strict=True))


def _tuples(text: str, pos: int) -> Iterator[list[Any]]:
    """The value tuples of one INSERT, from ``pos`` up to its closing semicolon."""
    n = len(text)
    while pos < n:
        while pos < n and text[pos] in " \t\r\n,":
            pos += 1
        if pos >= n or text[pos] == ";":
            return
        if text[pos] != "(":
            raise DumpError(f"expected '(' at offset {pos}")
        pos += 1
        row: list[Any] = []
        while True:
            while text[pos] in " \t\r\n":
                pos += 1
            ch = text[pos]
            if ch == "'":
                value, pos = _string(text, pos + 1)
            else:
                end = pos
                while text[end] not in ",)":
                    end += 1
                value = _literal(text[pos:end].strip())
                pos = end
            row.append(value)
            while text[pos] in " \t\r\n":
                pos += 1
            if text[pos] == ",":
                pos += 1
                continue
            if text[pos] == ")":
                pos += 1
                break
            raise DumpError(f"unexpected {text[pos]!r} at offset {pos}")
        yield row


def _string(text: str, pos: int) -> tuple[str, int]:
    out: list[str] = []
    start = pos
    while True:
        ch = text[pos]
        if ch == "\\":
            out.append(text[start:pos])
            nxt = text[pos + 1]
            out.append(_ESCAPES.get(nxt, nxt))  # \' \" \\ \% \_ stand for themselves
            pos += 2
            start = pos
        elif ch == "'":
            if text[pos + 1 : pos + 2] == "'":  # '' is a quote
                out.append(text[start : pos + 1])
                pos += 2
                start = pos
                continue
            out.append(text[start:pos])
            return "".join(out), pos + 1
        else:
            pos += 1


def _literal(token: str) -> Any:
    if token.upper() == "NULL":
        return None
    if token.lower().startswith("0x"):
        return bytes.fromhex(token[2:])
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        return token
