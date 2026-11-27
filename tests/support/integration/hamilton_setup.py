"""Shared Hamilton operator preparation fixture; never executes vendor hardware."""
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import RunRequest
from tests.support.integration.hamilton import HamiltonOperationTestBackend


class SetupFixture:
    @staticmethod
    def app(context, backend=None):
        from culsma_hamilton_os.providers import HamiltonOSDeviceFactory
        return OSApplicationFactory(session_factories={'hamilton-agent': HamiltonOSDeviceFactory(
            backend_factory=backend or HamiltonOperationTestBackend())}).build(context)

    @staticmethod
    def submit(app, compiled):
        app.client.start()
        run_id = app.client.submit_run(RunRequest(compiled.plan, compiled.state))
        return run_id, app.client.setup_plan(run_id)
