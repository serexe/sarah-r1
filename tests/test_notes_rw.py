"""Offline natural tool dispatch for note append/edit/delete."""
from pathlib import Path
from test_siyuan import Notes as Base, DOC

class NoteRW(Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.sy.backup_dir=Path(self.tmp.name)/'rollback'; self.deleted=False; self.children=False
        original=self.sy._request
        async def request(path,data=None):
            if path.endswith('removeDocByID'):
                self.syrequests.append((path,data)); self.deleted=True; return None
            if path.endswith('/sql'):
                if 'instr(hpath,' in data['stmt']: return [self.doc] if self.children else []
                if self.deleted: return []
            return await original(path,data)
        self.sy._request=request
    async def test_natural_append_stable_id_once(self):
        self.transcript='Add the green tile choice to my Ideas note.'
        a=('sy_append',{'document_id':DOC,'markdown':'Green tile'})
        self.calls=[('sy_search',{'query':'ideas'}),a,a]
        row=await self.submit(); self.assertIn('Write verified',row['detail'])
        self.assertEqual(self.body,'Original body\n\nGreen tile')
        self.assertEqual(sum(p.endswith('updateBlock') for p,d in self.syrequests),1)
    async def test_natural_edit_exact_text_stable_id(self):
        self.transcript='Change Original to Revised in that note.'
        self.calls=[('sy_edit',{'document_id':DOC,'old_text':'Original','new_text':'Revised'})]
        self.assertIn('Write verified',(await self.submit())['detail']); self.assertEqual(self.body,'Revised body')
    async def test_delete_exact_backup_and_readback(self):
        self.transcript='Delete the Ideas document at /Voice/Ideas.'
        self.calls=[('sy_delete',{'document_id':DOC,'expected_path':'/Voice/Ideas'})]*2
        row=await self.submit(); self.assertIn('Delete verified',row['detail'])
        self.assertEqual(sum(p.endswith('removeDocByID') for p,d in self.syrequests),1)
        backups=list(self.sy.backup_dir.glob('*.json')); self.assertEqual(len(backups),1)
        self.assertIn('Original body',backups[0].read_text()); self.assertEqual(backups[0].stat().st_mode & 0o777,0o600)
    async def test_children_mismatch_and_ambiguous_edit_refused(self):
        for key,action in [('wrong',('sy_delete',{'document_id':DOC,'expected_path':'/Wrong'})),('children',('sy_delete',{'document_id':DOC,'expected_path':'/Voice/Ideas'})),('missing',('sy_edit',{'document_id':DOC,'old_text':'Absent','new_text':'New'}))]:
            self.children=key=='children'; self.calls=[action]; await self.submit(key)
        self.assertFalse(any(p.endswith(('removeDocByID','updateBlock')) for p,d in self.syrequests))
    async def test_cancel_delete_before_claim(self):
        original=self.sy.export
        async def export(doc):
            text=await original(doc)
            turn=self.store.db.execute('select id from turns order by rowid desc limit 1').fetchone()[0]
            self.store.cancel('one',turn); return text
        self.sy.export=export
        self.calls=[('sy_delete',{'document_id':DOC,'expected_path':'/Voice/Ideas'})]
        self.assertEqual((await self.submit())['state'],'cancelled'); self.assertFalse(self.deleted)

for name in list(dir(Base)):
    if name.startswith('test_') and name not in NoteRW.__dict__: setattr(NoteRW,name,None)
del Base
