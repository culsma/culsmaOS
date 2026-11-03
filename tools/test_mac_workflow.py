"""Installed-App workflow acceptance with real MCP, persistence and local simulation.

Creates a named protocol copy and a layout draft, temporarily applies one empty-site
placement, restores the original station and leaves auditable test records. Never
connects to a physical device. Run --verify after restarting the App to check state.
Evidence output belongs outside Git. Run tools/test_mac_profile_runtime.py separately
for pinned Profile revisions and per-operation height evidence.
"""
import argparse, asyncio, json, os, time, uuid
from pathlib import Path
from mcp import Client, StdioServerParameters


async def exercise(app, output, verify=False):
    env = {k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ('TOKEN','SECRET','PASSWORD','API_KEY'))}
    async with Client(StdioServerParameters(command=str(app/'Contents/MacOS/culsma-mcp'), env=env), read_timeout_seconds=30) as client:
        async def call(tool_name, **args):
            result = await client.call_tool(tool_name, args)
            assert not result.is_error, (tool_name, str(result.content)[:1600])
            return result.structured_content
        async def poll(name, args, terminal, status):
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                result = await call(name, **args)
                if status(result) in terminal: return result
                await asyncio.sleep(.1)
            raise AssertionError((name, 'receipt did not settle; never resent', result))
        active = await call('configuration_status')
        station = (await call('station_status'))['data']
        assert station['host']['status'] == 'ready' and not station['host']['blocked_run']
        assert station['host']['capabilities']['driver'] == 'hamilton-local'
        if verify:
            summary = json.loads(output.read_text())
            assert active['active']['fingerprint'] == summary['original_configuration']
            document = await call('read_document', path=summary['document']['path'])
            assert document['revision'] == summary['document']['revision']
            for saved in summary['runs']:
                record = (await call('run_status', run_id=saved['run_id']))['data']
                assert record['status'] == 'completed'
                assert len(record['execution_evidence']['attempts']) == saved['attempts']
            summary['restart_verified'] = True
            output.write_text(json.dumps(summary, indent=2)+'\n')
            print(json.dumps({'restart_verified':True,'runs_retained':len(summary['runs'])}));return
        tag = uuid.uuid4().hex[:8]
        summary = {'original_configuration':active['active']['fingerprint'], 'runs':[], 'restart_verified':False}
        origin = active['active']['origin']
        path = 'Transfer/acceptance-'+tag+'.culs'
        original = await call('read_document', path='Transfer/transfer.culs')
        await call('create_document', path=path, content=original['content'])
        before = await call('read_document', path=path)
        await call('save_document', path=path, expected_revision=before['revision'], content=before['content']+'\n// Installed workflow acceptance.\n')
        saved = await call('read_document', path=path)
        stale = await client.call_tool('save_document', {'path':path,'expected_revision':before['revision'],'content':'stale write must not replace source'})
        assert stale.is_error
        assert (await call('read_document',path=path)) == saved
        summary['document'] = {'path':path,'revision':saved['revision'],'stale_write_rejected':True}
        changed = await call('prepare_labware_change', expected_fingerprint=active['active']['fingerprint'],action='place',target='CAR_5TIP_0001/4',model='HTF_L',name='AcceptanceTipsA4')
        draft = changed['draft']
        validation = await call('validate_configuration', draft_id=draft['draft_id'],revision=draft['revision'])
        assert validation['validation']['valid'],validation
        applied = False
        try:
            request = 'acceptance-layout-'+tag
            await call('apply_configuration',draft_id=draft['draft_id'],revision=draft['revision'],expected_fingerprint=active['active']['fingerprint'],request_id=request)
            receipt = await poll('configuration_status', {'request_id':request}, {'applied','rejected','failed'}, lambda r:r['receipt']['status'])
            assert receipt['receipt']['status']=='applied',receipt
            applied = True
            current = await call('configuration_status')
            catalogue = await call('labware_catalogue',expected_fingerprint=current['active']['fingerprint'])
            target = next(t for t in catalogue['catalogue']['targets'] if t['id']=='CAR_5TIP_0001/4')
            assert target['occupants']==['AcceptanceTipsA4'],target
            summary['layout_place_applied']=True
        finally:
            if applied:
                current = await call('configuration_status')
                request = 'acceptance-restore-'+tag
                await call('apply_configuration',draft_id=origin['draft_id'],revision=origin['revision'],expected_fingerprint=current['active']['fingerprint'],request_id=request)
                receipt = await poll('configuration_status', {'request_id':request}, {'applied','rejected','failed'}, lambda r:r['receipt']['status'])
                assert receipt['receipt']['status']=='applied',receipt
                assert (await call('configuration_status'))['active']['fingerprint']==summary['original_configuration']
                summary['layout_restored']=True
        inspection = await call('inspect_program',program_id=path)
        pending = await call('submit_program',program_id=path,snapshot_id=inspection['snapshot_id'],configuration_fingerprint=summary['original_configuration'],request_id='acceptance-prepare-'+tag)
        run_id = pending['run']['run_id']
        try:
            plan = await poll('loading_plan', {'run_id':run_id}, {'planned'},lambda r:r.get('phase'))
            sources = [i for i in plan['items'] if i['kind']=='tube']
            fixed = {i['allocation_id']:sources[0]['address'] for i in sources}
            request='acceptance-conflict-'+tag
            await call('revise_loading_plan',run_id=run_id,fingerprint=plan['fingerprint'],request_id=request,fixed=fixed)
            rejection = await poll('loading_request_status',{'run_id':run_id,'request_id':request},{'failed','completed'},lambda r:r['status'])
            assert rejection['status']=='failed' and rejection['result']['diagnostics'][0]['code']=='SETUP_NO_FEASIBLE_LAYOUT'
            assert (await call('loading_plan',run_id=run_id))['fingerprint']==plan['fingerprint']
            assert not (await call('run_status',run_id=run_id))['data']['execution_evidence']['attempts']
            request='acceptance-corrected-'+tag
            await call('revise_loading_plan',run_id=run_id,fingerprint=plan['fingerprint'],request_id=request)
            corrected = await poll('loading_request_status',{'run_id':run_id,'request_id':request},{'failed','completed'},lambda r:r['status'])
            assert corrected['status']=='completed'
            summary['conflict_rejected_and_corrected']=True
        finally:
            request='acceptance-cancel-'+tag
            await call('control_run',run_id=run_id,action='cancel',request_id=request)
            cancelled=await poll('control_request_status',{'run_id':run_id,'request_id':request},{'applied','rejected'},lambda r:r['acknowledgement']['status'])
            assert cancelled['acknowledgement']['status']=='applied'
        for program in (path,'Magnetic separation/local_magnetic_separation.culs',path):
            inspection=await call('inspect_program',program_id=program)
            started=await call('start_program',program_id=program,snapshot_id=inspection['snapshot_id'],configuration_fingerprint=summary['original_configuration'],request_id='acceptance-run-'+uuid.uuid4().hex)
            run_id=started['run']['run_id']
            outcome=await poll('run_status',{'run_id':run_id},{'completed','failed','needs_reconciliation'},lambda r:r['data']['status'])
            record=outcome['data']
            assert record['status']=='completed',(record['status'],record['error'])
            attempts=record['execution_evidence']['attempts']
            assert len([a for a in attempts if a['context']['description'].get('execution_batch')])==1
            assert all(a['evidence']['outcome']=='completed' for a in attempts)
            summary['runs'].append({'run_id':run_id,'program':program,'attempts':len(attempts),'status':record['status']})
        summary['hardware_operated']=False
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(summary,indent=2)+'\n')
        print(json.dumps(summary))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',type=Path,default=Path('/Applications/CulsmaOS Preview.app'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--verify',action='store_true')
    args=parser.parse_args();asyncio.run(exercise(args.app,args.output,args.verify))
