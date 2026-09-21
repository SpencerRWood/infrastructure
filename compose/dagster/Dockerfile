ARG PYTHON_VERSION=3.12-slim
FROM python:${PYTHON_VERSION}

ARG DAGSTER_VERSION=1.13.16
ARG DAGSTER_LIB_VERSION=0.29.16
RUN pip install --no-cache-dir dagster==${DAGSTER_VERSION} dagster-graphql==${DAGSTER_VERSION} dagster-postgres==${DAGSTER_LIB_VERSION} dagster-webserver==${DAGSTER_VERSION}
ENV DAGSTER_HOME=/opt/dagster/dagster_home
RUN mkdir -p /opt/dagster/dagster_home /opt/dagster/app /opt/dagster/local
COPY app/ /opt/dagster/app/
WORKDIR /opt/dagster/dagster_home
