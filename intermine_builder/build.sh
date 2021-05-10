#!/bin/bash

set -e

mkdir /root/.intermine
cd /root/

# Empty log
echo "" > /root/build.progress

# Build InterMine if any of the envvars are specified.
if [ ! -z ${IM_REPO_URL} ] || [ ! -z ${IM_REPO_BRANCH} ]; then
    echo "$(date +%Y/%m/%d-%H:%M) Start InterMine build" #>> /home/intermine/intermine/build.progress
    echo "$(date +%Y/%m/%d-%H:%M) Cloning ${IM_REPO_URL:-https://github.com/intermine/intermine} branch ${IM_REPO_BRANCH:-master} for InterMine build" #>> /home/intermine/intermine/build.progress
    git clone ${IM_REPO_URL:-https://github.com/intermine/intermine} intermine --single-branch --branch ${IM_REPO_BRANCH:-master} --depth=1

    cd intermine

    (cd plugin && ./gradlew clean && ./gradlew install) &&
    (cd intermine && ./gradlew clean && ./gradlew install) &&
    (cd bio && ./gradlew clean && ./gradlew install) &&
    (cd bio/sources && ./gradlew clean && ./gradlew install) &&
    (cd bio/postprocess/ && ./gradlew clean && ./gradlew install)

    # Read the version numbers of the built InterMine, as we'll need to set
    # the mine to use the same versions for it to use the local build.
    IM_VERSION=$(sed -n "s/^\s*version.*\+'\(.*\)'\s*$/\1/p" intermine/build.gradle)
    BIO_VERSION=$(sed -n "s/^\s*version.*\+'\(.*\)'\s*$/\1/p" bio/build.gradle)

    cd /root/
fi


echo "Starting mine build"
echo $MINE_REPO_URL
# Check if mine exists and is not empty
if [ -d ${MINE_NAME:-biotestmine} ] && [ ! -z "$(ls -A ${MINE_NAME:-biotestmine})" ]; then
    echo "$(date +%Y/%m/%d-%H:%M) Update ${MINE_NAME:-biotestmine} to newest version" #>> /home/intermine/intermine/build.progress
    cd ${MINE_NAME:-biotestmine}
    # git pull
    cd /root/
else
    # echo "$(date +%Y/%m/%d-%H:%M) Clone ${MINE_NAME:-biotestmine}" #>> /home/intermine/intermine/build.progress
    echo "$(date +%Y/%m/%d-%H:%M) Clone ${MINE_NAME:-biotestmine}"
    git clone ${MINE_REPO_URL:-https://github.com/intermine/biotestmine} ${MINE_NAME:-biotestmine}
    echo "$(date +%Y/%m/%d-%H:%M) Update keyword_search.properties to use http://solr" #>> /home/intermine/intermine/build.progress
    sed -i 's/localhost/'${SOLR_HOST:-solr}'/g' ./${MINE_NAME:-biotestmine}/dbmodel/resources/keyword_search.properties
    sed -i 's/localhost/'${SOLR_HOST:-solr}'/g' ./${MINE_NAME:-biotestmine}/dbmodel/resources/objectstoresummary.config.properties
fi

# If InterMine or Bio versions have been set (likely because of a custom
# InterMine build), update gradle.properties in the mine.
if [ ! -z ${IM_VERSION} ]; then
    sed -i "s/\(systemProp\.imVersion=\).*\$/\1${IM_VERSION}/" /root/${MINE_NAME:-biotestmine}/gradle.properties
fi
if [ ! -z ${BIO_VERSION} ]; then
    sed -i "s/\(systemProp\.bioVersion=\).*\$/\1${BIO_VERSION}/" /root/${MINE_NAME:-biotestmine}/gradle.properties
fi

# clone bio sources repo if url is given
if [ ! -z "$BIOSOURCES_REPO_URL" ]; then
    echo "$(date +%Y/%m/%d-%H:%M) Clone ${BIOSOURCES_REPO_URL}"
    git clone ${BIOSOURCES_REPO_URL} $MINE_NAME-bio-sources
    # build and install bio sources
    cd /root/$MINE_NAME-bio-sources
    echo "$(date +%Y/%m/%d-%H:%M) Building and Installing bio sources"
    ./gradlew clean --stacktrace
    ./gradlew install --stacktrace
    cd /root
fi

# Copy project_build from intermine_scripts repo
if [ ! -f /root/${MINE_NAME:-biotestmine}/project_build ]; then
    echo "$(date +%Y/%m/%d-%H:%M) Cloning intermine scripts repo to /home/intermine/intermine/intermine-scripts"
    git clone https://github.com/intermine/intermine-scripts
    echo "$(date +%Y/%m/%d-%H:%M) Copy project_build to /home/intermine/intermine/${MINE_NAME:-biotestmine}"
    cp /root/intermine-scripts/project_build /root/${MINE_NAME:-biotestmine}/project_build
    chmod +x /root/${MINE_NAME:-biotestmine}/project_build
fi

# Copy mine properties
if [ ! -f /root/.intermine/${MINE_NAME:-biotestmine}.properties ]; then
        echo "$(date +%Y/%m/%d-%H:%M) Copy ${MINE_NAME:-biotestmine}.properties to ~/.intermine/${MINE_NAME:-biotestmine}.properties"
        cp /root/alliancemine/${MINE_NAME:-biotestmine}.properties /root/.intermine/
    echo -e "$(date +%Y/%m/%d-%H:%M) Set properties in .intermine/${MINE_NAME:-biotestmine}.properties to\nPSQL_DB_NAME\tbiotestmine\nINTERMINE_PGUSER\t$INTERMINE_PGUSER\nINTERMINE_PSQL_PWD\t$INTERMINE_PGPASSWORD\nTOMCAT_USER\t$TOMCAT_USER\nTOMCAT_PWD\t$TOMCAT_PWD\nGRADLE_OPTS\t$GRADLE_OPTS" #>> /home/intermine/intermine/build.progress

    sed -i "s/PSQL_DB_NAME/${MINE_NAME:-biotestmine}/g" /root/.intermine/${MINE_NAME:-biotestmine}.properties
    sed -i "s/INTERMINE_PSQL_USER/${INTERMINE_PGUSER:-postgres}/g" /root/.intermine/${MINE_NAME:-biotestmine}.properties
    sed -i "s/INTERMINE_PSQL_PWD/${INTERMINE_PGPASSWORD:-postgres}/g" /root/.intermine/${MINE_NAME:-biotestmine}.properties
    sed -i "s/TOMCAT_USER/${TOMCAT_USER:-tomcat}/g" /root/.intermine/${MINE_NAME:-biotestmine}.properties
    sed -i "s/TOMCAT_PWD/${TOMCAT_PWD:-tomcat}/g" /root/.intermine/${MINE_NAME:-biotestmine}.properties
    sed -i "s/webapp.deploy.url=http:\/\/localhost:8080/webapp.deploy.url=http:\/\/${TOMCAT_HOST:-tomcat}:${TOMCAT_PORT:-8080}/g" /root/.intermine/${MINE_NAME:-biotestmine}.properties
    sed -i "s/serverName=INTERMINE_PGHOST/serverName=${INTERMINE_PGHOST:-postgres}:${INTERMINE_PGPORT:-5432}/g" /root/.intermine/${MINE_NAME:-biotestmine}.properties
fi

# Copy mine configs
if [ ! -f /root/${MINE_NAME:-biotestmine}/project.xml ]; then
    echo "$(date +%Y/%m/%d-%H:%M) Set correct source path in alliance else ***** project.xml"
    sed -i 's/dump="true"/dump="false"/g' /root/${MINE_NAME:-biotestmine}/project.xml
fi

#echo "$(date +%Y/%m/%d-%H:%M) Connect and create Postgres databases" #>> /home/intermine/intermine/build.progress

# # Wait for database
# dockerize -wait tcp://postgres:$PGPORT -timeout 60s
#until PGPASSWORD=${INTERMINE_PSQL_PWD:-postgres}; psql -U postgres -h ${INTERMINE_PGHOST:-postgres} -c '\l'; do
#  echo >&2 "$(date +%Y%m%dt%H%M%S) Postgres is unavailable - sleeping"
# sleep 1
#done
#echo >&2 "$(date +%Y%m%dt%H%M%S) Postgres is up - executing command"

# Close all open connections to database
#psql -U postgres -h ${INTERMINE_PGHOST:-postgres} -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE pid <> pg_backend_pid();"

#echo "$(date +%Y/%m/%d-%H:%M) Database is now available ..." #>> /home/intermine/intermine/build.progress
#echo "$(date +%Y/%m/%d-%H:%M) Reset databases and roles" #>> /home/intermine/intermine/build.progress

# Delete Databases if exist
#psql -U postgres -h ${INTERMINE_PGHOST:-postgres} -c "DROP DATABASE IF EXISTS \"${MINE_NAME:-biotestmine}\";"
#psql -U postgres -h ${INTERMINE_PGHOST:-postgres} -c "DROP DATABASE IF EXISTS \"items-${MINE_NAME:-biotestmine}\";"
#psql -U postgres -h ${INTERMINE_PGHOST:-postgres} -c "DROP DATABASE IF EXISTS \"userprofile-${MINE_NAME:-biotestmine}\";"

# Create Databases
#echo "$(date +%Y/%m/%d-%H:%M) Creating postgres database tables and roles.." #>> /home/intermine/intermine/build.progress
#psql -U postgres -h ${INTERMINE_PGHOST:-postgres} -c "ALTER USER ${INTERMINE_PSQL_USER:-postgres} WITH SUPERUSER;"
#psql -U postgres -h ${INTERMINE_PGHOST:-postgres} -c "CREATE DATABASE \"${MINE_NAME:-biotestmine}\";"
#psql -U postgres -h ${INTERMINE_PGHOST:-postgres} -c "CREATE DATABASE \"items-${MINE_NAME:-biotestmine}\";"
#psql -U postgres -h ${INTERMINE_PGHOST:-postgres} -c "CREATE DATABASE \"userprofile-${MINE_NAME:-biotestmine}\";"
#psql -U postgres -h ${INTERMINE_PGHOST:-postgres} -c "GRANT ALL PRIVILEGES ON DATABASE ${MINE_NAME:-biotestmine} to ${INTERMINE_PSQL_USER:-postgres};"
#psql -U postgres -h ${INTERMINE_PGHOST:-postgres} -c "GRANT ALL PRIVILEGES ON DATABASE \"items-${MINE_NAME:-biotestmine}\" to ${INTERMINE_PSQL_USER:-postgres};"
#psql -U postgres -h ${INTERMINE_PGHOST:-postgres} -c "GRANT ALL PRIVILEGES ON DATABASE \"userprofile-${MINE_NAME:-biotestmine}\" to ${INTERMINE_PSQL_USER:-postgres};"

cd ${MINE_NAME:-biotestmine}

echo "$(date +%Y/%m/%d-%H:%M) Running project_build script"
./project_build -b -T localhost /root/dump/dump

echo "$(date +%Y/%m/%d-%H:%M) Gradle: build userDB" #>> /home/intermine/intermine/build.progress
./gradlew buildUserDB --stacktrace #>> /home/intermine/intermine/build.progress

echo "$(date +%Y/%m/%d-%H:%M) Gradle: build webapp" #>> /home/intermine/intermine/build.progress
./gradlew cargoRedeployRemote  --stacktrace #>> /home/intermine/intermine/build.progress
sleep 60
./gradlew cargoRedeployRemote  --stacktrace #>> /home/intermine/intermine/build.progress
