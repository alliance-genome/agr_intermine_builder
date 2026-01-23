# Maintenance Page for AllianceMine Offline

**URL:** (ticket URL TBD)

## Request

> If/when AllianceMine goes down, we just get a 404 or an error page or a partially-working InterMine portal. We should have a more "official" page that displays while AllianceMine is being restored to let the public know to try again in a few moments (usually ~30-40 min).

## Assessment

**Complexity:** Low

This is a simple nginx configuration change with a static HTML maintenance page.

## Implementation

### Option 1: Nginx Maintenance Mode (Recommended)

Add to nginx config on multi-tenant (172.31.59.87):

```nginx
# In /etc/nginx/conf.d/alliancemine.conf

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

**To enable maintenance mode:**
```bash
touch /var/www/maintenance/alliancemine.flag
```

**To disable:**
```bash
rm /var/www/maintenance/alliancemine.flag
```

### Maintenance Page HTML

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AllianceMine - Maintenance</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a365d 0%, #2d3748 100%);
            color: #fff;
            min-height: 100vh;
            margin: 0;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            text-align: center;
            padding: 2rem;
            max-width: 600px;
        }
        .logo {
            width: 200px;
            margin-bottom: 2rem;
        }
        h1 {
            font-size: 2rem;
            margin-bottom: 1rem;
        }
        p {
            font-size: 1.1rem;
            line-height: 1.6;
            opacity: 0.9;
        }
        .status {
            background: rgba(255,255,255,0.1);
            border-radius: 8px;
            padding: 1rem;
            margin-top: 2rem;
        }
        .eta {
            font-size: 1.5rem;
            font-weight: bold;
            color: #68d391;
        }
        a {
            color: #63b3ed;
        }
    </style>
</head>
<body>
    <div class="container">
        <img src="https://www.alliancegenome.org/images/alliance_logo_white.png"
             alt="Alliance of Genome Resources" class="logo">
        <h1>AllianceMine is Currently Unavailable</h1>
        <p>
            We're performing scheduled maintenance to improve your experience.
            The service will be back online shortly.
        </p>
        <div class="status">
            <p>Estimated downtime:</p>
            <p class="eta">~30-40 minutes</p>
        </div>
        <p style="margin-top: 2rem;">
            Visit <a href="https://www.alliancegenome.org">alliancegenome.org</a>
            for other Alliance resources.
        </p>
    </div>
</body>
</html>
```

### Option 2: Tomcat Valve (Alternative)

Add maintenance valve to Tomcat's `server.xml` - more complex, not recommended.

### Option 3: Auto-detect Unhealthy Backend

Nginx can automatically show maintenance page when Tomcat is down:

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

This automatically shows the maintenance page when Tomcat returns errors.

## Recommendation

**Use Option 1 + Option 3 combined:**
- Manual flag for planned maintenance
- Auto-fallback for unexpected outages

## Files to Create

1. `/var/www/maintenance/maintenance.html` - The maintenance page
2. `/var/www/maintenance/alliancemine.flag` - Touch to enable (remove to disable)
3. Update nginx config

## Status

- [ ] Create maintenance page HTML
- [ ] Configure nginx
- [ ] Test maintenance mode toggle
- [ ] Document in runbook
