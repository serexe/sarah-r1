"""Offline tests of public answer-only formatting; no device, provider or audio."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from bridge.core import Store
from bridge.runtime import VoiceRuntime, plain_answer, speech_text
from bridge.server import make_app
from bridge.warm_voice import WarmVoice


class AnswerFormatting(unittest.TestCase):
    def test_markers_removed_but_values_kept_on_both_surfaces(self):
        samples = {
            '**Sunday, November 15**': 'Sunday, November 15',
            '## Choices\n- **A:** *yes* and ~~old~~\n1. `ID_49`': 'Choices\nA: yes and old\nID_49',
            '```text\n**literal** x*y #42\n```': '**literal** x*y #42',
            '[Specs](https://example.test/a_(b))': 'Specs (https://example.test/a_(b))',
            'A **bold *nested* phrase**.': 'A bold nested phrase.',
        }
        for raw, wanted in samples.items():
            with self.subTest(raw=raw):
                self.assertEqual(plain_answer(raw), wanted)
                self.assertEqual(speech_text(raw), wanted.replace('November 15', 'November fifteenth'))

    def test_meaningful_symbols_urls_and_ambiguous_markers(self):
        literal = '2 * 3 = 6; x*y; a_b_c; C#; #49ers; -5; +2; A*; 1.05; 2026-11-15; https://example.test/a_b?q=x*y.'
        self.assertEqual(plain_answer(literal), literal)
        self.assertEqual(plain_answer(r'Literal \* and `a*b` and #42.'), 'Literal * and a*b and #42.')
        self.assertEqual(plain_answer('**'), '**')
        self.assertEqual(plain_answer('~~unfinished'), '~~unfinished')
        self.assertEqual(speech_text('```text\n```'), '```text\n```')
        self.assertEqual(speech_text('**$100.50**'), 'one hundred dollars and fifty cents')
        self.assertEqual(speech_text('`$100.50`'), '$100.50')
        self.assertEqual(speech_text(literal), literal)


class SpokenBoundary(unittest.IsolatedAsyncioTestCase):
    async def test_actual_tts_input(self):
        raw = '**Sunday, November15**. ~~Formerly~~ [Docs](https://example.test/a_(b)).'
        seen = []
        async def synthesize(self, text, output):
            seen.append(text)
            Path(output).write_bytes(b'fixture wav')
        async def encode(*args, **kwargs):
            Path(args[-1]).write_bytes(b'fixture mp3')
        with tempfile.TemporaryDirectory() as tmp, patch.object(WarmVoice, 'synthesize', synthesize), \
                patch('bridge.runtime._tts_process', encode):
            output = Path(tmp) / 'answer.mp3'
            await VoiceRuntime().speak(raw, output)
            self.assertEqual(output.read_bytes(), b'fixture mp3')
        self.assertEqual(seen, ['Sunday, November fifteenth. Formerly Docs (https://example.test/a_(b)).'])


class AnswerHTTP(AioHTTPTestCase):
    async def get_application(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'state.db')
        self.store.provision('fixture', 'a' * 48)
        return make_app(self.store)

    async def tearDownAsync(self):
        await super().tearDownAsync()
        self.store.close()
        self.tmp.cleanup()

    async def test_poll_and_lookup_clean_only_answer_not_history_or_transcript(self):
        headers = {'Authorization': 'Bearer ' + 'a' * 48}
        conversation = self.store.conversation('fixture')
        turn = self.store.admit('fixture', conversation, 'req', 'fixture')
        raw = '**Sunday, November 15**. [Schedule](https://example.test/a_(b))'
        self.store.finish('fixture', turn, 'done', raw, 'Ask sports date')
        for path in ('/v1/turns/' + turn, '/v1/requests/req'):
            response = await self.client.get(path, headers=headers)
            self.assertEqual(response.status, 200)
            result = await response.json()
            self.assertEqual(result['detail'], 'Sunday, November 15. Schedule (https://example.test/a_(b))')
            self.assertEqual(result['transcript'], 'Ask sports date')
        self.assertEqual(self.store.get('fixture', turn)['detail'], raw)
        self.assertEqual((await self.client.get('/v1/turns/' + turn)).status, 403)
