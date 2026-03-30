# ui_retales.py — Costo360
# Módulo independiente: Banco de Retales (Sobrantes Aprovechables).
# Extraído de app.py mediante el Patrón de Estrangulamiento.
# Todas las funciones de BD se inyectan como parámetros — sin imports de app.py.

import streamlit as st

from calculos import cop
from parametros import CATEGORIAS_MATERIAL


# ── Helper de formateo (replicado de app.py para independencia total) ─────────

def _numero_completo(valor) -> str:
    """Moneda colombiana: $1.250.000"""
    return "$" + f"{int(round(valor)):,}".replace(",", ".")


# ═══════════════════════════════════════════════════════════════════════════════
# BANCO DE RETALES — Sobrantes Aprovechables
# ═══════════════════════════════════════════════════════════════════════════════

def _ui_banco_retales(
    fn_listar,
    fn_eliminar,
    fn_guardar_manual,
    fn_actualizar_precio,
):
    """
    Renderiza el Banco de Retales (Sobrantes Aprovechables).

    Args:
        fn_listar:           Callable — _listar_retales(usuario_id, rol) de app.py.
        fn_eliminar:         Callable — _eliminar_retal(retal_id) de app.py.
        fn_guardar_manual:   Callable — inserta un retal manual en BD.
                             Firma: fn_guardar_manual(cat, ref, m2, nota, usuario_id) -> bool
        fn_actualizar_precio: Callable — actualiza precio_recuperacion en BD.
                             Firma: fn_actualizar_precio(retal_id, precio) -> bool
    """
    st.markdown(
        "<h2 style='font-family:Playfair Display,serif;margin-bottom:4px'>♻️ Sobrantes Aprovechables</h2>"
        "<p style='opacity:0.6;font-size:0.85rem;margin:0 0 12px'>"
        "Material que sobró de proyectos anteriores y puedes volver a vender — úsalo en el próximo proyecto y dispara tu margen de ganancia."
        "</p>",
        unsafe_allow_html=True
    )

    # ── Tarjeta explicativa fija ──────────────────────────────────────────────
    with st.expander("📖 ¿Cómo funciona este módulo? — Léeme si es tu primera vez", expanded=False):
        st.markdown("""
**¿Qué es un sobrante?**

Cuando compras una lámina de mármol o granito para un proyecto, casi siempre sobra un pedazo que no se instaló. 
Ese pedazo se llama **sobrante** (o retal). En lugar de botarlo o dejarlo arrinconado, este módulo te ayuda a registrarlo y usarlo en el próximo proyecto.

**¿Por qué es importante?**

Si usas ese sobrante en otro trabajo, **el costo del material en esa cotización sube a $0**, 
lo que significa que toda la venta de ese material es ganancia pura. Tu margen puede subir del 40% habitual al 80-90%.

**¿Cómo entra un sobrante aquí?**

Automáticamente: cuando apruebas una cotización en el Historial que generó material de sobra, el sistema lo registra solo.

Manual: puedes usar el botón **"+ Agregar sobrante manual"** para registrar piezas que ya tenías guardadas.

**¿Cómo lo uso en una cotización?**

Ve a **Cotización Directa**, selecciona el mismo material y la app te avisará que tienes sobrante disponible.
Haz clic en "Usar sobrante" y el costo del material queda en $0.

---
**💡 Consejo:** Registra siempre dónde guardaste la pieza (usa el campo "Notas") para encontrarla rápido cuando la necesites.
        """)

    # ── Métricas del banco ────────────────────────────────────────────────────
    try:
        _todos_retales = fn_listar(
            usuario_id=st.session_state.get("usuario_actual", {}).get("id"),
            rol=st.session_state.get("usuario_actual", {}).get("rol", "Admin"),
        )
    except Exception:
        _todos_retales = []

    _disp        = [r for r in _todos_retales if r[8] == "Disponible"]
    _usados      = [r for r in _todos_retales if r[8] == "Usado"]
    _m2_disp_total = sum(r[3] for r in _disp)

    _rm1, _rm2, _rm3, _rm4 = st.columns(4)
    _rm1.metric("Sobrantes disponibles", len(_disp),
                help="Piezas de material que tienes guardadas y listas para usar en un nuevo proyecto.")
    _rm2.metric("m² disponibles", f"{_m2_disp_total:.2f} m²",
                help="Metros cuadrados totales de material sobrante que tienes en inventario.")
    _rm3.metric("Ya utilizados", len(_usados),
                help="Sobrantes que ya fueron asignados a un proyecto posterior.")
    _rm4.metric("Total registrado", f"{len(_todos_retales)} piezas",
                help="Total de sobrantes que el sistema ha registrado, incluyendo los ya utilizados.")

    st.markdown("<hr style='margin:10px 0 20px'>", unsafe_allow_html=True)

    # ── Filtro y herramientas ─────────────────────────────────────────────────
    _rf1, _rf2, _rf3 = st.columns([2, 1.5, 1])
    with _rf1:
        _rfiltro_cat = st.selectbox(
            "Filtrar por material",
            ["Todos"] + CATEGORIAS_MATERIAL,
            key="retal_filtro_cat", label_visibility="collapsed"
        )
    with _rf2:
        _rfiltro_est = st.selectbox(
            "Estado",
            ["Disponible", "Todos los estados", "Usado"],
            key="retal_filtro_est", label_visibility="collapsed"
        )
    with _rf3:
        if st.button("+ Agregar sobrante manual", use_container_width=True, type="primary"):
            st.session_state["retal_form_abierto"] = True

    # ── Formulario de registro manual ─────────────────────────────────────────
    if st.session_state.get("retal_form_abierto"):
        with st.container(border=True):
            st.markdown(
                "<div style='font-weight:700;margin-bottom:10px'>Registrar sobrante manualmente</div>",
                unsafe_allow_html=True
            )
            _rf_c1, _rf_c2, _rf_c3 = st.columns([1.5, 1.5, 1])
            with _rf_c1:
                _ncat = st.selectbox("Categoría", CATEGORIAS_MATERIAL, key="rfm_cat")
                _nref = st.text_input("Referencia", key="rfm_ref",
                                      placeholder="Ej: Calacatta Dorato")
            with _rf_c2:
                _nm2  = st.number_input("m² disponibles", min_value=0.05, max_value=50.0,
                                        value=1.0, step=0.05, key="rfm_m2", format="%.3f")
                _nnota = st.text_input("Notas (opcional)", key="rfm_nota",
                                       placeholder="Ej: Guardado en taller, estante 3")
            with _rf_c3:
                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                if st.button("Guardar", key="rfm_save", type="primary", use_container_width=True):
                    try:
                        _uid_manual = st.session_state.get("usuario_actual", {}).get("id")
                        _ok = fn_guardar_manual(_ncat, _nref, _nm2, _nnota, _uid_manual)
                        if _ok:
                            st.session_state["retal_form_abierto"] = False
                            st.success("Retal registrado.")
                            st.rerun()
                    except Exception as _e:
                        st.error(f"Error: {_e}")
                if st.button("Cancelar", key="rfm_cancel", use_container_width=True):
                    st.session_state["retal_form_abierto"] = False
                    st.rerun()

    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

    # ── Tabla de inventario ───────────────────────────────────────────────────
    _filas_filtradas = _todos_retales
    if _rfiltro_cat != "Todos":
        _filas_filtradas = [r for r in _filas_filtradas if r[1] == _rfiltro_cat]
    if _rfiltro_est == "Disponible":
        _filas_filtradas = [r for r in _filas_filtradas if r[8] == "Disponible"]
    elif _rfiltro_est == "Usado":
        _filas_filtradas = [r for r in _filas_filtradas if r[8] == "Usado"]

    if not _filas_filtradas:
        st.markdown(
            '<div style="text-align:center;padding:56px 0;opacity:0.38">'
            '<div style="font-size:0.95rem;font-weight:700;margin-bottom:8px">No hay sobrantes en el inventario</div>'
            '<div style="font-size:0.83rem">Los sobrantes se registran automáticamente cuando apruebas una cotización<br>'
            'que generó material de sobra. También puedes agregarlos manualmente.</div>'
            '</div>',
            unsafe_allow_html=True
        )
        return

    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

    for _rr in _filas_filtradas:
        _rr_id, _rr_cat, _rr_ref, _rr_m2d, _rr_m2o, _rr_onum, _rr_ocli, _rr_fech, _rr_est, _rr_nota = _rr[:10]
        _rr_precio_rec = float(_rr[10]) if len(_rr) > 10 else 0.0
        _pct_rest    = (_rr_m2d / _rr_m2o * 100) if _rr_m2o > 0 else 0
        _est_color   = "#15803d" if _rr_est == "Disponible" else "#6b7280"
        _bg_card     = "rgba(21,128,61,0.04)" if _rr_est == "Disponible" else "rgba(107,114,128,0.05)"
        _border_color = "#15803d" if _rr_est == "Disponible" else "#6b7280"

        with st.container(border=True):
            # Cabecera: ícono de estado + badge de disponibilidad
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">'
                f'<span style="width:10px;height:10px;border-radius:50%;'
                f'background:{_est_color};display:inline-block;flex-shrink:0"></span>'
                f'<span style="font-size:0.72rem;font-weight:800;color:{_est_color};'
                f'text-transform:uppercase;letter-spacing:0.06em">{_rr_est}</span>'
                f'</div>',
                unsafe_allow_html=True
            )

            # Fila superior: material + ref + m² + origen + fecha + botón eliminar
            _ca, _cb, _cc, _cd, _ce, _cf = st.columns([1.6, 1.4, 0.9, 1.4, 1.1, 0.9])
            _ca.markdown(
                f'<div style="font-size:0.85rem;font-weight:800">{_rr_cat}</div>'
                f'<div style="font-size:0.76rem;opacity:0.6">{_rr_ref or "Sin referencia"}</div>',
                unsafe_allow_html=True
            )
            _cb.markdown(
                f'<div style="font-size:0.7rem;opacity:0.5;text-transform:uppercase;font-weight:700">Disponible</div>'
                f'<div style="font-size:1.1rem;font-weight:900;color:{_est_color}">{_rr_m2d:.3f} m²</div>',
                unsafe_allow_html=True
            )
            _cc.markdown(
                f'<div style="font-size:0.7rem;opacity:0.5;text-transform:uppercase;font-weight:700">Original</div>'
                f'<div style="font-size:0.85rem;opacity:0.6">{_rr_m2o:.3f} m²</div>',
                unsafe_allow_html=True
            )
            _cd.markdown(
                f'<div style="font-size:0.7rem;opacity:0.5;text-transform:uppercase;font-weight:700">Origen</div>'
                f'<div style="font-size:0.78rem">{_rr_onum or "Manual"}</div>'
                f'<div style="font-size:0.72rem;opacity:0.55">{_rr_ocli or "—"}</div>',
                unsafe_allow_html=True
            )
            _ce.markdown(
                f'<div style="font-size:0.7rem;opacity:0.5;text-transform:uppercase;font-weight:700">Fecha</div>'
                f'<div style="font-size:0.76rem;opacity:0.65">{_rr_fech}</div>',
                unsafe_allow_html=True
            )
            with _cf:
                st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
                _del_retal_key = f"del_retal_ok_{_rr_id}"
                if not st.session_state.get(_del_retal_key):
                    if st.button("🗑️ Eliminar", key=f"del_retal_{_rr_id}",
                                 use_container_width=True):
                        st.session_state[_del_retal_key] = True
                        st.rerun()
                else:
                    if st.button("✅ Confirmar", key=f"delconf_retal_{_rr_id}",
                                 use_container_width=True, type="primary"):
                        fn_eliminar(_rr_id)
                        st.session_state.pop(_del_retal_key, None)
                        st.rerun()

            # Barra de progreso (solo si está disponible)
            if _rr_m2o > 0 and _rr_est == "Disponible":
                st.markdown(
                    f'<div style="height:4px;background:rgba(0,0,0,0.1);border-radius:2px;margin:10px 0 8px">'
                    f'<div style="height:100%;width:{_pct_rest:.0f}%;background:{_est_color};border-radius:2px"></div>'
                    f'</div>',
                    unsafe_allow_html=True
                )

            # Fila inferior: precio de recuperación (solo si está disponible)
            if _rr_est == "Disponible":
                st.markdown(
                    '<div style="border-top:1px solid var(--border-color);margin-top:10px;'
                    'padding-top:10px;margin-bottom:4px"></div>',
                    unsafe_allow_html=True
                )
                _pr_col1, _pr_col2, _pr_col3 = st.columns([1.6, 1.5, 4.9])
                with _pr_col1:
                    st.markdown(
                        '<div style="font-size:0.75rem;font-weight:800;padding-top:8px;'
                        'color:var(--text-color)">'
                        '💰 ¿A qué precio lo vendes?</div>'
                        '<div style="font-size:0.67rem;opacity:0.5;margin-top:3px;line-height:1.4">'
                        'Por m² · Ingresa el costo base o valor mínimo de recuperación contable</div>',
                        unsafe_allow_html=True
                    )
                with _pr_col2:
                    _pr_key = f"prec_rec_{_rr_id}"
                    _nuevo_precio_rec = st.number_input(
                        "precio_rec",
                        min_value=0,
                        max_value=5_000_000,
                        value=int(_rr_precio_rec),
                        step=5_000,
                        key=_pr_key,
                        label_visibility="collapsed",
                        help=(
                            "Ingresa el costo base del material o el valor mínimo de recuperación contable. "
                            "Evita colocar $0 para no generar márgenes de ganancia ilusorios en tus reportes.\n\n"
                            "Ejemplo: si el material original costó $150.000/m², pon al menos "
                            "$75.000/m² como valor de recuperación parcial. Así tus métricas "
                            "de margen reflejarán la rentabilidad real del proyecto."
                        ),
                    )
                    st.markdown(
                        f"<div style='margin-top:-2px; margin-bottom:10px; font-size:0.85rem; "
                        f"color:#1B5FA8; font-weight:600;'>💰 Equivalencia: {cop(_nuevo_precio_rec)}</div>",
                        unsafe_allow_html=True
                    )
                    if _nuevo_precio_rec != int(_rr_precio_rec):
                        try:
                            _ok_pr = fn_actualizar_precio(_rr_id, _nuevo_precio_rec)
                            if _ok_pr:
                                st.toast("✅ Precio guardado", icon="💾")
                        except Exception as _e_pr:
                            st.error(f"Error al guardar: {_e_pr}")
                with _pr_col3:
                    if _nuevo_precio_rec == 0:
                        _hint_icon  = "⚠️"
                        _hint_txt   = "Precio en $0 — Atención: esto generará un margen ilusorio en tus reportes. Ingresa al menos el costo base del material para reflejar la rentabilidad real."
                        _hint_color = "#b45309"
                    elif _nuevo_precio_rec < 50_000:
                        _hint_icon  = "🟡"
                        _hint_txt   = f"Cobras {_numero_completo(_nuevo_precio_rec)}/m² por este sobrante — precio simbólico, buen margen."
                        _hint_color = "#d97706"
                    else:
                        _hint_icon  = "🔵"
                        _hint_txt   = f"Cobras {_numero_completo(_nuevo_precio_rec)}/m² — precio de mercado parcial. El margen sigue siendo mejor que comprar nuevo."
                        _hint_color = "#1B5FA8"
                    st.markdown(
                        f'<div style="font-size:0.77rem;padding-top:8px;color:{_hint_color};font-weight:600">'
                        f'{_hint_icon} {_hint_txt}</div>',
                        unsafe_allow_html=True
                    )

        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
