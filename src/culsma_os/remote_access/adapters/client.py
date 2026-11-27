"""Read-only station client used by the remote MCP entry."""
from ..models import RemoteReadOperation, RemoteReadRequest
from ..ports import RemoteReadTransportPort


class RemoteStationClient:
    def __init__(self, station_id: str, transport: RemoteReadTransportPort):
        self.station_id, self.transport = station_id, transport

    def station_status(self):
        return self.transport.read(RemoteReadRequest(self.station_id, RemoteReadOperation.STATION))

    def list_runs(self):
        return self.transport.read(RemoteReadRequest(self.station_id, RemoteReadOperation.RUNS))

    def run_status(self, run_id: str):
        return self.transport.read(RemoteReadRequest(self.station_id, RemoteReadOperation.RUN, run_id))
