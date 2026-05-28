#!/usr/bin/env bash
#
# patch_mail_post_deploy.sh — apply the mail/SES fixes to a deployed InterMine
# Tomcat container.
#
# Usage:
#   ./patch_mail_post_deploy.sh <container-name> <mine-name>
#   Example:
#     ./patch_mail_post_deploy.sh mousemine-1x mousemine
#     ./patch_mail_post_deploy.sh alliancemine-9.0.0-rc20 alliancemine
#     ./patch_mail_post_deploy.sh wormmine wormmine
#
# What it does (idempotent — safe to re-run after any redeploy):
#   1. Replaces the upstream InterMine 1.x mail.jar (JavaMail 1.4, 2005, no
#      TLS 1.2 support) with javax.mail-1.6.2.jar from Maven Central.
#   2. Compiles patches/intermine/MailUtils.java + drops the .class into
#      WEB-INF/classes/ (shadows the buggy version in intermine-web.jar).
#      The patch removes upstream InterMine's "set From header = mail.smtp.user"
#      behavior, which assumes the SMTP user is an email address (Gmail-style).
#      With AWS SES the SMTP user is an IAM access key ID and SES rejects with
#      "554 User name is missing".
#   3. Patches global.web.properties to override mail.from=support@flymine.org
#      (upstream default at a dead host) to noreply@alliancegenome.org.
#
# Requires (in caller env):
#   SSH access to the multitenant host (172.31.59.87) — script is meant to run
#   FROM the multitenant host (host's `docker exec` is used, not nested SSH).
#   Or use the wrapper:  ssh ec2-user@multitenant 'bash -s' < this_script.sh <args>
#
# Does NOT add the mail.* / SMTP creds block — those are set via env / per-mine
# .env or AWS Secrets Manager and rendered into web.properties at deploy. See
# docs/OAUTH_AND_MAIL_CONFIG_GAP.md.
#
# Does NOT restart the container. Restart separately after applying; for
# alliancemine, follow docs/RUNBOOK_ALLIANCEMINE_RESTART.md and watch for the
# bag-upgrade deadlock kick.

set -euo pipefail

CONTAINER="${1:?Usage: $0 <container-name> <mine-name>}"
MINE="${2:?Usage: $0 <container-name> <mine-name>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MAILUTILS_SRC="$REPO_ROOT/patches/intermine/MailUtils.java"

if [[ ! -f "$MAILUTILS_SRC" ]]; then
    echo "ERROR: MailUtils.java patch not found at $MAILUTILS_SRC"
    exit 1
fi

WAR_LIB="/usr/local/tomcat/webapps/$MINE/WEB-INF/lib"
WAR_CLASSES="/usr/local/tomcat/webapps/$MINE/WEB-INF/classes/org/intermine/util"
WAR_GLOBAL="/usr/local/tomcat/webapps/$MINE/WEB-INF/global.web.properties"

echo "=== Patching $CONTAINER ($MINE) ==="

# 1. JavaMail jar swap (idempotent)
echo "[1/3] JavaMail jar"
docker cp "$MAILUTILS_SRC" "$CONTAINER:/tmp/MailUtils.java"
docker exec "$CONTAINER" bash -c "
    LIB='$WAR_LIB'
    if [ ! -f \$LIB/javax.mail-1.6.2.jar ]; then
        wget -q https://repo1.maven.org/maven2/com/sun/mail/javax.mail/1.6.2/javax.mail-1.6.2.jar -O \$LIB/javax.mail-1.6.2.jar
    fi
    for j in \$LIB/mail.jar \$LIB/mail-*.jar; do
        [ -f \"\$j\" ] || continue
        mv \"\$j\" \"\$j.bak.\$(date +%Y%m%d_%H%M%S)\"
    done
    ls \$LIB | grep -iE 'mail|activ'
"

# 2. Compile + install patched MailUtils
echo "[2/3] MailUtils class"
docker exec "$CONTAINER" bash -c "
    LIB='$WAR_LIB'
    ACT=\$(ls \$LIB/activation*.jar \$LIB/javax.activation*.jar 2>/dev/null | head -1)
    CP=\"\$LIB/javax.mail-1.6.2.jar:\$LIB/intermine-web.jar:\$LIB/commons-lang-2.6.jar:\$ACT\"
    rm -rf /tmp/build && mkdir /tmp/build
    cd /tmp/build && javac -cp \"\$CP\" -d /tmp/build /tmp/MailUtils.java
    mkdir -p '$WAR_CLASSES'
    cp /tmp/build/org/intermine/util/*.class '$WAR_CLASSES'/
    ls -la '$WAR_CLASSES'/MailUtils*.class
"

# 3. global.web.properties mail.from patch
echo "[3/3] global.web.properties mail.from"
docker exec "$CONTAINER" bash -c "
    sed -i 's|^mail.from=support@flymine.org|mail.from=noreply@alliancegenome.org|' '$WAR_GLOBAL'
    grep ^mail.from '$WAR_GLOBAL'
"

echo ""
echo "Patches applied. Restart $CONTAINER to load."
echo "For alliancemine: follow docs/RUNBOOK_ALLIANCEMINE_RESTART.md (bag-upgrade kick)."
