#!/usr/bin/env python3
"""
AllianceMine Full Build Script

Executes the complete InterMine build pipeline (7 stages):
1. buildDB       - Create PostgreSQL schema
2. extract_data  - Download data from FMS
3. project_build - Data integration (2-4 hours)
4. postprocess   - Indexing and summary tables
5. buildUserDB   - User profile database (skipped if exists)
6. war           - Build WAR file
7. deploy        - Deploy WAR to EC2 Tomcat via cargoRedeployRemote

Usage:
    python3 build_full.py --build-type test --release 8.3.0 --rc 1
    python3 build_full.py --build-type production --release 8.3.0
    python3 build_full.py --start-from postprocess
    python3 build_full.py --skip-stages buildUserDB deploy
"""

import os
import sys
import time
import subprocess
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Optional

ALLIANCEMINE_DIR = Path("/root/alliancemine")
SCRIPTS_DIR = Path("/root/scripts")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

STAGES = [
    "buildDB",
    "extract_data",
    "project_build",
    "postprocess",
    "buildUserDB",
    "war",
    "deploy",
]


class AllianceMineBuildPipeline:
    """Manages the complete AllianceMine build process."""

    def __init__(
        self,
        build_type: str = "test",
        release: str = "8.3.0",
        rc: Optional[int] = None,
        deploy_host: Optional[str] = None,
        deploy_port: int = 8090,
        skip_stages: Optional[List[str]] = None,
        start_from: Optional[str] = None,
        resume: bool = False,
    ):
        self.build_type = build_type
        self.release = release
        self.rc = rc
        self.deploy_host = deploy_host
        self.deploy_port = deploy_port
        self.skip_stages = set(skip_stages or [])
        self.start_from = start_from
        self.resume = resume
        self.start_time = time.time()
        self.stage_times: dict = {}

        os.chdir(ALLIANCEMINE_DIR)

    def _log_stage(self, num: int, description: str) -> None:
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"STAGE {num}/7: {description}")
        logger.info("=" * 60)

    def _run(self, cmd: list, description: str, cwd: Optional[str] = None) -> bool:
        """Run a shell command, streaming output."""
        logger.info(f"Running: {' '.join(cmd)}")
        start = time.time()
        try:
            result = subprocess.run(cmd, check=True, cwd=cwd)
            elapsed = time.time() - start
            logger.info(f"{description} completed in {elapsed:.0f}s")
            return True
        except subprocess.CalledProcessError as e:
            elapsed = time.time() - start
            logger.error(f"{description} failed (exit {e.returncode}) after {elapsed:.0f}s")
            return False

    def _should_run(self, stage: str) -> bool:
        """Check if a stage should run based on skip/start-from filters."""
        if stage in self.skip_stages:
            logger.info(f"Skipping stage: {stage} (--skip-stages)")
            return False
        if self.start_from:
            if STAGES.index(stage) < STAGES.index(self.start_from):
                logger.info(f"Skipping stage: {stage} (before --start-from {self.start_from})")
                return False
        return True

    def stage_build_db(self) -> bool:
        """Stage 1: Create database schema."""
        self._log_stage(1, "Building Database Schema")
        return self._run(
            ["./gradlew", "buildDB", "--stacktrace"],
            "Database schema build",
        )

    def stage_extract_data(self) -> bool:
        """Stage 2: Extract Alliance data from FMS."""
        self._log_stage(2, "Extracting Alliance Data from FMS")

        script = SCRIPTS_DIR / "extract_data.py"
        if not script.exists():
            logger.warning(f"extract_data.py not found at {script}, skipping")
            return True

        cmd = ["python3", str(script)]
        release_env = os.environ.get("ALLIANCE_RELEASE", self.release)
        if release_env:
            cmd.extend(["--release", release_env])

        return self._run(cmd, "Data extraction", cwd="/root")

    def stage_project_build(self) -> bool:
        """Stage 3: Project build (data integration) - LONGEST STAGE."""
        self._log_stage(3, "Running project_build (data integration)")

        if not (ALLIANCEMINE_DIR / "project_build").exists():
            logger.error("project_build script not found in /root/alliancemine/")
            return False

        cmd = ["./project_build", "-b", "-T", "localhost", "/root/data/dump"]

        if self.resume:
            logger.info("Resuming from last dump file (-l)")
            cmd.insert(1, "-l")
        else:
            logger.info("This will take 2-4 hours...")

        return self._run(cmd, "Data integration (project_build)")

    def stage_postprocess(self) -> bool:
        """Stage 4: Post-processing."""
        self._log_stage(4, "Running Post-Processing")
        return self._run(
            ["./gradlew", "postprocess", "--stacktrace"],
            "Post-processing",
        )

    def stage_build_user_db(self) -> bool:
        """Stage 5: Build user profile database (skip if exists)."""
        self._log_stage(5, "Building User Profile Database")

        profile_db = os.environ.get("RDS_PROFILE_DB_NAME", "alliancemine_userprofile")
        rds_host = os.environ.get("RDS_HOST", "localhost")
        rds_port = os.environ.get("RDS_PORT", "5432")
        rds_user = os.environ.get("RDS_USER", "postgres")

        # Check if profile DB already has tables (indicating it's been set up)
        try:
            check = subprocess.run(
                [
                    "psql",
                    "-h", rds_host,
                    "-p", rds_port,
                    "-U", rds_user,
                    "-d", profile_db,
                    "-tAc",
                    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if check.returncode == 0 and check.stdout.strip() not in ("", "0"):
                logger.info(
                    f"Profile database '{profile_db}' already has tables, skipping buildUserDB"
                )
                return True
        except (subprocess.TimeoutExpired, Exception) as e:
            logger.warning(f"Could not check profile DB: {e}, proceeding with buildUserDB")

        return self._run(
            ["./gradlew", "buildUserDB", "--stacktrace"],
            "User profile database build",
        )

    def stage_war(self) -> bool:
        """Stage 6: Build WAR file."""
        self._log_stage(6, "Building WAR File")
        return self._run(
            ["./gradlew", "war", "--stacktrace"],
            "WAR file build",
        )

    def stage_deploy(self) -> bool:
        """Stage 7: Deploy WAR to EC2 Tomcat."""
        self._log_stage(7, "Deploying WAR to Tomcat")

        if not self.deploy_host:
            logger.info("No --deploy-host specified, skipping deployment")
            logger.info("WAR file available at: webapp/build/libs/")
            return True

        deploy_script = SCRIPTS_DIR / "deploy_war.py"
        if deploy_script.exists():
            return self._run(
                [
                    "python3",
                    str(deploy_script),
                    "--host", self.deploy_host,
                    "--port", str(self.deploy_port),
                ],
                "WAR deployment",
            )

        # Fallback: direct Gradle deploy
        return self._run(
            ["./gradlew", "cargoRedeployRemote", "--stacktrace"],
            "WAR deployment (Gradle)",
        )

    def run(self) -> int:
        """Execute the complete build pipeline. Returns 0 on success, 1 on failure."""
        logger.info("=" * 60)
        logger.info("AllianceMine Full Build")
        logger.info("=" * 60)
        logger.info(f"Build type:  {self.build_type}")
        logger.info(f"Release:     {self.release}")
        if self.rc:
            logger.info(f"RC:          {self.rc}")
        logger.info(f"Database:    {os.environ.get('RDS_DB_NAME', 'unknown')}")
        logger.info(f"Profile DB:  {os.environ.get('RDS_PROFILE_DB_NAME', 'unknown')}")
        logger.info(f"Deploy host: {self.deploy_host or 'none'}")
        logger.info("=" * 60)

        stage_methods = {
            "buildDB": self.stage_build_db,
            "extract_data": self.stage_extract_data,
            "project_build": self.stage_project_build,
            "postprocess": self.stage_postprocess,
            "buildUserDB": self.stage_build_user_db,
            "war": self.stage_war,
            "deploy": self.stage_deploy,
        }

        completed = []
        failed_stage = None

        for stage in STAGES:
            if not self._should_run(stage):
                continue

            stage_start = time.time()
            method = stage_methods[stage]

            if not method():
                failed_stage = stage
                self.stage_times[stage] = time.time() - stage_start
                break

            self.stage_times[stage] = time.time() - stage_start
            completed.append(stage)

        # Summary
        total = time.time() - self.start_time
        hours = int(total // 3600)
        minutes = int((total % 3600) // 60)
        seconds = int(total % 60)

        logger.info("")
        logger.info("=" * 60)
        if failed_stage:
            logger.error(f"BUILD FAILED at stage: {failed_stage}")
        else:
            logger.info("BUILD COMPLETED SUCCESSFULLY")
        logger.info("=" * 60)
        logger.info(f"Duration: {hours}h {minutes}m {seconds}s")
        logger.info(f"Completed stages: {', '.join(completed)}")
        for stage, elapsed in self.stage_times.items():
            logger.info(f"  {stage}: {elapsed:.0f}s ({elapsed/3600:.2f}h)")
        logger.info("=" * 60)

        return 1 if failed_stage else 0


def main():
    parser = argparse.ArgumentParser(description="AllianceMine full build pipeline")
    parser.add_argument(
        "--build-type",
        choices=["test", "production"],
        default="test",
        help="Build type (default: test)",
    )
    parser.add_argument("--release", default=None, help="Alliance release version (e.g., 8.3.0)")
    parser.add_argument("--rc", type=int, default=None, help="RC number for test builds")
    parser.add_argument("--deploy-host", default=None, help="EC2 host for WAR deployment")
    parser.add_argument("--deploy-port", type=int, default=8090, help="Tomcat port on deploy host")
    parser.add_argument(
        "--skip-stages", nargs="+", choices=STAGES, default=[], help="Stages to skip"
    )
    parser.add_argument("--start-from", choices=STAGES, default=None, help="Resume from stage")
    parser.add_argument("--resume", action="store_true", help="Resume project_build from last dump checkpoint")

    args = parser.parse_args()

    # Use env var as fallback for release
    release = args.release or os.environ.get("ALLIANCE_RELEASE", "8.3.0")

    pipeline = AllianceMineBuildPipeline(
        build_type=args.build_type,
        release=release,
        rc=args.rc,
        deploy_host=args.deploy_host,
        deploy_port=args.deploy_port,
        skip_stages=args.skip_stages,
        start_from=args.start_from,
        resume=args.resume,
    )

    sys.exit(pipeline.run())


if __name__ == "__main__":
    main()
