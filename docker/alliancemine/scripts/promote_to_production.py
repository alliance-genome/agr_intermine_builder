#!/usr/bin/env python3
"""
AllianceMine Promote to Production

Promotes an RC build to production:
1. Rename RC database to production name
2. Update properties for production (port 8080)
3. Rebuild WAR with production properties
4. Deploy WAR to production Tomcat (port 8080)

Usage:
    # Promote RC2 of release 9.0.0 to production
    python3 promote_to_production.py --release 9.0.0 --rc 2 --deploy-host ec2-host

    # Dry-run to see what would happen
    python3 promote_to_production.py --release 9.0.0 --rc 2 --deploy-host ec2-host --dry-run

    # Just rename the DB (skip WAR rebuild and deploy)
    python3 promote_to_production.py --release 9.0.0 --rc 2 --db-only
"""

import os
import sys
import subprocess
import argparse
import logging
from pathlib import Path

ALLIANCEMINE_DIR = Path("/root/alliancemine")
PROPERTIES_FILE = Path("/root/.intermine/alliancemine.properties")
SCRIPTS_DIR = Path("/root/scripts")
PRODUCTION_PORT = 8080

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def sanitize_version(version: str) -> str:
    return version.replace(".", "_")


def run_sql(sql: str, database: str = "postgres") -> tuple:
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
    ok, result = run_sql(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'")
    return ok and result == "1"


def terminate_connections(db_name: str) -> None:
    sql = (
        "SELECT pg_terminate_backend(pid) "
        "FROM pg_stat_activity "
        f"WHERE datname = '{db_name}' AND pid <> pg_backend_pid()"
    )
    run_sql(sql)
    logger.info(f"Terminated active connections to {db_name}")


def promote_database(release: str, rc: int, dry_run: bool = False) -> bool:
    """Rename RC database to production name."""
    ver = sanitize_version(release)
    rc_name = f"alliancemine_{ver}_rc{rc}"
    prod_name = f"alliancemine_{ver}"

    logger.info(f"  RC database:   {rc_name}")
    logger.info(f"  Prod database: {prod_name}")

    if not db_exists(rc_name):
        logger.error(f"RC database '{rc_name}' does not exist")
        return False

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

    terminate_connections(rc_name)
    logger.info(f"Renaming {rc_name} -> {prod_name}...")
    ok, _ = run_sql(f'ALTER DATABASE "{rc_name}" RENAME TO "{prod_name}"')
    if not ok:
        logger.error("Database rename failed")
        return False

    if db_exists(prod_name):
        logger.info(f"Database promoted: {prod_name}")
        return True
    else:
        logger.error("Verification failed - production database not found after rename")
        return False


def update_properties_for_production(release: str, deploy_host: str) -> None:
    """Update properties file for production deployment."""
    if not PROPERTIES_FILE.exists():
        logger.warning(f"Properties file not found: {PROPERTIES_FILE}")
        return

    ver = sanitize_version(release)
    prod_db = f"alliancemine_{ver}"

    content = PROPERTIES_FILE.read_text()

    replacements = {
        "db.production.datasource.databaseName": prod_db,
        "db.userprofile-production.datasource.databaseName": "alliancemine_userprofile",
        "webapp.deploy.url": f"http://{deploy_host}:{PRODUCTION_PORT}",
        "webapp.baseurl": f"http://{deploy_host}:{PRODUCTION_PORT}",
        "webapp.hostname": deploy_host,
        "webapp.port": str(PRODUCTION_PORT),
    }

    lines = content.splitlines()
    new_lines = []
    replaced_keys = set()

    for line in lines:
        replaced = False
        for key, value in replacements.items():
            if line.startswith(f"{key}="):
                new_lines.append(f"{key}={value}")
                replaced_keys.add(key)
                replaced = True
                break
        if not replaced:
            new_lines.append(line)

    PROPERTIES_FILE.write_text("\n".join(new_lines) + "\n")

    # Copy to project directory too
    proj_props = ALLIANCEMINE_DIR / "alliancemine.properties"
    proj_props.write_text("\n".join(new_lines) + "\n")

    logger.info(f"Properties updated for production (DB: {prod_db}, port: {PRODUCTION_PORT})")


def rebuild_war() -> bool:
    """Rebuild WAR with production properties."""
    logger.info("Rebuilding WAR file with production properties...")
    result = subprocess.run(
        ["./gradlew", "war", "--stacktrace"],
        cwd=str(ALLIANCEMINE_DIR),
    )
    if result.returncode == 0:
        logger.info("WAR rebuilt successfully")
        return True
    else:
        logger.error("WAR rebuild failed")
        return False


def deploy_to_production(deploy_host: str, manager: str, password: str) -> bool:
    """Deploy WAR to production Tomcat at port 8080."""
    deploy_script = SCRIPTS_DIR / "deploy_war.py"
    if deploy_script.exists():
        result = subprocess.run(
            [
                "python3", str(deploy_script),
                "--host", deploy_host,
                "--port", str(PRODUCTION_PORT),
                "--manager", manager,
                "--password", password,
            ],
        )
        return result.returncode == 0

    # Fallback: direct Gradle deploy
    result = subprocess.run(
        ["./gradlew", "cargoRedeployRemote", "--stacktrace"],
        cwd=str(ALLIANCEMINE_DIR),
    )
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Promote AllianceMine RC to production")
    parser.add_argument("--release", required=True, help="Release version (e.g., 9.0.0)")
    parser.add_argument("--rc", type=int, required=True, help="RC number to promote")
    parser.add_argument("--deploy-host", default=None, help="EC2 host for production deploy")
    parser.add_argument("--manager", default="manager", help="Tomcat manager username")
    parser.add_argument("--password", default="manager", help="Tomcat manager password")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    parser.add_argument("--db-only", action="store_true", help="Only rename DB, skip WAR/deploy")

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("AllianceMine Promote to Production")
    logger.info("=" * 60)
    logger.info(f"  Release:     {args.release}")
    logger.info(f"  RC:          {args.rc}")
    logger.info(f"  Deploy host: {args.deploy_host or 'none'}")
    logger.info(f"  Prod port:   {PRODUCTION_PORT}")
    logger.info(f"  Dry run:     {args.dry_run}")
    logger.info(f"  DB only:     {args.db_only}")
    logger.info("=" * 60)

    # Step 1: Rename database
    logger.info("")
    logger.info("Step 1: Promote database")
    logger.info("-" * 40)
    if not promote_database(args.release, args.rc, dry_run=args.dry_run):
        sys.exit(1)

    if args.db_only:
        logger.info("")
        logger.info("DB-only mode: skipping WAR rebuild and deploy")
        sys.exit(0)

    if args.dry_run:
        logger.info("")
        logger.info("[DRY RUN] Would update properties, rebuild WAR, deploy to port 8080")
        sys.exit(0)

    if not args.deploy_host:
        logger.info("")
        logger.info("No --deploy-host specified, skipping WAR rebuild and deploy")
        logger.info("To deploy manually:")
        logger.info(f"  python3 deploy_war.py --host <ec2-host> --port {PRODUCTION_PORT}")
        sys.exit(0)

    # Step 2: Update properties for production
    logger.info("")
    logger.info("Step 2: Update properties for production")
    logger.info("-" * 40)
    update_properties_for_production(args.release, args.deploy_host)

    # Step 3: Rebuild WAR
    logger.info("")
    logger.info("Step 3: Rebuild WAR with production properties")
    logger.info("-" * 40)
    if not rebuild_war():
        sys.exit(1)

    # Step 4: Deploy to production port
    logger.info("")
    logger.info("Step 4: Deploy to production Tomcat")
    logger.info("-" * 40)
    if not deploy_to_production(args.deploy_host, args.manager, args.password):
        logger.error("Production deployment failed")
        sys.exit(1)

    logger.info("")
    logger.info("=" * 60)
    logger.info("PRODUCTION PROMOTION COMPLETE")
    logger.info("=" * 60)
    ver = sanitize_version(args.release)
    logger.info(f"  Database:  alliancemine_{ver}")
    logger.info(f"  Profile:   alliancemine_userprofile")
    logger.info(f"  URL:       http://{args.deploy_host}:{PRODUCTION_PORT}/alliancemine")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
