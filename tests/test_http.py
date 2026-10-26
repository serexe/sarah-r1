"""Actual local HTTP tests, synthetic identities only. No upstream traffic."""
import tempfile
import unittest
from pathlib import Path
from aiohttp.test_utils import AioHTTPTestCase
from bridge.core import Store
from bridge.server import make_app

class HTTPTests(AioHTTPTestCase):
    async def get_application(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'state.db')
        self.s.provision('a','a'*48);self.s.provision('b','b'*48)
        return make_app(self.s)
    async def tearDownAsync(self):
        await super().tearDownAsync();self.s.close();self.tmp.cleanup()
    def auth(self,which='a'):return {'Authorization':'Bearer '+which*48}
    async def test_auth_and_closed_health(self):
        self.assertEqual((await self.client.get('/v1/health')).status,403)
        r=await self.client.get('/v1/health',headers=self.auth());o=await r.json()
        self.assertTrue(o['connected']);self.assertFalse(o['ready'])
        self.assertEqual(o['reason'],'hermes_ingress_security_extension_required')
    async def test_no_generic_proxy_or_overrides(self):
        for value in [{'session_id':'foreign'},{'url':'http://127.0.0.1:8642'},{'tool':'terminal'},{'model':'paid'},{'profile':'other'},{'file':'/etc/passwd'}]:
            r=await self.client.post('/v1/conversations',json=value,headers=self.auth());self.assertEqual(r.status,403)
        self.assertEqual((await self.client.get('/api/sessions',headers=self.auth())).status,404)
    async def test_audio_refused_before_transcription_or_upstream(self):
        r=await self.client.post('/v1/turns',data=b'synthetic invalid audio',headers=self.auth())
        self.assertEqual(r.status,503)
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM turns').fetchone()[0],0)
    async def test_poll_cancel_cross_owner_and_revocation(self):
        c=self.s.conversation('a');t=self.s.admit('a',c,'fixture-1','fixture')
        for suffix,method in [('',self.client.get),('/cancel',self.client.post)]:
            r=await method('/v1/turns/'+t+suffix,headers=self.auth('b'),json={} if suffix else None)
            self.assertEqual(r.status,403)
        r=await self.client.post('/v1/turns/'+t+'/cancel',headers=self.auth(),json={});self.assertEqual(r.status,200)
        self.assertEqual((await r.json())['state'],'cancelled')
        self.s.revoke('a');self.assertEqual((await self.client.get('/v1/turns/'+t,headers=self.auth())).status,403)

if __name__=='__main__':unittest.main()
