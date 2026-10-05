#!/usr/bin/env bash
# bake_mail_into_war.sh — bake the SES "forgot password" mail fix into a built
# InterMine WAR, so the fix survives image rebuilds / WAR redeploys and the
# post-deploy patch_mail_post_deploy.sh is no longer required.
#
# Applies the same three layers as patch_mail_post_deploy.sh, but against a
# packaged .war (or an exploded WEB-INF dir) at BUILD time instead of a running
# container:
#   1. Swap the bundled JavaMail 1.4 (2005, no TLS 1.2) -> javax.mail-1.6.2.jar
#   2. Compile patches/intermine/MailUtils.java and drop MailUtils.class into
#      WEB-INF/classes/ (shadows the buggy one in intermine-web.jar that sets
#      From: = mail.smtp.user, which AWS SES rejects with "554 User name is missing")
#   3. Rewrite WEB-INF/global.web.properties mail.from=support@flymine.org (dead
#      upstream default) -> noreply@alliancegenome.org
#
# The mail.* SMTP creds themselves are NOT baked here — they render into
# web.properties from the MAIL_* env vars at deploy time (see each mine's
# .env / .env.example and *.properties.template). This script only fixes the
# two things the template can't: the JavaMail jar and the MailUtils/global bug.
#
# Usage (run in the build container, after the WAR is built; needs javac):
#   bake_mail_into_war.sh <path-to.war | path-to-exploded-WEB-INF-parent>
# Wire it into a build by adding one line after the WAR is produced, e.g. in
# flymine finalize_build.sh after `:webapp:war`:
#   /root/scripts/bake_mail_into_war.sh "$WAR"
#
# Idempotent. Env overrides:
#   MAILUTILS_SRC  path to MailUtils.java (default: <repo>/patches/intermine/MailUtils.java)
#   JAVAMAIL_JAR   path to a local javax.mail-1.6.2.jar (default: download from Maven Central)
#   MAIL_FROM_ADDR default noreply@alliancegenome.org
set -euo pipefail

TARGET="${1:?usage: $0 <path-to.war | exploded-webapp-dir>}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAILUTILS_SRC="${MAILUTILS_SRC:-$HERE/../patches/intermine/MailUtils.java}"
[ -f "$MAILUTILS_SRC" ] || MAILUTILS_SRC="/root/scripts/MailUtils.java"   # in-image fallback
MAIL_FROM_ADDR="${MAIL_FROM_ADDR:-noreply@alliancegenome.org}"
JM_URL="https://repo1.maven.org/maven2/com/sun/mail/javax.mail/1.6.2/javax.mail-1.6.2.jar"

[ -f "$MAILUTILS_SRC" ] || { echo "ERROR: MailUtils.java not found (set MAILUTILS_SRC)"; exit 1; }
command -v javac >/dev/null || { echo "ERROR: javac not on PATH (run inside the build container)"; exit 1; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
BUILD="$WORK/build"          # javac output — kept OUTSIDE the exploded WAR root
IS_WAR=0
if [ -f "$TARGET" ]; then
    IS_WAR=1
    mkdir -p "$WORK/war"
    ( cd "$WORK/war" && jar xf "$TARGET" )   # jar/unzip from the build JDK
    ROOT="$WORK/war"
elif [ -d "$TARGET/WEB-INF" ]; then
    ROOT="$TARGET"
else
    echo "ERROR: $TARGET is neither a .war nor an exploded webapp (no WEB-INF)"; exit 1
fi
LIB="$ROOT/WEB-INF/lib"; CLS="$ROOT/WEB-INF/classes"; GLOBAL="$ROOT/WEB-INF/global.web.properties"

# 1. JavaMail 1.6.2
if [ ! -f "$LIB/javax.mail-1.6.2.jar" ]; then
    if [ -n "${JAVAMAIL_JAR:-}" ] && [ -f "$JAVAMAIL_JAR" ]; then cp "$JAVAMAIL_JAR" "$LIB/javax.mail-1.6.2.jar";
    else wget -q "$JM_URL" -O "$LIB/javax.mail-1.6.2.jar"; fi
fi
for j in "$LIB"/mail.jar "$LIB"/mail-1.4.jar "$LIB"/mail-1.4.*.jar; do [ -f "$j" ] && rm -f "$j"; done
echo "  [1/3] JavaMail -> javax.mail-1.6.2.jar"

# 2. MailUtils.class (compile against the WAR's own lib)
mkdir -p "$BUILD"
javac -cp "$LIB/*" -d "$BUILD" "$MAILUTILS_SRC"
mkdir -p "$CLS/org/intermine/util"
cp "$BUILD"/org/intermine/util/*.class "$CLS/org/intermine/util/"
echo "  [2/3] MailUtils.class shadowed into WEB-INF/classes"

# 3. global.web.properties mail.from
if [ -f "$GLOBAL" ]; then
    sed -i "s|^mail.from=support@flymine.org|mail.from=$MAIL_FROM_ADDR|" "$GLOBAL"
    echo "  [3/3] global.web.properties mail.from=$(grep '^mail.from=' "$GLOBAL" | cut -d= -f2-)"
else
    echo "  [3/3] no global.web.properties (skipped)"
fi

# Repack if we started from a .war (absolute path so the cd into ROOT is safe)
if [ "$IS_WAR" -eq 1 ]; then
    ABS_WAR="$(cd "$(dirname "$TARGET")" && pwd)/$(basename "$TARGET")"
    ( cd "$ROOT" && jar cf "$ABS_WAR.tmp" . ) && mv "$ABS_WAR.tmp" "$ABS_WAR"
    echo "  repacked -> $ABS_WAR"
fi
echo "  mail fix baked."
