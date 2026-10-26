"""Offline narration only: real discovery labels, no live services."""
import copy
import unittest
from unittest.mock import AsyncMock
from bridge.ha import HADispatcher


class PartialLightNarration(unittest.IsolatedAsyncioTestCase):
    async def run_action(self, bad: str | None='unavailable', room='Master Bedroom', change=False, fail=False):
        group='light.discovered_room'
        ids=['light.discovered_'+str(i) for i in range(4)]
        rows={e:{'entity_id':e,'state':'off','attributes':{'friendly_name':n}}
              for e,n in zip(ids,['North','South','East','MBR4'])}
        rows[group]={'entity_id':group,'state':'off','attributes':{'friendly_name':room,'entity_id':ids}}
        if bad is not None: rows[ids[-1]]['state']=bad
        posts=[]
        async def request(method,path,data=None):
            if path=='/api/services': return [{'domain':'light','services':{'turn_off':{}}}]
            if method=='POST': posts.append(data); return []
            entity=path.rsplit('/',1)[-1]
            if posts and fail and entity==group: raise RuntimeError('private failure')
            if posts and bad=='missing' and entity==ids[-1]: raise RuntimeError('missing')
            row=copy.deepcopy(rows[entity])
            if posts and change and entity==group: row['attributes']['entity_id']=ids[:-1]
            return row
        dispatcher=HADispatcher('http://127.0.0.1','offline-only')
        dispatcher._request=request
        dispatcher.convergence_seconds=.012
        dispatcher.convergence_interval=.002
        result=await dispatcher.dispatch('ha_call_service',{'domain':'light','service':'turn_off','entity_id':group},AsyncMock(return_value=True))
        self.assertEqual(len(posts),1)
        return result

    async def test_three_off_one_unavailable_actual_names(self):
        result=await self.run_action()
        self.assertFalse(result['verified'])
        self.assertEqual(result['reply'],"3 lights in Master Bedroom are off. MBR4 isn't responding.")

    async def test_pending_still_on(self):
        result=await self.run_action('on')
        self.assertFalse(result['verified'])
        self.assertIn('3 lights in Master Bedroom are off.',result['reply'])
        self.assertIn('MBR4 is still on.',result['reply'])

    async def test_unknown_and_missing_not_off(self):
        for bad in ('unknown','missing'):
            result=await self.run_action(bad)
            self.assertFalse(result['verified'])
            self.assertIn('3 lights in Master Bedroom are off.',result['reply'])
            self.assertIn("Couldn't read the state of MBR4.",result['reply'])
            self.assertNotIn('4 lights',result['reply'])

    async def test_all_off_concise_unchanged(self):
        result=await self.run_action(None)
        self.assertTrue(result['verified'])
        self.assertEqual(result['reply'],'Master Bedroom is off. State verified. Service accepted.')

    async def test_generic_other_room(self):
        result=await self.run_action(room='Observatory')
        self.assertEqual(result['reply'],"3 lights in Observatory are off. MBR4 isn't responding.")

    async def test_membership_change_explained(self):
        result=await self.run_action(None,change=True)
        self.assertFalse(result['verified'])
        self.assertIn('Group membership changed',result['reply'])
        self.assertIn("Couldn't read the state of MBR4.",result['reply'])

    async def test_readback_failure_explained(self):
        result=await self.run_action(fail=True)
        self.assertFalse(result['verified'])
        self.assertIn("Couldn't read the updated state of Master Bedroom.",result['reply'])
        self.assertNotIn('private failure',result['reply'])
