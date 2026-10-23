"""Local operator setup commands; no implicit execution or operator confirmation."""
from contextlib import nullcontext


class RunSetupCommandInteractor:
    def __init__(self, applications, ownership):
        self.applications, self.ownership = applications, ownership

    def execute(self, request):
        if request.action not in {'show', 'revise', 'begin', 'confirm'}:
            raise ValueError('SETUP_COMMAND_INVALID')
        if not request.context.database_path.is_file():
            raise ValueError('RUN_DATABASE_NOT_FOUND')
        with self.ownership.embedded(request.context) if request.action != 'show' else nullcontext():
            app = self.applications.build(request.context)
            try:
                setup = app.client.tasks.setup
                if not setup.enabled():
                    raise ValueError('SETUP_DEVICE_UNSUPPORTED')
                if request.action == 'show':
                    return setup.get(request.run_id)
                owner = app.client.lifecycle.reservations.get(request.run_id)
                if owner is not None and owner.owner_id != app.client.lifecycle.reservations.owner_id:
                    app.client.take_over_run(request.run_id)
                if request.action == 'revise':
                    return setup.plan(request.run_id, request.preferences)
                if request.action == 'begin':
                    return setup.begin_loading(request.run_id, request.fingerprint)
                return setup.confirm(request.run_id, request.fingerprint, request.acknowledged)
            finally:
                app.close()
