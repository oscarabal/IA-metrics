# Guía de las gráficas de los dashboards

Qué muestra cada gráfica de los tres dashboards de IA-metrics, cómo leerla y para qué sirve. Las guías de
cada herramienta ([Claude Code](claude-code.md), [OpenCode](opencode.md)) explican además la configuración
y las páginas de sesión e informe. [English version](dashboards.en.md).

| Dashboard | Dirección | Periodo por defecto |
| --- | --- | --- |
| Resumen IA (inicio) | <http://localhost:3000/d/ia-overview> | Últimos 30 días |
| Claude Code | <http://localhost:3000/d/claude-code> | Últimos 7 días |
| OpenCode | <http://localhost:3000/d/opencode-usage> | Últimos 90 días |

## Antes de empezar: cómo leerlos

- **El coste es a precio de API.** Es lo que costaría pagando por token. Con una suscripción (Claude
  Pro/Max, GitHub Copilot) no es lo que pagas, sino una medida de cuánto la aprovechas. Cómo se calcula:
  [coste híbrido](architecture/08-crosscutting-concepts.md#coste-híbrido).
- **Filtros de arriba.** El selector de tiempo de Grafana y **Proyecto** filtran casi todo. **Texto de los
  prompts** (Oculto / Visible) decide si «Prompts más caros» enseña el texto; oculto, el colector envía
  asteriscos.
- **Paneles que no siguen el periodo.** Los de contexto de sesiones y cuotas muestran el estado actual (salen
  de Prometheus), y las gráficas semanales cubren siempre las últimas 13 semanas. Su descripción lo indica.
- **Días y horas** en la zona horaria de los colectores (`TZ`, por defecto Europe/Madrid).
- **Colores.**
  - Azul: coste. Morado: tokens o veces. En el Resumen IA, naranja es Claude Code y azul OpenCode.
  - Semáforo de ocupación (contexto, cuota): verde por debajo del 60 %, naranja desde el 60 % y rojo
    desde el 85 %.
  - Tasa de errores: naranja desde el 5 % y rojo desde el 15 %.
  - «Modelos sin precio»: verde con 0, rojo con 1 o más.
- **Más detalle.** El icono ⓘ de cada panel tiene su descripción, y «Inspect → Data» enseña los números.

## Resumen IA

El gasto de las dos herramientas juntas. Si solo instalaste una, los paneles de la otra muestran un aviso de
conexión.

### Coste total · Tokens totales · Sesiones

Tres cifras del periodo: coste de las dos herramientas, millones de tokens (caché incluida) y sesiones
principales iniciadas, sin subagentes. Son el punto de partida: si el coste sube, las gráficas de debajo
dicen dónde.

### Coste por herramienta

Una cifra por herramienta, con su color. Para ver de un vistazo cuál pesa más.

### Coste diario por herramienta

Barras por día, una serie por herramienta. Un pico señala un día con mucho trabajo o con un modelo caro; para
saber cuál, abre el dashboard de esa herramienta en ese día.

### Reparto del coste

Tarta con la parte de cada herramienta en el periodo.

### Coste por proyecto (ambas herramientas)

Barras horizontales con el coste de cada proyecto, sumando las dos herramientas. El proyecto es la carpeta de
trabajo de la sesión. Sirve para saber a qué se dedica el gasto.

### Eficiencia por herramienta

Tabla para comparar las dos herramientas: USD por millón de tokens, coste medio por respuesta y acierto de
caché. Un USD por millón más bajo significa modelos más baratos o más caché.

## Claude Code

### Resumen de Claude Code

**Coste estimado.** Coste de todas las llamadas del periodo.

**Modelos sin precio.** Cuántos de tus modelos no están en `prices.json`. En rojo, su coste sin telemetría no
cuenta. Al pulsarlo se abre la página de precios en una pestaña nueva.

**Tokens.** Entrada, salida y caché, en millones.

**USD por millón de tokens.** Precio medio efectivo. Baja si usas modelos más baratos o aprovechas más la caché.

**Acierto de caché.** Parte de la entrada que se leyó de caché (lectura de caché entre lectura, escritura de
caché y entrada). Cuanto más alto, más barato: las lecturas de caché cuestan una décima parte que la entrada.

**Sesiones con actividad.** Sesiones con alguna respuesta en el periodo. Al pulsar la cifra se abre la lista
de sesiones.

**Evolución diaria.** Barras de coste (eje izquierdo) y línea de tokens en millones (eje derecho) por día. Si
las barras crecen más que la línea, ese día se usaron modelos o efforts más caros.

**Coste por effort.** Barras con el gasto de cada nivel de esfuerzo de razonamiento. Si casi todo está en
`high` o `xhigh`, trabajar en un nivel más bajo para tareas sencillas ahorra. «desconocido» son peticiones sin
effort registrado.

**Coste por proyecto.** Barras con el coste de cada proyecto.

### Reparto del gasto

**Cuota de coste y de tokens por modelo.** Dos barras por modelo, para los diez que más cuestan («otros» suma
el resto): su parte del coste (azul) y su parte de los tokens (morado). Si la barra de tokens es mucho más
larga que la de coste, el modelo es barato; si es al revés, caro. Es la gráfica clave para decidir qué tareas
pasar a un modelo más económico.

**Detalle por modelo y effort.** Tabla con el coste de cada combinación de modelo y effort, con el total en el
pie.

### Sesiones, skills y prompts

**Contexto de las sesiones.** Las sesiones recientes con actividad (hasta 30). Para cada una: el porcentaje de
la ventana de contexto que ocupa su último mensaje, con el semáforo de ocupación, y los tokens usados, libres
y el límite. Una sesión en rojo está cerca de compactar; empezar otra suele salir más barato. Al pulsar una
sesión se abre su detalle.

**Uso de skills y comandos (veces).** Cada comando propio y cada skill: cuántas veces lo escribiste como
comando y cuántas lo cargó Claude como skill. Uno que no aparece en meses es candidato a retirarse.

**Modelos y origen por comando.** Coste de los turnos que lanzó cada comando, por modelo y por origen:

- `sdk`: el hilo principal;
- `agent:…`: subagentes;
- `prompt_suggestion`, `compact` o `web_search_tool`: llamadas de fondo.

Responde a «qué modelos se usaron al lanzar este comando».

**Prompts más caros.** Los 15 turnos más caros: un prompt y todas las llamadas al modelo que lo respondieron.
«Modelo» es el que más costó en ese turno. Sirve para ver qué tipo de petición sale cara.

**Herramientas.** Por herramienta: llamadas, bytes devueltos al contexto, esos bytes como tokens aproximados
(bytes entre 4) y duración media. Las que más devuelven son las que más llenan el contexto, que se relee en
cada llamada siguiente. La duración incluye la espera a que apruebes un permiso.

### Mejoras en Claude Code

Paneles del informe de mejoras, calculados para el periodo y los proyectos elegidos. Es el mismo cálculo que
el informe que se descarga.

**Mejoras detectadas.** Número de hallazgos. Al pulsar se abre el informe.

**Impacto estimado.** Suma del impacto en dólares de los hallazgos: un orden de magnitud del gasto evitable,
no un ahorro garantizado.

**Errores evitables de herramientas.** Parte de las llamadas a herramientas que fallaron, sin contar rechazos
(también de planes), bloqueos, interrupciones ni comandos que terminan con error.

**Compactaciones e interrupciones.** Veces que se compactó el contexto y respuestas que interrumpiste.

**Hallazgos.** Una fila por mejora, de mayor a menor severidad: qué pasa, cuánto pesa y qué cambiar. Pasa el
ratón por una celda para leerla entera.

**Hallazgos por regla.** Los hallazgos agrupados por regla y ordenados por impacto. Las reglas están en la
[guía de Claude Code](claude-code.md).

**Errores evitables por herramienta y modelo.** Tabla con las herramientas y modelos que tienen algún error
evitable, con la tasa coloreada (naranja desde el 5 %, rojo desde el 15 %). Ahí suele compensar una regla en
`CLAUDE.md` o usar otro modelo.

**Coste por mensaje de cada modelo, por semana.** Una línea por modelo con su coste medio por mensaje, las
últimas 13 semanas. Sirve para comprobar el efecto de cambiar de modelo o de effort: tras el cambio, la línea
debería bajar.

**Errores evitables por herramienta, por semana.** Tasa de error semanal de las cinco herramientas que más
fallan, las últimas 13 semanas. Si añades una regla a `CLAUDE.md`, aquí se ve si funciona.

**Bytes devueltos al contexto por herramienta.** Lo que cada herramienta devolvió al contexto según la
telemetría, con los tokens aproximados.

### Por hora (fila plegada)

**Tokens por modelo (por hora).** Tokens de cada hora, apilados por modelo, en millones. Para ver a qué horas
se trabaja y con qué.

**Coste por modelo y effort (por hora).** Coste de cada hora por modelo y effort. El effort solo se conoce en
las peticiones con telemetría; el resto aparece como «sin telemetría».

## OpenCode

### Resumen de OpenCode

**Coste estimado.** Coste del periodo a precio de API. Es el que guardó OpenCode y, cuando guardó 0
(suscripción como Copilot, o un modelo que no conoce), tokens × precio de models.dev
([ADR 0005](adr/0005-coste-de-opencode-a-precio-de-api.md)).

**Modelos sin precio.** Modelos con mensajes de coste 0 que no se pueden valorar porque no hay precio para
ellos en `models.json`, ni de su proveedor ni de su fabricante. Al pulsarlo se abre la página de precios.

**Tokens.** Entrada, salida, razonamiento y caché, en millones.

**USD por millón de tokens.** Precio medio efectivo, como en Claude Code.

**Acierto de caché.** Parte de la entrada que se leyó de caché.

**Sesiones.** Sesiones principales creadas en el periodo, sin las de subagente. Al pulsar se abre la lista.

**Contexto de las sesiones recientes.** Las cinco sesiones más recientes: cuánto contexto ocupa su último
mensaje y cuánto queda, con el semáforo de ocupación. Sigue el proyecto elegido, no el periodo.

**Cuota y uso por proveedor.** Coste, mensajes y tokens del periodo por proveedor y, para los que tienen cuota
(con el plugin `opencode-quota`), lo usado, lo disponible, el porcentaje usado con el semáforo de ocupación y
cuándo se restablece. Una cuota en rojo avisa de que te vas a quedar sin uso antes del reinicio.

**Evolución semanal.** Barras de coste (eje izquierdo) y línea de tokens (eje derecho) de las últimas 13
semanas. Sigue el proyecto elegido, no el periodo.

**Coste por agente.** Barras con el coste de `plan`, `build` y tus agentes propios.

**Coste por proyecto.** Barras por carpeta del proyecto; `global` agrupa lo que OpenCode no asocia a ninguno.

**Cuota de coste y de tokens por modelo.** Igual que en Claude Code: la parte del coste frente a la de los
tokens de los diez modelos más caros. La barra de tokens mucho mayor que la de coste indica un modelo barato.

**Comandos · Skills.** Una tabla para cada uno: activaciones (correctas y fallidas) y coste de los turnos en
que se usaron. Al desplegar una fila se ven el modelo y el agente que respondieron, con su parte del coste. El
coste no se puede aislar: incluye todo el turno.

**Prompts más caros.** Los 15 turnos más caros, con el agente y el modelo que más costaron. Los subagentes
cuentan aparte, en su propia sesión.

**Detalle por modelo.** Una fila por proveedor y modelo, de mayor a menor coste, con totales en el pie.

### Actividad diaria por modelo

**Coste por día y modelo.** Barras apiladas por día con los ocho modelos más caros («Otros» suma el resto).
Solo aparecen los días con actividad. Sirve para ver cuándo entró un modelo nuevo y cuánto pesa.

**Actividad por día y modelo.** Tabla con mensajes, tokens y coste de cada modelo cada día. El filtro de cada
columna busca un modelo o un día.

### Mejoras en OpenCode

Como en Claude Code, con el informe de OpenCode (reglas D1–D11 en la [guía de OpenCode](opencode.md)):
**Mejoras detectadas**, **Impacto estimado**, **Errores evitables de herramientas** (sin bloqueos por
permisos, rechazos ni interrupciones), **Compactaciones e interrupciones**, **Hallazgos**, **Hallazgos por
regla** y **Errores evitables por herramienta y modelo**. En OpenCode la regla que suele compensar va en
`AGENTS.md`. Además:

**Coste por mensaje de cada agente, por semana.** Una línea por agente con su coste medio por mensaje, las
últimas 13 semanas. Sirve para ver si cambiar el modelo de un agente lo abarata.

**Errores evitables por herramienta, por semana.** Tasa de error semanal de las cinco herramientas que más
fallan.

**Compactaciones e interrupciones, por semana.** Dos líneas, las últimas 13 semanas. Si suben, las sesiones
se alargan demasiado o las respuestas no van por donde quieres.

## Preguntas frecuentes al mirar los dashboards

| Pregunta | Dónde mirar |
| --- | --- |
| ¿Cuánto llevo gastado este mes, en total? | Resumen IA → Coste total, con el periodo «Este mes» |
| ¿Qué herramienta o proyecto cuesta más? | Resumen IA → Coste por herramienta · Coste por proyecto |
| ¿Qué modelo me sale caro? | Cuota de coste y de tokens por modelo (en cada herramienta) |
| ¿Me compensa bajar el effort? | Claude Code → Coste por effort · Coste por mensaje de cada modelo, por semana |
| ¿Qué petición fue la más cara? | Prompts más caros |
| ¿Por qué se llena el contexto? | Herramientas · Bytes devueltos al contexto · Contexto de las sesiones |
| ¿Me voy a quedar sin cuota? | OpenCode → Cuota y uso por proveedor |
| ¿Ha funcionado la regla que añadí? | Errores evitables por herramienta, por semana |
| ¿Por qué un coste sale 0 o falta? | Modelos sin precio → página de precios |
