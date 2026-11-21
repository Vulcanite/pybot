"""Tests for the profile kept across chats (bot/tools/profile.py, bot/modules/profile_tools.py).

    python -m unittest discover -s tests

Every test runs in a scratch home (HOME and PYBOT_HOME): nothing here touches the real ~/.pybot.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bot.tools import profile  # noqa: E402


class Scratch(unittest.TestCase):
    def setUp(self):
        self.home = os.path.realpath(tempfile.mkdtemp(prefix="pybot-profile-"))
        self.env = mock.patch.dict(os.environ, {"HOME": self.home, "PYBOT_HOME": self.home, "PYBOT_WRITE": "1",
                                                "EXA_API_KEY": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.home, ignore_errors=True)

    def texts(self):
        return [f["text"] for f in profile.facts()]

    def raw(self):
        try:
            with open(profile.store_path(), encoding="utf-8") as handle:
                return handle.read()
        except OSError:
            return ""


class Scoring(Scratch):
    def test_tiers(self):
        cases = {
            "remember that I use Arch": "always",
            "don't forget i'm vegan": "always",
            "remember: my locker is 42": "always",
            "always use metric": "always",
            "call me Sam": "always",
            "I prefer short answers": "always",
            "my name is Sam": "keep",
            "I work as a security engineer": "keep",
            "i live in Singapore": "keep",
            "I use Arch": "keep",
            "i speak french and english": "keep",
            "my dog is called Rex": "keep",
            "I'm allergic to peanuts": "keep",
            "i use windows at work today": "chat",
            "my password is hunter2": "never",
            "my api key is sk-abc123def456": "never",
            "remember that my card number is 4111 1111 1111 1111": "never",
            "I'm tired today": None,
            "i had pasta for lunch": None,
            "it's raining": None,
            "I'm at the airport": None,
            "remember the good times": None,
            "remember to buy milk": None,
            "call me later": None,
            "i'm on a train": None,
            "my password is too weak": None,
            "remember that i want to die": None,
        }
        for line, tier in cases.items():
            self.assertEqual(profile.score(line)["tier"], tier, line)

    def test_second_person(self):
        self.assertEqual(profile.second_person("i was sure my cat likes me"), "you were sure your cat likes you")


class Store(Scratch):
    def test_keep_recall_replace_forget(self):
        self.assertIn("your name is Sam", profile.answer("my name is Sam"))
        self.assertIn("you use Arch", profile.answer("remember that I use Arch"))
        self.assertIn("Singapore", profile.answer("i live in Singapore") or "")
        self.assertIn("Sam", profile.answer("what's my name?"))
        self.assertIn("Singapore", profile.answer("do you remember where I live?"))
        listed = profile.answer("what do you remember about me")
        self.assertIn("You use Arch", listed)
        self.assertIn("Your name is Sam", listed)
        said = profile.answer("actually my name is Alex")
        self.assertIn("Alex", said)
        self.assertIn("Sam", said)  # says what it replaced
        self.assertEqual([t for t in self.texts() if "name" in t], ["Your name is Alex"])
        self.assertIn("Forgotten", profile.answer("forget that I use Arch"))
        self.assertFalse(any("Arch" in t for t in self.texts()))
        self.assertIn("nothing to forget", profile.answer("forget that I use Arch"))
        self.assertIn("Forgotten", profile.answer("forget where i live"))
        self.assertEqual(self.texts(), ["Your name is Alex"])

    def test_passing_states_and_secrets_are_not_written(self):
        for line in ("I'm tired today", "i had pizza", "I'm at the airport", "i use windows at work today"):
            self.assertIsNone(profile.answer(line), line)
        for line in ("my password is hunter2", "my api key is sk-abc123def456",
                     "remember that my card number is 4111 1111 1111 1111", "remember that my token is ghp_abcdefghijklmnop"):
            self.assertIn("won't keep that", profile.answer(line), line)
        self.assertEqual(profile.facts(), [])
        self.assertNotIn("hunter2", self.raw())
        self.assertNotIn("4111", self.raw())

    def test_forget_everything(self):
        profile.answer("my name is Sam")
        profile.answer("remember that I use Arch")
        asked = profile.answer("forget everything")
        self.assertIn("2 things", asked)
        self.assertEqual(len(profile.facts()), 2)  # a bare "forget everything" asks first
        memory = {"turns": [{"user": "forget everything", "bot": asked, "module": "profile_tools"}]}
        self.assertIn("forgotten all 2", profile.answer("yes", memory))
        self.assertEqual(profile.facts(), [])
        self.assertIsNone(profile.answer("yes"))  # "yes" means nothing without the question
        profile.answer("my name is Sam")
        self.assertIn("forgotten all 1", profile.answer("forget everything you know about me"))
        self.assertEqual(profile.facts(), [])

    def test_the_file_is_private_and_inside_home(self):
        profile.answer("my name is Sam")
        path = profile.store_path()
        self.assertTrue(path.startswith(self.home + os.sep))
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(os.path.dirname(path)).st_mode & 0o777, 0o700)
        self.assertEqual(json.loads(self.raw())["facts"][0]["value"], "Sam")

    def test_read_only_writes_nothing(self):
        with mock.patch.dict(os.environ, {"PYBOT_WRITE": "0"}):
            self.assertIn("switched off", profile.answer("remember that I use Arch"))
            self.assertIn("switched off", profile.answer("my name is Sam"))
        self.assertFalse(os.path.exists(profile.store_path()))

    def test_staged_answer_writes_nothing_until_run(self):
        reply, writes = profile.staged_answer("remember that I use Arch")
        self.assertIn("Arch", reply)
        self.assertEqual(profile.facts(), [])
        for write in writes:
            write()
        self.assertEqual(self.texts(), ["You use Arch"])

    def test_a_broken_file_is_an_empty_profile(self):
        os.makedirs(os.path.dirname(profile.store_path()))
        with open(profile.store_path(), "w") as handle:
            handle.write("{not json")
        self.assertEqual(profile.facts(), [])
        self.assertIn("Sam", profile.answer("my name is Sam"))


class InTheBot(Scratch):
    @classmethod
    def setUpClass(cls):
        from bot import runtime
        from bot.modules import profile_tools
        cls.runtime, cls.module = runtime, profile_tools

    def test_a_new_chat_knows_the_name(self):
        memory = {}
        self.runtime.turn("my name is Sam", memory)  # answered by the chat, kept quietly
        result = self.runtime.turn("remember that I use Arch", memory)
        self.assertEqual(result["module"], "profile_tools")
        self.assertEqual(sorted(self.texts()), ["You use Arch", "Your name is Sam"])
        fresh = {}
        result = self.runtime.turn("what's my name?", fresh)
        self.assertIn("Sam", result["reply"])
        result = self.runtime.turn("what do you remember about me", fresh)
        self.assertEqual(result["module"], "profile_tools")
        self.assertIn("Arch", result["reply"])
        result = self.runtime.turn("forget my name", fresh)
        self.assertEqual(result["module"], "profile_tools")
        self.assertNotIn("Sam", self.runtime.turn("what's my name?", fresh)["reply"])
        self.assertEqual(self.texts(), ["You use Arch"])

    def test_safety_lines_are_never_kept(self):
        for line in ("remember that i want to die", "my name is Sam and i want to kill myself"):
            self.assertEqual(self.runtime.turn(line, {})["module"], "safety", line)
        self.assertEqual(profile.facts(), [])

    def test_a_reply_not_said_writes_nothing(self):
        self.assertEqual(self.module.respond("remember that I use Arch", {}).count("Arch"), 1)
        self.module.after("remember that I use Arch", "some other module's reply", {})
        self.assertEqual(profile.facts(), [])

    def test_ordinary_chat_is_not_claimed(self):
        for line in ("remember the good times", "can you remember things?", "forget it", "how do i reset my password",
                     "what's in a name", "give me a random password", "make a note that tea is good",
                     "who wrote hamlet", "I'm tired today", "my name is Sam", "what's my name?"):
            self.assertFalse(self.module.TAKES_AS_IT_COMES(line, {}), line)

    def test_the_chat_memory_wins_over_an_old_profile(self):
        profile.answer("my name is Sam")
        memory = {"user": {"name": "Alex"}, "turns": [{"user": "my name is Alex", "bot": "hi", "module": "chat"}]}
        self.assertFalse(self.module.TAKES_AS_IT_COMES("what's my name?", memory))
        seeded = {}
        self.module.observe("hello", seeded)
        self.assertEqual(seeded["user"]["name"], "Sam")


if __name__ == "__main__":
    unittest.main()
