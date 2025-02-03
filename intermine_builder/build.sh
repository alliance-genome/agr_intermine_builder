#!/bin/bash

set -euo pipefail

# Constants
LOG_FILE="/root/build.progress"
DEFAULT_MINE_NAME="biotestmine"
INTERMINE_SCRIPTS_REPO="https://github.com/intermine/intermine-scripts"

# Initialize logging
init_logging() {
    : > "$LOG_FILE"
    exec 1> >(tee -a "$LOG_FILE")
    exec 2> >(tee -a "$LOG_FILE" >&2)
}

log_message() {
    echo "$(date +%Y/%m/%d-%H:%M) $1"
}

# Setup initial environment
setup_environment() {
    mkdir -p /root/.intermine
    cd /root/
}

# Build InterMine if specified
build_intermine() {
    if [[ -z "${IM_REPO_URL-}" && -z "${IM_REPO_BRANCH-}" ]]; then
        return
    }

    log_message "Start InterMine build"
    log_message "Cloning ${IM_REPO_URL:-https://github.com/intermine/intermine} branch ${IM_REPO_BRANCH:-master}"
    
    git clone "${IM_REPO_URL:-https://github.com/intermine/intermine}" intermine \
        --single-branch --branch "${IM_REPO_BRANCH:-master}" --depth=1

    cd intermine

    local build_commands=(
        "cd plugin && ./gradlew clean && ./gradlew install"
        "cd intermine && ./gradlew clean && ./gradlew install"
        "cd bio && ./gradlew clean && ./gradlew install"
        "cd bio/sources && ./gradlew clean && ./gradlew install"
        "cd bio/postprocess/ && ./gradlew clean && ./gradlew install"
    )

    for cmd in "${build_commands[@]}"; do
        eval "($cmd)" || return 1
    done

    # Extract version numbers
    IM_VERSION=$(sed -n "s/^\s*version.*\+'\(.*\)'\s*$/\1/p" intermine/build.gradle)
    BIO_VERSION=$(sed -n "s/^\s*version.*\+'\(.*\)'\s*$/\1/p" bio/build.gradle)
    export IM_VERSION BIO_VERSION

    cd /root/
}

# Setup mine repository
setup_mine() {
    local mine_name="${MINE_NAME:-$DEFAULT_MINE_NAME}"
    log_message "Starting mine build"

    if [[ -d "$mine_name" && -n "$(ls -A "$mine_name")" ]]; then
        log_message "Update $mine_name to newest version"
        cd "$mine_name"
        cd /root/
    else
        log_message "Clone $mine_name"
        git clone "${MINE_REPO_URL:-https://github.com/intermine/biotestmine}" "$mine_name"
        
        # Update properties files
        sed -i "s/localhost/${SOLR_HOST:-solr}/g" "./$mine_name/dbmodel/resources/keyword_search.properties"
        sed -i "s/localhost/${SOLR_HOST:-solr}/g" "./$mine_name/dbmodel/resources/objectstoresummary.config.properties"
    fi

    # Update versions if custom InterMine build was done
    if [[ -n "${IM_VERSION-}" ]]; then
        sed -i "s/\(systemProp\.imVersion=\).*\$/\1${IM_VERSION}/" "/root/$mine_name/gradle.properties"
    fi
    if [[ -n "${BIO_VERSION-}" ]]; then
        sed -i "s/\(systemProp\.bioVersion=\).*\$/\1${BIO_VERSION}/" "/root/$mine_name/gradle.properties"
    fi
}

# Setup bio sources if specified
setup_bio_sources() {
    if [[ -z "${BIOSOURCES_REPO_URL-}" ]]; then
        return
    }

    log_message "Clone ${BIOSOURCES_REPO_URL}"
    git clone "$BIOSOURCES_REPO_URL" "$MINE_NAME-bio-sources"
    
    cd "/root/$MINE_NAME-bio-sources"
    log_message "Building and Installing bio sources"
    ./gradlew clean --stacktrace
    ./gradlew install --stacktrace
    cd /root
}

# Setup project build
setup_project_build() {
    local mine_name="${MINE_NAME:-$DEFAULT_MINE_NAME}"
    
    if [[ ! -f "/root/$mine_name/project_build" ]]; then
        log_message "Setting up project build"
        git clone "$INTERMINE_SCRIPTS_REPO"
        cp "/root/intermine-scripts/project_build" "/root/$mine_name/project_build"
        chmod +x "/root/$mine_name/project_build"
    }
}

# Configure mine properties
configure_mine_properties() {
    local mine_name="${MINE_NAME:-$DEFAULT_MINE_NAME}"
    local props_file="/root/.intermine/$mine_name.properties"

    if [[ ! -f "$props_file" ]]; then
        log_message "Configuring mine properties"
        cp "/root/$mine_name/$mine_name.properties" "/root/.intermine/"
        
        # ... existing property configurations ...
        # (keeping the existing sed commands as they are quite specific to your needs)
    fi
}

# Main execution
main() {
    init_logging
    setup_environment
    build_intermine
    setup_mine
    setup_bio_sources
    setup_project_build
    configure_mine_properties

    # Final build steps
    cd "${MINE_NAME:-$DEFAULT_MINE_NAME}"
    log_message "Running project_build script"
    ./project_build -b -T localhost /root/dump/dump

    log_message "Gradle: build webapp"
    ./gradlew cargoRedeployRemote --stacktrace
    sleep 60
    ./gradlew cargoRedeployRemote --stacktrace
}

main "$@"
