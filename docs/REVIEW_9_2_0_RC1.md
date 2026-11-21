# AllianceMine 9.2.0 rc1 review (2026-10-20)

Scope: the three im2 branches (alliancemine `im2-model-links` 4d5b737, alliancemine-bio-sources
`im2-model-links` cab200b, agr_intermine_builder `im2-layout-tools` db0e572) and the rc1 data on the
test webapp 172.31.59.87:8089, compared with live 9.1.0 on :8086 through the web service only.
10 reviewers (8 code areas, 2 data probes), 2 adversarial verifiers per area, 1 synthesis:
129 raw findings, 35 ranked items, 2 refuted at verification.

rc1 predates alliancemine PR #14 and bio-sources PRs #5 and #6, so every data count below describes
the rc1 build and needs the rc2 build to confirm the fix.

## Ranked items

| # | Sev | Item | Repo | Action |
|---|---|---|---|---|
| 1 | blocker | Genes created without organism by 3 converters merge on primaryIdentifier alone: 115,323 Allele.gene and 126,449 Homologue.gene references dangle | bio-sources | PR #5 already; reload from the checkpoint before alliance-disease-models |
| 2 | blocker | Image defaults to the `alliancemine-9.2.0.im2` branches, 15 and 17 commits behind `im2-model-links` | builder | PR #27 |
| 3 | blocker | Items mutated after store(): 460,565 DiseaseEvidence orphaned, 0 of 232,467 Samples with characteristics, DataSet.publication 0 | bio-sources | PR #10 |
| 4 | high | Solr preflight cannot run: no openssh-client, `/usr/local/bin/ssh` wrapper shadows real ssh | builder | PR #27 |
| 5 | high | alliance-disease-detail keys DiseaseAnnotation on uniqueId, alliance-disease on subject+term: 440,654 extra annotations | bio-sources | owner decision |
| 6 | high | allele-detail and mouse-strains create alleleId-only Alleles: 37,984 without primaryIdentifier, 22,385 SGD alleles twice | bio-sources | PR #8, alliancemine #16 |
| 7 | high | SGD GFF and UTR features under taxon 4932 while genes are 559292: Gene_UTRs returns 0 | bio-sources + alliancemine | PRs #7, alliancemine #15 |
| 8 | high | SgdConverter caches sequence per locus: every CDS, intron and exon stores the gene sequence | bio-sources | PR #7 |
| 9 | high | Zebrafish and Xenopus proteins have no gene: upstream `uniprot_config.properties` lacks gene-designation for 7955, 8364, 8355 | builder | open, see below |
| 10 | high | WormMine RNAi creates unprefixed WBGene and WBStrain stubs (5,204 twins) | bio-sources | PR #9 |
| 11 | high | Publication stubs: 319,686 copies of MGI:6194238, 48,604 with ':' in pubMedId | bio-sources | PR #9, alliancemine #16 |
| 12 | high | Yeast proteins duplicated: SGD proteins on 559292 without accession, UniProt yeast on 4932 | bio-sources + alliancemine | owner decision |
| 13 | high | Interactions attached to participant1 only; direction random | bio-sources | PR #9 |
| 14 | high | AlphaFold, STRING and ChEMBL create 121,348 Protein stubs; STRING picks TrEMBL aliases | bio-sources | PR #12 |
| 15 | high | Fetchers leave partial or stale TSVs with exit 0 | bio-sources | PR #13 |
| 16 | medium | HTTP cache keyed by URL only, so rc2 reuses rc1 payloads | bio-sources | PR #13 |
| 17 | high | alliance-disease passes annType as inferredFrom; DoTermToGene has equals without hashCode | bio-sources | PR #10 |
| 18 | high | DiseaseModel.disease NULL on all 1,060,800 rc1 rows; dedupe key collapses genes | bio-sources | PR #10 (fetcher), key is an owner decision |
| 19 | medium | Alliance yeast interactions duplicate BioGRID/SGD (870,203 details) | alliancemine | owner decision |
| 20 | medium | SGD alleles without organism; transgenic alleles write gene instead of targetGenes | bio-sources + alliancemine | PRs #8, alliancemine #15 |
| 21 | medium | Gene_Orthologs default gene has no Alliance orthologs | alliancemine | PR #15 |
| 22 | medium | 5 public templates use SequenceFeature.description (not in model) | alliancemine | PR #15 |
| 23 | medium | Reactome enrichment filter name and precompute path wrong; class_keys typos | alliancemine | PR #15 |
| 24 | medium | MP, PATO, ChEBI terms load without names (hpo, mpo, pato sources off) | alliancemine | owner decision |
| 25 | medium | AllianceGenes: Chromosome 'null' (48,102 genes), length off by one, mixed strand | bio-sources | PR #11 |
| 26 | medium | Xenbase cross-refs dropped, GO evidence dropped, CGOB rows skipped, Homologue.type empty | bio-sources | PR #11 |
| 27 | medium | 9 converters still create organism-less Genes | bio-sources | PR #11 |
| 28 | medium | Worm RNAi attributes empty, HTP field mapping wrong | bio-sources | owner decision |
| 29 | medium | entrypoint swallows psql errors, no databaseName check before buildDB | builder | PR #27 |
| 30 | medium | Flat-file cache checks existence only; release checked after download | builder | PR #28 |
| 31 | medium | Download checks cannot fail on lost rows; compile_check prints OK on error | builder | PRs #28, #26 |
| 32 | low | Compose does not forward env toggles; default passwords unguarded | builder | PR #27 |
| 33 | low | Cosmetic: data set names, nameless organisms, empty synonyms | bio-sources | PR #11 |
| 34 | low | Latent: hard-coded header skips, UTR length, priority names | bio-sources + alliancemine | PRs #7, #15 (part) |
| 35 | low | Logo URL, missing webconfig classes, docs | alliancemine | PR #15 |

## Pull requests

alliancemine (base `im2-model-links`): #15 config and templates; #16 class keys (stacked on #15).
alliancemine-bio-sources (base `im2-model-links`): #7 SGD taxon and sequences; #8 allele identity;
#9 worm RNAi, publications, interactions; #10 store order and disease evidence; #11 gene converters;
#12 protein stubs and STRING; #13 fetchers. Merge #13 last; it conflicts with #9, #10 and #12 in
`scripts/common.py`, `fetch_disease_models.py` and `fetch_interactions.py` and needs a rebase then.
agr_intermine_builder (base `alliancemine-9.2.0.im2`): #26 layout tools; #27 branch defaults, ssh,
builddb safety; #28 cache, release gate, checks. The three merge together without conflict.

Every Java change compiled in `eclipse-temurin:8-jdk` with gradle 4.9 (`-x buildUnitTestDB`); unit
tests ran where the module has a test class. Builder tests: 66 pass. Fetcher tests: 26 pass.

## Owner decisions

1. Item 5: one DiseaseAnnotation key for alliance-disease and alliance-disease-detail, or drop one feed.
2. Item 12: yeast UniProt under 4932 or 559292; SGD proteins need primaryAccession to merge.
3. Item 19: skip taxon 559292 in the Alliance interaction converters, or drop the BioGRID feed.
4. Item 24: enable mpo, pato, hpo with OBO downloads; loaders for FBcv, WBPhenotype, APO, ChEBI.
5. Item 9: the UniProt converter loads `uniprot_config.properties` from the classpath (first copy
   wins), so the mine cannot override it reliably. Options: patch the jar in the image after the
   first gradle resolve, or fork the uniprot source into bio-sources with ZFIN and Xenbase
   gene-designation entries plus CURIE rewriting.
6. Item 28: WormMine RNAi view paths and HTP material type and GEO mapping.

## Reload plan for rc2

Build from `im2-model-links` in both InterMine repos with the PRs above merged. Sources that need a
reload: sgd, sgd-gff, sgd-gff-utr, sgd-db-utr, alliance-genes, alliance-alleles, alliance-allele-detail,
alliance-mouse-strains, alliance-transgenic-alleles, alliance-disease*, alliance-htp, alliance-worm-rnai,
alliance-*-interactions, alliance-alphafold, alliance-string, alliance-chembl. The earliest of these
in `project.xml` sets the checkpoint to resume from with `-l`. Rerun the fetchers first (PR #13
changes outputs, chembl-targets.tsv has a new column).

Post-load checks to add to the build: Gene with organism NULL = 0; Allele.gene references that
resolve = 100%; DiseaseEvidence without annotation = 0; Samples with characteristics > 0;
DiseaseModel.disease NULL = 0; Gene_UTRs for YHR191C = 20 rows; Protein.genes per organism > 0.

## Gaps

Build-host logs and the items DB were not read (ssh key blocked from this session).
Stage API payload shapes were not fetched. The 78 duplicate WAR entries fix (PR #14) was not checked in a
built WAR. Upstream InterMine sources (uniprot, panther, kegg, reactome, pubmed-gene) were not read.
