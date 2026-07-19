"""Lectura deterministica de documentos compartidos con Capataz Campo."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from docx import Document

try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None


def extract_office_document(file_path, file_name=""):
    """Extract auditable text from DOCX/XLSX/CSV/TXT without model guesses."""
    suffix = Path(file_name or file_path).suffix.lower()
    if suffix == ".docx":
        document = Document(file_path)
        blocks = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
        for table_index, table in enumerate(document.tables, 1):
            blocks.append(f"--- Tabla {table_index} ---")
            for row in table.rows:
                values = [re.sub(r"\s+", " ", cell.text).strip() for cell in row.cells]
                if any(values):
                    blocks.append(" | ".join(values))
        return "\n".join(blocks)[:100000]
    if suffix in {".xlsx", ".xlsm"}:
        if load_workbook is None:
            raise RuntimeError("Falta openpyxl para leer la planilla")
        workbook = load_workbook(file_path, read_only=True, data_only=False)
        blocks = []
        cell_count = 0
        try:
            for sheet in workbook.worksheets[:12]:
                blocks.append(f"--- Hoja: {sheet.title} ---")
                for row in sheet.iter_rows():
                    values = [str(cell.value).strip() if cell.value is not None else "" for cell in row[:60]]
                    while values and not values[-1]:
                        values.pop()
                    if values and any(values):
                        blocks.append(" | ".join(values))
                        cell_count += len(values)
                    if cell_count >= 12000:
                        blocks.append("[Lectura truncada al limite de 12.000 celdas]")
                        return "\n".join(blocks)[:100000]
        finally:
            workbook.close()
        return "\n".join(blocks)[:100000]
    if suffix in {".csv", ".tsv"}:
        raw = Path(file_path).read_bytes()
        decoded = ""
        for encoding in ("utf-8-sig", "latin-1"):
            try:
                decoded = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        dialect = csv.excel_tab if suffix == ".tsv" else csv.excel
        rows = []
        for index, row in enumerate(csv.reader(decoded.splitlines(), dialect=dialect)):
            rows.append(" | ".join(str(value).strip() for value in row[:60]))
            if index >= 1000:
                rows.append("[Lectura truncada a 1.000 filas]")
                break
        return "\n".join(rows)[:100000]
    if suffix in {".txt", ".md"}:
        raw = Path(file_path).read_bytes()
        try:
            return raw.decode("utf-8-sig")[:100000]
        except UnicodeDecodeError:
            return raw.decode("latin-1")[:100000]
    raise ValueError("Formato de oficina no soportado")
