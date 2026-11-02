"""Installed local magnetic Profile acceptance; explicitly starts simulated runs.

Use the App's bundled interpreter and packages/mcp on PYTHONPATH. Requires an idle
hamilton-local station, a 100 uL -> 5 s magnetic capture -> 50 uL protocol, and an
explicit local decoder height scope containing 2.5, 3.5 and 4 mm. It does not widen
that scope or establish official-simulator/physical height suitability. Generated
results belong outside Git. Deliberate rejection remains visible in run history.
"""
import asyncio,json,os,sys,time,uuid
from pathlib import Path
from mcp import Client,StdioServerParameters

async def execute(app, program, output):
    APP = app
    env={k:v for k,v in os.environ.items() if not any(x in k.upper() for x in ('TOKEN','SECRET','PASSWORD','API_KEY'))}
    server=StdioServerParameters(command=str(APP/'Contents/MacOS/culsma-mcp'),args=[],env=env)
    async with Client(server,read_timeout_seconds=30) as client:
        names={t.name for t in (await client.list_tools()).tools}
        assert 'save_instrument_profile' in names,'installed MCP has no Profile tools'
        async def call(name,**args):
            value=await client.call_tool(name,args)
            if value.is_error:raise RuntimeError(name+': '+str(value.content)[:1000])
            return value.structured_content
        station=await call('station_status')
        assert station['data']['host']['capabilities']['driver']=='hamilton-local'
        status=await call('configuration_status')
        assert status['host']['status']=='ready',status['host']
        origin=status['active']['origin']
        configuration=(await call('read_configuration',draft_id=origin['draft_id'],revision=origin['revision']))['draft']['configuration']
        context=dict(draft_id=origin['draft_id'],configuration_revision=origin['revision'],device_id=configuration['device_id'])
        catalogue=await call('instrument_profile_catalogue',**context)
        module=next(m for m in catalogue['modules'] if m['kind']=='pipetting')
        plate=configuration['processing']['magnet']['labware'][0]
        preview=await call('preview_program',program_id=program)
        loading=preview['preparation']['plan']
        plate_model=next(i['model'] for i in loading['items'] if i['address']['labware']==plate)
        reservoir=next(i['model'] for i in loading['items'] if i['name']=='stock')
        tip=loading['supplies'][0]['model']
        identity=uuid.uuid4().hex[:10]
        async def save(name,operation,height,source,target,volume,held=False):
            args={**context,'module_id':module['module_id'],'profile_id':'live-'+identity+'-'+name,
                'method_id':'positioned_pipetting','definition_revision':'1','display_name':'MCP verification '+name,
                'parameters':{'aspiration_height_mm':height,'dispense_height_mm':5},
                'applicability':{'operation':operation,'source_models':[source],'destination_models':[target],
                    'tip_models':[tip],'per_aspiration_volume_uL':{'minimum':volume,'maximum':volume},
                    'required_source_conditions':['magnetically_held'] if held else []}}
            profile=(await call('save_instrument_profile',**args))['profile']
            return args,profile
        add_args,add=await save('addition','transfer',2.5,reservoir,plate_model,100)
        super_args,old=await save('supernatant','magnetic_flowthrough_transfer',3.5,plate_model,reservoir,50,True)
        new=(await call('save_instrument_profile',**{**super_args,'expected_revision':old['reference']['revision'],
            'parameters':{**super_args['parameters'],'aspiration_height_mm':4}}))['profile']
        assert (await call('read_instrument_profile',device_id=module['device_id'],module_id=module['module_id'],
            profile_id=old['reference']['profile_id'],profile_revision=old['reference']['revision']))['profile']==old
        inspection=await call('inspect_program',program_id=program)
        ids=[s['step_id'] for s in inspection['execution_steps'] if s['operation']=='Mutation']
        assert len(ids)==2,inspection['execution_steps']
        async def run(profile,wrong=False):
            bindings={ids[0]:add['reference'],ids[1]:(add if wrong else profile)['reference']}
            started=await call('start_program',program_id=inspection['program_id'],snapshot_id=inspection['snapshot_id'],
                request_id='profile-live-'+uuid.uuid4().hex,configuration_fingerprint=status['active']['fingerprint'],profile_bindings=bindings)
            run_id=started['run']['run_id']
            for _ in range(60):
                result=(await call('run_status',run_id=run_id))['data']
                if result['status'] in ('completed','failed','needs_reconciliation'):break
                await asyncio.sleep(0.25)
            if wrong:
                assert result['status']=='failed' and 'PROFILE_OPERATION_MISMATCH' in result['error'],(result['status'],result['error'])
                assert not result['execution_evidence']['attempts']
                return {'run_id':run_id,'status':result['status'],'expected_rejection':result['error']}
            assert result['status']=='completed',(result['status'],result['error'])
            attempts=result['execution_evidence']['attempts']
            root=next(a for a in attempts if 'execution_batch' in a['context']['description'])
            actions=root['evidence']['payload']['backend']['action_results']
            heights=[float(a['parameters']['liquidHeight']) for a in actions if a['kind']=='aspirate']
            expected=profile['parameters']['aspiration_height_mm']
            assert heights==[2.5,expected],heights
            recorded=root['context']['description']['instrument_profiles']
            assert recorded[1]['reference']==profile['reference']
            return {'run_id':run_id,'status':result['status'],'aspiration_heights_mm':heights,
                'profile_revisions':[x['reference']['revision'] for x in recorded],
                'products':result['result']['materials']['final_products']}
        results=[]
        results.append(await run(new))
        results.append(await run(new,wrong=True))
        results.append(await run(old))
        view=await call('view_state')
        summary={'installed_app':str(APP),'mode':'hamilton-local simulation','runs':results,
                 'online_console_sessions':[s['session_id'] for s in view['sessions'] if s['online']]}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(summary,indent=2))
        print(json.dumps(summary))

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Installed-App MCP acceptance: saves Profile revisions, runs two LOCAL magnetic simulations and one expected pre-dispatch rejection.')
    parser.add_argument('--app', type=Path, default=Path('/Applications/CulsmaOS Preview.app'))
    parser.add_argument('--program', default='Magnetic separation/local_magnetic_separation.culs')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(execute(args.app, args.program, args.output))
