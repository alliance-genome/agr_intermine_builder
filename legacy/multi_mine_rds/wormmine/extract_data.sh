#!/bin/bash
# Prepare WormBase data for WormMine from pre-provided files
set -e

WORMBASE_RELEASE="${WORMBASE_RELEASE:-WS290}"
DATA_DIR="/root/data"
CUSTOM_DATA_DIR="/root/custom_data"

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1"
}

# Create data directories
mkdir -p "${DATA_DIR}"/{wormbase,annotations,variations,interactions,go,orthologs}

log "Preparing WormBase data release ${WORMBASE_RELEASE}..."
log "Note: Data files should be pre-loaded in ${CUSTOM_DATA_DIR}"

# Check if custom data directory exists and has files
if [ ! -d "${CUSTOM_DATA_DIR}" ] || [ -z "$(ls -A ${CUSTOM_DATA_DIR})" ]; then
    log "⚠️  No custom data found in ${CUSTOM_DATA_DIR}"
    log "⚠️  Please mount WormBase data files to this location"
    log "⚠️  Expected files:"
    log "     - annotations.gff3.gz (genome annotations)"
    log "     - gene_association.gaf.gz (GO annotations)"
    log "     - orthologs.txt.gz (orthology data)"
    log "     - alleles.tsv.gz (genetic variations)"
    log "     - rnai_phenotypes.wb (RNAi phenotypes)"
    log "     - interactions.txt.gz (protein interactions)"
    exit 1
fi

log "Found custom data directory with files:"
ls -lh "${CUSTOM_DATA_DIR}"

# Copy/link files from custom data to working directories
copy_if_exists() {
    local FILENAME=$1
    local TARGET_DIR=$2
    local DESCRIPTION=$3

    if [ -f "${CUSTOM_DATA_DIR}/${FILENAME}" ]; then
        cp "${CUSTOM_DATA_DIR}/${FILENAME}" "${TARGET_DIR}/${FILENAME}"
        log "✅ Prepared ${DESCRIPTION} ($(du -h ${TARGET_DIR}/${FILENAME} | cut -f1))"
    else
        log "⚠️  ${FILENAME} not found - ${DESCRIPTION} will be skipped"
    fi
}

# Prepare data files
copy_if_exists "annotations.gff3.gz" "${DATA_DIR}/wormbase" "C. elegans genome annotations"
copy_if_exists "gene_association.gaf.gz" "${DATA_DIR}/go" "GO annotations"
copy_if_exists "orthologs.txt.gz" "${DATA_DIR}/orthologs" "Orthology data"
copy_if_exists "alleles.tsv.gz" "${DATA_DIR}/variations" "Genetic variations"
copy_if_exists "rnai_phenotypes.wb" "${DATA_DIR}/annotations" "RNAi phenotypes"
copy_if_exists "interactions.txt.gz" "${DATA_DIR}/interactions" "Protein interactions"

# Also check for any additional files and copy them
log "Checking for additional data files..."
for file in "${CUSTOM_DATA_DIR}"/*; do
    if [ -f "$file" ]; then
        filename=$(basename "$file")
        if [ ! -f "${DATA_DIR}/wormbase/${filename}" ] && \
           [ ! -f "${DATA_DIR}/go/${filename}" ] && \
           [ ! -f "${DATA_DIR}/orthologs/${filename}" ] && \
           [ ! -f "${DATA_DIR}/variations/${filename}" ] && \
           [ ! -f "${DATA_DIR}/annotations/${filename}" ] && \
           [ ! -f "${DATA_DIR}/interactions/${filename}" ]; then
            cp "$file" "${DATA_DIR}/wormbase/"
            log "✅ Copied additional file: ${filename}"
        fi
    fi
done

log "✅ WormBase data preparation complete!"
log "Data location: ${DATA_DIR}"
log ""
log "Data summary:"
du -sh "${DATA_DIR}"/*
