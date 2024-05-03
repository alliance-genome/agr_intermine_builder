#!/bin/bash
./docker_auth

# Define the local directory for PostgreSQL data
PG_DATA_DIR="/home/ec2-user/pg_data"

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

# Create the network if it doesn't exist
docker network ls | grep -w intermine || docker network create intermine

# Container names
containers=("agr.local.alliancemine.solr.server" "agr.local.alliancemine.loaddata")

# Stop and remove containers if they are already running
for container in "${containers[@]}"; do
    stop_and_remove $container
done

# Launch Solr container
docker run -d --name agr.local.alliancemine.solr.server \
    --net intermine \
    -p 8983:8983 \
    --log-driver=gelf --log-opt gelf-address=udp://logs.alliancegenome.org:12201 \
    100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_solr_env:stage

# Launch Loaddata container
docker run --name agr.local.alliancemine.loaddata \
    --net intermine \
    -v db_backup_volume:/root/data \
    -v "$PG_DATA_DIR:/var/lib/postgresql/data" \
    --log-driver=gelf --log-opt gelf-address=udp://logs.alliancegenome.org:12201 \
    100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_builder_env:stage \
    ./local_load_db_build_solr