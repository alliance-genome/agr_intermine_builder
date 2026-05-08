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
    py3-tqdm \
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
# GRADLE_OPTS is overridden at runtime by docker-compose.yml (-Xmx16g -Xms8g)
ENV GRADLE_OPTS="-server -Xmx4g -Xms2g -XX:+UseParallelGC -Dorg.gradle.daemon=false -Duser.home=/root"
ENV GRADLE_USER_HOME="/root/.gradle"

WORKDIR /root
RUN mkdir -p .intermine

# ============================================
# Clone AllianceMine Repositories
# Repos are cloned at build time but compiled at runtime (first run)
# to keep image build lightweight.
# ============================================
ARG ALLIANCEMINE_BRANCH=master
RUN git clone --depth 1 --branch ${ALLIANCEMINE_BRANCH} \
    https://github.com/alliance-genome/alliancemine.git

# Symlink the in-project alliancemine.properties to the InterMine-convention
# path. webapp/build.gradle reads /root/alliancemine/alliancemine.properties
# directly (line ~59), so we can't just delete it. Symlinking ensures the
# entrypoint-templated copy in /root/.intermine/ is the single source of
# truth — no stale upstream rc18 placeholder shadowing it.
RUN rm -f /root/alliancemine/alliancemine.properties && \
    ln -s /root/.intermine/alliancemine.properties /root/alliancemine/alliancemine.properties

# Fake ssh wrapper for project_build's checkpoint createdb step.
# project_build wraps every checkpoint copy in `ssh <dump_host> createdb ...`,
# but the dump_host is the RDS endpoint which doesn't accept SSH. The inner
# createdb already carries `-h <dump_host>` so dropping the host arg and
# exec'ing the rest locally hits RDS correctly via libpq.
RUN printf '#!/bin/sh\nshift\nexec "$@"\n' > /usr/local/bin/ssh && \
    chmod +x /usr/local/bin/ssh

ARG BIO_SOURCES_BRANCH=master
RUN git clone --depth 1 --branch ${BIO_SOURCES_BRANCH} \
    https://github.com/alliance-genome/alliancemine-bio-sources.git

# ============================================
# Install project_build from intermine-scripts
# ============================================
RUN git clone --depth 1 https://github.com/intermine/intermine-scripts.git /root/intermine-scripts && \
    cp /root/intermine-scripts/project_build /root/alliancemine/project_build && \
    chmod +x /root/alliancemine/project_build && \
    rm -rf /root/intermine-scripts

# ============================================
# Add Build Scripts, Properties, and Configuration
# ============================================
COPY properties/alliancemine.properties.template /root/.intermine/alliancemine.properties.template
COPY properties/alliancemine.properties.template /root/.intermine/alliancemine.properties

COPY scripts/ /root/scripts/
RUN chmod +x /root/scripts/*.py

# Override project.xml with dump checkpoints for restartable builds
COPY project.xml /root/alliancemine/project.xml

# Patch alliancemine gradle.properties: hardcoded -Xmx48g overrides GRADLE_OPTS
# Without this patch, the JVM starts with whatever the file says regardless of compose env.
# Upstream fix needed in: alliance-genome/alliancemine gradle.properties
RUN sed -i 's/org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx48g -XX:+HeapDumpOnOutOfMemoryError/' \
    /root/alliancemine/gradle.properties

# Patch SgdConverter: re-enable deduplication of child features
# The SQL query returns duplicate telomeric_repeat rows causing "Duplicate objects for pk" errors.
# Upstream fix needed in: alliance-genome/alliancemine-bio-sources sgd/src/.../SgdConverter.java
RUN SGDFILE=/root/alliancemine-bio-sources/sgd/src/main/java/org/intermine/bio/dataconversion/SgdConverter.java && \
    LINENUM=$(grep -n 'figure out why duplicates in the SQL' "$SGDFILE" | tail -1 | cut -d: -f1) && \
    sed -i "${LINENUM}d" "$SGDFILE" && \
    sed -i "${LINENUM}s|/\\*if|if|" "$SGDFILE" && \
    sed -i "$((LINENUM+4))s|}\\*/|}|" "$SGDFILE"

# Patch webconfig-model.xml: reorder Complex fieldconfig so systematicName comes
# right after function. Without this, the Complex list view default columns hide
# results until users manually add a column. Manually applied to prod 8082 on
# 2026-05; baking in here so future builds inherit. Upstream fix needed in:
# alliance-genome/alliancemine webapp/src/main/webapp/WEB-INF/webconfig-model.xml
RUN python3 - <<'PYEOF'
p = '/root/alliancemine/webapp/src/main/webapp/WEB-INF/webconfig-model.xml'
s = open(p).read()
old = '''            <fieldconfig fieldExpr="function" label="Complex Function" />
            <fieldconfig fieldExpr="properties" label="Complex Properties" />
            <fieldconfig fieldExpr="systematicName" label="Complex Systematic Name" />'''
new = '''            <fieldconfig fieldExpr="function" label="Complex Function" />

            <fieldconfig fieldExpr="systematicName" label="Complex Systematic Name" />
            <fieldconfig fieldExpr="properties" label="Complex Properties" />'''
assert old in s, 'webconfig Complex block not found - upstream may have changed'
open(p, 'w').write(s.replace(old, new))
PYEOF

COPY entrypoint.sh /root/entrypoint.sh
RUN chmod +x /root/entrypoint.sh

# Create data directories
RUN mkdir -p /root/data/{genes,alleles,disease,phenotype,orthology,expression,variants,go,dump}

# Marker file: entrypoint checks this to know if compilation is needed
RUN touch /root/.needs_compile

# ============================================
# Final Setup
# ============================================
WORKDIR /root/alliancemine

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD java -version || exit 1

ENTRYPOINT ["/root/entrypoint.sh"]
CMD ["bash"]
