"""Official MCP client -> production stdio bridge -> actual native editor."""
import asyncio
import base64
import json
import os
from pathlib import Path
import sys
from mcp import Client, StdioServerParameters


async def verify(socket,home,programs,store):
    server=StdioServerParameters(command=sys.executable,args=['-m','culsma_os.cli','mcp','--socket',socket,'--home',home,'--program-root',programs,'--program-store',store],env=dict(os.environ))
    async with Client(server,read_timeout_seconds=15) as client:
        names={tool.name for tool in (await client.list_tools()).tools}
        assert {'create_document','read_document','save_document','receive_files','inspect_program','view_state','open_view','view_request_status'}<=names
        assert not any('confirm' in name or 'renderer' in name for name in names)
        async def call(name,**arguments):
            result=await client.call_tool(name,arguments)
            assert not result.is_error,result
            return result.structured_content
        # Wait for the actual native renderer, then rely on shared business activity.
        for _ in range(1600):
            live=[v for v in (await call('view_state'))['sessions'] if v['online']]
            if live:break
            await asyncio.sleep(.1)
        assert len(live)==1,'Native renderer did not register'
        original='let sample=tube(capacity=200uL);return sample;'
        updated=original.replace('200uL','350uL')
        await call('receive_files',entries=[{'path':'received/helper.culs','data':base64.b64encode(original.encode()).decode()}])
        await call('create_document',path='from-ai.culs',content=original)
        read=await call('read_document',path='from-ai.culs')
        await call('save_document',path='from-ai.culs',content=updated,expected_revision=read['revision'])
        conflict=await client.call_tool('save_document',{'path':'from-ai.culs','content':'stale','expected_revision':read['revision']})
        assert conflict.is_error
        assert any("FILE_REVISION_CONFLICT" in getattr(item,"text","") for item in conflict.content),conflict
        assert (await call('read_document',path='from-ai.culs'))['content']==updated
        assert (await call('inspect_program',program_id='from-ai.culs'))['valid']
        for _ in range(300):
            state=await call('view_state')
            session=next(v for v in state['sessions'] if v['session_id']==live[0]['session_id'])
            if session['state']['view']=='editor' and session['state']['entity_id']=='from-ai.culs':break
            await asyncio.sleep(.1)
        assert session['state']['entity_id']=='from-ai.culs',(session,state.get('activity'))
        events=state['activity']
        assert any(v['action']=='file.save' and v['phase']=='returned' and v['actor']=='automation' for v in events)
        for _ in range(200):
            session=next(s for s in (await call('view_state'))['sessions'] if s['session_id']==session['session_id'])
            if session['state']['dirty']:break
            await asyncio.sleep(.1)
        assert session['state']['dirty']
        await call('open_view',session_id=session['session_id'],epoch=session['epoch'],expected_revision=session['revision'],request_id='mcp-preserve-edit',view='system_info')
        for _ in range(200):
            receipt=await call('view_request_status',request_id='mcp-preserve-edit')
            if receipt['status']!='accepted':break
            await asyncio.sleep(.1)
        assert receipt['status']=='deferred',receipt
        assert (await call('read_document',path='from-ai.culs'))['content']==updated
        print(json.dumps({'tools':len(names),'editor':'automatically_followed','unsaved_edits':'preserved','stale_save':'rejected','instruments_started':False}))


if __name__=='__main__':asyncio.run(verify(*sys.argv[1:]))
