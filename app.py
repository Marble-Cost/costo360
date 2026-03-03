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
cookies = CookieManager(prefix="ccmarmol_")
if not cookies.ready():
    st.stop()   # Bloqueo estricto — el script no avanza hasta que React hidrate
_COOKIE_TOKEN = "cm_tok"   # Transporta el UUID del token al navegador

# ── INICIALIZACIÓN DE VARIABLES Y NAVEGACIÓN (CON PERSISTENCIA EN URL) ────────
if "primera_visita" not in st.session_state:
    st.session_state.primera_visita = True
    if st.query_params.get("guia") == "terminada":
        st.session_state.onboarding_activo = False
        st.session_state.tour_completado   = True
    else:
        st.session_state.onboarding_activo = True
        st.session_state.tour_completado   = False
    st.session_state.onboarding_paso = 0

if "nav_radio" not in st.session_state:
    pag_url = st.query_params.get("pagina", "Inicio")
    st.session_state.nav_radio = pag_url
    st.session_state.radio_ui = pag_url
else:
    st.session_state.radio_ui = st.session_state.nav_radio

# ── BASE DE DATOS POSTGRESQL (SUPABASE) ───────────────────────────────────────
def _get_db_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def _init_db():
    conn = _get_db_connection()
    cur = conn.cursor()

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
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS app_config (
            clave TEXT PRIMARY KEY,
            valor TEXT NOT NULL,
            actualizado TEXT DEFAULT ''
        )
    """)
    
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
            cur.execute(f"ALTER TABLE {_tbl} ADD COLUMN IF NOT EXISTS {_col} {_def}")
        except Exception:
            conn.rollback()

    conn.commit()
    cur.close()
    conn.close()

# ── Persistencia de configuración en Supabase ────────────────────────────────
def _guardar_config(clave: str, valor) -> None:
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

def _uid() -> str:
    u = st.session_state.get("usuario_actual")
    if u and u.get("id"):
        return str(u["id"])
    return "anon"

def _clave_borrador_cdir() -> str:
    return f"borrador_cotizacion_directa_{_uid()}"

def _clave_borrador_aiu() -> str:
    return f"borrador_cotizacion_aiu_{_uid()}"

import base64 as _base64

def _guardar_logo(logo_bytes: bytes) -> None:
    logo_b64_str = _base64.b64encode(logo_bytes).decode("utf-8")
    _guardar_config("empresa_logo_b64", logo_b64_str)

def _cargar_logo() -> bytes | None:
    logo_b64_str = _leer_config("empresa_logo_b64")
    if logo_b64_str and isinstance(logo_b64_str, str):
        try:
            return _base64.b64decode(logo_b64_str.encode("utf-8"))
        except Exception:
            return None
    return None

def _cargar_config_desde_db() -> None:
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

    if not st.session_state.get("logo_bytes"):
        _logo_db = _cargar_logo()
        if _logo_db:
            st.session_state["logo_bytes"] = _logo_db

    if not st.session_state.get("chat"):
        try:
            _chat_db = _leer_config(f"chat_{_uid()}")
            if _chat_db and isinstance(_chat_db, list):
                st.session_state["chat"] = _chat_db
        except Exception:
            pass

    st.session_state["_config_cargada"] = True

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
    if m2_retal <= 0:
        return
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM inventario_retales WHERE origen_cotizacion_id = %s", (cot_id,))
    if cur.fetchone()[0] == 0:
        cur.execute(
            """INSERT INTO inventario_retales
               (material_categoria, referencia, m2_disponibles, m2_original,
                origen_cotizacion_id, origen_numero, origen_cliente, fecha_ingreso,
                estado, precio_recuperacion, precio_mercado_m2)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Disponible', 0, %s)""",
            (categoria, referencia or "", round(m2_retal, 4), round(m2_retal, 4),
             cot_id, numero, cliente or "Sin nombre", _hoy().isoformat(),
             round(precio_m2_original, 0))
        )
        conn.commit()
    cur.close()
    conn.close()

def _consultar_retal(categoria: str, referencia: str,
                     usuario_id: int | None = None, rol: str = "Admin") -> list:
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
    if referencia and referencia.strip():
        filtradas = [r for r in rows if r[1].strip().lower() == referencia.strip().lower()]
        return filtradas if filtradas else rows
    return rows

def _marcar_retal_usado(retal_id: int, m2_consumidos: float):
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
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM inventario_retales WHERE origen_cotizacion_id = %s",
        (cot_id,)
    )
    cur.execute("DELETE FROM cotizaciones WHERE id=%s", (cot_id,))
    conn.commit()
    cur.close()
    conn.close()
    st.cache_data.clear()

@st.cache_data(ttl=60)
def _stats_db():
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
    s = {}
    cur.execute("SELECT COUNT(*) FROM cotizaciones")
    s["total"]      = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM cotizaciones WHERE estado='Aprobada'")
    s["aprobadas"]  = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM cotizaciones WHERE estado='Pendiente'")
    s["pendientes"] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM cotizaciones WHERE estado='Rechazada'")
    s["rechazadas"] = cur.fetchone()[0]
    cur.execute("SELECT SUM(precio) FROM cotizaciones WHERE estado='Aprobada'")
    s["facturacion"]= cur.fetchone()[0] or 0
    cur.execute("SELECT AVG(margen) FROM cotizaciones WHERE estado='Aprobada'")
    s["margen_prom"]= cur.fetchone()[0] or 0
    cur.execute("SELECT material,COUNT(*),AVG(margen),SUM(precio) FROM cotizaciones WHERE estado='Aprobada' GROUP BY material")
    s["por_material"]= cur.fetchall()
    cur.execute("SELECT SUBSTR(fecha,1,7),COUNT(*),SUM(precio) FROM cotizaciones WHERE estado='Aprobada' GROUP BY SUBSTR(fecha,1,7) ORDER BY SUBSTR(fecha,1,7) DESC LIMIT 6")
    s["por_mes"]    = cur.fetchall()
    _cerradas = s["aprobadas"] + s["rechazadas"]
    s["tasa_cierre"] = round(s["aprobadas"] / _cerradas * 100, 1) if _cerradas > 0 else 0.0
    cur.close()
    conn.close()
    return s

def _stats_retales() -> dict:
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            material_categoria,
            COUNT(*) AS piezas,
            SUM(m2_disponibles) AS m2_total,
            SUM(m2_disponibles * precio_mercado_m2) AS valor_potencial
        FROM inventario_retales
        WHERE estado = 'Disponible' AND m2_disponibles > 0.05
        GROUP BY material_categoria
        ORDER BY valor_potencial DESC
    """)
    por_categoria = cur.fetchall()
    cur.execute("""
        SELECT
            COUNT(*) AS total_piezas,
            COALESCE(SUM(m2_disponibles), 0) AS m2_total,
            COALESCE(SUM(m2_disponibles * precio_mercado_m2), 0) AS valor_total
        FROM inventario_retales
        WHERE estado = 'Disponible' AND m2_disponibles > 0.05
    """)
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
def _hash_password(password: str) -> str:
    salt = b"cc_marmoles_2026_salt"
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return dk.hex()

def _verificar_password(password: str, hash_almacenado: str) -> bool:
    return _hmac_mod.compare_digest(_hash_password(password), hash_almacenado)

def _device_hint() -> str:
    try:
        from streamlit.web.server.websocket_headers import _get_websocket_headers
        ua = _get_websocket_headers().get("User-Agent", "")
        return ua[:60]
    except Exception:
        return ""

def _crear_sesion(usuario_id: int) -> str:
    token = str(uuid.uuid4())
    expires = datetime.now() + timedelta(days=30)
    try:
        _init_db()
        conn = _get_db_connection()
        cur  = conn.cursor()
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
        pass
    try:
        cookies[_COOKIE_TOKEN] = token
        cookies.save()
    except Exception:
        pass
    st.session_state["_session_token"] = token
    return token

def _validar_token(token: str) -> int | None:
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
              "store_permanente", "_sp_borrador_hash", "_sp_aiu_hash",
              "_borrador_restaurado"]:
        st.session_state.pop(k, None)

def _buscar_usuario_por_id(usuario_id: int) -> dict | None:
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

        with _tab_login:
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
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

            if _btn_login:
                if not _uname or not _pwd:
                    st.error("Completa usuario y contraseña.", icon="⚠️")
                else:
                    with st.spinner("Validando credenciales..."):
                        _usr     = _buscar_usuario_por_username(_uname)
                        _auth_ok = bool(
                            _usr and _verificar_password(_pwd, _usr["password_hash"])
                        )
                    if _auth_ok:
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
@import url('[https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=DM+Sans:wght@300;400;500;600;700&display=swap](https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=DM+Sans:wght@300;400;500;600;700&display=swap)');

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
    return "$" + f"{int(round(valor)):,}".replace(",", ".")

def fmt_decimal(valor: float, decimales: int = 2) -> str:
    fmt = f"{valor:,.{decimales}f}"
    partes = fmt.split(".")
    entero = partes[0].replace(",", ".")
    dec    = partes[1] if len(partes) > 1 else ""
    if not dec or all(c == "0" for c in dec):
        return entero
    return f"{entero},{dec}"

def fmt_m2(valor: float, decimales: int = 3) -> str:
    return fmt_decimal(valor, decimales) + " m²"

def fmt_ml(valor: float, decimales: int = 2) -> str:
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
    "cdir_paso": 0,
    "cdir_success": False,
    "aiu_paso": 0,
    "aiu_success": False,
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

try:
    _cargar_config_desde_db()
except Exception:
    pass

def _sp_init():
    if "store_permanente" in st.session_state:
        return

    _sp_defaults = {
        "cdir_paso": 0,
        "cdir_materiales": [],
        "cdir_piezas": [],
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
        "params_tarifas": None,
        "params_logistica": None,
        "params_viaticos": None,
        "params_adicionales": None,
    }

    sp = dict(_sp_defaults)

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

    if st.session_state.get("tarifas_custom"):
        sp["params_tarifas"]   = st.session_state.tarifas_custom
    if st.session_state.get("logistica_custom"):
        sp["params_logistica"] = st.session_state.logistica_custom
    if st.session_state.get("viaticos_custom"):
        sp["params_viaticos"]  = st.session_state.viaticos_custom
    if st.session_state.get("adicionales_custom"):
        sp["params_adicionales"] = st.session_state.adicionales_custom

    if st.session_state.get("aiu_items"):
        sp["aiu_items"] = st.session_state.aiu_items

    st.session_state.store_permanente = sp

def _sp() -> dict:
    if "store_permanente" not in st.session_state:
        _sp_init()
    return st.session_state.store_permanente

def _sp_set(key: str, value) -> None:
    _sp()[key] = value

def _sp_commit_borrador():
    sp = _sp()
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
    st.session_state.pre = _snapshot
    if st.session_state.get("cdir_piezas") is not None:
        st.session_state.piezas = sp.get("cdir_piezas", [])
    if st.session_state.get("materiales_proyecto") is not None:
        st.session_state.materiales_proyecto = sp.get("cdir_materiales", [])
    try:
        import json as _json
        _h = hash(_json.dumps(_snapshot, sort_keys=True, default=str))
        if _h != st.session_state.get("_sp_borrador_hash"):
            _guardar_config(_clave_borrador_cdir(), _snapshot)
            st.session_state["_sp_borrador_hash"] = _h
    except Exception:
        pass

def _sp_commit_borrador_aiu():
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

def _sp_agregar_pieza():
    piezas = list(_sp().get("cdir_piezas", []))
    piezas.append({"nombre": f"Pieza {len(piezas)+1}",
                   "ml": 1.0, "ancho_tipo": "Mesón de cocina", "ancho_custom": 0.60})
    _sp_set("cdir_piezas", piezas)
    st.session_state.piezas = piezas
    _sp_commit_borrador()

def _sp_eliminar_pieza(idx: int):
    piezas = list(_sp().get("cdir_piezas", []))
    if len(piezas) > 1 and 0 <= idx < len(piezas):
        piezas.pop(idx)
        _sp_set("cdir_piezas", piezas)
        st.session_state.piezas = piezas
        _sp_commit_borrador()

def _sp_sync_piezas(piezas_nuevas: list):
    _sp_set("cdir_piezas", piezas_nuevas)
    st.session_state.piezas = piezas_nuevas
    _sp_commit_borrador()

def _sp_agregar_material():
    mats = list(_sp().get("cdir_materiales", []))
    mats.append({"cat": "Mármol", "ref": "", "precio_m2": 220_000, "area_placa": 5.94})
    _sp_set("cdir_materiales", mats)
    st.session_state.materiales_proyecto = mats
    _sp_commit_borrador()

def _sp_eliminar_material(idx: int):
    mats = list(_sp().get("cdir_materiales", []))
    if 0 <= idx < len(mats):
        mats.pop(idx)
        _sp_set("cdir_materiales", mats)
        st.session_state.materiales_proyecto = mats
        _sp_commit_borrador()

def _sp_sync_materiales(mats_nuevos: list):
    _sp_set("cdir_materiales", mats_nuevos)
    st.session_state.materiales_proyecto = mats_nuevos
    _sp_commit_borrador()

def _sp_agregar_item_aiu():
    items = list(_sp().get("aiu_items", []))
    items.append({"desc": f"Ítem {len(items)+1}", "und": "und", "cant": 1.0, "punit": 0})
    _sp_set("aiu_items", items)
    st.session_state.aiu_items = items
    _sp_commit_borrador_aiu()

def _sp_eliminar_item_aiu(idx: int):
    items = list(_sp().get("aiu_items", []))
    if len(items) > 1 and 0 <= idx < len(items):
        items.pop(idx)
        _sp_set("aiu_items", items)
        st.session_state.aiu_items = items
        _sp_commit_borrador_aiu()

def _sp_sync_items_aiu(items_nuevos: list):
    _sp_set("aiu_items", items_nuevos)
    st.session_state.aiu_items = items_nuevos
    _sp_commit_borrador_aiu()

def _cb_tar(mat: str, campo: str, tipo: str):
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

_sp_init()

_token_actual = _leer_token()

if _token_actual:
    if not st.session_state.get("usuario_actual"):
        _uid_validado = _validar_token(_token_actual)
        if _uid_validado:
            _usr_token = _buscar_usuario_por_id(_uid_validado)
            if _usr_token:
                st.session_state["usuario_actual"] = _usr_token
            else:
                _limpiar_sesion()
                _pantalla_login()
                st.stop()
        else:
            _limpiar_sesion()
            _pantalla_login()
            st.stop()
else:
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

with st.sidebar:
    _base_dir  = os.path.dirname(os.path.abspath(__file__))
    _logo_path = next(
        (os.path.join(_base_dir, n) for n in
         ["logo_cc.jpeg", "logo_cc.jpg", "logo_cc.png",
          "Logo_cc.jpeg", "Logo_cc.jpg", "Logo_cc.png"]
         if os.path.exists(os.path.join(_base_dir, n))),
        None
    )
    if st.session_state.get("logo_bytes"):
        st.image(st.session_state.logo_bytes, use_container_width=True)
    elif _logo_path:
        st.image(_logo_path, use_container_width=True)
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

    _paginas_validas = ["Inicio", "Cotizacion Directa", "Cotizacion AIU",
                        "Historial", "Dashboard", "Banco de Retales",
                        "Parametros", "Asistente IA", "Configuracion", "Gestion de Equipo"]
    if st.session_state.get("nav_radio") not in _paginas_validas:
        st.session_state.nav_radio = "Inicio"
        st.session_state.radio_ui = "Inicio"

    _rol_nav = st.session_state.get("usuario_actual", {}).get("rol", "Operario")
    opciones_menu = ["Inicio", "Cotizacion Directa", "Cotizacion AIU", "Historial", "Dashboard",
                     "Banco de Retales", "Parametros", "Asistente IA", "Configuracion"]
    if _rol_nav == "Admin":
        opciones_menu.append("Gestion de Equipo")

    def update_nav():
        st.session_state.nav_radio = st.session_state.radio_ui
        st.query_params["pagina"] = st.session_state.nav_radio

    st.radio("Menú", opciones_menu, key="radio_ui",
             on_change=update_nav,
             label_visibility="collapsed")
    pagina = st.session_state.nav_radio

    st.markdown('<hr style="margin:12px 0">', unsafe_allow_html=True)
    if ia_disponible():
        st.markdown('<div style="background:rgba(74,222,128,0.15);border:1px solid rgba(74,222,128,0.3);border-radius:6px;padding:7px 10px;font-size:0.75rem;font-weight:600;color:#16a34a">🟢 IA Activa</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="background:rgba(251,191,36,0.12);border:1px solid rgba(251,191,36,0.25);border-radius:6px;padding:7px 10px;font-size:0.75rem;font-weight:600;color:#d97706">🟠 IA sin configurar</div>', unsafe_allow_html=True)

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

    st.markdown('<hr style="margin:12px 0">', unsafe_allow_html=True)
    with st.sidebar.popover("✨ Copiloto IA", use_container_width=True):
        st.markdown(
            "<div style='font-size:0.82rem;font-weight:700;margin-bottom:8px;"
            "color:#1B5FA8'>Asistente contextual</div>"
            "<div style='font-size:0.73rem;opacity:0.6;margin-bottom:10px'>"
            "Toca una pregunta rápida o escribe la tuya.</div>",
            unsafe_allow_html=True
        )

        _sos_ctx = st.session_state.get("nav_radio", "Inicio")

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
                    for _pi, _p in enumerate(_v[:5]):
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

if st.session_state.get("onboarding_activo"):
    _op    = min(st.session_state.get("onboarding_paso", 0), len(TOUR_PASOS) - 1)
    _paso  = TOUR_PASOS[_op]
    _total = len(TOUR_PASOS)

    with st.container(border=True):
        _etiqueta = _paso.get("etiqueta", f"PASO {_op + 1}")
        _es_bienvenida = (_paso.get("id") == "bienvenida")
        if _es_bienvenida:
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
        if _es_bienvenida:
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
        st.markdown(
            f"<div style='margin-top:12px;font-size:0.9rem;line-height:1.72;opacity:0.82'>"
            f"{_paso['cuerpo'].replace(chr(10), '<br>')}</div>",
            unsafe_allow_html=True,
        )
        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        st.progress((_op + 1) / _total)
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

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

def _cargar_en_calculadora(rid, rnum, rjson):
    try:
        datos = json.loads(rjson)
    except Exception:
        st.error("No se pudo leer el JSON de esta cotización.")
        return

    eg = datos.get("_estado_guardado", datos)

    _CLAVES_FORMULARIO = [
        "piezas", "materiales_proyecto", "aiu_items",
        "zocalo_activo", "adicionales_activos", "foraneo_activo",
        "viaticos_activos", "resultado_calculo", "resumen_ia",
        "pre", "editando_id", "cotizacion",
    ]
    for _k in _CLAVES_FORMULARIO:
        st.session_state.pop(_k, None)

    st.session_state.editando_id  = rid
    st.session_state.editando_num = rnum
    eg["_origen"] = "historial"
    st.session_state.pre          = eg

    if "AIU" in rnum or datos.get("tipo_proyecto") == "Licitación AIU" \
            or eg.get("tipo_proyecto") == "Licitación AIU":
        st.session_state.aiu_items = eg.get("aiu_items", [])
        destino = "Cotizacion AIU"
    else:
        destino = "Cotizacion Directa"

    st.session_state.cdir_paso   = 0
    st.session_state.aiu_paso    = 0
    st.session_state.cdir_success = False

    st.session_state.nav_radio = destino
    st.query_params["pagina"]  = destino
    st.rerun()

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
