"""Tests for questions about PyBot itself (bot/tools/capabilities.py, bot/modules/capability_tools.py).

Run from the repository root:

    python -m unittest discover -s tests
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bot.modules import capability_tools, note_tools, web_search  # noqa: E402
from bot.tools import capabilities, exa, fallback_search  # noqa: E402

ON = {"PYBOT_LOCAL": "1", "PYBOT_WRITE": "1", "PYBOT_WEB": "1", "EXA_API_KEY": "test"}


class Table(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, ON)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_questions_about_the_bot_are_answered(self):
        for line in ("can you read files?", "what can you do?", "do you have access to my files?",
                     "can you delete files?", "are you connected to the internet?", "can you see my screen?",
                     "what tools do you have", "Can u read my files", "can you set reminders?",
                     "are you able to browse websites?", "can you send emails?", "can you remember things?"):
            said = capabilities.answer(line)
            self.assertTrue(said, line)
            self.assertTrue(capability_tools.TAKES_AS_IT_COMES(line, {}), line)

    def test_other_lines_are_left_alone(self):
        for line in ("can you believe it rained again", "you can do it!", "can you pass me the salt",
                     "can you help me plan a trip", "list some good books", "can you remember that i use arch",
                     "can you find all python files in ~", "can you remind me to call mum at 5pm",
                     "how are you", "help"):
            self.assertIsNone(capabilities.answer(line), line)

    def test_the_answer_follows_what_is_switched_on(self):
        self.assertIn("Exa", capabilities.answer("can you search the web?"))
        with mock.patch.dict(os.environ, {"EXA_API_KEY": ""}):
            self.assertIn("no EXA_API_KEY", capabilities.answer("can you search the web?"))
            self.assertIn("can't search online", capabilities.answer("what can you do"))
        with mock.patch.dict(os.environ, {"PYBOT_WEB": "0"}):
            self.assertIn("offline", capabilities.answer("are you online?"))
        with mock.patch.dict(os.environ, {"PYBOT_LOCAL": "0"}):
            self.assertIn("switched off", capabilities.answer("can you read my files?"))
        with mock.patch.dict(os.environ, {"PYBOT_WRITE": "0"}):
            self.assertIn("PYBOT_WRITE=0", capabilities.answer("can you set reminders?"))
        self.assertIn("Try:", capabilities.answer("can you read files?"))

    def test_never_searched(self):
        with mock.patch.object(exa, "available", return_value=True):
            for line in ("can you search the web?", "can you search my files for something", "what can you do"):
                self.assertFalse(web_search.TAKES_AS_IT_COMES(line, {}), line)
                self.assertTrue(fallback_search.about_the_bot(line), line)
            self.assertFalse(fallback_search.about_the_bot("can you tell me the capital of peru"))
            self.assertFalse(fallback_search.about_the_bot("what is the tallest mountain"))

    def test_a_reminder_question_sets_no_reminder(self):
        self.assertFalse(note_tools.TAKES_AS_IT_COMES("can you set reminders?", {}))
        self.assertTrue(note_tools.TAKES_AS_IT_COMES("set a reminder to stretch in 20 minutes", {}))


class Turn(unittest.TestCase):
    """Through the real runtime and arbiter."""

    def test_the_capability_module_takes_the_turn(self):
        from bot import runtime
        with mock.patch.dict(os.environ, ON), \
                mock.patch("bot.tools.exa.search", side_effect=AssertionError("searched the web")):
            for line in ("can you read files?", "what can you do?", "can you search the web?"):
                result = runtime.turn(line, {})
                self.assertEqual(result["module"], "capability_tools", line)
                self.assertFalse(fallback_search.wants_the_web(line, {}, result), line)


if __name__ == "__main__":
    unittest.main()
