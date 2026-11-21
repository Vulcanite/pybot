"""A question nobody could answer, looked up on the web instead of shrugged at.

Not part of the swarm's original bot (see bot/tools/). Where the composer's floor would say "I'd
rather not guess. A quick search online will get you a solid answer", or "I can't see the news
from here", the bot now makes that search itself and says what it found and where.

It sits at PRIORITY -1, the top of the fallback band: the arbiter only lets a fallback answer when
no real module did, so a knowledge entry, the memory store or a chat module always comes first,
and this only replaces the floor's not-knowing. It proposes only when:

- EXA_API_KEY is set;
- the line is a question about the world: understood "kind" is "question" and it is not about the
  person ("first_person" is not set), so nothing they said about themselves is sent out to a
  search service;
- the composer's own answer would be a shrug or a "no live view" note (bot/compose/hedge.py,
  and the live pools in bot/compose/fallback.py).
"""
import re

from ..compose import fallback, hedge
from ..tools import ToolError, exa, replies

PRIORITY = -1

# The composer's "I can't see that live" lines: they name the place to look, and a search is that
# place.
try:
    _LIVE_LINES = frozenset(line for _kind, _phrases, pool in fallback.LIVE_KINDS for line in pool)
except Exception:  # noqa: BLE001 - without the pools only the shrug counts
    _LIVE_LINES = frozenset()
# "where is respond defined", "what does foo() return": about code, which the web cannot see.
_ABOUT_CODE = re.compile(r"\bwhere\s+(?:is|are)\s+\S+\s+(?:defined|declared|implemented)\b|`[^`]+`|"
                         r"\b[a-z_][a-z0-9_]*\(\)", re.I)
_NO_LIVE_VIEW = re.compile(r"\b(?:can'?t see|cannot see|no live|from here|rather not guess|"
                           r"quick search|search(?:ing)? (?:online|for it)|check online)\b", re.I)


def _wants_the_web(text, memory):
    if not exa.available():
        return False
    read = memory.get("understood") or {}
    if read.get("kind") != "question" or read.get("first_person"):
        return False
    if len(text.split()) < 3:
        return False
    if _ABOUT_CODE.search(text):
        return False  # a question about code on this machine is not one for a search engine
    said = hedge.what_the_composer_would_say(text, memory)
    if not said or said in _LIVE_LINES:
        return True
    return bool(hedge.NOTHING_SAID.search(said) or _NO_LIVE_VIEW.search(said))


def respond(text, memory):
    if not _wants_the_web(text, memory):
        return None
    try:
        reply, urls = replies.search(text, explicit=False)
    except ToolError:
        return None  # the floor's own honest line answers instead
    if reply.startswith(("I searched for", "Top results for")):
        return None  # nothing it can say in a sentence; the floor's line is better than links
    memory["web_results"] = urls
    return reply
