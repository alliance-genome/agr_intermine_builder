# TODO: HTTPS Setup for Multi-Tenant Mines

## Goal
Enable HTTPS access for multi-tenant AllianceMine (currently only accessible via HTTP on 44.206.248.213:8080)

## Current State

### Production (www.alliancegenome.org/alliancemine)
- **EC2 Instance**: Single instance with Docker containers:
  - BlueGenes
  - Solr
  - PostgreSQL
  - Tomcat
  - Builder
- **CDN**: Separate EC2 instance

### Multi-Tenant (44.206.248.213)
- **EC2 Instance**: 172.31.59.87 / 44.206.248.213
  - AllianceMine Tomcat (:8080) - HTTP only
  - WormMine Tomcat (:8081)
  - Solr (native, :8983)
  - Caddy CDN (:8888)
  - BlueGenes (:5000)
- **Database**: AWS RDS PostgreSQL (shared)
- **HTTPS**: Only WormMine via `wormmine.alliancegenome.org`

## Options

### Option A: Subdomain for Multi-Tenant (Recommended)
Use `alliancemine.alliancegenome.org` for multi-tenant, keep `www.alliancegenome.org/alliancemine` for production.

- [ ] Create Route 53 CNAME: `alliancemine.alliancegenome.org` → `alliancemine-lb`
- [ ] Add listener rule on `alliancemine-lb`:
  - Host: `alliancemine.alliancegenome.org` → new target group (172.31.59.87:8080)
- [ ] Add CDN rule: `/cdn/*` on `alliancemine.alliancegenome.org` → wormmine-cdn target group

### Option B: Replace Production with Multi-Tenant
Point `www.alliancegenome.org/alliancemine` to multi-tenant instead of production.

- [ ] Coordinate with web team on cutover timing
- [ ] Update existing ALB target group to point to 172.31.59.87:8080
- [ ] Ensure multi-tenant has all production data migrated

## Common Steps (for either option)

### Tomcat Configuration
- [ ] Add RemoteIpValve to AllianceMine container (like WormMine)
- [ ] Update `webapp.baseurl` in intermine.properties to HTTPS URL
- [ ] Update `head.cdn.location` to HTTPS CDN URL

### Testing
- [ ] Verify HTTPS access works
- [ ] Check `<base>` tag generates HTTPS URLs (no mixed content)
- [ ] Verify CDN resources load over HTTPS
- [ ] Test BlueGenes integration with HTTPS URLs

## Reference: WormMine HTTPS Setup
WormMine uses this pattern (already working):
```
wormmine.alliancegenome.org (Route 53 CNAME)
    → alliancemine-lb (ALB, HTTPS :443)
        → Rule 390: /cdn/* → wormmine-cdn target group (:8888)
        → Rule 400: Host match → wormmine target group (:8081)
```

## Notes
- ALB handles TLS termination (no certs needed on EC2)
- RemoteIpValve required for Tomcat to recognize `X-Forwarded-Proto: https`
- Security groups must allow ALB health checks
