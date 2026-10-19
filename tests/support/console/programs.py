def session_headers(console):
    code,_,session=console.request('GET','/api/v1/session',{'X-Culsma-Console':'1','Sec-Fetch-Site':'same-origin'})
    assert code==200
    return {'Origin':console.server.url,'Content-Type':'application/json','Authorization':'Bearer '+session['access_token']}


def inspect_and_submit(console,headers,request_id='console-transfer'):
    code,_,view=console.request('POST','/api/v1/programs',headers,{'action':'inspect','program_id':'transfer.culs'})
    assert code==200 and view['data']['valid']
    payload={'action':'submit','program_id':'transfer.culs','snapshot_id':view['data']['snapshot_id'],'request_id':request_id}
    code,_,result=console.request('POST','/api/v1/programs',headers,payload)
    assert code==200 and result['data']['run']['accepted']
    return payload,result['data']['run']['run_id']


