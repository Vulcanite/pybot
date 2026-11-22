"""Commands that change or destroy things: PyBot never runs them, it shows the command and a warning.

Not part of the swarm's original bot. local.py runs read-only commands and notes.py makes safe
writes (a new note, an append, a new file). Everything else that changes or deletes (rm, mv,
cp over a file, chmod/chown, kill, install/uninstall, sudo, git reset/clean/push --force,
truncate, dd, mkfs ...) is only ever suggested: `suggest(text)` returns

    {"command": "rm -i ~/Desktop/todo.txt", "warning": "⚠️ This deletes ..."}

for a line that asks for one, or None for a line that does not. Nothing here runs anything.

The rules:
- Only imperative lines ("delete ...", "kill process 1234", "rm -rf ~/tmp") and "how do i ..."
  lines. A question about PyBot itself ("can you delete files?", "are you able to remove
  things") is None: it names no real file, process or package, so it is a capability question.
- The line must name something with the right shape: a file or folder that exists (or a path
  written with / or ~), a process id or a known program, a package name. "remove the stain from
  my shirt", "kill time at the airport" and "delete my ex from my life" name none, so they stay
  chat.
- Everything stays inside the home folder (symlinks followed). A path outside it, a secrets file
  or folder (local.is_secret), or the home folder itself gets a refusal instead of a command:
  {"command": "", "warning": "", "reason": "..."}.
- The safer form of a command is the one shown where there is one (rm -i, rm -rI, mv -i, cp -i,
  git push --force-with-lease), and the warning names a preview command to run first.
- Paths in the command are written from ~ and quoted with shlex.quote.
"""
import os
import re
import shlex
import shutil
import subprocess

from . import local

# Questions about what PyBot can do: never a suggestion.
_CAPABILITY = re.compile(r"^(?:are\s+you\s+(?:able|allowed|capable|permitted)|do\s+you|does\s+pybot|is\s+pybot|"
                         r"can\s+pybot|could\s+pybot|would\s+you\s+be\s+able|are\s+you\s+going)\b", re.I)
_LEAD = re.compile(r"^(?:(?:hey|hi|ok|okay|so|pybot|bot)[,!\s]+)*"
                   r"(?:(?:can|could|would|will)\s+you\s+(?:please\s+|pls\s+)?|please\s+|pls\s+|plz\s+|now\s+|"
                   r"just\s+|go\s+(?:and\s+)?|i\s+(?:want|need|would\s+like|'d\s+like|wanna)\s+(?:you\s+)?to\s+|"
                   r"help\s+me\s+|how\s+(?:do|can|should|would)\s+i\s+|how\s+to\s+|"
                   r"what(?:'s|\s+is)\s+the\s+(?:command|way)\s+to\s+)?", re.I)
# Trailing "please" and punctuation, but not the "." of "git checkout -- ." or "cd ..".
_TAIL = re.compile(r"(?:[\s,]+(?:please|pls|plz|for\s+me|now|thanks|thank\s+you|thx))*(?:(?<=[^\s.])[?.!]+)?\s*$",
                   re.I)

_SAFE = re.compile(r"^[A-Za-z0-9_@%+=:,./-]+$")
_GLOB = re.compile(r"[*?\[]")
_THE = r"(?:(?:the|my|this|that|our)\s+)?"
_DIR_WORD = r"(?:\s+(?:folder|directory|dir))?"


def _path(name):
    return r"(?P<%s>\"[^\"]+\"|'[^']+'|\S+)" % name


class _Refused(Exception):
    """A line that asks for a change outside the fence: the reason is the reply."""


class _NotOurs(Exception):
    """A line that looked like ours but names nothing with the right shape."""


# --- the answer ---------------------------------------------------------------------------------

def suggest(text):
    """{"command", "warning"} for a line that asks for a change, a refusal, or None."""
    if not local.enabled() or not text or len(text) > 400:
        return None
    line = " ".join(text.split())
    if _CAPABILITY.match(line):
        return None
    body = _TAIL.sub("", _LEAD.sub("", line, count=1))
    if not body:
        return None
    try:
        for reader in (_raw, _trash, _git_words, _delete_kind, _empty, _delete_one, _move, _rename, _copy,
                       _overwrite, _permissions, _kill, _package):
            found = reader(body)
            if found is not None:
                return found
    except _Refused as error:
        return {"command": "", "warning": "", "reason": str(error)}
    except _NotOurs:
        return None
    return None


def reply_for(found):
    """What PyBot says for a suggestion (or a refusal)."""
    if not found.get("command"):
        return found.get("reason") or "I won't do that one."
    return ("I don't run commands that change or delete things, so here is the one to run yourself:\n\n"
            "`%s`\n\n%s" % (found["command"], found["warning"]))


def _said(command, warning):
    return {"command": command, "warning": "⚠️ " + warning}


# --- paths --------------------------------------------------------------------------------------

def _home_is_tilde():
    return local.home() == os.path.realpath(os.path.expanduser("~"))


def shown(path):
    """A path as it goes in a command: from ~ when inside home, quoted when it needs to be."""
    fence = local.home()
    if _home_is_tilde():
        if path == fence:
            return "~"
        if path.startswith(fence + os.sep):
            return "~/" + _quoted_parts(path[len(fence) + 1:])
    return _quoted_parts(path)


def _quoted_parts(path):
    """Each part of a path quoted on its own, so ~/projects/'my notes.md' keeps the ~ working."""
    return "/".join(part if not part or _SAFE.match(part) else shlex.quote(part) for part in path.split("/"))


def _clean(token):
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'`":
        return token[1:-1]
    token = token.rstrip(",;:!?")
    if token.endswith(".") and not token.endswith(".."):
        token = token.rstrip(".") or "."
    return token


def _explicit(token):
    return token.startswith(("~", "/", "./", "../")) or "/" in token


def _fence(path):
    """Refuse a path outside home, the home folder itself, or a secret."""
    if not local.inside_home(path):
        raise _Refused("%s is outside your home folder, so I won't suggest a command for it. Everything "
                       "I touch stays inside %s." % (os.path.realpath(path), local.home()))
    real = os.path.realpath(path)
    if real == local.home():
        raise _Refused("That's your whole home folder. I won't suggest a command that changes or deletes it.")
    if local.is_secret(real):
        raise _Refused("%s holds keys or tokens, so I won't suggest a command that changes it." % shown(real))
    return real


def _locate(token, want="any", base=None, missing_ok=False):
    """The real path a word names (fenced), or None when the word does not name a path.

    The word names a path when it exists (in base, the work folder or home), or when it is
    written as one (with / or ~) and missing_ok is set.
    """
    if not token:
        return None
    raw = _clean(token)
    if not raw or raw in (".", ".."):
        return None
    candidate = os.path.join(base, raw) if base and not raw.startswith(("~", "/")) else raw
    try:
        found = local.resolve(candidate, want)
    except local.Outside as error:
        raise _Refused("%s is outside your home folder, so I won't suggest a command for it. Everything "
                       "I touch stays inside %s." % (error.args[0], local.home()))
    if found is None and local.resolve(candidate, "any") is not None:
        return None  # it exists, but is not the kind wanted (a file named where a folder was)
    if found is None:
        if not (missing_ok and (_explicit(raw) or base)):
            return None
        found = os.path.expanduser(candidate) if candidate.startswith("~") else candidate
        if not os.path.isabs(found):
            found = os.path.join(local.workdir(), found)
    return _fence(found)


def _glob(token):
    """A glob like *.log or ~/tmp/*.log: (folder, pattern), or None."""
    raw = _clean(token)
    if not _GLOB.search(raw):
        return None
    folder, pattern = os.path.split(raw)
    if _GLOB.search(folder):
        return None
    root = _locate(folder, "dir") if folder else local.workdir()
    if root is None:
        raise _NotOurs()
    if root == local.home() and not re.search(r"[A-Za-z0-9]", pattern):
        raise _Refused("That matches everything in your home folder. I won't suggest a command for it.")
    return root, pattern


def _repo_note():
    path = local.workdir()
    while True:
        if os.path.exists(os.path.join(path, ".git")):
            return " Run it inside %s." % shown(path)
        parent = os.path.dirname(path)
        if parent == path or not local.inside_home(parent):
            return ""
        path = parent


def _trash_tip(path):
    if shutil.which("gio"):
        return " To keep a way back, `gio trash %s` moves it to the trash instead." % shown(path)
    return ""


def _join(parts):
    return " ".join(p if _SAFE.match(p) else shlex.quote(p) for p in parts)


# --- typed commands: "rm -rf ~/tmp", "chmod +x script.sh", "git reset --hard" ---------------------

_PATH_COMMANDS = ("rm", "rmdir", "shred", "unlink", "truncate", "mv", "cp", "chmod", "chown", "chgrp")
_PACKAGE_MANAGERS = ("apt", "apt-get", "dnf", "yum", "pacman", "zypper", "snap", "flatpak", "pip", "pip3",
                     "npm", "pnpm", "yarn", "cargo", "gem", "brew")
_DEVICE_COMMANDS = ("dd", "fdisk", "parted", "wipefs", "mkswap", "sfdisk", "gdisk")
_POWER = ("shutdown", "reboot", "poweroff", "halt")
_GIT_READS = ("status", "log", "diff", "show", "blame", "grep", "ls-files", "describe", "shortlog",
              "rev-parse", "help", "version", "--version")


def _raw(body):
    try:
        argv = shlex.split(body)
    except ValueError:
        return None
    if not argv:
        return None
    sudo = argv[0] == "sudo"
    if sudo:
        argv = argv[1:]
        while argv and argv[0].startswith("-"):
            argv = argv[1:]
        if not argv:
            return None
    name = argv[0]
    found = None
    if name in _PATH_COMMANDS:
        found = _raw_paths(argv)
    elif name in ("kill", "killall", "pkill"):
        found = _raw_kill(argv)
    elif name == "git":
        found = _raw_git(argv)
    elif name in _PACKAGE_MANAGERS:
        found = _raw_package(argv)
    elif name in ("systemctl", "service"):
        found = _raw_service(argv)
    elif name in _DEVICE_COMMANDS or name.startswith("mkfs"):
        found = _raw_device(argv)
    elif name in _POWER:
        found = _said(_join(argv), "This turns the machine off or restarts it, and unsaved work in every open "
                                   "program is lost. Save everything first.")
    elif name == "find" and ("-delete" in argv or "-exec" in argv or "-execdir" in argv):
        found = _raw_find(argv)
    elif sudo and shutil.which(name):
        _fence_tokens(argv[1:])
        found = _said(_join(argv), "This runs %s as root." % name)
    if found is None:
        return None
    if sudo:
        if not found["command"].startswith("sudo "):
            found["command"] = "sudo " + found["command"]
        found["warning"] += (" It runs as root, which can change anything on the system, so PyBot never runs "
                             "sudo. Double-check it before you press enter.")
    return found


def _fence_tokens(tokens):
    for token in tokens:
        if token.startswith(("/", "~", "./", "../")):
            _fence(os.path.expanduser(token) if token.startswith("~") else
                   os.path.join(local.workdir(), token))


def _raw_paths(argv):
    name, args = argv[0], argv[1:]
    flags, operands, takes_value = [], [], {"truncate": ("-s", "--size", "-r", "--reference"),
                                            "shred": ("-n", "--iterations", "-s", "--size")}.get(name, ())
    i, ended = 0, False
    while i < len(args):
        arg = args[i]
        if not ended and arg == "--":
            ended = True
        elif not ended and name in ("chmod", "chown", "chgrp") and not operands and re.match(r"^-[RvcfhH]+$", arg):
            flags.append(arg)
        elif not ended and name not in ("chmod",) and arg.startswith("-") and len(arg) > 1:
            flags.append(arg)
            if arg in takes_value and i + 1 < len(args):
                i += 1
                flags.append(args[i])
        elif not ended and name == "chmod" and arg.startswith("--"):
            flags.append(arg)
        else:
            operands.append(arg)
        i += 1
    lead = []
    if name in ("chmod", "chown", "chgrp"):
        if not operands:
            return None
        lead = [operands.pop(0)]
        if name == "chmod" and not re.match(r"^(?:[0-7]{3,4}|[ugoa]*[-+=][rwxXst]+(?:,[ugoa]*[-+=][rwxXst]+)*)$",
                                            lead[0]):
            return None
        if name != "chmod" and not re.match(r"^[a-z_][a-z0-9_.-]*(?::[a-z_][a-z0-9_.-]*)?$|^:[a-z_][a-z0-9_.-]*$",
                                            lead[0]):
            return None
    if not operands:
        return None
    shown_ops, paths = [], []
    for index, operand in enumerate(operands):
        last = index == len(operands) - 1 and name in ("mv", "cp") and len(operands) > 1
        glob = _glob(operand)
        if glob is not None:
            shown_ops.append(_glob_shown(*glob))
            paths.append(glob[0])
            continue
        path = _locate(operand, missing_ok=last or _explicit(_clean(operand)))
        if path is None:
            return None
        shown_ops.append(shown(path))
        paths.append(path)
    command = " ".join([name] + [f if _SAFE.match(f) else shlex.quote(f) for f in flags] +
                       [l if _SAFE.match(l) else shlex.quote(l) for l in lead] + shown_ops)
    target = " ".join(shown_ops)
    recursive = any(re.match(r"^-[a-zA-Z]*[rR]", f) or f == "--recursive" for f in flags)
    force = any(re.match(r"^-[a-zA-Z]*f", f) or f == "--force" for f in flags)
    if name in ("rm", "unlink", "rmdir"):
        what = "deletes %s%s" % (target, " and everything in it" if recursive else "")
        how = (" -f means no prompts at all." if force else "")
        safer = ""
        if recursive and force:
            safer = ", or use `%s` to be asked once before it goes" % " ".join(["rm", "-rI"] + shown_ops)
        return _said(command, "This %s, and it can't be undone.%s Run `ls -la %s` first to see what's there%s."
                     % (what, how, target, safer))
    if name == "shred":
        return _said(command, "This overwrites %s so it can never be read back, not even by recovery tools. "
                              "Run `ls -la %s` first to check it's the right file." % (target, target))
    if name == "truncate":
        return _said(command, "This cuts %s to the new size, and whatever is cut off is lost. Keep a copy first: "
                              "`cp -n %s %s.bak`." % (target, shown_ops[0], shown_ops[0]))
    if name in ("mv", "cp"):
        verb = "moves" if name == "mv" else "copies"
        safer = ""
        if not any(f in ("-i", "-n", "--interactive", "--no-clobber") for f in flags):
            safer = " `%s` asks before overwriting." % " ".join([name, "-i"] + flags + shown_ops)
        return _said(command, "This %s %s to %s, and anything already there with the same name is replaced.%s "
                              "Run `ls -la %s` first to check." % (verb, " ".join(shown_ops[:-1]), shown_ops[-1],
                                                                  safer, shown_ops[-1]))
    if name == "chmod":
        return _said(command, "This changes who can read, write or run %s%s. Run `ls -l %s` first to see the "
                              "permissions it has now." % (target, ", and everything in it" if recursive else "",
                                                           target))
    return _said(command, "This changes who owns %s, which usually needs sudo and can lock you out of your own "
                          "files. Run `ls -l %s` first to see who owns it now." % (target, target))


def _glob_shown(root, pattern):
    folder = shown(root)
    if _SAFE.match(pattern.replace("*", "").replace("?", "")):
        return folder + "/" + pattern
    return folder + "/" + shlex.quote(pattern)


def _raw_kill(argv):
    name, args = argv[0], argv[1:]
    targets = [a for a in args if not a.startswith("-")]
    if not targets:
        return None
    if name == "kill":
        if not all(re.match(r"^(?:\d{1,8}|%\d+)$", t) for t in targets):
            return None
        pids = ",".join(t for t in targets if t.isdigit())
        check = (" Run `ps -p %s -o pid,user,etime,cmd` first to check it's the one you mean." % pids) if pids else ""
        return _said(_join(argv), "This stops process %s, and anything unsaved in it is lost.%s"
                     % (", ".join(targets), check))
    if not all(re.match(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,40}$", t) for t in targets):
        return None
    return _said(_join(argv), "This stops every process named %s, and anything unsaved in them is lost. Run "
                              "`pgrep -a %s` first to see which ones it would stop." % (targets[0], targets[0]))


def _raw_git(argv):
    args = argv[1:]
    sub = next((a for a in args if not a.startswith("-")), "")
    if not sub or sub in _GIT_READS:
        return None
    if sub == "branch" and not any(f in ("-d", "-D", "--delete", "-m", "-M", "--move", "-f") for f in args):
        if len([a for a in args if not a.startswith("-")]) == 1:
            return None
    if sub in ("remote", "stash", "tag", "config") and len(args) == 1:
        return None
    _fence_tokens([a for a in args if a != sub])
    note = _repo_note()
    if sub == "reset" and "--hard" in args:
        return _said(_join(argv), "This throws away every uncommitted change in the repository, and they can't "
                                  "be recovered. Run `git status` first to see what you'd lose, or `git stash` to "
                                  "set the changes aside instead." + note)
    if sub == "push" and any(a in ("--force", "-f") or a.startswith("+") for a in args):
        safer = ["git"] + ["--force-with-lease" if a in ("--force", "-f") else a for a in args]
        return _said(_join(safer), "A force push rewrites the branch on the remote and can wipe out commits "
                                   "other people pushed. This is the safer --force-with-lease form: it stops if the "
                                   "remote has commits you haven't seen. Run `git status` and `git log --oneline -5` "
                                   "first." + note)
    if sub == "clean":
        return _said(_join(argv), "This deletes the untracked files for good (git can't bring them back). Run `%s` "
                                  "first to see what it would remove." % "git clean -nd" + note)
    if sub == "checkout" and "--" in args or sub == "restore":
        return _said(_join(argv), "This throws away your uncommitted changes to those files. Run `git diff` first "
                                  "to see what you'd lose." + note)
    if sub == "branch":
        return _said(_join(argv), "This changes your branches; a branch deleted with -D can lose commits that are "
                                  "on no other branch. Run `git branch -v` first, and prefer -d, which refuses to "
                                  "delete unmerged work." + note)
    if sub == "push":
        return _said(_join(argv), "This sends your commits to the remote, where other people see them. Run "
                                  "`git status` and `git log --oneline -5` first." + note)
    return _said(_join(argv), "This changes your git repository. Run `git status` first to see where things "
                              "stand." + note)


def _raw_package(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    flags = [a for a in argv[1:] if a.startswith("-")]
    changes = ("install", "uninstall", "remove", "purge", "autoremove", "upgrade", "update", "add", "erase",
               "reinstall", "dist-upgrade", "full-upgrade", "refresh")
    if not (args and args[0] in changes) and not any(re.match(r"^-[SRU]", f) for f in flags):
        return None
    removing = any(a in ("uninstall", "remove", "purge", "autoremove", "erase") for a in args[:1]) or any(
        f.startswith("-R") for f in flags)
    if removing:
        what = "This uninstalls software, and other packages that depend on it may go with it."
    else:
        what = "This installs or upgrades software, which changes your system."
    system = argv[0] not in ("pip", "pip3", "npm", "pnpm", "yarn", "cargo", "gem")
    return _said(_join(argv), what + (" It needs sudo." if system and argv[0] not in ("brew", "flatpak") else "") +
                 " Check the name and what it would change before you run it.")


def _raw_service(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    verbs = ("start", "stop", "restart", "reload", "enable", "disable", "mask", "unmask", "kill", "daemon-reload",
             "poweroff", "reboot", "isolate")
    verb = args[1] if argv[0] == "service" and len(args) > 1 else (args[0] if args else "")
    if verb not in verbs:
        return None
    unit = args[0] if argv[0] == "service" else (args[1] if len(args) > 1 else "")
    check = " Run `systemctl status %s` first." % unit if unit and _SAFE.match(unit) else ""
    return _said(_join(argv), "This %ss a system service, which can take things down for everyone on the "
                              "machine, and it needs sudo.%s" % (verb, check))


def _raw_device(argv):
    for arg in argv[1:]:
        value = arg.split("=", 1)[1] if re.match(r"^(?:if|of)=", arg) else arg
        if value.startswith(("/", "~", ".")):
            _fence(os.path.expanduser(value) if value.startswith("~") else os.path.join(local.workdir(), value))
    return _said(_join(argv), "This writes straight onto a disk or file and can wipe it completely, with no "
                              "undo. Check the target twice (`lsblk` lists the disks) before you run it.")


def _raw_find(argv):
    roots = []
    for arg in argv[1:]:
        if arg.startswith("-") or arg in ("(", "!", ")"):
            break
        roots.append(arg)
    shown_roots = []
    for root in roots or ["."]:
        path = _locate(root, "dir") if root != "." else local.workdir()
        if path is None:
            return None
        shown_roots.append(shown(path))
    rest = argv[1 + len(roots):]
    command = " ".join(["find"] + shown_roots + [_join([a]) for a in rest])
    cut = next((i for i, a in enumerate(rest) if a in ("-delete", "-exec", "-execdir")), len(rest))
    preview = " ".join(["find"] + shown_roots + [_join([a]) for a in rest[:cut]])
    return _said(command, "This deletes or changes every file it finds, and it can't be undone. Run `%s` first "
                          "to see what it would touch." % preview)


# --- plain words --------------------------------------------------------------------------------

_DELETE = r"(?:delete|remove|erase|rm|trash|nuke|destroy|get\s+rid\s+of|wipe)"
_TRASH = re.compile(r"^(?:empty|clear|clean(?:\s+out)?|delete\s+everything\s+in)\s+(?:the\s+|my\s+)?"
                    r"(?:trash(?:\s+(?:can|bin|folder))?|recycle\s+bin|rubbish\s+bin|wastebasket|bin)$", re.I)


def _trash(body):
    if not _TRASH.match(body):
        return None
    folder = os.path.join(local.home(), ".local", "share", "Trash")
    if shutil.which("gio"):
        command = "gio trash --empty"
    else:
        command = "find %s -mindepth 2 -delete" % shown(folder)
    return _said(command, "This deletes everything in the trash for good; it can't be undone. Run `ls -A %s` "
                          "first to see what's there." % shown(os.path.join(folder, "files")))


_FORCE_PUSH = re.compile(r"^force[\s-]?push(?:\s+(?:it|this|my\s+branch|the\s+branch))?$", re.I)
_UNDO_COMMIT = re.compile(r"^(?:undo|revert|take\s+back)\s+(?:my\s+|the\s+)?(?:last|latest|previous)\s+commit$",
                          re.I)
_DISCARD = re.compile(r"^(?:discard|throw\s+away|drop|undo)\s+(?:all\s+)?(?:of\s+)?(?:my\s+|the\s+)?(?:local\s+|"
                      r"uncommitted\s+)?(?:git\s+)?changes(?:\s+in\s+git)?$", re.I)
_CLEAN_UNTRACKED = re.compile(r"^(?:delete|remove|clean(?:\s+up)?|get\s+rid\s+of)\s+(?:all\s+)?(?:the\s+|my\s+)?"
                              r"untracked\s+files$", re.I)
_DELETE_BRANCH = re.compile(r"^" + _DELETE + r"\s+(?:the\s+)?(?:git\s+)?branch\s+(?P<branch>[A-Za-z0-9._/-]{1,80})$",
                            re.I)


def _git_words(body):
    note = _repo_note()
    if _FORCE_PUSH.match(body):
        return _said("git push --force-with-lease", "A force push rewrites the branch on the remote and can wipe "
                     "out commits other people pushed; --force-with-lease stops if the remote has commits you "
                     "haven't seen. Run `git status` and `git log --oneline -5` first." + note)
    if _UNDO_COMMIT.match(body):
        return _said("git reset --soft HEAD~1", "This takes the last commit back off the branch and keeps its "
                     "changes staged. If you already pushed it, use `git revert HEAD` instead. Run "
                     "`git log --oneline -3` first." + note)
    if _DISCARD.match(body):
        return _said("git restore .", "This throws away every uncommitted change to tracked files, and they can't "
                     "be recovered. Run `git diff --stat` first to see what you'd lose, or `git stash` to set "
                     "them aside instead." + note)
    if _CLEAN_UNTRACKED.match(body):
        return _said("git clean -fd", "This deletes the untracked files and folders for good. Run `git clean -nd` "
                     "first to see what it would remove." + note)
    match = _DELETE_BRANCH.match(body)
    if match:
        branch = match.group("branch")
        return _said("git branch -d %s" % _join([branch]), "This deletes the branch %s. -d refuses if it holds "
                     "commits that aren't merged; -D would delete them anyway. Run `git branch -v` first." % branch
                     + note)
    return None


_KINDS_EXTRA = {"tmp": ["*.tmp"], "bak": ["*.bak"], "backup": ["*.bak"], "swap": ["*.swp"], "swp": ["*.swp"],
                "pyc": ["*.pyc"], "o": ["*.o"], "class": ["*.class"], "orig": ["*.orig"], "temp": ["*.tmp"],
                "zip": ["*.zip"], "mp4": ["*.mp4"], "jpg": ["*.jpg", "*.jpeg"], "png": ["*.png"]}
_DELETE_KIND = re.compile(
    r"^" + _DELETE + r"\s+(?:all\s+|every\s+|any\s+)?(?:of\s+)?(?:the\s+|my\s+)?"
    r"(?:(?P<ext>\.[A-Za-z0-9]{1,10})\s+files?|(?P<kind>[A-Za-z0-9]{1,12})\s+files?|(?P<star>\*\.[A-Za-z0-9]{1,10})(?:\s+files?)?)"
    r"(?:\s+(?:in|from|inside|under|within)\s+" + _THE + _path("dir") + _DIR_WORD + r")?$", re.I)


def _delete_kind(body):
    match = _DELETE_KIND.match(body)
    if not match:
        return None
    ext = match.group("ext") or match.group("star")
    if ext:
        patterns = ["*" + ext.lstrip("*")]
    else:
        word = match.group("kind").lower()
        patterns = local.KINDS.get(word) or _KINDS_EXTRA.get(word) or _KINDS_EXTRA.get(word.rstrip("s"))
        if not patterns:
            return None
    root = _locate(match.group("dir"), "dir", missing_ok=True) if match.group("dir") else local.workdir()
    if root is None:
        return None
    if not os.path.isdir(root):
        raise _Refused("There's no folder %s, so there's nothing to delete." % shown(root))
    if len(patterns) == 1:
        tests = "-name %s" % shlex.quote(patterns[0])
    else:
        tests = "\\( %s \\)" % " -o ".join("-iname %s" % shlex.quote(p) for p in patterns)
    preview = "find %s -type f %s" % (shown(root), tests)
    return _said(preview + " -delete", "This deletes files and can't be undone. Run `%s` first to see what it "
                                       "would remove." % preview)


_EMPTY = re.compile(r"^(?:empty(?:\s+out)?|clear(?:\s+out)?|clean\s+out|wipe(?:\s+out)?|"
                    r"(?:delete|remove|erase)\s+(?:all\s+(?:of\s+)?)?(?:the\s+)?(?P<what>everything|files|contents|"
                    r"stuff)\s+(?:in|from|inside|of))\s+" + _THE + _path("target") + _DIR_WORD + r"$", re.I)


def _empty(body):
    match = _EMPTY.match(body)
    if not match:
        return None
    target = _locate(match.group("target"), missing_ok=True)
    if target is None:
        return None
    if not os.path.lexists(target):
        raise _Refused("There's nothing at %s, so there's nothing to empty." % shown(target))
    if os.path.isfile(target):
        if match.group("what"):
            return None
        return _truncate(target)
    if not os.path.isdir(target):
        return None
    only_files = (match.group("what") or "").lower() == "files"
    preview = "find %s -mindepth 1%s" % (shown(target), " -type f" if only_files else "")
    return _said(preview + " -delete", "This deletes everything inside %s (the folder itself stays), and it "
                 "can't be undone. Run `%s` first to see what it would remove." % (shown(target), preview))


def _truncate(path):
    return _said("truncate -s 0 %s" % shown(path), "This empties %s, and what's in it now is lost. Keep a copy "
                 "first: `cp -n %s %s`." % (shown(path), shown(path), shown(path + ".bak")))


_DELETE_ONE = re.compile(r"^" + _DELETE + r"\s+" + _THE + r"(?:(?:file|folder|directory|dir)\s+(?:called\s+|named\s+)?)?"
                         + _path("target") + r"(?:\s+(?:file|folder|directory|dir))?"
                         r"(?:\s+(?:in|from|inside|under|within)\s+" + _THE + _path("base") + _DIR_WORD + r")?$",
                         re.I)


def _delete_one(body):
    match = _DELETE_ONE.match(body)
    if not match:
        return None
    base = None
    if match.group("base"):
        base = _locate(match.group("base"), "dir")
        if base is None:
            return None
    target = _locate(match.group("target"), base=base, missing_ok=True)
    if target is None:
        glob = _glob(match.group("target"))
        if glob is None:
            return None
        root, pattern = glob
        preview = "find %s -maxdepth 1 -name %s" % (shown(base or root), shlex.quote(pattern))
        return _said(preview + " -delete", "This deletes files and can't be undone. Run `%s` first to see what it "
                     "would remove." % preview)
    if not os.path.lexists(target):
        raise _Refused("There's nothing at %s, so there's nothing to delete." % shown(target))
    if os.path.isdir(target):
        return _said("rm -rI %s" % shown(target), "This deletes the folder %s and everything in it, and it can't be "
                     "undone. Run `ls -la %s` first to see what's in it; -I asks once before it starts.%s"
                     % (shown(target), shown(target), _trash_tip(target)))
    return _said("rm -i %s" % shown(target), "This deletes %s, and it can't be undone. Run `ls -la %s` first to "
                 "check it's the right one.%s" % (shown(target), shown(target), _trash_tip(target)))


_MOVE = re.compile(r"^(?:move|mv)\s+" + _THE + r"(?:(?:file|folder)\s+)?" + _path("src") +
                   r"(?:\s+(?:file|folder|directory))?\s+(?:to|into|in|under|over\s+to)\s+" + _THE + _path("dst") +
                   _DIR_WORD + r"$", re.I)
_RENAME = re.compile(r"^rename\s+" + _THE + r"(?:(?:file|folder)\s+)?" + _path("src") +
                     r"(?:\s+(?:file|folder|directory))?\s+(?:to|as|into)\s+" + _path("dst") + r"$", re.I)
_COPY = re.compile(r"^(?:copy|cp)\s+" + _THE + r"(?:(?:file|folder)\s+)?" + _path("src") +
                   r"(?:\s+(?:file|folder|directory))?\s+(?:to|into|over\s+to)\s+" + _THE + _path("dst") +
                   _DIR_WORD + r"$", re.I)


def _source(token):
    src = _locate(token, missing_ok=True)
    if src is None:
        return None
    if not os.path.lexists(src):
        raise _Refused("There's nothing at %s to move or copy." % shown(src))
    return src


def _destination(token, src, same_folder=False):
    raw = _clean(token)
    if same_folder and "/" not in raw and not raw.startswith("~"):
        if not raw or raw in (".", ".."):
            raise _NotOurs()
        return _fence(os.path.join(os.path.dirname(src), raw)), False
    folder = _locate(token, "dir")
    if folder is not None:
        return folder, True
    dst = _locate(token, missing_ok=True, base=local.workdir())
    if dst is None:
        raise _NotOurs()
    if not os.path.isdir(os.path.dirname(dst)):
        raise _Refused("There's no folder %s to put it in." % shown(os.path.dirname(dst)))
    return dst, False


def _move(body):
    match = _MOVE.match(body)
    if not match:
        return None
    src = _source(match.group("src"))
    if src is None:
        return None
    dst, into = _destination(match.group("dst"), src)
    return _moved("mv", src, dst, into)


def _rename(body):
    match = _RENAME.match(body)
    if not match:
        return None
    src = _source(match.group("src"))
    if src is None:
        return None
    dst, into = _destination(match.group("dst"), src, same_folder=True)
    return _moved("mv", src, dst, into)


def _copy(body):
    match = _COPY.match(body)
    if not match:
        return None
    src = _source(match.group("src"))
    if src is None:
        return None
    dst, into = _destination(match.group("dst"), src)
    return _moved("cp", src, dst, into)


def _moved(name, src, dst, into):
    if dst == src:
        raise _Refused("That's the same place it already is.")
    flags = "-i" if name == "mv" else ("-ri" if os.path.isdir(src) else "-i")
    target = shown(dst) + ("/" if into else "")
    landing = os.path.join(dst, os.path.basename(src)) if into else dst
    verb = "moves" if name == "mv" else "copies"
    replaced = ("There's already a %s, and it would be replaced; -i asks first." % shown(landing)
                if os.path.lexists(landing) else "-i asks before it replaces anything that's already there.")
    return _said("%s %s %s %s" % (name, flags, shown(src), target), "This %s %s to %s. %s Run `ls -la %s` first to "
                 "check." % (verb, shown(src), target, replaced, shown(dst if into else os.path.dirname(dst))))


_OVERWRITE = re.compile(r"^(?:overwrite|replace)\s+" + _THE + r"(?:file\s+)?" + _path("target") +
                        r"(?:\s+file)?(?:\s+with\s+" + _THE + r"(?P<with>.+))?$", re.I)


def _overwrite(body):
    match = _OVERWRITE.match(body)
    if not match:
        return None
    target = _locate(match.group("target"), "file", missing_ok=True)
    if target is None:
        return None
    if not os.path.exists(target):
        raise _Refused("There's no file at %s to overwrite." % shown(target))
    backup = "cp -n %s %s" % (shown(target), shown(target + ".bak"))
    source = match.group("with")
    if not source:
        return _truncate(target)
    src = _locate(source.strip(), "file")
    if src is not None:
        return _said("cp -i %s %s" % (shown(src), shown(target)), "This replaces everything in %s with %s, and the "
                     "old contents are lost. Keep a copy first: `%s`." % (shown(target), shown(src), backup))
    words = _clean(source.strip())
    return _said("printf '%%s\\n' %s > %s" % (shlex.quote(words), shown(target)), "This replaces everything in %s, "
                 "and the old contents are lost. Keep a copy first: `%s`." % (shown(target), backup))


_EXECUTABLE = re.compile(r"^make\s+" + _THE + _path("target") + r"\s+(?P<how>executable|runnable|read[\s-]?only|"
                         r"private)$", re.I)
_PERMISSIONS = re.compile(r"^(?:change|set)\s+(?:the\s+)?(?:permissions?|perms|mode)\s+(?:of|on|for)\s+" + _THE +
                          _path("target") + r"\s+to\s+(?P<mode>[0-7]{3,4}|[ugoa]*[-+=][rwxX]+)$", re.I)
_OWNER = re.compile(r"^(?:change|set)\s+(?:the\s+)?owner(?:ship)?\s+(?:of|on|for)\s+" + _THE + _path("target") +
                    r"\s+to\s+(?P<owner>[a-z_][a-z0-9_.-]{0,31})$", re.I)


def _permissions(body):
    match = _EXECUTABLE.match(body)
    mode = None
    if match:
        how = match.group("how").lower()
        mode = {"executable": "+x", "runnable": "+x", "private": "go-rwx"}.get(how, "a-w")
    else:
        match = _PERMISSIONS.match(body)
        if match:
            mode = match.group("mode")
    if match:
        target = _locate(match.group("target"))
        if target is None:
            return None
        return _said("chmod %s %s" % (mode, shown(target)), "This changes who can read, write or run %s. Run "
                     "`ls -l %s` first to see the permissions it has now." % (shown(target), shown(target)))
    match = _OWNER.match(body)
    if match:
        target = _locate(match.group("target"))
        if target is None:
            return None
        return _said("sudo chown %s %s" % (match.group("owner"), shown(target)), "This hands %s to another user, "
                     "needs sudo, and can lock you out of your own file. Run `ls -l %s` first to see who owns it "
                     "now." % (shown(target), shown(target)))
    return None


_KILL = re.compile(r"^(?P<verb>kill(?:\s+-9)?|killall|pkill|terminate|force[\s-]?(?:quit|close|kill)|end|stop|"
                   r"shut\s+down|close)\s+(?:the\s+|that\s+|this\s+|my\s+)?(?:(?P<pre>process(?:\s+id)?|pid|"
                   r"program|app|application)\s+)?(?P<target>[A-Za-z0-9][A-Za-z0-9_.+-]{0,40})"
                   r"(?:\s+(?P<post>process(?:es)?|program|app|application|server))?$", re.I)
_KNOWN_PROGRAMS = frozenset(
    "firefox chrome chromium google-chrome brave code vscode node nodejs npm python python3 java nginx apache2 "
    "httpd mysql mysqld mariadb postgres postgresql redis redis-server mongod mongodb docker dockerd containerd "
    "slack discord spotify zoom teams steam vlc gimp obs thunderbird electron gunicorn uvicorn celery flask "
    "django ruby rails php php-fpm caddy ollama jupyter vim nvim emacs tmux ssh sshd rsync wget curl ffmpeg "
    "deno bun cargo rustc go dotnet kubectl minikube qemu virtualbox libreoffice evince nautilus gnome-shell "
    "telegram signal whatsapp skype dropbox onedrive syncthing transmission qbittorrent".split())
_NOT_PROGRAMS = frozenset(
    "time it this that him her them me myself yourself himself herself themselves us everyone everybody "
    "someone somebody anyone anybody you all the a an process processes program programs app apps pid "
    "mood vibe buzz lights light music noise pain joy bill boredom conversation silence power engine "
    "game one two everything something anything nothing job task tasks thing things".split())


def _kill(body):
    match = _KILL.match(body)
    if not match:
        return None
    verb = match.group("verb").lower()
    target = match.group("target")
    marked = bool(match.group("pre") or match.group("post"))
    force = "9" in verb or "force" in verb
    if target.isdigit():
        if not (marked or verb.startswith("kill")):
            return None
        command = "kill %s%s" % ("-9 " if force else "", target)
        return _said(command, "This stops process %s, and anything unsaved in it is lost. Run "
                     "`ps -p %s -o pid,user,etime,cmd` first to check it's the one you mean.%s"
                     % (target, target, "" if force else " If it won't stop, `kill -9 %s` forces it." % target))
    name = target.lower()
    if name in _NOT_PROGRAMS:
        return None
    gentle = verb.startswith(("kill", "pkill", "killall", "force"))
    known = name in _KNOWN_PROGRAMS and verb not in ("stop", "end")
    if not (marked or known or (gentle and _running(name))):
        return None
    command = "pkill %s-x %s" % ("-9 " if force else "", name)
    return _said(command, "This stops every process named %s, and anything unsaved in them is lost. Run "
                 "`pgrep -a -x %s` first to see which ones it would stop." % (name, name))


def _running(name):
    if not shutil.which("pgrep"):
        return False
    try:
        return subprocess.run(["pgrep", "-x", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=3).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


_PACKAGE = re.compile(r"^(?P<verb>uninstall|un-install|purge|remove|delete|install|reinstall)\s+(?:the\s+)?"
                      r"(?:(?P<pre>package|app|program|software|tool)\s+)?(?P<pkg>[A-Za-z0-9][A-Za-z0-9.+_-]{0,60})"
                      r"(?:\s+(?P<post>package|app|program|software|tool))?"
                      r"(?:\s+(?:with|using|via|from|through)\s+(?P<mgr>pip3?|npm|pnpm|yarn|apt(?:-get)?|dnf|yum|"
                      r"pacman|zypper|snap|flatpak|brew|cargo|gem))?$", re.I)
_NOT_PACKAGES = frozenset(
    "it this that them everything anything something stuff things apps programs packages software windows "
    "updates update me him her yourself myself a an the doors door shelves shelf carpet flooring curtains "
    "blinds lights solar tiles cabinets gutters fence fear doubt confidence hope habits files folders".split())
_MANAGERS = (("apt-get", "apt"), ("dnf", "dnf"), ("pacman", "pacman"), ("zypper", "zypper"))


def _package(body):
    match = _PACKAGE.match(body)
    if not match:
        return None
    verb = match.group("verb").lower()
    pkg = match.group("pkg")
    marked = bool(match.group("pre") or match.group("post") or match.group("mgr"))
    if pkg.lower() in _NOT_PACKAGES:
        return None
    if verb in ("remove", "delete") and not marked:
        return None
    removing = verb in ("uninstall", "un-install", "purge", "remove", "delete")
    mgr = (match.group("mgr") or "").lower()
    if not mgr:
        mgr = next((name for program, name in _MANAGERS if shutil.which(program)), "apt")
    if mgr == "apt-get":
        mgr = "apt"
    command, check = _package_command(mgr, pkg, removing, verb == "purge")
    if removing:
        what = "This uninstalls %s, and other packages that depend on it may go with it." % pkg
    else:
        what = "This installs %s, which changes your system." % pkg
    if command.startswith("sudo "):
        what += " It needs sudo, so it's yours to run."
    return _said(command, what + " Run `%s` first to see exactly what it would do." % check)


def _package_command(mgr, pkg, removing, purge):
    if mgr == "apt":
        verb = "purge" if purge else ("remove" if removing else "install")
        return "sudo apt %s %s" % (verb, pkg), "apt-get -s %s %s" % (verb, pkg)
    if mgr in ("dnf", "yum"):
        verb = "remove" if removing else "install"
        return "sudo %s %s %s" % (mgr, verb, pkg), "%s %s --assumeno %s" % (mgr, verb, pkg)
    if mgr == "pacman":
        return ("sudo pacman %s %s" % ("-R" if removing else "-S", pkg),
                "pacman %s %s" % ("-Rp" if removing else "-Si", pkg))
    if mgr == "zypper":
        verb = "remove" if removing else "install"
        return "sudo zypper %s %s" % (verb, pkg), "zypper %s --dry-run %s" % (verb, pkg)
    if mgr == "snap":
        return "sudo snap %s %s" % ("remove" if removing else "install", pkg), "snap info %s" % pkg
    if mgr == "flatpak":
        return "flatpak %s %s" % ("uninstall" if removing else "install", pkg), "flatpak search %s" % pkg
    if mgr in ("pip", "pip3"):
        return "%s %s %s" % (mgr, "uninstall" if removing else "install", pkg), "%s show %s" % (mgr, pkg)
    if mgr in ("npm", "pnpm", "yarn"):
        verb = {"npm": ("uninstall", "install"), "pnpm": ("remove", "add"), "yarn": ("remove", "add")}[mgr]
        return "%s %s %s" % (mgr, verb[0] if removing else verb[1], pkg), "%s ls %s" % (mgr, pkg)
    if mgr == "brew":
        return "brew %s %s" % ("uninstall" if removing else "install", pkg), "brew info %s" % pkg
    if mgr == "cargo":
        return "cargo %s %s" % ("uninstall" if removing else "install", pkg), "cargo install --list"
    return "gem %s %s" % ("uninstall" if removing else "install", pkg), "gem list %s" % pkg
