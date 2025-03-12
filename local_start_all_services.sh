#!/bin/bash
./docker_auth

# Define the local directory for PostgreSQL data
PG_DATA_DIR="/home/ec2-user/pg_data"

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
if ! docker network ls | grep -w intermine > /dev/null; then
    echo "Creating intermine network..."
    docker network create intermine || { echo "Failed to create network"; exit 1; }
fi

# Create the volume if it doesn't exist
if ! docker volume ls | grep -w db_backup_volume > /dev/null; then
    echo "Creating db_backup_volume..."
    docker volume create db_backup_volume || { echo "Failed to create volume"; exit 1; }
fi

# Container names
containers=("agr.local.alliancemine.bluegenes.server" "agr.local.alliancemine.solr.server" "agr.local.alliancemine.tomcat.server" "agr.local.alliancemine.postgres.server")

# Stop and remove containers if they are already running
for container in "${containers[@]}"; do
    stop_and_remove $container
done

# Launch Bluegenes container
./docker/local_run_bluegenes

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

# Launch Postgres container first (since other services depend on it)
docker run \
  -d \
  --name agr.local.alliancemine.postgres.server \
  --net intermine \
  -p 5432:5432 \
  --log-driver=gelf --log-opt gelf-address=udp://logs.alliancegenome.org:12201 \
  -e PGDATA=/var/lib/postgresql/data \
  -v "$PG_DATA_DIR:/var/lib/postgresql/data" \
  --health-cmd="pg_isready -U postgres" \
  --health-interval=10s \
  --health-timeout=5s \
  --health-retries=5 \
  100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_postgres_env:stage

# Wait for Postgres to be healthy
echo "Waiting for Postgres to be ready..."
while ! docker ps --filter "name=agr.local.alliancemine.postgres.server" --filter "health=healthy" --quiet; do
    sleep 5
done

# Launch remaining containers
# ... existing container launch commands with added health checks ...