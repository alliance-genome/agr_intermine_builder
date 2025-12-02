# RDS Setup Guide

Quick guide to provision a shared RDS PostgreSQL instance for all InterMine databases.

## 🎯 One RDS Instance for All Mines

This setup creates **one RDS instance** that hosts databases for:
- AllianceMine (main + profile DB)
- WormMine (main + profile DB)
- MouseMine (main + profile DB)
- FlyMine (main + profile DB)

**Total: 8 databases on one RDS instance**

## 💰 Recommended Configuration

**Instance:** db.t3.large (2 vCPU, 8GB RAM - Intel x86)
- **Cost:** ~$0.144/hour (~$105/month)
- **Storage:** 500GB gp3 (~$55/month)
- **Total:** ~$160/month
- **PostgreSQL:** Version 15

### Why db.t3.large?

✅ 8GB RAM handles 250 concurrent connections (InterMine recommendation)
✅ Intel x86 architecture (standard compatibility)
✅ Burstable performance for batch workloads
✅ Sufficient for 4 mines building/running
✅ InterMine-optimized parameter group included

### Alternative: db.t3.medium (Budget Option)

- **Cost:** ~$0.072/hour (~$52/month)
- **RAM:** 4GB (may struggle with all 4 mines)
- **Use for:** Testing or single mine builds

## 🎯 InterMine-Optimized PostgreSQL Settings

The provisioner automatically configures PostgreSQL based on **InterMine official recommendations**:

| Parameter | Value | Purpose |
|-----------|-------|---------|
| max_connections | 250 | InterMine production recommendation |
| shared_buffers | 25% of RAM | Caching frequently accessed data |
| effective_cache_size | 50% of RAM | Query planner optimization |
| work_mem | 512MB | Sort and hash operations |
| maintenance_work_mem | 1GB | VACUUM, CREATE INDEX operations |
| default_statistics_target | 250 | Better query plans (InterMine rec) |
| synchronous_commit | off | Performance boost (InterMine rec) |
| autovacuum_max_workers | 3 | Critical for data loading |

**Source:** [InterMine PostgreSQL Documentation](https://intermine.readthedocs.io/en/latest/system-requirements/software/postgres/postgres/)

## 🚀 Quick Start

### Prerequisites

1. **AWS CLI configured:**
   ```bash
   aws configure
   # Enter your AWS Access Key, Secret Key, and Region
   ```

2. **Python environment:**
   ```bash
   uv pip install -e .
   ```

3. **IAM Permissions Required:**

   **Minimum Required:**
   - `rds:CreateDBInstance`
   - `rds:DescribeDBInstances`
   - `ec2:CreateSecurityGroup`
   - `ec2:DescribeSecurityGroups`
   - `ec2:AuthorizeSecurityGroupIngress`
   - `ec2:DescribeVpcs`

   **Recommended for Optimization:**
   - `rds:CreateDBParameterGroup`
   - `rds:ModifyDBParameterGroup`
   - `rds:DescribeDBParameterGroups`

   **Note:** If you don't have parameter group permissions, the tool will automatically fall back to AWS's default PostgreSQL 16 parameter group. This works but won't include InterMine-specific optimizations.

### Step 1: Create RDS Instance (Recommended Settings)

```bash
# Using uv (recommended)
uv run python -m src.cli.rds_manager create

# Or with regular python3
python3 -m src.cli.rds_manager create
```

This will:
- ✅ Create db.t3.large instance (Intel x86)
- ✅ Allocate 500GB gp3 storage
- ✅ Create security group (allow PostgreSQL port 5432)
- ✅ Create parameter group (optimized for InterMine) OR use default if no permission
- ✅ Create all 8 databases
- ✅ Generate secure password
- ⏱️ Takes ~15-20 minutes

### Step 2: Save Credentials

The command outputs connection details. **Save these to `.env` file:**

```bash
RDS_HOST=intermine-postgres.xxxxxx.us-east-1.rds.amazonaws.com
RDS_PORT=5432
RDS_USER=postgres
RDS_PASSWORD=<generated-password>
```

### Step 3: Verify Parameter Group (Optional)

Check if custom parameter group was created:

```bash
uv run python -m src.cli.rds_manager status
```

Look for parameter group name in output:
- `intermine-postgres16` = Optimized ✅
- `default.postgres16` = Using default (still works)

If using default and you need optimization, see "Troubleshooting" section below.

### Step 4: Test Connection

```bash
psql -h $RDS_HOST -U postgres -d postgres
# Enter password when prompted
```

### Step 5: Start Building Mines

```bash
uv run python -m src.cli.build_mines build --mine alliancemine
```

## 🛠️ Custom Configuration

### Different Instance Type

```bash
# Smaller (budget/testing)
python -m src.cli.rds_manager create --instance-type db.t3.medium --storage 300

# Larger (production with more headroom)
python -m src.cli.rds_manager create --instance-type db.t3.xlarge --storage 1000
```

### Different Region

```bash
python -m src.cli.rds_manager create --region us-west-2
```

### Custom Password

```bash
python -m src.cli.rds_manager create --password "MySecurePassword123!"
```

### Skip Database Creation

```bash
# Create instance only, create databases manually later
python -m src.cli.rds_manager create --skip-databases
```

## 📊 Check Status

```bash
python -m src.cli.rds_manager status
```

## 🔧 Modify Instance

Increase storage or change instance type:

```bash
# Increase storage (can only increase, not decrease)
uv run python -m src.cli.rds_manager modify --storage 500 --apply-immediately

# Change instance type
uv run python -m src.cli.rds_manager modify --instance-type db.t3.xlarge --apply-immediately

# Both at once
uv run python -m src.cli.rds_manager modify --storage 1000 --instance-type db.t3.xlarge --apply-immediately
```

**Notes:**
- Storage can only be increased, never decreased
- `--apply-immediately` applies changes now (otherwise waits for maintenance window)
- Storage modification is online (no downtime)
- Instance type change requires brief downtime (~1-5 minutes)

## ⏸️ Stop/Start Instance

Save costs when not building:

```bash
# Stop instance (saves ~$105/month compute, storage still charged)
uv run python -m src.cli.rds_manager stop

# Start when needed
uv run python -m src.cli.rds_manager start
```

**Details:**
- Instance auto-restarts after 7 days (AWS limitation)
- Data persists while stopped
- Storage costs continue (~$55/month for 500GB)

Output:
```
📊 RDS Instance Status: intermine-postgres
============================================================
Status: available
Endpoint: intermine-postgres.xxxxx.us-east-1.rds.amazonaws.com
Port: 5432
Engine: postgres 16.4
Instance Class: db.t3.large
Storage: 200GB gp3
Multi-AZ: False
Publicly Accessible: True
Backup Retention: 7 days
============================================================
```

## 🗑️ Delete Instance

**⚠️ WARNING: This deletes ALL data!**

```bash
# Interactive confirmation
python -m src.cli.rds_manager delete

# Skip confirmation (dangerous!)
python -m src.cli.rds_manager delete --confirm --skip-snapshot
```

## 📋 What Gets Created

### RDS Instance
- **Identifier:** intermine-postgres
- **Engine:** PostgreSQL 15
- **Instance Class:** db.t3.large (Intel x86, or specified)
- **Storage:** 500GB gp3 (3000 IOPS baseline, 125 MB/s)
- **Backup:** 7-day retention
- **Multi-AZ:** Disabled (save cost for dev/test)
- **Public Access:** Enabled (for building from local)

### Security Group
- **Name:** intermine-rds-sg
- **Ingress:** Port 5432 from 0.0.0.0/0
- ⚠️ **Production:** Restrict to specific IPs

### Parameter Group
- **Name:** intermine-postgres16 (or default.postgres16 if insufficient permissions)
- **max_connections:** 250 (custom) or 100 (default)
- **shared_buffers:** 25% of RAM (custom) or ~128MB (default)
- **work_mem:** 512MB (custom) or 4MB (default)
- **maintenance_work_mem:** 1GB (custom) or 64MB (default)
- **Optimized for:** Batch processing, data integration (custom only)

### Databases Created

| Database | Purpose | Connections |
|----------|---------|-------------|
| alliancemine_db | AllianceMine main data | 20 |
| alliancemine_profiles_db | AllianceMine user profiles | 5 |
| wormmine_db | WormMine main data | 15 |
| wormmine_profiles_db | WormMine user profiles | 5 |
| mousemine_db | MouseMine main data | 18 |
| mousemine_profiles_db | MouseMine user profiles | 5 |
| flymine_db | FlyMine main data | 16 |
| flymine_profiles_db | FlyMine user profiles | 5 |

## 💡 Cost Optimization Tips

### 1. Use Reserved Instances (Not Implemented Yet)
- Save 30-60% by committing 1-3 years
- Pay upfront or monthly
- **Example:** db.t3.large 1-year RI: ~$73/month (vs $105 on-demand)

### 2. Stop Instance When Not Building

```bash
# Stop instance (saves ~$105/month, storage still charged ~$22/month)
uv run python -m src.cli.rds_manager stop

# Start when needed
uv run python -m src.cli.rds_manager start
```

**Details:**
- Stops billing for compute instance
- Storage still charged
- Auto-starts after 7 days (AWS policy)
- **Savings:** ~$95/month when stopped
- Data persists across stop/start

### 3. Use gp3 Instead of gp2
- ✅ Already using gp3 (cheaper and faster)
- gp3: $0.11/GB/month
- gp2: $0.125/GB/month

### 4. Reduce Storage After Builds Complete
- Monitor actual usage
- Resize down if using <100GB

### 5. Snapshot and Restore
- Create snapshot after builds complete
- Delete instance
- Restore from snapshot when needed
- **Snapshots:** $0.095/GB/month

## 🔧 Troubleshooting

### IAM Permission Denied for Parameter Group

**Problem:** `AccessDenied when calling CreateDBParameterGroup`

**What it means:** Your AWS user lacks permission to create custom parameter groups.

**Impact:**
- RDS will be created successfully using AWS's default parameter group
- Works but won't have InterMine-specific optimizations
- Builds will be slower (~2-3x) and may hit connection limits

**Solutions:**

**Option A: Continue with Default (Quick Start)**
```bash
# Tool automatically falls back to default.postgres16
uv run python -m src.cli.rds_manager create
```
- ✅ Works immediately
- ⚠️ Not optimized for InterMine
- ⚠️ Slower builds
- ⚠️ May hit 100-connection limit

**Option B: Add IAM Permissions (Recommended)**

Ask your AWS administrator to add these permissions to your IAM user:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "rds:CreateDBParameterGroup",
                "rds:ModifyDBParameterGroup",
                "rds:DescribeDBParameterGroups"
            ],
            "Resource": "*"
        }
    ]
}
```

Then recreate the RDS instance:
```bash
# Delete existing instance (if created with default)
uv run python -m src.cli.rds_manager delete --confirm

# Create with optimized parameter group
uv run python -m src.cli.rds_manager create
```

**Option C: Admin Creates Parameter Group**

Have your AWS administrator:
1. Run the provisioner with their credentials, OR
2. Manually create parameter group in AWS Console with settings from `src/intermine_builder/rds_provisioner.py:242-271`

Then specify it during creation:
```bash
# Use existing parameter group (feature to be added)
uv run python -m src.cli.rds_manager create --param-group intermine-postgres16
```

### Connection Timeout

**Problem:** Can't connect to RDS
**Solution:**
1. Check security group allows your IP
2. Verify instance is "available" status
3. Test with telnet: `telnet $RDS_HOST 5432`

### Out of Connections

**Problem:** "too many clients already"
**Solution:**
1. Check current connections:
   ```sql
   SELECT count(*) FROM pg_stat_activity;
   ```
2. Kill idle connections:
   ```sql
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE state = 'idle' AND state_change < now() - interval '1 hour';
   ```

### Slow Queries

**Problem:** Build stages taking too long
**Solution:**
1. Check parameter group is applied
2. Verify instance class is correct
3. Monitor CloudWatch metrics
4. Consider upgrading to db.t3.xlarge or db.t3.2xlarge

### Database Already Exists

**Problem:** "database already exists" error
**Solution:**
- Databases are persistent
- Skip database creation: `--skip-databases`
- Or manually drop and recreate

## 📖 Related Documentation

- **QUICKSTART.md** - Complete build guide
- **BUILD_SYSTEM.md** - Full system documentation
- **AWS RDS Pricing:** https://aws.amazon.com/rds/postgresql/pricing/

## 🔐 Security Best Practices

### Production Recommendations:

1. **Restrict Security Group:**
   ```bash
   # Allow only your build server IP
   aws ec2 authorize-security-group-ingress \
     --group-id sg-xxxxx \
     --protocol tcp \
     --port 5432 \
     --cidr YOUR_IP/32
   ```

2. **Enable Encryption:**
   - Storage encryption at rest
   - SSL/TLS for connections

3. **Enable Multi-AZ:**
   - For production high availability
   - Costs 2x but provides failover

4. **Enable Deletion Protection:**
   - Prevents accidental deletion
   - Set in AWS console or via CLI

5. **Regular Snapshots:**
   - Automated daily snapshots (enabled)
   - Manual snapshots before major changes

6. **Monitor:**
   - Set CloudWatch alarms for CPU, memory, storage
   - Alert on connection count approaching max

## ⏭️ Next Steps

After RDS is created:

1. ✅ Save credentials to `.env`
2. ✅ Test connection with psql
3. 🚀 Build first mine: `python -m src.cli.build_mines build --mine alliancemine`
4. 📊 Monitor RDS metrics in AWS Console
5. 💾 Create snapshot after first successful build
