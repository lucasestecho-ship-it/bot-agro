import unittest
from pathlib import Path


class StaticRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).parents[1] / "static" / "campo.js").read_text(encoding="utf-8")

    def _function(self, name, next_name):
        return self.source.split(f"function {name}", 1)[1].split(f"function {next_name}", 1)[0]

    def test_session_assignment_does_not_reference_a_client_email(self):
        body = self._function("addSessionAssignmentControls", "renderServerItems")
        self.assertNotIn("client.email", body)

    def test_uncovered_client_declares_email_before_using_it(self):
        body = self._function("createUncoveredClientItem", "showDueNotification")
        self.assertIn('const email = document.createElement("input")', body)
        self.assertLess(body.index("const email"), body.index("email.value.trim()"))

    def test_empty_report_link_is_rejected(self):
        body = self._function("safeExternalUrl", "urlBase64ToUint8Array")
        self.assertIn('!value.trim()', body)

    def test_render_keeps_telegram_activation_as_a_secret_setting(self):
        render_config = (Path(__file__).parents[1] / "render.yaml").read_text(encoding="utf-8")
        telegram_setting = render_config.split("- key: ENABLE_TELEGRAM_BOT", 1)[1].split(
            "- key: TELEGRAM_TOKEN", 1
        )[0]
        self.assertIn("sync: false", telegram_setting)
        self.assertNotIn('value: "false"', telegram_setting)

    def test_render_uses_terra_for_workers_and_sol_for_final_reports(self):
        render_config = (Path(__file__).parents[1] / "render.yaml").read_text(encoding="utf-8")
        self.assertIn("- key: CAPATAZ_AGENT_MODEL\n        value: gpt-5.6-terra", render_config)
        self.assertIn("- key: CAPATAZ_REPORT_MODEL\n        value: gpt-5.6-sol", render_config)
        self.assertIn("- key: CAPATAZ_REPORT_REASONING\n        value: high", render_config)

    def test_telegram_uses_a_render_waking_webhook(self):
        main_source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertIn('TELEGRAM_WEBHOOK_PATH = "/telegram/webhook"', main_source)
        self.assertIn("RENDER_EXTERNAL_HOSTNAME", main_source)
        self.assertIn("await telegram_app.bot.set_webhook(", main_source)
        self.assertIn('request.headers.get("X-Telegram-Bot-Api-Secret-Token"', main_source)
        self.assertIn("await telegram_app.update_queue.put(update)", main_source)

    def test_telegram_returns_geospatial_pdf_and_requires_explicit_email_id(self):
        main_source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertIn("await context.bot.send_document(", main_source)
        self.assertIn("Informe NDVI multianual por lote listo", main_source)
        self.assertIn('CommandHandler("enviar_correo", cmd_send_confirmed_email)', main_source)
        self.assertIn('name.endswith(".shp")', main_source)
        self.assertIn('name.endswith(".zip")', main_source)
        self.assertIn('@fastapi_app.get("/api/health/cdse")', main_source)
        self.assertIn("BLOQUEADO - faltan credenciales CDSE", main_source)


if __name__ == "__main__":
    unittest.main()
