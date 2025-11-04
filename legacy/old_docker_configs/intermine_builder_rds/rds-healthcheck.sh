#!/bin/bash
# Health check script for RDS InterMine Builder
# This script verifies that the container is healthy and ready

set -euo pipefail

# Exit codes
EXIT_SUCCESS=0
EXIT_FAILURE=1

# Configuration
TIMEOUT=10
QUIET=${QUIET:-false}

# Colors (only if not quiet)
if [[ "$QUIET" != "true" ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    BLUE='\033[0;34m'
    YELLOW='\033[1;33m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    BLUE=''
    YELLOW=''
    NC=''
fi

log() {
    if [[ "$QUIET" != "true" ]]; then
        echo -e "${BLUE}[HEALTH] $1${NC}"
    fi
}

warn() {
    if [[ "$QUIET" != "true" ]]; then
        echo -e "${YELLOW}[HEALTH] WARNING: $1${NC}"
    fi
}

error() {
    echo -e "${RED}[HEALTH] ERROR: $1${NC}" >&2
}

success() {
    if [[ "$QUIET" != "true" ]]; then
        echo -e "${GREEN}[HEALTH] $1${NC}"
    fi
}

# Function to check Java installation
check_java() {
    if command -v java &> /dev/null; then
        local java_version=$(java -version 2>&1 | head -n1)
        log "Java check: ✅ $java_version"
        return 0
    else
        error "Java check: ❌ Java not found"
        return 1
    fi
}

# Function to check essential tools
check_tools() {
    local tools=("psql" "git" "maven")
    local failed=0
    
    for tool in "${tools[@]}"; do
        if command -v "$tool" &> /dev/null; then
            log "Tool check ($tool): ✅"
        else
            error "Tool check ($tool): ❌ Not found"
            failed=1
        fi
    done
    
    return $failed
}

# Function to check RDS connectivity
check_rds_connectivity() {
    # Only check if DB_HOST is set (container might not be configured yet)
    if [[ -z "${DB_HOST:-}" ]]; then
        warn "RDS check: ⚠️  DB_HOST not configured"
        return 0
    fi
    
    local db_port=${DB_PORT:-5432}
    local db_user=${DB_USER:-postgres}
    
    # Test TCP connection
    if timeout "$TIMEOUT" nc -z "$DB_HOST" "$db_port" 2>/dev/null; then
        log "RDS TCP check: ✅ $DB_HOST:$db_port"
    else
        error "RDS TCP check: ❌ Cannot reach $DB_HOST:$db_port"
        return 1
    fi
    
    # Test PostgreSQL connection (if credentials are available)
    if [[ -n "${DB_PASSWORD:-}" ]]; then
        if timeout "$TIMEOUT" psql -h "$DB_HOST" -p "$db_port" -U "$db_user" -d "postgres" -c "SELECT 1;" &>/dev/null; then
            log "RDS PostgreSQL check: ✅"
        else
            error "RDS PostgreSQL check: ❌ Cannot connect to PostgreSQL"
            return 1
        fi
    else
        warn "RDS PostgreSQL check: ⚠️  DB_PASSWORD not configured"
    fi
    
    return 0
}

# Function to check InterMine setup
check_intermine_setup() {
    local alliancemine_dir="$HOME/alliancemine"
    local biosources_dir="$HOME/alliancemine-bio-sources"
    
    # Check if directories exist
    if [[ -d "$alliancemine_dir" ]]; then
        log "InterMine directory check: ✅ $alliancemine_dir"
        
        # Check for essential files
        if [[ -f "$alliancemine_dir/build.gradle" ]]; then
            log "InterMine build file check: ✅"
        else
            error "InterMine build file check: ❌ build.gradle not found"
            return 1
        fi
        
        if [[ -f "$alliancemine_dir/project_build" ]]; then
            log "InterMine project_build check: ✅"
        else
            error "InterMine project_build check: ❌ project_build script not found"
            return 1
        fi
    else
        error "InterMine directory check: ❌ $alliancemine_dir not found"
        return 1
    fi
    
    if [[ -d "$biosources_dir" ]]; then
        log "Bio-sources directory check: ✅ $biosources_dir"
    else
        error "Bio-sources directory check: ❌ $biosources_dir not found"
        return 1
    fi
    
    return 0
}

# Function to check properties configuration
check_properties() {
    local properties_file="$HOME/.intermine/alliancemine.properties"
    
    if [[ -f "$properties_file" ]]; then
        log "Properties file check: ✅ $properties_file"
        
        # Check for RDS-specific configuration
        if grep -q "datasource.dataSourceProperties.serverName" "$properties_file"; then
            log "RDS properties check: ✅"
        else
            warn "RDS properties check: ⚠️  RDS configuration not found"
        fi
    else
        warn "Properties file check: ⚠️  $properties_file not found (normal for unconfigured container)"
    fi
    
    return 0
}

# Function to check disk space
check_disk_space() {
    local min_free_gb=5
    local available_gb=$(df / | awk 'NR==2 {print int($4/1024/1024)}')
    
    if [[ $available_gb -gt $min_free_gb ]]; then
        log "Disk space check: ✅ ${available_gb}GB available"
    else
        error "Disk space check: ❌ Only ${available_gb}GB available (need at least ${min_free_gb}GB)"
        return 1
    fi
    
    return 0
}

# Function to check memory
check_memory() {
    if [[ -f "/proc/meminfo" ]]; then
        local total_mem_gb=$(awk '/MemTotal/ {print int($2/1024/1024)}' /proc/meminfo)
        local available_mem_gb=$(awk '/MemAvailable/ {print int($2/1024/1024)}' /proc/meminfo)
        
        log "Memory check: ✅ ${available_mem_gb}GB available / ${total_mem_gb}GB total"
        
        if [[ $available_mem_gb -lt 2 ]]; then
            warn "Memory check: ⚠️  Low memory (${available_mem_gb}GB available)"
        fi
    else
        warn "Memory check: ⚠️  Cannot read memory info"
    fi
    
    return 0
}

# Function to check container age (for ephemeral builds)
check_container_age() {
    if [[ -f "/proc/1/stat" ]]; then
        local uptime_seconds=$(awk '{print int($22/100)}' /proc/1/stat)
        local uptime_hours=$((uptime_seconds / 3600))
        
        log "Container age: ${uptime_hours}h"
        
        # Warn if container is running for more than 24 hours (ephemeral builds)
        if [[ $uptime_hours -gt 24 ]]; then
            warn "Container age: ⚠️  Running for ${uptime_hours}h (consider cleanup for ephemeral builds)"
        fi
    fi
    
    return 0
}

# Function to perform comprehensive health check
comprehensive_health_check() {
    local failed=0
    
    log "🏥 Starting comprehensive health check..."
    
    # Essential system checks
    check_java || failed=1
    check_tools || failed=1
    check_disk_space || failed=1
    check_memory || failed=1
    
    # InterMine-specific checks
    check_intermine_setup || failed=1
    check_properties || failed=1
    
    # RDS connectivity (if configured)
    check_rds_connectivity || failed=1
    
    # Operational checks
    check_container_age || failed=1
    
    return $failed
}

# Function to perform quick health check (for Docker health check)
quick_health_check() {
    local failed=0
    
    # Essential checks only
    check_java || failed=1
    
    # RDS connectivity (if configured)
    if [[ -n "${DB_HOST:-}" ]] && [[ -n "${DB_PASSWORD:-}" ]]; then
        check_rds_connectivity || failed=1
    fi
    
    return $failed
}

# Main execution
main() {
    local check_type="quick"
    local exit_code=0
    
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --comprehensive|-c)
                check_type="comprehensive"
                shift
                ;;
            --quick|-q)
                check_type="quick"
                shift
                ;;
            --quiet)
                QUIET=true
                shift
                ;;
            --help|-h)
                echo "Usage: $0 [--comprehensive|--quick] [--quiet]"
                echo "  --comprehensive: Run all health checks"
                echo "  --quick: Run essential checks only (default)"
                echo "  --quiet: Suppress informational output"
                exit 0
                ;;
            *)
                error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    # Run health check based on type
    case $check_type in
        comprehensive)
            comprehensive_health_check || exit_code=1
            ;;
        quick)
            quick_health_check || exit_code=1
            ;;
    esac
    
    # Report results
    if [[ $exit_code -eq 0 ]]; then
        success "🎉 Health check passed!"
    else
        error "❌ Health check failed!"
    fi
    
    exit $exit_code
}

# Handle script interruption
trap 'error "Health check interrupted"; exit 1' INT TERM

# Run main function
main "$@"