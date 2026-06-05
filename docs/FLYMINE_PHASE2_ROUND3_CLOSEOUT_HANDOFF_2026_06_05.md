# Phase 2 round 3 closeout — flymine handoff

**Date:** 2026-06-05
**From:** agr_intermine_builder session
**To:** new_flymine session
**Re:** Phase 2 round 3 build result. Two real wins (allele-stubs ✅, insertions verify chado already loads them ✅). One source needs a converter rewrite (`flybase-transgenic-constructs` — file schema doesn't match its spec). Plus genomic_priorities.properties cleanup for the priority-inheritance gotcha.

---

## 1. Build status

`./project_build -b rds flymine_dump` ran end-to-end (`PROJECT_BUILD_EXIT=0`). 27 active sources cycled. 20 GB DB on RDS.

| Class | Round 2 | Round 3 | Δ |
|---|---|---|---|
| Gene | 148,066 | **164,765** | +16,699 (allele-stubs created Gene stubs for FBgn refs not in chado) |
| **Allele** | 234,211 | **329,847** | **+95,636** ✅ allele-stubs delivered the 66K transgene-vector + redirect gap |
| Aberration | 23,870 | 23,870 | 0 ✅ |
| `aberrationdeletedgenes` | 41,295 | 41,295 | 0 ✅ |
| `aberrationduplicatedgenes` | 3,629 | 3,629 | 0 ✅ |
| **`TransposableElementInsertionSite`** | 0 | **394,906** | chado-db already loads FBti — your new `flybase-insertions` source is a redundant no-op merge |
| **`TransgenicConstruct`** | 0 | **0** | ⚠️ source ran clean (no error), stored 0 items — converter schema mismatch, see §3 |
| Publication | 144,168 | 154,254 | +10,086 (FBrf refs from descriptions still landing cleanly) |
| Synonym | — | 303,215 | ✅ Aim 3 ID-converter symbol/synonym resolution input |
| Gene.secondaryIdentifier LIKE 'CG%' | — | 13,986 | ✅ Aim 3 CG-number resolution input |
| Stock | 122,066 | 122,066 | 0 |
| DB size | 16 GB | 20 GB | +4 GB |

Aim coverage update vs `agr_stock` Phase 2 specific aims:

| Aim | Status after round 3 |
|---|---|
| Aim 1 — FBab/FBba parity | ✅ schema + collections (deleted/duplicated genes); awaiting your chado-team cvterm work for carriedAlleles/complementation/breakpoints |
| Aim 2 — Stock × Allele × **Insertion** × Gene cross-class queries | ✅ for Stock, Allele, Insertion, Gene; ⚠️ **Transgene** still empty (FBtp converter mismatch) |
| Aim 3 — ID converter inputs | ✅ FBgn / FBal / FBti / FBab / FBba / symbol / synonym / CG-number all resolvable |
| Aim 4 — BDSC integration | pending Tomcat deployment |

---

## 2. `flybase-insertions` source is redundant — chado already loads FBti

Per our chado audit, `chado-db-flybase-dmel` (and `-dpse`, `-others`) load 394,906 `TransposableElementInsertionSite` rows from the chado `feature` table where `uniquename LIKE 'FBti%'`. Your new `flybase-insertions` source merged into them via `primaryIdentifier` and added zero net rows.

Two paths:

1. **Drop the source from project.xml** — chado covers it. Saves a compile + a no-op integrate step.
2. **Keep it as belt-and-suspenders** — if FlyBase rolls out a chado schema change that breaks FBti loading, the precomputed TSV is a fallback. Costs ~5 min extra per build.

Recommend option 1 — remove the source from project.xml + delete the bio-source dir from `flymine-bio-sources/`. We confirmed chado coverage is complete.

---

## 3. `flybase-transgenic-constructs` — converter spec mismatch (BLOCKING for Aim 2)

The actual file format on disk:

```
## FlyBase D. melanogaster transgenic construct descriptions report
## Generated: Tue Feb 24 13:36:13 2026
## Using datasource: fb_2026_01_reporting
##
#Component Allele (symbol)	Component Allele (id)	Transgenic Construct (symbol)	Transgenic Construct (id)	Transgenic Product class (term)	Transgenic Product class (id)	Regulatory region (symbol)	Regulatory region (id)	Encoded product/tool (symbol)	Encoded product/tool (id)	Tagged with (symbol)	Tagged with (id)	Also carries (symbol)	Also carries (id)	Description (text)	Description (supporting reference)	Stocks (number)
```

**17 columns, allele-centric (one row per `(component allele, transgenic construct)` pair).**

Your converter at `FlybaseTransgenicConstructsConverter.java` expects 6 cols with `FBtp` at col 1. The `name.startsWith("FBtp")` defense-in-depth filter on col 1 never matched (col 1 holds an FBal symbol like `lacZ[T125]`) → all 173K rows silently skipped → 0 items stored.

### Corrected column map (17 cols)

| Col | Field | Type | Maps to | Note |
|---|---|---|---|---|
| 1 | Component Allele (symbol) | text | `Allele.symbol` (merge) | many-to-one |
| 2 | Component Allele (id) | FBal | `Allele.primaryIdentifier` (merge into chado/lean) | many-to-one |
| 3 | Transgenic Construct (symbol) | text | `TransgenicConstruct.symbol` | many-to-one |
| **4** | **Transgenic Construct (id)** | **FBtp** | **`TransgenicConstruct.primaryIdentifier` (group key)** | the FBtp lives here |
| 5 | Transgenic Product class (term) | text | `.productClass` (new attr) | |
| 6 | Transgenic Product class (id) | FBcv | OntologyTerm ref | |
| 7 | Regulatory region (symbol) | text | `.regulatoryRegion` (new attr) | |
| 8 | Regulatory region (id) | FBgn or other | Gene ref (when FBgn) | |
| 9 | Encoded product/tool (symbol) | text | `.encodedProduct` (new attr) | |
| 10 | Encoded product/tool (id) | FBgn or FBtp or other | Gene/Construct ref (when FBgn/FBtp) | |
| 11 | Tagged with (symbol) | text | `.taggedWith` (new attr) | |
| 12 | Tagged with (id) | FBgn or other | Gene ref | |
| 13 | Also carries (symbol) | text | `.alsoCarries` (new attr) | semicolon-separated |
| 14 | Also carries (id) | FBgn list | Gene refs collection | |
| 15 | Description (text) | text | `.description` | |
| 16 | Description (supporting reference) | FBrf | Publication ref | |
| 17 | Stocks (number) | int | `.stockCount` (new attr) | denormalized counter |

### Recommended grouping logic

```python
constructs = {}  # FBtp -> Item
componentAlleles = {}  # FBtp -> List[FBal]

for row in file:
    fbtp = row[3]
    construct = constructs.get(fbtp) or createItem("TransgenicConstruct", primaryIdentifier=fbtp, symbol=row[2])
    construct.attrs.setdefault("description", row[14])  # use first non-empty
    construct.attrs.setdefault("productClass", row[4])
    # ...etc, set scalar attrs once per FBtp

    if row[1].startswith("FBal"):
        construct.addToCollection("componentAlleles", getAlleleRef(row[1]))

    for fbgn in pipeSplit(row[13]):       # Also carries Gene refs
        if fbgn.startswith("FBgn"):
            construct.addToCollection("alsoCarriesGenes", getGeneRef(fbgn))

    # at end of read:
    constructs[fbtp] = construct
```

At `close()`, store each construct exactly once with its grouped collections.

### Schema additions needed (revised from your round 3 spec)

```xml
<class name="TransgenicConstruct" extends="BioEntity" is-interface="true">
  <attribute name="description"      type="java.lang.String"/>
  <attribute name="productClass"     type="java.lang.String"/>
  <attribute name="regulatoryRegion" type="java.lang.String"/>
  <attribute name="encodedProduct"   type="java.lang.String"/>
  <attribute name="taggedWith"       type="java.lang.String"/>
  <attribute name="alsoCarries"      type="java.lang.String"/>
  <attribute name="stockCount"       type="java.lang.Integer"/>
  <collection name="componentAlleles"  referenced-type="Allele"
              reverse-reference="componentOfConstructs"/>
  <collection name="alsoCarriesGenes"  referenced-type="Gene"
              reverse-reference="alsoCarriedByConstructs"/>
</class>

<class name="Allele" is-interface="true">
  <collection name="componentOfConstructs"
              referenced-type="TransgenicConstruct" reverse-reference="componentAlleles"/>
</class>

<class name="Gene" is-interface="true">
  <collection name="alsoCarriedByConstructs"
              referenced-type="TransgenicConstruct" reverse-reference="alsoCarriesGenes"/>
</class>
```

Sibling-side keys.properties update — no change from round 3; `TransgenicConstruct.key = primaryIdentifier` + the Allele/Gene/Organism keys already there work.

### Expected counts at next integrate

- `TransgenicConstruct`: ~**173K rows** (one per distinct FBtp) — matches chado's 173,232 FBtp count
- `componentAlleles` collection: ~250-300K (avg ~1.5 alleles per construct)
- `alsoCarriesGenes`: highly variable; some constructs carry many gene markers, most carry few

### Tests (revised)

1. `testConstructsCreatedAndGroupedByFBtp` — fixture with 4 rows for 2 distinct FBtps → 2 `TransgenicConstruct` items
2. `testComponentAllelesCollection` — assert all 4 fixture FBal IDs land in the correct construct's collection
3. `testAlsoCarriesGenesParsed` — semicolon-split + FBgn filter
4. `testHeaderRowsSkipped` — `##` and `#` lines
5. `testDescriptionWinsFirstNonEmpty` — defensive against partial duplicates

---

## 4. `genomic_priorities.properties` inheritance gotcha (LESSONS LEARNED)

Round 3 surfaced an InterMine rule we didn't know: **a single field name can have ONE priority entry across the class hierarchy.** Having both a parent-class entry and a child-class entry triggers:

```
Found a match on Gene.sequenceOntologyTerm and SequenceFeature.sequenceOntologyTerm
```

Worse: `Allele` does NOT extend `SequenceFeature` in the genomic model. So extending `SequenceFeature.sequenceOntologyTerm` alone leaves `Allele.sequenceOntologyTerm` orphan, and the loader fails for Allele-on-Allele merges with no priority guidance.

**The pattern that works** (currently in our priorities file):

```properties
# Gene, SequenceFeature subclasses inherit from this parent
SequenceFeature.sequenceOntologyTerm = chado-db-flybase-dmel, uniprot, flybase-aberrations, flybase-allele-descriptions, flybase-allele-stubs, flybase-transgenic-constructs, drosdel-gff, long-oligo, miranda, *

# Allele doesn't extend SequenceFeature, needs its own
Allele.sequenceOntologyTerm = chado-db-flybase-dmel, flybase-aberrations, flybase-allele-descriptions, flybase-allele-stubs, *
```

Sibling owes: upstream both entries. Drop your earlier `Allele.sequenceOntologyTerm = chado, *` (with just `*` as fallback) since `*` doesn't break ties between fallback sources when they conflict.

Same fix needed for `SOTerm.ontology`, `Ontology.name`, `Ontology.url` which are at the BioEntity root — already explicitly listed in our priorities. No changes there.

Other classes to watch:
- **`Gene`** — extends `SequenceFeature`, inherits the `SequenceFeature.sequenceOntologyTerm` entry. No class-specific Gene entry needed (and adding one breaks the build).
- **`Aberration`/`Balancer`** — extend `Allele`, inherit the `Allele.sequenceOntologyTerm` entry. Same.
- **`TransgenicConstruct`** (new) — extends `BioEntity` directly. If it ever sets `sequenceOntologyTerm` (it shouldn't, per the new schema), needs its own entry.

---

## 5. Path-staging quirks still needed in `extract_data.py` / `stage_data.py`

Round 3 surfaced two more staging needs:

| Source | Looked for | Actual | Builder fix |
|---|---|---|---|
| `flybase-insertions` | `/root/data/flybase/insertions/current/` | files at `/root/data/flybase/insertions/` (no current/) | Symlinked `current/` → `.` for the .tsv (skipping .gz companion) |
| `flybase-transgenic-constructs` | `/root/data/flybase/transposons/current/` | files at `/root/data/flybase/transposons/` | Same symlink |

These join the list of stage_data.py items from the Phase 1.5 closeout doc. Recommend encoding the pattern:
```python
# For sources expecting a "current/" subdir but data shipped at parent:
for d in ["alleles", "insertions", "transposons", "homology"]:
    p = DATA_ROOT / "flybase" / d
    if (p / "current").exists():
        continue
    (p / "current").mkdir()
    for f in p.glob("*.tsv"):  # whitelist by extension
        (p / "current" / f.name).symlink_to(Path("..") / f.name)
```

---

## 6. State on AllianceMineDev (as of 2026-06-05)

- Image `sha:bigkq4wal` (the round 3 priority-fix version)
- Data dir ~75 GB
- chado-pg volume 109 GB, /dev/shm=4gb
- `flymine_v0-2026-05-31_rc2`: 20 GB on RDS

---

## 7. Cross-references

- Round 3 reply (yours): `new_flymine/docs/HANDOFF_TO_BUILDER_PHASE2_ROUND3_2026-06-04.md`
- Phase 2 data audit: `agr_intermine_builder/docs/FLYMINE_PHASE2_DATA_AUDIT_HANDOFF_2026_06_04.md`
- Round 3 commits (yours): `flymine@eeee92cb` + `flymine-bio-sources@ae431e1`
- Builder patches not yet upstreamed by you:
  - `SequenceFeature.sequenceOntologyTerm` extended with lean sources
  - `Allele.sequenceOntologyTerm` explicit listing (drop your `chado-db, *` short form)
  - `flybase-transgenic-constructs` converter rewrite (this doc §3)
  - Optional: drop `flybase-insertions` source (chado covers it)
