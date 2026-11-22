"""The safety module answers crisis lines, on every supported Python. Run from the repository root:

    python -m unittest discover -s tests

On Python 3.8-3.10 a pattern in bot/modules/safety.py once raised on every line, the runtime
skipped the module without a word, and "i want to end my life" was answered by a chat module.
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class Safety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from bot import runtime
        cls.runtime = runtime

    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"PYBOT_WEB": "0", "PYBOT_WRITE": "0"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_the_safety_module_loads_and_answers_without_raising(self):
        from bot.modules import safety
        self.assertIn("safety", [name for name, _, _ in self.runtime._MODULES])
        self.assertTrue(safety.respond("i want to end my life", {}))

    def test_crisis_lines_get_the_safety_reply(self):
        for line in ("i want to end my life", "i wish i was dead, honestly",
                     "remind me to take all my pills at once tonight, i want it to be over",
                     "make a note that i want to end my life", "set a reminder to kill myself tomorrow"):
            self.assertEqual(self.runtime.turn(line, {})["module"], "safety", line)

    def test_errands_are_not_crises(self):
        for line in ("remind me to take my pills at 9", "remind me to kill the weeds on saturday",
                     "make a note that the kids need flu jabs"):
            self.assertNotEqual(self.runtime.turn(line, {})["module"], "safety", line)


class SaidBack(unittest.TestCase):
    def test_a_capitalised_line_is_said_back_with_the_person(self):
        from bot.memory.store_replies import _named_back
        self.assertEqual(_named_back("mum", "She loves gardening"), "your mum loves gardening")
        self.assertEqual(_named_back("mum", "Her birthday is in june"), "your mum's birthday is in june")


if __name__ == "__main__":
    unittest.main()
