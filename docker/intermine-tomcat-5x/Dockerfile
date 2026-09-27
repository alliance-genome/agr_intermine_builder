# intermine-tomcat:agr-5x-runtime
#
# Tomcat 9 + JDK 11 with the InterMine 5.x patches baked in. First user: MouseMine 5.1
# (mousemine_im5 port); also fits any other InterMine 5.x WAR.
#
# The patched conf files are the stock Tomcat 9.0.122 files with minimal edits, each marked
# "AGR PATCH". See README.md here and docs/INTERMINE_TOMCAT_DOCKER.md for why each one exists.
#
# Build:
#   docker build -t intermine-tomcat:agr-5x-runtime docker/intermine-tomcat-5x/
#
# Run (MouseMine 5.1 test):
#   docker run -d --name mousemine-5x -p 8088:8080 \
#     -e MANAGER_PASSWORD="$(openssl rand -hex 16)" \
#     -e JAVA_OPTS="-Xmx6g -Xms2g" \
#     intermine-tomcat:agr-5x-runtime

FROM tomcat:9.0.122-jdk11-temurin

# Global context.xml — sessionCookiePath="/", useHttpOnly="false",
# clearReferencesStopTimerThreads="true" (InterMine 5 Tomcat requirements)
COPY conf/context.xml /usr/local/tomcat/conf/context.xml

# server.xml — explicit UTF-8, maxParameterCount 10000, RemoteIpValve for the ALB
COPY conf/server.xml /usr/local/tomcat/conf/server.xml

# tomcat-users template — rendered from MANAGER_USER / MANAGER_PASSWORD at start
COPY conf/tomcat-users.template.xml /usr/local/tomcat/conf/tomcat-users.template.xml

# EL: allow Java keywords as identifiers (InterMine JSPs use e.g. ${...class})
RUN printf '\n# AGR patch: allow Java keywords as EL identifiers (InterMine JSP compat)\norg.apache.el.parser.SKIP_IDENTIFIER_CHECK=true\n' \
        >> /usr/local/tomcat/conf/catalina.properties

# Manager webapp: deployed by default, remote deploy allowed, 500 MB WAR uploads
RUN cp -r /usr/local/tomcat/webapps.dist/manager /usr/local/tomcat/webapps/manager
COPY manager/context.xml /usr/local/tomcat/webapps/manager/META-INF/context.xml
RUN sed -i -e 's|<max-file-size>52428800</max-file-size>|<max-file-size>524288000</max-file-size>|' \
           -e 's|<max-request-size>52428800</max-request-size>|<max-request-size>524288000</max-request-size>|' \
        /usr/local/tomcat/webapps/manager/WEB-INF/web.xml \
    && grep -q '<max-file-size>524288000</max-file-size>' /usr/local/tomcat/webapps/manager/WEB-INF/web.xml

# envsubst for the tomcat-users template
RUN apt-get update && apt-get install -y --no-install-recommends gettext-base \
    && rm -rf /var/lib/apt/lists/*
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Defaults — override at runtime. Heap is per mine; MouseMine wants 6g+.
ENV MANAGER_USER=manager
ENV MANAGER_PASSWORD=manager
ENV JAVA_OPTS="-Xmx4g -Xms2g"

EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
CMD ["catalina.sh", "run"]
