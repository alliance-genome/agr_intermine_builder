FROM alpine:3.13 
# Needs to be 3.13 because latest causes an error. Once docker is upgraded
# we should switch back to latest: https://gitlab-test.alpinelinux.org/alpine/aports/-/issues/12396
LABEL maintainer="Ank"

ENV JAVA_HOME="/usr/lib/jvm/default-jvm"

ARG ENVIRONMENT="stage"

RUN apk add --no-cache openjdk8 openjdk8-jre && \
    ln -sf "${JAVA_HOME}/bin/"* "/usr/bin/"

RUN apk add --no-cache git \
                       maven \
                       bash \
                       postgresql-client \
                       perl \
                       perl-utils

RUN apk add --no-cache build-base
RUN apk add --no-cache -X http://dl-cdn.alpinelinux.org/alpine/edge/testing perl-moosex
RUN apk add --no-cache wget \
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

RUN perl -MCPAN -e \
'my $c = "CPAN::HandleConfig"; $c->load(doit => 1, autoconfig => 1); $c->edit(prerequisites_policy => "follow"); $c->edit(build_requires_install_policy => "yes"); $c->commit'

RUN cpan -i App::cpanminus

RUN cpanm --force Ouch \
                  LWP \
                  URI \
                  Module::Find \
                  Web::Scraper \
                  Number::Format \
                  Perl6::Junction \
                  Module::Find \
                  MooseX::Types \
                  MooseX::FollowPBP \
                  MooseX::ABC \
                  MooseX::FileAttribute \
                  Text::Glob \
                  XML::Parser::PerlSAX \
                  XML::DOM

# RUN mkdir /home/intermine && mkdir /home/intermine/intermine
# RUN chmod -R 777 /home/intermine

ENV MEM_OPTS="-Xmx32g -Xms2g"
ENV HOME="/root"
ENV USER_HOME="/root"
ENV GRADLE_OPTS="-server ${MEM_OPTS} -XX:+UseParallelGC -XX:SoftRefLRUPolicyMSPerMB=1  -XX:+HeapDumpOnOutOfMemoryError -XX:MaxHeapFreeRatio=99 -Dorg.gradle.daemon=false -Duser.home=/root"
ENV GRADLE_USER_HOME="/root/.gradle"

WORKDIR /root

RUN git clone https://github.com/intermine/intermine-scripts
RUN git clone https://github.com/intermine/intermine intermine --single-branch --branch master --depth=1
RUN git clone https://github.com/alliance-genome/alliancemine
RUN git clone https://github.com/alliance-genome/alliancemine-bio-sources

RUN mkdir .intermine

RUN echo "index.solrurl = https://${ENVIRONMENT}-intermine-solr.alliancegenome.org/solr/alliancemine-search" >> alliancemine/dbmodel/resources/keyword_search.properties
RUN echo "autocomplete.solrurl = https://${ENVIRONMENT}-intermine-solr.alliancegenome.org/solr/alliancemine-autocomplete" >> alliancemine/dbmodel/resources/objectstoresummary.config.properties

RUN (cd intermine/intermine && ./gradlew clean && ./gradlew install)
RUN (cd intermine/bio && ./gradlew clean && ./gradlew install --parallel)
RUN (cd intermine/bio/sources && ./gradlew clean && ./gradlew install --parallel)
RUN (cd intermine/bio/postprocess/ && ./gradlew clean && ./gradlew install --parallel)
RUN (cd alliancemine-bio-sources/ && ./gradlew clean --stacktrace && ./gradlew install --parallel --stacktrace)

RUN cp /root/intermine-scripts/project_build /root/alliancemine/project_build
RUN chmod +x /root/alliancemine/project_build

COPY ./alliancemine.${ENVIRONMENT}.properties /root/alliancemine/alliancemine.properties
COPY ./alliancemine.${ENVIRONMENT}.properties /root/.intermine/alliancemine.properties

WORKDIR /root/alliancemine
