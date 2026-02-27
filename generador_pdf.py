# generador_pdf.py — CostoMarmol v5
# PDF 1 pagina fija · paleta extraida del logo del usuario · mismo diseno cot y cuenta cobro

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

# ── Paleta por defecto (azul marino corporativo) ─────────────────────────────
_DEFAULT_PALETTE = {
    "primary":   "#0D2137",
    "secondary": "#1B5FA8",
    "accent":    "#C9A84C",
    "light":     "#D6E8FA",
    "ultralight":"#EEF5FD",
    "gray":      "#6B85A0",
    "text":      "#0D2137",
    "white":     "#FFFFFF",
}


def _extraer_paleta_logo(logo_bytes: bytes | None) -> dict:
    """
    Extrae la paleta dominante del logo usando PIL.
    Retorna dict con primary, secondary, accent, light, ultralight, gray, text, white.
    Si no hay logo o falla, retorna la paleta por defecto.
    """
    if not logo_bytes:
        return _DEFAULT_PALETTE.copy()
    try:
        from PIL import Image as PILImage
        import io as _io
        img = PILImage.open(_io.BytesIO(logo_bytes)).convert("RGB")
        img.thumbnail((100, 100))
        pixels = list(img.getdata())
        # Filtrar pixeles muy claros (fondo blanco) y muy oscuros
        filtered = [
            p for p in pixels
            if not (p[0] > 230 and p[1] > 230 and p[2] > 230)  # no blanco
            and not (p[0] < 15 and p[1] < 15 and p[2] < 15)    # no negro puro
        ]
        if len(filtered) < 50:
            return _DEFAULT_PALETTE.copy()

        # Calcular color dominante (promedio ponderado por saturacion)
        def saturation(r, g, b):
            mx, mn = max(r,g,b)/255, min(r,g,b)/255
            return (mx - mn) / mx if mx > 0 else 0

        # Ordenar por saturacion y tomar los mas saturados
        saturated = sorted(filtered, key=lambda p: saturation(*p), reverse=True)
        top = saturated[:max(len(saturated)//4, 1)]
        avg_r = int(sum(p[0] for p in top) / len(top))
        avg_g = int(sum(p[1] for p in top) / len(top))
        avg_b = int(sum(p[2] for p in top) / len(top))

        # Color primario: version oscura del dominante
        def darken(r, g, b, factor=0.55):
            return (int(r*factor), int(g*factor), int(b*factor))
        def lighten(r, g, b, factor=0.88):
            return (
                min(255, int(r + (255-r)*factor)),
                min(255, int(g + (255-g)*factor)),
                min(255, int(b + (255-b)*factor)),
            )
        def to_hex(r, g, b):
            return f"#{r:02X}{g:02X}{b:02X}"

        pr = darken(avg_r, avg_g, avg_b, 0.45)
        sec = (int(avg_r*0.7), int(avg_g*0.7), int(avg_b*0.7))
        lt  = lighten(avg_r, avg_g, avg_b, 0.82)
        ult = lighten(avg_r, avg_g, avg_b, 0.92)

        # Acento dorado si el dominante es azul/frio; sino usar complementario
        is_cool = avg_b > avg_r and avg_b > avg_g
        accent = "#C9A84C" if is_cool else to_hex(
            min(255, int(avg_b*0.8 + 100)),
            min(255, int(avg_g*0.6 + 80)),
            min(255, int(avg_r*0.3))
        )

        return {
            "primary":    to_hex(*pr),
            "secondary":  to_hex(*sec),
            "accent":     accent,
            "light":      to_hex(*lt),
            "ultralight": to_hex(*ult),
            "gray":       "#6B85A0",
            "text":       to_hex(*pr),
            "white":      "#FFFFFF",
        }
    except Exception:
        return _DEFAULT_PALETTE.copy()


def _colores(palette: dict):
    """Convierte dict de paleta a objetos HexColor de reportlab."""
    return {k: colors.HexColor(v) for k, v in palette.items()}


def _num(valor: float) -> str:
    return f"${int(round(valor)):,}".replace(",", ".")


def _fecha_es():
    f = date.today()
    meses = ["enero","febrero","marzo","abril","mayo","junio",
             "julio","agosto","septiembre","octubre","noviembre","diciembre"]
    return f"{f.day} de {meses[f.month-1]} de {f.year}"


def _estilos(P):
    """Crea estilos usando la paleta P (dict de HexColor)."""
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
    if not logo_bytes:
        return None
    try:
        buf = io.BytesIO(logo_bytes)
        img = Image(buf)
        ratio = img.imageWidth / img.imageHeight
        img.drawWidth  = max_h * ratio
        img.drawHeight = max_h
        return img
    except Exception:
        return None


def _header_bloque(E, P, doc_type, numero, fecha_str, empresa_info, logo_bytes):
    """
    Encabezado idéntico para cotización y cuenta de cobro. Solo cambia el título.

    CORRECCIÓN: Solo extrae y muestra nombre, nit, ciudad, tel y email.
    El número de cuenta bancaria NO debe aparecer aquí — solo en la sección
    "DATOS PARA PAGO" de la cuenta de cobro.
    """
    emp = empresa_info or {}
    nombre_emp = emp.get("nombre", "MARMOLES COLLANTE & CASTRO LTDA.")

    logo_img = _logo_img(logo_bytes, max_h=1.4*cm)

    # Columna izquierda: logo + nombre empresa + NIT + ciudad + teléfono
    # IMPORTANTE: NO incluir cuenta_numero ni cuenta_tipo aquí
    col_izq = []
    if logo_img:
        col_izq.append(logo_img)
        col_izq.append(Spacer(1, 4))
    col_izq.append(Paragraph(nombre_emp, ParagraphStyle("ne", leading=12, fontSize=9, fontName="Helvetica-Bold", textColor=P["white"])))
    if emp.get("nit"):
        col_izq.append(Paragraph(emp["nit"], E["white_s"]))
    if emp.get("ciudad"):
        col_izq.append(Paragraph(emp["ciudad"], E["white_s"]))
    if emp.get("tel"):
        col_izq.append(Paragraph(emp["tel"], E["white_s"]))

    # Columna derecha: tipo doc + numero + fecha
    col_der = [
        Paragraph(doc_type, E["accent_s"]),
        Spacer(1, 3),
        Paragraph(f"<b>{numero}</b>", ParagraphStyle("num", leading=18, fontSize=13, fontName="Helvetica-Bold", textColor=P["white"], alignment=TA_RIGHT)),
        Spacer(1, 4),
        Paragraph(fecha_str, ParagraphStyle("fch", leading=11, fontSize=8, fontName="Helvetica", textColor=colors.HexColor("#B8D4F0"), alignment=TA_RIGHT)),
        Paragraph(emp.get("email", ""), ParagraphStyle("eml", leading=10, fontSize=7, fontName="Helvetica", textColor=colors.HexColor("#B8D4F0"), alignment=TA_RIGHT)),
    ]

    tbl = Table([[col_izq, col_der]], colWidths=[10*cm, 7*cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,-1), P["primary"]),
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
        ("TOPPADDING",   (0,0), (-1,-1), 14),
        ("BOTTOMPADDING",(0,0), (-1,-1), 14),
        ("LEFTPADDING",  (0,0), (0, -1), 16),
        ("RIGHTPADDING", (-1,0),(-1,-1), 16),
    ]))
    return tbl


def _tabla_2col(E, P, filas_datos, bg_header=None):
    """Tabla de 2 columnas label/valor con diseño consistente."""
    filas = []
    for label, valor in filas_datos:
        filas.append([Paragraph(label, E["normal"]), Paragraph(f"<b>{valor}</b>", E["bold"])])
    tbl = Table(filas, colWidths=[6*cm, 11*cm])
    tbl.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [P["white"], P["ultralight"]]),
        ("TOPPADDING",     (0,0), (-1,-1), 5),
        ("BOTTOMPADDING",  (0,0), (-1,-1), 5),
        ("LEFTPADDING",    (0,0), (-1,-1), 10),
        ("LINEBELOW",      (0,0), (-1,-1), 0.3, P["light"]),
    ]))
    return tbl


def _tabla_desglose(E, P, r, incluir_iva: bool = True):
    """
    Tabla de desglose para el PDF de COTIZACIÓN (cara al cliente).

    REFACTORIZACIÓN — PROTECCIÓN DE MÁRGENES:
    Los costos operativos internos (producción, disco, desgaste de máquina,
    logística detallada, viáticos) se agrupan en máximo 3 ítems comerciales.
    El cliente NO debe ver el desglose de transporte, mano de obra, insumos
    ni márgenes internos. Solo ve conceptos de alto nivel.

    Grupos:
      1. Suministro de material pétreo      → c1_material
      2. Servicios de fabricación e inst.   → c2 + c3 + c4 (producción, zócalos, insumos)
      3. Logística, traslado y gastos en obra → c5 + c6 + c7 (solo si > 0)
    """
    # ── Agrupar costos operativos en 3 conceptos comerciales ─────────────────
    c_material   = r.get("c1_material", 0)
    c_servicios  = (r.get("c2_mano_obra", 0)
                  + r.get("c3_zocalos", 0)
                  + r.get("c4_insumos", 0))
    c_logistica  = (r.get("c5_logistica", 0)
                  + r.get("c6_viaticos", 0)
                  + r.get("c7_adicionales", 0))

    items = [
        ("Suministro de material pétreo",                      c_material),
        ("Servicios de fabricación, elaboración e instalación", c_servicios),
        ("Logística, traslado y gastos en obra",               c_logistica),
    ]
    # Omitir ítems con valor cero para no mostrar líneas vacías
    items = [(c, v) for c, v in items if v > 0]

    utilidad    = r.get("utilidad", 0)
    precio_base = r.get("precio_sugerido", 0)

    if incluir_iva:
        iva         = precio_base * 0.19   # IVA sobre el total de la cotización
        precio_final = precio_base + iva
    else:
        iva         = 0.0
        precio_final = precio_base

    header_style = ParagraphStyle("dh", leading=11, fontSize=7, fontName="Helvetica-Bold",
                                   textColor=P["gray"], letterSpacing=1)
    filas = [[
        Paragraph("CONCEPTO", header_style),
        Paragraph("VALOR (COP)", ParagraphStyle("dhv", leading=11, fontSize=7,
                  fontName="Helvetica-Bold", textColor=P["gray"], alignment=TA_RIGHT)),
    ]]
    for concepto, valor in items:
        filas.append([
            Paragraph(concepto, ParagraphStyle("dc", leading=11, fontSize=8.5,
                      fontName="Helvetica", textColor=P["text"])),
            Paragraph(_num(valor), ParagraphStyle("dv", leading=11, fontSize=8.5,
                      fontName="Helvetica", textColor=P["text"], alignment=TA_RIGHT)),
        ])

    # Subtotal
    filas.append([
        Paragraph("Subtotal" + (" (sin IVA)" if incluir_iva else ""),
                  ParagraphStyle("dct", leading=12, fontSize=9, fontName="Helvetica-Bold",
                                 textColor=P["primary"])),
        Paragraph(_num(precio_base), ParagraphStyle("dcv", leading=12, fontSize=9,
                  fontName="Helvetica-Bold", textColor=P["primary"], alignment=TA_RIGHT)),
    ])

    if incluir_iva:
        # Fila IVA
        filas.append([
            Paragraph("IVA 19% (Impuesto al Valor Agregado)",
                      ParagraphStyle("diva", leading=12, fontSize=9,
                                     fontName="Helvetica", textColor=P["secondary"])),
            Paragraph(_num(iva), ParagraphStyle("divav", leading=12, fontSize=9,
                      fontName="Helvetica", textColor=P["secondary"], alignment=TA_RIGHT)),
        ])
        total_label = "TOTAL DE LA OFERTA (IVA INCLUIDO)"
    else:
        total_label = "TOTAL DE LA OFERTA (SIN IVA)"

    filas.append([
        Paragraph(total_label, ParagraphStyle("dtot", leading=13, fontSize=10,
                  fontName="Helvetica-Bold", textColor=P["white"])),
        Paragraph(_num(precio_final), ParagraphStyle("dtotv", leading=13, fontSize=10,
                  fontName="Helvetica-Bold", textColor=P["white"], alignment=TA_RIGHT)),
    ])

    tbl = Table(filas, colWidths=[12.5*cm, 4.5*cm])

    # Estilos base
    ts = [
        ("BACKGROUND",    (0,0),  (-1,0),  P["light"]),
        ("ROWBACKGROUNDS",(0,1),  (-1,-4), [P["white"], P["ultralight"]]),
        ("BACKGROUND",    (0,-3), (-1,-3), P["light"]),       # Subtotal
        ("BACKGROUND",    (0,-1), (-1,-1), P["primary"]),     # Total
        ("TOPPADDING",    (0,0),  (-1,-1), 5),
        ("BOTTOMPADDING", (0,0),  (-1,-1), 5),
        ("LEFTPADDING",   (0,0),  (-1,-1), 10),
        ("RIGHTPADDING",  (0,0),  (-1,-1), 10),
        ("LINEBELOW",     (0,0),  (-1,-1), 0.3, P["light"]),
        ("LINEABOVE",     (0,-3), (-1,-3), 1.2, P["primary"]),
    ]
    if incluir_iva:
        ts.append(("BACKGROUND", (0,-2), (-1,-2), P["ultralight"]))  # Fila IVA

    tbl.setStyle(TableStyle(ts))
    return tbl, precio_final


def _bloque_precio(E, P, precio, margen, utilidad, label="PRECIO DE VENTA SUGERIDO"):
    tbl = Table([
        [Paragraph(label, ParagraphStyle("pl", leading=10, fontSize=7.5, fontName="Helvetica-Bold", textColor=P["accent"], letterSpacing=1)), ""],
        [Paragraph(_num(precio), E["price"]), ""],
        [Paragraph(f"Margen: {margen:.0f}%   ·   Utilidad: {_num(utilidad)}", E["white_s"]), ""],
    ], colWidths=[14*cm, 3*cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,-1), P["primary"]),
        ("TOPPADDING",   (0,0), (-1,-1), 10),
        ("BOTTOMPADDING",(0,0), (-1,-1), 10),
        ("LEFTPADDING",  (0,0), (-1,-1), 16),
        ("SPAN",         (0,0), (-1,0)),
        ("SPAN",         (0,1), (-1,1)),
        ("SPAN",         (0,2), (-1,2)),
    ]))
    return tbl


def _footer(E, P, emp_nombre, fecha_str):
    return [
        HRFlowable(width="100%", thickness=0.5, color=P["light"]),
        Spacer(1, 4),
        Paragraph(f"{emp_nombre}   ·   {fecha_str}   ·   Barranquilla, Colombia", E["footer"]),
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# COTIZACION — 1 PAGINA FIJA
# ═══════════════════════════════════════════════════════════════════════════════
def generar_pdf_cotizacion(resultado: dict, numero: str = None,
                            empresa_info: dict = None, logo_bytes: bytes = None,
                            incluir_iva: bool = True) -> bytes:
    if numero is None:
        numero = f"COT-{date.today().strftime('%Y%m%d')}-001"
    fecha_str = _fecha_es()
    emp = empresa_info or {}

    palette = _extraer_paleta_logo(logo_bytes)
    P = _colores(palette)
    E = _estilos(P)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
        leftMargin=1.6*cm, rightMargin=1.6*cm,
        topMargin=1.2*cm, bottomMargin=1.4*cm,
        title=f"Cotizacion {numero}")

    r = resultado
    story = []

    story.append(_header_bloque(E, P, "COTIZACION DE PROYECTO", numero, fecha_str, emp, logo_bytes))
    story.append(Spacer(1, 8))

    # ── Datos del cliente ────────────────────────────────────────────────────
    datos_filas = []
    if r.get("nombre_cliente"):
        datos_filas.append(("Para", r["nombre_cliente"]))
    datos_filas += [
        ("Ciudad",           emp.get("ciudad", "Barranquilla")),
        ("Proyecto",         r.get("tipo_proyecto", "—")),
        ("Forma de pago",    "60% anticipo — 40% contra entrega"),
        ("Validez / Entrega",f"30 días · Entrega: {r.get('dias', '—')} días · Anticipo: 60%"),
    ]

    story.append(Paragraph("DATOS DEL CLIENTE", E["seccion"]))
    story.append(Spacer(1, 4))
    story.append(_tabla_2col(E, P, datos_filas))
    story.append(Spacer(1, 8))

    # ── Tabla de ítems (solo piezas del proyecto — cara al cliente) ──────────
    # PROTECCIÓN DE MÁRGENES: el cliente ve solo las piezas con su precio de venta.
    # No ve desglose interno de material, producción, logística, etc.
    piezas = r.get("_estado_guardado", {}).get("piezas", [])
    precio_sugerido_total = r.get("precio_sugerido", 0)

    story.append(Paragraph("DETALLE DE ÍTEMS Y PRECIOS", E["seccion"]))
    story.append(Spacer(1, 4))

    hdr_style = ParagraphStyle("th", leading=10, fontSize=7.5, fontName="Helvetica-Bold",
                                textColor=P["white"])
    cel_style = ParagraphStyle("tc", leading=11, fontSize=8.5, fontName="Helvetica",
                                textColor=P["text"])
    cel_bold  = ParagraphStyle("tcb", leading=11, fontSize=8.5, fontName="Helvetica-Bold",
                                textColor=P["text"])
    cel_r     = ParagraphStyle("tcr", leading=11, fontSize=8.5, fontName="Helvetica",
                                textColor=P["text"], alignment=TA_RIGHT)
    cel_bold_r= ParagraphStyle("tcbr", leading=11, fontSize=8.5, fontName="Helvetica-Bold",
                                textColor=P["text"], alignment=TA_RIGHT)

    tabla_items_filas = [[
        Paragraph("DESCRIPCIÓN",    hdr_style),
        Paragraph("UNID.",          ParagraphStyle("thc", leading=10, fontSize=7.5, fontName="Helvetica-Bold", textColor=P["white"], alignment=TA_CENTER)),
        Paragraph("CANT.",          ParagraphStyle("thc2", leading=10, fontSize=7.5, fontName="Helvetica-Bold", textColor=P["white"], alignment=TA_CENTER)),
        Paragraph("P. UNITARIO",    ParagraphStyle("thr", leading=10, fontSize=7.5, fontName="Helvetica-Bold", textColor=P["white"], alignment=TA_RIGHT)),
        Paragraph("SUBTOTAL",       ParagraphStyle("thr2", leading=10, fontSize=7.5, fontName="Helvetica-Bold", textColor=P["white"], alignment=TA_RIGHT)),
    ]]

    if piezas:
        # Distribuir el precio sugerido proporcionalmente al m² de cada pieza
        total_m2_piezas = sum(p.get("ml", 1) * p.get("ancho_custom", 0.60) for p in piezas)
        subtotal_items  = 0.0
        for p in piezas:
            m2_p = p.get("ml", 1) * p.get("ancho_custom", 0.60)
            prop  = (m2_p / total_m2_piezas) if total_m2_piezas > 0 else (1 / len(piezas))
            precio_p = precio_sugerido_total * prop
            ml_p     = p.get("ml", 1)
            pu       = precio_p / ml_p if ml_p > 0 else 0
            subtotal_items += precio_p
            tabla_items_filas.append([
                Paragraph(p.get("nombre", "—"), cel_style),
                Paragraph("ml", ParagraphStyle("tcc", leading=11, fontSize=8.5, fontName="Helvetica", textColor=P["text"], alignment=TA_CENTER)),
                Paragraph(f"{ml_p:.2f}", ParagraphStyle("tcc2", leading=11, fontSize=8.5, fontName="Helvetica", textColor=P["text"], alignment=TA_CENTER)),
                Paragraph(_num(round(pu / 1000) * 1000), cel_r),
                Paragraph(_num(round(precio_p / 1000) * 1000), cel_bold_r),
            ])
    else:
        # Sin piezas → mostrar una sola línea con el tipo de proyecto
        tabla_items_filas.append([
            Paragraph(f"{r.get('tipo_proyecto','Proyecto')} — {r.get('referencia', r.get('categoria',''))}", cel_style),
            Paragraph("glb", ParagraphStyle("tcc", leading=11, fontSize=8.5, fontName="Helvetica", textColor=P["text"], alignment=TA_CENTER)),
            Paragraph("1", ParagraphStyle("tcc2", leading=11, fontSize=8.5, fontName="Helvetica", textColor=P["text"], alignment=TA_CENTER)),
            Paragraph(_num(precio_sugerido_total), cel_r),
            Paragraph(_num(precio_sugerido_total), cel_bold_r),
        ])

    # Subtotal
    tabla_items_filas.append([
        Paragraph("Subtotal", cel_bold), "", "", "",
        Paragraph(_num(precio_sugerido_total), cel_bold_r),
    ])

    if incluir_iva:
        iva_total = precio_sugerido_total * 0.19
        precio_final_doc = precio_sugerido_total + iva_total
        tabla_items_filas.append([
            Paragraph("Base gravable (subtotal)", cel_style), "", "", "",
            Paragraph(_num(precio_sugerido_total), cel_r),
        ])
        tabla_items_filas.append([
            Paragraph("IVA 19% (Art. 468 E.T.)", ParagraphStyle("iva", leading=11, fontSize=8.5, fontName="Helvetica", textColor=P["secondary"])),
            "", "", "",
            Paragraph(_num(iva_total), ParagraphStyle("ivav", leading=11, fontSize=8.5, fontName="Helvetica", textColor=P["secondary"], alignment=TA_RIGHT)),
        ])
        tabla_items_filas.append([
            Paragraph("Subtotal con IVA", cel_style), "", "", "",
            Paragraph(_num(precio_final_doc), cel_bold_r),
        ])
        # Fila total final
        tabla_items_filas.append([
            Paragraph("TOTAL (IVA INCLUIDO)", ParagraphStyle("tot", leading=13, fontSize=10, fontName="Helvetica-Bold", textColor=P["white"])),
            "", "", "",
            Paragraph(_num(precio_final_doc), ParagraphStyle("totv", leading=13, fontSize=10, fontName="Helvetica-Bold", textColor=P["white"], alignment=TA_RIGHT)),
        ])
    else:
        precio_final_doc = precio_sugerido_total
        tabla_items_filas.append([
            Paragraph("TOTAL (SIN IVA)", ParagraphStyle("tot", leading=13, fontSize=10, fontName="Helvetica-Bold", textColor=P["white"])),
            "", "", "",
            Paragraph(_num(precio_final_doc), ParagraphStyle("totv", leading=13, fontSize=10, fontName="Helvetica-Bold", textColor=P["white"], alignment=TA_RIGHT)),
        ])

    n_items = len(piezas) if piezas else 1
    n_subtotal_rows = 4 if incluir_iva else 2  # rows after items: subtotal + gravable + iva + sub_iva + total

    tbl_items = Table(tabla_items_filas, colWidths=[8*cm, 1.2*cm, 1.5*cm, 3*cm, 3.3*cm])
    ts_items = [
        # Header
        ("BACKGROUND",    (0,0), (-1,0),  P["secondary"]),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("RIGHTPADDING",  (0,0), (-1,-1), 8),
        # Items zebra
        ("ROWBACKGROUNDS",(0,1), (-1, n_items), [P["white"], P["ultralight"]]),
        # Subtotal row
        ("BACKGROUND",    (0, n_items+1), (-1, n_items+1), P["light"]),
        # Total row (always last)
        ("BACKGROUND",    (0,-1), (-1,-1), P["primary"]),
        ("LINEABOVE",     (0,-1), (-1,-1), 1.2, P["primary"]),
        ("LINEBELOW",     (0,0),  (-1,-2), 0.3, P["light"]),
        # Spans for subtotal/iva/total rows
        ("SPAN", (0, n_items+1), (3, n_items+1)),
        ("SPAN", (0,-1), (3,-1)),
    ]
    if incluir_iva:
        ts_items += [
            ("SPAN", (0, n_items+2), (3, n_items+2)),
            ("SPAN", (0, n_items+3), (3, n_items+3)),
            ("SPAN", (0, n_items+4), (3, n_items+4)),
            ("BACKGROUND", (0, n_items+3), (-1, n_items+3), P["ultralight"]),
        ]

    tbl_items.setStyle(TableStyle(ts_items))
    story.append(tbl_items)
    story.append(Spacer(1, 10))

    # ── Alcance del proyecto (incluye / no incluye) ───────────────────────────
    inc_style  = ParagraphStyle("inc", leading=11, fontSize=7.5, fontName="Helvetica", textColor=P["text"])
    ninc_style = ParagraphStyle("ninc", leading=11, fontSize=7.5, fontName="Helvetica", textColor=P["text"])
    hdr_inc    = ParagraphStyle("hi", leading=10, fontSize=7.5, fontName="Helvetica-Bold", textColor=P["white"])

    incluye = [
        "Toma de rectificación de medidas finales en obra previa a producción",
        "Transporte especializado y acarreo cuidadoso del material hasta el punto de instalación",
        "Garantía de 12 meses sobre la mano de obra de instalación",
        "Limpieza técnica final del área de trabajo y retiro de desperdicios de material",
        "Diseño y modelado 3D fotorrealista del proyecto para previsualización de acabados pétreos",
        "Aplicación de tratamiento protector inicial (sellador hidrófugo/oleófugo) post-instalación",
    ]
    no_incluye = [
        "Conexiones finales (grifería, electrodomésticos y conexiones hidráulicas, eléctricas o de gas)",
        "Trabajos previos de obra civil (demoliciones, adecuación de muros, resanes o pintura)",
        "Suministro de materiales de obra gris ajenos a la instalación del proyecto",
        "Suministro o reparación de muebles de madera, ebanistería o estructuras de soporte inferiores",
    ]

    col_inc  = [[Paragraph("✔ INCLUYE",    hdr_inc)]] + [[Paragraph(f"✔ {t}", inc_style)] for t in incluye]
    col_ninc = [[Paragraph("✖ NO INCLUYE", hdr_inc)]] + [[Paragraph(f"✖ {t}", ninc_style)] for t in no_incluye] + \
               [[""] for _ in range(len(incluye) - len(no_incluye))]  # pad to same height

    max_rows = max(len(col_inc), len(col_ninc))
    while len(col_inc)  < max_rows: col_inc.append([""])
    while len(col_ninc) < max_rows: col_ninc.append([""])

    alcance_rows = [[col_inc[i][0], col_ninc[i][0]] for i in range(max_rows)]
    tbl_alcance = Table(alcance_rows, colWidths=[8.5*cm, 8.5*cm])
    tbl_alcance.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0),  P["secondary"]),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [P["white"], P["ultralight"]]),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("RIGHTPADDING",  (0,0), (-1,-1), 8),
        ("LINEBELOW",     (0,0), (-1,-1), 0.3, P["light"]),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
    ]))
    story.append(Paragraph("ALCANCE DEL PROYECTO", E["seccion"]))
    story.append(Spacer(1, 4))
    story.append(tbl_alcance)
    story.append(Spacer(1, 8))

    # ── Condiciones generales ─────────────────────────────────────────────────
    nota_iva = (
        "El precio incluye IVA del 19% (Art. 468 E.T.) — Responsable de IVA — Régimen Común. "
        if incluir_iva else
        "Cotización expedida sin IVA — prestador perteneciente al Régimen Simplificado (Art. 499 E.T.). "
    )
    condiciones_texto = (
        nota_iva +
        "Esta cotización abarca exclusivamente los materiales, servicios y alcances detallados "
        "expresamente en la sección de Inclusiones. Cualquier requerimiento adicional, modificación "
        "de diseño posterior a la rectificación de medidas, o trabajo no especificado en este "
        "documento, será considerado un servicio extra y requerirá una recotización y/o aprobación "
        "previa para su ejecución."
    )
    tbl_cond = Table(
        [[Paragraph("■ CONDICIONES GENERALES", ParagraphStyle("cg", leading=11, fontSize=7.5,
                    fontName="Helvetica-Bold", textColor=P["text"])),
          Paragraph(condiciones_texto, E["aviso"])]],
        colWidths=[4*cm, 13*cm]
    )
    tbl_cond.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), P["ultralight"]),
        ("TOPPADDING",    (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ("RIGHTPADDING",  (0,0), (-1,-1), 10),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("LINEABOVE",     (0,0), (-1,0),  0.8, P["secondary"]),
    ]))
    story.append(tbl_cond)
    story.append(Spacer(1, 10))

    story.extend(_footer(E, P, emp.get("nombre", ""), fecha_str))
    doc.build(story)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
# CUENTA DE COBRO — 1 PAGINA FIJA, MISMO DISENO
# ═══════════════════════════════════════════════════════════════════════════════
def generar_cuenta_cobro(resultado: dict, datos_prestador: dict, datos_pagador: dict,
                          numero: str = None, descripcion_servicio: str = None,
                          logo_bytes: bytes = None, incluir_iva: bool = True) -> bytes:
    if numero is None:
        numero = f"CC-{date.today().strftime('%Y%m%d')}-001"
    fecha_str = _fecha_es()

    precio_base = resultado.get("precio_sugerido", resultado.get("precio_total", 0))
    utilidad    = resultado.get("utilidad", 0)
    iva         = precio_base * 0.19 if incluir_iva else 0.0   # IVA sobre total
    valor_total = precio_base + iva

    # CORRECCIÓN: datos_prestador viene directamente de empresa_info (app.py).
    # Mapeamos solo los campos que debe mostrar el encabezado (NO cuenta_numero).
    # La cuenta bancaria se renderiza más abajo en "DATOS PARA PAGO".
    emp = {
        "nombre":  datos_prestador.get("nombre", ""),
        "nit":     datos_prestador.get("nit", datos_prestador.get("nit_cc", "")),
        "ciudad":  datos_prestador.get("ciudad", datos_prestador.get("direccion", "")),
        "tel":     datos_prestador.get("tel", datos_prestador.get("telefono", "")),
        "email":   datos_prestador.get("email", ""),
    }

    palette = _extraer_paleta_logo(logo_bytes)
    P = _colores(palette)
    E = _estilos(P)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
        leftMargin=1.6*cm, rightMargin=1.6*cm,
        topMargin=1.2*cm, bottomMargin=1.4*cm,
        title=f"Cuenta de Cobro {numero}")

    story = []

    # Encabezado identico al de cotizacion
    story.append(_header_bloque(E, P, "CUENTA DE COBRO", numero, fecha_str, emp, logo_bytes))
    story.append(Spacer(1, 10))

    # Prestador y pagador en 2 columnas
    story.append(Paragraph("QUIEN COBRA", E["seccion"]))
    story.append(Spacer(1, 4))
    story.append(_tabla_2col(E, P, [
        ("Nombre / Razon Social", datos_prestador.get("nombre","—")),
        ("NIT / CC",              datos_prestador.get("nit_cc","—")),
        ("Direccion",             datos_prestador.get("direccion","—")),
        ("Telefono",              datos_prestador.get("telefono","—")),
    ]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("QUIEN PAGA", E["seccion"]))
    story.append(Spacer(1, 4))
    story.append(_tabla_2col(E, P, [
        ("Nombre / Razon Social", datos_pagador.get("nombre","—")),
        ("NIT / CC",              datos_pagador.get("nit","—")),
        ("Direccion",             datos_pagador.get("direccion","—")),
    ]))
    story.append(Spacer(1, 8))

    # Descripcion del servicio — lenguaje comercial, sin datos internos
    if descripcion_servicio is None:
        m2 = resultado.get('m2_real', 0)
        tipo = resultado.get('tipo_proyecto', 'proyecto')
        cat  = resultado.get('categoria', 'material pétreo')
        ref  = resultado.get('referencia', '')
        ref_txt = f" referencia {ref}" if ref else ""
        descripcion_servicio = (
            f"Suministro, fabricación e instalación de {tipo} en {cat}{ref_txt}. "
            f"Área instalada: {m2:.2f} m². "
            f"Incluye corte, elaboración, instalación, insumos y transporte según especificaciones acordadas."
        )
    story.append(Paragraph("DESCRIPCION DEL SERVICIO", E["seccion"]))
    story.append(Spacer(1, 4))
    t_serv = Table([[Paragraph(descripcion_servicio, E["normal"])]], colWidths=[17*cm])
    t_serv.setStyle(TableStyle([
        ("BACKGROUND",   (0,0),(-1,-1), P["ultralight"]),
        ("TOPPADDING",   (0,0),(-1,-1), 8), ("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("LEFTPADDING",  (0,0),(-1,-1),10), ("RIGHTPADDING", (0,0),(-1,-1),10),
        ("LINEBELOW",    (0,0),(-1,-1), 0.5, P["secondary"]),
    ]))
    story.append(t_serv)
    story.append(Spacer(1, 8))

    # Valor total con desglose de IVA (condicional)
    valor_letras = _numero_a_letras(int(round(valor_total)))

    if incluir_iva:
        label_subtotal = "Valor del servicio (sin IVA)"
        filas_val = [
            [Paragraph(label_subtotal,
                       ParagraphStyle("cc1", leading=11, fontSize=8.5, fontName="Helvetica", textColor=P["text"])),
             Paragraph(_num(precio_base),
                       ParagraphStyle("cc1v", leading=11, fontSize=8.5, fontName="Helvetica", textColor=P["text"], alignment=TA_RIGHT))],
            [Paragraph("IVA 19% (Impuesto al Valor Agregado)",
                       ParagraphStyle("cc2", leading=11, fontSize=8.5, fontName="Helvetica", textColor=P["secondary"])),
             Paragraph(_num(iva),
                       ParagraphStyle("cc2v", leading=11, fontSize=8.5, fontName="Helvetica", textColor=P["secondary"], alignment=TA_RIGHT))],
            [Paragraph("TOTAL A COBRAR (IVA INCLUIDO)",
                       ParagraphStyle("cc3", leading=13, fontSize=10, fontName="Helvetica-Bold", textColor=P["white"])),
             Paragraph(_num(valor_total),
                       ParagraphStyle("cc3v", leading=13, fontSize=10, fontName="Helvetica-Bold", textColor=P["white"], alignment=TA_RIGHT))],
        ]
        ts_val = [
            ("BACKGROUND", (0,0), (-1,0), P["ultralight"]),
            ("BACKGROUND", (0,1), (-1,1), P["light"]),
            ("BACKGROUND", (0,2), (-1,2), P["primary"]),
            ("TOPPADDING",    (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
            ("LEFTPADDING",   (0,0), (-1,-1), 10),
            ("RIGHTPADDING",  (0,0), (-1,-1), 10),
            ("LINEABOVE",     (0,-1), (-1,-1), 1.2, P["primary"]),
        ]
    else:
        filas_val = [
            [Paragraph("TOTAL A COBRAR (SIN IVA — Régimen Simplificado)",
                       ParagraphStyle("cc3", leading=13, fontSize=10, fontName="Helvetica-Bold", textColor=P["white"])),
             Paragraph(_num(valor_total),
                       ParagraphStyle("cc3v", leading=13, fontSize=10, fontName="Helvetica-Bold", textColor=P["white"], alignment=TA_RIGHT))],
        ]
        ts_val = [
            ("BACKGROUND",    (0,0), (-1,0), P["primary"]),
            ("TOPPADDING",    (0,0), (-1,-1), 8),
            ("BOTTOMPADDING", (0,0), (-1,-1), 8),
            ("LEFTPADDING",   (0,0), (-1,-1), 10),
            ("RIGHTPADDING",  (0,0), (-1,-1), 10),
        ]

    tbl_val = Table(filas_val, colWidths=[12.5*cm, 4.5*cm])
    tbl_val.setStyle(TableStyle(ts_val))
    story.append(Paragraph("VALOR DEL COBRO", E["seccion"]))
    story.append(Spacer(1, 4))
    story.append(tbl_val)
    # Valor en letras
    story.append(Table(
        [[Paragraph(f"Son: {valor_letras} pesos M/CTE", E["white_s"])]],
        colWidths=[17*cm],
        style=TableStyle([
            ("BACKGROUND",(0,0),(-1,-1),P["primary"]),
            ("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),8),
            ("LEFTPADDING",(0,0),(-1,-1),16),
        ])
    ))
    story.append(Spacer(1, 8))

    # Datos bancarios
    banco_filas = []
    if datos_prestador.get("banco"):
        banco_filas.append(("Banco", datos_prestador["banco"]))
    if datos_prestador.get("cuenta_tipo"):
        banco_filas.append(("Tipo de cuenta", datos_prestador["cuenta_tipo"]))
    if datos_prestador.get("cuenta_numero"):
        banco_filas.append(("N de cuenta", datos_prestador["cuenta_numero"]))
    if datos_prestador.get("nombre"):
        banco_filas.append(("A nombre de", datos_prestador["nombre"]))
    if banco_filas:
        story.append(Paragraph("DATOS PARA PAGO", E["seccion"]))
        story.append(Spacer(1, 4))
        story.append(_tabla_2col(E, P, banco_filas))
        story.append(Spacer(1, 8))

    # Firmas
    firma = Table([[
        Table([
            [Paragraph("_" * 40, E["normal"])],
            [Paragraph(datos_prestador.get("nombre",""), E["aviso"])],
            [Paragraph("Firma del Prestador", E["aviso"])],
        ]),
        "",
        Table([
            [Paragraph("_" * 35, E["normal"])],
            [Paragraph("", E["aviso"])],
            [Paragraph("Sello / Firma del Pagador", E["aviso"])],
        ]),
    ]], colWidths=[8*cm, 1.5*cm, 7.5*cm])
    firma.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),14),("VALIGN",(0,0),(-1,-1),"BOTTOM")]))
    story.append(firma)
    story.append(Spacer(1, 12))

    story.extend(_footer(E, P, datos_prestador.get("nombre",""), fecha_str))
    doc.build(story)
    return buf.getvalue()


# ── Conversion de numero a letras ─────────────────────────────────────────────
def _numero_a_letras(n: int) -> str:
    if n == 0: return "cero"
    unidades = ["","uno","dos","tres","cuatro","cinco","seis","siete","ocho","nueve",
                "diez","once","doce","trece","catorce","quince","dieciseis","diecisiete","dieciocho","diecinueve"]
    decenas  = ["","diez","veinte","treinta","cuarenta","cincuenta","sesenta","setenta","ochenta","noventa"]
    centenas = ["","ciento","doscientos","trescientos","cuatrocientos","quinientos","seiscientos","setecientos","ochocientos","novecientos"]
    def _menor_mil(x):
        if x == 0: return ""
        if x == 100: return "cien"
        c, resto = divmod(x, 100)
        d, u = divmod(resto, 10)
        partes = []
        if c: partes.append(centenas[c])
        if resto == 0: pass
        elif resto < 20: partes.append(unidades[resto])
        else:
            p = decenas[d]
            if u: p += " y " + unidades[u]
            partes.append(p)
        return " ".join(partes)
    if n < 0: return "menos " + _numero_a_letras(-n)
    if n < 1000: return _menor_mil(n)
    if n < 1_000_000:
        m, r = divmod(n, 1000)
        pre = "mil" if m == 1 else _menor_mil(m) + " mil"
        return (pre + " " + _menor_mil(r)).strip()
    if n < 1_000_000_000:
        m, r = divmod(n, 1_000_000)
        pre = "un millon" if m == 1 else _menor_mil(m) + " millones"
        return (pre + " " + _numero_a_letras(r)).strip()
    return str(n)
