"""Tests for the home-folder fence, the developer tools, the quick answers and notes/reminders.

    python -m unittest discover -s tests
"""
import datetime
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bot.tools import local, notes, quick, runner  # noqa: E402


class Fenced(unittest.TestCase):
    """A scratch folder that stands in for home: the fence, "here", and where notes are kept."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="pybot-home-")
        self.outside = tempfile.mkdtemp(prefix="pybot-outside-")
        for name, body in {"proj/app.py": "class Box:\n    def open(self, key):\n        pass\n\ndef helper(a, *rest):\n    return 1\n",
                           "proj/app.log": "ok\nERROR disk full\nWARN slow\nTraceback (most recent call last)\n",
                           "proj/package.json": '{"name": "demo", "version": "1.0.0", "scripts": {"test": "jest"}, '
                                                '"dependencies": {"left-pad": "^1.3.0"}}',
                           ".ssh/id_ed25519": "PRIVATE KEY", ".ssh/config": "Host x\n"}.items():
            path = os.path.join(self.home, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as handle:
                handle.write(body)
        with open(os.path.join(self.outside, "secret.txt"), "w") as handle:
            handle.write("outside the fence\n")
        os.symlink(self.outside, os.path.join(self.home, "escape"))
        self.env = mock.patch.dict(os.environ, {"PYBOT_HOME": self.home, "PYBOT_WORKDIR": os.path.join(self.home, "proj"),
                                                "PYBOT_LOCAL": "1", "PYBOT_WRITE": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.outside, ignore_errors=True)

    def reply(self, text):
        found = local.plan(text)
        self.assertIsNotNone(found, text)
        return runner.reply_for(found)


class Fence(Fenced):
    def test_paths_outside_home_are_refused(self):
        for line in ("what's in %s" % self.outside, "show me %s/secret.txt" % self.outside,
                     "search for fence in %s" % self.outside, "list files in escape",
                     "show me escape/secret.txt"):
            said = self.reply(line)
            self.assertIn("outside your home folder", said, line)
            self.assertNotIn("outside the fence", said)

    def test_secrets_folders_are_refused(self):
        self.assertIn("keys or tokens", self.reply("list files in ~/.ssh".replace("~", self.home)))
        self.assertIn("won't print it", self.reply("show me %s/.ssh/config" % self.home))

    def test_commands_run_inside_home(self):
        found = local.plan("git status") or local.plan("what's in this folder")
        self.assertTrue(local.inside_home(found.cwd))

    def test_a_workdir_outside_home_falls_back_to_home(self):
        with mock.patch.dict(os.environ, {"PYBOT_WORKDIR": self.outside}):
            self.assertEqual(local.workdir(), os.path.realpath(self.home))


class DevTools(Fenced):
    def test_code_search_is_not_offered(self):
        # Code search was taken out until it can cover more than one language.
        for line in ("where is helper defined", "list the functions in app.py"):
            found = local.plan(line)
            self.assertTrue(found is None or found.argv[0] != "grep" or "defined" not in line, line)
        self.assertIsNone(local.plan("list the functions in app.py"))

    def test_errors_in_a_log(self):
        said = self.reply("errors in app.log")
        self.assertIn("disk full", said)
        self.assertIn("Traceback", said)
        self.assertNotIn("WARN slow", said)

    def test_package_json(self):
        said = self.reply("what's in package.json")
        self.assertIn("demo 1.0.0", said)
        self.assertIn("left-pad", said)

    def test_hash_and_stat(self):
        self.assertIn("SHA256", self.reply("sha256 of app.py"))
        self.assertIn("permissions", self.reply("when was app.py last modified"))

    @unittest.skipUnless(shutil.which("man") and subprocess.run(["man", "-w", "tar"], capture_output=True).returncode == 0,
                         "no man page for tar")
    def test_help_for_a_command(self):
        said = self.reply("how do i use tar")
        self.assertIn("tar", said)
        self.assertIsNone(local.plan("how do i use time"))  # an everyday word needs "the time command"

    def test_ports_and_dns_do_not_need_files(self):
        with mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.215.14", 0))]):
            self.assertIn("93.184.215.14", self.reply("what's the ip of example.com"))
        with mock.patch("socket.create_connection", side_effect=ConnectionRefusedError):
            self.assertIn("closed", self.reply("is port 9 open on localhost"))


class Quick(unittest.TestCase):
    def test_answers(self):
        self.assertIn("5,000 MB", quick.answer("convert 5 GB to MB"))
        self.assertIn("5,120 MiB", quick.answer("convert 5 GB to MB"))
        self.assertIn("2023-11-14 22:13:20 UTC", quick.answer("1700000000 to a date"))
        self.assertIn("hello", quick.answer("base64 decode aGVsbG8="))
        self.assertIn("0xff", quick.answer("255 to hex"))
        self.assertIn('"a": 1', quick.answer('pretty print {"a":1}'))
        self.assertIn("a%20b", quick.answer("url encode a b"))
        self.assertIn("here", quick.answer("what time is it"))
        self.assertIn("Tokyo", quick.answer("what time is it in tokyo"))

    def test_chat_is_left_alone(self):
        for line in ("what time is it in my heart", "time in a bottle", "i have 5 gb of photos",
                     "what's 15% of 240", "convert 10 km to miles"):
            self.assertIsNone(quick.answer(line), line)


class Notes(Fenced):
    def test_notes_round_trip(self):
        self.assertIn("Noted (#1)", notes.answer("make a note that the vpn is needed for ssh"))
        self.assertIn("vpn is needed", notes.answer("what did i note about vpn"))
        self.assertIn("Deleted note #1", notes.answer("delete note 1"))
        self.assertTrue(notes.store_path().startswith(os.path.realpath(self.home)))
        self.assertEqual(os.stat(notes.store_path()).st_mode & 0o777, 0o600)

    def test_read_only(self):
        with mock.patch.dict(os.environ, {"PYBOT_WRITE": "0"}):
            self.assertIn("switched off", notes.answer("make a note that x y z"))
            self.assertFalse(os.path.exists(notes.store_path()))

    def test_reminders_fall_due_once(self):
        said = notes.answer("remind me to stretch in 5 minutes")
        self.assertIn("Reminder #1", said)
        self.assertEqual(notes.due_now(), [])
        later = datetime.datetime.now().astimezone() + datetime.timedelta(minutes=6)
        with mock.patch.object(notes, "_now", return_value=later):
            due = notes.due_now()
            self.assertEqual([r["text"] for r in due], ["stretch"])
            self.assertEqual(notes.due_now(), [])

    def test_when(self):
        now = datetime.datetime(2026, 11, 21, 17, 40).astimezone()
        cases = {"x in 20 minutes": "21 18:00", "x at 9": "21 21:00", "x at 11pm": "21 23:00",
                 "x tomorrow at 9am": "22 09:00", "x on monday at 10": "23 10:00", "x tonight": "21 20:00"}
        for line, expected in cases.items():
            due, what = notes.parse_when(line, now)
            self.assertEqual(due.strftime("%d %H:%M"), expected, line)
            self.assertEqual(what, "x", line)
        self.assertIsNone(notes.parse_when("drink water", now)[0])

    def test_when_in_any_order_and_more_dates(self):
        now = datetime.datetime(2026, 11, 22, 10, 0).astimezone()  # a Sunday
        cases = {
            # the day after the time used to be dropped, saving today
            "at 9:30 tomorrow about the standup": ("2026-11-23 09:30", "the standup"),
            "to leave at 5 tomorrow": ("2026-11-23 17:00", "leave"),
            "to call the bank at 4:30pm on thursday": ("2026-11-26 16:30", "call the bank"),
            "x at 8:00 a.m. tomorrow": ("2026-11-23 08:00", "x"),
            "x tomorrow morning": ("2026-11-23 09:00", "x"),
            "x this evening": ("2026-11-22 18:00", "x"),
            "x tonight at 8": ("2026-11-22 20:00", "x"),
            "x on friday evening at 7": ("2026-11-27 19:00", "x"),
            "x tomorrow 9": ("2026-11-23 09:00", "x"),
            "x for 7pm": ("2026-11-22 19:00", "x"),
            "x on December 5th": ("2026-12-05 09:00", "x"),
            "x on 5 dec": ("2026-12-05 09:00", "x"),
            "x on the 5th of january at 10:15": ("2027-01-05 10:15", "x"),
            "x on the 25th": ("2026-11-25 09:00", "x"),
            "x next week": ("2026-11-29 09:00", "x"),
            "x in 2 months": ("2027-01-22 10:00", "x"),
            "x in 1 year": ("2027-11-22 10:00", "x"),
            "run for 2 hours at 6pm": ("2026-11-22 18:00", "run for 2 hours"),
        }
        for line, (expected, what) in cases.items():
            due, said = notes.parse_when(line, now)
            self.assertIsNotNone(due, line)
            self.assertEqual((due.strftime("%Y-%m-%d %H:%M"), said), (expected, what), line)
        for line in ("buy 2 apples", "x on feb 30"):
            self.assertIsNone(notes.parse_when(line, now)[0], line)

    def test_repeating_and_past_reminders_are_not_saved(self):
        said = notes.answer("remind me every day at 9 to take my pills")
        self.assertIn("one-off", said)
        self.assertIn("remind me to take my pills tomorrow", said)
        self.assertIn("already passed", notes.answer("remind me to x on 2020-01-01"))
        self.assertFalse(os.path.exists(notes.store_path()))

    def test_announce_says_when_and_marks_missed(self):
        now = datetime.datetime(2026, 11, 22, 10, 0).astimezone()
        item = {"id": 3, "text": "stretch", "due": now.isoformat(timespec="minutes")}
        self.assertEqual(notes.announce(item, now), "[reminder #3] stretch (due Sun 22 Nov 10:00)")
        later = now + datetime.timedelta(hours=3)
        self.assertEqual(notes.announce(item, later), "[reminder #3] stretch (missed, was due Sun 22 Nov 10:00)")

    def test_saving_stays_inside_home_and_never_overwrites(self):
        memory = {"turns": [{"user": "hi", "bot": "line one\nline two", "module": "x"}]}
        self.assertIn("Saved the last reply", notes.answer("save that to out.md", memory))
        with open(os.path.join(self.home, "proj", "out.md")) as handle:
            self.assertEqual(handle.read(), "line one\nline two\n")
        self.assertIn("already exists", notes.answer("save that to out.md", memory))
        self.assertIn("Saved", notes.answer("save that to out.md and overwrite", memory))
        self.assertIn("outside your home", notes.answer("save that to %s/x.md" % self.outside, memory))
        self.assertIn("outside your home", notes.answer("save that to %s/escape/x.md" % self.home, memory))
        self.assertIn("secrets", notes.answer("save that to .env", memory))
        self.assertFalse(os.path.exists(os.path.join(self.outside, "x.md")))


class Modules(Fenced):
    @classmethod
    def setUpClass(cls):
        from bot import runtime
        cls.runtime = runtime

    def test_each_tool_takes_its_turn(self):
        cases = {"what time is it": "quick_tools", "base64 decode aGVsbG8=": "quick_tools",
                 "remind me to stretch in 10 minutes": "note_tools", "make a note that tea is good": "note_tools",
                 "errors in app.log": "local_tools"}
        for line, module in cases.items():
            self.assertEqual(self.runtime.turn(line, {})["module"], module, line)

    def test_a_note_is_only_saved_when_its_reply_is_the_one_said(self):
        self.assertEqual(self.runtime.turn("make a note that i want to end my life", {})["module"], "safety")
        self.assertEqual(notes._load()["notes"], [])
        self.assertEqual(self.runtime.turn("make a note that tea is good", {})["module"], "note_tools")
        self.assertEqual([n["text"] for n in notes._load()["notes"]], ["tea is good"])

    def test_the_bots_own_answers_stay(self):
        self.assertNotIn(self.runtime.turn("what's 15% of 240", {})["module"],
                         ("quick_tools", "local_tools", "note_tools"))


if __name__ == "__main__":
    unittest.main()
