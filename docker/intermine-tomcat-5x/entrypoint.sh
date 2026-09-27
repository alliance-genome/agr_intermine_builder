#!/bin/bash
# entrypoint for intermine-tomcat:agr-5x-runtime
#
# Renders /usr/local/tomcat/conf/tomcat-users.xml from the template using MANAGER_USER and
# MANAGER_PASSWORD, then execs catalina. The manager credentials are not baked into the image
# (it lives in ECR, anyone with pull access can read it) — supply them at `docker run`.

set -euo pipefail

: "${MANAGER_USER:=manager}"
: "${MANAGER_PASSWORD:=manager}"

if [[ "$MANAGER_PASSWORD" == "manager" ]]; then
    echo "WARNING: MANAGER_PASSWORD is the default 'manager'. Set -e MANAGER_PASSWORD=<secret> in production." >&2
fi

export MANAGER_USER MANAGER_PASSWORD

envsubst < /usr/local/tomcat/conf/tomcat-users.template.xml \
    > /usr/local/tomcat/conf/tomcat-users.xml
chmod 600 /usr/local/tomcat/conf/tomcat-users.xml

exec "$@"
