# MouseMine 1.8: keyword-search index reload takes the site down after every restart

Status: **deployed 2026-09-29 16:45 UTC** (patch cf8aac5). The outage that prompted it: `mousemine-1x`
restarted 13:29 UTC for the model-browser counts, down ~13:45–16:14 UTC while the index reloaded
(6.5 GB on disk, not the ~1.2 GB first estimated), then search failed with OutOfMemoryError on the
4 GB heap. After the deploy: restart served in ~10 s, the log showed the index was reused
(`Reusing search index … skipped extraction from the database`), and the first search returned
7,651 hits in 27 s. Heap is now 6 GB (container limit 8 GB), with `-XX:+ExitOnOutOfMemoryError`.

## What happens

After every Tomcat/JVM restart, the first keyword search runs
`KeywordSearch.initKeywordSearch`, which is `static synchronized`, and that calls
`readFSDirectory`. On every start, that method:

1. deletes every file in `webapps/mousemine/keyword_search_index/`, which is a persistent bind mount
   (`/home/ec2-user/mousemine-data/keyword_search_index`);
2. streams the whole index out of the database: the large object behind `intermine_metadata`
   `search_directory`, 1,166 MB, read at about 160–200 KB/s with a 2 KB buffer;
3. unzips it back into that directory.

That takes 40–110 minutes. Every search that arrives meanwhile blocks on the `synchronized` method
while holding a Tomcat request thread.

Evidence from 2026-09-29 14:1x UTC:
- the thread dump showed **197 of 200** `http-nio-8080-exec` threads `BLOCKED` in
  `KeywordSearch.initKeywordSearch`;
- one thread was reading the large object;
- `service/version` couldn't get a thread, so the ALB marked the target unhealthy and the whole
  site went down, not just search;
- memory (2.3 of 6 GB) and CPU were idle.

Source: `intermine/api/main/src/org/intermine/api/lucene/KeywordSearch.java`, lines 796–906. It is
identical in the MouseMine build tree (tag `mousemine-1.8.1.18`, in the `mousemine` build container
on AllianceMineDev) and in InterMine 1.8.5. The copy on disk is never reused, although the directory
is persistent.

## Fix

Patch `KeywordSearch` so a restart reuses the index already on disk when it is the one in the
database, and extracts only when the database has a different index (a new release).

1. In `restoreSearchDirectory`, read the stored index's ID with
   `MetadataManager.retrieve(db, "search_directory")` (for example `BLOB: 7506108`). This is a single
   small row read, not the 1.2 GB object.
2. Before deleting anything, look for `keyword_search_index/.index-source` and reuse the directory
   (`FSDirectory.open`) without touching the database when:
   - the marker's first line equals that ID;
   - every file it lists exists with the recorded size;
   - `IndexReader.indexExists(dir)` is true.
3. Otherwise extract exactly as today (with a 64 KB buffer instead of 2 KB) and write the marker
   **last**, after a successful extraction, listing the ID and each file's name and size. An
   interrupted extraction therefore never leaves a marker that would be trusted.
4. Everything else in the class stays unchanged. The patched classes go into
   `WEB-INF/classes/org/intermine/api/lucene/`, which Tomcat loads ahead of `WEB-INF/lib/intermine-api.jar`.
   The jar isn't touched, so rolling back means deleting the classes.

Result: a restart costs seconds, not an hour. The full extraction only happens after a release
cutover, when the database has a new index, and that cutover can be warmed outside working hours.

## Build

In the `mousemine` build container on AllianceMineDev (the InterMine 1.x tree the WAR was built from):

- copy `KeywordSearch.java` from the tree and apply the patch;
- compile with `javac -source 8 -target 8` against the deployed WAR's `WEB-INF/lib/*.jar`. The
  running JVM is Java 11; the original class is Java 6 bytecode, and Java 8 bytecode runs fine;
- output `KeywordSearch*.class` (main plus any inner classes);
- commit the patched source to `agr_intermine_builder` as `patches/mousemine-1x/KeywordSearch.java`,
  next to the other InterMine patches.

## Test (AllianceMineDev, before production)

A throwaway 1.x Tomcat on a spare port (image from `docker/intermine-tomcat-1x/`), using a copy of the
production WAR plus the patched classes. It reads `mousemine_rc4`, and its userprofile DB is
redirected to `mousemine_im5_test_userprofile` (same schema, unused), so production users are never
touched.

| Case | Expect |
|---|---|
| First start, empty index directory | extracts (40–110 min), then writes `.index-source`; searches work |
| Restart | first search answers in seconds; no large-object read on RDS; log line "reusing index" |
| Marker edited to another ID | full extraction again, new marker |
| Marker present but a file truncated | full extraction (size check fails) |

## Deploy (production, about 2 minutes of work)

The permission system blocks my writes to the production host, so you run these steps.

1. After today's load has finished (`_5z.cfs` complete, search answering), write `.index-source`
   for the index that is already on disk. A small script lists the directory, adds the ID
   `BLOB: 7506108`, and writes the marker into the bind mount.
2. Copy the patched classes into the `mousemine-1x` container, into
   `webapps/mousemine/WEB-INF/classes/org/intermine/api/lucene/`. The exploded webapp persists
   because `mousemine.war`'s timestamp doesn't change.
3. `docker restart mousemine-1x`. Expect `service/version` in about 10 s, and the first search
   within seconds.
4. Verify: the ALB target is healthy, search for Pax6 returns hits, and the log shows the index
   being reused with no "Deleting old file" or "Extracting" lines.

**Rollback:** delete the patched classes from `WEB-INF/classes/…/lucene/` and restart. That brings
back today's behaviour, including the hour-long reload.

**Timing:** deploy before tonight's multitenant resize, so the resize restart is quick for MouseMine too.

## Related follow-ups

- Add `-XX:+ExitOnOutOfMemoryError` to `mousemine-1x` so a heap OOM restarts it instead of leaving it
  "Up" but dead (as on 2026-09-22 to 09-28), and add an ALB `UnHealthyHostCount` alarm.
- The long-term answer is MouseMine 5.1, where search runs in Solr outside the JVM and a webapp
  restart doesn't reload anything.
