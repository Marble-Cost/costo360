# ui_express.py — Costo360
# Módulo independiente: Modo Express — Cotización ultrarrápida en una sola pantalla.
# Extraído de app.py mediante el Patrón de Estrangulamiento.
# Todas las dependencias están declaradas aquí. No requiere imports de app.py.

import copy
import streamlit as st

from calculos import calcular_cotizacion_directa, cop
from parametros import (
    CATEGORIAS_MATERIAL,
    ADICIONALES,
    MATERIALES_CATALOGO,
    PROPIEDADES_MATERIAL,
)


# ── Helpers locales (replicados de app.py para independencia total) ───────────

def _bloque_costos(items_label_valor, total_label, total_val):
    """Renderiza tabla de desglose de costos en HTML."""
    html = ""
    for label, valor in items_label_valor:
        html += (
            f'<div style="display:flex;justify-content:space-between;padding:6px 0;'
            f'border-bottom:1px solid var(--border-color);color:var(--text-color);">'
            f'<span style="font-size:0.87rem;">{label}</span>'
            f'<span style="font-size:0.87rem;font-weight:600">{cop(valor)}</span></div>'
        )
    html += (
        f'<div style="display:flex;justify-content:space-between;padding:10px 0 0 0;'
        f'border-bottom:1px solid var(--border-color);color:var(--text-color);">'
        f'<span style="font-size:0.95rem;font-weight:800">{total_label}</span>'
        f'<span style="font-size:0.95rem;font-weight:800;color:#1B5FA8">{cop(total_val)}</span></div>'
    )
    st.markdown(f'<div class="card-custom">{html}</div>', unsafe_allow_html=True)


def _get_adicionales_ex():
    """Devuelve lista de adicionales respetando customizaciones del usuario."""
    return (
        copy.deepcopy(st.session_state.adicionales_custom)
        if st.session_state.get("adicionales_custom")
        else copy.deepcopy(ADICIONALES)
    )




# ═══════════════════════════════════════════════════════════════════════════════
# MODO EXPRESS — Cotización ultrarrápida en una sola pantalla
# ═══════════════════════════════════════════════════════════════════════════════

def _ui_cotizacion_express():
    """
    Cotización de una sola pantalla. Aplica la lógica dual ML/m² según tipo
    de proyecto y llama a calcular_cotizacion_directa con valores por defecto
    para logística local. Sin wizard, sin pasos, sin esperas.
    """
    st.markdown(
        '<div style="background:linear-gradient(135deg,#0B2432,#1B5FA8);'
        'border-radius:14px;padding:20px 26px;margin-bottom:22px">'
        '<div style="font-size:0.67rem;font-weight:800;letter-spacing:0.13em;'
        'color:rgba(255,255,255,0.5);text-transform:uppercase;margin-bottom:4px">'
        'Costo360</div>'
        '<div style="font-size:1.25rem;font-weight:900;color:white;margin-bottom:3px">'
        '⚡ Modo Express — Cotización en segundos</div>'
        '<div style="font-size:0.8rem;color:rgba(255,255,255,0.6)">'
        'Una sola pantalla. Cálculo real. Sin pasos.</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Tipos de proyecto y su lógica de cobro ────────────────────────────────
    _EX_TIPOS_ML = ["Mesón", "Cocina", "Baño", "Escalera", "Encimera"]
    _EX_TIPOS_M2 = ["Piso", "Fachada", "Revestimiento", "Otro"]
    _EX_TODOS_TIPOS = _EX_TIPOS_ML + _EX_TIPOS_M2

    # Anchos estándar por tipo de proyecto (ML)
    _EX_ANCHOS = {
        "Mesón":     0.60,
        "Cocina":    0.60,
        "Baño":      0.50,
        "Escalera":  0.30,
        "Encimera":  0.60,
    }

    _col_form, _col_res = st.columns([1.05, 1], gap="large")

    with _col_form:
        # ── Bloque 1: Tipo de proyecto ────────────────────────────────────────
        with st.container(border=True):
            st.markdown("**📋 Proyecto**")
            _ex_tipo = st.selectbox(
                "Tipo de proyecto",
                _EX_TODOS_TIPOS,
                key="ex2_tipo",
            )
            _es_ml = _ex_tipo in _EX_TIPOS_ML
            _ex_cliente = st.text_input(
                "Cliente (opcional)",
                placeholder="Ej: Constructora Ducal",
                key="ex2_cliente",
            )

        # ── Bloque 2: Material ────────────────────────────────────────────────
        with st.container(border=True):
            st.markdown("**🪨 Material**")
            _c1, _c2 = st.columns(2)
            with _c1:
                _ex_cat = st.selectbox(
                    "Categoría",
                    CATEGORIAS_MATERIAL,
                    key="ex2_categoria",
                )
            with _c2:
                _refs_ex2 = MATERIALES_CATALOGO.get(_ex_cat, []) + ["Otra referencia..."]
                _ex_ref_sel = st.selectbox("Referencia", _refs_ex2, key="ex2_ref_sel")
                _ex_ref = (
                    st.text_input("Nombre", placeholder="Ej: Calacatta Oro", key="ex2_ref_custom")
                    if _ex_ref_sel == "Otra referencia..."
                    else _ex_ref_sel
                )

            _c3, _c4, _c5 = st.columns(3)
            with _c3:
                _ex_pm2 = st.number_input(
                    "Precio/m² ($)",
                    min_value=10_000, max_value=5_000_000,
                    value=220_000, step=5_000,
                    key="ex2_pm2",
                    help="Lo que pagaste al proveedor por m²",
                )
            with _c4:
                _ex_placa_largo = st.number_input(
                    "Largo placa (m)",
                    min_value=0.1, max_value=10.0,
                    value=3.20, step=0.10, format="%.2f",
                    key="ex2_placa_largo",
                )
            with _c5:
                _ex_placa_ancho = st.number_input(
                    "Ancho placa (m)",
                    min_value=0.1, max_value=5.0,
                    value=1.80, step=0.10, format="%.2f",
                    key="ex2_placa_ancho",
                )
            _ex_area_placa = round(_ex_placa_largo * _ex_placa_ancho, 4)
            st.caption(f"Área de lámina: **{_ex_area_placa:.2f} m²** — Costo: **{cop(_ex_pm2 * _ex_area_placa)}**")

        # ── Bloque 3: Dimensiones del proyecto ───────────────────────────────
        with st.container(border=True):
            if _es_ml:
                st.markdown("**📏 Dimensiones (ML)**")
                _c6, _c7 = st.columns(2)
                with _c6:
                    _ex_ml_val = st.number_input(
                        "Metros lineales",
                        min_value=0.1, max_value=500.0,
                        value=3.0, step=0.1, format="%.2f",
                        key="ex2_ml",
                    )
                with _c7:
                    _ancho_std = _EX_ANCHOS.get(_ex_tipo, 0.60)
                    _ex_ancho = st.number_input(
                        "Ancho (m)",
                        min_value=0.05, max_value=4.0,
                        value=_ancho_std, step=0.05, format="%.2f",
                        key="ex2_ancho",
                        help=f"Ancho estándar para {_ex_tipo}: {_ancho_std} m",
                    )
                _ex_m2_proyecto = round(_ex_ml_val * _ex_ancho, 4)
                _ex_ml_final = _ex_ml_val
                _unidad_venta = "ml"
                st.caption(f"Área del proyecto: **{_ex_ml_val:.2f} ml × {_ex_ancho:.2f} m = {_ex_m2_proyecto:.3f} m²**")
            else:
                st.markdown("**📐 Dimensiones (m²)**")
                _ex_m2_proyecto = st.number_input(
                    "Metros cuadrados (m²)",
                    min_value=0.1, max_value=5000.0,
                    value=10.0, step=0.5, format="%.2f",
                    key="ex2_m2",
                )
                _ex_ancho = 1.0
                _ex_ml_final = _ex_m2_proyecto
                _unidad_venta = "m2"
                st.caption(f"Área del proyecto: **{_ex_m2_proyecto:.2f} m²**")

        # ── Bloque 4: Margen ──────────────────────────────────────────────────
        with st.container(border=True):
            st.markdown("**📈 Precio**")
            _c8, _c9 = st.columns(2)
            with _c8:
                _ex_margen = st.slider(
                    "Margen de utilidad (%)",
                    min_value=5, max_value=70, value=40, step=1,
                    key="ex2_margen",
                )
            with _c9:
                _ex_iva = st.checkbox("Incluir IVA 19%", value=False, key="ex2_iva")

        # ── Botón calcular ────────────────────────────────────────────────────
        _btn_ex = st.button(
            "⚡ Calcular cotización",
            type="primary",
            use_container_width=True,
            key="ex2_btn_calcular",
        )

    # ── Motor de cálculo ──────────────────────────────────────────────────────
    if _btn_ex:
        _props_ex   = PROPIEDADES_MATERIAL.get(_ex_cat, PROPIEDADES_MATERIAL["Mármol"])
        _merma_ex   = _props_ex["merma_base"]
        _add_ex     = _get_adicionales_ex()
        _cant_ex    = [0] * len(_add_ex)

        _pieza_ex = {
            "nombre":       _ex_tipo,
            "ml":           _ex_ml_final,
            "ml_unitario":  _ex_ml_final,
            "cantidad":     1,
            "ancho":        _ex_ancho,
            "ancho_custom": _ex_ancho,
            "unidad_venta": _unidad_venta,
            "categoria":    _ex_cat,
        }
        _mats_ex = [{
            "cat":        _ex_cat,
            "ref":        _ex_ref,
            "precio_m2":  float(_ex_pm2),
            "area_placa": _ex_area_placa,
        }]

        try:
            _res_ex = calcular_cotizacion_directa(
                categoria=_ex_cat,
                referencia=_ex_ref,
                precio_m2=float(_ex_pm2),
                area_placa_comprada=_ex_area_placa,
                m2_real=_ex_m2_proyecto,
                m2_cortados=round(_ex_m2_proyecto * (1 + _merma_ex), 4),
                m2_usados=_ex_m2_proyecto,
                margen_pct=float(_ex_margen),
                dias=1,
                personas=2,
                zocalo_activo=False,
                zocalo_ml=0.0,
                agente_externo_taller=False,
                vehiculo_entrega="externo",
                km=5.0,
                num_peajes=0,
                foraneo_activo=False,
                viaticos_activos=False,
                tipo_aloj="pueblo",
                noches=0,
                adicionales_activos=False,
                cantidades_add=_cant_ex,
                etapa="terminada",
                adicionales_lista=_add_ex,
                tipo_proyecto=_ex_tipo,
                nombre_cliente=_ex_cliente or "Sin nombre",
                piezas=[_pieza_ex],
                materiales_lista=_mats_ex,
                tarifas_override=st.session_state.get("tarifas_custom"),
                logistica_override=st.session_state.get("logistica_custom"),
                incluir_iva=_ex_iva,
            )
            st.session_state["ex2_resultado"] = _res_ex
        except Exception as _e_ex2:
            st.session_state["ex2_resultado"] = None
            st.error(f"Error en el cálculo: {_e_ex2}")

    # ── Panel de resultados (columna derecha) ─────────────────────────────────
    with _col_res:
        _r = st.session_state.get("ex2_resultado")
        _iva_panel  = st.session_state.get("ex2_iva", False)
        _marg_panel = st.session_state.get("ex2_margen", 40)

        if not _r:
            st.markdown(
                '<div style="border:2px dashed #C8D8E8;border-radius:12px;'
                'padding:52px 24px;text-align:center;background:#F8FAFD;color:#6B85A0;margin-top:8px">'
                '<div style="font-size:2.8rem;margin-bottom:12px">⚡</div>'
                '<div style="font-size:1rem;font-weight:700;color:#1C2B3A;margin-bottom:6px">'
                'El resultado aparecerá aquí</div>'
                '<div style="font-size:0.82rem;line-height:1.6">'
                'Completa los campos y presiona<br><strong>⚡ Calcular cotización</strong>.</div>'
                '</div>',
                unsafe_allow_html=True,
            )
        else:
            _precio_final = _r["precio_sugerido"] * (1.19 if _iva_panel else 1.0)
            _pml = (_precio_final / _r["ml_proyecto"]) if _r.get("ml_proyecto", 0) > 0 else 0

            # Semáforo de margen
            _mg = _r["margen_pct"]
            if _mg >= 30:
                _sem, _sem_txt = "🟢", "Margen saludable"
            elif _mg >= 20:
                _sem, _sem_txt = "🟡", "Margen aceptable"
            else:
                _sem, _sem_txt = "🔴", "Margen bajo"

            # Tarjeta de precio principal
            st.markdown(
                f'<div style="background:linear-gradient(135deg,#0B2432,#1B5FA8);'
                f'border-radius:14px;padding:22px 24px;color:white;margin-bottom:16px">'
                f'<div style="font-size:0.67rem;font-weight:800;letter-spacing:0.12em;'
                f'opacity:0.55;text-transform:uppercase;margin-bottom:4px">'
                f'{"Precio con IVA" if _iva_panel else "Precio de venta"}</div>'
                f'<div style="font-size:clamp(1.7rem,4vw,2.8rem);font-weight:900;'
                f'font-family:Playfair Display,serif;line-height:1.1;margin-bottom:8px">'
                f'{cop(_precio_final)}</div>'
                f'<div style="font-size:0.82rem;opacity:0.75;margin-bottom:8px">'
                f'Utilidad: {cop(_r["utilidad"])}'
                f'{f" · {cop(_pml)}/ml" if _pml > 0 else ""}</div>'
                f'<div style="font-size:0.82rem;font-weight:700">'
                f'{_sem} {_sem_txt} — {_mg:.1f}%</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

            # Métricas clave
            _ma, _mb, _mc = st.columns(3)
            _ma.metric("Costo total",     cop(_r["costo_total"]))
            _mb.metric("Aprovechamiento", f'{_r["aprovechamiento"]:.1f}%')
            _mc.metric("Retal",           f'{_r["retal"]:.2f} m²')

            # Desglose detallado
            with st.expander("📊 Ver desglose completo", expanded=True):
                _bloque_costos(
                    [
                        ("Material",     _r["c1_material"]),
                        ("Mano de obra", _r["c2_mano_obra"]),
                        ("Insumos",      _r["c4_insumos"]),
                        ("Logística",    _r["c5_logistica"]),
                    ],
                    "COSTO TOTAL",
                    _r["costo_total"],
                )
                _props_disp = PROPIEDADES_MATERIAL.get(
                    st.session_state.get("ex2_categoria", "Mármol"),
                    PROPIEDADES_MATERIAL["Mármol"]
                )
                st.caption(
                    f"Merma aplicada: {_props_disp['merma_base']*100:.0f}% · "
                    f"Área lámina: {_r['area_placa']:.2f} m² · "
                    f"Logística: distancia local (5 km, sin peajes)"
                )

            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

            # Acciones
            _ba1, _ba2 = st.columns(2)
            with _ba1:
                def _pasar_a_completo():
                    _ancho_ref = st.session_state.get("ex2_ancho", 0.60)
                    _ml_ref    = st.session_state.get("ex2_ml", st.session_state.get("ex2_m2", 3.0))
                    _placa_l   = float(st.session_state.get("ex2_placa_largo", 3.20))
                    _placa_a   = float(st.session_state.get("ex2_placa_ancho", 1.80))
                    _area_ref  = round(_placa_l * _placa_a, 4)
                    _tipo_ref  = st.session_state.get("ex2_tipo", "Mesón")
                    _ex_tipos_ml_cb = ["Mesón", "Cocina", "Baño", "Escalera", "Encimera"]
                    st.session_state.pre = {
                        "categoria":           st.session_state.get("ex2_categoria", "Mármol"),
                        "referencia":          st.session_state.get("ex2_ref_custom", "")
                                               or st.session_state.get("ex2_ref_sel", ""),
                        "precio_m2":           float(st.session_state.get("ex2_pm2", 220_000)),
                        "area_placa_comprada": _area_ref,
                        "margen_pct":          float(st.session_state.get("ex2_margen", 40)),
                        "nombre_cliente":      st.session_state.get("ex2_cliente", ""),
                        "tipo_proyecto":       _tipo_ref,
                        "incluir_iva":         st.session_state.get("ex2_iva", False),
                        "piezas": [{
                            "nombre":       _tipo_ref,
                            "ml":           _ml_ref,
                            "ml_unitario":  _ml_ref,
                            "cantidad":     1,
                            "ancho_custom": _ancho_ref,
                            "unidad_venta": "ml" if _tipo_ref in _ex_tipos_ml_cb else "m2",
                        }],
                        "materiales_proyecto": [{
                            "cat":          st.session_state.get("ex2_categoria", "Mármol"),
                            "ref":          st.session_state.get("ex2_ref_custom", "")
                                            or st.session_state.get("ex2_ref_sel", ""),
                            "precio_m2":    float(st.session_state.get("ex2_pm2", 220_000)),
                            "area_placa":   _area_ref,
                            "placas_largo": _placa_l,
                            "placas_ancho": _placa_a,
                            "placas_cant":  1,
                        }],
                    }
                    st.session_state.materiales_proyecto = st.session_state.pre["materiales_proyecto"]
                    st.session_state.piezas              = st.session_state.pre["piezas"]
                    st.session_state.cdir_paso           = 0
                    st.session_state.nav_radio           = "Cotizacion Directa"
                    st.query_params["pagina"]            = "Cotizacion Directa"

                st.button(
                    "🚀 Refinar en Modo Completo",
                    on_click=_pasar_a_completo,
                    type="primary",
                    use_container_width=True,
                    key="ex2_btn_completo",
                    help="Pre-carga todos estos datos en el wizard para agregar logística, viáticos y más.",
                )
            with _ba2:
                if st.button(
                    "🗑️ Limpiar",
                    use_container_width=True,
                    key="ex2_btn_limpiar",
                ):
                    for _ek in [k for k in list(st.session_state.keys()) if k.startswith("ex2_")]:
                        st.session_state.pop(_ek, None)
                    st.rerun()

        st.info(
            "⚡ Logística asumida: **entrega local (5 km)**, sin peajes ni viáticos. "
            "Usa **🚀 Refinar en Modo Completo** para ajustar estos parámetros.",
            icon="💡",
        )
