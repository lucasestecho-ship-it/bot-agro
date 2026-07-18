import hashlib
import json
import os

from capataz import PersistentStorageError, iso_now

try:
    from pywebpush import WebPushException, webpush
    from py_vapid import Vapid
except ImportError:  # El health check explica la dependencia faltante.
    WebPushException = Exception
    webpush = None
    Vapid = None


class PushNotifier:
    def __init__(self, store):
        self.store = store
        self.public_key = str(os.environ.get("VAPID_PUBLIC_KEY") or "").strip()
        self.private_key = str(os.environ.get("VAPID_PRIVATE_KEY") or "").strip()
        self.subject = str(
            os.environ.get("VAPID_SUBJECT") or "mailto:capataz-campo@example.com"
        ).strip()

    @property
    def configured(self):
        return bool(webpush and self.public_key and self.private_key and self.subject)

    def status(self):
        return {
            "configured": self.configured,
            "public_key": bool(self.public_key),
            "private_key": bool(self.private_key),
            "subject": bool(self.subject),
            "dependency": bool(webpush),
        }

    def subscribe(self, subscription):
        if not isinstance(subscription, dict):
            raise ValueError("subscription invalida")
        endpoint = str(subscription.get("endpoint") or "").strip()
        keys = subscription.get("keys") or {}
        if not endpoint.startswith("https://"):
            raise ValueError("endpoint push invalido")
        if not keys.get("p256dh") or not keys.get("auth"):
            raise ValueError("faltan claves de la suscripcion push")
        now = iso_now()
        row = {
            "id": "push-" + hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:40],
            "endpoint": endpoint,
            "subscription": subscription,
            "active": True,
            "last_success_at": None,
            "last_error": "",
            "created_at": now,
            "updated_at": now,
        }
        source, warning = self.store.save_rows("push_subscriptions", [row])
        if self.store.supabase_configured and source != "supabase":
            raise PersistentStorageError(warning or "No se pudo guardar la suscripcion push")
        return row

    def _vapid_private_key(self):
        private_key = self.private_key.replace("\\n", "\n")
        if "-----BEGIN" in private_key and Vapid is not None:
            return Vapid.from_pem(private_key.encode("utf-8"))
        return private_key

    def dispatch_due(self):
        if not self.configured:
            raise RuntimeError("Web Push no configurado")
        dashboard = self.store.dashboard()
        if self.store.supabase_configured and dashboard.get("warnings"):
            raise PersistentStorageError("No se pudieron leer las tareas para enviar recordatorios")
        due = [
            *(dashboard.get("tasks", {}).get("overdue") or []),
            *(dashboard.get("tasks", {}).get("today") or []),
        ]
        decisions = dashboard.get("pending_decisions") or []
        due_clients = [
            client for client in (dashboard.get("clients_without_next_action") or [])
            if client.get("followup_days") or client.get("next_contact_at")
        ]
        if not due and not decisions and not due_clients:
            return {"sent": 0, "failed": 0, "due": 0, "decisions": 0, "clients_due": 0}

        subscriptions, source, warning = self.store.list_rows(
            "push_subscriptions",
            order="created_at.desc",
        )
        if self.store.supabase_configured and source != "supabase":
            raise PersistentStorageError(warning or "No se pudieron leer las suscripciones push")

        body_parts = []
        if due:
            body_parts.append(f"{len(due)} tarea(s) para hoy o atrasadas")
        if decisions:
            body_parts.append(f"{len(decisions)} decisión(es) para revisar")
        if due_clients:
            body_parts.append(f"{len(due_clients)} cliente(s) para retomar")
        payload = json.dumps(
            {
                "title": "Capataz Campo",
                "body": " · ".join(body_parts),
                "url": "/campo",
                "tag": f"capataz-{dashboard.get('date')}",
            },
            ensure_ascii=False,
        )

        sent = 0
        failed = 0
        for subscription in subscriptions:
            if subscription.get("active") is False:
                continue
            try:
                webpush(
                    subscription_info=subscription.get("subscription") or {},
                    data=payload,
                    vapid_private_key=self._vapid_private_key(),
                    vapid_claims={"sub": self.subject},
                    ttl=3600,
                )
                sent += 1
                self.store.update_row(
                    "push_subscriptions",
                    subscription.get("id"),
                    {"last_success_at": iso_now(), "last_error": "", "updated_at": iso_now()},
                )
            except WebPushException as exc:
                failed += 1
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                self.store.update_row(
                    "push_subscriptions",
                    subscription.get("id"),
                    {
                        "active": status_code not in {404, 410},
                        "last_error": str(exc)[:2000],
                        "updated_at": iso_now(),
                    },
                )
        return {
            "sent": sent,
            "failed": failed,
            "due": len(due),
            "decisions": len(decisions),
            "clients_due": len(due_clients),
        }
