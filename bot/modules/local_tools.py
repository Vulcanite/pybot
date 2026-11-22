"""Local commands asked for in plain English: find files, search inside them, show a file, list
a folder, git status, disk space, what's on a port, is a program running.

Not part of the swarm's original bot (see bot/tools/local.py for the list of asks and the command
each one becomes, and bot/tools/runner.py for how it runs). Every command only reads; the
person's words only fill in arguments; there is no shell.

PRIORITY 7100 with TAKES_AS_IT_COMES, like the web modules: a line that names a real file or
folder and asks for something the list knows is a command, and an answer module's card for the
same words ("find my keys" has a card) is not what was asked. The safety band still comes
first. It sorts before web_search and web_inspect on a tie, so "search for TODO in ~/projects"
is a local search when ~/projects exists, and a web search when it does not.
"""
from ..tools import local, runner

PRIORITY = 7100


def TAKES_AS_IT_COMES(text, memory):  # noqa: N802 - the arbiter's hook name
    return local.plan(text) is not None


def respond(text, memory):
    found = local.plan(text)
    if found is None:
        return None
    return runner.reply_for(found)
