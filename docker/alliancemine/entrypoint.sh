#!/bin/bash
set -e

echo "============================================"
echo "AllianceMine Build Container"
echo "============================================"

# ============================================
# Compile bio-sources and alliancemine (first run only)
# ============================================
compile_if_needed() {
    if [ ! -f /root/.needs_compile ]; then
        echo "Already compiled, skipping."
        return
    fi

    echo "First run: compiling bio-sources and alliancemine..."
    echo "This takes ~10-15 minutes with 32 GB RAM."

    echo "  [1/2] Building bio-sources..."
    cd /root/alliancemine-bio-sources
    ./gradlew clean --stacktrace
    ./gradlew install --stacktrace

    echo "  [2/2] Building alliancemine..."
    cd /root/alliancemine
    ./gradlew install --stacktrace

    # Cleanup Gradle caches to save space
    rm -rf /root/.gradle/caches/transforms-* \
           /root/.gradle/caches/journal-* \
           /tmp/*

    rm /root/.needs_compile
    echo "Compilation complete."
}

compile_if_needed

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

    # Profile DB:
    #   production → alliancemine_userprofile (the real one)
    #   test       → alliancemine_userprofile_test (safe default)
    #   test + COPY_PROFILE_DB=true → fresh copy as alliancemine_userprofile_rcN
    if [ "${BUILD_TYPE}" = "production" ]; then
        export RDS_PROFILE_DB_NAME="alliancemine_userprofile"
    elif [ "${COPY_PROFILE_DB}" = "true" ]; then
        export RDS_PROFILE_DB_NAME="alliancemine_userprofile_rc${RC_NUMBER:-1}"
    else
        export RDS_PROFILE_DB_NAME="alliancemine_userprofile_test"
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

    # Set defaults for optional env vars (envsubst doesn't support ${VAR:-default})
    export DEPLOY_PORT="${DEPLOY_PORT:-8080}"
    export DEPLOY_HOST="${DEPLOY_HOST:-localhost}"
    export DEPLOY_URL="${DEPLOY_URL:-http://${DEPLOY_HOST}:${DEPLOY_PORT}}"
    export WEBAPP_BASEURL="${WEBAPP_BASEURL:-http://localhost:8080}"
    export DEPLOY_MANAGER="${DEPLOY_MANAGER:-manager}"
    export DEPLOY_PASSWORD="${DEPLOY_PASSWORD:-manager}"
    export SUPERUSER_ACCOUNT="${SUPERUSER_ACCOUNT:-superuser@mail_account}"
    export SUPERUSER_PASSWORD="${SUPERUSER_PASSWORD:-secret}"
    export SOLR_INDEX_URL="${SOLR_INDEX_URL:-http://localhost:8983/solr/alliancemine-search}"
    export SOLR_AUTOCOMPLETE_URL="${SOLR_AUTOCOMPLETE_URL:-http://localhost:8983/solr/alliancemine-autocomplete}"

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

    # Profile DB setup
    if ! db_exists "${RDS_PROFILE_DB_NAME}"; then
        if [ "${BUILD_TYPE}" != "production" ] && db_exists "alliancemine_userprofile"; then
            # Test builds: copy from production profile as template
            echo "  Copying profile DB: alliancemine_userprofile -> ${RDS_PROFILE_DB_NAME}"
            ${PSQL} -d postgres -c \
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='alliancemine_userprofile' AND pid <> pg_backend_pid();" \
                2>/dev/null || true
            ${PSQL} -d postgres -c \
                "CREATE DATABASE \"${RDS_PROFILE_DB_NAME}\" TEMPLATE \"alliancemine_userprofile\";"
            echo "  Profile DB copied successfully"
        else
            # Production builds or no source to copy from
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
        echo "Mode: PROMOTE TO PRODUCTION"
        shift
        exec python3 /root/scripts/promote_to_production.py \
            --release "${ALLIANCE_RELEASE}" \
            ${DEPLOY_HOST:+--deploy-host "${DEPLOY_HOST}"} \
            "$@"
        ;;

    promote-db)
        echo ""
        echo "Mode: PROMOTE DB ONLY"
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

    release)
        echo ""
        echo "Mode: RELEASE"
        shift
        exec python3 /root/scripts/release.py \
            ${DEPLOY_HOST:+--tomcat-host "${DEPLOY_HOST}"} \
            ${DEPLOY_PORT:+--tomcat-port "${DEPLOY_PORT}"} \
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
