import importlib.util
from pathlib import Path
import pytest
SPEC=importlib.util.spec_from_file_location('idle',Path(__file__).parents[1]/'power/idle_power.py')
assert SPEC is not None and SPEC.loader is not None
idle=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(idle)

def test_boundary_and_reset():
    p=idle.Policy('boot')
    assert not p.held(0)
    assert p.event('input',1,'',1)
    assert p.held(3600.999) and not p.held(3601)
    p.event('input',3602,'',3602)
    assert p.held(7201.999) and not p.held(7202)

def test_background_and_stale_never_renew():
    p=idle.Policy('boot'); p.event('input',0,'',0)
    for kind in ('poll','health','ssh','foreground','thinking'):
        assert not p.event(kind,3599,'',3599)
    assert not p.held(3600)
    assert not p.event('input',0,'',3601)
    assert not p.event('input',3603,'',3602)

def test_busy_end_cancel_and_stale():
    p=idle.Policy('boot'); p.event('input',0,'',0)
    assert p.event('begin',3599,'op',3599)
    assert p.held(3600) and not p.held(3899)
    assert not p.event('end',3900,'op',3900)
    assert not p.held(3900)
    p.event('input',4000,'',4000); p.event('begin',4001,'other',4001)
    assert p.event('end',4002,'other',4002)
    assert p.held(7601.999) and not p.held(7602)
    p.event('input',8000,'',8000); p.event('begin',8001,'third',8001)
    p.event('cancel',8002,'third',8002)
    assert not p.busy

def test_no_duplicate_begin_extension():
    p=idle.Policy('boot'); p.event('input',0,'',0)
    p.event('begin',3599,'op',3599)
    assert not p.event('begin',3800,'op',3800)
    assert not p.held(3899)
    q=idle.Policy('boot');q.event('input',0,'',0);q.event('begin',1,'op',1)
    assert not q.event('begin',302,'op',302)
    assert q.busy_until==301

@pytest.mark.parametrize('op',['recording','request','playback'])
def test_finite_work_grace(op):
    p=idle.Policy('boot');p.event('input',0,'',0);p.event('begin',3599,op,3599)
    assert p.held(3600) and not p.held(3899)
    assert p.event('end',3601,op,3601)
    assert p.held(7200.99) and not p.held(7201)

@pytest.mark.parametrize('saved',[[],{'boot':'boot'},{'boot':'boot','deadline':float('inf'),'busy_until':1,'highwater':1,'busy':'','cursors':{}}])
def test_corrupt_state_fails_closed(saved):
    assert not idle.Policy('boot',saved).held(10)

def test_restart_reboot_and_frozen_app():
    p=idle.Policy('boot'); p.event('input',5,'',5); p.event('begin',6,'op',6)
    q=idle.Policy('boot',p.dump())
    assert q.held(3604.9) and not q.held(3605)
    assert not idle.Policy('newboot',p.dump()).held(10)
    assert not q.held(99999) # no app callbacks; helper clock expires independently

def test_snapshot_replay_malformed_and_restart():
    p=idle.Policy('boot')
    e={'boot':'boot','session':'a'*32,'events':[{'seq':1,'at':10,'kind':'input','op':''}]}
    assert p.consume(e,10)
    q=idle.Policy('boot',p.dump()); assert not q.consume(e,11)
    assert q.deadline==3610
    assert not q.consume({**e,'boot':'wrong'},12)
    assert not q.consume({**e,'events':[{'seq':2,'at':12,'kind':'input','op':'','cmd':'whoami'}]},12)
    assert not q.consume({**e,'events':[{'seq':2,'at':float('nan'),'kind':'input','op':''}]},12)

def test_old_saved_deadline_is_not_retroactively_shortened():
    p=idle.Policy('boot');p.event('input',10,'',10)
    saved=p.dump();saved['deadline']=7210  # previous 7200-second policy state
    q=idle.Policy('boot',saved)
    assert q.held(7000) and not q.held(7210)
    assert q.event('input',7000,'',7000)
    assert q.deadline==10600  # new genuine input gets 3600 seconds

def test_owned_child_only():
    class Child:
        def __init__(self): self.stopped=0
        def poll(self): return None
        def terminate(self): self.stopped+=1
        def wait(self,timeout=None): return 0
    children=[]
    def spawn(): children.append(Child()); return children[-1]
    h=idle.Holder(spawn)
    h.sync(True); h.sync(True); assert len(children)==1
    h.sync(False); h.sync(False); assert children[0].stopped==1
    h.sync(True); assert len(children)==2

def test_safe_read_rejects_symlink_and_wrong_mode(tmp_path):
    import os
    path=tmp_path/'events.json'; path.write_text('{}'); path.chmod(0o600)
    assert idle.read_private(str(path),os.getuid())=={}
    path.chmod(0o644)
    with pytest.raises(ValueError): idle.read_private(str(path),os.getuid())
    path.unlink(); path.symlink_to('/etc/passwd')
    with pytest.raises(OSError): idle.read_private(str(path),os.getuid())
