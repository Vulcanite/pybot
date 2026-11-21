"""What PyBot keeps about the person across chats (bot/tools/profile.py), in the conversation.

Not part of the swarm's original bot. The memory store (PRIORITY 7000) keeps what is said for
this chat and answers "what's my name?" from it; this module keeps the few things worth keeping
for the next chat in ~/.pybot/profile.json, scored by rules (see bot/tools/profile.py).

- observe(): on the first turn of a conversation the kept facts are put into the chat's own
  memory (memory["user"]: name, city, job, pets, allergies), so the memory store answers "what's
  my name?" in a new chat exactly as it does in the chat where it was said. It never overwrites
  what the chat already holds.
- TAKES_AS_IT_COMES / respond(): the lines that are about the profile itself - "remember that
  ...", a standing rule ("always use metric", "call me Sam"), a secret ("my password is ...":
  refused, never written), "forget that ...", "forget everything about me", "what do you
  remember about me", and a question about a kept fact the chat does not hold.
- A plain stable fact ("my name is Sam", "i use arch") is not claimed: the bot answers it as it
  always did, and the fact is kept quietly in after().

PRIORITY 7100 with TAKES_AS_IT_COMES, like note_tools. The safety band (9000) still comes first.
Every module proposes before the arbiter picks one, so respond() only works out the reply and
keeps its writes; after() carries them out when that reply is the one the bot said, and a quiet
fact is kept only when the safety module had nothing to say about the line: "remember that i
want to die" is the safety module's turn, and nothing is stored.
"""
import copy

from ..tools import notes, profile

PRIORITY = 7100

_PENDING = {}  # this turn's staged writes: {"text", "reply", "writes", "quiet"}

# The kept slot -> how the chat's memory holds it (bot/memory/__init__.py, memory["user"]).
_SEEDED = {"name": ("name",), "call_me": ("name",), "city": ("city", "places", "home"), "job": ("job",)}


def _the_chat_has(slot, memory):
    known = memory.get("user") if isinstance(memory, dict) else None
    if not isinstance(known, dict):
        return False
    if slot.startswith("pet:"):
        return any(isinstance(p, dict) and p.get("animal") == slot[4:] and p.get("name") for p in known.get("pets") or [])
    if slot.startswith("allergy:"):
        return bool(known.get("allergies"))
    keys = _SEEDED.get(slot)
    return bool(keys) and bool(known.get(keys[0]))


def _wants_turn(text, memory):
    if notes.claims(text):
        return False  # "make a note that ...", "remind me ...": the notes tool's
    kind, detail = profile.classify(text, memory)
    if kind in ("secret", "remember", "confirm_forget", "forget_all"):
        return True
    kept = profile.facts()
    if kind in ("forget_all_ask", "recall_all"):
        return bool(kept)
    if kind == "forget":
        return bool(profile._to_forget(detail, kept))
    if kind == "recall":
        hits = profile._matching(detail[1], kept)
        # The chat's own memory is fresher ("actually my name is Alex" said with --read-only):
        # where it holds the fact, the memory store answers.
        return bool(hits) and not any(_the_chat_has(f["slot"], memory) for f in hits)
    return False


def TAKES_AS_IT_COMES(text, memory):  # noqa: N802 - the arbiter's hook name
    try:
        return _wants_turn(text, memory)
    except Exception:  # noqa: BLE001 - a bad profile file never takes a turn
        return False


def seed(memory):
    """Put the kept facts into the chat's memory, without overwriting what it holds."""
    if not isinstance(memory, dict):
        return
    known = memory.get("user")
    if not isinstance(known, dict):
        known = memory["user"] = {}
    for fact in profile.facts():
        slot, value = str(fact.get("slot", "")), fact.get("value")
        if not isinstance(value, str) or not value:
            continue
        if slot in ("name", "call_me"):
            if slot == "call_me" or not known.get("name"):
                known["name"] = value
        elif slot == "city" and not known.get("city"):
            known["city"] = value
            places = known.get("places") if isinstance(known.get("places"), list) else []
            if value not in places:
                known["places"] = places + [value]
            known["home"] = True
        elif slot == "job" and not known.get("job"):
            known["job"] = value
        elif slot.startswith("pet:"):
            pets = known.get("pets") if isinstance(known.get("pets"), list) else []
            if not any(isinstance(p, dict) and p.get("animal") == slot[4:] for p in pets):
                known["pets"] = pets + [{"animal": slot[4:], "name": value}]
        elif slot.startswith("allergy:"):
            allergies = known.get("allergies") if isinstance(known.get("allergies"), list) else []
            for one in [v.strip() for v in value.replace(" and ", ",").split(",") if v.strip()]:
                if one not in allergies:
                    allergies = allergies + [one]
            known["allergies"] = allergies
    if not known:
        memory.pop("user", None)


def observe(text, memory):
    if isinstance(memory, dict) and not memory.get("turns"):
        try:
            seed(memory)
        except Exception:  # noqa: BLE001 - a bad profile file never ends a chat
            pass


def _unseed(slots, memory):
    """A forgotten fact leaves the chat's copy too, so "what's my name?" does not still say it."""
    known = memory.get("user") if isinstance(memory, dict) else None
    if not isinstance(known, dict):
        return
    for slot in slots:
        for key in _SEEDED.get(slot, ()):
            known.pop(key, None)
        if slot.startswith("pet:") and isinstance(known.get("pets"), list):
            known["pets"] = [p for p in known["pets"] if not (isinstance(p, dict) and p.get("animal") == slot[4:])]
        if slot.startswith("allergy:"):
            known.pop("allergies", None)


def respond(text, memory):
    _PENDING.clear()
    if TAKES_AS_IT_COMES(text, memory):
        slots = profile.forgotten_slots(text, memory)
        reply, writes = profile.staged_answer(text, memory)
        if reply and writes:
            _PENDING.update(text=text, reply=reply, writes=writes, quiet=False)
            _unseed(slots, memory)
        return reply
    kind, _ = profile.classify(text, memory)
    if kind == "fact" and profile.writing_allowed():
        _, writes = profile.staged_answer(text, memory)
        if writes:
            _PENDING.update(text=text, reply=None, writes=writes, quiet=True)
    return None


def _safety_answers(text, memory):
    try:
        from . import safety  # noqa: PLC0415 - only for a quiet fact
        return bool(safety.respond(text, copy.deepcopy(memory)))
    except Exception:  # noqa: BLE001 - if safety cannot say, keep nothing
        return True


def after(text, reply, memory):
    pending = dict(_PENDING)
    _PENDING.clear()
    if not pending or pending["text"] != text:
        return
    if pending["quiet"]:
        if _safety_answers(text, memory):
            return
    elif pending["reply"] != reply:
        return
    for write in pending["writes"]:
        write()
