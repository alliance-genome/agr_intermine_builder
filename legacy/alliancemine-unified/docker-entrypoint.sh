#!/bin/bash
set -e

# ============================================
# AllianceMine Docker Entrypoint
# ============================================
# Handles initialization, configuration, and startup
# of Tomcat and InterMine build processes.
# ============================================

echo "============================================"
echo "🚀 AllianceMine Unified Container"
echo "============================================"
echo "Version: ${ALLIANCE_RELEASE}"
echo "Tomcat: ${TOMCAT_PORT}"
echo "RDS: ${RDS_HOST}:${RDS_PORT}"
echo "============================================"

# ============================================
# Wait for RDS PostgreSQL
# ============================================
wait_for_postgres() {
    echo "⏳ Waiting for PostgreSQL at ${RDS_HOST}:${RDS_PORT}..."

    MAX_ATTEMPTS=60
    ATTEMPT=0

    until pg_isready -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -t 5 2>/dev/null; do
        ATTEMPT=$((ATTEMPT+1))
        if [ $ATTEMPT -ge $MAX_ATTEMPTS ]; then
            echo "❌ Failed to connect to PostgreSQL after $MAX_ATTEMPTS attempts"
            exit 1
        fi
        echo "   Waiting... (attempt $ATTEMPT/$MAX_ATTEMPTS)"
        sleep 2
    done

    echo "✅ PostgreSQL is ready!"
}

# ============================================
# Configure InterMine Properties
# ============================================
configure_intermine() {
    echo "📝 Configuring InterMine properties..."

    # Generate properties file from template
    envsubst < /opt/intermine/.intermine/alliancemine.properties.template \
             > /opt/intermine/.intermine/alliancemine.properties

    # Also copy to the alliancemine directory where Gradle expects it
    cp /opt/intermine/.intermine/alliancemine.properties \
       /opt/intermine/alliancemine/alliancemine.properties

    # Set up .pgpass for passwordless psql access
    echo "${RDS_HOST}:${RDS_PORT}:*:${RDS_USER}:${RDS_PASSWORD}" > ~/.pgpass
    chmod 600 ~/.pgpass

    echo "✅ InterMine configured"
}

# ============================================
# Construct and Sanitize Database Names
# ============================================
sanitize_database_names() {
    echo "📦 Constructing database names..."

    # Construct main database name from release version and suffix
    # Replace dots with underscores: 8.3.0 -> 8_3_0
    RELEASE_SANITIZED=$(echo "${ALLIANCE_RELEASE}" | tr '.' '_')
    SAFE_DB_NAME="alliancemine_${RELEASE_SANITIZED}${DB_VERSION_SUFFIX}"

    # Profile database is fixed (shared across all releases)
    SAFE_PROFILE_DB_NAME="alliancemine_userprofile"

    # Update environment variables with sanitized names for use by InterMine
    export RDS_DB_NAME="${SAFE_DB_NAME}"
    export RDS_PROFILE_DB_NAME="${SAFE_PROFILE_DB_NAME}"

    echo "   Main database: ${RDS_DB_NAME}"
    echo "   Profile database: ${RDS_PROFILE_DB_NAME}"
}

# ============================================
# Check and Create Databases
# ============================================
setup_databases() {
    echo "📦 Checking databases in RDS..."

    # Export password for psql
    export PGPASSWORD="${RDS_PASSWORD}"

    # Check main database
    if ! psql -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -d postgres \
         -lqt | cut -d \| -f 1 | grep -qw "${RDS_DB_NAME}"; then
        echo "   Creating main database: ${RDS_DB_NAME}"
        psql -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -d postgres \
             -c "CREATE DATABASE \"${RDS_DB_NAME}\";"
        echo "   ✅ Main database created: ${RDS_DB_NAME}"
    else
        echo "   ✅ Main database exists: ${RDS_DB_NAME}"
    fi

    # Check profile database (shared across all releases)
    if ! psql -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -d postgres \
         -lqt | cut -d \| -f 1 | grep -qw "${RDS_PROFILE_DB_NAME}"; then
        echo "   Creating profile database: ${RDS_PROFILE_DB_NAME}"
        psql -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -d postgres \
             -c "CREATE DATABASE \"${RDS_PROFILE_DB_NAME}\";"
        echo "   ✅ Profile database created: ${RDS_PROFILE_DB_NAME}"
    else
        echo "   ✅ Profile database exists: ${RDS_PROFILE_DB_NAME}"
    fi

    # Check items database (for data integration staging)
    ITEMS_DB_NAME="alliancemine_items"
    if ! psql -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -d postgres \
         -lqt | cut -d \| -f 1 | grep -qw "${ITEMS_DB_NAME}"; then
        echo "   Creating items database: ${ITEMS_DB_NAME}"
        psql -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -d postgres \
             -c "CREATE DATABASE \"${ITEMS_DB_NAME}\";"
        echo "   ✅ Items database created: ${ITEMS_DB_NAME}"
    else
        echo "   ✅ Items database exists: ${ITEMS_DB_NAME}"
    fi
}

# ============================================
# Start Tomcat
# ============================================
start_tomcat() {
    echo "🌐 Starting Tomcat on port ${TOMCAT_PORT}..."

    # Start Tomcat in foreground (this keeps the container running)
    exec ${CATALINA_HOME}/bin/catalina.sh run
}

# ============================================
# Build InterMine (for 'build' command)
# ============================================
build_intermine() {
    echo "🏗️  Starting InterMine build process..."

    cd /opt/intermine/alliancemine

    # Run build script
    if [ -f "/opt/intermine/scripts/build_full.py" ]; then
        python3 /opt/intermine/scripts/build_full.py
    else
        echo "❌ Build script not found"
        exit 1
    fi
}

# ============================================
# Main Entrypoint Logic
# ============================================

# Always wait for PostgreSQL and configure
wait_for_postgres
sanitize_database_names
configure_intermine
setup_databases

# Handle different commands
case "$1" in
    build)
        echo "📋 Mode: BUILD"
        build_intermine
        ;;

    run)
        echo "📋 Mode: RUN (Database build testing - no Tomcat)"
        echo "ℹ️  Container started. Use 'docker exec -it alliancemine bash' to access shell."
        echo "ℹ️  You can manually run database builds from /opt/intermine/alliancemine"

        # Keep container alive
        tail -f /dev/null
        ;;

    bash|sh)
        echo "📋 Mode: SHELL"
        exec /bin/bash
        ;;

    *)
        # Default: run the provided command
        echo "📋 Mode: CUSTOM COMMAND"
        exec "$@"
        ;;
esac
