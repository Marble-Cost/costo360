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
    """Encabezado identico para cotizacion y cuenta de cobro. Solo cambia el titulo."""
    emp = empresa_info or {}
    nombre_emp = emp.get("nombre", "MARMOLES COLLANTE & CASTRO LTDA.")

    logo_img = _logo_img(logo_bytes, max_h=1.4*cm)

    # Columna izquierda: logo + nombre empresa
    col_izq = []
    if logo_img:
        col_izq.append(logo_img)
        col_izq.append(Spacer(1, 4))
    col_izq.append(Paragraph(nombre_emp, ParagraphStyle("ne", leading=12, fontSize=9, fontName="Helvetica-Bold", textColor=P["white"])))
    col_izq.append(Paragraph(emp.get("nit", ""), E["white_s"]))
    col_izq.append(Paragraph(emp.get("ciudad", "Barranquilla, Colombia"), E["white_s"]))
    col_izq.append(Paragraph(emp.get("tel", ""), E["white_s"]))

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
    Tabla de desglose para el PDF de COTIZACIÓN.
    IMPORTANTE: Solo muestra conceptos relevantes para el cliente.
    NO muestra: costo de material interno, margen, desglose de disco,
    desgaste de máquina ni información operativa interna.
    """
    items = [
        ("Suministro de material pétreo",          r.get("c1_material", 0)),
        ("Fabricación y elaboración",               r.get("c2_mano_obra", 0)),
        ("Instalación de zócalos",                  r.get("c3_zocalos", 0)),
        ("Insumos y herramientas especializadas",   r.get("c4_insumos", 0)),
        ("Transporte y logística",                  r.get("c5_logistica", 0)),
        ("Gastos de desplazamiento",                r.get("c6_viaticos", 0)),
        ("Costos adicionales en obra",              r.get("c7_adicionales", 0)),
    ]
    items = [(c, v) for c, v in items if v > 0]

    utilidad   = r.get("utilidad", 0)
    precio_base = r.get("precio_sugerido", 0)

    if incluir_iva:
        iva         = utilidad * 0.19
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

    datos_filas = []
    if r.get("nombre_cliente"):
        datos_filas.append(("Cliente", r["nombre_cliente"]))
    datos_filas += [
        ("Tipo de proyecto",  r.get("tipo_proyecto", "—")),
        ("Material",          f"{r.get('categoria','—')} — {r.get('referencia','—')}"),
        ("Área del proyecto", f"{r.get('m2_real', 0):.2f} m²"),
        ("Tiempo de entrega", f"{r.get('dias', '—')} día(s) hábiles"),
        ("Vigencia oferta",   "15 días calendario"),
        ("IVA",               "Incluido (19% s/utilidad)" if incluir_iva else "No aplica — Régimen simplificado"),
    ]

    col_desglose, precio_final = _tabla_desglose(E, P, r, incluir_iva=incluir_iva)
    col_datos = _tabla_2col(E, P, datos_filas)

    story.append(Paragraph("DATOS DEL PROYECTO", E["seccion"]))
    story.append(Spacer(1, 4))
    story.append(col_datos)
    story.append(Spacer(1, 8))

    story.append(Paragraph("DETALLE DE LA OFERTA", E["seccion"]))
    story.append(Spacer(1, 4))
    story.append(col_desglose)
    story.append(Spacer(1, 8))

    nota_iva = (
        "Precios incluyen IVA del 19% calculado sobre la utilidad (Estatuto Tributario colombiano, Art. 468). "
        if incluir_iva else
        "Cotización expedida sin IVA — prestador perteneciente al Régimen Simplificado (Art. 499 E.T.). "
    )
    story.append(Paragraph(
        nota_iva +
        "Cotización válida por 15 días calendario. Incluye exclusivamente los materiales y servicios detallados. "
        "Cualquier requerimiento adicional o modificación posterior requiere nueva cotización. "
        "Precios sujetos a disponibilidad de material en el momento de confirmar el pedido.",
        E["aviso"]))
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
    iva         = utilidad * 0.19 if incluir_iva else 0.0
    valor_total = precio_base + iva

    # Construir empresa_info desde datos_prestador
    emp = {
        "nombre":  datos_prestador.get("nombre", ""),
        "nit":     datos_prestador.get("nit_cc", ""),
        "ciudad":  datos_prestador.get("direccion", ""),
        "tel":     datos_prestador.get("telefono", ""),
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
