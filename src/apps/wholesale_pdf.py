"""PDF rendering for the canonical wholesale daily report."""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def generate_wholesale_report_pdf(*, business, report) -> BytesIO:
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=landscape(A4),
        rightMargin=1.2 * cm,
        leftMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"Rapport journalier — {business.name}", styles["Title"]),
        Paragraph(f"Date: {report['date'].strftime('%d/%m/%Y')} · Devise: USD", styles["Normal"]),
        Spacer(1, 0.4 * cm),
    ]

    totals = report["totals"]
    sales_margin_text = (
        "À vérifier"
        if totals["sales_margin_has_anomaly"]
        else f"${totals['sales_margin']:.2f}"
    )
    collected_margin_text = (
        "À vérifier"
        if totals["collected_margin_has_anomaly"]
        else f"${totals['collected_margin']:.2f}"
    )
    summary = Table([
        ["Ventes", "Marge ventes", "Cash encaissé", "Marge cash", "Nouvelle dette", "Dette restante"],
        [
            f"${totals['revenue']:.2f}",
            sales_margin_text,
            f"${totals['cash_collected']:.2f}",
            collected_margin_text,
            f"${totals['new_debt']:.2f}",
            f"${totals['remaining_debt']:.2f}",
        ],
    ])
    summary.setStyle(_table_style())
    story.extend([summary, Spacer(1, 0.5 * cm)])

    stock_rows = [[
        "Réseau", "Ouverture", "Acheté", "Coût achat", "Vendu",
        "Clôture", "Revenu", "Coût vendu", "Marge",
    ]]
    for row in report["networks"].values():
        has_cost_anomaly = row["network"].name in report["cost_anomalies"]["networks"]
        stock_rows.append([
            row["network"].value.capitalize(),
            f"{row['opening']:.0f}",
            f"{row['purchased']:.0f}",
            f"${row['purchase_cost']:.2f}",
            f"{row['sold']:.0f}",
            f"{row['closing']:.0f}",
            f"${row['revenue']:.2f}",
            "À vérifier" if has_cost_anomaly else f"${row['cost']:.2f}",
            "À vérifier" if has_cost_anomaly else f"${row['margin']:.2f}",
        ])
    stock_table = Table(stock_rows, repeatRows=1)
    stock_table.setStyle(_table_style())
    story.extend([Paragraph("Mouvements de stock", styles["Heading2"]), stock_table, Spacer(1, 0.5 * cm)])

    price_rows = [["Réseau", "Prix", "Unités", "Revenu", "Coût", "Marge"]]
    for group in report["price_groups"]:
        has_cost_anomaly = group.network.name in report["cost_anomalies"]["networks"]
        price_rows.append([
            group.network.value.capitalize(),
            f"${group.price_per_unit_applied:.5f}",
            str(group.quantity),
            f"${group.revenue:.2f}",
            "À vérifier" if has_cost_anomaly else f"${group.cost:.2f}",
            "À vérifier" if has_cost_anomaly else f"${group.margin:.2f}",
        ])
    if len(price_rows) == 1:
        price_rows.append(["—", "—", "0", "$0.00", "$0.00", "$0.00"])
    price_table = Table(price_rows, repeatRows=1)
    price_table.setStyle(_table_style())
    story.extend([Paragraph("Marge par prix de vente", styles["Heading2"]), price_table])

    document.build(story)
    output.seek(0)
    return output


def _table_style() -> TableStyle:
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#5e72e4")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9d9d9")),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f8fa")]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ])
