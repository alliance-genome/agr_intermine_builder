# Rnash SGD template restore — 2026-05-12

Restore action that attached 28 lost SGD curator templates to Rob Nash's account on the rc20 webapp without making them publicly visible.

## Why

The legacy `user-intermine-db` RDS (pre-8.3.0) held 4 historical userprofile DBs. The largest, `userprofile_alliancemine_local` (PG 12.22, db.t3.medium), contained 90 saved templates — 25-28 more than the prod `alliancemine_userprofile` ever inherited after the 8.3.0 migration. Most of the extras were SGD-curator hand-edits over years (e.g. yeast-specific feature-type queries, chromosomal feature templates, paralog/orthology variants).

Those 28 templates never reached the new prod userprofile because the migration cut from `userprofile-alliancemine-prod` (65 templates), not `userprofile_alliancemine_local` (90). The diff stayed lost until this restore.

## What

Imported the 28 missing templates into the live `alliancemine_userprofile.savedtemplatequery` table, attached to user `rnash@stanford.edu` (Rob Nash, SGD; `userprofile.id = 22000001`). Saved-template rows with a non-superuser owner are PRIVATE to that user — they appear in his "My Templates" panel but are not visible to anyone else and not exposed via the public template list.

Rob can promote any of them to public templates himself via the InterMine webapp UI ("Share" or similar), or we can re-INSERT copies under the superuser account if SGD agrees they should be system-wide.

## Templates restored (28)

```
AGR_Yeast_Genes
AllGene_ChromosomalFeatures
AllGenes_Topic_Literature
Chromosome_AllFeatures
Chromosome_IntergenicSequence
Chromosome_Telomeres
FeatureType_Gene
FeatureType_SequenceFeature
Gene_Auto_Descriptions
Gene_ChromosomeLocation
Gene_Complex_New
Gene_CrossRefs
Gene_FeatureType_Introns
Gene_Flanking_Sequence
Gene_Genetic_Interaction
Gene_Literature
Gene_OverlappingGenes
Gene_Phenotype_New
Gene_Physical_Interaction
Gene_Topic_Literature
Gene_UpstreamIntergenic
GeneFactor_GeneTarget
GeneTarget_GeneFactor
Literature_Gene
Phenotype_Genes_New
Publications_Literature
Qualifier_ORF
SequenceFeature_Topics
```

## How

1. Local dump file (gitignored): `dumps/old_userprofile/userprofile_alliancemine_local.dump` (37 KB, pg_dump -Fc from user-intermine-db RDS earlier this week).
2. Converted to SQL text via `pg_restore --data-only --no-owner --no-privileges -f /tmp/_local.sql ...`.
3. Python regex extracted each `<template name="...">...</template>` body matching the 28 names list. Output to `dumps/old_userprofile/extracted/non_prod_templates_28.xml` (gitignored).
4. Built INSERT SQL with `$mytag$ ... $mytag$` dollar-quoting to avoid escape hell on the XML.
5. Executed against `alliancemine_userprofile` on intermine-postgres:
   - ID range: 82000016 - 82000043
   - userprofileid: 22000001 (rnash@stanford.edu)
   - BEGIN/COMMIT wrapped — all 28 in single transaction
6. Verified count via `SELECT count(*) FROM savedtemplatequery WHERE userprofileid=22000001;` → 28.

No webapp restart needed — InterMine reads userprofile templates lazily per-user-login.

## What Rob sees

On next login at https://alliancemine.alliancegenome.org/alliancemine (or 8086 internal):
- Templates page → "My Templates" tab → 28 new entries
- Each is an exact copy of the body that existed in the old userprofile_alliancemine_local
- Editable + runnable + shareable (he can promote any to public if SGD wants them system-wide)

## Caveats

- These templates were written for the pre-Alliance schema. Some may need column tweaks for the current rc20 model (e.g. `Gene.sgdAlias` exists; `Gene.briefDescription` exists; but some paths may have shifted). Test before relying on them.
- Rob's userprofile-saved templates persist forever in alliancemine_userprofile DB across releases as long as that DB is reused. Future userprofile DB migrations (if any) must include these rows.
- Edith Wong has no account yet in current userprofile. Pending request: when she registers (`ewong@stanford.edu` or similar), copy the same 28 INSERTs under her userprofile.id.

## Files

- `dumps/old_userprofile/userprofile_alliancemine_local.dump` — source dump (gitignored)
- `dumps/old_userprofile/extracted/non_prod_templates_28.xml` — extracted XML bodies (gitignored)
- `/tmp/load_rnash_templates.sql` — INSERT SQL (operator-local)
- `/tmp/_local.sql` — full SQL conversion of the dump (operator-local)

## Related

- Task #39 — Restore lost SGD templates from old userprofile RDS (completed)
- `docs/RC20_TEMPLATE_FIX_STATUS_2026_05_12.md` — broader fix-status doc; references this restore in the "Not fixed - lost SGD curator templates" row
- `docs/SESSION_LOG_2026_05_11.md` — original discovery of the user-intermine-db RDS and the 90 vs 65 template diff
- `docs/UPSTREAM_CODE_UPDATE_PLAN.md` — separate plan for backporting the OTHER set of XML fixes into source `default-template-queries.xml`; if SGD wants any of these 28 also promoted to system templates, that plan should grow a section for them
