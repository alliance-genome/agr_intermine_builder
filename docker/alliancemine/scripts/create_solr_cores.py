#!/usr/bin/env python3
"""
Create versioned Solr cores for a new AllianceMine release.

Copies the schema from existing production cores, clears data,
and registers them with Solr. Cores must exist before the
postprocess step runs create-search-index and create-autocomplete-index.

Usually invoked automatically as a preflight step from build_full.py.
The standalone CLI exists for ops use when a build is half-broken
and you just need cores created (or recreated) without rerunning
the entire pipeline.

Naming pattern matches the database side:
  production:    alliancemine-search-9.0.0,         alliancemine-autocomplete-9.0.0
  RC builds:     alliancemine-search-9.0.0-rc99,    alliancemine-autocomplete-9.0.0-rc99

Usage:
    python3 create_solr_cores.py --release 9.0.0 --solr-host 172.31.59.87
    python3 create_solr_cores.py --release 9.0.0 --rc 99 --solr-host 172.31.59.87
    python3 create_solr_cores.py --release 9.0.0 --solr-host 172.31.59.87 --ssh-key ~/.ssh/AGR-ssl3.pem
"""

import argparse
import subprocess
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

SOLR_DATA_DIR = "/var/solr/data"
SOURCE_CORES = ["alliancemine-search", "alliancemine-autocomplete"]


def run_ssh(host: str, cmd: str, ssh_key: str = None, sudo: bool = False) -> str:
    ssh_cmd = ["ssh"]
    if ssh_key:
        ssh_cmd.extend(["-i", ssh_key])
    ssh_cmd.extend(["-o", "ConnectTimeout=10", f"ec2-user@{host}"])
    if sudo:
        cmd = f"sudo {cmd}"
    ssh_cmd.append(cmd)

    result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"SSH command failed: {result.stderr.strip()}")
    return result.stdout.strip()


def core_suffix(release: str, rc: int = None) -> str:
    """Build the suffix appended to source core names.

    Mirrors construct_db_names() in entrypoint.sh:
      production:  alliancemine-search-9.0.0
      RC build:    alliancemine-search-9.0.0-rc99
    """
    return f"{release}-rc{rc}" if rc else release


def create_cores(host: str, release: str, rc: int = None, ssh_key: str = None) -> bool:
    """Create the versioned search + autocomplete cores. Idempotent."""
    success = True
    suffix = core_suffix(release, rc)
    created_any = False

    for source in SOURCE_CORES:
        target = f"{source}-{suffix}"
        logger.info(f"Creating core: {target} from {source}")

        try:
            # Check if target already exists
            exists = run_ssh(host, f"test -d {SOLR_DATA_DIR}/{target} && echo yes || echo no", ssh_key, sudo=True)
            if exists == "yes":
                logger.info(f"  Core {target} already exists, skipping")
                continue

            # Copy production core config
            run_ssh(host, f"cp -r {SOLR_DATA_DIR}/{source} {SOLR_DATA_DIR}/{target}", ssh_key, sudo=True)

            # Update core.properties
            run_ssh(host, f"sh -c 'echo name={target} > {SOLR_DATA_DIR}/{target}/core.properties'", ssh_key, sudo=True)

            # Clear data (keep only schema/config)
            run_ssh(host, f"rm -rf {SOLR_DATA_DIR}/{target}/data", ssh_key, sudo=True)
            run_ssh(host, f"mkdir {SOLR_DATA_DIR}/{target}/data", ssh_key, sudo=True)

            # Fix ownership
            run_ssh(host, f"chown -R solr:solr {SOLR_DATA_DIR}/{target}", ssh_key, sudo=True)

            logger.info(f"  Created {target}")
            created_any = True

        except (RuntimeError, subprocess.TimeoutExpired) as e:
            logger.error(f"  Failed to create {target}: {e}")
            success = False

    if not success:
        return False

    # Skip Solr restart if everything was already in place — saves a multi-second
    # restart on every build invocation in the common case.
    if not created_any:
        logger.info("All target cores already existed; skipping Solr restart.")
        return True

    # Restart Solr to pick up new cores
    logger.info("Restarting Solr...")
    try:
        run_ssh(host, "-u solr /opt/solr/bin/solr restart", ssh_key, sudo=True)
        logger.info("Solr restarted")
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        logger.error(f"Failed to restart Solr: {e}")
        return False

    # Verify cores
    logger.info("Verifying cores...")
    try:
        output = run_ssh(host, f"python3 -c \"import urllib.request,json; data=json.loads(urllib.request.urlopen('http://localhost:8983/solr/admin/cores?action=STATUS').read()); [print(k) for k in sorted(data['status'])]\"", ssh_key)
        for source in SOURCE_CORES:
            target = f"{source}-{suffix}"
            if target in output:
                logger.info(f"  {target}: OK")
            else:
                logger.error(f"  {target}: NOT FOUND")
                success = False
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        logger.error(f"Failed to verify cores: {e}")
        success = False

    return success


def main():
    parser = argparse.ArgumentParser(description="Create versioned Solr cores for AllianceMine")
    parser.add_argument("--release", required=True, help="Release version (e.g., 9.0.0)")
    parser.add_argument("--rc", type=int, default=None,
                        help="RC number for test builds (e.g., 99 -> alliancemine-search-9.0.0-rc99)")
    parser.add_argument("--solr-host", required=True, help="Solr host IP")
    parser.add_argument("--ssh-key", default=None,
                        help="SSH key file path (omit on hosts where ssh defaults already work)")
    args = parser.parse_args()

    label = core_suffix(args.release, args.rc)
    logger.info(f"Creating Solr cores for {label} on {args.solr_host}")

    if create_cores(args.solr_host, args.release, args.rc, args.ssh_key):
        logger.info("All cores created successfully")
    else:
        logger.error("Some cores failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
