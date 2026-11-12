"""Public speech-only pronunciation rules; offline synthetic examples."""
import unittest
from bridge.runtime import plain_answer, speech_text


class CommonPronunciation(unittest.TestCase):
    def test_dates_calendar_and_years(self):
        cases = {
            'Sunday, November 15.': 'Sunday, November fifteenth.',
            'Nov 15, 2026; Nov. 2nd, 2026.': 'November fifteenth, twenty twenty six; November second, twenty twenty six.',
            'February 29, 2024; Feb 29, 2023.': 'February twenty-ninth, twenty twenty four; Feb 29, 2023.',
            'March 1st; September 30': 'March first; September thirtieth',
            'November15, 2026': 'November fifteenth, twenty twenty six',
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(speech_text(source), expected)

    def test_bounded_names_units_and_punctuation(self):
        cases = {
            '49ers vs. 76ers.': 'forty niners versus seventy sixers.',
            'Dr. Lee and Mr. Jones watch Mrs. Smith and Ms. Adams.':
                'Doctor Lee and Mister Jones watch Misses Smith and Miz Adams.',
            'Wind 20 km/h or 1 km/h.': 'Wind twenty kilometers per hour or one kilometer per hour.',
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(speech_text(source), expected)
        clock = speech_text('At 9:50 a.m.; at 3:05 p.m.; done.')
        self.assertNotIn('.;', clock)
        self.assertIn(';', clock)

    def test_ambiguous_or_literal_material_untouched(self):
        cases = [
            'There are 15 items. Version 2.15; 11/15/2026; 2026-02-30.',
            'https://example.test/November15/49ers?at=9:50AM user49ers@example.test',
            'invoice-November15; build_49ers; #49ers; ID-49ers; 49ers-id; X76ers; 149ers.',
            'April 31; May 32; February 29, 2023; November 15, 0000.',
            '`November 15, 2026; 49ers; 20 km/h`',
        ]
        for source in cases:
            with self.subTest(source=source):
                self.assertEqual(speech_text(source), source.replace('`', ''))

    def test_display_not_speech(self):
        source = '**Sunday, November 15**: 49ers vs. 76ers at 20 km/h.'
        self.assertEqual(plain_answer(source), 'Sunday, November 15: 49ers vs. 76ers at 20 km/h.')
        self.assertEqual(speech_text(source), 'Sunday, November fifteenth: forty niners versus seventy sixers at twenty kilometers per hour.')
        self.assertEqual(speech_text(speech_text(source)), speech_text(source))


if __name__ == '__main__':
    unittest.main()
