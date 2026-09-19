import unittest
import subprocess

class TestReproCompositeFactorization(unittest.TestCase):
    def test_audit_tool(self):
        result = subprocess.run(['python3', 'tools/audit_repro_composite_factorization.py'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, f"Audit tool failed: {result.stderr}")

if __name__ == '__main__':
    unittest.main()
