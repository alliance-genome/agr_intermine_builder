#!/usr/bin/env python3
"""
CLI for building InterMines

Provides command-line interface for building and managing InterMine instances.

Usage:
    # Build single mine
    python -m src.cli.build_mines build --mine alliancemine

    # Build all mines
    python -m src.cli.build_mines build-all

    # Build specific stage
    python -m src.cli.build_mines stage --mine wormmine --stage buildDB

    # Check status
    python -m src.cli.build_mines status --mine alliancemine

    # Cleanup
    python -m src.cli.build_mines cleanup --mine wormmine
"""

import argparse
import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.intermine_builder.mine_builder import MineBuilder
from src.intermine_builder.mine_config import MineType, BuildStage, list_available_mines
from src.intermine_builder.config import Config

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False):
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def cmd_build(args):
    """Build a single mine."""
    mine_type = MineType(args.mine)

    # Load configuration
    config = Config.from_env()

    with MineBuilder(config, log_level="DEBUG" if args.verbose else "INFO") as builder:
        try:
            summary = builder.build_mine(
                mine_type,
                force_rebuild_image=args.rebuild,
                skip_stages=[BuildStage(s) for s in args.skip_stages] if args.skip_stages else None
            )

            if summary["success"]:
                print(f"\n✅ Successfully built {summary['display_name']}")
                print(f"   Total time: {summary['total_duration_hours']:.2f} hours")
                return 0
            else:
                print(f"\n❌ Failed to build {summary['display_name']}")
                return 1

        except Exception as e:
            logger.error(f"Build failed: {e}")
            return 1


def cmd_build_all(args):
    """Build all mines."""
    config = Config.from_env()

    with MineBuilder(config, log_level="DEBUG" if args.verbose else "INFO") as builder:
        try:
            summaries = builder.build_all_mines(
                force_rebuild_images=args.rebuild,
                stop_on_failure=not args.continue_on_error
            )

            # Print summary
            success_count = sum(1 for s in summaries if s.get("success", False))
            total_count = len(summaries)

            print(f"\n{'='*60}")
            print(f"Built {success_count}/{total_count} mines successfully")
            print(f"{'='*60}")

            return 0 if success_count == total_count else 1

        except Exception as e:
            logger.error(f"Build failed: {e}")
            return 1


def cmd_stage(args):
    """Execute a single build stage."""
    mine_type = MineType(args.mine)
    stage = BuildStage(args.stage)

    config = Config.from_env()

    with MineBuilder(config, log_level="DEBUG" if args.verbose else "INFO") as builder:
        try:
            builder.execute_stage(mine_type, stage)
            print(f"\n✅ Successfully executed {stage.value} for {mine_type.value}")
            return 0

        except Exception as e:
            logger.error(f"Stage execution failed: {e}")
            return 1


def cmd_status(args):
    """Get status of a mine."""
    mine_type = MineType(args.mine)

    config = Config.from_env()

    with MineBuilder(config) as builder:
        status = builder.get_mine_status(mine_type)

        print(f"\nStatus for {mine_type.value}:")
        print(f"  Container: {status['container_status']}")
        print(f"  Building: {status['is_building']}")

        if status['is_building']:
            print(f"  Current stage: {status.get('current_stage', 'unknown')}")

    return 0


def cmd_cleanup(args):
    """Cleanup mine resources."""
    config = Config.from_env()

    with MineBuilder(config) as builder:
        if args.mine:
            mine_type = MineType(args.mine)
            builder.cleanup(mine_type)
            print(f"✅ Cleaned up {mine_type.value}")
        else:
            builder.cleanup()
            print("✅ Cleaned up all mines")

    return 0


def cmd_list(args):
    """List available mines."""
    print("\nAvailable mines:")
    for mine in list_available_mines():
        print(f"  - {mine}")
    print()
    return 0


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Build and manage InterMine instances",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Build AllianceMine
  %(prog)s build --mine alliancemine

  # Build all mines
  %(prog)s build-all

  # Build with image rebuild
  %(prog)s build --mine wormmine --rebuild

  # Execute single stage
  %(prog)s stage --mine alliancemine --stage buildDB

  # Check status
  %(prog)s status --mine wormmine

  # Cleanup
  %(prog)s cleanup --mine alliancemine
        """
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output'
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # Build command
    build_parser = subparsers.add_parser('build', help='Build a single mine')
    build_parser.add_argument(
        '--mine',
        required=True,
        choices=list_available_mines(),
        help='Mine to build'
    )
    build_parser.add_argument(
        '--rebuild',
        action='store_true',
        help='Force rebuild of Docker image'
    )
    build_parser.add_argument(
        '--skip-stages',
        nargs='+',
        choices=[s.value for s in BuildStage],
        help='Stages to skip'
    )
    build_parser.set_defaults(func=cmd_build)

    # Build all command
    build_all_parser = subparsers.add_parser('build-all', help='Build all mines')
    build_all_parser.add_argument(
        '--rebuild',
        action='store_true',
        help='Force rebuild of Docker images'
    )
    build_all_parser.add_argument(
        '--continue-on-error',
        action='store_true',
        help='Continue building other mines if one fails'
    )
    build_all_parser.set_defaults(func=cmd_build_all)

    # Stage command
    stage_parser = subparsers.add_parser('stage', help='Execute a single build stage')
    stage_parser.add_argument(
        '--mine',
        required=True,
        choices=list_available_mines(),
        help='Mine to build'
    )
    stage_parser.add_argument(
        '--stage',
        required=True,
        choices=[s.value for s in BuildStage],
        help='Stage to execute'
    )
    stage_parser.set_defaults(func=cmd_stage)

    # Status command
    status_parser = subparsers.add_parser('status', help='Get mine status')
    status_parser.add_argument(
        '--mine',
        required=True,
        choices=list_available_mines(),
        help='Mine to check'
    )
    status_parser.set_defaults(func=cmd_status)

    # Cleanup command
    cleanup_parser = subparsers.add_parser('cleanup', help='Cleanup mine resources')
    cleanup_parser.add_argument(
        '--mine',
        choices=list_available_mines(),
        help='Mine to cleanup (omit for all)'
    )
    cleanup_parser.set_defaults(func=cmd_cleanup)

    # List command
    list_parser = subparsers.add_parser('list', help='List available mines')
    list_parser.set_defaults(func=cmd_list)

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
