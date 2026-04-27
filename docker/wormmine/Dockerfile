FROM alpine:3.20
LABEL maintainer="Alliance of Genome Resources"
LABEL description="WormMine build-only container with RDS support"

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

# Install Perl modules required by InterMine project_build + WormMine extras
# (Bio::Perl, Log::Log4perl, HTTP::Date, Time::HiRes are WormMine-specific
# additions on top of the AllianceMine baseline.)
RUN cpanm --notest --force \
    Ouch \
    LWP \
    LWP::UserAgent \
    HTTP::Date \
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
    Log::Log4perl \
    Getopt::Std \
    Digest::MD5 \
    Time::HiRes \
    Bio::Perl \
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
# Clone WormMine Repositories
# Source: WormBase's fork of WormMine (NOT intermine/wormmine).
# Default branches im-298 / im-293 correspond to WormBase release WS298.
# Repos are cloned at build time but compiled at runtime (first run)
# to keep image build lightweight.
# ============================================
ARG WORMMINE_BRANCH=im-298
RUN git clone --depth 1 --branch ${WORMMINE_BRANCH} \
    https://github.com/WormBase/WormMine.git wormmine

ARG WORMMINE_BIO_SOURCES_BRANCH=im-293
RUN git clone --depth 1 --branch ${WORMMINE_BIO_SOURCES_BRANCH} \
    https://github.com/WormBase/wormmine-bio-sources.git

# ============================================
# Install project_build from intermine-scripts
# Mirrors the AllianceMine/FlyMine pattern.
# ============================================
RUN git clone --depth 1 https://github.com/intermine/intermine-scripts.git /root/intermine-scripts && \
    cp /root/intermine-scripts/project_build /root/wormmine/project_build && \
    chmod +x /root/wormmine/project_build && \
    rm -rf /root/intermine-scripts

# ============================================
# Add Properties, Scripts, and Configuration
# ============================================
COPY properties/wormmine.properties.template /root/.intermine/wormmine.properties.template
COPY properties/wormmine.properties.template /root/.intermine/wormmine.properties

COPY scripts/ /root/scripts/
RUN chmod +x /root/scripts/*.sh

COPY entrypoint.sh /root/entrypoint.sh
RUN chmod +x /root/entrypoint.sh

# Append a JVM heap setting to WormMine's gradle.properties so the build
# doesn't OOM on real-sized WormBase data with the default ~1G heap.
RUN echo '' >> /root/wormmine/gradle.properties && \
    echo 'org.gradle.jvmargs=-Xmx48g -XX:+HeapDumpOnOutOfMemoryError' >> /root/wormmine/gradle.properties

# Create data directories
# /root/data/dump for project_build checkpoints
# /root/data/wormbase for the acedb/species/ontology files the WormBase
# data fetcher (scripts/find_and_copy_wormbase_files.sh) populates
RUN mkdir -p /root/data/dump /root/data/wormbase

# Marker file: entrypoint checks this to know if compilation is needed
RUN touch /root/.needs_compile

# ============================================
# Final Setup
# ============================================
WORKDIR /root/wormmine

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD java -version || exit 1

ENTRYPOINT ["/root/entrypoint.sh"]
CMD ["bash"]
