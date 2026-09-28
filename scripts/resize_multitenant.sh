#!/usr/bin/env bash
# resize_multitenant.sh — change the multitenant host's EC2 instance type (stop -> snapshot ->
# modify -> start -> verify). Run from a machine with the AWS CLI and SSH to the host's private IP.
#
#   scripts/resize_multitenant.sh                # preflight only (default): records a baseline
#   scripts/resize_multitenant.sh --go           # preflight, then do the resize and verify
#   scripts/resize_multitenant.sh --verify       # post-checks only (e.g. re-run after fixing something)
#
# Downtime: every mine on the host, ~5-10 min. The public IP (not an Elastic IP) CHANGES on
# stop/start; the ALB targets the instance ID and SSH uses the private IP, so both are unaffected.
# Recovery notes for this host: memory feedback_multitenant_reboot_recovery,
# docs/INCIDENT_MULTITENANT_REBOOT_2026_06_23.md.
set -uo pipefail

INSTANCE_ID="${INSTANCE_ID:-i-0e7fbfd5a4440063e}"
TARGET_TYPE="${TARGET_TYPE:-r7i.2xlarge}"
HOST="${HOST:-172.31.59.87}"
REGION="${REGION:-us-east-1}"
KEY="${KEY:-$HOME/.ssh/AGR-ssl3.pem}"
STATE_DIR="${STATE_DIR:-$HOME/.multitenant-resize}"
# port:context of every webapp on the host (bluegenes is served at /)
MINES="8081:wormmine 8084:mousemine 8085:flymine 8086:alliancemine 8087:yeastmine 8088:mousemine"
mkdir -p "$STATE_DIR"

AWS() { aws --region "$REGION" "$@"; }
SSH() {  # exit status is ssh's (the warning filter's own status is ignored)
    ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=15 "ec2-user@$HOST" "$@" 2>&1 \
        | { grep -v -e 'post-quantum' -e 'store now, decrypt later' -e 'openssh.com/pq' || true; }
    return "${PIPESTATUS[0]}"
}
say() { echo "[$(date -u +%T)] $*"; }
die() { say "ABORT: $*"; exit 1; }

target_groups() {  # every TG with a target on this host (mines register by IP, bluegenes by instance)
    for tg in $(AWS elbv2 describe-target-groups --query 'TargetGroups[].TargetGroupArn' --output text); do
        AWS elbv2 describe-target-health --target-group-arn "$tg" \
            --query "TargetHealthDescriptions[?Target.Id=='$INSTANCE_ID' || Target.Id=='$HOST'].[Target.Port,TargetHealth.State]" \
            --output text | while read -r port state; do
                echo "${tg##*targetgroup/} $port $state"; done
    done | awk '{split($1,a,"/"); print a[1], $2, $3}' | sort
}

mine_checks() {  # service/version + keyword search per mine, from the host
    SSH "for pm in $MINES; do p=\${pm%%:*}; m=\${pm#*:};
           v=\$(curl -s --max-time 30 -o /dev/null -w %{http_code} http://localhost:\$p/\$m/service/version);
           s=\$(curl -s --max-time 90 -o /dev/null -w %{http_code} \"http://localhost:\$p/\$m/service/search?q=gene&size=1\");
           echo \"\$p \$m version=\$v search=\$s\"; done;
         echo \"5000 bluegenes / $(curl -s --max-time 30 -o /dev/null -w %{http_code} http://localhost:5000/)\""
}

preflight() {
    say "== preflight"
    local cur; cur=$(AWS ec2 describe-instances --instance-ids "$INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].[InstanceType,State.Name,PublicIpAddress]' --output text)
    say "instance $INSTANCE_ID: $cur -> target $TARGET_TYPE"
    AWS ec2 describe-instance-type-offerings --location-type availability-zone \
        --filters "Name=location,Values=$(AWS ec2 describe-instances --instance-ids "$INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].Placement.AvailabilityZone' --output text)" \
        "Name=instance-type,Values=$TARGET_TYPE" --query 'InstanceTypeOfferings[0].InstanceType' \
        --output text | grep -q "$TARGET_TYPE" || die "$TARGET_TYPE not offered in the instance's AZ"
    SSH true >/dev/null || die "cannot SSH to $HOST"

    say "running containers (baseline):"
    SSH "docker ps --format '{{.Names}}' | sort" | tee "$STATE_DIR/containers.before"
    local bad; bad=$(SSH "for c in \$(docker ps --format '{{.Names}}'); do
        [ \"\$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' \$c)\" = unless-stopped ] || echo \$c; done")
    [ -z "$bad" ] || die "running containers without restart=unless-stopped (won't come back): $bad"
    SSH "systemctl is-enabled docker solr-dnat >/dev/null && sudo /etc/init.d/solr status >/dev/null 2>&1 && echo 'docker, solr-dnat enabled; solr running'" \
        || die "docker/solr-dnat not enabled or solr not running"
    SSH "docker ps --format '{{.Names}}' | xargs -r -n1 docker inspect -f '{{.Name}} {{json .HostConfig.Binds}}' | grep '/tmp/'" \
        && die "a container bind-mounts from /tmp (wiped on boot)"

    say "target groups (baseline):"; target_groups | tee "$STATE_DIR/tgs.before"
    say "mines (baseline):"; mine_checks | tee "$STATE_DIR/mines.before"
}

resize() {
    say "== resize to $TARGET_TYPE"
    AWS ec2 stop-instances --instance-ids "$INSTANCE_ID" >/dev/null || die "stop failed"
    say "stopping..."; AWS ec2 wait instance-stopped --instance-ids "$INSTANCE_ID" || die "did not stop"
    say "stopped"
    for v in $(AWS ec2 describe-instances --instance-ids "$INSTANCE_ID" \
            --query 'Reservations[0].Instances[0].BlockDeviceMappings[].Ebs.VolumeId' --output text); do
        AWS ec2 create-snapshot --volume-id "$v" \
            --description "multitenant pre-resize $(date -u +%F) ($INSTANCE_ID)" \
            --tag-specifications "ResourceType=snapshot,Tags=[{Key=Name,Value=multitenant-pre-resize-$(date -u +%F)}]" \
            --query SnapshotId --output text | sed "s/^/snapshot $v: /" | tee -a "$STATE_DIR/snapshots"
    done
    AWS ec2 modify-instance-attribute --instance-id "$INSTANCE_ID" \
        --instance-type "{\"Value\": \"$TARGET_TYPE\"}" || die "modify failed - instance is STOPPED; start it: aws ec2 start-instances --instance-ids $INSTANCE_ID"
    AWS ec2 start-instances --instance-ids "$INSTANCE_ID" >/dev/null || die "start failed"
    say "starting..."; AWS ec2 wait instance-status-ok --instance-ids "$INSTANCE_ID" || say "WARN: status checks not ok yet"
    say "running: $(AWS ec2 describe-instances --instance-ids "$INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].[InstanceType,PublicIpAddress]' --output text) (new public IP)"
}

verify() {
    say "== verify"
    for i in $(seq 1 30); do SSH true >/dev/null && break; sleep 10; done
    SSH "free -g | sed -n 2p; nproc"
    say "waiting for containers..."
    for i in $(seq 1 30); do
        SSH "docker ps --format '{{.Names}}' | sort" > "$STATE_DIR/containers.after"
        diff -q "$STATE_DIR/containers.before" "$STATE_DIR/containers.after" >/dev/null && break; sleep 10
    done
    diff "$STATE_DIR/containers.before" "$STATE_DIR/containers.after" && say "all baseline containers running" \
        || say "WARN: container set differs (< missing, > extra)"
    SSH "sudo iptables -t nat -S PREROUTING | grep -q 'dport 8983' && echo 'solr DNAT rule present' || echo 'WARN: solr DNAT rule MISSING - sudo systemctl restart solr-dnat'"
    SSH "curl -s --max-time 30 -o /dev/null -w 'solr: %{http_code}\n' 'http://localhost:8983/solr/admin/cores?action=STATUS'"
    say "waiting for webapps (up to 10 min)..."
    for i in $(seq 1 60); do
        [ "$(SSH "for pm in $MINES; do p=\${pm%%:*}; m=\${pm#*:}; curl -s --max-time 10 -o /dev/null -w '%{http_code}\n' http://localhost:\$p/\$m/service/version; done" | grep -c '^200$')" -ge 6 ] && break
        sleep 10
    done
    say "mines:"; mine_checks | tee "$STATE_DIR/mines.after"
    say "MouseMine 1.x keyword index warm-up (first search takes ~40 min after a restart) started in background"
    SSH "(setsid nohup curl -s --max-time 3600 -o /dev/null 'http://localhost:8084/mousemine/service/search?q=Pax6&size=1' </dev/null >/dev/null 2>&1 &)"
    say "target groups (waiting up to 5 min for healthy):"
    for i in $(seq 1 30); do target_groups > "$STATE_DIR/tgs.after"
        diff -q "$STATE_DIR/tgs.before" "$STATE_DIR/tgs.after" >/dev/null && break; sleep 10; done
    cat "$STATE_DIR/tgs.after"
    diff "$STATE_DIR/tgs.before" "$STATE_DIR/tgs.after" >/dev/null && say "target group health matches baseline" \
        || say "WARN: target group health differs from baseline (see above vs $STATE_DIR/tgs.before)"
}

case "${1:-}" in
    "")        preflight; say "preflight only - re-run with --go to resize" ;;
    --go)      preflight && resize && verify ;;
    --verify)  verify ;;
    *)         sed -n '2,12p' "$0"; exit 2 ;;
esac
