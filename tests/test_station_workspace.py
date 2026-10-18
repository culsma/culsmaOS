"""One station placement ledger across separate program stores and artifact directories."""
from dataclasses import replace
from pathlib import Path
import json
import shutil
import sqlite3
import pytest
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import RunRequest
from culsma_os.resource_manager.interactors import StationPathInteractor
from .test_resident_docking import ResidentDockingHarness, ObservedMotionFactory
from .test_labware_motion import MotionFixture


class StationFixture:
    def query(self, context):
        return OSApplicationFactory({}).build_device_inspector(context).execute()

    def second(self, directory, context):
        return replace(context, database_path=directory/'second.sqlite3', artifacts_dir=directory/'second-artifacts')

    def emulate_legacy_store(self, context):
        station=StationPathInteractor().database_path(context)
        shared=StationPathInteractor().device_state_directory(context)/'motion-state.json'
        legacy=context.artifacts_dir/'motion-state.json'
        legacy.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(shared,legacy)
        shared.unlink()
        with sqlite3.connect(station) as source, sqlite3.connect(context.database_path) as target:
            for table in ('os_labware_positions','os_motion_registrations'):
                schema=source.execute('SELECT sql FROM sqlite_master WHERE name=?',(table,)).fetchone()[0]
                target.execute(schema)
                rows=source.execute('SELECT * FROM '+table).fetchall()
                if rows:
                    target.executemany('INSERT INTO '+table+' VALUES('+','.join('?' for _ in rows[0])+')',rows)
                source.execute('DELETE FROM '+table)
            source.execute('DELETE FROM os_station_motion_intents')
            source.execute('DELETE FROM os_workspace_imports')
        return legacy


def test_two_run_stores_and_artifact_directories_share_position_and_tip_history(tmp_path):
    plan,context,first=MotionFixture().build(tmp_path)
    try:
        result=first.execute(plan,init_state(plan))
        assert result.ok
        assert first.client.lifecycle.operations.motions.motion.positions()[0]==2
    finally:first.close()
    second_context=StationFixture().second(tmp_path,context)
    second=OSApplicationFactory().build(second_context)
    try:
        session=second.host.gateway.port.session
        assert session.motion.state['revision']==2 and not session.backend.protocol.commands()
        second.client.start()
        before=StationFixture().query(second_context)
        device=before['devices'][0]
        assert device['positions']['scope']=='station'
        assert device['positions']['current']['assay']=='D1' and device['positions']['revision']==2
        assert device['consumables']['tips']['known_consumed']==2
        assert not second_context.artifacts_dir.joinpath('motion-state.json').exists()
        result=second.execute(plan,init_state(plan))
        assert result.ok,[d.to_dict() for d in result.diagnostics]
        after=StationFixture().query(second_context)
        assert after['devices'][0]['positions']['revision']==4
        assert after['devices'][0]['consumables']['tips']['known_consumed']==4
        assert len(session.motion.receipts)==2
        # No implicit copying of program state into the station or the new run store.
        with sqlite3.connect(second_context.database_path) as db:
            assert db.execute('SELECT count(*) FROM os_runs').fetchone()[0]==1
            assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='os_labware_positions'").fetchone()
    finally:second.close()


def test_cancelled_plate_position_survives_new_store_without_commands(tmp_path):
    probe=ObservedMotionFactory(gate_kind='PreparedTemperatureHold')
    host=ResidentDockingHarness(tmp_path,probe).start()
    try:
        run_id=host.submit()['run_id']
        assert probe.entered.wait(5)
        host.client.execute({'action':'pause','run_id':run_id});probe.release.set()
        host.wait(lambda:host.status(run_id)['status']=='paused')
        host.client.execute({'action':'cancel','run_id':run_id})
        host.wait(lambda:host.status(run_id)['status']=='cancelled')
    finally:host.stop()
    context=StationFixture().second(tmp_path,host.context)
    second=OSApplicationFactory().build(context)
    try:
        session=second.host.gateway.port.session
        assert session.backend.module_for_labware('assay')=='heater'
        assert not session.backend.protocol.commands()
        second.client.start()
        report=StationFixture().query(context)
        assert report['devices'][0]['positions']['current']['assay']=='module:heater'
        assert report['devices'][0]['positions']['revision']==1
        # The same route assumes the dock is vacant: current shared placement rejects it.
        from culsma_os.program_manager.interactors.compilation import CompilationInteractor
        compiled=CompilationInteractor().compile([host.first_source],None,())
        result=second.execute(compiled.plan,compiled.state)
        assert not result.ok and 'MOTION_DESTINATION_OCCUPIED' in str(result.diagnostics)
        assert not session.backend.protocol.commands()
    finally:second.close()


def test_unknown_move_is_visible_and_blocks_a_different_run_store(tmp_path):
    probe=ObservedMotionFactory(fault='move-after')
    host=ResidentDockingHarness(tmp_path,probe).start()
    try:
        first=host.submit()['run_id']
        host.wait(lambda:host.status(first)['status']=='needs_reconciliation')
    finally:host.stop()
    context=StationFixture().second(tmp_path,host.context)
    second=OSApplicationFactory().build(context)
    try:
        session=second.host.gateway.port.session
        second.client.start()
        report=StationFixture().query(context)
        pose=report['devices'][0]['positions']
        assert pose['scope']=='station' and pose['current'] is None
        assert pose['pending_motion'][0]['run_id']==first
        assert pose['pending_motion'][0]['status']=='unknown'
        assert pose['pending_motion'][0]['run_store']==str(host.context.database_path.resolve())
        with pytest.raises(ValueError,match='UNCONFIRMED'):
            second.client.lifecycle.operations.motions.motion.require_known()
        assert not session.backend.protocol.commands()
        assert report['resources']['station_reservations'][0]['run_id']==first
    finally:second.close()


def test_legacy_adoption_preserves_proofs_and_never_overwrites_newer_station_positions(tmp_path):
    plan,context,app=MotionFixture().build(tmp_path)
    try:
        result=app.execute(plan,init_state(plan))
        assert result.ok
        run_id=result.user_result['os']['run_id']
        original_material=app.host.material.get(run_id)
    finally:app.close()
    old_file=StationFixture().emulate_legacy_store(context)
    before=old_file.read_bytes()
    resumed=OSApplicationFactory().build(context)
    try:
        assert not resumed.host.gateway.port.session.backend.protocol.commands()
        resumed.client.start()
        motion=resumed.client.lifecycle.operations.motions.motion
        assert motion.positions()[0]==2
        assert resumed.host.material.get(run_id)==original_material
        assert resumed.execute(plan,init_state(plan)).ok
        assert motion.positions()[0]==4
    finally:resumed.close()
    assert old_file.read_bytes()==before
    fresh=OSApplicationFactory().build(context)
    try:
        fresh.client.start()
        assert fresh.client.lifecycle.operations.motions.motion.positions()[0]==4
        assert fresh.host.gateway.port.session.motion.state['revision']==4
        assert not fresh.host.gateway.port.session.backend.protocol.commands()
    finally:fresh.close()


def test_legacy_unknown_intent_and_vendor_uncertainty_are_both_adopted(tmp_path,monkeypatch):
    plan,context,app=MotionFixture().build(tmp_path)
    backend=app.host.gateway.port.session.backend
    original=backend.protocol.move_labware
    def lost(*args,**kwargs):
        original(*args,**kwargs)
        raise TimeoutError('lost move feedback')
    monkeypatch.setattr(backend.protocol,'move_labware',lost)
    try:
        result=app.execute(plan,init_state(plan))
        assert not result.ok
        run_id=result.user_result['os']['run_id']
    finally:app.close()
    StationFixture().emulate_legacy_store(context)
    resumed=OSApplicationFactory().build(context)
    try:
        resumed.client.start()
        report=StationFixture().query(context)
        assert report['devices'][0]['positions']['current'] is None
        assert report['devices'][0]['positions']['pending_motion'][0]['run_id']==run_id
        assert resumed.host.gateway.port.session.motion.state['uncertain']
        assert not resumed.host.gateway.port.session.backend.protocol.commands()
    finally:resumed.close()


def test_legacy_conflict_leaves_authoritative_station_position_unchanged(tmp_path):
    plan,context,app=MotionFixture().build(tmp_path)
    try:assert app.execute(plan,init_state(plan)).ok
    finally:app.close()
    StationFixture().emulate_legacy_store(context)
    app=OSApplicationFactory().build(context)
    try:app.client.start()
    finally:app.close()
    with sqlite3.connect(context.database_path) as db:
        db.execute('UPDATE os_labware_positions SET revision=3')
    app=OSApplicationFactory().build(context)
    try:
        with pytest.raises(ValueError,match='LEGACY_'):
            app.client.start()
        assert app.client.lifecycle.operations.motions.motion.positions()[0]==2
        assert not app.host.gateway.port.session.backend.protocol.commands()
    finally:app.close()


def test_ambiguous_preupgrade_foreign_history_is_not_guessed(tmp_path):
    plan,context,app=MotionFixture().build(tmp_path)
    try:assert app.execute(plan,init_state(plan)).ok
    finally:app.close()
    StationFixture().emulate_legacy_store(context)
    foreign=StationFixture().second(tmp_path,context)
    app=OSApplicationFactory().build(foreign)
    try:
        with pytest.raises(ValueError,match='STATION_WORKSPACE_LEGACY_AMBIGUOUS'):
            app.client.start()
        assert not app.host.gateway.port.session.backend.protocol.commands()
    finally:app.close()


def test_station_motion_intent_exists_before_vendor_dispatch(tmp_path,monkeypatch):
    plan,context,app=MotionFixture().build(tmp_path)
    session=app.host.gateway.port.session
    original=session.execute_labware_move
    observed=[]
    def audit(prepared):
        report=StationFixture().query(context)
        pending=report['devices'][0]['positions']['pending_motion']
        assert len(pending)==1 and pending[0]['status']=='awaiting_evidence'
        assert report['devices'][0]['positions']['current'] is None
        observed.append(pending[0]['effect_id'])
        return original(prepared)
    monkeypatch.setattr(session,'execute_labware_move',audit)
    try:
        assert app.execute(plan,init_state(plan)).ok
        assert len(observed)==2
        assert not StationFixture().query(context)['devices'][0]['positions']['pending_motion']
    finally:app.close()


def test_confirmed_rejection_clears_pending_without_changing_position(tmp_path,monkeypatch):
    from culsma_opentrons.models import TransferFeedback
    plan,context,app=MotionFixture().build(tmp_path)
    session=app.host.gateway.port.session
    def reject(prepared):
        return TransferFeedback('rejected','simulation',prepared.intent.step_id,
                                prepared.configuration_revision,{}, {'reason':'test rejected before movement'})
    monkeypatch.setattr(session,'execute_labware_move',reject)
    try:
        result=app.execute(plan,init_state(plan))
        assert not result.ok
        report=StationFixture().query(context)
        assert not report['devices'][0]['positions']['pending_motion']
        assert report['devices'][0]['positions']['revision']==0
        assert report['devices'][0]['positions']['current']['assay']=='D1'
        assert not report['resources']['station_reservations']
        assert not session.backend.protocol.commands()
    finally:app.close()


def test_local_intent_crash_before_station_write_is_recovered_without_dispatch(tmp_path,monkeypatch):
    plan,context,app=MotionFixture().build(tmp_path)
    def interrupt(*args,**kwargs):raise KeyboardInterrupt('before station intent')
    monkeypatch.setattr(app.client.lifecycle.operations.motions.motion,'record_intent',interrupt)
    try:
        with pytest.raises(KeyboardInterrupt):app.execute(plan,init_state(plan))
        assert not app.host.gateway.port.session.backend.protocol.commands()
    finally:app.close()
    resumed=OSApplicationFactory().build(context)
    try:
        resumed.client.start()
        report=StationFixture().query(context)
        assert len(report['devices'][0]['positions']['pending_motion'])==1
        assert report['devices'][0]['positions']['current'] is None
        assert not resumed.host.gateway.port.session.backend.protocol.commands()
    finally:resumed.close()


def test_route_free_profile_cannot_implicitly_reset_existing_station_placement(tmp_path):
    plan,context,app=MotionFixture().build(tmp_path)
    try:assert app.execute(plan,init_state(plan)).ok
    finally:app.close()
    config=json.loads(context.config_path.read_text());config['labware_moves']={}
    path=tmp_path/'without-routes.json';path.write_text(json.dumps(config))
    changed=replace(StationFixture().second(tmp_path,context),config_path=path)
    app=OSApplicationFactory().build(changed)
    try:
        with pytest.raises(ValueError,match='MOTION_CONFIGURATION_MISMATCH'):
            app.client.start()
        assert not app.host.gateway.port.session.backend.protocol.commands()
    finally:app.close()


def test_os_derives_state_directory_from_station_identity(tmp_path):
    plan,context,app=MotionFixture().build(tmp_path)
    try:assert app.execute(plan,init_state(plan)).ok
    finally:app.close()
    changed=replace(StationFixture().second(tmp_path,context),device_state_dir=tmp_path/'different-state')
    app=OSApplicationFactory().build(changed)
    try:
        assert app.host.gateway.port.session.motion.state['revision']==2
        assert not changed.device_state_dir.exists()
        assert not app.host.gateway.port.session.backend.protocol.commands()
    finally:app.close()


def test_equal_coordinates_do_not_merge_independent_legacy_proof_histories(tmp_path):
    from culsma_os.workspace_manager.repository import SqliteLabwarePositionRepository
    plan,context,app=MotionFixture().build(tmp_path)
    try:assert app.execute(plan,init_state(plan)).ok
    finally:app.close()
    with sqlite3.connect(StationPathInteractor().database_path(context)) as connection:
        repository=SqliteLabwarePositionRepository(connection,run_store=str(tmp_path/'foreign.sqlite3'))
        position=repository.get('opentrons')
        old=connection.execute('SELECT record FROM os_motion_registrations LIMIT 1').fetchone()[0]
        record={**json.loads(old),'effect_id':'independent-effect','evidence_id':'independent-evidence'}
        before=tuple(connection.iterdump())
        with pytest.raises(ValueError,match='STATION_WORKSPACE_PROOF_CONFLICT'):
            repository.adopt('opentrons',position,{'independent-effect':record},'independent-digest')
        assert tuple(connection.iterdump())==before
