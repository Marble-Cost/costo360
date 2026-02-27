# calculos.py — CostoMármol v3
# Motor de cálculo. Correcciones v3:
#   - Logística corregida: externo NO calcula km (flete fijo)
#   - Costo traslado operarios incluido en logística (tiempo de ida+vuelta)
#   - Mano de obra calculada sobre m² de material trabajado (no solo m² instalados)
#   - Función ml_a_m2 para convertir metros lineales a m²

from parametros import LOGISTICA, VIATICOS, TARIFAS


# ── Conversor ML → m² ────────────────────────────────────────────────────────
def ml_a_m2(ml: float, ancho_m: float) -> float:
    """
    Convierte metros lineales de corte a m² de material.
    Ejemplo: 4 ml de mesón × 0.60 m de ancho = 2.40 m²
    """
    return round(ml * ancho_m, 4)


def horas_traslado_estimadas(km: float) -> float:
    """Estima horas de traslado ida+vuelta según distancia."""
    if km <= 15:
        return 1.0   # 30 min ida + 30 min vuelta
    elif km <= 40:
        return 2.0   # 1h ida + 1h vuelta
    else:
        return 4.0   # 2h ida + 2h vuelta (foráneo)


def calcular_logistica(vehiculo: str, km: float, num_peajes: int, agente_externo: bool,
                       personas: int = 2, categoria: str = "Mármol") -> dict:
    """
    Calcula costo logístico completo desglosado.
    
    CORREGIDO v3:
    - Externo solo paga flete fijo, no km propios
    - Se incluye costo de tiempo de operarios en traslado
    - Devuelve dict con desglose para transparencia
    """
    p = LOGISTICA
    tar = TARIFAS.get(categoria, TARIFAS["Mármol"])

    # ── Costo vehículo ────────────────────────────────────────────────────────
    if vehiculo == "externo":
        # Flete fijo. No hay costo de gasolina propio ni desgaste del vehículo.
        costo_vehiculo = p["externo"]["flete"]
        costo_km = 0.0
        costo_base = 0.0
    else:
        vh = p[vehiculo]
        # Costo por km = gasolina + desgaste mecánico
        # gasolina en COP/galón ÷ rendimiento km/galón = COP/km
        costo_por_km = (p["gasolina"] / vh["rend"]) + vh["desgaste"]
        # ida y vuelta (el vehículo regresa vacío)
        costo_km = costo_por_km * km * 2
        costo_base = vh["base"]
        costo_vehiculo = costo_base + costo_km

    # ── Peajes ────────────────────────────────────────────────────────────────
    costo_peajes = num_peajes * p["peaje"]

    # ── Herramientas ─────────────────────────────────────────────────────────
    costo_herram = p["herram"]

    # ── Flete agente externo (proveedor → taller) ─────────────────────────────
    costo_agente = p["agente"] if agente_externo else 0.0

    # ── Costo de tiempo de operarios en traslado ─────────────────────────────
    # Los operarios no trabajan material mientras viajan: ese tiempo tiene costo real
    # Solo aplica para vehículo propio (si es externo el transportador no es tu operario)
    if vehiculo != "externo" and km > 0:
        horas = horas_traslado_estimadas(km)
        costo_traslado_mo = horas * personas * tar["mo_hora"]
    else:
        costo_traslado_mo = 0.0

    costo_total = costo_vehiculo + costo_peajes + costo_herram + costo_agente + costo_traslado_mo

    return {
        "total":           costo_total,
        "vehiculo":        costo_vehiculo,
        "base":            costo_base if vehiculo != "externo" else 0,
        "km_costo":        costo_km,
        "peajes":          costo_peajes,
        "herram":          costo_herram,
        "agente":          costo_agente,
        "traslado_mo":     costo_traslado_mo,
    }


def calcular_viaticos(activo: bool, tipo_aloj: str, noches: int, personas: int) -> float:
    if not activo or noches <= 0:
        return 0.0
    tarifa = VIATICOS.get(tipo_aloj, VIATICOS["pueblo"])
    return noches * personas * tarifa


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
    area_placa_comprada: float,      # m² TOTAL de material comprado
    m2_real: float,                  # m² del proyecto (área a cubrir)
    m2_cortados: float,              # m² REALMENTE cortados de la placa (mano de obra real)
    m2_usados: float,                # m² que quedaron instalados (para retal)
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
) -> dict:
    tar = TARIFAS.get(categoria, TARIFAS["Mármol"])

    # ── ① Costo del material ──────────────────────────────────────────────────
    costo_material = precio_m2 * area_placa_comprada

    # ── ② Mano de obra ────────────────────────────────────────────────────────
    # CORRECCIÓN v3: la mano de obra (corte + elaboración) se aplica sobre
    # los m² CORTADOS de la placa, no solo sobre los m² instalados.
    # Si cortaste 4.2 m² para un proyecto de 3.6 m², pagas por 4.2 m² de trabajo.
    m2_mo = m2_cortados if m2_cortados > 0 else m2_real
    c2 = m2_mo * (tar["corte"] + tar["elab"])

    # ── ③ Zócalos ─────────────────────────────────────────────────────────────
    c3 = (zocalo_ml * tar["zocalo"]) if zocalo_activo else 0.0

    # ── ④ Insumos ─────────────────────────────────────────────────────────────
    # Disco se calcula sobre m² cortados (el disco se gasta al cortar, no al instalar)
    m2_disco = m2_cortados if m2_cortados > 0 else m2_real
    c4 = (m2_disco * tar["disco"]) + (dias * tar["desgaste"])

    # ── ⑤ Logística ──────────────────────────────────────────────────────────
    log_dict = calcular_logistica(
        vehiculo=vehiculo_entrega,
        km=km,
        num_peajes=num_peajes,
        agente_externo=agente_externo_taller,
        personas=personas,
        categoria=categoria,
    )
    c5 = log_dict["total"]

    # ── ⑥ Viáticos ───────────────────────────────────────────────────────────
    c6 = calcular_viaticos(foraneo_activo and viaticos_activos, tipo_aloj, noches, personas)

    # ── ⑦ Adicionales ────────────────────────────────────────────────────────
    c7 = calcular_adicionales(adicionales_activos, cantidades_add, etapa, adicionales_lista)

    costo_total = costo_material + c2 + c3 + c4 + c5 + c6 + c7

    # ── Precio sugerido ───────────────────────────────────────────────────────
    margen = max(0.01, min(margen_pct / 100, 0.99))
    precio_sugerido = costo_total / (1 - margen)
    utilidad = precio_sugerido - costo_total

    # ── Retal y aprovechamiento ───────────────────────────────────────────────
    m2_ref = m2_usados if m2_usados > 0 else m2_real
    retal = max(0.0, area_placa_comprada - m2_ref)
    aprovechamiento = min(100.0, m2_ref / area_placa_comprada * 100) if area_placa_comprada > 0 else 0.0

    return {
        # Identificación
        "categoria":         categoria,
        "referencia":        referencia,
        "tipo_proyecto":     tipo_proyecto,
        "nombre_cliente":    nombre_cliente,
        # Áreas
        "precio_m2":         precio_m2,
        "area_placa":        area_placa_comprada,
        "m2_real":           m2_real,
        "m2_cortados":       m2_mo,
        "m2_usados":         m2_ref,
        "margen_pct":        margen_pct,
        "dias":              dias,
        "personas":          personas,
        # Costos
        "c1_material":       costo_material,
        "c2_mano_obra":      c2,
        "c3_zocalos":        c3,
        "c4_insumos":        c4,
        "c5_logistica":      c5,
        "c5_detalle":        log_dict,    # desglose logística
        "c6_viaticos":       c6,
        "c7_adicionales":    c7,
        "costo_total":       costo_total,
        "precio_sugerido":   precio_sugerido,
        "utilidad":          utilidad,
        # Retal
        "aprovechamiento":   aprovechamiento,
        "retal":             retal,
    }


def analizar_precio_real(precio_real: float, costo_total: float, precio_sugerido: float) -> dict:
    if precio_real <= 0:
        return {}
    utilidad_real = precio_real - costo_total
    margen_real = (utilidad_real / precio_real * 100) if precio_real > 0 else 0
    diferencia = precio_real - precio_sugerido
    return {
        "utilidad_real": utilidad_real,
        "margen_real":   margen_real,
        "diferencia":    diferencia,
        "estado":        "bueno" if margen_real >= 35 else "aceptable" if margen_real >= 20 else "bajo",
    }


def calcular_aiu(cd, pct_a, pct_i, pct_u, vehiculo, km, num_peajes,
                 agente_externo, foraneo_activo, tipo_aloj, noches, personas,
                 logistica_override=None, vehiculos_custom=None):
    val_a   = cd * (pct_a / 100)
    val_i   = cd * (pct_i / 100)
    val_u   = cd * (pct_u / 100)
    val_iva = val_u * 0.19
    sub_aiu = val_a + val_i + val_u + val_iva
    log_dict = calcular_logistica(vehiculo, km, num_peajes, agente_externo, logistica_override=logistica_override, vehiculos_custom=vehiculos_custom)
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
    return f"${int(round(valor)):,}".replace(",", ".")


def pct(valor: float) -> str:
    return f"{valor:.1f}%"
