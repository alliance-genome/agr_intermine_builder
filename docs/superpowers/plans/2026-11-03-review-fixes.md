# Build and Deployment Review Fixes

**Goal:** Correct the six failures reproduced in the codebase review.

**Approach:** Preserve existing commands and module names. Add regression tests before
each fix, mock infrastructure boundaries, and leave the completed diff for review.
Production deployments and database operations are outside this change.

## Tasks

- [x] Promotion: exercise both promotion commands with a simulated PostgreSQL server.
  Refuse an occupied production name without terminating connections or deleting data;
  preserve dry runs and successful renames. Share the promotion implementation.
- [x] Solr rollback: execute the deployment script with fake external commands.
  Record completed swaps and reverse only those after failure. Cover first/second swap
  failures, successful deployment, verification failure, and failed rollback.
- [x] Docker execution: use the real Docker SDK with a simulated API. Inspect the
  completed exec for its status, unpack demultiplexed output, and retain errors.
- [x] Extraction: simulate failed S3 downloads and failed Gene.tsv synthesis. Both must
  fail the command; intentional skip options must keep working.
- [x] Build summaries: retain failed attempts in `build_all_mines()` results and return
  a nonzero CLI status for partial or complete failure, including continue-on-error.
- [x] Packaging: build the wheel and invoke its entry points outside the checkout.
  Package the existing `src` namespace so documented module commands remain valid.

## Verification

Run the focused tests red, implement, then run them green. Run the entire pytest suite,
check the edited shell script with `bash -n`, inspect the wheel in isolation, and run
aislop against changed files. Fix errors and fixable warnings without changing rules.

## Review Focus

- Existing production names, missing candidates, query errors, dry runs, rename failures.
- Partial core swaps, failed reversal, and preservation of the currently deployed WAR.
- Nonzero Docker exits, empty output, and Unicode split across stream chunks.
- Explicit extraction skip flags versus failed required inputs.
- Installed commands without the repository on `sys.path`.

## Results

- Regression tests reproduced the original failures before implementation. The final
  suite passes all 108 cases, including 44 new cases replacing one obsolete mock test.
- Independent review identified an additional extraction gap. Real-converter tests now
  reject empty/malformed BGI inputs without replacing the previous `Gene.tsv`; empty S3
  output is rejected. Custom data directories supply their own Sequence Ontology file.
- Ruff and Black pass for changed Python files. Python 3.9 syntax checks, `bash -n`,
  wheel entry-point checks, `uv lock --check --offline`, and `git diff --check` pass.
- The lockfile adds the wheel-test backend and its dependencies without removing any
  previously locked package version.
- Aislop reports zero errors and zero fixable warnings. Four nonfixable warnings remain
  in `extract_data.py`: module length and three existing chained snapshot lookups.
  Splitting the extractor and changing snapshot-schema handling are deferred.
- Mypy 1.18.2 reports 21 errors in four files: Docker/AWS/PostgreSQL typing dependencies,
  existing return annotations and optional arguments, and `set_release.py`'s Python 3.9
  incompatibility. An original-code comparison with equivalent package markers and the
  same Docker directory reproduces all 21 diagnostics; none were introduced here.
- Coverage now includes previously omitted CLI modules because `src` and `src.cli` are
  explicit packages. The final 31% overall coverage is not directly comparable to the
  earlier 57% report, which omitted most CLI code.

## Remaining Operational Limits

Verification used local files and simulated infrastructure; no live build, promotion,
or deployment ran. The review retained these existing behaviors outside this patch:

- A remote Solr swap that succeeds before its HTTP response is lost needs core identity
  reconciliation; recording acknowledged swaps does not resolve that ambiguity.
- Cross-run manual rollback eligibility and S3 manifest publication failure need a
  separate deployment-state design.
- Promotion lookup errors still count as absent databases. PostgreSQL rejects renaming
  onto an occupied name; promotion no longer drops that destination.
- Installed CLI imports work outside the checkout. Actual builds still require the
  repository's Docker assets and configured external services.
