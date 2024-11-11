# Function to stop and remove a container if it exists
stop_and_remove() {
    if [ "$(docker ps -aq -f name=^/$1$)" ]; then
        echo "Stopping and removing existing container '$1'..."
        if ! docker stop -t 30 "$1"; then
            echo "WARNING: Container '$1' did not stop gracefully after 30 seconds, forcing removal..."
            docker rm -f "$1"
        else
            docker rm "$1"
        fi
    else
        echo "Container '$1' not found, skipping..."
    fi
}

# Container names
containers=(
    "agr.local.alliancemine.bluegenes.server"
    "agr.local.alliancemine.solr.server"
    "agr.local.alliancemine.tomcat.server"
    "agr.local.alliancemine.postgres.server"
    "agr.local.alliancemine.loaddata"
)

# Stop and remove containers if they are already running
for container in "${containers[@]}"; do
    stop_and_remove $container
done