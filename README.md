# README.md for AllianceMine Deployment Scripts
## Introduction
This README provides instructions on how to run various shell scripts included in this repository for testing and loading an instance of AllianceMine on an AWS EC2 box.

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
  - 

- `local_build_all.sh`
  - Runs the intermine_builder container and loads all extracted data.
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
