"""Notes, reminders and "save that to a file". The one tool module that writes.

Not part of the swarm's original bot (see bot/tools/notes.py for what is written where). The
memory store keeps what is said in the chat ("remember that my server ip is ...") for this
conversation; notes and reminders here are kept in ~/.pybot/notes.json and last across chats.

PRIORITY 7100 with TAKES_AS_IT_COMES: "remind me to ..." was answered "I can't set an alarm",
and "make a note that ..." with a card about VPNs. The arbiter asks the hook first and the
module then writes in respond(), so the hook only reads the line (`notes.claims`).
"""
from ..tools import notes

PRIORITY = 7100


def TAKES_AS_IT_COMES(text, memory):  # noqa: N802 - the arbiter's hook name
    return notes.claims(text)


def respond(text, memory):
    if not notes.claims(text):
        return None
    return notes.answer(text, memory)
