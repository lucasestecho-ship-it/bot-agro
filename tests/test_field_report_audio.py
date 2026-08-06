import ast
import re
import unittest
import unicodedata
from pathlib import Path


class FieldReportAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(cls.source)
        helper_names = {
            "clean_inline_markdown",
            "normalize_transcript_text",
            "is_noise_transcript",
            "valid_transcript_blocks",
            "transcript_report_markdown",
            "build_basic_report_markdown",
        }
        helper_nodes = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in helper_names
        ]
        namespace = {
            "re": re,
            "unicodedata": unicodedata,
            "NOISE_TRANSCRIPTS": {
                "bye",
                "bye.",
                "thank you",
                "thank you.",
                "thanks",
                "gracias",
                "sin transcripcion disponible",
                "sin transcripción disponible",
            },
        }
        exec(compile(ast.Module(body=helper_nodes, type_ignores=[]), "main.py", "exec"), namespace)
        cls.helpers = namespace

    def test_short_useful_audio_is_not_discarded(self):
        self.assertFalse(self.helpers["is_noise_transcript"]("prueba"))
        blocks = self.helpers["valid_transcript_blocks"]([
            {"fecha_hora": "2026-08-05T21:19:34Z", "transcript_text": "prueba"},
        ])
        self.assertEqual(["Fecha 2026-08-05T21:19:34Z:\nprueba"], blocks)

    def test_fallback_report_preserves_voice_notes(self):
        markdown = self.helpers["build_basic_report_markdown"](
            {"campo": "Prueba", "sector": "Lote 1", "started_at": "2026-08-05T21:18:53Z"},
            [{"fecha_hora": "2026-08-05T21:19:34Z", "transcript_text": "prueba"}],
            [],
            [],
        )
        self.assertIn("## Notas de voz registradas", markdown)
        self.assertIn("### Nota de voz 1", markdown)
        self.assertIn("prueba", markdown)

    def test_report_builders_are_not_duplicated(self):
        self.assertEqual(1, self.source.count("def build_basic_report_markdown("))
        self.assertEqual(1, self.source.count("def build_report_markdown("))


if __name__ == "__main__":
    unittest.main()
