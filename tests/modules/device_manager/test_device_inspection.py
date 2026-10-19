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
from tests.support.device_manager.device_inspection import ROOT, InspectionFixture


def test_missing_stores_stay_absent_and_no_driver_is_loaded(tmp_path):
    context = HostBuildContext(tmp_path/'absent'/'os.sqlite3','does-not-exist',None,tmp_path/'unused',
                               station_root=tmp_path/'missing-station')
    inspector = OSApplicationFactory({}).build_device_inspector(context)
    result = inspector.execute()
    assert result['registration']=='not_recorded' and result['devices']==[]
    assert result['hardware_observed'] is False
    assert result['resources']['station_accounting']=='unavailable'
    assert not context.database_path.parent.exists() and not context.station_root.exists()


def test_schema_is_not_created_in_existing_empty_store(tmp_path):
    context=HostBuildContext(tmp_path/'empty.sqlite3','unused',None,tmp_path/'unused')
    sqlite3.connect(context.database_path).close()
    before=context.database_path.read_bytes()
    OSApplicationFactory({}).build_device_inspector(context).execute()
    assert context.database_path.read_bytes()==before
    with sqlite3.connect(context.database_path) as connection:
        assert not connection.execute('SELECT name FROM sqlite_master').fetchall()


def test_snapshot_is_read_only_and_consistent_during_writer_commit(tmp_path):
    path=tmp_path/'wal.sqlite3'
    with sqlite3.connect(path) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('CREATE TABLE records(value)')
        writer.execute('INSERT INTO records VALUES(1)');writer.commit()
        snapshot=ReadOnlyDatabaseSnapshot(path)
        with snapshot:
            with pytest.raises(sqlite3.OperationalError, match='readonly'):
                snapshot.connection.execute('DELETE FROM records')
            assert snapshot.rows('records','SELECT value FROM records')==((1,),)
            writer.execute('UPDATE records SET value=2');writer.commit()
            assert snapshot.rows('records','SELECT value FROM records')==((1,),)
        with snapshot:
            assert snapshot.rows('records','SELECT value FROM records')==((2,),)
        assert snapshot.connection is None


def test_known_consumption_deduplicates_station_without_writing_back(tmp_path):
    fixture=InspectionFixture(tmp_path)
    fixture.attempt('transfer','completed',{'tips':2},kind='transfer')
    fixture.usage('transfer-evidence',2)
    fixture.usage('other-run-evidence',3)
    before=fixture.dump()
    result=fixture.query()
    tips=result['devices'][0]['consumables']['tips']
    assert tips=={'configured_capacity':96,'known_consumed':5,'remaining_upper_bound':91,
                  'available_from_records':91,'status':'recorded'}
    assert fixture.dump()==before
    # A committed local receipt missing from the station is counted, never silently synchronized.
    with sqlite3.connect(fixture.station) as connection:
        connection.execute("DELETE FROM os_station_usage WHERE evidence_id='transfer-evidence'")
    before=fixture.dump()
    assert fixture.query()['devices'][0]['consumables']['tips']['known_consumed']==5
    assert fixture.dump()==before


@pytest.mark.parametrize('outcome,registered,expected', [
    (None,False,'unknown'),('unknown',False,'unknown'),('completed',False,'unknown'),
    ('completed',True,'registered'),('rejected',False,'configured')])
def test_position_requires_both_receipt_and_registration(tmp_path,outcome,registered,expected):
    fixture=InspectionFixture(tmp_path)
    fixture.attempt(outcome=outcome,registered=registered)
    before=fixture.dump()
    device=fixture.query()['devices'][0]
    assert device['positions']['status']==expected
    assert device['positions']['current']==(None if expected=='unknown' else
                                            {'plate':'module:heater' if registered else 'D1'})
    assert device['positions']['last_confirmed']==({'plate':'module:heater'} if registered else None)
    assert device['consumables']['tips']['available_from_records']==(None if expected=='unknown' else 96)
    assert fixture.dump()==before


def test_configuration_mismatch_keeps_last_position_but_not_current(tmp_path):
    fixture=InspectionFixture(tmp_path)
    fixture.attempt(outcome='completed',registered=True)
    with sqlite3.connect(fixture.context.database_path) as connection:
        connection.execute("UPDATE os_labware_positions SET configuration_revision='old'")
    positions=fixture.query()['devices'][0]['positions']
    assert positions['current'] is None and positions['last_confirmed']=={'plate':'module:heater'}
    assert 'configuration_mismatch' in positions['unresolved_motion']


def test_unknown_consumption_and_missing_station_never_show_exact_availability(tmp_path):
    fixture=InspectionFixture(tmp_path)
    fixture.attempt('transfer','unknown',{'tips':1},kind='transfer')
    tips=fixture.query()['devices'][0]['consumables']['tips']
    assert tips['known_consumed']==1 and tips['remaining_upper_bound']==95
    assert tips['available_from_records'] is None
    fixture.station.unlink()
    result=fixture.query()
    assert result['resources']['station_accounting']=='unavailable'
    assert result['devices'][0]['consumables']['tips']['available_from_records'] is None
    assert not fixture.station.exists()


def test_reserved_without_attempt_is_visible_and_conservative(tmp_path):
    fixture=InspectionFixture(tmp_path)
    with sqlite3.connect(fixture.context.database_path) as connection:
        connection.execute("INSERT INTO os_permits VALUES('preparing','effect','[]','reserved')")
        connection.execute("INSERT INTO os_resource_locks VALUES('gantry','preparing')")
    result=fixture.query()
    assert result['resources']['permits'][0]['status']=='reserved'
    assert result['resources']['locks'][0]['attempt_id']=='preparing'
    assert result['devices'][0]['consumables']['tips']['available_from_records'] is None


def test_resident_cli_before_admission_and_during_slow_device(tmp_path):
    sessions=GateSessionFactory()
    host=ResidentHarness(tmp_path,sessions).start()
    try:
        initial=host.client.execute({'action':'device-status'})
        assert initial['registration']=='not_recorded'
        assert len(sessions.ports)==1 and not sessions.ports[0].executions
        run_id=host.submit()['run_id']
        assert sessions.entered.wait(5)
        start=time.monotonic()
        result=host.client.execute({'action':'device-status'})
        assert time.monotonic()-start<1
        device=result['devices'][0]
        assert device['positions']['status']=='not_declared'
        assert device['unresolved_operations'][0]['status']=='awaiting_evidence'
        assert device['consumables']['tips']['available_from_records'] is None
        assert result['resources']['station_reservations'][0]['run_id']==run_id
        assert result['resources']['permits'][0]['status']=='authorized'
        completed=subprocess.run([sys.executable,'-m','culsma_os.cli','device-status','--socket',str(host.endpoint)],
                                 text=True,capture_output=True,timeout=5)
        assert completed.returncode==0,completed.stderr
        assert json.loads(completed.stdout)['devices'][0]['device_id']=='fake'
        assert len(sessions.ports)==1 and not sessions.ports[0].executions
        sessions.release.set()
        host.wait(lambda:host.status(run_id)['status']=='completed')
        result=host.client.execute({'action':'device-status'})
        assert not result['resources']['locks'] and not result['resources']['station_reservations']
        assert result['devices'][0]['consumables']['tips']['available_from_records']==94
    finally:host.stop()


@pytest.mark.parametrize('fault,position,unknown_motion',[
    ('move-after','D1',True),('heat-stop','module:heater',False)])
def test_real_simulator_unknown_query_survives_restart(tmp_path,fault,position,unknown_motion):
    probe=ObservedMotionFactory(fault=fault)
    host=ResidentDockingHarness(tmp_path,probe).start()
    try:
        run_id=host.submit()['run_id']
        host.wait(lambda:host.status(run_id)['status']=='needs_reconciliation')
        report=host.client.execute({'action':'device-status'})
        before=list(probe.dispatches)
        device=report['devices'][0]
        assert bool(device['positions']['unresolved_motion'])==unknown_motion
        known=device['positions']['last_confirmed'] or device['positions']['configured_initial']
        assert known['assay']==position
        if unknown_motion:
            assert device['positions']['current'] is None
        else:
            assert device['positions']['current']['assay']==position
        assert device['unresolved_operations'][-1]['status']=='unknown'
        assert device['consumables']['tips']['available_from_records'] is None
        assert probe.dispatches==before
    finally:host.stop()
    restarted=ResidentDockingHarness(tmp_path).start()
    try:
        result=restarted.client.execute({'action':'device-status'})
        assert result['devices']==report['devices']
        assert result['resources']['locks']==report['resources']['locks']
        assert not restarted.sessions.dispatches
    finally:restarted.stop()


def test_real_simulator_completed_queue_reports_registered_position_and_shared_tips(tmp_path):
    host=ResidentDockingHarness(tmp_path).start()
    try:
        host.submit()
        second=host.submit(host.second_source)['run_id']
        host.wait(lambda:host.status(second)['status']=='completed')
        host.wait(lambda:not host.client.execute({'action':'device-status'})['resources']['station_reservations'])
        before=list(host.sessions.dispatches)
        result=host.client.execute({'action':'device-status'})
        device=result['devices'][0]
        assert device['positions']['revision']==4 and device['positions']['current']['assay']=='D1'
        assert not device['unresolved_operations']
        assert device['consumables']['tips']['known_consumed']==4
        assert device['consumables']['tips']['available_from_records']==92
        assert not result['resources']['locks'] and not result['resources']['permits']
        assert host.sessions.dispatches==before
    finally:host.stop()


def test_inspection_ownership_and_read_only_architecture():
    files={
        'device_manager/repository.py':{'os_devices'},
        'workspace_manager/repository.py':{'os_layouts','os_labware_positions','os_motion_registrations','os_station_motion_intents','os_workspace_imports'},
        'resource_manager/repository.py':{'os_resource_locks','os_permits','os_run_reservations','os_run_resources','os_station_usage','os_run_releases'},
        'event_journal/repositories/inspection.py':{'os_attempts','os_evidence','os_logical_completions'},
        'material_system/repositories/inspection.py':{'os_material_changes'},
    }
    import re
    for path,owned in files.items():
        source=(ROOT/'src/culsma_os'/path).read_text()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node,ast.ClassDef) and 'Inspection' in node.name:
                sql=ast.get_source_segment(source,node)
                tables=set(re.findall(r'\bos_[a-z_]+\b',sql))
                assert tables<=owned,(path,tables-owned)
                assert not re.search(r'\b(CREATE|INSERT|UPDATE|DELETE|REPLACE)\b',sql)
    factory=ast.parse((ROOT/'src/culsma_os/bootstrap.py').read_text())
    builder=next(n for n in ast.walk(factory) if isinstance(n,ast.FunctionDef) and n.name=='build_device_inspector')
    assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in {'build','load'} for n in ast.walk(builder))
    assert 'ReadOnlyDatabaseSnapshot' in ast.unparse(builder)
    assert 'DatabaseConnection(' not in ast.unparse(builder)


@pytest.mark.parametrize('missing',['os_attempts','os_evidence','os_permits','os_resource_locks'])
def test_partial_schema_cannot_claim_exact_remaining_capacity(tmp_path,missing):
    fixture=InspectionFixture(tmp_path)
    with sqlite3.connect(fixture.context.database_path) as connection:
        connection.execute('DROP TABLE '+missing)
    result=fixture.query()
    assert result['devices'][0]['consumables']['tips']['available_from_records'] is None
    if missing in {'os_attempts','os_evidence'}:
        assert result['devices'][0]['evidence_accounting']=='unavailable'
    else:
        assert result['resources']['local_accounting']=='unavailable'


def test_other_run_store_cannot_establish_current_position_from_local_history(tmp_path):
    fixture=InspectionFixture(tmp_path)
    fixture.attempt(outcome='completed',registered=True)
    reservation={'run_id':'other-run','run_store':str(tmp_path/'other.sqlite3'),'status':'active'}
    with sqlite3.connect(fixture.station) as connection:
        connection.execute('INSERT INTO os_run_reservations VALUES(?,?)',('other-run',json.dumps(reservation)))
        connection.execute('INSERT INTO os_run_resources VALUES(?,?)',('simulation:test:gantry','other-run'))
    result=fixture.query()
    device=result['devices'][0]
    assert device['positions']['last_confirmed']=={'plate':'module:heater'}
    assert device['positions']['current'] is None
    assert 'external_run_store_active' in device['positions']['unresolved_motion']
    assert device['consumables']['tips']['available_from_records'] is None


def test_paused_resident_query_preserves_position_and_reservation(tmp_path):
    probe=ObservedMotionFactory(gate_kind='PreparedTemperatureHold')
    host=ResidentDockingHarness(tmp_path,probe).start()
    try:
        run_id=host.submit()['run_id']
        assert probe.entered.wait(5)
        host.client.execute({'action':'pause','run_id':run_id})
        probe.release.set()
        host.wait(lambda:host.status(run_id)['status']=='paused')
        before=list(probe.dispatches)
        result=host.client.execute({'action':'device-status'})
        assert result['devices'][0]['positions']['current']['assay']=='module:heater'
        assert result['resources']['station_reservations'][0]['run_id']==run_id
        assert host.status(run_id)['status']=='paused' and probe.dispatches==before
    finally:host.stop()


def test_released_foreign_store_history_is_not_mistaken_for_current_local_position(tmp_path):
    fixture=InspectionFixture(tmp_path)
    fixture.attempt(outcome='completed',registered=True)
    with sqlite3.connect(fixture.station) as connection:
        connection.execute('INSERT INTO os_run_reservations VALUES(?,?)', ('released-other', json.dumps(
            {'run_id':'released-other','status':'released','run_store':str(tmp_path/'other.sqlite3')})))
    result=fixture.query()
    positions=result['devices'][0]['positions']
    assert positions['last_confirmed']=={'plate':'module:heater'}
    assert positions['current'] is None
    assert 'external_run_store_history' in positions['unresolved_motion']
    assert not result['resources']['station_reservations']


def test_snapshot_requires_a_read_scope_even_when_store_is_missing(tmp_path):
    snapshot=ReadOnlyDatabaseSnapshot(tmp_path/'missing.sqlite3')
    with pytest.raises(RuntimeError,match='READ_SNAPSHOT_NOT_OPEN'):
        snapshot.rows('unused','SELECT 1')
    with snapshot:
        with pytest.raises(RuntimeError,match='READ_SNAPSHOT_ALREADY_OPEN'):
            with snapshot:pass
        assert snapshot.rows('unused','SELECT 1')==()
    assert not snapshot.active and not snapshot.path.exists()


def test_failed_query_closes_read_transaction_without_changing_records(tmp_path,monkeypatch):
    fixture=InspectionFixture(tmp_path)
    before=fixture.dump()
    def unavailable(*args):raise ValueError('test observation failure')
    with monkeypatch.context() as change:
        change.setattr(fixture.inspector.workspace,'inspect',unavailable)
        with pytest.raises(ValueError,match='test observation failure'):
            fixture.query()
    assert fixture.inspector.snapshot.connection is None and not fixture.inspector.snapshot.active
    assert fixture.query()['registration']=='recorded'
    assert fixture.dump()==before


def test_mismatched_receipt_is_not_accepted_as_confirmed_device_evidence(tmp_path):
    fixture=InspectionFixture(tmp_path)
    fixture.attempt('transfer','completed',{'tips':2},kind='transfer')
    with sqlite3.connect(fixture.context.database_path) as connection:
        record=json.loads(connection.execute('SELECT record FROM os_evidence').fetchone()[0])
        record['run_id']='wrong-run'
        connection.execute('UPDATE os_evidence SET record=?',(json.dumps(record),))
    device=fixture.query()['devices'][0]
    assert device['unresolved_operations'][0]['status']=='awaiting_evidence'
    assert device['consumables']['tips']['known_consumed']==0
    assert device['consumables']['tips']['available_from_records'] is None

