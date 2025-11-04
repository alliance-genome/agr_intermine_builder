"""InterMine Builder module.

This module provides a comprehensive Python-based build system for InterMine,
replacing the legacy bash scripts with testable, maintainable code.
"""

from .ec2_builder import EC2Builder, BuildContext
from .exceptions import (
    BuilderException,
    GitOperationError,
    GradleBuildError,
    DataIntegrationError,
    DeploymentError,
    HealthCheckError,
    ConfigurationError,
    TimeoutError
)
from .build_stages import StageStatus, StageResult

__all__ = [
    "EC2Builder",
    "BuildContext",
    "BuilderException",
    "GitOperationError",
    "GradleBuildError",
    "DataIntegrationError",
    "DeploymentError",
    "HealthCheckError",
    "ConfigurationError",
    "TimeoutError",
    "StageStatus",
    "StageResult",
]
