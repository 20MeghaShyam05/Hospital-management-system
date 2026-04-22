# =============================================================================
# features/gsuite/pdf_generator.py
# Generate clean, branded PDF documents for patient prescriptions and triage
# =============================================================================
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fpdf import FPDF

logger = logging.getLogger(__name__)


class _MediFlowPDF(FPDF):
    """Base PDF with MediFlow header and footer."""

    TEAL = (31, 122, 120)
    DARK = (20, 49, 58)
    MUTED = (110, 128, 133)
    LINE = (210, 218, 220)
    BG_LIGHT = (245, 250, 249)

    def header(self):
        # Brand bar
        self.set_fill_color(*self.TEAL)
        self.rect(0, 0, 210, 12, "F")
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(255, 255, 255)
        self.set_y(2.5)
        self.cell(0, 7, "MediFlow HMS", align="C")

        # Reset position below bar
        self.set_y(16)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*self.MUTED)
        self.cell(0, 10, f"Generated on {datetime.now().strftime('%d %b %Y, %I:%M %p')}  |  Page {self.page_no()}", align="C")

    def _section_title(self, title: str) -> None:
        """Print a section heading with a teal underline."""
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*self.TEAL)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        # Thin underline
        y = self.get_y()
        self.set_draw_color(*self.TEAL)
        self.set_line_width(0.4)
        self.line(10, y, 200, y)
        self.ln(3)

    def _label_value(self, label: str, value: Any, *, bold_value: bool = False) -> None:
        """Print a label: value row."""
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*self.MUTED)
        self.cell(45, 6, f"{label}:", new_x="END")
        style = "B" if bold_value else ""
        self.set_font("Helvetica", style, 9)
        self.set_text_color(*self.DARK)
        self.multi_cell(0, 6, str(value or "-"))
        self.ln(1)

    def _label_block(self, label: str, text: str) -> None:
        """Print a label followed by a multi-line text block in a light box."""
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*self.TEAL)
        self.cell(0, 6, f"{label}:", new_x="LMARGIN", new_y="NEXT")
        self.ln(1)
        # Light background box
        x = self.get_x()
        y = self.get_y()
        self.set_fill_color(*self.BG_LIGHT)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*self.DARK)
        # Use multi_cell for wrapping
        self.set_x(x + 2)
        self.multi_cell(180, 5, str(text or "-"), fill=True)
        self.ln(3)

    def _divider(self) -> None:
        """Print a thin grey horizontal line."""
        y = self.get_y()
        self.set_draw_color(*self.LINE)
        self.set_line_width(0.2)
        self.line(10, y, 200, y)
        self.ln(3)


def generate_prescription_pdf(rx: dict[str, Any]) -> bytes:
    """Generate a clean prescription PDF from a prescription record dict.

    Expected keys: patient_name, doctor_name, doctor_specialization,
    diagnosis, medicines, advice, follow_up_date, created_at.
    """
    pdf = _MediFlowPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Document title
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*_MediFlowPDF.DARK)
    pdf.cell(0, 10, "Prescription", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # Patient & Doctor info
    pdf._section_title("Patient & Doctor Details")
    pdf._label_value("Patient", rx.get("patient_name"), bold_value=True)
    pdf._label_value("Doctor", f"Dr. {rx.get('doctor_name', '-')}")
    pdf._label_value("Specialization", rx.get("doctor_specialization"))
    created = rx.get("created_at", "")
    if created:
        try:
            dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            created = dt.strftime("%d %b %Y, %I:%M %p")
        except (ValueError, TypeError):
            pass
    pdf._label_value("Date", created)
    pdf.ln(2)

    # Diagnosis
    pdf._section_title("Diagnosis")
    pdf._label_block("Diagnosis", rx.get("diagnosis"))

    # Medicines
    pdf._section_title("Medicines")
    pdf._label_block("Prescribed Medicines", rx.get("medicines"))

    # Advice
    advice = rx.get("advice")
    if advice:
        pdf._section_title("Advice")
        pdf._label_block("Doctor's Advice", advice)

    # Follow-up
    follow_up = rx.get("follow_up_date")
    if follow_up:
        pdf._divider()
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*_MediFlowPDF.TEAL)
        pdf.cell(0, 8, f"Follow-up Date: {follow_up}", new_x="LMARGIN", new_y="NEXT")

    return pdf.output()


def generate_triage_pdf(triage: dict[str, Any]) -> bytes:
    """Generate a clean triage vitals report PDF from a triage record dict.

    Expected keys: date, queue_type, blood_pressure, heart_rate,
    temperature, weight, oxygen_saturation, symptoms, notes, created_at.
    """
    pdf = _MediFlowPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Document title
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*_MediFlowPDF.DARK)
    pdf.cell(0, 10, "Triage / Vitals Report", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # Visit info
    pdf._section_title("Visit Information")
    pdf._label_value("Date", triage.get("date"))
    queue = str(triage.get("queue_type", "")).upper()
    pdf._label_value("Queue Type", queue, bold_value=True)
    created = triage.get("created_at", "")
    if created:
        try:
            dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            created = dt.strftime("%d %b %Y, %I:%M %p")
        except (ValueError, TypeError):
            pass
    pdf._label_value("Recorded At", created)
    pdf.ln(2)

    # Vitals in a two-column layout
    pdf._section_title("Vital Signs")

    vitals = [
        ("Blood Pressure", triage.get("blood_pressure"), "mmHg"),
        ("Heart Rate", triage.get("heart_rate"), "bpm"),
        ("Temperature", triage.get("temperature"), "°C"),
        ("Weight", triage.get("weight"), "kg"),
        ("SpO2", triage.get("oxygen_saturation"), "%"),
    ]

    for label, value, unit in vitals:
        display = f"{value} {unit}" if value is not None else "-"
        pdf._label_value(label, display)

    pdf.ln(2)

    # Symptoms
    symptoms = triage.get("symptoms")
    if symptoms:
        pdf._section_title("Symptoms")
        pdf._label_block("Reported Symptoms", symptoms)

    # Notes
    notes = triage.get("notes")
    if notes:
        pdf._section_title("Nurse Notes")
        pdf._label_block("Notes", notes)

    return pdf.output()
