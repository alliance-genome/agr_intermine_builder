"""Gradle build operations."""

import logging
import subprocess
from pathlib import Path
from typing import List, Optional, Dict

from .exceptions import GradleBuildError


class GradleOperations:
    """Handles Gradle build operations."""

    def __init__(
        self,
        heap_size_gb: int = 32,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize Gradle operations.

        Args:
            heap_size_gb: JVM heap size in GB
            logger: Optional logger instance
        """
        self.heap_size_gb = heap_size_gb
        self.logger = logger or logging.getLogger(__name__)

        # Configure Gradle environment
        self.env = self._setup_gradle_env()

    def _setup_gradle_env(self) -> Dict[str, str]:
        """Set up Gradle environment variables."""
        import os
        env = os.environ.copy()

        # JVM settings for Gradle
        gradle_opts = [
            f"-Xmx{self.heap_size_gb}g",
            f"-Xms{self.heap_size_gb // 2}g",
            "-XX:+UseG1GC",
            "-XX:MaxGCPauseMillis=200",
            "-XX:+ParallelRefProcEnabled",
            "-XX:InitiatingHeapOccupancyPercent=45",
            "-XX:G1HeapRegionSize=32m",
            "-XX:+UnlockExperimentalVMOptions",
            "-XX:G1NewSizePercent=20",
            "-XX:G1MaxNewSizePercent=30",
            "-XX:+UseStringDeduplication"
        ]

        env["GRADLE_OPTS"] = " ".join(gradle_opts)
        env["JAVA_HOME"] = env.get("JAVA_HOME", "/usr/lib/jvm/java-1.8.0")

        self.logger.info(f"Gradle configured with {self.heap_size_gb}GB heap")

        return env

    def run_task(
        self,
        project_dir: Path,
        tasks: List[str],
        args: Optional[List[str]] = None,
        timeout: int = 3600
    ) -> subprocess.CompletedProcess:
        """
        Run Gradle task(s).

        Args:
            project_dir: Project directory containing build.gradle
            tasks: List of Gradle tasks to run
            args: Additional Gradle arguments
            timeout: Timeout in seconds

        Returns:
            Completed process

        Raises:
            GradleBuildError: If Gradle task fails
        """
        cmd = ["./gradlew"] + tasks

        if args:
            cmd.extend(args)

        # Add common flags
        cmd.extend(["--stacktrace", "--no-daemon"])

        self.logger.info(f"Running Gradle: {' '.join(cmd)} in {project_dir}")

        try:
            result = subprocess.run(
                cmd,
                cwd=project_dir,
                capture_output=True,
                text=True,
                env=self.env,
                timeout=timeout,
                check=True
            )

            self.logger.info(f"Gradle task completed: {' '.join(tasks)}")
            return result

        except subprocess.CalledProcessError as e:
            error_msg = f"Gradle task failed: {' '.join(tasks)}\n{e.stderr}"
            self.logger.error(error_msg)
            raise GradleBuildError(error_msg) from e

        except subprocess.TimeoutExpired as e:
            error_msg = f"Gradle task timed out after {timeout}s: {' '.join(tasks)}"
            self.logger.error(error_msg)
            raise GradleBuildError(error_msg) from e

    def clean(self, project_dir: Path) -> None:
        """
        Run gradle clean.

        Args:
            project_dir: Project directory

        Raises:
            GradleBuildError: If clean fails
        """
        self.logger.info("Running gradle clean")
        self.run_task(project_dir, ["clean"])

    def build(self, project_dir: Path, skip_tests: bool = False) -> None:
        """
        Run gradle build.

        Args:
            project_dir: Project directory
            skip_tests: Skip running tests

        Raises:
            GradleBuildError: If build fails
        """
        self.logger.info("Running gradle build")
        args = ["-x", "test"] if skip_tests else []
        self.run_task(project_dir, ["build"], args=args, timeout=7200)  # 2 hour timeout

    def install(self, project_dir: Path) -> None:
        """
        Run gradle install (publish to local Maven).

        Args:
            project_dir: Project directory

        Raises:
            GradleBuildError: If install fails
        """
        self.logger.info("Running gradle install")
        self.run_task(project_dir, ["install"], timeout=3600)

    def build_intermine_core(self, intermine_dir: Path) -> None:
        """
        Build InterMine core components.

        This builds the core InterMine libraries in the correct order:
        1. plugin
        2. intermine
        3. bio
        4. bio/sources
        5. bio/postprocess

        Args:
            intermine_dir: InterMine source directory

        Raises:
            GradleBuildError: If any build step fails
        """
        self.logger.info("Building InterMine core components")

        components = [
            "plugin",
            "intermine",
            "bio",
            "bio/sources",
            "bio/postprocess"
        ]

        for component in components:
            component_dir = intermine_dir / component
            self.logger.info(f"Building {component}")

            # Clean and install
            self.clean(component_dir)
            self.install(component_dir)

        self.logger.info("InterMine core build completed")

    def build_biosources(self, biosources_dir: Path) -> None:
        """
        Build and install bio-sources.

        Args:
            biosources_dir: Bio-sources directory

        Raises:
            GradleBuildError: If build fails
        """
        self.logger.info("Building bio-sources")

        self.clean(biosources_dir)
        self.install(biosources_dir)

        self.logger.info("Bio-sources build completed")

    def build_webapp(self, mine_dir: Path, redeploy: bool = True) -> Path:
        """
        Build mine webapp.

        Args:
            mine_dir: Mine project directory
            redeploy: If True, redeploy to Tomcat

        Returns:
            Path to generated WAR file

        Raises:
            GradleBuildError: If build or deployment fails
        """
        self.logger.info("Building webapp")

        if redeploy:
            task = "cargoRedeployRemote"
        else:
            task = "war"

        self.run_task(mine_dir, [task], timeout=1800)  # 30 minute timeout

        # Find WAR file
        war_files = list((mine_dir / "webapp" / "build" / "libs").glob("*.war"))

        if not war_files:
            raise GradleBuildError("WAR file not found after build")

        war_file = war_files[0]
        self.logger.info(f"Webapp built: {war_file}")

        return war_file

    def get_version(self, build_gradle: Path) -> Optional[str]:
        """
        Extract version from build.gradle file.

        Args:
            build_gradle: Path to build.gradle

        Returns:
            Version string or None if not found
        """
        try:
            with open(build_gradle) as f:
                for line in f:
                    if line.strip().startswith("version"):
                        # Extract version = '5.0.0' or version = "5.0.0"
                        parts = line.split("=")
                        if len(parts) == 2:
                            version = parts[1].strip().strip("'\"")
                            self.logger.debug(f"Found version: {version}")
                            return version
        except Exception as e:
            self.logger.warning(f"Could not extract version: {e}")

        return None
