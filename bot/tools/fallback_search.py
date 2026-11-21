"""A question nobody could answer, looked up on the web instead of shrugged at.

Not part of the swarm's original bot. Where the bot's reply would be "I'd rather not guess. A
quick search online will get you a solid answer", or "I can't see the news from here", the
search is made and the reply says what it found and where.

This runs after the turn, on the reply the bot actually chose. It used to be a module
(bot/modules/web_lookup.py), and every module proposes before the arbiter picks one, so it
searched for every question the fallback layer would have shrugged at - including the ones a
knowledge entry then answered: 10 Exa searches for 20 ordinary lines, 7 of them thrown away
("what's the capital of peru", "what's 15% of 240"). Here a search happens only when the reply
in hand is the shrug. It replaces the reply only when:

- EXA_API_KEY is set (and PYBOT_WEB is not 0);
- the chosen reply came from the fallback band (PRIORITY below 0) and is a shrug or a "no live
  view" note;
- the line is a question about the world: understood "kind" is "question" and it is not about
  the person ("first_person"), so nothing they said about themselves is sent to a search service;
- and it is not a question about PyBot itself ("can you ...", "do you ...", "are you ...", "what
  can you do"): no page on the web knows what this bot can do.
"""
import re

from . import ToolError, exa, replies

# "where is respond defined", "what does foo() return": about code, which the web cannot see.
_ABOUT_CODE = re.compile(r"\bwhere\s+(?:is|are)\s+\S+\s+(?:defined|declared|implemented)\b|`[^`]+`|"
                         r"\b[a-z_][a-z0-9_]*\(\)", re.I)
# The fallback band's not-knowing lines: the shrug, and the "can't see it live" notes.
_SHRUG = re.compile(r"\b(?:can'?t see|cannot see|no live|from here|rather not guess|quick search|"
                    r"search(?:ing)? (?:online|for it)|check online|not sure about that one|"
                    r"beyond what i know|don'?t know enough)\b", re.I)


# "can you ...", "do you ...", "are you ...", "what can you ...": a question about PyBot itself,
# which no web page answers. "can you tell me ..." and "do you know ..." ask about the world.
_ABOUT_THE_BOT = re.compile(
    r"^\W*(?:(?:hey|hi|ok|okay|so|and|but|pybot|bot)[,!\s]+)*"
    r"(?:(?:can|could|will|would|do|does|did|are|were|have|r)\s+(?:you|u|ya)\b"
    r"(?!\s+(?:please\s+)?(?:tell|show|give|explain|find|search|look|check|recommend|suggest|name|list|describe|"
    r"define|translate|summari[sz]e|compare|teach|know|think|reckon|have\s+any\s+idea)\b)|"
    r"what\s+(?:else\s+)?(?:can|could|do|will|would|are)\s+(?:you|u)\s+(?:do|able|capable|good|for|like|made|"
    r"run|use)\b|(?:who|what)\s+are\s+(?:you|u)\b|is\s+it\s+possible\s+for\s+(?:you|u)\b)", re.I)


def about_the_bot(text):
    """True for a question about PyBot itself: answered from the capability table, never searched."""
    from . import capabilities  # noqa: PLC0415 - it imports local and notes
    return bool(_ABOUT_THE_BOT.search(text or "")) or capabilities.answer(text or "") is not None


def wants_the_web(text, memory, result):
    """True when this turn's chosen reply is a shrug the web can do better than."""
    if not exa.available() or not isinstance(result, dict):
        return False
    if about_the_bot(text):
        return False
    chosen = result.get("module")
    priority = next((c.get("priority", 0) for c in result.get("candidates") or [] if c.get("module") == chosen), -1)
    if priority >= 0 or not _SHRUG.search(str(result.get("reply") or "")):
        return False
    read = (memory or {}).get("understood") or {}
    if read.get("kind") != "question" or read.get("first_person"):
        return False
    return len(text.split()) >= 3 and not _ABOUT_CODE.search(text)


def improve(text, memory, result):
    """The turn's result, with a shrug replaced by what a web search found. Updates memory too."""
    if not wants_the_web(text, memory, result):
        return result
    try:
        reply, urls = replies.search(text, explicit=False)
    except ToolError:
        return result  # the bot's own honest line stands
    if reply.startswith(("I searched for", "Top results for")):
        return result  # nothing to say in a sentence; the honest line beats a list of links
    turns = memory.get("turns") or []
    if turns and turns[-1].get("user") == text:
        turns[-1]["bot"], turns[-1]["module"] = reply, "web_lookup"
    memory["web_results"] = urls
    return dict(result, reply=reply, module="web_lookup")
