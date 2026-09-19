import unittest
from pathlib import Path

class TestReproCompositeFactorization(unittest.TestCase):
    def test_composite_actions_exist(self):
        self.assertTrue((Path(".github/actions/repro-runtime/action.yml")).exists())
        self.assertTrue((Path(".github/actions/repro-browser/action.yml")).exists())

if __name__ == "__main__":
    unittest.main()
