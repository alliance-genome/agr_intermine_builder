#!/usr/bin/env bash
# install_mine_watchdog.sh - install mine-watchdog.sh + a 1-minute systemd timer on the multitenant host.
#   scp scripts/mine-watchdog.sh scripts/install_mine_watchdog.sh multitenant:/tmp/
#   ssh multitenant 'sudo bash /tmp/install_mine_watchdog.sh /tmp/mine-watchdog.sh'
# Watched mines are set in /etc/default/mine-watchdog (MINES="name port path ...").
set -euo pipefail
SRC=${1:?usage: $0 <path to mine-watchdog.sh>}
install -m 755 "$SRC" /usr/local/sbin/mine-watchdog.sh
[ -f /etc/default/mine-watchdog ] || cat > /etc/default/mine-watchdog <<'E'
# name port webapp-path (space separated, repeat per mine)
MINES="mousemine-1x 8084 mousemine"
E
cat > /etc/systemd/system/mine-watchdog.service <<'U'
[Unit]
Description=Restart mine containers whose webapp stopped answering
After=docker.service
Requires=docker.service
[Service]
Type=oneshot
EnvironmentFile=-/etc/default/mine-watchdog
ExecStart=/usr/local/sbin/mine-watchdog.sh
U
cat > /etc/systemd/system/mine-watchdog.timer <<'U'
[Unit]
Description=Run mine-watchdog every minute
[Timer]
OnBootSec=5min
OnUnitActiveSec=1min
AccuracySec=5s
[Install]
WantedBy=timers.target
U
systemctl daemon-reload
systemctl enable --now mine-watchdog.timer
systemctl start mine-watchdog.service
journalctl -t mine-watchdog -n 5 --no-pager || true
systemctl list-timers mine-watchdog.timer --no-pager | sed -n 2p
