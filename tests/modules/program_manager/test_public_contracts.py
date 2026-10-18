"""Public input/output and durable notification contracts."""
import json
import sqlite3
from dataclasses import replace

import pytest

from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.interactors.runs import TaskInteractor
from culsma_os.program_manager.models import RunRecord
from culsma_os.program_manager.repositories.runs import SqliteTaskRepository
from tests.support.common import FakeSessionFactory, ProgramFixture


class TestPublicContracts:
    @pytest.mark.parametrize('payload', [[], None, 12, 'inventory'])
    def test_inventory_snapshot_rejects_non_object_root(self, tmp_path, payload):
        path = tmp_path / 'inventory.json'
        path.write_text(json.dumps(payload))
        runner = OSApplicationFactory().build_program_runner()
        with pytest.raises(ValueError, match='INVENTORY_SNAPSHOT_INVALID'):
            runner.load_inventory_snapshot(path)

    def test_optional_inventory_and_material_input_roundtrip(self, tmp_path):
        runner = OSApplicationFactory().build_program_runner()
        assert runner.load_inventory_snapshot(None) is None
        assert runner.load_initial_material_state(None) == {'containers': {}}
        path = tmp_path / 'input.json'
        payload = {'containers': {}, 'inventory': {'tips': 96}}
        path.write_text(json.dumps(payload))
        assert runner.load_inventory_snapshot(path) == payload
        assert runner.load_initial_material_state(path) == payload

    def test_batch_failure_preserves_each_inputs_report(self):
        runner = OSApplicationFactory().build_program_runner()
        items = [{'input': name, 'bundle': {'output': {'ok': ok, 'report': {'id': name}},
                  'summary': {'source': name}}} for name, ok in [('first', True), ('second', False)]]
        result = runner.build_batch_run_output(run_items=items)
        assert result['schema'] == 'culsma_batch_run_output_v1' and not result['ok']
        assert [r['input'] for r in result['runs']] == ['first', 'second']
        assert [r['output']['report']['id'] for r in result['runs']] == ['first', 'second']
        assert [r['ok'] for r in result['runs']] == [True, False]

    def test_publishing_one_revision_keeps_the_next_revision_pending(self, tmp_path):
        path = tmp_path / 'runs.sqlite3'
        with sqlite3.connect(path) as connection:
            repository = SqliteTaskRepository(connection)
            first = repository.save(RunRecord('run', 'ready', 'checkpoint'))
            repository.save(replace(first, status='paused'))
            tasks = TaskInteractor(repository, None, None)
            events = tasks.pending_events()
            assert [(e.run_id, e.status, e.revision) for e in events] == [
                ('run', 'ready', 1), ('run', 'paused', 2)]
            tasks.mark_published(events[0].event_id)
        with sqlite3.connect(path) as connection:
            tasks = TaskInteractor(SqliteTaskRepository(connection), None, None)
            assert [(e.status, e.revision) for e in tasks.pending_events()] == [('paused', 2)]
            tasks.mark_published(events[0].event_id)
            assert len(tasks.pending_events()) == 1

    def test_client_stop_requires_restart_without_releasing_active_run(self, tmp_path):
        app = FakeSessionFactory().open(tmp_path)
        try:
            app.client.start()
            run_id = app.client.submit_run(ProgramFixture.request())
            app.client.lifecycle.runs.advance_ready(run_id)
            assert not app.client.lifecycle.reservations.released_safely(run_id)
            app.client.close()
            with pytest.raises(ValueError, match='OS_NOT_STARTED'):
                app.client.advance_run(run_id)
            assert app.client.lifecycle.reservations.get(run_id).status == 'active'
            app.client.start()
            assert app.client.run_until_settled(run_id).status == 'completed'
            assert app.client.lifecycle.reservations.released_safely(run_id)
        finally:
            app.close()
