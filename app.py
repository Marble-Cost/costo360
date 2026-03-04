# app.py — CostoMármol v9 · Token Session Auth · Mar 2026
# Mármoles Collante & Castro Ltda.

import io
import time
import uuid
import hashlib
import hmac as _hmac_mod
import streamlit as st
from st_cookies_manager import CookieManager
import psycopg2
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
    CATEGORIAS_MATERIAL, ADICIONALES, ETAPAS_OBRA, VEHICULOS,
    ALOJAMIENTO, AIU_DEFAULTS, TARIFAS, LOGISTICA, VIATICOS,
    BADGE_COLORS, DESCRIPCIONES_CATEGORIA, MATERIALES_CATALOGO,
    ANCHOS_ESTANDAR, VEHICULOS_CONFIG, TOUR_PASOS,
)
from asistente_ia import chat_con_ia, ia_disponible, interpretar_proyecto, generar_resumen_cotizacion, chat_sos
import plotly.graph_objects as go

st.set_page_config(
    page_title="CostoMármol — Mármoles Collante & Castro",
    page_icon="🪨",
    layout="centered",
    initial_sidebar_state="expanded",
)

# ── GESTOR DE COOKIES HTTP (st-cookies-manager) ──────────────────────────────
# CookieManager bloquea el renderizado con st.stop() hasta que el componente
# React haya inyectado las cookies del navegador, eliminando la necesidad del
# flag cookies_ok y el rerun manual anterior.
cookies = CookieManager(prefix="ccmarmol_")
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
def _get_db_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def _init_db():
    conn = _get_db_connection()
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

# ── Persistencia de configuración en Supabase ────────────────────────────────
# Por qué: session_state se pierde en cada F5 / reinicio del servidor.
# Solución: guardar en tabla app_config (key-value) y recargar al arrancar.

def _guardar_config(clave: str, valor) -> None:
    """Serializa `valor` como JSON y lo guarda/actualiza en app_config.

    FIX-3 Serialización Base64: los bytes se deben convertir a str UTF-8
    antes de llegar aquí (ver _guardar_logo). json.dumps no serializa bytes
    nativamente y lanzaría TypeError silencioso. Se conserva `default=str`
    como red de seguridad, pero la responsabilidad primaria es del llamador.
    """
    _init_db()
    conn = _get_db_connection()
    cur  = conn.cursor()
    cur.execute(
        """INSERT INTO app_config (clave, valor, actualizado)
           VALUES (%s, %s, %s)
           ON CONFLICT (clave) DO UPDATE
           SET valor = EXCLUDED.valor, actualizado = EXCLUDED.actualizado""",
        (clave, json.dumps(valor, ensure_ascii=False, default=str), _hoy().isoformat())
    )
    conn.commit()
    cur.close()
    conn.close()

def _leer_config(clave: str, defecto=None):
    """Lee un valor de app_config. Devuelve `defecto` si la clave no existe."""
    try:
        _init_db()
        conn = _get_db_connection()
        cur  = conn.cursor()
        cur.execute("SELECT valor FROM app_config WHERE clave = %s", (clave,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return json.loads(row[0]) if row else defecto
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

def _clave_borrador_cdir() -> str:
    return f"borrador_cotizacion_directa_{_uid()}"

def _clave_borrador_aiu() -> str:
    return f"borrador_cotizacion_aiu_{_uid()}"


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
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
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
    cur.close()
    conn.close()

def _consultar_retal(categoria: str, referencia: str,
                     usuario_id: int | None = None, rol: str = "Admin") -> list:
    """
    Retorna retales disponibles para un material/referencia.
    Multi-Tenant: Operario solo ve sus propios retales; Admin ve todos.
    """
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
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
    cur.close()
    conn.close()
    # Si hay referencia específica, filtrar por ella; si no, devolver todos del material
    if referencia and referencia.strip():
        filtradas = [r for r in rows if r[1].strip().lower() == referencia.strip().lower()]
        return filtradas if filtradas else rows  # fallback: misma categoría
    return rows

def _marcar_retal_usado(retal_id: int, m2_consumidos: float):
    """Descuenta m² usados; si queda menos de 0.05 m², pasa a Usado."""
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT m2_disponibles FROM inventario_retales WHERE id = %s", (retal_id,))
    row = cur.fetchone()
    if row:
        nuevo = round(row[0] - m2_consumidos, 4)
        if nuevo <= 0.05:
            cur.execute("UPDATE inventario_retales SET m2_disponibles=0, estado='Usado' WHERE id=%s", (retal_id,))
        else:
            cur.execute("UPDATE inventario_retales SET m2_disponibles=%s WHERE id=%s", (nuevo, retal_id))
        conn.commit()
    cur.close()
    conn.close()

def _listar_retales(usuario_id=None, rol="Admin") -> list:
    """Lista el banco de retales. Operario ve solo los suyos; Admin ve todos."""
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
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
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def _actualizar_notas_retal(retal_id: int, notas: str):
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE inventario_retales SET notas=%s WHERE id=%s", (notas, retal_id))
    conn.commit()
    cur.close()
    conn.close()

def _eliminar_retal(retal_id: int):
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM inventario_retales WHERE id=%s", (retal_id,))
    conn.commit()
    cur.close()
    conn.close()

def _guardar_cotizacion(numero, cliente, resultado):
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
    _uid = st.session_state.get("usuario_actual", {}).get("id")
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
    cur.close()
    conn.close()
    st.cache_data.clear()

def _actualizar_cotizacion(cot_id: int, numero: str, cliente: str, resultado: dict):
    """Actualiza una cotización existente en la BD (modo edición)."""
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """UPDATE cotizaciones
           SET numero=%s, cliente=%s, material=%s, tipo=%s, m2=%s, ml=%s,
               costo=%s, precio=%s, margen=%s, datos_json=%s
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
            cot_id,
        ),
    )
    conn.commit()
    cur.close()
    conn.close()
    st.cache_data.clear()

@st.cache_data(ttl=60)
def _listar_cotizaciones(busqueda="", usuario_id=None, rol="Admin"):
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
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
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def _actualizar_estado(cot_id, nuevo_estado):
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE cotizaciones SET estado=%s WHERE id=%s", (nuevo_estado, cot_id))
    conn.commit()

    # ── Automatización: inyectar retal cuando se aprueba ─────────────────────
    if nuevo_estado == "Aprobada":
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
                    cur.close()
                    conn.close()
                    st.cache_data.clear()
                    _inyectar_retal(cot_id, _numero, _cliente, _material, _referencia, _retal,
                                    precio_m2_original=_precio_m2_orig)
                    return
            except Exception:
                pass

    cur.close()
    conn.close()
    st.cache_data.clear()

def _eliminar_cotizacion(cot_id):
    """Elimina la cotizacion y sus sobrantes asociados del inventario."""
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
    # Primero eliminar los sobrantes que provienen de esta cotizacion
    cur.execute(
        "DELETE FROM inventario_retales WHERE origen_cotizacion_id = %s",
        (cot_id,)
    )
    # Luego eliminar la cotizacion
    cur.execute("DELETE FROM cotizaciones WHERE id=%s", (cot_id,))
    conn.commit()
    cur.close()
    conn.close()
    st.cache_data.clear()

@st.cache_data(ttl=60)
def _stats_db(usuario_id=None, rol="Admin"):
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
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
    cur.close()
    conn.close()
    return s


def _stats_retales(usuario_id=None, rol="Admin") -> dict:
    """Calcula el capital inmovilizado y métricas del banco de retales."""
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
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
    cur.close()
    conn.close()
    return {
        "total_piezas":  int(row[0] or 0),
        "m2_total":      float(row[1] or 0),
        "valor_total":   float(row[2] or 0),
        "por_categoria": por_categoria,
    }

def _chat_parametros(historial: list, mensaje: str) -> str:
    try:
        import anthropic
        api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
        if not api_key: return "Configura tu API key en .streamlit/secrets.toml"
        client = anthropic.Anthropic(api_key=api_key)
        SYSTEM_PARAMS = """Eres el asesor de costos operativos de MARMOLES COLLANTE & CASTRO LTDA., Barranquilla, Colombia.
Tu función es ayudar a actualizar los parámetros internos de la empresa: tarifas de producción, viáticos, logística.

CONTEXTO DEL MERCADO (Feb 2026, Barranquilla):
- Gasolina corriente: ~$16.000/galón
- Mano de obra mármol: $55.000–$70.000/ml | Granito: $50.000–$60.000/ml | Sinterizado: $80.000–$95.000/ml
- Hospedaje pueblo: $55.000–$70.000/noche | Ciudad: $80.000–$100.000/noche
- Alimentación diaria: $60.000–$75.000/persona

REGLAS:
- Responde en español colombiano directo, máximo 3 oraciones.
- Si el usuario menciona un precio nuevo, confírmalo antes de aplicar y pregunta si desea actualizar.
- Si el usuario confirma el cambio (dice "sí", "aplica", "actualiza", "correcto", etc.), 
  incluye AL FINAL un bloque ```json con los valores a actualizar.
- Para TARIFAS: usa estructura {Material: {prod_ml, zocalo, disco, maquina, consumibles, riesgo_rotura}}
- Para VIATICOS: usa estructura {pueblo: {hospedaje, alimentacion, transporte_local}, ciudad: {...}}
- Nunca incluyas el JSON si el usuario no ha confirmado el cambio.
- No uses emojis.
- Sé directo: da números concretos basados en el mercado de Barranquilla."""
        messages = [{"role": m["role"], "content": m["content"]} for m in historial]
        messages.append({"role": "user", "content": mensaje})
        response = client.messages.create(model="claude-sonnet-4-6", max_tokens=600, system=SYSTEM_PARAMS, messages=messages)
        return response.content[0].text
    except Exception as e:
        return f"Error: {str(e)}"


# SISTEMA DE AUTENTICACIÓN — Token UUID4 + PostgreSQL + PBKDF2-SHA256
# =============================================================================
#
# F5 / cierre de pestaña / reinicio del servidor NO cierran la sesión.
# El token UUID4 persiste en PostgreSQL con expiración de 30 días.
# La cookie es solo transporte — la fuente de verdad es la tabla `sesiones`.


def _hash_password(password: str) -> str:
    """Hashing PBKDF2-SHA256 con 200.000 iteraciones. Sin dependencias externas."""
    salt = b"cc_marmoles_2026_salt"
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return dk.hex()


def _verificar_password(password: str, hash_almacenado: str) -> bool:
    """Comparación segura contra timing-attacks via hmac.compare_digest."""
    return _hmac_mod.compare_digest(_hash_password(password), hash_almacenado)


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
        _init_db()
        conn = _get_db_connection()
        cur  = conn.cursor()
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
        cur.close(); conn.close()
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
        _init_db()
        conn = _get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            "SELECT usuario_id, expires_at FROM sesiones "
            "WHERE token = %s AND expires_at > NOW()",
            (token,)
        )
        row = cur.fetchone()
        if not row:
            cur.close(); conn.close()
            return None
        usuario_id, expires_at = row[0], row[1]
        # Renovación automática: si quedan <7 días extender a 30
        if expires_at and (expires_at - datetime.now()).days < 7:
            nueva_exp = datetime.now() + timedelta(days=30)
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
        cur.close(); conn.close()
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
            conn = _get_db_connection()
            cur  = conn.cursor()
            cur.execute("DELETE FROM sesiones WHERE token = %s", (token,))
            conn.commit()
            cur.close(); conn.close()
        except Exception:
            pass
    try:
        del cookies[_COOKIE_TOKEN]
        cookies.save()
    except Exception:
        pass
    for k in ["usuario_actual", "_session_token", "_config_cargada",
              "cotizacion", "pre", "piezas", "materiales_proyecto",
              "chat", "resumen_ia",
              "_cotiz_guardada", "_cotiz_guardada_num",
              "_aiu_guardada", "_aiu_guardada_num",
              # ── store_permanente: limpiar completamente al cerrar sesión ──
              "store_permanente", "_sp_borrador_hash", "_sp_aiu_hash",
              "_borrador_restaurado"]:
        st.session_state.pop(k, None)




def _buscar_usuario_por_id(usuario_id: int) -> dict | None:
    """Busca usuario por ID numérico. Usado por auth wall tras validar token."""
    try:
        _init_db()
        conn = _get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            "SELECT id, username, password_hash, pin_recuperacion, rol, nombre_completo "
            "FROM usuarios WHERE id = %s",
            (usuario_id,)
        )
        row = cur.fetchone()
        cur.close(); conn.close()
        if row:
            return {"id": row[0], "username": row[1], "password_hash": row[2],
                    "pin_recuperacion": row[3], "rol": row[4], "nombre_completo": row[5]}
        return None
    except Exception:
        return None


def _buscar_usuario_por_username(username: str) -> dict | None:
    try:
        _init_db()
        conn = _get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            "SELECT id, username, password_hash, pin_recuperacion, rol, nombre_completo "
            "FROM usuarios WHERE username = %s",

            (username.strip().lower(),)
        )
        row = cur.fetchone()
        cur.close(); conn.close()
        if row:
            return {"id": row[0], "username": row[1], "password_hash": row[2],
                    "pin_recuperacion": row[3], "rol": row[4], "nombre_completo": row[5]}
        return None
    except Exception:
        return None

def _crear_usuario(username: str, password: str, pin: str,
                   rol: str = "Operario", nombre_completo: str = "") -> bool:
    try:
        _init_db()
        conn = _get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            "INSERT INTO usuarios (username, password_hash, pin_recuperacion, rol, nombre_completo) "
            "VALUES (%s, %s, %s, %s, %s)",
            (username.strip().lower(), _hash_password(password), pin.strip(), rol, nombre_completo)
        )
        conn.commit()
        cur.close(); conn.close()
        return True
    except Exception:
        return False

def _actualizar_password(username: str, nueva_password: str) -> bool:
    try:
        _init_db()
        conn = _get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            "UPDATE usuarios SET password_hash = %s WHERE username = %s",
            (_hash_password(nueva_password), username.strip().lower())
        )
        conn.commit()
        cur.close(); conn.close()
        return True
    except Exception:
        return False

def _listar_usuarios() -> list:
    try:
        _init_db()
        conn = _get_db_connection()
        cur  = conn.cursor()
        cur.execute("SELECT id, username, rol, nombre_completo FROM usuarios ORDER BY id")
        rows = cur.fetchall()
        cur.close(); conn.close()
        return rows
    except Exception:
        return []

def _eliminar_usuario(uid: int) -> bool:
    try:
        _init_db()
        conn = _get_db_connection()
        cur  = conn.cursor()
        cur.execute("DELETE FROM usuarios WHERE id = %s", (uid,))
        conn.commit()
        cur.close(); conn.close()
        return True
    except Exception:
        return False

def _asegurar_admin_existe():
    """Crea el usuario admin por defecto si la tabla está vacía.
    Credenciales: admin / admin123 / PIN: 0000  — cambiar tras el primer login."""
    try:
        _init_db()
        conn = _get_db_connection()
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM usuarios")
        if cur.fetchone()[0] == 0:
            cur.close(); conn.close()
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
        color: #1B5FA8; margin-bottom: 4px; text-align: center;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── Logo centrado ─────────────────────────────────────────────────────────
    _login_base_dir = os.path.dirname(os.path.abspath(__file__))
    _login_logo = next(
        (os.path.join(_login_base_dir, n) for n in
         ["logo_cc.jpeg", "logo_cc.jpg", "logo_cc.png",
          "Logo_cc.jpeg", "Logo_cc.jpg", "Logo_cc.png"]
         if os.path.exists(os.path.join(_login_base_dir, n))),
        None
    )
    _col1, _col2, _col3 = st.columns([1.2, 1, 1.2])
    with _col2:
        if st.session_state.get("logo_bytes"):
            st.image(st.session_state.logo_bytes, use_container_width=True)
        elif _login_logo:
            st.image(_login_logo, use_container_width=True)
        else:
            st.markdown(
                '<div style="text-align:center;padding:10px 0 6px">'
                '<span style="color:#C9A84C;font-size:2.4rem;font-weight:900;'
                'font-family:serif;line-height:1">CC</span></div>',
                unsafe_allow_html=True
            )

    st.markdown(
        '<div class="login-title" style="margin-top:4px;margin-bottom:8px">Iniciar Sesión</div>',
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
                font-size:0.75rem'>Marmoles Collante &amp; Castro</span>
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



# ── CSS NATIVO (ADAPTABLE A MODO CLARO/OSCURO) ────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=DM+Sans:wght@300;400;500;600;700&display=swap');

* { box-sizing: border-box; }
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

/* ── BUTTONS ── */
.stButton > button {
    border-radius: 6px !important; font-weight: 600 !important; font-size: 0.85rem !important;
    transition: all 0.18s ease !important; padding: 0.45rem 1rem !important;
}
.stButton > button[kind="primary"] {
    background: #1B5FA8 !important; color: white !important; border: none !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15) !important; text-transform: uppercase !important;
}
.stButton > button[kind="primary"]:hover { filter: brightness(1.1); transform: translateY(-2px) !important; }

/* ── CARDS (Usa las variables de color del tema del celular/PC) ── */
.card-custom {
    background: var(--secondary-background-color);
    border: 1px solid var(--border-color); 
    border-radius: 10px; padding: 16px 18px; margin-bottom: 12px;
}
</style>
""", unsafe_allow_html=True)

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
            <span style="font-size:0.95rem;font-weight:800">{total_label}</span><span style="font-size:0.95rem;font-weight:800;color:#1B5FA8">{cop(total_val)}</span></div>"""
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
        "nombre": "MÁRMOLES COLLANTE & CASTRO LTDA.", "nit": "NIT: 900.111.561-1",
        "tel": "+57 300 000 0000", "email": "ventas@marmolescc.com",
        "ciudad": "Barranquilla, Atlántico — Colombia", "banco": "Davivienda",
        "cuenta_tipo": "Cuenta Corriente Empresas", "cuenta_numero": "108900027484",
    },
    "vehiculos_custom": None, "cat_sel": "Mármol",
    "adicionales_custom": None,
    "chat_input_key": 0,
    "params_wizard_chat": [],
    "params_cambios_aplicados": [],
    # Wizard navigation state
    "cdir_paso": 0,
    "cdir_success": False,
    "aiu_paso": 0,
    "aiu_success": False,
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Cargar configuración persistente desde Supabase ──────────────────────────
# Se ejecuta UNA VEZ por sesión (marcador _config_cargada).
# Sobreescribe tarifas_custom, logistica_custom, viaticos_custom,
# adicionales_custom y empresa_info con los valores guardados en la BD,
# de modo que sobreviven a F5 y reinicios del servidor.
try:
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
        "cdir_vehiculo": "frontier",
        "cdir_km": 5.0,
        "cdir_peajes": 0,
        "cdir_foraneo": False,
        "cdir_viaticos_activos": False,
        "cdir_tipo_aloj": "pueblo",
        "cdir_noches": 0,
        "cdir_adicionales_activos": False,
        "cdir_cantidades_add": [],
        "cdir_incluir_iva": True,
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
        sp["cdir_vehiculo"]            = _pre.get("vehiculo_entrega", sp["cdir_vehiculo"])
        sp["cdir_km"]                  = _pre.get("km", sp["cdir_km"])
        sp["cdir_peajes"]              = _pre.get("peajes", sp["cdir_peajes"])
        sp["cdir_foraneo"]             = _pre.get("foraneo_activo", sp["cdir_foraneo"])
        sp["cdir_viaticos_activos"]    = _pre.get("viaticos_activos", sp["cdir_viaticos_activos"])
        sp["cdir_tipo_aloj"]           = _pre.get("tipo_aloj", sp["cdir_tipo_aloj"])
        sp["cdir_noches"]              = _pre.get("noches", sp["cdir_noches"])
        sp["cdir_adicionales_activos"] = _pre.get("adicionales_activos", sp["cdir_adicionales_activos"])
        sp["cdir_cantidades_add"]      = _pre.get("cantidades_add", sp["cdir_cantidades_add"])
        sp["cdir_incluir_iva"]         = _pre.get("incluir_iva", sp["cdir_incluir_iva"])

    # ── Precargar tarifas/logística/viáticos desde sesión ────────────────────
    if st.session_state.get("tarifas_custom"):
        sp["params_tarifas"]   = st.session_state.tarifas_custom
    if st.session_state.get("logistica_custom"):
        sp["params_logistica"] = st.session_state.logistica_custom
    if st.session_state.get("viaticos_custom"):
        sp["params_viaticos"]  = st.session_state.viaticos_custom
    if st.session_state.get("adicionales_custom"):
        sp["params_adicionales"] = st.session_state.adicionales_custom

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
        "vehiculo_entrega":    sp.get("cdir_vehiculo", "frontier"),
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


# ── Helpers para listas dinámicas con persistencia atómica ───────────────────

def _sp_agregar_pieza():
    """Añade una pieza nueva y persiste en BD de inmediato."""
    piezas = list(_sp().get("cdir_piezas", []))
    piezas.append({"nombre": f"Pieza {len(piezas)+1}",
                   "ml": 1.0, "ml_unitario": 1.0, "cantidad": 1,
                   "ancho_tipo": "Mesón de cocina", "ancho_custom": 0.60})
    _sp_set("cdir_piezas", piezas)
    st.session_state.piezas = piezas
    _sp_commit_borrador()

def _sp_eliminar_pieza(idx: int):
    """Elimina una pieza y persiste en BD de inmediato."""
    piezas = list(_sp().get("cdir_piezas", []))
    if len(piezas) > 1 and 0 <= idx < len(piezas):
        piezas.pop(idx)
        _sp_set("cdir_piezas", piezas)
        st.session_state.piezas = piezas
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
# 4. Token inválido/expirado →  _limpiar_sesion() + pantalla login
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
                _limpiar_sesion()
                _pantalla_login()
                st.stop()
        else:
            # Token expirado o inválido
            _limpiar_sesion()
            _pantalla_login()
            st.stop()
else:
    # ── Sin token → primera visita o sesión expirada ───────────────────
    _pantalla_login()
    st.stop()
def get_tarifas(): return st.session_state.tarifas_custom or TARIFAS
def get_logistica(): return st.session_state.logistica_custom or LOGISTICA
def get_viaticos(): return st.session_state.viaticos_custom or VIATICOS
def get_adicionales():
    import copy
    return copy.deepcopy(st.session_state.adicionales_custom) if st.session_state.adicionales_custom else copy.deepcopy(ADICIONALES)
def get_vehiculos_config():
    import copy
    base = copy.deepcopy(VEHICULOS_CONFIG)
    custom = st.session_state.get("vehiculos_custom") or {}
    for k, v in custom.items(): base[k] = v
    return base
def get_vehiculos_dict():
    vc = get_vehiculos_config()
    return {f"{cfg.get('nombre', k)} ({'propio' if cfg.get('tipo')=='propio' else 'flete externo'})": k for k, cfg in vc.items()}

# ── SIDEBAR NAV ───────────────────────────────────────────────────────────────
with st.sidebar:
    # ── Logo corporativo — busca entre extensiones posibles automáticamente ───
    _base_dir  = os.path.dirname(os.path.abspath(__file__))
    _logo_path = next(
        (os.path.join(_base_dir, n) for n in
         ["logo_cc.jpeg", "logo_cc.jpg", "logo_cc.png",
          "Logo_cc.jpeg", "Logo_cc.jpg", "Logo_cc.png"]
         if os.path.exists(os.path.join(_base_dir, n))),
        None
    )
    # 1. Prioridad a la imagen subida en Configuración (Memoria)
    if st.session_state.get("logo_bytes"):
        st.image(st.session_state.logo_bytes, use_container_width=True)
    # 2. Si no hay en memoria, busca en el disco duro
    elif _logo_path:
        st.image(_logo_path, use_container_width=True)
    # 3. Fallback (Texto)
    else:
        st.markdown(
            '<div style="text-align:center;padding:14px 0 8px">'
            '<span style="color:#C9A84C;font-size:2rem;font-weight:900;'
            'font-family:Playfair Display,serif">CC</span><br>'
            '<span style="font-size:0.72rem;font-weight:700;opacity:0.8">'
            'MARMOLES COLLANTE &amp; CASTRO</span>'
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
    _paginas_validas = ["Inicio", "Cotizacion Directa", "Cotizacion AIU",
                        "Historial", "Dashboard", "Banco de Retales",
                        "Parametros", "Asistente IA", "Configuracion", "Gestion de Equipo"]
    if st.session_state.get("nav_radio") not in _paginas_validas:
        st.session_state.nav_radio = "Inicio"
        st.session_state.radio_ui = "Inicio"

    # Menú dinámico: "Gestión de Equipo" solo visible para rol Admin
    _rol_nav = st.session_state.get("usuario_actual", {}).get("rol", "Operario")
    opciones_menu = ["Inicio", "Cotizacion Directa", "Cotizacion AIU", "Historial", "Dashboard",
                     "Banco de Retales", "Parametros", "Asistente IA", "Configuracion"]
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
    _badge_rol = ("#1B5FA8", "Admin") if _rol_ses == "Admin" else ("#6b7280", "Operario")
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
            "color:#1B5FA8'>Asistente contextual</div>"
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
                    _resp_rapida = chat_sos(_q, _sos_ctx, _sos_form_ctx)
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
                    _sos_resp = chat_sos(_sos_pregunta.strip(), _sos_ctx, _sos_form_ctx)
                st.session_state["_sos_ultima_respuesta"] = _sos_resp
                st.session_state["_sos_ultima_pregunta"]  = _sos_pregunta.strip()
            else:
                st.warning("Escribe tu duda primero.", icon="⚠️")

        # ── Respuesta de la IA (fondo azul suave) ─────────────────────────────
        if st.session_state.get("_sos_ultima_respuesta"):
            st.markdown(
                f"<div style='background:rgba(27,95,168,0.08);border:1px solid rgba(27,95,168,0.25);"
                f"border-left:3px solid #1B5FA8;border-radius:8px;"
                f"padding:10px 12px;margin-top:8px;font-size:0.8rem;line-height:1.6'>"
                f"<div style='font-size:0.65rem;font-weight:700;color:#1B5FA8;"
                f"text-transform:uppercase;margin-bottom:6px'>✨ Copiloto responde</div>"
                f"{st.session_state['_sos_ultima_respuesta'].replace(chr(10), '<br>')}"
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
                f"color:#C9A84C;text-transform:uppercase;border-bottom:2px solid #C9A84C;"
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
                f"color:#C9A84C;text-transform:uppercase'>{_etiqueta}</span>"
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
                f"color:#1B5FA8;font-size:1.35rem;line-height:1.2'>"
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
                    f"color:#1B5FA8;font-size:1.25rem;line-height:1.2'>"
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

    # Limpiar claves residuales del formulario anterior para evitar contaminación
    _CLAVES_FORMULARIO = [
        "piezas", "materiales_proyecto", "aiu_items",
        "zocalo_activo", "adicionales_activos", "foraneo_activo",
        "viaticos_activos", "resultado_calculo", "resumen_ia",
        "pre", "editando_id", "cotizacion",
    ]
    for _k in _CLAVES_FORMULARIO:
        st.session_state.pop(_k, None)

    # Marcar modo edición con ID y número del registro
    st.session_state.editando_id  = rid
    st.session_state.editando_num = rnum
    eg["_origen"] = "historial"   # Para mostrar alerta de carga en el formulario
    st.session_state.pre          = eg

    if "AIU" in rnum or datos.get("tipo_proyecto") == "Licitación AIU" \
            or eg.get("tipo_proyecto") == "Licitación AIU":
        st.session_state.aiu_items = eg.get("aiu_items", [])
        destino = "Cotizacion AIU"
    else:
        destino = "Cotizacion Directa"

    # Resetear punteros del wizard para que el usuario empiece desde Paso 0
    # al cargar una cotización del historial — evita UX confusa en pasos intermedios.
    st.session_state.cdir_paso   = 0
    st.session_state.aiu_paso    = 0
    st.session_state.cdir_success = False

    # Actualizar navegación — la sincronización al inicio del rerun (línea ~49)
    # garantiza que radio_ui quede alineado con nav_radio y el menú se vea correcto.
    st.session_state.nav_radio = destino
    st.query_params["pagina"]  = destino
    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# INICIO
# ═══════════════════════════════════════════════════════════════════════════════
if pagina == "Inicio":
    st.markdown(f"""
    <div style="background:var(--secondary-background-color); border-radius:16px;padding:40px 44px;margin-bottom:28px; border:2px solid #1B5FA8;">
      <div style="color:#C9A84C;font-size:0.68rem;text-transform:uppercase;letter-spacing:0.15em;font-weight:800;margin-bottom:12px">
        Mármoles Collante &amp; Castro Ltda.
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

elif pagina == "Cotizacion Directa":

    # ══════════════════════════════════════════════════════════════════
    # EVENT-DRIVEN STATE SYNC: store_permanente → pre (on page entry)
    # ══════════════════════════════════════════════════════════════════
    # Garantiza que al navegar de vuelta a Cotización Directa, el estado
    # del wizard refleje exactamente lo que hay en el store_permanente,
    # que SOBREVIVIÓ el desmontaje de widgets al cambiar de página.
    _sp_entry = _sp()
    if _sp_entry.get("cdir_piezas") or _sp_entry.get("cdir_materiales"):
        # Solo sincronizar si el store tiene datos (evitar sobreescribir borrador pre-cargado)
        _pre_from_store = {
            "materiales_proyecto": _sp_entry.get("cdir_materiales", []),
            "piezas":              _sp_entry.get("cdir_piezas", []),
            "margen_pct":          _sp_entry.get("cdir_margen_pct", 40),
            "m2_usados":           _sp_entry.get("cdir_m2_usados", 0.0),
            "tipo_proyecto":       _sp_entry.get("cdir_tipo_proyecto", "Mesón"),
            "tipos_proyecto":      _sp_entry.get("cdir_tipos_proyecto", ["Mesón"]),
            "etapa_label":         _sp_entry.get("cdir_etapa_label", "Casa terminada (limpia)"),
            "nombre_cliente":      _sp_entry.get("cdir_nombre_cliente", ""),
            "dias_obra":           _sp_entry.get("cdir_dias_obra", 2),
            "personas":            _sp_entry.get("cdir_personas", 2),
            "zocalo_activo":       _sp_entry.get("cdir_zocalo_activo", False),
            "zocalo_ml":           _sp_entry.get("cdir_zocalo_ml", 0.0),
            "agente_externo_taller": _sp_entry.get("cdir_agente_externo", False),
            "vehiculo_entrega":    _sp_entry.get("cdir_vehiculo", "frontier"),
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
        # Merge: solo sobreescribir pre si el store tiene datos más recientes
        _pre_existing = st.session_state.get("pre", {})
        if not _pre_existing or _pre_existing.get("_origen") == "borrador":
            st.session_state.pre = _pre_from_store
            if _pre_from_store["piezas"]:
                st.session_state.piezas = _pre_from_store["piezas"]
            if _pre_from_store["materiales_proyecto"]:
                st.session_state.materiales_proyecto = _pre_from_store["materiales_proyecto"]
        # Sync wizard paso from store
        if "cdir_paso" not in st.session_state or st.session_state.get("cdir_paso") != _sp_entry.get("cdir_paso", 0):
            st.session_state.cdir_paso = _sp_entry.get("cdir_paso", 0)

    # ══════════════════════════════════════════════════════════════════
    # WIZARD COTIZACIÓN DIRECTA — 5 pasos, un bloque visible a la vez
    # ══════════════════════════════════════════════════════════════════
    # Estado del wizard: cdir_paso (0-4). Nunca se borra con limpiar
    # formulario — solo se resetea cuando el usuario pide empezar de cero.
    #
    # PASOS:
    #   0 — Material(es)       → qué piedra, qué precio, qué área comprada
    #   1 — Dimensiones        → piezas ML × ancho, margen, m² usados
    #   2 — Proyecto           → tipo, etapa, días, personas, zócalos, desperdicio
    #   3 — Logística / Extras → vehículo, km, foráneo, adicionales, IVA
    #   4 — Resultado          → pantalla de éxito / success screen
    # ══════════════════════════════════════════════════════════════════

    WIZARD_PASOS = [
        {"icono": "🪨", "label": "Material"},
        {"icono": "📐", "label": "Dimensiones"},
        {"icono": "🏗️", "label": "Proyecto"},
        {"icono": "🚛", "label": "Logística"},
        {"icono": "✅", "label": "Resultado"},
    ]
    N_PASOS = len(WIZARD_PASOS)

    # Inicializar estado wizard
    if "cdir_paso" not in st.session_state:
        st.session_state.cdir_paso = 0
    if "cdir_success" not in st.session_state:
        st.session_state.cdir_success = False   # True = pantalla de éxito

    pre = st.session_state.pre

    # ── Restaurar borrador desde BD (una sola vez post-F5) ──────────────
    # FIX-1 Multi-Tenant: se usa _clave_borrador_cdir() que incorpora el
    # ID del usuario activo — cada usuario ve solo su propio borrador.
    if not pre and not st.session_state.get("_borrador_restaurado"):
        try:
            _borrador = _leer_config(_clave_borrador_cdir())
            if _borrador:
                _borrador["_origen"] = "borrador"
                st.session_state.pre = _borrador
                pre = _borrador
                # ── FIX-2 Hidratación forzada: reconstruir todas las listas dinámicas ──
                # Sin esto, las piezas, adicionales y retal seleccionado se pierden en F5.
                if "piezas" in _borrador and _borrador["piezas"]:
                    st.session_state.piezas = _borrador["piezas"]
                if "materiales_proyecto" in _borrador and _borrador["materiales_proyecto"]:
                    st.session_state.materiales_proyecto = _borrador["materiales_proyecto"]
                if "cantidades_add" in _borrador:
                    # cantidades_add es lista plana — la usamos para pre-cargar el form
                    st.session_state["_cantidades_add_restauradas"] = _borrador["cantidades_add"]
                # Restaurar paso del wizard para que el usuario continúe donde lo dejó
                if "cdir_paso" in _borrador and isinstance(_borrador["cdir_paso"], int):
                    st.session_state.cdir_paso = _borrador["cdir_paso"]
                # Restaurar retal_id por material (guardados como retal_id_0, retal_id_1...)
                for _rk, _rv in _borrador.items():
                    if _rk.startswith("retal_id_") and _rv:
                        st.session_state[_rk] = _rv
        except Exception:
            pass
        st.session_state["_borrador_restaurado"] = True

    if pre and pre.get("_origen") in ("historial", "ia"):
        alerta("Datos cargados desde Historial o IA. Revisa y ajusta lo que necesites.", "bueno")
        st.session_state.pre.pop("_origen", None)
    elif pre and pre.get("_origen") == "borrador":
        alerta("📋 Se restauró tu último cálculo. Puedes continuar donde lo dejaste.", "info")
        st.session_state.pre.pop("_origen", None)

    # ── ATAJO DE EDICIÓN ── visible SIEMPRE que haya un editando_id activo ────
    # Evita obligar al usuario a navegar los 5 pasos del wizard para guardar
    # un cambio menor. Si ya hay cotizacion calculada, guarda de inmediato.
    if st.session_state.get("editando_id"):
        _eid   = st.session_state["editando_id"]
        _enum  = st.session_state.get("editando_num", "")
        st.markdown(
            f'<div style="background:rgba(201,168,76,0.10);border:1px solid rgba(201,168,76,0.45);'
            f'border-left:4px solid #C9A84C;border-radius:10px;'
            f'padding:14px 18px;margin-bottom:20px">'
            f'<div style="font-size:0.70rem;font-weight:800;color:#C9A84C;'
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
                _r_atajo      = st.session_state.get("cotizacion")

                # ── State Fallback: recalcular desde pre si no hay resultado cacheado ──
                # Garantiza que viáticos, logística y adicionales se preserven
                # aunque el usuario no haya navegado todos los pasos del wizard.
                if not _r_atajo:
                    _pre_sb = st.session_state.pre
                    _mats_sb = _pre_sb.get("materiales_proyecto", [])
                    if _mats_sb:
                        _m0 = _mats_sb[0]
                        _cat_sb   = _m0.get("cat", "Mármol")
                        _ref_sb   = _m0.get("ref", "")
                        _pm2_sb   = float(_m0.get("precio_m2", 0))
                        _area_sb  = float(_m0.get("area_placa", 1.0))
                    else:
                        _cat_sb   = _pre_sb.get("categoria", "Mármol")
                        _ref_sb   = _pre_sb.get("referencia", "")
                        _pm2_sb   = float(_pre_sb.get("precio_m2", 0))
                        _area_sb  = float(_pre_sb.get("area_placa", 1.0))
                    _add_sb = get_adicionales()
                    _cant_add_sb = _pre_sb.get("cantidades_add", [0]*len(_add_sb))
                    while len(_cant_add_sb) < len(_add_sb):
                        _cant_add_sb.append(0)
                    _etapa_sb = ETAPAS_OBRA.get(
                        _pre_sb.get("etapa_label", "Casa terminada (limpia)"), "terminada"
                    )
                    try:
                        _r_atajo = calcular_cotizacion_directa(
                            categoria=_cat_sb,
                            referencia=_ref_sb,
                            precio_m2=_pm2_sb,
                            area_placa_comprada=_area_sb,
                            m2_real=float(_pre_sb.get("m2_proyecto", _area_sb)),
                            m2_cortados=float(_pre_sb.get("m2_cortados_input", 0)),
                            m2_usados=float(_pre_sb.get("m2_usados", _area_sb)),
                            margen_pct=float(_pre_sb.get("margen_pct", 40)),
                            dias=int(_pre_sb.get("dias_obra", 1)),
                            personas=int(_pre_sb.get("personas", 2)),
                            zocalo_activo=bool(_pre_sb.get("zocalo_activo", False)),
                            zocalo_ml=float(_pre_sb.get("zocalo_ml", 0)),
                            agente_externo_taller=bool(_pre_sb.get("agente_externo_taller", False)),
                            vehiculo_entrega=_pre_sb.get("vehiculo_entrega", "frontier"),
                            km=float(_pre_sb.get("km", 10)),
                            num_peajes=int(_pre_sb.get("peajes", 0)),
                            foraneo_activo=bool(_pre_sb.get("foraneo_activo", False)),
                            viaticos_activos=bool(_pre_sb.get("viaticos_activos", True)),
                            tipo_aloj=_pre_sb.get("tipo_aloj", "pueblo"),
                            noches=int(_pre_sb.get("noches", 0)),
                            adicionales_activos=bool(_pre_sb.get("adicionales_activos", False)),
                            cantidades_add=_cant_add_sb,
                            etapa=_etapa_sb,
                            adicionales_lista=_add_sb,
                            tipo_proyecto=_pre_sb.get("tipo_proyecto", ""),
                            nombre_cliente=_nombre_atajo,
                            piezas=_pre_sb.get("piezas", []),
                            ml_proyecto=float(_pre_sb.get("ml_proyecto", 0)),
                            logistica_override=st.session_state.get("logistica_custom"),
                            vehiculos_custom={**VEHICULOS_CONFIG,
                                              **(st.session_state.get("vehiculos_custom") or {})},
                            tarifas_override=st.session_state.get("tarifas_custom"),
                        )
                        _r_atajo["_estado_guardado"] = _pre_sb
                        _r_atajo["incluir_iva"]      = _pre_sb.get("incluir_iva", False)
                        st.session_state.cotizacion  = _r_atajo
                    except Exception as _e_sb:
                        st.warning(
                            f"No se pudo recalcular automáticamente: {_e_sb}. "
                            "Navega al **Paso 4 (Logística)** y presiona **Calcular** primero.",
                            icon="⚠️",
                        )
                        _r_atajo = None

                if _r_atajo:
                    _actualizar_cotizacion(_eid, _enum, _nombre_atajo, _r_atajo)
                    st.session_state.pop("editando_id",  None)
                    st.session_state.pop("editando_num", None)
                    st.session_state["_cotiz_guardada_num"] = _enum
                    st.session_state["cdir_success"] = True
                    st.success(f"✅ Cotización **{_enum}** actualizada correctamente.", icon="💾")
                    st.rerun()
        with _eat_c2:
            if st.button(
                "✕ Cancelar edición",
                use_container_width=True,
                key="btn_cancelar_atajo_edicion",
            ):
                st.session_state.pop("editando_id",  None)
                st.session_state.pop("editando_num", None)
                st.session_state.cdir_paso = 0
                st.rerun()
        st.markdown("<hr style='margin:4px 0 20px'>", unsafe_allow_html=True)

    TARIFAS_ACT = get_tarifas()
    LOG_ACT     = get_logistica()
    VIA_ACT     = get_viaticos()

    # ════════════════════════════════════════════════════════════════════
    # PANTALLA DE ÉXITO — se muestra cuando cdir_success == True
    # ════════════════════════════════════════════════════════════════════
    if st.session_state.get("cdir_success") and st.session_state.cotizacion:
        r         = st.session_state.cotizacion
        _num_g    = st.session_state.get("_cotiz_guardada_num", "")
        _iva_act  = r.get("incluir_iva", False)
        _iva_monto   = r["precio_sugerido"] * 0.19 if _iva_act else 0.0
        _precio_final = r["precio_sugerido"] + _iva_monto

        # ── Header de éxito ──────────────────────────────────────────
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#0D2137 0%,#1B5FA8 100%);
                    border-radius:18px;padding:40px 44px 32px;margin-bottom:24px;color:white;
                    box-shadow:0 8px 32px rgba(27,95,168,0.35)">
          <div style="display:flex;align-items:center;gap:16px;margin-bottom:20px">
            <div style="width:52px;height:52px;background:rgba(201,168,76,0.25);border-radius:50%;
                        display:flex;align-items:center;justify-content:center;font-size:1.6rem">✅</div>
            <div>
              <div style="font-size:0.7rem;letter-spacing:0.14em;text-transform:uppercase;
                          color:#C9A84C;font-weight:700;margin-bottom:2px">COTIZACIÓN FINALIZADA</div>
              <div style="font-size:1.1rem;font-weight:700">{r.get("nombre_cliente","") or "Sin nombre de cliente"}</div>
            </div>
          </div>
          <div style="font-size:0.72rem;text-transform:uppercase;letter-spacing:0.12em;
                      color:rgba(255,255,255,0.55);font-weight:700;margin-bottom:6px">
            {"Precio de venta (sin IVA)" if _iva_act else "Precio de venta"}
          </div>
          <div style="font-size:3.8rem;font-weight:900;font-family:'Playfair Display',serif;
                      line-height:1;margin-bottom:8px">{numero_completo(r["precio_sugerido"])}</div>
          <div style="opacity:0.75;font-size:0.9rem">
            Margen: {r["margen_pct"]:.0f}% &nbsp;·&nbsp; Utilidad: {numero_completo(r["utilidad"])}
            &nbsp;·&nbsp; {r.get("tipo_proyecto","Proyecto")} — {r.get("categoria","")}
          </div>
          {f'<div style="margin-top:14px;padding-top:14px;border-top:1px solid rgba(255,255,255,0.2);font-size:1.05rem;font-weight:700;color:#C9A84C">+ IVA 19%: {numero_completo(_iva_monto)} &nbsp;→&nbsp; <span style="color:white">Total: {numero_completo(_precio_final)}</span></div>' if _iva_act else ""}
        </div>""", unsafe_allow_html=True)

        # ── Desglose compacto ────────────────────────────────────────
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
            bloque_costos(_items, "TOTAL CON IVA" if _iva_act else "PRECIO TOTAL", _precio_final)

            c1s, c2s = st.columns(2)
            c1s.metric("Aprovechamiento lámina", f"{r['aprovechamiento']:.1f}%", f"Retal: {fmt_m2(r['retal'])}")
            c2s.metric("Costo/m² instalado", numero_completo(r["costo_total"] / max(r["m2_real"], 0.001)))

        # ── Simulador de margen ──────────────────────────────────────
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
                  <span style="font-size:1.15rem;font-weight:900;color:#1B5FA8">{numero_completo(_sim_p)}</span>
                </div>
                {"" if not _iva_act else f'<div style="display:flex;justify-content:space-between;align-items:center;border-top:1px solid var(--border-color);padding-top:6px;margin-bottom:4px"><span style="font-size:0.75rem;font-weight:700;opacity:0.55;text-transform:uppercase">Con IVA 19%</span><span style="font-size:1.15rem;font-weight:900;color:#C9A84C">{numero_completo(_sim_p + _sim_iva)}</span></div>'}
                <div style="font-size:0.72rem;opacity:0.5">Utilidad: {numero_completo(_sim_ut)} · Margen: {_sim_m}%</div>
                </div>""",
                unsafe_allow_html=True
            )

        st.markdown("---")

        # ── Exportar PDFs ────────────────────────────────────────────
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
                    # FIX-2b: spinner durante la generación del buffer ReportLab
                    with st.spinner("Generando documento corporativo..."):
                        pdf_bytes = generar_pdf_cotizacion(
                            r, numero=num_cot,
                            empresa_info=st.session_state.empresa_info,
                            logo_bytes=st.session_state.logo_bytes,
                            incluir_iva=_iva_act,
                        )
                    st.download_button(
                        "⬇ Descargar Cotización PDF", pdf_bytes,
                        file_name=f"{num_cot}_Cotizacion.pdf", mime="application/pdf",
                        use_container_width=True, key="dl_pdf_cot"
                    )

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
                # FIX-2c: spinner durante la generación del buffer ReportLab
                with st.spinner("Generando documento corporativo..."):
                    cc_bytes = generar_cuenta_cobro(
                        r, st.session_state.empresa_info.copy(), datos_pag,
                        numero=num_cc, logo_bytes=st.session_state.logo_bytes, incluir_iva=_iva_act,
                    )
                st.download_button(
                    "⬇ Descargar Cuenta de Cobro PDF", cc_bytes,
                    file_name=f"{num_cc}_CuentaCobro.pdf", mime="application/pdf",
                    use_container_width=True, key="dl_pdf_cc"
                )

        st.markdown("---")
        _col_nueva, _col_editar = st.columns(2)
        with _col_nueva:
            if st.button("🆕 Nueva cotización", use_container_width=True, type="primary"):
                for k in ["cotizacion", "pre", "piezas", "materiales_proyecto",
                          "_cotiz_guardada", "_cotiz_guardada_num", "_num_auto_sugerido",
                          "_borrador_restaurado", "_sp_borrador_hash"]:
                    st.session_state.pop(k, None)
                for _wk in [k for k in st.session_state if k.startswith("cdir_")]:
                    del st.session_state[_wk]
                # ── store_permanente: reset del wizard para nueva cotización ──
                _sp = st.session_state.get("store_permanente", {})
                for _sk in [k for k in list(_sp.keys()) if k.startswith("cdir_")]:
                    del _sp[_sk]
                _sp["cdir_paso"]      = 0
                _sp["cdir_piezas"]    = []
                _sp["cdir_materiales"] = []
                st.session_state.cdir_paso    = 0
                st.session_state.cdir_success = False
                st.rerun()
        with _col_editar:
            if st.button("✏️ Editar esta cotización", use_container_width=True):
                st.session_state.cdir_success = False
                st.session_state.cdir_paso    = 0
                st.rerun()

        # FIN pantalla de éxito — no renderizar nada más
        st.stop()

    # ════════════════════════════════════════════════════════════════════
    # WIZARD — Barra de progreso + navegación
    # ════════════════════════════════════════════════════════════════════
    paso = st.session_state.cdir_paso

    # Botón limpiar — protegido con popover de confirmación (previene pérdida accidental en móvil)
    if pre and (pre.get("nombre_cliente") or pre.get("piezas") or pre.get("materiales_proyecto")):
        with st.popover("🗑️ Reiniciar cotización", use_container_width=False):
            st.markdown(
                "<div style='font-size:0.88rem;font-weight:700;color:#dc2626;margin-bottom:6px'>"
                "⚠️ ¿Estás seguro?</div>"
                "<div style='font-size:0.80rem;line-height:1.55;opacity:0.80;margin-bottom:14px'>"
                "Se perderán <strong>todos los datos</strong> del formulario actual: "
                "materiales, dimensiones, piezas, logística y el cálculo guardado.</div>",
                unsafe_allow_html=True
            )
            if st.button(
                "Sí, borrar todo y empezar de cero",
                key="btn_confirmar_limpiar",
                type="primary",
                use_container_width=True,
            ):
                for k in ["pre", "piezas", "materiales_proyecto", "cotizacion",
                          "_cotiz_guardada", "_cotiz_guardada_num", "_num_auto_sugerido",
                          "_borrador_restaurado"]:
                    st.session_state.pop(k, None)
                for _wk in [k for k in st.session_state if k.startswith("cdir_")]:
                    del st.session_state[_wk]
                st.session_state.cdir_paso    = 0
                st.session_state.cdir_success = False
                st.rerun()

    # Barra de progreso visual
    _pct_progreso = int((paso / (N_PASOS - 1)) * 100)
    _pasos_html = ""
    for _i, _p in enumerate(WIZARD_PASOS):
        if _i < paso:
            _dot_style = "background:#1B5FA8;color:white;border:2px solid #1B5FA8"
            _lbl_style = "color:#1B5FA8;font-weight:700"
            _dot_char  = "&#10003;"
            _conn_bg   = "#1B5FA8"
            _conn_op   = "1"
        elif _i == paso:
            _dot_style = "background:#1B5FA8;color:white;border:2px solid #1B5FA8;box-shadow:0 0 0 4px rgba(27,95,168,0.18)"
            _lbl_style = "color:#1B5FA8;font-weight:900"
            _dot_char  = str(_i + 1)
            _conn_bg   = "var(--border-color)"
            _conn_op   = "0.25"
        else:
            _dot_style = "background:transparent;color:var(--text-color);border:2px solid var(--border-color);opacity:0.4"
            _lbl_style = "opacity:0.4"
            _dot_char  = str(_i + 1)
            _conn_bg   = "var(--border-color)"
            _conn_op   = "0.25"

        _pasos_html += (
            '<div style="display:flex;flex-direction:column;align-items:center;gap:4px;min-width:56px">'
            '<div style="width:32px;height:32px;border-radius:50%;display:flex;align-items:center;'
            'justify-content:center;font-size:0.78rem;font-weight:800;' + _dot_style + '">' + _dot_char + '</div>'
            '<div style="font-size:0.65rem;text-align:center;' + _lbl_style + '">' + _p["label"] + '</div>'
            '</div>'
        )
        if _i < N_PASOS - 1:
            _pasos_html += (
                '<div style="flex:1;height:2px;background:' + _conn_bg + ';opacity:' + _conn_op + ';'
                'margin-bottom:14px;align-self:flex-start;margin-top:16px"></div>'
            )

    st.markdown(
        '<div style="display:flex;align-items:flex-start;margin-bottom:24px;'
        'padding:16px 20px;background:var(--secondary-background-color);'
        'border-radius:12px;border:1px solid var(--border-color)">'
        + _pasos_html +
        '</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        f"<h2 style='font-family:Playfair Display,serif;margin-bottom:2px'>"
        f"{WIZARD_PASOS[paso]['icono']} {WIZARD_PASOS[paso]['label']}</h2>"
        f"<p style='opacity:0.6;font-size:0.85rem;margin-bottom:20px'>Paso {paso+1} de {N_PASOS}</p>",
        unsafe_allow_html=True
    )

    # ── Navegación no-lineal: pills de salto directo entre pasos ─────────────
    # Permite saltar a cualquier paso sin usar los botones Anterior/Siguiente.
    # Importante: mostramos todos los pasos (incluyendo Resultado) para que el
    # usuario pueda volver a revisar. El cambio aplica inmediatamente vía rerun.
    _pill_labels_cdir = [
        f"{p['icono']} {i+1}. {p['label']}"
        for i, p in enumerate(WIZARD_PASOS)
    ]
    _pill_sel_cdir = st.pills(
        "Ir al paso",
        options=_pill_labels_cdir,
        default=_pill_labels_cdir[paso],
        key=f"nav_pills_cdir_{paso}",        # key incluye paso para forzar reset al avanzar
        label_visibility="collapsed",
    )
    if _pill_sel_cdir is not None:
        _paso_pill = _pill_labels_cdir.index(_pill_sel_cdir)
        if _paso_pill != paso:
            st.session_state.cdir_paso = _paso_pill
            st.rerun()

    # ════════════════════════════════════════════════════════════════════
    # PASO 0 — MATERIAL(ES)
    # ════════════════════════════════════════════════════════════════════
    if paso == 0:
        seccion_titulo("¿Qué material vas a instalar?",
                       "Puedes agregar varios materiales si el proyecto mezcla referencias")

        with st.expander("❓ ¿Cómo lleno este paso?", expanded=False):
            st.markdown("""
**Categoría:** El tipo de piedra (Mármol, Granito, Sinterizado, etc.)

**Referencia:** El nombre de la lámina que compraste. Está en la factura del proveedor.

**Precio/m²:** Exactamente lo que te cobró el proveedor por m². No lo inventes — usa la factura.

**Área comprada:** Los m² totales de la lámina. Ejemplo: 1,20 m × 2,60 m = **3,12 m²**.
            """)

        if "materiales_proyecto" not in st.session_state or not st.session_state.materiales_proyecto:
            st.session_state.materiales_proyecto = pre.get("materiales_proyecto", [
                {"cat": pre.get("categoria", "Mármol"), "ref": pre.get("referencia", ""),
                 "precio_m2": pre.get("precio_m2", 220_000), "area_placa": pre.get("area_placa_comprada", 5.94)}
            ])

        mats       = st.session_state.materiales_proyecto
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

                    # Badge visual de categoría
                    from parametros import BADGE_COLORS, DESCRIPCIONES_CATEGORIA
                    _bc = BADGE_COLORS.get(cat_sel_m, ("#f0f0f0","#333"))
                    st.markdown(
                        f'<div style="background:{_bc[0]};color:{_bc[1]};border-radius:6px;'
                        f'padding:6px 12px;font-size:0.78rem;font-weight:700;display:inline-block">'
                        f'{DESCRIPCIONES_CATEGORIA.get(cat_sel_m,"")}</div>',
                        unsafe_allow_html=True
                    )

                with colb:
                    refs_m     = ["Otra referencia..."] + [m["nombre"] for m in MATERIALES_CATALOGO if m["categoria"] == cat_sel_m]
                    pre_ref_m  = mat_item.get("ref","")
                    idx_ref_m  = refs_m.index(pre_ref_m) if pre_ref_m in refs_m else 0
                    ref_sel_m  = st.selectbox("Referencia del material", refs_m, index=idx_ref_m, key=f"mref_{midx}")
                    if ref_sel_m == "Otra referencia...":
                        referencia_m = st.text_input("Nombre de la referencia", value=pre_ref_m if pre_ref_m not in refs_m else "",
                                                     key=f"mrefcust_{midx}", placeholder="Ej: Calacatta Gold")
                    else:
                        referencia_m = ref_sel_m
                        m_cat_data   = next((m for m in MATERIALES_CATALOGO if m["nombre"] == ref_sel_m), None)

                colc, cold = st.columns(2)
                with colc:
                    precio_m2_m = st.number_input(
                        "Precio por m² (COP)", min_value=10_000, max_value=5_000_000,
                        value=int(mat_item.get("precio_m2", 220_000)), step=1_000,
                        key=f"mpm2_{midx}",
                        help="Este valor está en la factura del proveedor"
                    )
                    st.markdown(f"<div style='margin-top:-12px; margin-bottom:10px; font-size:0.85rem; color:#1B5FA8; font-weight:600;'>💰 Equivalencia: {cop(precio_m2_m)}</div>", unsafe_allow_html=True)
                with cold:
                    # Recuperar dimensiones guardadas (o calcularlas desde area_placa legacy)
                    _area_leg   = float(mat_item.get("area_placa", 5.94))
                    _cant_prev  = int(mat_item.get("placas_cant", 1))
                    _largo_prev = float(mat_item.get("placas_largo", round(_area_leg / 0.60, 2)))
                    _ancho_prev = float(mat_item.get("placas_ancho", 0.60))
                    st.markdown("<div style='font-size:0.8rem;font-weight:600;opacity:0.7;margin-bottom:4px'>Dimensiones de la lámina</div>", unsafe_allow_html=True)
                    _pcol1, _pcol2, _pcol3 = st.columns(3)
                    with _pcol1:
                        _cant_placas = st.number_input(
                            "Cant. placas", min_value=1, max_value=50, value=_cant_prev, step=1,
                            key=f"mpcant_{midx}", help="Número de láminas completas compradas"
                        )
                    with _pcol2:
                        _largo_placa = st.number_input(
                            "Largo (m)", min_value=0.10, max_value=10.0, value=_largo_prev, step=0.01,
                            key=f"mplargo_{midx}", format="%.2f", help="Largo de cada lámina en metros"
                        )
                    with _pcol3:
                        _ancho_placa = st.number_input(
                            "Ancho (m)", min_value=0.10, max_value=5.0, value=_ancho_prev, step=0.01,
                            key=f"mpancho_{midx}", format="%.2f", help="Ancho de cada lámina en metros"
                        )
                    area_placa_m = round(_cant_placas * _largo_placa * _ancho_placa, 4)
                    st.caption(f"Área total calculada: {area_placa_m:.2f} m²")

                costo_m = precio_m2_m * area_placa_m
                st.markdown(
                    f'<div style="background:var(--secondary-background-color);border-radius:8px;'
                    f'padding:8px 14px;margin-top:4px;font-size:0.85rem">'
                    f'<span style="opacity:0.6">{numero_completo(precio_m2_m)}/m² × {area_placa_m:.3f} m² = </span>'
                    f'<strong style="color:#1B5FA8">{numero_completo(costo_m)}</strong></div>',
                    unsafe_allow_html=True
                )

                # Banco de Retales
                _mat_dict = {"cat": cat_sel_m, "ref": referencia_m, "precio_m2": precio_m2_m, "area_placa": area_placa_m,
                              "placas_cant": _cant_placas, "placas_largo": _largo_placa, "placas_ancho": _ancho_placa}
                try:
                    _usr_act = st.session_state.get("usuario_actual", {})
                    _retales_disp = _consultar_retal(
                        cat_sel_m, referencia_m,
                        usuario_id=_usr_act.get("id"),
                        rol=_usr_act.get("rol", "Admin"),
                    )
                except Exception:
                    _retales_disp = []

                if _retales_disp:
                    _m2_total_retal = sum(r[2] for r in _retales_disp)
                    _retal_key      = f"usar_retal_{midx}"
                    _retal_sel_key  = f"retal_seleccionando_{midx}"
                    _usando_retal   = st.session_state.get(_retal_key, False)
                    _seleccionando  = st.session_state.get(_retal_sel_key, False)

                    if not _usando_retal and not _seleccionando:
                        # ── Estado inicial: banner informativo + botón ─────────
                        _num_piezas = len(_retales_disp)
                        _orig_txt   = _retales_disp[0][3] if _num_piezas == 1 else f"{_num_piezas} sobrantes disponibles"
                        st.markdown(
                            f'<div style="border:1px solid #1B5FA8;border-left:4px solid #1B5FA8;'
                            f'border-radius:8px;padding:10px 16px;margin:8px 0;background:rgba(27,95,168,0.06);">'
                            f'<div style="font-size:0.8rem;font-weight:700;color:#1B5FA8;margin-bottom:4px">'
                            f'♻️ Tienes {fmt_m2(_m2_total_retal, 2)} de sobrante de este material</div>'
                            f'<div style="font-size:0.75rem;opacity:0.65">Origen: {_orig_txt}</div></div>',
                            unsafe_allow_html=True
                        )
                        _col_rb, _ = st.columns([1.6, 2.4])
                        with _col_rb:
                            if st.button("Usar sobrante →", key=f"btn_retal_{midx}",
                                         type="primary", use_container_width=True):
                                # Solo abre el selector — NO asigna nada todavía
                                st.session_state[_retal_sel_key] = True
                                st.rerun()

                    elif _seleccionando:
                        # ── Paso de selección manual ───────────────────────────
                        st.markdown(
                            '<div style="border:1px solid #C9A84C;border-left:4px solid #C9A84C;'
                            'border-radius:8px;padding:10px 16px;margin:8px 0;'
                            'background:rgba(201,168,76,0.07);">'
                            '<div style="font-size:0.78rem;font-weight:700;color:#C9A84C;margin-bottom:6px">'
                            '🗂️ Selecciona el sobrante que quieres usar</div>'
                            '<div style="font-size:0.72rem;opacity:0.65;margin-bottom:6px">'
                            'Elige el sobrante que mejor se ajuste a tu proyecto.</div>'
                            '</div>',
                            unsafe_allow_html=True
                        )
                        # Construir opciones: r = (id, referencia, m2, origen_numero, origen_cliente, fecha_ingreso)
                        _opciones_retal = []
                        _mapa_retal     = {}
                        for _r in _retales_disp:
                            _rid   = _r[0]
                            _rref  = _r[1] or "Sin referencia"
                            _rm2   = _r[2]
                            _rnum  = _r[3] or "—"
                            _rclte = _r[4] or "—"
                            _rfech = str(_r[5])[:10] if len(_r) > 5 and _r[5] else ""
                            _lbl   = f"{fmt_m2(_rm2, 3)} · {_rref} · Cot. {_rnum}"
                            if _rfech:
                                _lbl += f" · {_rfech}"
                            _opciones_retal.append(_lbl)
                            _mapa_retal[_lbl] = {"id": _rid, "m2": _rm2}

                        _sel_lbl = st.radio(
                            "Sobrantes disponibles",
                            options=_opciones_retal,
                            key=f"retal_radio_{midx}",
                            label_visibility="collapsed",
                        )
                        _rsel_data = _mapa_retal.get(_sel_lbl, {})

                        _cbtn_c1, _cbtn_c2 = st.columns(2)
                        with _cbtn_c1:
                            if st.button("✓ Usar este sobrante", key=f"btn_confirmar_retal_{midx}",
                                         type="primary", use_container_width=True):
                                st.session_state[_retal_key]           = True
                                st.session_state[f"retal_id_{midx}"]   = _rsel_data["id"]
                                st.session_state[f"retal_m2_{midx}"]   = _rsel_data["m2"]
                                st.session_state.pop(_retal_sel_key, None)
                                st.rerun()
                        with _cbtn_c2:
                            if st.button("✕ Cancelar", key=f"btn_cancel_sel_{midx}",
                                         use_container_width=True):
                                st.session_state.pop(_retal_sel_key, None)
                                st.rerun()

                    else:
                        # ── Sobrante ya confirmado y activo ────────────────────
                        _rid_activo = st.session_state.get(f"retal_id_{midx}")
                        _rm2_activo = st.session_state.get(f"retal_m2_{midx}", _m2_total_retal)
                        _precio_rec = 0.0
                        try:
                            _conn_rec = _get_db_connection()
                            _cur_rec  = _conn_rec.cursor()
                            _cur_rec.execute("SELECT precio_recuperacion FROM inventario_retales WHERE id=%s", (_rid_activo,))
                            _row_rec  = _cur_rec.fetchone()
                            _precio_rec = float(_row_rec[0] or 0) if _row_rec else 0.0
                            _cur_rec.close(); _conn_rec.close()
                        except Exception:
                            pass
                        _mat_dict["precio_m2"]  = _precio_rec
                        _mat_dict["area_placa"] = _rm2_activo
                        _mat_dict["es_retal"]   = True
                        _mat_dict["retal_id"]   = _rid_activo
                        _prec_txt = f"Precio/m²: {numero_completo(_precio_rec)}" if _precio_rec > 0 else "Precio fijado en $0"
                        st.markdown(
                            f'<div style="border:1px solid #15803d;border-left:4px solid #15803d;border-radius:8px;'
                            f'padding:10px 16px;margin:8px 0;background:rgba(21,128,61,0.06);">'
                            f'<div style="font-size:0.8rem;font-weight:700;color:#15803d;margin-bottom:3px">'
                            f'♻️ Sobrante activo — {_prec_txt} · Área: {fmt_m2(_rm2_activo,3)}</div>'
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
                        _sp_eliminar_material(midx)
                        st.rerun()

                mats_nuevos.append(_mat_dict)

        # Sync materiales to store_permanente
        _sp_sync_materiales(mats_nuevos)
        st.session_state.materiales_proyecto = mats_nuevos

        if st.button("＋ Agregar otro material", use_container_width=True):
            _sp_agregar_material()
            st.rerun()

        # Derivar valores de materiales para pasos siguientes
        cat_sel     = mats_nuevos[0]["cat"]    if mats_nuevos else "Mármol"
        _refs_raw   = [m["ref"] or m["cat"] for m in mats_nuevos]
        _refs_unicas = list(dict.fromkeys(_refs_raw))  # Preserva orden, elimina duplicados
        referencia  = " + ".join(_refs_unicas) if len(_refs_unicas) > 1 else (_refs_unicas[0] if _refs_unicas else "")
        precio_m2   = mats_nuevos[0]["precio_m2"] if mats_nuevos else 220_000
        area_placa  = sum(m["area_placa"] for m in mats_nuevos)
        precio_m2_efectivo = mats_nuevos[0]["precio_m2"] if mats_nuevos else 220_000
        costo_material_total = sum(m["precio_m2"] * m["area_placa"] for m in mats_nuevos)

    # ════════════════════════════════════════════════════════════════════
    # PASO 1 — DIMENSIONES
    # ════════════════════════════════════════════════════════════════════
    elif paso == 1:
        # Recuperar materiales del paso anterior
        _mats_p1    = st.session_state.get("materiales_proyecto", [])
        cat_sel     = _mats_p1[0]["cat"]    if _mats_p1 else pre.get("categoria","Mármol")
        area_placa  = sum(m["area_placa"] for m in _mats_p1) if _mats_p1 else pre.get("area_placa_comprada", 5.94)

        seccion_titulo("¿Cuántas piezas tiene el proyecto?",
                       "Cada tramo o elemento de piedra es una pieza. Ingresa el largo en metros.")

        with st.expander("❓ ¿Qué es un metro lineal (ML)?", expanded=False):
            st.markdown("""
**ML = la longitud** de la pieza. La app calcula los m² sola.

| Pieza | Largo que ingresas | Ancho estándar | m² resultado |
|---|---|---|---|
| Mesón de 3 m | **3 ML** | 0,60 m | 1,80 m² |
| Baño de 1,2 m | **1,2 ML** | 0,45 m | 0,54 m² |
| Escalón | **0,9 ML** | 0,30 m | 0,27 m² |

Si el ancho es diferente, elige **Personalizado** y ajusta.
            """)

        if "piezas" not in st.session_state or not st.session_state.piezas:
            st.session_state.piezas = pre.get("piezas", [
                {"nombre": "Mesón de cocina", "ml": 2.0, "ancho_tipo": "Mesón de cocina", "ancho_custom": 0.60}
            ])

        tipos_superficie = list(ANCHOS_ESTANDAR.keys())
        piezas_nuevas    = []
        total_m2_piezas  = 0.0

        # ── CARDS POR PIEZA — layout mobile-first ────────────────────
        # Se elimina la "falsa tabla" de encabezados que colapsaba en móviles.
        # Cada pieza es una Card independiente con máximo 2 columnas por fila.
        for idx, pieza in enumerate(st.session_state.piezas):
            with st.container(border=True):
                # ── FILA 1: Descripción + Botón eliminar ─────────────
                _col_nom, _col_del = st.columns([5, 1])
                with _col_nom:
                    nombre_p = st.text_input(
                        "Descripción de la pieza",
                        value=pieza.get("nombre", ""),
                        key=f"pnom_{idx}",
                        placeholder=f"Pieza {idx + 1} — ej: Mesón de cocina",
                    )
                with _col_del:
                    # Spacer para alinear el botón con el input de la columna izquierda
                    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                    if st.button("🗑️", key=f"del_{idx}", help="Eliminar pieza",
                                 use_container_width=True) and len(st.session_state.piezas) > 1:
                        _sp_eliminar_pieza(idx)
                        st.rerun()

                # ── FILA 2: Tipo de elemento + Largo en ML + Cantidad ─
                _col_tipo, _col_ml, _col_cant = st.columns([2, 1.5, 1])
                with _col_tipo:
                    tipo_idx     = tipos_superficie.index(pieza.get("ancho_tipo", tipos_superficie[0])) if pieza.get("ancho_tipo") in tipos_superficie else 0
                    ancho_tipo_p = st.selectbox(
                        "Tipo de elemento",
                        tipos_superficie,
                        index=tipo_idx,
                        key=f"ptip_{idx}",
                        help=ANCHOS_ESTANDAR.get(pieza.get("ancho_tipo", tipos_superficie[0]), {}).get("desc", ""),
                    )
                with _col_ml:
                    ml_p = st.number_input(
                        "Largo (ML)",
                        value=float(pieza.get("ml", 1.0)),
                        min_value=0.01,
                        step=0.1,
                        key=f"pml_{idx}",
                        help="Metros lineales de esta pieza (una unidad)",
                    )
                with _col_cant:
                    cantidad_p = st.number_input(
                        "Cantidad",
                        value=int(pieza.get("cantidad", 1)),
                        min_value=1,
                        max_value=100,
                        step=1,
                        key=f"pcant_{idx}",
                        help="Número de piezas idénticas. El total ML = Largo × Cantidad",
                    )

                # ── CONDICIONAL: nombre extra si elige Personalizado ──
                if ancho_tipo_p == "Personalizado":
                    st.text_input(
                        "Nombre personalizado (aparece en el PDF)",
                        value=st.session_state.get(f"pcustom_{idx}", pieza.get("nombre_personalizado", "")),
                        key=f"pcustom_{idx}",
                        placeholder='Ej: "Mesón de lavamanos", "Pantry", "Cornisa"',
                        help="Nombre descriptivo que aparecerá en la cotización PDF",
                    )

                # ── FILA 3: Ancho + m² calculados ────────────────────
                _col_ancho, _col_m2 = st.columns(2)
                with _col_ancho:
                    ancho_def = ANCHOS_ESTANDAR[ancho_tipo_p]["ancho"] or pieza.get("ancho_custom", 0.60)
                    ancho_p   = st.number_input(
                        "Ancho (m)",
                        value=float(ancho_def),
                        min_value=0.01,
                        step=0.01,
                        key=f"panc_{idx}",
                        help="Profundidad o alto de la pieza en metros",
                    )
                ml_efectivo = ml_p * cantidad_p            # largo × cantidad
                m2_p = ml_a_m2(ml_efectivo, ancho_p)       # m² totales de esta fila
                total_m2_piezas += m2_p
                with _col_m2:
                    _m2_desc = f"{ml_p:.2f} ml × {ancho_p:.2f} m × {cantidad_p}" if cantidad_p > 1 else f"{ml_p:.2f} ml × {ancho_p:.2f} m"
                    st.markdown(
                        f"""<div style="background:rgba(27,95,168,0.08);border:1px solid rgba(27,95,168,0.22);
                        border-radius:10px;padding:10px 14px;margin-top:4px">
                        <div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;
                             letter-spacing:0.1em;color:#1B5FA8;opacity:0.8">m² calculados</div>
                        <div style="font-size:1.45rem;font-weight:900;color:#1B5FA8;
                             font-family:'Playfair Display',serif;line-height:1.2">{fmt_m2(m2_p)}</div>
                        <div style="font-size:0.7rem;opacity:0.6;margin-top:2px">{_m2_desc}</div>
                        </div>""",
                        unsafe_allow_html=True,
                    )

                # Guardar pieza con nombre_personalizado actualizado desde el widget
                _nom_personalizado = st.session_state.get(f"pcustom_{idx}", pieza.get("nombre_personalizado", ""))
                piezas_nuevas.append({
                    "nombre":              nombre_p,
                    "ml":                  ml_efectivo,     # largo × cantidad (total real)
                    "ml_unitario":         ml_p,            # largo de una sola pieza
                    "cantidad":            cantidad_p,
                    "ancho_tipo":          ancho_tipo_p,
                    "ancho_custom":        ancho_p,
                    "nombre_personalizado": _nom_personalizado,
                })

        # Sync piezas to store_permanente (event-driven — persists across navigation)
        _sp_sync_piezas(piezas_nuevas)
        st.session_state.piezas = piezas_nuevas
        m2_real         = total_m2_piezas
        m2_cortados_total = total_m2_piezas

        _col_add, _col_tot = st.columns([1, 2])
        with _col_add:
            if st.button("＋ Agregar pieza", use_container_width=True):
                _sp_agregar_pieza()
                st.rerun()
        with _col_tot:
            if m2_real > 0:
                _ml_total = sum(p.get("ml",0) for p in st.session_state.piezas)  # ya es ml efectivo (unitario × cantidad)
                st.markdown(
                    f'''<div style="background:var(--secondary-background-color);border:1px solid var(--border-color);
                    border-radius:10px;padding:12px 18px;text-align:center">
                    <div style="font-size:0.7rem;color:#1B5FA8;text-transform:uppercase;letter-spacing:0.08em;font-weight:700">Total</div>
                    <div style="font-size:2rem;font-weight:900;font-family:'Playfair Display',serif">{fmt_ml(_ml_total)}</div>
                    <div style="font-size:0.85rem;opacity:0.7">{fmt_m2(m2_real)} de material</div>
                    </div>''', unsafe_allow_html=True)

        st.markdown("---")

        # ── Margen y m² usados ────────────────────────────────────────
        st.markdown("**Margen de ganancia y uso del material**")
        _cm1, _cm2, _cm3 = st.columns([1.5, 1.5, 1])

        with _cm1:
            # Segmented control para margen — rango típico en 5 opciones rápidas
            _margen_opciones = ["20%", "30%", "35%", "40%", "45%", "50%", "Otro"]
            _margen_pre      = int(pre.get("margen_pct", 40))
            _margen_pre_str  = f"{_margen_pre}%" if f"{_margen_pre}%" in _margen_opciones else "Otro"
            _margen_sel = st.pills("Margen rápido", _margen_opciones,
                                   default=_margen_pre_str, key="p1_margen_pills",
                                   help="Porcentaje de ganancia sobre el precio de venta")
            if _margen_sel == "Otro" or _margen_sel is None:
                margen_pct = st.number_input("Margen personalizado (%)", min_value=5, max_value=80,
                                             value=_margen_pre, step=1, key="p1_margen_custom")
            else:
                margen_pct = int(_margen_sel.replace("%",""))

        with _cm2:
            # Sincronizar m² usados automáticamente cuando cambia m2_real
            _m2_real_prev = st.session_state.get("_cdir_m2_real_prev", None)
            if _m2_real_prev is None or abs(_m2_real_prev - m2_real) > 0.001:
                st.session_state["cdir_m2_usados"] = round(m2_real, 3)
                st.session_state["_cdir_m2_real_prev"] = m2_real
            m2_usados = st.number_input("m² finalmente instalados", min_value=0.0,
                                        value=float(pre.get("m2_usados", m2_real)), step=0.05,
                                        key="cdir_m2_usados",
                                        help="Normalmente igual a los m² del proyecto. Solo cambia si instalaste menos.")

        with _cm3:
            if area_placa > 0 and m2_usados > 0:
                aprv   = min(100, m2_usados / area_placa * 100)
                retal_ = max(0, area_placa - m2_usados)
                estado_a = "bueno" if aprv >= 80 else "acepta" if aprv >= 50 else "bajo"
                alerta(f"Uso del material: **{aprv:.1f}%**  Sobra: {fmt_m2(retal_)}", estado_a)

        # Guardar en pre para uso en pasos siguientes
        st.session_state.pre = {**pre, "margen_pct": margen_pct, "m2_usados": m2_usados, "piezas": st.session_state.piezas}
        # ── store_permanente sync: margen y m2_usados ─────────────────────────
        _sp_set("cdir_margen_pct", margen_pct)
        _sp_set("cdir_m2_usados", m2_usados)

    # ════════════════════════════════════════════════════════════════════
    # PASO 2 — PROYECTO (tipo, etapa, días, personas, zócalos, desperdicio)
    # ════════════════════════════════════════════════════════════════════
    elif paso == 2:
        _mats_p2    = st.session_state.get("materiales_proyecto", [])
        cat_sel     = _mats_p2[0]["cat"] if _mats_p2 else pre.get("categoria","Mármol")
        area_placa  = sum(m["area_placa"] for m in _mats_p2) if _mats_p2 else pre.get("area_placa_comprada", 5.94)
        _piezas_p2  = st.session_state.get("piezas", pre.get("piezas",[]))
        m2_real     = sum(ml_a_m2(float(p.get("ml",0)), float(p.get("ancho_custom",0.60))) for p in _piezas_p2) or pre.get("m2_proyecto", 4.0)

        seccion_titulo("Datos del proyecto", "Tipo de obra, cuántos días y quiénes van")

        c1, c2 = st.columns(2)
        with c1:
            tipo_opts  = ["Mesón", "Cocina", "Baño", "Piso", "Escalera", "Fachada", "Mueble de cocina", "Otro"]
            _sp_tipos  = _sp().get("cdir_tipos_proyecto", pre.get("tipos_proyecto", [pre.get("tipo_proyecto","Mesón")] if pre.get("tipo_proyecto") else ["Mesón"]))
            tipos_sel  = st.multiselect(
                "Tipo(s) de proyecto", tipo_opts,
                default=[t for t in _sp_tipos if t in tipo_opts] or ["Mesón"],
                key="cb_cdir_tipos_proyecto",
                on_change=_cb_cdir_tipos_proyecto,
            )
            tipo = " + ".join(tipos_sel) if tipos_sel else "Otro"

        with c2:
            _sp_etapa_label = _sp().get("cdir_etapa_label", pre.get("etapa_label", list(ETAPAS_OBRA.keys())[0]))
            etapa = ETAPAS_OBRA[st.selectbox(
                "Etapa de la obra", list(ETAPAS_OBRA.keys()),
                index=list(ETAPAS_OBRA.keys()).index(_sp_etapa_label)
                      if _sp_etapa_label in ETAPAS_OBRA else 0,
                key="cb_cdir_etapa",
                on_change=_cb_cdir_etapa,
            )]

        nombre_cliente = st.text_input(
            "Nombre del cliente",
            value=_sp().get("cdir_nombre_cliente", pre.get("nombre_cliente", "")),
            placeholder="Ej: Juan García / Constructora XYZ",
            key="cb_cdir_nombre_cliente",
            on_change=_cb_cdir_nombre_cliente,
        )

        st.markdown("---")

        # ── Días y personas — segmented controls ─────────────────────
        st.markdown("**¿Cuántos días dura la instalación y cuántas personas van?**")
        _dc1, _dc2 = st.columns(2)

        with _dc1:
            _dias_opts = ["1", "2", "3", "4", "5", "6+"]
            _dias_pre  = int(pre.get("dias_obra", 2))
            # FIX-1: garantizar que el default exista en la lista de opciones
            _dias_pre_s = str(_dias_pre) if str(_dias_pre) in _dias_opts else ("6+" if _dias_pre > 5 else _dias_opts[0])
            _dias_sel   = st.pills("Días en obra", _dias_opts, default=_dias_pre_s, key="p2_dias_pills")
            if _dias_sel == "6+" or _dias_sel is None:
                dias = st.number_input("Días (exacto)", min_value=1, value=_dias_pre, step=1, key="p2_dias_custom")
            else:
                dias = int(_dias_sel)

        with _dc2:
            _pers_opts = ["1", "2", "3", "4", "5+"]
            _pers_pre  = int(pre.get("personas", 2))
            # FIX-1: garantizar que el default exista en la lista de opciones
            _pers_pre_s = str(_pers_pre) if str(_pers_pre) in _pers_opts else ("5+" if _pers_pre > 4 else _pers_opts[0])
            _pers_sel   = st.pills("Personas en obra", _pers_opts, default=_pers_pre_s, key="p2_pers_pills")
            if _pers_sel == "5+" or _pers_sel is None:
                personas = st.number_input("Personas (exacto)", min_value=1, value=_pers_pre, step=1, key="p2_pers_custom")
            else:
                personas = int(_pers_sel)

        st.markdown("---")

        # ── Zócalos ──────────────────────────────────────────────────
        st.markdown("**¿El proyecto lleva zócalos?**")
        zocalo_activo = st.toggle("Sí, incluir zócalos", value=pre.get("zocalo_activo", False), key="cdir_zocalo_activo")
        zocalo_ml = 0.0
        if zocalo_activo:
            _zoc_opts = ["1 ml", "2 ml", "3 ml", "4 ml", "5 ml", "Otro"]
            _zoc_pre  = float(pre.get("zocalo_ml", 2.0))
            _zoc_pre_s = f"{int(_zoc_pre)} ml" if f"{int(_zoc_pre)} ml" in _zoc_opts else "Otro"
            _zoc_sel  = st.pills("Metros de zócalo", _zoc_opts, default=_zoc_pre_s, key="p2_zocalo_pills")
            if _zoc_sel == "Otro" or _zoc_sel is None:
                zocalo_ml = st.number_input("Metros lineales de zócalo", min_value=0.0,
                                             value=_zoc_pre, step=0.5, key="cdir_zocalo_ml")
            else:
                zocalo_ml = float(_zoc_sel.replace(" ml",""))

        st.markdown("---")

        # ── Desperdicio visual (conservado del original) ──────────────
        desperdicio_sugerido_15 = round(m2_real * 0.15, 2)
        st.markdown("""
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px">
          <span style="font-weight:700;font-size:1rem">Desperdicio en cortes</span>
          <span style="background:#1B5FA8;color:white;font-size:0.65rem;font-weight:700;
                       padding:3px 8px;border-radius:20px;letter-spacing:0.05em">RETAL</span>
        </div>
        <p style="font-size:0.82rem;opacity:0.65;margin:0 0 10px">
          Todo corte genera sobrante. Elige el perfil de tu proyecto.
        </p>""", unsafe_allow_html=True)

        with st.container(border=True):
            perfil_opciones = {
                "🟢 Simple — cortes rectos, sin curvas":     ("simple",   0.10),
                "🟡 Normal — algunos ángulos o esquinas":    ("normal",   0.15),
                "🔴 Complejo — curvas, biselados, figuras":  ("complejo", 0.22),
                "✏️ Personalizado":                          ("custom",   None),
            }
            perfil_sel = st.radio(
                "Perfil de corte", list(perfil_opciones.keys()), index=1,
                key="perfil_desperdicio_radio", label_visibility="collapsed"
            )
            perfil_id, pct_auto = perfil_opciones[perfil_sel]
            pct_auto = pct_auto or 0.15

            _cv1, _cv2 = st.columns([1.2, 1])
            with _cv1:
                st.markdown("<div style='font-size:0.78rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;opacity:0.6;margin-bottom:6px'>m² de retal estimados</div>", unsafe_allow_html=True)
                if perfil_id == "custom":
                    extra_corte = st.number_input(
                        "m² de retal", min_value=0.0, max_value=float(area_placa) if area_placa > 0 else 50.0,
                        value=float(pre.get("extra_corte", round(m2_real * 0.15, 2))),
                        step=0.05, format="%.2f", label_visibility="collapsed", key="cdir_extra_corte"
                    )
                    pct_real = (extra_corte / m2_real * 100) if m2_real > 0 else 0
                    st.caption(f"Equivale al **{pct_real:.1f}%** del proyecto")
                else:
                    extra_corte = round(m2_real * pct_auto, 2)
                    color_pct   = "#16a34a" if pct_auto <= 0.12 else "#d97706" if pct_auto <= 0.17 else "#dc2626"
                    st.markdown(f"""
                    <div style="background:var(--secondary-background-color);border:2px solid {color_pct};
                                border-radius:8px;padding:10px 14px;display:inline-flex;align-items:baseline;gap:8px">
                      <span style="font-size:1.8rem;font-weight:900;color:{color_pct}">{fmt_m2(extra_corte)}</span>
                      <span style="font-size:0.8rem;color:{color_pct};font-weight:700">({pct_auto*100:.0f}%)</span>
                    </div>""", unsafe_allow_html=True)
                    st.caption(f"Calculado automáticamente ({pct_auto*100:.0f}% de {fmt_m2(m2_real)})")

            with _cv2:
                _tar_actual      = get_tarifas().get(cat_sel, TARIFAS.get(cat_sel, TARIFAS["Mármol"]))
                _costo_disco_ret = extra_corte * _tar_actual.get("disco", 2_200)
                _costo_disco_base = m2_real * _tar_actual.get("disco", 2_200)
                st.markdown(f"""
                <div style="background:var(--secondary-background-color);border:1px solid var(--border-color);
                            border-radius:8px;padding:10px 14px;font-size:0.82rem">
                  <div style="font-size:0.72rem;font-weight:700;opacity:0.5;margin-bottom:6px;text-transform:uppercase">Impacto en costo disco</div>
                  <div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid var(--border-color)">
                    <span style="opacity:0.7">Proyecto</span><span style="font-weight:600">{numero_completo(_costo_disco_base)}</span>
                  </div>
                  <div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid var(--border-color)">
                    <span style="opacity:0.7">Retal</span><span style="font-weight:600;color:#d97706">+{numero_completo(_costo_disco_ret)}</span>
                  </div>
                  <div style="display:flex;justify-content:space-between;padding:4px 0 0">
                    <span style="font-weight:700">Total disco</span>
                    <span style="font-weight:800;color:#1B5FA8">{numero_completo(_costo_disco_base+_costo_disco_ret)}</span>
                  </div>
                </div>""", unsafe_allow_html=True)

        m2_cortados_total = m2_real + extra_corte

        # Guardar en pre
        _etapa_labels = {v: k for k, v in ETAPAS_OBRA.items()}
        st.session_state.pre = {
            **pre,
            "tipos_proyecto": tipos_sel, "tipo_proyecto": tipo,
            "etapa_label": _etapa_labels.get(etapa, list(ETAPAS_OBRA.keys())[0]),
            "dias_obra": dias, "personas": personas, "nombre_cliente": nombre_cliente,
            "zocalo_activo": zocalo_activo, "zocalo_ml": zocalo_ml,
            "perfil_desperdicio": perfil_sel, "extra_corte": extra_corte,
            "m2_proyecto": m2_real, "m2_cortados_input": m2_cortados_total,
        }

    # ════════════════════════════════════════════════════════════════════
    # PASO 3 — LOGÍSTICA + ADICIONALES + IVA
    # ════════════════════════════════════════════════════════════════════
    elif paso == 3:
        _mats_p3    = st.session_state.get("materiales_proyecto", [])
        cat_sel     = _mats_p3[0]["cat"] if _mats_p3 else pre.get("categoria","Mármol")
        area_placa  = sum(m["area_placa"] for m in _mats_p3) if _mats_p3 else pre.get("area_placa_comprada", 5.94)
        precio_m2_efectivo = _mats_p3[0]["precio_m2"] if _mats_p3 else pre.get("precio_m2", 220_000)
        _piezas_p3  = st.session_state.get("piezas", pre.get("piezas",[]))
        m2_real     = sum(ml_a_m2(float(p.get("ml",0)), float(p.get("ancho_custom",0.60))) for p in _piezas_p3) or pre.get("m2_proyecto", 4.0)
        m2_cortados_total = pre.get("m2_cortados_input", m2_real)
        extra_corte       = pre.get("extra_corte", round(m2_real * 0.15, 2))
        margen_pct        = pre.get("margen_pct", 40)
        m2_usados         = pre.get("m2_usados", m2_real)
        dias              = pre.get("dias_obra", 2)
        personas          = pre.get("personas", 2)
        tipo              = pre.get("tipo_proyecto", "Mesón")
        etapa             = pre.get("etapa_label","")
        etapa             = ETAPAS_OBRA.get(etapa, list(ETAPAS_OBRA.values())[0])
        nombre_cliente    = pre.get("nombre_cliente","")
        zocalo_activo     = pre.get("zocalo_activo", False)
        zocalo_ml         = pre.get("zocalo_ml", 0.0)
        tipos_sel         = pre.get("tipos_proyecto", ["Mesón"])

        seccion_titulo("Logística y extras", "Transporte, viáticos, servicios adicionales e IVA")

        # ── Logística ─────────────────────────────────────────────────
        with st.container(border=True):
            st.markdown("**🚛 Transporte y entrega**")
            _lag1, _lag2 = st.columns(2)
            with _lag1:
                agente_ext_taller = st.toggle(
                    "Agente externo trajo el material al taller",
                    value=bool(_sp().get("cdir_agente_externo", pre.get("agente_externo_taller", False))),
                    key="cb_cdir_agente_externo",
                    on_change=_cb_cdir_agente_externo,
                )
            with _lag2:
                _veh_dict = get_vehiculos_dict()
                _veh_keys = list(_veh_dict.keys())
                _v_idx    = 0
                if pre.get("vehiculo_entrega") in list(_veh_dict.values()):
                    _v_idx = list(_veh_dict.values()).index(pre.get("vehiculo_entrega"))

                # Selector visual de vehículo con st.pills
                _veh_sel = st.pills("Vehículo de entrega", _veh_keys,
                                    default=_veh_keys[_v_idx], key="p3_veh_pills")
                veh_lbl  = _veh_sel if _veh_sel else _veh_keys[0]
                vehiculo = _veh_dict[veh_lbl]

            _lk1, _lk2 = st.columns(2)
            with _lk1:
                # Distancia — opciones comunes + personalizado
                _km_opts = ["0-5 km", "5-15 km", "15-30 km", "30-60 km", "60+ km"]
                _km_pre  = float(pre.get("km", 5.0))
                _km_pre_s = (
                    "0-5 km"   if _km_pre <= 5 else
                    "5-15 km"  if _km_pre <= 15 else
                    "15-30 km" if _km_pre <= 30 else
                    "30-60 km" if _km_pre <= 60 else "60+ km"
                )
                _km_rango = st.pills("Distancia al destino", _km_opts, default=_km_pre_s, key="p3_km_pills")
                _km_defaults = {"0-5 km": 3, "5-15 km": 10, "15-30 km": 22, "30-60 km": 45, "60+ km": 80}
                km = st.number_input(
                    "Km exactos (un trayecto)", min_value=0.0,
                    value=float(_sp().get("cdir_km", _km_defaults.get(_km_rango or "5-15 km", _km_pre))),
                    step=1.0,
                    key="cb_cdir_km",
                    on_change=_cb_cdir_vehiculo_km,
                )

            with _lk2:
                # Peajes — segmented control 0-4+
                _pj_opts = ["0", "1", "2", "3", "4+"]
                _pj_pre  = int(pre.get("peajes", 0))
                # FIX-1: garantizar que el default exista en la lista de opciones
                _pj_pre_s = str(_pj_pre) if str(_pj_pre) in _pj_opts else ("4+" if _pj_pre > 3 else _pj_opts[0])
                _pj_sel  = st.pills("Peajes ida+vuelta", _pj_opts, default=_pj_pre_s, key="p3_peajes_pills")
                if _pj_sel == "4+" or _pj_sel is None:
                    peajes = st.number_input("Peajes (exacto)", min_value=0, value=_pj_pre, step=1, key="p3_peajes_custom")
                else:
                    peajes = int(_pj_sel)

        # ── Foráneo ──────────────────────────────────────────────────
        with st.container(border=True):
            st.markdown("**✈️ ¿El proyecto es fuera de Barranquilla?**")
            foraneo_activo = st.toggle(
                "Sí, proyecto en otra ciudad",
                value=_sp().get("cdir_foraneo", pre.get("foraneo_activo", False)),
                key="cb_cdir_foraneo",
                on_change=_cb_cdir_foraneo,
            )
            viaticos_activos = False; tipo_aloj = "pueblo"; noches = 0
            if foraneo_activo:
                _fa1, _fa2, _fa3 = st.columns(3)
                with _fa1:
                    viaticos_activos = st.toggle(
                        "Incluir viáticos",
                        value=_sp().get("cdir_viaticos_activos", pre.get("viaticos_activos", False)),
                        key="cb_cdir_viaticos_activos",
                        on_change=_cb_cdir_viaticos_activos,
                    )
                with _fa2:
                    _sp_tipo_aloj = _sp().get("cdir_tipo_aloj", pre.get("tipo_aloj", "pueblo"))
                    tipo_aloj = ALOJAMIENTO[st.selectbox(
                        "Destino", list(ALOJAMIENTO.keys()),
                        index=list(ALOJAMIENTO.keys()).index(next((k for k, v in ALOJAMIENTO.items() if v == _sp_tipo_aloj), list(ALOJAMIENTO.keys())[0])),
                        key="cb_cdir_tipo_aloj",
                        on_change=_cb_cdir_tipo_aloj,
                    )]
                with _fa3:
                    _nc_opts  = ["1", "2", "3", "4", "5+"]
                    _nc_pre   = int(pre.get("noches", 1))
                    # FIX-1: garantizar que el default exista en la lista de opciones
                    _nc_pre_s = str(_nc_pre) if str(_nc_pre) in _nc_opts else ("5+" if _nc_pre > 4 else _nc_opts[0])
                    _nc_sel   = st.pills("Noches", _nc_opts, default=_nc_pre_s, key="p3_noches_pills")
                    if _nc_sel == "5+" or _nc_sel is None:
                        noches = st.number_input("Noches (exacto)", min_value=0, value=_nc_pre, step=1, key="p3_noches_custom")
                    else:
                        noches = int(_nc_sel)

        # ── Adicionales ──────────────────────────────────────────────
        with st.container(border=True):
            st.markdown("**🔧 Costos adicionales** *(silicona, impermeabilizante, etc.)*")
            _ADICIONALES_ACT = get_adicionales()
            adicionales_activos = st.toggle(
                "Agregar costos adicionales",
                value=_sp().get("cdir_adicionales_activos", pre.get("adicionales_activos", False)),
                key="cb_cdir_adicionales_activos",
                on_change=_cb_cdir_adicionales_activos,
            )
            cantidades_add = pre.get("cantidades_add", [0.0]*len(_ADICIONALES_ACT)) if pre.get("adicionales_activos") else [0.0]*len(_ADICIONALES_ACT)
            while len(cantidades_add) < len(_ADICIONALES_ACT):
                cantidades_add.append(0.0)

            if adicionales_activos:
                for i, a in enumerate(_ADICIONALES_ACT):
                    _ac1, _ac2 = st.columns([3.5, 0.5])
                    _ac1.markdown(f"<div style='font-size:0.85rem;padding:8px 0'>{a['concepto']} — <strong>{numero_completo(a.get(etapa,0))}/{a['unidad']}</strong></div>", unsafe_allow_html=True)
                    cantidades_add[i] = _ac2.number_input("Cant.", min_value=0.0, value=float(cantidades_add[i]),
                                                           step=1.0, key=f"add_{i}", label_visibility="collapsed")

        # ── IVA ──────────────────────────────────────────────────────
        with st.container(border=True):
            st.markdown("**🧾 IVA en la cotización**")
            _iv1, _iv2 = st.columns([1, 1.5])
            with _iv1:
                incluir_iva = st.toggle(
                    "Incluir IVA 19%",
                    value=_sp().get("cdir_incluir_iva", pre.get("incluir_iva", True)),
                    key="cb_cdir_incluir_iva",
                    on_change=_cb_cdir_incluir_iva,
                    help="Activa si tu empresa es responsable del régimen común."
                )
            with _iv2:
                if incluir_iva:
                    st.info("IVA 19% sobre el total de la cotización.", icon="🧾")
                else:
                    st.warning("Sin IVA — aplica régimen simplificado.", icon="⚠️")

        # Guardar en pre
        _etapa_labels = {v: k for k, v in ETAPAS_OBRA.items()}
        st.session_state.pre = {
            **st.session_state.pre,
            "agente_externo_taller": agente_ext_taller,
            "vehiculo_entrega": vehiculo, "km": km, "peajes": peajes,
            "foraneo_activo": foraneo_activo, "viaticos_activos": viaticos_activos,
            "tipo_aloj": tipo_aloj, "noches": noches,
            "adicionales_activos": adicionales_activos, "cantidades_add": cantidades_add,
            "incluir_iva": incluir_iva,
        }
        # ── store_permanente sync: logística/adicionales/IVA ──────────────────
        _sp_set("cdir_agente_externo", agente_ext_taller)
        _sp_set("cdir_vehiculo", vehiculo)
        _sp_set("cdir_km", km)
        _sp_set("cdir_peajes", peajes)
        _sp_set("cdir_foraneo", foraneo_activo)
        _sp_set("cdir_viaticos_activos", viaticos_activos)
        _sp_set("cdir_tipo_aloj", tipo_aloj)
        _sp_set("cdir_noches", noches)
        _sp_set("cdir_adicionales_activos", adicionales_activos)
        _sp_set("cdir_cantidades_add", cantidades_add)
        _sp_set("cdir_incluir_iva", incluir_iva)

    # ════════════════════════════════════════════════════════════════════
    # PASO 4 — CALCULAR (trigger automático al llegar a este paso)
    # ════════════════════════════════════════════════════════════════════
    elif paso == 4:
        # Reconstruir todos los valores desde session_state.pre y materiales/piezas
        _mats   = st.session_state.get("materiales_proyecto", [])
        _piezas = st.session_state.get("piezas", pre.get("piezas", []))

        cat_sel            = _mats[0]["cat"]    if _mats else pre.get("categoria","Mármol")
        _refs_raw2  = [m["ref"] or m["cat"] for m in _mats]
        _refs_unicas2 = list(dict.fromkeys(_refs_raw2))  # Preserva orden, elimina duplicados
        referencia         = " + ".join(_refs_unicas2) if len(_refs_unicas2) > 1 else (_refs_unicas2[0] if _refs_unicas2 else "")
        precio_m2          = _mats[0]["precio_m2"] if _mats else pre.get("precio_m2", 220_000)
        precio_m2_efectivo = precio_m2
        area_placa         = sum(m["area_placa"] for m in _mats) if _mats else pre.get("area_placa_comprada", 5.94)

        m2_real           = sum(ml_a_m2(float(p.get("ml",0)), float(p.get("ancho_custom",0.60))) for p in _piezas) or pre.get("m2_proyecto", 4.0)
        m2_cortados_total = pre.get("m2_cortados_input", m2_real)
        m2_usados         = pre.get("m2_usados", m2_real)
        margen_pct        = pre.get("margen_pct", 40)

        _etapa_label = pre.get("etapa_label", list(ETAPAS_OBRA.keys())[0])
        etapa        = ETAPAS_OBRA.get(_etapa_label, list(ETAPAS_OBRA.values())[0])
        dias         = pre.get("dias_obra", 2)
        personas     = pre.get("personas", 2)
        tipo         = pre.get("tipo_proyecto","Mesón")
        nombre_cliente = pre.get("nombre_cliente","")
        zocalo_activo  = pre.get("zocalo_activo", False)
        zocalo_ml      = pre.get("zocalo_ml", 0.0)
        agente_ext_taller = pre.get("agente_externo_taller", False)
        vehiculo          = pre.get("vehiculo_entrega","frontier")
        km                = pre.get("km", 5.0)
        peajes            = pre.get("peajes", 0)
        foraneo_activo    = pre.get("foraneo_activo", False)
        viaticos_activos  = pre.get("viaticos_activos", False)
        tipo_aloj         = pre.get("tipo_aloj","pueblo")
        noches            = pre.get("noches", 0)
        adicionales_activos = pre.get("adicionales_activos", False)
        cantidades_add    = pre.get("cantidades_add", [])
        incluir_iva       = pre.get("incluir_iva", True)
        tipos_sel         = pre.get("tipos_proyecto", ["Mesón"])
        _ADICIONALES_ACT  = get_adicionales()

        # ── FIX-1/3 Snapshot profundo — captura TODO el estado vital ─────────────
        # Incluye listas dinámicas, paso del wizard y retal_ids por material,
        # de modo que un F5 en cualquier paso restaura la sesión al 100%.
        _etapa_labels = {v: k for k, v in ETAPAS_OBRA.items()}
        # Recopilar retal_ids activos por índice de material
        _retal_ids_snap = {
            k: v for k, v in st.session_state.items()
            if k.startswith("retal_id_") and v
        }
        _pre_snapshot = {
            # ── Inputs básicos ────────────────────────────────────────────────
            "materiales_proyecto": st.session_state.get("materiales_proyecto", []),
            "tipos_proyecto": tipos_sel, "tipo_proyecto": tipo,
            "etapa_label": _etapa_labels.get(etapa, list(ETAPAS_OBRA.keys())[0]),
            "dias_obra": dias, "personas": personas, "nombre_cliente": nombre_cliente,
            "zocalo_activo": zocalo_activo, "zocalo_ml": zocalo_ml,
            "perfil_desperdicio": pre.get("perfil_desperdicio", ""),
            "extra_corte": pre.get("extra_corte", round(m2_real * 0.15, 2)),
            "m2_proyecto": m2_real, "m2_cortados_input": m2_cortados_total,
            "m2_usados": m2_usados, "margen_pct": margen_pct,
            "agente_externo_taller": agente_ext_taller,
            "vehiculo_entrega": vehiculo, "km": km, "peajes": peajes,
            "foraneo_activo": foraneo_activo, "viaticos_activos": viaticos_activos,
            "tipo_aloj": tipo_aloj, "noches": noches,
            "adicionales_activos": adicionales_activos, "cantidades_add": cantidades_add,
            "incluir_iva": incluir_iva,
            # ── Estructuras dinámicas (Caja Negra) ────────────────────────────
            "piezas":             _piezas,                                  # lista completa de piezas
            "cdir_paso":          st.session_state.get("cdir_paso", 0),     # paso actual del wizard
            "editando_id":        st.session_state.get("editando_id"),      # modo edición activo
            **_retal_ids_snap,                                               # retal_id_0, retal_id_1…
        }
        st.session_state.pre = _pre_snapshot

        # ── Autoguardado en BD en CADA render del paso 4 (hash-gated) ────────
        # No espera al clic de Calcular — persiste en cada ciclo de renderizado.
        try:
            _nuevo_hash = hash(json.dumps(_pre_snapshot, sort_keys=True, default=str))
            if _nuevo_hash != st.session_state.get("last_pre_hash"):
                _guardar_config(_clave_borrador_cdir(), _pre_snapshot)
                st.session_state["last_pre_hash"] = _nuevo_hash
        except Exception:
            pass

        # ── Spinner de cálculo ────────────────────────────────────────
        if not st.session_state.cotizacion or st.session_state.get("_recalcular_paso4"):
            with st.spinner("Calculando costos..."):
                _ml_tot = sum(p.get("ml", 0) for p in _piezas)
                resultado = calcular_cotizacion_directa(
                    categoria=cat_sel, referencia=referencia, precio_m2=precio_m2_efectivo,
                    area_placa_comprada=area_placa, m2_real=m2_real, m2_cortados=m2_cortados_total,
                    m2_usados=m2_usados, margen_pct=margen_pct, dias=dias, personas=personas,
                    zocalo_activo=zocalo_activo, zocalo_ml=zocalo_ml,
                    agente_externo_taller=agente_ext_taller, vehiculo_entrega=vehiculo,
                    km=km, num_peajes=peajes, foraneo_activo=foraneo_activo,
                    viaticos_activos=viaticos_activos, tipo_aloj=tipo_aloj, noches=noches,
                    adicionales_activos=adicionales_activos, cantidades_add=cantidades_add,
                    etapa=etapa, adicionales_lista=_ADICIONALES_ACT,
                    tipo_proyecto=tipo, nombre_cliente=nombre_cliente,
                    ml_proyecto=_ml_tot,
                    logistica_override=st.session_state.get("logistica_custom"),
                    vehiculos_custom={**VEHICULOS_CONFIG, **(st.session_state.get("vehiculos_custom") or {})},
                    tarifas_override=st.session_state.get("tarifas_custom"),
                )
                resultado["_estado_guardado"] = _pre_snapshot
                resultado["incluir_iva"]      = incluir_iva
                st.session_state.cotizacion   = resultado
                st.session_state["_recalcular_paso4"] = False

        r         = st.session_state.cotizacion
        _iva_act  = r.get("incluir_iva", incluir_iva)
        _iva_mont = r["precio_sugerido"] * 0.19 if _iva_act else 0.0
        _pf       = r["precio_sugerido"] + _iva_mont

        import random as _rand
        _num_auto = f"COT-{_hoy().strftime('%Y%m%d')}-{_rand.randint(100,999)}"
        if "cdir_num_auto" not in st.session_state:
            st.session_state.cdir_num_auto = _num_auto

        # ── Hero card resultado ───────────────────────────────────────
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#0D2137 0%,#1B5FA8 100%);
                    border-radius:14px;padding:28px 36px;margin-bottom:20px;color:white;">
          <div style="color:#C9A84C;font-size:0.68rem;text-transform:uppercase;letter-spacing:0.14em;font-weight:700;margin-bottom:8px">
            Precio de venta sugerido {"(sin IVA)" if _iva_act else ""}
          </div>
          <div style="font-size:3.2rem;font-weight:900;font-family:'Playfair Display',serif;line-height:1;margin-bottom:8px">
            {numero_completo(r["precio_sugerido"])}
          </div>
          <div style="opacity:0.8;font-size:0.85rem">
            Margen: {r["margen_pct"]:.0f}% &nbsp;·&nbsp; Utilidad: {numero_completo(r["utilidad"])}
          </div>
          {"" if not _iva_act else f'<div style="margin-top:10px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.2)"><span style="color:#C9A84C;font-weight:700">+ IVA 19%: {numero_completo(_iva_mont)}</span> &nbsp;→&nbsp; <span style="font-weight:900">Total: {numero_completo(_pf)}</span></div>'}
        </div>""", unsafe_allow_html=True)

        # Desglose rápido
        _col_d, _col_m = st.columns([1, 1])
        with _col_d:
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
            bloque_costos(_items_d, "TOTAL CON IVA" if _iva_act else "PRECIO TOTAL", _pf)
        with _col_m:
            c1m, c2m = st.columns(2)
            c1m.metric("Aprovechamiento", f"{r['aprovechamiento']:.1f}%", f"Retal: {fmt_m2(r['retal'])}")
            c2m.metric("Costo/m²", numero_completo(r["costo_total"] / max(r["m2_real"], 0.001)))
            st.markdown("<div style='font-weight:700;margin:14px 0 8px'>Simulador de margen</div>", unsafe_allow_html=True)
            _sim_m = st.slider("Margen (%)", 5, 80, int(r["margen_pct"]), 1, key="sim_slider")
            _sim_p = r["costo_total"] / (1 - _sim_m / 100)
            _sim_ut = _sim_p - r["costo_total"]
            _sim_iva = _sim_p * 0.19 if _iva_act else 0.0
            st.markdown(
                f"""<div style="background:var(--secondary-background-color);border:1px solid var(--border-color);
                border-radius:10px;padding:12px 16px">
                <div style="display:flex;justify-content:space-between;align-items:center{";margin-bottom:6px" if _iva_act else ""}">
                  <span style="font-size:0.75rem;font-weight:700;opacity:0.55;text-transform:uppercase">{"Sin IVA" if _iva_act else "Precio total"}</span>
                  <span style="font-size:1.1rem;font-weight:900;color:#1B5FA8">{numero_completo(_sim_p)}</span>
                </div>
                {"" if not _iva_act else f'<div style="display:flex;justify-content:space-between;align-items:center;border-top:1px solid var(--border-color);padding-top:6px;margin-bottom:4px"><span style="font-size:0.75rem;font-weight:700;opacity:0.55;text-transform:uppercase">Con IVA 19%</span><span style="font-size:1.1rem;font-weight:900;color:#C9A84C">{numero_completo(_sim_p + _sim_iva)}</span></div>'}
                <div style="font-size:0.72rem;opacity:0.5">Utilidad: {numero_completo(_sim_ut)} · Margen: {_sim_m}%</div>
                </div>""",
                unsafe_allow_html=True
            )

        st.markdown("---")

        # ── Guardar en historial ───────────────────────────────────────
        _ya_guardada = st.session_state.get("_cotiz_guardada", False)
        _editando_id  = st.session_state.get("editando_id")
        _editando_num = st.session_state.get("editando_num","")

        if _editando_id:
            alerta(f"**Modo edición** — modificando cotización **{_editando_num}**.", "info")
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
                _actualizar_cotizacion(_editando_id, _editando_num, nombre_cliente, r)
                st.session_state.pop("editando_id", None)
                st.session_state.pop("editando_num", None)
                st.session_state["_cotiz_guardada_num"] = _editando_num
                st.session_state["_cotiz_guardada"] = True
                st.session_state.cdir_success = True
                st.rerun()
            if _btn_nueva:
                _guardar_cotizacion(st.session_state.cdir_num_auto, nombre_cliente, r)
                st.session_state.pop("editando_id", None)
                st.session_state.pop("editando_num", None)
                st.session_state["_cotiz_guardada_num"] = st.session_state.cdir_num_auto
                st.session_state["_cotiz_guardada"] = True
                st.session_state.cdir_success = True
                st.rerun()

        elif not _ya_guardada:
            st.markdown("""<div style="background:var(--secondary-background-color);border:1px solid var(--border-color);
            border-radius:12px;padding:18px 22px;margin-bottom:4px">
            <div style="font-size:0.75rem;font-weight:700;opacity:0.5;text-transform:uppercase;margin-bottom:4px">💾 ¿Guardar en historial?</div>
            <div style="font-size:0.88rem;opacity:0.75;margin-bottom:12px">
            Si es una cotización real para un cliente, guárdala. Si es una prueba, puedes omitirlo.
            </div></div>""", unsafe_allow_html=True)

            _gc1, _gc2, _gc3 = st.columns([2, 1.5, 1])
            with _gc1:
                _num_guardar = st.text_input(
                    "Número de cotización", value=st.session_state.get("cdir_num_auto", _num_auto),
                    key="num_guardar_hist", label_visibility="collapsed"
                )
            with _gc2:
                if st.button("💾 Guardar en historial", type="primary", use_container_width=True, key="btn_guardar_hist"):
                    try:
                        _guardar_cotizacion(_num_guardar, r.get("nombre_cliente","Sin nombre"), r)
                        for _mi, _md in enumerate(st.session_state.get("materiales_proyecto",[])):
                            if _md.get("es_retal") and _md.get("retal_id"):
                                try:
                                    _marcar_retal_usado(_md["retal_id"], _md.get("area_placa",0))
                                    st.session_state.pop(f"usar_retal_{_mi}", None)
                                except Exception:
                                    pass
                        st.session_state["_cotiz_guardada"]     = True
                        st.session_state["_cotiz_guardada_num"] = _num_guardar
                        st.session_state.cdir_success = True
                        st.rerun()
                    except Exception as _eg:
                        st.error(f"Error al guardar: {_eg}")
            with _gc3:
                if st.button("✕ Solo borrador", use_container_width=True, key="btn_no_guardar_hist"):
                    st.session_state["_cotiz_guardada"]     = True
                    st.session_state["_cotiz_guardada_num"] = ""
                    st.session_state.cdir_success = True
                    st.toast("Cotización calculada como borrador.", icon="📋")
                    st.rerun()

        else:
            # Ya guardada — ir directo a success screen
            st.session_state.cdir_success = True
            st.rerun()

    # ════════════════════════════════════════════════════════════════════
    # NAVEGACIÓN — botones Atrás / Siguiente (solo pasos 0-3)
    # ════════════════════════════════════════════════════════════════════
    if not st.session_state.get("cdir_success") and paso < N_PASOS - 1:
        st.markdown("---")
        _nav_l, _nav_r = st.columns([1, 1])

        # Validaciones mínimas por paso
        _puede_continuar = True
        _msg_validacion  = ""

        if paso == 0:
            _mats_v = st.session_state.get("materiales_proyecto", [])
            if not _mats_v or all(m.get("area_placa", 0) <= 0 for m in _mats_v):
                _puede_continuar = False
                _msg_validacion  = "Agrega al menos un material con área válida para continuar."

        elif paso == 1:
            _piezas_v = st.session_state.get("piezas", [])
            _m2_v = sum(ml_a_m2(float(p.get("ml",0)), float(p.get("ancho_custom",0.60))) for p in _piezas_v)
            if _m2_v <= 0:
                _puede_continuar = False
                _msg_validacion  = "Agrega al menos una pieza con dimensiones válidas."

        with _nav_l:
            if paso > 0:
                if st.button("← Atrás", use_container_width=True, key="btn_wizard_back"):
                    st.session_state.cdir_paso -= 1
                    # ── store_permanente: persistir paso (sobrevive nav) ──────
                    _sp_set("cdir_paso", st.session_state.cdir_paso)
                    _sp_commit_borrador()
                    st.rerun()

        with _nav_r:
            if not _puede_continuar:
                st.warning(_msg_validacion)
            else:
                _lbl_sig = "Calcular cotización →" if paso == N_PASOS - 2 else "Siguiente →"
                if st.button(_lbl_sig, type="primary", use_container_width=True, key="btn_wizard_next"):
                    st.session_state.cdir_paso += 1
                    # ── store_permanente: persistir paso (sobrevive nav) ──────
                    _sp_set("cdir_paso", st.session_state.cdir_paso)
                    _sp_commit_borrador()
                    if st.session_state.cdir_paso == N_PASOS - 1:
                        # Forzar recálculo al llegar al paso de resultado
                        st.session_state["_recalcular_paso4"] = True
                    st.rerun()


elif pagina == "Cotizacion AIU":

    # ══════════════════════════════════════════════════════════════════
    # WIZARD COTIZACIÓN AIU — 3 pasos
    # PASOS:
    #   0 — Items del contrato (tabla de ítems + Costo Directo)
    #   1 — Porcentajes AIU + Logística + Foráneo
    #   2 — Resultado / Success Screen
    # ══════════════════════════════════════════════════════════════════

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

    # Restaurar borrador AIU
    # FIX-1 Multi-Tenant: clave dinámica por usuario (_clave_borrador_aiu)
    if not st.session_state.pre and not st.session_state.get("_borrador_aiu_restaurado"):
        try:
            _borrador_aiu = _leer_config(_clave_borrador_aiu())
            if _borrador_aiu:
                st.session_state.pre = _borrador_aiu
                if _borrador_aiu.get("aiu_items"):
                    st.session_state.aiu_items = _borrador_aiu["aiu_items"]
                alerta("📋 Se restauró tu último cálculo AIU.", "info")
        except Exception:
            pass
        st.session_state["_borrador_aiu_restaurado"] = True

    # ════════════════════════════════════════════════════════════════════
    # PANTALLA DE ÉXITO AIU
    # ════════════════════════════════════════════════════════════════════
    if st.session_state.get("aiu_success") and st.session_state.cotizacion and \
       st.session_state.cotizacion.get("tipo_proyecto") == "Licitación AIU":

        r_aiu     = st.session_state.cotizacion
        _num_g_aiu = st.session_state.get("_aiu_guardada_num", "")
        nombre_cliente_aiu = st.session_state.pre.get("nombre_cliente","")
        pct_a = r_aiu.get("pct_a", 2.0)
        pct_i = r_aiu.get("pct_i", 2.0)
        pct_u = r_aiu.get("pct_u", 5.0)

        # Hero card
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#0D2137 0%,#1B5FA8 100%);
                    border-radius:18px;padding:40px 44px 32px;margin-bottom:24px;color:white;
                    box-shadow:0 8px 32px rgba(27,95,168,0.35)">
          <div style="display:flex;align-items:center;gap:16px;margin-bottom:20px">
            <div style="width:52px;height:52px;background:rgba(201,168,76,0.25);border-radius:50%;
                        display:flex;align-items:center;justify-content:center;font-size:1.6rem">✅</div>
            <div>
              <div style="font-size:0.7rem;letter-spacing:0.14em;text-transform:uppercase;
                          color:#C9A84C;font-weight:700;margin-bottom:2px">OFERTA AIU FINALIZADA</div>
              <div style="font-size:1.1rem;font-weight:700">{nombre_cliente_aiu or "Sin nombre de proyecto"}</div>
            </div>
          </div>
          <div style="font-size:0.72rem;text-transform:uppercase;letter-spacing:0.12em;color:rgba(255,255,255,0.55);font-weight:700;margin-bottom:6px">Precio total del contrato (A+I+U+IVA)</div>
          <div style="font-size:3.8rem;font-weight:900;font-family:'Playfair Display',serif;line-height:1;margin-bottom:8px">
            {numero_completo(r_aiu["precio_total"])}
          </div>
          <div style="opacity:0.75;font-size:0.9rem">
            Margen efectivo: {r_aiu["margen_pct"]:.1f}% &nbsp;·&nbsp;
            A({pct_a}%) + I({pct_i}%) + U({pct_u}%) + IVA
          </div>
        </div>""", unsafe_allow_html=True)

        _iva_lbl_sc = "IVA 19% (solo sobre Utilidad)" if r_aiu.get("incluir_iva", True)                       else "IVA (Exento — Régimen Simplificado)"
        with st.expander("📊 Ver desglose AIU", expanded=False):
            bloque_costos([
                ("Costo Directo (CD)",        r_aiu["cd"]),
                (f"A — Administración ({pct_a}%)", r_aiu["val_a"]),
                (f"I — Imprevistos ({pct_i}%)",    r_aiu["val_i"]),
                (f"U — Utilidad ({pct_u}%)",        r_aiu["val_u"]),
                (_iva_lbl_sc,                  r_aiu["val_iva"]),
                ("Logística",                  r_aiu["logistica"]),
                ("Viáticos",                   r_aiu.get("viaticos", 0)),
            ], "PRECIO TOTAL CONTRATO", r_aiu["precio_total"])

        st.markdown("---")
        st.markdown("### 📄 Documentos institucionales")
        from generador_pdf import generar_pdf_cotizacion_aiu, generar_cuenta_cobro

        _num_pre_aiu = st.session_state.get("_aiu_guardada_num") or f"AIU-{_hoy().strftime('%Y')}-001"

        with st.container(border=True):
            st.markdown("**Oferta AIU**")
            _ap1, _ap2 = st.columns([1.5, 1])
            with _ap1:
                num_cot_aiu = st.text_input("Número de oferta", value=f"OFE-AIU-{_hoy().strftime('%Y')}-001", key="num_cot_aiu_success")
            with _ap2:
                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                if st.button("📄 Generar Oferta AIU PDF", type="primary", use_container_width=True, key="btn_pdf_aiu"):
                    # FIX-2d: spinner durante la generación del buffer ReportLab
                    with st.spinner("Generando documento corporativo..."):
                        pdf_bytes = generar_pdf_cotizacion_aiu(
                            r_aiu, numero=num_cot_aiu,
                            empresa_info=st.session_state.empresa_info,
                            logo_bytes=st.session_state.logo_bytes,
                            incluir_iva=r_aiu.get("incluir_iva", True),
                        )
                    st.download_button("⬇ Descargar Oferta AIU", pdf_bytes,
                                       file_name=f"{num_cot_aiu}.pdf", mime="application/pdf",
                                       use_container_width=True, key="dl_pdf_aiu")

        with st.container(border=True):
            st.markdown("**Cuenta de cobro / Factura**")
            _ac1, _ac2 = st.columns(2)
            with _ac1:
                num_cc_aiu  = st.text_input("Número de cuenta", value=f"FAC-AIU-{_hoy().strftime('%Y')}-001", key="num_cc_aiu_success")
                nom_pag_aiu = st.text_input("Facturar a:", value=nombre_cliente_aiu, key="nom_pag_aiu_success")
            with _ac2:
                nit_pag_aiu = st.text_input("NIT / Rut", value="", key="nit_pag_aiu_success")
            if st.button("📄 Generar Cobro AIU PDF", type="primary", use_container_width=True, key="btn_pdf_cc_aiu"):
                datos_pag = {"nombre": nom_pag_aiu, "nit": nit_pag_aiu, "direccion": ""}
                # FIX-2e: spinner durante la generación del buffer ReportLab
                with st.spinner("Generando documento corporativo..."):
                    cc_bytes  = generar_cuenta_cobro(r_aiu, st.session_state.empresa_info.copy(), datos_pag,
                                                      numero=num_cc_aiu, logo_bytes=st.session_state.logo_bytes)
                st.download_button("⬇ Descargar Cobro AIU", cc_bytes,
                                   file_name=f"{num_cc_aiu}.pdf", mime="application/pdf",
                                   use_container_width=True, key="dl_pdf_cc_aiu")

        st.markdown("---")
        _an1, _an2 = st.columns(2)
        with _an1:
            if st.button("🆕 Nueva cotización AIU", use_container_width=True, type="primary"):
                for k in ["cotizacion", "pre", "aiu_items", "_aiu_guardada", "_aiu_guardada_num",
                          "_aiu_num_sugerido", "_borrador_aiu_restaurado"]:
                    st.session_state.pop(k, None)
                st.session_state.aiu_paso    = 0
                st.session_state.aiu_success = False
                # Reiniciar ítems a defaults
                st.session_state.aiu_items = [
                    {"desc": "Material pétreo (suministro)",       "und": "m²",  "cant": 10.0, "punit": 250_000},
                    {"desc": "Mano de obra corte y elaboración",   "und": "m²",  "cant": 10.0, "punit": 100_000},
                    {"desc": "Instalación y nivelación",           "und": "m²",  "cant": 10.0, "punit":  50_000},
                    {"desc": "Insumos (disco, adhesivo, silicona)","und": "glb", "cant":  1.0, "punit": 150_000},
                ]
                st.rerun()
        with _an2:
            if st.button("✏️ Editar esta cotización AIU", use_container_width=True):
                st.session_state.aiu_success = False
                st.session_state.aiu_paso    = 0
                st.rerun()

        st.stop()

    # ════════════════════════════════════════════════════════════════════
    # BARRA DE PROGRESO AIU
    # ════════════════════════════════════════════════════════════════════
    paso_aiu = st.session_state.aiu_paso

    _pasos_aiu_html = ""
    for _i, _p in enumerate(WIZARD_AIU_PASOS):
        if _i < paso_aiu:
            _ds = "background:#1B5FA8;color:white;border:2px solid #1B5FA8"
            _ls = "color:#1B5FA8;font-weight:700"
            _dc = "&#10003;"
            _cb = "#1B5FA8"
            _co = "1"
        elif _i == paso_aiu:
            _ds = "background:#1B5FA8;color:white;border:2px solid #1B5FA8;box-shadow:0 0 0 4px rgba(27,95,168,0.18)"
            _ls = "color:#1B5FA8;font-weight:900"
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
        + _pasos_aiu_html +
        '</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        f"<h2 style='font-family:Playfair Display,serif;margin-bottom:2px'>"
        f"{WIZARD_AIU_PASOS[paso_aiu]['icono']} {WIZARD_AIU_PASOS[paso_aiu]['label']}</h2>"
        f"<p style='opacity:0.6;font-size:0.85rem;margin-bottom:20px'>Paso {paso_aiu+1} de {N_AIU}</p>",
        unsafe_allow_html=True
    )

    # ── Navegación no-lineal AIU: pills de salto directo entre pasos ─────────
    _pill_labels_aiu = [
        f"{p['icono']} {i+1}. {p['label']}"
        for i, p in enumerate(WIZARD_AIU_PASOS)
    ]
    _pill_sel_aiu = st.pills(
        "Ir al paso AIU",
        options=_pill_labels_aiu,
        default=_pill_labels_aiu[paso_aiu],
        key=f"nav_pills_aiu_{paso_aiu}",
        label_visibility="collapsed",
    )
    if _pill_sel_aiu is not None:
        _paso_aiu_pill = _pill_labels_aiu.index(_pill_sel_aiu)
        if _paso_aiu_pill != paso_aiu:
            st.session_state.aiu_paso = _paso_aiu_pill
            st.rerun()

    # ════════════════════════════════════════════════════════════════════
    # PASO AIU 0 — ÍTEMS DEL CONTRATO
    # ════════════════════════════════════════════════════════════════════
    if paso_aiu == 0:
        seccion_titulo("Ítems del contrato", "Lista los trabajos y materiales que incluye la obra")
        nombre_cliente_aiu = st.text_input(
            "Nombre de la constructora o proyecto",
            placeholder="Ej: Constructora ABC S.A.S.",
            value=st.session_state.pre.get("nombre_cliente",""),
            key="aiu_nombre_cliente"
        )

        with st.expander("❓ ¿Cómo funciona la tabla de ítems?", expanded=False):
            st.markdown("""
Cada fila es un ítem del contrato. La app suma todos los ítems para calcular el **Costo Directo (CD)**, 
que es la base sobre la que se aplican los porcentajes A, I y U.

| Campo | Qué ingresar |
|---|---|
| Descripción | Nombre del trabajo o material |
| Unidad | m², ml, glb (global), und |
| Cantidad | Cuántas unidades |
| Precio unitario | Costo por unidad (COP) |
            """)

        # ── Cards mobile-first — un card por ítem ─────────────────────────────
        nuevos_items = []
        cd_total     = 0.0
        for idx, it in enumerate(st.session_state.aiu_items):
            with st.container(border=True):
                # ── Fila 1: descripción + botón eliminar ─────────────────────
                _row1a, _row1b = st.columns([5.5, 0.8])
                with _row1a:
                    desc = st.text_input(
                        "📝 Descripción",
                        value=it["desc"],
                        key=f"aiu_d_{idx}",
                        placeholder="Ej: Suministro e instalación mármol",
                    )
                with _row1b:
                    st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
                    _can_del = len(st.session_state.aiu_items) > 1
                    if st.button("✕", key=f"aiu_del_{idx}",
                                 help="Eliminar ítem", disabled=not _can_del):
                        _sp_eliminar_item_aiu(idx)
                        st.rerun()
                # ── Fila 2: unidad | cantidad | precio unitario ──────────────
                _row2a, _row2b, _row2c = st.columns([1.5, 1.5, 3])
                with _row2a:
                    und = st.text_input("Unidad", value=it["und"],
                                        key=f"aiu_u_{idx}", placeholder="glb / m² / ml")
                with _row2b:
                    cant = st.number_input("Cantidad", value=float(it["cant"]),
                                           min_value=0.0, step=1.0, key=f"aiu_c_{idx}")
                with _row2c:
                    punit = st.number_input("Precio unitario (COP)",
                                            value=float(it["punit"]),
                                            min_value=0.0, step=5_000.0, format="%.0f",
                                            key=f"aiu_p_{idx}")
                    st.markdown(f"<div style='margin-top:-12px; margin-bottom:10px; font-size:0.85rem; color:#1B5FA8; font-weight:600;'>💰 Equivalencia: {cop(punit)}</div>", unsafe_allow_html=True)
                sub = cant * punit
                cd_total += sub
                st.markdown(
                    f'<div style="font-size:0.78rem;font-weight:700;color:#1B5FA8;'
                    f'text-align:right;margin-top:2px">Subtotal: {numero_completo(sub)}</div>',
                    unsafe_allow_html=True
                )
            nuevos_items.append({"desc": desc, "und": und, "cant": cant, "punit": punit})
        # Sync AIU items to store_permanente (event-driven)
        _sp_sync_items_aiu(nuevos_items)
        st.session_state.aiu_items = nuevos_items

        if st.button("＋ Agregar ítem", use_container_width=True):
            _sp_agregar_item_aiu()
            st.rerun()

        st.markdown(
            f"<div style='background:var(--secondary-background-color);border:1px solid #1B5FA8;"
            f"border-left:4px solid #1B5FA8;border-radius:8px;padding:12px 18px;margin-top:16px;"
            f"font-size:1.1rem;font-weight:900;color:#1B5FA8'>Costo Directo total: {numero_completo(cd_total)}</div>",
            unsafe_allow_html=True
        )

        # Guardar CD
        st.session_state.pre = {**st.session_state.pre, "nombre_cliente": nombre_cliente_aiu, "cd_total": cd_total}

    # ════════════════════════════════════════════════════════════════════
    # PASO AIU 1 — PORCENTAJES AIU + LOGÍSTICA
    # ════════════════════════════════════════════════════════════════════
    elif paso_aiu == 1:
        cd_total = st.session_state.pre.get("cd_total", sum(it["cant"]*it["punit"] for it in st.session_state.aiu_items))
        nombre_cliente_aiu = st.session_state.pre.get("nombre_cliente","")

        seccion_titulo("Porcentajes AIU y logística",
                       "Define administración, imprevistos y utilidad sobre el Costo Directo")

        with st.expander("📖 ¿Qué es AIU?", expanded=False):
            st.markdown("""
**AIU = Administración + Imprevistos + Utilidad** — estructura para contratos de construcción en Colombia.

| Componente | ¿Qué incluye? | Valor típico |
|---|---|---|
| **A** | Gastos de oficina, seguros, permisos | 1.5% – 3% |
| **I** | Colchón para imprevistos | 1% – 3% |
| **U** | Tu ganancia | 5% – 10% |

El IVA (19%) se aplica **solo sobre la Utilidad (U)** — Decreto 1372/92 Colombia.
            """)

        # ── Porcentajes con segmented controls ───────────────────────
        st.markdown("**Porcentajes sobre el Costo Directo**")
        _pa1, _pa2, _pa3 = st.columns(3)

        with _pa1:
            _a_opts = ["1%", "1.5%", "2%", "2.5%", "3%", "Otro"]
            _a_pre  = float(st.session_state.pre.get("pct_a", AIU_DEFAULTS["a"]))
            _a_pre_s = f"{int(_a_pre) if _a_pre == int(_a_pre) else _a_pre}%" if f"{int(_a_pre) if _a_pre == int(_a_pre) else _a_pre}%" in _a_opts else "Otro"
            _a_sel  = st.pills("A — Administración", _a_opts, default=_a_pre_s, key="aiu_pills_a",
                               help="Cubre gastos administrativos del proyecto")
            if _a_sel == "Otro" or _a_sel is None:
                pct_a = st.number_input("A% exacto", min_value=0.0, max_value=20.0, value=_a_pre, step=0.5, key="aiu_pct_a_custom")
            else:
                pct_a = float(_a_sel.replace("%",""))

        with _pa2:
            _i_opts = ["1%", "1.5%", "2%", "2.5%", "3%", "Otro"]
            _i_pre  = float(st.session_state.pre.get("pct_i", AIU_DEFAULTS["i"]))
            _i_pre_s = f"{int(_i_pre) if _i_pre == int(_i_pre) else _i_pre}%" if f"{int(_i_pre) if _i_pre == int(_i_pre) else _i_pre}%" in _i_opts else "Otro"
            _i_sel  = st.pills("I — Imprevistos", _i_opts, default=_i_pre_s, key="aiu_pills_i",
                               help="Reserva para lo inesperado")
            if _i_sel == "Otro" or _i_sel is None:
                pct_i = st.number_input("I% exacto", min_value=0.0, max_value=20.0, value=_i_pre, step=0.5, key="aiu_pct_i_custom")
            else:
                pct_i = float(_i_sel.replace("%",""))

        with _pa3:
            _u_opts = ["3%", "5%", "7%", "8%", "10%", "Otro"]
            _u_pre  = float(st.session_state.pre.get("pct_u", AIU_DEFAULTS["u"]))
            _u_pre_s = f"{int(_u_pre) if _u_pre == int(_u_pre) else _u_pre}%" if f"{int(_u_pre) if _u_pre == int(_u_pre) else _u_pre}%" in _u_opts else "Otro"
            _u_sel  = st.pills("U — Utilidad", _u_opts, default=_u_pre_s, key="aiu_pills_u",
                               help="Tu margen de ganancia. El IVA aplica SOLO sobre este valor")
            if _u_sel == "Otro" or _u_sel is None:
                pct_u = st.number_input("U% exacto", min_value=0.0, max_value=30.0, value=_u_pre, step=0.5, key="aiu_pct_u_custom")
            else:
                pct_u = float(_u_sel.replace("%",""))

        # ── Toggle fiscal IVA ─────────────────────────────────────────
        st.markdown("---")
        _aiu_iva_col, _ = st.columns([1.5, 1])
        with _aiu_iva_col:
            incluir_iva_aiu = st.toggle(
                "🧾 Incluir IVA 19% sobre Utilidad",
                value=st.session_state.pre.get("incluir_iva", True),
                key="aiu_iva_toggle",
                help="Activa si tu empresa es responsable del régimen común. "
                     "Desactiva si cotizas bajo régimen simplificado (Art. 499 E.T.).",
            )
            if incluir_iva_aiu:
                st.caption("IVA 19% sobre U (Utilidad) — Decreto 1372/92.")
            else:
                st.caption("⚠️ Sin IVA — régimen simplificado. El total no incluye IVA.")

        # Preview cálculo en tiempo real
        _val_a_prev = cd_total * (pct_a / 100)
        _val_i_prev = cd_total * (pct_i / 100)
        _val_u_prev = cd_total * (pct_u / 100)
        _val_iva_prev = _val_u_prev * 0.19 if incluir_iva_aiu else 0.0
        _total_prev  = cd_total + _val_a_prev + _val_i_prev + _val_u_prev + _val_iva_prev
        _iva_label   = f"IVA: <strong>{numero_completo(_val_iva_prev)}</strong>" if incluir_iva_aiu else                        "<span style='opacity:0.45;text-decoration:line-through'>IVA: Exento</span>"
        st.markdown(
            f"""<div style="background:var(--secondary-background-color);border:1px solid var(--border-color);
            border-radius:10px;padding:12px 18px;margin-top:8px;font-size:0.85rem">
            <div style="display:flex;gap:24px;flex-wrap:wrap">
              <span>CD: <strong>{numero_completo(cd_total)}</strong></span>
              <span>A: <strong>{numero_completo(_val_a_prev)}</strong></span>
              <span>I: <strong>{numero_completo(_val_i_prev)}</strong></span>
              <span>U: <strong>{numero_completo(_val_u_prev)}</strong></span>
              <span>{_iva_label}</span>
              <span style="color:#1B5FA8;font-weight:900">Total: {numero_completo(_total_prev)}</span>
            </div></div>""",
            unsafe_allow_html=True
        )

        st.markdown("---")

        # ── Logística ─────────────────────────────────────────────────
        with st.container(border=True):
            st.markdown("**🚛 Logística**")
            _al1, _al2 = st.columns(2)
            with _al1:
                _veh_aiu_keys = list(VEHICULOS.keys())
                _veh_aiu_pre  = st.session_state.pre.get("vehiculo_entrega","frontier")
                _veh_aiu_lbl_pre = next((k for k, v in VEHICULOS.items() if v == _veh_aiu_pre), _veh_aiu_keys[0])
                _veh_aiu_sel  = st.pills("Vehículo", _veh_aiu_keys, default=_veh_aiu_lbl_pre, key="aiu_veh_pills")
                vehiculo_aiu  = VEHICULOS.get(_veh_aiu_sel or _veh_aiu_lbl_pre, "frontier")
                agente_aiu    = st.toggle("Agente externo trae material", value=bool(st.session_state.pre.get("agente_externo_taller",False)), key="aiu_agente")

            with _al2:
                _km_aiu_opts = ["0-5 km", "5-15 km", "15-30 km", "30-60 km", "60+ km"]
                _km_aiu_pre  = float(st.session_state.pre.get("km", 10.0))
                _km_aiu_sel  = st.pills("Distancia", _km_aiu_opts,
                                        default="5-15 km" if _km_aiu_pre <= 15 else "15-30 km" if _km_aiu_pre <= 30 else "30-60 km",
                                        key="aiu_km_pills")
                _km_aiu_defaults = {"0-5 km": 3, "5-15 km": 10, "15-30 km": 22, "30-60 km": 45, "60+ km": 80}
                km_aiu  = st.number_input("Km exactos (Ida)", min_value=0.0,
                                           value=float(_km_aiu_defaults.get(_km_aiu_sel or "5-15 km", _km_aiu_pre)),
                                           step=1.0, key="aiu_km")
                _pj_aiu_opts = ["0", "1", "2", "3", "4+"]
                _pj_aiu_pre  = int(st.session_state.pre.get("peajes", 0))
                # FIX-1: garantizar que el default exista en la lista de opciones
                _pj_aiu_pre_s = str(_pj_aiu_pre) if str(_pj_aiu_pre) in _pj_aiu_opts else ("4+" if _pj_aiu_pre > 3 else _pj_aiu_opts[0])
                _pj_aiu_sel  = st.pills("Peajes ida+vuelta", _pj_aiu_opts,
                                        default=_pj_aiu_pre_s,
                                        key="aiu_pj_pills")
                peajes_aiu   = int(_pj_aiu_sel) if (_pj_aiu_sel and _pj_aiu_sel != "4+") else st.number_input("Peajes (exacto)", min_value=0, value=_pj_aiu_pre, step=1, key="aiu_pj_custom")

        # ── Foráneo ──────────────────────────────────────────────────
        with st.container(border=True):
            st.markdown("**✈️ ¿Proyecto fuera de Barranquilla?**")
            foraneo_aiu = st.toggle("Sí, fuera de la ciudad", value=bool(st.session_state.pre.get("foraneo_activo",False)), key="aiu_foraneo")
            tipo_aloj_aiu = "pueblo"; noches_aiu = 0; pers_aiu = 2
            if foraneo_aiu:
                _ff1, _ff2, _ff3 = st.columns(3)
                with _ff1:
                    tipo_aloj_aiu = ALOJAMIENTO[st.selectbox(
                        "Destino", list(ALOJAMIENTO.keys()),
                        index=list(ALOJAMIENTO.keys()).index(next((k for k, v in ALOJAMIENTO.items() if v == st.session_state.pre.get("tipo_aloj","pueblo")), list(ALOJAMIENTO.keys())[0])),
                        key="aiu_tipo_aloj"
                    )]
                with _ff2:
                    _nc_aiu_opts = ["1", "2", "3", "4", "5+"]
                    _nc_aiu_pre  = int(st.session_state.pre.get("noches",1))
                    # FIX-1: garantizar que el default exista en la lista de opciones
                    _nc_aiu_pre_s = str(_nc_aiu_pre) if str(_nc_aiu_pre) in _nc_aiu_opts else ("5+" if _nc_aiu_pre > 4 else _nc_aiu_opts[0])
                    _nc_aiu_sel  = st.pills("Noches", _nc_aiu_opts,
                                            default=_nc_aiu_pre_s,
                                            key="aiu_noches_pills")
                    noches_aiu = int(_nc_aiu_sel) if (_nc_aiu_sel and _nc_aiu_sel != "5+") else st.number_input("Noches (exacto)", min_value=0, value=_nc_aiu_pre, step=1, key="aiu_nc_custom")
                with _ff3:
                    _ps_aiu_opts = ["1", "2", "3", "4", "5+"]
                    _ps_aiu_pre  = int(st.session_state.pre.get("personas",2))
                    # FIX-1: garantizar que el default exista en la lista de opciones
                    _ps_aiu_pre_s = str(_ps_aiu_pre) if str(_ps_aiu_pre) in _ps_aiu_opts else ("5+" if _ps_aiu_pre > 4 else _ps_aiu_opts[0])
                    _ps_aiu_sel  = st.pills("Personas", _ps_aiu_opts,
                                            default=_ps_aiu_pre_s,
                                            key="aiu_pers_pills")
                    pers_aiu = int(_ps_aiu_sel) if (_ps_aiu_sel and _ps_aiu_sel != "5+") else st.number_input("Personas (exacto)", min_value=1, value=_ps_aiu_pre, step=1, key="aiu_ps_custom")

        # Guardar en pre (incluir_iva persiste entre pasos y restauraciones)
        st.session_state.pre = {
            **st.session_state.pre,
            "nombre_cliente":        nombre_cliente_aiu,
            "pct_a":                 pct_a,
            "pct_i":                 pct_i,
            "pct_u":                 pct_u,
            "incluir_iva":           incluir_iva_aiu,
            "vehiculo_entrega":      vehiculo_aiu,
            "km":                    km_aiu,
            "peajes":                peajes_aiu,
            "agente_externo_taller": agente_aiu,
            "foraneo_activo":        foraneo_aiu,
            "tipo_aloj":             tipo_aloj_aiu,
            "noches":                noches_aiu,
            "personas":              pers_aiu,
            "aiu_items":             st.session_state.get("aiu_items",[]),
            "tipo_proyecto":         "Licitación AIU",
        }

    # ════════════════════════════════════════════════════════════════════
    # PASO AIU 2 — CÁLCULO Y RESULTADO
    # ════════════════════════════════════════════════════════════════════
    elif paso_aiu == 2:
        nombre_cliente_aiu = st.session_state.pre.get("nombre_cliente","")

        # FIX-3 Live Data Fetching — Corrección de Stale State en salto por pills.
        # ─────────────────────────────────────────────────────────────────────────
        # st.session_state.pre puede estar desactualizado si el usuario saltó
        # directamente al paso 2 sin pasar por el paso 0/1 en este ciclo de render.
        # La fuente de verdad para la lista de ítems y el toggle de IVA es siempre
        # session_state directamente, ya que esos widgets escriben en session_state
        # en tiempo real. Leerlos desde ahí garantiza que cd_total e iva sean
        # exactos sin importar el orden o velocidad de navegación.
        _current_aiu_items = st.session_state.get("aiu_items", [])
        _current_iva       = st.session_state.get("aiu_iva_toggle",
                                st.session_state.pre.get("incluir_iva", True))

        # cd_total: recalcular siempre desde los ítems en vivo
        if _current_aiu_items:
            cd_total = sum(
                float(it.get("cant", 0)) * float(it.get("punit", 0))
                for it in _current_aiu_items
            )
        else:
            # Fallback: usar el valor cacheado en pre si no hay ítems en vivo
            cd_total = st.session_state.pre.get("cd_total", 0.0)

        pct_a         = st.session_state.pre.get("pct_a",  AIU_DEFAULTS["a"])
        pct_i         = st.session_state.pre.get("pct_i",  AIU_DEFAULTS["i"])
        pct_u         = st.session_state.pre.get("pct_u",  AIU_DEFAULTS["u"])
        vehiculo_aiu  = st.session_state.pre.get("vehiculo_entrega", "frontier")
        km_aiu        = st.session_state.pre.get("km",     10.0)
        peajes_aiu    = st.session_state.pre.get("peajes", 0)
        agente_aiu    = st.session_state.pre.get("agente_externo_taller", False)
        foraneo_aiu   = st.session_state.pre.get("foraneo_activo",       False)
        tipo_aloj_aiu = st.session_state.pre.get("tipo_aloj",  "pueblo")
        noches_aiu    = st.session_state.pre.get("noches",    0)
        pers_aiu      = st.session_state.pre.get("personas",  2)
        # FIX-3: usar _current_iva (live) en lugar de pre.get("incluir_iva")
        incluir_iva_aiu = _current_iva

        # Calcular
        if not st.session_state.cotizacion or st.session_state.get("_recalcular_aiu"):
            with st.spinner("Calculando AIU..."):
                res_aiu = calcular_aiu(
                    cd_total, pct_a, pct_i, pct_u, vehiculo_aiu, km_aiu, peajes_aiu,
                    agente_aiu, foraneo_aiu, tipo_aloj_aiu, noches_aiu, pers_aiu,
                    # FIX-3: iva en vivo — nunca stale
                    incluir_iva=_current_iva,
                )
                res_aiu["tipo_proyecto"]   = "Licitación AIU"
                res_aiu["categoria"]       = "Proyecto Constructora"
                res_aiu["referencia"]      = "Múltiple"
                res_aiu["m2_real"]         = 0
                res_aiu["ml_proyecto"]     = 0
                res_aiu["costo_total"]     = cd_total
                res_aiu["precio_sugerido"] = res_aiu["precio_total"]
                res_aiu["incluir_iva"]     = incluir_iva_aiu
                res_aiu["_estado_guardado"] = {
                    # ── Inputs base ───────────────────────────────────────────
                    "nombre_cliente": nombre_cliente_aiu, "aiu_items": st.session_state.aiu_items,
                    "pct_a": pct_a, "pct_i": pct_i, "pct_u": pct_u, "tipo_proyecto": "Licitación AIU",
                    "vehiculo_entrega": vehiculo_aiu, "km": km_aiu, "peajes": peajes_aiu,
                    "agente_externo_taller": agente_aiu, "foraneo_activo": foraneo_aiu,
                    "tipo_aloj": tipo_aloj_aiu, "noches": noches_aiu, "personas": pers_aiu,
                    "incluir_iva": incluir_iva_aiu,
                    # ── FIX-1/3 Estructuras dinámicas (Caja Negra AIU) ────────
                    "aiu_paso":    st.session_state.get("aiu_paso", 0),
                    "editando_id": st.session_state.get("editando_id"),
                }
                st.session_state.cotizacion = res_aiu
                st.session_state["_recalcular_aiu"] = False
                # FIX-2 Dirty-State + FIX-1 Multi-Tenant
                try:
                    _snap_aiu = res_aiu["_estado_guardado"]
                    _hash_aiu = hash(json.dumps(_snap_aiu, sort_keys=True, default=str))
                    if _hash_aiu != st.session_state.get("last_aiu_hash"):
                        _guardar_config(_clave_borrador_aiu(), _snap_aiu)
                        st.session_state["last_aiu_hash"] = _hash_aiu
                except Exception:
                    pass

        r = st.session_state.cotizacion

        import random as _rr
        _num_auto_aiu = f"AIU-{_hoy().strftime('%Y%m%d')}-{_rr.randint(100,999)}"
        if "aiu_num_auto" not in st.session_state:
            st.session_state.aiu_num_auto = _num_auto_aiu

        # Hero card
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#0D2137 0%,#1B5FA8 100%);
                    border-radius:14px;padding:28px 36px;margin-bottom:20px;color:white;">
          <div style="color:#C9A84C;font-size:0.68rem;text-transform:uppercase;letter-spacing:0.14em;font-weight:700;margin-bottom:8px">
            Precio total del contrato (AIU)
          </div>
          <div style="font-size:3.2rem;font-weight:900;font-family:'Playfair Display',serif;line-height:1;margin-bottom:8px">
            {numero_completo(r["precio_total"])}
          </div>
          <div style="opacity:0.8;font-size:0.85rem">
            Margen efectivo: {r["margen_pct"]:.1f}% &nbsp;·&nbsp; Utilidad: {numero_completo(r["val_u"])}
          </div>
        </div>""", unsafe_allow_html=True)

        _cres, _ = st.columns([1.5, 1])
        with _cres:
            _iva_lbl_p2 = "IVA 19% exclusivo sobre Utilidad" if r.get("incluir_iva", True)                           else "IVA (Exento — Régimen Simplificado)"
            bloque_costos([
                ("Costo Directo Base (CD)",        r["cd"]),
                (f"A — Administración ({pct_a}%)", r["val_a"]),
                (f"I — Imprevistos ({pct_i}%)",    r["val_i"]),
                (f"U — Utilidad ({pct_u}%)",        r["val_u"]),
                (_iva_lbl_p2,                       r["val_iva"]),
                ("Gastos logísticos",               r["logistica"]),
            ], "PRECIO TOTAL CONTRATO", r["precio_total"])

        st.markdown("---")

        # Guardar
        _ya_g_aiu = st.session_state.get("_aiu_guardada", False)
        _editando_id_aiu  = st.session_state.get("editando_id")
        _editando_num_aiu = st.session_state.get("editando_num","")

        if _editando_id_aiu:
            alerta(f"**Modo edición** — modificando **{_editando_num_aiu}**.", "info")
            _au, _an_, _ac_ = st.columns([2, 1.5, 1])
            _btn_au = _au.button("✏️ Actualizar AIU", type="primary", use_container_width=True)
            _btn_an = _an_.button("💾 Guardar como nueva", use_container_width=True, key="aiu_nueva")
            _btn_ac = _ac_.button("✕ Cancelar", use_container_width=True, key="aiu_can")
            if _btn_ac:
                st.session_state.pop("editando_id", None)
                st.session_state.pop("editando_num", None)
                st.session_state.aiu_paso = 0
                st.rerun()
            if _btn_au:
                _actualizar_cotizacion(_editando_id_aiu, _editando_num_aiu, nombre_cliente_aiu, r)
                st.session_state.pop("editando_id", None)
                st.session_state.pop("editando_num", None)
                st.session_state["_aiu_guardada"]     = True
                st.session_state["_aiu_guardada_num"] = _editando_num_aiu
                st.session_state.aiu_success = True
                st.rerun()
            if _btn_an:
                # "Guardar como nueva" en modo edición: salir de edición y dejar
                # que el bloque "¿Guardar en historial?" decida el número definitivo.
                st.session_state.pop("editando_id", None)
                st.session_state.pop("editando_num", None)
                st.session_state["_aiu_guardada"]     = False  # Dejar al usuario decidir
                st.rerun()

        elif not _ya_g_aiu:
            st.markdown("""<div style="background:var(--secondary-background-color);border:1px solid var(--border-color);
            border-radius:12px;padding:18px 22px;margin-bottom:4px">
            <div style="font-size:0.75rem;font-weight:700;opacity:0.5;text-transform:uppercase;margin-bottom:4px">💾 ¿Guardar en historial?</div>
            <div style="font-size:0.88rem;opacity:0.75;margin-bottom:12px">Si es una oferta real, guárdala. Si es una prueba, puedes omitirlo.</div>
            </div>""", unsafe_allow_html=True)

            _ag1, _ag2, _ag3 = st.columns([2, 1.5, 1])
            with _ag1:
                _num_g_aiu_inp = st.text_input(
                    "Número de cotización AIU",
                    value=st.session_state.get("aiu_num_auto", _num_auto_aiu),
                    key="num_guardar_aiu_hist", label_visibility="collapsed"
                )
            with _ag2:
                if st.button("💾 Guardar en historial", type="primary", use_container_width=True, key="btn_guardar_aiu_hist"):
                    try:
                        _guardar_cotizacion(_num_g_aiu_inp, nombre_cliente_aiu or "Sin nombre", r)
                        st.session_state["_aiu_guardada"]     = True
                        st.session_state["_aiu_guardada_num"] = _num_g_aiu_inp
                        st.session_state.aiu_success = True
                        st.rerun()
                    except Exception as _eg_aiu:
                        st.error(f"Error al guardar: {_eg_aiu}")
            with _ag3:
                if st.button("✕ Solo borrador", use_container_width=True, key="btn_no_guardar_aiu_hist"):
                    st.session_state["_aiu_guardada"]     = True
                    st.session_state["_aiu_guardada_num"] = ""
                    st.session_state.aiu_success = True
                    st.toast("Cotización AIU calculada como borrador.", icon="📋")
                    st.rerun()
        else:
            st.session_state.aiu_success = True
            st.rerun()

    # ════════════════════════════════════════════════════════════════════
    # NAVEGACIÓN AIU
    # ════════════════════════════════════════════════════════════════════
    if not st.session_state.get("aiu_success") and paso_aiu < N_AIU - 1:
        st.markdown("---")
        _an_l, _an_r = st.columns(2)

        _puede_continuar_aiu = True
        _msg_val_aiu = ""

        if paso_aiu == 0:
            _cd_v = st.session_state.pre.get("cd_total", 0)
            if _cd_v <= 0:
                _puede_continuar_aiu = False
                _msg_val_aiu = "El Costo Directo es $0. Agrega al menos un ítem con precio y cantidad."

        with _an_l:
            if paso_aiu > 0:
                if st.button("← Atrás", use_container_width=True, key="btn_aiu_back"):
                    st.session_state.aiu_paso -= 1
                    st.rerun()

        with _an_r:
            if not _puede_continuar_aiu:
                st.warning(_msg_val_aiu)
            else:
                _lbl_aiu = "Calcular AIU →" if paso_aiu == N_AIU - 2 else "Siguiente →"
                if st.button(_lbl_aiu, type="primary", use_container_width=True, key="btn_aiu_next"):
                    st.session_state.aiu_paso += 1
                    if st.session_state.aiu_paso == N_AIU - 1:
                        st.session_state["_recalcular_aiu"] = True
                    st.rerun()

elif pagina == "Cotizacion AIU":
    st.markdown("<h2 style='font-family:Playfair Display,serif'>Cotizacion AIU</h2>", unsafe_allow_html=True)
    st.markdown("<p style='opacity:0.7;font-size:0.88rem'>Estructura formal colombiana A+I+U+IVA</p>", unsafe_allow_html=True)

    # [PERSISTENCIA] Restaurar borrador AIU desde BD si session_state está vacío (post-F5)
    # FIX-1 Multi-Tenant: clave dinámica por usuario
    if not st.session_state.pre and not st.session_state.get("_borrador_aiu_restaurado"):
        try:
            _borrador_aiu = _leer_config(_clave_borrador_aiu())
            if _borrador_aiu:
                st.session_state.pre = _borrador_aiu
                # ── FIX-2 Hidratación forzada AIU: reconstruir listas y paso ──────────
                if _borrador_aiu.get("aiu_items"):
                    st.session_state.aiu_items = _borrador_aiu["aiu_items"]
                if "aiu_paso" in _borrador_aiu and isinstance(_borrador_aiu["aiu_paso"], int):
                    st.session_state.aiu_paso = _borrador_aiu["aiu_paso"]
                if "editando_id" in _borrador_aiu and _borrador_aiu["editando_id"]:
                    st.session_state["editando_id"] = _borrador_aiu["editando_id"]
                st.info("📋 Se restauró tu último cálculo AIU (antes de la recarga).")
        except Exception:
            pass
        st.session_state["_borrador_aiu_restaurado"] = True

    nombre_cliente_aiu = st.text_input("Nombre de la Constructora o Proyecto", placeholder="Ej: Constructora ABC", value=st.session_state.pre.get("nombre_cliente", ""), key="aiu_nombre_cliente")

    seccion_titulo("Items del contrato")

    # ── Cards mobile-first — un card por ítem ─────────────────────────────────
    nuevos_items = []
    cd_total = 0.0
    for idx, it in enumerate(st.session_state.aiu_items):
        with st.container(border=True):
            # ── Fila 1: descripción + botón eliminar ─────────────────────────
            _row1a, _row1b = st.columns([5.5, 0.8])
            with _row1a:
                desc = st.text_input(
                    "📝 Descripción",
                    value=it["desc"],
                    key=f"aiu_d_{idx}",
                    placeholder="Ej: Suministro e instalación mármol",
                )
            with _row1b:
                st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
                _can_del = len(st.session_state.aiu_items) > 1
                if st.button("✕", key=f"aiu_del_{idx}",
                             help="Eliminar ítem", disabled=not _can_del):
                    st.session_state.aiu_items.pop(idx)
                    st.rerun()
            # ── Fila 2: unidad | cantidad | precio unitario ──────────────────
            _row2a, _row2b, _row2c = st.columns([1.5, 1.5, 3])
            with _row2a:
                und = st.text_input("Unidad", value=it["und"],
                                    key=f"aiu_u_{idx}", placeholder="glb / m² / ml")
            with _row2b:
                cant = st.number_input("Cantidad", value=float(it["cant"]),
                                       min_value=0.0, step=1.0, key=f"aiu_c_{idx}")
            with _row2c:
                punit = st.number_input("Precio unitario (COP)",
                                        value=float(it["punit"]),
                                        min_value=0.0, step=5_000.0, format="%.0f",
                                        key=f"aiu_p_{idx}")
                st.markdown(f"<div style='margin-top:-12px; margin-bottom:10px; font-size:0.85rem; color:#1B5FA8; font-weight:600;'>💰 Equivalencia: {cop(punit)}</div>", unsafe_allow_html=True)
            sub = cant * punit
            cd_total += sub
            st.markdown(
                f'<div style="font-size:0.78rem;font-weight:700;color:#1B5FA8;'
                f'text-align:right;margin-top:2px">Subtotal: {numero_completo(sub)}</div>',
                unsafe_allow_html=True
            )
        nuevos_items.append({"desc": desc, "und": und, "cant": cant, "punit": punit})
    st.session_state.aiu_items = nuevos_items

    if st.button("+ Agregar item"):
        st.session_state.aiu_items.append({"desc": "Nuevo item", "und": "glb", "cant": 1.0, "punit": 100_000})
        st.rerun()

    st.markdown(f"<div style='font-size:1.2rem;font-weight:900;color:#1B5FA8;margin:14px 0'>Costo Directo Total: {numero_completo(cd_total)}</div>", unsafe_allow_html=True)
    
    st.markdown("---")
    seccion_titulo("Porcentajes AIU y Logística")

    # ── Guía explicativa AIU ──────────────────────────────────────────────────
    with st.expander("📖 ¿Qué significa AIU? — Toca aquí para entenderlo", expanded=False):
        st.markdown("""
**AIU = Administración + Imprevistos + Utilidad**

Es la estructura de cobro estándar para contratos de construcción y obra en Colombia 
(exigida por constructoras y entidades públicas). Se aplica como **porcentaje sobre el Costo Directo** del proyecto.

| Componente | ¿Qué incluye? | Valor típico |
|---|---|---|
| **A — Administración** | Gastos de oficina, papelería, contador, permisos, seguros | 1.5% – 3% |
| **I — Imprevistos** | Colchón para imprevistos: clima, accidentes, retrasos | 1% – 3% |
| **U — Utilidad** | Tu ganancia por el proyecto | 5% – 10% |

**Sobre el IVA:** por ley colombiana (Decreto 1372/92), el IVA del 19% se cobra **solo sobre la Utilidad (U)**, 
no sobre el total del contrato. La app calcula esto automáticamente.

**Ejemplo práctico:**
- Costo Directo: $10.000.000
- A (2%): $200.000 — para cubrir gastos administrativos
- I (2%): $200.000 — colchón de imprevistos
- U (5%): $500.000 — tu ganancia
- IVA 19% sobre U: $95.000
- **Total contrato: $10.995.000**
        """)

    c1, c2, c3, c4 = st.columns(4)
    with c1: pct_a = st.number_input(
        "A — Administración (%)",
        value=float(st.session_state.pre.get("pct_a", AIU_DEFAULTS["a"])),
        step=0.5, key="aiu_pct_a",
        help="Cubre los gastos administrativos del proyecto: papelería, seguros, contador, permisos. Valor habitual: 2%."
    )
    with c2: pct_i = st.number_input(
        "I — Imprevistos (%)",
        value=float(st.session_state.pre.get("pct_i", AIU_DEFAULTS["i"])),
        step=0.5, key="aiu_pct_i",
        help="Reserva para lo inesperado: un accidente, un día de lluvia que para la obra, un material que llega tarde. Valor habitual: 2%."
    )
    with c3: pct_u = st.number_input(
        "U — Tu ganancia (%)",
        value=float(st.session_state.pre.get("pct_u", AIU_DEFAULTS["u"])),
        step=0.5, key="aiu_pct_u",
        help="Este es tu margen de utilidad. El IVA del 19% se aplica SOLO sobre este valor (no sobre el total). Valor habitual: 5-8%."
    )
    with c4:
        veh_aiu_lbl = st.selectbox("Vehículo", list(VEHICULOS.keys()), index=list(VEHICULOS.values()).index(st.session_state.pre.get("vehiculo_entrega", "frontier")) if st.session_state.pre.get("vehiculo_entrega", "frontier") in list(VEHICULOS.values()) else 0, key="aiu_vehiculo")
    
    vehiculo_aiu = VEHICULOS[veh_aiu_lbl]
    col1, col2, col3 = st.columns(3)
    km_aiu = col1.number_input("Km (Ida)", value=float(st.session_state.pre.get("km", 10.0)), key="aiu_km")
    peajes_aiu = col2.number_input("Peajes (Ida+vuelta)", value=int(st.session_state.pre.get("peajes", 0)), key="aiu_peajes")
    agente_aiu = col3.checkbox("Agente externo trae material", value=bool(st.session_state.pre.get("agente_externo_taller", False)), key="aiu_agente")

    st.markdown("**Gastos Foráneos**")
    foraneo_aiu = st.checkbox("Proyecto fuera de la ciudad", value=bool(st.session_state.pre.get("foraneo_activo", False)), key="aiu_foraneo")
    tipo_aloj_aiu = "pueblo"
    noches_aiu = 0
    pers_aiu = 2
    if foraneo_aiu:
        ca1, ca2, ca3 = st.columns(3)
        tipo_aloj_aiu = ALOJAMIENTO[ca1.selectbox("Destino", list(ALOJAMIENTO.keys()), index=list(ALOJAMIENTO.keys()).index(next((k for k,v in ALOJAMIENTO.items() if v==st.session_state.pre.get("tipo_aloj","pueblo")), list(ALOJAMIENTO.keys())[0])), key="aiu_tipo_aloj")]
        noches_aiu = ca2.number_input("Noches", min_value=0, value=int(st.session_state.pre.get("noches", 1)), step=1, key="aiu_noches")
        pers_aiu = ca3.number_input("Personas", min_value=1, value=int(st.session_state.pre.get("personas", 2)), step=1, key="aiu_personas")

    # ── Toggle fiscal IVA (ruta plana AIU) ──────────────────────────────────────
    _aiv_col, _ = st.columns([1.5, 1])
    with _aiv_col:
        incluir_iva_aiu = st.toggle(
            "🧾 Incluir IVA 19% sobre Utilidad",
            value=st.session_state.pre.get("incluir_iva", True),
            key="aiu_iva_toggle",
            help="Activa si tu empresa es responsable del régimen común. "
                 "Desactiva si cotizas bajo régimen simplificado (Art. 499 E.T.).",
        )
        if incluir_iva_aiu:
            st.caption("IVA 19% sobre U (Utilidad) — Decreto 1372/92.")
        else:
            st.caption("⚠️ Sin IVA — régimen simplificado. El total no incluye IVA.")

    # ── AUTOSAVE AIU: persistir estado en session_state.pre ────────────────────
    _pre_aiu_snap = {
        **st.session_state.pre,   # conservar lo que ya había (ej: piezas de Directa)
        "nombre_cliente":          nombre_cliente_aiu,
        "pct_a":                   pct_a,
        "pct_i":                   pct_i,
        "pct_u":                   pct_u,
        "incluir_iva":             incluir_iva_aiu,
        "vehiculo_entrega":        vehiculo_aiu,
        "km":                      km_aiu,
        "peajes":                  peajes_aiu,
        "agente_externo_taller":   agente_aiu,
        "foraneo_activo":          foraneo_aiu,
        "tipo_aloj":               tipo_aloj_aiu,
        "noches":                  noches_aiu,
        "personas":                pers_aiu,
        # ── FIX-1/3 Estructuras dinámicas (Caja Negra AIU) ────────────────────
        "aiu_items":               st.session_state.get("aiu_items", []),
        "aiu_paso":                st.session_state.get("aiu_paso", 0),
        "editando_id":             st.session_state.get("editando_id"),
        "tipo_proyecto":           "Licitación AIU",
    }
    st.session_state.pre = _pre_aiu_snap
    # ── Autoguardado AIU en BD en cada render (hash-gated) ────────────────────
    try:
        _hash_aiu_live = hash(json.dumps(_pre_aiu_snap, sort_keys=True, default=str))
        if _hash_aiu_live != st.session_state.get("last_aiu_pre_hash"):
            _guardar_config(_clave_borrador_aiu(), _pre_aiu_snap)
            st.session_state["last_aiu_pre_hash"] = _hash_aiu_live
    except Exception:
        pass

    # ── CALCULAR / ACTUALIZAR AIU ─────────────────────────────────────────────
    _editando_id_aiu  = st.session_state.get("editando_id")
    _editando_num_aiu = st.session_state.get("editando_num", "")

    if _editando_id_aiu:
        st.info(
            f"**Modo edición** — modificando cotización AIU **{_editando_num_aiu}**.",
            icon="✏️",
        )
        _aiu_col_upd, _aiu_col_new, _aiu_col_can = st.columns([2, 1.5, 1])
        _btn_aiu_actualizar   = _aiu_col_upd.button("✏️ Actualizar cotización AIU", type="primary", use_container_width=True)
        _btn_aiu_nueva        = _aiu_col_new.button("💾 Guardar como nueva", use_container_width=True, key="aiu_nueva")
        _btn_aiu_cancelar     = _aiu_col_can.button("✕ Cancelar edición", use_container_width=True, key="aiu_can")

        if _btn_aiu_cancelar:
            st.session_state.pop("editando_id", None)
            st.session_state.pop("editando_num", None)
            st.session_state.pop("pre", None)
            st.session_state.pop("cotizacion", None)
            st.rerun()
    else:
        _btn_aiu_actualizar = False
        _btn_aiu_nueva      = False
        _btn_aiu_cancelar   = False
        _btn_aiu_calcular   = st.button("Calcular cotización AIU", type="primary", use_container_width=True)

    _ejecutar_aiu = (
        (_editando_id_aiu and (_btn_aiu_actualizar or _btn_aiu_nueva))
        or (not _editando_id_aiu and _btn_aiu_calcular)
    )

    if _ejecutar_aiu:
        res_aiu = calcular_aiu(cd_total, pct_a, pct_i, pct_u, vehiculo_aiu, km_aiu, peajes_aiu, agente_aiu, foraneo_aiu, tipo_aloj_aiu, noches_aiu, pers_aiu,
                              incluir_iva=incluir_iva_aiu)

        # Preparación de campos para compatibilidad con BD y PDF
        res_aiu["tipo_proyecto"]   = "Licitación AIU"
        res_aiu["categoria"]       = "Proyecto Constructora"
        res_aiu["referencia"]      = "Múltiple"
        res_aiu["m2_real"]         = 0
        res_aiu["ml_proyecto"]     = 0
        res_aiu["costo_total"]     = cd_total
        res_aiu["precio_sugerido"] = res_aiu["precio_total"]
        res_aiu["incluir_iva"]     = incluir_iva_aiu

        res_aiu["_estado_guardado"] = {
            # ── Inputs base ────────────────────────────────────────────────────
            "nombre_cliente": nombre_cliente_aiu, "aiu_items": st.session_state.aiu_items,
            "pct_a": pct_a, "pct_i": pct_i, "pct_u": pct_u, "tipo_proyecto": "Licitación AIU",
            "vehiculo_entrega": vehiculo_aiu, "km": km_aiu, "peajes": peajes_aiu, "agente_externo_taller": agente_aiu,
            "foraneo_activo": foraneo_aiu, "tipo_aloj": tipo_aloj_aiu, "noches": noches_aiu, "personas": pers_aiu,
            "incluir_iva": incluir_iva_aiu,
            # ── FIX-1/3 Estructuras dinámicas (Caja Negra AIU) ─────────────────
            "aiu_paso":    st.session_state.get("aiu_paso", 0),
            "editando_id": st.session_state.get("editando_id"),
        }

        st.session_state.cotizacion = res_aiu

        # [PERSISTENCIA] Guardar borrador AIU — FIX-2 Dirty-State + FIX-1 Multi-Tenant
        try:
            _snap_aiu2 = res_aiu["_estado_guardado"]
            _hash_aiu2 = hash(json.dumps(_snap_aiu2, sort_keys=True, default=str))
            if _hash_aiu2 != st.session_state.get("last_aiu_hash"):
                _guardar_config(_clave_borrador_aiu(), _snap_aiu2)
                st.session_state["last_aiu_hash"] = _hash_aiu2
        except Exception:
            pass

        import random as _r
        _num_auto_aiu = f"AIU-{_hoy().strftime('%Y%m%d')}-{_r.randint(100,999)}"
        st.session_state["_aiu_num_sugerido"] = _num_auto_aiu

        if _editando_id_aiu and _btn_aiu_actualizar:
            _actualizar_cotizacion(_editando_id_aiu, _editando_num_aiu, nombre_cliente_aiu or "Sin nombre", res_aiu)
            st.session_state.pop("editando_id", None)
            st.session_state.pop("editando_num", None)
            st.session_state["_aiu_guardada"] = True
            st.session_state["_aiu_guardada_num"] = _editando_num_aiu
            st.success(f"✅ Cotización AIU **{_editando_num_aiu}** actualizada correctamente.")
        elif _editando_id_aiu and _btn_aiu_nueva:
            st.session_state.pop("editando_id", None)
            st.session_state.pop("editando_num", None)
            st.session_state["_aiu_guardada"] = False   # Nueva: dejar que el usuario decida guardar

    # ── RECÁLCULO DEFENSIVO AIU ──────────────────────────────────────────────
    # Se ejecuta SIEMPRE antes de renderizar el resultado.
    # Garantiza que st.session_state.cotizacion tenga precio_total válido
    # incluso si el usuario llegó aquí sin pasar por el botón Calcular
    # (navegación directa, F5, o salto de pasos desde pills/radio).
    _pre = st.session_state.pre

    # FIX-3b: Live Data Fetching — priorizar session_state sobre _pre
    # para evitar stale state en aiu_items e IVA (mismo fix que paso 2).
    _aiu_items_pre = (
        st.session_state.get("aiu_items")           # fuente en vivo (prioridad)
        or _pre.get("aiu_items")                    # fallback: borrador guardado
        or []
    )
    _iva_defensiva = st.session_state.get(
        "aiu_iva_toggle", bool(_pre.get("incluir_iva", True))
    )

    if _aiu_items_pre:
        _cd_total_pre = sum(float(it.get("cant", 0)) * float(it.get("punit", 0)) for it in _aiu_items_pre)
    else:
        _cd_total_pre = _pre.get("cd_total", 0.0)

    if _cd_total_pre > 0:
        _res_aiu_pre = calcular_aiu(
            _cd_total_pre,
            float(_pre.get("pct_a", AIU_DEFAULTS["a"])),
            float(_pre.get("pct_i", AIU_DEFAULTS["i"])),
            float(_pre.get("pct_u", AIU_DEFAULTS["u"])),
            _pre.get("vehiculo_entrega", "frontier"),
            float(_pre.get("km", 0.0)),
            int(_pre.get("peajes", 0)),
            bool(_pre.get("agente_externo_taller", False)),
            bool(_pre.get("foraneo_activo", False)),
            _pre.get("tipo_aloj", "pueblo"),
            int(_pre.get("noches", 0)),
            int(_pre.get("personas", 2)),
            # FIX-3b: IVA en vivo — coherente con el live-fetching del paso 2
            incluir_iva=_iva_defensiva,
        )
        _res_aiu_pre["tipo_proyecto"]   = "Licitación AIU"
        _res_aiu_pre["categoria"]       = "Proyecto Constructora"
        _res_aiu_pre["referencia"]      = "Múltiple"
        _res_aiu_pre["m2_real"]         = 0
        _res_aiu_pre["ml_proyecto"]     = 0
        _res_aiu_pre["costo_total"]     = _cd_total_pre
        _res_aiu_pre["precio_sugerido"] = _res_aiu_pre["precio_total"]
        _res_aiu_pre["nombre_cliente"]  = _pre.get("nombre_cliente", "")
        _res_aiu_pre["incluir_iva"]     = _iva_defensiva  # FIX-3b: IVA en vivo
        _res_aiu_pre["aiu_items"]       = _aiu_items_pre
        # Solo sobreescribir cotizacion si NO es ya una AIU válida con precio_total
        _cot_actual = st.session_state.cotizacion or {}
        if not (_cot_actual.get("tipo_proyecto") == "Licitación AIU"
                and _cot_actual.get("precio_total")):
            st.session_state.cotizacion = _res_aiu_pre

    if st.session_state.cotizacion and st.session_state.cotizacion.get("tipo_proyecto") == "Licitación AIU":
        r = st.session_state.cotizacion

        st.markdown(f"""
        <div style="background:#1B5FA8; border-radius:14px;padding:32px 36px;margin:8px 0 20px; color:white;">
          <div style="color:#C9A84C;font-size:0.68rem;text-transform:uppercase;letter-spacing:0.14em;font-weight:700;margin-bottom:10px">Precio total del contrato (AIU)</div>
          <div style="font-size:2.8rem;font-weight:900;font-family:'Playfair Display',serif;line-height:1;margin-bottom:8px">{numero_completo(r['precio_total'])}</div>
          <div style="opacity:0.8;font-size:0.85rem">Margen Efectivo: {r['margen_pct']:.1f}%</div>
        </div>""", unsafe_allow_html=True)

        c_res, _ = st.columns([1.5, 1])
        with c_res:
            _iva_lbl_pl = "IVA 19% exclusivo sobre Utilidad" if r.get("incluir_iva", True)                           else "IVA (Exento — Régimen Simplificado)"
            bloque_costos([
                ("Costo Directo Base (CD)", r["cd"]),
                (f"A — Administración ({r.get('pct_a', pct_a)}%)", r["val_a"]),
                (f"I — Imprevistos ({r.get('pct_i', pct_i)}%)", r["val_i"]),
                (f"U — Utilidad ({r.get('pct_u', pct_u)}%)", r["val_u"]),
                (_iva_lbl_pl,               r["val_iva"]),
                ("Gastos Logísticos Integrados", r["logistica"]),
            ], "PRECIO TOTAL", r["precio_total"])

        st.markdown("---")

        # ── Bloque de guardado en historial (idéntico al de Cotización Directa) ─
        _ya_guardada_aiu = st.session_state.get("_aiu_guardada", False)
        _num_sugerido_aiu = st.session_state.get("_aiu_num_sugerido",
                                                   f"AIU-{_hoy().strftime('%Y%m%d')}-001")

        if _ya_guardada_aiu:
            _num_g_aiu = st.session_state.get("_aiu_guardada_num", "")
            if _num_g_aiu:
                st.success(f"✅ Cotización AIU **{_num_g_aiu}** guardada en el historial.", icon="💾")
            else:
                st.info("📋 Cotización calculada como borrador. No se guardó en historial.")
        else:
            st.markdown(
                """<div style="background:var(--secondary-background-color);border:1px solid var(--border-color);
                border-radius:12px;padding:18px 22px;margin-bottom:4px">
                <div style="font-size:0.75rem;font-weight:700;opacity:0.5;text-transform:uppercase;margin-bottom:4px">💾 ¿Guardar en historial?</div>
                <div style="font-size:0.88rem;opacity:0.75;margin-bottom:12px">
                Si esta es una oferta real para un cliente, guárdala. Si es un borrador o prueba, puedes omitirlo.
                </div></div>""",
                unsafe_allow_html=True
            )
            _gc1_aiu, _gc2_aiu, _gc3_aiu = st.columns([2, 1.5, 1])
            with _gc1_aiu:
                _num_guardar_aiu = st.text_input(
                    "Número de cotización AIU",
                    value=_num_sugerido_aiu,
                    key="num_guardar_aiu_hist",
                    label_visibility="collapsed",
                    placeholder="Ej: AIU-20260301-001"
                )
            with _gc2_aiu:
                if st.button("💾 Guardar en historial", type="primary",
                             use_container_width=True, key="btn_guardar_aiu_hist"):
                    try:
                        _guardar_cotizacion(
                            _num_guardar_aiu,
                            nombre_cliente_aiu or "Sin nombre",
                            r
                        )
                        st.session_state["_aiu_guardada"] = True
                        st.session_state["_aiu_guardada_num"] = _num_guardar_aiu
                        st.rerun()
                    except Exception as _eg_aiu:
                        st.error(f"Error al guardar: {_eg_aiu}")
            with _gc3_aiu:
                if st.button("✕ Solo borrador", use_container_width=True,
                             key="btn_no_guardar_aiu_hist"):
                    st.session_state["_aiu_guardada"] = True
                    st.session_state["_aiu_guardada_num"] = ""
                    st.toast("Cotización AIU calculada como borrador. No se guardó en historial.",
                             icon="📋")
                    st.rerun()

        st.markdown("---")
        st.markdown("#### Exportar Documentos Institucionales")
        from generador_pdf import generar_pdf_cotizacion_aiu, generar_cuenta_cobro
        cp1, cp2 = st.columns(2)
        with cp1:
            num_cot_a = st.text_input("Número de Oferta", value=f"OFE-AIU-{_hoy().strftime('%Y')}-001")
            if st.button("📄 Generar Oferta AIU (PDF)", type="primary", use_container_width=True):
                # FIX-2f: spinner durante la generación del buffer ReportLab
                with st.spinner("Generando documento corporativo..."):
                    pdf_bytes = generar_pdf_cotizacion_aiu(
                        r, numero=num_cot_a, empresa_info=st.session_state.empresa_info,
                        logo_bytes=st.session_state.logo_bytes, incluir_iva=r.get("incluir_iva", True)
                    )
                st.download_button("⬇ Descargar Oferta", pdf_bytes, file_name=f"{num_cot_a}.pdf", mime="application/pdf", use_container_width=True)
        with cp2:
            num_cc_a = st.text_input("Número de Cuenta / Factura", value=f"FAC-AIU-{_hoy().strftime('%Y')}-001")
            nom_pag_a = st.text_input("Facturar a:", value=nombre_cliente_aiu)
            nit_pag_a = st.text_input("NIT / Rut", value="")
            if st.button("📄 Generar Cobro AIU (PDF)", type="primary", use_container_width=True):
                datos_prest = st.session_state.empresa_info.copy()
                datos_pag = {"nombre": nom_pag_a, "nit": nit_pag_a, "direccion": ""}
                # FIX-2g: spinner durante la generación del buffer ReportLab
                with st.spinner("Generando documento corporativo..."):
                    cc_bytes = generar_cuenta_cobro(
                        r, datos_prest, datos_pag,
                        numero=num_cc_a, logo_bytes=st.session_state.logo_bytes
                    )
                st.download_button("⬇ Descargar Cobro", cc_bytes, file_name=f"{num_cc_a}.pdf", mime="application/pdf", use_container_width=True)

# ═══════════════════════════════════════════════════════════════════════════════
# HISTORIAL DE COTIZACIONES — Tarjetas + métricas integradas (Dashboard eliminado)
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Historial":
    st.markdown(
        "<h2 style='font-family:Playfair Display,serif;margin-bottom:4px'>"
        "Historial de cotizaciones</h2>",
        unsafe_allow_html=True
    )

    # ── Métricas rápidas (integradas — ya no hay Dashboard separado) ──────────
    _s = _stats_db(
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
                    numero_completo(_s["facturacion"]) if _s["facturacion"] else "—")
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
    _rows = _listar_cotizaciones(_bus, usuario_id=st.session_state.get("usuario_actual",{}).get("id"), rol=st.session_state.get("usuario_actual",{}).get("rol","Admin"))
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
    else:
        _ESTADOS = ["Pendiente", "Aprobada", "Rechazada", "En revision"]

        # Color + icono por estado
        _EC = {
            "Pendiente":   ("#B8962E", "🟡"),
            "Aprobada":    ("#155724", "🟢"),
            "Rechazada":   ("#7B1A1A", "🔴"),
            "En revision": ("#1B5FA8", "🔵"),
        }

        # _cargar_en_calculadora se define a nivel global (ver más abajo en el archivo)

        # ── VISTA TARJETAS ────────────────────────────────────────────────────
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
      <div style="font-size:1rem;font-weight:900;color:#1B5FA8">{numero_completo(_rpre)}</div>
    </div>
    <div>
      <div style="font-size:0.6rem;font-weight:700;opacity:0.5;text-transform:uppercase;
                  letter-spacing:0.05em">Margen</div>
      <div style="font-size:1rem;font-weight:800;color:{_mrg_color}">
        {f"{float(_rmrg):.0f}%" if _rmrg else "—"}</div>
    </div>
    {"<div><div style='font-size:0.6rem;font-weight:700;opacity:0.5;text-transform:uppercase;letter-spacing:0.05em'>ML</div>" +
     f"<div style='font-size:1rem;font-weight:700'>{fmt_ml(float(_rml), 1)}</div></div>"
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
                            _actualizar_estado(_rid, _new_est)
                            st.rerun()
                    with _cb:
                        if st.button("✏️ Editar", key=f"ed_{_rid}",
                                     use_container_width=True, help="Recargar en la calculadora"):
                            _cargar_en_calculadora(_rid, _rnum, _rjson)
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
                            _eliminar_cotizacion(_rid)
                            st.session_state.pop(_ck, None)
                            st.rerun()
                        if _dy.button("Cancelar", key=f"dno_{_rid}",
                                      use_container_width=True):
                            st.session_state[_ck] = False
                            st.rerun()

                    st.markdown("<div style='margin-bottom:14px'></div>",
                                unsafe_allow_html=True)

        # ── VISTA TABLA ───────────────────────────────────────────────────────
        else:
            _th = st.columns([1.0, 0.9, 2.2, 1.3, 1.2, 0.95, 1.5, 0.55, 0.55])
            for _col, _lbl in zip(_th, ["Número","Fecha","Cliente","Material",
                                        "Precio","Margen","Estado","✏️","🗑️"]):
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
                    f"{numero_completo(_rpre)}</span>",
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
                    _actualizar_estado(_rid, _new_est)
                    st.rerun()

                if _tc[7].button("✏️", key=f"edt_{_rid}", help="Editar"):
                    _cargar_en_calculadora(_rid, _rnum, _rjson)

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
                        _eliminar_cotizacion(_rid)
                        st.session_state.pop(_ck2, None)
                        st.rerun()
                    if _dy2.button("Cancelar", key=f"dnot_{_rid}",
                                   use_container_width=True):
                        st.session_state[_ck2] = False
                        st.rerun()



# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD — ANÁLISIS DE NEGOCIO CON DATA LITERACY
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Dashboard":
    import pandas as pd

    st.markdown(
        "<h2 style='font-family:Playfair Display,serif;margin-bottom:4px'>Dashboard</h2>"
        "<p style='opacity:0.52;font-size:0.85rem;margin:0 0 20px'>Métricas reales de tu negocio — actualizadas automáticamente con cada cotización.</p>",
        unsafe_allow_html=True,
    )

    _s = _stats_db(
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
    _facturacion_f = numero_completo(_s["facturacion"]) if _s["facturacion"] else "$0"

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
        _sr = _stats_retales(
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
            f"Tienes {numero_completo(_valor_ret)} COP en retales disponibles "
            f"({fmt_m2(_m2_ret, 2)}, {_piezas_ret} {'pieza' if _piezas_ret == 1 else 'piezas'}). "
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
                padding: 20px 24px;
                margin: 4px 0 20px 0;
            ">
                <div style="
                    font-size: 0.68rem; font-weight: 800; letter-spacing: 0.16em;
                    text-transform: uppercase; color: #C9A84C; margin-bottom: 6px;
                ">💎 Capital Inmovilizado Recuperable</div>
                <div style="
                    font-size: 2.1rem; font-weight: 900;
                    font-family: 'Playfair Display', serif;
                    color: var(--text-color); line-height: 1.1; margin-bottom: 4px;
                ">{numero_completo(_valor_ret)}</div>
                <div style="
                    font-size: 0.8rem; opacity: 0.55; margin-bottom: 12px;
                ">{fmt_m2(_m2_ret, 2)} disponibles · {_piezas_ret} {'pieza' if _piezas_ret == 1 else 'piezas'} en inventario</div>
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
                        f'<div style="font-size:1.1rem;font-weight:900">{numero_completo(_rvalc)}</div>'
                        f'<div style="font-size:0.72rem;opacity:0.7;margin-top:2px">'
                        f'{fmt_m2(_rm2c, 2)} · {int(_rpzs)} pza.</div>'
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
                    tickformat="~s",  # 12M, 4M, etc.
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

            # Convertir "2026-02" → "Feb 2026" para el eje X
            import calendar
            def _fmt_mes(m):
                try:
                    y, mo = str(m).split("-")
                    return f"{calendar.month_abbr[int(mo)]} {y}"
                except Exception:
                    return str(m)
            _df_mes["MesLabel"] = _df_mes["Mes"].apply(_fmt_mes)

            if "numero_completo" in dir():
                _fmt_cop2 = numero_completo
            else:
                def _fmt_cop2(v): return "$" + f"{int(round(v)):,}".replace(",", ".")

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
                    type="category",  # ← evita que Plotly interprete como datetime
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
            lambda x: numero_completo(x) if x else "—"
        )
        _df_det = _df_det.sort_values("Proyectos aprobados", ascending=False).reset_index(drop=True)

        # Colorear margen en la tabla
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
    _rg1, _rg2, _rg3 = st.columns(3)

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


# ═══════════════════════════════════════════════════════════════════════════════
# SOBRANTES APROVECHABLES (antes: Banco de Retales)
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Banco de Retales":
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
        _todos_retales = _listar_retales(usuario_id=st.session_state.get("usuario_actual",{}).get("id"), rol=st.session_state.get("usuario_actual",{}).get("rol","Admin"))
    except Exception:
        _todos_retales = []

    _disp = [r for r in _todos_retales if r[8] == "Disponible"]
    _usados = [r for r in _todos_retales if r[8] == "Usado"]
    _m2_disp_total = sum(r[3] for r in _disp)
    _m2_orig_total = sum(r[4] for r in _todos_retales)

    _rm1, _rm2, _rm3, _rm4 = st.columns(4)
    _rm1.metric("Sobrantes disponibles", len(_disp), help="Piezas de material que tienes guardadas y listas para usar en un nuevo proyecto.")
    _rm2.metric("m² disponibles", f"{_m2_disp_total:.2f} m²", help="Metros cuadrados totales de material sobrante que tienes en inventario.")
    _rm3.metric("Ya utilizados", len(_usados), help="Sobrantes que ya fueron asignados a un proyecto posterior.")
    _rm4.metric("Total registrado", f"{len(_todos_retales)} piezas", help="Total de sobrantes que el sistema ha registrado, incluyendo los ya utilizados.")

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
            st.markdown("<div style='font-weight:700;margin-bottom:10px'>Registrar sobrante manualmente</div>", unsafe_allow_html=True)
            _rf_c1, _rf_c2, _rf_c3 = st.columns([1.5, 1.5, 1])
            with _rf_c1:
                _ncat = st.selectbox("Categoría", CATEGORIAS_MATERIAL, key="rfm_cat")
                _nref = st.text_input("Referencia", key="rfm_ref", placeholder="Ej: Calacatta Dorato")
            with _rf_c2:
                _nm2 = st.number_input("m² disponibles", min_value=0.05, max_value=50.0, value=1.0, step=0.05, key="rfm_m2", format="%.3f")
                _nnota = st.text_input("Notas (opcional)", key="rfm_nota", placeholder="Ej: Guardado en taller, estante 3")
            with _rf_c3:
                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                if st.button("Guardar", key="rfm_save", type="primary", use_container_width=True):
                    try:
                        _uid_manual = st.session_state.get("usuario_actual", {}).get("id")
                        _init_db()
                        _conn = _get_db_connection()
                        _cur = _conn.cursor()
                        _cur.execute(
                            """INSERT INTO inventario_retales
                               (material_categoria, referencia, m2_disponibles, m2_original,
                                fecha_ingreso, estado, notas, usuario_id)
                               VALUES (%s, %s, %s, %s, %s, 'Disponible', %s, %s)""",
                            (_ncat, _nref, _nm2, _nm2, _hoy().isoformat(), _nnota, _uid_manual)
                        )
                        _conn.commit()
                        _cur.close()
                        _conn.close()
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
    else:
        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

        for _rr in _filas_filtradas:
            _rr_id, _rr_cat, _rr_ref, _rr_m2d, _rr_m2o, _rr_onum, _rr_ocli, _rr_fech, _rr_est, _rr_nota = _rr[:10]
            _rr_precio_rec = float(_rr[10]) if len(_rr) > 10 else 0.0
            _pct_rest = (_rr_m2d / _rr_m2o * 100) if _rr_m2o > 0 else 0
            _est_color = "#15803d" if _rr_est == "Disponible" else "#6b7280"
            _bg_card = "rgba(21,128,61,0.04)" if _rr_est == "Disponible" else "rgba(107,114,128,0.05)"
            _border_color = "#15803d" if _rr_est == "Disponible" else "#6b7280"

            # ── Tarjeta compacta por sobrante ─────────────────────────────────
            with st.container():
                st.markdown(
                    f'<div style="border:1px solid {_border_color};border-left:4px solid {_border_color};'
                    f'border-radius:10px;padding:12px 16px 10px;margin-bottom:10px;background:{_bg_card}">',
                    unsafe_allow_html=True
                )

                # Fila superior: material + ref + m² + origen + fecha + badge estado
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
                        if st.button("🗑️ Eliminar", key=f"del_retal_{_rr_id}", use_container_width=True):
                            st.session_state[_del_retal_key] = True
                            st.rerun()
                    else:
                        if st.button("✅ Confirmar", key=f"delconf_retal_{_rr_id}", use_container_width=True, type="primary"):
                            _eliminar_retal(_rr_id)
                            st.session_state.pop(_del_retal_key, None)
                            st.rerun()

                # Barra de progreso de cuánto queda
                if _rr_m2o > 0 and _rr_est == "Disponible":
                    st.markdown(
                        f'<div style="height:4px;background:rgba(0,0,0,0.1);border-radius:2px;margin:10px 0 8px">'
                        f'<div style="height:100%;width:{_pct_rest:.0f}%;background:{_est_color};border-radius:2px"></div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )

                # Fila inferior: precio de recuperación — con guía clara
                if _rr_est == "Disponible":
                    st.markdown(
                        '<div style="border-top:1px solid var(--border-color);margin-top:10px;'
                        'padding-top:10px"></div>',
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
                        st.markdown(f"<div style='margin-top:-2px; margin-bottom:10px; font-size:0.85rem; color:#1B5FA8; font-weight:600;'>💰 Equivalencia: {cop(_nuevo_precio_rec)}</div>", unsafe_allow_html=True)
                        if _nuevo_precio_rec != int(_rr_precio_rec):
                            try:
                                _conn_pr = _get_db_connection()
                                _cur_pr  = _conn_pr.cursor()
                                _cur_pr.execute(
                                    "UPDATE inventario_retales SET precio_recuperacion=%s WHERE id=%s",
                                    (_nuevo_precio_rec, _rr_id)
                                )
                                _conn_pr.commit()
                                _cur_pr.close()
                                _conn_pr.close()
                                st.toast("✅ Precio guardado", icon="💾")
                            except Exception as _e_pr:
                                st.error(f"Error al guardar: {_e_pr}")
                    with _pr_col3:
                        if _nuevo_precio_rec == 0:
                            _hint_icon = "⚠️"
                            _hint_txt  = "Precio en $0 — Atención: esto generará un margen ilusorio en tus reportes. Ingresa al menos el costo base del material para reflejar la rentabilidad real."
                            _hint_color = "#b45309"
                        elif _nuevo_precio_rec < 50_000:
                            _hint_icon = "🟡"
                            _hint_txt  = f"Cobras {numero_completo(_nuevo_precio_rec)}/m² por este sobrante — precio simbólico, buen margen."
                            _hint_color = "#d97706"
                        else:
                            _hint_icon = "🔵"
                            _hint_txt  = f"Cobras {numero_completo(_nuevo_precio_rec)}/m² — precio de mercado parcial. El margen sigue siendo mejor que comprar nuevo."
                            _hint_color = "#1B5FA8"
                        st.markdown(
                            f'<div style="font-size:0.77rem;padding-top:8px;color:{_hint_color};font-weight:600">' +
                            f'{_hint_icon} {_hint_txt}</div>',
                            unsafe_allow_html=True
                        )

                st.markdown('</div>', unsafe_allow_html=True)
                st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PARÁMETROS, ASISTENTE IA Y CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Parametros":
    import pandas as pd
    st.markdown("<h2 style='font-family:Playfair Display,serif'>Parámetros Operativos y Costos</h2>", unsafe_allow_html=True)
    st.markdown("Ten control total de los costos de la empresa. Modifica las tablas manualmente o pídele al asistente que lo haga por ti.")

    t_ia, t_tar, t_via, t_log, t_add = st.tabs(["🤖 Asistente IA (Modificación Automática)", "📊 Tarifas y Producción", "🚗 Viáticos", "🚛 Logística y Vehículos", "➕ Costos Adicionales"])

    with t_ia:
        _ia_ok = ia_disponible()

        # ── CSS del panel de parámetros ───────────────────────────────────────
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
                unsafe_allow_html=True
            )
        else:
            # ── Layout split: chat + panel de valores actuales ────────────────
            _col_chat, _col_vals = st.columns([3, 2])

            with _col_chat:
                # Comandos rápidos del negocio real
                _comandos_rapidos = [
                    ("Gasolina subió", "La gasolina corriente subió. ¿A cuánto debería quedar mi costo por km en la Frontier?"),
                    ("Nuevo precio operario", "El operario de mármol ahora cobra más. ¿Cómo ajusto la tarifa por ml?"),
                    ("Viáticos fuera de ciudad", "¿Cuánto debería presupuestar por persona para trabajar en Cartagena o Santa Marta?"),
                    ("¿Mis consumibles son correctos?", "¿Los costos de consumibles que tengo son razonables para el mercado actual de Barranquilla?"),
                ]

                st.markdown(
                    "<div style='font-size:0.68rem;font-weight:700;opacity:0.4;letter-spacing:0.07em;"
                    "text-transform:uppercase;margin-bottom:8px'>Situaciones frecuentes</div>",
                    unsafe_allow_html=True
                )
                _cmd_c1, _cmd_c2 = st.columns(2)
                for _ci, (_lbl, _msg_cmd) in enumerate(_comandos_rapidos):
                    _col_cmd = _cmd_c1 if _ci % 2 == 0 else _cmd_c2
                    with _col_cmd:
                        if st.button(_lbl, key=f"pcmd_{_ci}", use_container_width=True):
                            st.session_state.params_wizard_chat.append({"role": "user", "content": _lbl})
                            with st.spinner(""):
                                _r_cmd = _chat_parametros(st.session_state.params_wizard_chat[:-1], _msg_cmd)
                            _aplicado_cmd = False
                            if "```json" in _r_cmd:
                                try:
                                    _js = _r_cmd.split("```json")[1].split("```")[0]
                                    _d = json.loads(_js)
                                    if "pueblo" in _d or "ciudad" in _d:
                                        _antes = (st.session_state.viaticos_custom or VIATICOS).copy()
                                        st.session_state.viaticos_custom = _d
                                        st.session_state.params_cambios_aplicados.append({"tipo": "viaticos", "antes": _antes, "despues": _d})
                                        try: _guardar_config("viaticos_custom", _d)
                                        except Exception: pass
                                    elif any(k in _d for k in ["Mármol", "Granito", "Sinterizado"]):
                                        _antes = (st.session_state.tarifas_custom or TARIFAS).copy()
                                        st.session_state.tarifas_custom = _d
                                        st.session_state.params_cambios_aplicados.append({"tipo": "tarifas", "antes": _antes, "despues": _d})
                                        try: _guardar_config("tarifas_custom", _d)
                                        except Exception: pass
                                    _aplicado_cmd = True
                                except Exception:
                                    pass
                            st.session_state.params_wizard_chat.append({
                                "role": "assistant", "content": _r_cmd, "aplicado": _aplicado_cmd
                            })
                            st.rerun()

                st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

                # Historial de conversación
                if not st.session_state.params_wizard_chat:
                    st.markdown(
                        '<div style="border:1px dashed var(--border-color);border-radius:10px;'
                        'padding:24px 18px;text-align:center;">'
                        '<div style="font-size:0.85rem;opacity:0.45;line-height:1.7">'
                        'Cuéntame qué cambió en tu operación.<br>'
                        '<span style="font-size:0.78rem">"La gasolina subió a $16.800" &nbsp;·&nbsp; '
                        '"El operario cobra $65.000/ml ahora"</span>'
                        '</div></div>',
                        unsafe_allow_html=True
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
                                unsafe_allow_html=True
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
                                unsafe_allow_html=True
                            )

                st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

                # Input
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
                        _pr = _chat_parametros(st.session_state.params_wizard_chat, _pnuevo.strip())
                    _p_aplic = False
                    if "```json" in _pr:
                        try:
                            _pjs = _pr.split("```json")[1].split("```")[0]
                            _pd = json.loads(_pjs)
                            if "pueblo" in _pd or "ciudad" in _pd:
                                _pantes = (st.session_state.viaticos_custom or VIATICOS).copy()
                                st.session_state.viaticos_custom = _pd
                                st.session_state.params_cambios_aplicados.append({"tipo": "viaticos", "antes": _pantes, "despues": _pd})
                                try: _guardar_config("viaticos_custom", _pd)
                                except Exception: pass
                            elif any(k in _pd for k in ["Mármol", "Granito", "Sinterizado"]):
                                _pantes = (st.session_state.tarifas_custom or TARIFAS).copy()
                                st.session_state.tarifas_custom = _pd
                                st.session_state.params_cambios_aplicados.append({"tipo": "tarifas", "antes": _pantes, "despues": _pd})
                                try: _guardar_config("tarifas_custom", _pd)
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

            # ── Panel derecho: valores actuales + historial de cambios ─────────
            with _col_vals:
                _tar_now = get_tarifas()
                _via_now = get_viaticos()
                _log_now = get_logistica()

                # Historial de cambios recientes
                if st.session_state.params_cambios_aplicados:
                    st.markdown(
                        "<div style='font-size:0.68rem;font-weight:700;opacity:0.4;letter-spacing:0.07em;"
                        "text-transform:uppercase;margin-bottom:8px'>Últimos cambios aplicados</div>",
                        unsafe_allow_html=True
                    )
                    _ultimo_cambio = st.session_state.params_cambios_aplicados[-1]
                    _tipo_c = _ultimo_cambio["tipo"]
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
                                            unsafe_allow_html=True
                                        )
                    elif _tipo_c == "tarifas":
                        for _mat in ["Mármol", "Granito", "Sinterizado", "Quarztone", "Quarzita"]:
                            if _mat in _antes_c and _mat in _despues_c:
                                for _sk in ["prod_ml", "zocalo", "disco", "maquina", "consumibles"]:
                                    _va = _antes_c[_mat].get(_sk, 0)
                                    _vd = _despues_c[_mat].get(_sk, 0)
                                    if _va != _vd:
                                        _lbl_sk = {"prod_ml": "Prod/ml", "zocalo": "Zócalo", "disco": "Disco", "maquina": "Máquina", "consumibles": "Consumibles"}
                                        st.markdown(
                                            f'<div class="cambio-row">'
                                            f'<span class="cambio-campo">{_mat} — {_lbl_sk.get(_sk, _sk)}</span>'
                                            f'<span class="cambio-antes">${int(_va):,}'.replace(",", ".") + '</span>'
                                            f'<span class="cambio-despues">${int(_vd):,}'.replace(",", ".") + '</span>'
                                            f'</div>',
                                            unsafe_allow_html=True
                                        )

                    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

                # Valores actuales resumidos
                st.markdown(
                    "<div style='font-size:0.68rem;font-weight:700;opacity:0.4;letter-spacing:0.07em;"
                    "text-transform:uppercase;margin-bottom:8px'>Valores actuales</div>",
                    unsafe_allow_html=True
                )

                # Gasolina + vehículos
                _gas = _log_now.get("gasolina", 16_000)
                st.markdown(
                    f'<div class="val-actual-row"><span class="val-label">Gasolina</span>'
                    f'<span class="val-num">${int(_gas):,}'.replace(",", ".") + '/gal</span></div>',
                    unsafe_allow_html=True
                )

                # Producción por material (prod_ml)
                for _m in ["Mármol", "Granito", "Sinterizado"]:
                    _pml = _tar_now.get(_m, {}).get("prod_ml", 0)
                    st.markdown(
                        f'<div class="val-actual-row"><span class="val-label">MO {_m}</span>'
                        f'<span class="val-num">${int(_pml):,}'.replace(",", ".") + '/ml</span></div>',
                        unsafe_allow_html=True
                    )

                # Viáticos pueblo y ciudad
                _via_p = _via_now.get("pueblo", {})
                _via_c = _via_now.get("ciudad", {})
                _total_p = sum(_via_p.values()) if isinstance(_via_p, dict) else _via_p
                _total_c = sum(_via_c.values()) if isinstance(_via_c, dict) else _via_c
                st.markdown(
                    f'<div class="val-actual-row"><span class="val-label">Viáticos pueblo</span>'
                    f'<span class="val-num">${int(_total_p):,}'.replace(",", ".") + '/día</span></div>',
                    unsafe_allow_html=True
                )
                st.markdown(
                    f'<div class="val-actual-row"><span class="val-label">Viáticos ciudad</span>'
                    f'<span class="val-num">${int(_total_c):,}'.replace(",", ".") + '/día</span></div>',
                    unsafe_allow_html=True
                )

                # Estado de personalización
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
                        unsafe_allow_html=True
                    )
                else:
                    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
                    st.markdown(
                        '<div style="font-size:0.75rem;opacity:0.45;font-style:italic">'
                        'Usando valores por defecto del sistema</div>',
                        unsafe_allow_html=True
                    )

    with t_tar:
        st.caption("Costos de mano de obra e insumos por material. Modifica cada campo y presiona **Guardar Tarifas**.")

        with st.expander("📖 ¿Qué significa cada campo? — Toca aquí para entenderlo", expanded=False):
            st.markdown("""
Estos son los **costos que tú pagas** por producir el trabajo. No son el precio que le cobras al cliente — son los costos que la app usa para calcular ese precio automáticamente.

| Campo | ¿Qué es en palabras simples? | Ejemplo |
|---|---|---|
| **Producción / ml** | Lo que le pagas al operario por cada metro lineal que corta e instala | El operario cobra $60.000 por cada ml → pon $60.000 |
| **Zócalo / ml** | Lo que cuesta instalar el zócalo (la tira de piedra en el borde inferior de la pared) | $12.000 por cada ml de zócalo |
| **Disco diamantado / m²** | Cuánto se gasta el disco de corte por cada m² que cortas. Los discos se desgastan. | Un disco cuesta $200.000 y dura ~90 m² → $2.200/m² |
| **Máquina cortadora / día** | El costo diario de usar tu cortadora (depreciación + mantenimiento) | Si la cortadora vale $6M y dura 5 años → ~$20.000/día |
| **Consumibles / m²** | Materiales que se gastan en cada obra: lijas, masilla, cera, sellador | Suma todo lo que gastas en insumos por m² instalado |
| **Riesgo de rotura (%)** | Un porcentaje del costo del material que guardas por si se rompe algo | 2% = si el material cuesta $500.000, guardas $10.000 de provisión |

**💡 Tip:** Si no sabes un valor exacto, deja el que ya está — son los valores del mercado de Barranquilla. Solo cambia cuando tengas un dato real de tu operación.
            """)

        tar_act = get_tarifas()
        # NOTA: No sincronizamos session_state directamente aquí porque eso
        # sobreescribiría los valores que el usuario acaba de editar antes de guardar.
        # Streamlit inicializa el widget con value= solo la primera vez que aparece el key.
        tar_edit = {}

        _MAT_ICONS = {"Mármol": "🪨", "Granito": "🟫", "Sinterizado": "⬜", "Quarztone": "🔵", "Quarzita": "🟡"}
        for _mat in ["Mármol", "Granito", "Sinterizado", "Quarztone", "Quarzita"]:
            _t = tar_act.get(_mat, {})
            tar_edit[_mat] = {}
            with st.container(border=True):
                st.markdown(f"**{_MAT_ICONS.get(_mat, '')} {_mat}**")
                _ca, _cb, _cc = st.columns(3)
                _cd, _ce, _cf = st.columns(3)
                tar_edit[_mat]["prod_ml"] = _ca.number_input(
                    "Producción / ml (COP)", min_value=0,
                    value=int(_t.get("prod_ml", 60_000)), step=1_000, format="%d",
                    key=f"tar_pml_{_mat}",
                    help="Lo que cobra el operario por cada metro lineal cortado e instalado (mesones, baños, escaleras).")
                tar_edit[_mat]["prod_m2"] = _cb.number_input(
                    "Producción / m² — Pisos (COP)", min_value=0,
                    value=int(_t.get("prod_m2", round(_t.get("prod_ml", 60_000) * 0.58))),
                    step=1_000, format="%d",
                    key=f"tar_pm2_{_mat}",
                    help="Lo que cobra el operario por cada m² instalado en pisos, fachadas y revestimientos. "
                         "Menor que prod_ml porque hay menos cortes de borde. "
                         "La app usa este valor automáticamente cuando el tipo de proyecto es Piso, Fachada o Revestimiento.")
                tar_edit[_mat]["zocalo"] = _ca.number_input(
                    "Zócalo / ml (COP)", min_value=0,
                    value=int(_t.get("zocalo", 12_000)), step=500, format="%d",
                    key=f"tar_zoc_{_mat}",
                    help="Tarifa por metro lineal de zócalo instalado.")
                tar_edit[_mat]["disco"] = _cb.number_input(
                    "Disco diamantado / m² (COP)", min_value=0,
                    value=int(_t.get("disco", 2_200)), step=100, format="%d",
                    key=f"tar_dis_{_mat}",
                    help="Desgaste del disco diamantado por m² cortado.")
                tar_edit[_mat]["maquina"] = _cc.number_input(
                    "Máquina cortadora / día (COP)", min_value=0,
                    value=int(_t.get("maquina", 20_000)), step=1_000, format="%d",
                    key=f"tar_maq_{_mat}",
                    help="Depreciación y mantenimiento de la cortadora por día de uso.")
                tar_edit[_mat]["consumibles"] = _cd.number_input(
                    "Consumibles / m² (COP)", min_value=0,
                    value=int(_t.get("consumibles", 10_000)), step=500, format="%d",
                    key=f"tar_con_{_mat}",
                    help="Masilla de poliéster, lijas diamantadas (50–3000), ceras, sellador y estopa.")
                tar_edit[_mat]["riesgo_rotura"] = _ce.number_input(
                    "Riesgo de rotura (%)", min_value=0.0, max_value=0.50,
                    value=float(_t.get("riesgo_rotura", 0.02)), step=0.01, format="%.2f",
                    key=f"tar_rie_{_mat}",
                    help="Porcentaje del costo del material reservado como provisión por rotura accidental.")

        st.markdown("")
        _col_save_tar, _col_reset_tar = st.columns([3, 1])
        if _col_save_tar.button("💾 Guardar Tarifas", type="primary", key="btn_save_tar", use_container_width=True):
            # Leer valores DIRECTAMENTE de los widgets activos (store + widget state)
            _saved_tar = {}
            for _sm in ["Mármol", "Granito", "Sinterizado", "Quarztone", "Quarzita"]:
                _saved_tar[_sm] = {
                    "prod_ml":       int(st.session_state.get(f"tar_pml_{_sm}", 60_000)),
                    "prod_m2":       int(st.session_state.get(f"tar_pm2_{_sm}", 35_000)),
                    "zocalo":        int(st.session_state.get(f"tar_zoc_{_sm}", 12_000)),
                    "disco":         int(st.session_state.get(f"tar_dis_{_sm}", 2_200)),
                    "maquina":       int(st.session_state.get(f"tar_maq_{_sm}", 20_000)),
                    "consumibles":   int(st.session_state.get(f"tar_con_{_sm}", 10_000)),
                    "riesgo_rotura": float(st.session_state.get(f"tar_rie_{_sm}", 0.02)),
                }
            # ── store_permanente: escritura dual — widget state + store ─────────
            _sp()["params_tarifas"] = _saved_tar
            st.session_state.tarifas_custom = _saved_tar
            # [PERSISTENCIA] Guardar en Supabase para sobrevivir a F5 y reinicios
            try:
                _guardar_config("tarifas_custom", _saved_tar)
            except Exception:
                pass
            # Limpiar keys de widgets para que se reinicialicen con los valores recién guardados
            for _sm in ["Mármol", "Granito", "Sinterizado", "Quarztone", "Quarzita"]:
                for _sfx in ["pml", "pm2", "zoc", "dis", "maq", "con", "rie"]:
                    st.session_state.pop(f"tar_{_sfx}_{_sm}", None)
            st.toast("✅ Tarifas guardadas y persistidas correctamente", icon="💾")
            st.rerun()
        if _col_reset_tar.button("↺ Restaurar", key="btn_reset_tar", use_container_width=True,
                                  help="Vuelve a los valores por defecto de fábrica"):
            st.session_state.tarifas_custom = None
            _sp()["params_tarifas"] = None  # store_permanente sync
            try:
                _guardar_config("tarifas_custom", None)
            except Exception:
                pass
            # Limpiar keys de widgets para forzar recarga con valores por defecto
            for _sm in ["Mármol", "Granito", "Sinterizado", "Quarztone", "Quarzita"]:
                for _sfx in ["pml", "pm2", "zoc", "dis", "maq", "con", "rie"]:
                    st.session_state.pop(f"tar_{_sfx}_{_sm}", None)
            st.toast("↺ Tarifas restauradas a valores por defecto", icon="🔄")
            st.rerun()

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

        via_act = get_viaticos()
        # NOTA: No sincronizamos session_state directamente aquí.
        # Streamlit inicializa el widget con value= solo la primera vez que aparece el key.

        def _normalizar_via(key):
            v = via_act.get(key, {})
            if isinstance(v, dict):
                return v
            # Formato legacy: valor plano → desglosar proporcionalmente
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
                st.caption(f"Total diario por persona: **{numero_completo(_total_via)}**")
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
            # ── store_permanente: escritura dual ────────────────────────────────
            _sp()["params_viaticos"] = _saved_via
            st.session_state.viaticos_custom = _saved_via
            # [PERSISTENCIA] Guardar en Supabase
            try:
                _guardar_config("viaticos_custom", _saved_via)
            except Exception:
                pass
            # Limpiar keys de widgets para que se reinicialicen con los valores recién guardados
            for _vk in ["via_pueblo_hosp", "via_pueblo_alim", "via_pueblo_tran",
                        "via_ciudad_hosp", "via_ciudad_alim", "via_ciudad_tran"]:
                st.session_state.pop(_vk, None)
            st.toast("✅ Viáticos guardados y persistidos correctamente", icon="💾")
            st.rerun()
        if _col_reset_via.button("↺ Restaurar", key="btn_reset_via", use_container_width=True,
                                  help="Vuelve a los valores por defecto de fábrica"):
            st.session_state.viaticos_custom = None
            _sp()["params_viaticos"] = None  # store_permanente sync
            try:
                _guardar_config("viaticos_custom", None)
            except Exception:
                pass
            for _vk in ["via_pueblo_hosp", "via_pueblo_alim", "via_pueblo_tran",
                        "via_ciudad_hosp", "via_ciudad_alim", "via_ciudad_tran"]:
                st.session_state.pop(_vk, None)
            st.toast("↺ Viáticos restaurados a valores por defecto", icon="🔄")
            st.rerun()

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

        log_act = get_logistica()
        # NOTA: No sincronizamos session_state directamente aquí.
        # Streamlit inicializa el widget con value= solo la primera vez que aparece el key.
        _lvc  = log_act.get("frontier", {})
        _lvc2 = log_act.get("cheyenne", {})
        _lve  = log_act.get("externo",  {})

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
            st.caption(f"Costo estimado por km ida+vuelta: **{numero_completo(_fr_km * 2)}/km** · "
                       f"Ejemplo 10 km → **{numero_completo(fr_base + _fr_km * 20)}** total")

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
            st.caption(f"Costo estimado por km ida+vuelta: **{numero_completo(_ch_km * 2)}/km** · "
                       f"Ejemplo 10 km → **{numero_completo(ch_base + _ch_km * 20)}** total")

        with st.container(border=True):
            st.markdown("**🤝 Externo / Tercero — flete contratado**")
            _ve = log_act.get("externo", {})
            _flete_val = int(_ve.get("flete", 165_000)) if isinstance(_ve, dict) else int(_ve)
            ext_flete = st.number_input(
                "Flete fijo por viaje (COP)", min_value=0,
                value=_flete_val, step=5_000, format="%d",
                key="log_ext_flete",
                help="Precio pactado con el flete externo. Aplica sin importar la distancia.")

        st.markdown("")
        _col_save_log, _col_reset_log = st.columns([3, 1])
        if _col_save_log.button("💾 Guardar Logística", type="primary", key="btn_save_log", use_container_width=True):
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
            }
            # ── store_permanente: escritura dual ────────────────────────────────
            _sp()["params_logistica"] = _saved_log
            st.session_state.logistica_custom = _saved_log
            # [PERSISTENCIA] Guardar en Supabase
            try:
                _guardar_config("logistica_custom", _saved_log)
            except Exception:
                pass
            # Limpiar keys de widgets para que se reinicialicen con los valores recién guardados
            for _lk in ["log_gas", "log_pea", "log_her", "log_age",
                        "log_fr_rend", "log_fr_desg", "log_fr_base",
                        "log_ch_rend", "log_ch_desg", "log_ch_base", "log_ext_flete"]:
                st.session_state.pop(_lk, None)
            st.toast("✅ Logística guardada y persistida correctamente", icon="💾")
            st.rerun()
        if _col_reset_log.button("↺ Restaurar", key="btn_reset_log", use_container_width=True,
                                  help="Vuelve a los valores por defecto de fábrica"):
            st.session_state.logistica_custom = None
            _sp()["params_logistica"] = None  # store_permanente sync
            try:
                _guardar_config("logistica_custom", None)
            except Exception:
                pass
            for _lk in ["log_gas", "log_pea", "log_her", "log_age",
                        "log_fr_rend", "log_fr_desg", "log_fr_base",
                        "log_ch_rend", "log_ch_desg", "log_ch_base", "log_ext_flete"]:
                st.session_state.pop(_lk, None)
            st.toast("↺ Logística restaurada a valores por defecto", icon="🔄")
            st.rerun()

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

        add_act = get_adicionales()
        UNIDADES_ADD = ["und", "ml", "m²", "viaje", "glb", "día", "kg"]

        # ── Inicializar estado ────────────────────────────────────────────────
        if "add_editor" not in st.session_state:
            st.session_state.add_editor = _cpy_add.deepcopy(add_act)

        # ── Construir DataFrame con tipos correctos ───────────────────────────
        _df_add = _pd_add.DataFrame(st.session_state.add_editor)
        for _cf in ["concepto", "unidad", "terminada", "acabados", "estructura", "comercial"]:
            if _cf not in _df_add.columns:
                _df_add[_cf] = "" if _cf in ("concepto", "unidad") else 0
        _df_add = _df_add[["concepto", "unidad", "terminada", "acabados", "estructura", "comercial"]]
        _df_add["terminada"]  = _df_add["terminada"].astype(int)
        _df_add["acabados"]   = _df_add["acabados"].astype(int)
        _df_add["estructura"] = _df_add["estructura"].astype(int)
        _df_add["comercial"]  = _df_add["comercial"].astype(int)

        # ── data_editor: 100% responsivo, soporte nativo a móvil ─────────────
        _df_editado = st.data_editor(
            _df_add,
            use_container_width=True,
            num_rows="dynamic",          # permite agregar y borrar filas
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

        # Sincronizar cambios del editor al session_state
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
                if str(row.get("concepto", "")).strip()   # descartar filas vacías
            ]
            st.session_state.adicionales_custom = _saved_add
            st.session_state.add_editor = _saved_add
            try:
                _guardar_config("adicionales_custom", _saved_add)
            except Exception:
                pass
            st.toast("✅ Costos adicionales guardados y persistidos", icon="💾")
            st.rerun()

        if _col_reset_add.button("↺ Restaurar", key="btn_reset_add", use_container_width=True,
                                  help="Vuelve a la lista original de fábrica"):
            st.session_state.adicionales_custom = None
            st.session_state.add_editor = _cpy_add.deepcopy(ADICIONALES)
            try:
                _guardar_config("adicionales_custom", None)
            except Exception:
                pass
            # Limpiar key del data_editor para forzar reinicialización
            st.session_state.pop("de_adicionales", None)
            st.toast("↺ Adicionales restaurados a valores por defecto", icon="🔄")
            st.rerun()

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
        background: #1B5FA8;
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
    .arranque-card:hover { border-color: #1B5FA8; }
    .arranque-icono   { font-size: 1.3rem; margin-bottom: 8px; }
    .arranque-titulo  { font-weight: 700; font-size: 0.9rem; margin-bottom: 5px; }
    .arranque-desc    { opacity: 0.52; font-size: 0.79rem; line-height: 1.5; }

    /* Pill de proyecto detectado */
    .pill-proyecto {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        border: 1.5px solid #1B5FA8;
        border-radius: 10px;
        padding: 7px 13px;
        font-size: 0.81rem;
        font-weight: 600;
        margin: 8px 0 4px;
        background: rgba(27,95,168,0.06);
        color: #1B5FA8;
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
                            _r = chat_con_ia([], _ar["msg"])
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
            if any(w in _ult for w in ["logística", "transporte", "flete", "vehículo"]):
                _sugs += ["¿Cuándo uso la Frontier vs la Cheyenne?"]
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
                                _sug
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
                _texto
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
    st.markdown("<h2 style='font-family:Playfair Display,serif'>Perfil de la Empresa y Preferencias</h2>", unsafe_allow_html=True)

    _rol_actual = st.session_state.get("usuario_actual", {}).get("rol", "Operario")
    if _rol_actual == "Admin":
        tab_emp, tab_finanzas, tab_logo, tab_usuarios = st.tabs(["📄 Datos de Facturación", "💰 Finanzas y Bancos", "🎨 Identidad Visual", "👥 Gestión de Usuarios"])
    else:
        tab_emp, tab_finanzas, tab_logo = st.tabs(["📄 Datos de Facturación", "💰 Finanzas y Bancos", "🎨 Identidad Visual"])
        tab_usuarios = None

    with tab_emp:
        c1, c2 = st.columns(2)
        st.session_state.empresa_info["nombre"] = c1.text_input(
            "Razón Social", st.session_state.empresa_info.get("nombre", "MÁRMOLES COLLANTE & CASTRO LTDA."))
        st.session_state.empresa_info["nit"] = c2.text_input(
            "NIT", st.session_state.empresa_info.get("nit", "NIT: 900.111.561-1"))
        st.session_state.empresa_info["ciudad"] = c1.text_input(
            "Ciudad / Dirección", st.session_state.empresa_info.get("ciudad", "Barranquilla, Atlántico — Colombia"))
        st.session_state.empresa_info["tel"] = c2.text_input(
            "Teléfono Comercial", st.session_state.empresa_info.get("tel", "+57 300 000 0000"))
        st.session_state.empresa_info["email"] = st.text_input(
            "Correo de contacto", st.session_state.empresa_info.get("email", "ventas@marmolescc.com"))

        st.markdown("---")
        st.markdown("#### 📝 Términos y Garantías (Aparecen en PDFs)")
        st.session_state.empresa_info["terminos"] = st.text_area(
            "Cláusulas de garantía y condiciones",
            value=st.session_state.empresa_info.get(
                "terminos",
                "Garantía de 1 año en mano de obra de instalación. No cubre manchas por ácidos, "
                "golpes, mal uso o intervención de terceros. Los daños causados por otros gremios "
                "durante la construcción no están cubiertos."
            ),
            height=110,
            placeholder="Ej: Garantía de 1 año en instalación, no cubre manchas por ácidos...",
            help="Este texto aparecerá en el pie de página de las cotizaciones y cuentas de cobro PDF."
        )
        st.markdown("")
        if st.button("💾 Guardar datos de la empresa", type="primary", key="btn_save_emp", use_container_width=True):
            try:
                _guardar_config("empresa_info", st.session_state.empresa_info)
                st.toast("✅ Datos de la empresa guardados y persistidos correctamente", icon="💾")
            except Exception as _e:
                st.error(f"Error al guardar: {_e}")

    with tab_finanzas:
        st.markdown("#### 🏦 Datos Bancarios (Aparecen en los PDFs de cobro)")
        b1, b2 = st.columns(2)
        st.session_state.empresa_info["banco"] = b1.text_input(
            "Banco", st.session_state.empresa_info.get("banco", "Davivienda"))
        _tipos_cuenta = ["Cuenta Corriente Empresas", "Cuenta de Ahorros", "Cuenta Corriente Personal"]
        _tipo_actual = st.session_state.empresa_info.get("cuenta_tipo", "Cuenta Corriente Empresas")
        _tipo_idx = _tipos_cuenta.index(_tipo_actual) if _tipo_actual in _tipos_cuenta else 0
        st.session_state.empresa_info["cuenta_tipo"] = b2.selectbox("Tipo de Cuenta", _tipos_cuenta, index=_tipo_idx)
        st.session_state.empresa_info["cuenta_numero"] = b1.text_input(
            "Número de Cuenta", st.session_state.empresa_info.get("cuenta_numero", "108900027484"))

        st.markdown("---")
        st.markdown("#### 📊 Parámetros Comerciales por Defecto")
        a1, a2 = st.columns(2)
        st.session_state.empresa_info["anticipo_pct"] = a1.number_input(
            "Anticipo exigido (%)",
            min_value=10, max_value=100,
            value=int(st.session_state.empresa_info.get("anticipo_pct", 60)),
            step=5,
            help="Porcentaje de anticipo estándar que aparece en los PDFs de cotización."
        )
        st.session_state.empresa_info["dias_validez"] = a2.number_input(
            "Días de validez de la cotización",
            min_value=5, max_value=90,
            value=int(st.session_state.empresa_info.get("dias_validez", 30)),
            step=5,
            help="Número de días que la cotización tiene validez comercial."
        )
        st.session_state.empresa_info["iva_defecto"] = a1.toggle(
            "Incluir IVA 19% por defecto",
            value=bool(st.session_state.empresa_info.get("iva_defecto", False)),
            help="Si se activa, las nuevas cotizaciones incluirán IVA por defecto."
        )

        # Mostrar resumen bancario
        _emp = st.session_state.empresa_info
        st.markdown(
            f'<div style="background:var(--secondary-background-color);border:1px solid var(--border-color);'
            f'border-radius:10px;padding:14px 18px;margin-top:12px">'
            f'<div style="font-size:0.75rem;font-weight:700;opacity:0.5;margin-bottom:6px">VISTA PREVIA EN PDF</div>'
            f'<div style="font-size:0.88rem"><strong>{_emp.get("banco","")}</strong> · {_emp.get("cuenta_tipo","")} '
            f'· Cta. {_emp.get("cuenta_numero","")}<br>'
            f'Anticipo: <strong>{_emp.get("anticipo_pct",60)}%</strong> · Validez: <strong>{_emp.get("dias_validez",30)} días</strong></div>'
            f'</div>',
            unsafe_allow_html=True
        )
        st.markdown("")
        if st.button("💾 Guardar finanzas y parámetros comerciales", type="primary", key="btn_save_fin", use_container_width=True):
            try:
                _guardar_config("empresa_info", st.session_state.empresa_info)
                st.toast("✅ Datos financieros guardados y persistidos correctamente", icon="💾")
            except Exception as _e:
                st.error(f"Error al guardar: {_e}")

    with tab_logo:
        st.info("El logo se redimensiona automáticamente para el sidebar y los encabezados PDF.", icon="🎨")
        _base_dir_cfg = os.path.dirname(os.path.abspath(__file__))
        _logo_path_cfg = next(
            (os.path.join(_base_dir_cfg, n) for n in
             ["logo_cc.jpeg", "logo_cc.jpg", "logo_cc.png", "Logo_cc.jpeg"]
             if os.path.exists(os.path.join(_base_dir_cfg, n))),
            None
        )
        if st.session_state.get("logo_bytes"):
            st.image(st.session_state.logo_bytes, width=220)
            st.caption("✅ Logo en memoria (subido en esta sesión)")
        elif _logo_path_cfg:
            st.image(_logo_path_cfg, width=220)
            st.caption(f"📁 Logo desde disco: `{os.path.basename(_logo_path_cfg)}`")

        logo = st.file_uploader("Subir nuevo logo (PNG/JPG)", type=["png", "jpg", "jpeg"])
        if logo:
            _logo_raw = logo.read()
            st.session_state.logo_bytes = _logo_raw
            # FIX-3 Serialización Base64: bytes → str UTF-8 antes de JSON/BD.
            # _guardar_logo() llama a base64.b64encode(...).decode('utf-8')
            # para evitar el TypeError que json.dumps lanzaría con bytes crudos.
            try:
                _guardar_logo(_logo_raw)
            except Exception as _le:
                st.warning(f"Logo guardado en sesión pero no persistido en BD: {_le}")
            st.success("✅ Logo cargado y guardado. Ya aparece en el sidebar y en los PDFs.")
            st.rerun()

    # ── Tab de gestión de usuarios (solo Admin) ───────────────────────────────
    if tab_usuarios is not None:
        with tab_usuarios:
            st.markdown("#### 👥 Gestión de Equipo")
            st.caption("Solo los Administradores pueden registrar nuevos usuarios. La contraseña se encripta con PBKDF2-SHA256 antes de guardarse.")

            # ── Formulario de registro con st.form ───────────────────────────
            with st.form("form_nuevo_usuario", clear_on_submit=True):
                st.markdown("**Registrar nuevo usuario**")
                _f1, _f2 = st.columns(2)
                _fu_nombre = _f1.text_input(
                    "Nombre completo *",
                    placeholder="Ej: Jorge Castro Díaz"
                )
                _fu_user = _f2.text_input(
                    "Username *",
                    placeholder="Ej: jcastro  (sin espacios)",
                    help="Se guarda en minúsculas automáticamente."
                )
                _f3, _f4 = st.columns(2)
                _fu_pwd = _f3.text_input(
                    "Contraseña *",
                    type="password",
                    placeholder="Mínimo 6 caracteres"
                )
                _fu_pwd2 = _f4.text_input(
                    "Confirmar contraseña *",
                    type="password",
                    placeholder="Repite la contraseña"
                )
                _f5, _f6 = st.columns(2)
                _fu_pin = _f5.text_input(
                    "PIN de recuperación * (4 dígitos)",
                    placeholder="Ej: 4821",
                    max_chars=4,
                    help="El usuario lo usará para restablecer su contraseña si la olvida."
                )
                _fu_rol = _f6.selectbox(
                    "Rol *",
                    ["Operario", "Admin"],
                    help="Admin: acceso total. Operario: solo sus cotizaciones."
                )

                _submit_form = st.form_submit_button(
                    "✅ Registrar usuario",
                    type="primary",
                    use_container_width=True
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
                    # desde _crear_usuario usando PBKDF2-SHA256
                    _ok_form = _crear_usuario(
                        _fu_user.strip().lower(),
                        _fu_pwd,
                        _fu_pin.strip(),
                        _fu_rol,
                        _fu_nombre.strip()
                    )
                    if _ok_form:
                        st.success(
                            f"✅ Usuario **{_fu_user.strip().lower()}** registrado con rol **{_fu_rol}**.",
                            icon="👤"
                        )
                        st.balloons()
                    else:
                        st.error(
                            "No se pudo crear el usuario. ¿El username ya existe en el sistema?",
                            icon="🚨"
                        )

            st.markdown("---")

            # ── Listado del equipo registrado ─────────────────────────────────
            st.markdown("**Equipo registrado:**")
            _todos_usr = _listar_usuarios()
            _uid_propio = st.session_state.get("usuario_actual", {}).get("id")

            if not _todos_usr:
                st.info("No hay usuarios registrados aún.", icon="ℹ️")
            else:
                # Cabecera
                _hc0, _hc1, _hc2, _hc3 = st.columns([0.4, 2.8, 1.4, 0.8])
                for _hcol, _hlbl in zip([_hc0, _hc1, _hc2, _hc3], ["#", "Nombre / Username", "Rol", "Acción"]):
                    _hcol.markdown(
                        f"<span style='font-size:0.67rem;font-weight:700;opacity:0.4;text-transform:uppercase'>{_hlbl}</span>",
                        unsafe_allow_html=True
                    )
                st.markdown("<hr style='margin:4px 0 8px'>", unsafe_allow_html=True)

                for _i_u, _u in enumerate(_todos_usr):
                    _u_id, _u_name, _u_rol, _u_nom = _u
                    _es_yo = (_u_id == _uid_propio)
                    _uc0, _uc1, _uc2, _uc3 = st.columns([0.4, 2.8, 1.4, 0.8])
                    _uc0.markdown(
                        f"<div style='padding-top:6px;font-size:0.78rem;opacity:0.35'>{_i_u+1}</div>",
                        unsafe_allow_html=True
                    )
                    _uc1.markdown(
                        f"<div style='padding-top:3px'>"
                        f"<span style='font-size:0.87rem;font-weight:700'>{_u_nom or _u_name}</span>"
                        f"<br><span style='font-size:0.7rem;opacity:0.45;font-family:monospace'>{_u_name}</span>"
                        f"</div>",
                        unsafe_allow_html=True
                    )
                    _uc2.markdown(
                        f"<div style='padding-top:7px'>"
                        f"<span style='background:{'#1B5FA8' if _u_rol=='Admin' else '#6b7280'};"
                        f"color:white;font-size:0.63rem;font-weight:700;padding:3px 8px;"
                        f"border-radius:4px;text-transform:uppercase'>{_u_rol}</span>"
                        f"{'<span style="font-size:0.65rem;opacity:0.4;margin-left:5px">(tú)</span>' if _es_yo else ''}"
                        f"</div>",
                        unsafe_allow_html=True
                    )
                    with _uc3:
                        if not _es_yo:
                            if st.button("🗑️", key=f"del_usr_{_u_id}",
                                         help=f"Eliminar {_u_name}"):
                                _eliminar_usuario(_u_id)
                                st.toast(f"Usuario {_u_name} eliminado.", icon="🗑️")
                                st.rerun()
                        else:
                            st.markdown(
                                "<div style='padding-top:6px;font-size:0.7rem;opacity:0.3'>—</div>",
                                unsafe_allow_html=True
                            )
                    if _i_u < len(_todos_usr) - 1:
                        st.markdown("<hr style='margin:3px 0;opacity:0.15'>", unsafe_allow_html=True)

            st.caption("💡 No puedes eliminarte a ti mismo. Para transferir el rol Admin, crea primero otro usuario Admin.")


# ═══════════════════════════════════════════════════════════════════════════════
# GESTIÓN DE EQUIPO — Sección dedicada (solo Admin)
# Accesible desde el menú lateral cuando rol == "Admin"
# ═══════════════════════════════════════════════════════════════════════════════
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
            "<div style='background:rgba(27,95,168,0.06);border-left:3px solid #1B5FA8;"
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
                    f"<span style='background:{'#1B5FA8' if _ge_urol=='Admin' else '#6b7280'};"
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
