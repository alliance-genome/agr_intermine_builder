FROM alpine:3.9
LABEL maintainer="Ank"

ARG TOMCAT_PASSWORD=tomcat
ENV TOMCAT_PASSWORD ${TOMCAT_PASSWORD}

ENV JAVA_HOME="/usr/lib/jvm/default-jvm"
ENV MEM_OPTS="-Xmx8g -Xms8g"
ENV GRADLE_OPTS="-server $MEM_OPTS -XX:+UseParallelGC -XX:SoftRefLRUPolicyMSPerMB=1 -XX:MaxHeapFreeRatio=99 -Dorg.gradle.daemon=false"
ENV JAVA_OPTS="$JAVA_OPTS -DTOMCAT_PASSWORD=$TOMCAT_PASSWORD -Dorg.apache.el.parser.SKIP_IDENTIFIER_CHECK=true $MEM_OPTS -XX:+UseParallelGC -XX:SoftRefLRUPolicyMSPerMB=1 -XX:MaxHeapFreeRatio=99"
ENV TOMCAT_MAJOR=8 \
    TOMCAT_VERSION=8.5.3 \
    TOMCAT_HOME=/opt/tomcat \
    CATALINA_HOME=/opt/tomcat \
    CATALINA_OUT=/dev/null

RUN apk add --no-cache openjdk8-jre && \
    ln -sf "${JAVA_HOME}/bin/"* "/usr/bin/"

RUN apk upgrade --update && \
    apk add --update curl && \
    curl -jksSL -o /tmp/apache-tomcat.tar.gz http://archive.apache.org/dist/tomcat/tomcat-${TOMCAT_MAJOR}/v${TOMCAT_VERSION}/bin/apache-tomcat-${TOMCAT_VERSION}.tar.gz && \
    gunzip /tmp/apache-tomcat.tar.gz && \
    tar -C /opt -xf /tmp/apache-tomcat.tar && \
    ln -s /opt/apache-tomcat-${TOMCAT_VERSION} ${TOMCAT_HOME}
    
RUN apk del curl && rm -rf /tmp/* /var/cache/apk/*

COPY ./configs/tomcat-users.xml /opt/tomcat/conf/
COPY ./configs/context.xml /opt/tomcat/webapps/manager/META-INF/context.xml
COPY ./configs/context.xml /opt/tomcat/webapps/host-manager/META-INF/context.xml

WORKDIR /opt/tomcat
EXPOSE 8080
ENTRYPOINT ["./bin/catalina.sh", "run"]
