# Create the network if it doesn't exist
docker network ls | grep -w intermine || docker network create intermine

docker run \
  --name "agr.local.intermine_builder" \
  --net intermine \
  --rm \
  -v "/data:/root/data" \
  "100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_builder_env:stage" \
  ./local_build_db_all postgres postgres