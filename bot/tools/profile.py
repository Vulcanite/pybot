"""What PyBot keeps about the person across chats: a small profile, scored by rules.

Not part of the swarm's original bot. The swarm's memory store (bot/memory/, answered by
bot/modules/memory_store.py) keeps what is said for one conversation; this file keeps the few
things worth keeping for the next one, in ~/.pybot/profile.json (the folder is 700, the file
600, written the way bot/tools/notes.py writes notes.json). PYBOT_WRITE=0 (`--read-only`) turns
writing off: the profile can still be read and recalled, nothing new is kept.

Every line is scored by score() into one of four tiers, the first that applies:

    never   a password, key, token, card number or a secret-looking value: never written, even
            when asked ("my password is hunter2", "remember that my card number is 4111 ...").
    always  asked for in so many words ("remember that ...", "remember: ...", "don't forget
            ..."), or a standing preference or rule ("always use metric", "call me Sam", "i
            prefer short answers", "from now on ...").
    keep    a stable fact about the person: name, job, where they live, the OS and tools they
            use, the languages they speak or code in, family and pet names, allergies, diet,
            favourites.
    chat    a passing state ("i'm tired today", "i'm at the airport", "i had pasta for lunch"),
            or a stable shape with a word that says it is only for now ("i use windows at work
            today"). Not written: the chat's own memory has it until the conversation ends.

Each kept fact has a slot ("name", "city", "os", "favourite:editor", "pet:dog", ...), and a new
value replaces the old one in the same slot: "actually my name is Alex" replaces Sam.

The controls always work: "what do you remember about me" lists the profile, "forget that i use
arch" (or "forget my name", "forget where i live") drops what it names, "forget everything about
me" clears it. A bare "forget everything" is ambiguous (this chat, or the profile?), so it asks
first and clears on "yes".

answer(text, memory) writes straight away; staged_answer() returns the writes instead, for the
module (bot/modules/profile_tools.py) to run only when its reply is the one the bot said.
"""
import datetime
import json
import os
import re
import threading

from .local import home

_LOCK = threading.Lock()
_STAGE = threading.local()
_CACHE = {}  # {"key": (mtime, size), "data": ...}: claims() reads the file on every turn


# --- the file ------------------------------------------------------------------------------------

def writing_allowed():
    return os.environ.get("PYBOT_WRITE", "1") != "0"


def store_path():
    return os.path.join(home(), ".pybot", "profile.json")


def _load():
    path = store_path()
    try:
        stat = os.stat(path)
        key = (path, stat.st_mtime_ns, stat.st_size)
        if _CACHE.get("key") == key:
            return json.loads(json.dumps(_CACHE["data"]))
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        key, data = None, {}
    if not isinstance(data, dict):
        data = {}
    kept = data.get("facts")
    data["facts"] = [f for f in kept if isinstance(f, dict) and f.get("text")] if isinstance(kept, list) else []
    data.setdefault("version", 1)
    if key:
        _CACHE.update(key=key, data=json.loads(json.dumps(data)))
    return data


def _save(data):
    folder = os.path.dirname(store_path())
    os.makedirs(folder, mode=0o700, exist_ok=True)
    temp = store_path() + ".tmp"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    os.replace(temp, store_path())
    _CACHE.clear()


def facts():
    """What is kept: [{"slot", "text", "value", "tier", "saved"}], oldest first."""
    return _load()["facts"]


def _do(write):
    """Run a write now, or keep it for later while a staged answer is being worked out."""
    pending = getattr(_STAGE, "pending", None)
    if pending is not None:
        pending.append(write)
    else:
        write()


def staged_answer(text, memory=None):
    """(reply, writes): the reply as answer() would give it, with its writes not yet done."""
    _STAGE.pending = []
    try:
        reply = answer(text, memory)
        writes = _STAGE.pending
    finally:
        _STAGE.pending = None
    return reply, writes


def _tilde(path):
    real_home = os.path.realpath(os.path.expanduser("~"))
    path = os.path.realpath(path)
    return "~" + path[len(real_home):] if path.startswith(real_home + os.sep) else path


# --- reading a line --------------------------------------------------------------------------------

_LEAD = re.compile(r"^\s*(?:(?:hey|hi|ok|okay|so|well|oh|actually|no|nope|sorry|btw|fyi|also|and|pybot|bot|"
                   r"by\s+the\s+way|just\s+so\s+you\s+know|for\s+the\s+record)\b[,!.:\s]*)*", re.I)
_ASK_LEAD = re.compile(r"^(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?|please\s+|pls\s+)", re.I)
_TAIL = re.compile(r"[\s,]*(?:\b(?:please|pls|thanks|thank\s+you|ok|okay|btw|lol)\b[\s,.!]*)*[\s.!?]*$", re.I)


def _clause(text):
    """The line without the chat around it: "ok so, actually my name is Alex!" -> "my name is Alex"."""
    text = " ".join((text or "").replace("’", "'").split())
    text = _LEAD.sub("", text)
    return _TAIL.sub("", text).strip()


# Secrets. A word that names one, said as "my <word> is ...", or a value shaped like one.
SECRET_WORD = re.compile(
    r"\b(?:pass(?:word|wd|phrase|code)s?|pin\s+(?:code|number)|my\s+pin|api[\s_-]?keys?|access[\s_-]?keys?|"
    r"secret\s+keys?|secrets?|auth[\s_-]?tokens?|tokens?|private[\s_-]?keys?|ssh[\s_-]?keys?|"
    r"(?:credit\s+|debit\s+|bank\s+)?card\s+(?:number|details|no)|cvv|cvc|security\s+code|ssn|"
    r"social\s+security(?:\s+number)?|account\s+number|sort\s+code|iban|seed\s+phrase|recovery\s+(?:phrase|codes?)|"
    r"2fa\s+codes?|otp|one[\s-]time\s+code)\b", re.I)
SECRET_VALUE = re.compile(
    r"\bsk-[A-Za-z0-9_-]{6,}|\bgh[pousr]_[A-Za-z0-9]{10,}|\bgithub_pat_\w+|\bAKIA[0-9A-Z]{12,}|\bxox[abprs]-[\w-]+"
    r"|\beyJ[\w-]{10,}\.[\w-]+|-----BEGIN|\bAIza[\w-]{20,}|(?<![\d.])(?:\d[ -]?){12,18}\d(?![\d.])"
    r"|\b(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{24,}\b")
# "my password is hunter2": the statement of a secret, whole. "my password is too weak" is not one.
SECRET_SAID = re.compile(
    r"^(?:(?:remember|don'?t\s+forget|do\s+not\s+forget)\s*(?:that\s*|:\s*)?)?(?:my|our|the)\s+(?:[\w-]+\s+){0,2}?"
    r"(?P<word>pass(?:word|wd|phrase|code)|pin(?:\s+(?:code|number))?|api[\s_-]?key|access[\s_-]?key|secret(?:\s+key)?|"
    r"(?:auth\s+)?token|private\s+key|(?:credit\s+|debit\s+|bank\s+)?card\s+(?:number|details|no)|cvv|cvc|"
    r"security\s+code|ssn|social\s+security\s+number|account\s+number|sort\s+code|iban|seed\s+phrase|recovery\s+(?:phrase|code))"
    r"(?:\s+for\s+[\w.-]+)?\s*(?:is|=|:|was|'s)\s*(?P<value>\S+(?:\s+\S+){0,3})$", re.I)
NOT_A_SECRET_VALUE = frozenset("""too not weak strong wrong expired incorrect invalid broken compromised leaked
stolen same short long old new missing lost changed reset forgotten different blank empty""".split())


def looks_secret(text):
    """True when a line names a secret or holds a value shaped like one."""
    return bool(SECRET_WORD.search(text or "") or SECRET_VALUE.search(text or ""))


def _secret_said(clause):
    found = SECRET_SAID.match(clause)
    if found and found.group("value").split()[0].lower() not in NOT_A_SECRET_VALUE:
        return True
    return bool(SECRET_VALUE.search(clause)) and len(clause.split()) <= 12


# A line the safety module answers is never kept: belt and braces under the module's staging.
CRISIS = re.compile(r"\b(?:die|dying|dead|kill\s+myself|killing\s+myself|suicid\w*|end\s+(?:my|it)\s+(?:life|all)|"
                    r"hurt(?:ing)?\s+myself|self[\s-]?harm\w*|overdos\w*|not\s+want\s+to\s+(?:live|be\s+here))\b", re.I)

# Words that say a line is about now, not about the person: "i use windows at work today".
PASSING = re.compile(r"\b(?:today|tonight|right\s+now|at\s+the\s+moment|atm|this\s+(?:morning|afternoon|evening|week|"
                     r"weekend|month)|for\s+now|for\s+the\s+moment|temporarily|just\s+now|yesterday|for\s+(?:breakfast|"
                     r"lunch|dinner|tea)|this\s+time|currently)\b", re.I)

OS_NAMES = ("arch linux", "arch", "ubuntu", "debian", "fedora", "linux mint", "mint", "manjaro", "nixos", "gentoo",
            "opensuse", "suse", "pop!_os", "pop os", "popos", "void linux", "void", "alpine", "kali", "elementary os",
            "endeavouros", "endeavour", "rhel", "centos", "rocky linux", "rocky", "almalinux", "linux", "windows 11",
            "windows 10", "windows", "macos", "mac os", "mac", "osx", "os x", "freebsd", "openbsd", "wsl", "wsl2",
            "chromeos", "chrome os", "slackware", "zorin", "qubes")
EDITORS = ("vim", "neovim", "nvim", "emacs", "vscode", "vs code", "visual studio code", "nano", "helix", "sublime",
           "sublime text", "atom", "pycharm", "intellij", "zed", "kate", "gedit", "notepad++", "cursor", "vi")
SHELLS = ("bash", "zsh", "fish", "nushell", "ksh", "tcsh", "dash", "powershell", "oh my zsh")
BROWSERS = ("firefox", "chrome", "chromium", "brave", "safari", "edge", "vivaldi", "opera", "librewolf",
            "qutebrowser", "tor browser", "arc")
SPOKEN = frozenset("""english french german spanish italian portuguese dutch swedish norwegian danish finnish polish
czech russian ukrainian greek turkish arabic hebrew hindi urdu bengali punjabi tamil telugu malay indonesian
tagalog thai vietnamese chinese mandarin cantonese hokkien japanese korean swahili afrikaans welsh irish gaelic
persian farsi romanian hungarian serbian croatian bulgarian slovak catalan basque icelandic latin esperanto""".split())
CODED = frozenset("""python rust go golang java javascript js typescript ts c c++ cpp c# csharp ruby php kotlin swift
haskell ocaml elixir erlang scala lua perl r julia zig bash shell sql dart clojure f# fortran cobol nim crystal
assembly asm matlab""".split())
LANGUAGE_FILLER = frozenset("""a bit of little some fluent fluently basic native conversational and also mostly
mainly""".split())
RELATIONS = ("wife", "husband", "partner", "spouse", "son", "daughter", "kid", "child", "baby", "mum", "mom", "mother",
             "dad", "father", "brother", "sister", "boyfriend", "girlfriend", "fiance", "fiancee", "grandma",
             "grandmother", "grandpa", "grandfather", "nan", "gran", "aunt", "uncle", "cousin", "niece", "nephew",
             "best friend", "boss", "flatmate", "roommate", "manager")
ANIMALS = ("dog", "cat", "puppy", "kitten", "rabbit", "bunny", "hamster", "guinea pig", "parrot", "budgie", "bird",
           "goldfish", "fish", "horse", "tortoise", "turtle", "snake", "lizard", "gecko", "ferret", "rat", "mouse",
           "gerbil", "chicken", "pony")
JOB_NOUNS = frozenset("""engineer developer programmer designer teacher nurse doctor lawyer accountant student
manager analyst scientist researcher writer artist chef cook driver mechanic electrician plumber carpenter architect
consultant admin administrator sysadmin pharmacist dentist vet therapist farmer pilot officer marketer cashier
barista waiter waitress journalist editor photographer musician lecturer professor tutor intern freelancer
contractor technician tester pentester founder ceo cto director clerk librarian paramedic firefighter soldier
economist translator surgeon physician cleaner builder secretary receptionist banker trader actuary auditor
psychologist counsellor counselor midwife carer caregiver hacker devops sre""".split())
NOT_A_NAME = frozenset("""not a an the none nobody no secret private unknown anonymous what who whatever
irrelevant important later back tomorrow when if crazy lazy old old-fashioned paranoid maybe sometime anytime
anything something soon""".split())
_SET = r"(?:%s)"


def _alts(words):
    return _SET % "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))


def _known(value, names):
    """The name from the list that the value is, or starts with ("Arch btw" -> "arch"), else ""."""
    low = value.lower()
    for one in sorted(names, key=len, reverse=True):
        if low == one or low.startswith(one + " "):
            return one
    return ""


_FLIP = {"i": "you", "me": "you", "my": "your", "mine": "yours", "myself": "yourself", "i'm": "you're",
         "im": "you're", "i've": "you've", "ive": "you've", "i'll": "you'll", "i'd": "you'd", "am": "are",
         "we": "you", "our": "your", "ours": "yours", "us": "you", "we're": "you're", "we've": "you've"}


def second_person(text):
    """The line said back to the person: "i use my laptop" -> "you use your laptop"."""
    words = text.split(" ")
    out = []
    for index, word in enumerate(words):
        core = word.rstrip(",.;:!?")
        tail = word[len(core):]
        low = core.lower()
        if low == "was" and index and words[index - 1].lower() == "i":
            out.append("were" + tail)
        elif low in _FLIP:
            out.append(_FLIP[low] + tail)
        else:
            out.append(word)
    return " ".join(out)


def _cap(text):
    return text[:1].upper() + text[1:] if text else text


def _name_case(value):
    return " ".join(w[:1].upper() + w[1:] if w.islower() else w for w in value.split())


_CUT = re.compile(r"\s*(?:,|;|\.(?:\s|$)|!|\?|\s-\s|\s+(?:and|but|because|cause|since|so|though|although|which|who|btw|lol)\s).*$",
                  re.I)


def _value(text, words=5):
    """The value of a fact, cut at the next clause and kept short."""
    text = _CUT.sub("", " " + text + " ").strip().strip("\"'`")
    return " ".join(text.split()[:words])


def _fact(slot, value, text, tier="keep"):
    return {"slot": slot, "value": value, "text": _cap(text), "tier": tier}


def _name(found, group):
    value = _value(found.group(group), 3)
    words = value.split()
    if not words or words[0].lower() in NOT_A_NAME or not all(re.match(r"^[^\W\d_][\w'-]*$", w) for w in words):
        return ""
    return _name_case(value)


# Each reader takes the clause (lead and tail already off) and returns a fact or None.

def _read_name(clause):
    found = re.match(r"^(?:my\s+name\s+is|my\s+name's|i'?m\s+called|i\s+am\s+called|the\s+name's|people\s+call\s+me|"
                     r"i\s+go\s+by)\s+(?P<name>.+)$", clause, re.I)
    if found:
        value = _name(found, "name")
        return _fact("name", value, "your name is %s" % value) if value else None
    return None


def _read_call_me(clause):
    found = re.match(r"^(?:please\s+)?(?:call\s+me|you\s+can\s+call\s+me|just\s+call\s+me)\s+(?P<callme>[^\s,.!?]+(?:\s+[^\s,.!?]+)?)"
                     r"(?:\s+(?:from\s+now\s+on|instead|going\s+forward|from\s+now))?$", clause, re.I)
    if found:
        value = _name(found, "callme")
        if value:
            return _fact("call_me", value, "you want me to call you %s" % value, "always")
    return None


def _read_place(clause):
    found = re.match(r"^(?:i\s+live|i'?m\s+living|i\s+am\s+living|i'?m\s+based|i\s+am\s+based|i\s+reside|we\s+live|"
                     r"i\s+moved|i've\s+moved|i\s+have\s+moved)\s+(?:in|to|at)\s+(?P<place>.+)$", clause, re.I)
    if found:
        value = re.sub(r"\s+(?:now|these\s+days|with\s+.*|near\s+.*|since\s+.*|for\s+.*)$", "", _value(found.group("place"), 5),
                       flags=re.I)
        if not value or value.split()[0].lower() in ("a", "an", "my", "our", "this", "that", "here", "there", "it"):
            return None
        return _fact("city", _name_case(value) if value.islower() else value, "you live in %s" % (
            _name_case(value) if value.islower() else value))
    found = re.match(r"^(?:i'?m|i\s+am|i\s+come)\s+(?:originally\s+)?from\s+(?P<origin>.+)$", clause, re.I)
    if found:
        value = _value(found.group("origin"), 4)
        if not value or not value[:1].isalpha() or value.split()[0].lower() in ("a", "an", "my", "the", "work", "home",
                                                                                 "school", "here", "there", "it"):
            return None
        value = _name_case(value) if value.islower() else value
        return _fact("from", value, "you're from %s" % value)
    return None


def _read_job(clause):
    found = re.match(r"^(?:i\s+work\s+as|i'?m\s+employed\s+as|i\s+am\s+employed\s+as|my\s+job\s+is|my\s+profession\s+is|"
                     r"my\s+job\s+title\s+is|i\s+do\s+(?:a\s+)?job\s+as)\s+(?P<art>an?\s+)?(?P<job>.+)$", clause, re.I)
    if found:
        job = _value(found.group("job"), 8)
        if not job:
            return None
        art = found.group("art") or ""
        return _fact("job", re.split(r"\s+(?:at|for|in)\s+", job)[0], "you work as %s%s" % (art.lower(), job))
    found = re.match(r"^(?:i'?m|i\s+am)\s+(?P<art2>an?\s+)(?P<job2>(?:(?!(?:at|for|in|by)\b)[\w-]+\s+){0,3}(?!(?:at|for|in|by)\b)[\w-]+)(?:\s+by\s+trade)?"
                     r"(?P<where>\s+(?:at|for|in)\s+.+)?$", clause, re.I)
    if found and found.group("job2").split()[-1].lower().rstrip("s") in JOB_NOUNS | {"engineer"}:
        job = found.group("job2")
        where = _value(found.group("where") or "", 6)
        return _fact("job", job, "you're %s%s%s" % (found.group("art2").lower(), job, " " + where if where else ""))
    found = re.match(r"^i\s+work\s+(?P<prep>at|for|in)\s+(?P<org>.+)$", clause, re.I)
    if found:
        org = _value(found.group("org"), 5)
        low = org.lower()
        if not org or low.split()[0] in ("home", "night", "nights", "weekends", "the", "a", "an", "my", "it", "this",
                                         "that", "shifts", "bed", "silence", "peace") and not low.startswith("the "):
            return None
        if low in CODED:
            return _fact("codes", org, "you code in %s" % org)
        return _fact("workplace", org, "you work %s %s" % (found.group("prep").lower(), org))
    found = re.match(r"^i\s+study\s+(?P<subject>(?!for\b|hard\b|at\s+night)\S.*)$", clause, re.I)
    if found:
        subject = _value(found.group("subject"), 6)
        return _fact("study", subject, "you study %s" % subject) if subject else None
    return None


def _tool_slot(value):
    for slot, names in (("os", OS_NAMES), ("editor", EDITORS), ("shell", SHELLS), ("browser", BROWSERS)):
        name = _known(value, names)
        if name:
            return slot, name
    return "", ""


def _read_tools(clause):
    found = re.match(r"^(?:i\s+(?:use|run|daily[\s-]?drive|mostly\s+use|mainly\s+use|use\s+mostly|main|prefer\s+to\s+use)|"
                     r"i'?m\s+(?:on|using|running)|i\s+am\s+(?:on|using|running))\s+(?P<tool>.+)$", clause, re.I)
    if found:
        value = re.sub(r"\s+(?:btw|by\s+the\s+way|as\s+my\s+(?:os|distro|editor|shell|browser|daily\s+driver)|"
                       r"on\s+my\s+\w+|at\s+(?:home|work)|for\s+(?:everything|work|coding|most\s+things))$", "",
                       _value(found.group("tool"), 5), flags=re.I)
        if not value:
            return None
        slot, _ = _tool_slot(value)
        verb = found.group(0)[:found.start("tool")].strip().lower()
        said = value.split(" for ")[0] if slot else value
        if slot:
            return _fact(slot, said, "you use %s" % said)
        if re.match(r"^(?:metric|imperial)(?:\s+units)?$", value, re.I):
            return _fact("units", value.split()[0].lower(), "you use %s units" % value.split()[0].lower(), "always")
        if not verb.startswith("i use") and not verb.startswith("i mostly") and not verb.startswith("i mainly"):
            return None  # "i'm on a train", "i run every morning": only named tools count after these
        first = value.split()[0].lower()
        if first in ("a", "an", "the", "my", "it", "this", "that", "them", "to", "too", "every", "some", "lots", "so",
                     "public", "your", "his", "her", "their", "our", "all", "any", "no", "more", "less", "up", "drugs"):
            return None
        return _fact("uses:" + value.lower(), value, "you use %s" % value)
    found = re.match(r"^my\s+(?P<kind>os|operating\s+system|distro|editor|text\s+editor|shell|browser|daily\s+driver)"
                     r"\s+is\s+(?P<thing>.+)$", clause, re.I)
    if found:
        value = _value(found.group("thing"), 4)
        kind = found.group("kind").lower()
        slot = {"operating system": "os", "distro": "os", "daily driver": "os", "text editor": "editor"}.get(kind, kind)
        return _fact(slot, value, "you use %s" % value) if value else None
    return None


def _languages(value, known):
    words = [w for w in re.split(r"[\s,/&]+", value.lower()) if w]
    real = [w for w in words if w not in LANGUAGE_FILLER]
    return bool(real) and all(w in known for w in real)


def _read_languages(clause):
    found = re.match(r"^i\s+(?:can\s+)?speak\s+(?P<spoken>.+)$", clause, re.I)
    if found and _languages(found.group("spoken"), SPOKEN):
        value = found.group("spoken")
        return _fact("speaks", value, "you speak %s" % value)
    found = re.match(r"^i\s+(?:mostly\s+|mainly\s+)?(?:code|program|write\s+code|develop|write\s+software)\s+in\s+(?P<coded>.+)$",
                     clause, re.I)
    if found and _languages(found.group("coded"), CODED):
        value = found.group("coded")
        return _fact("codes", value, "you code in %s" % value)
    return None


def _read_people(clause):
    rel, animal = _alts(RELATIONS), _alts(ANIMALS)
    found = re.match(r"^my\s+(?P<who>%s|%s)(?:'s|s)?\s+(?:name\s+is|is\s+called|is\s+named|called|named)\s+(?P<pname>.+)$"
                     % (rel, animal), clause, re.I)
    if not found:
        found = re.match(r"^(?:i\s+have|i've\s+got|ive\s+got|i\s+got|we\s+have)\s+an?\s+(?P<who>%s|%s)\s+(?:called|named)\s+"
                         r"(?P<pname>.+)$" % (rel, animal), clause, re.I)
    if not found:
        return None
    who = found.group("who").lower()
    value = _name(found, "pname")
    if not value:
        return None
    kind = "pet" if who in ANIMALS else "family"
    return _fact("%s:%s" % (kind, who), value, "your %s is called %s" % (who, value))


def _read_body(clause):
    found = re.match(r"^(?:i'?m|i\s+am|im)\s+(?:very\s+|really\s+|severely\s+|deathly\s+)?allergic\s+to\s+(?P<allergen>.+)$",
                     clause, re.I)
    if found:
        value = _value(found.group("allergen"), 6) if " and " not in found.group("allergen") else \
            " ".join(found.group("allergen").split()[:6])
        return _fact("allergy:" + value.lower(), value, "you're allergic to %s" % value) if value else None
    found = re.match(r"^i\s+have\s+an?\s+(?P<thing>[\w\s]{2,30}?)\s+allergy$", clause, re.I)
    if found:
        value = found.group("thing")
        return _fact("allergy:" + value.lower(), value, "you're allergic to %s" % value)
    found = re.match(r"^(?:i'?m|i\s+am|im)\s+(?:an?\s+)?(?P<diet>vegetarian|vegan|pescatarian|pescetarian|halal|kosher|"
                     r"lactose\s+intolerant|gluten\s+free)$", clause, re.I)
    if found:
        value = found.group("diet").lower()
        return _fact("diet", value, "you're %s" % value)
    found = re.match(r"^my\s+pronouns\s+are\s+(?P<pronouns>\S+)$", clause, re.I)
    if found:
        return _fact("pronouns", found.group("pronouns"), "your pronouns are %s" % found.group("pronouns"))
    found = re.match(r"^my\s+(?:birthday|bday|date\s+of\s+birth)\s+is\s+(?:on\s+)?(?P<bday>.+)$", clause, re.I)
    if found:
        value = _value(found.group("bday"), 5)
        return _fact("birthday", value, "your birthday is %s" % value) if value else None
    found = re.match(r"^my\s+time\s*zone\s+is\s+(?P<tz>\S+(?:\s+\S+)?)$", clause, re.I)
    if found:
        return _fact("timezone", found.group("tz"), "your timezone is %s" % found.group("tz"))
    return None


def _read_favourite(clause):
    found = re.match(r"^my\s+(?:favourite|favorite|fave|fav)\s+(?P<thing>[a-z][a-z\s-]{0,30}?)\s+(?P<verb>is|are)\s+(?P<fav>.+)$",
                     clause, re.I)
    if found:
        thing, value = found.group("thing").lower(), _value(found.group("fav"), 6)
        verb = found.group("verb").lower()
        return _fact("favourite:" + thing, value, "your favourite %s %s %s" % (thing, verb, value)) if value else None
    return None


def _read_rule(clause):
    found = re.match(r"^(?:please\s+)?(?P<how>always|never|from\s+now\s+on,?|going\s+forward,?|in\s+future,?)\s+(?:please\s+)?"
                     r"(?P<rule>(?:use|answer|reply|respond|give|say|show|call|talk|speak|write|keep|ask|include|put|start|"
                     r"end|add|tell|mention|assume|convert|round|list|explain|be|make|send|format|swear|curse)\b.+)$",
                     clause, re.I)
    if found:
        how = found.group("how").rstrip(",").lower()
        rule = found.group("rule").strip()
        units = re.search(r"\b(metric|imperial|celsius|fahrenheit|kilometres|kilometers|miles|kg|pounds)\b", rule, re.I)
        slot = "units" if units and how != "never" else "rule:" + " ".join(re.findall(r"[a-z0-9]+", rule.lower())[:6])
        if re.search(r"\b(?:answers?|repl(?:y|ies)|responses?)\b.*\b(?:short|brief|concise|long|longer|detailed|shorter)\b",
                     rule, re.I):
            slot = "answers"
        said = "you want me to %s %s" % (how, rule) if how in ("always", "never") else \
            "you want me to %s %s" % (rule, how)
        return _fact(slot, rule, said, "always")
    found = re.match(r"^(?:please\s+)?(?:keep|make)\s+(?:your\s+|the\s+)?(?P<what>answers|replies|responses|it)\s+"
                     r"(?P<size>short|brief|concise|shorter|long|longer|detailed)(?:\s+from\s+now\s+on|\s+in\s+future)$",
                     clause, re.I)
    if found:
        size = found.group("size").lower()
        return _fact("answers", size, "you want %s answers" % size, "always")
    found = re.match(r"^i\s+(?:prefer|like|want)\s+(?P<size2>short|brief|concise|shorter|long|longer|detailed)\s+"
                     r"(?:answers|replies|responses)$", clause, re.I)
    if found:
        size = found.group("size2").lower()
        return _fact("answers", size, "you prefer %s answers" % size, "always")
    found = re.match(r"^i\s+(?:always\s+)?prefer\s+(?P<pref>.+)$", clause, re.I)
    if found:
        value = _value(found.group("pref"), 8)
        if not value:
            return None
        head = re.split(r"\s+(?:over|to|than|instead\s+of|rather\s+than)\s+", value)[0]
        return _fact("prefer:" + (head.split()[-1].lower() if head else value.lower()), value,
                     "you prefer %s" % value, "always")
    return None


def _read_my(clause):
    """Only after "remember": "remember my server ip is 10.0.0.1" -> "your server ip is 10.0.0.1"."""
    found = re.match(r"^my\s+(?P<mything>[a-z][\w\s'-]{0,30}?)\s+(?P<verb>is|are|was)\s+(?P<myvalue>.+)$", clause, re.I)
    if found:
        thing, value = found.group("mything").lower(), _value(found.group("myvalue"), 10)
        if value:
            return _fact("my:" + thing, value, "your %s %s %s" % (thing, found.group("verb").lower(), value))
    return None


READERS = (_read_name, _read_call_me, _read_rule, _read_place, _read_body, _read_people, _read_favourite,
           _read_languages, _read_tools, _read_job)

REMEMBER = re.compile(r"^(?:(?:please\s+)?(?:remember|don'?t\s+forget|do\s+not\s+forget|never\s+forget|keep\s+in\s+mind|"
                      r"note|make\s+sure\s+you\s+remember|i\s+want\s+you\s+to\s+remember|for\s+future\s+reference)"
                      r"(?P<how>\s+that\s+|\s*:\s*|\s*,\s*|\s+this\s*:\s*|\s+))(?P<what>\S.*)$", re.I)


def _remember_inner(clause):
    """The thing a "remember ..." line asks to keep, or "" when it is not that kind of line."""
    found = REMEMBER.match(_ASK_LEAD.sub("", clause))
    if not found:
        return ""
    what, how = found.group("what").strip(), found.group("how").strip()
    if clause.lower().startswith("note") and not how:
        return ""  # "note down ...", "note to self": the notes tool's
    if how in ("that", ":", "this:", "this :"):
        return what
    # "remember my editor is vim", "remember i use arch": the bare form needs the person in it.
    # "remember the good times", "remember to buy milk", "remember when ..." are not about the person.
    if re.match(r"^(?:my|i|i'm|im|i've|i'd|i\s+am|we|we're|our|me)\b", what, re.I):
        return what
    return ""


def score(text):
    """How a line is kept: {"tier": "never"|"always"|"keep"|"chat"|None, "fact": dict or None, "why": str}.

    tier None means the line is not about the person at all (nothing to keep or refuse).
    """
    clause = _clause(text)
    inner = _remember_inner(clause)
    if inner and CRISIS.search(inner):
        return {"tier": None, "fact": None, "why": "a line for the safety module"}
    if _secret_said(clause) or (inner and looks_secret(inner)):
        return {"tier": "never", "fact": None, "why": "it looks like a password, key, token or card number"}
    if inner:
        inner_clause = _clause(inner)
        fact = None
        for reader in READERS + (_read_my,):
            fact = reader(inner_clause)
            if fact:
                break
        if not fact:
            said = second_person(inner_clause)
            words = re.findall(r"[a-z0-9]+", said.lower())
            fact = _fact("note:" + " ".join(words[:8]), said, said)
        fact["tier"] = "always"
        return {"tier": "always", "fact": fact, "why": "you asked me to remember it"}
    for reader in READERS:
        fact = reader(clause)
        if fact:
            if looks_secret(clause):
                return {"tier": "never", "fact": None, "why": "it looks like a password, key, token or card number"}
            if fact["tier"] == "always":
                if PASSING.search(clause):
                    return {"tier": "chat", "fact": fact, "why": "it is only for now"}
                return {"tier": "always", "fact": fact, "why": "a standing preference"}
            if PASSING.search(clause):
                return {"tier": "chat", "fact": fact, "why": "it is only for now"}
            return {"tier": "keep", "fact": fact, "why": "a stable fact about you"}
    return {"tier": None, "fact": None, "why": ""}


# --- the controls --------------------------------------------------------------------------------

FORGET_ALL = re.compile(
    r"^(?:please\s+)?(?:(?:forget|delete|erase|wipe|clear|remove|drop)\s+(?:absolutely\s+)?(?:everything|all|it\s+all|all\s+of\s+it)"
    r"(?:\s+(?:that\s+)?you(?:'ve|\s+have)?\s+(?:know|kept|got|learned|learnt|stored|saved|remember(?:ed)?|have))?"
    r"(?P<me>\s+(?:about|on|of)\s+me)?(?:\s+(?:from\s+)?(?:your\s+memory|my\s+profile))?"
    r"|(?:forget|delete|erase|wipe|clear|reset|remove)\s+(?:all\s+about\s+me|me|my\s+profile|your\s+memory(?:\s+of\s+me)?|"
    r"what\s+you\s+(?:know|remember)\s+about\s+me|everything\s+about\s+me|my\s+data)"
    r"|start\s+(?:over\s+)?with\s+a\s+(?:clean|blank)\s+(?:slate|profile))$", re.I)
CONFIRM_YES = re.compile(r"^(?:yes|yeah|yep|yup|sure|ok|okay|do\s+it|go\s+ahead|confirm|please\s+do|yes\s+please|"
                         r"yes,?\s+forget\s+(?:it\s+all|everything)(?:\s+about\s+me)?)$", re.I)
ASK_MARK = "Forget everything I keep about you across chats"
FORGET_ONE = re.compile(r"^(?:please\s+)?(?:forget|delete|remove|erase|drop|unlearn|stop\s+remembering|don'?t\s+remember|"
                        r"do\s+not\s+remember|you\s+can\s+forget)\s+(?:that\s+|about\s+|the\s+fact\s+that\s+)?(?P<what>\S.*)$",
                        re.I)
RECALL_ALL = re.compile(
    r"^(?:(?:so\s+)?(?:what|which\s+things)\s+(?:else\s+)?(?:do|did|have)\s+you\s+(?:remember(?:ed)?|know|kept|keep|stored|store|"
    r"saved|learn(?:ed|t)?|got)\s+(?:about|on|of)\s+me|what\s+(?:have|did)\s+you\s+(?:kept|keep|stored|saved|remembered)(?:\s+about\s+me)?"
    r"|(?:tell\s+me|show\s+me|list)\s+(?:what|everything)\s+you\s+(?:remember|know|keep|have\s+kept|have\s+saved)\s+about\s+me"
    r"|what(?:'s|s|\s+is)\s+in\s+my\s+profile|(?:show|list)\s+(?:me\s+)?my\s+profile|what\s+did\s+i\s+(?:ask|tell)\s+you\s+to\s+remember"
    r"|what\s+do\s+you\s+remember(?:\s+about\s+me)?|do\s+you\s+remember\s+(?:anything|me)(?:\s+about\s+me)?"
    r"|what\s+do\s+you\s+know\s+about\s+me|who\s+am\s+i\s+to\s+you)$", re.I)

# "what's my name", "do you remember where i live": asks about one slot.
_ASK_PREFIX = re.compile(r"^(?:(?:do|can|could|did)\s+you\s+(?:still\s+)?(?:remember|recall|know|tell\s+me)\s+|remind\s+me\s+|"
                         r"you\s+remember\s+)", re.I)
ASKS = (
    ("name", re.compile(r"^(?:what(?:'s|s|\s+is|\s+was)\s+my\s+name|my\s+name|what\s+my\s+name\s+is|who\s+i\s+am|who\s+am\s+i|"
                        r"what\s+(?:do\s+you|should\s+you|did\s+i\s+say\s+to)\s+call\s+me|what\s+did\s+i\s+say\s+my\s+name\s+(?:is|was))"
                        r"(?:\s+again)?$", re.I)),
    ("city", re.compile(r"^(?:where\s+do\s+i\s+live|where\s+i\s+live|where(?:'s|\s+is)\s+home|where\s+am\s+i\s+based|"
                        r"where\s+did\s+i\s+say\s+i\s+live|which\s+(?:city|country|town)\s+do\s+i\s+live\s+in)(?:\s+again)?$", re.I)),
    ("from", re.compile(r"^(?:where\s+am\s+i\s+from|where\s+i(?:'m|\s+am)\s+from|where\s+do\s+i\s+come\s+from)(?:\s+again)?$",
                        re.I)),
    ("job", re.compile(r"^(?:what(?:'s|s|\s+is)\s+my\s+(?:job|profession|occupation|line\s+of\s+work)|my\s+job|what\s+i\s+do"
                       r"(?:\s+for\s+(?:a\s+living|work))?|what\s+do\s+i\s+do(?:\s+for\s+(?:a\s+living|work))?|"
                       r"what\s+(?:is\s+my|my)\s+job\s+is)(?:\s+again)?$", re.I)),
    ("workplace", re.compile(r"^(?:where\s+do\s+i\s+work|where\s+i\s+work)(?:\s+again)?$", re.I)),
    ("thing", re.compile(r"^(?:what|which)\s+(?P<kind>os|operating\s+system|distro|linux|editor|text\s+editor|shell|browser|"
                         r"languages?|programming\s+languages?)\s+(?:do\s+i|i)\s+(?:use|run|speak|code\s+in|prefer|like)"
                         r"(?:\s+again)?$", re.I)),
    ("fav", re.compile(r"^(?:what(?:'s|s|\s+is|\s+are)\s+my|my)\s+(?:favourite|favorite|fave|fav)\s+(?P<favthing>[a-z][a-z\s-]{0,30}?)"
                       r"(?:\s+again)?$", re.I)),
    ("called", re.compile(r"^(?:what(?:'s|s|\s+is)\s+my\s+(?P<whose>[a-z][a-z\s]{1,20}?)(?:'s|s)?\s+(?:name|called)|"
                          r"what\s+(?:is|'s)\s+my\s+(?P<whose2>[a-z][a-z\s]{1,20}?)\s+called|"
                          r"what\s+did\s+i\s+(?:say|call)\s+my\s+(?P<whose3>[a-z][a-z\s]{1,20}?)(?:\s+was\s+called)?)(?:\s+again)?$",
                          re.I)),
    ("allergy", re.compile(r"^(?:what\s+am\s+i\s+allergic\s+to|am\s+i\s+allergic\s+to\s+anything|do\s+i\s+have\s+any\s+allergies|"
                           r"what\s+(?:are\s+)?my\s+allergies(?:\s+are)?|what\s+i(?:'m|\s+am)\s+allergic\s+to)(?:\s+again)?$", re.I)),
    ("my", re.compile(r"^(?:what(?:'s|s|\s+is|\s+are)\s+my|what\s+did\s+i\s+say\s+my)\s+(?P<mything>[a-z][\w\s'-]{0,30}?)"
                      r"(?:\s+(?:is|was|are))?(?:\s+again)?$", re.I)),
)
_KIND_SLOT = {"os": "os", "operating system": "os", "distro": "os", "linux": "os", "editor": "editor",
              "text editor": "editor", "shell": "shell", "browser": "browser", "language": "speaks",
              "languages": "speaks", "programming language": "codes", "programming languages": "codes"}


def _asked_slots(clause):
    """(label, [slot prefixes]) for a question about one fact, or (None, [])."""
    question = _ASK_PREFIX.sub("", clause.rstrip("?").strip())
    question = re.sub(r"\s+(?:is|was)$", "", question, flags=re.I) if question.lower().startswith(("what my", "where i")) \
        else question
    for label, pattern in ASKS:
        found = pattern.match(question)
        if not found:
            continue
        if label == "name":
            return label, ["call_me", "name"]
        if label in ("city", "from", "job", "workplace"):
            return label, {"city": ["city"], "from": ["from"], "job": ["job"], "workplace": ["workplace"]}[label]
        if label == "thing":
            kind = " ".join(found.group("kind").lower().split())
            return label, [_KIND_SLOT.get(kind, kind)]
        if label == "fav":
            return label, ["favourite:" + found.group("favthing").lower().strip()]
        if label == "called":
            who = (found.group("whose") or found.group("whose2") or found.group("whose3") or "").lower().strip()
            return label, ["pet:" + who, "family:" + who]
        if label == "allergy":
            return label, ["allergy:"]
        if label == "my":
            thing = found.group("mything").lower().strip()
            if thing in ("name", "job"):
                return label, [thing]
            return label, ["my:" + thing, "favourite:" + thing, "family:" + thing, "pet:" + thing]
    return None, []


def _matching(slots, kept):
    out = []
    for fact in kept:
        slot = str(fact.get("slot", ""))
        if any(slot == s or (s.endswith(":") and slot.startswith(s)) for s in slots):
            out.append(fact)
    return out


_STOP = frozenset("""i you me my your that the a an is am are was were be to of in on at for and or it this about
what where who do does did have has had use uses used please again just all any that's thats""".split())


def _words(text):
    return {w for w in re.findall(r"[a-z0-9+#]+", text.lower()) if w not in _STOP}


def _to_forget(what, kept):
    """The kept facts a "forget ..." line names."""
    clause = _clause(what)
    if not clause:
        return []
    for reader in READERS + (_read_my,):
        fact = reader(clause)
        if fact:
            same = [f for f in kept if f.get("slot") == fact["slot"]]
            if same:
                return same
            break
    label, slots = _asked_slots(clause)
    if not slots:
        bare = re.sub(r"^(?:my|where\s+i|what\s+i)\s+", "", clause, flags=re.I).strip().lower()
        _, slots = _asked_slots("what's my " + bare)
    if slots:
        hits = _matching(slots, kept)
        if hits:
            return hits
    words = _words(second_person(clause))
    if not words:
        return []
    return [f for f in kept if words <= _words(f.get("text", "")) | _words(str(f.get("value", "")))]


def _listing(kept):
    lines = ["  - %s" % f["text"] for f in kept[-40:]]
    return lines


def _clause_of(fact):
    text = fact.get("text", "")
    return text[:1].lower() + text[1:] if text[:2] not in ("I ", "I'") else text


def classify(text, memory=None):
    """What kind of line this is, without doing anything: (kind, detail).

    kinds: "secret", "remember", "fact", "chat", "forget_all", "forget_all_ask", "confirm_forget",
    "forget", "recall_all", "recall", or None.
    """
    if not text or len(text) > 1000:
        return None, None
    clause = _clause(text)
    if not clause:
        return None, None
    plain = _ASK_LEAD.sub("", clause)
    if CONFIRM_YES.match(clause) and ASK_MARK in _last_bot(memory):
        return "confirm_forget", None
    found = FORGET_ALL.match(plain)
    if found:
        bare = re.match(r"^(?:please\s+)?(?:forget|delete|erase|wipe|clear|remove|drop)\s+(?:everything|all|it\s+all|all\s+of\s+it)$",
                        plain, re.I)
        return ("forget_all_ask" if bare else "forget_all"), None
    found = FORGET_ONE.match(plain)
    if found and not re.match(r"^(?:it|about\s+it|that|this|i\s+said\s+.*|what\s+i\s+said.*|i\s+asked.*|everything|"
                              r"all|you|the\s+whole\s+thing|it\s+all)$", found.group("what"), re.I):
        return "forget", found.group("what")
    question = clause.rstrip("?").strip()
    if RECALL_ALL.match(question):
        return "recall_all", None
    label, slots = _asked_slots(clause)
    if slots:
        return "recall", (label, slots)
    scored = score(text)
    tier = scored["tier"]
    if tier == "never":
        return "secret", scored
    if tier == "always":
        return "remember", scored
    if tier == "keep":
        return "fact", scored
    if tier == "chat":
        return "chat", scored
    return None, None


def _last_bot(memory):
    turns = (memory or {}).get("turns") if isinstance(memory, dict) else None
    if isinstance(turns, list) and turns and isinstance(turns[-1], dict):
        return str(turns[-1].get("bot") or "")
    return ""


def _keep(fact):
    """Store fact, replacing the facts in its slot. Returns the facts it replaced (for the reply)."""
    data = _load()
    old = [f for f in data["facts"] if f.get("slot") == fact["slot"]]
    entry = dict(fact)
    entry["saved"] = datetime.datetime.now().astimezone().isoformat(timespec="minutes")

    def write():
        with _LOCK:
            fresh = _load()
            fresh["facts"] = [f for f in fresh["facts"] if f.get("slot") != entry["slot"]] + [entry]
            _save(fresh)

    _do(write)
    return old


def _drop(gone):
    slots_texts = {(f.get("slot"), f.get("text")) for f in gone}

    def write():
        with _LOCK:
            fresh = _load()
            fresh["facts"] = [f for f in fresh["facts"] if (f.get("slot"), f.get("text")) not in slots_texts]
            _save(fresh)

    _do(write)


READ_ONLY = ("Writing is switched off (--read-only), so I can't keep anything across chats right now. "
             "This chat still has it until it ends.")


def answer(text, memory=None):
    """The reply to a line about what PyBot keeps about the person, or None. Writes straight away."""
    kind, detail = classify(text, memory)
    if kind is None or kind == "chat":
        return None
    where = _tilde(store_path())
    if kind == "secret":
        return ("I won't keep that: %s, and I never write those down, not even when asked. "
                "A password manager is the right place for it." % detail["why"])
    if kind in ("remember", "fact"):
        fact = detail["fact"]
        if not writing_allowed():
            return READ_ONLY
        old = _keep(fact)
        said = _clause_of(fact)
        before = [f for f in old if f.get("text", "").lower() != fact["text"].lower()]
        if before:
            return "Got it: %s now (I had \"%s\"). I'll remember that in later chats too." % (said, _clause_of(before[-1]))
        if kind == "remember":
            return ("I'll remember that %s, in this chat and the next ones (kept in %s, only on this machine). "
                    "\"what do you remember about me\" lists what I keep." % (said, where))
        return "Noted: %s. I'll remember that in later chats too." % said
    kept = facts()
    if kind == "recall_all":
        if not kept:
            return ("I haven't kept anything about you across chats yet. Say \"remember that ...\", or tell me "
                    "things like your name or the OS you use, and I'll keep them in %s." % where)
        return "Here's what I keep about you across chats (in %s):\n%s\nSay \"forget that ...\" to drop one, " \
               "or \"forget everything about me\" to clear it." % (where, "\n".join(_listing(kept)))
    if kind == "recall":
        label, slots = detail
        hits = _matching(slots, kept)
        if not hits:
            return "I don't have that kept from earlier chats."
        if label == "name":
            name = [f for f in hits if f["slot"] == "name"]
            call = [f for f in hits if f["slot"] == "call_me"]
            if name and call and name[-1]["value"] != call[-1]["value"]:
                return "Your name is %s, and you asked me to call you %s." % (name[-1]["value"], call[-1]["value"])
            value = (call or name)[-1]["value"]
            return "You're %s." % value
        return " ".join("%s." % f["text"].rstrip(".") for f in hits)
    if kind in ("forget_all", "forget_all_ask", "confirm_forget"):
        if not kept:
            return "There's nothing to forget: I haven't kept anything about you across chats."
        if kind == "forget_all_ask":
            return ("%s (%d %s, in %s)? Say \"yes\" or \"forget everything about me\" to clear it. "
                    "This chat itself is forgotten when you /reset." % (ASK_MARK, len(kept),
                                                                       "thing" if len(kept) == 1 else "things", where))
        if not writing_allowed():
            return READ_ONLY.replace("keep anything across chats", "change what I keep")
        _drop(kept)
        return ("Done: I've forgotten all %d %s I kept about you, and %s is empty now. "
                "That can't be undone." % (len(kept), "thing" if len(kept) == 1 else "things", where))
    if kind == "forget":
        gone = _to_forget(detail, kept)
        if not gone:
            return "I don't have that kept, so there's nothing to forget. \"what do you remember about me\" lists what I keep."
        if not writing_allowed():
            return READ_ONLY.replace("keep anything across chats", "change what I keep")
        _drop(gone)
        return "Forgotten: %s. I won't bring %s up in later chats." % (
            "; ".join(_clause_of(f) for f in gone), "it" if len(gone) == 1 else "them")
    return None


def forgotten_slots(text, memory=None):
    """The slots a forget line would drop (for the module to clear the chat's copy too)."""
    kind, detail = classify(text, memory)
    kept = facts()
    if kind in ("forget_all", "confirm_forget"):
        return [f.get("slot") for f in kept]
    if kind == "forget":
        return [f.get("slot") for f in _to_forget(detail, kept)]
    return []
