"""The readings that decide a line wants the web: an explicit search, or a site to look at.

These are the "tool calls". There is no model to decide them, so a rule does: a line is a search
when it says so ("search for ...", "look up ...", "google ..."), and a site check when it names a
site and asks something of it ("is github.com down", "check the headers on example.com", "what
does example.com say"). Kept apart from the modules so they can be tested without loading the
whole bot.
"""
import re

_LEAD = r"^\s*(?:(?:hey|hi|ok|okay|so|pybot|bot)[,!\s]+)*" \
        r"(?:(?:can|could|would|will) you\s+(?:please\s+)?|please\s+|pls\s+|plz\s+|now\s+)?"

SEARCH = re.compile(
    _LEAD +
    r"(?:(?:do|run|make)\s+an?\s+)?"
    r"(?:web\s*search|internet\s+search|search(?:\s+(?:online|the\s+(?:web|internet|net)|google))?"
    r"|google|look\s*up|lookup|find(?=\s.*\b(?:online|on\s+the\s+(?:web|internet))\b))"
    r"(?:\s+(?:for|about|on))?\s*[:\-]?\s+(?P<q>.+?)\s*[?.!]*\s*$", re.I)

# "look it up", "can you search that", "google it for me": the thing is the line before.
SEARCH_THAT = re.compile(
    _LEAD +
    r"(?:look\s+(?:it|that|this)\s+up|search\s+(?:for\s+)?(?:it|that|this)|google\s+(?:it|that|this)"
    r"|search\s+(?:the\s+web|online)\s+for\s+(?:it|that|this))"
    r"(?:\s+(?:online|for\s+me|please))*\s*[?.!]*\s*$", re.I)

_TAIL = re.compile(r"\s+(?:for me|online|on the (?:web|internet)|please|pls|thanks)\s*$", re.I)


def search_query(text, memory=None):
    """The query when the line asks for a web search, else None."""
    text = text or ""
    found = SEARCH.match(text)
    if found:
        query = found.group("q")
        for _ in range(3):
            query = _TAIL.sub("", query)
        query = query.strip(" \"'")
        if len(query) >= 2 and not SEARCH_THAT.match("search " + query):
            return query
        if not SEARCH_THAT.match(text):
            return None
    if SEARCH_THAT.match(text):
        return _line_before(memory)
    return None


def _line_before(memory):
    turns = (memory or {}).get("turns") or []
    for turn in reversed(turns):
        said = (turn or {}).get("user") if isinstance(turn, dict) else None
        if said and not SEARCH_THAT.match(said):
            return " ".join(said.split())
    return None


# --- a site, and what is asked of it ----------------------------------------------------------

_FILE_ENDINGS = frozenset("""
txt pdf doc docx xls xlsx csv ppt pptx md py js ts jsx tsx json yml yaml xml jpg jpeg png gif
webp svg mp3 mp4 mov avi wav zip tar gz rar exe dmg apk msi iso bin log ini cfg conf sh bat
java c cpp h rb go rs php sql db bak tmp
""".split())

URL = re.compile(r"\bhttps?://[^\s<>\"']+", re.I)
DOMAIN = re.compile(
    r"(?<![@\w.-])((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+([a-z]{2,24})(?::\d{2,5})?"
    r"(?:/[^\s<>\"']*)?)(?![\w-])", re.I)

STATUS = re.compile(r"\b(?:down|up|working|online|offline|reachable|unreachable|broken|loading|"
                    r"responding|dead|alive|status)\b", re.I)
AUDIT = re.compile(r"\b(?:headers?|security|secure|inspect|inspection|audit|check|tls|ssl|https|"
                   r"certificate|cert|hsts|csp)\b", re.I)
READ = re.compile(r"\b(?:what(?:'s| is| does)?\b.*\b(?:say|on|about)|read|open|visit|browse|go to|"
                  r"summari[sz]e|tl;?dr|show me|whats on)\b", re.I)
# "the first one", "open the second result", "read the top link": a result of the last search.
NTH_RESULT = re.compile(r"\b(?:open|read|visit|check|show me|go to|what does)\b.*?"
                        r"\b(?P<nth>first|second|third|top|1st|2nd|3rd)\s+(?:one|result|link|page|site)\b",
                        re.I)
_NTH = {"first": 0, "top": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2}


def site_in(text):
    """The URL or bare domain the line names, or None."""
    found = URL.search(text or "")
    if found:
        return found.group(0).rstrip(".,;:!?)]}")
    for found in DOMAIN.finditer(text or ""):
        ending = found.group(2).lower()
        if ending in _FILE_ENDINGS:
            continue
        return found.group(1).rstrip(".,;:!?)]}")
    return None


def site_ask(text, memory=None):
    """(url, mode) when the line asks something of a site, else None.

    mode is "status" (is it up), "audit" (status, TLS and security headers) or "read" (what the
    page says). A bare link on its own is a "read".
    """
    text = text or ""
    nth = NTH_RESULT.search(text)
    if nth:
        urls = (memory or {}).get("web_results") or []
        index = _NTH.get(nth.group("nth").lower(), 0)
        if index < len(urls):
            return urls[index], "read"
    site = site_in(text)
    if not site:
        return None
    rest = text.replace(site, " ")
    if STATUS.search(rest):
        return site, "status"
    if AUDIT.search(rest):
        return site, "audit"
    if READ.search(rest):
        return site, "read"
    if len(rest.split()) <= 1:
        return site, "read"  # the link on its own
    return None
