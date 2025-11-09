#!/usr/bin/env python3
"""
Set Database Version Script

Helper script to set the database version suffix for AllianceMine builds.

Usage:
    python3 set_db_version.py              # Use base version (no suffix)
    python3 set_db_version.py -1           # First iteration
    python3 set_db_version.py -2           # Second iteration
    python3 set_db_version.py -patch1      # Patch version
    python3 set_db_version.py -test        # Test build
"""

import sys
import re
from pathlib import Path


def update_env_file(suffix: str = "") -> None:
    """
    Update DB_VERSION_SUFFIX in .env file.

    Args:
        suffix: Version suffix to set (empty string for base version)
    """
    env_file = Path(".env")

    if not env_file.exists():
        print("Error: .env file not found")
        sys.exit(1)

    # Read current .env file
    content = env_file.read_text()

    # Update DB_VERSION_SUFFIX line
    updated_content = re.sub(
        r'^DB_VERSION_SUFFIX=.*$',
        f'DB_VERSION_SUFFIX={suffix}',
        content,
        flags=re.MULTILINE
    )

    # Write back
    env_file.write_text(updated_content)

    # Extract ALLIANCE_RELEASE for display
    match = re.search(r'^ALLIANCE_RELEASE=(.+)$', content, re.MULTILINE)
    release = match.group(1) if match else "unknown"

    # Display configuration
    print("=" * 50)
    print("Database Version Configuration")
    print("=" * 50)
    print(f"Release: {release}")
    print(f"Suffix: {suffix if suffix else '<none>'}")
    print()
    print("Database names will be:")
    print(f"  Main: alliancemine_{release}{suffix}")
    print(f"  Profile: alliancemine_profiles_{release}{suffix}")
    print()
    print("(Dots will be converted to underscores in actual database names)")
    print("=" * 50)


def main():
    suffix = sys.argv[1] if len(sys.argv) > 1 else ""
    update_env_file(suffix)


if __name__ == "__main__":
    main()
