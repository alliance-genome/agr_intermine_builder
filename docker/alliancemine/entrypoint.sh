#!/bin/bash
set -e

echo "============================================"
echo "AllianceMine Build Container"
echo "============================================"

# ============================================
# Resolve Alliance Release from FMS API
# ============================================
resolve_release() {
    if [ -n "${ALLIANCE_RELEASE}" ]; then
        echo "Alliance Release: ${ALLIANCE_RELEASE} (from env)"
        return
    fi

    # Default to "next" release — that's what we're building toward
    local release_type="${FMS_RELEASE_TYPE:-next}"
    local api_url="https://fms.alliancegenome.org/api/releaseversion/${release_type}"

    echo "Fetching ${release_type} release version from FMS API..."
    local response
    response=$(wget -qO- "${api_url}" 2>/dev/null) || {
        echo "ERROR: Could not reach FMS API at ${api_url}"
        echo "Set ALLIANCE_RELEASE manually or check network connectivity."
        exit 1
    }

    # Parse releaseVersion from JSON (no jq in Alpine by default, use python3)
    export ALLIANCE_RELEASE
    ALLIANCE_RELEASE=$(echo "${response}" | python3 -c "import sys,json; print(json.load(sys.stdin)['releaseVersion'])")

    if [ -z "${ALLIANCE_RELEASE}" ]; then
        echo "ERROR: FMS API returned no releaseVersion"
        exit 1
    fi

    echo "Alliance Release: ${ALLIANCE_RELEASE} (from FMS API ${release_type})"
}

# ============================================
# Auto-detect next RC number from RDS
# ============================================
resolve_rc_number() {
    # Only relevant for test builds
    if [ "${BUILD_TYPE}" = "production" ]; then
        return
    fi

    # If RC_NUMBER is already set, use it
    if [ -n "${RC_NUMBER}" ]; then
        echo "RC Number: ${RC_NUMBER} (from env)"
        return
    fi

    local ver_sanitized
    ver_sanitized=$(echo "${ALLIANCE_RELEASE}" | tr '.' '_')
    local pattern="alliancemine_${ver_sanitized}_rc"

    echo "Auto-detecting next RC number..."
    export PGPASSWORD="${RDS_PASSWORD}"

    # Query RDS for existing RC databases matching this version
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

    # Sanitize version: 8.3.0 -> 8_3_0
    RELEASE_SANITIZED=$(echo "${ALLIANCE_RELEASE}" | tr '.' '_')

    # Build type determines naming
    if [ "${BUILD_TYPE}" = "production" ]; then
        export RDS_DB_NAME="alliancemine_${RELEASE_SANITIZED}"
    else
        # Test/RC builds: alliancemine_8_3_0_rc1
        RC="${RC_NUMBER:-1}"
        export RDS_DB_NAME="alliancemine_${RELEASE_SANITIZED}_rc${RC}"
    fi

    # Profile DB: shared by default, or isolated copy for test builds
    PROFILE_SOURCE="alliancemine_userprofile"
    if [ "${BUILD_TYPE}" != "production" ] && [ "${COPY_PROFILE_DB}" = "true" ]; then
        export RDS_PROFILE_DB_NAME="alliancemine_userprofile_rc${RC_NUMBER:-1}"
    else
        export RDS_PROFILE_DB_NAME="${PROFILE_SOURCE}"
    fi

    # Items DB (intermediary, can be dropped after build)
    export RDS_ITEMS_DB_NAME="alliancemine_items"

    echo "  Main database:    ${RDS_DB_NAME}"
    echo "  Profile database: ${RDS_PROFILE_DB_NAME}"
    echo "  Items database:   ${RDS_ITEMS_DB_NAME}"
}

# ============================================
# Configure InterMine Properties
# ============================================
configure_properties() {
    echo "Configuring InterMine properties..."

    envsubst < /root/.intermine/alliancemine.properties.template \
             > /root/.intermine/alliancemine.properties

    # Gradle also looks in the project directory
    cp /root/.intermine/alliancemine.properties \
       /root/alliancemine/alliancemine.properties 2>/dev/null || true

    # Set up .pgpass for passwordless psql
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

    # Helper: check if a database exists
    db_exists() {
        ${PSQL} -d postgres -lqt | cut -d \| -f 1 | grep -qw "$1"
    }

    # Create main DB and items DB if they don't exist
    for DB_NAME in "${RDS_DB_NAME}" "${RDS_ITEMS_DB_NAME}"; do
        if ! db_exists "${DB_NAME}"; then
            echo "  Creating database: ${DB_NAME}"
            ${PSQL} -d postgres -c "CREATE DATABASE \"${DB_NAME}\";"
        else
            echo "  Database exists: ${DB_NAME}"
        fi
    done

    # Profile DB: if COPY_PROFILE_DB=true and this is a test build,
    # copy from the shared alliancemine_userprofile as a template
    if [ "${COPY_PROFILE_DB}" = "true" ] && [ "${BUILD_TYPE}" != "production" ]; then
        if ! db_exists "${RDS_PROFILE_DB_NAME}"; then
            if db_exists "alliancemine_userprofile"; then
                echo "  Copying profile DB: alliancemine_userprofile -> ${RDS_PROFILE_DB_NAME}"
                # Terminate connections to source DB (required for TEMPLATE)
                ${PSQL} -d postgres -c \
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='alliancemine_userprofile' AND pid <> pg_backend_pid();" \
                    2>/dev/null || true
                ${PSQL} -d postgres -c \
                    "CREATE DATABASE \"${RDS_PROFILE_DB_NAME}\" TEMPLATE \"alliancemine_userprofile\";"
                echo "  Profile DB copied successfully"
            else
                echo "  Source profile DB 'alliancemine_userprofile' not found, creating empty"
                ${PSQL} -d postgres -c "CREATE DATABASE \"${RDS_PROFILE_DB_NAME}\";"
            fi
        else
            echo "  Profile database exists: ${RDS_PROFILE_DB_NAME}"
        fi
    else
        # Shared profile DB (default)
        if ! db_exists "${RDS_PROFILE_DB_NAME}"; then
            echo "  Creating database: ${RDS_PROFILE_DB_NAME}"
            ${PSQL} -d postgres -c "CREATE DATABASE \"${RDS_PROFILE_DB_NAME}\";"
        else
            echo "  Database exists: ${RDS_PROFILE_DB_NAME}"
        fi
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
    build)
        echo ""
        echo "Mode: BUILD"
        shift
        exec python3 /root/scripts/build_full.py \
            --build-type "${BUILD_TYPE:-test}" \
            --release "${ALLIANCE_RELEASE}" \
            ${RC_NUMBER:+--rc "${RC_NUMBER}"} \
            ${DEPLOY_HOST:+--deploy-host "${DEPLOY_HOST}"} \
            ${DEPLOY_PORT:+--deploy-port "${DEPLOY_PORT}"} \
            "$@"
        ;;

    promote)
        echo ""
        echo "Mode: PROMOTE"
        shift
        exec python3 /root/scripts/promote_db.py \
            --release "${ALLIANCE_RELEASE}" \
            "$@"
        ;;

    deploy)
        echo ""
        echo "Mode: DEPLOY"
        shift
        exec python3 /root/scripts/deploy_war.py "$@"
        ;;

    extract)
        echo ""
        echo "Mode: EXTRACT DATA"
        shift
        exec python3 /root/scripts/extract_data.py \
            --release "${ALLIANCE_RELEASE}" \
            "$@"
        ;;

    bash|sh)
        echo ""
        echo "Mode: SHELL"
        exec /bin/bash
        ;;

    *)
        # Default: run the provided command
        exec "$@"
        ;;
esac
