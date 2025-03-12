.PHONY: all help stage pushstage production pushproduction

# Default target shows error message
all:
	echo "Please choose make stage or make production"

# Show help message with available commands
help:
	@echo "Available commands:"
	@echo "  make stage          - Build staging environment Docker image"
	@echo "  make pushstage      - Push staging Docker image to ECR"
	@echo "  make production     - Build production environment Docker image"
	@echo "  make pushproduction - Push production Docker image to ECR"

# Build staging environment image
stage:
	docker build --no-cache \
		--build-arg ENVIRONMENT=stage \
		--build-arg SOLR_HOST=stage-intermine-solr.alliancegenome.org \
		-t 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_builder_env:stage \
		-f intermine_builder/intermine_builder.Dockerfile ./intermine_builder

# Push staging image to ECR
pushstage: stage
	docker push 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_builder_env:stage

# Build production environment image
production:
	docker build --no-cache \
		--build-arg ENVIRONMENT=production \
		--build-arg SOLR_HOST=production-intermine-solr.alliancegenome.org \
		-t 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_builder_env:production \
		-f intermine_builder/intermine_builder.Dockerfile ./intermine_builder

# Push production image to ECR
pushproduction: production
	docker push 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_builder_env:production
