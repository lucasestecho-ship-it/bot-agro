import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from capataz import CapatazStore, argentina_now, heuristic_analysis
from gmail_drafts import EmailDraftManager


class FakeGmailService:
    configured = True

    def __init__(self):
        self.created = []
        self.sent = []

    def create_draft(self, to_email, subject, body_text, attachments=None):
        self.created.append((to_email, subject, body_text))
        return {"id": "gmail-draft-1", "message": {"id": "gmail-message-1"}}

    def send_draft(self, gmail_draft_id):
        self.sent.append(gmail_draft_id)
        return {"id": "gmail-sent-message-1", "threadId": "gmail-thread-1"}


class GmailDraftTests(unittest.TestCase):
    def test_email_request_creates_real_gmail_draft_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CapatazStore(data_dir=Path(temp_dir))
            source_text = (
                "Doña Elena: preparar un correo para elena@example.com con el resumen de la recorrida"
            )
            draft = heuristic_analysis(source_text)
            confirmed = store.confirm_intake(draft, source_text=source_text)
            gmail = FakeGmailService()
            manager = EmailDraftManager(store, gmail_service=gmail)
            result = manager.prepare(
                confirmed["event"],
                draft,
                {"runs": [], "decision": None},
                source_text=source_text,
            )
            self.assertEqual(result["status"], "gmail_created")
            self.assertEqual(result["to_email"], "elena@example.com")
            self.assertEqual(gmail.created[0][0], "elena@example.com")
            rows, _source, _warning = store.list_rows("email_drafts")
            self.assertEqual(rows[0]["gmail_draft_id"], "gmail-draft-1")

    def test_plain_observation_does_not_create_email(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CapatazStore(data_dir=Path(temp_dir))
            draft = heuristic_analysis("La Susana: el lote norte tiene buena cobertura")
            confirmed = store.confirm_intake(draft, source_text=draft["summary"])
            manager = EmailDraftManager(store, gmail_service=FakeGmailService())
            result = manager.prepare(
                confirmed["event"],
                draft,
                {"runs": [], "decision": None},
                source_text=draft["summary"],
            )
            self.assertIsNone(result)

    def test_only_an_explicit_named_draft_is_sent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CapatazStore(data_dir=Path(temp_dir))
            source_text = "Preparar correo para cliente@example.com con el informe"
            draft = heuristic_analysis(source_text)
            confirmed = store.confirm_intake(draft, source_text=source_text)
            gmail = FakeGmailService()
            manager = EmailDraftManager(store, gmail_service=gmail)
            prepared = manager.prepare(
                confirmed["event"], draft, {"runs": [], "decision": None}, source_text=source_text
            )

            sent = manager.send_confirmed(prepared["id"])

            self.assertEqual(gmail.sent, ["gmail-draft-1"])
            self.assertEqual(sent["status"], "sent")
            self.assertEqual(sent["to_email"], "cliente@example.com")
            repeated = manager.send_confirmed(prepared["id"])
            self.assertTrue(repeated["already_sent"])
            self.assertEqual(gmail.sent, ["gmail-draft-1"])

    def test_send_requires_exact_existing_draft_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = EmailDraftManager(
                CapatazStore(data_dir=Path(temp_dir)), gmail_service=FakeGmailService()
            )
            with self.assertRaisesRegex(ValueError, "ID del borrador"):
                manager.send_confirmed("")
            with self.assertRaisesRegex(ValueError, "No encontre"):
                manager.send_confirmed("email-inexistente")

    def test_due_client_gets_daily_followup_draft(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CapatazStore(data_dir=Path(temp_dir))
            client = next(row for row in store.dashboard()["clients"] if row["name"] == "La Susana")
            store.update_client(
                client["id"],
                {
                    "email": "susana@example.com",
                    "next_contact_at": (argentina_now() - timedelta(days=1)).isoformat(),
                    "notes": "Consultar si revisaron la propuesta de aguadas",
                },
            )
            gmail = FakeGmailService()
            manager = EmailDraftManager(store, gmail_service=gmail)
            result = manager.prepare_due_followups()
            self.assertEqual(result["prepared"], 1)
            self.assertEqual(result["gmail_created"], 1)
            self.assertEqual(gmail.created[0][0], "susana@example.com")


if __name__ == "__main__":
    unittest.main()
