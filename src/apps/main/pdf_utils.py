# ============================================================
# PDF GENERATION UTILITY
# ============================================================

from io import BytesIO
from decimal import Decimal
from datetime import date, datetime

# ReportLab imports
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    Image,
    HRFlowable,
    KeepTogether,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT


def format_number(value, decimals=2):
    """Format a number with thousand separators and decimal places."""
    if value is None:
        value = Decimal("0.00")
    if not isinstance(value, (int, float, Decimal)):
        try:
            value = Decimal(str(value))
        except:
            value = Decimal("0.00")
    return f"{value:,.{decimals}f}"


def generate_daily_report_pdf(
    report_data: dict,
    grand_totals: dict,
    selected_date: str,
    business_name: str = "Mon Entreprise",
    networks: list = None
) -> BytesIO:
    """
    Generate a PDF for the daily transaction journal report.

    Args:
        report_data: Dict with network data {network_name: {initial_stock, purchased_stock, ...}}
        grand_totals: Dict with totals {initial_stock, purchased_stock, sold_stock, ...}
        selected_date: Date string (YYYY-MM-DD)
        business_name: Name of the business for the header
        networks: List of NetworkType enums (optional, will extract from report_data if not provided)

    Returns:
        BytesIO buffer containing the PDF
    """

    # Create buffer
    buffer = BytesIO()

    # Create document with A4 landscape for better table fit
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=1.5*cm,
        leftMargin=1.5*cm,
        topMargin=1.5*cm,
        bottomMargin=1.5*cm
    )

    # Styles
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        alignment=TA_CENTER,
        spaceAfter=6,
        textColor=colors.HexColor('#5e72e4')  # Primary color
    )

    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Normal'],
        fontSize=12,
        alignment=TA_CENTER,
        spaceAfter=12,
        textColor=colors.grey
    )

    section_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontSize=13,
        spaceBefore=8,
        spaceAfter=6,
        textColor=colors.HexColor('#32325d')
    )

    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        alignment=TA_CENTER,
        textColor=colors.grey
    )

    # Build story (content)
    story = []

    # === HEADER ===
    story.append(Paragraph(business_name, title_style))
    story.append(
        Paragraph(f"Rapport Journalier - {selected_date}", subtitle_style))

    # Horizontal line
    story.append(HRFlowable(
        width="100%",
        thickness=1,
        color=colors.HexColor('#e9ecef'),
        spaceBefore=10,
        spaceAfter=20
    ))

    # === TRANSACTION JOURNAL TABLE ===
    story.append(Paragraph("Journal des Transactions", section_style))

    # Table headers
    table_headers = [
        'Réseau',
        'Stock Initial',
        'Stock Acheté',
        'Stock Vendu',
        'Stock Final',
        'Valeur (FC)',
        'Dettes (FC)'
    ]

    # Build table data
    table_data = [table_headers]

    # Add network rows
    if networks:
        network_names = [n.name for n in networks]
    else:
        network_names = list(report_data.keys())

    for network_name in network_names:
        data = report_data.get(network_name, {})
        row = [
            network_name.upper(),
            format_number(data.get('initial_stock', 0)),
            format_number(data.get('purchased_stock', 0)),
            format_number(data.get('sold_stock', 0)),
            format_number(data.get('final_stock', 0)),
            format_number(data.get('virtual_value', 0)),
            format_number(data.get('debt_amount', 0)),
        ]
        table_data.append(row)

    # Add totals row
    totals_row = [
        'TOTAL GÉNÉRAL',
        format_number(grand_totals.get('initial_stock', 0)),
        format_number(grand_totals.get('purchased_stock', 0)),
        format_number(grand_totals.get('sold_stock', 0)),
        format_number(grand_totals.get('final_stock', 0)),
        format_number(grand_totals.get('virtual_value', 0)),
        format_number(grand_totals.get('total_debts', 0)),
    ]
    table_data.append(totals_row)

    # Calculate column widths (landscape A4 width minus margins)
    available_width = landscape(A4)[0] - 3*cm
    col_widths = [
        available_width * 0.12,  # Réseau
        available_width * 0.14,  # Stock Initial
        available_width * 0.14,  # Stock Acheté
        available_width * 0.14,  # Stock Vendu
        available_width * 0.14,  # Stock Final
        available_width * 0.16,  # Valeur
        available_width * 0.16,  # Dettes
    ]

    # Create table
    table = Table(table_data, colWidths=col_widths)

    # Table styling
    table_style = TableStyle([
        # Header styling
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#5e72e4')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('TOPPADDING', (0, 0), (-1, 0), 10),

        # Body styling
        ('FONTNAME', (0, 1), (-1, -2), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -2), 9),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),  # Network names left-aligned
        ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),  # Numbers right-aligned
        ('BOTTOMPADDING', (0, 1), (-1, -2), 8),
        ('TOPPADDING', (0, 1), (-1, -2), 8),

        # Totals row styling
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#5e72e4')),
        ('TEXTCOLOR', (0, -1), (-1, -1), colors.white),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, -1), (-1, -1), 10),
        ('BOTTOMPADDING', (0, -1), (-1, -1), 10),
        ('TOPPADDING', (0, -1), (-1, -1), 10),

        # Alternating row colors
        ('ROWBACKGROUNDS', (0, 1), (-1, -2),
         [colors.white, colors.HexColor('#f8f9fe')]),

        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),

        # First column bold
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
    ])

    table.setStyle(table_style)
    story.append(table)

    # === SUMMARY + FOOTER — kept together so footer never orphans on page 2 ===
    summary_data = [
        ['Stock Vendu Calculé:', format_number(grand_totals.get(
            'total_calculated_sold_stock', 0)) + ' unités'],
        ['Total Dettes:', format_number(
            grand_totals.get('total_debts', 0)) + ' FC'],
        ['Valeur Virtuelle Totale:', format_number(
            grand_totals.get('virtual_value', 0)) + ' FC'],
    ]

    summary_table = Table(summary_data, colWidths=[
                          available_width * 0.3, available_width * 0.3])
    summary_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
    ]))

    generated_at = datetime.now().strftime("%d/%m/%Y à %H:%M")

    closing_block = KeepTogether([
        Spacer(1, 10),
        Paragraph("Résumé", section_style),
        summary_table,
        Spacer(1, 12),
        HRFlowable(
            width="100%",
            thickness=0.5,
            color=colors.HexColor('#e9ecef'),
            spaceBefore=4,
            spaceAfter=6,
        ),
        Paragraph(
            f"Rapport généré le {generated_at} • Faida App",
            footer_style,
        ),
    ])
    story.append(closing_block)

    # Build PDF
    doc.build(story)

    # Reset buffer position
    buffer.seek(0)

    return buffer


# ============================================================
# ALTERNATIVE: Simple Text-based PDF (lighter weight)
# ============================================================

def generate_simple_report_pdf(
    report_data: dict,
    grand_totals: dict,
    selected_date: str,
    business_name: str = "Mon Entreprise"
) -> BytesIO:
    """
    Generate a simpler PDF using basic reportlab canvas.
    Lighter weight, fewer dependencies.
    """
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4, landscape

    buffer = BytesIO()
    width, height = landscape(A4)
    c = canvas.Canvas(buffer, pagesize=landscape(A4))

    # Title
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(width/2, height - 40, business_name)

    c.setFont("Helvetica", 12)
    c.drawCentredString(width/2, height - 60,
                        f"Rapport Journalier - {selected_date}")

    # Line
    c.setStrokeColor(colors.grey)
    c.line(50, height - 80, width - 50, height - 80)

    # Table header
    y = height - 120
    headers = ['Réseau', 'Initial', 'Acheté',
               'Vendu', 'Final', 'Valeur', 'Dettes']
    x_positions = [60, 160, 260, 360, 460, 560, 680]

    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(colors.HexColor('#5e72e4'))
    for i, header in enumerate(headers):
        c.drawString(x_positions[i], y, header)

    # Table rows
    y -= 25
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 9)

    for network_name, data in report_data.items():
        row_data = [
            network_name.upper(),
            format_number(data.get('initial_stock', 0)),
            format_number(data.get('purchased_stock', 0)),
            format_number(data.get('sold_stock', 0)),
            format_number(data.get('final_stock', 0)),
            format_number(data.get('virtual_value', 0)),
            format_number(data.get('debt_amount', 0)),
        ]
        for i, val in enumerate(row_data):
            c.drawString(x_positions[i], y, str(val))
        y -= 20

    # Totals
    y -= 10
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(colors.HexColor('#5e72e4'))
    totals = [
        'TOTAL',
        format_number(grand_totals.get('initial_stock', 0)),
        format_number(grand_totals.get('purchased_stock', 0)),
        format_number(grand_totals.get('sold_stock', 0)),
        format_number(grand_totals.get('final_stock', 0)),
        format_number(grand_totals.get('virtual_value', 0)),
        format_number(grand_totals.get('total_debts', 0)),
    ]
    for i, val in enumerate(totals):
        c.drawString(x_positions[i], y, str(val))

    # Footer
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.grey)
    generated_at = datetime.now().strftime("%d/%m/%Y à %H:%M")
    c.drawCentredString(width/2, 30, f"Généré le {generated_at} • Faida App")

    c.save()
    buffer.seek(0)
    return buffer
