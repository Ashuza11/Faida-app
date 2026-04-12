# ============================================================
# PDF GENERATION UTILITY
# ============================================================

from io import BytesIO
from decimal import Decimal
from datetime import datetime

# ReportLab imports
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    HRFlowable,
    KeepTogether,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT


# ── Colour palette (matches Argon dashboard theme) ──────────────────────────
C_PRIMARY  = colors.HexColor('#5e72e4')
C_SUCCESS  = colors.HexColor('#2dce89')
C_DANGER   = colors.HexColor('#f5365c')
C_INFO     = colors.HexColor('#11cdef')
C_DARK     = colors.HexColor('#32325d')
C_MUTED    = colors.HexColor('#8898aa')
C_LIGHT_BG = colors.HexColor('#f8f9fe')
C_BORDER   = colors.HexColor('#dee2e6')
C_WHITE    = colors.white


def format_number(value, decimals=2):
    """Format a number with thousand separators and decimal places."""
    if value is None:
        value = Decimal("0.00")
    if not isinstance(value, (int, float, Decimal)):
        try:
            value = Decimal(str(value))
        except Exception:
            value = Decimal("0.00")
    return f"{value:,.{decimals}f}"


def _make_styles():
    """Return a dict of named ParagraphStyles."""
    base = getSampleStyleSheet()
    return {
        'title': ParagraphStyle('Title_', parent=base['Heading1'],
                                fontSize=16, alignment=TA_CENTER,
                                spaceAfter=4, textColor=C_PRIMARY),
        'subtitle': ParagraphStyle('Sub_', parent=base['Normal'],
                                   fontSize=10, alignment=TA_CENTER,
                                   spaceAfter=10, textColor=C_MUTED),
        'section': ParagraphStyle('Sect_', parent=base['Heading2'],
                                  fontSize=11, spaceBefore=10, spaceAfter=5,
                                  textColor=C_DARK),
        'footer': ParagraphStyle('Footer_', parent=base['Normal'],
                                 fontSize=7, alignment=TA_CENTER,
                                 textColor=C_MUTED),
        'cell_bold': ParagraphStyle('CB_', parent=base['Normal'],
                                    fontSize=8, fontName='Helvetica-Bold'),
        'cell': ParagraphStyle('C_', parent=base['Normal'], fontSize=8),
    }


def _hr():
    return HRFlowable(width="100%", thickness=0.5, color=C_BORDER,
                      spaceBefore=4, spaceAfter=6)


def _header_style(col_count, header_row=0, total_row=-1):
    """Return common TableStyle commands for data tables."""
    return TableStyle([
        # Header row
        ('BACKGROUND',   (0, header_row), (-1, header_row), C_PRIMARY),
        ('TEXTCOLOR',    (0, header_row), (-1, header_row), C_WHITE),
        ('FONTNAME',     (0, header_row), (-1, header_row), 'Helvetica-Bold'),
        ('FONTSIZE',     (0, header_row), (-1, header_row), 8),
        ('ALIGN',        (0, header_row), (-1, header_row), 'CENTER'),
        ('TOPPADDING',   (0, header_row), (-1, header_row), 6),
        ('BOTTOMPADDING',(0, header_row), (-1, header_row), 6),
        # Body
        ('FONTNAME',  (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE',  (0, 1), (-1, -1), 8),
        ('ALIGN',     (1, 1), (-1, -1), 'RIGHT'),
        ('ALIGN',     (0, 1), (0, -1),  'LEFT'),
        ('TOPPADDING',    (0, 1), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        # Alternating rows
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [C_WHITE, C_LIGHT_BG]),
        # Grid
        ('GRID', (0, 0), (-1, -1), 0.4, C_BORDER),
    ])


def generate_daily_report_pdf(
    report_data: dict,
    grand_totals: dict,
    selected_date: str,
    business_name: str = "Mon Entreprise",
    networks: list = None,
    # Financial sections (new)
    cash_summary: dict = None,
    profit_data: dict = None,
    price_breakdown: dict = None,
    grand_profit=None,
    grand_revenue=None,
    grand_cost=None,
    debts_today: list = None,
    all_purchases: list = None,
    sales_today: list = None,
) -> BytesIO:
    """
    Generate a full-page PDF for the daily report, matching the web rapports page.
    Sections:
      1. KPI Summary row
      2. Journal des Transactions (stock balances)
      3. Bénéfice par Réseau + Détail Multi-Prix
      4. Dettes du Jour  (optional)
      5. Historique des Achats Stock
      6. Historique des Ventes
    """

    zero = Decimal("0.00")
    cash_summary  = cash_summary  or {"cash": zero, "credit": zero, "total": zero, "count": 0}
    profit_data   = profit_data   or {}
    price_breakdown = price_breakdown or {}
    grand_profit  = grand_profit  or zero
    grand_revenue = grand_revenue or zero
    grand_cost    = grand_cost    or zero
    debts_today   = debts_today   or []
    all_purchases = all_purchases or []
    sales_today   = sales_today   or []

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=1.2 * cm,
        leftMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )

    avail_w = landscape(A4)[0] - 2.4 * cm
    styles = _make_styles()
    story = []

    # ── HEADER ──────────────────────────────────────────────────────────────
    story.append(Paragraph(business_name, styles['title']))
    story.append(Paragraph(f"Rapport Journalier — {selected_date}", styles['subtitle']))
    story.append(_hr())

    # ── 1. KPI SUMMARY ROW ───────────────────────────────────────────────────
    story.append(Paragraph("Résumé de la Journée", styles['section']))

    kpi_data = [
        ['Total Ventes', 'Cash Reçu', 'Crédit (Dettes)', 'Bénéfice Net'],
        [
            format_number(cash_summary['total']) + ' FC',
            format_number(cash_summary['cash']) + ' FC',
            format_number(cash_summary['credit']) + ' FC',
            format_number(grand_profit) + ' FC',
        ],
        [
            f"{cash_summary['count']} vente(s)",
            'Paiements reçus',
            f"{len(debts_today)} client(s) en dette",
            f"Rev: {format_number(grand_revenue)} — Coût: {format_number(grand_cost)}",
        ],
    ]
    kpi_w = avail_w / 4
    kpi_table = Table(kpi_data, colWidths=[kpi_w] * 4)
    kpi_style = TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0),  C_PRIMARY),
        ('TEXTCOLOR',     (0, 0), (-1, 0),  C_WHITE),
        ('FONTNAME',      (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, 0),  8),
        ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME',      (0, 1), (-1, 1),  'Helvetica-Bold'),
        ('FONTSIZE',      (0, 1), (-1, 1),  11),
        ('TEXTCOLOR',     (0, 1), (0, 1),   C_PRIMARY),
        ('TEXTCOLOR',     (1, 1), (1, 1),   C_SUCCESS),
        ('TEXTCOLOR',     (2, 1), (2, 1),   C_DANGER),
        ('TEXTCOLOR',     (3, 1), (3, 1),   C_SUCCESS if grand_profit >= 0 else C_DANGER),
        ('FONTNAME',      (0, 2), (-1, 2),  'Helvetica'),
        ('FONTSIZE',      (0, 2), (-1, 2),  7),
        ('TEXTCOLOR',     (0, 2), (-1, 2),  C_MUTED),
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('GRID',          (0, 0), (-1, -1), 0.4, C_BORDER),
    ])
    kpi_table.setStyle(kpi_style)
    story.append(kpi_table)
    story.append(Spacer(1, 8))

    # ── 2. JOURNAL DES TRANSACTIONS ──────────────────────────────────────────
    story.append(Paragraph("Journal des Transactions (Stocks)", styles['section']))

    if networks:
        network_names = [n.name for n in networks]
    else:
        network_names = list(report_data.keys())

    jt_headers = ['Réseau', 'Stock Initial', 'Stock Acheté',
                  'Stock Vendu', 'Stock Final', 'Valeur Virtuelle (FC)']
    jt_data = [jt_headers]
    for nn in network_names:
        d = report_data.get(nn, {})
        jt_data.append([
            nn.upper(),
            format_number(d.get('initial_stock', 0), 0),
            format_number(d.get('purchased_stock', 0), 0),
            format_number(d.get('sold_stock', 0), 0),
            format_number(d.get('final_stock', 0), 0),
            format_number(d.get('virtual_value', 0)),
        ])
    jt_data.append([
        'TOTAL GÉNÉRAL',
        format_number(grand_totals.get('initial_stock', 0), 0),
        format_number(grand_totals.get('purchased_stock', 0), 0),
        format_number(grand_totals.get('sold_stock', 0), 0),
        format_number(grand_totals.get('final_stock', 0), 0),
        format_number(grand_totals.get('virtual_value', 0)),
    ])

    jt_col_w = [avail_w * r for r in (0.14, 0.14, 0.15, 0.15, 0.14, 0.28)]
    jt_table = Table(jt_data, colWidths=jt_col_w)
    jt_style = _header_style(len(jt_col_w))
    # Total row override
    jt_style.add('BACKGROUND', (0, -1), (-1, -1), C_PRIMARY)
    jt_style.add('TEXTCOLOR',  (0, -1), (-1, -1), C_WHITE)
    jt_style.add('FONTNAME',   (0, -1), (-1, -1), 'Helvetica-Bold')
    jt_table.setStyle(jt_style)
    story.append(jt_table)
    story.append(Spacer(1, 8))

    # ── 3. BÉNÉFICE PAR RÉSEAU ───────────────────────────────────────────────
    story.append(Paragraph("Bénéfice par Réseau", styles['section']))

    prof_headers = ['Réseau', 'Qté Vendue', "Prix d'Achat (FC)",
                    'Coût Total (FC)', 'Revenu (FC)', 'Bénéfice (FC)']
    prof_data = [prof_headers]
    for nn in network_names:
        p = profit_data.get(nn, {})
        prof_data.append([
            nn.upper(),
            format_number(p.get('qty', 0), 0),
            format_number(p.get('buying_price', 0)),
            format_number(p.get('cost', 0)),
            format_number(p.get('revenue', 0)),
            format_number(p.get('profit', 0)),
        ])
    prof_data.append([
        'TOTAL',
        format_number(sum(p.get('qty', 0) for p in profit_data.values()), 0),
        '—',
        format_number(grand_cost),
        format_number(grand_revenue),
        format_number(grand_profit),
    ])

    prof_col_w = [avail_w * r for r in (0.14, 0.13, 0.17, 0.18, 0.18, 0.20)]
    prof_table = Table(prof_data, colWidths=prof_col_w)
    prof_style = _header_style(len(prof_col_w))
    prof_style.add('BACKGROUND', (0, -1), (-1, -1), C_PRIMARY)
    prof_style.add('TEXTCOLOR',  (0, -1), (-1, -1), C_WHITE)
    prof_style.add('FONTNAME',   (0, -1), (-1, -1), 'Helvetica-Bold')
    # Colour profit cells per row (positive=green, negative=red)
    for i, nn in enumerate(network_names, start=1):
        p = profit_data.get(nn, {})
        profit_val = p.get('profit', Decimal("0"))
        cell_colour = C_SUCCESS if profit_val >= 0 else C_DANGER
        prof_style.add('TEXTCOLOR', (5, i), (5, i), cell_colour)
        prof_style.add('FONTNAME',  (5, i), (5, i), 'Helvetica-Bold')
    prof_table.setStyle(prof_style)
    story.append(prof_table)

    # ── Multi-price breakdown (right after profit table) ─────────────────────
    has_breakdown = any(price_breakdown.get(nn) for nn in network_names)
    if has_breakdown:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Détail par Prix de Vente", styles['section']))
        pb_blocks = []
        for nn in network_names:
            entries = price_breakdown.get(nn)
            if not entries:
                continue
            pb_blocks.append(Paragraph(f"  {nn.upper()}", ParagraphStyle(
                'PBNet', parent=_make_styles()['cell_bold'],
                textColor=C_PRIMARY, spaceBefore=4)))
            pb_headers = ['Prix Unitaire (FC)', 'Quantité', 'Revenu (FC)']
            pb_rows = [pb_headers]
            for e in entries:
                pb_rows.append([
                    format_number(e['price']),
                    format_number(e['qty'], 0),
                    format_number(e['revenue']),
                ])
            pb_col_w = [avail_w * r for r in (0.20, 0.10, 0.20)]
            pb_t = Table(pb_rows, colWidths=pb_col_w)
            pb_t.setStyle(_header_style(3))
            pb_blocks.append(pb_t)
        story.extend(pb_blocks)

    story.append(Spacer(1, 8))

    # ── 4. DETTES DU JOUR ────────────────────────────────────────────────────
    if debts_today:
        story.append(Paragraph(
            f"Dettes du Jour  ({len(debts_today)} client(s) — "
            f"Total: {format_number(cash_summary['credit'])} FC)",
            styles['section']))
        debt_headers = ['#', 'Client', 'Total Dû (FC)', 'Cash Payé (FC)', 'Dette Restante (FC)', 'Heure']
        debt_rows = [debt_headers]
        for i, sale in enumerate(debts_today, 1):
            client_name = getattr(sale, 'client_display_name', None) or '—'
            debt_rows.append([
                str(i),
                client_name,
                format_number(sale.total_amount_due),
                format_number(sale.cash_paid),
                format_number(sale.debt_amount),
                sale.created_at.strftime('%H:%M'),
            ])
        debt_col_w = [avail_w * r for r in (0.05, 0.30, 0.17, 0.17, 0.18, 0.13)]
        debt_table = Table(debt_rows, colWidths=debt_col_w)
        debt_style = _header_style(len(debt_col_w))
        # Highlight debt amount column red
        for i in range(1, len(debts_today) + 1):
            debt_style.add('TEXTCOLOR', (4, i), (4, i), C_DANGER)
            debt_style.add('FONTNAME',  (4, i), (4, i), 'Helvetica-Bold')
        debt_table.setStyle(debt_style)
        story.append(debt_table)
        story.append(Spacer(1, 8))

    # ── 5. HISTORIQUE DES ACHATS STOCK ───────────────────────────────────────
    story.append(Paragraph(
        f"Historique des Achats Stock  ({len(all_purchases)} achat(s))",
        styles['section']))
    if all_purchases:
        pur_headers = ['#', 'Réseau', 'Quantité', "Prix d'Achat (FC)", 'Montant Total (FC)', 'Acheteur', 'Heure']
        pur_rows = [pur_headers]
        for i, p in enumerate(all_purchases, 1):
            total_amt = p.amount_purchased * p.buying_price_at_purchase
            buyer = p.purchased_by.username if p.purchased_by else '—'
            pur_rows.append([
                str(i),
                p.network.value.upper(),
                format_number(p.amount_purchased, 0),
                format_number(p.buying_price_at_purchase),
                format_number(total_amt),
                buyer,
                p.created_at.strftime('%H:%M'),
            ])
        pur_col_w = [avail_w * r for r in (0.04, 0.12, 0.13, 0.16, 0.18, 0.24, 0.13)]
        pur_table = Table(pur_rows, colWidths=pur_col_w)
        pur_table.setStyle(_header_style(len(pur_col_w)))
        story.append(pur_table)
    else:
        story.append(Paragraph("Aucun achat de stock pour cette date.", styles['cell']))
    story.append(Spacer(1, 8))

    # ── 6. HISTORIQUE DES VENTES ─────────────────────────────────────────────
    story.append(Paragraph(
        f"Historique des Ventes  ({len(sales_today)} vente(s))",
        styles['section']))
    if sales_today:
        sal_headers = ['#', 'Client', 'Vendeur', 'Total Dû (FC)', 'Cash Payé (FC)', 'Dette (FC)', 'Heure']
        sal_rows = [sal_headers]
        for i, s in enumerate(sales_today, 1):
            client_name = getattr(s, 'client_display_name', None) or '—'
            seller_name = s.seller.username if s.seller else '—'
            sal_rows.append([
                str(i),
                client_name,
                seller_name,
                format_number(s.total_amount_due),
                format_number(s.cash_paid),
                format_number(s.debt_amount),
                s.created_at.strftime('%H:%M'),
            ])
        sal_col_w = [avail_w * r for r in (0.04, 0.26, 0.18, 0.15, 0.15, 0.12, 0.10)]
        sal_table = Table(sal_rows, colWidths=sal_col_w)
        sal_style = _header_style(len(sal_col_w))
        for i, s in enumerate(sales_today, 1):
            if s.debt_amount > 0:
                sal_style.add('TEXTCOLOR', (5, i), (5, i), C_DANGER)
                sal_style.add('FONTNAME',  (5, i), (5, i), 'Helvetica-Bold')
        sal_table.setStyle(sal_style)
        story.append(sal_table)
    else:
        story.append(Paragraph("Aucune vente enregistrée pour cette date.", styles['cell']))

    # ── FOOTER ───────────────────────────────────────────────────────────────
    generated_at = datetime.now().strftime("%d/%m/%Y à %H:%M")
    story.append(KeepTogether([
        Spacer(1, 10),
        _hr(),
        Paragraph(f"Rapport généré le {generated_at} • Faida App", styles['footer']),
    ]))

    doc.build(story)
    buffer.seek(0)
    return buffer
