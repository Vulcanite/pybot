"""Two or three local asks in one line: "show me README.md and then count its lines", "search
for TODO in ~/projects/pybot, then open the first one", and a follow-up on the last local result
("show the errors in it", "open the second one").

Not part of the swarm's original bot (see bot/tools/chain.py for how a line is cut into asks and
how a later ask gets the path the earlier one found). Every step is planned by bot/tools/local.py
and run by bot/tools/runner.py, exactly as a line of its own would be, so every step only reads
and stays inside home. A step that would change something is never run; the chain stops there.

PRIORITY 7100 with TAKES_AS_IT_COMES, like local_tools: the line asked for these commands in so
many words. A line that local.plan reads as one ask is local_tools' ("search for salt and pepper
in ~/Documents"), never a chain. after() keeps the paths a local answer found in
memory["last_paths"], so "it" on the next line means that file.
"""
from ..tools import chain

PRIORITY = 7100


def TAKES_AS_IT_COMES(text, memory):  # noqa: N802 - the arbiter's hook name
    return chain.wants(text, memory)


def respond(text, memory):
    return chain.answer(text, memory)


def after(text, reply, memory):
    chain.remember(text, reply, memory)
