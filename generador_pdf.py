# generador_pdf.py — CostoMármol v7 · Propuesta Comercial B2B
# MARMOLES COLLANTE & CASTRO LTDA.
#
# ARQUITECTURA v7:
#   - Diseño Platypus modular con 4 secciones claramente delimitadas por Spacer
#   - Paleta corporativa oscura: encabezados #1A252C con texto blanco (B2B financiero)
#   - Zebra-striping en filas de datos (blanco / gris muy sutil #F2F5F9)
#   - Total y bloque AIU con bordes definidos y fuente de mayor jerarquía visual
#   - Paragraph() en TODAS las celdas → ajuste automático de texto largo (sin desborde)
#   - Estructura:
#       ① Encabezado (Logo + Datos cliente)
#       ② Despiece Técnico y Elementos
#       ③ Resumen Financiero y AIU
#       ④ Términos y Condiciones Comerciales

import io
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from PIL import Image as PILImage

_BOG = ZoneInfo("America/Bogota")

def _hoy() -> date:
    """Fecha actual en zona horaria de Colombia."""
    return datetime.now(_BOG).date()
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle

# ── Ancho maestro del documento ───────────────────────────────────────────────
# Valor fijo de 16.5 cm que garantiza simetría y alineación perfecta en TODAS
# las tablas del documento. La suma de colWidths de cada tabla DEBE ser exactamente
# ancho_util. Esta es la única fuente de verdad para anchos de columna.
ancho_util = 16.5 * cm   # Ancho útil maestro — 16.5 cm exactos
_AU = ancho_util          # Alias interno para compatibilidad con bloques existentes
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Image, KeepTogether, PageBreak,
)
from reportlab.lib.utils import ImageReader
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from calculos import cop

# ── Paleta corporativa B2B ────────────────────────────────────────────────────
_DEFAULT_PALETTE = {
    "header_dark": "#1A252C",   # Fondo encabezados de tabla (carbón B2B)
    "primary":     "#0D2137",   # Azul marino profundo (header doc + total row)
    "secondary":   "#1B5FA8",   # Azul corporativo (acentos y subrayados)
    "accent":      "#C9A84C",   # Dorado corporativo (anticipo + borde inferior header)
    "light":       "#D6E8FA",   # Azul muy claro (fondos sutiles)
    "ultralight":  "#F5F8FC",   # Casi blanco (badge resumen)
    "zebra_a":     "#FFFFFF",   # Fila zebra A (blanca)
    "zebra_b":     "#F2F5F9",   # Fila zebra B (gris muy sutil)
    "total_bg":    "#0D2137",   # Fondo fila Total (azul profundo)
    "anticipo_bg": "#FFF8E7",   # Fondo fila anticipo (dorado muy tenue)
    "gray":        "#6B85A0",   # Texto secundario / etiquetas de sección
    "text":        "#1C2B3A",   # Texto cuerpo principal
    "white":       "#FFFFFF",
    "terms_text":  "#4A5568",   # Texto T&C (gris oscuro legible)
    "border":      "#C8D8E8",   # Borde de tablas
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
    """Extrae paleta dominante del logo; usa default si falla."""
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
    """Convierte todos los hex de la paleta a colores ReportLab."""
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
        # ── Sanitización de canal Alpha para visores PDF móviles (iOS / WhatsApp) ──
        # Los motores de renderizado móviles no interpretan correctamente el canal
        # Alpha de PNGs dentro de PDFs, mostrando el logo en blanco o invisible.
        # Solución: aplanar la transparencia sobre un lienzo blanco sólido y
        # recodificar como JPEG antes de pasar a ReportLab.
        pil_img = PILImage.open(io.BytesIO(logo_bytes))

        # Detectar si la imagen tiene transparencia (RGBA, LA, o P con paleta+alpha)
        _tiene_alpha = (
            pil_img.mode in ("RGBA", "LA") or
            (pil_img.mode == "P" and "transparency" in pil_img.info)
        )

        if _tiene_alpha:
            # Convertir a RGBA para garantizar canal alpha uniforme
            pil_rgba = pil_img.convert("RGBA")
            # Crear lienzo blanco sólido del mismo tamaño
            fondo_blanco = PILImage.new("RGB", pil_rgba.size, (255, 255, 255))
            # Pegar la imagen usando su propio canal alpha como máscara
            fondo_blanco.paste(pil_rgba, mask=pil_rgba.split()[3])
            pil_clean = fondo_blanco
        else:
            # Sin transparencia: conversión directa a RGB
            pil_clean = pil_img.convert("RGB")

        # Guardar imagen plana en BytesIO como JPEG de alta calidad
        clean_io = io.BytesIO()
        pil_clean.save(clean_io, format="JPEG", quality=95)
        clean_io.seek(0)

        # Pasar el BytesIO limpio a la clase Image de Platypus
        img = Image(clean_io, width=4.2*cm, height=1.6*cm, kind='proportional')
        ratio = img.imageWidth / img.imageHeight
        img.drawWidth  = max_h * ratio
        img.drawHeight = max_h
        return img
    except Exception:
        return None


# ── Estilos tipográficos ──────────────────────────────────────────────────────

def _estilos(C):
    """Devuelve dict de ParagraphStyle listos para usar en celdas de tabla."""
    return {
        "doc_empresa": ParagraphStyle("doc_empresa", fontSize=8.5, fontName="Helvetica-Bold",
                                       leading=11, textColor=C["white"]),
        "doc_emp_sub": ParagraphStyle("doc_emp_sub", fontSize=7, fontName="Helvetica",
                                       leading=9, textColor=colors.HexColor("#B8D4F0")),
        "doc_num":     ParagraphStyle("doc_num", fontSize=13, fontName="Helvetica-Bold",
                                       leading=16, textColor=C["white"], alignment=TA_RIGHT),
        "doc_validez": ParagraphStyle("doc_validez", fontSize=7, fontName="Helvetica-Bold",
                                       leading=9, textColor=C["accent"], alignment=TA_RIGHT),
        "seccion":     ParagraphStyle("seccion", fontSize=6.5, fontName="Helvetica-Bold",
                                       leading=8, textColor=C["gray"], letterSpacing=1.4),
        "cell":        ParagraphStyle("cell", fontSize=8, fontName="Helvetica",
                                       leading=10, textColor=C["text"]),
        "cell_b":      ParagraphStyle("cell_b", fontSize=8, fontName="Helvetica-Bold",
                                       leading=10, textColor=C["text"]),
        "cell_r":      ParagraphStyle("cell_r", fontSize=8, fontName="Helvetica",
                                       leading=10, textColor=C["text"], alignment=TA_RIGHT),
        "cell_br":     ParagraphStyle("cell_br", fontSize=8, fontName="Helvetica-Bold",
                                       leading=10, textColor=C["text"], alignment=TA_RIGHT),
        "cell_c":      ParagraphStyle("cell_c", fontSize=8, fontName="Helvetica",
                                       leading=10, textColor=C["text"], alignment=TA_CENTER),
        "th":          ParagraphStyle("th", fontSize=7.5, fontName="Helvetica-Bold",
                                       leading=9, textColor=C["white"]),
        "th_r":        ParagraphStyle("th_r", fontSize=7.5, fontName="Helvetica-Bold",
                                       leading=9, textColor=C["white"], alignment=TA_RIGHT),
        "th_c":        ParagraphStyle("th_c", fontSize=7.5, fontName="Helvetica-Bold",
                                       leading=9, textColor=C["white"], alignment=TA_CENTER),
        "total_label": ParagraphStyle("total_label", fontSize=10, fontName="Helvetica-Bold",
                                       leading=13, textColor=C["white"]),
        "total_val":   ParagraphStyle("total_val", fontSize=10, fontName="Helvetica-Bold",
                                       leading=13, textColor=C["white"], alignment=TA_RIGHT),
        "subtotal_l":  ParagraphStyle("subtotal_l", fontSize=8.5, fontName="Helvetica-Bold",
                                       leading=11, textColor=C["text"]),
        "subtotal_v":  ParagraphStyle("subtotal_v", fontSize=8.5, fontName="Helvetica-Bold",
                                       leading=11, textColor=C["text"], alignment=TA_RIGHT),
        "anticipo_l":  ParagraphStyle("anticipo_l", fontSize=8.5, fontName="Helvetica-Bold",
                                       leading=11, textColor=C["accent"]),
        "anticipo_v":  ParagraphStyle("anticipo_v", fontSize=8.5, fontName="Helvetica-Bold",
                                       leading=11, textColor=C["accent"], alignment=TA_RIGHT),
        "iva_l":       ParagraphStyle("iva_l", fontSize=8, fontName="Helvetica-Oblique",
                                       leading=10, textColor=C["secondary"]),
        "iva_v":       ParagraphStyle("iva_v", fontSize=8, fontName="Helvetica-Oblique",
                                       leading=10, textColor=C["secondary"], alignment=TA_RIGHT),
        "letras":      ParagraphStyle("letras", fontSize=7.5, fontName="Helvetica-Bold",
                                       leading=10, textColor=C["white"]),
        "footer":      ParagraphStyle("footer", fontSize=6.5, fontName="Helvetica",
                                       leading=8, textColor=C["gray"], alignment=TA_CENTER),
        "aviso":       ParagraphStyle("aviso", fontSize=6.5, fontName="Helvetica",
                                       leading=9, textColor=C["text"]),
        "terms_title": ParagraphStyle("terms_title", fontSize=7, fontName="Helvetica-Bold",
                                       leading=9, textColor=C["terms_text"]),
        "terms_body":  ParagraphStyle("terms_body", fontSize=6.5, fontName="Helvetica",
                                       leading=9, textColor=C["terms_text"]),
        "inc_hdr":     ParagraphStyle("inc_hdr", fontSize=7, fontName="Helvetica-Bold",
                                       leading=9, textColor=C["white"]),
        "inc_row":     ParagraphStyle("inc_row", fontSize=6.5, fontName="Helvetica",
                                       leading=9, textColor=C["text"],
                                       leftIndent=14, firstLineIndent=-14),
        "white_s":     ParagraphStyle("white_s", fontSize=7.5, fontName="Helvetica",
                                       leading=10, textColor=C["white"]),
        "accent_s":    ParagraphStyle("accent_s", fontSize=7, fontName="Helvetica-Bold",
                                       leading=9, textColor=C["accent"]),
        # Estilos nuevos para FIX-2, FIX-3, FIX-4
        "nota_legal":  ParagraphStyle("nota_legal", fontSize=6.5, fontName="Helvetica-Oblique",
                                       leading=9, textColor=colors.HexColor("#4A5568")),
        "firma_titulo":ParagraphStyle("firma_titulo", fontSize=8, fontName="Helvetica-Bold",
                                       leading=11, textColor=colors.HexColor("#1C2B3A")),
        "firma_campo": ParagraphStyle("firma_campo", fontSize=8, fontName="Helvetica",
                                       leading=12, textColor=colors.HexColor("#1C2B3A")),
        "matriz_inc":     ParagraphStyle("matriz_inc", fontSize=9, fontName="Helvetica-Bold",
                                          leading=12, textColor=colors.HexColor("#FFFFFF"),
                                          alignment=TA_CENTER, spaceAfter=0),
        "matriz_exc":     ParagraphStyle("matriz_exc", fontSize=9, fontName="Helvetica-Bold",
                                          leading=12, textColor=colors.HexColor("#FFFFFF"),
                                          alignment=TA_CENTER, spaceAfter=0),
        "matriz_inc_row": ParagraphStyle("matriz_inc_row", fontSize=9, fontName="Helvetica",
                                          leading=13, textColor=colors.HexColor("#1C2B3A"),
                                          leftIndent=0, firstLineIndent=0, spaceAfter=0),
        "matriz_exc_row": ParagraphStyle("matriz_exc_row", fontSize=9, fontName="Helvetica",
                                          leading=13, textColor=colors.HexColor("#1C2B3A"),
                                          leftIndent=0, firstLineIndent=0, spaceAfter=0),
    }


# ── Bloques reutilizables ─────────────────────────────────────────────────────

def _seccion_header(titulo, E):
    """[HRFlowable, Spacer, Paragraph(sección), Spacer] para separar secciones visualmente."""
    return [
        HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#CBD5E0")),
        Spacer(1, 4),
        Paragraph(titulo.upper(), E["seccion"]),
        Spacer(1, 3),
    ]


def _encabezado_doc(E, C, doc_type, numero, fecha_str, empresa_info, logo_bytes, valido_hasta=None):
    """
    Bloque encabezado corporativo B2B:
    [Logo + Datos empresa | Tipo doc + Número + Fecha + Validez]
    Fondo primary oscuro, texto blanco, borde inferior dorado.
    """
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
                           leading=9, textColor=C["accent"], alignment=TA_RIGHT)),
        Spacer(1, 4),
        Paragraph(f"<b>{numero}</b>", E["doc_num"]),
        Spacer(1, 3),
        Paragraph(fecha_str,
            ParagraphStyle("fch", fontSize=7.5, fontName="Helvetica",
                           leading=9, textColor=colors.HexColor("#B8D4F0"), alignment=TA_RIGHT)),
    ]
    if emp.get("email"):
        der.append(Paragraph(emp["email"],
            ParagraphStyle("em2", fontSize=6.5, fontName="Helvetica",
                           leading=9, textColor=colors.HexColor("#B8D4F0"), alignment=TA_RIGHT)))
    if valido_hasta:
        der.append(Spacer(1, 3))
        der.append(Paragraph(f"Válida hasta: {valido_hasta}", E["doc_validez"]))

    tbl = Table([[izq, der]], colWidths=[_AU * 0.588, _AU * 0.412])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), C["primary"]),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("TOPPADDING",    (0,0), (-1,-1), 12),
        ("BOTTOMPADDING", (0,0), (-1,-1), 12),
        ("LEFTPADDING",   (0,0), (0,-1),  14),
        ("RIGHTPADDING",  (-1,0),(-1,-1), 14),
        ("LEFTPADDING",   (-1,0),(-1,-1), 8),
        ("LINEBELOW",     (0,0), (-1,-1), 2.5, C["accent"]),
    ]))
    return tbl


def _tabla_datos_cliente(E, C, filas_datos):
    """Tabla 2 col (etiqueta|valor) con zebra striping y borde exterior."""
    rows = []
    for label, valor in filas_datos:
        rows.append([Paragraph(label, E["cell"]), Paragraph(f"<b>{valor}</b>", E["cell_b"])])
    tbl = Table(rows, colWidths=[_AU * 0.301, _AU * 0.699], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [C["zebra_a"], C["zebra_b"]]),
        ("TOPPADDING",     (0,0), (-1,-1), 5),
        ("BOTTOMPADDING",  (0,0), (-1,-1), 5),
        ("LEFTPADDING",    (0,0), (-1,-1), 8),
        ("RIGHTPADDING",   (0,0), (-1,-1), 8),
        ("LINEBELOW",      (0,0), (-1,-1), 0.3, C["border"]),
        ("BOX",            (0,0), (-1,-1), 0.5, C["border"]),
    ]))
    return tbl


def _tabla_2col(E, C, filas_datos):
    return _tabla_datos_cliente(E, C, filas_datos)


def _footer_doc(E, C, emp_nombre, fecha_str, numero="", ciudad="Barranquilla"):
    """Footer premium corporativo — sin código de cotización, con branding completo.
    Formato: 'MÁRMOLES COLLANTE & CASTRO LTDA. | Distribuidor Oficial de GRANITOS Y MÁRMOLES S.A.S | {ciudad} • {fecha}'
    Texto centrado en color gris oscuro (#4A5568). Sin referencia a número de cotización.
    """
    _nombre_marca = emp_nombre.strip() if emp_nombre and emp_nombre.strip() else "MÁRMOLES COLLANTE & CASTRO LTDA."
    _ciudad_str   = ciudad.strip() if ciudad and ciudad.strip() else "Barranquilla"
    # Texto centrado gris oscuro — branding completo sin código de documento
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
        Spacer(1, 6),
        HRFlowable(width="100%", thickness=0.5, color=C["border"]),
        Spacer(1, 3),
        Paragraph(linea, _footer_style),
    ]


# ── Módulo: Despiece Técnico ──────────────────────────────────────────────────

def _seccion_despiece_tecnico(E, C, r, incluir_iva, anticipo_pct, precio_sugerido_total):
    """
    SECCIÓN 2 — Tabla de ítems.
    Encabezado oscuro #1A252C · Zebra striping · Paragraph en columna Descripción.
    MOD-1: Descripción enriquecida con "REF: <material>" en cada fila.
    MOD-4: colWidths ampliados [8.0, 1.5, 1.5, 2.5, 2.5, 3.0] cm.
    """
    story = []
    story += _seccion_header("Despiece Técnico y Elementos del Proyecto", E)

    piezas = r.get("_estado_guardado", {}).get("piezas", [])

    # ── MOD-1: Referencia global del material para enriquecer descripción ──────
    # Combina categoría + referencia exacta del resultado.
    # Ej: "Mármol Café Pinta", "Sinterizado Ducal Gold", "Granito Vermont Brown"
    _cat_mat  = r.get("categoria", "")
    _ref_mat  = r.get("referencia", "")
    _nombres_mat = (f"{_cat_mat} {_ref_mat}".strip()
                    if _ref_mat and _ref_mat.strip()
                    else (_cat_mat.strip() or "Material"))

    hdr = [
        Paragraph("#", E["th_c"]),
        Paragraph("DESCRIPCIÓN / ÍTEM", E["th"]),
        Paragraph("CANT. / UNID.", E["th_c"]),
        Paragraph("P. UNITARIO", E["th_r"]),
        Paragraph("SUBTOTAL", E["th_r"]),
    ]
    filas = [hdr]

    if piezas:
        # Calcular total m² usando ml efectivo (ya absorbido cantidad × unitario)
        total_m2 = sum(p.get("ml", 1) * p.get("ancho_custom", 0.60) for p in piezas)
        for idx_p, p in enumerate(piezas, start=1):
            # ml ya es el total efectivo (ml_unitario × cantidad) guardado por app.py
            _ml_efectivo = p.get("ml", 1)
            _ml_unit     = p.get("ml_unitario", _ml_efectivo)  # longitud de UNA pieza
            _cantidad    = int(p.get("cantidad", 1))
            _ancho       = float(p.get("ancho_custom", 0.60))
            _m2_calc     = _ml_efectivo * _ancho                # m² total de la fila
            m2_p         = _m2_calc if _m2_calc > 0 else _ml_efectivo * _ancho
            prop         = (m2_p / total_m2) if total_m2 > 0 else (1 / len(piezas))
            precio_p     = precio_sugerido_total * prop          # subtotal de la fila

            # ── Unidad dinámica: área vs borde ──
            _tipo_pieza = p.get("ancho_tipo", "").lower()
            _es_area_p  = any(kw in _tipo_pieza for kw in ("piso", "fachada", "revestimiento"))

            if _es_area_p:
                _cant_unid_str = f"{_cantidad} u × {(_ml_unit * _ancho):.2f} m²"
                _qty_base  = m2_p
            else:
                _cant_unid_str = f"{_cantidad} u × {_ml_unit:.2f} ml"
                _qty_base  = _ml_efectivo

            pu = precio_p / _qty_base if _qty_base > 0 else 0

            # ── Descripción comercial: "Espacio en Material" ─────────
            _nombre_pieza = p.get("nombre", "—")
            _desc_enriq   = f"{_nombre_pieza} en {_nombres_mat}"

            filas.append([
                Paragraph(str(idx_p),                               E["cell_c"]),
                Paragraph(_desc_enriq,                              E["cell"]),
                Paragraph(_cant_unid_str,                           E["cell_c"]),
                Paragraph(_num(round(pu / 1000) * 1000),            E["cell_r"]),
                Paragraph(_num(round(precio_p / 1000) * 1000),      E["cell_br"]),
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

    # colWidths — Regla Matemática: suma de fracciones = 1.0 → ancho_util exacto
    # 5 columnas: [#/Ítem 5% | Descripción 45% | Unid/Cant 15% | P.Unitario 15% | Subtotal 20%]
    tbl = Table(filas, colWidths=[
        ancho_util * 0.05, ancho_util * 0.45, ancho_util * 0.15,
        ancho_util * 0.15, ancho_util * 0.20,
    ], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),  (-1,0),  C["header_dark"]),
        ("ROWBACKGROUNDS",(0,1),  (-1,-1), [C["zebra_a"], C["zebra_b"]]),
        ("TOPPADDING",    (0,0),  (-1,-1), 5),
        ("BOTTOMPADDING", (0,0),  (-1,-1), 5),
        ("LEFTPADDING",   (0,0),  (-1,-1), 7),
        ("RIGHTPADDING",  (0,0),  (-1,-1), 7),
        ("VALIGN",        (0,0),  (-1,-1), "TOP"),
        ("LINEBELOW",     (0,0),  (-1,-1), 0.3, C["border"]),
        ("BOX",           (0,0),  (-1,-1), 0.5, C["border"]),
    ]))
    story.append(tbl)

    # FIX-4: Nota Legal "A Todo Costo" — manejo de objeciones contractuales.
    # Clarifica que los precios unitarios absorben todos los costos del proyecto.
    nota_atodocosto = (
        "Nota Legal: Los valores unitarios presentados corresponden a la modalidad "
        "‘A Todo Costo’. Incluyen el suministro del material pétreo, mano de obra "
        "especializada de corte e instalación, insumos técnicos, herramientas y "
        "logística de transporte."
    )
    story.append(Table(
        [[Paragraph(nota_atodocosto, E["nota_legal"])]],
        colWidths=[_AU],
        style=TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#F7F9FC")),
            ("LEFTPADDING",   (0,0),(-1,-1), 10), ("RIGHTPADDING",  (0,0),(-1,-1),10),
            ("TOPPADDING",    (0,0),(-1,-1), 5),  ("BOTTOMPADDING", (0,0),(-1,-1),5),
            ("LINEABOVE",     (0,0),(-1, 0), 0.5, colors.HexColor("#6B85A0")),
            ("BOX",           (0,0),(-1,-1), 0.4, colors.HexColor("#C8D8E8")),
        ])
    ))

    return story


def _seccion_adicionales_alcance(E, C, adicionales_detalle, c7_adicionales):
    """
    BLOQUE PÁGINA 1 — ALCANCE DEL PROYECTO: Servicios Adicionales.
    Ubicación: Página 1, DESPUÉS de la Descripción y ANTES del Despiece Técnico.

    REGLA ESTRICTA — CERO HARDCODING:
    Itera EXCLUSIVAMENTE sobre adicionales_detalle (lista de dicts con nombre real
    y valor configurados por el usuario en la UI).
    Si está vacío → imprime "No se seleccionaron servicios adicionales."

    adicionales_detalle: lista de dicts con keys "concepto" y "valor"
    c7_adicionales: float — suma total de los adicionales
    """
    story = []
    story += _seccion_header("ALCANCE DEL PROYECTO: Servicios Adicionales", E)

    _s_hdr = ParagraphStyle("aaic_hdr", fontSize=7, fontName="Helvetica-Bold",
                             leading=9, textColor=colors.HexColor("#0D2137"),
                             letterSpacing=0.8)
    _s_item = ParagraphStyle("aaic_item", fontSize=7.5, fontName="Helvetica",
                              leading=10, textColor=colors.HexColor("#1C2B3A"))
    _s_val  = ParagraphStyle("aaic_val",  fontSize=7.5, fontName="Helvetica-Bold",
                              leading=10, textColor=colors.HexColor("#1B5FA8"),
                              alignment=TA_RIGHT)
    _s_tot_l = ParagraphStyle("aaic_tot_l", fontSize=7.5, fontName="Helvetica-Bold",
                               leading=10, textColor=colors.HexColor("#1B5FA8"))
    _s_tot_v = ParagraphStyle("aaic_tot_v", fontSize=7.5, fontName="Helvetica-Bold",
                               leading=10, textColor=colors.HexColor("#1B5FA8"),
                               alignment=TA_RIGHT)
    _s_val_hdr = ParagraphStyle("aaic_val_hdr", fontSize=7, fontName="Helvetica-Bold",
                                 leading=9, textColor=colors.HexColor("#0D2137"),
                                 alignment=TA_RIGHT)
    _s_vacio = ParagraphStyle("aaic_vacio", fontSize=7.5, fontName="Helvetica-Oblique",
                               leading=10, textColor=colors.HexColor("#6B85A0"))

    # ── Encabezado de columnas ─────────────────────────────────────────────────
    filas_aa = [[
        Paragraph("SERVICIO / ELEMENTO ADICIONAL", _s_hdr),
        Paragraph("VALOR", _s_val_hdr),
    ]]

    # ── Iteración DINÁMICA — EXCLUSIVAMENTE sobre adicionales_detalle ──────────
    # Los nombres vienen de la configuración del usuario en la UI.
    # No existe ningún texto quemado en este bloque.
    _items_con_valor = []
    if adicionales_detalle:
        for item in adicionales_detalle:
            nombre = (item.get("concepto") or item.get("nombre") or "").strip()
            if not nombre:
                nombre = "Servicio adicional"
            valor = float(item.get("valor", 0) or 0)
            if valor > 0:
                _items_con_valor.append((nombre, valor))
                filas_aa.append([
                    Paragraph(f"✔  {nombre}", _s_item),
                    Paragraph(_num(valor), _s_val),
                ])

    # ── Estado vacío: mensaje explícito cuando no hay servicios adicionales ────
    if not _items_con_valor:
        filas_aa.append([
            Paragraph("No se seleccionaron servicios adicionales.", _s_vacio),
            Paragraph("—", _s_val),
        ])
        c7_adicionales = 0.0

    # ── Fila de total (solo cuando hay ítems activos) ─────────────────────────
    if _items_con_valor and c7_adicionales and c7_adicionales > 0:
        filas_aa.append([
            Paragraph("Total servicios adicionales", _s_tot_l),
            Paragraph(_num(c7_adicionales), _s_tot_v),
        ])

    # colWidths: 75.3% + 24.7% = 100% de ancho_util (16.5 cm)
    tbl_aa = Table(filas_aa, colWidths=[ancho_util * 0.753, ancho_util * 0.247])
    tbl_aa.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0),  (-1, 0),  colors.HexColor("#EBF3FB")),
        ("ROWBACKGROUNDS",(0, 1),  (-1, -2), [colors.HexColor("#F7FAFD"),
                                               colors.HexColor("#FFFFFF")]),
        ("BACKGROUND",    (0, -1), (-1, -1), colors.HexColor("#EBF3FB")),
        ("LINEABOVE",     (0, 0),  (-1,  0), 1.5, colors.HexColor("#1B5FA8")),
        ("LINEBELOW",     (0, -1), (-1, -1), 1.5, colors.HexColor("#1B5FA8")),
        ("LINEBELOW",     (0, 0),  (-1, -2), 0.3, colors.HexColor("#C8D8E8")),
        ("TOPPADDING",    (0, 0),  (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0),  (-1, -1), 5),
        ("LEFTPADDING",   (0, 0),  (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0),  (-1, -1), 10),
        ("VALIGN",        (0, 0),  (-1, -1), "MIDDLE"),
        ("BOX",           (0, 0),  (-1, -1), 0.5, colors.HexColor("#C8D8E8")),
    ]))
    story.append(tbl_aa)
    return story



def _seccion_resumen_financiero(E, C, precio_sugerido_total, anticipo_pct, incluir_iva,
                                 c7_adicionales=0.0, adicionales_detalle=None):
    """
    SECCIÓN 3 — Resumen Financiero.
    Incluye fila discriminada de Costos Adicionales (c7_adicionales) cuando > 0,
    antes del bloque IVA/Total, para que el cliente vea exactamente qué paga por extras.
    Devuelve (story_list, precio_final_doc, anticipo_val).
    """
    story = []
    story += _seccion_header("Resumen Financiero", E)

    # (Los servicios adicionales se muestran en Página 1 — _seccion_adicionales_alcance)

    _s_adic_l = ParagraphStyle("adic_l", fontSize=8, fontName="Helvetica-Bold",
                                leading=11, textColor=colors.HexColor("#1B5FA8"))
    _s_adic_v = ParagraphStyle("adic_v", fontSize=8, fontName="Helvetica-Bold",
                                leading=11, textColor=colors.HexColor("#1B5FA8"), alignment=TA_RIGHT)

    filas_fin = []

    # Fila de Adicionales discriminada (visible solo si hay adicionales > 0)
    _tiene_adicionales = c7_adicionales and c7_adicionales > 0

    if incluir_iva:
        # ── MOD-3: Resumen Financiero reestructurado ──────────────────────────
        # Formato de referencia comercial de alta gama (4 filas alineadas derecha):
        #   Fila 1 — Subtotal            (precio sin IVA)
        #   Fila 2 — Costos Adicionales  (solo si c7_adicionales > 0)
        #   Fila 3 — Base gravable IVA 19% (Art. 468 E.T.)
        #   Fila 4 — Anticipo a pagar
        #   Fila 5 — Saldo contra entrega
        #   Fila 6 — TOTAL (bold, fondo oscuro)
        iva_val          = precio_sugerido_total * 0.19
        precio_final_doc = precio_sugerido_total + iva_val
        anticipo_val     = precio_final_doc * (anticipo_pct / 100)
        saldo_val        = precio_final_doc - anticipo_val

        filas_fin = []

        # Fila 1: Subtotal sin IVA
        filas_fin.append([
            Paragraph("Subtotal", E["cell_b"]),
            Paragraph(_num(precio_sugerido_total), E["cell_br"]),
        ])

        # Fila 2 (condicional): Costos Adicionales
        if _tiene_adicionales:
            filas_fin.append([
                Paragraph("Costos Adicionales", _s_adic_l),
                Paragraph(_num(c7_adicionales),  _s_adic_v),
            ])

        # Fila 3: Base gravable — IVA 19% (Art. 468 E.T.)
        filas_fin.append([
            Paragraph("Base gravable (subtotal) IVA 19% (Art. 468 E.T.)", E["iva_l"]),
            Paragraph(_num(iva_val), E["iva_v"]),
        ])

        # Fila 4: Anticipo
        filas_fin.append([
            Paragraph(f"ANTICIPO A PAGAR ({anticipo_pct}% del total)", E["anticipo_l"]),
            Paragraph(_num(anticipo_val), E["anticipo_v"]),
        ])

        # Fila 5: Saldo
        filas_fin.append([
            Paragraph(f"Saldo contra entrega ({100-anticipo_pct}%)",
                ParagraphStyle("sld",fontSize=7.5,fontName="Helvetica",leading=10,textColor=C["gray"])),
            Paragraph(_num(saldo_val),
                ParagraphStyle("sldv",fontSize=7.5,fontName="Helvetica",leading=10,textColor=C["gray"],alignment=TA_RIGHT)),
        ])

        # Fila 6: TOTAL con IVA — bold, fondo corporativo oscuro
        filas_fin.append([
            Paragraph("TOTAL", E["total_label"]),
            Paragraph(_num(precio_final_doc), E["total_val"]),
        ])

        # Índices para estilos de fondo (sin offset porque Adicionales va en pos. 1, no 0)
        _offset  = 0   # Subtotal siempre en pos 0; Adicionales inserta después
        _n_filas = len(filas_fin)
        idx_ant  = _n_filas - 3   # Fila Anticipo
        idx_tot  = _n_filas - 1   # Fila TOTAL (última)
    else:
        # ── MOD-3b: Resumen sin IVA — mismo patrón visual ─────────────────────
        precio_final_doc = precio_sugerido_total
        anticipo_val     = precio_final_doc * (anticipo_pct / 100)
        saldo_val        = precio_final_doc - anticipo_val

        filas_fin = []

        # Fila 1: Subtotal
        filas_fin.append([
            Paragraph("Subtotal", E["subtotal_l"]),
            Paragraph(_num(precio_final_doc), E["subtotal_v"]),
        ])

        # Fila 2 (condicional): Costos Adicionales
        if _tiene_adicionales:
            filas_fin.append([
                Paragraph("Costos Adicionales", _s_adic_l),
                Paragraph(_num(c7_adicionales),  _s_adic_v),
            ])

        # Fila 3: Anticipo
        filas_fin.append([
            Paragraph(f"ANTICIPO A PAGAR ({anticipo_pct}% del total)", E["anticipo_l"]),
            Paragraph(_num(anticipo_val), E["anticipo_v"]),
        ])

        # Fila 4: Saldo
        filas_fin.append([
            Paragraph(f"Saldo contra entrega ({100-anticipo_pct}%)",
                ParagraphStyle("sld2",fontSize=7.5,fontName="Helvetica",leading=10,textColor=C["gray"])),
            Paragraph(_num(saldo_val),
                ParagraphStyle("sldv2",fontSize=7.5,fontName="Helvetica",leading=10,textColor=C["gray"],alignment=TA_RIGHT)),
        ])

        # Fila 5: TOTAL sin IVA — bold, fondo corporativo oscuro
        filas_fin.append([
            Paragraph("TOTAL (SIN IVA)", E["total_label"]),
            Paragraph(_num(precio_final_doc), E["total_val"]),
        ])

        _offset  = 0
        _n_filas = len(filas_fin)
        idx_ant  = _n_filas - 3   # Fila Anticipo
        idx_tot  = _n_filas - 1   # Fila TOTAL (última)

    # ── MOD-3c: Estilos de tabla con índices dinámicos ───────────────────────────
    # Los índices idx_ant e idx_tot ya fueron calculados en cada rama (con/sin IVA).
    # La fila de Adicionales, cuando existe, siempre está en posición 1 (después de Subtotal).
    _adic_styles = []
    if _tiene_adicionales:
        _idx_adic = 1   # Adicionales siempre en pos 1 (después de Subtotal en pos 0)
        _adic_styles = [
            ("BACKGROUND",  (0,_idx_adic), (-1,_idx_adic), colors.HexColor("#EBF3FB")),
            ("LINEABOVE",   (0,_idx_adic), (-1,_idx_adic), 1.2, colors.HexColor("#1B5FA8")),
            ("LINEBELOW",   (0,_idx_adic), (-1,_idx_adic), 1.2, colors.HexColor("#1B5FA8")),
        ]

    tbl_fin = Table(filas_fin, colWidths=[_AU * 0.753, _AU * 0.247])
    tbl_fin.setStyle(TableStyle(
        _adic_styles + [
        ("ROWBACKGROUNDS", (0,0), (-1, idx_ant-1), [C["zebra_a"], C["zebra_b"]]),
        ("BACKGROUND",     (0,idx_ant), (-1,idx_ant), C["anticipo_bg"]),
        ("BACKGROUND",     (0,idx_tot), (-1,idx_tot), C["total_bg"]),
        ("LINEABOVE",      (0,idx_tot), (-1,idx_tot), 2.5, C["accent"]),
        ("TOPPADDING",     (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",  (0,0), (-1,-1), 6),
        ("LEFTPADDING",    (0,0), (-1,-1), 10),
        ("RIGHTPADDING",   (0,0), (-1,-1), 10),
        ("VALIGN",         (0,0), (-1,-1), "MIDDLE"),
        ("BOX",            (0,0), (-1,-1), 1.0, C["border"]),
        ("LINEBELOW",      (0,0), (-1,-2), 0.3, C["border"]),
    ]))
    story.append(KeepTogether([tbl_fin]))
    return story, precio_final_doc, anticipo_val


# ── Módulo: Matriz Dinámica de Inclusiones / Exclusiones ────────────────────

def _seccion_alcance(E, C, inclusiones=None, exclusiones=None):
    """
    BLOQUE 3 — Matriz Dinámica SaaS B2B: Inclusiones (✔) vs Exclusiones (✗).

    Implementación 100% Platypus Table:
      • Paragraph() en cada celda → wrap automático de texto largo garantizado.
      • Cabeceras centradas: INCLUYE (verde #166534) | NO INCLUYE (rojo #991B1B).
      • Zebra striping independiente por columna (gris neutro en pares).
      • Cell padding generoso (8 pt) para eliminar estrés visual.
      • Cuadrícula con bordes grises claros (#E2E8F0) para legibilidad cruzada.
      • Fallback a lista vacía si la UI no pasa valores.
    """
    _inc = inclusiones if inclusiones is not None else []
    _exc = exclusiones if exclusiones is not None else []

    story = []
    story += _seccion_header("Alcance de la Propuesta — Inclusiones y Exclusiones", E)

    # ── Paleta de la matriz ───────────────────────────────────────────────────
    _INC_HDR   = colors.HexColor("#166534")   # verde oscuro  — fondo cabecera INCLUYE
    _EXC_HDR   = colors.HexColor("#991B1B")   # rojo oscuro   — fondo cabecera NO INCLUYE
    _ZEBRA_INC = colors.HexColor("#F3F4F6")   # gris muy suave — filas pares inclusiones
    _ZEBRA_EXC = colors.HexColor("#F3F4F6")   # gris muy suave — filas pares exclusiones
    _GRID      = colors.HexColor("#E2E8F0")   # gris claro    — cuadrícula y bordes
    _WHITE     = colors.HexColor("#FFFFFF")   # blanco        — filas impares

    # ── Estilos tipográficos locales (9 pt, sin sangría, wrap automático) ─────
    _S_HDR_INC = ParagraphStyle(
        "_mhdr_inc", fontSize=9, fontName="Helvetica-Bold",
        leading=12, textColor=colors.HexColor("#FFFFFF"),
        alignment=TA_CENTER, spaceAfter=0, spaceBefore=0,
    )
    _S_HDR_EXC = ParagraphStyle(
        "_mhdr_exc", fontSize=9, fontName="Helvetica-Bold",
        leading=12, textColor=colors.HexColor("#FFFFFF"),
        alignment=TA_CENTER, spaceAfter=0, spaceBefore=0,
    )
    _S_INC = ParagraphStyle(
        "_minc", fontSize=9, fontName="Helvetica",
        leading=13, textColor=colors.HexColor("#14532D"),   # verde oscuro legible
        leftIndent=0, firstLineIndent=0, spaceAfter=0, spaceBefore=0,
        wordWrap="LTR",
    )
    _S_EXC = ParagraphStyle(
        "_mexc", fontSize=9, fontName="Helvetica",
        leading=13, textColor=colors.HexColor("#7F1D1D"),   # rojo oscuro legible
        leftIndent=0, firstLineIndent=0, spaceAfter=0, spaceBefore=0,
        wordWrap="LTR",
    )
    _S_EMPTY = ParagraphStyle(
        "_mempty", fontSize=9, fontName="Helvetica",
        leading=13, textColor=colors.HexColor("#FFFFFF"),
        spaceAfter=0, spaceBefore=0,
    )

    # ── Fila 0: cabeceras ────────────────────────────────────────────────────
    rows = [[
        Paragraph("✔  INCLUYE",    _S_HDR_INC),
        Paragraph("✖  NO INCLUYE", _S_HDR_EXC),
    ]]

    # ── Filas de datos: cada texto en un Paragraph → wrap automático ──────────
    _inc_items = _inc if _inc else ["—"]
    _exc_items = _exc if _exc else ["—"]
    _n_data = max(len(_inc_items), len(_exc_items))

    for _i in range(_n_data):
        _txt_inc = _inc_items[_i] if _i < len(_inc_items) else ""
        _txt_exc = _exc_items[_i] if _i < len(_exc_items) else ""
        # Párrafo inclusión: checkmark verde + texto completo
        _p_inc = (
            Paragraph(f"✔  {_txt_inc}", _S_INC)
            if _txt_inc else Paragraph("", _S_EMPTY)
        )
        # Párrafo exclusión: equis roja + texto completo
        _p_exc = (
            Paragraph(f"✖  {_txt_exc}", _S_EXC)
            if _txt_exc else Paragraph("", _S_EMPTY)
        )
        rows.append([_p_inc, _p_exc])

    # ── Tabla con colWidths fijos de 50% / 50% del ancho útil ────────────────
    _col_w = _AU * 0.5
    tbl_al = Table(rows, colWidths=[_col_w, _col_w], repeatRows=1)

    # ── Estilos base de la tabla ──────────────────────────────────────────────
    _ts = [
        # Cabeceras con fondos corporativos
        ("BACKGROUND",    (0, 0), (0, 0),  _INC_HDR),
        ("BACKGROUND",    (1, 0), (1, 0),  _EXC_HDR),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        # Padding generoso para legibilidad sin estrés visual
        ("TOPPADDING",    (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        # Cuadrícula con bordes grises claros
        ("GRID",          (0, 0), (-1, -1), 0.5, _GRID),
        ("BOX",           (0, 0), (-1, -1), 1.0, _GRID),
        # Separador vertical central más visible
        ("LINEBEFORE",    (1, 0), (1, -1),  1.0, _GRID),
        # Filas de datos: blanco por defecto
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_WHITE, _WHITE]),
    ]

    # ── Zebra striping independiente por columna (filas pares = índice par) ───
    for _ri in range(1, len(rows)):
        if _ri % 2 == 0:   # filas pares (2, 4, 6…) → gris suave
            _ts.append(("BACKGROUND", (0, _ri), (0, _ri), _ZEBRA_INC))
            _ts.append(("BACKGROUND", (1, _ri), (1, _ri), _ZEBRA_EXC))

    tbl_al.setStyle(TableStyle(_ts))
    story.append(tbl_al)
    return story

# ── Módulo: Términos y Condiciones ────────────────────────────────────────────

def _seccion_terminos(E, C, nota_iva, anticipo_pct):
    """
    SECCIÓN 4 — Términos y Condiciones Comerciales.
    Diseño limpio: título azul oscuro + viñetas sin tabla encajonada.
    """
    story = []
    story += _seccion_header("Términos y Condiciones Comerciales", E)

    _titulo_tc = ParagraphStyle(
        "tc_titulo", fontSize=8, fontName="Helvetica-Bold",
        leading=11, textColor=colors.HexColor("#0D2137"),
        spaceAfter=4,
    )
    _viñeta_tc = ParagraphStyle(
        "tc_viñeta", fontSize=6.5, fontName="Helvetica",
        leading=9, textColor=colors.HexColor("#4A5568"),
        leftIndent=12, firstLineIndent=-8, spaceAfter=3,
    )

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

    bloques = [Paragraph("CONDICIONES COMERCIALES", _titulo_tc)]
    for item in condiciones_items:
        bloques.append(Paragraph(f"• {item}", _viñeta_tc))

    story.append(KeepTogether(bloques))
    return story


def _bloque_firma_cliente(E, C):
    """
    FIX-3 — Bloque contractual de aceptación con valor probatorio.
    KeepTogether garantiza que no se divida entre páginas.
    Debe insertarse inmediatamente después de _seccion_terminos() en los 3 PDFs.
    """
    linea_blanca = "_" * 42

    filas_firma = [
        [Paragraph("ACEPTADO Y APROBADO POR EL CLIENTE:", E["firma_titulo"]), ""],
        [Paragraph("Firma:", E["firma_campo"]),
         Paragraph(linea_blanca, E["firma_campo"])],
        [Paragraph("Nombre / Razón Social:", E["firma_campo"]),
         Paragraph(linea_blanca, E["firma_campo"])],
        [Paragraph("C.C. / NIT:", E["firma_campo"]),
         Paragraph(linea_blanca, E["firma_campo"])],
        [Paragraph("Fecha de aprobación:", E["firma_campo"]),
         Paragraph(linea_blanca, E["firma_campo"])],
    ]

    tbl_firma = Table(filas_firma, colWidths=[_AU * 0.314, _AU * 0.686])
    tbl_firma.setStyle(TableStyle([
        ("SPAN",          (0, 0), (-1, 0)),          # título ocupa ambas columnas
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#EEF4FB")),
        ("BACKGROUND",    (0, 1), (-1, -1), colors.HexColor("#FAFCFF")),
        ("LINEABOVE",     (0, 0), (-1,  0), 1.5, colors.HexColor("#1B5FA8")),
        ("LINEBELOW",     (0,-1), (-1, -1), 0.5, colors.HexColor("#C8D8E8")),
        ("LINEBELOW",     (0, 1), (-1, -2), 0.3, colors.HexColor("#E0E8F0")),
        ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#C8D8E8")),
        ("TOPPADDING",    (0, 0), (-1,  0), 7),
        ("BOTTOMPADDING", (0, 0), (-1,  0), 7),
        # Espacio físico amplio en campos de firma para escritura a bolígrafo
        ("TOPPADDING",    (0, 1), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 14),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("VALIGN",        (0, 0), (-1, -1), "BOTTOM"),
    ]))

    return [
        Spacer(1, 8),
        KeepTogether([tbl_firma]),
    ]


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
        leftMargin=1.4*cm, rightMargin=1.4*cm,
        topMargin=1.0*cm,  bottomMargin=1.2*cm,
        title=f"Propuesta Comercial {numero}")

    r = resultado
    # ── Construir detalle de adicionales de forma dinámica ─────────────────────
    # Se leen los nombres de concepto DIRECTAMENTE desde la lista guardada en el
    # estado — sin ningún texto fijo. Si el usuario cambió el nombre en la UI de
    # Parámetros, ese nombre nuevo aparecerá en el PDF.
    _c7_adicionales = float(r.get("c7_adicionales", 0) or 0)
    _adicionales_detalle = []
    _estado_g = r.get("_estado_guardado", {})
    if _c7_adicionales > 0 and _estado_g.get("adicionales_activos"):
        from parametros import ADICIONALES, ETAPAS_OBRA
        _cantidades_add = _estado_g.get("cantidades_add", [])
        _etapa_r        = _estado_g.get("etapa_label", "")
        _etapa_val = ETAPAS_OBRA.get(_etapa_r, list(ETAPAS_OBRA.values())[0])
        # adicionales_lista: lista guardada en el estado (puede ser la del usuario o
        # el default de parametros). Cada elemento es un dict con clave "concepto"
        # que contiene el nombre tal como lo configuró el usuario.
        _adic_lista = _estado_g.get("adicionales_lista", ADICIONALES)
        for i, _ad in enumerate(_adic_lista):
            _cant = float(_cantidades_add[i]) if i < len(_cantidades_add) else 0.0
            if _cant > 0:
                _precio_unit = _ad.get(_etapa_val, 0)
                _valor = _cant * _precio_unit
                if _valor > 0:
                    # "concepto" es el nombre real configurado por el usuario en la UI
                    _adicionales_detalle.append({
                        "concepto": _ad.get("concepto", "—"),
                        "valor": _valor,
                    })

    # ══════════════════════════════════════════════════════════════════
    # PÁGINA 1 — Encabezado · Datos del Cliente · Despiece Técnico
    # ══════════════════════════════════════════════════════════════════
    story = []

    # ① ENCABEZADO
    story.append(_encabezado_doc(E, C, "PROPUESTA COMERCIAL", numero, fecha_str,
                                  emp, _lb, valido_hasta))
    story.append(Spacer(1, 7))
    story.append(Table([[Paragraph(
        f"Fecha: {_hoy().strftime('%d/%m/%Y')}  ·  Válida hasta: {valido_hasta}",
        ParagraphStyle("badge",fontSize=6.5,fontName="Helvetica",leading=9,textColor=C["gray"])
    )]], colWidths=[_AU], style=TableStyle([
        ("BACKGROUND",  (0,0),(-1,-1), C["ultralight"]),
        ("TOPPADDING",  (0,0),(-1,-1), 4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING", (0,0),(-1,-1), 10),
        ("LINEABOVE",   (0,0),(-1, 0), 0.5, C["secondary"]),
    ])))
    story.append(Spacer(1, 7))

    # ② DATOS DEL CLIENTE
    story += _seccion_header("Datos del Cliente y Condiciones", E)
    datos_filas = []
    if r.get("nombre_cliente"):
        datos_filas.append(("Para", r["nombre_cliente"]))
    # ── MOD-2: Resumen automático del campo Proyecto ────────────────────────────
    # En lugar de mostrar solo "Baño", compone una cadena con tipo + piezas.
    # Ejemplo: "Baño - Incluye: Lavamanos con poceta, Mueble de baño, Zócalo"
    # Si supera 80 caracteres se trunca añadiendo "..."
    _piezas_doc = r.get("_estado_guardado", {}).get("piezas", [])
    _tipo_proy  = r.get("tipo_proyecto", "—")
    if _piezas_doc:
        _nombres_piezas = ", ".join(p.get("nombre", "—") for p in _piezas_doc)
        _resumen_proy   = f"{_tipo_proy} - Incluye: {_nombres_piezas}"
        if len(_resumen_proy) > 80:
            _resumen_proy = _resumen_proy[:77] + "..."
    else:
        _resumen_proy = _tipo_proy

    datos_filas += [
        ("Ciudad",        emp.get("ciudad", "Barranquilla")),
        ("Proyecto",      _resumen_proy),                                    # ← MOD-2
        ("Forma de pago", f"{anticipo_pct}% anticipo  ·  {100-anticipo_pct}% contra entrega"),
        ("Condiciones",   f"Validez: {dias_validez} días  ·  Entrega estimada: {dias_entrega} días"),
    ]
    story.append(_tabla_datos_cliente(E, C, datos_filas))
    story.append(Spacer(1, 7))

    # ③ ALCANCE DEL PROYECTO: Servicios Adicionales (oculta si no hay adicionales)
    #    Validamos c7_adicionales para no imprimir secciones vacías en el PDF.
    # Usamos _c7_adicionales que ya fue calculado al inicio de la función
    if _c7_adicionales > 0:
        story.append(Spacer(1, 7))
        story += _seccion_adicionales_alcance(E, C, _adicionales_detalle, _c7_adicionales)

    # ④ DESPIECE TÉCNICO
    precio_sugerido_total = r.get("precio_sugerido", 0)
    story.append(Spacer(1, 7))
    story += _seccion_despiece_tecnico(E, C, r, incluir_iva, anticipo_pct, precio_sugerido_total)

    # ③b INCLUYE / NO INCLUYE — Matriz Dinámica con listas de la UI
    story.append(Spacer(1, 7))
    story += _seccion_alcance(E, C, inclusiones=inclusiones, exclusiones=exclusiones)

    # ══════════════════════════════════════════════════════════════════
    # SALTO DE PÁGINA — Página 2 inicia con Resumen Financiero
    # ══════════════════════════════════════════════════════════════════
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════
    # PÁGINA 2 — Resumen Financiero · Alcance · Términos · Firma
    # ══════════════════════════════════════════════════════════════════

    # ④ RESUMEN FINANCIERO (con adicionales discriminados)
    fin_story, precio_final_doc, anticipo_val = _seccion_resumen_financiero(
        E, C, precio_sugerido_total, anticipo_pct, incluir_iva,
        c7_adicionales=_c7_adicionales,
        adicionales_detalle=_adicionales_detalle)
    story += fin_story
    valor_letras = _numero_a_letras(int(round(precio_final_doc)))
    story.append(Table([[Paragraph(f"Son: {valor_letras}", E["letras"])]],
        colWidths=[_AU], style=TableStyle([
            ("BACKGROUND",   (0,0),(-1,-1), C["primary"]),
            ("TOPPADDING",   (0,0),(-1,-1), 3), ("BOTTOMPADDING",(0,0),(-1,-1),6),
            ("LEFTPADDING",  (0,0),(-1,-1), 10),
        ])))
    story.append(Spacer(1, 10))

    # ⑤ TÉRMINOS Y CONDICIONES
    nota_iva = (
        "Propuesta con IVA del 19% (Art. 468 E.T.) — Responsable de IVA — Régimen Común. "
        if incluir_iva else
        "Propuesta sin IVA — Régimen Simplificado (Art. 499 E.T.). "
    )
    story += _seccion_terminos(E, C, nota_iva, anticipo_pct)
    # Bloque contractual de aceptación con KeepTogether
    story += _bloque_firma_cliente(E, C)
    story.append(Spacer(1, 5))
    story += _footer_doc(E, C, emp.get("nombre",""), fecha_str, numero, ciudad=emp.get("ciudad","Barranquilla"))

    doc.build(story)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# COTIZACIÓN AIU
# ══════════════════════════════════════════════════════════════════════════════

def generar_pdf_cotizacion_aiu(resultado, numero=None, empresa_info=None, logo_bytes=None, incluir_iva=True):
    """PDF AIU. IVA (19%) SOLO sobre Utilidad (U) — Decreto 1372/92.
    Si incluir_iva=False (o resultado['incluir_iva']==False), la fila IVA
    muestra 'Exento' y $0 — sin alterar el diseño premium.
    """
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
        leftMargin=1.4*cm, rightMargin=1.4*cm,
        topMargin=1.0*cm,  bottomMargin=1.2*cm,
        title=f"Propuesta AIU {numero}")

    r = resultado
    story = []

    # ① ENCABEZADO
    story.append(_encabezado_doc(E, C, "PROPUESTA AIU — OBRA PUBLICA", numero, fecha_str,
                                  emp, _lb, valido_hasta))
    story.append(Spacer(1, 7))
    story.append(Table([[Paragraph(
        f"Fecha: {_hoy().strftime('%d/%m/%Y')}  ·  Válida hasta: {valido_hasta}  ·  "
        "Tipo: AIU — Administración, Imprevistos y Utilidad",
        ParagraphStyle("badge2",fontSize=6.5,fontName="Helvetica",leading=9,textColor=C["gray"])
    )]], colWidths=[_AU], style=TableStyle([
        ("BACKGROUND",  (0,0),(-1,-1), C["ultralight"]),
        ("TOPPADDING",  (0,0),(-1,-1), 4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING", (0,0),(-1,-1), 10),
        ("LINEABOVE",   (0,0),(-1, 0), 0.5, C["secondary"]),
    ])))
    story.append(Spacer(1, 7))

    # Datos contratante
    story += _seccion_header("Datos del Contratante", E)
    cliente_nombre = r.get("_estado_guardado", {}).get("nombre_cliente", r.get("nombre_cliente",""))
    datos_filas = []
    if cliente_nombre:
        datos_filas.append(("Para", cliente_nombre))
    datos_filas += [
        ("Ciudad",           emp.get("ciudad","Barranquilla")),
        ("Tipo de contrato", "Licitación / Proyecto Constructora — Estructura AIU"),
        ("Forma de pago",    f"{anticipo_pct}% anticipo  ·  {100-anticipo_pct}% contra acta de entrega"),
        ("Condiciones",      f"Validez: {dias_validez} días  ·  Entrega estimada: {dias_entrega} días"),
    ]
    story.append(_tabla_datos_cliente(E, C, datos_filas))
    story.append(Spacer(1, 7))

    # ② COSTO DIRECTO (CD)
    story += _seccion_header("Costo Directo (CD) — Items del Contrato", E)
    aiu_items = r.get("_estado_guardado", {}).get("aiu_items", [])
    cd = r.get("cd", r.get("costo_total", 0))

    cd_filas = [[
        Paragraph("DESCRIPCION / ITEM", E["th"]),
        Paragraph("UNID.", E["th_c"]),
        Paragraph("CANT.", E["th_c"]),
        Paragraph("P. UNIT.", E["th_r"]),
        Paragraph("SUBTOTAL", E["th_r"]),
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
            Paragraph("Costo Directo Total", E["cell"]),
            Paragraph("glb", E["cell_c"]),
            Paragraph("1",   E["cell_c"]),
            Paragraph(_num(cd), E["cell_r"]),
            Paragraph(_num(cd), E["cell_br"]),
        ])
    cd_filas.append([
        Paragraph("COSTO DIRECTO (CD)", E["subtotal_l"]),
        Paragraph("", E["cell_c"]), Paragraph("", E["cell_c"]), Paragraph("", E["cell_c"]),
        Paragraph(_num(cd), E["subtotal_v"]),
    ])
    tbl_cd = Table(cd_filas, colWidths=[
        _AU * 0.470, _AU * 0.078, _AU * 0.090, _AU * 0.181, _AU * 0.181,
    ], repeatRows=1)
    tbl_cd.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),  (-1,0),  C["header_dark"]),
        ("ROWBACKGROUNDS",(0,1),  (-1,-2), [C["zebra_a"], C["zebra_b"]]),
        ("BACKGROUND",    (0,-1), (-1,-1), C["light"]),
        ("SPAN",          (0,-1), (3,-1)),
        ("TOPPADDING",    (0,0),  (-1,-1), 5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("LEFTPADDING",   (0,0),  (-1,-1), 7), ("RIGHTPADDING", (0,0),(-1,-1),7),
        ("VALIGN",        (0,0),  (-1,-1), "TOP"),
        ("LINEBELOW",     (0,0),  (-1,-1), 0.3, C["border"]),
        ("BOX",           (0,0),  (-1,-1), 0.5, C["border"]),
    ]))
    story.append(tbl_cd)
    story.append(Spacer(1, 7))

    # ③ ESTRUCTURA AIU — Resumen Financiero Profesionalizado
    # Arquitectura de 3 bloques Platypus:
    #   BLOQUE 1: CD destacado (fondo azul claro, borde izquierdo corporativo)
    #   BLOQUE 2: A / I / U + IVA (fondo gris sutil, borde izquierdo dorado)
    #   BLOQUE 3: Logística / Viáticos + Anticipo + TOTAL (fondo #1A252C)
    story += _seccion_header("Estructura AIU — Desglose del Precio del Contrato", E)

    pct_a = r.get("pct_a", 2.0); pct_i = r.get("pct_i", 2.0); pct_u = r.get("pct_u", 5.0)
    val_a = r.get("val_a", cd * pct_a / 100); val_i = r.get("val_i", cd * pct_i / 100)
    val_u = r.get("val_u", cd * pct_u / 100)
    # incluir_iva: parámetro explícito > clave en el resultado > default True
    incluir_iva = incluir_iva and r.get("incluir_iva", True)
    val_iva = r.get("val_iva", val_u * 0.19) if incluir_iva else 0.0
    logistica = r.get("logistica", 0); viaticos = r.get("viaticos", 0)
    precio_total = r.get("precio_total", cd + val_a + val_i + val_u + val_iva + logistica + viaticos)
    anticipo_val = precio_total * (anticipo_pct / 100)

    # ── Estilos locales ───────────────────────────────────────────────────────
    _CD_BG      = colors.HexColor("#E8F0FB")   # Fondo bloque CD
    _AIU_BG     = colors.HexColor("#F4F6F9")   # Fondo bloque A/I/U
    _TOTAL_BG   = colors.HexColor("#1A252C")   # Fondo fila TOTAL DEL CONTRATO
    _BORDE_CD   = colors.HexColor("#1B5FA8")   # Borde izquierdo bloque CD
    _BORDE_AIU  = colors.HexColor("#C9A84C")   # Borde izquierdo bloque AIU

    s_cd_lbl  = ParagraphStyle("s_cd_lbl",  fontSize=9.5, fontName="Helvetica-Bold",
                                leading=12, textColor=colors.HexColor("#0D2137"))
    s_cd_val  = ParagraphStyle("s_cd_val",  fontSize=9.5, fontName="Helvetica-Bold",
                                leading=12, textColor=colors.HexColor("#0D2137"), alignment=TA_RIGHT)
    s_cd_sub  = ParagraphStyle("s_cd_sub",  fontSize=7,   fontName="Helvetica",
                                leading=9,  textColor=C["gray"])

    s_aiu_lbl = ParagraphStyle("s_aiu_lbl", fontSize=8,   fontName="Helvetica",
                                leading=10, textColor=C["text"])
    s_aiu_pct = ParagraphStyle("s_aiu_pct", fontSize=8,   fontName="Helvetica-Bold",
                                leading=10, textColor=C["secondary"], alignment=TA_CENTER)
    s_aiu_val = ParagraphStyle("s_aiu_val", fontSize=8,   fontName="Helvetica-Bold",
                                leading=10, textColor=C["text"], alignment=TA_RIGHT)
    s_iva_lbl = ParagraphStyle("s_iva_lbl", fontSize=7.5, fontName="Helvetica-Oblique",
                                leading=10, textColor=C["secondary"])
    s_iva_val = ParagraphStyle("s_iva_val", fontSize=7.5, fontName="Helvetica-Bold",
                                leading=10, textColor=C["secondary"], alignment=TA_RIGHT)
    s_tot_lbl = ParagraphStyle("s_tot_lbl", fontSize=11,  fontName="Helvetica-Bold",
                                leading=14, textColor=C["white"])
    s_tot_val = ParagraphStyle("s_tot_val", fontSize=12,  fontName="Helvetica-Bold",
                                leading=15, textColor=C["accent"], alignment=TA_RIGHT)
    s_ant_lbl = ParagraphStyle("s_ant_lbl", fontSize=8,   fontName="Helvetica-Bold",
                                leading=10, textColor=C["accent"])
    s_ant_val = ParagraphStyle("s_ant_val", fontSize=8,   fontName="Helvetica-Bold",
                                leading=10, textColor=C["accent"], alignment=TA_RIGHT)
    s_log_lbl = ParagraphStyle("s_log_lbl", fontSize=7.5, fontName="Helvetica",
                                leading=9,  textColor=C["gray"])
    s_log_val = ParagraphStyle("s_log_val", fontSize=7.5, fontName="Helvetica",
                                leading=9,  textColor=C["gray"], alignment=TA_RIGHT)

    COL_W = [_AU * 0.633, _AU * 0.121, _AU * 0.247]  # [Concepto | % | Valor] — suma = _AU

    # ── BLOQUE 1: COSTO DIRECTO (CD) ─────────────────────────────────────────
    tbl_cd_hdr = Table([[
        Paragraph("COSTO DIRECTO (CD)", s_cd_lbl),
        Paragraph("100%", s_aiu_pct),
        Paragraph(_num(cd), s_cd_val),
    ]], colWidths=COL_W)
    tbl_cd_hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), _CD_BG),
        ("LINEABOVE",     (0,0),(-1, 0), 1.5, _BORDE_CD),
        ("LINEBEFORE",    (0,0),(0, -1), 3.0, _BORDE_CD),
        ("TOPPADDING",    (0,0),(-1,-1), 9),
        ("BOTTOMPADDING", (0,0),(-1,-1), 9),
        ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ("RIGHTPADDING",  (0,0),(-1,-1), 10),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("BOX",           (0,0),(-1,-1), 0.5, C["border"]),
    ]))
    story.append(tbl_cd_hdr)

    # ── BLOQUE 2: COMPONENTES A / I / U + IVA ────────────────────────────────
    filas_aiu_comp = [
        [Paragraph(f"A — Administración  ({pct_a:.1f}% sobre CD)", s_aiu_lbl),
         Paragraph(f"{pct_a:.1f}%", s_aiu_pct),
         Paragraph(_num(val_a), s_aiu_val)],
        [Paragraph(f"I — Imprevistos  ({pct_i:.1f}% sobre CD)", s_aiu_lbl),
         Paragraph(f"{pct_i:.1f}%", s_aiu_pct),
         Paragraph(_num(val_i), s_aiu_val)],
        [Paragraph(f"U — Utilidad  ({pct_u:.1f}% sobre CD)", s_aiu_lbl),
         Paragraph(f"{pct_u:.1f}%", s_aiu_pct),
         Paragraph(_num(val_u), s_aiu_val)],
        # Fila IVA — visualmente separada dentro del mismo bloque
        # Label y valor cambian dinámicamente según si IVA aplica o no
        [Paragraph(
            "IVA 19%  (Sólo sobre Utilidad — Decreto 1372/92)" if incluir_iva
            else "IVA  (Exento — Régimen Simplificado Art. 499 E.T.)",
            s_iva_lbl),
         Paragraph("19%" if incluir_iva else "0%", s_iva_val),
         Paragraph(_num(val_iva), s_iva_val)],
    ]
    # Tinte de la fila IVA: azul claro si gravado, verde muy suave si exento
    _iva_bg = colors.HexColor("#EEF3FB") if incluir_iva else colors.HexColor("#EBF7EE")
    tbl_aiu_comp = Table(filas_aiu_comp, colWidths=COL_W)
    tbl_aiu_comp.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), _AIU_BG),
        ("LINEBEFORE",    (0,0),(0,-1),  3.0, _BORDE_AIU),
        ("LINEABOVE",     (0,3),(-1,3),  0.8, C["border"]),   # separador antes de IVA
        ("BACKGROUND",    (0,3),(-1,3),  _iva_bg),            # azul=gravado / verde=exento
        ("TOPPADDING",    (0,0),(-1,-1), 6),
        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
        ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ("RIGHTPADDING",  (0,0),(-1,-1), 10),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("LINEBELOW",     (0,0),(-1,-1), 0.3, C["border"]),
        ("BOX",           (0,0),(-1,-1), 0.5, C["border"]),
    ]))
    story.append(KeepTogether([tbl_aiu_comp]))

    # ── BLOQUE 3: Logística / Viáticos (si aplica) + Anticipo + TOTAL ─────────
    filas_extra = []
    if logistica > 0:
        filas_extra.append([
            Paragraph("Logística y transporte integrada", s_log_lbl),
            Paragraph("—", s_log_lbl),
            Paragraph(_num(logistica), s_log_val),
        ])
    if viaticos > 0:
        filas_extra.append([
            Paragraph("Viáticos y gastos foráneos", s_log_lbl),
            Paragraph("—", s_log_lbl),
            Paragraph(_num(viaticos), s_log_val),
        ])
    filas_extra.append([
        Paragraph(f"ANTICIPO A PAGAR  ({anticipo_pct}% del total)", s_ant_lbl),
        Paragraph(f"{anticipo_pct}%", s_ant_val),
        Paragraph(_num(anticipo_val), s_ant_val),
    ])
    # Fila TOTAL — tipografía máxima + fondo corporativo oscuro #1A252C
    filas_extra.append([
        Paragraph("TOTAL DEL CONTRATO", s_tot_lbl),
        Paragraph("", s_tot_lbl),
        Paragraph(_num(precio_total), s_tot_val),
    ])
    idx_ant_extra = len(filas_extra) - 2
    idx_tot_extra = len(filas_extra) - 1

    tbl_extra = Table(filas_extra, colWidths=COL_W)
    tbl_extra.setStyle(TableStyle([
        ("ROWBACKGROUNDS",  (0,0),(-1, idx_ant_extra-1), [C["zebra_a"], C["zebra_b"]]),
        ("BACKGROUND",      (0,idx_ant_extra),(-1,idx_ant_extra), C["anticipo_bg"]),
        ("BACKGROUND",      (0,idx_tot_extra),(-1,idx_tot_extra), _TOTAL_BG),
        ("LINEABOVE",       (0,idx_tot_extra),(-1,idx_tot_extra), 3.0, C["accent"]),
        ("TOPPADDING",      (0,0),(-1,-2), 6),
        ("BOTTOMPADDING",   (0,0),(-1,-2), 6),
        ("TOPPADDING",      (0,idx_tot_extra),(-1,idx_tot_extra), 12),
        ("BOTTOMPADDING",   (0,idx_tot_extra),(-1,idx_tot_extra), 12),
        ("LEFTPADDING",     (0,0),(-1,-1), 10),
        ("RIGHTPADDING",    (0,0),(-1,-1), 10),
        ("VALIGN",          (0,0),(-1,-1), "MIDDLE"),
        ("LINEBELOW",       (0,0),(-1,-2), 0.3, C["border"]),
        ("BOX",             (0,0),(-1,-1), 0.5, C["border"]),
    ]))
    story.append(KeepTogether([tbl_extra]))

    valor_letras = _numero_a_letras(int(round(precio_total)))
    story.append(Table([[Paragraph(f"Son: {valor_letras}", E["letras"])]],
        colWidths=[_AU], style=TableStyle([
            ("BACKGROUND",   (0,0),(-1,-1), C["primary"]),
            ("TOPPADDING",   (0,0),(-1,-1), 3), ("BOTTOMPADDING",(0,0),(-1,-1),6),
            ("LEFTPADDING",  (0,0),(-1,-1), 10),
        ])))
    story.append(Spacer(1, 7))

    # ④ NOTA TRIBUTARIA + T&C
    nota_aiu = (
        "En contratos bajo estructura AIU, el IVA (19%) aplica exclusivamente sobre la "
        "Utilidad (U), conforme al Art. 3 del Decreto 1372/1992 y conceptos DIAN. "
        "El IVA NO se aplica sobre Costo Directo (CD), Administración (A) ni Imprevistos (I). "
        f"Anticipo requerido: {anticipo_pct}% del total al inicio de la obra. "
        "Barranquilla, Colombia."
    )
    story += _seccion_terminos(E, C, nota_aiu, anticipo_pct)
    # FIX-3: Bloque contractual de aceptación con KeepTogether
    story += _bloque_firma_cliente(E, C)
    story.append(Spacer(1, 5))
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

    # FIX-1: Título tributario dinámico — la DIAN prohíbe "Cuenta de Cobro" con IVA.
    # Con IVA → PRE-FACTURA / DOCUMENTO PROFORMA (régimen común responsable IVA)
    # Sin IVA → CUENTA DE COBRO (DOCUMENTO SOPORTE) (régimen simplificado)
    _titulo_doc = (
        "PRE-FACTURA / DOCUMENTO PROFORMA"
        if (incluir_iva and not es_aiu) else
        "CUENTA DE COBRO (DOCUMENTO SOPORTE)"
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
        leftMargin=1.4*cm, rightMargin=1.4*cm,
        topMargin=1.0*cm,  bottomMargin=1.2*cm,
        title=f"{_titulo_doc} {numero}")

    story = []
    story.append(_encabezado_doc(E, C, _titulo_doc, numero, fecha_str, emp, _lb))
    story.append(Spacer(1, 7))

    story += _seccion_header("Quien Cobra", E)
    story.append(_tabla_datos_cliente(E, C, [
        ("Nombre / Razon Social", datos_prestador.get("nombre","—")),
        ("NIT / CC",              datos_prestador.get("nit_cc", datos_prestador.get("nit","—"))),
        ("Direccion",             datos_prestador.get("direccion", datos_prestador.get("ciudad","—"))),
        ("Telefono",              datos_prestador.get("telefono", datos_prestador.get("tel","—"))),
    ]))
    story.append(Spacer(1, 7))

    story += _seccion_header("Quien Paga", E)
    story.append(_tabla_datos_cliente(E, C, [
        ("Nombre / Razon Social", datos_pagador.get("nombre","—")),
        ("NIT / CC",              datos_pagador.get("nit","—")),
        ("Direccion",             datos_pagador.get("direccion","—")),
    ]))
    story.append(Spacer(1, 7))

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

    story += _seccion_header("Descripcion del Servicio / Concepto", E)
    tbl_serv = Table([[Paragraph(descripcion_servicio, E["cell"])]], colWidths=[_AU])
    tbl_serv.setStyle(TableStyle([
        ("BACKGROUND",  (0,0),(-1,-1), C["ultralight"]),
        ("TOPPADDING",  (0,0),(-1,-1), 8), ("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("LEFTPADDING", (0,0),(-1,-1), 10), ("RIGHTPADDING",(0,0),(-1,-1),10),
        ("BOX",         (0,0),(-1,-1), 0.5, C["border"]),
        ("LINEABOVE",   (0,0),(-1, 0), 1.0, C["secondary"]),
    ]))
    story.append(tbl_serv)
    story.append(Spacer(1, 7))

    story += _seccion_header("Valor del Cobro", E)
    if incluir_iva and not es_aiu:
        filas_val = [
            [Paragraph("Valor total del servicio (sin IVA)",       E["cell_b"]),   Paragraph(_num(precio_base),      E["cell_br"])],
            [Paragraph("IVA 19% (Art. 468 E.T.)",                   E["iva_l"]),    Paragraph(_num(iva),              E["iva_v"])],
            [Paragraph("Total (IVA incluido)",                      E["subtotal_l"]),Paragraph(_num(valor_total),     E["subtotal_v"])],
            [Paragraph(f"ANTICIPO A COBRAR ({anticipo_pct}%)",       E["anticipo_l"]),Paragraph(_num(valor_anticipo), E["anticipo_v"])],
            [Paragraph(f"Saldo contra entrega ({100-anticipo_pct}%)",
                ParagraphStyle("sl1",fontSize=7.5,fontName="Helvetica",leading=10,textColor=C["gray"])),
             Paragraph(_num(valor_saldo),
                ParagraphStyle("slv1",fontSize=7.5,fontName="Helvetica",leading=10,textColor=C["gray"],alignment=TA_RIGHT))],
            [Paragraph("VALOR COBRADO EN ESTE DOCUMENTO", E["total_label"]), Paragraph(_num(valor_anticipo), E["total_val"])],
        ]
        idx_ant, idx_tot = 3, 5
    else:
        filas_val = [
            [Paragraph("Valor total de la cotizacion",              E["subtotal_l"]),Paragraph(_num(valor_total),   E["subtotal_v"])],
            [Paragraph(f"ANTICIPO A COBRAR ({anticipo_pct}%)",       E["anticipo_l"]),Paragraph(_num(valor_anticipo),E["anticipo_v"])],
            [Paragraph(f"Saldo contra entrega ({100-anticipo_pct}%)",
                ParagraphStyle("sl2",fontSize=7.5,fontName="Helvetica",leading=10,textColor=C["gray"])),
             Paragraph(_num(valor_saldo),
                ParagraphStyle("slv2",fontSize=7.5,fontName="Helvetica",leading=10,textColor=C["gray"],alignment=TA_RIGHT))],
            [Paragraph("VALOR COBRADO EN ESTE DOCUMENTO", E["total_label"]), Paragraph(_num(valor_anticipo), E["total_val"])],
        ]
        idx_ant, idx_tot = 1, 3

    tbl_val = Table(filas_val, colWidths=[_AU * 0.753, _AU * 0.247])
    tbl_val.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0,0), (-1,idx_ant-1), [C["zebra_a"], C["zebra_b"]]),
        ("BACKGROUND",     (0,idx_ant), (-1,idx_ant), C["anticipo_bg"]),
        ("BACKGROUND",     (0,idx_tot), (-1,idx_tot), C["total_bg"]),
        ("LINEABOVE",      (0,idx_tot), (-1,idx_tot), 2.5, C["accent"]),
        ("TOPPADDING",     (0,0),(-1,-1), 6), ("BOTTOMPADDING",(0,0),(-1,-1),6),
        ("LEFTPADDING",    (0,0),(-1,-1), 10), ("RIGHTPADDING",(0,0),(-1,-1),10),
        ("LINEBELOW",      (0,0),(-1,-2), 0.3, C["border"]),
        ("BOX",            (0,0),(-1,-1), 0.5, C["border"]),
    ]))
    story.append(KeepTogether([tbl_val]))

    valor_letras = _numero_a_letras(int(round(valor_anticipo)))
    story.append(Table([[Paragraph(f"Son: {valor_letras}", E["letras"])]],
        colWidths=[_AU], style=TableStyle([
            ("BACKGROUND",   (0,0),(-1,-1), C["primary"]),
            ("TOPPADDING",   (0,0),(-1,-1), 3), ("BOTTOMPADDING",(0,0),(-1,-1),6),
            ("LEFTPADDING",  (0,0),(-1,-1), 10),
        ])))
    story.append(Spacer(1, 7))

    banco_filas = []
    if datos_prestador.get("banco"):        banco_filas.append(("Banco", datos_prestador["banco"]))
    if datos_prestador.get("cuenta_tipo"):  banco_filas.append(("Tipo de cuenta", datos_prestador["cuenta_tipo"]))
    if datos_prestador.get("cuenta_numero"):banco_filas.append(("N de cuenta", datos_prestador["cuenta_numero"]))
    if datos_prestador.get("nombre"):       banco_filas.append(("A nombre de", datos_prestador["nombre"]))
    if banco_filas:
        story += _seccion_header("Datos para Pago", E)
        story.append(_tabla_datos_cliente(E, C, banco_filas))
        story.append(Spacer(1, 7))

    # FIX-1: Nota tributaria obligatoria según régimen fiscal del emisor
    _nota_tributaria = (
        "Este documento es una Proforma. La Factura Electrónica legal será emitida "
        "y transmitida a la DIAN tras la recepción del anticipo."
        if (incluir_iva and not es_aiu) else
        "El prestador del servicio pertenece al Régimen Simplificado (No Responsable de IVA)."
    )
    story.append(Table(
        [[Paragraph(_nota_tributaria, E["nota_legal"])]],
        colWidths=[_AU],
        style=TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#FFF9EC")),
            ("LEFTPADDING",   (0,0),(-1,-1), 10), ("RIGHTPADDING",  (0,0),(-1,-1),10),
            ("TOPPADDING",    (0,0),(-1,-1), 6),  ("BOTTOMPADDING", (0,0),(-1,-1),6),
            ("LINEABOVE",     (0,0),(-1, 0), 1.0, colors.HexColor("#C9A84C")),
            ("BOX",           (0,0),(-1,-1), 0.4, colors.HexColor("#C8D8E8")),
        ])
    ))
    story.append(Spacer(1, 7))

    firma = Table([[
        Table([[Paragraph("_" * 40, E["cell"])],[Paragraph(datos_prestador.get("nombre",""), E["aviso"])],[Paragraph("Firma del Prestador", E["aviso"])]]),
        "",
        Table([[Paragraph("_" * 35, E["cell"])],[Paragraph("", E["aviso"])],[Paragraph("Sello / Firma del Pagador", E["aviso"])]]),
    ]], colWidths=[_AU * 0.482, _AU * 0.090, _AU * 0.428])
    firma.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),10),("VALIGN",(0,0),(-1,-1),"BOTTOM")]))
    story.append(firma)
    story.append(Spacer(1, 7))
    # FIX-3: Bloque contractual de aceptación con KeepTogether
    story += _bloque_firma_cliente(E, C)
    story.append(Spacer(1, 5))
    story += _footer_doc(E, C, datos_prestador.get("nombre",""), fecha_str, numero, ciudad=datos_prestador.get("ciudad","Barranquilla"))

    doc.build(story)
    return buf.getvalue()


# ── Conversion numero a letras (espanol colombiano) ───────────────────────────

def _numero_a_letras(n):
    """Convierte entero a letras en español colombiano.
    Devuelve string en MAYÚSCULAS con sufijo obligatorio ' PESOS M/CTE.'
    para ortografía contable estricta conforme a normas DIAN.
    """
    def _core(n):
        if n == 0: return "cero"
        # FIX-2: ortografía correcta — tildes en dieciséis, veintiuno, etc.
        unidades = ["","uno","dos","tres","cuatro","cinco","seis","siete","ocho","nueve",
                    "diez","once","doce","trece","catorce","quince","dieciséis","diecisiete",
                    "dieciocho","diecinueve"]
        # Compuestos del 20 con ortografía estricta
        veintes  = {20:"veinte",21:"veintiuno",22:"veintidós",23:"veintitrés",
                    24:"veinticuatro",25:"veinticinco",26:"veintiséis",
                    27:"veintisiete",28:"veintiocho",29:"veintinueve"}
        decenas  = ["","diez","veinte","treinta","cuarenta","cincuenta","sesenta","setenta",
                    "ochenta","noventa"]
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
    # FIX-2: Capitalizar primera letra y añadir sufijo contable obligatorio
    return raw.capitalize() + " PESOS M/CTE."
