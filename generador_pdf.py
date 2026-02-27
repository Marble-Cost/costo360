# generador_pdf.py — CostoMarmol v5.1 · AIU Support

import io
from datetime import date
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Image, KeepTogether,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from calculos import cop

_DEFAULT_PALETTE = {
    "primary":   "#0D2137", "secondary": "#1B5FA8", "accent":    "#C9A84C",
    "light":     "#D6E8FA", "ultralight":"#EEF5FD", "gray":      "#6B85A0",
    "text":      "#0D2137", "white":     "#FFFFFF",
}

def _extraer_paleta_logo(logo_bytes: bytes | None) -> dict:
    return _DEFAULT_PALETTE.copy()

def _colores(palette: dict):
    return {k: colors.HexColor(v) for k, v in palette.items()}

def _num(valor: float) -> str:
    return f"${int(round(valor)):,}".replace(",", ".")

def _fecha_es():
    f = date.today()
    meses = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"]
    return f"{f.day} de {meses[f.month-1]} de {f.year}"

def _estilos(P):
    b13 = dict(leading=13)
    b11 = dict(leading=11)
    return {
        "titulo":   ParagraphStyle("titulo",   **b13, fontSize=18, fontName="Helvetica-Bold",  textColor=P["white"]),
        "subtit":   ParagraphStyle("subtit",   **b11, fontSize=8,  fontName="Helvetica",       textColor=colors.HexColor("#B8D4F0"), alignment=TA_LEFT),
        "empresa":  ParagraphStyle("empresa",  **b11, fontSize=8,  fontName="Helvetica",       textColor=P["white"],    alignment=TA_RIGHT),
        "seccion":  ParagraphStyle("seccion",  **b11, fontSize=7,  fontName="Helvetica-Bold",  textColor=P["gray"],     letterSpacing=1.2),
        "normal":   ParagraphStyle("normal",   **b13, fontSize=8.5,fontName="Helvetica",       textColor=P["text"]),
        "bold":     ParagraphStyle("bold",     **b13, fontSize=8.5,fontName="Helvetica-Bold",  textColor=P["text"]),
        "footer":   ParagraphStyle("footer",   **b11, fontSize=7,  fontName="Helvetica",       textColor=P["gray"],     alignment=TA_CENTER),
        "aviso":    ParagraphStyle("aviso",     leading=10, fontSize=7,  fontName="Helvetica", textColor=P["gray"]),
        "accent_s": ParagraphStyle("accent_s", **b11, fontSize=7.5,fontName="Helvetica-Bold",  textColor=P["accent"]),
        "white_s":  ParagraphStyle("white_s",  **b11, fontSize=8,  fontName="Helvetica",       textColor=P["white"]),
        "price":    ParagraphStyle("price",    leading=28, fontSize=22, fontName="Helvetica-Bold", textColor=P["white"]),
    }

def _logo_img(logo_bytes: bytes | None, max_h: float = 1.5*cm) -> Image | None:
    if not logo_bytes: return None
    try:
        buf = io.BytesIO(logo_bytes)
        img = Image(buf)
        ratio = img.imageWidth / img.imageHeight
        img.drawWidth  = max_h * ratio
        img.drawHeight = max_h
        return img
    except Exception: return None

def _header_bloque(E, P, doc_type, numero, fecha_str, empresa_info, logo_bytes):
    emp = empresa_info or {}
    nombre_emp = emp.get("nombre", "MARMOLES COLLANTE & CASTRO LTDA.")
    logo_img = _logo_img(logo_bytes, max_h=1.4*cm)
    col_izq = []
    if logo_img:
        col_izq.append(logo_img)
        col_izq.append(Spacer(1, 4))
    col_izq.append(Paragraph(nombre_emp, ParagraphStyle("ne", leading=12, fontSize=9, fontName="Helvetica-Bold", textColor=P["white"])))
    col_izq.append(Paragraph(emp.get("nit", ""), E["white_s"]))
    col_izq.append(Paragraph(emp.get("ciudad", "Barranquilla, Colombia"), E["white_s"]))
    col_izq.append(Paragraph(emp.get("tel", ""), E["white_s"]))
    
    col_der = [
        Paragraph(doc_type, E["accent_s"]), Spacer(1, 3),
        Paragraph(f"<b>{numero}</b>", ParagraphStyle("num", leading=18, fontSize=13, fontName="Helvetica-Bold", textColor=P["white"], alignment=TA_RIGHT)),
        Spacer(1, 4),
        Paragraph(fecha_str, ParagraphStyle("fch", leading=11, fontSize=8, fontName="Helvetica", textColor=colors.HexColor("#B8D4F0"), alignment=TA_RIGHT)),
        Paragraph(emp.get("email", ""), ParagraphStyle("eml", leading=10, fontSize=7, fontName="Helvetica", textColor=colors.HexColor("#B8D4F0"), alignment=TA_RIGHT)),
    ]
    tbl = Table([[col_izq, col_der]], colWidths=[10*cm, 7*cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,-1), P["primary"]),
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
        ("TOPPADDING",   (0,0), (-1,-1), 14), ("BOTTOMPADDING",(0,0), (-1,-1), 14),
        ("LEFTPADDING",  (0,0), (0, -1), 16), ("RIGHTPADDING", (-1,0),(-1,-1), 16),
    ]))
    return tbl

def _tabla_2col(E, P, filas_datos, bg_header=None):
    filas = []
    for label, valor in filas_datos:
        filas.append([Paragraph(label, E["normal"]), Paragraph(f"<b>{valor}</b>", E["bold"])])
    tbl = Table(filas, colWidths=[6*cm, 11*cm])
    tbl.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [P["white"], P["ultralight"]]),
        ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 10), ("LINEBELOW", (0,0), (-1,-1), 0.3, P["light"]),
    ]))
    return tbl

def _tabla_desglose(E, P, r):
    # Detección Inteligente: Si es AIU o Cotización Directa
    if r.get("tipo_proyecto") == "Licitación AIU":
        items = [
            ("Costo Directo del Proyecto", r.get("cd", 0)),
            (f"Administración ({r.get('pct_a', 2)}%)", r.get("val_a", 0)),
            (f"Imprevistos ({r.get('pct_i', 2)}%)", r.get("val_i", 0)),
            (f"Utilidad ({r.get('pct_u', 5)}%)", r.get("val_u", 0)),
            ("IVA exclusivo sobre la Utilidad (19%)", r.get("val_iva", 0)),
            ("Gastos Logísticos (Transporte)", r.get("logistica", 0)),
        ]
        total_label = "PRECIO TOTAL DEL CONTRATO"
        total_val = r.get("precio_sugerido", 0)
    else:
        items = [
            ("Material (area comprada x precio/m2)", r.get("c1_material", 0)),
            ("Mano de obra (corte + elaboracion)", r.get("c2_mano_obra", 0)),
            ("Zocalos", r.get("c3_zocalos", 0)),
            ("Insumos (disco + desgaste maquinaria)", r.get("c4_insumos", 0)),
            ("Logistica (transporte + peajes)", r.get("c5_logistica", 0)),
            ("Viaticos foraneos", r.get("c6_viaticos", 0)),
            ("Costos adicionales en obra", r.get("c7_adicionales", 0)),
        ]
        total_label = "COSTO DIRECTO TOTAL"
        total_val = r.get("costo_total", 0)

    items = [(c, v) for c, v in items if v > 0]
    header_style = ParagraphStyle("dh", leading=11, fontSize=7, fontName="Helvetica-Bold", textColor=P["gray"], letterSpacing=1)
    filas = [[ Paragraph("CONCEPTO", header_style), Paragraph("VALOR (COP)", ParagraphStyle("dhv", leading=11, fontSize=7, fontName="Helvetica-Bold", textColor=P["gray"], alignment=TA_RIGHT)), ]]
    for concepto, valor in items:
        filas.append([ Paragraph(concepto, ParagraphStyle("dc", leading=11, fontSize=8.5, fontName="Helvetica", textColor=P["text"])), Paragraph(_num(valor), ParagraphStyle("dv", leading=11, fontSize=8.5, fontName="Helvetica", textColor=P["text"], alignment=TA_RIGHT)), ])
    filas.append([ Paragraph(total_label, ParagraphStyle("dct", leading=12, fontSize=9, fontName="Helvetica-Bold", textColor=P["primary"])), Paragraph(_num(total_val), ParagraphStyle("dcv", leading=12, fontSize=10, fontName="Helvetica-Bold", textColor=P["primary"], alignment=TA_RIGHT)), ])
    
    tbl = Table(filas, colWidths=[12.5*cm, 4.5*cm])
    estilo = [
        ("LINEBELOW", (0,0), (-1,-1), 0.3, P["light"]),
        ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LINEBELOW", (0,0), (-1,0), 1, P["secondary"]),
        ("LINEBELOW", (0,-1), (-1,-1), 1.5, P["primary"]),
    ]
    tbl.setStyle(TableStyle(estilo))
    return tbl

def generar_pdf_cotizacion(resultado: dict, numero: str = "COT-001", empresa_info: dict = None, logo_bytes: bytes = None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, rightMargin=2*cm, leftMargin=2*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)
    P = _colores(_extraer_paleta_logo(logo_bytes))
    E = _estilos(P)
    story = []
    story.append(_header_bloque(E, P, "COTIZACIÓN", numero, _fecha_es(), empresa_info, logo_bytes))
    story.append(Spacer(1, 15))
    story.append(Paragraph("DATOS DEL CLIENTE", E["seccion"]))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1, color=P["light"], spaceBefore=0, spaceAfter=8))
    story.append(_tabla_2col(E, P, [("Nombre / Razon Social:", resultado.get("nombre_cliente", "CLIENTE GENERAL"))]))
    story.append(Spacer(1, 15))
    story.append(Paragraph("DETALLE DEL PROYECTO", E["seccion"]))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1, color=P["light"], spaceBefore=0, spaceAfter=8))
    
    if resultado.get("tipo_proyecto") == "Licitación AIU":
        datos_proy = [("Tipo de Servicio:", "Licitación / Obra Comercial")]
    else:
        datos_proy = [
            ("Material:", f"{resultado.get('categoria','')} — {resultado.get('referencia','')}"),
            ("Tipo de superficie:", resultado.get("tipo_proyecto","")),
            ("Metros lineales:", f"{resultado.get('ml_proyecto',0):.1f} ml"),
        ]
    story.append(_tabla_2col(E, P, datos_proy))
    story.append(Spacer(1, 15))
    story.append(Paragraph("DESGLOSE COMERCIAL", E["seccion"]))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1, color=P["light"], spaceBefore=0, spaceAfter=4))
    story.append(_tabla_desglose(E, P, resultado))
    story.append(Spacer(1, 15))
    
    bloque_precio = Table([
        [Paragraph("PRECIO SUGERIDO", ParagraphStyle("ps", leading=11, fontSize=8, fontName="Helvetica-Bold", textColor=P["secondary"], alignment=TA_RIGHT))],
        [Paragraph(_num(resultado.get('precio_sugerido',0)), E["price"])]
    ], colWidths=[17*cm])
    bloque_precio.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), P["primary"]),
        ("TOPPADDING", (0,0), (-1,-1), 16), ("BOTTOMPADDING", (0,0), (-1,-1), 16),
        ("RIGHTPADDING", (0,0), (-1,-1), 24),
    ]))
    story.append(KeepTogether(bloque_precio))
    story.append(Spacer(1, 20))
    story.append(Paragraph("CONDICIONES COMERCIALES", E["seccion"]))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1, color=P["light"], spaceBefore=0, spaceAfter=8))
    story.append(Paragraph("1. Validez de esta cotizacion: 15 dias calendario.<br/>2. Forma de pago: 60% anticipo, 40% a la entrega.<br/>3. Tiempos de entrega sujetos a disponibilidad de agenda.", E["normal"]))
    doc.build(story)
    return buf.getvalue()

def generar_cuenta_cobro(resultado: dict, datos_prestador: dict, datos_pagador: dict, numero: str = "CC-001", logo_bytes: bytes = None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, rightMargin=2*cm, leftMargin=2*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)
    P = _colores(_extraer_paleta_logo(logo_bytes))
    E = _estilos(P)
    story = []
    story.append(_header_bloque(E, P, "CUENTA DE COBRO", numero, _fecha_es(), datos_prestador, logo_bytes))
    story.append(Spacer(1, 30))
    story.append(Paragraph(f"<b>DEBE A:</b>", E["normal"]))
    story.append(Paragraph(f"{datos_prestador.get('nombre', '')}", E["bold"]))
    story.append(Paragraph(f"NIT: {datos_prestador.get('nit', '')}", E["normal"]))
    story.append(Spacer(1, 15))
    story.append(Paragraph(f"<b>A CARGO DE:</b>", E["normal"]))
    story.append(Paragraph(f"{datos_pagador.get('nombre', '')}", E["bold"]))
    story.append(Paragraph(f"NIT / CC: {datos_pagador.get('nit', '')}", E["normal"]))
    story.append(Paragraph(f"Dirección: {datos_pagador.get('direccion', '')}", E["normal"]))
    story.append(Spacer(1, 30))
    
    precio_total = resultado.get("precio_sugerido", 0)
    concepto = "Por concepto de suministro, elaboración e instalación de acabados en piedra natural/sintética, "
    concepto += "según alcance detallado en la cotización comercial correspondiente." if resultado.get("tipo_proyecto") == "Licitación AIU" else f"correspondiente al proyecto de {resultado.get('tipo_proyecto','')} en {resultado.get('categoria','')}."

    story.append(Paragraph("POR CONCEPTO DE:", E["seccion"]))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1, color=P["light"], spaceBefore=0, spaceAfter=8))
    story.append(Paragraph(concepto, E["normal"]))
    story.append(Spacer(1, 25))
    
    val_tbl = Table([
        [Paragraph("VALOR TOTAL:", ParagraphStyle("vth", leading=11, fontSize=10, fontName="Helvetica-Bold", textColor=P["secondary"])),
         Paragraph(_num(precio_total), ParagraphStyle("vtv", leading=11, fontSize=14, fontName="Helvetica-Bold", textColor=P["primary"], alignment=TA_RIGHT))]
    ], colWidths=[8.5*cm, 8.5*cm])
    val_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), P["ultralight"]),
        ("TOPPADDING", (0,0), (-1,-1), 12), ("BOTTOMPADDING", (0,0), (-1,-1), 12),
        ("LEFTPADDING", (0,0), (0,0), 16), ("RIGHTPADDING", (1,0), (1,0), 16),
        ("LINEABOVE", (0,0), (-1,0), 1.5, P["primary"]),
        ("LINEBELOW", (0,0), (-1,-1), 1.5, P["primary"]),
    ]))
    story.append(val_tbl)
    story.append(Spacer(1, 30))
    story.append(Paragraph("INFORMACIÓN PARA PAGOS:", E["seccion"]))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1, color=P["light"], spaceBefore=0, spaceAfter=8))
    story.append(Paragraph(f"<b>Banco:</b> {datos_prestador.get('banco', '')}", E["normal"]))
    story.append(Paragraph(f"<b>Tipo de cuenta:</b> {datos_prestador.get('cuenta_tipo', '')}", E["normal"]))
    story.append(Paragraph(f"<b>Número:</b> {datos_prestador.get('cuenta_numero', '')}", E["normal"]))
    story.append(Paragraph(f"<b>A nombre de:</b> {datos_prestador.get('nombre', '')}", E["normal"]))
    doc.build(story)
    return buf.getvalue()
