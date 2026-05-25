# OAuth + email config gap across AGR InterMine deployments

Date discovered: 2026-05-25
Status: Open — affects user-facing login + password-reset flows on **all**
AGR InterMine instances (mousemine, alliancemine, wormmine). No fix yet
because the operator-side credential decisions haven't been made.

## Symptom

1. **OAuth login does not work.** The mine's login page does not display
   any "Sign in with Google / GitHub / ORCID" buttons. Users can only
   create local InterMine accounts.

2. **"Forgot password" emails are never sent.** Click "Forgot password",
   enter email, the webapp returns success — but no email arrives. No
   error in the webapp log; the InterMine 1.x `PasswordResetEmailAction`
   fails silently when `mail.host` is unset.

Both surfaced on MouseMine via user reports during the rc-era browser-test
window. Confirmed identical state on AllianceMine and WormMine — the
features have been silently broken since initial deploy, not a regression.

## Root cause

Neither feature is configured anywhere:

| Property prefix | Present in mousemine | alliancemine | wormmine | Build containers on AllianceMineDev |
|---|---|---|---|---|
| `oauth2.*` | (none) | (none) | (none) | (none) |
| `mail.*` (smtp.host etc.) | (none) | (none) | (none) | (none) |

Verified 2026-05-25:

```bash
# Each deployed WAR's three properties files
docker exec <mine> grep -iE "^oauth|^mail\." \
  /usr/local/tomcat/webapps/<mine>/WEB-INF/web.properties \
  /usr/local/tomcat/webapps/<mine>/WEB-INF/classes/intermine.properties \
  /usr/local/tomcat/webapps/<mine>/WEB-INF/global.web.properties
# returns empty for all 3 mines, both prefixes

# Build containers on AllianceMineDev (source ~/.intermine/<mine>.properties)
docker exec mousemine grep -iE "^oauth|^mail\." /root/.intermine/mousemine.properties
docker exec alliancemine-alliancemine-builder-run-c06d6908f14f \
  grep -iE "^oauth|^mail\." /root/.intermine/alliancemine.properties
# both empty
```

The `mail.from` / `mail.subject` lines DO exist in the AllianceMine
properties template (this repo, `docker/alliancemine/properties/alliancemine.properties.template`)
but with no `mail.host` they have no effect. InterMine's mailer needs
`mail.host` minimum to attempt SMTP.

## What needs to land

### OAuth config (example: Google)

```properties
oauth2.providers=GOOGLE
oauth2.GOOGLE.url=https://accounts.google.com/o/oauth2/v2/auth
oauth2.GOOGLE.token-url=https://www.googleapis.com/oauth2/v4/token
oauth2.GOOGLE.user-info-url=https://www.googleapis.com/oauth2/v3/userinfo
oauth2.GOOGLE.scope=openid email profile
oauth2.GOOGLE.responseType=code
oauth2.GOOGLE.client-id=<from Google Cloud Console>
oauth2.GOOGLE.client-secret=<from Google Cloud Console>
```

For GitHub / ORCID, use their respective URLs (see `oauth2-default.properties`
in the upstream InterMine source for the shape). To enable multiple
providers, comma-separate: `oauth2.providers=GOOGLE,GITHUB,ORCID`.

**Provider-side setup required**:

- **Google**: Cloud Console project → APIs & Services → Credentials →
  Create OAuth 2.0 Client ID → application type "Web application" →
  Authorized redirect URI for **each mine**:
  - `https://mousemine.alliancegenome.org/mousemine/oauth2callback`
  - `https://alliancemine.alliancegenome.org/alliancemine/oauth2callback`
  - `https://wormmine.alliancegenome.org/wormmine/oauth2callback`
- **GitHub**: Developer settings → OAuth Apps → New → Authorization
  callback URL same shape as above.
- **ORCID**: Developer Tools → Register a public API client → Redirect
  URI same shape.

Single OAuth app per provider can serve all three mines if all redirect
URIs are registered on that one app. Or one app per mine if SGD/MGI/WB
want to own them separately.

### Mail config (example: AWS SES via SMTP — recommended)

```properties
mail.host=email-smtp.us-east-1.amazonaws.com
mail.smtp.port=587
mail.smtp.auth=true
mail.smtp.starttls.enable=true
mail.smtp.user=<SES SMTP IAM user>
mail.smtp.password=<SES SMTP IAM password>
mail.from=noreply@alliancegenome.org
mail.subject=Password for the <MineName> system
mail.text=Your account for the <MineName> system has been created successfully!
```

**Provider-side setup required (AWS SES)**:

- Verify `noreply@alliancegenome.org` (or another sender address) in
  SES console → Verified identities. The verification email goes to
  the address being verified. For domain verification (preferred for
  any-from-this-domain), add DKIM CNAME records to Route 53.
- Request SES production access (move out of sandbox). In sandbox, SES
  only sends to verified recipients — useless for real user accounts.
  Production-access request takes ~24h.
- Create SES SMTP credentials: SES console → SMTP Settings → Create SMTP
  credentials. This provisions a special IAM user — its SMTP password is
  NOT the IAM secret access key, it's derived via HMAC. Copy what the
  console shows; you cannot re-derive it later.

Region note: `us-east-1` matches the AWS account region. SES SMTP host is
region-specific (`email-smtp.<region>.amazonaws.com`).

### Alternatives to SES

| Backend | Pros | Cons |
|---|---|---|
| AWS SES SMTP | Same AWS account, cheap (~$0.10 per 1k emails), DKIM/SPF auto-handled with domain verification | Sandbox limits, production-access form |
| SendGrid / Postmark / Mailgun | Quick to set up, no AWS approval flow | Separate account + billing, ~$10-15/mo minimum |
| Google Workspace SMTP relay | If `alliancegenome.org` is on Workspace, free | App-password setup per Workspace policy, 100/day limit |
| Direct postfix on EC2 | Most flexible | Owning a mail server is its own ops burden, deliverability issues |

Default recommendation: AWS SES. AGR is already AWS-native, the domain
is in Route 53 for DKIM, and the cost is negligible at AGR's expected
password-reset volume.

## Where to apply (when creds in hand)

### Phase 1 — Live runtime patches (low risk, no rebuild)

For each of the three mines on multitenant (`172.31.59.87`):

```bash
ssh -i ~/.ssh/AGR-ssl3.pem ec2-user@172.31.59.87
for f in WEB-INF/web.properties WEB-INF/classes/intermine.properties; do
  docker exec <container> bash -c "
    cat >> /usr/local/tomcat/webapps/<mine>/\$f <<'OAUTH'
oauth2.providers=GOOGLE
oauth2.GOOGLE.url=https://accounts.google.com/o/oauth2/v2/auth
... (rest of OAuth block)
OAUTH

    cat >> /usr/local/tomcat/webapps/<mine>/\$f <<'MAIL'
mail.host=email-smtp.us-east-1.amazonaws.com
... (rest of mail block)
MAIL
  "
done
docker restart <container>
# rc20 / 8086: follow docs/RUNBOOK_ALLIANCEMINE_RESTART.md for bag-upgrade kick
# mousemine-1x: simple restart (~1 min)
# wormmine: simple restart
```

Containers + restart procedure per mine:

| Mine | Container | Restart procedure |
|---|---|---|
| alliancemine | `alliancemine-9.0.0-rc20` | `docs/RUNBOOK_ALLIANCEMINE_RESTART.md` (pg_terminate_backend kick) |
| mousemine | `mousemine-1x` | plain `docker restart` (~1 min) |
| wormmine | `wormmine` | plain `docker restart` |

### Phase 2 — Build container patches (so next rebuild ships it)

On AllianceMineDev (`172.31.60.197`):

```bash
ssh -i ~/.ssh/AGR-ssl3.pem ec2-user@172.31.60.197
docker exec <mine-builder-container> bash -c "
  cat >> /root/.intermine/<mine>.properties <<'OAUTH'
... (same OAuth block)
OAUTH

  cat >> /root/.intermine/<mine>.properties <<'MAIL'
... (same mail block)
MAIL
"
```

This is the source-of-truth that `ant default release-webapp` reads from
when baking properties into the WAR. Without this patch, the next
redeploy reverts the Phase 1 patches.

### Phase 3 — Template + repo backport

In this repo, patch:

- `docker/alliancemine/properties/alliancemine.properties.template`
- `docker/mousemine/properties/mousemine.properties.template`
- `docker/wormmine/properties/wormmine.properties.template`
- `docker/yeastmine/properties/yeastmine.properties.template`
- `docker/flymine/properties/flymine.properties.template`

Add the OAuth + mail blocks templated with envsubst variables:

```properties
oauth2.providers=${OAUTH_PROVIDERS}
oauth2.GOOGLE.client-id=${OAUTH_GOOGLE_CLIENT_ID}
oauth2.GOOGLE.client-secret=${OAUTH_GOOGLE_CLIENT_SECRET}
# ... etc

mail.host=${MAIL_HOST}
mail.smtp.user=${MAIL_SMTP_USER}
mail.smtp.password=${MAIL_SMTP_PASSWORD}
mail.from=${MAIL_FROM}
```

And matching `.env.example` entries for each mine (with placeholders /
"unset" defaults so a build without these vars degrades gracefully — the
properties render with empty values, same effective state as today).

### Phase 4 — secrets storage

Do NOT commit credentials to this repo. Options:

| Option | Notes |
|---|---|
| Operator's local `.env` files (current convention) | Simplest, but each operator copies + maintains. Not committed. |
| AWS Secrets Manager | Already used for `IntermineStagePropertiesFile` per `docs/WORMMINE_MULTITENANT_SETUP.md` line 220. Add new secret `intermine/oauth-and-mail` with both blocks. Entrypoint fetches at container start. |
| Per-mine env in docker-compose `.env` file | One source per mine, but creates drift |

Recommended: AWS Secrets Manager. The entrypoint already supports the
pattern (alliancemine fetches `IntermineStagePropertiesFile` at deploy
time). Mirror that.

## Decision matrix (operator action items)

| Item | Decision | Owner |
|---|---|---|
| OAuth providers | Google? GitHub? ORCID? Multiple? | AGR product / SGD / MGI / WB liaisons |
| OAuth app registration | One app for all 3 mines, or per-mine? | Same |
| OAuth credentials | Who pays for the Google Cloud project / generates the GitHub OAuth app? | AGR IT / Stanford / MGI per-mine? |
| Mail backend | AWS SES (recommended) vs SendGrid vs Workspace relay | AGR IT |
| `mail.from` address | `noreply@alliancegenome.org` (need to verify) or per-mine | AGR IT |
| SES production access | Required (file form, 24h) — only AGR IT can request | AGR IT |
| Mail-config scope | All 3 mines now, or mousemine-only urgent fix? | Product |
| Secret storage | AWS Secrets Manager? per-operator `.env`? | Ops |

## Why this stayed hidden

- OAuth: InterMine 1.x's login page hides provider buttons entirely when
  `oauth2.providers` is unset. No "OAuth disabled" message, just no
  buttons. Most operators don't notice the absence.
- Mail: `PasswordResetEmailAction` returns HTTP 200 with a generic
  "if that account exists, an email has been sent" message regardless
  of whether the email actually sent — security-by-design (no account
  enumeration). Real user gets no email but the webapp logs no error.
  Only way to notice is for an actual user to try it and report.

The MouseMine maintainer found both during the rc20-era browser-test
window when a new user tried to register / recover their password.

## Cross-references

- `docs/WORMMINE_MULTITENANT_SETUP.md` — has the `IntermineStagePropertiesFile`
  Secrets Manager pattern that should be reused for these new secrets.
- `docs/PRODUCTION_CUTOVER_RC20.md` — explains the live-runtime patch +
  build-container backport flow we keep using for property fixes.
- `docs/RUNBOOK_ALLIANCEMINE_RESTART.md` — restart procedure for the
  alliancemine container (Phase 1 step) with the bag-upgrade kick.
- `docs/MOUSEMINE_PUBLIC_URL_RELEASE_2026_05_20.md` — pattern for the
  three-file properties sync (web.properties + classes/intermine.properties
  + global.web.properties).
- InterMine OAuth reference: `https://intermineorg.wordpress.com/2018/04/19/oauth2-integration/`
  (last working URL as of 2024; mirror in case it goes away).
