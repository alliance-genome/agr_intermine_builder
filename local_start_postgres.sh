docker run \
  --name postgres \
  --net local \
  -e PGDATA=/var/lib/postgresql/alliancedata \
  100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_postgres_env:stage
