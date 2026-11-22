"""More local asks, for a developer's machine: command help, git on one file,
errors in a log, a project's dependencies, file checks, and a few network checks.

Same rules as bot/tools/local.py: one fixed template per ask, the person's words only fill in
arguments, nothing writes, every path must exist and be inside the home folder. Some answers
need no program at all (reading package.json, a DNS lookup) and are worked out in
Python, as Plan("py", ...) with the function to call.
"""
import json
import os
import re
import shutil
import socket
import subprocess

from .local import (_END, _FOLDER_WORD, _IN, _LEAD, _PATH, _THE, Plan, _in_a_repo, _path_or, _unquote,
                    home, is_secret, resolve, workdir)



def _tidy(path):
    real_home = os.path.expanduser("~")
    return "~" + path[len(real_home):] if path.startswith(real_home + os.sep) else path


# --- help for a command ----------------------------------------------------------------------

HELP = re.compile(_LEAD + r"(?:how\s+(?:do\s+(?:i|you)\s+|to\s+|can\s+i\s+)use\s+(?:the\s+)?|help\s+(?:me\s+)?with\s+(?:the\s+)?|"
                  r"what\s+does\s+(?:the\s+)?|man\s+(?:page\s+(?:for\s+)?)?|usage\s+(?:of|for)\s+(?:the\s+)?|"
                  r"explain\s+(?:the\s+)?)`?(?P<cmd>[a-z][a-z0-9._+-]{0,40})`?(?P<qual>\s+(?:command|cmd|tool|"
                  r"in\s+(?:linux|bash|the\s+terminal|the\s+shell)))?(?:\s+do)?" + _END, re.I)
# Words that are commands and also everyday words: these need "the X command" to count.
_EVERYDAY = frozenset("time sleep yes true false test more less join sort split write wall look watch last date "
                      "cal kill at cut paste touch file find help read echo which who w users tree head tail "
                      "top free type wait print link shift rename install make patch top spell units fold "
                      "expand tac nice script screen fmt mail lock open run start stop".split())


def _help(text):
    found = HELP.match(text)
    if not found:
        return None
    cmd = found.group("cmd").lower()
    if cmd in _EVERYDAY and not found.group("qual"):
        return None
    try:
        known = subprocess.run(["man", "-w", cmd], capture_output=True, text=True, timeout=5,
                               stdin=subprocess.DEVNULL).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        known = False
    if not known:
        return None
    return Plan("man", ["man", "-P", "cat", cmd], title="help for %s" % cmd, limit=30, cmd=cmd)


# --- git on one file --------------------------------------------------------------------------

BLAME = re.compile(_LEAD + r"who\s+(?:last\s+)?(?:changed|wrote|edited|touched)\s+line\s+(?P<line>\d{1,6})\s+"
                   r"(?:of|in)\s+" + _THE + _PATH + _END, re.I)
FILE_HISTORY = re.compile(_LEAD + r"(?:(?:show\s+(?:me\s+)?)?(?:the\s+)?(?:git\s+)?(?:history|log)\s+(?:of|for)|"
                          r"who\s+(?:last\s+)?(?:changed|edited|wrote|worked\s+on))\s+" + _THE + _PATH + _END, re.I)
FILE_DIFF = re.compile(_LEAD + r"(?:show\s+(?:me\s+)?(?:the\s+)?(?:git\s+)?diff\s+(?:for|of|in)|what(?:'s|\s+has|\s+have)?\s+"
                       r"changed\s+in|(?:git\s+)?diff)\s+" + _THE + _PATH + _END, re.I)


def _git_file(text):
    for pattern, kind in ((BLAME, "blame"), (FILE_HISTORY, "history"), (FILE_DIFF, "diff")):
        found = pattern.match(text)
        if not found:
            continue
        path = resolve(found.group("path"), "file")
        if not path or not _in_a_repo(os.path.dirname(path)):
            return None
        folder, name = os.path.dirname(path), os.path.basename(path)
        if kind == "blame":
            line = found.group("line")
            return Plan("lines", ["git", "-C", folder, "blame", "-L", "%s,%s" % (line, line),
                                  "--date=short", "--", name], title="blame", limit=3)
        if kind == "history":
            return Plan("lines", ["git", "-C", folder, "log", "-n", "10", "--date=short",
                                  "--format=%h %ad %an  %s", "--", name], title="history", limit=10,
                        empty="No commits touch that file yet.")
        return Plan("lines", ["git", "-C", folder, "diff", "HEAD", "--", name], title="diff", limit=60,
                    empty="No changes in that file since the last commit.")
    return None


# --- errors in a log ---------------------------------------------------------------------------

LOG_ERRORS = re.compile(_LEAD + r"(?:show\s+(?:me\s+)?|find\s+|list\s+|are\s+there\s+|any\s+)?(?:the\s+)?(?:any\s+)?"
                        r"(?:(?:last|latest|recent)\s+(?:(?P<n>\d{1,3})\s+)?)?(?P<what>errors?|warnings?|problems|"
                        r"exceptions|failures)\s+(?:in|from|inside)\s+" + _THE + _PATH + _END, re.I)


def _logs(text):
    found = LOG_ERRORS.match(text)
    if not found:
        return None
    path = resolve(found.group("path"), "any")
    if not path or is_secret(path):
        return None
    what = found.group("what").lower()
    words = "warn|warning" if what.startswith("warn") else "error|err|fatal|exception|traceback|critical|fail(ed|ure)?|panic"
    argv = ["grep", "-nIEi", "--color=never"] + (["-r"] if os.path.isdir(path) else []) + [
        "-e", r"\b(%s)\b" % words, "--", path]
    return Plan("loglines", argv, title=what, limit=int(found.group("n") or 20), root=path)


# --- a project's packages ------------------------------------------------------------------------

PIP_LIST = re.compile(r"\b(?:what\s+(?:python\s+)?packages\s+(?:are|do\s+i\s+have)\s+installed|"
                      r"(?:list|show)\s+(?:the\s+|my\s+)?installed\s+(?:python\s+)?packages|pip\s+list|"
                      r"installed\s+python\s+packages)\b", re.I)
DEPENDENCIES = re.compile(_LEAD + r"(?:what(?:'s|\s+is|\s+are)\s+(?:in\s+)?|show\s+(?:me\s+)?|list\s+|read\s+)?(?:the\s+)?"
                          r"(?:(?P<file>package\.json|pyproject\.toml|requirements(?:\.txt)?|cargo\.toml|go\.mod)|"
                          r"(?:dependencies|deps|packages|requirements)(?:\s+(?:of|for|in)\s+" + _THE + _PATH +
                          _FOLDER_WORD + r")?|(?:project|npm)\s+scripts)" + _END, re.I)


def _project(text):
    if PIP_LIST.search(text):
        python = shutil.which("python3") or shutil.which("python") or "python3"
        return Plan("table", [python, "-m", "pip", "list", "--disable-pip-version-check"], title="packages",
                    limit=40)
    found = DEPENDENCIES.match(text)
    if not found:
        return None
    folder = _path_or(found, workdir())
    if not folder:
        return None
    named = (found.group("file") or "").lower()
    choices = [named + (".txt" if named == "requirements" else "")] if named else [
        "package.json", "pyproject.toml", "requirements.txt", "Cargo.toml", "go.mod"]
    for choice in choices:
        path = os.path.join(folder, choice)
        if os.path.isfile(path):
            return Plan("py", ["read", path], title="dependencies", fn=lambda p=path: _manifest(p),
                        how="reading %s" % choice)
    return None


def _manifest(path):
    name = os.path.basename(path)
    try:
        with open(path, "rb") as handle:
            raw = handle.read(2_000_000)
    except OSError as error:
        return "Couldn't read %s: %s." % (name, error)
    out = []
    if name == "package.json":
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except ValueError as error:
            return "%s isn't valid JSON: %s." % (name, error)
        out.append("%s %s" % (data.get("name", "(no name)"), data.get("version", "")))
        for key in ("scripts", "dependencies", "devDependencies"):
            items = data.get(key) or {}
            if items:
                out.append("%s (%d):" % (key, len(items)))
                out += ["  %s: %s" % (k, v) for k, v in list(items.items())[:25]]
    elif name == "pyproject.toml":
        try:
            import tomllib  # noqa: PLC0415 - Python 3.11+
            data = tomllib.loads(raw.decode("utf-8", "replace"))
        except Exception as error:  # noqa: BLE001 - an old Python or a bad file: say which
            return "Couldn't read %s: %s." % (name, error)
        project = data.get("project") or data.get("tool", {}).get("poetry") or {}
        out.append("%s %s" % (project.get("name", "(no name)"), project.get("version", "")))
        deps = project.get("dependencies") or []
        if isinstance(deps, dict):
            deps = ["%s %s" % kv for kv in deps.items()]
        out.append("dependencies (%d):" % len(deps))
        out += ["  " + str(d) for d in deps[:30]]
    else:
        lines = [line.strip() for line in raw.decode("utf-8", "replace").splitlines()
                 if line.strip() and not line.strip().startswith(("#", "//"))]
        out.append("%s: %d lines" % (name, len(lines)))
        out += ["  " + line for line in lines[:40]]
    return "%s\n%s" % (_tidy(path), "\n".join(out))


# --- file checks -----------------------------------------------------------------------------

HASH = re.compile(_LEAD + r"(?:what(?:'s|\s+is)\s+)?(?:the\s+)?(?P<algo>sha-?256|sha-?1|sha-?512|md5)(?:\s*(?:sum|hash|checksum))?"
                  r"\s+(?:of|for)\s+" + _THE + _PATH + _END + r"|" + _LEAD + r"(?:what(?:'s|\s+is)\s+)?(?:the\s+)?"
                  r"(?:checksum|hash)\s+(?:of|for)\s+" + _THE + r"(?P<path2>\S+)" + _END, re.I)
FILE_TYPE = re.compile(_LEAD + r"(?:what\s+(?:type|kind)\s+of\s+file\s+is|(?:the\s+)?file\s+type\s+of|what\s+is\s+the\s+file)\s+"
                       + _THE + _PATH + _END, re.I)
FILE_INFO = re.compile(_LEAD + r"(?:when\s+was\s+" + _THE + r"(?P<p1>\S+)\s+(?:last\s+)?(?:modified|changed|edited|created)|"
                       r"(?:who\s+owns|(?:what\s+are\s+)?(?:the\s+)?permissions\s+(?:of|on)|(?:file\s+)?info(?:rmation)?\s+"
                       r"(?:about|on|for)|stat)\s+" + _THE + r"(?P<p2>\S+))" + _END, re.I)


def _file_checks(text):
    found = HASH.match(text)
    if found:
        path = resolve(found.group("path") or found.group("path2"), "file")
        if not path:
            return None
        algo = (found.group("algo") or "sha256").lower().replace("-", "")
        return Plan("hash", [algo + "sum", "--", path], title=algo, limit=1, algo=algo)
    found = FILE_TYPE.match(text)
    if found:
        path = resolve(found.group("path"))
        if path:
            return Plan("lines", ["file", "-b", "--", path], title="file type", limit=2)
        return None
    found = FILE_INFO.match(text)
    if found:
        path = resolve(found.group("p1") or found.group("p2"))
        if path:
            return Plan("lines", ["stat", "--printf", "size: %s bytes\\ntype: %F\\nowner: %U:%G\\n"
                                  "permissions: %A (%a)\\nmodified: %y\\naccessed: %x\\n", "--", path],
                        title="info", limit=8)
    return None


# --- network --------------------------------------------------------------------------------------

_HOST = r"(?P<host>(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}|\d{1,3}(?:\.\d{1,3}){3}|localhost)"
DNS = re.compile(_LEAD + r"(?:what(?:'s|\s+is)\s+(?:the\s+)?ip(?:\s+address)?\s+(?:of|for)|(?:dns|nslookup|dig)\s+(?:for\s+|of\s+)?|"
                 r"(?:look\s*up|resolve)\s+(?:the\s+)?(?:ip\s+(?:of|for)\s+)?)\s*" + _HOST + _END, re.I)
PORT_CHECK = re.compile(_LEAD + r"(?:is|check\s+(?:if|whether)?)\s*port\s+(?P<port>\d{1,5})\s+(?:open\s+)?(?:on|at)\s+"
                        + _HOST + r"(?:\s+open)?" + _END + r"|" + _LEAD + r"can\s+i\s+(?:reach|connect\s+to)\s+"
                        r"(?P<host2>\S+)\s+on\s+port\s+(?P<port2>\d{1,5})" + _END, re.I)
MY_IP = re.compile(r"\b(?:what(?:'s|\s+is)\s+my\s+(?:local\s+)?ip(?:\s+address)?|my\s+(?:local\s+)?ip\s+address)\b", re.I)


def _network(text):
    if MY_IP.search(text):
        return Plan("lines", ["hostname", "-I"], title="local addresses", limit=2)
    found = DNS.match(text)
    if found:
        host = found.group("host").lower()
        return Plan("py", ["getaddrinfo", host], title="dns", fn=lambda: _dns(host), how="a DNS lookup")
    found = PORT_CHECK.match(text)
    if found:
        host = (found.group("host") or found.group("host2") or "").lower().strip(".,")
        port = int(found.group("port") or found.group("port2"))
        if not 0 < port < 65536:
            return None
        return Plan("py", ["connect", host, str(port)], title="port", fn=lambda: _port(host, port),
                    how="a TCP connection, closed straight away")
    return None


def _dns(host):
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError) as error:
        return "%s doesn't resolve (%s)." % (host, error.args[-1] if error.args else "no answer")
    v4 = sorted({i[4][0] for i in infos if i[0] == socket.AF_INET})
    v6 = sorted({i[4][0] for i in infos if i[0] == socket.AF_INET6})
    parts = []
    if v4:
        parts.append("IPv4: " + ", ".join(v4))
    if v6:
        parts.append("IPv6: " + ", ".join(v6[:4]))
    return "%s resolves to\n  %s" % (host, "\n  ".join(parts))


def _port(host, port):
    import time  # noqa: PLC0415
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=3):
            pass
    except socket.timeout:
        return "Port %d on %s didn't answer within 3 seconds (filtered, or the host is down)." % (port, host)
    except ConnectionRefusedError:
        return "Port %d on %s is closed: the host answered and refused the connection." % (port, host)
    except (socket.gaierror, UnicodeError):
        return "%s doesn't resolve." % host
    except OSError as error:
        return "Couldn't reach %s:%d (%s)." % (host, port, error.strerror or error.__class__.__name__)
    return "Port %d on %s is open (connected in %d ms)." % (port, host, (time.perf_counter() - start) * 1000)


READERS = (_git_file, _help, _logs, _project, _file_checks, _network)
