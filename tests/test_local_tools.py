"""Tests for the local commands (bot/tools/local.py, bot/tools/runner.py, bot/modules/local_tools.py).

They run the real find, grep, head and ls on a scratch folder. Run from the repository root:

    python -m unittest discover -s tests
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bot.tools import local, runner  # noqa: E402


class Scratch(unittest.TestCase):
    """A scratch folder that "here" means for the duration of a test."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pybot-local-")
        files = {
            "app/main.py": "import os\n\n# TODO: tidy this\nprint('hello')\n",
            "app/util.py": "def helper():\n    return 'TODO later'\n",
            "notes/plan.md": "# Plan\n\nShip it.\n",
            "notes/a; rm -rf x.txt": "a file with a shell-looking name\n",
            "dashes.txt": "this line mentions --help on purpose\n",
            ".env": "API_TOKEN=supersecretvalue123\n",
            "config.ini": "password = hunter2hunter2\nname = demo\n",
            "node_modules/dep/index.js": "// TODO in a dependency\n",
            "big.bin": "\0" * 200_000,
        }
        for name, body in files.items():
            path = os.path.join(self.dir, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as handle:
                handle.write(body)
        self.env = mock.patch.dict(os.environ, {"PYBOT_WORKDIR": self.dir, "PYBOT_HOME": self.dir, "PYBOT_LOCAL": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def reply(self, text):
        found = local.plan(text)
        self.assertIsNotNone(found, text)
        return runner.reply_for(found)


class Plans(Scratch):
    def test_lines_become_the_right_command(self):
        cases = {
            "find all python files in app": "find",
            "find files named plan in notes": "find",
            "search for TODO in app": "grep",
            "which files mention helper": "grep",
            "show me notes/plan.md": "head",
            "last 2 lines of app/main.py": "tail",
            "what's in notes": "ls",
            "how big is app": "du",
            "how many lines in app/main.py": "wc",
            "how much disk space do i have": "df",
            "how much ram is free": "free",
            "what's using the most cpu": "ps",
            "what's using port 8080": "ss",
            "is sshd running": "pgrep",
        }
        for line, program in cases.items():
            found = local.plan(line)
            self.assertIsNotNone(found, line)
            self.assertEqual(found.argv[0], program, line)

    def test_everyday_phrasings(self):
        cases = {
            "find me main.py": "find",
            "find me the python file util.py": "find",
            "give me the list of all the files in this folder": "ls",
            "list all the files in this folder": "ls",
            "what's in the current folder": "ls",
            "give me the size of this folder": "du",
            "how big is this folder": "du",
            "give me the first 2 lines of app/main.py": "head",
            "find all python files in this folder": "find",
        }
        for line, program in cases.items():
            found = local.plan(line)
            self.assertIsNotNone(found, line)
            self.assertEqual(found.argv[0], program, line)
        self.assertEqual(local.plan("how big is this folder").argv[-1], self.dir)

    def test_ordinary_chat_is_not_a_command(self):
        for line in ("what's in a name", "show me paris", "where is paris", "is it running",
                     "what's changed", "find my keys", "search for exa pricing in 2026",
                     "i love python files", "how are you", "how big is the moon", "give me a hug",
                     "find me a girlfriend", "how big is this", "give me the list of reasons"):
            self.assertIsNone(local.plan(line), line)

    def test_switched_off(self):
        with mock.patch.dict(os.environ, {"PYBOT_LOCAL": "0"}):
            self.assertIsNone(local.plan("what's in notes"))

    def test_user_words_are_only_ever_arguments(self):
        found = local.plan("search for --help in .")
        index = found.argv.index("-e")
        self.assertEqual(found.argv[index + 1], "--help")
        self.assertEqual(found.argv[index + 2], "--")
        self.assertIn("dashes.txt", runner.reply_for(found))


class Replies(Scratch):
    def test_find_lists_files_and_skips_dependencies(self):
        said = self.reply("find all python files in app")
        self.assertIn("Ran: `find", said)
        self.assertIn("main.py", said)
        self.assertIn("util.py", said)

    def test_grep_skips_node_modules_and_secrets(self):
        said = self.reply("search for TODO in .")
        self.assertIn("main.py", said)
        self.assertNotIn("node_modules", said.split("\n", 1)[1])
        said = self.reply("search for supersecret in .")
        self.assertIn("No matches", said)

    def test_a_capped_count_says_so(self):
        with open(os.path.join(self.dir, "app", "many.py"), "w") as handle:
            handle.write("# TODO\n" * 12)
        said = self.reply("search for TODO in app")
        self.assertIn("at least", said)
        self.assertIn("may be more", said)

    def test_secret_values_are_masked(self):
        said = self.reply("search for password in .")
        self.assertIn("config.ini", said)
        self.assertNotIn("hunter2hunter2", said)
        self.assertIn("****", said)

    def test_a_secrets_file_is_not_shown(self):
        said = self.reply("show me .env")
        self.assertIn("won't print it", said)
        self.assertNotIn("supersecret", said)

    def test_a_shell_looking_file_name_is_just_a_name(self):
        said = self.reply("find files named rm in notes")
        self.assertIn("a; rm -rf x.txt", said)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "notes")))

    def test_show_part_of_a_file(self):
        said = self.reply("first 3 lines of app/main.py")
        self.assertIn("import os", said)
        self.assertIn("(3 of 4 lines)", said)

    def test_binary_files_are_not_dumped(self):
        self.assertIn("binary file", self.reply("show me big.bin"))

    def test_largest_files(self):
        said = self.reply("largest files in .")
        self.assertIn("big.bin", said)
        self.assertIn("biggest first", said)

    def test_count(self):
        self.assertIn("2 files", self.reply("how many python files in app"))


class Module(Scratch):
    """Through the real runtime and arbiter."""

    @classmethod
    def setUpClass(cls):
        from bot import runtime
        cls.runtime = runtime

    def test_a_local_ask_takes_the_turn(self):
        result = self.runtime.turn("find all python files in app", {})
        self.assertEqual(result["module"], "local_tools")
        self.assertIn("main.py", result["reply"])

    def test_a_local_search_beats_a_web_search(self):
        with mock.patch.dict(os.environ, {"EXA_API_KEY": "test"}), \
                mock.patch("bot.tools.exa.search", side_effect=AssertionError("searched the web")):
            result = self.runtime.turn("search for TODO in app", {})
        self.assertEqual(result["module"], "local_tools")

    def test_chat_is_left_alone(self):
        result = self.runtime.turn("how are you today", {})
        self.assertNotEqual(result["module"], "local_tools")


if __name__ == "__main__":
    unittest.main()
