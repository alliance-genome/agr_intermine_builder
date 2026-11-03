"""Select a mine and delegate to Compose or its existing build script."""

from __future__ import annotations

import argparse
import os
import shlex
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType

MINES = ("alliancemine", "flymine", "mousemine", "wormmine", "yeastmine")
ACTIONS = ("image", "build", "run", "shell", "status", "logs", "compose")
PROJECT = Path(__file__).resolve().parents[2]


def build_command(
    mine: str, directory: Path, arguments: list[str], compose: list[str], env: dict[str, str]
) -> list[str]:
    """Use an existing pipeline; no common stage sequence is imposed on mines."""
    if mine == "alliancemine":
        return [*compose, "run", "--rm", "-T", "alliancemine-builder", "build", *arguments]
    if mine == "flymine":
        if arguments:
            raise ValueError("FlyMine build takes no arguments; use RESUME_AT in the environment.")
        env["FLYMINE_DIR"] = str(directory)
        script = directory / "scripts/build_release.sh"
        command = ["bash", str(script)]
    elif mine == "yeastmine":
        if arguments not in ([], ["--no-publish"]):
            raise ValueError("YeastMine build uses --no-publish; use RESUME_RC to resume.")
        env["YM_DIR"] = str(directory)
        script = directory / "weekly/weekly_build.sh"
        command = ["bash", str(script), "--no-publish"]
    else:
        raise ValueError(f"{mine} has no full build script; use '{mine} run COMMAND [ARGS...]'.")
    if not script.is_file():
        raise ValueError(f"Build script missing: {script}. Select its directory with --directory.")
    return command


def select_command(args: argparse.Namespace, directory: Path, env: dict[str, str]) -> list[str]:
    arguments = args.arguments
    if args.action == "logs":
        return ["tail", "-n", "100", *arguments, str(directory / "logs/commands.log")]
    compose_file = directory / "docker-compose.yml"
    if not compose_file.is_file():
        raise ValueError(f"Missing {compose_file}. Use --directory to select a mine directory.")
    compose = ["docker", "compose", "--project-directory", str(directory), "-f", str(compose_file)]
    service = f"{args.mine}-builder"
    if args.action == "build":
        return build_command(args.mine, directory, arguments, compose, env)
    if args.action in ("run", "compose") and not arguments:
        raise ValueError(f"{args.action} requires a command.")
    commands = {
        "image": [*compose, "build", *arguments, service],
        "run": [*compose, "run", "--rm", "-T", service, *arguments],
        "shell": [*compose, "run", "--rm", service, "bash", *arguments],
        "status": [*compose, "ps", "--all", *arguments],
        "compose": [*compose, *arguments],
    }
    return commands[args.action]


def wait_for_command(command: list[str], env: dict[str, str]) -> int:
    with subprocess.Popen(command, env=env, start_new_session=True) as process:

        def forward(number: int, _frame: FrameType | None) -> None:
            try:
                os.killpg(process.pid, number)
            except ProcessLookupError:
                # The command can finish between signal arrival and delivery.
                return

        previous = {
            number: signal.signal(number, forward)
            for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
        }
        try:
            status = process.wait()
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)
    return status if status >= 0 else 128 - status


def execute(
    command: list[str], args: argparse.Namespace, directory: Path, env: dict[str, str]
) -> int:
    os.chdir(directory)
    if args.action in ("image", "build", "run"):
        log = directory / "logs/commands.log"
        log.parent.mkdir(exist_ok=True)
        with log.open("a", encoding="utf-8") as output:
            output.write(
                f"\n[{datetime.now(timezone.utc).isoformat()}] {args.mine} {args.action}\n"
            )
        env["MINE_LOG_FILE"] = str(log)
        print(f"Log: {log}", file=sys.stderr, flush=True)
        command = [
            "bash",
            "-o",
            "pipefail",
            "-c",
            '"$@" 2>&1 | tee -a "$MINE_LOG_FILE"',
            "mine",
            *command,
        ]
        return wait_for_command(command, env)
    os.execvpe(command[0], command, env)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run existing InterMine builds through Docker Compose.",
        epilog="Arguments after ACTION are passed through. Use RC_NUMBER in the environment to pin a build.",
    )
    parser.add_argument(
        "--directory", type=Path, help="Mine directory containing docker-compose.yml"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the command without executing it"
    )
    parser.add_argument("mine", choices=("list", *MINES))
    parser.add_argument("action", nargs="?", choices=ACTIONS)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.mine == "list":
        if args.action or args.arguments:
            parser.error("list takes no action or arguments")
        print("\n".join(MINES))
        return 0
    if not args.action:
        parser.error("an action is required")
    directory = (args.directory or PROJECT / "docker" / args.mine).resolve()
    env = dict(os.environ)
    try:
        command = select_command(args, directory, env)
    except ValueError as error:
        parser.error(str(error))
    if args.dry_run:
        print(f"Directory: {directory}\n{shlex.join(command)}")
        return 0
    try:
        return execute(command, args, directory, env)
    except OSError as error:
        print(f"mine: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
