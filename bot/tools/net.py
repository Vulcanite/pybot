"""A guarded HTTP fetch for the web modules, standard library only.

The bot fetches URLs that people type, so a URL is untrusted input. Before any request:

- only http and https, no user:password@ in the URL;
- the host is resolved, and every address it resolves to must be a public one (no loopback,
  private ranges, link-local - which includes the 169.254.169.254 cloud metadata address -,
  CGNAT, multicast or reserved space, and no IPv4 hidden inside IPv6);
- the connection is made to the address that was checked, not re-resolved, so a DNS answer
  that changes between the check and the connect (rebinding) cannot move the request inside;
- redirects are followed by hand, at most MAX_REDIRECTS, and each hop is checked the same way;
- the body is read up to MAX_BYTES and the whole fetch has a timeout.

PYBOT_ALLOW_PRIVATE_FETCH=1 lifts the address rule, for trying the bot against a local server.
"""
import http.client
import ipaddress
import os
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit

from . import Refused, ToolError, enabled

MAX_REDIRECTS = 5
MAX_BYTES = 1_000_000
TIMEOUT = 8.0
USER_AGENT = "PyBot/0.1 (rule-based chatbot; +https://github.com/huggingface/pybot)"


def _private_allowed():
    return os.environ.get("PYBOT_ALLOW_PRIVATE_FETCH") == "1"


def normalise_url(url):
    """`example.com/path` -> `https://example.com/path`; the URL as given when it has a scheme."""
    url = url.strip().strip("<>\"'")
    if "://" not in url:
        url = "https://" + url
    return url


def is_public_address(address):
    """True when an IP address is one a public web server could have."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        for embedded in (ip.ipv4_mapped, ip.sixtofour):
            if embedded is not None:
                return is_public_address(str(embedded))
        if ip.teredo is not None:
            return False
    return ip.is_global and not ip.is_multicast


def check_url(url):
    """(scheme, host, port, path_and_query) for a URL the bot may fetch, else ToolError."""
    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise Refused("only http and https links can be fetched")
    if parts.username is not None or parts.password is not None:
        raise Refused("links with a username or password in them are not fetched")
    host = parts.hostname
    if not host:
        raise ToolError("that link has no host")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError:
        raise ToolError("that link has a bad port") from None
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return scheme, host, port, path


def resolve_public(host, port):
    """The first address for host, after checking that every address it has is public."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        raise ToolError("%s does not resolve" % host) from None
    addresses = []
    for family, _type, _proto, _canon, sockaddr in infos:
        if family in (socket.AF_INET, socket.AF_INET6) and sockaddr[0] not in addresses:
            addresses.append(sockaddr[0])
    if not addresses:
        raise ToolError("%s does not resolve" % host)
    if not _private_allowed():
        blocked = [a for a in addresses if not is_public_address(a)]
        if blocked:
            raise Refused("%s points at a private or local address, so it is not fetched" % host)
    return addresses[0]


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port, address, timeout):
        super().__init__(host, port, timeout=timeout)
        self._address = address

    def connect(self):
        self.sock = socket.create_connection((self._address, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port, address, timeout, context):
        super().__init__(host, port, timeout=timeout, context=context)
        self._address = address
        self._context = context
        self.peer_cert = None

    def connect(self):
        raw = socket.create_connection((self._address, self.port), self.timeout)
        # SNI and certificate checking use the real host name, not the pinned address.
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        self.peer_cert = self.sock.getpeercert()


class Response:
    """What a fetch found: the final URL, status, headers, body, and how it got there."""

    def __init__(self, url, status, reason, headers, body, seconds, chain, cert):
        self.url = url
        self.status = status
        self.reason = reason
        self.headers = headers  # {lower-case name: value}
        self.body = body
        self.seconds = seconds
        self.chain = chain  # [(url, status)] for every hop before the final one
        self.cert = cert  # the server certificate as ssl.getpeercert() gives it, or None

    def text(self):
        charset = "utf-8"
        kind = self.headers.get("content-type", "")
        if "charset=" in kind:
            charset = kind.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def fetch(url, method="GET", timeout=TIMEOUT, max_bytes=MAX_BYTES):
    """Fetch a public URL under the rules in this module's docstring; a Response or ToolError."""
    if not enabled():
        raise ToolError("the web is switched off")
    url = normalise_url(url)
    context = ssl.create_default_context()
    chain = []
    start = time.perf_counter()
    for _hop in range(MAX_REDIRECTS + 1):
        scheme, host, port, path = check_url(url)
        address = resolve_public(host, port)
        if scheme == "https":
            conn = _PinnedHTTPSConnection(host, port, address, timeout, context)
        else:
            conn = _PinnedHTTPConnection(host, port, address, timeout)
        try:
            conn.request(method, path, headers={"User-Agent": USER_AGENT,
                                                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                                                "Accept-Encoding": "identity"})
            reply = conn.getresponse()
            headers = {k.lower(): v for k, v in reply.getheaders()}
            body = reply.read(max_bytes) if method != "HEAD" else b""
        except ssl.SSLCertVerificationError as error:
            raise ToolError("the certificate for %s did not check out (%s)"
                            % (host, error.verify_message or "invalid")) from None
        except (socket.timeout, TimeoutError):
            raise ToolError("%s did not answer within %d seconds" % (host, timeout)) from None
        except (OSError, http.client.HTTPException) as error:
            raise ToolError("could not reach %s (%s)" % (host, error.__class__.__name__)) from None
        finally:
            cert = getattr(conn, "peer_cert", None)
            conn.close()
        if 300 <= reply.status < 400 and headers.get("location"):
            chain.append((url, reply.status))
            url = urljoin(url, headers["location"])
            continue
        return Response(url, reply.status, reply.reason, headers, body,
                        time.perf_counter() - start, chain, cert)
    raise ToolError("too many redirects")
