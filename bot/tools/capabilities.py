"""Questions about PyBot itself: "can you read files?", "what can you do?", "are you online?".

Not part of the swarm's original bot. These are answered from the table below, never searched:
a question about the bot sent to a search service comes back with pages about other bots. Each
answer says what is switched on right now, so it tells the truth for this run:

- web search only when exa.available() (EXA_API_KEY is set and PYBOT_WEB is not 0);
- site checks only when PYBOT_WEB is not 0;
- the local commands only when PYBOT_LOCAL is not 0;
- notes, reminders and saving to a file only when PYBOT_WRITE is not 0.

Each answer gives one or two lines to try. `answer(text)` is the reply, or None when the line
is not a question about PyBot ("can you believe it rained", "can you pass me the salt", "can you
find all python files in src", which is an ask to do it, not a question about whether it can).
"""
import importlib.util
import re

from . import enabled as web_enabled
from . import exa, local, notes

# "can you ...", "are you able to ...", "do you have ...", "is it possible for you to ...".
_ASK = re.compile(
    r"^\s*(?:(?:hey|hi|ok|okay|so|and|but|pybot|bot)[,!\s]+)*"
    r"(?:(?:can|could|will|would|do|does|are|r)\s+(?:you|u|ya|pybot)|is\s+it\s+possible\s+for\s+(?:you|u)\s+to|"
    r"(?:have|has)\s+(?:you|u)\s+got|how\s+(?:do|can|would)\s+(?:you|u))\s+"
    r"(?:(?:even|actually|also|really|ever|still|now)\s+)*(?:(?:be\s+)?able\s+to\s+|capable\s+of\s+|allowed\s+to\s+)?"
    r"(?P<rest>.+?)\s*[?.!]*\s*$", re.I)
# "what can you do", "what tools do you have", "help": the whole table.
_OVERVIEW = re.compile(
    r"^\s*(?:(?:hey|hi|ok|okay|so|pybot|bot)[,!\s]+)*(?:"
    r"what\s+(?:else\s+|all\s+|exactly\s+)?(?:can|could)\s+(?:you|u)\s+(?:do|help\s+(?:me\s+)?with)(?:\s+for\s+me)?|"
    r"what\s+are\s+(?:you|u)\s+(?:able\s+to\s+do|capable\s+of|good\s+at|for)|what\s+do\s+(?:you|u)\s+do|"
    r"what\s+(?:tools|commands|features|abilities|capabilities|skills|powers)\s+(?:do|have)\s+(?:you|u)(?:\s+got|\s+have)?|"
    r"(?:list|show(?:\s+me)?)\s+(?:your|the)\s+(?:tools|commands|capabilities|abilities|features)|"
    r"what\s+can\s+i\s+ask\s+(?:you|u)(?:\s+to\s+do)?|what\s+(?:do|can)\s+(?:you|u)\s+know\s+how\s+to\s+do|"
    r"(?:what\s+are\s+)?your\s+(?:tools|capabilities|abilities|features))"
    r"\s*[?.!]*\s*$", re.I)
_MY = r"(?:(?:my|the|any|local|all|your|our|some|other|people'?s)\s+)*"
_FILES = r"(?:files?|folders?|directories|documents?|docs|code|disk|hard\s*drive|drive|computer|pc|laptop|machine|system)"
_TAIL = r"(?:\s+(?:on|in|from|of)\s+" + _MY + r"(?:computer|pc|laptop|machine|system|disk|home(?:\s+folder)?))?" \
        r"(?:\s+(?:for\s+me|for\s+(?:something|anything|stuff|things|text|words)|at\s+all|too|as\s+well))*"

# (topic, pattern for the words after "can you"), most specific first.
_TOPICS = (
    ("delete", r"(?:delete|remove|rm|erase|wipe|trash|kill|move|rename|clean\s+up)\s+" + _MY +
     r"(?:files?|folders?|directories|documents?|things|stuff|processes|programs)" + _TAIL),
    ("edit", r"(?:edit|change|modify|write\s+to|write|create|make|save|overwrite|fix)\s+" + _MY +
     r"(?:files?|folders?|documents?|code)" + _TAIL),
    ("search_files", r"(?:search|grep|look\s+(?:through|inside|in)|go\s+through|find\s+(?:things|stuff|text|words)\s+in|"
     r"find)\s+(?:in(?:side)?\s+|through\s+)?" + _MY + _FILES + _TAIL),
    ("read_files", r"(?:read|open|see|look\s+at|view|access|get\s+(?:to|into)|show(?:\s+me)?|list|browse)\s+" + _MY + _FILES + _TAIL +
     r"|(?:have\s+)?access\s+to\s+" + _MY + _FILES + _TAIL + r"|(?:have\s+)?(?:file|disk)\s+access"),
    ("commands", r"(?:run|execute|use)\s+(?:(?:shell|terminal|linux|bash|system|local)\s+)?"
     r"(?:commands?|programs?|scripts?|code|the\s+(?:terminal|shell)|a\s+(?:terminal|shell)|things|stuff)" + _TAIL +
     r"|(?:use|access)\s+(?:the\s+)?(?:terminal|shell|command\s+line)" + _TAIL),
    ("screen", r"(?:see|look\s+at|watch|read|view|access)\s+(?:my\s+|the\s+)?(?:screen|desktop|monitor|display)|"
     r"take\s+(?:a\s+)?screenshots?|see\s+what\s+i(?:'m|\s+am)\s+doing|(?:use|access|see\s+through)\s+(?:my\s+|the\s+)?"
     r"(?:camera|webcam|mic|microphone)|see\s+me|hear\s+me|see\s+images?|look\s+at\s+(?:images?|pictures?|photos?)"),
    ("reminders", r"(?:set|make|create|add|do|keep)\s+(?:a\s+|any\s+)?(?:reminders?|alarms?|timers?)|remind\s+(?:me|people|us)"
     r"(?:\s+(?:of|about)\s+(?:things|stuff))?"),
    ("notes", r"(?:take|make|keep|save|write)\s+(?:a\s+)?notes?(?:\s+for\s+me)?"),
    ("memory", r"remember\s+(?:things|stuff|anything|what\s+i\s+(?:say|said|tell\s+you)|me|our\s+(?:chats?|conversations?)|"
     r"(?:past\s+|previous\s+|old\s+)?conversations?|between\s+(?:chats|sessions))|remember|"
     r"(?:have\s+)?(?:a\s+)?memory|learn(?:\s+(?:things|from\s+me))?"),
    ("email", r"(?:send|write|read|check)\s+(?:an?\s+|my\s+)?(?:e-?mails?|texts?|messages?|sms|whatsapps?|dms?)|"
     r"(?:make|place)\s+(?:phone\s+)?calls?|call\s+(?:people|someone)|(?:post|tweet)\s+(?:on|to)\s+\S+|"
     r"(?:buy|order|book|pay\s+for)\s+(?:things|stuff|tickets|flights)"),
    ("site", r"(?:check|test|ping|inspect|audit)\s+(?:if\s+)?(?:a\s+|any\s+)?(?:websites?|sites?|urls?|links?|pages?|servers?)"
     r"(?:\s+(?:is|are)\s+(?:up|down))?|(?:browse|visit|open|read)\s+(?:a\s+|any\s+)?(?:websites?|sites?|web\s*pages?|urls?|links?|pages?)"),
    ("web", r"(?:search|google|browse|surf|use|access|get\s+on|go\s+on|reach|see)\s+(?:the\s+)?(?:web|internet|net|online|google)|"
     r"(?:look|search)\s+(?:things|stuff)\s+up(?:\s+online|\s+on\s+the\s+(?:web|internet))?|"
     r"look\s+up\s+(?:things|stuff)(?:\s+online)?|(?:search|look\s+things\s+up)\s+online|"
     r"(?:connected|connect)\s+to\s+the\s+(?:internet|web|net)|online|on\s+the\s+(?:internet|web)|"
     r"(?:have\s+)?(?:internet|web)(?:\s+access)?|(?:get|find)\s+(?:the\s+)?(?:news|live\s+information|current\s+information)"),
    ("git", r"(?:use|read|check|see)\s+(?:my\s+)?(?:git|repos?|repositories|commits)"),
    ("time", r"(?:tell|give)\s+(?:me\s+)?the\s+time|(?:do|convert)\s+(?:units|timestamps|base64|maths?|math|sums)"),
)
_TOPIC_RES = tuple((name, re.compile(r"^(?:" + body + r")$", re.I)) for name, body in _TOPICS)


def _suggests():
    """True when bot/tools/suggest.py is there: destructive asks get the command shown, never run."""
    try:
        return importlib.util.find_spec(__package__ + ".suggest") is not None
    except (ImportError, ValueError):
        return False


def _state():
    return {"web": web_enabled(), "search": exa.available(), "local": local.enabled(),
            "write": notes.writing_allowed()}


def _try(*lines):
    return " Try: " + " or ".join("\"%s\"" % line for line in lines) + "."


def _overview(on):
    parts = []
    if on["local"]:
        parts.append("find and search files in your home folder, show a file, list a folder, and answer git and "
                     "machine questions (disk space, memory, ports) by running read-only commands like find, grep, "
                     "ls, git and df")
    else:
        parts.append("nothing on your files right now (the local tools are switched off)")
    if on["search"]:
        parts.append("search the web")
    if on["web"]:
        parts.append("check whether a website is up and read a page you name")
    parts.append("tell the time and convert units, timestamps and encodings")
    if on["write"]:
        parts.append("keep notes and set reminders")
    text = "I'm a chatbot made of rules, with a few tools. I can " + ", ".join(parts[:-1]) + ", and " + parts[-1] + "."
    if not on["search"]:
        text += " Web search is off right now (no EXA_API_KEY is set), so I can't search online."
    text += " I never delete, move or change your files%s, I stay inside your home folder, and I never show keys or tokens." % (
        " (I show you the command to run yourself instead)" if _suggests() else "")
    tries = ["find all pdf files in ~/Documents", "search for TODO in ~/projects"] if on["local"] else ["what time is it"]
    return text + _try(*tries)


def _reply(topic, on):
    if topic == "read_files":
        if not on["local"]:
            return "Not right now: the local tools are switched off (PYBOT_LOCAL=0)."
        return ("Yes, I can read files in your home folder: show a file, list a folder, count lines and find "
                "files by name, type, size or age. I only read, I stay inside home, and I never show secrets "
                "files like .env or anything in ~/.ssh." + _try("show me README.md", "what's in ~/Downloads"))
    if topic == "search_files":
        if not on["local"]:
            return "Not right now: the local tools are switched off (PYBOT_LOCAL=0)."
        return ("Yes, I can search inside the files in your home folder with grep, and find files by name or "
                "type. Secrets files and folders are left out." + _try("search for TODO in ~/projects",
                                                                       "which files mention helper"))
    if topic == "delete":
        text = "No, I don't delete, move or rename anything, and I don't kill processes."
        if _suggests():
            return text + (" Ask me and I'll show you the exact command to run yourself, with a warning about "
                           "what it does." + _try("delete all .log files in ~/tmp"))
        return text + " Everything I run only reads."
    if topic == "edit":
        if on["write"]:
            return ("I don't edit your files. The one thing I write is new files: I can save my last reply or a "
                    "web page to a new file inside your home folder (never over one that exists unless you say "
                    "overwrite), and keep notes." + _try("save that to notes.md", "make a note that the demo is friday"))
        return "No: I don't edit files, and writing is switched off right now (PYBOT_WRITE=0), so I don't save anything either."
    if topic == "commands":
        if not on["local"]:
            return "Not right now: the local tools are switched off (PYBOT_LOCAL=0)."
        return ("Only read-only ones, and only from a fixed list: find, grep, head, tail, ls, du, wc, git status "
                "and log, df, free, ps, ss, pgrep. Your words only fill in a file name or a pattern, there is no "
                "shell, and I don't run code or anything that changes things." + _try("git status", "how much disk space do i have"))
    if topic == "screen":
        return ("No, I can't see your screen, your camera or images. I only read what you type, and the files "
                "you ask about." + (_try("show me README.md") if on["local"] else ""))
    if topic == "reminders":
        if not on["write"]:
            return ("Not right now: writing is switched off (PYBOT_WRITE=0), so I can't save reminders. "
                    "I can still show the ones you have: \"show my reminders\".")
        return ("Yes, I can remind you: I keep reminders in ~/.pybot/notes.json and print them while the chat "
                "is open (there is no background service, so I tell you about missed ones when you come back)."
                + _try("remind me to stretch in 20 minutes", "show my reminders"))
    if topic == "notes":
        if not on["write"]:
            return "Not right now: writing is switched off (PYBOT_WRITE=0). I can still read your notes: \"show my notes\"."
        return "Yes, I keep notes in ~/.pybot/notes.json." + _try("make a note that the demo is friday", "show my notes")
    if topic == "memory":
        text = ("I remember what you tell me during this chat (your name, a fact, what we were talking about), "
                "and I can answer back from it.")
        if on["write"]:
            text += " Notes and reminders last between chats."
        return text + _try("my name is Sam", "make a note that the demo is friday" if on["write"] else "what's my name")
    if topic == "email":
        return ("No, I can't send emails or messages, make calls, post or buy anything. I only answer here, "
                "and the only things I reach are your files and, when it's on, the web.")
    if topic == "site":
        if not on["web"]:
            return "Not right now: the web is switched off (PYBOT_WEB=0), so I don't fetch any site."
        return ("Yes, I can check a site: whether it's up, its TLS certificate and security headers, or what a "
                "page says. Only public addresses." + _try("is python.org up", "what does example.com say"))
    if topic == "web":
        if not on["web"]:
            return "No, I'm offline right now: the web is switched off (PYBOT_WEB=0)."
        site = " I can still check whether a site is up or read a page you name." + _try("is python.org up")
        if not on["search"]:
            return "I can't search the web right now: no EXA_API_KEY is set, so search is off." + site
        return ("Yes, I can search the web (through Exa) and tell you what the top pages say, with the source. "
                "I also check sites and read pages you name." + _try("search for budget laptops", "is python.org up"))
    if topic == "git":
        if not on["local"]:
            return "Not right now: the local tools are switched off (PYBOT_LOCAL=0)."
        return ("Yes, read-only git: status, recent commits, what changed, the current branch, and the history or "
                "diff of one file." + _try("git status", "show me the last 5 commits"))
    if topic == "time":
        return "Yes, worked out in Python: the time here or in a city, and conversions." + _try(
            "what time is it in Tokyo", "convert 5 GB to MB")
    return None


def answer(text):
    """The reply to a question about what PyBot can do, or None when the line is not one."""
    if not text or len(text) > 200:
        return None
    line = " ".join(text.split())
    on = _state()
    if _OVERVIEW.match(line):
        return _overview(on)
    found = _ASK.match(line)
    if not found or local.plan(line) is not None:
        return None  # "can you show me README.md" is an ask to do it: local_tools runs it
    rest = found.group("rest").strip()
    for name, pattern in _TOPIC_RES:
        if pattern.match(rest):
            return _reply(name, on)
    return None
