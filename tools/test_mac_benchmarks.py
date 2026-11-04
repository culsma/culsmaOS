"""Audit unchanged language benchmarks through the installed OS/MCP boundary.

Imports only .culs sources with their original hierarchy and dependency bytes.
Compile success, OS admissibility and simulator completion are separate results.
Pass --execute to run only cases accepted by both inspection and layout preview.
Uses the installed App SDK/packages; JSON evidence must stay outside Git.
"""
import argparse, asyncio, base64, hashlib, json, os, time, uuid
from collections import Counter
from pathlib import Path
import culsma
from culsma_os.program_manager.interactors.compilation import CompilationInteractor
from culsma_os.program_manager.interactors.semantics import HostedRuntimeInteractor
from culsma.pipeline.plan_nodes import PlanStepTree
from mcp import Client, StdioServerParameters


def compile_case(source):
    compiled = CompilationInteractor().compile([source])
    steps = [s for p in compiled.plan.plans for s in PlanStepTree.leaves(p.steps)]
    diagnostics = HostedRuntimeInteractor().validate_plan(compiled.plan)
    by_id = {s.step_id:s for s in steps}
    return {
        'operations': dict(Counter(s.op for s in steps)),
        'language_diagnostics': [{'code':d.code,'message':d.message,'severity':d.severity} for d in compiled.plan.diagnostics],
        'host_diagnostics': [{'code':d.code,'message':d.message,'step_id':d.node_id,
            'operation':by_id[d.node_id].op,'span':str(by_id[d.node_id].span)} for d in diagnostics],
        'separation_programs': dict(Counter(s.args.get('program',{}).get('name','unknown') for s in steps if s.op=='sep')),
    }


async def audit(app, root, output, execute):
    cases = sorted(root.glob('modules/[0-9][0-9]-*/protocol.culs')) + sorted(root.glob('composites/[0-9][0-9]-*/protocol.culs'))
    assert len(cases)==12, f'Expected 9 modules and 3 composites, found {len(cases)}'
    files = sorted({p for source in cases for p in source.parent.glob('*.culs')})
    before = {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    imported = 'Benchmarks/audit-'+uuid.uuid4().hex[:8]
    report = {'scope':'Unmodified benchmark compile, installed OS inspection and conditional local simulation',
        'language_module':str(Path(culsma.__file__).resolve()), 'language_version':culsma.__version__, 'source_root':str(root), 'files_sha256':before,
        'imported_directory':imported, 'execute_accepted_cases':execute, 'cases':[]}
    output.parent.mkdir(parents=True,exist_ok=True)
    def save(): output.write_text(json.dumps(report,indent=2)+'\n')
    env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ('TOKEN','SECRET','PASSWORD','API_KEY'))}
    async with Client(StdioServerParameters(command=str(app/'Contents/MacOS/culsma-mcp'),env=env),read_timeout_seconds=60) as client:
        async def call(tool_name, **args):
            response=await client.call_tool(tool_name,args)
            if response.is_error: return {'tool_error':str(response.content)[:2500]}
            return response.structured_content
        station=(await call('station_status'))['data']
        assert station['host']['status']=='ready' and not station['host']['blocked_run']
        report['driver']=station['host']['capabilities']['driver']
        active=await call('configuration_status')
        report['configuration_fingerprint']=active['active']['fingerprint']
        receipt=await call('receive_files',directory=imported,entries=[{'path':str(p.relative_to(root)),'data':base64.b64encode(p.read_bytes()).decode()} for p in files])
        assert 'tool_error' not in receipt,receipt
        report['import_receipt']=receipt
        for source in cases:
            relative=str(source.relative_to(root))
            row={'case':str(source.parent.relative_to(root)), 'program_id':imported+'/'+relative}
            report['cases'].append(row)
            try:
                row['compile']=compile_case(source)
                row['inspection']=await call('inspect_program',program_id=row['program_id'])
                row['preview']=await call('preview_program',program_id=row['program_id'])
                inspection,preview=row['inspection'],row['preview']
                eligible=inspection.get('valid') is True and preview.get('valid') is True and preview.get('preparation',{}).get('status')=='available'
                row['outcome']='accepted_not_executed' if eligible else 'blocked_before_execution'
                if eligible and execute:
                    start=await call('start_program',program_id=row['program_id'],snapshot_id=inspection['snapshot_id'],configuration_fingerprint=report['configuration_fingerprint'],request_id='benchmark-'+uuid.uuid4().hex)
                    row['start']=start
                    if 'tool_error' in start:row['outcome']='start_rejected'
                    else:
                        run_id=start['run']['run_id'];deadline=time.monotonic()+60
                        while time.monotonic()<deadline:
                            record=await call('run_status',run_id=run_id)
                            row['run']=record
                            status=record.get('data',{}).get('status')
                            if status in {'completed','failed','needs_reconciliation','awaiting_setup'}:break
                            await asyncio.sleep(.2)
                        row['outcome']=status or 'status_unavailable'
                        if status not in {'completed','failed'}:
                            save();raise RuntimeError('Run unsettled: inspect evidence; no automatic replay or next benchmark')
            except Exception as error:
                row['error']={'type':type(error).__name__,'message':str(error)[:2500]}
                if row.get('start',{}).get('run'):save();raise
            save()
            print(json.dumps({'case':row['case'],'outcome':row.get('outcome'),'language_errors':len(row.get('compile',{}).get('language_diagnostics',[])),
                'host_gaps':dict(Counter(d['operation'] for d in row.get('compile',{}).get('host_diagnostics',[]))), 'error':row.get('error')}),flush=True)
        report['source_bytes_unchanged']=before=={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        final=await call('configuration_status')
        report['configuration_unchanged']=final['active']['fingerprint']==report['configuration_fingerprint']
        report['summary']=dict(Counter(r.get('outcome','audit_error') for r in report['cases']))
        assert report['source_bytes_unchanged'] and report['configuration_unchanged']
        save();print(json.dumps({'summary':report['summary'],'evidence':str(output)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',type=Path,default=Path('/Applications/CulsmaOS Preview.app'))
    parser.add_argument('--benchmarks-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args();asyncio.run(audit(args.app,args.benchmarks_root,args.output,args.execute))
