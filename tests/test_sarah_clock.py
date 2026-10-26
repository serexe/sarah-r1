"""Offline speech/receipt regressions, using synthetic calendar fixtures."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from bridge import runtime
from bridge.runtime import speech_text
from test_calendar_rw import CalendarRW, EVENT

class ClockSpeech(unittest.IsolatedAsyncioTestCase):
    def test_clock_formats(self):
        cases={
            'At 3:30 PM.':'At three thirty P M.',
            'At 12:00 p.m.':'At noon',
            'At 12:00 AM.':'At midnight.',
            'At 3:05 pm.':'At three oh five P M.',
            'At 15:30.':'At three thirty P M.',
            'At 00:05.':'At twelve oh five A M.',
            'At 2026-10-24T20:30:00Z.':'At 2026-10-24 at eight thirty P M.',
            'At 2026-12-24T21:30:00+00:00.':'At 2026-12-24 at nine thirty P M.',
            'At 2026-10-24T15:30:00-04:00.':'At 2026-10-24 at seven thirty P M.',
            'At 2026-03-08T08:05:00Z.':'At 2026-03-08 at eight oh five A M.',
            'At 2026-11-01T07:05:00Z.':'At 2026-11-01 at seven oh five A M.',
            '**8:30–10:00 a.m.**':'eight thirty A M to ten A M',
            '**10:00–11:30 a.m.**':'ten A M to eleven thirty A M',
            'I am S.A.R.A.H.':'I am Sarah.',
        }
        for source,expected in cases.items():
            with self.subTest(source=source): self.assertEqual(speech_text(source),expected)
    def test_nonclock_preserved(self):
        text='2026-10-24; 30 minutes; duration 01:30; ratio 3:05; VI230620; gpt-6.1-sol; 1.05; 80%; `15:30`.'
        self.assertEqual(speech_text(text),text.replace('`',''))
        self.assertEqual(speech_text('$100.50 at 3:30 PM.'),'one hundred dollars and fifty cents at three thirty P M.')
    async def test_production_tts_stdin_clock_and_original_display(self):
        original='Test event on 2026-10-24 at 2026-10-24T22:00:00Z.'
        seen=[]
        async def process(*args,input=None,**kwargs):
            if input is not None: seen.append(input.decode())
            Path(args[-1]).write_bytes(b'offline audio fixture')
        with tempfile.TemporaryDirectory() as tmp, patch.object(runtime,'_tts_process',process):
            await runtime.VoiceRuntime.__new__(runtime.VoiceRuntime).speak(original,Path(tmp)/'out.mp3')
        self.assertEqual(seen,['Test event on 2026-10-24 at 2026-10-24 at ten P M.'])
        self.assertEqual(original,'Test event on 2026-10-24 at 2026-10-24T22:00:00Z.')

class HumanCalendarReceipts(CalendarRW):
    async def test_human_receipts_not_ids(self):
        for name,args,verb in [
            ('calendar_create',{k:EVENT[k] for k in ('summary','start','end')},'Added'),
            ('calendar_update',{'event_id':'abc123','changes':{'summary':'Checkup'}},'Updated'),
            ('calendar_delete',{'event_id':'abc123','expected_summary':'Checkup'},'Deleted')]:
            result=await self.c.dispatch(name,args,self.claim)
            self.assertTrue(result['verified'],result)
            self.assertEqual(result['event_id'],'abc123')
            self.assertTrue(result['reply'].startswith(verb),result)
            self.assertIn('Dentist' if verb=='Added' else 'Checkup',result['reply'])
            self.assertIn('10:00 AM',result['reply'])
            self.assertNotIn('abc123',result['reply'])
            self.assertNotIn('verified',result['reply'])
    async def test_read_converts_offset_to_configured_zone(self):
        self.event=dict(EVENT,start={'dateTime':'2026-10-25T15:00:00Z'})
        result=await self.c.dispatch('calendar_read',{'event_id':'abc123'},self.claim)
        self.assertEqual(result['event']['start']['dateTime'],'2026-10-25T15:00:00+00:00')
    async def test_failed_receipt_retains_uncertainty(self):
        self.failwrite=True
        result=await self.c.dispatch('calendar_update',{'event_id':'abc123','changes':{'summary':'Checkup'}},self.claim)
        self.assertFalse(result['verified'])
        self.assertIn('outcome not verified',result['reply'])
        self.assertNotIn('Updated',result['reply'])

for name in list(dir(CalendarRW)):
    if name.startswith('test_') and name not in HumanCalendarReceipts.__dict__: setattr(HumanCalendarReceipts,name,None)
del CalendarRW
