FROM alpine:3.20
LABEL maintainer="Alliance of Genome Resources"
LABEL description="AllianceMine build-only container with RDS support"

# ============================================
# Base System Setup
# ============================================
ENV JAVA_HOME="/usr/lib/jvm/default-jvm"
ENV PATH="$JAVA_HOME/bin:$PATH"
ENV HOME="/root"

# Install system dependencies
RUN apk add --no-cache \
    openjdk8 \
    openjdk8-jre \
    git \
    bash \
    postgresql-client \
    wget \
    curl \
    ca-certificates \
    python3 \
    py3-pip \
    build-base \
    perl \
    perl-dev \
    perl-app-cpanminus \
    gettext \
    && ln -sf "${JAVA_HOME}/bin/"* "/usr/bin/"

# Install Perl modules required by InterMine project_build
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
    XML::Parser::PerlSAX \
    Text::Glob \
    Log::Handler \
    Getopt::Std \
    Digest::MD5 \
    && rm -rf /root/.cpanm /tmp/*

# ============================================
# InterMine Build Environment
# ============================================
ENV MEM_OPTS="-Xmx16g -Xms8g"
ENV GRADLE_OPTS="-server ${MEM_OPTS} -XX:+UseParallelGC -XX:SoftRefLRUPolicyMSPerMB=1 -XX:+HeapDumpOnOutOfMemoryError -Dorg.gradle.daemon=false -Duser.home=/root"
ENV GRADLE_USER_HOME="/root/.gradle"

WORKDIR /root
RUN mkdir -p .intermine

# ============================================
# Clone AllianceMine Repositories
# ============================================
ARG ALLIANCEMINE_BRANCH=master
RUN git clone --depth 1 --branch ${ALLIANCEMINE_BRANCH} \
    https://github.com/alliance-genome/alliancemine.git

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
# Build AllianceMine Dependencies
# ============================================
WORKDIR /root/alliancemine

# Copy properties templates
COPY properties/alliancemine.properties.template /root/.intermine/alliancemine.properties.template
COPY properties/alliancemine.properties.template /root/.intermine/alliancemine.properties

RUN echo "Installing AllianceMine Gradle dependencies..." && \
    ./gradlew install --stacktrace && \
    rm -rf /root/.gradle/caches/transforms-* \
           /root/.gradle/caches/journal-* \
           /tmp/*

# ============================================
# Install project_build from intermine-scripts
# ============================================
RUN git clone --depth 1 https://github.com/intermine/intermine-scripts.git /root/intermine-scripts && \
    cp /root/intermine-scripts/project_build /root/alliancemine/project_build && \
    chmod +x /root/alliancemine/project_build && \
    rm -rf /root/intermine-scripts

# ============================================
# Add Build Scripts and Configuration
# ============================================
COPY scripts/ /root/scripts/
RUN chmod +x /root/scripts/*.py

COPY entrypoint.sh /root/entrypoint.sh
RUN chmod +x /root/entrypoint.sh

# Create data directories
RUN mkdir -p /root/data/{genes,alleles,disease,phenotype,orthology,expression,variants,go,dump}

# ============================================
# Final Setup
# ============================================
WORKDIR /root/alliancemine

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD java -version || exit 1

ENTRYPOINT ["/root/entrypoint.sh"]
CMD ["bash"]
