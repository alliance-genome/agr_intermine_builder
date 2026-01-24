# KANBAN-799: Create Temporary Web Page for When AllianceMine is Offline

**URL:** https://agr-jira.atlassian.net/browse/KANBAN-799

## Request

> If / when AllianceMine goes down, we just get a 404 or an error page or a partially-working Intermine portal. We should have a more "official" page that displays while AllianceMine is being restored to let the public know to try again in a few moments (usually ~30-40 min).

## Assessment

**Complexity:** Low

This is a simple nginx configuration change with a static HTML maintenance page.

**See also:** `tickets/KANBAN-MAINTENANCE-PAGE.md` for detailed implementation.

## Implementation Summary

### Nginx Configuration

Add to `/etc/nginx/conf.d/alliancemine.conf` on multi-tenant (172.31.59.87):

```nginx
# Maintenance mode flag
set $maintenance 0;

# Check for maintenance file
if (-f /var/www/maintenance/alliancemine.flag) {
    set $maintenance 1;
}

# Serve maintenance page when flag exists
if ($maintenance = 1) {
    return 503;
}

error_page 503 @maintenance;
location @maintenance {
    root /var/www/maintenance;
    rewrite ^(.*)$ /maintenance.html break;
}
```

### Usage

**Enable maintenance mode:**
```bash
touch /var/www/maintenance/alliancemine.flag
```

**Disable maintenance mode:**
```bash
rm /var/www/maintenance/alliancemine.flag
```

### Auto-detection Option

Nginx can also auto-detect when Tomcat is down:

```nginx
upstream alliancemine {
    server localhost:9001 max_fails=3 fail_timeout=30s;
}

location / {
    proxy_pass http://alliancemine;
    proxy_intercept_errors on;
    error_page 502 503 504 = @maintenance;
}
```

## Recommendation

Combine manual flag + auto-detection:
- Manual flag for planned maintenance
- Auto-fallback for unexpected outages

## Ticket Response

I've prepared an nginx-based maintenance page solution that can be enabled/disabled with a simple flag file. The page displays Alliance branding and informs users that AllianceMine will be back in ~30-40 minutes.

**Implementation includes:**
1. Maintenance page HTML with Alliance styling
2. Nginx configuration for manual maintenance mode
3. Optional auto-detection when Tomcat is unresponsive

I can deploy this to the multi-tenant instance. Let me know if you'd like to review the page design first.

## Files to Create

1. `/var/www/maintenance/maintenance.html` - The maintenance page
2. `/var/www/maintenance/alliancemine.flag` - Touch to enable (remove to disable)
3. Update nginx config

## Status

- [x] Solution documented
- [ ] Create maintenance page HTML
- [ ] Configure nginx
- [ ] Test maintenance mode toggle
- [ ] Document in runbook
