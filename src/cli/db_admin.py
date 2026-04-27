#!/usr/bin/env python3
"""
CLI for per-database operations on the AllianceMine RDS instance.

Where rds_manager.py operates on the RDS *instance* (create, stop, modify),
this script operates on the *databases inside* it: list, inspect, copy,
rename, drop, and bulk-clean checkpoint databases left behind by builds.

Stdlib only — shells out to the system `psql` and (for free-space) to the
AWS CLI. No pip install needed.

RDS credentials are read from environment variables:
    RDS_HOST, RDS_PORT (default 5432), RDS_USER (default postgres), RDS_PASSWORD

If those are unset, the script auto-loads `docker/alliancemine/.env`
(relative to the repo root) so it Just Works on AllianceMineDev where
that file already exists.

Examples:
    python -m src.cli.db_admin list
    python -m src.cli.db_admin list --filter 'alliancemine_9_0_%'
    python -m src.cli.db_admin show alliancemine_9_0_0_rc99
    python -m src.cli.db_admin checkpoints 9.0.0 --rc 99
    python -m src.cli.db_admin free-space
    python -m src.cli.db_admin copy alliancemine_9_0_0_rc1 alliancemine_9_0_0_rc1_backup --force
    python -m src.cli.db_admin rename alliancemine_9_0_0_rc99 alliancemine_9_0_0_rc99_keep
    python -m src.cli.db_admin delete alliancemine_9_0_0_rc99 --force --yes
    python -m src.cli.db_admin drop-checkpoints 9.0.0 --rc 1 --keep-latest
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROTECTED_DBS = {
    "postgres",
    "template0",
    "template1",
    "rdsadmin",
    "alliancemine_userprofile",
}

LOG_PATH = Path.home() / ".alliancemine-db-admin.log"

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = REPO_ROOT / "docker" / "alliancemine" / ".env"

logger = logging.getLogger("db_admin")


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def require_creds() -> None:
    if not os.environ.get("RDS_HOST"):
        load_env_file(DEFAULT_ENV_FILE)
    missing = [v for v in ("RDS_HOST", "RDS_PASSWORD") if not os.environ.get(v)]
    if missing:
        sys.exit(
            f"Missing RDS credentials: {', '.join(missing)}. "
            f"Set them in the environment or in {DEFAULT_ENV_FILE}."
        )


def _psql_base() -> list:
    return [
        "psql", "--no-psqlrc",
        "-h", os.environ["RDS_HOST"],
        "-p", os.environ.get("RDS_PORT", "5432"),
        "-U", os.environ.get("RDS_USER", "postgres"),
    ]


def psql_query(sql: str, db: str = "postgres") -> list:
    cmd = _psql_base() + ["-d", db, "-tA", "-F", "\t", "-c", sql]
    env = {**os.environ, "PGPASSWORD": os.environ.get("RDS_PASSWORD", "")}
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"psql failed: {result.stderr.strip()}")
    return [line.split("\t") for line in result.stdout.splitlines() if line.strip()]


def psql_run(sql: str, db: str = "postgres", timeout: int = 600) -> None:
    cmd = _psql_base() + ["-d", db, "-c", sql]
    env = {**os.environ, "PGPASSWORD": os.environ.get("RDS_PASSWORD", "")}
    logger.debug("Executing SQL: %s", sql)
    result = subprocess.run(cmd, env=env, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"psql failed (exit {result.returncode})")


def db_exists(name: str) -> bool:
    rows = psql_query(f"SELECT 1 FROM pg_database WHERE datname = '{_quote(name)}';")
    return bool(rows)


def kill_connections(db: str) -> int:
    sql = (
        "SELECT count(pg_terminate_backend(pid)) "
        f"FROM pg_stat_activity WHERE datname = '{_quote(db)}' AND pid <> pg_backend_pid();"
    )
    rows = psql_query(sql)
    return int(rows[0][0]) if rows else 0


def _quote(value: str) -> str:
    return value.replace("'", "''")


def _ident(value: str) -> str:
    """Validate an identifier and return it double-quoted for SQL.

    Defense in depth — psql identifier args never traverse a shell here
    (we use subprocess.run with a list), but we still reject anything
    outside [A-Za-z0-9_.\\-:] before quoting, since names like
    `alliancemine_9_0_0_rc1:fbbt` are the exact pattern we expect.
    """
    if not re.fullmatch(r"[A-Za-z0-9_.\-:]+", value):
        raise ValueError(f"Refusing identifier with unexpected characters: {value!r}")
    return '"' + value + '"'


def check_protected(db: str, override: bool) -> None:
    if db in PROTECTED_DBS and not override:
        sys.exit(
            f"Refusing to operate on protected database: {db}. "
            f"Pass --really-i-mean-it to override."
        )


def confirm(prompt: str, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        sys.exit("Refusing to run a destructive op non-interactively without --yes.")
    answer = input(f"{prompt} [y/N] ").strip().lower()
    return answer in ("y", "yes")


def log_action(action: str, details: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    with LOG_PATH.open("a") as fp:
        fp.write(f"{timestamp}\t{action}\t{json.dumps(details, sort_keys=True)}\n")


def emit(rows: list, fmt: str, columns=None) -> None:
    if not rows:
        if fmt == "json":
            print("[]")
        elif fmt == "tsv":
            pass
        else:
            print("(no rows)")
        return

    columns = columns or list(rows[0].keys())

    if fmt == "json":
        print(json.dumps(rows, indent=2))
        return

    if fmt == "tsv":
        writer = csv.DictWriter(sys.stdout, fieldnames=columns, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return

    widths = {c: max(len(c), max(len(str(r.get(c, ""))) for r in rows)) for c in columns}
    print("  ".join(c.ljust(widths[c]) for c in columns))
    print("  ".join("-" * widths[c] for c in columns))
    for row in rows:
        print("  ".join(str(row.get(c, "")).ljust(widths[c]) for c in columns))


def cmd_list(args):
    where = f"WHERE datname LIKE '{_quote(args.filter)}'" if args.filter else ""
    sql = f"""
        SELECT
            d.datname,
            pg_size_pretty(pg_database_size(d.datname)),
            pg_database_size(d.datname),
            (SELECT count(*) FROM pg_stat_activity WHERE datname = d.datname),
            r.rolname
        FROM pg_database d
        JOIN pg_roles r ON d.datdba = r.oid
        {where}
        ORDER BY pg_database_size(d.datname) DESC;
    """
    rows = [
        {"name": r[0], "size": r[1], "size_bytes": int(r[2]), "conns": int(r[3]), "owner": r[4]}
        for r in psql_query(sql)
    ]
    columns = ["name", "size", "conns", "owner"]
    if args.format == "json":
        columns = ["name", "size", "size_bytes", "conns", "owner"]
    emit(rows, args.format, columns)


def cmd_show(args):
    if not db_exists(args.db):
        sys.exit(f"Database does not exist: {args.db}")

    meta_sql = f"""
        SELECT
            pg_size_pretty(pg_database_size('{_quote(args.db)}')),
            pg_database_size('{_quote(args.db)}'),
            r.rolname,
            pg_encoding_to_char(d.encoding),
            d.datcollate,
            (SELECT count(*) FROM pg_stat_activity WHERE datname = d.datname)
        FROM pg_database d
        JOIN pg_roles r ON d.datdba = r.oid
        WHERE d.datname = '{_quote(args.db)}';
    """
    meta_row = psql_query(meta_sql)[0]
    meta = {
        "name": args.db,
        "size": meta_row[0],
        "size_bytes": int(meta_row[1]),
        "owner": meta_row[2],
        "encoding": meta_row[3],
        "collation": meta_row[4],
        "active_connections": int(meta_row[5]),
    }

    conn_sql = f"""
        SELECT pid, usename, application_name, state, query_start
        FROM pg_stat_activity
        WHERE datname = '{_quote(args.db)}' AND pid <> pg_backend_pid()
        ORDER BY query_start NULLS LAST;
    """
    conn_rows = [
        {"pid": r[0], "user": r[1], "app": r[2], "state": r[3], "query_start": r[4]}
        for r in psql_query(conn_sql)
    ]

    if args.format == "json":
        print(json.dumps({"database": meta, "connections": conn_rows}, indent=2, default=str))
        return

    print(f"Database:        {meta['name']}")
    print(f"Size:            {meta['size']} ({meta['size_bytes']:,} bytes)")
    print(f"Owner:           {meta['owner']}")
    print(f"Encoding:        {meta['encoding']}")
    print(f"Collation:       {meta['collation']}")
    print(f"Active sessions: {meta['active_connections']}")
    if conn_rows:
        print()
        print("Connections:")
        emit(conn_rows, "text", ["pid", "user", "app", "state", "query_start"])


def cmd_checkpoints(args):
    sanitized = args.release.replace(".", "_")
    if args.rc:
        prefix = f"alliancemine_{sanitized}_rc{args.rc}:"
    else:
        prefix = f"alliancemine_{sanitized}_rc%:"
    sql = f"""
        SELECT
            datname,
            pg_size_pretty(pg_database_size(datname)),
            pg_database_size(datname)
        FROM pg_database
        WHERE datname LIKE '{_quote(prefix)}%'
        ORDER BY datname;
    """
    rows = [{"name": r[0], "size": r[1], "size_bytes": int(r[2])} for r in psql_query(sql)]
    columns = ["name", "size"]
    if args.format == "json":
        columns = ["name", "size", "size_bytes"]
    emit(rows, args.format, columns)
    if rows and args.format == "text":
        total = sum(r["size_bytes"] for r in rows)
        print(f"\nTotal: {len(rows)} checkpoint(s), {total / (1024 ** 3):.1f} GB")


def cmd_free_space(args):
    instance_id = args.instance_id
    cmd = [
        "aws", "cloudwatch", "get-metric-statistics",
        "--namespace", "AWS/RDS",
        "--metric-name", "FreeStorageSpace",
        "--dimensions", f"Name=DBInstanceIdentifier,Value={instance_id}",
        "--start-time", "5 minutes ago",
        "--end-time", "now",
        "--period", "300",
        "--statistics", "Average",
        "--query", "Datapoints[0].Average",
        "--output", "text",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True).stdout.strip()
    except FileNotFoundError:
        sys.exit("aws CLI not found.")
    except subprocess.CalledProcessError as e:
        sys.exit(f"aws CloudWatch query failed: {e.stderr.strip()}")

    if not out or out == "None":
        sys.exit("No CloudWatch datapoint returned (instance idle or wrong --instance-id?)")

    bytes_free = float(out)
    gb_free = bytes_free / (1024 ** 3)
    if args.format == "json":
        print(json.dumps({"instance_id": instance_id, "free_bytes": int(bytes_free), "free_gb": round(gb_free, 2)}))
    elif args.format == "tsv":
        print("instance_id\tfree_bytes\tfree_gb")
        print(f"{instance_id}\t{int(bytes_free)}\t{gb_free:.2f}")
    else:
        print(f"{instance_id}: {gb_free:.1f} GB free ({int(bytes_free):,} bytes)")


def cmd_copy(args):
    if not db_exists(args.src):
        sys.exit(f"Source database does not exist: {args.src}")
    if db_exists(args.dst):
        sys.exit(f"Destination already exists: {args.dst}. Drop it first or pick another name.")
    check_protected(args.dst, args.really_i_mean_it)

    sql = f"CREATE DATABASE {_ident(args.dst)} TEMPLATE {_ident(args.src)};"

    if args.dry_run:
        print(f"[dry-run] would run: {sql}")
        return

    if args.force:
        terminated = kill_connections(args.src)
        if terminated:
            logger.info("Terminated %d connection(s) on %s before copy", terminated, args.src)

    if not confirm(f"Copy {args.src} -> {args.dst}?", args.yes):
        sys.exit("Aborted.")

    psql_run(sql)
    log_action("copy", {"src": args.src, "dst": args.dst})
    print(f"Copied {args.src} -> {args.dst}")


def cmd_rename(args):
    if not db_exists(args.old):
        sys.exit(f"Database does not exist: {args.old}")
    if db_exists(args.new):
        sys.exit(f"Target name already exists: {args.new}")
    check_protected(args.old, args.really_i_mean_it)
    check_protected(args.new, args.really_i_mean_it)

    sql = f"ALTER DATABASE {_ident(args.old)} RENAME TO {_ident(args.new)};"

    if args.dry_run:
        print(f"[dry-run] would run: {sql}")
        return

    if args.force:
        terminated = kill_connections(args.old)
        if terminated:
            logger.info("Terminated %d connection(s) on %s before rename", terminated, args.old)

    if not confirm(f"Rename {args.old} -> {args.new}?", args.yes):
        sys.exit("Aborted.")

    psql_run(sql)
    log_action("rename", {"old": args.old, "new": args.new})
    print(f"Renamed {args.old} -> {args.new}")


def cmd_delete(args):
    if not db_exists(args.db):
        sys.exit(f"Database does not exist: {args.db}")
    check_protected(args.db, args.really_i_mean_it)

    rows = psql_query(
        f"SELECT pg_size_pretty(pg_database_size('{_quote(args.db)}')), "
        f"(SELECT count(*) FROM pg_stat_activity WHERE datname = '{_quote(args.db)}');"
    )
    size, conns = rows[0][0], int(rows[0][1])

    sql = f"DROP DATABASE {_ident(args.db)};"

    if args.dry_run:
        print(f"[dry-run] would drop {args.db} (size {size}, {conns} active conns): {sql}")
        return

    if conns and not args.force:
        sys.exit(
            f"{args.db} has {conns} active connection(s). "
            f"Pass --force to terminate them before dropping."
        )
    if args.force and conns:
        terminated = kill_connections(args.db)
        logger.info("Terminated %d connection(s) on %s before drop", terminated, args.db)

    if not confirm(f"Drop {args.db} (size {size})?", args.yes):
        sys.exit("Aborted.")

    psql_run(sql)
    log_action("delete", {"db": args.db, "size_pretty": size})
    print(f"Dropped {args.db}")


def cmd_drop_checkpoints(args):
    sanitized = args.release.replace(".", "_")
    if args.rc:
        prefix = f"alliancemine_{sanitized}_rc{args.rc}:"
    else:
        prefix = f"alliancemine_{sanitized}_rc%:"
    rows = psql_query(
        f"""
        SELECT
            datname,
            pg_size_pretty(pg_database_size(datname)),
            pg_database_size(datname)
        FROM pg_database
        WHERE datname LIKE '{_quote(prefix)}%'
        ORDER BY datname;
        """
    )
    candidates = [
        {"name": r[0], "size": r[1], "size_bytes": int(r[2])}
        for r in rows
    ]
    if not candidates:
        print("No checkpoint databases match.")
        return

    targets = candidates[:-1] if args.keep_latest else candidates

    print("Will drop the following checkpoints:")
    emit([{"name": t["name"], "size": t["size"]} for t in targets], "text", ["name", "size"])
    total_gb = sum(t["size_bytes"] for t in targets) / (1024 ** 3)
    print(f"\nTotal: {len(targets)} checkpoint(s), {total_gb:.1f} GB to free")
    if args.keep_latest and candidates:
        print(f"Keeping (most recent): {candidates[-1]['name']}")

    if args.dry_run:
        return

    if not confirm("Proceed with bulk drop?", args.yes):
        sys.exit("Aborted.")

    failures = []
    for target in targets:
        name = target["name"]
        try:
            if args.force:
                kill_connections(name)
            psql_run(f"DROP DATABASE {_ident(name)};")
            log_action("drop_checkpoint", {"db": name, "size_pretty": target["size"]})
            print(f"  dropped {name}")
        except Exception as e:
            failures.append((name, str(e)))
            print(f"  FAILED {name}: {e}")

    if failures:
        sys.exit(f"\n{len(failures)} of {len(targets)} drops failed. See log: {LOG_PATH}")


def cmd_promote(args):
    """Rename mine_X_Y_Z_rcN to its production equivalent (mine_X_Y_Z).

    Auto-derives the target by stripping the trailing _rcN suffix; pass
    --target to override. If the production target already exists, requires
    --replace to drop it first.
    """
    if not db_exists(args.src):
        sys.exit(f"Source database does not exist: {args.src}")

    if args.target:
        target = args.target
    else:
        m = re.match(r'^(.+)_rc\d+$', args.src)
        if not m:
            sys.exit(
                f"Source name {args.src!r} doesn't match the *_rcN pattern. "
                f"Pass --target to set the production name explicitly."
            )
        target = m.group(1)

    check_protected(args.src, args.really_i_mean_it)
    check_protected(target, args.really_i_mean_it)

    target_exists = db_exists(target)

    if target_exists and not args.replace:
        sys.exit(
            f"Target {target!r} already exists. Pass --replace to drop it first."
        )

    src_size = psql_query(
        f"SELECT pg_size_pretty(pg_database_size('{_quote(args.src)}'));"
    )[0][0]

    if args.dry_run:
        if target_exists:
            tgt_size = psql_query(
                f"SELECT pg_size_pretty(pg_database_size('{_quote(target)}'));"
            )[0][0]
            print(f"[dry-run] would drop existing {target} ({tgt_size}): "
                  f"DROP DATABASE {_ident(target)};")
        print(f"[dry-run] would rename {args.src} ({src_size}) -> {target}: "
              f"ALTER DATABASE {_ident(args.src)} RENAME TO {_ident(target)};")
        return

    if target_exists:
        prompt = (f"Promote: drop existing {target}, then rename "
                  f"{args.src} -> {target}?")
    else:
        prompt = f"Promote: rename {args.src} ({src_size}) -> {target}?"
    if not confirm(prompt, args.yes):
        sys.exit("Aborted.")

    if args.force:
        if kill_connections(args.src):
            logger.info("Terminated active connections on %s", args.src)
        if target_exists and kill_connections(target):
            logger.info("Terminated active connections on %s", target)

    if target_exists:
        psql_run(f"DROP DATABASE {_ident(target)};")
        log_action("promote_drop_target", {"db": target})
        print(f"Dropped existing {target}")

    psql_run(f"ALTER DATABASE {_ident(args.src)} RENAME TO {_ident(target)};")
    log_action("promote", {
        "src": args.src, "dst": target, "replaced": target_exists,
    })
    print(f"Promoted {args.src} -> {target}")


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )


def add_format_arg(parser):
    parser.add_argument(
        "--format",
        choices=["text", "tsv", "json"],
        default="text",
        help="Output format (default: text)",
    )


def add_destructive_args(parser):
    parser.add_argument("--yes", action="store_true", help="Skip the y/N confirmation")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the SQL that would run, don't execute")
    parser.add_argument("--force", action="store_true",
                        help="Terminate active connections before the operation")
    parser.add_argument("--really-i-mean-it", action="store_true",
                        help="Override the protected-database guard (postgres, template*, "
                             "rdsadmin, alliancemine_userprofile)")


def main():
    parser = argparse.ArgumentParser(
        description="Per-database operations on the AllianceMine RDS instance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List databases on the RDS instance")
    p_list.add_argument("--filter", help="SQL LIKE pattern (e.g. 'alliancemine_9_0_%%')")
    add_format_arg(p_list)
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Show details for one database")
    p_show.add_argument("db", help="Database name")
    add_format_arg(p_show)
    p_show.set_defaults(func=cmd_show)

    p_chk = sub.add_parser("checkpoints", help="List checkpoint DBs for a release/RC")
    p_chk.add_argument("release", help="Release version, e.g. 9.0.0")
    p_chk.add_argument("--rc", type=int, default=None, help="RC number (omit for all RCs)")
    add_format_arg(p_chk)
    p_chk.set_defaults(func=cmd_checkpoints)

    p_free = sub.add_parser("free-space", help="Show RDS free storage (via CloudWatch)")
    p_free.add_argument("--instance-id", default="intermine-postgres",
                        help="RDS instance identifier (default: intermine-postgres)")
    add_format_arg(p_free)
    p_free.set_defaults(func=cmd_free_space)

    p_copy = sub.add_parser("copy", help="Clone a database via CREATE DATABASE TEMPLATE")
    p_copy.add_argument("src", help="Source database")
    p_copy.add_argument("dst", help="Destination name (must not exist)")
    add_destructive_args(p_copy)
    p_copy.set_defaults(func=cmd_copy)

    p_rename = sub.add_parser("rename", help="Rename a database")
    p_rename.add_argument("old", help="Current name")
    p_rename.add_argument("new", help="New name")
    add_destructive_args(p_rename)
    p_rename.set_defaults(func=cmd_rename)

    p_del = sub.add_parser("delete", help="Drop a database")
    p_del.add_argument("db", help="Database name")
    add_destructive_args(p_del)
    p_del.set_defaults(func=cmd_delete)

    p_promote = sub.add_parser("promote",
        help="Rename mine_X_Y_Z_rcN to its production equivalent (mine_X_Y_Z)")
    p_promote.add_argument("src", help="RC database name, e.g. alliancemine_9_0_0_rc99")
    p_promote.add_argument("--target",
        help="Override the auto-derived production name (default: strip the _rcN suffix)")
    p_promote.add_argument("--replace", action="store_true",
        help="Drop the existing production DB first if it already exists")
    add_destructive_args(p_promote)
    p_promote.set_defaults(func=cmd_promote)

    p_dropchk = sub.add_parser("drop-checkpoints", help="Bulk-drop checkpoint DBs")
    p_dropchk.add_argument("release", help="Release version, e.g. 9.0.0")
    p_dropchk.add_argument("--rc", type=int, default=None, help="RC number (omit for all RCs)")
    p_dropchk.add_argument("--keep-latest", action="store_true",
                           help="Keep the alphabetically-last checkpoint (usually the most recent)")
    add_destructive_args(p_dropchk)
    p_dropchk.set_defaults(func=cmd_drop_checkpoints)

    args = parser.parse_args()
    setup_logging(args.verbose)
    require_creds()

    try:
        args.func(args)
    except KeyboardInterrupt:
        sys.exit("\nInterrupted.")
    except RuntimeError as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
