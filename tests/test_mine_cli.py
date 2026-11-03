"""Exercise the launcher at the process boundary without Docker or live services."""

import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
LAUNCHER = PROJECT / "mine"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    directory = tmp_path / "mine directory with spaces"
    directory.mkdir()
    (directory / "docker-compose.yml").write_text("services: {}\n")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    docker = binaries / "docker"
    helper = PROJECT / "tests/helpers/compose_command.py"
    docker.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(helper))} "$@"\n'
    )
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", f"{binaries}:{os.environ['PATH']}")
    monkeypatch.setenv("COMMAND_RECORD", str(tmp_path / "command.json"))
    monkeypatch.delenv("COMMAND_EXIT", raising=False)
    monkeypatch.delenv("COMMAND_WAIT", raising=False)
    return directory


def invoke(directory, *args):
    return subprocess.run(
        [sys.executable, "-S", "-B", str(LAUNCHER), "--directory", str(directory), *args],
        cwd=directory.parent,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def command(directory):
    return json.loads((directory.parent / "command.json").read_text())


def test_list_requires_no_dependencies_or_docker(tmp_path):
    result = invoke(tmp_path, "list")
    assert result.returncode == 0, result.stderr
    assert set(result.stdout.split()) == {
        "alliancemine",
        "flymine",
        "mousemine",
        "wormmine",
        "yeastmine",
    }


@pytest.mark.parametrize("mine", ["alliancemine", "flymine", "mousemine", "wormmine", "yeastmine"])
def test_image_uses_selected_compose_project(workspace, mine):
    result = invoke(workspace, mine, "image", "--no-cache")
    assert result.returncode == 0, result.stderr
    assert command(workspace)["args"] == [
        "compose",
        "--project-directory",
        str(workspace),
        "-f",
        str(workspace / "docker-compose.yml"),
        "build",
        "--no-cache",
        f"{mine}-builder",
    ]
    assert command(workspace)["cwd"] == str(workspace)


def test_build_keeps_rc_and_pipeline_arguments(workspace, monkeypatch):
    monkeypatch.setenv("RC_NUMBER", "21")
    result = invoke(workspace, "alliancemine", "build", "--start-from", "project_build", "--resume")
    assert result.returncode == 0, result.stderr
    assert command(workspace)["args"][-7:] == [
        "--rm",
        "-T",
        "alliancemine-builder",
        "build",
        "--start-from",
        "project_build",
        "--resume",
    ]
    assert command(workspace)["rc"] == "21"


def test_run_does_not_interpret_command_arguments(workspace):
    payload = '$(touch unwanted); spaces \' and "quotes"'
    result = invoke(workspace, "mousemine", "run", "printf", "%s", payload)
    assert result.returncode == 0, result.stderr
    assert command(workspace)["args"][-4:] == ["mousemine-builder", "printf", "%s", payload]
    assert not (workspace / "unwanted").exists()


def test_shell_preserves_interactive_input(workspace):
    result = invoke(workspace, "wormmine", "shell")
    assert result.returncode == 0, result.stderr
    assert command(workspace)["args"][-4:] == ["run", "--rm", "wormmine-builder", "bash"]
    assert not (workspace / "logs").exists()


def test_status_only_inspects_containers(workspace):
    result = invoke(workspace, "yeastmine", "status")
    assert result.returncode == 0, result.stderr
    assert command(workspace)["args"][-2:] == ["ps", "--all"]
    assert not (workspace / "logs").exists()


def test_compose_passthrough_preserves_service_and_options(workspace):
    result = invoke(workspace, "flymine", "compose", "exec", "-T", "chado-pg", "psql", "--version")
    assert result.returncode == 0, result.stderr
    assert command(workspace)["args"][-5:] == ["exec", "-T", "chado-pg", "psql", "--version"]
    assert not (workspace / "logs").exists()


def test_failed_build_retains_output_and_exit_code(workspace, monkeypatch):
    monkeypatch.setenv("COMMAND_EXIT", "17")
    result = invoke(workspace, "alliancemine", "build")
    assert result.returncode == 17, result.stderr
    log = (workspace / "logs/commands.log").read_text()
    assert "container stdout" in log and "container stderr" in log
    assert "container stdout" in result.stdout and "container stderr" in result.stdout
    inspection = invoke(workspace, "alliancemine", "logs")
    assert inspection.returncode == 0, inspection.stderr
    assert "container stderr" in inspection.stdout


def test_repeated_commands_keep_previous_logs(workspace):
    assert invoke(workspace, "alliancemine", "build").returncode == 0
    assert invoke(workspace, "alliancemine", "build").returncode == 0
    assert (workspace / "logs/commands.log").read_text().count("container stdout") == 2


def test_logs_do_not_require_compose_or_start_a_process(workspace):
    (workspace / "docker-compose.yml").unlink()
    (workspace / "logs").mkdir()
    (workspace / "logs/commands.log").write_text("previous build output\n")
    result = invoke(workspace, "alliancemine", "logs")
    assert result.returncode == 0, result.stderr
    assert "previous build output" in result.stdout
    assert not (workspace.parent / "command.json").exists()


def test_dry_run_has_no_side_effects(workspace):
    result = invoke(workspace, "--dry-run", "alliancemine", "build", "--resume")
    assert result.returncode == 0, result.stderr
    assert "--resume" in result.stdout and str(workspace) in result.stdout
    assert not (workspace / "logs").exists()
    assert not (workspace.parent / "command.json").exists()


@pytest.mark.parametrize(
    "args",
    [
        ("unknown", "image"),
        ("alliancemine",),
        ("alliancemine", "run"),
        ("mousemine", "build"),
        ("wormmine", "build"),
        ("flymine", "build", "--resume"),
        ("yeastmine", "build", "--publish"),
    ],
)
def test_invalid_or_unsupported_actions_fail_before_execution(workspace, args):
    result = invoke(workspace, *args)
    assert result.returncode == 2, result.stderr
    assert not (workspace.parent / "command.json").exists()


def test_missing_compose_file_fails_before_execution(workspace):
    (workspace / "docker-compose.yml").unlink()
    result = invoke(workspace, "alliancemine", "image")
    assert result.returncode == 2
    assert "docker-compose.yml" in result.stderr
    assert not (workspace.parent / "command.json").exists()


@pytest.mark.parametrize(
    "mine,script,variable,expected_args",
    [
        ("flymine", "scripts/build_release.sh", "FLYMINE_DIR", ""),
        ("yeastmine", "weekly/weekly_build.sh", "YM_DIR", "--no-publish"),
    ],
)
def test_host_pipeline_uses_selected_directory(workspace, mine, script, variable, expected_args):
    path = workspace / script
    path.parent.mkdir()
    path.write_text(f'printf "%s\\n" "${variable}" "$*"\nexit 23\n')
    result = invoke(workspace, mine, "build")
    assert result.returncode == 23, result.stderr
    assert str(workspace) in result.stdout
    if expected_args:
        assert expected_args in result.stdout
    assert not (workspace.parent / "command.json").exists()


def test_flymine_script_honors_explicit_build_directory(workspace):
    (workspace / ".env").write_text("printf 'selected build environment\\n'\nexit 39\n")
    result = subprocess.run(
        ["bash", str(PROJECT / "docker/flymine/scripts/build_release.sh")],
        env={**os.environ, "FLYMINE_DIR": str(workspace)},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 39, result.stderr
    assert "selected build environment" in result.stdout


def test_logging_failure_stops_before_build(workspace):
    (workspace / "logs").write_text("not a directory")
    result = invoke(workspace, "alliancemine", "build")
    assert result.returncode != 0
    assert not (workspace.parent / "command.json").exists()


def test_tee_failure_is_not_reported_as_build_success(workspace):
    tee = workspace.parent / "bin/tee"
    tee.write_text("#!/bin/sh\ncat >/dev/null\nexit 19\n")
    tee.chmod(0o755)
    result = invoke(workspace, "alliancemine", "build")
    assert result.returncode == 19
    assert command(workspace)["args"][-1] == "build"


def test_default_directory_is_independent_of_working_directory(tmp_path):
    result = subprocess.run(
        [sys.executable, "-S", str(LAUNCHER), "--dry-run", "alliancemine", "image"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert str(PROJECT / "docker/alliancemine") in result.stdout
    assert not (tmp_path / "logs").exists()


def test_interrupt_does_not_report_success(workspace, monkeypatch):
    monkeypatch.setenv("COMMAND_WAIT", "1")
    with subprocess.Popen(
        [
            sys.executable,
            "-S",
            str(LAUNCHER),
            "--directory",
            str(workspace),
            "alliancemine",
            "build",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    ) as process:
        deadline = time.monotonic() + 5
        record = workspace.parent / "command.json"
        while not record.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)
        process.communicate(timeout=5)
        assert record.exists(), "build command never started"
        assert process.returncode in (130, -signal.SIGINT)


@pytest.mark.parametrize("number", [signal.SIGINT, signal.SIGTERM, signal.SIGHUP])
def test_pid_cancellation_stops_the_build(workspace, monkeypatch, number):
    monkeypatch.setenv("COMMAND_WAIT", "1")
    process = subprocess.Popen(
        [
            sys.executable,
            "-S",
            str(LAUNCHER),
            "--directory",
            str(workspace),
            "alliancemine",
            "build",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    record = workspace.parent / "command.json"
    stopped = record.with_suffix(".stopped")
    child_pid = None
    try:
        deadline = time.monotonic() + 5
        while not record.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert record.exists(), "build never started"
        child_pid = json.loads(record.read_text())["pid"]
        process.send_signal(number)
        deadline = time.monotonic() + 2
        while not stopped.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert stopped.exists(), "cancellation left the build running"
        assert int(stopped.read_text()) == number
        assert process.wait(timeout=5) in (128 + number, -number)
    finally:
        if child_pid is not None and not stopped.exists():
            try:
                os.kill(child_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
