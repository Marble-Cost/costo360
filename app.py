# app.py — CostoMármol v6 · Adaptive UX & Fixes
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

st.set_page_config(
    page_title="CostoMármol — Mármoles Collante & Castro",
    page_icon="🪨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── INICIALIZACIÓN DE VARIABLES Y NAVEGACIÓN (CON PERSISTENCIA EN URL) ────────
if "primera_visita" not in st.session_state:
    st.session_state.primera_visita = True
    # Leer de la URL si la guía ya fue cerrada — sobrevive a F5
    if st.query_params.get("guia") == "terminada":
        st.session_state.onboarding_activo = False
        st.session_state.tour_completado   = True
    else:
        st.session_state.onboarding_activo = True
        st.session_state.tour_completado   = False
    st.session_state.onboarding_paso = 0

if "nav_radio" not in st.session_state:
    # Leer la página actual desde la URL, si no hay → Inicio
    pag_url = st.query_params.get("pagina", "Inicio")
    st.session_state.nav_radio = pag_url
    st.session_state._radio_ui = pag_url

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

# ── CSS NATIVO (ADAPTABLE A MODO CLARO/OSCURO) ────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=DM+Sans:wght@300;400;500;600;700&display=swap');

* { box-sizing: border-box; }
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

/* ── BUTTONS ── */
.stButton > button {
    border-radius: 6px !important; font-weight: 600 !important; font-size: 0.85rem !important;
    transition: all 0.18s ease !important; padding: 0.45rem 1rem !important;
}
.stButton > button[kind="primary"] {
    background: #1B5FA8 !important; color: white !important; border: none !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15) !important; text-transform: uppercase !important;
}
.stButton > button[kind="primary"]:hover { filter: brightness(1.1); transform: translateY(-2px) !important; }

/* ── CARDS (Usa las variables de color del tema del celular/PC) ── */
.card-custom {
    background: var(--secondary-background-color);
    border: 1px solid var(--border-color); 
    border-radius: 10px; padding: 16px 18px; margin-bottom: 12px;
}
</style>
""", unsafe_allow_html=True)

# ── HELPERS UI NATIVOS ────────────────────────────────────────────────────────
def alerta(texto, tipo="info"):
    """Reemplazo de la alerta CSS por componentes nativos de Streamlit (100% compatibles con modo claro/oscuro)"""
    if tipo == "bueno":
        st.success(texto, icon="✅")
    elif tipo == "acepta":
        st.warning(texto, icon="⚠️")
    elif tipo == "bajo":
        st.error(texto, icon="🚨")
    else:
        st.info(texto, icon="ℹ️")

def seccion_titulo(texto, subtexto=""):
    st.markdown(f"### {texto}")
    if subtexto:
        st.caption(subtexto)

def bloque_costos(items_label_valor, total_label, total_val):
    html = ""
    for label, valor in items_label_valor:
        html += f"""<div style="display:flex;justify-content:space-between;padding:6px 0; border-bottom:1px solid var(--border-color); color:var(--text-color);">
            <span style="font-size:0.87rem;">{label}</span><span style="font-size:0.87rem;font-weight:600">{cop(valor)}</span></div>"""
    
    html += f"""<div style="display:flex;justify-content:space-between;padding:10px 0 0 0; border-bottom:1px solid var(--border-color); color:var(--text-color);">
            <span style="font-size:0.95rem;font-weight:800">{total_label}</span><span style="font-size:0.95rem;font-weight:800;color:#1B5FA8">{cop(total_val)}</span></div>"""
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
        "nombre": "MÁRMOLES COLLANTE & CASTRO LTDA.", "nit": "NIT: 900.111.561-1",
        "tel": "+57 300 000 0000", "email": "ventas@marmolescc.com",
        "ciudad": "Barranquilla, Atlántico — Colombia", "banco": "Davivienda",
        "cuenta_tipo": "Cuenta Corriente Empresas", "cuenta_numero": "108900027484",
    },
    "vehiculos_custom": None, "cat_sel": "Mármol",
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

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

# ── SIDEBAR NAV ───────────────────────────────────────────────────────────────
with st.sidebar:
    # ── Logo corporativo — busca entre extensiones posibles automáticamente ───
    _base_dir  = os.path.dirname(os.path.abspath(__file__))
    _logo_path = next(
        (os.path.join(_base_dir, n) for n in
         ["logo_cc.jpeg", "logo_cc.jpg", "logo_cc.png",
          "Logo_cc.jpeg", "Logo_cc.jpg", "Logo_cc.png"]
         if os.path.exists(os.path.join(_base_dir, n))),
        None
    )
    # 1. Prioridad a la imagen subida en Configuración (Memoria)
    if st.session_state.get("logo_bytes"):
        st.image(st.session_state.logo_bytes, use_container_width=True)
    # 2. Si no hay en memoria, busca en el disco duro
    elif _logo_path:
        st.image(_logo_path, use_container_width=True)
    # 3. Fallback (Texto)
    else:
        st.markdown(
            '<div style="text-align:center;padding:14px 0 8px">'
            '<span style="color:#C9A84C;font-size:2rem;font-weight:900;'
            'font-family:Playfair Display,serif">CC</span><br>'
            '<span style="font-size:0.72rem;font-weight:700;opacity:0.8">'
            'MARMOLES COLLANTE &amp; CASTRO</span>'
            '</div>',
            unsafe_allow_html=True
        )

    st.markdown(
        '<div style="text-align:center;margin:2px 0 14px;padding-bottom:10px;'
        'border-bottom:1px solid var(--border-color)">'
        '<div style="font-size:0.66rem;font-weight:600;opacity:0.5;letter-spacing:0.07em;'
        'text-transform:uppercase">Sistema de Cotización Profesional</div>'
        '</div>',
        unsafe_allow_html=True
    )

    # Dashboard eliminado — redirigir si alguien tenía esa ruta guardada
    if st.session_state.get("nav_radio") == "Dashboard":
        st.session_state.nav_radio  = "Historial"
        st.session_state._radio_ui  = "Historial"

    opciones_menu = ["Inicio", "Cotizacion Directa", "Cotizacion AIU", "Historial", "Parametros", "Asistente IA", "Configuracion"]

    def update_nav():
        st.session_state.nav_radio = st.session_state._radio_ui
        # Persistir la página en la URL para sobrevivir a F5
        st.query_params["pagina"] = st.session_state.nav_radio

    _nav_idx = opciones_menu.index(st.session_state.nav_radio) \
               if st.session_state.nav_radio in opciones_menu else 0
    st.radio("Menú", opciones_menu, key="_radio_ui",
             index=_nav_idx, on_change=update_nav,
             label_visibility="collapsed")
    pagina = st.session_state.nav_radio

    st.markdown('<hr style="margin:12px 0">', unsafe_allow_html=True)
    if ia_disponible():
        st.markdown('<div style="background:rgba(74,222,128,0.15);border:1px solid rgba(74,222,128,0.3);border-radius:6px;padding:7px 10px;font-size:0.75rem;font-weight:600;color:#16a34a">🟢 IA Activa</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="background:rgba(251,191,36,0.12);border:1px solid rgba(251,191,36,0.25);border-radius:6px;padding:7px 10px;font-size:0.75rem;font-weight:600;color:#d97706">🟠 IA sin configurar</div>', unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TOUR GUIADO (ONBOARDING) - VERSIÓN NATIVA ESTÉTICA
# ═══════════════════════════════════════════════════════════════════════════════
if st.session_state.get("onboarding_activo"):
    _op = min(st.session_state.get("onboarding_paso", 0), len(TOUR_PASOS) - 1)
    _paso = TOUR_PASOS[_op]
    _total = len(TOUR_PASOS)

    # Tarjeta de Tour Integrada (Sin "position: fixed", sin romper la pantalla)
    with st.container(border=True):
        st.markdown(f"### <span style='color:#1B5FA8'>{_paso['icono']}</span> {_paso['titulo']}", unsafe_allow_html=True)
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
                st.query_params["guia"] = "terminada"   # persiste en URL
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
                    st.query_params["guia"] = "terminada"   # persiste en URL
                    st.rerun()
    st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# INICIO
# ═══════════════════════════════════════════════════════════════════════════════
if pagina == "Inicio":
    st.markdown(f"""
    <div style="background:var(--secondary-background-color); border-radius:16px;padding:40px 44px;margin-bottom:28px; border:2px solid #1B5FA8;">
      <div style="color:#C9A84C;font-size:0.68rem;text-transform:uppercase;letter-spacing:0.15em;font-weight:800;margin-bottom:12px">
        Mármoles Collante &amp; Castro Ltda.
      </div>
      <div style="font-size:2.4rem;font-weight:900;font-family:'Playfair Display',serif;line-height:1.1;margin-bottom:14px; color:var(--text-color);">
        Sistema de Cotización<br>Profesional
      </div>
      <div style="opacity:0.8;font-size:0.92rem;line-height:1.65;max-width:500px; color:var(--text-color);">
        Calcula el costo real de tus proyectos comerciales. Cotización Directa, licitaciones AIU y exportación a PDF adaptable a cualquier entorno.
      </div>
    </div>
    """, unsafe_allow_html=True)

    if st.button("🚀 Reactivar Guía de Inicio", use_container_width=True):
        st.session_state.onboarding_activo = True
        st.session_state.onboarding_paso = 0
        st.rerun()

    st.markdown("---")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Materiales", "5 tipos", "Mármol · Granito · Sint. · Quartz · Quarzita")
    c2.metric("Tiempo", "2 min", "vs. 45–90 min manual")
    c3.metric("Estructura", "AIU + IVA", "Norma colombiana")
    c4.metric("Exporta", "PDF", "Cotización + Cuenta de cobro")


# ═══════════════════════════════════════════════════════════════════════════════
# COTIZACIÓN DIRECTA
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Cotizacion Directa":
    st.markdown("<h2 style='font-family:Playfair Display,serif;margin-bottom:4px'>Cotizacion Directa</h2>", unsafe_allow_html=True)
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

    # Inicializar lista de materiales si no existe
    if "materiales_proyecto" not in st.session_state or not st.session_state.materiales_proyecto:
        st.session_state.materiales_proyecto = pre.get("materiales_proyecto", [
            {"cat": pre.get("categoria", "Mármol"), "ref": pre.get("referencia", ""), "precio_m2": pre.get("precio_m2", 220_000), "area_placa": pre.get("area_placa_comprada", 5.94)}
        ])

    mats = st.session_state.materiales_proyecto
    mats_nuevos = []

    for midx, mat_item in enumerate(mats):
        with st.container(border=True):
            lbl = f"Material {midx + 1}" if len(mats) > 1 else "Material del proyecto"
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
                    m_cat_data = next((m for m in MATERIALES_CATALOGO if m["nombre"] == ref_sel_m), None)
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

    # Para el cálculo usamos el primer material como principal (categoría determina tarifas de MO)
    # El costo total de material suma todos
    cat_sel = mats_nuevos[0]["cat"] if mats_nuevos else "Mármol"
    referencia = " + ".join([m["ref"] or m["cat"] for m in mats_nuevos]) if len(mats_nuevos) > 1 else (mats_nuevos[0]["ref"] if mats_nuevos else "")
    precio_m2 = mats_nuevos[0]["precio_m2"] if mats_nuevos else 220_000
    # Área total y costo total de todos los materiales
    area_placa = sum(m["area_placa"] for m in mats_nuevos)
    costo_mat_total = sum(m["precio_m2"] * m["area_placa"] for m in mats_nuevos)
    # Precio_m2 efectivo para que calcular_cotizacion_directa compute correctamente c1
    precio_m2_efectivo = costo_mat_total / area_placa if area_placa > 0 else precio_m2

    alerta(f"Total material: **{numero_completo(costo_mat_total)}** en {area_placa:.2f} m² comprados", "info")

    st.markdown("---")

    # ── PASO 2: DIMENSIONES ──────────────────────────────────────────────────
    seccion_titulo("Paso 2 — Dimensiones del proyecto", "Ingresa cada pieza por metros lineales — la app convierte a m² automaticamente")

    if "piezas" not in st.session_state or not st.session_state.piezas:
        st.session_state.piezas = pre.get("piezas", [{"nombre": "Meson de cocina", "ml": 2.0, "ancho_tipo": "Mesón de cocina", "ancho_custom": 0.60}])

    _mostrar_avanzado = st.session_state.get("modo_avanzado_medidas", False)
    if not _mostrar_avanzado:
        modo_medida = "Por piezas (ML × Ancho) — recomendado"
        if st.button("Opciones avanzadas (ingresar m² directamente)"):
            st.session_state.modo_avanzado_medidas = True
            st.rerun()
    else:
        modo_medida = st.radio("Modo de ingreso", ["Por piezas (ML × Ancho) — recomendado", "Ingresar m² directamente"], horizontal=True)
        if st.button("Volver al modo simplificado"):
            st.session_state.modo_avanzado_medidas = False
            st.rerun()

    m2_real = 0.0
    m2_cortados_total = 0.0

    if "Por piezas" in modo_medida:
        alerta("Agrega cada pieza del proyecto. Largo en ML × ancho estandar = m² calculados.", "info")
        hdr = st.columns([3, 1.2, 2.5, 1.5, 1.6, 0.6])
        for col, lbl in zip(hdr, ["Pieza / Descripcion", "ML largo", "Tipo de superficie", "Ancho (m)", "m² calculados", ""]):
            col.markdown(f"<div style='font-size:0.72rem;font-weight:700;opacity:0.6;text-transform:uppercase'>{lbl}</div>", unsafe_allow_html=True)

        tipos_superficie = list(ANCHOS_ESTANDAR.keys())
        piezas_nuevas = []
        total_m2_piezas = 0.0

        for idx, pieza in enumerate(st.session_state.piezas):
            c0, c1, c2, c3, c4, c5 = st.columns([3, 1.2, 2.5, 1.5, 1.6, 0.6])
            with c0: nombre_p = st.text_input("Nombre", value=pieza.get("nombre", ""), key=f"pnom_{idx}", label_visibility="collapsed")
            with c1: ml_p = st.number_input("ML", value=float(pieza.get("ml", 1.0)), min_value=0.01, step=0.1, key=f"pml_{idx}", label_visibility="collapsed")
            with c2:
                tipo_idx = tipos_superficie.index(pieza.get("ancho_tipo", tipos_superficie[0])) if pieza.get("ancho_tipo") in tipos_superficie else 0
                ancho_tipo_p = st.selectbox("Tipo", tipos_superficie, index=tipo_idx, key=f"ptip_{idx}", label_visibility="collapsed")
            with c3:
                ancho_def = ANCHOS_ESTANDAR[ancho_tipo_p]["ancho"] or pieza.get("ancho_custom", 0.60)
                ancho_p = st.number_input("Ancho", value=float(ancho_def), min_value=0.01, step=0.01, key=f"panc_{idx}", label_visibility="collapsed")
            m2_p = ml_a_m2(ml_p, ancho_p)
            total_m2_piezas += m2_p
            with c4: st.markdown(f"<div style='padding:8px 4px;font-weight:700;'>{m2_p:.3f} m²</div>", unsafe_allow_html=True)
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
                _ml_total = sum(p.get("ml", 0) for p in st.session_state.piezas)
                st.markdown(
                    f'''<div style="background:var(--secondary-background-color); border:1px solid var(--border-color); border-radius:10px;padding:12px 18px;text-align:center">
                  <div style="font-size:0.7rem;color:#1B5FA8;text-transform:uppercase;letter-spacing:0.08em;font-weight:700">Total del proyecto</div>
                  <div style="font-size:2rem;font-weight:900;font-family:'Playfair Display',serif">{_ml_total:.2f} ml</div>
                  <div style="font-size:0.85rem;opacity:0.7;margin-top:2px">{m2_real:.3f} m² de material</div>
                </div>''', unsafe_allow_html=True)
        extra_corte = st.number_input("m² adicionales cortados no aprovechados (desperdicios manuales)", min_value=0.0, value=0.0, step=0.05)
        m2_cortados_total += extra_corte

    else:
        c1, c2 = st.columns(2)
        with c1:
            m2_real = st.number_input("m² reales del proyecto", min_value=0.01, value=float(pre.get("m2_proyecto", 4.0)), step=0.05)
        with c2:
            m2_cortados_input = st.number_input("m² cortados de la placa (mayor por desperdicios)", min_value=0.0, value=float(m2_real), step=0.05)
            m2_cortados_total = m2_cortados_input if m2_cortados_input > 0 else m2_real

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    with c1:
        m2_usados = st.number_input("m² finalmente instalados", min_value=0.0, value=float(pre.get("m2_usados", m2_real)), step=0.05)
    with c2:
        margen_pct = st.slider("Margen de utilidad (%)", min_value=5, max_value=80, value=int(pre.get("margen_pct", 40)), step=1)
    with c3:
        if area_placa > 0 and m2_usados > 0:
            aprv = min(100, m2_usados / area_placa * 100)
            retal = max(0, area_placa - m2_usados)
            estado_a = "bueno" if aprv >= 80 else "acepta" if aprv >= 50 else "bajo"
            alerta(f"Aprovechamiento: **{aprv:.1f}%** — Retal: {retal:.3f} m²", estado_a)

    st.markdown("---")

    # ── PASO 3: PROYECTO ─────────────────────────────────────────────────────
    seccion_titulo("Paso 3 — Tipo de proyecto y obra")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        tipo_opts = ["Mesón", "Cocina", "Baño", "Piso", "Escalera", "Fachada", "Mueble de cocina", "Otro"]
        # Multi-select para tipo de proyecto
        pre_tipos = pre.get("tipos_proyecto", [pre.get("tipo_proyecto", "Mesón")] if pre.get("tipo_proyecto") else ["Mesón"])
        tipos_sel = st.multiselect(
            "Tipo(s) de proyecto",
            tipo_opts,
            default=[t for t in pre_tipos if t in tipo_opts] or ["Mesón"],
            help="Selecciona uno o varios si el proyecto combina espacios (ej: Cocina + Baño)"
        )
        tipo = " + ".join(tipos_sel) if tipos_sel else "Otro"
    with c2:
        etapa = ETAPAS_OBRA[st.selectbox("Etapa de la obra", list(ETAPAS_OBRA.keys()))]
    with c3:
        dias = st.number_input("Dias en obra", min_value=1, value=int(pre.get("dias_obra", 2)), step=1)
    with c4:
        personas = st.number_input("Num. de personas", min_value=1, value=int(pre.get("personas", 2)), step=1)

    nombre_cliente = st.text_input("Nombre del cliente", value=pre.get("nombre_cliente", ""), placeholder="Ej: Juan Garcia / Constructora XYZ")

    st.markdown("**Zócalos**")
    zocalo_activo = st.checkbox(
        "Este proyecto lleva zócalos",
        value=pre.get("zocalo_activo", False),
        help="El zócalo o guardaescoba requiere un trabajo de corte y brillo de cantos independiente al mesón. Se cobra por metro lineal (ML)."
    )
    zocalo_ml = 0.0
    if zocalo_activo:
        zocalo_ml = st.number_input(
            "Metros lineales de zócalo (ml)",
            min_value=0.0, value=float(pre.get("zocalo_ml", 2.0)), step=0.5,
            help="Suma el largo de todos los zócalos. El sistema multiplicará esto por la tarifa de zócalo definida en Parámetros."
        )

    # ── Gestión de Desperdicio Inteligente ──────────────────────────────────
    st.markdown("**Gestión de Desperdicio (Retal)**")
    desperdicio_sugerido = round(m2_real * 0.15, 2)
    col_d1, col_d2 = st.columns([1, 1])
    with col_d1:
        extra_corte = st.number_input(
            "m² adicionales por cortes/desperdicio",
            min_value=0.0,
            value=float(pre.get("extra_corte", desperdicio_sugerido)),
            step=0.05,
            help="Ningún proyecto usa el 100% de la placa. Los empates, bordes y cortes del lavaplatos generan pérdida. Agregar este extra asegura que el costo de ese material perdido se incluya en el precio final."
        )
    with col_d2:
        st.info(f"💡 Sugerido técnico (15%): **{desperdicio_sugerido:.2f} m²**", icon="📊")
    m2_cortados_total += extra_corte

    st.markdown("---")

    # ── Respaldo Visual (Planos / Modelado 3D) ───────────────────────────────
    st.markdown("**Respaldo Visual (Planos / Modelado 3D)**")
    plano_file = st.file_uploader("Adjuntar plano del cliente o render 3D (PDF, JPG, PNG)", type=["pdf", "png", "jpg", "jpeg"])
    if plano_file:
        st.session_state.pre["plano_nombre"] = plano_file.name
        st.success(f"📎 Documento adjunto: {plano_file.name}")
    elif st.session_state.pre.get("plano_nombre"):
        st.info(f"📎 Documento previo en memoria: {st.session_state.pre['plano_nombre']}")

    st.markdown("---")

    # ── PASO 4: LOGÍSTICA ────────────────────────────────────────────────────
    seccion_titulo("Paso 4 — Logistica")

    col_agt, col_veh = st.columns(2)
    with col_agt:
        agente_ext_taller = st.checkbox("Agente externo trajo el material al taller", value=bool(pre.get("agente_externo_taller", False)))
    with col_veh:
        _veh_dict = get_vehiculos_dict()
        _veh_keys = list(_veh_dict.keys())
        _v_idx = 0
        if pre.get("vehiculo_entrega") in list(_veh_dict.values()):
            _v_idx = list(_veh_dict.values()).index(pre.get("vehiculo_entrega"))
        veh_lbl = st.selectbox("Vehiculo de entrega", _veh_keys, index=_v_idx)
        vehiculo = _veh_dict[veh_lbl]

    c1, c2 = st.columns(2)
    with c1: km = st.number_input("Distancia (km, un trayecto)", min_value=0.0, value=float(pre.get("km", 5.0)), step=0.5)
    with c2: peajes = st.number_input("Num. de peajes (ida+vuelta)", min_value=0, value=int(pre.get("peajes", 0)), step=1)

    st.markdown("---")

    # ── PASO 5: FORÁNEO ──────────────────────────────────────────────────────
    seccion_titulo("Paso 5 — Proyecto fuera de Barranquilla?")
    foraneo_activo = st.checkbox("Si, proyecto en otra ciudad", value=pre.get("foraneo_activo", False))
    viaticos_activos = False; tipo_aloj = "pueblo"; noches = 0
    if foraneo_activo:
        c1, c2, c3 = st.columns(3)
        with c1: viaticos_activos = st.checkbox("Agregar viaticos", value=pre.get("viaticos_activos", False))
        with c2: tipo_aloj = ALOJAMIENTO[st.selectbox("Destino", list(ALOJAMIENTO.keys()))]
        with c3: noches = st.number_input("Noches", min_value=0, value=int(pre.get("noches", 1)))

    st.markdown("---")

    # ── PASO 6: ADICIONALES ──────────────────────────────────────────────────
    seccion_titulo("Paso 6 — Costos adicionales")
    adicionales_activos = st.checkbox("Agregar costos adicionales (silicona, impermeabilizante)", value=pre.get("adicionales_activos", False))
    cantidades_add = pre.get("cantidades_add", [0.0] * len(ADICIONALES)) if pre.get("adicionales_activos") else [0.0] * len(ADICIONALES)
    if adicionales_activos:
        for i, a in enumerate(ADICIONALES):
            c1, c2 = st.columns([3, 1])
            c1.markdown(f"<div style='font-size:0.85rem;'>{a['concepto']} — {numero_completo(a.get(etapa, 0))}/{a['unidad']}</div>", unsafe_allow_html=True)
            cantidades_add[i] = c2.number_input("Cant.", min_value=0.0, value=float(cantidades_add[i]), step=1.0, key=f"add_{i}", label_visibility="collapsed")

    st.markdown("---")

    # ── PASO 7: IVA ──────────────────────────────────────────────────────────
    seccion_titulo("Paso 7 — IVA en la cotización")

    _col_iva1, _col_iva2 = st.columns([1.4, 2])
    with _col_iva1:
        incluir_iva = st.toggle(
            "Incluir IVA 19% en la cotización",
            value=pre.get("incluir_iva", True),
            help="Activa si tu empresa es responsable del régimen común (ventas > 3.500 UVT ≈ $166 M/año). Desactiva si eres régimen simplificado.",
        )
    with _col_iva2:
        if incluir_iva:
            st.info(
                "**IVA activo.** Se calculará el 19% sobre el **total de la cotización** (precio sugerido). "
                "El precio final y el PDF incluirán el IVA desglosado.",
                icon="🧾"
            )
        else:
            st.warning(
                "**IVA desactivado.** La cotización y el PDF se entregarán sin IVA. "
                "Aplica si eres **régimen simplificado** o si el cliente es no responsable de IVA. "
                "Confirma con tu contador.",
                icon="⚠️"
            )

    st.markdown("---")

    # ── CALCULAR ─────────────────────────────────────────────────────────────
    if st.button("Calcular cotizacion", type="primary", use_container_width=True):
        _ml_tot = sum(p.get("ml", 0) for p in st.session_state.get("piezas", [])) if "Por piezas" in modo_medida else (m2_real/0.60)
        resultado = calcular_cotizacion_directa(
            categoria=cat_sel, referencia=referencia, precio_m2=precio_m2_efectivo, area_placa_comprada=area_placa,
            m2_real=m2_real, m2_cortados=m2_cortados_total, m2_usados=m2_usados, margen_pct=margen_pct,
            dias=dias, personas=personas, zocalo_activo=zocalo_activo, zocalo_ml=zocalo_ml,
            agente_externo_taller=agente_ext_taller, vehiculo_entrega=vehiculo, km=km, num_peajes=peajes,
            foraneo_activo=foraneo_activo, viaticos_activos=viaticos_activos, tipo_aloj=tipo_aloj, noches=noches,
            adicionales_activos=adicionales_activos, cantidades_add=cantidades_add, etapa=etapa,
            adicionales_lista=ADICIONALES, tipo_proyecto=tipo, nombre_cliente=nombre_cliente,
            ml_proyecto=_ml_tot, logistica_override=st.session_state.get("logistica_custom"),
            vehiculos_custom={**VEHICULOS_CONFIG, **(st.session_state.get("vehiculos_custom") or {})},
            tarifas_override=st.session_state.get("tarifas_custom"),
        )
        
        # Guardar TODO el estado para poder re-editar fácilmente
        resultado["_estado_guardado"] = {
            "categoria": cat_sel, "referencia": referencia, "precio_m2": precio_m2, "area_placa_comprada": area_placa,
            "piezas": st.session_state.piezas, "m2_proyecto": m2_real, "m2_usados": m2_usados, "margen_pct": margen_pct,
            "tipos_proyecto": tipos_sel, "tipo_proyecto": tipo, "dias_obra": dias, "personas": personas, "nombre_cliente": nombre_cliente,
            "zocalo_activo": zocalo_activo, "zocalo_ml": zocalo_ml, "agente_externo_taller": agente_ext_taller,
            "vehiculo_entrega": vehiculo, "km": km, "peajes": peajes, "foraneo_activo": foraneo_activo,
            "viaticos_activos": viaticos_activos, "noches": noches, "adicionales_activos": adicionales_activos,
            "cantidades_add": cantidades_add, "incluir_iva": incluir_iva,
        }
        
        st.session_state.cotizacion = resultado
        resultado["incluir_iva"] = incluir_iva
        import random as _rand
        _num_auto = f"COT-{date.today().strftime('%Y%m%d')}-{_rand.randint(100,999)}"
        _guardar_cotizacion(_num_auto, nombre_cliente, resultado)
        st.success("✅ Cotización guardada exitosamente en el Historial.")

    if st.session_state.cotizacion and st.session_state.cotizacion.get("tipo_proyecto") != "Licitación AIU":
        r = st.session_state.cotizacion
        st.markdown("---")
        st.markdown("<h3 style='font-family:Playfair Display,serif'>Resultado</h3>", unsafe_allow_html=True)

        # ── IVA: condicional según elección del usuario ───────────────────────
        # IVA se calcula sobre el TOTAL de la cotización (precio_sugerido), no sobre utilidad
        _iva_activo   = r.get("incluir_iva", incluir_iva)
        _iva_monto    = r['precio_sugerido'] * 0.19 if _iva_activo else 0.0
        _precio_final = r['precio_sugerido'] + _iva_monto

        # ── Hero card ─────────────────────────────────────────────────────────
        if _iva_activo:
            _iva_line = (
                f'<div style="margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.25)">'
                f'<span style="color:#C9A84C;font-weight:700">+ IVA 19% sobre total: {numero_completo(_iva_monto)}</span>'
                f'&nbsp;&nbsp;→&nbsp;&nbsp;'
                f'<span style="font-size:1.15rem;font-weight:900">Total con IVA: {numero_completo(_precio_final)}</span>'
                f'</div>'
            )
        else:
            _iva_line = (
                f'<div style="margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.25)'
                f';font-size:0.8rem;opacity:0.7">Sin IVA — cotización entregada en régimen simplificado</div>'
            )

        st.markdown(f"""
        <div style="background:#1B5FA8; border-radius:14px;padding:32px 36px;margin:8px 0 20px; color:white;">
          <div style="color:#C9A84C;font-size:0.68rem;text-transform:uppercase;letter-spacing:0.14em;font-weight:700;margin-bottom:10px">
            Precio de venta sugerido {'(sin IVA)' if _iva_activo else '— Sin IVA'}
          </div>
          <div style="font-size:2.8rem;font-weight:900;font-family:'Playfair Display',serif;line-height:1;margin-bottom:8px">
            {numero_completo(r['precio_sugerido'])}
          </div>
          <div style="opacity:0.8;font-size:0.85rem">
            Margen: {r['margen_pct']:.0f}%   ·   Utilidad: {numero_completo(r['utilidad'])}
          </div>
          {_iva_line}
        </div>""", unsafe_allow_html=True)

        # ── Nota contextual ───────────────────────────────────────────────────
        if _iva_activo:
            alerta(
                "ℹ️ **¿Cuándo cobrar IVA?** El IVA (19%) aplica cuando tu empresa es **responsable del régimen común** "
                "(ventas anuales > 3.500 UVT ≈ $166 M en 2026). Se aplica sobre el total de la cotización. "
                "Consulta a tu contador para confirmar.",
                "info"
            )
        else:
            alerta(
                "ℹ️ **Cotización sin IVA.** Si en algún momento cambias de régimen o el cliente lo requiere, "
                "activa el IVA en el Paso 7 y recalcula.",
                "info"
            )

        # ── Desglose de costos ────────────────────────────────────────────────
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
                _items_desglose.append((f"IVA 19% s/total cotización", _iva_monto))
                _total_label = "TOTAL CON IVA"
            else:
                _total_label = "PRECIO TOTAL (SIN IVA)"
            bloque_costos(_items_desglose, _total_label, _precio_final)

        with col_det:
            c1a, c2a = st.columns(2)
            c1a.metric("Aprovechamiento", f"{r['aprovechamiento']:.1f}%", f"Retal: {r['retal']:.3f} m²")
            c2a.metric("Costo/m² instalado", numero_completo(r['costo_total']/max(r['m2_real'],0.001)))
            st.markdown(f"<div style='font-weight:700;margin:14px 0 8px'>Simulador en tiempo real</div>", unsafe_allow_html=True)
            _sim_m = st.slider("Juega con tu Margen (%)", 5, 80, int(r["margen_pct"]), 1, key="sim_slider")
            _sim_p = r["costo_total"] / (1 - _sim_m / 100)
            _sim_ut = _sim_p - r["costo_total"]
            _sim_iva = _sim_p * 0.19 if _iva_activo else 0.0
            if _iva_activo:
                alerta(f"Sin IVA: **{numero_completo(_sim_p)}**   |   Con IVA 19% s/total: **{numero_completo(_sim_p + _sim_iva)}**", "info")
            else:
                alerta(f"Precio total (sin IVA): **{numero_completo(_sim_p)}**", "info")

        # ── AUDITORÍA DE FÓRMULAS (Modo Aprendizaje) ──────────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        with st.expander("💡 ¿Cómo calculó la aplicación este precio? (Auditoría de datos)"):
            st.markdown(f"""
Esta herramienta no suma números al azar. Aquí tienes el modelo matemático exacto utilizado para tu proyecto en **{r['categoria']}**:

- **Material ({numero_completo(r['c1_material'])}):** Se multiplicó el Área de placa comprada ({r['area_placa']:.3f} m²) por el Precio por m² que te cobra tu proveedor ({numero_completo(r['precio_m2'])}/m²).
- **Producción / Mano de Obra ({numero_completo(r['c2_mano_obra'])}):** Se multiplicaron los metros lineales del proyecto ({r['ml_proyecto']:.2f} ml) por la tarifa de producción configurada en Parámetros para {r['categoria']}.
- **Insumos y Consumibles ({numero_completo(r['c4_insumos'])}):** El sistema calculó tres sub-costos: desgaste de disco/máquina ({numero_completo(r.get('c4_disco_maq', 0))}), consumibles como masilla y lijas ({numero_completo(r.get('c4_consumibles', 0))}), y una provisión de riesgo de rotura ({numero_completo(r.get('c4_riesgo', 0))}).
- **Logística ({numero_completo(r['c5_logistica'])}):** Se calculó usando el rendimiento del vehículo seleccionado, el precio de la gasolina actual y la distancia en km, más peajes y herramientas.
- **Precio Sugerido ({numero_completo(r['precio_sugerido'])}):** No es una suma simple. Para garantizar un margen real del **{r['margen_pct']}%** sobre la venta, se usó la fórmula financiera: `Precio = Costo Total ÷ (1 − Margen)` = {numero_completo(r['costo_total'])} ÷ (1 − {r['margen_pct']/100:.2f}) = **{numero_completo(r['precio_sugerido'])}**.

> 💰 Utilidad proyectada: **{numero_completo(r['utilidad'])}** — lo que entra al bolsillo después de cubrir todos los costos.
            """)
        # ─────────────────────────────────────────────────────────────────────

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
                    logo_bytes=st.session_state.logo_bytes,
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
                    logo_bytes=st.session_state.logo_bytes,
                    incluir_iva=_iva_activo,
                )
                st.download_button("⬇ Descargar PDF", cc_bytes, file_name=f"{num_cc}_CuentaCobro.pdf", mime="application/pdf", use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# COTIZACIÓN AIU
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Cotizacion AIU":
    st.markdown("<h2 style='font-family:Playfair Display,serif'>Cotizacion AIU</h2>", unsafe_allow_html=True)
    st.markdown("<p style='opacity:0.7;font-size:0.88rem'>Estructura formal colombiana A+I+U+IVA</p>", unsafe_allow_html=True)

    nombre_cliente_aiu = st.text_input("Nombre de la Constructora o Proyecto", placeholder="Ej: Constructora ABC", value=st.session_state.pre.get("nombre_cliente", ""))

    seccion_titulo("Items del contrato")
    hdr = st.columns([4, 1, 1, 2, 0.5])
    for col, lbl in zip(hdr, ["Descripcion", "Unidad", "Cantidad", "Precio unitario (COP)", ""]):
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

    if st.button("+ Agregar item"):
        st.session_state.aiu_items.append({"desc": "Nuevo item", "und": "glb", "cant": 1.0, "punit": 100_000})
        st.rerun()

    st.markdown(f"<div style='font-size:1.2rem;font-weight:900;color:#1B5FA8;margin:14px 0'>Costo Directo Total: {numero_completo(cd_total)}</div>", unsafe_allow_html=True)
    
    st.markdown("---")
    seccion_titulo("Porcentajes AIU y Logística")
    c1, c2, c3, c4 = st.columns(4)
    with c1: pct_a = st.number_input("Admin (%)", value=float(st.session_state.pre.get("pct_a", AIU_DEFAULTS["a"])), step=0.5)
    with c2: pct_i = st.number_input("Imprevistos (%)", value=float(st.session_state.pre.get("pct_i", AIU_DEFAULTS["i"])), step=0.5)
    with c3: pct_u = st.number_input("Utilidad (%)", value=float(st.session_state.pre.get("pct_u", AIU_DEFAULTS["u"])), step=0.5)
    with c4:
        veh_aiu_lbl = st.selectbox("Vehículo", list(VEHICULOS.keys()), index=list(VEHICULOS.values()).index(st.session_state.pre.get("vehiculo_entrega", "frontier")) if st.session_state.pre.get("vehiculo_entrega", "frontier") in list(VEHICULOS.values()) else 0)
    
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
        
        # Preparación exacta para la base de datos
        res_aiu["tipo_proyecto"] = "Licitación AIU"
        res_aiu["categoria"] = "Proyecto Constructora"
        res_aiu["referencia"] = "Múltiple"
        res_aiu["m2_real"] = 0
        res_aiu["ml_proyecto"] = 0
        res_aiu["costo_total"] = cd_total
        res_aiu["precio_sugerido"] = res_aiu['precio_total']
        
        res_aiu["_estado_guardado"] = {
            "nombre_cliente": nombre_cliente_aiu, "aiu_items": st.session_state.aiu_items,
            "pct_a": pct_a, "pct_i": pct_i, "pct_u": pct_u, "tipo_proyecto": "Licitación AIU",
            "vehiculo_entrega": vehiculo_aiu, "km": km_aiu, "peajes": peajes_aiu, "agente_externo_taller": agente_aiu,
            "foraneo_activo": foraneo_aiu, "tipo_aloj": tipo_aloj_aiu, "noches": noches_aiu, "personas": pers_aiu
        }
        
        st.session_state.cotizacion = res_aiu
        import random as _r
        _num_auto = f"AIU-{date.today().strftime('%Y%m%d')}-{_r.randint(100,999)}"
        _guardar_cotizacion(_num_auto, nombre_cliente_aiu or "Sin nombre", res_aiu)
        st.success("✅ Cotización AIU guardada en el historial.")

    if st.session_state.cotizacion and st.session_state.cotizacion.get("tipo_proyecto") == "Licitación AIU":
        r = st.session_state.cotizacion
        
        st.markdown(f"""
        <div style="background:#1B5FA8; border-radius:14px;padding:32px 36px;margin:8px 0 20px; color:white;">
          <div style="color:#C9A84C;font-size:0.68rem;text-transform:uppercase;letter-spacing:0.14em;font-weight:700;margin-bottom:10px">Precio total del contrato (AIU)</div>
          <div style="font-size:2.8rem;font-weight:900;font-family:'Playfair Display',serif;line-height:1;margin-bottom:8px">{numero_completo(r['precio_total'])}</div>
          <div style="opacity:0.8;font-size:0.85rem">Margen Efectivo: {r['margen_pct']:.1f}%</div>
        </div>""", unsafe_allow_html=True)

        c_res, _ = st.columns([1.5, 1])
        with c_res:
            bloque_costos([
                ("Costo Directo Base (CD)", r['cd']),
                (f"A — Administración ({r.get('pct_a', pct_a)}%)", r['val_a']),
                (f"I — Imprevistos ({r.get('pct_i', pct_i)}%)", r['val_i']),
                (f"U — Utilidad ({r.get('pct_u', pct_u)}%)", r['val_u']),
                ("IVA 19% exclusivo sobre Utilidad", r['val_iva']),
                ("Gastos Logísticos Integrados", r['logistica']),
            ], "PRECIO TOTAL", r['precio_total'])

        st.markdown("---")
        st.markdown("#### Exportar Documentos Institucionales")
        from generador_pdf import generar_pdf_cotizacion, generar_cuenta_cobro
        cp1, cp2 = st.columns(2)
        with cp1:
            num_cot_a = st.text_input("Número de Oferta", value=f"OFE-AIU-{datetime.today().strftime('%Y')}-001")
            if st.button("📄 Generar Oferta AIU (PDF)", type="primary", use_container_width=True):
                pdf_bytes = generar_pdf_cotizacion(r, numero=num_cot_a, empresa_info=st.session_state.empresa_info, logo_bytes=st.session_state.logo_bytes)
                st.download_button("⬇ Descargar Oferta", pdf_bytes, file_name=f"{num_cot_a}.pdf", mime="application/pdf", use_container_width=True)
        with cp2:
            num_cc_a = st.text_input("Número de Cuenta / Factura", value=f"FAC-AIU-{datetime.today().strftime('%Y')}-001")
            nom_pag_a = st.text_input("Facturar a:", value=nombre_cliente_aiu)
            nit_pag_a = st.text_input("NIT / Rut", value="")
            if st.button("📄 Generar Cobro AIU (PDF)", type="primary", use_container_width=True):
                datos_prest = st.session_state.empresa_info.copy()
                datos_pag = {"nombre": nom_pag_a, "nit": nit_pag_a, "direccion": ""}
                cc_bytes = generar_cuenta_cobro(r, datos_prest, datos_pag, numero=num_cc_a, logo_bytes=st.session_state.logo_bytes)
                st.download_button("⬇ Descargar Cobro", cc_bytes, file_name=f"{num_cc_a}.pdf", mime="application/pdf", use_container_width=True)

# ═══════════════════════════════════════════════════════════════════════════════
# HISTORIAL DE COTIZACIONES — Tarjetas + métricas integradas (Dashboard eliminado)
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Historial":
    st.markdown(
        "<h2 style='font-family:Playfair Display,serif;margin-bottom:4px'>"
        "Historial de cotizaciones</h2>",
        unsafe_allow_html=True
    )

    # ── Métricas rápidas (integradas — ya no hay Dashboard separado) ──────────
    _s = _stats_db()
    if _s["total"] > 0:
        _tasa = round(_s["aprobadas"] / _s["total"] * 100) if _s["total"] else 0
        _mc1, _mc2, _mc3, _mc4 = st.columns(4)
        _mc1.metric("Total",      _s["total"])
        _mc2.metric("Aprobadas",  _s["aprobadas"],  f"{_tasa}% cierre")
        _mc3.metric("Pendientes", _s["pendientes"])
        _mc4.metric("Facturado (aprobadas)",
                    numero_completo(_s["facturacion"]) if _s["facturacion"] else "—")
        st.markdown("<hr style='margin:10px 0 18px'>", unsafe_allow_html=True)

    # ── Barra de herramientas ─────────────────────────────────────────────────
    _tb1, _tb2, _tb3 = st.columns([3, 1.6, 1.1])
    with _tb1:
        _bus = st.text_input(
            "buscar", placeholder="🔍  Buscar por cliente, número o material…",
            label_visibility="collapsed", key="hist_bus"
        )
    with _tb2:
        _filtro = st.selectbox(
            "filtro", ["Todos los estados", "Pendiente", "Aprobada", "Rechazada", "En revision"],
            label_visibility="collapsed", key="hist_filtro"
        )
    with _tb3:
        _vista = st.radio(
            "vista", ["🃏 Tarjetas", "📋 Tabla"],
            horizontal=True, label_visibility="collapsed", key="hist_vista"
        )

    # ── Cargar y filtrar filas ────────────────────────────────────────────────
    _rows = _listar_cotizaciones(_bus)
    if _filtro != "Todos los estados":
        _rows = [r for r in _rows if r[8] == _filtro]

    # ── Estado vacío ─────────────────────────────────────────────────────────
    if not _rows:
        st.markdown(
            '<div style="text-align:center;padding:64px 0;opacity:0.4">'
            '<div style="font-size:3.5rem">📋</div>'
            '<div style="font-size:1rem;font-weight:700;margin-top:10px">Sin cotizaciones</div>'
            '<div style="font-size:0.85rem;margin-top:6px">Genera tu primera cotización '
            'en <b>Cotizacion Directa</b></div>'
            '</div>',
            unsafe_allow_html=True
        )
    else:
        _ESTADOS = ["Pendiente", "Aprobada", "Rechazada", "En revision"]

        # Color + icono por estado
        _EC = {
            "Pendiente":   ("#B8962E", "🟡"),
            "Aprobada":    ("#155724", "🟢"),
            "Rechazada":   ("#7B1A1A", "🔴"),
            "En revision": ("#1B5FA8", "🔵"),
        }

        # Helper: cargar cotización en la calculadora
        def _cargar_en_calculadora(rid, rnum, rjson):
            try:
                datos = json.loads(rjson)
                eg = datos.get("_estado_guardado", datos)
                if "AIU" in rnum or datos.get("tipo_proyecto") == "Licitación AIU" \
                        or eg.get("tipo_proyecto") == "Licitación AIU":
                    st.session_state.aiu_items = eg.get("aiu_items", st.session_state.aiu_items)
                    st.session_state.pre = eg
                    st.session_state.nav_radio = st.session_state._radio_ui = "Cotizacion AIU"
                else:
                    st.session_state.pre = eg
                    st.session_state.nav_radio = st.session_state._radio_ui = "Cotizacion Directa"
                st.rerun()
            except Exception:
                st.error("No se pudo cargar esta cotización.")

        # ── VISTA TARJETAS ────────────────────────────────────────────────────
        if _vista == "🃏 Tarjetas":
            _col_a, _col_b = st.columns(2, gap="medium")

            for _i, _row in enumerate(_rows):
                _rid, _rnum, _rfec, _rcli, _rmat, _rml, _rpre, _rmrg, _rest, _rjson = _row
                _fc, _ico = _EC.get(_rest, ("#888888", "⚪"))
                _badge = "AIU" if "AIU" in _rnum else "Directa"
                _mrg_color = (
                    "#155724" if _rmrg and float(_rmrg) >= 30
                    else "#B8962E" if _rmrg and float(_rmrg) >= 20
                    else "#7B1A1A"
                )
                _tgt = _col_a if _i % 2 == 0 else _col_b

                with _tgt:
                    # ── Tarjeta visual ────────────────────────────────────────
                    st.markdown(f"""
<div style="background:var(--secondary-background-color);
            border:1px solid var(--border-color);
            border-left:4px solid {_fc};
            border-radius:12px;
            padding:16px 18px 14px;
            margin-bottom:4px">

  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
    <div style="display:flex;align-items:center;gap:8px">
      <span style="font-size:0.7rem;font-weight:800;color:{_fc};text-transform:uppercase;
                   letter-spacing:0.07em">{_ico} {_rest}</span>
      <span style="font-size:0.65rem;background:#1B5FA8;color:#fff;
                   padding:2px 8px;border-radius:20px;font-weight:700">{_badge}</span>
    </div>
    <span style="font-size:0.72rem;opacity:0.45">{_rfec}</span>
  </div>

  <div style="font-size:1.05rem;font-weight:800;line-height:1.25;margin-bottom:3px">{_rcli}</div>
  <div style="font-size:0.78rem;opacity:0.55;margin-bottom:12px">{_rnum} · {_rmat or "—"}</div>

  <div style="display:flex;gap:20px;padding-top:10px;
              border-top:1px solid var(--border-color)">
    <div>
      <div style="font-size:0.6rem;font-weight:700;opacity:0.5;text-transform:uppercase;
                  letter-spacing:0.05em">Precio</div>
      <div style="font-size:1rem;font-weight:900;color:#1B5FA8">{numero_completo(_rpre)}</div>
    </div>
    <div>
      <div style="font-size:0.6rem;font-weight:700;opacity:0.5;text-transform:uppercase;
                  letter-spacing:0.05em">Margen</div>
      <div style="font-size:1rem;font-weight:800;color:{_mrg_color}">
        {f"{float(_rmrg):.0f}%" if _rmrg else "—"}</div>
    </div>
    {"<div><div style='font-size:0.6rem;font-weight:700;opacity:0.5;text-transform:uppercase;letter-spacing:0.05em'>ML</div>" +
     f"<div style='font-size:1rem;font-weight:700'>{float(_rml):.1f} ml</div></div>"
     if _rml and float(_rml) > 0 else ""}
  </div>
</div>""", unsafe_allow_html=True)

                    # ── Controles debajo de la tarjeta ────────────────────────
                    _ca, _cb, _cc = st.columns([2.2, 1, 0.7])

                    with _ca:
                        _new_est = st.selectbox(
                            "Estado", _ESTADOS,
                            index=_ESTADOS.index(_rest) if _rest in _ESTADOS else 0,
                            key=f"est_{_rid}", label_visibility="collapsed"
                        )
                        if _new_est != _rest:
                            _actualizar_estado(_rid, _new_est)
                            st.rerun()

                    with _cb:
                        if st.button("✏️ Editar", key=f"ed_{_rid}",
                                     use_container_width=True, help="Recargar en la calculadora"):
                            _cargar_en_calculadora(_rid, _rnum, _rjson)

                    with _cc:
                        _ck = f"del_ok_{_rid}"
                        if _ck not in st.session_state:
                            st.session_state[_ck] = False

                        if not st.session_state[_ck]:
                            if st.button("🗑️", key=f"del_{_rid}",
                                         use_container_width=True, help="Eliminar"):
                                st.session_state[_ck] = True
                                st.rerun()
                        else:
                            st.warning(f"¿Eliminar **{_rnum}**?")
                            _dx, _dy = st.columns(2)
                            if _dx.button("Sí", key=f"dsi_{_rid}",
                                          type="primary", use_container_width=True):
                                _eliminar_cotizacion(_rid)
                                st.session_state.pop(_ck, None)
                                st.rerun()
                            if _dy.button("No", key=f"dno_{_rid}",
                                          use_container_width=True):
                                st.session_state[_ck] = False
                                st.rerun()

                    st.markdown("<div style='margin-bottom:14px'></div>",
                                unsafe_allow_html=True)

        # ── VISTA TABLA ───────────────────────────────────────────────────────
        else:
            _th = st.columns([1.0, 0.9, 2.2, 1.3, 1.2, 0.95, 1.5, 0.55, 0.55])
            for _col, _lbl in zip(_th, ["Número","Fecha","Cliente","Material",
                                        "Precio","Margen","Estado","✏️","🗑️"]):
                _col.markdown(
                    f"<div style='font-size:0.7rem;font-weight:800;opacity:0.55;"
                    f"text-transform:uppercase;letter-spacing:0.04em'>{_lbl}</div>",
                    unsafe_allow_html=True
                )
            st.markdown("<hr style='margin:4px 0 8px'>", unsafe_allow_html=True)

            for _row in _rows:
                _rid, _rnum, _rfec, _rcli, _rmat, _rml, _rpre, _rmrg, _rest, _rjson = _row
                _fc, _ico = _EC.get(_rest, ("#888888", "⚪"))
                _mrg_color = (
                    "#155724" if _rmrg and float(_rmrg) >= 30
                    else "#B8962E" if _rmrg and float(_rmrg) >= 20
                    else "#7B1A1A"
                )
                _tc = st.columns([1.0, 0.9, 2.2, 1.3, 1.2, 0.95, 1.5, 0.55, 0.55])
                _tc[0].markdown(f"<span style='font-size:0.82rem;font-weight:700'>{_rnum}</span>",
                                unsafe_allow_html=True)
                _tc[1].caption(_rfec)
                _tc[2].markdown(f"<span style='font-size:0.83rem'>{_rcli}</span>",
                                unsafe_allow_html=True)
                _tc[3].caption(_rmat or "—")
                _tc[4].markdown(
                    f"<span style='font-size:0.85rem;font-weight:900;color:#1B5FA8'>"
                    f"{numero_completo(_rpre)}</span>",
                    unsafe_allow_html=True
                )
                _tc[5].markdown(
                    f"<span style='font-size:0.85rem;font-weight:700;color:{_mrg_color}'>"
                    f"{f'{float(_rmrg):.0f}%' if _rmrg else '—'}</span>",
                    unsafe_allow_html=True
                )

                _new_est = _tc[6].selectbox(
                    "est", _ESTADOS,
                    index=_ESTADOS.index(_rest) if _rest in _ESTADOS else 0,
                    key=f"est_t_{_rid}", label_visibility="collapsed"
                )
                if _new_est != _rest:
                    _actualizar_estado(_rid, _new_est)
                    st.rerun()

                if _tc[7].button("✏️", key=f"edt_{_rid}", help="Editar"):
                    _cargar_en_calculadora(_rid, _rnum, _rjson)

                _ck2 = f"del_ok_t_{_rid}"
                if _ck2 not in st.session_state:
                    st.session_state[_ck2] = False
                if not st.session_state[_ck2]:
                    if _tc[8].button("🗑️", key=f"delt_{_rid}", help="Eliminar"):
                        st.session_state[_ck2] = True
                        st.rerun()
                else:
                    st.warning(f"¿Eliminar **{_rnum}** — {_rcli}? Esta acción no se puede deshacer.")
                    _dx2, _dy2 = st.columns(2)
                    if _dx2.button("Sí, eliminar", key=f"dsit_{_rid}",
                                   type="primary", use_container_width=True):
                        _eliminar_cotizacion(_rid)
                        st.session_state.pop(_ck2, None)
                        st.rerun()
                    if _dy2.button("Cancelar", key=f"dnot_{_rid}",
                                   use_container_width=True):
                        st.session_state[_ck2] = False
                        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# PARÁMETROS, ASISTENTE IA Y CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Parametros":
    import pandas as pd
    st.markdown("<h2 style='font-family:Playfair Display,serif'>Parámetros Operativos y Costos</h2>", unsafe_allow_html=True)
    st.markdown("Ten control total de los costos de la empresa. Modifica las tablas manualmente o pídele al asistente que lo haga por ti.")

    t_ia, t_tar, t_via = st.tabs(["🤖 Asistente IA (Modificación Automática)", "📊 Tarifas y Producción", "🚗 Viáticos y Logística"])

    with t_ia:
        _ia_ok = ia_disponible()
        if _ia_ok:
            st.markdown(
                '<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">'
                '<div style="width:9px;height:9px;border-radius:50%;background:#22c55e;flex-shrink:0"></div>'
                '<span style="font-size:0.82rem;font-weight:600;color:#16a34a">Asistente activo</span>'
                '</div>', unsafe_allow_html=True
            )
        else:
            st.warning("⚠️ La IA no está configurada. Actívala añadiendo tu API key en **Configuración**.", icon="🔑")

        st.info("💡 **Instrucción:** Dile a la IA qué valores cambiaron (Ej: 'La alimentación en pueblos subió a $75.000'). La IA actualizará las tablas automáticamente.")

        if "params_wizard_chat" not in st.session_state:
            st.session_state.params_wizard_chat = []

        chat_container = st.container()
        with chat_container:
            if not st.session_state.params_wizard_chat:
                st.markdown(
                    '<div style="text-align:center;padding:32px 16px;opacity:0.45;">'
                    '<div style="font-size:2rem;margin-bottom:8px">💬</div>'
                    '<div style="font-size:0.88rem">Aún no hay mensajes.<br>'
                    'Puedes escribir cosas como:<br>'
                    '<em>"La gasolina subió a $16.500"</em> &nbsp;·&nbsp; '
                    '<em>"El hospedaje en pueblos ahora vale $70.000"</em> &nbsp;·&nbsp; '
                    '<em>"¿Cuánto debería cobrar de consumibles por m² en Sinterizado?"</em>'
                    '</div></div>',
                    unsafe_allow_html=True
                )
            else:
                for _m in st.session_state.params_wizard_chat:
                    _es_user = _m["role"] == "user"
                    _bg   = "var(--secondary-background-color)" if _es_user else "transparent"
                    _bord = "1px solid var(--border-color)" if _es_user else "1px solid transparent"
                    # Ocultar JSON al usuario — mostrar mensaje amigable
                    msg_text = _m["content"]
                    if "```json" in msg_text:
                        msg_text = msg_text.split("```json")[0].strip() + "\n\n✅ *He aplicado los cambios en las variables del sistema.*"
                    st.markdown(
                        f'<div style="background:{_bg};border:{_bord};border-radius:10px;'
                        f'padding:10px 14px;margin-bottom:8px">'
                        f'<div style="font-size:0.72rem;font-weight:700;opacity:0.55;margin-bottom:4px">'
                        f'{"TÚ" if _es_user else "ASISTENTE IA"}</div>'
                        f'<div style="font-size:0.9rem">{msg_text}</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )

        # ── Chat input con lógica de IA Ejecutora ─────────────────────────────
        _col_input, _col_btn = st.columns([5, 1])
        with _col_input:
            _nuevo_msg = st.text_input(
                "Escribe tu mensaje",
                key="params_chat_input",
                placeholder="Ej: El precio del disco para mármol subió a $3.000...",
                label_visibility="collapsed",
                disabled=not _ia_ok,
            )
        with _col_btn:
            _enviar = st.button("Enviar ➤", key="params_chat_send", type="primary",
                                use_container_width=True, disabled=not _ia_ok)

        if _enviar and _nuevo_msg.strip():
            prompt_inyeccion = (
                _nuevo_msg.strip() +
                "\n\n(Regla interna IA: Si el usuario aprueba modificar un valor, "
                "incluye al final un bloque ```json con la estructura exacta de TARIFAS o VIATICOS actualizada. "
                "Para TARIFAS usa claves: Mármol/Granito/Sinterizado/Quarztone/Quarzita con subcampos prod_ml/zocalo/disco/maquina/consumibles/riesgo_rotura. "
                "Para VIATICOS usa claves: pueblo/ciudad con subcampos hospedaje/alimentacion/transporte_local.)"
            )
            with st.spinner("Analizando y actualizando variables..."):
                _resp = _chat_parametros(st.session_state.params_wizard_chat, prompt_inyeccion)
            # ── Detectar y aplicar JSON automáticamente ──────────────────────
            if "```json" in _resp:
                try:
                    json_str = _resp.split("```json")[1].split("```")[0]
                    datos_ia = json.loads(json_str)
                    if "pueblo" in datos_ia or "ciudad" in datos_ia:
                        st.session_state.viaticos_custom = datos_ia
                    elif any(k in datos_ia for k in ["Mármol", "Granito", "Sinterizado"]):
                        st.session_state.tarifas_custom = datos_ia
                except Exception as _e:
                    pass  # Si falla el parse, igual se muestra la respuesta
            st.session_state.params_wizard_chat.append({"role": "user", "content": _nuevo_msg.strip()})
            st.session_state.params_wizard_chat.append({"role": "assistant", "content": _resp})
            st.rerun()

        if st.session_state.params_wizard_chat:
            if st.button("🗑️ Limpiar conversación", key="params_clear"):
                st.session_state.params_wizard_chat = []
                st.rerun()

    with t_tar:
        st.markdown("### Costos base por material")
        st.caption("Edita directamente en la tabla. Los cambios se aplican al presionar 'Guardar'.")
        tarifas_actuales = get_tarifas()
        df_tarifas = pd.DataFrame(tarifas_actuales).T.reset_index().rename(columns={"index": "Material"})
        col_order = ["Material", "prod_ml", "zocalo", "disco", "maquina", "consumibles", "riesgo_rotura"]
        col_order = [c for c in col_order if c in df_tarifas.columns]
        df_tarifas = df_tarifas[col_order]
        df_edit = st.data_editor(
            df_tarifas,
            use_container_width=True,
            key="editor_tarifas",
            column_config={
                "Material":       st.column_config.TextColumn("Material", disabled=True),
                "prod_ml":        st.column_config.NumberColumn("Prod/ml (COP)", format="$ %d"),
                "zocalo":         st.column_config.NumberColumn("Zócalo/ml (COP)", format="$ %d"),
                "disco":          st.column_config.NumberColumn("Disco/m² (COP)", format="$ %d"),
                "maquina":        st.column_config.NumberColumn("Máquina/día (COP)", format="$ %d"),
                "consumibles":    st.column_config.NumberColumn("Consumibles/m² (COP)", format="$ %d",
                                    help="Masilla, lijas diamantadas, ceras, sellador, estopa"),
                "riesgo_rotura":  st.column_config.NumberColumn("Riesgo rotura (%)", format="%.3f",
                                    help="% del costo del material provisionado por riesgo de rotura"),
            },
            hide_index=True,
        )
        if st.button("💾 Guardar Tarifas", type="primary"):
            df_edit_indexed = df_edit.set_index("Material")
            st.session_state.tarifas_custom = df_edit_indexed.T.to_dict()
            st.success("✅ Tarifas actualizadas en memoria para esta sesión.")

    with t_via:
        st.markdown("### Desglose de Viáticos (COP por noche/persona)")
        st.caption("Cada fila es un destino. Las columnas son los componentes del costo diario.")
        viaticos_actuales = get_viaticos()
        # Normalizar a formato desglosado si viene legacy (valor plano)
        via_norm = {}
        for k, v in viaticos_actuales.items():
            if isinstance(v, dict):
                via_norm[k] = v
            else:
                via_norm[k] = {"hospedaje": int(v * 0.41), "alimentacion": int(v * 0.45), "transporte_local": int(v * 0.14)}
        df_via = pd.DataFrame(via_norm).T.reset_index().rename(columns={"index": "Destino"})
        df_via_edit = st.data_editor(
            df_via,
            use_container_width=True,
            key="editor_viaticos",
            column_config={
                "Destino":           st.column_config.TextColumn("Destino", disabled=True),
                "hospedaje":         st.column_config.NumberColumn("Hospedaje (COP/noche)", format="$ %d"),
                "alimentacion":      st.column_config.NumberColumn("Alimentación (COP/día)", format="$ %d"),
                "transporte_local":  st.column_config.NumberColumn("Transporte local (COP/día)", format="$ %d"),
            },
            hide_index=True,
        )
        totales = df_via_edit.copy()
        totales["Total diario/persona"] = totales[["hospedaje", "alimentacion", "transporte_local"]].sum(axis=1)
        for _, row in totales.iterrows():
            st.caption(f"**{row['Destino'].capitalize()}** → Total diario/persona: **${int(row['Total diario/persona']):,}**".replace(",", "."))
        if st.button("💾 Guardar Viáticos", type="primary"):
            df_via_indexed = df_via_edit.set_index("Destino")
            st.session_state.viaticos_custom = df_via_indexed.T.to_dict()
            st.success("✅ Viáticos actualizados en memoria para esta sesión.")

elif pagina == "Asistente IA":
    st.markdown("<h2 style='font-family:Playfair Display,serif'>Asistente IA</h2>", unsafe_allow_html=True)
    st.write("Escribe un mensaje en lenguaje natural describiendo tu proyecto. La IA lo interpretará y pre-llenará la calculadora.")
    desc = st.text_area("Describe tu proyecto:", placeholder="Ej: Mesón en granito san gabriel, 3 metros por 60cm...")
    if st.button("Procesar"):
        if ia_disponible():
            res = interpretar_proyecto(desc)
            if res:
                st.session_state.pre = res
                st.session_state.nav_radio = "Cotizacion Directa"
                st.session_state._radio_ui = "Cotizacion Directa"
                st.rerun()
        else:
            st.error("Configura tu API Key en Configuración.")

elif pagina == "Configuracion":
    st.markdown("<h2 style='font-family:Playfair Display,serif'>Perfil de la Empresa y Preferencias</h2>", unsafe_allow_html=True)

    tab_emp, tab_finanzas, tab_logo = st.tabs(["📄 Datos de Facturación", "💰 Finanzas y Bancos", "🎨 Identidad Visual"])

    with tab_emp:
        c1, c2 = st.columns(2)
        st.session_state.empresa_info["nombre"] = c1.text_input(
            "Razón Social", st.session_state.empresa_info.get("nombre", "MÁRMOLES COLLANTE & CASTRO LTDA."))
        st.session_state.empresa_info["nit"] = c2.text_input(
            "NIT", st.session_state.empresa_info.get("nit", "NIT: 900.111.561-1"))
        st.session_state.empresa_info["ciudad"] = c1.text_input(
            "Ciudad / Dirección", st.session_state.empresa_info.get("ciudad", "Barranquilla, Atlántico — Colombia"))
        st.session_state.empresa_info["tel"] = c2.text_input(
            "Teléfono Comercial", st.session_state.empresa_info.get("tel", "+57 300 000 0000"))
        st.session_state.empresa_info["email"] = st.text_input(
            "Correo de contacto", st.session_state.empresa_info.get("email", "ventas@marmolescc.com"))

        st.markdown("---")
        st.markdown("#### 📝 Términos y Garantías (Aparecen en PDFs)")
        st.session_state.empresa_info["terminos"] = st.text_area(
            "Cláusulas de garantía y condiciones",
            value=st.session_state.empresa_info.get(
                "terminos",
                "Garantía de 1 año en mano de obra de instalación. No cubre manchas por ácidos, "
                "golpes, mal uso o intervención de terceros. Los daños causados por otros gremios "
                "durante la construcción no están cubiertos."
            ),
            height=110,
            placeholder="Ej: Garantía de 1 año en instalación, no cubre manchas por ácidos...",
            help="Este texto aparecerá en el pie de página de las cotizaciones y cuentas de cobro PDF."
        )

    with tab_finanzas:
        st.markdown("#### 🏦 Datos Bancarios (Aparecen en los PDFs de cobro)")
        b1, b2 = st.columns(2)
        st.session_state.empresa_info["banco"] = b1.text_input(
            "Banco", st.session_state.empresa_info.get("banco", "Davivienda"))
        _tipos_cuenta = ["Cuenta Corriente Empresas", "Cuenta de Ahorros", "Cuenta Corriente Personal"]
        _tipo_actual = st.session_state.empresa_info.get("cuenta_tipo", "Cuenta Corriente Empresas")
        _tipo_idx = _tipos_cuenta.index(_tipo_actual) if _tipo_actual in _tipos_cuenta else 0
        st.session_state.empresa_info["cuenta_tipo"] = b2.selectbox("Tipo de Cuenta", _tipos_cuenta, index=_tipo_idx)
        st.session_state.empresa_info["cuenta_numero"] = b1.text_input(
            "Número de Cuenta", st.session_state.empresa_info.get("cuenta_numero", "108900027484"))

        st.markdown("---")
        st.markdown("#### 📊 Parámetros Comerciales por Defecto")
        a1, a2 = st.columns(2)
        st.session_state.empresa_info["anticipo_pct"] = a1.number_input(
            "Anticipo exigido (%)",
            min_value=10, max_value=100,
            value=int(st.session_state.empresa_info.get("anticipo_pct", 60)),
            step=5,
            help="Porcentaje de anticipo estándar que aparece en los PDFs de cotización."
        )
        st.session_state.empresa_info["dias_validez"] = a2.number_input(
            "Días de validez de la cotización",
            min_value=5, max_value=90,
            value=int(st.session_state.empresa_info.get("dias_validez", 30)),
            step=5,
            help="Número de días que la cotización tiene validez comercial."
        )
        st.session_state.empresa_info["iva_defecto"] = a1.toggle(
            "Incluir IVA 19% por defecto",
            value=bool(st.session_state.empresa_info.get("iva_defecto", False)),
            help="Si se activa, las nuevas cotizaciones incluirán IVA por defecto."
        )

        # Mostrar resumen bancario
        _emp = st.session_state.empresa_info
        st.markdown(
            f'<div style="background:var(--secondary-background-color);border:1px solid var(--border-color);'
            f'border-radius:10px;padding:14px 18px;margin-top:12px">'
            f'<div style="font-size:0.75rem;font-weight:700;opacity:0.5;margin-bottom:6px">VISTA PREVIA EN PDF</div>'
            f'<div style="font-size:0.88rem"><strong>{_emp.get("banco","")}</strong> · {_emp.get("cuenta_tipo","")} '
            f'· Cta. {_emp.get("cuenta_numero","")}<br>'
            f'Anticipo: <strong>{_emp.get("anticipo_pct",60)}%</strong> · Validez: <strong>{_emp.get("dias_validez",30)} días</strong></div>'
            f'</div>',
            unsafe_allow_html=True
        )

    with tab_logo:
        st.info("El logo se redimensiona automáticamente para el sidebar y los encabezados PDF.", icon="🎨")
        _base_dir_cfg = os.path.dirname(os.path.abspath(__file__))
        _logo_path_cfg = next(
            (os.path.join(_base_dir_cfg, n) for n in
             ["logo_cc.jpeg", "logo_cc.jpg", "logo_cc.png", "Logo_cc.jpeg"]
             if os.path.exists(os.path.join(_base_dir_cfg, n))),
            None
        )
        if st.session_state.get("logo_bytes"):
            st.image(st.session_state.logo_bytes, width=220)
            st.caption("✅ Logo en memoria (subido en esta sesión)")
        elif _logo_path_cfg:
            st.image(_logo_path_cfg, width=220)
            st.caption(f"📁 Logo desde disco: `{os.path.basename(_logo_path_cfg)}`")

        logo = st.file_uploader("Subir nuevo logo (PNG/JPG)", type=["png", "jpg", "jpeg"])
        if logo:
            st.session_state.logo_bytes = logo.read()
            st.success("✅ Logo cargado. Ya aparece en el sidebar y en los PDFs.")
            st.rerun()
