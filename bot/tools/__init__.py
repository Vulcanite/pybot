"""Tools: the bot's way out to the live web. Not part of the swarm's original bot.

Everything else in `bot/` answers from what it holds. These helpers let a few modules reach past
that, while the bot itself stays rules all the way down: no model chooses when to call a tool,
and no model writes the reply. A module's rule decides that a line wants the web, a tool fetches
it, and `digest` picks the sentences to say back by plain word overlap.

- `net.py`: a guarded HTTP fetch (http and https only, public addresses only, every redirect
  hop checked again, the connection pinned to the address that was checked).
- `exa.py`: web search through Exa's /search endpoint. Needs EXA_API_KEY; without it the search
  modules never fire and the bot behaves exactly as the swarm left it.
- `browser.py`: a rendered page through Vercel's `agent-browser` CLI, for pages that only have
  their text after JavaScript runs. Optional: without the CLI, `net.py` and an HTML reader are
  used instead.
- `digest.py`: the extractive reading - clean a snippet, split it into sentences, keep the ones
  that share the most words with the question.

Standard library only, like the rest of the bot. Every function here fails closed: it raises a
`ToolError`, and the modules that call them turn that into an honest line or no candidate.
"""


import os


def enabled():
    """False when PYBOT_WEB=0 (`python -m pybot --offline`): no tool reaches the web at all."""
    return os.environ.get("PYBOT_WEB", "1") != "0"


class ToolError(Exception):
    """A tool could not do what was asked (no key, blocked address, timeout, bad reply)."""


class Refused(ToolError):
    """The guard would not fetch this URL (a private address, a scheme that is not the web)."""
