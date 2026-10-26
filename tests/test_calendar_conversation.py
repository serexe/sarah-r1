"""Offline natural SSE calendar routing, mutation ledger, truthful receipts."""
from aiohttp.test_utils import TestClient, TestServer
from test_full_ha import FullHA as Base
from test_calendar_rw import EVENT
from bridge.server import make_app
from bridge.calendar import CalendarDispatcher

class CalendarConversation(Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.cal=CalendarDispatcher('synthetic',backup_dir=self.tmp.name); self.calendar_calls=[]; self.event=dict(EVENT)
        async def request(method,path='',data=None,params=None,etag=None):
            self.calendar_calls.append((method,path,data))
            if path=='/users/me/calendarList': return {'items':[{'id':self.cal.calendar_id,'accessRole':'owner'}]}
            if method=='GET': return {'items':[self.event]} if not path else self.event
            self.event.update(data or {}); return self.event
        self.cal._request=request
        await self.client.close()
        self.client=TestClient(TestServer(make_app(self.store,self.adapter,self.dispatcher,calendar=self.cal))); await self.client.start_server()
    async def test_natural_calendar_read_retains_synthesis_schema(self):
        self.transcript='What is on my calendar tomorrow?'; self.prose='Dentist tomorrow morning.'
        self.calls=[('calendar_list',{'time_min':'2026-10-25T00:00:00-05:00','time_max':'2026-10-26T00:00:00-05:00'})]
        row=await self.submit(); self.assertEqual(row['detail'],self.prose)
        wire=self.wire[0]; self.assertEqual(wire['tool_choice'],'auto'); self.assertFalse(wire['parallel_tool_calls'])
        self.assertTrue({'calendar_create','calendar_update','calendar_delete'}<={t['name'] for t in wire['tools']})
        self.assertIn('UTC',wire['instructions'])
        self.assertIn('You are S.A.R.A.H, pronounced Sarah',wire['instructions'])
        self.assertNotIn('You are Hermes',wire['instructions'])
        self.assertIn('Current server time in UTC:',wire['instructions'])
        self.assertFalse(any(m!='GET' for m,p,d in self.calendar_calls))
    async def test_different_second_mutation_blocked_and_receipt_truth(self):
        self.transcript='Rename my dentist event to Checkup.'; self.prose='Deleted everything!'
        self.calls=[('calendar_update',{'event_id':'abc123','changes':{'summary':'Checkup'}}),('calendar_update',{'event_id':'abc123','changes':{'summary':'WRONG'}})]
        row=await self.submit(); self.assertIn('Updated Checkup',row['detail']); self.assertNotIn('abc123',row['detail']); self.assertNotIn(self.prose,row['detail'])
        self.assertEqual(sum(m=='PATCH' for m,p,d in self.calendar_calls),1)
        self.assertEqual(len(list(self.store.db.execute('select * from dispatches'))),1)

for name in list(dir(Base)):
    if name.startswith('test_') and name not in CalendarConversation.__dict__: setattr(CalendarConversation,name,None)
del Base
