import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import create_solr_cores


def done(cmd, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


class CreateCoresTest(unittest.TestCase):
    def run_with(self, results):
        calls = []

        def run(cmd, input=None, **_):
            calls.append((cmd, input))
            return results.pop(0)

        with mock.patch.object(create_solr_cores.subprocess, "run", run):
            ok = create_solr_cores.create_cores("solr", "9.2.0", 1)
        return ok, calls

    def test_one_script_per_core_with_rc_names(self):
        ok, calls = self.run_with([done([], stdout="created"), done([], stdout="created")])
        self.assertTrue(ok)
        self.assertEqual([c[0][-3:] for c in calls], [["ec2-user@solr", "bash", "-s"]] * 2)
        self.assertIn("t=alliancemine-search-9.2.0-rc1", calls[0][1])
        self.assertIn("src=$D/alliancemine-autocomplete;", calls[1][1])

    def test_script_copies_conf_only_and_never_restarts_solr(self):
        _, calls = self.run_with([done([]), done([])])
        script = calls[0][1]
        self.assertIn('cp -r "$src/conf" "$D/$t/conf"', script)
        self.assertIn("action=CREATE&name=$t&instanceDir=$t", script)
        self.assertNotIn("restart", script)
        self.assertNotIn("core.properties\n", script.split("CREATE")[0].split("rm -rf")[1])

    def test_failure_on_one_core_still_tries_the_other(self):
        ok, calls = self.run_with([done([], 4, stderr="CREATE failed"), done([], stdout="exists")])
        self.assertFalse(ok)
        self.assertEqual(len(calls), 2)

    def test_script_is_valid_bash(self):
        script = create_solr_cores.CREATE_CORE_SH.format(data_dir="/d", source="s", target="t")
        self.assertEqual(subprocess.run(["bash", "-n"], input=script, text=True, check=False).returncode, 0)


if __name__ == "__main__":
    unittest.main()
