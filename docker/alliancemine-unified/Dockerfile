# ============================================
# AllianceMine Unified Container
# Build Environment + Tomcat + RDS
# ============================================
# This container consolidates all InterMine components (except PostgreSQL)
# into a single optimized image for simplified deployment with AWS RDS.
#
# Architecture:
# - Build environment (Java 8, Gradle, InterMine tools)
# - Apache Tomcat 9.0 (webapp server)
# - Connects to external RDS PostgreSQL
#
# Multi-stage build reduces final image size significantly.
# ============================================

# ============================================
# Stage 1: Builder - Compile InterMine
# ============================================
# Use pre-built Perl base image from ECR (or build locally if not available)
# To use ECR image: --build-arg PERL_BASE_IMAGE=<account>.dkr.ecr.us-east-1.amazonaws.com/alliancemine-perl-base:latest
ARG PERL_BASE_IMAGE=eclipse-temurin:8-jdk-alpine
FROM ${PERL_BASE_IMAGE} AS builder

LABEL maintainer="Alliance of Genome Resources"
LABEL stage="builder"

# Install build dependencies
# If using pre-built perl base, these are already installed
# If using eclipse-temurin base, install them now
RUN if ! command -v cpanm &> /dev/null; then \
        apk add --no-cache git build-base perl perl-dev perl-app-cpanminus && \
        cpanm --notest --force Ouch LWP URI Module::Find Web::Scraper || true && \
        cpanm --notest --force Number::Format Perl6::Junction YAML || true && \
        cpanm --notest --force XML::DOM XML::Simple Text::Glob Log::Handler || true && \
        cpanm --notest --force XML::Parser::PerlSAX || true && \
        rm -rf /root/.cpanm /tmp/* && \
        wget -q https://raw.githubusercontent.com/intermine/intermine-scripts/master/project_build \
            -O /usr/local/bin/project_build && \
        chmod +x /usr/local/bin/project_build; \
    else \
        apk add --no-cache git build-base; \
    fi

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
# Stage 2: Runtime - Unified Container
# ============================================
# Must use JDK (not JRE) because InterMine compiles Java at runtime
FROM eclipse-temurin:8-jdk-alpine

LABEL maintainer="Alliance of Genome Resources"
LABEL description="AllianceMine unified container with Tomcat + Build tools"

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
    TOMCAT_PORT=8080 \
    ALLIANCE_RELEASE=${ALLIANCE_RELEASE}

# Memory settings for production
ENV CATALINA_OPTS="-Xmx8g -Xms8g -XX:+UseG1GC -XX:MaxGCPauseMillis=200"

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
# Copy Built InterMine Application
# ============================================
WORKDIR /opt/intermine

# Copy compiled InterMine from builder
COPY --from=builder --chown=intermine:intermine /build/alliancemine ./alliancemine
COPY --from=builder --chown=intermine:intermine /build/alliancemine-bio-sources ./alliancemine-bio-sources
COPY --from=builder --chown=intermine:intermine /root/.gradle /opt/intermine/.gradle

# Copy Perl modules and project_build script from builder
# Alpine installs CPAN modules to multiple locations
COPY --from=builder /usr/local/lib/perl5 /usr/local/lib/perl5
COPY --from=builder /usr/local/share/perl5 /usr/local/share/perl5
COPY --from=builder /usr/local/bin/project_build /usr/local/bin/project_build

# Fix hardcoded /root path in build.gradle to use /opt/intermine
RUN sed -i 's|/root/alliancemine|/opt/intermine/alliancemine|g' \
    /opt/intermine/alliancemine/build.gradle

# Create data and config directories and fix all permissions
# CRITICAL: chmod 777 on /root so intermine user can access /root/data mount
RUN mkdir -p \
    /opt/intermine/.intermine \
    /opt/intermine/data \
    /opt/intermine/logs \
    /root/data && \
    chown -R intermine:intermine /opt/intermine && \
    chmod -R u+w /opt/intermine/alliancemine && \
    chmod -R 777 /root

# Switch to intermine user for bio-sources reinstall
USER intermine

# Reinstall bio-sources with correct user and Gradle home
# This ensures JARs are in the correct location for runtime builds
# Sequential build to avoid OOM with parallel compilation during Docker build
WORKDIR /opt/intermine/alliancemine-bio-sources
ENV GRADLE_OPTS="-Xmx4g -Xms2g -Dorg.gradle.daemon=false"
RUN ./gradlew clean install --stacktrace && \
    rm -rf /opt/intermine/.gradle/caches/transforms-* /opt/intermine/.gradle/caches/journal-*

# Back to alliancemine directory
WORKDIR /opt/intermine/alliancemine

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
# Switch back to root to install entrypoint script
USER root
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Switch back to intermine user for runtime
USER intermine

# ============================================
# Health Checks
# ============================================
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${TOMCAT_PORT}/alliancemine/service/version || exit 1

# ============================================
# Ports and Volumes
# ============================================
EXPOSE 8080

VOLUME ["/opt/intermine/data", "/opt/intermine/logs"]

# ============================================
# Startup
# ============================================
# Already running as intermine user (set earlier after bio-sources reinstall)

# Use tini for proper signal handling
ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]

CMD ["run"]
