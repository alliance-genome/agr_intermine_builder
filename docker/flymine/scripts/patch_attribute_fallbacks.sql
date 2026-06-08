-- Attribute-fallback patches: copy `primaryidentifier`, `symbol`, or
-- `secondaryidentifier` into NULL `name` / `symbol` columns so that the
-- Query Builder + report pages render meaningful values instead of empty
-- cells. None of the FlyBase chado loaders synthesize a human-readable
-- `name` for these entity classes, even when `symbol` or `primaryidentifier`
-- are populated.
--
-- All updates are guarded by `WHERE … IS NULL` so re-running is a no-op.
--
-- Companion to:
--   patch_chromosome_names.sql (chromosome.name/.symbol)
--
-- RUN ORDER:
--   Canonical (cold build, fast): run BEFORE `:dbmodel:postprocess`. The
--   `create-attribute-indexes` post-process (step 11 of 15) builds
--   case-insensitive b-trees on lower(name)/lower(symbol)/lower(secondary
--   identifier) across every entity table — ~6 indexes per column. UPDATEing
--   after those indexes exist rewrites all of them for every row touched
--   (gene 165K, allele 330K, transposableelementinsertionsite 395K). Running
--   the SQL first means UPDATEs hit unindexed tables and the post-process
--   builds the indexes once, from patched values.
--
--   Hot-fix on an already-built DB: also safe (the SQL is idempotent), just
--   slower for the large tables.
--
--   Always BEFORE `:webapp:summariseObjectStore` so the WAR's
--   `objectstoresummary.properties` picks up the filled values.
--
-- Usage:
--   PGPASSWORD=… psql -h <RDS_HOST> -U postgres -d <DB_NAME> \
--       -f patch_attribute_fallbacks.sql
--
-- See docs/FLYMINE_DEPLOY_2026_06_05.md for the runtime context.

\echo '--- aberration ---'
-- 2026-06-08: ~6K FBab stub entries arrive from the breakpoint-TSV pass with
-- NO symbol/name (they appear only in the breakpoints feed, not synonyms).
-- Cover those stubs first by copying primaryidentifier into symbol, then the
-- existing "name = symbol" line fills name for both the stubs AND the
-- synonym-loaded aberrations. See sibling handoff
-- new_flymine/docs/HANDOFF_TO_BUILDER_BREAKPOINTS_2026-06-08.md §1
-- "Stub-creating Aberrations from the breakpoints file alone".
UPDATE aberration SET symbol = primaryidentifier WHERE symbol IS NULL;
UPDATE aberration SET name = symbol WHERE name IS NULL AND symbol IS NOT NULL;
UPDATE aberration SET secondaryidentifier = primaryidentifier WHERE secondaryidentifier IS NULL;

\echo '--- balancer ---'
UPDATE balancer SET name = symbol WHERE name IS NULL AND symbol IS NOT NULL;
UPDATE balancer SET secondaryidentifier = primaryidentifier WHERE secondaryidentifier IS NULL;

\echo '--- transgenicconstruct ---'
UPDATE transgenicconstruct SET name = symbol WHERE name IS NULL AND symbol IS NOT NULL;
UPDATE transgenicconstruct SET secondaryidentifier = primaryidentifier WHERE secondaryidentifier IS NULL;

\echo '--- transcript ---'
UPDATE transcript SET name = secondaryidentifier WHERE name IS NULL AND secondaryidentifier IS NOT NULL;

\echo '--- transposableelement ---'
UPDATE transposableelement SET name = symbol WHERE name IS NULL AND symbol IS NOT NULL;

\echo '--- transposableelementinsertionsite ---'
UPDATE transposableelementinsertionsite SET name = secondaryidentifier
   WHERE name IS NULL AND secondaryidentifier IS NOT NULL;
UPDATE transposableelementinsertionsite SET symbol = secondaryidentifier
   WHERE symbol IS NULL AND secondaryidentifier IS NOT NULL;

\echo '--- gene: skeleton entries (no symbol) get FBgn as fallback ---'
-- Non-D.mel genes from chado-db-flybase-{others,dpse} arrive without
-- feature.name, so the resulting Gene record has primaryidentifier ("FBgn…")
-- but no symbol, no name. The Query Builder defaults these columns to
-- empty cells. Echo the FBgn into symbol+name so cross-class queries surface
-- a usable label.
UPDATE gene SET symbol = primaryidentifier
   WHERE symbol IS NULL AND primaryidentifier IS NOT NULL;
UPDATE gene SET name = primaryidentifier
   WHERE name IS NULL AND primaryidentifier IS NOT NULL;
UPDATE gene SET secondaryidentifier = primaryidentifier
   WHERE secondaryidentifier IS NULL AND primaryidentifier IS NOT NULL;

\echo '--- protein ---'
UPDATE protein SET name = primaryaccession
   WHERE name IS NULL AND primaryaccession IS NOT NULL;
UPDATE protein SET symbol = primaryaccession
   WHERE symbol IS NULL AND primaryaccession IS NOT NULL;

\echo '--- proteindomain ---'
UPDATE proteindomain SET symbol = primaryidentifier
   WHERE symbol IS NULL AND primaryidentifier IS NOT NULL;
UPDATE proteindomain SET secondaryidentifier = shortname
   WHERE secondaryidentifier IS NULL AND shortname IS NOT NULL;

\echo '--- stock ---'
UPDATE stock SET name = secondaryidentifier
   WHERE name IS NULL AND secondaryidentifier IS NOT NULL;
UPDATE stock SET symbol = primaryidentifier
   WHERE symbol IS NULL AND primaryidentifier IS NOT NULL;

\echo '--- allele ---'
UPDATE allele SET name = symbol WHERE name IS NULL AND symbol IS NOT NULL;
UPDATE allele SET secondaryidentifier = primaryidentifier
   WHERE secondaryidentifier IS NULL AND primaryidentifier IS NOT NULL;

\echo '--- done ---'
SELECT 'aberration' AS t, count(name) AS named, count(*) FROM aberration
UNION ALL SELECT 'balancer', count(name), count(*) FROM balancer
UNION ALL SELECT 'transgenicconstruct', count(name), count(*) FROM transgenicconstruct
UNION ALL SELECT 'transcript', count(name), count(*) FROM transcript
UNION ALL SELECT 'transposableelement', count(name), count(*) FROM transposableelement
UNION ALL SELECT 'transposableelementinsertionsite', count(name), count(*) FROM transposableelementinsertionsite
UNION ALL SELECT 'gene_symbol', count(symbol), count(*) FROM gene
UNION ALL SELECT 'gene_name', count(name), count(*) FROM gene
UNION ALL SELECT 'protein_name', count(name), count(*) FROM protein
UNION ALL SELECT 'proteindomain_symbol', count(symbol), count(*) FROM proteindomain
UNION ALL SELECT 'stock_name', count(name), count(*) FROM stock
UNION ALL SELECT 'allele_name', count(name), count(*) FROM allele
ORDER BY 1;
