"""Proposing a page's search title, description and keywords from what it says.

Nothing is sent anywhere: the page's own text is read here. The description is its
first sentences, cut at a sentence (or a word) within what a search result shows. The
keywords are the words it uses most, weighed: a name (a word with a capital inside a
sentence: Morlaca, Vlădeasa) and a word of the title count more, names of two words
(Cetatea Bologa) are kept together, and the little words of Romanian and English
(și, care, the...) do not count. An editor reads the proposal and changes what is wrong.
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

STOP = set(
    [
        "a",
        "acea",
        "aceasta",
        "această",
        "aceea",
        "acei",
        "aceia",
        "acel",
        "acela",
        "acele",
        "acelea",
        "acest",
        "acesta",
        "aceste",
        "acestea",
        "acestei",
        "acestor",
        "acum",
        "ai",
        "aia",
        "aici",
        "al",
        "ale",
        "alt",
        "alta",
        "altă",
        "alte",
        "altfel",
        "alții",
        "am",
        "an",
        "ani",
        "anul",
        "apoi",
        "ar",
        "are",
        "as",
        "asa",
        "așa",
        "asta",
        "astăzi",
        "astfel",
        "au",
        "avea",
        "avem",
        "aveți",
        "avut",
        "azi",
        "bine",
        "ca",
        "că",
        "căci",
        "care",
        "cărei",
        "căror",
        "cărui",
        "cât",
        "câte",
        "câți",
        "către",
        "ce",
        "cea",
        "cei",
        "cel",
        "cele",
        "celor",
        "ceva",
        "chiar",
        "ci",
        "cine",
        "cineva",
        "cit",
        "cât",
        "cum",
        "cumva",
        "da",
        "dacă",
        "dar",
        "de",
        "deci",
        "deja",
        "deoarece",
        "departe",
        "deși",
        "despre",
        "din",
        "dintr",
        "dintre",
        "doar",
        "două",
        "după",
        "ea",
        "ei",
        "el",
        "ele",
        "era",
        "erau",
        "este",
        "eu",
        "fără",
        "fi",
        "fie",
        "fiecare",
        "fiind",
        "foarte",
        "for",
        "fost",
        "iar",
        "ii",
        "îi",
        "îl",
        "îmi",
        "în",
        "înainte",
        "înapoi",
        "încă",
        "între",
        "îți",
        "la",
        "le",
        "li",
        "lor",
        "lui",
        "mai",
        "mare",
        "mult",
        "multe",
        "mulți",
        "ne",
        "nici",
        "nimic",
        "noi",
        "nostru",
        "noastră",
        "nu",
        "numai",
        "o",
        "oare",
        "ori",
        "orice",
        "pe",
        "pentru",
        "peste",
        "pînă",
        "până",
        "poate",
        "pot",
        "prea",
        "prin",
        "printr",
        "puțin",
        "s",
        "sa",
        "să",
        "sale",
        "sau",
        "se",
        "si",
        "și",
        "sint",
        "sînt",
        "sunt",
        "spre",
        "sub",
        "sus",
        "ta",
        "tale",
        "te",
        "tot",
        "toată",
        "toate",
        "toți",
        "tu",
        "tău",
        "un",
        "una",
        "unde",
        "unei",
        "unele",
        "unor",
        "unui",
        "unul",
        "v",
        "va",
        "vă",
        "vor",
        "voi",
        "vom",
        "vreo",
        "vreun",
        "zi",
        "zice",
        "the",
        "of",
        "and",
        "to",
        "in",
        "is",
        "was",
        "for",
        "on",
        "with",
        "as",
        "by",
        "at",
        "from",
        "that",
        "this",
        "it",
        "an",
        "be",
        "are",
        "or",
        "which",
        "also",
        "mai",
        "nou",
        "noi",
        "lea",
        "ale",
        "lea",
        "lor",
        "lui",
        "sec",
        "secolul",
        "anii",
        "acesteia",
        "acelaşi",
        "acelasi",
        "același",
        "aceeaşi",
        "aceeași",
        "aceluiaşi",
        "aceluiași",
        "mici",
        "mare",
        "mari",
    ]
)
_WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿĂÂÎȘȚăâîșțŞŢşţ][A-Za-zÀ-ÖØ-öø-ÿĂÂÎȘȚăâîșțŞŢşţ\-]{2,}")
_SENTENCE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZĂÂÎȘȚŞŢ„\"(])")
DESCRIPTION = 155
_CAP = r"[A-ZĂÂÎȘȚŞŢ][a-zà-öø-ÿăâîșțşţ\-]{2,}"
_PAIR = re.compile(rf"\b{_CAP} {_CAP}\b")


@dataclass
class Proposal:
    title: str
    description: str
    keywords: str


def plain(markup: str) -> str:
    """Text as read: no tags, no shortcodes, no addresses."""
    text = re.sub(
        r"<(?:br|/?p|/?h[1-6]|/?li|/?div|/?td|/?th|/?tr|/?blockquote|/?figcaption|img)\b[^>]*>",
        "\n",
        markup or "",
        flags=re.I,
    )
    text = re.sub(r"<[^>]+>", "", text)  # inline tags (a letter in a <span>) are not a space
    text = re.sub(r"\[/?[A-Za-z][\w-]*(?:\s[^\]]*)?\]", " ", text)
    text = re.sub(r"https?://\S+", " ", html.unescape(text))
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def _fold(word: str) -> str:
    word = word.lower().replace("ş", "ș").replace("ţ", "ț")
    return "".join(c for c in unicodedata.normalize("NFKD", word) if not unicodedata.combining(c))


# words ending in a full stop that do not end a sentence (jud. Cluj, com. Poieni, sec. XVIII)
_ABBREVIATIONS = {
    "jud",
    "com",
    "str",
    "nr",
    "sec",
    "dr",
    "prof",
    "pr",
    "sf",
    "st",
    "ing",
    "acad",
    "pag",
    "p",
    "pp",
    "vol",
    "ed",
    "etc",
    "art",
    "cf",
    "dl",
    "dna",
    "d",
    "hr",
    "ap",
    "bl",
    "sc",
    "et",
    "al",
}


def _sentences(flat: str) -> list[str]:
    out: list[str] = []
    for part in _SENTENCE.split(flat):
        last = out[-1].rsplit(" ", 1)[-1].rstrip(".").lower() if out else ""
        if out and out[-1].endswith(".") and (last in _ABBREVIATIONS or len(last) == 1):
            out[-1] = f"{out[-1]} {part}"  # "Jud. Cluj" goes on
        else:
            out.append(part)
    return out


def description(text: str, limit: int = DESCRIPTION) -> str:
    """The first sentences, as many as a search result shows."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    out = ""
    for sentence in _sentences(flat):
        if len(sentence) < 25 and not out:  # a greeting or a heading before the text
            continue
        if len(out) + len(sentence) + 1 > limit:
            break
        out = f"{out} {sentence}".strip()
    if len(out) >= 100:  # whole sentences that say enough
        return out
    start = flat.find(out[:20]) if out else 0
    rest = flat[max(start, 0) :] if out else flat
    cut = rest[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:—-(")
    return cut + "…"


def keywords(title: str, text: str, how_many: int = 8) -> str:
    """The words the page is about, most first."""
    score: Counter[str] = Counter()
    shown: dict[str, Counter[str]] = {}

    def count(word: str, weight: float) -> None:
        key = _fold(word)
        if key in STOP or _fold(word) in STOP or len(key) < 4 or key.isdigit():
            return
        score[key] += weight
        shown.setdefault(key, Counter())[word] += 1

    for sentence in re.split(r"[.!?…\n]+", text):
        words = _WORD.findall(sentence)
        for i, w in enumerate(words):
            name = w[:1].isupper() and i > 0  # a capital inside a sentence: a name
            count(w if name else w.lower(), 2.0 if name else 1.0)
        # a name of two words, side by side (Cetatea Bologa, Crișul Repede)
        for m in _PAIR.finditer(sentence):
            if m.start() == 0 and m.group(0).split()[0] not in shown:
                continue  # the sentence's first word has its capital for being first
            key = _fold(m.group(0))
            score[key] += 3.0
            shown.setdefault(key, Counter())[m.group(0)] += 1
    for w in _WORD.findall(title or ""):
        count(w if w[:1].isupper() else w.lower(), 4.0)
    picked: list[str] = []
    for key, _s in score.most_common():
        if score[key] < 2 or len(picked) >= how_many:
            break
        word = shown[key].most_common(1)[0][0]
        if any(_same(word, p) for p in picked):
            continue  # "Cetatea Bologa" covers "Bologa", "Transilvania" covers "Transilvaniei"
        picked.append(word)
    return ", ".join(picked)


def _same(a: str, b: str) -> bool:
    fa, fb = _fold(a), _fold(b)
    if fa in fb or fb in fa:
        return True
    return min(len(fa), len(fb)) >= 6 and fa[:6] == fb[:6] and " " not in fa + fb


GENERIC = {"uncategorized", "necategorisite", "fara categorie", "diverse", "general"}


def search_title(
    title: str, context: list[str], words: list[str], site: str = "", limit: int = 60
) -> str:
    """A title for search results: the page's own, with what it is about when that fits
    (its category, else the name it speaks most of), never the site's name (added after)."""
    own = " ".join(title.split())
    if len(own) > limit:
        return own[:limit].rsplit(" ", 1)[0] + "…"
    extras = [c for c in context if _fold(c) not in GENERIC] + [w for w in words if w[:1].isupper()]
    for extra in extras:
        extra = " ".join(extra.split())
        if (
            not extra
            or _same(extra, site)
            or _fold(extra) in _fold(own)
            or _fold(own) in _fold(extra)
        ):
            continue
        candidate = f"{own} – {extra}"
        if len(candidate) <= limit:
            return candidate
    return own


_FILE = re.compile(r"^[\w.\- ]+$")
_LABEL = re.compile(r"^\s*([A-Za-z][A-Za-z ]{1,24})\s*:\s*\S")
_CAMERA = {
    "aperture",
    "camera",
    "iso",
    "focal length",
    "shutter speed",
    "orientation",
    "exposure",
    "flash",
    "make",
    "model",
    "lens",
    "created timestamp",
    "copyright",
    "credit",
}


def noise(text: str) -> bool:
    """A file's name (morlaca035 20121226 1435168974) or a camera's record (Aperture: 7.1,
    Camera: NIKON D40): left behind by an upload, not words about anything."""
    text = (text or "").strip()
    if not text:
        return True
    if _FILE.match(text) and sum(c.isdigit() for c in text) >= max(6, len(text) // 3):
        return True
    lines = [line for line in text.splitlines() if line.strip()]
    labelled = [_LABEL.match(line) for line in lines]
    if all(labelled):
        known = sum(m.group(1).strip().lower() in _CAMERA for m in labelled if m)
        return known >= max(1, len(lines) // 2)
    return False


def _sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text[-1] in ".!?…:" else text + "."


def propose(
    title: str,
    *texts: str,
    context: list[str] | None = None,
    site: str = "",
    more: list[str] | None = None,
) -> Proposal:
    """``texts`` are the page's own words (the description comes from them); ``more`` is
    what it holds besides (a category's entries), which counts for the keywords only."""
    text = "\n".join(_sentence(plain(t)) for t in texts if t and plain(t) and not noise(plain(t)))
    extra_text = "\n".join(plain(t) for t in (more or []) if t and not noise(plain(t)))
    context = [c for c in (context or []) if c.strip()]
    found = keywords(title, f"{text}\n{extra_text}")
    # its categories are what it is about too (and all a page with little text may have)
    extra = [c for c in context if _fold(c) not in GENERIC]
    words = [w for w in found.split(", ") if w]
    for c in extra:
        if not any(_same(c, w) for w in words):
            words.insert(min(len(words), 3), c)
    found = ", ".join(words[:8])
    return Proposal(
        title=search_title(title, context, found.split(", ") if found else [], site),
        description=description(text or extra_text),
        keywords=found,
    )
