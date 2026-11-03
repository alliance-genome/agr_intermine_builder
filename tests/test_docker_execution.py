"""Check command results through the real Docker SDK and a simulated daemon."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from docker.models.containers import Container

from src.intermine_builder.build_executor import BuildExecutionError, BuildExecutor
from src.intermine_builder.docker_manager import DockerManager
from src.intermine_builder.mine_config import MineType, get_mine_config


@pytest.fixture
def execution(monkeypatch):
    client = MagicMock()
    client.api.exec_create.return_value = {"Id": "exec-1"}
    client.api.exec_inspect.return_value = {"Running": False, "ExitCode": 0}
    monkeypatch.setattr("src.intermine_builder.docker_manager.docker.from_env", lambda: client)
    manager = DockerManager(Path.cwd())
    manager.containers[MineType.ALLIANCEMINE] = Container(
        attrs={"Id": "container-1", "Name": "/alliancemine-builder"}, client=client
    )
    return manager, client.api


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("exit_code", [0, 7])
def test_real_exit_status_and_both_output_streams(execution, stream, exit_code):
    manager, api = execution
    api.exec_inspect.return_value["ExitCode"] = exit_code
    output = (b"output\n", b"error\n")
    api.exec_start.return_value = iter([output]) if stream else output
    assert manager.execute_command(MineType.ALLIANCEMINE, "command", stream=stream) == (
        exit_code,
        "output\nerror\n",
    )


@pytest.mark.parametrize("stream", [False, True])
def test_empty_output(execution, stream):
    manager, api = execution
    api.exec_start.return_value = iter([]) if stream else (None, None)
    assert manager.execute_command(MineType.ALLIANCEMINE, "command", stream=stream) == (0, "")


def test_unicode_split_across_stream_chunks(execution):
    manager, api = execution
    api.exec_start.return_value = iter([(b"gene \xce", None), (b"\xb1\n", None)])
    assert manager.execute_command(MineType.ALLIANCEMINE, "command") == (0, "gene α\n")


def test_successful_gradle_stage_is_accepted(execution):
    manager, api = execution
    api.exec_start.return_value = iter([(b"BUILD SUCCESSFUL\n", None)])
    executor = BuildExecutor(manager, get_mine_config(MineType.ALLIANCEMINE))
    executor.stage_build_db()
    assert "Build Database Schema" in executor.stage_times


def test_failed_gradle_stage_is_rejected(execution):
    manager, api = execution
    api.exec_start.return_value = iter([(None, b"BUILD FAILED\n")])
    api.exec_inspect.return_value["ExitCode"] = 1
    executor = BuildExecutor(manager, get_mine_config(MineType.ALLIANCEMINE))
    with pytest.raises(BuildExecutionError):
        executor.stage_build_db()
