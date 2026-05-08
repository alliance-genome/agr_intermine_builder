# IAM policy additions for `pnuin` — RDS reboot + scale

Date: 2026-05-08
Account: `100225593120`
User: `arn:aws:iam::100225593120:user/pnuin`
Target instance: `arn:aws:rds:us-east-1:100225593120:db:intermine-postgres` (db.t3.xlarge, PostgreSQL 15.12)

## Why

User `pnuin` currently lacks two operational RDS permissions:

1. **`rds:RebootDBInstance`** — pending parameter-group changes (`shared_buffers`, `effective_cache_size`, `max_connections`) require a reboot to take effect. Without this permission the parameter changes were applied via `ModifyDBParameterGroup` but never activated, leaving the perf tuning half-done.

2. **`rds:ModifyDBInstance` (scale-related actions)** — instance class upgrades (e.g. db.t3.large → db.t3.xlarge, the 2026-05-05 night upgrade) currently require admin assistance. Same for storage resizes and storage-type changes when capacity needs to grow.

Both blocked routine ops during the rc20 incident week. Granting them removes the human admin bottleneck for known-safe maintenance.

## Policy 1 — `RDSRebootIntermine` (minimal)

Allows reboot only on the single intermine-postgres instance. No other RDS instance affected.

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "RebootIntermineRDS",
            "Effect": "Allow",
            "Action": [
                "rds:RebootDBInstance"
            ],
            "Resource": [
                "arn:aws:rds:us-east-1:100225593120:db:intermine-postgres"
            ]
        }
    ]
}
```

## Policy 2 — `RDSScaleIntermine`

Allows instance-class scale, storage scale, parameter modify, plus describe for verification. Restricted to intermine-postgres + its parameter groups + its option group.

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ScaleAndModifyIntermineRDS",
            "Effect": "Allow",
            "Action": [
                "rds:ModifyDBInstance",
                "rds:RebootDBInstance",
                "rds:DescribeDBInstances",
                "rds:DescribeDBLogFiles",
                "rds:DescribePendingMaintenanceActions"
            ],
            "Resource": [
                "arn:aws:rds:us-east-1:100225593120:db:intermine-postgres"
            ]
        },
        {
            "Sid": "ParamGroupModify",
            "Effect": "Allow",
            "Action": [
                "rds:ModifyDBParameterGroup",
                "rds:DescribeDBParameterGroups",
                "rds:DescribeDBParameters",
                "rds:DescribeEngineDefaultParameters"
            ],
            "Resource": [
                "arn:aws:rds:us-east-1:100225593120:pg:intermine-*"
            ]
        },
        {
            "Sid": "ReadDescribe",
            "Effect": "Allow",
            "Action": [
                "rds:DescribeDBSnapshots",
                "rds:DescribeDBSubnetGroups",
                "rds:DescribeDBSecurityGroups",
                "rds:DescribeOptionGroups",
                "rds:ListTagsForResource"
            ],
            "Resource": "*"
        }
    ]
}
```

`Sid: ReadDescribe` is `Resource: "*"` because RDS describe APIs don't accept resource ARNs; safe (read-only).

## Policy 3 — `RDSSnapshotIntermine` (recommended addition)

Snapshots are usually how we recover from a misaimed `ModifyDBInstance`. Worth granting alongside scale powers so the operator who scales is the same one who can take/restore snapshots.

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "SnapshotIntermineRDS",
            "Effect": "Allow",
            "Action": [
                "rds:CreateDBSnapshot",
                "rds:CopyDBSnapshot",
                "rds:DeleteDBSnapshot",
                "rds:DescribeDBSnapshots",
                "rds:RestoreDBInstanceFromDBSnapshot"
            ],
            "Resource": [
                "arn:aws:rds:us-east-1:100225593120:db:intermine-postgres",
                "arn:aws:rds:us-east-1:100225593120:snapshot:*"
            ]
        }
    ]
}
```

## What is intentionally NOT granted

- `rds:DeleteDBInstance` — never needed for ops, single biggest accident-blast-radius.
- `rds:CreateDBInstance` — cluster provisioning is admin/IaC territory, not ops.
- `rds:ModifyDBInstanceFromBackup` (cross-account) — out of scope.
- Wildcard on RDS — keeps blast radius scoped to intermine-postgres only.

## Apply via AWS CLI (admin only)

```bash
ADMIN=admin-profile  # admin's AWS CLI profile

# Create policies
aws --profile $ADMIN iam create-policy \
    --policy-name RDSRebootIntermine \
    --policy-document file://policy_reboot.json

aws --profile $ADMIN iam create-policy \
    --policy-name RDSScaleIntermine \
    --policy-document file://policy_scale.json

aws --profile $ADMIN iam create-policy \
    --policy-name RDSSnapshotIntermine \
    --policy-document file://policy_snapshot.json

# Attach to user pnuin
for P in RDSRebootIntermine RDSScaleIntermine RDSSnapshotIntermine; do
  aws --profile $ADMIN iam attach-user-policy \
      --user-name pnuin \
      --policy-arn arn:aws:iam::100225593120:policy/$P
done
```

If pnuin is in an IAM group, attach to the group instead:
```bash
aws --profile $ADMIN iam attach-group-policy \
    --group-name <group-name> --policy-arn ...
```

## Verify after grant

As `pnuin`:
```bash
# Should now succeed
aws rds describe-db-instances --db-instance-identifier intermine-postgres
aws rds describe-pending-maintenance-actions \
    --resource-identifier arn:aws:rds:us-east-1:100225593120:db:intermine-postgres

# Dry-run feel: simulate a reboot without committing
aws iam simulate-principal-policy \
    --policy-source-arn arn:aws:iam::100225593120:user/pnuin \
    --action-names rds:RebootDBInstance \
    --resource-arns arn:aws:rds:us-east-1:100225593120:db:intermine-postgres
# expected EvaluationResults[0].EvalDecision = "allowed"
```

## Pending param-group reboot to apply once permission lands

The 2026-05-05 tuning changes (`shared_buffers`, `effective_cache_size`) are still pending-reboot. After grant:

```bash
# verify pending
aws rds describe-db-instances \
    --db-instance-identifier intermine-postgres \
    --query 'DBInstances[0].PendingModifiedValues'

# schedule reboot during off-hours (no failover for single-AZ; under 60s downtime)
aws rds reboot-db-instance \
    --db-instance-identifier intermine-postgres
```

Coordinate with the build pipeline — kill any active `pg_dump` / `project_build` first.
