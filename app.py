# app.py — CostoMármol v4 · Premium Dark Edition

import io
import base64
import streamlit as st
import psycopg2
import json, os
from datetime import date, datetime
from calculos import (
    calcular_cotizacion_directa, analizar_precio_real,
    calcular_aiu, calcular_logistica, ml_a_m2, cop,
)
from parametros import (
    CATEGORIAS_MATERIAL, ADICIONALES, ETAPAS_OBRA, VEHICULOS,
    ALOJAMIENTO, AIU_DEFAULTS, TARIFAS, LOGISTICA, VIATICOS,
    BADGE_COLORS, DESCRIPCIONES_CATEGORIA, MATERIALES_CATALOGO,
    ANCHOS_ESTANDAR, VEHICULOS_CONFIG, TOUR_PASOS,
)
from asistente_ia import chat_con_ia, ia_disponible, interpretar_proyecto, generar_resumen_cotizacion

# ── BASE DE DATOS POSTGRESQL (SUPABASE) ───────────────────────────────────────
def _get_db_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def _init_db():
    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cotizaciones (
            id SERIAL PRIMARY KEY,
            numero TEXT, fecha TEXT, cliente TEXT, material TEXT,
            tipo TEXT, m2 REAL, ml REAL, costo REAL, precio REAL,
            margen REAL, estado TEXT DEFAULT 'Pendiente', datos_json TEXT
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

def _guardar_cotizacion(numero, cliente, resultado):
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO cotizaciones (numero,fecha,cliente,material,tipo,m2,ml,costo,precio,margen,estado,datos_json) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (numero, date.today().isoformat(), cliente or "Sin nombre",
         resultado.get("categoria",""), resultado.get("tipo_proyecto",""),
         resultado.get("m2_real",0), resultado.get("ml_proyecto",0),
         resultado.get("costo_total",0), resultado.get("precio_sugerido",0),
         resultado.get("margen_pct",0), "Pendiente",
         json.dumps(resultado, ensure_ascii=False, default=str))
    )
    conn.commit()
    cur.close()
    conn.close()

def _listar_cotizaciones(busqueda=""):
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
    q = "SELECT id,numero,fecha,cliente,material,ml,precio,margen,estado FROM cotizaciones WHERE cliente ILIKE %s OR numero ILIKE %s OR material ILIKE %s ORDER BY id DESC LIMIT 200" if busqueda else "SELECT id,numero,fecha,cliente,material,ml,precio,margen,estado FROM cotizaciones ORDER BY id DESC LIMIT 200"
    cur.execute(q, (f"%{busqueda}%",)*3 if busqueda else ())
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def _actualizar_estado(cot_id, nuevo_estado):
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE cotizaciones SET estado=%s WHERE id=%s", (nuevo_estado, cot_id))
    conn.commit()
    cur.close()
    conn.close()

def _stats_db():
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
    s = {}
    cur.execute("SELECT COUNT(*) FROM cotizaciones")
    s["total"]      = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM cotizaciones WHERE estado='Aprobada'")
    s["aprobadas"]  = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM cotizaciones WHERE estado='Pendiente'")
    s["pendientes"] = cur.fetchone()[0]
    cur.execute("SELECT SUM(precio) FROM cotizaciones WHERE estado='Aprobada'")
    s["facturacion"]= cur.fetchone()[0] or 0
    cur.execute("SELECT AVG(margen) FROM cotizaciones WHERE estado='Aprobada'")
    s["margen_prom"]= cur.fetchone()[0] or 0
    cur.execute("SELECT material,COUNT(*),AVG(margen),SUM(precio) FROM cotizaciones WHERE estado='Aprobada' GROUP BY material")
    s["por_material"]= cur.fetchall()
    cur.execute("SELECT SUBSTR(fecha,1,7),COUNT(*),SUM(precio) FROM cotizaciones GROUP BY SUBSTR(fecha,1,7) ORDER BY SUBSTR(fecha,1,7) DESC LIMIT 6")
    s["por_mes"]    = cur.fetchall()
    cur.close()
    conn.close()
    return s

# ── Asistente de parámetros (system prompt SEPARADO del asistente general) ──
def _chat_parametros(historial: list, mensaje: str) -> str:
    """Chat con IA dedicado EXCLUSIVAMENTE a actualizar parametros de costos.
    NO usa el system prompt del asistente general."""
    try:
        import anthropic
        api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return "Configura tu API key en .streamlit/secrets.toml para usar esta funcion."
        client = anthropic.Anthropic(api_key=api_key)
        SYSTEM_PARAMS = """Eres un asistente experto en costos de marmolería en Colombia (Barranquilla, 2026).
Tu ÚNICO objetivo es ayudar al usuario a determinar los valores correctos para los parámetros de su calculadora de costos.

Parámetros que puedes actualizar:
- Gasolina: precio actual por galón en Barranquilla
- Frontier NP300: rendimiento km/galón y costo de desgaste por km
- Cheyenne V8: rendimiento km/galón y costo de desgaste por km
- Flete externo/tercero: tarifa fija por viaje
- Flete agente externo (proveedor→taller): tarifa fija
- Peaje ida+vuelta: valor actual
- Viáticos pueblo: tarifa por noche por persona
- Viáticos ciudad: tarifa por noche por persona
- Costos de produccion por material: prod_ml (COP/ml), zocalo, disco, maquina

REGLAS ESTRICTAS:
1. Haz UNA sola pregunta a la vez
2. Cuando el usuario responda un valor, confírmalo y pasa al siguiente
3. Usa formato colombiano: $16.000/galón, $148/km, etc.
4. Si el usuario no sabe un valor, sugiere el más común en Barranquilla hoy
5. NO saludes, NO expliques qué es cotización, NO preguntes sobre proyectos
6. Cuando termines un grupo de parámetros, muestra un resumen claro de los valores recopilados
7. Respuestas máximo 3 líneas — directo y específico"""
        messages = [{"role": m["role"], "content": m["content"]} for m in historial]
        messages.append({"role": "user", "content": mensaje})
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=400,
            system=SYSTEM_PARAMS,
            messages=messages,
        )
        return response.content[0].text
    except Exception as e:
        return f"Error: {str(e)}"


st.set_page_config(
    page_title="CostoMármol — Mármoles Collante & Castro",
    page_icon="assets/logo_cc.jpeg" if False else "C",
    layout="wide",
    initial_sidebar_state="expanded",
)

_dm = st.session_state.get("dark_mode", False)

# Colores adaptativos
if _dm:
    _bg_main    = "#0D1117"
    _bg_card    = "#161B22"
    _bg_sidebar = "#0D2137"
    _border     = "rgba(255,255,255,0.1)"
    _text_main  = "#E6EDF3"
    _text_sub   = "#8B949E"
    _input_bg   = "#0D1117"
    _input_border = "rgba(255,255,255,0.15)"
    _tab_bg     = "#161B22"
    _tab_active = "#1B5FA8"
    _metric_bg  = "#161B22"
    _expander_bg= "#161B22"
else:
    _bg_main    = "#EEF5FD"
    _bg_card    = "#FFFFFF"
    _bg_sidebar = "#0D2137"
    _border     = "#D6E8FA"
    _text_main  = "#0D2137"
    _text_sub   = "#6B85A0"
    _input_bg   = "#FFFFFF"
    _input_border = "#D6E8FA"
    _tab_bg     = "#FFFFFF"
    _tab_active = "#0D2137"
    _metric_bg  = "#FFFFFF"
    _expander_bg= "#FFFFFF"

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=DM+Sans:wght@300;400;500;600;700&display=swap');

* {{ box-sizing: border-box; }}
html, body, [class*="css"] {{ font-family: 'DM Sans', sans-serif; }}

/* ── SIDEBAR ── */
section[data-testid="stSidebar"] > div {{
    background: {_bg_sidebar} !important;
    border-right: 1px solid rgba(255,255,255,0.06) !important;
}}
section[data-testid="stSidebar"] * {{ color: rgba(255,255,255,0.85) !important; }}
section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3 {{
    color: white !important; font-family: 'Playfair Display', serif !important;
}}
section[data-testid="stSidebar"] .stRadio label {{
    color: rgba(255,255,255,0.8) !important; font-size: 0.88rem !important;
    font-weight: 500 !important; letter-spacing: 0.01em !important;
}}

/* ── MAIN BACKGROUND ── */
.main .block-container {{
    background: {_bg_main} !important;
    padding-top: 1.5rem !important; max-width: 1200px !important;
}}
.main {{ background: {_bg_main} !important; }}
[data-testid="stAppViewContainer"] > .main {{ background: {_bg_main} !important; }}

/* ── BUTTONS ── */
.stButton > button {{
    border-radius: 6px !important; font-weight: 600 !important;
    font-size: 0.85rem !important; letter-spacing: 0.03em !important;
    border: 1.5px solid {_border} !important;
    color: {_text_main} !important; background: {_bg_card} !important;
    transition: all 0.18s ease !important; padding: 0.45rem 1rem !important;
}}
.stButton > button:hover {{
    border-color: #1B5FA8 !important; color: #1B5FA8 !important;
    background: {_bg_main} !important; transform: translateY(-1px) !important;
    box-shadow: 0 3px 10px rgba(27,95,168,0.15) !important;
}}
.stButton > button[kind="primary"] {{
    background: linear-gradient(135deg, #0D2137 0%, #1B5FA8 100%) !important;
    color: white !important; border: none !important;
    box-shadow: 0 4px 16px rgba(27,95,168,0.38) !important;
    letter-spacing: 0.05em !important; text-transform: uppercase !important;
    font-size: 0.78rem !important; padding: 0.6rem 1.4rem !important;
}}
.stButton > button[kind="primary"]:hover {{
    background: linear-gradient(135deg, #1B5FA8 0%, #2E6DB4 100%) !important;
    box-shadow: 0 6px 22px rgba(27,95,168,0.48) !important;
    color: white !important; transform: translateY(-2px) !important;
}}

/* ── INPUTS ── */
.stNumberInput label, .stTextInput label, .stSelectbox label,
.stSlider label, .stCheckbox label, .stTextArea label, .stRadio label {{
    color: {_text_main} !important; font-weight: 600 !important;
    font-size: 0.82rem !important; letter-spacing: 0.04em !important;
    text-transform: uppercase !important;
}}
.stNumberInput input, .stTextInput input, .stTextArea textarea {{
    border: 1.5px solid {_input_border} !important; border-radius: 6px !important;
    font-size: 0.92rem !important; color: {_text_main} !important;
    background: {_input_bg} !important;
}}
.stNumberInput input:focus, .stTextInput input:focus, .stTextArea textarea:focus {{
    border-color: #1B5FA8 !important; box-shadow: 0 0 0 3px rgba(27,95,168,0.1) !important;
}}
.stSelectbox > div > div {{
    border: 1.5px solid {_input_border} !important; border-radius: 6px !important;
    background: {_input_bg} !important; color: {_text_main} !important;
}}

/* ── METRICS ── */
[data-testid="stMetric"] {{
    background: {_metric_bg} !important; border: 1px solid {_border} !important;
    border-radius: 10px !important; padding: 16px 18px !important;
}}
[data-testid="stMetricLabel"] p {{
    color: {_text_sub} !important; font-size: 0.68rem !important;
    font-weight: 700 !important; text-transform: uppercase !important; letter-spacing: 0.08em !important;
}}
[data-testid="stMetricValue"] {{ color: {_text_main} !important; font-weight: 800 !important; font-size: 1.2rem !important; }}

/* ── TABS ── */
.stTabs [data-baseweb="tab-list"] {{
    background: transparent !important; gap: 4px !important;
    border-bottom: 2px solid {_border} !important; padding-bottom: 0 !important;
}}
.stTabs [data-baseweb="tab"] {{
    background: {_tab_bg} !important; border-radius: 8px 8px 0 0 !important;
    font-weight: 600 !important; font-size: 0.82rem !important;
    color: {_text_sub} !important; padding: 10px 20px !important;
    border: 1px solid {_border} !important; border-bottom: none !important;
    letter-spacing: 0.04em !important; text-transform: uppercase !important;
}}
.stTabs [aria-selected="true"] {{
    background: {_tab_active} !important; color: white !important; border-color: {_tab_active} !important;
}}

/* ── EXPANDER ── */
.streamlit-expanderHeader {{
    background: {_expander_bg} !important; border-radius: 8px !important;
    font-weight: 600 !important; color: {_text_main} !important;
    border: 1.5px solid {_border} !important; font-size: 0.85rem !important;
}}
.streamlit-expanderContent {{
    border: 1.5px solid {_border} !important; border-top: none !important;
    border-radius: 0 0 8px 8px !important; background: {_bg_card} !important;
}}

/* ── DARK MODE general text ── */
p, span, div, label {{ color: {_text_main}; }}
hr {{ border-color: {_border} !important; }}
.stSuccess {{ border-radius: 8px !important; }}
.stWarning {{ border-radius: 8px !important; }}
.stError   {{ border-radius: 8px !important; }}
[data-testid="stFileUploader"] {{
    border: 1.5px dashed {_border} !important; border-radius: 10px !important;
    background: {_bg_card} !important;
}}
</style>
""", unsafe_allow_html=True)
# Original file header:
# CostoMármol v4 · Premium Dark Edition
# Mármoles Collante & Castro Ltda. · Feb 2026

import io
import base64
import streamlit as st
import psycopg2
import json, os
from datetime import date, datetime
from calculos import (
    calcular_cotizacion_directa, analizar_precio_real,
    calcular_aiu, calcular_logistica, ml_a_m2, cop,
)
from parametros import (
    CATEGORIAS_MATERIAL, ADICIONALES, ETAPAS_OBRA, VEHICULOS,
    ALOJAMIENTO, AIU_DEFAULTS, TARIFAS, LOGISTICA, VIATICOS,
    BADGE_COLORS, DESCRIPCIONES_CATEGORIA, MATERIALES_CATALOGO,
    ANCHOS_ESTANDAR, VEHICULOS_CONFIG, TOUR_PASOS,
)
from asistente_ia import chat_con_ia, ia_disponible, interpretar_proyecto, generar_resumen_cotizacion

# ── BASE DE DATOS POSTGRESQL (SUPABASE) ───────────────────────────────────────
def _get_db_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def _init_db():
    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cotizaciones (
            id SERIAL PRIMARY KEY,
            numero TEXT, fecha TEXT, cliente TEXT, material TEXT,
            tipo TEXT, m2 REAL, ml REAL, costo REAL, precio REAL,
            margen REAL, estado TEXT DEFAULT 'Pendiente', datos_json TEXT
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

def _guardar_cotizacion(numero, cliente, resultado):
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO cotizaciones (numero,fecha,cliente,material,tipo,m2,ml,costo,precio,margen,estado,datos_json) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (numero, date.today().isoformat(), cliente or "Sin nombre",
         resultado.get("categoria",""), resultado.get("tipo_proyecto",""),
         resultado.get("m2_real",0), resultado.get("ml_proyecto",0),
         resultado.get("costo_total",0), resultado.get("precio_sugerido",0),
         resultado.get("margen_pct",0), "Pendiente",
         json.dumps(resultado, ensure_ascii=False, default=str))
    )
    conn.commit()
    cur.close()
    conn.close()

def _listar_cotizaciones(busqueda=""):
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
    q = "SELECT id,numero,fecha,cliente,material,ml,precio,margen,estado FROM cotizaciones WHERE cliente ILIKE %s OR numero ILIKE %s OR material ILIKE %s ORDER BY id DESC LIMIT 200" if busqueda else "SELECT id,numero,fecha,cliente,material,ml,precio,margen,estado FROM cotizaciones ORDER BY id DESC LIMIT 200"
    cur.execute(q, (f"%{busqueda}%",)*3 if busqueda else ())
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def _actualizar_estado(cot_id, nuevo_estado):
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE cotizaciones SET estado=%s WHERE id=%s", (nuevo_estado, cot_id))
    conn.commit()
    cur.close()
    conn.close()

def _stats_db():
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
    s = {}
    cur.execute("SELECT COUNT(*) FROM cotizaciones")
    s["total"]      = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM cotizaciones WHERE estado='Aprobada'")
    s["aprobadas"]  = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM cotizaciones WHERE estado='Pendiente'")
    s["pendientes"] = cur.fetchone()[0]
    cur.execute("SELECT SUM(precio) FROM cotizaciones WHERE estado='Aprobada'")
    s["facturacion"]= cur.fetchone()[0] or 0
    cur.execute("SELECT AVG(margen) FROM cotizaciones WHERE estado='Aprobada'")
    s["margen_prom"]= cur.fetchone()[0] or 0
    cur.execute("SELECT material,COUNT(*),AVG(margen),SUM(precio) FROM cotizaciones WHERE estado='Aprobada' GROUP BY material")
    s["por_material"]= cur.fetchall()
    cur.execute("SELECT SUBSTR(fecha,1,7),COUNT(*),SUM(precio) FROM cotizaciones GROUP BY SUBSTR(fecha,1,7) ORDER BY SUBSTR(fecha,1,7) DESC LIMIT 6")
    s["por_mes"]    = cur.fetchall()
    cur.close()
    conn.close()
    return s

# ── Asistente de parámetros (system prompt SEPARADO del asistente general) ──
def _chat_parametros(historial: list, mensaje: str) -> str:
    """Chat con IA dedicado EXCLUSIVAMENTE a actualizar parametros de costos.
    NO usa el system prompt del asistente general."""
    try:
        import anthropic
        api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return "Configura tu API key en .streamlit/secrets.toml para usar esta funcion."
        client = anthropic.Anthropic(api_key=api_key)
        SYSTEM_PARAMS = """Eres un asistente experto en costos de marmolería en Colombia (Barranquilla, 2026).
Tu ÚNICO objetivo es ayudar al usuario a determinar los valores correctos para los parámetros de su calculadora de costos.

Parámetros que puedes actualizar:
- Gasolina: precio actual por galón en Barranquilla
- Frontier NP300: rendimiento km/galón y costo de desgaste por km
- Cheyenne V8: rendimiento km/galón y costo de desgaste por km
- Flete externo/tercero: tarifa fija por viaje
- Flete agente externo (proveedor→taller): tarifa fija
- Peaje ida+vuelta: valor actual
- Viáticos pueblo: tarifa por noche por persona
- Viáticos ciudad: tarifa por noche por persona
- Costos de produccion por material: prod_ml (COP/ml), zocalo, disco, maquina

REGLAS ESTRICTAS:
1. Haz UNA sola pregunta a la vez
2. Cuando el usuario responda un valor, confírmalo y pasa al siguiente
3. Usa formato colombiano: $16.000/galón, $148/km, etc.
4. Si el usuario no sabe un valor, sugiere el más común en Barranquilla hoy
5. NO saludes, NO expliques qué es cotización, NO preguntes sobre proyectos
6. Cuando termines un grupo de parámetros, muestra un resumen claro de los valores recopilados
7. Respuestas máximo 3 líneas — directo y específico"""
        messages = [{"role": m["role"], "content": m["content"]} for m in historial]
        messages.append({"role": "user", "content": mensaje})
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=400,
            system=SYSTEM_PARAMS,
            messages=messages,
        )
        return response.content[0].text
    except Exception as e:
        return f"Error: {str(e)}"


st.set_page_config(
    page_title="CostoMármol — Mármoles Collante & Castro",
    page_icon="assets/logo_cc.jpeg" if False else "C",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── PALETA CORPORATIVA ────────────────────────────────────────────────────────
C = {
    "navy":    "#0D2137",
    "blue":    "#1B5FA8",
    "blue_m":  "#2E6DB4",
    "blue_l":  "#D6E8FA",
    "blue_ul": "#EEF5FD",
    "gold":    "#C9A84C",
    "gold_l":  "#F5EED6",
    "white":   "#FFFFFF",
    "gray":    "#6B85A0",
    "gray_l":  "#E8EFF7",
    "text":    "#0D2137",
    "success": "#0A6E3F",
    "warn":    "#92580A",
    "error":   "#981520",
}

# Pre-extract color variables to avoid f-string quote conflicts
_navy   = C["navy"]
_blue   = C["blue"]
_blue_m = C["blue_m"]
_blue_l = C["blue_l"]
_blue_ul= C["blue_ul"]
_gold   = C["gold"]
_gold_l = C["gold_l"]
_white  = C["white"]
_gray   = C["gray"]
_gray_l = C["gray_l"]
_text   = C["text"]


# ── CSS PREMIUM DARK ──────────────────────────────────────────────────────────
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=DM+Sans:wght@300;400;500;600;700&display=swap');

* {{ box-sizing: border-box; }}

html, body, [class*="css"] {{
    font-family: 'DM Sans', sans-serif;
}}

/* ── SIDEBAR ── */
section[data-testid="stSidebar"] > div {{
    background: {_navy} !important;
    border-right: 1px solid rgba(255,255,255,0.06) !important;
}}
section[data-testid="stSidebar"] * {{
    color: rgba(255,255,255,0.85) !important;
}}
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {{
    color: white !important;
    font-family: 'Playfair Display', serif !important;
}}
section[data-testid="stSidebar"] .stRadio label {{
    color: rgba(255,255,255,0.8) !important;
    font-size: 0.88rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.01em !important;
}}
section[data-testid="stSidebar"] [data-testid="stRadioLabel"] {{
    color: rgba(255,255,255,0.5) !important;
}}

/* ── MAIN BACKGROUND ── */
.main .block-container {{
    background: {_blue_ul} !important;
    padding-top: 1.5rem !important;
    max-width: 1200px !important;
}}

/* ── BUTTONS ── */
.stButton > button {{
    border-radius: 6px !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    letter-spacing: 0.03em !important;
    border: 1.5px solid {_blue_l} !important;
    color: {_navy} !important;
    background: white !important;
    transition: all 0.18s ease !important;
    padding: 0.45rem 1rem !important;
}}
.stButton > button:hover {{
    border-color: {_blue} !important;
    color: {_blue} !important;
    background: {_blue_ul} !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 3px 10px rgba(27,95,168,0.15) !important;
}}
.stButton > button[kind="primary"] {{
    background: linear-gradient(135deg, #0D2137 0%, #1B5FA8 100%) !important;
    color: white !important;
    border: none !important;
    box-shadow: 0 4px 16px rgba(27,95,168,0.38) !important;
    letter-spacing: 0.05em !important;
    text-transform: uppercase !important;
    font-size: 0.78rem !important;
    padding: 0.6rem 1.4rem !important;
}}
.stButton > button[kind="primary"]:hover {{
    background: linear-gradient(135deg, #1B5FA8 0%, #2E6DB4 100%) !important;
    box-shadow: 0 6px 22px rgba(27,95,168,0.48) !important;
    color: white !important;
    transform: translateY(-2px) !important;
}}

/* ── INPUTS ── */
.stNumberInput label, .stTextInput label,
.stSelectbox label, .stSlider label,
.stCheckbox label, .stTextArea label,
.stRadio label {{ 
    color: {_navy} !important; 
    font-weight: 600 !important; 
    font-size: 0.82rem !important;
    letter-spacing: 0.04em !important;
    text-transform: uppercase !important;
}}
.stNumberInput input, .stTextInput input, .stTextArea textarea {{
    border: 1.5px solid {_blue_l} !important;
    border-radius: 6px !important;
    font-size: 0.92rem !important;
    color: {_navy} !important;
}}
.stNumberInput input:focus, .stTextInput input:focus, .stTextArea textarea:focus {{
    border-color: {_blue} !important;
    box-shadow: 0 0 0 3px rgba(27,95,168,0.1) !important;
}}
.stSelectbox > div > div {{
    border: 1.5px solid {_blue_l} !important;
    border-radius: 6px !important;
}}

/* ── METRICS ── */
[data-testid="stMetric"] {{
    background: white !important;
    border: 1px solid {_blue_l} !important;
    border-radius: 10px !important;
    padding: 16px 18px !important;
}}
[data-testid="stMetricLabel"] p {{
    color: {_gray} !important;
    font-size: 0.68rem !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
}}
[data-testid="stMetricValue"] {{
    color: {_navy} !important;
    font-weight: 800 !important;
    font-size: 1.2rem !important;
}}

/* ── TABS ── */
.stTabs [data-baseweb="tab-list"] {{
    background: transparent !important;
    gap: 4px !important;
    border-bottom: 2px solid {_blue_l} !important;
    padding-bottom: 0 !important;
}}
.stTabs [data-baseweb="tab"] {{
    background: white !important;
    border-radius: 8px 8px 0 0 !important;
    font-weight: 600 !important;
    font-size: 0.82rem !important;
    color: {_gray} !important;
    padding: 10px 20px !important;
    border: 1px solid {_blue_l} !important;
    border-bottom: none !important;
    letter-spacing: 0.04em !important;
    text-transform: uppercase !important;
}}
.stTabs [aria-selected="true"] {{
    background: {_navy} !important;
    color: white !important;
    border-color: {_navy} !important;
}}

/* ── EXPANDER ── */
.streamlit-expanderHeader {{
    background: white !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    color: {_navy} !important;
    border: 1.5px solid {_blue_l} !important;
    font-size: 0.85rem !important;
    letter-spacing: 0.03em !important;
}}
.streamlit-expanderContent {{
    border: 1.5px solid {_blue_l} !important;
    border-top: none !important;
    border-radius: 0 0 8px 8px !important;
    background: white !important;
}}

/* ── DIVIDER ── */
hr {{ border-color: {_blue_l} !important; }}

/* ── SUCCESS/WARNING/ERROR ── */
.stSuccess {{ border-radius: 8px !important; }}
.stWarning {{ border-radius: 8px !important; }}
.stError   {{ border-radius: 8px !important; }}

/* ── FILE UPLOADER ── */
[data-testid="stFileUploader"] {{
    border: 1.5px dashed {_blue_l} !important;
    border-radius: 10px !important;
    background: white !important;
}}
</style>
""", unsafe_allow_html=True)

# ── PALETA CORPORATIVA ────────────────────────────────────────────────────────
C = {
    "navy":    "#0D2137",
    "blue":    "#1B5FA8",
    "blue_m":  "#2E6DB4",
    "blue_l":  "#D6E8FA",
    "blue_ul": "#EEF5FD",
    "gold":    "#C9A84C",
    "gold_l":  "#F5EED6",
    "white":   "#FFFFFF",
    "gray":    "#6B85A0",
    "gray_l":  "#E8EFF7",
    "text":    "#0D2137",
    "success": "#0A6E3F",
    "warn":    "#92580A",
    "error":   "#981520",
}

# Pre-extract color variables to avoid f-string quote conflicts
_navy   = C["navy"]
_blue   = C["blue"]
_blue_m = C["blue_m"]
_blue_l = C["blue_l"]
_blue_ul= C["blue_ul"]
_gold   = C["gold"]
_gold_l = C["gold_l"]
_white  = C["white"]
_gray   = C["gray"]
_gray_l = C["gray_l"]
_text   = C["text"]


# ── CSS PREMIUM DARK ──────────────────────────────────────────────────────────
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=DM+Sans:wght@300;400;500;600;700&display=swap');

* {{ box-sizing: border-box; }}

html, body, [class*="css"] {{
    font-family: 'DM Sans', sans-serif;
}}

/* ── SIDEBAR ── */
section[data-testid="stSidebar"] > div {{
    background: {_navy} !important;
    border-right: 1px solid rgba(255,255,255,0.06) !important;
}}
section[data-testid="stSidebar"] * {{
    color: rgba(255,255,255,0.85) !important;
}}
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {{
    color: white !important;
    font-family: 'Playfair Display', serif !important;
}}
section[data-testid="stSidebar"] .stRadio label {{
    color: rgba(255,255,255,0.8) !important;
    font-size: 0.88rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.01em !important;
}}
section[data-testid="stSidebar"] [data-testid="stRadioLabel"] {{
    color: rgba(255,255,255,0.5) !important;
}}

/* ── MAIN BACKGROUND ── */
.main .block-container {{
    background: {_blue_ul} !important;
    padding-top: 1.5rem !important;
    max-width: 1200px !important;
}}

/* ── BUTTONS ── */
.stButton > button {{
    border-radius: 6px !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    letter-spacing: 0.03em !important;
    border: 1.5px solid {_blue_l} !important;
    color: {_navy} !important;
    background: white !important;
    transition: all 0.18s ease !important;
    padding: 0.45rem 1rem !important;
}}
.stButton > button:hover {{
    border-color: {_blue} !important;
    color: {_blue} !important;
    background: {_blue_ul} !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 3px 10px rgba(27,95,168,0.15) !important;
}}
.stButton > button[kind="primary"] {{
    background: linear-gradient(135deg, #0D2137 0%, #1B5FA8 100%) !important;
    color: white !important;
    border: none !important;
    box-shadow: 0 4px 16px rgba(27,95,168,0.38) !important;
    letter-spacing: 0.05em !important;
    text-transform: uppercase !important;
    font-size: 0.78rem !important;
    padding: 0.6rem 1.4rem !important;
}}
.stButton > button[kind="primary"]:hover {{
    background: linear-gradient(135deg, #1B5FA8 0%, #2E6DB4 100%) !important;
    box-shadow: 0 6px 22px rgba(27,95,168,0.48) !important;
    color: white !important;
    transform: translateY(-2px) !important;
}}

/* ── INPUTS ── */
.stNumberInput label, .stTextInput label,
.stSelectbox label, .stSlider label,
.stCheckbox label, .stTextArea label,
.stRadio label {{ 
    color: {_navy} !important; 
    font-weight: 600 !important; 
    font-size: 0.82rem !important;
    letter-spacing: 0.04em !important;
    text-transform: uppercase !important;
}}
.stNumberInput input, .stTextInput input, .stTextArea textarea {{
    border: 1.5px solid {_blue_l} !important;
    border-radius: 6px !important;
    font-size: 0.92rem !important;
    color: {_navy} !important;
}}
.stNumberInput input:focus, .stTextInput input:focus, .stTextArea textarea:focus {{
    border-color: {_blue} !important;
    box-shadow: 0 0 0 3px rgba(27,95,168,0.1) !important;
}}
.stSelectbox > div > div {{
    border: 1.5px solid {_blue_l} !important;
    border-radius: 6px !important;
}}

/* ── METRICS ── */
[data-testid="stMetric"] {{
    background: white !important;
    border: 1px solid {_blue_l} !important;
    border-radius: 10px !important;
    padding: 16px 18px !important;
}}
[data-testid="stMetricLabel"] p {{
    color: {_gray} !important;
    font-size: 0.68rem !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
}}
[data-testid="stMetricValue"] {{
    color: {_navy} !important;
    font-weight: 800 !important;
    font-size: 1.2rem !important;
}}

/* ── TABS ── */
.stTabs [data-baseweb="tab-list"] {{
    background: transparent !important;
    gap: 4px !important;
    border-bottom: 2px solid {_blue_l} !important;
    padding-bottom: 0 !important;
}}
.stTabs [data-baseweb="tab"] {{
    background: white !important;
    border-radius: 8px 8px 0 0 !important;
    font-weight: 600 !important;
    font-size: 0.82rem !important;
    color: {_gray} !important;
    padding: 10px 20px !important;
    border: 1px solid {_blue_l} !important;
    border-bottom: none !important;
    letter-spacing: 0.04em !important;
    text-transform: uppercase !important;
}}
.stTabs [aria-selected="true"] {{
    background: {_navy} !important;
    color: white !important;
    border-color: {_navy} !important;
}}

/* ── EXPANDER ── */
.streamlit-expanderHeader {{
    background: white !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    color: {_navy} !important;
    border: 1.5px solid {_blue_l} !important;
    font-size: 0.85rem !important;
    letter-spacing: 0.03em !important;
}}
.streamlit-expanderContent {{
    border: 1.5px solid {_blue_l} !important;
    border-top: none !important;
    border-radius: 0 0 8px 8px !important;
    background: white !important;
}}

/* ── DIVIDER ── */
hr {{ border-color: {_blue_l} !important; }}

/* ── SUCCESS/WARNING/ERROR ── */
.stSuccess {{ border-radius: 8px !important; }}
.stWarning {{ border-radius: 8px !important; }}
.stError   {{ border-radius: 8px !important; }}

/* ── FILE UPLOADER ── */
[data-testid="stFileUploader"] {{
    border: 1.5px dashed {_blue_l} !important;
    border-radius: 10px !important;
    background: white !important;
}}
</style>
""", unsafe_allow_html=True)

# ── HELPERS ───────────────────────────────────────────────────────────────────
def card(content_html, padding="20px 24px", background=None, border_color=None):
    bg = background or _bg_card
    bc = border_color or _border
    st.markdown(f"""<div style="background:{bg};border:1px solid {bc};
        border-radius:12px;padding:{padding};margin-bottom:12px">{content_html}</div>""",
        unsafe_allow_html=True)

def hero_banner(titulo, valor_str, subtitulo, meta=""):
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,{_navy} 0%,{_blue} 100%);
         border-radius:14px;padding:32px 36px;margin:8px 0 20px">
      <div style="color:{_gold};font-size:0.68rem;text-transform:uppercase;
           letter-spacing:0.14em;font-weight:700;margin-bottom:10px">{titulo}</div>
      <div style="color:white;font-size:2.8rem;font-weight:900;
           font-family:'Playfair Display',serif;line-height:1;margin-bottom:8px">{valor_str}</div>
      <div style="color:rgba(255,255,255,0.55);font-size:0.85rem">{subtitulo}</div>
      {f'<div style="margin-top:12px">{meta}</div>' if meta else ''}
    </div>""", unsafe_allow_html=True)

def tag(texto, color_bg=None, color_text=None):
    bg = color_bg or _blue_l
    tc = color_text or _blue
    return f'<span style="background:{bg};color:{tc};padding:3px 10px;border-radius:20px;font-size:0.7rem;font-weight:700;letter-spacing:0.05em;text-transform:uppercase">{texto}</span>'

def alerta(texto, tipo="info"):
    if _dm:
        estilos = {
            "info":   ("rgba(27,95,168,0.2)",  "#60A5FA", "#BFDBFE"),
            "bueno":  ("rgba(10,110,63,0.2)",  "#4ADE80", "#BBF7D0"),
            "acepta": ("rgba(194,122,0,0.2)",  "#FCD34D", "#FDE68A"),
            "bajo":   ("rgba(192,26,38,0.2)",  "#F87171", "#FECACA"),
        }
    else:
        estilos = {
            "info":   (_blue_ul, _blue,   _navy),
            "bueno":  ("#E8F5EE",    "#0A6E3F",   "#084D2C"),
            "acepta": ("#FFF3E0",    "#C17A00",   "#7A4D00"),
            "bajo":   ("#FDEAEC",    "#C01A26",   "#8A1520"),
        }
    bg, borde, color = estilos.get(tipo, estilos["info"])
    st.markdown(f"""<div style="background:{bg};border-left:3px solid {borde};
        padding:11px 16px;border-radius:0 8px 8px 0;color:{color};
        font-size:0.86rem;margin:6px 0;line-height:1.55">{texto}</div>""",
        unsafe_allow_html=True)

def seccion_titulo(texto, subtexto=""):
    sub = f'<div style="color:{_text_sub};font-size:0.82rem;font-weight:400;margin-top:3px">{subtexto}</div>' if subtexto else ""
    st.markdown(f'<div style="margin:24px 0 14px"><div style="color:{_text_main};font-size:1.15rem;font-weight:700;letter-spacing:-0.01em">{texto}</div>{sub}</div>', unsafe_allow_html=True)

def linea_costo(label, valor, destacado=False, cero_gris=True):
    gris = cero_gris and valor == 0
    color = _text_sub if gris else (_text_main if not destacado else _blue)
    peso = "800" if destacado else "400"
    borde = f"border-top:2px solid {_navy};padding-top:10px;margin-top:6px;" if destacado else ""
    return f"""<div style="display:flex;justify-content:space-between;padding:8px 0;
        border-bottom:1px solid {_blue_l};{borde}">
      <span style="color:{color};font-size:0.87rem;font-weight:{peso}">{label}</span>
      <span style="color:{color};font-size:0.87rem;font-weight:{peso}">{cop(valor)}</span>
    </div>"""

def bloque_costos(items_label_valor, total_label, total_val):
    html = ""
    for l, v in items_label_valor:
        html += linea_costo(l, v)
    html += linea_costo(total_label, total_val, destacado=True)
    st.markdown(f'<div style="background:{_bg_card};border:1px solid {_border};border-radius:10px;padding:14px 18px">{html}</div>', unsafe_allow_html=True)

def numero_completo(valor):
    """Formatea número sin truncar: $1.250.000 completo."""
    return f"${int(round(valor)):,}".replace(",", ".")

# ── SESSION STATE ─────────────────────────────────────────────────────────────
_defaults = {
    "chat": [],
    "cotizacion": None,
    "contexto_cot": {},
    "resumen_ia": "",
    "aiu_items": [
        {"desc": "Material pétreo (suministro)", "und": "m²",  "cant": 10.0, "punit": 250_000},
        {"desc": "Mano de obra corte y elaboración", "und": "m²", "cant": 10.0, "punit": 100_000},
        {"desc": "Instalación y nivelación",  "und": "m²",  "cant": 10.0, "punit": 50_000},
        {"desc": "Insumos (disco, adhesivo, silicona)", "und": "glb", "cant": 1.0, "punit": 150_000},
    ],
    "pre": {},
    "piezas": [],
    "tarifas_custom": None,     # dict con tarifas editadas por usuario
    "logistica_custom": None,   # dict con logística editada
    "viaticos_custom": None,    # dict con viáticos editados
    "logo_bytes": None,         # logo cargado por usuario
    "logo_mime": None,
    "empresa_info": {
        "nombre": "MÁRMOLES COLLANTE & CASTRO LTDA.",
        "nit": "NIT: 900.111.561-1",
        "tel": "+57 300 000 0000",
        "email": "ventas@marmolescc.com",
        "ciudad": "Barranquilla, Atlántico — Colombia",
        "banco": "Davivienda",
        "cuenta_tipo": "Cuenta Corriente Empresas",
        "cuenta_numero": "108900027484",
    },
    "params_wizard_activo": False,
    "tour_activo": False,
    "tour_paso": 0,
    "tour_completado": False,
    "vehiculos_custom": None,
    "params_wizard_campo": None,
    "params_wizard_chat": [],
    "cat_sel": "Mármol",
    "dark_mode": False,
    "primera_visita": True,
    "onboarding_paso": 0,
    "onboarding_activo": False,
    "hist_detalle_id": None,
    "hist_detalle_datos": None,
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Activar onboarding automático en primera visita
if st.session_state.get("primera_visita") and not st.session_state.get("onboarding_activo") and not st.session_state.get("tour_completado"):
    st.session_state.onboarding_activo = True
    st.session_state.primera_visita = False

# Tarifas activas (custom o por defecto)
def get_tarifas():
    return st.session_state.tarifas_custom or TARIFAS

def get_logistica():
    return st.session_state.logistica_custom or LOGISTICA

def get_viaticos():
    return st.session_state.viaticos_custom or VIATICOS

def get_vehiculos_config():
    import copy
    base = copy.deepcopy(VEHICULOS_CONFIG)
    custom = st.session_state.get("vehiculos_custom") or {}
    for k, v in custom.items():
        base[k] = v
    return base

def get_vehiculos_dict():
    vc = get_vehiculos_config()
    result = {}
    for key, cfg in vc.items():
        nombre = cfg.get("nombre", key)
        sufijo = " (propio)" if cfg.get("tipo") == "propio" else " (flete externo)"
        result[f"{nombre}{sufijo}"] = key
    return result

# ── SIDEBAR ───────────────────────────────────────────────────────────────────
with st.sidebar:
    # ── Logo: primero intenta el logo cargado por el usuario, luego el archivo local
    _logo_shown = False
    if st.session_state.get("logo_bytes"):
        try:
            st.image(st.session_state.logo_bytes, use_container_width=True)
            _logo_shown = True
        except Exception:
            pass
    if not _logo_shown:
        _local_paths = [
            "/mnt/user-data/uploads/logo_cc.jpeg",
            "logo_cc.jpeg",
        ]
        for _lp in _local_paths:
            try:
                with open(_lp, "rb") as _f:
                    _ld = _f.read()
                st.image(_ld, use_container_width=True)
                _logo_shown = True
                break
            except Exception:
                pass
    if not _logo_shown:
        # Fallback: bloque corporativo con iniciales
        st.markdown(
            f'<div style="background:linear-gradient(135deg,rgba(255,255,255,0.12),rgba(255,255,255,0.05));'
            f'border:1px solid rgba(255,255,255,0.15);border-radius:12px;padding:22px 16px;'
            f'text-align:center;margin-bottom:4px">'
            f'<div style="color:{_gold};font-size:2rem;font-weight:900;font-family:Playfair Display,serif;letter-spacing:0.05em">CC</div>'
            f'<div style="color:rgba(255,255,255,0.9);font-size:0.75rem;font-weight:700;margin-top:6px;letter-spacing:0.04em">MÁRMOLES</div>'
            f'<div style="color:rgba(255,255,255,0.5);font-size:0.65rem;margin-top:2px">Collante &amp; Castro</div>'
            f'</div>',
            unsafe_allow_html=True
        )

    # Nombre empresa
    _emp_nombre = st.session_state.get("empresa_info", {}).get("nombre", "MÁRMOLES COLLANTE & CASTRO LTDA.")
    st.markdown(
        f'<div style="margin:10px 0 16px;padding:0 2px">'
        f'<div style="color:white;font-size:0.82rem;font-weight:700;line-height:1.3">{_emp_nombre}</div>'
        f'<div style="color:{_gold};font-size:0.62rem;text-transform:uppercase;letter-spacing:0.1em;margin-top:3px">Sistema de Cotizacion Profesional</div>'
        f'</div>',
        unsafe_allow_html=True
    )

    st.markdown(f'<div style="height:1px;background:rgba(255,255,255,0.1);margin:4px 0 12px"></div>', unsafe_allow_html=True)
    st.markdown(f'<div style="color:rgba(255,255,255,0.35);font-size:0.62rem;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px">Menu</div>', unsafe_allow_html=True)

    pagina = st.radio("", [
        "Inicio",
        "Cotizacion Directa",
        "Cotizacion AIU",
        "Historial",
        "Dashboard",
        "Parametros",
        "Asistente IA",
        "Configuracion",
    ], label_visibility="collapsed")

    st.markdown(f'<div style="height:1px;background:rgba(255,255,255,0.1);margin:12px 0"></div>', unsafe_allow_html=True)
    if ia_disponible():
        st.markdown(f'<div style="background:rgba(74,222,128,0.15);border:1px solid rgba(74,222,128,0.3);border-radius:6px;padding:7px 10px;font-size:0.75rem;font-weight:600;color:#4ade80">IA Activa — Claude</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div style="background:rgba(251,191,36,0.12);border:1px solid rgba(251,191,36,0.25);border-radius:6px;padding:7px 10px;font-size:0.75rem;font-weight:600;color:#fbbf24">IA sin configurar</div>', unsafe_allow_html=True)
        with st.expander("Activar IA (2 min)"):
            st.markdown("Crea `.streamlit/secrets.toml` y escribe:\n```toml\nANTHROPIC_API_KEY = \"sk-ant-...\"\n```\nObtén tu clave en `console.anthropic.com`")

    st.markdown(f'<div style="height:1px;background:rgba(255,255,255,0.1);margin:10px 0"></div>', unsafe_allow_html=True)

    # Theme toggle
    _theme_label = "☀ Modo Claro" if _dm else "🌙 Modo Oscuro"
    if st.button(_theme_label, use_container_width=True, key="btn_theme"):
        st.session_state.dark_mode = not st.session_state.dark_mode
        st.rerun()

    # Onboarding / tour
    _onb_label = "📖 Ver guía de inicio" if st.session_state.get("tour_completado") else "📖 Guía de inicio"
    if st.button(_onb_label, use_container_width=True, key="btn_onb_sidebar"):
        st.session_state.onboarding_activo = True
        st.session_state.onboarding_paso = 0
        st.rerun()

    st.markdown(f'<div style="color:rgba(255,255,255,0.2);font-size:0.62rem;margin-top:14px">Feb 2026 · Barranquilla, Colombia</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# INICIO
# ═══════════════════════════════════════════════════════════════════════════════
if pagina == "Inicio":
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,{_navy} 0%,{_blue} 100%);
         border-radius:16px;padding:40px 44px;margin-bottom:28px;position:relative;overflow:hidden">
      <div style="position:absolute;top:-40px;right:-40px;width:200px;height:200px;
           background:rgba(255,255,255,0.03);border-radius:50%"></div>
      <div style="color:{_gold};font-size:0.68rem;text-transform:uppercase;
           letter-spacing:0.15em;font-weight:700;margin-bottom:12px">
        Mármoles Collante &amp; Castro Ltda.
      </div>
      <div style="color:white;font-size:2.4rem;font-weight:900;
           font-family:'Playfair Display',serif;line-height:1.1;margin-bottom:14px">
        Sistema de Cotización<br>Profesional
      </div>
      <div style="color:rgba(255,255,255,0.55);font-size:0.92rem;line-height:1.65;max-width:500px">
        Calcula el costo real de tus proyectos en mármol, granito, sinterizado, quarztone y cuarcita.
        Cotización, logística, AIU y PDF en menos de 2 minutos.
      </div>
    </div>
    """, unsafe_allow_html=True)
    # CTA onboarding si no ha sido completado
    if not st.session_state.get("tour_completado"):
        _i1, _i2, _i3 = st.columns([2,2,3])
        if _i1.button("📖 Ver guía de inicio", type="primary", use_container_width=True):
            st.session_state.onboarding_activo = True
            st.session_state.onboarding_paso = 0
            st.rerun()
        if _i2.button("⚡ Ir directo a cotizar", use_container_width=True):
            st.session_state.tour_completado = True
            st.rerun()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Materiales", "5 tipos", "Mármol · Granito · Sint. · Quartz · Cuarcita")
    c2.metric("Tiempo", "2 min", "vs. 45–90 min manual")
    c3.metric("Estructura", "AIU + IVA", "Norma colombiana")
    c4.metric("Exporta", "PDF", "Cotización + Cuenta de cobro")

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        card(f"""
        <div style="font-weight:700;color:{_navy};font-size:1rem;margin-bottom:6px">Cotizacion Directa</div>
        <div style="color:{_gray};font-size:0.87rem;line-height:1.55">
          Para clientes particulares. Ingresa material, precio/m² y área por piezas (ML × ancho).
          La app calcula mano de obra, logística, insumos y precio de venta sugerido.
        </div>""")
    with col2:
        card(f"""
        <div style="font-weight:700;color:{_navy};font-size:1rem;margin-bottom:6px">Cotizacion AIU</div>
        <div style="color:{_gray};font-size:0.87rem;line-height:1.55">
          Para constructoras y licitaciones. Estructura formal colombiana: Administración,
          Imprevistos, Utilidad + IVA sobre utilidad.
        </div>""")

    alerta("Describe tu proyecto en lenguaje natural en el <strong>Asistente IA</strong> y la app pre-llenará la calculadora por ti.", "info")


# ═══════════════════════════════════════════════════════════════════════════════
# COTIZACIÓN DIRECTA
# ═══════════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════
# ONBOARDING INTERACTIVO — primera visita o manual desde sidebar
# ═══════════════════════════════════════════════════════════════════════════════
ONBOARDING_PASOS = [
    {
        "icono": "👋",
        "titulo": "Bienvenido a CostoMármol",
        "desc": "Tu sistema de cotización profesional para Mármoles Collante & Castro",
        "contenido": """<p>Esta herramienta te permite <b>calcular el costo real</b> de cualquier proyecto
        de mármol, granito, sinterizado, cuarcita o quarztone en <b>menos de 2 minutos</b>.</p>
        <p>Con ella puedes generar cotizaciones PDF, cuentas de cobro, ver tu historial comercial
        y analizar el desempeño financiero de tu empresa.</p>
        <p>Este recorrido te guía en <b>7 pasos rápidos</b>. Puedes cerrarlo en cualquier momento.</p>""",
        "accion": "Entendido, ¡empecemos!",
    },
    {
        "icono": "📐",
        "titulo": "Paso 1 — Material y precio/m²",
        "desc": "Siempre empieza por el material que compraste",
        "contenido": """<p>Ve a <b>Cotizacion Directa</b> en el menú lateral.</p>
        <p>Selecciona la categoría (Mármol, Granito, etc.), escribe la referencia del material
        y el precio por m² que te cobró el proveedor.</p>
        <p><b>Consejo:</b> Si no recuerdas el precio exacto, usa el catálogo de materiales
        en la misma sección para partir de referencias del mercado.</p>""",
        "accion": "Entendido",
    },
    {
        "icono": "📏",
        "titulo": "Paso 2 — Medidas en metros lineales (ML)",
        "desc": "Así es como la industria mide en Colombia",
        "contenido": """<p>En marmolería se trabaja en <b>metros lineales (ML)</b>, no en m².</p>
        <p>Agrega cada pieza con su largo en ML y el ancho según el tipo
        (mesón = 0.60m, isla = 1.00m, etc.). La app convierte automáticamente a m².</p>
        <p><b>Ejemplo:</b> Mesón de cocina 3.5 ML × 0.60m = 2.10 m²</p>""",
        "accion": "Claro",
    },
    {
        "icono": "🚛",
        "titulo": "Paso 3 — Logística y transporte",
        "desc": "Estos costos se comen el margen si no los calculas",
        "contenido": """<p>Indica el vehículo de entrega (Frontier, Cheyenne o externo),
        los kilómetros hasta la obra y el número de peajes.</p>
        <p>Si el material viene de un proveedor externo al taller, activa
        <b>"Agente externo"</b> — la app suma el flete automáticamente.</p>
        <p>Para obras foráneas activa <b>"Proyecto foráneo"</b> y agrega viáticos.</p>""",
        "accion": "Entendido",
    },
    {
        "icono": "💰",
        "titulo": "Paso 4 — Precio sugerido y margen",
        "desc": "El corazón de la cotización",
        "contenido": """<p>Con un margen del <b>40%</b> (valor por defecto), la app calcula
        automáticamente el precio que deberías cobrar.</p>
        <p>Un margen saludable en marmolería es <b>30–45%</b>.
        Por debajo del 20% estás en zona de riesgo.</p>
        <p>Usa el comparador de materiales para ver cómo cambia el precio
        si usas otro material.</p>""",
        "accion": "Perfecto",
    },
    {
        "icono": "📄",
        "titulo": "Paso 5 — Genera el PDF profesional",
        "desc": "Cotización y cuenta de cobro lista para enviar",
        "contenido": """<p>Después de calcular, en la misma página aparece la sección
        <b>Exportar documentos</b>.</p>
        <p>Puedes generar:<br>
        • <b>Cotización PDF</b> con desglose de costos, alcance del proyecto e incluye/no incluye<br>
        • <b>Cuenta de cobro PDF</b> con datos bancarios lista para enviar al cliente</p>
        <p>Configura tu logo y datos empresariales en <b>Configuración</b>.</p>""",
        "accion": "Excelente",
    },
    {
        "icono": "📊",
        "titulo": "Paso 6 — Historial y Dashboard",
        "desc": "Tu negocio en tiempo real",
        "contenido": """<p>Cada cotización se guarda automáticamente en el <b>Historial</b>.
        Puedes cambiar el estado (Pendiente / Aprobada / Rechazada),
        ver el detalle completo y regenerar el PDF.</p>
        <p>El <b>Dashboard</b> muestra tu facturación mensual, margen promedio
        por material y tendencias comerciales.</p>""",
        "accion": "¡Ya sé todo!",
    },
]

if st.session_state.get("onboarding_activo"):
    _op = min(st.session_state.get("onboarding_paso", 0), len(ONBOARDING_PASOS) - 1)
    _paso = ONBOARDING_PASOS[_op]
    _total = len(ONBOARDING_PASOS)
    _prog = int((_op / max(_total - 1, 1)) * 100)

    # Overlay
    st.markdown("""<div style="position:fixed;top:0;left:0;right:0;bottom:0;
        background:rgba(0,0,0,0.6);z-index:9990;pointer-events:none"></div>""",
        unsafe_allow_html=True)

    # Modal card
    _contenido_html = _paso["contenido"]
    _nav_html = f"""
    <div style="position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);
        z-index:9999;background:{'#1e293b' if _dm else 'white'};border-radius:18px;
        padding:36px 40px;max-width:560px;width:92%;
        box-shadow:0 32px 80px rgba(0,0,0,{'0.6' if _dm else '0.28'});
        border-top:5px solid #C9A84C;font-family:'DM Sans',sans-serif">

      <!-- Header -->
      <div style="display:flex;align-items:center;gap:14px;margin-bottom:18px">
        <div style="font-size:2rem;line-height:1">{_paso['icono']}</div>
        <div>
          <div style="font-size:0.72rem;color:#C9A84C;text-transform:uppercase;
               letter-spacing:0.1em;font-weight:700">Paso {_op + 1} de {_total}</div>
          <div style="font-size:1.15rem;font-weight:800;
               color:{'#E6EDF3' if _dm else '#0D2137'};
               font-family:'Playfair Display',serif">{_paso['titulo']}</div>
          <div style="font-size:0.82rem;color:{'#8B949E' if _dm else '#6B85A0'}">{_paso['desc']}</div>
        </div>
      </div>

      <!-- Content -->
      <div style="font-size:0.9rem;color:{'#c9d1d9' if _dm else '#2a3a4a'};
           line-height:1.75;margin-bottom:20px">{_contenido_html}</div>

      <!-- Progress bar -->
      <div style="background:{'rgba(255,255,255,0.1)' if _dm else '#e8eff7'};
           border-radius:6px;height:5px;margin-bottom:16px">
        <div style="background:#C9A84C;width:{_prog}%;height:5px;
             border-radius:6px;transition:width 0.3s ease"></div>
      </div>

      <div style="font-size:0.75rem;color:{'#6B85A0' if _dm else '#8B949E'};
           text-align:center;margin-top:4px">
        Cierra este diálogo en cualquier momento desde el botón de abajo
      </div>
    </div>"""
    st.markdown(_nav_html, unsafe_allow_html=True)

    _oc1, _oc2, _oc3 = st.columns([1, 1, 1])
    with _oc1:
        if _op > 0:
            if st.button("← Anterior", key="onb_prev", use_container_width=True):
                st.session_state.onboarding_paso -= 1
                st.rerun()
    with _oc2:
        if st.button("✕ Cerrar guía", key="onb_close", use_container_width=True):
            st.session_state.onboarding_activo  = False
            st.session_state.tour_completado    = True
            st.rerun()
    with _oc3:
        if _op < _total - 1:
            if st.button(_paso["accion"] + " →", key="onb_next", type="primary", use_container_width=True):
                st.session_state.onboarding_paso += 1
                st.rerun()
        else:
            if st.button("🚀 Empezar a cotizar", key="onb_fin", type="primary", use_container_width=True):
                st.session_state.onboarding_activo  = False
                st.session_state.tour_completado    = True
                st.rerun()

if pagina == "Cotizacion Directa":

    st.markdown(f"<h2 style='color:{_text_main};font-family:Playfair Display,serif;margin-bottom:4px'>Cotizacion Directa</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:{_text_sub};font-size:0.88rem;margin-bottom:20px'>Para proyectos residenciales y clientes particulares</p>", unsafe_allow_html=True)

    pre = st.session_state.pre
    if pre:
        alerta("La IA detectó tu proyecto y pre-llenó los campos. Revisa y ajusta lo que necesites.", "bueno")
        if st.button("Limpiar pre-llenado"):
            st.session_state.pre = {}
            st.rerun()

    TARIFAS_ACT = get_tarifas()
    LOG_ACT = get_logistica()
    VIA_ACT = get_viaticos()

    # ── PASO 1: MATERIAL ──────────────────────────────────────────────────────
    seccion_titulo("Paso 1 — Material", "Selecciona el tipo de piedra e ingresa el precio del proveedor")

    cat_sel = st.session_state.get("cat_sel", pre.get("categoria", "Mármol"))
    cols_cat = st.columns(len(CATEGORIAS_MATERIAL))
    for i, cat in enumerate(CATEGORIAS_MATERIAL):
        bg_c, color_c = BADGE_COLORS.get(cat, (_blue_l, _navy))
        activo = cat_sel == cat
        borde = f"2px solid {_blue}" if activo else f"1px solid {_blue_l}"
        bg = _blue_ul if activo else "white"
        with cols_cat[i]:
            st.markdown(f"""<div style="border:{borde};border-radius:10px;padding:14px 8px;
                background:{bg};text-align:center">
              <div style="font-weight:700;font-size:0.8rem;color:{_navy};margin-top:2px">
                {'▶ ' if activo else ''}{cat}</div>
              <div style="font-size:0.65rem;color:{_gray};margin-top:4px;line-height:1.3">
                {DESCRIPCIONES_CATEGORIA.get(cat,'')}</div>
            </div>""", unsafe_allow_html=True)
            if st.button(f"Elegir {cat}", key=f"cat_{i}", use_container_width=True):
                st.session_state.cat_sel = cat
                st.rerun()
    cat_sel = st.session_state.get("cat_sel", "Mármol")

    st.markdown(f"<div style='margin:12px 0 4px;font-size:0.82rem;color:{_gray};font-weight:600;text-transform:uppercase;letter-spacing:0.05em'>Material seleccionado: <span style='color:{_navy}'>{cat_sel}</span></div>", unsafe_allow_html=True)
    st.divider()

    c1, c2, c3 = st.columns(3)
    with c1:
        refs_cat = [m["nombre"] for m in MATERIALES_CATALOGO if m["categoria"] == cat_sel]
        refs_cat = ["Otra referencia..."] + refs_cat
        ref_sel = st.selectbox("Referencia del material", refs_cat)
        if ref_sel == "Otra referencia...":
            referencia = st.text_input("Nombre de la referencia", value=pre.get("referencia", ""), placeholder="Ej: Calacatta Gold")
        else:
            referencia = ref_sel
            m_cat = next((m for m in MATERIALES_CATALOGO if m["nombre"] == ref_sel), None)
            if m_cat and "precio_m2_default" not in st.session_state:
                st.session_state["precio_m2_default"] = m_cat["precio_m2"]
    with c2:
        precio_m2_default = pre.get("precio_m2") or st.session_state.pop("precio_m2_default", 220_000)
        precio_m2 = st.number_input("Precio por m² — COP", min_value=10_000, max_value=5_000_000,
            value=int(precio_m2_default), step=1_000,
            help="El valor por m² que está en la factura del proveedor")
    with c3:
        area_placa_default = pre.get("area_placa_comprada", 5.94)
        area_placa = st.number_input("Area total comprada (m²)", min_value=0.01, max_value=200.0,
            value=float(area_placa_default), step=0.1, format="%.3f",
            help="Cuantos m² de material compraste en total")

    costo_mat = precio_m2 * area_placa
    alerta(f"Costo total del material: <strong>{numero_completo(precio_m2)}/m²</strong> x {area_placa} m² = <strong>{numero_completo(costo_mat)}</strong>", "info")

    st.markdown("---")

    # ── PASO 2: DIMENSIONES ──────────────────────────────────────────────────
    seccion_titulo("Paso 2 — Dimensiones del proyecto", "Ingresa cada pieza por metros lineales — la app convierte a m² automaticamente")

    if "piezas" not in st.session_state or not st.session_state.piezas:
        st.session_state.piezas = [{"nombre": "Meson de cocina", "ml": 2.0, "ancho_tipo": "Mesón de cocina", "ancho_custom": 0.60}]

    _mostrar_avanzado = st.session_state.get("modo_avanzado_medidas", False)
    if not _mostrar_avanzado:
        modo_medida = "Por piezas (ML × Ancho) — recomendado"
        if st.button("Opciones avanzadas (ingresar m\u00b2 directamente)"):
            st.session_state.modo_avanzado_medidas = True
            st.rerun()
    else:
        modo_medida = st.radio("Modo de ingreso", ["Por piezas (ML \u00d7 Ancho) \u2014 recomendado", "Ingresar m\u00b2 directamente"], horizontal=True)
        if st.button("Volver al modo simplificado"):
            st.session_state.modo_avanzado_medidas = False
            st.rerun()

    m2_real = 0.0
    m2_cortados_total = 0.0

    if "Por piezas" in modo_medida:
        alerta("Agrega cada pieza del proyecto. Para cada pieza: largo en ML × ancho estandar = m² calculados.", "info")

        hdr = st.columns([3, 1.2, 2.5, 1.5, 1.6, 0.6])
        for col, lbl in zip(hdr, ["Pieza / Descripcion", "ML largo", "Tipo de superficie", "Ancho (m)", "m² calculados", ""]):
            col.markdown(f"<div style='font-size:0.72rem;font-weight:700;color:{_gray};text-transform:uppercase;letter-spacing:0.06em;padding:4px 0'>{lbl}</div>", unsafe_allow_html=True)

        tipos_superficie = list(ANCHOS_ESTANDAR.keys())
        piezas_nuevas = []
        total_m2_piezas = 0.0

        for idx, pieza in enumerate(st.session_state.piezas):
            c0, c1, c2, c3, c4, c5 = st.columns([3, 1.2, 2.5, 1.5, 1.6, 0.6])
            with c0:
                nombre_p = st.text_input("Nombre pieza", value=pieza.get("nombre", ""), key=f"pnom_{idx}", label_visibility="collapsed")
            with c1:
                ml_p = st.number_input("ML", value=float(pieza.get("ml", 1.0)), min_value=0.01, step=0.1, format="%.2f", key=f"pml_{idx}", label_visibility="collapsed")
            with c2:
                tipo_idx = tipos_superficie.index(pieza.get("ancho_tipo", tipos_superficie[0])) if pieza.get("ancho_tipo") in tipos_superficie else 0
                ancho_tipo_p = st.selectbox("Tipo", tipos_superficie, index=tipo_idx, key=f"ptip_{idx}", label_visibility="collapsed")
            with c3:
                ancho_def = ANCHOS_ESTANDAR[ancho_tipo_p]["ancho"] or pieza.get("ancho_custom", 0.60)
                ancho_p = st.number_input("Ancho", value=float(ancho_def), min_value=0.01, max_value=5.0, step=0.01, format="%.2f", key=f"panc_{idx}", label_visibility="collapsed")
            m2_p = ml_a_m2(ml_p, ancho_p)
            total_m2_piezas += m2_p
            with c4:
                _m2p_fmt = f"{m2_p:.3f}".replace(".", ",")
                st.markdown(f"<div style='padding:8px 4px;font-weight:700;color:{_navy};font-size:0.9rem'>{_m2p_fmt} m²</div>", unsafe_allow_html=True)
            with c5:
                if st.button("X", key=f"del_{idx}") and len(st.session_state.piezas) > 1:
                    st.session_state.piezas.pop(idx)
                    st.rerun()
            piezas_nuevas.append({"nombre": nombre_p, "ml": ml_p, "ancho_tipo": ancho_tipo_p, "ancho_custom": ancho_p})

        st.session_state.piezas = piezas_nuevas
        m2_real = total_m2_piezas
        m2_cortados_total = total_m2_piezas

        col_add, col_sum = st.columns([1, 2])
        with col_add:
            if st.button("+ Agregar pieza", use_container_width=True):
                st.session_state.piezas.append({"nombre": f"Pieza {len(st.session_state.piezas)+1}", "ml": 1.0, "ancho_tipo": tipos_superficie[0], "ancho_custom": 0.60})
                st.rerun()
        with col_sum:
            if m2_real > 0:
                _ml_total = sum(p.get("ml", 0) for p in st.session_state.piezas if isinstance(p, dict))
                _ml_str = f"{_ml_total:.2f}".replace(".", ",")
                _m2_str = f"{m2_real:.3f}".replace(".", ",")
                st.markdown(
                    f'''<div style="background:{_navy};color:white;border-radius:10px;padding:12px 18px;text-align:center">
                  <div style="font-size:0.7rem;color:{_gold};text-transform:uppercase;letter-spacing:0.08em">Total del proyecto</div>
                  <div style="font-size:2rem;font-weight:900;font-family:'Playfair Display',serif">{_ml_str} ml</div>
                  <div style="font-size:0.85rem;color:rgba(255,255,255,0.6);margin-top:2px">{_m2_str} m² de material</div>
                  <div style="font-size:0.72rem;color:rgba(255,255,255,0.45);margin-top:1px">{len(st.session_state.piezas)} piezas</div>
                </div>''', unsafe_allow_html=True)

        extra_corte = st.number_input("m² adicionales cortados no aprovechados (desperdicios)", min_value=0.0, value=0.0, step=0.05, format="%.3f")
        m2_cortados_total += extra_corte

    else:
        c1, c2 = st.columns(2)
        with c1:
            usar_calc = st.checkbox("Calcular desde largo x ancho", value=False)
            if usar_calc:
                s1, s2, s3 = st.columns(3)
                lg = s1.number_input("Largo", min_value=0.0, value=4.0, step=0.1, format="%.2f")
                an = s2.number_input("Ancho", min_value=0.0, value=0.60, step=0.01, format="%.2f")
                un = s3.selectbox("Unidad", ["metros", "cm"])
                m2_real = ((lg/100)*(an/100)) if un == "cm" else lg*an
                st.info(f"{lg} {un} x {an} {un} = {m2_real:.3f} m²")
            else:
                m2_real = st.number_input("m² reales del proyecto", min_value=0.01, value=float(pre.get("m2_proyecto", 4.0)), step=0.05, format="%.3f")
        with c2:
            m2_cortados_input = st.number_input("m² cortados de la placa (puede ser mayor por desperdicios)", min_value=0.0, value=float(m2_real), step=0.05, format="%.3f")
            m2_cortados_total = m2_cortados_input if m2_cortados_input > 0 else m2_real

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    with c1:
        m2_usados_default = pre.get("m2_usados", 0.0)
        m2_usados = st.number_input("m² finalmente instalados", min_value=0.0,
            value=float(m2_usados_default) if m2_usados_default else float(round(m2_real, 3)),
            step=0.05, format="%.3f", help="Puede ser menor si hay huecos (poceta, estufa, etc.)")
    with c2:
        margen_pct = st.slider("Margen de utilidad (%)", min_value=5, max_value=80, value=40, step=1)
    with c3:
        if area_placa > 0 and m2_usados > 0:
            aprv = min(100, m2_usados / area_placa * 100)
            retal = max(0, area_placa - m2_usados)
            estado_a = "bueno" if aprv >= 80 else "acepta" if aprv >= 50 else "bajo"
            alerta(f"Aprovechamiento: <strong>{aprv:.1f}%</strong> — Retal: {retal:.3f} m²", estado_a)

    if m2_cortados_total > 0 and m2_real > 0:
        alerta(f"Resumen: {sum(p['ml'] for p in st.session_state.get('piezas',[]) if isinstance(p,dict)):.2f} ml totales · {m2_real:.3f} m² de material · Produccion calculada sobre los metros lineales reales", "info")

    st.markdown("---")

    # ── PASO 3: PROYECTO ─────────────────────────────────────────────────────
    seccion_titulo("Paso 3 — Tipo de proyecto y obra")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        tipo_default = pre.get("tipo_proyecto", "Mesón")
        tipo_opts = ["Mesón", "Cocina", "Baño", "Piso", "Escalera", "Fachada", "Mueble de cocina", "Otro"]
        tipo = st.selectbox("Tipo de proyecto", tipo_opts,
            index=tipo_opts.index(tipo_default) if tipo_default in tipo_opts else 0)
    with c2:
        etapa_lbl = st.selectbox("Etapa de la obra", list(ETAPAS_OBRA.keys()))
        etapa = ETAPAS_OBRA[etapa_lbl]
    with c3:
        dias_default = int(pre.get("dias_obra") or 2)
        dias = st.number_input("Dias en obra", min_value=1, value=dias_default, step=1)
    with c4:
        pers_default = int(pre.get("personas") or 2)
        personas = st.number_input("Num. de personas", min_value=1, value=pers_default, step=1)

    nombre_cliente = st.text_input("Nombre del cliente (para el PDF)", placeholder="Ej: Juan Garcia / Constructora XYZ")

    st.markdown("**Zocalos**")
    zocalo_activo = st.checkbox("Este proyecto lleva zocalos", key="cb_zocalo")
    zocalo_ml = 0.0
    if zocalo_activo:
        zocalo_ml = st.number_input("Metros lineales de zocalo (ml)", min_value=0.0, value=2.0, step=0.5, format="%.1f")
        tar_z = TARIFAS_ACT.get(cat_sel, {}).get("zocalo", 0)
        alerta(f"Tarifa zocalo {cat_sel}: {numero_completo(tar_z)}/ml — Subtotal: <strong>{numero_completo(zocalo_ml*tar_z)}</strong>", "info")

    st.markdown("---")

    # ── PASO 4: LOGÍSTICA ────────────────────────────────────────────────────
    seccion_titulo("Paso 4 — Logistica")

    col_agt, col_veh = st.columns(2)
    with col_agt:
        st.markdown(f"<div style='font-size:0.8rem;font-weight:600;color:{_navy};margin-bottom:6px'>Como llego el material al taller</div>", unsafe_allow_html=True)
        agente_ext_taller = st.checkbox("Agente externo trajo el material al taller",
            value=bool(pre.get("agente_externo_taller", False)), key="cb_agente_taller",
            help=f"Agrega {numero_completo(LOG_ACT['agente'])} de flete.")
        if agente_ext_taller:
            alerta(f"Flete proveedor al taller: <strong>{numero_completo(LOG_ACT['agente'])}</strong>", "info")
    with col_veh:
        st.markdown(f"<div style='font-size:0.8rem;font-weight:600;color:{_navy};margin-bottom:6px'>Transporte taller al cliente</div>", unsafe_allow_html=True)
        _veh_dict = get_vehiculos_dict()
        veh_default = pre.get("vehiculo_entrega", "frontier")
        _veh_keys = list(_veh_dict.keys())
        _veh_vals = list(_veh_dict.values())
        _veh_idx  = _veh_vals.index(veh_default) if veh_default in _veh_vals else 0
        veh_lbl   = st.selectbox("Vehiculo de entrega", _veh_keys, index=_veh_idx)
        vehiculo  = _veh_dict[veh_lbl]

    c1, c2 = st.columns(2)
    with c1:
        km_default = float(pre.get("km") or 5.0)
        km = st.number_input("Distancia taller al cliente (km, un trayecto)", min_value=0.0, value=km_default, step=0.5, format="%.1f")
        st.caption("El sistema calcula automaticamente el costo del tiempo de traslado de los operarios segun esta distancia.")
    with c2:
        peajes_default = int(pre.get("peajes") or 0)
        peajes = st.number_input("Num. de peajes (total ida+vuelta)", min_value=0, value=peajes_default, step=1)

    from calculos import calcular_logistica as _calc_log
    _log_custom  = st.session_state.get("logistica_custom") or None
    _veh_custom  = {**VEHICULOS_CONFIG, **(st.session_state.get("vehiculos_custom") or {})}
    log_prev = _calc_log(vehiculo, km, peajes, agente_ext_taller, personas, cat_sel,
        logistica_override=_log_custom, vehiculos_custom=_veh_custom)
    with st.expander(f"Desglose logistico — Total: {numero_completo(log_prev['total'])}"):
        items_log = []
        _vc_cur = get_vehiculos_config().get(vehiculo, {})
        if _vc_cur.get("tipo") != "externo":
            items_log.append((f"Base {_vc_cur.get('nombre', veh_lbl)}", log_prev["base"]))
            items_log.append((f"Gasolina + desgaste mecanico ({km*2:.0f} km ida+vuelta)", log_prev["km_costo"]))
        else:
            items_log.append((f"Flete {_vc_cur.get('nombre', 'Externo')}", log_prev["vehiculo"]))
        if agente_ext_taller:
            items_log.append(("Flete proveedor al taller", log_prev["agente"]))
        items_log.append((f"Peajes ({peajes} peajes)", log_prev["peajes"]))
        items_log.append(("Desgaste de herramientas", log_prev["herram"]))

        bloque_costos(items_log, "TOTAL LOGISTICO", log_prev["total"])


    st.markdown("---")

    # ── PASO 5: FORÁNEO ──────────────────────────────────────────────────────
    seccion_titulo("Paso 5 — Proyecto fuera de Barranquilla?")
    foraneo_activo = st.checkbox("Si, este proyecto es en otra ciudad o municipio", key="cb_foraneo")
    viaticos_activos = False
    tipo_aloj = "pueblo"
    noches = 0
    if foraneo_activo:
        c1, c2, c3 = st.columns(3)
        with c1:
            viaticos_activos = st.checkbox("Agregar viaticos (alojamiento)", key="cb_viaticos")
        with c2:
            tipo_aloj_lbl = st.selectbox("Tipo de destino", list(ALOJAMIENTO.keys()))
            tipo_aloj = ALOJAMIENTO[tipo_aloj_lbl]
        with c3:
            noches = st.number_input("Noches de alojamiento", min_value=0, value=1, step=1)
        if viaticos_activos and noches > 0:
            from calculos import calcular_viaticos as _cv
            viat_tot = _cv(True, tipo_aloj, noches, personas)
            alerta(f"Viaticos: {noches} noches × {personas} personas × {numero_completo(VIA_ACT.get(tipo_aloj,145000))} = <strong>{numero_completo(viat_tot)}</strong>", "info")

    st.markdown("---")

    # ── PASO 6: ADICIONALES ──────────────────────────────────────────────────
    seccion_titulo("Paso 6 — Costos adicionales en obra")
    adicionales_activos = st.checkbox("Agregar costos adicionales (silicona, impermeabilizante, etc.)", key="cb_add")
    cantidades_add = []
    if adicionales_activos:
        for i, a in enumerate(ADICIONALES):
            c1, c2 = st.columns([3, 1])
            c1.markdown(f"<div style='font-size:0.85rem;color:{_navy}'>{a['concepto']} — {numero_completo(a.get(etapa, 0))}/{a['unidad']}</div>", unsafe_allow_html=True)
            qty = c2.number_input("Cant.", min_value=0.0, value=0.0, step=1.0, key=f"add_{i}", label_visibility="collapsed")
            cantidades_add.append(qty)
    else:
        cantidades_add = [0.0] * len(ADICIONALES)

    st.markdown("---")

    # ── CALCULAR ─────────────────────────────────────────────────────────────
    col_btn, col_inf = st.columns([1, 3])
    with col_btn:
        calcular = st.button("Calcular cotizacion", type="primary", use_container_width=True)
    with col_inf:
        alerta("Completa todos los pasos y presiona calcular para obtener el costo real y precio sugerido.", "info")

    if calcular or st.session_state.cotizacion:
        if calcular:
            _ml_tot = sum(p.get("ml", 0) for p in st.session_state.get("piezas", []) if isinstance(p, dict))
            _log_ov = st.session_state.get("logistica_custom") or None
            _veh_cu = {**VEHICULOS_CONFIG, **(st.session_state.get("vehiculos_custom") or {})}
            _tar_ov = st.session_state.get("tarifas_custom") or None
            resultado = calcular_cotizacion_directa(
                categoria=cat_sel, referencia=referencia,
                precio_m2=precio_m2, area_placa_comprada=area_placa,
                m2_real=m2_real, m2_cortados=m2_cortados_total,
                m2_usados=m2_usados, margen_pct=margen_pct,
                dias=dias, personas=personas,
                zocalo_activo=zocalo_activo, zocalo_ml=zocalo_ml,
                agente_externo_taller=agente_ext_taller,
                vehiculo_entrega=vehiculo, km=km, num_peajes=peajes,
                foraneo_activo=foraneo_activo, viaticos_activos=viaticos_activos,
                tipo_aloj=tipo_aloj, noches=noches,
                adicionales_activos=adicionales_activos,
                cantidades_add=cantidades_add, etapa=etapa,
                adicionales_lista=ADICIONALES,
                tipo_proyecto=tipo, nombre_cliente=nombre_cliente,
                ml_proyecto=_ml_tot,
                logistica_override=_log_ov,
                vehiculos_custom=_veh_cu,
                tarifas_override=_tar_ov,
            )
            resultado["vehiculo_usado"] = vehiculo
            st.session_state.cotizacion = resultado
            st.session_state.contexto_cot = {"categoria": cat_sel, "referencia": referencia, "tipo_proyecto": tipo, "m2_real": m2_real}
            import random as _rand
            _num_auto = f"COT-{date.today().strftime('%Y%m%d')}-{_rand.randint(100,999)}"
            _guardar_cotizacion(_num_auto, nombre_cliente, resultado)
            if ia_disponible():
                with st.spinner("Analizando resultados con IA..."):
                    st.session_state.resumen_ia = generar_resumen_cotizacion(resultado, st.session_state.contexto_cot)

        r = st.session_state.cotizacion
        st.markdown("---")
        st.markdown(f"<h3 style='color:{_navy};font-family:Playfair Display,serif'>Resultado</h3>", unsafe_allow_html=True)

        hero_banner(
            titulo="Precio de venta sugerido",
            valor_str=numero_completo(r['precio_sugerido']),
            subtitulo=f"Margen: {r['margen_pct']:.0f}%   ·   Utilidad proyectada: {numero_completo(r['utilidad'])}",
            meta=f"{tag('Costo directo: '+numero_completo(r['costo_total']))}"
        )

        col_res, col_det = st.columns([1, 1])
        with col_res:
            st.markdown(f"<div style='font-size:0.8rem;font-weight:700;color:{_gray};text-transform:uppercase;letter-spacing:0.06em;margin-bottom:10px'>Desglose de costos</div>", unsafe_allow_html=True)
            bloque_costos([
                ("Material (area comprada x precio/m²)", r['c1_material']),
                ("Produccion (por metro lineal)",        r['c2_mano_obra']),
                ("Zocalos",                              r['c3_zocalos']),
                ("Insumos (disco + uso de maquina)",     r['c4_insumos']),
                ("Logistica",                            r['c5_logistica']),
                ("Viaticos",                             r['c6_viaticos']),
                ("Adicionales en obra",                  r['c7_adicionales']),
            ], "COSTO TOTAL", r['costo_total'])

        with col_det:
            c1a, c2a = st.columns(2)
            c1a.metric("Aprovechamiento", f"{r['aprovechamiento']:.1f}%", f"Retal: {r['retal']:.3f} m²")
            c2a.metric("Costo/m² instalado", numero_completo(r['costo_total']/r['m2_real']) if r['m2_real'] > 0 else "—")
            c1b, c2b = st.columns(2)
            c1b.metric("Costo total", numero_completo(r['costo_total']))
            c2b.metric("Utilidad", numero_completo(r['utilidad']))

            st.markdown(f"<div style='font-size:0.8rem;font-weight:700;color:{_gray};text-transform:uppercase;letter-spacing:0.06em;margin:14px 0 8px'>Analisis real</div>", unsafe_allow_html=True)
            precio_real = st.number_input("Ingresa el precio que vas a cobrar realmente (opcional)", min_value=0, value=0, step=10_000)
            if precio_real > 0:
                analisis = analizar_precio_real(precio_real, r['costo_total'], r['precio_sugerido'])
                tipo_a = analisis.get("estado", "bajo")
                alerta(f"Margen real: <strong>{analisis['margen_real']:.1f}%</strong> — Utilidad: {numero_completo(analisis['utilidad_real'])} — {'Por encima' if analisis['diferencia']>=0 else 'Por debajo'} del sugerido: {numero_completo(abs(analisis['diferencia']))}", tipo_a)

        if st.session_state.resumen_ia:
            st.markdown("---")
            st.markdown(f"<div style='font-size:0.8rem;font-weight:700;color:{_gray};text-transform:uppercase;letter-spacing:0.06em;margin-bottom:10px'>Analisis IA</div>", unsafe_allow_html=True)
            card(f"<div style='font-size:0.87rem;color:{_navy};line-height:1.65'>{st.session_state.resumen_ia.replace(chr(10),'<br>')}</div>")

        # ── SIMULADOR DE MARGEN ───────────────────────────────────────────────
        st.markdown("---")
        st.markdown(f"<div style='font-size:0.8rem;font-weight:700;color:{_gray};text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px'>Simulador de precio</div>", unsafe_allow_html=True)
        st.caption("Mueve el margen para ver como cambia el precio en tiempo real, sin recalcular.")
        _sim_m = st.slider("Margen de utilidad (%)", 5, 80, int(r["margen_pct"]), 1, key="sim_slider")
        _sim_p = r["costo_total"] / (1 - _sim_m / 100)
        _sim_u = _sim_p - r["costo_total"]
        _ss1, _ss2, _ss3 = st.columns(3)
        _ss1.metric("Precio sugerido", numero_completo(_sim_p), f"{numero_completo(abs(_sim_p - r['precio_sugerido']))} vs calculado")
        _ss2.metric("Utilidad neta", numero_completo(_sim_u))
        _ss3.metric("Margen", f"{_sim_m}%", "Saludable" if _sim_m >= 35 else "Bajo riesgo" if _sim_m < 20 else "Aceptable")
        if _sim_m < 20:
            alerta(f"Con {_sim_m}% de margen estas por debajo del minimo recomendado. Precio de quiebre (20%): {numero_completo(r['costo_total']/0.80)}", "bajo")

        # ── COMPARADOR A/B ─────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown(f"<div style='font-size:0.8rem;font-weight:700;color:{_gray};text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px'>Comparar con otro material</div>", unsafe_allow_html=True)
        _ab_on = st.toggle("Activar comparacion A/B", value=False, key="ab_toggle")
        if _ab_on:
            st.caption("Mismo proyecto, otro material. Compara precios al instante.")
            _ab1, _ab2, _ab3 = st.columns(3)
            _cat_b  = _ab1.selectbox("Material alternativo", [c for c in CATEGORIAS_MATERIAL if c != r["categoria"]], key="ab_cat")
            _prec_b = _ab2.number_input("Precio/m² alternativo", value=float(r["precio_m2"]), min_value=1000.0, step=5_000.0, format="%.0f", key="ab_px")
            _mrgb   = _ab3.slider("Margen alternativo (%)", 5, 80, int(r["margen_pct"]), key="ab_mrg")
            from calculos import calcular_cotizacion_directa as _ccd2
            _rb = _ccd2(
                categoria=_cat_b, referencia=f"{_cat_b} alternativo",
                precio_m2=_prec_b, area_placa_comprada=r["area_placa"],
                m2_real=r["m2_real"], m2_cortados=r.get("m2_cortados", r["m2_real"]),
                m2_usados=r.get("m2_usados", r["m2_real"]), margen_pct=_mrgb,
                dias=r.get("dias",1), personas=r.get("personas",2),
                zocalo_activo=(r["c3_zocalos"]>0), zocalo_ml=0.0,
                agente_externo_taller=(r["c5_detalle"]["agente"]>0),
                vehiculo_entrega=r.get("vehiculo_usado","frontier"), km=0, num_peajes=0,
                foraneo_activo=False, viaticos_activos=False, tipo_aloj="pueblo", noches=0,
                adicionales_activos=False, cantidades_add=[], etapa="terminada", adicionales_lista=ADICIONALES,
                ml_proyecto=r.get("ml_proyecto", r["m2_real"]/0.60),
            )
            _cA, _cB = st.columns(2)
            with _cA:
                st.markdown(f"<div style='background:{_blue};color:white;padding:8px 14px;border-radius:6px;font-weight:700;margin-bottom:8px'>{r['categoria']} (actual)</div>", unsafe_allow_html=True)
                bloque_costos([("Material",r["c1_material"]),("Produccion",r["c2_mano_obra"]),("Insumos",r["c4_insumos"]),("Logistica",r["c5_logistica"])],"PRECIO SUGERIDO",r["precio_sugerido"])
            with _cB:
                st.markdown(f"<div style='background:{_gold};color:{_navy};padding:8px 14px;border-radius:6px;font-weight:700;margin-bottom:8px'>{_cat_b} (alternativo)</div>", unsafe_allow_html=True)
                bloque_costos([("Material",_rb["c1_material"]),("Produccion",_rb["c2_mano_obra"]),("Insumos",_rb["c4_insumos"]),("Logistica",_rb["c5_logistica"])],"PRECIO SUGERIDO",_rb["precio_sugerido"])
            _diff = _rb["precio_sugerido"] - r["precio_sugerido"]
            alerta(f"El {_cat_b} resulta {numero_completo(abs(_diff))} {'mas caro' if _diff > 0 else 'mas economico'} que el {r['categoria']} para este proyecto.", "info")

        # ── EXPORTAR PDF ─────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown(f"<h4 style='color:{_navy}'>Exportar documentos</h4>", unsafe_allow_html=True)

        from generador_pdf import generar_pdf_cotizacion, generar_cuenta_cobro

        colp1, colp2 = st.columns(2)
        with colp1:
            st.markdown(f"<div style='font-size:0.85rem;font-weight:600;color:{_navy};margin-bottom:8px'>Cotizacion PDF</div>", unsafe_allow_html=True)
            num_cot = st.text_input("Numero de cotizacion", value=f"COT-{__import__('datetime').date.today().strftime('%Y')}-001", key="num_cot")
            logo_custom = st.session_state.logo_bytes
            emp_info = st.session_state.empresa_info
            if st.button("Generar PDF de cotizacion", type="primary", use_container_width=True):
                pdf_bytes = generar_pdf_cotizacion(r, numero=num_cot, empresa_info=emp_info, logo_bytes=logo_custom)
                nombre_pdf = f"{num_cot}_{nombre_cliente.replace(' ','_') if nombre_cliente else 'cotizacion'}.pdf"
                st.download_button("Descargar cotizacion PDF", pdf_bytes, file_name=nombre_pdf, mime="application/pdf", use_container_width=True)

        with colp2:
            st.markdown(f"<div style='font-size:0.85rem;font-weight:600;color:{_navy};margin-bottom:8px'>Cuenta de cobro PDF</div>", unsafe_allow_html=True)
            num_cc = st.text_input("Numero de cuenta de cobro", value=f"CC-{__import__('datetime').date.today().strftime('%Y')}-001", key="num_cc")
            nom_pag = st.text_input("Nombre de quien paga", value=nombre_cliente, key="nom_pag")
            nit_pag = st.text_input("NIT / CC de quien paga", value="", key="nit_pag")
            dir_pag = st.text_input("Direccion del pagador", value="", key="dir_pag")
            if st.button("Generar cuenta de cobro PDF", type="primary", use_container_width=True):
                datos_prest = emp_info.copy()
                datos_prest["nit_cc"] = emp_info.get("nit", "")
                datos_prest["direccion"] = emp_info.get("ciudad", "")
                datos_prest["telefono"] = emp_info.get("tel", "")
                datos_pag = {"nombre": nom_pag, "nit": nit_pag, "direccion": dir_pag}
                cc_bytes = generar_cuenta_cobro(r, datos_prest, datos_pag, numero=num_cc, logo_bytes=logo_custom)
                nombre_cc = f"{num_cc}_{nom_pag.replace(' ','_') if nom_pag else 'cuenta_cobro'}.pdf"
                st.download_button("Descargar cuenta de cobro PDF", cc_bytes, file_name=nombre_cc, mime="application/pdf", use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# COTIZACIÓN AIU
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Cotizacion AIU":
    st.markdown(f"<h2 style='color:{_text_main};font-family:Playfair Display,serif'>Cotizacion AIU</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:{_text_sub};font-size:0.88rem'>Para constructoras y licitaciones — estructura formal colombiana A+I+U+IVA</p>", unsafe_allow_html=True)

    LOG_ACT = get_logistica()
    VIA_ACT = get_viaticos()

    alerta("<strong>Estructura AIU:</strong> A = Administracion (2%) + I = Imprevistos (2%) + U = Utilidad (5%) + IVA 19% solo sobre Utilidad. Todo sobre el Costo Directo.", "info")

    # ── Items ────────────────────────────────────────────────────────────────
    seccion_titulo("Items del contrato")

    hdr = st.columns([4, 1, 1, 2, 0.5])
    for col, lbl in zip(hdr, ["Descripcion", "Unidad", "Cantidad", "Precio unitario (COP)", ""]):
        col.markdown(f"<div style='font-size:0.72rem;font-weight:700;color:{_gray};text-transform:uppercase;letter-spacing:0.06em;padding:4px 0'>{lbl}</div>", unsafe_allow_html=True)

    nuevos_items = []
    cd_total = 0.0
    for idx, it in enumerate(st.session_state.aiu_items):
        c0, c1, c2, c3, c4 = st.columns([4, 1, 1, 2, 0.5])
        desc   = c0.text_input("Desc", value=it["desc"], key=f"aiu_d_{idx}", label_visibility="collapsed")
        und    = c1.text_input("Und",  value=it["und"],  key=f"aiu_u_{idx}", label_visibility="collapsed")
        cant   = c2.number_input("Cant", value=float(it["cant"]), min_value=0.0, step=1.0, key=f"aiu_c_{idx}", label_visibility="collapsed")
        punit  = c3.number_input("PU", value=float(it["punit"]), min_value=0.0, step=5_000.0, key=f"aiu_p_{idx}", label_visibility="collapsed")
        sub    = cant * punit
        cd_total += sub
        c0.markdown(f"<div style='font-size:0.72rem;color:{_gray}'>Subtotal: {numero_completo(sub)}</div>", unsafe_allow_html=True)
        if c4.button("X", key=f"aiu_del_{idx}") and len(st.session_state.aiu_items) > 1:
            st.session_state.aiu_items.pop(idx)
            st.rerun()
        nuevos_items.append({"desc": desc, "und": und, "cant": cant, "punit": punit})
    st.session_state.aiu_items = nuevos_items

    if st.button("+ Agregar item"):
        st.session_state.aiu_items.append({"desc": "Nuevo item", "und": "glb", "cant": 1.0, "punit": 100_000})
        st.rerun()

    st.markdown(f"<div style='font-weight:700;color:{_navy};margin:10px 0'>Costo Directo: {numero_completo(cd_total)}</div>", unsafe_allow_html=True)
    st.markdown("---")

    # ── Porcentajes AIU ──────────────────────────────────────────────────────
    seccion_titulo("Porcentajes AIU")
    c1, c2, c3 = st.columns(3)
    with c1:
        pct_a = st.number_input("Administracion (%)", value=AIU_DEFAULTS["a"], min_value=0.0, max_value=20.0, step=0.5, format="%.1f")
    with c2:
        pct_i = st.number_input("Imprevistos (%)", value=AIU_DEFAULTS["i"], min_value=0.0, max_value=20.0, step=0.5, format="%.1f")
    with c3:
        pct_u = st.number_input("Utilidad (%)", value=AIU_DEFAULTS["u"], min_value=0.0, max_value=30.0, step=0.5, format="%.1f")

    st.markdown("---")
    seccion_titulo("Logistica")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        veh_aiu_lbl = st.selectbox("Vehiculo", list(VEHICULOS.keys()), key="aiu_veh")
        vehiculo_aiu = VEHICULOS[veh_aiu_lbl]
    with c2:
        km_aiu = st.number_input("Km", min_value=0.0, value=10.0, step=1.0, key="aiu_km")
    with c3:
        peajes_aiu = st.number_input("Peajes", min_value=0, value=0, step=1, key="aiu_pj")
    with c4:
        agente_aiu = st.checkbox("Agente externo al taller", key="aiu_ag")

    foraneo_aiu = st.checkbox("Proyecto foraneo", key="aiu_for")
    tipo_aloj_aiu = "pueblo"
    noches_aiu = 0
    pers_aiu = 2
    if foraneo_aiu:
        c1, c2, c3 = st.columns(3)
        tipo_aloj_aiu = ALOJAMIENTO[c1.selectbox("Destino", list(ALOJAMIENTO.keys()), key="aiu_aloj")]
        noches_aiu = c2.number_input("Noches", min_value=0, value=1, step=1, key="aiu_noch")
        pers_aiu = c3.number_input("Personas", min_value=1, value=2, step=1, key="aiu_per")

    if st.button("Calcular AIU", type="primary"):
        from calculos import calcular_aiu as _calc_aiu
        res_aiu = _calc_aiu(cd_total, pct_a, pct_i, pct_u, vehiculo_aiu, km_aiu, peajes_aiu,
                            agente_aiu, foraneo_aiu, tipo_aloj_aiu, noches_aiu, pers_aiu)

        hero_banner("Precio total del contrato", numero_completo(res_aiu['precio_total']),
            f"Margen efectivo: {res_aiu['margen_pct']:.1f}%   ·   CD: {numero_completo(cd_total)}")

        # Guardar en historial
        _aiu_num = f"AIU-{__import__('datetime').date.today().strftime('%Y%m%d')}-001"
        _aiu_r = {
            "categoria": "Proyecto AIU", "referencia": "Constructora/Licitación",
            "tipo_proyecto": "AIU", "nombre_cliente": "—",
            "m2_real": 0, "ml_proyecto": 0,
            "costo_total": cd_total, "precio_sugerido": res_aiu["precio_total"],
            "margen_pct": res_aiu["margen_pct"], "utilidad": res_aiu["val_u"],
            "c1_material": cd_total, "c2_mano_obra": 0,
            "c3_zocalos": 0, "c4_insumos": 0,
            "c5_logistica": res_aiu["logistica"], "c6_viaticos": res_aiu["viaticos"],
            "c7_adicionales": 0,
            "pct_a": pct_a, "pct_i": pct_i, "pct_u": pct_u,
            "val_a": res_aiu["val_a"], "val_i": res_aiu["val_i"],
            "val_u": res_aiu["val_u"], "val_iva": res_aiu["val_iva"],
            "aiu_items": st.session_state.aiu_items,
        }
        try:
            _guardar_cotizacion(_aiu_num, "Proyecto AIU", _aiu_r)
        except Exception:
            pass

        bloque_costos([
            ("Costo Directo (CD)",   res_aiu['cd']),
            (f"A — Administracion ({pct_a:.1f}%)", res_aiu['val_a']),
            (f"I — Imprevistos ({pct_i:.1f}%)",    res_aiu['val_i']),
            (f"U — Utilidad ({pct_u:.1f}%)",       res_aiu['val_u']),
            ("IVA 19% sobre Utilidad",             res_aiu['val_iva']),
            ("Logistica",                          res_aiu['logistica']),
            ("Viaticos",                           res_aiu['viaticos']),
        ], "PRECIO TOTAL DEL CONTRATO", res_aiu['precio_total'])


# ═══════════════════════════════════════════════════════════════════════════════
# PARAMETROS
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Historial":
    st.markdown(f"<h2 style='color:{_text_main};font-family:Playfair Display,serif'>Historial de Cotizaciones</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:{_text_sub};font-size:0.88rem'>Todas las cotizaciones guardadas. Haz clic en una fila para ver el detalle completo y editar.</p>", unsafe_allow_html=True)

    _hc1, _hc2 = st.columns([3, 1])
    _bus = _hc1.text_input("Buscar", placeholder="Cliente, número o material...", key="hist_bus")
    _filtro_est = _hc2.selectbox("Filtrar por estado", ["Todos", "Pendiente", "Aprobada", "Rechazada", "En revision"], key="hist_fest")

    _rows = _listar_cotizaciones(_bus)
    if _filtro_est != "Todos":
        _rows = [r for r in _rows if r[8] == _filtro_est]

    if not _rows:
        alerta("Aún no hay cotizaciones. Genera una y se guardará automáticamente.", "info")
    else:
        _ESTADOS = ["Pendiente", "Aprobada", "Rechazada", "En revision"]

        # ── Lista de cotizaciones ────────────────────────────────────────────
        _hdr = st.columns([0.4, 1.5, 1.1, 2.5, 1.4, 1, 1.3, 1.1, 1.3, 0.8])
        for _col, _lbl in zip(_hdr, ["#", "Número", "Fecha", "Cliente", "Material", "ML", "Precio", "Margen", "Estado", "Ver"]):
            _col.markdown(f"<div style='font-size:0.7rem;font-weight:700;color:{_text_sub};text-transform:uppercase;letter-spacing:0.06em'>{_lbl}</div>", unsafe_allow_html=True)
        st.markdown(f"<hr style='margin:4px 0 6px;border-color:{_border}'>", unsafe_allow_html=True)

        for _row in _rows:
            _rid, _rnum, _rfec, _rcli, _rmat, _rml, _rpre, _rmrg, _rest = _row
            _cs = st.columns([0.4, 1.5, 1.1, 2.5, 1.4, 1, 1.3, 1.1, 1.3, 0.8])
            _cs[0].markdown(f"<span style='font-size:0.78rem;color:{_text_sub}'>{_rid}</span>", unsafe_allow_html=True)
            _cs[1].markdown(f"<span style='font-size:0.8rem;color:{_text_main}'>{_rnum}</span>", unsafe_allow_html=True)
            _cs[2].markdown(f"<span style='font-size:0.78rem;color:{_text_sub}'>{_rfec}</span>", unsafe_allow_html=True)
            _cs[3].markdown(f"<span style='font-size:0.85rem;font-weight:600;color:{_text_main}'>{_rcli}</span>", unsafe_allow_html=True)
            _cs[4].markdown(f"<span style='font-size:0.8rem;color:{_text_main}'>{_rmat}</span>", unsafe_allow_html=True)
            _cs[5].markdown(f"<span style='font-size:0.8rem;color:{_text_main}'>{(_rml or 0):.1f} ml</span>", unsafe_allow_html=True)
            _cs[6].markdown(f"<span style='font-size:0.82rem;font-weight:700;color:{_text_main}'>{numero_completo(_rpre)}</span>", unsafe_allow_html=True)
            _mrg_c = "#4ADE80" if (_rmrg >= 35 and _dm) else "#0A6E3F" if _rmrg >= 35 else "#FCD34D" if (_rmrg >= 20 and _dm) else "#92580A" if _rmrg >= 20 else "#F87171" if _dm else "#981520"
            _cs[7].markdown(f"<span style='font-size:0.82rem;font-weight:700;color:{_mrg_c}'>{_rmrg:.0f}%</span>", unsafe_allow_html=True)
            _est_sel = _cs[8].selectbox("Estado", _ESTADOS, index=_ESTADOS.index(_rest) if _rest in _ESTADOS else 0, key=f"est_{_rid}", label_visibility="collapsed")
            if _est_sel != _rest:
                _actualizar_estado(_rid, _est_sel)
                st.rerun()
            if _cs[9].button("👁", key=f"ver_{_rid}", help="Ver detalle completo"):
                st.session_state.hist_detalle_id = _rid
                # Try to load datos_json from DB
                try:
                    import psycopg2 as _pg2
                    _conn = _pg2.connect(st.secrets["DATABASE_URL"])
                    _cur  = _conn.cursor()
                    _cur.execute("SELECT datos_json FROM cotizaciones WHERE id=%s", (_rid,))
                    _row_json = _cur.fetchone()
                    _cur.close(); _conn.close()
                    if _row_json and _row_json[0]:
                        st.session_state.hist_detalle_datos = json.loads(_row_json[0])
                    else:
                        st.session_state.hist_detalle_datos = {"numero": _rnum, "nombre_cliente": _rcli, "categoria": _rmat, "ml_proyecto": _rml, "precio_sugerido": _rpre, "margen_pct": _rmrg}
                except Exception:
                    st.session_state.hist_detalle_datos = {"numero": _rnum, "nombre_cliente": _rcli, "categoria": _rmat, "ml_proyecto": _rml, "precio_sugerido": _rpre, "margen_pct": _rmrg}
                st.rerun()

        st.caption(f"{len(_rows)} cotizaciones")

    # ── PANEL DETALLE ────────────────────────────────────────────────────────
    if st.session_state.get("hist_detalle_id") and st.session_state.get("hist_detalle_datos"):
        _d = st.session_state.hist_detalle_datos
        st.markdown("---")
        _dc1, _dc2 = st.columns([0.04, 0.96])
        _dc2.markdown(f"<h3 style='color:{_text_main};font-family:Playfair Display,serif'>Detalle — {_d.get('numero', 'Cotización')}</h3>", unsafe_allow_html=True)
        if st.button("✕ Cerrar detalle", key="hist_cerrar_det"):
            st.session_state.hist_detalle_id = None
            st.session_state.hist_detalle_datos = None
            st.rerun()

        _dd1, _dd2 = st.columns(2)
        with _dd1:
            card(f"""
            <div style="color:{_text_sub};font-size:0.75rem;text-transform:uppercase;letter-spacing:0.07em;margin-bottom:10px">Información del proyecto</div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
              <div><div style="font-size:0.72rem;color:{_text_sub}">Cliente</div><div style="font-weight:700;color:{_text_main}">{_d.get('nombre_cliente','—')}</div></div>
              <div><div style="font-size:0.72rem;color:{_text_sub}">Material</div><div style="font-weight:700;color:{_text_main}">{_d.get('categoria','—')} — {_d.get('referencia','—')}</div></div>
              <div><div style="font-size:0.72rem;color:{_text_sub}">Tipo de proyecto</div><div style="font-weight:700;color:{_text_main}">{_d.get('tipo_proyecto','—')}</div></div>
              <div><div style="font-size:0.72rem;color:{_text_sub}">Metros lineales</div><div style="font-weight:700;color:{_text_main}">{(_d.get('ml_proyecto') or 0):.2f} ml</div></div>
              <div><div style="font-size:0.72rem;color:{_text_sub}">Área material</div><div style="font-weight:700;color:{_text_main}">{(_d.get('m2_real') or 0):.3f} m²</div></div>
              <div><div style="font-size:0.72rem;color:{_text_sub}">Precio/m²</div><div style="font-weight:700;color:{_text_main}">{numero_completo(_d.get('precio_m2') or 0)}</div></div>
            </div>""")
        with _dd2:
            _dmc = "#4ADE80" if (_d.get("margen_pct",0) >= 35 and _dm) else "#0A6E3F" if _d.get("margen_pct",0) >= 35 else "#FCD34D" if (_d.get("margen_pct",0) >= 20 and _dm) else "#92580A" if _d.get("margen_pct",0) >= 20 else "#F87171" if _dm else "#981520"
            card(f"""
            <div style="color:{_text_sub};font-size:0.75rem;text-transform:uppercase;letter-spacing:0.07em;margin-bottom:10px">Resultados financieros</div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
              <div><div style="font-size:0.72rem;color:{_text_sub}">Costo total</div><div style="font-weight:700;color:{_text_main}">{numero_completo(_d.get('costo_total') or 0)}</div></div>
              <div><div style="font-size:0.72rem;color:{_text_sub}">Precio sugerido</div><div style="font-size:1.1rem;font-weight:900;color:{_text_main}">{numero_completo(_d.get('precio_sugerido') or 0)}</div></div>
              <div><div style="font-size:0.72rem;color:{_text_sub}">Utilidad</div><div style="font-weight:700;color:{_text_main}">{numero_completo(_d.get('utilidad') or 0)}</div></div>
              <div><div style="font-size:0.72rem;color:{_text_sub}">Margen</div><div style="font-size:1.2rem;font-weight:900;color:{_dmc}">{(_d.get('margen_pct') or 0):.0f}%</div></div>
            </div>""")

        # Desglose de costos si disponible
        if _d.get("c1_material"):
            st.markdown(f"<div style='font-size:0.78rem;font-weight:700;color:{_text_sub};text-transform:uppercase;letter-spacing:0.07em;margin:14px 0 8px'>Desglose de costos</div>", unsafe_allow_html=True)
            bloque_costos([
                ("① Material", _d.get("c1_material", 0)),
                ("② Producción (mano de obra)", _d.get("c2_mano_obra", 0)),
                ("③ Zócalos", _d.get("c3_zocalos", 0)),
                ("④ Insumos (disco + maquinaria)", _d.get("c4_insumos", 0)),
                ("⑤ Logística y transporte", _d.get("c5_logistica", 0)),
                ("⑥ Viáticos", _d.get("c6_viaticos", 0)),
                ("⑦ Adicionales en obra", _d.get("c7_adicionales", 0)),
            ], "COSTO TOTAL DIRECTO", _d.get("costo_total", 0))

        # Re-generar PDF desde historial
        st.markdown(f"<div style='margin-top:16px'></div>", unsafe_allow_html=True)
        _pf1, _pf2 = st.columns(2)
        with _pf1:
            if _d.get("precio_sugerido", 0) > 0:
                _num_hist = st.text_input("Número de cotización PDF", value=_d.get("numero","COT-001"), key="hist_num_cot_pdf")
                if st.button("📄 Generar cotización PDF", type="primary", use_container_width=True, key="hist_gen_cot"):
                    from generador_pdf import generar_pdf_cotizacion
                    _pdf_h = generar_pdf_cotizacion(
                        _d, numero=_num_hist,
                        empresa_info=st.session_state.empresa_info,
                        logo_bytes=st.session_state.logo_bytes
                    )
                    st.download_button("⬇ Descargar cotización", _pdf_h,
                        file_name=f"{_num_hist}.pdf", mime="application/pdf",
                        use_container_width=True, key="hist_dl_cot")
        with _pf2:
            if _d.get("precio_sugerido", 0) > 0:
                _num_cc_h = st.text_input("Número de cuenta de cobro", value=_d.get("numero","CC-001").replace("COT","CC"), key="hist_num_cc_pdf")
                _nom_pag_h = st.text_input("Nombre de quien paga", value=_d.get("nombre_cliente",""), key="hist_nom_pag")
                _nit_pag_h = st.text_input("NIT / CC del pagador", value="", key="hist_nit_pag")
                if st.button("📄 Generar cuenta de cobro", type="primary", use_container_width=True, key="hist_gen_cc"):
                    from generador_pdf import generar_cuenta_cobro
                    _prest_h = {**st.session_state.empresa_info, "nit_cc": st.session_state.empresa_info.get("nit","")}
                    _pag_h   = {"nombre": _nom_pag_h, "nit": _nit_pag_h}
                    _cc_h = generar_cuenta_cobro(_d, _prest_h, _pag_h, numero=_num_cc_h, logo_bytes=st.session_state.logo_bytes)
                    st.download_button("⬇ Descargar cuenta de cobro", _cc_h,
                        file_name=f"{_num_cc_h}.pdf", mime="application/pdf",
                        use_container_width=True, key="hist_dl_cc")

elif pagina == "Dashboard":
    st.markdown(f"<h2 style='color:{_text_main};font-family:Playfair Display,serif'>Dashboard Gerencial</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:{_text_sub};font-size:0.88rem'>Metricas de tu negocio en tiempo real.</p>", unsafe_allow_html=True)
    _s = _stats_db()
    if _s["total"] == 0:
        alerta("Genera cotizaciones para ver las metricas aqui.", "info")
    else:
        _m1, _m2, _m3, _m4 = st.columns(4)
        _m1.metric("Total cotizaciones", _s["total"])
        _m2.metric("Aprobadas", _s["aprobadas"])
        _m3.metric("Pendientes", _s["pendientes"])
        _m4.metric("Facturacion (aprobadas)", numero_completo(_s["facturacion"]))
        st.markdown("---")
        _da, _db = st.columns(2)
        with _da:
            st.markdown(f"<div style='font-size:0.8rem;font-weight:700;color:{_gray};text-transform:uppercase;margin-bottom:8px'>Por material</div>", unsafe_allow_html=True)
            for _mat, _cnt, _mrg, _tot in (_s["por_material"] or []):
                _pct = min(100, (_tot / max(_s["facturacion"], 1)) * 100)
                st.markdown(
                    f'<div style="margin-bottom:10px"><div style="display:flex;justify-content:space-between;font-size:0.82rem">'
                    f'<span style="font-weight:600;color:{_navy}">{_mat}</span>'
                    f'<span style="color:{_gray}">{_cnt} cot. · {_mrg:.0f}% margen</span></div>'
                    f'<div style="background:{_gray_l};border-radius:4px;height:5px;margin-top:3px">'
                    f'<div style="background:{_blue};width:{_pct:.0f}%;height:5px;border-radius:4px"></div></div>'
                    f'<div style="font-size:0.76rem;color:{_gray};margin-top:2px">{numero_completo(_tot)}</div></div>',
                    unsafe_allow_html=True)
        with _db:
            st.markdown(f"<div style='font-size:0.8rem;font-weight:700;color:{_gray};text-transform:uppercase;margin-bottom:8px'>Ultimos 6 meses</div>", unsafe_allow_html=True)
            for _mes, _cnt, _tot in (_s["por_mes"] or []):
                _pct = min(100, (_tot / max(_s["facturacion"], 1)) * 100) if _s["facturacion"] > 0 else 0
                st.markdown(
                    f'<div style="margin-bottom:10px"><div style="display:flex;justify-content:space-between;font-size:0.82rem">'
                    f'<span style="font-weight:600;color:{_navy}">{_mes}</span>'
                    f'<span style="color:{_gray}">{_cnt} cotizaciones</span></div>'
                    f'<div style="background:{_gray_l};border-radius:4px;height:5px;margin-top:3px">'
                    f'<div style="background:{_gold};width:{_pct:.0f}%;height:5px;border-radius:4px"></div></div>'
                    f'<div style="font-size:0.76rem;color:{_gray};margin-top:2px">{numero_completo(_tot)}</div></div>',
                    unsafe_allow_html=True)
        st.markdown("---")
        _mc = "#0A6E3F" if _s["margen_prom"] >= 35 else "#92580A" if _s["margen_prom"] >= 20 else "#981520"
        st.markdown(
            f'<div style="background:{_blue_ul};border:1px solid {_blue_l};border-radius:10px;padding:16px 24px;display:inline-block">'
            f'<div style="font-size:2.4rem;font-weight:900;color:{_mc};font-family:Playfair Display,serif">{_s["margen_prom"]:.1f}%</div>'
            f'<div style="font-size:0.8rem;color:{_gray}">margen promedio en aprobadas</div></div>',
            unsafe_allow_html=True)

elif pagina == "Parametros":
    st.markdown(f"<h2 style='color:{_text_main};font-family:Playfair Display,serif'>Parametros de costos</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:{_text_sub};font-size:0.88rem;margin-bottom:4px'>Edita directamente los valores o deja que la IA te guie. Los cambios aplican inmediatamente a todos los calculos.</p>", unsafe_allow_html=True)

    # ── Inicializar custom params desde defaults si no existen ────────────────
    import copy
    if st.session_state.tarifas_custom is None:
        st.session_state.tarifas_custom = copy.deepcopy(TARIFAS)
    if st.session_state.logistica_custom is None:
        st.session_state.logistica_custom = copy.deepcopy(LOGISTICA)
    if st.session_state.viaticos_custom is None:
        st.session_state.viaticos_custom = copy.deepcopy(VIATICOS)

    TAR  = st.session_state.tarifas_custom
    LOG  = st.session_state.logistica_custom
    VIA  = st.session_state.viaticos_custom

    # ── Barra de acciones ─────────────────────────────────────────────────────
    col_act1, col_act2, col_act3 = st.columns([2, 2, 3])
    with col_act1:
        if st.button("Restaurar valores originales", use_container_width=True):
            st.session_state.tarifas_custom   = copy.deepcopy(TARIFAS)
            st.session_state.logistica_custom = copy.deepcopy(LOGISTICA)
            st.session_state.viaticos_custom  = copy.deepcopy(VIATICOS)
            st.success("Valores restaurados.")
            st.rerun()
    with col_act2:
        _cambios = (
            st.session_state.tarifas_custom != TARIFAS or
            st.session_state.logistica_custom != LOGISTICA or
            st.session_state.viaticos_custom  != VIATICOS
        )
        if _cambios:
            alerta("Tienes parametros personalizados activos — todos los calculos usan estos valores.", "bueno")
        else:
            alerta("Usando valores por defecto.", "info")

    st.markdown("---")

    # ═══ TABS ═════════════════════════════════════════════════════════════════
    t_ia, t1, t2, t3, t4 = st.tabs([
        "Asistente IA",
        "Costos de produccion",
        "Logistica",
        "Viaticos",
        "Mis vehiculos",
    ])

    # ── TAB: ASISTENTE IA ─────────────────────────────────────────────────────
    with t_ia:
        st.markdown(f"<p style='color:{_gray};font-size:0.85rem;margin-bottom:12px'>Describe tus costos reales y la IA actualiza los parametros automaticamente conforme conversas.</p>", unsafe_allow_html=True)

        if not ia_disponible():
            alerta("Configura tu API key de Anthropic para usar el asistente (ver barra lateral).", "acepta")
        else:
            alerta("La IA detecta los valores que menciones y los aplica en tiempo real. Puedes hablar de gasolina, rendimiento de tus vehiculos, tarifas de mano de obra, viaticos, etc.", "info")

        # Chat display
        chat_wizard = st.session_state.get("params_wizard_chat", [])
        chat_html = f'<div style="background:{_blue_ul};border:1px solid {_blue_l};border-radius:10px;padding:14px;max-height:380px;overflow-y:auto;margin-bottom:10px">'
        if not chat_wizard:
            chat_html += (
                f'<div style="background:{_navy};color:rgba(255,255,255,0.87);padding:12px 16px;'
                f'border-radius:4px 14px 14px 14px;font-size:0.87rem;line-height:1.65;max-width:92%">'
                f'Hola. Soy tu asistente de parametros.<br><br>'
                f'Cuéntame un valor que quieras actualizar y lo aplico de inmediato. Por ejemplo:<br>'
                f'<strong>· "La gasolina está a $16.200 el galón"</strong><br>'
                f'<strong>· "El flete a clientes nos cuesta $180.000"</strong><br>'
                f'<strong>· "La mano de obra de mármol subió a $80.000/m²"</strong><br><br>'
                f'¿Por donde empezamos?'
                f'</div>'
            )
        for _msg in chat_wizard:
            if _msg["role"] == "user":
                chat_html += (f'<div style="background:{_blue};color:white;padding:10px 14px;'
                    f'border-radius:14px 4px 14px 14px;font-size:0.87rem;max-width:85%;'
                    f'margin-left:auto;text-align:right;margin-top:10px">{_msg["content"]}</div>')
            else:
                _ct = _msg["content"].replace("\n", "<br>")
                chat_html += (f'<div style="background:{_navy};color:rgba(255,255,255,0.87);padding:12px 16px;'
                    f'border-radius:4px 14px 14px 14px;font-size:0.87rem;line-height:1.65;'
                    f'max-width:92%;margin-top:10px">{_ct}</div>')
        chat_html += '</div>'
        st.markdown(chat_html, unsafe_allow_html=True)

        with st.form("wizard_params_form", clear_on_submit=True):
            _c1, _c2 = st.columns([5, 1])
            _msg_w  = _c1.text_input("msg", label_visibility="collapsed",
                placeholder='Ej: "La gasolina está a $16.500 el galón"')
            _send_w = _c2.form_submit_button("Enviar", use_container_width=True)

        if _send_w and _msg_w.strip():
            chat_wizard.append({"role": "user", "content": _msg_w.strip()})

            # ── Llamada IA con extraccion de JSON de valores ──────────────────
            try:
                import anthropic as _ant, json as _json
                _client = _ant.Anthropic(api_key=st.secrets.get("ANTHROPIC_API_KEY",""))

                _SYSTEM = """Eres el asistente de parámetros de una calculadora de costos de marmolería en Colombia.
Tu trabajo: detectar valores numéricos en el mensaje del usuario y actualizar los parámetros correspondientes.

PARÁMETROS DISPONIBLES (usa exactamente estos nombres de clave):
- gasolina: precio COP por galón de gasolina corriente
- frontier_rend: km por galón Frontier NP300
- frontier_desgaste: COP por km de desgaste Frontier
- frontier_base: flete base Frontier por viaje
- cheyenne_rend: km por galón Cheyenne V8
- cheyenne_desgaste: COP por km de desgaste Cheyenne
- cheyenne_base: flete base Cheyenne por viaje
- flete_externo: tarifa fija flete externo/tercero
- flete_agente: flete agente externo (proveedor→taller)
- peaje: valor peaje ida+vuelta
- herram: desgaste herramientas por viaje
- viaticos_pueblo: tarifa por noche/persona en pueblo
- viaticos_ciudad: tarifa por noche/persona en ciudad
COSTOS DE PRODUCCIÓN (se paga por metro lineal, no por hora):
- marmol_prod_ml: COP que le pagas al operario por cada ml cortado e instalado en mármol
- marmol_zocalo: COP/ml de zócalo en mármol
- marmol_disco: COP/m² de disco en mármol
- marmol_maquina: COP/día de máquina en mármol
- granito_prod_ml, granito_zocalo, granito_disco, granito_maquina
- sinterizado_prod_ml, sinterizado_zocalo, sinterizado_disco, sinterizado_maquina
- quarztone_prod_ml, quarztone_zocalo, quarztone_disco, quarztone_maquina
- cuarcita_prod_ml, cuarcita_zocalo, cuarcita_disco, cuarcita_maquina

RESPONDE SIEMPRE en este formato JSON exacto:
{
  "actualizados": {"clave": valor_numerico, ...},
  "mensaje": "Texto de confirmacion corto para el usuario. Menciona los valores que aplicaste."
}

Si el usuario no menciona ningún valor numérico actualizable, deja "actualizados" vacío {} y responde con orientación.
SOLO JSON, sin texto antes ni después."""

                _messages = [{"role": m["role"], "content": m["content"]} for m in chat_wizard]
                _resp = _client.messages.create(
                    model="claude-opus-4-6",
                    max_tokens=500,
                    system=_SYSTEM,
                    messages=_messages,
                )
                _raw = _resp.content[0].text.strip()
                if _raw.startswith("```"):
                    _raw = _raw.split("```")[1]
                    if _raw.startswith("json"): _raw = _raw[4:]
                _data = _json.loads(_raw.strip())
            except Exception as _e:
                _data = {"actualizados": {}, "mensaje": f"Error al procesar: {str(_e)}"}

            # ── Aplicar valores extraidos a session_state ─────────────────────
            _aplicados = []
            _act = _data.get("actualizados", {})

            # Gasolina
            if "gasolina" in _act:
                st.session_state.logistica_custom["gasolina"] = float(_act["gasolina"])
                _aplicados.append(f"Gasolina: {numero_completo(_act['gasolina'])}/galon")

            # Vehiculos
            for _veh in ["frontier", "cheyenne"]:
                for _campo, _key in [("rend",f"{_veh}_rend"),("desgaste",f"{_veh}_desgaste"),("base",f"{_veh}_base")]:
                    if _key in _act:
                        st.session_state.logistica_custom[_veh][_campo] = float(_act[_key])
                        _aplicados.append(f"{_veh.capitalize()} {_campo}: {_act[_key]}")

            # Logistica general
            for _lk, _lpath in [
                ("flete_externo", ("externo","flete")),
                ("flete_agente",  None),
                ("peaje",         None),
                ("herram",        None),
            ]:
                if _lk in _act:
                    if _lpath:
                        st.session_state.logistica_custom[_lpath[0]][_lpath[1]] = float(_act[_lk])
                    else:
                        st.session_state.logistica_custom[_lk.replace("flete_","")] = float(_act[_lk])
                    _aplicados.append(f"{_lk}: {numero_completo(_act[_lk])}")

            # Viaticos
            if "viaticos_pueblo" in _act:
                st.session_state.viaticos_custom["pueblo"] = float(_act["viaticos_pueblo"])
                _aplicados.append(f"Viaticos pueblo: {numero_completo(_act['viaticos_pueblo'])}")
            if "viaticos_ciudad" in _act:
                st.session_state.viaticos_custom["ciudad"] = float(_act["viaticos_ciudad"])
                _aplicados.append(f"Viaticos ciudad: {numero_completo(_act['viaticos_ciudad'])}")

            # Tarifas por material
            _mat_map = {
                "Mármol": "marmol", "Granito": "granito",
                "Sinterizado": "sinterizado", "Quarztone": "quarztone", "Cuarcita": "cuarcita"
            }
            _campo_map = {"prod_ml":"prod_ml","zocalo":"zocalo","disco":"disco","maquina":"maquina"}
            for _mat_nombre, _mat_key in _mat_map.items():
                for _campo_key in _campo_map:
                    _full_key = f"{_mat_key}_{_campo_key}"
                    if _full_key in _act:
                        st.session_state.tarifas_custom[_mat_nombre][_campo_key] = float(_act[_full_key])
                        _aplicados.append(f"{_mat_nombre} {_campo_key}: {numero_completo(_act[_full_key])}")

            # Mensaje de respuesta
            _msg_resp = _data.get("mensaje", "Listo.")
            if _aplicados:
                _msg_resp += f" Aplicado: {', '.join(_aplicados[:3])}{'...' if len(_aplicados)>3 else '.' }"

            chat_wizard.append({"role": "assistant", "content": _msg_resp})
            st.session_state.params_wizard_chat = chat_wizard
            st.rerun()

        col_w1, col_w2 = st.columns(2)
        with col_w1:
            if st.button("Limpiar conversacion", use_container_width=True):
                st.session_state.params_wizard_chat = []
                st.rerun()
        with col_w2:
            st.caption("Los cambios se aplican inmediatamente y se reflejan en las tabs de abajo.")

    # ── TAB: TARIFAS DE TRABAJO ───────────────────────────────────────────────
    with t1:
        st.markdown(f"<p style='color:{_gray};font-size:0.85rem;margin-bottom:16px'>Edita directamente. Cada cambio aplica al guardar con el boton al final.</p>", unsafe_allow_html=True)

        _tar_editadas = copy.deepcopy(TAR)
        for _cat in CATEGORIAS_MATERIAL:
            _tar = _tar_editadas.get(_cat, TARIFAS[_cat])
            st.markdown(f"<div style='font-weight:700;color:{_navy};font-size:0.92rem;margin:18px 0 10px;border-left:3px solid {_blue};padding-left:10px'>{_cat}</div>", unsafe_allow_html=True)
            _tc1,_tc2,_tc3,_tc4,_tc5 = st.columns(5)
            _tar["corte"]    = _tc1.number_input("Corte/m²",    value=float(_tar.get("corte",0)),    min_value=0.0, step=1000.0, format="%.0f", key=f"tar_{_cat}_corte",    label_visibility="visible")
            _tar["elab"]     = _tc2.number_input("Elab./m²",    value=float(_tar.get("elab",0)),     min_value=0.0, step=1000.0, format="%.0f", key=f"tar_{_cat}_elab",     label_visibility="visible")
            _tar["zocalo"]   = _tc3.number_input("Zocalo/ml",   value=float(_tar.get("zocalo",0)),   min_value=0.0, step=500.0,  format="%.0f", key=f"tar_{_cat}_zocalo",   label_visibility="visible")
            _tar["disco"]    = _tc4.number_input("Disco/m²",    value=float(_tar.get("disco",0)),    min_value=0.0, step=100.0,  format="%.0f", key=f"tar_{_cat}_disco",    label_visibility="visible")
            _tar["desgaste"] = _tc5.number_input("Desg./dia",   value=float(_tar.get("desgaste",0)), min_value=0.0, step=1000.0, format="%.0f", key=f"tar_{_cat}_desgaste", label_visibility="visible")

            _tar_editadas[_cat] = _tar

        if st.button("Guardar tarifas de trabajo", type="primary", use_container_width=True, key="btn_guardar_tar"):
            st.session_state.tarifas_custom = _tar_editadas
            st.success("Tarifas guardadas. La calculadora ya usa estos valores.")
            st.rerun()

    # ── TAB: LOGISTICA ────────────────────────────────────────────────────────
    with t2:
        st.markdown(f"<p style='color:{_gray};font-size:0.85rem;margin-bottom:16px'>Actualiza precios de gasolina, tarifas de vehiculos y costos fijos de logistica.</p>", unsafe_allow_html=True)

        _log_ed = copy.deepcopy(LOG)

        seccion_titulo("Gasolina y costos generales", "")
        _lc1,_lc2,_lc3,_lc4 = st.columns(4)
        _log_ed["gasolina"]          = _lc1.number_input("Gasolina (COP/galon)", value=float(_log_ed["gasolina"]),              min_value=0.0, step=100.0, format="%.0f", key="log_gas")
        _log_ed["agente"]            = _lc2.number_input("Flete agente externo", value=float(_log_ed["agente"]),                min_value=0.0, step=1000.0,format="%.0f", key="log_ag")
        _log_ed["peaje"]             = _lc3.number_input("Peaje ida+vuelta",     value=float(_log_ed["peaje"]),                 min_value=0.0, step=500.0, format="%.0f", key="log_pj")
        _log_ed["herram"]            = _lc4.number_input("Desg. herramientas",   value=float(_log_ed["herram"]),                min_value=0.0, step=100.0, format="%.0f", key="log_hr")

        seccion_titulo("Frontier NP300", "")
        _fc1,_fc2,_fc3 = st.columns(3)
        _log_ed["frontier"]["rend"]    = _fc1.number_input("Rendimiento (km/galon)", value=float(_log_ed["frontier"]["rend"]),    min_value=0.1, step=0.1, format="%.1f", key="log_fr_rend")
        _log_ed["frontier"]["desgaste"]= _fc2.number_input("Desgaste (COP/km)",     value=float(_log_ed["frontier"]["desgaste"]),min_value=0.0, step=1.0, format="%.0f", key="log_fr_deg")
        _log_ed["frontier"]["base"]    = _fc3.number_input("Flete base (COP/viaje)",value=float(_log_ed["frontier"]["base"]),    min_value=0.0, step=1000.0,format="%.0f",key="log_fr_base")

        seccion_titulo("Cheyenne V8", "")
        _cc1,_cc2,_cc3 = st.columns(3)
        _log_ed["cheyenne"]["rend"]    = _cc1.number_input("Rendimiento (km/galon)", value=float(_log_ed["cheyenne"]["rend"]),    min_value=0.1, step=0.1, format="%.1f", key="log_ch_rend")
        _log_ed["cheyenne"]["desgaste"]= _cc2.number_input("Desgaste (COP/km)",     value=float(_log_ed["cheyenne"]["desgaste"]),min_value=0.0, step=1.0, format="%.0f", key="log_ch_deg")
        _log_ed["cheyenne"]["base"]    = _cc3.number_input("Flete base (COP/viaje)",value=float(_log_ed["cheyenne"]["base"]),    min_value=0.0, step=1000.0,format="%.0f",key="log_ch_base")

        seccion_titulo("Flete externo / Tercero", "")
        _log_ed["externo"]["flete"] = st.number_input("Tarifa fija flete externo (COP)", value=float(_log_ed["externo"]["flete"]), min_value=0.0, step=5000.0, format="%.0f", key="log_ext")

        if st.button("Guardar logistica", type="primary", use_container_width=True, key="btn_guardar_log"):
            st.session_state.logistica_custom = _log_ed
            st.success("Logistica guardada. La calculadora ya usa estos valores.")
            st.rerun()

    # ── TAB: VIATICOS ─────────────────────────────────────────────────────────
    with t3:
        st.markdown(f"<p style='color:{_gray};font-size:0.85rem;margin-bottom:16px'>Tarifa de alojamiento por persona por noche segun tipo de destino.</p>", unsafe_allow_html=True)

        _via_ed = copy.deepcopy(VIA)
        _vc1,_vc2 = st.columns(2)
        _via_ed["pueblo"] = _vc1.number_input("Pueblo / Corregimiento (COP/noche/persona)", value=float(_via_ed["pueblo"]), min_value=0.0, step=1000.0, format="%.0f", key="via_pueblo")
        _via_ed["ciudad"] = _vc2.number_input("Ciudad Capital (COP/noche/persona)",         value=float(_via_ed["ciudad"]), min_value=0.0, step=1000.0, format="%.0f", key="via_ciudad")

        if st.button("Guardar viaticos", type="primary", use_container_width=True, key="btn_guardar_via"):
            st.session_state.viaticos_custom = _via_ed
            st.success("Viaticos guardados.")
            st.rerun()

    # ── TAB: MIS VEHÍCULOS ────────────────────────────────────────────────────
    with t4:
        import copy as _cp2
        st.markdown(f"<p style='color:{_gray};font-size:0.85rem;margin-bottom:6px'>Agrega, edita o elimina los vehiculos que usas para transporte. Los cambios se reflejan de inmediato en los selectores de cotizacion.</p>", unsafe_allow_html=True)
        alerta("El asistente IA puede ayudarte a configurar un vehiculo nuevo. Escribe 'quiero agregar un vehiculo nuevo' en la tab Asistente IA.", "info")

        if st.session_state.get("vehiculos_custom") is None:
            st.session_state.vehiculos_custom = _cp2.deepcopy(VEHICULOS_CONFIG)
        VEH = _cp2.deepcopy(st.session_state.vehiculos_custom)
        _veh_a_eliminar = None

        for _vk, _vc in VEH.items():
            _es_propio  = _vc.get("tipo") == "propio"
            _is_default = _vk in ["frontier", "cheyenne", "externo"]
            with st.expander(f"{_vc.get('nombre', _vk)} — {'Propio' if _es_propio else 'Externo'}", expanded=False):
                _ca, _cb = st.columns([3, 1])
                _vc["nombre"]      = _ca.text_input("Nombre", value=_vc.get("nombre", _vk), key=f"vn_{_vk}", max_chars=40)
                _vc["descripcion"] = _ca.text_input("Descripcion (opcional)", value=_vc.get("descripcion",""), key=f"vd_{_vk}", max_chars=80)
                _tipo_sel = _cb.selectbox("Tipo", ["Propio", "Externo"], index=0 if _es_propio else 1, key=f"vt_{_vk}")
                _vc["tipo"] = "propio" if _tipo_sel == "Propio" else "externo"
                if _vc["tipo"] == "propio":
                    _p1, _p2, _p3 = st.columns(3)
                    _vc["rend"]     = _p1.number_input("Rendimiento (km/galon)", value=float(_vc.get("rend",7.0)), min_value=0.1, step=0.1, format="%.1f", key=f"vr_{_vk}", help="Cuantos km rinde 1 galon con carga")
                    _vc["desgaste"] = _p2.number_input("Desgaste mecanico (COP/km)", value=float(_vc.get("desgaste",148)), min_value=0.0, step=1.0, format="%.0f", key=f"vg_{_vk}", help="Costo de mantenimiento + depreciacion por km")
                    _vc["base"]     = _p3.number_input("Flete minimo (COP/viaje)", value=float(_vc.get("base",65_000)), min_value=0.0, step=1_000.0, format="%.0f", key=f"vb_{_vk}", help="Costo minimo por viaje sin importar la distancia")
                    _gas = (st.session_state.logistica_custom or LOGISTICA).get("gasolina", 16_000)
                    _ckm = (_gas / max(_vc["rend"], 0.1)) + _vc["desgaste"]
                    st.caption(f"Estimado: 10 km = {numero_completo(_vc['base'] + _ckm*20)} · 30 km = {numero_completo(_vc['base'] + _ckm*60)}")
                else:
                    _vc["flete"] = st.number_input("Tarifa fija por viaje (COP)", value=float(_vc.get("flete",165_000)), min_value=0.0, step=5_000.0, format="%.0f", key=f"vf_{_vk}", help="El transportista cobra este valor fijo por cada viaje")
                if not _is_default:
                    if st.button("Eliminar este vehiculo", key=f"del_{_vk}"):
                        _veh_a_eliminar = _vk
            VEH[_vk] = _vc

        if _veh_a_eliminar:
            del VEH[_veh_a_eliminar]
            st.session_state.vehiculos_custom = VEH
            st.success("Vehiculo eliminado.")
            st.rerun()

        st.markdown("---")
        seccion_titulo("Agregar vehiculo nuevo", "")
        with st.expander("Configurar nuevo vehiculo", expanded=False):
            _nc1, _nc2 = st.columns(2)
            _new_nom  = _nc1.text_input("Nombre del vehiculo", placeholder="Ej: Camion Hino 300", key="new_vn")
            _new_tipo = _nc2.selectbox("Tipo", ["Propio (gasolina/diesel)", "Externo (flete fijo)"], key="new_vt")
            _new_desc = st.text_input("Descripcion", placeholder="Opcional", key="new_vd")
            if "Propio" in _new_tipo:
                _n1, _n2, _n3 = st.columns(3)
                _new_rend = _n1.number_input("Rendimiento km/galon", value=7.0, min_value=0.1, step=0.1, format="%.1f", key="new_vr")
                _new_desg = _n2.number_input("Desgaste COP/km", value=148.0, min_value=0.0, step=1.0, format="%.0f", key="new_vg")
                _new_base = _n3.number_input("Flete minimo COP/viaje", value=65_000.0, min_value=0.0, step=1_000.0, format="%.0f", key="new_vb")
                _new_data = {"tipo":"propio","rend":_new_rend,"desgaste":_new_desg,"base":_new_base}
            else:
                _new_flete = st.number_input("Tarifa fija COP/viaje", value=165_000.0, min_value=0.0, step=5_000.0, format="%.0f", key="new_vf")
                _new_data  = {"tipo":"externo","flete":_new_flete}
            if st.button("Agregar vehiculo", type="primary", key="btn_add_veh"):
                if _new_nom.strip():
                    _nk = _new_nom.strip().lower().replace(" ","_")[:20]
                    if _nk in VEH: _nk += "_2"
                    _new_data.update({"nombre":_new_nom.strip(),"descripcion":_new_desc.strip()})
                    VEH[_nk] = _new_data
                    st.session_state.vehiculos_custom = VEH
                    st.success(f"Vehiculo '{_new_nom}' agregado.")
                    st.rerun()
                else:
                    st.warning("Escribe un nombre.")

        _sg1, _sg2 = st.columns(2)
        if _sg1.button("Guardar cambios", type="primary", use_container_width=True, key="btn_sv_veh"):
            st.session_state.vehiculos_custom = VEH
            st.success("Vehiculos guardados.")
            st.rerun()
        if _sg2.button("Restaurar originales", use_container_width=True, key="btn_rst_veh"):
            st.session_state.vehiculos_custom = _cp2.deepcopy(VEHICULOS_CONFIG)
            st.success("Restaurados.")
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# ASISTENTE IA
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Asistente IA":
    st.markdown(f"<h2 style='color:{_navy};font-family:Playfair Display,serif'>Asistente IA</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:{_gray};font-size:0.88rem'>Experto en costos de marmoleria · Barranquilla, Colombia · Powered by Claude</p>", unsafe_allow_html=True)

    if ia_disponible():
        alerta("IA Activa — Haz cualquier pregunta sobre costos, materiales, logistica o cotizacion.", "bueno")
    else:
        alerta("IA en modo basico — Configura tu API key (ver barra lateral).", "acepta")

    # ── Interpretar proyecto ──────────────────────────────────────────────────
    seccion_titulo("Describir proyecto para pre-llenar la calculadora")
    alerta("""Describe tu proyecto en tus propias palabras. Por ejemplo: <em>"Tengo que fabricar una cocina de 4mt de largo por 90cm de ancho, 
    el material es marmol Crema Marfil a $420.000/m², compre media placa, el proveedor trajo el material al taller, 
    voy a entregar en la Frontier 8 km, 2 peajes."</em>""", "info")

    with st.form("form_proyecto"):
        desc_proyecto = st.text_area("Describe tu proyecto aqui:", height=100,
            placeholder="Ej: Cocina de 4mt largo x 90cm ancho, marmol Crema Marfil $420.000/m², media placa 2.5m², Frontier 8km, 2 peajes...")
        btn_interpretar = st.form_submit_button("Interpretar proyecto y pre-llenar calculadora", use_container_width=True)

    if btn_interpretar and desc_proyecto.strip():
        if not ia_disponible():
            alerta("Necesitas configurar la API key de Anthropic para esta funcion.", "acepta")
        else:
            with st.spinner("Interpretando tu descripcion..."):
                datos = interpretar_proyecto(desc_proyecto)
            if datos:
                st.session_state.pre = datos
                st.session_state.cat_sel = datos.get("categoria", "Mármol")
                st.markdown("**Datos detectados:**")
                cols = st.columns(3)
                campo_labels = {
                    "categoria": "Tipo de material", "referencia": "Referencia",
                    "precio_m2": "Precio/m²", "area_placa_comprada": "Area comprada (m²)",
                    "m2_usados": "m² usados", "m2_proyecto": "m² del proyecto",
                    "tipo_proyecto": "Tipo de proyecto", "vehiculo_entrega": "Vehiculo",
                    "km": "Distancia (km)", "peajes": "Peajes",
                }
                mostrados = 0
                for campo, label in campo_labels.items():
                    val = datos.get(campo)
                    if val is not None and val is not False and val != 0:
                        cols[mostrados % 3].success(f"**{label}:** {val}")
                        mostrados += 1
                if datos.get("datos_faltantes"):
                    alerta("Datos no detectados (completa en la calculadora): " + ", ".join(datos["datos_faltantes"]), "acepta")
                alerta("Listo. Ve a <strong>Cotizacion Directa</strong> — los campos ya estan pre-llenados.", "bueno")
            else:
                alerta("No pude interpretar la descripcion. Intenta ser mas especifico.", "acepta")

    st.markdown("---")

    # ── Chat ──────────────────────────────────────────────────────────────────
    seccion_titulo("Chat con el asistente")
    preguntas_rapidas = [
        ("Que % AIU usar?",       "¿Qué porcentaje de AIU debo usar para una licitación con una constructora en Colombia?"),
        ("Margen saludable?",     "¿Cuál es el margen de utilidad saludable para una marmolería en Barranquilla?"),
        ("Estoy subcotizando?",   "¿Cómo sé si estoy subcotizando un proyecto de mármoles?"),
        ("Desgaste de maquina",   "¿Cómo calculo el desgaste de mi cortadora en los costos?"),
        ("Flete a Cartagena",     "¿Cuánto cuesta el flete de Barranquilla a Cartagena para un proyecto?"),
        ("Marmol vs Sinterizado", "¿Diferencia de costo entre trabajar mármol y sinterizado?"),
    ]
    c1, c2, c3 = st.columns(3)
    for idx, (label, preg) in enumerate(preguntas_rapidas):
        col = [c1, c2, c3][idx % 3]
        if col.button(label, key=f"qr_{idx}", use_container_width=True):
            st.session_state.chat.append({"role": "user", "content": preg})
            with st.spinner("Pensando..."):
                resp = chat_con_ia([m for m in st.session_state.chat[:-1]], preg)
            st.session_state.chat.append({"role": "assistant", "content": resp})
            st.rerun()

    st.markdown("---")

    chat_html = f'<div style="background:{_blue_ul};border:1px solid {_blue_l};border-radius:12px;padding:16px;max-height:520px;overflow-y:auto;margin-bottom:12px">'
    if not st.session_state.chat:
        chat_html += f'<div style="background:{_navy};color:rgba(255,255,255,0.85);padding:12px 16px;border-radius:4px 14px 14px 14px;font-size:0.87rem;line-height:1.65;max-width:90%">Hola. Soy el asistente de costos de <strong style="color:{_gold}">Marmoles Collante & Castro</strong>.<br><br>Puedo ayudarte de dos formas:<br>1. <strong>Describe tu proyecto</strong> arriba y pre-lleno la calculadora.<br>2. <strong>Hazme cualquier pregunta</strong> sobre costos, materiales o cotizacion.<br><br>Por donde empezamos?</div>'
    for msg in st.session_state.chat:
        if msg["role"] == "user":
            chat_html += f'<div style="background:{_blue};color:white;padding:10px 16px;border-radius:14px 4px 14px 14px;font-size:0.87rem;line-height:1.6;max-width:85%;margin-left:auto;text-align:right;margin-top:10px">{msg["content"]}</div>'
        else:
            content = msg["content"].replace("\n", "<br>")
            chat_html += f'<div style="background:{_navy};color:rgba(255,255,255,0.87);padding:12px 16px;border-radius:4px 14px 14px 14px;font-size:0.87rem;line-height:1.7;max-width:90%;margin-top:10px">{content}</div>'
    chat_html += '</div>'
    st.markdown(chat_html, unsafe_allow_html=True)

    with st.form("chat_form", clear_on_submit=True):
        c1, c2 = st.columns([5, 1])
        msg_chat = c1.text_input("Pregunta", label_visibility="collapsed",
            placeholder="Ej: Cuanto deberia cobrar por 8m² de Crema Marfil en una cocina?")
        enviar = c2.form_submit_button("Enviar", use_container_width=True)

    if enviar and msg_chat.strip():
        st.session_state.chat.append({"role": "user", "content": msg_chat.strip()})
        with st.spinner("Escribiendo..."):
            resp = chat_con_ia([m for m in st.session_state.chat[:-1]], msg_chat.strip())
        st.session_state.chat.append({"role": "assistant", "content": resp})
        st.rerun()

    if st.session_state.chat:
        if st.button("Limpiar conversacion"):
            st.session_state.chat = []
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Configuracion":
    st.markdown(f"<h2 style='color:{_navy};font-family:Playfair Display,serif'>Configuracion</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:{_gray};font-size:0.88rem;margin-bottom:20px'>Personaliza la app con los datos de tu empresa y logo para los PDF</p>", unsafe_allow_html=True)

    tab_emp, tab_logo, tab_banco = st.tabs(["Datos de la empresa", "Logo y marca", "Datos bancarios"])

    with tab_emp:
        seccion_titulo("Datos de la empresa", "Aparecen en todos los PDF generados")
        emp = st.session_state.empresa_info
        c1, c2 = st.columns(2)
        with c1:
            emp["nombre"]  = st.text_input("Razon social", value=emp.get("nombre", ""))
            emp["nit"]     = st.text_input("NIT", value=emp.get("nit", ""))
            emp["tel"]     = st.text_input("Telefono", value=emp.get("tel", ""))
        with c2:
            emp["email"]   = st.text_input("Correo electronico", value=emp.get("email", ""))
            emp["ciudad"]  = st.text_input("Ciudad", value=emp.get("ciudad", ""))
        if st.button("Guardar datos de empresa", type="primary"):
            st.session_state.empresa_info = emp
            st.success("Datos guardados para esta sesion.")

    with tab_logo:
        seccion_titulo("Logo de la empresa", "El logo aparece en el encabezado de todos los PDF")
        alerta("Carga el logo en formato PNG o JPG. La app lo usara para personalizar los PDF de cotizacion y cuenta de cobro.", "info")

        logo_file = st.file_uploader("Cargar logo (PNG o JPG, max 2MB)", type=["png", "jpg", "jpeg"])
        if logo_file:
            logo_bytes = logo_file.read()
            logo_mime  = logo_file.type
            st.session_state.logo_bytes = logo_bytes
            st.session_state.logo_mime  = logo_mime
            st.image(logo_bytes, width=280)
            alerta("Logo cargado. Se usara en todos los PDF de esta sesion.", "bueno")
        elif st.session_state.logo_bytes:
            st.image(st.session_state.logo_bytes, width=280)
            alerta("Logo actual en uso.", "info")
            if st.button("Remover logo"):
                st.session_state.logo_bytes = None
                st.session_state.logo_mime  = None
                st.rerun()

    with tab_banco:
        seccion_titulo("Informacion bancaria", "Aparece en las cuentas de cobro")
        emp = st.session_state.empresa_info
        c1, c2 = st.columns(2)
        with c1:
            emp["banco"]        = st.text_input("Banco", value=emp.get("banco", "Davivienda"))
            emp["cuenta_tipo"]  = st.text_input("Tipo de cuenta", value=emp.get("cuenta_tipo", "Cuenta Corriente Empresas"))
        with c2:
            emp["cuenta_numero"] = st.text_input("Numero de cuenta", value=emp.get("cuenta_numero", ""))
        alerta("El nombre del titular se toma de la razon social ingresada en 'Datos de la empresa'.", "info")
        if st.button("Guardar datos bancarios", type="primary"):
            st.session_state.empresa_info = emp
            st.success("Datos bancarios guardados.")

# ── HELPERS ───────────────────────────────────────────────────────────────────
def card(content_html, padding="20px 24px", background="white", border_color=None):
    bc = border_color or _blue_l
    st.markdown(f"""<div style="background:{background};border:1px solid {bc};
        border-radius:12px;padding:{padding};margin-bottom:12px">{content_html}</div>""",
        unsafe_allow_html=True)

def hero_banner(titulo, valor_str, subtitulo, meta=""):
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,{_navy} 0%,{_blue} 100%);
         border-radius:14px;padding:32px 36px;margin:8px 0 20px">
      <div style="color:{_gold};font-size:0.68rem;text-transform:uppercase;
           letter-spacing:0.14em;font-weight:700;margin-bottom:10px">{titulo}</div>
      <div style="color:white;font-size:2.8rem;font-weight:900;
           font-family:'Playfair Display',serif;line-height:1;margin-bottom:8px">{valor_str}</div>
      <div style="color:rgba(255,255,255,0.55);font-size:0.85rem">{subtitulo}</div>
      {f'<div style="margin-top:12px">{meta}</div>' if meta else ''}
    </div>""", unsafe_allow_html=True)

def tag(texto, color_bg=None, color_text=None):
    bg = color_bg or _blue_l
    tc = color_text or _blue
    return f'<span style="background:{bg};color:{tc};padding:3px 10px;border-radius:20px;font-size:0.7rem;font-weight:700;letter-spacing:0.05em;text-transform:uppercase">{texto}</span>'

def alerta(texto, tipo="info"):
    estilos = {
        "info":   (_blue_ul, _blue,   _navy),
        "bueno":  ("#E8F5EE",    "#0A6E3F",   "#084D2C"),
        "acepta": ("#FFF3E0",    "#C17A00",   "#7A4D00"),
        "bajo":   ("#FDEAEC",    "#C01A26",   "#8A1520"),
    }
    bg, borde, color = estilos.get(tipo, estilos["info"])
    st.markdown(f"""<div style="background:{bg};border-left:3px solid {borde};
        padding:11px 16px;border-radius:0 8px 8px 0;color:{color};
        font-size:0.86rem;margin:6px 0;line-height:1.55">{texto}</div>""",
        unsafe_allow_html=True)

def seccion_titulo(texto, subtexto=""):
    sub = f'<div style="color:{_gray};font-size:0.82rem;font-weight:400;margin-top:3px">{subtexto}</div>' if subtexto else ""
    st.markdown(f'<div style="margin:24px 0 14px"><div style="color:{_navy};font-size:1.15rem;font-weight:700;letter-spacing:-0.01em">{texto}</div>{sub}</div>', unsafe_allow_html=True)

def linea_costo(label, valor, destacado=False, cero_gris=True):
    gris = cero_gris and valor == 0
    color = _gray if gris else (_navy if not destacado else _blue)
    peso = "800" if destacado else "400"
    borde = f"border-top:2px solid {_navy};padding-top:10px;margin-top:6px;" if destacado else ""
    return f"""<div style="display:flex;justify-content:space-between;padding:8px 0;
        border-bottom:1px solid {_blue_l};{borde}">
      <span style="color:{color};font-size:0.87rem;font-weight:{peso}">{label}</span>
      <span style="color:{color};font-size:0.87rem;font-weight:{peso}">{cop(valor)}</span>
    </div>"""

def bloque_costos(items_label_valor, total_label, total_val):
    html = ""
    for l, v in items_label_valor:
        html += linea_costo(l, v)
    html += linea_costo(total_label, total_val, destacado=True)
    st.markdown(f'<div style="background:white;border:1px solid {_blue_l};border-radius:10px;padding:14px 18px">{html}</div>', unsafe_allow_html=True)

def numero_completo(valor):
    """Formatea número sin truncar: $1.250.000 completo."""
    return f"${int(round(valor)):,}".replace(",", ".")

# ── SESSION STATE ─────────────────────────────────────────────────────────────
_defaults = {
    "chat": [],
    "cotizacion": None,
    "contexto_cot": {},
    "resumen_ia": "",
    "aiu_items": [
        {"desc": "Material pétreo (suministro)", "und": "m²",  "cant": 10.0, "punit": 250_000},
        {"desc": "Mano de obra corte y elaboración", "und": "m²", "cant": 10.0, "punit": 100_000},
        {"desc": "Instalación y nivelación",  "und": "m²",  "cant": 10.0, "punit": 50_000},
        {"desc": "Insumos (disco, adhesivo, silicona)", "und": "glb", "cant": 1.0, "punit": 150_000},
    ],
    "pre": {},
    "piezas": [],
    "tarifas_custom": None,     # dict con tarifas editadas por usuario
    "logistica_custom": None,   # dict con logística editada
    "viaticos_custom": None,    # dict con viáticos editados
    "logo_bytes": None,         # logo cargado por usuario
    "logo_mime": None,
    "empresa_info": {
        "nombre": "MÁRMOLES COLLANTE & CASTRO LTDA.",
        "nit": "NIT: 900.111.561-1",
        "tel": "+57 300 000 0000",
        "email": "ventas@marmolescc.com",
        "ciudad": "Barranquilla, Atlántico — Colombia",
        "banco": "Davivienda",
        "cuenta_tipo": "Cuenta Corriente Empresas",
        "cuenta_numero": "108900027484",
    },
    "params_wizard_activo": False,
    "tour_activo": False,
    "tour_paso": 0,
    "tour_completado": False,
    "vehiculos_custom": None,
    "params_wizard_campo": None,
    "params_wizard_chat": [],
    "cat_sel": "Mármol",
    "dark_mode": False,
    "primera_visita": True,
    "onboarding_paso": 0,
    "onboarding_activo": False,
    "hist_detalle_id": None,
    "hist_detalle_datos": None,
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Activar onboarding automático en primera visita
if st.session_state.get("primera_visita") and not st.session_state.get("onboarding_activo") and not st.session_state.get("tour_completado"):
    st.session_state.onboarding_activo = True
    st.session_state.primera_visita = False

# Tarifas activas (custom o por defecto)
def get_tarifas():
    return st.session_state.tarifas_custom or TARIFAS

def get_logistica():
    return st.session_state.logistica_custom or LOGISTICA

def get_viaticos():
    return st.session_state.viaticos_custom or VIATICOS

def get_vehiculos_config():
    import copy
    base = copy.deepcopy(VEHICULOS_CONFIG)
    custom = st.session_state.get("vehiculos_custom") or {}
    for k, v in custom.items():
        base[k] = v
    return base

def get_vehiculos_dict():
    vc = get_vehiculos_config()
    result = {}
    for key, cfg in vc.items():
        nombre = cfg.get("nombre", key)
        sufijo = " (propio)" if cfg.get("tipo") == "propio" else " (flete externo)"
        result[f"{nombre}{sufijo}"] = key
    return result

# ── SIDEBAR ───────────────────────────────────────────────────────────────────
with st.sidebar:
    # ── Logo: primero intenta el logo cargado por el usuario, luego el archivo local
    _logo_shown = False
    if st.session_state.get("logo_bytes"):
        try:
            st.image(st.session_state.logo_bytes, use_container_width=True)
            _logo_shown = True
        except Exception:
            pass
    if not _logo_shown:
        _local_paths = [
            "/mnt/user-data/uploads/logo_cc.jpeg",
            "logo_cc.jpeg",
        ]
        for _lp in _local_paths:
            try:
                with open(_lp, "rb") as _f:
                    _ld = _f.read()
                st.image(_ld, use_container_width=True)
                _logo_shown = True
                break
            except Exception:
                pass
    if not _logo_shown:
        # Fallback: bloque corporativo con iniciales
        st.markdown(
            f'<div style="background:linear-gradient(135deg,rgba(255,255,255,0.12),rgba(255,255,255,0.05));'
            f'border:1px solid rgba(255,255,255,0.15);border-radius:12px;padding:22px 16px;'
            f'text-align:center;margin-bottom:4px">'
            f'<div style="color:{_gold};font-size:2rem;font-weight:900;font-family:Playfair Display,serif;letter-spacing:0.05em">CC</div>'
            f'<div style="color:rgba(255,255,255,0.9);font-size:0.75rem;font-weight:700;margin-top:6px;letter-spacing:0.04em">MÁRMOLES</div>'
            f'<div style="color:rgba(255,255,255,0.5);font-size:0.65rem;margin-top:2px">Collante &amp; Castro</div>'
            f'</div>',
            unsafe_allow_html=True
        )

    # Nombre empresa
    _emp_nombre = st.session_state.get("empresa_info", {}).get("nombre", "MÁRMOLES COLLANTE & CASTRO LTDA.")
    st.markdown(
        f'<div style="margin:10px 0 16px;padding:0 2px">'
        f'<div style="color:white;font-size:0.82rem;font-weight:700;line-height:1.3">{_emp_nombre}</div>'
        f'<div style="color:{_gold};font-size:0.62rem;text-transform:uppercase;letter-spacing:0.1em;margin-top:3px">Sistema de Cotizacion Profesional</div>'
        f'</div>',
        unsafe_allow_html=True
    )

    st.markdown(f'<div style="height:1px;background:rgba(255,255,255,0.1);margin:4px 0 12px"></div>', unsafe_allow_html=True)
    st.markdown(f'<div style="color:rgba(255,255,255,0.35);font-size:0.62rem;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px">Menu</div>', unsafe_allow_html=True)

    pagina = st.radio("", [
        "Inicio",
        "Cotizacion Directa",
        "Cotizacion AIU",
        "Historial",
        "Dashboard",
        "Parametros",
        "Asistente IA",
        "Configuracion",
    ], label_visibility="collapsed")

    st.markdown(f'<div style="height:1px;background:rgba(255,255,255,0.1);margin:12px 0"></div>', unsafe_allow_html=True)
    if ia_disponible():
        st.markdown(f'<div style="background:rgba(74,222,128,0.15);border:1px solid rgba(74,222,128,0.3);border-radius:6px;padding:7px 10px;font-size:0.75rem;font-weight:600;color:#4ade80">IA Activa — Claude</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div style="background:rgba(251,191,36,0.12);border:1px solid rgba(251,191,36,0.25);border-radius:6px;padding:7px 10px;font-size:0.75rem;font-weight:600;color:#fbbf24">IA sin configurar</div>', unsafe_allow_html=True)
        with st.expander("Activar IA (2 min)"):
            st.markdown("Crea `.streamlit/secrets.toml` y escribe:\n```toml\nANTHROPIC_API_KEY = \"sk-ant-...\"\n```\nObtén tu clave en `console.anthropic.com`")

    st.markdown(f'<div style="color:rgba(255,255,255,0.2);font-size:0.62rem;margin-top:14px">Feb 2026 · Barranquilla, Colombia</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# INICIO
# ═══════════════════════════════════════════════════════════════════════════════
if pagina == "Inicio":
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,{_navy} 0%,{_blue} 100%);
         border-radius:16px;padding:40px 44px;margin-bottom:28px;position:relative;overflow:hidden">
      <div style="position:absolute;top:-40px;right:-40px;width:200px;height:200px;
           background:rgba(255,255,255,0.03);border-radius:50%"></div>
      <div style="color:{_gold};font-size:0.68rem;text-transform:uppercase;
           letter-spacing:0.15em;font-weight:700;margin-bottom:12px">
        Mármoles Collante &amp; Castro Ltda.
      </div>
      <div style="color:white;font-size:2.4rem;font-weight:900;
           font-family:'Playfair Display',serif;line-height:1.1;margin-bottom:14px">
        Sistema de Cotización<br>Profesional
      </div>
      <div style="color:rgba(255,255,255,0.55);font-size:0.92rem;line-height:1.65;max-width:500px">
        Calcula el costo real de tus proyectos en mármol, granito, sinterizado, quarztone y cuarcita.
        Cotización, logística, AIU y PDF en menos de 2 minutos.
      </div>
    </div>
    """, unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Materiales", "5 tipos", "Mármol · Granito · Sint. · Quartz · Cuarcita")
    c2.metric("Tiempo", "2 min", "vs. 45–90 min manual")
    c3.metric("Estructura", "AIU + IVA", "Norma colombiana")
    c4.metric("Exporta", "PDF", "Cotización + Cuenta de cobro")

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        card(f"""
        <div style="font-weight:700;color:{_navy};font-size:1rem;margin-bottom:6px">Cotizacion Directa</div>
        <div style="color:{_gray};font-size:0.87rem;line-height:1.55">
          Para clientes particulares. Ingresa material, precio/m² y área por piezas (ML × ancho).
          La app calcula mano de obra, logística, insumos y precio de venta sugerido.
        </div>""")
    with col2:
        card(f"""
        <div style="font-weight:700;color:{_navy};font-size:1rem;margin-bottom:6px">Cotizacion AIU</div>
        <div style="color:{_gray};font-size:0.87rem;line-height:1.55">
          Para constructoras y licitaciones. Estructura formal colombiana: Administración,
          Imprevistos, Utilidad + IVA sobre utilidad.
        </div>""")

    alerta("Describe tu proyecto en lenguaje natural en el <strong>Asistente IA</strong> y la app pre-llenará la calculadora por ti.", "info")


# ═══════════════════════════════════════════════════════════════════════════════
# COTIZACIÓN DIRECTA
# ═══════════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════
# TOUR GUIADO
# ═══════════════════════════════════════════════════════════════════════════════
if st.session_state.get("tour_activo"):
    _paso_idx = st.session_state.get("tour_paso", 0)
    _paso_idx = min(_paso_idx, len(TOUR_PASOS) - 1)
    _paso = TOUR_PASOS[_paso_idx]
    _total = len(TOUR_PASOS)

    # Overlay card
    st.markdown(
        f"""<div style="position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(13,33,55,0.72);z-index:9998;pointer-events:none"></div>""",
        unsafe_allow_html=True
    )
    _prog_pct = int((_paso_idx / max(_total - 1, 1)) * 100)
    _cuerpo_html = _paso["cuerpo"].replace("\n", "<br>")
    st.markdown(
        f"""<div style="position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);
            z-index:9999;background:white;border-radius:16px;padding:32px 36px;
            max-width:520px;width:90%;box-shadow:0 24px 64px rgba(0,0,0,0.35);
            border-top:4px solid {_gold}">
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
            <div style="background:{_navy};color:{_gold};width:36px;height:36px;border-radius:50%;
              display:flex;align-items:center;justify-content:center;font-weight:900;font-size:1rem;flex-shrink:0">{_paso['icono']}</div>
            <div>
              <div style="font-size:0.72rem;color:{_gray};text-transform:uppercase;letter-spacing:0.08em">Paso {_paso_idx + 1} de {_total}</div>
              <div style="font-size:1.1rem;font-weight:800;color:{_navy};font-family:Playfair Display,serif">{_paso['titulo']}</div>
            </div>
          </div>
          <div style="font-size:0.9rem;color:#2a3a4a;line-height:1.7;margin-bottom:20px">{_cuerpo_html}</div>
          <div style="background:{_gray_l};border-radius:4px;height:4px;margin-bottom:16px">
            <div style="background:{_gold};width:{_prog_pct}%;height:4px;border-radius:4px;transition:width 0.3s"></div>
          </div>
        </div>""",
        unsafe_allow_html=True
    )

    _tc1, _tc2, _tc3 = st.columns([1, 1, 1])
    with _tc1:
        if _paso_idx > 0:
            if st.button("Anterior", key="tour_prev", use_container_width=True):
                st.session_state.tour_paso -= 1
                st.rerun()
    with _tc2:
        if st.button("Cerrar recorrido", key="tour_close", use_container_width=True):
            st.session_state.tour_activo = False
            st.rerun()
    with _tc3:
        if _paso_idx < _total - 1:
            if st.button("Siguiente", key="tour_next", type="primary", use_container_width=True):
                st.session_state.tour_paso += 1
                if _paso.get("pagina"):
                    pass  # ya se muestra la info en el card
                st.rerun()
        else:
            if st.button("Finalizar", key="tour_fin", type="primary", use_container_width=True):
                st.session_state.tour_activo    = False
                st.session_state.tour_completado = True
                st.rerun()

if pagina == "Cotizacion Directa":
    st.markdown(f"<h2 style='color:{_text_main};font-family:Playfair Display,serif;margin-bottom:4px'>Cotizacion Directa</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:{_text_sub};font-size:0.88rem;margin-bottom:20px'>Para proyectos residenciales y clientes particulares</p>", unsafe_allow_html=True)

    pre = st.session_state.pre
    if pre:
        alerta("La IA detectó tu proyecto y pre-llenó los campos. Revisa y ajusta lo que necesites.", "bueno")
        if st.button("Limpiar pre-llenado"):
            st.session_state.pre = {}
            st.rerun()

    TARIFAS_ACT = get_tarifas()
    LOG_ACT = get_logistica()
    VIA_ACT = get_viaticos()

    # ── PASO 1: MATERIAL ──────────────────────────────────────────────────────
    seccion_titulo("Paso 1 — Material", "Selecciona el tipo de piedra e ingresa el precio del proveedor")

    cat_sel = st.session_state.get("cat_sel", pre.get("categoria", "Mármol"))
    cols_cat = st.columns(len(CATEGORIAS_MATERIAL))
    for i, cat in enumerate(CATEGORIAS_MATERIAL):
        bg_c, color_c = BADGE_COLORS.get(cat, (_blue_l, _navy))
        activo = cat_sel == cat
        borde = f"2px solid {_blue}" if activo else f"1px solid {_blue_l}"
        bg = _blue_ul if activo else "white"
        with cols_cat[i]:
            st.markdown(f"""<div style="border:{borde};border-radius:10px;padding:14px 8px;
                background:{bg};text-align:center">
              <div style="font-weight:700;font-size:0.8rem;color:{_navy};margin-top:2px">
                {'▶ ' if activo else ''}{cat}</div>
              <div style="font-size:0.65rem;color:{_gray};margin-top:4px;line-height:1.3">
                {DESCRIPCIONES_CATEGORIA.get(cat,'')}</div>
            </div>""", unsafe_allow_html=True)
            if st.button(f"Elegir {cat}", key=f"cat_{i}", use_container_width=True):
                st.session_state.cat_sel = cat
                st.rerun()
    cat_sel = st.session_state.get("cat_sel", "Mármol")

    st.markdown(f"<div style='margin:12px 0 4px;font-size:0.82rem;color:{_gray};font-weight:600;text-transform:uppercase;letter-spacing:0.05em'>Material seleccionado: <span style='color:{_navy}'>{cat_sel}</span></div>", unsafe_allow_html=True)
    st.divider()

    c1, c2, c3 = st.columns(3)
    with c1:
        refs_cat = [m["nombre"] for m in MATERIALES_CATALOGO if m["categoria"] == cat_sel]
        refs_cat = ["Otra referencia..."] + refs_cat
        ref_sel = st.selectbox("Referencia del material", refs_cat)
        if ref_sel == "Otra referencia...":
            referencia = st.text_input("Nombre de la referencia", value=pre.get("referencia", ""), placeholder="Ej: Calacatta Gold")
        else:
            referencia = ref_sel
            m_cat = next((m for m in MATERIALES_CATALOGO if m["nombre"] == ref_sel), None)
            if m_cat and "precio_m2_default" not in st.session_state:
                st.session_state["precio_m2_default"] = m_cat["precio_m2"]
    with c2:
        precio_m2_default = pre.get("precio_m2") or st.session_state.pop("precio_m2_default", 220_000)
        precio_m2 = st.number_input("Precio por m² — COP", min_value=10_000, max_value=5_000_000,
            value=int(precio_m2_default), step=1_000,
            help="El valor por m² que está en la factura del proveedor")
    with c3:
        area_placa_default = pre.get("area_placa_comprada", 5.94)
        area_placa = st.number_input("Area total comprada (m²)", min_value=0.01, max_value=200.0,
            value=float(area_placa_default), step=0.1, format="%.3f",
            help="Cuantos m² de material compraste en total")

    costo_mat = precio_m2 * area_placa
    alerta(f"Costo total del material: <strong>{numero_completo(precio_m2)}/m²</strong> x {area_placa} m² = <strong>{numero_completo(costo_mat)}</strong>", "info")

    st.markdown("---")

    # ── PASO 2: DIMENSIONES ──────────────────────────────────────────────────
    seccion_titulo("Paso 2 — Dimensiones del proyecto", "Ingresa cada pieza por metros lineales — la app convierte a m² automaticamente")

    if "piezas" not in st.session_state or not st.session_state.piezas:
        st.session_state.piezas = [{"nombre": "Meson de cocina", "ml": 2.0, "ancho_tipo": "Mesón de cocina", "ancho_custom": 0.60}]

    _mostrar_avanzado = st.session_state.get("modo_avanzado_medidas", False)
    if not _mostrar_avanzado:
        modo_medida = "Por piezas (ML × Ancho) — recomendado"
        if st.button("Opciones avanzadas (ingresar m\u00b2 directamente)"):
            st.session_state.modo_avanzado_medidas = True
            st.rerun()
    else:
        modo_medida = st.radio("Modo de ingreso", ["Por piezas (ML \u00d7 Ancho) \u2014 recomendado", "Ingresar m\u00b2 directamente"], horizontal=True)
        if st.button("Volver al modo simplificado"):
            st.session_state.modo_avanzado_medidas = False
            st.rerun()

    m2_real = 0.0
    m2_cortados_total = 0.0

    if "Por piezas" in modo_medida:
        alerta("Agrega cada pieza del proyecto. Para cada pieza: largo en ML × ancho estandar = m² calculados.", "info")

        hdr = st.columns([3, 1.2, 2.5, 1.5, 1.6, 0.6])
        for col, lbl in zip(hdr, ["Pieza / Descripcion", "ML largo", "Tipo de superficie", "Ancho (m)", "m² calculados", ""]):
            col.markdown(f"<div style='font-size:0.72rem;font-weight:700;color:{_gray};text-transform:uppercase;letter-spacing:0.06em;padding:4px 0'>{lbl}</div>", unsafe_allow_html=True)

        tipos_superficie = list(ANCHOS_ESTANDAR.keys())
        piezas_nuevas = []
        total_m2_piezas = 0.0

        for idx, pieza in enumerate(st.session_state.piezas):
            c0, c1, c2, c3, c4, c5 = st.columns([3, 1.2, 2.5, 1.5, 1.6, 0.6])
            with c0:
                nombre_p = st.text_input("Nombre pieza", value=pieza.get("nombre", ""), key=f"pnom_{idx}", label_visibility="collapsed")
            with c1:
                ml_p = st.number_input("ML", value=float(pieza.get("ml", 1.0)), min_value=0.01, step=0.1, format="%.2f", key=f"pml_{idx}", label_visibility="collapsed")
            with c2:
                tipo_idx = tipos_superficie.index(pieza.get("ancho_tipo", tipos_superficie[0])) if pieza.get("ancho_tipo") in tipos_superficie else 0
                ancho_tipo_p = st.selectbox("Tipo", tipos_superficie, index=tipo_idx, key=f"ptip_{idx}", label_visibility="collapsed")
            with c3:
                ancho_def = ANCHOS_ESTANDAR[ancho_tipo_p]["ancho"] or pieza.get("ancho_custom", 0.60)
                ancho_p = st.number_input("Ancho", value=float(ancho_def), min_value=0.01, max_value=5.0, step=0.01, format="%.2f", key=f"panc_{idx}", label_visibility="collapsed")
            m2_p = ml_a_m2(ml_p, ancho_p)
            total_m2_piezas += m2_p
            with c4:
                _m2p_fmt = f"{m2_p:.3f}".replace(".", ",")
                st.markdown(f"<div style='padding:8px 4px;font-weight:700;color:{_navy};font-size:0.9rem'>{_m2p_fmt} m²</div>", unsafe_allow_html=True)
            with c5:
                if st.button("X", key=f"del_{idx}") and len(st.session_state.piezas) > 1:
                    st.session_state.piezas.pop(idx)
                    st.rerun()
            piezas_nuevas.append({"nombre": nombre_p, "ml": ml_p, "ancho_tipo": ancho_tipo_p, "ancho_custom": ancho_p})

        st.session_state.piezas = piezas_nuevas
        m2_real = total_m2_piezas
        m2_cortados_total = total_m2_piezas

        col_add, col_sum = st.columns([1, 2])
        with col_add:
            if st.button("+ Agregar pieza", use_container_width=True):
                st.session_state.piezas.append({"nombre": f"Pieza {len(st.session_state.piezas)+1}", "ml": 1.0, "ancho_tipo": tipos_superficie[0], "ancho_custom": 0.60})
                st.rerun()
        with col_sum:
            if m2_real > 0:
                _ml_total = sum(p.get("ml", 0) for p in st.session_state.piezas if isinstance(p, dict))
                _ml_str = f"{_ml_total:.2f}".replace(".", ",")
                _m2_str = f"{m2_real:.3f}".replace(".", ",")
                st.markdown(
                    f'''<div style="background:{_navy};color:white;border-radius:10px;padding:12px 18px;text-align:center">
                  <div style="font-size:0.7rem;color:{_gold};text-transform:uppercase;letter-spacing:0.08em">Total del proyecto</div>
                  <div style="font-size:2rem;font-weight:900;font-family:'Playfair Display',serif">{_ml_str} ml</div>
                  <div style="font-size:0.85rem;color:rgba(255,255,255,0.6);margin-top:2px">{_m2_str} m² de material</div>
                  <div style="font-size:0.72rem;color:rgba(255,255,255,0.45);margin-top:1px">{len(st.session_state.piezas)} piezas</div>
                </div>''', unsafe_allow_html=True)

        extra_corte = st.number_input("m² adicionales cortados no aprovechados (desperdicios)", min_value=0.0, value=0.0, step=0.05, format="%.3f")
        m2_cortados_total += extra_corte

    else:
        c1, c2 = st.columns(2)
        with c1:
            usar_calc = st.checkbox("Calcular desde largo x ancho", value=False)
            if usar_calc:
                s1, s2, s3 = st.columns(3)
                lg = s1.number_input("Largo", min_value=0.0, value=4.0, step=0.1, format="%.2f")
                an = s2.number_input("Ancho", min_value=0.0, value=0.60, step=0.01, format="%.2f")
                un = s3.selectbox("Unidad", ["metros", "cm"])
                m2_real = ((lg/100)*(an/100)) if un == "cm" else lg*an
                st.info(f"{lg} {un} x {an} {un} = {m2_real:.3f} m²")
            else:
                m2_real = st.number_input("m² reales del proyecto", min_value=0.01, value=float(pre.get("m2_proyecto", 4.0)), step=0.05, format="%.3f")
        with c2:
            m2_cortados_input = st.number_input("m² cortados de la placa (puede ser mayor por desperdicios)", min_value=0.0, value=float(m2_real), step=0.05, format="%.3f")
            m2_cortados_total = m2_cortados_input if m2_cortados_input > 0 else m2_real

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    with c1:
        m2_usados_default = pre.get("m2_usados", 0.0)
        m2_usados = st.number_input("m² finalmente instalados", min_value=0.0,
            value=float(m2_usados_default) if m2_usados_default else float(round(m2_real, 3)),
            step=0.05, format="%.3f", help="Puede ser menor si hay huecos (poceta, estufa, etc.)")
    with c2:
        margen_pct = st.slider("Margen de utilidad (%)", min_value=5, max_value=80, value=40, step=1)
    with c3:
        if area_placa > 0 and m2_usados > 0:
            aprv = min(100, m2_usados / area_placa * 100)
            retal = max(0, area_placa - m2_usados)
            estado_a = "bueno" if aprv >= 80 else "acepta" if aprv >= 50 else "bajo"
            alerta(f"Aprovechamiento: <strong>{aprv:.1f}%</strong> — Retal: {retal:.3f} m²", estado_a)

    if m2_cortados_total > 0 and m2_real > 0:
        alerta(f"Resumen: {sum(p['ml'] for p in st.session_state.get('piezas',[]) if isinstance(p,dict)):.2f} ml totales · {m2_real:.3f} m² de material · Produccion calculada sobre los metros lineales reales", "info")

    st.markdown("---")

    # ── PASO 3: PROYECTO ─────────────────────────────────────────────────────
    seccion_titulo("Paso 3 — Tipo de proyecto y obra")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        tipo_default = pre.get("tipo_proyecto", "Mesón")
        tipo_opts = ["Mesón", "Cocina", "Baño", "Piso", "Escalera", "Fachada", "Mueble de cocina", "Otro"]
        tipo = st.selectbox("Tipo de proyecto", tipo_opts,
            index=tipo_opts.index(tipo_default) if tipo_default in tipo_opts else 0)
    with c2:
        etapa_lbl = st.selectbox("Etapa de la obra", list(ETAPAS_OBRA.keys()))
        etapa = ETAPAS_OBRA[etapa_lbl]
    with c3:
        dias_default = int(pre.get("dias_obra") or 2)
        dias = st.number_input("Dias en obra", min_value=1, value=dias_default, step=1)
    with c4:
        pers_default = int(pre.get("personas") or 2)
        personas = st.number_input("Num. de personas", min_value=1, value=pers_default, step=1)

    nombre_cliente = st.text_input("Nombre del cliente (para el PDF)", placeholder="Ej: Juan Garcia / Constructora XYZ")

    st.markdown("**Zocalos**")
    zocalo_activo = st.checkbox("Este proyecto lleva zocalos", key="cb_zocalo")
    zocalo_ml = 0.0
    if zocalo_activo:
        zocalo_ml = st.number_input("Metros lineales de zocalo (ml)", min_value=0.0, value=2.0, step=0.5, format="%.1f")
        tar_z = TARIFAS_ACT.get(cat_sel, {}).get("zocalo", 0)
        alerta(f"Tarifa zocalo {cat_sel}: {numero_completo(tar_z)}/ml — Subtotal: <strong>{numero_completo(zocalo_ml*tar_z)}</strong>", "info")

    st.markdown("---")

    # ── PASO 4: LOGÍSTICA ────────────────────────────────────────────────────
    seccion_titulo("Paso 4 — Logistica")

    col_agt, col_veh = st.columns(2)
    with col_agt:
        st.markdown(f"<div style='font-size:0.8rem;font-weight:600;color:{_navy};margin-bottom:6px'>Como llego el material al taller</div>", unsafe_allow_html=True)
        agente_ext_taller = st.checkbox("Agente externo trajo el material al taller",
            value=bool(pre.get("agente_externo_taller", False)), key="cb_agente_taller",
            help=f"Agrega {numero_completo(LOG_ACT['agente'])} de flete.")
        if agente_ext_taller:
            alerta(f"Flete proveedor al taller: <strong>{numero_completo(LOG_ACT['agente'])}</strong>", "info")
    with col_veh:
        st.markdown(f"<div style='font-size:0.8rem;font-weight:600;color:{_navy};margin-bottom:6px'>Transporte taller al cliente</div>", unsafe_allow_html=True)
        _veh_dict = get_vehiculos_dict()
        veh_default = pre.get("vehiculo_entrega", "frontier")
        _veh_keys = list(_veh_dict.keys())
        _veh_vals = list(_veh_dict.values())
        _veh_idx  = _veh_vals.index(veh_default) if veh_default in _veh_vals else 0
        veh_lbl   = st.selectbox("Vehiculo de entrega", _veh_keys, index=_veh_idx)
        vehiculo  = _veh_dict[veh_lbl]

    c1, c2 = st.columns(2)
    with c1:
        km_default = float(pre.get("km") or 5.0)
        km = st.number_input("Distancia taller al cliente (km, un trayecto)", min_value=0.0, value=km_default, step=0.5, format="%.1f")
        st.caption("El sistema calcula automaticamente el costo del tiempo de traslado de los operarios segun esta distancia.")
    with c2:
        peajes_default = int(pre.get("peajes") or 0)
        peajes = st.number_input("Num. de peajes (total ida+vuelta)", min_value=0, value=peajes_default, step=1)

    from calculos import calcular_logistica as _calc_log
    _log_custom  = st.session_state.get("logistica_custom") or None
    _veh_custom  = {**VEHICULOS_CONFIG, **(st.session_state.get("vehiculos_custom") or {})}
    log_prev = _calc_log(vehiculo, km, peajes, agente_ext_taller, personas, cat_sel,
        logistica_override=_log_custom, vehiculos_custom=_veh_custom)
    with st.expander(f"Desglose logistico — Total: {numero_completo(log_prev['total'])}"):
        items_log = []
        _vc_cur = get_vehiculos_config().get(vehiculo, {})
        if _vc_cur.get("tipo") != "externo":
            items_log.append((f"Base {_vc_cur.get('nombre', veh_lbl)}", log_prev["base"]))
            items_log.append((f"Gasolina + desgaste mecanico ({km*2:.0f} km ida+vuelta)", log_prev["km_costo"]))
        else:
            items_log.append((f"Flete {_vc_cur.get('nombre', 'Externo')}", log_prev["vehiculo"]))
        if agente_ext_taller:
            items_log.append(("Flete proveedor al taller", log_prev["agente"]))
        items_log.append((f"Peajes ({peajes} peajes)", log_prev["peajes"]))
        items_log.append(("Desgaste de herramientas", log_prev["herram"]))

        bloque_costos(items_log, "TOTAL LOGISTICO", log_prev["total"])


    st.markdown("---")

    # ── PASO 5: FORÁNEO ──────────────────────────────────────────────────────
    seccion_titulo("Paso 5 — Proyecto fuera de Barranquilla?")
    foraneo_activo = st.checkbox("Si, este proyecto es en otra ciudad o municipio", key="cb_foraneo")
    viaticos_activos = False
    tipo_aloj = "pueblo"
    noches = 0
    if foraneo_activo:
        c1, c2, c3 = st.columns(3)
        with c1:
            viaticos_activos = st.checkbox("Agregar viaticos (alojamiento)", key="cb_viaticos")
        with c2:
            tipo_aloj_lbl = st.selectbox("Tipo de destino", list(ALOJAMIENTO.keys()))
            tipo_aloj = ALOJAMIENTO[tipo_aloj_lbl]
        with c3:
            noches = st.number_input("Noches de alojamiento", min_value=0, value=1, step=1)
        if viaticos_activos and noches > 0:
            from calculos import calcular_viaticos as _cv
            viat_tot = _cv(True, tipo_aloj, noches, personas)
            alerta(f"Viaticos: {noches} noches × {personas} personas × {numero_completo(VIA_ACT.get(tipo_aloj,145000))} = <strong>{numero_completo(viat_tot)}</strong>", "info")

    st.markdown("---")

    # ── PASO 6: ADICIONALES ──────────────────────────────────────────────────
    seccion_titulo("Paso 6 — Costos adicionales en obra")
    adicionales_activos = st.checkbox("Agregar costos adicionales (silicona, impermeabilizante, etc.)", key="cb_add")
    cantidades_add = []
    if adicionales_activos:
        for i, a in enumerate(ADICIONALES):
            c1, c2 = st.columns([3, 1])
            c1.markdown(f"<div style='font-size:0.85rem;color:{_navy}'>{a['concepto']} — {numero_completo(a.get(etapa, 0))}/{a['unidad']}</div>", unsafe_allow_html=True)
            qty = c2.number_input("Cant.", min_value=0.0, value=0.0, step=1.0, key=f"add_{i}", label_visibility="collapsed")
            cantidades_add.append(qty)
    else:
        cantidades_add = [0.0] * len(ADICIONALES)

    st.markdown("---")

    # ── CALCULAR ─────────────────────────────────────────────────────────────
    col_btn, col_inf = st.columns([1, 3])
    with col_btn:
        calcular = st.button("Calcular cotizacion", type="primary", use_container_width=True)
    with col_inf:
        alerta("Completa todos los pasos y presiona calcular para obtener el costo real y precio sugerido.", "info")

    if calcular or st.session_state.cotizacion:
        if calcular:
            _ml_tot = sum(p.get("ml", 0) for p in st.session_state.get("piezas", []) if isinstance(p, dict))
            _log_ov = st.session_state.get("logistica_custom") or None
            _veh_cu = {**VEHICULOS_CONFIG, **(st.session_state.get("vehiculos_custom") or {})}
            _tar_ov = st.session_state.get("tarifas_custom") or None
            resultado = calcular_cotizacion_directa(
                categoria=cat_sel, referencia=referencia,
                precio_m2=precio_m2, area_placa_comprada=area_placa,
                m2_real=m2_real, m2_cortados=m2_cortados_total,
                m2_usados=m2_usados, margen_pct=margen_pct,
                dias=dias, personas=personas,
                zocalo_activo=zocalo_activo, zocalo_ml=zocalo_ml,
                agente_externo_taller=agente_ext_taller,
                vehiculo_entrega=vehiculo, km=km, num_peajes=peajes,
                foraneo_activo=foraneo_activo, viaticos_activos=viaticos_activos,
                tipo_aloj=tipo_aloj, noches=noches,
                adicionales_activos=adicionales_activos,
                cantidades_add=cantidades_add, etapa=etapa,
                adicionales_lista=ADICIONALES,
                tipo_proyecto=tipo, nombre_cliente=nombre_cliente,
                ml_proyecto=_ml_tot,
                logistica_override=_log_ov,
                vehiculos_custom=_veh_cu,
                tarifas_override=_tar_ov,
            )
            resultado["vehiculo_usado"] = vehiculo
            st.session_state.cotizacion = resultado
            st.session_state.contexto_cot = {"categoria": cat_sel, "referencia": referencia, "tipo_proyecto": tipo, "m2_real": m2_real}
            import random as _rand
            _num_auto = f"COT-{date.today().strftime('%Y%m%d')}-{_rand.randint(100,999)}"
            _guardar_cotizacion(_num_auto, nombre_cliente, resultado)
            if ia_disponible():
                with st.spinner("Analizando resultados con IA..."):
                    st.session_state.resumen_ia = generar_resumen_cotizacion(resultado, st.session_state.contexto_cot)

        r = st.session_state.cotizacion
        st.markdown("---")
        st.markdown(f"<h3 style='color:{_navy};font-family:Playfair Display,serif'>Resultado</h3>", unsafe_allow_html=True)

        hero_banner(
            titulo="Precio de venta sugerido",
            valor_str=numero_completo(r['precio_sugerido']),
            subtitulo=f"Margen: {r['margen_pct']:.0f}%   ·   Utilidad proyectada: {numero_completo(r['utilidad'])}",
            meta=f"{tag('Costo directo: '+numero_completo(r['costo_total']))}"
        )

        col_res, col_det = st.columns([1, 1])
        with col_res:
            st.markdown(f"<div style='font-size:0.8rem;font-weight:700;color:{_gray};text-transform:uppercase;letter-spacing:0.06em;margin-bottom:10px'>Desglose de costos</div>", unsafe_allow_html=True)
            bloque_costos([
                ("Material (area comprada x precio/m²)", r['c1_material']),
                ("Produccion (por metro lineal)",        r['c2_mano_obra']),
                ("Zocalos",                              r['c3_zocalos']),
                ("Insumos (disco + uso de maquina)",     r['c4_insumos']),
                ("Logistica",                            r['c5_logistica']),
                ("Viaticos",                             r['c6_viaticos']),
                ("Adicionales en obra",                  r['c7_adicionales']),
            ], "COSTO TOTAL", r['costo_total'])

        with col_det:
            c1a, c2a = st.columns(2)
            c1a.metric("Aprovechamiento", f"{r['aprovechamiento']:.1f}%", f"Retal: {r['retal']:.3f} m²")
            c2a.metric("Costo/m² instalado", numero_completo(r['costo_total']/r['m2_real']) if r['m2_real'] > 0 else "—")
            c1b, c2b = st.columns(2)
            c1b.metric("Costo total", numero_completo(r['costo_total']))
            c2b.metric("Utilidad", numero_completo(r['utilidad']))

            st.markdown(f"<div style='font-size:0.8rem;font-weight:700;color:{_gray};text-transform:uppercase;letter-spacing:0.06em;margin:14px 0 8px'>Analisis real</div>", unsafe_allow_html=True)
            precio_real = st.number_input("Ingresa el precio que vas a cobrar realmente (opcional)", min_value=0, value=0, step=10_000)
            if precio_real > 0:
                analisis = analizar_precio_real(precio_real, r['costo_total'], r['precio_sugerido'])
                tipo_a = analisis.get("estado", "bajo")
                alerta(f"Margen real: <strong>{analisis['margen_real']:.1f}%</strong> — Utilidad: {numero_completo(analisis['utilidad_real'])} — {'Por encima' if analisis['diferencia']>=0 else 'Por debajo'} del sugerido: {numero_completo(abs(analisis['diferencia']))}", tipo_a)

        if st.session_state.resumen_ia:
            st.markdown("---")
            st.markdown(f"<div style='font-size:0.8rem;font-weight:700;color:{_gray};text-transform:uppercase;letter-spacing:0.06em;margin-bottom:10px'>Analisis IA</div>", unsafe_allow_html=True)
            card(f"<div style='font-size:0.87rem;color:{_navy};line-height:1.65'>{st.session_state.resumen_ia.replace(chr(10),'<br>')}</div>")

        # ── SIMULADOR DE MARGEN ───────────────────────────────────────────────
        st.markdown("---")
        st.markdown(f"<div style='font-size:0.8rem;font-weight:700;color:{_gray};text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px'>Simulador de precio</div>", unsafe_allow_html=True)
        st.caption("Mueve el margen para ver como cambia el precio en tiempo real, sin recalcular.")
        _sim_m = st.slider("Margen de utilidad (%)", 5, 80, int(r["margen_pct"]), 1, key="sim_slider")
        _sim_p = r["costo_total"] / (1 - _sim_m / 100)
        _sim_u = _sim_p - r["costo_total"]
        _ss1, _ss2, _ss3 = st.columns(3)
        _ss1.metric("Precio sugerido", numero_completo(_sim_p), f"{numero_completo(abs(_sim_p - r['precio_sugerido']))} vs calculado")
        _ss2.metric("Utilidad neta", numero_completo(_sim_u))
        _ss3.metric("Margen", f"{_sim_m}%", "Saludable" if _sim_m >= 35 else "Bajo riesgo" if _sim_m < 20 else "Aceptable")
        if _sim_m < 20:
            alerta(f"Con {_sim_m}% de margen estas por debajo del minimo recomendado. Precio de quiebre (20%): {numero_completo(r['costo_total']/0.80)}", "bajo")

        # ── COMPARADOR A/B ─────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown(f"<div style='font-size:0.8rem;font-weight:700;color:{_gray};text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px'>Comparar con otro material</div>", unsafe_allow_html=True)
        _ab_on = st.toggle("Activar comparacion A/B", value=False, key="ab_toggle")
        if _ab_on:
            st.caption("Mismo proyecto, otro material. Compara precios al instante.")
            _ab1, _ab2, _ab3 = st.columns(3)
            _cat_b  = _ab1.selectbox("Material alternativo", [c for c in CATEGORIAS_MATERIAL if c != r["categoria"]], key="ab_cat")
            _prec_b = _ab2.number_input("Precio/m² alternativo", value=float(r["precio_m2"]), min_value=1000.0, step=5_000.0, format="%.0f", key="ab_px")
            _mrgb   = _ab3.slider("Margen alternativo (%)", 5, 80, int(r["margen_pct"]), key="ab_mrg")
            from calculos import calcular_cotizacion_directa as _ccd2
            _rb = _ccd2(
                categoria=_cat_b, referencia=f"{_cat_b} alternativo",
                precio_m2=_prec_b, area_placa_comprada=r["area_placa"],
                m2_real=r["m2_real"], m2_cortados=r.get("m2_cortados", r["m2_real"]),
                m2_usados=r.get("m2_usados", r["m2_real"]), margen_pct=_mrgb,
                dias=r.get("dias",1), personas=r.get("personas",2),
                zocalo_activo=(r["c3_zocalos"]>0), zocalo_ml=0.0,
                agente_externo_taller=(r["c5_detalle"]["agente"]>0),
                vehiculo_entrega=r.get("vehiculo_usado","frontier"), km=0, num_peajes=0,
                foraneo_activo=False, viaticos_activos=False, tipo_aloj="pueblo", noches=0,
                adicionales_activos=False, cantidades_add=[], etapa="terminada", adicionales_lista=ADICIONALES,
                ml_proyecto=r.get("ml_proyecto", r["m2_real"]/0.60),
            )
            _cA, _cB = st.columns(2)
            with _cA:
                st.markdown(f"<div style='background:{_blue};color:white;padding:8px 14px;border-radius:6px;font-weight:700;margin-bottom:8px'>{r['categoria']} (actual)</div>", unsafe_allow_html=True)
                bloque_costos([("Material",r["c1_material"]),("Produccion",r["c2_mano_obra"]),("Insumos",r["c4_insumos"]),("Logistica",r["c5_logistica"])],"PRECIO SUGERIDO",r["precio_sugerido"])
            with _cB:
                st.markdown(f"<div style='background:{_gold};color:{_navy};padding:8px 14px;border-radius:6px;font-weight:700;margin-bottom:8px'>{_cat_b} (alternativo)</div>", unsafe_allow_html=True)
                bloque_costos([("Material",_rb["c1_material"]),("Produccion",_rb["c2_mano_obra"]),("Insumos",_rb["c4_insumos"]),("Logistica",_rb["c5_logistica"])],"PRECIO SUGERIDO",_rb["precio_sugerido"])
            _diff = _rb["precio_sugerido"] - r["precio_sugerido"]
            alerta(f"El {_cat_b} resulta {numero_completo(abs(_diff))} {'mas caro' if _diff > 0 else 'mas economico'} que el {r['categoria']} para este proyecto.", "info")

        # ── EXPORTAR PDF ─────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown(f"<h4 style='color:{_navy}'>Exportar documentos</h4>", unsafe_allow_html=True)

        from generador_pdf import generar_pdf_cotizacion, generar_cuenta_cobro

        colp1, colp2 = st.columns(2)
        with colp1:
            st.markdown(f"<div style='font-size:0.85rem;font-weight:600;color:{_navy};margin-bottom:8px'>Cotizacion PDF</div>", unsafe_allow_html=True)
            num_cot = st.text_input("Numero de cotizacion", value=f"COT-{__import__('datetime').date.today().strftime('%Y')}-001", key="num_cot")
            logo_custom = st.session_state.logo_bytes
            emp_info = st.session_state.empresa_info
            if st.button("Generar PDF de cotizacion", type="primary", use_container_width=True):
                pdf_bytes = generar_pdf_cotizacion(r, numero=num_cot, empresa_info=emp_info, logo_bytes=logo_custom)
                nombre_pdf = f"{num_cot}_{nombre_cliente.replace(' ','_') if nombre_cliente else 'cotizacion'}.pdf"
                st.download_button("Descargar cotizacion PDF", pdf_bytes, file_name=nombre_pdf, mime="application/pdf", use_container_width=True)

        with colp2:
            st.markdown(f"<div style='font-size:0.85rem;font-weight:600;color:{_navy};margin-bottom:8px'>Cuenta de cobro PDF</div>", unsafe_allow_html=True)
            num_cc = st.text_input("Numero de cuenta de cobro", value=f"CC-{__import__('datetime').date.today().strftime('%Y')}-001", key="num_cc")
            nom_pag = st.text_input("Nombre de quien paga", value=nombre_cliente, key="nom_pag")
            nit_pag = st.text_input("NIT / CC de quien paga", value="", key="nit_pag")
            dir_pag = st.text_input("Direccion del pagador", value="", key="dir_pag")
            if st.button("Generar cuenta de cobro PDF", type="primary", use_container_width=True):
                datos_prest = emp_info.copy()
                datos_prest["nit_cc"] = emp_info.get("nit", "")
                datos_prest["direccion"] = emp_info.get("ciudad", "")
                datos_prest["telefono"] = emp_info.get("tel", "")
                datos_pag = {"nombre": nom_pag, "nit": nit_pag, "direccion": dir_pag}
                cc_bytes = generar_cuenta_cobro(r, datos_prest, datos_pag, numero=num_cc, logo_bytes=logo_custom)
                nombre_cc = f"{num_cc}_{nom_pag.replace(' ','_') if nom_pag else 'cuenta_cobro'}.pdf"
                st.download_button("Descargar cuenta de cobro PDF", cc_bytes, file_name=nombre_cc, mime="application/pdf", use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# COTIZACIÓN AIU
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Cotizacion AIU":
    st.markdown(f"<h2 style='color:{_text_main};font-family:Playfair Display,serif'>Cotizacion AIU</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:{_text_sub};font-size:0.88rem'>Para constructoras y licitaciones — estructura formal colombiana A+I+U+IVA</p>", unsafe_allow_html=True)

    LOG_ACT = get_logistica()
    VIA_ACT = get_viaticos()

    alerta("<strong>Estructura AIU:</strong> A = Administracion (2%) + I = Imprevistos (2%) + U = Utilidad (5%) + IVA 19% solo sobre Utilidad. Todo sobre el Costo Directo.", "info")

    # ── Items ────────────────────────────────────────────────────────────────
    seccion_titulo("Items del contrato")

    hdr = st.columns([4, 1, 1, 2, 0.5])
    for col, lbl in zip(hdr, ["Descripcion", "Unidad", "Cantidad", "Precio unitario (COP)", ""]):
        col.markdown(f"<div style='font-size:0.72rem;font-weight:700;color:{_gray};text-transform:uppercase;letter-spacing:0.06em;padding:4px 0'>{lbl}</div>", unsafe_allow_html=True)

    nuevos_items = []
    cd_total = 0.0
    for idx, it in enumerate(st.session_state.aiu_items):
        c0, c1, c2, c3, c4 = st.columns([4, 1, 1, 2, 0.5])
        desc   = c0.text_input("Desc", value=it["desc"], key=f"aiu_d_{idx}", label_visibility="collapsed")
        und    = c1.text_input("Und",  value=it["und"],  key=f"aiu_u_{idx}", label_visibility="collapsed")
        cant   = c2.number_input("Cant", value=float(it["cant"]), min_value=0.0, step=1.0, key=f"aiu_c_{idx}", label_visibility="collapsed")
        punit  = c3.number_input("PU", value=float(it["punit"]), min_value=0.0, step=5_000.0, key=f"aiu_p_{idx}", label_visibility="collapsed")
        sub    = cant * punit
        cd_total += sub
        c0.markdown(f"<div style='font-size:0.72rem;color:{_gray}'>Subtotal: {numero_completo(sub)}</div>", unsafe_allow_html=True)
        if c4.button("X", key=f"aiu_del_{idx}") and len(st.session_state.aiu_items) > 1:
            st.session_state.aiu_items.pop(idx)
            st.rerun()
        nuevos_items.append({"desc": desc, "und": und, "cant": cant, "punit": punit})
    st.session_state.aiu_items = nuevos_items

    if st.button("+ Agregar item"):
        st.session_state.aiu_items.append({"desc": "Nuevo item", "und": "glb", "cant": 1.0, "punit": 100_000})
        st.rerun()

    st.markdown(f"<div style='font-weight:700;color:{_navy};margin:10px 0'>Costo Directo: {numero_completo(cd_total)}</div>", unsafe_allow_html=True)
    st.markdown("---")

    # ── Porcentajes AIU ──────────────────────────────────────────────────────
    seccion_titulo("Porcentajes AIU")
    c1, c2, c3 = st.columns(3)
    with c1:
        pct_a = st.number_input("Administracion (%)", value=AIU_DEFAULTS["a"], min_value=0.0, max_value=20.0, step=0.5, format="%.1f")
    with c2:
        pct_i = st.number_input("Imprevistos (%)", value=AIU_DEFAULTS["i"], min_value=0.0, max_value=20.0, step=0.5, format="%.1f")
    with c3:
        pct_u = st.number_input("Utilidad (%)", value=AIU_DEFAULTS["u"], min_value=0.0, max_value=30.0, step=0.5, format="%.1f")

    st.markdown("---")
    seccion_titulo("Logistica")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        veh_aiu_lbl = st.selectbox("Vehiculo", list(VEHICULOS.keys()), key="aiu_veh")
        vehiculo_aiu = VEHICULOS[veh_aiu_lbl]
    with c2:
        km_aiu = st.number_input("Km", min_value=0.0, value=10.0, step=1.0, key="aiu_km")
    with c3:
        peajes_aiu = st.number_input("Peajes", min_value=0, value=0, step=1, key="aiu_pj")
    with c4:
        agente_aiu = st.checkbox("Agente externo al taller", key="aiu_ag")

    foraneo_aiu = st.checkbox("Proyecto foraneo", key="aiu_for")
    tipo_aloj_aiu = "pueblo"
    noches_aiu = 0
    pers_aiu = 2
    if foraneo_aiu:
        c1, c2, c3 = st.columns(3)
        tipo_aloj_aiu = ALOJAMIENTO[c1.selectbox("Destino", list(ALOJAMIENTO.keys()), key="aiu_aloj")]
        noches_aiu = c2.number_input("Noches", min_value=0, value=1, step=1, key="aiu_noch")
        pers_aiu = c3.number_input("Personas", min_value=1, value=2, step=1, key="aiu_per")

    if st.button("Calcular AIU", type="primary"):
        from calculos import calcular_aiu as _calc_aiu
        res_aiu = _calc_aiu(cd_total, pct_a, pct_i, pct_u, vehiculo_aiu, km_aiu, peajes_aiu,
                            agente_aiu, foraneo_aiu, tipo_aloj_aiu, noches_aiu, pers_aiu)

        hero_banner("Precio total del contrato", numero_completo(res_aiu['precio_total']),
            f"Margen efectivo: {res_aiu['margen_pct']:.1f}%   ·   CD: {numero_completo(cd_total)}")

        bloque_costos([
            ("Costo Directo (CD)",   res_aiu['cd']),
            (f"A — Administracion ({pct_a:.1f}%)", res_aiu['val_a']),
            (f"I — Imprevistos ({pct_i:.1f}%)",    res_aiu['val_i']),
            (f"U — Utilidad ({pct_u:.1f}%)",       res_aiu['val_u']),
            ("IVA 19% sobre Utilidad",             res_aiu['val_iva']),
            ("Logistica",                          res_aiu['logistica']),
            ("Viaticos",                           res_aiu['viaticos']),
        ], "PRECIO TOTAL DEL CONTRATO", res_aiu['precio_total'])


# ═══════════════════════════════════════════════════════════════════════════════
# PARAMETROS
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Historial":
    st.markdown(f"<h2 style='color:{_navy};font-family:Playfair Display,serif'>Historial de cotizaciones</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:{_gray};font-size:0.88rem'>Todas las cotizaciones guardadas automaticamente. Busca por cliente, numero o material.</p>", unsafe_allow_html=True)
    _bus = st.text_input("Buscar", placeholder="Nombre del cliente, numero o material...", key="hist_bus")
    _rows = _listar_cotizaciones(_bus)
    if not _rows:
        alerta("Aun no hay cotizaciones. Genera una y se guardara automaticamente.", "info")
    else:
        _ESTADOS = ["Pendiente", "Aprobada", "Rechazada", "En revision"]
        _hdr = st.columns([0.5, 1.2, 1.2, 2.2, 1.5, 1, 1.2, 1.2, 1.4])
        for _col, _lbl in zip(_hdr, ["#", "Numero", "Fecha", "Cliente", "Material", "ML", "Precio", "Margen", "Estado"]):
            _col.markdown(f"<div style='font-size:0.72rem;font-weight:700;color:{_gray};text-transform:uppercase'>{_lbl}</div>", unsafe_allow_html=True)
        st.markdown("<hr style='margin:4px 0 8px'>", unsafe_allow_html=True)
        for _row in _rows:
            _rid, _rnum, _rfec, _rcli, _rmat, _rml, _rpre, _rmrg, _rest = _row
            _cols = st.columns([0.5, 1.2, 1.2, 2.2, 1.5, 1, 1.2, 1.2, 1.4])
            _cols[0].markdown(f"<span style='font-size:0.8rem;color:{_gray}'>{_rid}</span>", unsafe_allow_html=True)
            _cols[1].markdown(f"<span style='font-size:0.8rem'>{_rnum}</span>", unsafe_allow_html=True)
            _cols[2].markdown(f"<span style='font-size:0.8rem;color:{_gray}'>{_rfec}</span>", unsafe_allow_html=True)
            _cols[3].markdown(f"<span style='font-size:0.85rem;font-weight:600;color:{_navy}'>{_rcli}</span>", unsafe_allow_html=True)
            _cols[4].markdown(f"<span style='font-size:0.8rem'>{_rmat}</span>", unsafe_allow_html=True)
            _cols[5].markdown(f"<span style='font-size:0.8rem'>{(_rml or 0):.1f} ml</span>", unsafe_allow_html=True)
            _cols[6].markdown(f"<span style='font-size:0.82rem;font-weight:700;color:{_navy}'>{numero_completo(_rpre)}</span>", unsafe_allow_html=True)
            _mrg_c = "#0A6E3F" if _rmrg >= 35 else "#92580A" if _rmrg >= 20 else "#981520"
            _cols[7].markdown(f"<span style='font-size:0.82rem;color:{_mrg_c}'>{_rmrg:.0f}%</span>", unsafe_allow_html=True)
            _est_sel = _cols[8].selectbox("Estado", _ESTADOS, index=_ESTADOS.index(_rest) if _rest in _ESTADOS else 0, key=f"est_{_rid}", label_visibility="collapsed")
            if _est_sel != _rest:
                _actualizar_estado(_rid, _est_sel)
                st.rerun()
        st.caption(f"{len(_rows)} cotizaciones encontradas")

elif pagina == "Dashboard":
    st.markdown(f"<h2 style='color:{_text_main};font-family:Playfair Display,serif'>Dashboard Gerencial</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:{_text_sub};font-size:0.88rem'>Metricas de tu negocio en tiempo real.</p>", unsafe_allow_html=True)
    _s = _stats_db()
    if _s["total"] == 0:
        alerta("Genera cotizaciones para ver las metricas aqui.", "info")
    else:
        _m1, _m2, _m3, _m4 = st.columns(4)
        _m1.metric("Total cotizaciones", _s["total"])
        _m2.metric("Aprobadas", _s["aprobadas"])
        _m3.metric("Pendientes", _s["pendientes"])
        _m4.metric("Facturacion (aprobadas)", numero_completo(_s["facturacion"]))
        st.markdown("---")
        _da, _db = st.columns(2)
        with _da:
            st.markdown(f"<div style='font-size:0.8rem;font-weight:700;color:{_gray};text-transform:uppercase;margin-bottom:8px'>Por material</div>", unsafe_allow_html=True)
            for _mat, _cnt, _mrg, _tot in (_s["por_material"] or []):
                _pct = min(100, (_tot / max(_s["facturacion"], 1)) * 100)
                st.markdown(
                    f'<div style="margin-bottom:10px"><div style="display:flex;justify-content:space-between;font-size:0.82rem">'
                    f'<span style="font-weight:600;color:{_navy}">{_mat}</span>'
                    f'<span style="color:{_gray}">{_cnt} cot. · {_mrg:.0f}% margen</span></div>'
                    f'<div style="background:{_gray_l};border-radius:4px;height:5px;margin-top:3px">'
                    f'<div style="background:{_blue};width:{_pct:.0f}%;height:5px;border-radius:4px"></div></div>'
                    f'<div style="font-size:0.76rem;color:{_gray};margin-top:2px">{numero_completo(_tot)}</div></div>',
                    unsafe_allow_html=True)
        with _db:
            st.markdown(f"<div style='font-size:0.8rem;font-weight:700;color:{_gray};text-transform:uppercase;margin-bottom:8px'>Ultimos 6 meses</div>", unsafe_allow_html=True)
            for _mes, _cnt, _tot in (_s["por_mes"] or []):
                _pct = min(100, (_tot / max(_s["facturacion"], 1)) * 100) if _s["facturacion"] > 0 else 0
                st.markdown(
                    f'<div style="margin-bottom:10px"><div style="display:flex;justify-content:space-between;font-size:0.82rem">'
                    f'<span style="font-weight:600;color:{_navy}">{_mes}</span>'
                    f'<span style="color:{_gray}">{_cnt} cotizaciones</span></div>'
                    f'<div style="background:{_gray_l};border-radius:4px;height:5px;margin-top:3px">'
                    f'<div style="background:{_gold};width:{_pct:.0f}%;height:5px;border-radius:4px"></div></div>'
                    f'<div style="font-size:0.76rem;color:{_gray};margin-top:2px">{numero_completo(_tot)}</div></div>',
                    unsafe_allow_html=True)
        st.markdown("---")
        _mc = "#0A6E3F" if _s["margen_prom"] >= 35 else "#92580A" if _s["margen_prom"] >= 20 else "#981520"
        st.markdown(
            f'<div style="background:{_blue_ul};border:1px solid {_blue_l};border-radius:10px;padding:16px 24px;display:inline-block">'
            f'<div style="font-size:2.4rem;font-weight:900;color:{_mc};font-family:Playfair Display,serif">{_s["margen_prom"]:.1f}%</div>'
            f'<div style="font-size:0.8rem;color:{_gray}">margen promedio en aprobadas</div></div>',
            unsafe_allow_html=True)

elif pagina == "Parametros":
    st.markdown(f"<h2 style='color:{_text_main};font-family:Playfair Display,serif'>Parametros de costos</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:{_text_sub};font-size:0.88rem;margin-bottom:4px'>Edita directamente los valores o deja que la IA te guie. Los cambios aplican inmediatamente a todos los calculos.</p>", unsafe_allow_html=True)

    # ── Inicializar custom params desde defaults si no existen ────────────────
    import copy
    if st.session_state.tarifas_custom is None:
        st.session_state.tarifas_custom = copy.deepcopy(TARIFAS)
    if st.session_state.logistica_custom is None:
        st.session_state.logistica_custom = copy.deepcopy(LOGISTICA)
    if st.session_state.viaticos_custom is None:
        st.session_state.viaticos_custom = copy.deepcopy(VIATICOS)

    TAR  = st.session_state.tarifas_custom
    LOG  = st.session_state.logistica_custom
    VIA  = st.session_state.viaticos_custom

    # ── Barra de acciones ─────────────────────────────────────────────────────
    col_act1, col_act2, col_act3 = st.columns([2, 2, 3])
    with col_act1:
        if st.button("Restaurar valores originales", use_container_width=True):
            st.session_state.tarifas_custom   = copy.deepcopy(TARIFAS)
            st.session_state.logistica_custom = copy.deepcopy(LOGISTICA)
            st.session_state.viaticos_custom  = copy.deepcopy(VIATICOS)
            st.success("Valores restaurados.")
            st.rerun()
    with col_act2:
        _cambios = (
            st.session_state.tarifas_custom != TARIFAS or
            st.session_state.logistica_custom != LOGISTICA or
            st.session_state.viaticos_custom  != VIATICOS
        )
        if _cambios:
            alerta("Tienes parametros personalizados activos — todos los calculos usan estos valores.", "bueno")
        else:
            alerta("Usando valores por defecto.", "info")

    st.markdown("---")

    # ═══ TABS ═════════════════════════════════════════════════════════════════
    t_ia, t1, t2, t3, t4 = st.tabs([
        "Asistente IA",
        "Costos de produccion",
        "Logistica",
        "Viaticos",
        "Mis vehiculos",
    ])

    # ── TAB: ASISTENTE IA ─────────────────────────────────────────────────────
    with t_ia:
        st.markdown(f"<p style='color:{_gray};font-size:0.85rem;margin-bottom:12px'>Describe tus costos reales y la IA actualiza los parametros automaticamente conforme conversas.</p>", unsafe_allow_html=True)

        if not ia_disponible():
            alerta("Configura tu API key de Anthropic para usar el asistente (ver barra lateral).", "acepta")
        else:
            alerta("La IA detecta los valores que menciones y los aplica en tiempo real. Puedes hablar de gasolina, rendimiento de tus vehiculos, tarifas de mano de obra, viaticos, etc.", "info")

        # Chat display
        chat_wizard = st.session_state.get("params_wizard_chat", [])
        chat_html = f'<div style="background:{_blue_ul};border:1px solid {_blue_l};border-radius:10px;padding:14px;max-height:380px;overflow-y:auto;margin-bottom:10px">'
        if not chat_wizard:
            chat_html += (
                f'<div style="background:{_navy};color:rgba(255,255,255,0.87);padding:12px 16px;'
                f'border-radius:4px 14px 14px 14px;font-size:0.87rem;line-height:1.65;max-width:92%">'
                f'Hola. Soy tu asistente de parametros.<br><br>'
                f'Cuéntame un valor que quieras actualizar y lo aplico de inmediato. Por ejemplo:<br>'
                f'<strong>· "La gasolina está a $16.200 el galón"</strong><br>'
                f'<strong>· "El flete a clientes nos cuesta $180.000"</strong><br>'
                f'<strong>· "La mano de obra de mármol subió a $80.000/m²"</strong><br><br>'
                f'¿Por donde empezamos?'
                f'</div>'
            )
        for _msg in chat_wizard:
            if _msg["role"] == "user":
                chat_html += (f'<div style="background:{_blue};color:white;padding:10px 14px;'
                    f'border-radius:14px 4px 14px 14px;font-size:0.87rem;max-width:85%;'
                    f'margin-left:auto;text-align:right;margin-top:10px">{_msg["content"]}</div>')
            else:
                _ct = _msg["content"].replace("\n", "<br>")
                chat_html += (f'<div style="background:{_navy};color:rgba(255,255,255,0.87);padding:12px 16px;'
                    f'border-radius:4px 14px 14px 14px;font-size:0.87rem;line-height:1.65;'
                    f'max-width:92%;margin-top:10px">{_ct}</div>')
        chat_html += '</div>'
        st.markdown(chat_html, unsafe_allow_html=True)

        with st.form("wizard_params_form", clear_on_submit=True):
            _c1, _c2 = st.columns([5, 1])
            _msg_w  = _c1.text_input("msg", label_visibility="collapsed",
                placeholder='Ej: "La gasolina está a $16.500 el galón"')
            _send_w = _c2.form_submit_button("Enviar", use_container_width=True)

        if _send_w and _msg_w.strip():
            chat_wizard.append({"role": "user", "content": _msg_w.strip()})

            # ── Llamada IA con extraccion de JSON de valores ──────────────────
            try:
                import anthropic as _ant, json as _json
                _client = _ant.Anthropic(api_key=st.secrets.get("ANTHROPIC_API_KEY",""))

                _SYSTEM = """Eres el asistente de parámetros de una calculadora de costos de marmolería en Colombia.
Tu trabajo: detectar valores numéricos en el mensaje del usuario y actualizar los parámetros correspondientes.

PARÁMETROS DISPONIBLES (usa exactamente estos nombres de clave):
- gasolina: precio COP por galón de gasolina corriente
- frontier_rend: km por galón Frontier NP300
- frontier_desgaste: COP por km de desgaste Frontier
- frontier_base: flete base Frontier por viaje
- cheyenne_rend: km por galón Cheyenne V8
- cheyenne_desgaste: COP por km de desgaste Cheyenne
- cheyenne_base: flete base Cheyenne por viaje
- flete_externo: tarifa fija flete externo/tercero
- flete_agente: flete agente externo (proveedor→taller)
- peaje: valor peaje ida+vuelta
- herram: desgaste herramientas por viaje
- viaticos_pueblo: tarifa por noche/persona en pueblo
- viaticos_ciudad: tarifa por noche/persona en ciudad
COSTOS DE PRODUCCIÓN (se paga por metro lineal, no por hora):
- marmol_prod_ml: COP que le pagas al operario por cada ml cortado e instalado en mármol
- marmol_zocalo: COP/ml de zócalo en mármol
- marmol_disco: COP/m² de disco en mármol
- marmol_maquina: COP/día de máquina en mármol
- granito_prod_ml, granito_zocalo, granito_disco, granito_maquina
- sinterizado_prod_ml, sinterizado_zocalo, sinterizado_disco, sinterizado_maquina
- quarztone_prod_ml, quarztone_zocalo, quarztone_disco, quarztone_maquina
- cuarcita_prod_ml, cuarcita_zocalo, cuarcita_disco, cuarcita_maquina

RESPONDE SIEMPRE en este formato JSON exacto:
{
  "actualizados": {"clave": valor_numerico, ...},
  "mensaje": "Texto de confirmacion corto para el usuario. Menciona los valores que aplicaste."
}

Si el usuario no menciona ningún valor numérico actualizable, deja "actualizados" vacío {} y responde con orientación.
SOLO JSON, sin texto antes ni después."""

                _messages = [{"role": m["role"], "content": m["content"]} for m in chat_wizard]
                _resp = _client.messages.create(
                    model="claude-opus-4-6",
                    max_tokens=500,
                    system=_SYSTEM,
                    messages=_messages,
                )
                _raw = _resp.content[0].text.strip()
                if _raw.startswith("```"):
                    _raw = _raw.split("```")[1]
                    if _raw.startswith("json"): _raw = _raw[4:]
                _data = _json.loads(_raw.strip())
            except Exception as _e:
                _data = {"actualizados": {}, "mensaje": f"Error al procesar: {str(_e)}"}

            # ── Aplicar valores extraidos a session_state ─────────────────────
            _aplicados = []
            _act = _data.get("actualizados", {})

            # Gasolina
            if "gasolina" in _act:
                st.session_state.logistica_custom["gasolina"] = float(_act["gasolina"])
                _aplicados.append(f"Gasolina: {numero_completo(_act['gasolina'])}/galon")

            # Vehiculos
            for _veh in ["frontier", "cheyenne"]:
                for _campo, _key in [("rend",f"{_veh}_rend"),("desgaste",f"{_veh}_desgaste"),("base",f"{_veh}_base")]:
                    if _key in _act:
                        st.session_state.logistica_custom[_veh][_campo] = float(_act[_key])
                        _aplicados.append(f"{_veh.capitalize()} {_campo}: {_act[_key]}")

            # Logistica general
            for _lk, _lpath in [
                ("flete_externo", ("externo","flete")),
                ("flete_agente",  None),
                ("peaje",         None),
                ("herram",        None),
            ]:
                if _lk in _act:
                    if _lpath:
                        st.session_state.logistica_custom[_lpath[0]][_lpath[1]] = float(_act[_lk])
                    else:
                        st.session_state.logistica_custom[_lk.replace("flete_","")] = float(_act[_lk])
                    _aplicados.append(f"{_lk}: {numero_completo(_act[_lk])}")

            # Viaticos
            if "viaticos_pueblo" in _act:
                st.session_state.viaticos_custom["pueblo"] = float(_act["viaticos_pueblo"])
                _aplicados.append(f"Viaticos pueblo: {numero_completo(_act['viaticos_pueblo'])}")
            if "viaticos_ciudad" in _act:
                st.session_state.viaticos_custom["ciudad"] = float(_act["viaticos_ciudad"])
                _aplicados.append(f"Viaticos ciudad: {numero_completo(_act['viaticos_ciudad'])}")

            # Tarifas por material
            _mat_map = {
                "Mármol": "marmol", "Granito": "granito",
                "Sinterizado": "sinterizado", "Quarztone": "quarztone", "Cuarcita": "cuarcita"
            }
            _campo_map = {"prod_ml":"prod_ml","zocalo":"zocalo","disco":"disco","maquina":"maquina"}
            for _mat_nombre, _mat_key in _mat_map.items():
                for _campo_key in _campo_map:
                    _full_key = f"{_mat_key}_{_campo_key}"
                    if _full_key in _act:
                        st.session_state.tarifas_custom[_mat_nombre][_campo_key] = float(_act[_full_key])
                        _aplicados.append(f"{_mat_nombre} {_campo_key}: {numero_completo(_act[_full_key])}")

            # Mensaje de respuesta
            _msg_resp = _data.get("mensaje", "Listo.")
            if _aplicados:
                _msg_resp += f" Aplicado: {', '.join(_aplicados[:3])}{'...' if len(_aplicados)>3 else '.' }"

            chat_wizard.append({"role": "assistant", "content": _msg_resp})
            st.session_state.params_wizard_chat = chat_wizard
            st.rerun()

        col_w1, col_w2 = st.columns(2)
        with col_w1:
            if st.button("Limpiar conversacion", use_container_width=True):
                st.session_state.params_wizard_chat = []
                st.rerun()
        with col_w2:
            st.caption("Los cambios se aplican inmediatamente y se reflejan en las tabs de abajo.")

    # ── TAB: TARIFAS DE TRABAJO ───────────────────────────────────────────────
    with t1:
        st.markdown(f"<p style='color:{_gray};font-size:0.85rem;margin-bottom:16px'>Edita directamente. Cada cambio aplica al guardar con el boton al final.</p>", unsafe_allow_html=True)

        _tar_editadas = copy.deepcopy(TAR)
        for _cat in CATEGORIAS_MATERIAL:
            _tar = _tar_editadas.get(_cat, TARIFAS[_cat])
            st.markdown(f"<div style='font-weight:700;color:{_navy};font-size:0.92rem;margin:18px 0 10px;border-left:3px solid {_blue};padding-left:10px'>{_cat}</div>", unsafe_allow_html=True)
            _tc1,_tc2,_tc3,_tc4,_tc5 = st.columns(5)
            _tar["corte"]    = _tc1.number_input("Corte/m²",    value=float(_tar.get("corte",0)),    min_value=0.0, step=1000.0, format="%.0f", key=f"tar_{_cat}_corte",    label_visibility="visible")
            _tar["elab"]     = _tc2.number_input("Elab./m²",    value=float(_tar.get("elab",0)),     min_value=0.0, step=1000.0, format="%.0f", key=f"tar_{_cat}_elab",     label_visibility="visible")
            _tar["zocalo"]   = _tc3.number_input("Zocalo/ml",   value=float(_tar.get("zocalo",0)),   min_value=0.0, step=500.0,  format="%.0f", key=f"tar_{_cat}_zocalo",   label_visibility="visible")
            _tar["disco"]    = _tc4.number_input("Disco/m²",    value=float(_tar.get("disco",0)),    min_value=0.0, step=100.0,  format="%.0f", key=f"tar_{_cat}_disco",    label_visibility="visible")
            _tar["desgaste"] = _tc5.number_input("Desg./dia",   value=float(_tar.get("desgaste",0)), min_value=0.0, step=1000.0, format="%.0f", key=f"tar_{_cat}_desgaste", label_visibility="visible")

            _tar_editadas[_cat] = _tar

        if st.button("Guardar tarifas de trabajo", type="primary", use_container_width=True, key="btn_guardar_tar"):
            st.session_state.tarifas_custom = _tar_editadas
            st.success("Tarifas guardadas. La calculadora ya usa estos valores.")
            st.rerun()

    # ── TAB: LOGISTICA ────────────────────────────────────────────────────────
    with t2:
        st.markdown(f"<p style='color:{_gray};font-size:0.85rem;margin-bottom:16px'>Actualiza precios de gasolina, tarifas de vehiculos y costos fijos de logistica.</p>", unsafe_allow_html=True)

        _log_ed = copy.deepcopy(LOG)

        seccion_titulo("Gasolina y costos generales", "")
        _lc1,_lc2,_lc3,_lc4 = st.columns(4)
        _log_ed["gasolina"]          = _lc1.number_input("Gasolina (COP/galon)", value=float(_log_ed["gasolina"]),              min_value=0.0, step=100.0, format="%.0f", key="log_gas")
        _log_ed["agente"]            = _lc2.number_input("Flete agente externo", value=float(_log_ed["agente"]),                min_value=0.0, step=1000.0,format="%.0f", key="log_ag")
        _log_ed["peaje"]             = _lc3.number_input("Peaje ida+vuelta",     value=float(_log_ed["peaje"]),                 min_value=0.0, step=500.0, format="%.0f", key="log_pj")
        _log_ed["herram"]            = _lc4.number_input("Desg. herramientas",   value=float(_log_ed["herram"]),                min_value=0.0, step=100.0, format="%.0f", key="log_hr")

        seccion_titulo("Frontier NP300", "")
        _fc1,_fc2,_fc3 = st.columns(3)
        _log_ed["frontier"]["rend"]    = _fc1.number_input("Rendimiento (km/galon)", value=float(_log_ed["frontier"]["rend"]),    min_value=0.1, step=0.1, format="%.1f", key="log_fr_rend")
        _log_ed["frontier"]["desgaste"]= _fc2.number_input("Desgaste (COP/km)",     value=float(_log_ed["frontier"]["desgaste"]),min_value=0.0, step=1.0, format="%.0f", key="log_fr_deg")
        _log_ed["frontier"]["base"]    = _fc3.number_input("Flete base (COP/viaje)",value=float(_log_ed["frontier"]["base"]),    min_value=0.0, step=1000.0,format="%.0f",key="log_fr_base")

        seccion_titulo("Cheyenne V8", "")
        _cc1,_cc2,_cc3 = st.columns(3)
        _log_ed["cheyenne"]["rend"]    = _cc1.number_input("Rendimiento (km/galon)", value=float(_log_ed["cheyenne"]["rend"]),    min_value=0.1, step=0.1, format="%.1f", key="log_ch_rend")
        _log_ed["cheyenne"]["desgaste"]= _cc2.number_input("Desgaste (COP/km)",     value=float(_log_ed["cheyenne"]["desgaste"]),min_value=0.0, step=1.0, format="%.0f", key="log_ch_deg")
        _log_ed["cheyenne"]["base"]    = _cc3.number_input("Flete base (COP/viaje)",value=float(_log_ed["cheyenne"]["base"]),    min_value=0.0, step=1000.0,format="%.0f",key="log_ch_base")

        seccion_titulo("Flete externo / Tercero", "")
        _log_ed["externo"]["flete"] = st.number_input("Tarifa fija flete externo (COP)", value=float(_log_ed["externo"]["flete"]), min_value=0.0, step=5000.0, format="%.0f", key="log_ext")

        if st.button("Guardar logistica", type="primary", use_container_width=True, key="btn_guardar_log"):
            st.session_state.logistica_custom = _log_ed
            st.success("Logistica guardada. La calculadora ya usa estos valores.")
            st.rerun()

    # ── TAB: VIATICOS ─────────────────────────────────────────────────────────
    with t3:
        st.markdown(f"<p style='color:{_gray};font-size:0.85rem;margin-bottom:16px'>Tarifa de alojamiento por persona por noche segun tipo de destino.</p>", unsafe_allow_html=True)

        _via_ed = copy.deepcopy(VIA)
        _vc1,_vc2 = st.columns(2)
        _via_ed["pueblo"] = _vc1.number_input("Pueblo / Corregimiento (COP/noche/persona)", value=float(_via_ed["pueblo"]), min_value=0.0, step=1000.0, format="%.0f", key="via_pueblo")
        _via_ed["ciudad"] = _vc2.number_input("Ciudad Capital (COP/noche/persona)",         value=float(_via_ed["ciudad"]), min_value=0.0, step=1000.0, format="%.0f", key="via_ciudad")

        if st.button("Guardar viaticos", type="primary", use_container_width=True, key="btn_guardar_via"):
            st.session_state.viaticos_custom = _via_ed
            st.success("Viaticos guardados.")
            st.rerun()

    # ── TAB: MIS VEHÍCULOS ────────────────────────────────────────────────────
    with t4:
        import copy as _cp2
        st.markdown(f"<p style='color:{_gray};font-size:0.85rem;margin-bottom:6px'>Agrega, edita o elimina los vehiculos que usas para transporte. Los cambios se reflejan de inmediato en los selectores de cotizacion.</p>", unsafe_allow_html=True)
        alerta("El asistente IA puede ayudarte a configurar un vehiculo nuevo. Escribe 'quiero agregar un vehiculo nuevo' en la tab Asistente IA.", "info")

        if st.session_state.get("vehiculos_custom") is None:
            st.session_state.vehiculos_custom = _cp2.deepcopy(VEHICULOS_CONFIG)
        VEH = _cp2.deepcopy(st.session_state.vehiculos_custom)
        _veh_a_eliminar = None

        for _vk, _vc in VEH.items():
            _es_propio  = _vc.get("tipo") == "propio"
            _is_default = _vk in ["frontier", "cheyenne", "externo"]
            with st.expander(f"{_vc.get('nombre', _vk)} — {'Propio' if _es_propio else 'Externo'}", expanded=False):
                _ca, _cb = st.columns([3, 1])
                _vc["nombre"]      = _ca.text_input("Nombre", value=_vc.get("nombre", _vk), key=f"vn_{_vk}", max_chars=40)
                _vc["descripcion"] = _ca.text_input("Descripcion (opcional)", value=_vc.get("descripcion",""), key=f"vd_{_vk}", max_chars=80)
                _tipo_sel = _cb.selectbox("Tipo", ["Propio", "Externo"], index=0 if _es_propio else 1, key=f"vt_{_vk}")
                _vc["tipo"] = "propio" if _tipo_sel == "Propio" else "externo"
                if _vc["tipo"] == "propio":
                    _p1, _p2, _p3 = st.columns(3)
                    _vc["rend"]     = _p1.number_input("Rendimiento (km/galon)", value=float(_vc.get("rend",7.0)), min_value=0.1, step=0.1, format="%.1f", key=f"vr_{_vk}", help="Cuantos km rinde 1 galon con carga")
                    _vc["desgaste"] = _p2.number_input("Desgaste mecanico (COP/km)", value=float(_vc.get("desgaste",148)), min_value=0.0, step=1.0, format="%.0f", key=f"vg_{_vk}", help="Costo de mantenimiento + depreciacion por km")
                    _vc["base"]     = _p3.number_input("Flete minimo (COP/viaje)", value=float(_vc.get("base",65_000)), min_value=0.0, step=1_000.0, format="%.0f", key=f"vb_{_vk}", help="Costo minimo por viaje sin importar la distancia")
                    _gas = (st.session_state.logistica_custom or LOGISTICA).get("gasolina", 16_000)
                    _ckm = (_gas / max(_vc["rend"], 0.1)) + _vc["desgaste"]
                    st.caption(f"Estimado: 10 km = {numero_completo(_vc['base'] + _ckm*20)} · 30 km = {numero_completo(_vc['base'] + _ckm*60)}")
                else:
                    _vc["flete"] = st.number_input("Tarifa fija por viaje (COP)", value=float(_vc.get("flete",165_000)), min_value=0.0, step=5_000.0, format="%.0f", key=f"vf_{_vk}", help="El transportista cobra este valor fijo por cada viaje")
                if not _is_default:
                    if st.button("Eliminar este vehiculo", key=f"del_{_vk}"):
                        _veh_a_eliminar = _vk
            VEH[_vk] = _vc

        if _veh_a_eliminar:
            del VEH[_veh_a_eliminar]
            st.session_state.vehiculos_custom = VEH
            st.success("Vehiculo eliminado.")
            st.rerun()

        st.markdown("---")
        seccion_titulo("Agregar vehiculo nuevo", "")
        with st.expander("Configurar nuevo vehiculo", expanded=False):
            _nc1, _nc2 = st.columns(2)
            _new_nom  = _nc1.text_input("Nombre del vehiculo", placeholder="Ej: Camion Hino 300", key="new_vn")
            _new_tipo = _nc2.selectbox("Tipo", ["Propio (gasolina/diesel)", "Externo (flete fijo)"], key="new_vt")
            _new_desc = st.text_input("Descripcion", placeholder="Opcional", key="new_vd")
            if "Propio" in _new_tipo:
                _n1, _n2, _n3 = st.columns(3)
                _new_rend = _n1.number_input("Rendimiento km/galon", value=7.0, min_value=0.1, step=0.1, format="%.1f", key="new_vr")
                _new_desg = _n2.number_input("Desgaste COP/km", value=148.0, min_value=0.0, step=1.0, format="%.0f", key="new_vg")
                _new_base = _n3.number_input("Flete minimo COP/viaje", value=65_000.0, min_value=0.0, step=1_000.0, format="%.0f", key="new_vb")
                _new_data = {"tipo":"propio","rend":_new_rend,"desgaste":_new_desg,"base":_new_base}
            else:
                _new_flete = st.number_input("Tarifa fija COP/viaje", value=165_000.0, min_value=0.0, step=5_000.0, format="%.0f", key="new_vf")
                _new_data  = {"tipo":"externo","flete":_new_flete}
            if st.button("Agregar vehiculo", type="primary", key="btn_add_veh"):
                if _new_nom.strip():
                    _nk = _new_nom.strip().lower().replace(" ","_")[:20]
                    if _nk in VEH: _nk += "_2"
                    _new_data.update({"nombre":_new_nom.strip(),"descripcion":_new_desc.strip()})
                    VEH[_nk] = _new_data
                    st.session_state.vehiculos_custom = VEH
                    st.success(f"Vehiculo '{_new_nom}' agregado.")
                    st.rerun()
                else:
                    st.warning("Escribe un nombre.")

        _sg1, _sg2 = st.columns(2)
        if _sg1.button("Guardar cambios", type="primary", use_container_width=True, key="btn_sv_veh"):
            st.session_state.vehiculos_custom = VEH
            st.success("Vehiculos guardados.")
            st.rerun()
        if _sg2.button("Restaurar originales", use_container_width=True, key="btn_rst_veh"):
            st.session_state.vehiculos_custom = _cp2.deepcopy(VEHICULOS_CONFIG)
            st.success("Restaurados.")
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# ASISTENTE IA
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Asistente IA":
    st.markdown(f"<h2 style='color:{_navy};font-family:Playfair Display,serif'>Asistente IA</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:{_gray};font-size:0.88rem'>Experto en costos de marmoleria · Barranquilla, Colombia · Powered by Claude</p>", unsafe_allow_html=True)

    if ia_disponible():
        alerta("IA Activa — Haz cualquier pregunta sobre costos, materiales, logistica o cotizacion.", "bueno")
    else:
        alerta("IA en modo basico — Configura tu API key (ver barra lateral).", "acepta")

    # ── Interpretar proyecto ──────────────────────────────────────────────────
    seccion_titulo("Describir proyecto para pre-llenar la calculadora")
    alerta("""Describe tu proyecto en tus propias palabras. Por ejemplo: <em>"Tengo que fabricar una cocina de 4mt de largo por 90cm de ancho, 
    el material es marmol Crema Marfil a $420.000/m², compre media placa, el proveedor trajo el material al taller, 
    voy a entregar en la Frontier 8 km, 2 peajes."</em>""", "info")

    with st.form("form_proyecto"):
        desc_proyecto = st.text_area("Describe tu proyecto aqui:", height=100,
            placeholder="Ej: Cocina de 4mt largo x 90cm ancho, marmol Crema Marfil $420.000/m², media placa 2.5m², Frontier 8km, 2 peajes...")
        btn_interpretar = st.form_submit_button("Interpretar proyecto y pre-llenar calculadora", use_container_width=True)

    if btn_interpretar and desc_proyecto.strip():
        if not ia_disponible():
            alerta("Necesitas configurar la API key de Anthropic para esta funcion.", "acepta")
        else:
            with st.spinner("Interpretando tu descripcion..."):
                datos = interpretar_proyecto(desc_proyecto)
            if datos:
                st.session_state.pre = datos
                st.session_state.cat_sel = datos.get("categoria", "Mármol")
                st.markdown("**Datos detectados:**")
                cols = st.columns(3)
                campo_labels = {
                    "categoria": "Tipo de material", "referencia": "Referencia",
                    "precio_m2": "Precio/m²", "area_placa_comprada": "Area comprada (m²)",
                    "m2_usados": "m² usados", "m2_proyecto": "m² del proyecto",
                    "tipo_proyecto": "Tipo de proyecto", "vehiculo_entrega": "Vehiculo",
                    "km": "Distancia (km)", "peajes": "Peajes",
                }
                mostrados = 0
                for campo, label in campo_labels.items():
                    val = datos.get(campo)
                    if val is not None and val is not False and val != 0:
                        cols[mostrados % 3].success(f"**{label}:** {val}")
                        mostrados += 1
                if datos.get("datos_faltantes"):
                    alerta("Datos no detectados (completa en la calculadora): " + ", ".join(datos["datos_faltantes"]), "acepta")
                alerta("Listo. Ve a <strong>Cotizacion Directa</strong> — los campos ya estan pre-llenados.", "bueno")
            else:
                alerta("No pude interpretar la descripcion. Intenta ser mas especifico.", "acepta")

    st.markdown("---")

    # ── Chat ──────────────────────────────────────────────────────────────────
    seccion_titulo("Chat con el asistente")
    preguntas_rapidas = [
        ("Que % AIU usar?",       "¿Qué porcentaje de AIU debo usar para una licitación con una constructora en Colombia?"),
        ("Margen saludable?",     "¿Cuál es el margen de utilidad saludable para una marmolería en Barranquilla?"),
        ("Estoy subcotizando?",   "¿Cómo sé si estoy subcotizando un proyecto de mármoles?"),
        ("Desgaste de maquina",   "¿Cómo calculo el desgaste de mi cortadora en los costos?"),
        ("Flete a Cartagena",     "¿Cuánto cuesta el flete de Barranquilla a Cartagena para un proyecto?"),
        ("Marmol vs Sinterizado", "¿Diferencia de costo entre trabajar mármol y sinterizado?"),
    ]
    c1, c2, c3 = st.columns(3)
    for idx, (label, preg) in enumerate(preguntas_rapidas):
        col = [c1, c2, c3][idx % 3]
        if col.button(label, key=f"qr_{idx}", use_container_width=True):
            st.session_state.chat.append({"role": "user", "content": preg})
            with st.spinner("Pensando..."):
                resp = chat_con_ia([m for m in st.session_state.chat[:-1]], preg)
            st.session_state.chat.append({"role": "assistant", "content": resp})
            st.rerun()

    st.markdown("---")

    chat_html = f'<div style="background:{_blue_ul};border:1px solid {_blue_l};border-radius:12px;padding:16px;max-height:520px;overflow-y:auto;margin-bottom:12px">'
    if not st.session_state.chat:
        chat_html += f'<div style="background:{_navy};color:rgba(255,255,255,0.85);padding:12px 16px;border-radius:4px 14px 14px 14px;font-size:0.87rem;line-height:1.65;max-width:90%">Hola. Soy el asistente de costos de <strong style="color:{_gold}">Marmoles Collante & Castro</strong>.<br><br>Puedo ayudarte de dos formas:<br>1. <strong>Describe tu proyecto</strong> arriba y pre-lleno la calculadora.<br>2. <strong>Hazme cualquier pregunta</strong> sobre costos, materiales o cotizacion.<br><br>Por donde empezamos?</div>'
    for msg in st.session_state.chat:
        if msg["role"] == "user":
            chat_html += f'<div style="background:{_blue};color:white;padding:10px 16px;border-radius:14px 4px 14px 14px;font-size:0.87rem;line-height:1.6;max-width:85%;margin-left:auto;text-align:right;margin-top:10px">{msg["content"]}</div>'
        else:
            content = msg["content"].replace("\n", "<br>")
            chat_html += f'<div style="background:{_navy};color:rgba(255,255,255,0.87);padding:12px 16px;border-radius:4px 14px 14px 14px;font-size:0.87rem;line-height:1.7;max-width:90%;margin-top:10px">{content}</div>'
    chat_html += '</div>'
    st.markdown(chat_html, unsafe_allow_html=True)

    with st.form("chat_form", clear_on_submit=True):
        c1, c2 = st.columns([5, 1])
        msg_chat = c1.text_input("Pregunta", label_visibility="collapsed",
            placeholder="Ej: Cuanto deberia cobrar por 8m² de Crema Marfil en una cocina?")
        enviar = c2.form_submit_button("Enviar", use_container_width=True)

    if enviar and msg_chat.strip():
        st.session_state.chat.append({"role": "user", "content": msg_chat.strip()})
        with st.spinner("Escribiendo..."):
            resp = chat_con_ia([m for m in st.session_state.chat[:-1]], msg_chat.strip())
        st.session_state.chat.append({"role": "assistant", "content": resp})
        st.rerun()

    if st.session_state.chat:
        if st.button("Limpiar conversacion"):
            st.session_state.chat = []
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Configuracion":
    st.markdown(f"<h2 style='color:{_navy};font-family:Playfair Display,serif'>Configuracion</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:{_gray};font-size:0.88rem;margin-bottom:20px'>Personaliza la app con los datos de tu empresa y logo para los PDF</p>", unsafe_allow_html=True)

    tab_emp, tab_logo, tab_banco = st.tabs(["Datos de la empresa", "Logo y marca", "Datos bancarios"])

    with tab_emp:
        seccion_titulo("Datos de la empresa", "Aparecen en todos los PDF generados")
        emp = st.session_state.empresa_info
        c1, c2 = st.columns(2)
        with c1:
            emp["nombre"]  = st.text_input("Razon social", value=emp.get("nombre", ""))
            emp["nit"]     = st.text_input("NIT", value=emp.get("nit", ""))
            emp["tel"]     = st.text_input("Telefono", value=emp.get("tel", ""))
        with c2:
            emp["email"]   = st.text_input("Correo electronico", value=emp.get("email", ""))
            emp["ciudad"]  = st.text_input("Ciudad", value=emp.get("ciudad", ""))
        if st.button("Guardar datos de empresa", type="primary"):
            st.session_state.empresa_info = emp
            st.success("Datos guardados para esta sesion.")

    with tab_logo:
        seccion_titulo("Logo de la empresa", "El logo aparece en el encabezado de todos los PDF")
        alerta("Carga el logo en formato PNG o JPG. La app lo usara para personalizar los PDF de cotizacion y cuenta de cobro.", "info")

        logo_file = st.file_uploader("Cargar logo (PNG o JPG, max 2MB)", type=["png", "jpg", "jpeg"])
        if logo_file:
            logo_bytes = logo_file.read()
            logo_mime  = logo_file.type
            st.session_state.logo_bytes = logo_bytes
            st.session_state.logo_mime  = logo_mime
            st.image(logo_bytes, width=280)
            alerta("Logo cargado. Se usara en todos los PDF de esta sesion.", "bueno")
        elif st.session_state.logo_bytes:
            st.image(st.session_state.logo_bytes, width=280)
            alerta("Logo actual en uso.", "info")
            if st.button("Remover logo"):
                st.session_state.logo_bytes = None
                st.session_state.logo_mime  = None
                st.rerun()

    with tab_banco:
        seccion_titulo("Informacion bancaria", "Aparece en las cuentas de cobro")
        emp = st.session_state.empresa_info
        c1, c2 = st.columns(2)
        with c1:
            emp["banco"]        = st.text_input("Banco", value=emp.get("banco", "Davivienda"))
            emp["cuenta_tipo"]  = st.text_input("Tipo de cuenta", value=emp.get("cuenta_tipo", "Cuenta Corriente Empresas"))
        with c2:
            emp["cuenta_numero"] = st.text_input("Numero de cuenta", value=emp.get("cuenta_numero", ""))
        alerta("El nombre del titular se toma de la razon social ingresada en 'Datos de la empresa'.", "info")
        if st.button("Guardar datos bancarios", type="primary"):
            st.session_state.empresa_info = emp
            st.success("Datos bancarios guardados.")
