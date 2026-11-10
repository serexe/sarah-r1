"""Offline exact owner/terminal clarification wire; no live model or integration."""
import asyncio
import io
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from aiohttp.test_utils import TestClient,TestServer
from bridge.core import Store,Denied,Conflict
from bridge.server import make_app

class ClarificationWireTest(unittest.IsolatedAsyncioTestCase):
 async def test_installed_no_tool_classifier_binding(self):
  import subprocess,sys
  script='''
import asyncio,os,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,os.environ.get('HERMES_SOURCE','/opt/hermes-agent'))
from bridge import acp_launcher
from hermes_state import SessionDB
async def main():
 db=SessionDB(db_path=Path(sys.argv[1])/'state.db')
 home=Path(sys.argv[1])/'global';home.mkdir()
 (home/'config.yaml').write_text('model:\\n  provider: openrouter\\n  default: vendor/offline\\n')
 dedicated=Path(sys.argv[1])/'dedicated';dedicated.mkdir()
 (dedicated/'config.yaml').write_bytes(Path('bridge/sarah-acp.yaml').read_bytes())
 (dedicated/'SOUL.md').write_bytes(acp_launcher.REVIEWED_SOUL)
 os.environ['HERMES_HOME']=str(dedicated)
 from run_agent import AIAgent
 resolver=lambda **kw: {'provider':'openrouter','api_mode':'chat_completions','base_url':'https://openrouter.ai/api/v1','api_key':'offline-placeholder'}
 with patch.object(acp_launcher,'GLOBAL_HOME',home):
  server=acp_launcher.compose(asyncio.get_running_loop(),db,resolver)
  state=server.session_manager.create_session(cwd=sys.argv[1]);nonce='a'*64
 state.agent._sarah_nonce=nonce
 params={'sessionId':state.session_id,'nonce':nonce,'utterance':'Tell me about the room','answer':'Which room?'}
 def classify(agent,prompt,**kw):
  assert agent.tools==[] and agent.valid_tool_names==set() and agent._fallback_chain==[]
  assert kw['conversation_history']==[]
  return {'final_response':'{"reply_expected":true}'}
 with patch.object(AIAgent,'run_conversation',classify):
  assert await server.ext_method('sarah/clarification',params)=={'reply_expected':True}
  # Model still decides semantics: policy must cover solicited conversational
  # questions, not only missing facts, without accepting quoted questions.
  prompt=state.agent._sarah_clarifier.ephemeral_system_prompt
  assert 'explicitly asks the assistant to ask them a question' in prompt
  assert 'quoted or hypothetical questions not addressed to the user' in prompt
  solicited={**params,'utterance':'Ask me a question.',
    'answer':'If you could instantly master any skill, what would you choose?'}
  assert await server.ext_method('sarah/clarification',solicited)=={'reply_expected':True}
  try:await server.ext_method('sarah/clarification',{**params,'nonce':'b'*64})
  except ValueError as e:assert str(e)=='acp_clarification_binding_denied'
  else:raise AssertionError('foreign nonce accepted')
  state.is_running=True
  try:await server.ext_method('sarah/clarification',params)
  except ValueError:pass
  else:raise AssertionError('inflight prompt accepted')
  state.is_running=False
 def malformed(agent,prompt,**kw):return {'final_response':'yes'}
 with patch.object(AIAgent,'run_conversation',malformed):
  assert await server.ext_method('sarah/clarification',params)=={'reply_expected':False}
asyncio.run(main())
'''
  with tempfile.TemporaryDirectory() as home:
   result=subprocess.run([sys.executable,'-B','-c',script,home],
    env={'HOME':str(Path.home()),'HERMES_HOME':home,'PATH':'/usr/bin:/bin',
         'HERMES_SOURCE':__import__('os').environ.get('HERMES_SOURCE','/opt/hermes-agent')},
    capture_output=True,text=True,timeout=30)
   self.assertEqual(result.returncode,0,result.stdout+result.stderr)

 async def test_bound_terminal_marker_and_same_conversation(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'state.db')
   store.provision('lenovo','a'*48);store.provision('foreign','b'*48)
   conversation=store.conversation('lenovo')
   calls=[]
   async def reply(text,history,*,device,conversation,dispatch,clarification):
    calls.append((text,conversation))
    return ('Which room do you mean?',await clarification('Which room do you mean?'))
   async def intent(**kw):
    return kw['utterance']=='turn one'
   async def speak(text,path):path.write_bytes(b'fixture')
   adapter=SimpleNamespace(ready=True,reason='fixture',transcribe=lambda _:('turn one' if len(calls)==0 else 'kitchen'),
      reply_turn=reply,clarification_intent=intent,speak=speak)
   client=TestClient(TestServer(make_app(store,adapter)));await client.start_server()
   buf=io.BytesIO()
   with wave.open(buf,'wb') as out:
    out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(b'\0\0'*16000)
   headers={'Authorization':'Bearer '+'a'*48,'Content-Type':'audio/wav','X-Conversation':conversation}
   try:
    health=await (await client.get('/v1/health',headers=headers)).json()
    self.assertEqual(health['protocol'],2)
    self.assertIs(health['clarification_reply_expected'],True)
    parent=None
    for index,expected in ((1,True),(2,False)):
     row={}
     sent=await client.post('/v1/turns',data=buf.getvalue(),headers={**headers,'Idempotency-Key':f'request-{index}',**({'X-Clarification-Parent':parent} if parent else {})})
     self.assertEqual(sent.status,202)
     turn=(await sent.json())['turn']
     for _ in range(100):
      row=await (await client.get('/v1/turns/'+turn,headers=headers)).json()
      if row['state']=='done':break
      await asyncio.sleep(.01)
     self.assertEqual(row['state'],'done')
     if index==1:parent=turn
     self.assertIs(row['reply_expected'],expected)
     self.assertEqual(row['conversation'],conversation)
     self.assertEqual(row['detail'],'Which room do you mean?')
     lookup=await (await client.get(f'/v1/requests/request-{index}',headers=headers)).json()
     self.assertIs(lookup['reply_expected'],expected)
     self.assertEqual((await client.get('/v1/turns/'+turn,headers={'Authorization':'Bearer '+'b'*48})).status,403)
    self.assertEqual(len(calls),2)
    self.assertEqual(calls[1][1],conversation)
    self.assertEqual(store.db.execute('SELECT clarification_parent FROM turns WHERE id=?',(turn,)).fetchone()[0],parent)
    reused=await client.post('/v1/turns',data=buf.getvalue(),headers={**headers,'Idempotency-Key':'request-three','X-Clarification-Parent':parent})
    self.assertEqual(reused.status,403)
    self.assertEqual(store.db.execute('SELECT count(*) FROM turns').fetchone()[0],2)
   finally:
    await client.close();store.close()

 async def test_uncertain_confirmation_and_action_never_exposed(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'state.db');store.provision('owner','a'*48);store.provision('foreign','b'*48)
   c=store.conversation('owner');t=store.admit('owner',c,'first','hash')
   self.assertFalse(store.get('owner',t)['reply_expected'])
   with self.assertRaises(Denied):store.expect_reply('foreign',t,c)
   store.finish('owner',t,'speaking','question')
   store.offer('owner',t,{'name':'something'},0)
   self.assertFalse(store.expect_reply('owner',t,c))
   store.finish('owner',t,'done','question')
   self.assertFalse(store.get('owner',t)['reply_expected'])
   t2=store.admit('owner',c,'second','hash')
   store.finish('owner',t2,'speaking','question')
   self.assertTrue(store.expect_reply('owner',t2,c))
   self.assertFalse(store.get('owner',t2)['reply_expected']) # nonterminal hidden
   store.cancel('owner',t2,dispatch_pending=True)
   self.assertFalse(store.get('owner',t2)['reply_expected'])
   with self.assertRaises(Conflict):store.admit('owner',c,'third','hash',parent=t2)
   with self.assertRaises(Denied):store.get('foreign',t2)
   store.close()

 async def test_expired_parent_rejected_without_new_turn(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'state.db');store.provision('owner','a'*48)
   c=store.conversation('owner');parent=store.admit('owner',c,'first','hash')
   store.finish('owner',parent,'speaking','question')
   self.assertTrue(store.expect_reply('owner',parent,c))
   store.finish('owner',parent,'done','question')
   store.db.execute('UPDATE turns SET reply_expected_until=0 WHERE id=?',(parent,))
   with self.assertRaises(Denied):store.admit('owner',c,'second','hash',parent=parent)
   self.assertEqual(store.db.execute('SELECT count(*) FROM turns').fetchone()[0],1)
   store.close()

 async def test_spoken_answer_cannot_approve_action(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'state.db');store.provision('owner','a'*48)
   conversation=store.conversation('owner');parent=store.admit('owner',conversation,'first','hash')
   store.finish('owner',parent,'speaking','Which room?')
   self.assertTrue(store.expect_reply('owner',parent,conversation))
   store.finish('owner',parent,'done','Which room?')
   calls=[]
   async def reply(text,history,*,dispatch,**kw):
    calls.append(await dispatch('ha_call_service',{'domain':'lock','service':'unlock','entity_id':'lock.front'}))
    return ('Yes, unlocking',True)
   async def speak(text,path):path.write_bytes(b'fixture')
   adapter=SimpleNamespace(ready=True,reason='fixture',transcribe=lambda _: 'yes',reply_turn=reply,speak=speak)
   client=TestClient(TestServer(make_app(store,adapter)));await client.start_server()
   wav=io.BytesIO()
   with wave.open(wav,'wb') as out:
    out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(b'\0\0'*16000)
   headers={'Authorization':'Bearer '+'a'*48,'Content-Type':'audio/wav','X-Conversation':conversation,
     'X-Clarification-Parent':parent,'Idempotency-Key':'second'}
   try:
    sent=await client.post('/v1/turns',data=wav.getvalue(),headers=headers)
    self.assertEqual(sent.status,202)
    turn=(await sent.json())['turn']
    row={}
    poll_headers={key:value for key,value in headers.items() if key not in ('X-Clarification-Parent','Content-Type')}
    for _ in range(100):
     row=await (await client.get('/v1/turns/'+turn,headers=poll_headers)).json()
     if row['state']=='done':break
     await asyncio.sleep(.01)
    self.assertEqual(row['state'],'done')
    self.assertFalse(row['reply_expected'])
    self.assertEqual(row['detail'],'Action not dispatched from spoken clarification. Ask a new command or use on-screen confirmation.')
    self.assertEqual(len(calls),1)
    self.assertEqual(store.db.execute('SELECT count(*) FROM dispatches').fetchone()[0],0)
   finally:
    await client.close();store.close()

if __name__=='__main__':unittest.main()
