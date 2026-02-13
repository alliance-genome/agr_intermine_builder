"""Shared test fixtures for AGR InterMine Builder tests."""

import os
from unittest.mock import MagicMock, patch
import pytest

from src.intermine_builder.config import Config, DatabaseConfig
from src.intermine_builder.mine_config import MineType, MineConfig, get_mine_config


@pytest.fixture
def mock_env(monkeypatch):
    """Set up test environment variables."""
    env_vars = {
        "RDS_HOST": "test-rds.example.com",
        "RDS_PORT": "5432",
        "RDS_USER": "testuser",
        "RDS_PASSWORD": "testpass",
        "ALLIANCE_RELEASE": "8.3.0",
    }
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)
    return env_vars


@pytest.fixture
def test_db_config():
    """Create a test DatabaseConfig."""
    return DatabaseConfig(
        user="testuser",
        password="testpass",
        host="test-rds.example.com",
        port=5432,
        database="intermine",
    )


@pytest.fixture
def test_config(test_db_config):
    """Create a test Config."""
    return Config(database=test_db_config)


@pytest.fixture
def alliancemine_config():
    """Get AllianceMine configuration."""
    return get_mine_config(MineType.ALLIANCEMINE)


@pytest.fixture
def mock_docker_client():
    """Create a mock Docker client."""
    import docker.errors

    client = MagicMock()
    client.images.get.side_effect = docker.errors.ImageNotFound("not found")
    client.images.build.return_value = (MagicMock(), [])
    client.containers.create.return_value = MagicMock(name="test-container")
    client.networks.get.side_effect = docker.errors.NotFound("not found")
    client.networks.create.return_value = MagicMock()
    return client


@pytest.fixture
def mock_container():
    """Create a mock Docker container."""
    container = MagicMock()
    container.name = "alliancemine-builder"
    container.status = "running"

    # Mock exec_run for command execution
    exec_result = MagicMock()
    exec_result.exit_code = 0
    exec_result.output = b"OK"
    container.exec_run.return_value = exec_result

    return container
