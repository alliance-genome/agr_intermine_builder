FROM alpine:3.20
LABEL maintainer="Alliance of Genome Resources"
LABEL description="YeastMine build-only container with RDS support"

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
    perl-xml-parser \
    expat-dev \
    gettext \
    aws-cli \
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
# GRADLE_OPTS is overridden at runtime by docker-compose.yml
ENV GRADLE_OPTS="-server -Xmx4g -Xms2g -XX:+UseParallelGC -Dorg.gradle.daemon=false -Duser.home=/root"
ENV GRADLE_USER_HOME="/root/.gradle"

WORKDIR /root
RUN mkdir -p .intermine

# ============================================
# Clone YeastMine Repositories
# Source: SGD's fork of YeastMine. The intermine/yeastmine path on GitHub is
# 404; the canonical maintained repos live under yeastgenome/.
# Repos are cloned at build time but compiled at runtime (first run) to keep
# image build lightweight.
# ============================================
ARG YEASTMINE_BRANCH=master
RUN git clone --depth 1 --branch ${YEASTMINE_BRANCH} \
    https://github.com/yeastgenome/yeastmine.git

ARG YEASTMINE_BIO_SOURCES_BRANCH=master
RUN git clone --depth 1 --branch ${YEASTMINE_BIO_SOURCES_BRANCH} \
    https://github.com/yeastgenome/yeastmine-bio-sources.git

# ============================================
# Install project_build from intermine-scripts
# Mirrors the AllianceMine / WormMine pattern.
# ============================================
RUN git clone --depth 1 https://github.com/intermine/intermine-scripts.git /root/intermine-scripts && \
    cp /root/intermine-scripts/project_build /root/yeastmine/project_build && \
    chmod +x /root/yeastmine/project_build && \
    rm -rf /root/intermine-scripts

# ============================================
# Add Properties and Configuration
# ============================================
COPY properties/yeastmine.properties.template /root/.intermine/yeastmine.properties.template
COPY properties/yeastmine.properties.template /root/.intermine/yeastmine.properties

COPY entrypoint.sh /root/entrypoint.sh
RUN chmod +x /root/entrypoint.sh

# Append a JVM heap setting to YeastMine's gradle.properties so the build
# doesn't OOM on real-sized SGD data with the default ~1G heap.
RUN echo '' >> /root/yeastmine/gradle.properties && \
    echo 'org.gradle.jvmargs=-Xmx48g -XX:+HeapDumpOnOutOfMemoryError' >> /root/yeastmine/gradle.properties

# Create data directories
# /root/data/dump for project_build checkpoints
# /root/data/sgd for SGD-distributed downloads (chromosomal_feature.tab,
# intron.tab, OBO ontologies, etc.) once a data fetcher is decided
RUN mkdir -p /root/data/dump /root/data/sgd

# Marker file: entrypoint checks this to know if compilation is needed
RUN touch /root/.needs_compile

# ============================================
# Final Setup
# ============================================
WORKDIR /root/yeastmine

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD java -version || exit 1

ENTRYPOINT ["/root/entrypoint.sh"]
CMD ["bash"]
