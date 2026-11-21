"""Web search when the person asks for one: "search for ...", "look up ...", "google ...".

Not part of the swarm's original bot (see bot/tools/). It proposes only when EXA_API_KEY is set
and the line is an explicit ask (bot/tools/asks.py), and then the turn is its own: PRIORITY 7100
is above the memory store (7000) and every answer module, and below the safety band (9000), so an
emergency is still answered as one. TAKES_AS_IT_COMES keeps a topic specialist from taking a
search the person asked for in so many words ("search for budget laptops" was answered with the
laptop card).

The results it found are kept in memory["web_results"], so "open the first one" can follow.
"""
from ..tools import ToolError, asks, exa, replies

PRIORITY = 7100


def TAKES_AS_IT_COMES(text, memory):  # noqa: N802 - the arbiter's hook name
    return exa.available() and asks.search_query(text, memory) is not None


def respond(text, memory):
    if not exa.available():
        return None
    query = asks.search_query(text, memory)
    if not query:
        return None
    try:
        reply, urls = replies.search(query, explicit=True)
    except ToolError as error:
        return "I tried to search for that, but %s, so I can't say from here." % error
    memory["web_results"] = urls
    return reply
