"""Transfer conformance through real official API contexts, not fake hardware ports."""

from copy import deepcopy
from dataclasses import dataclass
from itertools import product
from math import ceil, nextafter
from pathlib import Path
import json
import sqlite3
import subprocess
import sys
import pytest
from culsma.driver.stub import StubDriver
from culsma.frontend.resolver import resolve_files
from culsma.pipeline.compile import compile_ast
from culsma.pipeline.entrypoints import resolve_entry
from culsma.pipeline.plan import lower_ir_to_plan
from culsma.pipeline.typecheck import typecheck
from culsma.pipeline.validate import validate
from culsma.runtime.executor import run
from culsma.runtime.state import init_state
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.program_manager.models import HostBuildContext


BUFFER = 'content(kind = formulation, type = buffer, code = "BUFFER")'


CELLS = 'content(kind = bio_cellular, type = cell_line, code = "RPE1")'


MEDIUM = 'content(kind = formulation, type = medium, code = "MEDIUM")'


PIPETTES = {'p20_single_gen2': (1, 20, 'opentrons_96_tiprack_20ul'), 'p300_single_gen2': (20, 300, 'opentrons_96_tiprack_300ul')}


@dataclass(frozen=True)
class TransferCase:
    name: str
    body: str
    expected: tuple[float, ...]
    strokes: tuple[float, ...]
    load: str = f'{BUFFER}:200uL'
    declarations: str = ''
    policy: str = 'single'
    pipette: str = 'p300_single_gen2'


SHAPES = (
    TransferCase('whole-liquid', 'target << [source];', (0, 200), (200,)),
    TransferCase('whole-after-partial', 'target << [source:50uL]; target << [source];', (0, 200), (50, 150)),
    TransferCase('whole-split', 'target << [source];', (0, 610), (610/3, 610/3, 610-2*(610/3)), load=f'{BUFFER}:610uL', policy='balanced_split'),
    TransferCase('alias-source', 'let alias = source; target << [alias:50uL];', (150, 50), (50,)),
    TransferCase('alias-target', 'let alias = target; alias << [source:50uL];', (150, 50), (50,)),
    TransferCase('expression', 'target << [source:(100uL + 0.1mL) / 4];', (150, 50), (50,)),
    TransferCase('bound-quantity', 'let total = 0.1mL; let amount = total / 2; target << [source:amount];', (150, 50), (50,)),
    TransferCase('same-source-twice', 'target << [source:50uL, source:75uL];', (75, 125), (50, 75)),
    TransferCase('mixed-whole-and-quantity', 'target << [source:50uL, source];', (0, 200), (50, 150)),
    TransferCase('many-to-one', 'target << [source:50uL, second:100uL];', (150, 150, 100), (50, 100), declarations=f'let second = tube(capacity = 2000uL, load = [{BUFFER}:200uL]);'),
    TransferCase('one-to-many', 'target << [source:50uL]; second << [source:75uL];', (75, 50, 75), (50, 75), declarations='let second = tube(capacity = 2000uL);'),
    TransferCase('serial-dilution', 'target << [source:100uL]; second << [target:100uL];', (100, 200, 300), (100, 100), declarations=f'let second = tube(capacity = 2000uL, load = [{BUFFER}:200uL]);', load=f'{BUFFER}:200uL'),
    TransferCase('round-trip', 'target << [source:50uL]; source << [target:20uL];', (170, 30), (50, 20)),
    TransferCase('cells-explicit-carrier', 'target << [source:25000cells];', (150, 50), (50,), load=f'{CELLS}:100000cells, {MEDIUM}:200uL'),
    TransferCase('cells-default-carrier', 'target << [source:25000cells];', (75, 25), (25,), load=f'{CELLS}:100000cells'),
    TransferCase('cells-all', 'target << [source:100000cells];', (0, 200), (200,), load=f'{CELLS}:100000cells, {MEDIUM}:200uL'),
    TransferCase('cells-quantity-arithmetic', 'let amount = 100000cells / 4; target << [source:amount];', (150, 50), (50,), load=f'{CELLS}:100000cells, {MEDIUM}:200uL'),
    TransferCase('whole-cell-suspension', 'target << [source];', (0, 200), (200,), load=f'{CELLS}:100000cells, {MEDIUM}:200uL'),
    TransferCase('volume-cell-suspension', 'target << [source:50uL];', (150, 50), (50,), load=f'{CELLS}:100000cells, {MEDIUM}:200uL'),
    TransferCase('near-total-actual-volume', 'target << [source:100uL];', (0, nextafter(100.0, 0)), (nextafter(100.0, 0),), load=f'{BUFFER}:{nextafter(100.0, 0)}uL'),
)


class TransferMatrixFixture:
    def compile(self, source, directory):
        path = directory / 'protocol.culs'
        path.write_text(source)
        compiled = compile_ast(resolve_files([path]).prepared_program)
        checked = validate(compiled.ir, analysis=compiled.analysis, enforce_binding=True)
        typed = typecheck(checked.ir, analysis=compiled.analysis)
        errors = [d for d in [*checked.diagnostics, *typed.diagnostics] if d.severity == 'error']
        assert not errors, [d.to_dict() for d in errors]
        plan = lower_ir_to_plan(typed.ir, analysis=compiled.analysis, entry_resolution=resolve_entry(typed.ir))
        assert not [d for d in plan.diagnostics if d.severity == 'error'], plan.diagnostics
        return plan

    def source(self, body, load=f'{BUFFER}:200uL', declarations='', target_load='', capacity=2000):
        extra = f', load = [{target_load}]' if target_load else ''
        return f'let source = tube(capacity = 2000uL, load = [{load}]); let target = tube(capacity = {capacity}uL{extra}); {declarations}\n{body}'

    def context(self, directory, plan, pipette='p300_single_gen2', policy='single', config_mutation=None):
        allocations = [s for p in plan.plans for s in p.steps if s.op == 'AllocContainer']
        config = {
            'robot_type': 'OT-2', 'api_level': '2.20', 'pipette': pipette, 'mount': 'right',
            'tiprack': {'load_name': PIPETTES[pipette][2], 'slot': '2'},
            'labware': {'tubes': {'load_name': 'opentrons_24_tuberack_eppendorf_2ml_safelock_snapcap', 'slot': '1'}},
            'bindings': {s.step_id: {'labware': 'tubes', 'well': f'{chr(65+i//6)}{i%6+1}'} for i, s in enumerate(allocations)},
            'transfer_policy': {'stroke_mode': policy},
        }
        if config_mutation:
            config_mutation(config)
        path = directory / 'deck.json'
        path.write_text(json.dumps(config))
        return HostBuildContext(directory / 'os.sqlite3', 'opentrons-simulator', path, directory / 'artifacts')

    def volumes(self, result):
        return tuple(c['volume_uL'] for c in result.state.artifacts['material_state']['containers'].values())

    def assert_completed(self, app, plan, result, expected, strokes):
        assert result.ok, [d.to_dict() for d in result.diagnostics]
        assert result.user_result['os']['status'] == 'completed'
        assert self.volumes(result) == pytest.approx(expected)
        baseline = run(plan, StubDriver(), init_state(plan))
        assert baseline.ok
        assert result.state.artifacts['material_state'] == baseline.state.artifacts['material_state']
        backend = app.host.gateway.port.session.backend
        assert backend.protocol.is_simulating()
        receipts = backend.receipts
        commands = [c for r in receipts for c in r.operation.commands]
        assert [c.volume_uL for c in commands] == pytest.approx(strokes)
        assert all(backend.pipette.min_volume <= c.volume_uL <= backend.pipette.max_volume for c in commands)
        actions = [a for r in receipts for a in r.action_results]
        assert len(actions) == 4 * len(strokes) and all(a.status == 'returned' for a in actions)
        assert len({a.action_id for a in actions}) == len(actions)
        assert backend.available_tips() == 96 - len(strokes)
        assert not app.client.lifecycle.operations.resource.occupied()
        run_id = result.user_result['os']['run_id']
        assert app.host.material.get(run_id)[1] == result.state.artifacts['material_state']
        return {'status': 'completed', 'mode': 'simulation', 'volumes_uL': self.volumes(result), 'strokes_uL': [c.volume_uL for c in commands], 'receipts': len(receipts)}
