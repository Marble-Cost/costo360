# app.py — CostoMármol v6 · Adaptive UX & Fixes
# Mármoles Collante & Castro Ltda. · Feb 2026

import io
import base64
import hashlib
import hmac
import secrets
import streamlit as st
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
from asistente_ia import chat_con_ia, ia_disponible, interpretar_proyecto, generar_resumen_cotizacion
import plotly.graph_objects as go

st.set_page_config(
    page_title="CostoMármol — Mármoles Collante & Castro",
    page_icon="🪨",
    layout="wide",
    initial_sidebar_state="expanded",
)

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
    # ── Tabla de sesiones persistentes (reemplaza cookies del browser) ──────────
    # Permite que la sesion sobreviva a F5, cierre de pestana y reinicios.
    # El token viaja en st.query_params["sid"] — se pega en la URL de la app.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sesiones_activas (
            token       TEXT PRIMARY KEY,
            usuario_id  INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
            username    TEXT NOT NULL,
            expiry      TEXT NOT NULL
        )
    """)
    try:
        # Limpiar sesiones expiradas (comparamos como texto ISO8601)
        from datetime import datetime, timezone
        _ahora = datetime.now(timezone.utc).isoformat()
        cur.execute("DELETE FROM sesiones_activas WHERE expiry < %s", (_ahora,))
    except Exception:
        pass
    # ── Migraciones seguras: añade columnas nuevas sin romper datos existentes ──
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
    """Serializa `valor` como JSON y lo guarda/actualiza en app_config."""
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

def _cargar_config_desde_db() -> None:
    """
    Hidrata session_state desde Supabase al arrancar la app.
    Solo sobreescribe si el valor en BD es distinto de None/vacío,
    para no pisar datos que el usuario acaba de editar en esta sesión.
    Marcamos con _config_cargada para ejecutarlo solo una vez por sesión.
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

    st.session_state["_config_cargada"] = True

# ── CRUD Banco de Retales ─────────────────────────────────────────────────────

def _inyectar_retal(cot_id: int, numero: str, cliente: str, categoria: str, referencia: str,
                    m2_retal: float, precio_m2_original: float = 0):
    """Registra el retal de una cotización aprobada en el inventario."""
    if m2_retal <= 0:
        return
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
                estado, precio_recuperacion, precio_mercado_m2)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Disponible', 0, %s)""",
            (categoria, referencia or "", round(m2_retal, 4), round(m2_retal, 4),
             cot_id, numero, cliente or "Sin nombre", _hoy().isoformat(),
             round(precio_m2_original, 0))
        )
        conn.commit()
    cur.close()
    conn.close()

def _consultar_retal(categoria: str, referencia: str) -> list:
    """Retorna retales disponibles para un material/referencia."""
    _init_db()
    conn = _get_db_connection()
    cur = conn.cursor()
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
    cur.execute("SELECT SUM(precio) FROM cotizaciones WHERE estado='Aprobada'")
    s["facturacion"]= cur.fetchone()[0] or 0
    cur.execute("SELECT AVG(margen) FROM cotizaciones WHERE estado='Aprobada'")
    s["margen_prom"]= cur.fetchone()[0] or 0
    cur.execute("SELECT material,COUNT(*),AVG(margen),SUM(precio) FROM cotizaciones WHERE estado='Aprobada' GROUP BY material")
    s["por_material"]= cur.fetchall()
    cur.execute("SELECT SUBSTR(fecha,1,7),COUNT(*),SUM(precio) FROM cotizaciones WHERE estado='Aprobada' GROUP BY SUBSTR(fecha,1,7) ORDER BY SUBSTR(fecha,1,7) DESC LIMIT 6")
    s["por_mes"]    = cur.fetchall()
    cur.close()
    conn.close()
    return s

def _stats_retales() -> dict:
    """Calcula el capital inmovilizado y métricas del banco de retales."""
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


# ═══════════════════════════════════════════════════════════════════════════════
# SISTEMA DE AUTENTICACIÓN MULTI-TENANT
# ═══════════════════════════════════════════════════════════════════════════════

# ── Clave interna para firmar tokens de sesión (se genera una vez por deploy) ─
# Usa APP_SECRET en secrets.toml si existe; si no, usa una clave por defecto.
def _get_secret_key() -> bytes:
    try:
        return st.secrets.get("APP_SECRET", "cc_marbles_secret_2026").encode()
    except Exception:
        return b"cc_marbles_secret_2026"

def _hash_password(password: str) -> str:
    """SHA-256 con salt fijo por usuario (PBKDF2 estilo liviano)."""
    salt = b"cc_marmoles_2026_salt"
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return dk.hex()

def _verificar_password(password: str, hash_almacenado: str) -> bool:
    return hmac.compare_digest(_hash_password(password), hash_almacenado)

def _generar_token(username: str) -> str:
    """Genera un token firmado: base64(username:timestamp):firma_hmac."""
    expiry = (datetime.now(_BOG) + timedelta(days=30)).isoformat()
    payload = f"{username}|{expiry}"
    firma = hmac.new(_get_secret_key(), payload.encode(), hashlib.sha256).hexdigest()
    token_raw = f"{payload}|{firma}"
    return base64.b64encode(token_raw.encode()).decode()

def _validar_token(token: str) -> str | None:
    """Valida el token. Retorna username si es válido y no expiró; None si no."""
    try:
        decoded = base64.b64decode(token.encode()).decode()
        parts = decoded.split("|")
        if len(parts) != 3:
            return None
        username, expiry_str, firma_recibida = parts
        payload = f"{username}|{expiry_str}"
        firma_esperada = hmac.new(_get_secret_key(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(firma_recibida, firma_esperada):
            return None
        expiry = datetime.fromisoformat(expiry_str)
        if datetime.now(_BOG) > expiry:
            return None
        return username
    except Exception:
        return None

# ── PERSISTENCIA DE SESIÓN — BD + query_params ───────────────────────────────
# Estrategia: el token se guarda en la tabla sesiones_activas (PostgreSQL) y
# viaja en la URL como ?sid=<token>. Esto permite que la sesión sobreviva a F5,
# cierre de pestaña y reinicios del servidor sin depender de cookies del browser
# ni de librerías externas.
#
# Ciclo completo:
#   Login → INSERT en sesiones_activas + query_params["sid"] = token
#   F5 / reload → leer query_params["sid"] → verificar en BD → restaurar session_state
#   Logout → DELETE de BD + borrar query_params["sid"]

def _guardar_sesion_bd(token: str, usuario_id: int, username: str) -> bool:
    """Persiste el token en la BD y lo pone en la URL."""
    try:
        _init_db()
        conn = _get_db_connection()
        cur  = conn.cursor()
        expiry = (datetime.now(_BOG) + timedelta(days=30)).isoformat()
        cur.execute(
            """INSERT INTO sesiones_activas (token, usuario_id, username, expiry)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (token) DO UPDATE SET expiry = EXCLUDED.expiry""",
            (token, usuario_id, username, expiry)
        )
        conn.commit()
        cur.close()
        conn.close()
        # Guardar también en session_state + URL para acceso inmediato
        st.session_state["_auth_token"] = token
        st.query_params["sid"] = token
        return True
    except Exception:
        return False

def _verificar_sesion_bd(token: str) -> str | None:
    """
    Valida el token contra la BD.
    Retorna username si es válido y no expiró; None si no.
    También verifica la firma HMAC para doble seguridad.
    """
    # Primero validar firma criptográfica (evita consultas con tokens falsos)
    username_tok = _validar_token(token)
    if not username_tok:
        return None
    # Luego verificar que exista en BD y no haya expirado
    try:
        _init_db()
        conn = _get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            "SELECT username, expiry FROM sesiones_activas WHERE token = %s",
            (token,)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return None
        _username_bd, _expiry_str = row
        # Verificar expiración
        try:
            _expiry = datetime.fromisoformat(_expiry_str)
            # Normalizar a naive si es necesario para comparación
            _now = datetime.now(_BOG)
            if _expiry.tzinfo is None:
                _now = datetime.now()
            if _now > _expiry:
                return None
        except Exception:
            pass
        return _username_bd
    except Exception:
        # Si hay error de BD, hacer fallback a validación HMAC pura
        return username_tok

def _leer_cookie_sesion() -> str | None:
    """
    Lee el token de sesión desde (en orden de prioridad):
    1. session_state (mismo rerun de Streamlit)
    2. query_params ?sid= (recarga de página / F5 / nueva pestaña)
    """
    # Prioridad 1: session_state (ya verificado en este ciclo de vida)
    tok = st.session_state.get("_auth_token")
    if tok:
        return tok
    # Prioridad 2: URL query_params (persiste entre F5)
    tok_url = st.query_params.get("sid")
    if tok_url:
        st.session_state["_auth_token"] = tok_url  # cachear para este ciclo
        return tok_url
    return None

# Alias de compatibilidad (la firma de la función anterior)
def _guardar_cookie_sesion(token: str):
    st.session_state["_auth_token"] = token

def _limpiar_sesion():
    """Cierra sesión: elimina token de BD, query_params y session_state."""
    # Borrar de la BD
    tok = st.session_state.get("_auth_token") or st.query_params.get("sid")
    if tok:
        try:
            _init_db()
            conn = _get_db_connection()
            cur  = conn.cursor()
            cur.execute("DELETE FROM sesiones_activas WHERE token = %s", (tok,))
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            pass
    # Borrar de la URL
    try:
        st.query_params.clear()
    except Exception:
        try:
            if "sid" in st.query_params:
                del st.query_params["sid"]
        except Exception:
            pass
    # Borrar session_state
    for k in ["usuario_actual", "_auth_token", "_config_cargada",
              "cotizacion", "pre", "piezas", "materiales_proyecto",
              "chat", "resumen_ia"]:
        st.session_state.pop(k, None)

# ── CRUD de usuarios ──────────────────────────────────────────────────────────

def _buscar_usuario_por_username(username: str) -> dict | None:
    """Retorna dict con datos del usuario o None si no existe."""
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
    """Crea un usuario nuevo. Retorna True si tuvo éxito."""
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
    """Actualiza la contraseña de un usuario."""
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
    """Lista todos los usuarios (para panel Admin)."""
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
    """
    Crea el usuario admin por defecto si la tabla de usuarios está vacía.
    Credenciales: admin / admin123 / PIN: 0000
    IMPORTANTE: cambiar tras el primer login.
    """
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

def _pantalla_login():
    """Renderiza la pantalla de login y maneja el flujo de autenticación."""
    _asegurar_admin_existe()

    # CSS exclusivo del login
    st.markdown("""
    <style>
    .login-wrapper {
        max-width: 420px;
        margin: 60px auto 0;
    }
    .login-logo {
        text-align: center;
        padding: 28px 0 18px;
    }
    .login-logo .brand {
        font-family: 'Playfair Display', serif;
        font-size: 2.2rem;
        font-weight: 900;
        color: #C9A84C;
        line-height: 1;
    }
    .login-logo .sub {
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        opacity: 0.55;
        text-transform: uppercase;
        margin-top: 4px;
    }
    .login-title {
        font-family: 'Playfair Display', serif;
        font-size: 1.45rem;
        font-weight: 700;
        color: #1B5FA8;
        margin-bottom: 4px;
        text-align: center;
    }
    </style>
    """, unsafe_allow_html=True)

    _, col, _ = st.columns([1, 2, 1])
    with col:
        # Logo / identidad
        st.markdown("""
        <div class="login-logo">
            <div class="brand">CC</div>
            <div class="sub">Mármoles Collante &amp; Castro</div>
        </div>
        <div class="login-title">Iniciar Sesión</div>
        """, unsafe_allow_html=True)

        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

        with st.container(border=True):
            _tab_login, _tab_pin = st.tabs(["🔐 Acceder", "🔑 Recuperar contraseña"])

            # ── Tab login principal ───────────────────────────────────────────
            with _tab_login:
                st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
                _uname = st.text_input("Usuario", placeholder="Ej: jcastro",
                                       key="login_username")
                _pwd   = st.text_input("Contraseña", type="password",
                                       placeholder="••••••••", key="login_password")

                if st.button("Ingresar →", type="primary",
                             use_container_width=True, key="btn_login"):
                    if not _uname or not _pwd:
                        st.error("Completa usuario y contraseña.", icon="⚠️")
                    else:
                        _usr = _buscar_usuario_por_username(_uname)
                        if _usr and _verificar_password(_pwd, _usr["password_hash"]):
                            # Login exitoso: generar token y persistir en BD + URL
                            token = _generar_token(_usr["username"])
                            _guardar_sesion_bd(token, _usr["id"], _usr["username"])
                            st.session_state["usuario_actual"] = _usr
                            st.success(f"Bienvenido, {_usr['nombre_completo'] or _usr['username']}!")
                            st.rerun()
                        else:
                            st.error("Usuario o contraseña incorrectos.", icon="🚨")

                st.markdown(
                    "<div style='font-size:0.72rem;opacity:0.45;text-align:center;"
                    "margin-top:10px'>Sistema de uso exclusivo · Mármoles Collante &amp; Castro</div>",
                    unsafe_allow_html=True
                )

            # ── Tab recuperación por PIN ──────────────────────────────────────
            with _tab_pin:
                st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
                st.caption("Ingresa tu usuario y el PIN de recuperación de 4 dígitos.")
                _rec_user = st.text_input("Usuario", placeholder="Ej: jcastro",
                                          key="rec_username")
                _rec_pin  = st.text_input("PIN de recuperación (4 dígitos)",
                                          placeholder="0000", max_chars=4,
                                          key="rec_pin")

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

                # Mostrar campos de nueva contraseña solo si el PIN fue verificado
                if st.session_state.get("_pin_verificado_user"):
                    st.markdown("---")
                    _nueva_pwd  = st.text_input("Nueva contraseña", type="password",
                                                placeholder="Mínimo 6 caracteres",
                                                key="nueva_pwd")
                    _confirmar  = st.text_input("Confirmar contraseña", type="password",
                                                placeholder="Repite la contraseña",
                                                key="confirmar_pwd")
                    if st.button("Guardar nueva contraseña", type="primary",
                                 use_container_width=True, key="btn_cambiar_pwd"):
                        if len(_nueva_pwd) < 6:
                            st.error("La contraseña debe tener al menos 6 caracteres.")
                        elif _nueva_pwd != _confirmar:
                            st.error("Las contraseñas no coinciden.")
                        else:
                            _ok = _actualizar_password(
                                st.session_state["_pin_verificado_user"], _nueva_pwd
                            )
                            if _ok:
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

# ── MURO DE AUTENTICACIÓN ─────────────────────────────────────────────────────
# Verifica sesión activa antes de renderizar cualquier contenido de la app.
# Flujo:
#   1. Si hay token válido en session_state → restaurar usuario_actual desde BD
#   2. Si no hay token o expiró → mostrar pantalla de login y detener ejecución
# ── MURO DE AUTENTICACIÓN ─────────────────────────────────────────────────────
# Orden de verificación:
#   1. session_state["usuario_actual"] → ya autenticado en este ciclo, pasar
#   2. Token en session_state o URL (?sid=) → verificar firma + BD → restaurar
#   3. Sin token → pantalla de login
_token_sesion = _leer_cookie_sesion()
if not st.session_state.get("usuario_actual"):
    if _token_sesion:
        # Verificar firma HMAC + existencia/expiración en BD
        _username_restaurado = _verificar_sesion_bd(_token_sesion)
        if _username_restaurado:
            _usr_restaurado = _buscar_usuario_por_username(_username_restaurado)
            if _usr_restaurado:
                st.session_state["usuario_actual"] = _usr_restaurado
                # Mantener el sid en la URL para próximas recargas
                st.query_params["sid"] = _token_sesion
            else:
                # Token válido pero usuario borrado de BD
                _limpiar_sesion()
                _pantalla_login()
                st.stop()
        else:
            # Token inválido o expirado
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
    if st.session_state.get("nav_radio") not in ["Inicio", "Cotizacion Directa", "Cotizacion AIU",
                                                   "Historial", "Dashboard", "Banco de Retales",
                                                   "Parametros", "Asistente IA", "Configuracion"]:
        st.session_state.nav_radio = "Inicio"
        st.session_state.radio_ui = "Inicio"

    opciones_menu = ["Inicio", "Cotizacion Directa", "Cotizacion AIU", "Historial", "Dashboard", "Banco de Retales", "Parametros", "Asistente IA", "Configuracion"]

    def update_nav():
        st.session_state.nav_radio = st.session_state.radio_ui
        # Persistir la página en la URL para sobrevivir a F5
        st.query_params["pagina"] = st.session_state.nav_radio

    _nav_idx = opciones_menu.index(st.session_state.nav_radio) \
               if st.session_state.nav_radio in opciones_menu else 0
    st.radio("Menú", opciones_menu, key="radio_ui",
             index=_nav_idx, on_change=update_nav,
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
    st.markdown("<h2 style='font-family:Playfair Display,serif;margin-bottom:4px'>Cotizacion Directa</h2>", unsafe_allow_html=True)
    st.markdown("<p style='opacity:0.7;font-size:0.88rem;margin-bottom:20px'>Para proyectos residenciales y clientes particulares</p>", unsafe_allow_html=True)

    pre = st.session_state.pre

    # [PERSISTENCIA] Si el formulario está vacío (recién recargado con F5) y hay
    # un borrador guardado en BD, restaurarlo automáticamente una sola vez.
    if not pre and not st.session_state.get("_borrador_restaurado"):
        try:
            _borrador = _leer_config("borrador_cotizacion_directa")
            if _borrador:
                _borrador["_origen"] = "borrador"
                st.session_state.pre  = _borrador
                pre = _borrador
        except Exception:
            pass
        st.session_state["_borrador_restaurado"] = True

    # Mostrar alerta SOLO cuando los datos vienen de Historial o IA (no del autosave propio)
    if pre and pre.get("_origen") in ("historial", "ia"):
        alerta("Datos cargados exitosamente (desde Historial o IA). Revisa y ajusta lo que necesites.", "bueno")
        # Limpiar el marcador de origen para que no reaparezca en cada render
        st.session_state.pre.pop("_origen", None)
    elif pre and pre.get("_origen") == "borrador":
        alerta("📋 Se restauró tu último cálculo guardado (antes de la recarga). Puedes continuar donde lo dejaste.", "info")
        st.session_state.pre.pop("_origen", None)
    if pre and pre.get("nombre_cliente") or pre.get("piezas") or pre.get("materiales_proyecto"):
        if st.button("🗑️ Limpiar formulario y empezar de cero"):
            st.session_state.pre = {}
            st.session_state.piezas = []
            st.session_state.materiales_proyecto = []
            # Limpiar también los keys de widgets para que vuelvan a defaults
            for _wk in [k for k in st.session_state if k.startswith("cdir_")]:
                del st.session_state[_wk]
            st.rerun()

    TARIFAS_ACT = get_tarifas()
    LOG_ACT = get_logistica()
    VIA_ACT = get_viaticos()

    # ── PASO 1: MATERIAL(ES) ─────────────────────────────────────────────────
    seccion_titulo("Paso 1 — Material(es)", "Puedes agregar uno o más materiales si el proyecto mezcla referencias")

    with st.expander("❓ ¿Cómo lleno este paso? — Ayuda rápida", expanded=False):
        st.markdown("""
**Categoría:** El tipo de piedra o material que vas a instalar (Mármol, Granito, etc.).

**Referencia:** El nombre específico de la lámina que compraste, por ejemplo "Crema Marfil" o "Calacatta Gold". Si no sabes el nombre exacto, deja "Otra referencia" y escríbelo.

**Precio por m² (COP):** Exactamente lo que te cobró el proveedor por cada metro cuadrado del material. 
Está en la factura de compra. **No lo inventes — usa el valor real de lo que pagaste.**

**Área comprada (m²):** Los metros cuadrados totales de material que compraste. 
Está en la factura. Ejemplo: si compraste una lámina de 1,20 m × 2,60 m = **3,12 m²**.

> 💡 Si tienes sobrante de un proyecto anterior, la app te avisará aquí con un aviso azul y podrás usarlo gratis.
        """)

    # Inicializar lista de materiales si no existe
    if "materiales_proyecto" not in st.session_state or not st.session_state.materiales_proyecto:
        st.session_state.materiales_proyecto = pre.get("materiales_proyecto", [
            {"cat": pre.get("categoria", "Mármol"), "ref": pre.get("referencia", ""), "precio_m2": pre.get("precio_m2", 220_000), "area_placa": pre.get("area_placa_comprada", 5.94)}
        ])

    mats = st.session_state.materiales_proyecto
    mats_nuevos = []

    for midx, mat_item in enumerate(mats):
        with st.container(border=True):
            lbl = f"Material {midx + 1}" if len(mats) > 1 else "Material del proyecto"
            cola, colb, colc, cold = st.columns([1.8, 1.5, 1.5, 0.4])
            with cola:
                cats_opts = CATEGORIAS_MATERIAL
                cat_i = cats_opts.index(mat_item.get("cat", "Mármol")) if mat_item.get("cat") in cats_opts else 0
                cat_sel_m = st.selectbox("Categoría", cats_opts, index=cat_i, key=f"mcat_{midx}", label_visibility="collapsed" if midx > 0 else "visible")
            with colb:
                refs_m = ["Otra referencia..."] + [m["nombre"] for m in MATERIALES_CATALOGO if m["categoria"] == cat_sel_m]
                pre_ref_m = mat_item.get("ref", "")
                idx_ref_m = refs_m.index(pre_ref_m) if pre_ref_m in refs_m else 0
                ref_sel_m = st.selectbox("Referencia", refs_m, index=idx_ref_m, key=f"mref_{midx}", label_visibility="visible" if midx == 0 else "collapsed")
                if ref_sel_m == "Otra referencia...":
                    referencia_m = st.text_input("Nombre", value=pre_ref_m if pre_ref_m not in refs_m else "", key=f"mrefcust_{midx}", placeholder="Ej: Calacatta Gold")
                else:
                    referencia_m = ref_sel_m
                    m_cat_data = next((m for m in MATERIALES_CATALOGO if m["nombre"] == ref_sel_m), None)
            with colc:
                precio_m2_m = st.number_input("Precio/m² (COP)", min_value=10_000, max_value=5_000_000,
                    value=int(mat_item.get("precio_m2", 220_000)), step=1_000, key=f"mpm2_{midx}",
                    label_visibility="visible" if midx == 0 else "collapsed")
                area_placa_m = st.number_input("Área comprada (m²)", min_value=0.01, max_value=200.0,
                    value=float(mat_item.get("area_placa", 5.94)), step=0.1, key=f"maplaca_{midx}", format="%.3f",
                    label_visibility="visible" if midx == 0 else "collapsed")
            with cold:
                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                if len(mats) > 1 and st.button("✕", key=f"mdel_{midx}"):
                    st.session_state.materiales_proyecto.pop(midx)
                    st.rerun()

            costo_m = precio_m2_m * area_placa_m
            st.caption(f"Costo: {numero_completo(precio_m2_m)}/m² × {area_placa_m} m² = **{numero_completo(costo_m)}**")

            # ── Banco de Retales: detectar disponibilidad ─────────────────────
            _mat_dict = {"cat": cat_sel_m, "ref": referencia_m, "precio_m2": precio_m2_m, "area_placa": area_placa_m}
            try:
                _retales_disp = _consultar_retal(cat_sel_m, referencia_m)
            except Exception:
                _retales_disp = []

            if _retales_disp:
                _m2_total_retal = sum(r[2] for r in _retales_disp)
                _retal_key = f"usar_retal_{midx}"
                _usando_retal = st.session_state.get(_retal_key, False)

                if not _usando_retal:
                    # Aviso visual elegante
                    _num_piezas = len(_retales_disp)
                    _orig_txt = _retales_disp[0][3] if _num_piezas == 1 else f"{_num_piezas} proyectos anteriores"
                    st.markdown(
                        f'<div style="border:1px solid #1B5FA8;border-left:4px solid #1B5FA8;'
                        f'border-radius:8px;padding:10px 16px;margin:8px 0;'
                        f'background:rgba(27,95,168,0.06);">'
                        f'<div style="font-size:0.8rem;font-weight:700;color:#1B5FA8;margin-bottom:4px">'
                        f'Tienes {fmt_m2(_m2_total_retal, 2)} de este material en tu Banco de Retales'
                        f'</div>'
                        f'<div style="font-size:0.75rem;opacity:0.65">'
                        f'Origen: {_orig_txt} · Usar retal fija el precio en $0 y dispara el margen</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                    _col_rb, _ = st.columns([1.4, 2.6])
                    with _col_rb:
                        if st.button("Usar retal existente →", key=f"btn_retal_{midx}", type="primary", use_container_width=True):
                            st.session_state[_retal_key] = True
                            # Seleccionar el retal con más m²
                            _retal_sel = max(_retales_disp, key=lambda r: r[2])
                            st.session_state[f"retal_id_{midx}"]  = _retal_sel[0]
                            st.session_state[f"retal_m2_{midx}"]  = _retal_sel[2]
                            st.rerun()
                else:
                    # Estado activo: retal en uso — sobreescribir valores del dict
                    _rid_activo = st.session_state.get(f"retal_id_{midx}")
                    _rm2_activo = st.session_state.get(f"retal_m2_{midx}", _m2_total_retal)

                    # Leer precio de recuperación configurado para este retal
                    _precio_rec = 0.0
                    try:
                        _conn_rec = _get_db_connection()
                        _cur_rec  = _conn_rec.cursor()
                        _cur_rec.execute(
                            "SELECT precio_recuperacion FROM inventario_retales WHERE id=%s",
                            (_rid_activo,)
                        )
                        _row_rec = _cur_rec.fetchone()
                        _precio_rec = float(_row_rec[0] or 0) if _row_rec else 0.0
                        _cur_rec.close()
                        _conn_rec.close()
                    except Exception:
                        _precio_rec = 0.0

                    _mat_dict["precio_m2"]  = _precio_rec   # precio_recuperacion (0 si no configurado)
                    _mat_dict["area_placa"] = _rm2_activo
                    _mat_dict["es_retal"]   = True
                    _mat_dict["retal_id"]   = _rid_activo

                    _prec_txt = f"Precio/m² de recuperación: {numero_completo(_precio_rec)}" if _precio_rec > 0 else "Precio/m² fijado en $0"
                    st.markdown(
                        f'<div style="border:1px solid #15803d;border-left:4px solid #15803d;'
                        f'border-radius:8px;padding:10px 16px;margin:8px 0;'
                        f'background:rgba(21,128,61,0.06);">'
                        f'<div style="font-size:0.8rem;font-weight:700;color:#15803d;margin-bottom:3px">'
                        f'Retal activo — {_prec_txt} · Área disponible: {fmt_m2(_rm2_activo, 3)}'
                        f'</div>'
                        f'<div style="font-size:0.75rem;opacity:0.65">'
                        f'El margen sube al 80-90%+ según los demás costos. Configura el precio de recuperación en Banco de Retales.</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                    if st.button("Cancelar — usar material nuevo", key=f"btn_cancel_retal_{midx}"):
                        st.session_state.pop(_retal_key, None)
                        st.session_state.pop(f"retal_id_{midx}", None)
                        st.session_state.pop(f"retal_m2_{midx}", None)
                        st.rerun()

            mats_nuevos.append(_mat_dict)

    st.session_state.materiales_proyecto = mats_nuevos

    col_addmat, _ = st.columns([1, 3])
    with col_addmat:
        if st.button("+ Agregar otro material", use_container_width=True):
            st.session_state.materiales_proyecto.append({"cat": "Mármol", "ref": "", "precio_m2": 220_000, "area_placa": 5.94})
            st.rerun()

    # Para el cálculo usamos el primer material como principal (categoría determina tarifas de MO)
    # El costo total de material suma todos
    cat_sel = mats_nuevos[0]["cat"] if mats_nuevos else "Mármol"
    referencia = " + ".join([m["ref"] or m["cat"] for m in mats_nuevos]) if len(mats_nuevos) > 1 else (mats_nuevos[0]["ref"] if mats_nuevos else "")
    precio_m2 = mats_nuevos[0]["precio_m2"] if mats_nuevos else 220_000
    # Área total y costo total de todos los materiales
    area_placa = sum(m["area_placa"] for m in mats_nuevos)
    costo_mat_total = sum(m["precio_m2"] * m["area_placa"] for m in mats_nuevos)
    # Precio_m2 efectivo para que calcular_cotizacion_directa compute correctamente c1
    precio_m2_efectivo = costo_mat_total / area_placa if area_placa > 0 else precio_m2

    alerta(f"Total material: **{numero_completo(costo_mat_total)}** en {fmt_m2(area_placa, 2)} comprados", "info")

    st.markdown("---")

    # ── PASO 2: DIMENSIONES ──────────────────────────────────────────────────
    seccion_titulo("Paso 2 — Dimensiones del proyecto", "Ingresa cada pieza por metros lineales — la app convierte a m² automaticamente")

    with st.expander("❓ ¿Cómo mido las piezas? — Ayuda con metros lineales", expanded=False):
        st.markdown("""
**¿Qué es un metro lineal (ML)?**

En marmolería, se habla de **metros lineales de largo**, no de metros cuadrados. 
La app necesita el **largo** de cada pieza, y el ancho ya está preconfigurado según el tipo de elemento.

**Ejemplo práctico:**
- Mesón de cocina de 3 metros de largo → ingresas **3 ML** en "Largo"
- El ancho estándar de un mesón es 0,60 m → la app calcula 3 × 0,60 = **1,80 m²** automáticamente

**¿Qué es una "pieza"?**

Cada elemento de piedra es una pieza. Si un mesón en L tiene dos tramos, son dos piezas separadas.

**Tipos más comunes y su ancho estándar:**
- Mesón de cocina: 0,60 m de ancho
- Baño / lavamanos: 0,45 m de ancho  
- Zócalo: 0,10 m de ancho
- Escalón (huella): 0,30 m de ancho
- Piso / revestimiento: se mide en m² directamente

> 💡 Si el ancho de tu pieza es diferente al estándar, selecciona **"Personalizado"** e ingresa el valor real.
        """)

    if "piezas" not in st.session_state or not st.session_state.piezas:
        st.session_state.piezas = pre.get("piezas", [{"nombre": "Meson de cocina", "ml": 2.0, "ancho_tipo": "Mesón de cocina", "ancho_custom": 0.60}])

    _mostrar_avanzado = st.session_state.get("modo_avanzado_medidas", False)
    if not _mostrar_avanzado:
        modo_medida = "Por piezas (ML × Ancho) — recomendado"
        if st.button("Opciones avanzadas (ingresar m² directamente)"):
            st.session_state.modo_avanzado_medidas = True
            st.rerun()
    else:
        modo_medida = st.radio("Modo de ingreso", ["Por piezas (ML × Ancho) — recomendado", "Ingresar m² directamente"], horizontal=True, key="cdir_modo_medida")
        if st.button("Volver al modo simplificado"):
            st.session_state.modo_avanzado_medidas = False
            st.rerun()

    m2_real = 0.0
    m2_cortados_total = 0.0

    if "Por piezas" in modo_medida:
        alerta("Agrega cada pieza del proyecto. Largo en ML × ancho estandar = m² calculados.", "info")
        hdr = st.columns([3, 1.2, 2.5, 1.5, 1.6, 0.6])
        for col, lbl in zip(hdr, ["Pieza / Descripcion", "ML largo", "Elemento / Pieza", "Ancho (m)", "m² calculados", ""]):
            col.markdown(f"<div style='font-size:0.72rem;font-weight:700;opacity:0.6;text-transform:uppercase'>{lbl}</div>", unsafe_allow_html=True)

        tipos_superficie = list(ANCHOS_ESTANDAR.keys())
        piezas_nuevas = []
        total_m2_piezas = 0.0

        for idx, pieza in enumerate(st.session_state.piezas):
            c0, c1, c2, c3, c4, c5 = st.columns([3, 1.2, 2.5, 1.5, 1.6, 0.6])
            with c0:
                nombre_p = st.text_input("Nombre", value=pieza.get("nombre", ""), key=f"pnom_{idx}", label_visibility="collapsed")
            with c1:
                ml_p = st.number_input("ML", value=float(pieza.get("ml", 1.0)), min_value=0.01, step=0.1, key=f"pml_{idx}", label_visibility="collapsed")
            with c2:
                tipo_idx = tipos_superficie.index(pieza.get("ancho_tipo", tipos_superficie[0])) if pieza.get("ancho_tipo") in tipos_superficie else 0
                ancho_tipo_p = st.selectbox("Elemento", tipos_superficie, index=tipo_idx, key=f"ptip_{idx}", label_visibility="collapsed")
            with c3:
                ancho_def = ANCHOS_ESTANDAR[ancho_tipo_p]["ancho"] or pieza.get("ancho_custom", 0.60)
                ancho_p = st.number_input("Ancho", value=float(ancho_def), min_value=0.01, step=0.01, key=f"panc_{idx}", label_visibility="collapsed")
            m2_p = ml_a_m2(ml_p, ancho_p)
            total_m2_piezas += m2_p
            with c4:
                st.markdown(f"<div style='padding:8px 4px;font-weight:700;'>{fmt_m2(m2_p)}</div>", unsafe_allow_html=True)
            with c5:
                if st.button("X", key=f"del_{idx}") and len(st.session_state.piezas) > 1:
                    st.session_state.piezas.pop(idx)
                    st.rerun()

            # ── Input dinámico para tipo "Personalizado" ──────────────────────
            nombre_personalizado_p = pieza.get("nombre_personalizado", "")
            if ancho_tipo_p == "Personalizado":
                nombre_personalizado_p = st.text_input(
                    "Descripción del elemento",
                    value=nombre_personalizado_p,
                    key=f"pcustom_{idx}",
                    placeholder='Ej: "Mesón de lavamanos", "Pantry", "Repisa"',
                    help="Este nombre aparecerá en el PDF de cotización.",
                )

            piezas_nuevas.append({
                "nombre": nombre_p,
                "ml": ml_p,
                "ancho_tipo": ancho_tipo_p,
                "ancho_custom": ancho_p,
                "nombre_personalizado": nombre_personalizado_p,
            })

        st.session_state.piezas = piezas_nuevas
        m2_real = total_m2_piezas
        m2_cortados_total = total_m2_piezas

        col_add, col_sum = st.columns([1, 2])
        with col_add:
            if st.button("+ Agregar pieza", use_container_width=True):
                st.session_state.piezas.append({"nombre": f"Pieza {len(st.session_state.piezas)+1}", "ml": 1.0, "ancho_tipo": tipos_superficie[0], "ancho_custom": 0.60})
                st.rerun()
        with col_sum:
            if m2_real > 0:
                _ml_total = sum(p.get("ml", 0) for p in st.session_state.piezas)
                st.markdown(
                    f'''<div style="background:var(--secondary-background-color); border:1px solid var(--border-color); border-radius:10px;padding:12px 18px;text-align:center">
                  <div style="font-size:0.7rem;color:#1B5FA8;text-transform:uppercase;letter-spacing:0.08em;font-weight:700">Total del proyecto</div>
                  <div style="font-size:2rem;font-weight:900;font-family:'Playfair Display',serif">{fmt_ml(_ml_total)}</div>
                  <div style="font-size:0.85rem;opacity:0.7;margin-top:2px">{fmt_m2(m2_real)} de material</div>
                </div>''', unsafe_allow_html=True)
        # Desperdicio: gestionado en la sección de Gestión de Desperdicio más abajo
        # (extra_corte se suma a m2_cortados_total en la sección de Gestión de Desperdicio)

    else:
        c1, c2 = st.columns(2)
        with c1:
            m2_real = st.number_input("m² reales del proyecto", min_value=0.01, value=float(pre.get("m2_proyecto", 4.0)), step=0.05, key="cdir_m2_real")
        with c2:
            m2_cortados_input = st.number_input("m² cortados de la placa (mayor por desperdicios)", min_value=0.0, value=float(pre.get("m2_cortados_input", m2_real)), step=0.05, key="cdir_m2_cortados")
            m2_cortados_total = m2_cortados_input if m2_cortados_input > 0 else m2_real

    st.markdown("---")
    # ── Sincronización automática de m² finalmente instalados ─────────────────
    # Cuando el usuario modifica ML o ancho de una pieza, m2_real cambia pero el
    # widget "cdir_m2_usados" conserva el valor anterior porque Streamlit lo
    # almacena en session_state por key. Detectamos el cambio y reseteamos el
    # widget para que refleje siempre los m² actuales del proyecto.
    _m2_real_prev = st.session_state.get("_cdir_m2_real_prev", None)
    if _m2_real_prev is None or abs(_m2_real_prev - m2_real) > 0.001:
        # m2_real cambió (o es la primera vez) → forzar actualización del widget
        st.session_state["cdir_m2_usados"] = round(m2_real, 3)
        st.session_state["_cdir_m2_real_prev"] = m2_real

    c1, c2, c3 = st.columns(3)
    with c1:
        m2_usados = st.number_input("m² finalmente instalados", min_value=0.0, value=float(pre.get("m2_usados", m2_real)), step=0.05, key="cdir_m2_usados")
    with c2:
        margen_pct = st.slider(
            "Margen de ganancia (%)",
            min_value=5, max_value=80,
            value=int(pre.get("margen_pct", 40)),
            step=1, key="cdir_margen",
            help=(
                "El margen es la ganancia que quieres llevarte sobre el precio de venta.\n\n"
                "Ejemplo con margen 40%: si tus costos son $600.000, el precio de venta será $1.000.000 "
                "y tu ganancia son $400.000.\n\n"
                "✅ Saludable: 30-45% | ⚠️ Aceptable: 20-30% | 🚨 Riesgo: menos del 20%"
            )
        )
    with c3:
        if area_placa > 0 and m2_usados > 0:
            aprv = min(100, m2_usados / area_placa * 100)
            retal = max(0, area_placa - m2_usados)
            estado_a = "bueno" if aprv >= 80 else "acepta" if aprv >= 50 else "bajo"
            alerta(
                f"Uso del material: **{aprv:.1f}%** — Sobra: {fmt_m2(retal)}",
                estado_a
            )
            if retal > 0.1:
                st.caption(
                    f"💡 Sobran **{fmt_m2(retal)}** de material. Si guardas ese pedazo, "
                    f"el sistema lo registrará como sobrante aprovechable para el próximo proyecto."
                )

    st.markdown("---")

    # ── PASO 3: PROYECTO ─────────────────────────────────────────────────────
    seccion_titulo("Paso 3 — Tipo de proyecto y obra")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        tipo_opts = ["Mesón", "Cocina", "Baño", "Piso", "Escalera", "Fachada", "Mueble de cocina", "Otro"]
        # Multi-select para tipo de proyecto
        pre_tipos = pre.get("tipos_proyecto", [pre.get("tipo_proyecto", "Mesón")] if pre.get("tipo_proyecto") else ["Mesón"])
        tipos_sel = st.multiselect(
            "Tipo(s) de proyecto",
            tipo_opts,
            default=[t for t in pre_tipos if t in tipo_opts] or ["Mesón"],
            help="Selecciona uno o varios si el proyecto combina espacios (ej: Cocina + Baño)",
            key="cdir_tipos_proyecto"
        )
        tipo = " + ".join(tipos_sel) if tipos_sel else "Otro"
    with c2:
        etapa = ETAPAS_OBRA[st.selectbox("Etapa de la obra", list(ETAPAS_OBRA.keys()), index=list(ETAPAS_OBRA.keys()).index(pre.get("etapa_label", list(ETAPAS_OBRA.keys())[0])) if pre.get("etapa_label") in ETAPAS_OBRA else 0, key="cdir_etapa")]
    with c3:
        dias = st.number_input("Dias en obra", min_value=1, value=int(pre.get("dias_obra", 2)), step=1, key="cdir_dias")
    with c4:
        personas = st.number_input("Num. de personas", min_value=1, value=int(pre.get("personas", 2)), step=1, key="cdir_personas")

    nombre_cliente = st.text_input("Nombre del cliente", value=pre.get("nombre_cliente", ""), placeholder="Ej: Juan Garcia / Constructora XYZ", key="cdir_nombre_cliente")

    st.markdown("**Zocalos**")
    zocalo_activo = st.checkbox("Este proyecto lleva zocalos", value=pre.get("zocalo_activo", False), key="cdir_zocalo_activo")
    zocalo_ml = 0.0
    if zocalo_activo:
        zocalo_ml = st.number_input("Metros lineales de zocalo (ml)", min_value=0.0, value=float(pre.get("zocalo_ml", 2.0)), step=0.5, key="cdir_zocalo_ml")

    # ── GESTIÓN DE DESPERDICIO — SECCIÓN INNOVADORA ────────────────────────
    # Reemplaza el campo críptico "m² adicionales cortados no aprovechados"
    # por una experiencia educativa, visual e interactiva.
    #
    # CONCEPTO: El usuario elige el perfil de su corte (simple/complejo),
    # la app calcula el desperdicio técnico sugerido Y muestra en tiempo real
    # cómo impacta en el costo. El botón de ayuda explica TODO con imágenes.

    desperdicio_sugerido_15 = round(m2_real * 0.15, 2)
    desperdicio_sugerido_20 = round(m2_real * 0.20, 2)
    desperdicio_sugerido_10 = round(m2_real * 0.10, 2)

    # Título de sección con badge explicativo
    st.markdown("""
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px">
      <span style="font-weight:700;font-size:1rem">Desperdicio de material en cortes</span>
      <span style="background:#1B5FA8;color:white;font-size:0.65rem;font-weight:700;
                   padding:3px 8px;border-radius:20px;letter-spacing:0.05em">RETAL</span>
    </div>
    <p style="font-size:0.82rem;opacity:0.65;margin:0 0 10px">
      Toda instalación genera retales — piezas que se cortan y no se usan.
      Este valor afecta directamente el costo del disco y el consumo de insumos.
    </p>
    """, unsafe_allow_html=True)

    # ── Widget educativo principal ───────────────────────────────────────────
    with st.container(border=True):

        # Selector visual de perfil de corte
        st.markdown("""
        <div style="font-size:0.78rem;font-weight:700;text-transform:uppercase;
                    letter-spacing:0.08em;opacity:0.6;margin-bottom:8px">
          1. ¿Qué tan complejo es el corte de este proyecto?
        </div>""", unsafe_allow_html=True)

        perfil_opciones = {
            "🟢 Simple — cortes rectos, sin curvas":        ("simple",   0.10),
            "🟡 Normal — algunos ángulos o esquinas":        ("normal",   0.15),
            "🔴 Complejo — curvas, biselados, figuras":      ("complejo", 0.22),
            "✏️ Personalizado — quiero ingresar el valor":   ("custom",   None),
        }
        perfil_key = f"perfil_desperdicio_{st.session_state.get('_piezas_hash', 0)}"
        perfil_sel = st.radio(
            "Perfil de corte",
            list(perfil_opciones.keys()),
            index=1,  # Normal por defecto
            horizontal=False,
            key="perfil_desperdicio_radio",
            label_visibility="collapsed"
        )

        perfil_id, pct_auto = perfil_opciones[perfil_sel]
        pct_auto = pct_auto or 0.15

        # Mostrar el valor resultante (o input si es custom)
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

        col_val, col_imp = st.columns([1.2, 1])

        with col_val:
            st.markdown("""
            <div style="font-size:0.78rem;font-weight:700;text-transform:uppercase;
                        letter-spacing:0.08em;opacity:0.6;margin-bottom:6px">
              2. Metros cuadrados de retal estimados
            </div>""", unsafe_allow_html=True)

            if perfil_id == "custom":
                extra_corte = st.number_input(
                    "m² de retal (ingresa tu valor)",
                    min_value=0.0,
                    max_value=float(area_placa) if area_placa > 0 else 50.0,
                    value=float(pre.get("extra_corte", round(m2_real * 0.15, 2))),
                    step=0.05,
                    format="%.2f",
                    label_visibility="collapsed",
                    help="Ingresa los metros cuadrados exactos que esperas perder en cortes.",
                    key="cdir_extra_corte"
                )
                pct_real = (extra_corte / m2_real * 100) if m2_real > 0 else 0
                st.caption(f"Equivale al **{pct_real:.1f}%** del proyecto")
            else:
                extra_corte = round(m2_real * pct_auto, 2)
                pct_real = pct_auto * 100
                # Mostrar el valor calculado en un badge visual, NO editable
                color_pct = "#16a34a" if pct_auto <= 0.12 else "#d97706" if pct_auto <= 0.17 else "#dc2626"
                st.markdown(f"""
                <div style="background:var(--secondary-background-color);
                            border:2px solid {color_pct};border-radius:8px;
                            padding:10px 14px;display:inline-flex;align-items:baseline;gap:8px">
                  <span style="font-size:1.8rem;font-weight:900;color:{color_pct}">{fmt_m2(extra_corte)}</span>
                  <span style="font-size:0.8rem;color:{color_pct};font-weight:700">({pct_real:.0f}%)</span>
                </div>
                """, unsafe_allow_html=True)
                st.caption(f"Calculado automáticamente como el {pct_real:.0f}% de {fmt_m2(m2_real)}")

        with col_imp:
            # Impacto en costos en tiempo real
            st.markdown("""
            <div style="font-size:0.78rem;font-weight:700;text-transform:uppercase;
                        letter-spacing:0.08em;opacity:0.6;margin-bottom:6px">
              Impacto en el costo del disco
            </div>""", unsafe_allow_html=True)

            _tar_actual = get_tarifas().get(cat_sel, TARIFAS.get(cat_sel, TARIFAS["Mármol"]))
            _costo_disco_retal = extra_corte * _tar_actual.get("disco", 2_200)
            _costo_disco_base  = m2_real     * _tar_actual.get("disco", 2_200)
            _total_disco       = _costo_disco_base + _costo_disco_retal

            st.markdown(f"""
            <div style="background:var(--secondary-background-color);border:1px solid var(--border-color);
                        border-radius:8px;padding:10px 14px;font-size:0.82rem">
              <div style="display:flex;justify-content:space-between;padding:3px 0;
                          border-bottom:1px solid var(--border-color)">
                <span style="opacity:0.7">Proyecto ({fmt_m2(m2_real)})</span>
                <span style="font-weight:600">{numero_completo(_costo_disco_base)}</span>
              </div>
              <div style="display:flex;justify-content:space-between;padding:3px 0;
                          border-bottom:1px solid var(--border-color)">
                <span style="opacity:0.7">Retal ({fmt_m2(extra_corte)})</span>
                <span style="font-weight:600;color:#d97706">+{numero_completo(_costo_disco_retal)}</span>
              </div>
              <div style="display:flex;justify-content:space-between;padding:4px 0 0">
                <span style="font-weight:700">Total disco</span>
                <span style="font-weight:800;color:#1B5FA8">{numero_completo(_total_disco)}</span>
              </div>
            </div>
            """, unsafe_allow_html=True)

        # ── Ayuda expandible — EL CORAZÓN DE LA INNOVACIÓN ──────────────────
        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
        with st.expander("❓ ¿Qué es el retal y por qué me afecta económicamente?", expanded=False):
            st.markdown("""
<div style="font-size:0.88rem;line-height:1.7">

### 🪨 Qué es el retal
Cuando cortas una placa de mármol para hacer un mesón, **nunca usas el 100% de la placa**.
Los recortes que quedan y no se pueden reutilizar se llaman **retal** (o desperdicio de corte).

---

### 📐 Ejemplo visual

Imagina que compraste una placa de **5,94 m²** para un mesón de **3 ml × 0,60 m = 1,80 m²**:

| | m² |
|---|---|
| Material comprado | 5,94 m² |
| Mesón instalado | 1,80 m² |
| **Retal sobrante** | **4,14 m²** |

Ese retal ya fue pagado, ya fue cortado con el disco, y ya consumió insumos.
Por eso **el costo del disco se aplica TAMBIÉN sobre el retal**, no solo sobre el proyecto.

---

### 🔴 Por qué es importante
El campo de "retal estimado" le dice a la app cuántos m² **adicionales** cortaste
**más allá de las piezas del proyecto** — por ejemplo, al ajustar un borde o corregir un empate.

| Perfil | % típico | Cuándo aplica |
|---|---|---|
| 🟢 Simple | ~10% | Mesones rectos, sin curvas ni empates |
| 🟡 Normal | ~15% | Instalación estándar con 2–3 esquinas |
| 🔴 Complejo | ~22% | Figuras curvas, biselados, escaleras con curvas |

---

### 💡 Consejo práctico
Si ya terminaste la instalación y sabes exactamente cuánto retal quedó,
usa **"✏️ Personalizado"** e ingresa el valor real. Eso da el costo más preciso.

Si estás cotizando ANTES de instalar, usa el perfil que mejor describe el proyecto.

</div>
            """, unsafe_allow_html=True)

    m2_cortados_total += extra_corte

    st.markdown("---")

    # ── PASO 4: LOGÍSTICA ────────────────────────────────────────────────────
    seccion_titulo("Paso 4 — Logistica")

    col_agt, col_veh = st.columns(2)
    with col_agt:
        agente_ext_taller = st.checkbox("Agente externo trajo el material al taller", value=bool(pre.get("agente_externo_taller", False)), key="cdir_agente_ext")
    with col_veh:
        _veh_dict = get_vehiculos_dict()
        _veh_keys = list(_veh_dict.keys())
        _v_idx = 0
        if pre.get("vehiculo_entrega") in list(_veh_dict.values()):
            _v_idx = list(_veh_dict.values()).index(pre.get("vehiculo_entrega"))
        veh_lbl = st.selectbox("Vehiculo de entrega", _veh_keys, index=_v_idx, key="cdir_vehiculo")
        vehiculo = _veh_dict[veh_lbl]

    c1, c2 = st.columns(2)
    with c1: km = st.number_input("Distancia (km, un trayecto)", min_value=0.0, value=float(pre.get("km", 5.0)), step=0.5, key="cdir_km")
    with c2: peajes = st.number_input("Num. de peajes (ida+vuelta)", min_value=0, value=int(pre.get("peajes", 0)), step=1, key="cdir_peajes")

    st.markdown("---")

    # ── PASO 5: FORÁNEO ──────────────────────────────────────────────────────
    seccion_titulo("Paso 5 — Proyecto fuera de Barranquilla?")
    foraneo_activo = st.checkbox("Si, proyecto en otra ciudad", value=pre.get("foraneo_activo", False), key="cdir_foraneo")
    viaticos_activos = False; tipo_aloj = "pueblo"; noches = 0
    if foraneo_activo:
        c1, c2, c3 = st.columns(3)
        with c1: viaticos_activos = st.checkbox("Agregar viaticos", value=pre.get("viaticos_activos", False), key="cdir_viaticos")
        with c2: tipo_aloj = ALOJAMIENTO[st.selectbox("Destino", list(ALOJAMIENTO.keys()), index=list(ALOJAMIENTO.keys()).index(next((k for k,v in ALOJAMIENTO.items() if v==pre.get("tipo_aloj","pueblo")), list(ALOJAMIENTO.keys())[0])), key="cdir_tipo_aloj")]
        with c3: noches = st.number_input("Noches", min_value=0, value=int(pre.get("noches", 1)), key="cdir_noches")

    st.markdown("---")

    # ── PASO 6: ADICIONALES ──────────────────────────────────────────────────
    seccion_titulo("Paso 6 — Costos adicionales")
    _ADICIONALES_ACT = get_adicionales()
    adicionales_activos = st.checkbox("Agregar costos adicionales (silicona, impermeabilizante)", value=pre.get("adicionales_activos", False), key="cdir_adicionales")
    cantidades_add = pre.get("cantidades_add", [0.0] * len(_ADICIONALES_ACT)) if pre.get("adicionales_activos") else [0.0] * len(_ADICIONALES_ACT)
    # Ajustar longitud si la lista cambió
    while len(cantidades_add) < len(_ADICIONALES_ACT):
        cantidades_add.append(0.0)
    if adicionales_activos:
        for i, a in enumerate(_ADICIONALES_ACT):
            c1, c2 = st.columns([3, 1])
            c1.markdown(f"<div style='font-size:0.85rem;'>{a['concepto']} — {numero_completo(a.get(etapa, 0))}/{a['unidad']}</div>", unsafe_allow_html=True)
            cantidades_add[i] = c2.number_input("Cant.", min_value=0.0, value=float(cantidades_add[i]), step=1.0, key=f"add_{i}", label_visibility="collapsed")

    st.markdown("---")

    # ── PASO 7: IVA ──────────────────────────────────────────────────────────
    seccion_titulo("Paso 7 — IVA en la cotización")

    _col_iva1, _col_iva2 = st.columns([1.4, 2])
    with _col_iva1:
        incluir_iva = st.toggle(
            "Incluir IVA 19% en la cotización",
            value=pre.get("incluir_iva", True),
            key="cdir_incluir_iva",
            help="Activa si tu empresa es responsable del régimen común (ventas > 3.500 UVT ≈ $166 M/año). Desactiva si eres régimen simplificado.",
        )
    with _col_iva2:
        if incluir_iva:
            st.info(
                "**IVA activo.** Se calculará el 19% sobre el **total de la cotización** (precio sugerido). "
                "El precio final y el PDF incluirán el IVA desglosado.",
                icon="🧾"
            )
        else:
            st.warning(
                "**IVA desactivado.** La cotización y el PDF se entregarán sin IVA. "
                "Aplica si eres **régimen simplificado** o si el cliente es no responsable de IVA. "
                "Confirma con tu contador.",
                icon="⚠️"
            )

    st.markdown("---")

    # ── AUTOSAVE: persistir estado del formulario en session_state.pre ─────────
    # Cada vez que Streamlit re-ejecuta este bloque (al navegar a otra sección
    # y volver, al cambiar un widget, etc.) guardamos el snapshot actual de todos
    # los campos en st.session_state.pre. Así, cuando el usuario regresa desde
    # Parámetros u otra sección, los widgets se inicializan con los valores que
    # el usuario había ingresado, no con los defaults vacíos.
    _etapa_labels = {v: k for k, v in ETAPAS_OBRA.items()}  # invertir dict
    st.session_state.pre = {
        # Material(es)
        "materiales_proyecto":  st.session_state.get("materiales_proyecto", []),
        # Paso 3 — Proyecto
        "tipos_proyecto":       st.session_state.get("cdir_tipos_proyecto", tipos_sel) if "cdir_tipos_proyecto" in st.session_state else tipos_sel,
        "tipo_proyecto":        tipo,
        "etapa_label":          _etapa_labels.get(etapa, list(ETAPAS_OBRA.keys())[0]),
        "dias_obra":            dias,
        "personas":             personas,
        "nombre_cliente":       nombre_cliente,
        # Zócalos
        "zocalo_activo":        zocalo_activo,
        "zocalo_ml":            zocalo_ml,
        # Desperdicio
        "perfil_desperdicio":   perfil_sel,
        "extra_corte":          extra_corte,
        # m² (modo avanzado)
        "m2_proyecto":          m2_real,
        "m2_cortados_input":    m2_cortados_total,
        "m2_usados":            m2_usados,
        "margen_pct":           margen_pct,
        # Logística
        "agente_externo_taller": agente_ext_taller,
        "vehiculo_entrega":     vehiculo,
        "km":                   km,
        "peajes":               peajes,
        # Foráneo
        "foraneo_activo":       foraneo_activo,
        "viaticos_activos":     viaticos_activos,
        "tipo_aloj":            tipo_aloj,
        "noches":               noches,
        # Adicionales
        "adicionales_activos":  adicionales_activos,
        "cantidades_add":       cantidades_add,
        # IVA
        "incluir_iva":          incluir_iva,
        # Piezas (ya en session_state pero duplicar en pre para reload desde historial)
        "piezas":               st.session_state.get("piezas", []),
    }

    # ── CALCULAR / ACTUALIZAR ─────────────────────────────────────────────────
    _editando_id  = st.session_state.get("editando_id")
    _editando_num = st.session_state.get("editando_num", "")

    if _editando_id:
        st.info(
            f"**Modo edición** — estás modificando la cotización **{_editando_num}**. "
            "Al presionar *Actualizar* se sobreescribirá el registro existente.",
            icon="✏️",
        )
        _col_upd, _col_new, _col_can = st.columns([2, 1.5, 1])
        _btn_actualizar = _col_upd.button("✏️ Actualizar cotización", type="primary", use_container_width=True)
        _btn_guardar_nuevo = _col_new.button("💾 Guardar como nueva", use_container_width=True)
        _btn_cancelar = _col_can.button("✕ Cancelar edición", use_container_width=True)

        if _btn_cancelar:
            st.session_state.pop("editando_id", None)
            st.session_state.pop("editando_num", None)
            st.session_state.pop("pre", None)
            st.session_state.pop("cotizacion", None)
            st.rerun()
    else:
        _btn_actualizar    = False
        _btn_guardar_nuevo = False
        _btn_cancelar      = False
        _col_calc, _ = st.columns([2, 1])
        _btn_calcular = _col_calc.button("Calcular cotizacion", type="primary", use_container_width=True)

    _ejecutar_calculo = _editando_id and (_btn_actualizar or _btn_guardar_nuevo) or (not _editando_id and _btn_calcular)

    if _ejecutar_calculo:
        _ml_tot = sum(p.get("ml", 0) for p in st.session_state.get("piezas", [])) if "Por piezas" in modo_medida else (m2_real/0.60)
        resultado = calcular_cotizacion_directa(
            categoria=cat_sel, referencia=referencia, precio_m2=precio_m2_efectivo, area_placa_comprada=area_placa,
            m2_real=m2_real, m2_cortados=m2_cortados_total, m2_usados=m2_usados, margen_pct=margen_pct,
            dias=dias, personas=personas, zocalo_activo=zocalo_activo, zocalo_ml=zocalo_ml,
            agente_externo_taller=agente_ext_taller, vehiculo_entrega=vehiculo, km=km, num_peajes=peajes,
            foraneo_activo=foraneo_activo, viaticos_activos=viaticos_activos, tipo_aloj=tipo_aloj, noches=noches,
            adicionales_activos=adicionales_activos, cantidades_add=cantidades_add, etapa=etapa,
            adicionales_lista=_ADICIONALES_ACT, tipo_proyecto=tipo, nombre_cliente=nombre_cliente,
            ml_proyecto=_ml_tot, logistica_override=st.session_state.get("logistica_custom"),
            vehiculos_custom={**VEHICULOS_CONFIG, **(st.session_state.get("vehiculos_custom") or {})},
            tarifas_override=st.session_state.get("tarifas_custom"),
        )

        # Guardar estado completo para re-edición
        resultado["_estado_guardado"] = {
            "categoria": cat_sel, "referencia": referencia, "precio_m2": precio_m2, "area_placa_comprada": area_placa,
            "piezas": st.session_state.piezas, "m2_proyecto": m2_real, "m2_usados": m2_usados, "margen_pct": margen_pct,
            "tipos_proyecto": tipos_sel, "tipo_proyecto": tipo, "dias_obra": dias, "personas": personas, "nombre_cliente": nombre_cliente,
            "zocalo_activo": zocalo_activo, "zocalo_ml": zocalo_ml, "agente_externo_taller": agente_ext_taller,
            "vehiculo_entrega": vehiculo, "km": km, "peajes": peajes, "foraneo_activo": foraneo_activo,
            "viaticos_activos": viaticos_activos, "noches": noches, "adicionales_activos": adicionales_activos,
            "cantidades_add": cantidades_add, "incluir_iva": incluir_iva,
        }

        st.session_state.cotizacion = resultado
        resultado["incluir_iva"] = incluir_iva

        # [PERSISTENCIA] Guardar borrador del formulario en BD
        # Permite restaurar el último cálculo tras un F5 o cierre accidental.
        try:
            _guardar_config("borrador_cotizacion_directa", resultado["_estado_guardado"])
        except Exception:
            pass

        import random as _rand
        _num_auto = f"COT-{_hoy().strftime('%Y%m%d')}-{_rand.randint(100,999)}"

        if _editando_id and _btn_actualizar:
            # MODO EDICIÓN: sobreescribir el registro existente
            _actualizar_cotizacion(_editando_id, _editando_num, nombre_cliente, resultado)
            st.session_state.pop("editando_id", None)
            st.session_state.pop("editando_num", None)
            st.session_state["_cotiz_guardada_num"] = _editando_num
            st.session_state["_cotiz_guardada"] = True
            st.success(f"✅ Cotización **{_editando_num}** actualizada correctamente.")
        elif _editando_id and _btn_guardar_nuevo:
            # Guardar como nueva desde modo edición
            _guardar_cotizacion(_num_auto, nombre_cliente, resultado)
            st.session_state.pop("editando_id", None)
            st.session_state.pop("editando_num", None)
            st.session_state["_cotiz_guardada_num"] = _num_auto
            st.session_state["_cotiz_guardada"] = True
            st.success("✅ Cotización guardada exitosamente en el Historial.")
        else:
            # NUEVA cotización — NO guardar automáticamente. El usuario decide al final.
            st.session_state["_cotiz_guardada"] = False
            st.session_state["_num_auto_sugerido"] = _num_auto

    if st.session_state.cotizacion and st.session_state.cotizacion.get("tipo_proyecto") != "Licitación AIU":
        r = st.session_state.cotizacion
        st.markdown("---")
        st.markdown("<h3 style='font-family:Playfair Display,serif'>Resultado</h3>", unsafe_allow_html=True)

        # ── IVA: condicional según elección del usuario ───────────────────────
        # IVA se calcula sobre el TOTAL de la cotización (precio_sugerido), no sobre utilidad
        _iva_activo   = r.get("incluir_iva", incluir_iva)
        _iva_monto    = r['precio_sugerido'] * 0.19 if _iva_activo else 0.0
        _precio_final = r['precio_sugerido'] + _iva_monto

        # ── Hero card ─────────────────────────────────────────────────────────
        if _iva_activo:
            _iva_line = (
                f'<div style="margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.25)">'
                f'<span style="color:#C9A84C;font-weight:700">+ IVA 19% sobre total: {numero_completo(_iva_monto)}</span>'
                f'&nbsp;&nbsp;→&nbsp;&nbsp;'
                f'<span style="font-size:1.15rem;font-weight:900">Total con IVA: {numero_completo(_precio_final)}</span>'
                f'</div>'
            )
        else:
            _iva_line = (
                f'<div style="margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.25)'
                f';font-size:0.8rem;opacity:0.7">Sin IVA — cotización entregada en régimen simplificado</div>'
            )

        st.markdown(f"""
        <div style="background:#1B5FA8; border-radius:14px;padding:32px 36px;margin:8px 0 20px; color:white;">
          <div style="color:#C9A84C;font-size:0.68rem;text-transform:uppercase;letter-spacing:0.14em;font-weight:700;margin-bottom:10px">
            Precio de venta sugerido {'(sin IVA)' if _iva_activo else '— Sin IVA'}
          </div>
          <div style="font-size:2.8rem;font-weight:900;font-family:'Playfair Display',serif;line-height:1;margin-bottom:8px">
            {numero_completo(r['precio_sugerido'])}
          </div>
          <div style="opacity:0.8;font-size:0.85rem">
            Margen: {r['margen_pct']:.0f}%   ·   Utilidad: {numero_completo(r['utilidad'])}
          </div>
          {_iva_line}
        </div>""", unsafe_allow_html=True)

        # ── Nota contextual ───────────────────────────────────────────────────
        if _iva_activo:
            alerta(
                "**¿Cuándo cobrar IVA?** El IVA (19%) aplica cuando tu empresa es **responsable del régimen común** "
                "(ventas anuales > 3.500 UVT ≈ $166 M en 2026). Se aplica sobre el total de la cotización. "
                "Consulta a tu contador para confirmar.",
                "info"
            )
        else:
            alerta(
                "**Cotización sin IVA.** Si en algún momento cambias de régimen o el cliente lo requiere, "
                "activa el IVA en el Paso 7 y recalcula.",
                "info"
            )

        # ── Desglose de costos ────────────────────────────────────────────────
        col_res, col_det = st.columns([1, 1])
        with col_res:
            _items_desglose = [
                ("Material",    r['c1_material']),
                ("Producción",  r['c2_mano_obra']),
                ("Zócalos",     r['c3_zocalos']),
                ("Insumos",     r['c4_insumos']),
                ("Logística",   r['c5_logistica']),
                ("Viáticos",    r['c6_viaticos']),
                ("Adicionales", r['c7_adicionales']),
            ]
            if _iva_activo:
                _items_desglose.append(("Subtotal antes de IVA", r['precio_sugerido']))
                _items_desglose.append((f"IVA 19% s/total cotización", _iva_monto))
                _total_label = "TOTAL CON IVA"
            else:
                _total_label = "PRECIO TOTAL (SIN IVA)"
            bloque_costos(_items_desglose, _total_label, _precio_final)

        with col_det:
            c1a, c2a = st.columns(2)
            c1a.metric("Aprovechamiento", f"{r['aprovechamiento']:.1f}%", f"Retal: {fmt_m2(r['retal'])}")
            c2a.metric("Costo/m² instalado", numero_completo(r['costo_total']/max(r['m2_real'],0.001)))
            st.markdown(f"<div style='font-weight:700;margin:14px 0 8px'>Simulador en tiempo real</div>", unsafe_allow_html=True)
            _sim_m = st.slider("Juega con tu Margen (%)", 5, 80, int(r["margen_pct"]), 1, key="sim_slider")
            _sim_p = r["costo_total"] / (1 - _sim_m / 100)
            _sim_ut = _sim_p - r["costo_total"]
            _sim_iva = _sim_p * 0.19 if _iva_activo else 0.0
            if _iva_activo:
                st.markdown(
                    f"""<div style="background:var(--secondary-background-color);border:1px solid var(--border-color);
                    border-radius:10px;padding:12px 16px;margin-top:4px">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
                      <span style="font-size:0.75rem;font-weight:700;opacity:0.55;text-transform:uppercase">Sin IVA</span>
                      <span style="font-size:1.05rem;font-weight:900;color:#1B5FA8">{numero_completo(_sim_p)}</span>
                    </div>
                    <div style="display:flex;justify-content:space-between;align-items:center;border-top:1px solid var(--border-color);padding-top:6px">
                      <span style="font-size:0.75rem;font-weight:700;opacity:0.55;text-transform:uppercase">Con IVA 19%</span>
                      <span style="font-size:1.05rem;font-weight:900;color:#C9A84C">{numero_completo(_sim_p + _sim_iva)}</span>
                    </div>
                    <div style="font-size:0.72rem;opacity:0.5;margin-top:6px">Utilidad: {numero_completo(_sim_ut)} · Margen: {_sim_m}%</div>
                    </div>""",
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    f"""<div style="background:var(--secondary-background-color);border:1px solid var(--border-color);
                    border-radius:10px;padding:12px 16px;margin-top:4px">
                    <div style="display:flex;justify-content:space-between;align-items:center">
                      <span style="font-size:0.75rem;font-weight:700;opacity:0.55;text-transform:uppercase">Precio total (sin IVA)</span>
                      <span style="font-size:1.1rem;font-weight:900;color:#1B5FA8">{numero_completo(_sim_p)}</span>
                    </div>
                    <div style="font-size:0.72rem;opacity:0.5;margin-top:6px">Utilidad: {numero_completo(_sim_ut)} · Margen: {_sim_m}%</div>
                    </div>""",
                    unsafe_allow_html=True
                )

        st.markdown("---")

        # ── Bloque de guardado en historial ───────────────────────────────────
        _ya_guardada = st.session_state.get("_cotiz_guardada", False)
        _num_sugerido = st.session_state.get("_num_auto_sugerido", f"COT-{_hoy().strftime('%Y%m%d')}-001")

        if _ya_guardada:
            _num_g = st.session_state.get("_cotiz_guardada_num", "")
            st.success(f"✅ Cotización **{_num_g}** guardada en el historial.", icon="💾")
        else:
            st.markdown(
                """<div style="background:var(--secondary-background-color);border:1px solid var(--border-color);
                border-radius:12px;padding:18px 22px;margin-bottom:4px">
                <div style="font-size:0.75rem;font-weight:700;opacity:0.5;text-transform:uppercase;margin-bottom:4px">💾 ¿Guardar en historial?</div>
                <div style="font-size:0.88rem;opacity:0.75;margin-bottom:12px">
                Si esta es una cotización real para un cliente, guárdala. Si es un borrador o prueba, puedes omitirlo.
                </div></div>""",
                unsafe_allow_html=True
            )
            _gc1, _gc2, _gc3 = st.columns([2, 1.5, 1])
            with _gc1:
                _num_guardar = st.text_input(
                    "Número de cotización",
                    value=_num_sugerido,
                    key="num_guardar_hist",
                    label_visibility="collapsed",
                    placeholder="Ej: COT-20260301-001"
                )
            with _gc2:
                if st.button("💾 Guardar en historial", type="primary", use_container_width=True, key="btn_guardar_hist"):
                    try:
                        _guardar_cotizacion(_num_guardar, r.get("nombre_cliente", "Sin nombre"), r)
                        # Descontar retales si aplica
                        for _mi, _md in enumerate(st.session_state.get("materiales_proyecto", [])):
                            if _md.get("es_retal") and _md.get("retal_id"):
                                try:
                                    _marcar_retal_usado(_md["retal_id"], _md.get("area_placa", 0))
                                    st.session_state.pop(f"usar_retal_{_mi}", None)
                                except Exception:
                                    pass
                        st.session_state["_cotiz_guardada"] = True
                        st.session_state["_cotiz_guardada_num"] = _num_guardar
                        st.rerun()
                    except Exception as _eg:
                        st.error(f"Error al guardar: {_eg}")
            with _gc3:
                if st.button("✕ Solo borrador", use_container_width=True, key="btn_no_guardar_hist"):
                    st.session_state["_cotiz_guardada"] = True   # marcar como "ya decidido"
                    st.session_state["_cotiz_guardada_num"] = ""
                    st.toast("Cotización calculada como borrador. No se guardó en historial.", icon="📋")
                    st.rerun()

        st.markdown("---")
        st.markdown("#### Exportar documentos comerciales")
        from generador_pdf import generar_pdf_cotizacion, generar_cuenta_cobro
        colp1, colp2 = st.columns(2)
        with colp1:
            num_cot = st.text_input("Número de Cotización", value=f"COT-{_hoy().strftime('%Y')}-001", key="num_cot")
            if st.button("📄 Generar Cotización PDF", type="primary", use_container_width=True):
                pdf_bytes = generar_pdf_cotizacion(
                    r, numero=num_cot,
                    empresa_info=st.session_state.empresa_info,
                    logo_bytes=st.session_state.logo_bytes,
                    incluir_iva=_iva_activo,
                )
                st.download_button("⬇ Descargar PDF", pdf_bytes, file_name=f"{num_cot}_Cotizacion.pdf", mime="application/pdf", use_container_width=True)
        with colp2:
            num_cc = st.text_input("Número de Cuenta", value=f"CC-{_hoy().strftime('%Y')}-001", key="num_cc")
            nom_pag = st.text_input("Facturar a:", value=r.get("nombre_cliente",""), key="nom_pag")
            nit_pag = st.text_input("NIT / CC", value="", key="nit_pag")
            dir_pag = st.text_input("Dirección", value="", key="dir_pag")
            if st.button("📄 Generar Cuenta de Cobro PDF", type="primary", use_container_width=True):
                datos_prest = st.session_state.empresa_info.copy()
                datos_pag = {"nombre": nom_pag, "nit": nit_pag, "direccion": dir_pag}
                cc_bytes = generar_cuenta_cobro(
                    r, datos_prest, datos_pag,
                    numero=num_cc,
                    logo_bytes=st.session_state.logo_bytes,
                    incluir_iva=_iva_activo,
                )
                st.download_button("⬇ Descargar PDF", cc_bytes, file_name=f"{num_cc}_CuentaCobro.pdf", mime="application/pdf", use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# COTIZACIÓN AIU
# ═══════════════════════════════════════════════════════════════════════════════
elif pagina == "Cotizacion AIU":
    st.markdown("<h2 style='font-family:Playfair Display,serif'>Cotizacion AIU</h2>", unsafe_allow_html=True)
    st.markdown("<p style='opacity:0.7;font-size:0.88rem'>Estructura formal colombiana A+I+U+IVA</p>", unsafe_allow_html=True)

    # [PERSISTENCIA] Restaurar borrador AIU desde BD si session_state está vacío (post-F5)
    if not st.session_state.pre and not st.session_state.get("_borrador_aiu_restaurado"):
        try:
            _borrador_aiu = _leer_config("borrador_cotizacion_aiu")
            if _borrador_aiu:
                st.session_state.pre = _borrador_aiu
                if _borrador_aiu.get("aiu_items"):
                    st.session_state.aiu_items = _borrador_aiu["aiu_items"]
                st.info("📋 Se restauró tu último cálculo AIU (antes de la recarga).")
        except Exception:
            pass
        st.session_state["_borrador_aiu_restaurado"] = True

    nombre_cliente_aiu = st.text_input("Nombre de la Constructora o Proyecto", placeholder="Ej: Constructora ABC", value=st.session_state.pre.get("nombre_cliente", ""), key="aiu_nombre_cliente")

    seccion_titulo("Items del contrato")
    hdr = st.columns([4, 1, 1, 2, 0.5])
    for col, lbl in zip(hdr, ["Descripcion", "Unidad", "Cantidad", "Precio unitario (COP)", ""]):
        col.markdown(f"<div style='font-size:0.72rem;font-weight:700;opacity:0.6;text-transform:uppercase'>{lbl}</div>", unsafe_allow_html=True)

    nuevos_items = []
    cd_total = 0.0
    for idx, it in enumerate(st.session_state.aiu_items):
        c0, c1, c2, c3, c4 = st.columns([4, 1, 1, 2, 0.5])
        desc   = c0.text_input("Desc", value=it["desc"], key=f"aiu_d_{idx}", label_visibility="collapsed")
        und    = c1.text_input("Und",  value=it["und"],  key=f"aiu_u_{idx}", label_visibility="collapsed")
        cant   = c2.number_input("Cant", value=float(it["cant"]), min_value=0.0, step=1.0, key=f"aiu_c_{idx}", label_visibility="collapsed")
        punit  = c3.number_input("PU", value=float(it["punit"]), min_value=0.0, step=5_000.0, key=f"aiu_p_{idx}", label_visibility="collapsed")
        sub    = cant * punit
        cd_total += sub
        c0.caption(f"Subtotal: {numero_completo(sub)}")
        if c4.button("X", key=f"aiu_del_{idx}") and len(st.session_state.aiu_items) > 1:
            st.session_state.aiu_items.pop(idx)
            st.rerun()
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

    # ── AUTOSAVE AIU: persistir estado en session_state.pre ────────────────────
    st.session_state.pre = {
        **st.session_state.pre,   # conservar lo que ya había (ej: piezas de Directa)
        "nombre_cliente":          nombre_cliente_aiu,
        "pct_a":                   pct_a,
        "pct_i":                   pct_i,
        "pct_u":                   pct_u,
        "vehiculo_entrega":        vehiculo_aiu,
        "km":                      km_aiu,
        "peajes":                  peajes_aiu,
        "agente_externo_taller":   agente_aiu,
        "foraneo_activo":          foraneo_aiu,
        "tipo_aloj":               tipo_aloj_aiu,
        "noches":                  noches_aiu,
        "personas":                pers_aiu,
        "aiu_items":               st.session_state.get("aiu_items", []),
        "tipo_proyecto":           "Licitación AIU",
    }

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
        _btn_aiu_calcular   = st.button("Calcular y Guardar AIU", type="primary", use_container_width=True)

    _ejecutar_aiu = (
        (_editando_id_aiu and (_btn_aiu_actualizar or _btn_aiu_nueva))
        or (not _editando_id_aiu and _btn_aiu_calcular)
    )

    if _ejecutar_aiu:
        res_aiu = calcular_aiu(cd_total, pct_a, pct_i, pct_u, vehiculo_aiu, km_aiu, peajes_aiu, agente_aiu, foraneo_aiu, tipo_aloj_aiu, noches_aiu, pers_aiu)

        # Preparación exacta para la base de datos
        res_aiu["tipo_proyecto"] = "Licitación AIU"
        res_aiu["categoria"] = "Proyecto Constructora"
        res_aiu["referencia"] = "Múltiple"
        res_aiu["m2_real"] = 0
        res_aiu["ml_proyecto"] = 0
        res_aiu["costo_total"] = cd_total
        res_aiu["precio_sugerido"] = res_aiu['precio_total']

        res_aiu["_estado_guardado"] = {
            "nombre_cliente": nombre_cliente_aiu, "aiu_items": st.session_state.aiu_items,
            "pct_a": pct_a, "pct_i": pct_i, "pct_u": pct_u, "tipo_proyecto": "Licitación AIU",
            "vehiculo_entrega": vehiculo_aiu, "km": km_aiu, "peajes": peajes_aiu, "agente_externo_taller": agente_aiu,
            "foraneo_activo": foraneo_aiu, "tipo_aloj": tipo_aloj_aiu, "noches": noches_aiu, "personas": pers_aiu
        }

        st.session_state.cotizacion = res_aiu

        # [PERSISTENCIA] Guardar borrador AIU en BD
        try:
            _guardar_config("borrador_cotizacion_aiu", res_aiu["_estado_guardado"])
        except Exception:
            pass

        import random as _r
        _num_auto = f"AIU-{_hoy().strftime('%Y%m%d')}-{_r.randint(100,999)}"

        if _editando_id_aiu and _btn_aiu_actualizar:
            _actualizar_cotizacion(_editando_id_aiu, _editando_num_aiu, nombre_cliente_aiu or "Sin nombre", res_aiu)
            st.session_state.pop("editando_id", None)
            st.session_state.pop("editando_num", None)
            st.success(f"✅ Cotización AIU **{_editando_num_aiu}** actualizada correctamente.")
        else:
            _guardar_cotizacion(_num_auto, nombre_cliente_aiu or "Sin nombre", res_aiu)
            if _editando_id_aiu and _btn_aiu_nueva:
                st.session_state.pop("editando_id", None)
                st.session_state.pop("editando_num", None)
            st.success("✅ Cotización AIU guardada en el historial.")

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
            bloque_costos([
                ("Costo Directo Base (CD)", r['cd']),
                (f"A — Administración ({r.get('pct_a', pct_a)}%)", r['val_a']),
                (f"I — Imprevistos ({r.get('pct_i', pct_i)}%)", r['val_i']),
                (f"U — Utilidad ({r.get('pct_u', pct_u)}%)", r['val_u']),
                ("IVA 19% exclusivo sobre Utilidad", r['val_iva']),
                ("Gastos Logísticos Integrados", r['logistica']),
            ], "PRECIO TOTAL", r['precio_total'])

        st.markdown("---")
        st.markdown("#### Exportar Documentos Institucionales")
        from generador_pdf import generar_pdf_cotizacion, generar_cuenta_cobro
        cp1, cp2 = st.columns(2)
        with cp1:
            num_cot_a = st.text_input("Número de Oferta", value=f"OFE-AIU-{_hoy().strftime('%Y')}-001")
            if st.button("📄 Generar Oferta AIU (PDF)", type="primary", use_container_width=True):
                pdf_bytes = generar_pdf_cotizacion(r, numero=num_cot_a, empresa_info=st.session_state.empresa_info, logo_bytes=st.session_state.logo_bytes)
                st.download_button("⬇ Descargar Oferta", pdf_bytes, file_name=f"{num_cot_a}.pdf", mime="application/pdf", use_container_width=True)
        with cp2:
            num_cc_a = st.text_input("Número de Cuenta / Factura", value=f"FAC-AIU-{_hoy().strftime('%Y')}-001")
            nom_pag_a = st.text_input("Facturar a:", value=nombre_cliente_aiu)
            nit_pag_a = st.text_input("NIT / Rut", value="")
            if st.button("📄 Generar Cobro AIU (PDF)", type="primary", use_container_width=True):
                datos_prest = st.session_state.empresa_info.copy()
                datos_pag = {"nombre": nom_pag_a, "nit": nit_pag_a, "direccion": ""}
                cc_bytes = generar_cuenta_cobro(r, datos_prest, datos_pag, numero=num_cc_a, logo_bytes=st.session_state.logo_bytes)
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
    _s = _stats_db()
    if _s["total"] > 0:
        _tasa = round(_s["aprobadas"] / _s["total"] * 100) if _s["total"] else 0
        _mc1, _mc2, _mc3, _mc4 = st.columns(4)
        _mc1.metric("Total",      _s["total"])
        _mc2.metric("Aprobadas",  _s["aprobadas"],  f"{_tasa}% cierre")
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

    _s = _stats_db()

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
    _tasa_cierre   = round(_s["aprobadas"] / _s["total"] * 100, 1) if _s["total"] else 0
    _rechazadas    = _s["total"] - _s["aprobadas"] - _s["pendientes"]
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
        help="De cada 100 cotizaciones que hacemos, cuántas realmente nos compran. "
             "Si es muy baja (menos del 40%), nuestros precios podrían estar altos "
             "o la presentación necesita mejorar. Una tasa saludable en marmolería "
             "está entre el 50% y el 70%.",
    )
    _k3.metric(
        "Facturación real",
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
        _sr = _stats_retales()
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
            f"{round(max(0, _rechazadas) / _s['total'] * 100, 1)}%" if _s["total"] else "—",
            help="Porcentaje de cotizaciones rechazadas sobre el total. "
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
                        _init_db()
                        _conn = _get_db_connection()
                        _cur = _conn.cursor()
                        _cur.execute(
                            """INSERT INTO inventario_retales
                               (material_categoria, referencia, m2_disponibles, m2_original,
                                fecha_ingreso, estado, notas)
                               VALUES (%s, %s, %s, %s, %s, 'Disponible', %s)""",
                            (_ncat, _nref, _nm2, _nm2, _hoy().isoformat(), _nnota)
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
                            'Por m² · Pon $0 si lo reutilizas sin cobrar el material</div>',
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
                                "Este es el precio por m² que le vas a cobrar al cliente cuando uses este sobrante.\n\n"
                                "Ejemplo: si tienes 2 m² guardados y pones $80.000/m², "
                                "en la próxima cotización ese material costará $80.000/m² (en vez del precio de mercado completo).\n\n"
                                "Déjalo en $0 si no quieres cobrar nada por el material — eso maximiza tu margen al máximo."
                            ),
                        )
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
                            _hint_icon = "🟢"
                            _hint_txt  = "Material gratis para la próxima cotización — tu margen de ganancia sube al máximo."
                            _hint_color = "#15803d"
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
                    help="Lo que cobra el operario por cada metro lineal cortado e instalado.")
                tar_edit[_mat]["zocalo"] = _cb.number_input(
                    "Zócalo / ml (COP)", min_value=0,
                    value=int(_t.get("zocalo", 12_000)), step=500, format="%d",
                    key=f"tar_zoc_{_mat}",
                    help="Tarifa por metro lineal de zócalo instalado.")
                tar_edit[_mat]["disco"] = _cc.number_input(
                    "Disco diamantado / m² (COP)", min_value=0,
                    value=int(_t.get("disco", 2_200)), step=100, format="%d",
                    key=f"tar_dis_{_mat}",
                    help="Desgaste del disco diamantado por m² cortado.")
                tar_edit[_mat]["maquina"] = _cd.number_input(
                    "Máquina cortadora / día (COP)", min_value=0,
                    value=int(_t.get("maquina", 20_000)), step=1_000, format="%d",
                    key=f"tar_maq_{_mat}",
                    help="Depreciación y mantenimiento de la cortadora por día de uso.")
                tar_edit[_mat]["consumibles"] = _ce.number_input(
                    "Consumibles / m² (COP)", min_value=0,
                    value=int(_t.get("consumibles", 10_000)), step=500, format="%d",
                    key=f"tar_con_{_mat}",
                    help="Masilla de poliéster, lijas diamantadas (50–3000), ceras, sellador y estopa.")
                tar_edit[_mat]["riesgo_rotura"] = _cf.number_input(
                    "Riesgo de rotura (%)", min_value=0.0, max_value=0.50,
                    value=float(_t.get("riesgo_rotura", 0.02)), step=0.01, format="%.2f",
                    key=f"tar_rie_{_mat}",
                    help="Porcentaje del costo del material reservado como provisión por rotura accidental.")

        st.markdown("")
        _col_save_tar, _col_reset_tar = st.columns([3, 1])
        if _col_save_tar.button("💾 Guardar Tarifas", type="primary", key="btn_save_tar", use_container_width=True):
            _saved_tar = {}
            for _sm in ["Mármol", "Granito", "Sinterizado", "Quarztone", "Quarzita"]:
                _saved_tar[_sm] = {
                    "prod_ml":       int(st.session_state.get(f"tar_pml_{_sm}", 60_000)),
                    "zocalo":        int(st.session_state.get(f"tar_zoc_{_sm}", 12_000)),
                    "disco":         int(st.session_state.get(f"tar_dis_{_sm}", 2_200)),
                    "maquina":       int(st.session_state.get(f"tar_maq_{_sm}", 20_000)),
                    "consumibles":   int(st.session_state.get(f"tar_con_{_sm}", 10_000)),
                    "riesgo_rotura": float(st.session_state.get(f"tar_rie_{_sm}", 0.02)),
                }
            st.session_state.tarifas_custom = _saved_tar
            # [PERSISTENCIA] Guardar en Supabase para sobrevivir a F5 y reinicios
            try:
                _guardar_config("tarifas_custom", _saved_tar)
            except Exception:
                pass
            # Limpiar keys de widgets para que se reinicialicen con los valores recién guardados
            for _sm in ["Mármol", "Granito", "Sinterizado", "Quarztone", "Quarzita"]:
                for _sfx in ["pml", "zoc", "dis", "maq", "con", "rie"]:
                    st.session_state.pop(f"tar_{_sfx}_{_sm}", None)
            st.toast("✅ Tarifas guardadas y persistidas correctamente", icon="💾")
            st.rerun()
        if _col_reset_tar.button("↺ Restaurar", key="btn_reset_tar", use_container_width=True,
                                  help="Vuelve a los valores por defecto de fábrica"):
            st.session_state.tarifas_custom = None
            try:
                _guardar_config("tarifas_custom", None)
            except Exception:
                pass
            # Limpiar keys de widgets para forzar recarga con valores por defecto
            for _sm in ["Mármol", "Granito", "Sinterizado", "Quarztone", "Quarzita"]:
                for _sfx in ["pml", "zoc", "dis", "maq", "con", "rie"]:
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
            st.session_state.viaticos_custom = {
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
            # [PERSISTENCIA] Guardar en Supabase
            try:
                _guardar_config("viaticos_custom", st.session_state.viaticos_custom)
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
            st.session_state.logistica_custom = {
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
            # [PERSISTENCIA] Guardar en Supabase
            try:
                _guardar_config("logistica_custom", st.session_state.logistica_custom)
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

        add_act = get_adicionales()

        # Inicializar editor en session_state si no existe O si custom cambió externamente
        if "add_editor" not in st.session_state or (st.session_state.adicionales_custom and st.session_state.add_editor is ADICIONALES):
            st.session_state.add_editor = add_act

        add_rows = st.session_state.add_editor
        UNIDADES = ["und", "ml", "m²", "viaje", "glb", "día", "kg"]
        ETAPAS_LIST = ["terminada", "acabados", "estructura", "comercial"]
        ETAPAS_LABELS = {
            "terminada": "Casa terminada",
            "acabados":  "En acabados",
            "estructura": "En estructura",
            "comercial": "Proyecto comercial",
        }

        # ── Encabezados de la tabla ───────────────────────────────────────────
        _hcols = st.columns([3, 1, 1, 1, 1, 1, 0.5])
        for _hc, _hl in zip(_hcols, ["Concepto / Descripción", "Unidad", "Casa terminada", "En acabados", "En estructura", "Proyecto comercial", ""]):
            _hc.markdown(f"<div style='font-size:0.71rem;font-weight:700;opacity:0.55;text-transform:uppercase'>{_hl}</div>", unsafe_allow_html=True)

        add_rows_nuevas = []
        for _ai, _ar in enumerate(add_rows):
            _ac0, _ac1, _ac2, _ac3, _ac4, _ac5, _ac6 = st.columns([3, 1, 1, 1, 1, 1, 0.5])

            with _ac0:
                _concepto = st.text_input(
                    "Concepto", value=_ar.get("concepto", ""),
                    key=f"add_con_{_ai}", label_visibility="collapsed",
                    placeholder="Ej: Sellante y silicona")

            with _ac1:
                _und_idx = UNIDADES.index(_ar.get("unidad", "und")) if _ar.get("unidad") in UNIDADES else 0
                _unidad = st.selectbox(
                    "Und", UNIDADES, index=_und_idx,
                    key=f"add_und_{_ai}", label_visibility="collapsed")

            with _ac2:
                _v_ter = int(_ar.get("terminada", 0))
                _terminada = st.number_input(
                    "Terminada", min_value=0, value=_v_ter, step=1_000, format="%d",
                    key=f"add_ter_{_ai}", label_visibility="collapsed")
                st.caption(numero_completo(st.session_state.get(f"add_ter_{_ai}", _v_ter)))

            with _ac3:
                _v_aca = int(_ar.get("acabados", 0))
                _acabados = st.number_input(
                    "Acabados", min_value=0, value=_v_aca, step=1_000, format="%d",
                    key=f"add_aca_{_ai}", label_visibility="collapsed")
                st.caption(numero_completo(st.session_state.get(f"add_aca_{_ai}", _v_aca)))

            with _ac4:
                _v_est = int(_ar.get("estructura", 0))
                _estructura = st.number_input(
                    "Estructura", min_value=0, value=_v_est, step=1_000, format="%d",
                    key=f"add_est_{_ai}", label_visibility="collapsed")
                st.caption(numero_completo(st.session_state.get(f"add_est_{_ai}", _v_est)))

            with _ac5:
                _v_com = int(_ar.get("comercial", 0))
                _comercial = st.number_input(
                    "Comercial", min_value=0, value=_v_com, step=1_000, format="%d",
                    key=f"add_com_{_ai}", label_visibility="collapsed")
                st.caption(numero_completo(st.session_state.get(f"add_com_{_ai}", _v_com)))

            with _ac6:
                st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
                if st.button("✕", key=f"add_del_{_ai}", help="Eliminar este ítem") and len(add_rows) > 1:
                    st.session_state.add_editor.pop(_ai)
                    # Limpiar keys del ítem eliminado
                    for _sfx in ["con", "und", "ter", "aca", "est", "com"]:
                        st.session_state.pop(f"add_{_sfx}_{_ai}", None)
                    st.rerun()

            add_rows_nuevas.append({
                "concepto": _concepto,
                "unidad": _unidad,
                "terminada": _terminada,
                "acabados": _acabados,
                "estructura": _estructura,
                "comercial": _comercial,
            })

        st.session_state.add_editor = add_rows_nuevas

        st.markdown("")
        _col_add_new, _ = st.columns([1, 3])
        with _col_add_new:
            if st.button("＋ Agregar ítem", use_container_width=True):
                st.session_state.add_editor.append({
                    "concepto": "Nuevo costo adicional",
                    "unidad": "und",
                    "terminada": 0,
                    "acabados": 0,
                    "estructura": 0,
                    "comercial": 0,
                })
                st.rerun()

        st.markdown("")
        _col_save_add, _col_reset_add = st.columns([3, 1])
        if _col_save_add.button("💾 Guardar Adicionales", type="primary", key="btn_save_add", use_container_width=True):
            # Leer valores actuales de los widgets
            _saved_add = []
            for _ai in range(len(st.session_state.add_editor)):
                _saved_add.append({
                    "concepto":   st.session_state.get(f"add_con_{_ai}", st.session_state.add_editor[_ai].get("concepto", "")),
                    "unidad":     st.session_state.get(f"add_und_{_ai}", st.session_state.add_editor[_ai].get("unidad", "und")),
                    "terminada":  int(st.session_state.get(f"add_ter_{_ai}", 0)),
                    "acabados":   int(st.session_state.get(f"add_aca_{_ai}", 0)),
                    "estructura": int(st.session_state.get(f"add_est_{_ai}", 0)),
                    "comercial":  int(st.session_state.get(f"add_com_{_ai}", 0)),
                })
            st.session_state.adicionales_custom = _saved_add
            st.session_state.add_editor = _saved_add
            # [PERSISTENCIA] Guardar en Supabase
            try:
                _guardar_config("adicionales_custom", _saved_add)
            except Exception:
                pass
            # Limpiar keys para que se reinicialicen con los nuevos valores
            for _ai in range(len(_saved_add)):
                for _sfx in ["con", "und", "ter", "aca", "est", "com"]:
                    st.session_state.pop(f"add_{_sfx}_{_ai}", None)
            st.toast("✅ Costos adicionales guardados y persistidos", icon="💾")
            st.rerun()

        if _col_reset_add.button("↺ Restaurar", key="btn_reset_add", use_container_width=True,
                                  help="Vuelve a la lista original de fábrica"):
            import copy
            st.session_state.adicionales_custom = None
            st.session_state.add_editor = copy.deepcopy(ADICIONALES)
            try:
                _guardar_config("adicionales_custom", None)
            except Exception:
                pass
            for _ai in range(20):  # limpiar hasta 20 posibles keys
                for _sfx in ["con", "und", "ter", "aca", "est", "com"]:
                    st.session_state.pop(f"add_{_sfx}_{_ai}", None)
            st.toast("↺ Adicionales restaurados a valores por defecto", icon="🔄")
            st.rerun()

elif pagina == "Asistente IA":

    # ── Estado del chat ───────────────────────────────────────────────────────
    if "chat" not in st.session_state:
        st.session_state.chat = []
    if "chat_input_key" not in st.session_state:
        st.session_state.chat_input_key = 0

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
            st.session_state.logo_bytes = logo.read()
            st.success("✅ Logo cargado. Ya aparece en el sidebar y en los PDFs.")
            st.rerun()

    # ── Tab de gestión de usuarios (solo Admin) ───────────────────────────────
    if tab_usuarios is not None:
        with tab_usuarios:
            st.markdown("#### 👥 Gestión de Usuarios del Sistema")
            st.caption("Solo los Administradores pueden crear, ver y eliminar usuarios.")

            with st.expander("➕ Crear nuevo usuario", expanded=False):
                _nu_nombre  = st.text_input("Nombre completo", key="nu_nombre")
                _nu_user    = st.text_input("Usuario (sin espacios, minúsculas)", key="nu_user",
                                            placeholder="Ej: jcastro")
                _nu_pwd     = st.text_input("Contraseña inicial", type="password", key="nu_pwd")
                _nu_pin     = st.text_input("PIN de recuperación (4 dígitos)", key="nu_pin",
                                            max_chars=4, placeholder="1234")
                _nu_rol     = st.selectbox("Rol", ["Operario", "Admin"], key="nu_rol")
                if st.button("✅ Crear usuario", type="primary", key="btn_crear_usr"):
                    if not _nu_user or not _nu_pwd or not _nu_pin:
                        st.error("Completa todos los campos obligatorios.")
                    elif len(_nu_pin) != 4 or not _nu_pin.isdigit():
                        st.error("El PIN debe tener exactamente 4 dígitos numéricos.")
                    elif len(_nu_pwd) < 6:
                        st.error("La contraseña debe tener al menos 6 caracteres.")
                    else:
                        _ok_usr = _crear_usuario(
                            _nu_user.strip().lower(), _nu_pwd, _nu_pin,
                            _nu_rol, _nu_nombre
                        )
                        if _ok_usr:
                            st.success(f"✅ Usuario **{_nu_user}** creado correctamente.")
                            st.rerun()
                        else:
                            st.error("Error al crear el usuario. ¿El nombre de usuario ya existe?")

            st.markdown("---")
            st.markdown("**Usuarios registrados:**")
            _todos_usr = _listar_usuarios()
            _uid_propio = st.session_state.get("usuario_actual", {}).get("id")
            for _u in _todos_usr:
                _u_id, _u_name, _u_rol, _u_nom = _u
                _col_a, _col_b, _col_c = st.columns([3, 1.5, 1])
                _col_a.markdown(
                    f"**{_u_nom or _u_name}** · `{_u_name}`"
                    f"<span style='background:{'#1B5FA8' if _u_rol=='Admin' else '#6b7280'};"
                    f"color:white;font-size:0.62rem;font-weight:700;padding:2px 7px;"
                    f"border-radius:4px;margin-left:8px;text-transform:uppercase'>{_u_rol}</span>",
                    unsafe_allow_html=True
                )
                with _col_c:
                    if _u_id != _uid_propio:
                        if st.button("🗑", key=f"del_usr_{_u_id}",
                                     help="Eliminar este usuario"):
                            _eliminar_usuario(_u_id)
                            st.toast(f"Usuario {_u_name} eliminado.")
                            st.rerun()
                    else:
                        st.markdown("<span style='font-size:0.72rem;opacity:0.4'>(tú)</span>",
                                    unsafe_allow_html=True)
