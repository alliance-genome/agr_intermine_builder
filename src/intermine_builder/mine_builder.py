"""
Mine Builder Orchestrator

Main orchestrator that coordinates the complete InterMine build process:
- Manages RDS connections
- Builds Docker images
- Creates and manages containers
- Executes build stages
- Provides status monitoring
- Handles cleanup

This is the primary interface for building InterMines.
"""

import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from .mine_config import MineType, BuildStage, get_mine_config
from .docker_manager import DockerManager
from .build_executor import BuildExecutor
from .config import Config, DatabaseConfig

logger = logging.getLogger(__name__)


class MineBuilder:
    """Main orchestrator for InterMine builds."""

    def __init__(
        self,
        config: Config,
        base_dir: Optional[Path] = None,
        log_level: str = "INFO"
    ):
        """
        Initialize mine builder.

        Args:
            config: Application configuration with RDS details
            base_dir: Base directory for docker contexts (defaults to project root)
            log_level: Logging level
        """
        self.config = config
        self.base_dir = base_dir or Path.cwd()

        # Setup logging
        logging.basicConfig(
            level=getattr(logging, log_level.upper()),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        # Initialize Docker manager
        self.docker_manager = DockerManager(self.base_dir)

        # Track build status
        self.build_history: List[Dict[str, Any]] = []
        self.current_builds: Dict[MineType, BuildExecutor] = {}

    def build_mine(
        self,
        mine_type: MineType,
        force_rebuild_image: bool = False,
        skip_stages: Optional[List[BuildStage]] = None,
        rds_config: Optional[DatabaseConfig] = None
    ) -> Dict[str, Any]:
        """
        Build a complete InterMine instance.

        Args:
            mine_type: Type of mine to build
            force_rebuild_image: Force rebuild of Docker image
            skip_stages: Optional stages to skip
            rds_config: Optional RDS configuration (uses config default if not provided)

        Returns:
            Build summary dictionary
        """
        logger.info(f"Starting build for {mine_type.value}")

        # Get mine configuration
        mine_config = get_mine_config(mine_type)

        # Get RDS configuration
        if not rds_config:
            rds_config = self.config.database

        try:
            # Step 1: Create Docker network
            self.docker_manager.create_network()

            # Step 2: Build Docker image
            logger.info(f"Building Docker image for {mine_type.value}...")
            self.docker_manager.build_image(
                mine_config,
                force_rebuild=force_rebuild_image
            )

            # Step 3: Create container
            logger.info(f"Creating container for {mine_type.value}...")
            self.docker_manager.create_container(
                mine_config,
                rds_host=rds_config.host,
                rds_port=rds_config.port,
                rds_user=rds_config.username,
                rds_password=rds_config.password
            )

            # Step 4: Start container
            self.docker_manager.start_container(mine_type)

            # Wait for container to be ready
            logger.info("Waiting for container to be ready...")
            import time
            time.sleep(5)

            # Step 5: Execute build
            build_executor = BuildExecutor(
                self.docker_manager,
                mine_config,
                progress_callback=self._progress_callback
            )
            self.current_builds[mine_type] = build_executor

            summary = build_executor.execute_full_build(skip_stages=skip_stages)

            # Record build history
            self.build_history.append(summary)

            logger.info(f"Build completed for {mine_type.value}")
            return summary

        except Exception as e:
            logger.error(f"Build failed for {mine_type.value}: {e}")
            # Record failure
            failure_summary = {
                "mine_type": mine_type.value,
                "display_name": mine_config.display_name,
                "start_time": datetime.now().isoformat(),
                "success": False,
                "error": str(e)
            }
            self.build_history.append(failure_summary)
            raise

        finally:
            # Cleanup
            if mine_type in self.current_builds:
                del self.current_builds[mine_type]

    def build_all_mines(
        self,
        force_rebuild_images: bool = False,
        rds_config: Optional[DatabaseConfig] = None,
        stop_on_failure: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Build all configured mines in sequence.

        Args:
            force_rebuild_images: Force rebuild of all Docker images
            rds_config: Optional RDS configuration
            stop_on_failure: Stop building if one mine fails

        Returns:
            List of build summaries
        """
        logger.info("Starting build for all mines")
        logger.info("Build sequence: AllianceMine → WormMine → MouseMine → FlyMine")

        summaries = []
        mines_to_build = [
            MineType.ALLIANCEMINE,
            MineType.WORMMINE,
            MineType.MOUSEMINE,
            MineType.FLYMINE
        ]

        for mine_type in mines_to_build:
            try:
                summary = self.build_mine(
                    mine_type,
                    force_rebuild_image=force_rebuild_images,
                    rds_config=rds_config
                )
                summaries.append(summary)

            except Exception as e:
                logger.error(f"Failed to build {mine_type.value}: {e}")
                if stop_on_failure:
                    logger.error("Stopping build sequence due to failure")
                    break
                else:
                    logger.warning("Continuing to next mine despite failure")

        # Print summary
        self._print_build_summary(summaries)

        return summaries

    def execute_stage(
        self,
        mine_type: MineType,
        stage: BuildStage,
        rds_config: Optional[DatabaseConfig] = None
    ) -> None:
        """
        Execute a single build stage for a mine.

        Args:
            mine_type: Type of mine
            stage: Stage to execute
            rds_config: Optional RDS configuration
        """
        mine_config = get_mine_config(mine_type)

        if not rds_config:
            rds_config = self.config.database

        # Ensure container exists and is running
        status = self.docker_manager.get_container_status(mine_type)
        if status == "not_created":
            # Create and start container
            self.docker_manager.create_container(
                mine_config,
                rds_host=rds_config.host,
                rds_port=rds_config.port,
                rds_user=rds_config.username,
                rds_password=rds_config.password
            )
            self.docker_manager.start_container(mine_type)
        elif status != "running":
            self.docker_manager.start_container(mine_type)

        # Execute stage
        build_executor = BuildExecutor(self.docker_manager, mine_config)
        build_executor.execute_single_stage(stage)

    def get_mine_status(self, mine_type: MineType) -> Dict[str, Any]:
        """
        Get current status of a mine.

        Args:
            mine_type: Type of mine

        Returns:
            Status dictionary
        """
        container_status = self.docker_manager.get_container_status(mine_type)

        status = {
            "mine_type": mine_type.value,
            "container_status": container_status,
            "is_building": mine_type in self.current_builds,
        }

        if mine_type in self.current_builds:
            executor = self.current_builds[mine_type]
            status["current_stage"] = getattr(executor, 'current_stage', 'unknown')

        return status

    def get_build_history(self) -> List[Dict[str, Any]]:
        """Get build history."""
        return self.build_history

    def cleanup(self, mine_type: Optional[MineType] = None) -> None:
        """
        Cleanup containers and resources.

        Args:
            mine_type: Specific mine to cleanup, or None for all
        """
        logger.info(f"Cleaning up {mine_type.value if mine_type else 'all mines'}")
        self.docker_manager.cleanup(mine_type)

    def _progress_callback(self, stage: str, progress: float) -> None:
        """Handle progress updates from build executor."""
        logger.info(f"Stage: {stage}, Progress: {progress*100:.0f}%")

    def _print_build_summary(self, summaries: List[Dict[str, Any]]) -> None:
        """Print summary of all builds."""
        logger.info("="*70)
        logger.info("BUILD SUMMARY")
        logger.info("="*70)

        total_success = sum(1 for s in summaries if s.get("success", False))
        total_failed = len(summaries) - total_success
        total_time = sum(s.get("total_duration_seconds", 0) for s in summaries)

        for summary in summaries:
            status = "✅ SUCCESS" if summary.get("success") else "❌ FAILED"
            duration = summary.get("total_duration_hours", 0)
            logger.info(f"{summary['display_name']:15} {status:12} {duration:.2f} hours")

        logger.info("="*70)
        logger.info(f"Total: {total_success} succeeded, {total_failed} failed")
        logger.info(f"Total time: {total_time/3600:.2f} hours")
        logger.info("="*70)

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup resources."""
        self.cleanup()
