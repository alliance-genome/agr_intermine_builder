"""Tests for build executor module."""

from unittest.mock import MagicMock, patch, call
import pytest

from src.intermine_builder.build_executor import BuildExecutor, BuildExecutionError
from src.intermine_builder.mine_config import (
    MineType,
    MineConfig,
    BuildStage,
    ResourceLimits,
    get_mine_config,
)
from src.intermine_builder.docker_manager import DockerManager


@pytest.fixture
def mock_docker_manager():
    """Create a mock DockerManager."""
    manager = MagicMock(spec=DockerManager)
    manager.execute_command.return_value = (0, "OK")
    return manager


@pytest.fixture
def alliancemine_executor(mock_docker_manager):
    """Create a BuildExecutor for AllianceMine."""
    config = get_mine_config(MineType.ALLIANCEMINE)
    return BuildExecutor(mock_docker_manager, config)


@pytest.fixture
def wormmine_executor(mock_docker_manager):
    """Create a BuildExecutor for WormMine."""
    config = get_mine_config(MineType.WORMMINE)
    return BuildExecutor(mock_docker_manager, config)


class TestBuildDB:
    def test_executes_gradle_builddb(self, alliancemine_executor, mock_docker_manager):
        alliancemine_executor.stage_build_db()
        mock_docker_manager.execute_command.assert_called_once()
        call_args = mock_docker_manager.execute_command.call_args
        assert "buildDB" in call_args[1].get("command", "") or "buildDB" in str(call_args)

    def test_workdir_alliancemine(self, alliancemine_executor, mock_docker_manager):
        alliancemine_executor.stage_build_db()
        call_args = mock_docker_manager.execute_command.call_args
        # Check workdir is /root/alliancemine
        assert call_args[1].get("workdir", "") == "/root/alliancemine" or \
               "/root/alliancemine" in str(call_args)

    def test_workdir_wormmine(self, wormmine_executor, mock_docker_manager):
        wormmine_executor.stage_build_db()
        call_args = mock_docker_manager.execute_command.call_args
        assert "/root/wormmine" in str(call_args)


class TestExtractData:
    def test_calls_python_script(self, alliancemine_executor, mock_docker_manager):
        """Regression: was /root/extract_data.sh, now python3 /root/scripts/extract_data.py."""
        alliancemine_executor.stage_extract_data()
        call_args = mock_docker_manager.execute_command.call_args
        cmd = str(call_args)
        assert "python3" in cmd
        assert "extract_data.py" in cmd
        assert "extract_data.sh" not in cmd

    def test_raises_on_failure(self, alliancemine_executor, mock_docker_manager):
        mock_docker_manager.execute_command.return_value = (1, "error")
        with pytest.raises(BuildExecutionError, match="Data extraction failed"):
            alliancemine_executor.stage_extract_data()


class TestProjectBuild:
    def test_calls_project_build(self, alliancemine_executor, mock_docker_manager):
        alliancemine_executor.stage_project_build()
        calls = mock_docker_manager.execute_command.call_args_list
        # Should call project_build with -b -T localhost
        project_build_call = [c for c in calls if "project_build" in str(c)]
        assert len(project_build_call) > 0

    def test_uses_correct_workdir(self, alliancemine_executor, mock_docker_manager):
        alliancemine_executor.stage_project_build()
        calls = mock_docker_manager.execute_command.call_args_list
        project_build_call = [c for c in calls if "project_build -b" in str(c)]
        assert any("/root/alliancemine" in str(c) for c in project_build_call)


class TestBuildUserDB:
    def test_skips_if_profile_exists(self, alliancemine_executor, mock_docker_manager):
        """Should skip buildUserDB if profile DB already exists."""
        mock_docker_manager.execute_command.return_value = (0, "1")
        alliancemine_executor.stage_build_user_db()
        # Should only call the check, not the buildUserDB gradle task
        calls = mock_docker_manager.execute_command.call_args_list
        assert len(calls) == 1  # Only the check command

    def test_creates_if_not_exists(self, alliancemine_executor, mock_docker_manager):
        """Should run buildUserDB if profile DB doesn't exist."""
        # First call (check) returns empty, second call (buildUserDB) succeeds
        mock_docker_manager.execute_command.side_effect = [
            (0, ""),  # Profile DB check - not found
            (0, "OK"),  # buildUserDB
        ]
        alliancemine_executor.stage_build_user_db()
        assert mock_docker_manager.execute_command.call_count == 2


class TestDeploy:
    def test_skips_if_tomcat_not_running(self, alliancemine_executor, mock_docker_manager):
        """Should skip deploy if Tomcat is not running."""
        mock_docker_manager.execute_command.return_value = (1, "")
        alliancemine_executor.stage_deploy()
        # Only the curl check should have been called
        assert mock_docker_manager.execute_command.call_count == 1

    def test_deploys_if_tomcat_running(self, alliancemine_executor, mock_docker_manager):
        """Should deploy if Tomcat is running."""
        mock_docker_manager.execute_command.return_value = (0, "OK")
        alliancemine_executor.stage_deploy()
        # curl check + cargoRedeployRemote
        assert mock_docker_manager.execute_command.call_count == 2


class TestFullBuild:
    def test_returns_summary(self, alliancemine_executor, mock_docker_manager):
        summary = alliancemine_executor.execute_full_build()
        assert summary["success"] is True
        assert summary["mine_type"] == "alliancemine"
        assert "completed_stages" in summary
        assert "total_duration_seconds" in summary

    def test_skip_stages(self, alliancemine_executor, mock_docker_manager):
        summary = alliancemine_executor.execute_full_build(
            skip_stages=[BuildStage.DEPLOY, BuildStage.BUILD_WAR]
        )
        assert summary["success"] is True
        assert "war" not in summary["completed_stages"]
        assert "cargoRedeployRemote" not in summary["completed_stages"]

    def test_failure_raises(self, alliancemine_executor, mock_docker_manager):
        mock_docker_manager.execute_command.return_value = (1, "error")
        with pytest.raises(BuildExecutionError):
            alliancemine_executor.execute_full_build()


class TestSingleStage:
    def test_execute_single_stage(self, alliancemine_executor, mock_docker_manager):
        alliancemine_executor.execute_single_stage(BuildStage.BUILD_DB)
        assert mock_docker_manager.execute_command.called

    def test_invalid_stage_raises(self, alliancemine_executor):
        # execute_single_stage expects a BuildStage enum, not a string
        # Passing None or a missing stage should raise
        with pytest.raises((ValueError, KeyError, AttributeError)):
            alliancemine_executor.execute_single_stage(None)


class TestProgressCallback:
    def test_callback_called(self, mock_docker_manager):
        callback = MagicMock()
        config = get_mine_config(MineType.ALLIANCEMINE)
        executor = BuildExecutor(mock_docker_manager, config, progress_callback=callback)
        executor.stage_build_db()
        assert callback.called
        # Should be called with stage name and progress values
        calls = callback.call_args_list
        assert any("buildDB" in str(c) for c in calls)
