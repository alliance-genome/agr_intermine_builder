#!/usr/bin/env python3
"""
AllianceMine Full Build Script

Executes the complete InterMine build pipeline (6 stages):
1. buildDB       - Create PostgreSQL schema
2. extract_data  - S3 sync + FMS download + Alliance API fetchers
3. project_build - Data integration (4-7 hours)
4. postprocess   - Indexing, summary tables, Solr indexes
5. war           - Build WAR file
6. deploy        - Deploy WAR to Tomcat via cargoRedeployRemote

Usage:
    python3 build_full.py --build-type test            # release auto-resolved from FMS
    python3 build_full.py --build-type test --release 9.0.0 --rc 1
    python3 build_full.py --build-type production --release 9.0.0
    python3 build_full.py --start-from postprocess
    python3 build_full.py --skip-stages deploy
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
    "war",
    "deploy",
]


class AllianceMineBuildPipeline:
    """Manages the complete AllianceMine build process."""

    def __init__(
        self,
        build_type: str = "test",
        release: str = "",
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
        logger.info(f"STAGE {num}/{len(STAGES)}: {description}")
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
        """Stage 2: S3 sync + FMS download + Alliance API fetchers.

        On a cold cache the API fetch can add ~20 min; warm reruns are ~2 min.
        Cache lives at /root/data/api-cache/ (bind-mounted via docker-compose).
        """
        self._log_stage(2, "Extracting Alliance Data (S3 + FMS + API)")

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

        if self.resume:
            logger.info("Resuming from last dump checkpoint (-l)")
            cmd = ["./project_build", "-l", "-E", "UTF8", "localhost", "/root/data/dump"]
        else:
            logger.info("This will take 2-4 hours...")
            cmd = ["./project_build", "-b", "-E", "UTF8", "localhost", "/root/data/dump"]

        return self._run(cmd, "Data integration (project_build)")

    def stage_postprocess(self) -> bool:
        """Stage 4: Post-processing."""
        self._log_stage(4, "Running Post-Processing")
        return self._run(
            ["./gradlew", "postprocess", "--stacktrace"],
            "Post-processing",
        )

    def stage_war(self) -> bool:
        """Stage 5: Build WAR file."""
        self._log_stage(5, "Building WAR File")
        return self._run(
            ["./gradlew", "war", "--stacktrace"],
            "WAR file build",
        )

    def stage_deploy(self) -> bool:
        """Stage 6: Deploy WAR to Tomcat via cargoRedeployRemote."""
        self._log_stage(6, "Deploying WAR to Tomcat")

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
    parser.add_argument("--release", default=None, help="Alliance release version (e.g., 9.0.0); omit to read ALLIANCE_RELEASE from env")
    parser.add_argument("--rc", type=int, default=None, help="RC number for test builds")
    parser.add_argument("--deploy-host", default=None, help="EC2 host for WAR deployment")
    parser.add_argument("--deploy-port", type=int, default=8090, help="Tomcat port on deploy host")
    parser.add_argument(
        "--skip-stages", nargs="+", choices=STAGES, default=[], help="Stages to skip"
    )
    parser.add_argument("--start-from", choices=STAGES, default=None, help="Resume from stage")
    parser.add_argument("--resume", action="store_true", help="Resume project_build from last dump checkpoint")

    args = parser.parse_args()

    # Release: --release wins, then ALLIANCE_RELEASE (entrypoint.sh resolves it
    # from the FMS API before invoking us, so this should always be set).
    release = args.release or os.environ.get("ALLIANCE_RELEASE", "")
    if not release:
        logger.error("No release specified. Pass --release or set ALLIANCE_RELEASE.")
        sys.exit(2)

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
