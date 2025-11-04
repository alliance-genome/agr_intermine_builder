#!/usr/bin/env python3
"""
CLI for managing RDS instance for InterMine

Provides command-line interface for provisioning and managing the shared
RDS PostgreSQL instance for all InterMine mines.

Usage:
    # Create RDS instance (recommended settings)
    python -m src.cli.rds_manager create

    # Create with custom settings
    python -m src.cli.rds_manager create \
        --instance-type db.t3.large \
        --storage 200 \
        --region us-east-1

    # Check status
    python -m src.cli.rds_manager status

    # Delete instance (careful!)
    python -m src.cli.rds_manager delete --instance-id intermine-postgres
"""

import argparse
import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.intermine_builder.rds_provisioner import RDSProvisioner, RDSProvisionerError

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False):
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def cmd_create(args):
    """Create RDS instance for all InterMines."""
    print("\n🚀 Creating RDS PostgreSQL Instance for InterMine")
    print("="*60)

    provisioner = RDSProvisioner(
        region=args.region,
        profile_name=args.profile
    )

    try:
        result = provisioner.provision_complete_setup(
            instance_identifier=args.instance_id,
            instance_class=args.instance_type,
            allocated_storage=args.storage,
            master_password=args.password,
            vpc_id=args.vpc_id,
            create_databases_now=not args.skip_databases
        )

        print("\n✅ SUCCESS! RDS instance created and ready to use.")
        print("\n📋 Connection Details:")
        print(f"   Endpoint: {result['endpoint']}:{result['port']}")
        print(f"   Username: {result['username']}")
        print(f"   Password: {result['password']}")
        print(f"   Region: {result['region']}")

        if not args.skip_databases:
            print("\n📊 Databases Created:")
            print("   - alliancemine_db")
            print("   - alliancemine_profiles_db")
            print("   - wormmine_db")
            print("   - wormmine_profiles_db")
            print("   - mousemine_db")
            print("   - mousemine_profiles_db")
            print("   - flymine_db")
            print("   - flymine_profiles_db")

        print("\n💾 Save these credentials to your .env file:")
        print(f"RDS_HOST={result['endpoint']}")
        print(f"RDS_PORT={result['port']}")
        print(f"RDS_USER={result['username']}")
        print(f"RDS_PASSWORD={result['password']}")

        print("\n⏭️  Next Steps:")
        print("   1. Save credentials to .env file")
        print("   2. Test connection: psql -h <endpoint> -U postgres -d postgres")
        print("   3. Start building mines: python -m src.cli.build_mines build --mine alliancemine")

        return 0

    except RDSProvisionerError as e:
        print(f"\n❌ ERROR: {e}")
        return 1
    except Exception as e:
        logger.exception("Unexpected error during RDS creation")
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        return 1


def cmd_status(args):
    """Check RDS instance status."""
    provisioner = RDSProvisioner(
        region=args.region,
        profile_name=args.profile
    )

    try:
        import boto3
        rds = boto3.client('rds', region_name=args.region)

        response = rds.describe_db_instances(
            DBInstanceIdentifier=args.instance_id
        )

        instance = response['DBInstances'][0]

        print(f"\n📊 RDS Instance Status: {args.instance_id}")
        print("="*60)
        print(f"Status: {instance['DBInstanceStatus']}")
        print(f"Endpoint: {instance.get('Endpoint', {}).get('Address', 'N/A')}")
        print(f"Port: {instance.get('Endpoint', {}).get('Port', 'N/A')}")
        print(f"Engine: {instance['Engine']} {instance['EngineVersion']}")
        print(f"Instance Class: {instance['DBInstanceClass']}")
        print(f"Storage: {instance['AllocatedStorage']}GB {instance['StorageType']}")
        print(f"Multi-AZ: {instance['MultiAZ']}")
        print(f"Publicly Accessible: {instance['PubliclyAccessible']}")
        print(f"Backup Retention: {instance['BackupRetentionPeriod']} days")
        print("="*60)

        return 0

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        return 1


def cmd_delete(args):
    """Delete RDS instance."""
    if not args.confirm:
        print("⚠️  WARNING: This will delete the RDS instance and ALL data!")
        print(f"   Instance: {args.instance_id}")
        print(f"   Region: {args.region}")
        confirm = input("\nType 'DELETE' to confirm: ")
        if confirm != 'DELETE':
            print("❌ Deletion cancelled")
            return 0

    try:
        import boto3
        rds = boto3.client('rds', region_name=args.region)

        print(f"\n🗑️  Deleting RDS instance: {args.instance_id}")

        rds.delete_db_instance(
            DBInstanceIdentifier=args.instance_id,
            SkipFinalSnapshot=args.skip_snapshot,
            FinalDBSnapshotIdentifier=f"{args.instance_id}-final-snapshot" if not args.skip_snapshot else None
        )

        print("✅ Deletion initiated")
        if not args.skip_snapshot:
            print(f"   Final snapshot: {args.instance_id}-final-snapshot")

        return 0

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        return 1


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Manage RDS PostgreSQL instance for InterMine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create RDS instance with recommended settings
  %(prog)s create

  # Create with custom instance type
  %(prog)s create --instance-type db.t3.medium --storage 100

  # Create in specific region
  %(prog)s create --region us-west-2

  # Check status
  %(prog)s status

  # Delete instance
  %(prog)s delete
        """
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output'
    )

    parser.add_argument(
        '--region',
        default='us-east-1',
        help='AWS region (default: us-east-1)'
    )

    parser.add_argument(
        '--profile',
        help='AWS profile name (optional)'
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # Create command
    create_parser = subparsers.add_parser('create', help='Create RDS instance')
    create_parser.add_argument(
        '--instance-id',
        default='intermine-postgres',
        help='DB instance identifier (default: intermine-postgres)'
    )
    create_parser.add_argument(
        '--instance-type',
        default='db.t3.large',
        choices=['db.t3.micro', 'db.t3.small', 'db.t3.medium', 'db.t3.large', 'db.t3.xlarge', 'db.t3.2xlarge'],
        help='Instance type (default: db.t3.large - Intel x86, RECOMMENDED)'
    )
    create_parser.add_argument(
        '--storage',
        type=int,
        default=200,
        help='Storage size in GB (default: 200)'
    )
    create_parser.add_argument(
        '--password',
        help='Master password (generated if not provided)'
    )
    create_parser.add_argument(
        '--vpc-id',
        help='VPC ID (uses default VPC if not provided)'
    )
    create_parser.add_argument(
        '--skip-databases',
        action='store_true',
        help='Skip automatic database creation'
    )
    create_parser.set_defaults(func=cmd_create)

    # Status command
    status_parser = subparsers.add_parser('status', help='Check RDS instance status')
    status_parser.add_argument(
        '--instance-id',
        default='intermine-postgres',
        help='DB instance identifier (default: intermine-postgres)'
    )
    status_parser.set_defaults(func=cmd_status)

    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete RDS instance')
    delete_parser.add_argument(
        '--instance-id',
        default='intermine-postgres',
        help='DB instance identifier (default: intermine-postgres)'
    )
    delete_parser.add_argument(
        '--skip-snapshot',
        action='store_true',
        help='Skip final snapshot (data will be lost!)'
    )
    delete_parser.add_argument(
        '--confirm',
        action='store_true',
        help='Skip confirmation prompt'
    )
    delete_parser.set_defaults(func=cmd_delete)

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Setup logging
    setup_logging(args.verbose)

    # Execute command
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
