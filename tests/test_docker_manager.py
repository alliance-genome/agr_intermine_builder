"""Tests for Docker manager module."""

from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path
import pytest

from src.intermine_builder.docker_manager import DockerManager
from src.intermine_builder.mine_config import (
    MineType,
    MineConfig,
    ResourceLimits,
    get_mine_config,
)


@pytest.fixture
def docker_manager(mock_docker_client, tmp_path):
    """Create a DockerManager with mocked Docker client."""
    import docker.errors

    with patch("src.intermine_builder.docker_manager.docker") as mock_docker:
        mock_docker.from_env.return_value = mock_docker_client
        mock_docker.errors = docker.errors
        manager = DockerManager(tmp_path)
        manager.client = mock_docker_client
        return manager


class TestBuildImage:
    def test_skips_if_exists(self, docker_manager, mock_docker_client):
        """Should skip build if image already exists."""
        existing_image = MagicMock()
        mock_docker_client.images.get = MagicMock(return_value=existing_image)

        config = get_mine_config(MineType.ALLIANCEMINE)
        # Create the docker context directory
        context_path = docker_manager.base_dir / config.docker_context
        context_path.mkdir(parents=True)

        result = docker_manager.build_image(config)
        assert result == existing_image
        mock_docker_client.images.build.assert_not_called()

    def test_builds_if_not_exists(self, docker_manager, mock_docker_client):
        """Should build if image doesn't exist."""
        import docker.errors as docker_errors

        mock_docker_client.images.get.side_effect = docker_errors.ImageNotFound("not found")

        config = get_mine_config(MineType.ALLIANCEMINE)
        context_path = docker_manager.base_dir / config.docker_context
        context_path.mkdir(parents=True)

        docker_manager.build_image(config)
        mock_docker_client.images.build.assert_called_once()

    def test_force_rebuild(self, docker_manager, mock_docker_client):
        """Should rebuild even if image exists when force_rebuild=True."""
        existing_image = MagicMock()
        mock_docker_client.images.get.return_value = existing_image

        config = get_mine_config(MineType.ALLIANCEMINE)
        context_path = docker_manager.base_dir / config.docker_context
        context_path.mkdir(parents=True)

        docker_manager.build_image(config, force_rebuild=True)
        mock_docker_client.images.build.assert_called_once()


class TestCreateContainer:
    def test_sets_env_vars(self, docker_manager, mock_docker_client):
        config = get_mine_config(MineType.ALLIANCEMINE)
        docker_manager.create_container(
            config,
            rds_host="rds.example.com",
            rds_port=5432,
            rds_user="admin",
            rds_password="secret",
        )

        call_kwargs = mock_docker_client.containers.create.call_args[1]
        env = call_kwargs["environment"]
        assert env["RDS_HOST"] == "rds.example.com"
        assert env["RDS_PORT"] == "5432"
        assert env["RDS_USER"] == "admin"
        assert env["RDS_PASSWORD"] == "secret"

    def test_sets_alliance_release(self, docker_manager, mock_docker_client):
        config = get_mine_config(MineType.ALLIANCEMINE)
        docker_manager.create_container(
            config,
            rds_host="host",
            rds_port=5432,
            rds_user="user",
            rds_password="pass",
        )

        call_kwargs = mock_docker_client.containers.create.call_args[1]
        env = call_kwargs["environment"]
        assert "ALLIANCE_RELEASE" in env

    def test_container_naming(self, docker_manager, mock_docker_client):
        config = get_mine_config(MineType.ALLIANCEMINE)
        docker_manager.create_container(
            config,
            rds_host="host",
            rds_port=5432,
            rds_user="user",
            rds_password="pass",
        )

        call_kwargs = mock_docker_client.containers.create.call_args[1]
        assert call_kwargs["name"] == "alliancemine-builder"

    def test_resource_limits(self, docker_manager, mock_docker_client):
        config = get_mine_config(MineType.ALLIANCEMINE)
        docker_manager.create_container(
            config,
            rds_host="host",
            rds_port=5432,
            rds_user="user",
            rds_password="pass",
        )

        call_kwargs = mock_docker_client.containers.create.call_args[1]
        assert call_kwargs["mem_limit"] == "32g"
        assert call_kwargs["cpu_count"] == 8


class TestContainerLifecycle:
    def test_start_container(self, docker_manager, mock_docker_client):
        config = get_mine_config(MineType.ALLIANCEMINE)
        container = docker_manager.create_container(
            config, rds_host="h", rds_port=5432, rds_user="u", rds_password="p"
        )
        docker_manager.start_container(MineType.ALLIANCEMINE)
        docker_manager.containers[MineType.ALLIANCEMINE].start.assert_called_once()

    def test_stop_container(self, docker_manager, mock_docker_client):
        config = get_mine_config(MineType.ALLIANCEMINE)
        docker_manager.create_container(
            config, rds_host="h", rds_port=5432, rds_user="u", rds_password="p"
        )
        docker_manager.stop_container(MineType.ALLIANCEMINE)
        docker_manager.containers[MineType.ALLIANCEMINE].stop.assert_called_once()

    def test_start_nonexistent_raises(self, docker_manager):
        with pytest.raises(ValueError, match="No container found"):
            docker_manager.start_container(MineType.ALLIANCEMINE)

    def test_status_not_created(self, docker_manager):
        status = docker_manager.get_container_status(MineType.ALLIANCEMINE)
        assert status == "not_created"


class TestExecuteCommand:
    def test_execute_in_container(self, docker_manager, mock_docker_client, mock_container):
        docker_manager.containers[MineType.ALLIANCEMINE] = mock_container
        exit_code, output = docker_manager.execute_command(
            MineType.ALLIANCEMINE,
            "echo hello",
            workdir="/root",
            stream=False,
        )
        mock_container.exec_run.assert_called_once()

    def test_execute_nonexistent_raises(self, docker_manager):
        with pytest.raises(ValueError, match="No container found"):
            docker_manager.execute_command(MineType.ALLIANCEMINE, "echo hello")


class TestNetwork:
    def test_creates_network(self, docker_manager, mock_docker_client):
        import docker.errors as docker_errors

        mock_docker_client.networks.get.side_effect = docker_errors.NotFound("not found")
        docker_manager.create_network()
        mock_docker_client.networks.create.assert_called_once()

    def test_skips_existing_network(self, docker_manager, mock_docker_client):
        mock_docker_client.networks.get.return_value = MagicMock()
        mock_docker_client.networks.get.side_effect = None
        docker_manager.create_network()
        mock_docker_client.networks.create.assert_not_called()


class TestCleanup:
    def test_cleanup_all(self, docker_manager, mock_docker_client):
        config = get_mine_config(MineType.ALLIANCEMINE)
        docker_manager.create_container(
            config, rds_host="h", rds_port=5432, rds_user="u", rds_password="p"
        )
        docker_manager.cleanup()
        # Should have stopped and removed the container
        container = docker_manager.containers.get(MineType.ALLIANCEMINE)
        # Container should be removed from dict
        assert MineType.ALLIANCEMINE not in docker_manager.containers

    def test_context_manager(self, docker_manager, mock_docker_client):
        config = get_mine_config(MineType.ALLIANCEMINE)
        with docker_manager:
            docker_manager.create_container(
                config, rds_host="h", rds_port=5432, rds_user="u", rds_password="p"
            )
        # After context exit, cleanup should have been called
        assert MineType.ALLIANCEMINE not in docker_manager.containers
