# ui_dashboard.py — Costo360
# Módulo independiente: Dashboard de Business Intelligence y Analíticas.
# Extraído de app.py mediante el Patrón de Estrangulamiento.
# Todas las dependencias están declaradas aquí.

import calendar

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from calculos import cop
from parametros import BADGE_COLORS


# ── Helpers de formateo (replicados de app.py para independencia total) ───────

def _numero_completo(valor) -> str:
    """Moneda colombiana: $1.250.000"""
    return "$" + f"{int(round(valor)):,}".replace(",", ".")


def _fmt_decimal(valor: float, decimales: int = 2) -> str:
    """Número decimal colombiano: miles=punto, decimal=coma → 3.450,75"""
    fmt = f"{valor:,.{decimales}f}"
    partes = fmt.split(".")
    entero = partes[0].replace(",", ".")
    dec = partes[1] if len(partes) > 1 else ""
    if not dec or all(c == "0" for c in dec):
        return entero
    return f"{entero},{dec}"


def _fmt_m2(valor: float, decimales: int = 3) -> str:
    """Metros cuadrados: 3,450 m²"""
    return _fmt_decimal(valor, decimales) + " m²"


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD — Business Intelligence
# ═══════════════════════════════════════════════════════════════════════════════

def _ui_dashboard(stats_db_fn, stats_retales_fn):
    """
    Renderiza el Dashboard de analíticas del negocio.

    Args:
        stats_db_fn:      Callable — función _stats_db de app.py.
                          Se inyecta para evitar dependencia circular.
        stats_retales_fn: Callable — función _stats_retales de app.py.
                          Se inyecta por la misma razón.
    """
    import pandas as pd

    st.markdown(
        "<h2 style='font-family:Playfair Display,serif;margin-bottom:4px'>Dashboard</h2>"
        "<p style='opacity:0.52;font-size:0.85rem;margin:0 0 20px'>Métricas reales de tu negocio — actualizadas automáticamente con cada cotización.</p>",
        unsafe_allow_html=True,
    )

    _s = stats_db_fn(
        usuario_id=st.session_state.get("usuario_actual", {}).get("id"),
        rol=st.session_state.get("usuario_actual", {}).get("rol", "Admin"),
    )

    # ── Estado vacío ──────────────────────────────────────────────────────────
    if _s["total"] == 0:
        st.markdown(
            '<div style="text-align:center;padding:72px 0;opacity:0.38">'
            '<div style="font-size:3.5rem">📊</div>'
            '<div style="font-size:1rem;font-weight:700;margin-top:10px">Sin datos aún</div>'
            '<div style="font-size:0.85rem;margin-top:6px">Genera tu primera cotización en '
            '<b>Cotizacion Directa</b> para ver métricas aquí.</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.stop()

    # ── KPIs principales ──────────────────────────────────────────────────────
    # Tasa de cierre real (norma B2B): Aprobadas / (Aprobadas + Rechazadas) × 100
    # Los Pendientes se excluyen — solo cuentan decisiones ya tomadas por el cliente.
    _tasa_cierre   = _s["tasa_cierre"]
    _rechazadas    = _s["rechazadas"]
    _margen_fmt    = f"{_s['margen_prom']:.1f}%" if _s["margen_prom"] else "—"
    _facturacion_f = _numero_completo(_s["facturacion"]) if _s["facturacion"] else "$0"

    _k1, _k2, _k3, _k4 = st.columns(4)

    _k1.metric(
        "Cotizaciones totales",
        _s["total"],
        help="Número de cotizaciones creadas desde que usas la app. "
             "Incluye todas: pendientes, aprobadas y rechazadas.",
    )
    _k2.metric(
        "Tasa de cierre",
        f"{_tasa_cierre}%",
        delta=f"{_s['aprobadas']} aprobadas",
        help="De cada 100 cotizaciones con decisión tomada (aprobadas + rechazadas), "
             "cuántas el cliente aprobó. Los pendientes NO se cuentan — solo se miden "
             "decisiones reales. Una tasa saludable en marmolería está entre el 50% y el 70%.",
    )
    _k3.metric(
        "Ingresos Asegurados",
        _facturacion_f,
        help="Dinero asegurado que va a entrar a la empresa, "
             "contando solo los proyectos que el cliente ya aprobó. "
             "No incluye cotizaciones pendientes ni rechazadas.",
    )
    _k4.metric(
        "Margen promedio",
        _margen_fmt,
        help="El porcentaje limpio que le queda a la empresa después de pagar "
             "material, operarios y logística. "
             "Menos del 25% es zona de riesgo. "
             "Entre 30% y 45% es una operación saludable.",
    )

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    # ── KPI: Capital Inmovilizado en Retales ─────────────────────────────────
    try:
        _sr = stats_retales_fn(
            usuario_id=st.session_state.get("usuario_actual", {}).get("id"),
            rol=st.session_state.get("usuario_actual", {}).get("rol", "Admin"),
        )
    except Exception:
        _sr = {"total_piezas": 0, "m2_total": 0.0, "valor_total": 0.0, "por_categoria": []}

    if _sr["total_piezas"] > 0:
        _valor_ret  = _sr["valor_total"]
        _m2_ret     = _sr["m2_total"]
        _piezas_ret = _sr["total_piezas"]
        _proyectos_est = max(1, int(_m2_ret / 1.5))
        _insight = (
            f"Tienes {_numero_completo(_valor_ret)} COP en retales disponibles "
            f"({_fmt_m2(_m2_ret, 2)}, {_piezas_ret} {'pieza' if _piezas_ret == 1 else 'piezas'}). "
            f"Prioriza su uso en proyectos pequeños (~{_proyectos_est} proyectos estimados) "
            "para generar un margen de ganancia superior al 80%."
        )
        st.markdown(
            f"""
            <div style="
                background: linear-gradient(135deg, rgba(201,168,76,0.10) 0%, rgba(27,95,168,0.08) 100%);
                border: 1px solid rgba(201,168,76,0.45);
                border-left: 5px solid #C9A84C;
                border-radius: 12px;
                padding: 16px 20px;
                margin: 4px 0 20px 0;
            ">
                <div style="
                    font-size: 0.68rem; font-weight: 800; letter-spacing: 0.16em;
                    text-transform: uppercase; color: #C9A84C; margin-bottom: 6px;
                ">💎 Capital Inmovilizado Recuperable</div>
                <div style="
                    font-size: 1.8rem; font-weight: 900;
                    font-family: 'Playfair Display', serif;
                    color: var(--text-color); line-height: 1.1; margin-bottom: 4px;
                ">{_numero_completo(_valor_ret)}</div>
                <div style="
                    font-size: 0.8rem; opacity: 0.55; margin-bottom: 12px;
                ">{_fmt_m2(_m2_ret, 2)} disponibles · {_piezas_ret} {'pieza' if _piezas_ret == 1 else 'piezas'} en inventario</div>
                <div style="
                    font-size: 0.84rem; line-height: 1.65;
                    color: var(--text-color); opacity: 0.80;
                    background: rgba(0,0,0,0.04); border-radius: 8px;
                    padding: 10px 14px;
                ">{_insight}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if len(_sr["por_categoria"]) > 1:
            with st.expander("📦 Ver desglose por material"):
                _cols_ret = st.columns(min(len(_sr["por_categoria"]), 4))
                for _ci, (_rcat, _rpzs, _rm2c, _rvalc) in enumerate(_sr["por_categoria"]):
                    _bg, _fg = BADGE_COLORS.get(_rcat, ("#e8f0f8", "#1a4a8a"))
                    _cols_ret[_ci % 4].markdown(
                        f'<div style="background:{_bg};color:{_fg};border-radius:8px;'
                        f'padding:12px 14px;text-align:center;margin-bottom:6px">'
                        f'<div style="font-size:0.7rem;font-weight:800;letter-spacing:0.1em;'
                        f'text-transform:uppercase;margin-bottom:4px">{_rcat}</div>'
                        f'<div style="font-size:1.1rem;font-weight:900">{_numero_completo(_rvalc)}</div>'
                        f'<div style="font-size:0.72rem;opacity:0.7;margin-top:2px">'
                        f'{_fmt_m2(_rm2c, 2)} · {int(_rpzs)} pza.</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

    # ── Alerta de margen ──────────────────────────────────────────────────────
    if _s["margen_prom"] and _s["margen_prom"] < 25:
        st.warning(
            f"⚠️ **Margen promedio bajo ({_s['margen_prom']:.1f}%).** "
            "Estás trabajando en zona de riesgo. Revisa los costos de producción "
            "y logística, o sube ligeramente los precios de venta.",
        )
    elif _s["margen_prom"] and _s["margen_prom"] >= 35:
        st.success(
            f"✅ **Margen promedio saludable ({_s['margen_prom']:.1f}%).** "
            "La empresa está generando buena utilidad por proyecto.",
        )

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    # ── Gráficos: dos columnas ────────────────────────────────────────────────
    _gc1, _gc2 = st.columns(2)

    # ── Gráfico 1: Ventas por material ────────────────────────────────────────
    with _gc1:
        st.markdown(
            "<p style='font-size:0.78rem;font-weight:700;letter-spacing:0.06em;"
            "text-transform:uppercase;opacity:0.5;margin-bottom:8px'>"
            "Facturación por material</p>",
            unsafe_allow_html=True,
        )

        if _s["por_material"]:
            _df_mat = pd.DataFrame(
                _s["por_material"],
                columns=["Material", "Proyectos", "Margen %", "Facturación"],
            ).sort_values("Facturación", ascending=False)

            def _fmt_cop(v):
                return "$" + f"{int(round(v)):,}".replace(",", ".")

            _hover_mat = [
                "<br>".join([
                    f"<b style='font-size:13px'>{r['Material']}</b>",
                    f"Facturación: <b>{_fmt_cop(r['Facturación'])}</b>",
                    f"Proyectos aprobados: <b>{int(r['Proyectos'])}</b>",
                    f"Margen promedio: <b>{r['Margen %']:.1f}%</b>",
                ])
                for _, r in _df_mat.iterrows()
            ]

            _fig_mat = go.Figure(go.Bar(
                x=_df_mat["Material"],
                y=_df_mat["Facturación"],
                marker=dict(
                    color="#1B5FA8",
                    line=dict(color="#0d3d73", width=1.2),
                ),
                customdata=list(zip(
                    [_fmt_cop(v) for v in _df_mat["Facturación"]],
                    _df_mat["Proyectos"].astype(int),
                    _df_mat["Margen %"],
                )),
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "Facturación: <b>%{customdata[0]}</b><br>"
                    "Proyectos: <b>%{customdata[1]}</b><br>"
                    "Margen prom.: <b>%{customdata[2]:.1f}%</b>"
                    "<extra></extra>"
                ),
            ))
            _fig_mat.update_layout(
                height=270,
                margin=dict(t=6, b=4, l=0, r=6),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(
                    tickfont=dict(size=10, color="rgba(200,200,200,0.7)"),
                    gridcolor="rgba(255,255,255,0.07)",
                    tickformat="~s",
                    showgrid=True,
                    zeroline=False,
                ),
                xaxis=dict(
                    tickfont=dict(size=12, color="rgba(200,200,200,0.9)"),
                    showgrid=False,
                ),
                hoverlabel=dict(
                    bgcolor="#0d2a4a",
                    bordercolor="#1B5FA8",
                    font=dict(color="white", size=12, family="monospace"),
                    align="left",
                ),
                bargap=0.35,
            )
            st.plotly_chart(_fig_mat, use_container_width=True, config={"displayModeBar": False})
        else:
            st.caption("Sin datos de materiales aún.")

        with st.expander("💡 ¿Cómo leer este gráfico?"):
            st.info(
                "**Cada barra es un tipo de material** (Mármol, Granito, Sinterizado…) "
                "y su altura representa cuánto dinero has facturado con ese material en proyectos aprobados.\n\n"
                "**¿Qué hacer con esto?**\n"
                "- Si el **Sinterizado** tiene barra alta pero pocos proyectos, "
                "es tu producto más rentable por pieza — vale la pena enfocarte en cotizarlo más.\n"
                "- Si el **Mármol** domina en volumen pero el margen es bajo, "
                "puede que lo estés cotizando por debajo del mercado.\n"
                "- Usa esto para decidir en qué material invertir más en publicidad o stock.",
            )

    # ── Gráfico 2: Tendencia mensual ──────────────────────────────────────────
    with _gc2:
        st.markdown(
            "<p style='font-size:0.78rem;font-weight:700;letter-spacing:0.06em;"
            "text-transform:uppercase;opacity:0.5;margin-bottom:8px'>"
            "Tendencia de facturación mensual</p>",
            unsafe_allow_html=True,
        )

        if _s["por_mes"]:
            _df_mes = pd.DataFrame(
                _s["por_mes"],
                columns=["Mes", "Cotizaciones", "Facturación"],
            ).sort_values("Mes")

            def _fmt_mes(m):
                try:
                    y, mo = str(m).split("-")
                    return f"{calendar.month_abbr[int(mo)]} {y}"
                except Exception:
                    return str(m)
            _df_mes["MesLabel"] = _df_mes["Mes"].apply(_fmt_mes)

            _fmt_cop2 = _numero_completo

            _hover_mes = [
                "<br>".join([
                    f"<b style='font-size:13px'>{r['MesLabel']}</b>",
                    f"Facturación: <b>{_fmt_cop2(r['Facturación'])}</b>",
                    f"Proyectos aprobados: <b>{int(r['Cotizaciones'])}</b>",
                ])
                for _, r in _df_mes.iterrows()
            ]

            _fig_mes = go.Figure()
            _fig_mes.add_trace(go.Scatter(
                x=_df_mes["MesLabel"],
                y=_df_mes["Facturación"],
                mode="lines+markers",
                line=dict(color="#C9A84C", width=2.5, shape="spline"),
                marker=dict(
                    color="#C9A84C", size=8,
                    line=dict(color="#0d0d0d", width=2),
                ),
                fill="tozeroy",
                fillcolor="rgba(201,168,76,0.08)",
                customdata=list(zip(
                    [_fmt_cop2(v) for v in _df_mes["Facturación"]],
                    _df_mes["Cotizaciones"].astype(int),
                    _df_mes["MesLabel"],
                )),
                hovertemplate=(
                    "<b>%{customdata[2]}</b><br>"
                    "Facturación: <b>%{customdata[0]}</b><br>"
                    "Cotizaciones: <b>%{customdata[1]}</b>"
                    "<extra></extra>"
                ),
            ))
            _fig_mes.update_layout(
                height=270,
                margin=dict(t=6, b=4, l=0, r=6),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(
                    tickfont=dict(size=10, color="rgba(200,200,200,0.7)"),
                    gridcolor="rgba(255,255,255,0.07)",
                    tickformat="~s",
                    showgrid=True,
                    zeroline=False,
                ),
                xaxis=dict(
                    tickfont=dict(size=11, color="rgba(200,200,200,0.9)"),
                    showgrid=False,
                    type="category",
                ),
                hoverlabel=dict(
                    bgcolor="#1a1408",
                    bordercolor="#C9A84C",
                    font=dict(color="#f5e6c0", size=12, family="monospace"),
                    align="left",
                ),
            )
            st.plotly_chart(_fig_mes, use_container_width=True, config={"displayModeBar": False})
        else:
            st.caption("Sin datos mensuales aún.")

        with st.expander("💡 ¿Cómo leer este gráfico?"):
            st.info(
                "**Cada punto en la línea es un mes**, y su altura muestra cuánto facturaste ese mes "
                "en proyectos aprobados.\n\n"
                "**¿Qué hacer con esto?**\n"
                "- Si la línea **sube** mes a mes → el negocio está creciendo. ✅\n"
                "- Si la línea **cae dos meses seguidos** → es momento de activar "
                "referencias, ofrecer descuentos estratégicos o revisar precios.\n"
                "- Los meses bajos suelen ser enero y agosto en Barranquilla "
                "(temporada baja de construcción). Es normal, planifica tu flujo de caja.",
            )

    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

    # ── Tabla resumen por material ────────────────────────────────────────────
    if _s["por_material"]:
        st.markdown(
            "<p style='font-size:0.78rem;font-weight:700;letter-spacing:0.06em;"
            "text-transform:uppercase;opacity:0.5;margin-bottom:10px'>"
            "Detalle por material</p>",
            unsafe_allow_html=True,
        )

        _df_det = pd.DataFrame(
            _s["por_material"],
            columns=["Material", "Proyectos aprobados", "Margen promedio %", "Facturación total"],
        )
        _df_det["Margen promedio %"] = _df_det["Margen promedio %"].apply(
            lambda x: f"{x:.1f}%" if x else "—"
        )
        _df_det["Facturación total"] = _df_det["Facturación total"].apply(
            lambda x: _numero_completo(x) if x else "—"
        )
        _df_det = _df_det.sort_values("Proyectos aprobados", ascending=False).reset_index(drop=True)

        def _color_margen(val):
            try:
                v = float(str(val).replace("%", ""))
                if v < 25:   return "color:#e53e3e;font-weight:700"
                if v >= 35:  return "color:#2f855a;font-weight:700"
                return "color:#b7791f;font-weight:600"
            except Exception:
                return ""

        st.dataframe(
            _df_det,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Material":               st.column_config.TextColumn("Material"),
                "Proyectos aprobados":    st.column_config.NumberColumn("Proyectos ✓", format="%d"),
                "Margen promedio %":      st.column_config.TextColumn("Margen prom."),
                "Facturación total":      st.column_config.TextColumn("Facturación"),
            },
        )

        with st.expander("💡 ¿Cómo usar esta tabla?"):
            st.info(
                "Compara el **margen promedio** de cada material con la **facturación total**.\n\n"
                "El material ideal tiene **ambos valores altos**: muchos proyectos y buen margen.\n\n"
                "Si un material tiene margen bajo (menos del 25%), "
                "revisa si estás incluyendo todos los costos en la cotización: "
                "disco, consumibles, riesgo de rotura y logística completa.",
            )

    # ── Resumen de gestión ────────────────────────────────────────────────────
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    with st.container(border=True):
        _rr1, _rr2, _rr3 = st.columns(3)
        _rr1.metric(
            "Pendientes de respuesta",
            _s["pendientes"],
            help="Cotizaciones que enviaste y el cliente aún no ha respondido. "
                 "Si llevan más de 5 días, vale la pena hacer seguimiento.",
        )
        _rr2.metric(
            "Rechazadas",
            max(0, _rechazadas),
            help="Proyectos donde el cliente no aceptó la cotización. "
                 "Si esta cifra es alta, revisa si el precio está por encima del mercado.",
        )
        _rr3.metric(
            "Tasa de rechazo",
            f"{round(_rechazadas / (_rechazadas + _s['aprobadas']) * 100, 1)}%" if (_rechazadas + _s['aprobadas']) > 0 else "—",
            help="Porcentaje de cotizaciones rechazadas sobre las decisiones tomadas (aprobadas + rechazadas). "
                 "Una tasa mayor al 40% es una señal de alerta en precios o presentación.",
        )
