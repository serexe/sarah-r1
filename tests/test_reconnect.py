"""Accepted response discarded: actual authenticated bridge, no external provider."""
import asyncio
import io
import tempfile
import unittest
import wave
from pathlib import Path
from aiohttp.test_utils import AioHTTPTestCase
from bridge.core import Store
from bridge.server import make_app

class Adapter:
    ready=True
    calls=0
    def transcribe(self, path):return 'synthetic'
    async def reply(self, text, history):
        self.calls+=1
        await asyncio.sleep(0.05)
        return 'reply'
    async def speak(self, text, path):pass

class ReconnectTests(AioHTTPTestCase):
    async def get_application(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'state.db')
        self.s.provision('a','a'*48);self.s.provision('b','b'*48)
        self.adapter=Adapter();return make_app(self.s,self.adapter)
    async def tearDownAsync(self):
        await super().tearDownAsync();self.s.close();self.tmp.cleanup()
    def auth(self, who='a'):return {'Authorization':'Bearer '+who*48}
    async def test_lost_202_lookup_restart_cancel_ownership(self):
        c=self.s.conversation('a');f=io.BytesIO()
        with wave.open(f,'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0'*8000)
        headers=dict(self.auth(),**{'X-Conversation':c,'Idempotency-Key':'lost-202','Content-Type':'audio/wav'})
        response=await self.client.post('/v1/turns',data=f.getvalue(),headers=headers)
        self.assertEqual(response.status,202);response.release() # deliberately do not consume turn ID
        r=await self.client.get('/v1/requests/lost-202',headers=self.auth());self.assertEqual(r.status,200)
        turn=(await r.json())['id']
        self.assertEqual((await self.client.get('/v1/requests/lost-202')).status,403)
        self.assertEqual((await self.client.get('/v1/requests/lost-202',headers=self.auth('b'))).status,403)
        self.assertEqual((await self.client.get('/v1/requests/absent',headers=self.auth())).status,403)
        await self.client.post('/v1/turns/'+turn+'/cancel',headers=self.auth(),json={})
        await asyncio.sleep(.08)
        self.assertEqual(self.s.get('a',turn)['state'],'cancelled')
        self.assertLessEqual(self.adapter.calls,1)
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM turns').fetchone()[0],1)
        fresh=self.s.conversation('a');self.assertNotEqual(c,fresh)
        reopened=Store(self.s.path);reopened.recover()
        self.assertEqual(reopened.by_request('a','lost-202')['id'],turn);reopened.close()
        self.s.revoke('a');self.assertEqual((await self.client.get('/v1/requests/lost-202',headers=self.auth())).status,403)
    async def test_restart_uncertain_lookup_never_dispatches(self):
        c=self.s.conversation('a');t=self.s.admit('a',c,'interrupted','fingerprint');self.s.recover()
        r=await self.client.get('/v1/requests/interrupted',headers=self.auth());self.assertEqual(r.status,200)
        self.assertEqual((await r.json())['state'],'uncertain');self.assertEqual(self.adapter.calls,0)
        self.assertEqual(self.s.get('a',t)['state'],'uncertain')
