# asistente_ia.py — Sistema de Cotización v2
# MARMOLES COLLANTE & CASTRO LTDA.

import json
import re
import anthropic
import streamlit as st
from parametros import TARIFAS, LOGISTICA, VIATICOS, AIU_DEFAULTS, CATEGORIAS_MATERIAL


# ── Serializador de tarifas para RAG dinámico ─────────────────────────────────
# Convierte la estructura de tarifas (lista de recetas v4 o dict plano legacy)
# a texto legible para el LLM, sin importar el formato en que estén guardadas.
def _tarifas_a_texto(tarifas: dict) -> str:
    """Convierte tarifas (receta o dict plano) a texto descriptivo para el system prompt."""
    if not tarifas:
        return "Tarifas no especificadas"
    lineas = []
    for mat, entry in tarifas.items():
        if isinstance(entry, list):   # formato receta v4
            partes = []
            for r in entry:
                val = r.get("valor", 0)
                ind = r.get("inductor", "")
                nom = r.get("nombre_interno", "")
                unidad = {
                    "por_ml":              "/ml",
                    "por_m2":              "/m²",
                    "por_dia":             "/día",
                    "por_ml_zocalo":       "/ml zócalo",
                    "porcentaje_material": "% del material",
                }.get(ind, "")
                if ind == "porcentaje_material":
                    partes.append(f"{nom}: {val*100:.1f}{unidad}")
                else:
                    partes.append(f"{nom}: ${int(val):,}{unidad}".replace(",", "."))
            lineas.append(f"- {mat}: " + " | ".join(partes))
        elif isinstance(entry, dict):  # formato plano legacy
            lineas.append(
                f"- {mat}: MO/ml ${int(entry.get('prod_ml',0)):,}"
                f" | zócalo ${int(entry.get('zocalo',0)):,}/ml"
                f" | disco ${int(entry.get('disco',0)):,}/m²"
                f" | máquina ${int(entry.get('maquina',0)):,}/día"
                f" | consumibles ${int(entry.get('consumibles',0)):,}/m²"
                f" | riesgo {entry.get('riesgo_rotura',0)*100:.1f}% material".replace(",", ".")
            )
    return "\n".join(lineas) if lineas else "Tarifas no especificadas"


# ── System prompt principal ────────────────────────────────────────────────────
SYSTEM_PROMPT = """Eres el asistente experto en costos y cotización de MARMOLES COLLANTE & CASTRO LTDA., 
Barranquilla, Colombia. Ayudas a marmoleros a calcular el costo real de sus proyectos.

DATOS DEL MERCADO (Feb 2026, Barranquilla):
- Gasolina: $15.800/galón
- Frontier NP300: 7.2 km/gal ciudad, desgaste $148/km, flete base $65.000
- Cheyenne V8: 4.1 km/gal ciudad, desgaste $340/km, flete base $85.000
- Externo/Tercero: flete fijo $165.000 | Peaje: $19.500 | Flete agente: $85.000
- Viáticos pueblo: $145.000/noche/persona | Ciudad: $178.000/noche/persona

[Las tarifas de mano de obra se inyectan dinámicamente por petición — ver TARIFAS DE TRABAJO ACTUALES DEL TALLER al final del prompt]

ESTRUCTURA AIU (norma colombiana):
- A = 2%, I = 2%, U = 5-8% (todos sobre Costo Directo)
- IVA 19% SOLO sobre Utilidad (U), no sobre el total
- Para obra pública: AIU combinado 10-15%

MÁRGENES: Saludable 30-45% sobre precio venta | Mínimo 20% | Riesgo: <20%

REGLAS DE COMUNICACIÓN:
- Español colombiano claro, sin tecnicismos innecesarios
- Formato de moneda: $1.000.000 (puntos para miles)
- Cuando el usuario describe un proyecto, extrae los datos y guíalo a la calculadora
- Si el usuario no sabe un valor, sugiere el más común para Barranquilla
- Sé directo: si está subcotizando, dilo claramente
- Respuestas máximo 4 párrafos — conciso y útil
"""

# ── Prompt especial para interpretación de proyectos en lenguaje natural ───────
SYSTEM_INTERPRET = """Eres un extractor de datos para una calculadora de costos de mármoles.
El usuario describe un proyecto en lenguaje natural. Extrae los datos y devuelve un JSON.

REGLAS ESTRICTAS:
1. Devuelve SOLO el JSON, sin texto antes ni después
2. Si el usuario menciona dimensiones como "4mt de largo por 90cm de ancho", calcula m² = 4 * 0.9 = 3.6
3. Si menciona "media placa" con área dada, usa esa área
4. Si el usuario dice "el proveedor trajo el material" o "agente externo", agente_externo = true
5. Para vehículo, si dice "Frontier" → "frontier", "Cheyenne" → "cheyenne", cualquier otro → "externo"
6. Si un dato no se menciona, usa null
7. precio_m2 es el valor por m² que el proveedor le cobró al usuario
8. area_placa_comprada es el área total de material que compró (ej: "media placa de 2.5 m²" → 2.5)

JSON a retornar:
{
  "categoria": "Mármol|Granito|Sinterizado|Quarztone|Quarzita|null",
  "referencia": "nombre del material o null",
  "precio_m2": numero_o_null,
  "area_placa_comprada": numero_o_null,
  "m2_usados": numero_o_null,
  "m2_proyecto": numero_o_null,
  "tipo_proyecto": "Mesón|Cocina|Baño|Piso|Escalera|Fachada|Otro|null",
  "agente_externo_taller": true_o_false,
  "vehiculo_entrega": "frontier|cheyenne|externo|null",
  "km": numero_o_null,
  "peajes": numero_o_null,
  "foraneo": false,
  "noches": 0,
  "dias_obra": numero_o_null,
  "personas": numero_o_null,
  "datos_faltantes": ["lista de campos que el usuario no mencionó y son necesarios"]
}
"""


def get_client():
    try:
        api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return None
        return anthropic.Anthropic(api_key=api_key)
    except Exception:
        return None


def ia_disponible() -> bool:
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY", "")
        return bool(key and key.startswith("sk-ant-"))
    except Exception:
        return False


def chat_con_ia(historial: list, mensaje_usuario: str,
                contexto_tarifas: dict = None) -> str:
    """Respuesta conversacional del asistente.

    Args:
        historial:         lista de mensajes previos {role, content}
        mensaje_usuario:   texto del turno actual
        contexto_tarifas:  dict de tarifas activas del taller
                           (st.session_state.tarifas_custom o TARIFAS base).
                           Se inyecta al final del system prompt para que
                           la IA use los precios reales del taller, no los
                           valores hardcoded del prompt original.
    """
    client = get_client()
    if client is None:
        return (
            "⚠️ **IA no configurada.** Para activarla, crea el archivo `.streamlit/secrets.toml` "
            "con tu API key de Anthropic (instrucciones en la barra lateral)."
        )
    try:
        # RAG dinámico: inyectar tarifas reales del taller al system prompt
        _tarifas_txt = _tarifas_a_texto(contexto_tarifas or TARIFAS)
        _prompt_final = SYSTEM_PROMPT + (
            f"\n\nTARIFAS DE TRABAJO ACTUALES DEL TALLER:\n{_tarifas_txt}"
        )
        messages = [{"role": m["role"], "content": m["content"]} for m in historial]
        messages.append({"role": "user", "content": mensaje_usuario})
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=_prompt_final,
            messages=messages,
        )
        return response.content[0].text
    except anthropic.AuthenticationError:
        return "❌ API key inválida. Verifica el archivo `.streamlit/secrets.toml`."
    except anthropic.RateLimitError:
        return "⏳ Muchas consultas seguidas. Espera unos segundos e intenta de nuevo."
    except Exception as e:
        return f"❌ Error: {str(e)}"


def interpretar_proyecto(descripcion: str) -> dict | None:
    """
    Interpreta una descripción libre de proyecto y extrae parámetros
    para pre-llenar la calculadora. Retorna dict o None si falla.
    """
    client = get_client()
    if client is None:
        return None
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            system=SYSTEM_INTERPRET,
            messages=[{"role": "user", "content": descripcion}],
        )
        raw = response.content[0].text.strip()
        # Limpiar si viene con backticks
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception:
        return None


def generar_resumen_cotizacion(resultado: dict, contexto: dict) -> str:
    """
    Genera un resumen inteligente de la cotización para mostrar al usuario.
    Le dice si el precio está bien, si hay riesgos, y qué puede optimizar.
    """
    client = get_client()
    if client is None:
        return ""

    prompt = f"""El usuario acaba de calcular una cotización. Analiza los resultados y da un resumen ejecutivo breve (máx 3 párrafos):

DATOS DEL PROYECTO:
- Material: {contexto.get('categoria', '?')} — {contexto.get('referencia', '?')}
- Tipo: {contexto.get('tipo_proyecto', '?')}
- m² instalados: {contexto.get('m2_real', '?')}
- Aprovechamiento lámina: {resultado.get('aprovechamiento', 0):.0f}%
- Retal: {resultado.get('retal', 0):.2f} m²

RESULTADOS:
- Costo total: ${resultado.get('costo_total', 0):,.0f}
- Precio sugerido (margen {resultado.get('margen_pct', 40):.0f}%): ${resultado.get('precio_sugerido', 0):,.0f}
- Utilidad proyectada: ${resultado.get('utilidad', 0):,.0f}
- Desglose: material ${resultado.get('c1_material', 0):,.0f} | mano de obra ${resultado.get('c2_mano_obra', 0):,.0f} | logística ${resultado.get('c5_logistica', 0):,.0f}

Comenta: ¿el aprovechamiento es bueno o hay mucho retal? ¿el margen es saludable? ¿hay algo que optimizar?
Sé directo y usa formato de moneda colombiana ($1.000.000)."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception:
        return ""
# ── System prompt del Bot SOS ─────────────────────────────────────────────────
_SYSTEM_SOS = """Eres el asistente de ayuda rapida del sistema de cotizacion de MARMOLES COLLANTE & CASTRO LTDA.

TU MISION: Responder dudas sobre como usar la app y sobre terminologia de marmoleria.
Respondes en MAXIMO 2 parrafos cortos. Sin listas ni encabezados. Directo y claro.

PAGINAS DE LA APP:
- Inicio: pantalla de bienvenida y tour guiado
- Cotizacion Directa: cotizador principal (ML, m2, materiales, logistica, calculo)
- Cotizacion AIU: cotizador para obra publica con estructura A+I+U+IVA
- Historial: registro de todas las cotizaciones, busqueda y cambio de estado
- Dashboard: analiticas del negocio, materiales mas rentables, facturacion mensual
- Banco de Retales: inventario de sobrantes de material aprovechables
- Parametros: edicion de tarifas de mano de obra, logistica y viaticos
- Asistente IA: chat completo para analisis de proyectos y asesoria de costos
- Configuracion: datos de la empresa, logo, banco, condiciones de los PDFs
- Gestion de Equipo: (solo Admin) registrar y gestionar usuarios del sistema

GLOSARIO CLAVE DE MARMOLERIA:
- ML (Metro Lineal): unidad de medida de longitud. Un meson de 3 ML x 0,60 m de ancho = 1,80 m2.
- Retal: sobrante de lamina que quedo tras cortar el proyecto. Puede reutilizarse.
- Lamina / Placa: pieza completa de piedra tal como llega del proveedor.
- Aprovechamiento: % de la lamina realmente usado. 85%+ es bueno; <70% hay mucho desperdicio.
- Perfilado: acabado del borde visible de la piedra (bisel, media cana, recto, etc.).
- AIU: Administracion + Imprevistos + Utilidad. Estructura de precios para obra publica.
- IVA en AIU: segun Decreto 1372/92 de Colombia, el IVA (19%) se aplica SOLO sobre la Utilidad.
- Mano de obra: se paga por ML cortado e instalado, no por hora.
- Consumibles: lijas, masilla de poliester, ceras, sellador, estopa usados en la instalacion.
- Disco diamantado: herramienta de corte. Se desgasta ~90 m2 en marmol, menos en sinterizado.
- Sinterizado: material tecnico de alta resistencia. Requiere herramientas especiales.
- Quarzita: piedra natural muy dura, diferente al quarztone (cuarzo compactado).
- Zocalo: pieza baja de piedra instalada en la pared junto al piso (10 cm alto estandar).
- Margen: (precio - costo) / precio x 100. Saludable: 30-45%. Minimo viable: 20%.

TONO: Espanol colombiano claro. Amigable pero profesional. Sin tecnicismos innecesarios.
"""


def chat_sos(pregunta: str, contexto_actual: str = "Inicio", contexto_form: str = "",
             contexto_tarifas: dict = None) -> str:
    """
    Asistente contextual rapido para el boton SOS del sidebar.

    Args:
        pregunta:          duda del usuario en texto libre
        contexto_actual:   pagina en la que esta el usuario (st.session_state.nav_radio)
        contexto_form:     volcado en texto de st.session_state.pre — datos
                           del formulario activo (material, dimensiones, precios, etc.)
        contexto_tarifas:  dict de tarifas activas del taller
                           (st.session_state.tarifas_custom o TARIFAS base).
                           Se inyecta al system prompt para que la IA responda
                           usando los costos reales configurados en Parámetros.

    Returns:
        Respuesta en maximo 2 parrafos. Mensaje de error descriptivo si falla.
    """
    client = get_client()
    if client is None:
        return (
            "El asistente IA no esta configurado. Para activarlo, agrega tu API key "
            "de Anthropic en `.streamlit/secrets.toml` con la clave `ANTHROPIC_API_KEY`."
        )
    try:
        # ── RAG dinámico: inyectar tarifas reales en el system prompt ──────────
        _tarifas_txt_sos = _tarifas_a_texto(contexto_tarifas or TARIFAS)
        _system_sos_final = _SYSTEM_SOS + (
            f"\n\nTARIFAS DE TRABAJO ACTUALES DEL TALLER:\n{_tarifas_txt_sos}"
        )

        # ── Construir mensaje con contexto del formulario ─────────────────────
        _partes = [f"Estoy en la seccion '{contexto_actual}' de la app."]
        if contexto_form.strip():
            _partes.append(
                "\n\nAQUI TIENES LOS DATOS ACTUALES DE LA CALCULADORA DEL USUARIO. "
                "Basa tus respuestas en estas medidas, precios y selecciones exactas:\n"
                + contexto_form
            )
        _partes.append(f"\n\nMi duda es: {pregunta}")
        mensaje = "".join(_partes)

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            system=_system_sos_final,
            messages=[{"role": "user", "content": mensaje}],
        )
        return response.content[0].text
    except Exception as e:
        return f"No pude consultar la IA en este momento. ({type(e).__name__})"


def extraer_coordenadas_plano(descripcion: str) -> dict | None:
    """
    Interpreta una descripción libre de plano de taller y extrae
    coordenadas y medidas para el motor de generación de planos SVG.
    Retorna dict con las coordenadas o None si falla.
    """
    client = get_client()
    if client is None:
        return None

    _SYSTEM_PLANO = """Eres un extractor de datos para un generador de planos de marmolería.
El usuario describe las medidas de un proyecto. Extrae las dimensiones y devuelve SOLO un JSON.

REGLAS:
1. Devuelve SOLO el JSON, sin texto antes ni después, sin backticks
2. Convierte todas las medidas a metros (ej: 90cm → 0.90)
3. Si una medida no se menciona, usa null
4. tipo_pieza: "meson", "isla", "bano", "piso", "escalera", "fachada", "otro"

JSON a retornar:
{
  "tipo_pieza": "string",
  "piezas": [
    {
      "nombre": "string",
      "largo": numero_o_null,
      "ancho": numero_o_null,
      "cantidad": numero_entero
    }
  ],
  "notas": "observaciones adicionales o null"
}
"""
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            system=_SYSTEM_PLANO,
            messages=[{"role": "user", "content": descripcion}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception:
        return None


# ── Sistema de Investigación Automotriz con Web Search ───────────────────────
# Función dedicada con system prompt técnico + herramienta web_search.
# Aislada del asistente de marmolería — sin guardrails de cotización.
# Retorna {"rendimiento_km_gal": float, "capacidad_max_kg": float} o lanza excepción.

_SYSTEM_VEHICULO = """\
Eres un sistema experto en especificaciones técnicas automotrices para flotas de transporte en Colombia.
Tu tarea es obtener datos reales y precisos de un vehículo específico.

PROCESO OBLIGATORIO:
1. Usa web_search para buscar la ficha técnica oficial del vehículo.
   Busca: "[marca] [modelo] [año] ficha técnica carga útil Colombia"
   o en inglés: "[marca] [modelo] [año] payload capacity specifications"
2. Extrae del fabricante o fuente técnica:
   - rendimiento_km_gal: km por galón en uso urbano/mixto con carga típica
     (si encuentras l/100km, convierte: 235.2 / litros_por_100km)
   - capacidad_max_kg: carga útil máxima en kg según ficha del fabricante
3. Responde ÚNICAMENTE con un objeto JSON válido con exactamente dos llaves numéricas.
   Sin texto antes ni después del JSON. Sin markdown. Sin explicaciones.

Ejemplo de respuesta correcta:
{"rendimiento_km_gal": 9.5, "capacidad_max_kg": 850.0}
"""


def investigar_vehiculo(nombre_vehiculo: str) -> dict:
    """
    Investiga la ficha técnica REAL de un vehículo usando IA con web_search.

    Usa el tool web_search de Anthropic para consultar fuentes técnicas reales
    (fabricante, fichas técnicas, bases de datos automotrices) en lugar de
    depender del conocimiento estático de entrenamiento.

    Args:
        nombre_vehiculo: nombre del vehículo (ej: "Ford Ranger 2024")

    Retorna:
        dict con {"rendimiento_km_gal": float, "capacidad_max_kg": float}

    Lanza:
        ValueError si la IA no devuelve JSON parseable con las llaves esperadas.
        RuntimeError si el cliente de IA no está disponible.
    """
    import re as _re
    client = get_client()
    if client is None:
        raise RuntimeError(
            "IA no disponible. Configura ANTHROPIC_API_KEY en .streamlit/secrets.toml"
        )

    # Intentar primero con web_search para datos reales
    # Si falla (rate limit, etc.), intentar sin web_search como fallback
    _query = nombre_vehiculo.strip()
    _raw = ""

    for _use_web in (True, False):
        try:
            _kwargs = dict(
                model="claude-sonnet-4-6",
                max_tokens=512,
                system=_SYSTEM_VEHICULO,
                messages=[{"role": "user", "content": _query}],
            )
            if _use_web:
                _kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]
            response = client.messages.create(**_kwargs)
            # Extraer texto de todos los bloques content (puede haber tool_use + text)
            _raw = " ".join(
                b.text for b in response.content
                if hasattr(b, "text") and b.text
            ).strip()
            if _raw:
                break  # tenemos respuesta, salir del loop
        except Exception as _e_web:
            if not _use_web:
                raise  # si falla sin web también, relanzar
            # Si falla con web, intentar sin web_search
            continue

    if not _raw:
        raise ValueError("La IA no devolvió respuesta para el vehículo solicitado.")

    # Extracción robusta: greedy + DOTALL captura JSON aunque tenga saltos de línea
    raw_clean = _raw.replace("```json", "").replace("```", "").strip()
    match = _re.search(r"\{[^{}]*\}", raw_clean, _re.DOTALL)
    if not match:
        # Intentar extracción más permisiva con nested braces
        match = _re.search(r"\{.*\}", raw_clean, _re.DOTALL)
    if not match:
        raise ValueError(f"La IA no devolvió JSON válido. Respuesta: {_raw[:300]!r}")

    data = json.loads(match.group(0))
    rend = data.get("rendimiento_km_gal")
    cap  = data.get("capacidad_max_kg")
    if rend is None or cap is None:
        raise ValueError(
            f"JSON incompleto — faltan llaves esperadas. Datos: {data}"
        )
    return {
        "rendimiento_km_gal": float(rend),
        "capacidad_max_kg":   float(cap),
    }


# ── Auditor financiero de cotizaciones ─────────────────────────────────────────-
_SYSTEM_AUDITOR = """Eres un AUDITOR FINANCIERO experto en marmolería
para MARMOLES COLLANTE & CASTRO LTDA. en Barranquilla, Colombia.

Tu misión: revisar una cotización ANTES de enviarla al cliente y detectar:
- márgenes peligrosamente bajos
- olvidos de cobros lógicos (lavaplatos, perforaciones, desmontes, transporte, viáticos)
- perfiles de desperdicio incoherentes (merma muy baja en sinterizado, cuarzo, quarzita)
- cualquier fuga de dinero típica en talleres de mármol.

REGLAS ESTRICTAS:
1. Recibirás un JSON con todos los datos de la cotización (costos, precio, margen, material, tipo de proyecto, extras, logística, etc.).
2. Debes analizarlo y RESPONDER ÚNICAMENTE con un JSON válido, SIN texto antes ni después, SIN backticks y SIN comentarios.
3. Usa esta estructura EXACTA:
{
  "estado": "verde|amarillo|rojo",
  "margen_analisis": "Breve comentario sobre si el margen % es saludable para el taller.",
  "alertas": ["Alerta 1 (riesgos de pérdida de dinero)", "Alerta 2"],
  "sugerencias": ["Sugerencia 1 (oportunidades para cobrar extras lógicos)", "Sugerencia 2"]
}
4. "estado":
   - "verde": margen saludable (aprox. 30-45%), sin fugas evidentes.
   - "amarillo": margen aceptable pero con riesgos moderados u olvidos probables.
   - "rojo": pérdida de dinero, errores graves o margen <20%.
5. Si el JSON de entrada no tiene algún dato, asume un valor conservador y menciona la incertidumbre en "alertas".
6. No repitas literalmente todo el JSON de entrada en los mensajes; céntrate en el análisis financiero.
7. Usa español colombiano claro, concreto y profesional. Nada de relleno.
"""


def auditor_rentabilidad(datos_cotizacion: dict) -> dict:
    """
    Analiza la rentabilidad y riesgos de una cotización de marmolería.

    Args:
        datos_cotizacion: dict con toda la información relevante de la cotización.

    Returns:
        dict con la estructura:
        {
          "estado": "verde|amarillo|rojo",
          "margen_analisis": "texto",
          "alertas": [...],
          "sugerencias": [...]
        }

    Lanza:
        RuntimeError si la IA no está disponible.
        ValueError si la respuesta de la IA no es un JSON válido con la estructura esperada.
    """
    client = get_client()
    if client is None:
        raise RuntimeError(
            "IA no disponible. Configura ANTHROPIC_API_KEY en .streamlit/secrets.toml"
        )

    try:
        payload_str = json.dumps(datos_cotizacion, ensure_ascii=False, indent=2)
        prompt = (
            "Revisa la siguiente cotización de marmolería y devuelve ÚNICAMENTE un JSON "
            "con el análisis usando la estructura indicada en el system prompt.\n\n"
            "COTIZACION:\n"
            f"{payload_str}\n"
        )

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system=_SYSTEM_AUDITOR,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = "".join(
            getattr(b, "text", "") for b in response.content
            if hasattr(b, "text") and b.text
        ).strip()

        # Extracción robusta del primer bloque JSON con regex
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError(f"La IA no devolvió un JSON válido. Esto fue lo que respondió:\n{raw}")

        json_str = match.group(0)
        data = json.loads(json_str)

        # Validación mínima de estructura
        if not isinstance(data, dict):
            raise ValueError("La IA no devolvió un objeto JSON de nivel raíz.")
        for key in ("estado", "margen_analisis", "alertas", "sugerencias"):
            if key not in data:
                raise ValueError(f"Falta la clave obligatoria '{key}' en la respuesta de la IA.")

        return data
    except ValueError:
        # Propagar ValueError tal cual, según requisito
        raise
    except Exception as e:
        raise ValueError(f"Fallo al analizar la respuesta del auditor IA: {e}") from e
