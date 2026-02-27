# app.py — CostoMármol v7 · Identidad de Marca MARMOLES COLLANTE & CASTRO LTDA.
# Rediseño completo con colores corporativos del logo + logo en sidebar y header

import io
import base64
import streamlit as st
import psycopg2
import json, os
from datetime import date, datetime
from calculos import (
    calcular_cotizacion_directa, analizar_precio_real,
    calcular_aiu, calcular_logistica, ml_a_m2, cop,
    calcular_totales_piezas,
)
from parametros import (
    CATEGORIAS_MATERIAL, ADICIONALES, ETAPAS_OBRA, VEHICULOS,
    ALOJAMIENTO, AIU_DEFAULTS, TARIFAS, LOGISTICA, VIATICOS,
    BADGE_COLORS, DESCRIPCIONES_CATEGORIA, MATERIALES_CATALOGO,
    ANCHOS_ESTANDAR, TIPOS_ML, TIPOS_M2, VEHICULOS_CONFIG, TOUR_PASOS,
)
from asistente_ia import chat_con_ia, ia_disponible, interpretar_proyecto, generar_resumen_cotizacion

st.set_page_config(
    page_title="CostoMármol — MARMOLES Collante & Castro",
    page_icon="🪨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── LOGO DE EMPRESA (hardcoded para identidad de marca) ───────────────────────
LOGO_EMPRESA_PATH = os.path.join(os.path.dirname(__file__), "logo_cc.jpeg")

def _cargar_logo_empresa():
    """Carga el logo corporativo de la empresa."""
    try:
        with open(LOGO_EMPRESA_PATH, "rb") as f:
            return f.read()
    except Exception:
        return None

# Carga el logo al inicio
_LOGO_BYTES = _cargar_logo_empresa()

def _logo_base64():
    if _LOGO_BYTES:
        return base64.b64encode(_LOGO_BYTES).decode()
    return None

# ── PALETA CORPORATIVA (extraída del logo) ───────────────────────────────────
# Azul marino profundo + Azul brillante + Dorado (del logo)
CC_COLORS = {
    "primary":    "#0D2137",   # Azul marino oscuro (fondo header)
    "secondary":  "#1B5FA8",   # Azul corporativo brillante
    "accent":     "#C9A84C",   # Dorado corporativo
    "light":      "#D6E8FA",   # Azul muy claro
    "ultralight": "#EEF5FD",   # Fondo alternado
    "gray":       "#6B85A0",   # Gris azulado
    "text":       "#0D2137",   # Texto oscuro
    "white":      "#FFFFFF",
}

# ── CSS CORPORATIVO CON IDENTIDAD DE MARCA ────────────────────────────────────
_logo_b64 = _logo_base64()
_logo_style = f"background-image:url('data:image/jpeg;base64,{_logo_b64}');" if _logo_b64 else ""

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700;900&family=Outfit:wght@300;400;500;600;700&display=swap');

* {{ box-sizing: border-box; }}
html, body, [class*="css"] {{ font-family: 'Outfit', sans-serif; }}

/* ── SIDEBAR BRAND ── */
[data-testid="stSidebar"] {{
    background: {CC_COLORS['primary']} !important;
    border-right: 2px solid {CC_COLORS['secondary']} !important;
}}
[data-testid="stSidebar"] * {{
    color: #E8F2FF !important;
}}
[data-testid="stSidebar"] .stRadio label {{
    color: #B8D4F0 !important;
    font-size: 0.88rem !important;
    font-weight: 500 !important;
    padding: 6px 8px !important;
    border-radius: 6px !important;
    transition: all 0.15s !important;
}}
[data-testid="stSidebar"] .stRadio label:hover {{
    background: rgba(27, 95, 168, 0.4) !important;
    color: #ffffff !important;
}}

/* ── LOGO SIDEBAR ── */
.sidebar-logo-wrap {{
    background: {CC_COLORS['primary']};
    padding: 20px 16px 12px;
    text-align: center;
    border-bottom: 1px solid rgba(27,95,168,0.4);
    margin-bottom: 8px;
}}
.sidebar-logo-wrap img {{
    max-width: 140px;
    max-height: 70px;
    object-fit: contain;
    filter: brightness(1.05);
}}
.sidebar-brand-name {{
    font-size: 0.62rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    color: {CC_COLORS['accent']} !important;
    text-transform: uppercase;
    margin-top: 8px;
}}
.sidebar-brand-sub {{
    font-size: 0.58rem;
    color: #7BA7D0 !important;
    margin-top: 2px;
}}

/* ── BUTTONS ── */
.stButton > button {{
    border-radius: 6px !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    font-family: 'Outfit', sans-serif !important;
    transition: all 0.18s ease !important;
    padding: 0.45rem 1rem !important;
}}
.stButton > button[kind="primary"] {{
    background: linear-gradient(135deg, {CC_COLORS['secondary']}, {CC_COLORS['primary']}) !important;
    color: white !important;
    border: none !important;
    box-shadow: 0 4px 14px rgba(27,95,168,0.35) !important;
    text-transform: uppercase !important;
    letter-spacing: 0.04em !important;
}}
.stButton > button[kind="primary"]:hover {{
    filter: brightness(1.12);
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 20px rgba(27,95,168,0.45) !important;
}}

/* ── CARDS ── */
.card-custom {{
    background: var(--secondary-background-color);
    border: 1px solid var(--border-color);
    border-radius: 10px;
    padding: 16px 18px;
    margin-bottom: 12px;
}}
.brand-card {{
    background: linear-gradient(135deg, {CC_COLORS['primary']} 0%, {CC_COLORS['secondary']} 100%);
    border-radius: 14px;
    padding: 32px 40px;
    margin-bottom: 24px;
    color: white;
    position: relative;
    overflow: hidden;
}}
.brand-card::before {{
    content: '';
    position: absolute;
    top: -20px; right: -20px;
    width: 120px; height: 120px;
    background: rgba(201,168,76,0.15);
    border-radius: 50%;
}}
.brand-card::after {{
    content: '';
    position: absolute;
    bottom: -30px; right: 60px;
    width: 80px; height: 80px;
    background: rgba(201,168,76,0.1);
    border-radius: 50%;
}}

/* ── METRIC CARDS ── */
.metric-brand {{
    background: var(--secondary-background-color);
    border-top: 3px solid {CC_COLORS['secondary']};
    border-radius: 8px;
    padding: 14px 16px;
}}

/* ── SECTION HEADERS ── */
.seccion-titulo {{
    font-family: 'Playfair Display', serif;
    color: {CC_COLORS['secondary']};
    font-size: 1.05rem;
    font-weight: 700;
    margin: 20px 0 8px;
    padding-bottom: 4px;
    border-bottom: 2px solid {CC_COLORS['light']};
}}

/* ── HERO PRICE CARD ── */
.precio-hero {{
    background: linear-gradient(135deg, {CC_COLORS['primary']} 0%, {CC_COLORS['secondary']} 100%);
    border-radius: 14px;
    padding: 28px 36px;
    margin: 8px 0 20px;
    color: white;
    border-left: 4px solid {CC_COLORS['accent']};
}}
</style>
""", unsafe_allow_html=True)

# ── INICIALIZACIÓN DE VARIABLES Y NAVEGACIÓN ──────────────────────────────────
if "primera_visita" not in st.session_state:
    st.session_state.primera_visita = True
    st.session_state.onboarding_activo = True
    st.session_state.onboarding_paso = 0
    st.session_state.tour_completado = False

if "nav_radio" not in st.session_state:
    st.session_state.nav_radio = "Inicio"

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
    q = "SELECT id,numero,fecha,cliente,material,ml,precio,margen,estado,datos_json FROM cotizaciones WHERE cliente ILIKE %s OR numero ILIKE %s OR material ILIKE %s ORDER BY id DESC LIMIT 200" if busqueda else "SELECT id,numero,fecha,cliente,material,ml,precio,margen,estado,datos_json FROM cotizaciones ORDER BY id DESC LIMIT 200"
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

def _eliminar_cotizacion(cot_id):
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM cotizaciones WHERE id=%s", (cot_id,))
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

def _chat_parametros(historial: list, mensaje: str) -> str:
    try:
        import anthropic
        api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
        if not api_key: return "Configura tu API key en .streamlit/secrets.toml"
        client = anthropic.Anthropic(api_key=api_key)
        SYSTEM_PARAMS = """Eres un asistente experto en costos de marmolería en Colombia... [Responde corto y directo]."""
        messages = [{"role": m["role"], "content": m["content"]} for m in historial]
        messages.append({"role": "user", "content": mensaje})
        response = client.messages.create(model="claude-opus-4-6", max_tokens=400, system=SYSTEM_PARAMS, messages=messages)
        return response.content[0].text
    except Exception as e:
        return f"Error: {str(e)}"

# ── HELPERS UI ────────────────────────────────────────────────────────────────
def alerta(texto, tipo="info"):
    if tipo == "bueno":
        st.success(texto, icon="✅")
    elif tipo == "acepta":
        st.warning(texto, icon="⚠️")
    elif tipo == "bajo":
        st.error(texto, icon="🚨")
    else:
        st.info(texto, icon="ℹ️")

def seccion_titulo(texto, subtexto=""):
    st.markdown(f'<div class="seccion-titulo">{texto}</div>', unsafe_allow_html=True)
    if subtexto:
        st.caption(subtexto)

def bloque_costos(items_label_valor, total_label, total_val):
    html = ""
    for label, valor in items_label_valor:
        html += f"""<div style="display:flex;justify-content:space-between;padding:6px 0; border-bottom:1px solid var(--border-color); color:var(--text-color);">
            <span style="font-size:0.87rem;">{label}</span><span style="font-size:0.87rem;font-weight:600">{cop(valor)}</span></div>"""
    html += f"""<div style="display:flex;justify-content:space-between;padding:10px 0 0 0; border-bottom:1px solid var(--border-color); color:var(--text-color);">
            <span style="font-size:0.95rem;font-weight:800">{total_label}</span><span style="font-size:0.95rem;font-weight:800;color:{CC_COLORS['secondary']}">{cop(total_val)}</span></div>"""
    st.markdown(f'<div class="card-custom">{html}</div>', unsafe_allow_html=True)

def numero_completo(valor):
    return f"${int(round(valor)):,}".replace(",", ".")

# ── SESSION STATE DATA ────────────────────────────────────────────────────────
_defaults = {
    "chat": [], "cotizacion": None, "contexto_cot": {}, "resumen_ia": "",
    "materiales_proyecto": [],
    "aiu_items": [
        {"desc": "Material pétreo (suministro)", "und": "m²",  "cant": 10.0, "punit": 250_000},
        {"desc": "Mano de obra corte y elaboración", "und": "m²", "cant": 10.0, "punit": 100_000},
        {"desc": "Instalación y nivelación",  "und": "m²",  "cant": 10.0, "punit": 50_000},
        {"desc": "Insumos (disco, adhesivo, silicona)", "und": "glb", "cant": 1.0, "punit": 150_000},
    ],
    "pre": {}, "piezas": [],
    "tarifas_custom": None, "logistica_custom": None, "viaticos_custom": None,
    "logo_bytes": None, "logo_mime": None,
    "empresa_info": {
        "nombre": "MARMOLES COLLANTE & CASTRO LTDA.", "nit": "NIT: 900.111.561-1",
        "tel": "+57 317 310 9675", "email": "facturascollantecastro@gmail.com",
        "ciudad": "Barranquilla, Atlántico — Colombia", "banco": "Davivienda",
        "cuenta_tipo": "Cuenta Corriente Empresas", "cuenta_numero": "108900027484",
        # Condiciones de pago por defecto
        "anticipo_pct": 60,
        "dias_entrega": 10,
        "dias_validez": 30,
    },
    "vehiculos_custom": None, "cat_sel": "Mármol",
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Inyectar logo corporativo como logo_bytes si no hay logo personalizado
if st.session_state.logo_bytes is None and _LOGO_BYTES:
    st.session_state.logo_bytes = _LOGO_BYTES

def get_tarifas(): return st.session_state.tarifas_custom or TARIFAS
def get_logistica(): return st.session_state.logistica_custom or LOGISTICA
def get_viaticos(): return st.session_state.viaticos_custom or VIATICOS
def get_vehiculos_config():
    import copy
    base = copy.deepcopy(VEHICULOS_CONFIG)
    custom = st.session_state.get("vehiculos_custom") or {}
    for k, v in custom.items(): base[k] = v
    return base
def get_vehiculos_dict():
    vc = get_vehiculos_config()
    return {f"{cfg.get('nombre', k)} ({'propio' if cfg.get('tipo')=='propio' else 'flete externo'})": k for k, cfg in vc.items()}

# ── SIDEBAR CON LOGO CORPORATIVO ──────────────────────────────────────────────
with st.sidebar:
    # Logo de la empresa
    if _logo_b64:
        st.markdown(
            f'<div class="sidebar-logo-wrap">'
            f'<img src="data:image/jpeg;base64,{_logo_b64}" alt="MARMOLES Collante & Castro"/>'
            f'<div class="sidebar-brand-name">Sistema de Cotización</div>'
            f'<div class="sidebar-brand-sub">Uso Exclusivo Interno</div>'
            f'</div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            f'<div style="background:{CC_COLORS["primary"]};border-bottom:1px solid rgba(27,95,168,0.4);'
            f'padding:20px 16px 12px;text-align:center;margin-bottom:8px">'
            f'<div style="color:{CC_COLORS["accent"]};font-size:2rem;font-weight:900;font-family:Playfair Display,serif;">CC</div>'
            f'<div style="font-size:0.65rem;color:{CC_COLORS["accent"]};font-weight:700;letter-spacing:0.1em;margin-top:6px">MARMOLES C&C</div>'
            f'</div>',
            unsafe_allow_html=True
        )

    opciones_menu = ["Inicio", "Cotizacion Directa", "Cotizacion AIU", "Historial", "Dashboard", "Parametros", "Asistente IA", "Configuracion"]

    _nav_idx = opciones_menu.index(st.session_state.nav_radio) if st.session_state.nav_radio in opciones_menu else 0
    _seleccion = st.radio("Menú", opciones_menu, index=_nav_idx, label_visibility="collapsed")
    if _seleccion != st.session_state.nav_radio:
        st.session_state.nav_radio = _seleccion
        st.rerun()
    pagina = st.session_state.nav_radio

    st.markdown('<hr style="margin:12px 0;border-color:rgba(27,95,168,0.3)">', unsafe_allow_html=True)
    if ia_disponible():
        st.markdown('<div style="background:rgba(74,222,128,0.15);border:1px solid rgba(74,222,128,0.3);border-radius:6px;padding:7px 10px;font-size:0.75rem;font-weight:600;color:#4ade80">🟢 IA Activa</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="background:rgba(251,191,36,0.12);border:1px solid rgba(251,191,36,0.25);border-radius:6px;padding:7px 10px;font-size:0.75rem;font-weight:600;color:#fbbf24">🟠 IA sin configurar</div>', unsafe_allow_html=True)

    st.markdown(
        f'<div style="margin-top:16px;padding:10px 8px;font-size:0.65rem;color:#4a7aaa;line-height:1.5">'
        f'<b style="color:#7BA7D0">MARMOLES COLLANTE & CASTRO LTDA.</b><br>'
        f'NIT: 900.111.561-1<br>'
        f'+57 317 310 9675</div>',
        unsafe_allow_html=True
    )

# ═══════════════════════════════════════════════════════════════════════════════
# TOUR GUIADO
# ═══════════════════════════════════════════════════════════════════════════════
if st.session_state.get("onboarding_activo"):
    _op = min(st.session_state.get("onboarding_paso", 0), len(TOUR_PASOS) - 1)
    _paso = TOUR_PASOS[_op]
    _total = len(TOUR_PASOS)

    with st.container(border=True):
        st.markdown(f"### <span style='color:{CC_COLORS['secondary']}'>{_paso['icono']}</span> {_paso['titulo']}", unsafe_allow_html=True)
        st.caption(f"PASO {_op + 1} DE {_total}")
        st.markdown(_paso["cuerpo"].replace('\n', '\n\n'))
        st.progress((_op + 1) / _total)

        c1, c2, c3 = st.columns(3)
        with c1:
            if _op > 0:
                if st.button("⬅ Anterior", use_container_width=True):
                    st.session_state.onboarding_paso -= 1
                    st.rerun()
        with c2:
            if st.button("✕ Saltar guía", use_container_width=True):
                st.session_state.onboarding_activo = False
                st.session_state.tour_completado = True
                st.rerun()
        with c3:
            if _op < _total - 1:
                if st.button("Siguiente ➡", type="primary", use_container_width=True):
                    st.session_state.onboarding_paso += 1
                    st.rerun()
            else:
                if st.button("🚀 Finalizar y usar app", type="primary", use_container_width=True):
                    st.session_state.onboarding_activo = False
                    st.session_state.tour_completado = True
                    st.rerun()
    st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# INICIO
# ═══════════════════════════════════════════════════════════════════════════════
if pagina == "Inicio":
    # Hero con logo y branding
    col_logo, col_texto = st.columns([1, 2.5])
    with col_logo:
        if _logo_b64:
            st.markdown(
                f'<div style="padding:16px;background:white;border-radius:12px;box-shadow:0 4px 20px rgba(13,33,55,0.12);text-align:center">'
                f'<img src="data:image/jpeg;base64,{_logo_b64}" style="max-width:220px;max-height:120px;object-fit:contain"/>'
                f'</div>',
                unsafe_allow_html=True
            )
    with col_texto:
        st.markdown(f"""
        <div class="brand-card">
          <div style="color:{CC_COLORS['accent']};font-size:0.65rem;text-transform:uppercase;letter-spacing:0.18em;font-weight:800;margin-bottom:10px">
            Sistema de Cotización Profesional
          </div>
          <div style="font-size:2.2rem;font-weight:900;font-family:'Playfair Display',serif;line-height:1.1;margin-bottom:12px">
            MARMOLES<br>COLLANTE & CASTRO LTDA.
          </div>
          <div style="opacity:0.85;font-size:0.88rem;line-height:1.65;">
            Herramienta de uso exclusivo interno · NIT 900.111.561-1<br>
            Barranquilla, Atlántico — Colombia
          </div>
        </div>
        """, unsafe_allow_html=True)

    if st.button("🚀 Reactivar Guía de Inicio", use_container_width=True):
        st.session_state.onboarding_activo = True
        st.session_state.onboarding_paso = 0
        st.rerun()

    st.markdown("---")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Materiales", "5 tipos", "Mármol · Granito · Sint. · Quartz · Cuarcita")
    c2.metric("Tiempo", "2 min", "vs. 45–90 min manual")
    c3.metric("Estructura", "AIU + IVA", "Norma colombiana")
    c4.metric("Exporta", "PDF", "Cotización + Cuenta de cobro")


# ═══════════════════════════════════════════════════════════════════════════════
# COTIZACIÓN DIRECTA
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Cotizacion Directa":
    st.markdown("<h2 style='font-family:Playfair Display,serif;margin-bottom:4px'>Cotización Directa</h2>", unsafe_allow_html=True)
    st.markdown("<p style='opacity:0.7;font-size:0.88rem;margin-bottom:20px'>Para proyectos residenciales y clientes particulares</p>", unsafe_allow_html=True)

    pre = st.session_state.pre
    if pre:
        alerta("Datos cargados exitosamente (desde Historial o IA). Revisa y ajusta lo que necesites.", "bueno")
        if st.button("Limpiar formulario"):
            st.session_state.pre = {}
            st.session_state.piezas = []
            st.session_state.materiales_proyecto = []
            st.rerun()

    TARIFAS_ACT = get_tarifas()
    LOG_ACT = get_logistica()
    VIA_ACT = get_viaticos()

    # ── PASO 1: MATERIAL(ES) ─────────────────────────────────────────────────
    seccion_titulo("Paso 1 — Material(es)", "Puedes agregar uno o más materiales si el proyecto mezcla referencias")

    if "materiales_proyecto" not in st.session_state or not st.session_state.materiales_proyecto:
        st.session_state.materiales_proyecto = pre.get("materiales_proyecto", [
            {"cat": pre.get("categoria", "Mármol"), "ref": pre.get("referencia", ""), "precio_m2": pre.get("precio_m2", 220_000), "area_placa": pre.get("area_placa_comprada", 5.94)}
        ])

    mats = st.session_state.materiales_proyecto
    mats_nuevos = []

    for midx, mat_item in enumerate(mats):
        with st.container(border=True):
            cola, colb, colc, cold = st.columns([1.8, 1.5, 1.5, 0.4])
            with cola:
                cats_opts = CATEGORIAS_MATERIAL
                cat_i = cats_opts.index(mat_item.get("cat", "Mármol")) if mat_item.get("cat") in cats_opts else 0
                cat_sel_m = st.selectbox("Categoría", cats_opts, index=cat_i, key=f"mcat_{midx}", label_visibility="collapsed" if midx > 0 else "visible")
            with colb:
                refs_m = ["Otra referencia..."] + [m["nombre"] for m in MATERIALES_CATALOGO if m["categoria"] == cat_sel_m]
                pre_ref_m = mat_item.get("ref", "")
                idx_ref_m = refs_m.index(pre_ref_m) if pre_ref_m in refs_m else 0
                ref_sel_m = st.selectbox("Referencia", refs_m, index=idx_ref_m, key=f"mref_{midx}", label_visibility="visible" if midx == 0 else "collapsed")
                if ref_sel_m == "Otra referencia...":
                    referencia_m = st.text_input("Nombre", value=pre_ref_m if pre_ref_m not in refs_m else "", key=f"mrefcust_{midx}", placeholder="Ej: Calacatta Gold")
                else:
                    referencia_m = ref_sel_m
            with colc:
                precio_m2_m = st.number_input("Precio/m² (COP)", min_value=10_000, max_value=5_000_000,
                    value=int(mat_item.get("precio_m2", 220_000)), step=1_000, key=f"mpm2_{midx}",
                    label_visibility="visible" if midx == 0 else "collapsed")
                area_placa_m = st.number_input("Área comprada (m²)", min_value=0.01, max_value=200.0,
                    value=float(mat_item.get("area_placa", 5.94)), step=0.1, key=f"maplaca_{midx}", format="%.3f",
                    label_visibility="visible" if midx == 0 else "collapsed")
            with cold:
                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                if len(mats) > 1 and st.button("✕", key=f"mdel_{midx}"):
                    st.session_state.materiales_proyecto.pop(midx)
                    st.rerun()

            costo_m = precio_m2_m * area_placa_m
            st.caption(f"Costo: {numero_completo(precio_m2_m)}/m² × {area_placa_m} m² = **{numero_completo(costo_m)}**")
            mats_nuevos.append({"cat": cat_sel_m, "ref": referencia_m, "precio_m2": precio_m2_m, "area_placa": area_placa_m})

    st.session_state.materiales_proyecto = mats_nuevos

    col_addmat, _ = st.columns([1, 3])
    with col_addmat:
        if st.button("+ Agregar otro material", use_container_width=True):
            st.session_state.materiales_proyecto.append({"cat": "Mármol", "ref": "", "precio_m2": 220_000, "area_placa": 5.94})
            st.rerun()

    cat_sel = mats_nuevos[0]["cat"] if mats_nuevos else "Mármol"
    referencia = " + ".join([m["ref"] or m["cat"] for m in mats_nuevos]) if len(mats_nuevos) > 1 else (mats_nuevos[0]["ref"] if mats_nuevos else "")
    precio_m2 = mats_nuevos[0]["precio_m2"] if mats_nuevos else 220_000
    area_placa = sum(m["area_placa"] for m in mats_nuevos)
    costo_mat_total = sum(m["precio_m2"] * m["area_placa"] for m in mats_nuevos)
    precio_m2_efectivo = costo_mat_total / area_placa if area_placa > 0 else precio_m2

    alerta(f"Total material: **{numero_completo(costo_mat_total)}** en {area_placa:.2f} m² comprados", "info")

    st.markdown("---")

    # ── PASO 2: DIMENSIONES ──────────────────────────────────────────────────
    seccion_titulo("Paso 2 — Piezas del proyecto",
                   "ML = mesones, baños, escaleras  |  m² = pisos, revestimientos, fachadas")

    if "piezas" not in st.session_state or not st.session_state.piezas:
        st.session_state.piezas = pre.get("piezas", [
            {"nombre": "Mesón de cocina", "largo": 2.0, "ancho": 0.60,
             "tipo_sup": "Mesón de cocina", "unidad_venta": "ml", "precio_unitario": 0.0}
        ])

    _mostrar_avanzado = st.session_state.get("modo_avanzado_medidas", False)
    if not _mostrar_avanzado:
        if st.button("⚙️ Modo avanzado (m² directo)", key="btn_avanzado"):
            st.session_state.modo_avanzado_medidas = True
            st.rerun()
    else:
        if st.button("← Volver al modo por piezas", key="btn_simple"):
            st.session_state.modo_avanzado_medidas = False
            st.rerun()

    TODOS_TIPOS = list(ANCHOS_ESTANDAR.keys())

    m2_real = 0.0
    m2_cortados_total = 0.0

    if not _mostrar_avanzado:
        # ── CABECERA DE TABLA ──────────────────────────────────────────────
        hdr = st.columns([2.8, 1.1, 2.6, 1.2, 1.3, 1.8, 0.5])
        for col, lbl in zip(hdr, ["Descripción", "Largo", "Tipo de pieza", "Ancho m", "Unidad venta", "Cantidad / m²", ""]):
            col.markdown(
                f"<div style='font-size:0.68rem;font-weight:700;opacity:0.55;text-transform:uppercase;padding-bottom:2px'>{lbl}</div>",
                unsafe_allow_html=True)

        piezas_nuevas = []
        for idx, pieza in enumerate(st.session_state.piezas):
            c0, c1, c2, c3, c4, c5, c6 = st.columns([2.8, 1.1, 2.6, 1.2, 1.3, 1.8, 0.5])
            with c0:
                nombre_p = st.text_input("Desc", value=pieza.get("nombre", ""), key=f"pnom_{idx}",
                                         label_visibility="collapsed", placeholder="Ej: Mesón cocina")
            with c1:
                largo_p = st.number_input("Largo", value=float(pieza.get("largo", pieza.get("ml", 1.0))),
                                          min_value=0.01, step=0.1, format="%.2f",
                                          key=f"plargo_{idx}", label_visibility="collapsed")
            with c2:
                tipo_idx = TODOS_TIPOS.index(pieza.get("tipo_sup", TODOS_TIPOS[0])) \
                           if pieza.get("tipo_sup") in TODOS_TIPOS else 0
                tipo_p = st.selectbox("Tipo", TODOS_TIPOS, index=tipo_idx,
                                      key=f"ptip_{idx}", label_visibility="collapsed")
            with c3:
                cfg_tipo = ANCHOS_ESTANDAR[tipo_p]
                ancho_default = cfg_tipo["ancho"] if cfg_tipo["ancho"] is not None \
                                else float(pieza.get("ancho", 0.60))
                ancho_p = st.number_input("Ancho", value=float(ancho_default),
                                          min_value=0.01, step=0.01, format="%.2f",
                                          key=f"panc_{idx}", label_visibility="collapsed")
            with c4:
                uv_default = cfg_tipo.get("unidad_venta", pieza.get("unidad_venta", "ml"))
                uv_idx = 0 if uv_default == "ml" else 1
                uv_p = st.selectbox("UV", ["ml", "m²"], index=uv_idx,
                                    key=f"puv_{idx}", label_visibility="collapsed")
            m2_p = ml_a_m2(largo_p, ancho_p)
            with c5:
                if uv_p == "ml":
                    st.markdown(
                        f"<div style='padding:6px 4px;font-size:0.82rem'>"
                        f"<b style='color:{CC_COLORS['secondary']}'>{largo_p:.2f} ml</b>"
                        f"<br><span style='opacity:0.5;font-size:0.7rem'>{m2_p:.3f} m²</span></div>",
                        unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<div style='padding:6px 4px;font-size:0.82rem'>"
                        f"<b style='color:{CC_COLORS['accent']}'>{m2_p:.3f} m²</b>"
                        f"<br><span style='opacity:0.5;font-size:0.7rem'>{largo_p:.2f}×{ancho_p:.2f}</span></div>",
                        unsafe_allow_html=True)
            with c6:
                if st.button("✕", key=f"del_{idx}") and len(st.session_state.piezas) > 1:
                    st.session_state.piezas.pop(idx)
                    st.rerun()

            piezas_nuevas.append({
                "nombre":        nombre_p,
                "largo":         largo_p,
                "ancho":         ancho_p,
                "tipo_sup":      tipo_p,
                "unidad_venta":  uv_p,
                "precio_unitario": pieza.get("precio_unitario", 0.0),
            })

        st.session_state.piezas = piezas_nuevas

        # ── BOTONES AGREGAR ────────────────────────────────────────────────
        col_addml, col_addm2, col_sum = st.columns([1.1, 1.1, 2])
        with col_addml:
            if st.button("＋ Pieza ML", use_container_width=True,
                         help="Mesón, baño, lavamanos, escalón, salpicadero…"):
                st.session_state.piezas.append({
                    "nombre": f"Pieza {len(st.session_state.piezas)+1}",
                    "largo": 1.0, "ancho": 0.60,
                    "tipo_sup": "Mesón de cocina", "unidad_venta": "ml", "precio_unitario": 0.0
                })
                st.rerun()
        with col_addm2:
            if st.button("＋ Pieza m²", use_container_width=True,
                         help="Piso, revestimiento de pared, fachada, terraza…"):
                st.session_state.piezas.append({
                    "nombre": f"Piso {len(st.session_state.piezas)+1}",
                    "largo": 3.0, "ancho": 2.0,
                    "tipo_sup": "Piso / Pavimento", "unidad_venta": "m²", "precio_unitario": 0.0
                })
                st.rerun()

        # ── RESUMEN VISUAL ─────────────────────────────────────────────────
        tots = calcular_totales_piezas(st.session_state.piezas)
        ml_t   = tots["ml_total"]
        m2v_t  = tots["m2_total"]
        m2mat_t = tots["m2_material"]

        with col_sum:
            partes_html = ""
            if ml_t > 0:
                partes_html += (
                    f'<div style="font-size:1.55rem;font-weight:900;font-family:Playfair Display,serif;'
                    f'color:{CC_COLORS["secondary"]}">{ml_t:.2f} '
                    f'<span style="font-size:0.85rem;font-weight:600">ml</span></div>'
                )
            if m2v_t > 0:
                partes_html += (
                    f'<div style="font-size:1.55rem;font-weight:900;font-family:Playfair Display,serif;'
                    f'color:{CC_COLORS["accent"]}">{m2v_t:.3f} '
                    f'<span style="font-size:0.85rem;font-weight:600">m²</span></div>'
                )
            partes_html += f'<div style="font-size:0.75rem;opacity:0.6;margin-top:3px">Material a comprar: <b>{m2mat_t:.3f} m²</b></div>'

            st.markdown(
                f'<div style="background:var(--secondary-background-color);'
                f'border:2px solid {CC_COLORS["secondary"]};'
                f'border-radius:10px;padding:10px 16px;text-align:center">'
                f'<div style="font-size:0.65rem;text-transform:uppercase;letter-spacing:0.09em;'
                f'font-weight:700;opacity:0.55;margin-bottom:4px">Total del proyecto</div>'
                f'{partes_html}'
                f'</div>',
                unsafe_allow_html=True)

        extra_corte = st.number_input(
            "m² adicionales de desperdicios / recortes imprevistos",
            min_value=0.0, value=0.0, step=0.05, key="extra_corte")

        m2_real          = m2mat_t
        m2_cortados_total = m2mat_t + extra_corte

    else:
        # ── MODO AVANZADO: m² directo ─────────────────────────────────────
        alerta("Modo avanzado: ingresa m² directamente. Mano de obra estimada con ancho promedio.", "acepta")
        c1, c2 = st.columns(2)
        with c1:
            m2_real = st.number_input("m² reales del proyecto", min_value=0.01,
                                      value=float(pre.get("m2_proyecto", 4.0)), step=0.05)
        with c2:
            m2_cortados_input = st.number_input("m² cortados con desperdicios", min_value=0.0,
                                                value=float(m2_real), step=0.05)
            m2_cortados_total = m2_cortados_input if m2_cortados_input > 0 else m2_real

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    with c1:
        m2_usados = st.number_input("m² finalmente instalados", min_value=0.0,
                                    value=float(pre.get("m2_usados", m2_real)), step=0.05)
    with c2:
        margen_pct = st.slider("Margen de utilidad (%)", min_value=5, max_value=80,
                               value=int(pre.get("margen_pct", 40)), step=1)
    with c3:
        if area_placa > 0 and m2_usados > 0:
            aprv     = min(100, m2_usados / area_placa * 100)
            retal_v  = max(0, area_placa - m2_usados)
            estado_a = "bueno" if aprv >= 80 else "acepta" if aprv >= 50 else "bajo"
            alerta(f"Aprovechamiento: **{aprv:.1f}%** — Retal: {retal_v:.3f} m²", estado_a)

    st.markdown("---")

    # ── PASO 3: PROYECTO ─────────────────────────────────────────────────────
    seccion_titulo("Paso 3 — Tipo de proyecto y obra")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        tipo_opts = ["Mesón", "Cocina", "Baño", "Piso", "Escalera", "Fachada", "Mueble de cocina", "Otro"]
        pre_tipos = pre.get("tipos_proyecto", [pre.get("tipo_proyecto", "Mesón")] if pre.get("tipo_proyecto") else ["Mesón"])
        tipos_sel = st.multiselect(
            "Tipo(s) de proyecto", tipo_opts,
            default=[t for t in pre_tipos if t in tipo_opts] or ["Mesón"],
        )
        tipo = " + ".join(tipos_sel) if tipos_sel else "Otro"
    with c2:
        etapa = ETAPAS_OBRA[st.selectbox("Etapa de la obra", list(ETAPAS_OBRA.keys()))]
    with c3:
        dias = st.number_input("Días en obra", min_value=1, value=int(pre.get("dias_obra", 2)), step=1)
    with c4:
        personas = st.number_input("Núm. de personas", min_value=1, value=int(pre.get("personas", 2)), step=1)

    nombre_cliente = st.text_input("Nombre del cliente", value=pre.get("nombre_cliente", ""), placeholder="Ej: Juan García / Constructora XYZ")

    st.markdown("**Zócalos**")
    zocalo_activo = st.checkbox("Este proyecto lleva zócalos", value=pre.get("zocalo_activo", False))
    zocalo_ml = 0.0
    if zocalo_activo:
        zocalo_ml = st.number_input("Metros lineales de zócalo (ml)", min_value=0.0, value=float(pre.get("zocalo_ml", 2.0)), step=0.5)

    st.markdown("---")

    # ── PASO 4: CONDICIONES DE PAGO ──────────────────────────────────────────
    seccion_titulo("Paso 4 — Condiciones de pago y entrega")
    emp_info = st.session_state.empresa_info
    c_ant, c_dias, c_val = st.columns(3)
    with c_ant:
        anticipo_pct = st.number_input(
            "% de anticipo a cobrar", min_value=0, max_value=100,
            value=int(emp_info.get("anticipo_pct", 60)), step=5,
            help="Porcentaje del valor total que se cobra como anticipo"
        )
    with c_dias:
        dias_entrega = st.number_input(
            "Días de entrega", min_value=1,
            value=int(emp_info.get("dias_entrega", 10)), step=1
        )
    with c_val:
        dias_validez = st.number_input(
            "Días de validez de la cotización", min_value=1,
            value=int(emp_info.get("dias_validez", 30)), step=5
        )
    # Guardar en session para usarlo en el PDF
    st.session_state.empresa_info["anticipo_pct"] = anticipo_pct
    st.session_state.empresa_info["dias_entrega"] = dias_entrega
    st.session_state.empresa_info["dias_validez"] = dias_validez

    st.markdown("---")

    # ── PASO 5: LOGÍSTICA ────────────────────────────────────────────────────
    seccion_titulo("Paso 5 — Logística")

    col_agt, col_veh = st.columns(2)
    with col_agt:
        agente_ext_taller = st.checkbox("Agente externo trajo el material al taller", value=bool(pre.get("agente_externo_taller", False)))
    with col_veh:
        _veh_dict = get_vehiculos_dict()
        _veh_keys = list(_veh_dict.keys())
        _v_idx = 0
        if pre.get("vehiculo_entrega") in list(_veh_dict.values()):
            _v_idx = list(_veh_dict.values()).index(pre.get("vehiculo_entrega"))
        veh_lbl = st.selectbox("Vehículo de entrega", _veh_keys, index=_v_idx)
        vehiculo = _veh_dict[veh_lbl]

    c1, c2 = st.columns(2)
    with c1: km = st.number_input("Distancia (km, un trayecto)", min_value=0.0, value=float(pre.get("km", 5.0)), step=0.5)
    with c2: peajes = st.number_input("Núm. de peajes (ida+vuelta)", min_value=0, value=int(pre.get("peajes", 0)), step=1)

    st.markdown("---")

    # ── PASO 6: FORÁNEO ──────────────────────────────────────────────────────
    seccion_titulo("Paso 6 — ¿Proyecto fuera de Barranquilla?")
    foraneo_activo = st.checkbox("Sí, proyecto en otra ciudad", value=pre.get("foraneo_activo", False))
    viaticos_activos = False; tipo_aloj = "pueblo"; noches = 0
    if foraneo_activo:
        c1, c2, c3 = st.columns(3)
        with c1: viaticos_activos = st.checkbox("Agregar viáticos", value=pre.get("viaticos_activos", False))
        with c2: tipo_aloj = ALOJAMIENTO[st.selectbox("Destino", list(ALOJAMIENTO.keys()))]
        with c3: noches = st.number_input("Noches", min_value=0, value=int(pre.get("noches", 1)))

    st.markdown("---")

    # ── PASO 7: ADICIONALES ──────────────────────────────────────────────────
    seccion_titulo("Paso 7 — Costos adicionales")
    adicionales_activos = st.checkbox("Agregar costos adicionales (silicona, impermeabilizante)", value=pre.get("adicionales_activos", False))
    cantidades_add = pre.get("cantidades_add", [0.0] * len(ADICIONALES)) if pre.get("adicionales_activos") else [0.0] * len(ADICIONALES)
    if adicionales_activos:
        for i, a in enumerate(ADICIONALES):
            c1, c2 = st.columns([3, 1])
            c1.markdown(f"<div style='font-size:0.85rem;'>{a['concepto']} — {numero_completo(a.get(etapa, 0))}/{a['unidad']}</div>", unsafe_allow_html=True)
            cantidades_add[i] = c2.number_input("Cant.", min_value=0.0, value=float(cantidades_add[i]), step=1.0, key=f"add_{i}", label_visibility="collapsed")

    st.markdown("---")

    # ── PASO 8: IVA ──────────────────────────────────────────────────────────
    seccion_titulo("Paso 8 — IVA en la cotización")

    _col_iva1, _col_iva2 = st.columns([1.4, 2])
    with _col_iva1:
        incluir_iva = st.toggle(
            "Incluir IVA 19% en la cotización",
            value=pre.get("incluir_iva", True),
            help="Activa si tu empresa es responsable del régimen común.",
        )
    with _col_iva2:
        if incluir_iva:
            st.info("**IVA activo.** Se calculará el 19% sobre el **total de la cotización**.", icon="🧾")
        else:
            st.warning("**IVA desactivado.** Aplica si eres régimen simplificado.", icon="⚠️")

    st.markdown("---")

    # ── CALCULAR ─────────────────────────────────────────────────────────────
    if st.button("Calcular cotización", type="primary", use_container_width=True):
        _piezas_calc = st.session_state.get("piezas", []) if not _mostrar_avanzado else []
        _tots = calcular_totales_piezas(_piezas_calc) if _piezas_calc else {"ml_total": m2_real/0.60, "m2_total": 0.0, "m2_material": m2_real}
        resultado = calcular_cotizacion_directa(
            categoria=cat_sel, referencia=referencia, precio_m2=precio_m2_efectivo, area_placa_comprada=area_placa,
            m2_real=m2_real, m2_cortados=m2_cortados_total, m2_usados=m2_usados, margen_pct=margen_pct,
            dias=dias, personas=personas, zocalo_activo=zocalo_activo, zocalo_ml=zocalo_ml,
            agente_externo_taller=agente_ext_taller, vehiculo_entrega=vehiculo, km=km, num_peajes=peajes,
            foraneo_activo=foraneo_activo, viaticos_activos=viaticos_activos, tipo_aloj=tipo_aloj, noches=noches,
            adicionales_activos=adicionales_activos, cantidades_add=cantidades_add, etapa=etapa,
            adicionales_lista=ADICIONALES, tipo_proyecto=tipo, nombre_cliente=nombre_cliente,
            piezas=_piezas_calc,
            ml_proyecto=_tots["ml_total"],
            logistica_override=st.session_state.get("logistica_custom"),
            vehiculos_custom={**VEHICULOS_CONFIG, **(st.session_state.get("vehiculos_custom") or {})},
            tarifas_override=st.session_state.get("tarifas_custom"),
        )

        resultado["_estado_guardado"] = {
            "categoria": cat_sel, "referencia": referencia, "precio_m2": precio_m2, "area_placa_comprada": area_placa,
            "piezas": st.session_state.piezas, "m2_proyecto": m2_real, "m2_usados": m2_usados, "margen_pct": margen_pct,
            "tipos_proyecto": tipos_sel, "tipo_proyecto": tipo, "dias_obra": dias, "personas": personas, "nombre_cliente": nombre_cliente,
            "zocalo_activo": zocalo_activo, "zocalo_ml": zocalo_ml, "agente_externo_taller": agente_ext_taller,
            "vehiculo_entrega": vehiculo, "km": km, "peajes": peajes, "foraneo_activo": foraneo_activo,
            "viaticos_activos": viaticos_activos, "noches": noches, "adicionales_activos": adicionales_activos,
            "cantidades_add": cantidades_add, "incluir_iva": incluir_iva,
            # Condiciones de pago
            "anticipo_pct": anticipo_pct, "dias_entrega": dias_entrega, "dias_validez": dias_validez,
        }

        st.session_state.cotizacion = resultado
        resultado["incluir_iva"] = incluir_iva
        resultado["anticipo_pct"] = anticipo_pct
        resultado["dias_entrega"] = dias_entrega
        resultado["dias_validez"] = dias_validez
        import random as _rand
        _num_auto = f"COT-{date.today().strftime('%Y%m%d')}-{_rand.randint(100,999)}"
        _guardar_cotizacion(_num_auto, nombre_cliente, resultado)
        st.success("✅ Cotización guardada exitosamente en el Historial.")

    if st.session_state.cotizacion and st.session_state.cotizacion.get("tipo_proyecto") != "Licitación AIU":
        r = st.session_state.cotizacion
        st.markdown("---")
        st.markdown("<h3 style='font-family:Playfair Display,serif'>Resultado</h3>", unsafe_allow_html=True)

        _iva_activo   = r.get("incluir_iva", incluir_iva)
        _iva_monto    = r['precio_sugerido'] * 0.19 if _iva_activo else 0.0
        _precio_final = r['precio_sugerido'] + _iva_monto
        _anticipo_pct = r.get("anticipo_pct", 60)
        _anticipo_val = _precio_final * (_anticipo_pct / 100)

        # Hero card con anticipo visible
        if _iva_activo:
            _iva_line = (
                f'<div style="margin-top:10px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.25)">'
                f'<span style="color:{CC_COLORS["accent"]};font-weight:700">+ IVA 19%: {numero_completo(_iva_monto)}</span>'
                f'&nbsp;&nbsp;→&nbsp;&nbsp;'
                f'<span style="font-size:1.1rem;font-weight:900">Total con IVA: {numero_completo(_precio_final)}</span>'
                f'</div>'
            )
        else:
            _iva_line = f'<div style="margin-top:10px;font-size:0.8rem;opacity:0.7">Sin IVA — régimen simplificado</div>'

        st.markdown(f"""
        <div class="precio-hero">
          <div style="color:{CC_COLORS['accent']};font-size:0.65rem;text-transform:uppercase;letter-spacing:0.14em;font-weight:700;margin-bottom:10px">
            Precio de venta sugerido {'(sin IVA)' if _iva_activo else '— Sin IVA'}
          </div>
          <div style="font-size:2.8rem;font-weight:900;font-family:'Playfair Display',serif;line-height:1;margin-bottom:8px">
            {numero_completo(r['precio_sugerido'])}
          </div>
          <div style="opacity:0.8;font-size:0.85rem">
            Margen: {r['margen_pct']:.0f}%   ·   Utilidad: {numero_completo(r['utilidad'])}
          </div>
          {_iva_line}
          <div style="margin-top:12px;padding-top:10px;border-top:1px solid rgba(201,168,76,0.4);
               background:rgba(201,168,76,0.12);border-radius:8px;padding:10px 14px;margin-top:10px">
            <span style="color:{CC_COLORS['accent']};font-weight:700;font-size:0.9rem">
              💰 Anticipo ({_anticipo_pct}%): {numero_completo(_anticipo_val)}
            </span>
            <span style="opacity:0.75;font-size:0.82rem;margin-left:12px">
              · Saldo contra entrega: {numero_completo(_precio_final - _anticipo_val)}
            </span>
          </div>
        </div>""", unsafe_allow_html=True)

        col_res, col_det = st.columns([1, 1])
        with col_res:
            _items_desglose = [
                ("Material",    r['c1_material']),
                ("Producción",  r['c2_mano_obra']),
                ("Zócalos",     r['c3_zocalos']),
                ("Insumos",     r['c4_insumos']),
                ("Logística",   r['c5_logistica']),
                ("Viáticos",    r['c6_viaticos']),
                ("Adicionales", r['c7_adicionales']),
            ]
            if _iva_activo:
                _items_desglose.append(("Subtotal antes de IVA", r['precio_sugerido']))
                _items_desglose.append((f"IVA 19%", _iva_monto))
                _total_label = "TOTAL CON IVA"
            else:
                _total_label = "PRECIO TOTAL (SIN IVA)"
            bloque_costos(_items_desglose, _total_label, _precio_final)

        with col_det:
            c1a, c2a = st.columns(2)
            c1a.metric("Aprovechamiento", f"{r['aprovechamiento']:.1f}%", f"Retal: {r['retal']:.3f} m²")
            c2a.metric("Costo/m² instalado", numero_completo(r['costo_total']/max(r['m2_real'],0.001)))

            # ── Precio unitario de venta ───────────────────────────────────
            _ml_proy  = r.get("ml_proyecto", 0.0)
            _m2v_proy = r.get("m2_proyecto_m2", 0.0)
            if _ml_proy > 0 or _m2v_proy > 0:
                st.markdown(f"<div style='font-weight:700;margin:12px 0 6px;font-size:0.88rem'>Precio unitario de venta al cliente</div>", unsafe_allow_html=True)
                _cu1, _cu2 = st.columns(2)
                if _ml_proy > 0:
                    _pml = _precio_final / _ml_proy
                    _cu1.metric("Precio / ML", numero_completo(_pml), f"{_ml_proy:.2f} ml totales")
                if _m2v_proy > 0:
                    _pm2 = _precio_final / _m2v_proy
                    _cu2.metric("Precio / m²", numero_completo(_pm2), f"{_m2v_proy:.3f} m² totales")
                if _ml_proy > 0 and _m2v_proy <= 0:
                    _cu2.metric("Precio / m²", numero_completo(_precio_final / max(r['m2_real'],0.001)), "referencia interna")

            st.markdown(f"<div style='font-weight:700;margin:14px 0 8px;font-size:0.88rem'>Simulador de margen</div>", unsafe_allow_html=True)
            _sim_m = st.slider("Juega con tu Margen (%)", 5, 80, int(r["margen_pct"]), 1, key="sim_slider")
            _sim_p = r["costo_total"] / (1 - _sim_m / 100)
            _sim_iva = _sim_p * 0.19 if _iva_activo else 0.0
            if _iva_activo:
                alerta(f"Sin IVA: **{numero_completo(_sim_p)}**   |   Con IVA: **{numero_completo(_sim_p + _sim_iva)}**", "info")
            else:
                alerta(f"Precio total (sin IVA): **{numero_completo(_sim_p)}**", "info")

        st.markdown("---")
        st.markdown("#### Exportar documentos comerciales")
        from generador_pdf import generar_pdf_cotizacion, generar_cuenta_cobro
        colp1, colp2 = st.columns(2)
        with colp1:
            num_cot = st.text_input("Número de Cotización", value=f"COT-{datetime.today().strftime('%Y')}-001", key="num_cot")
            if st.button("📄 Generar Cotización PDF", type="primary", use_container_width=True):
                pdf_bytes = generar_pdf_cotizacion(
                    r, numero=num_cot,
                    empresa_info=st.session_state.empresa_info,
                    logo_bytes=st.session_state.logo_bytes or _LOGO_BYTES,
                    incluir_iva=_iva_activo,
                )
                st.download_button("⬇ Descargar PDF", pdf_bytes, file_name=f"{num_cot}_Cotizacion.pdf", mime="application/pdf", use_container_width=True)
        with colp2:
            num_cc = st.text_input("Número de Cuenta", value=f"CC-{datetime.today().strftime('%Y')}-001", key="num_cc")
            nom_pag = st.text_input("Facturar a:", value=r.get("nombre_cliente",""), key="nom_pag")
            nit_pag = st.text_input("NIT / CC", value="", key="nit_pag")
            dir_pag = st.text_input("Dirección", value="", key="dir_pag")
            if st.button("📄 Generar Cuenta de Cobro PDF", type="primary", use_container_width=True):
                datos_prest = st.session_state.empresa_info.copy()
                datos_pag = {"nombre": nom_pag, "nit": nit_pag, "direccion": dir_pag}
                cc_bytes = generar_cuenta_cobro(
                    r, datos_prest, datos_pag,
                    numero=num_cc,
                    logo_bytes=st.session_state.logo_bytes or _LOGO_BYTES,
                    incluir_iva=_iva_activo,
                )
                st.download_button("⬇ Descargar PDF", cc_bytes, file_name=f"{num_cc}_CuentaCobro.pdf", mime="application/pdf", use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# COTIZACIÓN AIU
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Cotizacion AIU":
    st.markdown("<h2 style='font-family:Playfair Display,serif'>Cotización AIU</h2>", unsafe_allow_html=True)
    st.markdown("<p style='opacity:0.7;font-size:0.88rem'>Estructura formal colombiana A+I+U+IVA — IVA solo sobre Utilidad (U)</p>", unsafe_allow_html=True)

    nombre_cliente_aiu = st.text_input("Nombre de la Constructora o Proyecto", placeholder="Ej: Constructora ABC", value=st.session_state.pre.get("nombre_cliente", ""))

    # Condiciones de pago AIU
    seccion_titulo("Condiciones de pago")
    c_ant_a, c_dias_a, c_val_a = st.columns(3)
    with c_ant_a:
        anticipo_pct_aiu = st.number_input("% de anticipo", min_value=0, max_value=100,
            value=int(st.session_state.empresa_info.get("anticipo_pct", 60)), step=5, key="aiu_anticipo")
    with c_dias_a:
        dias_entrega_aiu = st.number_input("Días de entrega", min_value=1,
            value=int(st.session_state.empresa_info.get("dias_entrega", 10)), step=1, key="aiu_dias_ent")
    with c_val_a:
        dias_validez_aiu = st.number_input("Días de validez", min_value=1,
            value=int(st.session_state.empresa_info.get("dias_validez", 30)), step=5, key="aiu_dias_val")

    seccion_titulo("Ítems del contrato")
    hdr = st.columns([4, 1, 1, 2, 0.5])
    for col, lbl in zip(hdr, ["Descripción", "Unidad", "Cantidad", "Precio unitario (COP)", ""]):
        col.markdown(f"<div style='font-size:0.72rem;font-weight:700;opacity:0.6;text-transform:uppercase'>{lbl}</div>", unsafe_allow_html=True)

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
        c0.caption(f"Subtotal: {numero_completo(sub)}")
        if c4.button("X", key=f"aiu_del_{idx}") and len(st.session_state.aiu_items) > 1:
            st.session_state.aiu_items.pop(idx)
            st.rerun()
        nuevos_items.append({"desc": desc, "und": und, "cant": cant, "punit": punit})
    st.session_state.aiu_items = nuevos_items

    if st.button("+ Agregar ítem"):
        st.session_state.aiu_items.append({"desc": "Nuevo ítem", "und": "glb", "cant": 1.0, "punit": 100_000})
        st.rerun()

    st.markdown(f"<div style='font-size:1.2rem;font-weight:900;color:{CC_COLORS['secondary']};margin:14px 0'>Costo Directo Total: {numero_completo(cd_total)}</div>", unsafe_allow_html=True)

    st.markdown("---")
    seccion_titulo("Porcentajes AIU")

    # Mostrar fórmula AIU claramente
    st.info(
        "**Fórmula AIU (norma colombiana):**  "
        "Precio = CD + A + I + U + IVA(19% solo sobre U) + Logística + Viáticos\n\n"
        "El IVA **NO** aplica sobre el Costo Directo ni sobre A+I — solo sobre la Utilidad (U).",
        icon="📋"
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1: pct_a = st.number_input("A — Administración (%)", value=float(st.session_state.pre.get("pct_a", AIU_DEFAULTS["a"])), step=0.5)
    with c2: pct_i = st.number_input("I — Imprevistos (%)", value=float(st.session_state.pre.get("pct_i", AIU_DEFAULTS["i"])), step=0.5)
    with c3: pct_u = st.number_input("U — Utilidad (%)", value=float(st.session_state.pre.get("pct_u", AIU_DEFAULTS["u"])), step=0.5)
    with c4:
        veh_aiu_lbl = st.selectbox("Vehículo", list(VEHICULOS.keys()), index=list(VEHICULOS.values()).index(st.session_state.pre.get("vehiculo_entrega", "frontier")) if st.session_state.pre.get("vehiculo_entrega", "frontier") in list(VEHICULOS.values()) else 0)

    # Preview en tiempo real del AIU
    if cd_total > 0:
        _val_a_prev = cd_total * (pct_a / 100)
        _val_i_prev = cd_total * (pct_i / 100)
        _val_u_prev = cd_total * (pct_u / 100)
        _iva_prev   = _val_u_prev * 0.19
        _total_prev = cd_total + _val_a_prev + _val_i_prev + _val_u_prev + _iva_prev
        st.markdown(
            f'<div style="background:{CC_COLORS["ultralight"]};border:1px solid {CC_COLORS["light"]};border-radius:8px;padding:12px 16px;margin:8px 0;font-size:0.85rem">'
            f'CD: {numero_completo(cd_total)} + '
            f'A({pct_a}%): {numero_completo(_val_a_prev)} + '
            f'I({pct_i}%): {numero_completo(_val_i_prev)} + '
            f'U({pct_u}%): {numero_completo(_val_u_prev)} + '
            f'IVA s/U(19%): {numero_completo(_iva_prev)} = '
            f'<b style="color:{CC_COLORS["secondary"]}">≈ {numero_completo(_total_prev)}</b>'
            f'</div>',
            unsafe_allow_html=True
        )

    vehiculo_aiu = VEHICULOS[veh_aiu_lbl]
    col1, col2, col3 = st.columns(3)
    km_aiu = col1.number_input("Km (Ida)", value=float(st.session_state.pre.get("km", 10.0)))
    peajes_aiu = col2.number_input("Peajes (Ida+vuelta)", value=int(st.session_state.pre.get("peajes", 0)))
    agente_aiu = col3.checkbox("Agente externo trae material", value=bool(st.session_state.pre.get("agente_externo_taller", False)))

    st.markdown("**Gastos Foráneos**")
    foraneo_aiu = st.checkbox("Proyecto fuera de la ciudad", value=bool(st.session_state.pre.get("foraneo_activo", False)))
    tipo_aloj_aiu = "pueblo"
    noches_aiu = 0
    pers_aiu = 2
    if foraneo_aiu:
        ca1, ca2, ca3 = st.columns(3)
        tipo_aloj_aiu = ALOJAMIENTO[ca1.selectbox("Destino", list(ALOJAMIENTO.keys()))]
        noches_aiu = ca2.number_input("Noches", min_value=0, value=int(st.session_state.pre.get("noches", 1)), step=1)
        pers_aiu = ca3.number_input("Personas", min_value=1, value=int(st.session_state.pre.get("personas", 2)), step=1)

    if st.button("Calcular y Guardar AIU", type="primary", use_container_width=True):
        res_aiu = calcular_aiu(cd_total, pct_a, pct_i, pct_u, vehiculo_aiu, km_aiu, peajes_aiu, agente_aiu, foraneo_aiu, tipo_aloj_aiu, noches_aiu, pers_aiu)

        res_aiu["tipo_proyecto"] = "Licitación AIU"
        res_aiu["categoria"] = "Proyecto Constructora"
        res_aiu["referencia"] = "Múltiple"
        res_aiu["m2_real"] = 0
        res_aiu["ml_proyecto"] = 0
        res_aiu["costo_total"] = cd_total
        res_aiu["precio_sugerido"] = res_aiu['precio_total']
        res_aiu["anticipo_pct"] = anticipo_pct_aiu
        res_aiu["dias_entrega"] = dias_entrega_aiu
        res_aiu["dias_validez"] = dias_validez_aiu

        res_aiu["_estado_guardado"] = {
            "nombre_cliente": nombre_cliente_aiu, "aiu_items": st.session_state.aiu_items,
            "pct_a": pct_a, "pct_i": pct_i, "pct_u": pct_u, "tipo_proyecto": "Licitación AIU",
            "vehiculo_entrega": vehiculo_aiu, "km": km_aiu, "peajes": peajes_aiu, "agente_externo_taller": agente_aiu,
            "foraneo_activo": foraneo_aiu, "tipo_aloj": tipo_aloj_aiu, "noches": noches_aiu, "personas": pers_aiu,
            "anticipo_pct": anticipo_pct_aiu, "dias_entrega": dias_entrega_aiu, "dias_validez": dias_validez_aiu,
        }

        st.session_state.cotizacion = res_aiu
        import random as _r
        _num_auto = f"AIU-{date.today().strftime('%Y%m%d')}-{_r.randint(100,999)}"
        _guardar_cotizacion(_num_auto, nombre_cliente_aiu or "Sin nombre", res_aiu)
        st.success("✅ Cotización AIU guardada en el historial.")

    if st.session_state.cotizacion and st.session_state.cotizacion.get("tipo_proyecto") == "Licitación AIU":
        r = st.session_state.cotizacion
        _anticipo_pct_r = r.get("anticipo_pct", 60)
        _anticipo_val_r = r['precio_total'] * (_anticipo_pct_r / 100)

        st.markdown(f"""
        <div class="precio-hero">
          <div style="color:{CC_COLORS['accent']};font-size:0.65rem;text-transform:uppercase;letter-spacing:0.14em;font-weight:700;margin-bottom:10px">Precio total del contrato (AIU)</div>
          <div style="font-size:2.8rem;font-weight:900;font-family:'Playfair Display',serif;line-height:1;margin-bottom:8px">{numero_completo(r['precio_total'])}</div>
          <div style="opacity:0.8;font-size:0.85rem">Margen Efectivo: {r['margen_pct']:.1f}%</div>
          <div style="margin-top:10px;background:rgba(201,168,76,0.12);border-radius:8px;padding:10px 14px">
            <span style="color:{CC_COLORS['accent']};font-weight:700">
              💰 Anticipo ({_anticipo_pct_r}%): {numero_completo(_anticipo_val_r)}
            </span>
            <span style="opacity:0.75;font-size:0.82rem;margin-left:12px">
              · Saldo: {numero_completo(r['precio_total'] - _anticipo_val_r)}
            </span>
          </div>
        </div>""", unsafe_allow_html=True)

        c_res, _ = st.columns([1.5, 1])
        with c_res:
            bloque_costos([
                ("Costo Directo Base (CD)", r['cd']),
                (f"A — Administración ({r.get('pct_a', pct_a):.1f}%)", r['val_a']),
                (f"I — Imprevistos ({r.get('pct_i', pct_i):.1f}%)", r['val_i']),
                (f"U — Utilidad ({r.get('pct_u', pct_u):.1f}%)", r['val_u']),
                ("IVA 19% exclusivo sobre Utilidad (U)", r['val_iva']),
                ("Gastos Logísticos Integrados", r['logistica']),
                ("Viáticos", r.get('viaticos', 0)),
            ], "PRECIO TOTAL", r['precio_total'])

        st.markdown("---")
        st.markdown("#### Exportar Documentos Institucionales")
        from generador_pdf import generar_pdf_cotizacion, generar_cuenta_cobro
        cp1, cp2 = st.columns(2)
        with cp1:
            num_cot_a = st.text_input("Número de Cotización AIU", value=f"COT-AIU-{datetime.today().strftime('%Y')}-001")
            if st.button("📄 Generar Cotización AIU (PDF)", type="primary", use_container_width=True):
                from generador_pdf import generar_pdf_cotizacion_aiu
                pdf_bytes = generar_pdf_cotizacion_aiu(r, numero=num_cot_a, empresa_info=st.session_state.empresa_info, logo_bytes=st.session_state.logo_bytes or _LOGO_BYTES)
                st.download_button("⬇ Descargar Cotización", pdf_bytes, file_name=f"{num_cot_a}.pdf", mime="application/pdf", use_container_width=True)
        with cp2:
            num_cc_a = st.text_input("Número de Cuenta de Cobro", value=f"CC-AIU-{datetime.today().strftime('%Y')}-001")
            nom_pag_a = st.text_input("Facturar a:", value=nombre_cliente_aiu)
            nit_pag_a = st.text_input("NIT / Rut", value="")
            if st.button("📄 Generar Cobro AIU (PDF)", type="primary", use_container_width=True):
                datos_prest = st.session_state.empresa_info.copy()
                datos_pag = {"nombre": nom_pag_a, "nit": nit_pag_a, "direccion": ""}
                cc_bytes = generar_cuenta_cobro(r, datos_prest, datos_pag, numero=num_cc_a, logo_bytes=st.session_state.logo_bytes or _LOGO_BYTES)
                st.download_button("⬇ Descargar Cobro", cc_bytes, file_name=f"{num_cc_a}.pdf", mime="application/pdf", use_container_width=True)

# ═══════════════════════════════════════════════════════════════════════════════
# HISTORIAL Y DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Historial":
    st.markdown("<h2 style='font-family:Playfair Display,serif'>Historial de cotizaciones</h2>", unsafe_allow_html=True)
    _bus = st.text_input("Buscar", placeholder="Cliente, número o material...")
    _rows = _listar_cotizaciones(_bus)

    if not _rows:
        alerta("No hay cotizaciones guardadas aún.", "info")
    else:
        _ESTADOS = ["Pendiente", "Aprobada", "Rechazada", "En revision"]
        _hdr = st.columns([1.2, 1.2, 2.5, 1.5, 1.2, 1.5, 0.6, 0.6])
        for _col, _lbl in zip(_hdr, ["Número", "Fecha", "Cliente", "Material", "Precio", "Estado", "✏️", "🗑️"]):
            _col.markdown(f"<div style='font-size:0.75rem;font-weight:700;opacity:0.7'>{_lbl}</div>", unsafe_allow_html=True)
        st.markdown("<hr style='margin:4px 0 8px'>", unsafe_allow_html=True)

        for _row in _rows:
            _rid, _rnum, _rfec, _rcli, _rmat, _rml, _rpre, _rmrg, _rest, _rjson = _row
            _cols = st.columns([1.2, 1.2, 2.5, 1.5, 1.2, 1.5, 0.6, 0.6])
            _cols[0].markdown(f"<span style='font-size:0.85rem;font-weight:600'>{_rnum}</span>", unsafe_allow_html=True)
            _cols[1].caption(_rfec)
            _cols[2].markdown(f"<span style='font-size:0.85rem'>{_rcli}</span>", unsafe_allow_html=True)
            _cols[3].caption(_rmat)
            _cols[4].markdown(f"<span style='font-size:0.85rem;font-weight:700'>{numero_completo(_rpre)}</span>", unsafe_allow_html=True)

            _est_sel = _cols[5].selectbox("Estado", _ESTADOS, index=_ESTADOS.index(_rest) if _rest in _ESTADOS else 0, key=f"est_{_rid}", label_visibility="collapsed")
            if _est_sel != _rest:
                _actualizar_estado(_rid, _est_sel)
                st.rerun()

            if _cols[6].button("✏️", key=f"ed_{_rid}", help="Recargar en la calculadora"):
                try:
                    datos = json.loads(_rjson)
                    estado_guardado = datos.get("_estado_guardado", datos)
                    if "AIU" in _rnum or datos.get("tipo_proyecto") == "Licitación AIU" or estado_guardado.get("tipo_proyecto") == "Licitación AIU":
                        st.session_state.aiu_items = estado_guardado.get("aiu_items", st.session_state.aiu_items)
                        st.session_state.pre = estado_guardado
                        st.session_state.nav_radio = "Cotizacion AIU"
                    else:
                        st.session_state.pre = estado_guardado
                        st.session_state.nav_radio = "Cotizacion Directa"
                    st.rerun()
                except Exception:
                    st.error("No se pudo cargar el archivo antiguo.")

            if f"confirmar_borrar_{_rid}" not in st.session_state:
                st.session_state[f"confirmar_borrar_{_rid}"] = False

            if not st.session_state[f"confirmar_borrar_{_rid}"]:
                if _cols[7].button("🗑️", key=f"del_{_rid}"):
                    st.session_state[f"confirmar_borrar_{_rid}"] = True
                    st.rerun()
            else:
                with st.container():
                    st.warning(f"⚠️ ¿Eliminar **{_rnum}** ({_rcli})?")
                    _c1, _c2 = st.columns(2)
                    if _c1.button("✅ Sí, eliminar", key=f"conf_si_{_rid}", type="primary", use_container_width=True):
                        _eliminar_cotizacion(_rid)
                        st.session_state.pop(f"confirmar_borrar_{_rid}", None)
                        st.rerun()
                    if _c2.button("❌ Cancelar", key=f"conf_no_{_rid}", use_container_width=True):
                        st.session_state[f"confirmar_borrar_{_rid}"] = False
                        st.rerun()

elif pagina == "Dashboard":
    st.markdown("<h2 style='font-family:Playfair Display,serif'>Dashboard Gerencial</h2>", unsafe_allow_html=True)
    _s = _stats_db()
    if _s["total"] == 0:
        alerta("Genera cotizaciones para ver métricas aquí.", "info")
    else:
        _m1, _m2, _m3, _m4 = st.columns(4)
        _m1.metric("Total cotizaciones", _s["total"])
        _m2.metric("Aprobadas", _s["aprobadas"])
        _m3.metric("Pendientes", _s["pendientes"])
        _m4.metric("Facturación (aprobadas)", numero_completo(_s["facturacion"]))
        st.markdown("---")
        _da, _db = st.columns(2)
        with _da:
            seccion_titulo("Por material (Facturado)")
            for _mat, _cnt, _mrg, _tot in (_s["por_material"] or []):
                _pct = min(100, (_tot / max(_s["facturacion"], 1)) * 100)
                st.markdown(f"**{_mat}** — {numero_completo(_tot)} ({_mrg:.0f}% margen)")
                st.progress(_pct/100)
        with _db:
            seccion_titulo("Últimos meses")
            for _mes, _cnt, _tot in (_s["por_mes"] or []):
                st.markdown(f"**{_mes}** — {numero_completo(_tot)} ({_cnt} cotizaciones)")

elif pagina == "Parametros":
    st.markdown("<h2 style='font-family:Playfair Display,serif'>Parámetros de costos</h2>", unsafe_allow_html=True)
    t_ia, t1, t2 = st.tabs(["🤖 Asistente IA", "Tarifas y Producción", "Logística y Vehículos"])

    with t_ia:
        if "params_wizard_chat" not in st.session_state:
            st.session_state.params_wizard_chat = []
        chat_wizard = st.session_state.params_wizard_chat

        _ia_ok = ia_disponible()
        if _ia_ok:
            st.markdown(
                '<div style="display:flex;align-items:center;gap:8px;margin-bottom:16px">'
                '<div style="width:9px;height:9px;border-radius:50%;background:#22c55e;flex-shrink:0"></div>'
                '<span style="font-size:0.82rem;font-weight:600;color:#16a34a">Asistente activo</span>'
                '</div>', unsafe_allow_html=True
            )
        else:
            st.warning("⚠️ La IA no está configurada.", icon="🔑")

        for _m in chat_wizard:
            _es_user = _m["role"] == "user"
            _bg = "var(--secondary-background-color)" if _es_user else "transparent"
            st.markdown(
                f'<div style="background:{_bg};border:1px solid var(--border-color);border-radius:10px;padding:10px 14px;margin-bottom:8px">'
                f'<div style="font-size:0.72rem;font-weight:700;opacity:0.55;margin-bottom:4px">{"TÚ" if _es_user else "ASISTENTE IA"}</div>'
                f'<div style="font-size:0.9rem">{_m["content"]}</div>'
                f'</div>', unsafe_allow_html=True
            )

        _col_input, _col_btn = st.columns([5, 1])
        with _col_input:
            _nuevo_msg = st.text_input("Escribe tu mensaje", key="params_chat_input",
                placeholder="Ej: La gasolina subió a $16.500...", label_visibility="collapsed", disabled=not _ia_ok)
        with _col_btn:
            _enviar = st.button("Enviar ➤", key="params_chat_send", type="primary", use_container_width=True, disabled=not _ia_ok)

        if _enviar and _nuevo_msg.strip():
            with st.spinner("Analizando…"):
                _resp = _chat_parametros(chat_wizard, _nuevo_msg.strip())
            st.session_state.params_wizard_chat.append({"role": "user", "content": _nuevo_msg.strip()})
            st.session_state.params_wizard_chat.append({"role": "assistant", "content": _resp})
            st.rerun()

        if chat_wizard:
            if st.button("🗑️ Limpiar conversación", key="params_clear"):
                st.session_state.params_wizard_chat = []
                st.rerun()

    with t1:
        st.markdown("#### Tarifas de producción por material")
        if st.session_state.tarifas_custom is None:
            import copy
            st.session_state.tarifas_custom = copy.deepcopy(TARIFAS)

        tarifas_editadas = {}
        for mat, tar in st.session_state.tarifas_custom.items():
            with st.expander(f"📌 {mat}", expanded=False):
                c1, c2, c3, c4 = st.columns(4)
                prod_ml = c1.number_input("Producción (COP/ml)", min_value=0, value=int(tar.get("prod_ml", 60_000)), step=1_000, key=f"tar_prodml_{mat}")
                zocalo  = c2.number_input("Zócalo (COP/ml)", min_value=0, value=int(tar.get("zocalo", 12_000)), step=500, key=f"tar_zoc_{mat}")
                disco   = c3.number_input("Disco (COP/m²)", min_value=0, value=int(tar.get("disco", 2_200)), step=100, key=f"tar_disco_{mat}")
                maquina = c4.number_input("Máquina (COP/día)", min_value=0, value=int(tar.get("maquina", 20_000)), step=1_000, key=f"tar_maq_{mat}")
                tarifas_editadas[mat] = {"prod_ml": prod_ml, "zocalo": zocalo, "disco": disco, "maquina": maquina}

        col_g1, col_g2 = st.columns(2)
        with col_g1:
            if st.button("💾 Guardar tarifas", type="primary", use_container_width=True, key="save_tarifas"):
                st.session_state.tarifas_custom = tarifas_editadas
                st.success("✅ Tarifas actualizadas.")
        with col_g2:
            if st.button("↩ Restablecer valores por defecto", use_container_width=True, key="reset_tarifas"):
                import copy
                st.session_state.tarifas_custom = copy.deepcopy(TARIFAS)
                st.rerun()

    with t2:
        st.markdown("#### Costos de logística y transporte")
        if st.session_state.logistica_custom is None:
            import copy
            st.session_state.logistica_custom = {k: v for k, v in LOGISTICA.items() if not isinstance(v, dict)}
        if st.session_state.viaticos_custom is None:
            st.session_state.viaticos_custom = dict(VIATICOS)

        lc1, lc2, lc3, lc4 = st.columns(4)
        gasolina = lc1.number_input("Gasolina (COP/galón)", min_value=0, value=int(st.session_state.logistica_custom.get("gasolina", 16_000)), step=500, key="log_gasolina")
        peaje    = lc2.number_input("Peaje promedio (COP)", min_value=0, value=int(st.session_state.logistica_custom.get("peaje", 19_500)), step=500, key="log_peaje")
        herram   = lc3.number_input("Desgaste herramientas / viaje", min_value=0, value=int(st.session_state.logistica_custom.get("herram", 4_500)), step=500, key="log_herram")
        agente   = lc4.number_input("Flete agente externo (COP)", min_value=0, value=int(st.session_state.logistica_custom.get("agente", 85_000)), step=5_000, key="log_agente")

        flete_ext = st.number_input("Flete externo fijo (COP/viaje)", min_value=0,
            value=int((st.session_state.vehiculos_custom or {}).get("externo", {}).get("flete", VEHICULOS_CONFIG["externo"].get("flete", 165_000))),
            step=5_000, key="log_flete_ext")

        st.markdown("**Vehículos propios**")
        if st.session_state.vehiculos_custom is None:
            st.session_state.vehiculos_custom = {}

        vehiculos_editados = {}
        for vk, vcfg in VEHICULOS_CONFIG.items():
            if vcfg.get("tipo") != "propio": continue
            custom_v = (st.session_state.vehiculos_custom or {}).get(vk, vcfg)
            with st.expander(f"🚛 {vcfg['nombre']}", expanded=False):
                vc1, vc2, vc3 = st.columns(3)
                rend_v = vc1.number_input("Rendimiento (km/galón)", min_value=0.1, value=float(custom_v.get("rend", vcfg["rend"])), step=0.1, key=f"veh_rend_{vk}")
                desg_v = vc2.number_input("Desgaste (COP/km)", min_value=0, value=int(custom_v.get("desgaste", vcfg["desgaste"])), step=10, key=f"veh_desg_{vk}")
                base_v = vc3.number_input("Base mínima (COP/viaje)", min_value=0, value=int(custom_v.get("base", vcfg["base"])), step=5_000, key=f"veh_base_{vk}")
                vehiculos_editados[vk] = {**vcfg, "rend": rend_v, "desgaste": desg_v, "base": base_v}
        vehiculos_editados["externo"] = {**VEHICULOS_CONFIG["externo"], "flete": flete_ext}

        vt1, vt2 = st.columns(2)
        v_pueblo = vt1.number_input("Pueblo (COP/noche/persona)", min_value=0, value=int(st.session_state.viaticos_custom.get("pueblo", 145_000)), step=5_000, key="viat_pueblo")
        v_ciudad = vt2.number_input("Ciudad Capital (COP/noche/persona)", min_value=0, value=int(st.session_state.viaticos_custom.get("ciudad", 178_000)), step=5_000, key="viat_ciudad")

        col_l1, col_l2 = st.columns(2)
        with col_l1:
            if st.button("💾 Guardar logística y vehículos", type="primary", use_container_width=True, key="save_logistica"):
                st.session_state.logistica_custom = {"gasolina": gasolina, "peaje": peaje, "herram": herram, "agente": agente}
                st.session_state.viaticos_custom = {"pueblo": v_pueblo, "ciudad": v_ciudad}
                st.session_state.vehiculos_custom = vehiculos_editados
                st.success("✅ Logística y vehículos actualizados.")
        with col_l2:
            if st.button("↩ Restablecer logística por defecto", use_container_width=True, key="reset_logistica"):
                st.session_state.logistica_custom = None
                st.session_state.viaticos_custom  = None
                st.session_state.vehiculos_custom  = None
                st.rerun()

elif pagina == "Asistente IA":

    # ── Inicializar historial del chat ────────────────────────────────────────
    if "ia_chat_historial" not in st.session_state:
        st.session_state.ia_chat_historial = []
    if "ia_esperando" not in st.session_state:
        st.session_state.ia_esperando = False

    _ia_ok = ia_disponible()

    # ── Encabezado ────────────────────────────────────────────────────────────
    col_h1, col_h2 = st.columns([3, 1])
    with col_h1:
        st.markdown("<h2 style='font-family:Playfair Display,serif;margin-bottom:2px'>Asistente IA</h2>", unsafe_allow_html=True)
        st.markdown(
            "<p style='opacity:0.65;font-size:0.88rem;margin-top:0'>Pregúntale cualquier cosa sobre tu proyecto, costos o materiales.</p>",
            unsafe_allow_html=True
        )
    with col_h2:
        if _ia_ok:
            st.markdown(
                f'<div style="text-align:right;padding-top:12px">'
                f'<span style="background:rgba(34,197,94,0.15);border:1px solid rgba(34,197,94,0.35);'
                f'border-radius:20px;padding:4px 12px;font-size:0.75rem;font-weight:700;color:#16a34a">'
                f'🟢 IA Activa</span></div>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f'<div style="text-align:right;padding-top:12px">'
                f'<span style="background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.3);'
                f'border-radius:20px;padding:4px 12px;font-size:0.75rem;font-weight:700;color:#dc2626">'
                f'🔴 IA no configurada</span></div>',
                unsafe_allow_html=True
            )

    # ── Alerta si IA no disponible ────────────────────────────────────────────
    if not _ia_ok:
        st.error(
            "**La IA no está configurada.** Ve a **Configuración** y añade tu API Key de Anthropic "
            "en el archivo `.streamlit/secrets.toml`.",
            icon="🔑"
        )

    st.markdown("---")

    # ── Modo: Chat libre vs Interpretar proyecto ──────────────────────────────
    _modo = st.radio(
        "¿Qué quieres hacer?",
        ["💬 Conversar con el asistente", "🔄 Describir un proyecto para pre-llenar la calculadora"],
        horizontal=True,
        help="El modo 'Conversar' responde preguntas libres. El modo 'Proyecto' extrae los datos y te lleva directo a la calculadora."
    )
    es_modo_chat = "Conversar" in _modo

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ════════════════════════════════════════════════════════════════
    # MODO 1: CHAT CONVERSACIONAL
    # ════════════════════════════════════════════════════════════════
    if es_modo_chat:

        # Sugerencias rápidas si el chat está vacío
        if not st.session_state.ia_chat_historial:
            st.markdown(
                f'<div style="background:var(--secondary-background-color);border:1px solid var(--border-color);'
                f'border-radius:12px;padding:20px 24px;margin-bottom:16px">'
                f'<div style="font-size:0.8rem;font-weight:700;opacity:0.5;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:12px">Puedes preguntarme cosas como...</div>'
                f'<div style="display:flex;flex-wrap:wrap;gap:8px">'
                f'</div></div>',
                unsafe_allow_html=True
            )
            sugerencias = [
                "¿Cuánto debería cobrar por m² de Sinterizado instalado?",
                "¿Mi margen del 25% es suficiente para un mesón de cocina?",
                "¿Cuál es la diferencia entre mármol y cuarcita en costos?",
                "¿Cómo calculo el retal de una placa de 3.36 m²?",
                "¿Qué incluye el AIU y cuándo se usa?",
            ]
            cols_sug = st.columns(2)
            for i, sug in enumerate(sugerencias):
                with cols_sug[i % 2]:
                    if st.button(
                        sug, key=f"sug_{i}",
                        use_container_width=True,
                        disabled=not _ia_ok
                    ):
                        st.session_state.ia_chat_historial.append({"role": "user", "content": sug})
                        st.session_state.ia_esperando = True
                        st.rerun()

        # Historial de mensajes
        for msg in st.session_state.ia_chat_historial:
            es_user = msg["role"] == "user"
            if es_user:
                st.markdown(
                    f'<div style="display:flex;justify-content:flex-end;margin-bottom:10px">'
                    f'<div style="background:{CC_COLORS["secondary"]};color:white;border-radius:14px 14px 2px 14px;'
                    f'padding:10px 16px;max-width:80%;font-size:0.88rem;line-height:1.5">'
                    f'{msg["content"]}'
                    f'</div></div>',
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    f'<div style="display:flex;justify-content:flex-start;margin-bottom:10px">'
                    f'<div style="background:var(--secondary-background-color);border:1px solid var(--border-color);'
                    f'border-radius:14px 14px 14px 2px;padding:10px 16px;max-width:85%;font-size:0.88rem;line-height:1.6">'
                    f'<div style="font-size:0.65rem;font-weight:700;color:{CC_COLORS["accent"]};margin-bottom:4px;letter-spacing:0.06em">ASISTENTE IA</div>'
                    f'{msg["content"]}'
                    f'</div></div>',
                    unsafe_allow_html=True
                )

        # Spinner de carga mientras espera respuesta
        if st.session_state.ia_esperando and st.session_state.ia_chat_historial:
            ultimo = st.session_state.ia_chat_historial[-1]
            if ultimo["role"] == "user":
                with st.spinner("El asistente está pensando..."):
                    _resp = chat_con_ia(
                        st.session_state.ia_chat_historial[:-1],
                        ultimo["content"]
                    )
                st.session_state.ia_chat_historial.append({"role": "assistant", "content": _resp})
                st.session_state.ia_esperando = False
                st.rerun()

        # Input del usuario
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        col_inp, col_btn = st.columns([5, 1])
        with col_inp:
            _msg_input = st.text_input(
                "Escribe tu pregunta",
                key="ia_chat_input",
                placeholder="Ej: ¿Cuánto debería cobrar por un baño en mármol de 2 m²?",
                label_visibility="collapsed",
                disabled=not _ia_ok or st.session_state.ia_esperando,
            )
        with col_btn:
            _enviar = st.button(
                "Enviar",
                key="ia_chat_enviar",
                type="primary",
                use_container_width=True,
                disabled=not _ia_ok or st.session_state.ia_esperando,
            )

        if _enviar and _msg_input.strip():
            st.session_state.ia_chat_historial.append({"role": "user", "content": _msg_input.strip()})
            st.session_state.ia_esperando = True
            st.rerun()

        # Botón limpiar
        if st.session_state.ia_chat_historial:
            st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
            if st.button("🗑️ Limpiar conversación", key="ia_limpiar"):
                st.session_state.ia_chat_historial = []
                st.session_state.ia_esperando = False
                st.rerun()

    # ════════════════════════════════════════════════════════════════
    # MODO 2: INTERPRETAR PROYECTO → PRE-LLENAR CALCULADORA
    # ════════════════════════════════════════════════════════════════
    else:
        st.markdown(
            f'<div style="background:var(--secondary-background-color);border-left:4px solid {CC_COLORS["accent"]};'
            f'border-radius:0 10px 10px 0;padding:14px 18px;margin-bottom:16px;font-size:0.88rem;line-height:1.6">'
            f'<b style="color:{CC_COLORS["accent"]}">¿Cómo funciona?</b><br>'
            f'Describe tu proyecto con las palabras que usas normalmente — material, medidas, tipo de espacio — '
            f'y la IA extrae los datos automáticamente para pre-llenar la calculadora. '
            f'No necesitas saber términos técnicos.'
            f'</div>',
            unsafe_allow_html=True
        )

        ejemplos = [
            "Mesón de cocina en Sinterizado Calacatta Snow, 3.5 metros de largo, ancho estándar. El material lo trajo el agente.",
            "Baño en mármol Crema Marfil, lavamanos 1.2 ml y ducha 2 ml, proyecto en Soledad, 15 km.",
            "Isla de cocina en granito negro absoluto importado, 2 metros, precio del proveedor $480.000 el m².",
        ]
        with st.expander("💡 Ver ejemplos de descripción", expanded=False):
            for ej in ejemplos:
                st.markdown(f'<div style="background:var(--secondary-background-color);border-radius:8px;padding:8px 12px;margin-bottom:6px;font-size:0.85rem;font-style:italic">"{ej}"</div>', unsafe_allow_html=True)

        desc_proyecto = st.text_area(
            "Describe tu proyecto:",
            placeholder="Ej: Mesón de cocina en granito San Gabriel, 3 metros de largo por 60 cm de ancho, cliente en Barranquilla...",
            height=120,
            label_visibility="collapsed",
            disabled=not _ia_ok,
        )

        col_proc, col_info = st.columns([1, 2])
        with col_proc:
            _procesar = st.button(
                "🔄 Interpretar y pre-llenar calculadora",
                type="primary",
                use_container_width=True,
                disabled=not _ia_ok or not desc_proyecto.strip(),
            )

        if _procesar and desc_proyecto.strip():
            with st.spinner("⏳ La IA está interpretando tu proyecto... puede tomar unos segundos"):
                res = interpretar_proyecto(desc_proyecto.strip())

            if res:
                # Mostrar qué datos extrajo antes de redirigir
                datos_extraidos = []
                if res.get("categoria"):       datos_extraidos.append(f"**Material:** {res['categoria']}")
                if res.get("referencia"):      datos_extraidos.append(f"**Referencia:** {res['referencia']}")
                if res.get("precio_m2"):       datos_extraidos.append(f"**Precio/m²:** ${res['precio_m2']:,}".replace(",","."))
                if res.get("m2_proyecto"):     datos_extraidos.append(f"**m² del proyecto:** {res['m2_proyecto']}")
                if res.get("tipo_proyecto"):   datos_extraidos.append(f"**Tipo:** {res['tipo_proyecto']}")
                if res.get("km"):              datos_extraidos.append(f"**Distancia:** {res['km']} km")

                if datos_extraidos:
                    st.success("✅ ¡Datos extraídos! Revísalos antes de ir a la calculadora:")
                    for d in datos_extraidos:
                        st.markdown(f"- {d}")
                else:
                    st.success("✅ Proyecto interpretado. Revisa y ajusta en la calculadora.")

                faltantes = res.get("datos_faltantes", [])
                if faltantes:
                    st.warning(f"⚠️ Datos que no encontré (puedes ingresarlos manualmente): {', '.join(faltantes)}")

                st.session_state.pre = res
                if st.button("➡️ Ir a la calculadora ahora", type="primary", use_container_width=True):
                    st.session_state.nav_radio = "Cotizacion Directa"
                    st.rerun()
            else:
                st.error(
                    "No pude interpretar el proyecto. Intenta ser más específico: "
                    "menciona el tipo de material, las medidas y el tipo de espacio.",
                    icon="❌"
                )

elif pagina == "Configuracion":
    st.markdown("<h2 style='font-family:Playfair Display,serif'>Configuración</h2>", unsafe_allow_html=True)
    tab_emp, tab_logo, tab_pago = st.tabs(["Datos Empresa", "Logo", "Condiciones de Pago"])
    with tab_emp:
        for campo, label in [
            ("nombre", "Razón Social"), ("nit", "NIT"), ("tel", "Teléfono"),
            ("email", "Email"), ("ciudad", "Ciudad"), ("banco", "Banco"),
            ("cuenta_tipo", "Tipo de Cuenta"), ("cuenta_numero", "Número de Cuenta"),
        ]:
            st.session_state.empresa_info[campo] = st.text_input(label, st.session_state.empresa_info.get(campo, ""))
    with tab_logo:
        st.info("El logo corporativo de MARMOLES COLLANTE & CASTRO LTDA. ya está integrado en la app. Si deseas usar otro logo personalizado, súbelo aquí.", icon="ℹ️")
        if _logo_b64:
            st.markdown(
                f'<div style="text-align:center;padding:16px;background:white;border-radius:8px;display:inline-block">'
                f'<img src="data:image/jpeg;base64,{_logo_b64}" style="max-width:200px"/>'
                f'<p style="font-size:0.75rem;color:#666;margin-top:8px">Logo corporativo activo</p>'
                f'</div>', unsafe_allow_html=True
            )
        logo = st.file_uploader("Subir logo personalizado (PNG/JPG)", type=["png", "jpg"])
        if logo:
            st.session_state.logo_bytes = logo.read()
            st.success("Logo personalizado cargado. Se usará en los PDFs.")
        if st.session_state.logo_bytes and st.session_state.logo_bytes != _LOGO_BYTES:
            if st.button("↩ Volver al logo corporativo"):
                st.session_state.logo_bytes = _LOGO_BYTES
                st.rerun()
    with tab_pago:
        st.markdown("**Condiciones de pago por defecto** (se usan como valores iniciales en las cotizaciones)")
        emp = st.session_state.empresa_info
        emp["anticipo_pct"] = st.number_input("% de anticipo predeterminado", min_value=0, max_value=100,
            value=int(emp.get("anticipo_pct", 60)), step=5)
        emp["dias_entrega"] = st.number_input("Días de entrega predeterminados", min_value=1,
            value=int(emp.get("dias_entrega", 10)), step=1)
        emp["dias_validez"] = st.number_input("Días de validez predeterminados", min_value=1,
            value=int(emp.get("dias_validez", 30)), step=5)
        if st.button("💾 Guardar condiciones", type="primary"):
            st.success("✅ Condiciones de pago guardadas.")
