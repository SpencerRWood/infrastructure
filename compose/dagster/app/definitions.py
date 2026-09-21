from dagster import Definitions, asset


@asset
def dagster_platform_healthcheck() -> str:
    return "ok"


defs = Definitions(assets=[dagster_platform_healthcheck])
