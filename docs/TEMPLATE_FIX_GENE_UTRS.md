# Gene_UTRs template — yeast returns 0 results

Date: 2026-05-08
Template: `Gene_UTRs` at `default-template-queries.xml:548`
Status: pending decision (Fix A vs Fix B)

## Symptom

`Gene → UTRs` template returns 0 rows for any yeast gene (tested: YHR191C, CDC28). Worked in 8.3.0.

## Data state in rc20

| Check | Count |
|---|---|
| `utr` table total | 54,998 |
| `FivePrimeUTR` instances | 27,499 |
| `ThreePrimeUTR` instances | 27,499 |
| Yeast UTRs via `utr.geneid → gene.id` direct | 35,624 |
| `YHR191C` UTRs via `utr.geneid` direct | 24 |
| `YHR191C` UTRs via `Gene.transcripts.UTRs` path | 0 |

UTR data IS loaded. Gene-UTR linkage exists. Template's traversal path is wrong for this data shape.

## Root cause

Template view path:
```
Gene.transcripts.UTRs.chromosomeLocation.start
Gene.transcripts.UTRs.chromosomeLocation.end
Gene.transcripts.UTRs.primaryIdentifier
Gene.transcripts.UTRs.sequence.residues
```

Requires the `transcript → UTR` reference (column `transcript.UTRs` collection in InterMine model). The `sgd-gff-utr` converter at `alliance-genome/alliancemine-bio-sources/sgd-gff-utr/src/main/java/org/intermine/bio/dataconversion/SgdGffUtrConverter.java` writes UTR Items with `gene` reference set but does NOT call `setReference("transcript", mrnaItem)`. Result: UTR is reachable from Gene direct (`Gene.UTRs`) but not via `Gene.transcripts.UTRs`.

8.3.0 worked because that release had a different UTR loader chain (the `sgd-utr` source via the now-replaced `agr_intermine_data_extractor`) which DID wire transcripts.

Additional issue in current template:
```xml
<constraint path="Gene.transcripts.dataSets.name" code="C"
            editable="false" op="=" value="SGD data set"/>
```
DB shows yeast UTR datasets named `SGD UTRs from DB` and `SGD UTRs from GFF`, not `SGD data set`. So even if transcript-UTR edge existed, this constraint would zero out the result.

## Fix A — rewrite template path (XML only, no rebuild)

Edit `default-template-queries.xml:548-555`. Replace path `Gene.transcripts.UTRs.*` with `Gene.UTRs.*` and drop the `dataSets.name` constraint.

Before:
```xml
<template name="Gene_UTRs" title="Gene --&gt; UTRs" comment="" ...>
    <query name="Gene_UTRs" model="genomic"
           view="Gene.secondaryIdentifier Gene.transcripts.primaryIdentifier
                 Gene.transcripts.chromosome.primaryIdentifier
                 Gene.transcripts.UTRs.chromosomeLocation.start
                 Gene.transcripts.UTRs.chromosomeLocation.end
                 Gene.chromosomeLocation.strand
                 Gene.transcripts.UTRs.primaryIdentifier
                 Gene.transcripts.UTRs.sequence.residues
                 Gene.transcripts.in_gal Gene.transcripts.in_ypd"
           ... constraintLogic="A and B and C">
        <constraint path="Gene.transcripts" editable="false" type="MRNA"/>
        <constraint path="Gene.organism.shortName" code="B" editable="false"
                    op="=" value="S. cerevisiae"/>
        <constraint path="Gene.transcripts.dataSets.name" code="C"
                    editable="false" op="=" value="SGD data set"/>
        <constraint path="Gene" code="A" editable="true"
                    op="LOOKUP" value="YHR191C"/>
    </query>
</template>
```

After:
```xml
<template name="Gene_UTRs" title="Gene --&gt; UTRs" comment="" ...>
    <query name="Gene_UTRs" model="genomic"
           view="Gene.primaryIdentifier Gene.secondaryIdentifier Gene.symbol
                 Gene.chromosome.primaryIdentifier
                 Gene.UTRs.chromosomeLocation.start
                 Gene.UTRs.chromosomeLocation.end
                 Gene.chromosomeLocation.strand
                 Gene.UTRs.primaryIdentifier
                 Gene.UTRs.sequence.residues"
           sortOrder="Gene.UTRs.primaryIdentifier asc"
           constraintLogic="A and B">
        <constraint path="Gene.organism.shortName" code="B" editable="false"
                    op="=" value="S. cerevisiae"/>
        <constraint path="Gene" code="A" editable="true"
                    op="LOOKUP" value="YHR191C"/>
    </query>
</template>
```

Lost columns vs original: `Gene.transcripts.in_gal` and `Gene.transcripts.in_ypd` (yeast-specific transcript expression flags from Pelechano 2013). These are MRNA-level attributes not transferable to UTR-direct path — would need a separate column or the template stays at gene level.

Cost: WAR rebuild + redeploy (~5 min). No data rebuild.
Risk: low. Path `Gene.UTRs` is a standard InterMine collection populated when any UTR Item references gene.

## Fix B — fix the converter (rebuild required)

Edit upstream `alliance-genome/alliancemine-bio-sources/sgd-gff-utr/src/main/java/org/intermine/bio/dataconversion/SgdGffUtrConverter.java`. In the per-feature loop where the UTR Item is created, after the existing `setReference("gene", geneItem)` call add:

```java
Item mrna = getOrCreateMRNA(transcriptId, geneItem);
utrItem.setReference("transcript", mrna);
```

Where `getOrCreateMRNA` resolves the MRNA Item that this UTR belongs to (via parent feature ID in the GFF, or by looking up gene → primary transcript).

Cost: source code change + rerun `sgd-gff-utr` integrate (~10 min) + UTR-related postprocess + WAR rebuild + redeploy.
Risk: medium. Requires deciding which transcript a UTR belongs to when multiple isoforms exist; may not be 1:1.

Long-term correct fix. PR upstream.

## Fix C — both

Apply Fix A now to unblock users. Open issue + PR for Fix B at `alliance-genome/alliancemine-bio-sources` to land in the next release. Once Fix B lands, optionally restore the original template path so transcript-level fields (`in_gal`, `in_ypd`) come back.

## Recommendation

Tonight: **Fix A**. Restores rc20 functionality with one XML edit. Loses two transcript-level columns nobody is currently looking at (yeast tooltips for transcript abundance under galactose / YPD media; Pelechano 2013 dataset).

Defer Fix B to next sprint via upstream PR.

## Verification

After Fix A + WAR redeploy:

```bash
curl -s 'http://172.31.59.87:8086/alliancemine/service/template/results?name=Gene_UTRs&constraint1=Gene&op1=LOOKUP&value1=YHR191C&format=tsv' | wc -l
```
Expect: 24+ rows (header + 24 UTR rows for YHR191C).

## Related files

- `default-template-queries.xml:548` — the template
- `alliance-genome/alliancemine-bio-sources/sgd-gff-utr/` — converter (Fix B)
- `docs/TEMPLATE_DESIGN_MULTIMOD_DISCUSSION.md` — broader design issue (Gene_UTRs is yeast-only path, not multi-MOD)
