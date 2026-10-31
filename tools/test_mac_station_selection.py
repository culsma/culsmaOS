"""Installed-product acceptance: real MCP selection and actual resident restarts."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


async def check(app, home, output):
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(app/'Contents/Resources/packages/mcp'))
    from mcp import Client,StdioServerParameters
    resources=app/'Contents/Resources';runtime=resources/'runtime/bin/python3.11'
    environment={**os.environ,'HOME':str(home)}
    environment.pop('CULSMA_OS_PROFILE',None)
    processes=[]
    initial=None
    for index,(profile,target) in enumerate((('opentrons-simulator','hamilton-local'),('hamilton-local','opentrons-simulator'),('opentrons-simulator',None))):
        log=(output/f'{index}-resident.log').open('w')
        process=subprocess.Popen([str(runtime),'-I','-B',str(resources/'launch.py'),'service'],env=environment,stdout=log,stderr=log)
        processes.append((profile,process,log))
        try:
            async with Client(StdioServerParameters(command=str(app/'Contents/MacOS/culsma-mcp'),env=environment),read_timeout_seconds=30) as client:
                async def call(name,**arguments):
                    result=await client.call_tool(name,arguments)
                    assert not result.is_error,result
                    return result.structured_content
                tools={tool.name for tool in (await client.list_tools()).tools}
                assert {'station_selection_status','select_station_for_next_start'}<=tools
                for _ in range(300):
                    result=await client.call_tool('station_status',{})
                    if not result.is_error and result.structured_content['data']['host']['status']=='ready':break
                    assert process.poll() is None,'Resident exited; inspect acceptance logs'
                    await asyncio.sleep(.1)
                else:raise AssertionError('Resident did not become ready')
                host=result.structured_content['data']['host']
                assert host['capabilities']['driver']==profile
                before=await call('station_selection_status')
                assert before['connected_profile']==before['selected_profile']==profile
                assert before['resident']['driver']==profile
                assert not before['restart_required']
                active=await call('configuration_status')
                if index==0:initial=active['active']['fingerprint']
                if index==2:assert active['active']['fingerprint']==initial
                if target:
                    selected=await call('select_station_for_next_start',profile_id=target,expected_selected_profile=profile)
                    assert selected['selected_profile']==target and selected['connected_profile']==profile
                    assert selected['restart_required'] and selected['mcp_reconnect_required']
                    assert selected['runtime_changed'] is selected['station_data_changed'] is False
                    assert selected['resident']['driver']==profile
                    assert (await call('station_status'))['data']['host']['capabilities']['driver']==profile
                    assert (await call('configuration_status'))['active']==active['active']
                    stale=await client.call_tool('select_station_for_next_start',{'profile_id':profile,'expected_selected_profile':profile})
                    assert stale.is_error and 'STATION_SELECTION_CONFLICT' in str(stale.content)
        finally:
            stop_env={**environment,'CULSMA_OS_PROFILE':profile}
            subprocess.run([str(runtime),'-I','-B',str(resources/'launch.py'),'stop'],env=stop_env,capture_output=True,timeout=15)
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)
            log.close()
    # The startup-selection tools remain usable with the App and resident both closed.
    async with Client(StdioServerParameters(command=str(app/'Contents/MacOS/culsma-mcp'),env=environment),read_timeout_seconds=15) as client:
        result=await client.call_tool('station_selection_status',{})
        assert not result.is_error
        assert result.structured_content['selected_profile']=='opentrons-simulator'
        assert result.structured_content['resident']['status']=='unavailable'
    return {'mcp_tools':len(tools),'restart_sequence':['opentrons-simulator','hamilton-local','opentrons-simulator'],
            'selection_available_before_app_start':True,'no_hot_switch':True,'opentrons_configuration_retained':True,'experiments_started':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',type=Path,required=True)
    parser.add_argument('--hamilton-addon',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    arguments=parser.parse_args();arguments.output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='culsma-selection-',dir='/private/tmp') as temporary:
        home=Path(temporary)/'Home';home.mkdir()
        addon=home/'Library/Application Support/culsmaOS/addons/hamilton';addon.mkdir(parents=True)
        # Real local addon content is read-only input; each station gets isolated writable state.
        for name in ('packages','LabWare','defaults'):(addon/name).symlink_to((arguments.hamilton_addon/name).resolve(),target_is_directory=True)
        summary=asyncio.run(check(arguments.app.resolve(),home,arguments.output.resolve()))
        (arguments.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        print(json.dumps(summary))


if __name__=='__main__':main()
