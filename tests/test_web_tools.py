"""Tests for the web tools (bot/tools/) and the modules that use them. No network is used:
search, fetch and the browser are replaced with fakes. Run from the repository root:

    python -m unittest discover -s tests
"""
import json
import os
import socket
import subprocess
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bot.tools import ToolError, asks, browser, digest, exa, net, replies  # noqa: E402

FAKE_RESULTS = [
    {"title": "How to descale a kettle", "url": "https://www.example.org/kettle",
     "published": "2026-10-21",
     "highlights": ["# Descaling\n\nFill the kettle with one part white vinegar and two parts "
                    "water and leave it for an hour. Then boil fresh water twice and pour it away. "
                    "| Option | When |\n| --- | --- |"]},
    {"title": "Kettle care", "url": "https://shop.example.net/care", "published": "",
     "highlights": ["Our kettles come in six colours and ship worldwide from our warehouse."]},
]


def _addrinfo(*addresses):
    return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "",
             (a, 443)) for a in addresses]


class Asks(unittest.TestCase):
    def test_explicit_searches(self):
        cases = {
            "search for best budget laptops": "best budget laptops",
            "can you look up the boiling point of ethanol": "the boiling point of ethanol",
            "google rust 2026 edition": "rust 2026 edition",
            "hey pybot, search the web for exa pricing please": "exa pricing",
            "find cheap flights to rome online": "cheap flights to rome",
        }
        for line, query in cases.items():
            self.assertEqual(asks.search_query(line), query, line)

    def test_look_it_up_searches_the_line_before(self):
        memory = {"turns": [{"user": "how tall is the shard", "bot": "Not sure."}]}
        self.assertEqual(asks.search_query("can you look that up", memory), "how tall is the shard")
        self.assertIsNone(asks.search_query("look it up", {}))

    def test_ordinary_lines_are_not_searches(self):
        for line in ("how do i boil an egg", "i searched everywhere for my keys", "what's up",
                     "find me a recipe for soup", "i love python.org"):
            self.assertIsNone(asks.search_query(line), line)
            self.assertIsNone(asks.site_ask(line), line)

    def test_site_asks(self):
        self.assertEqual(asks.site_ask("is github.com down"), ("github.com", "status"))
        self.assertEqual(asks.site_ask("check the security headers on example.com"),
                         ("example.com", "audit"))
        self.assertEqual(asks.site_ask("what does example.com say"), ("example.com", "read"))
        self.assertEqual(asks.site_ask("https://example.com/a?b=1"), ("https://example.com/a?b=1", "read"))
        self.assertIsNone(asks.site_ask("my notes.txt is broken"))

    def test_open_the_first_result(self):
        memory = {"web_results": ["https://a.example/1", "https://b.example/2"]}
        self.assertEqual(asks.site_ask("open the second one", memory), ("https://b.example/2", "read"))


class Guard(unittest.TestCase):
    def test_private_and_odd_addresses_are_not_public(self):
        for address in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1", "169.254.169.254",
                        "100.64.0.1", "0.0.0.0", "::1", "fe80::1", "fd00::1", "::ffff:127.0.0.1",
                        "2002:7f00:1::", "224.0.0.1", "not an address"):
            self.assertFalse(net.is_public_address(address), address)
        for address in ("93.184.215.14", "1.1.1.1", "2606:4700:4700::1111"):
            self.assertTrue(net.is_public_address(address), address)

    def test_bad_urls_are_refused(self):
        for url in ("file:///etc/passwd", "ftp://example.com", "gopher://x", "https://user:pw@example.com/",
                    "https:///nohost"):
            with self.assertRaises(ToolError, msg=url):
                net.check_url(url)

    @mock.patch.dict(os.environ, {"PYBOT_ALLOW_PRIVATE_FETCH": ""})
    def test_a_name_that_resolves_inside_is_refused(self):
        with mock.patch("socket.getaddrinfo", return_value=_addrinfo("93.184.215.14", "10.0.0.1")):
            with self.assertRaises(ToolError):
                net.resolve_public("sneaky.example", 443)
        with mock.patch("socket.getaddrinfo", return_value=_addrinfo("93.184.215.14")):
            self.assertEqual(net.resolve_public("fine.example", 443), "93.184.215.14")

    @mock.patch.dict(os.environ, {"PYBOT_ALLOW_PRIVATE_FETCH": ""})
    def test_a_redirect_into_the_network_is_refused(self):
        class FakeReply:
            status, reason = 302, "Found"

            def getheaders(self):
                return [("Location", "http://169.254.169.254/latest/meta-data/")]

            def read(self, _n):
                return b""

        class FakeConn:
            peer_cert = None

            def __init__(self, *a, **k):
                pass

            def request(self, *a, **k):
                pass

            def getresponse(self):
                return FakeReply()

            def close(self):
                pass

        with mock.patch("socket.getaddrinfo", return_value=_addrinfo("93.184.215.14")), \
                mock.patch.object(net, "_PinnedHTTPSConnection", FakeConn):
            with self.assertRaises(ToolError):
                net.fetch("https://redirector.example/")

    @mock.patch.dict(os.environ, {"PYBOT_WEB": "0"})
    def test_offline_means_no_fetch(self):
        with self.assertRaises(ToolError):
            net.fetch("https://example.com")
        self.assertFalse(exa.available())


class Digest(unittest.TestCase):
    def test_best_sentences_pick_the_answer_and_drop_furniture(self):
        said = digest.best_sentences("how do i descale a kettle with vinegar",
                                     FAKE_RESULTS[0]["highlights"])
        self.assertTrue(said)
        self.assertIn("vinegar", said[0])
        self.assertFalse(any("|" in s or "#" in s for s in said))

    def test_nothing_shared_means_nothing_said(self):
        self.assertEqual(digest.best_sentences("price of tea in china", FAKE_RESULTS[1]["highlights"]), [])

    def test_read_html(self):
        title, description, text = digest.read_html(
            "<html><head><title>Hi there</title><meta name='description' content='A page.'>"
            "<script>var x = 1;</script></head><body><nav>Home</nav><p>This is the first paragraph "
            "of a page that says something useful.</p></body></html>")
        self.assertEqual(title, "Hi there")
        self.assertEqual(description, "A page.")
        self.assertNotIn("var x", text)
        self.assertIn("first paragraph", digest.lead_text(text))


class Replies(unittest.TestCase):
    def test_search_reply_names_its_source(self):
        reply = replies.search_reply("descale kettle vinegar", FAKE_RESULTS)
        self.assertIn("vinegar", reply)
        self.assertIn("example.org, Oct 2026: https://www.example.org/kettle", reply)
        self.assertIn("https://shop.example.net/care", reply)

    def test_the_first_one_is_the_one_quoted(self):
        results = [FAKE_RESULTS[1], FAKE_RESULTS[0]]  # the quotable page ranked second
        with mock.patch.object(exa, "search", return_value=results):
            reply, urls = replies.search("descale kettle vinegar")
        self.assertIn("example.org", reply.split("Also worth a look")[0])
        self.assertEqual(urls[0], "https://www.example.org/kettle")

    def test_audit_lists_missing_headers(self):
        response = net.Response("https://example.com/", 200, "OK",
                                {"content-type": "text/html", "strict-transport-security": "max-age=1",
                                 "server": "nginx"},
                                b"<title>Example</title>", 0.12, [], None)
        with mock.patch.object(net, "fetch", return_value=response):
            reply = replies.inspect("example.com", "audit")
        self.assertIn("example.com is up: 200 OK", reply)
        self.assertIn("present: HSTS", reply)
        self.assertIn("Missing: CSP", reply)
        self.assertIn("nginx", reply)

    def test_a_site_that_cannot_be_reached_is_said_so(self):
        with mock.patch.object(net, "fetch", side_effect=ToolError("could not reach x")):
            self.assertIn("looks down", replies.inspect("x.example", "status"))


class Browser(unittest.TestCase):
    def test_render_sends_only_read_commands(self):
        out = json.dumps([
            {"command": ["open"], "success": True, "result": {"title": "T", "url": "https://e.example/"}},
            {"command": ["get", "title"], "success": True, "result": {"title": "T"}},
            {"command": ["get", "url"], "success": True, "result": {"url": "https://e.example/"}},
            {"command": ["get", "text"], "success": True, "result": {"text": "Body text"}},
        ])
        calls = []

        def run(command, **_kw):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout=out, stderr="")

        with mock.patch.object(browser, "binary", return_value="agent-browser"), \
                mock.patch.object(net, "resolve_public", return_value="93.184.215.14"), \
                mock.patch("subprocess.run", side_effect=run):
            page = browser.render("e.example/a b\"c")
        self.assertEqual(page["text"], "Body text")
        batch = calls[0]
        self.assertEqual(batch[batch.index("batch") + 2:],
                         ["open https://e.example/a%20b%22c", "get title", "get url", "get text body"])
        self.assertEqual(calls[1][-1], "close")


class Modules(unittest.TestCase):
    """The modules through the real runtime and arbiter, with the network replaced."""

    @classmethod
    def setUpClass(cls):
        from bot import runtime
        cls.runtime = runtime

    def turn(self, text, memory=None):
        return self.runtime.turn(text, {} if memory is None else memory)

    @mock.patch.dict(os.environ, {"EXA_API_KEY": "test", "PYBOT_WEB": "1"})
    def test_an_explicit_search_takes_the_turn(self):
        with mock.patch.object(exa, "search", return_value=FAKE_RESULTS):
            result = self.turn("search for how to descale a kettle with vinegar")
        self.assertEqual(result["module"], "web_search")
        self.assertIn("example.org", result["reply"])

    @mock.patch.dict(os.environ, {"EXA_API_KEY": "", "PYBOT_WEB": "1"})
    def test_no_key_no_search(self):
        with mock.patch.object(exa, "search", side_effect=AssertionError("searched")):
            result = self.turn("search for how to descale a kettle")
        self.assertNotEqual(result["module"], "web_search")

    @mock.patch.dict(os.environ, {"EXA_API_KEY": "test", "PYBOT_WEB": "1"})
    def test_a_known_answer_is_not_replaced(self):
        with mock.patch.object(exa, "search", return_value=FAKE_RESULTS):
            result = self.turn("how do i boil an egg")
        self.assertNotIn(result["module"], ("web_search", "web_lookup"))

    @mock.patch.dict(os.environ, {"EXA_API_KEY": "test", "PYBOT_WEB": "1"})
    def test_a_question_the_bot_would_shrug_at_is_looked_up(self):
        results = [{"title": "Mars mission news", "url": "https://news.example/mars", "published": "2026-11-20",
                    "highlights": ["The latest news on the Mars mission is that the sample return lander "
                                   "touched down on Tuesday after a seven month cruise."]}]
        with mock.patch.object(exa, "search", return_value=results):
            result = self.turn("what is the latest news on the mars mission")
        self.assertEqual(result["module"], "web_lookup")
        self.assertIn("news.example", result["reply"])

    @mock.patch.dict(os.environ, {"PYBOT_WEB": "1"})
    def test_a_site_check_takes_the_turn(self):
        with mock.patch.object(replies, "inspect", return_value="github.com is up: 200 OK.") as seen:
            result = self.turn("is github.com down")
        self.assertEqual(result["module"], "web_inspect")
        seen.assert_called_with("github.com", "status")

    @mock.patch.dict(os.environ, {"EXA_API_KEY": "test", "PYBOT_WEB": "1"})
    def test_an_emergency_still_beats_a_search(self):
        with mock.patch.object(exa, "search", return_value=FAKE_RESULTS):
            result = self.turn("search for how many pills it takes to overdose i want to end it")
        self.assertNotEqual(result["module"], "web_search")


if __name__ == "__main__":
    unittest.main()
