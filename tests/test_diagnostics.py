import copy,json,tempfile,time,unittest,sqlite3,os
from pathlib import Path
from aiohttp.test_utils import AioHTTPTestCase
from bridge.core import Store
from bridge.server import make_app
from bridge.diagnostics import Reports,validate,Invalid,Quota

def payload():
 p=dict(schema=1,appVersion=41,phase='uncertain',serverError='not_found',httpStatus=403,audioNext=2,chunkInFlight=True)
 for k in ['request','turn','conversation']:p.update({k+'Present':True,k+'Length':32,k+'Hash':'abcdef012345'})
 return p
class HTTP(AioHTTPTestCase):
 async def get_application(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=Store(self.root/'state.db');self.s.provision('a','a'*48);self.s.provision('b','b'*48);return make_app(self.s)
 async def tearDownAsync(self):
  await super().tearDownAsync();self.s.close();self.tmp.cleanup()
 def auth(self,k='a'):return {'Authorization':'Bearer '+k*48}
 async def test_auth_owner_notfound_and_receipt(self):
  for headers in [{},self.auth('x')]:self.assertEqual((await self.client.post('/v1/diagnostics',json=payload(),headers=headers)).status,403)
  self.assertFalse((self.root/'diagnostics').exists())
  self.assertEqual((await self.client.get('/v1/requests/absent',headers=self.auth())).status,403)
  r=await self.client.post('/v1/diagnostics',json=payload(),headers=self.auth());self.assertEqual(r.status,201);code=(await r.json())['receipt'];self.assertRegex(code,'^[A-F0-9]{24}$')
  self.assertEqual(r.headers['Cache-Control'],'no-store')
  self.assertEqual((await self.client.get('/v1/diagnostics/'+code)).status,403)
  self.assertEqual((await self.client.get('/v1/diagnostics/'+code,headers=self.auth('b'))).status,404)
  r=await self.client.get('/v1/diagnostics/'+code,headers=self.auth());self.assertEqual((await r.json())['report'],payload())
  self.assertEqual((self.root/'diagnostics').stat().st_mode&0o777,0o700);self.assertEqual((self.root/'diagnostics/reports.sqlite3').stat().st_mode&0o777,0o600)
  self.assertEqual(self.s.db.execute('select count(*) from turns').fetchone()[0],0)
 async def test_rejection_before_storage(self):
  for k,v in [('rawToken','secret'),('phase','https://secret'),('serverError','private transcript'),('httpStatus',True),('audioNext',33),('requestHash','RAW_ID'),('schema',1.0),('requestLength',-1),('chunkInFlight','false'),('appVersion',{'secret':'audio'})]:
   p=payload();p[k]=v;r=await self.client.post('/v1/diagnostics',json=p,headers=self.auth());self.assertEqual(r.status,400,(k,await r.text()))
  self.assertFalse((self.root/'diagnostics').exists())
  r=await self.client.post('/v1/diagnostics',data=b'x'*8193,headers={**self.auth(),'Content-Type':'application/json'});self.assertEqual(r.status,413)
  r=await self.client.post('/v1/diagnostics',data='{"schema":1,"schema":1}',headers={**self.auth(),'Content-Type':'application/json'});self.assertEqual(r.status,400)
  r=await self.client.post('/v1/diagnostics',data='{}',headers=self.auth());self.assertEqual(r.status,400)
 async def test_quota_does_not_block_commands(self):
  for _ in range(5):self.assertEqual((await self.client.post('/v1/diagnostics',json=payload(),headers=self.auth())).status,201)
  self.assertEqual((await self.client.post('/v1/diagnostics',json=payload(),headers=self.auth())).status,429)
  self.assertEqual((await self.client.get('/v1/health',headers=self.auth())).status,200)
class Storage(unittest.TestCase):
 def test_retention_and_per_owner_bound(self):
  with tempfile.TemporaryDirectory() as d:
   s=Reports(d);now=int(time.time());codes=[s.submit('a',payload(),now-25*4000+i*4000) for i in range(25)]
   with s.connect() as db:self.assertEqual(db.execute('select count(*) from reports').fetchone()[0],20)
   s.submit('b',payload(),now+8*86400)
   with s.connect() as db:self.assertEqual(db.execute('select count(*) from reports').fetchone()[0],1)
 def test_global_bound(self):
  with tempfile.TemporaryDirectory() as d:
   s=Reports(d)
   for i in range(1002):s.submit(str(i),payload())
   with s.connect() as db:self.assertEqual(db.execute('select count(*) from reports').fetchone()[0],1000)
if __name__=='__main__':unittest.main()
