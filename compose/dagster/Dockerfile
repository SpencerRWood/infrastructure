ARG PYTHON_VERSION=3.12-slim
FROM python:${PYTHON_VERSION}

ARG DAGSTER_VERSION=1.13.16
ARG DAGSTER_LIB_VERSION=0.29.16
# Match the repository's validated SQLAlchemy version. 2.1 changes the default
# PostgreSQL driver to psycopg3; dagster-postgres installs psycopg2 instead.
RUN pip install --no-cache-dir dagster==${DAGSTER_VERSION} dagster-graphql==${DAGSTER_VERSION} dagster-postgres==${DAGSTER_LIB_VERSION} dagster-webserver==${DAGSTER_VERSION} SQLAlchemy==2.0.52
# Exercise Dagster's engine factory inside the built runtime, without connecting
# to a database. Dependency/driver failures must block the build, not startup.
RUN pip check && python -c "from dagster_postgres.utils import create_pg_engine; engine = create_pg_engine('postgresql://dagster:test@localhost/dagster'); assert engine.dialect.driver == 'psycopg2'; engine.dispose()"
ENV DAGSTER_HOME=/opt/dagster/dagster_home
RUN mkdir -p /opt/dagster/dagster_home /opt/dagster/app /opt/dagster/local
COPY app/ /opt/dagster/app/
WORKDIR /opt/dagster/dagster_home
