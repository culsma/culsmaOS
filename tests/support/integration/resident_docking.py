"""Real official simulator acceptance through the resident worker and IPC boundary."""

from tests.support.paths import ROOT
from dataclasses import replace
from pathlib import Path
import json
import sqlite3
import threading
import subprocess
import sys
import time
from uuid import uuid4
import pytest
from culsma_os.bootstrap import OSApplicationFactory, OpentronsSessionFactory
from culsma_os.lifecycle_manager.models import ResidentHostSettings
from culsma_os.program_manager.adapters.resident import ResidentClientAdapter
from tests.support.integration.resident_host import ResidentHarness
from tests.support.workspace_manager.heater_shaker_docking import SOURCE


SECOND = SOURCE.replace(':50uL', ':40uL').replace(':20uL', ':15uL')


class DeviceFault:
    def __init__(self, original, hit=1, after=True):
        self.original, self.hit, self.after = original, hit, after
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.calls == self.hit:
            if self.after:
                self.original(*args, **kwargs)
            raise TimeoutError('resident test lost device completion')
        return self.original(*args, **kwargs)


class ObservedMotionPort:
    def __init__(self, delegate, probe):
        self.delegate, self.probe = delegate, probe
        self.session = delegate.session

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def execute(self, plan, attempt_id):
        kind = type(plan).__name__
        event = {'attempt_id':attempt_id, 'kind':kind, 'thread':threading.current_thread().name}
        self.probe.dispatches.append(event)
        receipt = self.delegate.execute(plan, attempt_id)
        event['outcome'] = receipt['outcome']
        event['available_tips'] = self.session.backend.available_tips()
        if kind == self.probe.gate_kind and not self.probe.gated:
            self.probe.gated = True
            self.probe.entered.set()
            if not self.probe.release.wait(10):
                raise RuntimeError('resident motion gate timed out')
        return receipt


class ObservedMotionFactory:
    def __init__(self, gate_kind=None, fault=None):
        self.gate_kind, self.fault = gate_kind, fault
        self.gated = False
        self.entered, self.release = threading.Event(), threading.Event()
        self.ports, self.dispatches, self.initial = [], [], []

    def build(self, context):
        delegate, *description = OpentronsSessionFactory().build(context)
        session = delegate.session
        self.initial.append({'positions':session.motion.positions(),
                             'commands':tuple(session.backend.protocol.commands())})
        if self.fault:
            owner, method, hit, after = {
                'open-before':(session.backend.modules['heater'], 'open_labware_latch', 1, False),
                'move-after':(session.backend.protocol, 'move_labware', 1, True),
                'heat-stop':(session.backend.modules['heater'], 'deactivate_heater', 1, True),
                'shake-stop':(session.backend.modules['heater'], 'deactivate_shaker', 1, True),
                'unload-after':(session.backend.protocol, 'move_labware', 2, True),
            }[self.fault]
            setattr(owner, method, DeviceFault(getattr(owner,method), hit, after))
        port = ObservedMotionPort(delegate, self)
        self.ports.append(port)
        return (port, *description)


class ResidentDockingHarness(ResidentHarness):
    def __init__(self, directory, sessions=None):
        super().__init__(directory, sessions or ObservedMotionFactory())
        self.context = replace(self.context, driver_name='opentrons-simulator',
                               config_path=ROOT/'examples/heater-shaker-docking/deck.json')
        self.settings = ResidentHostSettings(self.context, self.endpoint, 0.01)
        self.first_source, self.second_source = directory/'first.culs',directory/'second.culs'
        self.first_source.write_text(SOURCE)
        self.second_source.write_text(SECOND)

    def serve(self):
        try:
            self.host = OSApplicationFactory({'opentrons-simulator':self.sessions}).build_resident_host(self.settings)
            self.host.serve()
        except BaseException as error:
            self.errors.append(error)

    def submit(self, source=None, **kwargs):
        return self.client.execute({'action':'submit','source':str(source or self.first_source),**kwargs})

    def rows(self, table):
        # Independent read-only audit connection; never use worker-owned SQLite objects.
        from culsma_os.resource_manager.interactors import StationPathInteractor
        database = StationPathInteractor().database_path(self.context) if table in {
            'os_labware_positions','os_motion_registrations','os_station_motion_intents'} else self.context.database_path
        with sqlite3.connect(database) as connection:
            return connection.execute('SELECT * FROM '+table).fetchall()

    def attempts(self, run_id=None):
        records = [json.loads(row[2]) for row in self.rows('os_attempts')]
        return [record for record in records if run_id is None or record['run_id'] == run_id]

    def assert_following_untouched(self, run_id):
        assert self.status(run_id)['status'] == 'ready'
        assert not self.attempts(run_id)
        assert not self.status(run_id)['result']['os'].get('registered_material')

    def assert_results(self, first, second, dispatches=None):
        expected = ({'Assay_A1':30, 'Stock':70},{'Assay_A1':25,'Stock':75})
        for run_id, volumes in zip((first,second),expected):
            result = self.status(run_id)
            assert result['status'] == 'completed'
            registered = result['result']['os']['registered_material']
            assert registered['version'] == 4
            actual = {v['metadata']['label']:v['volume_uL'] for v in registered['state']['containers'].values()}
            assert actual == volumes
            assert len(self.attempts(run_id)) == 6
        records = self.attempts()
        owners = {r['attempt_id']:r['run_id'] for r in records}
        dispatches = self.sessions.dispatches if dispatches is None else dispatches
        observed = [owners[d['attempt_id']] for d in dispatches]
        assert observed == [first]*6 + [second]*6
        assert all(d['thread']=='culsma-os-execution' for d in dispatches)
        assert len(self.rows('os_motion_registrations')) == 4
        positions = self.rows('os_labware_positions')[0]
        assert positions[2] == 4 and json.loads(positions[3])['assay'] == 'D1'
        assert not self.rows('os_resource_locks')
