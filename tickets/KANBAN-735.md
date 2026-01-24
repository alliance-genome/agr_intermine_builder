# KANBAN-735: Add Checks to AllianceMine

**URL:** https://agr-jira.atlassian.net/browse/KANBAN-735

## Request

> It would be useful to have a checking script to make sure that Lists are populated and to run the script to repopulate them if they aren't.

## Assessment

**Complexity:** Low-Medium

**Related Tickets:** KANBAN-734 (Automated rebuilds)

### Current State

- Predefined gene lists exist in AllianceMine (e.g., "Essential Genes", "Disease Genes")
- Lists can become empty after builds if regeneration fails
- No automated monitoring for list health
- Manual intervention required to detect/fix issues

### Implementation Plan

#### Health Check Script

Create `/opt/alliancemine/scripts/health_check.py`:

```python
#!/usr/bin/env python3
"""
AllianceMine Health Check Script
Verifies lists are populated and webapp is responding correctly.
"""

import requests
import sys
import json
from typing import Dict, List, Tuple

ALLIANCEMINE_URL = "http://localhost:9001/alliancemine"
MIN_LIST_SIZE = 10  # Minimum genes expected in each list

# Expected lists and their minimum sizes
EXPECTED_LISTS = {
    "PL_GeneSummary": 1000,
    "PL_AllGenes_WB": 100,
    "PL_AllGenes_FB": 100,
    "PL_AllGenes_MGI": 100,
    "PL_AllGenes_RGD": 100,
    "PL_AllGenes_ZFIN": 100,
    "PL_AllGenes_SGD": 100,
}

def check_webapp_health() -> Tuple[bool, str]:
    """Check if webapp is responding."""
    try:
        resp = requests.get(f"{ALLIANCEMINE_URL}/service/version", timeout=10)
        if resp.status_code == 200:
            return True, f"Webapp OK: {resp.json()}"
        return False, f"Webapp returned {resp.status_code}"
    except Exception as e:
        return False, f"Webapp error: {e}"

def check_list_sizes() -> List[Dict]:
    """Check all public lists for minimum size."""
    issues = []
    try:
        resp = requests.get(f"{ALLIANCEMINE_URL}/service/lists", timeout=30)
        lists = resp.json().get("lists", [])

        list_map = {l["name"]: l["size"] for l in lists}

        for list_name, min_size in EXPECTED_LISTS.items():
            actual_size = list_map.get(list_name, 0)
            if actual_size < min_size:
                issues.append({
                    "list": list_name,
                    "expected": min_size,
                    "actual": actual_size,
                    "status": "EMPTY" if actual_size == 0 else "LOW"
                })
    except Exception as e:
        issues.append({"error": str(e)})

    return issues

def check_database_connection() -> Tuple[bool, str]:
    """Check database connectivity via a simple query."""
    try:
        query = {
            "from": "Gene",
            "select": ["primaryIdentifier"],
            "size": 1
        }
        resp = requests.post(
            f"{ALLIANCEMINE_URL}/service/query/results",
            json=query,
            timeout=30
        )
        if resp.status_code == 200:
            return True, "Database OK"
        return False, f"Query failed: {resp.status_code}"
    except Exception as e:
        return False, f"Database error: {e}"

def main():
    print("=== AllianceMine Health Check ===\n")

    all_ok = True

    # Check webapp
    ok, msg = check_webapp_health()
    print(f"[{'OK' if ok else 'FAIL'}] Webapp: {msg}")
    all_ok = all_ok and ok

    # Check database
    ok, msg = check_database_connection()
    print(f"[{'OK' if ok else 'FAIL'}] Database: {msg}")
    all_ok = all_ok and ok

    # Check lists
    print("\nList Status:")
    issues = check_list_sizes()
    if not issues:
        print("[OK] All lists populated correctly")
    else:
        all_ok = False
        for issue in issues:
            if "error" in issue:
                print(f"[FAIL] Error checking lists: {issue['error']}")
            else:
                print(f"[FAIL] {issue['list']}: {issue['actual']}/{issue['expected']} ({issue['status']})")

    print(f"\n=== Overall Status: {'HEALTHY' if all_ok else 'UNHEALTHY'} ===")
    sys.exit(0 if all_ok else 1)

if __name__ == "__main__":
    main()
```

#### List Regeneration Script

Create `/opt/alliancemine/scripts/regenerate_lists.py`:

```python
#!/usr/bin/env python3
"""
Regenerate AllianceMine public gene lists.
"""

import requests
import json

ALLIANCEMINE_URL = "http://localhost:9001/alliancemine"
API_TOKEN = "YOUR_ADMIN_TOKEN"  # From alliancemine.properties

# List definitions (name -> query)
LIST_DEFINITIONS = {
    "PL_AllGenes_WB": {
        "from": "Gene",
        "select": ["primaryIdentifier"],
        "where": [{"path": "organism.taxonId", "op": "=", "value": "6239"}]
    },
    "PL_AllGenes_FB": {
        "from": "Gene",
        "select": ["primaryIdentifier"],
        "where": [{"path": "organism.taxonId", "op": "=", "value": "7227"}]
    },
    # ... additional lists
}

def regenerate_list(name: str, query: dict) -> bool:
    """Delete and recreate a list."""
    headers = {"Authorization": f"Token {API_TOKEN}"}

    # Delete existing
    requests.delete(f"{ALLIANCEMINE_URL}/service/lists/{name}", headers=headers)

    # Create new
    resp = requests.post(
        f"{ALLIANCEMINE_URL}/service/query/tolist",
        json={"query": query, "listName": name},
        headers=headers
    )

    return resp.status_code == 200

def main():
    for name, query in LIST_DEFINITIONS.items():
        ok = regenerate_list(name, query)
        print(f"[{'OK' if ok else 'FAIL'}] {name}")

if __name__ == "__main__":
    main()
```

#### Integration with Automated Builds

Add to weekly build script:

```bash
# After build completes
python3 /opt/alliancemine/scripts/health_check.py
if [ $? -ne 0 ]; then
    echo "Health check failed, attempting list regeneration..."
    python3 /opt/alliancemine/scripts/regenerate_lists.py
    python3 /opt/alliancemine/scripts/health_check.py
fi
```

### Components

1. **health_check.py** - Verify webapp, database, and list sizes
2. **regenerate_lists.py** - Recreate gene lists from queries
3. **Cron job** - Run health check periodically (e.g., every 6 hours)

### Cron Integration

```bash
# /etc/cron.d/alliancemine-health
# Health check every 6 hours
0 */6 * * * root /opt/alliancemine/scripts/health_check.py >> /var/log/alliancemine-health.log 2>&1
```

## Recommendation

1. Create health check script (simple, immediate value)
2. Create list regeneration script
3. Integrate with KANBAN-734 automated builds
4. Add cron job for periodic monitoring

## Ticket Response

I'll create a health check script that:

1. Verifies the webapp is responding
2. Checks database connectivity
3. Validates all predefined gene lists have minimum expected counts
4. Auto-triggers list regeneration if counts are low

This will be integrated with the automated rebuild pipeline (KANBAN-734) to ensure builds complete successfully.

**Implementation includes:**
- `health_check.py` - Comprehensive health verification
- `regenerate_lists.py` - Auto-populate empty lists
- Cron job for periodic monitoring

## Status

- [x] Document requirements
- [ ] Create health_check.py script
- [ ] Create regenerate_lists.py script
- [ ] Test scripts manually
- [ ] Integrate with KANBAN-734
- [ ] Add cron monitoring
