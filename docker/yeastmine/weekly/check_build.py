#!/usr/bin/env python3
"""check_build.py - gate a weekly YeastMine build before it is published for deploy.

Compares the new build with the live one and inspects the WAR. Any failed check exits 1 and
the build is not published, so production keeps running the live build.

  --new / --live   per-class object counts (class<TAB>count) from each database
  --solr           core<TAB>numDocs for the live and standby (-next) cores
  --war            the built WAR; --db the database it must point at
"""
import argparse, io, json, sys, zipfile

KEY_CLASSES = ["Gene", "Protein", "Publication", "GOAnnotation", "Phenotype", "Interaction",
               "Complex", "Allele", "Chromosome", "Organism", "OntologyTerm"]
TOTAL_TOL = 0.10        # total objects within +/-10% of live
KEY_MIN = 0.90          # key classes keep at least 90% of their live count
ANY_MIN = 0.50          # any class with >= 1000 live objects keeps at least half
SOLR_MIN = 0.90         # standby indexes hold at least 90% of the live index


def counts(path):
    out = {}
    for line in open(path):
        if line.strip():
            cls, n = line.rstrip("\n").split("\t")
            out[cls] = int(n)
    return out


def parse(text):
    out = {}
    for l in text.splitlines():
        if "=" in l and not l.lstrip().startswith("#"):
            k, v = l.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def props(war, filename):
    """key -> value for `filename`, loose in the WAR or inside WEB-INF/lib/dbmodel.jar
    (where the Solr URL files live)."""
    with zipfile.ZipFile(war) as z:
        for entry in z.namelist():
            if entry.split("/")[-1] == filename:
                return parse(z.read(entry).decode("utf-8", "replace"))
        for entry in z.namelist():
            if entry.startswith("WEB-INF/lib/dbmodel") and entry.endswith(".jar"):
                with zipfile.ZipFile(io.BytesIO(z.read(entry))) as j:
                    if filename in j.namelist():
                        return parse(j.read(filename).decode("utf-8", "replace"))
    return {}


def main():
    ap = argparse.ArgumentParser()
    for a in ("--new", "--live", "--solr", "--war", "--db", "--out"):
        ap.add_argument(a, required=True)
    ap.add_argument("--label", help="expected project.releaseVersion (release, build date, GO version)")
    a = ap.parse_args()
    new, live = counts(a.new), counts(a.live)
    checks = []

    def check(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    tn, tl = sum(new.values()), sum(live.values())
    check("total objects", tl and abs(tn - tl) / tl <= TOTAL_TOL, "%d vs live %d (%+.1f%%)" % (tn, tl, 100.0 * (tn - tl) / tl if tl else 0))
    for c in KEY_CLASSES:
        if live.get(c):
            check("key class " + c, new.get(c, 0) >= KEY_MIN * live[c], "%d vs live %d" % (new.get(c, 0), live[c]))
    for c, n in sorted(live.items()):
        if n >= 1000 and c not in KEY_CLASSES and new.get(c, 0) < ANY_MIN * n:
            check("class " + c, False, "%d vs live %d (lost over half)" % (new.get(c, 0), n))

    solr = dict(l.rstrip("\n").split("\t") for l in open(a.solr) if "\t" in l)
    for kind in ("search", "autocomplete"):
        lv, nx = int(solr.get("yeastmine-%s" % kind) or 0), int(solr.get("yeastmine-%s-next" % kind) or 0)
        check("solr " + kind, nx > 0 and nx >= SOLR_MIN * lv, "standby %d vs live %d docs" % (nx, lv))

    with zipfile.ZipFile(a.war) as z:
        names = set(z.namelist())
    check("war webapp", {"WEB-INF/web.xml", "WEB-INF/struts-config.xml"} <= names, "%d entries" % len(names))
    ip = props(a.war, "intermine.properties")
    wp = props(a.war, "web.properties")
    ks = props(a.war, "keyword_search.properties")
    oc = props(a.war, "objectstoresummary.config.properties")
    check("war database", ip.get("db.production.datasource.databaseName") == a.db,
          ip.get("db.production.datasource.databaseName", "<missing>"))
    check("war mail", wp.get("mail.host") and wp.get("mail.smtp.user"), "mail.host=%s" % wp.get("mail.host", "<missing>"))
    check("war solr search", ks.get("index.solrurl", "").endswith("/yeastmine-search"),
          "%s (must be the live core, not -next)" % ks.get("index.solrurl", "<missing>"))
    check("war solr autocomplete", oc.get("autocomplete.solrurl", "").endswith("/yeastmine-autocomplete"),
          oc.get("autocomplete.solrurl", "<missing>"))
    check("war javamail", any(n.endswith("javax.mail-1.6.2.jar") for n in names), "SES needs JavaMail 1.6.2")
    logo = wp.get("branding.images.logo", "")
    check("war branding logo", logo.startswith("https://yeastmine.alliancegenome.org/"),
          "%s (BlueGenes shows this; the old yeastgenome.org host is dead)" % (logo or "<missing>"))
    if a.label:
        shown = wp.get("project.releaseVersion") or ip.get("project.releaseVersion", "<missing>")
        check("war release label", shown == a.label, "%s (header shows build date + GO version)" % shown)

    ok = all(c["ok"] for c in checks)
    json.dump({"ok": ok, "checks": checks, "total_new": tn, "total_live": tl}, open(a.out, "w"), indent=1)
    for c in checks:
        print("%-4s %-28s %s" % ("ok" if c["ok"] else "FAIL", c["check"], c["detail"]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
