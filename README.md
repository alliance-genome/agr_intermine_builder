# README.md for AllianceMine Deployment Scripts
## Introduction
This README provides instructions on how to run various shell scripts included in this repository for testing and loading an instance of AllianceMine on an AWS EC2 box.

## Getting started

If using stage versions of all necessary Docker images, start by pulling down the images from AWS ECR:

    local_download_images.sh

This will pull down the following images:

    agr_java_software:stage
    agr_intermine_builder_env:stage
    agr_intermine_solr_env:stage
    agr_intermine_tomcat_env:stage
    agr_intermine_postgres_env:stage

Next, extract the data from the FMS using `local_extract_data.sh`. Please edit the script to the version of data you require from the FMS by modifying the variable `ALLIANCE_RELEASE="7.0.0"`. 

    local_extract_data.sh

Start Postgres once the data is extracted.

    local_start_postgres.sh

To stop Postgres at any point and retain the loaded data, use the following script:

    local_stop_postgres.sh

To stop Postgres at any point and **remove** the loaded data, use the following script:

    local_stop_postgres_remove_all_data.sh

Next, to load an entire run of the AllianceMine data, use the command:

    local_build_all.sh

This script requires a Postgres container to be running. Once it finishes, it will upload a dump of the data to the S3 bucket. It does not load Solr or start any of the other services.

Alternatively, to use a `bash` shell prompt to manually load data, use the script:

    local_intermine_builder_bash.sh

Inside of this container you will fine both the `alliancemine` and `alliancemine-bio-sources` repositories. If you update the `alliancemine` and `alliancemine-bio-sources` repositories on GitHub, and you would like to use the new changes to load data with this image, you need to first exit from the image and rebuild it with the following command:

    local_build_docker_intermine_builder.sh

This command will grab new copies of the repositories `alliancemine` and `alliancemine-bio-sources` and add them to the image to be used in the `bash` container. If you would like to use *custom* branches from `alliancemine` and/or `alliancemine-bio-sources`, you can edit the Dockerfile located at `intermine_builder/intermine_builder.Dockerfile` in this repository. Around lines ~23 and ~31 are two custom arguments which can be adjusted: 

      ARG ALLIANCEMINE_BRANCH_NAME=master
      ARG BIO_SOURCES_BRANCH_NAME=master

Changing those variables and running the `local_build_docker_intermine_builder.sh` script will pull down custom branches for those two repositories into your `intermine_builder` image using whatever branch names you've used in place of `master`. Be sure to change these variables back to `master` if you'd like to go back to the `master` branches at some point.

If you have manually loaded data into Postgres using the `bash` approach, you can use the following script to dump the data into the S3 bucket when you are finished:

    local_db_to_S3.sh

Once the data has been loaded into Postgres, you can then proceed with loading the data into Solr and launching the rest of the Intermine components.

First, start the other services that are needed with this script:

    local_start_all_services.sh

This will start the following containers:

    agr.local.alliancemine.bluegenes.server
    agr.local.alliancemine.solr.server
    agr.local.alliancemine.tomcat.server
    agr.local.alliancemine.postgres.server

If a service is already running it will just restart without issue.

Next, to load the data into Solr and run the rest of the scripts to start the website, you can use either of these two scripts:

    local_build_solr.sh
    local_build_solr_without_S3_dump.sh

The first script will use the latest Postgres S3 dump to load Solr (without the need for Postgres) and the second script will use the data from the local Postgres database itself.

One the Solr load is finished, the website should be available from the following URL: 

    http://dev-intermine.alliancegenome.org:5000/bluegenes/alliancemine

Services can be stopped using the following script:

    local_stop_all_services.sh

This script stops the following services:

    agr.local.alliancemine.bluegenes.server
    agr.local.alliancemine.solr.server 
    agr.local.alliancemine.tomcat.server
    agr.local.alliancemine.postgres.server
    agr.local.alliancemine.loaddata

## File Descriptions
### List of shell scripts
- `local_download_images.sh`
  - Pulls down 5 images from AWS ECR.
    - `agr_java_software:stage`
    - `agr_intermine_builder_env:stage`
    - `agr_intermine_solr_env:stage`
    - `agr_intermine_tomcat_env:stage`
    - `agr_intermine_postgres_env:stage`

- `local_extract_data.sh`
  - Downloads data from the FMS.
  - Uses `agr_java_software:stage` image.
  - Please modify script to set release version.

- `local_start_postgres.sh`
  - Starts the Postgres container.
  - Uses `agr_intermine_postgres_env:stage` image.
  - Creates the local directory for saving data if it doesn't already exist.

- `local_stop_postgres.sh`
  - Stops the Postgres container.

- `local_stop_postgres_remove_all_data.sh`
  - Stops the Postgres container.
  - Removes the local directory (wipes all saved data).

- `local_build_docker_intermine_builder.sh`
  - Builds the intermine Docker image from this repository.
  - Uses the Dockerfile found at `intermine_builder/intermine_builder.Dockerfile`
  - **IMPORTANT**: You can use custom `alliancemine` and `alliancemine-bio-sources` branches by editing the Dockerfile: `intermine_builder/intermine_builder.Dockerfile`
    - Around lines ~23 and ~31 are two custom arguments: 
      - `ARG ALLIANCEMINE_BRANCH_NAME=master`
      - `ARG BIO_SOURCES_BRANCH_NAME=master`
    - Updating these arguments with branch names from GitHub will allow you to compile these branches into the `intermine_builder` image when the shell script `local_build_docker_intermine_builder.sh` is used.

- `local_build_all.sh`
  - Runs the intermine_builder container and loads all extracted data.
  - A Postgres container must be running.
  - Dumps and uploads the Postgres db to S3.
  - Does not load Solr.

- `local_db_to_S3.sh`
  - Dumps and uploads the Postgres db to S3.
  - Only dumps and uploads, does not load any data.

- `local_intermine_builder_bash.sh`
  - Runs the intermine_builder container but does not load any data.
  - Places the user at bash prompt inside the container.

- `local_build_solr.sh`
  - Builds the Solr index using a Postgres dump from S3.
  - Requires an exisiting S3 dump to exist.

- `local_build_solr_without_S3_dump.sh`
  - Builds the Solr index using the local Postgres data.
  - Does not use or require an S3 dump.

- `local_start_all_services.sh`
  - Starts the following services:
    - `agr.local.alliancemine.bluegenes.server`
    - `agr.local.alliancemine.solr.server`
    - `agr.local.alliancemine.tomcat.server`
    - `agr.local.alliancemine.postgres.server`

- `'local_stop_all_services.sh`
  - Stops the following services:
    - `agr.local.alliancemine.bluegenes.server`
    - `agr.local.alliancemine.solr.server `
    - `agr.local.alliancemine.tomcat.server`
    - `agr.local.alliancemine.postgres.server`
    - `agr.local.alliancemine.loaddata`
