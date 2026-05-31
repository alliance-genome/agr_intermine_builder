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
# FlyMine source — COPYed from staged build context
# We do NOT clone upstream intermine/flymine. The operator's local fork at
# new_flymine/{flymine, flymine-bio-sources} carries EBI Maven URL + GO
# enrichment fixes plus the full-no-fluff project.xml edits that exist
# nowhere else.
#
# scripts/build_and_push.sh stages those dirs into source/ here, then
# `docker build` COPYs them into the image. The image is then pushed to ECR
# and pulled on AllianceMineDev — no rsync coordination needed on that side.
#
# When alliance-genome/flymine fork is published, switch this back to a
# RUN git clone + ARG <pin-sha> pattern.
# See docs/FLYMINE_DOCKER_HANDOFF_REPLIES_2026_05_30.md Q2.
# ============================================
COPY source/flymine /root/flymine
COPY source/flymine-bio-sources /root/flymine-bio-sources

# ============================================
# Install project_build from intermine-scripts
# Mirrors the AllianceMine pattern (upstream over FlyMine's in-repo variant).
# ============================================
RUN git clone --depth 1 https://github.com/intermine/intermine-scripts.git /opt/intermine-scripts && \
    cp /opt/intermine-scripts/project_build /root/flymine/project_build && \
    chmod +x /root/flymine/project_build && \
    rm -rf /opt/intermine-scripts

# ============================================
# Bake in the runtime patches that would otherwise be applied at first run.
# Now that source is in-image, we can do them at build time:
#   1. Strip JCenter bintray classpaths from bio-sources build.gradle
#      (upstream dead since 2021; fixes the install failure that bit yeastmine)
#   2. Append -Xmx48g to flymine/gradle.properties (no default heap upstream)
# ============================================
RUN BS=/root/flymine-bio-sources/build.gradle && \
    if grep -q 'jfrog.bintray' "$BS"; then \
        sed -i '/com\.jfrog\.bintray\.gradle:gradle-bintray-plugin/d' "$BS" && \
        sed -i '/org\.jfrog\.buildinfo:build-info-extractor-gradle/d' "$BS" && \
        sed -i "/apply plugin: 'com\.jfrog\.bintray'/d" "$BS"; \
    fi && \
    GP=/root/flymine/gradle.properties && \
    if [ -f "$GP" ] && ! grep -q 'org.gradle.jvmargs.*-Xmx48g' "$GP"; then \
        echo '' >> "$GP" && \
        echo 'org.gradle.jvmargs=-Xmx48g -XX:+HeapDumpOnOutOfMemoryError' >> "$GP"; \
    fi

# ============================================
# Add Properties and Configuration
# ============================================
COPY properties/flymine.properties.template /root/.intermine/flymine.properties.template
COPY properties/flymine.properties.template /root/.intermine/flymine.properties

COPY entrypoint.sh /root/entrypoint.sh
RUN chmod +x /root/entrypoint.sh

COPY scripts/extract_data.py /root/scripts/extract_data.py
RUN chmod +x /root/scripts/extract_data.py

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
