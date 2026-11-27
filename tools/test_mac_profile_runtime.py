"""Exercise a magnetic program on an installed Hamilton local simulator through MCP."""
import asyncio,json,os,sys,time,uuid
from pathlib import Path
from mcp import Client,StdioServerParameters

async def execute(app, program, output):
    APP = app
    env={k:v for k,v in os.environ.items() if not any(x in k.upper() for x in ('TOKEN','SECRET','PASSWORD','API_KEY'))}
    server=StdioServerParameters(command=str(APP/'Contents/MacOS/culsma-mcp'),args=[],env=env)
    async with Client(server,read_timeout_seconds=30) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        for name in ('preview_program', 'prepare_program', 'start_program', 'submit_program'):
            assert 'profile_bindings' not in tools[name].input_schema['properties']
        async def call(name,**args):
            value=await client.call_tool(name,args)
            if value.is_error:raise RuntimeError(name+': '+str(value.content)[:1000])
            return value.structured_content
        station=await call('station_status')
        assert station['data']['host']['capabilities']['driver']=='hamilton-local'
        status=await call('configuration_status')
        assert status['host']['status']=='ready',status['host']
        inspection=await call('inspect_program',program_id=program)
        await call('preview_program', program_id=program)
        started = await call('start_program', program_id=inspection['program_id'],
            snapshot_id=inspection['snapshot_id'], request_id='station-live-'+uuid.uuid4().hex,
            configuration_fingerprint=status['active']['fingerprint'])
        run_id = started['run']['run_id']
        for _ in range(60):
            result = (await call('run_status', run_id=run_id))['data']
            if result['status'] in ('completed', 'failed', 'needs_reconciliation'):
                break
            await asyncio.sleep(0.25)
        assert result['status'] == 'completed', (result['status'], result['error'])
        attempts = result['execution_evidence']['attempts']
        batch = next(a for a in attempts if 'execution_batch' in a['context']['description'])
        actions = batch['evidence']['payload']['backend']['action_results']
        heights = [float(a['parameters']['liquidHeight']) for a in actions if a['kind'] == 'aspirate']
        assert len(heights) == 2, heights
        results = [{'run_id': run_id, 'status': result['status'], 'aspiration_heights_mm': heights}]
        view=await call('view_state')
        summary={'installed_app':str(APP),'mode':'hamilton-local simulation','runs':results,
                 'online_console_sessions':[s['session_id'] for s in view['sessions'] if s['online']]}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(summary,indent=2))
        print(json.dumps(summary))

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, default=Path('/Applications/CulsmaOS.app'))
    parser.add_argument('--program', default='Magnetic separation/local_magnetic_separation.culs')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(execute(args.app, args.program, args.output))
