"""Tests for mine configuration module."""

import os
import pytest

from src.intermine_builder.mine_config import (
    MineType,
    BuildStage,
    MineConfig,
    ResourceLimits,
    MINE_CONFIGS,
    get_mine_config,
    list_available_mines,
)


class TestMineType:
    def test_alliancemine_value(self):
        assert MineType.ALLIANCEMINE.value == "alliancemine"

    def test_all_mines_defined(self):
        assert len(MineType) == 4
        assert MineType.ALLIANCEMINE in MineType
        assert MineType.WORMMINE in MineType
        assert MineType.MOUSEMINE in MineType
        assert MineType.FLYMINE in MineType


class TestBuildStage:
    def test_all_stages(self):
        assert len(BuildStage) == 7
        stages = [s.value for s in BuildStage]
        assert "buildDB" in stages
        assert "extract_data" in stages
        assert "project_build" in stages
        assert "postprocess" in stages
        assert "buildUserDB" in stages
        assert "war" in stages
        assert "cargoRedeployRemote" in stages


class TestMineConfig:
    def test_docker_context_path(self):
        """Regression: was ./docker/multi_mine_rds/{mine}, now ./docker/{mine}."""
        config = MineConfig(
            mine_type=MineType.ALLIANCEMINE,
            display_name="AllianceMine",
            release_version="8.3.0",
            repo_url="https://example.com/repo.git",
            db_name="alliancemine_db",
            profile_db_name="alliancemine_profiles_db",
            resources=ResourceLimits(
                memory_gb=32, cpus=8, heap_size_gb=16, gradle_heap_gb=16
            ),
        )
        assert config.docker_context == "./docker/alliancemine"
        assert "multi_mine_rds" not in config.docker_context

    def test_docker_image_name(self):
        """Regression: was {mine}-rds:latest, now {mine}-builder:latest."""
        config = MineConfig(
            mine_type=MineType.ALLIANCEMINE,
            display_name="AllianceMine",
            release_version="8.3.0",
            repo_url="https://example.com/repo.git",
            db_name="alliancemine_db",
            profile_db_name="alliancemine_profiles_db",
            resources=ResourceLimits(
                memory_gb=32, cpus=8, heap_size_gb=16, gradle_heap_gb=16
            ),
        )
        assert config.docker_image == "alliancemine-builder:latest"

    def test_custom_docker_context(self):
        """Custom docker_context should not be overwritten."""
        config = MineConfig(
            mine_type=MineType.WORMMINE,
            display_name="WormMine",
            release_version="WS290",
            repo_url="https://example.com/repo.git",
            db_name="wormmine_db",
            profile_db_name="wormmine_profiles_db",
            resources=ResourceLimits(
                memory_gb=24, cpus=6, heap_size_gb=12, gradle_heap_gb=12
            ),
            docker_context="./docker/wormmine-custom",
        )
        assert config.docker_context == "./docker/wormmine-custom"


class TestAllianceMineConfig:
    def test_predefined_config_exists(self):
        config = MINE_CONFIGS[MineType.ALLIANCEMINE]
        assert config.mine_type == MineType.ALLIANCEMINE
        assert config.display_name == "AllianceMine"

    def test_release_version_from_env(self, monkeypatch):
        """Regression: was hardcoded '8.2.0', now reads ALLIANCE_RELEASE env."""
        monkeypatch.setenv("ALLIANCE_RELEASE", "9.1.0")
        # Need to reimport to pick up the new env var
        import importlib
        import src.intermine_builder.mine_config as mc

        importlib.reload(mc)
        # After reload, use the module's own MineType enum (not the imported one)
        config = mc.MINE_CONFIGS[mc.MineType.ALLIANCEMINE]
        assert config.release_version == "9.1.0"

        # Reset
        monkeypatch.delenv("ALLIANCE_RELEASE", raising=False)
        importlib.reload(mc)

    def test_resources(self):
        config = MINE_CONFIGS[MineType.ALLIANCEMINE]
        assert config.resources.memory_gb == 32
        assert config.resources.cpus == 8
        assert config.resources.gradle_heap_gb == 16

    def test_data_sources(self):
        config = MINE_CONFIGS[MineType.ALLIANCEMINE]
        source_names = [s.name for s in config.data_sources]
        assert "gene-basic" in source_names
        assert "allele" in source_names
        assert "disease" in source_names

    def test_tomcat_port(self):
        config = MINE_CONFIGS[MineType.ALLIANCEMINE]
        assert config.tomcat_port == 8080


class TestGetMineConfig:
    def test_get_alliancemine(self):
        # Ensure module is in a clean state (reload may have been called by earlier tests)
        import importlib
        import src.intermine_builder.mine_config as mc

        importlib.reload(mc)
        config = mc.get_mine_config(mc.MineType.ALLIANCEMINE)
        assert config.mine_type == mc.MineType.ALLIANCEMINE

    def test_get_wormmine(self):
        import importlib
        import src.intermine_builder.mine_config as mc

        importlib.reload(mc)
        config = mc.get_mine_config(mc.MineType.WORMMINE)
        assert config.mine_type == mc.MineType.WORMMINE
        assert config.use_custom_data is True

    def test_invalid_mine(self):
        import src.intermine_builder.mine_config as mc

        with pytest.raises(KeyError):
            mc.get_mine_config("nonexistent")


class TestListAvailableMines:
    def test_returns_all_mines(self):
        mines = list_available_mines()
        assert len(mines) == 4
        assert "alliancemine" in mines
        assert "wormmine" in mines
