#!/bin/bash

# Function to stop and remove a container if it exists
stop_and_remove() {
    if [ $(docker ps -aq -f name=^/$1$) ]; then
        echo "Stopping and removing existing container $1..."
        docker stop $1
        docker rm $1
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
    --env-file .env \
    --log-driver=gelf --log-opt gelf-address=udp://logs.alliancegenome.org:12201 \
    intermine/bluegenes:latest

# Launch Solr container
docker run -d --name agr.local.alliancemine.solr.server \
    --net intermine \
    -p 8983:8983 \
    --env-file .env \
    --log-driver=gelf --log-opt gelf-address=udp://logs.alliancegenome.org:12201 \
    100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_solr_env:stage

# Launch Tomcat container
docker run -d --name agr.local.alliancemine.tomcat.server \
    --net intermine \
    -p 8080:8080 \
    --env-file .env \
    --log-driver=gelf --log-opt gelf-address=udp://logs.alliancegenome.org:12201 \
    100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_tomcat_env:stage

# Launch Postgres container
docker run -d --name agr.local.alliancemine.postgres.server \
    --net intermine \
    -p 5432:5432 \
    --log-driver=gelf --log-opt gelf-address=udp://logs.alliancegenome.org:12201 \
    100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_postgres_env:stage

# Launch Loaddata container
docker run -d --name agr.local.alliancemine.loaddata \
    --net intermine \
    -v db_backup_volume:/root/data \
    --env-file .env \
    --log-driver=gelf --log-opt gelf-address=udp://logs.alliancegenome.org:12201 \
    --command ./load_db_build_solr \
    100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_builder_env:stage
