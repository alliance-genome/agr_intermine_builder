#!/usr/bin/env python3
"""compare_mines.py - compare two InterMine instances side by side through their REST APIs.

Compares:
  items      object count per class (from service/model, the counts the model browser shows)
  templates  public templates present on each, and the row count each returns with its own
             default values (each mine runs its own template XML)
  search     keyword-search hit counts for a list of terms

Usage:
  compare_mines.py A_URL B_URL [--labels "1.8,5.1"] [--terms Pax6,Trp53,...] [--out report]
  e.g. compare_mines.py https://mousemine.alliancegenome.org/mousemine \\
                        http://172.31.59.87:8088/mousemine --labels "1.8,5.1" --out mm_compare
Writes <out>.json (all numbers) and <out>.html (side-by-side report). Standard library only.
"""
import argparse, concurrent.futures as cf, html, json, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

TIMEOUT = 180


def get(url, data=None):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data, doseq=True).encode() if data else None)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", "replace")


def class_counts(base):
    model = json.loads(get(base + "/service/model?format=json"))["model"]["classes"]
    return {name: c.get("count") for name, c in model.items()}


def templates(base):
    """name -> (title, template/results parameters for its default values) for every public template.

    Mirrors running the template form without changing anything: every editable constraint is sent
    with its default op/value(s); optional constraints that are switched off by default are left out
    (the service then drops them); locked (non-editable) constraints are applied by the template."""
    root = ET.fromstring(get(base + "/service/templates?format=xml"))
    out = {}
    for t in root.iter("template"):
        q = t.find("query")
        if q is None:
            continue
        params = [("name", t.get("name")), ("format", "count")]
        i = 0
        for c in q.iter("constraint"):
            if c.get("editable") != "true" or c.get("switchable") == "off" or c.get("type"):
                continue
            i += 1
            params += [("constraint%d" % i, c.get("path")), ("op%d" % i, c.get("op") or "="),
                       ("code%d" % i, c.get("code") or "")]
            values = [v.text or "" for v in c.findall("value")]
            if c.get("value") is not None:
                params.append(("value%d" % i, c.get("value")))
            for v in values:
                params.append(("value%d" % i, v))
            if c.get("extraValue"):
                params.append(("extra%d" % i, c.get("extraValue")))
        out[t.get("name")] = (t.get("title") or "", params)
    return out


def run_count(base, params):
    t0 = time.time()
    try:
        n = int(get(base + "/service/template/results", params).strip())
        return {"count": n, "secs": round(time.time() - t0, 1)}
    except Exception as e:  # report, don't stop the comparison
        msg = getattr(e, "read", lambda: b"")()
        msg = msg.decode("utf-8", "replace")[:200] if msg else str(e)[:200]
        return {"error": msg.replace("\n", " "), "secs": round(time.time() - t0, 1)}


def search_hits(base, term):
    try:
        d = json.loads(get(base + "/service/search?" + urllib.parse.urlencode({"q": term, "size": 1})))
        return d.get("totalHits") if d.get("wasSuccessful", True) else "error"
    except Exception as e:
        return "error: %s" % str(e)[:80]


def pct(a, b):
    if isinstance(a, int) and isinstance(b, int):
        return 0.0 if a == b else (100.0 * (b - a) / a if a else float("inf"))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a"); ap.add_argument("b")
    ap.add_argument("--labels", default="A,B")
    ap.add_argument("--terms", default="Pax6,Trp53,Shh,MGI:97490,Diabetes mellitus,C57BL/6J,abnormal heart,Brca1,Kit,apoptosis")
    ap.add_argument("--out", default="mine_compare")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    la, lb = [s.strip() for s in a.labels.split(",")]
    bases = {la: a.a.rstrip("/"), lb: a.b.rstrip("/")}
    res = {"labels": [la, lb], "urls": bases, "when": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}

    for k, u in bases.items():
        res.setdefault("version", {})[k] = {"api": get(u + "/service/version").strip(),
                                            "release": get(u + "/service/version/release").strip().strip('"')}
    print("classes...", file=sys.stderr)
    cc = {k: class_counts(u) for k, u in bases.items()}
    res["classes"] = [{"class": c, la: cc[la].get(c), lb: cc[lb].get(c)} for c in sorted(set(cc[la]) | set(cc[lb]))]

    print("templates...", file=sys.stderr)
    tp = {k: templates(u) for k, u in bases.items()}
    names = sorted(set(tp[la]) | set(tp[lb]))
    jobs = {}
    with cf.ThreadPoolExecutor(a.workers) as ex:
        for n in names:
            for k in (la, lb):
                if n in tp[k]:
                    jobs[(n, k)] = ex.submit(run_count, bases[k], tp[k][n][1])
        rows = []
        for i, n in enumerate(names):
            row = {"template": n, "title": (tp[la].get(n) or tp[lb].get(n))[0]}
            for k in (la, lb):
                row[k] = jobs[(n, k)].result() if (n, k) in jobs else {"missing": True}
            rows.append(row)
            print("  %d/%d %s" % (i + 1, len(names), n), file=sys.stderr)
    res["templates"] = rows

    print("search...", file=sys.stderr)
    terms = [t.strip() for t in a.terms.split(",") if t.strip()]
    res["search"] = [{"term": t, la: search_hits(bases[la], t), lb: search_hits(bases[lb], t)} for t in terms]

    json.dump(res, open(a.out + ".json", "w"), indent=1)
    open(a.out + ".html", "w").write(render(res))
    s = summary(res)
    print(json.dumps(s, indent=1))
    return 0


def summary(r):
    la, lb = r["labels"]
    cls = r["classes"]; tpl = r["templates"]
    same_cls = sum(1 for c in cls if c[la] == c[lb])
    def cnt(x): return x.get("count") if isinstance(x, dict) else None
    both = [t for t in tpl if "missing" not in t[la] and "missing" not in t[lb]]
    same_t = sum(1 for t in both if cnt(t[la]) is not None and cnt(t[la]) == cnt(t[lb]))
    err = {k: sum(1 for t in tpl if "error" in t[k]) for k in (la, lb)}
    return {"classes": len(cls), "classes_identical": same_cls,
            "templates": len(tpl), "templates_in_both": len(both), "templates_same_count": same_t,
            "templates_only_" + la: sum(1 for t in tpl if "missing" in t[lb]),
            "templates_only_" + lb: sum(1 for t in tpl if "missing" in t[la]),
            "template_errors": err}


def render(r):
    la, lb = r["labels"]
    s = summary(r)
    e = html.escape

    def num(v):
        return "–" if v is None else ("{:,}".format(v) if isinstance(v, int) else e(str(v)))

    def delta(a, b):
        p = pct(a, b)
        if p is None: return ('<td class="d">—</td>', "")
        if p == 0: return ('<td class="d same">same</td>', "same")
        cls = "up" if p > 0 else "down"
        big = " big" if abs(p) >= 5 else ""
        return ('<td class="d %s%s">%+.1f%%</td>' % (cls, big, p) if p != float("inf") else '<td class="d up big">new</td>',
                "diff")

    def tcell(x):
        if x.get("missing"): return '<td class="n miss">not present</td>'
        if "error" in x: return '<td class="n err" title="%s">error</td>' % e(x["error"])
        return '<td class="n">%s</td>' % num(x["count"])

    cls_rows = []
    for c in r["classes"]:
        d, kind = delta(c[la], c[lb])
        cls_rows.append('<tr data-kind="%s"><td>%s</td><td class="n">%s</td><td class="n">%s</td>%s</tr>'
                        % (kind, e(c["class"]), num(c[la]), num(c[lb]), d))
    tpl_rows = []
    for t in r["templates"]:
        a_, b_ = t[la], t[lb]
        if a_.get("missing") or b_.get("missing") or "error" in a_ or "error" in b_:
            d, kind = '<td class="d big">check</td>', "diff"
        else:
            d, kind = delta(a_["count"], b_["count"])
        tpl_rows.append('<tr data-kind="%s"><td><b>%s</b><div class="sub">%s</div></td>%s%s%s</tr>'
                        % (kind, e(t["template"]), e(t["title"]), tcell(a_), tcell(b_), d))
    s_rows = []
    for x in r["search"]:
        d, kind = delta(x[la], x[lb])
        s_rows.append('<tr data-kind="%s"><td>%s</td><td class="n">%s</td><td class="n">%s</td>%s</tr>'
                      % (kind, e(x["term"]), num(x[la]), num(x[lb]), d))
    ver = r["version"]
    return TEMPLATE.format(
        la=e(la), lb=e(lb), when=e(r["when"]),
        ua=e(r["urls"][la]), ub=e(r["urls"][lb]),
        rela=e(ver[la]["release"]), relb=e(ver[lb]["release"]), apia=e(ver[la]["api"]), apib=e(ver[lb]["api"]),
        cls_same=s["classes_identical"], cls_n=s["classes"],
        t_same=s["templates_same_count"], t_both=s["templates_in_both"], t_n=s["templates"],
        t_only_a=s["templates_only_" + la], t_only_b=s["templates_only_" + lb],
        t_err=sum(s["template_errors"].values()),
        cls_rows="\n".join(cls_rows), tpl_rows="\n".join(tpl_rows), s_rows="\n".join(s_rows))


TEMPLATE = """<title>{la} vs {lb}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{{--bg:#f4f6f5;--paper:#fff;--ink:#1b2320;--muted:#5d6a64;--rule:#d8ddd9;--soft:#ebefec;--accent:#2d6b59;
--up:#2c7a4b;--down:#a8433b;--warn:#9a5b12;--warn-bg:#f8eedd}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#131816;--paper:#1a211e;--ink:#e3e9e5;--muted:#9aa8a1;
--rule:#2e3833;--soft:#222b27;--accent:#7cc4ad;--up:#7ccf9c;--down:#e8958c;--warn:#e3b36b;--warn-bg:#33291a;color-scheme:dark}}}}
:root[data-theme="dark"]{{--bg:#131816;--paper:#1a211e;--ink:#e3e9e5;--muted:#9aa8a1;--rule:#2e3833;--soft:#222b27;
--accent:#7cc4ad;--up:#7ccf9c;--down:#e8958c;--warn:#e3b36b;--warn-bg:#33291a;color-scheme:dark}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 "IBM Plex Sans",system-ui,sans-serif}}
.wrap{{max-width:1040px;margin:0 auto;padding-inline:18px;padding-block:32px 60px}}
h1{{font-size:1.7rem;margin:0}} h2{{font-size:1.15rem;margin:36px 0 8px}}
.meta{{color:var(--muted);font-size:.85rem;margin-top:6px}} code{{font-family:"IBM Plex Mono",monospace;font-size:.85em}}
.facts{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:20px}}
.fact{{background:var(--paper);border:1px solid var(--rule);border-radius:8px;padding:12px 14px}}
.fact b{{display:block;font-size:1.35rem;font-variant-numeric:tabular-nums}} .fact span{{color:var(--muted);font-size:.8rem}}
@media (max-width:700px){{.facts{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
.bar{{display:flex;gap:14px;align-items:center;margin:8px 0;flex-wrap:wrap}} label{{font-size:.85rem;color:var(--muted)}}
input[type=search]{{padding:6px 10px;border:1px solid var(--rule);border-radius:6px;background:var(--paper);color:var(--ink);min-width:220px}}
.box{{overflow-x:auto;border:1px solid var(--rule);border-radius:8px;background:var(--paper)}}
table{{border-collapse:collapse;width:100%;font-size:.88rem}} th,td{{padding:6px 10px;border-bottom:1px solid var(--rule);text-align:left;vertical-align:top}}
th{{background:var(--soft);font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);position:sticky;top:0}}
td.n,td.d{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}} .sub{{color:var(--muted);font-size:.8rem}}
.same{{color:var(--muted)}} .up{{color:var(--up)}} .down{{color:var(--down)}} .big{{font-weight:600}}
.miss{{color:var(--muted);font-style:italic}} .err{{color:var(--warn);background:var(--warn-bg)}}
.hide{{display:none}}
</style>
<div class="wrap">
<h1>{la} vs {lb}</h1>
<p class="meta">{when} · <b>{la}</b> <code>{ua}</code> (release {rela}, API {apia}) · <b>{lb}</b> <code>{ub}</code> (release {relb}, API {apib})</p>
<div class="facts">
 <div class="fact"><b>{cls_same} / {cls_n}</b><span>classes with identical counts</span></div>
 <div class="fact"><b>{t_same} / {t_both}</b><span>templates in both returning the same rows</span></div>
 <div class="fact"><b>{t_only_a} · {t_only_b}</b><span>templates only in {la} · only in {lb}</span></div>
 <div class="fact"><b>{t_err}</b><span>template runs that errored</span></div>
</div>
<div class="bar"><label><input type="checkbox" id="onlydiff" checked> Show only differences</label>
<input type="search" id="filter" placeholder="Filter by name…"></div>

<h2>Templates (default values, row counts)</h2>
<div class="box"><table data-t><thead><tr><th>Template</th><th>{la}</th><th>{lb}</th><th>Δ</th></tr></thead><tbody>
{tpl_rows}
</tbody></table></div>

<h2>Items (objects per class)</h2>
<div class="box"><table data-t><thead><tr><th>Class</th><th>{la}</th><th>{lb}</th><th>Δ</th></tr></thead><tbody>
{cls_rows}
</tbody></table></div>

<h2>Keyword search (total hits)</h2>
<div class="box"><table data-t><thead><tr><th>Term</th><th>{la}</th><th>{lb}</th><th>Δ</th></tr></thead><tbody>
{s_rows}
</tbody></table></div>
<p class="meta">Row counts are what each mine returns for its own template with the template's default values. Search ranking differs between Lucene (1.x) and Solr (5.x), so hit counts are indicative only.</p>
</div>
<script>
const od=document.getElementById('onlydiff'), f=document.getElementById('filter');
function apply(){{const q=f.value.toLowerCase();document.querySelectorAll('table[data-t] tbody tr').forEach(tr=>{{
 const hideSame=od.checked&&tr.dataset.kind==='same'; const miss=q&&!tr.textContent.toLowerCase().includes(q);
 tr.classList.toggle('hide',hideSame||miss);}});}}
od.addEventListener('change',apply); f.addEventListener('input',apply); apply();
</script>
"""

if __name__ == "__main__":
    sys.exit(main())
