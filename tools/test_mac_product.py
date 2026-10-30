"""Relocated installed app -> bundled Python/MCP -> official simulator -> native view."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


async def exercise(app, env):
    from mcp import Client, StdioServerParameters
    server=StdioServerParameters(command=str(app/'Contents/MacOS/culsma-mcp'),env=env)
    async with Client(server,read_timeout_seconds=30) as client:
        async def call(name,**arguments):
            result=await client.call_tool(name,arguments)
            assert not result.is_error,result
            return result.structured_content
        tools=(await client.list_tools()).tools
        assert len(tools)==43,len(tools)
        for _ in range(300):
            result=await client.call_tool('station_status',{})
            if not result.is_error and result.structured_content['data']['host']['status']=='ready':break
            await asyncio.sleep(.1)
        else:raise AssertionError('Bundled station did not become ready')
        programs=await call('list_programs')
        assert any(p['program_id']=='Transfer/transfer.culs' for p in programs['programs'])
        await call('create_document',path='from-mcp.culs',content='let sample=tube(capacity=200uL);return sample;')
        document=await call('read_document',path='from-mcp.culs')
        await call('save_document',path='from-mcp.culs',content='let sample=tube(capacity=300uL);return sample;',expected_revision=document['revision'])
        conflict=await client.call_tool('save_document',{'path':'from-mcp.culs','content':'stale','expected_revision':document['revision']})
        assert conflict.is_error
        profiles=await call('configuration_profiles')
        assert profiles
        active=await call('configuration_status')
        assert active['active']['fingerprint']
        program=await call('inspect_program',program_id='Transfer/transfer.culs')
        assert program['valid'],program
        run=await call('start_program',program_id='Transfer/transfer.culs',snapshot_id=program['snapshot_id'],request_id='installed-mac-transfer')
        run_id=run['run']['run_id']
        for _ in range(600):
            outcome=await call('run_status',run_id=run_id)
            status=outcome['data']['status']
            if status in {'completed','failed','reconciliation_required','awaiting_setup'}:break
            await asyncio.sleep(.1)
        assert status=='completed',outcome
        evidence=outcome['data']['execution_evidence']
        assert evidence['attempts'],evidence
        registered=evidence.get('material_state') or outcome['data'].get('material_state')
        if registered is not None:assert registered
        for _ in range(300):
            live=[s for s in (await call('view_state'))['sessions'] if s['online'] and not s['state']['busy']]
            if live:break
            await asyncio.sleep(.1)
        assert len(live)==1,'Packaged native renderer did not register'
        session=live[0]
        await call('open_view',session_id=session['session_id'],epoch=session['epoch'],expected_revision=session['revision'],request_id='installed-mac-result',view='experiment',entity_id=run_id)
        for _ in range(300):
            receipt=await call('view_request_status',request_id='installed-mac-result')
            if receipt['status']!='accepted':break
            await asyncio.sleep(.1)
        assert receipt['status']=='displayed',receipt
        return {'tools':len(tools),'status':status,'run_id':run_id,'native_result':'displayed',
                'official_simulator':'opentrons','editable_files':True,'stale_save':'rejected','hardware_operated':False}


def main(app, output):
    app=app.resolve();output=output.resolve();output.mkdir(parents=True,exist_ok=True)
    # The SDK used by this test comes from the delivered product, not the developer environment.
    sys.path.insert(0,str(app/'Contents/Resources/packages/mcp'))
    with tempfile.TemporaryDirectory(prefix='cm-',dir='/private/tmp') as temporary:
        home=Path(temporary)/'User';home.mkdir()
        env={**os.environ,'HOME':str(home),'PYTHONPATH':'/unavailable-developer-environment','PYTHONHOME':'/unavailable-python','PYTHONDONTWRITEBYTECODE':'1'}
        resources=app/'Contents/Resources';python=resources/'runtime/bin/python3.11';launch=resources/'launch.py'
        with (output/'native.log').open('w') as log:
            native=subprocess.Popen([str(python),'-I',str(launch),'desktop'],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                result=asyncio.run(exercise(app,env))
                (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
                text=(output/'native.log').read_text()
                assert 'Failed to update ui::AXTree' not in text
                assert native.poll() is None,'Native desktop unexpectedly exited'
                print(json.dumps(result,indent=2))
            finally:
                subprocess.run([str(python),'-I',str(launch),'stop'],env=env,capture_output=True,timeout=15)
                resident_log=home/'Library/Application Support/culsmaOS/preview/resident.log'
                if resident_log.exists():shutil.copy2(resident_log,output/'resident.log')
                # Terminate only this isolated test's native child, not any user's app.
                children=subprocess.run(['/usr/bin/pgrep','-P',str(native.pid)],capture_output=True,text=True).stdout.split()
                for child in children:
                    try:os.kill(int(child),15)
                    except ProcessLookupError:pass
                if native.poll() is None:
                    try:native.wait(timeout=8)
                    except subprocess.TimeoutExpired:native.terminate();native.wait(timeout=5)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();main(args.app,args.output)
