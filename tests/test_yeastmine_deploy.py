"""Execute deployment with local files and simulated AWS, Docker, and Solr."""

import hashlib
import json
import os
import shlex
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
NEW_DB = "yeastmine_1_rc2"
LIVE_DB = "yeastmine_1_rc1"


@pytest.fixture
def deployment(tmp_path):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    helper = PROJECT / "tests/helpers/yeastmine_commands.py"
    for command in ["aws", "curl", "docker", "flock", "sha256sum"]:
        path = binaries / command
        path.write_text(
            f"#!/bin/sh\nexec {shlex.quote(sys.executable)} -B "
            f'{shlex.quote(str(helper))} {command} "$@"\n'
        )
        path.chmod(0o755)
    (binaries / "python3").symlink_to(sys.executable)
    s3 = tmp_path / "s3"
    s3.mkdir()
    with zipfile.ZipFile(s3 / "new.war", "w") as archive:
        archive.writestr(
            "WEB-INF/classes/intermine.properties",
            f"db.production.datasource.databaseName={NEW_DB}\n",
        )
    ready = {
        "db": NEW_DB,
        "war": "s3://test/weekly/new.war",
        "sha256": hashlib.sha256((s3 / "new.war").read_bytes()).hexdigest(),
        "checks": {"ok": True},
    }
    (s3 / "ready.json").write_text(json.dumps(ready))
    (s3 / "live.json").write_text(json.dumps({"db": LIVE_DB}))
    (tmp_path / "live.war").write_bytes(b"previous WAR")
    (tmp_path / "cores.json").write_text(
        json.dumps({"search": "old", "autocomplete": "old", "calls": 0})
    )
    return tmp_path


def run_deploy(root, fail_swaps=(), fail_verify=False, manual=False):
    env = {
        **os.environ,
        "PATH": f"{root / 'bin'}:/usr/bin:/bin",
        "DEPLOY_TEST_ROOT": str(root),
        "STATE": str(root / "state"),
        "WAR": str(root / "live.war"),
        "S3": "s3://test/weekly",
        "SOLR": "http://fake-solr/solr",
        "FAIL_SWAPS": json.dumps(fail_swaps),
        "FAIL_VERIFY": str(int(fail_verify)),
    }
    result = subprocess.run(
        [
            "bash",
            str(PROJECT / "docker/yeastmine/weekly/deploy_agent.sh"),
            *(["--rollback"] if manual else []),
        ],
        check=False,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    cores = json.loads((root / "cores.json").read_text())
    status = json.loads((root / "state/last-deploy-status.json").read_text())
    return result, cores, status


@pytest.mark.parametrize("failed_swap", [1, 2])
def test_partial_swap_restores_original_indexes_and_war(deployment, failed_swap):
    result, cores, status = run_deploy(deployment, fail_swaps=[failed_swap])
    assert result.returncode == 1
    assert (cores["search"], cores["autocomplete"]) == ("old", "old")
    assert (deployment / "live.war").read_bytes() == b"previous WAR"
    assert status["state"] == "ROLLED_BACK"


def test_success_deploys_both_new_indexes_and_war(deployment):
    result, cores, status = run_deploy(deployment)
    assert result.returncode == 0
    assert (cores["search"], cores["autocomplete"]) == ("new", "new")
    assert (deployment / "live.war").read_bytes() == (deployment / "s3/new.war").read_bytes()
    assert json.loads((deployment / "s3/live.json").read_text())["db"] == NEW_DB
    assert status["state"] == "DEPLOYED"


def test_verification_failure_restores_previous_deployment(deployment):
    result, cores, status = run_deploy(deployment, fail_verify=True)
    assert result.returncode == 1
    assert (cores["search"], cores["autocomplete"]) == ("old", "old")
    assert (deployment / "live.war").read_bytes() == b"previous WAR"
    assert status["state"] == "ROLLED_BACK"


def test_failed_reversal_is_not_reported_as_successful_rollback(deployment):
    result, _, status = run_deploy(deployment, fail_swaps=[2, 3])
    assert result.returncode == 1
    assert status["state"] == "ROLLBACK_FAILED"


@pytest.mark.parametrize("fail_swaps,fail_verify", [([2], False), ([], True)])
def test_failed_manual_rollback_restores_current_deployment(deployment, fail_swaps, fail_verify):
    state = deployment / "state"
    state.mkdir()
    (state / "rollback.war").write_bytes(b"older WAR")
    (state / "previous-live.json").write_text(json.dumps({"db": "yeastmine_1_rc0"}))
    result, cores, status = run_deploy(
        deployment, fail_swaps=fail_swaps, fail_verify=fail_verify, manual=True
    )
    assert result.returncode == 1
    assert (cores["search"], cores["autocomplete"]) == ("old", "old")
    assert (deployment / "live.war").read_bytes() == b"previous WAR"
    assert status["state"] == "ROLLBACK_FAILED"
