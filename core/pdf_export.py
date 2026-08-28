from __future__ import annotations

from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from core.formatting import amount_in_words, document_label, french_date, money


ACCENT = colors.HexColor("#121D7C")
SLATE = colors.HexColor("#334155")
MUTED = colors.HexColor("#6B7280")
LIGHT = colors.HexColor("#F3F4F6")
BORDER = colors.HexColor("#D1D5DB")
ROOT_DIR = Path(__file__).resolve().parent.parent


def _safe(value: object) -> str:
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _company_legal_line(company: dict) -> str:
    entries = [
        ("IF", company.get("fiscal_id")),
        ("RC", company.get("rc") or company.get("registration")),
        ("PATENTE", company.get("patente")),
        ("CNSS", company.get("cnss")),
        ("ICE", company.get("tax_id")),
    ]
    return " - ".join(f"{label} : {value}" for label, value in entries if value)


def _draw_footer(canvas, doc, company: dict) -> None:
    canvas.saveState()
    width, _ = A4
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.6)
    canvas.line(16 * mm, 20 * mm, width - 16 * mm, 20 * mm)
    footer_style = ParagraphStyle(
        "Footer",
        fontName="Helvetica",
        fontSize=7.4,
        leading=9,
        alignment=1,
        textColor=SLATE,
    )
    address_line = " - ".join(
        str(value)
        for value in [company.get("address"), company.get("phone"), company.get("email")]
        if value
    )
    text = f"<b>{_safe(company.get('name'))}</b><br/>{_safe(address_line)}"
    legal = _company_legal_line(company)
    if legal:
        text += f"<br/>{_safe(legal)}"
    paragraph = Paragraph(text, footer_style)
    paragraph.wrapOn(canvas, width - 32 * mm, 16 * mm)
    paragraph.drawOn(canvas, 16 * mm, 6 * mm)
    canvas.restoreState()


def build_document_pdf(document: dict, company: dict) -> bytes:
    buffer = BytesIO()
    pdf = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=12 * mm,
        bottomMargin=30 * mm,
        title=document["number"],
        author=company.get("name", ""),
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8.4, leading=11, textColor=SLATE))
    styles.add(ParagraphStyle(name="SmallMuted", parent=styles["BodyText"], fontSize=8, leading=10, textColor=MUTED))
    styles.add(ParagraphStyle(name="BodyRight", parent=styles["BodyText"], alignment=TA_RIGHT, fontSize=9, leading=12))
    styles.add(ParagraphStyle(name="DocTitle", parent=styles["Title"], alignment=TA_LEFT, fontSize=21, textColor=colors.black, leading=25))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading3"], fontSize=9, textColor=ACCENT, spaceAfter=4))
    styles.add(ParagraphStyle(name="AmountWords", parent=styles["BodyText"], fontSize=8.6, leading=11, textColor=SLATE))

    title = document_label(document["doc_type"])
    title_content = Paragraph(
        f"<b>{_safe(title)} N° : {_safe(document['number'])}</b><br/>"
        f"<font color='#6B7280' size='10'>Date : {french_date(document['issue_date'])}</font>",
        styles["DocTitle"],
    )
    logo_cell: object = ""
    logo_value = company.get("logo_path")
    if logo_value:
        logo_path = Path(str(logo_value))
        if not logo_path.is_absolute():
            logo_path = ROOT_DIR / logo_path
        if logo_path.exists():
            logo_cell = Image(str(logo_path))
            aspect_ratio = logo_cell.imageWidth / logo_cell.imageHeight
            logo_height = 27 * mm
            logo_width = min(43 * mm, logo_height * aspect_ratio)
            logo_cell.drawWidth = logo_width
            logo_cell.drawHeight = logo_width / aspect_ratio
            logo_cell.hAlign = "RIGHT"
    header = Table([[title_content, logo_cell]], colWidths=[126 * mm, 44 * mm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT")]))

    company_lines = [f"<b>{_safe(company.get('name'))}</b>"]
    if company.get("tax_id"):
        company_lines.append(f"<b>ICE :</b> {_safe(company['tax_id'])}")
    if company.get("address"):
        company_lines.append(f"<b>Adresse :</b> {_safe(company['address']).replace(chr(10), '<br/>')}")
    if company.get("phone"):
        company_lines.append(f"<b>Téléphone :</b> {_safe(company['phone'])}")
    if company.get("email"):
        company_lines.append(f"<b>E-mail :</b> {_safe(company['email'])}")

    client_lines = [f"<b>{_safe(document['customer_name'])}</b>"]
    if document.get("customer_tax_id"):
        client_lines.append(f"<b>ICE :</b> {_safe(document['customer_tax_id'])}")
    if document.get("customer_address"):
        client_lines.append(f"<b>Adresse :</b> {_safe(document['customer_address']).replace(chr(10), '<br/>')}")
    if document.get("customer_phone"):
        client_lines.append(f"<b>Téléphone :</b> {_safe(document['customer_phone'])}")
    if document.get("customer_email"):
        client_lines.append(f"<b>E-mail :</b> {_safe(document['customer_email'])}")

    cards = Table(
        [
            [Paragraph("<b>Informations sur l'entreprise</b>", styles["Small"]), Paragraph("<b>Client</b>", styles["Small"])],
            [Paragraph("<br/>".join(company_lines), styles["Small"]), Paragraph("<br/>".join(client_lines), styles["Small"])],
        ],
        colWidths=[84 * mm, 84 * mm],
    )
    cards.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))

    story = [header, Spacer(1, 6 * mm), cards, Spacer(1, 7 * mm)]
    delivery_note = document["doc_type"] == "BL"
    show_prices = not delivery_note or bool(company.get("show_prices_on_delivery_note", 1))

    if show_prices:
        table_data = [["Désignation", "Prix unitaire HT", "Quantité", "Prix total HT"]]
        for line in document["lines"]:
            description = _safe(line["description"])
            if float(line.get("discount_rate", 0)):
                description += f"<br/><font color='#6B7280'>Remise : {line['discount_rate']:g} %</font>"
            table_data.append([
                Paragraph(description, styles["Small"]),
                money(line["unit_price"], document["currency"]),
                f"{line['quantity']:g} {_safe(line['unit'])}",
                money(line["line_subtotal"], document["currency"]),
            ])
        widths = [84 * mm, 29 * mm, 25 * mm, 32 * mm]
    else:
        table_data = [["Désignation", "Quantité", "Unité"]]
        for line in document["lines"]:
            table_data.append([
                Paragraph(_safe(line["description"]), styles["Small"]),
                f"{line['quantity']:g}",
                _safe(line["unit"]),
            ])
        widths = [125 * mm, 20 * mm, 25 * mm]

    lines_table = Table(table_data, colWidths=widths, repeatRows=1)
    lines_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("FONTSIZE", (0, 1), (-1, -1), 8.2),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.45, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(lines_table)

    if show_prices:
        gross_subtotal = sum(float(line["quantity"]) * float(line["unit_price"]) for line in document["lines"])
        discount_total = max(0.0, gross_subtotal - float(document["subtotal"]))
        total_rows = [["Sous-total", money(gross_subtotal, document["currency"])]]
        if discount_total > 0.004:
            total_rows.append(["Remise", f"- {money(discount_total, document['currency'])}"])
        total_rows.extend([
            ["Total HT", money(document["subtotal"], document["currency"])],
            ["TVA", money(document["tax_total"], document["currency"])],
            ["Total TTC", money(document["total"], document["currency"])],
        ])
        totals = Table(total_rows, colWidths=[38 * mm, 37 * mm], hAlign="RIGHT")
        totals.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ("BACKGROUND", (0, -1), (-1, -1), LIGHT),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, -1), (-1, -1), ACCENT),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        amount_text = (
            "Arrêtée à la somme de "
            + _safe(amount_in_words(document["total"], document["currency"]))
            + " toutes taxes comprises."
        )
        summary = Table(
            [[Paragraph(amount_text, styles["AmountWords"]), totals]],
            colWidths=[92 * mm, 78 * mm],
            style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 8)]),
        )
        story.extend([Spacer(1, 5 * mm), summary])

    details = []
    if document.get("notes"):
        details.extend([Paragraph("Notes / commentaires", styles["Section"]), Paragraph(_safe(document["notes"]).replace("\n", "<br/>"), styles["Small"]), Spacer(1, 3 * mm)])
    if document.get("terms"):
        details.extend([Paragraph("Conditions", styles["Section"]), Paragraph(_safe(document["terms"]).replace("\n", "<br/>"), styles["Small"]), Spacer(1, 3 * mm)])
    if document["doc_type"] == "FACTURE" and (company.get("rib") or company.get("swift") or company.get("bank_details")):
        payment_lines = []
        if company.get("rib"):
            payment_lines.append(f"<b>RIB :</b> {_safe(company['rib'])}")
        if company.get("swift"):
            payment_lines.append(f"<b>Code SWIFT :</b> {_safe(company['swift'])}")
        if not payment_lines and company.get("bank_details"):
            payment_lines.append(_safe(company["bank_details"]).replace("\n", "<br/>"))
        details.extend([Paragraph("Coordonnées de paiement", styles["Section"]), Paragraph("<br/>".join(payment_lines), styles["Small"]), Spacer(1, 3 * mm)])
    if delivery_note:
        signature = Table(
            [[Paragraph("<b>Livré par</b><br/><br/><br/>Date et signature", styles["Small"]), Paragraph("<b>Reçu par</b><br/><br/><br/>Date, nom et signature", styles["Small"])]],
            colWidths=[85 * mm, 85 * mm],
            style=TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]),
        )
        details.append(signature)
    if company.get("document_footer"):
        details.extend([Spacer(1, 2 * mm), Paragraph(_safe(company["document_footer"]), styles["SmallMuted"])])
    if details:
        story.extend([Spacer(1, 6 * mm), KeepTogether(details)])

    def footer(canvas, doc):
        _draw_footer(canvas, doc, company)

    pdf.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
