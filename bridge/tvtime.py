"""Fixed canonical Hermes TV ON quick command; never arbitrary shell/URL.

Canonical script owns env, endpoint, payload and SofaBaton/guard workflow.
Its zero exit means webhook accepted, NOT guard/device readiness proof.
"""
import asyncio
import os
from pathlib import Path
from .ha import tool

# Administrator-supplied fixed local script, never model-supplied commands.
COMMAND = ('/usr/bin/python3', '/opt/sarah/bin/tvtime')
TIMEOUT_SECONDS = 60
GUIDANCE = ('When the user requests "TV time", invoke tvtime_on: the existing TV ON workflow. '
    'Interpret natural variants and contextual requests without a magic prefix. '
    'The user request authorizes this action; do not ask duplicate confirmation. '
    'Do not substitute generic HA turn_on or recreate SofaBaton actions. '
    'Quoted examples, negation and discussion are not action requests. '
    'Started means only webhook accepted; never claim devices ready or guard verified. '
    'Never automatically retry this mutation, including unknown outcomes.')
TOOLS = [tool('tvtime_on', 'Start existing TV time ON workflow once. No arguments. '
              'Webhook acceptance only, not verified device readiness.', {})]


async def _cleanup(spawn):
    proc = await spawn
    if proc.returncode is None:
        try: proc.terminate()
        except ProcessLookupError: pass
        try: await asyncio.wait_for(proc.wait(), 1)
        except TimeoutError:
            try: proc.kill()
            except ProcessLookupError: pass
    await proc.wait()


class TVTimeDispatcher:
    def __init__(self, script=COMMAND[1]):
        if not Path(script).is_absolute():
            raise ValueError('tvtime_script_must_be_absolute')
        self.command = (COMMAND[0], str(script))

    @classmethod
    def from_env(cls):
        # Never discover or run private scripts without administrator opt-in.
        script = os.getenv('R1_TVTIME_SCRIPT', '')
        if os.getenv('R1_ENABLE_TVTIME') != '1' or not script:
            return None
        path = Path(script)
        return cls(script) if path.is_absolute() and path.is_file() and os.access(path, os.R_OK) else None

    async def dispatch(self, name, args, claim):
        if name != 'tvtime_on' or not isinstance(args, dict) or args:
            return {'dispatched':False, 'verified':False, 'reply':'TV time request denied. Nothing dispatched.'}
        if not await claim({'name':'tvtime_on', 'arguments':{}}):
            return {'dispatched':False, 'verified':False,
                    'reply':'TV time cancelled or already claimed. Nothing further dispatched.'}
        spawn = asyncio.create_task(asyncio.create_subprocess_exec(
            *self.command, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL))
        try:
            async with asyncio.timeout(TIMEOUT_SECONDS):
                proc = await asyncio.shield(spawn)
                await proc.wait()
                if proc.returncode != 0: raise RuntimeError('canonical_command_failed')
            return {'dispatched':True, 'verified':False,
                    'reply':'TV time started. Device readiness not verified.'}
        except Exception:
            return {'dispatched':True, 'verified':False,
                    'reply':'TV time could not be confirmed. Outcome unknown. No automatic retry.'}
        finally:
            # Retain spawn ownership through cancellation; terminate and reap locally.
            # Stopping local process cannot undo an already accepted webhook.
            cancelled = False
            cleanup = asyncio.create_task(_cleanup(spawn))
            while not cleanup.done():
                try: await asyncio.shield(cleanup)
                except asyncio.CancelledError: cancelled = True
                except Exception: break
            if cleanup.done() and not cleanup.cancelled():
                try: cleanup.result()
                except Exception: pass
            if cancelled: raise asyncio.CancelledError
