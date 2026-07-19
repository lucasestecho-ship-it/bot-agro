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


if __name__ == "__main__":
    unittest.main()
