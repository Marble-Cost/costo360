# ui_historial.py — Costo360
# Módulo independiente: Historial de Cotizaciones.
# Extraído de app.py mediante el Patrón de Estrangulamiento.
# Todas las dependencias externas se inyectan como parámetros — sin imports de app.py.

import streamlit as st

from calculos import cop


# ── Helpers de formateo (replicados de app.py para independencia total) ───────

def _numero_completo(valor) -> str:
    """Moneda colombiana: $1.250.000"""
    return "$" + f"{int(round(valor)):,}".replace(",", ".")


def _fmt_ml(valor: float, decimales: int = 2) -> str:
    """Metros lineales: 3,50 ml"""
    fmt = f"{valor:,.{decimales}f}"
    partes = fmt.split(".")
    entero = partes[0].replace(",", ".")
    dec = partes[1] if len(partes) > 1 else ""
    if not dec or all(c == "0" for c in dec):
        return entero + " ml"
    return f"{entero},{dec} ml"


# ═══════════════════════════════════════════════════════════════════════════════
# HISTORIAL DE COTIZACIONES
# ═══════════════════════════════════════════════════════════════════════════════

def _ui_historial(
    fn_listar,
    fn_actualizar_estado,
    fn_eliminar,
    fn_cargar_en_calculadora,
    fn_stats_db,
):
    """
    Renderiza el Historial de cotizaciones.

    Args:
        fn_listar:                 Callable — _listar_cotizaciones de app.py.
        fn_actualizar_estado:      Callable — _actualizar_estado de app.py.
        fn_eliminar:               Callable — _eliminar_cotizacion de app.py.
        fn_cargar_en_calculadora:  Callable — _cargar_en_calculadora de app.py.
        fn_stats_db:               Callable — _stats_db de app.py.
    """
    st.markdown("""
    <div style="margin-bottom:28px;padding-bottom:20px;border-bottom:1px solid rgba(31,111,84,0.2)">
      <div style="font-size:0.65rem;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;
           color:rgba(201,164,92,0.7);margin-bottom:6px">Gestión</div>
      <h2 style="font-family:'Playfair Display',serif;font-size:1.9rem;font-weight:700;
           color:#E8F0EB;margin:0 0 6px">Historial de Cotizaciones</h2>
      <p style="color:rgba(232,240,235,0.5);font-size:0.88rem;margin:0;line-height:1.5">
        Registro completo de proyectos. Filtra, actualiza estados y recarga en el calculador.
      </p>
    </div>
    """, unsafe_allow_html=True)

    # ── Métricas rápidas ──────────────────────────────────────────────────────
    _s = fn_stats_db(
        usuario_id=st.session_state.get("usuario_actual", {}).get("id"),
        rol=st.session_state.get("usuario_actual", {}).get("rol", "Admin"),
    )
    if _s["total"] > 0:
        _tasa = _s["tasa_cierre"]   # Aprobadas / (Aprobadas + Rechazadas) × 100
        _mc1, _mc2, _mc3, _mc4 = st.columns(4)
        _mc1.metric("Total",      _s["total"])
        _mc2.metric("Aprobadas",  _s["aprobadas"],  f"{_tasa}% cierre real")
        _mc3.metric("Pendientes", _s["pendientes"])
        _mc4.metric("Facturado (aprobadas)",
                    _numero_completo(_s["facturacion"]) if _s["facturacion"] else "—")
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
    _rows = fn_listar(
        _bus,
        usuario_id=st.session_state.get("usuario_actual", {}).get("id"),
        rol=st.session_state.get("usuario_actual", {}).get("rol", "Admin"),
    )
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
        return

    _ESTADOS = ["Pendiente", "Aprobada", "Rechazada", "En revision"]

    # Color + icono por estado
    _EC = {
        "Pendiente":   ("#B8962E", "🟡"),
        "Aprobada":    ("#155724", "🟢"),
        "Rechazada":   ("#7B1A1A", "🔴"),
        "En revision": ("#1B5FA8", "🔵"),
    }

    # ── VISTA TARJETAS ────────────────────────────────────────────────────────
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
      <div style="font-size:1rem;font-weight:900;color:#1B5FA8">{_numero_completo(_rpre)}</div>
    </div>
    <div>
      <div style="font-size:0.6rem;font-weight:700;opacity:0.5;text-transform:uppercase;
                  letter-spacing:0.05em">Margen</div>
      <div style="font-size:1rem;font-weight:800;color:{_mrg_color}">
        {f"{float(_rmrg):.0f}%" if _rmrg else "—"}</div>
    </div>
    {"<div><div style='font-size:0.6rem;font-weight:700;opacity:0.5;text-transform:uppercase;letter-spacing:0.05em'>ML</div>" +
     f"<div style='font-size:1rem;font-weight:700'>{_fmt_ml(float(_rml), 1)}</div></div>"
     if _rml and float(_rml) > 0 else ""}
  </div>
</div>""", unsafe_allow_html=True)

                # ── Controles debajo de la tarjeta ────────────────────────
                _ck = f"del_ok_{_rid}"
                if _ck not in st.session_state:
                    st.session_state[_ck] = False

                _ca, _cb, _cc = st.columns([2.2, 1, 0.7])
                with _ca:
                    _new_est = st.selectbox(
                        "Estado", _ESTADOS,
                        index=_ESTADOS.index(_rest) if _rest in _ESTADOS else 0,
                        key=f"est_{_rid}", label_visibility="collapsed"
                    )
                    if _new_est != _rest:
                        fn_actualizar_estado(_rid, _new_est)
                        st.rerun()
                with _cb:
                    if st.button("✏️ Editar", key=f"ed_{_rid}",
                                 use_container_width=True, help="Recargar en la calculadora"):
                        fn_cargar_en_calculadora(_rid, _rnum, _rjson)
                with _cc:
                    if not st.session_state[_ck]:
                        if st.button("🗑️", key=f"del_{_rid}",
                                     use_container_width=True, help="Eliminar"):
                            st.session_state[_ck] = True
                            st.rerun()
                    else:
                        # Placeholder para mantener el layout cuando el diálogo está abajo
                        st.markdown("<div style='height:38px'></div>", unsafe_allow_html=True)

                # Diálogo de confirmación — ancho completo, fuera de columnas estrechas
                if st.session_state.get(_ck):
                    st.markdown(
                        f'<div style="background:rgba(220,38,38,0.07);'
                        f'border:1px solid rgba(220,38,38,0.35);border-radius:10px;'
                        f'padding:12px 16px;margin:6px 0 4px">'
                        f'<div style="font-size:0.85rem;font-weight:700;color:#dc2626;margin-bottom:3px">'
                        f'¿Eliminar esta cotizacion?</div>'
                        f'<div style="font-size:0.78rem;opacity:0.65;line-height:1.4">'
                        f'Se borrara <strong>{_rnum}</strong> y sus sobrantes asociados. '
                        f'Esta accion no se puede deshacer.</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                    _dx, _dy, _ = st.columns([1, 1, 1.8])
                    if _dx.button("🗑️ Eliminar", key=f"dsi_{_rid}",
                                  type="primary", use_container_width=True):
                        fn_eliminar(_rid)
                        st.session_state.pop(_ck, None)
                        st.rerun()
                    if _dy.button("Cancelar", key=f"dno_{_rid}",
                                  use_container_width=True):
                        st.session_state[_ck] = False
                        st.rerun()

                st.markdown("<div style='margin-bottom:14px'></div>",
                            unsafe_allow_html=True)

    # ── VISTA TABLA ───────────────────────────────────────────────────────────
    else:
        _th = st.columns([1.0, 0.9, 2.2, 1.3, 1.2, 0.95, 1.5, 0.55, 0.55])
        for _col, _lbl in zip(_th, ["Número", "Fecha", "Cliente", "Material",
                                    "Precio", "Margen", "Estado", "✏️", "🗑️"]):
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
                f"{_numero_completo(_rpre)}</span>",
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
                fn_actualizar_estado(_rid, _new_est)
                st.rerun()

            if _tc[7].button("✏️", key=f"edt_{_rid}", help="Editar"):
                fn_cargar_en_calculadora(_rid, _rnum, _rjson)

            _ck2 = f"del_ok_t_{_rid}"
            if _ck2 not in st.session_state:
                st.session_state[_ck2] = False
            if not st.session_state[_ck2]:
                if _tc[8].button("🗑️", key=f"delt_{_rid}", help="Eliminar"):
                    st.session_state[_ck2] = True
                    st.rerun()
            else:
                st.markdown(
                    f'<div style="background:rgba(220,38,38,0.08);border:1px solid rgba(220,38,38,0.3);'
                    f'border-radius:8px;padding:10px 14px;margin:4px 0 8px">'
                    f'<div style="font-size:0.82rem;font-weight:700;color:#dc2626;margin-bottom:3px">'
                    f'Eliminar {_rnum} — {_rcli}</div>'
                    f'<div style="font-size:0.76rem;opacity:0.65">'
                    f'Esta accion no se puede deshacer. Se eliminaran tambien los sobrantes asociados.</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
                _dx2, _dy2 = st.columns(2)
                if _dx2.button("Eliminar", key=f"dsit_{_rid}",
                               type="primary", use_container_width=True):
                    fn_eliminar(_rid)
                    st.session_state.pop(_ck2, None)
                    st.rerun()
                if _dy2.button("Cancelar", key=f"dnot_{_rid}",
                               use_container_width=True):
                    st.session_state[_ck2] = False
                    st.rerun()
