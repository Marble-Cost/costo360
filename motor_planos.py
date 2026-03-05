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
    """
    Genera el SVG de Nesting 2D con estándar industrial B2B:
      1. Etiquetas numéricas grandes dentro de cada pieza (sin texto de nombre)
      2. Margen de corte (kerf) de 2 px visual entre piezas
      3. Leyenda de despiece detallada debajo del dibujo
      4. Cotas de la placa virgen (ancho y alto totales)
    """

    # ── Constantes de layout ─────────────────────────────────────────────────
    PX_M         = 160     # píxeles por metro
    MARG         = 80      # margen lateral del canvas
    TITL_H       = 44      # altura barra título
    KERF         = 2.0     # reducción visual kerf (px) por lado
    # Espacio para cotas de la placa (izq y arriba)
    COTA_PLACA   = _COTA_GAP + _COTA_TICK + 18
    # Espacio para el panel de aviso de piezas que no caben
    PANEL_H      = 52 if unplaced else 0
    # Escala gráfica
    ESCALA_H     = 40
    # Leyenda de despiece: 26 px por fila + cabecera
    LEY_ROW_H    = 24
    LEY_HEADER_H = 32
    LEY_PAD      = 14
    LEY_H        = LEY_PAD + LEY_HEADER_H + len(placed) * LEY_ROW_H + LEY_PAD + 10

    placa_w_px = placa_ancho * PX_M
    placa_h_px = placa_alto  * PX_M

    # Canvas: margen izq incluye espacio para cota vertical de la placa
    canvas_w = max(760, placa_w_px + 2 * MARG + COTA_PLACA)
    canvas_h = (TITL_H + MARG + COTA_PLACA
                + placa_h_px
                + COTA_PLACA + PANEL_H + ESCALA_H
                + LEY_H + MARG)

    # Origen de la placa dentro del canvas
    # Desplazada a la derecha para dejar espacio a la cota vertical izquierda
    ox = MARG + COTA_PLACA
    oy = TITL_H + MARG + COTA_PLACA   # desplazada abajo para cota horizontal superior

    parts = []

    # ── Definiciones: marcadores de flecha ───────────────────────────────────
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{canvas_w:.0f}" height="{canvas_h:.0f}" '
        f'viewBox="0 0 {canvas_w:.0f} {canvas_h:.0f}" '
        f'style="display:block;border-radius:8px;box-shadow:0 2px 16px rgba(13,33,55,0.14);">'
    )
    parts.append(
        '<defs>'
        f'<marker id="na" markerWidth="7" markerHeight="7" refX="3.5" refY="2" '
        f'orient="auto" markerUnits="strokeWidth">'
        f'<path d="M0,0 L0,4 L5.5,2 z" fill="{_DORADO}"/></marker>'
        f'<marker id="na_r" markerWidth="7" markerHeight="7" refX="2" refY="2" '
        f'orient="auto" markerUnits="strokeWidth">'
        f'<path d="M5.5,0 L5.5,4 L0,2 z" fill="{_DORADO}"/></marker>'
        '<pattern id="retal_hatch" width="12" height="12" '
        'patternTransform="rotate(45 0 0)" patternUnits="userSpaceOnUse">'
        '<line x1="0" y1="0" x2="0" y2="12" stroke="#9CA3AF" stroke-width="1" opacity="0.3"/>'
        '</pattern>'
        '</defs>'
    )

    # ── Fondo canvas ─────────────────────────────────────────────────────────
    parts.append(f'<rect width="{canvas_w:.0f}" height="{canvas_h:.0f}" fill="#F8FAFD" rx="6"/>')

    # ── Barra título ─────────────────────────────────────────────────────────
    pct_uso = 100 - metricas["porcentaje_desperdicio"]
    parts.append(
        f'<rect x="0" y="0" width="{canvas_w:.0f}" height="{TITL_H}" '
        f'fill="{_AZUL_OSCURO}" rx="6"/>'
        f'<rect x="0" y="{TITL_H//2}" width="{canvas_w:.0f}" height="{TITL_H//2}" '
        f'fill="{_AZUL_OSCURO}"/>'
        f'<text x="14" y="28" font-family="Helvetica,Arial,sans-serif" font-size="13" '
        f'font-weight="bold" fill="#FFFFFF">'
        f'NESTING 2D  ·  Placa {placa_ancho:.2f}×{placa_alto:.2f} m  '
        f'·  Uso: {pct_uso:.1f}%  ·  Retal: {metricas["porcentaje_desperdicio"]:.1f}%'
        f'</text>'
        f'<text x="{canvas_w - 12:.0f}" y="28" text-anchor="end" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="9" fill="{_DORADO}">'
        f'MÁRMOLES COLLANTE &amp; CASTRO · Optimización de Corte</text>'
    )

    # ════════════════════════════════════════════════════════════════════════
    # COTAS DE LA PLACA VIRGEN (ancho superior + alto izquierdo)
    # ════════════════════════════════════════════════════════════════════════

    # — Cota horizontal superior: ancho total de la placa ────────────────────
    _cx1     = ox
    _cx2     = ox + placa_w_px
    _cy_cota = oy - _COTA_GAP           # encima de la placa
    _cy_tick = oy - _COTA_TICK          # líneas testigo salen del borde superior
    _mid_cx  = (_cx1 + _cx2) / 2
    parts.append(
        # líneas testigo
        f'<line x1="{_cx1:.1f}" y1="{_cy_tick:.1f}" x2="{_cx1:.1f}" y2="{_cy_cota:.1f}" '
        f'stroke="{_DORADO}" stroke-width="1.0" opacity="0.80"/>'
        f'<line x1="{_cx2:.1f}" y1="{_cy_tick:.1f}" x2="{_cx2:.1f}" y2="{_cy_cota:.1f}" '
        f'stroke="{_DORADO}" stroke-width="1.0" opacity="0.80"/>'
        # línea de cota con flechas
        f'<line x1="{_cx1:.1f}" y1="{_cy_cota:.1f}" x2="{_cx2:.1f}" y2="{_cy_cota:.1f}" '
        f'stroke="{_DORADO}" stroke-width="1.5" '
        f'marker-start="url(#na_r)" marker-end="url(#na)"/>'
        # texto con fondo blanco
        f'<rect x="{_mid_cx - 36:.1f}" y="{_cy_cota - 8:.1f}" width="72" height="16" '
        f'rx="2" fill="#FFFFFF" opacity="0.93"/>'
        f'<text x="{_mid_cx:.1f}" y="{_cy_cota + 4:.1f}" text-anchor="middle" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="10" '
        f'font-weight="bold" fill="{_DORADO}">{_fmt_m(placa_ancho)}</text>'
    )

    # — Cota vertical izquierda: alto total de la placa ──────────────────────
    _cy1      = oy
    _cy2      = oy + placa_h_px
    _cx_cota  = ox - _COTA_GAP          # a la izquierda de la placa
    _cx_tick  = ox - _COTA_TICK
    _mid_cy   = (_cy1 + _cy2) / 2
    parts.append(
        # líneas testigo
        f'<line x1="{_cx_tick:.1f}" y1="{_cy1:.1f}" x2="{_cx_cota:.1f}" y2="{_cy1:.1f}" '
        f'stroke="{_DORADO}" stroke-width="1.0" opacity="0.80"/>'
        f'<line x1="{_cx_tick:.1f}" y1="{_cy2:.1f}" x2="{_cx_cota:.1f}" y2="{_cy2:.1f}" '
        f'stroke="{_DORADO}" stroke-width="1.0" opacity="0.80"/>'
        # línea de cota con flechas
        f'<line x1="{_cx_cota:.1f}" y1="{_cy1:.1f}" x2="{_cx_cota:.1f}" y2="{_cy2:.1f}" '
        f'stroke="{_DORADO}" stroke-width="1.5" '
        f'marker-start="url(#na_r)" marker-end="url(#na)"/>'
        # texto rotado con fondo blanco
        f'<rect x="{_cx_cota - 8:.1f}" y="{_mid_cy - 36:.1f}" width="16" height="72" '
        f'rx="2" fill="#FFFFFF" opacity="0.93" '
        f'transform="rotate(-90,{_cx_cota:.1f},{_mid_cy:.1f})"/>'
        f'<text x="{_cx_cota:.1f}" y="{_mid_cy:.1f}" text-anchor="middle" '
        f'dominant-baseline="middle" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="10" '
        f'font-weight="bold" fill="{_DORADO}" '
        f'transform="rotate(-90,{_cx_cota:.1f},{_mid_cy:.1f})">'
        f'{_fmt_m(placa_alto)}</text>'
    )

    # ════════════════════════════════════════════════════════════════════════
    # PLACA VIRGEN (fondo gris con cuadrícula)
    # ════════════════════════════════════════════════════════════════════════
    parts.append(
        f'<rect x="{ox:.1f}" y="{oy:.1f}" '
        f'width="{placa_w_px:.1f}" height="{placa_h_px:.1f}" '
        f'rx="3" fill="#CDD3DA" stroke="#6B7280" stroke-width="2"/>'
    )
    # Patrón de rayado diagonal sobre la placa virgen — indica zona de retal/sobrante
    parts.append(
        f'<rect x="{ox:.1f}" y="{oy:.1f}" '
        f'width="{placa_w_px:.1f}" height="{placa_h_px:.1f}" '
        f'rx="3" fill="url(#retal_hatch)" stroke="none"/>'
    )

    # Cuadrícula 0.25 m
    _paso_g = 0.25 * PX_M
    _gx = _paso_g
    while _gx < placa_w_px - 0.5:
        _es_m_g = abs(round(_gx / PX_M) * PX_M - _gx) < 0.5
        parts.append(
            f'<line x1="{ox+_gx:.1f}" y1="{oy:.1f}" '
            f'x2="{ox+_gx:.1f}" y2="{oy+placa_h_px:.1f}" '
            f'stroke="#9CA3AF" stroke-width="{"0.7" if _es_m_g else "0.35"}" '
            f'opacity="{"0.55" if _es_m_g else "0.30"}"/>'
        )
        _gx += _paso_g
    _gy = _paso_g
    while _gy < placa_h_px - 0.5:
        _es_m_g = abs(round(_gy / PX_M) * PX_M - _gy) < 0.5
        parts.append(
            f'<line x1="{ox:.1f}" y1="{oy+_gy:.1f}" '
            f'x2="{ox+placa_w_px:.1f}" y2="{oy+_gy:.1f}" '
            f'stroke="#9CA3AF" stroke-width="{"0.7" if _es_m_g else "0.35"}" '
            f'opacity="{"0.55" if _es_m_g else "0.30"}"/>'
        )
        _gy += _paso_g

    # Etiqueta discreta de dimensión en la esquina de la placa
    parts.append(
        f'<text x="{ox + 7:.1f}" y="{oy + 15:.1f}" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="10" '
        f'fill="#374151" opacity="0.55">'
        f'Placa {placa_ancho:.2f}×{placa_alto:.2f} m  ({metricas["area_placa"]:.2f} m²)'
        f'</text>'
    )

    # ════════════════════════════════════════════════════════════════════════
    # PIEZAS COLOCADAS — Número secuencial + kerf visual
    # ════════════════════════════════════════════════════════════════════════
    for idx, p in enumerate(placed):
        num    = idx + 1                          # número secuencial 1, 2, 3…
        fill   = _NEST_FILLS[idx % len(_NEST_FILLS)]
        stroke = _NEST_STROKES[idx % len(_NEST_STROKES)]

        # Coordenadas reales (sin kerf)
        px_real = ox + p["x"] * PX_M
        py_real = oy + p["y"] * PX_M
        pw_real = p["w"] * PX_M
        ph_real = p["h"] * PX_M

        # Coordenadas con kerf (reducción visual para simular canal de disco)
        px_ = px_real + KERF
        py_ = py_real + KERF
        pw_ = pw_real - 2 * KERF
        ph_ = ph_real - 2 * KERF

        cx_ = px_ + pw_ / 2
        cy_ = py_ + ph_ / 2

        # Tamaño de fuente del número: grande, adaptativo al espacio de la pieza
        fs_num = max(11, min(36, int(min(pw_, ph_) / 2.2)))

        # Rectángulo de pieza con kerf aplicado
        parts.append(
            f'<rect x="{px_:.1f}" y="{py_:.1f}" '
            f'width="{max(1, pw_):.1f}" height="{max(1, ph_):.1f}" '
            f'rx="2" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>'
        )

        # ── Alerta de Rotación Crítica (Control de Vetas) ────────────────────
        # Franja amarilla-naranja en la parte superior de la pieza con texto
        # de advertencia para prevenir errores de veta en el taller.
        if p.get("rotada"):
            _rot_banner_h = min(22, max(14, ph_ * 0.18))   # altura proporcional al rect
            _rot_banner_w = max(1, pw_)
            # Franja de fondo amarillo-naranja, clippeada al rectángulo de la pieza
            parts.append(
                f'<clipPath id="rot_clip_{idx}">'
                f'<rect x="{px_:.1f}" y="{py_:.1f}" '
                f'width="{_rot_banner_w:.1f}" height="{_rot_banner_h:.1f}" rx="2"/>'
                f'</clipPath>'
                f'<rect x="{px_:.1f}" y="{py_:.1f}" '
                f'width="{_rot_banner_w:.1f}" height="{_rot_banner_h:.1f}" '
                f'rx="2" fill="#FEF3C7" stroke="#F59E0B" stroke-width="1.2" '
                f'clip-path="url(#rot_clip_{idx})"/>'
            )
            # Texto de advertencia centrado en la franja, solo si hay espacio
            if pw_ > 60 and _rot_banner_h >= 14:
                _rot_fs   = max(6, min(10, int(_rot_banner_h * 0.62)))
                _rot_cx   = px_ + pw_ / 2
                _rot_cy   = py_ + _rot_banner_h / 2
                _rot_txt  = "⚠ ROTADA — Cuidado con Veta"
                parts.append(
                    f'<text x="{_rot_cx:.1f}" y="{_rot_cy + _rot_fs * 0.35:.1f}" '
                    f'text-anchor="middle" dominant-baseline="middle" '
                    f'font-family="Helvetica,Arial,sans-serif" '
                    f'font-size="{_rot_fs}" font-weight="700" fill="#B91C1C" '
                    f'clip-path="url(#rot_clip_{idx})">{_rot_txt}</text>'
                )

        # Número secuencial centrado, grande, con clipPath de seguridad
        parts.append(
            f'<clipPath id="nc_{idx}">'
            f'<rect x="{px_:.1f}" y="{py_:.1f}" '
            f'width="{max(1, pw_):.1f}" height="{max(1, ph_):.1f}"/>'
            f'</clipPath>'
            f'<text x="{cx_:.1f}" y="{cy_:.1f}" text-anchor="middle" '
            f'dominant-baseline="middle" font-family="Helvetica,Arial,sans-serif" '
            f'font-size="{fs_num}" font-weight="bold" fill="{_AZUL_OSCURO}" '
            f'opacity="0.75" clip-path="url(#nc_{idx})">{num}</text>'
        )

        # ── Dimensiones In-Situ ───────────────────────────────────────────────
        # Muestra: nombre real (si no es "Pieza"/vacío) + dimensiones exactas
        # en fuente legible directamente sobre la pieza, para evitar que el
        # operario tenga que consultar la tabla inferior.
        if ph_ > 45 and pw_ > 70:
            _nombre_raw = str(p.get("nombre", "")).strip()
            _mostrar_nombre = _nombre_raw and _nombre_raw.lower() != "pieza"
            _dims_is    = f'{p["w"]:.3f} \u00d7 {p["h"]:.3f} m'
            _fs_is_dim  = max(8, min(11, int(min(pw_, ph_) / 6.0)))
            _fs_is_nom  = max(7, min(10, _fs_is_dim - 1))

            # Posición Y base: justo debajo del número grande
            _cy_base = cy_ + fs_num * 0.55

            if _mostrar_nombre:
                _nombre_trunc = _nombre_raw[:14]
                _cy_nom = _cy_base + _fs_is_nom + 1
                _cy_dim = _cy_nom + _fs_is_dim + 2
                parts.append(
                    f'<text x="{cx_:.1f}" y="{_cy_nom:.1f}" text-anchor="middle" '
                    f'font-family="Helvetica,Arial,sans-serif" font-size="{_fs_is_nom}" '
                    f'font-weight="600" fill="{_AZUL_OSCURO}" opacity="0.72" '
                    f'clip-path="url(#nc_{idx})">{_esc(_nombre_trunc)}</text>'
                )
                parts.append(
                    f'<text x="{cx_:.1f}" y="{_cy_dim:.1f}" text-anchor="middle" '
                    f'font-family="Helvetica,Arial,sans-serif" font-size="{_fs_is_dim}" '
                    f'font-weight="700" fill="{_AZUL_OSCURO}" '
                    f'clip-path="url(#nc_{idx})">{_dims_is}</text>'
                )
            else:
                # Sin nombre significativo → dimensiones ocupan el lugar de honor
                _cy_dim = _cy_base + _fs_is_dim + 2
                parts.append(
                    f'<text x="{cx_:.1f}" y="{_cy_dim:.1f}" text-anchor="middle" '
                    f'font-family="Helvetica,Arial,sans-serif" font-size="{_fs_is_dim}" '
                    f'font-weight="700" fill="{_AZUL_OSCURO}" '
                    f'clip-path="url(#nc_{idx})">{_dims_is}</text>'
                )

    # ════════════════════════════════════════════════════════════════════════
    # PANEL "PIEZAS QUE NO CABEN"
    # ════════════════════════════════════════════════════════════════════════
    _y_after_placa = oy + placa_h_px
    if unplaced:
        _yp = _y_after_placa + 10
        _nombres_u = ", ".join(str(n) for n in unplaced[:6])
        if len(unplaced) > 6:
            _nombres_u += f" (+{len(unplaced)-6} más)"
        parts.append(
            f'<rect x="{ox:.1f}" y="{_yp:.1f}" '
            f'width="{placa_w_px:.1f}" height="40" '
            f'rx="4" fill="#FEF2F2" stroke="#FCA5A5" stroke-width="1.2"/>'
            f'<text x="{ox+10:.1f}" y="{_yp+14:.1f}" '
            f'font-family="Helvetica,Arial,sans-serif" font-size="10" '
            f'font-weight="bold" fill="#B91C1C">⚠ No caben en esta placa:</text>'
            f'<text x="{ox+10:.1f}" y="{_yp+30:.1f}" '
            f'font-family="Helvetica,Arial,sans-serif" font-size="9" '
            f'fill="#7F1D1D">{_esc(_nombres_u)}</text>'
        )

    # ════════════════════════════════════════════════════════════════════════
    # ESCALA GRÁFICA 1 m
    # ════════════════════════════════════════════════════════════════════════
    _ey = _y_after_placa + PANEL_H + 22
    parts.append(
        f'<line x1="{ox:.1f}" y1="{_ey:.1f}" x2="{ox+PX_M:.1f}" y2="{_ey:.1f}" '
        f'stroke="{_AZUL_CORP}" stroke-width="1.8"/>'
        f'<line x1="{ox:.1f}" y1="{_ey-6:.1f}" x2="{ox:.1f}" y2="{_ey+6:.1f}" '
        f'stroke="{_AZUL_CORP}" stroke-width="1.8"/>'
        f'<line x1="{ox+PX_M:.1f}" y1="{_ey-6:.1f}" x2="{ox+PX_M:.1f}" y2="{_ey+6:.1f}" '
        f'stroke="{_AZUL_CORP}" stroke-width="1.8"/>'
        f'<text x="{ox + PX_M/2:.1f}" y="{_ey - 10:.1f}" text-anchor="middle" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="10" '
        f'font-weight="bold" fill="{_AZUL_CORP}">↔ 1 m (escala real)</text>'
    )

    # ════════════════════════════════════════════════════════════════════════
    # LEYENDA DE DESPIECE — tabla detallada debajo de la escala
    # ════════════════════════════════════════════════════════════════════════
    _ly_top  = _ey + ESCALA_H - 14       # Y de inicio del panel de leyenda
    _ley_w   = max(520, placa_w_px)       # ancho de la tabla de leyenda
    _ley_col = [58, 200, 100, 100, 90]   # anchos de columnas: Check, Nombre, Largo, Ancho, Área

    # Fondo del panel de leyenda
    parts.append(
        f'<rect x="{ox:.1f}" y="{_ly_top:.1f}" '
        f'width="{_ley_w:.1f}" height="{LEY_H:.1f}" '
        f'rx="6" fill="{_WHITE}" stroke="{_AZUL_CORP}" stroke-width="1.0" opacity="0.96"/>'
    )

    # Cabecera de la tabla
    _hdr_y = _ly_top + LEY_PAD
    parts.append(
        f'<rect x="{ox:.1f}" y="{_hdr_y:.1f}" '
        f'width="{_ley_w:.1f}" height="{LEY_HEADER_H}" '
        f'rx="4" fill="{_AZUL_OSCURO}"/>'
        # radio inferior cuadrado para que se una con la tabla
        f'<rect x="{ox:.1f}" y="{_hdr_y + LEY_HEADER_H//2:.1f}" '
        f'width="{_ley_w:.1f}" height="{LEY_HEADER_H//2}" fill="{_AZUL_OSCURO}"/>'
    )
    _hdr_labels = ["Check", "Nombre de la Pieza", "Largo (m)", "Ancho (m)", "Área (m²)"]
    _hdr_anchors = ["middle", "start", "middle", "middle", "middle"]
    _col_x = ox
    for ci, (col_w, label, anchor) in enumerate(zip(_ley_col, _hdr_labels, _hdr_anchors)):
        _tx = _col_x + (col_w / 2 if anchor == "middle" else 8)
        parts.append(
            f'<text x="{_tx:.1f}" y="{_hdr_y + 21:.1f}" '
            f'font-family="Helvetica,Arial,sans-serif" font-size="11" '
            f'font-weight="bold" fill="#FFFFFF" text-anchor="{anchor}">'
            f'{label}</text>'
        )
        _col_x += col_w

    # Filas de piezas
    for idx, p in enumerate(placed):
        num    = idx + 1
        fill   = _NEST_FILLS[idx % len(_NEST_FILLS)]
        stroke = _NEST_STROKES[idx % len(_NEST_STROKES)]
        nombre = str(p.get("nombre", "Pieza"))
        if p.get("rotada"):
            nombre += " ↺"
        largo_m = p["w"]
        ancho_m = p["h"]
        area_m2 = largo_m * ancho_m

        _row_y    = _hdr_y + LEY_HEADER_H + idx * LEY_ROW_H
        _row_bg   = "#F0F5FB" if idx % 2 == 0 else "#FFFFFF"

        # fondo de fila alternado
        parts.append(
            f'<rect x="{ox:.1f}" y="{_row_y:.1f}" '
            f'width="{_ley_w:.1f}" height="{LEY_ROW_H}" '
            f'fill="{_row_bg}" opacity="0.95"/>'
        )

        # Separador horizontal entre filas
        parts.append(
            f'<line x1="{ox:.1f}" y1="{_row_y:.1f}" '
            f'x2="{ox + _ley_w:.1f}" y2="{_row_y:.1f}" '
            f'stroke="{_AZUL_CORP}" stroke-width="0.4" opacity="0.25"/>'
        )

        _ty = _row_y + LEY_ROW_H / 2
        _col_x = ox

        # Columna 1: casilla de verificación imprimible + pastilla de color + número
        # La casilla (□) es un rect blanco con borde gris oscuro para tachar con bolígrafo.
        _chk_size = 12          # tamaño del cuadrado de check
        _chk_x    = _col_x + 5                          # margen izq dentro de la celda
        _chk_y    = _ty - _chk_size / 2
        parts.append(
            # Casilla de verificación imprimible
            f'<rect x="{_chk_x:.1f}" y="{_chk_y:.1f}" '
            f'width="{_chk_size}" height="{_chk_size}" rx="1.5" '
            f'fill="#FFFFFF" stroke="#374151" stroke-width="1.4"/>'
        )
        # Pastilla de color corporativo con número, desplazada a la derecha de la casilla
        _nc_x = _chk_x + _chk_size + 14    # separación casilla → pastilla
        parts.append(
            f'<rect x="{_nc_x - 11:.1f}" y="{_ty - 9:.1f}" '
            f'width="22" height="18" rx="3" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>'
            f'<text x="{_nc_x:.1f}" y="{_ty + 4:.1f}" text-anchor="middle" '
            f'font-family="Helvetica,Arial,sans-serif" font-size="11" '
            f'font-weight="bold" fill="{_AZUL_OSCURO}">{num}</text>'
        )
        _col_x += _ley_col[0]

        # Columna 2: nombre de la pieza (alineado a la izquierda)
        parts.append(
            f'<text x="{_col_x + 8:.1f}" y="{_ty + 4:.1f}" '
            f'font-family="Helvetica,Arial,sans-serif" font-size="12" '
            f'fill="{_TEXT_DIM}">{_esc(nombre)}</text>'
        )
        _col_x += _ley_col[1]

        # Columnas 3, 4, 5: medidas y área (centradas)
        for val in [f"{largo_m:.3f}", f"{ancho_m:.3f}", f"{area_m2:.4f}"]:
            _mx = _col_x + _ley_col[2] / 2 if val == f"{largo_m:.3f}" else \
                  _col_x + _ley_col[3] / 2 if val == f"{ancho_m:.3f}" else \
                  _col_x + _ley_col[4] / 2
            parts.append(
                f'<text x="{_mx:.1f}" y="{_ty + 4:.1f}" text-anchor="middle" '
                f'font-family="Helvetica,Arial,sans-serif" font-size="12" '
                f'fill="{_TEXT_DIM}" font-variant-numeric="tabular-nums">{val}</text>'
            )
            _col_x += _ley_col[2 if val == f"{largo_m:.3f}" else
                                 3 if val == f"{ancho_m:.3f}" else 4]

    # Línea de cierre y total
    _total_y = _hdr_y + LEY_HEADER_H + len(placed) * LEY_ROW_H
    _total_area = sum(p["w"] * p["h"] for p in placed)
    parts.append(
        f'<rect x="{ox:.1f}" y="{_total_y:.1f}" '
        f'width="{_ley_w:.1f}" height="{LEY_ROW_H + 4}" '
        f'rx="0" fill="{_AZUL_CLARO}" opacity="0.60"/>'
        f'<text x="{ox + _ley_col[0] + 8:.1f}" y="{_total_y + LEY_ROW_H/2 + 4:.1f}" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="11" '
        f'font-weight="bold" fill="{_AZUL_OSCURO}">'
        f'TOTAL  ·  {len(placed)} piezas colocadas'
        f'</text>'
        f'<text x="{ox + sum(_ley_col[:4]) + _ley_col[4]/2:.1f}" '
        f'y="{_total_y + LEY_ROW_H/2 + 4:.1f}" text-anchor="middle" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="11" '
        f'font-weight="bold" fill="{_AZUL_OSCURO}">{_total_area:.4f} m²</text>'
    )

    parts.append("</svg>")
    return "\n".join(parts)
