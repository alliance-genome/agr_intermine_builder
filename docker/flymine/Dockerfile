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

# Fake ssh wrapper for project_build's checkpoint createdb step.
# project_build wraps every checkpoint copy in `ssh <dump_host> createdb ...`,
# expecting a unix host it can shell into; RDS doesn't accept SSH. The wrapper
# drops the host arg and execs the command locally so the createdb/psql calls
# run inside the container against RDS using the container's pg client + .pgpass.
RUN printf '#!/bin/sh\nshift\nexec "$@"\n' > /usr/local/bin/ssh && \
    chmod +x /usr/local/bin/ssh

# ============================================
# Bake in the runtime patches that would otherwise be applied at first run.
# Now that source is in-image, we can do them at build time:
#   1. Strip JCenter bintray classpaths from bio-sources build.gradle
#      (upstream dead since 2021; fixes the install failure that bit yeastmine)
#   2. Append -Xmx48g to flymine/gradle.properties (no default heap upstream)
#   3. Comment out the hardcoded localhost solrurl in dbmodel/resources/
#      so that flymine.properties (set by entrypoint envsubst) wins. Without
#      this the post-process create-search-index task connects to localhost:8983
#      and fails even when flymine.properties is correct (the dbmodel resources
#      take precedence in the property merge for postprocess gradle tasks).
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
    fi && \
    KS=/root/flymine/dbmodel/resources/keyword_search.properties && \
    OS=/root/flymine/dbmodel/resources/objectstoresummary.config.properties && \
    sed -i 's|^index.solrurl = http://localhost:8983|index.solrurl = http://172.31.59.87:8983|' "$KS" && \
    sed -i 's|^autocomplete.solrurl = http://localhost:8983|autocomplete.solrurl = http://172.31.59.87:8983|' "$OS" && \
    : "--- drop pathway refs: Gene.pathways field is provided by kegg-pathway/reactome which are not loaded in the slim FlyBase-only project.xml; leaving them in causes create-search-index postprocess to throw PathException ---" && \
    sed -i 's|^index.references.Gene = pathways goAnnotation.ontologyTerm|index.references.Gene = goAnnotation.ontologyTerm|' "$KS" && \
    sed -i 's|^index.facet.multi.Pathway = pathways.name|#index.facet.multi.Pathway = pathways.name|' "$KS" && \
    : "--- drop autocomplete entries for classes absent from slim FlyBase-only model (Disease/Pathway/MRNAExpressionTerm); AutoCompleter trips on Class.forName misses and aborts the whole task ---" && \
    sed -i 's|^org.intermine.model.bio.Disease.autocomplete|#org.intermine.model.bio.Disease.autocomplete|' "$OS" && \
    sed -i 's|^org.intermine.model.bio.Pathway.autocomplete|#org.intermine.model.bio.Pathway.autocomplete|' "$OS" && \
    sed -i 's|^org.intermine.model.bio.MRNAExpressionTerm.autocomplete|#org.intermine.model.bio.MRNAExpressionTerm.autocomplete|' "$OS" && \
    : "--- skip Sequence summary: residues is a Clob and ObjectStoreSummary chokes on ClobAccess, killing the summariseObjectStore task that bakes objectstoresummary.properties into the WAR; without that file the webapp prints 'cannot find class count' for every class on begin.do ---" && \
    grep -q '^noSummary' "$OS" || echo 'noSummary = Sequence' >> "$OS"

# ============================================
# Strip widgets from webconfig-model.xml that reference classes absent from
# the slim FlyBase-only model. Without this the webapp boots but begin.do
# floods the page with "The path X for the widget Y is not in the model"
# errors. Each widget is a single self-closing XML element matched by id;
# `awk` deletes from the line with the matching id to the next `/>`.
# Widgets removed:
#   - flyatlas_for_gene / flyatlas_for_probeset  (FlyAtlasResult, ProbeSet)
#   - flyfish / bdgp / bdgp_enrichment           (MRNAExpressionResult, MRNAExpressionTerm)
#   - miranda_enrichment                          (miRNAinteractions)
#   - pathway_enrichment                          (pathways)
#   - prot_dom_enrichment_for_gene / _for_protein (proteinDomainRegions)
# ============================================
RUN WC=/root/flymine/webapp/src/main/webapp/WEB-INF/webconfig-model.xml && \
    for id in flyatlas_for_gene flyatlas_for_probeset flyfish bdgp miranda_enrichment pathway_enrichment prot_dom_enrichment_for_gene prot_dom_enrichment_for_protein bdgp_enrichment; do \
        awk -v id="$id" 'BEGIN{drop=0} \
            $0 ~ "id=\"" id "\"" && /<(graphdisplayer|enrichmentwidgetdisplayer)/ {drop=1} \
            !drop {print} \
            drop && /\/>/ {drop=0; next}' "$WC" > "$WC.tmp" && mv "$WC.tmp" "$WC"; \
    done

# ============================================
# Add Properties and Configuration
# ============================================
COPY properties/flymine.properties.template /root/.intermine/flymine.properties.template
COPY properties/flymine.properties.template /root/.intermine/flymine.properties

COPY entrypoint.sh /root/entrypoint.sh
RUN chmod +x /root/entrypoint.sh

COPY scripts/extract_data.py /root/scripts/extract_data.py
RUN chmod +x /root/scripts/extract_data.py

# Post-build SQL patches + finalize wrapper.
# Run after :dbmodel:postprocess so the WAR's objectstoresummary.properties
# and the deployed UI both reflect the patched DB. See scripts/finalize_build.sh.
COPY scripts/patch_chromosome_names.sql /root/scripts/patch_chromosome_names.sql
COPY scripts/patch_attribute_fallbacks.sql /root/scripts/patch_attribute_fallbacks.sql
COPY scripts/finalize_build.sh /root/scripts/finalize_build.sh
RUN chmod +x /root/scripts/finalize_build.sh && \
    ln -sf /root/scripts/finalize_build.sh /usr/local/bin/finalize_build

# Create data directories
# A future session will own data layout; for image build we just need /root/data/dump
# for project_build's checkpoint area.
RUN mkdir -p /root/data/dump

# ============================================
# Compile bio-sources + flymine + webapp WAR at IMAGE BUILD TIME so that
# runtime container starts are instant. The runtime entrypoint's
# compile_if_needed() is a no-op once /root/.needs_compile is absent.
#
# webapp gradle config reads webapp.port as an integer, so we substitute a
# placeholder properties file (port=8080, manager creds harmless) just for
# the build. The entrypoint overwrites /root/.intermine/flymine.properties
# at runtime via envsubst before any gradle task runs.
#
# RDS-related properties stay as ${RDS_HOST} placeholders during the build
# — gradle install / war do not connect to the DB.
# ============================================
RUN cat > /root/.intermine/flymine.properties <<'EOF'
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
db.flybase.datasource.class=org.postgresql.ds.PGPoolingDataSource
db.flybase.datasource.dataSourceName=db.flybase
db.flybase.datasource.serverName=BUILD_PLACEHOLDER
db.flybase.datasource.databaseName=BUILD_PLACEHOLDER
db.flybase.datasource.user=BUILD_PLACEHOLDER
db.flybase.datasource.password=BUILD_PLACEHOLDER
db.flybase.datasource.portNumber=5432
db.flybase.driver=org.postgresql.Driver
db.flybase.platform=PostgreSQL
project.title=FlyMine
project.subTitle=An integrated database for Drosophila genomics
project.releaseVersion=build-placeholder
project.sitePrefix=http://localhost:8080
webapp.deploy.url=http://localhost:8080
webapp.baseurl=http://localhost:8080
webapp.path=flymine
webapp.manager=manager
webapp.password=manager
webapp.port=8080
webapp.hostname=localhost
tomcat.user=manager
tomcat.pwd=manager
bluegenes.toolLocation=/root/bluegenes-tools/node_modules
superuser.account=superuser@mail_account
superuser.initialPassword=secret
batch.size=1000
webapp.os.alias=os.production
webapp.query.cache.size=10000
webapp.query.cache.timeout=300
EOF
RUN cd /root/flymine-bio-sources && ./gradlew clean install --stacktrace --no-daemon \
    && cd /root/flymine && ./gradlew install --stacktrace --no-daemon \
    && rm -rf /root/.gradle/caches/transforms-* /root/.gradle/caches/journal-* /tmp/* 2>/dev/null || true

# ============================================
# Final Setup
# ============================================
WORKDIR /root/flymine

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD java -version || exit 1

ENTRYPOINT ["/root/entrypoint.sh"]
CMD ["bash"]
