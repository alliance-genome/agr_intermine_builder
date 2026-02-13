#!/bin/bash
# Extract Alliance data from FMS (File Management System)
set -e

ALLIANCE_RELEASE="${ALLIANCE_RELEASE:-8.2.0}"
DATA_DIR="/root/data"
FMS_BASE_URL="https://fms.alliancegenome.org/api/datafile"

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1"
}

# Create data directories
mkdir -p "${DATA_DIR}"/{genes,alleles,disease,phenotype,orthology,expression,variants,go}

log "Extracting Alliance data release ${ALLIANCE_RELEASE}..."

# Download data files
download_file() {
    local FILE_TYPE=$1
    local OUTPUT_DIR=$2
    local FILENAME=$3

    log "Downloading ${FILE_TYPE}..."

    curl -L -o "${OUTPUT_DIR}/${FILENAME}" \
        "${FMS_BASE_URL}/${FILE_TYPE}/${ALLIANCE_RELEASE}/${FILENAME}" \
        --connect-timeout 30 \
        --max-time 3600

    if [ -f "${OUTPUT_DIR}/${FILENAME}" ]; then
        log "✅ Downloaded ${FILENAME} ($(du -h ${OUTPUT_DIR}/${FILENAME} | cut -f1))"
    else
        log "❌ Failed to download ${FILENAME}"
        return 1
    fi
}

# Gene data
download_file "gene-basic" "${DATA_DIR}/genes" "GENE-BASIC_AGR.json" || true

# Allele data
download_file "allele" "${DATA_DIR}/alleles" "ALLELE_AGR.json" || true

# Disease annotations
download_file "disease" "${DATA_DIR}/disease" "DISEASE-ANNOTATION_AGR.json" || true

# Phenotype data
download_file "phenotype" "${DATA_DIR}/phenotype" "PHENOTYPE-ANNOTATION_AGR.json" || true

# Orthology
download_file "orthology" "${DATA_DIR}/orthology" "ORTHOLOGY-ALLIANCE_COMBINED.json" || true

# GO annotations
download_file "go-annotation" "${DATA_DIR}/go" "GO-ANNOTATION_AGR.gaf" || true

log "✅ Data extraction complete!"
log "Data location: ${DATA_DIR}"
