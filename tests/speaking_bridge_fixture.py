"""Isolated actual make_app; delayed synthetic TTS/audio, no providers/hardware."""
import asyncio
import sys
from pathlib import Path
from aiohttp import web
from bridge.core import Store
from bridge.server import make_app

class Adapter:
    ready = True
    calls = 0
    mode = 'resume'
    def transcribe(self, path):
        return 'fixture speech'
    async def reply(self, text, history):
        self.calls += 1
        return 'fixture reply'
    async def speak(self, text, path):
        await asyncio.sleep(.7)
        if self.mode != 'resume' and self.mode != 'cancel':
            path.write_bytes(b'synthetic audio; playback boundary overridden')

async def main():
    root = Path(sys.argv[1])
    store = Store(root / 'state.db')
    store.provision('native', 'x' * 48)
    adapter = Adapter()
    app = make_app(store, adapter)
    counts = {'uploads': 0, 'audio': 0}
    @web.middleware
    async def delays(request, handler):
        if request.method == 'POST' and request.path == '/v1/turns':
            counts['uploads'] += 1
        response = await handler(request)
        if request.path.endswith('/audio'):
            counts['audio'] += 1
            if adapter.mode in ('fetch_suspend', 'fetch_stop'):
                await asyncio.sleep(.8)
        return response
    app.middlewares.insert(0, delays)
    async def mode(request):
        adapter.mode = request.match_info['mode']
        return web.json_response({})
    async def stats(request):
        return web.json_response(dict(counts, calls=adapter.calls,
            turns=store.db.execute('SELECT count(*) FROM turns').fetchone()[0]))
    app.router.add_post('/fixture/mode/{mode}', mode)
    app.router.add_get('/fixture/stats', stats)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '127.0.0.1', 38479).start()
    (root / 'ready').touch()
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        store.close()
asyncio.run(main())
