#!/usr/bin/env bash
# dump_mines_to_s3.sh - pg15 custom-format dumps of mine databases, streamed straight to S3.
# Runs on the build host (AllianceMineDev: RDS creds in ~/flymine-deploy/.env, S3 via the instance role).
#
#   nohup ~/ops-backups/dump_mines_to_s3.sh db1 db2 ... > ~/ops-backups/dump-$(date +%F).log 2>&1 &
#
# One database at a time (light on the shared RDS). Each lands at
#   s3://agr-db-backups/db-backups/<db>/<YYYY-MM-DD>/<db>.dump  (+ .sha256)
# Restore: aws s3 cp s3://.../<db>.dump - | pg_restore -d <newdb> ...   (pg15 client)
set -uo pipefail
cd ~/flymine-deploy && set -a && . ./.env && set +a
DAY=$(date -u +%F); BUCKET=s3://agr-db-backups/db-backups
say() { echo "[$(date -u +%FT%TZ)] $*"; }
fails=0
for db in "$@"; do
    dest="$BUCKET/$db/$DAY/$db.dump"
    # exact-key lookups (aws s3 ls matches by prefix, so it would also list <db>.dump.sha256)
    s3size() { aws s3api head-object --bucket agr-db-backups --key "${1#s3://agr-db-backups/}" --query ContentLength --output text 2>/dev/null; }
    if [ -n "$(s3size "$dest.sha256")" ]; then say "$db: already in S3, skipping"; continue; fi
    bytes=$(docker run --rm -e PGPASSWORD="$RDS_PASSWORD" postgres:15 psql -h "$RDS_HOST" -U "$RDS_USER" -d postgres -At \
            -c "SELECT pg_database_size('$db')") || { say "$db: cannot read size - skipped"; fails=$((fails+1)); continue; }
    say "$db: dumping $((bytes/1024/1024/1024)) GB -> $dest"
    start=$(date +%s); sumf=$(mktemp)
    # --expected-size lets the CLI pick large enough multipart chunks for big streams (uncompressed size = upper bound)
    docker run --rm -e PGPASSWORD="$RDS_PASSWORD" postgres:15 \
        pg_dump -Fc -Z6 -h "$RDS_HOST" -U "$RDS_USER" -d "$db" \
      | tee >(sha256sum | cut -d' ' -f1 > "$sumf") \
      | aws s3 cp - "$dest" --expected-size "$bytes" --only-show-errors
    rc=("${PIPESTATUS[@]}")
    sleep 2
    if [ "${rc[0]}" = 0 ] && [ "${rc[2]}" = 0 ]; then
        echo "$(cat "$sumf")  $db.dump" | aws s3 cp - "$dest.sha256" --only-show-errors
        size=$(s3size "$dest"); size=${size:-0}
        say "$db: OK in $(( ($(date +%s)-start)/60 )) min, $((size/1024/1024)) MB in S3, sha256 $(cut -c1-16 "$sumf")"
    else
        say "$db: FAILED (pg_dump rc=${rc[0]}, s3 rc=${rc[2]}) - removing partial upload"
        aws s3 rm "$dest" --only-show-errors 2>/dev/null; fails=$((fails+1))
    fi
    rm -f "$sumf"
done
say "DONE: $# databases, $fails failed"
