import tempfile
import unittest

from capataz import CapatazStore
from client_profile import (
    build_client_profile,
    extract_client_facts,
    format_client_profile,
    heuristic_facts,
    save_client_facts,
)


AUDIO = (
    "Recorrimos La Susana con Dani. Vendimos 50 terneros a 2.800 pesos el kilo. "
    "Quedan 320 vacas en el campo y sembramos 45 hectareas de maiz. "
    "Cayeron 38 mm el jueves."
)


class HeuristicExtractionTests(unittest.TestCase):
    def test_extracts_numbers_with_units_and_quotes(self):
        facts = heuristic_facts(AUDIO)
        quotes = {fact["source_quote"].lower() for fact in facts}
        self.assertIn("50 terneros", quotes)
        self.assertIn("320 vacas", quotes)
        self.assertIn("45 hectareas", quotes)
        self.assertIn("38 mm", quotes)
        for fact in facts:
            self.assertIn(fact["source_quote"].lower(), AUDIO.lower())

    def test_thousand_separator_is_parsed(self):
        facts = heuristic_facts("lo vendimos a 2.800 pesos")
        pesos = next(fact for fact in facts if fact["unit"] == "pesos")
        self.assertEqual(pesos["value_number"], 2800.0)


class ExtractionGuaranteeTests(unittest.TestCase):
    def test_fact_without_textual_backing_is_discarded(self):
        event = {"id": "event-1", "client_name": "La Susana", "created_at": "2026-07-19T10:00:00"}

        fake_json = (
            '{"facts": ['
            '{"category": "ganadero", "variable": "carga", '
            '"value_number": 999, "value_text": "999 cabezas", '
            '"unit": "cabezas", "source_quote": "999 cabezas inventadas"},'
            '{"category": "economico", "variable": "precio_ternero", '
            '"value_number": 2800, "value_text": "2.800 pesos el kilo", '
            '"unit": "pesos", "source_quote": "2.800 pesos el kilo"}'
            ']}'
        )

        class FakeClient:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kwargs):
                        class Message:
                            content = fake_json

                        class Choice:
                            message = Message()

                        class Response:
                            choices = [Choice()]

                        return Response()

        facts = extract_client_facts(
            event, AUDIO, openai_client=FakeClient(),
            completion_request=lambda prompt: {"model": "fake", "messages": []},
        )
        variables = [fact["variable"] for fact in facts]
        self.assertIn("precio ternero", variables)
        self.assertNotIn("carga", variables)  # la cita inventada no esta en la fuente

    def test_without_openai_uses_heuristics(self):
        event = {"id": "event-2", "client_name": "La Susana", "created_at": "2026-07-19T10:00:00"}
        facts = extract_client_facts(event, AUDIO)
        self.assertGreaterEqual(len(facts), 3)
        for fact in facts:
            self.assertTrue(fact["id"].startswith("fact-"))
            self.assertEqual(fact["client_name"], "La Susana")
            self.assertEqual(fact["fact_date"], "2026-07-19")


class ProfileTests(unittest.TestCase):
    def test_profile_roundtrip_with_local_store(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CapatazStore(data_dir=temp_dir)
            event = {"id": "event-3", "client_name": "La Susana", "created_at": "2026-07-19T10:00:00"}
            facts = extract_client_facts(event, AUDIO)
            saved = save_client_facts(store, facts)
            self.assertGreater(saved, 0)
            profile = build_client_profile(store, "susana")
            self.assertEqual(profile["facts_total"], saved)
            self.assertIn("ganadero", profile["facts_by_category"])
            text = format_client_profile(profile)
            self.assertIn("FICHA", text)
            self.assertIn("PRODUCTIVO GANADERO", text)
            self.assertIn("terneros", text.lower())

    def test_profile_for_unknown_client_is_empty_but_valid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CapatazStore(data_dir=temp_dir)
            profile = build_client_profile(store, "Cliente Fantasma")
            text = format_client_profile(profile)
            self.assertIn("Todavia no hay datos", text)


if __name__ == "__main__":
    unittest.main()
