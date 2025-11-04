#!/bin/bash
# Auto-push to ECR when repositories change
# This script can be used as a Git hook or run manually after changes

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$PROJECT_ROOT/logs/ecr-push-$(date +%Y%m%d_%H%M%S).log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "$1" | tee -a "$LOG_FILE"
}

log_info() {
    log "${BLUE}[INFO]${NC} $1"
}

log_success() {
    log "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    log "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    log "${RED}[ERROR]${NC} $1"
}

# Function to check if repository has changes
has_dockerfile_changes() {
    # Check if Dockerfile or related files have changed in last commit
    if git diff --name-only HEAD~1 HEAD | grep -E "(Dockerfile|docker/|src/lib/)" > /dev/null 2>&1; then
        return 0  # Has changes
    else
        return 1  # No changes
    fi
}

# Function to get current git branch and commit
get_git_info() {
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
    CURRENT_COMMIT=$(git rev-parse --short HEAD)
    COMMIT_MESSAGE=$(git log -1 --pretty=format:"%s")
}

# Main function
main() {
    log_info "Starting ECR auto-push process..."
    log_info "Timestamp: $(date)"
    
    cd "$PROJECT_ROOT"
    
    # Ensure logs directory exists
    mkdir -p logs
    
    # Get git information
    get_git_info
    log_info "Branch: $CURRENT_BRANCH"
    log_info "Commit: $CURRENT_COMMIT"
    log_info "Message: $COMMIT_MESSAGE"
    
    # Check if we should push based on branch
    if [[ "$CURRENT_BRANCH" != "main" && "$CURRENT_BRANCH" != "stage" && "$CURRENT_BRANCH" != "master" ]]; then
        log_warn "Not on main/stage/master branch. Skipping ECR push."
        exit 0
    fi
    
    # Check for relevant changes
    if ! has_dockerfile_changes; then
        log_info "No Dockerfile or relevant changes detected. Skipping ECR push."
        exit 0
    fi
    
    log_info "Relevant changes detected. Proceeding with ECR push..."
    
    # Determine version bump type based on commit message
    VERSION_TYPE="patch"  # default
    
    if echo "$COMMIT_MESSAGE" | grep -iE "(major|breaking)" > /dev/null; then
        VERSION_TYPE="major"
    elif echo "$COMMIT_MESSAGE" | grep -iE "(minor|feature|feat)" > /dev/null; then
        VERSION_TYPE="minor"
    fi
    
    log_info "Using version bump: $VERSION_TYPE"
    
    # Check ECR authentication
    log_info "Testing ECR authentication..."
    if ! uv run python src/main.py ecr auth > /dev/null 2>&1; then
        log_error "ECR authentication failed. Make sure AWS credentials are configured."
        exit 1
    fi
    
    # Build and push to ECR
    log_info "Building and pushing to ECR..."
    if uv run python src/main.py ecr push -t "$VERSION_TYPE" 2>&1 | tee -a "$LOG_FILE"; then
        log_success "ECR push completed successfully!"
        
        # Get the pushed version info
        NEW_VERSION=$(uv run python src/main.py ecr info 2>/dev/null | grep "Next patch version:" | awk '{print $4}')
        if [[ -n "$NEW_VERSION" ]]; then
            # Subtract 1 from patch version to get the version that was just pushed
            MAJOR=$(echo "$NEW_VERSION" | cut -d. -f1)
            MINOR=$(echo "$NEW_VERSION" | cut -d. -f2)
            PATCH=$(echo "$NEW_VERSION" | cut -d. -f3)
            PUSHED_PATCH=$((PATCH - 1))
            PUSHED_VERSION="$MAJOR.$MINOR.$PUSHED_PATCH"
            
            log_success "Pushed version: $PUSHED_VERSION"
            log_info "Pull command: docker pull 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_builder_v2:$PUSHED_VERSION"
        fi
    else
        log_error "ECR push failed!"
        exit 1
    fi
    
    log_info "Auto-push process completed."
}

# Help function
show_help() {
    cat << EOF
Auto-push ECR Script

Usage: $0 [OPTIONS]

OPTIONS:
    -h, --help      Show this help message
    -f, --force     Force push even if no changes detected
    -t, --type      Version bump type (major|minor|patch)
    -v, --verbose   Enable verbose output

EXAMPLES:
    $0                      # Auto-detect changes and push
    $0 --force              # Force push regardless of changes
    $0 --type minor         # Force minor version bump
    
GIT HOOK USAGE:
    # To set up as post-commit hook:
    ln -s ../../scripts/auto-push-ecr.sh .git/hooks/post-commit
    chmod +x .git/hooks/post-commit

ENVIRONMENT VARIABLES:
    ECR_AUTO_PUSH          Set to 'false' to disable auto-push
    ECR_VERSION_TYPE       Override version bump type
EOF
}

# Parse command line arguments
FORCE_PUSH=false
CUSTOM_VERSION_TYPE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -f|--force)
            FORCE_PUSH=true
            shift
            ;;
        -t|--type)
            CUSTOM_VERSION_TYPE="$2"
            shift 2
            ;;
        -v|--verbose)
            set -x
            shift
            ;;
        *)
            log_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Check for environment variable to disable
if [[ "${ECR_AUTO_PUSH:-true}" == "false" ]]; then
    log_info "ECR auto-push disabled via ECR_AUTO_PUSH environment variable."
    exit 0
fi

# Override version type if specified
if [[ -n "$CUSTOM_VERSION_TYPE" ]]; then
    VERSION_TYPE="$CUSTOM_VERSION_TYPE"
fi

# Override change detection if forced
if [[ "$FORCE_PUSH" == "true" ]]; then
    has_dockerfile_changes() { return 0; }  # Always return true
fi

# Run main function
main "$@"