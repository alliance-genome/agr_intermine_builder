-- seed_templates.sql — install (or refresh) the BDSC Phase 2 named-query
-- templates into the FlyMine userprofile DB.
--
-- The six templates surface AGR's Phase 2 named-query categories defined in
-- agr_stock/docs/plans/2026-05-22-bdsc-phase2-specific-aims.md §Aim 4:
--   * Synonym audits        → Gene_to_Synonyms
--   * FBab/FBba resolution  → Aberration_by_Symbol, Balancer_by_Symbol
--   * Aberration depth      → Aberration_DeletedGenes, Aberration_DuplicatedGenes
--   * Balancer composition  → Balancer_Composition (depends on
--                             flymine-bio-sources@75303cb populating
--                             balancercomposedofaberrations from the curated
--                             fbba_to_fbab.tsv — 9 classic balancers in v1)
-- (Stock additions are intentionally NOT here — they coordinate with the
--  separate Phase 1 stock-api Lambda flow.)
--
-- Templates are owned by `superuser@mail_account` (userprofileid 999999999),
-- tagged `im:public` so they show on /flymine/templates.do, and aspect-tagged
-- (Genomics / Genetic_Variations) so they group under the right BlueGenes
-- category.
--
-- USAGE: idempotent. Re-run after every fresh userprofile rebuild OR after
-- recovering profile from a wormmine_userprofile TEMPLATE clone (the clone
-- inherits wormmine templates which are then untagged separately by the
-- entrypoint / runbook).
--
--   PGPASSWORD=… psql -h <RDS_HOST> -U postgres \
--       -d flymine_userprofile_test -f seed_templates.sql
--
-- RUN ORDER: after `superuser@mail_account` is inserted (see runbook).
-- Companion files:
--   patch_chromosome_names.sql        chromosome attribute fallbacks
--   patch_attribute_fallbacks.sql     gene/aberration/balancer/etc. fallbacks
--   finalize_build.sh                 orchestrator
--
-- See docs/FLYMINE_DEPLOY_2026_06_05.md for the runtime context.

BEGIN;

-- Wipe any prior seed (idempotent on re-run)
DELETE FROM tag
 WHERE userprofileid = 999999999
   AND type = 'template'
   AND objectidentifier IN (
       'Gene_to_Synonyms',
       'Aberration_by_Symbol',
       'Balancer_by_Symbol',
       'Aberration_DeletedGenes',
       'Aberration_DuplicatedGenes',
       'Balancer_Composition'
   );

DELETE FROM savedtemplatequery
 WHERE userprofileid = 999999999
   AND id BETWEEN 900000001 AND 900000006;

INSERT INTO savedtemplatequery (id, userprofileid, templatequery) VALUES
(900000001, 999999999, $TPL$<template name="Gene_to_Synonyms" title="Gene --> All synonyms" longDescription="Given a FlyBase gene identifier, list every synonym (current symbol, secondary identifiers, historical names) with the data source that contributed it. Useful for synonym audits and symbol-merge detection." comment="">
  <query name="Gene_to_Synonyms" model="genomic" view="Gene.primaryIdentifier Gene.symbol Gene.synonyms.value Gene.synonyms.dataSets.name" longDescription="Given a FlyBase gene identifier, list every synonym with its data source." sortOrder="Gene.synonyms.value asc">
    <pathDescription pathString="Gene.synonyms" description="Synonyms loaded from FlyBase chado"/>
    <constraint path="Gene.primaryIdentifier" editable="true" description="Gene FBgn identifier" op="=" value="FBgn0000008"/>
  </query>
</template>$TPL$),
(900000002, 999999999, $TPL$<template name="Aberration_DeletedGenes" title="Aberration --> Genes deleted" longDescription="Given a FlyBase aberration identifier (FBab), list every gene the aberration deletes — the canonical 'what genes does this deletion remove?' lookup. 8,569 of 23,870 aberrations have deleted-gene data; deletion aberrations are typically the populated ones." comment="">
  <query name="Aberration_DeletedGenes" model="genomic" view="Aberration.primaryIdentifier Aberration.symbol Aberration.aberrationType Aberration.deletedGenes.primaryIdentifier Aberration.deletedGenes.symbol Aberration.deletedGenes.name" sortOrder="Aberration.deletedGenes.primaryIdentifier asc">
    <pathDescription pathString="Aberration.deletedGenes" description="Genes deleted by this aberration"/>
    <constraint path="Aberration.primaryIdentifier" editable="true" description="Aberration FBab identifier (e.g. FBab0037998 = Df(2R)Exel6060, 69 genes)" op="=" value="FBab0037998"/>
  </query>
</template>$TPL$),
(900000003, 999999999, $TPL$<template name="Aberration_by_Symbol" title="Aberration symbol --> FBab identifier" longDescription="Resolve an aberration symbol (e.g. Df(3L)Exel6137, Df(2L)TW161) to its canonical FlyBase identifier (FBab) and metadata. Useful for normalising stock-genotype-string entries to canonical IDs." comment="">
  <query name="Aberration_by_Symbol" model="genomic" view="Aberration.primaryIdentifier Aberration.symbol Aberration.name Aberration.aberrationType Aberration.description" sortOrder="Aberration.primaryIdentifier asc">
    <constraint path="Aberration.symbol" editable="true" description="Aberration symbol (e.g. Df(3L)Exel6137)" op="=" value="Df(3L)Exel6137"/>
  </query>
</template>$TPL$),
(900000004, 999999999, $TPL$<template name="Balancer_by_Symbol" title="Balancer symbol --> FBba identifier" longDescription="Resolve a balancer symbol (e.g. CyO, TM3, FM7c) to its canonical FlyBase identifier (FBba). Useful for normalising stock-genotype-string entries." comment="">
  <query name="Balancer_by_Symbol" model="genomic" view="Balancer.primaryIdentifier Balancer.symbol Balancer.name Balancer.balancedChromosome Balancer.description" sortOrder="Balancer.primaryIdentifier asc">
    <constraint path="Balancer.symbol" editable="true" description="Balancer symbol (e.g. CyO, TM3, TM6B, FM7c)" op="=" value="CyO"/>
  </query>
</template>$TPL$),
(900000005, 999999999, $TPL$<template name="Aberration_DuplicatedGenes" title="Aberration --> Genes duplicated" longDescription="Given a FlyBase aberration identifier (FBab), list every gene the aberration duplicates. Smaller dataset than deletedGenes (3,629 rows across duplication aberrations)." comment="">
  <query name="Aberration_DuplicatedGenes" model="genomic" view="Aberration.primaryIdentifier Aberration.symbol Aberration.aberrationType Aberration.duplicatedGenes.primaryIdentifier Aberration.duplicatedGenes.symbol Aberration.duplicatedGenes.name" sortOrder="Aberration.duplicatedGenes.primaryIdentifier asc">
    <pathDescription pathString="Aberration.duplicatedGenes" description="Genes duplicated by this aberration"/>
    <constraint path="Aberration.primaryIdentifier" editable="true" description="Aberration FBab identifier (must be a duplication type)" op="=" value=""/>
  </query>
</template>$TPL$),
(900000006, 999999999, $TPL$<template name="Balancer_Composition" title="Balancer --> Composing aberrations" longDescription="Given a FlyBase balancer identifier (FBba), list the aberrations (FBabs) that make up the balancer. v1 covers 9 classic balancers hand-curated by the sibling repo: FM3, FM6, FM7, CyO, SM5, SM6, TM3, TM6, TM6B. Other balancers will return empty until the curated table is extended (no code change needed)." comment="">
  <query name="Balancer_Composition" model="genomic" view="Balancer.primaryIdentifier Balancer.symbol Balancer.composedOfAberrations.primaryIdentifier Balancer.composedOfAberrations.symbol Balancer.composedOfAberrations.aberrationType" sortOrder="Balancer.composedOfAberrations.primaryIdentifier asc">
    <pathDescription pathString="Balancer.composedOfAberrations" description="Aberrations the balancer is composed of"/>
    <constraint path="Balancer.primaryIdentifier" editable="true" description="Balancer FBba identifier (e.g. FBba0000033 = CyO, FBba0000091 = TM3)" op="=" value="FBba0000033"/>
  </query>
</template>$TPL$);

INSERT INTO tag (id, type, objectidentifier, tagname, userprofileid) VALUES
 (910000001,'template','Gene_to_Synonyms','im:public',999999999),
 (910000002,'template','Aberration_DeletedGenes','im:public',999999999),
 (910000003,'template','Aberration_by_Symbol','im:public',999999999),
 (910000004,'template','Balancer_by_Symbol','im:public',999999999),
 (910000005,'template','Aberration_DuplicatedGenes','im:public',999999999),
 (910000006,'template','Balancer_Composition','im:public',999999999),
 (910000011,'template','Gene_to_Synonyms','im:aspect:Genomics',999999999),
 (910000012,'template','Aberration_DeletedGenes','im:aspect:Genetic_Variations',999999999),
 (910000013,'template','Aberration_by_Symbol','im:aspect:Genetic_Variations',999999999),
 (910000014,'template','Balancer_by_Symbol','im:aspect:Genetic_Variations',999999999),
 (910000015,'template','Aberration_DuplicatedGenes','im:aspect:Genetic_Variations',999999999),
 (910000016,'template','Balancer_Composition','im:aspect:Genetic_Variations',999999999);

COMMIT;

-- Sanity print
SELECT id, substring(templatequery from 'name="([^"]+)"') AS name
  FROM savedtemplatequery
 WHERE userprofileid = 999999999
 ORDER BY id;
