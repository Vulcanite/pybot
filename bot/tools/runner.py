"""Runs a Plan from local.py and says what came back: "Ran: ...", then what it found.

No shell: argv goes straight to the program, so a pattern or a file name is only ever one
argument. Each run has a timeout and reads at most MAX_OUTPUT characters. The reply keeps its
line breaks (the chat prints them), says how many things were found, shows the first few, and
writes paths under the home folder as ~/...

A line in the output that looks like a key or a password being set has its value masked.
"""
import os
import re
import shlex
import subprocess
import time

from . import ToolError
from .local import GREP_PER_FILE, is_secret

TIMEOUT = 20
MAX_OUTPUT = 300_000
_HOME = os.path.expanduser("~")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_SECRET_VALUE = re.compile(
    r"(?i)((?:api[_-]?key|secret|token|passw(?:or)?d|passwd|private[_-]?key|access[_-]?key|auth)"
    r"[\"']?\s*[:=]\s*[\"']?)([^\s\"',;]{6,})")


def tidy(path):
    """A path as a person would say it: ~/x for things under home."""
    if path == _HOME:
        return "~"
    if path.startswith(_HOME + os.sep):
        return "~" + path[len(_HOME):]
    return path


def _shown(argv):
    """The command as it would be typed, shortened: the long --exclude lists folded away."""
    kept, folded = [], 0
    for arg in argv:
        if arg.startswith(("--exclude-dir=", "--exclude=")):
            folded += 1
            continue
        kept.append(arg)
    text = shlex.join(kept).replace(_HOME + os.sep, "~" + os.sep)
    text = re.sub(r"(?<![\w/])%s(?![\w/])" % re.escape(_HOME), "~", text)
    # find's prune list: "( -name .git -o -name node_modules ... ) -prune -o" -> "<skip caches>"
    text = re.sub(r"'\(' -name .*? '\)' -prune -o", "<skip .git, node_modules, caches>", text)
    if folded:
        text += "  (skipping caches and secret files)"
    return text


def execute(plan):
    """(stdout, stderr, returncode, seconds) for a plan; ToolError when it cannot run at all."""
    start = time.perf_counter()
    try:
        done = subprocess.run(plan.argv, cwd=plan.cwd, capture_output=True, text=True, errors="replace",
                              timeout=TIMEOUT, stdin=subprocess.DEVNULL,
                              env=dict(os.environ, LC_ALL="C.UTF-8", GIT_PAGER="cat", PAGER="cat"))
    except FileNotFoundError:
        raise ToolError("%s is not installed" % plan.argv[0]) from None
    except subprocess.TimeoutExpired:
        raise ToolError("it was still running after %d seconds, so I stopped it" % TIMEOUT) from None
    except OSError as error:
        raise ToolError("it could not be started (%s)" % error.__class__.__name__) from None
    out = _ANSI.sub("", done.stdout[:MAX_OUTPUT])
    err = _ANSI.sub("", done.stderr[:4000])
    return out, err, done.returncode, time.perf_counter() - start


def _mask(line):
    return _SECRET_VALUE.sub(lambda m: m.group(1) + "****", line)


def _size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024


def _more(total, shown):
    return "\n...and %d more." % (total - shown) if total > shown else ""


def _listed(items, limit):
    return "\n".join("  " + item for item in items[:limit]) + _more(len(items), min(limit, len(items)))


def _errors(err):
    """The first stderr line worth saying, with permission noise left out."""
    for line in err.splitlines():
        line = line.strip()
        if line and "Permission denied" not in line:
            return line[:200]
    return ""


def reply_for(plan):
    """The whole reply to a plan: the command, then what it found."""
    if plan.kind == "refuse":
        return plan.extra["reason"]
    if plan.kind == "py":
        # Worked out in Python, no program run: say how, then the answer.
        try:
            said = plan.extra["fn"]()
        except Exception as error:  # noqa: BLE001 - a check that fails says so, it never loses the turn
            said = "That didn't work: %s." % error
        return "Checked with %s:\n%s" % (plan.extra.get("how", "Python"), said)
    try:
        out, err, code, seconds = execute(plan)
    except ToolError as error:
        return "I tried to run `%s`, but %s." % (_shown(plan.argv), error)
    took = " (%.1fs)" % seconds if seconds >= 0.5 else ""
    head = "Ran: `%s`%s\n" % (_shown(plan.argv), took)
    # A file is shown as it is, blank lines and all; every other output loses its blank lines.
    lines = out.splitlines() if plan.kind == "file" else [line for line in out.splitlines() if line.strip()]
    body = _read(plan, lines, err, code)
    return head + body


def _read(plan, lines, err, code):
    kind, limit = plan.kind, plan.limit
    problem = _errors(err)
    if kind == "files":
        if not lines:
            return "Nothing found%s." % (" (%s)" % problem if problem and code not in (0, 1) else "")
        found = [tidy(line) for line in lines]
        return "Found %d:\n%s" % (len(found), _listed(found, limit))
    if kind == "count":
        return "%d %s in %s." % (len(lines), "file" if len(lines) == 1 else "files", tidy(plan.extra["root"]))
    if kind == "sized":
        rows = []
        for line in lines:
            size, _, path = line.partition("\t")
            if size.isdigit():
                rows.append((int(size), path))
        if not rows:
            return "No files that big."
        rows.sort(reverse=True)
        return "Found %d, biggest first:\n%s" % (
            len(rows), _listed(["%9s  %s" % (_size(s), tidy(p)) for s, p in rows], limit))
    if kind == "recent":
        rows = []
        for line in lines:
            stamp, _, path = line.partition("\t")
            try:
                rows.append((float(stamp), path))
            except ValueError:
                continue
        if not rows:
            return "Nothing changed in that time."
        rows.sort(reverse=True)
        return "Found %d, newest first:\n%s" % (len(rows), _listed(
            ["%s  %s" % (time.strftime("%d %b %H:%M", time.localtime(s)), tidy(p)) for s, p in rows], limit))
    if kind == "grep":
        if code == 1 or not lines:
            return "No matches for \"%s\" in %s." % (plan.extra["query"], tidy(plan.extra["root"]))
        if code > 1 and not lines:
            return "grep could not search there: %s." % (problem or "unknown error")
        per_file = {}
        shown = []
        for line in lines:
            path, _, rest = line.partition(":")
            number, _, text = rest.partition(":")
            per_file[path] = per_file.get(path, 0) + 1
            if len(shown) < limit and not is_secret(path):
                shown.append("%s:%s  %s" % (tidy(path), number, _mask(text.strip())[:160]))
        # grep stops at PER_FILE matches in each file (-m), so a file at the cap may hold more:
        # the count says so instead of passing a floor off as the total.
        capped = [p for p, n in per_file.items() if n >= GREP_PER_FILE]
        count = "%s%d matching %s" % ("at least " if capped else "", len(lines), "line" if len(lines) == 1 else "lines")
        note = ("\n(I stop at %d per file; %d %s hit that, so there may be more.)"
                % (GREP_PER_FILE, len(capped), "file" if len(capped) == 1 else "files")) if capped else ""
        return "%s in %d %s:\n%s%s" % (
            count, len(per_file), "file" if len(per_file) == 1 else "files",
            "\n".join("  " + s for s in shown) + _more(len(lines), len(shown)), note)
    if kind == "file":
        path = plan.extra["path"]
        if code != 0:
            return "Couldn't read %s: %s." % (tidy(path), problem or "unknown error")
        try:
            with open(path, "rb") as handle:
                if b"\0" in handle.read(2048):
                    return "%s is a binary file (%s), so there's no text to show." % (
                        tidy(path), _size(os.path.getsize(path)))
            with open(path, "rb") as handle:
                total = sum(1 for _ in handle)
        except OSError:
            total = len(lines)
        text = "\n".join(_mask(line)[:240] for line in lines[:limit])
        note = "" if total <= limit else "\n(%d of %d lines)" % (min(limit, len(lines)), total)
        return "%s:\n%s%s" % (tidy(path), text, note)
    if kind == "wc":
        if code != 0 or not lines:
            return "Couldn't count it: %s." % (problem or "unknown error")
        return "%s lines in %s." % (lines[0].split()[0], tidy(plan.argv[-1]))
    if kind == "running":
        if code == 1 or not lines:
            return "No, nothing called %s is running." % plan.extra["name"]
        own = [line for line in lines if " pgrep " not in line]
        return "Yes, %d %s:\n%s" % (len(own), "process" if len(own) == 1 else "processes",
                                     _listed([line[:160] for line in own], limit))
    if kind == "ports":
        port = plan.extra.get("port")
        rows = []
        for line in lines:
            parts = line.split()
            if len(parts) < 4:
                continue
            local = parts[3]
            process = ""
            found = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
            if found:
                process = "%s (pid %s)" % found.groups()
            if port and not local.endswith(":" + port):
                continue
            rows.append("%-22s %s" % (local, process or "(another user's process)"))
        if port and not rows:
            return "Nothing is listening on port %s." % port
        return "%s:\n%s" % ("Listening on port %s" % port if port else "Listening ports", _listed(rows, limit))
    if kind == "man":
        return _man_summary(plan.extra["cmd"], lines)
    if kind == "hash":
        if code != 0 or not lines:
            return "Couldn't hash it: %s." % (problem or "unknown error")
        digest, _, path = lines[0].partition("  ")
        return "%s of %s:\n  %s" % (plan.extra["algo"].upper(), tidy(path.strip()), digest)
    if kind == "loglines":
        if code == 1 or not lines:
            return "No %s in %s." % (plan.title, tidy(plan.extra["root"]))
        shown = lines[-limit:]
        return "%d %s found, the last %d:\n%s" % (len(lines), "line" if len(lines) == 1 else "lines",
                                                 len(shown), "\n".join("  " + _mask(line.replace(_HOME + os.sep, "~" + os.sep))[:200] for line in shown))
    if kind == "listing":
        if code != 0:
            return "Couldn't list it: %s." % (problem or "unknown error")
        rows = [line for line in lines if not line.startswith("total ")]
        return "%d entries:\n%s" % (len(rows), _listed(rows, limit))
    # "lines" and "table": the output as it is, trimmed.
    if code != 0 and not lines:
        return "It didn't work: %s." % (problem or "exit code %d" % code)
    if not lines:
        return plan.extra.get("empty", "It printed nothing.")
    return _listed([_mask(line.replace(_HOME + os.sep, "~" + os.sep)) for line in lines], limit)


def _man_summary(cmd, lines):
    """NAME, SYNOPSIS and the start of DESCRIPTION from a man page, then its first few options."""
    sections, current = {}, None
    for line in lines:
        if line and not line.startswith(" ") and line.strip().isupper():
            current = line.strip()
            sections[current] = []
        elif current:
            sections[current].append(line.strip())
    def text(name, n):
        body = [l for l in sections.get(name, []) if l]
        return " ".join(body[:n])
    parts = []
    if sections.get("NAME"):
        parts.append(text("NAME", 2))
    if sections.get("SYNOPSIS"):
        usage = [l for l in sections["SYNOPSIS"] if l and not l.endswith(("usage", ":"))][:4]
        parts.append("Usage:\n" + "\n".join("  " + l[:110] for l in usage))
    if sections.get("DESCRIPTION"):
        parts.append(text("DESCRIPTION", 4)[:500])
    options = []
    for name in ("OPTIONS", "COMMON OPTIONS", "OPERATION MODE", "MAIN OPERATION MODE"):
        for line in sections.get(name, []):
            # An option heading line holds options and nothing else: "--verbose, -v", "-f FILE".
            if re.match(r"^-{1,2}[A-Za-z0-9][\w=\[\]-]*(?:,?\s+(?:-{1,2}[\w=\[\]-]+|[A-Z][A-Z_]+))*$", line) \
                    and len(options) < 8:
                options.append("  " + line[:120])
    if options:
        parts.append("Some options:\n" + "\n".join(options))
    if not parts:
        return "The man page for %s printed nothing I could read." % cmd
    return "\n".join(parts) + "\n(Full page: man %s)" % cmd

