all:
	echo "Please choose make stage or make production"

stage:
	docker build --no-cache \
	--build-arg ENVIRONMENT=stage \
	--build-arg SOLR_HOST=stage-intermine-solr.alliancegenome.org \
	-t 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_builder_env:stage \
	-f intermine_builder/intermine_builder.Dockerfile ./intermine_builder

pushstage: stage
	docker push 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_builder_env:stage

production:
	docker build --no-cache \
	--build-arg ENVIRONMENT=production \
	--build-arg SOLR_HOST=production-intermine-solr.alliancegenome.org \
	-t 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_builder_env:production \
	-f intermine_builder/intermine_builder.Dockerfile ./intermine_builder

pushproduction: production
	docker push 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_builder_env:production
