"""Web search when the person asks for one: "search for ...", "look up ...", "google ...".

Not part of the swarm's original bot (see bot/tools/). It proposes only when EXA_API_KEY is set
and the line is an explicit ask (bot/tools/asks.py), and then the turn is its own: PRIORITY 7100
is above the memory store (7000) and every answer module, and below the safety band (9000), so an
emergency is still answered as one. TAKES_AS_IT_COMES keeps a topic specialist from taking a
search the person asked for in so many words ("search for budget laptops" was answered with the
laptop card).

The results it found are kept in memory["web_results"], so "open the first one" can follow.
"""
import re

from ..tools import ToolError, asks, capabilities, exa, local, replies

PRIORITY = 7100

# "search my feelings", "search my soul": about the person, not something to send to a search
# service ("search my name online" still says where to search, so it is still a search).
_ABOUT_ME = re.compile(r"^\s*(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?search\s+(?:in(?:side)?\s+|through\s+)?"
                       r"(?:my|me|myself|your|yourself)\b(?!.*\b(?:online|on\s+the\s+(?:web|internet)|google)\b)", re.I)


def _query(text, memory):
    """The web query, or None: not a search, a question about PyBot, a local search, or about the person."""
    if not exa.available():
        return None
    query = asks.search_query(text, memory)
    if not query or _ABOUT_ME.match(text or ""):
        return None
    # "search ~/projects for TODO" names a folder that exists: local_tools greps it.
    # "can you search the web?" asks whether PyBot can: capability_tools says so.
    if local.plan(text) is not None or capabilities.answer(text) is not None:
        return None
    return query


def TAKES_AS_IT_COMES(text, memory):  # noqa: N802 - the arbiter's hook name
    return _query(text, memory) is not None


def respond(text, memory):
    query = _query(text, memory)
    if not query:
        return None
    try:
        reply, urls = replies.search(query, explicit=True)
    except ToolError as error:
        return "I tried to search for that, but %s, so I can't say from here." % error
    memory["web_results"] = urls
    return reply
