import asyncio, io, tempfile, unittest, wave
from pathlib import Path
from aiohttp.test_utils import AioHTTPTestCase
from bridge.core import Store
from bridge.server import make_app

class ChunkHTTPTests(AioHTTPTestCase):
 async def get_application(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'state.db');self.store.provision('test','a'*48)
  self.c=self.store.conversation('test');self.generated=[];self.block=False;self.native=asyncio.Event();self.cleaned=asyncio.Event()
  owner=self
  class Adapter:
   ready=True
   def transcribe(self,path):return 'Tell a story'
   async def reply(self,*args):return 'One. Two. Three.'
   async def speak(self,text,path):
    owner.generated.append(text)
    if owner.block and len(owner.generated)==2:
     owner.native.set()
     try:await asyncio.Event().wait()
     finally:await asyncio.sleep(.05);owner.cleaned.set()
    path.write_bytes(text.encode())
  return make_app(self.store,Adapter())
 async def tearDownAsync(self):
  await super().tearDownAsync();self.store.close();self.tmp.cleanup()
 def headers(self,**extra):return {'Authorization':'Bearer '+'a'*48,**extra}
 async def submit(self,key):
  out=io.BytesIO()
  with wave.open(out,'wb') as w:w.setparams((1,2,16000,0,'NONE',''));w.writeframes(b'\0\0'*16000)
  r=await self.client.post('/v1/turns',data=out.getvalue(),headers=self.headers(**{'Content-Type':'audio/wav','X-Conversation':self.c,'Idempotency-Key':key,'X-Audio-Chunks':'sentence-mp3-v1'}))
  self.assertEqual(r.status,202);return (await r.json())['turn']
 async def row(self,t,after=0):
  r=await self.client.get('/v1/turns/'+t,headers=self.headers(**{'X-Audio-After':str(after)}));self.assertEqual(r.status,200);return await r.json()
 async def test_order_backpressure_ack_and_done(self):
  t=await self.submit('order');await asyncio.sleep(.1)
  row=await self.row(t);self.assertEqual(row['state'],'speaking');self.assertEqual(row['audio_chunks']['count'],2)
  self.assertEqual(self.generated,['One.','Two.'])
  for seq,text in enumerate(['One.','Two.','Three.']):
   for _ in range(30):
    row=await self.row(t,seq)
    if row['audio_chunks']['count']>seq:break
    await asyncio.sleep(.01)
   r=await self.client.get(f'/v1/turns/{t}/audio/{seq}',headers=self.headers());self.assertEqual(await r.read(),text.encode());self.assertEqual(r.content_type,'audio/mpeg')
  await self.row(t,3);await asyncio.sleep(.1)
  self.assertEqual((await self.row(t,3))['state'],'done')
  self.assertEqual(self.generated,['One.','Two.','Three.'])
 async def test_stop_clears_chunks_joins_generation_and_followup(self):
  self.block=True;t=await self.submit('stop');await asyncio.wait_for(self.native.wait(),1)
  for _ in range(2):
   r=await self.client.post(f'/v1/turns/{t}/cancel',json={},headers=self.headers());self.assertEqual(r.status,200)
  self.assertEqual((await self.row(t))['state'],'cancelled')
  r=await self.client.get(f'/v1/turns/{t}/audio/0',headers=self.headers());self.assertEqual(r.status,403)
  await asyncio.wait_for(self.cleaned.wait(),1);await asyncio.sleep(.05)
  self.assertEqual(self.generated,['One.','Two.'])
  self.assertFalse(list((Path(self.tmp.name)/'media').glob(t+'.*.mp3')))
  self.block=False;await self.submit('next')
