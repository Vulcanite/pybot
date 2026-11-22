"""Tests for the suggest-only commands (bot/tools/suggest.py, bot/modules/suggest_tools.py).

Nothing here runs a command: every test checks the text PyBot would show. They use the scratch
home of tests/phrasings.py. Run from the repository root:

    python -m unittest discover -s tests
"""
import os
import shlex
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import phrasings  # noqa: E402


class Suggest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = phrasings.Scratch()
        cls.home = cls.scratch.home
        from bot.tools import suggest  # noqa: PLC0415 - after the environment is set
        cls.suggest = staticmethod(suggest.suggest)
        cls.reply_for = staticmethod(suggest.reply_for)

    @classmethod
    def tearDownClass(cls):
        cls.scratch.close()

    def command(self, line):
        found = self.suggest(line)
        self.assertIsNotNone(found, line)
        self.assertTrue(found["command"], "%s: %r" % (line, found))
        self.assertTrue(found["warning"].startswith("⚠️ "), found["warning"])
        return found["command"]

    def refused(self, line):
        found = self.suggest(line)
        self.assertIsNotNone(found, line)
        self.assertEqual(found["command"], "", "%s: %r" % (line, found))
        return found["reason"]

    def test_the_safer_forms(self):
        self.assertEqual(self.command("delete ~/Desktop/todo.txt"), "rm -i ~/Desktop/todo.txt")
        self.assertEqual(self.command("remove the folder build"), "rm -rI ~/projects/pybot/build")
        self.assertEqual(self.command("move notes.md to ~/Documents"), "mv -i ~/projects/pybot/notes.md ~/Documents/")
        self.assertEqual(self.command("git push --force"), "git push --force-with-lease")
        self.assertEqual(self.command("force push"), "git push --force-with-lease")
        self.assertEqual(self.command("kill nginx"), "pkill -x nginx")

    def test_a_preview_comes_first(self):
        found = self.suggest("delete all .log files in ~/tmp")
        self.assertEqual(found["command"], "find ~/tmp -type f -name '*.log' -delete")
        self.assertIn("`find ~/tmp -type f -name '*.log'` first", found["warning"])
        self.assertIn("can't be undone", found["warning"])
        self.assertIn("ps -p 1234", self.suggest("kill process 1234")["warning"])
        self.assertIn("git clean -nd", self.suggest("git clean -fd")["warning"])

    def test_typed_commands_are_given_back(self):
        self.assertEqual(self.command("rm -rf ~/tmp"), "rm -rf ~/tmp")
        self.assertIn("rm -rI ~/tmp", self.suggest("rm -rf ~/tmp")["warning"])
        self.assertEqual(self.command("chmod +x script.sh"), "chmod +x ~/projects/pybot/script.sh")
        self.assertEqual(self.command("git reset --hard"), "git reset --hard")
        self.assertEqual(self.command("git checkout -- ."), "git checkout -- .")
        self.assertTrue(self.command("sudo apt install htop").startswith("sudo apt install htop"))

    def test_read_only_commands_are_not_ours(self):
        for line in ("git status", "git log", "git branch", "apt list --installed", "ls -la ~/tmp", "find ~/tmp"):
            self.assertIsNone(self.suggest(line), line)

    def test_paths_are_quoted(self):
        command = self.command('rename "notes.md" to "my notes; rm -rf x.md"')
        self.assertEqual(shlex.split(command)[-1], "~/projects/pybot/my notes; rm -rf x.md")
        self.assertIn("'my notes; rm -rf x.md'", command)

    def test_the_fence(self):
        self.assertIn("outside your home", self.refused("rm -rf /"))
        self.assertIn("outside your home", self.refused("delete /etc/passwd"))
        self.assertIn("outside your home", self.refused("delete ~/escape"))  # a link that points out
        self.assertIn("outside your home", self.refused("sudo rm -rf /var/log"))
        self.assertIn("outside your home", self.refused("cp ~/tmp/a.log %s/x" % self.scratch.paths["outside"]))
        self.assertIn("whole home folder", self.refused("rm -rf ~"))
        self.assertIn("whole home folder", self.refused("rm -rf ~/*"))
        self.assertIn("keys or tokens", self.refused("delete .env"))
        self.assertIn("keys or tokens", self.refused("rm ~/.ssh/id_ed25519"))
        self.assertIn("keys or tokens", self.refused("delete the .ssh folder"))
        self.assertIn("nothing at", self.refused("delete ~/nothing-here.txt"))

    def test_capability_questions_are_not_ours(self):
        for line in ("can you delete files?", "are you able to remove things", "could you kill processes",
                     "do you delete stuff", "will you move files for me", "can you install packages"):
            self.assertIsNone(self.suggest(line), line)
        self.assertEqual(self.command("can you delete ~/Desktop/todo.txt"), "rm -i ~/Desktop/todo.txt")

    def test_everyday_words_are_not_ours(self):
        for line in ("how do i kill time at the airport", "remove the stain from my shirt",
                     "i want to delete my ex from my life", "should i move to berlin", "how do i move on after a breakup",
                     "how do i delete my facebook account", "kill time", "kill me", "how do i kill myself",
                     "i want to kill him", "kill the lights", "kill bill", "delete note 1", "clear my head",
                     "empty my mind", "install windows", "move my car to the garage", "stop the music",
                     "delete it", "install it", "remove the stain"):
            self.assertIsNone(self.suggest(line), line)

    def test_nothing_runs(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("ran a command")), \
                mock.patch("subprocess.Popen", side_effect=AssertionError("ran a command")):
            for line in ("rm -rf ~/tmp", "delete all .log files in ~/tmp", "empty the trash", "uninstall docker",
                         "kill process 1234", "git reset --hard"):
                self.command(line)
        self.assertTrue(os.path.exists(os.path.join(self.home, "tmp", "a.log")))

    def test_the_module(self):
        from bot.modules import suggest_tools  # noqa: PLC0415
        self.assertEqual(suggest_tools.PRIORITY, 7100)
        self.assertTrue(suggest_tools.TAKES_AS_IT_COMES("rm -rf ~/tmp", {}))
        self.assertFalse(suggest_tools.TAKES_AS_IT_COMES("remove the stain from my shirt", {}))
        reply = suggest_tools.respond("delete ~/Desktop/todo.txt", {})
        self.assertIn("`rm -i ~/Desktop/todo.txt`", reply)
        self.assertIn("⚠️", reply)
        self.assertIn("outside your home", suggest_tools.respond("delete /etc/passwd", {}))

    def test_a_turn_never_runs_it_and_safety_still_wins(self):
        from bot import runtime  # noqa: PLC0415
        said = runtime.turn("rm -rf ~/tmp", {})
        self.assertEqual(said["module"], "suggest_tools")
        self.assertIn("rm -rf ~/tmp", said["reply"])
        self.assertTrue(os.path.isdir(os.path.join(self.home, "tmp")))
        self.assertEqual(runtime.turn("how do i kill myself", {})["module"], "safety")

    def test_off_with_the_local_tools(self):
        with mock.patch.dict(os.environ, {"PYBOT_LOCAL": "0"}):
            self.assertIsNone(self.suggest("rm -rf ~/tmp"))


if __name__ == "__main__":
    unittest.main()
