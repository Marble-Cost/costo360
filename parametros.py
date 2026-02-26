# parametros.py — CostoMármol v2
# Materiales agrupados por CATEGORÍA, no por nombre de placa.

CATEGORIAS_MATERIAL = ["Mármol", "Granito", "Sinterizado", "Quarztone", "Cuarcita"]

TARIFAS = {
    "Mármol":      {"corte": 25_000, "elab": 75_000, "zocalo": 12_000, "disco":  2_200, "desgaste": 20_000},
    "Granito":     {"corte": 28_000, "elab": 48_000, "zocalo": 14_000, "disco":  6_000, "desgaste": 25_000},
    "Sinterizado": {"corte": 45_000, "elab": 70_000, "zocalo": 20_000, "disco": 18_000, "desgaste": 32_000},
    "Quarztone":   {"corte": 32_000, "elab": 55_000, "zocalo": 16_000, "disco":  5_200, "desgaste": 27_000},
    "Cuarcita":    {"corte": 35_000, "elab": 65_000, "zocalo": 15_000, "disco":  8_000, "desgaste": 28_000},
}

LOGISTICA = {
    "gasolina": 15_800,
    "frontier": {"rend": 7.2,  "desgaste": 148, "base": 65_000},
    "cheyenne":  {"rend": 4.1,  "desgaste": 340, "base": 85_000},
    "externo":   {"flete": 165_000},
    "agente":    85_000,
    "peaje":     19_500,
    "herram":     4_500,
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
    "Externo / Tercero":           "externo",
}

ALOJAMIENTO = {"Pueblo / Corregimiento": "pueblo", "Ciudad Capital": "ciudad"}

ICONOS = {"Mármol": "🤍", "Granito": "🪨", "Sinterizado": "⬜", "Quarztone": "💎", "Cuarcita": "🔷"}

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

# Materiales de referencia en catálogo (ahora opcionales — el usuario puede ingresar cualquier referencia)
MATERIALES_CATALOGO = [
    {"nombre": "Crema Marfil Clásico",  "categoria": "Mármol",      "precio_m2": 220_000, "area_placa": 5.94},
    {"nombre": "New Cremo Sicilia",     "categoria": "Mármol",      "precio_m2": 240_000, "area_placa": 2.212},
    {"nombre": "Ducal Gold 1200×2800",  "categoria": "Sinterizado", "precio_m2": 88_000,  "area_placa": 3.36},
    {"nombre": "Blanco Polar",          "categoria": "Quarztone",   "precio_m2": 169_000, "area_placa": 5.168},
    {"nombre": "Alpine Premium",        "categoria": "Granito",     "precio_m2": 475_000, "area_placa": 5.12},
    {"nombre": "Calacatta Dorato",      "categoria": "Sinterizado", "precio_m2": 580_000, "area_placa": 5.12},
]
