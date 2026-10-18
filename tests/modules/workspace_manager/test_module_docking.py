from tests.support.paths import ROOT
from pathlib import Path
import ast
import pytest
from culsma.driver.stub import StubDriver
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from tests.support.workspace_manager.labware_motion import MotionFixture
from tests.support.transfer_engine.transfer_matrix import TransferMatrixFixture, BUFFER
from tests.support.workspace_manager.module_docking import SOURCE, DockingFixture


@pytest.mark.parametrize('entry', ['direct','language-cli','os-cli'])
def test_dock_heat_undock_transfer(tmp_path, entry):
    plan, context, app = DockingFixture().build(tmp_path)
    if entry != 'direct':
        app.close()
        import subprocess, sys, json
        (tmp_path/'protocol.culs').write_text(SOURCE)
        module = 'culsma.cli' if entry == 'language-cli' else 'culsma_os.cli'
        completed = subprocess.run([sys.executable,'-m',module,'run',str(tmp_path/'protocol.culs'),
            '--driver','opentrons-simulator','--driver-config',str(tmp_path/'deck.json'),
            '--artifacts-dir',str(tmp_path/'cli-artifacts')],capture_output=True,text=True)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        return
    try:
        result = app.execute(plan, init_state(plan))
        assert result.ok, result.diagnostics
        baseline = run(plan, StubDriver(), init_state(plan))
        assert result.state.artifacts['material_state'] == baseline.state.artifacts['material_state']
        assert result.state.artifacts['protocol_outputs'] == baseline.state.artifacts['protocol_outputs']
        session = app.host.gateway.port.session
        assert len(session.motion.receipts) == 2 and len(session.thermal.receipts) == 1
        assert len(session.backend.receipts) == 2
        commands = session.backend.protocol.commands()
        enter = next(i for i,c in enumerate(commands) if 'with gripper' in c)
        heat = next(i for i,c in enumerate(commands) if 'Setting Temperature Module' in c)
        stop = next(i for i,c in enumerate(commands) if 'Deactivating Temperature Module' in c)
        leave = next(i for i,c in enumerate(commands) if 'slot D1 with gripper' in c)
        assert enter < heat < stop < leave
        run_id = result.user_result['os']['run_id']
        assert len(app.client.lifecycle.evidence.attempts_for_run(run_id)) == 5
        assert app.host.material.get(run_id)[2] == 3
        assert app.client.lifecycle.operations.motions.motion.positions()[0] == 2
        assert not app.client.lifecycle.operations.resource.occupied()
    finally: app.close()


@pytest.mark.parametrize('problem', ['off-module','occupied-module','undock-too-early'])
def test_preflight_rejects_processing_off_module(tmp_path, problem):
    def change(raw):
        if problem == 'off-module': raw['labware_moves'] = {next(reversed(raw['labware_moves'])):raw['labware_moves'][next(reversed(raw['labware_moves']))]}
        if problem == 'occupied-module': raw['labware']['parked'] = {'load_name':'nest_96_wellplate_200ul_flat','module':'heater'}
        if problem == 'undock-too-early':
            hold = next(iter(raw['labware_moves']))
            raw['labware_moves'][hold].append({'labware':'assay','destination':'D2'})
    plan, _, app = DockingFixture().build(tmp_path, change)
    try:
        result = app.execute(plan, init_state(plan))
        assert not result.ok
        assert result.user_result['os']['preflight']['status'] == 'rejected'
        assert not app.host.gateway.port.session.backend.protocol.commands()
        assert not app.client.lifecycle.evidence.attempts_for_run(result.user_result['os']['run_id'])
    finally: app.close()


@pytest.mark.parametrize('move', [0,1])
def test_docked_restart_repairs_without_replay(tmp_path, monkeypatch, move):
    plan, context, app = DockingFixture().build(tmp_path)
    identity, _ = MotionFixture().waiting(app, plan)
    motion = app.client.lifecycle.operations.motions.motion
    original = motion.register
    def crash(attempt, evidence):
        if attempt.context['description']['motion_intent']['position_revision'] == move:
            raise KeyboardInterrupt('after completed docking movement')
        return original(attempt, evidence)
    monkeypatch.setattr(motion,'register',crash)
    try:
        with pytest.raises(KeyboardInterrupt): app.client.run_until_settled(identity)
        assert len(app.host.gateway.port.session.thermal.receipts) == move
    finally: app.close()
    restarted = OSApplicationFactory().build(context)
    try:
        session = restarted.host.gateway.port.session
        if move == 0: assert session.backend.labware['assay'].parent is session.backend.modules['heater']
        else: assert str(session.backend.labware['assay'].parent) == 'D1'
        assert not session.backend.protocol.commands()
        restarted.client.take_over_run(identity)
        restarted.client.start()
        record = restarted.client.run_until_settled(identity)
        assert record.status == 'completed', record
        assert len(session.motion.receipts) == 1 - move
        assert len(session.thermal.receipts) == 1 - move
        assert restarted.host.result(identity).state.artifacts['material_state'] == run(plan, StubDriver()).state.artifacts['material_state']
    finally: restarted.close()


def test_unknown_docking_blocks_processing(tmp_path, monkeypatch):
    plan, context, app = DockingFixture().build(tmp_path)
    identity, _ = MotionFixture().waiting(app, plan)
    session = app.host.gateway.port.session
    original = session.backend.protocol.move_labware
    def lost(*args, **kwargs):
        original(*args, **kwargs)
        raise TimeoutError('docking completion unknown')
    monkeypatch.setattr(session.backend.protocol,'move_labware',lost)
    try:
        assert app.client.run_until_settled(identity).status == 'needs_reconciliation'
        assert not session.thermal.receipts and len(session.backend.receipts) == 1
        assert app.client.lifecycle.operations.resource.occupied()
        assert app.client.lifecycle.operations.motions.motion.positions()[0] == 0
    finally: app.close()
    restarted = OSApplicationFactory().build(context)
    try:
        restarted.client.take_over_run(identity)
        restarted.client.start()
        assert restarted.client.run_until_settled(identity).status == 'needs_reconciliation'
        assert not restarted.host.gateway.port.session.backend.protocol.commands()
    finally: restarted.close()


def test_docking_architecture():
    root = ROOT/'src/culsma_os'
    for path in ('workspace_manager/interactors.py','processing_engine/interactors/preparation.py'):
        names = [n.module or '' for n in ast.walk(ast.parse((root/path).read_text())) if isinstance(n, ast.ImportFrom)]
        assert not any(n.startswith(('opentrons','culsma_opentrons')) for n in names)
    source = (root/'processing_engine/interactors/preparation.py').read_text()
    assert 'placement: ProcessingPlacementPort' in source


def test_docking_preflight_is_read_only(tmp_path):
    from copy import deepcopy
    plan, _, app = DockingFixture().build(tmp_path)
    try:
        state = init_state(plan)
        before = deepcopy(state)
        motion = app.client.lifecycle.operations.motions.motion
        report, diagnostics = app.client.execution.host.preflight.inspect(plan, state, 'preview')
        assert not diagnostics and report['status'] == 'passed'
        assert state == before and motion.positions()[0] == 0
        assert motion.repository.get('opentrons') is None
        assert not app.host.gateway.port.session.backend.protocol.commands()
        with pytest.raises(ValueError, match='PROCESSING_LABWARE_NOT_DOCKED'):
            motion.require_module('assay','heater')
    finally: app.close()


def test_unknown_processing_blocks_undocking(tmp_path, monkeypatch):
    plan, _, app = DockingFixture().build(tmp_path)
    session = app.host.gateway.port.session
    def lost(): raise TimeoutError('temperature deactivation unknown')
    monkeypatch.setattr(session.backend.modules['heater'], 'deactivate', lost)
    try:
        result = app.execute(plan, init_state(plan))
        assert not result.ok
        assert app.client.get_run(result.user_result['os']['run_id']).status == 'needs_reconciliation'
        assert len(session.motion.receipts) == 1 and len(session.backend.receipts) == 1
        assert session.backend.labware['assay'].parent is session.backend.modules['heater']
        assert app.client.lifecycle.operations.motions.motion.positions()[0] == 1
        assert app.client.lifecycle.operations.resource.occupied()
    finally: app.close()

