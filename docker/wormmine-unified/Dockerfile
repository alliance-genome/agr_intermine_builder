# ============================================
# WormMine Unified Container
# Build Environment + Tomcat + Solr + RDS
# ============================================
# This container includes:
# - InterMine build tools (Java 8, Gradle)
# - Apache Tomcat 9.0 (webapp server)
# - Apache Solr 8.4.1 (search platform)
# - Perl with all required CPAN modules
# - Connects to external RDS PostgreSQL
# - sudo for manual operations
# ============================================

# ============================================
# Stage 1: Builder - Compile InterMine
# ============================================
FROM eclipse-temurin:8-jdk-alpine AS builder

LABEL maintainer="WormBase"
LABEL stage="builder"

# Install build dependencies including Perl and CPAN
RUN apk add --no-cache \
    bash \
    git \
    build-base \
    perl \
    perl-dev \
    perl-app-cpanminus \
    wget

# Install Perl modules required by WormMine
RUN cpanm --notest --force \
    Moose \
    Time::HiRes \
    FindBin \
    Digest::MD5 \
    Log::Log4perl \
    Bio::Perl \
    LWP::UserAgent \
    LWP \
    HTTP::Date \
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
    XML::Parser::PerlSAX \
    Ouch || true

# Clean up CPAN cache
RUN rm -rf /root/.cpanm /tmp/*

# Download project_build script
RUN wget -q https://raw.githubusercontent.com/intermine/intermine-scripts/master/project_build \
    -O /usr/local/bin/project_build && \
    chmod +x /usr/local/bin/project_build

# Set up environment
ENV GRADLE_OPTS="-server -Xmx30g -XX:+UseParallelGC -XX:+UseStringDeduplication -Xms2g -XX:SoftRefLRUPolicyMSPerMB=1 -XX:MaxHeapFreeRatio=99 -XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/tmp -Dorg.gradle.daemon=false -Dfile.encoding=UTF-8"
WORKDIR /build

# Clone WormMine repositories
ARG WORMMINE_BRANCH=im-298
ARG BIO_SOURCES_BRANCH=im-293

RUN git clone --depth 1 --branch ${WORMMINE_BRANCH} \
    https://github.com/WormBase/WormMine.git wormmine && \
    git clone --depth 1 --branch ${BIO_SOURCES_BRANCH} \
    https://github.com/WormBase/wormmine-bio-sources.git

# Build bio-sources
WORKDIR /build/wormmine-bio-sources
RUN ./gradlew clean install --parallel --stacktrace && \
    rm -rf /root/.gradle/caches/transforms-* /root/.gradle/caches/journal-*

# Copy properties template to both locations
WORKDIR /build/wormmine
COPY wormmine.properties.template /root/.intermine/wormmine.properties
COPY wormmine.properties.template /root/wormmine/wormmine.properties

# Pre-build WormMine dependencies
RUN mkdir -p /root/.gradle/daemon/4.9/dbmodel/resources && \
    mkdir -p /root/.gradle/daemon/4.9/dbmodel/build && \
    cp /build/wormmine/dbmodel/resources/so_terms /root/.gradle/daemon/4.9/dbmodel/resources/so_terms || true

RUN ./gradlew install --stacktrace && \
    rm -rf /root/.gradle/caches/transforms-* /root/.gradle/caches/journal-*

# ============================================
# Stage 2: Runtime - Unified Container
# ============================================
FROM eclipse-temurin:8-jdk-alpine

LABEL maintainer="WormBase"
LABEL description="WormMine unified container with Tomcat, Solr, and Build tools"

# Build argument for release version
ARG WORMBASE_RELEASE=WS290
LABEL version="${WORMBASE_RELEASE}"

# ============================================
# Install Runtime Dependencies
# ============================================
RUN apk add --no-cache \
    bash \
    curl \
    wget \
    postgresql-client \
    perl \
    perl-dev \
    perl-app-cpanminus \
    python3 \
    py3-pip \
    shadow \
    tini \
    lsof \
    procps \
    gettext \
    sudo \
    git \
    build-base

# ============================================
# Environment Variables
# ============================================
ENV JAVA_HOME=/opt/java/openjdk \
    CATALINA_HOME=/opt/tomcat \
    TOMCAT_VERSION=9.0.82 \
    TOMCAT_PORT=8080 \
    SOLR_VERSION=8.4.1 \
    SOLR_PORT=8983 \
    SOLR_HOME=/var/solr \
    WORMBASE_RELEASE=${WORMBASE_RELEASE}

# Memory settings for production
ENV CATALINA_OPTS="-Xmx8g -Xms8g -XX:+UseG1GC -XX:MaxGCPauseMillis=200" \
    SOLR_JAVA_MEM="-Xms4g -Xmx4g"

# RDS connection (override via environment)
ENV RDS_HOST=postgres \
    RDS_PORT=5432 \
    RDS_USER=postgres \
    RDS_PASSWORD=postgres \
    RDS_DB_NAME=wormmine_db \
    RDS_PROFILE_DB_NAME=wormmine_userprofile

# ============================================
# Create Application User
# ============================================
RUN addgroup -g 1000 intermine && \
    adduser -D -u 1000 -G intermine -h /opt/intermine intermine && \
    echo "intermine ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

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
WORKDIR /tmp
RUN wget -q "https://archive.apache.org/dist/lucene/solr/${SOLR_VERSION}/solr-${SOLR_VERSION}.tgz" && \
    tar -xzf "solr-${SOLR_VERSION}.tgz" && \
    mv "solr-${SOLR_VERSION}" /opt/solr && \
    rm "solr-${SOLR_VERSION}.tgz" && \
    mkdir -p ${SOLR_HOME}/data ${SOLR_HOME}/logs && \
    cp /opt/solr/server/solr/solr.xml ${SOLR_HOME}/data/ && \
    chown -R intermine:intermine /opt/solr ${SOLR_HOME}

# ============================================
# Copy Built InterMine Application
# ============================================
WORKDIR /opt/intermine

# Copy compiled WormMine from builder
COPY --from=builder --chown=intermine:intermine /build/wormmine ./wormmine
COPY --from=builder --chown=intermine:intermine /build/wormmine-bio-sources ./wormmine-bio-sources
COPY --from=builder --chown=intermine:intermine /root/.gradle /opt/intermine/.gradle

# Copy Perl modules and project_build script from builder
COPY --from=builder /usr/local/lib/perl5 /usr/local/lib/perl5
COPY --from=builder /usr/local/share/perl5 /usr/local/share/perl5
COPY --from=builder /usr/local/bin/project_build /usr/local/bin/project_build

# Create data and config directories
RUN mkdir -p \
    /opt/intermine/.intermine \
    /opt/intermine/data \
    /opt/intermine/logs \
    /root/data && \
    chown -R intermine:intermine /opt/intermine && \
    chmod -R u+w /opt/intermine/wormmine && \
    chmod -R 777 /root

# Switch to intermine user for bio-sources reinstall
USER intermine

# Reinstall bio-sources with correct user and Gradle home
WORKDIR /opt/intermine/wormmine-bio-sources
ENV GRADLE_OPTS="-server -Xmx30g -XX:+UseParallelGC -XX:+UseStringDeduplication -Xms2g -XX:SoftRefLRUPolicyMSPerMB=1 -XX:MaxHeapFreeRatio=99 -XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/opt/intermine/logs -Dorg.gradle.daemon=false -Dfile.encoding=UTF-8"
RUN ./gradlew clean install --stacktrace && \
    rm -rf /opt/intermine/.gradle/caches/transforms-* /opt/intermine/.gradle/caches/journal-*

# Back to wormmine directory
WORKDIR /opt/intermine/wormmine

# ============================================
# Configuration Files
# ============================================

# Create InterMine properties template (filled in by entrypoint)
COPY --chown=intermine:intermine wormmine.properties.template /opt/intermine/.intermine/wormmine.properties.template

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
    CMD curl -f http://localhost:${TOMCAT_PORT}/wormmine/service/version || exit 1

# ============================================
# Ports and Volumes
# ============================================
EXPOSE 8080 8983

VOLUME ["/opt/intermine/data", "/opt/intermine/logs", "/var/solr/data"]

# ============================================
# Startup
# ============================================
# Use tini for proper signal handling
ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]

CMD ["run"]
