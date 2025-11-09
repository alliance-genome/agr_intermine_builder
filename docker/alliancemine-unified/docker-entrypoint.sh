#!/bin/bash
set -e

# ============================================
# AllianceMine Docker Entrypoint
# ============================================
# Handles initialization, configuration, and startup
# of Tomcat, Solr, and InterMine build processes.
# ============================================

echo "============================================"
echo "🚀 AllianceMine Unified Container"
echo "============================================"
echo "Version: ${ALLIANCE_RELEASE}"
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
    envsubst < /opt/intermine/.intermine/alliancemine.properties.template \
             > /opt/intermine/.intermine/alliancemine.properties

    # Set up .pgpass for passwordless psql access
    echo "${RDS_HOST}:${RDS_PORT}:*:${RDS_USER}:${RDS_PASSWORD}" > ~/.pgpass
    chmod 600 ~/.pgpass

    echo "✅ InterMine configured"
}

# ============================================
# Check and Create Databases
# ============================================
setup_databases() {
    echo "📦 Checking databases..."

    # Export password for psql
    export PGPASSWORD="${RDS_PASSWORD}"

    # Check main database
    if ! psql -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -d postgres \
         -lqt | cut -d \| -f 1 | grep -qw "${RDS_DB_NAME}"; then
        echo "   Creating main database: ${RDS_DB_NAME}"
        psql -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -d postgres \
             -c "CREATE DATABASE ${RDS_DB_NAME};"
        echo "   ✅ Main database created"
    else
        echo "   ✅ Main database exists: ${RDS_DB_NAME}"
    fi

    # Check profile database
    if ! psql -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -d postgres \
         -lqt | cut -d \| -f 1 | grep -qw "${RDS_PROFILE_DB_NAME}"; then
        echo "   Creating profile database: ${RDS_PROFILE_DB_NAME}"
        psql -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -d postgres \
             -c "CREATE DATABASE ${RDS_PROFILE_DB_NAME};"
        echo "   ✅ Profile database created"
    else
        echo "   ✅ Profile database exists: ${RDS_PROFILE_DB_NAME}"
    fi
}

# ============================================
# Start Solr
# ============================================
start_solr() {
    echo "🔍 Starting Solr on port ${SOLR_PORT}..."

    # Start Solr in background
    /opt/solr/bin/solr start -p ${SOLR_PORT} -m ${SOLR_JAVA_MEM} -noprompt

    # Wait for Solr to be ready
    MAX_ATTEMPTS=30
    ATTEMPT=0
    until curl -s "http://localhost:${SOLR_PORT}/solr/admin/info/system" > /dev/null; do
        ATTEMPT=$((ATTEMPT+1))
        if [ $ATTEMPT -ge $MAX_ATTEMPTS ]; then
            echo "❌ Solr failed to start"
            exit 1
        fi
        echo "   Waiting for Solr... (attempt $ATTEMPT/$MAX_ATTEMPTS)"
        sleep 2
    done

    echo "✅ Solr is running"

    # Create InterMine Solr cores if they don't exist
    echo "📝 Checking Solr cores..."

    # Check if alliancemine-search core exists
    if ! curl -s "http://localhost:${SOLR_PORT}/solr/admin/cores?action=STATUS&core=alliancemine-search" | grep -q '"name":"alliancemine-search"'; then
        echo "   Creating alliancemine-search core..."
        /opt/solr/bin/solr create -c alliancemine-search -p ${SOLR_PORT}
        echo "   ✅ alliancemine-search core created"
    else
        echo "   ✅ alliancemine-search core already exists"
    fi

    # Check if alliancemine-autocomplete core exists
    if ! curl -s "http://localhost:${SOLR_PORT}/solr/admin/cores?action=STATUS&core=alliancemine-autocomplete" | grep -q '"name":"alliancemine-autocomplete"'; then
        echo "   Creating alliancemine-autocomplete core..."
        /opt/solr/bin/solr create -c alliancemine-autocomplete -p ${SOLR_PORT}
        echo "   ✅ alliancemine-autocomplete core created"
    else
        echo "   ✅ alliancemine-autocomplete core already exists"
    fi

    echo "✅ Solr cores initialized"
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
    if [ -f "/opt/intermine/scripts/build_full.sh" ]; then
        /opt/intermine/scripts/build_full.sh
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
configure_intermine
setup_databases

# Handle different commands
case "$1" in
    build)
        echo "📋 Mode: BUILD"
        start_solr
        build_intermine
        ;;

    run)
        echo "📋 Mode: RUN (Tomcat + Solr)"
        start_solr

        # Check if auto-build is enabled and build hasn't been done
        if [ "${AUTO_BUILD}" = "true" ]; then
            # Check if build marker file exists
            if [ ! -f "/opt/intermine/.build_complete" ]; then
                echo "🔄 AUTO_BUILD enabled - running initial build..."
                build_intermine
                # Create marker file to prevent rebuilding on restart
                touch /opt/intermine/.build_complete
                echo "✅ Initial build complete"
            else
                echo "ℹ️  AUTO_BUILD enabled but build already complete (marker exists)"
            fi
        fi

        start_tomcat
        ;;

    solr)
        echo "📋 Mode: SOLR ONLY"
        start_solr
        # Keep container alive
        tail -f /var/solr/logs/solr.log
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
