#!/usr/bin/env python3
"""
Set AllianceMine release version from Alliance FMS API or manual input.

Usage:
    # Set to current release from API
    python -m src.cli.set_release current

    # Set to next release from API
    python -m src.cli.set_release next

    # Set to specific version
    python -m src.cli.set_release 8.3.0

    # Show current setting
    python -m src.cli.set_release show
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import requests


def get_project_root() -> Path:
    """Get the project root directory."""
    current = Path(__file__).resolve()
    # Navigate up from src/cli/set_release.py to project root
    return current.parent.parent.parent


def get_env_file() -> Path:
    """Get the .env file path."""
    return get_project_root() / ".env"


def fetch_release_from_api(endpoint: str) -> str:
    """
    Fetch release version from Alliance FMS API.

    Args:
        endpoint: Either 'current' or 'next'

    Returns:
        Release version string (e.g., '8.2.0')

    Raises:
        RuntimeError: If API request fails
    """
    url = f"https://fms.alliancegenome.org/api/releaseversion/{endpoint}"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        version = data.get("releaseVersion")

        if not version:
            raise RuntimeError(f"No releaseVersion field in API response: {data}")

        return version

    except requests.RequestException as e:
        raise RuntimeError(f"Failed to fetch {endpoint} release from {url}: {e}")


def get_current_release() -> str | None:
    """Get current ALLIANCE_RELEASE from .env file."""
    env_file = get_env_file()

    if not env_file.exists():
        return None

    content = env_file.read_text()
    match = re.search(r'^ALLIANCE_RELEASE=(.+)$', content, re.MULTILINE)

    if match:
        return match.group(1).strip()

    return None


def update_env_file(version: str) -> None:
    """
    Update ALLIANCE_RELEASE in .env file.

    Args:
        version: Release version to set (e.g., '8.3.0')
    """
    env_file = get_env_file()

    if not env_file.exists():
        raise FileNotFoundError(f".env file not found at {env_file}")

    content = env_file.read_text()

    # Check if ALLIANCE_RELEASE exists
    if re.search(r'^ALLIANCE_RELEASE=', content, re.MULTILINE):
        # Update existing value
        new_content = re.sub(
            r'^ALLIANCE_RELEASE=.+$',
            f'ALLIANCE_RELEASE={version}',
            content,
            flags=re.MULTILINE
        )
    else:
        # Add new line after Alliance release version comment or at end
        if '# Alliance release version' in content:
            new_content = re.sub(
                r'(# Alliance release version\n)',
                f'\\1ALLIANCE_RELEASE={version}\n',
                content
            )
        else:
            # Append at end
            new_content = content.rstrip() + f'\n\n# Alliance release version\nALLIANCE_RELEASE={version}\n'

    env_file.write_text(new_content)


def show_current() -> None:
    """Display current release version."""
    current = get_current_release()

    if current:
        print(f"Current ALLIANCE_RELEASE: {current}")
    else:
        print("ALLIANCE_RELEASE not set in .env file")

    # Also show what's available from API
    try:
        api_current = fetch_release_from_api("current")
        api_next = fetch_release_from_api("next")
        print(f"\nAvailable from Alliance API:")
        print(f"  Current: {api_current}")
        print(f"  Next:    {api_next}")
    except RuntimeError as e:
        print(f"\nWarning: Could not fetch from API: {e}", file=sys.stderr)


def validate_version(version: str) -> bool:
    """Validate version format (e.g., 8.2.0)."""
    return bool(re.match(r'^\d+\.\d+\.\d+$', version))


def main():
    parser = argparse.ArgumentParser(
        description="Set AllianceMine release version",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Set to current release from Alliance API
  python -m src.cli.set_release current

  # Set to next release from Alliance API
  python -m src.cli.set_release next

  # Set to specific version
  python -m src.cli.set_release 8.3.0

  # Show current setting and available versions
  python -m src.cli.set_release show
        """
    )

    parser.add_argument(
        'version',
        help='Release version: "current", "next", "show", or explicit version (e.g., 8.3.0)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be changed without modifying .env'
    )

    args = parser.parse_args()

    # Handle 'show' command
    if args.version.lower() == 'show':
        show_current()
        return

    # Determine version to set
    version = None
    source = None

    if args.version.lower() in ('current', 'next'):
        # Fetch from API
        try:
            version = fetch_release_from_api(args.version.lower())
            source = f"Alliance API ({args.version})"
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    else:
        # Manual version
        version = args.version
        source = "manual input"

        if not validate_version(version):
            print(f"Error: Invalid version format '{version}'. Expected format: X.Y.Z (e.g., 8.3.0)", file=sys.stderr)
            sys.exit(1)

    # Show current state
    current = get_current_release()
    print(f"Current ALLIANCE_RELEASE: {current or '(not set)'}")
    print(f"New ALLIANCE_RELEASE:     {version} (from {source})")

    if current == version:
        print("\n✅ Already set to this version. No changes needed.")
        return

    # Update .env file
    if args.dry_run:
        print("\n🔍 DRY RUN: Would update .env file (use without --dry-run to apply)")
    else:
        try:
            update_env_file(version)
            print(f"\n✅ Updated .env file: ALLIANCE_RELEASE={version}")
            print(f"\nNext steps:")
            print(f"  cd docker/alliancemine-unified")
            print(f"  docker-compose build --build-arg ALLIANCE_RELEASE={version}")
            print(f"  docker-compose up -d")
        except Exception as e:
            print(f"\nError updating .env: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
