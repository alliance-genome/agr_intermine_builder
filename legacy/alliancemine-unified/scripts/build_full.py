#!/usr/bin/env python3
"""
AllianceMine Full Build Script

Executes complete InterMine build pipeline:
1. Build database schema
2. Extract and load data
3. Post-processing
4. Build user profile database
5. Build Solr indexes
6. Build and deploy WAR file

Usage:
    python3 build_full.py [--skip-data-extraction] [--skip-war-deploy]
"""

import os
import sys
import time
import subprocess
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional


ALLIANCEMINE_DIR = Path("/opt/intermine/alliancemine")
EXTRACT_DATA_SCRIPT = Path("/opt/intermine/scripts/extract_data.py")

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class AllianceMineBuildPipeline:
    """Manages the complete AllianceMine build process."""

    def __init__(self, skip_data_extraction: bool = False, skip_war_deploy: bool = False):
        self.skip_data_extraction = skip_data_extraction
        self.skip_war_deploy = skip_war_deploy
        self.start_time = time.time()

        # Change to alliancemine directory
        os.chdir(ALLIANCEMINE_DIR)

    def log_step(self, step_num: int, description: str) -> None:
        """Log a build step with formatting."""
        logger.info("")
        logger.info("=" * 50)
        logger.info(f"📋 STEP {step_num}: {description}")
        logger.info("=" * 50)

    def run_command(self, cmd: list, description: str) -> bool:
        """
        Run a shell command and handle errors.

        Args:
            cmd: Command and arguments as list
            description: Human-readable description

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Running: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=False,
                text=True
            )
            logger.info(f"✅ {description} completed successfully")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"❌ {description} failed with exit code {e.returncode}")
            return False

    def step_build_database_schema(self) -> bool:
        """Step 1: Build database schema."""
        self.log_step(1, "Building Database Schema")

        return self.run_command(
            ["./gradlew", "buildDB", "--stacktrace"],
            "Database schema build"
        )

    def step_extract_data(self) -> bool:
        """Step 2: Extract data from sources."""
        if self.skip_data_extraction:
            logger.info("Skipping data extraction (--skip-data-extraction)")
            return True

        self.log_step(2, "Extracting Data from Sources")

        if not EXTRACT_DATA_SCRIPT.exists():
            logger.warning(f"Data extraction script not found: {EXTRACT_DATA_SCRIPT}")
            logger.warning("Skipping data extraction")
            return True

        success = self.run_command(
            ["python3", str(EXTRACT_DATA_SCRIPT)],
            "Data extraction"
        )

        if not success:
            logger.warning("⚠️  Data extraction had errors (continuing anyway)")

        return True  # Don't fail build on data extraction errors

    def step_load_data(self) -> bool:
        """Step 3: Load data into database."""
        self.log_step(3, "Loading Data into Database")

        return self.run_command(
            ["./project_build", "-b"],
            "Data loading"
        )

    def step_postprocess(self) -> bool:
        """Step 4: Run post-processing."""
        self.log_step(4, "Running Post-Processing")

        success = self.run_command(
            ["./gradlew", "postprocess", "--stacktrace"],
            "Post-processing"
        )

        if not success:
            logger.warning("⚠️  Some post-processing steps failed (continuing anyway)")

        return True  # Don't fail build on post-processing errors

    def step_build_user_db(self) -> bool:
        """Step 5: Build user profile database."""
        self.log_step(5, "Building User Profile Database")

        return self.run_command(
            ["./gradlew", "buildUserDB", "--stacktrace"],
            "User profile database build"
        )

    def step_build_solr_indexes(self) -> bool:
        """Step 6: Build Solr search indexes."""
        self.log_step(6, "Building Solr Search Indexes")

        success = self.run_command(
            ["./load_db_build_solr"],
            "Solr index build"
        )

        if not success:
            logger.warning("⚠️  Solr indexing had errors (continuing anyway)")

        return True  # Don't fail build on Solr errors

    def step_deploy_war(self) -> bool:
        """Step 7: Build and deploy WAR file."""
        if self.skip_war_deploy:
            logger.info("Skipping WAR deployment (--skip-war-deploy)")
            return True

        self.log_step(7, "Building and Deploying WAR File")

        return self.run_command(
            ["./gradlew", "cargoRedeployRemote", "--stacktrace"],
            "WAR deployment"
        )

    def print_summary(self) -> None:
        """Print build summary."""
        duration = time.time() - self.start_time
        hours = int(duration // 3600)
        minutes = int((duration % 3600) // 60)
        seconds = int(duration % 60)

        logger.info("")
        logger.info("=" * 50)
        logger.info("✅ AllianceMine Build Completed Successfully!")
        logger.info("=" * 50)
        logger.info(f"Duration: {hours}h {minutes}m {seconds}s")
        logger.info("")
        logger.info("🌐 Web Application: http://localhost:8080/alliancemine")
        logger.info("🔍 Solr Admin: http://localhost:8983/solr")
        logger.info("")
        logger.info("To access the application:")
        logger.info("  docker-compose exec alliancemine bash")
        logger.info("  curl http://localhost:8080/alliancemine/service/version")
        logger.info("=" * 50)

    def run(self) -> int:
        """
        Execute the complete build pipeline.

        Returns:
            0 on success, 1 on failure
        """
        logger.info("=" * 50)
        logger.info("🏗️  AllianceMine Full Build")
        logger.info("=" * 50)

        steps = [
            self.step_build_database_schema,
            self.step_extract_data,
            self.step_load_data,
            self.step_postprocess,
            self.step_build_user_db,
            self.step_build_solr_indexes,
            self.step_deploy_war,
        ]

        for step in steps:
            if not step():
                logger.error("Build failed!")
                return 1

        self.print_summary()
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="Run complete AllianceMine build pipeline"
    )
    parser.add_argument(
        "--skip-data-extraction",
        action="store_true",
        help="Skip data extraction step (use existing data)"
    )
    parser.add_argument(
        "--skip-war-deploy",
        action="store_true",
        help="Skip WAR deployment step"
    )

    args = parser.parse_args()

    pipeline = AllianceMineBuildPipeline(
        skip_data_extraction=args.skip_data_extraction,
        skip_war_deploy=args.skip_war_deploy
    )

    sys.exit(pipeline.run())


if __name__ == "__main__":
    main()
