"""Modulo de agricultura: lotes, cultivos, labores y margenes.

Misma regla que la ficha de clientes: SOLO se guarda lo que tiene cita textual
en la fuente. Los margenes se calculan unicamente con datos declarados; si
falta un numero, el modulo dice que falta en vez de inventarlo.
"""

import hashlib
import re
import unicodedata

from capataz import extract_json_object, iso_now, normalize_key


CROP_KEYWORDS = [
    "maiz", "soja", "trigo", "girasol", "sorgo", "avena", "cebada", "centeno",
    "alfalfa", "pastura", "raigras", "moha", "arroz", "lino", "colza", "vicia",
]

EVENT_TYPES = {"siembra", "labor", "aplicacion", "monitoreo", "cosecha", "venta", "otro"}

_VERB_TO_TYPE = [
    (r"sembr\w+", "siembra"),
    (r"cosech\w+|trill\w+", "cosecha"),
    (r"pulveriz\w+|fumig\w+|aplic\w+|cur\w+", "aplicacion"),
    (r"fertiliz\w+|ure\w+", "aplicacion"),
    (r"vend\w+|entregu\w+", "venta"),
    (r"monitore\w+|recorr\w+|revis\w+", "monitoreo"),
]

_NUMBER_RE = r"(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"


def _normalize(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def _parse_number(raw):
    text = str(raw or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", text):
        text = re.sub(r"[.,]", "", text)
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def campaign_for_date(date_text):
    """Campania agricola argentina: julio a junio (ej. 2026/27)."""
    try:
        year = int(str(date_text or "")[:4])
        month = int(str(date_text or "")[5:7])
    except (TypeError, ValueError):
        return ""
    if month >= 7:
        return f"{year}/{(year + 1) % 100:02d}"
    return f"{year - 1}/{year % 100:02d}"


def _quote_present(quote, source_text):
    return bool(quote) and _normalize(quote) in _normalize(source_text)


def _row_id(prefix, *parts):
    identity = ":".join(str(part) for part in parts)
    return prefix + "-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:40]


def heuristic_agriculture(source_text):
    """Extraccion sin LLM: analiza oracion por oracion para no mezclar cultivos."""
    text = str(source_text or "")
    lots, events = [], []
    for sentence in re.split(r"(?<=[.;\n])\s+", text):
        sentence = sentence.strip()
        if not sentence:
            continue
        sentence_norm = _normalize(sentence)
        for crop in CROP_KEYWORDS:
            if not re.search(rf"\b{crop}\b", sentence_norm):
                continue
            event_type = next(
                (etype for pattern, etype in _VERB_TO_TYPE if re.search(pattern, sentence_norm)),
                None,
            )
            lot_match = re.search(r"lote\s+([\w-]+)", sentence_norm)
            area_match = re.search(rf"{_NUMBER_RE}\s*(?:hectareas?|has?\b|ha\b)", sentence_norm)
            yield_match = re.search(
                rf"{_NUMBER_RE}\s*(?:qq|quintales?|kg|tn|toneladas?)\s*(?:por\s+ha|/ha|por\s+hectarea)?",
                sentence_norm,
            )
            if not event_type and not area_match:
                continue
            record = {
                "cultivo": crop,
                "lote": lot_match.group(1) if lot_match else "",
                "superficie_ha": _parse_number(area_match.group(1)) if area_match else None,
                "tipo": event_type or "otro",
                "rinde": _parse_number(yield_match.group(1)) if yield_match else None,
                "source_quote": sentence[:240],
                "descripcion": sentence[:240],
            }
            events.append(record)
            if event_type == "siembra" or area_match:
                lots.append({
                    "cultivo": crop,
                    "lote": record["lote"],
                    "superficie_ha": record["superficie_ha"],
                    "source_quote": record["source_quote"],
                })
    return {"lots": lots, "events": events}


def _extraction_prompt(source_text, client_name):
    return f"""
Sos el registro agricola de Capataz Campo. Extrae SOLO lo que este textualmente
en la entrada sobre lotes y cultivos: siembras, labores, aplicaciones,
monitoreos, cosechas, ventas, superficies, rindes, precios y costos.
PROHIBIDO inferir o inventar. Cada registro lleva la cita textual exacta.

Cliente: {client_name or "sin identificar"}

Responde SOLO JSON puro:
{{
  "lots": [
    {{"cultivo": "maiz", "lote": "3", "superficie_ha": 45.0, "fecha_siembra": "2026-07-10", "source_quote": "cita textual"}}
  ],
  "events": [
    {{"cultivo": "maiz", "lote": "3", "tipo": "siembra|labor|aplicacion|monitoreo|cosecha|venta|otro",
      "fecha": "2026-07-10", "descripcion": "que se hizo", "costo_monto": 120.5, "costo_moneda": "usd|pesos",
      "rinde": 85.0, "rinde_unidad": "qq/ha", "precio_monto": 180.0, "precio_moneda": "usd|pesos",
      "superficie_ha": 45.0, "source_quote": "cita textual"}}
  ]
}}
Si no hay nada agricola, devolve {{"lots": [], "events": []}}.

Entrada:
{str(source_text or "")[:6000]}
""".strip()


def extract_agriculture(event, source_text, openai_client=None, completion_request=None):
    text = str(source_text or "").strip()
    client_name = str((event or {}).get("client_name") or "").strip()
    if not text:
        return {"lots": [], "events": []}
    payload = None
    if openai_client is not None and completion_request is not None:
        try:
            response = openai_client.chat.completions.create(
                **completion_request(_extraction_prompt(text, client_name))
            )
            payload = extract_json_object(response.choices[0].message.content)
        except Exception:
            payload = None
    if not payload or (not payload.get("lots") and not payload.get("events")):
        payload = heuristic_agriculture(text)

    now = iso_now()
    event_id = str((event or {}).get("id") or "")
    default_date = str((event or {}).get("created_at") or now)[:10]
    clean_lots, clean_events = [], []
    seen = set()

    for lot in payload.get("lots") or []:
        if not isinstance(lot, dict):
            continue
        quote = str(lot.get("source_quote") or "").strip()
        if not _quote_present(quote, text):
            continue
        cultivo = normalize_key(str(lot.get("cultivo") or ""))[:40]
        if not cultivo:
            continue
        lote = str(lot.get("lote") or "").strip()[:40]
        fecha = str(lot.get("fecha_siembra") or default_date)[:10]
        campania = campaign_for_date(fecha)
        row_id = _row_id("lot", client_name, cultivo, lote, campania)
        if row_id in seen:
            continue
        seen.add(row_id)
        superficie = lot.get("superficie_ha")
        try:
            superficie = float(superficie) if superficie is not None else None
        except (TypeError, ValueError):
            superficie = None
        clean_lots.append({
            "id": row_id,
            "client_id": (event or {}).get("client_id"),
            "client_name": client_name or None,
            "campo": str((event or {}).get("field_name") or "")[:80] or None,
            "lote": lote,
            "cultivo": cultivo,
            "campania": campania,
            "superficie_ha": superficie,
            "fecha_siembra": fecha,
            "estado": "activo",
            "event_id": event_id or None,
            "source_quote": quote[:240],
            "created_at": now,
            "updated_at": now,
        })

    for record in payload.get("events") or []:
        if not isinstance(record, dict):
            continue
        quote = str(record.get("source_quote") or "").strip()
        if not _quote_present(quote, text):
            continue
        cultivo = normalize_key(str(record.get("cultivo") or ""))[:40]
        tipo = str(record.get("tipo") or "otro").strip().lower()
        if tipo not in EVENT_TYPES:
            tipo = "otro"
        fecha = str(record.get("fecha") or default_date)[:10]
        lote = str(record.get("lote") or "").strip()[:40]
        row_id = _row_id("cropev", event_id, cultivo, lote, tipo, quote)
        if row_id in seen:
            continue
        seen.add(row_id)

        def _num(key):
            value = record.get(key)
            try:
                return float(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        clean_events.append({
            "id": row_id,
            "client_id": (event or {}).get("client_id"),
            "client_name": client_name or None,
            "lote": lote,
            "cultivo": cultivo,
            "campania": campaign_for_date(fecha),
            "tipo": tipo,
            "fecha": fecha,
            "descripcion": str(record.get("descripcion") or quote)[:240],
            "costo_monto": _num("costo_monto"),
            "costo_moneda": str(record.get("costo_moneda") or "")[:10],
            "rinde": _num("rinde"),
            "rinde_unidad": str(record.get("rinde_unidad") or "")[:15],
            "precio_monto": _num("precio_monto"),
            "precio_moneda": str(record.get("precio_moneda") or "")[:10],
            "superficie_ha": _num("superficie_ha"),
            "event_id": event_id or None,
            "source_quote": quote[:240],
            "created_at": now,
            "updated_at": now,
        })
    return {"lots": clean_lots, "events": clean_events}


def save_agriculture(store, extracted):
    saved = 0
    if extracted.get("lots"):
        store.save_rows("crop_lots", extracted["lots"])
        saved += len(extracted["lots"])
    if extracted.get("events"):
        store.save_rows("crop_events", extracted["events"])
        saved += len(extracted["events"])
    return saved


def _lot_margin(lot, lot_events):
    """Margen bruto por ha SOLO con datos declarados; si falta algo, lo dice."""
    superficie = lot.get("superficie_ha")
    harvest = next(
        (e for e in lot_events if e["tipo"] == "cosecha" and e.get("rinde") is not None), None
    )
    price = next(
        (e for e in lot_events if e.get("precio_monto") is not None), None
    )
    costs = [e for e in lot_events if e.get("costo_monto") is not None]
    missing = []
    if not harvest:
        missing.append("rinde de cosecha")
    if not price:
        missing.append("precio de venta")
    if not costs:
        missing.append("costos declarados")
    if missing:
        return {"margin_per_ha": None, "missing": missing}
    total_costs = sum(e["costo_monto"] for e in costs)
    cost_per_ha = total_costs / superficie if superficie else None
    if cost_per_ha is None:
        return {"margin_per_ha": None, "missing": ["superficie del lote"]}
    income_per_ha = harvest["rinde"] * price["precio_monto"]
    return {
        "margin_per_ha": round(income_per_ha - cost_per_ha, 1),
        "income_per_ha": round(income_per_ha, 1),
        "cost_per_ha": round(cost_per_ha, 1),
        "currency": price.get("precio_moneda") or "",
        "missing": [],
    }


def build_agriculture_overview(store, client_name=""):
    key = normalize_key(client_name)
    lots, _s, _w = store.list_rows("crop_lots", order="updated_at.desc")
    events, _s, _w = store.list_rows("crop_events", order="fecha.desc")
    if key:
        lots = [row for row in lots if key in normalize_key(str(row.get("client_name") or ""))]
        events = [row for row in events if key in normalize_key(str(row.get("client_name") or ""))]
    overview = []
    for lot in lots:
        lot_events = [
            e for e in events
            if normalize_key(str(e.get("cultivo"))) == normalize_key(str(lot.get("cultivo")))
            and str(e.get("lote") or "") == str(lot.get("lote") or "")
            and str(e.get("campania") or "") == str(lot.get("campania") or "")
        ]
        overview.append({
            "lot": lot,
            "events": sorted(lot_events, key=lambda e: str(e.get("fecha") or "")),
            "margin": _lot_margin(lot, lot_events),
        })
    return {"client_name": client_name, "lots": overview, "events_total": len(events)}


def format_agriculture_overview(overview):
    lines = []
    title = f"AGRICULTURA: {overview['client_name']}" if overview.get("client_name") else "AGRICULTURA (todos los clientes)"
    lines.append(title)
    lots = overview.get("lots") or []
    if not lots:
        lines.append("")
        lines.append(
            "Todavia no hay lotes registrados. Se cargan solos cuando mencionas "
            "siembras, labores o cosechas en los audios y documentos."
        )
        return "\n".join(lines)
    for item in lots:
        lot = item["lot"]
        lines.append("")
        etiqueta = f"Lote {lot['lote']} - " if lot.get("lote") else ""
        superficie = f", {lot['superficie_ha']:.0f} ha" if lot.get("superficie_ha") else ""
        cliente = f" ({lot['client_name']})" if not overview.get("client_name") and lot.get("client_name") else ""
        lines.append(f"{etiqueta}{str(lot['cultivo']).upper()} {lot.get('campania') or ''}{superficie}{cliente}")
        for event in item["events"][-4:]:
            extra = []
            if event.get("rinde") is not None:
                extra.append(f"rinde {event['rinde']:g} {event.get('rinde_unidad') or ''}".strip())
            if event.get("costo_monto") is not None:
                extra.append(f"costo {event['costo_monto']:g} {event.get('costo_moneda') or ''}".strip())
            suffix = f" [{', '.join(extra)}]" if extra else ""
            lines.append(f"  - {event['fecha']}: {event['tipo']} - {event['descripcion'][:90]}{suffix}")
        margin = item["margin"]
        if margin.get("margin_per_ha") is not None:
            lines.append(
                f"  Margen bruto declarado: {margin['margin_per_ha']:g} {margin.get('currency') or ''}/ha "
                f"(ingreso {margin['income_per_ha']:g}, costos {margin['cost_per_ha']:g})"
            )
        else:
            lines.append("  Margen: faltan datos (" + ", ".join(margin["missing"]) + ")")
    lines.append("")
    lines.append("Solo se muestran datos declarados por vos o Dani; nada es estimado.")
    return "\n".join(lines)
