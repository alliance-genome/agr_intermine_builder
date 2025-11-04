"""
Build Executor Module

Orchestrates InterMine build process through defined stages:
1. BuildDB - Create database schema
2. Extract Data - Download/prepare data files
3. Project Build - Data integration (longest stage: 2-4 hours)
4. Post Process - Post-processing and indexing
5. Build User DB - Create user profile database (once per mine, persistent)
6. Build WAR - Build web application
7. Deploy - Deploy to Tomcat (optional)

Note: Profile databases are created once and persist across builds.
They can be imported from production releases using import_profile_db().
"""

import logging
from typing import Optional, List, Callable
from datetime import datetime
from pathlib import Path

from .mine_config import MineConfig, BuildStage, MineType
from .docker_manager import DockerManager

logger = logging.getLogger(__name__)


class BuildExecutionError(Exception):
    """Raised when a build stage fails."""
    pass


class BuildExecutor:
    """Executes InterMine build stages."""

    def __init__(
        self,
        docker_manager: DockerManager,
        mine_config: MineConfig,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ):
        """
        Initialize build executor.

        Args:
            docker_manager: Docker manager instance
            mine_config: Mine configuration
            progress_callback: Optional callback for progress updates (stage_name, progress)
        """
        self.docker_manager = docker_manager
        self.mine_config = mine_config
        self.mine_type = mine_config.mine_type
        self.progress_callback = progress_callback
        self.build_start_time: Optional[datetime] = None
        self.stage_times: dict = {}

    def _report_progress(self, stage: str, progress: float) -> None:
        """Report progress to callback if provided."""
        if self.progress_callback:
            self.progress_callback(stage, progress)

    def _execute_gradle_task(
        self,
        task: str,
        stage_name: str,
        workdir: str = "/root/alliancemine"
    ) -> tuple[int, str]:
        """
        Execute a Gradle task inside the container.

        Args:
            task: Gradle task name
            stage_name: Human-readable stage name
            workdir: Working directory

        Returns:
            Tuple of (exit_code, output)
        """
        # Adjust workdir based on mine type
        if self.mine_type == MineType.WORMMINE:
            workdir = "/root/wormmine"
        elif self.mine_type == MineType.MOUSEMINE:
            workdir = "/root/mousemine"
        elif self.mine_type == MineType.FLYMINE:
            workdir = "/root/flymine"

        logger.info(f"Starting {stage_name}...")
        stage_start = datetime.now()

        command = f"./gradlew {task} --stacktrace"
        exit_code, output = self.docker_manager.execute_command(
            self.mine_type,
            command,
            workdir=workdir,
            stream=True
        )

        stage_duration = (datetime.now() - stage_start).total_seconds()
        self.stage_times[stage_name] = stage_duration

        if exit_code != 0:
            logger.error(f"{stage_name} failed with exit code {exit_code}")
            raise BuildExecutionError(f"{stage_name} failed")

        logger.info(f"{stage_name} completed in {stage_duration:.1f}s")
        return exit_code, output

    def stage_build_db(self) -> None:
        """Stage 1: Create database schema."""
        self._report_progress("buildDB", 0.0)
        self._execute_gradle_task("buildDB", "Build Database Schema")
        self._report_progress("buildDB", 1.0)

    def stage_extract_data(self) -> None:
        """Stage 2: Extract/prepare data files."""
        self._report_progress("extract_data", 0.0)

        logger.info("Extracting data files...")
        stage_start = datetime.now()

        # Execute data extraction script
        exit_code, output = self.docker_manager.execute_command(
            self.mine_type,
            "/root/extract_data.sh",
            workdir="/root",
            stream=True
        )

        stage_duration = (datetime.now() - stage_start).total_seconds()
        self.stage_times["Extract Data"] = stage_duration

        if exit_code != 0:
            logger.error(f"Data extraction failed with exit code {exit_code}")
            raise BuildExecutionError("Data extraction failed")

        logger.info(f"Data extraction completed in {stage_duration:.1f}s")
        self._report_progress("extract_data", 1.0)

    def stage_project_build(self) -> None:
        """Stage 3: Project build (data integration) - LONGEST STAGE."""
        self._report_progress("project_build", 0.0)

        logger.info("Starting project_build (data integration)...")
        logger.info("This will take 2-4 hours depending on data size...")
        stage_start = datetime.now()

        # Determine workdir
        workdir = f"/root/{self.mine_type.value}"

        # Check if project_build script exists, clone if needed
        check_script = """
        if [ ! -f "./project_build" ]; then
            cd /root
            git clone --depth 1 https://github.com/intermine/intermine-scripts.git
            cp intermine-scripts/project_build /root/{}/project_build
            chmod +x /root/{}/project_build
        fi
        """.format(self.mine_type.value, self.mine_type.value)

        self.docker_manager.execute_command(
            self.mine_type,
            f"/bin/bash -c '{check_script}'",
            workdir=workdir
        )

        # Execute project_build
        command = "./project_build -b -T localhost /root/data/dump"
        exit_code, output = self.docker_manager.execute_command(
            self.mine_type,
            command,
            workdir=workdir,
            stream=True
        )

        stage_duration = (datetime.now() - stage_start).total_seconds()
        self.stage_times["Project Build"] = stage_duration

        if exit_code != 0:
            logger.error(f"Project build failed with exit code {exit_code}")
            raise BuildExecutionError("Project build failed")

        logger.info(f"Project build completed in {stage_duration:.1f}s "
                   f"({stage_duration/3600:.1f} hours)")
        self._report_progress("project_build", 1.0)

    def stage_post_process(self) -> None:
        """Stage 4: Post-processing."""
        self._report_progress("postprocess", 0.0)
        self._execute_gradle_task("postprocess", "Post-processing")
        self._report_progress("postprocess", 1.0)

    def stage_build_user_db(self) -> None:
        """Stage 5: Build user profile database (only if not exists)."""
        self._report_progress("buildUserDB", 0.0)

        # Check if profile database already exists
        profile_db = self.mine_config.profile_db_name
        check_db_cmd = f"""
        psql -h $RDS_HOST -U $RDS_USER -d postgres -tAc \
        "SELECT 1 FROM pg_database WHERE datname='{profile_db}'"
        """

        logger.info(f"Checking if profile database '{profile_db}' exists...")
        exit_code, output = self.docker_manager.execute_command(
            self.mine_type,
            check_db_cmd,
            workdir="/root",
            stream=False
        )

        if output.strip() == "1":
            logger.info(f"✅ Profile database '{profile_db}' already exists, skipping creation")
            logger.info("Note: Profile DB can be imported from current releases if needed")
            self._report_progress("buildUserDB", 1.0)
            return

        # Profile DB doesn't exist, create it
        logger.info(f"Profile database '{profile_db}' not found, creating new one...")
        self._execute_gradle_task("buildUserDB", "Build User Database")
        self._report_progress("buildUserDB", 1.0)

    def stage_build_war(self) -> None:
        """Stage 6: Build WAR file."""
        self._report_progress("war", 0.0)
        self._execute_gradle_task("war", "Build WAR File")
        self._report_progress("war", 1.0)

    def stage_deploy(self) -> None:
        """Stage 7: Deploy to Tomcat."""
        self._report_progress("deploy", 0.0)

        # Check if Tomcat is running
        port = self.mine_config.tomcat_port
        check_tomcat = f"curl -s http://localhost:{port} > /dev/null"
        exit_code, _ = self.docker_manager.execute_command(
            self.mine_type,
            check_tomcat,
            workdir="/root",
            stream=False
        )

        if exit_code != 0:
            logger.warning("Tomcat not running, skipping deployment")
            logger.info("To deploy later: ./gradlew cargoRedeployRemote")
            self._report_progress("deploy", 1.0)
            return

        self._execute_gradle_task("cargoRedeployRemote", "Deploy to Tomcat")
        self._report_progress("deploy", 1.0)

    def execute_full_build(
        self,
        skip_stages: Optional[List[BuildStage]] = None
    ) -> dict:
        """
        Execute complete build process.

        Args:
            skip_stages: Optional list of stages to skip

        Returns:
            Build summary dict with timings and status
        """
        self.build_start_time = datetime.now()
        skip_stages = skip_stages or self.mine_config.skip_stages

        logger.info("="*60)
        logger.info(f"{self.mine_config.display_name} Build Process")
        logger.info("="*60)
        logger.info(f"Mine Type: {self.mine_type.value}")
        logger.info(f"Release: {self.mine_config.release_version}")
        logger.info(f"Database: {self.mine_config.db_name}")
        logger.info(f"Profile DB: {self.mine_config.profile_db_name}")
        logger.info("="*60)

        # Stage mapping
        stage_methods = {
            BuildStage.BUILD_DB: self.stage_build_db,
            BuildStage.EXTRACT_DATA: self.stage_extract_data,
            BuildStage.PROJECT_BUILD: self.stage_project_build,
            BuildStage.POST_PROCESS: self.stage_post_process,
            BuildStage.BUILD_USER_DB: self.stage_build_user_db,
            BuildStage.BUILD_WAR: self.stage_build_war,
            BuildStage.DEPLOY: self.stage_deploy,
        }

        failed_stage = None
        completed_stages = []

        try:
            for stage in self.mine_config.build_stages:
                if stage in skip_stages:
                    logger.info(f"Skipping stage: {stage.value}")
                    continue

                stage_method = stage_methods.get(stage)
                if not stage_method:
                    logger.warning(f"Unknown stage: {stage.value}")
                    continue

                stage_method()
                completed_stages.append(stage.value)

        except BuildExecutionError as e:
            failed_stage = str(e)
            logger.error(f"Build failed: {e}")

        # Calculate total time
        total_duration = (datetime.now() - self.build_start_time).total_seconds()

        # Build summary
        summary = {
            "mine_type": self.mine_type.value,
            "display_name": self.mine_config.display_name,
            "release_version": self.mine_config.release_version,
            "start_time": self.build_start_time.isoformat(),
            "total_duration_seconds": total_duration,
            "total_duration_hours": total_duration / 3600,
            "completed_stages": completed_stages,
            "failed_stage": failed_stage,
            "stage_times": self.stage_times,
            "success": failed_stage is None,
        }

        # Log summary
        logger.info("="*60)
        if summary["success"]:
            logger.info(f"✅ {self.mine_config.display_name} build completed successfully!")
        else:
            logger.error(f"❌ {self.mine_config.display_name} build failed at: {failed_stage}")
        logger.info("="*60)
        logger.info(f"Total time: {total_duration/3600:.2f} hours")
        logger.info(f"Completed stages: {len(completed_stages)}/{len(self.mine_config.build_stages)}")
        logger.info("="*60)

        if not summary["success"]:
            raise BuildExecutionError(f"Build failed at stage: {failed_stage}")

        return summary

    def execute_single_stage(self, stage: BuildStage) -> None:
        """
        Execute a single build stage.

        Args:
            stage: Stage to execute
        """
        stage_methods = {
            BuildStage.BUILD_DB: self.stage_build_db,
            BuildStage.EXTRACT_DATA: self.stage_extract_data,
            BuildStage.PROJECT_BUILD: self.stage_project_build,
            BuildStage.POST_PROCESS: self.stage_post_process,
            BuildStage.BUILD_USER_DB: self.stage_build_user_db,
            BuildStage.BUILD_WAR: self.stage_build_war,
            BuildStage.DEPLOY: self.stage_deploy,
        }

        stage_method = stage_methods.get(stage)
        if not stage_method:
            raise ValueError(f"Unknown stage: {stage.value}")

        logger.info(f"Executing single stage: {stage.value}")
        stage_method()

    def import_profile_db(self, dump_file: str) -> None:
        """
        Import profile database from a pg_dump file.

        This allows importing existing profile data from production releases
        rather than creating a fresh profile database.

        Args:
            dump_file: Path to pg_dump file (inside container or mounted volume)

        Example:
            executor.import_profile_db("/root/data/alliancemine_profiles.sql")
        """
        profile_db = self.mine_config.profile_db_name

        logger.info(f"Importing profile database: {profile_db}")
        logger.info(f"Source dump file: {dump_file}")

        # Check if dump file exists
        check_file = f"test -f {dump_file} && echo 'exists'"
        exit_code, output = self.docker_manager.execute_command(
            self.mine_type,
            check_file,
            workdir="/root",
            stream=False
        )

        if "exists" not in output:
            raise BuildExecutionError(f"Dump file not found: {dump_file}")

        # Drop existing profile DB if it exists
        drop_cmd = f"""
        psql -h $RDS_HOST -U $RDS_USER -d postgres -c \
        "DROP DATABASE IF EXISTS {profile_db}"
        """
        logger.info(f"Dropping existing profile database (if exists)...")
        self.docker_manager.execute_command(
            self.mine_type,
            drop_cmd,
            workdir="/root",
            stream=True
        )

        # Create new profile DB
        create_cmd = f"""
        psql -h $RDS_HOST -U $RDS_USER -d postgres -c \
        "CREATE DATABASE {profile_db}"
        """
        logger.info(f"Creating profile database...")
        exit_code, _ = self.docker_manager.execute_command(
            self.mine_type,
            create_cmd,
            workdir="/root",
            stream=True
        )

        if exit_code != 0:
            raise BuildExecutionError(f"Failed to create profile database")

        # Import dump
        import_cmd = f"""
        psql -h $RDS_HOST -U $RDS_USER -d {profile_db} < {dump_file}
        """
        logger.info(f"Importing profile data from dump file...")
        exit_code, _ = self.docker_manager.execute_command(
            self.mine_type,
            import_cmd,
            workdir="/root",
            stream=True
        )

        if exit_code != 0:
            raise BuildExecutionError(f"Failed to import profile database")

        logger.info(f"✅ Profile database imported successfully")
        logger.info(f"   Database: {profile_db}")
        logger.info(f"   Source: {dump_file}")
