"""Offline production SSE/shared HA+SiYuan flow; no real notes/provider."""
import json
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient
from test_full_ha import FullHA as Base
from bridge.server import make_app
from bridge.siyuan import SiYuanDispatcher

NB='20000101000000-abcdefg'
DOC='20000101000001-abcdefg'

class Notes(Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.syrequests=[]; self.body='Original body'; self.badexport=False; self.failwrite=False
        self.doc={'id':DOC,'box':NB,'hpath':'/Voice/Ideas','content':'Ideas'}
        async def api(request):
            self.assertEqual(request.headers['Authorization'],'Token synthetic-notes')
            data=await request.json(); path=request.path; self.syrequests.append((path,data))
            if path.endswith('lsNotebooks'): result={'notebooks':[{'id':NB,'name':'Reference','closed':False}]}
            elif path.endswith('/sql'):
                result=[] if "hpath='/Voice/New'" in data['stmt'] and self.doc['hpath']!='/Voice/New' else [self.doc]
            elif path.endswith('exportMdContent'): result={'content':'# '+self.doc['content']+'\n\n'+('WRONG' if self.badexport else self.body)}
            elif path.endswith('createDocWithMd'):
                if self.failwrite: return web.json_response({'code':-1,'msg':'secret raw failure'})
                self.body=data['markdown']; self.doc=self.doc|{'hpath':data['path'],'content':'New'}; result=DOC
            elif path.endswith('updateBlock'):
                if self.failwrite: return web.Response(status=503,text='secret raw failure')
                self.body=data['data']; result=[]
            else: return web.Response(status=404)
            return web.json_response({'code':0,'data':result})
        app=web.Application(); app.router.add_post('/{rest:.*}',api)
        self.syserver=TestServer(app); await self.syserver.start_server()
        self.sy=SiYuanDispatcher(str(self.syserver.make_url('')).rstrip('/'),'synthetic-notes')
        await self.client.close()
        self.client=TestClient(TestServer(make_app(self.store,self.adapter,self.dispatcher,self.sy))); await self.client.start_server()
    async def asyncTearDown(self):
        await self.syserver.close(); await super().asyncTearDown()
    async def test_natural_notebooks_search_read_then_ha(self):
        self.prose='Your note says Original body.'
        self.transcript='Find my ideas in notes, then make the lounge dark.'
        self.calls=[('sy_list_notebooks',{}),('sy_search',{'query':'ideas'}),('sy_read',{'document_id':DOC}),self.action()]
        row=await self.submit()
        self.assertEqual(row['state'],'done',row)
        self.assertIn('Original body',str(self.wire[-1]['input'])); self.assertIn('State verified.',row['detail'])
        self.assertEqual(len(self.wire[0]['tools']),18)
        self.assertEqual(len(self.payloads),1)
        self.assertTrue(all(len(w['tools'])==18 for w in self.wire))
        self.calls=[('sy_read',{'document_id':DOC})]; await self.submit('followup')
        self.assertIn(self.transcript,self.wire[-1]['input'][0]['content'])
    async def test_update_stable_id_verified_and_duplicate_once(self):
        action=('sy_update',{'document_id':DOC,'markdown':'# Ideas\n\nFresh body'})
        self.calls=[action,action]; row=await self.submit(); duplicate=await self.submit()
        self.assertEqual(row['id'],duplicate['id']); self.assertIn('Write verified',row['detail'])
        writes=[d for p,d in self.syrequests if p.endswith('updateBlock')]
        self.assertEqual(writes,[{'id':DOC,'dataType':'markdown','data':'Fresh body'}])
        self.assertEqual(self.spoken,[row['detail']])
    async def test_create_verified_and_existing_path_not_recreated(self):
        self.calls=[('sy_create',{'notebook_id':NB,'path':'/Voice/New','markdown':'New idea'})]
        row=await self.submit(); self.assertIn('Write verified',row['detail'])
        self.assertEqual(sum(p.endswith('createDocWithMd') for p,d in self.syrequests),1)
        self.doc=self.doc|{'hpath':'/Voice/Ideas','content':'Ideas'}
        self.calls=[('sy_create',{'notebook_id':NB,'path':'/Voice/Ideas','markdown':'No duplicate'})]
        row=await self.submit('existing'); self.assertIn('already exists',row['detail'])
        self.assertEqual(sum(p.endswith('createDocWithMd') for p,d in self.syrequests),1)
    async def test_export_mismatch_and_write_error_not_success_or_retry(self):
        for flag in ('badexport','failwrite'):
            setattr(self,flag,True)
            action=('sy_update',{'document_id':DOC,'markdown':'New body'})
            self.calls=[action,action]; row=await self.submit(flag)
            self.assertIn('not verified',row['detail']); self.assertNotIn('Write verified',row['detail'])
            self.assertNotIn('secret raw failure',row['detail']); setattr(self,flag,False)
        self.assertEqual(sum(p.endswith('updateBlock') for p,d in self.syrequests),2)
    async def test_private_root_archive_and_invalid_ids_denied(self):
        self.doc['hpath']='/Private/Secrets'; self.calls=[('sy_read',{'document_id':DOC})]
        row=await self.submit(); self.assertIn('excluded',row['detail'])
        self.assertFalse(any(p.endswith('exportMdContent') for p,d in self.syrequests))
        self.calls=[('sy_read',{'document_id':'../invalid'})]; await self.submit('bad')
        self.assertFalse(any(p.endswith('exportMdContent') for p,d in self.syrequests))
    async def test_cancel_before_notes_write(self):
        original=self.sy._request
        async def request(path,data=None):
            out=await original(path,data)
            if path.endswith('exportMdContent'):
                turn=self.store.db.execute('select id from turns order by rowid desc limit 1').fetchone()[0]
                self.store.cancel('one',turn)
            return out
        self.sy._request=request
        self.calls=[('sy_update',{'document_id':DOC,'markdown':'Cancelled body'})]
        row=await self.submit()
        self.assertEqual(row['state'],'cancelled')
        self.assertFalse(any(p.endswith('updateBlock') for p,d in self.syrequests)); self.assertEqual(self.spoken,[])

    async def test_root_archive_excluded_but_normal_archive_notes_allowed(self):
        self.prose='Your note says Original body.'
        self.doc['hpath']='/zArchive/Old'; self.calls=[('sy_read',{'document_id':DOC})]
        row=await self.submit('rootarchive'); self.assertIn('excluded',row['detail'])
        self.doc['hpath']='/Tasks/Archive/Useful'; self.calls=[('sy_read',{'document_id':DOC})]
        row=await self.submit('normalarchive'); self.assertIn('Original body',row['detail'])

    async def test_mixed_notes_then_ha_service_error_does_not_erase_note_read(self):
        self.prose='Your note says Original body. That service is unavailable.'
        self.calls=[('sy_read',{'document_id':DOC}),self.action('climate','invented','climate.study')]
        row=await self.submit(); self.assertIn('Original body',str(self.wire[-1]['input']))
        self.assertIn('ha_service_unavailable',row['detail']); self.assertEqual(self.payloads,[])

    async def test_cancel_after_notes_write_discards_audio_and_never_replays(self):
        original=self.sy._request
        async def request(path,data=None):
            out=await original(path,data)
            if path.endswith('updateBlock'):
                turn=self.store.db.execute('select id from turns order by rowid desc limit 1').fetchone()[0]
                self.store.cancel('one',turn)
            return out
        self.sy._request=request
        self.calls=[('sy_update',{'document_id':DOC,'markdown':'Written before cancellation'})]
        first=await self.submit(); second=await self.submit()
        self.assertEqual(first['id'],second['id']); self.assertEqual(first['state'],'cancelled')
        self.assertEqual(sum(p.endswith('updateBlock') for p,d in self.syrequests),1)
        self.assertEqual(self.spoken,[])
        self.assertEqual((await self.client.get('/v1/turns/'+first['id']+'/audio',headers=self.headers)).status,403)

    async def test_search_sql_body_matching_and_injection_is_literal(self):
        import sqlite3
        db=sqlite3.connect(':memory:'); db.row_factory=sqlite3.Row
        db.execute('create table blocks(id,box,hpath,content,markdown,root_id,type,updated)')
        for ident,path in [(DOC,'/Normal/Ideas'),('20000101000002-abcdefg','/Private/Hidden'),('20000101000003-abcdefg','/zArchive/Hidden')]:
            db.execute('insert into blocks values(?,?,?,?,?,?,?,?)',(ident,NB,path,'Ideas','ordinary body',ident,'d','1'))
            db.execute('insert into blocks values(?,?,?,?,?,?,?,?)',(ident+'child',NB,path,'body anchor','body anchor',ident,'p','1'))
        original=self.sy._request
        async def request(path,data=None):
            if path.endswith('/sql'): return [dict(r) for r in db.execute(data['stmt'])]
            return await original(path,data)
        self.sy._request=request
        from unittest.mock import AsyncMock
        try:
            result=await self.sy.dispatch('sy_search',{'query':'body anchor'},AsyncMock())
            self.assertEqual([r['id'] for r in result['documents']],[DOC])
            result=await self.sy.dispatch('sy_search',{'query':"' OR 1=1 --"},AsyncMock())
            self.assertEqual(result['documents'],[])
        finally: db.close()

for name in list(dir(Base)):
    if name.startswith('test_') and name not in Notes.__dict__: setattr(Notes,name,None)
del Base
