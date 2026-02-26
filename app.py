# app.py — CostoMármol v2
# Streamlit · Python 3.10+ · Mármoles Collante & Castro Ltda.

import streamlit as st
from calculos import (
    calcular_cotizacion_directa, analizar_precio_real,
    calcular_aiu, calcular_logistica, cop,
)
from parametros import (
    CATEGORIAS_MATERIAL, ADICIONALES, ETAPAS_OBRA, VEHICULOS,
    ALOJAMIENTO, AIU_DEFAULTS, TARIFAS, LOGISTICA, VIATICOS,
    ICONOS, BADGE_COLORS, DESCRIPCIONES_CATEGORIA, MATERIALES_CATALOGO,
)
from asistente_ia import chat_con_ia, ia_disponible, interpretar_proyecto, generar_resumen_cotizacion

st.set_page_config(
    page_title="CostoMármol — Cotización Profesional",
    page_icon="🪨", layout="wide", initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""<style>
section[data-testid="stSidebar"] > div {
    background: linear-gradient(180deg,#0d2744 0%,#1a3d6b 100%) !important;
}
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] .stMarkdown,
section[data-testid="stSidebar"] span {color:rgba(255,255,255,0.85)!important;}
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {color:white!important;}
section[data-testid="stSidebar"] .stRadio label {color:white!important;}

.stButton>button[kind="primary"]{
    background:linear-gradient(135deg,#0d2744,#1a3d6b)!important;
    color:#4da3f5!important;border:none!important;
    font-weight:700!important;border-radius:10px!important;padding:12px 24px!important;
}
.stButton>button[kind="primary"]:hover{
    background:#1a3d6b!important;box-shadow:0 4px 16px rgba(13,39,68,.35)!important;
    transform:translateY(-1px)!important;
}
.stButton>button{
    border-radius:9px!important;font-weight:600!important;
    border:2px solid #deeefa!important;color:#0d2744!important;
}
.stButton>button:hover{border-color:#1a6bb5!important;color:#1a6bb5!important;background:#f0f7ff!important;}
[data-testid="stMetric"]{background:#f8fbff;border:1px solid #deeefa;border-radius:10px;padding:14px 16px;}
[data-testid="stMetricLabel"] p{color:#5a7a9a!important;font-size:.72rem!important;font-weight:700!important;text-transform:uppercase;letter-spacing:.06em}
[data-testid="stMetricValue"]{color:#0d2744!important;font-weight:800!important;}
.stTabs [data-baseweb="tab"]{background:#f0f7ff;border-radius:8px 8px 0 0;font-weight:600;color:#0d2744;padding:8px 18px;}
.stTabs [aria-selected="true"]{background:#0d2744!important;color:white!important;}
.streamlit-expanderHeader{background:#f0f7ff!important;border-radius:10px!important;font-weight:700!important;color:#0d2744!important;border:2px solid #deeefa!important;}
.streamlit-expanderContent{border:2px solid #deeefa!important;border-top:none!important;border-radius:0 0 10px 10px!important;}
.stCheckbox label{font-weight:500;font-size:.95rem;}
.stNumberInput label,.stTextInput label,.stSelectbox label,.stSlider label{color:#0d2744!important;font-weight:600!important;font-size:.88rem!important;}
</style>""", unsafe_allow_html=True)

# ── Helpers ───────────────────────────────────────────────────────────────────
def hero(titulo, precio_str, subtitulo, pills=""):
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#0d2744,#1a3d6b);border-radius:16px;
         padding:28px 32px;margin:16px 0;text-align:center">
      <div style="color:#4da3f5;font-size:.72rem;text-transform:uppercase;letter-spacing:.1em;font-weight:700">{titulo}</div>
      <div style="color:white;font-size:2.6rem;font-weight:900;margin:8px 0 4px;font-family:monospace">{precio_str}</div>
      <div style="color:rgba(255,255,255,.5);font-size:.82rem">{subtitulo}</div>
      {pills}
    </div>""", unsafe_allow_html=True)

def pill(texto):
    return f'<span style="background:rgba(255,255,255,.1);color:rgba(255,255,255,.85);padding:4px 14px;border-radius:20px;font-size:.8rem;margin:0 4px">{texto}</span>'

def alerta(texto, tipo="info"):
    estilos = {
        "info":   ("#f0f7ff","#1a6bb5","#0d2744"),
        "bueno":  ("#e8f7ef","#0f7a4a","#0a5a35"),
        "acepta": ("#fff4e0","#b86a00","#7a4a00"),
        "bajo":   ("#fce8ea","#b01e2a","#b01e2a"),
    }
    bg, borde, color = estilos.get(tipo, estilos["info"])
    st.markdown(f'<div style="background:{bg};border-left:4px solid {borde};padding:12px 16px;'
                f'border-radius:8px;color:{color};font-size:.88rem;margin:8px 0">{texto}</div>',
                unsafe_allow_html=True)

def desglose(items, total_label, total_val):
    html = ""
    for label, val in items:
        c = "#8aa3bf" if val == 0 else "#0d2744"
        html += (f'<div style="display:flex;justify-content:space-between;padding:9px 0;'
                 f'border-bottom:1px solid #e8f0f8;font-size:.87rem">'
                 f'<span style="color:{c}">{label}</span>'
                 f'<span style="font-weight:600;color:{c}">{cop(val)}</span></div>')
    html += (f'<div style="display:flex;justify-content:space-between;padding:13px 0;'
             f'font-weight:800;font-size:1rem;color:#0d2744;border-top:2px solid #0d2744;margin-top:4px">'
             f'<span>{total_label}</span><span>{cop(total_val)}</span></div>')
    st.markdown(html, unsafe_allow_html=True)

def badge(cat):
    bg, color = BADGE_COLORS.get(cat, ("#e8f0f8","#0d2744"))
    return f'<span style="background:{bg};color:{color};padding:2px 9px;border-radius:10px;font-size:.62rem;font-weight:700;text-transform:uppercase">{cat}</span>'

# ── Session state ─────────────────────────────────────────────────────────────
_defaults = {
    "chat": [],
    "cotizacion": None,
    "contexto_cot": {},
    "resumen_ia": "",
    "aiu_items": [
        {"desc":"Material pétreo (suministro)","und":"m²","cant":10.0,"punit":250_000},
        {"desc":"Mano de obra corte y elaboración","und":"m²","cant":10.0,"punit":100_000},
        {"desc":"Instalación y nivelación","und":"m²","cant":10.0,"punit":50_000},
        {"desc":"Insumos (disco, adhesivo, silicona)","und":"glb","cant":1.0,"punit":150_000},
    ],
    # Pre-llenado desde IA
    "pre": {},
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🪨 CostoMármol")
    st.markdown("**Mármoles Collante & Castro Ltda.**")
    st.markdown("---")
    pagina = st.radio("", [
        "🏠 Inicio",
        "⚡ Cotización Directa",
        "📋 Cotización AIU",
        "⚙️ Parámetros",
        "🤖 Asistente IA",
    ], label_visibility="collapsed")
    st.markdown("---")
    if ia_disponible():
        st.success("🤖 IA Activa — Claude")
    else:
        st.warning("🔌 IA sin configurar")
        with st.expander("▶ Activar IA (2 min)"):
            st.markdown("""
**1.** Regístrate en `console.anthropic.com`

**2.** Crea el archivo `.streamlit/secrets.toml`

**3.** Escribe adentro:
```toml
ANTHROPIC_API_KEY = "sk-ant-..."
```
**4.** Reinicia: `streamlit run app.py`
""")
    st.markdown("---")
    st.caption("📅 Feb 2026 · Barranquilla")

# ═══════════════════════════════════════════════════════════════════════════════
# INICIO
# ═══════════════════════════════════════════════════════════════════════════════
if pagina == "🏠 Inicio":
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d2744,#1a3d6b);border-radius:16px;padding:32px;margin-bottom:24px">
      <div style="color:#4da3f5;font-size:.75rem;text-transform:uppercase;letter-spacing:.1em;font-weight:700;margin-bottom:8px">Mármoles Collante & Castro Ltda.</div>
      <div style="color:white;font-size:2rem;font-weight:900;line-height:1.1;margin-bottom:10px">Sistema de Cotización<br>Profesional de Mármoles</div>
      <div style="color:rgba(255,255,255,.55);font-size:.9rem;line-height:1.6;max-width:520px">
        Calcula el costo real de tus proyectos de mármol, granito, sinterizado, quarztone y cuarcita
        con estructura profesional. Logística, AIU, IA y PDF en menos de 2 minutos.
      </div>
    </div>
    """, unsafe_allow_html=True)
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Categorías","5","mármol · granito · sinterizado · quarztone · cuarcita")
    c2.metric("Cotización","< 2 min","vs. 45–90 min manual")
    c3.metric("Estructura","AIU + IVA(U)","norma colombiana")
    c4.metric("Exporta","PDF","cotización + cuenta cobro")
    st.markdown("---")
    col1,col2 = st.columns(2)
    with col1:
        st.markdown("### ⚡ Cotización Directa")
        st.markdown("Para clientes particulares. Ingresa el tipo de material, precio/m² y área. La app calcula el resto.")
    with col2:
        st.markdown("### 📋 Cotización AIU")
        st.markdown("Para constructoras y licitaciones. Estructura formal colombiana A+I+U+IVA.")
    st.markdown("---")
    alerta("💡 <strong>Nuevo:</strong> Describe tu proyecto en lenguaje natural en el Asistente IA y la app pre-llenará la calculadora por ti.", "info")

# ═══════════════════════════════════════════════════════════════════════════════
# COTIZACIÓN DIRECTA
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "⚡ Cotización Directa":
    st.markdown("## ⚡ Cotización Directa")
    st.caption("Para proyectos residenciales y clientes particulares")

    # ── Banner: si la IA pre-llenó datos ──
    pre = st.session_state.pre
    if pre:
        alerta(f"✨ <strong>IA detectó tu proyecto.</strong> Revisa los campos — ya están pre-llenados con los datos que describiste. Puedes ajustar cualquier valor.", "bueno")
        if st.button("✕ Limpiar pre-llenado"):
            st.session_state.pre = {}
            st.rerun()

    st.markdown("---")

    # ── PASO 1: MATERIAL ──────────────────────────────────────────────────────
    st.markdown("### 🪨 Paso 1 — Material")
    st.caption("Selecciona el tipo de piedra e ingresa el precio que te cobró el proveedor.")

    # Selección de categoría por botones grandes (UX mejorada)
    cat_sel = st.session_state.get("cat_sel", pre.get("categoria", "Mármol"))
    cols_cat = st.columns(len(CATEGORIAS_MATERIAL))
    for i, cat in enumerate(CATEGORIAS_MATERIAL):
        icono = ICONOS.get(cat,"🪨")
        bg_c, color_c = BADGE_COLORS.get(cat,("#e8f0f8","#0d2744"))
        activo = cat_sel == cat
        borde = "2px solid #1a6bb5" if activo else f"2px solid {bg_c}"
        bg = "#f0f7ff" if activo else bg_c
        marca = "✅ " if activo else ""
        with cols_cat[i]:
            st.markdown(f"""
            <div style="border:{borde};border-radius:10px;padding:12px 8px;
                 background:{bg};text-align:center;cursor:pointer">
              <div style="font-size:1.4rem">{icono}</div>
              <div style="font-weight:700;font-size:.82rem;color:{color_c};margin-top:4px">{marca}{cat}</div>
              <div style="font-size:.65rem;color:#8aa3bf;margin-top:3px;line-height:1.3">{DESCRIPCIONES_CATEGORIA.get(cat,'')}</div>
            </div>""", unsafe_allow_html=True)
            if st.button(f"Seleccionar {cat}", key=f"cat_{i}", use_container_width=True):
                st.session_state.cat_sel = cat
                st.rerun()

    cat_sel = st.session_state.get("cat_sel", "Mármol")

    st.markdown(f"**Categoría seleccionada:** {ICONOS.get(cat_sel,'')} {cat_sel}")
    st.divider()

    # Referencia y precio/m²
    c1,c2,c3 = st.columns(3)
    with c1:
        # Autocompletar desde catálogo
        refs_cat = [m["nombre"] for m in MATERIALES_CATALOGO if m["categoria"] == cat_sel]
        refs_cat = ["Otra referencia..."] + refs_cat
        ref_sel = st.selectbox("Referencia del material", refs_cat,
            help="Si tu referencia no aparece en la lista, selecciona 'Otra referencia...' y escríbela abajo.")
        if ref_sel == "Otra referencia...":
            referencia = st.text_input("Escribe el nombre de la referencia",
                value=pre.get("referencia",""), placeholder="Ej: Calacatta Gold, Nero Marquina...")
        else:
            referencia = ref_sel
            # Autocompletar precio/m²
            m_cat = next((m for m in MATERIALES_CATALOGO if m["nombre"] == ref_sel), None)
            if m_cat and "precio_m2_default" not in st.session_state:
                st.session_state["precio_m2_default"] = m_cat["precio_m2"]
    with c2:
        precio_m2_default = pre.get("precio_m2") or st.session_state.pop("precio_m2_default", 220_000)
        precio_m2 = st.number_input(
            "Precio/m² (COP) — lo que te cobró el proveedor",
            min_value=10_000, max_value=5_000_000,
            value=int(precio_m2_default), step=1_000,
            help="El valor por metro cuadrado que está en la factura de compra del material.",
        )
    with c3:
        area_placa_default = pre.get("area_placa_comprada", 5.94)
        area_placa = st.number_input(
            "Área del material comprado (m²)",
            min_value=0.01, max_value=200.0, value=float(area_placa_default), step=0.1, format="%.3f",
            help="¿Cuántos m² de material compraste en total? Si compraste media placa de 5.94 m² → 2.97 m²",
        )

    costo_mat = precio_m2 * area_placa
    alerta(f"📦 <strong>Costo total del material:</strong> {cop(precio_m2)}/m² × {area_placa} m² = <strong>{cop(costo_mat)}</strong>", "info")

    st.markdown("---")

    # ── PASO 2: DIMENSIONES ──────────────────────────────────────────────────
    st.markdown("### 📐 Paso 2 — Dimensiones del proyecto")
    st.caption("Puedes ingresar el área directamente o calcularla desde largo × ancho.")

    c1,c2 = st.columns(2)
    with c1:
        usar_medidas = st.checkbox("Calcular m² desde largo × ancho (en cm o metros)", value=bool(pre.get("m2_proyecto") is None and pre.get("largo") is None))
        if usar_medidas:
            sub1,sub2,sub3 = st.columns(3)
            largo_val = sub1.number_input("Largo", min_value=0.0, value=4.0, step=0.1, format="%.2f")
            ancho_val = sub2.number_input("Ancho", min_value=0.0, value=0.90, step=0.01, format="%.2f")
            unidad_med = sub3.selectbox("Unidad", ["metros","cm"], help="Selecciona la unidad de las medidas")
            if unidad_med == "cm":
                m2_real = (largo_val/100) * (ancho_val/100)
            else:
                m2_real = largo_val * ancho_val
            st.info(f"📐 {largo_val} {unidad_med} × {ancho_val} {unidad_med} = **{m2_real:.2f} m²**")
        else:
            m2_real = st.number_input("m² reales del proyecto *",
                min_value=0.01, value=float(pre.get("m2_proyecto", 4.0)),
                step=0.1, format="%.2f",
                help="Área total que vas a instalar")
    with c2:
        m2_usados_default = pre.get("m2_usados", 0.0)
        m2_usados = st.number_input("m² usados de las láminas (para calcular retal)",
            min_value=0.0, value=float(m2_usados_default), step=0.1, format="%.2f",
            help="Área real que cortaste. Si no lo sabes, déjalo en 0.")
        margen_pct = st.slider("Margen de utilidad (%)", min_value=5, max_value=80, value=40, step=1,
            help="% de ganancia sobre precio de venta. Recomendado: 30-45%")

    if area_placa > 0:
        m2_ref = m2_usados if m2_usados > 0 else m2_real
        aprv = min(100, m2_ref / area_placa * 100)
        emoji_a = "🟢" if aprv >= 80 else "🟡" if aprv >= 50 else "🔴"
        retal = max(0, area_placa - m2_ref)
        st.info(f"{emoji_a} **Aprovechamiento:** {aprv:.0f}% · Retal estimado: {retal:.2f} m² de {area_placa:.2f} m² comprados")

    st.markdown("---")

    # ── PASO 3: TIPO DE PROYECTO ─────────────────────────────────────────────
    st.markdown("### 🏗️ Paso 3 — Tipo de proyecto y obra")
    c1,c2,c3,c4 = st.columns(4)
    with c1:
        tipo_default = pre.get("tipo_proyecto","Mesón")
        tipo = st.selectbox("Tipo de proyecto", ["Mesón","Cocina","Baño","Piso","Escalera","Fachada","Mueble de cocina","Otro"],
            index=["Mesón","Cocina","Baño","Piso","Escalera","Fachada","Mueble de cocina","Otro"].index(tipo_default) if tipo_default in ["Mesón","Cocina","Baño","Piso","Escalera","Fachada","Mueble de cocina","Otro"] else 0)
    with c2:
        etapa_lbl = st.selectbox("Etapa de la obra", list(ETAPAS_OBRA.keys()))
        etapa = ETAPAS_OBRA[etapa_lbl]
    with c3:
        dias_default = int(pre.get("dias_obra") or 2)
        dias = st.number_input("Días en obra", min_value=1, value=dias_default, step=1)
    with c4:
        pers_default = int(pre.get("personas") or 2)
        personas = st.number_input("N° de personas", min_value=1, value=pers_default, step=1,
            help="Número de empleados (para viáticos si aplica)")

    nombre_cliente = st.text_input("Nombre del cliente (opcional — para el PDF)", placeholder="Ej: Juan García / Constructora XYZ")

    # Zócalos
    st.markdown("**¿El proyecto lleva zócalos?**")
    zocalo_activo = st.checkbox("Sí, este proyecto lleva zócalos", key="cb_zocalo")
    zocalo_ml = 0.0
    if zocalo_activo:
        zocalo_ml = st.number_input("Metros lineales de zócalo (ml)", min_value=0.0, value=2.0, step=0.5, format="%.1f")
        tar_z = TARIFAS.get(cat_sel,{}).get("zocalo",0)
        alerta(f"Tarifa zócalo {cat_sel}: {cop(tar_z)}/ml → <strong>Subtotal: {cop(zocalo_ml*tar_z)}</strong>", "info")

    st.markdown("---")

    # ── PASO 4: LOGÍSTICA — PROVEEDOR → TALLER ───────────────────────────────
    st.markdown("### 📦 Paso 4 — ¿Cómo llegó el material a tu taller?")
    agente_ext_taller = st.checkbox(
        "El proveedor / agente externo transportó el material hasta mi taller",
        value=bool(pre.get("agente_externo_taller", False)),
        key="cb_agente_taller",
        help=f"Agrega {cop(LOGISTICA['agente'])} de flete al costo total.",
    )
    if agente_ext_taller:
        alerta(f"📦 Flete agente externo (proveedor→taller): <strong>{cop(LOGISTICA['agente'])}</strong>", "info")

    st.markdown("---")

    # ── PASO 5: LOGÍSTICA — TALLER → CLIENTE ─────────────────────────────────
    st.markdown("### 🚛 Paso 5 — Transporte taller → cliente")
    st.caption("Distancia desde tu taller hasta el punto de instalación del cliente.")

    c1,c2,c3 = st.columns(3)
    with c1:
        veh_default = pre.get("vehiculo_entrega","frontier")
        veh_keys = list(VEHICULOS.keys())
        veh_vals = list(VEHICULOS.values())
        veh_idx = veh_vals.index(veh_default) if veh_default in veh_vals else 0
        veh_lbl = st.selectbox("Vehículo de entrega al cliente", veh_keys, index=veh_idx)
        vehiculo = VEHICULOS[veh_lbl]
    with c2:
        km_default = float(pre.get("km") or 5.0)
        km = st.number_input("Distancia taller → cliente (km)", min_value=0.0, value=km_default, step=0.5, format="%.1f",
            help="Un solo trayecto — se calcula ida y vuelta automáticamente")
    with c3:
        peajes_default = int(pre.get("peajes") or 0)
        peajes = st.number_input("N° de peajes (total ida+vuelta)", min_value=0, value=peajes_default, step=1)

    costo_log_entrega = calcular_logistica(vehiculo, km, peajes, False)
    alerta(f"🚛 Costo entrega taller→cliente: <strong>{cop(costo_log_entrega)}</strong> (gasolina+desgaste+flete+peajes)", "info")

    st.markdown("---")

    # ── PASO 6: FORÁNEO ──────────────────────────────────────────────────────
    st.markdown("### 🗺️ Paso 6 — ¿Proyecto fuera de Barranquilla?")
    foraneo = st.checkbox("El proyecto es fuera de Barranquilla", value=bool(pre.get("foraneo", False)), key="cb_foraneo")
    viaticos_on, tipo_aloj, noches = False, "pueblo", 0
    if foraneo:
        viaticos_on = st.checkbox("Se dieron viáticos al personal", value=True, key="cb_viat")
        if viaticos_on:
            c1,c2 = st.columns(2)
            with c1:
                aloj_lbl = st.selectbox("Tipo de alojamiento", list(ALOJAMIENTO.keys()))
                tipo_aloj = ALOJAMIENTO[aloj_lbl]
            with c2:
                noches_default = int(pre.get("noches") or 1)
                noches = st.number_input("N° de noches", min_value=0, value=noches_default, step=1)
            tv = noches * personas * VIATICOS[tipo_aloj]
            alerta(f"🏨 Viáticos: {noches} noches × {personas} personas × {cop(VIATICOS[tipo_aloj])} = <strong>{cop(tv)}</strong>", "info")

    st.markdown("---")

    # ── PASO 7: ADICIONALES ──────────────────────────────────────────────────
    st.markdown("### 🔧 Paso 7 — Costos adicionales en obra")
    adic_on = st.checkbox("Hay costos adicionales en esta obra", value=False, key="cb_adic")
    cantidades_add = [0]*len(ADICIONALES)
    if adic_on:
        st.caption(f"Precios ajustados para etapa: **{etapa_lbl}**")
        total_add = 0
        for i,a in enumerate(ADICIONALES):
            precio = a.get(etapa, a["terminada"])
            c1,c2,c3 = st.columns([4,1,2])
            c1.caption(f"**{a['concepto']}** ({a['unidad']}) — {cop(precio)}/und")
            qty = c2.number_input("Cant.", min_value=0, value=0, step=1, key=f"add_{i}", label_visibility="collapsed")
            if qty > 0:
                c3.markdown(f"**{cop(qty*precio)}**")
            cantidades_add[i] = qty
            total_add += qty*precio
        if total_add > 0:
            alerta(f"Total adicionales: <strong>{cop(total_add)}</strong>", "info")

    st.markdown("---")

    # ── CALCULAR ─────────────────────────────────────────────────────────────
    puede_calcular = cat_sel and precio_m2 > 0 and m2_real > 0 and area_placa > 0

    if not puede_calcular:
        alerta("👆 Completa el tipo de material, precio/m², área comprada y m² del proyecto para calcular.", "info")

    c1,c2 = st.columns([3,1])
    with c1:
        if st.button("⚡ CALCULAR COTIZACIÓN COMPLETA", type="primary",
                     use_container_width=True, disabled=not puede_calcular):
            r = calcular_cotizacion_directa(
                categoria=cat_sel, referencia=referencia,
                precio_m2=precio_m2, area_placa_comprada=area_placa,
                m2_real=m2_real, m2_usados=m2_usados,
                margen_pct=margen_pct, dias=dias, personas=personas,
                zocalo_activo=zocalo_activo, zocalo_ml=zocalo_ml,
                vehiculo_taller="externo", agente_externo_taller=agente_ext_taller,
                vehiculo_entrega=vehiculo, km=km, num_peajes=peajes,
                foraneo_activo=foraneo, viaticos_activos=viaticos_on,
                tipo_aloj=tipo_aloj, noches=noches,
                adicionales_activos=adic_on, cantidades_add=cantidades_add,
                etapa=etapa, adicionales_lista=ADICIONALES,
                tipo_proyecto=tipo, nombre_cliente=nombre_cliente,
            )
            st.session_state.cotizacion = r
            st.session_state.contexto_cot = {
                "categoria": cat_sel, "referencia": referencia,
                "tipo_proyecto": tipo, "m2_real": m2_real,
            }
            # Generar resumen IA si está disponible
            if ia_disponible():
                with st.spinner("🤖 Analizando resultado..."):
                    st.session_state.resumen_ia = generar_resumen_cotizacion(r, st.session_state.contexto_cot)
            st.rerun()
    with c2:
        if st.button("↺ Nueva cotización", use_container_width=True):
            st.session_state.cotizacion = None
            st.session_state.pre = {}
            st.session_state.resumen_ia = ""
            st.rerun()

    # ── RESULTADO ─────────────────────────────────────────────────────────────
    if st.session_state.cotizacion:
        r = st.session_state.cotizacion
        st.markdown("---")
        st.markdown("## 📊 Resultado de la Cotización")

        pills_html = '<div style="margin-top:14px;display:flex;justify-content:center;gap:10px;flex-wrap:wrap">' + \
            pill(f"Margen: {r['margen_pct']:.0f}%") + pill(f"Costo: {cop(r['costo_total'])}") + \
            pill(f"Utilidad: {cop(r['utilidad'])}") + "</div>"
        hero("💰 Precio de Venta Sugerido", cop(r["precio_sugerido"]),
             "COP · con margen de utilidad aplicado", pills_html)

        c1,c2,c3 = st.columns(3)
        aprv = r["aprovechamiento"]
        em = "✅" if aprv>=80 else "⚠️" if aprv>=50 else "🔴"
        c1.metric(f"{em} Aprovechamiento lámina", f"{aprv:.0f}%", f"Retal: {r['retal']:.2f} m²")
        c2.metric("💵 Utilidad proyectada", cop(r["utilidad"]))
        c3.metric("📉 Costo total", cop(r["costo_total"]))

        st.markdown("### 📋 Desglose de costos")
        desglose([
            ("① Material (área comprada × precio/m²)", r["c1_material"]),
            ("② Mano de obra (corte + elaboración)",   r["c2_mano_obra"]),
            ("③ Zócalos",                              r["c3_zocalos"]),
            ("④ Insumos (disco + desgaste maquinaria)",r["c4_insumos"]),
            ("⑤ Transporte proveedor → taller",        r["c5_taller"]),
            ("⑥ Transporte taller → cliente",          r["c5_entrega"]),
            ("⑦ Viáticos foráneos",                    r["c6_viaticos"]),
            ("⑧ Adicionales en obra",                  r["c7_adicionales"]),
        ], "COSTO VARIABLE TOTAL", r["costo_total"])

        # Resumen IA
        if st.session_state.resumen_ia:
            st.markdown("### 🤖 Análisis de la IA")
            st.markdown(f'<div style="background:#0d2744;color:rgba(255,255,255,.88);padding:16px 20px;border-radius:12px;font-size:.88rem;line-height:1.7">{st.session_state.resumen_ia.replace(chr(10),"<br>")}</div>', unsafe_allow_html=True)

        # Precio real
        st.markdown("### 💬 ¿A cuánto cerraste con el cliente?")
        alerta("Ingresa el precio acordado para analizar tu margen real.", "info")
        precio_real = st.number_input("Precio real acordado (COP)", min_value=0, value=0, step=10_000, format="%d")
        if precio_real > 0:
            an = analizar_precio_real(precio_real, r["costo_total"], r["precio_sugerido"])
            mr, ur, diff = an["margen_real"], an["utilidad_real"], an["diferencia"]
            dir_txt = f"{'↑ '+cop(abs(diff))+' sobre sugerido' if diff>=0 else '↓ '+cop(abs(diff))+' bajo sugerido'}"
            tipos = {"bueno":"bueno","aceptable":"acepta","bajo":"bajo"}
            alerta(f"{'✅' if an['estado']=='bueno' else '⚠️' if an['estado']=='aceptable' else '🔴'} "
                   f"<strong>Margen {an['estado']}: {mr:.1f}%</strong> — Utilidad real: {cop(ur)} · {dir_txt}",
                   tipos[an["estado"]])

        # ── EXPORTAR PDF ─────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### 📄 Exportar Documentos")
        tab_cot, tab_cc = st.tabs(["📋 Cotización PDF", "💰 Cuenta de Cobro PDF"])

        with tab_cot:
            c1,c2 = st.columns(2)
            with c1:
                num_cot = st.text_input("Número de cotización", value=f"COT-{__import__('datetime').date.today().strftime('%Y%m%d')}-001")
            with c2:
                st.write("")
            if st.button("📄 Generar PDF de Cotización", type="primary", use_container_width=True):
                try:
                    from generador_pdf import generar_pdf_cotizacion
                    pdf_bytes = generar_pdf_cotizacion(r, numero=num_cot)
                    st.download_button(
                        label="⬇️ Descargar Cotización PDF",
                        data=pdf_bytes,
                        file_name=f"Cotizacion_{num_cot}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                    )
                except ImportError:
                    alerta("Para generar PDFs instala: <code>pip install reportlab</code>", "acepta")
                except Exception as e:
                    alerta(f"Error generando PDF: {str(e)}", "bajo")

        with tab_cc:
            st.caption("Completa los datos para la cuenta de cobro:")
            c1,c2 = st.columns(2)
            with c1:
                st.markdown("**Quien cobra (tú):**")
                p_nombre  = st.text_input("Nombre / Razón Social", key="cc_nombre", placeholder="Tu nombre o empresa")
                p_nit     = st.text_input("NIT / Cédula",          key="cc_nit",    placeholder="123456789-0")
                p_dir     = st.text_input("Dirección",             key="cc_dir",    placeholder="Calle 72 #45-12")
                p_tel     = st.text_input("Teléfono",              key="cc_tel",    placeholder="3001234567")
            with c2:
                st.markdown("**Datos bancarios:**")
                p_banco   = st.text_input("Banco",                  key="cc_banco",  placeholder="Bancolombia")
                p_tc      = st.selectbox("Tipo de cuenta", ["Ahorros","Corriente"], key="cc_tc")
                p_cuenta  = st.text_input("N° de cuenta",           key="cc_cta",    placeholder="12345678901")
            st.markdown("**Quien paga (cliente):**")
            c3,c4,c5 = st.columns(3)
            pg_nombre = c3.text_input("Nombre / Razón Social", key="pg_nom", placeholder="Cliente o empresa")
            pg_nit    = c4.text_input("NIT / Cédula",          key="pg_nit")
            pg_dir    = c5.text_input("Dirección",             key="pg_dir")
            num_cc = st.text_input("Número de cuenta de cobro", value=f"CC-{__import__('datetime').date.today().strftime('%Y%m%d')}-001", key="num_cc")

            if st.button("💰 Generar Cuenta de Cobro PDF", type="primary", use_container_width=True):
                try:
                    from generador_pdf import generar_cuenta_cobro
                    pdf_bytes = generar_cuenta_cobro(
                        resultado=r,
                        datos_prestador={"nombre":p_nombre,"nit_cc":p_nit,"direccion":p_dir,"telefono":p_tel,"banco":p_banco,"cuenta_tipo":p_tc,"cuenta_numero":p_cuenta},
                        datos_pagador={"nombre":pg_nombre,"nit":pg_nit,"direccion":pg_dir},
                        numero=num_cc,
                    )
                    st.download_button(
                        label="⬇️ Descargar Cuenta de Cobro PDF",
                        data=pdf_bytes,
                        file_name=f"CuentaCobro_{num_cc}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                    )
                except ImportError:
                    alerta("Para generar PDFs instala: <code>pip install reportlab</code>", "acepta")
                except Exception as e:
                    alerta(f"Error generando PDF: {str(e)}", "bajo")

# ═══════════════════════════════════════════════════════════════════════════════
# COTIZACIÓN AIU
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "📋 Cotización AIU":
    st.markdown("## 📋 Cotización AIU")
    st.caption("Para constructoras, licitaciones y proyectos formales")
    alerta("📌 <strong>AIU Colombia:</strong> A + I + U sobre Costo Directo. IVA 19% solo sobre Utilidad (U).", "info")
    st.markdown("---")
    c1,c2 = st.columns(2)
    with c1:
        desc_p = st.text_input("Descripción del proyecto", placeholder="Ej: Cocinas Torre B, Pisos 1-5")
        cliente_p = st.text_input("Cliente / Constructora")
    with c2:
        c3,c4 = st.columns(2)
        dias_a = c3.number_input("Días en obra", min_value=1, value=3, key="aiu_d")
        pers_a = c4.number_input("N° personas",  min_value=1, value=3, key="aiu_p")

    st.markdown("---")
    st.markdown("### 📊 Ítems del Costo Directo")
    hc = st.columns([3,1,1,2,2,0.4])
    for h,lbl in zip(hc,["Descripción","Unidad","Cantidad","Precio Unit.","Total",""]):
        h.markdown(f"**{lbl}**")
    cd_total = 0.0
    borrar = []
    for idx, item in enumerate(st.session_state.aiu_items):
        c1,c2,c3,c4,c5,c6 = st.columns([3,1,1,2,2,0.4])
        item["desc"]  = c1.text_input("d",value=item["desc"],  key=f"d_{idx}", label_visibility="collapsed", placeholder="Descripción")
        item["und"]   = c2.text_input("u",value=item["und"],   key=f"u_{idx}", label_visibility="collapsed")
        item["cant"]  = c3.number_input("c",value=float(item["cant"]),min_value=0.0,step=0.5,key=f"c_{idx}",label_visibility="collapsed",format="%.2f")
        item["punit"] = c4.number_input("p",value=float(item["punit"]),min_value=0.0,step=1000.0,key=f"p_{idx}",label_visibility="collapsed",format="%.0f")
        t = item["cant"]*item["punit"]
        c5.markdown(f"**{cop(t)}**")
        cd_total += t
        if c6.button("✕",key=f"rm_{idx}"):
            borrar.append(idx)
    for i in reversed(borrar):
        st.session_state.aiu_items.pop(i)
        st.rerun()
    if st.button("+ Agregar ítem"):
        st.session_state.aiu_items.append({"desc":"","und":"m²","cant":1.0,"punit":0})
        st.rerun()
    alerta(f"📊 <strong>Costo Directo (CD): {cop(cd_total)}</strong>","info")
    st.markdown("---")
    st.markdown("### 🏛️ Estructura AIU")
    c1,c2,c3 = st.columns(3)
    pct_a = c1.number_input("A — Administración (%)",0.0,30.0,float(AIU_DEFAULTS["a"]),0.5,format="%.1f")
    pct_i = c2.number_input("I — Imprevistos (%)",   0.0,30.0,float(AIU_DEFAULTS["i"]),0.5,format="%.1f")
    pct_u = c3.number_input("U — Utilidad (%)",      0.0,30.0,float(AIU_DEFAULTS["u"]),0.5,format="%.1f")
    st.caption("IVA 19% sobre la Utilidad (U) — fijo por norma colombiana")
    st.markdown("---")
    st.markdown("### 🚛 Logística y Viáticos")
    ag_a = st.checkbox("Agente externo trajo el material",key="aiu_ag")
    c1,c2,c3 = st.columns(3)
    veh_a = VEHICULOS[c1.selectbox("Vehículo",list(VEHICULOS.keys()),key="aiu_vl")]
    km_a  = c2.number_input("Distancia (km)",0.0,value=10.0,step=0.5,key="aiu_km")
    pea_a = c3.number_input("N° peajes",0,value=0,key="aiu_pea")
    for_a = st.checkbox("Proyecto fuera de Barranquilla",key="aiu_for")
    aloj_a,noc_a="pueblo",0
    if for_a:
        c1,c2 = st.columns(2)
        aloj_a = ALOJAMIENTO[c1.selectbox("Alojamiento",list(ALOJAMIENTO.keys()),key="aiu_al")]
        noc_a  = c2.number_input("N° noches",0,value=1,key="aiu_noc")
    st.markdown("---")
    if st.button("📋 CALCULAR PRESUPUESTO AIU",type="primary",use_container_width=True):
        ra = calcular_aiu(cd_total,pct_a,pct_i,pct_u,veh_a,km_a,pea_a,ag_a,for_a,aloj_a,noc_a,pers_a)
        st.markdown("## 📊 Resultado AIU")
        hero("💰 Precio Final del Proyecto",cop(ra["precio_total"]),"COP · CD + AIU + IVA(U) + Logística")
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Costo Directo",cop(ra["cd"]))
        c2.metric("AIU + IVA(U)",cop(ra["sub_aiu"]))
        c3.metric("Logística",cop(ra["logistica"]))
        c4.metric("Margen efectivo",f"{ra['margen_pct']:.1f}%")
        desglose([
            ("Costo Directo (CD)",             ra["cd"]),
            (f"Administración ({pct_a}%)",     ra["val_a"]),
            (f"Imprevistos ({pct_i}%)",        ra["val_i"]),
            (f"Utilidad ({pct_u}%)",           ra["val_u"]),
            ("IVA sobre Utilidad (19%)",       ra["val_iva"]),
            ("Logística",                      ra["logistica"]),
            ("Viáticos foráneos",              ra["viaticos"]),
        ],"PRECIO FINAL DEL PROYECTO",ra["precio_total"])

# ═══════════════════════════════════════════════════════════════════════════════
# PARÁMETROS
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "⚙️ Parámetros":
    st.markdown("## ⚙️ Parámetros del Sistema")
    st.caption("Valores actualizados a febrero 2026 · Barranquilla, Colombia")
    alerta("💡 Para modificar permanentemente, edita el archivo <strong>parametros.py</strong>.", "info")
    t1,t2,t3,t4 = st.tabs(["🪨 Tarifas por Material","📦 Catálogo referencia","🚛 Logística","🏨 Viáticos"])
    with t1:
        for cat, tar in TARIFAS.items():
            st.markdown(f"**{ICONOS.get(cat,'')} {cat}**")
            c1,c2,c3,c4,c5 = st.columns(5)
            c1.metric("Corte",     f"{cop(tar['corte'])}/m²")
            c2.metric("Elaborac.", f"{cop(tar['elab'])}/m²")
            c3.metric("Zócalo",    f"{cop(tar['zocalo'])}/ml")
            c4.metric("Disco",     f"{cop(tar['disco'])}/m²")
            c5.metric("Desgaste",  f"{cop(tar['desgaste'])}/día")
            st.divider()
    with t2:
        st.caption("Referencias de materiales comunes — el usuario puede ingresar cualquier precio/m² personalizado.")
        for m in MATERIALES_CATALOGO:
            c1,c2,c3 = st.columns(3)
            c1.markdown(f"**{m['nombre']}** — {badge(m['categoria'])}", unsafe_allow_html=True)
            c2.metric("Precio/m² referencia", cop(m["precio_m2"]))
            c3.metric("Área placa",           f"{m['area_placa']} m²")
    with t3:
        st.metric("Gasolina",f"{cop(LOGISTICA['gasolina'])}/galón")
        st.divider()
        c1,c2 = st.columns(2)
        with c1:
            st.markdown("**Frontier NP300**")
            st.metric("Rendimiento",f"{LOGISTICA['frontier']['rend']} km/gal")
            st.metric("Desgaste",f"{cop(LOGISTICA['frontier']['desgaste'])}/km")
            st.metric("Flete base",cop(LOGISTICA['frontier']['base']))
        with c2:
            st.markdown("**Cheyenne V8**")
            st.metric("Rendimiento",f"{LOGISTICA['cheyenne']['rend']} km/gal")
            st.metric("Desgaste",f"{cop(LOGISTICA['cheyenne']['desgaste'])}/km")
            st.metric("Flete base",cop(LOGISTICA['cheyenne']['base']))
        st.divider()
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Flete externo",cop(LOGISTICA['externo']['flete']))
        c2.metric("Flete agente",cop(LOGISTICA['agente']))
        c3.metric("Peaje",cop(LOGISTICA['peaje']))
        c4.metric("Desg. herramienta",cop(LOGISTICA['herram']))
    with t4:
        c1,c2 = st.columns(2)
        c1.metric("Pueblo/Corregimiento",f"{cop(VIATICOS['pueblo'])}/noche/persona")
        c2.metric("Ciudad Capital",f"{cop(VIATICOS['ciudad'])}/noche/persona")

# ═══════════════════════════════════════════════════════════════════════════════
# ASISTENTE IA
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "🤖 Asistente IA":
    st.markdown("## 🤖 Asistente IA de Costos")
    st.caption("Experto en mármoles · Barranquilla, Colombia · Powered by Claude")

    if ia_disponible():
        alerta("🟢 <strong>IA Activa</strong> — Haz cualquier pregunta o describe tu proyecto y te guío.", "bueno")
    else:
        alerta("🔌 <strong>IA en modo básico</strong> — Configura tu API key (instrucciones en la barra lateral).", "acepta")

    # ── MODO ESPECIAL: describir proyecto para pre-llenar calculadora ─────────
    st.markdown("### ✨ Describir proyecto para pre-llenar la calculadora")
    alerta("""💡 <strong>Cómo usar:</strong> Describe tu proyecto en tus propias palabras, como hablarías con un colega. 
    Por ejemplo: <em>"Tengo que fabricar una cocina de 4mt de largo por 90cm de ancho, el material es mármol 
    Crema Marfil con valor de m² de $420.000, compré media placa de 2.5 m², usé 2.42 m² para fabricar el mesón, 
    el proveedor trajo el material al taller, voy a entregar en la Frontier y la distancia es 8 km, 2 peajes."</em>""", "info")

    with st.form("form_proyecto"):
        desc_proyecto = st.text_area(
            "Describe tu proyecto aquí:",
            placeholder="Ej: Tengo que fabricar una cocina de 4mt de largo por 90cm de ancho, material mármol Crema Marfil a $420.000/m², compré media placa de 2.5 m², usé 2.42 m², el proveedor trajo el material al taller, voy en la Frontier 8 km, 2 peajes...",
            height=120,
        )
        btn_interpretar = st.form_submit_button("🤖 Interpretar proyecto y pre-llenar calculadora", use_container_width=True)

    if btn_interpretar and desc_proyecto.strip():
        if not ia_disponible():
            alerta("Necesitas configurar la API key de Anthropic para usar esta función.", "acepta")
        else:
            with st.spinner("🤖 Interpretando tu descripción..."):
                datos = interpretar_proyecto(desc_proyecto)
            if datos:
                st.session_state.pre = datos
                st.session_state.cat_sel = datos.get("categoria", "Mármol")

                # Mostrar lo que encontró
                st.markdown("**✅ Datos detectados:**")
                cols = st.columns(3)
                mostrados = 0
                campo_labels = {
                    "categoria": "Tipo de material", "referencia": "Referencia",
                    "precio_m2": "Precio/m²", "area_placa_comprada": "Área comprada (m²)",
                    "m2_usados": "m² usados", "m2_proyecto": "m² del proyecto",
                    "tipo_proyecto": "Tipo de proyecto",
                    "agente_externo_taller": "Agente externo→taller",
                    "vehiculo_entrega": "Vehículo entrega",
                    "km": "Distancia (km)", "peajes": "N° peajes",
                }
                for campo, label in campo_labels.items():
                    val = datos.get(campo)
                    if val is not None and val is not False and val != 0:
                        cols[mostrados % 3].success(f"**{label}:** {val}")
                        mostrados += 1

                if datos.get("datos_faltantes"):
                    st.warning("**Datos que no detecté (deberás completarlos en la calculadora):** " + ", ".join(datos["datos_faltantes"]))

                st.success("✅ ¡Listo! Ve a **⚡ Cotización Directa** — los campos ya están pre-llenados con tu proyecto.")
            else:
                alerta("No pude interpretar la descripción. Intenta ser más específico o ve directamente a la calculadora.", "acepta")

    st.markdown("---")

    # ── CHAT NORMAL ──────────────────────────────────────────────────────────
    st.markdown("### 💬 Chat con el asistente")
    preguntas = [
        ("¿Qué % AIU usar?",     "¿Qué porcentaje de AIU debo usar para una licitación con una constructora en Colombia?"),
        ("¿Margen saludable?",   "¿Cuál es el margen de utilidad saludable para una marmolería en Barranquilla?"),
        ("¿Estoy subcotizando?", "¿Cómo sé si estoy subcotizando un proyecto de mármoles?"),
        ("Desgaste máquina",     "¿Cómo calculo el desgaste de mi máquina cortadora en los costos?"),
        ("Flete a Cartagena",    "¿Cuánto me cuesta el flete para un proyecto en Cartagena desde Barranquilla?"),
        ("Mármol vs Sinterizado","¿Cuál es la diferencia de costo entre trabajar mármol y sinterizado?"),
    ]
    c1,c2,c3 = st.columns(3)
    for idx,(label,preg) in enumerate(preguntas):
        col = [c1,c2,c3][idx%3]
        if col.button(label, key=f"qr_{idx}", use_container_width=True):
            st.session_state.chat.append({"role":"user","content":preg})
            with st.spinner("La IA está pensando..."):
                resp = chat_con_ia([m for m in st.session_state.chat[:-1]], preg)
            st.session_state.chat.append({"role":"assistant","content":resp})
            st.rerun()

    st.markdown("---")

    # Historial
    chat_html = '<div style="background:#f8fbff;border:1px solid #deeefa;border-radius:12px;padding:14px;max-height:500px;overflow-y:auto;margin-bottom:12px">'
    if not st.session_state.chat:
        chat_html += '<div style="background:#0d2744;color:rgba(255,255,255,.85);padding:12px 16px;border-radius:4px 14px 14px 14px;font-size:.88rem;line-height:1.6;max-width:90%">👋 Hola, soy el asistente de costos de <strong style="color:#4da3f5">Mármoles Collante & Castro</strong>.<br><br>Puedo ayudarte de dos formas:<br>1️⃣ <strong>Describe tu proyecto</strong> arriba y pre-lleno la calculadora por ti.<br>2️⃣ <strong>Hazme cualquier pregunta</strong> sobre costos, materiales, AIU o cotización.<br><br>¿Por dónde empezamos?</div>'
    for msg in st.session_state.chat:
        if msg["role"] == "user":
            chat_html += f'<div style="background:#1a6bb5;color:white;padding:10px 16px;border-radius:14px 4px 14px 14px;font-size:.88rem;line-height:1.6;max-width:85%;margin-left:auto;text-align:right;margin-top:10px">{msg["content"]}</div>'
        else:
            content = msg["content"].replace("\n","<br>")
            chat_html += f'<div style="background:#0d2744;color:rgba(255,255,255,.87);padding:12px 16px;border-radius:4px 14px 14px 14px;font-size:.88rem;line-height:1.7;max-width:90%;margin-top:10px">{content}</div>'
    chat_html += '</div>'
    st.markdown(chat_html, unsafe_allow_html=True)

    with st.form("chat_form", clear_on_submit=True):
        c1,c2 = st.columns([5,1])
        msg  = c1.text_input("Pregunta",placeholder="Ej: ¿Cuánto debería cobrar por 8m² de Crema Marfil en una cocina?",label_visibility="collapsed")
        enviar = c2.form_submit_button("Enviar →", use_container_width=True)

    if enviar and msg.strip():
        st.session_state.chat.append({"role":"user","content":msg.strip()})
        with st.spinner("La IA está escribiendo..."):
            resp = chat_con_ia([m for m in st.session_state.chat[:-1]], msg.strip())
        st.session_state.chat.append({"role":"assistant","content":resp})
        st.rerun()

    if st.session_state.chat:
        if st.button("🗑️ Limpiar conversación"):
            st.session_state.chat = []
            st.rerun()
