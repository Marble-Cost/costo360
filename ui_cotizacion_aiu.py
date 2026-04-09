# ui_cotizacion_aiu.py
# ─────────────────────────────────────────────────────────────────────────────
# Módulo de Cotización AIU (Administración + Imprevistos + Utilidad)
# Extraído de app.py siguiendo el patrón Strangler Fig (Fase 7).
#
# REGLA ARQUITECTÓNICA: este archivo NUNCA importa app.py.
# Las dependencias de BD y estado global se inyectan como parámetros.
#
# Firma principal:
#   _ui_cotizacion_aiu(
#       fn_guardar_cotizacion,    # (numero, cliente, resultado) -> None
#       fn_actualizar_cotizacion, # (cot_id, numero, cliente, resultado) -> None
#       fn_guardar_config,        # (clave, valor) -> None
#       fn_leer_config,           # (clave, defecto=None) -> Any
#       fn_clave_borrador_aiu,    # () -> str
#       fn_sp_set,                # (key, value) -> None
#       fn_sp_agregar_item_aiu,   # () -> None
#       fn_sp_eliminar_item_aiu,  # (idx) -> None
#       fn_sp_sync_items_aiu,     # (items_nuevos) -> None
#   )
# ─────────────────────────────────────────────────────────────────────────────

import json
import random as _rr
from datetime import date

import streamlit as st

from calculos import calcular_aiu, cop
from parametros import ALOJAMIENTO, AIU_DEFAULTS


# ── UI helpers ────────────────────────────────────────────────────────────────

def _numero_completo(valor) -> str:
    return "$" + f"{int(round(valor)):,}".replace(",", ".")


def _alerta(texto, tipo="info"):
    fn = {"info": st.info, "warning": st.warning,
          "error": st.error, "success": st.success}.get(tipo, st.info)
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


def _hoy() -> date:
    return date.today()


# ── Módulo principal ──────────────────────────────────────────────────────────

def _ui_cotizacion_aiu(
    fn_guardar_cotizacion,
    fn_actualizar_cotizacion,
    fn_guardar_config,
    fn_leer_config,
    fn_clave_borrador_aiu,
    fn_sp_set,
    fn_sp_agregar_item_aiu,
    fn_sp_eliminar_item_aiu,
    fn_sp_sync_items_aiu,
    # Anti-Amnesia dependencies
    fn_sp=None,
    fn_sp_commit_borrador_aiu=None,
    fn_cb_aiu_nombre_cliente=None,
    fn_cb_aiu_numero=None,
    fn_cb_aiu_a_pct=None,
    fn_cb_aiu_i_pct=None,
    fn_cb_aiu_u_pct=None,
    fn_cb_aiu_anticipo=None,
    fn_cb_aiu_incluir_iva=None,
    fn_cb_aiu_telefono_cliente=None,
    fn_cb_aiu_email_cliente=None,
    fn_cb_aiu_ciudad_proyecto=None,
    fn_cb_aiu_dias_entrega=None,
    fn_cb_aiu_dias_validez=None,
):
    """Renderiza la pantalla completa de Cotización AIU (wizard 3 pasos)."""

    # ── Safe fallbacks so function works even if Anti-Amnesia callbacks not injected ──
    def _noop(*a, **kw): pass
    if fn_sp is None:
        fn_sp = lambda: st.session_state.get("store_permanente", {})
    if fn_sp_commit_borrador_aiu is None:
        fn_sp_commit_borrador_aiu = _noop
    if fn_cb_aiu_nombre_cliente   is None: fn_cb_aiu_nombre_cliente   = _noop
    if fn_cb_aiu_numero           is None: fn_cb_aiu_numero           = _noop
    if fn_cb_aiu_a_pct            is None: fn_cb_aiu_a_pct            = _noop
    if fn_cb_aiu_i_pct            is None: fn_cb_aiu_i_pct            = _noop
    if fn_cb_aiu_u_pct            is None: fn_cb_aiu_u_pct            = _noop
    if fn_cb_aiu_anticipo         is None: fn_cb_aiu_anticipo         = _noop
    if fn_cb_aiu_incluir_iva      is None: fn_cb_aiu_incluir_iva      = _noop
    if fn_cb_aiu_telefono_cliente is None: fn_cb_aiu_telefono_cliente = _noop
    if fn_cb_aiu_email_cliente    is None: fn_cb_aiu_email_cliente    = _noop
    if fn_cb_aiu_ciudad_proyecto  is None: fn_cb_aiu_ciudad_proyecto  = _noop
    if fn_cb_aiu_dias_entrega     is None: fn_cb_aiu_dias_entrega     = _noop
    if fn_cb_aiu_dias_validez     is None: fn_cb_aiu_dias_validez     = _noop

    WIZARD_AIU_PASOS = [
        {"icono": "📋", "label": "Ítems"},
        {"icono": "📊", "label": "AIU + Logística"},
        {"icono": "✅", "label": "Resultado"},
    ]
    N_AIU = len(WIZARD_AIU_PASOS)

    if "aiu_paso" not in st.session_state:
        st.session_state.aiu_paso = 0
    if "aiu_success" not in st.session_state:
        st.session_state.aiu_success = False

    # Restaurar borrador AIU desde BD (post-F5)
    if not st.session_state.pre and not st.session_state.get("_borrador_aiu_restaurado"):
        try:
            _borrador_aiu = fn_leer_config(fn_clave_borrador_aiu())
            if _borrador_aiu:
                st.session_state.pre = _borrador_aiu
                if _borrador_aiu.get("aiu_items"):
                    st.session_state.aiu_items = _borrador_aiu["aiu_items"]
                if "aiu_paso" in _borrador_aiu and isinstance(_borrador_aiu["aiu_paso"], int):
                    st.session_state.aiu_paso = _borrador_aiu["aiu_paso"]
                if "editando_id" in _borrador_aiu and _borrador_aiu["editando_id"]:
                    st.session_state["editando_id"] = _borrador_aiu["editando_id"]
                _alerta("📋 Se restauró tu último cálculo AIU.", "info")
        except Exception:
            pass
        st.session_state["_borrador_aiu_restaurado"] = True

    # ══════════════════════════════════════════════════════════════════════════
    # PANTALLA DE ÉXITO AIU
    # ══════════════════════════════════════════════════════════════════════════
    if (
        st.session_state.get("aiu_success")
        and st.session_state.get("cotizacion")
        and "val_u" in st.session_state.cotizacion
    ):
        r_aiu = st.session_state.cotizacion
        nombre_cliente_aiu = st.session_state.pre.get("nombre_cliente", "")
        pct_a = r_aiu.get("pct_a", 2.0)
        pct_i = r_aiu.get("pct_i", 2.0)
        pct_u = r_aiu.get("pct_u", 5.0)

        st.markdown(
            f"""
        <div style="background:linear-gradient(135deg,#1C1C1C 0%,#1F6F54 100%);
                    border-radius:18px;padding:40px 44px 32px;margin-bottom:24px;color:white;
                    box-shadow:0 8px 32px rgba(31,111,84,0.35)">
          <div style="display:flex;align-items:center;gap:16px;margin-bottom:20px">
            <div style="width:52px;height:52px;background:rgba(201,168,76,0.25);border-radius:50%;
                        display:flex;align-items:center;justify-content:center;font-size:1.6rem">&#1C1C1C;</div>
            <div>
              <div style="font-size:0.7rem;letter-spacing:0.14em;text-transform:uppercase;
                          color:#C9A45C;font-weight:700;margin-bottom:2px">OFERTA AIU FINALIZADA</div>
              <div style="font-size:1.1rem;font-weight:700">{nombre_cliente_aiu or "Sin nombre de proyecto"}</div>
            </div>
          </div>
          <div style="font-size:0.72rem;text-transform:uppercase;letter-spacing:0.12em;
                      color:rgba(255,255,255,0.55);font-weight:700;margin-bottom:6px">
            Precio total del contrato (A+I+U+IVA)
          </div>
          <div style="font-size:clamp(1.5rem,5vw,3.8rem);font-weight:900;
                      font-family:'Playfair Display',serif;line-height:1.1;
                      margin-bottom:8px;word-break:break-word">
            {_numero_completo(r_aiu["precio_total"])}
          </div>
          <div style="opacity:0.75;font-size:0.9rem">
            Margen efectivo: {r_aiu["margen_pct"]:.1f}% &nbsp;&middot;&nbsp;
            A({pct_a}%) + I({pct_i}%) + U({pct_u}%) + IVA
          </div>
        </div>""",
            unsafe_allow_html=True,
        )

        _iva_lbl_sc = (
            "IVA 19% (solo sobre Utilidad)"
            if r_aiu.get("incluir_iva", True)
            else "IVA (Exento - Regimen Simplificado)"
        )
        with st.expander("📊 Ver desglose AIU", expanded=False):
            _bloque_costos(
                [
                    ("Costo Directo (CD)",             r_aiu["cd"]),
                    (f"A - Administracion ({pct_a}%)", r_aiu["val_a"]),
                    (f"I - Imprevistos ({pct_i}%)",    r_aiu["val_i"]),
                    (f"U - Utilidad ({pct_u}%)",        r_aiu["val_u"]),
                    (_iva_lbl_sc,                       r_aiu["val_iva"]),
                    ("Logistica",                       r_aiu["logistica"]),
                    ("Viaticos",                        r_aiu.get("viaticos", 0)),
                ],
                "PRECIO TOTAL CONTRATO",
                r_aiu["precio_total"],
            )

        st.markdown("---")
        st.markdown("### 📄 Documentos institucionales")
        from generador_pdf import generar_pdf_cotizacion_aiu, generar_cuenta_cobro

        with st.container(border=True):
            st.markdown("**Oferta AIU**")
            _ap1, _ap2 = st.columns([1.5, 1])
            with _ap1:
                num_cot_aiu = st.text_input(
                    "Numero de oferta",
                    value=f"OFE-AIU-{_hoy().strftime('%Y')}-001",
                    key="num_cot_aiu_success",
                )
            with _ap2:
                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                if st.button("📄 Generar Oferta AIU PDF", type="primary", use_container_width=True, key="btn_pdf_aiu"):
                    with st.spinner("Generando documento corporativo..."):
                        inclusiones_aiu = ["Ejecución integral de la obra bajo estructura AIU"]
                        exclusiones_aiu = ["Trámites de permisos gubernamentales"]
                        pdf_bytes = generar_pdf_cotizacion_aiu(
                            r_aiu, numero=num_cot_aiu,
                            empresa_info=st.session_state.empresa_info,
                            logo_bytes=st.session_state.logo_bytes,
                            incluir_iva=r_aiu.get("incluir_iva", True),
                            inclusiones=inclusiones_aiu,
                            exclusiones=exclusiones_aiu,
                        )
                    st.download_button(
                        "Descargar Oferta AIU", pdf_bytes,
                        file_name=f"{num_cot_aiu}.pdf", mime="application/pdf",
                        use_container_width=True, key="dl_pdf_aiu",
                    )

        with st.container(border=True):
            st.markdown("**Cuenta de cobro / Factura**")
            _ac1, _ac2 = st.columns(2)
            with _ac1:
                num_cc_aiu  = st.text_input("Numero de cuenta", value=f"FAC-AIU-{_hoy().strftime('%Y')}-001", key="num_cc_aiu_success")
                nom_pag_aiu = st.text_input("Facturar a:", value=nombre_cliente_aiu, key="nom_pag_aiu_success")
            with _ac2:
                nit_pag_aiu = st.text_input("NIT / Rut", value="", key="nit_pag_aiu_success")
            if st.button("📄 Generar Cobro AIU PDF", type="primary", use_container_width=True, key="btn_pdf_cc_aiu"):
                datos_pag = {"nombre": nom_pag_aiu, "nit": nit_pag_aiu, "direccion": ""}
                with st.spinner("Generando documento corporativo..."):
                    cc_bytes = generar_cuenta_cobro(
                        r_aiu, st.session_state.empresa_info.copy(), datos_pag,
                        numero=num_cc_aiu, logo_bytes=st.session_state.logo_bytes,
                    )
                st.download_button(
                    "Descargar Cobro AIU", cc_bytes,
                    file_name=f"{num_cc_aiu}.pdf", mime="application/pdf",
                    use_container_width=True, key="dl_pdf_cc_aiu",
                )

        st.markdown("---")
        _an1, _an2 = st.columns(2)
        with _an1:
            if st.button("🆕 Nueva cotizacion AIU", use_container_width=True, type="primary"):
                for k in ["cotizacion", "pre", "aiu_items", "_aiu_guardada",
                          "_aiu_guardada_num", "_aiu_num_sugerido", "_borrador_aiu_restaurado"]:
                    st.session_state.pop(k, None)
                st.session_state.aiu_paso    = 0
                st.session_state.aiu_success = False
                st.session_state.aiu_items = [
                    {"desc": "Material petreo (suministro)",        "und": "m2",  "cant": 10.0, "punit": 250_000},
                    {"desc": "Mano de obra corte y elaboracion",    "und": "m2",  "cant": 10.0, "punit": 100_000},
                    {"desc": "Instalacion y nivelacion",            "und": "m2",  "cant": 10.0, "punit":  50_000},
                    {"desc": "Insumos (disco, adhesivo, silicona)", "und": "glb", "cant":  1.0, "punit": 150_000},
                ]
                st.rerun()
        with _an2:
            if st.button("Editar esta cotizacion AIU", use_container_width=True):
                st.session_state.aiu_success = False
                st.session_state.aiu_paso    = 0
                st.rerun()

        st.stop()

    # ══════════════════════════════════════════════════════════════════════════
    # BARRA DE PROGRESO
    # ══════════════════════════════════════════════════════════════════════════
    paso_aiu = st.session_state.aiu_paso

    _pasos_aiu_html = ""
    for _i, _p in enumerate(WIZARD_AIU_PASOS):
        if _i < paso_aiu:
            _ds = "background:#1F6F54;color:white;border:2px solid #1F6F54"
            _ls = "color:#1F6F54;font-weight:700"
            _dc = "&#1C1C1C;"
            _cb = "#1F6F54"
            _co = "1"
        elif _i == paso_aiu:
            _ds = "background:#1F6F54;color:white;border:2px solid #1F6F54;box-shadow:0 0 0 4px rgba(31,111,84,0.18)"
            _ls = "color:#1F6F54;font-weight:900"
            _dc = str(_i + 1)
            _cb = "var(--border-color)"
            _co = "0.25"
        else:
            _ds = "background:transparent;color:var(--text-color);border:2px solid var(--border-color);opacity:0.4"
            _ls = "opacity:0.4"
            _dc = str(_i + 1)
            _cb = "var(--border-color)"
            _co = "0.25"

        _pasos_aiu_html += (
            '<div style="display:flex;flex-direction:column;align-items:center;gap:4px;min-width:56px">'
            '<div style="width:32px;height:32px;border-radius:50%;display:flex;align-items:center;'
            'justify-content:center;font-size:0.78rem;font-weight:800;' + _ds + '">' + _dc + '</div>'
            '<div style="font-size:0.65rem;text-align:center;' + _ls + '">' + _p["label"] + '</div>'
            '</div>'
        )
        if _i < N_AIU - 1:
            _pasos_aiu_html += (
                '<div style="flex:1;height:2px;background:' + _cb + ';opacity:' + _co + ';'
                'margin-bottom:14px;align-self:flex-start;margin-top:16px"></div>'
            )

    st.markdown(
        '<div style="display:flex;align-items:flex-start;margin-bottom:24px;'
        'padding:16px 20px;background:var(--secondary-background-color);'
        'border-radius:12px;border:1px solid var(--border-color)">'
        + _pasos_aiu_html + "</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        f"<h2 style='font-family:Playfair Display,serif;margin-bottom:2px'>"
        f"{WIZARD_AIU_PASOS[paso_aiu]['icono']} {WIZARD_AIU_PASOS[paso_aiu]['label']}</h2>"
        f"<p style='opacity:0.6;font-size:0.85rem;margin-bottom:20px'>Paso {paso_aiu + 1} de {N_AIU}</p>",
        unsafe_allow_html=True,
    )

    # Navegacion no-lineal
    st.markdown("<br>", unsafe_allow_html=True)
    _cols_nav_aiu = st.columns(len(WIZARD_AIU_PASOS))
    for _i, _p in enumerate(WIZARD_AIU_PASOS):
        with _cols_nav_aiu[_i]:
            _tipo_btn = "primary" if st.session_state.aiu_paso == _i else "secondary"
            if st.button(
                f"{_p['icono']} {_p['label']}",
                key=f"nav_aiu_{_i}",
                type=_tipo_btn,
                use_container_width=True,
            ):
                st.session_state.aiu_paso = _i
                fn_sp_set("aiu_paso", _i)
                fn_sp_commit_borrador_aiu()
                st.rerun()
    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════════
    # PASO 0 — ITEMS DEL CONTRATO
    # ══════════════════════════════════════════════════════════════════════════
    if paso_aiu == 0:
        _seccion_titulo("Items del contrato", "Lista los trabajos y materiales que incluye la obra")
        nombre_cliente_aiu = st.text_input(
            "Nombre de la constructora o proyecto",
            placeholder="Ej: Constructora ABC S.A.S.",
            value=fn_sp().get("aiu_nombre_cliente", st.session_state.pre.get("nombre_cliente", "")),
            key="cb_aiu_nombre_cliente",
            on_change=fn_cb_aiu_nombre_cliente,
        )

        _aiu_c1, _aiu_c2, _aiu_c3 = st.columns(3)
        with _aiu_c1:
            telefono_cliente_aiu = st.text_input(
                "Teléfono",
                value=fn_sp().get("aiu_telefono_cliente", st.session_state.pre.get("telefono_cliente", "")),
                placeholder="Ej: 300 123 4567",
                key="cb_aiu_telefono_cliente",
                on_change=fn_cb_aiu_telefono_cliente,
            )
        with _aiu_c2:
            email_cliente_aiu = st.text_input(
                "Correo electrónico",
                value=fn_sp().get("aiu_email_cliente", st.session_state.pre.get("email_cliente", "")),
                placeholder="cliente@email.com",
                key="cb_aiu_email_cliente",
                on_change=fn_cb_aiu_email_cliente,
            )
        with _aiu_c3:
            ciudad_proyecto_aiu = st.text_input(
                "Ciudad del proyecto",
                value=fn_sp().get("aiu_ciudad_proyecto", st.session_state.pre.get("ciudad_proyecto", "")),
                placeholder="Ej: Barranquilla",
                key="cb_aiu_ciudad_proyecto",
                on_change=fn_cb_aiu_ciudad_proyecto,
            )

        with st.expander("Como funciona la tabla de items", expanded=False):
            st.markdown("""
Cada fila es un item del contrato. La app suma todos los items para calcular el **Costo Directo (CD)**,
que es la base sobre la que se aplican los porcentajes A, I y U.

| Campo | Que ingresar |
|---|---|
| Descripcion | Nombre del trabajo o material |
| Unidad | m2, ml, glb (global), und |
| Cantidad | Cuantas unidades |
| Precio unitario | Costo por unidad (COP) |
            """)

        nuevos_items = []
        cd_total = 0.0
        for idx, it in enumerate(st.session_state.aiu_items):
            with st.container(border=True):
                _row1a, _row1b = st.columns([5.5, 0.8])
                with _row1a:
                    desc = st.text_input(
                        "Descripcion",
                        value=it["desc"],
                        key=f"aiu_d_{idx}",
                        placeholder="Ej: Suministro e instalacion marmol",
                    )
                with _row1b:
                    st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
                    _can_del = len(st.session_state.aiu_items) > 1
                    if st.button("X", key=f"aiu_del_{idx}", help="Eliminar item", disabled=not _can_del):
                        fn_sp_eliminar_item_aiu(idx)
                        st.rerun()

                _row2a, _row2b, _row2c = st.columns([1.5, 1.5, 3])
                with _row2a:
                    und = st.text_input("Unidad", value=it["und"], key=f"aiu_u_{idx}", placeholder="glb / m2 / ml")
                with _row2b:
                    cant = st.number_input("Cantidad", value=float(it["cant"]), min_value=0.0, step=1.0, key=f"aiu_c_{idx}")
                with _row2c:
                    punit = st.number_input(
                        "Precio unitario (COP)",
                        value=float(it["punit"]),
                        min_value=0.0,
                        step=5_000.0,
                        format="%.0f",
                        key=f"aiu_p_{idx}",
                    )
                    st.markdown(
                        f"<div style='margin-top:-12px;margin-bottom:10px;font-size:0.85rem;"
                        f"color:#1F6F54;font-weight:600;'>Equivalencia: {cop(punit)}</div>",
                        unsafe_allow_html=True,
                    )
                sub = cant * punit
                cd_total += sub
                st.markdown(
                    f'<div style="font-size:0.78rem;font-weight:700;color:#1F6F54;'
                    f'text-align:right;margin-top:2px">Subtotal: {_numero_completo(sub)}</div>',
                    unsafe_allow_html=True,
                )
            nuevos_items.append({"desc": desc, "und": und, "cant": cant, "punit": punit})

        fn_sp_sync_items_aiu(nuevos_items)
        st.session_state.aiu_items = nuevos_items

        if st.button("+ Agregar item", use_container_width=True):
            fn_sp_agregar_item_aiu()
            st.rerun()

        st.markdown(
            f"<div style='background:var(--secondary-background-color);border:1px solid #1F6F54;"
            f"border-left:4px solid #1F6F54;border-radius:8px;padding:12px 18px;margin-top:16px;"
            f"font-size:1.1rem;font-weight:900;color:#1F6F54'>"
            f"Costo Directo total: {_numero_completo(cd_total)}</div>",
            unsafe_allow_html=True,
        )

        st.session_state.pre = {
            **st.session_state.pre,
            "nombre_cliente": nombre_cliente_aiu,
            "telefono_cliente": telefono_cliente_aiu,
            "email_cliente": email_cliente_aiu,
            "ciudad_proyecto": ciudad_proyecto_aiu,
            "cd_total":       cd_total,
        }

    # ══════════════════════════════════════════════════════════════════════════
    # PASO 1 — PORCENTAJES AIU + LOGISTICA
    # ══════════════════════════════════════════════════════════════════════════
    elif paso_aiu == 1:
        cd_total = st.session_state.pre.get(
            "cd_total",
            sum(it["cant"] * it["punit"] for it in st.session_state.aiu_items),
        )
        nombre_cliente_aiu = st.session_state.pre.get("nombre_cliente", "")

        _seccion_titulo(
            "Porcentajes AIU y logistica",
            "Define administracion, imprevistos y utilidad sobre el Costo Directo",
        )

        with st.expander("Que es AIU", expanded=False):
            st.markdown("""
**AIU = Administracion + Imprevistos + Utilidad** - estructura para contratos de construccion en Colombia.

| Componente | Que incluye | Valor tipico |
|---|---|---|
| **A** | Gastos de oficina, seguros, permisos | 1.5% - 3% |
| **I** | Colchon para imprevistos | 1% - 3% |
| **U** | Tu ganancia | 5% - 10% |

El IVA (19%) se aplica **solo sobre la Utilidad (U)** - Decreto 1372/92 Colombia.
            """)

        st.markdown("**Porcentajes sobre el Costo Directo**")
        _pa1, _pa2, _pa3 = st.columns(3)

        with _pa1:
            _a_opts  = ["1%", "1.5%", "2%", "2.5%", "3%", "Otro"]
            _a_pre   = float(st.session_state.pre.get("pct_a", AIU_DEFAULTS["a"]))
            _a_pre_s = (
                f"{int(_a_pre) if _a_pre == int(_a_pre) else _a_pre}%"
                if f"{int(_a_pre) if _a_pre == int(_a_pre) else _a_pre}%" in _a_opts
                else "Otro"
            )
            _a_sel = st.pills("A - Administracion", _a_opts, default=_a_pre_s, key="aiu_pills_a",
                              help="Cubre gastos administrativos del proyecto")
            _a_sel = _a_sel if _a_sel else _a_pre_s
            pct_a  = (
                st.number_input("A% exacto", min_value=0.0, max_value=20.0, value=_a_pre, step=0.5, key="aiu_pct_a_custom")
                if _a_sel in ("Otro", None)
                else float(_a_sel.replace("%", ""))
            )

        with _pa2:
            _i_opts  = ["1%", "1.5%", "2%", "2.5%", "3%", "Otro"]
            _i_pre   = float(st.session_state.pre.get("pct_i", AIU_DEFAULTS["i"]))
            _i_pre_s = (
                f"{int(_i_pre) if _i_pre == int(_i_pre) else _i_pre}%"
                if f"{int(_i_pre) if _i_pre == int(_i_pre) else _i_pre}%" in _i_opts
                else "Otro"
            )
            _i_sel = st.pills("I - Imprevistos", _i_opts, default=_i_pre_s, key="aiu_pills_i",
                              help="Reserva para lo inesperado")
            _i_sel = _i_sel if _i_sel else _i_pre_s
            pct_i  = (
                st.number_input("I% exacto", min_value=0.0, max_value=20.0, value=_i_pre, step=0.5, key="aiu_pct_i_custom")
                if _i_sel in ("Otro", None)
                else float(_i_sel.replace("%", ""))
            )

        with _pa3:
            _u_opts  = ["3%", "5%", "7%", "8%", "10%", "Otro"]
            _u_pre   = float(st.session_state.pre.get("pct_u", AIU_DEFAULTS["u"]))
            _u_pre_s = (
                f"{int(_u_pre) if _u_pre == int(_u_pre) else _u_pre}%"
                if f"{int(_u_pre) if _u_pre == int(_u_pre) else _u_pre}%" in _u_opts
                else "Otro"
            )
            _u_sel = st.pills("U - Utilidad", _u_opts, default=_u_pre_s, key="aiu_pills_u",
                              help="Tu margen de ganancia. El IVA aplica SOLO sobre este valor")
            _u_sel = _u_sel if _u_sel else _u_pre_s
            pct_u  = (
                st.number_input("U% exacto", min_value=0.0, max_value=30.0, value=_u_pre, step=0.5, key="aiu_pct_u_custom")
                if _u_sel in ("Otro", None)
                else float(_u_sel.replace("%", ""))
            )

        st.markdown("---")
        _aiu_iva_col, _ = st.columns([1.5, 1])
        with _aiu_iva_col:
            incluir_iva_aiu = st.toggle(
                "Incluir IVA 19% sobre Utilidad",
                value=st.session_state.pre.get("incluir_iva", True),
                key="aiu_iva_toggle",
                help="Activa si tu empresa es responsable del regimen comun. "
                     "Desactiva si cotizas bajo regimen simplificado (Art. 499 E.T.).",
            )
            if incluir_iva_aiu:
                st.caption("IVA 19% sobre U (Utilidad) - Decreto 1372/92.")
            else:
                st.caption("Sin IVA - regimen simplificado. El total no incluye IVA.")

        # Preview en tiempo real
        _val_a_prev   = cd_total * (pct_a / 100)
        _val_i_prev   = cd_total * (pct_i / 100)
        _val_u_prev   = cd_total * (pct_u / 100)
        _val_iva_prev = _val_u_prev * 0.19 if incluir_iva_aiu else 0.0
        _total_prev   = cd_total + _val_a_prev + _val_i_prev + _val_u_prev + _val_iva_prev
        _iva_label    = (
            f"IVA: <strong>{_numero_completo(_val_iva_prev)}</strong>"
            if incluir_iva_aiu
            else "<span style='opacity:0.45;text-decoration:line-through'>IVA: Exento</span>"
        )
        st.markdown(
            f"""<div style="background:var(--secondary-background-color);border:1px solid var(--border-color);
            border-radius:10px;padding:12px 18px;margin-top:8px;font-size:0.85rem">
            <div style="display:flex;gap:24px;flex-wrap:wrap">
              <span>CD: <strong>{_numero_completo(cd_total)}</strong></span>
              <span>A: <strong>{_numero_completo(_val_a_prev)}</strong></span>
              <span>I: <strong>{_numero_completo(_val_i_prev)}</strong></span>
              <span>U: <strong>{_numero_completo(_val_u_prev)}</strong></span>
              <span>{_iva_label}</span>
              <span style="color:#1F6F54;font-weight:900">Total: {_numero_completo(_total_prev)}</span>
            </div></div>""",
            unsafe_allow_html=True,
        )

        st.markdown("---")

        with st.container(border=True):
            st.markdown("**Logistica**")
            _al1, _al2 = st.columns(2)
            with _al1:
                agente_aiu = st.toggle(
                    "Agente externo trae material",
                    value=bool(st.session_state.pre.get("agente_externo_taller", False)),
                    key="aiu_agente",
                )

            with _al2:
                _km_aiu_opts   = ["0-5 km", "5-15 km", "15-30 km", "30-60 km", "60+ km"]
                _km_aiu_pre    = float(st.session_state.pre.get("km", 10.0))
                _km_aiu_pre_s  = (
                    "0-5 km"   if _km_aiu_pre <= 5  else
                    "5-15 km"  if _km_aiu_pre <= 15 else
                    "15-30 km" if _km_aiu_pre <= 30 else
                    "30-60 km" if _km_aiu_pre <= 60 else "60+ km"
                )
                _km_aiu_sel        = st.pills("Distancia", _km_aiu_opts, default=_km_aiu_pre_s, key="aiu_km_pills")
                _km_aiu_sel        = _km_aiu_sel if _km_aiu_sel else _km_aiu_pre_s
                _km_aiu_defaults   = {"0-5 km": 3, "5-15 km": 10, "15-30 km": 22, "30-60 km": 45, "60+ km": 80}
                _km_aiu_stored     = float(st.session_state.pre.get("km", _km_aiu_pre))
                _km_stored_rango   = (
                    "0-5 km"   if _km_aiu_stored <= 5  else
                    "5-15 km"  if _km_aiu_stored <= 15 else
                    "15-30 km" if _km_aiu_stored <= 30 else
                    "30-60 km" if _km_aiu_stored <= 60 else "60+ km"
                )
                _km_aiu_val_init = (
                    float(_km_aiu_defaults.get(_km_aiu_sel, _km_aiu_pre))
                    if _km_stored_rango != _km_aiu_sel
                    else _km_aiu_stored
                )
                km_aiu = st.number_input("Km exactos (Ida)", min_value=0.0, value=_km_aiu_val_init, step=1.0, key="aiu_km")

            _peaje_aiu_pre = float(st.session_state.pre.get("costo_peaje_total", st.session_state.pre.get("costo_peaje_unitario", 0.0)))
            peajes_aiu_total = st.number_input(
                "💰 Costo Total de Peajes de la Ruta ($)",
                min_value=0,
                value=int(_peaje_aiu_pre),
                step=500,
                format="%d",
                key="aiu_peaje_total",
                help="Ingresa el valor exacto en pesos que pagas en peajes (ida + vuelta). Ej: $39.000 si hay 2 peajes de $19.500.",
            )
            if peajes_aiu_total > 0:
                st.caption(f"Total peajes incluido: **${int(peajes_aiu_total):,}**".replace(",","."))

        with st.container(border=True):
            st.markdown("**Proyecto fuera de Barranquilla?**")
            foraneo_aiu   = st.toggle("Si, fuera de la ciudad", value=bool(st.session_state.pre.get("foraneo_activo", False)), key="aiu_foraneo")
            tipo_aloj_aiu = "pueblo"
            noches_aiu    = 0
            pers_aiu      = 2
            if foraneo_aiu:
                _ff1, _ff2, _ff3 = st.columns(3)
                with _ff1:
                    tipo_aloj_aiu = ALOJAMIENTO[st.selectbox(
                        "Destino",
                        list(ALOJAMIENTO.keys()),
                        index=list(ALOJAMIENTO.keys()).index(
                            next(
                                (k for k, v in ALOJAMIENTO.items() if v == st.session_state.pre.get("tipo_aloj", "pueblo")),
                                list(ALOJAMIENTO.keys())[0],
                            )
                        ),
                        key="aiu_tipo_aloj",
                    )]
                with _ff2:
                    _nc_opts  = ["1", "2", "3", "4", "5+"]
                    _nc_pre   = int(st.session_state.pre.get("noches", 1))
                    _nc_pre_s = str(_nc_pre) if str(_nc_pre) in _nc_opts else ("5+" if _nc_pre > 4 else _nc_opts[0])
                    _nc_sel   = st.pills("Noches", _nc_opts, default=_nc_pre_s, key="aiu_noches_pills")
                    _nc_sel   = _nc_sel if _nc_sel else _nc_pre_s
                    noches_aiu = (
                        int(_nc_sel)
                        if (_nc_sel and _nc_sel != "5+")
                        else st.number_input("Noches (exacto)", min_value=0, value=_nc_pre, step=1, key="aiu_nc_custom")
                    )
                with _ff3:
                    _ps_opts  = ["1", "2", "3", "4", "5+"]
                    _ps_pre   = int(st.session_state.pre.get("personas", 2))
                    _ps_pre_s = str(_ps_pre) if str(_ps_pre) in _ps_opts else ("5+" if _ps_pre > 4 else _ps_opts[0])
                    _ps_sel   = st.pills("Personas", _ps_opts, default=_ps_pre_s, key="aiu_pers_pills")
                    _ps_sel   = _ps_sel if _ps_sel else _ps_pre_s
                    pers_aiu  = (
                        int(_ps_sel)
                        if (_ps_sel and _ps_sel != "5+")
                        else st.number_input("Personas (exacto)", min_value=1, value=_ps_pre, step=1, key="aiu_ps_custom")
                    )

        st.session_state.pre = {
            **st.session_state.pre,
            "nombre_cliente":        nombre_cliente_aiu,
            "pct_a":                 pct_a,
            "pct_i":                 pct_i,
            "pct_u":                 pct_u,
            "incluir_iva":           incluir_iva_aiu,
            "vehiculo_entrega":      "externo",
            "km":                    km_aiu,
            "peajes":                0,
            "costo_peaje_total":     peajes_aiu_total,
            "agente_externo_taller": agente_aiu,
            "foraneo_activo":        foraneo_aiu,
            "tipo_aloj":             tipo_aloj_aiu,
            "noches":                noches_aiu,
            "personas":              pers_aiu,
            "aiu_items":             st.session_state.get("aiu_items", []),
            "tipo_proyecto":         "Licitación AIU",
        }

    # ══════════════════════════════════════════════════════════════════════════
    # PASO 2 — CALCULO Y RESULTADO
    # ══════════════════════════════════════════════════════════════════════════
    elif paso_aiu == 2:
        nombre_cliente_aiu = st.session_state.pre.get("nombre_cliente", "")

        # FIX-3 Live Data Fetching
        _current_aiu_items = st.session_state.get("aiu_items", [])
        _current_iva       = st.session_state.get(
            "aiu_iva_toggle", st.session_state.pre.get("incluir_iva", True)
        )

        cd_total = (
            sum(float(it.get("cant", 0)) * float(it.get("punit", 0)) for it in _current_aiu_items)
            if _current_aiu_items
            else st.session_state.pre.get("cd_total", 0.0)
        )

        pct_a         = st.session_state.pre.get("pct_a",  AIU_DEFAULTS["a"])
        pct_i         = st.session_state.pre.get("pct_i",  AIU_DEFAULTS["i"])
        pct_u         = st.session_state.pre.get("pct_u",  AIU_DEFAULTS["u"])
        vehiculo_aiu  = "externo"
        km_aiu        = st.session_state.pre.get("km",     10.0)
        peajes_aiu    = 0
        peajes_aiu_total = float(st.session_state.pre.get("costo_peaje_total", 0.0))
        agente_aiu    = st.session_state.pre.get("agente_externo_taller", False)
        foraneo_aiu   = st.session_state.pre.get("foraneo_activo",       False)
        tipo_aloj_aiu = st.session_state.pre.get("tipo_aloj",  "pueblo")
        noches_aiu    = st.session_state.pre.get("noches",    0)
        pers_aiu      = st.session_state.pre.get("personas",  2)
        incluir_iva_aiu = _current_iva

        _cot_aiu = st.session_state.cotizacion
        _cot_es_aiu = (
            isinstance(_cot_aiu, dict)
            and "val_u" in _cot_aiu
            and "precio_total" in _cot_aiu
            and "margen_pct" in _cot_aiu
        )
        if not _cot_es_aiu or st.session_state.get("_recalcular_aiu"):
            with st.spinner("Calculando AIU..."):
                res_aiu = calcular_aiu(
                    cd_total, pct_a, pct_i, pct_u, vehiculo_aiu, km_aiu, peajes_aiu,
                    agente_aiu, foraneo_aiu, tipo_aloj_aiu, noches_aiu, pers_aiu,
                    incluir_iva=_current_iva,
                    logistica_override=st.session_state.get("logistica_custom"),
                    viaticos_override=st.session_state.get("viaticos_custom"),
                    costo_peaje_unitario=peajes_aiu_total,
                )
                res_aiu.update({
                    "tipo_proyecto":   "Licitación AIU",
                    "categoria":       "Proyecto Constructora",
                    "referencia":      "Multiple",
                    "m2_real":         0,
                    "ml_proyecto":     0,
                    "costo_total":     cd_total,
                    "precio_sugerido": res_aiu["precio_total"],
                    "incluir_iva":     incluir_iva_aiu,
                })
                res_aiu["_estado_guardado"] = {
                    "nombre_cliente":        nombre_cliente_aiu,
                    "aiu_items":             st.session_state.aiu_items,
                    "pct_a": pct_a, "pct_i": pct_i, "pct_u": pct_u,
                    "tipo_proyecto":         "Licitación AIU",
                    "vehiculo_entrega":      "externo",
                    "km": km_aiu, "peajes": 0, "costo_peaje_total": peajes_aiu_total,
                    "agente_externo_taller": agente_aiu,
                    "foraneo_activo":        foraneo_aiu,
                    "tipo_aloj":             tipo_aloj_aiu,
                    "noches": noches_aiu, "personas": pers_aiu,
                    "incluir_iva":           incluir_iva_aiu,
                    "aiu_paso":              st.session_state.get("aiu_paso", 0),
                    "editando_id":           st.session_state.get("editando_id"),
                }
                st.session_state.cotizacion         = res_aiu
                st.session_state["_recalcular_aiu"] = False
                try:
                    _snap = res_aiu["_estado_guardado"]
                    _hash = hash(json.dumps(_snap, sort_keys=True, default=str))
                    if _hash != st.session_state.get("last_aiu_hash"):
                        fn_guardar_config(fn_clave_borrador_aiu(), _snap)
                        st.session_state["last_aiu_hash"] = _hash
                except Exception:
                    pass

        r = st.session_state.cotizacion

        # Guarda defensiva: si la cotización no es AIU (le faltan claves clave),
        # forzar recálculo en lugar de lanzar KeyError al usuario.
        if not isinstance(r, dict) or "precio_total" not in r or "val_u" not in r:
            st.session_state["_recalcular_aiu"] = True
            st.rerun()

        _num_auto_aiu = f"AIU-{_hoy().strftime('%Y%m%d')}-{_rr.randint(100, 999)}"
        if "aiu_num_auto" not in st.session_state:
            st.session_state.aiu_num_auto = _num_auto_aiu

        # Hero card
        st.markdown(
            f"""
        <div style="background:linear-gradient(135deg,#1C1C1C 0%,#1F6F54 100%);
                    border-radius:14px;padding:28px 36px;margin-bottom:20px;color:white;">
          <div style="color:#C9A45C;font-size:0.68rem;text-transform:uppercase;
                      letter-spacing:0.14em;font-weight:700;margin-bottom:8px">
            Precio total del contrato (AIU)
          </div>
          <div style="font-size:clamp(1.5rem,5vw,3.2rem);font-weight:900;
                      font-family:'Playfair Display',serif;line-height:1.1;
                      margin-bottom:8px;word-break:break-word">
            {_numero_completo(r["precio_total"])}
          </div>
          <div style="opacity:0.8;font-size:0.85rem">
            Margen efectivo: {r["margen_pct"]:.1f}% &nbsp;&middot;&nbsp;
            Utilidad: {_numero_completo(r["val_u"])}
          </div>
        </div>""",
            unsafe_allow_html=True,
        )

        _cres, _ = st.columns([1.5, 1])
        with _cres:
            _iva_lbl_p2 = (
                "IVA 19% exclusivo sobre Utilidad"
                if r.get("incluir_iva", True)
                else "IVA (Exento - Regimen Simplificado)"
            )
            _bloque_costos(
                [
                    ("Costo Directo Base (CD)",        r["cd"]),
                    (f"A - Administracion ({pct_a}%)", r["val_a"]),
                    (f"I - Imprevistos ({pct_i}%)",    r["val_i"]),
                    (f"U - Utilidad ({pct_u}%)",        r["val_u"]),
                    (_iva_lbl_p2,                       r["val_iva"]),
                    ("Gastos logisticos",               r["logistica"]),
                ],
                "PRECIO TOTAL CONTRATO",
                r["precio_total"],
            )

        st.markdown("---")

        # ── Condiciones comerciales AIU ───────────────────────────────────────
        with st.container(border=True):
            st.markdown("**💼 Condiciones comerciales**")
            _aiu_cc1, _aiu_cc2 = st.columns(2)
            with _aiu_cc1:
                dias_entrega_aiu = st.number_input(
                    "Días de entrega",
                    min_value=1, max_value=365,
                    value=int(fn_sp().get("aiu_dias_entrega", st.session_state.pre.get("dias_entrega", 10))),
                    step=1,
                    key="cb_aiu_dias_entrega",
                    on_change=fn_cb_aiu_dias_entrega,
                )
            with _aiu_cc2:
                dias_validez_aiu = st.number_input(
                    "Validez de la oferta (días)",
                    min_value=1, max_value=365,
                    value=int(fn_sp().get("aiu_dias_validez", st.session_state.pre.get("dias_validez", 30))),
                    step=5,
                    key="cb_aiu_dias_validez",
                    on_change=fn_cb_aiu_dias_validez,
                )

        r["dias_entrega"]    = dias_entrega_aiu
        r["dias_validez"]    = dias_validez_aiu
        r["anticipo_pct"]    = st.session_state.pre.get("anticipo_pct", 60)
        r["nombre_cliente"]  = nombre_cliente_aiu
        r["telefono_cliente"] = st.session_state.pre.get("telefono_cliente", "")
        r["email_cliente"]   = st.session_state.pre.get("email_cliente", "")
        r["ciudad_proyecto"] = st.session_state.pre.get("ciudad_proyecto", "")
        st.session_state.cotizacion = r

        _ya_g_aiu         = st.session_state.get("_aiu_guardada", False)
        _editando_id_aiu  = st.session_state.get("editando_id")
        _editando_num_aiu = st.session_state.get("editando_num", "")

        if _editando_id_aiu:
            _alerta(f"**Modo edicion** - modificando **{_editando_num_aiu}**.", "info")
            _au, _an_, _ac_ = st.columns([2, 1.5, 1])
            _btn_au = _au.button("Actualizar AIU", type="primary", use_container_width=True)
            _btn_an = _an_.button("Guardar como nueva", use_container_width=True, key="aiu_nueva")
            _btn_ac = _ac_.button("Cancelar", use_container_width=True, key="aiu_can")
            if _btn_ac:
                st.session_state.pop("editando_id", None)
                st.session_state.pop("editando_num", None)
                st.session_state.aiu_paso = 0
                st.rerun()
            if _btn_au:
                fn_actualizar_cotizacion(_editando_id_aiu, _editando_num_aiu, nombre_cliente_aiu, r)
                st.session_state.pop("editando_id", None)
                st.session_state.pop("editando_num", None)
                st.session_state["_aiu_guardada"]     = True
                st.session_state["_aiu_guardada_num"] = _editando_num_aiu
                st.session_state.aiu_success           = True
                st.rerun()
            if _btn_an:
                st.session_state.pop("editando_id", None)
                st.session_state.pop("editando_num", None)
                st.session_state["_aiu_guardada"] = False
                st.rerun()

        elif not _ya_g_aiu:
            st.markdown(
                """<div style="background:var(--secondary-background-color);
                border:1px solid var(--border-color);border-radius:12px;
                padding:18px 22px;margin-bottom:4px">
                <div style="font-size:0.75rem;font-weight:700;opacity:0.5;
                text-transform:uppercase;margin-bottom:4px">Guardar en historial?</div>
                <div style="font-size:0.88rem;opacity:0.75;margin-bottom:12px">
                Si es una oferta real, guardala. Si es una prueba, puedes omitirlo.
                </div></div>""",
                unsafe_allow_html=True,
            )
            _ag1, _ag2, _ag3 = st.columns([2, 1.5, 1])
            with _ag1:
                _num_g_aiu_inp = st.text_input(
                    "Numero de cotizacion AIU",
                    value=st.session_state.get("aiu_num_auto", _num_auto_aiu),
                    key="num_guardar_aiu_hist",
                    label_visibility="collapsed",
                )
            with _ag2:
                if st.button("Guardar en historial", type="primary", use_container_width=True, key="btn_guardar_aiu_hist"):
                    try:
                        fn_guardar_cotizacion(_num_g_aiu_inp, nombre_cliente_aiu or "Sin nombre", r)
                        st.session_state["_aiu_guardada"]     = True
                        st.session_state["_aiu_guardada_num"] = _num_g_aiu_inp
                        st.session_state.aiu_success           = True
                        st.rerun()
                    except Exception as _eg_aiu:
                        st.error(f"Error al guardar: {_eg_aiu}")
            with _ag3:
                if st.button("Solo borrador", use_container_width=True, key="btn_no_guardar_aiu_hist"):
                    st.session_state["_aiu_guardada"]     = True
                    st.session_state["_aiu_guardada_num"] = ""
                    st.session_state.aiu_success           = True
                    st.toast("Cotizacion AIU calculada como borrador.", icon="📋")
                    st.rerun()
        else:
            st.session_state.aiu_success = True
            st.rerun()

    # ══════════════════════════════════════════════════════════════════════════
    # NAVEGACION INFERIOR
    # ══════════════════════════════════════════════════════════════════════════
    if not st.session_state.get("aiu_success") and paso_aiu < N_AIU - 1:
        st.markdown("---")
        _an_l, _an_r = st.columns(2)

        _puede_continuar = True
        _msg_val         = ""

        if paso_aiu == 0:
            _cd_v = st.session_state.pre.get("cd_total", 0)
            if _cd_v <= 0:
                _puede_continuar = False
                _msg_val = "El Costo Directo es $0. Agrega al menos un item con precio y cantidad."

        with _an_l:
            if paso_aiu > 0:
                if st.button("Atras", use_container_width=True, key="btn_aiu_back"):
                    st.session_state.aiu_paso -= 1
                    fn_sp_set("aiu_paso", st.session_state.aiu_paso)
                    fn_sp_commit_borrador_aiu()
                    st.rerun()

        with _an_r:
            if not _puede_continuar:
                st.warning(_msg_val)
            else:
                _lbl_aiu = "Calcular AIU" if paso_aiu == N_AIU - 2 else "Siguiente"
                if st.button(_lbl_aiu, type="primary", use_container_width=True, key="btn_aiu_next"):
                    st.session_state.aiu_paso += 1
                    fn_sp_set("aiu_paso", st.session_state.aiu_paso)
                    fn_sp_commit_borrador_aiu()
                    if st.session_state.aiu_paso == N_AIU - 1:
                        st.session_state["_recalcular_aiu"] = True
                    st.rerun()
