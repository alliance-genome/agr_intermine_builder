#!/bin/bash
# ============================================
# AllianceMine Data Extraction Script
# ============================================
# Downloads data from Alliance FMS and other sources
# Prepares data files for InterMine integration
# ============================================

set -e

echo "============================================"
echo "📥 AllianceMine Data Extraction"
echo "============================================"

DATA_DIR="/opt/intermine/data"
mkdir -p "${DATA_DIR}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# ============================================
# Alliance FMS Data Sources
# ============================================
FMS_BASE_URL="https://fms.alliancegenome.org/api/datafile"
RELEASE="${ALLIANCE_RELEASE:-8.2.0}"

log "Alliance Release: ${RELEASE}"
log "Data directory: ${DATA_DIR}"

# Function to download from FMS
download_fms_file() {
    local data_type=$1
    local file_name=$2
    local target_dir="${DATA_DIR}/${data_type}"

    mkdir -p "${target_dir}"

    log "Downloading ${data_type}..."

    # Construct FMS URL (actual URL structure depends on FMS API)
    local url="${FMS_BASE_URL}/${RELEASE}/${file_name}"

    wget -q -O "${target_dir}/${file_name}" "${url}" || {
        log "⚠️  Failed to download ${data_type} from ${url}"
        return 1
    }

    log "✅ Downloaded ${file_name} to ${target_dir}"
}

# ============================================
# Download Data Files
# ============================================

# Gene basic information
log "Downloading gene data..."
download_fms_file "genes" "GENE-BASIC_*.json" || true

# Alleles
log "Downloading allele data..."
download_fms_file "alleles" "ALLELE_*.json" || true

# Disease annotations
log "Downloading disease annotations..."
download_fms_file "disease" "DISEASE-ALLIANCE_*.json" || true

# Phenotype annotations
log "Downloading phenotype annotations..."
download_fms_file "phenotype" "PHENOTYPE_*.json" || true

# Orthology
log "Downloading orthology data..."
download_fms_file "orthology" "ORTHOLOGY-ALLIANCE_*.tsv" || true

# GO annotations
log "Downloading GO annotations..."
download_fms_file "go" "GO_*.gaf" || true

# ============================================
# Verify Downloaded Files
# ============================================
log "Verifying downloaded files..."

FILE_COUNT=$(find "${DATA_DIR}" -type f | wc -l)
log "Total files downloaded: ${FILE_COUNT}"

if [ "${FILE_COUNT}" -eq 0 ]; then
    log "⚠️  WARNING: No files were downloaded!"
    log "This may be expected if using pre-staged data"
fi

log "✅ Data extraction complete"
echo "============================================"
