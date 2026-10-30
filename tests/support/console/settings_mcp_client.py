"""Official stdio client exercises configuration, rack and slot tools on a local test station."""
import asyncio
import base64
import json
import os
from pathlib import Path
import sys
from mcp import Client, StdioServerParameters


async def execute(socket,home,programs,store,drafts,layout_source):
    server=StdioServerParameters(command=sys.executable,args=['-m','culsma_os.cli','mcp','--socket',socket,'--home',home,'--program-root',programs,'--program-store',store,'--drafts-db',drafts],env=dict(os.environ))
    async with Client(server,read_timeout_seconds=15) as client:
        tools={t.name:t for t in (await client.list_tools()).tools}
        required={'configuration_profiles','list_configurations','read_configuration','create_configuration','save_configuration','validate_configuration','export_configuration','export_vendor_layout','import_vendor_layout','review_program_bindings','configuration_status','apply_configuration','labware_catalogue','prepare_labware_change','test_device_fault'}
        assert required <= tools.keys(),tools.keys()
        assert not any('confirm' in name or 'renderer' in name for name in tools)
        views=tools['open_view'].input_schema['properties']['view']['enum']
        assert {'desktop','developer','editor','settings'}<=set(views)
        async def call(tool_name,**arguments):
            result=await client.call_tool(tool_name,arguments)
            assert not result.is_error,result
            return result.structured_content
        async def apply(draft,fp,request_id):
            await call('apply_configuration',draft_id=draft['draft_id'],revision=draft['revision'],expected_fingerprint=fp,request_id=request_id)
            for _ in range(300):
                status=await call('configuration_status',request_id=request_id)
                if status.get('receipt',{}).get('status') in {'applied','failed','interrupted'}:break
                await asyncio.sleep(.02)
            assert status['receipt']['status']=='applied',status
            return status['active']['fingerprint']
        initial=await call('configuration_status');fp=initial['active']['fingerprint']
        catalogue=await call('labware_catalogue',expected_fingerprint=fp)
        assert any(t.get('kind')=='carrier' for t in catalogue['catalogue']['targets'])
        stale=await client.call_tool('labware_catalogue',{'expected_fingerprint':'0'*64})
        assert stale.is_error
        proposal=await call('prepare_labware_change',expected_fingerprint=fp,action='replace-carrier',target='carrier:PREVIEW_T37_38_4R200',model='RGT_CAR_5R60_A00')
        assert proposal['activation']=='not_applied'
        assert (await call('configuration_status'))['active']['fingerprint']==fp
        draft=(await call('read_configuration',draft_id=proposal['draft']['draft_id']))['draft']
        draft=(await call('save_configuration',draft_id=draft['draft_id'],expected_revision=draft['revision'],title='Rack edited through MCP',driver=draft['driver'],configuration=draft['configuration']))['draft']
        assert (await call('validate_configuration',draft_id=draft['draft_id'],revision=draft['revision']))['validation']['valid']
        assert (await call('export_configuration',draft_id=draft['draft_id'],revision=draft['revision']))['configuration']==draft['configuration']
        await call('create_document',path='bindings.culs',content='let sample=tube(capacity=200uL);return sample;')
        program=await call('inspect_program',program_id='bindings.culs')
        bindings=await call('review_program_bindings',draft_id=draft['draft_id'],revision=draft['revision'],program_id='bindings.culs',snapshot_id=program['snapshot_id'])
        assert bindings['activation']=='not_applied' and bindings['diagnostics']
        fp=await apply(draft,fp,'mcp-rack-replacement')
        for action in ('place','replace','remove'):
            arguments={'expected_fingerprint':fp,'action':action,'target':'PREVIEW_T36_5R60_SUBSTITUTE/2'}
            if action!='remove':arguments['model']='RGT_CONT_60ML_BC_A00'
            if action=='place':arguments['name']='MCPVessel'
            proposal=await call('prepare_labware_change',**arguments)
            fp=await apply(proposal['draft'],fp,'mcp-vessel-'+action)
        path=Path(layout_source)
        imported=await call('import_vendor_layout',driver='hamilton-layout',layout_source={'name':path.name,'encoding':'base64','content':base64.b64encode(path.read_bytes()).decode()})
        offline=(await call('create_configuration',title='Offline imported layout',driver='hamilton-layout',configuration=imported['import_report']['configuration']))['draft']
        archive=await call('export_vendor_layout',draft_id=offline['draft_id'],revision=offline['revision'])
        assert base64.b64decode(archive['layout_artifact']['content']).startswith(b'PK')
        assert any(d['draft_id']==offline['draft_id'] for d in (await call('list_configurations'))['drafts'])
        for scenario in ('tip_unavailable','liquid_insufficient','interrupted'):
            fault=await call('test_device_fault',scenario=scenario)
            assert isinstance(fault['supported'],bool)
            if fault['supported']:assert fault['station_changed'] is False and fault['recovery_allowed'] is False
        assert (await call('configuration_status'))['active']['fingerprint']==fp
        print(json.dumps({'tools':len(tools),'draft_id':draft['draft_id'],'rack':'RGT_CAR_5R60_A00','labware_actions':['place','replace','remove'],'active_fingerprint':fp,'physical_actions':0}))


if __name__=='__main__':asyncio.run(execute(*sys.argv[1:]))
