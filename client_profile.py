"""Ficha economico-productiva por cliente.

Extrae datos concretos (numeros con unidad y contexto) de lo que Lucas ya le
manda al bot y arma una ficha consultable por cliente. Regla de oro: SOLO se
guardan datos respaldados por una cita textual presente en la fuente; nada se
infiere ni se inventa.
"""

import hashlib
import json
import re
import unicodedata

from capataz import extract_json_object, iso_now, normalize_key


FACT_CATEGORIES = {"economico", "ganadero", "agricola", "comercial", "otro"}

# Unidades reconocidas por el extractor heuristico (sin OpenAI) y su categoria.
_UNIT_PATTERNS = [
    (r"cabezas?|cab\b", "cabezas", "ganadero"),
    (r"terneros?|terneras?", "terneros", "ganadero"),
    (r"vacas?", "vacas", "ganadero"),
    (r"novillos?|novillitos?", "novillos", "ganadero"),
    (r"vaquillonas?", "vaquillonas", "ganadero"),
    (r"toros?", "toros", "ganadero"),
    (r"ovejas?|corderos?", "ovinos", "ganadero"),
    (r"kg/ha|kilos? por hectarea", "kg/ha", "ganadero"),
    (r"kg|kilos?", "kg", "ganadero"),
    (r"quintales?|qq", "qq", "agricola"),
    (r"toneladas?|tn|tt\b", "tn", "agricola"),
    (r"hectareas?|has?\b|ha\b", "ha", "agricola"),
    (r"rollos?|fardos?", "rollos", "ganadero"),
    (r"litros?|lts?\b", "litros", "ganadero"),
    (r"mm\b|milimetros?", "mm", "otro"),
    (r"d[oó]lares|usd|u\$s", "usd", "economico"),
    (r"pesos?|\$|ars\b", "pesos", "economico"),
    (r"%|por ?ciento", "%", "otro"),
]

_NUMBER_RE = r"(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"


def _normalize_text(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def _parse_number(raw):
    text = str(raw or "").strip()
    if not text:
        return None
    # 2.800 o 2,800 como miles; 12,5 como decimal
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", text):
        text = re.sub(r"[.,]", "", text)
    else:
        text = text.replace(".", "").replace(",", ".") if text.count(",") == 1 and text.count(".") > 0 else text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def fact_id(event_id, variable, quote):
    identity = f"{event_id}:{variable}:{quote}"
    return "fact-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:40]


def _quote_present(quote, source_text):
    return bool(quote) and _normalize_text(quote) in _normalize_text(source_text)


def heuristic_facts(source_text):
    """Extraccion sin LLM: numeros con unidad reconocible y su frase de contexto."""
    facts = []
    text = str(source_text or "")
    for pattern, unit, category in _UNIT_PATTERNS:
        for match in re.finditer(
            rf"{_NUMBER_RE}\s*(?:{pattern})", text, flags=re.IGNORECASE
        ):
            start = max(0, match.start() - 45)
            end = min(len(text), match.end() + 45)
            quote = text[match.start():match.end()]
            context = text[start:end].strip()
            value = _parse_number(match.group(1))
            if value is None:
                continue
            facts.append({
                "category": category,
                "variable": unit,
                "value_number": value,
                "value_text": context[:240],
                "unit": unit,
                "source_quote": quote[:240],
            })
    return facts


def _extraction_prompt(source_text, client_name):
    return f"""
Sos el fichero de datos de Capataz Campo. Extrae SOLO datos concretos que esten
textualmente en la entrada: cantidades, precios, superficies, rindes, stock,
gastos, ingresos, compromisos con fecha. PROHIBIDO inferir, estimar o inventar.
Cada dato debe incluir la cita textual exacta de donde sale.

Cliente: {client_name or "sin identificar"}

Responde SOLO JSON puro:
{{
  "facts": [
    {{
      "category": "economico|ganadero|agricola|comercial|otro",
      "variable": "nombre corto del dato (ej. precio_ternero, carga, superficie_maiz)",
      "value_number": 123.4,
      "value_text": "valor con contexto en una frase",
      "unit": "kg|ha|pesos|usd|cabezas|%|qq|tn|litros|mm|otro",
      "source_quote": "cita textual exacta de la entrada"
    }}
  ]
}}
Si no hay datos concretos, devolve {{"facts": []}}.

Entrada:
{str(source_text or "")[:6000]}
""".strip()


def extract_client_facts(event, source_text, openai_client=None, completion_request=None):
    """Extrae datos del evento. Con OpenAI usa el prompt; sin OpenAI, heuristica.

    Todo dato cuya cita no aparezca en la fuente se descarta: garantia anti-invento.
    """
    text = str(source_text or "").strip()
    client_name = str((event or {}).get("client_name") or "").strip()
    if not text:
        return []
    raw_facts = []
    if openai_client is not None and completion_request is not None:
        try:
            response = openai_client.chat.completions.create(
                **completion_request(_extraction_prompt(text, client_name))
            )
            payload = extract_json_object(response.choices[0].message.content)
            raw_facts = list((payload or {}).get("facts") or [])
        except Exception:
            raw_facts = []
    if not raw_facts:
        raw_facts = heuristic_facts(text)

    now = iso_now()
    event_id = str((event or {}).get("id") or "")
    fact_date = str((event or {}).get("created_at") or now)[:10]
    cleaned = []
    seen = set()
    for fact in raw_facts:
        if not isinstance(fact, dict):
            continue
        quote = str(fact.get("source_quote") or "").strip()
        if not _quote_present(quote, text):
            continue  # sin respaldo textual no se guarda
        category = str(fact.get("category") or "otro").strip().lower()
        if category not in FACT_CATEGORIES:
            category = "otro"
        variable = normalize_key(str(fact.get("variable") or "dato"))[:60] or "dato"
        value_number = fact.get("value_number")
        if value_number is not None:
            try:
                value_number = float(value_number)
            except (TypeError, ValueError):
                value_number = None
        identity = fact_id(event_id, variable, quote)
        if identity in seen:
            continue
        seen.add(identity)
        cleaned.append({
            "id": identity,
            "client_id": (event or {}).get("client_id"),
            "client_name": client_name or None,
            "category": category,
            "variable": variable,
            "value_number": value_number,
            "value_text": str(fact.get("value_text") or quote)[:240],
            "unit": str(fact.get("unit") or "")[:30],
            "fact_date": fact_date,
            "event_id": event_id or None,
            "source_quote": quote[:240],
            "created_at": now,
            "updated_at": now,
        })
    return cleaned


def save_client_facts(store, facts):
    if not facts:
        return 0
    store.save_rows("client_facts", facts)
    return len(facts)


def build_client_profile(store, client_name, max_events=5):
    """Arma la ficha del cliente con datos guardados. No calcula nada nuevo."""
    key = normalize_key(client_name)
    if not key:
        raise ValueError("Falta el nombre del cliente")

    def _matches(row):
        return key in normalize_key(str(row.get("client_name") or ""))

    clients, _source, _warning = store.list_rows("clients", order="updated_at.desc")
    client = next((row for row in clients if key in normalize_key(str(row.get("name") or ""))), None)

    facts, _s, _w = store.list_rows("client_facts", order="updated_at.desc")
    client_facts = [row for row in facts if _matches(row)]
    by_category = {}
    latest_by_variable = {}
    for fact in sorted(client_facts, key=lambda row: str(row.get("fact_date") or ""), reverse=True):
        variable = fact.get("variable") or "dato"
        if variable not in latest_by_variable:
            latest_by_variable[variable] = fact
            by_category.setdefault(fact.get("category") or "otro", []).append(fact)

    tasks, _s, _w = store.list_rows("tasks", order="updated_at.desc")
    pending_tasks = [
        row for row in tasks
        if _matches(row) and str(row.get("status") or "").lower() in {"pending", "in_progress", ""}
    ]

    events, _s, _w = store.list_rows("client_events", order="created_at.desc")
    recent_events = [row for row in events if _matches(row)][:max_events]

    return {
        "client": client,
        "client_name": (client or {}).get("name") or client_name,
        "facts_by_category": by_category,
        "facts_total": len(client_facts),
        "pending_tasks": pending_tasks,
        "recent_events": recent_events,
    }


def format_client_profile(profile):
    """Ficha en texto para Telegram, sin inventos y con fuentes."""
    lines = [f"FICHA: {profile.get('client_name')}"]
    client = profile.get("client") or {}
    if client.get("last_contact_at"):
        lines.append(f"Ultimo contacto: {str(client['last_contact_at'])[:10]}")
    if client.get("next_contact_at"):
        lines.append(f"Proximo contacto: {str(client['next_contact_at'])[:10]}")

    titles = {
        "economico": "ECONOMICO",
        "ganadero": "PRODUCTIVO GANADERO",
        "agricola": "PRODUCTIVO AGRICOLA",
        "comercial": "COMERCIAL",
        "otro": "OTROS DATOS",
    }
    by_category = profile.get("facts_by_category") or {}
    for category in ("economico", "ganadero", "agricola", "comercial", "otro"):
        rows = by_category.get(category) or []
        if not rows:
            continue
        lines.append("")
        lines.append(titles[category] + ":")
        for fact in rows[:12]:
            value = fact.get("value_text") or fact.get("source_quote") or ""
            lines.append(f"- {str(fact.get('fact_date') or '')[:10]}: {value}")

    if not by_category:
        lines.append("")
        lines.append(
            "Todavia no hay datos registrados. La ficha se arma sola con los proximos "
            "audios, recorridas y documentos que mandes de este cliente."
        )

    pending = profile.get("pending_tasks") or []
    if pending:
        lines.append("")
        lines.append("PENDIENTES:")
        for task in pending[:8]:
            due = f" (vence {str(task.get('due_date'))[:10]})" if task.get("due_date") else ""
            lines.append(f"- {task.get('title')}{due}")

    recent = profile.get("recent_events") or []
    if recent:
        lines.append("")
        lines.append("ULTIMOS MOVIMIENTOS:")
        for event in recent:
            lines.append(
                f"- {str(event.get('created_at') or '')[:10]}: {str(event.get('summary') or '')[:120]}"
            )

    lines.append("")
    lines.append(f"Datos registrados en total: {profile.get('facts_total', 0)}.")
    return "\n".join(lines)
