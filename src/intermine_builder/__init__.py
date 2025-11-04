"""
InterMine Builder Package

Provides Python-based orchestration for building InterMine instances in Docker containers.

Main components:
- MineBuilder: Main orchestrator
- DockerManager: Docker container lifecycle management
- BuildExecutor: Build stage execution
- MineConfig: Mine configuration and settings
"""

from .mine_builder import MineBuilder
from .docker_manager import DockerManager
from .build_executor import BuildExecutor, BuildExecutionError
from .mine_config import (
    MineConfig,
    MineType,
    BuildStage,
    DataSource,
    ResourceLimits,
    get_mine_config,
    list_available_mines,
    MINE_CONFIGS,
)

__all__ = [
    'MineBuilder',
    'DockerManager',
    'BuildExecutor',
    'BuildExecutionError',
    'MineConfig',
    'MineType',
    'BuildStage',
    'DataSource',
    'ResourceLimits',
    'get_mine_config',
    'list_available_mines',
    'MINE_CONFIGS',
]
