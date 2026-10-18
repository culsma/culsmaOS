"""Explicit run control uses the saved program, never resubmits source."""

class RunControlInteractor:
    def __init__(self, applications, ownership=None):
        self.applications = applications
        self.ownership = ownership

    def execute(self, request):
        from contextlib import nullcontext
        lease = (self.ownership.embedded(request.context)
                 if self.ownership and request.action != 'status' else nullcontext())
        with lease:
            return self.execute_owned(request)

    def execute_owned(self, request):
        if request.action not in {"resume", "pause", "cancel", "status"}:
            raise ValueError("RUN_CONTROL_ACTION_INVALID")
        if not request.context.database_path.is_file():
            raise ValueError("RUN_DATABASE_NOT_FOUND")
        if request.action != "resume":
            inspector = self.applications.build_run_inspector(request.context)
            try:
                return inspector.execute(request)
            finally:
                inspector.close()
        app = self.applications.build(request.context)
        try:
            app.client.take_over_run(request.run_id)
            app.client.start()
            if app.client.get_run(request.run_id).status not in {"completed", "cancelled"}:
                app.client.resume_run(request.run_id)
            app.client.run_until_settled(request.run_id)
            record = app.client.get_run(request.run_id)
            return {"run_id": record.run_id, "status": record.status,
                    "revision": record.revision, "error": record.error, "body_outcome": record.body_outcome,
                    "ok": record.status == "completed",
                    "result": app.host.result(request.run_id).user_result}
        finally:
            app.close()


class RunInspectionInteractor:
    def __init__(self, tasks, report, connections):
        self.tasks, self.report, self.connections = tasks, report, connections

    def execute(self, request):
        if request.action == "pause":
            self.tasks.pause_dispatch(request.run_id)
        elif request.action == "cancel":
            self.tasks.request_cancel(request.run_id)
        elif request.action != "status":
            raise ValueError("RUN_INSPECTION_ACTION_INVALID")
        record = self.tasks.get(request.run_id)
        return {"run_id": record.run_id, "status": record.status,
                "revision": record.revision, "error": record.error, "body_outcome": record.body_outcome,
                "ok": record.status == "completed",
                "result": self.report.result(request.run_id).user_result}

    def close(self):
        for connection in self.connections:
            connection.close()
