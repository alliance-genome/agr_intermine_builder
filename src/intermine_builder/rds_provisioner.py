"""
RDS Provisioner Module

Creates and manages a single RDS PostgreSQL instance for all InterMine databases.

Features:
- Creates RDS instance with optimal InterMine settings
- Configures security groups
- Sets up parameter groups for connection pooling
- Creates all mine databases and profile databases
- Outputs connection details for .env file
"""

import logging
import time
import boto3
from typing import Dict, List, Optional, Tuple
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class RDSProvisionerError(Exception):
    """Raised when RDS provisioning fails."""
    pass


class RDSProvisioner:
    """Provisions and manages RDS PostgreSQL instance for InterMine."""

    def __init__(
        self,
        region: str = "us-east-1",
        profile_name: Optional[str] = None
    ):
        """
        Initialize RDS provisioner.

        Args:
            region: AWS region
            profile_name: AWS profile name (optional)
        """
        self.region = region
        session = boto3.Session(profile_name=profile_name, region_name=region)
        self.rds_client = session.client('rds')
        self.ec2_client = session.client('ec2')

    def create_security_group(
        self,
        vpc_id: str,
        group_name: str = "intermine-rds-sg",
        description: str = "Security group for InterMine RDS instance"
    ) -> str:
        """
        Create security group for RDS instance.

        Args:
            vpc_id: VPC ID
            group_name: Security group name
            description: Security group description

        Returns:
            Security group ID
        """
        try:
            # Check if security group already exists
            response = self.ec2_client.describe_security_groups(
                Filters=[
                    {'Name': 'group-name', 'Values': [group_name]},
                    {'Name': 'vpc-id', 'Values': [vpc_id]}
                ]
            )

            if response['SecurityGroups']:
                sg_id = response['SecurityGroups'][0]['GroupId']
                logger.info(f"Security group already exists: {sg_id}")
                return sg_id

            # Create security group
            logger.info(f"Creating security group: {group_name}")
            response = self.ec2_client.create_security_group(
                GroupName=group_name,
                Description=description,
                VpcId=vpc_id
            )
            sg_id = response['GroupId']

            # Add ingress rule for PostgreSQL (port 5432)
            # Allow from anywhere (0.0.0.0/0) - adjust this for production
            self.ec2_client.authorize_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=[
                    {
                        'IpProtocol': 'tcp',
                        'FromPort': 5432,
                        'ToPort': 5432,
                        'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'PostgreSQL access'}]
                    }
                ]
            )

            logger.info(f"✅ Security group created: {sg_id}")
            return sg_id

        except ClientError as e:
            logger.error(f"Failed to create security group: {e}")
            raise RDSProvisionerError(f"Security group creation failed: {e}")

    def create_parameter_group(
        self,
        group_name: str = "intermine-postgres16",
        description: str = "Parameter group for InterMine PostgreSQL 16"
    ) -> str:
        """
        Create RDS parameter group optimized for InterMine.

        Args:
            group_name: Parameter group name
            description: Parameter group description

        Returns:
            Parameter group name
        """
        try:
            # Check if parameter group already exists
            try:
                response = self.rds_client.describe_db_parameter_groups(
                    DBParameterGroupName=group_name
                )
                logger.info(f"Parameter group already exists: {group_name}")
                return group_name
            except ClientError as e:
                if 'DBParameterGroupNotFound' not in str(e):
                    raise

            # Create parameter group
            logger.info(f"Creating parameter group: {group_name}")
            self.rds_client.create_db_parameter_group(
                DBParameterGroupName=group_name,
                DBParameterGroupFamily='postgres16',
                Description=description
            )

            # Modify parameters for InterMine workloads
            # Based on InterMine official recommendations:
            # https://intermine.readthedocs.io/en/latest/system-requirements/software/postgres/postgres/
            parameters = [
                # Connection settings - InterMine recommendation: 250 for production
                {'ParameterName': 'max_connections', 'ParameterValue': '250', 'ApplyMethod': 'pending-reboot'},

                # Memory settings - InterMine recommendations:
                # shared_buffers: 10-25% of RAM (using 25%)
                {'ParameterName': 'shared_buffers', 'ParameterValue': '{DBInstanceClassMemory/4096}', 'ApplyMethod': 'pending-reboot'},
                # effective_cache_size: 50% of RAM
                {'ParameterName': 'effective_cache_size', 'ParameterValue': '{DBInstanceClassMemory/2048}', 'ApplyMethod': 'immediate'},
                # work_mem: ~500MB but <10% of RAM (using ~512MB = 524288 KB)
                {'ParameterName': 'work_mem', 'ParameterValue': '524288', 'ApplyMethod': 'immediate'},
                # maintenance_work_mem: 5-20% of RAM (using ~1GB for 8GB instance)
                {'ParameterName': 'maintenance_work_mem', 'ParameterValue': '1048576', 'ApplyMethod': 'immediate'},

                # Statistics - InterMine recommendation: 250
                {'ParameterName': 'default_statistics_target', 'ParameterValue': '250', 'ApplyMethod': 'immediate'},

                # Performance optimizations for data warehouse workloads
                {'ParameterName': 'random_page_cost', 'ParameterValue': '1.1', 'ApplyMethod': 'immediate'},  # SSD optimization
                {'ParameterName': 'synchronous_commit', 'ParameterValue': '0', 'ApplyMethod': 'immediate'},  # InterMine recommendation

                # Checkpoint settings for write-heavy workloads
                {'ParameterName': 'checkpoint_completion_target', 'ParameterValue': '0.9', 'ApplyMethod': 'immediate'},

                # Logging - Log slow queries > 5 seconds
                {'ParameterName': 'log_min_duration_statement', 'ParameterValue': '5000', 'ApplyMethod': 'immediate'},

                # Autovacuum - critical for InterMine data loading
                {'ParameterName': 'autovacuum', 'ParameterValue': '1', 'ApplyMethod': 'immediate'},
                {'ParameterName': 'autovacuum_max_workers', 'ParameterValue': '3', 'ApplyMethod': 'pending-reboot'},
            ]

            self.rds_client.modify_db_parameter_group(
                DBParameterGroupName=group_name,
                Parameters=parameters
            )

            logger.info(f"✅ Parameter group created: {group_name}")
            return group_name

        except ClientError as e:
            logger.error(f"Failed to create parameter group: {e}")
            raise RDSProvisionerError(f"Parameter group creation failed: {e}")

    def create_rds_instance(
        self,
        instance_identifier: str = "intermine-postgres",
        instance_class: str = "db.t3.large",
        allocated_storage: int = 200,
        storage_type: str = "gp3",
        master_username: str = "postgres",
        master_password: str = None,
        postgres_version: str = "16.4",
        vpc_security_group_ids: List[str] = None,
        parameter_group_name: str = "intermine-postgres16",
        backup_retention_days: int = 7,
        multi_az: bool = False,
        publicly_accessible: bool = True,
        tags: Optional[Dict[str, str]] = None
    ) -> Dict:
        """
        Create RDS PostgreSQL instance.

        Args:
            instance_identifier: DB instance identifier
            instance_class: Instance type (db.t3.large recommended - Intel x86)
            allocated_storage: Storage in GB (200 recommended)
            storage_type: Storage type (gp3 recommended)
            master_username: Master username
            master_password: Master password (will generate if not provided)
            postgres_version: PostgreSQL version
            vpc_security_group_ids: List of security group IDs
            parameter_group_name: Parameter group name
            backup_retention_days: Backup retention period
            multi_az: Enable Multi-AZ
            publicly_accessible: Make instance publicly accessible
            tags: Resource tags

        Returns:
            Dict with instance details
        """
        try:
            # Check if instance already exists
            try:
                response = self.rds_client.describe_db_instances(
                    DBInstanceIdentifier=instance_identifier
                )
                logger.warning(f"RDS instance already exists: {instance_identifier}")
                instance = response['DBInstances'][0]
                return {
                    'instance_id': instance['DBInstanceIdentifier'],
                    'endpoint': instance.get('Endpoint', {}).get('Address'),
                    'port': instance.get('Endpoint', {}).get('Port', 5432),
                    'status': instance['DBInstanceStatus']
                }
            except ClientError as e:
                if 'DBInstanceNotFound' not in str(e):
                    raise

            # Generate password if not provided
            if not master_password:
                import secrets
                master_password = secrets.token_urlsafe(32)
                logger.info("Generated master password (save this!):")
                logger.info(f"Password: {master_password}")

            # Prepare tags
            default_tags = [
                {'Key': 'Project', 'Value': 'InterMine'},
                {'Key': 'ManagedBy', 'Value': 'intermine-builder'},
                {'Key': 'Purpose', 'Value': 'All mines shared database'}
            ]
            if tags:
                default_tags.extend([{'Key': k, 'Value': v} for k, v in tags.items()])

            # Create RDS instance
            logger.info(f"Creating RDS instance: {instance_identifier}")
            logger.info(f"  Instance class: {instance_class}")
            logger.info(f"  Storage: {allocated_storage}GB {storage_type}")
            logger.info(f"  PostgreSQL: {postgres_version}")
            logger.info(f"  Multi-AZ: {multi_az}")

            create_params = {
                'DBInstanceIdentifier': instance_identifier,
                'DBInstanceClass': instance_class,
                'Engine': 'postgres',
                'EngineVersion': postgres_version,
                'MasterUsername': master_username,
                'MasterUserPassword': master_password,
                'AllocatedStorage': allocated_storage,
                'StorageType': storage_type,
                'BackupRetentionPeriod': backup_retention_days,
                'MultiAZ': multi_az,
                'PubliclyAccessible': publicly_accessible,
                'Tags': default_tags,
                'CopyTagsToSnapshot': True,
                'EnableCloudwatchLogsExports': ['postgresql'],
                'DeletionProtection': False,  # Set to True for production
            }

            # Add optional parameters
            if vpc_security_group_ids:
                create_params['VpcSecurityGroupIds'] = vpc_security_group_ids

            if parameter_group_name:
                create_params['DBParameterGroupName'] = parameter_group_name

            # Add gp3 specific settings
            if storage_type == 'gp3':
                create_params['Iops'] = 3000  # gp3 baseline
                create_params['StorageThroughput'] = 125  # gp3 baseline MB/s

            response = self.rds_client.create_db_instance(**create_params)

            instance = response['DBInstance']
            logger.info(f"✅ RDS instance creation initiated: {instance_identifier}")
            logger.info(f"   Status: {instance['DBInstanceStatus']}")

            return {
                'instance_id': instance['DBInstanceIdentifier'],
                'status': instance['DBInstanceStatus'],
                'master_username': master_username,
                'master_password': master_password,
                'engine': instance['Engine'],
                'engine_version': instance['EngineVersion'],
                'instance_class': instance['DBInstanceClass'],
                'storage': instance['AllocatedStorage'],
                'multi_az': instance['MultiAZ']
            }

        except ClientError as e:
            logger.error(f"Failed to create RDS instance: {e}")
            raise RDSProvisionerError(f"RDS instance creation failed: {e}")

    def wait_for_instance_available(
        self,
        instance_identifier: str,
        timeout_minutes: int = 30
    ) -> str:
        """
        Wait for RDS instance to become available.

        Args:
            instance_identifier: DB instance identifier
            timeout_minutes: Maximum time to wait

        Returns:
            Instance endpoint address
        """
        logger.info(f"Waiting for RDS instance to become available (timeout: {timeout_minutes}m)...")

        start_time = time.time()
        timeout_seconds = timeout_minutes * 60

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise RDSProvisionerError(f"Timeout waiting for instance to become available")

            try:
                response = self.rds_client.describe_db_instances(
                    DBInstanceIdentifier=instance_identifier
                )
                instance = response['DBInstances'][0]
                status = instance['DBInstanceStatus']

                logger.info(f"Status: {status} ({int(elapsed/60)}m elapsed)")

                if status == 'available':
                    endpoint = instance['Endpoint']['Address']
                    port = instance['Endpoint']['Port']
                    logger.info(f"✅ RDS instance is available!")
                    logger.info(f"   Endpoint: {endpoint}:{port}")
                    return endpoint

                if status in ['failed', 'incompatible-parameters', 'incompatible-restore']:
                    raise RDSProvisionerError(f"Instance creation failed with status: {status}")

            except ClientError as e:
                logger.error(f"Error checking instance status: {e}")
                raise

            time.sleep(30)  # Check every 30 seconds

    def create_databases(
        self,
        endpoint: str,
        port: int,
        master_username: str,
        master_password: str,
        databases: List[str]
    ) -> None:
        """
        Create databases for all mines.

        Args:
            endpoint: RDS endpoint
            port: RDS port
            master_username: Master username
            master_password: Master password
            databases: List of database names to create
        """
        import psycopg2

        logger.info(f"Creating {len(databases)} databases...")

        try:
            # Connect to postgres database
            conn = psycopg2.connect(
                host=endpoint,
                port=port,
                database='postgres',
                user=master_username,
                password=master_password
            )
            conn.autocommit = True

            cursor = conn.cursor()

            for db_name in databases:
                logger.info(f"  Creating database: {db_name}")
                cursor.execute(f"CREATE DATABASE {db_name}")

            cursor.close()
            conn.close()

            logger.info(f"✅ All databases created successfully")

        except Exception as e:
            logger.error(f"Failed to create databases: {e}")
            raise RDSProvisionerError(f"Database creation failed: {e}")

    def provision_complete_setup(
        self,
        instance_identifier: str = "intermine-postgres",
        instance_class: str = "db.t4g.large",
        allocated_storage: int = 200,
        master_password: Optional[str] = None,
        vpc_id: Optional[str] = None,
        create_databases_now: bool = True
    ) -> Dict:
        """
        Complete RDS setup for all InterMine mines.

        Args:
            instance_identifier: DB instance identifier
            instance_class: Instance type
            allocated_storage: Storage in GB
            master_password: Master password (generated if not provided)
            vpc_id: VPC ID (uses default if not provided)
            create_databases_now: Create all mine databases immediately

        Returns:
            Dict with connection details and passwords
        """
        logger.info("="*60)
        logger.info("InterMine RDS Provisioning")
        logger.info("="*60)

        # Get default VPC if not provided
        if not vpc_id:
            logger.info("Getting default VPC...")
            vpcs = self.ec2_client.describe_vpcs(Filters=[{'Name': 'isDefault', 'Values': ['true']}])
            if vpcs['Vpcs']:
                vpc_id = vpcs['Vpcs'][0]['VpcId']
                logger.info(f"Using default VPC: {vpc_id}")
            else:
                raise RDSProvisionerError("No default VPC found. Please specify vpc_id.")

        # Create security group
        sg_id = self.create_security_group(vpc_id)

        # Create parameter group
        param_group = self.create_parameter_group()

        # Create RDS instance
        instance_details = self.create_rds_instance(
            instance_identifier=instance_identifier,
            instance_class=instance_class,
            allocated_storage=allocated_storage,
            master_password=master_password,
            vpc_security_group_ids=[sg_id],
            parameter_group_name=param_group
        )

        # Wait for instance to be available
        endpoint = self.wait_for_instance_available(instance_identifier)
        port = 5432

        # Create databases
        if create_databases_now:
            databases = [
                'alliancemine_db',
                'alliancemine_profiles_db',
                'wormmine_db',
                'wormmine_profiles_db',
                'mousemine_db',
                'mousemine_profiles_db',
                'flymine_db',
                'flymine_profiles_db'
            ]

            self.create_databases(
                endpoint=endpoint,
                port=port,
                master_username=instance_details['master_username'],
                master_password=instance_details['master_password'],
                databases=databases
            )

        # Summary
        result = {
            'instance_id': instance_identifier,
            'endpoint': endpoint,
            'port': port,
            'username': instance_details['master_username'],
            'password': instance_details['master_password'],
            'instance_class': instance_class,
            'storage_gb': allocated_storage,
            'postgres_version': instance_details['engine_version'],
            'security_group_id': sg_id,
            'parameter_group': param_group,
            'region': self.region
        }

        logger.info("="*60)
        logger.info("✅ RDS Provisioning Complete!")
        logger.info("="*60)
        logger.info(f"Endpoint: {endpoint}:{port}")
        logger.info(f"Username: {result['username']}")
        logger.info(f"Password: {result['password']}")
        logger.info(f"Instance: {instance_class}")
        logger.info(f"Storage: {allocated_storage}GB gp3")
        logger.info("="*60)
        logger.info("\n💾 Add to your .env file:")
        logger.info(f"RDS_HOST={endpoint}")
        logger.info(f"RDS_PORT={port}")
        logger.info(f"RDS_USER={result['username']}")
        logger.info(f"RDS_PASSWORD={result['password']}")
        logger.info("="*60)

        return result
