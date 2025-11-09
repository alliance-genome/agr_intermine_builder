# ============================================
# AllianceMine Unified Container
# Build Environment + Tomcat + Solr + RDS
# ============================================
# This container consolidates all InterMine components (except PostgreSQL)
# into a single optimized image for simplified deployment with AWS RDS.
#
# Architecture:
# - Build environment (Java 11, Gradle, InterMine tools)
# - Apache Tomcat 9.0 (webapp server)
# - Apache Solr 8.4 (search engine)
# - Connects to external RDS PostgreSQL
#
# Multi-stage build reduces final image size significantly.
# ============================================

# ============================================
# Stage 1: Builder - Compile InterMine
# ============================================
# InterMine requires Java 8 (1.8) - NOT Java 11
FROM eclipse-temurin:8-jdk-alpine AS builder

LABEL maintainer="Alliance of Genome Resources"
LABEL stage="builder"

# Install build dependencies
RUN apk add --no-cache \
    git \
    bash \
    wget \
    curl \
    perl \
    perl-dev \
    perl-app-cpanminus \
    build-base \
    postgresql-client

# Install Perl modules for InterMine
# Install in batches and ignore exit codes since --force may still return non-zero
RUN cpanm --notest --force Ouch LWP URI Module::Find Web::Scraper || true && \
    cpanm --notest --force Number::Format Perl6::Junction YAML || true && \
    cpanm --notest --force XML::DOM XML::Simple Text::Glob Log::Handler || true && \
    rm -rf /root/.cpanm /tmp/*

# Set up environment
ENV GRADLE_OPTS="-Xmx4g -Xms2g -Dorg.gradle.daemon=false"
WORKDIR /build

# Clone AllianceMine repositories
ARG ALLIANCEMINE_BRANCH=master
ARG BIO_SOURCES_BRANCH=master

RUN git clone --depth 1 --branch ${ALLIANCEMINE_BRANCH} \
    https://github.com/alliance-genome/alliancemine.git && \
    git clone --depth 1 --branch ${BIO_SOURCES_BRANCH} \
    https://github.com/alliance-genome/alliancemine-bio-sources.git

# Build bio-sources
WORKDIR /build/alliancemine-bio-sources
RUN ./gradlew clean install --parallel --stacktrace && \
    rm -rf /root/.gradle/caches/transforms-* /root/.gradle/caches/journal-*

# Copy properties template to both possible locations
# AllianceMine may look in either ~/.intermine/ or the project directory
WORKDIR /build/alliancemine
COPY alliancemine.properties.template /root/.intermine/alliancemine.properties
COPY alliancemine.properties.template /root/alliancemine/alliancemine.properties

# Pre-build AllianceMine dependencies
# Copy so_terms file to where Gradle expects it and create build output directory
RUN mkdir -p /root/.gradle/daemon/4.9/dbmodel/resources && \
    mkdir -p /root/.gradle/daemon/4.9/dbmodel/build && \
    cp /build/alliancemine/dbmodel/resources/so_terms /root/.gradle/daemon/4.9/dbmodel/resources/so_terms

RUN ./gradlew install --stacktrace && \
    rm -rf /root/.gradle/caches/transforms-* /root/.gradle/caches/journal-*

# ============================================
# Stage 2: Solr Setup
# ============================================
FROM eclipse-temurin:8-jre-alpine AS solr-builder

ARG SOLR_VERSION=8.4.1
ARG SOLR_SHA512=2f210dae8d6a07b111ede22005fbd16aa6848900cda8adb352a33e08229783a170dddb529a7eb990f5157d4f5427c199df2114b9c0ffecdf9490a2ac07c6bb09

# Install wget for downloading Solr
RUN apk add --no-cache wget bash

# Download and verify Solr
RUN wget -nv "https://archive.apache.org/dist/lucene/solr/${SOLR_VERSION}/solr-${SOLR_VERSION}.tgz" -O /tmp/solr.tgz && \
    echo "${SOLR_SHA512}  /tmp/solr.tgz" | sha512sum -c - && \
    mkdir -p /opt && \
    tar -C /opt -xzf /tmp/solr.tgz && \
    mv "/opt/solr-${SOLR_VERSION}" /opt/solr && \
    rm /tmp/solr.tgz

# Clean up unnecessary Solr components
RUN rm -rf /opt/solr/docs /opt/solr/example && \
    mkdir -p /opt/solr/server/solr/configsets/intermine

# ============================================
# Stage 3: Runtime - Unified Container
# ============================================
# Must use JDK (not JRE) because InterMine compiles Java at runtime
FROM eclipse-temurin:8-jdk-alpine

LABEL maintainer="Alliance of Genome Resources"
LABEL description="AllianceMine unified container with Tomcat + Solr + Build tools"

# Build argument for release version
ARG ALLIANCE_RELEASE=8.2.0
LABEL version="${ALLIANCE_RELEASE}"

# ============================================
# Install Runtime Dependencies
# ============================================
RUN apk add --no-cache \
    bash \
    curl \
    wget \
    postgresql-client \
    perl \
    python3 \
    py3-pip \
    shadow \
    tini \
    lsof \
    procps \
    gettext

# ============================================
# Environment Variables
# ============================================
ENV JAVA_HOME=/opt/java/openjdk \
    CATALINA_HOME=/opt/tomcat \
    TOMCAT_VERSION=9.0.82 \
    SOLR_HOME=/var/solr/data \
    SOLR_PORT=8983 \
    TOMCAT_PORT=8080 \
    ALLIANCE_RELEASE=${ALLIANCE_RELEASE}

# Memory settings for production
ENV CATALINA_OPTS="-Xmx8g -Xms8g -XX:+UseG1GC -XX:MaxGCPauseMillis=200" \
    SOLR_JAVA_MEM="-Xmx2g -Xms1g"

# RDS connection (override via environment)
ENV RDS_HOST=postgres \
    RDS_PORT=5432 \
    RDS_USER=postgres \
    RDS_PASSWORD=postgres \
    RDS_DB_NAME=alliancemine_db \
    RDS_PROFILE_DB_NAME=alliancemine_profiles_db

# ============================================
# Create Application User
# ============================================
RUN addgroup -g 1000 intermine && \
    adduser -D -u 1000 -G intermine -h /opt/intermine intermine

# ============================================
# Install Apache Tomcat
# ============================================
WORKDIR /tmp
RUN wget -q "https://archive.apache.org/dist/tomcat/tomcat-9/v${TOMCAT_VERSION}/bin/apache-tomcat-${TOMCAT_VERSION}.tar.gz" && \
    tar -xzf "apache-tomcat-${TOMCAT_VERSION}.tar.gz" -C /opt && \
    mv "/opt/apache-tomcat-${TOMCAT_VERSION}" "${CATALINA_HOME}" && \
    rm "apache-tomcat-${TOMCAT_VERSION}.tar.gz" && \
    rm -rf "${CATALINA_HOME}/webapps/docs" \
           "${CATALINA_HOME}/webapps/examples" \
           "${CATALINA_HOME}/webapps/host-manager" && \
    chown -R intermine:intermine "${CATALINA_HOME}"

# Configure Tomcat
COPY tomcat-users.xml "${CATALINA_HOME}/conf/tomcat-users.xml"
COPY server.xml "${CATALINA_HOME}/conf/server.xml"
RUN chmod 600 "${CATALINA_HOME}/conf/tomcat-users.xml" && \
    chown intermine:intermine "${CATALINA_HOME}/conf/tomcat-users.xml" "${CATALINA_HOME}/conf/server.xml"

# ============================================
# Install Apache Solr
# ============================================
COPY --from=solr-builder /opt/solr /opt/solr
COPY --from=solr-builder /opt/solr/server/solr/solr.xml /var/solr/data/solr.xml

# Create Solr data directories
RUN mkdir -p /var/solr/data /var/solr/logs && \
    chown -R intermine:intermine /opt/solr /var/solr

# Copy Solr configuration from builder
COPY --from=builder /build/alliancemine/dbmodel/resources/keyword_search.properties /opt/solr/server/solr/configsets/intermine/
COPY solr-config/ /opt/solr/server/solr/configsets/intermine/conf/

# ============================================
# Copy Built InterMine Application
# ============================================
WORKDIR /opt/intermine

# Copy compiled InterMine from builder
COPY --from=builder --chown=intermine:intermine /build/alliancemine ./alliancemine
COPY --from=builder --chown=intermine:intermine /build/alliancemine-bio-sources ./alliancemine-bio-sources
COPY --from=builder --chown=intermine:intermine /root/.gradle /opt/intermine/.gradle

# Create data and config directories and fix all permissions
RUN mkdir -p \
    /opt/intermine/.intermine \
    /opt/intermine/data \
    /opt/intermine/logs && \
    chown -R intermine:intermine /opt/intermine && \
    chmod -R u+w /opt/intermine/alliancemine

# ============================================
# Configuration Files
# ============================================

# Create InterMine properties template (filled in by entrypoint)
COPY --chown=intermine:intermine alliancemine.properties.template /opt/intermine/.intermine/alliancemine.properties.template

# Copy build and startup scripts
COPY --chown=intermine:intermine scripts/ /opt/intermine/scripts/
RUN chmod +x /opt/intermine/scripts/*.py

# ============================================
# Entrypoint Script
# ============================================
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# ============================================
# Health Checks
# ============================================
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${TOMCAT_PORT}/alliancemine/service/version || exit 1

# ============================================
# Ports and Volumes
# ============================================
EXPOSE 8080 8983

VOLUME ["/opt/intermine/data", "/var/solr/data", "/opt/intermine/logs"]

# ============================================
# Startup
# ============================================
WORKDIR /opt/intermine/alliancemine

USER intermine

# Use tini for proper signal handling
ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]

CMD ["run"]
