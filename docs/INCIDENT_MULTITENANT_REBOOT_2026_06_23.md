# Incident — Multitenant Reboot Breaks All Mine Search (2026-06-23)

The multitenant host (172.31.59.87) rebooted (during/after the 2026-06-18 RDS storage-full window). On reboot, **every mine's keyword search broke** and the **flymine container failed to start**. Symptoms looked mine-specific ("flymine is down", "all queries have an error") but the root causes were host-level and recur on every reboot. This doc is the recovery playbook.

## Symptoms

- "flymine is down" — container `Exited`, won't start.
- "all queries have an error" — `service/version` + `service/lists` return 200, but **`service/search` hangs ~25 s then 000/500** on every mine.
- Tomcat logs (all mines): `org.apache.http.conn.ConnectTimeoutException: Connect to 172.31.59.87:8983 failed: connect timed out`.

## Root cause 1 — Solr unreachable from containers (the hairpin)

Solr runs as a **host process** on `*:8983` (not a container). Mines connect to it at the host's **primary ENI IP** `172.31.59.87:8983`. After a reboot:

| From | `172.31.59.87:8983` | `172.17.0.1:8983` (docker0 gw) |
|---|---|---|
| Host | ✅ 200 | ✅ 200 |
| Inside a container | ❌ timeout | ✅ 200 |

This is the AWS Docker-bridge→host-ENI **hairpin**: a container packet to the host's own ENI IP isn't routed back. It works for weeks, then a reboot resets bridge/route state and it dies. `rp_filter` tweaks do **not** fix it. Editing each WAR's `index.solrurl` to `172.17.0.1` also does **not** fix it (the running webapp still hit `172.31.59.87` regardless — don't chase this).

### Fix — one DNAT rule repairs all mines

```bash
sudo iptables -t nat -A PREROUTING -s 172.17.0.0/16 -p tcp \
  -d 172.31.59.87 --dport 8983 -j DNAT --to-destination 172.17.0.1:8983
```
Redirects container traffic for `172.31.59.87:8983` to the working `172.17.0.1:8983`. Verify:
```bash
docker exec flymine curl -s -o /dev/null -w '%{http_code}\n' \
  'http://172.31.59.87:8983/solr/flymine-search/select?q=eve'   # -> 200
```

### Persistence — `solr-dnat.service`

A systemd oneshot re-adds the rule after Docker on every boot (idempotent `-C || -A`):

```ini
# /etc/systemd/system/solr-dnat.service
[Unit]
Description=DNAT container traffic for Solr ENI IP to docker host gateway
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash -c "/usr/sbin/iptables -t nat -C PREROUTING -s 172.17.0.0/16 -p tcp -d 172.31.59.87 --dport 8983 -j DNAT --to-destination 172.17.0.1:8983 2>/dev/null || /usr/sbin/iptables -t nat -A PREROUTING -s 172.17.0.0/16 -p tcp -d 172.31.59.87 --dport 8983 -j DNAT --to-destination 172.17.0.1:8983"

[Install]
WantedBy=multi-user.target
```
```bash
systemctl daemon-reload && systemctl enable --now solr-dnat.service
```
(There is no `netfilter-persistent` service on this host, so the ruleset saved at `/etc/iptables/rules.v4` is NOT auto-loaded — the systemd unit is what actually restores the rule.)

**If search breaks after a future reboot:** check `sudo iptables -t nat -L PREROUTING -n | grep 8983` and `systemctl status solr-dnat`.

## Root cause 2 — `/tmp` WARs vanish on reboot

The flymine container bind-mounted `/tmp/flymine.war` (tmpfs, wiped on reboot). Docker then recreated `/tmp/flymine.war` as an empty **directory**, so the container failed:
```
error mounting "/tmp/flymine.war" … not a directory: Are you trying to mount a directory onto a file?
```

### Recovery + permanent fix — persistent WAR mount

The flymine WAR lives inside the build container at `flymine-build:/root/flymine/webapp/build/libs/webapp.war`. The dev host has no SSH key to scp directly to multitenant, so relay dev → laptop → multitenant:
```bash
# on dev: docker cp flymine-build:/root/flymine/webapp/build/libs/webapp.war /tmp/flymine.war
scp ec2-user@dev:/tmp/flymine.war /tmp/flymine.war          # laptop pulls
scp /tmp/flymine.war ec2-user@multitenant:/tmp/flymine.war  # laptop pushes
# on multitenant: persist + recreate container with the PERSISTENT mount
cp /tmp/flymine.war /home/ec2-user/mine-wars/flymine.war
docker rm -f flymine
docker run -d --name flymine -p 8085:8080 \
  -v /home/ec2-user/mine-wars/flymine.war:/usr/local/tomcat/webapps/flymine.war:ro \
  --add-host agr.stage.alliancemine.solr.server:172.17.0.1 \
  --add-host agr.stage.flymine.solr.server:172.17.0.1 \
  -e JAVA_OPTS="-Dorg.apache.el.parser.SKIP_IDENTIFIER_CHECK=true -Xmx6g -Xms2g" \
  -e MANAGER_USER=manager -e MANAGER_PASSWORD=manager \
  --restart unless-stopped intermine-tomcat:agr-1x-runtime
```
flymine + yeastmine now mount persistent WARs from `/home/ec2-user/mine-wars/`. **TODO:** audit the other mines (`docker inspect <mine> --format '{{json .HostConfig.Binds}}'`) and migrate any remaining `/tmp` WAR mounts before the next reboot.

## Root cause 3 — stale JDBC pools after the RDS outage

Independently, after the 2026-06-18 RDS storage-full outage, Tomcat HikariCP pools held dead connections (`FATAL: the database system is not accepting connections`) → queries 500 even once RDS recovered. A `docker restart <mine>` recreates the pool. (Same class of "restart to clear in-JVM state" as the savedbag-cache and bag-upgrade-deadlock issues.)

## Final state — all green

| Mine | version | search |
|---|---|---|
| alliancemine | 200 | 200 |
| flymine | 200 | 200 |
| wormmine | 200 | 200 |
| yeastmine | 200 | 200 |
| mousemine | 200 (local) | 200 (local) |

- flymine on reboot-proof WAR mount + `restart=unless-stopped`
- `solr-dnat.service` enabled — DNAT survives future reboots

## Reboot recovery checklist (do this after ANY multitenant reboot)

1. `systemctl status solr-dnat` — confirm the Solr DNAT rule is present (search else hangs).
2. `docker ps -a` — start/recreate any mine whose `/tmp` WAR vanished (use `/home/ec2-user/mine-wars/`).
3. If queries 500 after RDS was down: `docker restart <mine>` to refresh JDBC pools.
4. Warm mousemine's Lucene search with one query (≈30 min self-clearing re-extract).
5. Public probe: `curl https://<mine>.alliancegenome.org/<mine>/service/search?q=eve&format=json`.

## Related

- `feedback_multitenant_reboot_recovery` memory — condensed version of this playbook
- `feedback_multitenant_disk` memory — log hot spots that also fill the host
- `RUNBOOK_ALLIANCEMINE_RESTART.md` — the bag-upgrade-deadlock restart kick
- `MOUSEMINE_RC3_BUILD_2026_06_16.md` — the RDS storage-full incident that preceded this reboot
