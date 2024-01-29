FROM alpine:3.13 

LABEL maintainer="Alliance"

ENV JAVA_HOME="/usr/lib/jvm/default-jvm"

RUN apk add --no-cache openjdk8 openjdk8-jre && ln -sf "${JAVA_HOME}/bin/"* "/usr/bin/"
RUN apk add --no-cache git maven bash postgresql-client aws-cli wget build-base

ENV MEM_OPTS="-Xmx32g -Xms2g"
ENV HOME="/root"
ENV USER_HOME="/root"
ENV GRADLE_OPTS="-server ${MEM_OPTS} -XX:+UseParallelGC -XX:SoftRefLRUPolicyMSPerMB=1  -XX:+HeapDumpOnOutOfMemoryError -XX:MaxHeapFreeRatio=99 -Dorg.gradle.daemon=false -Duser.home=/root"
ENV GRADLE_USER_HOME="/root/.gradle"

WORKDIR /root

RUN mkdir .intermine
RUN git clone https://github.com/alliance-genome/alliancemine
RUN git clone https://github.com/alliance-genome/alliancemine-bio-sources

RUN (cd alliancemine-bio-sources/ && ./gradlew clean --stacktrace && ./gradlew install --parallel --stacktrace)

RUN echo "postgres:5432:*:postgres:postgres" >> /root/.pgpass

WORKDIR /root/alliancemine

#COPY ./alliancemine.${ENVIRONMENT}.properties /root/alliancemine/alliancemine.properties
#COPY ./alliancemine.${ENVIRONMENT}.properties /root/.intermine/alliancemine.properties
#RUN echo "index.solrurl = https://${ENVIRONMENT}-intermine-solr.alliancegenome.org/solr/alliancemine-search" >> dbmodel/resources/keyword_search.properties
#RUN echo "autocomplete.solrurl = https://${ENVIRONMENT}-intermine-solr.alliancegenome.org/solr/alliancemine-autocomplete" >> dbmodel/resources/objectstoresummary.config.properties
