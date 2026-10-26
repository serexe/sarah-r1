import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def test_real_helper_loop_expires_with_native_process_stopped(tmp_path):
    """Actual helper main loop + SIGSTOP'd client; fake clock and fake holder only."""
    module=Path(__file__).parents[1]/'power/idle_power.py'
    events=tmp_path/'events.json'; clock=tmp_path/'clock'; trace=tmp_path/'holds'
    clock.write_text('1')
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    reader,writer=os.pipe()
    client=os.fork()
    if client==0:
        os.close(reader)
        events.write_text(json.dumps({'boot':boot,'session':'a'*32,'events':[{'seq':1,'at':1,'kind':'input','op':''}]}))
        events.chmod(0o600)
        os.write(writer,b'R');os.close(writer)
        os.kill(os.getpid(),signal.SIGSTOP)
        os._exit(0)
    os.close(writer);assert os.read(reader,1)==b'R';os.close(reader)
    assert os.WIFSTOPPED(os.waitpid(client,os.WUNTRACED)[1])
    harness=r'''
import importlib.util,sys,os,types
from pathlib import Path
spec=importlib.util.spec_from_file_location('idle',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.EVENTS=sys.argv[2];m.STATE=sys.argv[3]
m.pwd.getpwnam=lambda name:types.SimpleNamespace(pw_uid=os.getuid())
m.time.clock_gettime=lambda which:float(Path(sys.argv[4]).read_text())
class Child:
 def __init__(self):
  with open(sys.argv[5],'a') as f:f.write('acquire\n')
 def poll(self):return None
 def terminate(self):
  with open(sys.argv[5],'a') as f:f.write('release\n')
 def wait(self,timeout=None):return 0
# Keep production Holder implementation; replace only fixed process factory.
original=m.Holder
m.Holder=lambda:original(Child)
m.main()
'''
    helper=subprocess.Popen([sys.executable,'-c',harness,str(module),str(events),str(tmp_path/'state'/'state.json'),str(clock),str(trace)])
    def until(predicate):
        end=time.monotonic()+4
        while time.monotonic()<end:
            if predicate():return
            assert helper.poll() is None
            time.sleep(.03)
        raise AssertionError('helper evidence timeout')
    try:
        until(lambda:trace.exists() and 'acquire' in trace.read_text())
        contender=subprocess.run([sys.executable,'-c',harness,str(module),str(events),str(tmp_path/'state'/'state.json'),str(clock),str(trace)],capture_output=True,timeout=3)
        assert contender.returncode != 0 and b'BlockingIOError' in contender.stderr
        newclock=tmp_path/'newclock';newclock.write_text('3600.999');newclock.replace(clock);time.sleep(.4)
        assert trace.read_text()=='acquire\n'
        newclock.write_text('3601');newclock.replace(clock)
        until(lambda:trace.read_text()=='acquire\nrelease\n')
        helper.terminate();helper.wait(timeout=3)
        # Same boot restart: unchanged stale journal cannot rearm expired lease.
        helper=subprocess.Popen([sys.executable,'-c',harness,str(module),str(events),str(tmp_path/'state'/'state.json'),str(clock),str(trace)])
        time.sleep(.5);assert helper.poll() is None
        assert trace.read_text()=='acquire\nrelease\n'
    finally:
        helper.terminate();helper.wait(timeout=3)
        os.kill(client,signal.SIGCONT);os.waitpid(client,0)
