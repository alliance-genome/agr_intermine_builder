# EC2 + Step Functions Architecture

## Overview

This architecture uses:
1. **Persistent EC2 Tomcat Server** - Hosts all mine webapps (24/7)
2. **Ephemeral EC2 Build Server** - Spins up only during builds (on-demand)
3. **AWS Step Functions** - Orchestrates the entire build lifecycle
4. **Persistent RDS** - Single PostgreSQL instance with all mine databases

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    Step Functions Workflow                       │
│                                                                  │
│  START → Launch EC2 → Run Build → Deploy → Terminate → END     │
│            ↓            ↓           ↓         ↓                 │
│         AMI Ready   SSM Exec    S3 Upload  CloudWatch          │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Persistent Tomcat EC2 Instance

**Purpose**: Host all InterMine webapps (alliancemine, flymine, wormmine, etc.)

**Specifications**:
- Instance Type: `t3.xlarge` (4 vCPU, 16 GB RAM)
- OS: Amazon Linux 2023
- Storage: 200 GB gp3
- Ports: 8080-8086 (one per mine)
- Auto-start: Yes
- Backup: Daily EBS snapshots

**Software Stack**:
```
├── Tomcat 9.x (multi-instance)
│   ├── alliancemine on :8080
│   ├── flymine on :8081
│   ├── wormmine on :8082
│   ├── mousemine on :8083
│   ├── ratmine on :8084
│   ├── zebrafish on :8085
│   └── yeastmine on :8086
├── Nginx (reverse proxy + SSL)
├── CloudWatch Agent (metrics/logs)
└── SSM Agent (remote management)
```

**Cost**: ~$120/month (reserved instance: ~$85/month)

---

### 2. Ephemeral Build EC2 Instance

**Purpose**: Run InterMine builds, then self-terminate

**Specifications**:
- Instance Type: `r6i.2xlarge` (8 vCPU, 64 GB RAM) - **Memory Optimized**
- OS: Amazon Linux 2023 with custom AMI
- Storage: 500 GB gp3 (ephemeral, 10,000 IOPS)
- Lifecycle: Launch → Build → Terminate
- Cost: ~$0.504/hour × 7 hours = ~$3.53 per build

**Why 64GB Memory?**
- PostgreSQL: 16GB shared_buffers + connections
- Gradle/JVM: 32GB heap for compilation
- File system cache: 12GB for data files
- OS + overhead: 4GB
- Total: Perfect fit for single mine builds

**Custom AMI Contents** (`agr-intermine-builder-v1`):
```
├── Java 8 (OpenJDK)
├── Gradle 7.x
├── Git
├── Python 3.11 + dependencies
│   ├── boto3
│   ├── psycopg2
│   └── build scripts
├── InterMine dependencies pre-cached
├── Build scripts (/opt/intermine-builder/)
└── CloudWatch + SSM agents
```

**Startup Script** (User Data):
```bash
#!/bin/bash
# Auto-start build when instance launches

BUILD_ID="${BUILD_ID}"  # Passed from Step Functions
MINE_NAME="${MINE_NAME}"

cd /opt/intermine-builder
python3 -m src.main build full \
  --mine "$MINE_NAME" \
  --build-id "$BUILD_ID" \
  --rds-endpoint "$RDS_ENDPOINT"

# Upload logs to S3
aws s3 cp /var/log/intermine-build.log \
  s3://agr-builds/logs/$BUILD_ID/

# Self-terminate when done
shutdown -h now
```

**Cost**: Only pay when running (~10 builds/month = $55/month)

---

### 3. Persistent RDS PostgreSQL

**Purpose**: Single database instance hosting all mine databases

**Specifications**:
- Instance: `db.r6g.xlarge` (4 vCPU, 32 GB RAM)
- Storage: 500 GB gp3 (scalable)
- Multi-AZ: No (cost optimization)
- Backups: Automated daily snapshots
- Parameter Group: `intermine-optimized-pg13`

**Databases**:
```sql
-- Each mine gets 2 databases
alliancemine_db, alliancemine_profiles_db
flymine_db, flymine_profiles_db
wormmine_db, wormmine_profiles_db
mousemine_db, mousemine_profiles_db
ratmine_db, ratmine_profiles_db
zebrafish_db, zebrafish_profiles_db
yeastmine_db, yeastmine_profiles_db
```

**Cost**: ~$260/month (reserved: ~$180/month)

---

### 4. AWS Step Functions State Machine

**Purpose**: Orchestrate entire build lifecycle with automatic error handling

#### State Machine Definition

```json
{
  "Comment": "InterMine Build Orchestration",
  "StartAt": "ValidateInputs",
  "States": {
    "ValidateInputs": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:ValidateBuildInputs",
      "Next": "LaunchBuilderEC2",
      "Catch": [{
        "ErrorEquals": ["States.ALL"],
        "Next": "NotifyFailure"
      }]
    },

    "LaunchBuilderEC2": {
      "Type": "Task",
      "Resource": "arn:aws:states:::aws-sdk:ec2:runInstances",
      "Parameters": {
        "ImageId": "ami-XXXXXXXXX",
        "InstanceType": "c6i.4xlarge",
        "MinCount": 1,
        "MaxCount": 1,
        "IamInstanceProfile": {
          "Arn": "arn:aws:iam::ACCOUNT:instance-profile/InterMineBuilder"
        },
        "TagSpecifications": [{
          "ResourceType": "instance",
          "Tags": [
            {"Key": "Name", "Value.$": "$.mine_name"},
            {"Key": "BuildId", "Value.$": "$.build_id"},
            {"Key": "Type", "Value": "EphemeralBuilder"}
          ]
        }],
        "UserData.$": "States.Base64Encode($.user_data_script)"
      },
      "ResultPath": "$.ec2_result",
      "Next": "WaitForEC2Ready"
    },

    "WaitForEC2Ready": {
      "Type": "Wait",
      "Seconds": 60,
      "Next": "CheckEC2Status"
    },

    "CheckEC2Status": {
      "Type": "Task",
      "Resource": "arn:aws:states:::aws-sdk:ec2:describeInstanceStatus",
      "Parameters": {
        "InstanceIds.$": "$.ec2_result.Instances[0].InstanceId"
      },
      "ResultPath": "$.status_result",
      "Next": "IsEC2Ready"
    },

    "IsEC2Ready": {
      "Type": "Choice",
      "Choices": [{
        "Variable": "$.status_result.InstanceStatuses[0].InstanceStatus.Status",
        "StringEquals": "ok",
        "Next": "StartBuildProcess"
      }],
      "Default": "WaitForEC2Ready"
    },

    "StartBuildProcess": {
      "Type": "Task",
      "Resource": "arn:aws:states:::aws-sdk:ssm:sendCommand",
      "Parameters": {
        "InstanceIds.$": "States.Array($.ec2_result.Instances[0].InstanceId)",
        "DocumentName": "AWS-RunShellScript",
        "Parameters": {
          "commands": [
            "cd /opt/intermine-builder",
            "python3 -m src.main build full --mine $.mine_name"
          ]
        }
      },
      "ResultPath": "$.ssm_result",
      "Next": "MonitorBuildProgress"
    },

    "MonitorBuildProgress": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:MonitorBuildProgress",
      "Parameters": {
        "instance_id.$": "$.ec2_result.Instances[0].InstanceId",
        "command_id.$": "$.ssm_result.Command.CommandId"
      },
      "ResultPath": "$.monitor_result",
      "Next": "IsBuildComplete"
    },

    "IsBuildComplete": {
      "Type": "Choice",
      "Choices": [
        {
          "Variable": "$.monitor_result.status",
          "StringEquals": "SUCCESS",
          "Next": "DeployToTomcat"
        },
        {
          "Variable": "$.monitor_result.status",
          "StringEquals": "FAILED",
          "Next": "NotifyFailure"
        },
        {
          "Variable": "$.monitor_result.status",
          "StringEquals": "IN_PROGRESS",
          "Next": "WaitForBuildProgress"
        }
      ]
    },

    "WaitForBuildProgress": {
      "Type": "Wait",
      "Seconds": 300,
      "Next": "MonitorBuildProgress"
    },

    "DeployToTomcat": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:DeployToTomcat",
      "Parameters": {
        "mine_name.$": "$.mine_name",
        "build_id.$": "$.build_id",
        "tomcat_instance_id": "i-TOMCATINSTANCEID"
      },
      "ResultPath": "$.deploy_result",
      "Next": "TerminateBuilderEC2"
    },

    "TerminateBuilderEC2": {
      "Type": "Task",
      "Resource": "arn:aws:states:::aws-sdk:ec2:terminateInstances",
      "Parameters": {
        "InstanceIds.$": "States.Array($.ec2_result.Instances[0].InstanceId)"
      },
      "ResultPath": "$.terminate_result",
      "Next": "NotifySuccess"
    },

    "NotifySuccess": {
      "Type": "Task",
      "Resource": "arn:aws:states:::sns:publish",
      "Parameters": {
        "TopicArn": "arn:aws:sns:REGION:ACCOUNT:intermine-build-notifications",
        "Subject": "Build Success",
        "Message.$": "States.Format('Build {} for {} completed successfully', $.build_id, $.mine_name)"
      },
      "End": true
    },

    "NotifyFailure": {
      "Type": "Task",
      "Resource": "arn:aws:states:::sns:publish",
      "Parameters": {
        "TopicArn": "arn:aws:sns:REGION:ACCOUNT:intermine-build-notifications",
        "Subject": "Build Failure",
        "Message.$": "States.Format('Build {} for {} failed: {}', $.build_id, $.mine_name, $.error_message)"
      },
      "Next": "CleanupFailedBuild"
    },

    "CleanupFailedBuild": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:CleanupFailedBuild",
      "Parameters": {
        "instance_id.$": "$.ec2_result.Instances[0].InstanceId"
      },
      "End": true
    }
  }
}
```

---

### 5. Lambda Functions

#### `ValidateBuildInputs`
```python
def lambda_handler(event, context):
    """Validate build request before starting."""
    required = ['mine_name', 'release_version']
    if not all(k in event for k in required):
        raise ValueError("Missing required parameters")

    # Check if mine exists
    valid_mines = ['alliancemine', 'flymine', 'wormmine', ...]
    if event['mine_name'] not in valid_mines:
        raise ValueError(f"Invalid mine: {event['mine_name']}")

    return event
```

#### `MonitorBuildProgress`
```python
import boto3

ssm = boto3.client('ssm')
cloudwatch = boto3.client('cloudwatch')

def lambda_handler(event, context):
    """Monitor SSM command execution and build progress."""
    command_id = event['command_id']
    instance_id = event['instance_id']

    # Get command status
    response = ssm.get_command_invocation(
        CommandId=command_id,
        InstanceId=instance_id
    )

    status = response['Status']

    if status == 'Success':
        return {'status': 'SUCCESS'}
    elif status in ['Failed', 'Cancelled', 'TimedOut']:
        return {'status': 'FAILED', 'error': response.get('StandardErrorContent')}
    else:
        return {'status': 'IN_PROGRESS'}
```

#### `DeployToTomcat`
```python
def lambda_handler(event, context):
    """Deploy built webapp to Tomcat server."""
    ssm = boto3.client('ssm')

    mine_name = event['mine_name']
    build_id = event['build_id']
    tomcat_instance = event['tomcat_instance_id']

    # Download WAR from S3 and deploy
    commands = [
        f"aws s3 cp s3://agr-builds/{build_id}/{mine_name}.war /tmp/",
        f"systemctl stop tomcat@{mine_name}",
        f"cp /tmp/{mine_name}.war /opt/tomcat/{mine_name}/webapps/",
        f"systemctl start tomcat@{mine_name}",
        f"curl -f http://localhost:8080/{mine_name}/service/version"
    ]

    response = ssm.send_command(
        InstanceIds=[tomcat_instance],
        DocumentName='AWS-RunShellScript',
        Parameters={'commands': commands}
    )

    return {'command_id': response['Command']['CommandId']}
```

---

## Implementation Plan

### Phase 1: Infrastructure Setup (Week 1)

1. **Create Custom AMI**
   ```bash
   # Launch base instance
   aws ec2 run-instances --image-id ami-amazon-linux-2023 ...

   # SSH and install dependencies
   sudo yum install -y java-1.8.0-openjdk git
   # ... install all InterMine dependencies

   # Create AMI
   aws ec2 create-image --instance-id i-xxx --name agr-intermine-builder-v1
   ```

2. **Launch Persistent Tomcat EC2**
   - Use Terraform/CloudFormation
   - Configure multi-instance Tomcat
   - Set up Nginx reverse proxy
   - Configure auto-scaling group (min=1, max=1)

3. **Configure RDS**
   - Create PostgreSQL 13 instance
   - Apply InterMine parameter group
   - Create all mine databases
   - Set up automated backups

### Phase 2: Step Functions Implementation (Week 2)

1. **Create Lambda Functions**
   - Package Python functions with dependencies
   - Deploy to Lambda
   - Configure IAM roles

2. **Create Step Functions State Machine**
   - Deploy JSON definition
   - Test with simple build
   - Add error handling

3. **Set up Notifications**
   - Create SNS topic
   - Subscribe email/Slack

### Phase 3: Python Build Scripts (Week 3-4)

**Update build system to work with Step Functions**

Create `src/lib/builder/ec2_builder.py`:

```python
"""EC2-based build system for Step Functions integration."""

import boto3
import subprocess
from pathlib import Path
from src.lib.config import Config

class EC2Builder:
    def __init__(self, config: Config):
        self.config = config
        self.ec2 = boto3.client('ec2')
        self.ssm = boto3.client('ssm')
        self.s3 = boto3.client('s3')

    def build_full(self, mine_name: str, build_id: str):
        """Execute full mine build on EC2 instance."""
        try:
            # 1. Clone repositories
            self._clone_repos(mine_name)

            # 2. Build InterMine core
            self._build_intermine_core()

            # 3. Build biosources
            self._build_biosources(mine_name)

            # 4. Run project_build
            self._run_project_build(mine_name)

            # 5. Package webapp
            war_file = self._package_webapp(mine_name)

            # 6. Upload to S3
            self._upload_to_s3(war_file, build_id, mine_name)

            return {'status': 'success', 'war_location': f"s3://agr-builds/{build_id}/{mine_name}.war"}

        except Exception as e:
            return {'status': 'failed', 'error': str(e)}
```

### Phase 4: Testing & Deployment (Week 5)

1. **Test Build Flow**
   - Trigger Step Functions manually
   - Monitor all stages
   - Verify EC2 termination

2. **Set Up Scheduled Builds**
   ```json
   {
     "schedule": "cron(0 2 * * ? *)",  // 2 AM daily
     "target": "step-functions-arn",
     "input": {
       "mine_name": "alliancemine",
       "release_version": "8.2.0"
     }
   }
   ```

3. **Create Dashboard**
   - CloudWatch dashboard showing:
     - Build duration
     - Success/failure rate
     - EC2 costs
     - Build queue

---

## Benefits of This Architecture

✅ **Cost Optimized**: Builder EC2 only runs during builds (~$55/month vs $500/month)
✅ **Scalable**: Can run multiple builds in parallel if needed
✅ **Resilient**: Step Functions handles failures and retries
✅ **Observable**: CloudWatch logs/metrics for everything
✅ **Maintainable**: All infrastructure as code (Terraform)
✅ **Flexible**: Easy to add new mines or change instance types

---

## Next Steps

**Would you like me to:**

1. Create the Terraform/CloudFormation templates for this infrastructure?
2. Implement the Python EC2Builder class?
3. Write the Step Functions state machine JSON?
4. Create the Lambda functions for orchestration?

**Let me know which part you'd like to tackle first!**
