"""EC2Builder - Main orchestrator for InterMine builds on EC2.

This module replaces build.sh with a comprehensive Python-based build system.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from ..config import Config
from .exceptions import BuilderException, ConfigurationError
from .git_operations import GitOperations
from .gradle_operations import GradleOperations
from .build_stages import (
    StageResult,
    StageStatus,
    ConfigurePropertiesStage,
    UpdateSolrConfigStage,
    UpdateGradleVersionsStage,
    ProjectBuildStage
)


@dataclass
class BuildContext:
    """Context for a build execution."""
    build_id: str
    mine_name: str
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    status: str = "running"
    stage_results: List[StageResult] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> Optional[float]:
        """Get build duration in seconds."""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return (datetime.now() - self.start_time).total_seconds()

    @property
    def completed_stages(self) -> int:
        """Count completed stages."""
        return sum(1 for r in self.stage_results if r.status == StageStatus.COMPLETED)

    @property
    def failed_stages(self) -> int:
        """Count failed stages."""
        return sum(1 for r in self.stage_results if r.status == StageStatus.FAILED)


class EC2Builder:
    """
    Main InterMine builder for EC2 instances.

    This class orchestrates the entire build process:
    1. Clone repositories (InterMine, Mine, Bio-sources)
    2. Build InterMine core components
    3. Build bio-sources
    4. Configure mine properties
    5. Run project_build (data integration)
    6. Build and deploy webapp

    Example:
        ```python
        from src.lib.config import load_config
        from src.lib.builder.ec2_builder import EC2Builder

        config = load_config()
        builder = EC2Builder(config)

        # Full build
        result = builder.build_full(
            mine_name="alliancemine",
            build_id="build-20250103-001"
        )

        print(f"Build status: {result.status}")
        print(f"Duration: {result.duration_seconds / 3600:.1f} hours")
        ```
    """

    def __init__(self, config: Config, logger: Optional[logging.Logger] = None):
        """
        Initialize EC2 Builder.

        Args:
            config: Configuration instance
            logger: Optional logger
        """
        self.config = config
        self.logger = logger or logging.getLogger(__name__)

        # Set up build directories
        self.build_root = Path(config.intermine.build_dir)
        self.build_root.mkdir(parents=True, exist_ok=True)

        self.data_dir = Path(config.intermine.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Initialize operation handlers
        self.git_ops = GitOperations(self.build_root, self.logger)
        self.gradle_ops = GradleOperations(
            heap_size_gb=config.ec2_build.gradle_heap_gb,
            logger=self.logger
        )

        # Build context
        self.context: Optional[BuildContext] = None

        self.logger.info("EC2Builder initialized")
        self.logger.info(f"Build root: {self.build_root}")
        self.logger.info(f"Data directory: {self.data_dir}")

    def build_full(
        self,
        mine_name: str,
        build_id: str,
        skip_intermine_build: bool = False,
        skip_biosources_build: bool = False
    ) -> BuildContext:
        """
        Execute a full mine build.

        Args:
            mine_name: Name of mine to build
            build_id: Unique build identifier
            skip_intermine_build: Skip building InterMine core
            skip_biosources_build: Skip building bio-sources

        Returns:
            BuildContext with results

        Raises:
            BuilderException: If build fails
        """
        self.logger.info(f"Starting full build: {mine_name} ({build_id})")

        # Initialize build context
        self.context = BuildContext(
            build_id=build_id,
            mine_name=mine_name
        )

        try:
            # Stage 1: Clone repositories
            self._stage_clone_repositories()

            # Stage 2: Build InterMine core (optional)
            if not skip_intermine_build and self._should_build_intermine():
                self._stage_build_intermine_core()

            # Stage 3: Build bio-sources (optional)
            if not skip_biosources_build and self.config.intermine.biosources_repo_url:
                self._stage_build_biosources()

            # Stage 4: Configure mine
            self._stage_configure_mine()

            # Stage 5: Run project_build (data integration)
            self._stage_run_project_build()

            # Stage 6: Build and deploy webapp
            self._stage_build_webapp()

            # Mark as completed
            self.context.status = "completed"
            self.context.end_time = datetime.now()

            self.logger.info(
                f"Build completed successfully: {mine_name} "
                f"(duration: {self.context.duration_seconds / 3600:.1f} hours)"
            )

            return self.context

        except Exception as e:
            self.context.status = "failed"
            self.context.end_time = datetime.now()
            self.context.metadata["error"] = str(e)

            self.logger.error(f"Build failed: {mine_name} - {e}")
            raise BuilderException(f"Build failed: {e}") from e

    def _should_build_intermine(self) -> bool:
        """Determine if InterMine core should be built."""
        return bool(
            self.config.intermine.intermine_repo_url or
            self.config.intermine.intermine_branch != "master"
        )

    def _stage_clone_repositories(self) -> None:
        """Clone all required repositories."""
        self.logger.info("=== Stage: Clone Repositories ===")

        # Clone InterMine (if needed)
        if self._should_build_intermine():
            self.logger.info("Cloning InterMine repository")
            intermine_dir = self.git_ops.clone(
                repo_url=self.config.intermine.intermine_repo_url,
                target_dir="intermine",
                branch=self.config.intermine.intermine_branch
            )
            self.context.metadata["intermine_dir"] = str(intermine_dir)

        # Clone mine repository
        self.logger.info(f"Cloning {self.context.mine_name} repository")
        mine_dir = self.git_ops.clone(
            repo_url=self.config.intermine.mine_repo_url,
            target_dir=self.context.mine_name,
            branch=self.config.intermine.mine_branch
        )
        self.context.metadata["mine_dir"] = str(mine_dir)

        # Clone bio-sources (if configured)
        if self.config.intermine.biosources_repo_url:
            self.logger.info("Cloning bio-sources repository")
            biosources_dir = self.git_ops.clone(
                repo_url=self.config.intermine.biosources_repo_url,
                target_dir=f"{self.context.mine_name}-bio-sources",
                branch=self.config.intermine.biosources_branch
            )
            self.context.metadata["biosources_dir"] = str(biosources_dir)

    def _stage_build_intermine_core(self) -> None:
        """Build InterMine core components."""
        self.logger.info("=== Stage: Build InterMine Core ===")

        intermine_dir = Path(self.context.metadata["intermine_dir"])

        # Build core
        self.gradle_ops.build_intermine_core(intermine_dir)

        # Extract versions
        im_version = self.gradle_ops.get_version(intermine_dir / "intermine" / "build.gradle")
        bio_version = self.gradle_ops.get_version(intermine_dir / "bio" / "build.gradle")

        self.context.metadata["im_version"] = im_version
        self.context.metadata["bio_version"] = bio_version

        self.logger.info(f"InterMine version: {im_version}")
        self.logger.info(f"Bio version: {bio_version}")

    def _stage_build_biosources(self) -> None:
        """Build bio-sources."""
        self.logger.info("=== Stage: Build Bio-sources ===")

        biosources_dir = Path(self.context.metadata["biosources_dir"])
        self.gradle_ops.build_biosources(biosources_dir)

    def _stage_configure_mine(self) -> None:
        """Configure mine properties and settings."""
        self.logger.info("=== Stage: Configure Mine ===")

        mine_dir = Path(self.context.metadata["mine_dir"])

        # Stage 4.1: Update Solr configuration
        update_solr = UpdateSolrConfigStage(
            mine_dir=mine_dir,
            solr_host=self.config.intermine.solr_host,
            logger=self.logger
        )
        result = update_solr.execute()
        self.context.stage_results.append(result)

        if result.status == StageStatus.FAILED:
            raise BuilderException(f"Failed to update Solr config: {result.error_message}")

        # Stage 4.2: Update Gradle versions (if custom InterMine build)
        if "im_version" in self.context.metadata:
            update_versions = UpdateGradleVersionsStage(
                mine_dir=mine_dir,
                im_version=self.context.metadata.get("im_version"),
                bio_version=self.context.metadata.get("bio_version"),
                logger=self.logger
            )
            result = update_versions.execute()
            self.context.stage_results.append(result)

        # Stage 4.3: Configure properties
        properties = self._build_properties_dict()

        configure_props = ConfigurePropertiesStage(
            mine_dir=mine_dir,
            mine_name=self.context.mine_name,
            properties=properties,
            logger=self.logger
        )
        result = configure_props.execute()
        self.context.stage_results.append(result)

        if result.status == StageStatus.FAILED:
            raise BuilderException(f"Failed to configure properties: {result.error_message}")

    def _build_properties_dict(self) -> Dict[str, str]:
        """Build properties dictionary for mine configuration."""
        db_config = self.config.database
        im_config = self.config.intermine

        # Build connection strings
        db_host = f"{db_config.host}:{db_config.port}"

        properties = {
            # Database - production
            "db.production.datasource.serverName": db_host,
            "db.production.datasource.databaseName": f"{self.context.mine_name}_db",
            "db.production.datasource.user": db_config.user,
            "db.production.datasource.password": db_config.password,
            "db.production.driver": "org.postgresql.Driver",
            "db.production.platform": "PostgreSQL",

            # Database - common target items
            "db.common-tgt-items.datasource.serverName": db_host,
            "db.common-tgt-items.datasource.databaseName": f"{self.context.mine_name}_db",
            "db.common-tgt-items.datasource.user": db_config.user,
            "db.common-tgt-items.datasource.password": db_config.password,
            "db.common-tgt-items.driver": "org.postgresql.Driver",
            "db.common-tgt-items.platform": "PostgreSQL",

            # Database - user profile
            "db.userprofile-production.datasource.serverName": db_host,
            "db.userprofile-production.datasource.databaseName": f"{self.context.mine_name}_profiles_db",
            "db.userprofile-production.datasource.user": db_config.user,
            "db.userprofile-production.datasource.password": db_config.password,
            "db.userprofile-production.driver": "org.postgresql.Driver",
            "db.userprofile-production.platform": "PostgreSQL",

            # Tomcat deployment
            "webapp.manager": im_config.tomcat_user,
            "webapp.password": im_config.tomcat_password,
            "webapp.deploy.url": f"http://{im_config.tomcat_host}:{im_config.tomcat_port}",
            "webapp.baseurl": f"http://{im_config.tomcat_host}:{im_config.tomcat_port}",
            "project.sitePrefix": f"http://{im_config.tomcat_host}:{im_config.tomcat_port}",

            # Project info
            "project.releaseVersion": self.config.alliance.release_version,
        }

        return properties

    def _stage_run_project_build(self) -> None:
        """Run project_build for data integration."""
        self.logger.info("=== Stage: Run Project Build (Data Integration) ===")

        mine_dir = Path(self.context.metadata["mine_dir"])
        dump_dir = self.data_dir / "dump"
        dump_dir.mkdir(parents=True, exist_ok=True)

        # Copy project_build script if needed
        self._ensure_project_build_script(mine_dir)

        # Run project_build
        project_build = ProjectBuildStage(
            mine_dir=mine_dir,
            dump_dir=dump_dir,
            logger=self.logger
        )

        result = project_build.execute()
        self.context.stage_results.append(result)

        if result.status == StageStatus.FAILED:
            raise BuilderException(f"project_build failed: {result.error_message}")

    def _ensure_project_build_script(self, mine_dir: Path) -> None:
        """Ensure project_build script exists."""
        script_path = mine_dir / "project_build"

        if not script_path.exists():
            self.logger.info("project_build not found, cloning intermine-scripts")

            # Clone intermine-scripts
            scripts_dir = self.git_ops.clone(
                repo_url="https://github.com/intermine/intermine-scripts",
                target_dir="intermine-scripts"
            )

            # Copy project_build
            import shutil
            source = scripts_dir / "project_build"
            shutil.copy(source, script_path)
            script_path.chmod(0o755)

            self.logger.info(f"Copied project_build to {script_path}")

    def _stage_build_webapp(self) -> None:
        """Build and deploy webapp."""
        self.logger.info("=== Stage: Build Webapp ===")

        mine_dir = Path(self.context.metadata["mine_dir"])

        # Build and deploy
        war_file = self.gradle_ops.build_webapp(mine_dir, redeploy=True)

        self.context.metadata["war_file"] = str(war_file)
        self.logger.info(f"Webapp deployed: {war_file}")

    def get_build_summary(self) -> Dict[str, Any]:
        """
        Get build summary.

        Returns:
            Dictionary with build summary
        """
        if not self.context:
            return {}

        return {
            "build_id": self.context.build_id,
            "mine_name": self.context.mine_name,
            "status": self.context.status,
            "start_time": self.context.start_time.isoformat(),
            "end_time": self.context.end_time.isoformat() if self.context.end_time else None,
            "duration_hours": self.context.duration_seconds / 3600 if self.context.duration_seconds else None,
            "completed_stages": self.context.completed_stages,
            "failed_stages": self.context.failed_stages,
            "total_stages": len(self.context.stage_results),
            "metadata": self.context.metadata
        }
