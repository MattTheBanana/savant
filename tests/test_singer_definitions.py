import tempfile
import unittest
from pathlib import Path

from lyrics_align import load_inline_singer_config, parse_inline_singer_definitions, read_lyrics_with_speaker_units


class InlineSingerDefinitionTests(unittest.TestCase):
    def test_ampersand_group_remains_supported(self):
        definitions = parse_inline_singer_definitions(
            "[Forrest Nolan, *love interest*, **Forrest Nolan & love interest**]"
        )
        self.assertIsNotNone(definitions)
        self.assertEqual(definitions[2]["name"], "Forrest Nolan & love interest")
        self.assertEqual(definitions[2]["members"], ["Forrest Nolan", "love interest"])
        self.assertTrue(definitions[2]["is_group"])

    def test_comma_separated_bold_group_is_valid(self):
        definitions = parse_inline_singer_definitions(
            "[Forrest Nolan, *love interest*, **Forrest Nolan, love interest**]"
        )
        self.assertIsNotNone(definitions)
        self.assertEqual(definitions[2]["name"], "Forrest Nolan, love interest")
        self.assertEqual(definitions[2]["members"], ["Forrest Nolan", "love interest"])
        self.assertTrue(definitions[2]["is_group"])

    def test_quoted_comma_proper_name_is_one_singer(self):
        definitions = parse_inline_singer_definitions(
            '["Tyler, the Creator", *love interest*, **"Tyler, the Creator" & love interest**]'
        )
        self.assertIsNotNone(definitions)
        self.assertEqual(definitions[0]["name"], "Tyler, the Creator")
        self.assertEqual(definitions[0]["style"], "normal")
        self.assertEqual(
            definitions[2]["members"], ["Tyler, the Creator", "love interest"]
        )

    def test_unclosed_quoted_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "closing"):
            parse_inline_singer_definitions('["Lead", *Guest*, **"Tyler, the Creator**]')

    def test_proper_name_in_bold_role_is_not_split_when_quoted(self):
        definitions = parse_inline_singer_definitions(
            '["Lead", *Guest*, **"Tyler, the Creator"**]'
        )
        self.assertEqual(definitions[2]["name"], "Tyler, the Creator")
        self.assertFalse(definitions[2]["is_group"])

    def test_default_role_must_be_first_and_unwrapped(self):
        with self.assertRaisesRegex(ValueError, "first bracketed singer definition"):
            parse_inline_singer_definitions("[*Guest*, Lead, **Both**]")

    def test_duplicate_style_roles_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "only one 'normal' role"):
            parse_inline_singer_definitions("[Lead, Guest, *Featured*, **Both**]")


    def test_quoted_comma_name_and_comma_group_work_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            lyrics = Path(tmp) / "sample.txt"
            lyrics.write_text(
                '["Tyler, the Creator", *love interest*, **"Tyler, the Creator", love interest**]\n'
                'Lead line\n'
                '*Featured line*\n'
                '**Group line**\n',
                encoding="utf-8",
            )
            config = load_inline_singer_config(lyrics)
            lines, line_speakers, unit_speakers = read_lyrics_with_speaker_units(lyrics, config)
            self.assertEqual(lines, ["Lead line", "Featured line", "Group line"])
            self.assertEqual(line_speakers[0], config["name_to_id"]["tyler, the creator"])
            self.assertEqual(line_speakers[1], config["name_to_id"]["love interest"])
            group_id = next(sid for sid, singer in config["singers"].items() if singer["type"] == "group")
            self.assertTrue(unit_speakers[2])
            self.assertEqual(set(unit_speakers[2]), {group_id})

    def test_inline_config_retains_group_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            lyrics = Path(tmp) / "sample.txt"
            lyrics.write_text(
                '["Tyler, the Creator", *love interest*, **"Tyler, the Creator", love interest**]\n'
                'Hello *there* **both voices**\n',
                encoding="utf-8",
            )
            config = load_inline_singer_config(lyrics)
            self.assertIsNotNone(config)
            group = next(row for row in config["singers"].values() if row["type"] == "group")
            self.assertEqual(group["members"], ["Tyler, the Creator", "love interest"])


if __name__ == "__main__":
    unittest.main()
