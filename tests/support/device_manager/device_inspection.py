"""Read-only OS observations, including real simulator activity and uncertainty."""

from tests.support.paths import ROOT
from dataclasses import asdict
from pathlib import Path
import ast
import json
import sqlite3
import subprocess
import sys
import time
import pytest
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.device_manager.models import DeviceConfigurationSnapshot
from culsma_os.program_manager.models import HostBuildContext
from culsma_os.resource_manager.interactors import StationPathInteractor
from culsma_os.storage import ReadOnlyDatabaseSnapshot
from tests.support.integration.resident_host import ResidentHarness, GateSessionFactory
from tests.support.integration.resident_docking import ResidentDockingHarness, ObservedMotionFactory


class InspectionFixture:
    def __init__(self, directory):
        self.context = HostBuildContext(directory/'os.sqlite3', 'must-not-load', None, directory/'unused')
        self.station = StationPathInteractor().database_path(self.context)
        self.station.parent.mkdir(parents=True, exist_ok=True)
        self.device = DeviceConfigurationSnapshot('test', 'simulation', 'r1', ('simulation:test:gantry',),
            consumable_capacities={'tips':96}, motion_capabilities={'initial_locations':{'plate':'D1'}})
        with sqlite3.connect(self.context.database_path) as connection:
            connection.executescript('''
                CREATE TABLE os_devices(device_id PRIMARY KEY,snapshot);
                CREATE TABLE os_attempts(attempt_id PRIMARY KEY,effect_id,record);
                CREATE TABLE os_evidence(evidence_id PRIMARY KEY,effect_id,record);
                CREATE TABLE os_labware_positions(device_id PRIMARY KEY,configuration_revision,revision,positions);
                CREATE TABLE os_motion_registrations(effect_id PRIMARY KEY,record);
                CREATE TABLE os_resource_locks(resource_id PRIMARY KEY,attempt_id);
                CREATE TABLE os_permits(attempt_id PRIMARY KEY,effect_id,resources,status);
            ''')
            connection.execute('INSERT INTO os_devices VALUES(?,?)', ('test',json.dumps(asdict(self.device))))
        with sqlite3.connect(self.station) as connection:
            connection.executescript('''
                CREATE TABLE os_run_reservations(run_id PRIMARY KEY,record);
                CREATE TABLE os_run_resources(resource_id PRIMARY KEY,run_id);
                CREATE TABLE os_station_usage(evidence_id PRIMARY KEY,device_id,consumption);
            ''')
        self.inspector = OSApplicationFactory({}).build_device_inspector(self.context)

    def query(self):
        return self.inspector.execute()

    def attempt(self, effect='move', outcome=None, consumption=None, kind='labware_move', registered=False):
        intent = {'step_id':'entry.s1/motion/0','labware':'plate','source':'D1','destination':'module:heater',
                  'position_revision':0, 'carrier':{'namespace':'entry','carrier_id':'p'}}
        attempt = {'attempt_id':effect+'-attempt','run_id':'run','effect_id':effect,'mode':'simulation',
                   'context':{'device_id':'test','configuration_revision':'r1','step_id':'entry.s1',
                              'description':{'operation_kind':kind,'motion_intent':intent}}}
        with sqlite3.connect(self.context.database_path) as connection:
            connection.execute('INSERT INTO os_attempts VALUES(?,?,?)',
                               (attempt['attempt_id'],effect,json.dumps(attempt)))
            if outcome:
                evidence = {'evidence_id':effect+'-evidence','effect_id':effect,'attempt_id':attempt['attempt_id'],
                    'run_id':'run','mode':'simulation','outcome':outcome,'payload':{},'consumed_resources':consumption or {}}
                connection.execute('INSERT INTO os_evidence VALUES(?,?,?)',
                                   (evidence['evidence_id'],effect,json.dumps(evidence)))
            if registered:
                connection.execute('INSERT INTO os_labware_positions VALUES(?,?,?,?)',
                    ('test','r1',1,json.dumps({'plate':'module:heater'})))
                connection.execute('INSERT INTO os_motion_registrations VALUES(?,?)',
                    (effect,json.dumps({'effect_id':effect,'evidence_id':effect+'-evidence','intent':intent})))

    def usage(self, evidence, amount):
        with sqlite3.connect(self.station) as connection:
            connection.execute('INSERT INTO os_station_usage VALUES(?,?,?)',
                               (evidence,'test',json.dumps({'tips':amount})))

    def dump(self):
        result = []
        for path in (self.context.database_path,self.station):
            with sqlite3.connect(path) as connection:
                result.append(tuple(connection.iterdump()))
        return result
