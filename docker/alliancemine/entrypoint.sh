#!/bin/bash
set -e

echo "============================================"
echo "AllianceMine Build Container"
echo "============================================"
echo "Alliance Release: ${ALLIANCE_RELEASE}"
echo "Build Type:       ${BUILD_TYPE:-test}"
echo "RC Number:        ${RC_NUMBER:-none}"
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

    # Profile DB is shared across all versions
    export RDS_PROFILE_DB_NAME="alliancemine_userprofile"

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

    for DB_NAME in "${RDS_DB_NAME}" "${RDS_PROFILE_DB_NAME}" "${RDS_ITEMS_DB_NAME}"; do
        if ! psql -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -d postgres \
             -lqt | cut -d \| -f 1 | grep -qw "${DB_NAME}"; then
            echo "  Creating database: ${DB_NAME}"
            psql -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -d postgres \
                 -c "CREATE DATABASE \"${DB_NAME}\";"
        else
            echo "  Database exists: ${DB_NAME}"
        fi
    done
}

# ============================================
# Main
# ============================================

wait_for_postgres
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
