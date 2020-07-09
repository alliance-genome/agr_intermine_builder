build:
	cd intermine_builder && docker build -t docker-intermine-gradle_intermine_builder  -f intermine_builder.Dockerfile . 

run:
	docker run --rm -it -e MINE_NAME=alliancemine -e MINE_REPO_URL=https://github.com/yeastgenome/alliancemine --net docker-intermine-gradle_default docker-intermine-gradle_intermine_builder:latest /bin/sh 
