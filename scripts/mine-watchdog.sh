#!/usr/bin/env bash
# mine-watchdog.sh - restart a mine container whose webapp has stopped answering.
#
# Why: under scraper floods MouseMine 1.x's JVM wedges (GC-bound, no OutOfMemoryError, process alive),
# so Docker's restart policy never fires and the mine stays down until someone restarts it by hand
# (33 h on 2026-10-04, again 2026-10-05). The ALB alarm emails; this recovers.
#
# Run every minute by mine-watchdog.timer (installed by install_mine_watchdog.sh). Per mine:
# GET http://localhost:<port>/<path>/service/version; after FAILS_TO_RESTART consecutive failures,
# `docker restart` it (at most once per COOLDOWN_MIN, at most MAX_PER_6H per 6 h), then warm the
# keyword search. Events go to the journal: journalctl -t mine-watchdog
set -u
# name port webapp-path
MINES=${MINES:-"mousemine-1x 8084 mousemine"}
FAILS_TO_RESTART=${FAILS_TO_RESTART:-5}
COOLDOWN_MIN=${COOLDOWN_MIN:-15}
MAX_PER_6H=${MAX_PER_6H:-4}
WARM_TRIES=${WARM_TRIES:-40}   # x15 s waiting for the webapp before warming search
STATE=${STATE:-/var/lib/mine-watchdog}; mkdir -p "$STATE"
log() { logger -t mine-watchdog "$*"; echo "$*"; }

set -- $MINES
while [ $# -ge 3 ]; do
    name=$1 port=$2 path=$3; shift 3
    f="$STATE/$name.fails"; r="$STATE/$name.restarts"; touch "$r"
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "http://localhost:$port/$path/service/version" || true)
    if [ "$code" = 200 ]; then
        [ -s "$f" ] && [ "$(cat "$f")" != 0 ] && log "$name healthy again"
        echo 0 > "$f"; continue
    fi
    n=$(( $(cat "$f" 2>/dev/null || echo 0) + 1 )); echo $n > "$f"
    log "$name check failed ($code), $n/$FAILS_TO_RESTART"
    [ $n -ge $FAILS_TO_RESTART ] || continue
    now=$(date +%s)
    last=$(tail -1 "$r" 2>/dev/null || echo 0); last=${last:-0}
    if [ $(( now - last )) -lt $(( COOLDOWN_MIN * 60 )) ]; then log "$name: restarted $(( (now-last)/60 )) min ago, waiting (cooldown)"; continue; fi
    recent=$(awk -v t=$(( now - 21600 )) '$1 > t' "$r" | wc -l)
    if [ "$recent" -ge "$MAX_PER_6H" ]; then log "$name: $recent restarts in 6 h - NOT restarting again, needs a human"; continue; fi
    log "$name: unresponsive for $n checks - docker restart"
    echo "$now" >> "$r"; echo 0 > "$f"
    docker restart -t 60 "$name" >/dev/null 2>&1 && log "$name restarted" || log "$name: docker restart FAILED"
    # warm the keyword search in the background (the first search after a restart is slow)
    ( for i in $(seq 1 $WARM_TRIES); do
          [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "http://localhost:$port/$path/service/version")" = 200 ] && break; sleep 15
      done
      curl -s -o /dev/null --max-time 300 "http://localhost:$port/$path/service/search?q=gene&size=1" && log "$name search warmed" ) &
done
wait
