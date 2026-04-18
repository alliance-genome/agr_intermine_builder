#!/usr/bin/env python3
"""
AllianceMine Release Script

Automates the deployment of a built AllianceMine to a Tomcat container:
1. Starts a new Tomcat container on the specified port
2. Deploys the WAR via cargoRedeployRemote
3. Verifies the deployment

Prerequisites:
- WAR must be built (run `build` first)
- Tomcat image must exist on the target host
- Solr cores must be created (run create_solr_cores.py first)

Usage:
    python3 release.py --tomcat-host 172.31.59.87 --tomcat-port 8082
    python3 release.py --tomcat-host 172.31.59.87 --tomcat-port 8082 --container-name alliancemine-9.0.0
    python3 release.py --tomcat-host 172.31.59.87 --tomcat-port 8082 --deploy-only  # skip container creation
"""

import argparse
import os
import subprocess
import sys
import time
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

ALLIANCEMINE_DIR = Path("/root/alliancemine")


def update_deploy_properties(host: str, port: int) -> None:
    """Update alliancemine.properties to point at the target Tomcat."""
    props_file = Path("/root/.intermine/alliancemine.properties")
    project_props = ALLIANCEMINE_DIR / "alliancemine.properties"

    logger.info(f"Setting deploy target: {host}:{port}")

    for pfile in [props_file, project_props]:
        if not pfile.exists():
            continue
        content = pfile.read_text()
        lines = []
        for line in content.splitlines():
            if line.startswith("webapp.deploy.url="):
                lines.append(f"webapp.deploy.url=http://{host}:{port}")
            elif line.startswith("webapp.hostname="):
                lines.append(f"webapp.hostname={host}")
            elif line.startswith("webapp.port="):
                lines.append(f"webapp.port={port}")
            else:
                lines.append(line)
        pfile.write_text("\n".join(lines) + "\n")


def deploy_war() -> bool:
    """Deploy WAR via Gradle cargoRedeployRemote."""
    logger.info("Deploying WAR via cargoRedeployRemote...")

    os.chdir(ALLIANCEMINE_DIR)
    result = subprocess.run(
        ["./gradlew", "cargoRedeployRemote", "--stacktrace"],
        timeout=120,
    )

    if result.returncode != 0:
        logger.error("WAR deployment failed")
        return False

    logger.info("WAR deployed successfully")
    return True


def verify_deployment(host: str, port: int, timeout: int = 180) -> bool:
    """Wait for the webapp to respond on the version endpoint."""
    from urllib.request import urlopen
    from urllib.error import URLError

    url = f"http://{host}:{port}/alliancemine/service/version"
    logger.info(f"Verifying deployment at {url} (timeout {timeout}s)...")

    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = urlopen(url, timeout=10)
            version = resp.read().decode().strip()
            if version:
                logger.info(f"Deployment verified — InterMine version: {version}")
                return True
        except (URLError, OSError, TimeoutError):
            pass
        time.sleep(10)

    logger.error(f"Deployment verification timed out after {timeout}s")
    return False


def main():
    parser = argparse.ArgumentParser(description="Deploy AllianceMine WAR to Tomcat")
    parser.add_argument("--tomcat-host", required=True, help="Tomcat host IP")
    parser.add_argument("--tomcat-port", type=int, default=8082, help="Tomcat port (default: 8082)")
    parser.add_argument("--container-name", default=None, help="Docker container name (default: alliancemine-{release})")
    parser.add_argument("--tomcat-image", default="intermine-tomcat:latest", help="Tomcat Docker image")
    parser.add_argument("--deploy-only", action="store_true", help="Skip container creation, just deploy WAR")
    parser.add_argument("--verify-timeout", type=int, default=180, help="Verification timeout in seconds")
    args = parser.parse_args()

    release = os.environ.get("ALLIANCE_RELEASE", "unknown")
    container_name = args.container_name or f"alliancemine-{release}"

    logger.info("=" * 60)
    logger.info("AllianceMine Release")
    logger.info("=" * 60)
    logger.info(f"Release:   {release}")
    logger.info(f"Target:    {args.tomcat_host}:{args.tomcat_port}")
    logger.info(f"Container: {container_name}")
    logger.info(f"Image:     {args.tomcat_image}")
    logger.info("=" * 60)

    # Step 1: Update properties
    update_deploy_properties(args.tomcat_host, args.tomcat_port)

    # Step 2: Deploy WAR
    if not deploy_war():
        sys.exit(1)

    # Step 3: Verify
    if not verify_deployment(args.tomcat_host, args.tomcat_port, args.verify_timeout):
        logger.error("Deployment verification failed")
        logger.error("Check Tomcat logs for errors")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Release complete")
    logger.info(f"URL: http://{args.tomcat_host}:{args.tomcat_port}/alliancemine/")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
