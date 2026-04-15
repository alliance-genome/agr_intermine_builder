# Multi-Tenant Production Alignment — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Align the agr_intermine_builder codebase with the reality that multi-tenant Docker is production, by cleaning up legacy code, adding deployment automation, consolidating docs, and parameterizing configs.

**Architecture:** No new abstractions. The Python orchestration layer and Docker build container already target Docker + RDS correctly. This plan cleans up the surrounding code, adds a deploy script, consolidates 19 docs into 5, archives legacy code, and removes hardcoded infrastructure values.

**Tech Stack:** Python 3.9+, Docker, subprocess SSH, argparse

---

### Task 1: Commit extract_data.py rewrite

The FMS Snapshot API rewrite of extract_data.py has been sitting uncommitted. Commit it.

**Files:**
- Stage: `docker/alliancemine/scripts/extract_data.py`

**Step 1: Review the diff**

Run: `git diff docker/alliancemine/scripts/extract_data.py | head -100`
Expected: Shows the FMS Snapshot API changes (dataType/dataSubType mapping, gzip handling)

**Step 2: Commit**

```bash
git add docker/alliancemine/scripts/extract_data.py
git commit -m "Rewrite extract_data.py to use FMS Snapshot API

Replace hardcoded FTP paths with FMS dataType/dataSubType mapping.
Add gzip decompression, per-MOD BGI/GAF downloads, and 50+ file
mappings matching project.xml expectations."
```

---

### Task 2: Archive legacy code

Create a git tag preserving the legacy code, then remove the directory.

**Files:**
- Remove: `legacy/` (entire directory)

**Step 1: Create archive tag**

```bash
git tag -a archive/legacy-code -m "Archive legacy build scripts and Docker configs before cleanup"
```

**Step 2: Remove legacy directory**

```bash
git rm -r legacy/
```

**Step 3: Commit**

```bash
git commit -m "Remove legacy/ directory

Legacy bash scripts, old Docker configs, and deprecated builder code
archived at tag 'archive/legacy-code'. Access via:
  git show archive/legacy-code:legacy/"
```

---

### Task 3: Parameterize hardcoded infrastructure values

Replace hardcoded RDS endpoints, AWS account IDs, and resource IDs with environment variables.

**Files:**
- Modify: `docker/alliancemine/.env.example`
- Modify: `docker/alliancemine-unified/.env.example`
- Modify: `docker/wormmine-unified/.env.example`
- Modify: `docker/alliancemine-unified/docker-compose.yml`
- Modify: `docker/wormmine-unified/docker-compose.yml`
- Modify: `scripts/docker-compose.multitenant.yml`
- Modify: `scripts/launch_multitenant_ec2.sh`
- Modify: `scripts/auto-push-ecr.sh`

**Step 1: Fix .env.example files**

In `docker/alliancemine/.env.example`, line 5, replace:
```
RDS_HOST=intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com
```
with:
```
RDS_HOST=your-rds-endpoint.region.rds.amazonaws.com
```

Do the same for `docker/alliancemine-unified/.env.example` (line 16) and `docker/wormmine-unified/.env.example` (line 25).

**Step 2: Remove hardcoded default from unified docker-compose files**

In `docker/alliancemine-unified/docker-compose.yml`, line 53, replace:
```yaml
RDS_HOST: ${RDS_HOST:-intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com}
```
with:
```yaml
RDS_HOST: ${RDS_HOST:?RDS_HOST must be set in .env}
```

Same for `docker/wormmine-unified/docker-compose.yml` line 51.

**Step 3: Parameterize multitenant compose**

In `scripts/docker-compose.multitenant.yml`, replace all 6 occurrences of:
```yaml
image: 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_MINENAME:latest
```
with:
```yaml
image: ${ECR_REGISTRY:-100225593120.dkr.ecr.us-east-1.amazonaws.com}/agr_MINENAME:${IMAGE_TAG:-latest}
```

Add `ECR_REGISTRY` and `IMAGE_TAG` to the top of the file or reference a `.env`.

**Step 4: Parameterize launch script**

In `scripts/launch_multitenant_ec2.sh`, lines 8-13, replace hardcoded values with env var defaults:
```bash
INSTANCE_TYPE="${INSTANCE_TYPE:-c7i.4xlarge}"
REGION="${AWS_REGION:-us-east-1}"
KEY_NAME="${KEY_NAME:-AGR-ssl3}"
SUBNET_ID="${SUBNET_ID:-subnet-ff838bd5}"
SECURITY_GROUP_IDS="${SECURITY_GROUP_IDS:-sg-21ac675b sg-0415cab61ab6b45c5}"
IAM_INSTANCE_PROFILE="${IAM_INSTANCE_PROFILE:-S3DataAccess}"
```

For line 229 (ECR login inside USER_DATA), replace hardcoded account ID:
```bash
ECR_REGISTRY="${AWS_ACCOUNT_ID:-100225593120}.dkr.ecr.${REGION}.amazonaws.com"
```

**Step 5: Parameterize ECR push script**

In `scripts/auto-push-ecr.sh`, line 120, replace hardcoded account ID in the log message with the variable already defined earlier in the script (if one exists), or add `ECR_REGISTRY` variable.

**Step 6: Commit**

```bash
git add docker/alliancemine/.env.example \
        docker/alliancemine-unified/.env.example \
        docker/wormmine-unified/.env.example \
        docker/alliancemine-unified/docker-compose.yml \
        docker/wormmine-unified/docker-compose.yml \
        scripts/docker-compose.multitenant.yml \
        scripts/launch_multitenant_ec2.sh \
        scripts/auto-push-ecr.sh
git commit -m "Parameterize hardcoded RDS endpoints and AWS account IDs

Replace hardcoded infrastructure values with environment variables:
- RDS endpoints in .env.example files use placeholders
- Unified docker-compose files fail fast if RDS_HOST not set
- Multitenant compose uses ECR_REGISTRY variable
- Launch script accepts env vars for all AWS resource IDs"
```

---

### Task 4: Mark unified Docker dirs as deprecated

**Files:**
- Modify: `docker/alliancemine-unified/README.md` (add deprecation notice at top)
- Create or modify: `docker/wormmine-unified/README.md` (add deprecation notice at top)

**Step 1: Add deprecation notice to alliancemine-unified README**

Prepend to `docker/alliancemine-unified/README.md`:
```markdown
> **DEPRECATED**: This unified container setup (Tomcat + Solr + Build in one image) is
> superseded by `docker/alliancemine/` (build-only container) + multi-tenant EC2 deployment.
> Kept for reference. See `docs/DEPLOYMENT.md` for the current approach.

---

```

**Step 2: Add deprecation notice to wormmine-unified**

If `docker/wormmine-unified/README.md` exists, prepend the same notice (adjusted for wormmine). If it doesn't exist, create it with just the deprecation notice.

**Step 3: Commit**

```bash
git add docker/alliancemine-unified/README.md docker/wormmine-unified/README.md
git commit -m "Mark alliancemine-unified and wormmine-unified as deprecated"
```

---

### Task 5: Write deployment script

**Files:**
- Create: `scripts/deploy.py`
- Create: `tests/test_deploy.py`

**Step 1: Write the test**

Create `tests/test_deploy.py`:
```python
"""Tests for deploy.py mine registry and argument parsing."""
import subprocess
import sys
from unittest.mock import patch, MagicMock

import pytest

# Import will be tested after creation
sys.path.insert(0, "scripts")


class TestMineRegistry:
    """Test the MINE_REGISTRY configuration."""

    def test_alliancemine_in_registry(self):
        from deploy import MINE_REGISTRY
        assert "alliancemine" in MINE_REGISTRY

    def test_wormmine_in_registry(self):
        from deploy import MINE_REGISTRY
        assert "wormmine" in MINE_REGISTRY

    def test_registry_has_required_fields(self):
        from deploy import MINE_REGISTRY
        for name, config in MINE_REGISTRY.items():
            assert "port" in config, f"{name} missing 'port'"
            assert "image" in config, f"{name} missing 'image'"
            assert "health_path" in config, f"{name} missing 'health_path'"


class TestArgumentParsing:
    """Test CLI argument parsing."""

    def test_single_mine(self):
        from deploy import parse_args
        args = parse_args(["alliancemine"])
        assert args.mines == ["alliancemine"]

    def test_all_mines(self):
        from deploy import parse_args, MINE_REGISTRY
        args = parse_args(["--all"])
        assert set(args.mines) == set(MINE_REGISTRY.keys())

    def test_dry_run(self):
        from deploy import parse_args
        args = parse_args(["alliancemine", "--dry-run"])
        assert args.dry_run is True

    def test_custom_host(self):
        from deploy import parse_args
        args = parse_args(["alliancemine", "--host", "10.0.0.1"])
        assert args.host == "10.0.0.1"

    def test_no_mine_no_all_fails(self):
        from deploy import parse_args
        with pytest.raises(SystemExit):
            parse_args([])


class TestSSHCommand:
    """Test SSH command construction."""

    def test_build_ssh_command(self):
        from deploy import build_ssh_cmd
        cmd = build_ssh_cmd("172.31.59.87", "~/.ssh/key.pem", "docker ps")
        assert "ssh" in cmd
        assert "-i" in cmd
        assert "~/.ssh/key.pem" in cmd
        assert "ec2-user@172.31.59.87" in cmd
        assert "docker ps" in cmd

    def test_ssh_command_strict_host_off(self):
        from deploy import build_ssh_cmd
        cmd = build_ssh_cmd("host", "key", "ls")
        assert "StrictHostKeyChecking=no" in " ".join(cmd)


class TestHealthCheck:
    """Test health check URL construction."""

    def test_health_url(self):
        from deploy import get_health_url
        url = get_health_url("172.31.59.87", 8080, "/alliancemine/service/version")
        assert url == "http://172.31.59.87:8080/alliancemine/service/version"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_deploy.py -v`
Expected: ModuleNotFoundError (deploy module doesn't exist yet)

**Step 3: Write the deployment script**

Create `scripts/deploy.py`:
```python
#!/usr/bin/env python3
"""Deploy mines to the multi-tenant EC2 instance.

Usage:
    python3 scripts/deploy.py alliancemine
    python3 scripts/deploy.py wormmine
    python3 scripts/deploy.py --all
    python3 scripts/deploy.py alliancemine --dry-run
"""
import argparse
import os
import subprocess
import sys
import time

MINE_REGISTRY = {
    "alliancemine": {
        "port": 8080,
        "image": "agr_alliancemine",
        "health_path": "/alliancemine/service/version",
        "compose_service": "alliancemine-tomcat",
    },
    "wormmine": {
        "port": 8081,
        "image": "agr_wormmine",
        "health_path": "/wormmine/service/version",
        "compose_service": "wormmine-tomcat",
    },
}

DEFAULT_SSH_KEY = os.path.expanduser("~/.ssh/AGR-ssl3.pem")
DEFAULT_REGION = "us-east-1"
HEALTH_TIMEOUT = 120
HEALTH_INTERVAL = 10


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Deploy mines to multi-tenant EC2")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("mine", nargs="?", choices=list(MINE_REGISTRY.keys()),
                       help="Mine to deploy")
    group.add_argument("--all", action="store_true", help="Deploy all mines")
    parser.add_argument("--host", default=os.environ.get("DEPLOY_HOST"),
                        help="EC2 host (or set DEPLOY_HOST env var)")
    parser.add_argument("--ssh-key", default=os.environ.get("DEPLOY_SSH_KEY", DEFAULT_SSH_KEY),
                        help="SSH key path")
    parser.add_argument("--ecr-registry", default=os.environ.get("ECR_REGISTRY"),
                        help="ECR registry URL (or set ECR_REGISTRY env var)")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing")
    parser.add_argument("--skip-health", action="store_true", help="Skip health check after deploy")

    args = parser.parse_args(argv)

    if args.all:
        args.mines = list(MINE_REGISTRY.keys())
    else:
        args.mines = [args.mine]

    if not args.host and not args.dry_run:
        parser.error("--host or DEPLOY_HOST env var is required")

    return args


def build_ssh_cmd(host, ssh_key, remote_cmd):
    """Build an SSH command list for subprocess."""
    return [
        "ssh", "-i", ssh_key,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"ec2-user@{host}",
        remote_cmd,
    ]


def get_health_url(host, port, path):
    """Construct a health check URL."""
    return f"http://{host}:{port}{path}"


def run_ssh(host, ssh_key, remote_cmd, dry_run=False):
    """Execute a command on the remote host via SSH."""
    cmd = build_ssh_cmd(host, ssh_key, remote_cmd)
    if dry_run:
        print(f"  [dry-run] {' '.join(cmd)}")
        return True

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        print(f"  FAILED: {result.stderr.strip()}")
        return False
    if result.stdout.strip():
        print(f"  {result.stdout.strip()}")
    return True


def check_health(host, port, path, timeout=HEALTH_TIMEOUT, interval=HEALTH_INTERVAL):
    """Wait for a mine's health endpoint to return HTTP 200."""
    url = get_health_url(host, port, path)
    print(f"  Waiting for {url} ...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            result = subprocess.run(
                ["curl", "-sf", "-o", "/dev/null", "-w", "%{http_code}", url],
                capture_output=True, text=True, timeout=10,
            )
            if result.stdout.strip() == "200":
                elapsed = time.time() - start
                print(f"  Healthy ({elapsed:.0f}s)")
                return True
        except subprocess.TimeoutExpired:
            pass
        time.sleep(interval)

    print(f"  TIMEOUT after {timeout}s")
    return False


def deploy_mine(mine_name, args):
    """Deploy a single mine."""
    config = MINE_REGISTRY[mine_name]
    print(f"\n{'='*50}")
    print(f"Deploying {mine_name}")
    print(f"{'='*50}")

    ecr_image = f"{args.ecr_registry}/{config['image']}:latest" if args.ecr_registry else None

    # Step 1: Pull latest image
    if ecr_image:
        print(f"\n1. Pulling {ecr_image}")
        if not run_ssh(args.host, args.ssh_key, f"docker pull {ecr_image}", args.dry_run):
            return False
    else:
        print("\n1. Skipping pull (no ECR registry configured)")

    # Step 2: Restart container
    service = config["compose_service"]
    print(f"\n2. Restarting {service}")
    restart_cmd = f"cd /opt/intermine && docker compose restart {service}"
    if not run_ssh(args.host, args.ssh_key, restart_cmd, args.dry_run):
        return False

    # Step 3: Health check
    if not args.skip_health and not args.dry_run:
        print(f"\n3. Health check")
        if not check_health(args.host, config["port"], config["health_path"]):
            return False
    else:
        print(f"\n3. Health check {'skipped' if args.skip_health else '[dry-run]'}")

    print(f"\n{mine_name} deployed successfully")
    return True


def main():
    args = parse_args()
    start = time.time()
    results = {}

    for mine in args.mines:
        results[mine] = deploy_mine(mine, args)

    elapsed = time.time() - start
    print(f"\n{'='*50}")
    print(f"Summary ({elapsed:.0f}s)")
    print(f"{'='*50}")
    for mine, success in results.items():
        status = "OK" if success else "FAILED"
        print(f"  {mine}: {status}")

    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

Run: `pytest tests/test_deploy.py -v`
Expected: All tests pass

**Step 5: Commit**

```bash
git add scripts/deploy.py tests/test_deploy.py
git commit -m "Add deployment script for multi-tenant EC2

scripts/deploy.py handles SSH-based deployment of any mine:
- Pull latest Docker image from ECR
- Restart container via docker compose
- Health check until service responds
- Supports --all, --dry-run, --skip-health
- No hardcoded IPs — uses DEPLOY_HOST env var or --host flag"
```

---

### Task 6: Consolidate documentation

This task merges 19 docs into 5 clean files and archives the rest.

**Files:**
- Create: `docs/ARCHITECTURE.md` (merge from DOCKER_ARCHITECTURE, DEPLOYMENT_STRATEGY, BUILD_SYSTEM)
- Create: `docs/DEPLOYMENT.md` (merge from MULTITENANT_DEPLOYMENT, BLUEGENES_MIGRATION, WORMMINE_MULTITENANT_SETUP, HTTPS_SETUP)
- Create: `docs/RDS.md` (merge from RDS_INTEGRATION_NOTES, RDS_SETUP)
- Keep: `docs/QUICKSTART.md` (as-is)
- Keep: `docs/INFRASTRUCTURE_REFERENCE.md` (already created)
- Keep: `docs/BUILD_PROCESS_OVERVIEW.md` (recent, still accurate)
- Keep: `docs/ALLIANCEMINE_BUILD_GUIDE.md` (recent operational guide)
- Move to archive: everything else

**Step 1: Create archive directory and move stale docs**

```bash
mkdir -p docs/archive
git mv docs/BLUEGENES_MIGRATION.md docs/archive/
git mv docs/MULTITENANT_DEPLOYMENT.md docs/archive/
git mv docs/WORMMINE_MULTITENANT_SETUP.md docs/archive/
git mv docs/ALLIANCEMINE_HTTPS_SETUP.md docs/archive/
git mv docs/TODO_HTTPS_SETUP.md docs/archive/
git mv docs/RDS_INTEGRATION_NOTES.md docs/archive/
git mv docs/RDS_SETUP.md docs/archive/
git mv docs/DOCKER_ARCHITECTURE.md docs/archive/
git mv docs/DEPLOYMENT_STRATEGY.md docs/archive/
git mv docs/S3_DATA_TRANSFER.md docs/archive/
git mv docs/BUILD_SYSTEM.md docs/archive/
git mv docs/SUMMARY.md docs/archive/
git mv docs/GEMINI.md docs/archive/
git mv docs/alliancemine-build-process.md docs/archive/
```

**Step 2: Write docs/ARCHITECTURE.md**

Write a consolidated architecture doc covering:
- System overview (multi-tenant Docker + RDS)
- Docker setup evolution (brief timeline referencing archived docs for history)
- Current architecture diagram description (reference docs/architecture_comparison.png)
- Component inventory: build container, Tomcat containers, Solr, Caddy, RDS, BlueGenes
- Port mapping table
- Database naming strategy

Source material: read `docs/archive/DOCKER_ARCHITECTURE.md`, `docs/archive/DEPLOYMENT_STRATEGY.md`, `docs/archive/BUILD_SYSTEM.md` before writing.

**Step 3: Write docs/DEPLOYMENT.md**

Write a consolidated deployment doc covering:
- Prerequisites (SSH key, DEPLOY_HOST, ECR access)
- Using `scripts/deploy.py` (the new script from Task 5)
- Manual deployment steps (SSH + docker compose)
- WormMine-specific notes
- BlueGenes configuration
- HTTPS/TLS setup with Caddy
- Maintenance page setup
- Troubleshooting

Source material: read `docs/archive/MULTITENANT_DEPLOYMENT.md`, `docs/archive/BLUEGENES_MIGRATION.md`, `docs/archive/WORMMINE_MULTITENANT_SETUP.md`, `docs/archive/ALLIANCEMINE_HTTPS_SETUP.md` before writing.

**Step 4: Write docs/RDS.md**

Write a consolidated RDS doc covering:
- RDS instance details (identifier, engine, instance type)
- Connection information (reference INFRASTRUCTURE_REFERENCE.md for credentials)
- Database naming conventions
- Provisioning with `rds-manager` CLI
- Backup and restore
- Profile database management
- Troubleshooting

Source material: read `docs/archive/RDS_INTEGRATION_NOTES.md`, `docs/archive/RDS_SETUP.md` before writing.

**Step 5: Update docs/README.md**

Update the docs index to list the new structure:
```markdown
# Documentation

| Document | Purpose |
|----------|---------|
| [QUICKSTART.md](QUICKSTART.md) | Getting started |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture and components |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Deploying and managing mines on EC2 |
| [RDS.md](RDS.md) | RDS PostgreSQL management |
| [BUILD_PROCESS_OVERVIEW.md](BUILD_PROCESS_OVERVIEW.md) | Build pipeline stages |
| [ALLIANCEMINE_BUILD_GUIDE.md](ALLIANCEMINE_BUILD_GUIDE.md) | Operational build guide |
| [INFRASTRUCTURE_REFERENCE.md](INFRASTRUCTURE_REFERENCE.md) | Credentials and resource IDs |

Archived documentation is in [archive/](archive/).
```

**Step 6: Commit**

```bash
git add docs/
git commit -m "Consolidate documentation from 19 files to 7 active docs

Merge stale docs into ARCHITECTURE.md, DEPLOYMENT.md, and RDS.md.
Archive 14 historical docs to docs/archive/.
Update docs/README.md with new structure."
```

---

### Task 7: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update CLAUDE.md**

Update the following sections to reflect current reality:

- **Project Overview**: Mention multi-tenant Docker is production, AllianceMineDev is permanent dev
- **Build Commands**: Add `scripts/deploy.py` usage
- **Architecture**: Update to describe multi-tenant EC2 (Caddy → per-mine Tomcat → RDS), not EB
- **Docker Configurations**: Remove multi_mine_rds reference (archived), note unified dirs are deprecated
- **Important Notes**: Add note about legacy code being archived at `archive/legacy-code` tag, update doc references

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "Update CLAUDE.md for multi-tenant production architecture

Reflect that multi-tenant Docker is production, AllianceMineDev is
permanent dev. Add deploy script docs, update architecture section,
note legacy code archived, update documentation references."
```

---

### Task 8: Final verification

**Step 1: Run tests**

```bash
pytest tests/ -v
```

Expected: All tests pass including new deploy.py tests

**Step 2: Check for remaining hardcoded values**

```bash
grep -r "intermine-postgres.cmnnhlso7wdi" --include="*.yml" --include="*.yaml" --include="*.example" .
grep -r "100225593120" --include="*.sh" --include="*.yml" --include="*.yaml" . | grep -v docs/archive | grep -v docs/INFRASTRUCTURE
```

Expected: No matches outside of `.env` files (which contain actual credentials for use) and archived docs

**Step 3: Verify legacy/ is gone**

```bash
ls legacy/ 2>&1
```

Expected: "No such file or directory"

**Step 4: Verify docs structure**

```bash
ls docs/*.md | sort
```

Expected: ALLIANCEMINE_BUILD_GUIDE.md, ARCHITECTURE.md, BUILD_PROCESS_OVERVIEW.md, DEPLOYMENT.md, INFRASTRUCTURE_REFERENCE.md, QUICKSTART.md, RDS.md, README.md

**Step 5: Push tag and verify**

```bash
git tag -l "archive/*"
```

Expected: Shows `archive/legacy-code`
