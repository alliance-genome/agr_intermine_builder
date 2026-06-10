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
# YeastMine source — COPYed from staged build context (Approach A).
# We do NOT clone upstream. The operator's local fork at
# source/{yeastmine, yeastmine-bio-sources} carries the project.xml path
# rewrites (/data/intermine -> /root/data/intermine) and the dropped
# create-search-index postprocess. scripts/build_and_push.sh rsyncs the
# fork into source/ before `docker build`.
# ============================================
COPY source/yeastmine /root/yeastmine
COPY source/yeastmine-bio-sources /root/yeastmine-bio-sources

# ============================================
# Install project_build from intermine-scripts (upstream variant).
# ============================================
RUN git clone --depth 1 https://github.com/intermine/intermine-scripts.git /opt/intermine-scripts && \
    cp /opt/intermine-scripts/project_build /root/yeastmine/project_build && \
    chmod +x /root/yeastmine/project_build && \
    rm -rf /opt/intermine-scripts

# Fake ssh wrapper for project_build's checkpoint createdb step (RDS rejects
# real SSH). Drops the host arg and execs the command locally.
RUN printf '#!/bin/sh\nshift\nexec "$@"\n' > /usr/local/bin/ssh && \
    chmod +x /usr/local/bin/ssh

# ============================================
# Bake in runtime patches at build time:
#   1. Strip dead JCenter/bintray classpaths from bio-sources build.gradle
#   2. Append -Xmx48g to yeastmine/gradle.properties (no default heap upstream)
#   3. Point dbmodel keyword_search/objectstoresummary solrurl at multitenant
#      (only matters once create-search-index is re-enabled at deploy time).
# ============================================
RUN BS=/root/yeastmine-bio-sources/build.gradle && \
    if [ -f "$BS" ] && grep -q 'jfrog.bintray' "$BS"; then \
        sed -i '/com\.jfrog\.bintray\.gradle:gradle-bintray-plugin/d' "$BS" && \
        sed -i '/org\.jfrog\.buildinfo:build-info-extractor-gradle/d' "$BS" && \
        sed -i "/apply plugin: 'com\.jfrog\.bintray'/d" "$BS"; \
    fi && \
    GP=/root/yeastmine/gradle.properties && \
    if [ -f "$GP" ] && ! grep -q 'org.gradle.jvmargs.*-Xmx48g' "$GP"; then \
        echo '' >> "$GP" && \
        echo 'org.gradle.jvmargs=-Xmx48g -XX:+HeapDumpOnOutOfMemoryError' >> "$GP"; \
    fi && \
    KS=/root/yeastmine/dbmodel/resources/keyword_search.properties && \
    OS=/root/yeastmine/dbmodel/resources/objectstoresummary.config.properties && \
    [ -f "$KS" ] && sed -i 's|http://localhost:8983|http://172.31.59.87:8983|g' "$KS" || true && \
    [ -f "$OS" ] && sed -i 's|http://localhost:8983|http://172.31.59.87:8983|g' "$OS" || true

# ============================================
# Properties + entrypoint + scripts
# ============================================
COPY properties/yeastmine.properties.template /root/.intermine/yeastmine.properties.template
COPY entrypoint.sh /root/entrypoint.sh
RUN chmod +x /root/entrypoint.sh

COPY scripts/extract_data.py /root/scripts/extract_data.py
COPY scripts/finalize_build.sh /root/scripts/finalize_build.sh
RUN chmod +x /root/scripts/extract_data.py /root/scripts/finalize_build.sh && \
    ln -sf /root/scripts/finalize_build.sh /usr/local/bin/finalize_build

RUN mkdir -p /root/data/dump /root/data/intermine

# ============================================
# Build-placeholder properties so webapp gradle config (which reads
# webapp.port as an int) succeeds at image-build time. The entrypoint
# overwrites /root/.intermine/yeastmine.properties via envsubst at runtime.
# ============================================
RUN cat > /root/.intermine/yeastmine.properties <<'EOF'
db.production.datasource.class=com.zaxxer.hikari.HikariDataSource
db.production.datasource.serverName=BUILD_PLACEHOLDER
db.production.datasource.databaseName=BUILD_PLACEHOLDER
db.production.datasource.user=BUILD_PLACEHOLDER
db.production.datasource.password=BUILD_PLACEHOLDER
db.production.driver=org.postgresql.Driver
db.production.platform=PostgreSQL
db.common-tgt-items.datasource.class=com.zaxxer.hikari.HikariDataSource
db.common-tgt-items.datasource.serverName=BUILD_PLACEHOLDER
db.common-tgt-items.datasource.databaseName=BUILD_PLACEHOLDER
db.common-tgt-items.datasource.user=BUILD_PLACEHOLDER
db.common-tgt-items.datasource.password=BUILD_PLACEHOLDER
db.common-tgt-items.driver=org.postgresql.Driver
db.common-tgt-items.platform=PostgreSQL
db.userprofile-production.datasource.class=com.zaxxer.hikari.HikariDataSource
db.userprofile-production.datasource.serverName=BUILD_PLACEHOLDER
db.userprofile-production.datasource.databaseName=BUILD_PLACEHOLDER
db.userprofile-production.datasource.user=BUILD_PLACEHOLDER
db.userprofile-production.datasource.password=BUILD_PLACEHOLDER
db.userprofile-production.driver=org.postgresql.Driver
db.userprofile-production.platform=PostgreSQL
db.sgd.datasource.class=org.postgresql.ds.PGPoolingDataSource
db.sgd.datasource.dataSourceName=db.sgd
db.sgd.datasource.serverName=BUILD_PLACEHOLDER
db.sgd.datasource.databaseName=BUILD_PLACEHOLDER
db.sgd.datasource.user=BUILD_PLACEHOLDER
db.sgd.datasource.password=BUILD_PLACEHOLDER
db.sgd.datasource.portNumber=5432
db.sgd.driver=org.postgresql.Driver
db.sgd.platform=PostgreSQL
project.title=YeastMine
project.subTitle=An integrated database of Saccharomyces cerevisiae genomics
project.releaseVersion=build-placeholder
project.sitePrefix=http://localhost:8080
webapp.deploy.url=http://localhost:8080
webapp.baseurl=http://localhost:8080
webapp.path=yeastmine
webapp.manager=manager
webapp.password=manager
webapp.port=8080
webapp.hostname=localhost
tomcat.user=manager
tomcat.pwd=manager
superuser.account=superuser@mail_account
superuser.initialPassword=secret
batch.size=1000
webapp.os.alias=os.production
webapp.query.cache.size=10000
webapp.query.cache.timeout=300
EOF

# ============================================
# Compile bio-sources + yeastmine at IMAGE BUILD TIME (webapp classes compile
# during install; the WAR itself is built later by finalize_build.sh).
# Runtime entrypoint compile is then a no-op (no /root/.needs_compile).
# ============================================
RUN cd /root/yeastmine-bio-sources && ./gradlew clean install --stacktrace --no-daemon && \
    cd /root/yeastmine && ./gradlew install --stacktrace --no-daemon && \
    rm -rf /root/.gradle/caches/transforms-* /root/.gradle/caches/journal-* /tmp/* 2>/dev/null || true

# ============================================
# Final Setup
# ============================================
WORKDIR /root/yeastmine

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD java -version || exit 1

ENTRYPOINT ["/root/entrypoint.sh"]
CMD ["bash"]
