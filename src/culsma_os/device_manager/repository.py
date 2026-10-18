import json
from dataclasses import asdict
from typing import Protocol
from .models import DeviceConfigurationSnapshot, ExecutionFeedbackCapabilities


class DeviceRepository(Protocol):

    def put(self, snapshot: DeviceConfigurationSnapshot) -> None: ...

    def get(self, device_id: str) -> DeviceConfigurationSnapshot: ...


class SqliteDeviceRepository:

    def __init__(self, connection, legacy=None):
        self.connection, self.legacy = connection, legacy
        with connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS os_devices(device_id TEXT PRIMARY KEY,snapshot TEXT)"
            )

    def put(self, snapshot):
        with self.connection:
            self.connection.execute(
                "INSERT INTO os_devices VALUES(?,?) ON CONFLICT(device_id) DO UPDATE SET snapshot=excluded.snapshot",
                (snapshot.device_id, json.dumps(asdict(snapshot))),
            )

    def get(self, device_id):
        row = self.connection.execute(
            "SELECT snapshot FROM os_devices WHERE device_id=?", (device_id,)
        ).fetchone()
        if row is None and self.legacy is not None and self.legacy.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='os_devices'").fetchone():
            row = self.legacy.execute('SELECT snapshot FROM os_devices WHERE device_id=?', (device_id,)).fetchone()
        if row is None:
            raise KeyError(device_id)
        return self.decode_snapshot(row[0])

    @staticmethod
    def decode_snapshot(payload):
        data = json.loads(payload)
        data["shared_resources"] = tuple(data["shared_resources"])
        if "tip_capacity" in data:
            capacity = data.pop("tip_capacity")
            data.setdefault("consumable_capacities", {"tips": capacity})
        data["labware_geometries"] = {name: tuple(shape) for name, shape in data.get("labware_geometries", {}).items()}
        data["transfer_selection_capabilities"] = tuple(data.get("transfer_selection_capabilities", ()))
        data["transfer_requirements"] = tuple(data.get("transfer_requirements", ()))
        feedback = data.get("feedback_capabilities")
        if feedback is not None:
            data["feedback_capabilities"] = ExecutionFeedbackCapabilities(tuple(feedback["completion_units"]))
        return DeviceConfigurationSnapshot(**data)


class DeviceInspectionRepository(Protocol):
    def snapshots(self) -> tuple[DeviceConfigurationSnapshot, ...]: ...


class SqliteDeviceInspectionRepository:
    def __init__(self, snapshot, legacy=None):
        self.snapshot, self.legacy = snapshot, legacy

    def snapshots(self):
        sources = (self.legacy, self.snapshot) if self.legacy is not None else (self.snapshot,)
        devices = {}
        for source in sources:
            for row in source.rows('os_devices', 'SELECT snapshot FROM os_devices ORDER BY device_id'):
                device = SqliteDeviceRepository.decode_snapshot(row[0])
                devices[device.device_id] = device
        return tuple(devices[key] for key in sorted(devices))
