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
  - **Not** required to be run as images will be pulled down automatically at runtime.

- 