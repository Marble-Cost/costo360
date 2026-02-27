# parametros.py — Sistema de Cotización v4
# MARMOLES COLLANTE & CASTRO LTDA. · Feb 2026 · Barranquilla, Colombia

CATEGORIAS_MATERIAL = ["Mármol", "Granito", "Sinterizado", "Quarztone", "Cuarcita"]

# ── TARIFAS DE PRODUCCIÓN ────────────────────────────────────────────────────
# En Colombia la mano de obra en marmolería se paga POR METRO LINEAL (ml),
# no por hora ni por m². El operario cobra según lo que corta e instala.
#
# Estructura de cada tarifa:
#   prod_ml:  COP por metro lineal — lo que le pagas al operario por cada ml
#             cortado e instalado. Este es el valor principal de producción.
#   zocalo:   COP por ml de zócalo instalado (trabajo diferente, tarifa diferente)
#   disco:    COP por m² cortado (costo del disco diamantado consumido)
#   maquina:  COP por día de uso de la cortadora (depreciación + mantenimiento)
#
# NOTA: prod_ml incluye corte + elaboración + instalación del metro lineal.
# Para calcular el costo de producción total: ml_totales × prod_ml

TARIFAS = {
    "Mármol": {
        "prod_ml":  60_000,   # COP/ml — lo que cobra el operario por cada ml cortado e instalado
        "zocalo":   12_000,   # COP/ml de zócalo instalado
        "disco":     2_200,   # COP/m² cortado (disco diamantado rinde ~90 m² en mármol)
        "maquina":  20_000,   # COP/día de uso de la cortadora
    },
    "Granito": {
        "prod_ml":  55_000,
        "zocalo":   14_000,
        "disco":     6_000,
        "maquina":  25_000,
    },
    "Sinterizado": {
        "prod_ml":  85_000,
        "zocalo":   20_000,
        "disco":    18_000,
        "maquina":  32_000,
    },
    "Quarztone": {
        "prod_ml":  65_000,
        "zocalo":   16_000,
        "disco":     5_200,
        "maquina":  27_000,
    },
    "Cuarcita": {
        "prod_ml":  70_000,
        "zocalo":   15_000,
        "disco":     8_000,
        "maquina":  28_000,
    },
}

LOGISTICA = {
    # Gasolina corriente Feb 2026 Barranquilla: ~$16.000/galón
    "gasolina": 16_000,

    # Vehículos propios: rend en km/galón (con carga), desgaste COP/km, base=mínimo por viaje
    "frontier": {"rend": 7.2,  "desgaste": 148, "base": 65_000},
    "cheyenne": {"rend": 4.1,  "desgaste": 340, "base": 85_000},

    # Externo/Tercero: flete fijo. No se calcula km propio.
    "externo":  {"flete": 165_000},

    # Flete agente externo (proveedor → taller)
    "agente":   85_000,

    # Peaje promedio zona Atlántico (Galapa/Juan Mina ida+vuelta)
    "peaje":    19_500,

    # Desgaste herramientas por viaje (llaves, niveles, espátulas, etc.)
    "herram":   4_500,
}

VIATICOS = {"pueblo": 145_000, "ciudad": 178_000}

ADICIONALES = [
    {"concepto": "Fregadero instalación bajo cubierta", "unidad": "und",   "terminada": 35_000, "acabados": 42_000, "estructura": 50_000, "comercial": 55_000},
    {"concepto": "Sellante y silicona especializada",   "unidad": "und",   "terminada": 28_000, "acabados": 32_000, "estructura": 38_000, "comercial": 40_000},
    {"concepto": "Impermeabilizante bajo ducha",        "unidad": "und",   "terminada": 35_000, "acabados": 45_000, "estructura": 60_000, "comercial": 65_000},
    {"concepto": "Adhesivo sustrato irregular",         "unidad": "und",   "terminada": 25_000, "acabados": 35_000, "estructura": 45_000, "comercial": 50_000},
    {"concepto": "Soporte / anclaje metálico",          "unidad": "ml",    "terminada": 18_000, "acabados": 22_000, "estructura": 28_000, "comercial": 32_000},
    {"concepto": "Acceso elevación (pisos altos)",      "unidad": "viaje", "terminada":      0, "acabados": 80_000, "estructura":100_000, "comercial":120_000},
    {"concepto": "Limpieza de mortero / residuos",      "unidad": "viaje", "terminada": 50_000, "acabados": 60_000, "estructura": 70_000, "comercial": 80_000},
    {"concepto": "Reserva riesgo daño otros gremios",   "unidad": "glb",   "terminada": 50_000, "acabados": 65_000, "estructura": 80_000, "comercial": 90_000},
]

AIU_DEFAULTS = {"a": 2.0, "i": 2.0, "u": 5.0}

ETAPAS_OBRA = {
    "Casa terminada (limpia)": "terminada",
    "En acabados":             "acabados",
    "En estructura":           "estructura",
    "Proyecto comercial":      "comercial",
}

VEHICULOS = {
    "Frontier NP300 (camioneta)": "frontier",
    "Cheyenne V8 (camión)":       "cheyenne",
    "Externo / Tercero":          "externo",
}

# Configuración detallada de vehículos propios (editable en Parámetros)
VEHICULOS_CONFIG = {
    "frontier": {
        "nombre": "Frontier NP300",
        "tipo": "propio",
        "rend": 7.2,
        "desgaste": 148,
        "base": 65_000,
        "descripcion": "Camioneta pickup — carga media, ideal transporte losa",
    },
    "cheyenne": {
        "nombre": "Cheyenne V8",
        "tipo": "propio",
        "rend": 4.1,
        "desgaste": 340,
        "base": 85_000,
        "descripcion": "Camión grande — carga pesada, varios proyectos",
    },
    "externo": {
        "nombre": "Externo / Tercero",
        "tipo": "externo",
        "flete": 165_000,
        "descripcion": "Flete contratado — precio fijo por viaje",
    },
}

ALOJAMIENTO = {"Pueblo / Corregimiento": "pueblo", "Ciudad Capital": "ciudad"}

BADGE_COLORS = {
    "Mármol":      ("#e8f0f8", "#1a4a8a"),
    "Granito":     ("#e4f0e8", "#1a5a2a"),
    "Sinterizado": ("#ede8f8", "#4a1a8a"),
    "Quarztone":   ("#f8f0e4", "#7a4a1a"),
    "Cuarcita":    ("#fce8ea", "#8a1a1a"),
}

DESCRIPCIONES_CATEGORIA = {
    "Mármol":      "Piedra natural clásica. Alta demanda en cocinas y baños.",
    "Granito":     "Muy resistente. Ideal para cocinas y exteriores.",
    "Sinterizado": "Material técnico de última generación. Alta resistencia.",
    "Quarztone":   "Cuarzo compactado. Consistencia de color perfecta.",
    "Cuarcita":    "Piedra natural de dureza superior al mármol.",
}

ANCHOS_ESTANDAR = {
    "Mesón de cocina":       {"ancho": 0.60, "unidad": "m", "desc": "Ancho estándar mesón"},
    "Isla de cocina":        {"ancho": 1.00, "unidad": "m", "desc": "Ancho estándar isla"},
    "Encimera":              {"ancho": 0.60, "unidad": "m", "desc": "Igual que mesón"},
    "Salpicadero / Frente":  {"ancho": 0.60, "unidad": "m", "desc": "Altura backsplash estándar"},
    "Baño / Lavamanos":      {"ancho": 0.45, "unidad": "m", "desc": "Profundidad estándar baño"},
    "Mueble de baño":        {"ancho": 0.50, "unidad": "m", "desc": "Profundidad mueble baño"},
    "Zócalo":                {"ancho": 0.10, "unidad": "m", "desc": "Alto estándar zócalo 10cm"},
    "Huella escalón":        {"ancho": 0.30, "unidad": "m", "desc": "Profundidad huella escalera"},
    "Escalón completo":      {"ancho": 0.90, "unidad": "m", "desc": "Ancho escalera estándar"},
    "Fachada / Panel":       {"ancho": 1.00, "unidad": "m", "desc": "Módulos de 1m de ancho"},
    "Personalizado":         {"ancho": None, "unidad": "m", "desc": "Ingresa el ancho manualmente"},
}

MATERIALES_CATALOGO = [
    {"nombre": "Crema Marfil Clásico",  "categoria": "Mármol",      "precio_m2": 220_000, "area_placa": 5.94},
    {"nombre": "New Cremo Sicilia",     "categoria": "Mármol",      "precio_m2": 240_000, "area_placa": 2.212},
    {"nombre": "Ducal Gold 1200×2800",  "categoria": "Sinterizado", "precio_m2":  88_000, "area_placa": 3.36},
    {"nombre": "Blanco Polar",          "categoria": "Quarztone",   "precio_m2": 169_000, "area_placa": 5.168},
    {"nombre": "Alpine Premium",        "categoria": "Granito",     "precio_m2": 475_000, "area_placa": 5.12},
    {"nombre": "Calacatta Dorato",      "categoria": "Sinterizado", "precio_m2": 580_000, "area_placa": 5.12},
]

# ── TOUR GUIADO — pasos del onboarding ──────────────────────────────────────
TOUR_PASOS = [
    {
        "id": "bienvenida",
        "titulo": "Sistema de Cotización Profesional",
        "cuerpo": "Esta herramienta es de uso exclusivo de MARMOLES COLLANTE & CASTRO LTDA. y te ayuda a calcular el costo real de cualquier proyecto de mármol, granito o sinterizado, y a generar cotizaciones y cuentas de cobro profesionales en segundos.\n\nEl recorrido guiado toma menos de 3 minutos y cubre todo lo que necesitas saber.",
        "icono": "C",
        "pagina": None,
    },
    {
        "id": "cotizacion_directa",
        "titulo": "Cotización Directa — el corazón de la app",
        "cuerpo": "Aquí calculas el precio real de un proyecto paso a paso:\n\n1. Selecciona el material y el precio por m² que te cobró el proveedor\n2. Agrega las piezas del proyecto en metros lineales (ML)\n3. Define logística y transporte\n4. Presiona 'Calcular' y obtienes precio sugerido, desglose completo y margen de utilidad",
        "icono": "1",
        "pagina": "Cotizacion Directa",
    },
    {
        "id": "medidas_ml",
        "titulo": "Por qué se trabaja en metros lineales (ML)",
        "cuerpo": "En marmolería se habla en ML, no en m². Por eso la app usa ML como unidad principal.\n\nEjemplo: un mesón de 3 ML de largo × 0.60 m de ancho = 1.80 m² de material.\n\nLa app hace esa conversión automáticamente. Solo ingresas el largo de cada pieza.",
        "icono": "2",
        "pagina": "Cotizacion Directa",
    },
    {
        "id": "produccion",
        "titulo": "Costo de producción — cómo se calcula",
        "cuerpo": "La producción se paga por metro lineal (ML) cortado e instalado, no por hora.\n\nEjemplo: si el operario cobra $60.000/ml y el proyecto tiene 5 ML, el costo de producción es $300.000.\n\nEste valor lo configuras en Parámetros > Costos de producción.",
        "icono": "3",
        "pagina": "Parametros",
    },
    {
        "id": "parametros",
        "titulo": "Parámetros — personaliza todos los costos",
        "cuerpo": "Todos los valores de la app son editables: tarifas de producción por material, logística, vehículos y viáticos.\n\nPuedes cambiarlos manualmente o pedirle a la IA que te ayude a calcularlos según tu operación real.\n\nLos cambios aplican inmediatamente a todos los cálculos.",
        "icono": "4",
        "pagina": "Parametros",
    },
    {
        "id": "historial_dashboard",
        "titulo": "Historial y Dashboard",
        "cuerpo": "Cada cotización que calculas se guarda automáticamente en tu historial.\n\nPuedes buscar por cliente, cambiar el estado (Pendiente / Aprobada / Rechazada) y ver métricas de tu negocio en el Dashboard: materiales más rentables, facturación mensual y margen promedio.",
        "icono": "5",
        "pagina": "Historial",
    },
    {
        "id": "pdf",
        "titulo": "Documentos PDF profesionales",
        "cuerpo": "Al terminar una cotización puedes generar:\n\n- PDF de cotización con desglose de costos\n- Cuenta de cobro lista para enviar\n\nAmbos documentos usan el logo y colores de tu empresa si los configuras en la sección Configuración.",
        "icono": "6",
        "pagina": "Cotizacion Directa",
    },
    {
        "id": "fin",
        "titulo": "Listo para empezar",
        "cuerpo": "Ya conoces las funciones principales. Recuerda:\n\n- Si tienes dudas, el Asistente IA siempre está disponible\n- Puedes editar todos los parámetros en cualquier momento\n- Las cotizaciones se guardan automáticamente\n\nPuedes volver a este recorrido en cualquier momento desde el menú lateral.",
        "icono": "C",
        "pagina": None,
    },
]
