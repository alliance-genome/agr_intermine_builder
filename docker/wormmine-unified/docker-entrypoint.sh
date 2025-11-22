#!/bin/bash
set -e

# ============================================
# WormMine Docker Entrypoint
# ============================================
# Handles initialization, configuration, and startup
# of Tomcat, Solr, and InterMine build processes.
# ============================================

echo "============================================"
echo "🪱 WormMine Unified Container"
echo "============================================"
echo "Version: ${WORMBASE_RELEASE}"
echo "Tomcat: ${TOMCAT_PORT}"
echo "Solr: ${SOLR_PORT}"
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
    envsubst < /opt/intermine/.intermine/wormmine.properties.template \
             > /opt/intermine/.intermine/wormmine.properties

    # Also copy to the wormmine directory where Gradle expects it
    cp /opt/intermine/.intermine/wormmine.properties \
       /opt/intermine/wormmine/wormmine.properties

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

    # Fixed database names for WormMine
    SAFE_DB_NAME="wormmine_final"
    SAFE_ITEMS_DB_NAME="wormmine_items"
    SAFE_PROFILE_DB_NAME="wormmine_userprofile"

    # Update environment variables with sanitized names
    export RDS_DB_NAME="${SAFE_DB_NAME}"
    export RDS_ITEMS_DB_NAME="${SAFE_ITEMS_DB_NAME}"
    export RDS_PROFILE_DB_NAME="${SAFE_PROFILE_DB_NAME}"

    echo "   Main database: ${RDS_DB_NAME}"
    echo "   Items database: ${RDS_ITEMS_DB_NAME}"
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
    if ! psql -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -d postgres \
         -lqt | cut -d \| -f 1 | grep -qw "${RDS_ITEMS_DB_NAME}"; then
        echo "   Creating items database: ${RDS_ITEMS_DB_NAME}"
        psql -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -d postgres \
             -c "CREATE DATABASE \"${RDS_ITEMS_DB_NAME}\";"
        echo "   ✅ Items database created: ${RDS_ITEMS_DB_NAME}"
    else
        echo "   ✅ Items database exists: ${RDS_ITEMS_DB_NAME}"
    fi
}

# ============================================
# Start Solr
# ============================================
start_solr() {
    echo "🔍 Starting Solr on port ${SOLR_PORT}..."

    # Ensure JAVA_HOME is set
    export JAVA_HOME=/opt/java/openjdk
    export PATH=$JAVA_HOME/bin:$PATH

    # Start Solr in background (use SOLR_HOME as base, not SOLR_HOME/data)
    /opt/solr/bin/solr start \
        -p ${SOLR_PORT} \
        -s ${SOLR_HOME} \
        -m ${SOLR_JAVA_MEM#-Xms} \
        -d /opt/solr/server

    # Wait for Solr to be fully started
    echo "⏳ Waiting for Solr to start..."
    sleep 5

    # Create WormMine cores if they don't exist
    if ! /opt/solr/bin/solr status | grep -q "wormmine-search"; then
        echo "📋 Creating Solr core: wormmine-search"
        /opt/solr/bin/solr create -c wormmine-search -p ${SOLR_PORT}
    fi

    if ! /opt/solr/bin/solr status | grep -q "wormmine-autocomplete"; then
        echo "📋 Creating Solr core: wormmine-autocomplete"
        /opt/solr/bin/solr create -c wormmine-autocomplete -p ${SOLR_PORT}
    fi

    echo "✅ Solr started with cores: wormmine-search, wormmine-autocomplete"
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
# Main Entrypoint Logic
# ============================================

# Always wait for PostgreSQL and configure
wait_for_postgres
sanitize_database_names
configure_intermine
setup_databases

# Handle different commands
case "$1" in
    run)
        echo "📋 Mode: RUN (Manual operation - shell access only)"
        echo "ℹ️  Container started. Use 'docker exec -it wormmine bash' to access shell."
        echo "ℹ️  Solr and Tomcat NOT auto-started - start manually as needed."
        echo "ℹ️  Database builds from /opt/intermine/wormmine"

        # Keep container alive
        tail -f /dev/null
        ;;

    tomcat)
        echo "📋 Mode: TOMCAT"
        start_solr
        start_tomcat
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
