# Function to stop and remove a container if it exists
stop_and_remove() {
    if [ $(docker ps -aq -f name=^/$1$) ]; then
        echo "Stopping and removing existing container $1..."
        # Stop the container with a timeout of 30 seconds
        docker stop -t 30 $1 || {
            echo "Container $1 did not stop gracefully after 30 seconds, forcing removal..."
            docker rm -f $1
        }
        # Ensure container is removed
        docker rm -f $1
    fi
}

# Container names
containers=("agr.local.alliancemine.bluegenes.server" "agr.local.alliancemine.solr.server" "agr.local.alliancemine.tomcat.server" "postgres" "agr.local.alliancemine.loaddata")

# Stop and remove containers if they are already running
for container in "${containers[@]}"; do
    stop_and_remove $container
done