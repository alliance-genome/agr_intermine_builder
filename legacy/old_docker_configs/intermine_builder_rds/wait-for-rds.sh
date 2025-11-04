#!/bin/bash
# Wait for RDS instance to be available
# This script will retry connection attempts with exponential backoff

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() {
    echo -e "${BLUE}[WAIT-RDS] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[WAIT-RDS] WARNING: $1${NC}"
}

error() {
    echo -e "${RED}[WAIT-RDS] ERROR: $1${NC}"
}

success() {
    echo -e "${GREEN}[WAIT-RDS] $1${NC}"
}

# Configuration
MAX_ATTEMPTS=${MAX_ATTEMPTS:-30}
INITIAL_WAIT=${INITIAL_WAIT:-2}
MAX_WAIT=${MAX_WAIT:-30}
TIMEOUT=${TIMEOUT:-10}

# Get environment variables
DB_HOST=${DB_HOST:-""}
DB_PORT=${DB_PORT:-5432}
DB_USER=${DB_USER:-"postgres"}
DB_PASSWORD=${DB_PASSWORD:-""}

# Function to test TCP connection
test_tcp_connection() {
    log "Testing TCP connection to ${DB_HOST}:${DB_PORT}..."
    
    if timeout "$TIMEOUT" nc -z "$DB_HOST" "$DB_PORT" 2>/dev/null; then
        success "TCP connection successful"
        return 0
    else
        warn "TCP connection failed"
        return 1
    fi
}

# Function to test PostgreSQL connection
test_postgresql_connection() {
    log "Testing PostgreSQL connection..."
    
    # Create temporary .pgpass if it doesn't exist
    local temp_pgpass=false
    if [[ ! -f "$HOME/.pgpass" ]]; then
        echo "${DB_HOST}:${DB_PORT}:*:${DB_USER}:${DB_PASSWORD}" > "$HOME/.pgpass"
        chmod 400 "$HOME/.pgpass"
        temp_pgpass=true
    fi
    
    # Test connection
    if timeout "$TIMEOUT" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "postgres" -c "SELECT 1;" &>/dev/null; then
        success "PostgreSQL connection successful"
        
        # Clean up temporary .pgpass
        if [[ "$temp_pgpass" == "true" ]]; then
            rm -f "$HOME/.pgpass"
        fi
        
        return 0
    else
        warn "PostgreSQL connection failed"
        
        # Clean up temporary .pgpass
        if [[ "$temp_pgpass" == "true" ]]; then
            rm -f "$HOME/.pgpass"
        fi
        
        return 1
    fi
}

# Function to get RDS instance status (if AWS CLI is available)
get_rds_status() {
    if command -v aws &> /dev/null; then
        log "Checking RDS instance status via AWS CLI..."
        
        # Try to get RDS instance status
        local instance_id=$(echo "$DB_HOST" | cut -d'.' -f1)
        local status=$(aws rds describe-db-instances --db-instance-identifier "$instance_id" --query 'DBInstances[0].DBInstanceStatus' --output text 2>/dev/null || echo "unknown")
        
        if [[ "$status" != "unknown" ]]; then
            log "RDS instance status: $status"
            
            if [[ "$status" == "available" ]]; then
                return 0
            elif [[ "$status" == "creating" ]] || [[ "$status" == "backing-up" ]] || [[ "$status" == "modifying" ]]; then
                warn "RDS instance is $status, waiting..."
                return 1
            else
                error "RDS instance is in unexpected state: $status"
                return 1
            fi
        fi
    fi
    
    return 1
}

# Function to wait with exponential backoff
wait_for_rds() {
    local attempt=1
    local wait_time=$INITIAL_WAIT
    
    log "Waiting for RDS instance to be available..."
    log "Target: ${DB_HOST}:${DB_PORT}"
    log "Max attempts: $MAX_ATTEMPTS"
    
    while [[ $attempt -le $MAX_ATTEMPTS ]]; do
        log "Attempt $attempt/$MAX_ATTEMPTS"
        
        # Try to get RDS status first
        if get_rds_status; then
            log "RDS instance reports as available, testing connections..."
        fi
        
        # Test TCP connection
        if test_tcp_connection; then
            # Test PostgreSQL connection
            if test_postgresql_connection; then
                success "🎉 RDS instance is ready!"
                
                # Get and display PostgreSQL version
                local pg_version=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "postgres" -t -c "SELECT version();" 2>/dev/null | head -n1 | xargs || echo "unknown")
                log "PostgreSQL version: $pg_version"
                
                # Show connection statistics
                local connections=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "postgres" -t -c "SELECT count(*) FROM pg_stat_activity;" 2>/dev/null || echo "0")
                log "Active connections: $connections"
                
                return 0
            fi
        fi
        
        # Connection failed, wait before retry
        if [[ $attempt -lt $MAX_ATTEMPTS ]]; then
            warn "Connection attempt $attempt failed, waiting ${wait_time}s before retry..."
            sleep "$wait_time"
            
            # Exponential backoff with jitter
            wait_time=$(( wait_time * 2 ))
            if [[ $wait_time -gt $MAX_WAIT ]]; then
                wait_time=$MAX_WAIT
            fi
            
            # Add some jitter (±25%)
            local jitter=$(( RANDOM % (wait_time / 2) ))
            wait_time=$(( wait_time + jitter - (wait_time / 4) ))
        fi
        
        attempt=$(( attempt + 1 ))
    done
    
    error "Failed to connect to RDS after $MAX_ATTEMPTS attempts"
    error "This could indicate:"
    error "  - RDS instance is not available"
    error "  - Security group restrictions"
    error "  - Network connectivity issues"
    error "  - Incorrect credentials"
    
    return 1
}

# Function to show diagnostic information
show_diagnostics() {
    log "=== RDS Connection Diagnostics ==="
    log "Host: ${DB_HOST}"
    log "Port: ${DB_PORT}"
    log "User: ${DB_USER}"
    log "Password: [${#DB_PASSWORD} chars]"
    
    # Test name resolution
    if command -v nslookup &> /dev/null; then
        log "DNS resolution:"
        nslookup "$DB_HOST" || warn "DNS resolution failed"
    fi
    
    # Test basic connectivity
    log "Network connectivity:"
    if command -v ping &> /dev/null; then
        ping -c 1 -W 5 "$DB_HOST" &>/dev/null && log "  Ping: ✅ Success" || warn "  Ping: ❌ Failed"
    fi
    
    if command -v telnet &> /dev/null; then
        timeout 5 telnet "$DB_HOST" "$DB_PORT" &>/dev/null && log "  Telnet: ✅ Success" || warn "  Telnet: ❌ Failed"
    fi
    
    log "================================"
}

# Main execution
main() {
    # Validate required environment variables
    if [[ -z "$DB_HOST" ]]; then
        error "DB_HOST environment variable is required"
        exit 1
    fi
    
    if [[ -z "$DB_PASSWORD" ]]; then
        error "DB_PASSWORD environment variable is required"
        exit 1
    fi
    
    # Show diagnostic information
    show_diagnostics
    
    # Wait for RDS to be available
    if wait_for_rds; then
        success "RDS instance is ready for InterMine build!"
        exit 0
    else
        error "RDS instance is not available"
        exit 1
    fi
}

# Handle script interruption
trap 'error "Script interrupted"; exit 1' INT TERM

# Run main function
main "$@"