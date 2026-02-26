# calculos.py — CostoMármol v2
# Motor de cálculo puro. Ahora el material se define por:
#   - categoria (tipo de piedra)
#   - precio_m2 (lo que el proveedor cobró)
#   - area_placa_comprada (área total de material comprado)

from parametros import LOGISTICA, VIATICOS, TARIFAS


def calcular_logistica(vehiculo: str, km: float, num_peajes: int, agente_externo: bool) -> float:
    p = LOGISTICA
    costo = 0.0
    if vehiculo == "externo":
        costo += p["externo"]["flete"]
    else:
        vh = p[vehiculo]
        costo_km = (p["gasolina"] / vh["rend"]) + vh["desgaste"]
        costo += vh["base"] + costo_km * km * 2   # ida y vuelta
    costo += num_peajes * p["peaje"]
    costo += p["herram"]
    if agente_externo:
        costo += p["agente"]
    return costo


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
    area_placa_comprada: float,
    m2_real: float,
    m2_usados: float,
    margen_pct: float,
    dias: int,
    personas: int,
    zocalo_activo: bool,
    zocalo_ml: float,
    vehiculo_taller: str,        # vehículo proveedor→taller (agente externo o no)
    agente_externo_taller: bool, # si agente externo trajo material al taller
    vehiculo_entrega: str,       # vehículo taller→cliente
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
    """
    Calcula cotización directa completa.
    El material se define por categoría + precio/m² que cobró el proveedor.
    """
    tar = TARIFAS.get(categoria, TARIFAS["Mármol"])

    # ── Costo del material (precio_m2 × área_comprada) ──
    costo_material = precio_m2 * area_placa_comprada

    # ── Mano de obra sobre m² reales del proyecto ──
    c2 = m2_real * (tar["corte"] + tar["elab"])

    # ── Zócalos ──
    c3 = (zocalo_ml * tar["zocalo"]) if zocalo_activo else 0.0

    # ── Insumos: disco (por m²) + desgaste máquina (por día) ──
    c4 = (m2_real * tar["disco"]) + (dias * tar["desgaste"])

    # ── Logística: el área comprada fue traída al taller por agente externo ──
    # + la entrega taller→cliente en el vehículo propio
    c5_taller = LOGISTICA["agente"] if agente_externo_taller else 0.0
    c5_entrega = calcular_logistica(vehiculo_entrega, km, num_peajes, False)
    c5 = c5_taller + c5_entrega

    # ── Viáticos ──
    c6 = calcular_viaticos(foraneo_activo and viaticos_activos, tipo_aloj, noches, personas)

    # ── Adicionales ──
    c7 = calcular_adicionales(adicionales_activos, cantidades_add, etapa, adicionales_lista)

    costo_total = costo_material + c2 + c3 + c4 + c5 + c6 + c7

    # ── Precio sugerido ──
    margen = max(0.01, min(margen_pct / 100, 0.99))
    precio_sugerido = costo_total / (1 - margen)
    utilidad = precio_sugerido - costo_total

    # ── Aprovechamiento ──
    m2_efectivos = m2_usados if m2_usados > 0 else m2_real
    retal = max(0.0, area_placa_comprada - m2_efectivos)
    aprovechamiento = min(100.0, m2_efectivos / area_placa_comprada * 100) if area_placa_comprada > 0 else 0.0

    return {
        # Datos del proyecto (para PDF)
        "categoria":          categoria,
        "referencia":         referencia,
        "precio_m2":          precio_m2,
        "area_placa":         area_placa_comprada,
        "m2_real":            m2_real,
        "m2_usados":          m2_efectivos,
        "tipo_proyecto":      tipo_proyecto,
        "nombre_cliente":     nombre_cliente,
        "margen_pct":         margen_pct,
        "dias":               dias,
        "personas":           personas,
        # Costos
        "c1_material":        costo_material,
        "c2_mano_obra":       c2,
        "c3_zocalos":         c3,
        "c4_insumos":         c4,
        "c5_logistica":       c5,
        "c5_taller":          c5_taller,
        "c5_entrega":         c5_entrega,
        "c6_viaticos":        c6,
        "c7_adicionales":     c7,
        "costo_total":        costo_total,
        "precio_sugerido":    precio_sugerido,
        "utilidad":           utilidad,
        # Lámina
        "aprovechamiento":    aprovechamiento,
        "retal":              retal,
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
                 agente_externo, foraneo_activo, tipo_aloj, noches, personas):
    val_a   = cd * (pct_a / 100)
    val_i   = cd * (pct_i / 100)
    val_u   = cd * (pct_u / 100)
    val_iva = val_u * 0.19
    sub_aiu = val_a + val_i + val_u + val_iva
    logistica = calcular_logistica(vehiculo, km, num_peajes, agente_externo)
    viaticos  = calcular_viaticos(foraneo_activo, tipo_aloj, noches, personas)
    precio_total = cd + sub_aiu + logistica + viaticos
    margen_pct   = ((val_u + val_iva) / precio_total * 100) if precio_total > 0 else 0
    return {
        "cd": cd, "val_a": val_a, "val_i": val_i, "val_u": val_u,
        "val_iva": val_iva, "sub_aiu": sub_aiu,
        "logistica": logistica, "viaticos": viaticos,
        "precio_total": precio_total, "margen_pct": margen_pct,
        "pct_a": pct_a, "pct_i": pct_i, "pct_u": pct_u,
    }


def cop(valor: float) -> str:
    return f"${int(round(valor)):,}".replace(",", ".")

def pct(valor: float) -> str:
    return f"{valor:.1f}%"
