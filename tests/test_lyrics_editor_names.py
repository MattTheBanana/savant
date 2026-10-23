import tempfile
import unittest
from pathlib import Path

from lyrics_editor import _build_command, _safe_name


class SafeOutputNameTests(unittest.TestCase):
    def test_preserves_single_quotes(self):
        self.assertEqual(_safe_name("Don't Stop (Live).txt", "lyrics"), "Don't Stop (Live).txt")

    def test_preserves_single_quotes_and_strips_windows_directories(self):
        self.assertEqual(_safe_name(r"C:\\Music\\Don't Stop.lrc", "lyrics"), "Don't Stop.lrc")

    def test_uses_fallback_for_empty_names(self):
        self.assertEqual(_safe_name("...", "lyrics"), "lyrics")


class NativeSourcePathTests(unittest.TestCase):
    def test_uses_native_source_paths_without_uploading_copies(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = root / "run"
            (run_dir / "inputs").mkdir(parents=True)
            audio = root / "Don't Stop.wav"
            lyrics = root / "Don't Stop.txt"
            audio.write_bytes(b"audio placeholder")
            lyrics.write_text("Don't stop", encoding="utf-8")
            run = {"directory": run_dir, "artifacts": {}}
            command = _build_command(run, {
                "mode": "align",
                "audioSourcePath": str(audio),
                "lyricsSourcePath": str(lyrics),
                "outputDirectory": str(root),
                "outputName": "Don't Stop",
                "wordLevel": False,
            }, {})
            self.assertIn(str(audio.resolve()), command)
            self.assertIn(str(lyrics.resolve()), command)
            self.assertEqual(run["artifacts"]["input-audio"]["path"], str(audio.resolve()))
            self.assertTrue(any(arg.endswith("Don't Stop.lrc") for arg in command))


if __name__ == "__main__":
    unittest.main()
