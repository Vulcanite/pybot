"""The fast checks of every status "pass" case in tests/phrasings.jsonl (see tests/phrasings.py).

    python -m unittest discover -s tests

The slow checks (a full bot turn per case) are not run here: `python tests/phrasings.py --slow`.
"""
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import phrasings  # noqa: E402


class Phrasings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = phrasings.load_cases()
        cls.scratch = phrasings.Scratch()
        cls.outcomes = phrasings.run(cls.cases, scratch=cls.scratch)

    @classmethod
    def tearDownClass(cls):
        cls.scratch.close()

    def test_the_file_is_well_formed(self):
        self.assertGreaterEqual(len(self.cases), 300)
        for group in phrasings.GROUPS:
            self.assertTrue(any(c["group"] == group for c in self.cases), group)

    def test_every_pass_case_passes(self):
        broken = [o for o in self.outcomes if o.case["status"] == "pass" and not o.ok and not o.skipped]
        if broken:
            out = io.StringIO()
            phrasings.report(broken, out=out)
            self.fail("%d phrasing cases fail:\n%s" % (len(broken), out.getvalue()))


if __name__ == "__main__":
    unittest.main()
