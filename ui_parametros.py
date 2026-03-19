# ui_parametros.py
# ─────────────────────────────────────────────────────────────────────────────
# Módulo de Parámetros Operativos y Costos
# Extraído de app.py siguiendo el patrón Strangler Fig (Fase 5).
#
# REGLA ARQUITECTÓNICA: este archivo NUNCA importa app.py.
# Las dependencias de BD, caché y estado global se inyectan como parámetros.
#
# Firma principal:
#   _ui_parametros(
#       fn_get_tarifas,        # () -> dict
#       fn_get_viaticos,       # () -> dict
#       fn_get_logistica,      # () -> dict
#       fn_get_adicionales,    # () -> list
#       fn_guardar_config,     # (clave: str, valor) -> None
#       fn_chat_parametros,    # (historial: list, mensaje: str) -> str
#       fn_interceptar_ia,     # (respuesta: str) -> dict | None
#       fn_sp,                 # () -> dict  (store_permanente)
#       fn_numero_completo,    # (valor) -> str
#       fn_ia_disponible,      # () -> bool
#   )
# ─────────────────────────────────────────────────────────────────────────────

import copy as _copy

import streamlit as st
from parametros import TARIFAS, LOGISTICA, VIATICOS, ADICIONALES


def _ui_parametros(
    fn_get_tarifas,
    fn_get_viaticos,
    fn_get_logistica,
    fn_get_adicionales,
    fn_guardar_config,
    fn_chat_parametros,
    fn_interceptar_ia,
    fn_sp,
    fn_numero_completo,
    fn_ia_disponible,
):
    """Renderiza la pestaña completa de Parámetros Operativos y Costos."""

    import pandas as pd

    st.markdown(
        "<h2 style='font-family:Playfair Display,serif'>Parámetros Operativos y Costos</h2>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "Ten control total de los costos de la empresa. "
        "Modifica las tablas manualmente o pídele al asistente que lo haga por ti."
    )

    t_ia, t_tar, t_via, t_log, t_add = st.tabs([
        "🤖 Asistente IA (Modificación Automática)",
        "📊 Tarifas y Producción",
        "🚗 Viáticos",
        "🚛 Logística y Vehículos",
        "➕ Costos Adicionales",
    ])

    # ─────────────────────────────────────────────────────────────────────────
    # TAB: 🤖 ASISTENTE IA
    # ─────────────────────────────────────────────────────────────────────────
    with t_ia:
        _ia_ok = fn_ia_disponible()

        st.markdown("""
        <style>
        .pmsg-user {
            background: #1B5FA8; color: white;
            border-radius: 14px 14px 3px 14px;
            padding: 9px 14px; margin: 2px 0 2px 25%;
            font-size: 0.86rem; line-height: 1.55;
        }
        .pmsg-ai {
            background: var(--secondary-background-color);
            border: 1px solid var(--border-color);
            border-radius: 14px 14px 14px 3px;
            padding: 9px 14px; margin: 2px 25% 2px 0;
            font-size: 0.86rem; line-height: 1.6;
        }
        .pmsg-label {
            font-size: 0.63rem; font-weight: 700; letter-spacing: 0.06em;
            text-transform: uppercase; opacity: 0.38; margin-bottom: 3px;
        }
        .cambio-row {
            display: flex; align-items: center; gap: 10px;
            padding: 6px 0; border-bottom: 1px solid var(--border-color);
            font-size: 0.83rem;
        }
        .cambio-campo { font-weight: 600; flex: 2; }
        .cambio-antes { opacity: 0.45; flex: 1; text-decoration: line-through; }
        .cambio-despues { color: #16a34a; font-weight: 700; flex: 1; }
        .val-actual-row {
            display: flex; justify-content: space-between;
            padding: 5px 0; border-bottom: 1px solid var(--border-color);
            font-size: 0.82rem;
        }
        .val-label { opacity: 0.65; }
        .val-num { font-weight: 700; font-variant-numeric: tabular-nums; }
        .cmd-btn-row { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px; }
        </style>
        """, unsafe_allow_html=True)

        if not _ia_ok:
            st.markdown(
                '<div style="border:1px solid var(--border-color);border-radius:10px;'
                'padding:20px 24px;max-width:480px">'
                '<div style="font-weight:700;margin-bottom:6px">API key no configurada</div>'
                '<div style="font-size:0.87rem;opacity:0.7">Ve a Configuración para activar el asistente.</div>'
                '</div>',
                unsafe_allow_html=True,
            )
        else:
            _col_chat, _col_vals = st.columns([3, 2])

            with _col_chat:
                _comandos_rapidos = [
                    ("Gasolina subió", "La gasolina corriente subió. ¿A cuánto debería quedar mi costo por km en la Frontier?"),
                    ("Nuevo precio operario", "El operario de mármol ahora cobra más. ¿Cómo ajusto la tarifa por ml?"),
                    ("Viáticos fuera de ciudad", "¿Cuánto debería presupuestar por persona para trabajar en Cartagena o Santa Marta?"),
                    ("¿Mis consumibles son correctos?", "¿Los costos de consumibles que tengo son razonables para el mercado actual de Barranquilla?"),
                ]

                st.markdown(
                    "<div style='font-size:0.68rem;font-weight:700;opacity:0.4;letter-spacing:0.07em;"
                    "text-transform:uppercase;margin-bottom:8px'>Situaciones frecuentes</div>",
                    unsafe_allow_html=True,
                )
                _cmd_c1, _cmd_c2 = st.columns(2)
                for _ci, (_lbl, _msg_cmd) in enumerate(_comandos_rapidos):
                    _col_cmd = _cmd_c1 if _ci % 2 == 0 else _cmd_c2
                    with _col_cmd:
                        if st.button(_lbl, key=f"pcmd_{_ci}", use_container_width=True):
                            st.session_state.params_wizard_chat.append({"role": "user", "content": _lbl})
                            with st.spinner(""):
                                _r_cmd = fn_chat_parametros(st.session_state.params_wizard_chat[:-1], _msg_cmd)
                            _ia_accion = fn_interceptar_ia(_r_cmd)
                            _aplicado_cmd = False
                            if _ia_accion:
                                try:
                                    _ac = _ia_accion["accion"]; _d = _ia_accion["datos"]
                                    if _ac == "actualizar_viaticos":
                                        _antes = (st.session_state.viaticos_custom or VIATICOS).copy()
                                        st.session_state.viaticos_custom = _d
                                        fn_sp()["params_viaticos"] = _d
                                        st.session_state.params_cambios_aplicados.append({"tipo": "viaticos", "antes": _antes, "despues": _d})
                                        try: fn_guardar_config("viaticos_custom", _d)
                                        except Exception: pass
                                    elif _ac == "actualizar_tarifas":
                                        _antes = (st.session_state.tarifas_custom or TARIFAS).copy()
                                        st.session_state.tarifas_custom = _d
                                        st.session_state.params_cambios_aplicados.append({"tipo": "tarifas", "antes": _antes, "despues": _d})
                                        try: fn_guardar_config("tarifas_custom", _d)
                                        except Exception: pass
                                    elif _ac == "actualizar_logistica":
                                        _antes = (st.session_state.logistica_custom or LOGISTICA).copy()
                                        _logist_nuevo = {**_antes, **_d}
                                        st.session_state.logistica_custom = _logist_nuevo
                                        st.session_state.params_cambios_aplicados.append({"tipo": "logistica", "antes": _antes, "despues": _logist_nuevo})
                                        try: fn_guardar_config("logistica_custom", _logist_nuevo)
                                        except Exception: pass
                                    _aplicado_cmd = True
                                except Exception:
                                    pass
                            st.session_state.params_wizard_chat.append({
                                "role": "assistant", "content": _r_cmd, "aplicado": _aplicado_cmd
                            })
                            st.rerun()

                st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

                if not st.session_state.params_wizard_chat:
                    st.markdown(
                        '<div style="border:1px dashed var(--border-color);border-radius:10px;'
                        'padding:24px 18px;text-align:center;">'
                        '<div style="font-size:0.85rem;opacity:0.45;line-height:1.7">'
                        'Cuéntame qué cambió en tu operación.<br>'
                        '<span style="font-size:0.78rem">"La gasolina subió a $16.800" &nbsp;·&nbsp; '
                        '"El operario cobra $65.000/ml ahora"</span>'
                        '</div></div>',
                        unsafe_allow_html=True,
                    )
                else:
                    for _pm in st.session_state.params_wizard_chat:
                        _es_u = _pm["role"] == "user"
                        _ptxt = _pm["content"]
                        _p_aplicado = _pm.get("aplicado", False)
                        if not _es_u and "```json" in _ptxt:
                            _ptxt = _ptxt.split("```json")[0].strip()
                        if _es_u:
                            st.markdown(
                                f'<div class="pmsg-label" style="text-align:right">Tú</div>'
                                f'<div class="pmsg-user">{_ptxt}</div>',
                                unsafe_allow_html=True,
                            )
                        else:
                            _badge = (
                                '<div style="display:inline-block;font-size:0.71rem;font-weight:700;'
                                'background:#dcfce7;color:#15803d;padding:2px 10px;border-radius:6px;margin-top:6px">'
                                'Valores actualizados</div>'
                            ) if _p_aplicado else ""
                            st.markdown(
                                f'<div class="pmsg-label">Asistente</div>'
                                f'<div class="pmsg-ai">{_ptxt}{_badge}</div>',
                                unsafe_allow_html=True,
                            )

                st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

                _pi_c, _ps_c = st.columns([5, 1])
                with _pi_c:
                    _pnuevo = st.text_input(
                        "msg",
                        key="params_chat_input",
                        placeholder="¿Qué cambió en tus costos operativos?",
                        label_visibility="collapsed",
                    )
                with _ps_c:
                    _penviar = st.button("Enviar", key="params_chat_send", type="primary", use_container_width=True)

                if _penviar and _pnuevo.strip():
                    with st.spinner(""):
                        _pr = fn_chat_parametros(st.session_state.params_wizard_chat, _pnuevo.strip())
                    _ia_accion_p = fn_interceptar_ia(_pr)
                    _p_aplic = False
                    if _ia_accion_p:
                        try:
                            _acp = _ia_accion_p["accion"]; _pd = _ia_accion_p["datos"]
                            if _acp == "actualizar_viaticos":
                                _pantes = (st.session_state.viaticos_custom or VIATICOS).copy()
                                st.session_state.viaticos_custom = _pd
                                fn_sp()["params_viaticos"] = _pd
                                st.session_state.params_cambios_aplicados.append({"tipo": "viaticos", "antes": _pantes, "despues": _pd})
                                try: fn_guardar_config("viaticos_custom", _pd)
                                except Exception: pass
                            elif _acp == "actualizar_tarifas":
                                _pantes = (st.session_state.tarifas_custom or TARIFAS).copy()
                                st.session_state.tarifas_custom = _pd
                                st.session_state.params_cambios_aplicados.append({"tipo": "tarifas", "antes": _pantes, "despues": _pd})
                                try: fn_guardar_config("tarifas_custom", _pd)
                                except Exception: pass
                            elif _acp == "actualizar_logistica":
                                _pantes = (st.session_state.logistica_custom or LOGISTICA).copy()
                                _logist_n = {**_pantes, **_pd}
                                st.session_state.logistica_custom = _logist_n
                                st.session_state.params_cambios_aplicados.append({"tipo": "logistica", "antes": _pantes, "despues": _logist_n})
                                try: fn_guardar_config("logistica_custom", _logist_n)
                                except Exception: pass
                            _p_aplic = True
                        except Exception:
                            pass
                    st.session_state.params_wizard_chat.append({"role": "user", "content": _pnuevo.strip()})
                    st.session_state.params_wizard_chat.append({"role": "assistant", "content": _pr, "aplicado": _p_aplic})
                    st.rerun()

                if st.session_state.params_wizard_chat:
                    if st.button("Limpiar conversación", key="params_clear"):
                        st.session_state.params_wizard_chat = []
                        st.rerun()

            with _col_vals:
                _tar_now = fn_get_tarifas()
                _via_now = fn_get_viaticos()
                _log_now = fn_get_logistica()

                if st.session_state.params_cambios_aplicados:
                    st.markdown(
                        "<div style='font-size:0.68rem;font-weight:700;opacity:0.4;letter-spacing:0.07em;"
                        "text-transform:uppercase;margin-bottom:8px'>Últimos cambios aplicados</div>",
                        unsafe_allow_html=True,
                    )
                    _ultimo_cambio = st.session_state.params_cambios_aplicados[-1]
                    _tipo_c  = _ultimo_cambio["tipo"]
                    _antes_c = _ultimo_cambio["antes"]
                    _despues_c = _ultimo_cambio["despues"]

                    if _tipo_c == "viaticos":
                        for _dk in ["pueblo", "ciudad"]:
                            if _dk in _antes_c and _dk in _despues_c:
                                for _sk in ["hospedaje", "alimentacion", "transporte_local"]:
                                    _va = _antes_c[_dk].get(_sk, 0) if isinstance(_antes_c[_dk], dict) else 0
                                    _vd = _despues_c[_dk].get(_sk, 0) if isinstance(_despues_c[_dk], dict) else 0
                                    if _va != _vd:
                                        _lbl_sk = {"hospedaje": "Hospedaje", "alimentacion": "Alimentación", "transporte_local": "Transporte"}
                                        st.markdown(
                                            f'<div class="cambio-row">'
                                            f'<span class="cambio-campo">{_lbl_sk.get(_sk, _sk)} ({_dk})</span>'
                                            f'<span class="cambio-antes">${int(_va):,}'.replace(",", ".") + '</span>'
                                            f'<span class="cambio-despues">${int(_vd):,}'.replace(",", ".") + '</span>'
                                            f'</div>',
                                            unsafe_allow_html=True,
                                        )
                    elif _tipo_c == "tarifas":
                        def _norm_tar_for_diff(tar_src: dict) -> dict:
                            _out = {}
                            for _m, _v in tar_src.items():
                                if isinstance(_v, list):
                                    _out[_m] = {r["nombre_interno"]: r["valor"] for r in _v}
                                elif isinstance(_v, dict):
                                    _out[_m] = _v
                            return _out
                        _antes_n   = _norm_tar_for_diff(_antes_c)
                        _despues_n = _norm_tar_for_diff(_despues_c)
                        for _mat in ["Mármol", "Granito", "Sinterizado", "Quarztone", "Quarzita"]:
                            if _mat in _antes_n and _mat in _despues_n:
                                _claves_union = set(_antes_n[_mat]) | set(_despues_n[_mat])
                                for _sk in sorted(_claves_union):
                                    _va = _antes_n[_mat].get(_sk, 0)
                                    _vd = _despues_n[_mat].get(_sk, 0)
                                    if _va != _vd:
                                        st.markdown(
                                            f'<div class="cambio-row">'
                                            f'<span class="cambio-campo">{_mat} — {_sk}</span>'
                                            f'<span class="cambio-antes">{_va}</span>'
                                            f'<span class="cambio-despues">{_vd}</span>'
                                            f'</div>',
                                            unsafe_allow_html=True,
                                        )

                    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

                st.markdown(
                    "<div style='font-size:0.68rem;font-weight:700;opacity:0.4;letter-spacing:0.07em;"
                    "text-transform:uppercase;margin-bottom:8px'>Valores actuales</div>",
                    unsafe_allow_html=True,
                )

                _gas = _log_now.get("gasolina", 16_000)
                st.markdown(
                    f'<div class="val-actual-row"><span class="val-label">Gasolina</span>'
                    f'<span class="val-num">${int(_gas):,}'.replace(",", ".") + '/gal</span></div>',
                    unsafe_allow_html=True,
                )

                _recetas_vivas = st.session_state.get("tar_recetas_edit", {})
                for _m in ["Mármol", "Granito", "Sinterizado", "Quarztone", "Quarzita"]:
                    _receta_m = _recetas_vivas.get(_m) or _tar_now.get(_m, {})
                    if isinstance(_receta_m, list):
                        _mo_reglas = [
                            r for r in _receta_m
                            if r.get("etiqueta_pdf") == "c2_mano_obra"
                            and r.get("inductor") in ("por_ml", "por_m2")
                        ]
                        _mo_regla = (
                            next((r for r in _mo_reglas if r.get("inductor") == "por_ml"), None)
                            or next(iter(_mo_reglas), None)
                        )
                        _pmo  = _mo_regla["valor"]   if _mo_regla else 0
                        _unid = _mo_regla["inductor"] if _mo_regla else "por_ml"
                    else:
                        _pmo  = _receta_m.get("prod_ml", 0)
                        _unid = "por_ml"
                    _unid_lbl = "ml" if _unid == "por_ml" else "m²"
                    if _pmo > 0:
                        st.markdown(
                            f'<div class="val-actual-row">'
                            f'<span class="val-label">Elaboración {_m}</span>'
                            f'<span class="val-num">'
                            + f'${int(_pmo):,}'.replace(",", ".")
                            + f'/{_unid_lbl}</span></div>',
                            unsafe_allow_html=True,
                        )

                _via_p   = _via_now.get("pueblo", {})
                _via_c   = _via_now.get("ciudad", {})
                _total_p = sum(_via_p.values()) if isinstance(_via_p, dict) else _via_p
                _total_c = sum(_via_c.values()) if isinstance(_via_c, dict) else _via_c
                st.markdown(
                    f'<div class="val-actual-row"><span class="val-label">Viáticos pueblo</span>'
                    f'<span class="val-num">${int(_total_p):,}'.replace(",", ".") + '/día</span></div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div class="val-actual-row"><span class="val-label">Viáticos ciudad</span>'
                    f'<span class="val-num">${int(_total_c):,}'.replace(",", ".") + '/día</span></div>',
                    unsafe_allow_html=True,
                )

                _aiu_u = float(
                    fn_sp().get("aiu_u_pct",
                        (st.session_state.get("aiu_custom") or {}).get("utilidad", 5.0)
                    )
                )
                st.markdown(
                    f'<div class="val-actual-row"><span class="val-label">Utilidad esperada</span>'
                    f'<span class="val-num">{_aiu_u:.1f} %</span></div>',
                    unsafe_allow_html=True,
                )

                _cif_display = None
                for _mat_cif in ["Granito", "Mármol", "Sinterizado", "Quarztone", "Quarzita"]:
                    _tar_cif = _tar_now.get(_mat_cif, {})
                    if isinstance(_tar_cif, list):
                        _r = next(
                            (r["valor"] for r in _tar_cif
                             if "Servicios" in r.get("nombre_interno", "")
                             or "Luz" in r.get("nombre_interno", "")),
                            None,
                        )
                        if _r is not None:
                            _cif_display = float(_r)
                            break
                if _cif_display is None:
                    _cif_display = st.session_state.get("wiz_cif_por_m2")
                if _cif_display is not None:
                    st.markdown(
                        f'<div class="val-actual-row">'
                        f'<span class="val-label">Gastos Fijos (Luz/Agua)</span>'
                        f'<span class="val-num">${int(_cif_display):,}'.replace(",", ".") + '/m²</span></div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<div class="val-actual-row">'
                        '<span class="val-label">Gastos Fijos (Luz/Agua)</span>'
                        '<span class="val-num" style="opacity:0.45;font-style:italic">Configura en Tarifas</span></div>',
                        unsafe_allow_html=True,
                    )

                _tiene_custom = any([
                    st.session_state.tarifas_custom,
                    st.session_state.logistica_custom,
                    st.session_state.viaticos_custom,
                ])
                if _tiene_custom:
                    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
                    st.markdown(
                        '<div style="font-size:0.75rem;background:#dcfce7;color:#15803d;'
                        'border-radius:6px;padding:6px 10px;font-weight:600">'
                        'Tienes valores personalizados activos</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
                    st.markdown(
                        '<div style="font-size:0.75rem;opacity:0.45;font-style:italic">'
                        'Usando valores por defecto del sistema</div>',
                        unsafe_allow_html=True,
                    )

    # ─────────────────────────────────────────────────────────────────────────
    # TAB: 📊 TARIFAS Y PRODUCCIÓN
    # ─────────────────────────────────────────────────────────────────────────
    with t_tar:

        # ── Adaptador de retrocompatibilidad ─────────────────────────────────
        from calculos import calcular_cotizacion_directa as _ccd_dummy  # noqa
        import calculos as _calculos_mod

        def _tar_a_receta_ui(tar_dict: dict) -> list:
            """Convierte formato plano legacy a lista de reglas para la UI."""
            return [
                {"nombre_interno": "Mano obra borde",       "inductor": "por_ml",              "valor": float(tar_dict.get("prod_ml",       60_000)), "etiqueta_pdf": "c2_mano_obra"},
                {"nombre_interno": "Mano obra área",         "inductor": "por_m2",              "valor": float(tar_dict.get("prod_m2",       35_000)), "etiqueta_pdf": "c2_mano_obra"},
                {"nombre_interno": "Instalación zócalo",     "inductor": "por_ml_zocalo",       "valor": float(tar_dict.get("zocalo",        12_000)), "etiqueta_pdf": "c3_zocalos"},
                {"nombre_interno": "Desgaste disco",         "inductor": "por_m2",              "valor": float(tar_dict.get("disco",          2_200)), "etiqueta_pdf": "c4_insumos"},
                {"nombre_interno": "Uso máquina cortadora",  "inductor": "por_dia",             "valor": float(tar_dict.get("maquina",       20_000)), "etiqueta_pdf": "c4_insumos"},
                {"nombre_interno": "Consumibles",            "inductor": "por_m2",              "valor": float(tar_dict.get("consumibles",    8_500)), "etiqueta_pdf": "c4_insumos"},
                {"nombre_interno": "Seguro contra Roturas",  "inductor": "porcentaje_material", "valor": float(tar_dict.get("riesgo_rotura", 0.02)), "etiqueta_pdf": "c4_insumos"},
            ]

        def _resolver_receta_ui(entry) -> list:
            if isinstance(entry, list):
                return [dict(r) for r in entry]
            if isinstance(entry, dict):
                return _tar_a_receta_ui(entry)
            return _tar_a_receta_ui({})

        _INDUCTORES     = ["por_ml", "por_m2", "por_dia", "porcentaje_material", "por_ml_zocalo"]
        _ETIQUETAS_PDF  = ["c2_mano_obra", "c3_zocalos", "c4_insumos"]
        _INDUCTOR_LABEL = {
            "por_ml":              "por ML (borde)",
            "por_m2":              "por m² (área)",
            "por_dia":             "por día de obra",
            "porcentaje_material": "% del material",
            "por_ml_zocalo":       "por ML de zócalo",
        }
        _PDF_LABEL = {
            "c2_mano_obra": "② Mano de obra",
            "c3_zocalos":   "③ Zócalos",
            "c4_insumos":   "④ Insumos",
        }
        _CAT_LABEL = {
            "c2_mano_obra": "👷 Mano de Obra y Elaboración",
            "c3_zocalos":   "📏 Zócalos y Remates",
            "c4_insumos":   "💎 Insumos, Servicios y Riesgos",
        }
        _MAT_ICONS = {"Mármol": "🪨", "Granito": "🟫", "Sinterizado": "⬜", "Quarztone": "🔵", "Quarzita": "🟡"}
        _SS_KEY    = "tar_recetas_edit"

        if "paso_wizard" not in st.session_state:
            st.session_state.paso_wizard = 1

        # ─── RAMA A — WIZARD DE CONFIGURACIÓN INICIAL ────────────────────────
        if not st.session_state.get("setup_tarifas_completado", False):

            st.markdown("""
            <style>
            .wiz-wrap {
                max-width: 580px;
                margin: 32px auto 0;
                font-family: "Inter", "Segoe UI", sans-serif;
            }
            .wiz-step-label {
                font-size: 0.72rem;
                font-weight: 700;
                letter-spacing: 0.1em;
                text-transform: uppercase;
                opacity: 0.45;
                margin-bottom: 6px;
            }
            .wiz-title {
                font-size: 1.35rem;
                font-weight: 800;
                line-height: 1.3;
                margin-bottom: 6px;
            }
            .wiz-subtitle {
                font-size: 0.88rem;
                opacity: 0.55;
                margin-bottom: 28px;
            }
            .wiz-progress-track {
                height: 4px;
                background: var(--secondary-background-color);
                border-radius: 99px;
                margin-bottom: 32px;
                overflow: hidden;
            }
            .wiz-progress-fill {
                height: 100%;
                border-radius: 99px;
                background: linear-gradient(90deg, #1B5FA8, #3B82F6);
                transition: width 0.4s ease;
            }
            .wiz-done-box {
                background: linear-gradient(135deg, #f0f7ff 0%, #e8f5e9 100%);
                border: 1px solid #b3d4f5;
                border-radius: 14px;
                padding: 32px 28px;
                text-align: center;
                margin-top: 12px;
            }
            .wiz-done-icon  { font-size: 2.8rem; margin-bottom: 8px; }
            .wiz-done-title { font-size: 1.25rem; font-weight: 800; margin-bottom: 6px; }
            .wiz-done-sub   { font-size: 0.86rem; opacity: 0.6; }
            </style>
            """, unsafe_allow_html=True)

            _pct = {1: 15, 2: 50, 3: 82}.get(st.session_state.paso_wizard, 100)
            st.markdown(
                f'''<div class="wiz-wrap">
                  <div class="wiz-step-label">Configuración inicial · Paso {st.session_state.paso_wizard} de 3</div>
                  <div class="wiz-progress-track">
                    <div class="wiz-progress-fill" style="width:{_pct}%"></div>
                  </div>
                </div>''',
                unsafe_allow_html=True,
            )

            _, _wc, _ = st.columns([1, 2.8, 1])

            with _wc:

                # ── PASO 1 ────────────────────────────────────────────────────
                if st.session_state.paso_wizard == 1:
                    st.markdown("### ¿Cómo le pagas a tus instaladores/operarios?")
                    st.caption("Esto determina cómo le cobramos la instalación al cliente en cada cotización.")
                    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

                    _b1, _b2 = st.columns(2)
                    with _b1:
                        st.markdown("""
                        <div style="background:var(--secondary-background-color);border:2px solid #1B5FA8;
                                    border-radius:12px;padding:20px 16px;text-align:center;cursor:pointer">
                            <div style="font-size:1.8rem;margin-bottom:6px">📏</div>
                            <div style="font-weight:700;font-size:0.9rem">Por Metro Lineal</div>
                            <div style="font-size:0.75rem;opacity:0.55;margin-top:4px">Recomendado para mesones</div>
                        </div>""", unsafe_allow_html=True)
                        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
                        if st.button(
                            "Elegir → Metro Lineal",
                            key="wiz_btn_ml",
                            use_container_width=True,
                            type="primary",
                            help="Se cobra por cada metro lineal físico de borde cortado e instalado. "
                                 "Los zócalos también se cobran por ML de tira añadida a las piezas.",
                        ):
                            st.session_state.wiz_inductor_mo = "por_ml"
                            st.session_state.paso_wizard     = 2
                            st.rerun()

                    with _b2:
                        st.markdown("""
                        <div style="background:var(--secondary-background-color);border:2px solid var(--border-color);
                                    border-radius:12px;padding:20px 16px;text-align:center;cursor:pointer">
                            <div style="font-size:1.8rem;margin-bottom:6px">⬛</div>
                            <div style="font-weight:700;font-size:0.9rem">Por Metro Cuadrado</div>
                            <div style="font-size:0.75rem;opacity:0.55;margin-top:4px">Recomendado para pisos</div>
                        </div>""", unsafe_allow_html=True)
                        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
                        if st.button(
                            "Elegir → Metro Cuadrado",
                            key="wiz_btn_m2",
                            use_container_width=True,
                            help="Se cobra por cada m² de superficie elaborada. "
                                 "Ideal para pisos, fachadas y proyectos con área predominante.",
                        ):
                            st.session_state.wiz_inductor_mo = "por_m2"
                            st.session_state.paso_wizard     = 2
                            st.rerun()

                # ── PASO 2 ────────────────────────────────────────────────────
                elif st.session_state.paso_wizard == 2:
                    _ind_elegido = st.session_state.get("wiz_inductor_mo", "por_ml")
                    _unidad_lbl  = "metro lineal (ML)" if _ind_elegido == "por_ml" else "metro cuadrado (m²)"

                    st.markdown(f"### ¿Cuánto pagas por ese {_unidad_lbl}?")
                    st.caption("Este valor es el costo de mano de obra que le pagas a tus operarios — sin incluir materiales ni logística.")
                    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

                    _wiz_val = st.number_input(
                        f"Valor por {_unidad_lbl} (COP)",
                        min_value=0.0,
                        max_value=500_000.0,
                        value=float(st.session_state.get("wiz_valor_mo", 60_000.0)),
                        step=1_000.0,
                        format="%.0f",
                        key="wiz_input_valor_mo",
                        help="Promedio Barranquilla 2026: $50.000–$80.000/ML para mesones de mármol",
                    )

                    if _wiz_val < 30_000:
                        st.warning("Parece muy bajo. El mínimo típico en Barranquilla es $30.000/ML.", icon="⚠️")
                    elif _wiz_val > 150_000:
                        st.info("Valor alto. Asegúrate de que incluya solo mano de obra, no materiales.", icon="ℹ️")

                    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
                    _nav1, _nav2 = st.columns([1, 2])
                    with _nav1:
                        if st.button("← Atrás", key="wiz_back_2", use_container_width=True):
                            st.session_state.paso_wizard = 1
                            st.rerun()
                    with _nav2:
                        if st.button("Siguiente →", key="wiz_next_2", use_container_width=True, type="primary"):
                            st.session_state.wiz_valor_mo = float(_wiz_val)
                            st.session_state.paso_wizard  = 3
                            st.rerun()

                # ── PASO 3 ────────────────────────────────────────────────────
                elif st.session_state.paso_wizard == 3:
                    st.markdown("### 💡 Para calcular exactamente cuánto te cuesta la luz y el agua por proyecto, dinos:")
                    st.caption(
                        "Muchos talleres pierden dinero porque nunca incluyen los servicios públicos "
                        "en el presupuesto. Esta calculadora lo hace por ti, con tu cifra real."
                    )
                    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

                    _wiz_recibo = st.number_input(
                        "1. ¿Cuánto pagas de Luz y Agua al mes? ($ COP)",
                        min_value=0.0,
                        max_value=50_000_000.0,
                        value=float(st.session_state.get("wiz_recibo_servicios", 1_000_000.0)),
                        step=50_000.0,
                        format="%.0f",
                        key="wiz_input_recibo",
                        help=(
                            "Suma el recibo de energía más acueducto del taller. "
                            "Si el taller comparte medidor con la vivienda, ingresa "
                            "solo la parte proporcional que usa la producción."
                        ),
                    )

                    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

                    _OPT_M2 = "Metros Cuadrados (m²)"
                    _OPT_ML = "Metros Lineales (ml — Mesones estándar)"
                    _unidad_prev = st.session_state.get("wiz_unidad_produccion", _OPT_M2)
                    _unidad_sel  = st.radio(
                        "¿Cómo mides tu producción?",
                        [_OPT_M2, _OPT_ML],
                        index=0 if _unidad_prev == _OPT_M2 else 1,
                        horizontal=True,
                        key="wiz_radio_unidad",
                        help=(
                            "Elige la unidad que usas habitualmente. "
                            "Si mides en ML de borde cortado (mesones), "
                            "el sistema convierte a m² automáticamente."
                        ),
                    )

                    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

                    if _unidad_sel == _OPT_M2:
                        _input_produccion = st.number_input(
                            "2. ¿Cuántos m² procesa tu taller al mes aprox.?",
                            min_value=1.0,
                            max_value=10_000.0,
                            value=float(st.session_state.get("wiz_m2_mes_taller", 100.0)),
                            step=5.0,
                            format="%.0f",
                            key="wiz_input_produccion_m2",
                            help=(
                                "Promedio mensual de m² de piedra elaborada y entregada. "
                                "Una estimación conservadora es mejor que dejarla en cero."
                            ),
                        )
                        _wiz_m2_mes = _input_produccion
                    else:
                        _ANCHO_MESON_M = 0.60
                        _input_produccion = st.number_input(
                            "2. ¿Cuántos ml procesa tu taller al mes aprox.?",
                            min_value=1.0,
                            max_value=50_000.0,
                            value=float(st.session_state.get("wiz_ml_mes_taller", 167.0)),
                            step=10.0,
                            format="%.0f",
                            key="wiz_input_produccion_ml",
                            help=(
                                "Metros lineales totales de borde cortado e instalado al mes. "
                                "Ej: 10 mesones de 2 m = 20 ML. "
                                "El sistema convierte a m² asumiendo 60 cm de ancho estándar."
                            ),
                        )
                        _wiz_m2_mes = _input_produccion * _ANCHO_MESON_M
                        st.caption(
                            f"ℹ️ Equivale a **{_wiz_m2_mes:,.1f} m²** "
                            f"asumiendo un ancho estándar de 60 cm por mesón."
                        )

                    _m2_mes_seguro = max(_wiz_m2_mes, 1.0)
                    _cif_por_m2    = _wiz_recibo / _m2_mes_seguro

                    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
                    st.info(
                        f"**Gastos fijos del taller (Luz y Agua): "
                        f"${_cif_por_m2:,.0f} COP por metro cuadrado.** "
                        f"Este monto se añadirá automáticamente a tu receta de costos.",
                        icon="💡",
                    )

                    if _cif_por_m2 > 30_000:
                        st.warning(
                            "El gasto por m² supera $30.000 — parece demasiado alto. "
                            "Revisa que el recibo sea solo del taller y que "
                            "la producción mensual no esté subestimada.",
                            icon="⚠️",
                        )
                    elif _wiz_recibo > 0 and _cif_por_m2 < 500:
                        st.info(
                            "El gasto por m² es menor a $500 — puede que la producción "
                            "mensual esté sobreestimada o el recibo subestimado.",
                            icon="ℹ️",
                        )

                    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
                    st.divider()
                    st.markdown("#### 🛠️ ¿Quién compra los materiales de trabajo?")
                    st.caption(
                        "Lijas, discos, pegante y masilla no son lo mismo que la luz o el agua. "
                        "Dinos quién los paga en tu taller."
                    )

                    _POL_TALLER   = "El Taller los compra"
                    _POL_OPERARIO = "El Operario los trae"
                    _pol_prev = st.session_state.get("wiz_politica_insumos", _POL_TALLER)
                    _pol_idx  = 0 if _pol_prev == _POL_TALLER else 1

                    _wiz_politica = st.radio(
                        "¿Quién compra los materiales de trabajo (lijas, discos, pegante)?",
                        [_POL_TALLER, _POL_OPERARIO],
                        index=_pol_idx,
                        key="wiz_radio_politica_insumos",
                        help=(
                            "**El Taller los compra:** se suma una regla de Consumibles "
                            "a la receta para que quede reflejado en el presupuesto. "
                            "**El Operario los trae:** ya está cubierto en el valor de "
                            "mano de obra que pusiste en el Paso 2."
                        ),
                    )

                    if _wiz_politica == _POL_TALLER:
                        st.success(
                            "Se añadirá **\"Consumibles Directos (Discos, Lijas, Pegante)\"** "
                            "con $15.000/m² a tu receta. Podrás ajustar ese valor después.",
                            icon="🛠️",
                        )
                    else:
                        st.info(
                            "No se agrega ningún costo extra. "
                            "El valor que pusiste en el Paso 2 ya cubre esos materiales.",
                            icon="ℹ️",
                        )

                    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
                    _nav3a, _nav3b = st.columns([1, 2])
                    with _nav3a:
                        if st.button("← Atrás", key="wiz_back_3", use_container_width=True):
                            st.session_state.paso_wizard = 2
                            st.rerun()
                    with _nav3b:
                        if st.button("Siguiente →", key="wiz_next_3", use_container_width=True, type="primary"):
                            st.session_state.wiz_recibo_servicios  = float(_wiz_recibo)
                            st.session_state.wiz_m2_mes_taller     = float(_wiz_m2_mes)
                            st.session_state.wiz_unidad_produccion = _unidad_sel
                            if _unidad_sel == _OPT_ML:
                                st.session_state.wiz_ml_mes_taller = float(_input_produccion)
                            st.session_state.wiz_cif_por_m2        = round(_cif_por_m2, 2)
                            st.session_state.wiz_insumos           = True
                            st.session_state.wiz_politica_insumos  = _wiz_politica
                            st.session_state.paso_wizard           = 4
                            st.rerun()

                # ── PASO 4: CIERRE ────────────────────────────────────────────
                elif st.session_state.paso_wizard == 4:
                    st.markdown("""
                    <div class="wiz-done-box">
                        <div class="wiz-done-icon">🎉</div>
                        <div class="wiz-done-title">¡Configuración lista!</div>
                        <div class="wiz-done-sub">Construyendo tu primera receta de costos…</div>
                    </div>""", unsafe_allow_html=True)

                    _ind_mo  = st.session_state.get("wiz_inductor_mo", "por_ml")
                    _val_mo  = float(st.session_state.get("wiz_valor_mo", 60_000.0))
                    _insumos = st.session_state.get("wiz_insumos", True)
                    _nom_mo  = "Elaboración e Instalación"

                    _receta_base: list = [
                        {"nombre_interno": _nom_mo,              "inductor": _ind_mo,          "valor": _val_mo,   "etiqueta_pdf": "c2_mano_obra"},
                        {"nombre_interno": "Instalación zócalo", "inductor": "por_ml_zocalo",  "valor": 12_000.0,  "etiqueta_pdf": "c3_zocalos"},
                    ]

                    _cif_inyectado = float(st.session_state.get("wiz_cif_por_m2", 3_000.0))
                    _receta_base += [
                        {"nombre_interno": "Servicios de Taller (Luz y Agua)", "inductor": "por_m2", "valor": _cif_inyectado, "etiqueta_pdf": "c4_insumos"},
                    ]

                    _POL_TALLER_4 = "El Taller los compra"
                    _politica_insumos = st.session_state.get("wiz_politica_insumos", _POL_TALLER_4)
                    if _politica_insumos == _POL_TALLER_4:
                        _receta_base += [
                            {"nombre_interno": "Consumibles Directos (Discos, Lijas, Pegante)", "inductor": "por_m2", "valor": 15_000.0, "etiqueta_pdf": "c4_insumos"},
                        ]

                    def _riesgo_rotura(_mat: str) -> float:
                        if _mat == "Sinterizado":
                            return 0.05
                        if _mat in ("Mármol", "Quarztone"):
                            return 0.03
                        return 0.02

                    _recetas_por_mat: dict = {}
                    for _m in ["Mármol", "Granito", "Sinterizado", "Quarztone", "Quarzita"]:
                        _receta_m = [dict(r) for r in _receta_base]
                        _receta_m.append({
                            "nombre_interno": "Seguro contra Roturas",
                            "inductor":       "porcentaje_material",
                            "valor":          _riesgo_rotura(_m),
                            "etiqueta_pdf":   "c4_insumos",
                        })
                        _recetas_por_mat[_m] = _receta_m
                    st.session_state[_SS_KEY] = _recetas_por_mat

                    st.session_state.setup_tarifas_completado = True
                    st.session_state.paso_wizard              = 1
                    st.rerun()

        # ─── RAMA B — VISUAL BUILDER COMPLETO ────────────────────────────────
        else:
            st.caption("Constructor visual de costos por material. Cada fila es una regla de costo que el motor aplica automáticamente al calcular. Agrega, edita o elimina reglas y presiona **Guardar Tarifas**.")

            with st.expander("🔄 ¿Quieres reconfigurar desde cero?", expanded=False):
                st.caption("Esto borrará la receta actual del editor (no las tarifas guardadas en BD) y te llevará al wizard de configuración inicial.")
                if st.button("↺ Volver al asistente de configuración", key="btn_reset_wizard", use_container_width=True):
                    st.session_state.setup_tarifas_completado = False
                    st.session_state.paso_wizard              = 1
                    st.session_state.pop(_SS_KEY, None)
                    st.rerun()

            with st.expander("📖 ¿Cómo funciona este constructor?", expanded=False):
                st.markdown("""
Cada material tiene una **lista de gastos**. El sistema los suma automáticamente al armar el presupuesto.

| Columna | ¿Qué defines aquí? | Ejemplo |
|---|---|---|
| **Concepto** | El nombre del gasto — solo para identificarlo | "Mano de obra borde", "Disco diamantado" |
| **¿Cómo se cobra?** | La forma en que se multiplica ese gasto | `por_ml` → multiplica por metros lineales cortados |
| **Valor** | El monto en COP (o porcentaje para %) | `60000` = $60.000/ml · `0.02` = 2% del material |
| **Tipo de Gasto** | Dónde aparece en el desglose del PDF | Mano de Obra, Zócalos, o Gastos Fijos y Consumibles |

**Formas de cobro disponibles:**
- `por_ml` — por cada metro lineal de borde cortado (mesones, escaleras)
- `por_m2` — por cada m² de superficie elaborada (pisos, fachadas, disco)
- `por_dia` — monto fijo por día de obra (máquina cortadora, arriendo de equipos)
- `porcentaje_material` — porcentaje del costo del material (seguro contra roturas)
- `por_ml_zocalo` — por metro lineal de zócalo instalado

**💡 Tip:** Puedes agregar gastos personalizados como "Transporte de equipos especiales por día" sin tocar ningún otro archivo.
                """)

            tar_act = fn_get_tarifas()

            if _SS_KEY not in st.session_state:
                st.session_state[_SS_KEY] = {}
            for _mat in ["Mármol", "Granito", "Sinterizado", "Quarztone", "Quarzita"]:
                _entry = tar_act.get(_mat, {})
                if _mat not in st.session_state[_SS_KEY]:
                    st.session_state[_SS_KEY][_mat] = _resolver_receta_ui(_entry)

            for _mat in ["Mármol", "Granito", "Sinterizado", "Quarztone", "Quarzita"]:
                _receta = st.session_state[_SS_KEY][_mat]

                with st.container(border=True):
                    _ch1, _ch2 = st.columns([5, 1])
                    _ch1.markdown(f"**{_MAT_ICONS.get(_mat, '')} {_mat}** — {len(_receta)} regla{'s' if len(_receta) != 1 else ''}")

                    _hc1, _hc2, _hc3, _hc4, _hc5 = st.columns([3, 2, 1.4, 2, 0.6])
                    _header_cfg = [
                        (_hc1, "Concepto",        "Nombre descriptivo del costo. Solo para identificarlo — no afecta el cálculo."),
                        (_hc2, "¿Cómo se cobra?", "Base matemática del cálculo: por ML de borde, por m² de área, por día de obra, etc."),
                        (_hc3, "Valor",            "Monto en COP (ej: 60000) o porcentaje expresado como número entero (ej: 2 = 2%)."),
                        (_hc4, "Tipo de Gasto",    "¿A qué grupo pertenece este costo? Mano de Obra, Zócalos y Remates, o Gastos Fijos y Consumibles."),
                        (_hc5, "",                 ""),
                    ]
                    for _hcol, _hlbl, _hhelp in _header_cfg:
                        _hcol.markdown(
                            f"<div style='font-size:0.68rem;font-weight:700;text-transform:uppercase;"
                            f"letter-spacing:0.07em;opacity:0.5;padding-bottom:2px' "
                            f"title='{_hhelp}'>{_hlbl}</div>",
                            unsafe_allow_html=True,
                        )

                    _indices_a_borrar = []
                    for _ri, _regla in enumerate(_receta):
                        _rc1, _rc2, _rc3, _rc4, _rc5 = st.columns([3, 2, 1.4, 2, 0.6])

                        _nom_key    = f"trec_nom_{_mat}_{_ri}"
                        _nom_actual = _regla.get("nombre_interno", "")
                        _nom_help   = (
                            "Se cobra por cada metro lineal físico de tira de zócalo o "
                            "salpicadero añadido a las piezas."
                            if "zócalo" in _nom_actual.lower() or "zocalo" in _nom_actual.lower()
                            else "Nombre descriptivo del costo — no afecta el cálculo."
                        )
                        _regla["nombre_interno"] = _rc1.text_input(
                            "Concepto",
                            value=_nom_actual,
                            key=_nom_key,
                            label_visibility="collapsed",
                            placeholder="Ej: Elaboración e Instalación",
                            help=_nom_help,
                        )

                        _ind_key = f"trec_ind_{_mat}_{_ri}"
                        _ind_cur = _regla.get("inductor", "por_ml")
                        _ind_idx = _INDUCTORES.index(_ind_cur) if _ind_cur in _INDUCTORES else 0
                        _ind_sel = _rc2.selectbox(
                            "Forma de cobro", _INDUCTORES, index=_ind_idx,
                            key=_ind_key, label_visibility="collapsed",
                            format_func=lambda x: _INDUCTOR_LABEL.get(x, x),
                        )
                        _regla["inductor"] = _ind_sel

                        _val_key    = f"trec_val_{_mat}_{_ri}"
                        _es_pct     = (_ind_sel == "porcentaje_material")
                        _val_stored = float(_regla.get("valor", 0.0))
                        if _es_pct:
                            _val_display = round(_val_stored * 100, 4)
                            _val_ui = _rc3.number_input(
                                "% (Ej. 2.0)",
                                value=max(0.0, _val_display),
                                min_value=0.0,
                                max_value=100.0,
                                step=0.5,
                                format="%.1f",
                                key=_val_key,
                                label_visibility="collapsed",
                                help="Porcentaje del costo del material. Ej: 2.0 = 2%. Se aplica sobre el subtotal de material.",
                            )
                            _regla["valor"] = round(_val_ui / 100.0, 6)
                        else:
                            _val_ui = _rc3.number_input(
                                "$ COP",
                                value=float(max(0.0, _val_stored)),
                                min_value=0.0,
                                step=1_000.0,
                                format="%.0f",
                                key=_val_key,
                                label_visibility="collapsed",
                                help="Monto en pesos colombianos. Ej: 60000 = $60.000.",
                            )
                            _regla["valor"] = float(_val_ui)

                        _pdf_key = f"trec_pdf_{_mat}_{_ri}"
                        _pdf_cur = _regla.get("etiqueta_pdf", "c4_insumos")
                        _pdf_idx = _ETIQUETAS_PDF.index(_pdf_cur) if _pdf_cur in _ETIQUETAS_PDF else 2
                        _regla["etiqueta_pdf"] = _rc4.selectbox(
                            "Categoría",
                            _ETIQUETAS_PDF,
                            index=_pdf_idx,
                            key=_pdf_key,
                            label_visibility="collapsed",
                            format_func=lambda x: _CAT_LABEL.get(x, _PDF_LABEL.get(x, x)),
                            help="¿A qué tipo de gasto pertenece? (Mano de Obra, Zócalos, Gastos Fijos)",
                        )

                        _rc5.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
                        if _rc5.button("🗑", key=f"trec_del_{_mat}_{_ri}", help="Eliminar esta regla"):
                            _indices_a_borrar.append(_ri)

                    for _bi in sorted(_indices_a_borrar, reverse=True):
                        st.session_state[_SS_KEY][_mat].pop(_bi)
                    if _indices_a_borrar:
                        st.rerun()

                    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
                    if st.button(
                        f"＋ Agregar costo a {_mat}",
                        key=f"trec_add_{_mat}",
                        use_container_width=True,
                        help="Inserta una nueva regla de costo vacía para este material",
                    ):
                        st.session_state[_SS_KEY][_mat].append({
                            "nombre_interno": "",
                            "inductor":       "por_m2",
                            "valor":          0.0,
                            "etiqueta_pdf":   "c4_insumos",
                        })
                        st.rerun()

            st.markdown("")
            _col_save_tar, _col_reset_tar = st.columns([3, 1])
            if _col_save_tar.button("💾 Guardar Tarifas", type="primary", key="btn_save_tar", use_container_width=True):
                _saved_tar = {}
                for _sm in ["Mármol", "Granito", "Sinterizado", "Quarztone", "Quarzita"]:
                    _receta_guardada = []
                    for _ri, _regla_base in enumerate(st.session_state[_SS_KEY].get(_sm, [])):
                        _ind_w = st.session_state.get(f"trec_ind_{_sm}_{_ri}", _regla_base.get("inductor", "por_ml"))
                        _val_w = st.session_state.get(f"trec_val_{_sm}_{_ri}", _regla_base.get("valor", 0.0))
                        if _ind_w == "porcentaje_material":
                            _val_final = round(float(_val_w) / 100.0, 6)
                        else:
                            _val_final = float(_val_w)
                        _receta_guardada.append({
                            "nombre_interno": st.session_state.get(f"trec_nom_{_sm}_{_ri}", _regla_base.get("nombre_interno", "")),
                            "inductor":       _ind_w,
                            "valor":          _val_final,
                            "etiqueta_pdf":   st.session_state.get(f"trec_pdf_{_sm}_{_ri}", _regla_base.get("etiqueta_pdf", "c4_insumos")),
                        })
                    _saved_tar[_sm] = _receta_guardada

                st.session_state.tarifas_custom        = _saved_tar
                st.session_state.setup_tarifas_completado = True
                fn_sp()["params_tarifas"] = _saved_tar
                _bd_ok = False
                try:
                    fn_guardar_config("tarifas_custom", _saved_tar)
                    _bd_ok = True
                except Exception as _e_save:
                    st.warning(
                        f"Las tarifas se aplicaron en esta sesión, pero no pudieron "
                        f"guardarse en la base de datos ({type(_e_save).__name__}). "
                        f"Verifica la conexión a Supabase.",
                        icon="⚠️",
                    )
                st.session_state.pop(_SS_KEY, None)
                if _bd_ok:
                    st.toast("✅ Tarifas guardadas y persistidas correctamente", icon="💾")
                else:
                    st.toast("⚠️ Aplicadas en sesión — sin persistencia en BD", icon="⚠️")
                st.rerun()

            if _col_reset_tar.button("↺ Restaurar", key="btn_reset_tar", use_container_width=True,
                                      help="Vuelve a los valores por defecto de fábrica"):
                st.session_state.tarifas_custom           = None
                st.session_state.setup_tarifas_completado = False
                st.session_state.paso_wizard              = 1
                fn_sp()["params_tarifas"] = None
                try:
                    fn_guardar_config("tarifas_custom", None)
                except Exception:
                    pass
                st.session_state.pop(_SS_KEY, None)
                st.toast("↺ Tarifas restauradas a valores por defecto", icon="🔄")
                st.rerun()

    # ─────────────────────────────────────────────────────────────────────────
    # TAB: 🚗 VIÁTICOS
    # ─────────────────────────────────────────────────────────────────────────
    with t_via:
        st.caption("Costos de desplazamiento para proyectos fuera de Barranquilla. Modifica y presiona **Guardar Viáticos**.")

        with st.expander("📖 ¿Para qué sirven los viáticos?", expanded=False):
            st.markdown("""
Los **viáticos** son los gastos que tiene el equipo cuando el proyecto es fuera de Barranquilla y deben quedarse a dormir.

La app los suma automáticamente al costo del proyecto cuando activas la opción **"Proyecto fuera de la ciudad"** en la cotización.

Hay dos destinos:
- **Pueblo / Corregimiento:** zonas rurales o municipios pequeños (hospedaje más económico)
- **Ciudad Capital:** Bogotá, Medellín, Cartagena, Santa Marta, etc. (hospedaje más costoso)

Cada destino tiene tres componentes:

| Campo | ¿Qué cubre? | Ejemplo Barranquilla 2026 |
|---|---|---|
| **Hospedaje** | Una noche de alojamiento por persona | $60.000–$90.000/noche |
| **Alimentación** | Desayuno + almuerzo + cena por persona | $65.000–$70.000/día |
| **Transporte local** | Movilidad dentro del destino (moto, taxi, buseta) | $20.000/día |

La app multiplica estos valores por el número de personas y noches que configures en la cotización.

**Ejemplo:** 2 operarios, 3 noches en pueblo = 2 × 3 × ($60.000 + $65.000 + $20.000) = **$870.000**
            """)

        via_act = fn_get_viaticos()

        def _normalizar_via(key):
            v = via_act.get(key, {})
            if isinstance(v, dict):
                return v
            return {"hospedaje": int(v * 0.41), "alimentacion": int(v * 0.45), "transporte_local": int(v * 0.14)}

        via_edit = {}
        for _dest_key, _dest_label, _dest_icon in [
            ("pueblo", "Pueblo / Corregimiento", "🏘️"),
            ("ciudad", "Ciudad Capital",          "🏙️"),
        ]:
            _vd = _normalizar_via(_dest_key)
            with st.container(border=True):
                st.markdown(f"**{_dest_icon} {_dest_label}**")
                _va, _vb, _vc = st.columns(3)
                _hosp = _va.number_input(
                    "Hospedaje (COP/noche)", min_value=0,
                    value=int(_vd.get("hospedaje", 60_000)), step=1_000, format="%d",
                    key=f"via_{_dest_key}_hosp",
                    help="Costo de alojamiento por persona por noche.")
                _alim = _vb.number_input(
                    "Alimentación (COP/día)", min_value=0,
                    value=int(_vd.get("alimentacion", 65_000)), step=1_000, format="%d",
                    key=f"via_{_dest_key}_alim",
                    help="Desayuno + almuerzo + cena por persona.")
                _tran = _vc.number_input(
                    "Transporte local (COP/día)", min_value=0,
                    value=int(_vd.get("transporte_local", 20_000)), step=500, format="%d",
                    key=f"via_{_dest_key}_tran",
                    help="Movilidad local: moto, taxi o buseta.")
                _total_via = _hosp + _alim + _tran
                st.caption(f"Total diario por persona: **{fn_numero_completo(_total_via)}**")
                via_edit[_dest_key] = {"hospedaje": _hosp, "alimentacion": _alim, "transporte_local": _tran}

        st.markdown("")
        _col_save_via, _col_reset_via = st.columns([3, 1])
        if _col_save_via.button("💾 Guardar Viáticos", type="primary", key="btn_save_via", use_container_width=True):
            _saved_via = {
                "pueblo": {
                    "hospedaje":        int(st.session_state.get("via_pueblo_hosp", 60_000)),
                    "alimentacion":     int(st.session_state.get("via_pueblo_alim", 65_000)),
                    "transporte_local": int(st.session_state.get("via_pueblo_tran", 20_000)),
                },
                "ciudad": {
                    "hospedaje":        int(st.session_state.get("via_ciudad_hosp", 90_000)),
                    "alimentacion":     int(st.session_state.get("via_ciudad_alim", 68_000)),
                    "transporte_local": int(st.session_state.get("via_ciudad_tran", 20_000)),
                },
            }
            fn_sp()["params_viaticos"] = _saved_via
            st.session_state.viaticos_custom = _saved_via
            try:
                fn_guardar_config("viaticos_custom", _saved_via)
            except Exception:
                pass
            for _vk in ["via_pueblo_hosp", "via_pueblo_alim", "via_pueblo_tran",
                        "via_ciudad_hosp", "via_ciudad_alim", "via_ciudad_tran"]:
                st.session_state.pop(_vk, None)
            st.toast("✅ Viáticos guardados y persistidos correctamente", icon="💾")
            st.rerun()

        if _col_reset_via.button("↺ Restaurar", key="btn_reset_via", use_container_width=True,
                                  help="Vuelve a los valores por defecto de fábrica"):
            st.session_state.viaticos_custom = None
            fn_sp()["params_viaticos"] = None
            try:
                fn_guardar_config("viaticos_custom", None)
            except Exception:
                pass
            for _vk in ["via_pueblo_hosp", "via_pueblo_alim", "via_pueblo_tran",
                        "via_ciudad_hosp", "via_ciudad_alim", "via_ciudad_tran"]:
                st.session_state.pop(_vk, None)
            st.toast("↺ Viáticos restaurados a valores por defecto", icon="🔄")
            st.rerun()

    # ─────────────────────────────────────────────────────────────────────────
    # TAB: 🚛 LOGÍSTICA Y VEHÍCULOS
    # ─────────────────────────────────────────────────────────────────────────
    with t_log:
        st.caption("Costos de transporte, vehículos propios, peajes y fletes. Modifica y presiona **Guardar Logística**.")

        with st.expander("📖 ¿Cómo funciona el cálculo de logística?", expanded=False):
            st.markdown("""
La app calcula automáticamente el costo de llevar el material desde el taller hasta la obra del cliente.

**¿Qué se suma?**
- El costo del **combustible** del trayecto (según el rendimiento del vehículo y la distancia)
- El **desgaste** del vehículo (llantas, frenos, suspensión) por kilómetro recorrido
- El **costo base mínimo** por salir (aunque sea cerca)
- Los **peajes** del camino
- El **desgaste de herramientas** (llaves, niveles, espátulas que se gastan)
- El **flete del agente externo** si alguien trajo el material desde el proveedor hasta tu taller

**Vehículos propios (Frontier / Cheyenne):**
El costo se calcula por kilómetro. La app hace:
> costo = (gasolina ÷ rendimiento km/gal) + desgaste por km × km × 2 (ida + vuelta) + base mínima

**Ejemplo con Frontier, 15 km de distancia:**
> ($16.000 ÷ 7.2 km/gal) + $148/km = $2.370/km
> $2.370 × 15 km × 2 (ida+vuelta) = $71.100 + $65.000 base = **$136.100 de transporte**

**Vehículo externo / tercero:**
Se usa un precio fijo de flete. Sin importar la distancia, el costo es siempre el mismo valor que configures aquí.

**💡 Actualiza estos valores cada que cambien los precios del mercado** (gasolina, peajes, etc.).
            """)

        log_act = fn_get_logistica()

        with st.container(border=True):
            st.markdown("**⛽ Insumos generales**")
            _lg1, _lg2, _lg3, _lg4 = st.columns(4)
            gasolina_edit = _lg1.number_input(
                "Gasolina (COP/galón)", min_value=1_000,
                value=int(log_act.get("gasolina", 16_000)), step=500, format="%d",
                key="log_gas",
                help="Precio de la gasolina corriente en Barranquilla.")
            peaje_edit = _lg2.number_input(
                "Peaje promedio (COP)", min_value=0,
                value=int(log_act.get("peaje", 19_500)), step=500, format="%d",
                key="log_pea",
                help="Peaje promedio Galapa / Juan Mina, ida + vuelta.")
            herram_edit = _lg3.number_input(
                "Herramientas (COP/viaje)", min_value=0,
                value=int(log_act.get("herram", 4_500)), step=500, format="%d",
                key="log_her",
                help="Desgaste de llaves, niveles, espátulas, etc. por viaje.")
            agente_edit = _lg4.number_input(
                "Agente externo (COP)", min_value=0,
                value=int(log_act.get("agente", 85_000)), step=1_000, format="%d",
                key="log_age",
                help="Lo que cobra el agente por traer el material desde el proveedor hasta el taller.")

        with st.container(border=True):
            st.markdown("**🚙 Frontier NP300 — camioneta propia**")
            _vc = log_act.get("frontier", {})
            _cf1, _cf2, _cf3 = st.columns(3)
            fr_rend = _cf1.number_input(
                "Rendimiento (km/galón)", min_value=1.0,
                value=float(_vc.get("rend", 7.2)), step=0.1, format="%.1f",
                key="log_fr_rend",
                help="Rendimiento real con carga. Promedio cargada ≈ 7 km/gal.")
            fr_desg = _cf2.number_input(
                "Desgaste por km (COP/km)", min_value=0,
                value=int(_vc.get("desgaste", 148)), step=5, format="%d",
                key="log_fr_desg",
                help="Amortización de llantas, frenos y suspensión por kilómetro.")
            fr_base = _cf3.number_input(
                "Flete base mínimo (COP)", min_value=0,
                value=int(_vc.get("base", 65_000)), step=1_000, format="%d",
                key="log_fr_base",
                help="Costo mínimo por viaje sin importar la distancia.")
            _fr_km = (gasolina_edit / fr_rend) + fr_desg
            st.caption(f"Costo estimado por km ida+vuelta: **{fn_numero_completo(_fr_km * 2)}/km** · "
                       f"Ejemplo 10 km → **{fn_numero_completo(fr_base + _fr_km * 20)}** total")

        with st.container(border=True):
            st.markdown("**🚛 Cheyenne V8 — camión propio**")
            _vc2 = log_act.get("cheyenne", {})
            _cc1, _cc2, _cc3 = st.columns(3)
            ch_rend = _cc1.number_input(
                "Rendimiento (km/galón)", min_value=1.0,
                value=float(_vc2.get("rend", 4.1)), step=0.1, format="%.1f",
                key="log_ch_rend",
                help="Rendimiento real del V8 con carga pesada.")
            ch_desg = _cc2.number_input(
                "Desgaste por km (COP/km)", min_value=0,
                value=int(_vc2.get("desgaste", 340)), step=5, format="%d",
                key="log_ch_desg",
                help="Mayor desgaste por tonelaje.")
            ch_base = _cc3.number_input(
                "Flete base mínimo (COP)", min_value=0,
                value=int(_vc2.get("base", 85_000)), step=1_000, format="%d",
                key="log_ch_base",
                help="Costo mínimo por viaje del camión.")
            _ch_km = (gasolina_edit / ch_rend) + ch_desg
            st.caption(f"Costo estimado por km ida+vuelta: **{fn_numero_completo(_ch_km * 2)}/km** · "
                       f"Ejemplo 10 km → **{fn_numero_completo(ch_base + _ch_km * 20)}** total")

        with st.container(border=True):
            st.markdown("**🤝 Externo / Tercero — flete contratado**")
            _ve = log_act.get("externo", {})
            _flete_val = int(_ve.get("flete", 165_000)) if isinstance(_ve, dict) else int(_ve)
            ext_flete = st.number_input(
                "Flete fijo por viaje (COP)", min_value=0,
                value=_flete_val, step=5_000, format="%d",
                key="log_ext_flete",
                help="Precio pactado con el flete externo. Aplica sin importar la distancia.")

        # ── GESTOR MANUAL DE FLETES ───────────────────────────────────────────
        st.markdown("### 🚚 Mi Flota y Fletes")
        st.caption("Agrega manualmente vehículos propios o fletes externos fijos.")
        _log_c_now   = st.session_state.get("logistica_custom") or {}
        _flota_actual = _log_c_now.get("flota_propia", {})

        if _flota_actual:
            st.markdown("Vehículos/Fletes guardados:")
            for _fslug, _fvcfg in list(_flota_actual.items()):
                with st.container(border=True):
                    _fc1, _fc2, _fc3 = st.columns([4, 4, 1])
                    _fc1.markdown(f"**{_fvcfg.get('nombre', _fslug)}**", unsafe_allow_html=True)
                    if _fvcfg.get("tipo") == "flete_fijo":
                        _fc2.markdown(f"Costo por viaje: ${_fvcfg.get('costo_viaje', 0):,.0f}".replace(",", "."))
                    else:
                        _fc2.markdown(f"Rendimiento: {_fvcfg.get('rendimiento_km_gal', _fvcfg.get('rend', 0))} km/gal | Desgaste: ${_fvcfg.get('desgaste', 0)}/km")

                    if _fc3.button("🗑️", key=f"flota_del_{_fslug}"):
                        _log_del    = dict(st.session_state.get("logistica_custom") or {})
                        _flota_del  = dict(_log_del.get("flota_propia", {}))
                        _flota_del.pop(_fslug, None)
                        _log_del["flota_propia"] = _flota_del
                        st.session_state.logistica_custom = _log_del
                        fn_sp()["params_logistica"] = _log_del
                        try:
                            fn_guardar_config("logistica_custom", _log_del)
                        except Exception:
                            pass
                        st.rerun()
        else:
            st.info("No tienes vehículos manuales registrados.")

        with st.container(border=True):
            st.markdown("**➕ Agregar nuevo vehículo o flete fijo**")
            _flota_col1, _flota_col2 = st.columns(2)
            _flota_input = _flota_col1.text_input("Nombre (Ej: Camioneta Empresa, Flete Norte)", key="flota_nombre_input")
            _flota_costo = _flota_col2.number_input("Costo del viaje ($ COP)", min_value=0, step=5000, value=70000, key="flota_costo_input")

            if st.button("💾 Guardar Vehículo/Flete", type="primary", use_container_width=True):
                if (_flota_input or "").strip():
                    import re as _re_fl
                    _slug = _re_fl.sub(r"[^a-z0-9]+", "_", _flota_input.lower().strip())[:30].strip("_")
                    if _slug in {"frontier", "cheyenne", "externo"}:
                        _slug = f"custom_{_slug}"

                    _veh_nuevo = {
                        "nombre":      _flota_input.strip(),
                        "tipo":        "flete_fijo",
                        "costo_viaje": _flota_costo,
                    }
                    _log_save  = dict(st.session_state.get("logistica_custom") or {})
                    _flota_upd = dict(_log_save.get("flota_propia", {}))
                    _flota_upd[_slug] = _veh_nuevo
                    _log_save["flota_propia"] = _flota_upd

                    st.session_state.logistica_custom = _log_save
                    fn_sp()["params_logistica"] = _log_save
                    try:
                        fn_guardar_config("logistica_custom", _log_save)
                    except Exception:
                        pass
                    st.session_state.pop("flota_nombre_input", None)
                    st.session_state.pop("flota_costo_input", None)
                    st.rerun()

        st.markdown("")
        _col_save_log, _col_reset_log = st.columns([3, 1])
        if _col_save_log.button("💾 Guardar Logística", type="primary", key="btn_save_log", use_container_width=True):
            _flota_preservada = (st.session_state.get("logistica_custom") or {}).get("flota_propia", {})
            _saved_log = {
                "gasolina": int(st.session_state.get("log_gas",      16_000)),
                "peaje":    int(st.session_state.get("log_pea",      19_500)),
                "herram":   int(st.session_state.get("log_her",       4_500)),
                "agente":   int(st.session_state.get("log_age",      85_000)),
                "frontier": {
                    "rend":     float(st.session_state.get("log_fr_rend",  7.2)),
                    "desgaste": int(st.session_state.get("log_fr_desg",    148)),
                    "base":     int(st.session_state.get("log_fr_base", 65_000)),
                },
                "cheyenne": {
                    "rend":     float(st.session_state.get("log_ch_rend",  4.1)),
                    "desgaste": int(st.session_state.get("log_ch_desg",    340)),
                    "base":     int(st.session_state.get("log_ch_base", 85_000)),
                },
                "externo": {
                    "flete": int(st.session_state.get("log_ext_flete", 165_000)),
                },
                "flota_propia": _flota_preservada,
            }
            fn_sp()["params_logistica"] = _saved_log
            st.session_state.logistica_custom = _saved_log
            try:
                fn_guardar_config("logistica_custom", _saved_log)
            except Exception:
                pass
            for _lk in ["log_gas", "log_pea", "log_her", "log_age",
                        "log_fr_rend", "log_fr_desg", "log_fr_base",
                        "log_ch_rend", "log_ch_desg", "log_ch_base", "log_ext_flete"]:
                st.session_state.pop(_lk, None)
            st.toast("✅ Logística guardada y persistida correctamente", icon="💾")
            st.rerun()

        if _col_reset_log.button("↺ Restaurar", key="btn_reset_log", use_container_width=True,
                                  help="Vuelve a los valores por defecto de fábrica"):
            st.session_state.logistica_custom = None
            fn_sp()["params_logistica"] = None
            try:
                fn_guardar_config("logistica_custom", None)
            except Exception:
                pass
            for _lk in ["log_gas", "log_pea", "log_her", "log_age",
                        "log_fr_rend", "log_fr_desg", "log_fr_base",
                        "log_ch_rend", "log_ch_desg", "log_ch_base", "log_ext_flete"]:
                st.session_state.pop(_lk, None)
            st.toast("↺ Logística restaurada a valores por defecto", icon="🔄")
            st.rerun()

    # ─────────────────────────────────────────────────────────────────────────
    # TAB: ➕ COSTOS ADICIONALES
    # ─────────────────────────────────────────────────────────────────────────
    with t_add:
        st.caption("Edita los ítems de costos adicionales que aparecen en el Paso 6 de la cotización. Puedes cambiar el nombre, la unidad y el precio por etapa de obra.")
        st.info(
            "**💡 Tabla responsiva:** Puedes agregar filas con el botón ➕ al final de la tabla "
            "y borrar filas seleccionando la casilla de la fila y presionando **Suprimir**. "
            "Funciona correctamente en móviles y escritorio.",
            icon="📱",
        )

        import copy as _cpy_add
        import pandas as _pd_add

        add_act       = fn_get_adicionales()
        UNIDADES_ADD  = ["und", "ml", "m²", "viaje", "glb", "día", "kg"]

        if "add_editor" not in st.session_state:
            st.session_state.add_editor = _cpy_add.deepcopy(add_act)

        _df_add = _pd_add.DataFrame(st.session_state.add_editor)
        for _cf in ["concepto", "unidad", "terminada", "acabados", "estructura", "comercial"]:
            if _cf not in _df_add.columns:
                _df_add[_cf] = "" if _cf in ("concepto", "unidad") else 0
        _df_add = _df_add[["concepto", "unidad", "terminada", "acabados", "estructura", "comercial"]]
        _df_add["terminada"]  = _df_add["terminada"].astype(int)
        _df_add["acabados"]   = _df_add["acabados"].astype(int)
        _df_add["estructura"] = _df_add["estructura"].astype(int)
        _df_add["comercial"]  = _df_add["comercial"].astype(int)

        _df_editado = st.data_editor(
            _df_add,
            use_container_width=True,
            num_rows="dynamic",
            key="de_adicionales",
            column_config={
                "concepto": st.column_config.TextColumn(
                    "Concepto / Descripción",
                    help="Nombre del servicio o material adicional",
                    width="large",
                    required=True,
                ),
                "unidad": st.column_config.SelectboxColumn(
                    "Unidad",
                    options=UNIDADES_ADD,
                    help="Unidad de cobro",
                    width="small",
                    required=True,
                ),
                "terminada": st.column_config.NumberColumn(
                    "Casa terminada (COP)",
                    help="Precio cuando el inmueble ya está terminado",
                    format="$ %d",
                    min_value=0,
                    step=1_000,
                    width="medium",
                ),
                "acabados": st.column_config.NumberColumn(
                    "En acabados (COP)",
                    help="Precio cuando hay obra de acabados en curso",
                    format="$ %d",
                    min_value=0,
                    step=1_000,
                    width="medium",
                ),
                "estructura": st.column_config.NumberColumn(
                    "En estructura (COP)",
                    help="Precio en obra gris o estructura sin terminar",
                    format="$ %d",
                    min_value=0,
                    step=1_000,
                    width="medium",
                ),
                "comercial": st.column_config.NumberColumn(
                    "Proyecto comercial (COP)",
                    help="Precio para proyectos comerciales (locales, oficinas, centros comerciales)",
                    format="$ %d",
                    min_value=0,
                    step=1_000,
                    width="medium",
                ),
            },
            hide_index=True,
        )

        st.session_state.add_editor = _df_editado.to_dict(orient="records")

        st.markdown("")
        _col_save_add, _col_reset_add = st.columns([3, 1])
        if _col_save_add.button("💾 Guardar Adicionales", type="primary", key="btn_save_add", use_container_width=True):
            _saved_add = [
                {
                    "concepto":   str(row.get("concepto", "") or ""),
                    "unidad":     str(row.get("unidad", "und") or "und"),
                    "terminada":  int(row.get("terminada",  0) or 0),
                    "acabados":   int(row.get("acabados",   0) or 0),
                    "estructura": int(row.get("estructura", 0) or 0),
                    "comercial":  int(row.get("comercial",  0) or 0),
                }
                for row in st.session_state.add_editor
                if str(row.get("concepto", "")).strip()
            ]
            st.session_state.adicionales_custom = _saved_add
            st.session_state.add_editor = _saved_add
            try:
                fn_guardar_config("adicionales_custom", _saved_add)
            except Exception:
                pass
            st.toast("✅ Costos adicionales guardados y persistidos", icon="💾")
            st.rerun()

        if _col_reset_add.button("↺ Restaurar", key="btn_reset_add", use_container_width=True,
                                  help="Vuelve a la lista original de fábrica"):
            st.session_state.adicionales_custom = None
            st.session_state.add_editor = _cpy_add.deepcopy(ADICIONALES)
            try:
                fn_guardar_config("adicionales_custom", None)
            except Exception:
                pass
            st.session_state.pop("de_adicionales", None)
            st.toast("↺ Adicionales restaurados a valores por defecto", icon="🔄")
            st.rerun()
