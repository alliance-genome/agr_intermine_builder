# Phase 2 build results + new source request — flymine handoff

**Date:** 2026-06-04
**From:** agr_intermine_builder session
**To:** new_flymine session
**Re:** Phase 2 build state, 2 builder patches to upstream, new `flybase-allele-stubs` source request

---

## 1. Phase 2 build status: green

`./project_build -b rds flymine_dump` with your 5 commits + 2 builder patches landed clean across **23 active sources**.

`flymine_v0-2026-05-31_rc2` on intermine-postgres RDS, **19 GB** (Phase 1.5 16 GB + 3 GB delta).

### Counts

| Metric | Phase 1.5 | Phase 2 | Δ |
|---|---|---|---|
| Gene | 148,066 | 148,066 | 0 |
| Allele | 233,414 | **234,211** | +797 (non-dmel Drosophila chado) |
| Aberration | 23,870 | 23,870 | 0 ✅ |
| Balancer | 644 | 644 | 0 ✅ |
| Organism | 16 | **17** | +1 (Dpse added by `chado-db-flybase-dpse`) |
| Protein | 57,911 | 57,911 | 0 |
| OntologyTerm | 58,698 | 58,698 | 0 |
| GOAnnotation | 182,289 | 182,289 | 0 |
| Publication | 144,168 | **154,254** | +10,086 (FBrf refs from `flybase-allele-descriptions`) |
| Homologue | 516,326 | 516,326 | 0 |
| ProteinDomain | 51,489 | 51,489 | 0 |
| Stock | 122,066 | 122,066 | 0 |
| **`allele.description IS NOT NULL`** | 0 | **45,945** | ✅ lean alleles signal |
| DB size | 16 GB | 19 GB | +3 GB |

### Your Aim-1 schema additions (12152b3): **clean compile**

No build break from the new `ComplementationResult`, `CytologicalBand`, `carriedAlleles`/`carriedByAberrations` etc. Collections come back empty as expected (your converter SQL not landed yet); no regression on Phase 1 collection counts.

---

## 2. Builder patches to upstream

### 2.1 `flybase-allele-descriptions_additions.xml` — Publication needs `primaryIdentifier` field

Your converter at `FlybaseAlleleDescriptionsConverter.java:153`:
```java
p = createItem("Publication");
p.setAttribute("primaryIdentifier", fbrf);
```

But the additions XML didn't add the field to `Publication`. buildDB blocks with:
> `No such field name primaryIdentifier in class org.intermine.model.bio.Publication for primary key key`

Builder-side patch I applied to your additions XML:
```xml
<class name="Publication" is-interface="true">
  <attribute name="primaryIdentifier" type="java.lang.String"/>
</class>
```

Please upstream into `flybase-allele-descriptions_additions.xml`. (Or, alternatively, change the converter to use a different attribute — though FBrf doesn't map cleanly to `Publication.pubMedId` since FBrf ≠ PubMed ID.)

### 2.2 `genomic_priorities.properties` — `Allele.sequenceOntologyTerm` collision

The new lean alleles source incidentally creates an `Allele` item, which by InterMine inheritance brings a `sequenceOntologyTerm` reference. The reference is to a fresh `SOTerm("allele")` + `Ontology("Sequence Ontology")` pair the converter never explicitly creates (likely a default field on the parent class or InterMine `BioFileConverter` boilerplate). When merging with the chado-loaded Allele rows, the loader hits a field collision.

Builder-side patch I applied to `genomic_priorities.properties`:
```properties
Allele.sequenceOntologyTerm = chado-db-flybase-dmel, *
```

Please upstream. The earlier `SOTerm.ontology` / `Ontology.name` / `Ontology.url` priority entries (from the Phase 1.5 closeout) are still needed too — keep all four.

If your converter doesn't actually want to touch `sequenceOntologyTerm` at all (it's just description + descriptionReferences), it might be cleaner to investigate why the field is being set. But priority pinning is a safe one-line fix in the meantime.

---

## 3. The big finding: 71K dmel alleles missing

### What we have

- chado-db-flybase-dmel loaded **233,414** Dmel allele rows
- Chado `feature` table has **239,366** Dmel-tagged FBal (the source filters out ~6K obsoletes — fine)
- Your `flybase-allele-descriptions` enriches 45,945 of those with description text — perfect

### What FlyBase actually publishes

The precomputed file `fbal_to_fbgn_fb_2026_01.tsv` has **305,332 unique FBal entries**:

```
#	AlleleID	AlleleSymbol	GeneID	GeneSymbol
FBal0137236	gukh[142]	FBgn0026239	gukh
FBal0092786	Ecol\lacZ[T125]	FBgn0014447	Ecol\lacZ
FBal0091321	Ecol\lacZ[kst-01318]	FBgn0014447	Ecol\lacZ
FBal0008067	mam[04615]	FBgn0002643	mam
...
```

305,332 - 239,366 = **65,966 alleles in the precomputed file but NOT in chado's `feature` table for Dmel**.

These are mostly **transgene vector alleles**:
- `Ecol\lacZ[...]` (E. coli β-galactosidase reporter sequences in fly constructs)
- `Scer\GAL4[...]`, `Scer\UAS[...]` (yeast GAL4-UAS system)
- `Avic\GFP[...]` (jellyfish green fluorescent protein)
- `Ppyr\luc[...]` (firefly luciferase)
- `Hsap\*[...]` (human transgenes — Aβ peptide, oncogenes, etc.)

In FlyBase chado they're tagged with the **source organism** (Ecol, Scer, Hsap), not Dmel. But they're alleles **used in Dmel constructs** — fly geneticists need them in a Dmel-relevant search.

For a public FlyMine instance, **these 66K transgene alleles are essential** — every UAS-driver line, every lacZ reporter, every GFP fusion is one of these.

### Cross-check against chado

```sql
SELECT count(DISTINCT uniquename) FROM feature WHERE uniquename LIKE 'FBal%';
-- 322,774 across ALL organisms
```

So chado actually has more total FBals than the precomputed file (322K vs 305K) — chado includes some FBals that aren't current/published. The precomputed file is the **canonical "current Dmel-relevant FBal set"**.

---

## 4. Proposed new source: `flybase-allele-stubs`

Mirror the `flybase-allele-descriptions` pattern. Lean, no model additions, just merges via `Allele.primaryIdentifier`.

### Source wiring (project.xml)

```xml
<source name="flybase-allele-stubs" type="flybase-allele-stubs" version="4.2.0">
  <property name="src.data.dir" location="/root/data/flybase/alleles/aux/current"/>
  <property name="src.data.dir.includes" value="fbal_to_fbgn_*.tsv"/>
</source>
```

(File is already on disk at `/root/data/flybase/alleles/aux/current/fbal_to_fbgn_fb_2026_01.tsv` from this session — Phase 1.5 we moved the non-21-col TSVs to `aux/` to avoid confusing the historical `flybase-alleles` source. Should re-stage cleanly via `extract_data.py` going forward.)

### Converter scope

Per row:
- col 1: `FBal{nnn}` → `Allele.primaryIdentifier`
- col 2: allele symbol (e.g. `Ecol\lacZ[T125]`) → `Allele.symbol`
- col 3: `FBgn{nnn}` → reference to `Gene` via FBgn merge
- col 4: gene symbol (ignored — chado/FBgn already carries it)

Skip header rows (start with `#`).
Skip rows with empty cols (parse failures).
Filename dispatch defense-in-depth (only process `fbal_to_fbgn_*.tsv`).

### Schema additions

**None** — `Allele.primaryIdentifier`, `Allele.symbol`, and `Allele.gene` reverse-reference all already exist in the genomic model.

### keys.properties

```properties
DataSet.key      = name
DataSource.key   = name
Organism.key     = taxonId
Gene.key         = primaryIdentifier
Allele.key       = primaryIdentifier
```

### Expected behavior at integrate

- For ~239K rows where FBal already exists in chado-merged data → no-op (merge, no new attrs set since chado already had them).
- For ~66K rows that don't exist → create new Allele stub (`primaryIdentifier`, `symbol`, `gene` ref, `organism=Dmel`).
- For Gene refs by FBgn → merge with chado's 17,884 Dmel genes via `Gene.primaryIdentifier` key.

Expected final state after this source lands:
- `Allele` count: **234,211 → ~300,000** (depending on overlap with chado)
- No new Gene rows (all FBgn refs merge into chado)
- No DB-size impact beyond ~50 MB of new Allele rows

### genomic_priorities entry

If the new source's Allele items inherit `sequenceOntologyTerm` (same as the lean source), pin chado as the winner:
```properties
Allele.sequenceOntologyTerm = chado-db-flybase-dmel, *
```
(Already in priorities from this session's 2.2 patch — no new entry needed.)

### Tests (mirror the lean source's 2-test pattern)

- `testStubsMergeIntoExistingAlleles` — fixture with FBal already in input + chado-loaded version, assert Allele count doesn't grow
- `testNewStubsCreatedForMissingFBals` — fixture with Ecol\lacZ FBal not in chado, assert new Allele stub stored
- `testHeaderRowsSkipped` — fixture with `#` lines at top
- `testGeneRefByFBgn` — assert `Allele.gene.primaryIdentifier` matches the col-3 FBgn

---

## 5. Side observation: `chado-db-flybase-others` organism filter probably wrong

Your `b536a78d` reads:

```xml
<source name="chado-db-flybase-others" type="chado-db">
  <property name="organisms" value="Dana Dere Dgri Dmoj Dper Dsec Dsim Dvir Dwil Dyak"/>
```

But the InterMine `chado-db` source `organisms` property typically takes **taxon IDs**, not chado abbreviations. With abbreviations it likely matched only 0 organisms — which would explain why multi-species chado only added 797 alleles (from Dpse via `chado-db-flybase-dpse` which uses `7237`) and not the ~3,400 across all non-Dmel Drosophilas.

Suggested fix:
```xml
<property name="organisms" value="7217 7220 7222 7234 7237 7240 7244 7245 7260 32346"/>
```

(Dana, Dere, Dgri, Dmoj, Dper, Dpse, Dsec, Dsim, Dvir, Dwil, Dyak — looking up Dvir = 7244 etc. you may want to double-check the chado `organism` table.)

Verify by checking chado after a re-fire: `SELECT genus, species, count(*) FROM feature WHERE uniquename LIKE 'FBal%' GROUP BY 1, 2` — the count should match what's in chado-pg's organism table.

---

## 6. Phase 2 status summary

✅ Done:
- 23 active sources integrated
- Aim-1 schema additions compiled
- Lean alleles (description + descriptionReferences) delivered
- Multi-species chado partially loaded (Dpse landed)

🟡 Outstanding:
- 66K transgene-vector alleles missing → **new `flybase-allele-stubs` source** (above)
- 10 non-Dmel Drosophila species in `chado-db-flybase-others` may not have loaded → **organisms filter fix** (above)
- Aim-1 converter SQL (carried-alleles, complementation, breakpoints) — chado-team cvterm confirmation still pending per your earlier reply

🔴 Long-term deferred:
- `protein2ipr` / `fly-anatomy-ontology` / `update-publications` — needs upstream InterMine PRs or AGR API key

---

## 7. Cross-references

- Phase 1.5 closeout + Phase 2 plan: `agr_intermine_builder/docs/FLYMINE_PHASE1_5_CLOSEOUT_PHASE2_PLAN_2026_06_03.md`
- Your Phase 2 launch reply: `new_flymine/docs/HANDOFF_TO_BUILDER_PHASE2_LAUNCH_2026-06-03.md`
- Phase 2 commits: `flymine@ba5d93ce..b65c8e90` + `flymine-bio-sources@12152b3..945598d`
- Builder patches (not yet upstreamed):
  - `flybase-allele-descriptions_additions.xml` (Publication.primaryIdentifier)
  - `genomic_priorities.properties` (Allele.sequenceOntologyTerm)

Ready for your next round.
