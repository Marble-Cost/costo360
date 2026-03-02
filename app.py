Actúa como un Auditor de Software B2B y Arquitecto de Datos. Hemos detectado fallos críticos de usabilidad, matemáticas comerciales y análisis de datos en la versión actual de CostoMarmol. La refactorización anterior omitió soluciones vitales.

Aplica ESTRICTAMENTE las siguientes 5 correcciones a los archivos adjuntos y devuélveme el código completo refactorizado de app.py, calculos.py y asistente_ia.py:

1. Corrección Real de la Tasa de Cierre (app.py):





En la función _stats_db() y en la métrica del Dashboard, modifica la fórmula matemática de la Tasa de Cierre.



Ya NO debe dividir entre el total absoluto. La fórmula obligatoria para la conversión es: (Aprobadas / (Aprobadas + Rechazadas)) * 100. Si (Aprobadas + Rechazadas) es 0, la tasa es 0%. Ignora el estado "Pendiente" y "En revisión" para este cálculo de rendimiento.

2. Eliminación de la Mentira Contable del Retal (app.py):





En la sección "Banco de Retales" / "Sobrantes Aprovechables", localiza el texto de ayuda que dice "Pon $0 si lo reutilizas..." y elimínalo por completo.



Cambia la sugerencia a un enfoque de Business Intelligence: "Ingresa el costo base del material o el valor mínimo de recuperación contable. Evita colocar $0 para no generar márgenes de ganancia ilusorios en tus reportes."

3. Atajo de Edición en el Wizard (Anti-Fricción en app.py):





En el bloque de "Cotización Directa", justo debajo del título principal de la página, implementa una validación: if st.session_state.get("editando_id"):.



Si esto es verdadero, inyecta un botón destacado (ej. st.button("💾 Guardar cambios de esta edición")) que permita ejecutar la función de _actualizar_cotizacion y limpiar el estado INMEDIATAMENTE, sin obligar al usuario a navegar por los 5 pasos del wizard.

4. Adaptabilidad a Móviles con Data Editor (app.py):





En la pestaña de Parámetros -> Costos Adicionales, la estructura actual usa un bucle de st.columns con 7 divisiones que colapsa catastróficamente en dispositivos móviles.



Destruye ese bloque de columnas y reemplázalo usando st.data_editor. Pasa la lista de diccionarios de adicionales al data_editor permitiendo edición dinámica (añadir y borrar filas). Esto es 100% responsivo y profesional.

5. El Copiloto IA con Memoria (asistente_ia.py y app.py):





En app.py, modifica la llamada a la función del Copiloto en el sidebar. En lugar de pasarle solo st.session_state.nav_radio, pásale como contexto un volcado resumido en texto de todo lo que el usuario lleva rellenado en st.session_state.pre.



En asistente_ia.py, modifica el prompt de chat_sos para que reciba estos datos del formulario e indique a la IA: "Aquí tienes los datos actuales de la calculadora del usuario. Basa tus respuestas en estas medidas, precios y selecciones exactas."

Devuélveme los archivos actualizados garantizando que ninguna de estas instrucciones sea omitida.
