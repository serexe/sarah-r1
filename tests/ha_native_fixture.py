"""Reuse integrated fixture; no credentials/providers/audio touched."""
import asyncio
import signal
import sys
from pathlib import Path
from test_ha_slice import Slice

async def main():
    fixture=Slice();await fixture.asyncSetUp()
    stop=asyncio.Event();asyncio.get_running_loop().add_signal_handler(signal.SIGTERM,stop.set)
    Path(sys.argv[1],'ready').write_text(str(fixture.client.make_url('')).rstrip('/')+'\n')
    try:
        await stop.wait()
        fixture.assertEqual(fixture.requests,[('POST','/api/services/light/turn_on'),('GET','/api/states/light.example_bulb_c')]*2)
        fixture.assertEqual(len(fixture.wire),4)
        fixture.assertEqual(fixture.store.db.execute('SELECT count(*) FROM approvals').fetchone()[0],0)
        fixture.assertEqual(fixture.store.db.execute('SELECT count(*) FROM dispatches').fetchone()[0],2)
        fixture.assertEqual(len(fixture.spoken),2)
        print('PASS native wire: two HA POST + exact GET, zero approvals, two durable claims, four synthetic Codex requests, two authoritative TTS texts',flush=True)
    finally: await fixture.asyncTearDown()
asyncio.run(main())
