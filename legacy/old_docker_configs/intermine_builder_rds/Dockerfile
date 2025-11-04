FROM alpine:3.20
LABEL maintainer="Alliance of Genome Resources"
LABEL description="InterMine Builder for RDS/Ephemeral builds - optimized for cloud databases"
LABEL version="4.0"
LABEL java.version="8"

# Java environment
ENV JAVA_HOME="/usr/lib/jvm/default-jvm"
ENV PATH="$JAVA_HOME/bin:$PATH"

# Install Java
RUN apk add --no-cache openjdk8-jdk openjdk8-jre && \
    ln -sf "${JAVA_HOME}/bin/"* "/usr/bin/"

# Install core development tools + RDS specific tools
RUN apk add --no-cache \
    git \
    maven \
    bash \
    postgresql-client \
    aws-cli \
    wget \
    ca-certificates \
    curl \
    py3-pip \
    python3 \
    jq \
    netcat-openbsd \
    redis

# Install Perl and common Perl packages from Alpine repos
RUN apk add --no-cache \
    perl \
    perl-utils \
    perl-module-build \
    perl-module-build-tiny \
    perl-package-stash \
    perl-sub-identify \
    perl-moose \
    perl-datetime \
    perl-html-parser \
    perl-html-tree \
    perl-io-gzip \
    perl-list-moreutils-xs \
    perl-text-csv_xs \
    perl-xml-libxml \
    perl-xml-parser

# Temporarily install build dependencies for additional Perl modules
RUN apk add --no-cache --virtual .perl-build-deps \
    build-base \
    perl-dev \
    perl-app-cpanminus \
    gcc \
    make \
    && cpanm --notest --force \
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
    && apk del .perl-build-deps \
    && rm -rf /root/.cpanm /tmp/* /var/cache/apk/*

# Environment setup for root user
ENV HOME="/root"
ENV USER_HOME="/root"

# RDS-optimized memory settings - higher for cloud builds
ENV MEM_OPTS=""
ENV GRADLE_USER_HOME="$HOME/.gradle"
ENV GRADLE_OPTS="-Xmx8g -XX:+UseParallelGC -Dorg.gradle.daemon=false -Duser.home=$HOME -Dorg.gradle.parallel=true"

# RDS connection environment variables
ENV DB_HOST=""
ENV DB_PORT="5432"
ENV DB_USER="postgres"
ENV DB_PASSWORD=""
ENV DB_NAME="alliancemine_db"
ENV DB_PROFILE_NAME="alliancemine_profiles_db"

# Continue as root user
WORKDIR $HOME

# Create necessary directories
RUN mkdir -p .intermine .gradle logs data

# Build arguments for custom branches and Alliance release
ARG ALLIANCEMINE_BRANCH_NAME=master
ARG BIO_SOURCES_BRANCH_NAME=master
ARG ENVIRONMENT=stage
ARG SOLR_HOST=stage-intermine-solr.alliancegenome.org
ARG ALLIANCE_RELEASE=8.2.0

# Clone AllianceMine repository
RUN git clone https://github.com/alliance-genome/alliancemine.git && \
    cd alliancemine && \
    git checkout ${ALLIANCEMINE_BRANCH_NAME} && \
    git config pull.rebase false

# Clone alliancemine-bio-sources repository
RUN git clone https://github.com/alliance-genome/alliancemine-bio-sources.git && \
    cd alliancemine-bio-sources && \
    git checkout ${BIO_SOURCES_BRANCH_NAME} && \
    git config pull.rebase false

# Clone InterMine scripts repository for project_build script
RUN git clone https://github.com/intermine/intermine-scripts.git && \
    cp intermine-scripts/project_build alliancemine/ && \
    chmod +x alliancemine/project_build && \
    rm -rf intermine-scripts

# Set Alliance release version environment variable for AllianceMine
ENV ALLIANCE_RELEASE_VERSION=${ALLIANCE_RELEASE}

# Create template properties file (will be configured at runtime)
WORKDIR $HOME/alliancemine
RUN cp alliancemine.properties alliancemine.properties.template

# Build and install bio-sources (this is the slow part, keep as separate layer)
WORKDIR $HOME/alliancemine-bio-sources
RUN ./gradlew clean install --stacktrace && \
    # Clean up Gradle caches to reduce image size
    rm -rf $HOME/.gradle/caches/transforms-* \
           $HOME/.gradle/caches/journal-* \
           /tmp/*

# Build and install alliancemine dependencies
WORKDIR $HOME/alliancemine
RUN ./gradlew install --stacktrace && \
    # Clean up Gradle caches to reduce image size
    rm -rf $HOME/.gradle/caches/transforms-* \
           $HOME/.gradle/caches/journal-* \
           /tmp/*

# Make sure build scripts are executable
RUN chmod +x ./load_db_build_solr && \
    chmod +x ./project_build

# Copy RDS-specific scripts and configurations
COPY rds-entrypoint.sh /rds-entrypoint.sh
COPY configure-rds.sh /configure-rds.sh
COPY wait-for-rds.sh /wait-for-rds.sh
COPY rds-healthcheck.sh /rds-healthcheck.sh

RUN chmod +x /rds-entrypoint.sh && \
    chmod +x /configure-rds.sh && \
    chmod +x /wait-for-rds.sh && \
    chmod +x /rds-healthcheck.sh

# Health check to verify RDS connectivity and Java
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD /rds-healthcheck.sh

# Default working directory
WORKDIR $HOME/alliancemine

# Set entrypoint to handle RDS configuration
ENTRYPOINT ["/rds-entrypoint.sh"]

# Use array form for better signal handling
CMD ["/bin/bash"]

# Labels for ephemeral build tracking
LABEL build.type="ephemeral-rds"
LABEL build.optimized="true"