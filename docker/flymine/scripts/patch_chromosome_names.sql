-- Copy primaryidentifier to name + symbol on Chromosome rows that come out of
-- the FlyBase chado loader with NULL name/symbol attributes. Without this the
-- Query Builder + report pages show empty cells for `Chromosome > Name` and
-- `Chromosome > Symbol`, even though the underlying `primaryIdentifier` ("2L",
-- "3R", etc.) is populated and chromosomal locations resolve correctly.
--
-- Run against the production object store DB after the `postprocess` step.
-- Idempotent — guarded by `WHERE … IS NULL`.
--
-- Usage:
--   PGPASSWORD=... psql -h <RDS_HOST> -U postgres -d <DB_NAME> \
--       -f patch_chromosome_names.sql
--
-- See docs/FLYMINE_DEPLOY_2026_06_05.md for the runtime context.
UPDATE chromosome SET name = primaryidentifier WHERE name IS NULL;
UPDATE chromosome SET symbol = primaryidentifier WHERE symbol IS NULL;
