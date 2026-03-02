# calculos.py — Sistema de Cotización v4
# MARMOLES COLLANTE & CASTRO LTDA.
# Motor de cálculo con soporte dual ML/m²
#
# LÓGICA DE NEGOCIO:
#   La empresa vende en ML la mayoría de proyectos (mesones, encimeras, baños, escaleras).
#   Excepción: pisos, revestimientos y paneles grandes → se venden en m².
#
#   Cada pieza del proyecto tiene una "unidad_venta" ("ml" o "m2").
#   - ML: el cliente paga precio × ml. El m² se calcula internamente para el material.
#   - m²: el cliente paga precio × m². El ml es irrelevante para la venta.
#
#   Mano de obra siempre se paga en ML (operario cobra por ml cortado e instalado),
#   EXCEPTO pisos y revestimientos donde se paga por m² (menos cortes).

from parametros import LOGISTICA, VIATICOS, TARIFAS, VEHICULOS_CONFIG


# ── Conversor ML → m² ────────────────────────────────────────────────────────
def ml_a_m2(ml: float, ancho_m: float) -> float:
    """Convierte metros lineales × ancho a m² de material."""
    return round(ml * ancho_m, 4)


# ── Calcular totales de piezas ────────────────────────────────────────────────
def calcular_totales_piezas(piezas: list) -> dict:
    """
    Dado el listado de piezas, calcula:
    - ml_total: suma de ml de piezas en ML
    - m2_total: suma de m² de piezas en m² (pisos/revestimientos)
    - m2_material: m² totales de material necesario (todas las piezas)
    - piezas_ml: lista de piezas con unidad_venta==ml
    - piezas_m2: lista de piezas con unidad_venta==m2

    Cada pieza debe tener:
      - nombre (str)
      - largo (float)  → ml si es ml, largo del rectángulo si es m²
      - ancho (float)  → profundidad en ambos casos
      - unidad_venta ("ml" o "m2")
      - precio_unitario (float, opcional) → precio/ml o precio/m² de venta
    """
    ml_total = 0.0
    m2_total = 0.0
    m2_material = 0.0

    for p in piezas:
        largo = float(p.get("largo", p.get("ml", 0.0)))
        ancho = float(p.get("ancho", 0.60))
        uv    = p.get("unidad_venta", "ml")
        m2_p  = ml_a_m2(largo, ancho)
        m2_material += m2_p
        if uv == "ml":
            ml_total += largo
        else:
            m2_total += m2_p

    return {
        "ml_total":    round(ml_total, 3),
        "m2_total":    round(m2_total, 3),
        "m2_material": round(m2_material, 4),
    }


def calcular_logistica(vehiculo: str, km: float, num_peajes: int, agente_externo: bool,
                       personas: int = 2, categoria: str = "Mármol",
                       logistica_override: dict = None,
                       vehiculos_custom: dict = None) -> dict:
    """Calcula costo logístico completo desglosado."""
    p = logistica_override or LOGISTICA

    veh_cfg = (vehiculos_custom or {}).get(vehiculo) or VEHICULOS_CONFIG.get(vehiculo, VEHICULOS_CONFIG["externo"])
    es_externo = veh_cfg.get("tipo") == "externo"

    if es_externo:
        # Soporte para externo como dict {"flete": N} o como int legacy
        _ext_src = p.get("externo", {})
        _ext_flete_default = _ext_src.get("flete", 165_000) if isinstance(_ext_src, dict) else int(_ext_src)
        flete_ext = veh_cfg.get("flete", _ext_flete_default)
        costo_vehiculo = flete_ext
        costo_km   = 0.0
        costo_base = 0.0
    else:
        gasolina   = p.get("gasolina", LOGISTICA["gasolina"])
        rend       = veh_cfg.get("rend",     7.2)
        desg       = veh_cfg.get("desgaste", 148)
        costo_base = veh_cfg.get("base",  65_000)
        costo_por_km = (gasolina / rend) + desg
        costo_km     = costo_por_km * km * 2
        costo_vehiculo = costo_base + costo_km

    costo_peajes = num_peajes * p.get("peaje", LOGISTICA["peaje"])
    costo_herram = p.get("herram", LOGISTICA["herram"])
    costo_agente = p.get("agente", LOGISTICA["agente"]) if agente_externo else 0.0

    costo_total = costo_vehiculo + costo_peajes + costo_herram + costo_agente

    return {
        "total":    costo_total,
        "vehiculo": costo_vehiculo,
        "base":     costo_base if not es_externo else 0,
        "km_costo": costo_km,
        "peajes":   costo_peajes,
        "herram":   costo_herram,
        "agente":   costo_agente,
    }


def calcular_viaticos(activo: bool, tipo_aloj: str, noches: int, personas: int, viaticos_override: dict = None) -> float:
    if not activo or noches <= 0:
        return 0.0
    v_data = viaticos_override or VIATICOS
    tarifa_dict = v_data.get(tipo_aloj, v_data["pueblo"])
    # Soporte formato legacy (valor plano) y nuevo formato desglosado (dict)
    if isinstance(tarifa_dict, dict):
        costo_diario = sum(tarifa_dict.values())
    else:
        costo_diario = tarifa_dict
    return noches * personas * costo_diario


def calcular_adicionales(activos: bool, cantidades: list, etapa: str, lista: list) -> float:
    if not activos:
        return 0.0
    total = 0.0
    for i, a in enumerate(lista):
        qty = cantidades[i] if i < len(cantidades) else 0
        total += qty * a.get(etapa, a["terminada"])
    return total


def calcular_cotizacion_directa(
    categoria: str,
    referencia: str,
    precio_m2: float,
    area_placa_comprada: float,      # m² TOTAL de material comprado al proveedor
    m2_real: float,                  # m² del proyecto (área a cubrir, todas las piezas)
    m2_cortados: float,              # m² realmente cortados (incluye desperdicios)
    m2_usados: float,                # m² finalmente instalados
    margen_pct: float,
    dias: int,
    personas: int,
    zocalo_activo: bool,
    zocalo_ml: float,
    agente_externo_taller: bool,
    vehiculo_entrega: str,
    km: float,
    num_peajes: int,
    foraneo_activo: bool,
    viaticos_activos: bool,
    tipo_aloj: str,
    noches: int,
    adicionales_activos: bool,
    cantidades_add: list,
    etapa: str,
    adicionales_lista: list,
    tipo_proyecto: str = "",
    nombre_cliente: str = "",
    **kwargs,
) -> dict:
    _tarifas_src = kwargs.get("tarifas_override") or TARIFAS
    tar = _tarifas_src.get(categoria, TARIFAS["Mármol"])

    # ── ① Costo del material ──────────────────────────────────────────────────
    costo_material = precio_m2 * area_placa_comprada

    # ── ② Producción ──────────────────────────────────────────────────────────
    # ARQUITECTURA DUAL ML vs m²:
    #
    # TIPO BORDE (Mesón, Baño, Escalera, Cocina…):
    #   El operario cobra por ML cortado e instalado. Mayor cantidad de
    #   cortes de borde y perfilado → tarifa prod_ml por metro lineal.
    #
    # TIPO ÁREA (Piso, Fachada, Revestimiento):
    #   El operario trabaja por m² instalado. Menos cortes de borde,
    #   más colocación → tarifa prod_m2 por metro cuadrado.
    #   Esta tarifa DEBE venir de TARIFAS["Material"]["prod_m2"] — no se
    #   puede inferir dividiendo m2_real / 0.60 (eso era un hack incorrecto).
    #
    # Las piezas con unidad_venta=="m2" SIEMPRE usan prod_m2.
    # Las piezas con unidad_venta=="ml"  SIEMPRE usan prod_ml.
    # El tipo_proyecto actúa como tiebreaker en el fallback sin piezas.
    piezas = kwargs.get("piezas", [])

    ml_piezas = sum(
        float(p.get("largo", p.get("ml", 0)))
        for p in piezas if p.get("unidad_venta", "ml") == "ml"
    )
    m2_piezas = sum(
        ml_a_m2(float(p.get("largo", p.get("ml", 0))), float(p.get("ancho", 0.60)))
        for p in piezas if p.get("unidad_venta", "ml") == "m2"
    )

    # Tipos de proyecto que se pagan por área (no por borde)
    _TIPOS_AREA = {"Piso", "Fachada", "Revestimiento"}
    _es_tipo_area = any(t.strip() in _TIPOS_AREA for t in tipo_proyecto.split(",")) if tipo_proyecto else False

    # Fallback cuando no hay piezas explícitas (carga desde pre, atajo, etc.)
    ml_proyecto = kwargs.get("ml_proyecto", 0.0)
    if ml_piezas <= 0 and ml_proyecto > 0:
        ml_piezas = ml_proyecto

    if ml_piezas <= 0 and m2_piezas <= 0:
        if _es_tipo_area:
            # Proyecto de área: costear todo por m², sin convertir a ML ficticio
            m2_piezas = m2_real
        else:
            # Proyecto de borde: estimado razonable — 1 ML = 0.60 m de ancho estándar
            # Solo se usa cuando no hay piezas detalladas disponibles
            ml_piezas = m2_real / 0.60

    tarifa_prod_ml = tar.get("prod_ml", 60_000)
    # prod_m2 viene de TARIFAS (valor real calibrado por material).
    # El fallback 0.55×prod_ml se mantiene solo para retrocompatibilidad
    # con instalaciones donde prod_m2 aún no esté en la BD de config.
    tarifa_prod_m2 = tar.get("prod_m2", round(tarifa_prod_ml * 0.55))

    c2_ml = ml_piezas * tarifa_prod_ml
    c2_m2 = m2_piezas * tarifa_prod_m2
    c2    = c2_ml + c2_m2

    # ── ③ Zócalos ─────────────────────────────────────────────────────────────
    c3 = (zocalo_ml * tar["zocalo"]) if zocalo_activo else 0.0

    # ── ④ Insumos, Consumibles y Riesgo ──────────────────────────────────────
    m2_disco = m2_cortados if m2_cortados > 0 else m2_real
    costo_disco_maq  = (m2_disco * tar.get("disco", 2_200)) + (dias * tar.get("maquina", 20_000))
    costo_consumibles = m2_real * tar.get("consumibles", 10_000)   # Lijas, masilla, ceras, sellador
    costo_riesgo      = costo_material * tar.get("riesgo_rotura", 0.02)  # % provisión rotura
    c4 = costo_disco_maq + costo_consumibles + costo_riesgo

    # ── ⑤ Logística ──────────────────────────────────────────────────────────
    log_dict = calcular_logistica(
        vehiculo=vehiculo_entrega, km=km, num_peajes=num_peajes,
        agente_externo=agente_externo_taller, personas=personas, categoria=categoria,
        logistica_override=kwargs.get("logistica_override"),
        vehiculos_custom=kwargs.get("vehiculos_custom"),
    )
    c5 = log_dict["total"]

    # ── ⑥ Viáticos ───────────────────────────────────────────────────────────
    c6 = calcular_viaticos(foraneo_activo and viaticos_activos, tipo_aloj, noches, personas)

    # ── ⑦ Adicionales ────────────────────────────────────────────────────────
    c7 = calcular_adicionales(adicionales_activos, cantidades_add, etapa, adicionales_lista)

    costo_total = costo_material + c2 + c3 + c4 + c5 + c6 + c7

    # ── Precio sugerido global ────────────────────────────────────────────────
    margen = max(0.01, min(margen_pct / 100, 0.99))
    precio_sugerido = costo_total / (1 - margen)
    utilidad = precio_sugerido - costo_total

    # ── Precio unitario de venta desglosado por unidad ────────────────────────
    # Permite mostrar al cliente: "X ml × $YY.000/ml" y "Z m² × $WW.000/m²"
    precio_por_ml = (precio_sugerido / ml_piezas) if ml_piezas > 0 else 0.0
    precio_por_m2 = (precio_sugerido / max(m2_real, 0.001))

    # ── Retal y aprovechamiento ───────────────────────────────────────────────
    m2_ref = m2_usados if m2_usados > 0 else m2_real
    retal  = max(0.0, area_placa_comprada - m2_ref)
    aprovechamiento = min(100.0, m2_ref / area_placa_comprada * 100) if area_placa_comprada > 0 else 0.0

    return {
        # Identificación
        "categoria":         categoria,
        "referencia":        referencia,
        "tipo_proyecto":     tipo_proyecto,
        "nombre_cliente":    nombre_cliente,
        # Dimensiones
        "precio_m2":         precio_m2,
        "area_placa":        area_placa_comprada,
        "m2_real":           m2_real,
        "m2_cortados":       m2_cortados,
        "ml_proyecto":       ml_piezas,
        "m2_proyecto_m2":    m2_piezas,       # ← m² de piezas vendidas en m²
        "m2_usados":         m2_ref,
        "margen_pct":        margen_pct,
        "dias":              dias,
        "personas":          personas,
        # Costos
        "c1_material":       costo_material,
        "c2_mano_obra":      c2,
        "c2_ml":             c2_ml,
        "c2_m2":             c2_m2,
        "c3_zocalos":        c3,
        "c4_insumos":        c4,
        "c4_disco_maq":      costo_disco_maq,
        "c4_consumibles":    costo_consumibles,
        "c4_riesgo":         costo_riesgo,
        "c5_logistica":      c5,
        "c5_detalle":        log_dict,
        "c6_viaticos":       c6,
        "c7_adicionales":    c7,
        "costo_total":       costo_total,
        "precio_sugerido":   precio_sugerido,
        "utilidad":          utilidad,
        # Precios unitarios de venta
        "precio_por_ml":     precio_por_ml,
        "precio_por_m2_venta": precio_por_m2,
        # Retal
        "aprovechamiento":   aprovechamiento,
        "retal":             retal,
    }


def analizar_precio_real(precio_real: float, costo_total: float, precio_sugerido: float) -> dict:
    if precio_real <= 0:
        return {}
    utilidad_real = precio_real - costo_total
    margen_real   = (utilidad_real / precio_real * 100) if precio_real > 0 else 0
    diferencia    = precio_real - precio_sugerido
    return {
        "utilidad_real": utilidad_real,
        "margen_real":   margen_real,
        "diferencia":    diferencia,
        "estado":        "bueno" if margen_real >= 35 else "aceptable" if margen_real >= 20 else "bajo",
    }


def calcular_aiu(cd, pct_a, pct_i, pct_u, vehiculo, km, num_peajes,
                 agente_externo, foraneo_activo, tipo_aloj, noches, personas):
    """
    Cálculo AIU normativo colombiano.
    IVA (19%) solo sobre Utilidad (U) — Art. 3° Decreto 1372/92.
    """
    val_a   = cd * (pct_a / 100)
    val_i   = cd * (pct_i / 100)
    val_u   = cd * (pct_u / 100)
    val_iva = val_u * 0.19
    sub_aiu = val_a + val_i + val_u + val_iva
    log_dict  = calcular_logistica(vehiculo, km, num_peajes, agente_externo)
    logistica = log_dict["total"]
    viaticos  = calcular_viaticos(foraneo_activo, tipo_aloj, noches, personas)
    precio_total = cd + sub_aiu + logistica + viaticos
    margen_pct   = ((val_u + val_iva) / precio_total * 100) if precio_total > 0 else 0
    return {
        "cd": cd, "val_a": val_a, "val_i": val_i, "val_u": val_u,
        "val_iva": val_iva, "sub_aiu": sub_aiu,
        "logistica": logistica, "logistica_detalle": log_dict,
        "viaticos": viaticos,
        "precio_total": precio_total, "margen_pct": margen_pct,
        "pct_a": pct_a, "pct_i": pct_i, "pct_u": pct_u,
    }


def cop(valor: float) -> str:
    """Formato moneda colombiana: $1.250.000"""
    return "$" + f"{int(round(valor)):,}".replace(",", ".")


def fmt_decimal(valor: float, decimales: int = 2) -> str:
    """Número decimal colombiano: 3.450,75  (miles=punto, decimal=coma)"""
    fmt = f"{valor:,.{decimales}f}"          # Python: "3,450.75"
    partes = fmt.split(".")
    entero = partes[0].replace(",", ".")     # miles con punto
    dec    = partes[1] if len(partes) > 1 else ""
    if not dec or all(c == "0" for c in dec):
        return entero
    return f"{entero},{dec}"


def fmt_m2(valor: float, decimales: int = 3) -> str:
    """Metros cuadrados: 3,450 m²"""
    return fmt_decimal(valor, decimales) + " m²"


def fmt_ml(valor: float, decimales: int = 2) -> str:
    """Metros lineales: 3,50 ml"""
    return fmt_decimal(valor, decimales) + " ml"


def pct(valor: float) -> str:
    return f"{valor:.1f}%"
