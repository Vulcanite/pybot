"""Chains of two or three read-only local asks (bot/tools/chain.py, bot/modules/chain_tools.py).

Runs in the scratch home of tests/phrasings.py: nothing here touches the real home folder.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import phrasings  # noqa: E402


def kinds(steps):
    return None if steps is None else [s if isinstance(s, str) else s.kind for s in steps]


class Chains(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = phrasings.Scratch()
        cls.home = cls.scratch.home
        from bot.tools import chain  # noqa: PLC0415 - after the environment is set
        from bot.modules import chain_tools  # noqa: PLC0415
        cls.chain, cls.module = chain, chain_tools

    @classmethod
    def tearDownClass(cls):
        cls.scratch.close()

    def test_steps_are_the_planner_kinds(self):
        steps = self.chain.steps
        self.assertEqual(kinds(steps("show me README.md and then count its lines")), ["file", "wc"])
        self.assertEqual(kinds(steps("find README.md and open it")), ["files", "file"])
        self.assertEqual(kinds(steps("show me README.md, count its lines, then search for install in it")),
                         ["file", "wc", "grep"])
        self.assertEqual(kinds(steps("check disk space and then show the biggest files in ~")), ["table", "sized"])

    def test_one_ask_is_not_a_chain(self):
        for line in ("show me README.md", "find python and json files", "salt and pepper",
                     "search for salt and pepper in ~/Documents", "I went shopping and then cooked dinner",
                     "find my keys and then go to work", "rock and roll then sleep", "open it and then close it",
                     "check disk space and memory"):
            self.assertIsNone(self.chain.steps(line), line)
            self.assertFalse(self.module.TAKES_AS_IT_COMES(line, {}), line)

    def test_at_most_three_steps(self):
        line = "git status, then show me README.md, then count its lines, then open it"
        self.assertIsNone(self.chain.steps(line))

    def test_the_second_step_gets_the_first_ones_path(self):
        reply = self.chain.answer("show me README.md and then count its lines", {})
        self.assertIn("Step 1 of 2 (show me README.md)", reply)
        self.assertIn("Step 2 of 2 (how many lines in", reply)
        self.assertIn("7 lines in", reply)

    def test_the_first_one_of_a_search(self):
        reply = self.chain.answer("search for TODO in ~/projects/pybot, then open the first one", {})
        self.assertIn("Step 2 of 2 (show ", reply)
        self.assertIn("head -n 40", reply)
        self.assertIn("def respond", reply)  # bot/core.py, the first file grep named

    def test_them_runs_one_search_per_file(self):
        reply = self.chain.answer("find files changed today in ~/projects and search them for TODO", {})
        self.assertIn("TODO", reply.split("Step 2 of 2")[1])
        self.assertNotIn(phrasings.SECRET_VALUE, reply)
        self.assertNotIn("in ~/projects/pybot/.env", reply)

    def test_a_refused_step_stops_the_chain(self):
        reply = self.chain.answer("show ~/.ssh/config and then count its lines", {})
        self.assertIn("won't", reply)
        self.assertNotIn("Step 2", reply)
        self.assertNotIn("User me", reply)

    def test_it_needs_one_candidate(self):
        reply = self.chain.answer("list the python files in ~/projects/pybot/bot, then open it", {})
        self.assertIn("found 3", reply)
        self.assertIn("the first one", reply)
        self.assertNotIn("head -n", reply)

    def test_nothing_found_stops(self):
        reply = self.chain.answer("find nosuchthing.txt and then open it", {})
        self.assertIn("found nothing", reply)

    def test_a_change_is_never_run(self):
        target = os.path.join(self.home, "Desktop", "todo.txt")
        reply = self.chain.answer("find todo.txt in ~/Desktop and then delete it", {})
        self.assertIn("not run", reply)
        self.assertTrue(os.path.exists(target))
        self.assertEqual(kinds(self.chain.steps("find todo.txt in ~/Desktop and then delete it")),
                         ["files", "suggest"])
        self.assertIsNone(self.chain.steps("delete todo.txt and then show me README.md"))

    def test_a_path_with_a_space_is_one_word(self):
        folder = os.path.join(self.home, "Documents", "my stuff")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "plan b.txt"), "w") as handle:
            handle.write("one\ntwo\n")
        reply = self.chain.answer('find "plan b.txt" in ~/Documents and then count its lines', {})
        self.assertIn('/Documents/my stuff/plan b.txt"):', reply)  # quoted: one word for the planner
        self.assertIn("2 lines in", reply)

    def test_a_follow_up_line_uses_the_last_result(self):
        memory = {"turns": [{"user": "x", "bot": "y", "module": None}]}
        line = "find README.md"
        from bot.tools import local, runner  # noqa: PLC0415
        self.module.after(line, runner.reply_for(local.plan(line)), memory)
        self.assertTrue(memory["last_paths"][0].endswith("projects/pybot/README.md"))
        self.assertTrue(self.module.TAKES_AS_IT_COMES("count its lines", memory))
        self.assertIn("lines in", self.module.respond("count its lines", memory))
        self.assertFalse(self.module.TAKES_AS_IT_COMES("count the lines", memory))  # "the" alone is too loose

    def test_an_old_result_is_not_it(self):
        memory = {"turns": [], "last_paths": [os.path.join(self.home, "notes.md")], "last_paths_turn": 0}
        self.assertTrue(self.module.TAKES_AS_IT_COMES("open it", memory))
        memory["turns"] = [{}] * 5
        self.assertFalse(self.module.TAKES_AS_IT_COMES("open it", memory))

    def test_a_later_web_search_owns_the_first_one(self):
        memory = {"turns": [], "last_paths": [os.path.join(self.home, "notes.md")], "last_paths_turn": 0,
                  "last_paths_web": []}
        self.assertTrue(self.module.TAKES_AS_IT_COMES("open the first one", memory))
        memory["web_results"] = ["https://example.org/page"]
        self.assertFalse(self.module.TAKES_AS_IT_COMES("open the first one", memory))
        self.module.after("search for cats", "Some cats.", memory)
        self.assertNotIn("last_paths", memory)

    def test_a_whole_turn(self):
        from bot import runtime  # noqa: PLC0415
        memory = {}
        result = runtime.turn("show me README.md and then count its lines", memory)
        self.assertEqual(result["module"], "chain_tools")
        result = runtime.turn("search for install in it", memory)
        self.assertEqual(result["module"], "chain_tools")
        self.assertIn("pip install", result["reply"])


if __name__ == "__main__":
    unittest.main()
