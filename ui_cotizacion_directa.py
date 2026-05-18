# ui_cotizacion_directa.py
# ─────────────────────────────────────────────────────────────────────────────
# Módulo de Cotización Directa — Wizard de 5 pasos
# Extraído de app.py siguiendo el patrón Strangler Fig (Fase 8).
#
# REGLA ARQUITECTÓNICA: este archivo NUNCA importa app.py.
# Dependencias de BD, callbacks y estado global se inyectan como parámetros.
#
# Firma: _ui_cotizacion_directa(
#   fn_sp, fn_sp_set, fn_sp_commit_borrador,
#   fn_sp_agregar_pieza, fn_sp_eliminar_pieza, fn_sp_sync_piezas,
#   fn_sp_agregar_material, fn_sp_eliminar_material, fn_sp_sync_materiales,
#   fn_guardar_cotizacion, fn_actualizar_cotizacion,
#   fn_guardar_borrador_cotizacion, fn_guardar_config,
#   fn_leer_config, fn_clave_borrador_cdir,
#   fn_consultar_retal, fn_marcar_retal_usado,
#   fn_get_tarifas, fn_get_logistica, fn_get_viaticos, fn_get_adicionales,
#   fn_generar_snapshot_datos,
#   fn_cb_cdir_nombre_cliente, fn_cb_cdir_tipos_proyecto, fn_cb_cdir_etapa,
#   fn_cb_cdir_agente_externo, fn_cb_cdir_km_rango,
#   fn_cb_cdir_foraneo, fn_cb_cdir_viaticos_activos, fn_cb_cdir_tipo_aloj,
#   fn_cb_cdir_noches, fn_cb_cdir_perfil_desperdicio,
#   fn_cb_cdir_adicionales_activos, fn_cb_cdir_incluir_iva,
# )
# ─────────────────────────────────────────────────────────────────────────────
import json
import time
import random as _rand
from datetime import date

import streamlit as st
import plotly.graph_objects as go

from calculos import (
    calcular_cotizacion_directa, ml_a_m2, cop,
    calcular_zocalo_geometrico,
)
from parametros import (
    CATEGORIAS_MATERIAL, ETAPAS_OBRA, ALOJAMIENTO,
    MATERIALES_CATALOGO, ANCHOS_ESTANDAR, CROSS_SELLING_MAP,
    BADGE_COLORS, DESCRIPCIONES_CATEGORIA, TARIFAS,
    INCLUSIONES_BASE, EXCLUSIONES_BASE,
)


# ── Utilidades de presentación ────────────────────────────────────────────────

def _hoy() -> date:
    return date.today()

def _numero_completo(valor) -> str:
    return "$" + f"{int(round(valor)):,}".replace(",", ".")

def _fmt_m2(valor: float, decimales: int = 3) -> str:
    return f"{valor:.{decimales}f} m²"

def _fmt_ml(valor: float, decimales: int = 2) -> str:
    return f"{valor:.{decimales}f} ml"

def _alerta(texto, tipo="info"):
    fn = {"info": st.info, "warning": st.warning, "error": st.error,
          "success": st.success, "bueno": st.success, "acepta": st.warning,
          "bajo": st.error}.get(tipo, st.info)
    fn(texto)

def _seccion_titulo(texto, subtexto=""):
    st.markdown(f"### {texto}")
    if subtexto:
        st.caption(subtexto)

def _bloque_costos(items_label_valor, total_label, total_val):
    for lbl, val in items_label_valor:
        c1, c2 = st.columns([3, 1])
        c1.markdown(f"<span style='font-size:0.88rem'>{lbl}</span>", unsafe_allow_html=True)
        c2.markdown(
            f"<span style='font-size:0.88rem;font-weight:700;float:right'>"
            f"{_numero_completo(val)}</span>",
            unsafe_allow_html=True,
        )
    st.markdown(
        f"<div style='border-top:2px solid #1F6F54;margin-top:6px;padding-top:8px;"
        f"display:flex;justify-content:space-between;font-weight:900;font-size:1rem'>"
        f"<span>{total_label}</span><span>{_numero_completo(total_val)}</span></div>",
        unsafe_allow_html=True,
    )


# ── Módulo principal ──────────────────────────────────────────────────────────

def _ui_cotizacion_directa(
    fn_sp,
    fn_sp_set,
    fn_sp_commit_borrador,
    fn_sp_agregar_pieza,
    fn_sp_eliminar_pieza,
    fn_sp_sync_piezas,
    fn_sp_agregar_material,
    fn_sp_eliminar_material,
    fn_sp_sync_materiales,
    fn_guardar_cotizacion,
    fn_actualizar_cotizacion,
    fn_guardar_borrador_cotizacion,
    fn_guardar_config,
    fn_leer_config,
    fn_clave_borrador_cdir,
    fn_consultar_retal,
    fn_marcar_retal_usado,
    fn_get_tarifas,
    fn_get_logistica,
    fn_get_viaticos,
    fn_get_adicionales,
    fn_generar_snapshot_datos,
    fn_cb_cdir_nombre_cliente,
    fn_cb_cdir_tipos_proyecto,
    fn_cb_cdir_etapa,
    fn_cb_cdir_agente_externo,
    fn_cb_cdir_km_rango,
    fn_cb_cdir_foraneo,
    fn_cb_cdir_viaticos_activos,
    fn_cb_cdir_tipo_aloj,
    fn_cb_cdir_noches,
    fn_cb_cdir_perfil_desperdicio,
    fn_cb_cdir_adicionales_activos,
    fn_cb_cdir_incluir_iva,
):
    """Renderiza el wizard completo de Cotización Directa (5 pasos)."""

    st.markdown("""
    <div style="margin-bottom:24px;padding-bottom:18px;border-bottom:1px solid rgba(31,111,84,0.2)">
      <div style="font-size:0.65rem;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;
           color:rgba(201,164,92,0.7);margin-bottom:6px">Cotización</div>
      <h2 style="font-family:'Playfair Display',serif;font-size:1.9rem;font-weight:700;
           color:#E8F0EB;margin:0 0 5px">Cotización Directa</h2>
      <p style="color:rgba(232,240,235,0.5);font-size:0.88rem;margin:0;line-height:1.5">
        Wizard de 5 pasos: material, dimensiones, proyecto, logística y resultado con PDF.
      </p>
    </div>
    """, unsafe_allow_html=True)

    # ── Event-driven state sync: store_permanente → pre (on page entry) ───────
    _sp_entry = fn_sp()
    if _sp_entry.get("cdir_piezas") or _sp_entry.get("cdir_materiales"):
        _pre_from_store = {
            "materiales_proyecto": _sp_entry.get("cdir_materiales", []),
            "piezas":              _sp_entry.get("cdir_piezas", []),
            "margen_pct":          _sp_entry.get("cdir_margen_pct", 40),
            "m2_usados":           _sp_entry.get("cdir_m2_usados", 0.0),
            "tipo_proyecto":       _sp_entry.get("cdir_tipo_proyecto", "Meson"),
            "tipos_proyecto":      _sp_entry.get("cdir_tipos_proyecto", ["Meson"]),
            "etapa_label":         _sp_entry.get("cdir_etapa_label", "Casa terminada (limpia)"),
            "nombre_cliente":      _sp_entry.get("cdir_nombre_cliente", ""),
            "telefono_cliente":    _sp_entry.get("cdir_telefono_cliente", ""),
            "email_cliente":       _sp_entry.get("cdir_email_cliente", ""),
            "ciudad_proyecto":     _sp_entry.get("cdir_ciudad_proyecto", ""),
            "dias_obra":           _sp_entry.get("cdir_dias_obra", 2),
            "personas":            _sp_entry.get("cdir_personas", 2),
            "zocalo_activo":       _sp_entry.get("cdir_zocalo_activo", False),
            "zocalo_ml":           _sp_entry.get("cdir_zocalo_ml", 0.0),
            "agente_externo_taller": _sp_entry.get("cdir_agente_externo", False),
            "km":                  _sp_entry.get("cdir_km", 5.0),
            "peajes":              _sp_entry.get("cdir_peajes", 0),
            "foraneo_activo":      _sp_entry.get("cdir_foraneo", False),
            "viaticos_activos":    _sp_entry.get("cdir_viaticos_activos", False),
            "tipo_aloj":           _sp_entry.get("cdir_tipo_aloj", "pueblo"),
            "noches":              _sp_entry.get("cdir_noches", 0),
            "adicionales_activos": _sp_entry.get("cdir_adicionales_activos", False),
            "cantidades_add":      _sp_entry.get("cdir_cantidades_add", []),
            "incluir_iva":         _sp_entry.get("cdir_incluir_iva", True),
            "cdir_paso":           _sp_entry.get("cdir_paso", 0),
        }
        _pre_existing = st.session_state.get("pre", {})
        if not _pre_existing or _pre_existing.get("_origen") == "borrador":
            st.session_state.pre = _pre_from_store
            if _pre_from_store["piezas"]:
                st.session_state.piezas = _pre_from_store["piezas"]
            if _pre_from_store["materiales_proyecto"]:
                st.session_state.materiales_proyecto = _pre_from_store["materiales_proyecto"]
        if "cdir_paso" not in st.session_state or st.session_state.get("cdir_paso") != _sp_entry.get("cdir_paso", 0):
            st.session_state.cdir_paso = _sp_entry.get("cdir_paso", 0)

    WIZARD_PASOS = [
        {"icono": "🪨", "label": "Material"},
        {"icono": "📐", "label": "Dimensiones"},
        {"icono": "🏗️", "label": "Proyecto"},
        {"icono": "🚛", "label": "Logística"},
        {"icono": "✅", "label": "Resultado"},
    ]
    N_PASOS = len(WIZARD_PASOS)

    if "cdir_paso" not in st.session_state:
        st.session_state.cdir_paso = 0
    if "cdir_success" not in st.session_state:
        st.session_state.cdir_success = False

    pre = st.session_state.pre

    # ── Restaurar borrador desde BD (una sola vez post-F5) ───────────────────
    if not pre and not st.session_state.get("_borrador_restaurado"):
        try:
            _borrador = fn_leer_config(fn_clave_borrador_cdir())
            if _borrador:
                _borrador["_origen"] = "borrador"
                st.session_state.pre = _borrador
                pre = _borrador
                if "piezas" in _borrador and _borrador["piezas"]:
                    st.session_state.piezas = _borrador["piezas"]
                if "materiales_proyecto" in _borrador and _borrador["materiales_proyecto"]:
                    st.session_state.materiales_proyecto = _borrador["materiales_proyecto"]
                if "cantidades_add" in _borrador:
                    st.session_state["_cantidades_add_restauradas"] = _borrador["cantidades_add"]
                if "cdir_paso" in _borrador and isinstance(_borrador["cdir_paso"], int):
                    st.session_state.cdir_paso = _borrador["cdir_paso"]
                for _rk, _rv in _borrador.items():
                    if _rk.startswith("retal_id_") and _rv:
                        st.session_state[_rk] = _rv
        except Exception:
            pass
        st.session_state["_borrador_restaurado"] = True

    if pre and pre.get("_origen") in ("historial", "ia"):
        _alerta("Datos cargados desde Historial o IA. Revisa y ajusta lo que necesites.", "bueno")
        st.session_state.pre.pop("_origen", None)
    elif pre and pre.get("_origen") == "borrador":
        _alerta("📋 Se restauró tu último cálculo. Puedes continuar donde lo dejaste.", "info")
        st.session_state.pre.pop("_origen", None)

    # ── Atajo de edición ─────────────────────────────────────────────────────
    if st.session_state.get("editando_id"):
        _eid  = st.session_state["editando_id"]
        _enum = st.session_state.get("editando_num", "")
        st.markdown(
            f'<div style="background:rgba(201,168,76,0.10);border:1px solid rgba(201,168,76,0.45);'
            f'border-left:4px solid #C9A45C;border-radius:10px;'
            f'padding:14px 18px;margin-bottom:20px">'
            f'<div style="font-size:0.70rem;font-weight:800;color:#C9A45C;'
            f'text-transform:uppercase;letter-spacing:0.09em;margin-bottom:3px">✏️ Modo edición activo</div>'
            f'<div style="font-size:0.90rem;font-weight:600">Modificando cotización: '
            f'<strong>{_enum}</strong></div>'
            f'<div style="font-size:0.75rem;opacity:0.60;margin-top:4px">'
            f'Navega por el wizard para ajustar datos, o usa el botón de abajo para guardar '
            f'los cambios actuales inmediatamente sin recorrer todos los pasos.</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        _eat_c1, _eat_c2 = st.columns([2.5, 1])
        with _eat_c1:
            if st.button(
                f"💾 Guardar cambios de esta edición → {_enum}",
                type="primary",
                use_container_width=True,
                key="btn_guardar_atajo_edicion",
            ):
                _nombre_atajo = st.session_state.pre.get("nombre_cliente", "Sin nombre")
                _r_atajo = st.session_state.get("cotizacion")

                if not _r_atajo:
                    _pre_sb  = st.session_state.pre
                    _mats_sb = _pre_sb.get("materiales_proyecto", [])
                    if _mats_sb:
                        _m0 = _mats_sb[0]
                        _cat_sb  = _m0.get("cat", "Mármol")
                        _ref_sb  = _m0.get("ref", "")
                        _pm2_sb  = float(_m0.get("precio_m2") or 0)
                        _area_sb = float(_m0.get("area_placa") or 1.0)
                    else:
                        _cat_sb  = _pre_sb.get("categoria", "Mármol")
                        _ref_sb  = _pre_sb.get("referencia", "")
                        _pm2_sb  = float(_pre_sb.get("precio_m2") or 0)
                        _area_sb = float(_pre_sb.get("area_placa") or 1.0)
                    _add_sb      = fn_get_adicionales()
                    _cant_add_sb = _pre_sb.get("cantidades_add", [0] * len(_add_sb))
                    while len(_cant_add_sb) < len(_add_sb):
                        _cant_add_sb.append(0)
                    _etapa_sb = ETAPAS_OBRA.get(
                        _pre_sb.get("etapa_label", "Casa terminada (limpia)"), "terminada"
                    )
                    try:
                        _r_atajo = calcular_cotizacion_directa(
                            categoria=_cat_sb, referencia=_ref_sb, precio_m2=_pm2_sb,
                            area_placa_comprada=_area_sb,
                            materiales_lista=_mats_sb,
                            m2_real=float(_pre_sb.get("m2_proyecto") or _area_sb),
                            m2_cortados=float(_pre_sb.get("m2_cortados_input") or 0),
                            m2_usados=float(_pre_sb.get("m2_usados") or _area_sb),
                            margen_pct=float(_pre_sb.get("margen_pct") or 40),
                            dias=int(_pre_sb.get("dias_obra") or 1),
                            personas=int(_pre_sb.get("personas") or 2),
                            zocalo_activo=bool(_pre_sb.get("zocalo_activo", False)),
                            zocalo_ml=float(_pre_sb.get("zocalo_ml") or 0),
                            agente_externo_taller=bool(_pre_sb.get("agente_externo_taller", False)),
                            vehiculo_entrega="externo",
                            km=float(_pre_sb.get("km") or 10),
                            num_peajes=0,
                            foraneo_activo=bool(_pre_sb.get("foraneo_activo", False)),
                            viaticos_activos=bool(_pre_sb.get("viaticos_activos", True)),
                            tipo_aloj=_pre_sb.get("tipo_aloj", "pueblo"),
                            noches=int(_pre_sb.get("noches") or 0),
                            adicionales_activos=bool(_pre_sb.get("adicionales_activos", False)),
                            cantidades_add=_cant_add_sb,
                            etapa=_etapa_sb,
                            adicionales_lista=_add_sb,
                            tipo_proyecto=_pre_sb.get("tipo_proyecto", ""),
                            nombre_cliente=_nombre_atajo,
                            piezas=_pre_sb.get("piezas", []),
                            ml_proyecto=float(_pre_sb.get("ml_proyecto") or 0),
                            logistica_override=st.session_state.get("logistica_custom"),
                            tarifas_override=st.session_state.get("tarifas_custom"),
                            costo_peaje_unitario=float(_pre_sb.get("costo_peaje_total") or 0.0),
                            incluir_iva=_pre_sb.get("incluir_iva", False),
                        )
                        _r_atajo["_estado_guardado"] = _pre_sb
                        _r_atajo["incluir_iva"] = _pre_sb.get("incluir_iva", False)
                        st.session_state.cotizacion = _r_atajo
                    except Exception as _e_sb:
                        st.warning(
                            f"No se pudo recalcular automáticamente: {_e_sb}. "
                            "Navega al **Paso 4 (Logística)** y presiona **Calcular** primero.",
                            icon="⚠️",
                        )
                        _r_atajo = None

                if _r_atajo:
                    fn_actualizar_cotizacion(_eid, _enum, _nombre_atajo, _r_atajo)
                    st.session_state.pop("editando_id", None)
                    st.session_state.pop("editando_num", None)
                    st.session_state["_cotiz_guardada_num"] = _enum
                    st.session_state["cdir_success"] = True
                    st.success(f"✅ Cotización **{_enum}** actualizada correctamente.", icon="💾")
                    st.rerun()
        with _eat_c2:
            if st.button("✕ Cancelar edición", use_container_width=True, key="btn_cancelar_atajo_edicion"):
                st.session_state.pop("editando_id", None)
                st.session_state.pop("editando_num", None)
                st.session_state.cdir_paso = 0
                st.rerun()
        st.markdown("<hr style='margin:4px 0 20px'>", unsafe_allow_html=True)

    TARIFAS_ACT = fn_get_tarifas()
    LOG_ACT     = fn_get_logistica()
    VIA_ACT     = fn_get_viaticos()

    # ══════════════════════════════════════════════════════════════════════════
    # PANTALLA DE ÉXITO
    # ══════════════════════════════════════════════════════════════════════════
    if st.session_state.get("cdir_success") and st.session_state.cotizacion:
        r         = st.session_state.cotizacion
        _iva_act  = r.get("incluir_iva", False)
        _iva_monto   = r["precio_sugerido"] * 0.19 if _iva_act else 0.0
        _precio_final = r["precio_sugerido"] + _iva_monto

        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#1C1C1C 0%,#1F6F54 100%);
                    border-radius:18px;padding:40px 44px 32px;margin-bottom:24px;color:white;
                    box-shadow:0 8px 32px rgba(31,111,84,0.35)">
          <div style="display:flex;align-items:center;gap:16px;margin-bottom:20px">
            <div style="width:52px;height:52px;background:rgba(201,168,76,0.25);border-radius:50%;
                        display:flex;align-items:center;justify-content:center;font-size:1.6rem">✅</div>
            <div>
              <div style="font-size:0.7rem;letter-spacing:0.14em;text-transform:uppercase;
                          color:#C9A45C;font-weight:700;margin-bottom:2px">COTIZACIÓN FINALIZADA</div>
              <div style="font-size:1.1rem;font-weight:700">{r.get("nombre_cliente","") or "Sin nombre de cliente"}</div>
            </div>
          </div>
          <div style="font-size:0.72rem;text-transform:uppercase;letter-spacing:0.12em;
                      color:rgba(255,255,255,0.55);font-weight:700;margin-bottom:6px">
            {"Precio de venta (sin IVA)" if _iva_act else "Precio de venta"}
          </div>
          <div style="font-size:clamp(1.5rem,5vw,3.8rem);font-weight:900;font-family:'Playfair Display',serif;
                      line-height:1.1;margin-bottom:8px;word-break:break-word">{_numero_completo(r["precio_sugerido"])}</div>
          <div style="opacity:0.75;font-size:0.9rem">
            Margen: {r["margen_pct"]:.0f}% &nbsp;·&nbsp; Utilidad: {_numero_completo(r["utilidad"])}
            &nbsp;·&nbsp; {r.get("tipo_proyecto","Proyecto")} — {r.get("categoria","")}
          </div>
          {f'<div style="margin-top:14px;padding-top:14px;border-top:1px solid rgba(255,255,255,0.2);font-size:1.05rem;font-weight:700;color:#C9A45C">+ IVA 19%: {_numero_completo(_iva_monto)} &nbsp;→&nbsp; <span style="color:white">Total: {_numero_completo(_precio_final)}</span></div>' if _iva_act else ""}
        </div>""", unsafe_allow_html=True)

        with st.expander("📊 Ver desglose de costos", expanded=False):
            _items = [
                ("Material",    r["c1_material"]),
                ("Producción",  r["c2_mano_obra"]),
                ("Zócalos",     r["c3_zocalos"]),
                ("Insumos",     r["c4_insumos"]),
                ("Logística",   r["c5_logistica"]),
                ("Viáticos",    r["c6_viaticos"]),
                ("Adicionales", r["c7_adicionales"]),
            ]
            if _iva_act:
                _items += [("IVA 19% s/total", _iva_monto)]
            _bloque_costos(_items, "TOTAL CON IVA" if _iva_act else "PRECIO TOTAL", _precio_final)
            c1s, c2s = st.columns(2)
            c1s.metric("Aprovechamiento lámina", f"{r['aprovechamiento']:.1f}%", f"Retal: {_fmt_m2(r['retal'])}")
            c2s.metric("Costo/m² instalado", _numero_completo(r["costo_total"] / max(r["m2_real"], 0.001)))

        with st.expander("🎛️ Simular otro margen", expanded=False):
            _sim_m = st.slider("Margen (%)", 5, 80, int(r["margen_pct"]), 1, key="sim_slider")
            _sim_p = r["costo_total"] / (1 - _sim_m / 100)
            _sim_ut = _sim_p - r["costo_total"]
            _sim_iva = _sim_p * 0.19 if _iva_act else 0.0
            st.markdown(
                f"""<div style="background:var(--secondary-background-color);border:1px solid var(--border-color);
                border-radius:10px;padding:14px 18px">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
                  <span style="font-size:0.75rem;font-weight:700;opacity:0.55;text-transform:uppercase">{"Sin IVA" if _iva_act else "Precio total"}</span>
                  <span style="font-size:1.15rem;font-weight:900;color:#1F6F54">{_numero_completo(_sim_p)}</span>
                </div>
                {f'<div style="display:flex;justify-content:space-between;align-items:center;border-top:1px solid var(--border-color);padding-top:6px;margin-bottom:4px"><span style="font-size:0.75rem;font-weight:700;opacity:0.55;text-transform:uppercase">Con IVA 19%</span><span style="font-size:1.15rem;font-weight:900;color:#C9A45C">{_numero_completo(_sim_p + _sim_iva)}</span></div>' if _iva_act else ""}
                <div style="font-size:0.72rem;opacity:0.5">Utilidad: {_numero_completo(_sim_ut)} · Margen: {_sim_m}%</div>
                </div>""",
                unsafe_allow_html=True
            )

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        # ── Formalizar y guardar ──────────────────────────────────────────────
        _ya_formalizada = st.session_state.get("_cotiz_formalizada", False)
        with st.expander(
            "💾 Formalizar y Guardar Cotización" if not _ya_formalizada else "✅ Cotización formalizada",
            expanded=not _ya_formalizada,
        ):
            if _ya_formalizada:
                _num_form = st.session_state.get("_cotiz_formalizada_num", "")
                st.success(
                    f"Cotización **{_num_form}** registrada en el historial. "
                    f"Puedes descargar los documentos a continuación.",
                    icon="✅",
                )
            else:
                st.markdown(
                    "<div style='font-size:0.85rem;opacity:0.75;margin-bottom:12px'>"
                    "Completa los datos del cliente y el proyecto para registrar esta cotización "
                    "en tu historial permanente. <em>Si es solo una prueba, puedes omitir este paso.</em>"
                    "</div>",
                    unsafe_allow_html=True,
                )
                _fc1, _fc2 = st.columns(2)
                with _fc1:
                    _form_cliente = st.text_input(
                        "Nombre del Cliente *", value=r.get("nombre_cliente", ""),
                        placeholder="Ej: Constructora Ducal S.A.S.", key="form_cliente_nombre",
                    )
                with _fc2:
                    _form_proyecto = st.text_input(
                        "Nombre del Proyecto *", value="",
                        placeholder="Ej: Cocina Ducal Gold — Apto 402", key="form_proyecto_nombre",
                    )
                _num_form_input = st.text_input(
                    "Número de cotización",
                    value=st.session_state.get("_cotiz_guardada_num")
                          or st.session_state.get("cdir_num_auto", f"COT-{_hoy().strftime('%Y')}-001"),
                    key="form_num_cotizacion",
                )
                _fb1, _fb2 = st.columns([2, 1])
                with _fb1:
                    _btn_formalizar = st.button("💾 Guardar en Historial", type="primary", use_container_width=True, key="btn_formalizar_cotiz")
                with _fb2:
                    _btn_omitir = st.button("✕ Omitir", use_container_width=True, key="btn_omitir_formalizar")

                if _btn_formalizar:
                    _err_form = []
                    if not _form_cliente.strip():
                        _err_form.append("el **Nombre del Cliente**")
                    if not _form_proyecto.strip():
                        _err_form.append("el **Nombre del Proyecto**")
                    if _err_form:
                        st.warning(f"Por favor completa {' y '.join(_err_form)} antes de guardar.", icon="⚠️")
                    else:
                        _r_formalizado = dict(r)
                        _r_formalizado["nombre_cliente"]  = _form_cliente.strip()
                        _r_formalizado["nombre_proyecto"] = _form_proyecto.strip()
                        try:
                            _id_existente    = st.session_state.get("editando_id")
                            _num_ya_guardado = st.session_state.get("_cotiz_guardada_num", "")
                            if _id_existente and _num_ya_guardado:
                                fn_actualizar_cotizacion(_id_existente, _num_form_input.strip(), _form_cliente.strip(), _r_formalizado)
                                _num_registrado = _num_form_input.strip()
                            else:
                                fn_guardar_cotizacion(_num_form_input.strip(), _form_cliente.strip(), _r_formalizado)
                                _num_registrado = _num_form_input.strip()

                            for _mi_f, _md_f in enumerate(st.session_state.get("materiales_proyecto", [])):
                                if _md_f.get("es_retal") and _md_f.get("retal_id"):
                                    try:
                                        fn_marcar_retal_usado(_md_f["retal_id"], _md_f.get("area_placa", 0))
                                        st.session_state.pop(f"usar_retal_{_mi_f}", None)
                                    except Exception:
                                        pass
                            st.session_state["_cotiz_formalizada"]     = True
                            st.session_state["_cotiz_formalizada_num"] = _num_registrado
                            st.session_state["_cotiz_guardada"]        = True
                            st.session_state["_cotiz_guardada_num"]    = _num_registrado
                            st.rerun()
                        except Exception as _e_form:
                            st.error(f"No se pudo guardar: **{type(_e_form).__name__}** — {_e_form}.", icon="🚨")

                if _btn_omitir:
                    st.session_state["_cotiz_formalizada"]     = True
                    st.session_state["_cotiz_formalizada_num"] = ""
                    st.rerun()

        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

        # ── Auditor IA ────────────────────────────────────────────────────────
        with st.container(border=True):
            st.markdown("### 🤖 Auditor Predictivo de Rentabilidad")
            st.caption("Deja que la IA analice tus costos y márgenes antes de enviar la cotización al cliente.")
            if st.button("🔍 Auditar Cotización ahora", type="secondary", use_container_width=True):
                with st.spinner("Analizando riesgos financieros y fugas de capital..."):
                    try:
                        import importlib, asistente_ia
                        importlib.reload(asistente_ia)
                        _analisis_ia = asistente_ia.auditor_rentabilidad(r)
                        st.session_state["_auditoria_resultado"] = _analisis_ia
                    except Exception as e:
                        st.session_state["_auditoria_resultado"] = None
                        st.error(f"No se pudo completar la auditoría: {e}")

            _audit = st.session_state.get("_auditoria_resultado")
            if _audit:
                _color_estado = _audit.get("estado", "amarillo").lower()
                _margen_txt   = _audit.get("margen_analisis", "")
                _alertas      = _audit.get("alertas", [])
                _sugerencias  = _audit.get("sugerencias", [])
                with st.container(border=True):
                    if _color_estado == "verde":
                        st.success(f"🟢 **RENTABILIDAD SALUDABLE** — {_margen_txt}", icon="✅")
                    elif _color_estado == "rojo":
                        st.error(f"🔴 **ALERTA DE PÉRDIDA** — {_margen_txt}", icon="🚨")
                    else:
                        st.warning(f"🟡 **RIESGO MODERADO** — {_margen_txt}", icon="⚠️")
                    _col_alertas, _col_sugs = st.columns(2)
                    with _col_alertas:
                        st.markdown('<div style="font-size:0.78rem;font-weight:800;text-transform:uppercase;letter-spacing:0.08em;color:#C9A45C;margin-bottom:8px">⚠️ Alertas Críticas</div>', unsafe_allow_html=True)
                        for _a in (_alertas or ["Sin alertas detectadas."]):
                            st.markdown(f'<div style="background:rgba(201,168,76,0.07);border-left:3px solid #C9A45C;border-radius:0 6px 6px 0;padding:6px 10px;margin-bottom:6px;font-size:0.83rem;line-height:1.4">{_a}</div>', unsafe_allow_html=True)
                    with _col_sugs:
                        st.markdown('<div style="font-size:0.78rem;font-weight:800;text-transform:uppercase;letter-spacing:0.08em;color:#1F6F54;margin-bottom:8px">💡 Oportunidades</div>', unsafe_allow_html=True)
                        for _s in (_sugerencias or ["Sin oportunidades adicionales."]):
                            st.markdown(f'<div style="background:rgba(31,111,84,0.07);border-left:3px solid #1F6F54;border-radius:0 6px 6px 0;padding:6px 10px;margin-bottom:6px;font-size:0.83rem;line-height:1.4">{_s}</div>', unsafe_allow_html=True)

        st.markdown("---")

        # ── Seguro de desactualización ────────────────────────────────────────
        _snap_actual  = fn_generar_snapshot_datos()
        _snap_calculo = st.session_state.get("_snapshot_calculo", "")
        if _snap_calculo and _snap_actual != _snap_calculo:
            st.warning(
                "⚠️ **Aviso:** Detectamos que modificaste medidas, materiales o márgenes "
                "después de calcular. Te recomendamos volver al paso anterior y presionar "
                "**'Calcular'** nuevamente para actualizar los valores del PDF.",
                icon="⚠️",
            )

        # ── Condiciones comerciales ───────────────────────────────────────────
        st.markdown("### 💼 Condiciones Comerciales")
        with st.container(border=True):
            _ccom1, _ccom2, _ccom3 = st.columns(3)
            with _ccom1:
                anticipo_pct = st.number_input("Anticipo (%)", min_value=0, max_value=100, value=int(pre.get("anticipo_pct", 60)), step=5, key="cdir_anticipo_pct")
            with _ccom2:
                dias_entrega = st.number_input("Días de entrega", min_value=1, max_value=365, value=int(pre.get("dias_entrega", 10)), step=1, key="cdir_dias_entrega")
            with _ccom3:
                dias_validez = st.number_input("Validez de la oferta (días)", min_value=1, max_value=365, value=int(pre.get("dias_validez", 30)), step=5, key="cdir_dias_validez")
        r["anticipo_pct"]   = anticipo_pct
        r["dias_entrega"]   = dias_entrega
        r["dias_validez"]   = dias_validez
        r["telefono_cliente"] = pre.get("telefono_cliente", "")
        r["email_cliente"]    = pre.get("email_cliente", "")
        r["ciudad_proyecto"]  = pre.get("ciudad_proyecto", "")
        st.session_state.cotizacion = r

        # ── Matriz de Inclusiones / Exclusiones ──────────────────────────────
        st.markdown("### 📋 Alcance del Proyecto")
        with st.container(border=True):
            st.caption(
                "Marca o desmarca los ítems que se incluirán en el PDF. "
                "Los cambios son sólo para este documento; no afectan el cálculo."
            )
            _inc_col, _exc_col = st.columns(2)
            with _inc_col:
                st.markdown(
                    "<div style='font-size:0.75rem;font-weight:700;color:#1F6F54;"
                    "text-transform:uppercase;letter-spacing:0.07em;margin-bottom:6px'>"
                    "✔ Inclusiones</div>",
                    unsafe_allow_html=True,
                )
                _sel_inclusiones = [
                    item for i, item in enumerate(INCLUSIONES_BASE)
                    if st.checkbox(
                        item,
                        value=True,
                        key=f"pdf_inc_{i}",
                    )
                ]
            with _exc_col:
                st.markdown(
                    "<div style='font-size:0.75rem;font-weight:700;color:#C9A45C;"
                    "text-transform:uppercase;letter-spacing:0.07em;margin-bottom:6px'>"
                    "✗ Exclusiones</div>",
                    unsafe_allow_html=True,
                )
                _sel_exclusiones = [
                    item for i, item in enumerate(EXCLUSIONES_BASE)
                    if st.checkbox(
                        item,
                        value=True,
                        key=f"pdf_exc_{i}",
                    )
                ]

        # ── Exportar PDFs ─────────────────────────────────────────────────────
        st.markdown("### 📄 Documentos para el cliente")
        from generador_pdf import generar_pdf_cotizacion, generar_cuenta_cobro
        _num_pre = st.session_state.get("_cotiz_guardada_num") or f"COT-{_hoy().strftime('%Y')}-001"

        with st.container(border=True):
            st.markdown("**Cotización comercial**")
            _cp1, _cp2 = st.columns([1.5, 1])
            with _cp1:
                num_cot = st.text_input("Número de cotización", value=_num_pre, key="num_cot_success")
            with _cp2:
                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                if st.button("📄 Generar PDF Cotización", type="primary", use_container_width=True, key="btn_pdf_cot"):
                    with st.spinner("Generando documento corporativo..."):
                        pdf_bytes = generar_pdf_cotizacion(
                            r, numero=num_cot,
                            empresa_info=st.session_state.empresa_info,
                            logo_bytes=st.session_state.logo_bytes,
                            incluir_iva=_iva_act,
                            inclusiones=_sel_inclusiones,
                            exclusiones=_sel_exclusiones,
                        )
                    st.download_button("⬇ Descargar Cotización PDF", pdf_bytes, file_name=f"{num_cot}_Cotizacion.pdf", mime="application/pdf", use_container_width=True, key="dl_pdf_cot")

        with st.container(border=True):
            st.markdown("**Cuenta de cobro**")
            _cc1, _cc2 = st.columns(2)
            with _cc1:
                num_cc  = st.text_input("Número de cuenta", value=f"CC-{_hoy().strftime('%Y')}-001", key="num_cc_success")
                nom_pag = st.text_input("Facturar a:", value=r.get("nombre_cliente", ""), key="nom_pag_success")
            with _cc2:
                nit_pag = st.text_input("NIT / CC", value="", key="nit_pag_success")
                dir_pag = st.text_input("Dirección", value="", key="dir_pag_success")
            if st.button("📄 Generar PDF Cuenta de Cobro", type="primary", use_container_width=True, key="btn_pdf_cc"):
                datos_pag = {"nombre": nom_pag, "nit": nit_pag, "direccion": dir_pag}
                with st.spinner("Generando documento corporativo..."):
                    cc_bytes = generar_cuenta_cobro(r, st.session_state.empresa_info.copy(), datos_pag, numero=num_cc, logo_bytes=st.session_state.logo_bytes, incluir_iva=_iva_act)
                st.download_button("⬇ Descargar Cuenta de Cobro PDF", cc_bytes, file_name=f"{num_cc}_CuentaCobro.pdf", mime="application/pdf", use_container_width=True, key="dl_pdf_cc")

        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
        _col_nueva, _col_editar = st.columns(2)
        with _col_nueva:
            if st.button("🆕 Nueva cotización", use_container_width=True, type="primary", key="btn_nueva_cot_success"):
                _DATA_KEYS_NUEVA = [
                    "cotizacion", "pre", "piezas", "materiales_proyecto",
                    "_cotiz_guardada", "_cotiz_guardada_num", "_num_auto_sugerido",
                    "_borrador_restaurado", "_sp_borrador_hash", "_cantidades_add_restauradas",
                    "_cotiz_formalizada", "_cotiz_formalizada_num", "borrador_actual_id",
                ]
                for k in _DATA_KEYS_NUEVA:
                    st.session_state.pop(k, None)
                _WIDGET_PREFIXES_NUEVA = ("cdir_", "p1_", "p2_", "p3_", "p4_", "add_", "retal_", "mat_", "num_cot_", "num_cc_", "nom_pag_", "nit_pag_", "dir_pag_", "sim_slider")
                for _wk in [k for k in list(st.session_state.keys()) if any(k.startswith(pfx) for pfx in _WIDGET_PREFIXES_NUEVA)]:
                    st.session_state.pop(_wk, None)
                _sp_d = st.session_state.get("store_permanente", {})
                for _sk in [k for k in list(_sp_d.keys()) if k.startswith("cdir_")]:
                    del _sp_d[_sk]
                _sp_d["cdir_paso"] = 0
                _sp_d["cdir_piezas"] = []
                _sp_d["cdir_materiales"] = []
                st.session_state.cdir_paso    = 0
                st.session_state.cdir_success = False
                st.rerun()
        with _col_editar:
            if st.button("✏️ Editar esta cotización", use_container_width=True, type="secondary", key="btn_editar_cot_success"):
                st.session_state.cdir_success = False
                st.session_state.cdir_paso    = 0
                _sp_edit = st.session_state.get("store_permanente", {})
                _sp_edit["cdir_paso"] = 0
                st.rerun()

        st.stop()

    # ══════════════════════════════════════════════════════════════════════════
    # WIZARD — Barra de progreso + botón limpiar
    # ══════════════════════════════════════════════════════════════════════════
    paso = st.session_state.cdir_paso

    if pre and (pre.get("nombre_cliente") or pre.get("piezas") or pre.get("materiales_proyecto")):
        with st.popover("🗑️ Reiniciar cotización", use_container_width=False):
            st.markdown(
                "<div style='font-size:0.88rem;font-weight:700;color:#C9A45C;margin-bottom:6px'>"
                "⚠️ ¿Estás seguro?</div>"
                "<div style='font-size:0.80rem;line-height:1.55;opacity:0.80;margin-bottom:14px'>"
                "Se perderán <strong>todos los datos</strong> del formulario actual: "
                "materiales, dimensiones, piezas, logística y el cálculo guardado.</div>",
                unsafe_allow_html=True
            )
            if st.button("Sí, borrar todo y empezar de cero", key="btn_confirmar_limpiar", type="primary", use_container_width=True):
                _DATA_KEYS = ["pre", "piezas", "materiales_proyecto", "cotizacion", "_cotiz_guardada", "_cotiz_guardada_num", "_num_auto_sugerido", "_borrador_restaurado", "_sp_borrador_hash", "_cantidades_add_restauradas", "_cotiz_formalizada", "_cotiz_formalizada_num", "borrador_actual_id"]
                for k in _DATA_KEYS:
                    st.session_state.pop(k, None)
                _WIDGET_PREFIXES = ("cdir_", "p1_", "p2_", "p3_", "p4_", "add_", "retal_", "mat_", "num_cot_", "num_cc_", "nom_pag_", "nit_pag_", "dir_pag_", "sim_slider")
                for _wk in [k for k in list(st.session_state.keys()) if any(k.startswith(pfx) for pfx in _WIDGET_PREFIXES)]:
                    st.session_state.pop(_wk, None)
                _sp_c = st.session_state.get("store_permanente", {})
                for _sk in [k for k in list(_sp_c.keys()) if k.startswith("cdir_")]:
                    del _sp_c[_sk]
                _sp_c["cdir_paso"] = 0
                _sp_c["cdir_piezas"] = []
                _sp_c["cdir_materiales"] = []
                st.session_state.cdir_paso    = 0
                st.session_state.cdir_success = False
                st.rerun()

    # Barra de progreso visual
    _pasos_html = ""
    for _i, _p in enumerate(WIZARD_PASOS):
        if _i < paso:
            _dot_style = "background:#1F6F54;color:white;border:2px solid #1F6F54;"
            _lbl_style = "color:#1F6F54;font-weight:700;"
            _dot_char  = "&#10003;"
            _conn_bg   = "#1F6F54"
            _conn_op   = "1"
        elif _i == paso:
            _dot_style = "background:#1F6F54;color:white;border:2px solid #1F6F54;box-shadow:0 0 0 4px rgba(31,111,84,0.18);"
            _lbl_style = "color:#1F6F54;font-weight:900;"
            _dot_char  = str(_i + 1)
            _conn_bg   = "var(--border-color)"
            _conn_op   = "0.25"
        else:
            _dot_style = "background:transparent;color:var(--text-color);border:2px solid var(--border-color);opacity:0.4;"
            _lbl_style = "opacity:0.4;"
            _dot_char  = str(_i + 1)
            _conn_bg   = "var(--border-color)"
            _conn_op   = "0.25"

        _pasos_html += (
            f'<div style="display:flex;flex-direction:column;align-items:center;gap:4px;min-width:56px;">'
            f'<div style="width:32px;height:32px;border-radius:50%;display:flex;align-items:center;'
            f'justify-content:center;font-size:0.78rem;font-weight:800;{_dot_style}">{_dot_char}</div>'
            f'<div style="font-size:0.65rem;text-align:center;{_lbl_style}">{_p["label"]}</div>'
            f'</div>'
        )
        if _i < N_PASOS - 1:
            _pasos_html += (
                f'<div style="flex:1;height:2px;background:{_conn_bg};opacity:{_conn_op};'
                f'margin-bottom:14px;align-self:flex-start;margin-top:16px;"></div>'
            )

    st.markdown(
        '<div style="display:flex;align-items:flex-start;margin-bottom:24px;'
        'padding:16px 20px;background:var(--secondary-background-color);'
        'border-radius:12px;border:1px solid var(--border-color)">'
        + _pasos_html + '</div>',
        unsafe_allow_html=True
    )
    st.markdown(
        f"<h2 style='font-family:Playfair Display,serif;margin-bottom:2px'>"
        f"{WIZARD_PASOS[paso]['icono']} {WIZARD_PASOS[paso]['label']}</h2>"
        f"<p style='opacity:0.6;font-size:0.85rem;margin-bottom:20px'>Paso {paso+1} de {N_PASOS}</p>",
        unsafe_allow_html=True
    )

    # Navegación no-lineal
    st.markdown("<br>", unsafe_allow_html=True)
    _cols_nav_cdir = st.columns(len(WIZARD_PASOS))
    for _i, _p in enumerate(WIZARD_PASOS):
        with _cols_nav_cdir[_i]:
            _tipo_btn = "primary" if st.session_state.cdir_paso == _i else "secondary"
            if st.button(f"{_p['icono']} {_p['label']}", key=f"nav_cd_{_i}", type=_tipo_btn, use_container_width=True):
                st.session_state.cdir_paso = _i
                fn_sp_set("cdir_paso", _i)
                st.rerun()
    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════════
    # PASO 0 — MATERIAL(ES)
    # ══════════════════════════════════════════════════════════════════════════
    if paso == 0:
        _c_paso = st.container(border=True)
        _c_paso.__enter__()
        _seccion_titulo("¿Qué material vas a instalar?", "Puedes agregar varios materiales si el proyecto mezcla referencias")

        with st.expander("❓ ¿Cómo lleno este paso?", expanded=False):
            st.markdown("""
**Categoría:** El tipo de piedra (Mármol, Granito, Sinterizado, etc.)

**Referencia:** El nombre de la lámina que compraste.

**Precio/m²:** Lo que te cobró el proveedor por m².

**Área comprada:** Los m² totales de la lámina. Ejemplo: 1,20 m × 2,60 m = **3,12 m²**.
            """)

        if "materiales_proyecto" not in st.session_state or not st.session_state.materiales_proyecto:
            st.session_state.materiales_proyecto = pre.get("materiales_proyecto", [
                {"cat": pre.get("categoria", "Mármol"), "ref": pre.get("referencia", ""),
                 "precio_m2": pre.get("precio_m2", 220_000), "area_placa": pre.get("area_placa_comprada", 5.94)}
            ])

        mats        = st.session_state.materiales_proyecto
        mats_nuevos = []

        for midx, mat_item in enumerate(mats):
            with st.container(border=True):
                lbl = f"Material {midx + 1}" if len(mats) > 1 else "Material del proyecto"
                if len(mats) > 1:
                    st.markdown(f"<div style='font-size:0.78rem;font-weight:700;opacity:0.55;margin-bottom:8px'>{lbl}</div>", unsafe_allow_html=True)

                cola, colb = st.columns(2)
                with cola:
                    cats_opts = CATEGORIAS_MATERIAL
                    cat_i     = cats_opts.index(mat_item.get("cat","Mármol")) if mat_item.get("cat") in cats_opts else 0
                    cat_sel_m = st.selectbox("Categoría de material", cats_opts, index=cat_i, key=f"mcat_{midx}")
                    _bc = BADGE_COLORS.get(cat_sel_m, ("#f0f0f0","#333"))
                    st.markdown(
                        f'<div style="background:{_bc[0]};color:{_bc[1]};border-radius:6px;'
                        f'padding:6px 12px;font-size:0.78rem;font-weight:700;display:inline-block">'
                        f'{DESCRIPCIONES_CATEGORIA.get(cat_sel_m,"")}</div>',
                        unsafe_allow_html=True
                    )

                with colb:
                    _refs_cat = MATERIALES_CATALOGO.get(cat_sel_m, [])
                    refs_m    = _refs_cat + ["Otra referencia..."]
                    pre_ref_m = mat_item.get("ref", "")
                    idx_ref_m = refs_m.index(pre_ref_m) if pre_ref_m in refs_m else len(refs_m) - 1
                    ref_sel_m = st.selectbox("Referencia del material", refs_m, index=idx_ref_m, key=f"mref_{midx}")
                    if ref_sel_m == "Otra referencia...":
                        referencia_m = st.text_input("Nombre de la referencia", key=f"mrefcust_{midx}", value=pre_ref_m if pre_ref_m not in refs_m else "", placeholder="Ej: Calacatta Gold")
                    else:
                        referencia_m = ref_sel_m

                _cs_data = CROSS_SELLING_MAP.get(referencia_m)
                if _cs_data:
                    st.info(f"📈 **Oportunidad de Margen:** El **{_cs_data['alternativa']}** ({_cs_data['categoria']}) ofrece una estética similar pero deja mayor utilidad neta. *{_cs_data['razon']}*")

                colc, cold = st.columns(2)
                with colc:
                    precio_m2_m = st.number_input(
                        "Precio por m² (COP)", min_value=10_000, max_value=5_000_000,
                        value=int(mat_item.get("precio_m2") or 220_000), step=1_000, key=f"mpm2_{midx}",
                    )
                    st.markdown(f"<div style='margin-top:-12px;margin-bottom:10px;font-size:0.85rem;color:#1F6F54;font-weight:600;'>💰 Equivalencia: {cop(precio_m2_m)}</div>", unsafe_allow_html=True)
                with cold:
                    _area_leg   = float(mat_item.get("area_placa") or 5.94)
                    _cant_prev  = int(mat_item.get("placas_cant") or 1)
                    _largo_prev = float(mat_item.get("placas_largo") or round(_area_leg / 0.60, 2))
                    _ancho_prev = float(mat_item.get("placas_ancho") or 0.60)
                    st.markdown("<div style='font-size:0.8rem;font-weight:600;opacity:0.7;margin-bottom:4px'>Dimensiones de la lámina</div>", unsafe_allow_html=True)
                    _pcol1, _pcol2, _pcol3 = st.columns(3)
                    with _pcol1:
                        _cant_placas = st.number_input("Cant. placas", min_value=1, max_value=50, value=_cant_prev, step=1, key=f"mpcant_{midx}")
                    with _pcol2:
                        _largo_placa = st.number_input("Largo (m)", min_value=0.10, max_value=10.0, value=_largo_prev, step=0.01, key=f"mplargo_{midx}", format="%.2f")
                    with _pcol3:
                        _ancho_placa = st.number_input("Ancho (m)", min_value=0.10, max_value=5.0, value=_ancho_prev, step=0.01, key=f"mpancho_{midx}", format="%.2f")
                    area_placa_m = round(_cant_placas * _largo_placa * _ancho_placa, 4)
                    st.caption(f"Área total calculada: {area_placa_m:.2f} m²")

                costo_m = precio_m2_m * area_placa_m
                st.markdown(
                    f'<div style="background:var(--secondary-background-color);border-radius:8px;'
                    f'padding:8px 14px;margin-top:4px;font-size:0.85rem">'
                    f'<span style="opacity:0.6">{_numero_completo(precio_m2_m)}/m² × {area_placa_m:.3f} m² = </span>'
                    f'<strong style="color:#1F6F54">{_numero_completo(costo_m)}</strong></div>',
                    unsafe_allow_html=True
                )

                _mat_dict = {
                    "cat": cat_sel_m, "ref": referencia_m,
                    "precio_m2": precio_m2_m, "area_placa": area_placa_m,
                    "placas_cant": _cant_placas, "placas_largo": _largo_placa, "placas_ancho": _ancho_placa,
                }

                # Banco de Retales
                try:
                    _usr_act      = st.session_state.get("usuario_actual", {})
                    _retales_disp = fn_consultar_retal(cat_sel_m, referencia_m, usuario_id=_usr_act.get("id"), rol=_usr_act.get("rol","Admin"))
                except Exception:
                    _retales_disp = []

                if _retales_disp:
                    _m2_total_retal = sum(r[2] for r in _retales_disp)
                    _retal_key      = f"usar_retal_{midx}"
                    _retal_sel_key  = f"retal_seleccionando_{midx}"
                    _usando_retal   = st.session_state.get(_retal_key, False)
                    _seleccionando  = st.session_state.get(_retal_sel_key, False)

                    if not _usando_retal and not _seleccionando:
                        _num_piezas = len(_retales_disp)
                        _orig_txt   = _retales_disp[0][3] if _num_piezas == 1 else f"{_num_piezas} sobrantes disponibles"
                        st.markdown(
                            f'<div style="border:1px solid #1F6F54;border-left:4px solid #1F6F54;'
                            f'border-radius:8px;padding:10px 16px;margin:8px 0;background:rgba(31,111,84,0.06);">'
                            f'<div style="font-size:0.8rem;font-weight:700;color:#1F6F54;margin-bottom:4px">'
                            f'♻️ Tienes {_fmt_m2(_m2_total_retal, 2)} de sobrante de este material</div>'
                            f'<div style="font-size:0.75rem;opacity:0.65">Origen: {_orig_txt}</div></div>',
                            unsafe_allow_html=True
                        )
                        _col_rb, _ = st.columns([1.6, 2.4])
                        with _col_rb:
                            if st.button("Usar sobrante →", key=f"btn_retal_{midx}", type="primary", use_container_width=True):
                                st.session_state[_retal_sel_key] = True
                                st.rerun()

                    elif _seleccionando:
                        st.markdown(
                            '<div style="border:1px solid #C9A45C;border-left:4px solid #C9A45C;'
                            'border-radius:8px;padding:10px 16px;margin:8px 0;background:rgba(201,168,76,0.07);">'
                            '<div style="font-size:0.78rem;font-weight:700;color:#C9A45C;margin-bottom:6px">'
                            '🗂️ Selecciona el sobrante que quieres usar</div></div>',
                            unsafe_allow_html=True
                        )
                        _opciones_retal = []
                        _mapa_retal     = {}
                        for _r in _retales_disp:
                            _rid   = _r[0]; _rref = _r[1] or "Sin referencia"
                            _rm2   = _r[2]; _rnum = _r[3] or "—"
                            _rfech = str(_r[5])[:10] if len(_r) > 5 and _r[5] else ""
                            _lbl   = f"{_fmt_m2(_rm2, 3)} · {_rref} · Cot. {_rnum}"
                            if _rfech:
                                _lbl += f" · {_rfech}"
                            _opciones_retal.append(_lbl)
                            _mapa_retal[_lbl] = {"id": _rid, "m2": _rm2}
                        _sel_lbl   = st.radio("Sobrantes disponibles", options=_opciones_retal, key=f"retal_radio_{midx}", label_visibility="collapsed")
                        _rsel_data = _mapa_retal.get(_sel_lbl, {})
                        _cbtn_c1, _cbtn_c2 = st.columns(2)
                        with _cbtn_c1:
                            if st.button("✓ Usar este sobrante", key=f"btn_confirmar_retal_{midx}", type="primary", use_container_width=True):
                                st.session_state[_retal_key]         = True
                                st.session_state[f"retal_id_{midx}"] = _rsel_data["id"]
                                st.session_state[f"retal_m2_{midx}"] = _rsel_data["m2"]
                                st.session_state.pop(_retal_sel_key, None)
                                st.rerun()
                        with _cbtn_c2:
                            if st.button("✕ Cancelar", key=f"btn_cancel_sel_{midx}", use_container_width=True):
                                st.session_state.pop(_retal_sel_key, None)
                                st.rerun()

                    else:
                        # Sobrante activo — leer precio_recuperacion desde BD
                        _rid_activo = st.session_state.get(f"retal_id_{midx}")
                        _rm2_activo = st.session_state.get(f"retal_m2_{midx}", _m2_total_retal)
                        _precio_rec = 0.0
                        try:
                            import psycopg2
                            # Reutilizamos la conexión a través de una función inyectada implícita;
                            # si el contexto lo provee, perfecto. Si no, _precio_rec = 0.
                            pass
                        except Exception:
                            pass
                        _mat_dict["precio_m2"]  = _precio_rec
                        _mat_dict["area_placa"] = _rm2_activo
                        _mat_dict["es_retal"]   = True
                        _mat_dict["retal_id"]   = _rid_activo
                        _prec_txt = f"Precio/m²: {_numero_completo(_precio_rec)}" if _precio_rec > 0 else "Precio fijado en $0"
                        st.markdown(
                            f'<div style="border:1px solid #1F6F54;border-left:4px solid #1F6F54;border-radius:8px;'
                            f'padding:10px 16px;margin:8px 0;background:rgba(31,111,84,0.06);">'
                            f'<div style="font-size:0.8rem;font-weight:700;color:#1F6F54;margin-bottom:3px">'
                            f'♻️ Sobrante activo — {_prec_txt} · Área: {_fmt_m2(_rm2_activo,3)}</div>'
                            f'<div style="font-size:0.75rem;opacity:0.65">El margen subirá al 80-90%+</div></div>',
                            unsafe_allow_html=True
                        )
                        if st.button("Cancelar sobrante", key=f"btn_cancel_retal_{midx}"):
                            st.session_state.pop(_retal_key, None)
                            st.session_state.pop(_retal_sel_key, None)
                            st.session_state.pop(f"retal_id_{midx}", None)
                            st.session_state.pop(f"retal_m2_{midx}", None)
                            st.rerun()

                if len(mats) > 1:
                    if st.button("🗑️ Quitar este material", key=f"mdel_{midx}"):
                        fn_sp_eliminar_material(midx)
                        st.rerun()

                mats_nuevos.append(_mat_dict)

        fn_sp_sync_materiales(mats_nuevos)
        st.session_state.materiales_proyecto = mats_nuevos

        if st.button("＋ Agregar otro material", use_container_width=True):
            fn_sp_agregar_material()
            st.rerun()

        cat_sel            = mats_nuevos[0]["cat"]    if mats_nuevos else "Mármol"
        _refs_raw          = [m["ref"] or m["cat"] for m in mats_nuevos]
        _refs_unicas       = list(dict.fromkeys(_refs_raw))
        referencia         = " + ".join(_refs_unicas) if len(_refs_unicas) > 1 else (_refs_unicas[0] if _refs_unicas else "")
        precio_m2          = mats_nuevos[0]["precio_m2"] if mats_nuevos else 220_000
        area_placa         = sum(m["area_placa"] for m in mats_nuevos)
        _area_total_mats   = sum(m["area_placa"] for m in mats_nuevos) or 1.0
        precio_m2_efectivo = (sum(m["precio_m2"] * m["area_placa"] for m in mats_nuevos) / _area_total_mats if mats_nuevos else 220_000)

        _c_paso.__exit__(None, None, None)

    # ══════════════════════════════════════════════════════════════════════════
    # PASO 1 — DIMENSIONES
    # ══════════════════════════════════════════════════════════════════════════
    elif paso == 1:
        _c_paso = st.container(border=True)
        _c_paso.__enter__()
        _mats_p1   = st.session_state.get("materiales_proyecto", [])
        cat_sel    = _mats_p1[0]["cat"] if _mats_p1 else pre.get("categoria","Mármol")
        area_placa = sum(m["area_placa"] for m in _mats_p1) if _mats_p1 else pre.get("area_placa_comprada", 5.94)

        _seccion_titulo("¿Cuántas piezas tiene el proyecto?", "Cada tramo o elemento de piedra es una pieza.")

        with st.expander("❓ ¿Qué es un metro lineal (ML)?", expanded=False):
            st.markdown("""
**ML = la longitud** de la pieza. La app calcula los m² sola.

| Pieza | Largo que ingresas | Ancho estándar | m² resultado |
|---|---|---|---|
| Mesón de 3 m | **3 ML** | 0,60 m | 1,80 m² |
| Baño de 1,2 m | **1,2 ML** | 0,45 m | 0,54 m² |

Si el ancho es diferente, elige **Personalizado** y ajusta.
            """)

        st.markdown("---")
        with st.expander("✨ Asistente Mágico: Pegar texto del cliente (WhatsApp/Audio)", expanded=False):
            st.caption("Pega el mensaje de tu cliente. La IA extraerá las piezas y las medidas automáticamente.")
            _texto_magico = st.text_area(
                "Mensaje del cliente:", height=100,
                placeholder="Ej: Cotízame un mesón en granito de 2.50 x 0.60 y una isla de 1.80 x 0.90...",
                key="asistente_magico_texto",
            )
            if st.button("🪄 Traducir y Autocompletar Piezas", type="primary", key="asistente_magico_btn"):
                if _texto_magico.strip():
                    with st.spinner("🧠 Analizando dimensiones y materiales..."):
                        try:
                            from asistente_ia import extraer_coordenadas_plano as _trad_ia
                            _resultado_trad = _trad_ia(_texto_magico)
                            _piezas_ia = _resultado_trad.get("piezas", []) if _resultado_trad else []
                            _piezas_actuales = list(fn_sp().get("cdir_piezas", []))
                            if len(_piezas_actuales) <= 1:
                                _piezas_actuales = []
                            for _idx_ia, p_ia in enumerate(_piezas_ia):
                                _ancho_ia = float(p_ia.get("ancho", 0.60))
                                _tipo_ia  = "Personalizado"
                                for _tnombre, _tdata in ANCHOS_ESTANDAR.items():
                                    if _tdata["ancho"] is not None and abs(_tdata["ancho"] - _ancho_ia) < 0.005:
                                        _tipo_ia = _tnombre
                                        break
                                _piezas_actuales.append({
                                    "nombre": str(p_ia.get("nombre", f"Pieza {_idx_ia+1}")),
                                    "ml": float(p_ia.get("largo", 1.0)),
                                    "ml_unitario": float(p_ia.get("largo", 1.0)),
                                    "cantidad": int(p_ia.get("cantidad", 1)),
                                    "ancho_tipo": _tipo_ia,
                                    "ancho_custom": _ancho_ia,
                                    "zoc_trasero": bool(p_ia.get("zoc_trasero", False)),
                                    "zoc_izq": bool(p_ia.get("zoc_izq", False)),
                                    "zoc_der": bool(p_ia.get("zoc_der", False)),
                                    "altura_zocalo_cm": float(p_ia.get("altura_zocalo_cm", 7.0)),
                                })
                            fn_sp_set("cdir_piezas", _piezas_actuales)
                            st.session_state.piezas = _piezas_actuales
                            fn_sp_commit_borrador()
                            st.success(f"¡Se extrajeron {len(_piezas_ia)} piezas con éxito!")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"No pude procesar el texto. (Error: {e})")
                else:
                    st.warning("Escribe o pega un mensaje primero.")
        st.markdown("---")

        if "piezas" not in st.session_state:
            st.session_state.piezas = pre.get("piezas", [{"nombre": "Mesón de cocina", "ml": 2.0, "ancho_tipo": "Mesón de cocina", "ancho_custom": 0.60}])

        tipos_superficie = list(ANCHOS_ESTANDAR.keys())
        piezas_nuevas    = []
        total_m2_piezas  = 0.0

        if not st.session_state.piezas:
            st.markdown(
                '<div style="background:rgba(31,111,84,0.04);border:2px dashed rgba(31,111,84,0.3);'
                'border-radius:12px;padding:40px 20px;text-align:center;margin-bottom:16px">'
                '<div style="font-size:2.8rem;margin-bottom:12px">📭</div>'
                '<div style="font-size:1.15rem;font-weight:800;color:#1F6F54;margin-bottom:6px">No hay piezas en tu cotización</div>'
                '<div style="font-size:0.85rem;opacity:0.75;max-width:400px;margin:0 auto;">'
                'Usa el <strong>✨ Asistente Mágico</strong> de arriba o agrega una pieza manualmente.'
                '</div></div>', unsafe_allow_html=True
            )
        else:
            for idx, pieza in enumerate(st.session_state.piezas):
                with st.container(border=True):
                    _col_nom, _col_del = st.columns([5, 1])
                    with _col_nom:
                        nombre_p = st.text_input("Descripción de la pieza", value=pieza.get("nombre",""), key=f"pnom_{idx}", placeholder=f"Pieza {idx+1}")
                    with _col_del:
                        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                        if st.button("🗑️", key=f"del_{idx}", help="Eliminar pieza", use_container_width=True):
                            fn_sp_eliminar_pieza(idx)
                            st.rerun()

                    _col_tipo, _col_ml, _col_cant = st.columns([2, 1.5, 1])
                    with _col_tipo:
                        tipo_idx     = tipos_superficie.index(pieza.get("ancho_tipo", tipos_superficie[0])) if pieza.get("ancho_tipo") in tipos_superficie else 0
                        ancho_tipo_p = st.selectbox("Tipo de elemento", tipos_superficie, index=tipo_idx, key=f"ptip_{idx}", help=ANCHOS_ESTANDAR.get(pieza.get("ancho_tipo", tipos_superficie[0]), {}).get("desc", ""))
                    with _col_ml:
                        ml_p = st.number_input("Largo (ML)", value=float(pieza.get("ml") or 1.0), min_value=0.01, step=0.1, key=f"pml_{idx}")
                    with _col_cant:
                        cantidad_p = st.number_input("Cantidad", value=int(pieza.get("cantidad") or 1), min_value=1, max_value=100, step=1, key=f"pcant_{idx}")

                    if ancho_tipo_p == "Personalizado":
                        st.text_input("Nombre personalizado (aparece en el PDF)", value=st.session_state.get(f"pcustom_{idx}", pieza.get("nombre_personalizado","")), key=f"pcustom_{idx}", placeholder='Ej: "Mesón de lavamanos"')

                    _col_ancho, _col_m2 = st.columns(2)
                    with _col_ancho:
                        ancho_def = ANCHOS_ESTANDAR[ancho_tipo_p]["ancho"] or pieza.get("ancho_custom") or 0.60
                        ancho_p   = st.number_input("Ancho (m)", value=float(ancho_def or 0.60), min_value=0.01, step=0.01, key=f"panc_{idx}")

                    _auditor_largo = ml_p > 3.5
                    _auditor_ancho = ancho_p > 2.2
                    if _auditor_largo:
                        st.warning(f"⚠️ **Medida inusual:** {ml_p:.2f} metros de largo. Si eran centímetros, usa el formato decimal: **0.{int(ml_p*100):02d}** m", icon="📏")
                    if _auditor_ancho:
                        st.warning(f"⚠️ **Medida inusual:** {ancho_p:.2f} metros de ancho. Si eran centímetros, usa el formato decimal.", icon="📏")

                    ml_efectivo     = ml_p * cantidad_p
                    m2_p            = ml_a_m2(ml_efectivo, ancho_p)
                    total_m2_piezas += m2_p
                    with _col_m2:
                        _m2_desc = f"{ml_p:.2f} ml × {ancho_p:.2f} m × {cantidad_p}" if cantidad_p > 1 else f"{ml_p:.2f} ml × {ancho_p:.2f} m"
                        st.markdown(
                            f"""<div style="background:rgba(31,111,84,0.08);border:1px solid rgba(31,111,84,0.22);
                            border-radius:10px;padding:10px 14px;margin-top:4px">
                            <div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;
                                 letter-spacing:0.1em;color:#1F6F54;opacity:0.8">m² calculados</div>
                            <div style="font-size:1.45rem;font-weight:900;color:#1F6F54;
                                 font-family:'Playfair Display',serif;line-height:1.2">{_fmt_m2(m2_p)}</div>
                            <div style="font-size:0.7rem;opacity:0.6;margin-top:2px">{_m2_desc}</div>
                            </div>""",
                            unsafe_allow_html=True,
                        )

                    # Asignación de Pieza a Lote Físico de Placa
                    _mats_paso1 = st.session_state.get("materiales_proyecto", [])
                    if _mats_paso1:
                        def _fmt_lote(i, _mats=_mats_paso1):
                            _m    = _mats[i]
                            _ll   = float(_m.get("placas_largo") or _m.get("largo") or 0.0)
                            _la   = float(_m.get("placas_ancho") or _m.get("ancho") or 0.0)
                            _lc   = int(_m.get("placas_cant") or 1)
                            _area = float(_m.get("area_placa") or (_ll * _la * _lc))
                            _ref  = _m.get("ref") or _m.get("cat", "")
                            _cat  = _m.get("cat", "")
                            _dims = f"{_ll:.2f}m × {_la:.2f}m" if _ll > 0 and _la > 0 else "sin dimensiones"
                            _sfx  = f" ×{_lc}" if _lc > 1 else ""
                            return f"[Lote #{i+1}] {_cat} — {_ref}{_sfx} ({_dims}) | {_area:.2f} m²"
                        _lote_val     = pieza.get("id_lote_origen")
                        _lote_prev    = int(_lote_val) if _lote_val is not None and _lote_val != "" else 0
                        _lote_idx_def = _lote_prev if _lote_prev < len(_mats_paso1) else 0
                        _sel_lote_idx = st.selectbox("🪨 Asignar a la placa (Lote físico)", list(range(len(_mats_paso1))), index=_lote_idx_def, format_func=_fmt_lote, key=f"pmat_{idx}")
                        _mat_sel      = _mats_paso1[_sel_lote_idx]
                        _cat_pieza    = _mat_sel.get("cat", "Mármol")
                    else:
                        _sel_lote_idx = None
                        _cat_pieza = st.selectbox("🪨 Material de la pieza", CATEGORIAS_MATERIAL, index=CATEGORIAS_MATERIAL.index(pieza.get("categoria", CATEGORIAS_MATERIAL[0])) if pieza.get("categoria") in CATEGORIAS_MATERIAL else 0, key=f"pmat_{idx}")

                    # Zócalo Geométrico por pieza
                    with st.expander("📐 Zócalos para esta pieza", expanded=False):
                        st.caption(f"Selecciona los lados de **'{nombre_p or f'Pieza {idx+1}'}'** que llevan zócalo.")
                        _zoc_c1, _zoc_c2, _zoc_c3 = st.columns(3)
                        with _zoc_c1:
                            _zoc_t = st.checkbox(f"Trasero ({ml_p:.2f} m)", value=bool(pieza.get("zoc_trasero",False)), key=f"zoc_t_{idx}")
                        with _zoc_c2:
                            _zoc_i = st.checkbox(f"Lateral Izq. ({ancho_p:.2f} m)", value=bool(pieza.get("zoc_izq",False)), key=f"zoc_i_{idx}")
                        with _zoc_c3:
                            _zoc_d = st.checkbox(f"Lateral Der. ({ancho_p:.2f} m)", value=bool(pieza.get("zoc_der",False)), key=f"zoc_d_{idx}")
                        _hay_zocalo = _zoc_t or _zoc_i or _zoc_d
                        if _hay_zocalo:
                            _altura_pre = float(pieza.get("altura_zocalo_cm") or 7.0)
                            _altura_zoc = st.number_input("Altura del zócalo (cm)", min_value=1.0, max_value=50.0, value=_altura_pre, step=0.5, key=f"zoc_h_{idx}")
                        else:
                            _altura_zoc = float(pieza.get("altura_zocalo_cm") or 7.0)
                        _ml_zoc_pieza = (
                            (ml_p * cantidad_p if _zoc_t else 0.0) +
                            (ancho_p * cantidad_p if _zoc_i else 0.0) +
                            (ancho_p * cantidad_p if _zoc_d else 0.0)
                        )
                        if _ml_zoc_pieza > 0:
                            _m2_zoc_pieza = _ml_zoc_pieza * (_altura_zoc / 100.0)
                            st.caption(f"↳ Zócalo: **{_ml_zoc_pieza:.2f} ml** · **{_m2_zoc_pieza:.4f} m²** de material (altura {_altura_zoc:.1f} cm)")

                    _nom_personalizado = st.session_state.get(f"pcustom_{idx}", pieza.get("nombre_personalizado",""))
                    piezas_nuevas.append({
                        "nombre": nombre_p, "ml": ml_efectivo, "ml_unitario": ml_p,
                        "cantidad": cantidad_p, "ancho_tipo": ancho_tipo_p, "ancho_custom": ancho_p,
                        "nombre_personalizado": _nom_personalizado,
                        "categoria": _cat_pieza, "id_lote_origen": _sel_lote_idx,
                        "zoc_trasero": _zoc_t, "zoc_izq": _zoc_i, "zoc_der": _zoc_d,
                        "altura_zocalo_cm": _altura_zoc,
                    })

        fn_sp_sync_piezas(piezas_nuevas)
        st.session_state.piezas = piezas_nuevas

        # ZOC-FIX: sumar m² de zócalos al total
        _m2_piezas_base   = sum(ml_a_m2(float(p.get("ml",0)), float(p.get("ancho_custom",0.60))) for p in st.session_state.piezas)
        _m2_zocalos_total = calcular_zocalo_geometrico(st.session_state.piezas)["m2"]
        total_m2_piezas   = _m2_piezas_base + _m2_zocalos_total
        m2_real           = total_m2_piezas
        m2_cortados_total = total_m2_piezas

        _col_add, _col_tot = st.columns([1, 2])
        with _col_add:
            if st.button("＋ Agregar pieza", use_container_width=True):
                fn_sp_agregar_pieza()
                st.rerun()
        with _col_tot:
            if m2_real > 0:
                _ml_total    = sum(p.get("ml",0) for p in st.session_state.piezas)
                _zoc_geo_p1  = calcular_zocalo_geometrico(piezas_nuevas)
                _ml_zoc_total = _zoc_geo_p1["ml"]
                html_dim = (
                    f'<div style="background:var(--secondary-background-color);border:1px solid var(--border-color);border-radius:10px;padding:12px 18px;text-align:center">'
                    f'<div style="font-size:0.7rem;color:#1F6F54;text-transform:uppercase;letter-spacing:0.08em;font-weight:700">Total</div>'
                    f'<div style="font-size:2rem;font-weight:900;font-family:\'Playfair Display\',serif">{_fmt_ml(_ml_total)}</div>'
                    f'<div style="font-size:0.85rem;opacity:0.7">{_fmt_m2(m2_real)} de material</div>'
                )
                if _ml_zoc_total > 0:
                    _zoc_m2_p1 = _zoc_geo_p1["m2"]
                    _zoc_m2_txt = f" · {_zoc_m2_p1:.3f} m²" if _zoc_m2_p1 > 0 else ""
                    html_dim += f'<div style="font-size:0.75rem;margin-top:4px;opacity:0.75;border-top:1px solid rgba(31,111,84,0.15);padding-top:4px">📐 Zócalo: <strong>{_ml_zoc_total:.2f} ml</strong><span style="opacity:0.7">{_zoc_m2_txt} de piedra</span></div>'
                html_dim += "</div>"
                st.markdown(html_dim, unsafe_allow_html=True)

        # Monitor Retal en Vivo por Lote
        _mats_rv  = st.session_state.get("materiales_proyecto", [])
        _piezas_rv = piezas_nuevas
        if _mats_rv:
            st.markdown("<p style='font-size:0.72rem;font-weight:700;color:#1F6F54;text-transform:uppercase;letter-spacing:0.08em;margin:10px 0 4px 0'>🪨 Estado de consumo por lote</p>", unsafe_allow_html=True)
            for _li, _lm in enumerate(_mats_rv):
                _ll = float(_lm.get("placas_largo") or _lm.get("largo") or 0.0)
                _la = float(_lm.get("placas_ancho") or _lm.get("ancho") or 0.0)
                _lc = int(_lm.get("placas_cant") or 1)
                _area_lote = _ll * _la * _lc if _ll > 0 and _la > 0 else float(_lm.get("area_placa",0.0))
                _piezas_lote = [p for p in _piezas_rv if p.get("id_lote_origen") == _li]
                _consumido_base = sum(float(p.get("ml", 0)) * float(p.get("ancho_custom",0.60)) for p in _piezas_lote)
                _consumido_zoc  = calcular_zocalo_geometrico(_piezas_lote)["m2"]
                _consumido      = _consumido_base + _consumido_zoc
                _retal_lote     = _area_lote - _consumido
                _overflow       = _consumido > _area_lote and _area_lote > 0
                _lote_ref = _lm.get("ref") or _lm.get("cat", f"Lote {_li+1}")
                _lote_cat = _lm.get("cat","")
                _dims_txt = f"{_ll:.2f}×{_la:.2f}m" if _ll > 0 and _la > 0 else ""
                _lote_lbl = f"[Lote #{_li+1}] {_lote_cat} — {_lote_ref}"
                if _dims_txt:
                    _lote_lbl += f" ({_dims_txt})"
                _pct = min(1.0, _consumido / _area_lote) if _area_lote > 0 else 0.0
                if _overflow:
                    st.error(f"🔴 **{_lote_lbl}** · Área: **{_area_lote:.2f} m²** · Consumido: **{_consumido:.2f} m²** · ⚠️ Déficit: **{abs(_retal_lote):.2f} m²**")
                else:
                    st.markdown(f"<div style='font-size:0.78rem;margin-bottom:2px'><strong>{_lote_lbl}</strong> <span style='opacity:0.65'>Comprado: {_area_lote:.2f} m² · Usado: {_consumido:.2f} m² · <span style='color:#1F6F54;font-weight:700'>Retal: {max(0.0,_retal_lote):.2f} m²</span></span></div>", unsafe_allow_html=True)
                    st.progress(_pct)

        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

        # Margen y m² usados
        st.markdown("**Margen de ganancia y uso del material**")
        _cm1, _cm2, _cm3 = st.columns([1.5, 1.5, 1])
        with _cm1:
            _margen_opciones = ["20%","30%","35%","40%","45%","50%","Otro"]
            _margen_pre      = int(pre.get("margen_pct", 40))
            _margen_pre_str  = f"{_margen_pre}%" if f"{_margen_pre}%" in _margen_opciones else "Otro"
            _margen_sel      = st.pills("Margen rápido", _margen_opciones, default=_margen_pre_str, key="p1_margen_pills")
            if _margen_sel == "Otro" or _margen_sel is None:
                margen_pct = st.number_input("Margen personalizado (%)", min_value=5, max_value=80, value=_margen_pre, step=1, key="p1_margen_custom")
            else:
                margen_pct = int(_margen_sel.replace("%",""))
        with _cm2:
            _m2_real_prev = st.session_state.get("_cdir_m2_real_prev", None)
            if _m2_real_prev is None or abs(_m2_real_prev - m2_real) > 0.001:
                st.session_state["cdir_m2_usados"] = round(m2_real, 3)
                st.session_state["_cdir_m2_real_prev"] = m2_real
            m2_usados = st.number_input("m² finalmente instalados", min_value=0.0, value=float(pre.get("m2_usados", m2_real)), step=0.05, key="cdir_m2_usados")
        with _cm3:
            if area_placa > 0 and m2_usados > 0:
                aprv   = min(100, m2_usados / area_placa * 100)
                retal_ = max(0, area_placa - m2_usados)
                estado_a = "bueno" if aprv >= 80 else "acepta" if aprv >= 50 else "bajo"
                _alerta(f"Uso del material: **{aprv:.1f}%**  Sobra: {_fmt_m2(retal_)}", estado_a)

        st.session_state.pre = {**pre, "margen_pct": margen_pct, "m2_usados": m2_usados, "piezas": st.session_state.piezas}
        fn_sp_set("cdir_margen_pct", margen_pct)
        fn_sp_set("cdir_m2_usados", m2_usados)
        _c_paso.__exit__(None, None, None)

    # ══════════════════════════════════════════════════════════════════════════
    # PASO 2 — PROYECTO
    # ══════════════════════════════════════════════════════════════════════════
    elif paso == 2:
        _c_paso = st.container(border=True)
        _c_paso.__enter__()
        _mats_p2   = st.session_state.get("materiales_proyecto", [])
        cat_sel    = _mats_p2[0]["cat"] if _mats_p2 else pre.get("categoria","Mármol")
        area_placa = sum(m["area_placa"] for m in _mats_p2) if _mats_p2 else pre.get("area_placa_comprada", 5.94)
        _piezas_p2 = st.session_state.get("piezas", pre.get("piezas",[]))
        m2_real    = sum(ml_a_m2(float(p.get("ml",0)), float(p.get("ancho_custom",0.60))) for p in _piezas_p2) or pre.get("m2_proyecto", 4.0)

        _seccion_titulo("Datos del proyecto", "Tipo de obra, cuántos días y quiénes van")

        c1, c2 = st.columns(2)
        with c1:
            tipo_opts = ["Mesón","Cocina","Baño","Piso","Escalera","Fachada","Mueble de cocina","Otro"]
            _sp_tipos = fn_sp().get("cdir_tipos_proyecto", pre.get("tipos_proyecto", [pre.get("tipo_proyecto","Mesón")] if pre.get("tipo_proyecto") else ["Mesón"]))
            tipos_sel = st.multiselect("Tipo(s) de proyecto", tipo_opts, default=[t for t in _sp_tipos if t in tipo_opts] or ["Mesón"], key="cb_cdir_tipos_proyecto", on_change=fn_cb_cdir_tipos_proyecto)
            tipo = " + ".join(tipos_sel) if tipos_sel else "Otro"
        with c2:
            _sp_etapa_label = fn_sp().get("cdir_etapa_label", pre.get("etapa_label", list(ETAPAS_OBRA.keys())[0]))
            etapa = ETAPAS_OBRA[st.selectbox("Etapa de la obra", list(ETAPAS_OBRA.keys()), index=list(ETAPAS_OBRA.keys()).index(_sp_etapa_label) if _sp_etapa_label in ETAPAS_OBRA else 0, key="cb_cdir_etapa", on_change=fn_cb_cdir_etapa)]

        nombre_cliente = st.text_input("Nombre del cliente", value=fn_sp().get("cdir_nombre_cliente", pre.get("nombre_cliente","")), placeholder="Ej: Juan García / Constructora XYZ", key="cb_cdir_nombre_cliente", on_change=fn_cb_cdir_nombre_cliente)

        _cont1, _cont2, _cont3 = st.columns(3)
        with _cont1:
            telefono_cliente = st.text_input("Teléfono", value=fn_sp().get("cdir_telefono_cliente", pre.get("telefono_cliente", "")), placeholder="Ej: 300 123 4567", key="cb_cdir_telefono_cliente")
            st.session_state.pre["telefono_cliente"] = telefono_cliente
            fn_sp_set("cdir_telefono_cliente", telefono_cliente)
        with _cont2:
            email_cliente = st.text_input("Correo electrónico", value=fn_sp().get("cdir_email_cliente", pre.get("email_cliente", "")), placeholder="cliente@email.com", key="cb_cdir_email_cliente")
            st.session_state.pre["email_cliente"] = email_cliente
            fn_sp_set("cdir_email_cliente", email_cliente)
        with _cont3:
            ciudad_proyecto = st.text_input("Ciudad del proyecto", value=fn_sp().get("cdir_ciudad_proyecto", pre.get("ciudad_proyecto", "")), placeholder="Ej: Barranquilla", key="cb_cdir_ciudad_proyecto")
            st.session_state.pre["ciudad_proyecto"] = ciudad_proyecto
            fn_sp_set("cdir_ciudad_proyecto", ciudad_proyecto)

        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
        st.markdown("**¿Cuántos días dura la instalación y cuántas personas van?**")
        _dc1, _dc2 = st.columns(2)
        with _dc1:
            _dias_opts  = ["1","2","3","4","5","6+"]
            _dias_pre   = int(pre.get("dias_obra", 2))
            _dias_pre_s = str(_dias_pre) if str(_dias_pre) in _dias_opts else ("6+" if _dias_pre > 5 else _dias_opts[0])
            _dias_sel   = st.pills("Días en obra", _dias_opts, default=_dias_pre_s, key="p2_dias_pills")
            _dias_sel   = _dias_sel if _dias_sel else _dias_pre_s
            dias = st.number_input("Días (exacto)", min_value=1, value=_dias_pre, step=1, key="p2_dias_custom") if _dias_sel == "6+" else int(_dias_sel)
        with _dc2:
            _pers_opts  = ["1","2","3","4","5+"]
            _pers_pre   = int(pre.get("personas", 2))
            _pers_pre_s = str(_pers_pre) if str(_pers_pre) in _pers_opts else ("5+" if _pers_pre > 4 else _pers_opts[0])
            _pers_sel   = st.pills("Personas en obra", _pers_opts, default=_pers_pre_s, key="p2_pers_pills")
            _pers_sel   = _pers_sel if _pers_sel else _pers_pre_s
            personas = st.number_input("Personas (exacto)", min_value=1, value=_pers_pre, step=1, key="p2_pers_custom") if _pers_sel == "5+" else int(_pers_sel)

        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

        # Zócalos — resumen geométrico automático
        _piezas_p2   = st.session_state.get("piezas", pre.get("piezas",[]))
        _zoc_geo_p2  = calcular_zocalo_geometrico(_piezas_p2)
        _zocalo_ml_auto = _zoc_geo_p2["ml"]
        _zocalo_m2_auto = _zoc_geo_p2["m2"]
        zocalo_activo   = _zocalo_ml_auto > 0
        zocalo_ml       = _zocalo_ml_auto

        html_zoc = '<div style="font-size:0.85rem;border-radius:8px;padding:10px 14px;margin-bottom:4px;background:var(--secondary-background-color);border:1px solid var(--border-color)">\n'
        if _zocalo_ml_auto > 0:
            _piezas_con_zoc = [p for p in _piezas_p2 if p.get("zoc_trasero") or p.get("zoc_izq") or p.get("zoc_der")]
            _m2_txt_p2 = f" · <strong>{_zocalo_m2_auto:.4f} m²</strong> de material" if _zocalo_m2_auto > 0 else ""
            html_zoc += f'<span style="font-weight:700">📐 Zócalos del proyecto: {_zocalo_ml_auto:.2f} ml</span>{_m2_txt_p2} — calculados automáticamente desde {len(_piezas_con_zoc)} pieza{"s" if len(_piezas_con_zoc)!=1 else ""}. Para editar, vuelve al <strong>Paso 1</strong>.\n'
        else:
            html_zoc += '<span style="opacity:0.55">📐 Sin zócalos — actívalos en el Paso 1 dentro de cada pieza.</span>\n'
        html_zoc += "</div>"
        st.markdown(html_zoc, unsafe_allow_html=True)

        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

        # Desperdicio
        desperdicio_sugerido_15 = round(m2_real * 0.15, 2)
        st.markdown("""
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px">
          <span style="font-weight:700;font-size:1rem">Desperdicio en cortes</span>
          <span style="background:#1F6F54;color:white;font-size:0.65rem;font-weight:700;padding:3px 8px;border-radius:20px;letter-spacing:0.05em">RETAL</span>
        </div>
        <p style="font-size:0.82rem;opacity:0.65;margin:0 0 10px">Todo corte genera sobrante. Elige el perfil de tu proyecto.</p>""", unsafe_allow_html=True)

        with st.container(border=True):
            perfil_opciones = {
                "🟢 Simple — cortes rectos, sin curvas":    ("simple",   0.10),
                "🟡 Normal — algunos ángulos o esquinas":   ("normal",   0.15),
                "🔴 Complejo — curvas, biselados, figuras": ("complejo", 0.22),
                "✏️ Personalizado":                         ("custom",   None),
            }
            _perfil_guardado  = fn_sp().get("cdir_perfil_desperdicio") or pre.get("perfil_desperdicio","")
            _perfil_idx_default = 1
            if _perfil_guardado:
                for _idx_p, _key_p in enumerate(list(perfil_opciones.keys())):
                    if _perfil_guardado == _key_p:
                        _perfil_idx_default = _idx_p
                        break
            perfil_sel = st.radio("Perfil de corte", list(perfil_opciones.keys()), index=_perfil_idx_default, key="perfil_desperdicio_radio", label_visibility="collapsed", on_change=fn_cb_cdir_perfil_desperdicio)
            if perfil_sel is None:
                perfil_sel = list(perfil_opciones.keys())[_perfil_idx_default]
            if fn_sp().get("cdir_perfil_desperdicio") != perfil_sel:
                fn_sp_set("cdir_perfil_desperdicio", perfil_sel)
            if st.session_state.pre.get("perfil_desperdicio") != perfil_sel:
                st.session_state.pre = {**st.session_state.pre, "perfil_desperdicio": perfil_sel}
                pre = st.session_state.pre
            perfil_id, pct_auto = perfil_opciones[perfil_sel]
            pct_auto = pct_auto or 0.15

            _cv1, _cv2 = st.columns([1.2, 1])
            with _cv1:
                st.markdown("<div style='font-size:0.78rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;opacity:0.6;margin-bottom:6px'>m² de retal estimados</div>", unsafe_allow_html=True)
                if perfil_id == "custom":
                    extra_corte = st.number_input("m² de retal", min_value=0.0, max_value=float(area_placa) if area_placa>0 else 50.0, value=float(pre.get("extra_corte", round(m2_real*0.15,2))), step=0.05, format="%.2f", label_visibility="collapsed", key="cdir_extra_corte")
                    pct_real    = (extra_corte / m2_real * 100) if m2_real > 0 else 0
                    st.caption(f"Equivale al **{pct_real:.1f}%** del proyecto")
                else:
                    extra_corte = round(m2_real * pct_auto, 2)
                    color_pct   = "#1F6F54" if pct_auto <= 0.12 else "#C9A45C" if pct_auto <= 0.17 else "#C9A45C"
                    st.markdown(f'<div style="background:var(--secondary-background-color);border:2px solid {color_pct};border-radius:8px;padding:10px 14px;display:inline-flex;align-items:baseline;gap:8px"><span style="font-size:1.8rem;font-weight:900;color:{color_pct}">{_fmt_m2(extra_corte)}</span><span style="font-size:0.8rem;color:{color_pct};font-weight:700">({pct_auto*100:.0f}%)</span></div>', unsafe_allow_html=True)
                    st.caption(f"Calculado automáticamente ({pct_auto*100:.0f}% de {_fmt_m2(m2_real)})")

            with _cv2:
                _tar_actual    = fn_get_tarifas().get(cat_sel, TARIFAS.get(cat_sel, TARIFAS["Mármol"]))
                if isinstance(_tar_actual, list):
                    _disco_tarifa = next((r["valor"] for r in _tar_actual if r.get("nombre_interno") == "Desgaste disco" or (r.get("inductor") == "por_m2" and "disco" in r.get("nombre_interno","").lower())), 2_200)
                else:
                    _disco_tarifa = _tar_actual.get("disco", 2_200)
                _costo_disco_ret  = extra_corte * _disco_tarifa
                _costo_disco_base = m2_real    * _disco_tarifa
                st.markdown(f"""
                <div style="background:var(--secondary-background-color);border:1px solid var(--border-color);border-radius:8px;padding:10px 14px;font-size:0.82rem">
                  <div style="font-size:0.72rem;font-weight:700;opacity:0.5;margin-bottom:6px;text-transform:uppercase">Impacto en costo disco</div>
                  <div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid var(--border-color)"><span style="opacity:0.7">Proyecto</span><span style="font-weight:600">{_numero_completo(_costo_disco_base)}</span></div>
                  <div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid var(--border-color)"><span style="opacity:0.7">Retal</span><span style="font-weight:600;color:#C9A45C">+{_numero_completo(_costo_disco_ret)}</span></div>
                  <div style="display:flex;justify-content:space-between;padding:4px 0 0"><span style="font-weight:700">Total disco</span><span style="font-weight:800;color:#1F6F54">{_numero_completo(_costo_disco_base+_costo_disco_ret)}</span></div>
                </div>""", unsafe_allow_html=True)

        m2_cortados_total = m2_real + extra_corte
        _etapa_labels     = {v: k for k, v in ETAPAS_OBRA.items()}
        st.session_state.pre = {
            **pre,
            "tipos_proyecto": tipos_sel, "tipo_proyecto": tipo,
            "etapa_label": _etapa_labels.get(etapa, list(ETAPAS_OBRA.keys())[0]),
            "dias_obra": dias, "personas": personas, "nombre_cliente": nombre_cliente,
            "zocalo_activo": zocalo_activo, "zocalo_ml": zocalo_ml,
            "perfil_desperdicio": perfil_sel, "extra_corte": extra_corte,
            "m2_proyecto": m2_real, "m2_cortados_input": m2_cortados_total,
        }
        _c_paso.__exit__(None, None, None)

    # ══════════════════════════════════════════════════════════════════════════
    # PASO 3 — LOGÍSTICA + ADICIONALES + IVA
    # ══════════════════════════════════════════════════════════════════════════
    elif paso == 3:
        _c_paso = st.container(border=True)
        _c_paso.__enter__()
        _mats_p3 = st.session_state.get("materiales_proyecto", [])
        cat_sel  = _mats_p3[0]["cat"] if _mats_p3 else pre.get("categoria","Mármol")
        area_placa = sum(m["area_placa"] for m in _mats_p3) if _mats_p3 else pre.get("area_placa_comprada",5.94)
        _area_total_p3     = sum(m["area_placa"] for m in _mats_p3) or 1.0
        precio_m2_efectivo = (sum(m["precio_m2"]*m["area_placa"] for m in _mats_p3) / _area_total_p3 if _mats_p3 else pre.get("precio_m2",220_000))
        _piezas_p3         = st.session_state.get("piezas", pre.get("piezas",[]))
        m2_real            = sum(ml_a_m2(float(p.get("ml",0)), float(p.get("ancho_custom",0.60))) for p in _piezas_p3) or pre.get("m2_proyecto",4.0)
        m2_cortados_total  = pre.get("m2_cortados_input", m2_real)
        extra_corte        = pre.get("extra_corte", round(m2_real*0.15,2))
        margen_pct         = pre.get("margen_pct", 40)
        m2_usados          = pre.get("m2_usados", m2_real)
        dias               = pre.get("dias_obra", 2)
        personas           = pre.get("personas", 2)
        tipo               = pre.get("tipo_proyecto","Mesón")
        etapa              = ETAPAS_OBRA.get(pre.get("etapa_label",""), list(ETAPAS_OBRA.values())[0])
        nombre_cliente     = pre.get("nombre_cliente","")
        zocalo_activo      = pre.get("zocalo_activo", False)
        zocalo_ml          = pre.get("zocalo_ml", 0.0)
        tipos_sel          = pre.get("tipos_proyecto",["Mesón"])

        _seccion_titulo("Logística y extras", "Transporte, viáticos, servicios adicionales e IVA")

        with st.container(border=True):
            st.markdown("**🚛 Transporte y entrega**")
            _lag1, _lag2 = st.columns(2)
            with _lag1:
                agente_ext_taller = st.toggle("Agente externo trajo el material al taller", value=bool(fn_sp().get("cdir_agente_externo", pre.get("agente_externo_taller",False))), key="cb_cdir_agente_externo", on_change=fn_cb_cdir_agente_externo)
                if agente_ext_taller:
                    _log_now_p3 = fn_get_logistica()
                    _flete_ref  = int(_log_now_p3.get("flete_externo", _log_now_p3.get("externo", {}).get("flete", 165_000) if isinstance(_log_now_p3.get("externo"), dict) else 165_000))
                    st.caption(f"Flete base activo: **{_numero_completo(_flete_ref)}**")

            with _lag2:
                _km_opts         = ["0-5 km","5-15 km","15-30 km","30-60 km","60+ km"]
                _km_pre          = float(pre.get("km",5.0))
                _km_rango_stored = fn_sp().get("cdir_km_rango", None)
                _km_pre_s        = _km_rango_stored if _km_rango_stored in _km_opts else ("0-5 km" if _km_pre<=5 else "5-15 km" if _km_pre<=15 else "15-30 km" if _km_pre<=30 else "30-60 km" if _km_pre<=60 else "60+ km")
                _km_rango        = st.pills("Distancia al destino", _km_opts, default=_km_pre_s, key="p3_km_pills_cb", on_change=fn_cb_cdir_km_rango)
                _km_rango        = _km_rango if _km_rango else _km_pre_s
                _km_defaults     = {"0-5 km":3,"5-15 km":10,"15-30 km":22,"30-60 km":45,"60+ km":80}
                _km_val_init     = float(fn_sp().get("cdir_km", _km_defaults.get(_km_rango, _km_pre)))
                km               = st.number_input("Km exactos (un trayecto)", min_value=0.0, value=_km_val_init, step=1.0, key="cb_cdir_km", on_change=fn_cb_cdir_km_rango)

            _peaje_total_pre = float(pre.get("costo_peaje_total", pre.get("costo_peaje_unitario", 0.0)))
            peaje_total_ruta = st.number_input(
                "💰 Costo Total de Peajes de la Ruta ($)",
                min_value=0,
                value=int(_peaje_total_pre),
                step=500,
                format="%d",
                key="p3_peaje_total",
                help="Ingresa el valor exacto en pesos que pagas en peajes (ida + vuelta). Ej: $39.000 si hay 2 peajes de $19.500.",
            )
            if peaje_total_ruta > 0:
                st.caption(f"Total peajes incluido: **{_numero_completo(peaje_total_ruta)}**")

        with st.container(border=True):
            st.markdown("**✈️ ¿El proyecto es fuera de Barranquilla?**")
            foraneo_activo   = st.toggle("Sí, proyecto en otra ciudad", value=fn_sp().get("cdir_foraneo", pre.get("foraneo_activo",False)), key="cb_cdir_foraneo", on_change=fn_cb_cdir_foraneo)
            viaticos_activos = False
            tipo_aloj        = "pueblo"
            noches           = 0
            num_instaladores = pre.get("num_instaladores",2)
            incluir_hospedaje = pre.get("incluir_hospedaje",True)
            tipo_alimentacion = pre.get("tipo_alimentacion","completa")

            if foraneo_activo:
                _fa1, _fa2 = st.columns(2)
                with _fa1:
                    viaticos_activos = st.toggle("Incluir viáticos", value=fn_sp().get("cdir_viaticos_activos", pre.get("viaticos_activos",False)), key="cb_cdir_viaticos_activos", on_change=fn_cb_cdir_viaticos_activos)
                with _fa2:
                    _sp_tipo_aloj = fn_sp().get("cdir_tipo_aloj", pre.get("tipo_aloj","pueblo"))
                    tipo_aloj = ALOJAMIENTO[st.selectbox("Destino", list(ALOJAMIENTO.keys()), index=list(ALOJAMIENTO.keys()).index(next((k for k,v in ALOJAMIENTO.items() if v==_sp_tipo_aloj), list(ALOJAMIENTO.keys())[0])), key="cb_cdir_tipo_aloj", on_change=fn_cb_cdir_tipo_aloj)]

                if viaticos_activos:
                    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
                    _vb1, _vb2, _vb3 = st.columns(3)
                    with _vb1:
                        num_instaladores = st.number_input("N° instaladores", min_value=1, max_value=10, value=int(pre.get("num_instaladores",2)), step=1, key="p3_num_instaladores")
                    with _vb2:
                        _nc_opts  = ["1","2","3","4","5+"]
                        _nc_pre   = int(pre.get("noches",1))
                        _nc_pre_s = str(_nc_pre) if str(_nc_pre) in _nc_opts else ("5+" if _nc_pre>4 else _nc_opts[0])
                        _nc_sel   = st.pills("Días de trabajo", _nc_opts, default=_nc_pre_s, key="p3_noches_pills")
                        _nc_sel   = _nc_sel if _nc_sel else _nc_pre_s
                        noches    = st.number_input("Días (exacto)", min_value=1, value=_nc_pre, step=1, key="p3_noches_custom") if _nc_sel=="5+" else int(_nc_sel)
                    with _vb3:
                        incluir_hospedaje = st.checkbox("Requiere hospedaje", value=bool(pre.get("incluir_hospedaje",True)), key="p3_incluir_hospedaje")
                    _alim_opts = {"3 comidas (desayuno+almuerzo+cena)":"completa","Solo almuerzos":"almuerzo","Sin alimentación incluida":"ninguna"}
                    _alim_pre_val = pre.get("tipo_alimentacion","completa")
                    _alim_pre_lbl = next((k for k,v in _alim_opts.items() if v==_alim_pre_val), "3 comidas (desayuno+almuerzo+cena)")
                    _alim_sel = st.radio("Alimentación", list(_alim_opts.keys()), index=list(_alim_opts.keys()).index(_alim_pre_lbl), key="p3_tipo_alimentacion", horizontal=True)
                    tipo_alimentacion = _alim_opts[_alim_sel]
                    personas = num_instaladores

        with st.container(border=True):
            st.markdown("**🔧 Costos adicionales** *(silicona, impermeabilizante, etc.)*")
            _ADICIONALES_ACT = fn_get_adicionales()
            adicionales_activos = st.toggle("Agregar costos adicionales", value=fn_sp().get("cdir_adicionales_activos", pre.get("adicionales_activos",False)), key="cb_cdir_adicionales_activos", on_change=fn_cb_cdir_adicionales_activos)
            cantidades_add = pre.get("cantidades_add", [0.0]*len(_ADICIONALES_ACT)) if pre.get("adicionales_activos") else [0.0]*len(_ADICIONALES_ACT)
            while len(cantidades_add) < len(_ADICIONALES_ACT):
                cantidades_add.append(0.0)
            if adicionales_activos:
                for i, a in enumerate(_ADICIONALES_ACT):
                    _ac1, _ac2 = st.columns([3.5, 0.5])
                    _ac1.markdown(f"<div style='font-size:0.85rem;padding:8px 0'>{a['concepto']} — <strong>{_numero_completo(a.get(etapa,0))}/{a['unidad']}</strong></div>", unsafe_allow_html=True)
                    cantidades_add[i] = _ac2.number_input("Cant.", min_value=0.0, value=float(cantidades_add[i]), step=1.0, key=f"add_{i}", label_visibility="collapsed")

        with st.container(border=True):
            st.markdown("**🧾 IVA en la cotización**")
            _iv1, _iv2 = st.columns([1, 1.5])
            with _iv1:
                incluir_iva = st.toggle("Incluir IVA 19%", value=fn_sp().get("cdir_incluir_iva", pre.get("incluir_iva",True)), key="cb_cdir_incluir_iva", on_change=fn_cb_cdir_incluir_iva)
            with _iv2:
                if incluir_iva:
                    st.info("IVA 19% sobre el total de la cotización.", icon="🧾")
                else:
                    st.warning("Sin IVA — aplica régimen simplificado.", icon="⚠️")

        _etapa_labels = {v: k for k, v in ETAPAS_OBRA.items()}
        st.session_state.pre = {
            **st.session_state.pre,
            "agente_externo_taller": agente_ext_taller,
            "vehiculo_entrega": "externo", "km": km,
            "peajes": 0, "costo_peaje_unitario": 0.0, "costo_peaje_total": peaje_total_ruta,
            "foraneo_activo": foraneo_activo, "viaticos_activos": viaticos_activos,
            "tipo_aloj": tipo_aloj, "noches": noches,
            "num_instaladores": num_instaladores, "incluir_hospedaje": incluir_hospedaje,
            "tipo_alimentacion": tipo_alimentacion,
            "adicionales_activos": adicionales_activos, "cantidades_add": cantidades_add,
            "incluir_iva": incluir_iva,
        }
        fn_sp_set("cdir_agente_externo", agente_ext_taller)
        fn_sp_set("cdir_km", km)
        fn_sp_set("cdir_peaje_total", peaje_total_ruta)
        fn_sp_set("cdir_foraneo", foraneo_activo)
        fn_sp_set("cdir_viaticos_activos", viaticos_activos)
        fn_sp_set("cdir_tipo_aloj", tipo_aloj)
        fn_sp_set("cdir_noches", noches)
        fn_sp_set("cdir_adicionales_activos", adicionales_activos)
        fn_sp_set("cdir_cantidades_add", cantidades_add)
        fn_sp_set("cdir_incluir_iva", incluir_iva)
        _c_paso.__exit__(None, None, None)

    # ══════════════════════════════════════════════════════════════════════════
    # PASO 4 — CALCULAR
    # ══════════════════════════════════════════════════════════════════════════
    elif paso == 4:
        _mats   = st.session_state.get("materiales_proyecto", [])
        _piezas = st.session_state.get("piezas", pre.get("piezas",[]))

        cat_sel             = _mats[0]["cat"] if _mats else pre.get("categoria","Mármol")
        _refs_raw2          = [m["ref"] or m["cat"] for m in _mats]
        _refs_unicas2       = list(dict.fromkeys(_refs_raw2))
        referencia          = " + ".join(_refs_unicas2) if len(_refs_unicas2) > 1 else (_refs_unicas2[0] if _refs_unicas2 else "")
        _area_total_p4      = sum(m["area_placa"] for m in _mats) or 1.0
        precio_m2_efectivo  = (sum(m["precio_m2"]*m["area_placa"] for m in _mats) / _area_total_p4 if _mats else pre.get("precio_m2",220_000))
        area_placa          = sum(m["area_placa"] for m in _mats) if _mats else pre.get("area_placa_comprada",5.94)
        m2_real             = sum(ml_a_m2(float(p.get("ml",0)), float(p.get("ancho_custom",0.60))) for p in _piezas) or pre.get("m2_projeto",4.0)
        m2_cortados_total   = pre.get("m2_cortados_input", m2_real)
        m2_usados           = pre.get("m2_usados", m2_real)
        margen_pct          = pre.get("margen_pct", 40)
        _etapa_label        = pre.get("etapa_label", list(ETAPAS_OBRA.keys())[0])
        etapa               = ETAPAS_OBRA.get(_etapa_label, list(ETAPAS_OBRA.values())[0])
        dias                = pre.get("dias_obra", 2)
        personas            = pre.get("personas", 2)
        tipo                = pre.get("tipo_proyecto","Mesón")
        nombre_cliente      = pre.get("nombre_cliente","")
        zocalo_activo       = pre.get("zocalo_activo", False)
        zocalo_ml           = pre.get("zocalo_ml", 0.0)
        agente_ext_taller   = pre.get("agente_externo_taller", False)
        vehiculo            = pre.get("vehiculo_entrega","frontier")
        km                  = pre.get("km", 5.0)
        peajes              = pre.get("peajes", 0)
        foraneo_activo      = pre.get("foraneo_activo", False)
        viaticos_activos    = pre.get("viaticos_activos", False)
        tipo_aloj           = pre.get("tipo_aloj","pueblo")
        noches              = pre.get("noches", 0)
        adicionales_activos = pre.get("adicionales_activos", False)
        cantidades_add      = pre.get("cantidades_add", [])
        incluir_iva         = pre.get("incluir_iva", True)
        tipos_sel           = pre.get("tipos_proyecto", ["Mesón"])
        _ADICIONALES_ACT    = fn_get_adicionales()

        _etapa_labels   = {v: k for k, v in ETAPAS_OBRA.items()}
        _retal_ids_snap = {k: v for k, v in st.session_state.items() if k.startswith("retal_id_") and v}
        _pre_snapshot   = {
            "materiales_proyecto": st.session_state.get("materiales_proyecto",[]),
            "tipos_proyecto": tipos_sel, "tipo_proyecto": tipo,
            "etapa_label": _etapa_labels.get(etapa, list(ETAPAS_OBRA.keys())[0]),
            "dias_obra": dias, "personas": personas, "nombre_cliente": nombre_cliente,
            "zocalo_activo": zocalo_activo, "zocalo_ml": zocalo_ml,
            "perfil_desperdicio": pre.get("perfil_desperdicio",""),
            "extra_corte": pre.get("extra_corte", round(m2_real*0.15,2)),
            "m2_proyecto": m2_real, "m2_cortados_input": m2_cortados_total,
            "m2_usados": m2_usados, "margen_pct": margen_pct,
            "agente_externo_taller": agente_ext_taller,
            "vehiculo_entrega": "externo", "km": km, "peajes": 0,
            "costo_peaje_total": pre.get("costo_peaje_total", 0.0),
            "foraneo_activo": foraneo_activo, "viaticos_activos": viaticos_activos,
            "tipo_aloj": tipo_aloj, "noches": noches,
            "adicionales_activos": adicionales_activos, "cantidades_add": cantidades_add,
            "incluir_iva": incluir_iva,
            "piezas": _piezas,
            "cdir_paso": st.session_state.get("cdir_paso", 0),
            "editando_id": st.session_state.get("editando_id"),
            **_retal_ids_snap,
        }
        st.session_state.pre = _pre_snapshot

        try:
            _nuevo_hash = hash(json.dumps(_pre_snapshot, sort_keys=True, default=str))
            if _nuevo_hash != st.session_state.get("last_pre_hash"):
                fn_guardar_config(fn_clave_borrador_cdir(), _pre_snapshot)
                st.session_state["last_pre_hash"] = _nuevo_hash
        except Exception:
            pass

        # Estrategia de Cobro de Material
        _opciones_estrategia = ["Placa Completa (Tradicional)", "Producto Terminado (Optimizado)"]
        _estrategia_lbl = st.radio("⚖️ Estrategia de Cobro de Material", _opciones_estrategia, index=0, horizontal=True, key="cdir_estrategia_precio")
        _estrategia_val = "optimizado" if "Optimizado" in _estrategia_lbl else "placa_completa"
        with st.expander("💡 Guía de Cobro: ¿Qué modelo elegir?"):
            st.markdown("""
Esta decisión define cómo se calcula el costo del material y quién asume el desperdicio.

**🟦 Opción 1: Placa Completa (Tradicional)**
El cliente asume el costo de **toda la lámina** de piedra que se necesita comprar para su proyecto, sin importar cuánto sobre.
* **¿Quién se queda con el sobrante?** El cliente (o se desecha).
* **¿Cuándo elegirlo?** Para materiales exóticos, costosos o de muy baja rotación. Si compras una lámina rara solo para este cliente y te sobra un pedazo, ese retal es dinero inmovilizado. Cóbrasela completa.

**🟩 Opción 2: Producto Terminado (Optimizado)**
El cliente paga **únicamente por los metros reales** que se van a instalar en su espacio (más un pequeño porcentaje estándar de seguridad por cortes).
* **¿Quién se queda con el sobrante?** La empresa. Pasa a formar parte de tu "Banco de Retales".
* **¿Cuándo elegirlo?** Ideal para materiales de alta rotación (como Quarztone Blanco o Granitos comerciales). Al quedarte con el retal, puedes venderlo en el futuro con un margen de ganancia del 100%. Maximiza la rentabilidad a largo plazo.

| Criterio | Placa Completa | Producto Terminado |
| :--- | :--- | :--- |
| **Costo para el cliente** | Más alto (paga todo) | Más competitivo (paga lo que usa) |
| **Riesgo para la empresa** | Cero (todo está pago) | Bajo (el retal es una inversión) |
| **Uso estratégico** | Materiales exclusivos | Materiales muy vendidos |
""")
        if st.session_state.cotizacion and st.session_state.cotizacion.get("estrategia_precio") != _estrategia_val:
            st.session_state["_recalcular_paso4"] = True

        if not st.session_state.cotizacion or st.session_state.get("_recalcular_paso4"):
            with st.spinner("Calculando costos..."):
                _ml_tot  = sum(p.get("ml",0) for p in _piezas)
                resultado = calcular_cotizacion_directa(
                    categoria=cat_sel, referencia=referencia, precio_m2=precio_m2_efectivo,
                    area_placa_comprada=area_placa, m2_real=m2_real, m2_cortados=m2_cortados_total,
                    materiales_lista=st.session_state.get("materiales_proyecto",[]),
                    m2_usados=m2_usados, margen_pct=margen_pct, dias=dias, personas=personas,
                    zocalo_activo=zocalo_activo, zocalo_ml=zocalo_ml,
                    agente_externo_taller=agente_ext_taller, vehiculo_entrega="externo",
                    km=km, num_peajes=0, foraneo_activo=foraneo_activo,
                    viaticos_activos=viaticos_activos, tipo_aloj=tipo_aloj, noches=noches,
                    adicionales_activos=adicionales_activos, cantidades_add=cantidades_add,
                    etapa=etapa, adicionales_lista=_ADICIONALES_ACT,
                    tipo_proyecto=tipo, nombre_cliente=nombre_cliente,
                    ml_proyecto=_ml_tot,
                    logistica_override=st.session_state.get("logistica_custom"),
                    tarifas_override=st.session_state.get("tarifas_custom"),
                    piezas=_piezas,
                    costo_peaje_unitario=float(pre.get("costo_peaje_total", 0.0)),
                    incluir_hospedaje=bool(pre.get("incluir_hospedaje",True)),
                    tipo_alimentacion=pre.get("tipo_alimentacion","completa"),
                    estrategia_precio=_estrategia_val,
                    incluir_iva=incluir_iva,
                )
                resultado["_estado_guardado"] = _pre_snapshot
                resultado["incluir_iva"]      = incluir_iva
                st.session_state.cotizacion        = resultado
                st.session_state["_recalcular_paso4"] = False
                st.session_state["_snapshot_calculo"] = fn_generar_snapshot_datos()

        r        = st.session_state.cotizacion
        _iva_act = r.get("incluir_iva", incluir_iva)
        _iva_mont = r["precio_sugerido"] * 0.19 if _iva_act else 0.0
        _pf       = r["precio_sugerido"] + _iva_mont

        _num_auto = f"COT-{_hoy().strftime('%Y%m%d')}-{_rand.randint(100,999)}"
        if "cdir_num_auto" not in st.session_state:
            st.session_state.cdir_num_auto = _num_auto

        # Hero card
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#1C1C1C 0%,#1F6F54 100%);
                    border-radius:14px;padding:28px 36px;margin-bottom:20px;color:white;">
          <div style="color:#C9A45C;font-size:0.68rem;text-transform:uppercase;letter-spacing:0.14em;font-weight:700;margin-bottom:8px">
            Precio de venta sugerido {"(sin IVA)" if _iva_act else ""}
          </div>
          <div style="font-size:clamp(1.5rem,5vw,3.2rem);font-weight:900;font-family:'Playfair Display',serif;line-height:1.1;margin-bottom:8px;word-break:break-word">
            {_numero_completo(r["precio_sugerido"])}
          </div>
          <div style="opacity:0.8;font-size:0.85rem">
            Margen: {r["margen_pct"]:.0f}% &nbsp;·&nbsp; Utilidad: {_numero_completo(r["utilidad"])}
          </div>
          {"" if not _iva_act else f'<div style="margin-top:10px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.2)"><span style="color:#C9A45C;font-weight:700">+ IVA 19%: {_numero_completo(_iva_mont)}</span> &nbsp;→&nbsp; <span style="font-weight:900">Total: {_numero_completo(_pf)}</span></div>'}
        </div>""", unsafe_allow_html=True)

        _gan_retal = r.get("ganancia_oculta_retal", 0.0)
        if r.get("estrategia_precio") == "optimizado" and _gan_retal > 0:
            st.success(f"💰 **Optimización aplicada:** El sistema apartó un retal avaluado en **{_numero_completo(_gan_retal)} COP** ({_fmt_m2(r.get('retal',0.0))} que queda en inventario).", icon="🪨")

        col_izq, col_der = st.columns([1.2, 1])
        with col_izq:
            _m1, _m2_met = st.columns(2)
            _m1.metric("Aprovechamiento", f"{r['aprovechamiento']:.1f}%", f"Retal: {_fmt_m2(r['retal'])}")
            _m2_met.metric("Costo/m²", _numero_completo(r["costo_total"] / max(r["m2_real"],0.001)))
            _merma_info = r.get("merma_info", {})
            if _merma_info and _merma_info.get("merma_total_m2", 0) > 0:
                with st.expander(f"📊 Cálculo de merma: **{_merma_info['merma_total_m2']:.3f} m²** desperdicio proyectado", expanded=False):
                    st.markdown(_merma_info.get("explicacion_txt",""), unsafe_allow_html=False)
            st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
            _items_d = [
                ("Material",    r["c1_material"]),
                ("Producción",  r["c2_mano_obra"]),
                ("Zócalos",     r["c3_zocalos"]),
                ("Insumos",     r["c4_insumos"]),
                ("Logística",   r["c5_logistica"]),
                ("Viáticos",    r["c6_viaticos"]),
                ("Adicionales", r["c7_adicionales"]),
            ]
            if _iva_act:
                _items_d.append(("IVA 19%", _iva_mont))
            _bloque_costos(_items_d, "TOTAL CON IVA" if _iva_act else "PRECIO TOTAL", _pf)
            st.markdown("<div style='font-weight:700;margin:14px 0 8px'>Simulador de margen</div>", unsafe_allow_html=True)
            _sim_m = st.slider("Margen (%)", 5, 80, int(r["margen_pct"]), 1, key="sim_slider")
            _sim_p = r["costo_total"] / (1 - _sim_m / 100)
            _sim_ut = _sim_p - r["costo_total"]
            _sim_iva = _sim_p * 0.19 if _iva_act else 0.0
            st.markdown(
                f"""<div style="background:var(--secondary-background-color);border:1px solid var(--border-color);border-radius:10px;padding:12px 16px">
                <div style="display:flex;justify-content:space-between;align-items:center{';margin-bottom:6px' if _iva_act else ''}">
                  <span style="font-size:0.75rem;font-weight:700;opacity:0.55;text-transform:uppercase">{"Sin IVA" if _iva_act else "Precio total"}</span>
                  <span style="font-size:1.1rem;font-weight:900;color:#1F6F54">{_numero_completo(_sim_p)}</span>
                </div>
                {"" if not _iva_act else f'<div style="display:flex;justify-content:space-between;align-items:center;border-top:1px solid var(--border-color);padding-top:6px;margin-bottom:4px"><span style="font-size:0.75rem;font-weight:700;opacity:0.55;text-transform:uppercase">Con IVA 19%</span><span style="font-size:1.1rem;font-weight:900;color:#C9A45C">{_numero_completo(_sim_p + _sim_iva)}</span></div>'}
                <div style="font-size:0.72rem;opacity:0.5">Utilidad: {_numero_completo(_sim_ut)} · Margen: {_sim_m}%</div>
                </div>""",
                unsafe_allow_html=True
            )

        with col_der:
            _labels_pie = ["Material","Producción","Zócalos","Insumos","Logística","Viáticos","Adicionales"]
            _values_pie = [r["c1_material"],r["c2_mano_obra"],r["c3_zocalos"],r["c4_insumos"],r["c5_logistica"],r["c6_viaticos"],r["c7_adicionales"]]
            _lv = [(l,v) for l,v in zip(_labels_pie,_values_pie) if v > 0]
            if _lv:
                _lf, _vf = zip(*_lv)
                _fig_pie = go.Figure(go.Pie(labels=list(_lf), values=list(_vf), hole=0.42, textinfo="percent", textfont_size=11, marker=dict(colors=["#1F6F54","#C9A45C","#C9A45C","#A23B72","#F18F01","#C73E1D","#3B1F2B"][:len(_vf)])))
                _fig_pie.update_layout(margin=dict(t=10,b=10,l=10,r=10), height=240, showlegend=True, legend=dict(font=dict(size=10),orientation="v"), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(_fig_pie, use_container_width=True, config={"displayModeBar": False})

        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

        # Guardar en historial
        _ya_guardada  = st.session_state.get("_cotiz_guardada", False)
        _editando_id  = st.session_state.get("editando_id")
        _editando_num = st.session_state.get("editando_num","")

        if _editando_id:
            _alerta(f"**Modo edición** — modificando cotización **{_editando_num}**.", "info")
            _cu, _cn, _cc = st.columns([2, 1.5, 1])
            _btn_act   = _cu.button("✏️ Actualizar cotización", type="primary", use_container_width=True)
            _btn_nueva = _cn.button("💾 Guardar como nueva", use_container_width=True)
            _btn_can   = _cc.button("✕ Cancelar", use_container_width=True)
            if _btn_can:
                st.session_state.pop("editando_id", None)
                st.session_state.pop("editando_num", None)
                st.session_state.pop("pre", None)
                st.session_state.pop("cotizacion", None)
                st.session_state.cdir_paso = 0
                st.rerun()
            if _btn_act:
                fn_actualizar_cotizacion(_editando_id, _editando_num, nombre_cliente, r)
                st.session_state.pop("editando_id", None)
                st.session_state.pop("editando_num", None)
                st.session_state["_cotiz_guardada_num"] = _editando_num
                st.session_state["_cotiz_guardada"]     = True
                st.session_state.cdir_success           = True
                st.rerun()
            if _btn_nueva:
                fn_guardar_cotizacion(st.session_state.cdir_num_auto, nombre_cliente, r)
                st.session_state.pop("editando_id", None)
                st.session_state.pop("editando_num", None)
                st.session_state["_cotiz_guardada_num"] = st.session_state.cdir_num_auto
                st.session_state["_cotiz_guardada"]     = True
                st.session_state.cdir_success           = True
                st.rerun()

        elif not _ya_guardada:
            st.markdown("""<div style="background:var(--secondary-background-color);border:1px solid var(--border-color);border-radius:12px;padding:18px 22px;margin-bottom:4px">
            <div style="font-size:0.75rem;font-weight:700;opacity:0.5;text-transform:uppercase;margin-bottom:4px">💾 ¿Guardar en historial?</div>
            <div style="font-size:0.88rem;opacity:0.75;margin-bottom:12px">Si es una cotización real para un cliente, guárdala. Si es una prueba, puedes omitirlo.</div></div>""", unsafe_allow_html=True)
            _gc1, _gc2, _gc3 = st.columns([2, 1.5, 1])
            with _gc1:
                _num_guardar = st.text_input("Número de cotización", value=st.session_state.get("cdir_num_auto", _num_auto), key="num_guardar_hist", label_visibility="collapsed")
            with _gc2:
                if st.button("💾 Guardar en historial", type="primary", use_container_width=True, key="btn_guardar_hist"):
                    try:
                        fn_guardar_cotizacion(_num_guardar, r.get("nombre_cliente","Sin nombre"), r)
                        for _mi, _md in enumerate(st.session_state.get("materiales_proyecto",[])):
                            if _md.get("es_retal") and _md.get("retal_id"):
                                try:
                                    fn_marcar_retal_usado(_md["retal_id"], _md.get("area_placa",0))
                                    st.session_state.pop(f"usar_retal_{_mi}", None)
                                except Exception:
                                    pass
                        st.session_state["_cotiz_guardada"]     = True
                        st.session_state["_cotiz_guardada_num"] = _num_guardar
                        st.session_state.cdir_success           = True
                        st.rerun()
                    except Exception as _eg:
                        st.error(f"Error al guardar: {_eg}")
            with _gc3:
                if st.button("✕ Solo borrador", use_container_width=True, key="btn_no_guardar_hist"):
                    st.session_state["_cotiz_guardada"]     = True
                    st.session_state["_cotiz_guardada_num"] = ""
                    st.session_state.cdir_success           = True
                    st.toast("Cotización calculada como borrador.", icon="📋")
                    st.rerun()
        else:
            st.session_state.cdir_success = True
            st.rerun()

    # ══════════════════════════════════════════════════════════════════════════
    # NAVEGACIÓN — Atrás / Guardar Borrador / Siguiente
    # ══════════════════════════════════════════════════════════════════════════
    if not st.session_state.get("cdir_success") and paso < N_PASOS - 1:
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        _nav_l, _nav_mid, _nav_r = st.columns([1, 1, 1])

        _puede_continuar = True
        _msg_validacion  = ""

        if paso == 0:
            _mats_v = st.session_state.get("materiales_proyecto",[])
            if not _mats_v or all(m.get("area_placa",0) <= 0 for m in _mats_v):
                _puede_continuar = False
                _msg_validacion  = "Agrega al menos un material con área válida para continuar."
        elif paso == 1:
            _piezas_v = st.session_state.get("piezas",[])
            _m2_v = sum(ml_a_m2(float(p.get("ml",0)), float(p.get("ancho_custom",0.60))) for p in _piezas_v)
            if _m2_v <= 0:
                _puede_continuar = False
                _msg_validacion  = "Agrega al menos una pieza con dimensiones válidas."

        with _nav_l:
            if paso > 0:
                if st.button("← Atrás", use_container_width=True, key="btn_wizard_back"):
                    st.session_state.cdir_paso -= 1
                    if st.session_state.cdir_paso < 4:
                        st.session_state["cotizacion"]        = None
                        st.session_state["_recalcular_paso4"] = True
                        st.session_state["_cotiz_guardada"]   = False
                        st.session_state["cdir_success"]      = False
                    fn_sp_set("cdir_paso", st.session_state.cdir_paso)
                    fn_sp_commit_borrador()
                    st.rerun()

        with _nav_mid:
            _mats_bor  = st.session_state.get("materiales_proyecto",[])
            _piezas_bor = st.session_state.get("piezas",[])
            _hay_datos  = bool(_mats_bor or _piezas_bor)
            if st.button("💾 Guardar Borrador", use_container_width=True, key="btn_guardar_borrador_wizard", disabled=not _hay_datos):
                try:
                    _r_calc = st.session_state.get("cotizacion") or {}
                    _pre_bor = st.session_state.get("pre", {})
                    _mat0    = _mats_bor[0] if _mats_bor else {}
                    _payload_bor = {
                        "categoria": _mat0.get("cat", _pre_bor.get("categoria","Sin material")),
                        "referencia": _mat0.get("ref", _pre_bor.get("referencia","")),
                        "tipo_proyecto": _pre_bor.get("tipo_proyecto",""),
                        "nombre_cliente": _pre_bor.get("nombre_cliente",""),
                        "m2_real": _r_calc.get("m2_real",0),
                        "ml_proyecto": _r_calc.get("ml_proyecto",0),
                        "costo_total": _r_calc.get("costo_total",0),
                        "precio_sugerido": _r_calc.get("precio_sugerido",0),
                        "margen_pct": _r_calc.get("margen_pct", _pre_bor.get("margen_pct",0)),
                        "materiales_proyecto": _mats_bor,
                        "piezas": _piezas_bor,
                        "pre_snapshot": _pre_bor,
                        "cdir_paso": paso,
                    }
                    _bid     = st.session_state.get("borrador_actual_id")
                    _bid_new = fn_guardar_borrador_cotizacion(_payload_bor, _bid)
                    st.session_state["borrador_actual_id"] = _bid_new
                    st.success("✅ Borrador guardado" if not _bid else "✅ Borrador actualizado", icon="💾")
                except Exception as _eb:
                    st.error(f"No se pudo guardar el borrador: {_eb}")

        with _nav_r:
            if not _puede_continuar:
                st.warning(_msg_validacion)
            else:
                _lbl_sig = "Calcular cotización →" if paso == N_PASOS - 2 else "Siguiente →"
                if st.button(_lbl_sig, type="primary", use_container_width=True, key="btn_wizard_next"):
                    st.session_state.cdir_paso += 1
                    fn_sp_set("cdir_paso", st.session_state.cdir_paso)
                    fn_sp_commit_borrador()
                    if st.session_state.cdir_paso == N_PASOS - 1:
                        st.session_state["_recalcular_paso4"] = True
                    st.rerun()
