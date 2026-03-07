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

from parametros import LOGISTICA, VIATICOS, TARIFAS, VEHICULOS_CONFIG, PROPIEDADES_MATERIAL


# ── Conversor ML → m² ────────────────────────────────────────────────────────
def ml_a_m2(ml: float, ancho_m: float) -> float:
    """Convierte metros lineales × ancho a m² de material."""
    return round(ml * ancho_m, 4)



def calcular_peso_proyecto(piezas: list, categoria: str) -> float:
    """
    Calcula el PESO TOTAL del proyecto en kg.

    Fórmula: Σ (área_pieza_m² × grosor_std_m × densidad_kg_m³)

    El grosor estándar y la densidad dependen del material (PROPIEDADES_MATERIAL).
    Si hay piezas de materiales distintos, se usa la densidad de cada pieza
    si está definida; si no, se usa la del material principal (categoria).

    Parámetros:
        piezas    : lista de piezas con llaves 'largo', 'ancho', 'categoria' (opcional)
        categoria : material principal del proyecto (fallback cuando pieza no tiene categoria)
    """
    props_default = PROPIEDADES_MATERIAL.get(categoria, PROPIEDADES_MATERIAL["Mármol"])
    peso_total = 0.0
    for p in piezas:
        # Soporte multi-material: cada pieza puede tener su propia categoría
        cat_pieza = p.get("categoria", categoria)
        props = PROPIEDADES_MATERIAL.get(cat_pieza, props_default)
        largo = float(p.get("largo", p.get("ml", 0.0)))
        ancho = float(p.get("ancho", 0.60))
        area_pieza = largo * ancho                             # m²
        grosor     = props["grosor_std_m"]                     # m
        densidad   = props["densidad_kg_m3"]                   # kg/m³
        # kg = m² × m × kg/m³ = volumen_m³ × densidad_kg_m³
        peso_total += area_pieza * grosor * densidad
    return round(peso_total, 2)


def calcular_merma_inteligente(piezas: list, categoria: str) -> dict:
    """
    Calcula el desperdicio por pieza usando el factor merma_base de cada material.

    Si hay piezas de distintos materiales, el desperdicio se calcula
    independientemente para cada pieza y se suma.

    Retorna:
        merma_total_m2  : m² totales de merma proyectada
        detalle         : lista de dicts {nombre, material, area_m2, merma_pct, merma_m2}
        explicacion_txt : texto en lenguaje natural para mostrar en st.info()
    """
    props_default = PROPIEDADES_MATERIAL.get(categoria, PROPIEDADES_MATERIAL["Mármol"])
    detalle = []
    merma_total = 0.0
    categorias_usadas = set()

    for p in piezas:
        cat_pieza = p.get("categoria", categoria)
        categorias_usadas.add(cat_pieza)
        props = PROPIEDADES_MATERIAL.get(cat_pieza, props_default)
        largo  = float(p.get("largo", p.get("ml", 0.0)))
        ancho  = float(p.get("ancho", 0.60))
        area   = largo * ancho
        merma_pct = props["merma_base"]
        merma_m2  = area * merma_pct
        merma_total += merma_m2
        detalle.append({
            "nombre":    p.get("nombre", "Pieza"),
            "material":  cat_pieza,
            "area_m2":   round(area, 3),
            "merma_pct": merma_pct,
            "merma_m2":  round(merma_m2, 3),
        })

    # Construir texto explicativo en lenguaje natural
    lineas = []
    for d in detalle:
        lineas.append(
            f"• **{d['nombre']}** ({d['material']}): {d['area_m2']:.2f} m² "
            f"× {d['merma_pct']*100:.0f}% merma = **{d['merma_m2']:.3f} m²** desperdicio"
        )
    explicacion = (
        "**Cálculo de merma por material** — cada pieza se evalúa de forma independiente "
        "según el factor de desperdicio propio de su material:\n" + "\n".join(lineas)
    )
    if "Sinterizado" in categorias_usadas:
        explicacion += (
            "\n\n⚠️ El **Sinterizado** tiene merma base del 15% por riesgo de fisura "
            "térmica durante el corte con disco diamantado."
        )

    return {
        "merma_total_m2": round(merma_total, 3),
        "detalle":        detalle,
        "explicacion_txt": explicacion,
    }

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
        # "ml" ya viene como el total efectivo (ml_unitario × cantidad) desde app.py
        # "largo" es el valor escalado. La cantidad ya está absorbida en "ml".
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
                       vehiculos_custom: dict = None,
                       peso_carga_kg: float = 0.0,
                       costo_peaje_unitario: float = 0.0) -> dict:
    """
    Calcula costo logístico completo desglosado.

    Innovación 3 — Logística por Peso y Mantenimiento:
      • El rendimiento km/gal se penaliza según el peso de la carga.
        Fórmula: rend_efectivo = rend_base × (1 - factor_penalizacion)
        factor_penalizacion = min(0.30, peso_kg / (peso_max × 2))
        — El vehículo pierde hasta un 30% de rendimiento a carga máxima.
      • Se suma costo_mantenimiento_por_km × km × 2 (ida y vuelta)
        como aporte al fondo de rodamiento (llantas, aceite, filtros).

    Innovación 7 — Peajes Exactos:
      • Si se pasa costo_peaje_unitario > 0, se usa num_peajes × costo_peaje_unitario.
      • Si no, se usa el peaje promedio del diccionario de logística (comportamiento legacy).
    """
    p = logistica_override or LOGISTICA

    veh_cfg = (vehiculos_custom or {}).get(vehiculo) or VEHICULOS_CONFIG.get(vehiculo, VEHICULOS_CONFIG["externo"])
    es_externo = veh_cfg.get("tipo") == "externo"

    costo_mantenimiento = 0.0

    if es_externo:
        _ext_src = p.get("externo", {})
        _ext_flete_default = _ext_src.get("flete", 165_000) if isinstance(_ext_src, dict) else int(_ext_src)
        flete_ext = veh_cfg.get("flete", _ext_flete_default)
        costo_vehiculo = flete_ext
        costo_km   = 0.0
        costo_base = 0.0
    else:
        gasolina   = p.get("gasolina", LOGISTICA["gasolina"])
        rend_base  = veh_cfg.get("rend",     7.2)
        desg       = veh_cfg.get("desgaste", 148)
        costo_base = veh_cfg.get("base",  65_000)
        mant_por_km = veh_cfg.get("costo_mantenimiento_por_km", 0)

        # ── Penalización km/gal por peso de carga ─────────────────────────────
        # A mayor peso, el motor trabaja más → menor rendimiento de gasolina.
        # Escalamos linealmente: 0 kg = sin penalización, peso_max = 30% menos.
        # peso_max = 2 × peso_max_penalizacion del material (aprox. capacidad útil).
        props_mat = PROPIEDADES_MATERIAL.get(categoria, {})
        peso_max_ref = props_mat.get("peso_max_penalizacion_kg", 300) * 2
        if peso_carga_kg > 0 and peso_max_ref > 0:
            factor_pen = min(0.30, peso_carga_kg / peso_max_ref)
        else:
            factor_pen = 0.0
        rend_efectivo = rend_base * (1 - factor_pen)

        costo_por_km = (gasolina / rend_efectivo) + desg
        costo_km     = costo_por_km * km * 2           # ida y vuelta
        # Fondo de rodamiento: aporte por km recorrido (llantas, aceite, filtros)
        costo_mantenimiento = mant_por_km * km * 2
        costo_vehiculo = costo_base + costo_km + costo_mantenimiento

    # ── Peajes exactos ────────────────────────────────────────────────────────
    # Si el usuario ingresó el costo unitario por peaje, se usa ese valor exacto.
    # Si no, se usa el peaje promedio configurado en LOGISTICA (modo legacy).
    if costo_peaje_unitario > 0:
        costo_peajes = num_peajes * costo_peaje_unitario
    else:
        costo_peajes = num_peajes * p.get("peaje", LOGISTICA["peaje"])

    costo_herram = p.get("herram", LOGISTICA["herram"])
    costo_agente = p.get("agente", LOGISTICA["agente"]) if agente_externo else 0.0

    costo_total = costo_vehiculo + costo_peajes + costo_herram + costo_agente

    return {
        "total":        costo_total,
        "vehiculo":     costo_vehiculo,
        "base":         costo_base if not es_externo else 0,
        "km_costo":     costo_km,
        "mantenimiento": costo_mantenimiento,
        "peajes":       costo_peajes,
        "herram":       costo_herram,
        "agente":       costo_agente,
        "peso_carga_kg": peso_carga_kg,
        "rend_efectivo": locals().get("rend_efectivo", 0),
    }


def calcular_viaticos(activo: bool, tipo_aloj: str, noches: int, personas: int,
                      viaticos_override: dict = None,
                      incluir_hospedaje: bool = True,
                      tipo_alimentacion: str = "completa") -> float:
    """
    Calcula el costo de viáticos con control granular por componente.

    Innovación 6 — Constructor de Viáticos:
      incluir_hospedaje   : True = suma hospedaje. False = solo alimentación + transporte.
      tipo_alimentacion   : "completa" = desayuno+almuerzo+cena ($65.000/día)
                            "almuerzo" = solo almuerzo ($25.000/día)
                            "ninguna"  = sin costo de alimentación

    Fórmula: (hospedaje_dia × incluir_hospedaje + comida_dia + transporte_dia)
              × dias × personas
    """
    if not activo or noches <= 0:
        return 0.0
    v_data = viaticos_override or VIATICOS
    tarifa_dict = v_data.get(tipo_aloj, v_data["pueblo"])

    # Soporte formato legacy (valor plano) — retrocompatibilidad total
    if not isinstance(tarifa_dict, dict):
        return noches * personas * float(tarifa_dict)

    # Componentes individuales del viático diario
    c_hospedaje   = tarifa_dict.get("hospedaje", 60_000)      if incluir_hospedaje       else 0
    c_transporte  = tarifa_dict.get("transporte_local", 20_000)

    if tipo_alimentacion == "almuerzo":
        c_alimento = tarifa_dict.get("almuerzo", 25_000)       # Solo almuerzo
    elif tipo_alimentacion == "completa":
        c_alimento = tarifa_dict.get("alimentacion", 65_000)   # Desayuno + almuerzo + cena
    else:
        c_alimento = 0                                          # Sin alimentación

    costo_diario = c_hospedaje + c_alimento + c_transporte
    return noches * personas * costo_diario


def calcular_adicionales(activos: bool, cantidades: list, etapa: str, lista: list) -> float:
    if not activos:
        return 0.0
    total = 0.0
    for i, a in enumerate(lista):
        qty = cantidades[i] if i < len(cantidades) else 0
        total += qty * a.get(etapa, a["terminada"])
    return total



def calcular_zocalo_geometrico(piezas: list) -> dict:
    """
    Calcula el total de ML y m² de zócalo a partir de los checkboxes geométricos
    y la altura de zócalo almacenados en cada pieza.

    Por cada pieza se evalúan 3 lados independientes:
      - zoc_trasero      : True → suma el LARGO de la pieza (ml_unitario × cantidad)
      - zoc_izq / zoc_der: True → suma el ANCHO de la pieza × cantidad

    Los ML se usan para la mano de obra (tarifa por metro lineal).
    Los m² = ML × (altura_zocalo_cm / 100) se suman al consumo de material
    de la placa para que el costo de piedra incluya la franja del zócalo.

    Retorna: dict con claves:
        "ml"  → float, total de metros lineales de zócalo
        "m2"  → float, área total de material consumido por el zócalo
    """
    total_ml = 0.0
    total_m2 = 0.0

    for p in piezas:
        cantidad       = int(p.get("cantidad", 1))
        ml_unitario    = float(p.get("ml_unitario", p.get("ml", 0.0)))
        ancho          = float(p.get("ancho_custom", 0.60))
        # altura_zocalo_cm: valor guardado por pieza; default 7 cm (estándar en obra residencial)
        altura_cm      = float(p.get("altura_zocalo_cm", 7.0))
        altura_cm      = max(1.0, min(altura_cm, 50.0))   # límites razonables

        ml_pieza = 0.0
        if p.get("zoc_trasero", False):
            ml_pieza += ml_unitario * cantidad
        if p.get("zoc_izq", False):
            ml_pieza += ancho * cantidad
        if p.get("zoc_der", False):
            ml_pieza += ancho * cantidad

        total_ml += ml_pieza
        # m² de material que consume el zócalo de esta pieza
        total_m2 += ml_pieza * (altura_cm / 100.0)

    return {
        "ml": round(total_ml, 3),
        "m2": round(total_m2, 4),
    }

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
    materiales_lista: list = None,   # Lista de dicts {cat, ref, precio_m2, area_placa} por material
    **kwargs,
) -> dict:
    _tarifas_src = kwargs.get("tarifas_override") or TARIFAS
    tar = _tarifas_src.get(categoria, TARIFAS["Mármol"])

    # ── ① Costo del material ──────────────────────────────────────────────────
    # costo_material base = costo de la placa comprada al proveedor.
    # El m² del zócalo se suma DESPUÉS de calcular zocalo_m2_calc (bloque ③),
    # por eso se inicializa aquí sin el extra y se ajusta más abajo.
    # MULTI-MATERIAL: si se recibe materiales_lista, el costo se calcula
    # sumando (area_placa × precio_m2) de cada material individualmente.
    # Esto evita aplicar el precio_m2 del primer material al área total.
    # FALLBACK retrocompatible: si no hay lista, usa parámetros clásicos.
    if materiales_lista:
        costo_material = sum(
            float(m.get("area_placa", 0)) * float(m.get("precio_m2", 0))
            for m in materiales_lista
        )
    else:
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

    # p["ml"] ya viene escalado (ml_unitario × cantidad) desde app.py
    # → no se necesita multiplicar aquí; la cantidad ya está absorbida.
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

    # ── ③ Zócalos — Geométrico por pieza (Innovación) ───────────────────────────
    # Si alguna pieza tiene checkboxes de zócalo geométrico → calcular_zocalo_geometrico().
    # Fallback: modo legacy con zocalo_activo + zocalo_ml (para recálculos de historial
    # y el atajo del sidebar donde las piezas antiguas no tienen estos campos).
    _piezas_zoc = kwargs.get("piezas", [])
    _tiene_zoc_geometrico = any(
        p.get("zoc_trasero") or p.get("zoc_izq") or p.get("zoc_der")
        for p in _piezas_zoc
    )
    if _tiene_zoc_geometrico:
        # Modo geométrico: ML y m² calculados automáticamente desde los lados/altura
        _zoc_geo         = calcular_zocalo_geometrico(_piezas_zoc)
        zocalo_ml_calc   = _zoc_geo["ml"]
        zocalo_m2_calc   = _zoc_geo["m2"]   # área de piedra que consume el zócalo
        c3 = zocalo_ml_calc * tar["zocalo"]
    else:
        # Modo legacy: el usuario ingresó el total manual (zocalo_activo + zocalo_ml)
        zocalo_ml_calc = zocalo_ml if zocalo_activo else 0.0
        zocalo_m2_calc = 0.0   # sin dato de altura → no suma m² (retrocompatible)
        c3 = zocalo_ml_calc * tar["zocalo"]
    # Exponer el ML real y los m² de material usados en zócalos (para PDF y UI)
    zocalo_ml_efectivo = zocalo_ml_calc
    zocalo_m2_efectivo = zocalo_m2_calc

    # ── Ajuste de costo de material por m² de zócalo ─────────────────────────
    # Los zócalos se cortan de la misma placa comprada. Si el proveedor no vendió
    # una placa extra para el zócalo, el m² ya está en area_placa_comprada y
    # costo_material ya cubre ese material. Este extra se activa SOLO cuando
    # zocalo_m2_calc > 0 (modo geométrico con altura), y representa el costo de
    # la fracción de piedra asignada al zócalo que, de otro modo, no quedaría
    # reflejada en el costo (porque area_placa_comprada es la lámina principal).
    # FIX: Los zócalos se cortan de la placa principal ya costeada.
    # costo_extra_material_zocalo = 0 elimina el doble cobro.
    # La mano de obra del zócalo sí se sigue cobrando en c3.
    costo_extra_material_zocalo = 0.0
    costo_material_total = costo_material   # sin doble cobro

    # ── ④ Insumos, Consumibles y Riesgo ──────────────────────────────────────
    m2_disco = m2_cortados if m2_cortados > 0 else m2_real
    costo_disco_maq  = (m2_disco * tar.get("disco", 2_200)) + (dias * tar.get("maquina", 20_000))
    costo_consumibles = m2_real * tar.get("consumibles", 10_000)   # Lijas, masilla, ceras, sellador
    # RIESGO POR MATERIAL: si hay lista multi-material, se calcula el riesgo
    # de rotura individualmente por categoría (sinterizado tiene mayor riesgo).
    # FALLBACK retrocompatible: aplica la tarifa de la categoría principal.
    if materiales_lista:
        _tarifas_riesgo_src = kwargs.get("tarifas_override") or TARIFAS
        costo_riesgo = sum(
            float(m.get("area_placa", 0)) * float(m.get("precio_m2", 0))
            * _tarifas_riesgo_src.get(m.get("cat", categoria), TARIFAS["Mármol"]).get("riesgo_rotura", 0.02)
            for m in materiales_lista
        )
    else:
        costo_riesgo = costo_material * tar.get("riesgo_rotura", 0.02)  # % provisión rotura
    c4 = costo_disco_maq + costo_consumibles + costo_riesgo

    # ── ⑤ Logística con peso de carga y peajes exactos ──────────────────────
    # Calculamos el peso total para penalizar el rendimiento km/gal del vehículo
    _piezas_log = kwargs.get("piezas", [])
    peso_carga_kg = calcular_peso_proyecto(_piezas_log, categoria) if _piezas_log else 0.0
    log_dict = calcular_logistica(
        vehiculo=vehiculo_entrega, km=km, num_peajes=num_peajes,
        agente_externo=agente_externo_taller, personas=personas, categoria=categoria,
        logistica_override=kwargs.get("logistica_override"),
        vehiculos_custom=kwargs.get("vehiculos_custom"),
        peso_carga_kg=peso_carga_kg,
        costo_peaje_unitario=kwargs.get("costo_peaje_unitario", 0.0),
    )
    c5 = log_dict["total"]

    # ── ⑥ Viáticos con constructor granular ───────────────────────────────────
    c6 = calcular_viaticos(
        activo=foraneo_activo and viaticos_activos,
        tipo_aloj=tipo_aloj,
        noches=noches,
        personas=personas,
        viaticos_override=kwargs.get("viaticos_override"),
        incluir_hospedaje=kwargs.get("incluir_hospedaje", True),
        tipo_alimentacion=kwargs.get("tipo_alimentacion", "completa"),
    )

    # ── ⑦ Adicionales ────────────────────────────────────────────────────────
    c7 = calcular_adicionales(adicionales_activos, cantidades_add, etapa, adicionales_lista)

    costo_total = costo_material_total + c2 + c3 + c4 + c5 + c6 + c7

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

    # ── Merma inteligente multi-material ─────────────────────────────────────
    _merma_info = calcular_merma_inteligente(kwargs.get("piezas", []), categoria)

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
        "c1_material":       costo_material_total,   # incluye m² del zócalo
        "c1_material_placa":  costo_material,          # solo placa principal
        "c1_material_zocalo": costo_extra_material_zocalo,  # extra por zócalo
        "c2_mano_obra":      c2,
        "c2_ml":             c2_ml,
        "c2_m2":             c2_m2,
        "c3_zocalos":        c3,
        "zocalo_ml_efectivo": zocalo_ml_efectivo,
        "zocalo_m2_efectivo": zocalo_m2_efectivo,  # m² de material consumido en zócalos
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
        # Peso y merma
        "peso_carga_kg":     peso_carga_kg,
        "merma_info":        _merma_info,
        "merma_total_m2":    _merma_info["merma_total_m2"],
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
                 agente_externo, foraneo_activo, tipo_aloj, noches, personas,
                 incluir_iva: bool = True):
    """
    Cálculo AIU normativo colombiano.
    IVA (19%) solo sobre Utilidad (U) — Art. 3° Decreto 1372/92.

    incluir_iva=False: cotización exenta (régimen simplificado).
    En ese caso val_iva=0 y el total se ajusta dinámicamente.
    """
    val_a   = cd * (pct_a / 100)
    val_i   = cd * (pct_i / 100)
    val_u   = cd * (pct_u / 100)
    # IVA solo sobre Utilidad — si exento, val_iva es 0 y no suma al total
    val_iva = val_u * 0.19 if incluir_iva else 0.0
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
        "incluir_iva": incluir_iva,
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
