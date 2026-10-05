#!/usr/bin/env bash
# fix_flymine_data.sh — FlyMine data-fix, parameterised (FB_RELEASE / DMEL_REL env; was FB2026_02-only) (run on dev host 172.31.60.197)
# host /home/ec2-user/flymine-deploy/data == container /root/data
set -uo pipefail
export PATH=/usr/bin:/bin:/usr/local/bin:$PATH

DATA=/home/ec2-user/flymine-deploy/data
FB_RELEASE=${FB_RELEASE:-FB2026_03}; DMEL_REL=${DMEL_REL:-r6.69}
REL=$(echo "$FB_RELEASE" | tr "[:upper:]" "[:lower:]" | sed "s/^fb/fb_/")   # FB2026_03 -> fb_2026_03
FASTA_BASE=https://s3ftp.flybase.org/releases/$FB_RELEASE/dmel_$DMEL_REL/fasta
UNIPROT=https://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/complete
EBI_GO=https://ftp.ebi.ac.uk/pub/databases/GO/goa/external2go

ok(){   echo "  [OK]   $*"; }
info(){ echo "  [..]   $*"; }
warn(){ echo "  [WARN] $*"; }
hdr(){  echo; echo "==== $* ===="; }

# fetch <url> <dest-final-path> [--gunzip]
fetch(){
  local url=$1 dest=$2 gz=${3:-}
  if [ -s "$dest" ]; then ok "exists: $dest ($(sudo stat -c %s "$dest") B)"; return 0; fi
  sudo mkdir -p "$(dirname "$dest")"
  if [ "$gz" = "--gunzip" ]; then
    info "download $url"
    sudo curl -fsSL --retry 3 --max-time 1800 -o "$dest.gz" "$url" || { warn "download FAILED: $url"; return 1; }
    sudo gunzip -f "$dest.gz" || { warn "gunzip FAILED: $dest.gz"; return 1; }
  else
    info "download $url"
    sudo curl -fsSL --retry 3 --max-time 1800 -o "$dest" "$url" || { warn "download FAILED: $url"; return 1; }
  fi
  ok "wrote $dest ($(sudo stat -c %s "$dest") B)"
}

echo "FlyMine $FB_RELEASE ($DMEL_REL) data-fix @ $(date -u)"

hdr "1. alleles + transposons  (current -> . self-symlinks)"
for d in "$DATA/flybase/alleles" "$DATA/flybase/transposons"; do
  sudo ln -sfn . "$d/current"; ok "$d/current -> ."
done

hdr "2. allele-stubs  (aux/current + fbal symlink)"
sudo mkdir -p "$DATA/flybase/alleles/aux/current"
sudo cp -f "$DATA/flybase/alleles/fbal_to_fbgn_$REL.tsv" "$DATA/flybase/alleles/aux/current/fbal_to_fbgn_$REL.tsv"   # real copy: a host-path symlink dangles in the container
ls "$DATA/flybase/alleles/aux/current/"fbal_to_fbgn_*.tsv >/dev/null 2>&1 && ok "fbal glob resolves" || warn "fbal glob MISSING"

hdr "3. dmel FASTA (gene/CDS/5'UTR/3'UTR $DMEL_REL -> flybase/fasta/current)"
sudo mkdir -p "$DATA/flybase/fasta/current"
fetch "$FASTA_BASE/dmel-all-gene-$DMEL_REL.fasta.gz"            "$DATA/flybase/fasta/current/dmel-all-gene-$DMEL_REL.fasta"            --gunzip
fetch "$FASTA_BASE/dmel-all-CDS-$DMEL_REL.fasta.gz"             "$DATA/flybase/fasta/current/dmel-all-CDS-$DMEL_REL.fasta"             --gunzip
fetch "$FASTA_BASE/dmel-all-five_prime_UTR-$DMEL_REL.fasta.gz"  "$DATA/flybase/fasta/current/dmel-all-five_prime_UTR-$DMEL_REL.fasta"  --gunzip
fetch "$FASTA_BASE/dmel-all-three_prime_UTR-$DMEL_REL.fasta.gz" "$DATA/flybase/fasta/current/dmel-all-three_prime_UTR-$DMEL_REL.fasta" --gunzip

hdr "4. uniprot-fasta (uniprot_sprot_varsplic.fasta)"
sudo rm -f "$DATA/uniprot/current/uniprot_sprot_drosophila.xml.gz.part"
fetch "$UNIPROT/uniprot_sprot_varsplic.fasta.gz" "$DATA/uniprot/current/uniprot_sprot_varsplic.fasta" --gunzip

hdr "5. uniprot-keywords (re-fetch keywlist.xml, it was gzip mis-named)"
sudo rm -f "$DATA/uniprot/current/keywlist.xml"
sudo curl -fsSL --retry 3 --max-time 600 -o "$DATA/uniprot/current/keywlist.xml.gz" "$UNIPROT/docs/keywlist.xml.gz" \
  && sudo gunzip -f "$DATA/uniprot/current/keywlist.xml.gz" && ok "keywlist.xml ($(sudo stat -c %s "$DATA/uniprot/current/keywlist.xml") B)" || warn "keywlist FAILED"
sudo head -c5 "$DATA/uniprot/current/keywlist.xml" | grep -q '<?xml' && ok "keywlist starts with <?xml" || warn "keywlist not valid XML"

hdr "6. interpro-go (interpro2go)"
fetch "$EBI_GO/interpro2go" "$DATA/interpro/ontology/current/interpro2go"

hdr "7. update-data-sources (uniprot dbxref.txt)"
fetch "$UNIPROT/docs/dbxref.txt" "$DATA/uniprot/xrefs/current/dbxref.txt"

hdr "8. fly-misc-cvterms (delete obsolete consider FBcv:0003012)"
OBO="$DATA/flybase/ontologies/flybase_controlled_vocabulary.obo"
if sudo grep -q '^consider: FBcv:0003012$' "$OBO"; then
  sudo cp -n "$OBO" "$OBO.orig"; sudo sed -i '/^consider: FBcv:0003012$/d' "$OBO"; ok "removed obsolete consider (backup .orig)"
else ok "cv obo already clean"; fi

hdr "9. drosophila-homology (UNRESOLVED — no data in this release; source will be skipped)"
sudo mkdir -p "$DATA/flybase/homology/current"
warn "no cross-Drosophila orthologs feed in $FB_RELEASE — drosophila-homology excluded from integration"

echo; echo "==== DONE @ $(date -u) ===="
