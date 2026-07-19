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

    def test_completed_contact_moves_client_followup_forward(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CapatazStore(data_dir=Path(temp_dir))
            client = next(row for row in store.dashboard()["clients"] if row["name"] == "Policarpo")
            store.update_client(client["id"], {"followup_days": 15})
            before = next(row for row in store.dashboard()["clients"] if row["id"] == client["id"])
            draft = heuristic_analysis("Policarpo: hablé hoy y confirmó que recibió el informe")
            store.confirm_intake(draft, source_text="Policarpo: hablé hoy y confirmó que recibió el informe")
            after = next(row for row in store.dashboard()["clients"] if row["id"] == client["id"])
            self.assertIsNotNone(after["last_contact_at"])
            self.assertGreater(after["next_contact_at"], before["next_contact_at"])


if __name__ == "__main__":
    unittest.main()


class PendingSummaryTests(unittest.TestCase):
    def test_summary_groups_tasks_and_decisions(self):
        from capataz import format_pending_summary

        dashboard = {
            "tasks": {
                "overdue": [{"title": "Mandar informe de recorrida", "client_name": "La Susana", "due_date": "2026-07-15"}],
                "today": [{"title": "Llamar por presupuesto", "client_name": "Policarpo", "due_date": "2026-07-19"}],
                "upcoming": [],
                "no_date": [],
            },
            "pending_decisions": [{"topic": "Compra de bomba", "client_name": "La Susana"}],
            "clients_without_next_action": [{"name": "Riendas Sueltas"}],
        }
        text = format_pending_summary(dashboard)
        self.assertIn("VENCIDAS", text)
        self.assertIn("Mandar informe de recorrida", text)
        self.assertIn("PARA HOY", text)
        self.assertIn("Compra de bomba", text)
        self.assertIn("Riendas Sueltas", text)

    def test_summary_empty_when_nothing_pending(self):
        from capataz import format_pending_summary

        self.assertEqual(format_pending_summary({"tasks": {}}), "")
