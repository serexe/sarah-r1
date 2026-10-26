"""Speech-only Markdown cleanup; literal values and displayed answers survive."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bridge import runtime


class SpeechFormat(unittest.IsolatedAsyncioTestCase):
    def test_markdown(self):
        cases = [
            ('## Choices\n- **Cooking:** `VI230620`\n* *Hood:* EAR146S4\n1. [Quote](https://example.test/quote)',
             'Choices\nCooking: VI230620\nHood: EAR146S4\nQuote'),
            ('### Title ###\n+ __Bosch__ and _Café_\n```text\nSHP78CM6N\n```',
             'Title\nBosch and Café\nSHP78CM6N'),
            ('[Specs](https://example.test/a_(b)) and **$23,501.77**.', 'Specs and twenty three thousand five hundred one dollars and seventy seven cents.'),
            ('***Important*** and **bold**; *quiet*.', 'Important and bold; quiet.'),
            ('```CTC912P2NS1```', 'CTC912P2NS1'),
            ('```python\n# literal heading\nvalue = "**literal**"\n```', '# literal heading\nvalue = "**literal**"'),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(runtime.speech_text(source), expected)

    def test_literals_and_normal_prose_unchanged(self):
        cases = [
            '2 * 3 = 6; 2*3*4 = 24. C++ C# A*; #42; 80%; -5; +2.',
            'gpt-6.1-sol; af_heart; CTC912P2NS1; 46½-inch; 1,200-CFM.',
            '1.05 speed. 0.2.5 native. 2026-10-24. file_name and a_b_c.',
            'Normal prose stays exactly here.\nSecond line, too.',
        ]
        for text in cases:
            self.assertEqual(runtime.speech_text(text), text)
        self.assertEqual(runtime.speech_text(r'Literal \* and `a*b*c` and `#42`.'), 'Literal * and a*b*c and #42.')

    async def test_server_display_and_history_keep_original_provider_answer(self):
        from test_siyuan import Notes, DOC
        case = Notes('test_natural_notebooks_search_read_then_ha')
        await case.asyncSetUp()
        seen = []
        async def process(*args, input=None, **kwargs):
            if input is not None:
                seen.append(input.decode())
            Path(args[-1]).write_bytes(b'test encoded audio')
        async def speak(text, path):
            await runtime.VoiceRuntime.speak(case.adapter, text, path)
        try:
            case.prose = '## Oven\n- **GE Café:** `CTC912P2NS1`, **$100.50**.'
            case.calls = [('sy_read', {'document_id': DOC})]
            case.adapter.speak = speak
            with patch.object(runtime, '_tts_process', process):
                row = await case.submit()
                self.assertEqual(row['detail'], case.prose)
                self.assertEqual(seen, ['Oven\nGE Café: CTC912P2NS1, one hundred dollars and fifty cents.'])
                case.calls = []
                await case.submit('followup')
                self.assertIn({'role': 'assistant', 'content': case.prose}, case.wire[-1]['input'])
            self.assertEqual(case.body, 'Original body')
        finally:
            await case.asyncTearDown()

    async def test_only_synthesis_input_changes(self):
        original = '## Appliances\n- **Bosch:** `SHP78CM6N`, **$23,501.77**.'
        seen = []
        async def process(*args, input=None, **kwargs):
            if input is not None:
                seen.append(input.decode())
            Path(args[-1]).write_bytes(b'test encoded audio')
        with tempfile.TemporaryDirectory() as tmp, patch.object(runtime, '_tts_process', process):
            await runtime.VoiceRuntime.__new__(runtime.VoiceRuntime).speak(original, Path(tmp)/'out.mp3')
        self.assertEqual(seen, ['Appliances\nBosch: SHP78CM6N, twenty three thousand five hundred one dollars and seventy seven cents.'])
        self.assertEqual(original, '## Appliances\n- **Bosch:** `SHP78CM6N`, **$23,501.77**.')

    async def test_currency_production_stdin(self):
        cases = {
            '$100': 'one hundred dollars', '$1': 'one dollar',
            '$100.50': 'one hundred dollars and fifty cents',
            '$0.50': 'fifty cents', '$0.01': 'one cent',
            '$1.01': 'one dollar and one cent', '$0': 'zero dollars',
            '$1.00': 'one dollar', '$1,234,567.89': 'one million two hundred thirty four thousand five hundred sixty seven dollars and eighty nine cents',
            '-$100.50': 'minus one hundred dollars and fifty cents',
            '$-1': 'minus one dollar', '-$0.50': 'minus fifty cents',
            '$100, then $1.': 'one hundred dollars, then one dollar.',
            '$1,000,000,000,000; $1.2; -$-1': '$1,000,000,000,000; $1.2; -$-1',
            '**$100** and `$100` and \\$100': 'one hundred dollars and $100 and $100',
            '```text\n$100\n```': '$100',
            '2 * 3 = 6; ID$100; $100ABC; $100$; $12,34; $1.234; $100-id; -5':
            '2 * 3 = 6; ID$100; $100ABC; $100$; $12,34; $1.234; $100-id; -5',
        }
        for original, expected in cases.items():
            with self.subTest(original=original):
                seen = []
                async def process(*args, input=None, **kwargs):
                    if input is not None:
                        seen.append(input.decode())
                    Path(args[-1]).write_bytes(b'test encoded audio')
                with tempfile.TemporaryDirectory() as tmp, patch.object(runtime, '_tts_process', process):
                    await runtime.VoiceRuntime.__new__(runtime.VoiceRuntime).speak(original, Path(tmp)/'out.mp3')
                self.assertEqual(seen, [expected])
