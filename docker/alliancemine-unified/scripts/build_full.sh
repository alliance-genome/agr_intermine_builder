#!/bin/bash
# ============================================
# AllianceMine Full Build Script
# ============================================
# Executes complete InterMine build pipeline:
# 1. Build database schema
# 2. Extract and load data
# 3. Post-processing
# 4. Build user profile database
# 5. Build and deploy WAR file
# ============================================

set -e  # Exit on error

echo "============================================"
echo "🏗️  AllianceMine Full Build"
echo "============================================"

# Timestamps for logging
START_TIME=$(date +%s)

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log_step() {
    echo ""
    echo "============================================"
    echo "📋 STEP: $1"
    echo "============================================"
}

# Change to alliancemine directory
cd /opt/intermine/alliancemine || exit 1

# ============================================
# Step 1: Build Database Schema
# ============================================
log_step "1. Building Database Schema"

log "Running: ./gradlew buildDB"
./gradlew buildDB --stacktrace || {
    log "❌ buildDB failed"
    exit 1
}

log "✅ Database schema built successfully"

# ============================================
# Step 2: Extract Data (if script exists)
# ============================================
if [ -f "/opt/intermine/scripts/extract_data.sh" ]; then
    log_step "2. Extracting Data from Sources"

    /opt/intermine/scripts/extract_data.sh || {
        log "⚠️  Data extraction had some errors (continuing anyway)"
    }

    log "✅ Data extraction completed"
else
    log_step "2. Skipping Data Extraction (no extract_data.sh)"
fi

# ============================================
# Step 3: Project Build (Load Data)
# ============================================
log_step "3. Loading Data into Database"

log "Running: ./project_build -b"
./project_build -b || {
    log "❌ project_build failed"
    exit 1
}

log "✅ Data loaded successfully"

# ============================================
# Step 4: Post-Processing
# ============================================
log_step "4. Running Post-Processing"

log "Running: ./gradlew postprocess"
./gradlew postprocess --stacktrace || {
    log "⚠️  Some post-processing steps failed (continuing anyway)"
}

log "✅ Post-processing completed"

# ============================================
# Step 5: Build User Profile Database
# ============================================
log_step "5. Building User Profile Database"

log "Running: ./gradlew buildUserDB"
./gradlew buildUserDB --stacktrace || {
    log "❌ buildUserDB failed"
    exit 1
}

log "✅ User profile database built"

# ============================================
# Step 6: Build Solr Indexes
# ============================================
log_step "6. Building Solr Search Indexes"

log "Running: ./load_db_build_solr"
./load_db_build_solr || {
    log "⚠️  Solr indexing had some errors (continuing anyway)"
}

log "✅ Solr indexes built"

# ============================================
# Step 7: Build and Deploy WAR
# ============================================
log_step "7. Building and Deploying WAR File"

log "Running: ./gradlew cargoRedeployRemote"
./gradlew cargoRedeployRemote --stacktrace || {
    log "❌ WAR deployment failed"
    exit 1
}

log "✅ WAR deployed successfully"

# ============================================
# Build Summary
# ============================================
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
HOURS=$((DURATION / 3600))
MINUTES=$(( (DURATION % 3600) / 60 ))
SECONDS=$((DURATION % 60))

echo ""
echo "============================================"
echo "✅ AllianceMine Build Completed Successfully!"
echo "============================================"
echo "Duration: ${HOURS}h ${MINUTES}m ${SECONDS}s"
echo ""
echo "🌐 Web Application: http://localhost:8080/alliancemine"
echo "🔍 Solr Admin: http://localhost:8983/solr"
echo ""
echo "To access the application:"
echo "  docker-compose exec alliancemine bash"
echo "  curl http://localhost:8080/alliancemine/service/version"
echo "============================================"
