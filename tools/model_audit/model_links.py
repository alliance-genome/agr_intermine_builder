#!/usr/bin/env python3
"""Cross-link audit of the AllianceMine model: InterMine core + genomic additions + every
*_additions.xml under a bio-sources checkout. Standard InterMine source additions (uniprot,
go-annotation, ...) are not on disk, so the merged class count is below the built model's.

    model_links.py report ~/intermine/alliancemine-bio-sources
    model_links.py where  ~/intermine/alliancemine-bio-sources Gene Variant.affectedGene
"""
import argparse
import re
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from pathlib import Path

BIO_MODEL_JAR = "https://repo1.maven.org/maven2/org/intermine/bio-model/{v}/bio-model-{v}.jar"
CACHE = Path.home() / ".cache" / "model_audit"
HUBS = {"Gene", "Allele", "Protein", "Publication", "OntologyTerm", "Organism", "DataSet"}
OWN_IDS = {"primaryIdentifier", "secondaryIdentifier", "identifier", "symbol", "name",
           "primaryAccession", "secondaryAccession", "taxonId", "accession"}
FOREIGN_ID = re.compile(r"(Id|Ids|Curie|Curies|Identifier|Identifiers|Symbol|Symbols|Accession)$")


def core_files(version):
    """core.xml and genomic_additions.xml from the bio-model jar, downloaded once."""
    out = [CACHE / version / n for n in ("core.xml", "genomic_additions.xml")]
    if not all(p.exists() for p in out):
        out[0].parent.mkdir(parents=True, exist_ok=True)
        jar = out[0].parent / "bio-model.jar"
        urllib.request.urlretrieve(BIO_MODEL_JAR.format(v=version), jar)
        with zipfile.ZipFile(jar) as z:
            for p in out:
                p.write_bytes(z.read(p.name))
    return out


def model_files(bio_sources, version):
    extra = sorted(p for p in Path(bio_sources).rglob("*additions*.xml") if "build" not in p.parts)
    return core_files(version), extra


def load(files):
    classes = {}
    for f in files:
        for c in ET.parse(f).getroot().iter("class"):
            d = classes.setdefault(c.get("name"), {"extends": set(), "attrs": {}, "refs": {}})
            d["extends"].update((c.get("extends") or "").split())
            for a in c.findall("attribute"):
                d["attrs"][a.get("name")] = a.get("type").split(".")[-1]
            for kind in ("reference", "collection"):
                for r in c.findall(kind):
                    d["refs"][r.get("name")] = (r.get("referenced-type"), r.get("reverse-reference"), kind)
    return classes


def ancestors(classes, name):
    seen, todo = set(), [name]
    while todo:
        for parent in classes.get(todo.pop(), {}).get("extends", ()):
            if parent not in seen:
                seen.add(parent)
                todo.append(parent)
    return seen


def report(args):
    core, extra = model_files(args.bio_sources, args.version)
    classes = load(core + extra)
    base = set(load(core))
    new = sorted(n for n in classes if n not in base)
    incoming = defaultdict(set)
    for n, d in classes.items():
        for field, (target, _, _) in d["refs"].items():
            incoming[target].add(f"{n}.{field}")

    print(f"classes: {len(classes)} merged, {len(new)} from bio-source additions\n")
    oneway = [(n, f, t, k) for n in new for f, (t, rev, k) in classes[n]["refs"].items() if not rev]
    print(f"== one-way references from bio-source classes: {len(oneway)}")
    for n, f, t, k in oneway:
        print(f"  {n}.{f} -> {t} ({k})")
    orphans = [n for n in new if not incoming[n] and not any(incoming[a] for a in ancestors(classes, n))]
    print(f"\n== bio-source classes nothing references: {len(orphans)}")
    for n in orphans:
        print(f"  {n}")
    ids = [(n, a) for n in sorted(classes) for a, t in classes[n]["attrs"].items()
           if t == "String" and a not in OWN_IDS and FOREIGN_ID.search(a)]
    print(f"\n== String attributes holding another object's ID: {len(ids)}")
    for n, a in ids:
        print(f"  {n}.{a}")
    print("\n== bio-source classes with no reference path to " + ", ".join(sorted(HUBS)))
    for n in new:
        reach = set()
        for target, _, _ in classes[n]["refs"].values():
            reach |= {target} | ancestors(classes, target)
        if not reach & HUBS:
            print(f"  {n}")


def where(args):
    core, extra = model_files(args.bio_sources, args.version)
    for query in args.names:
        cls, _, field = query.partition(".")
        print(f"== {query}")
        for f in core + extra:
            for c in ET.parse(f).getroot().iter("class"):
                if c.get("name") != cls:
                    continue
                for e in c:
                    if field and e.get("name") != field:
                        continue
                    rest = " ".join(f"{k}={v}" for k, v in e.attrib.items() if k != "name")
                    print(f"  {f.name}: {e.tag} {e.get('name')} {rest}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", default="5.1.0", help="InterMine bio-model version (default 5.1.0)")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report")
    r.add_argument("bio_sources")
    r.set_defaults(func=report)
    w = sub.add_parser("where")
    w.add_argument("bio_sources")
    w.add_argument("names", nargs="+", help="Class or Class.field")
    w.set_defaults(func=where)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
