"""The phrasing test set: how people actually type, and what PyBot's tool layer must do with it.

    python tests/phrasings.py                    # fast checks, every case
    python tests/phrasings.py --slow             # also the slow checks (a full bot turn per case)
    python tests/phrasings.py --group git        # one group
    python tests/phrasings.py --owner A          # one owner's cases
    python tests/phrasings.py --status todo      # only "todo" cases (or pass / all, the default)
    python tests/phrasings.py -v                 # also list the todo cases that fail

The cases are in tests/phrasings.jsonl, one JSON object per line:

    {"id": "files-001", "group": "files", "line": "find all python files in ~/projects",
     "expect": {"plan_kind": "files", "argv0": "find"}, "status": "pass", "owner": "-", "note": ""}

- status "pass": must pass today. Any failure makes this script exit 1, and
  tests/test_phrasings.py runs the fast checks of every "pass" case under unittest.
- status "todo": a feature not built yet (or a gap in an existing rule). It is reported, never
  fatal. A todo case that passes is listed as "now passing": promote it to "pass".
- owner: "-" (the existing rules), or "A", "B", "C", "D" (the agent building that feature).
- Optional fields: "before" (lines said first, in the same memory; see C below), "memory" (a
  dict the case's memory starts as, e.g. {"web_results": [...]}), "needs" (a list of programs
  that must be on PATH, or "man:<cmd>" for a man page; the case is skipped otherwise).
- "{home}" and "{outside}" in a line (and in argv_has / output_has values) become the scratch
  home folder and a folder outside it.

The scratch home
----------------
Every run builds a fake home in a temporary folder (see build_home() for every file in it):
~/projects/pybot is a git repository with README.md, pybot.py, bot/core.py, app.log, .env, ...;
~/projects/webapp has package.json and src/; ~/Documents, ~/Downloads, ~/Desktop, ~/tmp hold a
few files each; ~/.ssh, ~/.aws, ~/.gnupg hold fake keys; ~/escape is a link to a folder outside
home. The environment is set for the whole run:

    HOME = PYBOT_HOME = <scratch>/home        ("~/x" means the scratch home, the fence is there)
    PYBOT_WORKDIR = <scratch>/home/projects/pybot   ("here", "this folder", bare file names)
    EXA_API_KEY = ""   PYBOT_WRITE = "0"   PYBOT_LOCAL = "1"   PYBOT_WEB = "1"

Nothing here reaches the network: exa.search, net.fetch, socket.getaddrinfo and
socket.create_connection are replaced with fakes while the checks run.

Expect keys: the existing tools (fast)
--------------------------------------
plan_kind   str   local.plan(line) is a Plan whose .kind equals it ("files", "listing",
                  "sized", "count", "recent", "file", "lines", "table", "grep", "wc", "ports",
                  "running", "man", "hash", "loglines", "py", "refuse").
no_plan     true  local.plan(line) is None: the line is not a local command.
argv0       str   plan.argv[0] equals it ("find", "ls", "grep", "head", "git", ...).
argv_has    list  every item is an element of plan.argv, or (an item with a "/") the end of
                  one: "projects/pybot/README.md" matches "/tmp/x/home/projects/pybot/README.md".
refuse      true  plan.kind == "refuse" (outside home, or a secrets file or folder).
reason_has  str   plan.extra["reason"] contains it (case-insensitive).
output_has  list  runner.reply_for(plan) contains each item (case-insensitive). This runs the
                  real read-only command in the scratch home: milliseconds.
output_lacks list runner.reply_for(plan) contains none of them (a secret's value, ".ssh").
claims      str|list  each named module (bot/modules/<name>.py) says TAKES_AS_IT_COMES(line,
                  memory) is true, with exa.available() patched to True so the web modules
                  answer as if a key were set.
not_tools   true  no tool module takes the line: every bot/modules/*_tools.py module (today
                  local_tools, quick_tools, note_tools; tomorrow suggest_tools, capability_tools,
                  profile_tools, chain_tools as they appear) plus web_search and web_inspect
                  says TAKES_AS_IT_COMES is false (exa.available() patched to True).
                  Slow part (--slow): the module that answers a real turn is none of them.
no_search   true  neither web_search nor web_inspect takes the line (exa.available() patched
                  to True). Slow part (--slow): the turn is not answered by web_search or
                  web_inspect, and fallback_search.wants_the_web(line, memory, result) is
                  False with exa.available() patched to True: the shrug is not searched.

Expect keys: slow (only with --slow)
------------------------------------
A slow case runs its "before" lines and then the line through bot.runtime.turn(text, memory)
in one fresh memory (seeded from "memory"). exa.available() is True and exa.search returns a
fixed fake result, so explicit search lines route as they would with a key.

module      str   result["module"] equals it ("local_tools", "web_search", "note_tools", ...).
reply_has   str|list  result["reply"] contains each (case-insensitive).
reply_lacks str|list  result["reply"] contains none of them.

Contract for the features being built (A-D)
-------------------------------------------
A missing module makes its keys fail as "not built yet" (never a crash), so these cases sit at
todo until the feature lands. Each owner also gets a module in bot/modules/ that the keys
"claims", "not_tools" and "module" will see by name.

A  Destructive asks are never run; PyBot shows the exact command plus a warning.
   Expose bot/tools/suggest.py: suggest(text) -> None, or a dict
   {"command": str, "warning": str} (an object with .command and .warning also works).
   Module: bot/modules/suggest_tools.py.
   suggests     true   suggest(line) returns a suggestion whose "command" and "warning" are
                       both non-empty strings; and local.plan(line) is None or a Plan of kind
                       "suggest" or "refuse" (a destructive line never becomes a runnable plan).
                false  suggest(line) is None ("how do i kill time at the airport").
   suggest_has  list   the suggestion's command contains each item (case-sensitive: it is a
                       shell command, e.g. ["rm", "build"]). "{home}" is expanded.

B  Questions about PyBot itself are answered from a capability table, never searched.
   Expose bot/tools/capabilities.py: answer(text) -> str, or None when the line is not a
   question about PyBot. Module: bot/modules/capability_tools.py.
   capability     true   capabilities.answer(line) is a non-empty string.
                  false  capabilities.answer(line) is None ("can you believe it rained").
   capability_has list   that answer contains each item (case-insensitive).
   Capability lines also carry no_search (above). B also owns looser file wording ("read this
   file: X"), which is checked with the ordinary plan keys.

C  Persistent memory with scoring.
   Expose bot/tools/profile.py with
     store_path() -> the file the profile is kept in, inside local.home(). The runner deletes
                     it before every C case, so each case starts with an empty profile.
     answer(text, memory) -> str or None: one user line. It stores, forgets or recalls as the
                     line asks and returns the reply (None when the line is not about memory).
                     Writes happen straight away when called directly (as notes.answer does).
     facts() -> list of what is stored: each a str, or a dict with a "text" key.
   Module: bot/modules/profile_tools.py. C cases run with PYBOT_WRITE=1 (only C cases).
   Every "before" line, then the line, is passed to profile.answer(text, memory), in one memory.
   stores      str    after the line, a fact contains it (case-insensitive) that no fact
                      contained before the line.
   not_stored  true   the facts after the line are the same as before it.
   forgets     str    a fact contained it before the line, and none does after it.
   recalls     list   profile.answer(line) contains each item (case-insensitive).
   never_stored str   no fact contains it, after the line (e.g. a password).

D  Chains: two asks in one line, the second working on the first one's result.
   Expose bot/tools/chain.py: steps(text) -> None (not a chain), or a list of steps, one per
   ask, each a local.Plan (or anything with a .kind, or the kind as a str) giving the kind of
   plan that step will run. Module: bot/modules/chain_tools.py.
   chain       list   [step.kind for step in steps(line)] equals it, e.g. ["sized", "loglines"].
               false  steps(line) is None or empty.
"""
import argparse
import copy
import importlib
import json
import os
import pkgutil
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CASES = os.path.join(HERE, "phrasings.jsonl")
GROUPS = ("files", "listing", "sizes", "show", "grep", "git", "machine", "devtools", "quick", "notes",
          "web", "fence", "negative", "suggest", "capability", "memory", "chain")
OWNERS = ("-", "A", "B", "C", "D")
FAST_KEYS = ("plan_kind", "no_plan", "argv0", "argv_has", "refuse", "reason_has", "output_has", "output_lacks",
             "claims", "not_tools", "no_search", "suggests", "suggest_has", "capability", "capability_has",
             "stores", "not_stored", "forgets", "recalls", "never_stored", "chain")
SLOW_KEYS = ("module", "reply_has", "reply_lacks")
FIELDS = ("id", "group", "line", "expect", "status", "owner", "note", "before", "memory", "needs")
WEB_MODULES = ("web_search", "web_inspect")
FAKE_RESULTS = [{"title": "A page", "url": "https://example.org/page", "published": "2026-11-01",
                 "highlights": ["This fake page says something about the thing that was asked, at length."]}]
SECRET_VALUE = "supersecretvalue123"


class NotBuilt(Exception):
    """A feature module that does not exist yet."""


# --- the scratch home ----------------------------------------------------------------------------

def build_home(root):
    """Make the fake home under root. Returns {"home": ..., "outside": ...}."""
    home = os.path.join(root, "home")
    outside = os.path.join(root, "outside")
    big = "x" * 300_000
    files = {
        "projects/pybot/README.md": "# PyBot\n\nA chatbot written in Python rules.\n\n## Install\n\npip install .\n",
        "projects/pybot/pybot.py": "import sys\n\n\ndef main():\n    # TODO: argument parsing\n    print('hi')\n",
        "projects/pybot/bot/__init__.py": "",
        "projects/pybot/bot/core.py": ("import os\n\n# TODO: tidy this\n\ndef respond(text):\n"
                                       "    return helper(text)\n\n\ndef helper(text):\n    return 'TODO later'\n"),
        "projects/pybot/bot/util.py": "def helper():\n    return 42\n",
        "projects/pybot/tests/test_core.py": "import unittest\n\nfrom bot import core\n",
        "projects/pybot/requirements.txt": "requests==2.32.0\n# a comment\npytest\n",
        "projects/pybot/pyproject.toml": "[project]\nname = \"pybot\"\nversion = \"0.1.0\"\ndependencies = []\n",
        "projects/pybot/app.log": ("ok started\nERROR disk full\nWARN slow request\nTraceback (most recent call last)\n"
                                   "ok done\n"),
        "projects/pybot/logs/server.log": "INFO up\nERROR connection refused\nINFO request\n",
        "projects/pybot/.env": "EXA_API_KEY=%s\n" % SECRET_VALUE,
        "projects/pybot/config.ini": "[db]\npassword = hunter2hunter2\nname = demo\n",
        "projects/pybot/notes.md": "# Notes\n\n- ship it\n",
        "projects/pybot/script.sh": "#!/bin/sh\necho hi\n",
        "projects/pybot/data.json": "{\"a\": 1}\n",
        "projects/pybot/build/out.txt": "built\n",
        "projects/pybot/node_modules/dep/index.js": "// TODO in a dependency\n",
        "projects/webapp/package.json": ('{"name": "webapp", "version": "2.1.0", "scripts": {"test": "jest"}, '
                                         '"dependencies": {"left-pad": "^1.3.0"}}\n'),
        "projects/webapp/src/index.js": "// TODO: routes\nconsole.log('hi')\n",
        "projects/webapp/src/app.ts": "export const app = 1\n",
        "projects/webapp/server.log": "GET / 200\nERROR timeout talking to db\n",
        "projects/webapp/big.bundle.js": big,
        "Documents/resume.pdf": "%PDF-1.4 fake resume\n",
        "Documents/taxes-2025.pdf": "%PDF-1.4 fake taxes\n",
        "Documents/report.docx": "fake docx\n",
        "Documents/budget.csv": "month,amount\njan,100\nfeb,120\n",
        "Documents/notes.md": "# Doc notes\n",
        "Downloads/setup.zip": "PK fake zip\n",
        "Downloads/photo.jpg": "fake jpg\n",
        "Downloads/movie.mp4": big * 2,
        "Desktop/todo.txt": "buy milk\ncall mum\n",
        "Pictures/cat.png": "fake png\n",
        "Music/song.mp3": "fake mp3\n",
        "tmp/a.log": "ERROR one\n",
        "tmp/b.log": "fine\n",
        "notes.md": "# Home notes\n\nremember the milk\n",
        "secrets.txt": "my bank pin is 0000\n",
        "server.pem": "-----BEGIN PRIVATE KEY-----\nfake\n",
        ".env": "TOKEN=%s\n" % SECRET_VALUE,
        ".ssh/id_ed25519": "-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n",
        ".ssh/config": "Host box\n  User me\n",
        ".aws/credentials": "[default]\naws_secret_access_key = %s\n" % SECRET_VALUE,
        ".gnupg/pubring.kbx": "fake\n",
    }
    for name, body in files.items():
        path = os.path.join(home, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(body)
    os.makedirs(os.path.join(home, "Videos"), exist_ok=True)
    os.makedirs(outside, exist_ok=True)
    with open(os.path.join(outside, "secret.txt"), "w") as handle:
        handle.write("outside the fence\n")
    os.symlink(outside, os.path.join(home, "escape"))
    os.symlink("/etc", os.path.join(home, "etc-link"))
    repo = os.path.join(home, "projects", "pybot")
    git = ["git", "-C", repo, "-c", "user.name=Test", "-c", "user.email=test@example.com",
           "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false"]
    with open(os.path.join(repo, ".gitignore"), "w") as handle:
        handle.write(".env\nbuild/\nnode_modules/\n")
    if shutil.which("git"):
        quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        subprocess.run(git + ["init", "-q"], check=True, **quiet)
        subprocess.run(git + ["add", "-A"], check=True, **quiet)
        subprocess.run(git + ["commit", "-q", "-m", "First commit"], check=True, **quiet)
        with open(os.path.join(repo, "pybot.py"), "a") as handle:
            handle.write("\nmain()\n")
        subprocess.run(git + ["commit", "-q", "-am", "Call main"], check=True, **quiet)
        with open(os.path.join(repo, "notes.md"), "a") as handle:
            handle.write("- an uncommitted change\n")
    return {"home": os.path.realpath(home), "outside": os.path.realpath(outside)}


class Scratch:
    """The scratch home and the environment that points at it; restores everything on close."""

    VARS = ("HOME", "PYBOT_HOME", "PYBOT_WORKDIR", "EXA_API_KEY", "PYBOT_WRITE", "PYBOT_LOCAL", "PYBOT_WEB")

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="pybot-phrasings-")
        self.paths = build_home(self.root)
        self.home = self.paths["home"]
        self.saved = {name: os.environ.get(name) for name in self.VARS}
        os.environ.update({"HOME": self.home, "PYBOT_HOME": self.home,
                           "PYBOT_WORKDIR": os.path.join(self.home, "projects", "pybot"),
                           "EXA_API_KEY": "", "PYBOT_WRITE": "0", "PYBOT_LOCAL": "1", "PYBOT_WEB": "1"})
        self.patches = [
            mock.patch("socket.getaddrinfo", side_effect=_fake_getaddrinfo),
            mock.patch("socket.create_connection", side_effect=ConnectionRefusedError("fake: refused")),
        ]
        for patch in self.patches:
            patch.start()
        self._offline()

    def _offline(self):
        from bot.tools import ToolError, browser, exa, net  # noqa: PLC0415 - after the environment is set

        def no_fetch(*_args, **_kwargs):
            raise ToolError("the phrasing tests do not fetch pages")

        more = [mock.patch.object(exa, "search", return_value=FAKE_RESULTS),
                mock.patch.object(net, "fetch", side_effect=no_fetch),
                mock.patch.object(browser, "available", return_value=False)]
        for patch in more:
            patch.start()
        self.patches += more

    def fill(self, text):
        return text.replace("{home}", self.home).replace("{outside}", self.paths["outside"])

    def close(self):
        for patch in reversed(self.patches):
            patch.stop()
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        shutil.rmtree(self.root, ignore_errors=True)


def _fake_getaddrinfo(host, port, *args, **kwargs):
    if host in ("localhost", "127.0.0.1"):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port or 0))]
    if host and host.endswith(".invalid"):
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", port or 0))]


# --- the cases ----------------------------------------------------------------------------------

def load_cases(path=CASES):
    """The cases, checked for shape. Raises ValueError naming the bad line."""
    cases, seen = [], set()
    with open(path, encoding="utf-8") as handle:
        for number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            try:
                case = json.loads(raw)
            except ValueError as error:
                raise ValueError("phrasings.jsonl line %d: %s" % (number, error))
            problems = []
            for field in ("id", "group", "line", "expect", "status", "owner"):
                if field not in case:
                    problems.append("missing %s" % field)
            problems += ["unknown field %s" % f for f in case if f not in FIELDS]
            problems += ["unknown expect key %s" % k for k in case.get("expect", {})
                         if k not in FAST_KEYS + SLOW_KEYS]
            if case.get("status") not in ("pass", "todo"):
                problems.append("status must be pass or todo")
            if case.get("owner") not in OWNERS:
                problems.append("owner must be one of %s" % ", ".join(OWNERS))
            if case.get("group") not in GROUPS:
                problems.append("unknown group %s" % case.get("group"))
            if not case.get("expect"):
                problems.append("empty expect")
            if case.get("id") in seen:
                problems.append("duplicate id")
            if problems:
                raise ValueError("phrasings.jsonl line %d (%s): %s" % (number, case.get("id"), "; ".join(problems)))
            seen.add(case["id"])
            cases.append(case)
    return cases


def _as_list(value):
    return value if isinstance(value, list) else [value]


def _feature(name):
    """Import bot.tools.<name> or bot.modules.<name>; NotBuilt when that module does not exist."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as error:
        if error.name and (error.name == name or name.startswith(error.name + ".")):
            raise NotBuilt("not built yet: %s" % name)
        raise


def tool_modules():
    """The names of the tool modules: bot/modules/*_tools.py, web_search and web_inspect."""
    from bot import modules  # noqa: PLC0415
    names = [m.name for m in pkgutil.iter_modules(modules.__path__) if m.name.endswith("_tools")]
    return sorted(set(names) | set(WEB_MODULES))


def _takes(name, line, memory):
    module = _feature("bot.modules." + name)
    hook = getattr(module, "TAKES_AS_IT_COMES", None)
    if not callable(hook):
        return False
    from bot.tools import exa  # noqa: PLC0415
    with mock.patch.object(exa, "available", return_value=True):
        return bool(hook(line, copy.deepcopy(memory)))


class Outcome:
    def __init__(self, case):
        self.case = case
        self.problems = []  # what failed, each with the actual value
        self.skipped = ""

    @property
    def ok(self):
        return not self.problems and not self.skipped


def _needs_missing(case):
    for need in case.get("needs") or []:
        if need.startswith("man:"):
            if not shutil.which("man") or subprocess.run(["man", "-w", need[4:]], stdout=subprocess.DEVNULL,
                                                         stderr=subprocess.DEVNULL).returncode != 0:
                return need
        elif not shutil.which(need):
            return need
    return ""


def evaluate(case, scratch, slow=False):
    """An Outcome for one case: its fast checks, and with slow=True its slow ones."""
    outcome = Outcome(case)
    missing = _needs_missing(case)
    if missing:
        outcome.skipped = "needs %s" % missing
        return outcome
    line = scratch.fill(case["line"])
    expect = case["expect"]
    groups = [("plan", _check_plan), ("tools", _check_claims), ("suggest", _check_suggest),
              ("capability", _check_capability), ("memory", _check_memory), ("chain", _check_chain)]
    if slow:
        groups.append(("turn", _check_turn))
    for label, check in groups:
        try:
            outcome.problems += check(line, expect, case, scratch)
        except NotBuilt as error:
            outcome.problems.append(str(error))
        except Exception as error:  # noqa: BLE001 - a case never crashes the run
            outcome.problems.append("%s check raised %s: %s" % (label, error.__class__.__name__, error))
    return outcome


def _plan_text(plan):
    if plan is None:
        return "no plan"
    reason = plan.extra.get("reason")
    return "%s %s%s" % (plan.kind, " ".join(plan.argv[:2] + (["..."] if len(plan.argv) > 2 else [])),
                        " (%s)" % reason[:80] if reason else "")


def _check_plan(line, expect, case, scratch):
    keys = ("plan_kind", "no_plan", "argv0", "argv_has", "refuse", "reason_has", "output_has", "output_lacks")
    if not any(k in expect for k in keys):
        return []
    from bot.tools import local, runner  # noqa: PLC0415
    plan = local.plan(line)
    seen = _plan_text(plan)
    if plan is None and not expect.get("no_plan"):
        return ["no plan (expected %s)" % ", ".join("%s=%s" % (k, json.dumps(expect[k])) for k in keys if k in expect)]
    problems = []
    if expect.get("no_plan") and plan is not None:
        problems.append("no_plan: got %s" % seen)
    if "plan_kind" in expect and (plan is None or plan.kind != expect["plan_kind"]):
        problems.append("plan_kind %s: got %s" % (expect["plan_kind"], seen))
    if "argv0" in expect and (plan is None or not plan.argv or plan.argv[0] != expect["argv0"]):
        problems.append("argv0 %s: got %s" % (expect["argv0"], seen))
    for item in _as_list(expect.get("argv_has") or []):
        item = scratch.fill(item)
        argv = plan.argv if plan is not None else []
        if not any(arg == item or ("/" in item and arg.endswith("/" + item.lstrip("/"))) for arg in argv):
            problems.append("argv_has %r: got %s" % (item, argv[:12] if argv else seen))
    if expect.get("refuse") and (plan is None or plan.kind != "refuse"):
        problems.append("refuse: got %s" % seen)
    if "reason_has" in expect:
        reason = (plan.extra.get("reason") if plan is not None else "") or ""
        if expect["reason_has"].lower() not in reason.lower():
            problems.append("reason_has %r: got %s" % (expect["reason_has"], seen))
    if "output_has" in expect or "output_lacks" in expect:
        if plan is None:
            problems.append("output_has/output_lacks: no plan to run")
        else:
            said = runner.reply_for(plan)
            for item in _as_list(expect.get("output_has") or []):
                if scratch.fill(item).lower() not in said.lower():
                    problems.append("output_has %r: got %r" % (item, said[:300]))
            for item in _as_list(expect.get("output_lacks") or []):
                if scratch.fill(item).lower() in said.lower():
                    problems.append("output_lacks %r: got %r" % (item, said[:300]))
    return problems


def _check_claims(line, expect, case, scratch):
    memory = case.get("memory") or {}
    problems = []
    for name in _as_list(expect.get("claims") or []):
        if not _takes(name, line, memory):
            takers = [n for n in tool_modules() if _safe_takes(n, line, memory)]
            problems.append("claims %s: taken by %s" % (name, takers or "no tool module"))
    if expect.get("not_tools"):
        takers = [n for n in tool_modules() if _safe_takes(n, line, memory)]
        if takers:
            problems.append("not_tools: taken by %s" % takers)
    if expect.get("no_search"):
        takers = [n for n in WEB_MODULES if _safe_takes(n, line, memory)]
        if takers:
            problems.append("no_search: taken by %s" % takers)
    return problems


def _safe_takes(name, line, memory):
    try:
        return _takes(name, line, memory)
    except Exception:  # noqa: BLE001 - a broken module does not take the line
        return False


def _field(thing, name):
    if isinstance(thing, dict):
        return thing.get(name)
    return getattr(thing, name, None)


def _check_suggest(line, expect, case, scratch):
    if "suggests" not in expect and "suggest_has" not in expect:
        return []
    suggest = _feature("bot.tools.suggest")
    found = suggest.suggest(line)
    problems = []
    if expect.get("suggests") is False:
        if found:
            problems.append("suggests false: got %r" % (found,))
        return problems
    command, warning = _field(found, "command"), _field(found, "warning")
    if not found or not isinstance(command, str) or not command.strip() or not isinstance(warning, str) \
            or not warning.strip():
        problems.append("suggests: got %r" % (found,))
        return problems
    from bot.tools import local  # noqa: PLC0415
    plan = local.plan(line)
    if plan is not None and plan.kind not in ("suggest", "refuse"):
        problems.append("suggests: local.plan would run it: %s" % _plan_text(plan))
    for item in _as_list(expect.get("suggest_has") or []):
        if scratch.fill(item) not in command:
            problems.append("suggest_has %r: command was %r" % (item, command))
    return problems


def _check_capability(line, expect, case, scratch):
    if "capability" not in expect and "capability_has" not in expect:
        return []
    capabilities = _feature("bot.tools.capabilities")
    said = capabilities.answer(line)
    if expect.get("capability") is False:
        return ["capability false: got %r" % said[:200]] if said else []
    if not isinstance(said, str) or not said.strip():
        return ["capability: got %r" % (said,)]
    return ["capability_has %r: got %r" % (item, said[:300]) for item in _as_list(expect.get("capability_has") or [])
            if item.lower() not in said.lower()]


def _facts(profile):
    out = []
    for fact in profile.facts() or []:
        out.append(str(fact.get("text", "")) if isinstance(fact, dict) else str(fact))
    return out


def _check_memory(line, expect, case, scratch):
    keys = ("stores", "not_stored", "forgets", "recalls", "never_stored")
    if not any(k in expect for k in keys):
        return []
    profile = _feature("bot.tools.profile")
    store = profile.store_path()
    from bot.tools import local  # noqa: PLC0415
    if not local.inside_home(os.path.dirname(store) or "."):
        return ["profile.store_path() is outside home: %s" % store]
    if os.path.isdir(store):
        shutil.rmtree(store)
    elif os.path.exists(store):
        os.remove(store)
    memory = copy.deepcopy(case.get("memory") or {})
    with mock.patch.dict(os.environ, {"PYBOT_WRITE": "1"}):
        for said in case.get("before") or []:
            profile.answer(scratch.fill(said), memory)
        before = _facts(profile)
        reply = profile.answer(line, memory) or ""
        after = _facts(profile)
    problems = []
    if "stores" in expect:
        want = expect["stores"].lower()
        if not any(want in f.lower() for f in after) or any(want in f.lower() for f in before):
            problems.append("stores %r: facts before %r, after %r" % (expect["stores"], before, after))
    if expect.get("not_stored") and sorted(after) != sorted(before):
        problems.append("not_stored: facts before %r, after %r" % (before, after))
    if "forgets" in expect:
        want = expect["forgets"].lower()
        if not any(want in f.lower() for f in before) or any(want in f.lower() for f in after):
            problems.append("forgets %r: facts before %r, after %r" % (expect["forgets"], before, after))
    if "never_stored" in expect and any(expect["never_stored"].lower() in f.lower() for f in after):
        problems.append("never_stored %r: facts %r" % (expect["never_stored"], after))
    for item in _as_list(expect.get("recalls") or []):
        if item.lower() not in reply.lower():
            problems.append("recalls %r: replied %r" % (item, reply[:300]))
    return problems


def _check_chain(line, expect, case, scratch):
    if "chain" not in expect:
        return []
    chain = _feature("bot.tools.chain")
    steps = chain.steps(line)
    if expect["chain"] is False:
        return ["chain false: got %r" % (steps,)] if steps else []
    kinds = [s if isinstance(s, str) else getattr(s, "kind", None) for s in (steps or [])]
    return [] if kinds == expect["chain"] else ["chain %s: got %s" % (expect["chain"], kinds or steps)]


_RUNTIME = []


def _runtime():
    if not _RUNTIME:
        from bot import runtime  # noqa: PLC0415 - slow: loads the whole bot
        _RUNTIME.append(runtime)
    return _RUNTIME[0]


def _check_turn(line, expect, case, scratch):
    wanted = [k for k in SLOW_KEYS if k in expect] + [k for k in ("not_tools", "no_search") if expect.get(k)]
    if not wanted:
        return []
    from bot.tools import exa, fallback_search  # noqa: PLC0415
    runtime = _runtime()
    memory = copy.deepcopy(case.get("memory") or {})
    with mock.patch.object(exa, "available", return_value=True):
        for said in case.get("before") or []:
            runtime.turn(scratch.fill(said), memory)
        result = runtime.turn(line, memory)
        searched = fallback_search.wants_the_web(line, memory, result)
    module, reply = result.get("module"), str(result.get("reply") or "")
    seen = "%s: %r" % (module, reply[:200])
    problems = []
    if "module" in expect and module != expect["module"]:
        problems.append("module %s: got %s" % (expect["module"], seen))
    for item in _as_list(expect.get("reply_has") or []):
        if scratch.fill(item).lower() not in reply.lower():
            problems.append("reply_has %r: got %s" % (item, seen))
    for item in _as_list(expect.get("reply_lacks") or []):
        if scratch.fill(item).lower() in reply.lower():
            problems.append("reply_lacks %r: got %s" % (item, seen))
    if expect.get("not_tools") and module in tool_modules():
        problems.append("not_tools (turn): answered by %s" % seen)
    if expect.get("no_search"):
        if module in WEB_MODULES:
            problems.append("no_search (turn): answered by %s" % seen)
        if searched:
            problems.append("no_search (turn): the fallback would search; reply was %s" % seen)
    return problems


# --- the run ------------------------------------------------------------------------------------

def select(cases, group=None, owner=None, status="all"):
    return [c for c in cases if (not group or c["group"] == group) and (not owner or c["owner"] == owner)
            and (status == "all" or c["status"] == status)]


def run(cases, slow=False, scratch=None):
    """[Outcome] for the cases, in a scratch home made for the run (or the one given)."""
    own = scratch is None
    scratch = scratch or Scratch()
    try:
        return [evaluate(case, scratch, slow) for case in cases]
    finally:
        if own:
            scratch.close()


def _rates(outcomes, key):
    table = {}
    for outcome in outcomes:
        row = table.setdefault(outcome.case[key], {"pass": [0, 0], "todo": [0, 0], "skipped": 0})
        if outcome.skipped:
            row["skipped"] += 1
            continue
        cell = row[outcome.case["status"]]
        cell[1] += 1
        cell[0] += outcome.ok
    return table


def report(outcomes, verbose=False, out=sys.stdout):
    """Print the summary; return the number of failing "pass" cases."""
    def cell(pair):
        return "%3d/%-3d" % tuple(pair) if pair[1] else "   -   "

    for key, order in (("group", GROUPS), ("owner", OWNERS)):
        table = _rates(outcomes, key)
        print("%-13s %-9s %-9s %s" % ("by " + key, "pass", "todo", "skipped"), file=out)
        for name in [n for n in order if n in table]:
            row = table[name]
            print("  %-11s %-9s %-9s %s" % (name, cell(row["pass"]), cell(row["todo"]), row["skipped"] or ""), file=out)
        print(file=out)
    broken = [o for o in outcomes if o.case["status"] == "pass" and not o.ok and not o.skipped]
    promoted = [o for o in outcomes if o.case["status"] == "todo" and o.ok]
    todo = [o for o in outcomes if o.case["status"] == "todo" and not o.ok and not o.skipped]
    for title, items in (("FAILING (status pass)", broken), ("now passing (status todo: promote to pass)", promoted)) + (
            (("todo, still failing", todo),) if verbose else ()):
        if not items:
            continue
        print("%s: %d" % (title, len(items)), file=out)
        for o in items:
            print("  %s [%s/%s] %s" % (o.case["id"], o.case["group"], o.case["owner"], o.case["line"]), file=out)
            for problem in o.problems:
                print("      - %s" % problem, file=out)
        print(file=out)
    total = [o for o in outcomes if not o.skipped]
    passing = [o for o in total if o.case["status"] == "pass"]
    todos = [o for o in total if o.case["status"] == "todo"]
    print("pass cases: %d/%d passing   todo cases: %d/%d passing   skipped: %d" % (
        sum(o.ok for o in passing), len(passing), sum(o.ok for o in todos), len(todos), len(outcomes) - len(total)),
        file=out)
    return len(broken)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the phrasing test set (tests/phrasings.jsonl).")
    parser.add_argument("--slow", action="store_true", help="also run the slow checks (a full bot turn per case)")
    parser.add_argument("--group", help="only this group")
    parser.add_argument("--owner", help="only this owner (-, A, B, C, D)")
    parser.add_argument("--status", default="all", choices=("pass", "todo", "all"))
    parser.add_argument("-v", "--verbose", action="store_true", help="list failing todo cases too")
    args = parser.parse_args(argv)
    cases = select(load_cases(), args.group, args.owner, args.status)
    if not cases:
        print("no cases match")
        return 2
    start = time.perf_counter()
    outcomes = run(cases, slow=args.slow)
    broken = report(outcomes, verbose=args.verbose)
    print("%d cases in %.1f s%s" % (len(cases), time.perf_counter() - start, " (with the slow checks)" if args.slow else ""))
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
