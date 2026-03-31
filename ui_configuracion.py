# ui_configuracion.py
# ─────────────────────────────────────────────────────────────────────────────
# Módulo de Configuración — Perfil de la Empresa y Preferencias
# Extraído de app.py siguiendo el patrón Strangler Fig (Fase 6).
#
# REGLA ARQUITECTÓNICA: este archivo NUNCA importa app.py.
# Las dependencias de BD se inyectan como parámetros.
#
# Firma principal:
#   _ui_configuracion(
#       fn_guardar_config,   # (clave: str, valor) -> None
#       fn_guardar_logo,     # (logo_bytes: bytes) -> None
#       fn_crear_usuario,    # (username, password, pin, rol, nombre_completo) -> bool
#       fn_listar_usuarios,  # () -> list[tuple(id, username, rol, nombre_completo)]
#       fn_eliminar_usuario, # (uid: int) -> bool
#   )
# ─────────────────────────────────────────────────────────────────────────────

import os
import time

import streamlit as st


def _ui_configuracion(
    fn_guardar_config,
    fn_guardar_logo,
    fn_crear_usuario,
    fn_listar_usuarios,
    fn_eliminar_usuario,
):
    """Renderiza la pestaña completa de Configuración (Perfil de la Empresa)."""

    st.markdown(
        "<h2 style='font-family:Playfair Display,serif'>Perfil de la Empresa y Preferencias</h2>",
        unsafe_allow_html=True,
    )

    _rol_actual = st.session_state.get("usuario_actual", {}).get("rol", "Operario")
    if _rol_actual == "Admin":
        tab_emp, tab_finanzas, tab_logo, tab_usuarios = st.tabs([
            "📄 Datos de Facturación",
            "💰 Finanzas y Bancos",
            "🎨 Identidad Visual",
            "👥 Gestión de Usuarios",
        ])
    else:
        tab_emp, tab_finanzas, tab_logo = st.tabs([
            "📄 Datos de Facturación",
            "💰 Finanzas y Bancos",
            "🎨 Identidad Visual",
        ])
        tab_usuarios = None

    # ── Tab: Datos de Facturación ─────────────────────────────────────────────
    with tab_emp:
        c1, c2 = st.columns(2)
        st.session_state.empresa_info["nombre"] = c1.text_input(
            "Razón Social",
            st.session_state.empresa_info.get("nombre", ""),
            placeholder="Ej: Mi Empresa S.A.S.",
        )
        st.session_state.empresa_info["nit"] = c2.text_input(
            "NIT",
            st.session_state.empresa_info.get("nit", ""),
            placeholder="Ej: NIT: 900.000.000-0",
        )
        st.session_state.empresa_info["ciudad"] = c1.text_input(
            "Ciudad / Dirección",
            st.session_state.empresa_info.get("ciudad", ""),
            placeholder="Ej: Bogotá, Cundinamarca — Colombia",
        )
        st.session_state.empresa_info["tel"] = c2.text_input(
            "Teléfono Comercial",
            st.session_state.empresa_info.get("tel", ""),
            placeholder="Ej: +57 300 000 0000",
        )
        st.session_state.empresa_info["email"] = st.text_input(
            "Correo de contacto",
            st.session_state.empresa_info.get("email", ""),
            placeholder="Ej: ventas@miempresa.com",
        )

        st.markdown("---")
        st.markdown("#### 📝 Términos y Garantías (Aparecen en PDFs)")
        st.session_state.empresa_info["terminos"] = st.text_area(
            "Cláusulas de garantía y condiciones",
            value=st.session_state.empresa_info.get(
                "terminos",
                "Garantía de 1 año en mano de obra de instalación. No cubre manchas por ácidos, "
                "golpes, mal uso o intervención de terceros. Los daños causados por otros gremios "
                "durante la construcción no están cubiertos.",
            ),
            height=110,
            placeholder="Ej: Garantía de 1 año en instalación, no cubre manchas por ácidos...",
            help="Este texto aparecerá en el pie de página de las cotizaciones y cuentas de cobro PDF.",
        )
        st.markdown("")
        if st.button("💾 Guardar datos de la empresa", type="primary", key="btn_save_emp", use_container_width=True):
            try:
                fn_guardar_config("empresa_info", st.session_state.empresa_info)
                st.toast("✅ Datos de la empresa guardados y persistidos correctamente", icon="💾")
            except Exception as _e:
                st.error(f"Error al guardar: {_e}")

    # ── Tab: Finanzas y Bancos ────────────────────────────────────────────────
    with tab_finanzas:
        st.markdown("#### 🏦 Datos Bancarios (Aparecen en los PDFs de cobro)")
        b1, b2 = st.columns(2)
        st.session_state.empresa_info["banco"] = b1.text_input(
            "Banco",
            st.session_state.empresa_info.get("banco", ""),
            placeholder="Ej: Bancolombia",
        )
        _tipos_cuenta = ["Cuenta Corriente Empresas", "Cuenta de Ahorros", "Cuenta Corriente Personal"]
        _tipo_actual  = st.session_state.empresa_info.get("cuenta_tipo", "Cuenta Corriente Empresas")
        _tipo_idx     = _tipos_cuenta.index(_tipo_actual) if _tipo_actual in _tipos_cuenta else 0
        st.session_state.empresa_info["cuenta_tipo"] = b2.selectbox(
            "Tipo de Cuenta", _tipos_cuenta, index=_tipo_idx,
        )
        st.session_state.empresa_info["cuenta_numero"] = b1.text_input(
            "Número de Cuenta",
            st.session_state.empresa_info.get("cuenta_numero", ""),
            placeholder="Ej: 123456789012",
        )

        st.markdown("---")
        st.markdown("#### 📊 Parámetros Comerciales por Defecto")
        a1, a2 = st.columns(2)
        st.session_state.empresa_info["anticipo_pct"] = a1.number_input(
            "Anticipo exigido (%)",
            min_value=10,
            max_value=100,
            value=int(st.session_state.empresa_info.get("anticipo_pct", 60)),
            step=5,
            help="Porcentaje de anticipo estándar que aparece en los PDFs de cotización.",
        )
        st.session_state.empresa_info["dias_validez"] = a2.number_input(
            "Días de validez de la cotización",
            min_value=5,
            max_value=90,
            value=int(st.session_state.empresa_info.get("dias_validez", 30)),
            step=5,
            help="Número de días que la cotización tiene validez comercial.",
        )
        st.session_state.empresa_info["iva_defecto"] = a1.toggle(
            "Incluir IVA 19% por defecto",
            value=bool(st.session_state.empresa_info.get("iva_defecto", False)),
            help="Si se activa, las nuevas cotizaciones incluirán IVA por defecto.",
        )

        # Vista previa bancaria
        _emp = st.session_state.empresa_info
        st.markdown(
            f'<div style="background:var(--secondary-background-color);border:1px solid var(--border-color);'
            f'border-radius:10px;padding:14px 18px;margin-top:12px">'
            f'<div style="font-size:0.75rem;font-weight:700;opacity:0.5;margin-bottom:6px">VISTA PREVIA EN PDF</div>'
            f'<div style="font-size:0.88rem"><strong>{_emp.get("banco", "")}</strong> · {_emp.get("cuenta_tipo", "")} '
            f'· Cta. {_emp.get("cuenta_numero", "")}<br>'
            f'Anticipo: <strong>{_emp.get("anticipo_pct", 60)}%</strong> · '
            f'Validez: <strong>{_emp.get("dias_validez", 30)} días</strong></div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.markdown("")
        if st.button("💾 Guardar finanzas y parámetros comerciales", type="primary", key="btn_save_fin", use_container_width=True):
            try:
                fn_guardar_config("empresa_info", st.session_state.empresa_info)
                st.toast("✅ Datos financieros guardados y persistidos correctamente", icon="💾")
            except Exception as _e:
                st.error(f"Error al guardar: {_e}")

    # ── Tab: Identidad Visual ─────────────────────────────────────────────────
    with tab_logo:
        st.info("El logo se redimensiona automáticamente para el sidebar y los encabezados PDF.", icon="🎨")
        _base_dir_cfg = os.path.dirname(os.path.abspath(__file__))
        _logo_path_cfg = next(
            (
                os.path.join(_base_dir_cfg, n)
                for n in ["logo_corporativo.png", "logo_corporativo.jpg", "logo_corporativo.jpeg"]
                if os.path.exists(os.path.join(_base_dir_cfg, n))
            ),
            None,
        )
        if st.session_state.get("logo_bytes"):
            st.image(st.session_state.logo_bytes, width=220)
            st.caption("✅ Logo personalizado activo (subido por el usuario)")
            if st.button("🗑️ Restablecer Logos de Costo360", type="secondary", use_container_width=True):
                try:
                    st.session_state.logo_bytes = None
                    fn_guardar_logo(b"")
                    st.success("✅ Logo personalizado eliminado. Se han restaurado los logos duales (Claro/Oscuro).")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al limpiar la base de datos: {e}")
        else:
            st.info(
                "🛡️ Modo Dual Activo: El sistema está usando los logos oficiales de alta resolución "
                "que se adaptan automáticamente al modo claro y oscuro de tu dispositivo."
            )

        logo = st.file_uploader("Subir nuevo logo (PNG/JPG)", type=["png", "jpg", "jpeg"])
        if logo:
            _logo_raw = logo.read()
            st.session_state.logo_bytes = _logo_raw
            # FIX-3 Serialización Base64: bytes → str UTF-8 antes de JSON/BD.
            # fn_guardar_logo() usa base64.b64encode(...).decode('utf-8')
            # para evitar el TypeError que json.dumps lanzaría con bytes crudos.
            try:
                fn_guardar_logo(_logo_raw)
            except Exception as _le:
                st.warning(f"Logo guardado en sesión pero no persistido en BD: {_le}")
            st.success("✅ Logo cargado y guardado. Ya aparece en el sidebar y en los PDFs.")
            st.rerun()

    # ── Tab: Gestión de Usuarios (solo Admin) ─────────────────────────────────
    if tab_usuarios is not None:
        with tab_usuarios:
            st.markdown("#### 👥 Gestión de Equipo")
            st.caption(
                "Solo los Administradores pueden registrar nuevos usuarios. "
                "La contraseña se encripta con PBKDF2-SHA256 antes de guardarse."
            )

            # Formulario de registro
            with st.form("form_nuevo_usuario", clear_on_submit=True):
                st.markdown("**Registrar nuevo usuario**")
                _f1, _f2 = st.columns(2)
                _fu_nombre = _f1.text_input(
                    "Nombre completo *",
                    placeholder="Ej: Jorge Castro Díaz",
                )
                _fu_user = _f2.text_input(
                    "Username *",
                    placeholder="Ej: jcastro  (sin espacios)",
                    help="Se guarda en minúsculas automáticamente.",
                )
                _f3, _f4 = st.columns(2)
                _fu_pwd = _f3.text_input(
                    "Contraseña *",
                    type="password",
                    placeholder="Mínimo 6 caracteres",
                )
                _fu_pwd2 = _f4.text_input(
                    "Confirmar contraseña *",
                    type="password",
                    placeholder="Repite la contraseña",
                )
                _f5, _f6 = st.columns(2)
                _fu_pin = _f5.text_input(
                    "PIN de recuperación * (4 dígitos)",
                    placeholder="Ej: 4821",
                    max_chars=4,
                    help="El usuario lo usará para restablecer su contraseña si la olvida.",
                )
                _fu_rol = _f6.selectbox(
                    "Rol *",
                    ["Operario", "Admin"],
                    help="Admin: acceso total. Operario: solo sus cotizaciones.",
                )

                _submit_form = st.form_submit_button(
                    "✅ Registrar usuario",
                    type="primary",
                    use_container_width=True,
                )

            # Validación y ejecución del INSERT (fuera del form para mostrar mensajes)
            if _submit_form:
                _err_form = []
                if not _fu_nombre.strip():
                    _err_form.append("El nombre completo es obligatorio.")
                if not _fu_user.strip() or " " in _fu_user.strip():
                    _err_form.append("El username no puede estar vacío ni contener espacios.")
                if len(_fu_pwd) < 6:
                    _err_form.append("La contraseña debe tener al menos 6 caracteres.")
                elif _fu_pwd != _fu_pwd2:
                    _err_form.append("Las contraseñas no coinciden.")
                if not _fu_pin.strip() or len(_fu_pin.strip()) != 4 or not _fu_pin.strip().isdigit():
                    _err_form.append("El PIN debe tener exactamente 4 dígitos numéricos.")

                if _err_form:
                    for _e in _err_form:
                        st.error(_e, icon="⚠️")
                else:
                    # INSERT seguro y parametrizado — la contraseña ya viene hasheada
                    # desde fn_crear_usuario usando PBKDF2-SHA256
                    _ok_form = fn_crear_usuario(
                        _fu_user.strip().lower(),
                        _fu_pwd,
                        _fu_pin.strip(),
                        _fu_rol,
                        _fu_nombre.strip(),
                    )
                    if _ok_form:
                        st.success(
                            f"✅ Usuario **{_fu_user.strip().lower()}** registrado con rol **{_fu_rol}**.",
                            icon="👤",
                        )
                        st.balloons()
                    else:
                        st.error(
                            "No se pudo crear el usuario. ¿El username ya existe en el sistema?",
                            icon="🚨",
                        )

            st.markdown("---")

            # Listado del equipo registrado
            st.markdown("**Equipo registrado:**")
            _todos_usr  = fn_listar_usuarios()
            _uid_propio = st.session_state.get("usuario_actual", {}).get("id")

            if not _todos_usr:
                st.info("No hay usuarios registrados aún.", icon="ℹ️")
            else:
                # Cabecera de tabla
                _hc0, _hc1, _hc2, _hc3 = st.columns([0.4, 2.8, 1.4, 0.8])
                for _hcol, _hlbl in zip(
                    [_hc0, _hc1, _hc2, _hc3],
                    ["#", "Nombre / Username", "Rol", "Acción"],
                ):
                    _hcol.markdown(
                        f"<span style='font-size:0.67rem;font-weight:700;opacity:0.4;"
                        f"text-transform:uppercase'>{_hlbl}</span>",
                        unsafe_allow_html=True,
                    )
                st.markdown("<hr style='margin:4px 0 8px'>", unsafe_allow_html=True)

                for _i_u, _u in enumerate(_todos_usr):
                    _u_id, _u_name, _u_rol, _u_nom = _u
                    _es_yo = (_u_id == _uid_propio)
                    _uc0, _uc1, _uc2, _uc3 = st.columns([0.4, 2.8, 1.4, 0.8])
                    _uc0.markdown(
                        f"<div style='padding-top:6px;font-size:0.78rem;opacity:0.35'>{_i_u + 1}</div>",
                        unsafe_allow_html=True,
                    )
                    _uc1.markdown(
                        f"<div style='padding-top:3px'>"
                        f"<span style='font-size:0.87rem;font-weight:700'>{_u_nom or _u_name}</span>"
                        f"<br><span style='font-size:0.7rem;opacity:0.45;font-family:monospace'>{_u_name}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    _uc2.markdown(
                        f"<div style='padding-top:7px'>"
                        f"<span style='background:{'#1F6F54' if _u_rol == 'Admin' else '#6b7280'};"
                        f"color:white;font-size:0.63rem;font-weight:700;padding:3px 8px;"
                        f"border-radius:4px;text-transform:uppercase'>{_u_rol}</span>"
                        f"{'<span style=\\\"font-size:0.65rem;opacity:0.4;margin-left:5px\\\">(tú)</span>' if _es_yo else ''}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    with _uc3:
                        if not _es_yo:
                            if st.button("🗑️", key=f"del_usr_{_u_id}", help=f"Eliminar {_u_name}"):
                                fn_eliminar_usuario(_u_id)
                                st.toast(f"Usuario {_u_name} eliminado.", icon="🗑️")
                                st.rerun()
                        else:
                            st.markdown(
                                "<div style='padding-top:6px;font-size:0.7rem;opacity:0.3'>—</div>",
                                unsafe_allow_html=True,
                            )
                    if _i_u < len(_todos_usr) - 1:
                        st.markdown("<hr style='margin:3px 0;opacity:0.15'>", unsafe_allow_html=True)

            st.caption(
                "💡 No puedes eliminarte a ti mismo. "
                "Para transferir el rol Admin, crea primero otro usuario Admin."
            )
