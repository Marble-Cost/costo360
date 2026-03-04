# motor_planos.py — Motor de Despiece Paramétrico SVG
# CostoMármol — Mármoles Collante & Castro Ltda.
#
# Genera planos técnicos 2D en SVG puro (sin librerías externas de dibujo).
# Entrada : dict JSON con piezas y perforaciones
#           (producido por asistente_ia.extraer_coordenadas_plano)
# Salida  : string SVG completo, listo para st.markdown(..., unsafe_allow_html=True)
#           o para descargar como archivo .svg

import io
import tempfile
import os

# ── Paleta corporativa ────────────────────────────────────────────────────────
_AZUL_CORP   = "#1B5FA8"   # Borde y texto principal de piezas
_AZUL_OSCURO = "#0D2137"   # Fondo título, texto cotas
_AZUL_CLARO  = "#D6E8FA"   # Relleno de piezas
_AZUL_MED    = "#4A90C4"   # Etiqueta de dimensiones interna
_DORADO      = "#C9A84C"   # Cotas (flechas + valor)
_GRIS_PERF   = "#9CA3AF"   # Contorno perforaciones
_GRIS_FILL   = "#F1F3F5"   # Relleno perforaciones
_GRID_COLOR  = "#D6E8FA"   # Líneas de cuadrícula
_BG          = "#F8FAFD"   # Fondo canvas
_WHITE       = "#FFFFFF"
_TEXT_DIM    = "#374151"   # Texto dimensiones leyenda

# ── Constantes de layout ──────────────────────────────────────────────────────
_PX_M        = 140         # píxeles por metro
_MARGEN      = 90          # margen externo del canvas
_TITULO_H    = 40          # altura de la barra de título
_COTA_GAP    = 32          # distancia cota a borde pieza
_COTA_TICK   = 8           # longitud líneas testigo más allá de la cota
_MIN_W       = 600         # ancho mínimo del SVG (legibilidad)
_PASO_GRID_M = 0.25        # paso de cuadrícula en metros


# ══════════════════════════════════════════════════════════════════════════════
# Utilidades
# ══════════════════════════════════════════════════════════════════════════════

def _px(metros):
    return metros * _PX_M

def _fmt_m(v):
    return f"{v:.2f} m"

def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ══════════════════════════════════════════════════════════════════════════════
# Definiciones SVG (marcadores flecha, filtro sombra)
# ══════════════════════════════════════════════════════════════════════════════

def _defs_svg():
    arrow = (
        '<marker id="arr" markerWidth="7" markerHeight="7" '
        'refX="3.5" refY="2" orient="auto" markerUnits="strokeWidth">'
        '<path d="M0,0 L0,4 L5.5,2 z" fill="{c}"/></marker>'
        '<marker id="arr_rev" markerWidth="7" markerHeight="7" '
        'refX="2" refY="2" orient="auto" markerUnits="strokeWidth">'
        '<path d="M5.5,0 L5.5,4 L0,2 z" fill="{c}"/></marker>'
    ).format(c=_DORADO)
    shadow = (
        '<filter id="sombra" x="-2%" y="-2%" width="104%" height="104%">'
        '<feDropShadow dx="0" dy="2" stdDeviation="3" '
        'flood-color="#0D2137" flood-opacity="0.10"/></filter>'
    )
    return f"<defs>\n{arrow}\n{shadow}\n</defs>"


# ══════════════════════════════════════════════════════════════════════════════
# Cuadrícula de referencia
# ══════════════════════════════════════════════════════════════════════════════

def _cuadricula(ancho_px, alto_px):
    lines = []
    paso_px = _px(_PASO_GRID_M)
    x = 0.0
    while x <= ancho_px + 0.5:
        es_metro = abs(round(x / _PX_M) * _PX_M - x) < 0.5
        sw = "0.8" if es_metro else "0.4"
        op = "0.55" if es_metro else "0.28"
        lines.append(
            f'<line x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{alto_px:.1f}" '
            f'stroke="{_GRID_COLOR}" stroke-width="{sw}" opacity="{op}"/>'
        )
        x += paso_px
    y = 0.0
    while y <= alto_px + 0.5:
        es_metro = abs(round(y / _PX_M) * _PX_M - y) < 0.5
        sw = "0.8" if es_metro else "0.4"
        op = "0.55" if es_metro else "0.28"
        lines.append(
            f'<line x1="0" y1="{y:.1f}" x2="{ancho_px:.1f}" y2="{y:.1f}" '
            f'stroke="{_GRID_COLOR}" stroke-width="{sw}" opacity="{op}"/>'
        )
        y += paso_px
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# Barra de título
# ══════════════════════════════════════════════════════════════════════════════

def _titulo(ancho_px, n_piezas, area_total):
    return (
        f'<rect x="0" y="0" width="{ancho_px:.1f}" height="{_TITULO_H}" '
        f'fill="{_AZUL_OSCURO}" rx="5"/>'
        f'<rect x="0" y="{_TITULO_H // 2}" width="{ancho_px:.1f}" height="{_TITULO_H // 2}" '
        f'fill="{_AZUL_OSCURO}"/>'
        f'<text x="14" y="26" font-family="Helvetica,Arial,sans-serif" '
        f'font-size="13" font-weight="bold" fill="{_WHITE}">'
        f'PLANO DE PRODUCCIÓN  ·  {n_piezas} pieza(s)  ·  '
        f'Área total: {area_total:.2f} m\u00b2</text>'
        f'<text x="{ancho_px - 12:.1f}" y="26" text-anchor="end" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="9" fill="{_DORADO}">'
        f'MÁRMOLES COLLANTE &amp; CASTRO · Plano Paramétrico</text>'
    )


# ══════════════════════════════════════════════════════════════════════════════
# Pieza de mármol
# ══════════════════════════════════════════════════════════════════════════════

def _pieza(pid, x_m, y_m, ancho_m, alto_m, ox, oy):
    x  = ox + _px(x_m)
    y  = oy + _px(y_m)
    w  = _px(ancho_m)
    h  = _px(alto_m)
    cx = x + w / 2
    cy = y + h / 2

    shadow = (
        f'<rect x="{x + 4:.1f}" y="{y + 4:.1f}" '
        f'width="{w:.1f}" height="{h:.1f}" rx="3" '
        f'fill="{_AZUL_CORP}" opacity="0.10"/>'
    )
    rect = (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="3" '
        f'fill="{_AZUL_CLARO}" stroke="{_AZUL_CORP}" stroke-width="2"/>'
    )
    # línea central de textura sutil
    hatch = ""
    if w > 40 and h > 40:
        hatch = (
            f'<line x1="{x + 6:.1f}" y1="{cy:.1f}" '
            f'x2="{x + w - 6:.1f}" y2="{cy:.1f}" '
            f'stroke="{_AZUL_CORP}" stroke-width="0.5" opacity="0.20" stroke-dasharray="3,5"/>'
        )
    fs_id  = max(9, min(14, int(min(w, h) / 3.8)))
    fs_dim = max(7, min(11, fs_id - 2))
    offset_label = -(fs_dim + 4) if h > 30 else 0
    label = (
        f'<text x="{cx:.1f}" y="{cy + offset_label:.1f}" '
        f'text-anchor="middle" dominant-baseline="middle" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="{fs_id}" '
        f'font-weight="bold" fill="{_AZUL_OSCURO}">{_esc(pid)}</text>'
    )
    dim = ""
    if h > 28:
        dim = (
            f'<text x="{cx:.1f}" y="{cy + fs_id:.1f}" '
            f'text-anchor="middle" '
            f'font-family="Helvetica,Arial,sans-serif" font-size="{fs_dim}" '
            f'fill="{_AZUL_MED}" opacity="0.82">'
            f'{ancho_m:.2f} × {alto_m:.2f} m</text>'
        )
    return "\n".join(filter(None, [shadow, rect, hatch, label, dim]))


# ══════════════════════════════════════════════════════════════════════════════
# Perforación
# ══════════════════════════════════════════════════════════════════════════════

def _perforacion(x_m, y_m, ancho_m, alto_m, tipo, ox, oy):
    x  = ox + _px(x_m)
    y  = oy + _px(y_m)
    w  = _px(ancho_m)
    h  = _px(alto_m)
    cx = x + w / 2
    cy = y + h / 2
    fs = max(7, min(10, int(min(w, h) / 3.5)))
    rect = (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="4" '
        f'fill="{_GRIS_FILL}" stroke="{_GRIS_PERF}" stroke-width="1.4" '
        f'stroke-dasharray="5,3" opacity="0.92"/>'
    )
    cross = (
        f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x+w:.1f}" y2="{y+h:.1f}" '
        f'stroke="{_GRIS_PERF}" stroke-width="0.7" opacity="0.40"/>'
        f'<line x1="{x+w:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{y+h:.1f}" '
        f'stroke="{_GRIS_PERF}" stroke-width="0.7" opacity="0.40"/>'
    )
    label = (
        f'<text x="{cx:.1f}" y="{cy + 3:.1f}" text-anchor="middle" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="{fs}" '
        f'font-style="italic" fill="{_GRIS_PERF}">{_esc(tipo)}</text>'
    )
    return "\n".join([rect, cross, label])


# ══════════════════════════════════════════════════════════════════════════════
# Cotas dimensionales
# ══════════════════════════════════════════════════════════════════════════════

def _cota_h(x1, x2, y_pieza, valor_m, abajo=True):
    """Cota horizontal con flechas doradas y texto centrado."""
    sentido  = 1 if abajo else -1
    y_cota   = y_pieza + sentido * _COTA_GAP
    y_tick0  = y_pieza + sentido * _COTA_TICK
    mid_x    = (x1 + x2) / 2
    tl = (
        f'<line x1="{x1:.1f}" y1="{y_tick0:.1f}" x2="{x1:.1f}" y2="{y_cota:.1f}" '
        f'stroke="{_DORADO}" stroke-width="0.9" opacity="0.75"/>'
        f'<line x1="{x2:.1f}" y1="{y_tick0:.1f}" x2="{x2:.1f}" y2="{y_cota:.1f}" '
        f'stroke="{_DORADO}" stroke-width="0.9" opacity="0.75"/>'
    )
    cota = (
        f'<line x1="{x1:.1f}" y1="{y_cota:.1f}" x2="{x2:.1f}" y2="{y_cota:.1f}" '
        f'stroke="{_DORADO}" stroke-width="1.3" '
        f'marker-start="url(#arr_rev)" marker-end="url(#arr)"/>'
    )
    bw, bh = 58, 15
    bg = (
        f'<rect x="{mid_x - bw/2:.1f}" y="{y_cota - bh/2 - 1:.1f}" '
        f'width="{bw}" height="{bh}" rx="2" fill="{_WHITE}" opacity="0.93"/>'
    )
    txt = (
        f'<text x="{mid_x:.1f}" y="{y_cota + 4:.1f}" text-anchor="middle" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="9.5" '
        f'font-weight="bold" fill="{_DORADO}">{_fmt_m(valor_m)}</text>'
    )
    return "\n".join([tl, cota, bg, txt])


def _cota_v(y1, y2, x_pieza, valor_m, derecha=True):
    """Cota vertical con texto rotado 90°."""
    sentido  = 1 if derecha else -1
    x_cota   = x_pieza + sentido * _COTA_GAP
    x_tick0  = x_pieza + sentido * _COTA_TICK
    mid_y    = (y1 + y2) / 2
    tl = (
        f'<line x1="{x_tick0:.1f}" y1="{y1:.1f}" x2="{x_cota:.1f}" y2="{y1:.1f}" '
        f'stroke="{_DORADO}" stroke-width="0.9" opacity="0.75"/>'
        f'<line x1="{x_tick0:.1f}" y1="{y2:.1f}" x2="{x_cota:.1f}" y2="{y2:.1f}" '
        f'stroke="{_DORADO}" stroke-width="0.9" opacity="0.75"/>'
    )
    cota = (
        f'<line x1="{x_cota:.1f}" y1="{y1:.1f}" x2="{x_cota:.1f}" y2="{y2:.1f}" '
        f'stroke="{_DORADO}" stroke-width="1.3" '
        f'marker-start="url(#arr_rev)" marker-end="url(#arr)"/>'
    )
    txt = (
        f'<text x="{x_cota:.1f}" y="{mid_y:.1f}" text-anchor="middle" '
        f'dominant-baseline="middle" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="9.5" '
        f'font-weight="bold" fill="{_DORADO}" '
        f'transform="rotate(-90,{x_cota:.1f},{mid_y:.1f})">'
        f'{_fmt_m(valor_m)}</text>'
    )
    return "\n".join([tl, cota, txt])


# ══════════════════════════════════════════════════════════════════════════════
# Escala gráfica y leyenda
# ══════════════════════════════════════════════════════════════════════════════

def _escala_grafica(ox, oy_dibujo_bottom):
    """Barra de escala 1 m debajo del área de dibujo."""
    y   = oy_dibujo_bottom + _COTA_GAP + 18
    x0  = ox
    x1  = ox + _PX_M
    mid = (x0 + x1) / 2
    t   = 5
    return (
        f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x1:.1f}" y2="{y:.1f}" '
        f'stroke="{_AZUL_CORP}" stroke-width="1.5"/>'
        f'<line x1="{x0:.1f}" y1="{y-t:.1f}" x2="{x0:.1f}" y2="{y+t:.1f}" '
        f'stroke="{_AZUL_CORP}" stroke-width="1.5"/>'
        f'<line x1="{x1:.1f}" y1="{y-t:.1f}" x2="{x1:.1f}" y2="{y+t:.1f}" '
        f'stroke="{_AZUL_CORP}" stroke-width="1.5"/>'
        f'<text x="{mid:.1f}" y="{y - 7:.1f}" text-anchor="middle" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="9" fill="{_AZUL_CORP}">'
        f'↔ 1 m (escala)</text>'
    )


def _leyenda(piezas, canvas_w, canvas_h):
    """Panel compacto de leyenda en la esquina inferior derecha."""
    if not piezas:
        return ""
    n      = len(piezas)
    leg_w  = 190
    row_h  = 17
    pad    = 10
    leg_h  = pad * 2 + 16 + n * row_h
    lx     = canvas_w - leg_w - 10
    ly     = canvas_h - leg_h - 10
    parts  = [
        f'<rect x="{lx:.1f}" y="{ly:.1f}" width="{leg_w}" height="{leg_h:.1f}" '
        f'rx="5" fill="{_WHITE}" stroke="{_AZUL_CORP}" stroke-width="0.9" opacity="0.95"/>',
        f'<text x="{lx + pad:.1f}" y="{ly + pad + 10:.1f}" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="9" '
        f'font-weight="bold" fill="{_AZUL_OSCURO}">PIEZAS DEL PROYECTO</text>',
    ]
    for i, p in enumerate(piezas):
        ry    = ly + pad + 16 + i * row_h + row_h / 2
        ancho = p.get("ancho", 0)
        alto  = p.get("alto", 0)
        area  = ancho * alto
        pid   = p.get("id", "?")
        parts.append(
            f'<rect x="{lx + pad:.1f}" y="{ry - 5:.1f}" width="10" height="10" '
            f'rx="1" fill="{_AZUL_CLARO}" stroke="{_AZUL_CORP}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{lx + pad + 14:.1f}" y="{ry + 4:.1f}" '
            f'font-family="Helvetica,Arial,sans-serif" font-size="8.5" fill="{_TEXT_DIM}">'
            f'{_esc(pid)}  {ancho:.2f}×{alto:.2f} m  ({area:.2f} m\u00b2)</text>'
        )
    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PÚBLICA PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def generar_plano_svg(datos_json):
    """
    Genera un plano técnico 2D en SVG puro a partir del JSON de piezas/perforaciones.

    Estructura esperada del parámetro datos_json:
    {
        "piezas": [
            {"id": "Brazo Largo", "x": 0,    "y": 0,   "ancho": 2.50, "alto": 0.60},
            {"id": "Brazo Corto", "x": 2.50, "y": 0,   "ancho": 0.60, "alto": 1.20},
        ],
        "perforaciones": [
            {"pieza_id": "Brazo Largo", "x": 0.90, "y": 0.10,
             "ancho": 0.50, "alto": 0.40, "tipo": "Lavaplatos"}
        ]
    }

    Retorna:
        str — SVG embebible en HTML / Streamlit vía st.markdown(unsafe_allow_html=True).
    """
    piezas        = datos_json.get("piezas", [])
    perforaciones = datos_json.get("perforaciones", [])

    # Guard: sin piezas → SVG de error
    if not piezas:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="420" height="90">'
            f'<rect width="420" height="90" fill="#FEF2F2" rx="6"/>'
            f'<text x="210" y="48" text-anchor="middle" '
            f'font-family="Helvetica,Arial,sans-serif" font-size="13" fill="#B91C1C">'
            f'⚠ No se recibieron piezas para dibujar.</text>'
            '</svg>'
        )

    # Normalizar coordenadas al origen (0,0)
    min_x = min(p.get("x", 0) for p in piezas)
    min_y = min(p.get("y", 0) for p in piezas)
    for p in piezas:
        p["x"] = round(p.get("x", 0) - min_x, 6)
        p["y"] = round(p.get("y", 0) - min_y, 6)
    for pf in perforaciones:
        pf["x"] = round(pf.get("x", 0) - min_x, 6)
        pf["y"] = round(pf.get("y", 0) - min_y, 6)

    # Bounding box
    span_x_m = max(p.get("x", 0) + p.get("ancho", 0) for p in piezas)
    span_y_m = max(p.get("y", 0) + p.get("alto",  0) for p in piezas)
    dibujo_w = _px(span_x_m)
    dibujo_h = _px(span_y_m)

    # Dimensiones del canvas (incluye espacio para cotas y leyenda)
    extra_cota = _COTA_GAP + _COTA_TICK + 10
    canvas_w   = max(_MIN_W, dibujo_w + 2 * _MARGEN + 2 * extra_cota)
    canvas_h   = dibujo_h + 2 * _MARGEN + 2 * extra_cota + _TITULO_H + 8

    # Origen del área de dibujo dentro del canvas
    ox = _MARGEN + extra_cota
    oy = _TITULO_H + 8 + _MARGEN + extra_cota

    area_total = sum(p.get("ancho", 0) * p.get("alto", 0) for p in piezas)

    # ── Ensamblar SVG ─────────────────────────────────────────────────────────
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{canvas_w:.0f}" height="{canvas_h:.0f}" '
        f'viewBox="0 0 {canvas_w:.0f} {canvas_h:.0f}" '
        f'style="display:block;border-radius:8px;'
        f'box-shadow:0 2px 16px rgba(13,33,55,0.14);">',

        _defs_svg(),

        # fondo canvas
        f'<rect width="{canvas_w:.0f}" height="{canvas_h:.0f}" fill="{_BG}" rx="6"/>',

        # cuadrícula (solo dentro del área de dibujo)
        f'<g transform="translate({ox:.1f},{oy:.1f})">',
        _cuadricula(dibujo_w, dibujo_h),
        '</g>',

        # título
        _titulo(canvas_w, len(piezas), area_total),
    ]

    # Piezas
    for p in piezas:
        parts.append(
            _pieza(
                p.get("id", "—"),
                p.get("x", 0), p.get("y", 0),
                p.get("ancho", 1), p.get("alto", 0.6),
                ox, oy,
            )
        )

    # Perforaciones
    for pf in perforaciones:
        parts.append(
            _perforacion(
                pf.get("x", 0), pf.get("y", 0),
                pf.get("ancho", 0.5), pf.get("alto", 0.4),
                pf.get("tipo", "Perf."),
                ox, oy,
            )
        )

    # Cotas por pieza
    for p in piezas:
        px_ = ox + _px(p.get("x", 0))
        py_ = oy + _px(p.get("y", 0))
        pw_ = _px(p.get("ancho", 1))
        ph_ = _px(p.get("alto",  0.6))
        # cota ancho (horizontal) → debajo de la pieza
        parts.append(_cota_h(px_, px_ + pw_, py_ + ph_, p.get("ancho", 1), abajo=True))
        # cota alto (vertical) → a la derecha de la pieza
        parts.append(_cota_v(py_, py_ + ph_, px_ + pw_, p.get("alto", 0.6), derecha=True))

    # Escala gráfica
    parts.append(_escala_grafica(ox, oy + dibujo_h))

    # Leyenda
    parts.append(_leyenda(piezas, canvas_w, canvas_h))

    parts.append("</svg>")
    return "\n".join(parts)


def wrap_svg_streamlit(svg):
    """
    Envuelve el SVG en un div con scroll horizontal para evitar
    desbordamiento en el layout de Streamlit.
    """
    return (
        '<div style="overflow-x:auto;overflow-y:hidden;'
        'background:#F8FAFD;border-radius:8px;padding:6px 4px">'
        + svg +
        '</div>'
    )


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTACIÓN A PDF
# ══════════════════════════════════════════════════════════════════════════════

def exportar_svg_a_pdf(svg_string: str) -> bytes:
    """
    Convierte un string SVG en un PDF descargable usando svglib + ReportLab.

    Flujo:
      1. Escribe el SVG en un archivo temporal en disco (svglib requiere un
         path de archivo — no acepta StringIO directamente).
      2. svglib.svg2rlg() lee el archivo y devuelve un objeto ReportLab Drawing.
      3. reportlab.graphics.renderPDF.drawToString() renderiza el Drawing en
         bytes de PDF en memoria, sin tocar el disco.
      4. El archivo temporal se borra siempre (bloque finally).

    Retorna:
        bytes — contenido PDF listo para st.download_button(data=...).

    Lanza:
        RuntimeError si svglib o ReportLab no están instalados, o si el SVG
        no puede parsearse.
    """
    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPDF
    except ImportError as exc:
        raise RuntimeError(
            "svglib o reportlab no están instalados. "
            "Añade 'svglib>=1.5.1' a requirements.txt y reinstala."
        ) from exc

    # svglib.svg2rlg necesita un path real en disco
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".svg", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(svg_string)
            tmp_path = tmp.name

        drawing = svg2rlg(tmp_path)
        if drawing is None:
            raise RuntimeError(
                "svglib no pudo interpretar el SVG. "
                "Verifica que el plano se generó correctamente."
            )

        pdf_bytes = renderPDF.drawToString(drawing)
        return pdf_bytes

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


# ══════════════════════════════════════════════════════════════════════════════
# ALGORITMO NESTING 2D — Bin Packing con Guillotine Cut + rotación 90°
# ══════════════════════════════════════════════════════════════════════════════
# Implementa el algoritmo Guillotine 2D (variante Best Short Side Fit).
# Referencia clásica: Jukka Jylanki, "A Thousand Ways to Pack the Bin" (2010).
#
# Entrada:
#   placa_ancho  float  — ancho de la lámina en metros (eje X)
#   placa_alto   float  — alto  de la lámina en metros (eje Y)
#   lista_piezas list   — [{"nombre": str, "largo": float, "ancho": float}, ...]
#
# Salida:
#   (svg_string, metricas)
#   metricas = {
#       "area_placa":           float,
#       "area_utilizada":       float,
#       "porcentaje_desperdicio": float,   # retal %
#       "piezas_colocadas":     int,
#       "piezas_no_caben":      list[str], # nombres de piezas que no cupieron
#   }
# ══════════════════════════════════════════════════════════════════════════════

def _guillotine_pack(bin_w: float, bin_h: float, items: list[dict]):
    """
    Guillotine 2D bin packing con Best Short Side Fit y rotación libre.
    Devuelve (placed, unplaced).
      placed   = [{"nombre":str, "x":float, "y":float, "w":float, "h":float}, ...]
      unplaced = [nombre, ...]
    """
    # Espacios libres: lista de rectángulos disponibles
    free_rects = [{"x": 0.0, "y": 0.0, "w": bin_w, "h": bin_h}]
    placed  = []
    unplaced = []

    # Ordenar de mayor a menor área para mejor aprovechamiento
    sorted_items = sorted(
        items,
        key=lambda it: it.get("largo", 0) * it.get("ancho", 0),
        reverse=True,
    )

    for item in sorted_items:
        iw = float(item.get("largo", 0))
        ih = float(item.get("ancho", 0))
        if iw <= 0 or ih <= 0:
            unplaced.append(item.get("nombre", "?"))
            continue

        best_rect  = None
        best_score = float("inf")
        best_rotated = False

        for fr in free_rects:
            for rotado, (pw, ph) in enumerate([(iw, ih), (ih, iw)]):
                if pw <= fr["w"] + 1e-9 and ph <= fr["h"] + 1e-9:
                    # Short side fit score
                    score = min(fr["w"] - pw, fr["h"] - ph)
                    if score < best_score:
                        best_score = score
                        best_rect  = fr
                        best_rotated = bool(rotado)

        if best_rect is None:
            unplaced.append(item.get("nombre", "?"))
            continue

        # Colocar la pieza
        pw, ph = (ih, iw) if best_rotated else (iw, ih)
        placed.append({
            "nombre":   item.get("nombre", "Pieza"),
            "x":        best_rect["x"],
            "y":        best_rect["y"],
            "w":        pw,
            "h":        ph,
            "rotada":   best_rotated,
        })

        # Guillotine split: dividir el espacio libre en dos nuevos rectángulos
        bx, by, bw, bh = best_rect["x"], best_rect["y"], best_rect["w"], best_rect["h"]

        # Regla de corte: eje más corto primero (mejor para cuadrados)
        if bw - pw < bh - ph:
            # Corte horizontal (arriba de la pieza)
            r1 = {"x": bx,      "y": by + ph, "w": pw,      "h": bh - ph}
            r2 = {"x": bx + pw, "y": by,      "w": bw - pw, "h": bh}
        else:
            # Corte vertical (a la derecha de la pieza)
            r1 = {"x": bx + pw, "y": by, "w": bw - pw, "h": ph}
            r2 = {"x": bx,      "y": by + ph, "w": bw,  "h": bh - ph}

        free_rects.remove(best_rect)
        for nr in (r1, r2):
            if nr["w"] > 1e-4 and nr["h"] > 1e-4:
                free_rects.append(nr)

    return placed, unplaced


# ── Paleta nesting ────────────────────────────────────────────────────────────
_NEST_FILLS = [
    "#D6E8FA", "#D6F5E3", "#FFF3CD", "#F5D6FA",
    "#FAD6D6", "#D6F0FA", "#E8FAD6", "#FAF0D6",
    "#D6DAFA", "#FAD6F0",
]
_NEST_STROKES = [
    "#1B5FA8", "#1A7A3C", "#A07C00", "#7A1A8A",
    "#8A1A1A", "#1A7A8A", "#4A8A1A", "#8A6A1A",
    "#2A1A8A", "#8A1A5A",
]


def optimizar_corte_2d(placa_ancho: float, placa_alto: float, lista_piezas: list) -> tuple:
    """
    Ejecuta el algoritmo Guillotine 2D sobre la lámina indicada y genera el SVG.

    Parámetros:
        placa_ancho   float  — ancho de la placa (eje X), en metros
        placa_alto    float  — alto de la placa (eje Y), en metros
        lista_piezas  list   — [{"nombre": str, "largo": float, "ancho": float}, ...]
                               (puede incluir "cantidad": int, default 1)

    Retorna:
        (svg_string: str, metricas: dict)
        metricas = {
            "area_placa":             float,
            "area_utilizada":         float,
            "porcentaje_desperdicio": float,
            "piezas_colocadas":       int,
            "piezas_no_caben":        list[str],
        }
    """
    # Expandir por cantidad
    items_expandidos = []
    for p in lista_piezas:
        cant = int(p.get("cantidad", 1)) or 1
        for i in range(cant):
            sufijo = f" ({i+1})" if cant > 1 else ""
            items_expandidos.append({
                "nombre": str(p.get("nombre", "Pieza")) + sufijo,
                "largo":  float(p.get("largo", 0)),
                "ancho":  float(p.get("ancho", 0)),
            })

    placed, unplaced = _guillotine_pack(placa_ancho, placa_alto, items_expandidos)

    area_placa    = placa_ancho * placa_alto
    area_utilizada = sum(p["w"] * p["h"] for p in placed)
    pct_retal     = max(0.0, (1 - area_utilizada / area_placa) * 100) if area_placa > 0 else 0.0

    metricas = {
        "area_placa":             round(area_placa, 4),
        "area_utilizada":         round(area_utilizada, 4),
        "porcentaje_desperdicio": round(pct_retal, 1),
        "piezas_colocadas":       len(placed),
        "piezas_no_caben":        unplaced,
    }

    svg = _generar_svg_nesting(placa_ancho, placa_alto, placed, unplaced, metricas)
    return svg, metricas


def _generar_svg_nesting(
    placa_ancho: float,
    placa_alto: float,
    placed: list,
    unplaced: list,
    metricas: dict,
) -> str:
    """Genera el SVG de nesting: fondo gris (placa virgen) + piezas de colores."""

    PX_M   = 160          # píxeles por metro
    MARG   = 70           # margen canvas
    TITL_H = 44           # altura barra título
    PANEL_H = 52 if unplaced else 0  # panel aviso piezas que no caben

    placa_w_px = placa_ancho * PX_M
    placa_h_px = placa_alto  * PX_M

    canvas_w = max(640, placa_w_px + 2 * MARG)
    canvas_h = TITL_H + MARG + placa_h_px + MARG + PANEL_H + 10

    ox = (canvas_w - placa_w_px) / 2  # origen X de la placa
    oy = TITL_H + MARG                # origen Y de la placa

    parts = []

    # ── Cabecera SVG ─────────────────────────────────────────────────────────
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{canvas_w:.0f}" height="{canvas_h:.0f}" '
        f'viewBox="0 0 {canvas_w:.0f} {canvas_h:.0f}" '
        f'style="display:block;border-radius:8px;box-shadow:0 2px 16px rgba(13,33,55,0.14);">'
    )

    # ── Fondo canvas ─────────────────────────────────────────────────────────
    parts.append(f'<rect width="{canvas_w:.0f}" height="{canvas_h:.0f}" fill="#F8FAFD" rx="6"/>')

    # ── Barra título ─────────────────────────────────────────────────────────
    pct_uso = 100 - metricas["porcentaje_desperdicio"]
    parts.append(
        f'<rect x="0" y="0" width="{canvas_w:.0f}" height="{TITL_H}" fill="{_AZUL_OSCURO}" rx="6"/>'
        f'<rect x="0" y="{TITL_H//2}" width="{canvas_w:.0f}" height="{TITL_H//2}" fill="{_AZUL_OSCURO}"/>'
        f'<text x="14" y="28" font-family="Helvetica,Arial,sans-serif" font-size="13" '
        f'font-weight="bold" fill="#FFFFFF">NESTING 2D  ·  Placa {placa_ancho:.2f}×{placa_alto:.2f} m  '
        f'·  Uso: {pct_uso:.1f}%  ·  Retal: {metricas["porcentaje_desperdicio"]:.1f}%</text>'
        f'<text x="{canvas_w - 12:.0f}" y="28" text-anchor="end" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="9" fill="{_DORADO}">'
        f'MÁRMOLES COLLANTE &amp; CASTRO · Optimización de Corte</text>'
    )

    # ── Fondo placa (lámina virgen — gris) ───────────────────────────────────
    parts.append(
        f'<rect x="{ox:.1f}" y="{oy:.1f}" '
        f'width="{placa_w_px:.1f}" height="{placa_h_px:.1f}" '
        f'rx="4" fill="#D1D5DB" stroke="#6B7280" stroke-width="2"/>'
    )

    # ── Etiqueta placa ────────────────────────────────────────────────────────
    parts.append(
        f'<text x="{ox + 6:.1f}" y="{oy + 14:.1f}" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="10" '
        f'fill="#374151" opacity="0.70">Placa {placa_ancho:.2f}×{placa_alto:.2f} m  '
        f'({metricas["area_placa"]:.2f} m²)</text>'
    )

    # ── Cuadrícula 0.25 m sobre la placa ─────────────────────────────────────
    paso_px = 0.25 * PX_M
    x = paso_px
    while x < placa_w_px - 1:
        parts.append(
            f'<line x1="{ox+x:.1f}" y1="{oy:.1f}" x2="{ox+x:.1f}" y2="{oy+placa_h_px:.1f}" '
            f'stroke="#9CA3AF" stroke-width="0.5" opacity="0.40"/>'
        )
        x += paso_px
    y = paso_px
    while y < placa_h_px - 1:
        parts.append(
            f'<line x1="{ox:.1f}" y1="{oy+y:.1f}" x2="{ox+placa_w_px:.1f}" y2="{oy+y:.1f}" '
            f'stroke="#9CA3AF" stroke-width="0.5" opacity="0.40"/>'
        )
        y += paso_px

    # ── Piezas colocadas ──────────────────────────────────────────────────────
    for idx, p in enumerate(placed):
        fill   = _NEST_FILLS[idx % len(_NEST_FILLS)]
        stroke = _NEST_STROKES[idx % len(_NEST_STROKES)]
        px_ = ox + p["x"] * PX_M
        py_ = oy + p["y"] * PX_M
        pw_ = p["w"] * PX_M
        ph_ = p["h"] * PX_M
        cx_ = px_ + pw_ / 2
        cy_ = py_ + ph_ / 2

        rot_tag = " ↺" if p.get("rotada") else ""
        nombre  = str(p["nombre"]) + rot_tag
        fs_name = max(8, min(13, int(min(pw_, ph_) / 4.5)))
        fs_dim  = max(7, min(10, fs_name - 2))

        parts.append(
            # sombra
            f'<rect x="{px_+3:.1f}" y="{py_+3:.1f}" width="{pw_:.1f}" height="{ph_:.1f}" '
            f'rx="3" fill="{stroke}" opacity="0.10"/>'
            # rectángulo
            f'<rect x="{px_:.1f}" y="{py_:.1f}" width="{pw_:.1f}" height="{ph_:.1f}" '
            f'rx="3" fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>'
        )
        # Texto solo si la pieza es visible
        if pw_ > 28 and ph_ > 20:
            offset_y = -(fs_dim + 3) if ph_ > 32 else 0
            parts.append(
                f'<text x="{cx_:.1f}" y="{cy_ + offset_y:.1f}" text-anchor="middle" '
                f'dominant-baseline="middle" font-family="Helvetica,Arial,sans-serif" '
                f'font-size="{fs_name}" font-weight="bold" fill="{_AZUL_OSCURO}">'
                f'{_esc(nombre)}</text>'
            )
        if pw_ > 40 and ph_ > 32:
            parts.append(
                f'<text x="{cx_:.1f}" y="{cy_ + fs_name:.1f}" text-anchor="middle" '
                f'font-family="Helvetica,Arial,sans-serif" font-size="{fs_dim}" '
                f'fill="{stroke}" opacity="0.85">'
                f'{p["w"]:.2f}×{p["h"]:.2f} m</text>'
            )

    # ── Panel "piezas que no caben" ───────────────────────────────────────────
    if unplaced:
        py_panel = oy + placa_h_px + 10
        nombres_str = ", ".join(str(n) for n in unplaced[:6])
        if len(unplaced) > 6:
            nombres_str += f" (+{len(unplaced)-6} más)"
        parts.append(
            f'<rect x="{ox:.1f}" y="{py_panel:.1f}" '
            f'width="{placa_w_px:.1f}" height="38" '
            f'rx="4" fill="#FEF2F2" stroke="#FCA5A5" stroke-width="1.2"/>'
            f'<text x="{ox+10:.1f}" y="{py_panel+14:.1f}" '
            f'font-family="Helvetica,Arial,sans-serif" font-size="10" '
            f'font-weight="bold" fill="#B91C1C">⚠ No caben en esta placa:</text>'
            f'<text x="{ox+10:.1f}" y="{py_panel+30:.1f}" '
            f'font-family="Helvetica,Arial,sans-serif" font-size="9" '
            f'fill="#7F1D1D">{_esc(nombres_str)}</text>'
        )

    # ── Escala 1 m ────────────────────────────────────────────────────────────
    ey = oy + placa_h_px + (PANEL_H or 0) + 20
    parts.append(
        f'<line x1="{ox:.1f}" y1="{ey:.1f}" x2="{ox+PX_M:.1f}" y2="{ey:.1f}" '
        f'stroke="{_AZUL_CORP}" stroke-width="1.5"/>'
        f'<line x1="{ox:.1f}" y1="{ey-5:.1f}" x2="{ox:.1f}" y2="{ey+5:.1f}" '
        f'stroke="{_AZUL_CORP}" stroke-width="1.5"/>'
        f'<line x1="{ox+PX_M:.1f}" y1="{ey-5:.1f}" x2="{ox+PX_M:.1f}" y2="{ey+5:.1f}" '
        f'stroke="{_AZUL_CORP}" stroke-width="1.5"/>'
        f'<text x="{ox + PX_M/2:.1f}" y="{ey-8:.1f}" text-anchor="middle" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="9" fill="{_AZUL_CORP}">↔ 1 m</text>'
    )

    parts.append("</svg>")
    return "\n".join(parts)
