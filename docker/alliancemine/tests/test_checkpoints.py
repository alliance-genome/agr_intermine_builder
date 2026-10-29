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

    def test_single_string_command_runs_in_a_shell(self):
        lines = self.run_wrapper("rds", "createdb -U u -h rds am_rc1")
        self.assertEqual(lines, ["createdb -U u -h rds am_rc1"])

    def test_project_build_goes_through_the_wrapper(self):
        # project_build skips ssh (and so the pruning) when the dump host is "localhost"
        self.assertNotEqual(build_full.DUMP_HOST, "localhost")

    def test_option_or_user_at_host_calls_go_to_real_ssh(self):
        for args in [("-i", "k.pem", "-o", "ConnectTimeout=10", "ec2-user@solr", "bash", "-s"),
                     ("ec2-user@solr", "ls")]:
            with TemporaryDirectory() as tmp:
                real = Path(tmp) / "realssh"
                real.write_text(f'#!/bin/sh\necho "$*" > {tmp}/log\n')
                real.chmod(0o755)
                subprocess.run(["sh", str(SCRIPTS / "checkpoint_ssh.sh"), *args],
                               env={"PATH": "/usr/bin:/bin", "SSH_REAL": str(real)},
                               check=True, capture_output=True)
                self.assertEqual((Path(tmp) / "log").read_text().split(), list(args))


class PreflightSolrTest(unittest.TestCase):
    def pipeline(self):
        with mock.patch.object(build_full, "ALLIANCEMINE_DIR", Path(".")):
            return build_full.AllianceMineBuildPipeline(release="9.2.0", rc=1)

    def test_failed_core_creation_is_fatal_when_solr_host_set(self):
        with mock.patch.dict(os.environ, {"SOLR_HOST": "solr"}), \
                mock.patch("create_solr_cores.create_cores", return_value=False):
            self.assertFalse(self.pipeline().preflight_solr())

    def test_exception_is_fatal_when_solr_host_set(self):
        with mock.patch.dict(os.environ, {"SOLR_HOST": "solr"}), \
                mock.patch("create_solr_cores.create_cores", side_effect=OSError("no ssh")):
            self.assertFalse(self.pipeline().preflight_solr())

    def test_created_cores_pass(self):
        with mock.patch.dict(os.environ, {"SOLR_HOST": "solr"}), \
                mock.patch("create_solr_cores.create_cores", return_value=True):
            self.assertTrue(self.pipeline().preflight_solr())

    def test_unset_solr_host_skips(self):
        env = {k: v for k, v in os.environ.items() if k != "SOLR_HOST"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(self.pipeline().preflight_solr())


class BuildDbTargetTest(unittest.TestCase):
    def check(self, props, results, rds_db="am_rc2"):
        calls = []

        def run(cmd, **_):
            calls.append(cmd)
            return results.pop(0)

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.properties"
            path.write_text(props)
            with mock.patch.dict(os.environ, {**ENV, "RDS_DB_NAME": rds_db}), \
                    mock.patch.object(build_full, "PROPERTIES_FILE", path), \
                    mock.patch.object(build_full.subprocess, "run", run):
                return build_full.check_build_db_target(), calls

    NAME = "db.production.datasource.databaseName=am_rc2\n"

    def test_name_mismatch_stops_before_any_query(self):
        problem, calls = self.check("db.production.datasource.databaseName=am_rc18\n", [])
        self.assertIn("am_rc18", problem)
        self.assertIn("am_rc2", problem)
        self.assertEqual(calls, [])

    def test_missing_database_is_fine(self):
        problem, _ = self.check(self.NAME, [done([], stdout="")])
        self.assertIsNone(problem)

    def test_empty_database_is_fine(self):
        problem, _ = self.check(self.NAME, [done([], stdout="1\n"), done([], stdout="0\n")])
        self.assertIsNone(problem)

    def test_database_with_tables_is_refused(self):
        problem, _ = self.check(self.NAME, [done([], stdout="1\n"), done([], stdout="412\n")])
        self.assertIn("412 tables", problem)

    def test_psql_error_is_refused(self):
        problem, _ = self.check(self.NAME, [done([], 2, stderr="timeout")])
        self.assertIn("timeout", problem)


if __name__ == "__main__":
    unittest.main()
