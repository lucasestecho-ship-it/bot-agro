import tempfile
import unittest

from capataz import CapatazStore
from agriculture import (
    build_agriculture_overview,
    campaign_for_date,
    extract_agriculture,
    format_agriculture_overview,
    heuristic_agriculture,
    save_agriculture,
)


AUDIO = (
    "En La Susana sembramos 45 hectareas de maiz en el lote 3. "
    "Tambien aplicamos urea en el trigo del lote 5. "
    "Cosechamos la soja del lote 1 con 32 qq por ha."
)


class CampaignTests(unittest.TestCase):
    def test_july_starts_new_campaign(self):
        self.assertEqual(campaign_for_date("2026-07-19"), "2026/27")
        self.assertEqual(campaign_for_date("2026-03-10"), "2025/26")


class HeuristicTests(unittest.TestCase):
    def test_detects_crops_verbs_and_numbers(self):
        payload = heuristic_agriculture(AUDIO)
        events = payload["events"]
        tipos = {(e["cultivo"], e["tipo"]) for e in events}
        self.assertIn(("maiz", "siembra"), tipos)
        self.assertIn(("trigo", "aplicacion"), tipos)
        self.assertIn(("soja", "cosecha"), tipos)
        maiz = next(e for e in events if e["cultivo"] == "maiz")
        self.assertEqual(maiz["superficie_ha"], 45.0)
        self.assertEqual(maiz["lote"], "3")
        soja = next(e for e in events if e["cultivo"] == "soja")
        self.assertEqual(soja["rinde"], 32.0)

    def test_text_without_agriculture_returns_nothing(self):
        payload = heuristic_agriculture("Revisamos los bebederos y la bomba del molino.")
        self.assertEqual(payload["events"], [])
        self.assertEqual(payload["lots"], [])


class ExtractionTests(unittest.TestCase):
    def test_quote_guarantee_discards_unbacked_records(self):
        event = {"id": "event-9", "client_name": "La Susana", "created_at": "2026-07-19T10:00:00"}
        fake_json = (
            '{"lots": [{"cultivo": "maiz", "lote": "99", "superficie_ha": 500,'
            ' "source_quote": "500 hectareas inventadas"}],'
            ' "events": [{"cultivo": "maiz", "tipo": "siembra", "lote": "3",'
            ' "superficie_ha": 45, "source_quote": "sembramos 45 hectareas de maiz en el lote 3"}]}'
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

        extracted = extract_agriculture(
            event, AUDIO, openai_client=FakeClient(),
            completion_request=lambda prompt: {"model": "fake", "messages": []},
        )
        self.assertEqual(extracted["lots"], [])  # cita inventada: descartado
        self.assertEqual(len(extracted["events"]), 1)
        self.assertEqual(extracted["events"][0]["cultivo"], "maiz")

    def test_offline_extraction_builds_rows_with_ids(self):
        event = {"id": "event-10", "client_name": "La Susana",
                 "created_at": "2026-07-19T10:00:00", "field_name": "La Susana"}
        extracted = extract_agriculture(event, AUDIO)
        self.assertGreaterEqual(len(extracted["events"]), 3)
        for row in extracted["events"]:
            self.assertTrue(row["id"].startswith("cropev-"))
            self.assertEqual(row["campania"], "2026/27")


class OverviewTests(unittest.TestCase):
    def test_margin_requires_declared_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CapatazStore(data_dir=temp_dir)
            event = {"id": "event-11", "client_name": "La Susana", "created_at": "2026-07-19T10:00:00"}
            save_agriculture(store, extract_agriculture(event, AUDIO))
            overview = build_agriculture_overview(store, "susana")
            self.assertGreaterEqual(len(overview["lots"]), 1)
            for item in overview["lots"]:
                self.assertIsNone(item["margin"]["margin_per_ha"])
                self.assertTrue(item["margin"]["missing"])
            text = format_agriculture_overview(overview)
            self.assertIn("MAIZ", text)
            self.assertIn("faltan datos", text)
            self.assertIn("nada es estimado", text)

    def test_empty_overview_is_friendly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CapatazStore(data_dir=temp_dir)
            overview = build_agriculture_overview(store, "Fantasma")
            text = format_agriculture_overview(overview)
            self.assertIn("Todavia no hay lotes", text)


if __name__ == "__main__":
    unittest.main()
