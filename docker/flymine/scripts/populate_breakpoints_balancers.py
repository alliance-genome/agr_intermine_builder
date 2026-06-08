#!/usr/bin/env python3
"""
Direct-SQL population of:
  * cytologicalband + intermineobject  (new CytologicalBand entities)
  * aberrationcytologicalbreakpoints   (FBab -> band links)
  * balancercomposedofaberrations      (FBba -> FBab links)

This bypasses InterMine's integrate machinery. Used 2026-06-08 when a
re-integrate of flybase-aberrations against an already-built rc2 DB tripped
the tracker provenance check (`SourcePriorityComparator: Object o1 is not
in the data tracking system`) and the only escape paths were (a) full rc3
rebuild from scratch (5-8 hours) or (b) direct SQL insert (minutes).

INPUTS (read from `/tmp/` inside the build container — operator must copy
in first; the data dir mount is at `/root/data/flybase/aberrations/` but the
script reads from `/tmp/` so it works both inside the build container and
on the dev host as long as the files are placed there):

  /tmp/aberration_cytological_breakpoints.tsv
      The chado-pg dump produced by scripts/dump_breakpoints.sql.
      Columns: fbab \\t breakpoint_name \\t genomic_loc \\t chrom \\t fmin \\t fmax \\t cyto_loc
      Only fbab + cyto_loc are read in v1 (matches sibling commit
      flymine-bio-sources@74ef170 scope).

  /tmp/fbba_to_fbab.tsv
      Sibling-curated balancer-composition table from
      flymine-bio-sources@75303cb /flybase-aberrations/src/main/resources/.
      Columns: fbba_id \\t fbba_symbol \\t fbab_refs (pipe-separated FBabs OR
      symbols like "In(2LR)CyO") \\t note

USAGE (run inside the flymine-build container so psycopg2 is reachable; the
DB connection params are read from env or fall back to FlyMine deploy
defaults):

  docker exec flymine-build python3 -m pip install psycopg2-binary --break-system-packages
  docker cp /tmp/aberration_cytological_breakpoints.tsv flymine-build:/tmp/
  docker cp /tmp/fbba_to_fbab.tsv flymine-build:/tmp/
  docker exec -e RDS_PASSWORD=... flymine-build python3 \
      /root/scripts/populate_breakpoints_balancers.py

PREREQUISITES:
  * Aberration + Balancer entities already loaded (their primaryidentifier
    is the lookup key).
  * cytologicalband table EMPTY (the script allocates IDs from
    max(intermineobject.id)+1; if rows already exist the ID allocation
    needs a different strategy).
  * fbba_to_fbab.tsv uses FBab primary IDs OR aberration symbols; symbols
    are resolved via aberration.symbol case-sensitive exact match.

IDEMPOTENCE: NOT idempotent. Re-running will duplicate CytologicalBand
rows and link table entries. Drop the inserted rows first if re-running:

  TRUNCATE aberrationcytologicalbreakpoints;
  TRUNCATE balancercomposedofaberrations;
  DELETE FROM intermineobject WHERE id IN (SELECT id FROM cytologicalband);
  TRUNCATE cytologicalband;
"""

import csv
import os
import sys
import psycopg2

PG = dict(
    host=os.environ.get("RDS_HOST", "intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com"),
    user=os.environ.get("RDS_USER", "postgres"),
    password=os.environ["RDS_PASSWORD"],
    dbname=os.environ.get("RDS_DB_NAME", "flymine_v0-2026-05-31_rc2"),
)

BREAKPOINTS_TSV = os.environ.get(
    "BREAKPOINTS_TSV", "/tmp/aberration_cytological_breakpoints.tsv"
)
FBBA_TSV = os.environ.get("FBBA_TSV", "/tmp/fbba_to_fbab.tsv")
CLASS_FQN = "org.intermine.model.bio.CytologicalBand"


def make_object_text(class_fqn: str, fields: dict) -> str:
    """Serialize an InterMine object as '$_^class$_^aFIELD$_^VALUE...'.

    Mirrors the format InterMine's ObjectStoreInterMineImpl serializer
    writes for entities. Single-letter prefix marks the kind:
      a = attribute, r = reference, c = collection (collections aren't used
      here — link rows go straight into the join table).
    """
    parts = [class_fqn]
    for name, val in fields.items():
        parts.append(f"a{name}")
        parts.append(str(val))
    return "$_^" + "$_^".join(parts)


def main():
    conn = psycopg2.connect(**PG)
    conn.autocommit = False
    cur = conn.cursor()

    print("loading aberration id maps…", flush=True)
    cur.execute("SELECT primaryidentifier, id FROM aberration")
    abr_by_pk = dict(cur.fetchall())
    cur.execute("SELECT symbol, id FROM aberration WHERE symbol IS NOT NULL")
    abr_by_sym = dict(cur.fetchall())
    print(f"  {len(abr_by_pk)} by FBab, {len(abr_by_sym)} by symbol", flush=True)

    cur.execute("SELECT primaryidentifier, id FROM balancer")
    bal_by_pk = dict(cur.fetchall())
    print(f"  {len(bal_by_pk)} balancers by FBba", flush=True)

    print(f"reading {BREAKPOINTS_TSV}…", flush=True)
    abr_bands: dict[str, set[str]] = {}
    with open(BREAKPOINTS_TSV) as fh:
        reader = csv.reader(fh, delimiter="\t")
        header = next(reader)
        idx_fbab = header.index("fbab")
        idx_cyto = header.index("cyto_loc")
        for row in reader:
            if len(row) <= idx_cyto:
                continue
            fbab = row[idx_fbab].strip()
            cyto = row[idx_cyto].strip()
            if not fbab or not cyto:
                continue
            for band in cyto.split(";"):
                band = band.strip()
                if band:
                    abr_bands.setdefault(fbab, set()).add(band)

    matched = sum(1 for f in abr_bands if f in abr_by_pk)
    unique_bands = sorted({b for bs in abr_bands.values() for b in bs})
    print(f"  {len(abr_bands)} FBabs with bands ({matched} match DB)", flush=True)
    print(f"  {len(unique_bands)} distinct band strings", flush=True)

    cur.execute("SELECT COALESCE(max(id), 0) FROM intermineobject")
    next_id = cur.fetchone()[0] + 1
    print(f"next intermineobject id = {next_id}", flush=True)

    band_id = {}
    for b in unique_bands:
        band_id[b] = next_id
        next_id += 1

    print(f"inserting {len(unique_bands)} CytologicalBand rows…", flush=True)
    cur.executemany(
        "INSERT INTO intermineobject (id, class, object) VALUES (%s, %s, %s)",
        [(bid, CLASS_FQN, make_object_text(CLASS_FQN, {
            "cytologicalCoordinates": b, "id": bid,
        })) for b, bid in band_id.items()],
    )
    cur.executemany(
        "INSERT INTO cytologicalband (id, cytologicalcoordinates, class) VALUES (%s, %s, %s)",
        [(bid, b, CLASS_FQN) for b, bid in band_id.items()],
    )

    print("inserting aberrationcytologicalbreakpoints…", flush=True)
    pairs = set()
    skipped = 0
    for fbab, bs in abr_bands.items():
        abr_id = abr_by_pk.get(fbab)
        if abr_id is None:
            skipped += 1
            continue
        for b in bs:
            pairs.add((abr_id, band_id[b]))
    cur.executemany(
        "INSERT INTO aberrationcytologicalbreakpoints (aberration, cytologicalbreakpoints) VALUES (%s, %s)",
        sorted(pairs),
    )
    print(f"  {len(pairs)} aberration->band rows ({skipped} FBabs not in DB)", flush=True)

    print(f"reading {FBBA_TSV}…", flush=True)
    bal_pairs = set()
    bal_skip = ref_skip = 0
    with open(FBBA_TSV) as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            fbba = parts[0].strip()
            refs = parts[2].strip()
            bal_id = bal_by_pk.get(fbba)
            if bal_id is None:
                bal_skip += 1
                continue
            for ref in refs.split("|"):
                ref = ref.strip()
                if not ref:
                    continue
                abr_id = abr_by_pk.get(ref) if ref.startswith("FBab") else abr_by_sym.get(ref)
                if abr_id is None:
                    print(f"  skip {fbba} -> {ref!r} (unresolved)", flush=True)
                    ref_skip += 1
                    continue
                bal_pairs.add((bal_id, abr_id))
    cur.executemany(
        "INSERT INTO balancercomposedofaberrations (balancer, composedofaberrations) VALUES (%s, %s)",
        sorted(bal_pairs),
    )
    print(f"  {len(bal_pairs)} balancer->aberration rows ({bal_skip} bal skipped, {ref_skip} refs unresolved)", flush=True)

    conn.commit()
    print("committed.", flush=True)


if __name__ == "__main__":
    main()
