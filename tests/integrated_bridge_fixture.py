"""Namespace-only real bridge fixture. Synthetic speech/provider, delayed lost202."""
import asyncio
import sys
from pathlib import Path
from aiohttp import web
from bridge.core import Store
from bridge.server import make_app

class Adapter:
    ready=True
    calls=0
    def transcribe(self,path):return 'fixture speech'
    async def reply(self,text,history):
        self.calls+=1
        await asyncio.sleep(.25)
        return 'fixture reply'
    async def speak(self,text,path):pass

async def main():
    root=Path(sys.argv[1]);store=Store(root/'state.db');store.provision('native','x'*48)
    adapter=Adapter();app=make_app(store,adapter)
    @web.middleware
    async def lose_response(request,handler):
        response=await handler(request)
        if request.method=='POST' and request.path=='/v1/turns' and response.status==202:
            await asyncio.sleep(.35)
            if request.transport:request.transport.close()
        return response
    app.middlewares.insert(0,lose_response)
    async def stats(request):
        cancelled=store.db.execute("SELECT count(*) FROM turns WHERE state='cancelled'").fetchone()[0]
        return web.json_response({'turns':store.db.execute('SELECT count(*) FROM turns').fetchone()[0], 'calls':adapter.calls,'cancelled':cancelled})
    app.router.add_get('/fixture/stats',stats)
    runner=web.AppRunner(app);await runner.setup();await web.TCPSite(runner,'127.0.0.1',38479).start()
    (root/'ready').touch()
    try:await asyncio.Event().wait()
    finally:await runner.cleanup();store.close()
asyncio.run(main())
