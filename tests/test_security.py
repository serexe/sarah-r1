"""Synthetic fixtures only. No live Hermes/HA/model/audio calls."""
import hashlib
import io
import tempfile
import unittest
import wave
from pathlib import Path
from bridge.core import Store, Conflict, Denied, validate_audio, BlockedHermes

class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'state.db'
        self.s = Store(self.path)
        self.s.provision('device-a', 'a'*48)
        self.s.provision('device-b', 'b'*48)
        self.c = self.s.conversation('device-a')
    def tearDown(self):
        self.s.close(); self.tmp.cleanup()
    def test_token_revocable_and_hashed(self):
        self.assertEqual(self.s.authenticate('a'*48),'device-a')
        self.assertNotIn(b'a'*48, self.path.read_bytes())
        self.s.revoke('device-a')
        with self.assertRaises(Denied):self.s.authenticate('a'*48)
    def test_cross_device_denied(self):
        with self.assertRaises(Denied):self.s.admit('device-b',self.c,'req-1','hash')
    def test_durable_dedup_and_payload_conflict(self):
        one=self.s.admit('device-a',self.c,'req-1','hash')
        self.s.close(); self.s=Store(self.path)
        self.assertEqual(one,self.s.admit('device-a',self.c,'req-1','hash'))
        with self.assertRaises(Conflict):self.s.admit('device-a',self.c,'req-1','changed')
    def test_serialized_turns(self):
        one=self.s.admit('device-a',self.c,'req-1','hash')
        with self.assertRaises(Conflict):self.s.admit('device-a',self.c,'req-2','hash')
        self.s.finish('device-a',one,'error','blocked')
        self.assertNotEqual(one,self.s.admit('device-a',self.c,'req-2','hash'))
    def test_ownership_applies_poll_and_cancel(self):
        one=self.s.admit('device-a',self.c,'req-1','hash')
        for fn in [self.s.get,self.s.cancel]:
            with self.assertRaises(Denied):fn('device-b',one)
    def test_cancel_truth_and_late_result(self):
        one=self.s.admit('device-a',self.c,'req-1','hash')
        self.s.cancel('device-a',one)
        self.s.finish('device-a',one,'done','late answer')
        result=self.s.get('device-a',one)
        self.assertEqual(result['state'],'cancelled')
        self.assertIn('not undo',result['detail'])
    def test_restart_never_redispatches(self):
        one=self.s.admit('device-a',self.c,'req-1','hash')
        self.s.recover()
        self.assertEqual(self.s.get('device-a',one)['state'],'uncertain')
        self.assertEqual(one,self.s.admit('device-a',self.c,'req-1','hash'))
        with self.assertRaises(Conflict):self.s.admit('device-a',self.c,'req-2','hash')
    def test_confirmation_bound_atomic_single_use(self):
        one=self.s.admit('device-a',self.c,'req-1','hash')
        action={'tool':'ha_call_service','domain':'lock','service':'unlock','entity_id':'lock.front'}
        nonce=self.s.offer('device-a',one,action,now=100)
        for dev,run,act,t in [('device-b',one,action,101),('device-a',one,{**action,'entity_id':'lock.back'},101),('device-a',one,action,161)]:
            with self.assertRaises(Denied):self.s.claim(dev,run,nonce,act,now=t)
        self.s.claim('device-a',one,nonce,action,now=101)
        with self.assertRaises(Denied):self.s.claim('device-a',one,nonce,action,now=102)
    def test_cancel_invalidates_pending_confirmation(self):
        one=self.s.admit('device-a',self.c,'req-1','hash')
        action={'tool':'ha_call_service','domain':'lock','service':'unlock','entity_id':'lock.front'}
        nonce=self.s.offer('device-a',one,action,now=100)
        self.s.cancel('device-a',one)
        with self.assertRaises(Denied):self.s.claim('device-a',one,nonce,action,now=101)
    def test_terminal_cannot_offer_confirmation(self):
        one=self.s.admit('device-a',self.c,'req-1','hash')
        self.s.finish('device-a',one,'error','blocked')
        with self.assertRaises(Denied):self.s.offer('device-a',one,{'tool':'anything'},now=100)
    def test_capability_fail_closed(self):
        adapter=BlockedHermes()
        self.assertFalse(adapter.ready)
        with self.assertRaises(Denied):adapter.submit('anything')
    def test_wav_validation(self):
        f=io.BytesIO()
        with wave.open(f,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*16000)
        self.assertAlmostEqual(validate_audio(f.getvalue()),1)
        for bad in [b'not audio',b'',b'0'*(4*1024*1024+1)]:
            with self.assertRaises(Denied):validate_audio(bad)

if __name__=='__main__':unittest.main()
