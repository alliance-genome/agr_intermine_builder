"""Failed attempts must survive aggregation and determine the CLI exit status."""

from argparse import Namespace
from unittest.mock import MagicMock

import pytest

from src.cli import build_mines
from src.intermine_builder.config import Config
from src.intermine_builder.mine_builder import MineBuilder
from src.intermine_builder.mine_config import MineType


@pytest.fixture
def builder(monkeypatch):
    monkeypatch.setattr("src.intermine_builder.docker_manager.docker.from_env", MagicMock())
    return MineBuilder(Config())


def failed_build(mine_type, **kwargs):
    raise RuntimeError("synthetic build failure")


def test_failed_attempt_is_in_summary(builder, monkeypatch):
    monkeypatch.setattr(builder, "build_mine", failed_build)
    summaries = builder.build_all_mines()
    assert len(summaries) == 1
    assert summaries[0]["mine_type"] == "alliancemine"
    assert summaries[0]["success"] is False
    assert summaries[0]["error"] == "synthetic build failure"


def test_continue_on_error_retains_every_attempt(builder, monkeypatch):
    def build(mine_type, **kwargs):
        if mine_type == MineType.ALLIANCEMINE:
            raise RuntimeError("synthetic build failure")
        return {"success": True, "mine_type": mine_type.value, "display_name": mine_type.value}

    monkeypatch.setattr(builder, "build_mine", build)
    summaries = builder.build_all_mines(stop_on_failure=False)
    assert len(summaries) == 4
    assert [s["success"] for s in summaries] == [False, True, True, True]


@pytest.mark.parametrize("continue_on_error", [False, True])
def test_cli_returns_failure_when_build_raises(builder, monkeypatch, capsys, continue_on_error):
    monkeypatch.setattr(builder, "build_mine", failed_build)
    monkeypatch.setattr(build_mines, "MineBuilder", lambda *args, **kwargs: builder)
    monkeypatch.setattr(build_mines.Config, "from_env", lambda: Config())
    args = Namespace(verbose=False, rebuild=False, continue_on_error=continue_on_error)
    assert build_mines.cmd_build_all(args) == 1
    assert "Built 0/0" not in capsys.readouterr().out
