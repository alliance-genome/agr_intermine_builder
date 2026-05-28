# MouseMine "forgot password" fix — full journey

Date: 2026-05-27
Scope: applied to mousemine, alliancemine, wormmine (all three multitenant containers)
Outcome: "forgot password" now sends a real reset link via AWS SES

## Symptom

User clicks "Forgot password" on any AGR InterMine login page → enters email →
webapp returns "Unable to send email. Please try again." in a yellow banner.
No email arrives.

State: silently broken on every AGR mine since their original deploys.

## The five-layer onion

Each layer hid the next. Took five distinct fixes to get end-to-end delivery.

### Layer 1 — No mail config at all

`/usr/local/tomcat/webapps/<mine>/WEB-INF/web.properties` had no
`mail.host` / `mail.smtp.*` block. InterMine fell back to upstream defaults in
`global.web.properties` which pointed at `mail.flymine.org` — a hostname that
no longer resolves (FlyMine migrated to Outlook365; the `mail.` subdomain
was retired). Container's JVM threw `UnknownHostException`.

**Fix:** added a complete `mail.*` block to `web.properties` +
`classes/intermine.properties` with AWS SES SMTP credentials provided by IT
(send-only IAM user `alliancemine-ses-smtp` in account 100225593120).

### Layer 2 — JavaMail 1.4 can't negotiate TLS 1.2

`WEB-INF/lib/mail.jar` was JavaMail 1.4 (manifest dated 2005-12-09). Predates
TLS 1.2 entirely. JavaMail 1.5.5+ is the minimum that supports modern TLS.
The container's JVM is Java 11 (with TLS 1.2/1.3 enabled) but the bundled
JavaMail couldn't negotiate — every STARTTLS attempt returned
`SSLHandshakeException: No appropriate protocol`.

**Fix:** replaced `mail.jar` with `javax.mail-1.6.2.jar` from Maven Central:

```bash
wget https://repo1.maven.org/maven2/com/sun/mail/javax.mail/1.6.2/javax.mail-1.6.2.jar
```

### Layer 3 — InterMine's MailUtils sets `From: ${mail.smtp.user}`

Once TLS worked, the SMTP conversation reached `MAIL FROM` + `RCPT TO`
successfully, then SES rejected at end-of-DATA with:

```
554 Transaction failed: User name is missing: 'AKIAROVPJF4QF3YXRSGZ'
```

`AKIAROVPJF4QF3YXRSGZ` is the SES SMTP username (an AWS access key ID).
That value was appearing as the message `From:` header. Decompiling
`MailUtils.class` revealed:

```java
if (StringUtils.isEmpty(smtpUser)) {
    msg.setFrom(new InternetAddress(mail.from));    // works
} else {
    msg.setReplyTo(InternetAddress.parse(mail.from, true));
    msg.setFrom(new InternetAddress(smtpUser));     // BUG: uses SMTP user as From
}
```

The upstream assumption: when SMTP auth is enabled, the SMTP username
*is* an email address (Gmail-style personal-account relay). That assumption
breaks with AWS SES, where the username is a 20-char IAM access key ID,
not an email. SES correctly rejects the malformed From header.

**Fix:** wrote a patched `MailUtils.java` (lives at
`patches/intermine/MailUtils.java` in this repo) that always uses `mail.from`
for the From header, regardless of `mail.smtp.user`. Compiled the patch
inside the container against the WAR's classpath, dropped the resulting
`MailUtils.class` + `MailUtils$1.class` into
`WEB-INF/classes/org/intermine/util/`. Tomcat's classloader searches
`WEB-INF/classes/` before `WEB-INF/lib/*.jar`, so the patched version
shadows the buggy one in `intermine-web.jar` without touching the jar.

### Layer 4 — `global.web.properties` mail.from override

Even with the patched MailUtils, mail.from could be wrong if multiple
properties files set it inconsistently. Three files were in play:

- `WEB-INF/web.properties` (per-mine override, set by us to `noreply@…`)
- `WEB-INF/classes/intermine.properties` (same override)
- `WEB-INF/global.web.properties` — **still had upstream default `mail.from=support@flymine.org`**

InterMine's `WebProperties` loader merges these and the precedence order
isn't fully predictable across versions. The global file was occasionally
winning, putting `support@flymine.org` in the From header. SES rejected
because the IAM user has no permission for the `flymine.org` domain.

**Fix:** patched the global.web.properties file to also say
`mail.from=noreply@alliancegenome.org`.

### Layer 5 — IT-side SES setup (turned out to already be in place)

Required SES state, all already configured by IT before we started:

- `alliancegenome.org` domain verified (DKIM CNAMEs in Route 53)
- Production access granted (out of sandbox — 50K/day quota)
- IAM user `alliancemine-ses-smtp` with `AllianceMineSESSendOnly` policy
  permitting `ses:SendRawEmail` + `ses:SendEmail`
- SES SMTP credentials derived for us-east-1 region

Test we ran to confirm SES side was healthy (before debugging InterMine):

```bash
aws ses send-email --region us-east-1 \
  --from noreply@alliancegenome.org \
  --destination ToAddresses=paulo.nuin@gmail.com \
  --message 'Subject={Data=test},Body={Text={Data=test}}'
# Returns MessageId → confirmed SES + verified domain + IAM all work
```

Useful because it isolated the bug to JavaMail / InterMine, not SES.

## What landed (per-container, applied 2026-05-27)

Each of the three mines (`mousemine-1x`, `wormmine`, `alliancemine-9.0.0-rc20`)
on multitenant got:

1. `mail.*` block appended to `WEB-INF/web.properties` +
   `WEB-INF/classes/intermine.properties` (mail.host, mail.smtp.port=587,
   mail.smtp.auth=true, mail.smtp.starttls.enable=true, mail.smtp.user=
   the SES SMTP username, mail.server.password= the SES SMTP password,
   mail.from=noreply@alliancegenome.org)
2. `WEB-INF/lib/mail.jar` (or `mail-1.4.jar` on wormmine) renamed to
   `mail.jar.bak.<timestamp>`; `javax.mail-1.6.2.jar` downloaded from
   Maven Central into the same dir
3. Patched `MailUtils.class` + `MailUtils$1.class` compiled from
   `patches/intermine/MailUtils.java` and dropped into
   `WEB-INF/classes/org/intermine/util/`
4. `WEB-INF/global.web.properties` `mail.from` updated from
   `support@flymine.org` to `noreply@alliancegenome.org`
5. Container restarted (for alliancemine, with the bag-upgrade
   `pg_terminate_backend` kick per `docs/RUNBOOK_ALLIANCEMINE_RESTART.md` —
   20 idle Hikari connections kicked at t+90s; recovery complete at t+110s)

Test verification (mousemine, MessageId-equivalent screenshot):

- Visit `/login.do` → click "Forgot password" → enter `paulo.nuin@gmail.com`
- Reset email arrives within seconds at the inbox, From
  `noreply@alliancegenome.org`, Subject "Password reset for MouseMine",
  with the working reset link

## Persistence

These five changes live in the **unpacked WAR inside the running container**.
They survive container restart but DO NOT survive:

- Container recreation from the image (`docker compose down && up`)
- Image rebuild from `docker/<mine>/`
- WAR redeploy via `cargoRedeployRemote` from AllianceMineDev

For permanence we ship in this repo:

| File | Purpose |
|---|---|
| `patches/intermine/MailUtils.java` | The Java source of the patched MailUtils — reproducible |
| `scripts/patch_mail_post_deploy.sh` | Idempotent script: takes `<container-name> <mine-name>`, applies layers 2-4 against a running container |
| `docker/<mine>/properties/<mine>.properties.template` | Adds the `mail.*` block (envsubst-templated). Empty values render harmlessly if env not set, matching pre-fix behavior |
| `docker/<mine>/.env.example` | Documents the `MAIL_*` env vars + warns about the post-deploy script |

After any WAR redeploy from AllianceMineDev or fresh container creation, run:

```bash
ssh multitenant
cd /path/to/agr_intermine_builder  # or scp the script + patches/
./scripts/patch_mail_post_deploy.sh <container-name> <mine-name>
docker restart <container-name>
# (for alliancemine: docs/RUNBOOK_ALLIANCEMINE_RESTART.md kick procedure)
```

## Credentials handling

The SES SMTP credentials appeared in chat during this debugging session.
They're send-only and rotation is one IAM step away, so risk is low, but
IT can rotate at any time and we'll just re-run the script with new values.
Operators should:

- Keep creds in operator-local `.env` files (never committed)
- Or migrate to AWS Secrets Manager per the existing
  `IntermineStagePropertiesFile` pattern (see `docs/WORMMINE_MULTITENANT_SETUP.md`)

## Cross-references

- `docs/OAUTH_AND_MAIL_CONFIG_GAP.md` — original audit that surfaced this gap
- `docs/RUNBOOK_ALLIANCEMINE_RESTART.md` — bag-upgrade kick procedure used
  during alliancemine restart after applying the patches
- `docs/WORMMINE_MULTITENANT_SETUP.md` — Secrets Manager pattern for
  potentially relocating the SES creds out of operator `.env`
- `patches/intermine/MailUtils.java` — the patch source
- `scripts/patch_mail_post_deploy.sh` — the post-deploy applicator
- IT contact: whoever provisioned the SES IAM user
  `alliancemine-ses-smtp` (account 100225593120, region us-east-1)
