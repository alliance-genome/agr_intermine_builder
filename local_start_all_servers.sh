#!/bin/bash

# Define the local directory for PostgreSQL data
PG_DATA_DIR="/home/core/pg_data"

# Check if the directory exists, if not, create it
if [ ! -d "$PG_DATA_DIR" ]; then
    echo "Creating directory $PG_DATA_DIR"
    mkdir -p "$PG_DATA_DIR"
fi

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

# Create the volume if it doesn't exist
docker volume ls | grep -w db_backup_volume || docker volume create db_backup_volume

# Container names
containers=("agr.local.alliancemine.bluegenes.server" "agr.local.alliancemine.solr.server" "agr.local.alliancemine.tomcat.server" "agr.local.alliancemine.postgres.server" "agr.local.alliancemine.loaddata")

# Stop and remove containers if they are already running
for container in "${containers[@]}"; do
    stop_and_remove $container
done

# Launch Bluegenes container
docker run -d --name agr.local.alliancemine.bluegenes.server \
    --net intermine \
    -p 5000:5000 \
    --log-driver=gelf --log-opt gelf-address=udp://logs.alliancegenome.org:12201 \
    intermine/bluegenes:latest

# Launch Solr container
docker run -d --name agr.local.alliancemine.solr.server \
    --net intermine \
    -p 8983:8983 \
    --log-driver=gelf --log-opt gelf-address=udp://logs.alliancegenome.org:12201 \
    100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_solr_env:stage

# Launch Tomcat container
docker run -d --name agr.local.alliancemine.tomcat.server \
    --net intermine \
    -p 8080:8080 \
    --log-driver=gelf --log-opt gelf-address=udp://logs.alliancegenome.org:12201 \
    100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_tomcat_env:stage

# Launch Postgres container
docker run -d --name agr.local.alliancemine.postgres.server \
    --net intermine \
    -p 5432:5432 \
    --log-driver=gelf --log-opt gelf-address=udp://logs.alliancegenome.org:12201 \
    100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_postgres_env:stage

# Launch Loaddata container
docker run --name agr.local.alliancemine.loaddata \
    --net intermine \
    -v db_backup_volume:/root/data \
    -v "$PG_DATA_DIR:/var/lib/postgresql/data" \
    100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_builder_env:stage \
    ./local_load_db_build_solr

# docker run -d --name agr.local.alliancemine.loaddata \
#     --net intermine \
#     -v db_backup_volume:/root/data \
#     -v "$PG_DATA_DIR:/var/lib/postgresql/data" \
#     --log-driver=gelf --log-opt gelf-address=udp://logs.alliancegenome.org:12201 \
#     100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_builder_env:stage \
#     ./local_load_db_build_solr