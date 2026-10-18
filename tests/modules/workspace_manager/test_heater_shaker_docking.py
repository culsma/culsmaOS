from tests.support.paths import ROOT
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import ast
import json
import subprocess
import sys
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from tests.support.workspace_manager.labware_motion import MotionFixture
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture, BUFFER
from tests.support.workspace_manager.heater_shaker_docking import BASE, HEAT, SHAKE, TAIL, SOURCE, HeaterShakerDockingFixture


@pytest.mark.parametrize('shake_only',[False,True])
def test_dock_heat_shake_undock_transfer(tmp_path, shake_only):
    plan, _, app = HeaterShakerDockingFixture().build(tmp_path, shake_only=shake_only)
    try:
        result = app.execute(plan, init_state(plan))
        assert result.ok, [d.to_dict() for d in result.diagnostics]
        baseline = run(plan, StubDriver(), init_state(plan))
        assert result.state.artifacts['material_state'] == baseline.state.artifacts['material_state']
        assert result.state.artifacts['protocol_outputs'] == baseline.state.artifacts['protocol_outputs']
        session = app.host.gateway.port.session
        assert len(session.motion.receipts) == 2 and len(session.agitation.receipts) == 1
        assert len(session.thermal.receipts) == (0 if shake_only else 1)
        assert len(session.backend.receipts) == 2
        commands = session.backend.protocol.commands()
        opens = [i for i,c in enumerate(commands) if c == 'Unlatching labware on Heater-Shaker']
        moves = [i for i,c in enumerate(commands) if 'with gripper' in c]
        closes = [i for i,c in enumerate(commands) if c == 'Latching labware on Heater-Shaker']
        shake = next(i for i,c in enumerate(commands) if 'Shake at 500 RPM' in c)
        stopped = next(i for i,c in enumerate(commands) if 'Deactivating Shaker' in c)
        assert opens[0] < moves[0] < closes[0] < shake < stopped < opens[1] < moves[1]
        if not shake_only:
            heat_done = next(i for i,c in enumerate(commands) if 'Deactivating Heater' in c)
            assert heat_done < shake
        identity = result.user_result['os']['run_id']
        assert app.host.material.get(identity)[2] == (3 if shake_only else 4)
        motion = app.client.lifecycle.operations.motions.motion
        assert motion.positions()[0] == 2 and motion.positions()[1]['assay'] == 'D1'
        attempts = app.client.lifecycle.evidence.attempts_for_run(identity)
        assert len(attempts) == (5 if shake_only else 6)
        for attempt in attempts:
            if motion.is_move_attempt(attempt):
                evidence = app.client.lifecycle.evidence.find_evidence(attempt.effect_id)
                assert attempt.context['description']['required_access'] == evidence.payload['completed_access']
        assert not session.backend.module_access.active
        assert not app.client.lifecycle.operations.resource.occupied()
    finally: app.close()


@pytest.mark.parametrize('entry',['language','os'])
def test_cli_complete_docking_chain(tmp_path, entry):
    plan, _, app = HeaterShakerDockingFixture().build(tmp_path)
    app.close()
    (tmp_path/'protocol.culs').write_text(SOURCE)
    artifacts = tmp_path/'cli-artifacts'
    completed = subprocess.run([sys.executable,'-m','culsma.cli' if entry == 'language' else 'culsma_os.cli',
        'run',str(tmp_path/'protocol.culs'),'--driver','opentrons-simulator','--driver-config',str(tmp_path/'deck.json'),
        '--artifacts-dir',str(artifacts)],capture_output=True,text=True,timeout=45)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads((artifacts/'run.json').read_text())
    assert result['ok'] and result['user_result']['os']['registered_material']['version'] == 4


@pytest.mark.parametrize('stage',['open-before','open-after','move-after'])
def test_unknown_latch_or_motion_blocks_processing(tmp_path, monkeypatch, stage):
    plan, context, app = HeaterShakerDockingFixture().build(tmp_path)
    identity, _ = MotionFixture().waiting(app, plan)
    session = app.host.gateway.port.session
    owner = session.backend.protocol if stage == 'move-after' else session.backend.modules['heater']
    method = 'move_labware' if stage == 'move-after' else 'open_labware_latch'
    original = getattr(owner,method)
    def lost(*args,**kwargs):
        if stage != 'open-before': original(*args,**kwargs)
        raise TimeoutError('completion lost')
    monkeypatch.setattr(owner,method,lost)
    try:
        assert app.client.run_until_settled(identity).status == 'needs_reconciliation'
        assert not session.thermal.receipts and not session.agitation.receipts
        assert len(session.backend.receipts) == 1
        assert app.client.lifecycle.operations.motions.motion.positions()[0] == 0
        assert app.client.lifecycle.operations.resource.occupied()
        receipt = session.motion.receipts[0]
        assert receipt.payload['phases']['move'] == ('started' if stage == 'move-after' else 'not_started')
    finally: app.close()
    restarted = OSApplicationFactory().build(context)
    try:
        restarted.client.take_over_run(identity); restarted.client.start()
        assert restarted.client.run_until_settled(identity).status == 'needs_reconciliation'
        assert not restarted.host.gateway.port.session.backend.protocol.commands()
    finally: restarted.close()


@pytest.mark.parametrize('proof',['missing','different'])
def test_missing_access_evidence_never_registers_position(tmp_path, monkeypatch, proof):
    plan, context, app = HeaterShakerDockingFixture().build(tmp_path)
    identity, _ = MotionFixture().waiting(app, plan)
    original = app.host.gateway.execute
    def incomplete(plan,permit,attempt_id):
        receipt = original(plan,permit,attempt_id)
        if plan.description.get('operation_kind') == 'labware_move':
            payload = deepcopy(receipt.payload)
            if proof == 'missing': payload.pop('completed_access')
            else: payload['completed_access'] = ['another-access']
            return replace(receipt,payload=payload)
        return receipt
    monkeypatch.setattr(app.host.gateway,'execute',incomplete)
    try:
        assert app.client.run_until_settled(identity).status == 'needs_reconciliation'
        assert app.client.lifecycle.operations.motions.motion.positions()[0] == 0
        assert not app.host.gateway.port.session.thermal.receipts
        assert app.client.lifecycle.operations.resource.occupied()
    finally: app.close()
    restarted = OSApplicationFactory().build(context)
    try:
        restarted.client.take_over_run(identity); restarted.client.start()
        assert restarted.client.run_until_settled(identity).status == 'needs_reconciliation'
        assert not restarted.host.gateway.port.session.backend.protocol.commands()
    finally: restarted.close()


@pytest.mark.parametrize('move',[0,1])
@pytest.mark.parametrize('after_registration',[False,True])
def test_docking_restart_never_replays_completed_move(tmp_path, monkeypatch, move, after_registration):
    plan, context, app = HeaterShakerDockingFixture().build(tmp_path)
    identity, _ = MotionFixture().waiting(app, plan)
    motion = app.client.lifecycle.operations.motions.motion
    original = motion.register
    def interrupted(attempt,evidence):
        if attempt.context['description']['motion_intent']['position_revision'] == move:
            if after_registration: original(attempt,evidence)
            raise KeyboardInterrupt('saved movement completion')
        return original(attempt,evidence)
    monkeypatch.setattr(motion,'register',interrupted)
    try:
        with pytest.raises(KeyboardInterrupt): app.client.run_until_settled(identity)
    finally: app.close()
    restarted = OSApplicationFactory().build(context)
    try:
        session = restarted.host.gateway.port.session
        assert not session.backend.protocol.commands()
        if move == 0: assert session.backend.labware['assay'].parent is session.backend.module_adapters['heater']
        restarted.client.take_over_run(identity);restarted.client.start()
        assert restarted.client.run_until_settled(identity).status == 'completed'
        assert len(session.motion.receipts) == 1-move
        assert len(session.thermal.receipts) == 1-move
        assert len(session.agitation.receipts) == 1-move
        assert sum('Unlatching labware' in c for c in session.backend.protocol.commands()) == 1-move
        assert restarted.host.result(identity).state.artifacts['material_state'] == run(plan,StubDriver()).state.artifacts['material_state']
    finally: restarted.close()


@pytest.mark.parametrize('method',['deactivate_heater','deactivate_shaker'])
def test_unknown_processing_prevents_unload(tmp_path, monkeypatch, method):
    plan, _, app = HeaterShakerDockingFixture().build(tmp_path)
    session = app.host.gateway.port.session
    def unknown(): raise TimeoutError('stop unconfirmed')
    monkeypatch.setattr(session.backend.modules['heater'],method,unknown)
    try:
        result = app.execute(plan,init_state(plan))
        assert not result.ok and result.user_result['os']['status'] == 'needs_reconciliation'
        assert len(session.motion.receipts) == 1 and len(session.backend.receipts) == 1
        assert session.backend.labware['assay'].parent is session.backend.module_adapters['heater']
        assert session.backend.module_access.active
        assert app.client.lifecycle.operations.resource.occupied()
    finally: app.close()


def test_transfer_on_current_adapter_uses_latch_prerequisite(tmp_path):
    def change(raw): raw['labware_moves'].pop(next(reversed(raw['labware_moves'])))
    plan, _, app = HeaterShakerDockingFixture().build(tmp_path,change)
    try:
        result = app.execute(plan,init_state(plan))
        assert result.ok, result.diagnostics
        session = app.host.gateway.port.session
        assert session.backend.module_for_labware('assay') == 'heater'
        assert session.backend.receipts[-1].module_action_results[0]['action'] == 'close_labware_latch'
    finally: app.close()


def test_docking_architecture():
    root = ROOT/'src/culsma_os'
    source = (root/'workspace_manager/interactors.py').read_text()
    imports = [n.module or '' for n in ast.walk(ast.parse(source)) if isinstance(n,ast.ImportFrom)]
    assert not any(n.startswith(('opentrons','culsma_opentrons')) for n in imports)
    assert 'open_labware_latch' not in source
    assert 'required_access' in source and 'completed_access' in source


@pytest.mark.parametrize('stage',['open-before','open-after','move-after'])
def test_unknown_unload_preserves_docked_position(tmp_path, monkeypatch, stage):
    plan, context, app = HeaterShakerDockingFixture().build(tmp_path)
    session = app.host.gateway.port.session
    owner = session.backend.protocol if stage == 'move-after' else session.backend.modules['heater']
    method = 'move_labware' if stage == 'move-after' else 'open_labware_latch'
    original = getattr(owner,method)
    calls = 0
    def lost(*args,**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            if stage != 'open-before': original(*args,**kwargs)
            raise TimeoutError('unload completion unknown')
        return original(*args,**kwargs)
    monkeypatch.setattr(owner,method,lost)
    try:
        result = app.execute(plan,init_state(plan))
        identity = result.user_result['os']['run_id']
        assert result.user_result['os']['status'] == 'needs_reconciliation'
        assert app.client.lifecycle.operations.motions.motion.positions()[1]['assay'] == 'module:heater'
        assert len(session.backend.receipts) == 1
        assert app.client.lifecycle.operations.resource.occupied()
    finally: app.close()
    restarted = OSApplicationFactory().build(context)
    try:
        restarted.client.take_over_run(identity);restarted.client.start()
        assert restarted.client.run_until_settled(identity).status == 'needs_reconciliation'
        assert not restarted.host.gateway.port.session.backend.protocol.commands()
    finally: restarted.close()

