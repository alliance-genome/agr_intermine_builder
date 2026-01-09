# BlueGenes Migration: Elastic Beanstalk to Multi-Tenant

This document describes the current BlueGenes infrastructure, its complexity, and the migration plan to simplify it using the multi-tenant setup.

## Current Architecture (Complex)

```
                                    www.alliancegenome.org/bluegenes/
                                                │
                                                ▼
                                    ┌───────────────────────┐
                                    │   AWS Amplify (CDK)   │
                                    │   agr_ui React App    │
                                    └───────────────────────┘
                                                │
                                                │ REWRITE to :444
                                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ELASTIC BEANSTALK                                   │
│                  production-alliancemine.alliancegenome.org                 │
│                         (52.73.209.222 / 54.167.4.227)                      │
│                                                                             │
│   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐            │
│   │  BlueGenes:444  │  │   Tomcat:8080   │  │   Solr:8983     │            │
│   └─────────────────┘  └─────────────────┘  └─────────────────┘            │
│                                                                             │
│   DNS: production-alliancemine.us-east-1.elasticbeanstalk.com              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                    STAGE/DEV EC2 "AllianceMine"                             │
│                         172.31.96.148                                       │
│                                                                             │
│   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐            │
│   │  BlueGenes:5000 │  │   Tomcat:8080   │  │   Solr:8983     │            │
│   └─────────────────┘  └─────────────────┘  └─────────────────┘            │
│   ┌─────────────────┐                                                       │
│   │  Postgres:5432  │  (local postgres, not RDS)                           │
│   └─────────────────┘                                                       │
│                                                                             │
│   SSH: ssh AllianceMine (via bastion)                                      │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                         MULTI-TENANT EC2                                    │
│              172.31.59.87 (private) / 44.206.248.213 (public)              │
│                                                                             │
│   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐            │
│   │  BlueGenes:5000 │  │ AllianceMine    │  │   WormMine      │            │
│   │                 │  │   Tomcat:8080   │  │   Tomcat:8081   │            │
│   └─────────────────┘  └─────────────────┘  └─────────────────┘            │
│   ┌─────────────────┐                                                       │
│   │   Caddy:8888    │  (CDN for static files)                              │
│   └─────────────────┘                                                       │
│                                                                             │
│   ALB: alliancemine-lb-309443304.us-east-1.elb.amazonaws.com               │
│   DNS: alliancemine.alliancegenome.org, wormmine.alliancegenome.org        │
│   RDS: Shared PostgreSQL (intermine-postgres.cmnnhlso7wdi.us-east-1.rds)   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Problems with Current Setup

1. **Three separate BlueGenes instances** running on different infrastructure
2. **Elastic Beanstalk overhead** for a single container
3. **Non-standard port (444)** instead of standard HTTPS
4. **Multiple EC2 instances** for the same service
5. **Inconsistent configuration** across environments
6. **Higher costs** from running redundant infrastructure

## Target Architecture (Simplified)

```
                                    www.alliancegenome.org/bluegenes/
                                                │
                                                ▼
                                    ┌───────────────────────┐
                                    │   AWS Amplify (CDK)   │
                                    │   agr_ui React App    │
                                    └───────────────────────┘
                                                │
                                                │ REWRITE
                                                ▼
                        https://alliancemine.alliancegenome.org/bluegenes/
                                                │
                                                ▼
                                    ┌───────────────────────┐
                                    │   ALB (alliancemine-lb)│
                                    │   Port 443 (HTTPS)    │
                                    └───────────────────────┘
                                                │
                                                │ Target Group: bluegenes:5000
                                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MULTI-TENANT EC2                                    │
│              172.31.59.87 (private) / 44.206.248.213 (public)              │
│                                                                             │
│   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐            │
│   │  BlueGenes:5000 │  │ AllianceMine    │  │   WormMine      │            │
│   │  (single inst)  │  │   :8080         │  │   :8081         │            │
│   └─────────────────┘  └─────────────────┘  └─────────────────┘            │
│   ┌─────────────────┐  ┌─────────────────┐                                 │
│   │   Caddy:8888    │  │  Future mines   │                                 │
│   │   (CDN)         │  │  :8082, etc     │                                 │
│   └─────────────────┘  └─────────────────┘                                 │
│                                                                             │
│   Shared RDS PostgreSQL                                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Benefits

1. **Single BlueGenes instance** serving all mines
2. **Standard HTTPS (443)** via ALB
3. **Consolidated infrastructure** on one EC2
4. **Shared RDS** reduces database overhead
5. **Easier maintenance** with docker-compose
6. **Lower costs** (~$500/month vs multiple instances)

## Migration Steps

### Phase 1: Prepare Multi-Tenant BlueGenes

#### 1.1 Verify BlueGenes is running on multi-tenant

```bash
# SSH to multi-tenant
ssh -i ~/.ssh/AGR-ssl3.pem ec2-user@172.31.59.87

# Check BlueGenes container
docker ps | grep bluegenes

# Test locally
curl -s http://localhost:5000/bluegenes/alliancemine | head -c 100
curl -s http://localhost:5000/bluegenes/wormmine | head -c 100
```

#### 1.2 Register BlueGenes target in ALB

```bash
# Register target
aws elbv2 register-targets \
  --target-group-arn arn:aws:elasticloadbalancing:us-east-1:100225593120:targetgroup/bluegenes/2f1b5243ba6b3022 \
  --targets Id=172.31.59.87,Port=5000

# Verify registration
aws elbv2 describe-target-health \
  --target-group-arn arn:aws:elasticloadbalancing:us-east-1:100225593120:targetgroup/bluegenes/2f1b5243ba6b3022
```

#### 1.3 Add ALB listener rule for /bluegenes

```bash
# Get listener ARN
LISTENER_ARN=$(aws elbv2 describe-listeners \
  --load-balancer-arn arn:aws:elasticloadbalancing:us-east-1:100225593120:loadbalancer/app/alliancemine-lb/ba5d2c2ed6bb4d3a \
  --query 'Listeners[?Port==`443`].ListenerArn' --output text)

# Create rule for /bluegenes/*
aws elbv2 create-rule \
  --listener-arn $LISTENER_ARN \
  --priority 100 \
  --conditions '[{"Field":"path-pattern","Values":["/bluegenes/*"]},{"Field":"host-header","Values":["alliancemine.alliancegenome.org"]}]' \
  --actions '[{"Type":"forward","TargetGroupArn":"arn:aws:elasticloadbalancing:us-east-1:100225593120:targetgroup/bluegenes/2f1b5243ba6b3022"}]'
```

#### 1.4 Test BlueGenes via ALB

```bash
# Test via ALB
curl -sI "https://alliancemine.alliancegenome.org/bluegenes/alliancemine"

# Should return HTTP 200
```

### Phase 2: Update Amplify Configuration

#### 2.1 Modify agr_ui CDK stacks

Edit the following files in `agr_ui/cdk/`:

**amplify-production-stack.ts** (lines 168-182):

```typescript
// BEFORE (Elastic Beanstalk)
{
  source: '/bluegenes',
  target: 'https://www.alliancegenome.org/bluegenes/',
  status: amplify.RedirectStatus.PERMANENT_REDIRECT,
},
{
  source: '/bluegenes/',
  target: 'https://production-alliancemine.alliancegenome.org:444/bluegenes/alliancemine',
  status: amplify.RedirectStatus.REWRITE,
},
{
  source: '/bluegenes/<*>',
  target: 'https://production-alliancemine.alliancegenome.org:444/bluegenes/<*>',
  status: amplify.RedirectStatus.REWRITE,
},

// AFTER (Multi-tenant)
{
  source: '/bluegenes',
  target: 'https://www.alliancegenome.org/bluegenes/',
  status: amplify.RedirectStatus.PERMANENT_REDIRECT,
},
{
  source: '/bluegenes/',
  target: 'https://alliancemine.alliancegenome.org/bluegenes/alliancemine',
  status: amplify.RedirectStatus.REWRITE,
},
{
  source: '/bluegenes/<*>',
  target: 'https://alliancemine.alliancegenome.org/bluegenes/<*>',
  status: amplify.RedirectStatus.REWRITE,
},
```

**amplify-stage-stack.ts** (lines 184-197):

```typescript
// BEFORE
{
  source: '/bluegenes/',
  target: 'https://stage.alliancegenome.org/bluegenes/alliancemine',
  status: amplify.RedirectStatus.PERMANENT_REDIRECT,
},
{
  source: '/bluegenes/<*>',
  target: 'https://stage-alliancemine.alliancegenome.org:444/bluegenes/<*>',
  status: amplify.RedirectStatus.REWRITE,
},

// AFTER
{
  source: '/bluegenes/',
  target: 'https://alliancemine.alliancegenome.org/bluegenes/alliancemine',
  status: amplify.RedirectStatus.REWRITE,
},
{
  source: '/bluegenes/<*>',
  target: 'https://alliancemine.alliancegenome.org/bluegenes/<*>',
  status: amplify.RedirectStatus.REWRITE,
},
```

**amplify-test-stack.ts** (lines 158-171):

```typescript
// BEFORE
{
  source: '/bluegenes',
  target: 'https://production-alliancemine.alliancegenome.org:444/bluegenes/alliancemine',
  status: amplify.RedirectStatus.REWRITE,
},
{
  source: '/bluegenes/',
  target: 'https://production-alliancemine.alliancegenome.org:444/bluegenes/alliancemine',
  status: amplify.RedirectStatus.REWRITE,
},
{
  source: '/bluegenes/<*>',
  target: 'https://production-alliancemine.alliancegenome.org:444/bluegenes/<*>',
  status: amplify.RedirectStatus.REWRITE,
},

// AFTER
{
  source: '/bluegenes',
  target: 'https://alliancemine.alliancegenome.org/bluegenes/alliancemine',
  status: amplify.RedirectStatus.REWRITE,
},
{
  source: '/bluegenes/',
  target: 'https://alliancemine.alliancegenome.org/bluegenes/alliancemine',
  status: amplify.RedirectStatus.REWRITE,
},
{
  source: '/bluegenes/<*>',
  target: 'https://alliancemine.alliancegenome.org/bluegenes/<*>',
  status: amplify.RedirectStatus.REWRITE,
},
```

#### 2.2 Deploy CDK changes

```bash
cd agr_ui/cdk
npm install
npm run build

# Deploy to test first
cdk deploy AmplifyTestStack

# Test
curl -sI "https://test.alliancegenome.org/bluegenes/"

# Deploy to stage
cdk deploy AmplifyStageStack

# Deploy to production
cdk deploy AmplifyProductionStack
```

#### 2.3 Verify production

```bash
# Test production BlueGenes
curl -sI "https://www.alliancegenome.org/bluegenes/"
curl -s "https://www.alliancegenome.org/bluegenes/alliancemine" | head -c 200

# Check in browser
open "https://www.alliancegenome.org/bluegenes/alliancemine"
```

### Phase 3: Decommission Old Infrastructure

#### 3.1 Decommission Elastic Beanstalk

After confirming multi-tenant works:

```bash
# List Elastic Beanstalk environments
aws elasticbeanstalk describe-environments \
  --query 'Environments[?contains(EnvironmentName, `alliancemine`)].[EnvironmentName,Status,CNAME]'

# Terminate environment (CAREFUL - this is destructive!)
aws elasticbeanstalk terminate-environment \
  --environment-name production-alliancemine

# Delete application (after environment is terminated)
aws elasticbeanstalk delete-application \
  --application-name alliancemine
```

#### 3.2 Clean up DNS records

Remove old DNS records pointing to Elastic Beanstalk:

```bash
# Check current records
aws route53 list-resource-record-sets \
  --hosted-zone-id Z3IZ3D6V94JEC2 \
  --query "ResourceRecordSets[?contains(Name, 'production-alliancemine')]"

# Delete record (adjust as needed)
aws route53 change-resource-record-sets \
  --hosted-zone-id Z3IZ3D6V94JEC2 \
  --change-batch '{
    "Changes": [{
      "Action": "DELETE",
      "ResourceRecordSet": {
        "Name": "production-alliancemine.alliancegenome.org",
        "Type": "CNAME",
        "TTL": 300,
        "ResourceRecords": [{"Value": "production-alliancemine.us-east-1.elasticbeanstalk.com"}]
      }
    }]
  }'
```

#### 3.3 Decommission Stage/Dev AllianceMine EC2 (optional)

If the stage EC2 (172.31.96.148) is no longer needed:

```bash
# Get instance ID
INSTANCE_ID=$(aws ec2 describe-instances \
  --filters "Name=private-ip-address,Values=172.31.96.148" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)

# Stop instance first (for safety)
aws ec2 stop-instances --instance-ids $INSTANCE_ID

# After verification period, terminate
aws ec2 terminate-instances --instance-ids $INSTANCE_ID
```

## BlueGenes Configuration

### Multi-tenant BlueGenes config

Location on multi-tenant: `/home/ec2-user/bluegenes-config/config.edn`

```clojure
{:mines
 {:alliancemine
  {:name "AllianceMine"
   :service {:root "https://alliancemine.alliancegenome.org/alliancemine"}}

  :wormmine
  {:name "WormMine"
   :service {:root "https://wormmine.alliancegenome.org/wormmine"}}}

 :default-mine :alliancemine
 :bluegenes-deploy-path "/bluegenes"
 :server-port 5000}
```

### Adding more mines to BlueGenes

Edit config.edn and add new mine:

```clojure
:flymine
{:name "FlyMine"
 :service {:root "https://flymine.alliancegenome.org/flymine"}}
```

Then restart BlueGenes:

```bash
docker restart bluegenes
```

## Rollback Plan

If issues occur after migration:

### 1. Revert Amplify CDK

```bash
cd agr_ui
git revert HEAD  # Revert CDK changes
cd cdk
cdk deploy AmplifyProductionStack
```

### 2. Elastic Beanstalk should still be running

If not terminated, traffic will resume to Elastic Beanstalk.

### 3. Emergency: Direct DNS change

```bash
# Point production-alliancemine back to EB
aws route53 change-resource-record-sets \
  --hosted-zone-id Z3IZ3D6V94JEC2 \
  --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "production-alliancemine.alliancegenome.org",
        "Type": "CNAME",
        "TTL": 300,
        "ResourceRecords": [{"Value": "production-alliancemine.us-east-1.elasticbeanstalk.com"}]
      }
    }]
  }'
```

## Infrastructure Inventory

### Current (Before Migration)

| Component | Location | Port | Status |
|-----------|----------|------|--------|
| BlueGenes (Prod) | Elastic Beanstalk | 444 | Active |
| BlueGenes (Stage) | 172.31.96.148 | 5000 | Active |
| BlueGenes (Multi-tenant) | 172.31.59.87 | 5000 | Active |
| AllianceMine (Prod) | Elastic Beanstalk | 8080 | Active |
| AllianceMine (Multi-tenant) | 172.31.59.87 | 8080 | Active |
| WormMine (Multi-tenant) | 172.31.59.87 | 8081 | Active |

### Target (After Migration)

| Component | Location | Port | Status |
|-----------|----------|------|--------|
| BlueGenes | 172.31.59.87 | 5000 | Active |
| AllianceMine | 172.31.59.87 | 8080 | Active |
| WormMine | 172.31.59.87 | 8081 | Active |
| FlyMine (future) | 172.31.59.87 | 8082 | Planned |

### To Decommission

| Component | Type | Reason |
|-----------|------|--------|
| production-alliancemine | Elastic Beanstalk | Replaced by multi-tenant |
| 172.31.96.148 | EC2 (Stage) | Consolidated to multi-tenant |
| stage-alliancemine | Elastic Beanstalk (if exists) | Replaced by multi-tenant |

## Estimated Cost Savings

| Current | Monthly Cost |
|---------|-------------|
| Elastic Beanstalk (production-alliancemine) | ~$150-200 |
| EC2 Stage (172.31.96.148) | ~$100-150 |
| Multi-tenant EC2 | ~$500 |
| **Total** | **~$750-850** |

| After Migration | Monthly Cost |
|-----------------|-------------|
| Multi-tenant EC2 only | ~$500 |
| **Total** | **~$500** |

**Savings: ~$250-350/month**

## Related Documentation

- [AllianceMine HTTPS Setup](ALLIANCEMINE_HTTPS_SETUP.md)
- [Multi-Tenant Deployment Guide](MULTITENANT_DEPLOYMENT.md)
- [WormMine Multi-Tenant Setup](WORMMINE_MULTITENANT_SETUP.md)
