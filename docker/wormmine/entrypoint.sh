#!/bin/bash
set -e

echo "============================================"
echo "WormMine Build Container"
echo "============================================"

# ============================================
# Compile bio-sources and wormmine (first run only)
# ============================================
compile_if_needed() {
    if [ ! -f /root/.needs_compile ]; then
        echo "Already compiled, skipping."
        return
    fi

    echo "First run: compiling wormmine-bio-sources and wormmine..."
    echo "This takes ~10-15 minutes."

    echo "  [1/2] Building wormmine-bio-sources..."
    cd /root/wormmine-bio-sources
    ./gradlew clean --stacktrace
    ./gradlew install --stacktrace

    echo "  [2/2] Building wormmine..."
    cd /root/wormmine
    ./gradlew install --stacktrace

    rm -rf /root/.gradle/caches/transforms-* \
           /root/.gradle/caches/journal-* \
           /tmp/*

    rm /root/.needs_compile
    echo "Compilation complete."
}

compile_if_needed

# ============================================
# Resolve WormBase Release
# Like FlyMine, no FMS API. Operator sets WORMBASE_RELEASE explicitly,
# or we default to today's date for self-describing tags.
# Convention: use the WS-prefixed release the build aligns with, e.g. WS298.
# ============================================
resolve_release() {
    if [ -n "${WORMBASE_RELEASE}" ]; then
        echo "WormBase Release: ${WORMBASE_RELEASE} (from env)"
        return
    fi

    export WORMBASE_RELEASE
    WORMBASE_RELEASE="$(date +%Y%m%d)"
    echo "WORMBASE_RELEASE not set, defaulting to ${WORMBASE_RELEASE}"
}

# ============================================
# Auto-detect next RC number from RDS
# ============================================
resolve_rc_number() {
    if [ "${BUILD_TYPE}" = "production" ]; then
        return
    fi

    if [ -n "${RC_NUMBER}" ]; then
        echo "RC Number: ${RC_NUMBER} (from env)"
        return
    fi

    local ver_sanitized
    ver_sanitized=$(echo "${WORMBASE_RELEASE}" | tr '.' '_')
    local pattern="wormmine_${ver_sanitized}_rc"

    echo "Auto-detecting next RC number..."
    export PGPASSWORD="${RDS_PASSWORD}"

    local max_rc
    max_rc=$(psql -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -d postgres -tAc \
        "SELECT coalesce(max(
            substring(datname from '${pattern}([0-9]+)$')::int
        ), 0)
        FROM pg_database
        WHERE datname ~ '^${pattern}[0-9]+$'" 2>/dev/null) || max_rc=0

    export RC_NUMBER=$(( ${max_rc:-0} + 1 ))
    echo "RC Number: ${RC_NUMBER} (auto-incremented, found rc${max_rc:-0} on RDS)"
}

resolve_release

echo "Build Type:       ${BUILD_TYPE:-test}"
echo "RDS:              ${RDS_HOST}:${RDS_PORT}"
echo "============================================"

# ============================================
# Wait for RDS PostgreSQL
# ============================================
wait_for_postgres() {
    echo "Waiting for PostgreSQL at ${RDS_HOST}:${RDS_PORT}..."

    MAX_ATTEMPTS=60
    ATTEMPT=0

    until pg_isready -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -t 5 2>/dev/null; do
        ATTEMPT=$((ATTEMPT+1))
        if [ $ATTEMPT -ge $MAX_ATTEMPTS ]; then
            echo "ERROR: Failed to connect to PostgreSQL after $MAX_ATTEMPTS attempts"
            exit 1
        fi
        echo "  Waiting... (attempt $ATTEMPT/$MAX_ATTEMPTS)"
        sleep 2
    done

    echo "PostgreSQL is ready!"
}

# ============================================
# Construct Database Names
# ============================================
construct_db_names() {
    echo "Constructing database names..."

    RELEASE_SANITIZED=$(echo "${WORMBASE_RELEASE}" | tr '.' '_')

    if [ "${BUILD_TYPE}" = "production" ]; then
        export RDS_DB_NAME="wormmine_${RELEASE_SANITIZED}"
    else
        RC="${RC_NUMBER:-1}"
        export RDS_DB_NAME="wormmine_${RELEASE_SANITIZED}_rc${RC}"
    fi

    if [ "${BUILD_TYPE}" = "production" ]; then
        export RDS_PROFILE_DB_NAME="wormmine_userprofile"
    elif [ "${COPY_PROFILE_DB}" = "true" ]; then
        export RDS_PROFILE_DB_NAME="wormmine_userprofile_rc${RC_NUMBER:-1}"
    else
        export RDS_PROFILE_DB_NAME="wormmine_userprofile_test"
    fi

    export RDS_ITEMS_DB_NAME="wormmine_items"

    echo "  Main database:    ${RDS_DB_NAME}"
    echo "  Profile database: ${RDS_PROFILE_DB_NAME}"
    echo "  Items database:   ${RDS_ITEMS_DB_NAME}"
}

# ============================================
# Configure InterMine Properties
# ============================================
configure_properties() {
    echo "Configuring InterMine properties..."

    export DEPLOY_PORT="${DEPLOY_PORT:-8080}"
    export DEPLOY_HOST="${DEPLOY_HOST:-localhost}"
    export DEPLOY_URL="${DEPLOY_URL:-http://${DEPLOY_HOST}:${DEPLOY_PORT}}"
    export WEBAPP_BASEURL="${WEBAPP_BASEURL:-http://localhost:8080}"
    export DEPLOY_MANAGER="${DEPLOY_MANAGER:-manager}"
    export DEPLOY_PASSWORD="${DEPLOY_PASSWORD:-manager}"
    export SUPERUSER_ACCOUNT="${SUPERUSER_ACCOUNT:-superuser@mail_account}"
    export SUPERUSER_PASSWORD="${SUPERUSER_PASSWORD:-secret}"

    envsubst < /root/.intermine/wormmine.properties.template \
             > /root/.intermine/wormmine.properties

    cp /root/.intermine/wormmine.properties \
       /root/wormmine/wormmine.properties 2>/dev/null || true

    echo "${RDS_HOST}:${RDS_PORT}:*:${RDS_USER}:${RDS_PASSWORD}" > /root/.pgpass
    chmod 600 /root/.pgpass

    echo "Properties configured"
}

# ============================================
# Create Databases if Needed
# ============================================
setup_databases() {
    echo "Checking databases in RDS..."
    export PGPASSWORD="${RDS_PASSWORD}"

    local PSQL="psql -h ${RDS_HOST} -p ${RDS_PORT} -U ${RDS_USER}"

    db_exists() {
        ${PSQL} -d postgres -lqt | cut -d \| -f 1 | grep -qw "$1"
    }

    for DB_NAME in "${RDS_DB_NAME}" "${RDS_ITEMS_DB_NAME}"; do
        if ! db_exists "${DB_NAME}"; then
            echo "  Creating database: ${DB_NAME}"
            ${PSQL} -d postgres -c "CREATE DATABASE \"${DB_NAME}\";"
        else
            echo "  Database exists: ${DB_NAME}"
        fi
    done

    if ! db_exists "${RDS_PROFILE_DB_NAME}"; then
        if [ "${BUILD_TYPE}" != "production" ] && db_exists "wormmine_userprofile"; then
            echo "  Copying profile DB: wormmine_userprofile -> ${RDS_PROFILE_DB_NAME}"
            ${PSQL} -d postgres -c \
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='wormmine_userprofile' AND pid <> pg_backend_pid();" \
                2>/dev/null || true
            ${PSQL} -d postgres -c \
                "CREATE DATABASE \"${RDS_PROFILE_DB_NAME}\" TEMPLATE \"wormmine_userprofile\";"
            echo "  Profile DB copied successfully"
        else
            echo "  Creating database: ${RDS_PROFILE_DB_NAME}"
            ${PSQL} -d postgres -c "CREATE DATABASE \"${RDS_PROFILE_DB_NAME}\";"
        fi
    else
        echo "  Profile database exists: ${RDS_PROFILE_DB_NAME}"
    fi
}

# ============================================
# Main
# ============================================

wait_for_postgres
resolve_rc_number
construct_db_names
configure_properties
setup_databases

# Handle commands
case "$1" in
    bash|sh)
        echo ""
        echo "Mode: SHELL"
        exec /bin/bash
        ;;

    *)
        if [ $# -eq 0 ]; then
            exec /bin/bash
        else
            exec "$@"
        fi
        ;;
esac
