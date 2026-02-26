# generador_pdf.py — CostoMármol v2
# Genera PDF de cotización y cuenta de cobro usando reportlab

import io
from datetime import date
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from calculos import cop


# ── Paleta de colores ─────────────────────────────────────────────────────────
NAVY    = colors.HexColor("#0d2744")
BLUE    = colors.HexColor("#1a6bb5")
BLUE_L  = colors.HexColor("#deeefa")
BLUE_UL = colors.HexColor("#f0f7ff")
WHITE   = colors.white
GRAY    = colors.HexColor("#5a7a9a")
GRAY_L  = colors.HexColor("#e8f0f8")
GREEN   = colors.HexColor("#0f7a4a")
BLACK   = colors.HexColor("#0d2744")


def _estilos():
    s = getSampleStyleSheet()
    base = dict(fontName="Helvetica", leading=14)
    return {
        "titulo":    ParagraphStyle("titulo",    **base, fontSize=22, fontName="Helvetica-Bold", textColor=WHITE,    alignment=TA_LEFT),
        "subtitulo": ParagraphStyle("subtitulo", **base, fontSize=10, textColor=colors.HexColor("#93c5fd"), alignment=TA_LEFT),
        "empresa":   ParagraphStyle("empresa",   **base, fontSize=9,  textColor=WHITE, alignment=TA_RIGHT),
        "seccion":   ParagraphStyle("seccion",   **base, fontSize=8,  fontName="Helvetica-Bold", textColor=GRAY, letterSpacing=1),
        "normal":    ParagraphStyle("normal",    **base, fontSize=9,  textColor=BLACK),
        "bold":      ParagraphStyle("bold",      **base, fontSize=9,  fontName="Helvetica-Bold", textColor=BLACK),
        "precio":    ParagraphStyle("precio",    **base, fontSize=20, fontName="Helvetica-Bold", textColor=NAVY, alignment=TA_RIGHT),
        "label":     ParagraphStyle("label",     **base, fontSize=7,  textColor=GRAY, alignment=TA_RIGHT),
        "footer":    ParagraphStyle("footer",    **base, fontSize=7,  textColor=GRAY, alignment=TA_CENTER),
        "aviso":     ParagraphStyle("aviso",     **base, fontSize=8,  textColor=GRAY),
    }


def _header_cotizacion(E, numero, fecha_str):
    """Bloque de encabezado azul marino para cotización."""
    col1 = [
        Paragraph("COTIZACIÓN DE PROYECTO", E["subtitulo"]),
        Spacer(1, 4),
        Paragraph("CostoMármol Pro", E["titulo"]),
        Spacer(1, 2),
        Paragraph("Sistema de Cotización Profesional · Colombia", E["subtitulo"]),
    ]
    col2 = [
        Paragraph(f"N° <b>{numero}</b>", E["empresa"]),
        Paragraph(fecha_str, E["empresa"]),
        Spacer(1, 6),
        Paragraph("costomarmpol.streamlit.app", E["empresa"]),
    ]
    tbl = Table([[col1, col2]], colWidths=[11*cm, 7*cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",  (0,0), (-1,-1), NAVY),
        ("VALIGN",      (0,0), (-1,-1), "TOP"),
        ("TOPPADDING",  (0,0), (-1,-1), 18),
        ("BOTTOMPADDING",(0,0),(-1,-1), 18),
        ("LEFTPADDING", (0,0), (0,-1),  20),
        ("RIGHTPADDING",(-1,0),(-1,-1), 20),
    ]))
    return tbl


def _fila_dato(E, label, valor):
    return [Paragraph(label, E["normal"]), Paragraph(f"<b>{valor}</b>", E["bold"])]


def _tabla_datos_proyecto(E, r):
    """Tabla de datos del proyecto (2 columnas)."""
    filas = [
        [Paragraph("DATOS DEL PROYECTO", E["seccion"]), ""],
        _fila_dato(E, "Tipo de proyecto",   r.get("tipo_proyecto",  "—")),
        _fila_dato(E, "Material",            f"{r.get('categoria','—')} — {r.get('referencia','—')}"),
        _fila_dato(E, "m² del proyecto",     f"{r.get('m2_real', 0):.2f} m²"),
        _fila_dato(E, "Área material comprado", f"{r.get('area_placa', 0):.2f} m²"),
        _fila_dato(E, "m² usados",           f"{r.get('m2_usados', 0):.2f} m²"),
        _fila_dato(E, "Retal estimado",      f"{r.get('retal', 0):.2f} m²"),
        _fila_dato(E, "Aprovechamiento",     f"{r.get('aprovechamiento', 0):.0f}%"),
        _fila_dato(E, "Días en obra",        str(r.get("dias", "—"))),
        _fila_dato(E, "Personas",            str(r.get("personas", "—"))),
    ]
    if r.get("nombre_cliente"):
        filas.insert(2, _fila_dato(E, "Cliente", r["nombre_cliente"]))
    tbl = Table(filas, colWidths=[7*cm, 11*cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,0), BLUE_L),
        ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE, BLUE_UL]),
        ("TOPPADDING",   (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0), (-1,-1), 6),
        ("LEFTPADDING",  (0,0), (-1,-1), 10),
        ("LINEBELOW",    (0,0), (-1,-1), 0.3, BLUE_L),
        ("ROUNDEDCORNERS", [4]),
    ]))
    return tbl


def _tabla_desglose(E, r):
    """Tabla de desglose de costos con totales."""
    items = [
        ("① Material (área comprada × precio/m²)", r.get("c1_material", 0)),
        ("② Mano de obra (corte + elaboración)",    r.get("c2_mano_obra", 0)),
        ("③ Zócalos",                               r.get("c3_zocalos", 0)),
        ("④ Insumos (disco + desgaste maquinaria)", r.get("c4_insumos", 0)),
        ("⑤ Transporte proveedor → taller",         r.get("c5_taller", 0)),
        ("⑥ Transporte taller → cliente",           r.get("c5_entrega", 0)),
        ("⑦ Viáticos foráneos",                     r.get("c6_viaticos", 0)),
        ("⑧ Costos adicionales en obra",            r.get("c7_adicionales", 0)),
    ]
    # Encabezado
    filas = [[
        Paragraph("CONCEPTO", E["seccion"]),
        Paragraph("VALOR (COP)", ParagraphStyle("sh", fontName="Helvetica-Bold", fontSize=8, textColor=GRAY, alignment=TA_RIGHT, leading=14)),
    ]]
    for concepto, valor in items:
        c = GRAY if valor == 0 else BLACK
        filas.append([
            Paragraph(concepto, ParagraphStyle("c", fontName="Helvetica", fontSize=9, textColor=c, leading=13)),
            Paragraph(cop(valor), ParagraphStyle("v", fontName="Helvetica", fontSize=9, textColor=c, alignment=TA_RIGHT, leading=13)),
        ])
    # Subtotal costos
    filas.append([
        Paragraph("COSTO VARIABLE TOTAL", ParagraphStyle("ct", fontName="Helvetica-Bold", fontSize=9, textColor=NAVY, leading=14)),
        Paragraph(cop(r.get("costo_total", 0)), ParagraphStyle("cv", fontName="Helvetica-Bold", fontSize=9, textColor=NAVY, alignment=TA_RIGHT, leading=14)),
    ])
    tbl = Table(filas, colWidths=[13*cm, 5*cm])
    style = TableStyle([
        ("BACKGROUND",    (0,0),  (-1,0),  BLUE_L),
        ("ROWBACKGROUNDS",(0,1),  (-1,-2), [WHITE, BLUE_UL]),
        ("BACKGROUND",    (0,-1), (-1,-1), BLUE_L),
        ("FONTNAME",      (0,-1), (-1,-1), "Helvetica-Bold"),
        ("TOPPADDING",    (0,0),  (-1,-1), 7),
        ("BOTTOMPADDING", (0,0),  (-1,-1), 7),
        ("LEFTPADDING",   (0,0),  (-1,-1), 10),
        ("RIGHTPADDING",  (0,0),  (-1,-1), 10),
        ("LINEBELOW",     (0,0),  (-1,-1), 0.3, BLUE_L),
        ("LINEABOVE",     (0,-1), (-1,-1), 1.5, NAVY),
    ])
    tbl.setStyle(style)
    return tbl


def _bloque_precio_final(E, r):
    """Bloque visual con precio sugerido y margen."""
    precio = cop(r.get("precio_sugerido", 0))
    margen = r.get("margen_pct", 40)
    utilidad = cop(r.get("utilidad", 0))

    datos = Table(
        [[
            Paragraph("PRECIO DE VENTA SUGERIDO", ParagraphStyle("pl", fontName="Helvetica-Bold", fontSize=8, textColor=colors.HexColor("#93c5fd"), leading=12)),
            "",
        ],[
            Paragraph(precio, ParagraphStyle("pv", fontName="Helvetica-Bold", fontSize=22, textColor=WHITE, leading=26)),
            "",
        ],[
            Paragraph(f"Margen: {margen:.0f}%  ·  Utilidad proyectada: {utilidad}", ParagraphStyle("ps", fontName="Helvetica", fontSize=8, textColor=colors.HexColor("93c5fd"), leading=12, textColor=colors.HexColor("#93c5fd"))),
            "",
        ]],
        colWidths=[14*cm, 4*cm],
    )
    datos.setStyle(TableStyle([
        ("BACKGROUND",  (0,0), (-1,-1), NAVY),
        ("TOPPADDING",  (0,0), (-1,-1), 12),
        ("BOTTOMPADDING",(0,0),(-1,-1), 12),
        ("LEFTPADDING", (0,0), (-1,-1), 20),
        ("SPAN",        (0,0), (-1,0)),
        ("SPAN",        (0,1), (-1,1)),
        ("SPAN",        (0,2), (-1,2)),
    ]))
    return datos


def _nota_validez(E):
    return Paragraph(
        "Esta cotización tiene una validez de 15 días calendario. Los precios pueden variar "
        "según disponibilidad de material y condiciones del mercado. "
        "No incluye IVA a menos que se especifique.",
        E["aviso"],
    )


def generar_pdf_cotizacion(resultado: dict, numero: str = None, empresa_info: dict = None) -> bytes:
    """
    Genera el PDF de cotización profesional.
    Retorna bytes del PDF para descarga directa en Streamlit.
    """
    if numero is None:
        numero = f"COT-{date.today().strftime('%Y%m%d')}-001"
    fecha_str = date.today().strftime("%d de %B de %Y").replace(
        "January","enero").replace("February","febrero").replace("March","marzo").replace(
        "April","abril").replace("May","mayo").replace("June","junio").replace(
        "July","julio").replace("August","agosto").replace("September","septiembre").replace(
        "October","octubre").replace("November","noviembre").replace("December","diciembre")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=1.8*cm, rightMargin=1.8*cm,
        topMargin=1.5*cm, bottomMargin=2*cm,
        title=f"Cotización {numero}",
    )
    E = _estilos()
    story = []

    # Encabezado
    story.append(_header_cotizacion(E, numero, fecha_str))
    story.append(Spacer(1, 16))

    # Datos del proyecto
    story.append(_tabla_datos_proyecto(E, resultado))
    story.append(Spacer(1, 14))

    # Desglose
    story.append(Paragraph("DESGLOSE DE COSTOS", E["seccion"]))
    story.append(Spacer(1, 6))
    story.append(_tabla_desglose(E, resultado))
    story.append(Spacer(1, 14))

    # Precio final
    story.append(_bloque_precio_final(E, resultado))
    story.append(Spacer(1, 12))

    # Nota de validez
    story.append(_nota_validez(E))
    story.append(Spacer(1, 20))

    # Footer
    story.append(HRFlowable(width="100%", thickness=0.5, color=BLUE_L))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"Generado con CostoMármol Pro · {fecha_str} · Barranquilla, Colombia",
        E["footer"],
    ))

    doc.build(story)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# CUENTA DE COBRO
# ─────────────────────────────────────────────────────────────────────────────

def generar_cuenta_cobro(
    resultado: dict,
    datos_prestador: dict,    # quien cobra
    datos_pagador: dict,      # quien paga
    numero: str = None,
    descripcion_servicio: str = None,
) -> bytes:
    """
    Genera PDF de cuenta de cobro.
    datos_prestador: {nombre, nit_cc, direccion, telefono, banco, cuenta_tipo, cuenta_numero}
    datos_pagador:   {nombre, nit, direccion}
    """
    if numero is None:
        numero = f"CC-{date.today().strftime('%Y%m%d')}-001"
    fecha_str = date.today().strftime("%d/%m/%Y")
    valor_total = resultado.get("precio_sugerido", resultado.get("precio_total", 0))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=1.5*cm, bottomMargin=2*cm,
        title=f"Cuenta de Cobro {numero}",
    )
    E = _estilos()
    story = []

    # ── ENCABEZADO ──
    header = Table(
        [[
            Paragraph("CUENTA DE COBRO", ParagraphStyle("cct", fontName="Helvetica-Bold", fontSize=18, textColor=WHITE, leading=22)),
            Paragraph(f"N° <b>{numero}</b><br/>Fecha: {fecha_str}", E["empresa"]),
        ]],
        colWidths=[10*cm, 8*cm],
    )
    header.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,-1), NAVY),
        ("TOPPADDING",   (0,0), (-1,-1), 20),
        ("BOTTOMPADDING",(0,0), (-1,-1), 20),
        ("LEFTPADDING",  (0,0), (0,-1),  20),
        ("RIGHTPADDING", (-1,0),(-1,-1), 20),
        ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(header)
    story.append(Spacer(1, 16))

    # ── DATOS PRESTADOR ──
    story.append(Paragraph("DATOS DE QUIEN COBRA", E["seccion"]))
    story.append(Spacer(1, 5))
    prestador_filas = [
        [Paragraph("Nombre / Razón Social:", E["normal"]),
         Paragraph(f"<b>{datos_prestador.get('nombre','—')}</b>", E["bold"])],
        [Paragraph("NIT / CC:",              E["normal"]),
         Paragraph(datos_prestador.get('nit_cc','—'),              E["normal"])],
        [Paragraph("Dirección:",             E["normal"]),
         Paragraph(datos_prestador.get('direccion','—'),           E["normal"])],
        [Paragraph("Teléfono:",              E["normal"]),
         Paragraph(datos_prestador.get('telefono','—'),            E["normal"])],
    ]
    t_prestador = Table(prestador_filas, colWidths=[5*cm, 13*cm])
    t_prestador.setStyle(TableStyle([
        ("ROWBACKGROUNDS",(0,0),(-1,-1),[BLUE_UL, WHITE]),
        ("TOPPADDING",   (0,0),(-1,-1),6), ("BOTTOMPADDING",(0,0),(-1,-1),6),
        ("LEFTPADDING",  (0,0),(-1,-1),10), ("LINEBELOW",(0,0),(-1,-1),0.3,BLUE_L),
    ]))
    story.append(t_prestador)
    story.append(Spacer(1, 12))

    # ── DATOS PAGADOR ──
    story.append(Paragraph("DATOS DE QUIEN PAGA", E["seccion"]))
    story.append(Spacer(1, 5))
    pagador_filas = [
        [Paragraph("Nombre / Razón Social:", E["normal"]),
         Paragraph(f"<b>{datos_pagador.get('nombre','—')}</b>", E["bold"])],
        [Paragraph("NIT / CC:",              E["normal"]),
         Paragraph(datos_pagador.get('nit','—'),  E["normal"])],
        [Paragraph("Dirección:",             E["normal"]),
         Paragraph(datos_pagador.get('direccion','—'), E["normal"])],
    ]
    t_pagador = Table(pagador_filas, colWidths=[5*cm, 13*cm])
    t_pagador.setStyle(TableStyle([
        ("ROWBACKGROUNDS",(0,0),(-1,-1),[BLUE_UL, WHITE]),
        ("TOPPADDING",   (0,0),(-1,-1),6), ("BOTTOMPADDING",(0,0),(-1,-1),6),
        ("LEFTPADDING",  (0,0),(-1,-1),10), ("LINEBELOW",(0,0),(-1,-1),0.3,BLUE_L),
    ]))
    story.append(t_pagador)
    story.append(Spacer(1, 14))

    # ── DESCRIPCIÓN DEL SERVICIO ──
    story.append(Paragraph("DESCRIPCIÓN DEL SERVICIO", E["seccion"]))
    story.append(Spacer(1, 5))
    if descripcion_servicio is None:
        descripcion_servicio = (
            f"Fabricación e instalación de {resultado.get('tipo_proyecto','proyecto')} "
            f"en {resultado.get('categoria','material')} — {resultado.get('referencia','')}, "
            f"{resultado.get('m2_real',0):.2f} m²."
        )
    t_servicio = Table(
        [[Paragraph(descripcion_servicio, E["normal"])]],
        colWidths=[18*cm],
    )
    t_servicio.setStyle(TableStyle([
        ("BACKGROUND",   (0,0),(-1,-1), BLUE_UL),
        ("TOPPADDING",   (0,0),(-1,-1), 10), ("BOTTOMPADDING",(0,0),(-1,-1),10),
        ("LEFTPADDING",  (0,0),(-1,-1), 12), ("RIGHTPADDING", (0,0),(-1,-1),12),
        ("LINEBELOW",    (0,0),(-1,-1), 0.5, BLUE),
    ]))
    story.append(t_servicio)
    story.append(Spacer(1, 14))

    # ── VALOR TOTAL ──
    valor_letras = _numero_a_letras(int(round(valor_total)))
    t_valor = Table(
        [[
            Paragraph("VALOR TOTAL A COBRAR", ParagraphStyle("vl", fontName="Helvetica-Bold", fontSize=10, textColor=WHITE, leading=14)),
            Paragraph(cop(valor_total), ParagraphStyle("vv", fontName="Helvetica-Bold", fontSize=18, textColor=WHITE, alignment=TA_RIGHT, leading=22)),
        ],[
            Paragraph(f"Son: {valor_letras} pesos M/CTE", ParagraphStyle("vlt", fontName="Helvetica", fontSize=8, textColor=colors.HexColor("#93c5fd"), leading=12)),
            "",
        ]],
        colWidths=[10*cm, 8*cm],
    )
    t_valor.setStyle(TableStyle([
        ("BACKGROUND",   (0,0),(-1,-1), NAVY),
        ("TOPPADDING",   (0,0),(-1,-1),14), ("BOTTOMPADDING",(0,0),(-1,-1),14),
        ("LEFTPADDING",  (0,0),(-1,-1),16), ("RIGHTPADDING", (0,0),(-1,-1),16),
        ("VALIGN",       (0,0),(-1,-1),"MIDDLE"),
        ("SPAN",         (0,1),(-1,1)),
    ]))
    story.append(t_valor)
    story.append(Spacer(1, 14))

    # ── DATOS BANCARIOS ──
    if any([datos_prestador.get("banco"), datos_prestador.get("cuenta_numero")]):
        story.append(Paragraph("DATOS PARA PAGO", E["seccion"]))
        story.append(Spacer(1, 5))
        banco_filas = []
        if datos_prestador.get("banco"):
            banco_filas.append([Paragraph("Banco:", E["normal"]), Paragraph(f"<b>{datos_prestador['banco']}</b>", E["bold"])])
        if datos_prestador.get("cuenta_tipo") and datos_prestador.get("cuenta_numero"):
            banco_filas.append([Paragraph("Tipo de cuenta:", E["normal"]), Paragraph(datos_prestador["cuenta_tipo"], E["normal"])])
            banco_filas.append([Paragraph("N° de cuenta:", E["normal"]), Paragraph(f"<b>{datos_prestador['cuenta_numero']}</b>", E["bold"])])
        if datos_prestador.get("nombre"):
            banco_filas.append([Paragraph("A nombre de:", E["normal"]), Paragraph(datos_prestador["nombre"], E["normal"])])
        if banco_filas:
            t_banco = Table(banco_filas, colWidths=[5*cm, 13*cm])
            t_banco.setStyle(TableStyle([
                ("ROWBACKGROUNDS",(0,0),(-1,-1),[BLUE_UL, WHITE]),
                ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
                ("LEFTPADDING",(0,0),(-1,-1),10),("LINEBELOW",(0,0),(-1,-1),0.3,BLUE_L),
            ]))
            story.append(t_banco)
        story.append(Spacer(1, 14))

    # ── FIRMA ──
    firma = Table(
        [[
            Table([[Paragraph("_" * 45, E["normal"])],[Paragraph(datos_prestador.get("nombre",""), E["normal"])],[Paragraph("Firma del Prestador del Servicio", E["aviso"])]]),
            "",
            Table([[Paragraph("_" * 40, E["normal"])],[Paragraph("Sello / Firma del Pagador", E["aviso"])]])
        ]],
        colWidths=[8*cm, 2*cm, 8*cm],
    )
    firma.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),20),("VALIGN",(0,0),(-1,-1),"BOTTOM")]))
    story.append(firma)
    story.append(Spacer(1, 20))

    # Footer
    story.append(HRFlowable(width="100%", thickness=0.5, color=BLUE_L))
    story.append(Spacer(1, 5))
    story.append(Paragraph(
        f"Documento generado con CostoMármol Pro · {fecha_str} · Barranquilla, Colombia",
        E["footer"],
    ))

    doc.build(story)
    return buf.getvalue()


# ── Conversión básica de número a letras (para la cuenta de cobro) ────────────
def _numero_a_letras(n: int) -> str:
    if n == 0:
        return "cero"
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
