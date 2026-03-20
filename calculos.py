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

from parametros import LOGISTICA, VIATICOS, TARIFAS, PROPIEDADES_MATERIAL


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

    Retorna:
        float — peso total en kg, redondeado a 2 decimales.
    """
    props_default = PROPIEDADES_MATERIAL.get(categoria, PROPIEDADES_MATERIAL["Mármol"])
    peso_total = 0.0
    for p in piezas:
        # Soporte multi-material: cada pieza puede tener su propia categoría
        cat_pieza = p.get("categoria", categoria)
        props = PROPIEDADES_MATERIAL.get(cat_pieza, props_default)
        largo_total = float(p.get("ml", float(p.get("largo", 0.0)) * int(p.get("cantidad", 1))))
        ancho = float(p.get("ancho_custom", p.get("ancho", 0.60)))
        area_pieza = largo_total * ancho                       # m²
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
        largo_total = float(p.get("ml", float(p.get("largo", 0.0)) * int(p.get("cantidad", 1))))
        ancho  = float(p.get("ancho", 0.60))
        area   = largo_total * ancho
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
        largo_total = float(p.get("ml", float(p.get("largo", 0.0)) * int(p.get("cantidad", 1))))
        ancho = float(p.get("ancho", 0.60))
        uv    = p.get("unidad_venta", "ml")
        # largo_total usa "ml" (ya escalado por cantidad desde app.py) o
        # calcula largo × cantidad cuando "ml" no está presente.
        m2_p  = ml_a_m2(largo_total, ancho)
        m2_material += m2_p
        if uv == "ml":
            ml_total += largo_total
        else:
            m2_total += m2_p

    return {
        "ml_total":    round(ml_total, 3),
        "m2_total":    round(m2_total, 3),
        "m2_material": round(m2_material, 4),
    }


def calcular_logistica(vehiculo: str = "externo",
                       km: float = 0.0,
                       num_peajes: int = 0,
                       agente_externo: bool = False,
                       personas: int = 2,
                       categoria: str = "Mármol",
                       logistica_override: dict = None,
                       vehiculos_custom: dict = None,
                       peso_carga_kg: float = 0.0,
                       costo_peaje_unitario: float = 0.0) -> dict:
    """
    Calcula el costo logístico del viaje al cliente.

    Modelo simplificado v6 (sin flota propia):
      • Si agente_externo=True  → se usa flete_externo del diccionario de logística.
      • Si agente_externo=False → se estima el costo de combustible por km usando
        precio_gasolina y un rendimiento estándar de 10 km/galón (vehículo propio
        genérico), más un costo base de salida fijo de $30.000.

    El costo total de peajes de la ruta llega ya calculado en `costo_peaje_unitario`
    (el campo "Costo Total de Peajes de la Ruta" de la UI). No se usa num_peajes.

    Los parámetros vehiculo, vehiculos_custom y peso_carga_kg se aceptan por
    compatibilidad con llamadas heredadas y se ignoran sin efecto.
    """
    p = logistica_override or LOGISTICA

    # ── Flete externo (agente trae el material al taller) ────────────────────
    # Lee primero la nueva llave "flete_externo" y cae en legados si no existe.
    _flete_ext = p.get("flete_externo",
                    p.get("externo", {}).get("flete", 165_000)
                    if isinstance(p.get("externo"), dict)
                    else p.get("externo", 165_000)
                )
    costo_agente = float(_flete_ext) if agente_externo else 0.0

    # ── Costo de desplazamiento al cliente ───────────────────────────────────
    # Usa precio_gasolina con rendimiento genérico 10 km/gal.
    # Aplica ida y vuelta (× 2). Si km = 0 no se cobra nada.
    _gasolina    = p.get("precio_gasolina", p.get("gasolina", 16_000))
    _rend_std    = 10.0          # km/galón — vehículo propio estándar sin especificar
    _base_salida = 30_000.0      # costo mínimo fijo por salir al terreno
    if km > 0:
        costo_km       = (_gasolina / _rend_std) * km * 2   # ida y vuelta
        costo_vehiculo = _base_salida + costo_km
    else:
        costo_km       = 0.0
        costo_vehiculo = 0.0

    # ── Peajes ───────────────────────────────────────────────────────────────
    # costo_peaje_unitario ya contiene el total exacto de la ruta (nueva UI).
    costo_peajes = float(costo_peaje_unitario)

    costo_total = costo_vehiculo + costo_peajes + costo_agente

    return {
        "total":             costo_total,
        "vehiculo":          costo_vehiculo,
        "base":              _base_salida if km > 0 else 0.0,
        "km_costo":          costo_km,
        "mantenimiento":     0.0,
        "peajes":            costo_peajes,
        "herram":            0.0,
        "agente":            costo_agente,
        "peso_carga_kg":     peso_carga_kg,
        "rend_efectivo":     _rend_std,
        "bloqueo_capacidad": False,
        "nota_bloqueo":      "",
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
        ml_unitario    = float(p.get("ml_unitario", p.get("largo", 0.0)))
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
    estrategia_precio: str = "placa_completa",   # "placa_completa" | "optimizado"
    **kwargs,
) -> dict:
    _tarifas_src = kwargs.get("tarifas_override") or TARIFAS
    tar = _tarifas_src.get(categoria, TARIFAS["Mármol"])

    # ── ① Costo del material — Motor de Doble Estrategia ─────────────────────
    # PLACA COMPLETA (tradicional): cobra el área total de placa comprada al proveedor.
    # OPTIMIZADO (producto terminado): cobra solo el área neta de las piezas + su
    # merma técnica real por material. El excedente queda como retal del taller.
    materiales_lista = kwargs.get("materiales_lista", [])
    piezas_temp      = kwargs.get("piezas", [])   # leído aquí para el bloque ①; reasignado en ②

    # ── Rama PLACA COMPLETA ────────────────────────────────────────────────────
    if materiales_lista:
        costo_material_placa_completa = sum(
            float(m.get("area_placa", 0)) * float(m.get("precio_m2", 0))
            for m in materiales_lista
        )
    else:
        costo_material_placa_completa = precio_m2 * area_placa_comprada

    # ── Rama OPTIMIZADO ───────────────────────────────────────────────────────
    # Área neta por pieza × (1 + merma_base del material) × precio_m2 del material.
    # Si no hay piezas detalladas, cae al modo placa_completa como salvaguarda.
    if estrategia_precio == "optimizado" and piezas_temp:
        costo_material_optimizado = 0.0
        for _p in piezas_temp:
            _cat_p   = _p.get("categoria", categoria)
            _props_p = PROPIEDADES_MATERIAL.get(_cat_p, PROPIEDADES_MATERIAL.get(categoria, {}))
            _merma_p = float(_props_p.get("merma_base", 0.08))
            _largo_p = float(_p.get("ml", float(_p.get("largo", 0.0)) * int(_p.get("cantidad", 1))))
            _ancho_p = float(_p.get("ancho_custom", _p.get("ancho", 0.60)))
            _area_p  = _largo_p * _ancho_p
            # Precio del material: busca en materiales_lista por categoría, fallback a precio_m2 global
            _pm2_p   = precio_m2  # default
            if materiales_lista:
                for _m in materiales_lista:
                    if _m.get("cat", _m.get("categoria", "")) == _cat_p:
                        _pm2_p = float(_m.get("precio_m2", precio_m2))
                        break
            costo_material_optimizado += _area_p * (1.0 + _merma_p) * _pm2_p
        costo_material = costo_material_optimizado
    else:
        costo_material = costo_material_placa_completa

    # Ganancia oculta: diferencia que queda en el taller como retal rentable
    ganancia_oculta_retal = max(0.0, costo_material_placa_completa - costo_material)

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

    # Tipos de proyecto que se pagan por área (no por borde)
    _TIPOS_AREA = {"Piso", "Fachada", "Revestimiento"}
    _es_tipo_area = any(t.strip() in _TIPOS_AREA for t in tipo_proyecto.split(",")) if tipo_proyecto else False

    # ── Adaptador: formato plano legacy → formato de receta dinámica ──────────
    # El editor de tarifas de app.py guarda en BD el formato plano (prod_ml, disco…)
    # para no requerir migración de datos históricos. Este adaptador convierte
    # ambos formatos a una lista de reglas homogénea antes de ejecutar el motor.
    # Si el dict ya es una lista (formato receta nativo), se usa directamente.
    def _tar_a_receta(tar_dict: dict) -> list:
        """Convierte un dict plano de tarifas al formato de lista de reglas."""
        return [
            {"nombre_interno": "Mano obra borde",       "inductor": "por_ml",              "valor": float(tar_dict.get("prod_ml",       60_000)), "etiqueta_pdf": "c2_mano_obra"},
            {"nombre_interno": "Mano obra área",         "inductor": "por_m2",              "valor": float(tar_dict.get("prod_m2",       35_000)), "etiqueta_pdf": "c2_mano_obra"},
            {"nombre_interno": "Instalación zócalo",     "inductor": "por_ml_zocalo",       "valor": float(tar_dict.get("zocalo",        12_000)), "etiqueta_pdf": "c3_zocalos"},
            {"nombre_interno": "Desgaste disco",         "inductor": "por_m2",              "valor": float(tar_dict.get("disco",          2_200)), "etiqueta_pdf": "c4_insumos"},
            {"nombre_interno": "Uso máquina cortadora",  "inductor": "por_dia",             "valor": float(tar_dict.get("maquina",       20_000)), "etiqueta_pdf": "c4_insumos"},
            {"nombre_interno": "Consumibles",            "inductor": "por_m2",              "valor": float(tar_dict.get("consumibles",    8_500)), "etiqueta_pdf": "c4_insumos"},
            {"nombre_interno": "Riesgo rotura",          "inductor": "porcentaje_material", "valor": float(tar_dict.get("riesgo_rotura",  0.02)), "etiqueta_pdf": "c4_insumos"},
        ]

    def _resolver_receta(tar_entry) -> list:
        """Devuelve siempre una lista de reglas, independientemente del formato de entrada."""
        if isinstance(tar_entry, list):
            return tar_entry          # formato receta nativo (parametros.py v4)
        if isinstance(tar_entry, dict):
            return _tar_a_receta(tar_entry)   # formato plano legacy (BD / tarifas_override)
        return _tar_a_receta({})      # fallback vacío — usa valores hardcoded de respaldo

    # ── ② Producción + ③ Zócalos + ④ Insumos — Motor de Buckets ─────────────
    # El motor itera la RECETA de cada material por pieza y acumula los costos
    # en tres buckets (c2, c3, c4) según la etiqueta_pdf de cada regla.
    #
    # Inductores disponibles:
    #   "por_ml"              → valor × ml_de_la_pieza         (piezas tipo borde)
    #   "por_m2"              → valor × m²_de_la_pieza         (piezas tipo área)
    #   "por_dia"             → valor × dias_del_proyecto       (costo global, 1 sola vez)
    #   "porcentaje_material" → valor × costo_material_pieza    (riesgo proporcional)
    #   "por_ml_zocalo"       → valor × ml_zócalo_de_la_pieza  (instalación de zócalo)
    #
    # FALLBACK RETROCOMPATIBLE (if not piezas):
    # Si no hay lista de piezas (historial antiguo, cotización rápida, atajo del
    # sidebar), se usa la lógica global con ml_proyecto y tarifas del material
    # principal para que esos registros no se rompan.
    if piezas:
        acumulados = {"c2_mano_obra": 0.0, "c3_zocalos": 0.0, "c4_insumos": 0.0}
        ml_piezas      = 0.0   # acumulado total para precio_por_ml y métricas de UI
        m2_piezas      = 0.0
        zocalo_ml_calc = 0.0
        zocalo_m2_calc = 0.0

        # ── Costo de insumos con inductor "por_dia" ────────────────────────────
        # Este inductor representa costos fijos del proyecto (ej: alquiler de
        # máquina cortadora), no del metro lineal de cada pieza. Si se sumara
        # dentro del loop de piezas se multiplicaría por el número de piezas.
        # Solución: se aplica UNA SOLA VEZ aquí, usando la receta del material
        # principal del proyecto (primer material de materiales_lista, o categoria).
        _cat_global  = (materiales_lista[0].get("cat", categoria) if materiales_lista else categoria)
        _tar_global  = _tarifas_src.get(_cat_global, _tarifas_src.get(categoria, TARIFAS.get("Mármol", {})))
        _receta_glob = _resolver_receta(_tar_global)
        for _regla_g in _receta_glob:
            if _regla_g["inductor"] == "por_dia":
                _bucket_g = _regla_g["etiqueta_pdf"]
                if _bucket_g in acumulados:
                    acumulados[_bucket_g] += _regla_g["valor"] * dias

        # ── Loop por pieza: inductores proporcionales ──────────────────────────
        for p in piezas:
            # Categoría y receta propias de esta pieza
            cat_p    = p.get("categoria", categoria)
            tar_p    = _tarifas_src.get(cat_p, _tarifas_src.get(categoria, TARIFAS.get("Mármol", {})))
            receta_p = _resolver_receta(tar_p)

            # Dimensiones de la pieza
            largo_total = float(p.get("ml", float(p.get("largo", 0.0)) * int(p.get("cantidad", 1))))
            ancho_p     = float(p.get("ancho_custom", p.get("ancho", 0.60)))
            area_p      = ml_a_m2(largo_total, ancho_p)
            uv          = p.get("unidad_venta", "ml")

            # Acumular métricas globales de dimensión
            if uv == "ml":
                ml_piezas += largo_total
            else:
                m2_piezas += area_p

            # Zócalo geométrico individual — aisla la pieza para aplicar SU tarifa
            _zoc_p       = calcular_zocalo_geometrico([p])
            ml_zoc_p     = _zoc_p["ml"]
            m2_zoc_p     = _zoc_p["m2"]
            zocalo_ml_calc += ml_zoc_p
            zocalo_m2_calc += m2_zoc_p

            # Costo del material de esta pieza (para inductor porcentaje_material)
            _costo_mat_p = 0.0
            if materiales_lista:
                for _m in materiales_lista:
                    if _m.get("cat", _m.get("categoria", "")) == cat_p:
                        _costo_mat_p = float(_m.get("area_placa", 0)) * float(_m.get("precio_m2", 0))
                        break
            if _costo_mat_p == 0.0:
                # Fallback: prorratear costo_material proporcionalmente por área
                _costo_mat_p = costo_material * (area_p / max(m2_real, 0.001))

            # ── Aplicar reglas de la receta (excluir "por_dia", ya calculado) ──
            for regla in receta_p:
                inductor = regla["inductor"]
                valor    = regla["valor"]
                bucket   = regla["etiqueta_pdf"]
                if bucket not in acumulados:
                    continue   # etiqueta desconocida → ignorar con seguridad

                if inductor == "por_dia":
                    pass       # ya calculado globalmente antes del loop
                elif inductor == "por_ml" and uv == "ml":
                    acumulados[bucket] += valor * largo_total
                elif inductor == "por_m2":
                    # por_m2 aplica a todas las piezas (disco, consumibles)
                    # Para mano obra área: solo si la unidad de venta es m²
                    _es_mo_area = regla.get("nombre_interno", "").lower().startswith("mano obra área")
                    if _es_mo_area:
                        if uv == "m2":
                            acumulados[bucket] += valor * area_p
                    else:
                        # Insumos y consumibles aplican a toda el área cortada
                        acumulados[bucket] += valor * area_p
                elif inductor == "porcentaje_material":
                    acumulados[bucket] += valor * _costo_mat_p
                elif inductor == "por_ml_zocalo":
                    acumulados[bucket] += valor * ml_zoc_p

        # ── Asignar buckets a variables legacy ────────────────────────────────
        c2_ml = acumulados["c2_mano_obra"]   # no se desglosará ml/m2 en el motor de recetas;
        c2_m2 = 0.0                           # c2_ml lleva el total — ver nota en return dict
        c2    = acumulados["c2_mano_obra"]
        c3    = acumulados["c3_zocalos"]

        # Descomponer c4 en sub-llaves legacy para el dict de salida
        # (generador_pdf.py y el debug de app.py las leen individualmente)
        _receta_c4 = _receta_glob   # se usa la receta del material principal para sub-desglose
        _disco_val  = next((r["valor"] for r in _receta_c4 if r["nombre_interno"] == "Desgaste disco"),        2_200.0)
        _maq_val    = next((r["valor"] for r in _receta_c4 if r["nombre_interno"] == "Uso máquina cortadora"), 20_000.0)
        _cons_val   = next((r["valor"] for r in _receta_c4 if r["nombre_interno"] == "Consumibles"),            8_500.0)
        _risk_val   = next((r["valor"] for r in _receta_c4 if r["nombre_interno"] == "Riesgo rotura"),          0.02)
        m2_disco         = m2_cortados if m2_cortados > 0 else m2_real
        costo_disco_maq  = (m2_disco * _disco_val) + (dias * _maq_val)
        costo_consumibles = m2_real * _cons_val
        costo_riesgo      = acumulados["c4_insumos"] - costo_disco_maq - costo_consumibles
        # costo_riesgo puede ser negativo si hay diferencias de redondeo entre recetas
        # de distintos materiales — lo clampamos a 0 para que el PDF no muestre negativo
        costo_riesgo = max(0.0, costo_riesgo)
        c4 = acumulados["c4_insumos"]

        # Si ninguna pieza tenía checkboxes de zócalo geométrico, aplicar modo legacy
        if zocalo_ml_calc == 0.0 and zocalo_activo and zocalo_ml > 0:
            zocalo_ml_calc = zocalo_ml
            _zoc_tarifa = next((r["valor"] for r in _receta_glob if r["inductor"] == "por_ml_zocalo"), 12_000.0)
            c3 = zocalo_ml_calc * _zoc_tarifa

    else:
        # ── FALLBACK GLOBAL — historial antiguo / cotización rápida ──────────
        ml_piezas   = 0.0
        m2_piezas   = 0.0
        ml_proyecto = kwargs.get("ml_proyecto", 0.0)

        if ml_proyecto > 0:
            ml_piezas = ml_proyecto
        elif _es_tipo_area:
            m2_piezas = m2_real
        else:
            ml_piezas = m2_real / 0.60

        _receta_fb = _resolver_receta(tar)
        _tarifa_ml_fb  = next((r["valor"] for r in _receta_fb if r["inductor"] == "por_ml"),        60_000.0)
        _tarifa_m2_fb  = next((r["valor"] for r in _receta_fb if r["inductor"] == "por_m2" and "área" in r.get("nombre_interno","").lower()), round(_tarifa_ml_fb * 0.55))
        c2_ml = ml_piezas * _tarifa_ml_fb
        c2_m2 = m2_piezas * _tarifa_m2_fb
        c2    = c2_ml + c2_m2

        # Zócalo modo legacy (ML total ingresado manualmente)
        zocalo_ml_calc = zocalo_ml if zocalo_activo else 0.0
        zocalo_m2_calc = 0.0
        _zoc_tarifa_fb = next((r["valor"] for r in _receta_fb if r["inductor"] == "por_ml_zocalo"), 12_000.0)
        c3 = zocalo_ml_calc * _zoc_tarifa_fb

        # Insumos globales (fallback)
        _disco_val_fb = next((r["valor"] for r in _receta_fb if r["nombre_interno"] == "Desgaste disco"),        2_200.0)
        _maq_val_fb   = next((r["valor"] for r in _receta_fb if r["nombre_interno"] == "Uso máquina cortadora"), 20_000.0)
        _cons_val_fb  = next((r["valor"] for r in _receta_fb if r["nombre_interno"] == "Consumibles"),            8_500.0)
        _risk_val_fb  = next((r["valor"] for r in _receta_fb if r["nombre_interno"] == "Riesgo rotura"),          0.02)
        m2_disco          = m2_cortados if m2_cortados > 0 else m2_real
        costo_disco_maq   = (m2_disco * _disco_val_fb) + (dias * _maq_val_fb)
        costo_consumibles = m2_real * _cons_val_fb
        costo_riesgo      = costo_material * _risk_val_fb
        c4 = costo_disco_maq + costo_consumibles + costo_riesgo

    # Exponer el ML real y los m² de material usados en zócalos (para PDF y UI)
    zocalo_ml_efectivo = zocalo_ml_calc
    zocalo_m2_efectivo = zocalo_m2_calc

    # ── Ajuste de costo de material por m² de zócalo (Corregido) ─────────────
    # El zócalo se corta de la misma placa comprada. NO se debe sumar un costo
    # de material adicional para no generar doble cobro al cliente.
    costo_extra_material_zocalo = 0.0
    costo_material_total = costo_material

    # ── ⑤ Logística con peso de carga y peajes exactos ──────────────────────
    # Calculamos el peso total para penalizar el rendimiento km/gal del vehículo
    _piezas_log = kwargs.get("piezas", [])
    peso_carga_kg = calcular_peso_proyecto(_piezas_log, categoria) if _piezas_log else 0.0
    log_dict = calcular_logistica(
        vehiculo=vehiculo_entrega, km=km, num_peajes=num_peajes,
        agente_externo=agente_externo_taller, personas=personas, categoria=categoria,
        logistica_override=kwargs.get("logistica_override"),
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
    # C-05 FIX: los precios unitarios deben calcularse sobre el precio FINAL
    # (con IVA incluido cuando aplica), no sobre el subtotal sin IVA.
    # De lo contrario, en el PDF:  X ml × precio_por_ml ≠ total de la factura.
    #
    # Régimen fiscal de Cotización Directa (Estatuto Tributario general):
    #   IVA 19% se aplica sobre el Subtotal completo (Costo + Utilidad).
    #   precio_final = precio_sugerido * 1.19  (si incluir_iva=True)
    #   precio_final = precio_sugerido         (si incluir_iva=False)
    #
    # Nota: incluir_iva llega vía **kwargs. Default True para no romper
    # llamadas legadas que no lo pasen explícitamente.
    _incluir_iva_cd = kwargs.get("incluir_iva", True)
    precio_final_cd = precio_sugerido * (1.19 if _incluir_iva_cd else 1.0)

    precio_por_ml = (precio_final_cd / ml_piezas) if ml_piezas > 0 else 0.0
    precio_por_m2 = (precio_final_cd / max(m2_real, 0.001))

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
        # Doble Estrategia de Precio
        "estrategia_precio":         estrategia_precio,
        "ganancia_oculta_retal":     ganancia_oculta_retal,
        "costo_material_placa_completa": costo_material_placa_completa,
        # Peso y merma
        "peso_carga_kg":     peso_carga_kg,
        "merma_info":        _merma_info,
        "merma_total_m2":    _merma_info["merma_total_m2"],
        # Logística predictiva: trazabilidad del vehículo y bloqueo por capacidad
        "vehiculo_entrega":       vehiculo_entrega,
        "log_bloqueo_capacidad":  log_dict.get("bloqueo_capacidad", False),
        "log_nota_bloqueo":       log_dict.get("nota_bloqueo", ""),
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
                 incluir_iva: bool = True,
                 logistica_override: dict = None,
                 viaticos_override: dict = None,
                 vehiculos_custom: dict = None,   # aceptado por compatibilidad, ignorado
                 costo_peaje_unitario: float = 0.0):
    """
    Cálculo AIU normativo colombiano.
    IVA (19%) solo sobre Utilidad (U) — Art. 3° Decreto 1372/92.

    incluir_iva=False: cotización exenta (régimen simplificado).
    En ese caso val_iva=0 y el total se ajusta dinámicamente.

    logistica_override / viaticos_override / vehiculos_custom:
        Permiten que el módulo AIU use las tarifas personalizadas que el
        Admin configuró en Parámetros, exactamente igual que Cotización Directa.
        Sin estos overrides, AIU ignoraba los cambios del usuario y cotizaba
        siempre con los valores hardcodeados de LOGISTICA/VIATICOS (C-03).
    """
    val_a   = cd * (pct_a / 100)
    val_i   = cd * (pct_i / 100)
    val_u   = cd * (pct_u / 100)
    # IVA solo sobre Utilidad (U) — Decreto 1372/92.
    # La Cotización Directa (venta comercial) aplica IVA sobre el subtotal total
    # bajo el régimen general del Estatuto Tributario. Esa lógica es exclusiva
    # de app.py (línea ~4138) y NO debe tocarse aquí.
    val_iva = val_u * 0.19 if incluir_iva else 0.0
    sub_aiu = val_a + val_i + val_u + val_iva

    # Pasar overrides para que AIU use las tarifas personalizadas del usuario
    log_dict = calcular_logistica(
        vehiculo=vehiculo, km=km, num_peajes=num_peajes,
        agente_externo=agente_externo,
        logistica_override=logistica_override,
        costo_peaje_unitario=costo_peaje_unitario,
    )
    logistica = log_dict["total"]
    viaticos  = calcular_viaticos(
        foraneo_activo, tipo_aloj, noches, personas,
        viaticos_override=viaticos_override,
    )
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
