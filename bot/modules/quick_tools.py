"""Quick answers worked out in Python: the time here and in other cities, data sizes, Unix
timestamps, base64, hex and binary, URL encoding, JSON, a UUID or a password.

Not part of the swarm's original bot (see bot/tools/quick.py). The bot's own maths domain keeps
plain arithmetic and units; this takes the asks it got wrong ("what time is it" was answered
"35pm.") or could not do ("base64 decode ..." was answered "I'll remember that.").

PRIORITY 7100 with TAKES_AS_IT_COMES, like the other tool modules: the patterns are narrow, and
a line that matches one asked for exactly this.
"""
from ..tools import quick

PRIORITY = 7100


def TAKES_AS_IT_COMES(text, memory):  # noqa: N802 - the arbiter's hook name
    return quick.answer(text) is not None


def respond(text, memory):
    return quick.answer(text)
