"""A look at a website: "is github.com down", "check the headers on example.com", "what does
example.com say", a bare link, or "open the first one" after a search.

Not part of the swarm's original bot (see bot/tools/). It fetches with the guarded client in
bot/tools/net.py (public addresses only, every redirect checked), and reads a page through
Vercel's agent-browser when it is installed, so pages that need JavaScript still have text.
What it says is built by rule: the status, the time, the certificate, which security headers
are there and which are missing, or the page's title and opening lines.

PRIORITY 7100 and TAKES_AS_IT_COMES for the same reason as web_search: the person asked for this
site in so many words. A line that is an explicit search ("search for example.com") is left to
web_search.
"""
from ..tools import asks, enabled, replies

PRIORITY = 7100


def _ask(text, memory):
    if not enabled() or asks.search_query(text, memory) is not None:
        return None
    return asks.site_ask(text, memory)


def TAKES_AS_IT_COMES(text, memory):  # noqa: N802 - the arbiter's hook name
    return _ask(text, memory) is not None


def respond(text, memory):
    found = _ask(text, memory)
    if not found:
        return None
    site, mode = found
    return replies.inspect(site, mode)
