"""Notes, reminders and "save that to a file". The one tool module that writes.

Not part of the swarm's original bot (see bot/tools/notes.py for what is written where). The
memory store keeps what is said in the chat ("remember that my server ip is ...") for this
conversation; notes and reminders here are kept in ~/.pybot/notes.json and last across chats.

PRIORITY 7100 with TAKES_AS_IT_COMES: "remind me to ..." was answered "I can't set an alarm",
and "make a note that ..." with a card about VPNs. The safety band (9000) still comes first.

Every module proposes before the arbiter picks one, so respond() only works out the reply and
keeps its writes; after() carries them out when that reply is the one the bot said. "make a note
that i want to end my life" is the safety module's turn, and nothing is saved.
"""
from ..tools import notes

PRIORITY = 7100

_PENDING = {}  # the staged writes of this turn's proposal: {"text", "reply", "writes"}


def TAKES_AS_IT_COMES(text, memory):  # noqa: N802 - the arbiter's hook name
    return notes.claims(text)


def respond(text, memory):
    _PENDING.clear()
    if not notes.claims(text):
        return None
    reply, writes = notes.staged_answer(text, memory)
    if reply and writes:
        _PENDING.update(text=text, reply=reply, writes=writes)
    return reply


def after(text, reply, memory):
    pending = dict(_PENDING)
    _PENDING.clear()
    if pending and pending["text"] == text and pending["reply"] == reply:
        for write in pending["writes"]:
            write()
