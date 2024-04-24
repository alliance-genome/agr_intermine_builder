docker run \
  --name "agr.local.intermine_builder" \
  --net local \
  -v "/data:/root/data" \
  "100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_builder_env:stage" \
  ./local_build_db_all postgres postgres
