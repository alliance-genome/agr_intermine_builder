FROM alpine:3.20
LABEL maintainer="Alliance of Genome Resources"
LABEL description="FlyMine build-only container with RDS support"

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
# GRADLE_OPTS is overridden at runtime by docker-compose.yml (-Xmx48g -Xms24g)
ENV GRADLE_OPTS="-server -Xmx4g -Xms2g -XX:+UseParallelGC -Dorg.gradle.daemon=false -Duser.home=/root"
ENV GRADLE_USER_HOME="/root/.gradle"

WORKDIR /root
RUN mkdir -p .intermine

# ============================================
# FlyMine source location
# We do NOT clone upstream intermine/flymine — the operator's local fork at
# new_flymine/{flymine, flymine-bio-sources} carries EBI Maven URL + GO
# enrichment fixes (and the in-progress full-no-fluff project.xml edits) that
# exist nowhere else.
#
# The source dirs are bind-mounted at runtime by docker-compose.yml:
#   host: ${FLYMINE_SRC_DIR}            -> container: /root/flymine
#   host: ${FLYMINE_BIO_SOURCES_SRC_DIR} -> container: /root/flymine-bio-sources
#
# When alliance-genome/flymine fork is published, switch this back to a clone
# + ARG <pin-sha> pattern. See docs/FLYMINE_DOCKER_HANDOFF_REPLIES_2026_05_30.md Q2.
# ============================================

# ============================================
# Install project_build from intermine-scripts
# Mirrors the AllianceMine pattern (consistency over FlyMine's in-repo variant).
# Drop the binary into /opt; entrypoint copies it into /root/flymine after
# the source mount is in place.
# ============================================
RUN git clone --depth 1 https://github.com/intermine/intermine-scripts.git /opt/intermine-scripts && \
    cp /opt/intermine-scripts/project_build /opt/project_build && \
    chmod +x /opt/project_build && \
    rm -rf /opt/intermine-scripts

# ============================================
# Add Properties and Configuration
# ============================================
COPY properties/flymine.properties.template /root/.intermine/flymine.properties.template
COPY properties/flymine.properties.template /root/.intermine/flymine.properties

COPY entrypoint.sh /root/entrypoint.sh
RUN chmod +x /root/entrypoint.sh

# Create data directories
# A future session will own data layout; for image build we just need /root/data/dump
# for project_build's checkpoint area.
RUN mkdir -p /root/data/dump

# Marker file: entrypoint checks this to know if compilation is needed
RUN touch /root/.needs_compile

# ============================================
# Final Setup
# ============================================
WORKDIR /root/flymine

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD java -version || exit 1

ENTRYPOINT ["/root/entrypoint.sh"]
CMD ["bash"]
