"""Runs the profile service's own tests (worker/test, written for Node's built-in runner) as part of the
normal suite, so one command and one CI job cover everything. Skipped when Node isn't installed."""
import glob
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKER = os.path.join(ROOT, "worker")
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node is not installed")
class ProfileService(unittest.TestCase):
    def test_worker_tests_pass(self):
        files = sorted(glob.glob(os.path.join(WORKER, "test", "*.test.mjs")))
        self.assertTrue(files, "no worker tests found")
        run = subprocess.run([NODE, "--test"] + files, cwd=WORKER, capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stdout[-3000:] + run.stderr[-1000:])


if __name__ == "__main__":
    unittest.main()
