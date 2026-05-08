# intermine-tomcat:agr-1x-runtime
#
# Tomcat 8.5 + JDK 11 with all InterMine 1.x patches baked in.
# Used for mousemine, wormmine, flymine.
#
# See docs/INTERMINE_TOMCAT_DOCKER.md (§8) for what's patched and why.
#
# Build:
#   docker build -t intermine-tomcat:agr-1x-runtime .
#
# Run (mousemine on port 8084):
#   docker run -d --name mousemine-1x \
#     -p 8084:8080 \
#     -e MANAGER_PASSWORD="$(openssl rand -hex 16)" \
#     -e JAVA_OPTS="-Dorg.apache.el.parser.SKIP_IDENTIFIER_CHECK=true -Xmx4g -Xms2g" \
#     intermine-tomcat:agr-1x-runtime

FROM tomcat:8.5-jdk11-temurin

# Patch global context.xml — session cookie path, cookie HttpOnly off,
# clear ScheduledExecutor refs on undeploy
COPY conf/context.xml /usr/local/tomcat/conf/context.xml

# Patch tomcat-users (template; rendered at runtime via envsubst)
COPY conf/tomcat-users.template.xml /usr/local/tomcat/conf/tomcat-users.template.xml

# Patch catalina.properties — append SKIP_IDENTIFIER_CHECK system prop
RUN echo "" >> /usr/local/tomcat/conf/catalina.properties && \
    echo "# AGR patch: allow Java keywords as EL identifiers (InterMine JSP compat)" \
        >> /usr/local/tomcat/conf/catalina.properties && \
    echo "org.apache.el.parser.SKIP_IDENTIFIER_CHECK=true" \
        >> /usr/local/tomcat/conf/catalina.properties

# Patch server.xml — full-file replacement with URIEncoding=UTF-8 + RemoteIpValve baked in
COPY conf/server.xml /usr/local/tomcat/conf/server.xml

# Move manager + host-manager out of webapps.dist (Tomcat docker convention)
# into webapps so they're deployed by default
RUN cp -r /usr/local/tomcat/webapps.dist/manager /usr/local/tomcat/webapps/manager && \
    cp -r /usr/local/tomcat/webapps.dist/host-manager /usr/local/tomcat/webapps/host-manager

# Patch manager context.xml — RemoteAddrValve commented out (allows remote deploy)
COPY manager/context.xml /usr/local/tomcat/webapps/manager/META-INF/context.xml

# Patch manager web.xml — 500 MB upload limit
RUN sed -i 's|<max-file-size>52428800</max-file-size>|<max-file-size>524288000</max-file-size>|g' \
    /usr/local/tomcat/webapps/manager/WEB-INF/web.xml && \
    sed -i 's|<max-request-size>52428800</max-request-size>|<max-request-size>524288000</max-request-size>|g' \
    /usr/local/tomcat/webapps/manager/WEB-INF/web.xml

# Entrypoint — renders tomcat-users.xml from env, then execs catalina
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && \
    apt-get update && apt-get install -y --no-install-recommends gettext-base && \
    rm -rf /var/lib/apt/lists/*

# Defaults — override at runtime
ENV MANAGER_USER=manager
ENV MANAGER_PASSWORD=manager
ENV JAVA_OPTS="-Dorg.apache.el.parser.SKIP_IDENTIFIER_CHECK=true -Xmx4g -Xms2g"

EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
CMD ["catalina.sh", "run"]
