import unittest

from lyrics_align import create_navidrome_ttml


class InstrumentalCueDurationTests(unittest.TestCase):
    def build_ttml(self) -> str:
        return create_navidrome_ttml(
            lines=["Hello", "World"],
            units_by_line=[["Hello"], ["World"]],
            mapped_by_line=[
                [{"start": 10.0, "end": 11.0}],
                [{"start": 20.0, "end": 21.0}],
            ],
            speaker_ids=[None, None],
            singer_config=None,
            language="en",
            duration=30.0,
            instrumental_cues=True,
            instrumental_threshold=6.0,
        )

    def test_intro_cue_spans_the_intro_instead_of_a_fixed_short_cap(self):
        ttml = self.build_ttml()
        self.assertIn(
            '<p begin="0.000s" end="9.950s"><span begin="0.000s" end="9.950s">♪</span></p>',
            ttml,
        )

    def test_inter_line_cue_fills_the_instrumental_gap(self):
        ttml = self.build_ttml()
        self.assertIn(
            '<p begin="11.300s" end="19.950s"><span begin="11.300s" end="19.950s">♪</span></p>',
            ttml,
        )

    def test_outro_cue_reaches_the_audio_duration(self):
        ttml = self.build_ttml()
        self.assertIn(
            '<p begin="21.300s" end="30.000s"><span begin="21.300s" end="30.000s">♪</span></p>',
            ttml,
        )


if __name__ == "__main__":
    unittest.main()
