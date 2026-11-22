"""Questions about PyBot itself: "can you read files?", "what can you do?", "are you online?".

Not part of the swarm's original bot (see bot/tools/capabilities.py for the table). The answer
comes from what is switched on in this run (web search, the local commands, writing), never from
a web search: "can you search the web?" was being sent to the search service as a query for
"the web".

PRIORITY 7100 with TAKES_AS_IT_COMES, like the other tool modules: the patterns are narrow (a
second-person question about one of the bot's own abilities), and a line that matches asked
exactly this. The safety band (9000) still comes first.
"""
from ..tools import capabilities

PRIORITY = 7100


def TAKES_AS_IT_COMES(text, memory):  # noqa: N802 - the arbiter's hook name
    return capabilities.answer(text) is not None


def respond(text, memory):
    return capabilities.answer(text)
