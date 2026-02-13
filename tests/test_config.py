"""Tests for configuration module."""

import os
import pytest

from src.intermine_builder.config import (
    Config,
    DatabaseConfig,
    RDSConfig,
    DockerConfig,
    InterMineConfig,
    AllianceConfig,
    load_config,
)


class TestDatabaseConfig:
    def test_default_values(self):
        config = DatabaseConfig()
        assert config.user == "postgres"
        assert config.password == "postgres"
        assert config.host == "postgres"
        assert config.port == 5432

    def test_connection_string(self):
        config = DatabaseConfig(
            user="admin", password="secret", host="rds.example.com", port=5432
        )
        conn_str = config.connection_string("mydb")
        assert conn_str == "postgresql://admin:secret@rds.example.com:5432/mydb"

    def test_connection_string_default_db(self):
        config = DatabaseConfig(database="intermine")
        conn_str = config.connection_string()
        assert "intermine" in conn_str

    def test_field_name_is_user_not_username(self):
        """Regression: mine_builder.py was using .username instead of .user."""
        config = DatabaseConfig(user="myuser")
        assert config.user == "myuser"
        assert not hasattr(config, "username")


class TestConfigFromEnv:
    def test_loads_rds_env_vars(self, mock_env):
        config = Config.from_env()
        assert config.database.host == "test-rds.example.com"
        assert config.database.user == "testuser"
        assert config.database.password == "testpass"
        assert config.database.port == 5432

    def test_rds_vars_override_postgres_vars(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_USER", "pg_user")
        monkeypatch.setenv("RDS_USER", "rds_user")
        monkeypatch.setenv("RDS_PASSWORD", "pass")
        config = Config.from_env()
        assert config.database.user == "rds_user"

    def test_postgres_vars_fallback(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_USER", "pg_user")
        monkeypatch.setenv("RDS_PASSWORD", "pass")
        # No RDS_USER set
        monkeypatch.delenv("RDS_USER", raising=False)
        config = Config.from_env()
        assert config.database.user == "pg_user"

    def test_alliance_release(self, monkeypatch):
        monkeypatch.setenv("ALLIANCE_RELEASE", "9.0.0")
        monkeypatch.setenv("RDS_PASSWORD", "pass")
        config = Config.from_env()
        assert config.alliance.release_version == "9.0.0"

    def test_default_alliance_release(self, monkeypatch):
        monkeypatch.delenv("ALLIANCE_RELEASE", raising=False)
        monkeypatch.setenv("RDS_PASSWORD", "pass")
        config = Config.from_env()
        assert config.alliance.release_version == "8.3.0"

    def test_overrides(self, monkeypatch):
        monkeypatch.setenv("RDS_PASSWORD", "pass")
        config = Config.from_env(environment="production")
        assert config.environment == "production"

    def test_no_ec2_build_config(self):
        """Regression: EC2BuildConfig was removed."""
        config = Config()
        assert not hasattr(config, "ec2_build")


class TestConfigValidation:
    def test_valid_config(self):
        config = Config(
            database=DatabaseConfig(password="secret"),
            rds=RDSConfig(storage_gb=100),
        )
        is_valid, errors = config.validate()
        assert is_valid
        assert errors == []

    def test_empty_password_invalid(self):
        config = Config(database=DatabaseConfig(password=""))
        is_valid, errors = config.validate()
        assert not is_valid
        assert any("password" in e.lower() for e in errors)

    def test_small_storage_invalid(self):
        config = Config(
            database=DatabaseConfig(password="secret"),
            rds=RDSConfig(storage_gb=10),
        )
        is_valid, errors = config.validate()
        assert not is_valid
        assert any("storage" in e.lower() for e in errors)


class TestConfigToDict:
    def test_masks_password(self):
        config = Config(database=DatabaseConfig(password="supersecret"))
        d = config.to_dict()
        assert d["database"]["password"] == "***"


class TestLoadConfig:
    def test_convenience_function(self, mock_env):
        config = load_config()
        assert config.database.host == "test-rds.example.com"
