"""Git operations for cloning and managing repositories."""

import logging
import subprocess
from pathlib import Path
from typing import Optional

from .exceptions import GitOperationError


class GitOperations:
    """Handles git clone, checkout, and repository management."""

    def __init__(self, base_dir: Path, logger: Optional[logging.Logger] = None):
        """
        Initialize Git operations.

        Args:
            base_dir: Base directory for cloning repositories
            logger: Optional logger instance
        """
        self.base_dir = Path(base_dir)
        self.logger = logger or logging.getLogger(__name__)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def clone(
        self,
        repo_url: str,
        target_dir: str,
        branch: str = "master",
        depth: int = 1,
        single_branch: bool = True
    ) -> Path:
        """
        Clone a git repository.

        Args:
            repo_url: Git repository URL
            target_dir: Target directory name (relative to base_dir)
            branch: Branch to clone
            depth: Clone depth (1 for shallow clone)
            single_branch: Only clone specified branch

        Returns:
            Path to cloned repository

        Raises:
            GitOperationError: If clone fails
        """
        target_path = self.base_dir / target_dir

        # Skip if already exists
        if target_path.exists() and (target_path / ".git").exists():
            self.logger.info(f"Repository already exists: {target_path}")
            return target_path

        self.logger.info(f"Cloning {repo_url} (branch: {branch}) to {target_path}")

        cmd = ["git", "clone", repo_url, str(target_path)]

        if branch:
            cmd.extend(["--branch", branch])

        if single_branch:
            cmd.append("--single-branch")

        if depth:
            cmd.extend(["--depth", str(depth)])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout
                check=True
            )
            self.logger.info(f"Successfully cloned to {target_path}")
            return target_path

        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to clone {repo_url}: {e.stderr}"
            self.logger.error(error_msg)
            raise GitOperationError(error_msg) from e

        except subprocess.TimeoutExpired as e:
            error_msg = f"Clone timeout for {repo_url} after 10 minutes"
            self.logger.error(error_msg)
            raise GitOperationError(error_msg) from e

    def checkout(self, repo_path: Path, branch: str) -> None:
        """
        Checkout a specific branch.

        Args:
            repo_path: Path to repository
            branch: Branch name to checkout

        Raises:
            GitOperationError: If checkout fails
        """
        self.logger.info(f"Checking out branch {branch} in {repo_path}")

        try:
            subprocess.run(
                ["git", "checkout", branch],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
                timeout=30
            )
            self.logger.info(f"Successfully checked out {branch}")

        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to checkout {branch}: {e.stderr}"
            self.logger.error(error_msg)
            raise GitOperationError(error_msg) from e

    def pull(self, repo_path: Path) -> None:
        """
        Pull latest changes from remote.

        Args:
            repo_path: Path to repository

        Raises:
            GitOperationError: If pull fails
        """
        self.logger.info(f"Pulling latest changes in {repo_path}")

        try:
            subprocess.run(
                ["git", "pull"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
                timeout=300
            )
            self.logger.info("Successfully pulled changes")

        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to pull changes: {e.stderr}"
            self.logger.error(error_msg)
            raise GitOperationError(error_msg) from e

    def get_current_commit(self, repo_path: Path) -> str:
        """
        Get current commit hash.

        Args:
            repo_path: Path to repository

        Returns:
            Commit hash (short)

        Raises:
            GitOperationError: If getting commit fails
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
                timeout=10
            )
            commit_hash = result.stdout.strip()
            self.logger.debug(f"Current commit: {commit_hash}")
            return commit_hash

        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to get commit hash: {e.stderr}"
            self.logger.error(error_msg)
            raise GitOperationError(error_msg) from e

    def get_branch_name(self, repo_path: Path) -> str:
        """
        Get current branch name.

        Args:
            repo_path: Path to repository

        Returns:
            Branch name

        Raises:
            GitOperationError: If getting branch fails
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
                timeout=10
            )
            branch = result.stdout.strip()
            self.logger.debug(f"Current branch: {branch}")
            return branch

        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to get branch name: {e.stderr}"
            self.logger.error(error_msg)
            raise GitOperationError(error_msg) from e
