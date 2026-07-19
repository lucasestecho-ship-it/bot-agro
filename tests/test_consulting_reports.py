import tempfile
import unittest
from pathlib import Path

from agent_crew import AgentCrew
from capataz import CapatazStore, heuristic_analysis
from consulting_reports import generate_consulting_report
from report_playbooks import detect_report_playbook
from document_intake import extract_office_document


class ReportPlaybookTests(unittest.TestCase):
    def test_detects_each_professional_deliverable(self):
        examples = {
            "proyecto_agua": "Haceme un informe de agua y dimensiona la red de bebederos",
            "propuesta_comercial": "Arma una propuesta tecnica y comercial para el cliente",
            "presupuesto_profesional": "Necesito un presupuesto profesional de mi trabajo",
            "comparativo_presupuestos": "Comparar presupuestos de tres proveedores",
            "evaluacion_compra": "Informe de riesgo de compra de este campo",
            "comparativo_campos": "Hacer comparacion de islas contra La Tigra",
            "dossier_venta": "Preparar un dossier de venta del campo",
            "informe_recorrida": "Cerrar con informe de recorrida",
            "informe_tecnico": "Hacer un informe tecnico agronomico",
        }
        for expected, text in examples.items():
            with self.subTest(text=text):
                self.assertEqual(detect_report_playbook(text).key, expected)
        self.assertEqual(
            detect_report_playbook("Comparame estas ofertas y decime cual proveedor conviene").key,
            "comparativo_presupuestos",
        )

    def test_deliverable_routes_the_complete_specialist_crew(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            crew = AgentCrew(CapatazStore(data_dir=Path(temp_dir)))
            draft = heuristic_analysis("Comparar presupuestos de bombas para La Susana")
            route = crew.route(draft, draft["summary"])
            self.assertEqual(route, ["tero", "margen", "comercial", "informes"])


class ConsultingReportGenerationTests(unittest.TestCase):
    def test_extracts_docx_and_xlsx_for_budget_comparisons(self):
        try:
            from openpyxl import Workbook
            from docx import Document
        except ImportError:
            self.skipTest("Dependencias de oficina no instaladas")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docx_path = root / "oferta.docx"
            document = Document()
            document.add_paragraph("Proveedor Uno - oferta vigente")
            table = document.add_table(rows=1, cols=2)
            table.cell(0, 0).text = "Bomba"
            table.cell(0, 1).text = "USD 1200"
            document.save(docx_path)
            self.assertIn("USD 1200", extract_office_document(docx_path, docx_path.name))

            xlsx_path = root / "comparativo.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Ofertas"
            sheet.append(["Proveedor", "Subtotal", "IVA"])
            sheet.append(["Uno", 1000, "=B2*0.21"])
            workbook.save(xlsx_path)
            extracted = extract_office_document(xlsx_path, xlsx_path.name)
            self.assertIn("--- Hoja: Ofertas ---", extracted)
            self.assertIn("=B2*0.21", extracted)

    def test_generates_real_pdf_and_docx_and_marks_missing_data(self):
        try:
            from pypdf import PdfReader
            from docx import Document
        except ImportError:
            self.skipTest("Dependencias de documentos no instaladas")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = (
                "Hacer una propuesta tecnica para Estancias Demo. "
                "Objetivo: diagnosticar el sistema de agua. Todavia no se definieron honorarios."
            )
            event = {
                "id": "event-demo",
                "client_name": "Estancias Demo",
                "source": "telegram",
            }
            draft = heuristic_analysis(source, field_name="Campo Demo", source="telegram")
            crew_result = {
                "runs": [
                    {
                        "agent": "Comercial",
                        "output": {
                            "summary": "El cliente necesita diagnostico de agua.",
                            "findings": ["El objetivo fue expresamente informado."],
                            "recommendations": ["Definir alcance y honorarios antes de enviar."],
                            "risks": ["Alcance todavia abierto."],
                            "missing_data": ["Honorarios y forma de pago."],
                        },
                    }
                ],
                "decision": {
                    "summary": "Preparar una propuesta preliminar sin completar precios.",
                    "recommendation": "Confirmar alcance, honorarios y movilidad.",
                    "risks": ["No enviar sin revision de Lucas."],
                    "missing_data": ["Honorarios y forma de pago."],
                },
            }
            report = generate_consulting_report(
                event=event,
                draft=draft,
                crew_result=crew_result,
                source_text=source,
                assets=[],
                output_dir=root,
                logo_path=str(Path(__file__).parents[1] / "static" / "logo.png"),
            )
            self.assertIsNotNone(report)
            self.assertEqual(report.playbook_key, "propuesta_comercial")
            self.assertEqual(report.status, "preliminar")
            self.assertTrue(Path(report.pdf_path).exists())
            self.assertTrue(Path(report.docx_path).exists())
            pdf_text = "\n".join(
                page.extract_text() or "" for page in PdfReader(report.pdf_path).pages
            )
            docx_text = "\n".join(
                paragraph.text for paragraph in Document(report.docx_path).paragraphs
            )
            self.assertIn("Datos y verificaciones pendientes", pdf_text)
            self.assertIn("Honorarios y forma de pago", pdf_text)
            self.assertIn("Honorarios y forma de pago", docx_text)
            self.assertNotIn("$1.650.000", pdf_text)

    def test_no_document_is_generated_for_a_simple_reminder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = "La Susana: llamar mañana"
            report = generate_consulting_report(
                event={"id": "event-simple", "client_name": "La Susana"},
                draft=heuristic_analysis(source),
                crew_result={"runs": [], "decision": None},
                source_text=source,
                assets=[],
                output_dir=temp_dir,
            )
            self.assertIsNone(report)


if __name__ == "__main__":
    unittest.main()
