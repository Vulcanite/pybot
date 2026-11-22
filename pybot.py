#!/usr/bin/env python3
"""Chat with PyBot in a terminal.

    python -m pybot                          interactive chat
    python -m pybot -p "your message"        one reply, then exit
    echo "your message" | python -m pybot    one reply per input line

PyBot itself is the `bot` package next to this file, exactly as the swarm of agents wrote it.
This file only adds the command line. It holds no chatbot logic of its own.
"""
import argparse
import os
import random
import sys
import threading
import time

__version__ = "0.1.0"

# The commit that `bot/` was copied from.
SOURCE_COMMIT = "24cbc0439e07fd015c0747ab3be6e782a42b5c5b"

# The first lines of the interactive chat: the name in FIGlet's "slant" lettering, then one line
# saying what PyBot is.
LOGO = r"""
    ____        ____        __
   / __ \__  __/ __ )____  / /_
  / /_/ / / / / __  / __ \/ __/
 / ____/ /_/ / /_/ / /_/ / /_
/_/    \__, /_____/\____/\__/
      /____/
""".strip("\n")
TAGLINE = "A chatbot written in plain Python. No weights, no training, just rules."

# What the interactive chat puts in front of each turn.
USER_PREFIX = "user: "
BOT_PREFIX = "pybot: "

HINT = "Type a message and press Enter. /reset starts a new conversation, /exit quits."

HELP = """Commands:
  /reset   clear the screen and start again (PyBot forgets what was said)
  /help    show this help
  /exit    quit (Ctrl+D works too)"""


def load_env(path=None):
    """Read KEY=VALUE lines from the .env next to this file into the environment.

    That is where a local EXA_API_KEY lives (.env is in .gitignore). A variable that is already
    set wins over the file, so `EXA_API_KEY=... python -m pybot` still works.
    """
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        os.environ.setdefault(key, value.strip().strip("\"'"))


def load_bot():
    """Import the bot's runtime. The first start compiles every module, so it takes longer."""
    try:
        from bot import runtime
    except ModuleNotFoundError as error:
        if error.name != "bot":
            raise
        # Run from another directory: the bot package sits next to this file.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from bot import runtime
    return runtime


def answer(runtime, text, memory):
    """One turn: (reply, module, seconds). A turn never raises.

    Like bot/__main__.py the reply is never empty, and the spaces inside each line are tidied.
    Its line breaks are kept - the local tools print file lists and command output - and pipe()
    flattens them, so piped input still gets exactly one reply line per input line.
    """
    start = time.perf_counter()
    try:
        result = runtime.turn(text, memory)
        result = _search_instead_of_shrugging(text, memory, result)
        said = str(result["reply"]).strip("\n")
        if "\n" in said:
            # Command output: kept as printed (indents, blank lines in a file), ends trimmed.
            reply = "\n".join(line.rstrip() for line in said.splitlines()) if said.strip() else "Hello!"
        else:
            reply = " ".join(said.split()) or "Hello!"
        module = result.get("module")
    except Exception:  # noqa: BLE001 - keep the bot's interface: always one reply
        reply, module = "Hello!", None
    return reply, module, time.perf_counter() - start


def _search_instead_of_shrugging(text, memory, result):
    """After the turn: a shrug from the bot becomes a web search (bot/tools/fallback_search.py)."""
    try:
        from bot.tools import fallback_search
    except Exception:  # noqa: BLE001 - no tools, the bot as it was
        return result
    return fallback_search.improve(text, memory, result)


def details(module, seconds):
    return "[module: %s | %.0f ms]" % (module or "none", seconds * 1000)


def one_shot(runtime, args):
    """-p without -i: print the reply to one message and exit."""
    reply, module, seconds = answer(runtime, args.prompt, {})
    print(reply, flush=True)
    if args.verbose:
        print(details(module, seconds), file=sys.stderr)


def pipe(runtime, args):
    """Input that is not a terminal: one reply per line, like `python -m bot`."""
    memory = {}
    for line in sys.stdin:
        reply, module, seconds = answer(runtime, line.rstrip("\r\n"), memory)
        print(" ".join(reply.split()), flush=True)
        if args.verbose:
            print(details(module, seconds), file=sys.stderr, flush=True)


def opening():
    """What the chat shows when it starts, and again after /reset."""
    print(LOGO + "\n")
    print(TAGLINE)
    print(HINT + "\n")


def clear_screen():
    """Wipe the terminal, including what has scrolled off the top."""
    if os.name == "nt":
        os.system("cls")
    else:
        # Cursor to the top, erase the screen, erase the scrollback.
        sys.stdout.write("\033[H\033[2J\033[3J")
        sys.stdout.flush()


def watch_reminders(every=10):
    """Print reminders as they fall due while the chat is open (and missed ones at the start)."""
    try:
        from bot.tools import notes
    except Exception:  # noqa: BLE001 - no tools, no reminders
        return None

    def loop():
        while True:
            try:
                due = notes.due_now()
            except Exception:  # noqa: BLE001 - a bad notes file must not end the chat
                due = []
            for item in due:
                print("\n%s\n%s" % (notes.announce(item), USER_PREFIX), end="", flush=True)
            time.sleep(every)

    thread = threading.Thread(target=loop, name="pybot-reminders", daemon=True)
    thread.start()
    return thread


def chat(runtime, args):
    """An interactive conversation in the terminal.

    Every turn is labelled with who is speaking: `user: ` in front of what you type and
    `pybot: ` in front of the reply. /reset clears the conversation: PyBot forgets it, and in a
    terminal the screen is wiped back to the opening.
    """
    try:
        import readline  # noqa: F401 - line editing and history for input()
    except ImportError:
        pass
    opening()
    watch_reminders()
    memory = {}
    first = args.prompt
    while True:
        if first is not None:
            text, first = first, None
            print(USER_PREFIX + text)
        else:
            try:
                text = input(USER_PREFIX)
            except (EOFError, KeyboardInterrupt):
                print()
                break
        command = text.strip().lower()
        if command in ("/exit", "/quit", "/bye"):
            break
        if command == "/reset":
            memory = {}
            if args.seed is not None:
                random.seed(args.seed)
            if sys.stdout.isatty():
                clear_screen()
                opening()
            else:
                print("New conversation.\n")
            continue
        if command == "/help":
            print(HELP + "\n")
            continue
        if not command:
            continue
        reply, module, seconds = answer(runtime, text, memory)
        # Later lines of a multi-line reply sit under the first, past the "pybot: " label.
        print(BOT_PREFIX + reply.replace("\n", "\n" + " " * len(BOT_PREFIX)))
        if args.verbose:
            print(details(module, seconds))
        print()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="pybot",
        description="Chat with PyBot, a chatbot written in plain Python: no model, no weights.",
        epilog="With no options, PyBot starts an interactive chat. "
               "When input is piped in, it prints one reply per input line.")
    parser.add_argument("-p", "--prompt", metavar="TEXT",
                        help="reply to this one message and exit")
    parser.add_argument("-i", "--interactive", action="store_true",
                        help="with -p: keep chatting after the first reply")
    parser.add_argument("-s", "--seed", type=int, metavar="N",
                        help="seed for PyBot's choice of wording, to get the same replies again")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="after each reply, show the module that produced it and the time it took")
    parser.add_argument("--version", action="version",
                        version="pybot %s (bot at commit %s)" % (__version__, SOURCE_COMMIT[:12]))
    parser.add_argument("--offline", action="store_true",
                        help="no web search or site checks, as the swarm's bot was")
    parser.add_argument("--no-local", action="store_true",
                        help="no local commands (finding files, git, disk space, ...)")
    parser.add_argument("--read-only", action="store_true",
                        help="no notes, reminders or saved files: nothing is written")
    args = parser.parse_args(argv)

    load_env()
    if args.offline:
        os.environ["PYBOT_WEB"] = "0"
    if args.no_local:
        os.environ["PYBOT_LOCAL"] = "0"
    if args.read_only:
        os.environ["PYBOT_WRITE"] = "0"
    if args.seed is not None:
        random.seed(args.seed)
    interactive = (args.prompt is None and sys.stdin.isatty()) or (args.prompt is not None and args.interactive)
    if interactive:
        print("Loading PyBot...", end="", file=sys.stderr, flush=True)
    runtime = load_bot()
    if interactive:
        print("\r" + " " * 16 + "\r", end="", file=sys.stderr, flush=True)
        chat(runtime, args)
    elif args.prompt is not None:
        one_shot(runtime, args)
    else:
        pipe(runtime, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
