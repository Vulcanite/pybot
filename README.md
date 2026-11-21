<p align="center"><img src="assets/banner.png" alt="PyBot: no weights, no training, just rules" width="100%"></p>

<div align="center">
  <a href="https://huggingface.co/spaces/HuggingFaceSwarms/PyBot" target="_blank">
    <img alt="Hugging Face Space: PyBot demo" src="https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Demo-ffc107?color=ffc107&logoColor=white" />
  </a>
</div>

# PyBot: can Python be a chatbot?

LLMs drive today’s chatbots and agents, but chatbots long predate them. Sixty years ago, [ELIZA](https://en.wikipedia.org/wiki/ELIZA) held conversations by matching patterns in what the user typed and answering with predefined templates. It could seem insightful, but its repertoire was narrow, and expanding it meant writing more rules by hand. How far could a rule-based chatbot go if a swarm of agents did that work instead?

We challenged a swarm of over 1,000 agents to build a chatbot entirely in Python: no weights, no training, just if-else branches, regex patterns and lookup tables. The agents wrote and evaluated over 5,000 versions, and the chatbot’s win rate on [SmolTalkBench](https://huggingface.co/datasets/HuggingFaceSwarms/SmolTalkBench), where an LLM judge compares each reply with a reference answer, climbed from 0% to 26%. That puts it on par with SmolLM-360M-Instruct, which just a few years ago was state of the art for models under 1B parameters.

![PyBot's win rate over the evaluated commits on a log scale: every commit as a dot and the best so far as a line, with three SmolLM baselines as dashed lines, and its lines of Python code in grey on the right axis](assets/progress.png)

The result is PyBot: around 640k lines of code that can answer everyday questions, backed by 550k lines of tests the agents wrote themselves.

## Try it out

Try PyBot in your terminal below, or in the browser on [Hugging Face](https://huggingface.co/spaces/HuggingFaceSwarms/PyBot), where each reply shows which of PyBot’s modules produced it.

PyBot needs Python 3.8 or newer and nothing else: no packages to install and no model to download.

```sh
git clone https://github.com/huggingface/pybot
cd pybot
python -m pybot
```

That starts a chat in your terminal:

```text
    ____        ____        __
   / __ \__  __/ __ )____  / /_
  / /_/ / / / / __  / __ \/ __/
 / ____/ /_/ / /_/ / /_/ / /_
/_/    \__, /_____/\____/\__/
      /____/

A chatbot written in plain Python. No weights, no training, just rules.
Type a message and press Enter. /reset starts a new conversation, /exit quits.

user: hi, i'm Sam
pybot: Nice to meet you, Sam. What can I help with?

user: my kettle is full of limescale, how do i get rid of it?
pybot: Half fill the kettle with equal parts water and white vinegar, or a sachet of citric acid, boil it and leave it half an hour, then tip it out and boil fresh water twice before you use it again. In a hard-water area do it every couple of months: the scale forms because hard water leaves calcium behind as it boils, and a thick layer makes the kettle slow and puts a scum on the tea.

user: how long does that take
pybot: Half an hour.

user: what's my name?
pybot: You're Sam.
```

Type `/reset` to clear the screen and start a new conversation, and `/exit` to quit. PyBot takes a few seconds to start, because Python has about 640,000 lines of code to load, and about a second to reply.

To ask one question and exit, or to pipe messages in and get one reply per line:

```sh
python -m pybot -p "Why do onions make you cry?"
echo "how long should i boil an egg" | python -m pybot
```

| Option | What it does |
|---|---|
| `-p TEXT`, `--prompt TEXT` | reply to this one message and exit |
| `-i`, `--interactive` | with `-p`, keep chatting after the first reply |
| `-s N`, `--seed N` | fix PyBot's choice of wording, to get the same replies again |
| `-v`, `--verbose` | after each reply, show the module that produced it and the time it took |

For a `pybot` command you can run from anywhere, install the clone with `pip install .`.

## What is in this repository

| Path | What it holds |
|---|---|
| `bot/` | PyBot itself: 528 Python files and about 640,000 lines, exactly as the swarm wrote them |
| `pybot.py` | the command line shown above. It contains no chatbot logic |
| `tests/` | tests for the command line: `python -m unittest discover -s tests` |
| `assets/` | the banner and the chart |

Every turn, each module in `bot/modules/` may propose a reply, and an arbiter (`bot/modules/arbiter.py`) picks the one you get. The modules build on four shared parts:

| Part | Where | Lines |
|---|---|---:|
| Understanding engine: what you typed and meant, with typos, chat-speak, the topic and what "it" refers to | `bot/understanding/` | 25,000 |
| Memory store: what you and PyBot have said so far | `bot/memory/` | 109,000 |
| Knowledge base: facts about the world, kept as data | `bot/knowledge/` | 317,000 |
| Response composer: how a reply is phrased, and what to say when nothing fits | `bot/compose/` | 104,000 |

The modules themselves are another 81,000 lines.

## Web tools (added on the `web-tools` branch)

The swarm's bot answers only from what it holds. This branch lets it reach the web, and the
"tool calls" are rules too: a module's pattern decides that a line wants the web, and the reply
is picked from what came back by word overlap. No model is involved at any step.

| Module | Fires on | Does |
|---|---|---|
| `bot/modules/web_search.py` | "search for ...", "look up ...", "google ...", "look that up" | Exa search, says the best sentences and the source |
| `bot/tools/fallback_search.py` (run by `pybot.py` after the turn) | a question about the world whose chosen reply was a shrug ("I'd rather not guess", "I can't see the news from here") | the same search, in place of the shrug; it never runs when the bot had a real answer |
| `bot/modules/web_inspect.py` | "is github.com down", "check the headers on example.com", "what does example.com say", a bare link, "open the first one" | status, timing, TLS certificate and security headers, or the page's opening text through [agent-browser](https://github.com/vercel-labs/agent-browser) |
| `bot/modules/local_tools.py` | "find all python files in src", "search for TODO in ~/projects", "show me README.md", "what's in ~/Downloads", "git status", "how much disk space do i have", "what's using port 8080", "is ollama running" | turns the line into one fixed, read-only command (find, grep, head, ls, du, wc, git, df, free, ps, ss, pgrep), runs it without a shell, and says what it found |
| `bot/modules/local_tools.py` (more) | "how do i use rsync", "history of pybot.py", "who last changed line 40 of x.py", "show me the diff for README.md", "errors in app.log", "what's in package.json", "sha256 of x.iso", "when was x last modified", "what's the ip of github.com", "is port 443 open on example.com" | `man`, `git log/blame/diff`, `grep` for error lines, a manifest reader, `sha256sum`, `stat`, a DNS lookup, a TCP connect |
| `bot/modules/quick_tools.py` | "what time is it", "time in Tokyo", "convert 5 GB to MB", "1700000000 to a date", "base64 decode ...", "255 to hex", "url encode ...", "pretty print {...}", "generate a uuid / password" | worked out in Python; plain arithmetic and km-to-miles stay with the bot's own maths |
| `bot/modules/note_tools.py` | "make a note that ...", "show my notes", "remind me to ... in 20 minutes / at 5pm / tomorrow at 9", "my reminders", "save that to notes.md", "save example.com as markdown" | notes and reminders in `~/.pybot/notes.json`; the chat prints reminders when they fall due |

Everything local stays inside the home folder: a path that resolves outside it (`/etc`, `/mnt/c`, a
symlink that points out) is refused, commands run with a working directory inside home, and
`~/.ssh`, `~/.gnupg`, `~/.aws` and other secrets folders are never listed, searched or shown.

The local commands only read: nothing deletes, moves, writes or runs code, and the person's words
only fill in arguments (a name, a pattern, a folder that must exist). Secrets files (`.env`,
SSH keys, `*.pem`, ...) are never shown or searched, and key or password values in output are
masked. `--no-local` turns them off. The notes tools are the only ones that write: only inside
home, never over an existing file unless the line says "overwrite"; `--read-only` turns writing off.

The shared code is in `bot/tools/`. Setup:

```sh
echo 'EXA_API_KEY=your-key' > .env      # .env is gitignored; pybot.py reads it
npm install -g agent-browser             # optional: reads pages that need JavaScript
python -m pybot -v                       # -v shows which module answered
python -m pybot --offline                # the swarm's bot, with no web at all
```

Without `EXA_API_KEY` the search modules never fire. Site checks only fetch public addresses:
localhost, private ranges and cloud metadata addresses are refused, every redirect is checked
again, and the connection is pinned to the address that was checked. The fallback search never
sends a line about the person themselves to the search service. Tests: `python -m unittest discover -s tests`.

Memory across chats (`bot/tools/profile.py`, `bot/modules/profile_tools.py`): a few things about
you are kept in `~/.pybot/profile.json` (folder 700, file 600), scored by rules. Always kept:
"remember that ...", "don't forget ...", and standing rules ("always use metric", "call me Sam",
"i prefer short answers"). Kept: stable facts (name, job, where you live, the OS and tools you
use, languages, family and pet names, allergies); a new value replaces the old one. Not kept:
passing states ("i'm tired today") and anything that looks like a password, key, token or card
number. A new chat starts with the kept facts, so "what's my name?" works there. "what do you
remember about me", "forget that i use arch" and "forget everything about me" always work (a bare
"forget everything" asks first); `--read-only` keeps nothing new.

## License

Apache License 2.0. See [LICENSE](LICENSE).
