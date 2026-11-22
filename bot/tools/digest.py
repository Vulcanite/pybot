"""The extractive reading of web text: which sentences to say back, chosen by rule.

No model writes anything here. A snippet is cleaned of page furniture (markdown headings,
tables, list bullets, image and link markup, "..." joins), split into sentences, and each
sentence is scored by how many of the question's content words it holds, with a small bonus for
a figure when the question asks for one. The best one or two are said back in page order.
"""
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

STOP = frozenset("""
a an the and or but if then than that this these those there here it its i me my we our us you
your he him his she her they them their is are was were be been being do does did have has had
will would shall should can could may might must not no so too very just also as at by for from
in into of off on onto out over under up with about after again all any both each few more most
other some such own same what which who whom whose when where why how please search look find
google web online internet latest news today now tell show give me get know
""".split())

_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_BARE_URL = re.compile(r"https?://\S+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_FIGURE_ASK = re.compile(r"\b(?:how (?:many|much|old|long|far|tall|big)|when|what year|"
                         r"population|price|cost|score|rate)\b", re.I)


def words(text):
    return [w for w in _WORD.findall(text.lower()) if w not in STOP and len(w) > 1]


def stems(text):
    """Content words cut to a rough stem, so "descale", "descaling" and "descaler" meet."""
    return {w[:5] if len(w) > 5 else w for w in words(text)}


# A sentence that is a caveat or an aside rather than the answer: "Note: ...", "If ...".
_ASIDE = re.compile(r"^(?:note|tip|remember|warning|disclaimer|if|however|also)\b", re.I)


def clean(snippet):
    """A highlight or page text with the page furniture taken out, as plain running text."""
    kept = []
    for line in snippet.replace("\r", "").split("\n"):
        line = line.strip()
        if not line or line.startswith(("|", "#", "---", "```", "table")) or line == "...":
            # A heading is a label, not a sentence; a table row has no sentence to say.
            if line.startswith("#"):
                kept.append("\n")
            continue
        line = re.sub(r"^(?:[-*+•]|\d+[.)])\s+", "", line)
        line = _MD_IMAGE.sub("", line)
        line = _MD_LINK.sub(r"\1", line)
        line = _BARE_URL.sub("", line)
        line = line.replace("**", "").replace("__", "").replace("`", "").strip()
        if not line or line.endswith(":"):
            continue  # a lead-in to a list ("Pay attention to:") says nothing by itself
        if not re.search(r"[.!?][\"')\]]?$", line):
            # A list item or a caption: a sentence of its own when it is long enough to be one,
            # so it is not run into the next line as one long "sentence".
            if len(line.split()) < 6:
                continue
            line += "."
        kept.append(line)
    text = " ".join(kept).replace(" ... ", " ").replace("...", " ")
    return " ".join(text.split())


def sentences(text):
    out = []
    for part in _SENTENCE_END.split(text):
        part = part.strip()
        # Too short to say anything, or too long to be one sentence of prose.
        if 25 <= len(part) <= 400 and len(part.split()) >= 5:
            out.append(part)
    return out


def best_sentences(question, snippets, limit=2, max_chars=360):
    """The sentences from snippets that answer question best, in the order they were written."""
    asked = stems(question)
    wants_figure = bool(_FIGURE_ASK.search(question))
    scored = []
    order = 0
    for snippet in snippets:
        for sentence in sentences(clean(snippet)):
            have = stems(sentence)
            score = len(asked & have) * 2.0
            if wants_figure and re.search(r"\d", sentence):
                score += 1.5
            if _ASIDE.match(sentence):
                score -= 1.0
            score -= len(sentence) / 400.0  # the shorter of two equal sentences
            scored.append((score, order, sentence))
            order += 1
    if not scored:
        return []
    scored.sort(key=lambda item: (-item[0], item[1]))
    if asked and scored[0][0] <= 0:
        return []  # nothing in the text shares a word with the question
    chosen, total = [], 0
    for score, position, sentence in scored:
        if len(chosen) >= limit:
            break
        if chosen and (score <= 0 or total + len(sentence) > max_chars):
            continue
        chosen.append((position, sentence))
        total += len(sentence)
    return [sentence for _position, sentence in sorted(chosen)]


def site_of(url):
    host = (urlsplit(url).hostname or url).lower()
    return host[4:] if host.startswith("www.") else host


class _TextReader(HTMLParser):
    """Title, meta description and visible text of an HTML page."""

    SKIP = {"script", "style", "noscript", "svg", "template", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.parts = []
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            found = dict(attrs)
            name = (found.get("name") or found.get("property") or "").lower()
            if name in ("description", "og:description") and not self.description:
                self.description = " ".join((found.get("content") or "").split())
        if tag in self.SKIP:
            self._skip += 1
        if tag in ("p", "br", "li", "h1", "h2", "h3", "div", "section", "article", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def read_html(html):
    """(title, description, text) of an HTML page, by the standard library's parser."""
    reader = _TextReader()
    try:
        reader.feed(html)
        reader.close()
    except Exception:  # noqa: BLE001 - a page that does not parse just has less text
        pass
    text = "".join(reader.parts)
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return (" ".join(reader.title.split()), reader.description,
            "\n".join(line for line in lines if line))


def lead_text(text, max_chars=420):
    """The opening prose of a page: its first lines long enough to be sentences."""
    picked, total = [], 0
    for line in text.split("\n"):
        line = " ".join(line.split())
        if len(line) < 40 or len(line.split()) < 7:
            continue  # menus, buttons, cookie banners
        if total + len(line) > max_chars:
            if not picked:
                cut = line[:max_chars].rsplit(" ", 1)[0]
                picked.append(cut + "...")
            break
        picked.append(line)
        total += len(line)
    return " ".join(picked)
