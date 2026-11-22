"""Quick answers worked out in Python: the time here and in other cities, data sizes, Unix
timestamps, base64, hex and binary, URL encoding, pretty-printed JSON, a UUID or a password.

Not part of the swarm's original bot. Plain arithmetic ("15% of 240", "2^10 + 3*7") and units
like km to miles are left to the bot's own maths domain, which already answers them; this file
only takes what it got wrong or could not do. Every reader is a pattern and a little Python; no
program is run and nothing is written. `answer(text)` returns the reply, or None.
"""
import base64
import binascii
import datetime
import json
import re
import secrets
import string
import time
import urllib.parse
import uuid

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # Python < 3.9: only local time
    ZoneInfo = None

    class ZoneInfoNotFoundError(Exception):
        pass

_LEAD = (r"^\s*(?:(?:hey|hi|ok|okay|so|pybot|bot)[,!\s]+)*(?:(?:can|could|would|will) you\s+(?:please\s+)?|"
         r"please\s+|pls\s+|just\s+)?")
_END = r"\s*[?.!]*\s*$"

CITIES = {
    "singapore": "Asia/Singapore", "tokyo": "Asia/Tokyo", "osaka": "Asia/Tokyo", "seoul": "Asia/Seoul",
    "beijing": "Asia/Shanghai", "shanghai": "Asia/Shanghai", "hong kong": "Asia/Hong_Kong",
    "taipei": "Asia/Taipei", "manila": "Asia/Manila", "bangkok": "Asia/Bangkok", "jakarta": "Asia/Jakarta",
    "kuala lumpur": "Asia/Kuala_Lumpur", "ho chi minh city": "Asia/Ho_Chi_Minh", "hanoi": "Asia/Bangkok",
    "delhi": "Asia/Kolkata", "new delhi": "Asia/Kolkata", "noida": "Asia/Kolkata", "mumbai": "Asia/Kolkata",
    "bangalore": "Asia/Kolkata", "bengaluru": "Asia/Kolkata", "chennai": "Asia/Kolkata",
    "kolkata": "Asia/Kolkata", "hyderabad": "Asia/Kolkata", "india": "Asia/Kolkata",
    "karachi": "Asia/Karachi", "dhaka": "Asia/Dhaka", "kathmandu": "Asia/Kathmandu", "colombo": "Asia/Colombo",
    "dubai": "Asia/Dubai", "abu dhabi": "Asia/Dubai", "riyadh": "Asia/Riyadh", "doha": "Asia/Qatar",
    "tehran": "Asia/Tehran", "istanbul": "Europe/Istanbul", "tel aviv": "Asia/Jerusalem",
    "jerusalem": "Asia/Jerusalem", "cairo": "Africa/Cairo", "nairobi": "Africa/Nairobi",
    "lagos": "Africa/Lagos", "johannesburg": "Africa/Johannesburg", "cape town": "Africa/Johannesburg",
    "london": "Europe/London", "uk": "Europe/London", "dublin": "Europe/Dublin", "lisbon": "Europe/Lisbon",
    "paris": "Europe/Paris", "berlin": "Europe/Berlin", "munich": "Europe/Berlin", "amsterdam": "Europe/Amsterdam",
    "brussels": "Europe/Brussels", "zurich": "Europe/Zurich", "geneva": "Europe/Zurich", "madrid": "Europe/Madrid",
    "barcelona": "Europe/Madrid", "rome": "Europe/Rome", "milan": "Europe/Rome", "vienna": "Europe/Vienna",
    "prague": "Europe/Prague", "warsaw": "Europe/Warsaw", "stockholm": "Europe/Stockholm", "oslo": "Europe/Oslo",
    "copenhagen": "Europe/Copenhagen", "helsinki": "Europe/Helsinki", "athens": "Europe/Athens",
    "kyiv": "Europe/Kyiv", "moscow": "Europe/Moscow", "new york": "America/New_York", "nyc": "America/New_York",
    "boston": "America/New_York", "washington": "America/New_York", "miami": "America/New_York",
    "toronto": "America/Toronto", "montreal": "America/Toronto", "chicago": "America/Chicago",
    "dallas": "America/Chicago", "houston": "America/Chicago", "denver": "America/Denver",
    "phoenix": "America/Phoenix", "los angeles": "America/Los_Angeles", "la": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles", "sf": "America/Los_Angeles", "seattle": "America/Los_Angeles",
    "vancouver": "America/Vancouver", "mexico city": "America/Mexico_City", "sao paulo": "America/Sao_Paulo",
    "buenos aires": "America/Argentina/Buenos_Aires", "lima": "America/Lima", "bogota": "America/Bogota",
    "santiago": "America/Santiago", "honolulu": "Pacific/Honolulu", "sydney": "Australia/Sydney",
    "melbourne": "Australia/Melbourne", "brisbane": "Australia/Brisbane", "perth": "Australia/Perth",
    "adelaide": "Australia/Adelaide", "auckland": "Pacific/Auckland", "utc": "UTC", "gmt": "UTC",
    "pst": "America/Los_Angeles", "pacific time": "America/Los_Angeles", "est": "America/New_York",
    "eastern time": "America/New_York", "cst": "America/Chicago", "ist": "Asia/Kolkata", "sgt": "Asia/Singapore",
    "cet": "Europe/Paris", "jst": "Asia/Tokyo", "aest": "Australia/Sydney",
}


def _now():
    return datetime.datetime.now().astimezone()


def _clock(moment):
    return moment.strftime("%H:%M (%I:%M %p)").replace("(0", "(")


def _offset(moment):
    off = moment.utcoffset() or datetime.timedelta()
    minutes = int(off.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    return "UTC%s%d%s" % (sign, abs(minutes) // 60, ":%02d" % (abs(minutes) % 60) if minutes % 60 else "")


# --- time --------------------------------------------------------------------------------------

TIME_HERE = re.compile(_LEAD + r"(?:what(?:'s|\s+is)\s+the\s+time|what\s+time\s+is\s+it|(?:tell\s+me\s+)?the\s+time|"
                       r"current\s+time|time\s+now)(?:\s+(?:now|here|right\s+now))?" + _END, re.I)
DATE_HERE = re.compile(_LEAD + r"(?:what(?:'s|\s+is)\s+(?:the\s+)?(?:date|day)(?:\s+today)?|what\s+day\s+is\s+(?:it|today)|"
                       r"today'?s\s+date)" + _END, re.I)
TIME_IN = re.compile(_LEAD + r"(?:what(?:'s|\s+is)\s+the\s+time|what\s+time\s+is\s+it|time)(?:\s+now)?\s+in\s+"
                     r"(?P<place>[a-z][a-z .'/_-]{1,40}?)(?:\s+(?:now|right\s+now))?" + _END, re.I)


def _zone(place):
    place = place.strip().lower().rstrip(".?")
    name = CITIES.get(place)
    if not name and "/" in place and ZoneInfo is not None:
        name = "/".join(part.capitalize() if part.islower() else part for part in place.split("/"))
    if not name or ZoneInfo is None:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _time(text):
    if TIME_HERE.match(text):
        now = _now()
        return "It's %s here, %s (%s)." % (_clock(now), now.strftime("%A %d %B"), _offset(now))
    if DATE_HERE.match(text):
        now = _now()
        return "Today is %s." % now.strftime("%A, %d %B %Y")
    found = TIME_IN.match(text)
    if found:
        zone = _zone(found.group("place"))
        if zone is None:
            return None
        here = _now()
        there = here.astimezone(zone)
        diff = ((there.utcoffset() or datetime.timedelta()) - (here.utcoffset() or datetime.timedelta()))
        hours = diff.total_seconds() / 3600
        if hours == 0:
            relation = "the same time as here"
        else:
            amount = ("%g" % abs(hours)).rstrip("0").rstrip(".") if hours % 1 else "%d" % abs(hours)
            relation = "%s hour%s %s you" % (amount, "" if abs(hours) == 1 else "s",
                                            "ahead of" if hours > 0 else "behind")
        day = "" if there.date() == here.date() else (" (%s)" % ("tomorrow" if there.date() > here.date()
                                                                    else "yesterday"))
        return "It's %s in %s%s, %s: %s (%s)." % (_clock(there), found.group("place").strip().title(), day,
                                                  there.strftime("%A"), relation, _offset(there))
    return None


# --- data sizes ----------------------------------------------------------------------------------

_UNITS = {"b": (1, "B"), "byte": (1, "B"), "bytes": (1, "B"),
          "kb": (10**3, "KB"), "kilobyte": (10**3, "KB"), "kilobytes": (10**3, "KB"),
          "mb": (10**6, "MB"), "megabyte": (10**6, "MB"), "megabytes": (10**6, "MB"),
          "gb": (10**9, "GB"), "gigabyte": (10**9, "GB"), "gigabytes": (10**9, "GB"),
          "tb": (10**12, "TB"), "terabyte": (10**12, "TB"), "terabytes": (10**12, "TB"),
          "pb": (10**15, "PB"), "kib": (2**10, "KiB"), "mib": (2**20, "MiB"), "gib": (2**30, "GiB"),
          "tib": (2**40, "TiB")}
_UNIT = r"(?:kib|mib|gib|tib|kb|mb|gb|tb|pb|b|bytes?|kilobytes?|megabytes?|gigabytes?|terabytes?)"
DATA = re.compile(_LEAD + r"(?:convert\s+|what(?:'s|\s+is)\s+)?(?P<n>\d+(?:[.,]\d+)?)\s*(?P<a>" + _UNIT + r")\s+"
                  r"(?:to|in|into|as|=)\s+(?P<b>" + _UNIT + r")" + _END + r"|" + _LEAD +
                  r"how\s+many\s+(?P<b2>" + _UNIT + r")\s+(?:are\s+)?(?:in|is)\s+(?:a\s+)?(?P<n2>\d+(?:[.,]\d+)?)?\s*"
                  r"(?P<a2>" + _UNIT + r")" + _END, re.I)


def _number(value):
    text = (("%.6f" if abs(value) < 1 else "%.2f") % value).rstrip("0").rstrip(".")
    whole, _, frac = text.partition(".")
    return "{:,}".format(int(whole)) + ("." + frac if frac else "")


def _data(text):
    found = DATA.match(text)
    if not found:
        return None
    n = float((found.group("n") or found.group("n2") or "1").replace(",", "."))
    a = _UNITS[(found.group("a") or found.group("a2")).lower()]
    b = _UNITS[(found.group("b") or found.group("b2")).lower()]
    result = n * a[0] / b[0]
    said = "%s %s = %s %s." % (_number(n), a[1], _number(result), b[1])
    decimal = {"KB": "KiB", "MB": "MiB", "GB": "GiB", "TB": "TiB"}
    if a[1] in decimal and b[1] in decimal:
        ba = _UNITS[decimal[a[1]].lower()][0]
        bb = _UNITS[decimal[b[1]].lower()][0]
        said += " (In binary units, as an OS often counts: %s %s = %s %s.)" % (
            _number(n), decimal[a[1]], _number(n * ba / bb), decimal[b[1]])
    return said


# --- timestamps -----------------------------------------------------------------------------------

STAMP_TO_DATE = re.compile(_LEAD + r"(?:convert\s+)?(?:(?:the\s+)?(?:unix\s+|epoch\s+)?(?:timestamp|epoch|time)\s+)?"
                           r"(?P<ts>\d{9,13})(?:\s+(?:to|as|in|into)\s+(?:a\s+)?(?:date|time|datetime|human|readable|"
                           r"normal\s+time))" + _END + r"|" + _LEAD + r"(?:what\s+(?:date|time)\s+is|(?:unix\s+|epoch\s+)?"
                           r"timestamp|epoch)\s+(?P<ts2>\d{9,13})" + _END, re.I)
STAMP_NOW = re.compile(_LEAD + r"(?:what(?:'s|\s+is)\s+)?(?:the\s+)?(?:current\s+)?(?:unix\s+(?:time(?:stamp)?)|epoch(?:\s+time)?|"
                       r"timestamp)(?:\s+(?:now|right\s+now))?" + _END, re.I)
DATE_TO_STAMP = re.compile(_LEAD + r"(?:(?:unix\s+)?timestamp|epoch)\s+(?:for|of)\s+(?P<date>\d{4}-\d{2}-\d{2}"
                           r"(?:[ t]\d{1,2}:\d{2}(?::\d{2})?)?)" + _END, re.I)


def _stamps(text):
    found = STAMP_TO_DATE.match(text)
    if found:
        raw = found.group("ts") or found.group("ts2")
        value = int(raw)
        millis = len(raw) == 13
        seconds = value / 1000 if millis else value
        local = datetime.datetime.fromtimestamp(seconds).astimezone()
        utc = datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc)
        return "%s%s is %s here (%s), or %s UTC." % (
            raw, " (milliseconds)" if millis else "", local.strftime("%a %d %b %Y, %H:%M:%S"), _offset(local),
            utc.strftime("%Y-%m-%d %H:%M:%S"))
    if STAMP_NOW.match(text):
        return "The Unix timestamp now is %d (%s)." % (int(time.time()), _now().strftime("%d %b %Y %H:%M:%S %Z"))
    found = DATE_TO_STAMP.match(text)
    if found:
        raw = found.group("date").replace("t", " ").replace("T", " ")
        for shape in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                moment = datetime.datetime.strptime(raw, shape).astimezone()
                return "%s (your time, %s) is Unix timestamp %d." % (raw, _offset(moment), int(moment.timestamp()))
            except ValueError:
                continue
    return None


# --- encodings --------------------------------------------------------------------------------------

B64 = re.compile(_LEAD + r"(?:(?:base64|b64)\s+(?P<op>decode|encode)|(?P<op2>decode|encode)\s+(?:this\s+)?(?:from\s+|to\s+|in\s+|as\s+)?"
                 r"(?:base64|b64))(?:\s+(?:this|the\s+string))?\s*:?\s+(?P<value>.+?)" + _END + r"|" + _LEAD +
                 r"(?P<op3>decode|encode)\s+(?P<value3>.+?)\s+(?:from|to|in|as)\s+base64" + _END, re.I | re.S)
URL = re.compile(_LEAD + r"(?:url[\s-]?(?P<op>encode|decode)|(?P<op2>encode|decode)\s+(?:this\s+)?(?:for\s+a\s+)?url)\s*:?\s+"
                 r"(?P<value>.+?)" + _END, re.I | re.S)
NUMBER_BASE = re.compile(_LEAD + r"(?:convert\s+|what(?:'s|\s+is)\s+)?(?P<value>0x[0-9a-f]+|0b[01]+|0o[0-7]+|\d+)"
                         r"(?:\s+from\s+(?P<frombase>hex|binary|octal|decimal))?\s+(?:to|in|into|as)\s+"
                         r"(?P<to>hex(?:adecimal)?|binary|octal|decimal|dec)" + _END, re.I)
JSON_PRETTY = re.compile(_LEAD + r"(?:pretty[\s-]?print|format|prettify|tidy\s+up|is\s+this\s+valid|validate|check)\s+"
                         r"(?:this\s+|the\s+)?(?:json)?\s*:?\s*(?P<value>[\[{].*[\]}])" + _END, re.I | re.S)
UUID = re.compile(_LEAD + r"(?:generate|make|give\s+me|create|new)\s+(?:me\s+)?(?:a\s+)?(?:new\s+)?(?:random\s+)?uuid(?:4)?" + _END, re.I)
PASSWORD = re.compile(_LEAD + r"(?:generate|make|give\s+me|create)\s+(?:me\s+)?(?:a\s+)?(?:strong\s+|random\s+|secure\s+)*"
                      r"password(?:\s+(?:of\s+)?(?P<n>\d{1,3})(?:\s+(?:characters|chars|long))?)?" + _END, re.I)


def _encodings(text):
    found = B64.match(text)
    if found:
        op = (found.group("op") or found.group("op2") or found.group("op3")).lower()
        value = (found.group("value") or found.group("value3")).strip().strip("`\"'")
        if op == "encode":
            return "Base64 of \"%s\":\n  %s" % (value, base64.b64encode(value.encode("utf-8")).decode("ascii"))
        try:
            raw = base64.b64decode(value + "=" * (-len(value) % 4), validate=False)
        except (binascii.Error, ValueError):
            return "That isn't valid base64."
        try:
            return "Decoded:\n  %s" % raw.decode("utf-8")
        except UnicodeDecodeError:
            return "Decoded to %d bytes that aren't text; in hex:\n  %s" % (len(raw), raw.hex()[:400])
    found = URL.match(text)
    if found:
        op = (found.group("op") or found.group("op2")).lower()
        value = found.group("value").strip().strip("`\"'")
        if op == "encode":
            return "URL-encoded:\n  %s" % urllib.parse.quote(value, safe="")
        return "URL-decoded:\n  %s" % urllib.parse.unquote(value)
    found = NUMBER_BASE.match(text)
    if found:
        raw = found.group("value").lower()
        base = {"hex": 16, "binary": 2, "octal": 8, "decimal": 10}.get((found.group("frombase") or "").lower())
        try:
            value = int(raw, 0) if base is None else int(raw.replace("0x", "").replace("0b", "").replace("0o", ""), base)
        except ValueError:
            return None
        to = found.group("to").lower()
        shown = {"hex": hex(value), "hexadecimal": hex(value), "binary": bin(value), "octal": oct(value),
                 "decimal": str(value), "dec": str(value)}[to]
        return "%s = %s" % (raw, shown)
    found = JSON_PRETTY.match(text)
    if found:
        try:
            data = json.loads(found.group("value"))
        except ValueError as error:
            return "That isn't valid JSON: %s." % error
        return "Valid JSON:\n%s" % json.dumps(data, indent=2, ensure_ascii=False)[:4000]
    if UUID.match(text):
        return "A new UUID (version 4, random):\n  %s" % uuid.uuid4()
    found = PASSWORD.match(text)
    if found:
        n = min(max(int(found.group("n") or 20), 8), 128)
        alphabet = string.ascii_letters + string.digits + "-_.!@#%^*+="
        while True:
            word = "".join(secrets.choice(alphabet) for _ in range(n))
            if (any(c.islower() for c in word) and any(c.isupper() for c in word) and any(c.isdigit() for c in word)):
                break
        return "A random %d-character password (from Python's secrets module, never stored):\n  %s" % (n, word)
    return None


def answer(text):
    """The reply to a quick ask, or None when the line is not one."""
    if not text or len(text) > 5000:
        return None
    from .local import tidy_line  # noqa: PLC0415 - "whats the date pls" reads as "what's the date"
    plain = text.strip()
    for reader in (_time, _stamps, _data, _encodings):
        said = reader(plain) or (reader(tidy_line(plain)) if reader is _time else None)
        if said:
            return said
    return None
