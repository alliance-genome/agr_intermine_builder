#!/usr/bin/env python3
"""
Generate the InterMine `objectstoresummary.properties` file from raw table
row counts.

InterMine's `:webapp:summariseObjectStore` task is supposed to write this
file, but it fails silently on the FlyMine model because `Sequence.residues`
is a Clob and the summariser's `registerOffset` code path can't handle
ClobAccess values. The task exits with `Error: failed to get the object
store summary` and no file is produced — which then makes every begin.do
/report page render with `Unable to load objectstoresummary.properties
file. Cannot find class count for: org.intermine.model.InterMineObject`.

This script bypasses the summariser entirely. For each class declared in
the merged genomic_model.xml, it COUNTs the underlying lowercase table
(InterMine convention) and emits an `org.intermine.model.bio.<Class>.classCount`
line. The aggregate `InterMineObject.classCount` is the sum.

Output is written to stdout — `finalize_build.sh` pipes it into the WAR.

USAGE:
    python3 gen_objectstoresummary.py [--model PATH] [--out PATH]

The script reads `db.production.datasource.*` props from
`/root/.intermine/flymine.properties` for the DB connection. Override the
default model path with `--model`; defaults to the in-image location:

    /root/flymine/dbmodel/build/resources/main/genomic_model.xml

LIMITS:
    * Only `classCount` is emitted. Field-value lists + null-field info
      that the original summariser produces are skipped — webapp filter
      drop-downs may show fewer pre-computed buckets. For the immediate
      "page won't render" bug, classCount is the only thing needed.

    * Empty-table classes still get a row (`classCount=0`) so the webapp
      doesn't fall back to "cannot find class count".

See docs/FLYMINE_DEPLOY_2026_06_05.md "Hand-rolled objectstoresummary"
section for the rc2 hot-fix that this script generalises.
"""

import argparse
import os
import re
import sys
import time

import psycopg2

DEFAULT_MODEL = "/root/flymine/dbmodel/build/resources/main/genomic_model.xml"
PROPS = "/root/.intermine/flymine.properties"
CLASS_PREFIX = "org.intermine.model.bio."


def read_props(path: str) -> dict:
    out = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def extract_classes(model_path: str) -> list:
    with open(model_path) as fh:
        xml = fh.read()
    classes = re.findall(r'<class\s+name="([A-Z][A-Za-z0-9]+)"', xml)
    return sorted(set(classes))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", default="-", help="output path; '-' for stdout")
    args = ap.parse_args()

    props = read_props(PROPS)
    conn = psycopg2.connect(
        host=props["db.production.datasource.serverName"],
        user=props["db.production.datasource.user"],
        password=props["db.production.datasource.password"],
        dbname=props["db.production.datasource.databaseName"],
    )
    cur = conn.cursor()

    classes = extract_classes(args.model)
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    tables = {row[0] for row in cur.fetchall()}

    lines = [
        f"# Generated {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} "
        f"by gen_objectstoresummary.py against "
        f"{props['db.production.datasource.databaseName']}"
    ]
    total = 0
    for cls in classes:
        tbl = cls.lower()
        if tbl in tables:
            cur.execute(f'SELECT count(*) FROM "{tbl}"')
            (n,) = cur.fetchone()
        else:
            n = 0
        lines.append(f"{CLASS_PREFIX}{cls}.classCount={n}")
        total += n
    lines.append(f"org.intermine.model.InterMineObject.classCount={total}")

    output = "\n".join(lines) + "\n"
    if args.out == "-":
        sys.stdout.write(output)
    else:
        with open(args.out, "w") as fh:
            fh.write(output)
    sys.stderr.write(
        f"wrote {len(classes)} class lines, InterMineObject total={total}\n"
    )


if __name__ == "__main__":
    main()
