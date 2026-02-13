FROM alpine:3.20
LABEL maintainer="Alliance of Genome Resources"
LABEL description="InterMine Host Base Image - Java 8, Tomcat 8, Solr 8.4.1 (RDS-ready)"
LABEL version="2.0-rds-base"

# Environment setup
ENV JAVA_HOME="/usr/lib/jvm/default-jvm"
ENV PATH="$JAVA_HOME/bin:$PATH"
ENV HOME="/home/intermine"
ENV USER_HOME="/home/intermine"

# Install base dependencies in single layer
RUN apk add --no-cache --virtual .build-deps \
    wget \
    tar \
    unzip \
    && apk add --no-cache \
    openjdk8-jdk \
    openjdk8-jre \
    bash \
    curl \
    git \
    maven \
    postgresql-client \
    ca-certificates \
    && ln -sf "${JAVA_HOME}/bin/"* "/usr/bin/" \
    \
    # Install Gradle 6.9.4 (Java 8 compatible)
    && wget -q -O /tmp/gradle.zip https://services.gradle.org/distributions/gradle-6.9.4-bin.zip \
    && unzip -q /tmp/gradle.zip -d /opt \
    && ln -s /opt/gradle-6.9.4/bin/gradle /usr/local/bin/gradle \
    \
    # Install Tomcat 8.5.93
    && wget -q -O /tmp/tomcat.tar.gz https://archive.apache.org/dist/tomcat/tomcat-8/v8.5.93/bin/apache-tomcat-8.5.93.tar.gz \
    && tar -xzf /tmp/tomcat.tar.gz -C /opt \
    && mv /opt/apache-tomcat-8.5.93 /opt/tomcat \
    \
    # Install Solr 8.4.1
    && wget -q -O /tmp/solr.tgz https://archive.apache.org/dist/lucene/solr/8.4.1/solr-8.4.1.tgz \
    && tar -xzf /tmp/solr.tgz -C /opt \
    && mv /opt/solr-8.4.1 /opt/solr \
    \
    # Clean up downloads and build deps
    && rm -rf /tmp/* \
    && apk del .build-deps \
    && rm -rf /var/cache/apk/* \
    \
    # Remove unnecessary Solr files
    && rm -rf /opt/solr/docs \
    && rm -rf /opt/solr/example \
    && find /opt/solr -name "*.zip" -delete \
    && find /opt/solr -name "*.tar.gz" -delete \
    \
    # Remove Tomcat examples
    && rm -rf /opt/tomcat/webapps/examples \
    && rm -rf /opt/tomcat/webapps/docs \
    && rm -rf /opt/tomcat/webapps/ROOT \
    \
    # Create intermine user
    && addgroup -g 1000 intermine \
    && adduser -D -u 1000 -G intermine intermine \
    && mkdir -p /home/intermine \
    && chown -R intermine:intermine /home/intermine /opt/solr /opt/tomcat

# Tomcat configuration (InterMine optimized)
COPY <<EOF /opt/tomcat/conf/context.xml
<?xml version="1.0" encoding="UTF-8"?>
<Context sessionCookiePath="/" useHttpOnly="false" clearReferencesStopTimerThreads="true">
    <WatchedResource>WEB-INF/web.xml</WatchedResource>
    <WatchedResource>\${catalina.base}/conf/web.xml</WatchedResource>
</Context>
EOF

COPY <<EOF /opt/tomcat/conf/server.xml
<?xml version="1.0" encoding="UTF-8"?>
<Server port="8005" shutdown="SHUTDOWN">
  <Service name="Catalina">
    <Connector port="8080" protocol="HTTP/1.1"
               connectionTimeout="20000"
               redirectPort="8443"
               URIEncoding="UTF-8"
               maxThreads="150"/>
    <Engine name="Catalina" defaultHost="localhost">
      <Host name="localhost" appBase="webapps" unpackWARs="true" autoDeploy="true"/>
    </Engine>
  </Service>
</Server>
EOF

COPY <<EOF /opt/tomcat/bin/setenv.sh
#!/bin/bash
export JAVA_OPTS="\$JAVA_OPTS -Xmx3g -Xms2g -Dorg.apache.el.parser.SKIP_IDENTIFIER_CHECK=true -Djava.awt.headless=true -server"
EOF

RUN chmod +x /opt/tomcat/bin/setenv.sh

# Environment variables
ENV GRADLE_HOME=/opt/gradle-6.9.4
ENV PATH="$GRADLE_HOME/bin:$PATH"
ENV SOLR_HOME=/opt/solr
ENV CATALINA_HOME=/opt/tomcat
ENV GRADLE_OPTS="-Xmx3g -Xms2g"

# Switch to intermine user
USER intermine
WORKDIR $HOME

# Create base InterMine configuration directory
RUN mkdir -p .intermine

# Create script to wait for RDS availability
COPY <<'EOF' $HOME/wait-for-rds.sh
#!/bin/bash
set -e

echo "Waiting for RDS PostgreSQL at ${RDS_HOST}:${RDS_PORT}..."

MAX_ATTEMPTS=30
ATTEMPT=0

until pg_isready -h "${RDS_HOST}" -p "${RDS_PORT}" -U "${RDS_USER}" -t 5; do
    ATTEMPT=$((ATTEMPT+1))
    if [ $ATTEMPT -ge $MAX_ATTEMPTS ]; then
        echo "❌ Failed to connect to RDS after $MAX_ATTEMPTS attempts"
        exit 1
    fi
    echo "Waiting for RDS... (attempt $ATTEMPT/$MAX_ATTEMPTS)"
    sleep 5
done

echo "✅ RDS is available!"
EOF

RUN chmod +x $HOME/wait-for-rds.sh

# Expose ports
EXPOSE 8080 8983

WORKDIR /home/intermine

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/ || exit 1
