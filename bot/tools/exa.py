"""Web search through Exa (https://exa.ai), standard library only.

Only the /search endpoint is used, with `highlights` for the text. Exa's /answer endpoint and
its `summary` option are written by a language model, and PyBot's replies are not, so neither is
called: the bot reads the highlights itself (`digest.py`) and says which page they came from.

EXA_API_KEY turns search on. EXA_SEARCH_TYPE picks Exa's search type ("fast" by default, which
answers in a fraction of a second; "auto" is slower and sometimes better).
"""
import json
import os
import time
import urllib.error
import urllib.request

from . import ToolError, enabled

ENDPOINT = "https://api.exa.ai/search"
TIMEOUT = 8.0
CACHE_SECONDS = 600
_CACHE = {}  # (query, n) -> (time, results); one process, one chat at a time
_CACHE_LIMIT = 64


def api_key():
    return (os.environ.get("EXA_API_KEY") or "").strip()


def available():
    """True when a key is set, so a search can be made at all."""
    return enabled() and bool(api_key())


def search(query, num_results=3, highlight_chars=900):
    """[{"title", "url", "published", "highlights": [str]}] for query, best first; or ToolError."""
    key = api_key()
    if not enabled():
        raise ToolError("the web is switched off")
    if not key:
        raise ToolError("no search key is set")
    query = " ".join(query.split())[:400]
    if not query:
        raise ToolError("nothing to search for")
    cache_key = (query.lower(), num_results)
    hit = _CACHE.get(cache_key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    body = json.dumps({
        "query": query,
        "numResults": num_results,
        "type": os.environ.get("EXA_SEARCH_TYPE", "fast"),
        "contents": {"highlights": {"maxCharacters": highlight_chars, "query": query}},
    }).encode("utf-8")
    request = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
        "x-api-key": key, "content-type": "application/json", "accept": "application/json",
        "user-agent": "PyBot/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as reply:
            data = json.loads(reply.read(2_000_000).decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise ToolError("the search key was refused") from None
        if error.code == 429:
            raise ToolError("the search service is rate-limiting us") from None
        raise ToolError("the search service answered %d" % error.code) from None
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        raise ToolError("the search service could not be reached") from None
    results = []
    for item in data.get("results") or []:
        if not isinstance(item, dict) or not item.get("url"):
            continue
        results.append({
            "title": " ".join(str(item.get("title") or "").split()),
            "url": str(item["url"]),
            "published": str(item.get("publishedDate") or "")[:10],
            "highlights": [str(h) for h in item.get("highlights") or [] if h],
        })
    if len(_CACHE) >= _CACHE_LIMIT:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[cache_key] = (time.time(), results)
    return results
