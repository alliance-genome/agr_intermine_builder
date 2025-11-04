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

**Instance:** db.t4g.large (2 vCPU, 8GB RAM)
- **Cost:** ~$0.13/hour (~$95/month)
- **Storage:** 200GB gp3 (~$22/month)
- **Total:** ~$117/month
- **PostgreSQL:** Version 16.4

### Why db.t4g.large?

✅ 8GB RAM handles ~90 concurrent connections
✅ ARM Graviton2 (10% cheaper than Intel)
✅ Burstable performance for batch workloads
✅ Sufficient for 4 mines building/running

### Alternative: db.t4g.medium (Budget Option)

- **Cost:** ~$0.065/hour (~$47/month)
- **RAM:** 4GB (may struggle with all 4 mines)
- **Use for:** Testing or single mine builds

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

### Step 1: Create RDS Instance (Recommended Settings)

```bash
python -m src.cli.rds_manager create
```

This will:
- ✅ Create db.t4g.large instance
- ✅ Allocate 200GB gp3 storage
- ✅ Create security group (allow PostgreSQL port 5432)
- ✅ Create parameter group (optimized for InterMine)
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

### Step 3: Test Connection

```bash
psql -h $RDS_HOST -U postgres -d postgres
# Enter password when prompted
```

### Step 4: Start Building Mines

```bash
python -m src.cli.build_mines build --mine alliancemine
```

## 🛠️ Custom Configuration

### Different Instance Type

```bash
# Smaller (budget)
python -m src.cli.rds_manager create --instance-type db.t4g.medium --storage 100

# Larger (production)
python -m src.cli.rds_manager create --instance-type db.t4g.xlarge --storage 500
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

Output:
```
📊 RDS Instance Status: intermine-postgres
============================================================
Status: available
Endpoint: intermine-postgres.xxxxx.us-east-1.rds.amazonaws.com
Port: 5432
Engine: postgres 16.4
Instance Class: db.t4g.large
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
- **Engine:** PostgreSQL 16.4
- **Instance Class:** db.t4g.large (or specified)
- **Storage:** 200GB gp3 (3000 IOPS, 125 MB/s)
- **Backup:** 7-day retention
- **Multi-AZ:** Disabled (save cost for dev/test)
- **Public Access:** Enabled (for building from local)

### Security Group
- **Name:** intermine-rds-sg
- **Ingress:** Port 5432 from 0.0.0.0/0
- ⚠️ **Production:** Restrict to specific IPs

### Parameter Group
- **Name:** intermine-postgres16
- **max_connections:** 200
- **shared_buffers:** 25% of RAM
- **work_mem:** 16MB
- **maintenance_work_mem:** 512MB
- **Optimized for:** Batch processing, data integration

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
- **Example:** db.t4g.large 1-year RI: ~$65/month (vs $95 on-demand)

### 2. Stop Instance When Not Building
```bash
aws rds stop-db-instance --db-instance-identifier intermine-postgres
```
- Stops billing for instance (storage still charged)
- Auto-starts after 7 days
- **Savings:** ~$95/month when stopped

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
4. Consider upgrading to db.t4g.xlarge

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
