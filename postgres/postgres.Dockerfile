FROM postgres:9.3
LABEL maintainer="Ank"

COPY ./init_postgresql.sh /docker-entrypoint-initdb.d/
COPY ./postgresql.conf /opt/postgresql.conf
COPY docker-healthcheck /usr/local/bin/

HEALTHCHECK CMD ["docker-healthcheck"]
ENTRYPOINT ["docker-entrypoint.sh"]
EXPOSE 5432

RUN chmod 777 /opt
RUN echo "127.0.0.1			postgres" >> /etc/hosts

CMD ["postgres", "-c", "config_file=/opt/postgresql.conf", "-p", "5432"]
