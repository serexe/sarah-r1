"""Exact physical transcripts, read prose and mixed boundary regressions."""
import json
from test_siyuan import Notes as Base, DOC

class ReadAnswers(Base):
    async def test_exact_lights_question_keeps_provider_summary(self):
        self.transcript='What lights are on?'
        self.calls=[('ha_list_entities',{'domain':'light'})]
        self.prose='Living Room, alpha and beta are on.'
        row=await self.submit()
        self.assertEqual(row['detail'],self.prose)
        result=json.loads(self.wire[-1]['input'][-1]['output'])
        self.assertIn('entities',result)
        self.assertEqual(self.payloads,[])

    async def test_exact_appliance_question_keeps_grounded_prose(self):
        self.transcript='What were my appliance choices for the house?'
        self.body='Appliances: Bosch dishwasher; induction range.'
        self.calls=[('sy_search',{'query':'appliance'}),('sy_read',{'document_id':DOC})]
        self.prose='Your note lists a Bosch dishwasher and induction range.'
        row=await self.submit()
        self.assertEqual(row['detail'],self.prose)
        self.assertIn(self.body,self.wire[-1]['input'][-1]['output'])
        self.assertFalse(any(p.endswith(('updateBlock','createDocWithMd')) for p,d in self.syrequests))

    async def test_mixed_reads_and_failed_write_keep_synthesis_and_truth(self):
        self.calls=[('sy_read',{'document_id':DOC}),self.action()]
        self.failpost=True
        self.prose='Your note says Original body. The light change could not be verified.'
        row=await self.submit()
        self.assertNotIn(self.prose,row['detail'])
        self.assertIn('Original body', str(self.wire[-1]['input']))
        self.assertIn('Outcome not verified. No automatic retry.',row['detail'])
        self.assertEqual(len(self.payloads),1)

    async def test_read_clarification_not_replaced(self):
        self.calls=[('sy_search',{'query':'ideas'})]
        self.prose='Do you mean the kitchen or laundry appliances?'
        self.assertEqual((await self.submit())['detail'],self.prose)

    async def test_appliance_sql_matches_real_internal_parser(self):
        original=self.sy._request
        async def request(path,data=None):
            # Actual appliance server returns code=0,data=null for ESCAPE clauses.
            if path.endswith('/sql') and ' escape ' in data['stmt'].lower(): return None
            return await original(path,data)
        self.sy._request=request
        async def claim(_): raise AssertionError('write forbidden')
        result=await self.sy.dispatch('sy_search',{'query':'appliance'},claim)
        self.assertEqual(result['documents'][0]['id'],DOC)

for name in list(dir(Base)):
    if name.startswith('test_') and name not in ReadAnswers.__dict__: setattr(ReadAnswers,name,None)
del Base
