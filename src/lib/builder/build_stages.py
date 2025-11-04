"""Build stages for InterMine construction.

This module defines individual build stages that can be tracked and retried independently.
"""

import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any

from .exceptions import BuilderException, DataIntegrationError


class StageStatus(Enum):
    """Build stage status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StageResult:
    """Result of a build stage execution."""
    stage_name: str
    status: StageStatus
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

        if self.end_time and self.start_time:
            self.duration_seconds = (self.end_time - self.start_time).total_seconds()


class BuildStage:
    """Base class for build stages."""

    def __init__(self, name: str, logger: Optional[logging.Logger] = None):
        """
        Initialize build stage.

        Args:
            name: Stage name
            logger: Optional logger
        """
        self.name = name
        self.logger = logger or logging.getLogger(__name__)
        self.status = StageStatus.PENDING

    def execute(self) -> StageResult:
        """
        Execute the build stage.

        Returns:
            StageResult with execution details

        Raises:
            BuilderException: If stage fails
        """
        self.logger.info(f"Starting stage: {self.name}")
        start_time = datetime.now()
        self.status = StageStatus.RUNNING

        try:
            metadata = self._run()
            end_time = datetime.now()
            self.status = StageStatus.COMPLETED

            result = StageResult(
                stage_name=self.name,
                status=StageStatus.COMPLETED,
                start_time=start_time,
                end_time=end_time,
                metadata=metadata
            )

            self.logger.info(
                f"Stage completed: {self.name} "
                f"(duration: {result.duration_seconds:.1f}s)"
            )

            return result

        except Exception as e:
            end_time = datetime.now()
            self.status = StageStatus.FAILED
            error_msg = str(e)

            self.logger.error(f"Stage failed: {self.name} - {error_msg}")

            result = StageResult(
                stage_name=self.name,
                status=StageStatus.FAILED,
                start_time=start_time,
                end_time=end_time,
                error_message=error_msg
            )

            return result

    def _run(self) -> Dict[str, Any]:
        """
        Execute stage logic (override in subclass).

        Returns:
            Metadata dictionary

        Raises:
            BuilderException: If stage execution fails
        """
        raise NotImplementedError("Subclasses must implement _run()")


class ProjectBuildStage(BuildStage):
    """Stage for running project_build script."""

    def __init__(
        self,
        mine_dir: Path,
        dump_dir: Path,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize project build stage.

        Args:
            mine_dir: Mine project directory
            dump_dir: Data dump directory
            logger: Optional logger
        """
        super().__init__("project_build", logger)
        self.mine_dir = mine_dir
        self.dump_dir = dump_dir

    def _run(self) -> Dict[str, Any]:
        """Execute project_build script."""
        script_path = self.mine_dir / "project_build"

        if not script_path.exists():
            raise DataIntegrationError(f"project_build script not found: {script_path}")

        # Make executable
        script_path.chmod(0o755)

        cmd = [
            str(script_path),
            "-b",  # Build database
            "-T", "localhost",  # Target
            str(self.dump_dir)
        ]

        self.logger.info(f"Running: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                cwd=self.mine_dir,
                capture_output=True,
                text=True,
                timeout=18000,  # 5 hour timeout
                check=True
            )

            return {
                "command": " ".join(cmd),
                "exit_code": result.returncode
            }

        except subprocess.CalledProcessError as e:
            raise DataIntegrationError(
                f"project_build failed with exit code {e.returncode}\n{e.stderr}"
            ) from e

        except subprocess.TimeoutExpired as e:
            raise DataIntegrationError(
                "project_build timed out after 5 hours"
            ) from e


class ConfigurePropertiesStage(BuildStage):
    """Stage for configuring mine properties files."""

    def __init__(
        self,
        mine_dir: Path,
        mine_name: str,
        properties: Dict[str, str],
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize configure properties stage.

        Args:
            mine_dir: Mine project directory
            mine_name: Mine name
            properties: Property key-value pairs to set
            logger: Optional logger
        """
        super().__init__("configure_properties", logger)
        self.mine_dir = mine_dir
        self.mine_name = mine_name
        self.properties = properties

    def _run(self) -> Dict[str, Any]:
        """Configure mine properties."""
        import os

        # Create .intermine directory in home
        intermine_dir = Path.home() / ".intermine"
        intermine_dir.mkdir(exist_ok=True)

        properties_file = intermine_dir / f"{self.mine_name}.properties"

        self.logger.info(f"Configuring properties: {properties_file}")

        # Copy base properties if they exist
        base_properties = self.mine_dir / f"{self.mine_name}.properties"

        if base_properties.exists():
            import shutil
            shutil.copy(base_properties, properties_file)
            self.logger.info(f"Copied base properties from {base_properties}")
        else:
            # Create new file
            properties_file.touch()

        # Apply property overrides
        self._update_properties_file(properties_file, self.properties)

        return {
            "properties_file": str(properties_file),
            "num_properties": len(self.properties)
        }

    def _update_properties_file(
        self,
        properties_file: Path,
        updates: Dict[str, str]
    ) -> None:
        """Update properties file with new values."""
        # Read existing properties
        if properties_file.exists():
            with open(properties_file, 'r') as f:
                lines = f.readlines()
        else:
            lines = []

        # Apply updates
        updated_keys = set()

        for i, line in enumerate(lines):
            for key, value in updates.items():
                if line.startswith(f"{key}="):
                    lines[i] = f"{key}={value}\n"
                    updated_keys.add(key)
                    self.logger.debug(f"Updated property: {key}={value}")

        # Add new properties that weren't in file
        for key, value in updates.items():
            if key not in updated_keys:
                lines.append(f"{key}={value}\n")
                self.logger.debug(f"Added property: {key}={value}")

        # Write back
        with open(properties_file, 'w') as f:
            f.writelines(lines)

        self.logger.info(f"Updated {len(updates)} properties")


class UpdateSolrConfigStage(BuildStage):
    """Stage for updating Solr configuration."""

    def __init__(
        self,
        mine_dir: Path,
        solr_host: str,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize update Solr config stage.

        Args:
            mine_dir: Mine project directory
            solr_host: Solr hostname
            logger: Optional logger
        """
        super().__init__("update_solr_config", logger)
        self.mine_dir = mine_dir
        self.solr_host = solr_host

    def _run(self) -> Dict[str, Any]:
        """Update Solr configuration files."""
        config_files = [
            self.mine_dir / "dbmodel" / "resources" / "keyword_search.properties",
            self.mine_dir / "dbmodel" / "resources" / "objectstoresummary.config.properties"
        ]

        updated_files = []

        for config_file in config_files:
            if not config_file.exists():
                self.logger.warning(f"Config file not found: {config_file}")
                continue

            # Read file
            with open(config_file, 'r') as f:
                content = f.read()

            # Replace localhost with actual Solr host
            updated_content = content.replace('localhost', self.solr_host)

            # Write back
            with open(config_file, 'w') as f:
                f.write(updated_content)

            updated_files.append(str(config_file))
            self.logger.info(f"Updated Solr host to {self.solr_host} in {config_file}")

        return {
            "solr_host": self.solr_host,
            "files_updated": updated_files
        }


class UpdateGradleVersionsStage(BuildStage):
    """Stage for updating InterMine and Bio versions in gradle.properties."""

    def __init__(
        self,
        mine_dir: Path,
        im_version: Optional[str] = None,
        bio_version: Optional[str] = None,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize update gradle versions stage.

        Args:
            mine_dir: Mine project directory
            im_version: InterMine version (if custom build)
            bio_version: Bio version (if custom build)
            logger: Optional logger
        """
        super().__init__("update_gradle_versions", logger)
        self.mine_dir = mine_dir
        self.im_version = im_version
        self.bio_version = bio_version

    def _run(self) -> Dict[str, Any]:
        """Update gradle.properties with versions."""
        gradle_props = self.mine_dir / "gradle.properties"

        if not gradle_props.exists():
            self.logger.warning(f"gradle.properties not found: {gradle_props}")
            return {}

        # Read file
        with open(gradle_props, 'r') as f:
            lines = f.readlines()

        # Update versions
        updated = False

        for i, line in enumerate(lines):
            if self.im_version and line.startswith("systemProp.imVersion="):
                lines[i] = f"systemProp.imVersion={self.im_version}\n"
                self.logger.info(f"Updated imVersion to {self.im_version}")
                updated = True

            if self.bio_version and line.startswith("systemProp.bioVersion="):
                lines[i] = f"systemProp.bioVersion={self.bio_version}\n"
                self.logger.info(f"Updated bioVersion to {self.bio_version}")
                updated = True

        # Write back if updated
        if updated:
            with open(gradle_props, 'w') as f:
                f.writelines(lines)

        return {
            "im_version": self.im_version,
            "bio_version": self.bio_version,
            "updated": updated
        }
