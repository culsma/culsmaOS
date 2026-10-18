from ..models import SemanticHostPort
from ..models import RunRequest


class PreparationInteractor:

    def __init__(self, host: SemanticHostPort, catalog=None, checkpoints=None):
        self.host, self.catalog, self.checkpoints = host, catalog, checkpoints

    def prepare(self, request: RunRequest, run_id: str) -> str:
        errors = [d for d in request.plan.diagnostics if d.severity == "error"]
        if errors:
            raise ValueError("PROGRAM_DIAGNOSTICS_REJECTED")
        workspace = self.catalog.resolve(request.plan) if self.catalog is not None else None
        checkpoint = self.host.create(request.plan, request.state, run_id)
        return self.checkpoints.attach(checkpoint, workspace) if workspace is not None else checkpoint
