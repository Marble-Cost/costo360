# generador_pdf.py — CostoMármol v10 · Propuesta Comercial B2B Premium
# MARMOLES COLLANTE & CASTRO LTDA.
#
# ARQUITECTURA v10 (Balance Premium):
#   - Sistema de espaciado jerárquico: _SP_SECCION=10, _SP_BLOQUE=4, _SP_HEADER=3
#   - Tipografía con contraste por nivel: sec=10pt bold, label=9pt bold, body=9pt, nota=8pt
#   - Leading = fontSize + 2 en todos los estilos (respira sin inflar)
#   - Padding por nivel: _PAD_HDR=6, _PAD_DATA=5, _PAD_NOTA=4, _PAD_FIRMA=10
#   - Borde dorado 3pt encima de fila TOTAL — máxima jerarquía visual
#   - KeepTogether SOLO en Resumen Financiero (tabla+letras) y Firma
#   - T&C numerado con leading=12 para escaneo fácil
#   - Cierre de contrato: línea superior 2pt + celdas generosas
#   - Flujo: Encabezado→Cliente→Adicionales→Despiece→Resumen(KT)→Alcance→T&C→Firma(KT)→Footer

import io
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from PIL import Image as PILImage

_BOG = ZoneInfo("America/Bogota")

def _hoy() -> date:
    return datetime.now(_BOG).date()

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle

# ── Ancho maestro del documento ───────────────────────────────────────────────
ancho_util = 16.5 * cm
_AU = ancho_util
_margen_lateral = (letter[0] - _AU) / 2.0

# ── Constantes globales de columnas ──────────────────────────────────────────
COL_2_30_70   = [_AU * 0.301, _AU * 0.699]
COL_2_75_25   = [_AU * 0.753, _AU * 0.247]
COL_2_50_50   = [_AU * 0.50,  _AU * 0.50]
COL_5_STD     = [_AU * 0.06, _AU * 0.38, _AU * 0.20, _AU * 0.20, _AU * 0.16]
COL_ENCAB     = [_AU * 0.588, _AU * 0.412]
COL_FIRMA_CC  = [_AU * 0.482, _AU * 0.090, _AU * 0.428]
COL_FIRMA_CLI = [_AU * 0.314, _AU * 0.686]
COL_AIU_3     = [_AU * 0.633, _AU * 0.121, _AU * 0.247]
COL_AIU_5     = [_AU * 0.470, _AU * 0.078, _AU * 0.090, _AU * 0.181, _AU * 0.181]

# ── Sistema de espaciado jerárquico ──────────────────────────────────────────
_SP_SECCION = 10   # Entre secciones mayores
_SP_BLOQUE  = 4    # Dentro de un bloque
_SP_HEADER  = 3    # Spacer interior del _seccion_header

# ── Sistema de padding por nivel ─────────────────────────────────────────────
_PAD_HDR   = 6    # Cabeceras de tabla (fila 0 con fondo oscuro)
_PAD_DATA  = 5    # Filas de datos
_PAD_NOTA  = 4    # Tablas de notas / avisos
_PAD_FIRMA = 10   # Celdas de firma (altura escribible)

from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Image, KeepTogether, PageBreak,
)
from reportlab.lib.utils import ImageReader
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from calculos import cop

# ── Paleta corporativa B2B ────────────────────────────────────────────────────
_DEFAULT_PALETTE = {
    "header_dark": "#1A252C",
    "primary":     "#0D2137",
    "secondary":   "#1B5FA8",
    "accent":      "#C9A84C",
    "light":       "#D6E8FA",
    "ultralight":  "#F5F8FC",
    "zebra_a":     "#FFFFFF",
    "zebra_b":     "#F2F5F9",
    "total_bg":    "#0D2137",
    "anticipo_bg": "#FFF8E7",
    "gray":        "#6B85A0",
    "text":        "#1C2B3A",
    "white":       "#FFFFFF",
    "terms_text":  "#4A5568",
    "border":      "#C8D8E8",
}

_LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo_cc.jpeg")


# ── Utilidades ────────────────────────────────────────────────────────────────

def _cargar_logo_corporativo():
    try:
        with open(_LOGO_PATH, "rb") as f:
            return f.read()
    except Exception:
        return None


def _extraer_paleta_logo(logo_bytes):
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
        def darken(r, g, b, f=0.25): return (int(r*f), int(g*f), int(b*f))
        def lighten(r, g, b, f=0.88):
            return (min(255,int(r+(255-r)*f)), min(255,int(g+(255-g)*f)), min(255,int(b+(255-b)*f)))
        def to_hex(r, g, b): return f"#{r:02X}{g:02X}{b:02X}"
        pr   = darken(avg_r, avg_g, avg_b, 0.22)
        sec  = darken(avg_r, avg_g, avg_b, 0.50)
        lt   = lighten(avg_r, avg_g, avg_b, 0.82)
        ult  = lighten(avg_r, avg_g, avg_b, 0.94)
        is_cool = avg_b > avg_r and avg_b > avg_g
        accent = "#C9A84C" if is_cool else to_hex(
            min(255, int(avg_b*0.8+100)), min(255, int(avg_g*0.6+80)), min(255, int(avg_r*0.3)))
        pal = _DEFAULT_PALETTE.copy()
        pal.update({
            "header_dark": to_hex(*pr),
            "primary":     to_hex(*pr),
            "secondary":   to_hex(*sec),
            "accent":      accent,
            "light":       to_hex(*lt),
            "ultralight":  to_hex(*ult),
            "total_bg":    to_hex(*pr),
            "text":        to_hex(*darken(avg_r, avg_g, avg_b, 0.16)),
        })
        return pal
    except Exception:
        return _DEFAULT_PALETTE.copy()


def _C(palette):
    return {k: colors.HexColor(v) for k, v in palette.items()}


def _num(valor):
    return f"${int(round(valor)):,}".replace(",", ".")


def _fecha_es():
    f = _hoy()
    meses = ["enero","febrero","marzo","abril","mayo","junio",
             "julio","agosto","septiembre","octubre","noviembre","diciembre"]
    return f"{f.day} de {meses[f.month-1]} de {f.year}"


def _fecha_hasta(dias):
    f = _hoy() + timedelta(days=int(dias))
    return f.strftime("%d/%m/%Y")


def _logo_img(logo_bytes, max_h=1.4*cm):
    if not logo_bytes:
        return None
    try:
        pil_img = PILImage.open(io.BytesIO(logo_bytes))
        _tiene_alpha = (
            pil_img.mode in ("RGBA", "LA") or
            (pil_img.mode == "P" and "transparency" in pil_img.info)
        )
        if _tiene_alpha:
            pil_rgba = pil_img.convert("RGBA")
            fondo_blanco = PILImage.new("RGB", pil_rgba.size, (255, 255, 255))
            fondo_blanco.paste(pil_rgba, mask=pil_rgba.split()[3])
            pil_clean = fondo_blanco
        else:
            pil_clean = pil_img.convert("RGB")
        clean_io = io.BytesIO()
        pil_clean.save(clean_io, format="JPEG", quality=95)
        clean_io.seek(0)
        img = Image(clean_io, width=4.2*cm, height=1.6*cm, kind='proportional')
        ratio = img.imageWidth / img.imageHeight
        img.drawWidth  = max_h * ratio
        img.drawHeight = max_h
        return img
    except Exception:
        return None


# ── Estilos tipográficos — Sistema Premium con contraste por nivel ────────────
# leading = fontSize + 2 en todos los estilos
# NIVEL 1 — Títulos de sección : 10pt bold  / secondary blue
# NIVEL 2 — Labels / subtítulos: 9pt bold
# NIVEL 3 — Cuerpo             : 9pt regular
# NIVEL 4 — Notas / pie        : 8pt

def _estilos(C):
    return {
        # ── Encabezado corporativo ─────────────────────────────────────────────
        "doc_empresa": ParagraphStyle("doc_empresa", fontSize=9, fontName="Helvetica-Bold",
                                       leading=11, textColor=C["white"]),
        "doc_emp_sub": ParagraphStyle("doc_emp_sub", fontSize=7.5, fontName="Helvetica",
                                       leading=10, textColor=colors.HexColor("#B8D4F0")),
        "doc_num":     ParagraphStyle("doc_num", fontSize=14, fontName="Helvetica-Bold",
                                       leading=17, textColor=C["white"], alignment=TA_RIGHT),
        "doc_validez": ParagraphStyle("doc_validez", fontSize=7.5, fontName="Helvetica-Bold",
                                       leading=10, textColor=C["accent"], alignment=TA_RIGHT),

        # ── NIVEL 1: Títulos de sección ───────────────────────────────────────
        "seccion":     ParagraphStyle("seccion", fontSize=10, fontName="Helvetica-Bold",
                                       leading=12, textColor=C["secondary"], letterSpacing=0.8),

        # ── NIVEL 2: Labels / subtítulos ──────────────────────────────────────
        "cell_b":      ParagraphStyle("cell_b", fontSize=9, fontName="Helvetica-Bold",
                                       leading=11, textColor=C["text"]),
        "cell_br":     ParagraphStyle("cell_br", fontSize=9, fontName="Helvetica-Bold",
                                       leading=11, textColor=C["text"], alignment=TA_RIGHT),
        "th":          ParagraphStyle("th", fontSize=9, fontName="Helvetica-Bold",
                                       leading=11, textColor=C["white"]),
        "th_r":        ParagraphStyle("th_r", fontSize=9, fontName="Helvetica-Bold",
                                       leading=11, textColor=C["white"], alignment=TA_RIGHT),
        "th_c":        ParagraphStyle("th_c", fontSize=9, fontName="Helvetica-Bold",
                                       leading=11, textColor=C["white"], alignment=TA_CENTER),
        "subtotal_l":  ParagraphStyle("subtotal_l", fontSize=9, fontName="Helvetica-Bold",
                                       leading=11, textColor=C["text"]),
        "subtotal_v":  ParagraphStyle("subtotal_v", fontSize=9, fontName="Helvetica-Bold",
                                       leading=11, textColor=C["text"], alignment=TA_RIGHT),
        "anticipo_l":  ParagraphStyle("anticipo_l", fontSize=9, fontName="Helvetica-Bold",
                                       leading=11, textColor=C["accent"]),
        "anticipo_v":  ParagraphStyle("anticipo_v", fontSize=9, fontName="Helvetica-Bold",
                                       leading=11, textColor=C["accent"], alignment=TA_RIGHT),

        # ── NIVEL 3: Cuerpo ───────────────────────────────────────────────────
        "cell":        ParagraphStyle("cell", fontSize=9, fontName="Helvetica",
                                       leading=11, textColor=C["text"]),
        "cell_r":      ParagraphStyle("cell_r", fontSize=9, fontName="Helvetica",
                                       leading=11, textColor=C["text"], alignment=TA_RIGHT),
        "cell_c":      ParagraphStyle("cell_c", fontSize=9, fontName="Helvetica",
                                       leading=11, textColor=C["text"], alignment=TA_CENTER),
        "iva_l":       ParagraphStyle("iva_l", fontSize=9, fontName="Helvetica-Oblique",
                                       leading=11, textColor=C["secondary"]),
        "iva_v":       ParagraphStyle("iva_v", fontSize=9, fontName="Helvetica-Oblique",
                                       leading=11, textColor=C["secondary"], alignment=TA_RIGHT),

        # ── TOTAL: máxima jerarquía visual ────────────────────────────────────
        "total_label": ParagraphStyle("total_label", fontSize=11, fontName="Helvetica-Bold",
                                       leading=14, textColor=C["white"]),
        "total_val":   ParagraphStyle("total_val", fontSize=11, fontName="Helvetica-Bold",
                                       leading=14, textColor=C["white"], alignment=TA_RIGHT),
        "letras":      ParagraphStyle("letras", fontSize=8, fontName="Helvetica-Bold",
                                       leading=10, textColor=C["white"]),

        # ── NIVEL 4: Notas / pie ──────────────────────────────────────────────
        "footer":      ParagraphStyle("footer", fontSize=6.5, fontName="Helvetica",
                                       leading=8, textColor=C["gray"], alignment=TA_CENTER),
        "aviso":       ParagraphStyle("aviso", fontSize=8, fontName="Helvetica",
                                       leading=10, textColor=C["text"]),
        "nota_legal":  ParagraphStyle("nota_legal", fontSize=8, fontName="Helvetica-Oblique",
                                       leading=10, textColor=colors.HexColor("#4A5568")),
        "terms_title": ParagraphStyle("terms_title", fontSize=9, fontName="Helvetica-Bold",
                                       leading=11, textColor=colors.HexColor("#0D2137")),
        "terms_body":  ParagraphStyle("terms_body", fontSize=8.5, fontName="Helvetica",
                                       leading=12, textColor=colors.HexColor("#4A5568")),
        "inc_hdr":     ParagraphStyle("inc_hdr", fontSize=8.5, fontName="Helvetica-Bold",
                                       leading=11, textColor=C["white"]),
        "inc_row":     ParagraphStyle("inc_row", fontSize=8.5, fontName="Helvetica",
                                       leading=11, textColor=C["text"],
                                       leftIndent=14, firstLineIndent=-14),
        "white_s":     ParagraphStyle("white_s", fontSize=8.5, fontName="Helvetica",
                                       leading=11, textColor=C["white"]),
        "accent_s":    ParagraphStyle("accent_s", fontSize=8.5, fontName="Helvetica-Bold",
                                       leading=11, textColor=C["accent"]),
        "firma_titulo":ParagraphStyle("firma_titulo", fontSize=9, fontName="Helvetica-Bold",
                                       leading=11, textColor=colors.HexColor("#1C2B3A")),
        "firma_campo": ParagraphStyle("firma_campo", fontSize=8.5, fontName="Helvetica",
                                       leading=11, textColor=colors.HexColor("#1C2B3A")),

        # ── Matriz inclusiones/exclusiones ────────────────────────────────────
        "matriz_inc":     ParagraphStyle("matriz_inc", fontSize=8.5, fontName="Helvetica-Bold",
                                          leading=11, textColor=colors.HexColor("#FFFFFF"),
                                          alignment=TA_CENTER, spaceAfter=0),
        "matriz_exc":     ParagraphStyle("matriz_exc", fontSize=8.5, fontName="Helvetica-Bold",
                                          leading=11, textColor=colors.HexColor("#FFFFFF"),
                                          alignment=TA_CENTER, spaceAfter=0),
        "matriz_inc_row": ParagraphStyle("matriz_inc_row", fontSize=8.5, fontName="Helvetica",
                                          leading=11, textColor=colors.HexColor("#1C2B3A"),
                                          leftIndent=0, firstLineIndent=0, spaceAfter=0),
        "matriz_exc_row": ParagraphStyle("matriz_exc_row", fontSize=8.5, fontName="Helvetica",
                                          leading=11, textColor=colors.HexColor("#1C2B3A"),
                                          leftIndent=0, firstLineIndent=0, spaceAfter=0),
    }


# ── Bloques reutilizables ─────────────────────────────────────────────────────

def _seccion_header(titulo, E):
    return [
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#C8D8E8")),
        Spacer(1, _SP_HEADER),
        Paragraph(titulo.upper(), E["seccion"]),
        Spacer(1, _SP_HEADER),
    ]


def _encabezado_doc(E, C, doc_type, numero, fecha_str, empresa_info, logo_bytes, valido_hasta=None):
    emp = empresa_info or {}
    _lb = logo_bytes or _cargar_logo_corporativo()
    logo_img = _logo_img(_lb, max_h=1.4*cm)

    izq = []
    if logo_img:
        izq.append(logo_img)
        izq.append(Spacer(1, 4))
    izq.append(Paragraph(emp.get("nombre", "MARMOLES COLLANTE & CASTRO LTDA."), E["doc_empresa"]))
    if emp.get("nit"):
        izq.append(Paragraph(emp["nit"], E["doc_emp_sub"]))
    if emp.get("tel") and emp.get("email"):
        izq.append(Paragraph(f"{emp['tel']}  ·  {emp['email']}", E["doc_emp_sub"]))
    elif emp.get("tel"):
        izq.append(Paragraph(emp["tel"], E["doc_emp_sub"]))
    if emp.get("ciudad"):
        izq.append(Paragraph(emp["ciudad"], E["doc_emp_sub"]))

    der = [
        Paragraph(doc_type,
            ParagraphStyle("dt", fontSize=7.5, fontName="Helvetica-Bold",
                           leading=10, textColor=C["accent"], alignment=TA_RIGHT)),
        Spacer(1, 4),
        Paragraph(f"<b>{numero}</b>", E["doc_num"]),
        Spacer(1, 3),
        Paragraph(fecha_str,
            ParagraphStyle("fch", fontSize=7.5, fontName="Helvetica",
                           leading=10, textColor=colors.HexColor("#B8D4F0"), alignment=TA_RIGHT)),
    ]
    if emp.get("email"):
        der.append(Paragraph(emp["email"],
            ParagraphStyle("em2", fontSize=6.5, fontName="Helvetica",
                           leading=9, textColor=colors.HexColor("#B8D4F0"), alignment=TA_RIGHT)))
    if valido_hasta:
        der.append(Spacer(1, 4))
        der.append(Paragraph(f"Válida hasta: {valido_hasta}", E["doc_validez"]))

    tbl = Table([[izq, der]], colWidths=COL_ENCAB)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), C["primary"]),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("TOPPADDING",    (0,0), (-1,-1), 14),
        ("BOTTOMPADDING", (0,0), (-1,-1), 14),
        ("LEFTPADDING",   (0,0), (0,-1),  16),
        ("RIGHTPADDING",  (-1,0),(-1,-1), 16),
        ("LEFTPADDING",   (-1,0),(-1,-1), 10),
        ("LINEBELOW",     (0,0), (-1,-1), 3.0, C["accent"]),
    ]))
    return tbl


def _tabla_datos_cliente(E, C, filas_datos):
    _lbl_style = ParagraphStyle("_lbl_dc", fontSize=8.5, fontName="Helvetica",
                                 leading=11, textColor=C["gray"])
    rows = []
    for label, valor in filas_datos:
        rows.append([Paragraph(label, _lbl_style), Paragraph(f"<b>{valor}</b>", E["cell_b"])])
    tbl = Table(rows, colWidths=COL_2_30_70, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [C["zebra_a"], C["zebra_b"]]),
        ("TOPPADDING",     (0,0), (-1,-1), _PAD_DATA),
        ("BOTTOMPADDING",  (0,0), (-1,-1), _PAD_DATA),
        ("LEFTPADDING",    (0,0), (-1,-1), 10),
        ("RIGHTPADDING",   (0,0), (-1,-1), 10),
        ("LINEBELOW",      (0,0), (-1,-1), 0.3, C["border"]),
        ("BOX",            (0,0), (-1,-1), 0.5, C["border"]),
    ]))
    return tbl


def _tabla_2col(E, C, filas_datos):
    return _tabla_datos_cliente(E, C, filas_datos)


def _footer_doc(E, C, emp_nombre, fecha_str, numero="", ciudad="Barranquilla"):
    _ciudad_str = ciudad.strip() if ciudad and ciudad.strip() else "Barranquilla"
    linea = (
        f"MÁRMOLES COLLANTE & CASTRO LTDA.  |  "
        f"Distribuidor Oficial de GRANITOS Y MÁRMOLES S.A.S  |  "
        f"{_ciudad_str}  •  {fecha_str}"
    )
    _footer_style = ParagraphStyle(
        "footer_premium", fontSize=6.5, fontName="Helvetica-Bold",
        leading=8, textColor=colors.HexColor("#4A5568"), alignment=TA_CENTER,
        letterSpacing=0.3,
    )
    return [
        Spacer(1, 8),
        HRFlowable(width="100%", thickness=0.5, color=C["border"]),
        Spacer(1, 4),
        Paragraph(linea, _footer_style),
    ]


# ── Módulo: Despiece Técnico ──────────────────────────────────────────────────

def _seccion_despiece_tecnico(E, C, r, incluir_iva, anticipo_pct, precio_sugerido_total):
    story = []
    story += _seccion_header("Despiece Técnico y Elementos del Proyecto", E)

    piezas = r.get("_estado_guardado", {}).get("piezas", [])
    _cat_mat  = r.get("categoria", "")
    _ref_mat  = r.get("referencia", "")
    _nombres_mat = (f"{_cat_mat} {_ref_mat}".strip()
                    if _ref_mat and _ref_mat.strip()
                    else (_cat_mat.strip() or "Material"))

    hdr = [
        Paragraph("Nº", E["th_c"]),
        Paragraph("ÍTEM", E["th"]),
        Paragraph("CANTIDAD", E["th_c"]),
        Paragraph("PRECIO UNITARIO", E["th_r"]),
        Paragraph("SUBTOTAL", E["th_r"]),
    ]
    filas = [hdr]

    if piezas:
        total_m2 = sum(p.get("ml", 1) * p.get("ancho_custom", 0.60) for p in piezas)
        for idx_p, p in enumerate(piezas, start=1):
            _ml_efectivo = p.get("ml", 1)
            _ml_unit     = p.get("ml_unitario", _ml_efectivo)
            _cantidad    = int(p.get("cantidad", 1))
            _ancho       = float(p.get("ancho_custom", 0.60))
            _m2_calc     = _ml_efectivo * _ancho
            m2_p         = _m2_calc if _m2_calc > 0 else _ml_efectivo * _ancho
            prop         = (m2_p / total_m2) if total_m2 > 0 else (1 / len(piezas))
            precio_p     = precio_sugerido_total * prop
            _tipo_pieza  = p.get("ancho_tipo", "").lower()
            _es_area_p   = any(kw in _tipo_pieza for kw in ("piso", "fachada", "revestimiento"))
            if _es_area_p:
                _cant_unid_str = f"{m2_p:.2f}&nbsp;m²&nbsp;({_cantidad}&nbsp;unid.)"
                _qty_base  = m2_p
            else:
                _cant_unid_str = f"{_ml_efectivo:.2f}&nbsp;ml&nbsp;({_cantidad}&nbsp;unid.)"
                _qty_base  = _ml_efectivo
            pu = precio_p / _qty_base if _qty_base > 0 else 0
            _desc_enriq = f"<b>{p.get('nombre', '—')}</b><br/><font size='7.5' color='#6B85A0'>Material: {_nombres_mat}</font>"
            filas.append([
                Paragraph(str(idx_p),          E["cell_c"]),
                Paragraph(_desc_enriq,         E["cell"]),
                Paragraph(_cant_unid_str,      E["cell_c"]),
                Paragraph(_num(pu),            E["cell_r"]),
                Paragraph(_num(precio_p),      E["cell_br"]),
            ])
    else:
        ref_txt = r.get("referencia", r.get("categoria", ""))
        filas.append([
            Paragraph("1",   E["cell_c"]),
            Paragraph(f"{r.get('tipo_proyecto', 'Proyecto')} — {ref_txt}", E["cell"]),
            Paragraph("1 glb", E["cell_c"]),
            Paragraph(_num(precio_sugerido_total), E["cell_r"]),
            Paragraph(_num(precio_sugerido_total), E["cell_br"]),
        ])

    # ── RELLENO DE FILAS (ROW PADDING) PARA DISEÑO B2B ──
    # Garantizamos un mínimo de 8 filas de datos para que la tabla siempre tenga
    # un peso visual elegante, pareciendo un formato corporativo estándar.
    _MIN_FILAS = 8
    _filas_actuales = len(piezas) if piezas else 1
    _filas_faltantes = max(0, _MIN_FILAS - _filas_actuales)

    for _ in range(_filas_faltantes):
        filas.append([
            Paragraph("&nbsp;", E["cell_c"]),
            Paragraph("&nbsp;", E["cell"]),
            Paragraph("&nbsp;", E["cell_c"]),
            Paragraph("&nbsp;", E["cell_r"]),
            Paragraph("&nbsp;", E["cell_br"]),
        ])

    tbl = Table(filas, colWidths=COL_5_STD, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0),  C["header_dark"]),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [C["zebra_a"], C["zebra_b"]]),
        ("TOPPADDING",    (0,0), (-1,0),  _PAD_HDR),
        ("BOTTOMPADDING", (0,0), (-1,0),  _PAD_HDR),
        ("TOPPADDING",    (0,1), (-1,-1), _PAD_DATA),
        ("BOTTOMPADDING", (0,1), (-1,-1), _PAD_DATA),
        ("LEFTPADDING",   (0,0), (-1,-1), 4),
        ("RIGHTPADDING",  (0,0), (-1,-1), 4),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("LINEBELOW",     (0,0), (-1,-1), 0.3, C["border"]),
        ("BOX",           (0,0), (-1,-1), 0.5, C["border"]),
    ]))
    story.append(tbl)

    nota_atodocosto = "Nota: Incluye el suministro del material pétreo, mano de obra especializada de corte e instalación, insumos técnicos, herramientas y logística de transporte."
    story.append(Table(
        [[Paragraph(nota_atodocosto, E["nota_legal"])]],
        colWidths=[_AU],
        style=TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#F7F9FC")),
            ("LEFTPADDING",   (0,0),(-1,-1), 10), ("RIGHTPADDING",(0,0),(-1,-1),10),
            ("TOPPADDING",    (0,0),(-1,-1), _PAD_NOTA), ("BOTTOMPADDING",(0,0),(-1,-1),_PAD_NOTA),
            ("LINEABOVE",     (0,0),(-1, 0), 0.5, colors.HexColor("#6B85A0")),
            ("BOX",           (0,0),(-1,-1), 0.4, colors.HexColor("#C8D8E8")),
        ])
    ))
    return story


def _seccion_adicionales_alcance(E, C, adicionales_detalle, c7_adicionales):
    story = []
    story += _seccion_header("Alcance del Proyecto: Servicios Adicionales", E)

    _s_hdr    = ParagraphStyle("aaic_hdr", fontSize=9, fontName="Helvetica-Bold",
                                leading=11, textColor=colors.HexColor("#0D2137"))
    _s_item   = ParagraphStyle("aaic_item", fontSize=9, fontName="Helvetica",
                                leading=11, textColor=colors.HexColor("#1C2B3A"))
    _s_val    = ParagraphStyle("aaic_val",  fontSize=9, fontName="Helvetica-Bold",
                                leading=11, textColor=colors.HexColor("#1B5FA8"), alignment=TA_RIGHT)
    _s_tot_l  = ParagraphStyle("aaic_tot_l", fontSize=9, fontName="Helvetica-Bold",
                                leading=11, textColor=colors.HexColor("#1B5FA8"))
    _s_tot_v  = ParagraphStyle("aaic_tot_v", fontSize=9, fontName="Helvetica-Bold",
                                leading=11, textColor=colors.HexColor("#1B5FA8"), alignment=TA_RIGHT)
    _s_vhdr   = ParagraphStyle("aaic_vhdr", fontSize=9, fontName="Helvetica-Bold",
                                leading=11, textColor=colors.HexColor("#0D2137"), alignment=TA_RIGHT)
    _s_vacio  = ParagraphStyle("aaic_vacio", fontSize=9, fontName="Helvetica-Oblique",
                                leading=11, textColor=colors.HexColor("#6B85A0"))

    filas_aa = [[Paragraph("SERVICIO / ELEMENTO ADICIONAL", _s_hdr), Paragraph("VALOR", _s_vhdr)]]
    _items_con_valor = []
    if adicionales_detalle:
        for item in adicionales_detalle:
            nombre = (item.get("concepto") or item.get("nombre") or "").strip() or "Servicio adicional"
            valor = float(item.get("valor", 0) or 0)
            if valor > 0:
                _items_con_valor.append((nombre, valor))
                filas_aa.append([Paragraph(f"✔  {nombre}", _s_item), Paragraph(_num(valor), _s_val)])

    if not _items_con_valor:
        filas_aa.append([Paragraph("No se seleccionaron servicios adicionales.", _s_vacio), Paragraph("—", _s_val)])
        c7_adicionales = 0.0
    if _items_con_valor and c7_adicionales and c7_adicionales > 0:
        filas_aa.append([Paragraph("Total servicios adicionales", _s_tot_l), Paragraph(_num(c7_adicionales), _s_tot_v)])

    tbl_aa = Table(filas_aa, colWidths=COL_2_75_25)
    tbl_aa.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0),  (-1, 0),  colors.HexColor("#EBF3FB")),
        ("ROWBACKGROUNDS",(0, 1),  (-1,-2),  [colors.HexColor("#F7FAFD"), colors.HexColor("#FFFFFF")]),
        ("BACKGROUND",    (0,-1),  (-1,-1),  colors.HexColor("#EBF3FB")),
        ("LINEABOVE",     (0, 0),  (-1, 0),  1.5, colors.HexColor("#1B5FA8")),
        ("LINEBELOW",     (0,-1),  (-1,-1),  1.5, colors.HexColor("#1B5FA8")),
        ("LINEBELOW",     (0, 0),  (-1,-2),  0.3, colors.HexColor("#C8D8E8")),
        ("TOPPADDING",    (0, 0),  (-1, 0),  _PAD_HDR), ("BOTTOMPADDING",(0,0),(-1,0),_PAD_HDR),
        ("TOPPADDING",    (0, 1),  (-1,-1),  _PAD_DATA), ("BOTTOMPADDING",(0,1),(-1,-1),_PAD_DATA),
        ("LEFTPADDING",   (0, 0),  (-1,-1),  10), ("RIGHTPADDING",(0,0),(-1,-1),10),
        ("VALIGN",        (0, 0),  (-1,-1),  "MIDDLE"),
        ("BOX",           (0, 0),  (-1,-1),  0.5, colors.HexColor("#C8D8E8")),
    ]))
    story.append(tbl_aa)
    return story


def _seccion_resumen_financiero(E, C, precio_sugerido_total, anticipo_pct, incluir_iva,
                                 c7_adicionales=0.0, adicionales_detalle=None):
    story = []
    story += _seccion_header("Resumen Financiero", E)

    _s_adic_l = ParagraphStyle("adic_l", fontSize=9, fontName="Helvetica-Bold",
                                leading=11, textColor=colors.HexColor("#1B5FA8"))
    _s_adic_v = ParagraphStyle("adic_v", fontSize=9, fontName="Helvetica-Bold",
                                leading=11, textColor=colors.HexColor("#1B5FA8"), alignment=TA_RIGHT)
    _tiene_adicionales = c7_adicionales and c7_adicionales > 0
    filas_fin = []

    if incluir_iva:
        iva_val          = precio_sugerido_total * 0.19
        precio_final_doc = precio_sugerido_total + iva_val
        anticipo_val     = precio_final_doc * (anticipo_pct / 100)
        saldo_val        = precio_final_doc - anticipo_val

        filas_fin.append([Paragraph("Subtotal", E["cell_b"]), Paragraph(_num(precio_sugerido_total), E["cell_br"])])
        if _tiene_adicionales:
            filas_fin.append([Paragraph("Costos Adicionales", _s_adic_l), Paragraph(_num(c7_adicionales), _s_adic_v)])
        filas_fin.append([Paragraph("IVA 19%", E["iva_l"]), Paragraph(_num(iva_val), E["iva_v"])])
        filas_fin.append([Paragraph(f"ANTICIPO A PAGAR ({anticipo_pct}% del total)", E["anticipo_l"]), Paragraph(_num(anticipo_val), E["anticipo_v"])])
        filas_fin.append([
            Paragraph(f"Saldo contra entrega ({100-anticipo_pct}%)",
                ParagraphStyle("sld",fontSize=8,fontName="Helvetica",leading=10,textColor=C["gray"])),
            Paragraph(_num(saldo_val),
                ParagraphStyle("sldv",fontSize=8,fontName="Helvetica",leading=10,textColor=C["gray"],alignment=TA_RIGHT)),
        ])
        filas_fin.append([Paragraph("TOTAL", E["total_label"]), Paragraph(_num(precio_final_doc), E["total_val"])])
    else:
        precio_final_doc = precio_sugerido_total
        anticipo_val     = precio_final_doc * (anticipo_pct / 100)
        saldo_val        = precio_final_doc - anticipo_val

        filas_fin.append([Paragraph("Subtotal", E["subtotal_l"]), Paragraph(_num(precio_final_doc), E["subtotal_v"])])
        if _tiene_adicionales:
            filas_fin.append([Paragraph("Costos Adicionales", _s_adic_l), Paragraph(_num(c7_adicionales), _s_adic_v)])
        filas_fin.append([Paragraph(f"ANTICIPO A PAGAR ({anticipo_pct}% del total)", E["anticipo_l"]), Paragraph(_num(anticipo_val), E["anticipo_v"])])
        filas_fin.append([
            Paragraph(f"Saldo contra entrega ({100-anticipo_pct}%)",
                ParagraphStyle("sld2",fontSize=8,fontName="Helvetica",leading=10,textColor=C["gray"])),
            Paragraph(_num(saldo_val),
                ParagraphStyle("sldv2",fontSize=8,fontName="Helvetica",leading=10,textColor=C["gray"],alignment=TA_RIGHT)),
        ])
        filas_fin.append([Paragraph("TOTAL (SIN IVA)", E["total_label"]), Paragraph(_num(precio_final_doc), E["total_val"])])

    _n_filas = len(filas_fin)
    idx_ant  = _n_filas - 3
    idx_tot  = _n_filas - 1

    _adic_styles = []
    if _tiene_adicionales:
        _adic_styles = [
            ("BACKGROUND", (0,1),(-1,1), colors.HexColor("#EBF3FB")),
            ("LINEABOVE",  (0,1),(-1,1), 1.2, colors.HexColor("#1B5FA8")),
            ("LINEBELOW",  (0,1),(-1,1), 1.2, colors.HexColor("#1B5FA8")),
        ]

    tbl_fin = Table(filas_fin, colWidths=COL_2_75_25)
    tbl_fin.setStyle(TableStyle(
        _adic_styles + [
        ("ROWBACKGROUNDS", (0,0), (-1,idx_ant-1), [C["zebra_a"], C["zebra_b"]]),
        ("BACKGROUND",     (0,idx_ant), (-1,idx_ant), C["anticipo_bg"]),
        ("BACKGROUND",     (0,idx_tot), (-1,idx_tot), C["total_bg"]),
        ("LINEABOVE",      (0,idx_tot), (-1,idx_tot), 3.0, C["accent"]),
        ("TOPPADDING",     (0,0), (-1,idx_tot-1), _PAD_DATA),
        ("BOTTOMPADDING",  (0,0), (-1,idx_tot-1), _PAD_DATA),
        ("TOPPADDING",     (0,idx_tot), (-1,idx_tot), 8),
        ("BOTTOMPADDING",  (0,idx_tot), (-1,idx_tot), 8),
        ("LEFTPADDING",    (0,0), (-1,-1), 10),
        ("RIGHTPADDING",   (0,0), (-1,-1), 10),
        ("VALIGN",         (0,0), (-1,-1), "MIDDLE"),
        ("BOX",            (0,0), (-1,-1), 1.0, C["border"]),
        ("LINEBELOW",      (0,0), (-1,-2), 0.3, C["border"]),
    ]))
    story.append(tbl_fin)
    return story, precio_final_doc, anticipo_val


# ── Módulo: Matriz Dinámica de Inclusiones / Exclusiones ────────────────────

def _seccion_alcance(E, C, inclusiones=None, exclusiones=None):
    _inc = inclusiones if inclusiones is not None else []
    _exc = exclusiones if exclusiones is not None else []

    # ── Paleta corporativa: azul primario para inclusiones, gris plomo para exclusiones ──
    _INC_HDR = colors.HexColor("#1B5FA8")   # Azul corporativo
    _EXC_HDR = colors.HexColor("#6B85A0")   # Gris plomo elegante (sin rastro de rojo)
    _ZEBRA_INC = colors.HexColor("#F0F5FB") # Azul ultralight para filas pares de inclusión
    _ZEBRA_EXC = colors.HexColor("#F4F6F8") # Gris ultralight para filas pares de exclusión
    _GRID    = colors.HexColor("#D8E4EF")
    _WHITE   = colors.HexColor("#FFFFFF")
    _CONTENT_BG = colors.HexColor("#F8F9FA") # Fondo de contenido: gris casi blanco

    _S_TIT = ParagraphStyle("_alcance_tit", fontSize=9, fontName="Helvetica-Bold",
                             leading=11, textColor=colors.HexColor("#FFFFFF"),
                             alignment=TA_CENTER, spaceAfter=0, spaceBefore=0)
    _S_HDR_INC = ParagraphStyle("_mhdr_inc", fontSize=9, fontName="Helvetica-Bold",
                                 leading=11, textColor=colors.HexColor("#FFFFFF"),
                                 alignment=TA_CENTER, spaceAfter=0, spaceBefore=0)
    _S_HDR_EXC = ParagraphStyle("_mhdr_exc", fontSize=9, fontName="Helvetica-Bold",
                                 leading=11, textColor=colors.HexColor("#FFFFFF"),
                                 alignment=TA_CENTER, spaceAfter=0, spaceBefore=0)
    _S_INC = ParagraphStyle("_minc", fontSize=8.5, fontName="Helvetica",
                             leading=11, textColor=colors.HexColor("#0D2137"),
                             leftIndent=0, firstLineIndent=0, spaceAfter=0, spaceBefore=0, wordWrap="LTR")
    _S_EXC = ParagraphStyle("_mexc", fontSize=8.5, fontName="Helvetica",
                             leading=11, textColor=colors.HexColor("#4A5568"),
                             leftIndent=0, firstLineIndent=0, spaceAfter=0, spaceBefore=0, wordWrap="LTR")
    _S_EMPTY = ParagraphStyle("_mempty", fontSize=8.5, fontName="Helvetica",
                               leading=11, textColor=colors.HexColor("#FFFFFF"),
                               spaceAfter=0, spaceBefore=0)

    _tbl_tit = Table([[Paragraph("ALCANCE DE LA PROPUESTA — INCLUSIONES Y EXCLUSIONES", _S_TIT)]], colWidths=[_AU])
    _tbl_tit.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#1A252C")),
        ("TOPPADDING",    (0,0),(-1,-1), _PAD_HDR), ("BOTTOMPADDING",(0,0),(-1,-1),_PAD_HDR),
        ("LEFTPADDING",   (0,0),(-1,-1), 10), ("RIGHTPADDING",(0,0),(-1,-1),10),
        ("LINEBELOW",     (0,0),(-1,-1), 2.0, colors.HexColor("#C9A84C")),
    ]))

    rows = [[Paragraph("☑  INCLUYE", _S_HDR_INC), Paragraph("☒  NO INCLUYE", _S_HDR_EXC)]]
    _inc_items = _inc if _inc else ["--"]
    _exc_items = _exc if _exc else ["--"]
    for _i in range(max(len(_inc_items), len(_exc_items))):
        _txt_inc = _inc_items[_i] if _i < len(_inc_items) else ""
        _txt_exc = _exc_items[_i] if _i < len(_exc_items) else ""
        rows.append([
            Paragraph(f"☑  {_txt_inc}", _S_INC) if _txt_inc else Paragraph("", _S_EMPTY),
            Paragraph(f"☒  {_txt_exc}", _S_EXC) if _txt_exc else Paragraph("", _S_EMPTY),
        ])

    tbl_al = Table(rows, colWidths=COL_2_50_50, repeatRows=1)
    _ts = [
        # Encabezados con paleta corporativa
        ("BACKGROUND",     (0,0),(0,0),  _INC_HDR),
        ("BACKGROUND",     (1,0),(1,0),  _EXC_HDR),
        ("VALIGN",         (0,0),(-1,-1), "TOP"),
        ("TOPPADDING",     (0,0),(-1, 0), _PAD_HDR), ("BOTTOMPADDING",(0,0),(-1,0),_PAD_HDR),
        ("TOPPADDING",     (0,1),(-1,-1), _PAD_DATA), ("BOTTOMPADDING",(0,1),(-1,-1),_PAD_DATA),
        ("LEFTPADDING",    (0,0),(-1,-1), 10), ("RIGHTPADDING",(0,0),(-1,-1),10),
        ("GRID",           (0,0),(-1,-1), 0.4, _GRID),
        ("BOX",            (0,0),(-1,-1), 1.2, colors.HexColor("#1A252C")),
        ("LINEBEFORE",     (1,0),(1,-1),  0.8, _GRID),
        # Fondo de contenido: gris casi blanco para limpieza visual
        ("ROWBACKGROUNDS", (0,1),(-1,-1), [_CONTENT_BG, _WHITE]),
    ]
    # Zebra diferenciada por columna en filas pares
    for _ri in range(1, len(rows)):
        if _ri % 2 == 0:
            _ts.append(("BACKGROUND", (0,_ri),(0,_ri), _ZEBRA_INC))
            _ts.append(("BACKGROUND", (1,_ri),(1,_ri), _ZEBRA_EXC))
    tbl_al.setStyle(TableStyle(_ts))

    # ── BLINDAJE ABSOLUTO CONTRA SALTOS DE PÁGINA ──
    tbl_maestra = Table(
        [[_tbl_tit], [Spacer(1, _SP_BLOQUE)], [tbl_al]],
        colWidths=[_AU],
        splitByRow=0
    )
    tbl_maestra.setStyle(TableStyle([
        ("LEFTPADDING",   (0,0), (-1,-1), 0),
        ("RIGHTPADDING",  (0,0), (-1,-1), 0),
        ("TOPPADDING",    (0,0), (-1,-1), 0),
        ("BOTTOMPADDING", (0,0), (-1,-1), 0),
    ]))

    return [tbl_maestra]


# ── Módulo: Términos y Condiciones ────────────────────────────────────────────

def _seccion_terminos(E, C, nota_iva, anticipo_pct):
    story = []
    story += _seccion_header("Términos y Condiciones Comerciales", E)

    _titulo_tc = ParagraphStyle("tc_titulo", fontSize=9, fontName="Helvetica-Bold",
                                 leading=11, textColor=colors.HexColor("#0D2137"), spaceAfter=6)
    # leading=12 para mayor escaneo visual
    _viñeta_tc = ParagraphStyle("tc_viñeta", fontSize=8.5, fontName="Helvetica",
                                 leading=12, textColor=colors.HexColor("#4A5568"),
                                 leftIndent=14, firstLineIndent=-10, spaceAfter=5)

    condiciones_items = [
        nota_iva.strip(),
        "Esta propuesta abarca exclusivamente los materiales, servicios y alcances detallados "
        "en la sección de Inclusiones. Cualquier requerimiento adicional, modificación de diseño "
        "posterior a la rectificación de medidas, o trabajo no especificado en este documento "
        "será considerado un servicio extra y requerirá una recotización y aprobación previa.",
        f"El inicio de la obra está condicionado al pago del anticipo del {anticipo_pct}% del valor total.",
        "Los precios cotizados son válidos durante el período indicado en el encabezado. "
        "El prestador se reserva el derecho de ajustar precios por variación superior al 5% "
        "en los materiales durante el período de validez.",
        "Barranquilla, Colombia.",
    ]

    # Sin KeepTogether — flujo natural
    for i, item in enumerate(condiciones_items, start=1):
        story.append(Paragraph(f"{i}.  {item}", _viñeta_tc))
    return story


def _bloque_firma_cliente(E, C):
    """
    Bloque ACEPTADO Y APROBADO POR EL CLIENTE rediseñado.
    Encabezado azul + cuatro campos en dos columnas simétricas con borde.
    """
    _GAP   = 10
    _MITAD = (_AU - _GAP) / 2.0
    _st_lbl = E["firma_campo"]
    _st_tit = E["firma_titulo"]
    _st_lin = ParagraphStyle("_fl", fontSize=8.5, fontName="Helvetica",
                              leading=11, textColor=colors.HexColor("#1C2B3A"))
    _linea  = "_" * 32

    tit_row = Table(
        [[Paragraph("ACEPTADO Y APROBADO POR EL CLIENTE", _st_tit)]],
        colWidths=[_AU],
    )
    tit_row.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#EEF4FB")),
        ("LINEABOVE",     (0,0),(-1, 0), 2.0, colors.HexColor("#1B5FA8")),
        ("TOPPADDING",    (0,0),(-1,-1), 9),
        ("BOTTOMPADDING", (0,0),(-1,-1), 9),
        ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ("RIGHTPADDING",  (0,0),(-1,-1), 10),
        ("BOX",           (0,0),(-1,-1), 0.5, colors.HexColor("#C8D8E8")),
    ]))

    def _campo(etiqueta):
        t = Table(
            [[Paragraph(etiqueta, _st_lbl), Paragraph(_linea, _st_lin)]],
            colWidths=[_MITAD * 0.42, _MITAD * 0.58],
        )
        t.setStyle(TableStyle([
            ("TOPPADDING",    (0,0),(-1,-1), _PAD_FIRMA),
            ("BOTTOMPADDING", (0,0),(-1,-1), _PAD_FIRMA),
            ("LEFTPADDING",   (0,0),(-1,-1), 0),
            ("RIGHTPADDING",  (0,0),(-1,-1), 0),
            ("VALIGN",        (0,0),(-1,-1), "BOTTOM"),
        ]))
        return t

    campos_row = Table(
        [
            [_campo("Firma:"),     _campo("Nombre / Razon Social:")],
            [_campo("C.C. / NIT:"), _campo("Fecha de aprobacion:")],
        ],
        colWidths=[_MITAD, _MITAD],
    )
    campos_row.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#FAFCFF")),
        ("BOX",           (0,0),(-1,-1), 0.5, colors.HexColor("#C8D8E8")),
        ("LINEBELOW",     (0,0),(-1, 0), 0.5, colors.HexColor("#C8D8E8")),
        ("LINEBELOW",     (0,1),(-1,-1), 0.3, colors.HexColor("#E0E8F0")),
        ("LINEBEFORE",    (1,0),( 1,-1), 0.5, colors.HexColor("#C8D8E8")),
        ("TOPPADDING",    (0,0),(-1,-1), 2),
        ("BOTTOMPADDING", (0,0),(-1,-1), 2),
        ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ("RIGHTPADDING",  (0,0),(-1,-1), 10),
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
    ]))

    return [Spacer(1, _SP_SECCION), KeepTogether([tit_row, campos_row])]


# ══════════════════════════════════════════════════════════════════════════════
# COTIZACIÓN DIRECTA
# ══════════════════════════════════════════════════════════════════════════════

def generar_pdf_cotizacion(resultado, numero=None, empresa_info=None,
                            logo_bytes=None, incluir_iva=True,
                            inclusiones=None, exclusiones=None):
    if numero is None:
        numero = f"COT-{_hoy().strftime('%Y%m%d')}-001"
    fecha_str = _fecha_es()
    emp = empresa_info or {}

    anticipo_pct  = resultado.get("anticipo_pct", emp.get("anticipo_pct", 60))
    dias_entrega  = resultado.get("dias_entrega", emp.get("dias_entrega", 10))
    dias_validez  = resultado.get("dias_validez", emp.get("dias_validez", 30))
    valido_hasta  = _fecha_hasta(dias_validez)

    _lb = logo_bytes or _cargar_logo_corporativo()
    palette = _extraer_paleta_logo(_lb)
    C = _C(palette)
    E = _estilos(C)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
        leftMargin=_margen_lateral, rightMargin=_margen_lateral,
        topMargin=1.0*cm,  bottomMargin=1.2*cm,
        title=f"Propuesta Comercial {numero}")

    r = resultado
    _c7_adicionales = float(r.get("c7_adicionales", 0) or 0)
    _adicionales_detalle = []
    _estado_g = r.get("_estado_guardado", {})
    if _c7_adicionales > 0 and _estado_g.get("adicionales_activos"):
        from parametros import ADICIONALES, ETAPAS_OBRA
        _cantidades_add = _estado_g.get("cantidades_add", [])
        _etapa_r        = _estado_g.get("etapa_label", "")
        _etapa_val = ETAPAS_OBRA.get(_etapa_r, list(ETAPAS_OBRA.values())[0])
        _adic_lista = _estado_g.get("adicionales_lista", ADICIONALES)
        for i, _ad in enumerate(_adic_lista):
            _cant = float(_cantidades_add[i]) if i < len(_cantidades_add) else 0.0
            if _cant > 0:
                _precio_unit = _ad.get(_etapa_val, 0)
                _valor = _cant * _precio_unit
                if _valor > 0:
                    _adicionales_detalle.append({"concepto": _ad.get("concepto", "—"), "valor": _valor})

    story = []

    # ① ENCABEZADO
    story.append(_encabezado_doc(E, C, "PROPUESTA COMERCIAL", numero, fecha_str, emp, _lb, valido_hasta))
    story.append(Spacer(1, 8))
    story.append(Table([[Paragraph(
        f"Fecha: {_hoy().strftime('%d/%m/%Y')}  ·  Válida hasta: {valido_hasta}",
        ParagraphStyle("badge",fontSize=7,fontName="Helvetica",leading=9,textColor=C["gray"])
    )]], colWidths=[_AU], style=TableStyle([
        ("BACKGROUND",  (0,0),(-1,-1), C["ultralight"]),
        ("TOPPADDING",  (0,0),(-1,-1), 5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("LEFTPADDING", (0,0),(-1,-1), 10),
        ("LINEABOVE",   (0,0),(-1, 0), 0.5, C["secondary"]),
    ])))
    story.append(Spacer(1, _SP_SECCION))

    # ② DATOS DEL CLIENTE
    story += _seccion_header("Datos del Cliente y Condiciones", E)
    datos_filas = []

    # Cliente siempre visible — nunca oculto
    datos_filas.append(("Cliente / Atención a", r.get("nombre_cliente") or "A quien pueda interesar / Por definir"))

    # Contacto: solo si existe teléfono o email
    _tel_cli   = (r.get("telefono_cliente") or "").strip()
    _email_cli = (r.get("email_cliente") or "").strip()
    if _tel_cli or _email_cli:
        _contacto_str = "  ·  ".join(filter(None, [_tel_cli, _email_cli]))
        datos_filas.append(("Contacto", _contacto_str))

    # Proyecto — sin redundancia
    _piezas_doc    = _estado_g.get("piezas", [])
    _tipo_proy     = (r.get("tipo_proyecto") or "—").strip()
    if _piezas_doc:
        _nombres_piezas = ", ".join(p.get("nombre", "—") for p in _piezas_doc)
        # Solo concatena si el tipo de proyecto NO está ya contenido en los nombres
        if _tipo_proy.lower() in _nombres_piezas.lower():
            _resumen_proy = _nombres_piezas
        else:
            _resumen_proy = f"{_tipo_proy} — Incluye: {_nombres_piezas}"
        if len(_resumen_proy) > 85:
            _resumen_proy = _resumen_proy[:82] + "…"
    else:
        _resumen_proy = _tipo_proy

    # Ubicación real del proyecto, no la de la empresa
    _ciudad_proy = (r.get("ciudad_proyecto") or "").strip() or "Área Metropolitana"

    datos_filas += [
        ("Ubicación del Proyecto", _ciudad_proy),
        ("Proyecto",               _resumen_proy),
        ("Forma de pago",          f"{anticipo_pct}% anticipo  ·  {100-anticipo_pct}% contra entrega"),
        ("Condiciones",            f"Validez: {dias_validez} días  ·  Entrega estimada: {dias_entrega} días"),
    ]
    story.append(_tabla_datos_cliente(E, C, datos_filas))
    story.append(Spacer(1, _SP_SECCION))

    # ③ SERVICIOS ADICIONALES (si aplica)
    if _c7_adicionales > 0:
        story += _seccion_adicionales_alcance(E, C, _adicionales_detalle, _c7_adicionales)
        story.append(Spacer(1, _SP_SECCION))

    # ④ DESPIECE TÉCNICO
    precio_sugerido_total = r.get("precio_sugerido", 0)
    story += _seccion_despiece_tecnico(E, C, r, incluir_iva, anticipo_pct, precio_sugerido_total)
    story.append(Spacer(1, _SP_SECCION))

    # ⑤ RESUMEN FINANCIERO — KeepTogether protege tabla + letras
    fin_story, precio_final_doc, anticipo_val = _seccion_resumen_financiero(
        E, C, precio_sugerido_total, anticipo_pct, incluir_iva,
        c7_adicionales=_c7_adicionales, adicionales_detalle=_adicionales_detalle)
    valor_letras = _numero_a_letras(int(round(precio_final_doc)))
    _tbl_letras = Table([[Paragraph(f"Son: {valor_letras}", E["letras"])]],
        colWidths=[_AU], style=TableStyle([
            ("BACKGROUND",   (0,0),(-1,-1), C["primary"]),
            ("TOPPADDING",   (0,0),(-1,-1), 4), ("BOTTOMPADDING",(0,0),(-1,-1),6),
            ("LEFTPADDING",  (0,0),(-1,-1), 10),
        ]))
    story.append(KeepTogether(fin_story + [_tbl_letras]))
    story.append(Spacer(1, _SP_SECCION))

    # ⑥ ALCANCE — sin KeepTogether
    story += _seccion_alcance(E, C, inclusiones=inclusiones, exclusiones=exclusiones)
    story.append(Spacer(1, _SP_SECCION))

    # ⑦ TÉRMINOS Y CONDICIONES — sin KeepTogether
    nota_iva = (
        "Propuesta con IVA del 19% (Art. 468 E.T.) — Responsable de IVA — Régimen Común. "
        if incluir_iva else
        "Propuesta sin IVA — Régimen Simplificado (Art. 499 E.T.). "
    )
    story += _seccion_terminos(E, C, nota_iva, anticipo_pct)
    story.append(Spacer(1, _SP_BLOQUE))

    # ⑧ FIRMA — KeepTogether conservado
    story += _bloque_firma_cliente(E, C)

    # ⑨ FOOTER
    story += _footer_doc(E, C, emp.get("nombre",""), fecha_str, numero, ciudad=emp.get("ciudad","Barranquilla"))

    doc.build(story)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# COTIZACIÓN AIU
# ══════════════════════════════════════════════════════════════════════════════

def generar_pdf_cotizacion_aiu(resultado, numero=None, empresa_info=None, logo_bytes=None, incluir_iva=True, inclusiones=None, exclusiones=None):
    if numero is None:
        numero = f"COT-AIU-{_hoy().strftime('%Y%m%d')}-001"
    fecha_str = _fecha_es()
    emp = empresa_info or {}

    anticipo_pct = resultado.get("anticipo_pct", emp.get("anticipo_pct", 60))
    dias_entrega = resultado.get("dias_entrega", emp.get("dias_entrega", 10))
    dias_validez = resultado.get("dias_validez", emp.get("dias_validez", 30))
    valido_hasta = _fecha_hasta(dias_validez)

    _lb = logo_bytes or _cargar_logo_corporativo()
    palette = _extraer_paleta_logo(_lb)
    C = _C(palette)
    E = _estilos(C)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
        leftMargin=_margen_lateral, rightMargin=_margen_lateral,
        topMargin=1.0*cm,  bottomMargin=1.2*cm,
        title=f"Propuesta AIU {numero}")

    r = resultado
    story = []

    # ① ENCABEZADO
    story.append(_encabezado_doc(E, C, "PROPUESTA AIU — OBRA PUBLICA", numero, fecha_str, emp, _lb, valido_hasta))
    story.append(Spacer(1, 8))
    story.append(Table([[Paragraph(
        f"Fecha: {_hoy().strftime('%d/%m/%Y')}  ·  Válida hasta: {valido_hasta}  ·  "
        "Tipo: AIU — Administración, Imprevistos y Utilidad",
        ParagraphStyle("badge2",fontSize=7,fontName="Helvetica",leading=9,textColor=C["gray"])
    )]], colWidths=[_AU], style=TableStyle([
        ("BACKGROUND",  (0,0),(-1,-1), C["ultralight"]),
        ("TOPPADDING",  (0,0),(-1,-1), 5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("LEFTPADDING", (0,0),(-1,-1), 10),
        ("LINEABOVE",   (0,0),(-1, 0), 0.5, C["secondary"]),
    ])))
    story.append(Spacer(1, _SP_SECCION))

    # ② DATOS DEL CONTRATANTE
    story += _seccion_header("Datos del Contratante", E)
    cliente_nombre = r.get("nombre_cliente") or r.get("_estado_guardado", {}).get("nombre_cliente") or "A quien pueda interesar"
    datos_filas = [
        ("Contratante / Atención a", cliente_nombre),
    ]
    _tel = r.get("telefono_cliente", "")
    _ema = r.get("email_cliente", "")
    if _tel or _ema:
        datos_filas.append(("Contacto", "  ·  ".join(filter(None, [_tel, _ema]))))
    datos_filas += [
        ("Ciudad",           r.get("ciudad_proyecto") or "Área Metropolitana"),
        ("Tipo de contrato", "Licitación / Proyecto Constructora — Estructura AIU"),
        ("Forma de pago",    f"{anticipo_pct}% anticipo  ·  {100-anticipo_pct}% contra acta de entrega"),
        ("Condiciones",      f"Validez: {dias_validez} días  ·  Entrega estimada: {dias_entrega} días"),
    ]
    story.append(_tabla_datos_cliente(E, C, datos_filas))
    story.append(Spacer(1, _SP_SECCION))

    # ③ COSTO DIRECTO
    story += _seccion_header("Costo Directo (CD) — Items del Contrato", E)
    aiu_items = r.get("_estado_guardado", {}).get("aiu_items", [])
    cd = r.get("cd", r.get("costo_total", 0))

    cd_filas = [[
        Paragraph("DESCRIPCION / ITEM", E["th"]), Paragraph("UNID.", E["th_c"]),
        Paragraph("CANT.", E["th_c"]), Paragraph("P. UNIT.", E["th_r"]), Paragraph("SUBTOTAL", E["th_r"]),
    ]]
    if aiu_items:
        for it in aiu_items:
            sub_it = it.get("cant",0) * it.get("punit",0)
            cd_filas.append([
                Paragraph(it.get("desc","—"), E["cell"]),
                Paragraph(it.get("und",""),   E["cell_c"]),
                Paragraph(f"{it.get('cant',0):.1f}", E["cell_c"]),
                Paragraph(_num(it.get("punit",0)), E["cell_r"]),
                Paragraph(_num(sub_it),            E["cell_br"]),
            ])
    else:
        cd_filas.append([
            Paragraph("Costo Directo Total", E["cell"]), Paragraph("glb", E["cell_c"]),
            Paragraph("1", E["cell_c"]), Paragraph(_num(cd), E["cell_r"]), Paragraph(_num(cd), E["cell_br"]),
        ])
    cd_filas.append([
        Paragraph("COSTO DIRECTO (CD)", E["subtotal_l"]),
        Paragraph("", E["cell_c"]), Paragraph("", E["cell_c"]), Paragraph("", E["cell_c"]),
        Paragraph(_num(cd), E["subtotal_v"]),
    ])
    tbl_cd = Table(cd_filas, colWidths=COL_AIU_5, repeatRows=1)
    tbl_cd.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,0),  C["header_dark"]),
        ("ROWBACKGROUNDS",(0,1),(-1,-2), [C["zebra_a"], C["zebra_b"]]),
        ("BACKGROUND",    (0,-1),(-1,-1),C["light"]),
        ("SPAN",          (0,-1),(3,-1)),
        ("TOPPADDING",    (0,0),(-1,0),  _PAD_HDR), ("BOTTOMPADDING",(0,0),(-1,0),_PAD_HDR),
        ("TOPPADDING",    (0,1),(-1,-1), _PAD_DATA), ("BOTTOMPADDING",(0,1),(-1,-1),_PAD_DATA),
        ("LEFTPADDING",   (0,0),(-1,-1), 8), ("RIGHTPADDING",(0,0),(-1,-1),8),
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
        ("LINEBELOW",     (0,0),(-1,-1), 0.3, C["border"]),
        ("BOX",           (0,0),(-1,-1), 0.5, C["border"]),
    ]))
    story.append(tbl_cd)
    story.append(Spacer(1, _SP_SECCION))

    # ④ ESTRUCTURA AIU
    story += _seccion_header("Estructura AIU — Desglose del Precio del Contrato", E)

    pct_a = r.get("pct_a", 2.0); pct_i = r.get("pct_i", 2.0); pct_u = r.get("pct_u", 5.0)
    val_a = r.get("val_a", cd * pct_a / 100); val_i = r.get("val_i", cd * pct_i / 100)
    val_u = r.get("val_u", cd * pct_u / 100)
    incluir_iva = incluir_iva and r.get("incluir_iva", True)
    val_iva = r.get("val_iva", val_u * 0.19) if incluir_iva else 0.0
    logistica = r.get("logistica", 0); viaticos = r.get("viaticos", 0)
    precio_total = r.get("precio_total", cd + val_a + val_i + val_u + val_iva + logistica + viaticos)
    anticipo_val = precio_total * (anticipo_pct / 100)

    _CD_BG    = colors.HexColor("#E8F0FB")
    _AIU_BG   = colors.HexColor("#F4F6F9")
    _TOTAL_BG = colors.HexColor("#1A252C")
    _BORDE_CD = colors.HexColor("#1B5FA8")
    _BORDE_AIU= colors.HexColor("#C9A84C")

    s_cd_lbl  = ParagraphStyle("s_cd_lbl",  fontSize=9.5, fontName="Helvetica-Bold",   leading=12, textColor=colors.HexColor("#0D2137"))
    s_cd_val  = ParagraphStyle("s_cd_val",  fontSize=9.5, fontName="Helvetica-Bold",   leading=12, textColor=colors.HexColor("#0D2137"), alignment=TA_RIGHT)
    s_aiu_lbl = ParagraphStyle("s_aiu_lbl", fontSize=9,   fontName="Helvetica",        leading=11, textColor=C["text"])
    s_aiu_pct = ParagraphStyle("s_aiu_pct", fontSize=9,   fontName="Helvetica-Bold",   leading=11, textColor=C["secondary"], alignment=TA_CENTER)
    s_aiu_val = ParagraphStyle("s_aiu_val", fontSize=9,   fontName="Helvetica-Bold",   leading=11, textColor=C["text"], alignment=TA_RIGHT)
    s_iva_lbl = ParagraphStyle("s_iva_lbl", fontSize=8.5, fontName="Helvetica-Oblique",leading=11, textColor=C["secondary"])
    s_iva_val = ParagraphStyle("s_iva_val", fontSize=8.5, fontName="Helvetica-Bold",   leading=11, textColor=C["secondary"], alignment=TA_RIGHT)
    s_tot_lbl = ParagraphStyle("s_tot_lbl", fontSize=11,  fontName="Helvetica-Bold",   leading=14, textColor=C["white"])
    s_tot_val = ParagraphStyle("s_tot_val", fontSize=12,  fontName="Helvetica-Bold",   leading=15, textColor=C["accent"], alignment=TA_RIGHT)
    s_ant_lbl = ParagraphStyle("s_ant_lbl", fontSize=9,   fontName="Helvetica-Bold",   leading=11, textColor=C["accent"])
    s_ant_val = ParagraphStyle("s_ant_val", fontSize=9,   fontName="Helvetica-Bold",   leading=11, textColor=C["accent"], alignment=TA_RIGHT)
    s_log_lbl = ParagraphStyle("s_log_lbl", fontSize=8.5, fontName="Helvetica",        leading=11, textColor=C["gray"])
    s_log_val = ParagraphStyle("s_log_val", fontSize=8.5, fontName="Helvetica",        leading=11, textColor=C["gray"], alignment=TA_RIGHT)

    tbl_cd_hdr = Table([[Paragraph("COSTO DIRECTO (CD)", s_cd_lbl), Paragraph("100%", s_aiu_pct), Paragraph(_num(cd), s_cd_val)]], colWidths=COL_AIU_3)
    tbl_cd_hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), _CD_BG),
        ("LINEABOVE",     (0,0),(-1, 0), 2.0, _BORDE_CD),
        ("LINEBEFORE",    (0,0),(0,-1),  3.0, _BORDE_CD),
        ("TOPPADDING",    (0,0),(-1,-1), 9), ("BOTTOMPADDING",(0,0),(-1,-1),9),
        ("LEFTPADDING",   (0,0),(-1,-1), 10), ("RIGHTPADDING",(0,0),(-1,-1),10),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("BOX",           (0,0),(-1,-1), 0.5, C["border"]),
    ]))
    story.append(tbl_cd_hdr)

    filas_aiu_comp = [
        [Paragraph(f"A — Administración  ({pct_a:.1f}% sobre CD)", s_aiu_lbl), Paragraph(f"{pct_a:.1f}%", s_aiu_pct), Paragraph(_num(val_a), s_aiu_val)],
        [Paragraph(f"I — Imprevistos  ({pct_i:.1f}% sobre CD)", s_aiu_lbl),   Paragraph(f"{pct_i:.1f}%", s_aiu_pct), Paragraph(_num(val_i), s_aiu_val)],
        [Paragraph(f"U — Utilidad  ({pct_u:.1f}% sobre CD)", s_aiu_lbl),      Paragraph(f"{pct_u:.1f}%", s_aiu_pct), Paragraph(_num(val_u), s_aiu_val)],
        [Paragraph("IVA 19%  (Sólo sobre Utilidad — Decreto 1372/92)" if incluir_iva else "IVA  (Exento — Régimen Simplificado Art. 499 E.T.)", s_iva_lbl),
         Paragraph("19%" if incluir_iva else "0%", s_iva_val), Paragraph(_num(val_iva), s_iva_val)],
    ]
    _iva_bg = colors.HexColor("#EEF3FB") if incluir_iva else colors.HexColor("#EBF7EE")
    tbl_aiu_comp = Table(filas_aiu_comp, colWidths=COL_AIU_3)
    tbl_aiu_comp.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), _AIU_BG),
        ("LINEBEFORE",    (0,0),(0,-1),  3.0, _BORDE_AIU),
        ("LINEABOVE",     (0,3),(-1,3),  0.8, C["border"]),
        ("BACKGROUND",    (0,3),(-1,3),  _iva_bg),
        ("TOPPADDING",    (0,0),(-1,-1), _PAD_DATA), ("BOTTOMPADDING",(0,0),(-1,-1),_PAD_DATA),
        ("LEFTPADDING",   (0,0),(-1,-1), 10), ("RIGHTPADDING",(0,0),(-1,-1),10),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("LINEBELOW",     (0,0),(-1,-1), 0.3, C["border"]),
        ("BOX",           (0,0),(-1,-1), 0.5, C["border"]),
    ]))
    story.append(KeepTogether([tbl_aiu_comp]))

    filas_extra = []
    if logistica > 0:
        filas_extra.append([Paragraph("Logística y transporte integrada", s_log_lbl), Paragraph("—", s_log_lbl), Paragraph(_num(logistica), s_log_val)])
    if viaticos > 0:
        filas_extra.append([Paragraph("Viáticos y gastos foráneos", s_log_lbl), Paragraph("—", s_log_lbl), Paragraph(_num(viaticos), s_log_val)])
    filas_extra.append([Paragraph(f"ANTICIPO A PAGAR  ({anticipo_pct}% del total)", s_ant_lbl), Paragraph(f"{anticipo_pct}%", s_ant_val), Paragraph(_num(anticipo_val), s_ant_val)])
    filas_extra.append([Paragraph("TOTAL DEL CONTRATO", s_tot_lbl), Paragraph("", s_tot_lbl), Paragraph(_num(precio_total), s_tot_val)])
    idx_ant_extra = len(filas_extra) - 2
    idx_tot_extra = len(filas_extra) - 1

    tbl_extra = Table(filas_extra, colWidths=COL_AIU_3)
    tbl_extra.setStyle(TableStyle([
        ("ROWBACKGROUNDS",  (0,0),(-1,idx_ant_extra-1), [C["zebra_a"], C["zebra_b"]]),
        ("BACKGROUND",      (0,idx_ant_extra),(-1,idx_ant_extra), C["anticipo_bg"]),
        ("BACKGROUND",      (0,idx_tot_extra),(-1,idx_tot_extra), _TOTAL_BG),
        ("LINEABOVE",       (0,idx_tot_extra),(-1,idx_tot_extra), 3.0, C["accent"]),
        ("TOPPADDING",      (0,0),(-1,-2), _PAD_DATA), ("BOTTOMPADDING",(0,0),(-1,-2),_PAD_DATA),
        ("TOPPADDING",      (0,idx_tot_extra),(-1,idx_tot_extra), 10),
        ("BOTTOMPADDING",   (0,idx_tot_extra),(-1,idx_tot_extra), 10),
        ("LEFTPADDING",     (0,0),(-1,-1), 10), ("RIGHTPADDING",(0,0),(-1,-1),10),
        ("VALIGN",          (0,0),(-1,-1), "MIDDLE"),
        ("LINEBELOW",       (0,0),(-1,-2), 0.3, C["border"]),
        ("BOX",             (0,0),(-1,-1), 0.5, C["border"]),
    ]))
    story.append(KeepTogether([tbl_extra]))

    valor_letras = _numero_a_letras(int(round(precio_total)))
    story.append(Table([[Paragraph(f"Son: {valor_letras}", E["letras"])]],
        colWidths=[_AU], style=TableStyle([
            ("BACKGROUND",   (0,0),(-1,-1), C["primary"]),
            ("TOPPADDING",   (0,0),(-1,-1), 4), ("BOTTOMPADDING",(0,0),(-1,-1),6),
            ("LEFTPADDING",  (0,0),(-1,-1), 10),
        ])))
    story.append(Spacer(1, _SP_SECCION))

    nota_aiu = (
        "En contratos bajo estructura AIU, el IVA (19%) aplica exclusivamente sobre la "
        "Utilidad (U), conforme al Art. 3 del Decreto 1372/1992 y conceptos DIAN. "
        "El IVA NO se aplica sobre Costo Directo (CD), Administración (A) ni Imprevistos (I). "
        f"Anticipo requerido: {anticipo_pct}% del total al inicio de la obra. "
        "Barranquilla, Colombia."
    )
    story += _seccion_alcance(E, C, inclusiones=inclusiones, exclusiones=exclusiones)
    story.append(Spacer(1, _SP_SECCION))
    story += _seccion_terminos(E, C, nota_aiu, anticipo_pct)
    story.append(Spacer(1, _SP_BLOQUE))
    story += _bloque_firma_cliente(E, C)
    story += _footer_doc(E, C, emp.get("nombre",""), fecha_str, numero, ciudad=emp.get("ciudad","Barranquilla"))

    doc.build(story)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# CUENTA DE COBRO
# ══════════════════════════════════════════════════════════════════════════════

def generar_cuenta_cobro(resultado, datos_prestador, datos_pagador,
                          numero=None, descripcion_servicio=None,
                          logo_bytes=None, incluir_iva=True):
    if numero is None:
        numero = f"CC-{_hoy().strftime('%Y%m%d')}-001"
    fecha_str = _fecha_es()

    es_aiu = resultado.get("tipo_proyecto") == "Licitacion AIU"
    precio_base  = resultado.get("precio_sugerido", resultado.get("precio_total", 0))
    anticipo_pct = resultado.get("anticipo_pct", datos_prestador.get("anticipo_pct", 60))

    if es_aiu:
        precio_base  = resultado.get("precio_total", precio_base)
        valor_total  = precio_base
        iva          = resultado.get("val_iva", 0)
        incluir_iva  = False
    else:
        iva          = precio_base * 0.19 if incluir_iva else 0.0
        valor_total  = precio_base + iva

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
    C = _C(palette)
    E = _estilos(C)

    _titulo_doc = "CUENTA DE COBRO"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
        leftMargin=_margen_lateral, rightMargin=_margen_lateral,
        topMargin=1.0*cm,  bottomMargin=1.2*cm,
        title=f"{_titulo_doc} {numero}")

    story = []

    # ① ENCABEZADO
    story.append(_encabezado_doc(E, C, _titulo_doc, numero, fecha_str, emp, _lb))
    story.append(Spacer(1, _SP_SECCION))

    # ② QUIEN COBRA
    story += _seccion_header("Quien Cobra", E)
    story.append(_tabla_datos_cliente(E, C, [
        ("Nombre / Razon Social", datos_prestador.get("nombre","—")),
        ("NIT / CC",              datos_prestador.get("nit_cc", datos_prestador.get("nit","—"))),
        ("Dirección",             "Área metropolitana"),
        ("Telefono",              datos_prestador.get("telefono", datos_prestador.get("tel","—"))),
    ]))
    story.append(Spacer(1, _SP_SECCION))

    # ③ QUIEN PAGA
    story += _seccion_header("Quien Paga", E)
    story.append(_tabla_datos_cliente(E, C, [
        ("Nombre / Razon Social", datos_pagador.get("nombre","—")),
        ("NIT / CC",              datos_pagador.get("nit","—")),
    ]))
    story.append(Spacer(1, _SP_SECCION))

    # ④ DESCRIPCION DEL SERVICIO
    if descripcion_servicio is None:
        if es_aiu:
            cn = resultado.get("_estado_guardado", {}).get("nombre_cliente", "")
            rt = f" para {cn}" if cn else ""
            descripcion_servicio = (
                f"Cobro del {anticipo_pct}% de anticipo en cotización AIU{rt}. "
                f"Suministro, fabricación e instalación de materiales pétreos según especificaciones. "
                f"Saldo {100-anticipo_pct}% contra acta de entrega."
            )
        else:
            m2   = resultado.get("m2_real", 0)
            tipo = resultado.get("tipo_proyecto", "proyecto")
            cat  = resultado.get("categoria", "material petreo")
            ref  = resultado.get("referencia","")
            rt   = f" referencia {ref}" if ref else ""
            descripcion_servicio = (
                f"Cobro del {anticipo_pct}% de anticipo para: suministro, fabricación e instalación "
                f"de {tipo} en {cat}{rt}. Area instalada: {m2:.2f} m2. "
                f"Saldo {100-anticipo_pct}% contra entrega a satisfacción."
            )

    story += _seccion_header("Descripcion del Servicio", E)
    tbl_serv = Table([[Paragraph(descripcion_servicio, E["cell"])]], colWidths=[_AU])
    tbl_serv.setStyle(TableStyle([
        ("BACKGROUND",  (0,0),(-1,-1), C["ultralight"]),
        ("TOPPADDING",  (0,0),(-1,-1), _PAD_DATA+1), ("BOTTOMPADDING",(0,0),(-1,-1),_PAD_DATA+1),
        ("LEFTPADDING", (0,0),(-1,-1), 10), ("RIGHTPADDING",(0,0),(-1,-1),10),
        ("BOX",         (0,0),(-1,-1), 0.5, C["border"]),
        ("LINEABOVE",   (0,0),(-1, 0), 1.5, C["secondary"]),
    ]))
    story.append(tbl_serv)
    story.append(Spacer(1, _SP_SECCION))

    # ⑤ VALOR DEL COBRO — KeepTogether conservado
    story += _seccion_header("Valor del Cobro", E)
    if incluir_iva and not es_aiu:
        filas_val = [
            [Paragraph("Valor total del servicio (sin IVA)",        E["cell_b"]),   Paragraph(_num(precio_base),      E["cell_br"])],
            [Paragraph("IVA 19% (Art. 468 E.T.)",                   E["iva_l"]),    Paragraph(_num(iva),              E["iva_v"])],
            [Paragraph("Total (IVA incluido)",                      E["subtotal_l"]),Paragraph(_num(valor_total),     E["subtotal_v"])],
            [Paragraph(f"ANTICIPO A COBRAR ({anticipo_pct}%)",      E["anticipo_l"]),Paragraph(_num(valor_anticipo),  E["anticipo_v"])],
            [Paragraph(f"Saldo contra entrega ({100-anticipo_pct}%)",
                ParagraphStyle("sl1",fontSize=8,fontName="Helvetica",leading=10,textColor=C["gray"])),
             Paragraph(_num(valor_saldo),
                ParagraphStyle("slv1",fontSize=8,fontName="Helvetica",leading=10,textColor=C["gray"],alignment=TA_RIGHT))],
            [Paragraph("VALOR COBRADO EN ESTE DOCUMENTO", E["total_label"]), Paragraph(_num(valor_anticipo), E["total_val"])],
        ]
        idx_ant, idx_tot = 3, 5
    else:
        filas_val = [
            [Paragraph("Valor total de la cotizacion",              E["subtotal_l"]),Paragraph(_num(valor_total),     E["subtotal_v"])],
            [Paragraph(f"ANTICIPO A COBRAR ({anticipo_pct}%)",      E["anticipo_l"]),Paragraph(_num(valor_anticipo),  E["anticipo_v"])],
            [Paragraph(f"Saldo contra entrega ({100-anticipo_pct}%)",
                ParagraphStyle("sl2",fontSize=8,fontName="Helvetica",leading=10,textColor=C["gray"])),
             Paragraph(_num(valor_saldo),
                ParagraphStyle("slv2",fontSize=8,fontName="Helvetica",leading=10,textColor=C["gray"],alignment=TA_RIGHT))],
            [Paragraph("VALOR COBRADO EN ESTE DOCUMENTO", E["total_label"]), Paragraph(_num(valor_anticipo), E["total_val"])],
        ]
        idx_ant, idx_tot = 1, 3

    tbl_val = Table(filas_val, colWidths=COL_2_75_25)
    tbl_val.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0,0), (-1,idx_ant-1), [C["zebra_a"], C["zebra_b"]]),
        ("BACKGROUND",     (0,idx_ant),(-1,idx_ant), C["anticipo_bg"]),
        ("BACKGROUND",     (0,idx_tot),(-1,idx_tot), C["total_bg"]),
        ("LINEABOVE",      (0,idx_tot),(-1,idx_tot), 3.0, C["accent"]),
        ("TOPPADDING",     (0,0),(-1,idx_tot-1), _PAD_DATA), ("BOTTOMPADDING",(0,0),(-1,idx_tot-1),_PAD_DATA),
        ("TOPPADDING",     (0,idx_tot),(-1,idx_tot), 8), ("BOTTOMPADDING",(0,idx_tot),(-1,idx_tot),8),
        ("LEFTPADDING",    (0,0),(-1,-1), 10), ("RIGHTPADDING",(0,0),(-1,-1),10),
        ("LINEBELOW",      (0,0),(-1,-2), 0.3, C["border"]),
        ("BOX",            (0,0),(-1,-1), 0.5, C["border"]),
    ]))
    valor_letras = _numero_a_letras(int(round(valor_anticipo)))
    _tbl_letras_cc = Table([[Paragraph(f"Son: {valor_letras}", E["letras"])]],
        colWidths=[_AU], style=TableStyle([
            ("BACKGROUND",   (0,0),(-1,-1), C["primary"]),
            ("TOPPADDING",   (0,0),(-1,-1), 4), ("BOTTOMPADDING",(0,0),(-1,-1),6),
            ("LEFTPADDING",  (0,0),(-1,-1), 10),
        ]))
    story.append(KeepTogether([tbl_val, _tbl_letras_cc]))
    story.append(Spacer(1, _SP_SECCION))

    # ⑥ DATOS BANCARIOS
    banco_filas = []
    if datos_prestador.get("banco"):         banco_filas.append(("Banco", datos_prestador["banco"]))
    if datos_prestador.get("cuenta_tipo"):   banco_filas.append(("Tipo de cuenta", datos_prestador["cuenta_tipo"]))
    if datos_prestador.get("cuenta_numero"): banco_filas.append(("N de cuenta", datos_prestador["cuenta_numero"]))
    if datos_prestador.get("nombre"):        banco_filas.append(("A nombre de", datos_prestador["nombre"]))
    if banco_filas:
        story += _seccion_header("Datos para Pago", E)
        story.append(_tabla_datos_cliente(E, C, banco_filas))
        story.append(Spacer(1, _SP_SECCION))

    # ⑦ NOTA TRIBUTARIA
    _nota_tributaria = (
        "La Factura Electrónica DIAN será emitida y transmitida oficialmente "
        "una vez se confirme la recepción del anticipo pactado."
        if (incluir_iva and not es_aiu) else
        "El prestador del servicio pertenece al Régimen Simplificado (No Responsable de IVA)."
    )
    story.append(Table([[Paragraph(_nota_tributaria, E["nota_legal"])]],
        colWidths=[_AU], style=TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#FFF9EC")),
            ("LEFTPADDING",   (0,0),(-1,-1), 10), ("RIGHTPADDING",(0,0),(-1,-1),10),
            ("TOPPADDING",    (0,0),(-1,-1), _PAD_DATA+1), ("BOTTOMPADDING",(0,0),(-1,-1),_PAD_DATA+1),
            ("LINEABOVE",     (0,0),(-1, 0), 1.5, colors.HexColor("#C9A84C")),
            ("BOX",           (0,0),(-1,-1), 0.4, colors.HexColor("#C8D8E8")),
        ])))
    story.append(Spacer(1, _SP_SECCION))

    # ⑧ FIRMA PRESTADOR / PAGADOR — dos columnas simétricas con caja/borde
    _f_mitad = (_AU - 12) / 2.0
    _st_fn   = E["aviso"]
    _st_fc   = E["cell"]

    def _caja_firma(titulo, nombre_pie):
        """Sub-tabla de firma: línea de firma + nombre + rol, con borde completo."""
        t = Table(
            [
                [Paragraph("", _st_fc)],
                [Paragraph("", _st_fc)],
                [Paragraph("_" * 36, _st_fc)],
                [Paragraph(nombre_pie, _st_fn)],
                [Paragraph(titulo, _st_fn)],
            ],
            colWidths=[_f_mitad],
            rowHeights=[14, 14, 12, 12, 12],
        )
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#FAFCFF")),
            ("BOX",           (0,0),(-1,-1), 0.5, colors.HexColor("#C8D8E8")),
            ("LINEABOVE",     (0,0),(-1, 0), 2.0, colors.HexColor("#1B5FA8")),
            ("TOPPADDING",    (0,0),(-1,-1), 3),
            ("BOTTOMPADDING", (0,0),(-1,-1), 3),
            ("LEFTPADDING",   (0,0),(-1,-1), 10),
            ("RIGHTPADDING",  (0,0),(-1,-1), 10),
            ("ALIGN",         (0,2),(-1,-1), "LEFT"),
            ("VALIGN",        (0,0),(-1,-1), "BOTTOM"),
        ]))
        return t

    firma = Table(
        [[
            _caja_firma("Firma del Prestador", datos_prestador.get("nombre", "")),
            _caja_firma("Sello / Firma del Pagador", ""),
        ]],
        colWidths=[_f_mitad, _f_mitad],
        hAlign="CENTER",
        spaceBefore=_SP_SECCION,
    )
    firma.setStyle(TableStyle([
        ("LEFTPADDING",  (0,0),(-1,-1), 0),
        ("RIGHTPADDING", (0,0),(-1,-1), 0),
        ("TOPPADDING",   (0,0),(-1,-1), 0),
        ("BOTTOMPADDING",(0,0),(-1,-1), 0),
        ("COLPADDING",   (0,0),( 0,-1), 6),
    ]))
    story.append(Spacer(1, _SP_SECCION))
    story.append(firma)

    # ⑨ FIRMA CLIENTE — KeepTogether conservado
    story += _bloque_firma_cliente(E, C)

    # ⑩ FOOTER
    story += _footer_doc(E, C, datos_prestador.get("nombre",""), fecha_str, numero,
                          ciudad=datos_prestador.get("ciudad","Barranquilla"))

    doc.build(story)
    return buf.getvalue()


# ── Conversion numero a letras (espanol colombiano) ───────────────────────────

def _numero_a_letras(n):
    def _core(n):
        if n == 0: return "cero"
        unidades = ["","uno","dos","tres","cuatro","cinco","seis","siete","ocho","nueve",
                    "diez","once","doce","trece","catorce","quince","dieciséis","diecisiete",
                    "dieciocho","diecinueve"]
        veintes  = {20:"veinte",21:"veintiuno",22:"veintidós",23:"veintitrés",
                    24:"veinticuatro",25:"veinticinco",26:"veintiséis",
                    27:"veintisiete",28:"veintiocho",29:"veintinueve"}
        decenas  = ["","diez","veinte","treinta","cuarenta","cincuenta","sesenta","setenta","ochenta","noventa"]
        centenas = ["","ciento","doscientos","trescientos","cuatrocientos","quinientos",
                    "seiscientos","setecientos","ochocientos","novecientos"]
        def _menor_mil(x):
            if x == 0:   return ""
            if x == 100: return "cien"
            c, resto = divmod(x, 100)
            d, u     = divmod(resto, 10)
            partes   = []
            if c: partes.append(centenas[c])
            if resto == 0: pass
            elif resto < 20: partes.append(unidades[resto])
            elif resto in veintes: partes.append(veintes[resto])
            else:
                p = decenas[d]
                if u: p += " y " + unidades[u]
                partes.append(p)
            return " ".join(partes)
        if n < 0:           return "menos " + _core(-n)
        if n < 1_000:       return _menor_mil(n)
        if n < 1_000_000:
            m, r = divmod(n, 1_000)
            pre  = "mil" if m == 1 else _menor_mil(m) + " mil"
            return (pre + " " + _menor_mil(r)).strip()
        if n < 1_000_000_000:
            m, r = divmod(n, 1_000_000)
            pre  = "un millón" if m == 1 else _menor_mil(m) + " millones"
            return (pre + " " + _core(r)).strip()
        return str(n)

    raw = _core(int(abs(n)))
    return raw.capitalize() + " PESOS M/CTE."
