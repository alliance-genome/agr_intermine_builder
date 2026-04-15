#!/usr/bin/env python3
"""
InterMine Sequential Integration Script

Parses project.xml and runs each data source integration sequentially.
Skips commented-out sources and provides detailed progress tracking.
Automatically resumes from last successful step if interrupted.

Usage:
    python3 integrate_all.py [--reset] [--skip SOURCE1,SOURCE2,...]

    --reset: Start from beginning, ignoring saved progress
    --skip: Skip specific sources (comma-separated)
"""

import argparse
import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path


# Progress file location
PROGRESS_FILE = Path('/opt/intermine/logs/integration_progress.json')


def parse_sources(project_xml_path):
    """Parse project.xml and extract source names (skip commented sources)"""
    try:
        tree = ET.parse(project_xml_path)
        root = tree.getroot()

        sources = []
        sources_elem = root.find('sources')
        if sources_elem is None:
            print("❌ No <sources> element found in project.xml")
            sys.exit(1)

        for source in sources_elem.findall('source'):
            source_name = source.get('name')
            source_type = source.get('type')
            if source_name:
                sources.append({
                    'name': source_name,
                    'type': source_type
                })

        print(f"📋 Found {len(sources)} sources in project.xml\n")
        return sources

    except ET.ParseError as e:
        print(f"❌ Failed to parse project.xml: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print(f"❌ project.xml not found at {project_xml_path}")
        sys.exit(1)


def load_progress():
    """Load progress from file"""
    if not PROGRESS_FILE.exists():
        return {'completed': [], 'failed': [], 'last_run': None}

    try:
        with open(PROGRESS_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {'completed': [], 'failed': [], 'last_run': None}


def save_progress(progress):
    """Save progress to file"""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    progress['last_run'] = datetime.now().isoformat()

    try:
        with open(PROGRESS_FILE, 'w') as f:
            json.dump(progress, f, indent=2)
    except IOError as e:
        print(f"⚠️  Warning: Could not save progress: {e}")


def reset_progress():
    """Reset progress file"""
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()
        print("🔄 Progress reset\n")


def format_duration(seconds):
    """Format duration in human-readable format"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def run_integration(source_name, gradle_dir):
    """Run Gradle integration for a single source"""
    cmd = [
        './gradlew',
        'integrate',
        f'-Psource={source_name}',
        '--stacktrace'
    ]

    print(f"\n{'='*80}")
    print(f"🔄 Integrating: {source_name}")
    print(f"{'='*80}")
    print(f"Command: {' '.join(cmd)}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*80}\n")

    start_time = time.time()

    try:
        subprocess.run(
            cmd,
            cwd=gradle_dir,
            check=True,
            text=True
        )

        elapsed = time.time() - start_time
        print(f"\n{'='*80}")
        print(f"✅ SUCCESS: {source_name}")
        print(f"Duration: {format_duration(elapsed)}")
        print(f"{'='*80}\n")

        return True

    except subprocess.CalledProcessError as e:
        elapsed = time.time() - start_time
        print(f"\n{'='*80}")
        print(f"❌ FAILED: {source_name}")
        print(f"Duration: {format_duration(elapsed)}")
        print(f"Exit code: {e.returncode}")
        print(f"{'='*80}\n")

        return False


def main():
    parser = argparse.ArgumentParser(
        description='Run InterMine data source integrations sequentially with progress tracking',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--reset',
        action='store_true',
        help='Reset progress and start from beginning'
    )

    parser.add_argument(
        '--skip',
        metavar='SOURCE1,SOURCE2,...',
        help='Skip specific sources (comma-separated)'
    )

    parser.add_argument(
        '--project-xml',
        default='/opt/intermine/alliancemine/project.xml',
        help='Path to project.xml (default: /opt/intermine/alliancemine/project.xml)'
    )

    parser.add_argument(
        '--gradle-dir',
        default='/opt/intermine/alliancemine',
        help='Path to Gradle project directory (default: /opt/intermine/alliancemine)'
    )

    args = parser.parse_args()

    # Reset progress if requested
    if args.reset:
        reset_progress()

    # Load existing progress
    progress = load_progress()

    # Parse sources from project.xml
    all_sources = parse_sources(args.project_xml)

    # Determine skip list
    skip_list = []
    if args.skip:
        skip_list = [s.strip() for s in args.skip.split(',')]
        print(f"⏭️  Skipping sources: {', '.join(skip_list)}\n")

    # Filter sources based on progress and skip list
    sources_to_run = []
    for source in all_sources:
        source_name = source['name']

        # Skip if in skip list
        if source_name in skip_list:
            continue

        # Skip if already completed
        if source_name in progress['completed']:
            continue

        sources_to_run.append(source)

    # Show progress summary
    if progress['completed']:
        print(f"📊 Previous Progress:")
        print(f"   ✅ Completed: {len(progress['completed'])} sources")
        print(f"   Last run: {progress.get('last_run', 'Unknown')}\n")
        print(f"   Already completed:")
        for src in progress['completed']:
            print(f"      - {src}")
        print()

    if not sources_to_run:
        print("✅ All sources already integrated!")
        print("\nUse --reset to start over")
        return

    total = len(sources_to_run)
    start_time = time.time()

    print(f"{'='*80}")
    print(f"🚀 Starting Integration")
    print(f"{'='*80}")
    print(f"Total sources: {len(all_sources)}")
    print(f"Already completed: {len(progress['completed'])}")
    print(f"To integrate: {total}")
    print(f"{'='*80}\n")

    successful = []
    failed = []

    for i, source in enumerate(sources_to_run, 1):
        source_name = source['name']
        print(f"\n[{i}/{total}] Processing: {source_name}")

        success = run_integration(source_name, args.gradle_dir)

        if success:
            successful.append(source_name)
            progress['completed'].append(source_name)
            # Remove from failed if it was there
            if source_name in progress['failed']:
                progress['failed'].remove(source_name)
            save_progress(progress)
        else:
            failed.append(source_name)
            if source_name not in progress['failed']:
                progress['failed'].append(source_name)
            save_progress(progress)

            print(f"\n⚠️  Integration failed for: {source_name}")
            print(f"Progress saved. Run again to resume from next source.")
            print(f"Or use --skip {source_name} to skip this source and continue.")
            break

    # Print summary
    total_time = time.time() - start_time
    print(f"\n{'='*80}")
    print(f"📊 INTEGRATION SUMMARY")
    print(f"{'='*80}")
    print(f"✅ Successful: {len(successful)}")
    print(f"❌ Failed:     {len(failed)}")
    print(f"📝 Total completed: {len(progress['completed'])}")
    print(f"⏱️  Session time: {format_duration(total_time)}")
    print(f"{'='*80}\n")

    if successful:
        print("✅ Successful in this run:")
        for source in successful:
            print(f"  - {source}")
        print()

    if failed:
        print("❌ Failed in this run:")
        for source in failed:
            print(f"  - {source}")
        print()

    if progress['completed']:
        print(f"📝 All completed sources ({len(progress['completed'])}):")
        for source in progress['completed']:
            print(f"  - {source}")
        print()

    if failed:
        print(f"\n💡 To resume: python3 {sys.argv[0]}")
        print(f"💡 To skip failed source: python3 {sys.argv[0]} --skip {','.join(failed)}")
        print(f"💡 To start over: python3 {sys.argv[0]} --reset")
    elif len(progress['completed']) == len(all_sources):
        print("🎉 All sources integrated successfully!")

    sys.exit(0 if not failed else 1)


if __name__ == '__main__':
    main()
