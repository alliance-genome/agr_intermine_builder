#!/bin/bash
# RDS EntryPoint for InterMine Builder
# Configures InterMine to connect to AWS RDS PostgreSQL

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}"
}

success() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

# Function to validate required environment variables
validate_env() {
    local required_vars=("DB_HOST" "DB_USER" "DB_PASSWORD" "DB_NAME")
    local missing_vars=()
    
    for var in "${required_vars[@]}"; do
        if [[ -z "${!var:-}" ]]; then
            missing_vars+=("$var")
        fi
    done
    
    if [[ ${#missing_vars[@]} -gt 0 ]]; then
        error "Missing required environment variables:"
        for var in "${missing_vars[@]}"; do
            error "  - $var"
        done
        error "Please set these variables when running the container"
        exit 1
    fi
}

# Function to wait for RDS to be available
wait_for_rds() {
    log "Waiting for RDS instance to be available..."
    log "Connecting to: ${DB_HOST}:${DB_PORT}"
    
    if ! /wait-for-rds.sh; then
        error "Failed to connect to RDS instance after multiple attempts"
        exit 1
    fi
    
    success "RDS instance is available"
}

# Function to configure InterMine properties for RDS
configure_intermine_properties() {
    log "Configuring InterMine properties for RDS..."
    
    # Run the configuration script
    if ! /configure-rds.sh; then
        error "Failed to configure InterMine properties"
        exit 1
    fi
    
    success "InterMine properties configured for RDS"
}

# Function to create .pgpass for automatic authentication
setup_postgresql_auth() {
    log "Setting up PostgreSQL authentication..."
    
    # Create .pgpass file for automatic authentication
    cat > "$HOME/.pgpass" <<EOF
${DB_HOST}:${DB_PORT}:*:${DB_USER}:${DB_PASSWORD}
EOF
    chmod 400 "$HOME/.pgpass"
    
    success "PostgreSQL authentication configured"
}

# Function to test database connectivity
test_database_connection() {
    log "Testing database connectivity..."
    
    # Test connection to main database
    if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "SELECT version();" &>/dev/null; then
        success "Successfully connected to main database: $DB_NAME"
    else
        warn "Could not connect to main database: $DB_NAME (this is normal if database doesn't exist yet)"
    fi
    
    # Test connection to profile database
    if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_PROFILE_NAME" -c "SELECT version();" &>/dev/null; then
        success "Successfully connected to profile database: $DB_PROFILE_NAME"
    else
        warn "Could not connect to profile database: $DB_PROFILE_NAME (this is normal if database doesn't exist yet)"
    fi
    
    # Test connection to postgres default database
    if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "postgres" -c "SELECT version();" &>/dev/null; then
        success "Successfully connected to PostgreSQL server"
        
        # Get PostgreSQL version
        local pg_version=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "postgres" -t -c "SELECT version();" | head -n1 | xargs)
        log "PostgreSQL version: $pg_version"
    else
        error "Could not connect to PostgreSQL server"
        exit 1
    fi
}

# Function to show connection information
show_connection_info() {
    log "=== RDS Connection Information ==="
    log "Host: $DB_HOST"
    log "Port: $DB_PORT"
    log "User: $DB_USER"
    log "Main Database: $DB_NAME"
    log "Profile Database: $DB_PROFILE_NAME"
    log "=================================="
}

# Function to create databases if they don't exist
create_databases_if_needed() {
    log "Checking if databases exist..."
    
    # Check and create main database
    if ! psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "postgres" -lqt | cut -d \| -f 1 | grep -qw "$DB_NAME"; then
        log "Creating main database: $DB_NAME"
        psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "postgres" -c "CREATE DATABASE $DB_NAME;"
        success "Created main database: $DB_NAME"
    else
        success "Main database already exists: $DB_NAME"
    fi
    
    # Check and create profile database
    if ! psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "postgres" -lqt | cut -d \| -f 1 | grep -qw "$DB_PROFILE_NAME"; then
        log "Creating profile database: $DB_PROFILE_NAME"
        psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "postgres" -c "CREATE DATABASE $DB_PROFILE_NAME;"
        success "Created profile database: $DB_PROFILE_NAME"
    else
        success "Profile database already exists: $DB_PROFILE_NAME"
    fi
}

# Function to set up monitoring
setup_monitoring() {
    log "Setting up build monitoring..."
    
    # Create logs directory
    mkdir -p "$HOME/logs"
    
    # Set up log rotation
    cat > "$HOME/.logrotate.conf" <<EOF
$HOME/logs/*.log {
    daily
    missingok
    rotate 7
    compress
    notifempty
    create 644 root root
}
EOF
    
    success "Monitoring setup complete"
}

# Main execution
main() {
    log "🚀 Starting InterMine Builder with RDS support"
    log "Container: $(hostname)"
    log "Build Type: Ephemeral RDS Build"
    
    # Validate environment
    validate_env
    
    # Show connection info
    show_connection_info
    
    # Wait for RDS to be available
    wait_for_rds
    
    # Setup PostgreSQL authentication
    setup_postgresql_auth
    
    # Test database connectivity
    test_database_connection
    
    # Create databases if needed
    create_databases_if_needed
    
    # Configure InterMine properties
    configure_intermine_properties
    
    # Setup monitoring
    setup_monitoring
    
    success "🎉 RDS configuration complete!"
    log "InterMine is ready to build against RDS instance"
    log "Available commands:"
    log "  - ./gradlew buildDB          # Create database schema"
    log "  - ./project_build           # Full InterMine build"
    log "  - ./load_db_build_solr      # Load data and build Solr"
    
    # Execute the command passed to the container
    exec "$@"
}

# Run main function
main "$@"