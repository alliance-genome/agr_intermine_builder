import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import build_full

ENV = {"RDS_HOST": "rds", "RDS_USER": "u", "RDS_PORT": "5432"}


def done(cmd, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


class DropCheckpointsTest(unittest.TestCase):
    def test_drops_every_checkpoint(self):
        calls = []

        def run(cmd, **_):
            calls.append(cmd)
            return done(cmd, stdout="am_rc1:fbbt\nam_rc1:go-slim\n" if cmd[0] == "psql" else "")

        with mock.patch.dict(os.environ, ENV), mock.patch.object(build_full.subprocess, "run", run):
            build_full.drop_checkpoints("am_rc1")
        self.assertEqual([c[-1] for c in calls if c[0] == "dropdb"], ["am_rc1:fbbt", "am_rc1:go-slim"])

    def test_listing_failure_does_not_raise(self):
        def run(cmd, **_):
            self.assertEqual(cmd[0], "psql")
            return done(cmd, returncode=2, stderr="connection refused")

        with mock.patch.dict(os.environ, ENV), mock.patch.object(build_full.subprocess, "run", run):
            build_full.drop_checkpoints("am_rc1")

    def test_keep_all_checkpoints(self):
        run = mock.Mock()
        env = {**ENV, "KEEP_ALL_CHECKPOINTS": "true"}
        with mock.patch.dict(os.environ, env), mock.patch.object(build_full.subprocess, "run", run):
            build_full.drop_checkpoints("am_rc1")
        run.assert_not_called()


class CheckpointSshTest(unittest.TestCase):
    """checkpoint_ssh.sh with stub createdb/psql/dropdb that log their arguments."""

    def run_wrapper(self, *args, env=None):
        with TemporaryDirectory() as tmp:
            log = Path(tmp) / "log"
            for tool, out in [("createdb", ""), ("dropdb", ""), ("psql", "am_rc1:fbbt\n")]:
                stub = Path(tmp) / tool
                stub.write_text(f'#!/bin/sh\necho "{tool} $*" >> {log}\nprintf "{out}"\n')
                stub.chmod(0o755)
            subprocess.run(
                ["sh", str(SCRIPTS / "checkpoint_ssh.sh"), *args],
                env={"PATH": f"{tmp}:/usr/bin:/bin", **(env or {})},
                check=True, capture_output=True,
            )
            return log.read_text().splitlines()

    def test_drops_older_checkpoints_after_createdb(self):
        lines = self.run_wrapper("rds", "createdb", "-U", "u", "-h", "rds", "-T", "am_rc1", "am_rc1:go-slim")
        self.assertEqual(lines[0], "createdb -U u -h rds -T am_rc1 am_rc1:go-slim")
        self.assertIn("dropdb -U u -h rds am_rc1:fbbt", lines)

    def test_keep_all_checkpoints(self):
        lines = self.run_wrapper("rds", "createdb", "-U", "u", "-h", "rds", "-T", "am_rc1", "am_rc1:go-slim",
                                 env={"KEEP_ALL_CHECKPOINTS": "true"})
        self.assertEqual(lines, ["createdb -U u -h rds -T am_rc1 am_rc1:go-slim"])


if __name__ == "__main__":
    unittest.main()
