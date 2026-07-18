import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from capataz import CapatazStore, heuristic_analysis
from push_notifications import PushNotifier


class PushNotificationTests(unittest.TestCase):
    def test_dispatches_due_tasks_to_saved_subscription(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CapatazStore(data_dir=Path(temp_dir))
            draft = heuristic_analysis("Policarpo: llamar hoy para coordinar recorrida")
            store.confirm_intake(draft, source_text=draft["summary"])
            env = {
                "VAPID_PUBLIC_KEY": "public-key",
                "VAPID_PRIVATE_KEY": "private-key",
                "VAPID_SUBJECT": "mailto:test@example.com",
            }
            with patch.dict(os.environ, env), patch("push_notifications.webpush") as send:
                notifier = PushNotifier(store)
                notifier.subscribe({
                    "endpoint": "https://push.example.com/subscription/1",
                    "keys": {"p256dh": "key", "auth": "auth"},
                })
                result = notifier.dispatch_due()
                self.assertEqual(result["sent"], 1)
                self.assertEqual(result["due"], 1)
                send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
