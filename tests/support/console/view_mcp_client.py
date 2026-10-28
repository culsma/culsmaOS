"""Separate-process official MCP client for view interaction browser acceptance."""
import asyncio
import json
import os
import sys
from mcp import Client, StdioServerParameters


async def execute(socket, operation, entity, request_id):
    server=StdioServerParameters(command=sys.executable,args=['-m','culsma_os.cli','mcp','--socket',socket],env=dict(os.environ))
    async with Client(server,read_timeout_seconds=15) as client:
        names={tool.name for tool in (await client.list_tools()).tools}
        assert {'view_state','open_view','reveal_entity','view_request_status'}<=names
        assert not any('renderer' in name or 'acknowledge' in name for name in names)
        for _ in range(100):
            response=await client.call_tool('view_state',{})
            assert not response.is_error,response
            state=response.structured_content
            live=[row for row in state['sessions'] if row['online'] and not row['state']['busy']]
            if operation=='state' or live: break
            await asyncio.sleep(.05)
        if operation=='state':
            print(json.dumps(state));return
        assert len(live)==1,state
        session=live[0]
        arguments={'session_id':session['session_id'],'epoch':session['epoch'],
            'expected_revision':session['revision'],'request_id':request_id}
        if operation=='reveal':
            method='reveal_entity';arguments['entity_id']=entity
        else:
            method='open_view';arguments['view']=operation
            if entity!='-':arguments['entity_id']=entity
        for _ in range(4):
            response=await client.call_tool(method,arguments)
            if not response.is_error: break
            # A presentation revision may advance between observation and request.
            # Check the retained identity first; only a request absent from the store
            # can be re-proposed against the newly observed revision.
            saved=await client.call_tool('view_request_status',{'request_id':request_id})
            if not saved.is_error: break
            state=(await client.call_tool('view_state',{})).structured_content
            current=next(row for row in state['sessions'] if row['session_id']==session['session_id'])
            arguments['expected_revision']=current['revision']
            await asyncio.sleep(.05)
        assert not response.is_error,response
        for _ in range(240):
            receipt=await client.call_tool('view_request_status',{'request_id':request_id})
            assert not receipt.is_error,receipt
            result=receipt.structured_content
            if result['status']!='accepted':break
            await asyncio.sleep(.05)
        assert result['status'] in {'displayed','deferred','rejected'},result
        repeated=await client.call_tool(method,arguments)
        assert not repeated.is_error and repeated.structured_content['status']==result['status']
        print(json.dumps(result))


if __name__=='__main__':
    asyncio.run(execute(*sys.argv[1:]))
