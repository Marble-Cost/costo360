# generador_pdf.py — CostoMármol v6
# MARMOLES COLLANTE & CASTRO LTDA.
# Correcciones v6:
#   - Logo SIEMPRE presente en encabezado (logo corporativo integrado)
#   - AIU: discrimina A, I, U y calcula IVA SOLO sobre Utilidad (U)
#   - Anticipo visible en cotizaciones (no en cuentas de cobro)
#   - Cuentas de cobro: descripción muestra % anticipo acordado
#   - Todo en UNA sola página (márgenes ajustados, fuentes compactas)

import io
import os
from datetime import date, timedelta
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

# ── Paleta corporativa por defecto (colores del logo CC) ─────────────────────
_DEFAULT_PALETTE = {
    "primary":    "#0D2137",   # Azul marino profundo
    "secondary":  "#1B5FA8",   # Azul corporativo
    "accent":     "#C9A84C",   # Dorado corporativo
    "light":      "#D6E8FA",
    "ultralight": "#EEF5FD",
    "gray":       "#6B85A0",
    "text":       "#0D2137",
    "white":      "#FFFFFF",
}

# Ruta al logo corporativo (junto al script)
_LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo_cc.jpeg")


def _cargar_logo_corporativo() -> bytes | None:
    """Carga el logo corporativo desde disco."""
    try:
        with open(_LOGO_PATH, "rb") as f:
            return f.read()
    except Exception:
        return None


def _extraer_paleta_logo(logo_bytes: bytes | None) -> dict:
    """Extrae paleta dominante del logo. Usa default si falla."""
    if not logo_bytes:
        return _DEFAULT_PALETTE.copy()
    try:
        from PIL import Image as PILImage
        import io as _io
        img = PILImage.open(_io.BytesIO(logo_bytes)).convert("RGB")
        img.thumbnail((100, 100))
        pixels = list(img.getdata())
        filtered = [
            p for p in pixels
            if not (p[0] > 230 and p[1] > 230 and p[2] > 230)
            and not (p[0] < 15 and p[1] < 15 and p[2] < 15)
        ]
        if len(filtered) < 50:
            return _DEFAULT_PALETTE.copy()

        def saturation(r, g, b):
            mx, mn = max(r,g,b)/255, min(r,g,b)/255
            return (mx - mn) / mx if mx > 0 else 0

        saturated = sorted(filtered, key=lambda p: saturation(*p), reverse=True)
        top = saturated[:max(len(saturated)//4, 1)]
        avg_r = int(sum(p[0] for p in top) / len(top))
        avg_g = int(sum(p[1] for p in top) / len(top))
        avg_b = int(sum(p[2] for p in top) / len(top))

        def darken(r, g, b, f=0.45): return (int(r*f), int(g*f), int(b*f))
        def lighten(r, g, b, f=0.88):
            return (min(255,int(r+(255-r)*f)), min(255,int(g+(255-g)*f)), min(255,int(b+(255-b)*f)))
        def to_hex(r, g, b): return f"#{r:02X}{g:02X}{b:02X}"

        pr  = darken(avg_r, avg_g, avg_b, 0.45)
        sec = (int(avg_r*0.7), int(avg_g*0.7), int(avg_b*0.7))
        lt  = lighten(avg_r, avg_g, avg_b, 0.82)
        ult = lighten(avg_r, avg_g, avg_b, 0.92)
        is_cool = avg_b > avg_r and avg_b > avg_g
        accent = "#C9A84C" if is_cool else to_hex(
            min(255, int(avg_b*0.8+100)), min(255, int(avg_g*0.6+80)), min(255, int(avg_r*0.3))
        )
        return {
            "primary": to_hex(*pr), "secondary": to_hex(*sec),
            "accent": accent, "light": to_hex(*lt), "ultralight": to_hex(*ult),
            "gray": "#6B85A0", "text": to_hex(*pr), "white": "#FFFFFF",
        }
    except Exception:
        return _DEFAULT_PALETTE.copy()


def _colores(palette: dict):
    return {k: colors.HexColor(v) for k, v in palette.items()}


def _num(valor: float) -> str:
    return f"${int(round(valor)):,}".replace(",", ".")


def _fecha_es():
    f = date.today()
    meses = ["enero","febrero","marzo","abril","mayo","junio",
             "julio","agosto","septiembre","octubre","noviembre","diciembre"]
    return f"{f.day} de {meses[f.month-1]} de {f.year}"


def _fecha_hasta(dias: int) -> str:
    f = date.today() + timedelta(days=dias)
    meses = ["enero","febrero","marzo","abril","mayo","junio",
             "julio","agosto","septiembre","octubre","noviembre","diciembre"]
    return f"{f.day}/{f.month}/{f.year}"


def _estilos(P):
    b13 = dict(leading=12)
    b11 = dict(leading=10)
    return {
        "titulo":   ParagraphStyle("titulo",   **b13, fontSize=16, fontName="Helvetica-Bold",  textColor=P["white"]),
        "subtit":   ParagraphStyle("subtit",   **b11, fontSize=7.5,fontName="Helvetica",       textColor=colors.HexColor("#B8D4F0")),
        "empresa":  ParagraphStyle("empresa",  **b11, fontSize=7.5,fontName="Helvetica",       textColor=P["white"], alignment=TA_RIGHT),
        "seccion":  ParagraphStyle("seccion",  **b11, fontSize=6.5,fontName="Helvetica-Bold",  textColor=P["gray"], letterSpacing=1.2),
        "normal":   ParagraphStyle("normal",   **b13, fontSize=8,  fontName="Helvetica",       textColor=P["text"]),
        "bold":     ParagraphStyle("bold",     **b13, fontSize=8,  fontName="Helvetica-Bold",  textColor=P["text"]),
        "footer":   ParagraphStyle("footer",   **b11, fontSize=6.5,fontName="Helvetica",       textColor=P["gray"], alignment=TA_CENTER),
        "aviso":    ParagraphStyle("aviso",     leading=9, fontSize=6.5, fontName="Helvetica", textColor=P["gray"]),
        "accent_s": ParagraphStyle("accent_s", **b11, fontSize=7,  fontName="Helvetica-Bold",  textColor=P["accent"]),
        "white_s":  ParagraphStyle("white_s",  **b11, fontSize=7.5,fontName="Helvetica",       textColor=P["white"]),
        "price":    ParagraphStyle("price",    leading=24, fontSize=20, fontName="Helvetica-Bold", textColor=P["white"]),
    }


def _logo_img(logo_bytes: bytes | None, max_h: float = 1.3*cm) -> Image | None:
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


def _header_bloque(E, P, doc_type, numero, fecha_str, empresa_info, logo_bytes, valido_hasta=None):
    """
    Encabezado corporativo con logo SIEMPRE visible.
    Intenta cargar el logo proporcionado; si no, usa el corporativo del disco.
    """
    emp = empresa_info or {}
    nombre_emp = emp.get("nombre", "MARMOLES COLLANTE & CASTRO LTDA.")

    # Garantizar logo: primero el pasado, luego el corporativo
    _lb = logo_bytes or _cargar_logo_corporativo()
    logo_img = _logo_img(_lb, max_h=1.3*cm)

    # Columna izquierda: logo + datos empresa
    col_izq = []
    if logo_img:
        col_izq.append(logo_img)
        col_izq.append(Spacer(1, 3))
    col_izq.append(Paragraph(nombre_emp,
        ParagraphStyle("ne", leading=11, fontSize=8.5, fontName="Helvetica-Bold", textColor=P["white"])))
    if emp.get("nit"):
        col_izq.append(Paragraph(emp["nit"], E["white_s"]))
    if emp.get("tel") and emp.get("email"):
        col_izq.append(Paragraph(f"{emp['tel']} · {emp['email']}", E["white_s"]))
    elif emp.get("tel"):
        col_izq.append(Paragraph(emp["tel"], E["white_s"]))
    if emp.get("ciudad"):
        col_izq.append(Paragraph(emp["ciudad"], E["white_s"]))

    # Columna derecha: tipo doc + número + fecha
    col_der = [
        Paragraph(doc_type, E["accent_s"]),
        Spacer(1, 3),
        Paragraph(f"<b>{numero}</b>",
            ParagraphStyle("num", leading=16, fontSize=12, fontName="Helvetica-Bold",
                           textColor=P["white"], alignment=TA_RIGHT)),
        Spacer(1, 3),
        Paragraph(fecha_str,
            ParagraphStyle("fch", leading=10, fontSize=7.5, fontName="Helvetica",
                           textColor=colors.HexColor("#B8D4F0"), alignment=TA_RIGHT)),
    ]
    if emp.get("email"):
        col_der.append(Paragraph(emp["email"],
            ParagraphStyle("eml", leading=9, fontSize=6.5, fontName="Helvetica",
                           textColor=colors.HexColor("#B8D4F0"), alignment=TA_RIGHT)))
    if valido_hasta:
        col_der.append(Paragraph(f"Válida hasta: {valido_hasta}",
            ParagraphStyle("val", leading=9, fontSize=6.5, fontName="Helvetica-Bold",
                           textColor=P["accent"], alignment=TA_RIGHT)))

    tbl = Table([[col_izq, col_der]], colWidths=[10*cm, 7*cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), P["primary"]),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("TOPPADDING",    (0,0), (-1,-1), 12),
        ("BOTTOMPADDING", (0,0), (-1,-1), 12),
        ("LEFTPADDING",   (0,0), (0,-1),  14),
        ("RIGHTPADDING",  (-1,0),(-1,-1), 14),
    ]))
    return tbl


def _tabla_2col(E, P, filas_datos):
    filas = []
    for label, valor in filas_datos:
        filas.append([Paragraph(label, E["normal"]), Paragraph(f"<b>{valor}</b>", E["bold"])])
    tbl = Table(filas, colWidths=[5.5*cm, 11.5*cm])
    tbl.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [P["white"], P["ultralight"]]),
        ("TOPPADDING",     (0,0), (-1,-1), 4),
        ("BOTTOMPADDING",  (0,0), (-1,-1), 4),
        ("LEFTPADDING",    (0,0), (-1,-1), 8),
        ("LINEBELOW",      (0,0), (-1,-1), 0.3, P["light"]),
    ]))
    return tbl


def _footer(E, P, emp_nombre, fecha_str, numero=""):
    linea = f"{emp_nombre}   ·   {fecha_str}   ·   Barranquilla, Colombia"
    if numero:
        linea = f"{numero}   ·   " + linea
    return [
        HRFlowable(width="100%", thickness=0.5, color=P["light"]),
        Spacer(1, 3),
        Paragraph(linea, E["footer"]),
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# COTIZACION DIRECTA — 1 PÁGINA
# ═══════════════════════════════════════════════════════════════════════════════
def generar_pdf_cotizacion(resultado: dict, numero: str = None,
                            empresa_info: dict = None, logo_bytes: bytes = None,
                            incluir_iva: bool = True) -> bytes:
    if numero is None:
        numero = f"COT-{date.today().strftime('%Y%m%d')}-001"
    fecha_str = _fecha_es()
    emp = empresa_info or {}

    # Condiciones de pago
    anticipo_pct  = resultado.get("anticipo_pct", emp.get("anticipo_pct", 60))
    dias_entrega  = resultado.get("dias_entrega", emp.get("dias_entrega", 10))
    dias_validez  = resultado.get("dias_validez", emp.get("dias_validez", 30))
    valido_hasta  = _fecha_hasta(dias_validez)

    # Garantizar logo
    _lb = logo_bytes or _cargar_logo_corporativo()
    palette = _extraer_paleta_logo(_lb)
    P = _colores(palette)
    E = _estilos(P)

    buf = io.BytesIO()
    # Márgenes compactos para una sola página
    doc = SimpleDocTemplate(buf, pagesize=letter,
        leftMargin=1.4*cm, rightMargin=1.4*cm,
        topMargin=1.0*cm, bottomMargin=1.2*cm,
        title=f"Cotizacion {numero}")

    r = resultado
    story = []

    story.append(_header_bloque(E, P, "COTIZACIÓN DE PROYECTO", numero, fecha_str, emp, _lb, valido_hasta))
    story.append(Spacer(1, 6))

    # ── Tipo de cotización ───────────────────────────────────────────────────
    _tipo_badge = "DIRECTA"
    story.append(Table([[
        Paragraph(f"Fecha: {date.today().strftime('%d/%m/%Y')}  ·  Válida hasta: {valido_hasta}  ·  Tipo: {_tipo_badge}",
            ParagraphStyle("badge", leading=9, fontSize=6.5, fontName="Helvetica", textColor=P["gray"]))
    ]], colWidths=[17*cm],
        style=TableStyle([
            ("BACKGROUND", (0,0),(-1,-1), P["ultralight"]),
            ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
            ("LEFTPADDING",(0,0),(-1,-1),10),
        ])
    ))
    story.append(Spacer(1, 5))

    # ── Datos del cliente ────────────────────────────────────────────────────
    datos_filas = []
    if r.get("nombre_cliente"):
        datos_filas.append(("Para", r["nombre_cliente"]))
    datos_filas.append(("Ciudad", emp.get("ciudad", "Barranquilla")))
    datos_filas.append(("Proyecto", r.get("tipo_proyecto", "—")))
    datos_filas.append(("Forma de pago",
        f"{anticipo_pct}% anticipo — {100 - anticipo_pct}% contra entrega"))
    datos_filas.append(("Validez / Entrega",
        f"{dias_validez} días  ·  Entrega: {dias_entrega} días  ·  Anticipo: {anticipo_pct}%"))

    story.append(Paragraph("DATOS DEL CLIENTE", E["seccion"]))
    story.append(Spacer(1, 3))
    story.append(_tabla_2col(E, P, datos_filas))
    story.append(Spacer(1, 6))

    # ── Tabla de ítems ────────────────────────────────────────────────────────
    piezas = r.get("_estado_guardado", {}).get("piezas", [])
    precio_sugerido_total = r.get("precio_sugerido", 0)

    story.append(Paragraph("DETALLE DE ÍTEMS Y PRECIOS", E["seccion"]))
    story.append(Spacer(1, 3))

    hdr_s = ParagraphStyle("th", leading=9, fontSize=7, fontName="Helvetica-Bold", textColor=P["white"])
    cel_s = ParagraphStyle("tc", leading=10, fontSize=7.5, fontName="Helvetica", textColor=P["text"])
    cel_b = ParagraphStyle("tcb",leading=10, fontSize=7.5, fontName="Helvetica-Bold", textColor=P["text"])
    cel_r = ParagraphStyle("tcr",leading=10, fontSize=7.5, fontName="Helvetica", textColor=P["text"], alignment=TA_RIGHT)
    cel_br= ParagraphStyle("tcbr",leading=10,fontSize=7.5, fontName="Helvetica-Bold", textColor=P["text"], alignment=TA_RIGHT)

    tabla_items_filas = [[
        Paragraph("DESCRIPCIÓN",  hdr_s),
        Paragraph("UNID.", ParagraphStyle("thc", leading=9, fontSize=7, fontName="Helvetica-Bold", textColor=P["white"], alignment=TA_CENTER)),
        Paragraph("CANT.", ParagraphStyle("thc2",leading=9, fontSize=7, fontName="Helvetica-Bold", textColor=P["white"], alignment=TA_CENTER)),
        Paragraph("P. UNITARIO", ParagraphStyle("thr", leading=9, fontSize=7, fontName="Helvetica-Bold", textColor=P["white"], alignment=TA_RIGHT)),
        Paragraph("SUBTOTAL",    ParagraphStyle("thr2",leading=9, fontSize=7, fontName="Helvetica-Bold", textColor=P["white"], alignment=TA_RIGHT)),
    ]]

    if piezas:
        total_m2_piezas = sum(p.get("ml",1)*p.get("ancho_custom",0.60) for p in piezas)
        for p in piezas:
            m2_p = p.get("ml",1)*p.get("ancho_custom",0.60)
            prop  = (m2_p/total_m2_piezas) if total_m2_piezas > 0 else (1/len(piezas))
            precio_p = precio_sugerido_total * prop
            ml_p  = p.get("ml",1)
            pu    = precio_p/ml_p if ml_p > 0 else 0
            tabla_items_filas.append([
                Paragraph(p.get("nombre","—"), cel_s),
                Paragraph("ml", ParagraphStyle("tcc",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["text"],alignment=TA_CENTER)),
                Paragraph(f"{ml_p:.2f}", ParagraphStyle("tcc2",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["text"],alignment=TA_CENTER)),
                Paragraph(_num(round(pu/1000)*1000), cel_r),
                Paragraph(_num(round(precio_p/1000)*1000), cel_br),
            ])
    else:
        ref_txt = r.get("referencia", r.get("categoria",""))
        tabla_items_filas.append([
            Paragraph(f"{r.get('tipo_proyecto','Proyecto')} — {ref_txt}", cel_s),
            Paragraph("glb", ParagraphStyle("tcc",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["text"],alignment=TA_CENTER)),
            Paragraph("1",   ParagraphStyle("tcc2",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["text"],alignment=TA_CENTER)),
            Paragraph(_num(precio_sugerido_total), cel_r),
            Paragraph(_num(precio_sugerido_total), cel_br),
        ])

    n_items = len(piezas) if piezas else 1

    # Filas de totales
    tabla_items_filas.append([Paragraph("Subtotal", cel_b), "", "", "", Paragraph(_num(precio_sugerido_total), cel_br)])

    if incluir_iva:
        iva_total = precio_sugerido_total * 0.19
        precio_final_doc = precio_sugerido_total + iva_total
        tabla_items_filas.append([Paragraph("Base gravable (subtotal)", cel_s), "", "", "", Paragraph(_num(precio_sugerido_total), cel_r)])
        tabla_items_filas.append([Paragraph("IVA 19% (Art. 468 E.T.)",
            ParagraphStyle("iva",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["secondary"])),
            "", "", "", Paragraph(_num(iva_total),
            ParagraphStyle("ivav",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["secondary"],alignment=TA_RIGHT))])
        tabla_items_filas.append([Paragraph("Subtotal con IVA", cel_s), "", "", "", Paragraph(_num(precio_final_doc), cel_br)])
        # Fila anticipo
        anticipo_val = precio_final_doc * (anticipo_pct / 100)
        tabla_items_filas.append([
            Paragraph(f"ANTICIPO A PAGAR ({anticipo_pct}%)",
                ParagraphStyle("ant",leading=10,fontSize=8,fontName="Helvetica-Bold",textColor=P["accent"])),
            "", "", "",
            Paragraph(_num(anticipo_val),
                ParagraphStyle("antv",leading=10,fontSize=8,fontName="Helvetica-Bold",textColor=P["accent"],alignment=TA_RIGHT))
        ])
        # Total final
        tabla_items_filas.append([
            Paragraph("TOTAL (IVA INCLUIDO)",
                ParagraphStyle("tot",leading=12,fontSize=9.5,fontName="Helvetica-Bold",textColor=P["white"])),
            "", "", "",
            Paragraph(_num(precio_final_doc),
                ParagraphStyle("totv",leading=12,fontSize=9.5,fontName="Helvetica-Bold",textColor=P["white"],alignment=TA_RIGHT))
        ])
    else:
        precio_final_doc = precio_sugerido_total
        anticipo_val = precio_final_doc * (anticipo_pct / 100)
        tabla_items_filas.append([
            Paragraph(f"ANTICIPO A PAGAR ({anticipo_pct}%)",
                ParagraphStyle("ant",leading=10,fontSize=8,fontName="Helvetica-Bold",textColor=P["accent"])),
            "", "", "",
            Paragraph(_num(anticipo_val),
                ParagraphStyle("antv",leading=10,fontSize=8,fontName="Helvetica-Bold",textColor=P["accent"],alignment=TA_RIGHT))
        ])
        tabla_items_filas.append([
            Paragraph("TOTAL (SIN IVA)",
                ParagraphStyle("tot",leading=12,fontSize=9.5,fontName="Helvetica-Bold",textColor=P["white"])),
            "", "", "",
            Paragraph(_num(precio_final_doc),
                ParagraphStyle("totv",leading=12,fontSize=9.5,fontName="Helvetica-Bold",textColor=P["white"],alignment=TA_RIGHT))
        ])

    tbl_items = Table(tabla_items_filas, colWidths=[7.8*cm, 1.2*cm, 1.5*cm, 3*cm, 3.5*cm])
    n_sub = n_items + 1  # subtotal row index
    ts_items = [
        ("BACKGROUND",    (0,0),  (-1,0),   P["secondary"]),
        ("TOPPADDING",    (0,0),  (-1,-1),  4),
        ("BOTTOMPADDING", (0,0),  (-1,-1),  4),
        ("LEFTPADDING",   (0,0),  (-1,-1),  7),
        ("RIGHTPADDING",  (0,0),  (-1,-1),  7),
        ("ROWBACKGROUNDS",(0,1),  (-1,n_items), [P["white"], P["ultralight"]]),
        ("BACKGROUND",    (0,n_sub),(-1,n_sub), P["light"]),
        ("BACKGROUND",    (0,-2), (-1,-2),  colors.HexColor("#FFF3D4")),  # anticipo
        ("BACKGROUND",    (0,-1), (-1,-1),  P["primary"]),
        ("LINEABOVE",     (0,-1), (-1,-1),  1.2, P["primary"]),
        ("LINEBELOW",     (0,0),  (-1,-2),  0.3, P["light"]),
        ("SPAN", (0,n_sub),(3,n_sub)),
        ("SPAN", (0,-2),(3,-2)),
        ("SPAN", (0,-1),(3,-1)),
    ]
    if incluir_iva:
        ts_items += [
            ("SPAN", (0, n_sub+1),(3, n_sub+1)),
            ("SPAN", (0, n_sub+2),(3, n_sub+2)),
            ("SPAN", (0, n_sub+3),(3, n_sub+3)),
            ("BACKGROUND", (0,n_sub+2),(-1,n_sub+2), P["ultralight"]),
        ]

    tbl_items.setStyle(TableStyle(ts_items))
    story.append(tbl_items)
    story.append(Spacer(1, 6))

    # ── Alcance (incluye / no incluye) — compacto ─────────────────────────────
    inc_s  = ParagraphStyle("inc", leading=10, fontSize=6.5, fontName="Helvetica", textColor=P["text"])
    hinc_s = ParagraphStyle("hi",  leading=9,  fontSize=7,   fontName="Helvetica-Bold", textColor=P["white"])

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

    col_inc  = [[Paragraph("✔ INCLUYE",    hinc_s)]] + [[Paragraph(f"✔ {t}", inc_s)] for t in incluye]
    col_ninc = [[Paragraph("✖ NO INCLUYE", hinc_s)]] + [[Paragraph(f"✖ {t}", inc_s)] for t in no_incluye]

    max_rows = max(len(col_inc), len(col_ninc))
    while len(col_inc)  < max_rows: col_inc.append([""])
    while len(col_ninc) < max_rows: col_ninc.append([""])

    alcance_rows = [[col_inc[i][0], col_ninc[i][0]] for i in range(max_rows)]
    tbl_alcance = Table(alcance_rows, colWidths=[8.5*cm, 8.5*cm])
    tbl_alcance.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0),  P["secondary"]),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [P["white"], P["ultralight"]]),
        ("TOPPADDING",    (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("LEFTPADDING",   (0,0), (-1,-1), 7),
        ("RIGHTPADDING",  (0,0), (-1,-1), 7),
        ("LINEBELOW",     (0,0), (-1,-1), 0.3, P["light"]),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
    ]))
    story.append(Paragraph("ALCANCE DEL PROYECTO", E["seccion"]))
    story.append(Spacer(1, 3))
    story.append(tbl_alcance)
    story.append(Spacer(1, 5))

    # ── Condiciones generales ─────────────────────────────────────────────────
    nota_iva = (
        "El precio incluye IVA del 19% (Art. 468 E.T.) — Responsable de IVA — Régimen Común. "
        if incluir_iva else
        "Cotización expedida sin IVA — Régimen Simplificado (Art. 499 E.T.). "
    )
    condiciones_texto = (
        nota_iva +
        "Esta cotización abarca exclusivamente los materiales, servicios y alcances detallados "
        "expresamente en la sección de Inclusiones. Cualquier requerimiento adicional, modificación "
        "de diseño posterior a la rectificación de medidas, o trabajo no especificado en este "
        "documento, será considerado un servicio extra y requerirá una recotización y/o aprobación "
        f"previa para su ejecución. Anticipo requerido: {anticipo_pct}% del total al inicio de la obra."
    )
    tbl_cond = Table(
        [[Paragraph("■ CONDICIONES GENERALES",
            ParagraphStyle("cg",leading=10,fontSize=7,fontName="Helvetica-Bold",textColor=P["text"])),
          Paragraph(condiciones_texto, E["aviso"])]],
        colWidths=[3.5*cm, 13.5*cm]
    )
    tbl_cond.setStyle(TableStyle([
        ("BACKGROUND",   (0,0),(-1,-1), P["ultralight"]),
        ("TOPPADDING",   (0,0),(-1,-1), 6),
        ("BOTTOMPADDING",(0,0),(-1,-1), 6),
        ("LEFTPADDING",  (0,0),(-1,-1), 8),
        ("RIGHTPADDING", (0,0),(-1,-1), 8),
        ("VALIGN",       (0,0),(-1,-1), "TOP"),
        ("LINEABOVE",    (0,0),(-1,0),  0.8, P["secondary"]),
    ]))
    story.append(tbl_cond)
    story.append(Spacer(1, 6))
    story.extend(_footer(E, P, emp.get("nombre",""), fecha_str, numero))

    doc.build(story)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
# COTIZACIÓN AIU — 1 PÁGINA con desglose correcto A, I, U + IVA sobre U
# ═══════════════════════════════════════════════════════════════════════════════
def generar_pdf_cotizacion_aiu(resultado: dict, numero: str = None,
                                empresa_info: dict = None, logo_bytes: bytes = None) -> bytes:
    """
    PDF específico para cotizaciones AIU.
    Discrimina A (Admin), I (Imprevistos), U (Utilidad) y calcula IVA SOLO sobre U.
    """
    if numero is None:
        numero = f"COT-AIU-{date.today().strftime('%Y%m%d')}-001"
    fecha_str = _fecha_es()
    emp = empresa_info or {}

    anticipo_pct = resultado.get("anticipo_pct", emp.get("anticipo_pct", 60))
    dias_entrega = resultado.get("dias_entrega", emp.get("dias_entrega", 10))
    dias_validez = resultado.get("dias_validez", emp.get("dias_validez", 30))
    valido_hasta = _fecha_hasta(dias_validez)

    _lb = logo_bytes or _cargar_logo_corporativo()
    palette = _extraer_paleta_logo(_lb)
    P = _colores(palette)
    E = _estilos(P)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
        leftMargin=1.4*cm, rightMargin=1.4*cm,
        topMargin=1.0*cm, bottomMargin=1.2*cm,
        title=f"Cotizacion AIU {numero}")

    r = resultado
    story = []

    story.append(_header_bloque(E, P, "COTIZACIÓN AIU", numero, fecha_str, emp, _lb, valido_hasta))
    story.append(Spacer(1, 5))

    # Badge tipo
    story.append(Table([[
        Paragraph(f"Fecha: {date.today().strftime('%d/%m/%Y')}  ·  Válida hasta: {valido_hasta}  ·  Tipo: AIU — Administración, Imprevistos y Utilidad",
            ParagraphStyle("badge", leading=9, fontSize=6.5, fontName="Helvetica", textColor=P["gray"]))
    ]], colWidths=[17*cm],
        style=TableStyle([("BACKGROUND",(0,0),(-1,-1),P["ultralight"]),
            ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),("LEFTPADDING",(0,0),(-1,-1),10)])
    ))
    story.append(Spacer(1, 5))

    # Cliente
    cliente_nombre = r.get("_estado_guardado", {}).get("nombre_cliente", r.get("nombre_cliente",""))
    datos_filas = []
    if cliente_nombre:
        datos_filas.append(("Para", cliente_nombre))
    datos_filas += [
        ("Ciudad", emp.get("ciudad","Barranquilla")),
        ("Tipo de contrato", "Licitación / Proyecto Constructora — Estructura AIU"),
        ("Forma de pago", f"{anticipo_pct}% anticipo — {100 - anticipo_pct}% contra acta de entrega"),
        ("Validez / Entrega", f"{dias_validez} días  ·  Entrega estimada: {dias_entrega} días"),
    ]
    story.append(Paragraph("DATOS DEL CONTRATANTE", E["seccion"]))
    story.append(Spacer(1, 3))
    story.append(_tabla_2col(E, P, datos_filas))
    story.append(Spacer(1, 6))

    # ── Ítems del Costo Directo ────────────────────────────────────────────────
    aiu_items = r.get("_estado_guardado", {}).get("aiu_items", [])
    cd = r.get("cd", r.get("costo_total", 0))

    story.append(Paragraph("COSTO DIRECTO (CD) — ÍTEMS DEL CONTRATO", E["seccion"]))
    story.append(Spacer(1, 3))

    hdr_s = ParagraphStyle("th", leading=9, fontSize=7, fontName="Helvetica-Bold", textColor=P["white"])
    cel_s = ParagraphStyle("tc", leading=10, fontSize=7.5, fontName="Helvetica", textColor=P["text"])
    cel_r = ParagraphStyle("tcr",leading=10, fontSize=7.5, fontName="Helvetica", textColor=P["text"], alignment=TA_RIGHT)
    cel_br= ParagraphStyle("tcbr",leading=10,fontSize=7.5, fontName="Helvetica-Bold",textColor=P["text"], alignment=TA_RIGHT)
    cel_b = ParagraphStyle("tcb",leading=10, fontSize=7.5, fontName="Helvetica-Bold",textColor=P["text"])

    cd_filas = [[
        Paragraph("DESCRIPCIÓN", hdr_s),
        Paragraph("UNID.", ParagraphStyle("thc",leading=9,fontSize=7,fontName="Helvetica-Bold",textColor=P["white"],alignment=TA_CENTER)),
        Paragraph("CANT.", ParagraphStyle("thc2",leading=9,fontSize=7,fontName="Helvetica-Bold",textColor=P["white"],alignment=TA_CENTER)),
        Paragraph("P. UNIT.", ParagraphStyle("thr",leading=9,fontSize=7,fontName="Helvetica-Bold",textColor=P["white"],alignment=TA_RIGHT)),
        Paragraph("SUBTOTAL", ParagraphStyle("thr2",leading=9,fontSize=7,fontName="Helvetica-Bold",textColor=P["white"],alignment=TA_RIGHT)),
    ]]

    if aiu_items:
        for it in aiu_items:
            sub_it = it.get("cant",0) * it.get("punit",0)
            cd_filas.append([
                Paragraph(it.get("desc",""), cel_s),
                Paragraph(it.get("und",""), ParagraphStyle("tcc",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["text"],alignment=TA_CENTER)),
                Paragraph(f"{it.get('cant',0):.1f}", ParagraphStyle("tcc2",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["text"],alignment=TA_CENTER)),
                Paragraph(_num(it.get("punit",0)), cel_r),
                Paragraph(_num(sub_it), cel_br),
            ])
    else:
        cd_filas.append([Paragraph("Costo Directo Total", cel_s), "", "", "", Paragraph(_num(cd), cel_br)])

    n_cd_items = len(aiu_items) if aiu_items else 1
    cd_filas.append([Paragraph("COSTO DIRECTO (CD)", cel_b), "", "", "", Paragraph(_num(cd), cel_br)])

    tbl_cd = Table(cd_filas, colWidths=[7.8*cm, 1.2*cm, 1.5*cm, 3*cm, 3.5*cm])
    tbl_cd.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,0),   P["secondary"]),
        ("TOPPADDING",    (0,0),(-1,-1),  4),
        ("BOTTOMPADDING", (0,0),(-1,-1),  4),
        ("LEFTPADDING",   (0,0),(-1,-1),  7),
        ("RIGHTPADDING",  (0,0),(-1,-1),  7),
        ("ROWBACKGROUNDS",(0,1),(-1,-2),  [P["white"], P["ultralight"]]),
        ("BACKGROUND",    (0,-1),(-1,-1), P["light"]),
        ("LINEBELOW",     (0,0),(-1,-1),  0.3, P["light"]),
        ("SPAN",          (0,-1),(3,-1)),
    ]))
    story.append(tbl_cd)
    story.append(Spacer(1, 6))

    # ── Desglose AIU ─────────────────────────────────────────────────────────
    pct_a = r.get("pct_a", 2.0)
    pct_i = r.get("pct_i", 2.0)
    pct_u = r.get("pct_u", 5.0)
    val_a = r.get("val_a", cd * pct_a / 100)
    val_i = r.get("val_i", cd * pct_i / 100)
    val_u = r.get("val_u", cd * pct_u / 100)
    # IVA SOLO sobre Utilidad (U) — norma colombiana
    val_iva = r.get("val_iva", val_u * 0.19)
    logistica = r.get("logistica", 0)
    viaticos  = r.get("viaticos", 0)
    precio_total = r.get("precio_total", cd + val_a + val_i + val_u + val_iva + logistica + viaticos)
    anticipo_val = precio_total * (anticipo_pct / 100)

    story.append(Paragraph("ESTRUCTURA AIU — DESGLOSE DEL PRECIO", E["seccion"]))
    story.append(Spacer(1, 3))

    hdr_aiu = ParagraphStyle("ha", leading=9, fontSize=7, fontName="Helvetica-Bold", textColor=P["white"])
    cel_aiu = ParagraphStyle("ca", leading=10, fontSize=7.5, fontName="Helvetica", textColor=P["text"])
    cel_aiu_r = ParagraphStyle("car",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["text"],alignment=TA_RIGHT)

    filas_aiu = [
        [Paragraph("CONCEPTO", hdr_aiu), Paragraph("BASE", ParagraphStyle("hab",leading=9,fontSize=7,fontName="Helvetica-Bold",textColor=P["white"],alignment=TA_CENTER)),
         Paragraph("%", ParagraphStyle("hap",leading=9,fontSize=7,fontName="Helvetica-Bold",textColor=P["white"],alignment=TA_CENTER)),
         Paragraph("VALOR (COP)", ParagraphStyle("hav",leading=9,fontSize=7,fontName="Helvetica-Bold",textColor=P["white"],alignment=TA_RIGHT))],
        # CD
        [Paragraph("Costo Directo (CD)", cel_aiu),
         Paragraph("—", ParagraphStyle("ca2",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["gray"],alignment=TA_CENTER)),
         Paragraph("100%", ParagraphStyle("ca3",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["gray"],alignment=TA_CENTER)),
         Paragraph(_num(cd), ParagraphStyle("cav",leading=10,fontSize=7.5,fontName="Helvetica-Bold",textColor=P["text"],alignment=TA_RIGHT))],
        # A
        [Paragraph(f"A — Administración", cel_aiu),
         Paragraph("CD", ParagraphStyle("ca2",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["gray"],alignment=TA_CENTER)),
         Paragraph(f"{pct_a:.1f}%", ParagraphStyle("ca3",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["secondary"],alignment=TA_CENTER)),
         Paragraph(_num(val_a), cel_aiu_r)],
        # I
        [Paragraph(f"I — Imprevistos", cel_aiu),
         Paragraph("CD", ParagraphStyle("ca2",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["gray"],alignment=TA_CENTER)),
         Paragraph(f"{pct_i:.1f}%", ParagraphStyle("ca3",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["secondary"],alignment=TA_CENTER)),
         Paragraph(_num(val_i), cel_aiu_r)],
        # U
        [Paragraph(f"U — Utilidad", cel_aiu),
         Paragraph("CD", ParagraphStyle("ca2",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["gray"],alignment=TA_CENTER)),
         Paragraph(f"{pct_u:.1f}%", ParagraphStyle("ca3",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["secondary"],alignment=TA_CENTER)),
         Paragraph(_num(val_u), cel_aiu_r)],
        # IVA sobre U
        [Paragraph("IVA 19% (exclusivo sobre Utilidad U)",
            ParagraphStyle("iva",leading=10,fontSize=7.5,fontName="Helvetica-Oblique",textColor=P["secondary"])),
         Paragraph("U", ParagraphStyle("ca2",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["gray"],alignment=TA_CENTER)),
         Paragraph("19%", ParagraphStyle("ca3",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["secondary"],alignment=TA_CENTER)),
         Paragraph(_num(val_iva), ParagraphStyle("cav2",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["secondary"],alignment=TA_RIGHT))],
    ]
    # Logística y Viáticos (si aplica)
    if logistica > 0:
        filas_aiu.append([Paragraph("Logística y transporte", cel_aiu),
            Paragraph("—",ParagraphStyle("ca2",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["gray"],alignment=TA_CENTER)),
            Paragraph("—",ParagraphStyle("ca3",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["gray"],alignment=TA_CENTER)),
            Paragraph(_num(logistica), cel_aiu_r)])
    if viaticos > 0:
        filas_aiu.append([Paragraph("Viáticos y gastos foráneos", cel_aiu),
            Paragraph("—",ParagraphStyle("ca2",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["gray"],alignment=TA_CENTER)),
            Paragraph("—",ParagraphStyle("ca3",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["gray"],alignment=TA_CENTER)),
            Paragraph(_num(viaticos), cel_aiu_r)])

    # Anticipo
    filas_aiu.append([
        Paragraph(f"ANTICIPO A PAGAR ({anticipo_pct}%)",
            ParagraphStyle("ant",leading=10,fontSize=8,fontName="Helvetica-Bold",textColor=P["accent"])),
        Paragraph("Total", ParagraphStyle("ca2",leading=10,fontSize=7.5,fontName="Helvetica",textColor=P["gray"],alignment=TA_CENTER)),
        Paragraph(f"{anticipo_pct}%", ParagraphStyle("ca3",leading=10,fontSize=7.5,fontName="Helvetica-Bold",textColor=P["accent"],alignment=TA_CENTER)),
        Paragraph(_num(anticipo_val), ParagraphStyle("antv",leading=10,fontSize=8,fontName="Helvetica-Bold",textColor=P["accent"],alignment=TA_RIGHT))
    ])
    # Total
    filas_aiu.append([
        Paragraph("PRECIO TOTAL DEL CONTRATO",
            ParagraphStyle("tot",leading=12,fontSize=9,fontName="Helvetica-Bold",textColor=P["white"])),
        "", "",
        Paragraph(_num(precio_total),
            ParagraphStyle("totv",leading=12,fontSize=9,fontName="Helvetica-Bold",textColor=P["white"],alignment=TA_RIGHT))
    ])

    tbl_aiu = Table(filas_aiu, colWidths=[8.5*cm, 2*cm, 2*cm, 4.5*cm])
    n_aiu = len(filas_aiu)
    tbl_aiu.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),  (-1,0),   P["secondary"]),
        ("TOPPADDING",    (0,0),  (-1,-1),  4),
        ("BOTTOMPADDING", (0,0),  (-1,-1),  4),
        ("LEFTPADDING",   (0,0),  (-1,-1),  7),
        ("RIGHTPADDING",  (0,0),  (-1,-1),  7),
        ("ROWBACKGROUNDS",(0,1),  (-1,-3),  [P["white"], P["ultralight"]]),
        ("BACKGROUND",    (0,-2), (-1,-2),  colors.HexColor("#FFF3D4")),
        ("BACKGROUND",    (0,-1), (-1,-1),  P["primary"]),
        ("LINEABOVE",     (0,-1), (-1,-1),  1.2, P["primary"]),
        ("LINEBELOW",     (0,0),  (-1,-2),  0.3, P["light"]),
        ("SPAN",          (0,-1), (2,-1)),
    ]))
    story.append(tbl_aiu)
    story.append(Spacer(1, 5))

    # Nota IVA AIU
    tbl_nota = Table([[
        Paragraph("■ NOTA TRIBUTARIA AIU",
            ParagraphStyle("nt",leading=9,fontSize=7,fontName="Helvetica-Bold",textColor=P["text"])),
        Paragraph(
            "En contratos bajo estructura AIU, el IVA (19%) aplica exclusivamente sobre la componente "
            "de Utilidad (U), conforme al Art. 3° del Decreto 1372/1992 y conceptos DIAN. "
            "El IVA NO se aplica sobre el Costo Directo (CD) ni sobre Administración (A) o Imprevistos (I). "
            f"Anticipo requerido: {anticipo_pct}% del total al inicio de la obra.",
            E["aviso"])
    ]], colWidths=[3.5*cm, 13.5*cm])
    tbl_nota.setStyle(TableStyle([
        ("BACKGROUND",   (0,0),(-1,-1), P["ultralight"]),
        ("TOPPADDING",   (0,0),(-1,-1), 6),("BOTTOMPADDING",(0,0),(-1,-1),6),
        ("LEFTPADDING",  (0,0),(-1,-1), 8),("RIGHTPADDING", (0,0),(-1,-1),8),
        ("VALIGN",       (0,0),(-1,-1), "TOP"),
        ("LINEABOVE",    (0,0),(-1,0),  0.8, P["secondary"]),
    ]))
    story.append(tbl_nota)
    story.append(Spacer(1, 5))
    story.extend(_footer(E, P, emp.get("nombre",""), fecha_str, numero))

    doc.build(story)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
# CUENTA DE COBRO — 1 PÁGINA, MISMO DISEÑO
# Muestra % de anticipo en la descripción del servicio
# ═══════════════════════════════════════════════════════════════════════════════
def generar_cuenta_cobro(resultado: dict, datos_prestador: dict, datos_pagador: dict,
                          numero: str = None, descripcion_servicio: str = None,
                          logo_bytes: bytes = None, incluir_iva: bool = True) -> bytes:
    if numero is None:
        numero = f"CC-{date.today().strftime('%Y%m%d')}-001"
    fecha_str = _fecha_es()

    es_aiu = resultado.get("tipo_proyecto") == "Licitación AIU"
    precio_base = resultado.get("precio_sugerido", resultado.get("precio_total", 0))
    anticipo_pct = resultado.get("anticipo_pct", datos_prestador.get("anticipo_pct", 60))

    if es_aiu:
        # Para AIU la cuenta de cobro es siempre con IVA calculado sobre U
        precio_base = resultado.get("precio_total", precio_base)
        valor_total = precio_base  # ya incluye IVA sobre U
        iva = resultado.get("val_iva", 0)
        incluir_iva = False  # ya integrado
    else:
        iva = precio_base * 0.19 if incluir_iva else 0.0
        valor_total = precio_base + iva

    valor_anticipo = valor_total * (anticipo_pct / 100)
    valor_saldo    = valor_total - valor_anticipo

    emp = {
        "nombre": datos_prestador.get("nombre",""),
        "nit":    datos_prestador.get("nit", datos_prestador.get("nit_cc","")),
        "ciudad": datos_prestador.get("ciudad", datos_prestador.get("direccion","")),
        "tel":    datos_prestador.get("tel", datos_prestador.get("telefono","")),
        "email":  datos_prestador.get("email",""),
    }

    _lb = logo_bytes or _cargar_logo_corporativo()
    palette = _extraer_paleta_logo(_lb)
    P = _colores(palette)
    E = _estilos(P)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
        leftMargin=1.4*cm, rightMargin=1.4*cm,
        topMargin=1.0*cm, bottomMargin=1.2*cm,
        title=f"Cuenta de Cobro {numero}")

    story = []
    story.append(_header_bloque(E, P, "CUENTA DE COBRO", numero, fecha_str, emp, _lb))
    story.append(Spacer(1, 8))

    # ── Quién cobra ───────────────────────────────────────────────────────────
    story.append(Paragraph("QUIEN COBRA", E["seccion"]))
    story.append(Spacer(1, 3))
    story.append(_tabla_2col(E, P, [
        ("Nombre / Razón Social", datos_prestador.get("nombre","—")),
        ("NIT / CC",              datos_prestador.get("nit_cc", datos_prestador.get("nit","—"))),
        ("Dirección",             datos_prestador.get("direccion", datos_prestador.get("ciudad","—"))),
        ("Teléfono",              datos_prestador.get("telefono", datos_prestador.get("tel","—"))),
    ]))
    story.append(Spacer(1, 7))

    # ── Quién paga ────────────────────────────────────────────────────────────
    story.append(Paragraph("QUIEN PAGA", E["seccion"]))
    story.append(Spacer(1, 3))
    story.append(_tabla_2col(E, P, [
        ("Nombre / Razón Social", datos_pagador.get("nombre","—")),
        ("NIT / CC",              datos_pagador.get("nit","—")),
        ("Dirección",             datos_pagador.get("direccion","—")),
    ]))
    story.append(Spacer(1, 7))

    # ── Descripción del servicio — INCLUYE el % de anticipo ──────────────────
    if descripcion_servicio is None:
        if es_aiu:
            cliente_nombre = resultado.get("_estado_guardado", {}).get("nombre_cliente", "")
            ref_txt = f" para {cliente_nombre}" if cliente_nombre else ""
            descripcion_servicio = (
                f"Cobro correspondiente al {anticipo_pct}% de anticipo acordado en la cotización AIU{ref_txt}. "
                f"Suministro, fabricación e instalación de materiales pétreos según especificaciones del contrato. "
                f"El saldo restante del {100-anticipo_pct}% será exigible contra acta de entrega y recibo a satisfacción."
            )
        else:
            m2    = resultado.get("m2_real", 0)
            tipo  = resultado.get("tipo_proyecto", "proyecto")
            cat   = resultado.get("categoria", "material pétreo")
            ref   = resultado.get("referencia","")
            ref_txt = f" referencia {ref}" if ref else ""
            descripcion_servicio = (
                f"Cobro del {anticipo_pct}% de anticipo acordado en cotización para: "
                f"suministro, fabricación e instalación de {tipo} en {cat}{ref_txt}. "
                f"Área instalada: {m2:.2f} m². "
                f"El saldo del {100-anticipo_pct}% restante será cobrado contra entrega a satisfacción."
            )

    story.append(Paragraph("DESCRIPCIÓN DEL SERVICIO / CONCEPTO", E["seccion"]))
    story.append(Spacer(1, 3))
    t_serv = Table([[Paragraph(descripcion_servicio, E["normal"])]], colWidths=[17*cm])
    t_serv.setStyle(TableStyle([
        ("BACKGROUND",   (0,0),(-1,-1), P["ultralight"]),
        ("TOPPADDING",   (0,0),(-1,-1), 8), ("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("LEFTPADDING",  (0,0),(-1,-1), 10),("RIGHTPADDING", (0,0),(-1,-1),10),
        ("LINEBELOW",    (0,0),(-1,-1), 0.5, P["secondary"]),
    ]))
    story.append(t_serv)
    story.append(Spacer(1, 7))

    # ── Valor del cobro ───────────────────────────────────────────────────────
    valor_letras = _numero_a_letras(int(round(valor_anticipo)))
    cel_s = ParagraphStyle("cc1",leading=11,fontSize=8,fontName="Helvetica",textColor=P["text"])
    cel_r = ParagraphStyle("cc1r",leading=11,fontSize=8,fontName="Helvetica",textColor=P["text"],alignment=TA_RIGHT)
    cel_br= ParagraphStyle("cc1br",leading=11,fontSize=8,fontName="Helvetica-Bold",textColor=P["text"],alignment=TA_RIGHT)
    cel_w = ParagraphStyle("ccw",leading=12,fontSize=9,fontName="Helvetica-Bold",textColor=P["white"])
    cel_wr= ParagraphStyle("ccwr",leading=12,fontSize=9,fontName="Helvetica-Bold",textColor=P["white"],alignment=TA_RIGHT)
    cel_acc= ParagraphStyle("cca",leading=11,fontSize=8,fontName="Helvetica-Bold",textColor=P["accent"])
    cel_accr=ParagraphStyle("ccar",leading=11,fontSize=8,fontName="Helvetica-Bold",textColor=P["accent"],alignment=TA_RIGHT)

    if incluir_iva and not es_aiu:
        filas_val = [
            [Paragraph("Valor total del servicio (sin IVA)", cel_s), Paragraph(_num(precio_base), cel_r)],
            [Paragraph("IVA 19% (Art. 468 E.T.)",
                ParagraphStyle("cciva",leading=11,fontSize=8,fontName="Helvetica",textColor=P["secondary"])),
             Paragraph(_num(iva), ParagraphStyle("ccivar",leading=11,fontSize=8,fontName="Helvetica",textColor=P["secondary"],alignment=TA_RIGHT))],
            [Paragraph("Total de la cotización (IVA incluido)", ParagraphStyle("cct",leading=11,fontSize=8,fontName="Helvetica-Bold",textColor=P["text"])),
             Paragraph(_num(valor_total), cel_br)],
            [Paragraph(f"ANTICIPO A COBRAR ({anticipo_pct}% del total)", cel_acc),
             Paragraph(_num(valor_anticipo), cel_accr)],
            [Paragraph(f"Saldo contra entrega ({100-anticipo_pct}%)",
                ParagraphStyle("ccs",leading=11,fontSize=8,fontName="Helvetica",textColor=P["gray"])),
             Paragraph(_num(valor_saldo), ParagraphStyle("ccsr",leading=11,fontSize=8,fontName="Helvetica",textColor=P["gray"],alignment=TA_RIGHT))],
            [Paragraph("VALOR TOTAL COBRADO EN ESTE DOCUMENTO", cel_w), Paragraph(_num(valor_anticipo), cel_wr)],
        ]
        ts_val = [
            ("BACKGROUND",(0,0),(-1,0),P["ultralight"]),
            ("BACKGROUND",(0,1),(-1,1),P["ultralight"]),
            ("BACKGROUND",(0,2),(-1,2),P["light"]),
            ("BACKGROUND",(0,3),(-1,3),colors.HexColor("#FFF3D4")),
            ("BACKGROUND",(0,4),(-1,4),P["ultralight"]),
            ("BACKGROUND",(0,5),(-1,5),P["primary"]),
            ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
            ("LEFTPADDING",(0,0),(-1,-1),10),("RIGHTPADDING",(0,0),(-1,-1),10),
            ("LINEABOVE",(0,-1),(-1,-1),1.2,P["primary"]),
        ]
    else:
        filas_val = [
            [Paragraph("Valor total de la cotización", ParagraphStyle("cct",leading=11,fontSize=8,fontName="Helvetica-Bold",textColor=P["text"])),
             Paragraph(_num(valor_total), cel_br)],
            [Paragraph(f"ANTICIPO A COBRAR ({anticipo_pct}% del total)", cel_acc),
             Paragraph(_num(valor_anticipo), cel_accr)],
            [Paragraph(f"Saldo contra entrega ({100-anticipo_pct}%)",
                ParagraphStyle("ccs",leading=11,fontSize=8,fontName="Helvetica",textColor=P["gray"])),
             Paragraph(_num(valor_saldo), ParagraphStyle("ccsr",leading=11,fontSize=8,fontName="Helvetica",textColor=P["gray"],alignment=TA_RIGHT))],
            [Paragraph("VALOR TOTAL COBRADO EN ESTE DOCUMENTO", cel_w), Paragraph(_num(valor_anticipo), cel_wr)],
        ]
        ts_val = [
            ("BACKGROUND",(0,0),(-1,0),P["light"]),
            ("BACKGROUND",(0,1),(-1,1),colors.HexColor("#FFF3D4")),
            ("BACKGROUND",(0,2),(-1,2),P["ultralight"]),
            ("BACKGROUND",(0,3),(-1,3),P["primary"]),
            ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
            ("LEFTPADDING",(0,0),(-1,-1),10),("RIGHTPADDING",(0,0),(-1,-1),10),
            ("LINEABOVE",(0,-1),(-1,-1),1.2,P["primary"]),
        ]

    tbl_val = Table(filas_val, colWidths=[12.5*cm, 4.5*cm])
    tbl_val.setStyle(TableStyle(ts_val))
    story.append(Paragraph("VALOR DEL COBRO", E["seccion"]))
    story.append(Spacer(1, 3))
    story.append(tbl_val)

    # Valor en letras (del anticipo)
    story.append(Table(
        [[Paragraph(f"Son: {valor_letras} pesos M/CTE", E["white_s"])]],
        colWidths=[17*cm],
        style=TableStyle([
            ("BACKGROUND",(0,0),(-1,-1),P["primary"]),
            ("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),7),
            ("LEFTPADDING",(0,0),(-1,-1),14),
        ])
    ))
    story.append(Spacer(1, 7))

    # Datos bancarios
    banco_filas = []
    if datos_prestador.get("banco"):
        banco_filas.append(("Banco", datos_prestador["banco"]))
    if datos_prestador.get("cuenta_tipo"):
        banco_filas.append(("Tipo de cuenta", datos_prestador["cuenta_tipo"]))
    if datos_prestador.get("cuenta_numero"):
        banco_filas.append(("N° de cuenta", datos_prestador["cuenta_numero"]))
    if datos_prestador.get("nombre"):
        banco_filas.append(("A nombre de", datos_prestador["nombre"]))
    if banco_filas:
        story.append(Paragraph("DATOS PARA PAGO", E["seccion"]))
        story.append(Spacer(1, 3))
        story.append(_tabla_2col(E, P, banco_filas))
        story.append(Spacer(1, 7))

    # Firmas
    firma = Table([[
        Table([
            [Paragraph("_" * 38, E["normal"])],
            [Paragraph(datos_prestador.get("nombre",""), E["aviso"])],
            [Paragraph("Firma del Prestador", E["aviso"])],
        ]),
        "",
        Table([
            [Paragraph("_" * 33, E["normal"])],
            [Paragraph("", E["aviso"])],
            [Paragraph("Sello / Firma del Pagador", E["aviso"])],
        ]),
    ]], colWidths=[8*cm, 1.5*cm, 7.5*cm])
    firma.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),10),("VALIGN",(0,0),(-1,-1),"BOTTOM")]))
    story.append(firma)
    story.append(Spacer(1, 8))
    story.extend(_footer(E, P, datos_prestador.get("nombre",""), fecha_str, numero))

    doc.build(story)
    return buf.getvalue()


# ── Conversion de número a letras ─────────────────────────────────────────────
def _numero_a_letras(n: int) -> str:
    if n == 0: return "cero"
    unidades = ["","uno","dos","tres","cuatro","cinco","seis","siete","ocho","nueve",
                "diez","once","doce","trece","catorce","quince","dieciséis","diecisiete","dieciocho","diecinueve"]
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
        pre = "un millón" if m == 1 else _menor_mil(m) + " millones"
        return (pre + " " + _numero_a_letras(r)).strip()
    return str(n)
