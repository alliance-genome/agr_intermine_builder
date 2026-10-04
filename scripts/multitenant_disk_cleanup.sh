#!/usr/bin/env bash
# multitenant_disk_cleanup.sh - free disk on InterMine-MultiTenant and keep it from filling again.
# Runs ON the host as root; from a laptop:
#   ssh multitenant 'sudo bash -s' < scripts/multitenant_disk_cleanup.sh
#
# Background: 2026-10-03 the 100 GB root disk hit 100%, intermine-restart.timer's
# `docker restart wormmine alliancemine` could not start them again, public WormMine was down 19 h.
# Causes: logrotate "keep 7" never matches Tomcat's dated filenames (/data/mines/logs/wormmine
# 22 GB), closed logs inside container layers (rc20 localhost.2026-06-24.log 13.5 GB), unbounded
# docker json logs (mousemine-1x INFO spam), no daemon.json log limits.
#
# What it does (never stops or restarts a mine; never touches mine data or volumes):
#   0. grow the root partition + XFS if the EBS volume was enlarged (idempotent)
#   1-3. the log cleanup below, now
#   4. remove the long-stopped alliancemine-9.0.0 container and unused images
#      (all verified present in ECR on 2026-10-04 before listing them here)
#   5. clear intermine-restart.service's failed state
#   6. install intermine-log-cleanup.timer: steps 1-3 daily at 04:30 UTC (before the 05:00 restart)
set -u
[ "$(id -u)" = 0 ] || { echo "run as root (sudo bash -s)"; exit 1; }
usage() { df -h / | tail -1 | awk '{print $2" size, "$3" used, "$4" free ("$5")"}'; }
echo "before: $(usage)"

# ---- 0. grow root filesystem ---------------------------------------------------------------
DISK=/dev/nvme0n1
if [ "$(lsblk -bno SIZE $DISK)" -gt "$(( $(lsblk -bno SIZE ${DISK}p1) + 1073741824 ))" ]; then
    growpart $DISK 1 && xfs_growfs / >/dev/null && echo "0. grew / to $(df -h / | tail -1 | awk '{print $2}')"
else
    echo "0. disk not larger than the partition yet (EBS resize still pending?) - rerun later to grow"
fi

# ---- 1-3. log cleanup (also installed as the daily job) ------------------------------------
cat > /usr/local/sbin/intermine-log-cleanup.sh <<'JOB'
#!/usr/bin/env bash
# Daily: dated Tomcat logs older than 7 days (host dirs + inside container layers), and docker
# json logs over 200 MB. Installed by agr_intermine_builder/scripts/multitenant_disk_cleanup.sh.
set -u
DATED='\( -name "*.20[0-9][0-9]-*.log" -o -name "*.20[0-9][0-9]-*.txt" \)'
n=$(eval find /data/mines/logs -type f -mtime +7 "$DATED" -print -delete | wc -l)
echo "host Tomcat logs deleted: $n"
for c in $(docker ps --format '{{.Names}}'); do
    docker inspect "$c" --format '{{range .Mounts}}{{.Destination}} {{end}}' | grep -q /usr/local/tomcat/logs && continue
    out=$(docker exec "$c" sh -c "cd /usr/local/tomcat/logs 2>/dev/null || exit 0; du -sk . | cut -f1; find . -type f -mtime +7 $DATED -delete; du -sk . | cut -f1" 2>/dev/null | tr '\n' ' ')
    set -- $out; [ $# -eq 2 ] && [ "$1" != "$2" ] && echo "$c: in-container logs, $(( ($1-$2)/1024 )) MB freed"
done
for c in $(docker ps -q); do
    p=$(docker inspect -f '{{.LogPath}}' "$c"); s=$(stat -c %s "$p" 2>/dev/null || echo 0)
    [ "$s" -gt 209715200 ] && truncate -s 0 "$p" && echo "$(docker inspect -f '{{.Name}}' "$c"): json log truncated ($((s/1048576)) MB)"
done
echo "disk: $(df -h / | tail -1 | awk '{print $3" used, "$4" free ("$5")"}')"
JOB
chmod 755 /usr/local/sbin/intermine-log-cleanup.sh
echo "1-3. log cleanup:"; /usr/local/sbin/intermine-log-cleanup.sh | sed 's/^/     /'

# ---- 4. stopped container + unused images ---------------------------------------------------
docker rm alliancemine-9.0.0 >/dev/null 2>&1 && echo "4. removed stopped container alliancemine-9.0.0 (stopped since July)"
ECR=100225593120.dkr.ecr.us-east-1.amazonaws.com
for i in agr_alliancemine:runtime-9.0.0 agr_alliancemine:runtime-9.0.0-20260506-0308 \
         agr_alliancemine:runtime-9.0.0-20260505-0011 agr_alliancemine:runtime-9.0.0-20260504-2207 \
         agr_alliancemine:runtime-9.0.0-20260504-2118 agr_alliancemine:runtime-9.0.0-20260501-1930 \
         agr_alliancemine:9.0.0 agr_wormmine:runtime-latest agr_wormmine:runtime-latest-20260506-0308 \
         agr_intermine_tomcat_data_image:8.3.0 agr_intermine_nginx_cdn:latest; do
    docker rmi "$ECR/$i" >/dev/null 2>&1 && echo "   rmi $i (still in ECR)" || echo "   kept $i (in use or already gone)"
done
docker rmi postgres:14-alpine postgres:15-alpine >/dev/null 2>&1 && echo "   rmi postgres:14-alpine, postgres:15-alpine"
docker image prune -f >/dev/null

# ---- 5. restart unit state ------------------------------------------------------------------
systemctl reset-failed intermine-restart.service 2>/dev/null && echo "5. cleared intermine-restart.service failed state"

# ---- 6. daily timer -------------------------------------------------------------------------
cat > /etc/systemd/system/intermine-log-cleanup.service <<'U'
[Unit]
Description=Delete old Tomcat logs and cap docker json logs (InterMine mines)
After=docker.service
Requires=docker.service
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/intermine-log-cleanup.sh
U
cat > /etc/systemd/system/intermine-log-cleanup.timer <<'U'
[Unit]
Description=Daily InterMine log cleanup (before intermine-restart at 05:00 UTC)
[Timer]
OnCalendar=*-*-* 04:30:00 UTC
Persistent=true
[Install]
WantedBy=timers.target
U
systemctl daemon-reload && systemctl enable --now intermine-log-cleanup.timer >/dev/null 2>&1 \
    && echo "6. intermine-log-cleanup.timer enabled: $(systemctl list-timers intermine-log-cleanup.timer --no-pager | sed -n 2p | awk '{print $1, $2, $3, $4}')"

echo "after: $(usage)"
