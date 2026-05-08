#!/bin/bash
# entrypoint for intermine-tomcat:agr-1x-runtime
#
# Renders /usr/local/tomcat/conf/tomcat-users.xml from template using
# MANAGER_USER and MANAGER_PASSWORD env vars. Then execs catalina.
#
# Why a template: the manager-script credentials should not be baked into
# the image (image lives in ECR, anyone with pull access reads it).
# Render at runtime from secrets.

set -euo pipefail

: "${MANAGER_USER:=manager}"
: "${MANAGER_PASSWORD:=manager}"

if [[ "$MANAGER_PASSWORD" == "manager" ]]; then
    echo "WARNING: MANAGER_PASSWORD is using the default 'manager'. Set it via -e MANAGER_PASSWORD=<secret> in production." >&2
fi

export MANAGER_USER MANAGER_PASSWORD

# Render tomcat-users.xml
envsubst < /usr/local/tomcat/conf/tomcat-users.template.xml \
    > /usr/local/tomcat/conf/tomcat-users.xml
chmod 600 /usr/local/tomcat/conf/tomcat-users.xml

# Hand off to catalina
exec "$@"
