from packages.connectors.base import DatabaseConnector
from packages.connectors.postgresql import PostgreSQLConnector
from packages.platform_core.models import DataSourceType


class ConnectorRegistry:
    def __init__(self, connectors: tuple[DatabaseConnector, ...] | None = None) -> None:
        registered = connectors or (PostgreSQLConnector(),)
        self._connectors = {item.source_type: item for item in registered}

    def get(self, source_type: DataSourceType) -> DatabaseConnector:
        connector = self._connectors.get(source_type)
        if connector is None:
            from packages.connectors.base import ConnectorError

            raise ConnectorError("connector.unsupported")
        return connector


connector_registry = ConnectorRegistry()
