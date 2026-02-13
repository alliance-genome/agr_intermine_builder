#!/usr/bin/env python3
"""
AllianceMine Database Promotion Script

Promotes an RC (release candidate) database to production by renaming it.

Example:
    # Rename alliancemine_8_3_0_rc2 -> alliancemine_8_3_0
    python3 promote_db.py --release 8.3.0 --rc 2

    # Dry-run to see what would happen
    python3 promote_db.py --release 8.3.0 --rc 2 --dry-run
"""

import os
import sys
import argparse
import subprocess
import logging

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def sanitize_version(version: str) -> str:
    """Convert version dots to underscores: 8.3.0 -> 8_3_0."""
    return version.replace(".", "_")


def run_sql(sql: str, database: str = "postgres") -> tuple:
    """Execute SQL against RDS, returns (success, output)."""
    host = os.environ.get("RDS_HOST", "localhost")
    port = os.environ.get("RDS_PORT", "5432")
    user = os.environ.get("RDS_USER", "postgres")

    result = subprocess.run(
        ["psql", "-h", host, "-p", port, "-U", user, "-d", database, "-tAc", sql],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "PGPASSWORD": os.environ.get("RDS_PASSWORD", "")},
    )
    return result.returncode == 0, result.stdout.strip()


def db_exists(db_name: str) -> bool:
    """Check if a database exists."""
    ok, result = run_sql(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'")
    return ok and result == "1"


def terminate_connections(db_name: str) -> None:
    """Terminate all active connections to a database."""
    sql = (
        "SELECT pg_terminate_backend(pid) "
        "FROM pg_stat_activity "
        f"WHERE datname = '{db_name}' AND pid <> pg_backend_pid()"
    )
    run_sql(sql)
    logger.info(f"Terminated active connections to {db_name}")


def promote(release: str, rc: int, dry_run: bool = False) -> bool:
    """Promote RC database to production name."""
    ver = sanitize_version(release)
    rc_name = f"alliancemine_{ver}_rc{rc}"
    prod_name = f"alliancemine_{ver}"

    logger.info("=" * 50)
    logger.info("Database Promotion")
    logger.info("=" * 50)
    logger.info(f"  RC database:   {rc_name}")
    logger.info(f"  Prod database: {prod_name}")
    logger.info(f"  Dry run:       {dry_run}")
    logger.info("=" * 50)

    # Verify RC database exists
    if not db_exists(rc_name):
        logger.error(f"RC database '{rc_name}' does not exist")
        return False

    # Check if prod name already exists
    if db_exists(prod_name):
        logger.warning(f"Production database '{prod_name}' already exists")
        if dry_run:
            logger.info("[DRY RUN] Would drop existing production database")
        else:
            logger.info(f"Dropping existing {prod_name}...")
            terminate_connections(prod_name)
            ok, _ = run_sql(f'DROP DATABASE "{prod_name}"')
            if not ok:
                logger.error(f"Failed to drop {prod_name}")
                return False

    if dry_run:
        logger.info(f"[DRY RUN] Would rename {rc_name} -> {prod_name}")
        return True

    # Terminate connections to RC database before rename
    terminate_connections(rc_name)

    # Rename
    logger.info(f"Renaming {rc_name} -> {prod_name}...")
    ok, _ = run_sql(f'ALTER DATABASE "{rc_name}" RENAME TO "{prod_name}"')
    if not ok:
        logger.error("Database rename failed")
        return False

    # Verify
    if db_exists(prod_name):
        logger.info(f"Promotion successful: {prod_name} is now available")
        return True
    else:
        logger.error("Verification failed - production database not found after rename")
        return False


def main():
    parser = argparse.ArgumentParser(description="Promote RC database to production")
    parser.add_argument("--release", required=True, help="Release version (e.g., 8.3.0)")
    parser.add_argument("--rc", type=int, required=True, help="RC number to promote")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")

    args = parser.parse_args()

    success = promote(args.release, args.rc, dry_run=args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
