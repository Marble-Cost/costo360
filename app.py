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