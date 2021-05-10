FROM alpine:latest
LABEL maintainer="Ank"

ENV JAVA_HOME="/usr/lib/jvm/default-jvm"

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
                #   PerlIO::gzip \
                  Perl6::Junction \
                #   List::MoreUtils \
                  Module::Find \
                #   Moose \
                #   MooseX::Role::WithOverloading \
                  MooseX::Types \
                  MooseX::FollowPBP \
                  MooseX::ABC \
                  MooseX::FileAttribute \
                #   Text::CSV_XS \
                  Text::Glob \
                  XML::Parser::PerlSAX \
                  XML::DOM
                #  Getopt::Std \
                #  Digest::MD5 \
                #  Log::Handler

# RUN mkdir /home/intermine && mkdir /home/intermine/intermine
# RUN chmod -R 777 /home/intermine

ENV MEM_OPTS="-Xmx32g -Xms2g"
ENV GRADLE_OPTS="-server ${MEM_OPTS} -XX:+UseParallelGC -XX:SoftRefLRUPolicyMSPerMB=1  -XX:+HeapDumpOnOutOfMemoryError -XX:MaxHeapFreeRatio=99 -Dorg.gradle.daemon=false -Duser.home=/root"
ENV HOME="/root"
ENV USER_HOME="/root"
ENV GRADLE_USER_HOME="/root/.gradle"
ENV INTERMINE_PGUSER="postgres"
ENV INTERMINE_PGPASSWORD="postgres"
ENV TOMCAT_USER="tomcat"
ENV TOMCAT_PWD="tomcat"
ENV TOMCAT_PORT=8080
ENV INTERMINE_PGPORT=5432

COPY ./build.sh /root
RUN chmod a+rx /root/build.sh
WORKDIR /root
CMD ["/bin/sh","/root/build.sh"]
