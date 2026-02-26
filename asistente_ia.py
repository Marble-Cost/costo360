# asistente_ia.py — CostoMármol v2
# IA real con Claude + capacidad de interpretar proyectos en lenguaje natural

import json
import anthropic
import streamlit as st
from parametros import TARIFAS, LOGISTICA, VIATICOS, AIU_DEFAULTS, CATEGORIAS_MATERIAL

# ── System prompt principal ────────────────────────────────────────────────────
SYSTEM_PROMPT = """Eres el asistente experto en costos y cotización de Mármoles Collante & Castro Ltda., 
Barranquilla, Colombia. Ayudas a marmoleros a calcular el costo real de sus proyectos.

DATOS DEL MERCADO (Feb 2026, Barranquilla):
- Gasolina: $15.800/galón
- Frontier NP300: 7.2 km/gal ciudad, desgaste $148/km, flete base $65.000
- Cheyenne V8: 4.1 km/gal ciudad, desgaste $340/km, flete base $85.000
- Externo/Tercero: flete fijo $165.000 | Peaje: $19.500 | Flete agente: $85.000
- Viáticos pueblo: $145.000/noche/persona | Ciudad: $178.000/noche/persona

TARIFAS DE TRABAJO (mano de obra):
- Mármol:      corte $25.000/m², elaboración $75.000/m², zócalo $12.000/ml, disco $2.200/m², desgaste maq. $20.000/día
- Granito:     corte $28.000/m², elaboración $48.000/m², zócalo $14.000/ml, disco $6.000/m², desgaste maq. $25.000/día
- Sinterizado: corte $45.000/m², elaboración $70.000/m², zócalo $20.000/ml, disco $18.000/m², desgaste maq. $32.000/día
- Quarztone:   corte $32.000/m², elaboración $55.000/m², zócalo $16.000/ml, disco $5.200/m², desgaste maq. $27.000/día
- Cuarcita:    corte $35.000/m², elaboración $65.000/m², zócalo $15.000/ml, disco $8.000/m², desgaste maq. $28.000/día

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
  "categoria": "Mármol|Granito|Sinterizado|Quarztone|Cuarcita|null",
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


def chat_con_ia(historial: list, mensaje_usuario: str) -> str:
    """Respuesta conversacional del asistente."""
    client = get_client()
    if client is None:
        return (
            "⚠️ **IA no configurada.** Para activarla, crea el archivo `.streamlit/secrets.toml` "
            "con tu API key de Anthropic (instrucciones en la barra lateral)."
        )
    try:
        messages = [{"role": m["role"], "content": m["content"]} for m in historial]
        messages.append({"role": "user", "content": mensaje_usuario})
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
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
            model="claude-opus-4-6",
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
            model="claude-opus-4-6",
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception:
        return ""
