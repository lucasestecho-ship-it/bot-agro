import tempfile
import unittest
from pathlib import Path

from capataz import CapatazStore, heuristic_analysis


class CapatazAnalysisTests(unittest.TestCase):
    def test_routes_water_and_economic_note(self):
        draft = heuristic_analysis(
            "Doña Elena: revisar costo de la bomba de agua y mandar presupuesto mañana"
        )
        self.assertEqual(draft["client_name"], "Doña Elena")
        self.assertIn("Agua", draft["agents"])
        self.assertIn("Margen", draft["agents"])
        self.assertTrue(draft["water_project"])
        self.assertTrue(draft["economic_review"])
        self.assertEqual(len(draft["tasks"]), 1)
        self.assertIsNotNone(draft["tasks"][0]["due_date"])

    def test_observation_does_not_invent_task(self):
        draft = heuristic_analysis("La Susana: el lote norte tiene buena cobertura")
        self.assertEqual(draft["client_name"], "La Susana")
        self.assertEqual(draft["tasks"], [])


class CapatazStoreTests(unittest.TestCase):
    def test_confirmed_task_appears_in_dashboard(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CapatazStore(data_dir=Path(temp_dir))
            draft = heuristic_analysis("Policarpo: llamar hoy para coordinar la recorrida")
            result = store.confirm_intake(draft, source_text="Policarpo: llamar hoy")
            self.assertEqual(len(result["tasks"]), 1)
            dashboard = store.dashboard()
            self.assertEqual(len(dashboard["tasks"]["today"]), 1)
            self.assertEqual(dashboard["tasks"]["today"][0]["client_name"], "Policarpo")

            task_id = dashboard["tasks"]["today"][0]["id"]
            store.update_task(task_id, {"status": "done"})
            refreshed = store.dashboard()
            self.assertEqual(refreshed["tasks"]["today"], [])

    def test_client_frequency_creates_next_followup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CapatazStore(data_dir=Path(temp_dir))
            dashboard = store.dashboard()
            client = next(row for row in dashboard["clients"] if row["name"] == "La Susana")
            self.assertTrue(any(row["id"] == client["id"] for row in dashboard["clients_without_next_action"]))
            store.update_client(client["id"], {"followup_days": 30})
            refreshed = store.dashboard()
            self.assertFalse(any(row["id"] == client["id"] for row in refreshed["clients_without_next_action"]))


if __name__ == "__main__":
    unittest.main()
