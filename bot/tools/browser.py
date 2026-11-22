"""A rendered page through Vercel's agent-browser CLI (https://github.com/vercel-labs/agent-browser).

Some pages hold no text until their JavaScript runs, and a plain fetch of those reads an empty
shell. For those the bot asks a real headless browser: one `agent-browser batch` call opens the
page, reads the title, URL and body text, and the session is closed afterwards.

Only these read-only commands are ever sent - never `eval`, `click`, `fill` or anything else
that acts on a page - and the URL is passed as one argument, never through a shell. The URL is
checked by `net.check_url` and `net.resolve_public` first. The browser then makes its own
requests for the page's scripts and images, and follows redirects itself, which the address
check cannot see; a hosted bot should also limit the machine's outbound traffic.

AGENT_BROWSER_BIN names the binary when it is not on PATH; PYBOT_BROWSER=0 turns it off.
"""
import json
import os
import shutil
import subprocess
import uuid
from urllib.parse import quote

from . import ToolError
from . import net

TIMEOUT = 40
# Every URL character except space, quotes and backslash stays as it is; "%" is kept so an
# already-encoded URL is not encoded twice.
_URL_SAFE = ":/?#[]@!$&()*+,;=%~-._"


def binary():
    if os.environ.get("PYBOT_BROWSER") == "0" or not net.enabled():
        return None
    return os.environ.get("AGENT_BROWSER_BIN") or shutil.which("agent-browser")


def available():
    return bool(binary())


def render(url):
    """{"url", "title", "text"} of a page as a browser shows it; or ToolError."""
    exe = binary()
    if not exe:
        raise ToolError("no browser is installed")
    # `batch` splits each command string into words itself, so the URL is percent-encoded until
    # it holds no space, quote or backslash: it can only ever be the one argument to `open`.
    url = quote(net.normalise_url(url), safe=_URL_SAFE)
    _scheme, host, port, _path = net.check_url(url)
    net.resolve_public(host, port)
    session = "pybot-" + uuid.uuid4().hex[:10]
    command = [exe, "--session", session, "--json", "batch", "--bail",
               "open " + url, "get title", "get url", "get text body"]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise ToolError("the page did not finish loading in %d seconds" % TIMEOUT) from None
    except OSError:
        raise ToolError("the browser could not be started") from None
    finally:
        try:
            subprocess.run([exe, "--session", session, "close"], capture_output=True,
                           timeout=15, stdin=subprocess.DEVNULL)
        except (subprocess.TimeoutExpired, OSError):
            pass
    try:
        steps = json.loads(done.stdout)
    except ValueError:
        raise ToolError("the browser gave no readable answer") from None
    found = {"url": url, "title": "", "text": ""}
    for step in steps if isinstance(steps, list) else []:
        if not isinstance(step, dict):
            continue
        if not step.get("success"):
            raise ToolError("the browser could not open the page (%s)"
                            % str(step.get("error") or "unknown error")[:120])
        result = step.get("result") or {}
        found["title"] = result.get("title", found["title"]) or found["title"]
        found["url"] = result.get("url", found["url"]) or found["url"]
        if "text" in result:
            found["text"] = str(result["text"])
    return found
