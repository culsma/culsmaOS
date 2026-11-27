"""One-shot OS execution behind the unchanged language CLI program-executor port."""

from pathlib import Path
from ..models import CommandRequest


class LanguageProgramInteractor:
    def __init__(self, runner, device_driver_name=None):
        self.runner = runner
        self.device_driver_name = device_driver_name

    def execute(self, request):
        artifacts = request.artifacts_dir or Path("run-artifacts")
        return self.runner.execute(
            CommandRequest(
                input_paths=list(request.input_paths),
                fail_ops=set(request.fail_ops),
                material_state_path=request.material_state_path,
                inventory_check=request.inventory_check,
                library_roots=list(request.library_roots),
                driver_name=self.device_driver_name or request.driver_name,
                driver_config_path=request.config_path,
                driver_artifacts_dir=artifacts / "driver",
                host_database_path=artifacts / "culsma-os.sqlite3",
                execution_mode="os",
            )
        )
