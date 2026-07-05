import unittest

from timeline import TimelineParseError, parse_webvtt_timeline, timeline_summary

VALID_TIMELINE = """WEBVTT

NOTE station=Neural FM
NOTE default_voice=am_michael

bed-001
00:00:00.000 --> 00:00:12.000

NOTE type=music_bed
NOTE asset=deep_house_news_01
NOTE ducking=true

news-001
00:00:00.000 --> 00:00:05.400

<v Ava>
Good morning. You're listening to Neural FM.
NOTE type=speech
NOTE speaker=ava

mark-001
00:00:05.400 --> 00:00:05.400

NOTE type=mark
NOTE event=safe_interrupt
"""


class TimelineTests(unittest.TestCase):
    def test_parse_typed_webvtt_timeline(self):
        timeline = parse_webvtt_timeline(VALID_TIMELINE)

        self.assertEqual(timeline.metadata["station"], "Neural FM")
        self.assertEqual(len(timeline.cues), 3)
        self.assertEqual(len(timeline.speech_cues), 1)
        self.assertEqual(len(timeline.asset_cues), 1)
        self.assertEqual(len(timeline.marker_cues), 1)
        self.assertEqual(
            timeline.speech_cues[0].text,
            "Good morning. You're listening to Neural FM.",
        )
        self.assertEqual(timeline.asset_cues[0].metadata["asset"], "deep_house_news_01")

    def test_summary_includes_type_counts_and_assets(self):
        timeline = parse_webvtt_timeline(VALID_TIMELINE)

        self.assertEqual(
            timeline_summary(timeline),
            "1 mark, 1 music_bed, 1 speech, 1 asset refs",
        )

    def test_asset_cues_require_asset_reference(self):
        text = """WEBVTT

song-001
00:00:00.000 --> 00:01:00.000
NOTE type=music_track
"""

        with self.assertRaisesRegex(TimelineParseError, "asset"):
            parse_webvtt_timeline(text)

    def test_speech_cues_must_not_overlap(self):
        text = """WEBVTT

news-001
00:00:00.000 --> 00:00:05.000
First item.
NOTE type=speech

news-002
00:00:04.500 --> 00:00:06.000
Second item.
NOTE type=speech
"""

        with self.assertRaisesRegex(TimelineParseError, "Overlapping speech"):
            parse_webvtt_timeline(text)


if __name__ == "__main__":
    unittest.main()
