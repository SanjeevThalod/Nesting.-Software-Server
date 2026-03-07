"""
PDF Report Generator - Creates Nest Overview and Utilisation reports
Similar to professional nesting software output (e.g. MINDA format)
"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional


# Steel density kg/m³ (default if not specified)
STEEL_DENSITY = 7850.0


def _part_weight_kg(area_mm2: float, thickness_mm: float, density_kg_m3: float) -> float:
    """Calculate part weight: area (mm²) * thickness (mm) * density (kg/m³) / 1e9"""
    if thickness_mm <= 0 or density_kg_m3 <= 0:
        return 0.0
    return (area_mm2 * thickness_mm * density_kg_m3) / 1e9


def generate_nest_overview_report(
    output_path: str,
    project_name: str,
    sheets: List[Dict[str, Any]],
    material_spec: str = "",
    material_thickness_mm: float = 0,
    material_density: float = STEEL_DENSITY,
) -> str:
    """
    Generate Nest Overview Report PDF (detailed per-sheet breakdown).
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=16,
        alignment=TA_CENTER,
        spaceAfter=12,
    )
    heading_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontSize=11,
        spaceAfter=6,
    )
    body_style = styles["Normal"]

    story = []
    date_str = datetime.now().strftime("%d-%m-%Y")

    # Title
    story.append(Paragraph("Nest Overview Report", title_style))
    story.append(Spacer(1, 6))

    # Plan information
    total_nests = len(sheets)
    total_parts = sum(s.get("shapesCount", 0) for s in sheets)
    story.append(Paragraph("Plan information", heading_style))
    plan_data = [
        ["Date", date_str],
        ["Project Name", project_name],
        ["Number of nests", str(total_nests)],
        ["Number of sheets", str(total_nests)],
    ]
    if material_spec:
        plan_data.append(["Material", material_spec])
    story.append(Table(plan_data, colWidths=[120, 200]))
    story.append(Spacer(1, 12))

    for sheet_idx, sheet in enumerate(sheets):
        sheet_num = sheet.get("sheetNumber", sheet_idx + 1)
        sheet_width = sheet.get("sheetWidth", 0)
        sheet_height = sheet.get("sheetHeight", 0)
        utilization = sheet.get("utilization", 0)
        nested_shapes = sheet.get("nestedShapes", [])

        # Production statistics (with weights if material params provided)
        sheet_area_mm2 = sheet_width * sheet_height
        parts_area_mm2 = sum(
            ns.get("width", 0) * ns.get("height", 0) for ns in nested_shapes
        )
        scrap_area_mm2 = sheet_area_mm2 - parts_area_mm2

        if material_thickness_mm > 0 and material_density > 0:
            sheet_wt = _part_weight_kg(sheet_area_mm2, material_thickness_mm, material_density)
            parts_wt = _part_weight_kg(parts_area_mm2, material_thickness_mm, material_density)
            scrap_wt = _part_weight_kg(scrap_area_mm2, material_thickness_mm, material_density)
            wt_sheet = f"{sheet_wt:.2f} kg"
            wt_parts = f"{parts_wt:.2f} kg"
            wt_scrap = f"{scrap_wt:.2f} kg"
        else:
            wt_sheet = wt_parts = wt_scrap = "N/A"

        if material_spec:
            story.append(Paragraph(material_spec, body_style))
        story.append(Paragraph("Production Statistics", heading_style))
        prod_data = [
            ["Total wt. of Sheets", wt_sheet],
            ["Total wt. of Parts", wt_parts],
            ["Total wt. of Scrap", wt_scrap],
        ]
        story.append(Table(prod_data, colWidths=[150, 100]))
        story.append(Spacer(1, 6))

        # Plate information
        story.append(Paragraph("Plate information", heading_style))
        plate_data = [
            ["Nest Name", f"Sheet {sheet_num} - {project_name}"],
            ["Sheet Size", f"{sheet_width:.0f} X {sheet_height:.0f} MM"],
            ["Sheet Quantity", "1 Sheet"],
            ["Utilization", f"{utilization:.1f} %"],
        ]
        story.append(Table(plate_data, colWidths=[120, 200]))
        story.append(Spacer(1, 6))

        # Part details table
        story.append(Paragraph("Part Details", heading_style))
        col_widths = [50, 80, 60, 55, 55, 45, 55, 50, 50]
        table_data = [
            [
                "Part #",
                "Part Name",
                "Drawing No.",
                "Length",
                "Width",
                "Per Sheet",
                "Part Wt.",
                "Part X",
                "Part Y",
            ]
        ]

        for idx, ns in enumerate(nested_shapes):
            shape = ns.get("original_shape", {})
            part_name = shape.get("shape_id", f"Part_{idx + 1}")
            drawing_no = shape.get("shape_id", "-")
            length = ns.get("width", 0)
            width = ns.get("height", 0)
            x = ns.get("x", 0)
            y = ns.get("y", 0)
            rotation = ns.get("rotation", 0)

            area_mm2 = length * width
            if material_thickness_mm > 0 and material_density > 0:
                part_wt = _part_weight_kg(area_mm2, material_thickness_mm, material_density)
                wt_str = f"{part_wt:.2f}"
            else:
                wt_str = "-"

            table_data.append(
                [
                    str(idx + 1),
                    part_name,
                    drawing_no,
                    f"{length:.0f}",
                    f"{width:.0f}",
                    "1",
                    wt_str,
                    f"{x:.2f}",
                    f"{y:.2f}",
                ]
            )

        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4472C4")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 8),
                    ("FONTSIZE", (0, 1), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                    ("TOPPADDING", (0, 0), (-1, 0), 8),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 8))

        # Pagination
        story.append(
            Paragraph(
                f"-- {sheet_idx + 1} of {total_nests} --",
                ParagraphStyle("PageNum", alignment=TA_CENTER, fontSize=9),
            )
        )

        if sheet_idx < total_nests - 1:
            story.append(PageBreak())

    doc.build(story)
    return output_path


def generate_utilisation_report(
    output_path: str,
    project_name: str,
    sheets: List[Dict[str, Any]],
    material_spec: str = "",
    material_thickness_mm: float = 0,
    material_density: float = STEEL_DENSITY,
) -> str:
    """
    Generate Utilisation Report PDF (summary of all sheets).
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=16,
        alignment=TA_CENTER,
        spaceAfter=12,
    )
    heading_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontSize=11,
        spaceAfter=6,
    )

    story = []
    date_str = datetime.now().strftime("%d-%m-%Y")

    story.append(Paragraph("Utilisation Report", title_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"Date {date_str}", styles["Normal"]))
    story.append(Paragraph(f"Project Name: {project_name}", styles["Normal"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Utilisation Summary", heading_style))

    col_widths = [80, 90, 60, 70, 70, 70, 70, 70]
    table_data = [
        [
            "Nest",
            "Sheet Size",
            "Sheet Qty",
            "Sheets Wt.",
            "Parts Wt.",
            "Scrap Wt.",
            "Utilisation",
            "Scrap/sheet",
        ]
    ]

    total_sheets_wt = 0.0
    total_parts_wt = 0.0
    total_scrap_wt = 0.0
    utilizations = []

    for sheet in sheets:
        sheet_num = sheet.get("sheetNumber", 0)
        sheet_width = sheet.get("sheetWidth", 0)
        sheet_height = sheet.get("sheetHeight", 0)
        utilization = sheet.get("utilization", 0)
        nested_shapes = sheet.get("nestedShapes", [])

        sheet_area_mm2 = sheet_width * sheet_height
        parts_area_mm2 = sum(
            ns.get("width", 0) * ns.get("height", 0) for ns in nested_shapes
        )
        scrap_area_mm2 = max(0, sheet_area_mm2 - parts_area_mm2)

        if material_thickness_mm > 0 and material_density > 0:
            sheet_wt = _part_weight_kg(sheet_area_mm2, material_thickness_mm, material_density)
            parts_wt = _part_weight_kg(parts_area_mm2, material_thickness_mm, material_density)
            scrap_wt = _part_weight_kg(scrap_area_mm2, material_thickness_mm, material_density)
            total_sheets_wt += sheet_wt
            total_parts_wt += parts_wt
            total_scrap_wt += scrap_wt
            wt_sheet_str = f"{sheet_wt:.2f} kg"
            wt_parts_str = f"{parts_wt:.2f} kg"
            wt_scrap_str = f"{scrap_wt:.2f} kg"
        else:
            wt_sheet_str = wt_parts_str = wt_scrap_str = "-"

        utilizations.append(utilization)
        scrap_pct = (100 - utilization) if utilization > 0 else 0

        table_data.append(
            [
                f"Sheet {sheet_num}",
                f"{sheet_width:.0f} X {sheet_height:.0f}mm",
                "1",
                wt_sheet_str,
                wt_parts_str,
                wt_scrap_str,
                f"{utilization:.2f}%",
                f"{scrap_pct:.2f}%",
            ]
        )

    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4472C4")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 12))

    avg_util = sum(utilizations) / len(utilizations) if utilizations else 0
    story.append(
        Paragraph(f"Average Utilisation: {avg_util:.2f}%", styles["Normal"])
    )
    if material_thickness_mm > 0 and material_density > 0:
        story.append(
            Paragraph(
                f"Total Sheets Wt.: {total_sheets_wt:.2f} kg  |  "
                f"Total Parts Wt.: {total_parts_wt:.2f} kg  |  "
                f"Total Scrap Wt.: {total_scrap_wt:.2f} kg",
                styles["Normal"],
            )
        )

    story.append(Spacer(1, 8))
    story.append(
        Paragraph("-- 1 of 1 --", ParagraphStyle("PageNum", alignment=TA_CENTER, fontSize=9))
    )

    doc.build(story)
    return output_path


def generate_all_reports(
    output_dir: Path,
    project_name: str,
    sheets: List[Dict[str, Any]],
    material_spec: str = "",
    material_thickness_mm: float = 0,
    material_density: float = STEEL_DENSITY,
) -> List[tuple]:
    """
    Generate both Nest Overview and Utilisation reports.
    Returns list of (file_path, arc_name) for ZIP inclusion.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in project_name)

    overview_path = output_dir / f"{safe_name}_Nest_Overview.pdf"
    utilisation_path = output_dir / f"{safe_name}_Utilisation_Report.pdf"

    generate_nest_overview_report(
        str(overview_path),
        project_name=project_name,
        sheets=sheets,
        material_spec=material_spec,
        material_thickness_mm=material_thickness_mm,
        material_density=material_density,
    )
    generate_utilisation_report(
        str(utilisation_path),
        project_name=project_name,
        sheets=sheets,
        material_spec=material_spec,
        material_thickness_mm=material_thickness_mm,
        material_density=material_density,
    )

    return [
        (overview_path, overview_path.name),
        (utilisation_path, utilisation_path.name),
    ]
