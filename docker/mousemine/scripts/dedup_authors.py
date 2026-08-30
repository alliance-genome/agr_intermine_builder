#!/usr/bin/env python3
"""Merge author items with duplicate names (mojibake collisions) in the reordered
publication.xml. Keep one item per name; remap dropped author IDs to the kept one
and rewrite publication author references. Preserves authors-first ordering."""
import re, sys

PX = "/intermine/mousemine/integrate/build/publication.xml"
OUT = "/intermine/mousemine/integrate/build/publication_dedup.xml"

id_re = re.compile(r'id="([^"]+)"')
val_re = re.compile(r'value="([^"]*)"')
ref_re = re.compile(r'ref_id="([^"]+)"')

# ---- Pass 1: build name->kept_id and dropped_id->kept_id ----
name_to_id, remap = {}, {}
in_author = False
cur_id = cur_name = None
buf_is_author = False
with open(PX, encoding="utf-8", errors="surrogatepass") as f:
    for line in f:
        if '<item ' in line and 'class="Author"' in line:
            m = id_re.search(line); cur_id = m.group(1) if m else None
            cur_name = None; in_author = True
        elif in_author and 'name="name"' in line:
            mv = val_re.search(line); cur_name = mv.group(1) if mv else None
        elif in_author and '</item>' in line:
            if cur_id is not None and cur_name is not None:
                if cur_name in name_to_id:
                    remap[cur_id] = name_to_id[cur_name]
                else:
                    name_to_id[cur_name] = cur_id
            in_author = False
dropped = set(remap)
print(f"pass1: {len(name_to_id)} unique names, {len(dropped)} dropped author items", file=sys.stderr)

# ---- Pass 2: stream, drop remapped authors, rewrite pub refs ----
def rewrite_refs(line):
    def repl(m):
        rid = m.group(1)
        return 'ref_id="%s"' % remap.get(rid, rid)
    return ref_re.sub(repl, line)

kept = dropped_cnt = rewrit = 0
block = []            # current <item>..</item> buffer
block_is_author = False
block_drop = False
with open(PX, encoding="utf-8", errors="surrogatepass") as f, \
     open(OUT, "w", encoding="utf-8", errors="surrogatepass") as out:
    for line in f:
        if '<item ' in line:
            block = [line]
            block_is_author = 'class="Author"' in line
            m = id_re.search(line)
            block_drop = block_is_author and m and m.group(1) in dropped
            if '</item>' in line:   # single-line item (rare)
                if not block_drop:
                    out.write(rewrite_refs(line) if not block_is_author else line)
                else:
                    dropped_cnt += 1
                block = []
        elif block:
            block.append(line)
            if '</item>' in line:
                if block_drop:
                    dropped_cnt += 1
                else:
                    for bl in block:
                        # only publications need ref rewriting; authors have no refs
                        if not block_is_author and 'ref_id=' in bl:
                            nb = rewrite_refs(bl)
                            if nb != bl:
                                rewrit += 1
                            out.write(nb)
                        else:
                            out.write(bl)
                    kept += 1
                block = []
        else:
            out.write(line)   # header / footer
print(f"pass2: kept {kept} items, dropped {dropped_cnt} authors, rewrote {rewrit} ref lines", file=sys.stderr)
