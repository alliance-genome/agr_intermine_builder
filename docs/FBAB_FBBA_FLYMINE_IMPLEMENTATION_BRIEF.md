# FBab / FBba in FlyMine — implementation brief for the new_flymine session

Date: 2026-05-28
Audience: the Claude Code session working in `~/Projects/alliance/new_flymine/`
(the side-by-side `flymine` + `flymine-bio-sources` checkouts).
Status: design approved; ready to implement.

This is a hand-off brief. The design was settled in the agr_intermine_builder
session; you (new_flymine session) own the implementation in the flymine
repos. Read this top to bottom before touching code. Coordination rules at
the end.

## Goal (from the spec)

Extend the AGR allele schema for FlyBase aberrations (FBab) and balancers
(FBba); ingest the FlyBase bulk dumps via a dedicated loader; publish
FBab/FBba entity pages at FlyBase parity. A curated FBba→FBab equivalence
table lands first (week 1) to unblock the Phase 1 parser while full ingest
is staged.

This work targets the **slim FlyMine** build (Path 2 in
`docs/FLYMINE_SOURCE_TO_DATA_MAP.md`), which loads fly genome features from
`GFF_FB.gff` (Alliance FMS) rather than the historic chado-db sources.

## Data sources (verified 2026-05-28 against FlyBase release FB2026_01)

FlyBase S3 FTP base: `https://s3ftp.flybase.org/releases/FB2026_01/precomputed_files/`
(the old `ftp.flybase.net` host is slow/timing out — use the s3ftp host).

| File | Provides | Scale |
|---|---|---|
| `synonyms/fb_synonym_fb_2026_01.tsv.gz` | FBab + FBba identity: primary id, organism (Dmel), current symbol, fullname, synonyms | 23,870 FBab rows + 642 FBba rows |
| `aberrations/aberration_experimental_gene_del_dup_data.fb_2026_01.tsv.gz` | gene↔FBab deletion/duplication relationships | 74,619 rows / 9,937 distinct FBab |
| `map_conversion/cyto-genetic-seq.tsv.gz` | cytogenetic→sequence coords (later phase, for breakpoints) | — |
| **curated `fbba_to_fbab.tsv`** | FBba balancer → constituent FBab inversion(s). **NOT published by FlyBase** — hand-curated, lands week 1 | 642 balancers |

### aberration_experimental_gene_del_dup_data columns

```
gene_id          FBgn#  (current FlyBase gene id)
gene_symbol      current gene symbol
type             one of: completely/partially deleted/disrupted (complementation|molecular),
                 not deleted/disrupted, completely/partially duplicated (complementation|molecular),
                 not duplicated
aberration_id    FBab#
aberration_symbol  e.g. Df(2R)min, In(2LR)a[M60], Dp(...)
references       pipe-separated FBrf# (may be empty)
```

Sample:
```
FBgn0000008  a  completely deleted (molecular)  FBab0038016  Df(2R)Exel6078  FBrf0184335
FBgn0000002  5SrRNA  completely deleted/disrupted (complementation)  FBab0022274  Df(2R)min
```

Note: only `completely/partially deleted/disrupted` and `…duplicated` rows
create real relationships. The `not deleted/not duplicated` rows are negative
results — Phase 1 should skip them (or store as a separate "tested-negative"
collection if a curator wants them; default = skip).

### fb_synonym columns (relevant subset)

```
##primary_FBid  organism_abbreviation  current_symbol  current_fullname  fullname_synonym(s)  symbol_synonym(s)
FBab0000001  Dmel  Df(2R)03072  (blank)  (blank)  Df03072
FBba0000001  Dmel  CyO-Df(2R)B80
FBba0000002  Dmel  FM3  First Multiple 3
```

Filter to rows whose primary id starts with `FBab` or `FBba`.

### Aberration type from symbol prefix

The aberration class is encoded in the symbol, not a column:

| Prefix | Type | aberrationType value |
|---|---|---|
| `Df(` | Deficiency / deletion | `deletion` |
| `Dp(` | Duplication | `duplication` |
| `In(` | Inversion | `inversion` |
| `T(` | Translocation | `translocation` |

Parse with a regex on `aberration_symbol` / `current_symbol`. Default unknown
prefixes to `other`.

## Schema additions

Add to `flymine-bio-sources/<source>/src/main/resources/<source>_additions.xml`
(the new source's additions file — see Loader section). Two subclasses of the
existing genomic-model `Allele` class:

```xml
<class name="Aberration" extends="Allele" is-interface="true">
  <attribute name="aberrationType" type="java.lang.String"/>   <!-- deletion|duplication|inversion|translocation|other -->
  <collection name="deletedGenes"    referenced-type="Gene"/>
  <collection name="duplicatedGenes" referenced-type="Gene"/>
  <collection name="breakpoints"     referenced-type="Location"/>   <!-- phase 2; empty in phase 1 -->
</class>

<class name="Balancer" extends="Allele" is-interface="true">
  <collection name="composedOfAberrations" referenced-type="Aberration"/>
  <attribute  name="balancedChromosome" type="java.lang.String"/>   <!-- optional; from curated table or symbol -->
</class>
```

Reverse references on Gene (so a gene's report page lists aberrations that
delete/duplicate it — needed for FlyBase parity on the *gene* page too):

```xml
<class name="Gene" is-interface="true">
  <collection name="deletedByAberrations"    referenced-type="Aberration" reverse-reference="deletedGenes"/>
  <collection name="duplicatedByAberrations" referenced-type="Aberration" reverse-reference="duplicatedGenes"/>
</class>
```

Inherited from `Allele` (do NOT redeclare): `primaryIdentifier`, `symbol`,
`name`, `organism`, `synonyms`, `crossReferences`, `dataSets`. Confirm the
current FlyMine genomic model `Allele` actually has these before relying on
them — check `flymine/dbmodel/` generated model or
`alliancemine-bio-sources` genomic_additions for the canonical Allele shape.

## Loader — new `flybase-aberrations` bio-source

Do NOT extend alliance-alleles. That converter reads Alliance JSON; this is
FlyBase TSV. A dedicated source keeps both parsers clean.

```
flymine-bio-sources/flybase-aberrations/
├── build.gradle                       (copy a sibling bio-source's build.gradle)
└── src/main/
    ├── resources/
    │   └── flybase-aberrations_additions.xml   (the schema above)
    └── java/org/intermine/bio/dataconversion/
        └── FlybaseAberrationsConverter.java
```

Converter logic (FileConverter, processes a directory of the 3 input files):

1. Parse `fb_synonym_*.tsv` → for each FBab row create an `Aberration` item
   (primaryIdentifier=FBab#, symbol=current_symbol, organism=Dmel taxon 7227,
   aberrationType from symbol prefix); for each FBba row create a `Balancer`
   item. Stash a `Map<String,Item>` keyed by FB id for relationship wiring.
2. Parse `aberration_experimental_gene_del_dup_data.tsv` → for each
   deleted/disrupted row add the Gene (resolve/create by FBgn) to the
   Aberration's `deletedGenes`; for each duplicated row → `duplicatedGenes`.
   Skip `not deleted` / `not duplicated` rows. Attach references (FBrf#) as
   publications if FlyMine loads pubs (optional phase 1).
3. Parse curated `fbba_to_fbab.tsv` → for each row add the referenced
   Aberration(s) to the Balancer's `composedOfAberrations`.

Gene resolution: use the IdResolver / the genes already loaded by the
GFF_FB source. Aberrations must integrate AFTER genes in project.xml.

project.xml source block (add to the slim flymine project.xml):

```xml
<source name="flybase-aberrations" type="flybase-aberrations">
  <property name="src.data.dir" location="/root/data/flybase/aberrations"/>
</source>
```

Place it after the gene/genome sources, before postprocess.

## Curated FBba→FBab table (week 1, the unblocker)

Format — minimal TSV, lives in the flymine-bio-sources repo (or the data dir):

```
#fbba_id   fbba_symbol   fbab_ids (pipe-separated)   note
FBba0000002  FM3   FBab0000xxx|FBab0000yyy   First Multiple 3 balancer
FBba0000003  FM6   FBab...                   
```

Bootstrapping the 642 balancers: most classic balancers (FM6, FM7, CyO, SM5,
SM6, TM3, TM6, TM6B, …) are inversions whose constituent FBab inversions are
documented in FlyBase reports + the literature. A curator seeds the high-use
balancers first; the long tail can be empty (Balancer object still created
from synonyms, just with no `composedOfAberrations`). The Phase 1 parser must
tolerate balancers with zero mapped aberrations.

## Phasing

| Phase | Deliverable | Blocks |
|---|---|---|
| Week 1 | `fbba_to_fbab.tsv` curated seed (high-use balancers) committed to repo | unblocks Phase 1 |
| Phase 1 | schema additions + FlybaseAberrationsConverter + project.xml source; ingest FBab (identity + gene del/dup) + FBba (identity + curated composition) | first integrate |
| Phase 2 | breakpoints from cyto-genetic-seq; richer aberration metadata; FBrf publications; negative-result collection if wanted | later |
| Entity pages | Aberration/Balancer report displayers at FlyBase parity (inherit Allele page + type-specific blocks) | after Phase 1 data loads |

## Entity pages (FlyBase parity)

Aberration + Balancer inherit the Allele report page automatically (they're
Allele subclasses). Add webconfig-model.xml displayer blocks:

- Aberration: a "Deleted genes" table + "Duplicated genes" table +
  aberrationType + references. Matches the gene-affected tables on a FlyBase
  FBab report.
- Balancer: a "Composed of aberrations" list + balancedChromosome. Matches
  the FlyBase FBba report.
- Gene page: add "Aberrations that delete/duplicate this gene" inline list
  (uses the reverse references).

"Parity" scope for Phase 1 = the fields sourced from the dumps above (symbol,
type, affected genes, composition, references). Cytogenetic breakpoint maps
are Phase 2.

## Coordination with the agr_intermine_builder session

| Resource | Who owns it |
|---|---|
| `flymine-bio-sources/flybase-aberrations/` (new source) | YOU (new_flymine session) |
| flymine `project.xml` slim source list | YOU — but the GFF_FB.gff genome-feature source wiring is shared design; check `docs/FLYMINE_SOURCE_TO_DATA_MAP.md` Path 2 |
| schema additions XML | YOU |
| webconfig-model.xml displayers | YOU |
| `fbba_to_fbab.tsv` curated table | a curator seeds it; YOU consume it. Commit a stub with header + a few known balancers so the parser has something to read |
| Docker build pipeline (`docker/flymine/`), RDS, AWS, prod containers | agr_intermine_builder session — do NOT touch. Ask via the user. |
| This brief | agr_intermine_builder session wrote it; if it needs changes, ask via the user |

When you have the converter compiling + one integrate of flybase-aberrations
producing non-zero Aberration + Balancer counts, report back (via the user)
with: the row counts, any schema surprises, and whether the curated table
format worked. The agr_intermine_builder session will fold the source into
the Docker pipeline + the FLYMINE_SOURCE_TO_DATA_MAP Path-2 build.

## Verification targets (Phase 1 done when)

```bash
# After integrate -Psource=flybase-aberrations against the flymine DB:
SELECT count(*) FROM aberration;   -- expect ~23,870 (all FBab from synonyms)
SELECT count(*) FROM balancer;     -- expect ~642 (all FBba from synonyms)
SELECT count(*) FROM aberrationdeletedgenes;     -- thousands (from del/dup file)
SELECT count(*) FROM balancercomposedofaberrations;  -- = curated table rows
SELECT aberrationtype, count(*) FROM aberration GROUP BY 1;  -- Df/Dp/In/T split
```

Report pages: an FBab report (e.g. Df(2R)min / FBab0022274) shows its deleted
genes; an FBba report (e.g. FM6) shows its constituent aberrations.

## Cross-references

- `docs/FLYMINE_SOURCE_TO_DATA_MAP.md` — the slim FlyMine (Path 2) data plan this fits into
- `docs/SIBLING_SESSION_DOCKER_BUILD.md` — how the new_flymine session uses the Docker pipeline + JCenter/bintray traps
- FlyBase FBab report example: `https://flybase.org/reports/FBab0022274`
- FlyBase FBba report example: `https://flybase.org/reports/FBba0000003`
- FlyBase data source: `https://s3ftp.flybase.org/releases/FB2026_01/precomputed_files/`
