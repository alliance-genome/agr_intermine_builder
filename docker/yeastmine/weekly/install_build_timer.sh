#!/usr/bin/env bash
# install_build_timer.sh — one-time setup of the weekly YeastMine build on the build host
# (AllianceMineDev). Run as ec2-user (uses sudo) from this directory:
#     bash install_build_timer.sh
# Copies the build scripts to ~/yeastmine-build/weekly/bin and enables
# yeastmine-weekly-build.timer (Fridays 22:00 America/Los_Angeles).
# The yeastmine .env must also carry MAIL_* (see README.md) - weekly_build.sh refuses to run without.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN=/home/ec2-user/yeastmine-build/weekly/bin
mkdir -p "$BIN"
install -m 755 "$HERE/weekly_build.sh" "$BIN/weekly_build.sh"
install -m 755 "$HERE/check_build.py" "$BIN/check_build.py"
sudo install -m 644 "$HERE/systemd/yeastmine-weekly-build.service" "$HERE/systemd/yeastmine-weekly-build.timer" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yeastmine-weekly-build.timer
systemctl list-timers --no-pager yeastmine-weekly-build.timer
