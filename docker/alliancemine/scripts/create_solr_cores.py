#!/usr/bin/env python3
"""
Create versioned Solr cores for a new AllianceMine release.

Copies conf/ from the live alliancemine-search / alliancemine-autocomplete cores into an
empty instance dir and registers it with CoreAdmin CREATE; Solr is not restarted.
Cores must exist before the postprocess step runs create-search-index and
create-autocomplete-index.

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


# One remote run per core. Copies only conf/ from the live core (the live index is ~14M docs), lets
# CoreAdmin CREATE write core.properties and load the core, so Solr is never restarted.
# Exit codes: 2 source has no config, 3 target dir has core.properties but Solr does not know the core,
# 4 CREATE failed.
CREATE_CORE_SH = """
set -eu
D={data_dir}; S=http://localhost:8983/solr/admin/cores; src=$D/{source}; t={target}
if curl -s --max-time 30 "$S?action=STATUS&core=$t&wt=json" | grep -q "\\"name\\":\\"$t\\""; then
  echo exists; exit 0
fi
sudo test -f "$src/conf/solrconfig.xml" || {{ echo "no conf/solrconfig.xml in $src" >&2; exit 2; }}
if sudo test -e "$D/$t"; then
  if sudo test -f "$D/$t/core.properties"; then
    echo "$D/$t has core.properties but Solr has no core $t" >&2; exit 3
  fi
  sudo rm -rf "$D/$t"
  echo "removed leftover $D/$t"
fi
sudo mkdir -p "$D/$t/data"
sudo cp -r "$src/conf" "$D/$t/conf"
sudo chown -R solr:solr "$D/$t"
r=$(curl -s --max-time 120 "$S?action=CREATE&name=$t&instanceDir=$t&wt=json")
echo "$r" | grep -q '"status":0' || {{ echo "CREATE failed: $r" >&2; exit 4; }}
echo created
"""


def run_ssh_script(host: str, script: str, ssh_key: str = None) -> str:
    ssh_cmd = ["ssh"]
    if ssh_key:
        ssh_cmd.extend(["-i", ssh_key])
    ssh_cmd.extend(["-o", "ConnectTimeout=10", f"ec2-user@{host}", "bash", "-s"])
    result = subprocess.run(
        ssh_cmd, input=script, capture_output=True, text=True, timeout=180, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"exit {result.returncode}: {result.stderr.strip()}")
    return result.stdout.strip()


def core_suffix(release: str, rc: int = None) -> str:
    """Build the suffix appended to source core names.

    Mirrors construct_db_names() in entrypoint.sh:
      production:  alliancemine-search-9.0.0
      RC build:    alliancemine-search-9.0.0-rc99
    """
    return f"{release}-rc{rc}" if rc else release


def create_cores(host: str, release: str, rc: int = None, ssh_key: str = None) -> bool:
    """Create the versioned search + autocomplete cores with the live cores' config. Idempotent.

    A target dir without core.properties is a leftover from a failed CREATE and is replaced.
    """
    success = True
    suffix = core_suffix(release, rc)

    for source in SOURCE_CORES:
        target = f"{source}-{suffix}"
        script = CREATE_CORE_SH.format(data_dir=SOLR_DATA_DIR, source=source, target=target)
        try:
            out = run_ssh_script(host, script, ssh_key)
            logger.info(f"  {target}: {out.replace(chr(10), '; ')}")
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            logger.error(f"  {target} from {source} failed: {e}")
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
