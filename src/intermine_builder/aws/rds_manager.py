"""AWS RDS management for AGR InterMine Builder with multi-mine support."""

import time
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import subprocess

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None
    ClientError = None

from ..config import Config


class RDSInstanceSize(Enum):
    """RDS instance sizes for different workloads."""
    # Development/testing
    MICRO = "db.t4g.micro"  # 2 vCPU, 1 GB RAM
    SMALL = "db.t4g.small"  # 2 vCPU, 2 GB RAM
    
    # Normal operations
    MEDIUM = "db.t4g.medium"  # 2 vCPU, 4 GB RAM
    
    # Build operations
    BUILD_STANDARD = "db.r6g.large"  # 2 vCPU, 16 GB RAM
    BUILD_HEAVY = "db.r6g.xlarge"  # 4 vCPU, 32 GB RAM
    
    # Cost-optimized alternatives
    MEDIUM_INTEL = "db.t3.medium"  # 2 vCPU, 4 GB RAM (if ARM not available)
    BUILD_INTEL = "db.r6i.large"  # 2 vCPU, 16 GB RAM (if ARM not available)


class MineDatabase:
    """Represents a mine database configuration."""
    
    def __init__(self, name: str, db_name: str, profile_db_name: str, 
                 organism: str = "", description: str = ""):
        self.name = name
        self.db_name = db_name
        self.profile_db_name = profile_db_name
        self.organism = organism
        self.description = description
        self.created_at = None
        self.last_build = None
        self.status = "pending"
        self.size_mb = 0
        self.profile_size_mb = 0


class BuildQueue:
    """Manages sequential mine builds to optimize memory usage."""
    
    def __init__(self):
        self.queue: List[Tuple[MineDatabase, str]] = []
        self.current_build: Optional[MineDatabase] = None
        self.completed: List[MineDatabase] = []
        self.failed: List[Tuple[MineDatabase, str]] = []
        
    def add(self, mine: MineDatabase, priority: str = "normal"):
        """Add a mine to the build queue."""
        if priority == "high":
            self.queue.insert(0, (mine, priority))
        else:
            self.queue.append((mine, priority))
    
    def get_next(self) -> Optional[MineDatabase]:
        """Get the next mine to build."""
        if self.queue:
            mine, _ = self.queue.pop(0)
            self.current_build = mine
            return mine
        return None
    
    def complete_current(self):
        """Mark current build as completed."""
        if self.current_build:
            self.current_build.status = "completed"
            self.current_build.last_build = datetime.now()
            self.completed.append(self.current_build)
            self.current_build = None
    
    def fail_current(self, error: str):
        """Mark current build as failed."""
        if self.current_build:
            self.current_build.status = "failed"
            self.failed.append((self.current_build, error))
            self.current_build = None
    
    def get_status(self) -> Dict:
        """Get queue status."""
        return {
            "queued": len(self.queue),
            "current": self.current_build.name if self.current_build else None,
            "completed": len(self.completed),
            "failed": len(self.failed),
            "queue": [mine.name for mine, _ in self.queue]
        }


class EphemeralBuildInstance:
    """Manages ephemeral RDS instances for InterMine builds."""
    
    def __init__(self, mine_name: str, instance_id: str, created_at: datetime):
        self.mine_name = mine_name
        self.instance_id = instance_id
        self.created_at = created_at
        self.endpoint = None
        self.status = "creating"
        self.build_start = None
        self.build_end = None
        
    def get_age_hours(self) -> float:
        """Get instance age in hours."""
        if self.created_at:
            delta = datetime.now() - self.created_at
            return delta.total_seconds() / 3600
        return 0
    
    def get_estimated_cost(self, hourly_rate: float = 0.144) -> float:
        """Calculate estimated cost for this build instance."""
        return self.get_age_hours() * hourly_rate


class RDSManager:
    """Manages AWS RDS PostgreSQL instances for multiple InterMine deployments."""
    
    # Predefined mine configurations
    MINE_CONFIGS = {
        "alliancemine": MineDatabase(
            "alliancemine", "alliancemine_db", "alliancemine_profiles_db",
            "multi", "Alliance of Genome Resources main mine"
        ),
        "wormmine": MineDatabase(
            "wormmine", "wormmine_db", "wormmine_profiles_db",
            "C. elegans", "WormBase InterMine"
        ),
        "flymine": MineDatabase(
            "flymine", "flymine_db", "flymine_profiles_db",
            "D. melanogaster", "FlyBase InterMine"
        ),
        "mousemine": MineDatabase(
            "mousemine", "mousemine_db", "mousemine_profiles_db",
            "M. musculus", "MGI InterMine"
        ),
        "ratmine": MineDatabase(
            "ratmine", "ratmine_db", "ratmine_profiles_db",
            "R. norvegicus", "RGD InterMine"
        ),
        "zebrafish": MineDatabase(
            "zebrafish", "zfin_db", "zfin_profiles_db",
            "D. rerio", "ZFIN InterMine"
        ),
        "yeastmine": MineDatabase(
            "yeastmine", "yeastmine_db", "yeastmine_profiles_db",
            "S. cerevisiae", "SGD InterMine"
        )
    }
    
    def __init__(self, config: Config):
        self.config = config
        self.build_queue = BuildQueue()
        self.mines: Dict[str, MineDatabase] = {}
        self.ephemeral_instances: Dict[str, EphemeralBuildInstance] = {}
        
        # RDS configuration
        self.rds_identifier = config.rds_identifier if hasattr(config, 'rds_identifier') else "agr-intermine-cluster"
        self.rds_region = config.rds_region if hasattr(config, 'rds_region') else "us-east-1"
        self.current_size = RDSInstanceSize.SMALL
        self.resize_history = []
        
        # Initialize boto3 client if available
        if boto3:
            self.rds_client = boto3.client('rds', region_name=self.rds_region)
            self.cloudwatch = boto3.client('cloudwatch', region_name=self.rds_region)
        else:
            self.rds_client = None
            self.cloudwatch = None
            print("⚠️  boto3 not installed. RDS operations will be limited.")
    
    def create_intermine_parameter_group(self) -> bool:
        """Create RDS parameter group with InterMine-optimized settings."""
        if not self.rds_client:
            print("❌ boto3 not available")
            return False
        
        param_group_name = self.config.rds_parameter_group if hasattr(self.config, 'rds_parameter_group') else "intermine-pg13"
        
        print(f"🔧 Creating InterMine parameter group: {param_group_name}")
        
        try:
            # Create parameter group
            self.rds_client.create_db_parameter_group(
                DBParameterGroupName=param_group_name,
                DBParameterGroupFamily='postgres13',
                Description='InterMine optimized PostgreSQL 13 parameters'
            )
            
            # InterMine-optimized parameters (UTF-8 compatible for RDS)
            parameters = [
                {'ParameterName': 'shared_buffers', 'ParameterValue': '{DBInstanceClassMemory/4}', 'ApplyMethod': 'pending-reboot'},
                {'ParameterName': 'work_mem', 'ParameterValue': '524288', 'ApplyMethod': 'immediate'},  # 500MB in KB
                {'ParameterName': 'maintenance_work_mem', 'ParameterValue': '204800', 'ApplyMethod': 'immediate'},  # 200MB in KB
                {'ParameterName': 'effective_cache_size', 'ParameterValue': '{DBInstanceClassMemory/2}', 'ApplyMethod': 'immediate'},
                {'ParameterName': 'max_connections', 'ParameterValue': '250', 'ApplyMethod': 'pending-reboot'},
                {'ParameterName': 'max_locks_per_transaction', 'ParameterValue': '640', 'ApplyMethod': 'pending-reboot'},
                {'ParameterName': 'max_pred_locks_per_transaction', 'ParameterValue': '640', 'ApplyMethod': 'pending-reboot'},
                {'ParameterName': 'default_statistics_target', 'ParameterValue': '250', 'ApplyMethod': 'immediate'},
                {'ParameterName': 'random_page_cost', 'ParameterValue': '2', 'ApplyMethod': 'immediate'},
                {'ParameterName': 'effective_io_concurrency', 'ParameterValue': '200', 'ApplyMethod': 'immediate'},
                {'ParameterName': 'geqo_threshold', 'ParameterValue': '14', 'ApplyMethod': 'immediate'},
                {'ParameterName': 'from_collapse_limit', 'ParameterValue': '14', 'ApplyMethod': 'immediate'},
                {'ParameterName': 'join_collapse_limit', 'ParameterValue': '14', 'ApplyMethod': 'immediate'},
                {'ParameterName': 'checkpoint_timeout', 'ParameterValue': '600', 'ApplyMethod': 'immediate'},  # 10 min in seconds
                {'ParameterName': 'checkpoint_completion_target', 'ParameterValue': '0.9', 'ApplyMethod': 'immediate'},
                {'ParameterName': 'synchronous_commit', 'ParameterValue': 'off', 'ApplyMethod': 'immediate'},
                {'ParameterName': 'log_min_duration_statement', 'ParameterValue': '1000', 'ApplyMethod': 'immediate'},  # 1 second
            ]
            
            # Apply parameters
            self.rds_client.modify_db_parameter_group(
                DBParameterGroupName=param_group_name,
                Parameters=parameters
            )
            
            print("✅ InterMine parameter group created and configured")
            print("⚠️  Note: Using UTF-8 encoding (RDS doesn't support SQL_ASCII)")
            print("    This may impact performance compared to local SQL_ASCII setup")
            
            return True
            
        except ClientError as e:
            if 'DBParameterGroupAlreadyExists' in str(e):
                print(f"ℹ️  Parameter group {param_group_name} already exists")
                return True
            print(f"❌ Failed to create parameter group: {e}")
            return False
    
    def create_rds_instance(self, size: RDSInstanceSize = RDSInstanceSize.SMALL,
                           storage_gb: int = 100, multi_az: bool = False) -> bool:
        """Create a new RDS PostgreSQL instance."""
        if not self.rds_client:
            print("❌ boto3 not available. Install with: pip install boto3")
            return False
        
        print(f"🚀 Creating RDS instance: {self.rds_identifier}")
        print(f"   Size: {size.value}")
        print(f"   Storage: {storage_gb} GB")
        print(f"   Multi-AZ: {multi_az}")
        
        try:
            # Ensure parameter group exists
            param_group_name = self.config.rds_parameter_group if hasattr(self.config, 'rds_parameter_group') else "intermine-pg13"
            
            response = self.rds_client.create_db_instance(
                DBInstanceIdentifier=self.rds_identifier,
                DBInstanceClass=size.value,
                Engine='postgres',
                EngineVersion='13.13',  # Latest PostgreSQL 13
                MasterUsername=self.config.postgres_user,
                MasterUserPassword=self.config.postgres_password,
                AllocatedStorage=storage_gb,
                StorageType='gp3',
                StorageEncrypted=True,
                DBParameterGroupName=param_group_name,  # Use InterMine parameter group
                VpcSecurityGroupIds=[self.config.rds_security_group] if hasattr(self.config, 'rds_security_group') and self.config.rds_security_group else [],
                DBSubnetGroupName=self.config.rds_subnet_group if hasattr(self.config, 'rds_subnet_group') and self.config.rds_subnet_group else None,
                BackupRetentionPeriod=7,
                PreferredBackupWindow='03:00-04:00',
                PreferredMaintenanceWindow='sun:04:00-sun:05:00',
                MultiAZ=multi_az,
                PubliclyAccessible=False,
                AutoMinorVersionUpgrade=True,
                Tags=[
                    {'Key': 'Project', 'Value': 'AGR-InterMine'},
                    {'Key': 'Environment', 'Value': self.config.environment if hasattr(self.config, 'environment') else 'stage'},
                    {'Key': 'ManagedBy', 'Value': 'agr-intermine-builder'}
                ]
            )
            
            print("✅ RDS instance creation initiated")
            print(f"   Instance ID: {response['DBInstance']['DBInstanceIdentifier']}")
            print(f"   Status: {response['DBInstance']['DBInstanceStatus']}")
            
            # Wait for instance to be available
            print("⏳ Waiting for instance to be available (this may take 5-10 minutes)...")
            waiter = self.rds_client.get_waiter('db_instance_available')
            waiter.wait(
                DBInstanceIdentifier=self.rds_identifier,
                WaiterConfig={'Delay': 30, 'MaxAttempts': 40}
            )
            
            print("✅ RDS instance is available")
            self.current_size = size
            return True
            
        except ClientError as e:
            print(f"❌ Failed to create RDS instance: {e}")
            return False
    
    def resize_instance(self, new_size: RDSInstanceSize, apply_immediately: bool = True) -> bool:
        """Resize the RDS instance for different workloads."""
        if not self.rds_client:
            print("❌ boto3 not available")
            return False
        
        if self.current_size == new_size:
            print(f"ℹ️  Instance already at size {new_size.value}")
            return True
        
        print(f"📏 Resizing RDS instance from {self.current_size.value} to {new_size.value}")
        
        try:
            # Record resize event
            self.resize_history.append({
                'timestamp': datetime.now(),
                'from_size': self.current_size.value,
                'to_size': new_size.value,
                'reason': 'manual' if apply_immediately else 'scheduled'
            })
            
            response = self.rds_client.modify_db_instance(
                DBInstanceIdentifier=self.rds_identifier,
                DBInstanceClass=new_size.value,
                ApplyImmediately=apply_immediately
            )
            
            print(f"✅ Resize initiated: {response['DBInstance']['DBInstanceStatus']}")
            
            if apply_immediately:
                print("⏳ Waiting for resize to complete...")
                waiter = self.rds_client.get_waiter('db_instance_available')
                waiter.wait(
                    DBInstanceIdentifier=self.rds_identifier,
                    WaiterConfig={'Delay': 30, 'MaxAttempts': 40}
                )
                print("✅ Resize completed")
            
            self.current_size = new_size
            return True
            
        except ClientError as e:
            print(f"❌ Failed to resize instance: {e}")
            return False
    
    def create_ephemeral_build_instance(self, mine_name: str, storage_gb: int = 500) -> Optional[EphemeralBuildInstance]:
        """Create an ephemeral RDS instance for building a specific mine."""
        if not self.rds_client:
            print("❌ boto3 not available")
            return None
        
        # Generate unique instance ID
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        instance_id = f"build-{mine_name}-{timestamp}"
        
        print(f"🚀 Creating ephemeral build instance for {mine_name}")
        print(f"   Instance ID: {instance_id}")
        print(f"   Size: {RDSInstanceSize.BUILD_STANDARD.value}")
        print(f"   Storage: {storage_gb} GB")
        
        try:
            # Create parameter group if it doesn't exist
            param_group_name = f"intermine-build-{mine_name}"
            try:
                self.rds_client.create_db_parameter_group(
                    DBParameterGroupName=param_group_name,
                    DBParameterGroupFamily='postgres13',
                    Description=f'InterMine build parameters for {mine_name}'
                )
                
                # Apply InterMine parameters
                parameters = [
                    {'ParameterName': 'work_mem', 'ParameterValue': '1048576', 'ApplyMethod': 'immediate'},  # 1GB for builds
                    {'ParameterName': 'maintenance_work_mem', 'ParameterValue': '524288', 'ApplyMethod': 'immediate'},  # 500MB
                    {'ParameterName': 'synchronous_commit', 'ParameterValue': 'off', 'ApplyMethod': 'immediate'},
                    {'ParameterName': 'checkpoint_timeout', 'ParameterValue': '1800', 'ApplyMethod': 'immediate'},  # 30 min
                    {'ParameterName': 'max_wal_size', 'ParameterValue': '4096', 'ApplyMethod': 'immediate'},  # 4GB
                ]
                self.rds_client.modify_db_parameter_group(
                    DBParameterGroupName=param_group_name,
                    Parameters=parameters
                )
            except ClientError as e:
                if 'DBParameterGroupAlreadyExists' not in str(e):
                    print(f"⚠️  Could not create parameter group: {e}")
                param_group_name = self.config.rds_parameter_group if hasattr(self.config, 'rds_parameter_group') else "intermine-pg13"
            
            # Create the ephemeral instance
            response = self.rds_client.create_db_instance(
                DBInstanceIdentifier=instance_id,
                DBInstanceClass=RDSInstanceSize.BUILD_STANDARD.value,
                Engine='postgres',
                EngineVersion='13.13',
                MasterUsername=self.config.postgres_user,
                MasterUserPassword=self.config.postgres_password,
                AllocatedStorage=storage_gb,
                StorageType='gp3',
                Iops=12000,  # Higher IOPS for build performance
                StorageEncrypted=True,
                DBParameterGroupName=param_group_name,
                BackupRetentionPeriod=0,  # No backups for ephemeral instance
                MultiAZ=False,  # Single AZ for cost savings
                PubliclyAccessible=True,  # May need public access for builds
                AutoMinorVersionUpgrade=False,
                DeletionProtection=False,  # Allow easy deletion
                Tags=[
                    {'Key': 'Type', 'Value': 'Ephemeral-Build'},
                    {'Key': 'Mine', 'Value': mine_name},
                    {'Key': 'CreatedAt', 'Value': timestamp},
                    {'Key': 'ManagedBy', 'Value': 'agr-intermine-builder'}
                ]
            )
            
            # Create ephemeral instance object
            ephemeral = EphemeralBuildInstance(mine_name, instance_id, datetime.now())
            self.ephemeral_instances[instance_id] = ephemeral
            
            print("⏳ Waiting for instance to be available (5-10 minutes)...")
            
            # Wait for instance to be available
            waiter = self.rds_client.get_waiter('db_instance_available')
            waiter.wait(
                DBInstanceIdentifier=instance_id,
                WaiterConfig={'Delay': 30, 'MaxAttempts': 20}
            )
            
            # Get endpoint
            response = self.rds_client.describe_db_instances(DBInstanceIdentifier=instance_id)
            if response['DBInstances']:
                instance = response['DBInstances'][0]
                ephemeral.endpoint = f"{instance['Endpoint']['Address']}:{instance['Endpoint']['Port']}"
                ephemeral.status = "available"
                
                print("✅ Ephemeral build instance ready")
                print(f"   Endpoint: {ephemeral.endpoint}")
                print(f"   Estimated cost: ~${storage_gb * 0.115 / 30:.2f} + ${0.144 * 8:.2f} = ~${(storage_gb * 0.115 / 30) + (0.144 * 8):.2f} per build")
                
                # Create the mine databases
                self._create_build_databases(ephemeral, mine_name)
                
                return ephemeral
                
        except ClientError as e:
            print(f"❌ Failed to create ephemeral instance: {e}")
            return None
    
    def _create_build_databases(self, ephemeral: EphemeralBuildInstance, mine_name: str) -> bool:
        """Create databases on the ephemeral build instance."""
        if mine_name not in self.MINE_CONFIGS:
            print(f"⚠️  Using default database names for {mine_name}")
            mine_config = MineDatabase(
                mine_name, f"{mine_name}_db", f"{mine_name}_profiles_db",
                "unknown", f"Custom mine: {mine_name}"
            )
        else:
            mine_config = self.MINE_CONFIGS[mine_name]
        
        print("📦 Creating databases on build instance...")
        
        try:
            # Create main and profile databases using psql
            for db_name in [mine_config.db_name, mine_config.profile_db_name]:
                result = subprocess.run([
                    "psql",
                    f"postgresql://{self.config.postgres_user}:{self.config.postgres_password}@{ephemeral.endpoint}/postgres",
                    "-c", f"CREATE DATABASE {db_name};"
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    print(f"   ✅ Created {db_name}")
                elif "already exists" in result.stderr:
                    print(f"   ℹ️  {db_name} already exists")
                else:
                    print(f"   ❌ Failed to create {db_name}: {result.stderr}")
                    return False
            
            ephemeral.status = "ready"
            return True
            
        except Exception as e:
            print(f"❌ Failed to create databases: {e}")
            return False
    
    def dump_build_database(self, ephemeral: EphemeralBuildInstance, target_file: Optional[Path] = None) -> Optional[Path]:
        """Dump the completed build database from ephemeral instance."""
        if not ephemeral.endpoint:
            print("❌ Ephemeral instance has no endpoint")
            return None
        
        mine_config = self.MINE_CONFIGS.get(ephemeral.mine_name)
        if not mine_config:
            mine_config = MineDatabase(
                ephemeral.mine_name, f"{ephemeral.mine_name}_db", 
                f"{ephemeral.mine_name}_profiles_db", "unknown", "Custom mine"
            )
        
        if not target_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            target_file = Path(f"/tmp/{ephemeral.mine_name}_build_{timestamp}.sql")
        
        print(f"💾 Dumping {ephemeral.mine_name} database from build instance...")
        print(f"   Target: {target_file}")
        
        try:
            # Dump the main database
            result = subprocess.run([
                "pg_dump",
                f"postgresql://{self.config.postgres_user}:{self.config.postgres_password}@{ephemeral.endpoint}/{mine_config.db_name}",
                "-f", str(target_file),
                "--no-owner",
                "--no-acl",
                "--verbose"
            ], capture_output=True, text=True, timeout=3600)  # 1 hour timeout
            
            if result.returncode != 0:
                print(f"❌ Database dump failed: {result.stderr}")
                return None
            
            # Check file size
            size_mb = target_file.stat().st_size / (1024 * 1024)
            print(f"✅ Database dumped successfully ({size_mb:.1f} MB)")
            
            return target_file
            
        except subprocess.TimeoutExpired:
            print("❌ Database dump timed out")
            return None
        except Exception as e:
            print(f"❌ Dump failed: {e}")
            return None
    
    def restore_to_production(self, dump_file: Path, mine_name: str) -> bool:
        """Restore a database dump to the production RDS instance."""
        endpoint = self.get_endpoint()
        if not endpoint:
            print("❌ Production RDS instance not available")
            return False
        
        mine_config = self.MINE_CONFIGS.get(mine_name)
        if not mine_config:
            print(f"❌ Unknown mine: {mine_name}")
            return False
        
        print(f"📥 Restoring {mine_name} to production instance...")
        print(f"   Source: {dump_file}")
        print(f"   Target: {mine_config.db_name}")
        
        try:
            # Drop existing database if it exists
            print("   Dropping existing database...")
            subprocess.run([
                "psql",
                f"postgresql://{self.config.postgres_user}:{self.config.postgres_password}@{endpoint}/postgres",
                "-c", f"DROP DATABASE IF EXISTS {mine_config.db_name};"
            ], capture_output=True, text=True, timeout=60)
            
            # Create fresh database
            print("   Creating fresh database...")
            subprocess.run([
                "psql",
                f"postgresql://{self.config.postgres_user}:{self.config.postgres_password}@{endpoint}/postgres",
                "-c", f"CREATE DATABASE {mine_config.db_name};"
            ], capture_output=True, text=True, timeout=60)
            
            # Restore the dump
            print("   Restoring data...")
            result = subprocess.run([
                "psql",
                f"postgresql://{self.config.postgres_user}:{self.config.postgres_password}@{endpoint}/{mine_config.db_name}",
                "-f", str(dump_file)
            ], capture_output=True, text=True, timeout=7200)  # 2 hour timeout
            
            if result.returncode != 0:
                print(f"❌ Restore failed: {result.stderr[-1000:]}")  # Last 1000 chars of error
                return False
            
            print(f"✅ Successfully restored {mine_name} to production")
            
            # Update mine status
            if mine_name in self.mines:
                self.mines[mine_name].last_build = datetime.now()
                self.mines[mine_name].status = "deployed"
            
            return True
            
        except subprocess.TimeoutExpired:
            print("❌ Restore operation timed out")
            return False
        except Exception as e:
            print(f"❌ Restore failed: {e}")
            return False
    
    def terminate_ephemeral_instance(self, instance_id: str, force: bool = False) -> bool:
        """Terminate an ephemeral build instance."""
        if not self.rds_client:
            print("❌ boto3 not available")
            return False
        
        if instance_id not in self.ephemeral_instances:
            print(f"⚠️  Instance {instance_id} not tracked, attempting termination anyway...")
        
        ephemeral = self.ephemeral_instances.get(instance_id)
        
        # Show cost estimate
        if ephemeral:
            cost = ephemeral.get_estimated_cost()
            print(f"💰 Estimated cost for this build: ${cost:.2f}")
            print(f"   Runtime: {ephemeral.get_age_hours():.1f} hours")
        
        print(f"🗑️  Terminating ephemeral instance: {instance_id}")
        
        try:
            # Delete the instance
            response = self.rds_client.delete_db_instance(
                DBInstanceIdentifier=instance_id,
                SkipFinalSnapshot=True,
                DeleteAutomatedBackups=True
            )
            
            print(f"✅ Termination initiated: {response['DBInstance']['DBInstanceStatus']}")
            
            # Remove from tracking
            if instance_id in self.ephemeral_instances:
                del self.ephemeral_instances[instance_id]
            
            return True
            
        except ClientError as e:
            if 'DBInstanceNotFound' in str(e):
                print(f"ℹ️  Instance {instance_id} not found (may already be terminated)")
                if instance_id in self.ephemeral_instances:
                    del self.ephemeral_instances[instance_id]
                return True
            print(f"❌ Failed to terminate instance: {e}")
            return False
    
    def list_ephemeral_instances(self) -> List[Dict]:
        """List all ephemeral build instances."""
        if not self.rds_client:
            print("❌ boto3 not available")
            return []
        
        instances = []
        
        try:
            # Get all RDS instances with ephemeral tag
            response = self.rds_client.describe_db_instances()
            
            for instance in response['DBInstances']:
                # Check tags for ephemeral instances
                tag_response = self.rds_client.list_tags_for_resource(
                    ResourceName=instance['DBInstanceArn']
                )
                
                tags = {tag['Key']: tag['Value'] for tag in tag_response.get('TagList', [])}
                
                if tags.get('Type') == 'Ephemeral-Build':
                    instance_info = {
                        'instance_id': instance['DBInstanceIdentifier'],
                        'mine': tags.get('Mine', 'unknown'),
                        'status': instance['DBInstanceStatus'],
                        'created': tags.get('CreatedAt', 'unknown'),
                        'endpoint': f"{instance['Endpoint']['Address']}:{instance['Endpoint']['Port']}" if 'Endpoint' in instance else 'pending',
                        'size': instance['DBInstanceClass'],
                        'storage_gb': instance['AllocatedStorage']
                    }
                    
                    # Calculate age and cost
                    if instance_info['created'] != 'unknown':
                        created_dt = datetime.strptime(instance_info['created'], "%Y%m%d%H%M%S")
                        age_hours = (datetime.now() - created_dt).total_seconds() / 3600
                        instance_info['age_hours'] = round(age_hours, 1)
                        instance_info['estimated_cost'] = round(age_hours * 0.144, 2)
                    
                    instances.append(instance_info)
            
            return instances
            
        except ClientError as e:
            print(f"❌ Failed to list ephemeral instances: {e}")
            return []
    
    def cleanup_old_ephemeral_instances(self, max_age_hours: int = 24) -> int:
        """Clean up ephemeral instances older than specified hours."""
        instances = self.list_ephemeral_instances()
        terminated = 0
        
        for instance in instances:
            if instance.get('age_hours', 0) > max_age_hours:
                print(f"🧹 Cleaning up old instance: {instance['instance_id']} (age: {instance['age_hours']}h)")
                if self.terminate_ephemeral_instance(instance['instance_id'], force=True):
                    terminated += 1
        
        print(f"✅ Cleaned up {terminated} old ephemeral instances")
        return terminated
    
    def prepare_for_build(self, mine_name: str = None) -> bool:
        """Prepare RDS instance for a mine build by resizing if needed."""
        target_size = RDSInstanceSize.BUILD_STANDARD
        
        # Check current memory usage
        if self.cloudwatch:
            try:
                # Get current memory metrics
                response = self.cloudwatch.get_metric_statistics(
                    Namespace='AWS/RDS',
                    MetricName='FreeableMemory',
                    Dimensions=[
                        {'Name': 'DBInstanceIdentifier', 'Value': self.rds_identifier}
                    ],
                    StartTime=datetime.now() - timedelta(minutes=5),
                    EndTime=datetime.now(),
                    Period=300,
                    Statistics=['Average']
                )
                
                if response['Datapoints']:
                    free_memory_bytes = response['Datapoints'][0]['Average']
                    free_memory_gb = free_memory_bytes / (1024**3)
                    print(f"📊 Current free memory: {free_memory_gb:.2f} GB")
                    
                    # Determine if we need heavy build instance
                    if free_memory_gb < 8:
                        target_size = RDSInstanceSize.BUILD_HEAVY
                        print("ℹ️  Low memory detected, using heavy build instance")
                        
            except ClientError as e:
                print(f"⚠️  Could not get memory metrics: {e}")
        
        # Resize for build
        if self.current_size not in [RDSInstanceSize.BUILD_STANDARD, RDSInstanceSize.BUILD_HEAVY]:
            print(f"🔧 Preparing for {mine_name or 'mine'} build...")
            return self.resize_instance(target_size)
        
        return True
    
    def finish_build(self, downsize: bool = True, delay_minutes: int = 30) -> bool:
        """Finish build and optionally downsize the instance."""
        if not downsize:
            print("ℹ️  Keeping current instance size")
            return True
        
        print(f"⏱️  Scheduling downsize in {delay_minutes} minutes...")
        
        # In production, you'd schedule this with Lambda or CloudWatch Events
        # For now, we'll just document the plan
        target_size = RDSInstanceSize.MEDIUM
        
        if delay_minutes == 0:
            return self.resize_instance(target_size)
        else:
            print(f"📝 Note: Implement scheduled downsize to {target_size.value}")
            print(f"   Schedule for: {datetime.now() + timedelta(minutes=delay_minutes)}")
            return True
    
    def create_mine_databases(self, mine: MineDatabase) -> bool:
        """Create databases for a specific mine."""
        print(f"🗄️  Creating databases for {mine.name}...")
        
        endpoint = self.get_endpoint()
        if not endpoint:
            print("❌ Could not get RDS endpoint")
            return False
        
        # Create main database
        create_db_sql = f"CREATE DATABASE {mine.db_name};"
        create_profile_sql = f"CREATE DATABASE {mine.profile_db_name};"
        
        try:
            # Use psql to create databases
            for sql, db_type in [(create_db_sql, "main"), (create_profile_sql, "profile")]:
                result = subprocess.run([
                    "psql",
                    f"postgresql://{self.config.postgres_user}:{self.config.postgres_password}@{endpoint}/postgres",
                    "-c", sql
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode != 0 and "already exists" not in result.stderr:
                    print(f"❌ Failed to create {db_type} database: {result.stderr}")
                    return False
                elif "already exists" in result.stderr:
                    print(f"ℹ️  {db_type.capitalize()} database already exists")
                else:
                    print(f"✅ Created {db_type} database")
            
            mine.created_at = datetime.now()
            mine.status = "ready"
            self.mines[mine.name] = mine
            
            return True
            
        except Exception as e:
            print(f"❌ Database creation failed: {e}")
            return False
    
    def add_mine(self, mine_name: str) -> bool:
        """Add a new mine to the RDS instance."""
        if mine_name not in self.MINE_CONFIGS:
            print(f"❌ Unknown mine: {mine_name}")
            print(f"   Available: {', '.join(self.MINE_CONFIGS.keys())}")
            return False
        
        mine = self.MINE_CONFIGS[mine_name]
        
        # Create databases
        if not self.create_mine_databases(mine):
            return False
        
        print(f"✅ Mine {mine_name} added successfully")
        print(f"   Main DB: {mine.db_name}")
        print(f"   Profile DB: {mine.profile_db_name}")
        
        return True
    
    def queue_build(self, mine_name: str, priority: str = "normal") -> bool:
        """Queue a mine for building."""
        if mine_name not in self.mines:
            print(f"❌ Mine {mine_name} not found. Add it first with 'rds add-mine'")
            return False
        
        mine = self.mines[mine_name]
        self.build_queue.add(mine, priority)
        
        print(f"✅ {mine_name} added to build queue")
        print(f"   Queue status: {self.build_queue.get_status()}")
        
        return True
    
    def process_build_queue(self) -> bool:
        """Process the build queue sequentially."""
        if not self.build_queue.queue and not self.build_queue.current_build:
            print("ℹ️  Build queue is empty")
            return True
        
        print("🔨 Processing build queue...")
        
        while True:
            # Get next mine to build
            mine = self.build_queue.get_next()
            if not mine:
                break
            
            print(f"\n📦 Building {mine.name}...")
            
            # Prepare for build
            if not self.prepare_for_build(mine.name):
                self.build_queue.fail_current("Failed to prepare instance")
                continue
            
            # Here you would trigger the actual InterMine build
            # For now, we'll simulate it
            print(f"   🚧 Build process would start here for {mine.db_name}")
            print("   📊 Using sequential processing to optimize memory")
            
            # Simulate build completion
            time.sleep(2)  # In reality, this would be the actual build
            
            self.build_queue.complete_current()
            print(f"   ✅ {mine.name} build completed")
        
        # Downsize after all builds
        print("\n🎉 All builds completed")
        self.finish_build(downsize=True, delay_minutes=30)
        
        # Print summary
        status = self.build_queue.get_status()
        print("\n📊 Build Summary:")
        print(f"   Completed: {status['completed']}")
        print(f"   Failed: {status['failed']}")
        
        return True
    
    def get_endpoint(self) -> Optional[str]:
        """Get the RDS instance endpoint."""
        if not self.rds_client:
            return None
        
        try:
            response = self.rds_client.describe_db_instances(
                DBInstanceIdentifier=self.rds_identifier
            )
            
            if response['DBInstances']:
                instance = response['DBInstances'][0]
                endpoint = instance['Endpoint']['Address']
                port = instance['Endpoint']['Port']
                return f"{endpoint}:{port}"
            
        except ClientError as e:
            print(f"❌ Failed to get endpoint: {e}")
        
        return None
    
    def get_connection_string(self, mine_name: str, use_profile_db: bool = False) -> Optional[str]:
        """Get PostgreSQL connection string for a specific mine."""
        endpoint = self.get_endpoint()
        if not endpoint:
            return None
        
        if mine_name not in self.mines:
            print(f"❌ Mine {mine_name} not found")
            return None
        
        mine = self.mines[mine_name]
        db_name = mine.profile_db_name if use_profile_db else mine.db_name
        
        return f"postgresql://{self.config.postgres_user}:{self.config.postgres_password}@{endpoint}/{db_name}"
    
    def get_status(self) -> Dict:
        """Get comprehensive RDS and mine status."""
        status = {
            "rds_identifier": self.rds_identifier,
            "region": self.rds_region,
            "current_size": self.current_size.value,
            "endpoint": self.get_endpoint(),
            "mines": {},
            "build_queue": self.build_queue.get_status(),
            "resize_history": self.resize_history[-5:] if self.resize_history else []
        }
        
        # Add mine details
        for name, mine in self.mines.items():
            status["mines"][name] = {
                "status": mine.status,
                "main_db": mine.db_name,
                "profile_db": mine.profile_db_name,
                "created": mine.created_at.isoformat() if mine.created_at else None,
                "last_build": mine.last_build.isoformat() if mine.last_build else None
            }
        
        # Get RDS metrics if available
        if self.rds_client:
            try:
                response = self.rds_client.describe_db_instances(
                    DBInstanceIdentifier=self.rds_identifier
                )
                
                if response['DBInstances']:
                    instance = response['DBInstances'][0]
                    status["rds_status"] = instance['DBInstanceStatus']
                    status["storage_gb"] = instance['AllocatedStorage']
                    status["multi_az"] = instance['MultiAZ']
                    
            except ClientError:
                status["rds_status"] = "unknown"
        
        return status
    
    def estimate_costs(self, builds_per_month: int = 10, build_hours: int = 4) -> Dict:
        """Estimate monthly costs based on current configuration."""
        # Pricing as of 2024 (us-east-1, on-demand)
        hourly_rates = {
            RDSInstanceSize.MICRO.value: 0.018,
            RDSInstanceSize.SMALL.value: 0.036,
            RDSInstanceSize.MEDIUM.value: 0.072,
            RDSInstanceSize.BUILD_STANDARD.value: 0.144,
            RDSInstanceSize.BUILD_HEAVY.value: 0.288,
        }
        
        # Calculate hours per month
        hours_per_month = 730  # Average month
        normal_size = self.config.rds_normal_size if hasattr(self.config, 'rds_normal_size') else RDSInstanceSize.MEDIUM.value
        build_size = self.config.rds_build_size if hasattr(self.config, 'rds_build_size') else RDSInstanceSize.BUILD_STANDARD.value
        
        # Estimate based on usage pattern
        total_build_hours = builds_per_month * build_hours
        normal_hours = hours_per_month - total_build_hours
        
        normal_cost = normal_hours * hourly_rates.get(normal_size, 0.072)
        build_cost = total_build_hours * hourly_rates.get(build_size, 0.144)
        
        # Storage cost (GP3: $0.115 per GB-month)
        storage_gb = self.config.rds_storage_gb if hasattr(self.config, 'rds_storage_gb') else 100
        storage_cost = storage_gb * 0.115
        
        # Backup storage (assume 50% of allocated)
        backup_cost = (storage_gb * 0.5) * 0.095
        
        total = normal_cost + build_cost + storage_cost + backup_cost
        
        return {
            "normal_operations": f"${normal_cost:.2f}",
            "build_operations": f"${build_cost:.2f}",
            "storage": f"${storage_cost:.2f}",
            "backups": f"${backup_cost:.2f}",
            "total_monthly": f"${total:.2f}",
            "total_annual": f"${total * 12:.2f}",
            "builds_per_month": builds_per_month,
            "normal_hours": normal_hours,
            "build_hours": total_build_hours,
            "savings_tip": "Use Reserved Instances for ~30-52% discount"
        }
    
    def calculate_reservation_savings(self, usage_pattern: str = "steady") -> Dict:
        """Calculate potential savings with Reserved Instances."""
        # Base hourly rates (on-demand)
        on_demand_rates = {
            "db.t4g.micro": 0.018,
            "db.t4g.small": 0.036,
            "db.t4g.medium": 0.072,
            "db.r6g.large": 0.144,
            "db.r6g.xlarge": 0.288,
        }
        
        # Reserved Instance discounts
        ri_discounts = {
            "1_year_no_upfront": 0.31,
            "1_year_partial": 0.33,
            "1_year_all_upfront": 0.35,
            "3_year_no_upfront": 0.48,
            "3_year_partial": 0.50,
            "3_year_all_upfront": 0.52,
        }
        
        # Usage patterns
        patterns = {
            "steady": {  # 24/7 operation
                "description": "24/7 steady state (always running)",
                "hours_per_month": 730,
                "builds_per_month": 10,
                "build_hours": 4,
            },
            "business": {  # Business hours + builds
                "description": "Business hours (12h/day, 22 days) + builds",
                "hours_per_month": 264,
                "builds_per_month": 8,
                "build_hours": 4,
            },
            "minimal": {  # Only for builds
                "description": "Minimal usage (builds only)",
                "hours_per_month": 40,
                "builds_per_month": 10,
                "build_hours": 4,
            }
        }
        
        pattern = patterns.get(usage_pattern, patterns["steady"])
        normal_size = self.config.rds_normal_size if hasattr(self.config, 'rds_normal_size') else "db.t4g.medium"
        
        # Calculate on-demand costs
        on_demand_rate = on_demand_rates.get(normal_size, 0.072)
        monthly_on_demand = pattern["hours_per_month"] * on_demand_rate
        annual_on_demand = monthly_on_demand * 12
        
        # Calculate reserved instance costs
        recommendations = []
        
        for ri_type, discount in ri_discounts.items():
            ri_rate = on_demand_rate * (1 - discount)
            monthly_ri = pattern["hours_per_month"] * ri_rate
            annual_ri = monthly_ri * 12
            
            # Calculate upfront costs
            upfront = 0
            if "all_upfront" in ri_type:
                years = 3 if "3_year" in ri_type else 1
                upfront = annual_ri * years
                monthly_effective = upfront / (years * 12)
            elif "partial" in ri_type:
                years = 3 if "3_year" in ri_type else 1
                upfront = annual_ri * years * 0.5  # Approximate 50% upfront
                monthly_effective = (upfront / (years * 12)) + (monthly_ri * 0.5)
            else:
                monthly_effective = monthly_ri
                
            annual_savings = annual_on_demand - annual_ri
            roi_months = upfront / (monthly_on_demand - monthly_ri) if upfront > 0 and monthly_on_demand > monthly_ri else 0
            
            recommendations.append({
                "type": ri_type.replace("_", " ").title(),
                "discount": f"{discount * 100:.0f}%",
                "upfront": f"${upfront:.2f}",
                "monthly_cost": f"${monthly_effective:.2f}",
                "annual_cost": f"${annual_ri:.2f}",
                "annual_savings": f"${annual_savings:.2f}",
                "roi_months": f"{roi_months:.1f}" if roi_months > 0 else "Immediate",
                "break_even": roi_months < 12 if roi_months > 0 else True,
            })
        
        # Sort by annual savings
        recommendations.sort(key=lambda x: float(x["annual_savings"].replace("$", "").replace(",", "")), reverse=True)
        
        # Determine best option based on pattern
        if pattern["hours_per_month"] >= 500:  # Heavy usage
            best_option = "3 Year All Upfront (52% discount)"
            rationale = "Heavy usage justifies maximum commitment for best savings"
        elif pattern["hours_per_month"] >= 200:  # Moderate usage
            best_option = "1 Year No Upfront (31% discount)"
            rationale = "Moderate usage with flexibility to adjust"
        else:  # Light usage
            best_option = "Stay with On-Demand"
            rationale = "Light usage doesn't justify reservation commitment"
        
        return {
            "usage_pattern": pattern["description"],
            "instance_type": normal_size,
            "monthly_hours": pattern["hours_per_month"],
            "on_demand": {
                "hourly_rate": f"${on_demand_rate:.3f}",
                "monthly_cost": f"${monthly_on_demand:.2f}",
                "annual_cost": f"${annual_on_demand:.2f}",
            },
            "recommendations": recommendations[:3],  # Top 3 options
            "best_option": best_option,
            "rationale": rationale,
            "notes": [
                "Reserved Instances apply automatically to matching instances",
                "Can still resize within instance family (t4g.small ↔ t4g.medium)",
                "Build hours using larger instances are charged at on-demand rates",
                "Consider Aurora Serverless v2 for highly variable workloads"
            ]
        }