# app.py — Costo360 SaaS

import io
import html as _html_mod   # M-04: escape de caracteres HTML en respuestas IA (XSS)
import time
import uuid
import hashlib
import hmac as _hmac_mod
import streamlit as st
from st_cookies_manager import CookieManager
import psycopg2
import contextlib
import json, os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_BOG = ZoneInfo("America/Bogota")

def _hoy() -> date:
    """Fecha actual en zona horaria de Colombia (evita desfase UTC del servidor)."""
    return datetime.now(_BOG).date()
from calculos import (
    calcular_cotizacion_directa, analizar_precio_real,
    calcular_aiu, calcular_logistica, ml_a_m2, cop,
)
from parametros import (
    CATEGORIAS_MATERIAL, ADICIONALES, ETAPAS_OBRA,
    ALOJAMIENTO, AIU_DEFAULTS, TARIFAS, LOGISTICA, VIATICOS,
    BADGE_COLORS, DESCRIPCIONES_CATEGORIA, MATERIALES_CATALOGO,
    ANCHOS_ESTANDAR, TOUR_PASOS, CROSS_SELLING_MAP,
    PROPIEDADES_MATERIAL,
)
from asistente_ia import chat_con_ia, ia_disponible, interpretar_proyecto, generar_resumen_cotizacion, chat_sos, extraer_coordenadas_plano
import plotly.graph_objects as go
from motor_planos import generar_plano_svg, wrap_svg_streamlit, exportar_svg_a_pdf, optimizar_corte_2d
from ui_express import _ui_cotizacion_express
from ui_dashboard import _ui_dashboard
from ui_historial import _ui_historial
from ui_retales import _ui_banco_retales
from ui_nesting import _ui_nesting
from ui_cotizacion_directa import _ui_cotizacion_directa
from ui_cotizacion_aiu import _ui_cotizacion_aiu
from ui_configuracion import _ui_configuracion
from ui_parametros import _ui_parametros

st.set_page_config(
    page_title="Costo360 | Plataforma de Costos B2B",
    page_icon="🪨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Logos de alta resolución en Base64 (carga única al arrancar) ─────────────
import base64 as _base64_mod

def _cargar_logo_b64(ruta: str) -> str:
    """Lee un archivo de imagen y devuelve su contenido como string Base64 UTF-8.
    Devuelve string vacío si el archivo no existe o no puede leerse.
    """
    try:
        # Insensible a mayúsculas: busca coincidencia exacta primero, luego case-insensitive en el directorio
        _target = ruta
        if not os.path.exists(_target):
            _dir = os.path.dirname(ruta)
            _name = os.path.basename(ruta).strip()
            try:
                for _f in os.listdir(_dir):
                    if _f.strip().lower() == _name.lower():
                        _target = os.path.join(_dir, _f)
                        break
            except Exception:
                pass
        if os.path.exists(_target):
            with open(_target, "rb") as _lf:
                return _base64_mod.b64encode(_lf.read()).decode("utf-8")
    except Exception:
        pass
    return ""

def _resolver_logo(nombres_candidatos: list) -> str:
    """Prueba una lista de nombres de archivo en _APP_DIR y devuelve el primero que exista en b64."""
    _dir = os.path.dirname(os.path.abspath(__file__))
    for _n in nombres_candidatos:
        _b = _cargar_logo_b64(os.path.join(_dir, _n))
        if _b:
            return _b
    # Ningún candidato encontrado — advertir en consola (visible en logs de Streamlit)
    st.warning(f"⚠️ Logo no encontrado. Se buscó: {nombres_candidatos} en `{_dir}`. Verifica que el archivo exista con ese nombre exacto.", icon="🖼️")
    return ""

_APP_DIR        = os.path.dirname(os.path.abspath(__file__))
# Nombres con espacio (originales) y con guion bajo (versiones renombradas por el SO/repo)
_LOGO_LIGHT_B64 = _resolver_logo([
    "Logo principal.png",
    "Logo_principal.png",
])
_LOGO_DARK_B64  = _resolver_logo([
    "Logo para versiones oscuras.png",
    "Logo_para_versiones_oscuras.png",
])
# MIME real — ambos archivos son JPEG aunque tengan extensión .png
_LOGO_MIME = "image/jpeg"


def _inyectar_css_global():
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700&display=swap');
        
        html, body, [class*="css"] {
            font-family: 'Inter', sans-serif !important;
        }

        /* Botones primarios */
        .stButton > button[kind="primary"] {
            background-color: #1F6F54 !important;
            color: #FFFFFF !important;
            border: none !important;
            transition: all 0.3s ease;
        }
        .stButton > button[kind="primary"]:hover {
            background-color: #144D3A !important;
            transform: scale(1.02);
        }

        /* Botones secundarios */
        .stButton > button[kind="secondary"] {
            background-color: transparent !important;
            border: 1px solid #1F6F54 !important;
            color: var(--text-color) !important;
            transition: all 0.3s ease;
        }
        .stButton > button[kind="secondary"]:hover {
            border-color: #1F6F54 !important;
            color: #1F6F54 !important;
            box-shadow: 0 2px 4px rgba(31, 111, 84, 0.2);
        }

        /* Métricas en verde de marca */
        div[data-testid="stMetricValue"] {
            color: #1F6F54 !important;
        }

        /* ── Swap automático de logos según esquema del SO ────────────────── */
        .img-logo-light { display: none; width: 100%; max-width: 220px; margin: 0 auto; }
        .img-logo-dark  { display: none; width: 100%; max-width: 220px; margin: 0 auto; }

        @media (prefers-color-scheme: light) {
            .img-logo-light { display: block !important; }
            .img-logo-dark  { display: none  !important; }
        }
        @media (prefers-color-scheme: dark) {
            .img-logo-light { display: none  !important; }
            .img-logo-dark  { display: block !important; }
        }
        </style>
    """, unsafe_allow_html=True)

_inyectar_css_global()

# ── GESTOR DE COOKIES HTTP (st-cookies-manager) ──────────────────────────────
# CookieManager bloquea el renderizado con st.stop() hasta que el componente
# React haya inyectado las cookies del navegador, eliminando la necesidad del
# flag cookies_ok y el rerun manual anterior.
cookies = CookieManager(prefix="costo360_")
if not cookies.ready():
    st.stop()   # Bloqueo estricto — el script no avanza hasta que React hidrate
_COOKIE_TOKEN = "cm_tok"   # Transporta el UUID del token al navegador

# ── INICIALIZACIÓN DE VARIABLES Y NAVEGACIÓN (CON PERSISTENCIA EN URL) ────────
if "primera_visita" not in st.session_state:
    st.session_state.primera_visita = True
    # Leer de la URL si la guía ya fue cerrada — sobrevive a F5
    if st.query_params.get("guia") == "terminada":
        st.session_state.onboarding_activo = False
        st.session_state.tour_completado   = True
    else:
        st.session_state.onboarding_activo = True
        st.session_state.tour_completado   = False
    st.session_state.onboarding_paso = 0

if "nav_radio" not in st.session_state:
    # Leer la página actual desde la URL, si no hay → Inicio
    pag_url = st.query_params.get("pagina", "Inicio")
    st.session_state.nav_radio = pag_url
    st.session_state.radio_ui = pag_url
else:
    # CRÍTICO: sincronizar radio_ui con nav_radio en cada rerun.
    # Sin esto, Streamlit restaura el widget radio al último valor del usuario
    # (ej: "Historial") y sobreescribe una navegación programática al hacer rerun
    # (ej: al cargar una cotización para editar → "Cotizacion Directa").
    st.session_state.radio_ui = st.session_state.nav_radio

# ── BASE DE DATOS POSTGRESQL (SUPABASE) ───────────────────────────────────────
# ── M-01: _init_db se ejecuta UNA SOLA VEZ por proceso Streamlit ──────────────
# @st.cache_resource persiste entre reruns y entre usuarios en el mismo worker.
# Las funciones CRUD ya NO llaman _init_db() — el DDL de arranque está garantizado
# por el bloque `try: _init_db()` en el nivel raíz (línea ~1279, junto a
# _cargar_config_desde_db). Si la BD no está disponible al arrancar, las funciones
# CRUD fallarán igualmente — no tiene sentido reintentar el DDL en cada query.
#
# M-02: _db_conn() es el único punto de creación de conexiones.
# Usar SIEMPRE como context manager:
#
#   with _db_conn() as conn:
#       with conn.cursor() as cur:
#           cur.execute(...)
#       conn.commit()          # ← explícito; psycopg2 no auto-commit
#
# psycopg2: `with conn` solo gestiona transacciones (commit/rollback).
# El cierre de la conexión lo hace el bloque `finally` interno del helper.
# Esto garantiza que NUNCA queden conexiones abiertas, evitando el agotamiento
# del pool de Supabase (error "too many clients").

@st.cache_resource
def _init_db():
    """
    Ejecuta todo el DDL de arranque (CREATE TABLE IF NOT EXISTS + migraciones).
    Llamado UNA VEZ por proceso via @st.cache_resource. No retorna nada útil;
    el decorador cachea el resultado (None) y nunca vuelve a ejecutar el cuerpo.
    """
    conn = psycopg2.connect(st.secrets["DATABASE_URL"])
    cur = conn.cursor()

    # ── Tabla de usuarios (Multi-Tenant) ────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id               SERIAL PRIMARY KEY,
            username         TEXT UNIQUE NOT NULL,
            password_hash    TEXT NOT NULL,
            pin_recuperacion TEXT NOT NULL,
            rol              TEXT NOT NULL DEFAULT 'Operario',
            nombre_completo  TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cotizaciones (
            id SERIAL PRIMARY KEY,
            numero TEXT, fecha TEXT, cliente TEXT, material TEXT,
            tipo TEXT, m2 REAL, ml REAL, costo REAL, precio REAL,
            margen REAL, estado TEXT DEFAULT 'Pendiente', datos_json TEXT
        )
    """)
    # ── Configuración persistente (parámetros, empresa_info, etc.) ────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS app_config (
            clave TEXT PRIMARY KEY,
            valor TEXT NOT NULL,
            actualizado TEXT DEFAULT ''
        )
    """)
    # ── Banco de Retales Digital ────────────────────────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventario_retales (
            id SERIAL PRIMARY KEY,
            material_categoria  TEXT NOT NULL,
            referencia          TEXT,
            m2_disponibles      REAL NOT NULL,
            m2_original         REAL NOT NULL,
            origen_cotizacion_id INTEGER REFERENCES cotizaciones(id) ON DELETE SET NULL,
            origen_numero       TEXT,
            origen_cliente      TEXT,
            fecha_ingreso       TEXT NOT NULL,
            estado              TEXT DEFAULT 'Disponible',
            notas               TEXT,
            precio_recuperacion REAL DEFAULT 0,
            precio_mercado_m2   REAL DEFAULT 0
        )
    """)
    # ── Migraciones seguras: añade columnas nuevas sin romper datos existentes ──
    # ── Tabla de sesiones persistentes (Token Auth) ────────────────────────
    # Token UUID4 por dispositivo, expira en 30 días, validado en BD en cada render.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sesiones (
            id          SERIAL PRIMARY KEY,
            token       TEXT UNIQUE NOT NULL,
            usuario_id  INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
            expires_at  TIMESTAMP NOT NULL,
            device_hint TEXT DEFAULT '',
            created_at  TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_sesiones_token ON sesiones(token)
    """)

    _migraciones = [
        ("inventario_retales", "precio_recuperacion", "REAL DEFAULT 0"),
        ("inventario_retales", "precio_mercado_m2",   "REAL DEFAULT 0"),
        ("cotizaciones",       "usuario_id",          "INTEGER"),
        ("inventario_retales", "usuario_id",          "INTEGER"),
    ]
    for _tbl, _col, _def in _migraciones:
        try:
            cur.execute(
                f"ALTER TABLE {_tbl} ADD COLUMN IF NOT EXISTS {_col} {_def}"
            )
        except Exception:
            conn.rollback()

    conn.commit()
    cur.close()
    conn.close()


from contextlib import contextmanager

@st.cache_resource
def _get_engine():
    """
    Crea el engine de SQLAlchemy UNA SOLA VEZ por proceso (cache_resource).
    pool_size=5 conexiones base + max_overflow=2 de emergencia = máx 7 simultáneas.
    pool_pre_ping=True verifica que la conexión esté viva antes de entregarla.
    """
    from sqlalchemy import create_engine
    return create_engine(
        st.secrets["DATABASE_URL"],
        pool_size=5,
        max_overflow=2,
        pool_pre_ping=True,
    )


class AutoCloseConnection:
    """
    Wrapper sobre raw_connection() de SQLAlchemy que garantiza la devolución
    de la conexión al pool aunque el código llamante no invoque .close().

    — __getattr__: delega transparentemente todos los métodos y atributos
      (.cursor(), .commit(), .rollback(), etc.) a la conexión original,
      por lo que es 100% compatible con psycopg2 sin cambiar ninguna consulta.
    — __del__: el recolector de basura de Python lo invoca automáticamente
      cuando la variable sale del scope al finalizar cada ejecución del
      script de Streamlit, devolviendo la conexión al pool de SQLAlchemy.
    """
    __slots__ = ("_conn", "_closed")

    def __init__(self, conn):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_closed", False)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_conn"), name)

    def close(self):
        """Devuelve la conexión al pool y marca el wrapper como cerrado."""
        if not object.__getattribute__(self, "_closed"):
            object.__getattribute__(self, "_conn").close()
            object.__setattr__(self, "_closed", True)

    def __del__(self):
        """Garantía final: si nadie llamó .close(), el GC lo hace aquí."""
        self.close()


@contextlib.contextmanager
def _db_conn():
    """
    Context manager compatible con psycopg2. Entrega un AutoCloseConnection
    del pool de SQLAlchemy. La conexión se devuelve al pool al salir del bloque
    with, y como garantía adicional también al ser destruida por el GC.
    El resto del código (cursor, commit, rollback) funciona igual que antes.

    INYECCIÓN RLS: declara app.usuario_id con FALSE (persiste en la conexión
    pero NO en la transacción) para que las políticas Row Level Security de
    Supabase puedan aislar datos por taller. Se limpia obligatoriamente en
    finally para evitar fugas en el pool de conexiones de SQLAlchemy.
    """
    conn = AutoCloseConnection(_get_engine().raw_connection())
    try:
        # ── INYECCIÓN RLS: Declarar el usuario activo para toda la sesión de conexión ──
        uid = st.session_state.get("usuario_actual", {}).get("id")
        if uid:
            with conn.cursor() as _cur:
                _cur.execute("SELECT set_config('app.usuario_id', %s, FALSE)", (str(uid),))
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        # ── LIMPIEZA OBLIGATORIA: Prevenir fugas de datos en el pool de conexiones ──
        try:
            with conn.cursor() as _cur:
                _cur.execute("SELECT set_config('app.usuario_id', '', FALSE)")
        except Exception:
            pass
        conn.close()  # devuelve al pool; __del__ es el paracaidas de respaldo



# Por qué: session_state se pierde en cada F5 / reinicio del servidor.
# Solución: guardar en tabla app_config (key-value) y recargar al arrancar.

def _guardar_config(clave: str, valor) -> None:
    """Serializa `valor` como JSON y lo guarda/actualiza en app_config.

    SEGURIDAD MULTI-TENANT: la clave se transforma via _clave_tenant() antes
    de escribir en BD. Claves globales (empresa_info, logo) se escriben sin
    sufijo. Claves operativas llevan sufijo _uUID para aislar datos entre
    usuarios: "tarifas_custom_u12" nunca colisiona con "tarifas_custom_u7".

    FIX-3 Serialización Base64: los bytes se deben convertir a str UTF-8
    antes de llegar aquí (ver _guardar_logo). json.dumps no serializa bytes
    nativamente y lanzaría TypeError silencioso. Se conserva `default=str`
    como red de seguridad, pero la responsabilidad primaria es del llamador.
    """
    _clave_bd = _clave_tenant(clave)
    with _db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO app_config (clave, valor)
                   VALUES (%s, %s)
                   ON CONFLICT (clave) DO UPDATE
                   SET valor = EXCLUDED.valor""",
                (_clave_bd, json.dumps(valor, ensure_ascii=False, default=str))
            )
        conn.commit()

def _leer_config(clave: str, defecto=None):
    """Lee un valor de app_config. Devuelve `defecto` si la clave no existe.

    SEGURIDAD MULTI-TENANT: lee primero la clave tenant (_clave_tenant()).
    Si no existe, intenta la clave sin sufijo (legacy) para migración
    transparente: usuarios existentes no pierden su configuración al
    desplegar este parche. La próxima escritura ya usará la clave tenant.
    """
    try:
        _clave_bd = _clave_tenant(clave)
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT valor FROM app_config WHERE clave = %s", (_clave_bd,))
                row = cur.fetchone()
        if row:
            return json.loads(row[0])
        # Fallback de migración: leer clave legacy solo para claves tenant
        # (_clave_bd != clave significa que se le aplicó sufijo de usuario).
        if _clave_bd != clave:
            try:
                with _db_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT valor FROM app_config WHERE clave = %s", (clave,))
                        row_legacy = cur.fetchone()
                if row_legacy:
                    return json.loads(row_legacy[0])
            except Exception:
                pass
        return defecto
    except Exception:
        return defecto


# ── Helpers Multi-Tenant: claves dinámicas por usuario ───────────────────────

def _uid() -> str:
    """
    Devuelve un sufijo único para el usuario activo.
    Usar en TODAS las claves de borradores y chat para aislar datos
    entre usuarios (FIX-1 Multi-Tenant).

    Formato: str(id) del usuario ─ ej. "12".
    Si por alguna razón no hay sesión activa, devuelve "anon" como fallback
    seguro (no mezcla datos con ningún ID real).
    """
    u = st.session_state.get("usuario_actual")
    if u and u.get("id"):
        return str(u["id"])
    return "anon"

def _clave_tenant(clave: str) -> str:
    """
    Convierte una clave de app_config en una clave aislada por usuario.

    El esquema app_config tiene PRIMARY KEY en (clave), sin columna usuario_id,
    por lo que el aislamiento multi-tenant se implementa sufixando la clave:
        "tarifas_custom"  →  "tarifas_custom_u12"   (usuario id=12)

    Claves GLOBALES (compartidas por todos, no sufixadas):
        empresa_info, empresa_logo_b64
    Claves OPERATIVAS (aisladas por usuario, sufixadas):
        tarifas_custom, logistica_custom, viaticos_custom, adicionales_custom
        y cualquier otra clave de configuración individual.

    El prefijo "_u" hace las claves tenant legibles en la BD y distinguibles
    de las claves legacy sin sufijo (ver fallback en _leer_config).
    """
    _CLAVES_GLOBALES = frozenset({
        "empresa_info",
        "empresa_logo_b64",
    })
    if clave in _CLAVES_GLOBALES:
        return clave
    return f"{clave}_u{_uid()}"

def _clave_borrador_cdir() -> str:
    return f"borrador_cotizacion_directa_{_uid()}"

def _clave_borrador_aiu() -> str:
    return f"borrador_cotizacion_aiu_{_uid()}"


def _generar_snapshot_datos() -> str:
    """
    Captura un fingerprint de los datos críticos del cotizador en el momento actual.
    Se usa para detectar si el usuario modificó algo después de calcular.
    Retorna un string JSON ordenado — si cambia cualquier campo, el string cambia.
    """
    _snap = {
        "materiales": json.dumps(
            st.session_state.get("materiales_proyecto", []),
            sort_keys=True, default=str
        ),
        "piezas": json.dumps(
            [
                {k: v for k, v in p.items()
                 if k in ("nombre", "ml", "ml_unitario", "cantidad", "ancho_custom",
                          "unidad_venta", "categoria")}
                for p in st.session_state.get("piezas", [])
            ],
            sort_keys=True, default=str
        ),
        "margen_pct":    str(st.session_state.get("pre", {}).get("margen_pct", "")),
        # "vehiculo":      str(st.session_state.get("pre", {}).get("vehiculo_entrega", "")),
        "km":            str(st.session_state.get("pre", {}).get("km", "")),
        "peajes":        str(st.session_state.get("pre", {}).get("peajes", "")),
        "foraneo":       str(st.session_state.get("pre", {}).get("foraneo_activo", "")),
        "incluir_iva":   str(st.session_state.get("pre", {}).get("incluir_iva", "")),
        "zocalo_activo": str(st.session_state.get("pre", {}).get("zocalo_activo", "")),
        "zocalo_ml":     str(st.session_state.get("pre", {}).get("zocalo_ml", "")),
    }
    return json.dumps(_snap, sort_keys=True)


# ── Helper Base64 para logo (FIX-3 Serialización) ─────────────────────────

import base64 as _base64

def _guardar_logo(logo_bytes: bytes) -> None:
    """
    Convierte los bytes del logo a string UTF-8 antes de persitir en BD.
    json.dumps lanzaría TypeError si recibe bytes directamente.
    FIX-3: encode → str, decode → bytes al recuperar.
    """
    logo_b64_str = _base64.b64encode(logo_bytes).decode("utf-8")
    _guardar_config("empresa_logo_b64", logo_b64_str)

def _cargar_logo() -> bytes | None:
    """Recupera el logo de la BD y lo devuelve como bytes, o None si no existe."""
    logo_b64_str = _leer_config("empresa_logo_b64")
    if logo_b64_str and isinstance(logo_b64_str, str):
        try:
            return _base64.b64decode(logo_b64_str.encode("utf-8"))
        except Exception:
            return None
    return None

def _cargar_config_desde_db() -> None:
    """
    Hidrata session_state desde Supabase al arrancar la app.
    Solo sobreescribe si el valor en BD es distinto de None/vacío,
    para no pisar datos que el usuario acaba de editar en esta sesión.
    Marcamos con _config_cargada para ejecutarlo solo una vez por sesión.

    FIX-3: el logo se recupera mediante _cargar_logo() que decodifica
    correctamente desde la representación UTF-8 guardada en BD.
    FIX-1: los borradores se leen con claves tenant-específicas para que
    cada usuario vea solo sus propios datos.
    FIX-4: el historial de chat del copiloto IA se recupera por usuario.
    """
    if st.session_state.get("_config_cargada"):
        return

    _CLAVES_CONFIG = [
        ("tarifas_custom",    None),
        ("logistica_custom",  None),
        ("viaticos_custom",   None),
        ("adicionales_custom",None),
        ("empresa_info",      None),
    ]
    for _clave, _def in _CLAVES_CONFIG:
        _val = _leer_config(_clave, _def)
        if _val is not None:
            st.session_state[_clave] = _val

    # FIX-3: cargar logo desde su representación base64 en BD
    if not st.session_state.get("logo_bytes"):
        _logo_db = _cargar_logo()
        if _logo_db:
            st.session_state["logo_bytes"] = _logo_db

    # FIX-4: recuperar historial del chat del copiloto IA (por usuario)
    # Solo se hace al arrancar — si el chat ya tiene mensajes en sesión, no se pisa.
    if not st.session_state.get("chat"):
        try:
            _chat_db = _leer_config(f"chat_{_uid()}")
            if _chat_db and isinstance(_chat_db, list):
                st.session_state["chat"] = _chat_db
        except Exception:
            pass

    # ── PERSISTENCIA TARIFAS DINÁMICAS ───────────────────────────────────────
    # Si hay tarifas_custom guardadas en BD (ya cargadas arriba en _CLAVES_CONFIG),
    # necesitamos hacer tres cosas adicionales que la carga genérica no hace:
    #
    #  1. Marcar setup_tarifas_completado = True para que el usuario no vea
    #     el Wizard de novatos al volver a la pestaña de Parámetros.
    #
    #  2. Pre-cargar tar_recetas_edit (el estado interno del Visual Builder)
    #     para que las reglas aparezcan ya listas sin necesidad de abrir la pestaña.
    #     Usamos la misma lógica _resolver_receta_ui inline para no depender de
    #     funciones definidas más adelante en el archivo.
    #
    #  3. Sincronizar params_tarifas en el store_permanente (si ya existe).
    #     store_permanente puede no existir aún en este punto del arranque;
    #     la sincronización a store se hace al inicializar _sp_init() más adelante.
    try:
        _tc = st.session_state.get("tarifas_custom")
        if _tc and isinstance(_tc, dict) and len(_tc) > 0:
            # 1 — El usuario ya configuró sus tarifas → saltarse el Wizard
            st.session_state["setup_tarifas_completado"] = True
            st.session_state["paso_wizard"] = 1  # reset por seguridad

            # 2 — Pre-cargar tar_recetas_edit solo si el editor no tiene datos
            #     (evitar pisar ediciones en curso dentro de la misma sesión)
            if "tar_recetas_edit" not in st.session_state:
                _recetas_precargadas = {}
                for _m_pc, _entry_pc in _tc.items():
                    if isinstance(_entry_pc, list):
                        # Formato receta v4 — copia directa
                        _recetas_precargadas[_m_pc] = [dict(r) for r in _entry_pc]
                    elif isinstance(_entry_pc, dict):
                        # Formato plano legacy — convertir a receta inline
                        _recetas_precargadas[_m_pc] = [
                            {"nombre_interno": "Elaboración e Instalación",
                             "inductor": "por_ml",
                             "valor": float(_entry_pc.get("prod_ml", 60_000)),
                             "etiqueta_pdf": "c2_mano_obra"},
                            {"nombre_interno": "Mano obra área",
                             "inductor": "por_m2",
                             "valor": float(_entry_pc.get("prod_m2", 35_000)),
                             "etiqueta_pdf": "c2_mano_obra"},
                            {"nombre_interno": "Instalación zócalo",
                             "inductor": "por_ml_zocalo",
                             "valor": float(_entry_pc.get("zocalo", 12_000)),
                             "etiqueta_pdf": "c3_zocalos"},
                            {"nombre_interno": "Desgaste disco",
                             "inductor": "por_m2",
                             "valor": float(_entry_pc.get("disco", 2_200)),
                             "etiqueta_pdf": "c4_insumos"},
                            {"nombre_interno": "Uso máquina cortadora",
                             "inductor": "por_dia",
                             "valor": float(_entry_pc.get("maquina", 20_000)),
                             "etiqueta_pdf": "c4_insumos"},
                            {"nombre_interno": "Consumibles (lijas, masilla, sellador)",
                             "inductor": "por_m2",
                             "valor": float(_entry_pc.get("consumibles", 8_500)),
                             "etiqueta_pdf": "c4_insumos"},
                            {"nombre_interno": "Riesgo rotura",
                             "inductor": "porcentaje_material",
                             "valor": float(_entry_pc.get("riesgo_rotura", 0.02)),
                             "etiqueta_pdf": "c4_insumos"},
                        ]
                if _recetas_precargadas:
                    st.session_state["tar_recetas_edit"] = _recetas_precargadas
    except Exception:
        pass  # Falla silenciosa — la app sigue funcionando con defaults

    st.session_state["_config_cargada"] = True

    # ── Precargar borrador de Cotización Directa desde BD ────────────────────
    # Se hace aquí (en _cargar_config_desde_db) porque en este punto ya tenemos
    # el usuario activo (_uid() funciona) y la BD está disponible.
    # El store_permanente se inicializará después con estos datos pre-cargados.
    if not st.session_state.get("pre"):
        try:
            _borrador = _leer_config(_clave_borrador_cdir())
            if _borrador:
                _borrador["_origen"] = "borrador"
                st.session_state.pre = _borrador
                if "piezas" in _borrador and _borrador["piezas"]:
                    st.session_state.piezas = _borrador["piezas"]
                if "materiales_proyecto" in _borrador and _borrador["materiales_proyecto"]:
                    st.session_state.materiales_proyecto = _borrador["materiales_proyecto"]
        except Exception:
            pass

    # ── Precargar borrador AIU ────────────────────────────────────────────────
    if not st.session_state.get("aiu_items"):
        try:
            _borrador_aiu = _leer_config(_clave_borrador_aiu())
            if _borrador_aiu and _borrador_aiu.get("aiu_items"):
                st.session_state.aiu_items = _borrador_aiu["aiu_items"]
        except Exception:
            pass


# ── CRUD Banco de Retales ─────────────────────────────────────────────────────

def _inyectar_retal(cot_id: int, numero: str, cliente: str, categoria: str, referencia: str,
                    m2_retal: float, precio_m2_original: float = 0):
    """Registra el retal de una cotización aprobada en el inventario."""
    if m2_retal <= 0:
        return
    _uid_act = st.session_state.get("usuario_actual", {}).get("id")
    with _db_conn() as conn:
        with conn.cursor() as cur:
            # Evitar duplicados: solo inyectar una vez por cotización
            cur.execute("SELECT COUNT(*) FROM inventario_retales WHERE origen_cotizacion_id = %s", (cot_id,))
            if cur.fetchone()[0] == 0:
                cur.execute(
                    """INSERT INTO inventario_retales
                       (material_categoria, referencia, m2_disponibles, m2_original,
                        origen_cotizacion_id, origen_numero, origen_cliente, fecha_ingreso,
                        estado, precio_recuperacion, precio_mercado_m2, usuario_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Disponible', 0, %s, %s)""",
                    (categoria, referencia or "", round(m2_retal, 4), round(m2_retal, 4),
                     cot_id, numero, cliente or "Sin nombre", _hoy().isoformat(),
                     round(precio_m2_original, 0), _uid_act)
                )
                conn.commit()

def _consultar_retal(categoria: str, referencia: str,
                     usuario_id: int | None = None, rol: str = "Admin") -> list:
    """
    Retorna retales disponibles para un material/referencia.
    Multi-Tenant: Operario solo ve sus propios retales; Admin ve todos.
    """
    with _db_conn() as conn:
        with conn.cursor() as cur:
            if rol == "Operario" and usuario_id is not None:
                cur.execute(
                    """SELECT id, referencia, m2_disponibles, origen_numero, origen_cliente, fecha_ingreso
                       FROM inventario_retales
                       WHERE material_categoria = %s
                         AND estado = 'Disponible'
                         AND m2_disponibles > 0.05
                         AND usuario_id = %s
                       ORDER BY fecha_ingreso ASC""",
                    (categoria, usuario_id)
                )
            else:
                cur.execute(
                    """SELECT id, referencia, m2_disponibles, origen_numero, origen_cliente, fecha_ingreso
                       FROM inventario_retales
                       WHERE material_categoria = %s
                         AND estado = 'Disponible'
                         AND m2_disponibles > 0.05
                       ORDER BY fecha_ingreso ASC""",
                    (categoria,)
                )
            rows = cur.fetchall()
    # Si hay referencia específica, filtrar por ella; si no, devolver todos del material
    if referencia and referencia.strip():
        filtradas = [r for r in rows if r[1].strip().lower() == referencia.strip().lower()]
        return filtradas if filtradas else rows  # fallback: misma categoría
    return rows

def _marcar_retal_usado(retal_id: int, m2_consumidos: float):
    """Descuenta m² usados; si queda menos de 0.05 m², pasa a Usado."""
    with _db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT m2_disponibles FROM inventario_retales WHERE id = %s", (retal_id,))
            row = cur.fetchone()
            if row:
                nuevo = round(row[0] - m2_consumidos, 4)
                if nuevo <= 0.05:
                    cur.execute("UPDATE inventario_retales SET m2_disponibles=0, estado='Usado' WHERE id=%s", (retal_id,))
                else:
                    cur.execute("UPDATE inventario_retales SET m2_disponibles=%s WHERE id=%s", (nuevo, retal_id))
                conn.commit()


def _guardar_retal_manual(cat: str, ref: str, m2: float, nota: str, usuario_id) -> bool:
    """
    Inserta un retal manual en inventario_retales.
    Función auxiliar expuesta como inyectable para ui_retales.py.
    """
    try:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO inventario_retales
                       (material_categoria, referencia, m2_disponibles, m2_original,
                        fecha_ingreso, estado, notas, usuario_id)
                       VALUES (%s, %s, %s, %s, %s, 'Disponible', %s, %s)""",
                    (cat, ref, m2, m2, _hoy().isoformat(), nota, usuario_id)
                )
            conn.commit()
        _listar_retales.clear()
        _stats_retales.clear()
        return True
    except Exception:
        return False


def _actualizar_precio_retal(retal_id: int, precio: int) -> bool:
    """
    Actualiza el precio_recuperacion de un retal.
    Función auxiliar expuesta como inyectable para ui_retales.py.
    """
    try:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE inventario_retales SET precio_recuperacion=%s WHERE id=%s",
                    (precio, retal_id)
                )
            conn.commit()
        return True
    except Exception:
        return False


@st.cache_data(show_spinner=False)
def _listar_retales(usuario_id=None, rol="Admin") -> list:
    """Lista el banco de retales. Operario ve solo los suyos; Admin ve todos."""
    with _db_conn() as conn:
        with conn.cursor() as cur:
            if rol == "Operario" and usuario_id is not None:
                cur.execute(
                    """SELECT id, material_categoria, referencia, m2_disponibles, m2_original,
                              origen_numero, origen_cliente, fecha_ingreso, estado, notas,
                              COALESCE(precio_recuperacion, 0)
                       FROM inventario_retales
                       WHERE usuario_id = %s
                       ORDER BY estado ASC, fecha_ingreso DESC""",
                    (usuario_id,)
                )
            else:
                cur.execute(
                    """SELECT id, material_categoria, referencia, m2_disponibles, m2_original,
                              origen_numero, origen_cliente, fecha_ingreso, estado, notas,
                              COALESCE(precio_recuperacion, 0)
                       FROM inventario_retales
                       ORDER BY estado ASC, fecha_ingreso DESC"""
                )
            return cur.fetchall()

def _actualizar_notas_retal(retal_id: int, notas: str):
    with _db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE inventario_retales SET notas=%s WHERE id=%s", (notas, retal_id))
        conn.commit()
    # M-07: UPDATE en inventario_retales → solo afecta lecturas de retales
    _listar_retales.clear()

def _eliminar_retal(retal_id: int):
    with _db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM inventario_retales WHERE id=%s", (retal_id,))
        conn.commit()
    # M-07: DELETE en inventario_retales → afecta lista y stats de retales
    _listar_retales.clear()
    _stats_retales.clear()

def _guardar_cotizacion(numero, cliente, resultado):
    _uid = st.session_state.get("usuario_actual", {}).get("id")
    with _db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO cotizaciones (numero,fecha,cliente,material,tipo,m2,ml,costo,precio,margen,estado,datos_json,usuario_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (numero, _hoy().isoformat(), cliente or "Sin nombre",
                 resultado.get("categoria",""), resultado.get("tipo_proyecto",""),
                 resultado.get("m2_real",0), resultado.get("ml_proyecto",0),
                 resultado.get("costo_total",0), resultado.get("precio_sugerido",0),
                 resultado.get("margen_pct",0), "Pendiente",
                 json.dumps(resultado, ensure_ascii=False, default=str), _uid)
            )
        conn.commit()
    # M-07: invalidación quirúrgica — solo las lecturas afectadas por un INSERT en cotizaciones
    _listar_cotizaciones.clear()
    _stats_db.clear()

def _guardar_borrador_cotizacion(resultado: dict, borrador_id: int = None) -> int:
    """
    Guarda o actualiza un borrador en la tabla cotizaciones con estado='Borrador'.
    - Si borrador_id es None → INSERT y retorna el nuevo ID.
    - Si borrador_id tiene valor → UPDATE de ese registro y retorna el mismo ID.
    """
    _uid   = st.session_state.get("usuario_actual", {}).get("id")
    _fecha = _hoy().isoformat()
    _num   = f"BOR-{_fecha}-{(resultado.get('categoria','??'))[:3].upper()}"
    _cli   = resultado.get("nombre_cliente", "") or "Borrador sin nombre"

    if borrador_id:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE cotizaciones SET fecha=%s, cliente=%s, material=%s, tipo=%s, "
                    "m2=%s, ml=%s, costo=%s, precio=%s, margen=%s, datos_json=%s "
                    "WHERE id=%s AND estado='Borrador'",
                    (_fecha, _cli,
                     resultado.get("categoria", ""), resultado.get("tipo_proyecto", ""),
                     resultado.get("m2_real", 0), resultado.get("ml_proyecto", 0),
                     resultado.get("costo_total", 0), resultado.get("precio_sugerido", 0),
                     resultado.get("margen_pct", 0),
                     json.dumps(resultado, ensure_ascii=False, default=str),
                     borrador_id)
                )
            conn.commit()
        _listar_cotizaciones.clear()
        _stats_db.clear()
        return borrador_id
    else:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO cotizaciones "
                    "(numero,fecha,cliente,material,tipo,m2,ml,costo,precio,margen,estado,datos_json,usuario_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (_num, _fecha, _cli,
                     resultado.get("categoria", ""), resultado.get("tipo_proyecto", ""),
                     resultado.get("m2_real", 0), resultado.get("ml_proyecto", 0),
                     resultado.get("costo_total", 0), resultado.get("precio_sugerido", 0),
                     resultado.get("margen_pct", 0), "Borrador",
                     json.dumps(resultado, ensure_ascii=False, default=str), _uid)
                )
                _new_id = cur.fetchone()[0]
            conn.commit()
        _listar_cotizaciones.clear()
        _stats_db.clear()
        return _new_id


def _actualizar_cotizacion(cot_id: int, numero: str, cliente: str, resultado: dict):
    """
    Actualiza una cotización existente en la BD (modo edición).

    C-07 FIX — Inventario Fantasma:
    Al editar una cotización que consume un retal, el inventario debe
    descontarse exactamente igual que en _guardar_cotizacion nueva.

    Lógica de detección: cualquier material en `materiales_proyecto`
    donde `es_retal == True` y `retal_id` sea un entero válido.

    Protección contra doble descuento: _marcar_retal_usado solo hace
    UPDATE si aún hay m² disponibles (la función ya es idempotente cuando
    el estado pasa a 'Usado'). Para mayor seguridad, verificamos aquí que
    el retal no haya sido consumido previamente por ESTA cotización antes
    de descontar, comparando con los materiales del JSON original en BD.
    """
    # ── 1. Leer materiales_proyecto del JSON actualmente en BD ────────────────
    # Esto permite detectar qué retales ya se descontaron en guardados previos
    # y evitar doble descuento si el usuario edita sin cambiar los materiales.
    _retales_ya_descontados: set[int] = set()
    try:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT datos_json FROM cotizaciones WHERE id = %s", (cot_id,))
                _row_prev = cur.fetchone()
        if _row_prev and _row_prev[0]:
            _datos_prev = json.loads(_row_prev[0])
            for _mp in _datos_prev.get("materiales_proyecto", []):
                if _mp.get("es_retal") and _mp.get("retal_id"):
                    _retales_ya_descontados.add(int(_mp["retal_id"]))
    except Exception:
        pass  # Si falla la lectura previa, procedemos sin protección de doble descuento

    # ── 2. Actualizar el registro principal ───────────────────────────────────
    with _db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE cotizaciones
                   SET numero=%s, cliente=%s, material=%s, tipo=%s, m2=%s, ml=%s,
                       costo=%s, precio=%s, margen=%s, datos_json=%s,
                       fecha=%s, estado=%s
                   WHERE id=%s""",
                (
                    numero,
                    cliente or "Sin nombre",
                    resultado.get("categoria", ""),
                    resultado.get("tipo_proyecto", ""),
                    resultado.get("m2_real", 0),
                    resultado.get("ml_proyecto", 0),
                    resultado.get("costo_total", 0),
                    resultado.get("precio_sugerido", 0),
                    resultado.get("margen_pct", 0),
                    json.dumps(resultado, ensure_ascii=False, default=str),
                    # C-06 FIX (incluido aquí): actualizar la fecha para que
                    # el dashboard registre la edición en el período correcto.
                    _hoy().isoformat(),
                    # Bug #8 FIX — Auditoría de Estados: cualquier edición
                    # revoca automáticamente una aprobación previa por seguridad.
                    "Pendiente",
                    cot_id,
                ),
            )
        conn.commit()

    # ── 3. C-07: descontar retales nuevos del inventario ─────────────────────
    # Solo se descuentan retales que NO estaban en el JSON anterior (nuevos en
    # esta edición). Los que ya existían no se tocan para evitar doble descuento.
    for _md in resultado.get("materiales_proyecto", []):
        if not (_md.get("es_retal") and _md.get("retal_id")):
            continue
        _rid = int(_md["retal_id"])
        if _rid in _retales_ya_descontados:
            continue  # Este retal ya fue descontado en un guardado anterior
        try:
            _marcar_retal_usado(_rid, _md.get("area_placa", 0))
        except Exception:
            pass  # No bloquear el guardado si falla el descuento de inventario

    # M-07: invalidación quirúrgica — UPDATE en cotizaciones + posible UPDATE en retales
    _listar_cotizaciones.clear()
    _stats_db.clear()
    _listar_retales.clear()     # por si se consumió un retal en esta edición
    _stats_retales.clear()      # ídem

@st.cache_data(show_spinner=False)
def _listar_cotizaciones(busqueda="", usuario_id=None, rol="Admin"):
    with _db_conn() as conn:
        with conn.cursor() as cur:
            # Multi-tenant: Operario solo ve sus cotizaciones; Admin ve todas
            if rol == "Operario" and usuario_id is not None:
                if busqueda:
                    q = ("SELECT id,numero,fecha,cliente,material,ml,precio,margen,estado,datos_json "
                         "FROM cotizaciones "
                         "WHERE usuario_id = %s AND (cliente ILIKE %s OR numero ILIKE %s OR material ILIKE %s) "
                         "ORDER BY id DESC LIMIT 200")
                    cur.execute(q, (usuario_id, f"%{busqueda}%", f"%{busqueda}%", f"%{busqueda}%"))
                else:
                    cur.execute(
                        "SELECT id,numero,fecha,cliente,material,ml,precio,margen,estado,datos_json "
                        "FROM cotizaciones WHERE usuario_id = %s ORDER BY id DESC LIMIT 200",
                        (usuario_id,)
                    )
            else:
                if busqueda:
                    q = ("SELECT id,numero,fecha,cliente,material,ml,precio,margen,estado,datos_json "
                         "FROM cotizaciones "
                         "WHERE cliente ILIKE %s OR numero ILIKE %s OR material ILIKE %s "
                         "ORDER BY id DESC LIMIT 200")
                    cur.execute(q, (f"%{busqueda}%",)*3)
                else:
                    cur.execute(
                        "SELECT id,numero,fecha,cliente,material,ml,precio,margen,estado,datos_json "
                        "FROM cotizaciones ORDER BY id DESC LIMIT 200"
                    )
            return cur.fetchall()

def _actualizar_estado(cot_id, nuevo_estado):
    with _db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE cotizaciones SET estado=%s WHERE id=%s", (nuevo_estado, cot_id))
        conn.commit()

        # ── Automatización: inyectar retal cuando se aprueba ─────────────────────
        if nuevo_estado == "Aprobada":
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT numero, cliente, material, datos_json FROM cotizaciones WHERE id=%s",
                    (cot_id,)
                )
                row = cur.fetchone()
            if row:
                _numero, _cliente, _material, _datos_json = row
                try:
                    _datos = json.loads(_datos_json) if _datos_json else {}
                    _retal = float(_datos.get("retal", 0))
                    _referencia = _datos.get("referencia", "")
                    _precio_m2_orig = float(_datos.get("precio_m2", 0))
                    if _retal > 0.05:
                        # M-07: aprobación con retal → afecta cotizaciones, stats y retales
                        _listar_cotizaciones.clear()
                        _stats_db.clear()
                        _listar_retales.clear()
                        _stats_retales.clear()
                        _inyectar_retal(cot_id, _numero, _cliente, _material, _referencia, _retal,
                                        precio_m2_original=_precio_m2_orig)
                        return
                except Exception:
                    pass

    # M-07: cambio de estado sin retal → solo afecta cotizaciones y stats
    _listar_cotizaciones.clear()
    _stats_db.clear()

def _eliminar_cotizacion(cot_id):
    """Elimina la cotizacion y sus sobrantes asociados del inventario."""
    with _db_conn() as conn:
        with conn.cursor() as cur:
            # Primero eliminar los sobrantes que provienen de esta cotizacion
            cur.execute(
                "DELETE FROM inventario_retales WHERE origen_cotizacion_id = %s",
                (cot_id,)
            )
            # Luego eliminar la cotizacion
            cur.execute("DELETE FROM cotizaciones WHERE id=%s", (cot_id,))
        conn.commit()
    # M-07: DELETE en cascada afecta cotizaciones Y retales asociados
    _listar_cotizaciones.clear()
    _stats_db.clear()
    _listar_retales.clear()
    _stats_retales.clear()

@st.cache_data(show_spinner=False)
def _stats_db(usuario_id=None, rol="Admin"):
    with _db_conn() as conn:
        with conn.cursor() as cur:
            s = {}
            # Multi-tenant: Operario solo ve sus propias cotizaciones
            _es_op = (rol == "Operario" and usuario_id is not None)
            _w  = "WHERE usuario_id = %s" if _es_op else "WHERE TRUE"
            _p  = (usuario_id,) if _es_op else ()
            cur.execute(f"SELECT COUNT(*) FROM cotizaciones {_w}", _p)
            s["total"]       = cur.fetchone()[0]
            cur.execute(f"SELECT COUNT(*) FROM cotizaciones {_w} AND estado='Aprobada'", _p)
            s["aprobadas"]   = cur.fetchone()[0]
            cur.execute(f"SELECT COUNT(*) FROM cotizaciones {_w} AND estado='Pendiente'", _p)
            s["pendientes"]  = cur.fetchone()[0]
            # Rechazadas: query directa — NO se infiere como total-aprobadas-pendientes
            # porque pueden existir otros estados (ej: "En revisión").
            cur.execute(f"SELECT COUNT(*) FROM cotizaciones {_w} AND estado='Rechazada'", _p)
            s["rechazadas"]  = cur.fetchone()[0]
            cur.execute(f"SELECT SUM(precio) FROM cotizaciones {_w} AND estado='Aprobada'", _p)
            s["facturacion"] = cur.fetchone()[0] or 0
            cur.execute(f"SELECT AVG(margen) FROM cotizaciones {_w} AND estado='Aprobada'", _p)
            s["margen_prom"] = cur.fetchone()[0] or 0
            cur.execute(f"SELECT material,COUNT(*),AVG(margen),SUM(precio) FROM cotizaciones {_w} AND estado='Aprobada' GROUP BY material", _p)
            s["por_material"] = cur.fetchall()
            cur.execute(f"SELECT SUBSTR(fecha,1,7),COUNT(*),SUM(precio) FROM cotizaciones {_w} AND estado='Aprobada' GROUP BY SUBSTR(fecha,1,7) ORDER BY SUBSTR(fecha,1,7) DESC LIMIT 6", _p)
            s["por_mes"]     = cur.fetchall()
    # ── Tasa de cierre real (B2B correcta) ────────────────────────────────────
    # Fórmula: Aprobadas / (Aprobadas + Rechazadas) × 100
    # Los Pendientes se EXCLUYEN — no son decisiones tomadas todavía.
    _cerradas = s["aprobadas"] + s["rechazadas"]
    s["tasa_cierre"] = round(s["aprobadas"] / _cerradas * 100, 1) if _cerradas > 0 else 0.0
    return s


@st.cache_data(show_spinner=False)
def _stats_retales(usuario_id=None, rol="Admin") -> dict:
    """Calcula el capital inmovilizado y métricas del banco de retales."""
    with _db_conn() as conn:
        with conn.cursor() as cur:
            # Multi-tenant: Operario solo ve sus propios retales
            _es_op = (rol == "Operario" and usuario_id is not None)
            _extra = "AND usuario_id = %s" if _es_op else ""
            _p     = (usuario_id,) if _es_op else ()
            cur.execute(f"""
                SELECT
                    material_categoria,
                    COUNT(*) AS piezas,
                    SUM(m2_disponibles) AS m2_total,
                    SUM(m2_disponibles * precio_mercado_m2) AS valor_potencial
                FROM inventario_retales
                WHERE estado = 'Disponible' AND m2_disponibles > 0.05 {_extra}
                GROUP BY material_categoria
                ORDER BY valor_potencial DESC
            """, _p)
            por_categoria = cur.fetchall()
            cur.execute(f"""
                SELECT
                    COUNT(*) AS total_piezas,
                    COALESCE(SUM(m2_disponibles), 0) AS m2_total,
                    COALESCE(SUM(m2_disponibles * precio_mercado_m2), 0) AS valor_total
                FROM inventario_retales
                WHERE estado = 'Disponible' AND m2_disponibles > 0.05 {_extra}
            """, _p)
            row = cur.fetchone()
    return {
        "total_piezas":  int(row[0] or 0),
        "m2_total":      float(row[1] or 0),
        "valor_total":   float(row[2] or 0),
        "por_categoria": por_categoria,
    }

def _chat_parametros(historial: list, mensaje: str) -> str:
    """
    IA Autónoma Ejecutora (Innovación 4).

    El prompt de sistema ahora instruye explícitamente a la IA para que,
    cuando el usuario confirme un cambio, devuelva un JSON estructurado
    con la clave especial "__accion__" que el interceptor de app.py
    procesa automáticamente para actualizar session_state sin acción manual.

    Claves del JSON reconocidas por el interceptor:
      __accion__ : "actualizar_tarifas" | "actualizar_logistica" | "actualizar_viaticos"
      datos      : dict con los valores nuevos en la estructura de TARIFAS / LOGISTICA / VIATICOS
    """
    try:
        SYSTEM_PARAMS = """Eres el asesor de costos operativos de MARMOLES COLLANTE & CASTRO LTDA., Barranquilla, Colombia.
Tu función es ayudar a actualizar los parámetros internos de la empresa: tarifas de producción, viáticos, logística.

CONTEXTO DEL MERCADO (Feb 2026, Barranquilla):
- Gasolina corriente: ~$16.000/galón
- Mano de obra mármol: $55.000–$70.000/ml | Granito: $50.000–$60.000/ml | Sinterizado: $80.000–$95.000/ml
- Hospedaje pueblo: $55.000–$70.000/noche | Ciudad: $80.000–$100.000/noche
- Alimentación diaria: $60.000–$75.000/persona

REGLAS DE RESPUESTA:
- Responde en español colombiano directo, máximo 3 oraciones.
- Si el usuario menciona un precio nuevo, confírmalo y pregunta si desea actualizar.
- Si el usuario CONFIRMA el cambio (dice "sí", "aplica", "actualiza", "correcto", "dale", etc.),
  incluye AL FINAL un bloque ```json con la siguiente estructura EXACTA:

  Para actualizar TARIFAS de producción:
  {"__accion__": "actualizar_tarifas", "datos": {"Material": {"prod_ml": N, "zocalo": N, "disco": N, "maquina": N}}}

  Para actualizar LOGÍSTICA (gasolina, peaje, etc.):
  {"__accion__": "actualizar_logistica", "datos": {"gasolina": N, "peaje": N}}

  Para actualizar VIÁTICOS:
  {"__accion__": "actualizar_viaticos", "datos": {"pueblo": {"hospedaje": N, "alimentacion": N, "transporte_local": N}, "ciudad": {...}}}

- NUNCA incluyas el JSON si el usuario no ha confirmado el cambio.
- NUNCA incluyas texto después del bloque ```json.
- No uses emojis. Sé directo: usa números concretos del mercado de Barranquilla."""
        _prompt_cp = f"{SYSTEM_PARAMS}\n\nHistorial:\n"
        for m in historial:
            _prompt_cp += f"{m['role'].upper()}: {m['content']}\n"
        _prompt_cp += f"USER: {mensaje}"
        return chat_con_ia([], _prompt_cp)
    except Exception as e:
        return f"Error: {str(e)}"


def _interceptar_accion_ia(respuesta_ia: str) -> dict | None:
    """
    Innovación 4 — Interceptor de JSON de IA Autónoma.

    Extrae el JSON de la respuesta de _chat_parametros y retorna:
      {"accion": str, "datos": dict, "campo": str}
    o None si no hay JSON válido.

    La UI de Parámetros llama esta función y aplica el cambio directamente
    en st.session_state sin que el usuario tenga que hacer nada más.
    """
    if "```json" not in respuesta_ia:
        return None
    try:
        raw = respuesta_ia.split("```json")[1].split("```")[0].strip()
        parsed = json.loads(raw)
        accion = parsed.get("__accion__", "")
        datos  = parsed.get("datos", parsed)   # compatibilidad con formato legacy
        if not accion:
            # Formato legacy: intentar detectar por las llaves del JSON
            if any(k in datos for k in ["Mármol", "Granito", "Sinterizado", "Quarztone", "Quarzita"]):
                accion = "actualizar_tarifas"
            elif any(k in datos for k in ["pueblo", "ciudad"]):
                accion = "actualizar_viaticos"
            elif any(k in datos for k in ["gasolina", "peaje", "herram"]):
                accion = "actualizar_logistica"
        return {"accion": accion, "datos": datos} if accion else None
    except Exception:
        return None


# SISTEMA DE AUTENTICACIÓN — Token UUID4 + PostgreSQL + PBKDF2-SHA256
# =============================================================================
#
# F5 / cierre de pestaña / reinicio del servidor NO cierran la sesión.
# El token UUID4 persiste en PostgreSQL con expiración de 30 días.
# La cookie es solo transporte — la fuente de verdad es la tabla `sesiones`.


def _hash_password(password: str) -> str:
    """Hashing PBKDF2-SHA256 con 200.000 iteraciones y salt dinámico único.

    Formato de salida: salt_hex + "$" + key_hex
    El salt se genera con os.urandom(16) — único por contraseña, nunca reutilizado.
    Esto elimina la vulnerabilidad de Rainbow Tables del Bug QA #1.
    """
    salt_bytes = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt_bytes, 200_000)
    return salt_bytes.hex() + "$" + dk.hex()


def _verificar_password(password: str, hash_almacenado: str) -> bool:
    """Verificación segura con retrocompatibilidad estricta.

    Formato nuevo (salt dinámico): "salt_hex$key_hex"
        → Extrae el salt del hash almacenado y recomputa para comparar.
    Formato legacy (salt estático): solo "key_hex" sin "$"
        → Usa el salt estático original para no bloquear al Admin existente.
    """
    partes = hash_almacenado.split("$")
    if len(partes) == 2:
        # ── Formato nuevo: salt dinámico embebido ────────────────────────────
        salt_hex, key_hex = partes
        try:
            salt_bytes = bytes.fromhex(salt_hex)
        except ValueError:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt_bytes, 200_000)
        return _hmac_mod.compare_digest(dk.hex(), key_hex)
    else:
        # ── Formato legacy: salt estático (retrocompatibilidad) ──────────────
        _SALT_LEGACY = b"cc_marmoles_2026_salt"
        dk_legacy = hashlib.pbkdf2_hmac("sha256", password.encode(), _SALT_LEGACY, 200_000)
        return _hmac_mod.compare_digest(dk_legacy.hex(), hash_almacenado)


def _device_hint() -> str:
    """Primeros 60 chars del User-Agent. Solo informativo."""
    try:
        from streamlit.web.server.websocket_headers import _get_websocket_headers
        ua = _get_websocket_headers().get("User-Agent", "")
        return ua[:60]
    except Exception:
        return ""


def _crear_sesion(usuario_id: int) -> str:
    """
    Genera token UUID4, lo persiste en BD por 30 días y escribe la cookie.
    Debe llamarse inmediatamente después de un login exitoso.
    """
    token = str(uuid.uuid4())
    expires = datetime.now() + timedelta(days=30)
    try:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                # Limpiar tokens expirados del usuario (housekeeping silencioso)
                cur.execute(
                    "DELETE FROM sesiones WHERE usuario_id = %s AND expires_at < NOW()",
                    (usuario_id,)
                )
                cur.execute(
                    "INSERT INTO sesiones (token, usuario_id, expires_at, device_hint) "
                    "VALUES (%s, %s, %s, %s)",
                    (token, usuario_id, expires, _device_hint())
                )
            conn.commit()
    except Exception:
        pass   # BD no disponible: el token queda solo en session_state esta sesión
    try:
        cookies[_COOKIE_TOKEN] = token
        cookies.save()
    except Exception:
        pass
    st.session_state["_session_token"] = token
    return token


def _validar_token(token: str) -> int | None:
    """
    Valida el token contra BD. Devuelve usuario_id si es válido y vigente.
    Renueva silenciosamente si quedan menos de 7 días.
    Devuelve None si no existe, expiró o hay error de BD.
    """
    if not token:
        return None
    try:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT usuario_id, expires_at FROM sesiones "
                    "WHERE token = %s AND expires_at > NOW()",
                    (token,)
                )
                row = cur.fetchone()
            if not row:
                return None
            usuario_id, expires_at = row[0], row[1]
            # Renovación automática: si quedan <7 días extender a 30
            if expires_at and (expires_at - datetime.now()).days < 7:
                nueva_exp = datetime.now() + timedelta(days=30)
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE sesiones SET expires_at = %s WHERE token = %s",
                        (nueva_exp, token)
                    )
                conn.commit()
                try:
                    cookies[_COOKIE_TOKEN] = token
                    cookies.save()
                except Exception:
                    pass
        return usuario_id
    except Exception:
        return None


def _leer_token() -> str | None:
    """
    Lee el token desde session_state (rápido) o desde la cookie (F5/nueva pestaña).
    Devuelve None si no hay token — no causa bucle, solo muestra pantalla de login.
    """
    cached = st.session_state.get("_session_token")
    if cached:
        return cached
    try:
        val = cookies.get(_COOKIE_TOKEN)
        if val:
            st.session_state["_session_token"] = val
        return val or None
    except Exception:
        return None


def _limpiar_sesion() -> None:
    """
    Cierra sesión: invalida token en BD, borra cookie y limpia session_state.
    NUNCA toca 'cookies_ok' — es flag de infraestructura del componente React.
    """
    token = st.session_state.get("_session_token")
    if token:
        try:
            with _db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM sesiones WHERE token = %s", (token,))
                conn.commit()
        except Exception:
            pass
    try:
        del cookies[_COOKIE_TOKEN]
        cookies.save()
    except Exception:
        pass
    # ── Borrado profundo: eliminar TODO el estado del tenant ─────────────────
    # La lista hardcodeada anterior dejaba sobrevivir tarifas_custom,
    # logistica_custom, viaticos_custom, tar_recetas_edit, params_wizard_chat,
    # setup_tarifas_completado, wiz_*, aiu_items y más — permitiendo que el
    # próximo usuario en la misma pestaña heredara la configuración del anterior.
    #
    # Preservamos ÚNICAMENTE "cookies_ok": es un flag de infraestructura del
    # componente React (st-cookies-manager). Borrarlo hace que el componente JS
    # quede colgado esperando una cookie que nunca llega en el siguiente render.
    # No contiene datos de negocio ni identificadores de usuario.
    _INFRA_KEYS = frozenset({"cookies_ok"})
    for _k in list(st.session_state.keys()):
        if _k not in _INFRA_KEYS:
            try:
                del st.session_state[_k]
            except Exception:
                pass


def _limpiar_token_invalido() -> None:
    """
    Limpieza liviana para el auth wall: elimina el token inválido/expirado de
    la BD y del session_state, pero NO llama cookies.save().

    Por qué no cookies.save(): llamar save() encola un rerun desde el componente
    React (st-cookies-manager). Si esto ocurre durante el rerun de un submit de
    formulario, el rerun extra llega DESPUÉS de que se procesó el login y muestra
    la pantalla de login limpia, haciendo que el usuario vea "no pasó nada" aunque
    las credenciales eran correctas.

    La cookie obsoleta en el navegador se sobreescribe automáticamente al hacer
    login exitoso (_crear_sesion → cookies.save), o al hacer logout explícito
    (_limpiar_sesion). No es necesario limpiarla aquí.
    """
    token = st.session_state.pop("_session_token", None)
    st.session_state.pop("usuario_actual", None)
    if token:
        try:
            with _db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM sesiones WHERE token = %s", (token,))
                conn.commit()
        except Exception:
            pass




def _buscar_usuario_por_id(usuario_id: int) -> dict | None:
    """Busca usuario por ID numérico. Usado por auth wall tras validar token."""
    try:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, username, password_hash, pin_recuperacion, rol, nombre_completo "
                    "FROM usuarios WHERE id = %s",
                    (usuario_id,)
                )
                row = cur.fetchone()
        if row:
            return {"id": row[0], "username": row[1], "password_hash": row[2],
                    "pin_recuperacion": row[3], "rol": row[4], "nombre_completo": row[5]}
        return None
    except Exception:
        return None


def _buscar_usuario_por_username(username: str) -> dict | None:
    try:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, username, password_hash, pin_recuperacion, rol, nombre_completo "
                    "FROM usuarios WHERE username = %s",
                    (username.strip().lower(),)
                )
                row = cur.fetchone()
        if row:
            return {"id": row[0], "username": row[1], "password_hash": row[2],
                    "pin_recuperacion": row[3], "rol": row[4], "nombre_completo": row[5]}
        return None
    except Exception:
        return None

def _crear_usuario(username: str, password: str, pin: str,
                   rol: str = "Operario", nombre_completo: str = "") -> bool:
    try:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO usuarios (username, password_hash, pin_recuperacion, rol, nombre_completo) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (username.strip().lower(), _hash_password(password), pin.strip(), rol, nombre_completo)
                )
            conn.commit()
        return True
    except Exception:
        return False

def _actualizar_password(username: str, nueva_password: str) -> bool:
    try:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE usuarios SET password_hash = %s WHERE username = %s",
                    (_hash_password(nueva_password), username.strip().lower())
                )
            conn.commit()
        return True
    except Exception:
        return False

def _listar_usuarios() -> list:
    try:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, username, rol, nombre_completo FROM usuarios ORDER BY id")
                return cur.fetchall()
    except Exception:
        return []

def _eliminar_usuario(uid: int) -> bool:
    try:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM usuarios WHERE id = %s", (uid,))
            conn.commit()
        return True
    except Exception:
        return False

def _asegurar_admin_existe():
    """Crea el usuario admin por defecto si la tabla está vacía.
    Credenciales: admin / admin123 / PIN: 0000  — cambiar tras el primer login."""
    try:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM usuarios")
                if cur.fetchone()[0] == 0:
                    _crear_usuario("admin", "admin123", "0000", "Admin", "Administrador")
    except Exception:
        pass

# ── Pantalla de Login ─────────────────────────────────────────────────────────

def _pantalla_login() -> None:
    """
    Renderiza la pantalla de login corporativa con CookieManager.
    En login exitoso: _crear_sesion() + st.rerun().
    """
    _asegurar_admin_existe()

    st.markdown("""
    <style>
    .login-title {
        font-family: 'Playfair Display', serif;
        font-size: 1.45rem; font-weight: 700;
        color: #1F6F54; margin-bottom: 4px; text-align: center;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── Logo centrado — bimodal (Light / Dark automático) ────────────────────
    # IMPORTANTE: los <img> NO llevan display en el style inline para que las
    # media queries de CSS puedan controlar su visibilidad sin ser sobreescritas.
    _logo_img_style = (
        "width:220px;max-width:90%;height:auto;object-fit:contain;"
    )
    if _LOGO_LIGHT_B64 or _LOGO_DARK_B64:
        _src_light = f"data:{_LOGO_MIME};base64,{_LOGO_LIGHT_B64}" if _LOGO_LIGHT_B64 else ""
        _src_dark  = f"data:{_LOGO_MIME};base64,{_LOGO_DARK_B64}"  if _LOGO_DARK_B64  else ""
        # Si sólo existe uno de los dos, usarlo en ambas variantes
        _src_light = _src_light or _src_dark
        _src_dark  = _src_dark  or _src_light
        st.markdown(
            f'<div style="text-align:center;margin-bottom:15px;padding-top:8px">'
            f'<img src="{_src_light}" class="img-logo-light" style="{_logo_img_style}" alt="Costo360"/>'
            f'<img src="{_src_dark}"  class="img-logo-dark"  style="{_logo_img_style}" alt="Costo360"/>'
            f'</div>',
            unsafe_allow_html=True,
        )
    elif st.session_state.get("logo_bytes") and len(st.session_state.logo_bytes) > 0:
        # Fallback: logo subido en Configuración (BD) — solo si tiene contenido real
        _l_b64 = _base64_mod.b64encode(st.session_state.logo_bytes).decode("utf-8")
        st.markdown(
            f'<div style="text-align:center;margin-bottom:15px;padding-top:8px">'
            f'<img src="data:image/jpeg;base64,{_l_b64}" '
            f'style="{_logo_img_style}" alt="Costo360"/></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div style="text-align:center;padding:10px 0 12px">'
            '<span style="color:#C9A45C;font-size:2.4rem;font-weight:900;'
            'font-family:serif;line-height:1">C360</span></div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div class="login-title" style="margin-top:-20px;margin-bottom:8px">Iniciar Sesión</div>',
        unsafe_allow_html=True
    )

    with st.container(border=True):
        _tab_login, _tab_pin = st.tabs(["🔐 Acceder", "🔑 Recuperar contraseña"])

        # ── Tab login principal ───────────────────────────────────────────────
        with _tab_login:
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            # FIX-1: st.form agrupa los inputs en un solo bloque cerrado.
            # Efecto: (a) cero reruns por pulsación de tecla — elimina el lag y
            # la gray-screen al escribir; (b) habilita submit nativo con Enter.
            with st.form("login_form", clear_on_submit=False):
                _uname = st.text_input(
                    "Usuario", placeholder="Ej: jcastro", key="login_username"
                )
                _pwd = st.text_input(
                    "Contraseña", type="password",
                    placeholder="••••••••", key="login_password"
                )
                _btn_login = st.form_submit_button(
                    "Iniciar Sesión", type="primary", use_container_width=True
                )

            # La lógica de validación va FUERA del form para poder mostrar
            # el spinner sin que quede capturado dentro del contexto del form.
            if _btn_login:
                if not _uname or not _pwd:
                    st.error("Completa usuario y contraseña.", icon="⚠️")
                else:
                    # FIX-2a: spinner durante la consulta a BD — da feedback
                    # inmediato y bloquea el doble-clic accidental.
                    with st.spinner("Validando credenciales..."):
                        _usr     = _buscar_usuario_por_username(_uname)
                        _auth_ok = bool(
                            _usr and _verificar_password(_pwd, _usr["password_hash"])
                        )
                    if _auth_ok:
                        # Login exitoso: persistir sesión en cookie HTTP (30 días)
                        _crear_sesion(_usr["id"])
                        st.session_state["usuario_actual"] = _usr
                        st.success(
                            f"Bienvenido, {_usr['nombre_completo'] or _usr['username']}!"
                        )
                        st.rerun()
                    else:
                        st.error("Usuario o contraseña incorrectos.", icon="🚨")

            st.markdown(
                """<div style='text-align:center;margin-top:14px;padding-top:10px;
                border-top:1px solid rgba(128,128,128,0.15)'>
                <span style='color:#9ca3af;font-size:0.75rem;font-weight:400;
                letter-spacing:0.03em'>Sistema de uso exclusivo</span>
                <span style='color:#9ca3af;font-size:0.75rem'> · </span>
                <span style='font-style:italic;font-weight:600;color:#6b7280;
                font-size:0.75rem'>Costo360 Plataforma B2B</span>
                </div>""",
                unsafe_allow_html=True
            )

        # ── Tab recuperación por PIN ──────────────────────────────────────────
        with _tab_pin:
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            st.caption("Ingresa tu usuario y el PIN de recuperación de 4 dígitos.")
            _rec_user = st.text_input("Usuario", placeholder="Ej: jcastro", key="rec_username")
            _rec_pin  = st.text_input("PIN de recuperación (4 dígitos)",
                                      placeholder="0000", max_chars=4, key="rec_pin")

            if st.button("Verificar PIN →", use_container_width=True, key="btn_verificar_pin"):
                if not _rec_user or not _rec_pin:
                    st.error("Completa usuario y PIN.", icon="⚠️")
                else:
                    _usr_rec = _buscar_usuario_por_username(_rec_user)
                    if _usr_rec and _usr_rec["pin_recuperacion"] == _rec_pin.strip():
                        st.session_state["_pin_verificado_user"] = _rec_user.strip().lower()
                        st.success("PIN correcto. Ahora ingresa tu nueva contraseña.")
                    else:
                        st.error("Usuario o PIN incorrecto.", icon="🚨")
                        st.session_state.pop("_pin_verificado_user", None)

            if st.session_state.get("_pin_verificado_user"):
                st.markdown("---")
                _nueva_pwd = st.text_input("Nueva contraseña", type="password",
                                           placeholder="Mínimo 6 caracteres", key="nueva_pwd")
                _confirmar = st.text_input("Confirmar contraseña", type="password",
                                           placeholder="Repite la contraseña", key="confirmar_pwd")
                if st.button("Guardar nueva contraseña", type="primary",
                             use_container_width=True, key="btn_cambiar_pwd"):
                    if len(_nueva_pwd) < 6:
                        st.error("La contraseña debe tener al menos 6 caracteres.")
                    elif _nueva_pwd != _confirmar:
                        st.error("Las contraseñas no coinciden.")
                    else:
                        if _actualizar_password(st.session_state["_pin_verificado_user"], _nueva_pwd):
                            st.session_state.pop("_pin_verificado_user", None)
                            st.success("Contraseña actualizada. Ya puedes iniciar sesión.")
                            st.rerun()
                        else:
                            st.error("Error al actualizar. Intenta de nuevo.")



# ── HELPERS UI NATIVOS ────────────────────────────────────────────────────────
def alerta(texto, tipo="info"):
    """Reemplazo de la alerta CSS por componentes nativos de Streamlit (100% compatibles con modo claro/oscuro)"""
    if tipo == "bueno":
        st.success(texto, icon="✅")
    elif tipo == "acepta":
        st.warning(texto, icon="⚠️")
    elif tipo == "bajo":
        st.error(texto, icon="🚨")
    else:
        st.info(texto, icon="ℹ️")

def seccion_titulo(texto, subtexto=""):
    st.markdown(f"### {texto}")
    if subtexto:
        st.caption(subtexto)

def bloque_costos(items_label_valor, total_label, total_val):
    html = ""
    for label, valor in items_label_valor:
        html += f"""<div style="display:flex;justify-content:space-between;padding:6px 0; border-bottom:1px solid var(--border-color); color:var(--text-color);">
            <span style="font-size:0.87rem;">{label}</span><span style="font-size:0.87rem;font-weight:600">{cop(valor)}</span></div>"""
    
    html += f"""<div style="display:flex;justify-content:space-between;padding:10px 0 0 0; border-bottom:1px solid var(--border-color); color:var(--text-color);">
            <span style="font-size:0.95rem;font-weight:800">{total_label}</span><span style="font-size:0.95rem;font-weight:800;color:#1F6F54">{cop(total_val)}</span></div>"""
    st.markdown(f'<div class="card-custom">{html}</div>', unsafe_allow_html=True)

def numero_completo(valor):
    """Moneda colombiana: $1.250.000"""
    return "$" + f"{int(round(valor)):,}".replace(",", ".")

def fmt_decimal(valor: float, decimales: int = 2) -> str:
    """Número decimal colombiano: miles=punto, decimal=coma  →  3.450,75"""
    fmt = f"{valor:,.{decimales}f}"
    partes = fmt.split(".")
    entero = partes[0].replace(",", ".")
    dec    = partes[1] if len(partes) > 1 else ""
    if not dec or all(c == "0" for c in dec):
        return entero
    return f"{entero},{dec}"

def fmt_m2(valor: float, decimales: int = 3) -> str:
    """Metros cuadrados: 3,450 m²"""
    return fmt_decimal(valor, decimales) + " m²"

def fmt_ml(valor: float, decimales: int = 2) -> str:
    """Metros lineales: 3,50 ml"""
    return fmt_decimal(valor, decimales) + " ml"

# ── SESSION STATE DATA ────────────────────────────────────────────────────────
_defaults = {
    "chat": [], "cotizacion": None, "contexto_cot": {}, "resumen_ia": "",
    "materiales_proyecto": [],
    "aiu_items": [
        {"desc": "Material pétreo (suministro)", "und": "m²",  "cant": 10.0, "punit": 250_000},
        {"desc": "Mano de obra corte y elaboración", "und": "m²", "cant": 10.0, "punit": 100_000},
        {"desc": "Instalación y nivelación",  "und": "m²",  "cant": 10.0, "punit": 50_000},
        {"desc": "Insumos (disco, adhesivo, silicona)", "und": "glb", "cant": 1.0, "punit": 150_000},
    ],
    "pre": {}, "piezas": [],
    "tarifas_custom": None, "logistica_custom": None, "viaticos_custom": None,
    "logo_bytes": None, "logo_mime": None,
    "empresa_info": {
        "nombre": "Costo360 - Plataforma B2B", "nit": "",
        "tel": "", "email": "",
        "ciudad": "Barranquilla, Atlántico — Colombia", "banco": "",
        "cuenta_tipo": "", "cuenta_numero": "",
    },
    "cat_sel": "Mármol",
    "adicionales_custom": None,
    "chat_input_key": 0,
    "params_wizard_chat": [],
    "params_cambios_aplicados": [],
    # Wizard navigation state
    "cdir_paso": 0,
    "cdir_success": False,
    "aiu_paso": 0,
    "aiu_success": False,
    # Wizard de Tarifas — se marca True al cargar si hay tarifas en BD
    "setup_tarifas_completado": False,
    "paso_wizard": 1,
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Cargar configuración persistente desde Supabase ──────────────────────────
# Se ejecuta UNA VEZ por sesión (marcador _config_cargada).
# Sobreescribe tarifas_custom, logistica_custom, viaticos_custom,
# adicionales_custom y empresa_info con los valores guardados en la BD,
# de modo que sobreviven a F5 y reinicios del servidor.
#
# M-01: _init_db() está marcado con @st.cache_resource — solo ejecuta el DDL
# la primera vez que el proceso Streamlit arranca (o tras hot-reload).
# Las funciones CRUD ya NO llaman _init_db() internamente.
try:
    _init_db()          # DDL único de arranque — @cache_resource garantiza 1 sola ejecución
    _cargar_config_desde_db()
except Exception:
    pass   # Si la BD no está disponible, se usan los defaults del código


# ══════════════════════════════════════════════════════════════════════════════
# ARQUITECTURA EVENT-DRIVEN: store_permanente + callbacks on_change
# ══════════════════════════════════════════════════════════════════════════════
#
# PROBLEMA RAÍZ: Cuando el usuario navega entre páginas del menú lateral,
# Streamlit desmonta todos los widgets de la página anterior y ELIMINA sus
# claves de st.session_state automáticamente ("Widget State Cleanup").
# Cualquier dato que solo vivía en un widget key se pierde para siempre.
#
# SOLUCIÓN — Tres capas independientes:
#
#   1. store_permanente (dict en session_state, sin keys de widgets)
#      El "cerebro central" de la app. Se inicializa UNA VEZ y NUNCA se borra.
#      Almacena el estado canónico de todos los inputs críticos.
#      Los widgets se hidratán desde aquí al renderizarse (value=store[...]).
#
#   2. Callbacks on_change (disparados en el instante del cambio)
#      Cada input crítico tiene on_change= apuntando a su callback.
#      El callback escribe en store_permanente y hace commit a PostgreSQL
#      ANTES de que Streamlit termine el ciclo de renderizado.
#      No hay botón "Guardar" que interceptar — el guardado es atómico.
#
#   3. Autoguardado de listas dinámicas
#      Cada mutación de piezas (agregar/eliminar/editar) llama a
#      _sp_commit_borrador() que persiste el snapshot completo en BD.
#      Igual para ítems AIU y materiales del proyecto.
#
# GARANTÍA: al navegar de "Cotización Directa" → "Parámetros" → volver a
# "Cotización Directa", el store_permanente no fue tocado, los widgets se
# renderizan con value=store[...] y el usuario ve exactamente lo que dejó.
# ─────────────────────────────────────────────────────────────────────────────


def _sp_init():
    """
    Inicializa st.session_state.store_permanente una única vez por sesión.
    Lo precarga desde el borrador en BD si existe.
    NUNCA sobreescribe un store ya existente en memoria — idempotente.
    """
    if "store_permanente" in st.session_state:
        return   # Ya existe — no tocar

    # ── Valores por defecto del store ────────────────────────────────────────
    _sp_defaults = {
        # ── Cotización Directa ───────────────────────────────────────────────
        "cdir_paso": 0,
        "cdir_materiales": [],          # lista [{cat, ref, precio_m2, area_placa}, ...]
        "cdir_piezas": [],              # lista [{nombre, ml, ancho_tipo, ancho_custom}, ...]
        "cdir_margen_pct": 40,
        "cdir_m2_usados": 0.0,
        "cdir_tipo_proyecto": "Mesón",
        "cdir_tipos_proyecto": ["Mesón"],
        "cdir_etapa_label": "Casa terminada (limpia)",
        "cdir_nombre_cliente": "",
        "cdir_dias_obra": 2,
        "cdir_personas": 2,
        "cdir_zocalo_activo": False,
        "cdir_zocalo_ml": 0.0,
        "cdir_agente_externo": False,
        "cdir_km": 5.0,
        "cdir_peajes": 0,
        "cdir_foraneo": False,
        "cdir_viaticos_activos": False,
        "cdir_tipo_aloj": "pueblo",
        "cdir_noches": 0,
        "cdir_adicionales_activos": False,
        "cdir_cantidades_add": [],
        "cdir_incluir_iva": True,
        "cdir_perfil_desperdicio": "🟡 Normal — algunos ángulos o esquinas",
        "cdir_km_rango": "0-5 km",
        # ── Cotización AIU ───────────────────────────────────────────────────
        "aiu_paso": 0,
        "aiu_items": [
            {"desc": "Material pétreo (suministro)", "und": "m²",  "cant": 10.0, "punit": 250_000},
            {"desc": "Mano de obra corte y elaboración", "und": "m²", "cant": 10.0, "punit": 100_000},
            {"desc": "Instalación y nivelación",  "und": "m²",  "cant": 10.0, "punit": 50_000},
            {"desc": "Insumos (disco, adhesivo, silicona)", "und": "glb", "cant": 1.0, "punit": 150_000},
        ],
        "aiu_nombre_cliente": "",
        "aiu_numero": "",
        "aiu_a_pct": 2.0,
        "aiu_i_pct": 2.0,
        "aiu_u_pct": 5.0,
        "aiu_anticipo_pct": 50,
        "aiu_incluir_iva": True,
        "aiu_telefono_cliente": "",
        "aiu_email_cliente": "",
        "aiu_ciudad_proyecto": "",
        "aiu_dias_entrega": 10,
        "aiu_dias_validez": 30,
        # ── Parámetros ───────────────────────────────────────────────────────
        "params_tarifas": None,         # dict completo tarifas o None → usa TARIFAS
        "params_logistica": None,       # dict completo logistica o None → usa LOGISTICA
        "params_viaticos": None,        # dict completo viaticos o None → usa VIATICOS
        "params_adicionales": None,     # lista adicionales o None → usa ADICIONALES
    }

    sp = dict(_sp_defaults)

    # ── Precargar desde sesión existente (si el store no existía pero sí hay pre) ──
    _pre = st.session_state.get("pre", {})
    if _pre:
        sp["cdir_paso"]                = _pre.get("cdir_paso", sp["cdir_paso"])
        sp["cdir_materiales"]          = _pre.get("materiales_proyecto", sp["cdir_materiales"])
        sp["cdir_piezas"]              = _pre.get("piezas", sp["cdir_piezas"])
        sp["cdir_margen_pct"]          = _pre.get("margen_pct", sp["cdir_margen_pct"])
        sp["cdir_m2_usados"]           = _pre.get("m2_usados", sp["cdir_m2_usados"])
        sp["cdir_tipo_proyecto"]       = _pre.get("tipo_proyecto", sp["cdir_tipo_proyecto"])
        sp["cdir_tipos_proyecto"]      = _pre.get("tipos_proyecto", sp["cdir_tipos_proyecto"])
        sp["cdir_etapa_label"]         = _pre.get("etapa_label", sp["cdir_etapa_label"])
        sp["cdir_nombre_cliente"]      = _pre.get("nombre_cliente", sp["cdir_nombre_cliente"])
        sp["cdir_dias_obra"]           = _pre.get("dias_obra", sp["cdir_dias_obra"])
        sp["cdir_personas"]            = _pre.get("personas", sp["cdir_personas"])
        sp["cdir_zocalo_activo"]       = _pre.get("zocalo_activo", sp["cdir_zocalo_activo"])
        sp["cdir_zocalo_ml"]           = _pre.get("zocalo_ml", sp["cdir_zocalo_ml"])
        sp["cdir_agente_externo"]      = _pre.get("agente_externo_taller", sp["cdir_agente_externo"])
        sp["cdir_km"]                  = _pre.get("km", sp["cdir_km"])
        sp["cdir_peajes"]              = _pre.get("peajes", sp["cdir_peajes"])
        sp["cdir_foraneo"]             = _pre.get("foraneo_activo", sp["cdir_foraneo"])
        sp["cdir_viaticos_activos"]    = _pre.get("viaticos_activos", sp["cdir_viaticos_activos"])
        sp["cdir_tipo_aloj"]           = _pre.get("tipo_aloj", sp["cdir_tipo_aloj"])
        sp["cdir_noches"]              = _pre.get("noches", sp["cdir_noches"])
        sp["cdir_adicionales_activos"] = _pre.get("adicionales_activos", sp["cdir_adicionales_activos"])
        sp["cdir_cantidades_add"]      = _pre.get("cantidades_add", sp["cdir_cantidades_add"])
        sp["cdir_incluir_iva"]         = _pre.get("incluir_iva", sp["cdir_incluir_iva"])
        sp["cdir_perfil_desperdicio"]  = _pre.get("perfil_desperdicio", sp["cdir_perfil_desperdicio"])
        sp["cdir_km_rango"]            = _pre.get("km_rango", sp["cdir_km_rango"])

    # ── Precargar tarifas/logística/viáticos desde sesión ────────────────────
    if st.session_state.get("tarifas_custom"):
        sp["params_tarifas"]   = st.session_state.tarifas_custom
    if st.session_state.get("logistica_custom"):
        sp["params_logistica"] = st.session_state.logistica_custom
    if st.session_state.get("viaticos_custom"):
        sp["params_viaticos"]  = st.session_state.viaticos_custom
    if st.session_state.get("adicionales_custom"):
        sp["params_adicionales"] = st.session_state.adicionales_custom

    # ── Sincronizar bandera del wizard de Tarifas ─────────────────────────
    # Si en session_state ya se marcó como completado (por carga desde BD o
    # por el usuario durante esta sesión), propagarlo al store para que
    # sobreviva a la navegación entre páginas de Streamlit.
    if st.session_state.get("setup_tarifas_completado"):
        sp["setup_tarifas_completado"] = True

    # ── Precargar ítems AIU si existen ────────────────────────────────────────
    if st.session_state.get("aiu_items"):
        sp["aiu_items"] = st.session_state.aiu_items

    st.session_state.store_permanente = sp


def _sp() -> dict:
    """Acceso rápido al store_permanente. Garantiza que exista antes de devolver."""
    if "store_permanente" not in st.session_state:
        _sp_init()
    return st.session_state.store_permanente


def _sp_set(key: str, value) -> None:
    """Escribe un valor en el store_permanente de forma segura."""
    _sp()[key] = value


def _sp_commit_borrador():
    """
    Persiste el estado crítico del borrador de Cotización Directa en BD.
    Se llama desde callbacks on_change y desde mutaciones de listas.
    Hash-gated: solo escribe si hay cambios reales desde el último commit.
    """
    sp = _sp()
    # Construir snapshot desde el store (independiente de widgets)
    _snapshot = {
        "materiales_proyecto": sp.get("cdir_materiales", []),
        "piezas":              sp.get("cdir_piezas", []),
        "margen_pct":          sp.get("cdir_margen_pct", 40),
        "m2_usados":           sp.get("cdir_m2_usados", 0.0),
        "tipo_proyecto":       sp.get("cdir_tipo_proyecto", "Mesón"),
        "tipos_proyecto":      sp.get("cdir_tipos_proyecto", ["Mesón"]),
        "etapa_label":         sp.get("cdir_etapa_label", "Casa terminada (limpia)"),
        "nombre_cliente":      sp.get("cdir_nombre_cliente", ""),
        "dias_obra":           sp.get("cdir_dias_obra", 2),
        "personas":            sp.get("cdir_personas", 2),
        "zocalo_activo":       sp.get("cdir_zocalo_activo", False),
        "zocalo_ml":           sp.get("cdir_zocalo_ml", 0.0),
        "agente_externo_taller": sp.get("cdir_agente_externo", False),
        "vehiculo_entrega": "externo",
        "km":                  sp.get("cdir_km", 5.0),
        "peajes":              sp.get("cdir_peajes", 0),
        "foraneo_activo":      sp.get("cdir_foraneo", False),
        "viaticos_activos":    sp.get("cdir_viaticos_activos", False),
        "tipo_aloj":           sp.get("cdir_tipo_aloj", "pueblo"),
        "noches":              sp.get("cdir_noches", 0),
        "adicionales_activos": sp.get("cdir_adicionales_activos", False),
        "cantidades_add":      sp.get("cdir_cantidades_add", []),
        "incluir_iva":         sp.get("cdir_incluir_iva", True),
        "cdir_paso":           sp.get("cdir_paso", 0),
        "perfil_desperdicio":  sp.get("cdir_perfil_desperdicio", "🟡 Normal — algunos ángulos o esquinas"),
        "km_rango":            sp.get("cdir_km_rango", "0-5 km"),
    }
    # ── Sync bidireccional: mantener pre en sincronía con el store ────────────
    st.session_state.pre = _snapshot
    if st.session_state.get("cdir_piezas") is not None:
        st.session_state.piezas = sp.get("cdir_piezas", [])
    if st.session_state.get("materiales_proyecto") is not None:
        st.session_state.materiales_proyecto = sp.get("cdir_materiales", [])
    # ── Hash-gate: commit a BD solo si hay cambio real ────────────────────────
    try:
        import json as _json
        _h = hash(_json.dumps(_snapshot, sort_keys=True, default=str))
        if _h != st.session_state.get("_sp_borrador_hash"):
            _guardar_config(_clave_borrador_cdir(), _snapshot)
            st.session_state["_sp_borrador_hash"] = _h
    except Exception:
        pass


def _sp_commit_borrador_aiu():
    """Persiste el estado del borrador de Cotización AIU en BD."""
    sp = _sp()
    _snapshot = {
        "aiu_items":         sp.get("aiu_items", []),
        "aiu_nombre_cliente": sp.get("aiu_nombre_cliente", ""),
        "aiu_numero":        sp.get("aiu_numero", ""),
        "aiu_a_pct":         sp.get("aiu_a_pct", 2.0),
        "aiu_i_pct":         sp.get("aiu_i_pct", 2.0),
        "aiu_u_pct":         sp.get("aiu_u_pct", 5.0),
        "aiu_anticipo_pct":  sp.get("aiu_anticipo_pct", 50),
        "aiu_incluir_iva":   sp.get("aiu_incluir_iva", True),
        "aiu_telefono_cliente": sp.get("aiu_telefono_cliente", ""),
        "aiu_email_cliente": sp.get("aiu_email_cliente", ""),
        "aiu_ciudad_proyecto": sp.get("aiu_ciudad_proyecto", ""),
        "aiu_dias_entrega":  sp.get("aiu_dias_entrega", 10),
        "aiu_dias_validez":  sp.get("aiu_dias_validez", 30),
        "aiu_paso":          sp.get("aiu_paso", 0),
    }
    st.session_state.aiu_items = sp.get("aiu_items", [])
    try:
        import json as _json
        _h = hash(_json.dumps(_snapshot, sort_keys=True, default=str))
        if _h != st.session_state.get("_sp_aiu_hash"):
            _guardar_config(_clave_borrador_aiu(), _snapshot)
            st.session_state["_sp_aiu_hash"] = _h
    except Exception:
        pass


def _sp_commit_params(tipo: str):
    """
    Persiste un grupo de parámetros (tarifas/logistica/viaticos) en BD.
    Actualiza simultáneamente session_state y store_permanente.
    Llamado desde callbacks on_change de Parámetros.
    """
    sp = _sp()
    if tipo == "tarifas":
        _val = sp.get("params_tarifas")
        st.session_state.tarifas_custom = _val
        try: _guardar_config("tarifas_custom", _val)
        except Exception: pass
    elif tipo == "logistica":
        _val = sp.get("params_logistica")
        st.session_state.logistica_custom = _val
        try: _guardar_config("logistica_custom", _val)
        except Exception: pass
    elif tipo == "viaticos":
        _val = sp.get("params_viaticos")
        st.session_state.viaticos_custom = _val
        try: _guardar_config("viaticos_custom", _val)
        except Exception: pass
    elif tipo == "adicionales":
        _val = sp.get("params_adicionales")
        st.session_state.adicionales_custom = _val
        try: _guardar_config("adicionales_custom", _val)
        except Exception: pass


# ── Callbacks on_change para Cotización Directa ──────────────────────────────

def _cb_cdir_nombre_cliente():
    _sp_set("cdir_nombre_cliente", st.session_state.get("cb_cdir_nombre_cliente", ""))
    _sp_commit_borrador()

def _cb_cdir_margen():
    _sp_set("cdir_margen_pct", st.session_state.get("cb_cdir_margen", 40))
    _sp_commit_borrador()

def _cb_cdir_m2_usados():
    _sp_set("cdir_m2_usados", st.session_state.get("cb_cdir_m2_usados", 0.0))
    _sp_commit_borrador()

def _cb_cdir_tipos_proyecto():
    _vals = st.session_state.get("cb_cdir_tipos_proyecto", ["Mesón"])
    _sp_set("cdir_tipos_proyecto", _vals)
    _sp_set("cdir_tipo_proyecto", " + ".join(_vals) if _vals else "Otro")
    _sp_commit_borrador()

def _cb_cdir_etapa():
    _sp_set("cdir_etapa_label", st.session_state.get("cb_cdir_etapa", "Casa terminada (limpia)"))
    _sp_commit_borrador()

def _cb_cdir_dias():
    _sp_set("cdir_dias_obra", st.session_state.get("cb_cdir_dias", 2))
    _sp_commit_borrador()

def _cb_cdir_personas():
    _sp_set("cdir_personas", st.session_state.get("cb_cdir_personas", 2))
    _sp_commit_borrador()

def _cb_cdir_zocalo_activo():
    _sp_set("cdir_zocalo_activo", st.session_state.get("cb_cdir_zocalo_activo", False))
    _sp_commit_borrador()

def _cb_cdir_zocalo_ml():
    _sp_set("cdir_zocalo_ml", st.session_state.get("cb_cdir_zocalo_ml", 0.0))
    _sp_commit_borrador()

def _cb_cdir_agente_externo():
    _sp_set("cdir_agente_externo", st.session_state.get("cb_cdir_agente_externo", False))
    _sp_commit_borrador()

def _cb_cdir_vehiculo_km():
    _sp_set("cdir_km", st.session_state.get("cb_cdir_km", 5.0))


def _cb_cdir_km_rango():
    """Callback: al cambiar el pills de rango de km, actualiza cdir_km al promedio del rango
    y guarda el rango seleccionado para que el number_input se sincronice mágicamente."""
    _rango = st.session_state.get("p3_km_pills_cb")
    if _rango is None:
        return
    _km_defaults = {"0-5 km": 3.0, "5-15 km": 10.0, "15-30 km": 22.0, "30-60 km": 45.0, "60+ km": 80.0}
    _sp_set("cdir_km_rango", _rango)
    _sp_set("cdir_km", float(_km_defaults.get(_rango, _sp().get("cdir_km", 5.0))))
    _sp_commit_borrador()

def _cb_cdir_peajes():
    _sp_set("cdir_peajes", st.session_state.get("cb_cdir_peajes", 0))
    _sp_commit_borrador()

def _cb_cdir_foraneo():
    _sp_set("cdir_foraneo", st.session_state.get("cb_cdir_foraneo", False))
    _sp_commit_borrador()

def _cb_cdir_viaticos_activos():
    _sp_set("cdir_viaticos_activos", st.session_state.get("cb_cdir_viaticos_activos", False))
    _sp_commit_borrador()

def _cb_cdir_tipo_aloj():
    _sp_set("cdir_tipo_aloj", st.session_state.get("cb_cdir_tipo_aloj", "pueblo"))
    _sp_commit_borrador()

def _cb_cdir_noches():
    _sp_set("cdir_noches", st.session_state.get("cb_cdir_noches", 0))
    _sp_commit_borrador()


def _cb_cdir_perfil_desperdicio():
    """Callback: persiste el perfil de desperdicio en store_permanente para que no se
    resetee al cambiar de pestaña o al repintar la página."""
    _val = st.session_state.get("perfil_desperdicio_radio")
    if _val is not None:
        _sp_set("cdir_perfil_desperdicio", _val)
    _sp_commit_borrador()

def _cb_cdir_adicionales_activos():
    _sp_set("cdir_adicionales_activos", st.session_state.get("cb_cdir_adicionales_activos", False))
    _sp_commit_borrador()

def _cb_cdir_incluir_iva():
    _sp_set("cdir_incluir_iva", st.session_state.get("cb_cdir_incluir_iva", True))
    _sp_commit_borrador()


# ── Callbacks on_change para Cotización AIU ──────────────────────────────────

def _cb_aiu_nombre_cliente():
    _sp_set("aiu_nombre_cliente", st.session_state.get("cb_aiu_nombre_cliente", ""))
    _sp_commit_borrador_aiu()

def _cb_aiu_numero():
    _sp_set("aiu_numero", st.session_state.get("cb_aiu_numero", ""))
    _sp_commit_borrador_aiu()

def _cb_aiu_a_pct():
    _sp_set("aiu_a_pct", st.session_state.get("cb_aiu_a_pct", 2.0))
    _sp_commit_borrador_aiu()

def _cb_aiu_i_pct():
    _sp_set("aiu_i_pct", st.session_state.get("cb_aiu_i_pct", 2.0))
    _sp_commit_borrador_aiu()

def _cb_aiu_u_pct():
    _sp_set("aiu_u_pct", st.session_state.get("cb_aiu_u_pct", 5.0))
    _sp_commit_borrador_aiu()

def _cb_aiu_anticipo():
    _sp_set("aiu_anticipo_pct", st.session_state.get("cb_aiu_anticipo_pct", 50))
    _sp_commit_borrador_aiu()

def _cb_aiu_incluir_iva():
    _sp_set("aiu_incluir_iva", st.session_state.get("cb_aiu_incluir_iva", True))
    _sp_commit_borrador_aiu()

def _cb_aiu_telefono_cliente():
    _sp_set("aiu_telefono_cliente", st.session_state.get("cb_aiu_telefono_cliente", ""))
    _sp_commit_borrador_aiu()

def _cb_aiu_email_cliente():
    _sp_set("aiu_email_cliente", st.session_state.get("cb_aiu_email_cliente", ""))
    _sp_commit_borrador_aiu()

def _cb_aiu_ciudad_proyecto():
    _sp_set("aiu_ciudad_proyecto", st.session_state.get("cb_aiu_ciudad_proyecto", ""))
    _sp_commit_borrador_aiu()

def _cb_aiu_dias_entrega():
    _sp_set("aiu_dias_entrega", st.session_state.get("cb_aiu_dias_entrega", 10))
    _sp_commit_borrador_aiu()

def _cb_aiu_dias_validez():
    _sp_set("aiu_dias_validez", st.session_state.get("cb_aiu_dias_validez", 30))
    _sp_commit_borrador_aiu()


# ── Helpers para listas dinámicas con persistencia atómica ───────────────────

def _sp_agregar_pieza():
    """Añade una pieza nueva y persiste en BD de inmediato."""
    piezas = list(_sp().get("cdir_piezas", []))
    piezas.append({"nombre": f"Pieza {len(piezas)+1}",
                   "ml": 1.0, "ml_unitario": 1.0, "cantidad": 1,
                   "ancho_tipo": "Mesón de cocina", "ancho_custom": 0.60,
                   # Zócalo geométrico — desactivado por defecto
                   "zoc_trasero": False, "zoc_izq": False, "zoc_der": False,
                   "altura_zocalo_cm": 7.0})
    _sp_set("cdir_piezas", piezas)
    st.session_state.piezas = piezas
    _sp_commit_borrador()

def _sp_eliminar_pieza(idx: int):
    """Elimina una pieza y persiste en BD de inmediato.
    También limpia los keys de session_state de los widgets de esa pieza
    (inputs de nombre, tipo, ml, ancho, cantidad, zócalo) para que Streamlit
    no recicle valores de la pieza eliminada en las filas desplazadas.
    """
    piezas = list(_sp().get("cdir_piezas", []))
    if 0 <= idx < len(piezas):
        piezas.pop(idx)
        _sp_set("cdir_piezas", piezas)
        st.session_state.piezas = piezas
        # Limpiar todos los keys de widget asociados a la pieza eliminada
        _keys_pieza = [
            f"pnom_{idx}", f"ptip_{idx}", f"pml_{idx}", f"pcant_{idx}",
            f"panc_{idx}", f"pcustom_{idx}",
            f"zoc_t_{idx}", f"zoc_i_{idx}", f"zoc_d_{idx}", f"zoc_h_{idx}",
        ]
        for _k in _keys_pieza:
            st.session_state.pop(_k, None)
        _sp_commit_borrador()

def _sp_sync_piezas(piezas_nuevas: list):
    """Sincroniza la lista de piezas completa hacia el store y BD."""
    _sp_set("cdir_piezas", piezas_nuevas)
    st.session_state.piezas = piezas_nuevas
    _sp_commit_borrador()

def _sp_agregar_material():
    """Añade un material nuevo y persiste en BD."""
    mats = list(_sp().get("cdir_materiales", []))
    mats.append({"cat": "Mármol", "ref": "", "precio_m2": 220_000, "area_placa": 5.94})
    _sp_set("cdir_materiales", mats)
    st.session_state.materiales_proyecto = mats
    _sp_commit_borrador()

def _sp_eliminar_material(idx: int):
    """Elimina un material y persiste en BD."""
    mats = list(_sp().get("cdir_materiales", []))
    if 0 <= idx < len(mats):
        mats.pop(idx)
        _sp_set("cdir_materiales", mats)
        st.session_state.materiales_proyecto = mats
        _sp_commit_borrador()

def _sp_sync_materiales(mats_nuevos: list):
    """Sincroniza la lista de materiales completa hacia el store y BD."""
    _sp_set("cdir_materiales", mats_nuevos)
    st.session_state.materiales_proyecto = mats_nuevos
    _sp_commit_borrador()

def _sp_agregar_item_aiu():
    """Añade un ítem AIU y persiste en BD."""
    items = list(_sp().get("aiu_items", []))
    items.append({"desc": f"Ítem {len(items)+1}", "und": "und", "cant": 1.0, "punit": 0})
    _sp_set("aiu_items", items)
    st.session_state.aiu_items = items
    _sp_commit_borrador_aiu()

def _sp_eliminar_item_aiu(idx: int):
    """Elimina un ítem AIU y persiste en BD."""
    items = list(_sp().get("aiu_items", []))
    if len(items) > 1 and 0 <= idx < len(items):
        items.pop(idx)
        _sp_set("aiu_items", items)
        st.session_state.aiu_items = items
        _sp_commit_borrador_aiu()

def _sp_sync_items_aiu(items_nuevos: list):
    """Sincroniza la lista de ítems AIU completa hacia el store y BD."""
    _sp_set("aiu_items", items_nuevos)
    st.session_state.aiu_items = items_nuevos
    _sp_commit_borrador_aiu()


# ── Callbacks on_change para Parámetros (cada campo guarda inmediatamente) ───

def _cb_tar(mat: str, campo: str, tipo: str):
    """Factory closure para callbacks de tarifas. Usa cierre sobre mat/campo/tipo."""
    def _inner():
        from parametros import TARIFAS as _TARIFAS_BASE
        import copy as _copy
        sp = _sp()
        _tar = _copy.deepcopy(sp.get("params_tarifas") or _copy.deepcopy(_TARIFAS_BASE))
        if mat not in _tar:
            _tar[mat] = {}
        _wk = f"cb_tar_{mat}_{campo}"
        _raw = st.session_state.get(_wk)
        if _raw is not None:
            _tar[mat][campo] = float(_raw) if tipo == "float" else int(_raw)
        sp["params_tarifas"] = _tar
        st.session_state.tarifas_custom = _tar
        try: _guardar_config("tarifas_custom", _tar)
        except Exception: pass
    return _inner


def _cb_via(dest: str, campo: str):
    """Factory closure para callbacks de viáticos."""
    def _inner():
        from parametros import VIATICOS as _VIATICOS_BASE
        import copy as _copy
        sp = _sp()
        _via = _copy.deepcopy(sp.get("params_viaticos") or _copy.deepcopy(_VIATICOS_BASE))
        if dest not in _via:
            _via[dest] = {}
        _wk = f"cb_via_{dest}_{campo}"
        _raw = st.session_state.get(_wk)
        if _raw is not None:
            _via[dest][campo] = int(_raw)
        sp["params_viaticos"] = _via
        st.session_state.viaticos_custom = _via
        try: _guardar_config("viaticos_custom", _via)
        except Exception: pass
    return _inner


def _cb_log(campo: str, veh: str = "", sub: str = "", tipo: str = "int"):
    """Factory closure para callbacks de logística."""
    def _inner():
        from parametros import LOGISTICA as _LOGISTICA_BASE
        import copy as _copy
        sp = _sp()
        _log = _copy.deepcopy(sp.get("params_logistica") or _copy.deepcopy(_LOGISTICA_BASE))
        _wk = f"cb_log_{campo}" if not veh else f"cb_log_{veh}_{sub}"
        _raw = st.session_state.get(_wk)
        if _raw is not None:
            if not veh:
                _log[campo] = float(_raw) if tipo == "float" else int(_raw)
            else:
                if veh not in _log or not isinstance(_log[veh], dict):
                    _log[veh] = {}
                _log[veh][sub] = float(_raw) if tipo == "float" else int(_raw)
        sp["params_logistica"] = _log
        st.session_state.logistica_custom = _log
        try: _guardar_config("logistica_custom", _log)
        except Exception: pass
    return _inner


# ── Inicializar el store_permanente AHORA (antes del auth wall) ───────────────
_sp_init()


# ══════════════════════════════════════════════════════════════════════════════
# MURO DE AUTENTICACIÓN — Token UUID + PostgreSQL
# =============================================================================
#
# 1. _leer_token()          →  session_state cache  →  cookie del navegador  →  None
# 2. Token presente         →  _validar_token() en BD  →  usuario_id
# 3. Token válido           →  hidratar usuario  →  abrir app (sin login)
# 4. Token inválido/expirado →  _limpiar_token_invalido() + pantalla login
# 5. Sin token              →  pantalla de login
#
# El usuario NO vuelve a hacer login mientras el token (30 días) esté vigente,
# aunque cierre el navegador, apague el dispositivo o refresque la página.

_token_actual = _leer_token()

if _token_actual:
    # ── Token presente: validar en BD ───────────────────────────────────────
    if not st.session_state.get("usuario_actual"):
        _uid_validado = _validar_token(_token_actual)
        if _uid_validado:
            _usr_token = _buscar_usuario_por_id(_uid_validado)
            if _usr_token:
                st.session_state["usuario_actual"] = _usr_token
            else:
                # Usuario eliminado de la BD — invalidar token
                _limpiar_token_invalido()
                _pantalla_login()
                st.stop()
        else:
            # Token expirado o inválido
            _limpiar_token_invalido()
            _pantalla_login()
            st.stop()
else:
    # ── Sin token → primera visita o sesión expirada ───────────────────
    _pantalla_login()
    st.stop()

# ── LATE CONFIG LOAD (post-auth, claves reales del usuario) ─────────────
# _cargar_config_desde_db() corre antes del login con _uid()="anon",
# por lo que lee "logistica_custom_uanon" en lugar de "logistica_custom_u{id}".
# La bandera _config_cargada=True impide una segunda carga. Este bloque
# repara eso: en el primer render post-auth, recarga todas las claves
# operativas con el ID real del usuario autenticado.
if st.session_state.get("usuario_actual") and not st.session_state.get("_config_hidratada_postauth"):
    _claves_postauth = [
        ("tarifas_custom",      "tarifas_custom"),
        ("logistica_custom",    "logistica_custom"),
        ("viaticos_custom",     "viaticos_custom"),
        ("adicionales_custom",  "adicionales_custom"),
    ]
    for _ss_key_pa, _db_key_pa in _claves_postauth:
        try:
            _v_pa = _leer_config(_db_key_pa)   # _uid() ya tiene el ID real
            if _v_pa is not None:
                st.session_state[_ss_key_pa] = _v_pa
        except Exception:
            pass
    st.session_state["_config_hidratada_postauth"] = True

def get_tarifas(): return st.session_state.tarifas_custom or TARIFAS
def get_logistica(): return st.session_state.logistica_custom or LOGISTICA
def get_viaticos(): return st.session_state.viaticos_custom or VIATICOS
def get_adicionales():
    import copy
    return copy.deepcopy(st.session_state.adicionales_custom) if st.session_state.adicionales_custom else copy.deepcopy(ADICIONALES)


# ── SIDEBAR NAV ───────────────────────────────────────────────────────────────
with st.sidebar:
    # ── Logo corporativo — bimodal (Light / Dark automático) ─────────────────
    # IMPORTANTE: los <img> NO llevan display en el style inline para que las
    # media queries de CSS puedan controlar su visibilidad sin ser sobreescritas.
    _sb_logo_style = (
        "width:100%;max-width:220px;height:auto;object-fit:contain;"
    )
    if _LOGO_LIGHT_B64 or _LOGO_DARK_B64:
        _sb_src_light = f"data:{_LOGO_MIME};base64,{_LOGO_LIGHT_B64}" if _LOGO_LIGHT_B64 else ""
        _sb_src_dark  = f"data:{_LOGO_MIME};base64,{_LOGO_DARK_B64}"  if _LOGO_DARK_B64  else ""
        _sb_src_light = _sb_src_light or _sb_src_dark
        _sb_src_dark  = _sb_src_dark  or _sb_src_light
        st.sidebar.markdown(
            f'<div style="text-align:center;padding:10px 0 4px">'
            f'<img src="{_sb_src_light}" class="img-logo-light" style="{_sb_logo_style}" alt="Costo360"/>'
            f'<img src="{_sb_src_dark}"  class="img-logo-dark"  style="{_sb_logo_style}" alt="Costo360"/>'
            f'</div>',
            unsafe_allow_html=True,
        )
    elif st.session_state.get("logo_bytes") and len(st.session_state.logo_bytes) > 0:
        # Fallback: logo subido en Configuración (BD) — solo si tiene contenido real
        st.image(st.session_state.logo_bytes, use_container_width=True)
    else:
            st.markdown(
                '<div style="text-align:center;padding:14px 0 8px">'
                '<span style="color:#C9A45C;font-size:2rem;font-weight:900;'
                'font-family:Playfair Display,serif">C360</span><br>'
                '<span style="font-size:0.72rem;font-weight:700;opacity:0.8">'
                'COSTO360 — PLATAFORMA B2B</span>'
                '</div>',
                unsafe_allow_html=True
            )

    st.markdown(
        '<div style="text-align:center;margin:2px 0 14px;padding-bottom:10px;'
        'border-bottom:1px solid var(--border-color)">'
        '<div style="font-size:0.66rem;font-weight:600;opacity:0.5;letter-spacing:0.07em;'
        'text-transform:uppercase">Sistema de Cotización Profesional</div>'
        '</div>',
        unsafe_allow_html=True
    )

    # Historial: redirección legacy si alguien tenía ruta guardada sin "Historial"
    _paginas_validas = ["Inicio", "⚡ Modo Express", "Cotizacion Directa", "Cotizacion AIU",
                        "Historial", "Dashboard", "Banco de Retales",
                        "Parametros", "Asistente IA", "Planos de Taller (IA)",
                        "Configuracion", "Gestion de Equipo"]
    if st.session_state.get("nav_radio") not in _paginas_validas:
        st.session_state.nav_radio = "Inicio"
        st.session_state.radio_ui = "Inicio"

    # Menú dinámico: "Gestión de Equipo" solo visible para rol Admin
    _rol_nav = st.session_state.get("usuario_actual", {}).get("rol", "Operario")
    opciones_menu = ["Inicio", "⚡ Modo Express", "Cotizacion Directa", "Cotizacion AIU",
                     "Historial", "Dashboard", "Banco de Retales", "Parametros",
                     "Asistente IA", "Planos de Taller (IA)", "Configuracion"]
    if _rol_nav == "Admin":
        opciones_menu.append("Gestion de Equipo")

    def update_nav():
        st.session_state.nav_radio = st.session_state.radio_ui
        # Persistir la página en la URL para sobrevivir a F5
        st.query_params["pagina"] = st.session_state.nav_radio

    # CRÍTICO: NO usar index= en st.radio cuando la key está en session_state.
    # Pasar index= y key= simultáneamente causa el error "conflicto de estado":
    # Streamlit no puede reconciliar el valor externo (index) con el valor del
    # session_state gestionado por on_change. La solución correcta es dejar que
    # Streamlit lea directamente st.session_state["radio_ui"], que ya fue
    # sincronizado con nav_radio justo al inicio del script (ver líneas ~61-72).
    st.radio("Menú", opciones_menu, key="radio_ui",
             on_change=update_nav,
             label_visibility="collapsed")
    pagina = st.session_state.nav_radio

    st.markdown('<hr style="margin:12px 0">', unsafe_allow_html=True)
    if ia_disponible():
        st.markdown('<div style="background:rgba(74,222,128,0.15);border:1px solid rgba(74,222,128,0.3);border-radius:6px;padding:7px 10px;font-size:0.75rem;font-weight:600;color:#16a34a">🟢 IA Activa</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="background:rgba(251,191,36,0.12);border:1px solid rgba(251,191,36,0.25);border-radius:6px;padding:7px 10px;font-size:0.75rem;font-weight:600;color:#d97706">🟠 IA sin configurar</div>', unsafe_allow_html=True)

    # ── Info de usuario en sesión + botón de logout ───────────────────────────
    st.markdown('<hr style="margin:12px 0">', unsafe_allow_html=True)
    _usr_ses = st.session_state.get("usuario_actual", {})
    _rol_ses = _usr_ses.get("rol", "")
    _nom_ses = _usr_ses.get("nombre_completo") or _usr_ses.get("username", "")
    _badge_rol = ("#1F6F54", "Admin") if _rol_ses == "Admin" else ("#6b7280", "Operario")
    st.markdown(
        f'''<div style="background:var(--secondary-background-color);border:1px solid var(--border-color);
        border-radius:8px;padding:8px 12px;margin-bottom:8px">
        <div style="font-size:0.72rem;opacity:0.5;font-weight:600;text-transform:uppercase;margin-bottom:2px">Sesión activa</div>
        <div style="font-size:0.85rem;font-weight:700">{_nom_ses}</div>
        <div style="display:inline-block;background:{_badge_rol[0]};color:white;
             font-size:0.62rem;font-weight:700;padding:2px 7px;border-radius:4px;
             margin-top:3px;text-transform:uppercase">{_badge_rol[1]}</div>
        </div>''',
        unsafe_allow_html=True
    )
    if st.button("⏻ Cerrar sesión", use_container_width=True, key="btn_logout"):
        _limpiar_sesion()
        st.rerun()

    # ── ✨ Copiloto IA Flotante — popover nativo (Zero-Click UX) ─────────────
    st.markdown('<hr style="margin:12px 0">', unsafe_allow_html=True)
    with st.sidebar.popover("✨ Copiloto IA", use_container_width=True):
        st.markdown(
            "<div style='font-size:0.82rem;font-weight:700;margin-bottom:8px;"
            "color:#1F6F54'>Asistente contextual</div>"
            "<div style='font-size:0.73rem;opacity:0.6;margin-bottom:10px'>"
            "Toca una pregunta rápida o escribe la tuya.</div>",
            unsafe_allow_html=True
        )

        # ── Preguntas rápidas (Zero-Click) ────────────────────────────────────
        _sos_ctx = st.session_state.get("nav_radio", "Inicio")

        # ── Volcado resumido de st.session_state.pre → memoria del Copiloto ──
        # Filtra claves internas (_origen, etc.) y traduce a texto legible.
        def _volcado_pre() -> str:
            _pre = st.session_state.get("pre", {})
            if not _pre:
                return ""
            _campos = {
                "categoria":         "Material (categoría)",
                "referencia":        "Referencia del material",
                "precio_m2":         "Precio/m² del material (COP)",
                "area_placa":        "Área de lámina comprada (m²)",
                "m2_real":           "m² del proyecto",
                "m2_usados":         "m² instalados",
                "margen_pct":        "Margen de venta (%)",
                "nombre_cliente":    "Cliente",
                "tipo_proyecto":     "Tipo de proyecto",
                "etapa":             "Etapa de obra",
                "dias":              "Días de trabajo",
                "personas":          "Personas en obra",
                "vehiculo_entrega":  "Vehículo de entrega",
                "km":                "Kilómetros al sitio",
                "num_peajes":        "Número de peajes",
                "foraneo_activo":    "¿Proyecto foráneo?",
                "noches":            "Noches de viáticos",
                "zocalo_activo":     "¿Hay zócalos?",
                "zocalo_ml":         "Metros lineales de zócalo",
                "piezas":            "Piezas del proyecto",
            }
            _lineas = []
            for _k, _label in _campos.items():
                _v = _pre.get(_k)
                if _v is None or _v == "" or _v == [] or _v == {}:
                    continue
                if isinstance(_v, list) and _k == "piezas":
                    _lineas.append(f"- {_label}: {len(_v)} pieza(s)")
                    for _pi, _p in enumerate(_v[:5]):   # máx 5 piezas
                        _lineas.append(
                            f"    • Pieza {_pi+1}: {_p.get('nombre','?')} "
                            f"{_p.get('largo',0)} ml × {_p.get('ancho',0)} m"
                        )
                elif isinstance(_v, bool):
                    _lineas.append(f"- {_label}: {'Sí' if _v else 'No'}")
                elif isinstance(_v, float):
                    _lineas.append(f"- {_label}: {_v:,.2f}".replace(",", "."))
                else:
                    _lineas.append(f"- {_label}: {_v}")
            return "\n".join(_lineas)

        _sos_form_ctx = _volcado_pre()

        _PREGUNTAS_RAPIDAS = [
            "¿Qué es el AIU y cómo se calcula?",
            "¿Cómo calculo el retal de una lámina?",
            "¿Qué cobro en proyectos foráneos?",
        ]
        for _q in _PREGUNTAS_RAPIDAS:
            if st.button(_q, use_container_width=True, key=f"sos_q_{_q[:20]}"):
                with st.spinner("Consultando IA..."):
                    _resp_rapida = chat_sos(_q, _sos_ctx, _sos_form_ctx,
                                                  contexto_tarifas=st.session_state.get("tarifas_custom"))
                st.session_state["_sos_ultima_respuesta"] = _resp_rapida
                st.session_state["_sos_ultima_pregunta"]  = _q

        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
        st.divider()

        # ── Input manual ──────────────────────────────────────────────────────
        _sos_pregunta = st.text_input(
            "Tu duda",
            placeholder="Ej: ¿Qué es el disco diamantado?",
            label_visibility="collapsed",
            key="sos_input"
        )
        if st.button("Preguntar →", use_container_width=True, key="btn_sos",
                     type="primary"):
            if _sos_pregunta.strip():
                with st.spinner("Consultando..."):
                    _sos_resp = chat_sos(_sos_pregunta.strip(), _sos_ctx, _sos_form_ctx,
                                               contexto_tarifas=st.session_state.get("tarifas_custom"))
                st.session_state["_sos_ultima_respuesta"] = _sos_resp
                st.session_state["_sos_ultima_pregunta"]  = _sos_pregunta.strip()
            else:
                st.warning("Escribe tu duda primero.", icon="⚠️")

        # ── Respuesta de la IA (fondo azul suave) ─────────────────────────────
        if st.session_state.get("_sos_ultima_respuesta"):
            # M-04 FIX — Prevención XSS:
            # La respuesta viene de la API de Anthropic, pero puede contener
            # caracteres HTML especiales si el modelo genera código, URLs con
            # parámetros, o si un atacante logra inyectar contenido vía el
            # campo de pregunta (prompt injection → reflected XSS).
            # html.escape() convierte <, >, &, " y ' a sus entidades seguras
            # ANTES de que el string entre al bloque unsafe_allow_html.
            # Solo después se restauran los saltos de línea como <br> legítimos.
            _respuesta_escapada = _html_mod.escape(
                st.session_state["_sos_ultima_respuesta"]
            ).replace("\n", "<br>")
            st.markdown(
                f"<div style='background:rgba(31,111,84,0.08);border:1px solid rgba(31,111,84,0.25);"
                f"border-left:3px solid #1F6F54;border-radius:8px;"
                f"padding:10px 12px;margin-top:8px;font-size:0.8rem;line-height:1.6'>"
                f"<div style='font-size:0.65rem;font-weight:700;color:#1F6F54;"
                f"text-transform:uppercase;margin-bottom:6px'>✨ Copiloto responde</div>"
                f"{_respuesta_escapada}"
                f"</div>",
                unsafe_allow_html=True
            )

# ═══════════════════════════════════════════════════════════════════════════════
# TOUR GUIADO (ONBOARDING) — DISEÑO CORPORATIVO
# ═══════════════════════════════════════════════════════════════════════════════
if st.session_state.get("onboarding_activo"):
    _op    = min(st.session_state.get("onboarding_paso", 0), len(TOUR_PASOS) - 1)
    _paso  = TOUR_PASOS[_op]
    _total = len(TOUR_PASOS)

    with st.container(border=True):
        # ── Encabezado: etiqueta dorada + contador ────────────────────────────
        _etiqueta = _paso.get("etiqueta", f"PASO {_op + 1}")
        _es_bienvenida = (_paso.get("id") == "bienvenida")
        if _es_bienvenida:
            # Paso de bienvenida: nombre empresa como identidad, sin badge pequeño
            st.markdown(
                f"<div style='display:flex;align-items:center;justify-content:space-between;"
                f"margin-bottom:14px'>"
                f"<span style='font-size:0.70rem;font-weight:900;letter-spacing:0.18em;"
                f"color:#C9A45C;text-transform:uppercase;border-bottom:2px solid #C9A45C;"
                f"padding-bottom:3px'>{_etiqueta}</span>"
                f"<span style='font-size:0.62rem;font-weight:600;letter-spacing:0.06em;"
                f"opacity:0.4;text-transform:uppercase'>PASO {_op + 1} DE {_total}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"<div style='display:flex;align-items:center;justify-content:space-between;"
                f"margin-bottom:14px'>"
                f"<span style='font-size:0.62rem;font-weight:800;letter-spacing:0.16em;"
                f"color:#C9A45C;text-transform:uppercase'>{_etiqueta}</span>"
                f"<span style='font-size:0.62rem;font-weight:600;letter-spacing:0.06em;"
                f"opacity:0.4;text-transform:uppercase'>PASO {_op + 1} DE {_total}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        # ── Ícono + título en columnas ────────────────────────────────────────
        if _es_bienvenida:
            # Paso bienvenida: título prominente sin ícono lateral
            st.markdown(
                f"<h3 style='margin:0 0 2px;font-family:Playfair Display,serif;"
                f"color:#1F6F54;font-size:1.35rem;line-height:1.2'>"
                f"{_paso['titulo']}</h3>",
                unsafe_allow_html=True,
            )
        else:
            _col_icon, _col_text = st.columns([0.6, 9.4])
            with _col_icon:
                st.markdown(
                    f"<div style='font-size:2.1rem;padding-top:2px;line-height:1'>"
                    f"{_paso.get('icono', '📋')}</div>",
                    unsafe_allow_html=True,
                )
            with _col_text:
                st.markdown(
                    f"<h3 style='margin:0 0 2px;font-family:Playfair Display,serif;"
                    f"color:#1F6F54;font-size:1.25rem;line-height:1.2'>"
                    f"{_paso['titulo']}</h3>",
                    unsafe_allow_html=True,
                )
        # ── Cuerpo del texto ──────────────────────────────────────────────────
        st.markdown(
            f"<div style='margin-top:12px;font-size:0.9rem;line-height:1.72;opacity:0.82'>"
            f"{_paso['cuerpo'].replace(chr(10), '<br>')}</div>",
            unsafe_allow_html=True,
        )
        # ── Barra de progreso ─────────────────────────────────────────────────
        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        st.progress((_op + 1) / _total)
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

        # ── Botones de navegación ─────────────────────────────────────────────
        _b_ant, _b_skip, _b_sig = st.columns([1, 1.4, 1.6])
        with _b_ant:
            if _op > 0:
                if st.button("← Anterior", use_container_width=True, key="tour_ant"):
                    st.session_state.onboarding_paso -= 1
                    st.rerun()
        with _b_skip:
            if st.button("Saltar recorrido", use_container_width=True, key="tour_skip",
                         help="Puedes volver a este recorrido desde la pantalla de Inicio"):
                st.session_state.onboarding_activo = False
                st.session_state.tour_completado   = True
                st.query_params["guia"] = "terminada"
                st.rerun()
        with _b_sig:
            if _op < _total - 1:
                if st.button("Siguiente →", type="primary", use_container_width=True, key="tour_sig"):
                    st.session_state.onboarding_paso += 1
                    st.rerun()
            else:
                if st.button("Empezar a cotizar 🚀", type="primary", use_container_width=True, key="tour_fin"):
                    st.session_state.onboarding_activo = False
                    st.session_state.tour_completado   = True
                    st.query_params["guia"] = "terminada"
                    st.rerun()

    st.markdown("<div style='margin-bottom:20px'></div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# HELPER GLOBAL: cargar cotización del historial en la calculadora
# DEBE estar a nivel global (NO anidado en elif pagina == "Historial") para que
# el st.rerun() que cambia la página no destruya la función antes de ejecutarse.
# ═══════════════════════════════════════════════════════════════════════════════
def _cargar_en_calculadora(rid, rnum, rjson):
    """Carga una cotización del historial en el formulario para editarla."""
    try:
        datos = json.loads(rjson)
    except Exception:
        st.error("No se pudo leer el JSON de esta cotización.")
        return

    eg = datos.get("_estado_guardado", datos)

    # ── 1. Limpiar TODO el estado anterior del wizard ─────────────────────────
    _CLAVES_FORMULARIO = [
        "piezas", "materiales_proyecto", "aiu_items",
        "zocalo_activo", "adicionales_activos", "foraneo_activo",
        "viaticos_activos", "resultado_calculo", "resumen_ia",
        "pre", "editando_id", "cotizacion",
        "_cantidades_add_restauradas", "_sp_borrador_hash",
        "last_pre_hash", "_cotiz_guardada", "_cotiz_guardada_num",
        "_cotiz_formalizada", "_cotiz_formalizada_num", "borrador_actual_id",
    ]
    for _k in _CLAVES_FORMULARIO:
        st.session_state.pop(_k, None)

    # ── 2. Limpiar store_permanente de cdir_* para que no pise los datos cargados
    _sp_limpia = st.session_state.get("store_permanente", {})
    for _sk in [k for k in list(_sp_limpia.keys()) if k.startswith("cdir_")]:
        del _sp_limpia[_sk]

    # ── 3. Marcar _borrador_restaurado para bloquear la restauración automática
    st.session_state["_borrador_restaurado"] = True

    # ── 4. Marcar modo edición ────────────────────────────────────────────────
    st.session_state.editando_id  = rid
    st.session_state.editando_num = rnum
    eg["_origen"] = "historial"
    st.session_state.pre = eg

    # ── 5. Hidratar listas dinámicas directamente en session_state ───────────
    # El wizard las lee de session_state, no solo de pre
    _piezas_cargadas = eg.get("piezas", [])
    if _piezas_cargadas:
        st.session_state.piezas = _piezas_cargadas

    _mats_cargados = eg.get("materiales_proyecto", [])
    if _mats_cargados:
        st.session_state.materiales_proyecto = _mats_cargados

    # cantidades_add necesita su propia clave para el widget de adicionales
    if eg.get("cantidades_add"):
        st.session_state["_cantidades_add_restauradas"] = eg["cantidades_add"]

    # Restaurar retal_id por material (retal_id_0, retal_id_1…)
    for _rk, _rv in eg.items():
        if _rk.startswith("retal_id_") and _rv:
            st.session_state[_rk] = _rv

    if "AIU" in rnum or "aiu" in str(datos.get("tipo_proyecto", "")).lower() \
            or "aiu" in str(eg.get("tipo_proyecto", "")).lower():
        st.session_state.aiu_items = eg.get("aiu_items", [])
        destino = "Cotizacion AIU"
    else:
        destino = "Cotizacion Directa"

    # ── 6. Resetear wizard a paso 0 ───────────────────────────────────────────
    st.session_state.cdir_paso    = 0
    st.session_state.aiu_paso     = 0
    st.session_state.cdir_success = False

    st.session_state.nav_radio = destino
    st.query_params["pagina"]  = destino
    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# INICIO
# ═══════════════════════════════════════════════════════════════════════════════


if pagina == "Inicio":
    st.markdown(f"""
    <div style="background:var(--secondary-background-color); border-radius:16px;padding:40px 44px;margin-bottom:28px; border:2px solid #1F6F54;">
      <div style="color:#C9A45C;font-size:0.68rem;text-transform:uppercase;letter-spacing:0.15em;font-weight:800;margin-bottom:12px">
        Costo360 — Plataforma B2B
      </div>
      <div style="font-size:2.4rem;font-weight:900;font-family:'Playfair Display',serif;line-height:1.1;margin-bottom:14px; color:var(--text-color);">
        Sistema de Cotización<br>Profesional
      </div>
      <div style="opacity:0.8;font-size:0.92rem;line-height:1.65;max-width:500px; color:var(--text-color);">
        Calcula el costo real de tus proyectos comerciales. Cotización Directa, licitaciones AIU y exportación a PDF adaptable a cualquier entorno.
      </div>
    </div>
    """, unsafe_allow_html=True)

    if st.button("🚀 Reactivar Guía de Inicio", use_container_width=True):
        st.session_state.onboarding_activo = True
        st.session_state.onboarding_paso = 0
        st.rerun()

    st.markdown("---")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Materiales", "5 tipos", "Mármol · Granito · Sint. · Quartz · Quarzita")
    c2.metric("Tiempo", "2 min", "vs. 45–90 min manual")
    c3.metric("Estructura", "AIU + IVA", "Norma colombiana")
    c4.metric("Exporta", "PDF", "Cotización + Cuenta de cobro")


# ═══════════════════════════════════════════════════════════════════════════════
# COTIZACIÓN DIRECTA
# ═══════════════════════════════════════════════════════════════════════════════

elif pagina == "⚡ Modo Express":
    _ui_cotizacion_express()

elif pagina == "Cotizacion Directa":
    _ui_cotizacion_directa(
        fn_sp=_sp,
        fn_sp_set=_sp_set,
        fn_sp_commit_borrador=_sp_commit_borrador,
        fn_sp_agregar_pieza=_sp_agregar_pieza,
        fn_sp_eliminar_pieza=_sp_eliminar_pieza,
        fn_sp_sync_piezas=_sp_sync_piezas,
        fn_sp_agregar_material=_sp_agregar_material,
        fn_sp_eliminar_material=_sp_eliminar_material,
        fn_sp_sync_materiales=_sp_sync_materiales,
        fn_guardar_cotizacion=_guardar_cotizacion,
        fn_actualizar_cotizacion=_actualizar_cotizacion,
        fn_guardar_borrador_cotizacion=_guardar_borrador_cotizacion,
        fn_guardar_config=_guardar_config,
        fn_leer_config=_leer_config,
        fn_clave_borrador_cdir=_clave_borrador_cdir,
        fn_consultar_retal=_consultar_retal,
        fn_marcar_retal_usado=_marcar_retal_usado,
        fn_get_tarifas=get_tarifas,
        fn_get_logistica=get_logistica,
        fn_get_viaticos=get_viaticos,
        fn_get_adicionales=get_adicionales,
        fn_generar_snapshot_datos=_generar_snapshot_datos,
        fn_cb_cdir_nombre_cliente=_cb_cdir_nombre_cliente,
        fn_cb_cdir_tipos_proyecto=_cb_cdir_tipos_proyecto,
        fn_cb_cdir_etapa=_cb_cdir_etapa,
        fn_cb_cdir_agente_externo=_cb_cdir_agente_externo,
        fn_cb_cdir_km_rango=_cb_cdir_km_rango,
        fn_cb_cdir_foraneo=_cb_cdir_foraneo,
        fn_cb_cdir_viaticos_activos=_cb_cdir_viaticos_activos,
        fn_cb_cdir_tipo_aloj=_cb_cdir_tipo_aloj,
        fn_cb_cdir_noches=_cb_cdir_noches,
        fn_cb_cdir_perfil_desperdicio=_cb_cdir_perfil_desperdicio,
        fn_cb_cdir_adicionales_activos=_cb_cdir_adicionales_activos,
        fn_cb_cdir_incluir_iva=_cb_cdir_incluir_iva,
    )
elif pagina == "Cotizacion AIU":
    _ui_cotizacion_aiu(
        fn_guardar_cotizacion=_guardar_cotizacion,
        fn_actualizar_cotizacion=_actualizar_cotizacion,
        fn_guardar_config=_guardar_config,
        fn_leer_config=_leer_config,
        fn_clave_borrador_aiu=_clave_borrador_aiu,
        fn_sp_set=_sp_set,
        fn_sp_agregar_item_aiu=_sp_agregar_item_aiu,
        fn_sp_eliminar_item_aiu=_sp_eliminar_item_aiu,
        fn_sp_sync_items_aiu=_sp_sync_items_aiu,
        # --- Dependencias de Estado (Anti-Amnesia) restauradas ---
        fn_sp=_sp,
        fn_sp_commit_borrador_aiu=_sp_commit_borrador_aiu,
        fn_cb_aiu_nombre_cliente=_cb_aiu_nombre_cliente,
        fn_cb_aiu_numero=_cb_aiu_numero,
        fn_cb_aiu_a_pct=_cb_aiu_a_pct,
        fn_cb_aiu_i_pct=_cb_aiu_i_pct,
        fn_cb_aiu_u_pct=_cb_aiu_u_pct,
        fn_cb_aiu_anticipo=_cb_aiu_anticipo,
        fn_cb_aiu_incluir_iva=_cb_aiu_incluir_iva,
        fn_cb_aiu_telefono_cliente=_cb_aiu_telefono_cliente,
        fn_cb_aiu_email_cliente=_cb_aiu_email_cliente,
        fn_cb_aiu_ciudad_proyecto=_cb_aiu_ciudad_proyecto,
        fn_cb_aiu_dias_entrega=_cb_aiu_dias_entrega,
        fn_cb_aiu_dias_validez=_cb_aiu_dias_validez,
    )
elif pagina == "Historial":
    _ui_historial(
        fn_listar=_listar_cotizaciones,
        fn_actualizar_estado=_actualizar_estado,
        fn_eliminar=_eliminar_cotizacion,
        fn_cargar_en_calculadora=_cargar_en_calculadora,
        fn_stats_db=_stats_db,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD — ANÁLISIS DE NEGOCIO CON DATA LITERACY
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Dashboard":
    _ui_dashboard(_stats_db, _stats_retales)

# ═══════════════════════════════════════════════════════════════════════════════
# SOBRANTES APROVECHABLES (antes: Banco de Retales)
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Banco de Retales":
    _ui_banco_retales(
        fn_listar=_listar_retales,
        fn_eliminar=_eliminar_retal,
        fn_guardar_manual=_guardar_retal_manual,
        fn_actualizar_precio=_actualizar_precio_retal,
    )

# ═══════════════════════════════════════════════════════════════════════════════
# PARÁMETROS, ASISTENTE IA Y CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Parametros":
    _ui_parametros(
        fn_get_tarifas=get_tarifas,
        fn_get_viaticos=get_viaticos,
        fn_get_logistica=get_logistica,
        fn_get_adicionales=get_adicionales,
        fn_guardar_config=_guardar_config,
        fn_chat_parametros=_chat_parametros,
        fn_interceptar_ia=_interceptar_accion_ia,
        fn_sp=_sp,
        fn_numero_completo=numero_completo,
        fn_ia_disponible=ia_disponible,
    )

elif pagina == "Asistente IA":

    # ── Estado del chat ───────────────────────────────────────────────────────
    if "chat" not in st.session_state:
        st.session_state.chat = []
    if "chat_input_key" not in st.session_state:
        st.session_state.chat_input_key = 0

    # ── FIX-4 Carga tardía del historial (post-auth, _uid() ya tiene ID real) ─
    # _cargar_config_desde_db se ejecuta antes de auth → _uid() = "anon".
    # Aquí, ya autenticado, hacemos una segunda lectura con la clave correcta.
    if not st.session_state.chat and not st.session_state.get("_chat_hidratado"):
        try:
            _chat_bd = _leer_config(f"chat_{_uid()}")
            if _chat_bd and isinstance(_chat_bd, list):
                st.session_state.chat = _chat_bd
        except Exception:
            pass
        st.session_state["_chat_hidratado"] = True

    # ── CSS refinado ──────────────────────────────────────────────────────────
    st.markdown("""
    <style>
    /* Burbujas de chat */
    .burbuja-wrap-user { display:flex; flex-direction:column; align-items:flex-end; margin: 6px 0; }
    .burbuja-wrap-ai   { display:flex; flex-direction:column; align-items:flex-start; margin: 6px 0; }

    .burbuja-label {
        font-size: 0.64rem;
        font-weight: 700;
        letter-spacing: 0.07em;
        text-transform: uppercase;
        opacity: 0.38;
        margin-bottom: 4px;
        padding: 0 4px;
    }
    .burbuja-user {
        background: #1F6F54;
        color: white;
        border-radius: 18px 18px 4px 18px;
        padding: 10px 16px;
        max-width: 78%;
        font-size: 0.9rem;
        line-height: 1.6;
        word-break: break-word;
    }
    .burbuja-ai {
        background: var(--secondary-background-color);
        border: 1px solid var(--border-color);
        border-radius: 18px 18px 18px 4px;
        padding: 10px 16px;
        max-width: 84%;
        font-size: 0.9rem;
        line-height: 1.68;
        word-break: break-word;
    }

    /* Tarjetas de inicio */
    .arranque-card {
        border: 1px solid var(--border-color);
        border-radius: 14px;
        padding: 16px 18px;
        background: var(--secondary-background-color);
        height: 100%;
        transition: border-color 0.15s;
    }
    .arranque-card:hover { border-color: #1F6F54; }
    .arranque-icono   { font-size: 1.3rem; margin-bottom: 8px; }
    .arranque-titulo  { font-weight: 700; font-size: 0.9rem; margin-bottom: 5px; }
    .arranque-desc    { opacity: 0.52; font-size: 0.79rem; line-height: 1.5; }

    /* Pill de proyecto detectado */
    .pill-proyecto {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        border: 1.5px solid #1F6F54;
        border-radius: 10px;
        padding: 7px 13px;
        font-size: 0.81rem;
        font-weight: 600;
        margin: 8px 0 4px;
        background: rgba(31,111,84,0.06);
        color: #1F6F54;
    }
    .pill-proyecto span { opacity: 0.65; font-weight: 400; }

    /* Separador decorativo */
    .chat-divider {
        border: none;
        border-top: 1px solid var(--border-color);
        margin: 14px 0 10px;
        opacity: 0.4;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── Guard: IA no disponible ───────────────────────────────────────────────
    if not ia_disponible():
        st.markdown(
            "<h2 style='font-family:Playfair Display,serif;margin-bottom:8px'>Asistente IA</h2>",
            unsafe_allow_html=True
        )
        with st.container(border=True):
            st.markdown("#### 🔑 API key no configurada")
            st.markdown(
                "Para activar el asistente, ve a **Configuración** e ingresa tu API key de Anthropic.  \n"
                "El asistente te permite describir proyectos en lenguaje natural, "
                "consultar márgenes y recibir análisis de cotizaciones."
            )
            if st.button("Ir a Configuración →", type="primary"):
                st.session_state.nav_radio = "Configuracion"
                st.session_state.radio_ui = "Configuracion"
                st.rerun()
        st.stop()

    # ── Header ────────────────────────────────────────────────────────────────
    _col_hdr, _col_clr = st.columns([6, 1])
    with _col_hdr:
        st.markdown(
            "<h2 style='font-family:Playfair Display,serif;margin-bottom:2px'>Asistente IA</h2>"
            "<p style='opacity:0.48;font-size:0.83rem;margin:0 0 8px'>"
            "Describe un proyecto o consulta cualquier duda sobre costos y cotización."
            "</p>",
            unsafe_allow_html=True
        )
    with _col_clr:
        if st.session_state.chat:
            st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
            if st.button("🗑️ Limpiar", use_container_width=True, help="Borra el historial de esta conversación"):
                st.session_state.chat = []
                st.session_state.chat_input_key += 1
                # FIX-4: borrar permanentemente en BD para que el F5 tampoco lo restaure
                try:
                    _guardar_config(f"chat_{_uid()}", [])
                except Exception:
                    pass
                st.rerun()

    # ── Estado vacío: tarjetas de inicio ─────────────────────────────────────
    if not st.session_state.chat:
        st.markdown(
            "<div style='font-size:0.7rem;font-weight:700;opacity:0.38;letter-spacing:0.09em;"
            "text-transform:uppercase;margin:12px 0 14px'>¿Por dónde empezar?</div>",
            unsafe_allow_html=True
        )
        _arranques = [
            {
                "icono": "🧮",
                "titulo": "Cotizar un proyecto",
                "desc":   "Describe el material, medidas y tipo de obra. La IA extrae los datos y los carga en la calculadora.",
                "msg":    "Tengo un mesón de cocina en mármol crema marfil, 3,5 metros de largo por 60 cm de ancho. El proveedor me cobró $220.000/m² por una placa de 5,94 m². ¿Me ayudas a cotizarlo?"
            },
            {
                "icono": "💰",
                "titulo": "¿Estoy cobrando bien?",
                "desc":   "Ingresa tu precio y la IA revisa si el margen es saludable para el mercado de Barranquilla.",
                "msg":    "Le voy a cobrar $3.200.000 a un cliente por 4 metros lineales de granito instalado en cocina. ¿Ese precio tiene buen margen o estoy dejando plata sobre la mesa?"
            },
            {
                "icono": "⚖️",
                "titulo": "Comparar materiales",
                "desc":   "Descubre cuál material deja más utilidad para un mismo proyecto.",
                "msg":    "Para un mesón de 5 ml, ¿qué me conviene más cotizar: mármol, granito o sinterizado? ¿Cuál deja mejor margen normalmente?"
            },
            {
                "icono": "🔍",
                "titulo": "Costos que se te olvidan",
                "desc":   "La IA explica qué cargos debes incluir para no quedar en rojo al final del proyecto.",
                "msg":    "Siempre que termino un proyecto siento que gané menos de lo esperado. ¿Qué costos suele olvidar un marmolero al cotizar?"
            },
        ]
        _col_a, _col_b = st.columns(2)
        for _i, _ar in enumerate(_arranques):
            _col = _col_a if _i % 2 == 0 else _col_b
            with _col:
                # Tarjeta + botón dentro de un contenedor unificado
                with st.container(border=True):
                    st.markdown(
                        f'<div class="arranque-icono">{_ar["icono"]}</div>'
                        f'<div class="arranque-titulo">{_ar["titulo"]}</div>'
                        f'<div class="arranque-desc">{_ar["desc"]}</div>',
                        unsafe_allow_html=True
                    )
                    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
                    if st.button("Consultar →", key=f"arr_{_i}", use_container_width=True):
                        st.session_state.chat.append({"role": "user", "content": _ar["msg"]})
                        with st.spinner("El asistente está analizando…"):
                            _r = chat_con_ia([], _ar["msg"],
                                               contexto_tarifas=st.session_state.get("tarifas_custom"))
                            _datos = None
                            if any(w in _ar["msg"].lower() for w in ["mesón", "cocina", "ml", "metros", "placa"]):
                                _datos = interpretar_proyecto(_ar["msg"])
                        _msg_ia = {"role": "assistant", "content": _r}
                        if _datos and _datos.get("categoria"):
                            _msg_ia["datos_proyecto"] = _datos
                        st.session_state.chat.append(_msg_ia)
                        st.rerun()

    else:
        # ── Render del historial ──────────────────────────────────────────────
        for _midx, _msg in enumerate(st.session_state.chat):
            if _msg["role"] == "user":
                # Burbuja usuario — derecha, azul
                st.markdown(
                    '<div class="burbuja-wrap-user">'
                    '<div class="burbuja-label">Tú</div>'
                    f'<div class="burbuja-user">{_msg["content"]}</div>'
                    '</div>',
                    unsafe_allow_html=True
                )
            else:
                # Burbuja asistente — izquierda, fondo neutro
                # Usamos st.chat_message internamente para que el Markdown se renderice bien
                with st.chat_message("assistant", avatar="🤖"):
                    st.markdown(_msg["content"])

                # Si el último mensaje de la IA detectó datos de proyecto → CTA
                if _msg.get("datos_proyecto") and _midx == len(st.session_state.chat) - 1:
                    _d = _msg["datos_proyecto"]
                    _partes = []
                    if _d.get("categoria"):   _partes.append(_d["categoria"])
                    if _d.get("referencia"):  _partes.append(_d["referencia"])
                    if _d.get("m2_proyecto"): _partes.append(f'{_d["m2_proyecto"]} m²')
                    _resumen_str = " · ".join(_partes) if _partes else "datos detectados"

                    _cta_col, _ = st.columns([2, 3])
                    with _cta_col:
                        st.markdown(
                            f'<div class="pill-proyecto">📋 Proyecto detectado '
                            f'<span>— {_resumen_str}</span></div>',
                            unsafe_allow_html=True
                        )
                        if st.button("Cargar en la calculadora →", key=f"cargar_{_midx}",
                                     type="primary", use_container_width=True):
                            _d["_origen"] = "ia"
                            st.session_state.pre = _d
                            st.session_state.nav_radio = "Cotizacion Directa"
                            st.session_state.radio_ui = "Cotizacion Directa"
                            st.query_params["pagina"] = "Cotizacion Directa"
                            st.rerun()

        # ── Sugerencias contextuales ──────────────────────────────────────────
        _ultimo_ai = next(
            (_m for _m in reversed(st.session_state.chat) if _m["role"] == "assistant"), None
        )
        if _ultimo_ai:
            _ult  = _ultimo_ai["content"].lower()
            _sugs = []
            if any(w in _ult for w in ["margen", "utilidad", "precio sugerido"]):
                _sugs += ["¿Cómo mejorar el margen?", "¿Cuál es el mínimo aceptable?"]
            if any(w in _ult for w in ["retal", "desperdicio", "aprovechamiento"]):
                _sugs += ["¿Cómo reduzco el retal?"]
            if any(w in _ult for w in ["material", "mármol", "granito", "sinterizado"]):
                _sugs += ["¿Cuál material tiene más riesgo de rotura?", "¿Sinterizado vs granito: cuál conviene más?"]
            if any(w in _ult for w in ["aiu", "imprevisto", "administración"]):
                _sugs += ["¿Cuándo aplica la estructura AIU?", "¿El IVA va sobre todo o solo sobre la utilidad?"]
            if not _sugs:
                _sugs = ["¿Qué más debo incluir en el precio?", "¿Cuál es el error más común al cotizar?", "Dame un ejemplo con números reales"]

            _sugs = _sugs[:3]
            st.markdown("<hr class='chat-divider'>", unsafe_allow_html=True)
            st.markdown(
                "<div style='font-size:0.68rem;font-weight:700;opacity:0.38;"
                "letter-spacing:0.07em;text-transform:uppercase;margin-bottom:8px'>"
                "Seguir preguntando</div>",
                unsafe_allow_html=True
            )
            _sug_cols = st.columns(len(_sugs))
            for _si, _sug in enumerate(_sugs):
                with _sug_cols[_si]:
                    if st.button(_sug, key=f"sug_{_si}_{st.session_state.chat_input_key}",
                                 use_container_width=True):
                        st.session_state.chat.append({"role": "user", "content": _sug})
                        with st.spinner("El asistente está pensando…"):
                            _sr = chat_con_ia(
                                [m for m in st.session_state.chat[:-1]
                                 if m["role"] in ("user", "assistant")],
                                _sug,
                                contexto_tarifas=st.session_state.get("tarifas_custom"),
                            )
                        st.session_state.chat.append({"role": "assistant", "content": _sr})
                        st.session_state.chat_input_key += 1
                        # FIX-4: persistir también al usar las tarjetas de sugerencias
                        try:
                            _guardar_config(f"chat_{_uid()}", [
                                {"role": m["role"], "content": m["content"]}
                                for m in st.session_state.chat
                                if m.get("role") in ("user", "assistant")
                            ])
                        except Exception:
                            pass
                        st.rerun()

    # ── Input de texto ────────────────────────────────────────────────────────
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
    st.markdown("<hr class='chat-divider'>", unsafe_allow_html=True)

    _ic, _sc = st.columns([6, 1])
    with _ic:
        _nuevo = st.text_input(
            "Escribe tu mensaje",
            key=f"chat_inp_{st.session_state.chat_input_key}",
            placeholder="Describe tu proyecto o escribe tu pregunta…",
            label_visibility="collapsed",
        )
    with _sc:
        _enviar = st.button(
            "Enviar ➤",
            type="primary",
            use_container_width=True,
            key=f"enviar_{st.session_state.chat_input_key}"
        )

    if _enviar and _nuevo.strip():
        _texto = _nuevo.strip()
        st.session_state.chat.append({"role": "user", "content": _texto})

        with st.spinner("El asistente está analizando tu consulta…"):
            _kw_proyecto = ["mesón","meson","cocina","baño","bano","escalera","fachada",
                            "piso","ml","metro","placa","granito","mármol","sinterizado",
                            "quarztone","quarzita","cuarzo"]
            _es_proyecto = sum(1 for w in _kw_proyecto if w in _texto.lower()) >= 2
            _datos_ext   = interpretar_proyecto(_texto) if _es_proyecto else None
            _resp        = chat_con_ia(
                [m for m in st.session_state.chat[:-1] if m["role"] in ("user","assistant")],
                _texto,
                contexto_tarifas=st.session_state.get("tarifas_custom"),
            )

        _nuevo_msg_ia = {"role": "assistant", "content": _resp}
        if _datos_ext and _datos_ext.get("categoria"):
            _nuevo_msg_ia["datos_proyecto"] = _datos_ext

        st.session_state.chat.append(_nuevo_msg_ia)
        st.session_state.chat_input_key += 1
        # FIX-4: persistir el historial completo en BD después de cada intercambio
        # Se serializa solo text/role — datos_proyecto con dicts simples es JSON-safe.
        try:
            _chat_serial = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state.chat
                if m.get("role") in ("user", "assistant")
            ]
            _guardar_config(f"chat_{_uid()}", _chat_serial)
        except Exception:
            pass
        st.rerun()



elif pagina == "Configuracion":
    _ui_configuracion(
        fn_guardar_config=_guardar_config,
        fn_guardar_logo=_guardar_logo,
        fn_crear_usuario=_crear_usuario,
        fn_listar_usuarios=_listar_usuarios,
        fn_eliminar_usuario=_eliminar_usuario,
    )
elif pagina == "Gestion de Equipo":
    # Guard de seguridad: doble verificación de rol
    _ge_rol = st.session_state.get("usuario_actual", {}).get("rol", "Operario")
    if _ge_rol != "Admin":
        st.error("🔒 Acceso restringido. Solo los Administradores pueden acceder a esta sección.")
        st.stop()

    st.markdown(
        "<h2 style='font-family:Playfair Display,serif'>👥 Gestión de Equipo</h2>",
        unsafe_allow_html=True
    )
    st.markdown(
        "<p style='opacity:0.6;font-size:0.88rem;margin-bottom:20px'>"
        "Administra quién tiene acceso al sistema. Las contraseñas se encriptan con "
        "PBKDF2-SHA256 antes de guardarse — nunca se almacenan en texto plano.</p>",
        unsafe_allow_html=True
    )

    _ge_tab_crear, _ge_tab_equipo = st.tabs(["➕ Registrar usuario", "📋 Equipo activo"])

    # ── Tab: Registrar nuevo usuario con st.form ──────────────────────────────
    with _ge_tab_crear:
        st.markdown(
            "<div style='background:rgba(31,111,84,0.06);border-left:3px solid #1F6F54;"
            "border-radius:0 8px 8px 0;padding:10px 14px;font-size:0.8rem;margin-bottom:18px'>"
            "Todos los campos marcados con <strong>*</strong> son obligatorios. "
            "El <strong>PIN</strong> de 4 dígitos sirve para que el usuario recupere su contraseña "
            "desde la pantalla de inicio de sesión, sin necesidad de correo electrónico.</div>",
            unsafe_allow_html=True
        )

        with st.form("form_ge_nuevo_usuario", clear_on_submit=True):
            _ge_c1, _ge_c2 = st.columns(2)
            _ge_nombre = _ge_c1.text_input(
                "Nombre completo *",
                placeholder="Ej: Jorge Castro Díaz"
            )
            _ge_user = _ge_c2.text_input(
                "Username *",
                placeholder="Ej: jcastro  (sin espacios, minúsculas)",
                help="Se convierte a minúsculas automáticamente al guardar."
            )
            _ge_c3, _ge_c4 = st.columns(2)
            _ge_pwd = _ge_c3.text_input(
                "Contraseña *",
                type="password",
                placeholder="Mínimo 6 caracteres",
                help="Se encriptará con PBKDF2-SHA256 antes de guardarse."
            )
            _ge_pwd2 = _ge_c4.text_input(
                "Confirmar contraseña *",
                type="password",
                placeholder="Repite la contraseña"
            )
            _ge_c5, _ge_c6 = st.columns(2)
            _ge_pin = _ge_c5.text_input(
                "PIN de recuperación * (4 dígitos)",
                placeholder="Ej: 4821",
                max_chars=4,
                help="4 dígitos numéricos. El usuario lo usa para cambiar su contraseña si la olvida."
            )
            _ge_rol_nuevo = _ge_c6.selectbox(
                "Rol *",
                ["Operario", "Admin"],
                help="Operario: solo ve sus cotizaciones. Admin: acceso total + Gestión de Equipo."
            )

            # Resumen descriptivo del rol
            _ge_desc_rol = (
                "Acceso total al sistema, puede ver todas las cotizaciones "
                "y gestionar el equipo."
            ) if _ge_rol_nuevo == "Admin" else (
                "Solo visualiza y gestiona sus propias cotizaciones y retales. "
                "No tiene acceso a Gestión de Equipo."
            )
            st.markdown(
                f"<div style='background:var(--secondary-background-color);"
                f"border:1px solid var(--border-color);border-radius:6px;"
                f"padding:8px 12px;font-size:0.78rem;margin-top:4px'>"
                f"<strong>{_ge_rol_nuevo}:</strong> {_ge_desc_rol}</div>",
                unsafe_allow_html=True
            )

            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
            _ge_submit = st.form_submit_button(
                "✅ Registrar usuario en el sistema",
                type="primary",
                use_container_width=True
            )

        # Validación y ejecución del INSERT parametrizado
        if _ge_submit:
            _ge_errores = []
            if not _ge_nombre.strip():
                _ge_errores.append("El nombre completo es obligatorio.")
            if not _ge_user.strip():
                _ge_errores.append("El username es obligatorio.")
            elif " " in _ge_user.strip():
                _ge_errores.append("El username no puede contener espacios.")
            if len(_ge_pwd) < 6:
                _ge_errores.append("La contraseña debe tener al menos 6 caracteres.")
            elif _ge_pwd != _ge_pwd2:
                _ge_errores.append("Las contraseñas no coinciden.")
            if not _ge_pin.strip() or len(_ge_pin.strip()) != 4 or not _ge_pin.strip().isdigit():
                _ge_errores.append("El PIN debe tener exactamente 4 dígitos numéricos.")

            if _ge_errores:
                for _ge_e in _ge_errores:
                    st.error(_ge_e, icon="⚠️")
            else:
                # _crear_usuario ejecuta INSERT parametrizado y hashea la contraseña
                _ge_ok = _crear_usuario(
                    _ge_user.strip().lower(),
                    _ge_pwd,
                    _ge_pin.strip(),
                    _ge_rol_nuevo,
                    _ge_nombre.strip()
                )
                if _ge_ok:
                    st.success(
                        f"✅ Usuario **{_ge_user.strip().lower()}** registrado "
                        f"exitosamente con rol **{_ge_rol_nuevo}**.",
                        icon="👤"
                    )
                    st.balloons()
                else:
                    st.error(
                        "No se pudo registrar el usuario. "
                        "¿El username ya existe en el sistema?",
                        icon="🚨"
                    )

    # ── Tab: Listado del equipo activo ────────────────────────────────────────
    with _ge_tab_equipo:
        _ge_lista = _listar_usuarios()
        _ge_uid_yo = st.session_state.get("usuario_actual", {}).get("id")

        _ge_total_admin = sum(1 for u in _ge_lista if u[2] == "Admin")
        _ge_total_op    = sum(1 for u in _ge_lista if u[2] == "Operario")

        # Métricas rápidas
        _m1, _m2, _m3 = st.columns(3)
        _m1.metric("Total usuarios", len(_ge_lista))
        _m2.metric("Administradores", _ge_total_admin)
        _m3.metric("Operarios", _ge_total_op)

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        if not _ge_lista:
            st.info("No hay usuarios registrados aún.", icon="ℹ️")
        else:
            # Cabecera de tabla
            _gh0, _gh1, _gh2, _gh3, _gh4 = st.columns([0.4, 2.6, 1.4, 1.2, 0.8])
            for _gc, _gl in zip([_gh0, _gh1, _gh2, _gh3, _gh4],
                                 ["#", "Nombre / Username", "Rol", "ID Sistema", "Acción"]):
                _gc.markdown(
                    f"<span style='font-size:0.67rem;font-weight:700;opacity:0.4;"
                    f"text-transform:uppercase'>{_gl}</span>",
                    unsafe_allow_html=True
                )
            st.markdown("<hr style='margin:4px 0 6px'>", unsafe_allow_html=True)

            for _ge_i, _ge_u in enumerate(_ge_lista):
                _ge_uid, _ge_uname, _ge_urol, _ge_unom = _ge_u
                _ge_yo = (_ge_uid == _ge_uid_yo)
                _gc0, _gc1, _gc2, _gc3, _gc4 = st.columns([0.4, 2.6, 1.4, 1.2, 0.8])

                _gc0.markdown(
                    f"<div style='padding-top:7px;font-size:0.78rem;opacity:0.3'>{_ge_i+1}</div>",
                    unsafe_allow_html=True
                )
                _gc1.markdown(
                    f"<div style='padding-top:3px'>"
                    f"<div style='font-size:0.88rem;font-weight:700'>{_ge_unom or _ge_uname}</div>"
                    f"<div style='font-size:0.7rem;opacity:0.45;font-family:monospace'>@{_ge_uname}</div>"
                    f"</div>",
                    unsafe_allow_html=True
                )
                _gc2.markdown(
                    f"<div style='padding-top:8px'>"
                    f"<span style='background:{'#1F6F54' if _ge_urol=='Admin' else '#6b7280'};"
                    f"color:white;font-size:0.63rem;font-weight:700;padding:3px 9px;"
                    f"border-radius:4px;text-transform:uppercase'>{_ge_urol}</span>"
                    f"{'<span style="font-size:0.65rem;opacity:0.4;margin-left:6px">(tú)</span>' if _ge_yo else ''}"
                    f"</div>",
                    unsafe_allow_html=True
                )
                _gc3.markdown(
                    f"<div style='padding-top:9px;font-size:0.73rem;opacity:0.38;"
                    f"font-family:monospace'>#{_ge_uid}</div>",
                    unsafe_allow_html=True
                )
                with _gc4:
                    if _ge_yo:
                        st.markdown(
                            "<div style='padding-top:8px;font-size:0.72rem;opacity:0.3'>—</div>",
                            unsafe_allow_html=True
                        )
                    else:
                        if st.button("🗑️", key=f"ge_del_{_ge_uid}",
                                     help=f"Eliminar {_ge_uname}"):
                            _eliminar_usuario(_ge_uid)
                            st.toast(f"Usuario @{_ge_uname} eliminado del sistema.", icon="🗑️")
                            st.rerun()

                if _ge_i < len(_ge_lista) - 1:
                    st.markdown(
                        "<hr style='margin:3px 0;opacity:0.15'>",
                        unsafe_allow_html=True
                    )

        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        st.caption(
            "💡 No puedes eliminar tu propio usuario. "
            "Para transferir el rol Admin, primero registra otro usuario Admin."
        )

# ═══════════════════════════════════════════════════════════════════════════════
# PLANOS DE PRODUCCIÓN — Motor de Despiece Paramétrico
# ═══════════════════════════════════════════════════════════════════════════════

elif pagina == "Planos de Taller (IA)":
    _ui_nesting(
        fn_ia_disponible=ia_disponible,
        fn_extraer_coordenadas=extraer_coordenadas_plano,
        fn_optimizar_corte_2d=optimizar_corte_2d,
        fn_wrap_svg_streamlit=wrap_svg_streamlit,
        fn_exportar_svg_a_pdf=exportar_svg_a_pdf,
    )
