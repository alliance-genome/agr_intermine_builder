#!/bin/bash

# CDN Management Script for Multi-Tenant InterMine
# Manages static assets served via Nginx CDN

set -e

DOCKER_VOLUME="cdn_data"
CDN_CONTAINER="nginx-proxy"
CDN_PATH="/var/www/cdn"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

usage() {
    cat <<EOF
CDN Management Script

Usage: $0 <command> [options]

Commands:
  upload <local_path> <cdn_path>  Upload files to CDN
  list [path]                     List CDN contents
  download <cdn_path> <local>     Download files from CDN
  delete <cdn_path>               Delete files from CDN
  sync <local_dir> <cdn_path>     Sync directory to CDN
  structure                       Create standard CDN directory structure
  status                          Show CDN usage statistics

Examples:
  $0 upload ./jquery.min.js /cdn/js/jquery/3.6.0/jquery.min.js
  $0 list /cdn/js
  $0 sync ./bluegenes-assets /cdn/bluegenes
  $0 structure
  $0 status

CDN URL Format:
  https://yourdomain.com/cdn/<path>

Standard Structure:
  /cdn/
    ├── js/              JavaScript libraries
    ├── css/             Stylesheets
    ├── fonts/           Web fonts
    ├── images/          Shared images
    ├── bluegenes/       BlueGenes static assets
    └── mines/           Mine-specific assets
        ├── alliancemine/
        ├── wormmine/
        └── ...
EOF
    exit 1
}

# Check if docker-compose is running
check_running() {
    if ! docker ps | grep -q "$CDN_CONTAINER"; then
        echo -e "${RED}Error: $CDN_CONTAINER is not running${NC}"
        echo "Start the stack with: docker-compose up -d"
        exit 1
    fi
}

# Upload files to CDN
upload_file() {
    local local_path="$1"
    local cdn_path="$2"

    if [ ! -e "$local_path" ]; then
        echo -e "${RED}Error: $local_path does not exist${NC}"
        exit 1
    fi

    check_running

    # Remove leading /cdn if present
    cdn_path="${cdn_path#/cdn}"
    cdn_path="${cdn_path#/}"

    echo -e "${GREEN}Uploading $local_path to /cdn/$cdn_path${NC}"

    # Create parent directory if needed
    local parent_dir=$(dirname "$cdn_path")
    if [ "$parent_dir" != "." ]; then
        docker exec "$CDN_CONTAINER" mkdir -p "$CDN_PATH/$parent_dir"
    fi

    # Upload file or directory
    docker cp "$local_path" "$CDN_CONTAINER:$CDN_PATH/$cdn_path"

    echo -e "${GREEN}✓ Upload complete${NC}"
    echo -e "URL: https://yourdomain.com/cdn/$cdn_path"
}

# List CDN contents
list_cdn() {
    local path="${1:-/}"

    check_running

    # Remove leading /cdn if present
    path="${path#/cdn}"
    path="${path#/}"

    echo -e "${GREEN}CDN Contents: /cdn/$path${NC}"
    docker exec "$CDN_CONTAINER" ls -lah "$CDN_PATH/$path" 2>/dev/null || {
        echo -e "${RED}Path not found: /cdn/$path${NC}"
        exit 1
    }
}

# Download from CDN
download_file() {
    local cdn_path="$1"
    local local_path="$2"

    check_running

    # Remove leading /cdn if present
    cdn_path="${cdn_path#/cdn}"
    cdn_path="${cdn_path#/}"

    echo -e "${GREEN}Downloading /cdn/$cdn_path to $local_path${NC}"
    docker cp "$CDN_CONTAINER:$CDN_PATH/$cdn_path" "$local_path"
    echo -e "${GREEN}✓ Download complete${NC}"
}

# Delete from CDN
delete_file() {
    local cdn_path="$1"

    check_running

    # Remove leading /cdn if present
    cdn_path="${cdn_path#/cdn}"
    cdn_path="${cdn_path#/}"

    read -p "Are you sure you want to delete /cdn/$cdn_path? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        docker exec "$CDN_CONTAINER" rm -rf "$CDN_PATH/$cdn_path"
        echo -e "${GREEN}✓ Deleted /cdn/$cdn_path${NC}"
    else
        echo "Cancelled"
    fi
}

# Sync directory to CDN
sync_dir() {
    local local_dir="$1"
    local cdn_path="$2"

    if [ ! -d "$local_dir" ]; then
        echo -e "${RED}Error: $local_dir is not a directory${NC}"
        exit 1
    fi

    check_running

    # Remove leading /cdn if present
    cdn_path="${cdn_path#/cdn}"
    cdn_path="${cdn_path#/}"

    echo -e "${GREEN}Syncing $local_dir to /cdn/$cdn_path${NC}"

    # Create parent directory
    docker exec "$CDN_CONTAINER" mkdir -p "$CDN_PATH/$cdn_path"

    # Use rsync if available, otherwise tar
    if command -v rsync &> /dev/null; then
        # Create temporary container with rsync
        docker exec "$CDN_CONTAINER" sh -c "apk add rsync 2>/dev/null || true"
        rsync -avz --delete "$local_dir/" "$CDN_CONTAINER:$CDN_PATH/$cdn_path/"
    else
        # Fallback to tar
        tar -czf - -C "$local_dir" . | docker exec -i "$CDN_CONTAINER" tar -xzf - -C "$CDN_PATH/$cdn_path"
    fi

    echo -e "${GREEN}✓ Sync complete${NC}"
}

# Create standard directory structure
create_structure() {
    check_running

    echo -e "${GREEN}Creating standard CDN directory structure${NC}"

    docker exec "$CDN_CONTAINER" sh -c "
        mkdir -p $CDN_PATH/{js,css,fonts,images,bluegenes}
        mkdir -p $CDN_PATH/mines/{alliancemine,wormmine,flymine,zebrafishmine,mousemine,ratmine}
        mkdir -p $CDN_PATH/js/{jquery,bootstrap,datatables,d3,react}
        mkdir -p $CDN_PATH/css/{bootstrap,themes}
        mkdir -p $CDN_PATH/fonts/{roboto,opensans}

        # Create a simple index.html
        cat > $CDN_PATH/index.html <<'HTML'
<!DOCTYPE html>
<html>
<head>
    <title>InterMine CDN</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        h1 { color: #333; }
        ul { list-style-type: none; }
        a { color: #0066cc; text-decoration: none; }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <h1>InterMine CDN</h1>
    <p>Static assets for InterMine instances</p>
    <ul>
        <li><a href=\"./js/\">JavaScript Libraries</a></li>
        <li><a href=\"./css/\">Stylesheets</a></li>
        <li><a href=\"./fonts/\">Fonts</a></li>
        <li><a href=\"./images/\">Images</a></li>
        <li><a href=\"./bluegenes/\">BlueGenes Assets</a></li>
        <li><a href=\"./mines/\">Mine-Specific Assets</a></li>
    </ul>
</body>
</html>
HTML
    "

    echo -e "${GREEN}✓ Directory structure created${NC}"
    echo ""
    echo "CDN Structure:"
    docker exec "$CDN_CONTAINER" tree -L 2 "$CDN_PATH" 2>/dev/null || \
    docker exec "$CDN_CONTAINER" find "$CDN_PATH" -maxdepth 2 -type d
}

# Show CDN statistics
show_status() {
    check_running

    echo -e "${GREEN}CDN Status${NC}"
    echo ""

    # Disk usage
    echo "Disk Usage:"
    docker exec "$CDN_CONTAINER" du -sh "$CDN_PATH" 2>/dev/null || echo "N/A"
    echo ""

    # File counts
    echo "File Counts:"
    docker exec "$CDN_CONTAINER" sh -c "
        echo \"  Total files: \$(find $CDN_PATH -type f | wc -l)\"
        echo \"  JavaScript: \$(find $CDN_PATH -name '*.js' | wc -l)\"
        echo \"  CSS: \$(find $CDN_PATH -name '*.css' | wc -l)\"
        echo \"  Images: \$(find $CDN_PATH -name '*.png' -o -name '*.jpg' -o -name '*.svg' | wc -l)\"
        echo \"  Fonts: \$(find $CDN_PATH -name '*.woff*' -o -name '*.ttf' | wc -l)\"
    "
    echo ""

    # Top directories by size
    echo "Top Directories by Size:"
    docker exec "$CDN_CONTAINER" du -sh "$CDN_PATH"/* 2>/dev/null | sort -hr | head -10 || echo "N/A"
}

# Main
case "${1:-}" in
    upload)
        [ -z "$2" ] || [ -z "$3" ] && usage
        upload_file "$2" "$3"
        ;;
    list)
        list_cdn "${2:-/}"
        ;;
    download)
        [ -z "$2" ] || [ -z "$3" ] && usage
        download_file "$2" "$3"
        ;;
    delete)
        [ -z "$2" ] && usage
        delete_file "$2"
        ;;
    sync)
        [ -z "$2" ] || [ -z "$3" ] && usage
        sync_dir "$2" "$3"
        ;;
    structure)
        create_structure
        ;;
    status)
        show_status
        ;;
    *)
        usage
        ;;
esac
