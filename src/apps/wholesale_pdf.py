"""PDF rendering for the canonical wholesale daily report."""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.money import format_unit_price


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
        ["Ventes", "Marge ventes", "Cash reçu", "Marge encaissée", "Nouvelle dette", "Dette restante"],
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
    collection_breakdown = Table([
        ["Détail des encaissements", "Cash", "Marge"],
        [
            "Ventes directes",
            f"${totals['current_sale_cash_collected']:.2f}",
            (
                "À vérifier"
                if totals["collected_margin_has_anomaly"]
                else f"${totals['current_sale_collected_margin']:.2f}"
            ),
        ],
        [
            "Dettes précédentes",
            f"${totals['prior_debt_cash_collected']:.2f}",
            (
                "À vérifier"
                if totals["collected_margin_has_anomaly"]
                else f"${totals['prior_debt_collected_margin']:.2f}"
            ),
        ],
    ])
    collection_breakdown.setStyle(_table_style())
    story.extend([
        summary,
        Spacer(1, 0.3 * cm),
        collection_breakdown,
        Spacer(1, 0.5 * cm),
    ])
    margin_rows = [[
        "Réseau", "Unités", "Prix vendu moyen", "Coût stock moyen",
        "Marge commerciale", "Arrondi", "Marge totale",
    ]]
    for row in report["networks"].values():
        if not row["sold"]:
            continue
        has_cost_anomaly = (
            row["network"].name in report["cost_anomalies"]["networks"]
        )
        margin_rows.append([
            row["network"].value.capitalize(),
            f"{row['sold']:.0f}",
            f"${format_unit_price(row['average_selling_price'])}",
            f"${format_unit_price(row['average_cost_per_unit'])}",
            "À vérifier" if has_cost_anomaly else f"${row['commercial_margin']:.2f}",
            "À vérifier" if has_cost_anomaly else f"${row['rounding_adjustment']:+.2f}",
            "À vérifier" if has_cost_anomaly else f"${row['margin']:.2f}",
        ])
    if len(margin_rows) == 1:
        margin_rows.append(["—", "0", "$0.00000", "$0.00000", "$0.00", "$0.00", "$0.00"])
    margin_table = Table(margin_rows, repeatRows=1)
    margin_table.setStyle(_table_style())
    story.extend([
        Paragraph("Comprendre la marge", styles["Heading2"]),
        Paragraph(
            "Le coût utilisé est la moyenne exacte du stock disponible.",
            styles["Normal"],
        ),
        margin_table,
        Spacer(1, 0.5 * cm),
    ])
    if report["cost_anomalies"]["details"]:
        story.append(Paragraph(
            "Les ventes et paiements sont enregistrés. Seules les marges "
            "suivantes nécessitent une vérification :",
            styles["Normal"],
        ))
        for issue in report["cost_anomalies"]["details"]:
            story.append(Paragraph(
                f"Vente #{issue['sale_id']} · {issue['client_name']} · "
                f"{issue['sale_date']:%d/%m/%Y} · "
                f"{issue['network'].value.capitalize()} · {issue['reason']}",
                styles["Normal"],
            ))
        story.append(Spacer(1, 0.4 * cm))

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
            f"${format_unit_price(group.price_per_unit_applied)}",
            str(group.quantity),
            f"${group.revenue:.2f}",
            "À vérifier" if has_cost_anomaly else f"${group.cost:.2f}",
            "À vérifier" if has_cost_anomaly else f"${group.margin:.2f}",
        ])
    if len(price_rows) == 1:
        price_rows.append(["—", "—", "0", "$0.00", "$0.00", "$0.00"])
    price_table = Table(price_rows, repeatRows=1)
    price_table.setStyle(_table_style())
    story.extend([
        Paragraph("Marge par prix de vente", styles["Heading2"]),
        price_table,
        Spacer(1, 0.5 * cm),
    ])

    debt_rows = [
        ["Calcul de la dette", "Montant"],
        ["Dette au début", f"${totals['opening_debt']:.2f}"],
        ["+ Nouvelle dette", f"${totals['new_debt']:.2f}"],
        ["- Dette encaissée", f"${totals['old_debt_collected']:.2f}"],
        ["  Jours précédents", f"${totals['prior_day_debt_collected']:.2f}"],
        ["  Même jour", f"${totals['same_day_debt_collected']:.2f}"],
        ["= Dette restante", f"${totals['remaining_debt']:.2f}"],
    ]
    debt_table = Table(debt_rows, repeatRows=1)
    debt_table.setStyle(_table_style())
    client_debt_rows = [["Dettes par client", "Montant"]]
    client_debt_rows.extend([
        [entry["client_name"], f"${entry['amount']:.2f}"]
        for entry in report["client_debts"]
    ])
    client_debt_rows.append([
        "Total clients", f"${totals['client_debt_total']:.2f}"
    ])
    client_debt_rows.append([
        "Écart de contrôle",
        f"${abs(totals['debt_reconciliation_difference']):.2f}",
    ])
    client_debt_table = Table(client_debt_rows, repeatRows=1)
    client_debt_table.setStyle(_table_style())
    story.extend([
        Paragraph("Dettes et encaissements", styles["Heading2"]),
        debt_table,
        Spacer(1, 0.3 * cm),
        client_debt_table,
    ])

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
