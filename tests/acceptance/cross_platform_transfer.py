"""One immutable Culsma program and plan per paired OS acceptance scenario."""
import argparse
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys

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


class DispenseFailureInjector:
    """Test-only fault: throw before the chosen backend dispense call."""
    def __init__(self, owner, ordinal):
        self.owner, self.ordinal = owner, ordinal
        self.calls = 0

    def __enter__(self):
        self.original = self.owner.dispense
        self.owner.dispense = self.invoke
        return self

    def invoke(self, *args, **kwargs):
        self.calls += 1
        if self.calls == self.ordinal:
            raise RuntimeError(f"acceptance injected failure before dispense {self.ordinal}")
        return self.original(*args, **kwargs)

    def __exit__(self, *exception):
        self.owner.dispense = self.original


class CrossPlatformTransferAcceptance:
    root = Path(__file__).resolve().parents[2]

    def __init__(self, fixture_dir=None):
        self.fixtures = fixture_dir or self.root / 'examples/cross-platform-transfer'
        self.manifest = json.loads((self.fixtures / 'manifest.json').read_text())

    def compile(self, path):
        compiled = compile_ast(resolve_files([path]).prepared_program)
        checked = validate(compiled.ir, analysis=compiled.analysis, enforce_binding=True)
        typed = typecheck(checked.ir, analysis=compiled.analysis)
        assert checked.ok and typed.ok, [d.to_dict() for d in (*checked.diagnostics, *typed.diagnostics)]
        plan = lower_ir_to_plan(typed.ir, analysis=compiled.analysis,
                               entry_resolution=resolve_entry(typed.ir))
        assert not plan.diagnostics
        return plan

    def fingerprint(self, value):
        return sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def quantities(self, state):
        return {c['metadata']['label']: c['volume_uL'] for c in state['containers'].values()}

    def backend_metrics(self, app, backend):
        port = app.host.gateway.port
        if backend == 'ot2':
            device = port.session.backend
            commands = list(device.protocol.commands())
            return {'log_level': 'official API requests, including failed requests',
                    'aspirate_requests': sum(c.startswith('Aspirating ') for c in commands),
                    'dispense_requests': sum(c.startswith('Dispensing ') for c in commands),
                    'receipt_count': len(device.receipts),
                    'commands': commands,
                    'independent_physical_volume_observation': False}
        frames = list(port.backend.frames)
        return {'log_level': 'third-party STAR protocol simulation exchanges',
                'aspirate_requests': sum(f['written'].startswith('C0AS') for f in frames),
                'dispense_requests': sum(f['written'].startswith('C0DS') for f in frames),
                'receipt_count': len(port.receipts), 'exchanges': frames,
                'simulator_volumes': port.backend.snapshot(),
                'independent_physical_volume_observation': False}

    def capture(self, app, result, backend):
        run_id = result.user_result['os']['run_id']
        evidence = app.client.lifecycle.evidence
        attempts = evidence.attempts_for_run(run_id)
        records = [evidence.find_evidence(a.effect_id) for a in attempts]
        try:
            mode, registered, material_version = app.host.material.get(run_id)
        except KeyError:
            mode, registered, material_version = 'simulation', None, 0
        reservation = app.client.lifecycle.reservations.get(run_id)
        return {'ok': result.ok, 'status': result.user_result['os']['status'],
                'mode': mode, 'run_id': run_id,
                'language_state': result.state.artifacts['material_state'],
                'registered_state': registered, 'material_version': material_version,
                'volumes': self.quantities(registered) if registered is not None else None,
                'diagnostics': [d.to_dict() for d in result.diagnostics],
                'uncertain_effects': list(app.host.material.uncertainties(run_id)),
                'occupied_resources': list(app.client.lifecycle.operations.resource.occupied()),
                'reservation_status': reservation.status if reservation else 'not_acquired',
                'consumption': evidence.known_consumption(app.client.lifecycle.device_id),
                'attempts': [asdict(a) for a in attempts],
                'evidence': [asdict(e) for e in records if e is not None],
                'device': self.backend_metrics(app, backend)}

    def execute_backend(self, scenario, backend, plan, directory):
        directory.mkdir(parents=True, exist_ok=True)
        profile = self.manifest['profiles'][backend]
        config = self.fixtures / f'{scenario["protocol"]}.{backend}.json'
        context = HostBuildContext(directory / 'os.sqlite3', profile, config,
                                   directory / 'artifacts', station_id='paired-acceptance',
                                   station_root=directory / 'station')
        app = OSApplicationFactory().build(context)
        try:
            owner = (app.host.gateway.port.session.backend.pipette if backend == 'ot2'
                     else app.host.gateway.port.backend)
            fault = (DispenseFailureInjector(owner, scenario['fail_dispense'])
                     if scenario['fail_dispense'] else nullcontext())
            with fault:
                result = app.execute(deepcopy(plan), init_state(plan))
            captured = self.capture(app, result, backend)
            captured['config_sha256'] = sha256(config.read_bytes()).hexdigest()
            captured['program_sha256'] = sha256((self.fixtures / f'{scenario["protocol"]}.culs').read_bytes()).hexdigest()
            captured['plan_sha256'] = self.fingerprint(plan.to_dict())
            if scenario['fail_dispense']:
                before = self.backend_metrics(app, backend)
                app.client.run_until_settled(captured['run_id'])
                after = self.backend_metrics(app, backend)
                assert before == after, 'Uncertain execution was replayed in the same session'
                captured['same_session_no_replay'] = True
        finally:
            app.close()
        if scenario['fail_dispense']:
            restarted = OSApplicationFactory().build(context)
            try:
                restarted.client.take_over_run(captured['run_id'])
                restarted.client.start()
                settled = restarted.client.run_until_settled(captured['run_id'])
                metrics = self.backend_metrics(restarted, backend)
                assert settled.status == 'needs_reconciliation'
                assert metrics['aspirate_requests'] == metrics['dispense_requests'] == 0
                assert metrics['receipt_count'] == 0
                assert restarted.client.lifecycle.operations.resource.occupied()
                captured['restart_no_replay'] = True
            finally:
                restarted.close()
        return captured

    def run_scenario(self, scenario, directory):
        path = self.fixtures / f'{scenario["protocol"]}.culs'
        source_hash = sha256(path.read_bytes()).hexdigest()
        plan = self.compile(path)
        reference = run(deepcopy(plan), StubDriver(), state=init_state(plan))
        assert reference.ok
        results = {backend: self.execute_backend(scenario, backend, plan, directory / backend)
                   for backend in self.manifest['profiles']}
        assert sha256(path.read_bytes()).hexdigest() == source_hash
        assert len({r['program_sha256'] for r in results.values()}) == 1
        assert len({r['plan_sha256'] for r in results.values()}) == 1
        self.verify(scenario, results, reference.state.artifacts['material_state'])
        output = {'scenario': scenario, 'program_sha256': source_hash,
                  'reference_state': reference.state.artifacts['material_state'],
                  'backends': results, 'checks': 'passed'}
        (directory / 'result.json').write_text(json.dumps(output, indent=2))
        return output

    def verify(self, scenario, results, reference):
        ot, star = results['ot2'], results['star']
        if scenario.get('expected_ot2_rejection'):
            assert not ot['ok'] and ot['status']=='failed'
            assert any(scenario['expected_ot2_rejection'] in d['message'] for d in ot['diagnostics'])
            assert ot['registered_state'] is None and not ot['attempts']
            assert not ot['occupied_resources'] and not ot['consumption']
            assert ot['device']['aspirate_requests']==ot['device']['dispense_requests']==0
            assert star['ok'] and star['registered_state']==reference
            assert not star['occupied_resources']
            return
        if not scenario['fail_dispense']:
            for result in results.values():
                assert result['ok'] and result['status'] == 'completed'
                assert result['language_state'] == result['registered_state'] == reference
                assert not result['occupied_resources'] and not result['uncertain_effects']
                assert result['reservation_status'] == 'released'
            expected = {'continuous-transfer': (2,2,2), 'unequal-eight-wells': (8,1,8),
                        'layout-splitting': (8,8,8)}[scenario['name']]
            for result, batches in [(ot,expected[0]), (star,expected[1])]:
                assert result['device']['aspirate_requests'] == result['device']['dispense_requests'] == batches
                assert result['consumption'] == {'tips': expected[2]}
            assert ot['registered_state'] == star['registered_state']
            if scenario['name'] == 'unequal-eight-wells':
                assert [star['volumes'][f'D{i}'] for i in range(8)] == list(range(20,100,10))
        else:
            for result in results.values():
                assert not result['ok'] and result['status'] == 'needs_reconciliation'
                assert result['occupied_resources'] and result['uncertain_effects']
                assert result['reservation_status'] == 'active'
                assert result['same_session_no_replay'] and result['restart_no_replay']
            if scenario['protocol'] == 'scalar':
                expected = {'Source':200,'Destination':0} if scenario['fail_dispense']==1 else {'Source':150,'Destination':50}
                assert ot['volumes'] == star['volumes'] == expected
                assert ot['registered_state'] == star['registered_state']
            else:
                # Existing OT single-channel flow registers confirmed members; STAR's
                # collective plan keeps all members uncertain until all batches finish.
                assert ot['volumes']['D0'] == 20 and star['volumes']['D0'] == 0
                assert all(ot['volumes'][f'D{i}'] == star['volumes'][f'D{i}'] == 0 for i in range(1,8))
                assert len(ot['uncertain_effects']) == 1 and len(star['uncertain_effects']) == 8
                assert ot['material_version'] == 1 and star['material_version'] == 0

    def cli_pair(self, directory):
        directory.mkdir(parents=True,exist_ok=True)
        records = {}
        source = self.fixtures / 'scalar.culs'
        for backend, profile in self.manifest['profiles'].items():
            work = directory / backend
            args = [sys.executable,'-m','culsma.cli','run',str(source),'--driver',profile,
                    '--driver-config',str(self.fixtures/f'scalar.{backend}.json'),
                    '--artifacts-dir',str(work)]
            import os
            env = {**os.environ,'CULSMA_OS_STATION_ROOT':str(work/'station'),
                   'CULSMA_OS_STATION_ID':'paired-cli-acceptance'}
            process = subprocess.run(args,capture_output=True,text=True,env=env,timeout=90)
            assert process.returncode == 0,process.stdout+process.stderr
            result=json.loads((work/'run.json').read_text())
            assert result['ok'] and result['user_result']['os']['status']=='completed'
            records[backend]={'program_sha256':sha256(source.read_bytes()).hexdigest(),
                              'state':result['state']['artifacts']['material_state']}
        assert records['ot2'] == records['star']
        return {'checks':'passed','backends':records}

    def run(self, directory):
        directory.mkdir(parents=True,exist_ok=True)
        assert not (directory/'summary.json').exists(), 'Use a fresh output directory'
        results=[self.run_scenario(s,directory/s['name']) for s in self.manifest['scenarios']]
        cli=self.cli_pair(directory/'language-cli')
        summary={'schema':'culsma_cross_platform_acceptance_v1','checks':'passed',
                 'versions':{'opentrons':version('opentrons'),'plr':version('PyLabRobot'),
                             'os':version('culsma-os')},
                 'scenario_pairs':len(results),'os_executions':2*len(results),
                 'cli_executions':2,'restart_checks':sum(bool(r['scenario']['fail_dispense']) for r in results)*2,
                 'cases':[{'name':r['scenario']['name'],'checks':r['checks'],
                          'devices':{k:{field:v[field] for field in ('status','volumes','material_version','consumption','uncertain_effects')}
                                     for k,v in r['backends'].items()}} for r in results],
                 'cli':cli}
        (directory/'summary.json').write_text(json.dumps(summary,indent=2))
        return summary

    @classmethod
    def main(cls):
        parser=argparse.ArgumentParser()
        parser.add_argument('--output-dir',type=Path,required=True)
        args=parser.parse_args()
        result=cls().run(args.output_dir)
        print(json.dumps({k:result[k] for k in ('checks','scenario_pairs','os_executions','cli_executions','restart_checks')},indent=2))


if __name__ == '__main__':
    CrossPlatformTransferAcceptance.main()
