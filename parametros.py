# parametros.py — Sistema de Cotización v4
# MARMOLES COLLANTE & CASTRO LTDA. · Feb 2026 · Barranquilla, Colombia

CATEGORIAS_MATERIAL = ["Mármol", "Granito", "Sinterizado", "Quarztone", "Quarzita"]

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
        "prod_ml":       60_000,  # COP/ml — lo que cobra el operario por cada ml cortado e instalado
        "prod_m2":       35_000,  # COP/m² — mano de obra en pisos/fachadas/revestimientos (menos cortes de borde)
        "zocalo":        12_000,  # COP/ml de zócalo instalado
        "disco":          2_200,  # COP/m² cortado (disco diamantado rinde ~90 m² en mármol)
        "maquina":       20_000,  # COP/día de uso de la cortadora
        "consumibles":    8_500,  # COP/m² — lijas, masilla de poliéster, ceras, sellador, estopa
        "riesgo_rotura":   0.02,  # 2% del costo del material (provisión de rotura)
    },
    "Granito": {
        "prod_ml":       55_000,
        "prod_m2":       32_000,  # Granito: menos cortes de borde en pisos/fachadas
        "zocalo":        14_000,
        "disco":          6_000,
        "maquina":       25_000,
        "consumibles":   10_000,  # Adhesivos más resistentes por dureza del granito
        "riesgo_rotura":   0.01,  # Granito es menos frágil que mármol
    },
    "Sinterizado": {
        "prod_ml":       85_000,
        "prod_m2":       52_000,  # Sinterizado: herramientas especiales, mayor cuidado en pisos grandes
        "zocalo":        20_000,
        "disco":         18_000,
        "maquina":       32_000,
        "consumibles":   25_000,  # Adhesivos especiales + herramientas específicas
        "riesgo_rotura":   0.08,  # Alta tensión superficial — mayor riesgo de rotura
    },
    "Quarztone": {
        "prod_ml":       65_000,
        "prod_m2":       38_000,  # Quarztone: cuarzo compactado, pisos sin cortes de perfil
        "zocalo":        16_000,
        "disco":          5_200,
        "maquina":       27_000,
        "consumibles":    9_000,
        "riesgo_rotura":   0.01,
    },
    "Quarzita": {
        "prod_ml":       70_000,
        "prod_m2":       42_000,  # Quarzita: mayor dureza → más desgaste en pisos, menos que en bordes
        "zocalo":        15_000,
        "disco":          8_000,
        "maquina":       28_000,
        "consumibles":   15_000,  # Mayor consumo de lijas por dureza
        "riesgo_rotura":   0.05,  # Dureza superior genera más riesgo de fractura en corte
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

VIATICOS = {
    # Desglose real por componente — suma = costo diario por persona
    "pueblo": {
        "hospedaje":         60_000,  # Alojamiento en pueblo/corregimiento
        "alimentacion":      65_000,  # Desayuno + almuerzo + cena
        "transporte_local":  20_000,  # Movilidad local (moto, taxi, buseta)
    },
    "ciudad": {
        "hospedaje":         90_000,  # Hotel o posada en ciudad capital
        "alimentacion":      68_000,  # Comidas en ciudad (ligeramente más caro)
        "transporte_local":  20_000,  # Transporte urbano
    },
}

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
    "Quarzita":    ("#fce8ea", "#8a1a1a"),
}

DESCRIPCIONES_CATEGORIA = {
    "Mármol":      "Piedra natural clásica. Alta demanda en cocinas y baños.",
    "Granito":     "Muy resistente. Ideal para cocinas y exteriores.",
    "Sinterizado": "Material técnico de última generación. Alta resistencia.",
    "Quarztone":   "Cuarzo compactado. Consistencia de color perfecta.",
    "Quarzita":    "Piedra natural de dureza superior al mármol.",
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

# ── TOUR GUIADO — pasos del onboarding (actualizados v5) ─────────────────────
TOUR_PASOS = [
    {
        "id":       "bienvenida",
        "etiqueta": "MARMOLES COLLANTE & CASTRO",
        "icono":    "⚡",
        "titulo":   "Sistema de Cotizacion Profesional",
        "cuerpo":   "Bienvenido. Esta herramienta es de uso exclusivo de MARMOLES COLLANTE & CASTRO LTDA. y te permite calcular el costo real de cualquier proyecto en piedra natural o sinterizado y generar cotizaciones PDF listas para enviar al cliente.\n\nEl recorrido guiado cubre las funciones clave en menos de 2 minutos.",
        "pagina":   None,
    },
    {
        "id":       "cotizacion_directa",
        "etiqueta": "COTIZADOR",
        "icono":    "📐",
        "titulo":   "Cotizacion Directa — el corazon de la app",
        "cuerpo":   "Define el material, agrega las piezas del proyecto, configura logistica y presiona Calcular. Obtienes de inmediato el precio sugerido, el desglose completo de costos y el margen de utilidad.\n\nEl cotizador guarda automaticamente cada calculo en el Historial para que puedas rastrearlo y editarlo cuando necesites.",
        "pagina":   "Cotizacion Directa",
    },
    {
        "id":       "cobro_dual",
        "etiqueta": "ML vs m2",
        "icono":    "📏",
        "titulo":   "Logica dual de cobro: ML y m2",
        "cuerpo":   "En marmoleria se trabaja en dos unidades segun el tipo de pieza. Las piezas de mesones, encimeras y baños se cobran en Metros Lineales (ML): el cliente paga por largo de pieza. Los pisos y revestimientos grandes se cobran en m2.\n\nLa app maneja las dos unidades en el mismo proyecto: cada pieza tiene su unidad de venta y el motor de calculo convierte todo a m2 internamente para costear el material.",
        "pagina":   "Cotizacion Directa",
    },
    {
        "id":       "retal",
        "etiqueta": "SOBRANTES",
        "icono":    "♻️",
        "titulo":   "Gestor visual de desperdicio (Retal)",
        "cuerpo":   "Cuando apruebas una cotizacion, el sistema calcula automaticamente el retal (material sobrante de la lamina) y lo registra en el Banco de Retales. La proxima vez que cotices el mismo material, la app te avisara que tienes sobrante disponible.\n\nUsar un retal puede eliminar por completo el costo de material y elevar tu margen al 80% o mas. En el Dashboard veras el Capital Inmovilizado Recuperable: el valor total de tus sobrantes al precio de mercado.",
        "pagina":   "Banco de Retales",
    },
    {
        "id":       "produccion",
        "etiqueta": "PRODUCCION",
        "icono":    "👷",
        "titulo":   "Costo de produccion — pago por ML",
        "cuerpo":   "La mano de obra en marmoleria se paga por metro lineal cortado e instalado, no por hora. Si el operario cobra $60.000/ml y el proyecto tiene 5 ML, el costo de produccion es $300.000.\n\nEste valor lo personalizas en Parametros > Tarifas y Produccion segun lo que paga tu empresa en Barranquilla.",
        "pagina":   "Parametros",
    },
    {
        "id":       "dashboard",
        "etiqueta": "ANALYTICS",
        "icono":    "📊",
        "titulo":   "Dashboard e Historial",
        "cuerpo":   "El Historial guarda cada cotizacion con su estado (Pendiente / Aprobada / Rechazada). Puedes buscar por cliente o material y editar cualquier cotizacion anterior.\n\nEl Dashboard muestra los materiales mas rentables, la facturacion mensual y el margen promedio para que tomes decisiones con datos reales.",
        "pagina":   "Dashboard",
    },
    {
        "id":       "pdf",
        "etiqueta": "DOCUMENTOS",
        "icono":    "📄",
        "titulo":   "PDF de cotizacion y cuenta de cobro",
        "cuerpo":   "Al finalizar un calculo puedes exportar dos documentos profesionales listos para enviar al cliente: la cotizacion con el desglose de la oferta y la cuenta de cobro con los datos bancarios y la firma.\n\nConfigura el logo y la informacion de la empresa en Configuracion > Identidad Visual para que aparezcan en todos los PDFs.",
        "pagina":   "Cotizacion Directa",
    },
    {
        "id":       "sos",
        "etiqueta": "AYUDA",
        "icono":    "🆘",
        "titulo":   "Boton SOS — ayuda en tiempo real",
        "cuerpo":   "Si en algun momento te sientes atascado o no entiendes un termino, abre el panel SOS en el menu lateral: encuentra el expander que dice Necesitas ayuda rapida y escribe tu duda.\n\nLa IA te respondera en segundos con una explicacion concisa adaptada a la pantalla en la que te encuentras — sin salir del cotizador ni perder lo que llevas escrito.",
        "pagina":   None,
    },
    {
        "id":       "fin",
        "etiqueta": "LISTO",
        "icono":    "🚀",
        "titulo":   "Ya estas listo para cotizar",
        "cuerpo":   "Conoces las funciones clave. Recuerda: el boton SOS del menu lateral esta disponible en cualquier momento para resolver dudas. Los parametros de costos son editables y los cambios aplican de inmediato.\n\nPuedes volver a este recorrido desde la pantalla de Inicio cuando quieras.",
        "pagina":   None,
    },
]
