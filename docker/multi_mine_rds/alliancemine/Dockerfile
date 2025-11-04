FROM alpine:3.20
LABEL maintainer="Alliance of Genome Resources"
LABEL description="AllianceMine - Complete build environment with RDS support"
LABEL version="8.2.0-rds"

# ============================================
# Base System Setup
# ============================================
ENV JAVA_HOME="/usr/lib/jvm/default-jvm"
ENV PATH="$JAVA_HOME/bin:$PATH"
ENV HOME="/root"
ENV USER_HOME="/root"

# Install system dependencies
RUN apk add --no-cache \
    openjdk8 \
    openjdk8-jre \
    git \
    maven \
    bash \
    postgresql-client \
    aws-cli \
    wget \
    curl \
    ca-certificates \
    python3 \
    py3-pip \
    build-base \
    perl \
    perl-dev \
    perl-app-cpanminus \
    && ln -sf "${JAVA_HOME}/bin/"* "/usr/bin/"

# Install Perl modules required by InterMine
RUN cpanm --notest --force \
    Ouch \
    LWP \
    URI \
    Module::Find \
    Web::Scraper \
    Number::Format \
    Perl6::Junction \
    YAML \
    XML::DOM \
    XML::Simple \
    Text::Glob \
    Log::Handler \
    Getopt::Std \
    Digest::MD5 \
    && rm -rf /root/.cpanm /tmp/*

# ============================================
# InterMine Build Environment
# ============================================
ENV MEM_OPTS="-Xmx16g -Xms8g"
ENV GRADLE_OPTS="-server ${MEM_OPTS} -XX:+UseParallelGC -XX:SoftRefLRUPolicyMSPerMB=1 -XX:+HeapDumpOnOutOfMemoryError -XX:MaxHeapFreeRatio=99 -Dorg.gradle.daemon=false -Duser.home=/root"
ENV GRADLE_USER_HOME="/root/.gradle"

WORKDIR /root
RUN mkdir -p .intermine

# ============================================
# Clone AllianceMine Repositories
# ============================================

# Clone AllianceMine
ARG ALLIANCEMINE_BRANCH=master
RUN git clone --depth 1 --branch ${ALLIANCEMINE_BRANCH} \
    https://github.com/alliance-genome/alliancemine.git

# Clone AllianceMine bio-sources
ARG BIO_SOURCES_BRANCH=master
RUN git clone --depth 1 --branch ${BIO_SOURCES_BRANCH} \
    https://github.com/alliance-genome/alliancemine-bio-sources.git

# ============================================
# Build Bio-sources
# ============================================
WORKDIR /root/alliancemine-bio-sources
RUN ./gradlew clean --stacktrace && \
    ./gradlew install --parallel --stacktrace && \
    rm -rf /root/.gradle/caches/transforms-* \
           /root/.gradle/caches/journal-* \
           /tmp/*

# ============================================
# RDS Configuration
# ============================================
WORKDIR /root/alliancemine

# RDS environment variables (override via docker-compose)
ENV RDS_HOST="postgres"
ENV RDS_PORT="5432"
ENV RDS_USER="postgres"
ENV RDS_PASSWORD="postgres"
ENV RDS_DB_NAME="alliancemine_db"
ENV RDS_PROFILE_DB_NAME="alliancemine_profiles_db"
ENV ALLIANCE_RELEASE="8.2.0"

# Create .pgpass for RDS authentication
RUN echo "*:*:*:${RDS_USER}:${RDS_PASSWORD}" > /root/.pgpass && \
    chmod 400 /root/.pgpass

# Create AllianceMine properties file for RDS
COPY <<'PROPERTIES_EOF' /root/.intermine/alliancemine.properties
# AllianceMine RDS Configuration
# Database connections use HikariCP for connection pooling

# Production Database (Main data)
db.production.datasource.class=com.zaxxer.hikari.HikariDataSource
db.production.datasource.dataSourceClassName=org.postgresql.ds.PGSimpleDataSource
db.production.datasource.dataSourceProperties.serverName=${RDS_HOST}
db.production.datasource.dataSourceProperties.portNumber=${RDS_PORT}
db.production.datasource.dataSourceProperties.databaseName=${RDS_DB_NAME}
db.production.datasource.dataSourceProperties.user=${RDS_USER}
db.production.datasource.dataSourceProperties.password=${RDS_PASSWORD}
db.production.datasource.maximumPoolSize=20
db.production.datasource.minimumIdle=10
db.production.datasource.connectionTimeout=30000
db.production.datasource.idleTimeout=600000
db.production.datasource.maxLifetime=1800000
db.production.driver=org.postgresql.Driver
db.production.platform=PostgreSQL

# Common Target Items Database
db.common-tgt-items.datasource.class=com.zaxxer.hikari.HikariDataSource
db.common-tgt-items.datasource.dataSourceClassName=org.postgresql.ds.PGSimpleDataSource
db.common-tgt-items.datasource.dataSourceProperties.serverName=${RDS_HOST}
db.common-tgt-items.datasource.dataSourceProperties.portNumber=${RDS_PORT}
db.common-tgt-items.datasource.dataSourceProperties.databaseName=${RDS_DB_NAME}
db.common-tgt-items.datasource.dataSourceProperties.user=${RDS_USER}
db.common-tgt-items.datasource.dataSourceProperties.password=${RDS_PASSWORD}
db.common-tgt-items.datasource.maximumPoolSize=10
db.common-tgt-items.datasource.minimumIdle=5
db.common-tgt-items.driver=org.postgresql.Driver
db.common-tgt-items.platform=PostgreSQL

# User Profile Database
db.userprofile-production.datasource.class=com.zaxxer.hikari.HikariDataSource
db.userprofile-production.datasource.dataSourceClassName=org.postgresql.ds.PGSimpleDataSource
db.userprofile-production.datasource.dataSourceProperties.serverName=${RDS_HOST}
db.userprofile-production.datasource.dataSourceProperties.portNumber=${RDS_PORT}
db.userprofile-production.datasource.dataSourceProperties.databaseName=${RDS_PROFILE_DB_NAME}
db.userprofile-production.datasource.dataSourceProperties.user=${RDS_USER}
db.userprofile-production.datasource.dataSourceProperties.password=${RDS_PASSWORD}
db.userprofile-production.datasource.maximumPoolSize=5
db.userprofile-production.datasource.minimumIdle=2
db.userprofile-production.driver=org.postgresql.Driver
db.userprofile-production.platform=PostgreSQL

# Project Configuration
project.title=AllianceMine
project.subTitle=Alliance of Genome Resources
project.releaseVersion=${ALLIANCE_RELEASE}
project.sitePrefix=http://localhost:8080

# Web Application
webapp.deploy.url=http://localhost:8080/manager/text
webapp.baseurl=http://localhost:8080
webapp.path=alliancemine
webapp.manager=manager
webapp.password=manager

# XML Factory
systemProp.javax.xml.stream.XMLOutputFactory=com.sun.xml.internal.stream.XMLOutputFactoryImpl
PROPERTIES_EOF

# ============================================
# Data Source Configuration
# ============================================

# Update Solr configuration to use local Solr
RUN sed -i 's/localhost/solr/g' dbmodel/resources/keyword_search.properties && \
    sed -i 's/localhost/solr/g' dbmodel/resources/objectstoresummary.config.properties

# Make load scripts executable
RUN chmod +x ./load_db_build_solr

# ============================================
# Entrypoint Script
# ============================================
COPY <<'ENTRYPOINT_EOF' /entrypoint.sh
#!/bin/bash
set -e

echo "🚀 AllianceMine RDS Builder Starting..."
echo "========================================="
echo "RDS Host: ${RDS_HOST}:${RDS_PORT}"
echo "Main DB: ${RDS_DB_NAME}"
echo "Profile DB: ${RDS_PROFILE_DB_NAME}"
echo "Alliance Release: ${ALLIANCE_RELEASE}"
echo "========================================="

# Wait for RDS to be available
echo "⏳ Waiting for RDS PostgreSQL..."
MAX_ATTEMPTS=30
ATTEMPT=0

until pg_isready -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -t 5; do
    ATTEMPT=$((ATTEMPT+1))
    if [ $ATTEMPT -ge $MAX_ATTEMPTS ]; then
        echo "❌ Failed to connect to RDS after $MAX_ATTEMPTS attempts"
        exit 1
    fi
    echo "Waiting for RDS... (attempt $ATTEMPT/$MAX_ATTEMPTS)"
    sleep 5
done

echo "✅ RDS is available!"

# Update properties file with environment variables
echo "📝 Configuring properties..."
sed -i "s/\${RDS_HOST}/${RDS_HOST}/g" /root/.intermine/alliancemine.properties
sed -i "s/\${RDS_PORT}/${RDS_PORT}/g" /root/.intermine/alliancemine.properties
sed -i "s/\${RDS_USER}/${RDS_USER}/g" /root/.intermine/alliancemine.properties
sed -i "s/\${RDS_PASSWORD}/${RDS_PASSWORD}/g" /root/.intermine/alliancemine.properties
sed -i "s/\${RDS_DB_NAME}/${RDS_DB_NAME}/g" /root/.intermine/alliancemine.properties
sed -i "s/\${RDS_PROFILE_DB_NAME}/${RDS_PROFILE_DB_NAME}/g" /root/.intermine/alliancemine.properties
sed -i "s/\${ALLIANCE_RELEASE}/${ALLIANCE_RELEASE}/g" /root/.intermine/alliancemine.properties

echo "✅ Properties configured"

# Check and create databases if needed
echo "📦 Checking RDS databases..."

# Main database
if ! psql -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -d postgres -lqt | cut -d \| -f 1 | grep -qw "${RDS_DB_NAME}"; then
    echo "Creating main database: ${RDS_DB_NAME}"
    psql -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -d postgres -c "CREATE DATABASE ${RDS_DB_NAME};"
    echo "✅ Main database created"
else
    echo "✅ Main database exists"
fi

# Profile database
if ! psql -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -d postgres -lqt | cut -d \| -f 1 | grep -qw "${RDS_PROFILE_DB_NAME}"; then
    echo "Creating profile database: ${RDS_PROFILE_DB_NAME}"
    psql -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -d postgres -c "CREATE DATABASE ${RDS_PROFILE_DB_NAME};"
    echo "✅ Profile database created"
else
    echo "✅ Profile database exists"
fi

echo "✅ AllianceMine ready for build!"
echo ""
echo "To build:"
echo "  cd /root/alliancemine"
echo "  ./gradlew buildDB"
echo "  ./project_build -b"
echo "  ./gradlew cargoRedeployRemote"
echo ""

# Execute provided command or start bash
exec "$@"
ENTRYPOINT_EOF

RUN chmod +x /entrypoint.sh

# ============================================
# Final Setup
# ============================================
WORKDIR /root/alliancemine

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD java -version || exit 1

# Set entrypoint
ENTRYPOINT ["/entrypoint.sh"]

# Default command
CMD ["/bin/bash"]
