"""Plain English to a local command, by rule: "find the pdf files in ~/Downloads" -> find ...

Not part of the swarm's original bot. Every ask maps to one fixed command template, and the
person's words only ever fill in its arguments (a file name, a search pattern, a folder), so a
line can never run something that is not on this list. Every command reads only: nothing here
deletes, moves, writes, installs or runs code. Commands run as the user, without a shell
(argv lists, never a string), with a timeout and a cap on output.

`plan(text)` returns a Plan for a line it recognises, or None. A plan that names a file or a
folder is only made when that file or folder exists, which is what keeps ordinary chat ("what's
in a name", "show me paris") from reading as a command.

Templates:
- find by name, by kind ("python files"), by size ("largest files", "files over 100mb"), by age
  ("files changed today"), and a count ("how many files in ...")
- search inside files: grep -rnI, with .git, node_modules and the like left out
- show a file (head / tail), list a folder (ls), size of a path (du), lines in a file (wc)
- git: status, recent commits, what changed, current branch
- the machine: disk space (df), memory (free), top processes (ps), listening ports (ss),
  whether a program is running (pgrep), uptime

Everything stays inside the home folder. A path is resolved with its symlinks followed, and one
that lands outside home (/etc, /mnt/c, a link that points out) is refused, not searched; every
command runs with home or a folder inside it as its working directory; find and grep do not
follow links they meet on the way. The secrets folders inside home (~/.ssh, ~/.gnupg, ~/.aws,
...) are never listed, searched or shown.

PYBOT_LOCAL=0 (or `python -m pybot --no-local`) turns all of it off. PYBOT_WORKDIR sets the
folder that "here" and relative paths mean; it is the folder pybot was started in otherwise, and
home when that folder is outside home. PYBOT_HOME moves the fence (the tests use a scratch
folder).
"""
import os
import re

# grep stops after this many matches in one file, so one huge file cannot fill the reply.
GREP_PER_FILE = 5

# Folders not worth searching: tools' caches and other people's code.
PRUNE = (".git", "node_modules", "__pycache__", ".venv", "venv", ".cache", ".npm", ".nvm",
         ".cargo", ".rustup", ".mypy_cache", ".pytest_cache", ".tox", "dist", "build", "snap",
         ".local", "site-packages", ".vscode-server", "graphify-out")

# Folders inside home that hold keys and tokens: never listed, searched or shown.
SECRET_DIRS = (".ssh", ".gnupg", ".aws", ".azure", ".kube", ".password-store", ".docker",
               "ssh_keys", ".claude-mem", ".config/gh", ".config/gcloud", ".pybot-secrets")

# Files whose contents are secrets: never printed, never searched.
SECRET_NAMES = re.compile(
    r"^(?:\.env(?:\..+)?|id_(?:rsa|dsa|ecdsa|ed25519)(?:_sk)?|.*\.(?:pem|key|p12|pfx|keystore|jks)|"
    r"\.netrc|\.pgpass|\.git-credentials|credentials(?:\.json)?|\.npmrc|\.pypirc|"
    r"secrets?(?:\..+)?|.*_secret(?:\..+)?)$", re.I)
SECRET_GLOBS = (".env", ".env.*", "id_rsa*", "id_ed25519*", "id_ecdsa*", "*.pem", "*.key", "*.p12",
                "*.pfx", ".netrc", ".pgpass", ".git-credentials", "credentials*", ".npmrc",
                ".pypirc", "secret*", "*_secret*")

KINDS = {
    "python": ["*.py"], "py": ["*.py"], "javascript": ["*.js", "*.mjs", "*.cjs"], "js": ["*.js"],
    "typescript": ["*.ts", "*.tsx"], "ts": ["*.ts", "*.tsx"], "markdown": ["*.md"], "md": ["*.md"],
    "pdf": ["*.pdf"], "text": ["*.txt"], "txt": ["*.txt"], "json": ["*.json"],
    "yaml": ["*.yml", "*.yaml"], "yml": ["*.yml", "*.yaml"], "csv": ["*.csv"], "log": ["*.log"],
    "shell": ["*.sh"], "bash": ["*.sh"], "html": ["*.html", "*.htm"], "css": ["*.css"],
    "go": ["*.go"], "rust": ["*.rs"], "java": ["*.java"], "c": ["*.c", "*.h"],
    "cpp": ["*.cpp", "*.hpp", "*.cc"], "excel": ["*.xlsx", "*.xls"], "word": ["*.docx", "*.doc"],
    "image": ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.svg"],
    "photo": ["*.png", "*.jpg", "*.jpeg", "*.heic"], "video": ["*.mp4", "*.mov", "*.mkv", "*.avi"],
    "zip": ["*.zip", "*.tar", "*.gz", "*.tgz"], "config": ["*.toml", "*.ini", "*.cfg", "*.conf"],
    "docker": ["Dockerfile", "*.dockerfile", "docker-compose*.yml"],
}
_KIND_WORDS = "|".join(sorted(KINDS, key=len, reverse=True))

_LEAD = (r"^\s*(?:(?:hey|hi|ok|okay|so|pybot|bot)[,!\s]+)*"
         r"(?:(?:can|could|would|will) you\s+(?:please\s+)?|please\s+|pls\s+|now\s+|just\s+)?"
         r"(?:(?:give|get|tell|show)\s+me\s+(?=(?:the\s+)?(?:list|size|number|count|contents|files|"
         r"first|last|top|bottom|largest|biggest|how|all|what)\b))?")
_THE = r"(?:(?:the|my|our|that)\s+)?"
_FOLDER_WORD = r"(?:\s+(?:folder|directory|dir|repo|repository|project|codebase))?"
_END = r"\s*[?.!]*\s*$"
# "this folder" and "the current folder" are one path, not "this" plus a folder called "folder".
_PATH = (r"(?P<path>(?:this|current|the\s+current)\s+(?:folder|directory|dir|repo|project)|\"[^\"]+\"|'[^']+'|"
         r"(?!this\b)\S+)")
_IN = r"\s+(?:in|inside|within|under|across|through|from|of|on)\s+" + _THE + _PATH + _FOLDER_WORD

# "... please", "... pls", "... thanks": the ask is the same without them.
_POLITE = re.compile(r"(?:[\s,]+(?:please|pls|plz|thanks|thank\s+you|thx))+\s*(?P<p>[?.!]*)\s*$", re.I)
# "whats in documents", "wheres my taxes pdf": the apostrophe people skip.
_NO_APOSTROPHE = re.compile(r"\b(what|where)s\b", re.I)


def tidy_line(text):
    """The line as the patterns read it: spaces folded, a trailing please dropped, "whats" -> "what's"."""
    text = " ".join((text or "").split())
    text = _POLITE.sub(lambda m: m.group("p"), text)
    return _NO_APOSTROPHE.sub(lambda m: m.group(1) + "'s", text)


_HERE = re.compile(r"^(?:here|(?:this|current|the\s+current)\s+(?:folder|directory|dir|repo|project)|\.)$",
                   re.I)
_HOME_NAMES = {"home": "", "home folder": "", "downloads": "Downloads", "desktop": "Desktop",
               "documents": "Documents", "docs": "Documents", "pictures": "Pictures",
               "music": "Music", "videos": "Videos"}


class Plan:
    """One command to run, and how to read what it prints."""

    def __init__(self, kind, argv, cwd=None, title="", limit=20, **extra):
        self.kind = kind  # what the reader in runner.py does with the output
        self.argv = argv
        self.cwd = cwd
        self.title = title  # what was asked, for the reply's first line
        self.limit = limit
        self.extra = extra

    def __repr__(self):
        return "Plan(%r, %r)" % (self.kind, self.argv)


class Outside(Exception):
    """A path that resolves outside the home folder."""


def enabled():
    return os.environ.get("PYBOT_LOCAL", "1") != "0"


def home():
    """The fence: every path the local tools touch is inside this folder."""
    return os.path.realpath(os.environ.get("PYBOT_HOME") or os.path.expanduser("~"))


def inside_home(path):
    real, fence = os.path.realpath(path), home()
    return real == fence or real.startswith(fence + os.sep)


def workdir():
    here = os.path.realpath(os.environ.get("PYBOT_WORKDIR") or os.getcwd())
    return here if inside_home(here) else home()


def resolve(token, want="any"):
    """The absolute path a word names, when it exists and is of the kind wanted; else None.

    "~/x", "/x", "./x", "x" (in the work folder, then in home), "here", and the usual home
    folders by name ("downloads", "desktop").
    """
    if not token:
        return None
    token = token.strip().strip("\"'").rstrip(",;:!?")
    if token.endswith(".") and not token.endswith(".."):
        token = token.rstrip(".") or "."
    if not token:
        return None
    if _HERE.match(token):
        candidates = [workdir()]
    elif token.lower() in _HOME_NAMES:
        candidates = [os.path.join(home(), _HOME_NAMES[token.lower()])]
    elif token.startswith(("~", "/")):
        candidates = [os.path.expanduser(token)]
    else:
        candidates = [os.path.join(workdir(), token), os.path.join(home(), token)]
    for path in candidates:
        path = os.path.realpath(path)
        fits = (want == "dir" and os.path.isdir(path)) or (want == "file" and os.path.isfile(path)) or (
            want == "any" and os.path.exists(path))
        if not fits:
            continue
        if not inside_home(path):
            raise Outside(path)
        return path
    return None


def is_secret(path):
    """True for a secrets file, or anything inside a secrets folder."""
    if SECRET_NAMES.match(os.path.basename(path)):
        return True
    rel = os.path.relpath(os.path.realpath(path), home()) if inside_home(path) else path
    parts = rel.replace(os.sep, "/")
    return any(parts == d or parts.startswith(d + "/") or ("/" + d + "/") in ("/" + parts + "/")
               for d in SECRET_DIRS)


def _prune_args(caches=True):
    args = ["("]
    for i, name in enumerate((PRUNE if caches else ()) + tuple(d for d in SECRET_DIRS if "/" not in d)):
        if i:
            args.append("-o")
        args += ["-name", name]
    return args + [")", "-prune", "-o"]


def _find(root, tests, title, kind="files", limit=20, **extra):
    argv = ["find", root] + _prune_args() + tests
    return Plan(kind, argv, title=title, limit=limit, root=root, **extra)


def _name_tests(patterns):
    tests = ["("]
    for i, pattern in enumerate(patterns):
        if i:
            tests.append("-o")
        tests += ["-iname", pattern]
    return tests + [")"]


def _unquote(text):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'`":
        return text[1:-1]
    return text


# --- the asks, most specific first ------------------------------------------------------------

GIT_STATUS = re.compile(_LEAD + r"(?:show\s+(?:me\s+)?|what(?:'s|\s+is)\s+)?(?:the\s+)?(?:git\s+status(?:" + _IN + r")?|"
                        r"status\s+of\s+(?:my|the|this|our)\s+(?:git\s+)?(?:repo|repository|project|working\s+tree))"
                        + _END, re.I)
GIT_LOG = re.compile(_LEAD + r"(?:show\s+(?:me\s+)?|what\s+are\s+)?(?:the\s+)?(?:(?:recent|last|latest)\s+"
                     r"(?:(?P<n>\d{1,3})\s+)?commits|git\s+log)(?:" + _IN + r")?" + _END, re.I)
# "what's changed" alone is as often about a life as a repo, so the line has to say which.
GIT_CHANGED = re.compile(_LEAD + r"what(?:'s|\s+has|\s+have|\s+is)?\s+changed\s+(?:in\s+(?:the\s+)?"
                         r"(?:code|repo|repository|working\s+tree)|since\s+the\s+last\s+commit|"
                         r"(?:in|inside|within|under|of|on)\s+" + _THE + _PATH + _FOLDER_WORD + r")" + _END, re.I)
GIT_BRANCH = re.compile(_LEAD + r"(?:what(?:'s|\s+is)\s+)?(?:the\s+)?(?:current|which)\s+branch"
                        r"(?:\s+am\s+i\s+on)?(?:" + _IN + r")?" + _END, re.I)

DISK = re.compile(r"\b(?:(?:disk|free|storage|drive)\s+space|how\s+full\s+is\s+(?:my\s+|the\s+)?"
                  r"(?:disk|drive|ssd)|disk\s+usage)\b(?!\s+of\b)", re.I)
MEMORY = re.compile(r"\b(?:(?:memory|ram)\s+(?:usage|left|free|used|available)|how\s+much\s+"
                    r"(?:memory|ram)\b)", re.I)
# "how much memory does a goldfish have" is not about this machine: the line has to say it is
# (my, this computer, ram, free, left), or say nothing else at all ("how much memory?").
_MACHINE_MEMORY = re.compile(r"\b(?:my|i|this|the\s+(?:computer|machine|system|pc|laptop|server))\b|\bram\b|"
                             r"\b(?:usage|left|free|used|available|in\s+use)\b|^\W*how\s+much\s+memory\W*$", re.I)
_SOMEONE_ELSES_MEMORY = re.compile(r"\bhow\s+much\s+(?:memory|ram)\s+(?:does|do|did|can|could|has|will|would)\s+"
                                  r"(?!i\b|it\b|(?:my|this|the|our)\s+(?:computer|machine|system|pc|laptop|server|box|mac)\b)",
                                  re.I)
CPU = re.compile(r"\b(?:cpu|processor)\s+(?:usage|load|use)\b|\bhow\s+(?:busy|loaded)\s+is\s+(?:my|the)\s+"
                 r"(?:cpu|processor)\b", re.I)
PROCESSES = re.compile(_LEAD + r"(?:(?:what|which)\s+(?:processes|programs)\s+are\s+(?:running|open)(?:\s+(?:now|right\s+now))?|"
                       r"(?:list|show(?:\s+me)?)\s+(?:all\s+)?(?:the\s+|my\s+)?(?:running\s+)?processes|"
                       r"(?:the\s+)?running\s+processes|ps(?:\s+aux)?)" + _END, re.I)
TOP = re.compile(r"\b(?:what(?:'s|\s+is)|which\s+(?:process(?:es)?|programs?|apps?))\s+(?:is\s+|are\s+)?"
                 r"(?:using|eating|hogging|taking)\s+(?:up\s+)?(?:the\s+most\s+|all\s+(?:the|my)\s+|my\s+)?"
                 r"(?P<what>memory|ram|cpu)\b", re.I)
PORT = re.compile(r"\b(?:what(?:'s|\s+is)\s+(?:using|on|listening\s+on|running\s+on)\s+port\s+"
                  r"(?P<port>\d{1,5})|(?:open|listening)\s+ports|which\s+ports\s+are\s+(?:open|in\s+use))\b",
                  re.I)
RUNNING = re.compile(_LEAD + r"is\s+(?P<name>[a-z0-9][a-z0-9_.+-]{1,40})\s+(?:running|up|still\s+running)"
                     + _END, re.I)
UPTIME = re.compile(r"\b(?:uptime|how\s+long\s+has\s+(?:the|my|this)\s+(?:computer|machine|system|pc|laptop)"
                    r"\s+been\s+(?:on|up|running))\b", re.I)
_A_DOMAIN = re.compile(r"^(?:[a-z0-9-]+\.)+(?:com|org|net|io|dev|ai|app|co|uk|de|fr|edu|gov|me|info|sh|so|"
                       r"xyz|tech|cloud|site|page|us|ca|au|in|jp|cn|nl|eu|ly|gg|tv|fm)$", re.I)
_NOT_PROGRAMS = frozenset("it this that he she they my the your our everything anything something "
                          "someone everyone nothing life work".split())

SIZE = re.compile(_LEAD + r"(?:how\s+(?:big|large)\s+is|(?:what(?:'s|\s+is)\s+)?the\s+size\s+of|size\s+of|"
                  r"disk\s+usage\s+of)\s+" + _THE + _PATH + _FOLDER_WORD + _END, re.I)
LINES = re.compile(_LEAD + r"how\s+many\s+lines\s+(?:are\s+|of\s+code\s+)?(?:in|of)\s+" + _THE + _PATH + _END, re.I)
COUNT = re.compile(_LEAD + r"(?:how\s+many|count\s+(?:up\s+)?(?:all\s+)?(?:the\s+|my\s+)?)\s*(?:(?P<kind>" + _KIND_WORDS + r")\s+)?files\s+(?:are\s+)?"
                   r"(?:there\s+)?(?:in|under|inside)\s+" + _THE + _PATH + _FOLDER_WORD + _END, re.I)

_DIRS = r"(?:(?:sub)?folders|(?:sub)?directories|dirs)"
LIST = re.compile(_LEAD + r"(?:what(?:'s|\s+is)\s+in(?:side)?|what\s+(?:files|" + _DIRS + r")\s+are\s+(?:there\s+)?in|"
                  r"(?:the\s+)?list\s+of\s+(?:all\s+)?(?:the\s+)?(?:files|contents|everything|" + _DIRS + r")"
                  r"(?:\s+(?:in|of|inside))?|"
                  r"list(?:\s+(?:all\s+)?(?:the\s+)?(?:files|contents|everything|what's|" + _DIRS + r"))?"
                  r"(?:\s+(?:in|of|inside))?|ls|"
                  r"(?:show(?:\s+me)?\s+)?(?:all\s+)?(?:the\s+)?(?:files|contents|everything|" + _DIRS + r")"
                  r"\s+(?:in|of|inside))\s+" + _THE + _PATH + _FOLDER_WORD + _END, re.I)
MY_FOLDERS = re.compile(_LEAD + r"(?:list|show(?:\s+me)?|what\s+are)\s+(?:all\s+)?(?:of\s+)?my\s+" + _DIRS + _END, re.I)
SHOW_PART = re.compile(_LEAD + r"(?:show(?:\s+me)?\s+|print\s+|read\s+|give\s+me\s+)?(?:the\s+)?"
                       r"(?P<which>first|last|top|bottom)\s+(?P<n>\d{1,4})\s+lines\s+(?:of|in|from)\s+"
                       + _THE + _PATH + _END, re.I)
SHOW = re.compile(_LEAD + r"(?:show(?:\s+me)?|read|cat|open|print|display|view)\s+(?:(?:the|this|that)\s+(?=file\b)|the\s+)?"
                  r"(?:file\s*:?\s+|contents\s+of\s+(?:the\s+)?(?:file\s+)?)?" + _PATH + _END, re.I)
# "what's in README.md": LIST's words, said of a file.
SHOW_WHATS_IN = re.compile(_LEAD + r"what(?:'s|\s+is)\s+in(?:side)?\s+" + _THE + _PATH + _END, re.I)
# "head README.md", "tail -n 20 app.log": the command typed as it is.
HEAD_TAIL = re.compile(r"^\s*(?P<tool>head|tail)(?:\s+-n\s*(?P<n>\d{1,4})|\s+-(?P<m>\d{1,4}))?\s+(?:--\s+)?(?P<path>\S+)\s*$",
                       re.I)
# "open the readme": the few files every project has, named without their ending.
_USUAL_FILES = frozenset("readme license licence changelog contributing makefile dockerfile authors".split())

GREP_IN = re.compile(_LEAD + r"(?:search|grep|look|find|check)(?:\s+for)?\s+(?P<q>\"[^\"]+\"|'[^']+'|`[^`]+`|.+?)"
                     + _IN + _END, re.I)
GREP_WHICH = re.compile(_LEAD + r"(?:which|what)\s+files\s+(?:mention|contain|reference|use|include|say|have|import)s?"
                        r"\s+(?P<q>\"[^\"]+\"|'[^']+'|`[^`]+`|.+?)(?:\s+in\s+(?:them|it)|" + _IN + r")?" + _END, re.I)
# "search ~/projects for TODO", "search inside ~/projects for helper": the folder first. The
# folder has to exist, so "search google for cats" stays a web search.
GREP_PLACE_FIRST = re.compile(_LEAD + r"(?:search|grep|look|check)\s+(?:(?:in|inside|within|through)\s+)?" + _THE + _PATH
                              + _FOLDER_WORD + r"\s+for\s+(?P<q>\"[^\"]+\"|'[^']+'|`[^`]+`|.+?)" + _END, re.I)
# "any TODOs in ~/projects?": one word, and a folder or file that exists.
GREP_ANY = re.compile(_LEAD + r"(?:are\s+there\s+)?any\s+(?P<q>\"[^\"]+\"|'[^']+'|`[^`]+`|[A-Za-z_][\w.-]*)" + _IN + _END, re.I)
# "grep -r TODO .": a grep typed as a command; only its pattern and folder are kept.
GREP_TYPED = re.compile(r"^\s*grep\s+(?:-[A-Za-z]+\s+)*(?P<q>\"[^\"]+\"|'[^']+'|[^\s-]\S*)(?:\s+(?P<path>\S+))?\s*$")
GREP_WHERE = re.compile(_LEAD + r"where\s+(?:is|are)\s+(?P<q>\"[^\"]+\"|'[^']+'|`[^`]+`|\S+)\s+"
                        r"(?:used|mentioned|called|imported|referenced)(?:" + _IN + r")?"
                        + _END, re.I)

FIND_KIND = re.compile(_LEAD + r"(?:(?:find|list|show(?:\s+me)?|get|locate|search\s+for|look\s+for|are\s+there|"
                       r"do\s+i\s+have)\s+|(?=any\s))"
                       r"(?:all\s+|the\s+|my\s+|any\s+|me\s+)*(?P<kind>" + _KIND_WORDS + r")\s+files"
                       r"(?:" + _IN + r")?" + _END, re.I)
FIND_BIG = re.compile(_LEAD + r"(?:find|list|show(?:\s+me)?|what(?:'s|\s+is|\s+are))?\s*(?:the\s+)?(?:(?P<top>\d{1,3})\s+)?"
                      r"(?:largest|biggest)\s+(?:(?P<kind>" + _KIND_WORDS + r")\s+)?(?P<files>files?)(?:" + _IN + r")?"
                      + _END, re.I)
# "the newest file in ~/Downloads", "latest 5 pdf files": newest first, with no time limit.
FIND_NEWEST = re.compile(_LEAD + r"(?:find|list|show(?:\s+me)?|what(?:'s|\s+is|\s+are))?\s*(?:the\s+|my\s+)?"
                         r"(?:(?P<top>\d{1,3})\s+)?(?:newest|latest|most\s+recent(?:ly\s+(?:modified|changed))?|"
                         r"last\s+(?:modified|changed))\s+(?:(?P<kind>" + _KIND_WORDS + r")\s+)?(?P<files>files?)"
                         r"(?:" + _IN + r")?" + _END, re.I)
FIND_OVER = re.compile(_LEAD + r"(?:find|list|show(?:\s+me)?)?\s*(?:all\s+|any\s+)?files\s+(?:bigger|larger|over|above|more)"
                       r"\s+(?:than\s+)?(?P<n>\d+(?:\.\d+)?)\s*(?P<unit>k|kb|m|mb|g|gb)\b(?:" + _IN + r")?" + _END, re.I)
FIND_RECENT = re.compile(_LEAD + r"(?:find|list|show(?:\s+me)?|what\s+are)?\s*(?:the\s+)?(?:(?:recently|recent)\s+)?"
                         r"(?:(?:modified|changed|edited)\s+)?files(?:\s+(?:i\s+)?(?:modified|changed|edited|touched))?"
                         r"\s*(?P<when>today|recently|this\s+week|in\s+the\s+(?:last|past)\s+(?:(?P<n>\d{1,3})\s+)?"
                         r"(?P<unit>minutes?|hours?|days?|weeks?))?(?:" + _IN + r")?" + _END, re.I)
FIND_NAME = re.compile(_LEAD + r"(?:find|locate|search\s+for|look\s+for|where(?:'s|\s+is|\s+are))\s+"
                       r"(?:the\s+|my\s+|all\s+|any\s+|a\s+|me\s+|this\s+)*(?P<object>(?:(?:" + _KIND_WORDS + r")\s+)?"
                       r"(?:files?|folders?|directories|dirs?)\s+"
                       r"(?:named|called|matching|like|with\s+(?:the\s+)?name)?\s*)?"
                       r"(?P<name>\"[^\"]+\"|'[^']+'|\S+)(?:\s+(?P<kind>" + _KIND_WORDS + r"))?(?P<noun>\s+(?:file|folder|directory))?"
                       r"(?:" + _IN + r")?"
                       + _END, re.I)

_LOOKS_LIKE_A_FILE = re.compile(r"[*?]|\.[A-Za-z0-9]{1,8}$")


def _path_or(match, default, want="dir"):
    """The path a match names, the default when it names none, None when it names a missing one."""
    token = match.groupdict().get("path")
    if not token:
        return default
    return resolve(token, want)


def plan(text):
    """The Plan for a line that asks for a local command, or None."""
    if not enabled() or not text or len(text) > 400:
        return None
    text = tidy_line(text)
    try:
        found = _plan(text)
    except Outside as error:
        return Plan("refuse", [], title="outside", reason=(
            "%s is outside your home folder, so I won't look there. Everything I run stays inside %s."
            % (error.args[0], home())))
    if found is not None and found.kind != "refuse":
        for arg in found.argv[1:]:
            if arg.startswith("/") and os.path.exists(arg) and is_secret(arg):
                return Plan("refuse", [], title="secret", reason=(
                    "%s holds keys or tokens, so I won't list, search or show it." % arg))
        found.cwd = found.cwd or workdir()
    return found


def _plan(text):
    # The finds by kind, size and age go before the content search ("find all python files in x"
    # is a find); a find by name goes after it ("find TODO in x" is a search inside the files).
    from . import devtools  # noqa: PLC0415 - it builds on this module's pieces
    for reader in devtools.READERS + (_git, _machine, _sizes, _show, _list, _find_by, _grep, _find_by_name):
        found = reader(text)
        if found is not None:
            return found
    return None


def _git(text):
    for pattern, kind in ((GIT_STATUS, "status"), (GIT_LOG, "log"), (GIT_CHANGED, "changed"),
                          (GIT_BRANCH, "branch")):
        found = pattern.match(text)
        if not found:
            continue
        repo = _path_or(found, workdir())
        if not repo or not _in_a_repo(repo):
            return None
        if kind == "status":
            return Plan("lines", ["git", "-C", repo, "status", "--short", "--branch"],
                        title="git status", limit=30, empty="Nothing to commit: the working tree is clean.")
        if kind == "log":
            n = min(int(found.group("n") or 10), 50)
            return Plan("lines", ["git", "-C", repo, "log", "--oneline", "--decorate", "-n", str(n)],
                        title="recent commits", limit=n)
        if kind == "changed":
            return Plan("lines", ["git", "-C", repo, "diff", "--stat", "HEAD"], title="changes since the last commit",
                        limit=30, empty="Nothing has changed since the last commit.")
        return Plan("lines", ["git", "-C", repo, "branch", "--show-current"], title="current branch", limit=1)
    return None


def _in_a_repo(path):
    while True:
        if os.path.exists(os.path.join(path, ".git")):
            return True
        parent = os.path.dirname(path)
        if parent == path:
            return False
        path = parent


def _machine(text):
    found = PORT.search(text)
    if found:
        return Plan("ports", ["ss", "-ltnpH"], title="listening ports", limit=25, port=found.group("port"))
    found = TOP.search(text)
    if found:
        key = "-%cpu" if found.group("what").lower() == "cpu" else "-%mem"
        return Plan("table", ["ps", "-eo", "pid,user,%cpu,%mem,comm", "--sort=" + key],
                    title="top processes by " + found.group("what").lower(), limit=8)
    if DISK.search(text):
        return Plan("table", ["df", "-h", "-x", "tmpfs", "-x", "devtmpfs", "-x", "squashfs", "-x", "overlay",
                         "-x", "fuse.snapfuse"],
                    title="disk space", limit=15)
    if MEMORY.search(text) and _MACHINE_MEMORY.search(text) and not _SOMEONE_ELSES_MEMORY.search(text):
        return Plan("table", ["free", "-h"], title="memory", limit=5)
    if CPU.search(text):
        return Plan("table", ["ps", "-eo", "pid,user,%cpu,%mem,comm", "--sort=-%cpu"],
                    title="top processes by cpu", limit=8)
    if PROCESSES.match(text):
        return Plan("table", ["ps", "-eo", "pid,user,%cpu,%mem,comm", "--sort=-%cpu"],
                    title="running processes", limit=15)
    if UPTIME.search(text):
        return Plan("lines", ["uptime", "-p"], title="uptime", limit=1)
    found = RUNNING.match(text)
    # "is python.org up" names a site (web_inspect checks it), not a program called python.org.
    if found and found.group("name").lower() not in _NOT_PROGRAMS and not _A_DOMAIN.match(found.group("name")):
        name = found.group("name")
        return Plan("running", ["pgrep", "-a", "-i", "--", name], title="is %s running" % name, limit=10,
                    name=name)
    return None


def _sizes(text):
    found = COUNT.match(text)
    if found:
        root = resolve(found.group("path"), "dir")
        if root:
            kind = (found.group("kind") or "").lower()
            tests = (_name_tests(KINDS[kind]) if kind else []) + ["-type", "f", "-print"]
            return _find(root, tests, "how many %sfiles" % (kind + " " if kind else ""), kind="count")
    found = LINES.match(text)
    if found:
        path = resolve(found.group("path"), "file")
        if path and is_secret(path):
            return Plan("refuse", [], title="lines", reason="%s looks like a secrets file, so I won't read it."
                        % os.path.basename(path))
        if path:
            return Plan("wc", ["wc", "-l", "--", path], title="lines", limit=1)
    found = SIZE.match(text)
    if found:
        path = resolve(found.group("path"))
        if path:
            return Plan("lines", ["du", "-sh", "--", path], title="size", limit=1)
    return None


def _show(text):
    found = SHOW_PART.match(text)
    want = None
    if found:
        path = resolve(found.group("path"), "file")
        n = min(int(found.group("n")), 500)
        want = ("tail" if found.group("which").lower() in ("last", "bottom") else "head", n)
    elif HEAD_TAIL.match(text):
        found = HEAD_TAIL.match(text)
        path = resolve(found.group("path"), "file")
        n = min(int(found.group("n") or found.group("m") or (20 if found.group("tool").lower() == "tail" else 40)), 500)
        want = (found.group("tool").lower(), n)
    else:
        found = SHOW.match(text) or SHOW_WHATS_IN.match(text)
        if not found:
            return None
        path = resolve(found.group("path"), "file") or _usual_file(found.group("path"))
        want = ("head", 40)
    if not path:
        return None
    if is_secret(path):
        return Plan("refuse", [], title="show", reason="%s looks like a secrets file, so I won't print it."
                    % os.path.basename(path))
    tool, n = want
    return Plan("file", [tool, "-n", str(n), "--", path], title="%s %d lines" % (tool, n), limit=n, path=path)


def _usual_file(token):
    """README.md for "readme": a file every project has, in the work folder, named without its ending."""
    token = (token or "").strip().strip("\"'").lower()
    if token not in _USUAL_FILES:
        return None
    try:
        names = sorted(os.listdir(workdir()))
    except OSError:
        return None
    hits = [n for n in names if n.lower() == token or n.lower().split(".")[0] == token]
    hits = [os.path.join(workdir(), n) for n in hits if os.path.isfile(os.path.join(workdir(), n))]
    return hits[0] if hits else None


def _list(text):
    if MY_FOLDERS.match(text):
        # "list my folders": the folders in home, one level down
        return _folders(home())
    found = LIST.match(text)
    if not found:
        return None
    path = resolve(found.group("path"), "dir")
    if not path:
        return None
    if re.search(r"\b" + _DIRS + r"\b", text[:found.start("path")], re.I):
        return _folders(path)
    return Plan("listing", ["ls", "-lAh", "--group-directories-first", "--", path], title="listing", limit=40)


def _folders(path):
    """Every folder one level down in path, except the secrets folders ("list all the folders in ~")."""
    argv = ["find", path, "-mindepth", "1", "-maxdepth", "1"] + _prune_args(caches=False) + ["-type", "d", "-print"]
    return Plan("files", argv, title="folders", limit=60, root=path, sort=True)


def _grep_argv(pattern, root):
    # -H: name the file even when the search is a single file, so every line reads "path:line:text".
    argv = ["grep", "-rnHIi", "--color=never", "-m", str(GREP_PER_FILE)]
    for name in PRUNE + tuple(d for d in SECRET_DIRS if "/" not in d):
        argv.append("--exclude-dir=" + name)
    for glob in SECRET_GLOBS:
        argv.append("--exclude=" + glob)
    return argv + ["-e", pattern, "--", root]


def _grep(text):
    for pattern in (GREP_TYPED, GREP_WHICH, GREP_WHERE, GREP_PLACE_FIRST, GREP_IN, GREP_ANY):
        found = pattern.match(text)
        if not found:
            continue
        query = _unquote(found.group("q"))
        if pattern is GREP_ANY and re.match(r"^[A-Z]{3,}s$", query):
            query = query[:-1]  # "any TODOs" looks for TODO
        if pattern in (GREP_IN, GREP_ANY):
            # "search for *.pdf in downloads" and "find files named x in y" are finds, not greps.
            if _LOOKS_LIKE_A_FILE.search(query) or re.search(r"\b(?:files?|folders?|directories)\b",
                                                              query, re.I):
                return None
        root = _path_or(found, workdir(), "any")
        if not root or len(query) < 2:
            continue
        return Plan("grep", _grep_argv(query, root), title="search for \"%s\"" % query, limit=20,
                    root=root, query=query)
    return None


def _find_by(text):
    found = FIND_KIND.match(text)
    if found:
        root = _path_or(found, workdir())
        if not root:
            return None
        kind = found.group("kind").lower()
        return _find(root, _name_tests(KINDS[kind]) + ["-type", "f", "-print"], "%s files" % kind)
    found = FIND_BIG.match(text)
    if found:
        root = _path_or(found, workdir())
        if not root:
            return None
        one = found.group("files").lower() == "file"
        top = min(int(found.group("top") or (1 if one else 10)), 50)
        kind = (found.group("kind") or "").lower()
        # Without a kind, small files can't be the biggest; with one ("the biggest log file") they can.
        tests = _name_tests(KINDS[kind]) if kind else ["-size", "+100k"]
        return _find(root, tests + ["-type", "f", "-printf", "%s\\t%p\\n"],
                     "largest %sfiles" % (kind + " " if kind else ""), kind="sized", limit=top)
    found = FIND_NEWEST.match(text)
    if found:
        root = _path_or(found, workdir())
        if not root:
            return None
        one = found.group("files").lower() == "file"
        top = min(int(found.group("top") or (1 if one else 10)), 50)
        kind = (found.group("kind") or "").lower()
        tests = _name_tests(KINDS[kind]) if kind else []
        return _find(root, tests + ["-type", "f", "-printf", "%T@\\t%p\\n"],
                     "newest %sfiles" % (kind + " " if kind else ""), kind="recent", limit=top)
    found = FIND_OVER.match(text)
    if found:
        root = _path_or(found, workdir())
        if not root:
            return None
        unit = {"k": "k", "kb": "k", "m": "M", "mb": "M", "g": "G", "gb": "G"}[found.group("unit").lower()]
        size = max(1, int(float(found.group("n"))))
        return _find(root, ["-type", "f", "-size", "+%d%s" % (size, unit), "-printf", "%s\\t%p\\n"],
                     "files over %d%s" % (size, unit.upper() + "B" if unit != "k" else "KB"), kind="sized", limit=25)
    found = FIND_RECENT.match(text)
    if found and (found.group("when") or re.search(r"\b(?:recent|modified|changed|edited)\b", text, re.I)):
        root = _path_or(found, workdir())
        if not root:
            return None
        minutes = 24 * 60
        when = (found.group("when") or "").lower()
        if "week" in when and not found.group("unit"):
            minutes = 7 * 24 * 60
        elif found.group("unit"):
            n = int(found.group("n") or 1)
            per = {"m": 1, "h": 60, "d": 24 * 60, "w": 7 * 24 * 60}[found.group("unit")[0].lower()]
            minutes = n * per
        return _find(root, ["-type", "f", "-mmin", "-%d" % minutes, "-printf", "%T@\\t%p\\n"],
                     "files changed in the last %s" % _span(minutes), kind="recent", limit=20)
    return None


def _find_by_name(text):
    found = FIND_NAME.match(text)
    if found:
        name = _unquote(found.group("name"))
        named_a_path = bool(found.groupdict().get("path"))
        kind = (found.group("kind") or "").lower()
        filelike = bool(found.group("object") or found.group("noun") or kind or _LOOKS_LIKE_A_FILE.search(name))
        if not filelike and not named_a_path:
            return None  # "where is paris" is not a file search
        if kind and len(name) < 3:
            return None
        # A name with no folder is looked for in the whole home folder: "find taxes-2025.pdf"
        # should not come back empty because the file is not under the work folder.
        root = _path_or(found, home())
        if not root or len(name) < 2:
            return None
        pattern = name if re.search(r"[*?]", name) else "*%s*" % name
        objects = (found.group("object") or "") + (found.group("noun") or "")
        type_test = ["-type", "d"] if re.search(r"folder|director|dir", objects, re.I) else []
        kind_test = _name_tests(KINDS[kind]) if kind else []
        return _find(root, ["-iname", pattern] + kind_test + type_test + ["-print"],
                     "%s files named %s" % (kind, name) if kind else "files named %s" % name)
    return None


def _span(minutes):
    if minutes % (7 * 24 * 60) == 0:
        n, unit = minutes // (7 * 24 * 60), "week"
    elif minutes % (24 * 60) == 0:
        n, unit = minutes // (24 * 60), "day"
    elif minutes % 60 == 0:
        n, unit = minutes // 60, "hour"
    else:
        n, unit = minutes, "minute"
    return unit if n == 1 else "%d %ss" % (n, unit)
