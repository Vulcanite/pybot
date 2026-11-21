"""Two or three local asks in one line, the later ones working on what the earlier one found.

    "show me README.md and then count its lines"
    "search for TODO in ~/projects/pybot, then open the first one"
    "find files changed today in ~/projects and search them for TODO"

Not a general agent loop: a line is cut at "then", "and then", ";" or "and" into at most three
asks, and every ask must be one the planner in bot/tools/local.py already reads, so the home
fence, the secrets refusal and argv-without-a-shell apply to every step exactly as they do to a
line on its own. A later ask that points back ("its lines", "the first one", "them") is matched
against a short list of follow-up templates below, and its text is rewritten with the concrete
path from the step before ("count its lines" -> "how many lines in ~/projects/pybot/README.md"),
then planned like any other line. Plans are never built or changed here, only asked for.

A chain stops early, and says why, when a step is refused, finds nothing, or finds several where
"it" needs one. A step that would change something (delete, move, kill, ...) is never run: the
chain stops there.

The paths the last local answer found are kept in memory["last_paths"] (by the chain module's
respond and after hooks), so a follow-up on its own line ("show the errors in it", "open the
second one") works on them too, for a couple of turns.
"""
import os
import re

from . import local, runner

MAX_STEPS = 3
MAX_EACH = 10  # "search them for TODO" runs one search per file, for at most this many files
FRESH_TURNS = 2  # a follow-up line may point at the last result for this many turns

# Where one ask ends and the next begins. "then" (and ";") is a strong cut; a bare "and" is weak,
# because it is just as often inside one ask ("find python and json files"), and so is a comma.
_STRONG = re.compile(r"(?:\s*[,;]\s*|\s+)(?:and\s+)?(?:then|after\s+that|afterwards)\b,?\s*|\s*;\s*", re.I)
_WEAK = re.compile(r"(?:\s*,\s*|\s+)and\s+(?:also\s+)?|\s*,\s*", re.I)

_LEADS = re.compile(r"^(?:(?:please|pls|now|also|then|and|just|so|ok|okay)[,\s]+|"
                    r"(?:can|could|would|will)\s+you\s+(?:please\s+)?)*", re.I)

# What a later ask points back with. Each template below uses REF or POSS at most once.
REF = (r"(?P<ref>it|them|those(?:\s+files)?|these(?:\s+files)?|that(?:\s+(?:one|file|folder|log))?|"
       r"this(?:\s+(?:one|file|folder))?|the\s+(?P<nth>first|second|third|top|last|1st|2nd|3rd)"
       r"(?:\s+(?:one|result|file|match|hit))?|the\s+(?:results|files|result|file|folder))")
POSS = r"(?P<poss>its|their|the)"
_WHAT = r"(?P<what>errors?|warnings?|problems|exceptions|failures)"
_SHOWS = r"(?:show|find|list|grep|get|check|give|are\s+there|is\s+there)"
_NTH = {"first": 0, "top": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "last": -1}
_MANY = re.compile(r"^(?:them|those|these|their|the\s+(?:results|files))\b", re.I)

# (kind the step will plan as, the text it is rewritten to, the ways of saying it)
FOLLOW_UPS = [
    ("loglines", "show the {what} in {path}", [
        _SHOWS + r"?\s*(?:me\s+)?(?:the\s+|any\s+)*" + _WHAT + r"\s+(?:in|from|inside|of)\s+" + REF,
        r"(?:show|find|list|get|check|give)\s+(?:me\s+)?" + POSS + r"\s+(?:last\s+)?" + _WHAT,
        r"does\s+" + REF + r"\s+have\s+(?:any\s+)?" + _WHAT]),
    ("wc", "how many lines in {path}", [
        r"count\s+" + POSS + r"\s+lines",
        r"count\s+(?:the\s+)?lines\s+(?:in|of)\s+" + REF,
        r"how\s+many\s+lines\s+(?:are\s+)?(?:in|does)\s+" + REF + r"(?:\s+have)?",
        r"(?:show\s+|get\s+|give\s+)?(?:me\s+)?" + POSS + r"\s+line\s+count"]),
    ("lines", "how big is {path}", [
        r"(?:tell\s+me\s+|say\s+|show\s+me\s+)?how\s+(?:big|large)\s+is\s+" + REF,
        r"(?:tell\s+me\s+|say\s+|show\s+me\s+)?how\s+(?:big|large)\s+" + REF + r"\s+(?:is|are)",
        r"(?:what(?:'s|\s+is)\s+|show\s+(?:me\s+)?|get\s+|tell\s+me\s+)?" + POSS + r"\s+size",
        r"(?:what(?:'s|\s+is)\s+)?the\s+size\s+of\s+" + REF]),
    ("grep", "search for {q} in {path}", [
        r"(?:search|grep|look\s+through|check)\s+" + REF + r"\s+for\s+(?P<q>.+)",
        r"(?:search|grep|look|find|check)(?:\s+for)?\s+(?P<q>.+?)\s+(?:in|inside|within)\s+" + REF]),
    ("file", "show the {which} {n} lines of {path}", [
        r"(?:show(?:\s+me)?\s+|print\s+|read\s+|give\s+me\s+)?(?:the\s+)?(?P<which>first|last|top|bottom)\s+"
        r"(?P<n>\d{1,4})\s+lines\s+(?:of|in|from)\s+" + REF,
        r"(?:show(?:\s+me)?\s+|print\s+|read\s+|give\s+me\s+)?" + POSS + r"\s+(?P<which>first|last|top|bottom)\s+"
        r"(?P<n>\d{1,4})\s+lines"]),
    ("lines", "show me the diff for {path}", [
        r"(?:show\s+(?:me\s+)?)?" + POSS + r"\s+(?:git\s+)?diff",
        r"(?:show\s+(?:me\s+)?)?(?:the\s+)?(?:git\s+)?diff\s+(?:for|of|in)\s+" + REF,
        r"what(?:'s|\s+has)?\s+changed\s+in\s+" + REF]),
    ("lines", "show the history of {path}", [
        r"(?:show\s+(?:me\s+)?)?" + POSS + r"\s+(?:git\s+)?(?:history|log)",
        r"who\s+(?:last\s+)?(?:changed|edited|wrote)\s+" + REF]),
    ("file", "show {path}", [
        r"(?:open|show|read|cat|print|display|view|see)\s+(?:me\s+)?" + REF + r"(?:\s+(?:to\s+me|please))?",
        r"what(?:'s|\s+is)\s+in(?:side)?\s+" + REF,
        r"what\s+does\s+" + REF + r"\s+say",
        r"(?:list|ls)\s+" + REF]),
]
FOLLOW_UPS = [(kind, template, [re.compile(r"^" + p + r"$", re.I) for p in patterns])
              for kind, template, patterns in FOLLOW_UPS]

# An ask that would change something: never run in a chain (bot/tools/suggest.py shows those).
DESTRUCTIVE = re.compile(r"^(?:delete|remove|rm|erase|wipe|kill|move|mv|rename|chmod|chown|overwrite|truncate|"
                         r"empty|clear\s+out|uninstall|install|shred|format|git\s+(?:reset|push|clean|checkout|rebase|"
                         r"commit))\b", re.I)


class Step:
    """One ask of a chain: a plan of its own, a follow-up on the step before, or a change."""

    def __init__(self, text, plan=None, follow=None, destructive=False):
        self.text = text
        self.plan = plan  # a local.Plan for an ask that stands on its own
        self.follow = follow  # (kind, template, match) for one that points back
        self.destructive = destructive

    @property
    def kind(self):
        if self.destructive:
            return "suggest"
        return self.plan.kind if self.plan is not None else self.follow[0]


def _clean(part):
    part = " ".join(part.split()).strip(" ,")
    part = _LEADS.sub("", part)
    return re.sub(r"\s*[?.!]+\s*$", "", part)


def follow_up(part):
    """(kind, template, match) when an ask points back at the last result, else None."""
    part = _clean(part)
    for kind, template, patterns in FOLLOW_UPS:
        for pattern in patterns:
            found = pattern.match(part)
            if found and _refers(found):
                return kind, template, found
    return None


def _refers(found):
    groups = found.groupdict()
    return bool(groups.get("ref") or groups.get("poss"))


def _step(part, first, memory):
    text = _clean(part)
    if not text:
        return None
    follow = follow_up(text)
    if follow is not None:
        if first and not fresh_paths(memory):
            return None  # "it" with nothing before it to point at
        return Step(text, follow=follow)
    if DESTRUCTIVE.match(text):
        return None if first else Step(text, destructive=True)
    plan = local.plan(text)
    return Step(text, plan=plan) if plan is not None else None


def _cuts(text):
    """Every way of cutting the line into 2..MAX_STEPS parts, the likeliest first."""
    spots = [(m.start(), m.end(), False) for m in _STRONG.finditer(text)]
    taken = [(a, b) for a, b, _ in spots]
    for m in _WEAK.finditer(text):
        if not any(a <= m.start() < b or m.start() <= a < m.end() for a, b in taken):
            spots.append((m.start(), m.end(), True))
    spots.sort()
    ways = []
    for i in range(len(spots)):
        ways.append([spots[i]])
        ways += [[spots[i], spots[j]] for j in range(i + 1, len(spots))]  # three steps at most
    # fewer weak "and" cuts first (a whole ask is kept whole), then more steps
    ways.sort(key=lambda way: (sum(1 for s in way if s[2]), -len(way)))
    for way in ways:
        parts, at = [], 0
        for start, end, _ in way:
            parts.append(text[at:start])
            at = end
        parts.append(text[at:])
        yield parts, any(not weak for _, _, weak in way)


def parse(text, memory=None):
    """The chain's steps for a line, or None when it is not a chain of local asks."""
    if not local.enabled() or not text or len(text) > 400:
        return None
    text = " ".join(text.split())
    if not (_STRONG.search(text) or _WEAK.search(text)):
        return None
    # A line the planner reads whole is one ask, "and" and all ("search for salt and pepper in
    # ~/Documents"), unless "then" cuts it: "check disk space and then show the biggest files in ~"
    # is read whole as disk space, because that ask is found anywhere in a line.
    whole = local.plan(text) is not None
    for parts, strong in _cuts(text):
        if whole and not strong:
            continue
        chain = []
        for i, part in enumerate(parts):
            step = _step(part, i == 0, memory)
            if step is None:
                break
            chain.append(step)
        else:
            if any(not s.destructive for s in chain):
                return chain
    return None


def steps(text, memory=None):
    """The contract for tests/phrasings.py: None, or one entry per ask. An ask that stands on its
    own is its local.Plan; one that works on the step before is the kind it will plan as (it can
    only be planned once that step has run); one that would change something is "suggest"."""
    chain = parse(text, memory)
    if not chain:
        return None
    return [s.plan if s.plan is not None else s.kind for s in chain]


# --- what a step found ------------------------------------------------------------------------

def _untidy(path):
    path = path.strip()
    if path == "~":
        return runner._HOME
    if path.startswith("~/"):
        return runner._HOME + path[1:]
    return path


_SIZED = re.compile(r"^\s+\d+(?:\.\d+)? [KMGT]?B  (?P<p>.+)$")
_RECENT = re.compile(r"^\s+\d\d \w{3} \d\d:\d\d  (?P<p>.+)$")
_GREP = re.compile(r"^  (?P<p>.+?):\d+  ")


def found_paths(plan, reply):
    """The files or folders a plan's reply names, in the order the reply shows them."""
    kind = plan.kind
    if kind == "refuse":
        return []
    if kind == "file":
        return [plan.extra["path"]]
    if kind == "wc" or (kind == "lines" and plan.argv[:2] == ["du", "-sh"]):
        return [plan.argv[-1]]
    if kind == "loglines":
        return [plan.extra["root"]]
    body = reply.split("\n")[1:]
    paths = []
    for line in body:
        if line.startswith("...and "):
            break
        if kind == "files" and line.startswith("  "):
            paths.append(_untidy(line))
        elif kind == "sized" and _SIZED.match(line):
            paths.append(_untidy(_SIZED.match(line).group("p")))
        elif kind == "recent" and _RECENT.match(line):
            paths.append(_untidy(_RECENT.match(line).group("p")))
        elif kind == "grep" and _GREP.match(line):
            path = _untidy(_GREP.match(line).group("p"))
            if path not in paths:
                paths.append(path)
        elif kind == "listing" and line.startswith("  "):
            parts = line.split(None, 8)
            if len(parts) == 9:
                name = parts[8].split(" -> ")[0]
                paths.append(os.path.join(plan.argv[-1], name))
    return [p for p in paths if os.path.exists(p) and local.inside_home(p) and not local.is_secret(p)]


def fresh_paths(memory):
    """The paths of the last local result, while it is recent enough to be "it"."""
    memory = memory or {}
    paths = memory.get("last_paths") or []
    at = memory.get("last_paths_turn")
    if not paths or not isinstance(at, int):
        return []
    turns = memory.get("turns")
    now = len(turns) if isinstance(turns, list) else 0
    return list(paths) if now - at <= FRESH_TURNS else []


def keep(memory, paths):
    """Remember what a local answer found, for "it" on the next line."""
    if memory is None or not paths:
        return
    turns = memory.get("turns")
    memory["last_paths"] = list(paths)[:50]
    memory["last_paths_turn"] = len(turns) if isinstance(turns, list) else 0
    memory["last_paths_web"] = list(memory.get("web_results") or [])


def _token(path):
    """A path as one word the planner reads back: quoted when it has a space in it."""
    if not re.search(r"\s", path):
        return path
    if '"' not in path:
        return '"%s"' % path
    if "'" not in path:
        return "'%s'" % path
    return None


def _pick(follow, earlier, before_text, before):
    """(paths to work on, None) or (None, why not). before is "the step before" or "the last result"."""
    found = follow[2]
    groups = found.groupdict()
    nth = (groups.get("nth") or "").lower()
    if not earlier:
        return None, "%s found nothing to work on, so I stopped there." % before
    if nth:
        index = _NTH[nth]
        if index >= len(earlier):
            return None, "%s found only %d, so there is no %s one." % (before, len(earlier), nth)
        return [earlier[index]], None
    if _MANY.match(groups.get("ref") or "") or (groups.get("poss") or "").lower() == "their":
        return earlier[:MAX_EACH], None
    if len(earlier) == 1:
        return earlier, None
    # "the biggest log file", "the newest file": the one at the top of the list.
    if re.search(r"\b(?:biggest|largest|newest|latest|most\s+recent|smallest|oldest)\b", before_text, re.I) \
            and not re.search(r"\b(?:files|folders)\b", before_text, re.I):
        return earlier[:1], None
    return None, ("%s found %d, and \"%s\" could be any of them. Say which one (\"the first one\", "
                  "\"the second one\") and I'll go on." % (before, len(earlier), found.group(0)))


def rewrite(follow, path):
    """The follow-up's text with the concrete path in it, ready for local.plan."""
    kind, template, found = follow
    token = _token(path)
    if token is None:
        return None
    if template == "show {path}" and os.path.isdir(path):
        template = "list {path}"
    values = {k: v for k, v in found.groupdict().items() if v}
    values["path"] = token
    if "what" in values:
        values["what"] = values["what"].lower()
    try:
        return template.format(**values)
    except KeyError:
        return None


# --- running a chain --------------------------------------------------------------------------

def said(text):
    """A step's text as said back: paths under home as ~/..."""
    return re.sub(re.escape(runner._HOME) + r"(?=/|\b)", "~", text)


def _suggestion(text):
    """Agent A's suggested command for a change, when bot/tools/suggest.py is there."""
    try:
        from . import suggest  # noqa: PLC0415 - optional
        found = suggest.suggest(text)
    except Exception:  # noqa: BLE001 - no suggestion is fine
        return ""
    if not found:
        return ""
    get = found.get if isinstance(found, dict) else (lambda name: getattr(found, name, None))
    if not get("command"):
        return ""
    return "\nThe command would be `%s`%s" % (get("command"), ": %s" % get("warning") if get("warning") else ".")


def _follow(step, earlier, earlier_text, before):
    """(header text, reply, paths it found, stop) for a step that works on the one before."""
    paths, why = _pick(step.follow, earlier, earlier_text, before)
    if paths is None:
        return step.text, why[0].upper() + why[1:], [], True
    replies, found, stop, nothing = [], [], False, []
    for path in paths:
        text = rewrite(step.follow, path)
        plan = local.plan(text) if text else None
        if plan is None:
            replies.append("I couldn't do \"%s\" on %s." % (step.text, runner.tidy(path)))
            stop = stop or len(paths) == 1
            continue
        reply = runner.reply_for(plan)
        if len(paths) > 1 and reply.split("\n", 1)[-1].startswith("No matches for "):
            nothing.append(runner.tidy(path))  # one line for all of these, below
            continue
        replies.append(reply if len(paths) == 1 else "%s:\n%s" % (said(text), reply))
        if plan.kind == "refuse":
            stop = True
            break
        found += [p for p in found_paths(plan, reply) if p not in found]
    if nothing:
        replies.append("No matches in %s%s." % ("the other " if replies else "",
                                               "%d: %s" % (len(nothing), ", ".join(nothing))))
    if len(paths) == 1:
        head = said(rewrite(step.follow, paths[0]) or step.text)
    else:
        head = "%s: each of %d files%s" % (step.text, len(paths), ", the first %d of %d" % (len(paths), len(earlier))
                                            if len(paths) < len(earlier) else "")
    return head, "\n\n".join(replies), found, stop


def run(chain, memory=None):
    """The reply to a chain: each step's text, then what it found. Stops at the first problem.

    A chain of one step is a follow-up line on its own ("show the errors in it"): no "Step" label.
    """
    out = []
    earlier, earlier_text, last_found = fresh_paths(memory), "", []
    total = len(chain)
    for number, step in enumerate(chain, 1):
        label = "Step %d of %d" % (number, total) if total > 1 else ""
        before = "the step before" if number > 1 else "the last result"
        if step.destructive:
            text = step.text
            if earlier and len(earlier) == 1 and _token(earlier[0]):
                text = re.sub(r"\b(?:it|them|that)\b", lambda _m: _token(earlier[0]), text, count=1)
            out.append("%s (%s): not run. It would change things, and a chain only runs steps that read.%s"
                       % (label, said(text), _suggestion(text)))
            break
        if step.plan is not None:
            reply = runner.reply_for(step.plan)
            out.append("%s (%s):\n%s" % (label, step.text, reply))
            if step.plan.kind == "refuse":
                if number < total:
                    out.append("I stopped there.")
                break
            found = found_paths(step.plan, reply)
            if found:
                earlier, earlier_text, last_found = found, step.text, found
            continue
        head, reply, found, stop = _follow(step, earlier, earlier_text, before)
        if label:
            out.append("%s (%s):\n%s" % (label, head, reply))
        else:
            out.append(reply)
        if found:
            earlier, earlier_text, last_found = found, step.text, found
        if stop:
            break
    keep(memory, last_found)
    return "\n\n".join(out)


# --- the module's hooks -------------------------------------------------------------------------

def wants(text, memory=None):
    """True for a chain of local asks, or a follow-up line on the last local result."""
    if parse(text, memory):
        return True
    return _follow_line(text, memory) is not None


def _follow_line(text, memory):
    """A line of its own that points back at the last local result: the follow-up, or None."""
    if not local.enabled() or not text or len(text) > 200 or local.plan(text) is not None:
        return None
    paths = fresh_paths(memory)
    if not paths:
        return None
    follow = follow_up(text)
    if follow is None or (follow[2].groupdict().get("poss") or "").lower() == "the":
        return None  # "show me the errors" on its own is not clearly about that file
    if follow[2].groupdict().get("nth") and (memory or {}).get("web_results") and \
            list(memory.get("web_results") or []) != list(memory.get("last_paths_web") or []):
        return None  # a web search came after: "open the first one" is a result of that
    return follow


def answer(text, memory=None):
    """The reply to a chain or a follow-up line, or None."""
    chain = parse(text, memory)
    if not chain:
        follow = _follow_line(text, memory)
        if follow is None:
            return None
        chain = [Step(_clean(text), follow=follow)]
    return run(chain, memory)


def remember(text, reply, memory):
    """After a turn: a local answer's paths become "it" for the next line; a web search that came
    after them means "the first one" is a web result again."""
    if not isinstance(memory, dict):
        return
    web = list(memory.get("web_results") or [])
    if memory.get("last_paths") and web != list(memory.get("last_paths_web") or []):
        memory.pop("last_paths", None)
        memory.pop("last_paths_turn", None)
    if not isinstance(reply, str) or not reply.startswith("Ran: `"):
        return
    plan = local.plan(text)
    if plan is not None and plan.kind not in ("refuse", "py"):
        keep(memory, found_paths(plan, reply))
