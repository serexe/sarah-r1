"""Offline R1 calendar CRUD and safety; never live mutations."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from bridge.calendar import CalendarDispatcher, CALENDAR_ID

EVENT={'id':'abc123','summary':'Dentist','start':{'dateTime':'2026-10-25T10:00:00+00:00','timeZone':'UTC'},'end':{'dateTime':'2026-10-25T11:00:00+00:00','timeZone':'UTC'},'etag':'"v1"'}
class CalendarRW(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.c=CalendarDispatcher('synthetic',CALENDAR_ID,Path(self.tmp.name))
        self.event=dict(EVENT); self.calls=[]; self.failwrite=False; self.mismatch=False
        async def request(method,path='',data=None,params=None,etag=None):
            self.calls.append((method,path,data,params,etag))
            if path=='/users/me/calendarList': return {'items':[{'id':CALENDAR_ID,'accessRole':'owner'}]}
            if method=='GET': return ({'items':[self.event]} if not path else (self.event or {'status':'cancelled','id':'abc123'}))
            if self.failwrite: raise RuntimeError('calendar_http_error')
            if method=='DELETE': self.event=None; return None
            self.event=dict(EVENT,**(data if not self.mismatch else {})); return self.event
        self.c._request=request
        self.claim=AsyncMock(return_value=True)
    async def test_list_read_create_update_delete_verified(self):
        result=await self.c.dispatch('calendar_list',{'time_min':'2026-10-25T00:00:00-05:00','time_max':'2026-10-26T00:00:00-05:00'},self.claim)
        self.assertEqual(len(result['events']),1)
        self.assertEqual((await self.c.dispatch('calendar_read',{'event_id':'abc123'},self.claim))['event']['id'],'abc123')
        for name,args in [('calendar_create',{k:EVENT[k] for k in ('summary','start','end')}),('calendar_update',{'event_id':'abc123','changes':{'summary':'Changed'}}),('calendar_delete',{'event_id':'abc123','expected_summary':'Changed'})]:
            out=await self.c.dispatch(name,args,self.claim); self.assertTrue(out['verified'],out)
        self.assertEqual(len(list(Path(self.tmp.name).glob('*.json'))),1)
    async def test_empty_calendar_id_rejected(self):
        with self.assertRaises(ValueError): CalendarDispatcher('synthetic','',Path(self.tmp.name))
    async def test_all_day_create_and_unsafe_fields(self):
        out=await self.c.dispatch('calendar_create',{'summary':'Visit','start':{'date':'2026-10-25'},'end':{'date':'2026-10-26'}},self.claim)
        self.assertTrue(out['verified'],out)
        out=await self.c.dispatch('calendar_create',{'summary':'Visit','start':{'date':'2026-10-25'},'end':{'date':'2026-10-26'},'calendar_id':'other'},self.claim)
        self.assertFalse(out['dispatched'])
    async def test_cancel_fail_mismatch_no_retry(self):
        args={'event_id':'abc123','changes':{'summary':'Changed'}}
        self.claim.return_value=False
        self.assertFalse((await self.c.dispatch('calendar_update',args,self.claim))['dispatched'])
        self.assertFalse(any(c[0]=='PATCH' for c in self.calls))
        self.claim.return_value=True; self.failwrite=True
        result=await self.c.dispatch('calendar_update',args,self.claim)
        self.assertTrue(result['dispatched']); self.assertFalse(result['verified'])
        self.assertEqual(sum(c[0]=='PATCH' for c in self.calls),1)
        self.failwrite=False; self.mismatch=True
        self.assertFalse((await self.c.dispatch('calendar_update',args,self.claim))['verified'])
    async def test_delete_exact_single_nonrecurring_and_schema(self):
        for args in ({'event_id':'abc123','expected_summary':'Other'},{'event_id':['abc123'],'expected_summary':'Dentist'},{'event_id':'abc123','expected_summary':'Dentist','calendar_id':'primary'}):
            self.assertFalse((await self.c.dispatch('calendar_delete',args,self.claim))['dispatched'])
        self.event['recurrence']=['RRULE:FREQ=DAILY']
        self.assertFalse((await self.c.dispatch('calendar_delete',{'event_id':'abc123','expected_summary':'Dentist'},self.claim))['dispatched'])
        self.assertFalse(any(c[0]=='DELETE' for c in self.calls))
    async def test_missing_owner_and_invalid_dates_fail_closed(self):
        original=self.c._request
        async def request(method,path='',**kwargs):
            return {'items':[{'id':CALENDAR_ID,'accessRole':'reader'}]} if path=='/users/me/calendarList' else await original(method,path,**kwargs)
        self.c._request=request
        out=await self.c.dispatch('calendar_create',{k:EVENT[k] for k in ('summary','start','end')},self.claim)
        self.assertFalse(out['dispatched'])
        self.c._request=original
        for changes in ({'start':{'dateTime':'2026-10-25T10:00:00'},'end':EVENT['end']},{'start':EVENT['end'],'end':EVENT['start']},{'attendees':[]}):
            self.assertFalse((await self.c.dispatch('calendar_update',{'event_id':'abc123','changes':changes},self.claim))['dispatched'])
