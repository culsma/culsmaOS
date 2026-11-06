"""Deterministic external-device fixtures for isolated OS simulation."""

from copy import deepcopy


class ExternalFixtureSimulator:
    def __init__(self, scenarios):
        self.scenarios = deepcopy(scenarios)

    def execute(self, request):
        if request["mode"] != "simulation":
            raise ValueError("EXTERNAL_SIMULATION_REQUIRED")
        try:
            fixture = self.scenarios[request["operation"]]
        except KeyError as error:
            raise ValueError("EXTERNAL_FIXTURE_UNAVAILABLE") from error
        return {
            **deepcopy(fixture),
            "schema": "culsma_external_simulation_receipt_v1",
            "mode": "simulation",
            "provider": "internal_fixture",
            "handoff_id": request["handoff_id"],
            "request_fingerprint": request["fingerprint"],
        }
