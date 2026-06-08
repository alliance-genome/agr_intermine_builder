-- patch_intermineobject_blob.sql
--
-- patch_attribute_fallbacks.sql writes into the per-class table (balancer,
-- aberration, gene, etc.) for fast SQL filtering. But InterMine's REST API
-- and report pages return attributes from the SERIALIZED canonical form in
-- intermineobject.object — a "$_^"-delimited blob that the per-class UPDATEs
-- don't touch. Without this companion patch, the API shows NULL for name /
-- symbol / secondaryIdentifier even when the per-class column has data.
--
-- This script appends '$_^a<field>$_^<value>' to the blob for entities where
-- the per-class table has a value but the blob doesn't. Append-not-insert is
-- safe because InterMine's parser walks delimited chunks; order doesn't
-- matter for deserialization.
--
-- Idempotent — guarded by `object NOT LIKE '%$_^a<field>$_^%'`.
--
-- Run AFTER patch_attribute_fallbacks.sql (which sets the per-class column
-- values that this script reads).

BEGIN;

-- ===== Balancer (name + secondaryIdentifier) =====
UPDATE intermineobject io
   SET object = io.object || E'$_^aname$_^' || b.name
  FROM balancer b
 WHERE io.id = b.id
   AND b.name IS NOT NULL
   AND io.object NOT LIKE E'%$_^aname$_^%';

UPDATE intermineobject io
   SET object = io.object || E'$_^asecondaryIdentifier$_^' || b.secondaryidentifier
  FROM balancer b
 WHERE io.id = b.id
   AND b.secondaryidentifier IS NOT NULL
   AND io.object NOT LIKE E'%$_^asecondaryIdentifier$_^%';

-- ===== Aberration =====
UPDATE intermineobject io
   SET object = io.object || E'$_^aname$_^' || a.name
  FROM aberration a
 WHERE io.id = a.id
   AND a.name IS NOT NULL
   AND io.object NOT LIKE E'%$_^aname$_^%';

UPDATE intermineobject io
   SET object = io.object || E'$_^asecondaryIdentifier$_^' || a.secondaryidentifier
  FROM aberration a
 WHERE io.id = a.id
   AND a.secondaryidentifier IS NOT NULL
   AND io.object NOT LIKE E'%$_^asecondaryIdentifier$_^%';

-- ===== Aberration: stub aberrations may also need symbol injected =====
UPDATE intermineobject io
   SET object = io.object || E'$_^asymbol$_^' || a.symbol
  FROM aberration a
 WHERE io.id = a.id
   AND a.symbol IS NOT NULL
   AND io.object NOT LIKE E'%$_^asymbol$_^%';

-- ===== TransgenicConstruct =====
UPDATE intermineobject io
   SET object = io.object || E'$_^aname$_^' || t.name
  FROM transgenicconstruct t
 WHERE io.id = t.id
   AND t.name IS NOT NULL
   AND io.object NOT LIKE E'%$_^aname$_^%';

UPDATE intermineobject io
   SET object = io.object || E'$_^asecondaryIdentifier$_^' || t.secondaryidentifier
  FROM transgenicconstruct t
 WHERE io.id = t.id
   AND t.secondaryidentifier IS NOT NULL
   AND io.object NOT LIKE E'%$_^asecondaryIdentifier$_^%';

-- ===== Transcript =====
UPDATE intermineobject io
   SET object = io.object || E'$_^aname$_^' || t.name
  FROM transcript t
 WHERE io.id = t.id
   AND t.name IS NOT NULL
   AND io.object NOT LIKE E'%$_^aname$_^%';

-- ===== TransposableElement =====
UPDATE intermineobject io
   SET object = io.object || E'$_^aname$_^' || t.name
  FROM transposableelement t
 WHERE io.id = t.id
   AND t.name IS NOT NULL
   AND io.object NOT LIKE E'%$_^aname$_^%';

-- ===== TransposableElementInsertionSite =====
UPDATE intermineobject io
   SET object = io.object || E'$_^aname$_^' || t.name
  FROM transposableelementinsertionsite t
 WHERE io.id = t.id
   AND t.name IS NOT NULL
   AND io.object NOT LIKE E'%$_^aname$_^%';

UPDATE intermineobject io
   SET object = io.object || E'$_^asymbol$_^' || t.symbol
  FROM transposableelementinsertionsite t
 WHERE io.id = t.id
   AND t.symbol IS NOT NULL
   AND io.object NOT LIKE E'%$_^asymbol$_^%';

-- ===== Gene (the 90% non-D.mel skeleton entries get FBgn as symbol/name) =====
UPDATE intermineobject io
   SET object = io.object || E'$_^asymbol$_^' || g.symbol
  FROM gene g
 WHERE io.id = g.id
   AND g.symbol IS NOT NULL
   AND io.object NOT LIKE E'%$_^asymbol$_^%';

UPDATE intermineobject io
   SET object = io.object || E'$_^aname$_^' || g.name
  FROM gene g
 WHERE io.id = g.id
   AND g.name IS NOT NULL
   AND io.object NOT LIKE E'%$_^aname$_^%';

UPDATE intermineobject io
   SET object = io.object || E'$_^asecondaryIdentifier$_^' || g.secondaryidentifier
  FROM gene g
 WHERE io.id = g.id
   AND g.secondaryidentifier IS NOT NULL
   AND io.object NOT LIKE E'%$_^asecondaryIdentifier$_^%';

-- ===== Protein =====
UPDATE intermineobject io
   SET object = io.object || E'$_^aname$_^' || p.name
  FROM protein p
 WHERE io.id = p.id
   AND p.name IS NOT NULL
   AND io.object NOT LIKE E'%$_^aname$_^%';

UPDATE intermineobject io
   SET object = io.object || E'$_^asymbol$_^' || p.symbol
  FROM protein p
 WHERE io.id = p.id
   AND p.symbol IS NOT NULL
   AND io.object NOT LIKE E'%$_^asymbol$_^%';

-- ===== ProteinDomain =====
UPDATE intermineobject io
   SET object = io.object || E'$_^asymbol$_^' || pd.symbol
  FROM proteindomain pd
 WHERE io.id = pd.id
   AND pd.symbol IS NOT NULL
   AND io.object NOT LIKE E'%$_^asymbol$_^%';

UPDATE intermineobject io
   SET object = io.object || E'$_^asecondaryIdentifier$_^' || pd.secondaryidentifier
  FROM proteindomain pd
 WHERE io.id = pd.id
   AND pd.secondaryidentifier IS NOT NULL
   AND io.object NOT LIKE E'%$_^asecondaryIdentifier$_^%';

-- ===== Stock =====
UPDATE intermineobject io
   SET object = io.object || E'$_^aname$_^' || s.name
  FROM stock s
 WHERE io.id = s.id
   AND s.name IS NOT NULL
   AND io.object NOT LIKE E'%$_^aname$_^%';

UPDATE intermineobject io
   SET object = io.object || E'$_^asymbol$_^' || s.symbol
  FROM stock s
 WHERE io.id = s.id
   AND s.symbol IS NOT NULL
   AND io.object NOT LIKE E'%$_^asymbol$_^%';

-- ===== Allele =====
UPDATE intermineobject io
   SET object = io.object || E'$_^aname$_^' || a.name
  FROM allele a
 WHERE io.id = a.id
   AND a.name IS NOT NULL
   AND io.object NOT LIKE E'%$_^aname$_^%';

UPDATE intermineobject io
   SET object = io.object || E'$_^asecondaryIdentifier$_^' || a.secondaryidentifier
  FROM allele a
 WHERE io.id = a.id
   AND a.secondaryidentifier IS NOT NULL
   AND io.object NOT LIKE E'%$_^asecondaryIdentifier$_^%';

-- ===== Chromosome =====
UPDATE intermineobject io
   SET object = io.object || E'$_^aname$_^' || c.name
  FROM chromosome c
 WHERE io.id = c.id
   AND c.name IS NOT NULL
   AND io.object NOT LIKE E'%$_^aname$_^%';

UPDATE intermineobject io
   SET object = io.object || E'$_^asymbol$_^' || c.symbol
  FROM chromosome c
 WHERE io.id = c.id
   AND c.symbol IS NOT NULL
   AND io.object NOT LIKE E'%$_^asymbol$_^%';

COMMIT;

-- Sanity print
SELECT 'balancer w/aname'        AS t, count(*) FROM intermineobject WHERE class = 'org.intermine.model.bio.Balancer' AND object LIKE E'%$_^aname$_^%'
UNION ALL SELECT 'aberration w/aname',  count(*) FROM intermineobject WHERE class = 'org.intermine.model.bio.Aberration' AND object LIKE E'%$_^aname$_^%'
UNION ALL SELECT 'transgenicconstruct w/aname', count(*) FROM intermineobject WHERE class = 'org.intermine.model.bio.TransgenicConstruct' AND object LIKE E'%$_^aname$_^%'
UNION ALL SELECT 'gene w/asymbol',      count(*) FROM intermineobject WHERE class = 'org.intermine.model.bio.Gene' AND object LIKE E'%$_^asymbol$_^%'
ORDER BY 1;
