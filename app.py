Actúa como Arquitecto de Software Principal y Analista de Datos.

He detectado dos problemas de lógica de negocio en app.py:

El Riesgo de Rotura en el Paso 4 del Wizard es estático (2%), lo cual es financieramente peligroso para materiales frágiles como el Sinterizado.

La mini-tabla de contexto del Asistente IA está "hardcodeada" (texto estático) y está incompleta, por lo que no refleja los verdaderos costos dinámicos del usuario.

Tu tarea:

Fase 1: Riesgo Dinámico por Material (Paso 4 del Wizard with t_tar:)
En la lógica donde se clona la _receta_base para cada categoría (for _m in CATEGORIAS_MATERIAL:):

No agregues el "Seguro contra Roturas" en la lista _receta_base general antes del loop.

En su lugar, dentro del loop for _m in CATEGORIAS_MATERIAL:, inyecta la regla de Seguro evaluando el nombre del material _m:

Si _m == "Sinterizado": valor 0.05 (5%).

Si _m in ["Mármol", "Quarztone"]: valor 0.03 (3%).

else (Granito/Otros): valor 0.02 (2%).

Añade esta regla dinámica a la lista clonada específica de ese material antes de guardarla en _saved_tar[_m].

Fase 2: Tabla de Contexto IA Dinámica
Busca la sección en app.py donde se renderiza la interfaz del Asistente IA y su mini-tabla de contexto (usualmente un st.markdown o st.dataframe con datos quemados de gasolina y MO).
Reemplaza esa tabla estática por un bloque dinámico que lea directamente del st.session_state:

Muestra el Costo de Combustible actual (logistica_custom.get("precio_galon", 16000)).

Muestra la Utilidad Esperada actual (aiu_custom.get("utilidad", 20) %).

Muestra el Costo de Luz/Agua por m² (si existe en la receta de Granito, búscalo, o simplemente pon una nota de "Costos Fijos parametrizados").

Da formato de tabla Markdown generada dinámicamente con un f-string para que siempre muestre los valores reales y actualizados en la memoria de la app.

Entregable:
Entrégame EXCLUSIVAMENTE los dos bloques de código corregidos:

El bloque elif paso_wizard == 4: completo con la inyección dinámica.

El bloque exacto donde se renderiza la tabla del Asistente IA, transformado a dinámico.
