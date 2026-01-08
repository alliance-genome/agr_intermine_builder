# AllianceMine HTTPS Setup

This document describes the HTTPS configuration for AllianceMine on the multi-tenant EC2 instance.

## Architecture

```
alliancemine.alliancegenome.org (Route 53 CNAME)
    → alliancemine-lb-309443304.us-east-1.elb.amazonaws.com (ALB, port 443 HTTPS)
        → Rule 150: Path = "/cdn/*" AND Host = "alliancemine.alliancegenome.org" → alliancemine-mt-cdn (port 8888)
        → Rule 250: Host = "alliancemine.alliancegenome.org" → alliancemine-multitenant (port 8080)
            → 172.31.59.87:8080 (Multi-tenant EC2)
```

## Infrastructure

### EC2 Instance
- **Instance ID**: i-0e7fbfd5a4440063e
- **Name**: InterMine-MultiTenant
- **Private IP**: 172.31.59.87
- **Public IP**: 44.206.248.213

### ALB Target Groups

| Target Group | ARN | Target | Health Check |
|--------------|-----|--------|--------------|
| alliancemine-multitenant | arn:aws:elasticloadbalancing:us-east-1:100225593120:targetgroup/alliancemine-multitenant/9c6cdef38cbc7e6b | 172.31.59.87:8080 | /alliancemine/service/version |
| alliancemine-mt-cdn | arn:aws:elasticloadbalancing:us-east-1:100225593120:targetgroup/alliancemine-mt-cdn/161152c8ff7b7752 | 172.31.59.87:8888 | / |

### DNS (Route 53)
- **Record**: `alliancemine.alliancegenome.org`
- **Type**: CNAME
- **Value**: `alliancemine-lb-309443304.us-east-1.elb.amazonaws.com`
- **Hosted Zone**: Z3IZ3D6V94JEC2 (public)

## Required Configuration

### 1. web.properties (in deployed WAR)

Location: `/usr/local/tomcat/webapps/alliancemine/WEB-INF/web.properties`

```properties
webapp.hostname=alliancemine.alliancegenome.org
webapp.baseurl=https://alliancemine.alliancegenome.org/alliancemine
head.cdn.location=https://alliancemine.alliancegenome.org/cdn
```

### 2. RemoteIpValve (Tomcat server.xml)

Location: `/usr/local/tomcat/conf/server.xml`

The RemoteIpValve is required because the ALB terminates TLS and forwards requests as HTTP. Without it, the Struts `<html:base/>` tag generates HTTP URLs causing mixed content issues.

```xml
<Valve className="org.apache.catalina.valves.RemoteIpValve"
       remoteIpHeader="X-Forwarded-For"
       protocolHeader="X-Forwarded-Proto" />
```

This should be placed before the `<Host>` element in server.xml.

### 3. CDN (Caddy)

Caddy serves static files on port 8888. The ALB routes `/cdn/*` requests to Caddy.

**/etc/caddy/Caddyfile**:
```
:8888 {
    handle_path /cdn/* {
        root * /data/cdn
        file_server
        header Access-Control-Allow-Origin *
    }

    handle {
        root * /data/cdn
        file_server
        header Access-Control-Allow-Origin *
    }
}
```

## Fix Commands

If the HTTPS configuration is broken, run these commands:

```bash
# SSH to multi-tenant instance
ssh -i ~/.ssh/AGR-ssl3.pem ec2-user@172.31.59.87

# Fix CDN location
docker exec alliancemine sed -i 's|head.cdn.location = https://intermine-cdn.alliancegenome.org|head.cdn.location = https://alliancemine.alliancegenome.org/cdn|g' /usr/local/tomcat/webapps/alliancemine/WEB-INF/web.properties

# Fix hostname (if set to internal IP)
docker exec alliancemine sed -i 's|webapp.hostname=172.31.59.87|webapp.hostname=alliancemine.alliancegenome.org|g' /usr/local/tomcat/webapps/alliancemine/WEB-INF/web.properties

# Verify changes
docker exec alliancemine grep -E 'head.cdn.location|webapp.hostname|webapp.baseurl' /usr/local/tomcat/webapps/alliancemine/WEB-INF/web.properties

# Restart AllianceMine
docker restart alliancemine
```

## Verification

### Test Service Endpoint
```bash
# Via ALB (from server)
curl -sk -H 'Host: alliancemine.alliancegenome.org' https://alliancemine-lb-309443304.us-east-1.elb.amazonaws.com/alliancemine/service/version

# Direct (from server)
curl -s http://localhost:8080/alliancemine/service/version
```

### Test CDN
```bash
curl -sk -H 'Host: alliancemine.alliancegenome.org' https://alliancemine-lb-309443304.us-east-1.elb.amazonaws.com/cdn/js/intermine/im-tables/2.0.0-beta/imtables.min.js | head -c 100
```

### Check Base Tag (for HTTPS)
```bash
curl -sL "https://alliancemine.alliancegenome.org/alliancemine" | grep '<base'
# Should show: <base href="https://alliancemine.alliancegenome.org/alliancemine/...
```

### DNS Resolution
```bash
dig @8.8.8.8 +short alliancemine.alliancegenome.org
```

## Troubleshooting

### "Safari Can't Find the Server"

DNS cache issue. Flush local DNS:

**macOS**:
```bash
sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder
```

**Verify DNS resolves**:
```bash
dig @8.8.8.8 +short alliancemine.alliancegenome.org
# Should return ALB IPs
```

### Mixed Content (CSS/JS not loading)

1. Check `<base>` tag is HTTPS:
   ```bash
   curl -sL "https://alliancemine.alliancegenome.org/alliancemine" | grep '<base'
   ```

2. If HTTP, verify RemoteIpValve:
   ```bash
   docker exec alliancemine grep RemoteIpValve /usr/local/tomcat/conf/server.xml
   ```

3. Add RemoteIpValve if missing:
   ```bash
   docker exec alliancemine sed -i 's|<Host name="localhost"|<Valve className="org.apache.catalina.valves.RemoteIpValve" remoteIpHeader="X-Forwarded-For" protocolHeader="X-Forwarded-Proto" />\n        <Host name="localhost"|' /usr/local/tomcat/conf/server.xml
   docker restart alliancemine
   ```

### CDN 404 Errors

1. Check Caddy is running:
   ```bash
   sudo systemctl status caddy
   ```

2. Check Caddyfile has `handle_path /cdn/*`:
   ```bash
   cat /etc/caddy/Caddyfile
   ```

3. Reload Caddy:
   ```bash
   sudo systemctl reload caddy
   ```

### Connection Pool Exhaustion (500 errors on queries)

If queries return 500 errors with `Connection is not available, request timed out`:

```bash
docker restart alliancemine
```

Health checks are configured to detect this (see docker-compose.multitenant.yml).

## Access URLs

| Type | URL |
|------|-----|
| HTTPS (Production) | https://alliancemine.alliancegenome.org/alliancemine |
| HTTP (Direct) | http://44.206.248.213:8080/alliancemine |
| HTTP (Internal) | http://172.31.59.87:8080/alliancemine |
| CDN (HTTPS) | https://alliancemine.alliancegenome.org/cdn/ |
| CDN (Direct) | http://172.31.59.87:8888/ |

## Related Documentation

- [Multi-Tenant Deployment Guide](MULTITENANT_DEPLOYMENT.md)
- [WormMine Multi-Tenant Setup](WORMMINE_MULTITENANT_SETUP.md)
