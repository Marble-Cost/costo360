# ui_nesting.py
# ─────────────────────────────────────────────────────────────────────────────
# Módulo de Planos de Taller & Optimizador de Corte (Nesting 2D)
# Extraído de app.py siguiendo el patrón Strangler Fig (Fase 9).
#
# REGLA ARQUITECTÓNICA: este archivo NUNCA importa app.py.
# Las dependencias externas se inyectan como parámetros.
#
# Firma:
#   _ui_nesting(
#       fn_ia_disponible,           # () -> bool
#       fn_extraer_coordenadas,     # (prompt: str) -> dict | None
#       fn_optimizar_corte_2d,      # (largo, ancho, piezas) -> (svg_str, metricas_dict)
#       fn_wrap_svg_streamlit,      # (svg_str) -> str (HTML envolvente)
#       fn_exportar_svg_a_pdf,      # (svg_str) -> bytes
#   )
# ─────────────────────────────────────────────────────────────────────────────

import uuid

import streamlit as st


def _ui_nesting(
    fn_ia_disponible,
    fn_extraer_coordenadas,
    fn_optimizar_corte_2d,
    fn_wrap_svg_streamlit,
    fn_exportar_svg_a_pdf,
):
    """Renderiza la pantalla completa de Planos de Taller & Optimizador de Corte."""

    # ── Callback: agregar pieza al carrito ────────────────────────────────────
    # Definido ANTES de cualquier widget para que on_click pueda referenciarlo.
    def agregar_pieza_nesting():
        nom   = st.session_state.get("nest_nom",   "")
        largo = st.session_state.get("nest_largo", 1.20)
        ancho = st.session_state.get("nest_ancho", 0.60)
        cant  = int(st.session_state.get("nest_cant", 1))
        if float(largo) > 0 and float(ancho) > 0:
            for _ in range(cant):
                st.session_state.nesting_piezas.append({
                    "id":       uuid.uuid4().hex[:8],
                    "nombre":   nom.strip() if nom.strip() else "Pieza",
                    "largo":    float(largo),
                    "ancho":    float(ancho),
                    "cantidad": 1,
                })
        st.session_state.nest_nom   = ""
        st.session_state.nest_largo = 1.20
        st.session_state.nest_ancho = 0.60
        st.session_state.nest_cant  = 1

    # ── Estilos ───────────────────────────────────────────────────────────────
    st.markdown("""
    <style>
    .plano-header {
        background: linear-gradient(135deg, #0D2137 0%, #1B5FA8 100%);
        border-radius: 10px;
        padding: 22px 24px 18px;
        margin-bottom: 18px;
    }
    .plano-header h2  { color:#FFFFFF; font-size:1.35rem; font-weight:700; margin:0 0 4px 0; }
    .plano-header p   { color:#B8D4F0; font-size:0.88rem; margin:0 0 10px 0; }
    .plano-badge      { background:#C9A84C; color:#0D2137; font-size:0.72rem;
                        font-weight:700; border-radius:4px; padding:3px 10px;
                        letter-spacing:0.06em; text-transform:uppercase; }
    .plano-tip        { background:#EFF6FF; border-left:3px solid #1B5FA8;
                        border-radius:0 6px 6px 0; padding:8px 12px;
                        font-size:0.82rem; color:#1E3A5F; margin-bottom:10px; }
    .plano-error      { background:#FEF2F2; border:1px solid #FECACA;
                        border-radius:6px; padding:10px 14px;
                        font-size:0.84rem; color:#7F1D1D; margin-top:8px; }
    .pieza-card-header {
        font-size:0.72rem; font-weight:700; color:#1B5FA8;
        text-transform:uppercase; letter-spacing:0.07em; margin:0 0 6px 0;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── Encabezado ────────────────────────────────────────────────────────────
    st.markdown("""
    <div class="plano-header">
        <h2>📐 Planos de Taller &amp; Optimizador de Corte</h2>
        <p>Ingresa las medidas de la placa y las piezas a cortar.
        El algoritmo 2D acomoda automáticamente todas las piezas dentro de la lámina.</p>
        <span class="plano-badge">✦ Nesting 2D · Descarga PDF</span>
    </div>
    """, unsafe_allow_html=True)

    # ── Protección anti-refresco accidental ──────────────────────────────────
    st.components.v1.html(
        """
        <script>
            window.parent.addEventListener('beforeunload', function (e) {
                e.preventDefault();
                e.returnValue = '';
            });
        </script>
        """,
        height=0,
        width=0,
    )

    # ── Inicializar session state ─────────────────────────────────────────────
    if "nesting_svg" not in st.session_state:
        st.session_state.nesting_svg = None
    if "nesting_metricas" not in st.session_state:
        st.session_state.nesting_metricas = None
    if "nesting_error" not in st.session_state:
        st.session_state.nesting_error = ""
    if "nesting_piezas" not in st.session_state:
        st.session_state.nesting_piezas = [
            {"id": 1, "nombre": "Mesón", "largo": 2.50, "ancho": 0.60, "cantidad": 1}
        ]
    if "nesting_id_counter" not in st.session_state:
        st.session_state.nesting_id_counter = 2

    # ── Lienzo Inteligente: vincular con inventario ───────────────────────────
    _mats_inv = st.session_state.get("materiales_proyecto", [])
    _opciones_lienzo = ["🆓 Modo Libre — Plano Independiente"]
    for _mi, _mm in enumerate(_mats_inv):
        _ml_inv  = float(_mm.get("placas_largo", _mm.get("largo", 0.0)))
        _ma_inv  = float(_mm.get("placas_ancho", _mm.get("ancho", 0.0)))
        _mc_inv  = int(_mm.get("placas_cant", 1))
        _mr_inv  = _mm.get("ref") or _mm.get("cat", f"Lote {_mi+1}")
        _cat_inv = _mm.get("cat", "")
        _dims_inv = f"{_ml_inv:.2f}×{_ma_inv:.2f}m" if _ml_inv > 0 and _ma_inv > 0 else "sin medidas"
        _suffix_inv = f" ×{_mc_inv}" if _mc_inv > 1 else ""
        _opciones_lienzo.append(
            f"[Lote #{_mi+1}] {_cat_inv} — {_mr_inv}{_suffix_inv} ({_dims_inv})"
        )

    _lbl_lienzo = st.selectbox(
        "📏 Vincular plano con inventario actual (Opcional):",
        _opciones_lienzo,
        index=0,
        key="nesting_lienzo_lote",
        help=(
            "Selecciona un lote para cargar automáticamente sus dimensiones como lienzo base. "
            "El asistente IA también recibirá el contexto de la placa seleccionada."
        ),
    )

    _lienzo_idx = _opciones_lienzo.index(_lbl_lienzo) - 1
    _lienzo_contexto_txt = ""
    if _lienzo_idx >= 0 and _lienzo_idx < len(_mats_inv):
        _lm_sel   = _mats_inv[_lienzo_idx]
        _lm_largo = float(_lm_sel.get("placas_largo", _lm_sel.get("largo", 2.80)))
        _lm_ancho = float(_lm_sel.get("placas_ancho", _lm_sel.get("ancho", 1.60)))
        _lm_cat   = _lm_sel.get("cat", "")
        _lm_ref   = _lm_sel.get("ref") or _lm_cat
        st.session_state["nesting_placa_largo"] = _lm_largo
        st.session_state["nesting_placa_ancho"] = _lm_ancho
        _lienzo_contexto_txt = (
            f"[Contexto del sistema: El usuario requiere dibujar sobre un lienzo base "
            f"de {_lm_largo:.2f}m × {_lm_ancho:.2f}m correspondiente a la placa de "
            f"{_lm_cat} — {_lm_ref}]. "
        )
        st.caption(
            f"↳ Lienzo activo: **{_lm_cat} — {_lm_ref}** "
            f"({_lm_largo:.2f}m × {_lm_ancho:.2f}m). "
            f"Dimensiones cargadas en la sección de placa."
        )

    # ── Layout maestro-detalle ────────────────────────────────────────────────
    col_form, col_lista = st.columns([1.2, 1], gap="large")

    # ── Columna izquierda: formulario ─────────────────────────────────────────
    with col_form:

        st.markdown(
            "<p style='font-size:0.78rem;font-weight:700;color:#1B5FA8;"
            "text-transform:uppercase;letter-spacing:0.07em;margin:0 0 6px 0'>"
            "1 · Medidas de la lámina virgen</p>",
            unsafe_allow_html=True,
        )
        with st.container(border=True):
            _pc1, _pc2 = st.columns(2)
            with _pc1:
                placa_largo = st.number_input(
                    "Largo de la Placa (m)",
                    min_value=0.20, max_value=10.0,
                    value=2.80, step=0.05, format="%.2f",
                    key="nesting_placa_largo",
                    help="Dimensión más larga de la lámina, ej: 2.80 m",
                )
            with _pc2:
                placa_ancho = st.number_input(
                    "Ancho de la Placa (m)",
                    min_value=0.10, max_value=5.0,
                    value=1.60, step=0.05, format="%.2f",
                    key="nesting_placa_ancho",
                    help="Dimensión más corta de la lámina, ej: 1.60 m",
                )

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

        st.markdown(
            "<p style='font-size:0.78rem;font-weight:700;color:#1B5FA8;"
            "text-transform:uppercase;letter-spacing:0.07em;margin:0 0 6px 0'>"
            "2 · Agregar pieza a cortar</p>",
            unsafe_allow_html=True,
        )

        if "nest_nom" not in st.session_state:
            st.session_state.nest_nom   = ""
        if "nest_largo" not in st.session_state:
            st.session_state.nest_largo = 1.20
        if "nest_ancho" not in st.session_state:
            st.session_state.nest_ancho = 0.60
        if "nest_cant" not in st.session_state:
            st.session_state.nest_cant  = 1

        with st.container(border=True):
            st.text_input(
                "Nombre de la pieza",
                placeholder="Ej: Mesón cocina, Baño, Zócalo…",
                key="nest_nom",
            )
            _fn_cols = st.columns([2, 1, 1, 1])
            with _fn_cols[0]:
                st.caption(
                    f"Pieza: «{st.session_state.nest_nom.strip() or 'sin nombre'}»"
                    if st.session_state.nest_nom.strip() else "«escribe el nombre arriba»"
                )
            with _fn_cols[1]:
                st.number_input(
                    "Largo (m)",
                    min_value=0.0,
                    step=0.05, format="%.2f",
                    help="Medida más larga",
                    key="nest_largo",
                )
            with _fn_cols[2]:
                st.number_input(
                    "Ancho (m)",
                    min_value=0.0,
                    step=0.05, format="%.2f",
                    help="Medida más corta",
                    key="nest_ancho",
                )
            with _fn_cols[3]:
                st.number_input(
                    "Cant.",
                    min_value=1, max_value=20,
                    step=1,
                    help="Cuántas iguales",
                    key="nest_cant",
                )
            st.button(
                "➕ Agregar a la lista",
                type="primary",
                on_click=agregar_pieza_nesting,
                use_container_width=True,
            )

    # ── Columna derecha: carrito de piezas ────────────────────────────────────
    with col_lista:
        _n_piezas_lista = len(st.session_state.nesting_piezas)
        st.markdown(
            "<p style='font-size:0.78rem;font-weight:700;color:#1B5FA8;"
            "text-transform:uppercase;letter-spacing:0.07em;margin:0 0 6px 0'>"
            "3 · Lista de corte</p>",
            unsafe_allow_html=True,
        )

        if _n_piezas_lista == 0:
            st.info(
                "Aún no hay piezas. Usa el formulario de la izquierda para agregarlas.",
                icon="📋",
            )
        else:
            _area_total_lista = sum(
                p["largo"] * p["ancho"] for p in st.session_state.nesting_piezas
            )
            st.markdown(
                f"<p style='font-size:0.82rem;color:#6B7280;margin:0 0 10px 0'>"
                f"🧩 <strong>{_n_piezas_lista}</strong> pieza(s)"
                f" &nbsp;·&nbsp; "
                f"Área total: <strong>{_area_total_lista:.2f} m²</strong></p>",
                unsafe_allow_html=True,
            )

            _id_a_eliminar = None
            for _lp in st.session_state.nesting_piezas:
                with st.container(border=True):
                    _lc1, _lc2 = st.columns([0.82, 0.18])
                    with _lc1:
                        st.markdown(
                            f"<p style='margin:0;font-size:0.95rem;"
                            f"font-weight:700;color:#1C2B3A;line-height:1.3'>"
                            f"{_lp['nombre']}</p>"
                            f"<p style='margin:2px 0 0 0;font-size:0.78rem;color:#6B7280'>"
                            f"📏 {_lp['largo']:.2f} m"
                            f" &nbsp;×&nbsp; "
                            f"📐 {_lp['ancho']:.2f} m"
                            f" &nbsp;·&nbsp; "
                            f"{_lp['largo'] * _lp['ancho']:.3f} m²</p>",
                            unsafe_allow_html=True,
                        )
                    with _lc2:
                        if st.button(
                            "❌",
                            key=f"del_{_lp['id']}",
                            use_container_width=True,
                            help="Quitar esta pieza",
                        ):
                            _id_a_eliminar = _lp["id"]

            if _id_a_eliminar is not None:
                st.session_state.nesting_piezas = [
                    p for p in st.session_state.nesting_piezas
                    if p["id"] != _id_a_eliminar
                ]
                st.rerun()

            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
            if st.button(
                "🗑️ Vaciar lista",
                use_container_width=True,
                key="nesting_btn_vaciar",
                help="Elimina todas las piezas y empieza de nuevo",
            ):
                st.session_state.nesting_piezas = []
                st.rerun()

    # ── Chat IA del Lienzo Inteligente ────────────────────────────────────────
    if fn_ia_disponible():
        with st.expander("🤖 Describir proyecto con IA (Opcional)", expanded=False):
            st.caption(
                "Describe en lenguaje natural las piezas a cortar. "
                "La IA extraerá las medidas y las añadirá a la lista automáticamente."
                + (f" Lienzo base activo: **{_lbl_lienzo}**." if _lienzo_idx >= 0 else "")
            )
            _ia_desc = st.text_area(
                "Describe las piezas:",
                placeholder="Ej: necesito un mesón de 3.20 m × 0.60 m y dos baños de 1.10 m × 0.55 m",
                height=80,
                key="nesting_ia_descripcion",
                label_visibility="collapsed",
            )
            if st.button(
                "✨ Extraer medidas con IA",
                key="nesting_ia_extraer",
                disabled=not _ia_desc.strip(),
            ):
                _prompt_ia = (
                    (_lienzo_contexto_txt + _ia_desc.strip())
                    if _lienzo_contexto_txt
                    else _ia_desc.strip()
                )
                with st.spinner("Interpretando descripción…"):
                    _coords = fn_extraer_coordenadas(_prompt_ia)
                if _coords and _coords.get("piezas"):
                    _importadas = 0
                    for _pp in _coords["piezas"]:
                        _p_largo = float(_pp.get("largo") or 0.0)
                        _p_ancho = float(_pp.get("ancho") or 0.0)
                        _p_cant  = int(_pp.get("cantidad") or 1)
                        _p_nom   = str(_pp.get("nombre") or "Pieza IA")
                        if _p_largo > 0 and _p_ancho > 0:
                            for _ in range(_p_cant):
                                st.session_state.nesting_piezas.append({
                                    "id":       uuid.uuid4().hex[:8],
                                    "nombre":   _p_nom,
                                    "largo":    _p_largo,
                                    "ancho":    _p_ancho,
                                    "cantidad": 1,
                                })
                                _importadas += 1
                    if _importadas:
                        st.success(f"✅ {_importadas} pieza(s) añadidas desde la descripción.")
                        st.rerun()
                    else:
                        st.warning("No se encontraron piezas con medidas válidas en la descripción.")
                else:
                    st.error("La IA no pudo interpretar la descripción. Intenta ser más específico con las medidas.")

    # ── Zona full-width: botón + SVG + métricas ───────────────────────────────
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.divider()

    _btn_space1, _btn_main, _btn_space2 = st.columns([1, 2, 1])
    with _btn_main:
        btn_optimizar = st.button(
            "✂️ Optimizar Corte y Generar Plano",
            use_container_width=True,
            type="primary",
            key="nesting_btn_optimizar",
        )

    if btn_optimizar:
        st.session_state.nesting_error    = ""
        st.session_state.nesting_svg      = None
        st.session_state.nesting_metricas = None

        _piezas_validas = [
            {
                "nombre":   str(p.get("nombre") or "Pieza"),
                "largo":    float(p.get("largo") or 0),
                "ancho":    float(p.get("ancho") or 0),
                "cantidad": 1,
            }
            for p in st.session_state.nesting_piezas
            if float(p.get("largo") or 0) > 0 and float(p.get("ancho") or 0) > 0
        ]

        if not _piezas_validas:
            st.session_state.nesting_error = (
                "Agrega al menos una pieza antes de optimizar."
            )
        else:
            with st.spinner("🔢 Calculando disposición óptima de corte…"):
                try:
                    _svg, _metricas = fn_optimizar_corte_2d(
                        placa_largo, placa_ancho, _piezas_validas
                    )
                    st.session_state.nesting_svg      = _svg
                    st.session_state.nesting_metricas = _metricas
                except Exception as _e:
                    st.session_state.nesting_error = f"Error en el cálculo: {_e}"

    if st.session_state.get("nesting_error"):
        st.markdown(
            f'<div class="plano-error">⚠️ {st.session_state.nesting_error}</div>',
            unsafe_allow_html=True,
        )

    # ── Resultado SVG + métricas ──────────────────────────────────────────────
    _svg_act = st.session_state.get("nesting_svg")
    _met     = st.session_state.get("nesting_metricas")

    if _svg_act and _met:
        _area_retal = _met["area_placa"] - _met["area_utilizada"]
        _mc1, _mc2, _mc3, _mc4 = st.columns(4)
        _mc1.metric("Área Total Placa",  f'{_met["area_placa"]:.2f} m²')
        _mc2.metric(
            "Área Utilizada",
            f'{_met["area_utilizada"]:.2f} m²',
            delta=f'{100 - _met["porcentaje_desperdicio"]:.1f}% aprovechado',
            delta_color="normal",
        )
        _mc3.metric(
            "Retal Sobrante",
            f'{_area_retal:.2f} m²',
            delta=f'{_met["porcentaje_desperdicio"]:.1f}% de merma',
            delta_color="inverse",
        )
        _mc4.metric("Piezas colocadas", _met["piezas_colocadas"])

        if _met.get("piezas_no_caben"):
            _names = ", ".join(str(n) for n in _met["piezas_no_caben"])
            st.warning(
                f"⚠️ Las siguientes piezas **no caben** en la placa actual: **{_names}**. "
                "Considera aumentar las dimensiones de la placa o dividir el proyecto.",
                icon="📐",
            )

        st.markdown(
            fn_wrap_svg_streamlit(_svg_act),
            unsafe_allow_html=True,
        )
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

        _ba1, _ba2, _ba3 = st.columns([1, 1, 2])
        with _ba1:
            st.download_button(
                label="⬇️ Descargar SVG",
                data=_svg_act.encode("utf-8"),
                file_name="nesting_corte.svg",
                mime="image/svg+xml",
                use_container_width=True,
                key="nesting_dl_svg",
            )
        with _ba2:
            try:
                _pdf_bytes = fn_exportar_svg_a_pdf(_svg_act)
                st.download_button(
                    label="📄 Descargar PDF",
                    data=_pdf_bytes,
                    file_name="Plano_Nesting_MCC.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    type="primary",
                    key="nesting_dl_pdf",
                )
            except Exception as _pdf_err:
                st.warning(
                    f"PDF no disponible. SVG descargable. (Detalle: {_pdf_err})",
                    icon="⚠️",
                )

    else:
        st.markdown("""
        <div style="
            border: 2px dashed #C8D8E8; border-radius: 10px;
            padding: 48px 24px; text-align: center;
            background: #F8FAFD; color: #6B85A0;
        ">
            <div style="font-size: 3rem; margin-bottom: 10px">📐</div>
            <div style="font-size: 1.05rem; font-weight: 600; margin-bottom: 6px; color: #1C2B3A">
                El plano de nesting aparecerá aquí
            </div>
            <div style="font-size: 0.82rem; line-height: 1.6">
                Agrega las piezas en el formulario de la izquierda,<br>
                luego presiona <strong>✂️ Optimizar Corte y Generar Plano</strong>.
            </div>
        </div>
        """, unsafe_allow_html=True)
