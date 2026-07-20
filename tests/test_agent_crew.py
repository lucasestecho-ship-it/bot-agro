import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_crew import AgentCrew
from capataz import CapatazStore, heuristic_analysis


class AgentCrewTests(unittest.TestCase):
    def test_default_routing_suspends_margen_and_contralor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            crew = AgentCrew(CapatazStore(data_dir=Path(temp_dir)))
            draft = heuristic_analysis("Presupuesto de bomba y costo para La Susana")
            route = crew.route(draft, draft["summary"])
            self.assertNotIn("margen", route)

    def test_exclusive_routing_single_specialist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            crew = AgentCrew(CapatazStore(data_dir=Path(temp_dir)))
            draft = heuristic_analysis("Analisis del caudal y presion de la bomba")
            route = crew.route(draft, "Analisis del caudal y presion de la bomba")
            self.assertIn("hidro", route)
            self.assertNotIn("margen", route)
            self.assertNotIn("contralor", route)

    def test_water_routes_technical_agents_only(self):
        # El agua rutea tecnicos; la economia solo entra si el pedido la nombra.
        with tempfile.TemporaryDirectory() as temp_dir:
            crew = AgentCrew(CapatazStore(data_dir=Path(temp_dir)))
            draft = heuristic_analysis(
                "Proyecto de agua: revisar aguadas y caudal de la bomba en La Susana"
            )
            route = crew.route(draft, draft["summary"])
            self.assertIn("aqua", route)
            self.assertIn("hidro", route)
            self.assertNotIn("margen", route)

    def test_specialists_create_audited_decision_and_approval_tasks(self):
        # Comportamiento historico: se prueba con los agentes reactivados.
        self._env = patch.dict("os.environ", {"CAPATAZ_SUSPENDED_AGENTS": ""})
        self._env.start()
        self.addCleanup(self._env.stop)
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
