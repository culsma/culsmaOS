"""Move one declared source through actual MCP while the browser has acknowledged the previous revision."""
import asyncio
import json
import os
import sys
from mcp import Client, StdioServerParameters


async def revise(socket,run_id):
    server=StdioServerParameters(command=sys.executable,args=['-m','culsma_os.cli','mcp','--socket',socket],env=dict(os.environ))
    async with Client(server,read_timeout_seconds=10) as client:
        async def call(name,arguments):
            result=await client.call_tool(name,arguments)
            assert not result.is_error,result
            return result.structured_content
        plan=await call('loading_plan',{'run_id':run_id})
        source=next(row for row in plan['items'] if row['name']=='source')
        request='mcp-loading-layout-revision'
        await call('revise_loading_plan',{'run_id':run_id,'fingerprint':plan['fingerprint'],'request_id':request,
            'fixed':{source['allocation_id']:{'labware':'source_other','well':'1'}}})
        for _ in range(100):
            receipt=await call('loading_request_status',{'run_id':run_id,'request_id':request})
            if receipt['status']!='pending': break
            await asyncio.sleep(.02)
        assert receipt['status']=='completed',receipt
        after=await call('loading_plan',{'run_id':run_id})
        assert after['fingerprint']!=plan['fingerprint'] and after['confirmation'] is None
        print(json.dumps({'before':plan['fingerprint'],'after':after['fingerprint']}))


if __name__=='__main__':
    asyncio.run(revise(sys.argv[1],sys.argv[2]))
