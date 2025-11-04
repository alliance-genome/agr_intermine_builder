#!/usr/bin/env python3
"""
Quick Start Example for InterMine Builder

This example demonstrates how to use the Python API to build mines.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.intermine_builder import MineBuilder, MineType, BuildStage
from src.intermine_builder.config import Config


def example_build_single_mine():
    """Example: Build a single mine."""
    print("Example 1: Building AllianceMine")
    print("="*60)

    # Load configuration from environment
    config = Config.from_env()

    # Create builder (using context manager for automatic cleanup)
    with MineBuilder(config, log_level="INFO") as builder:
        # Build AllianceMine
        summary = builder.build_mine(
            MineType.ALLIANCEMINE,
            force_rebuild_image=False
        )

        # Print results
        if summary["success"]:
            print(f"\n✅ Build succeeded!")
            print(f"   Total time: {summary['total_duration_hours']:.2f} hours")
            print(f"   Stages completed: {len(summary['completed_stages'])}")
        else:
            print(f"\n❌ Build failed at: {summary['failed_stage']}")


def example_build_with_skip_stages():
    """Example: Build mine but skip deployment."""
    print("\nExample 2: Building WormMine (skip deployment)")
    print("="*60)

    config = Config.from_env()

    with MineBuilder(config) as builder:
        summary = builder.build_mine(
            MineType.WORMMINE,
            skip_stages=[BuildStage.DEPLOY]
        )

        print(f"Completed in {summary['total_duration_hours']:.2f} hours")


def example_execute_single_stage():
    """Example: Execute a single build stage."""
    print("\nExample 3: Execute single stage (buildDB)")
    print("="*60)

    config = Config.from_env()

    with MineBuilder(config) as builder:
        # Execute just the buildDB stage
        builder.execute_stage(
            MineType.ALLIANCEMINE,
            BuildStage.BUILD_DB
        )

        print("✅ buildDB stage completed")


def example_build_all_mines():
    """Example: Build all mines in sequence."""
    print("\nExample 4: Building all mines")
    print("="*60)

    config = Config.from_env()

    with MineBuilder(config) as builder:
        summaries = builder.build_all_mines(
            force_rebuild_images=False,
            stop_on_failure=True
        )

        # Print summary
        total_time = sum(s['total_duration_hours'] for s in summaries)
        success_count = sum(1 for s in summaries if s['success'])

        print(f"\n{'='*60}")
        print(f"Built {success_count}/{len(summaries)} mines successfully")
        print(f"Total time: {total_time:.2f} hours")
        print(f"{'='*60}")


def example_check_status():
    """Example: Check status of a mine."""
    print("\nExample 5: Check mine status")
    print("="*60)

    config = Config.from_env()

    with MineBuilder(config) as builder:
        status = builder.get_mine_status(MineType.ALLIANCEMINE)

        print(f"Mine: {status['mine_type']}")
        print(f"Container status: {status['container_status']}")
        print(f"Currently building: {status['is_building']}")


def example_with_custom_rds():
    """Example: Build with custom RDS configuration."""
    print("\nExample 6: Build with custom RDS config")
    print("="*60)

    from src.intermine_builder.config import DatabaseConfig

    # Create custom config
    config = Config.from_env()

    # Override with custom RDS settings
    custom_rds = DatabaseConfig(
        host="my-custom-rds.amazonaws.com",
        port=5432,
        username="myuser",
        password="mypassword"
    )

    with MineBuilder(config) as builder:
        summary = builder.build_mine(
            MineType.WORMMINE,
            rds_config=custom_rds
        )

        print(f"Built with custom RDS: {custom_rds.host}")


def example_cleanup():
    """Example: Cleanup resources."""
    print("\nExample 7: Cleanup resources")
    print("="*60)

    config = Config.from_env()

    with MineBuilder(config) as builder:
        # Cleanup specific mine
        builder.cleanup(MineType.ALLIANCEMINE)
        print("✅ Cleaned up AllianceMine")

        # Cleanup all mines
        builder.cleanup()
        print("✅ Cleaned up all mines")


def main():
    """Run examples."""
    print("\n")
    print("="*60)
    print("InterMine Builder - Python API Examples")
    print("="*60)
    print("\nNote: These are example scripts. Uncomment the ones you want to run.")
    print("\n")

    # Uncomment the example you want to run:

    # example_build_single_mine()
    # example_build_with_skip_stages()
    # example_execute_single_stage()
    # example_build_all_mines()
    # example_check_status()
    # example_with_custom_rds()
    # example_cleanup()

    print("\nTo run an example, edit this file and uncomment the desired function call.")


if __name__ == "__main__":
    main()
