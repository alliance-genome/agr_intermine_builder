#!/usr/bin/env python3
"""
AllianceMine Build Automation Script

Automates the process of:
1. Setting database version suffix
2. Restarting container with new configuration
3. Running gradlew clean buildDB in the container

Usage:
    # Build base version
    python3 build_mine.py

    # Build with iteration suffix
    python3 build_mine.py -1

    # Build with patch suffix
    python3 build_mine.py -patch1

    # Build test version
    python3 build_mine.py -test

    # Skip buildDB (just set version and restart)
    python3 build_mine.py -1 --skip-build
"""

import sys
import subprocess
import argparse
import time
from pathlib import Path


def run_command(cmd: list, description: str, check: bool = True) -> subprocess.CompletedProcess:
    """
    Run a shell command and display progress.

    Args:
        cmd: Command as list of strings
        description: Human-readable description
        check: Whether to raise exception on non-zero exit

    Returns:
        CompletedProcess object
    """
    print(f"{'=' * 60}")
    print(f"🔧 {description}")
    print(f"{'=' * 60}")
    print(f"Running: {' '.join(cmd)}")
    print()

    result = subprocess.run(cmd, check=check)

    if result.returncode == 0:
        print(f"✅ {description} completed successfully")
    else:
        print(f"❌ {description} failed with exit code {result.returncode}")

    print()
    return result


def set_db_version(suffix: str) -> None:
    """
    Set database version suffix in .env file.

    Args:
        suffix: Version suffix (empty string for base version)
    """
    script_path = Path(__file__).parent / "set_db_version.py"

    if suffix:
        run_command(
            ["python3", str(script_path), suffix],
            f"Setting database version suffix: {suffix}"
        )
    else:
        run_command(
            ["python3", str(script_path)],
            "Setting database version (base, no suffix)"
        )


def restart_container() -> None:
    """Restart docker-compose to pick up new environment variables."""
    run_command(
        ["docker-compose", "down"],
        "Stopping containers"
    )

    time.sleep(2)

    run_command(
        ["docker-compose", "up", "-d"],
        "Starting containers with new configuration"
    )

    # Wait for container to be healthy
    print("⏳ Waiting for container to be ready...")
    time.sleep(10)
    print()


def run_builddb() -> None:
    """Run gradlew clean buildDB inside the container."""
    run_command(
        [
            "docker-compose", "exec", "-T", "alliancemine",
            "bash", "-c",
            "cd /opt/intermine/alliancemine && ./gradlew clean buildDB --stacktrace"
        ],
        "Running gradlew clean buildDB",
        check=False  # Don't fail script if build fails
    )


def main():
    parser = argparse.ArgumentParser(
        description="Automate AllianceMine database build with versioning",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                 # Build base version (8.3.0)
  %(prog)s -1              # Build iteration 1 (8.3.0-1)
  %(prog)s -2              # Build iteration 2 (8.3.0-2)
  %(prog)s -patch1         # Build patch 1 (8.3.0-patch1)
  %(prog)s -test           # Build test version (8.3.0-test)
  %(prog)s -1 --skip-build # Just set version and restart (no buildDB)
        """
    )

    parser.add_argument(
        "suffix",
        nargs="?",
        default="",
        help="Database version suffix (e.g., -1, -2, -patch1, -test). Leave empty for base version."
    )

    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip running gradlew buildDB (only set version and restart container)"
    )

    args = parser.parse_args()

    print()
    print("=" * 60)
    print("🚀 AllianceMine Build Automation")
    print("=" * 60)
    print()

    try:
        # Step 1: Set database version
        set_db_version(args.suffix)

        # Step 2: Restart container
        restart_container()

        # Step 3: Run buildDB (unless skipped)
        if not args.skip_build:
            run_builddb()

            print()
            print("=" * 60)
            print("✅ Build Process Complete!")
            print("=" * 60)
            print()
            print("Next steps:")
            print("  1. Check logs: docker-compose logs -f alliancemine")
            print("  2. Load data: docker-compose exec alliancemine bash")
            print("  3. Run post-processing and deploy webapp")
            print()
        else:
            print()
            print("=" * 60)
            print("✅ Container Restarted with New Database Version")
            print("=" * 60)
            print()
            print("Skipped buildDB as requested.")
            print("To run buildDB manually:")
            print("  docker-compose exec alliancemine bash -c 'cd /opt/intermine/alliancemine && ./gradlew clean buildDB'")
            print()

    except subprocess.CalledProcessError as e:
        print()
        print("=" * 60)
        print(f"❌ Build process failed at step: {e.cmd}")
        print("=" * 60)
        sys.exit(1)
    except KeyboardInterrupt:
        print()
        print("=" * 60)
        print("⚠️  Build process interrupted by user")
        print("=" * 60)
        sys.exit(130)


if __name__ == "__main__":
    main()
