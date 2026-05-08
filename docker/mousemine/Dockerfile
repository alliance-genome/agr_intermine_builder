FROM alpine:3.20
LABEL maintainer="Alliance of Genome Resources"
LABEL description="MouseMine build-only container with RDS support"

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
# Clone MouseMine Repositories
# Repos are cloned at build time but compiled at runtime (first run)
# to keep image build lightweight.
# ============================================
ARG MOUSEMINE_BRANCH=master
RUN git clone --depth 1 --branch ${MOUSEMINE_BRANCH} \
    https://github.com/intermine/mousemine.git

ARG MOUSEMINE_BIO_SOURCES_BRANCH=master
RUN git clone --depth 1 --branch ${MOUSEMINE_BIO_SOURCES_BRANCH} \
    https://github.com/intermine/mousemine-bio-sources.git

# ============================================
# Install project_build from intermine-scripts
# Mirrors the AllianceMine pattern (consistency over MouseMine's in-repo variant).
# ============================================
RUN git clone --depth 1 https://github.com/intermine/intermine-scripts.git /root/intermine-scripts && \
    cp /root/intermine-scripts/project_build /root/mousemine/project_build && \
    chmod +x /root/mousemine/project_build && \
    rm -rf /root/intermine-scripts

# ============================================
# Add Properties and Configuration
# ============================================
COPY properties/mousemine.properties.template /root/.intermine/mousemine.properties.template
COPY properties/mousemine.properties.template /root/.intermine/mousemine.properties

# Append a JVM heap setting to MouseMine's gradle.properties.
# MouseMine's upstream gradle.properties does NOT set org.gradle.jvmargs, so
# we APPEND (not sed-replace as in AllianceMine where the line exists). Without
# this the build OOMs on real-sized data with the default ~1g heap.
RUN echo '' >> /root/mousemine/gradle.properties && \
    echo 'org.gradle.jvmargs=-Xmx48g -XX:+HeapDumpOnOutOfMemoryError' >> /root/mousemine/gradle.properties

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
WORKDIR /root/mousemine

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD java -version || exit 1

ENTRYPOINT ["/root/entrypoint.sh"]
CMD ["bash"]
