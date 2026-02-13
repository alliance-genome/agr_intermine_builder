#!/bin/bash
# Complete WormMine build process for RDS
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

success() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} ✅ $1"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} ❌ $1"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} ⚠️  $1"
}

# Change to wormmine directory
cd /root/wormmine

log "============================================"
log "WormMine Complete Build Process"
log "============================================"
log "RDS Host: ${RDS_HOST}:${RDS_PORT}"
log "Main DB: ${RDS_DB_NAME}"
log "Profile DB: ${RDS_PROFILE_DB_NAME}"
log "WormBase Release: ${WORMBASE_RELEASE}"
log "============================================"

# Stage 1: Gradle Build DB
log "📦 Stage 1: Creating database schema..."
./gradlew buildDB --stacktrace 2>&1 | tee /tmp/buildDB.log

if [ ${PIPESTATUS[0]} -eq 0 ]; then
    success "Database schema created"
else
    error "Failed to create database schema"
    exit 1
fi

# Stage 2: Extract WormBase Data
log "📥 Stage 2: Extracting WormBase data..."
if [ -f "/root/extract_data.sh" ]; then
    /root/extract_data.sh
    success "Data extraction complete"
else
    warn "No data extraction script found, skipping..."
fi

# Stage 3: Project Build (Data Integration)
log "🔨 Stage 3: Running project_build (data integration)..."
log "This will take 2-3 hours for WormMine..."

# Check if project_build script exists
if [ ! -f "./project_build" ]; then
    log "Cloning intermine-scripts for project_build..."
    cd /root
    git clone --depth 1 https://github.com/intermine/intermine-scripts.git
    cp intermine-scripts/project_build /root/wormmine/project_build
    chmod +x /root/wormmine/project_build
    cd /root/wormmine
fi

# Run project_build
./project_build -b -T localhost /root/data/dump 2>&1 | tee /tmp/project_build.log

if [ ${PIPESTATUS[0]} -eq 0 ]; then
    success "Project build complete"
else
    error "Failed to run project_build"
    exit 1
fi

# Stage 4: Post-processing
log "⚙️  Stage 4: Running post-processing..."
./gradlew postprocess --stacktrace 2>&1 | tee /tmp/postprocess.log

if [ ${PIPESTATUS[0]} -eq 0 ]; then
    success "Post-processing complete"
else
    error "Failed post-processing"
    exit 1
fi

# Stage 5: Build User DB
log "👤 Stage 5: Building user profile database..."
./gradlew buildUserDB --stacktrace 2>&1 | tee /tmp/buildUserDB.log

if [ ${PIPESTATUS[0]} -eq 0 ]; then
    success "User profile database created"
else
    error "Failed to create user profile database"
    exit 1
fi

# Stage 6: Build WAR file
log "📦 Stage 6: Building webapp WAR file..."
./gradlew war --stacktrace 2>&1 | tee /tmp/war.log

if [ ${PIPESTATUS[0]} -eq 0 ]; then
    success "WAR file built"
    WAR_FILE=$(find webapp/build/libs -name "*.war" | head -1)
    log "WAR file: ${WAR_FILE}"
else
    error "Failed to build WAR file"
    exit 1
fi

# Stage 7: Deploy to Tomcat (if Tomcat is running)
if command -v curl &> /dev/null && curl -s http://localhost:8081 > /dev/null; then
    log "🐱 Stage 7: Deploying to Tomcat..."
    ./gradlew cargoRedeployRemote --stacktrace 2>&1 | tee /tmp/deploy.log

    if [ ${PIPESTATUS[0]} -eq 0 ]; then
        success "Deployed to Tomcat"
    else
        error "Failed to deploy"
        exit 1
    fi
else
    warn "Tomcat not running, skipping deployment"
    log "To deploy later: ./gradlew cargoRedeployRemote"
fi

# Final Summary
log "============================================"
success "WormMine build completed successfully!"
log "============================================"
log "Summary:"
log "  - Database schema: ✅"
log "  - Data integration: ✅"
log "  - Post-processing: ✅"
log "  - User profiles: ✅"
log "  - WAR file: ✅"
log "  - Deployment: $([ -f /tmp/deploy.log ] && echo '✅' || echo '⏭️  skipped')"
log "============================================"
log ""
log "Next steps:"
log "  - Access mine at: http://localhost:8081/wormmine"
log "  - Check logs in: /tmp/*.log"
log "  - Database: ${RDS_HOST}:${RDS_PORT}/${RDS_DB_NAME}"
log ""
