"""Official SDK client used by protocol and browser tests in an isolated SDK process."""
import asyncio
import json
import os
from pathlib import Path
import sys
from mcp import Client, StdioServerParameters


class LoadingMCPClient:
    async def execute(self,socket,run_id):
        server=StdioServerParameters(command=sys.executable,args=['-m','culsma_os.cli','mcp','--socket',socket],env=dict(os.environ))
        async with Client(server,read_timeout_seconds=10) as client:
            tools=await client.list_tools()
            names=[tool.name for tool in tools.tools]
            assert 'loading_plan' in names and not any('confirm' in name for name in names)
            for name,arguments in [('station_status',{}),('list_runs',{}),('run_status',{'run_id':run_id})]:
                observation=await client.call_tool(name,arguments)
                assert not observation.is_error and isinstance(observation.structured_content,dict),observation
            initial=await client.call_tool('loading_plan',{'run_id':run_id})
            assert not initial.is_error,initial
            before=initial.structured_content
            source=next(item for item in before['items'] if item['name']=='source')
            result=await client.call_tool('revise_loading_plan',{'run_id':run_id,'fingerprint':before['fingerprint'],
                'request_id':'mcp-fixed-source','fixed':{source['allocation_id']:{'labware':'source_vessel','well':'1'}}})
            assert not result.is_error,result
            for _ in range(100):
                receipt=(await client.call_tool('loading_request_status',{'run_id':run_id,'request_id':'mcp-fixed-source'})).structured_content
                if receipt['status']!='pending': break
                await asyncio.sleep(.02)
            assert receipt['status']=='completed',receipt
            after=(await client.call_tool('loading_plan',{'run_id':run_id})).structured_content
            assert after['fingerprint']!=before['fingerprint']
            assert any(e['origin']=='local-mcp-process' for e in after['activity'])
            stale=await client.call_tool('begin_loading',{'run_id':run_id,'fingerprint':before['fingerprint'],'request_id':'mcp-stale-begin'})
            assert not stale.is_error
            for _ in range(100):
                stale_receipt=(await client.call_tool('loading_request_status',{'run_id':run_id,'request_id':'mcp-stale-begin'})).structured_content
                if stale_receipt['status']!='pending': break
                await asyncio.sleep(.02)
            assert stale_receipt['status']=='failed' and stale_receipt['error']=='SETUP_PLAN_STALE',stale_receipt
            forbidden=await client.call_tool('confirm_loading',{'run_id':run_id,'acknowledged':True})
            assert forbidden.is_error
            print(json.dumps({'before':before['fingerprint'],'after':after['fingerprint'],'tools':names}))


if __name__=='__main__':
    asyncio.run(LoadingMCPClient().execute(sys.argv[1],sys.argv[2]))
