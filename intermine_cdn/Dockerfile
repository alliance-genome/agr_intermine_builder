ARG DOCKER_PULL_TAG=latest
ARG REG=100225593120.dkr.ecr.us-east-1.amazonaws.com
FROM ${REG}/agr_base_linux_env:${DOCKER_PULL_TAG} as buildstage

WORKDIR /workdir/cdn

RUN git clone https://github.com/intermine/CDN.git

FROM nginx

WORKDIR /usr/share/nginx/html

COPY --from=buildstage /workdir/cdn/CDN /usr/share/nginx/html

