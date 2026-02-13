#!/usr/bin/env python3
"""
AllianceMine WAR Deployment Script

Deploys the AllianceMine WAR file to a remote Tomcat server
using Gradle's cargoRedeployRemote task.

Usage:
    python3 deploy_war.py --host ec2-host.example.com --port 8080
    python3 deploy_war.py --host ec2-host --port 9099 --manager admin --password secret
"""

import os
import sys
import subprocess
import argparse
import logging
from pathlib import Path

ALLIANCEMINE_DIR = Path("/root/alliancemine")
PROPERTIES_FILE = Path("/root/.intermine/alliancemine.properties")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def deploy(host: str, port: int, manager: str, password: str) -> bool:
    """Deploy WAR to remote Tomcat via cargoRedeployRemote."""
    logger.info("=" * 50)
    logger.info("WAR Deployment")
    logger.info("=" * 50)
    logger.info(f"  Target: {host}:{port}")
    logger.info(f"  Manager: {manager}")
    logger.info("=" * 50)

    # Update properties with deploy target
    _update_deploy_properties(host, port, manager, password)

    # Check WAR file exists
    war_dir = ALLIANCEMINE_DIR / "webapp" / "build" / "libs"
    war_files = list(war_dir.glob("*.war")) if war_dir.exists() else []
    if not war_files:
        logger.error("No WAR file found. Run 'build_full.py' first or './gradlew war'")
        return False

    logger.info(f"WAR file: {war_files[0]}")

    # Run Gradle deploy
    result = subprocess.run(
        ["./gradlew", "cargoRedeployRemote", "--stacktrace"],
        cwd=str(ALLIANCEMINE_DIR),
    )

    if result.returncode == 0:
        logger.info(f"Deployed successfully to {host}:{port}/alliancemine")
        return True
    else:
        logger.error("Deployment failed")
        return False


def _update_deploy_properties(host: str, port: int, manager: str, password: str) -> None:
    """Update the properties file with deploy target."""
    if not PROPERTIES_FILE.exists():
        logger.warning(f"Properties file not found: {PROPERTIES_FILE}")
        return

    content = PROPERTIES_FILE.read_text()

    replacements = {
        "webapp.deploy.url": f"http://{host}:{port}",
        "webapp.baseurl": f"http://{host}:{port}",
        "webapp.hostname": host,
        "webapp.port": str(port),
        "webapp.manager": manager,
        "webapp.password": password,
        "tomcat.user": manager,
        "tomcat.pwd": password,
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

    # Append any keys that weren't already in the file
    for key, value in replacements.items():
        if key not in replaced_keys:
            new_lines.append(f"{key}={value}")

    PROPERTIES_FILE.write_text("\n".join(new_lines) + "\n")
    logger.info("Updated properties with deploy target")


def main():
    parser = argparse.ArgumentParser(description="Deploy AllianceMine WAR to remote Tomcat")
    parser.add_argument("--host", required=True, help="Target Tomcat hostname")
    parser.add_argument("--port", type=int, default=8080, help="Target Tomcat port (default: 8080)")
    parser.add_argument("--manager", default="manager", help="Tomcat manager username")
    parser.add_argument("--password", default="manager", help="Tomcat manager password")

    args = parser.parse_args()

    success = deploy(args.host, args.port, args.manager, args.password)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
