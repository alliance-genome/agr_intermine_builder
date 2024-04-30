# README.md for AllianceMine Deployment Scripts
## Introduction
This README provides instructions on how to run various shell scripts included in this repository for testing and loading an instance of AllianceMine on an AWS EC2 box.

### List of shell scripts
- `local_download_images.sh`
  - Optionally pulls down 5 images from AWS ECR.
    - `agr_java_software:stage`
    - `agr_intermine_builder_env:stage`
    - `agr_intermine_solr_env:stage`
    - `agr_intermine_tomcat_env:stage`
    - `agr_intermine_postgres_env:stage`

- `local_extract_data.sh`
  - Downloads data from the FMS.
  - Modify to set release version.

- `local_start_postgres.sh`
  - Starts the Postgres container.
  - Creates the local directory for saving data if it doesn't already exist.

- `local_stop_postgres.sh`
  - Stops the Postgres container.

- `local_stop_postgres_remove_all_data.sh`
  - Stops the Postgres container.
  - Removes the local directory (wipes all saved data).

- `local_build_docker_intermine_builder.sh`
  - Builds the intermine Docker image from this repository.
  - Only necessary to run if the intermine_builder image from stage is not preferred (as in, there are some specific changes in this repo you need for your image).

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
  - Builds the Solr index using the local Postgres data.
  - Requires a local Postgres dump to be retrieved from the S3 bucket.