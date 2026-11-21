"""Notes, reminders and saving to a file: the tools that write.

Not part of the swarm's original bot. Notes and reminders live in one JSON file,
~/.pybot/notes.json (the folder is 700 and the file 600). "save that to x.md" writes the bot's
last reply to a new file, and "save example.com as markdown" writes a page's text; both only
inside the home folder, never over a file that exists (unless the line says "overwrite"), never
under a secrets folder or with a secrets file name.

Reminders are kept with the time they fall due. The chat (`python -m pybot`) checks every few
seconds while it is open and prints the ones that are due, and prints any it missed when it
starts again: there is no background service.

PYBOT_WRITE=0 (or `python -m pybot --read-only`) turns writing off: notes and reminders can
still be read, nothing new is saved.
"""
import datetime
import json
import os
import re
import threading

from . import ToolError
from .local import home, inside_home, is_secret, workdir

_LEAD = (r"^\s*(?:(?:hey|hi|ok|okay|so|pybot|bot)[,!\s]+)*(?:(?:can|could|would|will) you\s+(?:please\s+)?|"
         r"please\s+|pls\s+|just\s+)?")
_END = r"\s*[?.!]*\s*$"
_LOCK = threading.Lock()
_STAGE = threading.local()


def _do(write):
    """Run a write now, or keep it for later while a staged answer is being worked out."""
    pending = getattr(_STAGE, "pending", None)
    if pending is not None:
        pending.append(write)
    else:
        write()


def staged_answer(text, memory=None):
    """(reply, writes): the reply as answer() would give it, with its writes not yet done.

    The bot runs every module before it picks a reply, so a module that wrote straight away would
    write even when another module's reply is the one said ("make a note that i want to end my
    life" is the safety module's turn, and the note was being saved anyway). The caller runs the
    writes only once this reply is the one chosen.
    """
    _STAGE.pending = []
    try:
        reply = answer(text, memory)
        writes = _STAGE.pending
    finally:
        _STAGE.pending = None
    return reply, writes


def writing_allowed():
    return os.environ.get("PYBOT_WRITE", "1") != "0"


def store_path():
    return os.path.join(home(), ".pybot", "notes.json")


def _load():
    try:
        with open(store_path(), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = {}
    data.setdefault("notes", [])
    data.setdefault("reminders", [])
    data.setdefault("next_id", 1)
    data.setdefault("next_reminder", 1)
    return data


def _save(data):
    folder = os.path.dirname(store_path())
    os.makedirs(folder, mode=0o700, exist_ok=True)
    temp = store_path() + ".tmp"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    os.replace(temp, store_path())


def _stamp(moment):
    return moment.strftime("%a %d %b %H:%M")


def _now():
    return datetime.datetime.now().astimezone()


# --- notes ------------------------------------------------------------------------------------

NOTE_ADD = re.compile(_LEAD + r"(?:(?:make|take|add|save|write|leave)\s+(?:me\s+)?(?:a\s+)?note(?:\s+(?:that|saying|of|to\s+self))?"
                      r"|note\s+(?:down|that|to\s+self)|note\s*:|jot\s+(?:down\s+)?(?:that\s+)?)\s*:?\s*(?P<text>.+?)\s*$", re.I)
NOTES_LIST = re.compile(_LEAD + r"(?:(?:show|list|read|give)\s+(?:me\s+)?(?:all\s+)?(?:of\s+)?my\s+notes|what\s+are\s+my\s+notes|"
                        r"my\s+notes|(?:what|which)\s+notes\s+do\s+i\s+have)" + _END, re.I)
NOTES_FIND = re.compile(_LEAD + r"(?:what\s+did\s+i\s+(?:note|write\s+down|jot\s+down)|(?:find|search|show)\s+(?:me\s+)?(?:my\s+)?"
                        r"notes?|(?:any\s+)?notes)\s+(?:about|on|for|with|mentioning)\s+(?P<q>.+?)" + _END, re.I)
NOTE_DELETE = re.compile(_LEAD + r"(?:delete|remove|forget|drop|clear)\s+note\s+(?:#|number\s+|no\.?\s*)?(?P<id>\d{1,6})" + _END, re.I)


def _notes(text):
    found = NOTES_LIST.match(text)
    if found:
        notes = _load()["notes"]
        if not notes:
            return "You have no notes yet. Say \"make a note that ...\" to add one."
        return "Your notes (%d):\n%s" % (len(notes), "\n".join(
            "  #%d  %s  (%s)" % (n["id"], n["text"], n["created"]) for n in notes[-30:]))
    found = NOTES_FIND.match(text)
    if found:
        words = [w for w in re.findall(r"[a-z0-9]+", found.group("q").lower()) if len(w) > 1]
        hits = [n for n in _load()["notes"] if all(w in n["text"].lower() for w in words)]
        if not hits:
            return "No notes mention \"%s\"." % found.group("q")
        return "%d %s about \"%s\":\n%s" % (len(hits), "note" if len(hits) == 1 else "notes", found.group("q"),
                                           "\n".join("  #%d  %s  (%s)" % (n["id"], n["text"], n["created"]) for n in hits))
    found = NOTE_DELETE.match(text)
    if found:
        return _delete("notes", int(found.group("id")), "note")
    found = NOTE_ADD.match(text)
    if found:
        body = found.group("text").strip().strip("\"'")
        if len(body) < 2:
            return None
        if not writing_allowed():
            return "Writing is switched off (--read-only), so I can't save notes right now."
        note = {"id": _load()["next_id"], "text": body, "created": _stamp(_now())}

        def write():
            with _LOCK:
                data = _load()
                note["id"] = data["next_id"]
                data["next_id"] += 1
                data["notes"].append(note)
                _save(data)

        _do(write)
        return "Noted (#%d): %s\nSaved in %s. \"show my notes\" lists them." % (note["id"], body, _tilde(store_path()))
    return None


def _delete(kind, item, label):
    if not writing_allowed():
        return "Writing is switched off (--read-only), so I can't change your %ss right now." % label
    if not any(n["id"] == item for n in _load()[kind]):
        return "There's no %s #%d." % (label, item)

    def write():
        with _LOCK:
            data = _load()
            data[kind] = [n for n in data[kind] if n["id"] != item]
            _save(data)

    _do(write)
    return "Deleted %s #%d." % (label, item)


# --- reminders ----------------------------------------------------------------------------------

REMIND = re.compile(_LEAD + r"(?:remind\s+me|set\s+(?:a\s+|an\s+)?(?:reminder|alarm)|add\s+a\s+reminder|reminder\s*:)\s*(?P<rest>.*?)\s*[.!]*\s*$",
                    re.I)
REMINDERS_LIST = re.compile(_LEAD + r"(?:(?:show|list|give)\s+(?:me\s+)?(?:all\s+)?my\s+reminders|what\s+(?:are\s+my|reminders\s+do\s+i\s+have)"
                            r"(?:\s+reminders)?|my\s+reminders|any\s+reminders|do\s+i\s+have\s+any\s+reminders)" + _END, re.I)
REMINDER_DELETE = re.compile(_LEAD + r"(?:cancel|delete|remove|clear|drop)\s+reminder\s+(?:#|number\s+|no\.?\s*)?(?P<id>\d{1,6})" + _END,
                             re.I)

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_CLOCK = r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm|a\.m\.|p\.m\.)?|(?P<noon>noon|midday|midnight)"
_WHEN = re.compile(
    r"\b(?:in\s+(?P<n>\d{1,4}|an?|half\s+an)\s*(?P<unit>minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?)\b"
    r"|(?P<day>today|tonight|tomorrow|(?:on\s+|next\s+|this\s+)?(?:" + "|".join(_WEEKDAYS) + r")|on\s+\d{4}-\d{2}-\d{2})"
    r"(?:\s+(?:at\s+)?(?:" + _CLOCK + r"))?"
    r"|at\s+(?:" + _CLOCK.replace("?P<h>", "?P<h2>").replace("?P<m>", "?P<m2>").replace("?P<ap>", "?P<ap2>")
    .replace("?P<noon>", "?P<noon2>") + r")(?:\s+(?P<day2>today|tonight|tomorrow))?)", re.I)


def _clock_time(h, m, ap, noon):
    if noon:
        return (0, 0) if noon.lower() == "midnight" else (12, 0)
    if h is None:
        return None
    hour, minute = int(h), int(m or 0)
    ap = (ap or "").lower().replace(".", "")
    if ap == "pm" and hour < 12:
        hour += 12
    if ap == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def parse_when(rest, now=None):
    """(due, text without the time words) for a reminder line, or (None, rest) when it gives no time."""
    now = now or _now()
    found = _WHEN.search(rest)
    if not found:
        return None, rest
    g = found.groupdict()
    due = None
    if g["unit"]:
        amount = {"a": 1, "an": 1}.get((g["n"] or "").lower())
        if amount is None:
            amount = 0.5 if (g["n"] or "").lower().startswith("half") else int(g["n"])
        unit = g["unit"].lower()[0]
        if (g["n"] or "").lower().startswith("half"):
            unit = "h"
        minutes = {"m": 1, "h": 60, "d": 24 * 60, "w": 7 * 24 * 60}[unit] * amount
        due = now + datetime.timedelta(minutes=minutes)
    else:
        clock = _clock_time(g["h"] or g["h2"], g["m"] or g["m2"], g["ap"] or g["ap2"], g["noon"] or g["noon2"])
        day = (g["day"] or g["day2"] or "").lower().replace("on ", "").replace("next ", "").replace("this ", "").strip()
        base = now
        if day == "tomorrow":
            base = now + datetime.timedelta(days=1)
        elif day in _WEEKDAYS:
            ahead = (_WEEKDAYS.index(day) - now.weekday()) % 7 or 7
            base = now + datetime.timedelta(days=ahead)
        elif re.match(r"\d{4}-\d{2}-\d{2}$", day):
            try:
                base = datetime.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=now.tzinfo)
            except ValueError:
                return None, rest
        if clock is None:
            clock = (20, 0) if day == "tonight" else (9, 0) if day not in ("", "today") else None
        if clock is None:
            return None, rest
        if day in ("", "today") and g["h2"] and not g["ap2"] and 1 <= clock[0] < 12:
            # "at 5" said after 5am means 5pm today, while 5pm is still ahead.
            said, minutes_now = clock[0] * 60 + clock[1], now.hour * 60 + now.minute
            if said <= minutes_now < said + 12 * 60:
                clock = (clock[0] + 12, clock[1])
        due = base.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
        if due <= now and day in ("", "today"):
            due += datetime.timedelta(days=1)
    words = (rest[:found.start()] + " " + rest[found.end():]).strip()
    words = re.sub(r"^(?:to|that|about|for)\s+", "", words, flags=re.I).strip(" ,.-")
    words = re.sub(r"\s+(?:to|that)$", "", words, flags=re.I)
    return due, words


def _reminders(text):
    if REMINDERS_LIST.match(text):
        pending = [r for r in _load()["reminders"] if not r.get("done")]
        if not pending:
            return "No reminders set. Say \"remind me to ... in 20 minutes\" or \"... at 5pm\"."
        pending.sort(key=lambda r: r["due"])
        return "Your reminders (%d):\n%s" % (len(pending), "\n".join(
            "  #%d  %s  -> %s" % (r["id"], r["text"], _stamp(datetime.datetime.fromisoformat(r["due"]))) for r in pending))
    found = REMINDER_DELETE.match(text)
    if found:
        return _delete("reminders", int(found.group("id")), "reminder")
    found = REMIND.match(text)
    if not found:
        return None
    rest = re.sub(r"^(?:to|that|about|for)\s+", "", found.group("rest"), flags=re.I)
    due, what = parse_when(rest)
    if not what:
        return "What should I remind you about? Say \"remind me to call the bank at 4pm\"."
    if due is None:
        return ("When should I remind you to %s? Add a time, like \"in 20 minutes\", \"at 5pm\" or "
                "\"tomorrow at 9\"." % what)
    if not writing_allowed():
        return "Writing is switched off (--read-only), so I can't save reminders right now."
    item = {"id": _load()["next_reminder"], "text": what, "due": due.isoformat(timespec="minutes"),
            "created": _stamp(_now()), "done": False}

    def write():
        with _LOCK:
            data = _load()
            item["id"] = data["next_reminder"]
            data["next_reminder"] += 1
            data["reminders"].append(item)
            _save(data)

    _do(write)
    return ("Reminder #%d set for %s: %s\nI'll show it here when it's due while this chat is open, or the next "
            "time you start PyBot." % (item["id"], _stamp(due), what))


def due_now():
    """Reminders that have fallen due and were not shown yet; each is marked done as it is returned."""
    with _LOCK:
        data = _load()
        now = _now()
        due = []
        for item in data["reminders"]:
            if item.get("done"):
                continue
            try:
                when = datetime.datetime.fromisoformat(item["due"])
            except (ValueError, KeyError):
                continue
            if when <= now:
                item["done"] = True
                due.append(item)
        if due:
            try:
                _save(data)
            except OSError:
                pass
    return due


# --- saving to a file -------------------------------------------------------------------------------

SAVE_LAST = re.compile(_LEAD + r"(?:save|write|put|dump)\s+(?:that|this|it|the\s+(?:last\s+)?(?:answer|reply|output|result|response))"
                       r"\s+(?:to|as|in|into)\s+(?:a\s+)?(?:file\s+(?:called|named)\s+)?(?P<path>\S+)(?P<over>\s+(?:and\s+)?overwrite(?:\s+it)?)?"
                       + _END, re.I)
SAVE_PAGE = re.compile(_LEAD + r"(?:save|download|grab)\s+(?:the\s+)?(?:web\s*page\s+|page\s+|website\s+|site\s+|article\s+)?"
                       r"(?P<url>https?://\S+|(?:[a-z0-9-]+\.)+[a-z]{2,24}(?:/\S*)?)(?:\s+as\s+(?:a\s+)?(?:text|markdown|md|txt)(?:\s+file)?)?"
                       r"(?:\s+(?:to|as|into|in)\s+(?P<path>\S+))?(?P<over>\s+(?:and\s+)?overwrite(?:\s+it)?)?" + _END, re.I)


def _tilde(path):
    real_home = os.path.expanduser("~")
    return "~" + path[len(real_home):] if path.startswith(real_home + os.sep) else path


def target(token, default_name=None):
    """The absolute path to write to, checked: inside home, parent exists, not a secrets name."""
    token = (token or "").strip().strip("\"'`").rstrip(",;")
    if not token:
        folder = os.path.join(home(), "Downloads")
        folder = folder if os.path.isdir(folder) else workdir()
        path = os.path.join(folder, default_name)
    elif token.startswith("~"):
        path = os.path.expanduser(token)
    elif token.startswith("/"):
        path = token
    else:
        path = os.path.join(workdir(), token)
    path = os.path.abspath(path)
    parent = os.path.realpath(os.path.dirname(path))
    path = os.path.join(parent, os.path.basename(path))
    if not inside_home(parent):
        raise ToolError("%s is outside your home folder, so I won't write there" % path)
    if not os.path.isdir(parent):
        raise ToolError("the folder %s doesn't exist" % _tilde(parent))
    if is_secret(path):
        raise ToolError("that's a secrets file or folder, so I won't write there")
    if os.path.islink(path):
        raise ToolError("%s is a link, so I won't write through it" % _tilde(path))
    return path


def write_new(path, text, overwrite=False):
    """Write text to path; a new file unless overwrite. Returns the byte count.

    The checks happen now; the write itself may be kept for later (see staged_answer)."""
    if not writing_allowed():
        raise ToolError("writing is switched off (--read-only)")
    if os.path.exists(path) and not overwrite:
        raise ToolError("%s already exists; say \"... and overwrite\" to replace it" % _tilde(path))
    if os.path.isdir(path):
        raise ToolError("%s is a folder" % _tilde(path))
    data = text.encode("utf-8")

    def write():
        flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if overwrite else os.O_EXCL)
        fd = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0), 0o644)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)

    _do(write)
    return len(data)


def _unique(path):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    for n in range(1, 100):
        candidate = "%s-%d%s" % (stem, n, ext)
        if not os.path.exists(candidate):
            return candidate
    return path


def _save_last(text, memory):
    found = SAVE_LAST.match(text)
    if not found:
        return None
    turns = (memory or {}).get("turns") or []
    last = next((t.get("bot") for t in reversed(turns) if isinstance(t, dict) and t.get("bot")), None)
    if not last:
        return "There's nothing to save yet: ask me something first, then say \"save that to notes.md\"."
    try:
        path = target(found.group("path"))
        size = write_new(path, last.rstrip("\n") + "\n", overwrite=bool(found.group("over")))
    except ToolError as error:
        return "I didn't save it: %s." % error
    return "Saved the last reply to %s (%d bytes)." % (_tilde(path), size)


def _save_page(text):
    found = SAVE_PAGE.match(text)
    if not found:
        return None
    from . import browser, digest, net  # noqa: PLC0415 - only when a page is saved
    url = net.normalise_url(found.group("url"))
    host = digest.site_of(url)
    try:
        path = target(found.group("path"), default_name=host.replace(":", "_") + ".md")
        if not found.group("path"):
            path = _unique(path)
        title, body = "", ""
        if browser.available():
            try:
                page = browser.render(url)
                title, body, url = page["title"], page["text"], page["url"] or url
            except ToolError:
                body = ""
        if not body:
            response = net.fetch(url)
            title, _description, body = digest.read_html(response.text())
        paragraphs = [" ".join(line.split()) for line in body.split("\n") if len(line.split()) >= 4]
        document = "# %s\n\nSource: %s\nSaved: %s\n\n%s\n" % (title or host, url, _stamp(_now()), "\n\n".join(paragraphs))
        size = write_new(path, document, overwrite=bool(found.group("over")))
    except ToolError as error:
        return "I didn't save it: %s." % error
    return "Saved %s (\"%s\") to %s: %d paragraphs, %d bytes." % (host, (title or host)[:60], _tilde(path),
                                                                 len(paragraphs), size)


def answer(text, memory=None):
    """The reply to a notes, reminders or save line, or None."""
    if not text or len(text) > 2000:
        return None
    text = text.strip()
    for reader in (_reminders, _notes):
        said = reader(text)
        if said:
            return said
    return _save_last(text, memory) or _save_page(text)


def claims(text):
    """True when the line is one of these asks (without doing it): for the arbiter's hook."""
    text = (text or "").strip()
    return bool(REMIND.match(text) or REMINDERS_LIST.match(text) or REMINDER_DELETE.match(text)
                or NOTES_LIST.match(text) or NOTES_FIND.match(text) or NOTE_DELETE.match(text)
                or NOTE_ADD.match(text) or SAVE_LAST.match(text) or SAVE_PAGE.match(text))
