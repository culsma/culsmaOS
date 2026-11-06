"""Validate explicit simulation handoffs before admitting a continuation."""

from dataclasses import asdict
from hashlib import sha256
import json
from uuid import NAMESPACE_URL, uuid5

from ..models import RunRequest, RunConflict
from .setup_requirements import SetupRequirementsInteractor
from .workspace import WorkspaceCheckpointInteractor


class ExternalSimulationHandoffInteractor:
    def __init__(self, repository, tasks, report, host, snapshot, station_id, space):
        self.repository = repository
        self.tasks = tasks
        self.report = report
        self.host = host
        self.codec = host.codec
        self.snapshot = snapshot
        self.station_id = station_id
        self.space = space

    def station(self):
        if self.snapshot.mode != "simulation":
            raise ValueError("EXTERNAL_SIMULATION_REQUIRED")
        return self.snapshot.execution_identity(self.station_id)

    def continuation_id(self, handoff_id):
        return str(uuid5(NAMESPACE_URL, "culsma:simulation-continuation:" + handoff_id))

    def source_material(self, run_id):
        record = self.tasks.get(run_id)
        if record.status != "completed":
            raise ValueError("EXTERNAL_SOURCE_NOT_COMPLETED")
        material = self.report.result(run_id).user_result["os"].get("registered_material")
        if material is None or material["mode"] != "simulation":
            raise ValueError("EXTERNAL_SOURCE_SIMULATION_EVIDENCE_REQUIRED")
        return record, material

    def begin(self, source_run_id, continuation, operation, sample_ids, return_bindings, observation_fields):
        station = self.station()
        source, material = self.source_material(source_run_id)
        if not isinstance(continuation, RunRequest) or continuation.setup_preferences is not None or continuation.profile_bindings is not None:
            raise ValueError("EXTERNAL_CONTINUATION_REQUEST_INVALID")
        if (not isinstance(operation, str) or not operation.strip()
                or not isinstance(observation_fields, tuple) or not observation_fields
                or any(not isinstance(field, str) or not field.strip() for field in observation_fields)
                or len(set(observation_fields)) != len(observation_fields)):
            raise ValueError("EXTERNAL_RESULT_CONTRACT_INVALID")
        handoff_id = str(uuid5(NAMESPACE_URL, "culsma:simulation-handoff:" + source_run_id))
        sealed = self.tasks.prepare_checkpoint(continuation, self.continuation_id(handoff_id))
        demands = SetupRequirementsInteractor(self.codec).inspect(sealed)
        workspace = WorkspaceCheckpointInteractor(self.codec).read(self.codec.loads(sealed))
        positions = self.space.configured_positions(workspace)
        by_allocation = {d["allocation_id"]: d for d in demands}
        containers = material["state"]["containers"]
        if (not isinstance(sample_ids, tuple) or not sample_ids
                or any(not isinstance(ref, str) or ref not in containers for ref in sample_ids)
                or len(set(sample_ids)) != len(sample_ids)):
            raise ValueError("EXTERNAL_SOURCE_SAMPLES_INVALID")
        if (not isinstance(return_bindings, dict) or not return_bindings
                or len(by_allocation) != len(demands)
                or set(return_bindings) - (set(by_allocation) & set(positions))
                or any(not isinstance(ref, str) or ref not in sample_ids for ref in return_bindings.values())):
            raise ValueError("EXTERNAL_RETURN_BINDINGS_INVALID")
        expected = {
            allocation: {
                "source_sample_id": reference,
                "load": by_allocation[allocation],
                "destination": asdict(positions[allocation]),
            }
            for allocation, reference in sorted(return_bindings.items())
        }
        request = {
            "schema": "culsma_external_simulation_request_v1",
            "mode": "simulation",
            "handoff_id": handoff_id,
            "source_run_id": source_run_id,
            "source_revision": source.revision,
            "source_material_fingerprint": self.codec.fingerprint(material),
            "continuation_fingerprint": sha256(sealed.encode()).hexdigest(),
            "station": station,
            "operation": operation,
            "sample_ids": list(sample_ids),
            "observation_fields": list(observation_fields),
            "expected_returns": expected,
        }
        request["fingerprint"] = self.codec.fingerprint(request)
        stored, _, _ = self.repository.create(request, sealed)
        if stored["fingerprint"] != request["fingerprint"]:
            raise ValueError("EXTERNAL_HANDOFF_CONFLICT")
        return stored

    def get(self, handoff_id):
        self.station()
        request, _, receipt = self.repository.get(handoff_id)
        run_id = self.continuation_id(handoff_id)
        try:
            continuation = self.tasks.get(run_id)
        except KeyError:
            continuation = None
        status = "receipt_accepted" if receipt is not None else "awaiting_external_result"
        if continuation is not None:
            status = continuation.status
        return {"request": request, "receipt": receipt, "status": status,
                "continuation_run_id": continuation.run_id if continuation is not None else None}

    def accept(self, handoff_id, receipt):
        request, _, _ = self.repository.get(handoff_id)
        self.validate_source(request)
        self.validate_receipt(request, receipt)
        if self.repository.accept(handoff_id, receipt) != receipt:
            raise ValueError("EXTERNAL_RECEIPT_CONFLICT")
        return self.get(handoff_id)

    def validate_source(self, request):
        if request["station"] != self.station():
            raise ValueError("EXTERNAL_STATION_CHANGED")
        source, material = self.source_material(request["source_run_id"])
        if (source.revision != request["source_revision"]
                or self.codec.fingerprint(material) != request["source_material_fingerprint"]):
            raise ValueError("EXTERNAL_SOURCE_CHANGED")

    def validate_receipt(self, request, receipt):
        if (not isinstance(receipt, dict)
                or receipt.get("schema") != "culsma_external_simulation_receipt_v1"
                or receipt.get("provider") != "internal_fixture"
                or receipt.get("mode") != "simulation"
                or receipt.get("outcome") != "completed"
                or receipt.get("handoff_id") != request["handoff_id"]
                or receipt.get("request_fingerprint") != request["fingerprint"]):
            raise ValueError("EXTERNAL_RECEIPT_MISMATCH")
        if receipt.get("sample_ids") != request["sample_ids"]:
            raise ValueError("EXTERNAL_OBSERVATION_SAMPLES_MISMATCH")
        observations = receipt.get("observations")
        if not isinstance(observations, dict) or set(observations) != set(request["observation_fields"]):
            raise ValueError("EXTERNAL_OBSERVATION_FIELDS_MISMATCH")
        returned = receipt.get("returned_samples")
        expected = request["expected_returns"]
        if not isinstance(returned, dict) or set(returned) != set(expected):
            raise ValueError("EXTERNAL_RETURN_SAMPLES_MISMATCH")
        sample_ids = set()
        for allocation, requirement in expected.items():
            row = returned[allocation]
            sample_id = row.get("returned_sample_id") if isinstance(row, dict) else None
            if (not isinstance(sample_id, str) or not sample_id.strip() or sample_id in sample_ids
                    or row.get("source_sample_id") != requirement["source_sample_id"]
                    or row.get("load") != requirement["load"]
                    or row.get("destination") != requirement["destination"]):
                raise ValueError("EXTERNAL_RETURN_SAMPLES_MISMATCH")
            sample_ids.add(sample_id)
        # Accept only stable JSON values so the receipt compares identically after restart.
        try:
            serialized = json.dumps(receipt, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError("EXTERNAL_RECEIPT_INVALID") from error
        if json.loads(serialized) != receipt:
            raise ValueError("EXTERNAL_RECEIPT_INVALID")

    def start_continuation(self, handoff_id):
        request, sealed, receipt = self.repository.get(handoff_id)
        self.validate_source(request)
        if receipt is None:
            raise ValueError("EXTERNAL_RECEIPT_REQUIRED")
        self.validate_receipt(request, receipt)
        if sha256(sealed.encode()).hexdigest() != request["continuation_fingerprint"]:
            raise ValueError("EXTERNAL_CONTINUATION_CHANGED")
        run_id = self.continuation_id(handoff_id)
        try:
            existing = self.tasks.get(run_id)
        except KeyError:
            data, _ = self.host.restore(sealed)
            if data["scope_id"] != run_id:
                raise ValueError("EXTERNAL_CONTINUATION_CHANGED")
            try:
                return self.tasks.submit_simulation_continuation(run_id, sealed, request["station"])
            except RunConflict:
                # Another caller may have won the same unique run identity.
                existing = self.tasks.get(run_id)
        if existing.simulation_station != request["station"]:
            raise ValueError("EXTERNAL_CONTINUATION_ID_CONFLICT")
        return existing.run_id
