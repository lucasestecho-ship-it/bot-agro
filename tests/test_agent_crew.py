import tempfile
import unittest
from pathlib import Path

from agent_crew import AgentCrew
from capataz import CapatazStore, heuristic_analysis


class AgentCrewTests(unittest.TestCase):
    def test_water_routes_technical_and_economic_agents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            crew = AgentCrew(CapatazStore(data_dir=Path(temp_dir)))
            draft = heuristic_analysis("Doña Elena: revisar bomba y cañería de la aguada")
            route = crew.route(draft, draft["summary"])
            self.assertIn("aqua", route)
            self.assertIn("hidro", route)
            self.assertIn("margen", route)

    def test_simple_followup_does_not_create_extra_decision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CapatazStore(data_dir=Path(temp_dir))
            crew = AgentCrew(store)
            draft = heuristic_analysis("Policarpo: llamar mañana")
            confirmed = store.confirm_intake(draft, source_text=draft["summary"])
            crew.queue_event(confirmed["event"], draft, draft["summary"])
            result = crew.process_event(confirmed["event"], draft, draft["summary"])
            self.assertIsNone(result["decision"])
            self.assertEqual([run["agent"] for run in result["runs"]], ["Cartera"])

    def test_specialists_create_audited_decision_and_approval_tasks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CapatazStore(data_dir=Path(temp_dir))
            crew = AgentCrew(store)
            draft = heuristic_analysis(
                "Doña Elena: revisar costo de la bomba de agua y cotizar mañana"
            )
            confirmed = store.confirm_intake(draft, source_text=draft["summary"])
            crew.queue_event(confirmed["event"], draft, draft["summary"])
            result = crew.process_event(confirmed["event"], draft, draft["summary"])

            decision = result["decision"]
            self.assertEqual(decision["status"], "pending_review")
            self.assertIn("Contralor", decision["agents"])
            self.assertIn("Margen", decision["agents"])
            self.assertEqual(len(store.dashboard()["pending_decisions"]), 1)

            approved = crew.approve_decision(decision["id"])
            self.assertEqual(approved["decision"]["status"], "approved")
            self.assertGreaterEqual(len(approved["tasks"]), 1)
            runs, _source, _warning = store.list_rows("agent_runs")
            self.assertTrue(any(run.get("agent") == "Ejecutor" for run in runs))
            second_approval = crew.approve_decision(decision["id"])
            self.assertEqual(second_approval["tasks"], [])


if __name__ == "__main__":
    unittest.main()
