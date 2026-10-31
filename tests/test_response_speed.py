import asyncio, io, tempfile, unittest, wave
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from aiohttp.test_utils import AioHTTPTestCase
from bridge.core import Store
from bridge.server import make_app
from bridge.direct_clock import direct_clock

class ClockTests(unittest.TestCase):
 def test_dst_midnight_and_date(self):
  with patch.dict('os.environ', {'R1_TIMEZONE':'America/Chicago'}):
   for stamp, expected in [('2026-11-01T06:30:00+00:00',"It's 1:30 AM CDT."),('2026-11-01T07:30:00+00:00',"It's 1:30 AM CST."),('2026-10-30T05:00:00+00:00',"It's 12:00 AM CDT."),('2026-10-30T17:00:00+00:00',"It's 12:00 PM CDT.")]:
    self.assertEqual(direct_clock('What time is it?',now=datetime.fromisoformat(stamp)),expected)
   self.assertEqual(direct_clock("What's today's date?",now=datetime.fromisoformat('2026-10-30T03:00:00+00:00')),'Today is Thursday, October 29, 2026.')
 def test_conservative_negatives(self):
  for s in ['what time is it and unlock the door','what time is it in London','say “what time is it”','"what time is it?"','what time is my meeting','what about tomorrow','set a timer','what date was that','what time is it? unlock the door','what time is it??']:
   self.assertIsNone(direct_clock(s),s)
  with patch.dict('os.environ', {'R1_TIMEZONE':'invalid/zone'}):self.assertIsNone(direct_clock('What time is it?'))

class HTTPClockTests(AioHTTPTestCase):
 async def get_application(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'state.db');self.store.provision('test','a'*48)
  self.conversation=self.store.conversation('test');self.text='What time is it?';self.calls=[];self.spoken=[];self.block=False;self.speaking=asyncio.Event()
  owner=self
  class Adapter:
   ready=True
   def transcribe(self,path):return owner.text
   async def reply(self,text,history,**kw):owner.calls.append((text,history));return 'Normal model answer'
   async def speak(self,text,path):
    owner.spoken.append(text);owner.speaking.set()
    if owner.block:await asyncio.Event().wait()
    path.write_bytes(b'test only')
  return make_app(self.store,Adapter())
 async def tearDownAsync(self):
  await super().tearDownAsync();self.store.close();self.tmp.cleanup()
 async def submit(self,key):
  out=io.BytesIO()
  with wave.open(out,'wb') as w:w.setparams((1,2,16000,0,'NONE',''));w.writeframes(b'\0\0'*16000)
  r=await self.client.post('/v1/turns',data=out.getvalue(),headers={'Authorization':'Bearer '+'a'*48,'Content-Type':'audio/wav','X-Conversation':self.conversation,'Idempotency-Key':key})
  self.assertEqual(r.status,202);return (await r.json())['turn']
 async def row(self,t):
  r=await self.client.get('/v1/turns/'+t,headers={'Authorization':'Bearer '+'a'*48});return await r.json()
 async def test_clock_same_voice_history_fallback_and_timings(self):
  t=await self.submit('first')
  for _ in range(20):
   row=await self.row(t)
   if row['state']=='done':break
   await asyncio.sleep(.01)
  self.assertEqual(row['state'],'done');self.assertEqual(self.calls,[]);self.assertEqual(row['detail'],self.spoken[0]);self.assertEqual(row['transcript'],self.text)
  self.assertEqual(row['timings']['route'],'direct_clock');self.assertEqual(row['timings']['model_ms'],0)
  self.assertGreaterEqual(row['timings']['tts_ms'],0)
  self.text='What time is it in London?';t=await self.submit('second')
  for _ in range(20):
   row=await self.row(t)
   if row['state']=='done':break
   await asyncio.sleep(.01)
  self.assertEqual(self.calls[0][1][0]['content'],'What time is it?');self.assertEqual(row['detail'],'Normal model answer');self.assertEqual(row['timings']['route'],'model')
  self.assertEqual(self.store.db.execute('SELECT count(*) FROM dispatches').fetchone()[0],0)
 async def test_stop_during_direct_tts(self):
  self.block=True;t=await self.submit('stop');await asyncio.wait_for(self.speaking.wait(),2)
  r=await self.client.post('/v1/turns/'+t+'/cancel',json={},headers={'Authorization':'Bearer '+'a'*48});self.assertEqual(r.status,200)
  await asyncio.sleep(.02);self.assertEqual((await self.row(t))['state'],'cancelled');self.assertFalse((Path(self.tmp.name)/'media'/(t+'.mp3')).exists());self.assertEqual(self.calls,[])

class ACPClockTests(unittest.IsolatedAsyncioTestCase):
 async def test_local_history_before_first_model_and_uncertain_gate(self):
  from bridge.acp_runtime import ACPRuntime
  from bridge.acp_client import ACPError
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory() as tmp:
   s=Store(Path(tmp)/'state.db');s.provision('test','a'*48);c=s.conversation('test')
   a=ACPRuntime(s,'/not-used',SimpleNamespace(identity='test-policy',cwd='/isolated',timeout=2))
   make_app(s,SimpleNamespace(ready=True))
   a.check_direct_reply(device='test',conversation=c)
   t=s.admit('test',c,'clock','fixture');s.finish('test',t,'done',"It's 1:00 PM CDT.",'What time is it?')
   s.db.execute('INSERT INTO response_metrics VALUES(?,?,?)',(t,'direct_clock','{}'))
   a.check_direct_reply(device='test',conversation=c)
   prompts=[];contexts=[]
   class Client:
    async def initialize(self):return {'loadSession':True}
    async def request(self,name,params):
     if name=='_sarah/turn':contexts.append(params['dialogue'])
     if name=='_sarah/policy':
      from bridge.acp_policy import identity,SCHEMAS
      return {'policy':identity(),'schemas':SCHEMAS}
     return {'sessionId':'isolated-session'}
    async def prompt(self,session,text):prompts.append(text);return 'Normal reply'
    async def close(self):pass
   async def connect(config):return Client()
   with patch('bridge.acp_runtime.ACPClient.connect',connect):
    answer=await a.reply_turn('Repeat that time',[],device='test',conversation=c)
   self.assertEqual(answer,'Normal reply');self.assertEqual(contexts[0][1]['content'],"It's 1:00 PM CDT.");self.assertEqual(prompts[0],'Repeat that time')
   s.db.execute("UPDATE acp_sessions SET state='uncertain'")
   with self.assertRaisesRegex(ACPError,'acp_session_uncertain_or_changed'):a.check_direct_reply(device='test',conversation=c)
   await a.close();s.close()
