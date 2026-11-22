"""Asks to delete, move, rename, overwrite, chmod, kill, install or force-push: never run, only shown.

Not part of the swarm's original bot (see bot/tools/suggest.py for the asks and the commands
they become). PyBot replies with the exact command the person can run themselves and a warning
that says what it would change and what to run first to check. Nothing here runs anything.

PRIORITY 7100 with TAKES_AS_IT_COMES, like the other tool modules. The safety band (9000) still
comes first, so "how do i kill myself" is the safety module's turn; suggest() does not take it
either, since "myself" is no process.
"""
from ..tools import suggest

PRIORITY = 7100


def TAKES_AS_IT_COMES(text, memory):  # noqa: N802 - the arbiter's hook name
    return suggest.suggest(text) is not None


def respond(text, memory):
    found = suggest.suggest(text)
    if found is None:
        return None
    return suggest.reply_for(found)
