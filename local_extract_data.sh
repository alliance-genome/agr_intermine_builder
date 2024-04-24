docker network create local

docker run \
  --name "agr.local.data_extractor" \
  --net local \
  -v "/data:/data" \
  -e ALLIANCE_RELEASE="7.0.0" \
  -e EXTRACTOR_OUTPUTDIR="/data" \
  -e NEO4J_HOST="stage-neo4j.alliancegenome.org" \
  --rm \
  "100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_java_software:stage" \
  java -Xms"31g" -Xmx"31g" -DDEFAULT_LOG_LEVEL=DEBUG -jar agr_intermine_data_extractor/target/agr_intermine_data_extractor-jar-with-dependencies.jar
