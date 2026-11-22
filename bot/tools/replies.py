"""The words the web modules say, built by rule from what the tools found."""
import re

from . import Refused, ToolError, browser, digest, exa, net

# The page a site shows a robot instead of itself.
_BLOCKED = re.compile(r"access denied|forbidden|just a moment|attention required|are you a robot|"
                      r"captcha|verify you are human|request blocked|not acceptable", re.I)

SECURITY_HEADERS = (
    ("strict-transport-security", "HSTS"),
    ("content-security-policy", "CSP"),
    ("x-content-type-options", "X-Content-Type-Options"),
    ("referrer-policy", "Referrer-Policy"),
    ("permissions-policy", "Permissions-Policy"),
)


def _date(published):
    """'2026-10-21' -> 'Oct 2026'; '' when there is none."""
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    try:
        year, month = published[:4], int(published[5:7])
        return "%s %s" % (months[month - 1], year)
    except (ValueError, IndexError):
        return ""


def _source(result):
    when = _date(result.get("published", ""))
    site = digest.site_of(result["url"])
    return "%s%s: %s" % (site, ", " + when if when else "", result["url"])


def _best(query, results):
    """(result, sentences) for the page that answers best, or None.

    The page whose best sentences share the most with the question, the search's own order
    breaking a tie (and costing a little, so a lower result has to be clearly better).
    """
    asked = digest.stems(query)
    best, best_score = None, None
    for rank, result in enumerate(results[:3]):
        said = digest.best_sentences(query, result.get("highlights") or [])
        if not said:
            continue
        score = len(asked & digest.stems(" ".join(said))) - 0.75 * rank
        if best_score is None or score > best_score:
            best, best_score = (result, said), score
    return best


def in_the_order_said(query, results):
    """The results with the one the reply quotes first, so "the first one" is the one it quoted."""
    best = _best(query, results)
    if not best:
        return list(results)
    return [best[0]] + [r for r in results if r is not best[0]]


def search_reply(query, results, explicit=True):
    """The reply to a search: the best sentences and where they came from, or the top links."""
    if not results:
        return "I searched for \"%s\" and nothing useful came back." % query
    best = _best(query, results)
    others = [r for r in results if not best or r is not best[0]][:2]
    if best:
        result, said = best
        lead = "Here's what I found: " if explicit else "From a quick search: "
        reply = "%s%s (%s)" % (lead, " ".join(said), _source(result))
        if others and explicit:
            reply += " Also worth a look: " + "; ".join(
                "%s (%s)" % (r["title"] or digest.site_of(r["url"]), r["url"]) for r in others) + "."
        return reply
    listed = "; ".join("%d) %s (%s)" % (i + 1, r["title"] or digest.site_of(r["url"]), r["url"])
                       for i, r in enumerate(results[:3]))
    return "Top results for \"%s\": %s." % (query, listed)


def search(query, explicit=True):
    """(reply, urls) for a query, or ToolError when the search could not be made."""
    results = exa.search(query)
    return search_reply(query, results, explicit), [r["url"] for r in in_the_order_said(query, results)]


# --- a site -----------------------------------------------------------------------------------

def _status_line(host, response):
    ms = int(response.seconds * 1000)
    over = "HTTPS" if response.url.lower().startswith("https://") else "plain HTTP"
    code = "%d %s" % (response.status, response.reason)
    if response.status >= 500:
        return "%s answers, but with %s, so something is wrong on their side (%d ms)." % (host, code, ms)
    if response.status in (401, 403):
        return "%s is up and answering %s: it is there, it just won't show this page to me (%d ms)." % (
            host, code, ms)
    if response.status >= 400:
        return "%s is up but that page answers %s (%d ms over %s)." % (host, code, ms, over)
    return "%s is up: %s in %d ms over %s." % (host, code, ms, over)


def _cert_line(response):
    cert = response.cert
    if not cert:
        return ""
    expires = cert.get("notAfter", "")
    issuer = ""
    for part in cert.get("issuer", ()):
        for key, value in part:
            if key == "organizationName":
                issuer = value
    if not expires:
        return ""
    return " The certificate is valid until %s%s." % (
        " ".join(expires.split()[:2] + expires.split()[3:4]), " (issued by %s)" % issuer if issuer else "")


def _headers_line(response):
    headers = response.headers
    have, missing = [], []
    for name, label in SECURITY_HEADERS:
        (have if name in headers else missing).append(label)
    frames = "x-frame-options" in headers or "frame-ancestors" in headers.get(
        "content-security-policy", "")
    (have if frames else missing).append("clickjacking protection")
    parts = []
    if have:
        parts.append("Security headers present: %s." % ", ".join(have))
    if missing:
        parts.append("Missing: %s." % ", ".join(missing))
    leaks = [headers[h] for h in ("server", "x-powered-by") if headers.get(h)]
    if leaks:
        parts.append("It announces its software as %s." % " / ".join(leaks))
    return " " + " ".join(parts)


def inspect(site, mode):
    """The reply to a site ask: is it up, how is it set up, or what does it say."""
    url = net.normalise_url(site)
    host = digest.site_of(url)
    if mode == "read":
        return read(url)
    try:
        response = net.fetch(url)
    except Refused as error:
        return "I won't check that one: %s." % error
    except ToolError as error:
        return "%s looks down from here, or I can't reach it: %s." % (host, error)
    reply = _status_line(host, response)
    if response.chain:
        reply += " It redirected from %s." % response.chain[0][0]
    if mode == "audit":
        title = digest.read_html(response.text())[0] if "html" in response.headers.get(
            "content-type", "") else ""
        if title:
            reply += " The page title is \"%s\"." % title[:120]
        reply += _cert_line(response)
        reply += _headers_line(response)
    return reply


def read(url):
    """What a page says: its title and opening prose, through the browser when there is one."""
    host = digest.site_of(url)
    title = text = ""
    how = ""
    if browser.available():
        try:
            page = browser.render(url)
            title, text, url = page["title"], page["text"], page["url"] or url
            how = "browser"
        except Refused as error:
            return "I won't open that one: %s." % error
        except ToolError:
            how = ""
    if not how:
        try:
            response = net.fetch(url)
        except Refused as error:
            return "I won't open that one: %s." % error
        except ToolError as error:
            return "I couldn't open %s: %s." % (host, error)
        if response.status >= 400:
            return "%s answered %d %s, so there's nothing to read." % (host, response.status,
                                                                        response.reason)
        title, description, text = digest.read_html(response.text())
        if description and len(description) > 40:
            text = description + "\n" + text
    if _BLOCKED.search(title or "") or (len(text) < 300 and _BLOCKED.search(text)):
        return ("%s turned the automated browser away (it showed \"%s\"), so I can't read it from "
                "here. The link is %s." % (host, (title or "access denied")[:60], url))
    lead = digest.lead_text(text)
    if not lead:
        if title:
            return "%s is titled \"%s\", but there's no readable text on the page." % (host, title)
        return "%s loaded, but there's no readable text on the page." % host
    return "%s%s: %s" % (host, " (\"%s\")" % title[:100] if title else "", lead)
