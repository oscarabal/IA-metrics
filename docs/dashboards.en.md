# Dashboard chart guide

What each chart of the three IA-metrics dashboards shows, how to read it and what it is for. Panel names are
given as they appear in Grafana (in Spanish), with a translation the first time. The per-tool guides
([Claude Code](claude-code.md), [OpenCode](opencode.md), in Spanish) also cover configuration and the session
and report pages. [Versión en español](dashboards.md).

| Dashboard | Address | Default time range |
| --- | --- | --- |
| Resumen IA (home) | <http://localhost:3000/d/ia-overview> | Last 30 days |
| Claude Code | <http://localhost:3000/d/claude-code> | Last 7 days |
| OpenCode | <http://localhost:3000/d/opencode-usage> | Last 90 days |

## Before you start: how to read them

- **Cost is at API price.** It is what the usage would cost paying per token. With a subscription (Claude
  Pro/Max, GitHub Copilot) it is not what you pay, but a measure of how much you get out of it. How it is
  computed: [hybrid cost](architecture/08-crosscutting-concepts.md#coste-híbrido) (in Spanish).
- **Filters at the top.** Grafana's time picker and **Proyecto** (project) filter almost everything.
  **Texto de los prompts** (prompt text: Oculto / Visible, hidden / visible) decides whether «Prompts más
  caros» shows the text; when hidden, the collector sends asterisks.
- **Panels that ignore the time range.** Session context and quota panels show the current state (they come
  from Prometheus), and the weekly charts always cover the last 13 weeks. Their description says so.
- **Days and hours** are in the collectors' time zone (`TZ`, Europe/Madrid by default).
- **Colours.**
  - Blue: cost. Purple: tokens or counts. In Resumen IA, orange is Claude Code and blue is OpenCode.
  - Occupancy traffic light (context, quota): green below 60 %, orange from 60 % and red from 85 %.
  - Error rate: orange from 5 % and red from 15 %.
  - «Modelos sin precio» (models without a price): green at 0, red at 1 or more.
- **More detail.** Each panel's ⓘ icon has its description, and «Inspect → Data» shows the numbers.

## Resumen IA (AI overview)

Spend of both tools together. If you installed only one, the other's panels show a connection warning.

### Coste total · Tokens totales · Sesiones

Total cost · total tokens · sessions. Three figures for the period: cost of both tools, millions of tokens
(cache included) and main sessions started, without subagents. They are the starting point: if cost goes up,
the charts below tell you where.

### Coste por herramienta

Cost per tool. One figure per tool, in its colour, to see at a glance which one weighs more.

### Coste diario por herramienta

Daily cost per tool. Bars per day, one series per tool. A spike points to a day with a lot of work or an
expensive model; to find out which, open that tool's dashboard on that day.

### Reparto del coste

Cost split. Pie chart with each tool's share of the period.

### Coste por proyecto (ambas herramientas)

Cost per project (both tools). Horizontal bars with the cost of each project, adding up both tools. The project
is the session's working folder. It tells you what the spend goes to.

### Eficiencia por herramienta

Efficiency per tool. Table to compare both tools: USD per million tokens, average cost per answer and cache
hit rate. A lower USD per million means cheaper models or more cache.

## Claude Code

### Claude Code summary (Resumen)

**Coste estimado** (estimated cost). Cost of every call in the period.

**Modelos sin precio** (models without a price). How many of your models are missing from `prices.json`. When
red, their cost without telemetry is not counted. Clicking it opens the prices page in a new tab.

**Tokens.** Input, output and cache, in millions.

**USD por millón de tokens** (USD per million tokens). Effective average price. It goes down if you use
cheaper models or make more use of the cache.

**Acierto de caché** (cache hit rate). Share of the input read from cache (cache reads over cache reads,
cache writes and input). The higher, the cheaper: cache reads cost a tenth of regular input.

**Sesiones con actividad** (active sessions). Sessions with at least one answer in the period. Clicking the
figure opens the session list.

**Evolución diaria** (daily trend). Cost bars (left axis) and a token line in millions (right axis) per day.
If the bars grow more than the line, more expensive models or efforts were used that day.

**Coste por effort** (cost per effort). Bars with the spend at each reasoning effort level. If almost
everything is at `high` or `xhigh`, working at a lower level for simple tasks saves money. «desconocido»
(unknown) are requests with no recorded effort.

**Coste por proyecto** (cost per project). Bars with each project's cost.

### Reparto del gasto (spend breakdown)

**Cuota de coste y de tokens por modelo** (cost share and token share per model). Two bars per model for the
ten most expensive ones («otros», others, adds up the rest): its share of the cost (blue) and its share of the
tokens (purple). If the token bar is much longer than the cost bar, the model is cheap; the other way round,
expensive. This is the key chart to decide which tasks to move to a cheaper model.

**Detalle por modelo y effort** (detail per model and effort). Table with the cost of each model and effort
combination, with the total in the footer.

### Sesiones, skills y prompts (sessions, skills and prompts)

**Contexto de las sesiones** (session context). Recent active sessions (up to 30). For each one: the share of
the context window its last message takes, with the occupancy traffic light, and the tokens used, free and the
limit. A red session is close to compacting; starting a new one is usually cheaper. Clicking a session opens
its detail.

**Uso de skills y comandos (veces)** (skill and command usage, count). Each custom command and skill: how many
times you typed it as a command and how many times Claude loaded it as a skill. One unused for months is a
candidate for removal.

**Modelos y origen por comando** (models and origin per command). Cost of the turns each command launched, by
model and by origin:

- `sdk`: the main thread;
- `agent:…`: subagents;
- `prompt_suggestion`, `compact` or `web_search_tool`: background calls.

It answers «which models were used when I ran this command».

**Prompts más caros** (most expensive prompts). The 15 most expensive turns: a prompt and every model call
that answered it. «Modelo» is the one that cost most in that turn. It shows what kind of request turns out
expensive.

**Herramientas** (tools). Per tool: calls, bytes returned to the context, those bytes as approximate tokens
(bytes divided by 4) and average duration. The ones that return the most fill the context the most, and the
context is re-read on every following call. Duration includes the wait for you to approve a permission.

### Mejoras in Claude Code (improvements)

Panels of the improvement report, computed for the selected period and projects. Same computation as the
downloadable report.

**Mejoras detectadas** (improvements found). Number of findings. Clicking it opens the report.

**Impacto estimado** (estimated impact). Sum of the findings' impact in dollars: an order of magnitude of
avoidable spend, not guaranteed savings.

**Errores evitables de herramientas** (avoidable tool errors). Share of tool calls that failed, not counting
rejections (plans included), blocks, interruptions or commands that end with an error.

**Compactaciones e interrupciones** (compactions and interruptions). Times the context was compacted and
answers you interrupted.

**Hallazgos** (findings). One row per improvement, from highest to lowest severity: what happens, how much it
weighs and what to change. Hover over a cell to read it in full.

**Hallazgos por regla** (findings per rule). Findings grouped by rule and sorted by impact. The rules are
listed in the [Claude Code guide](claude-code.md).

**Errores evitables por herramienta y modelo** (avoidable errors per tool and model). Table with the tools and
models that have some avoidable error, with the rate coloured (orange from 5 %, red from 15 %). That is where a
rule in `CLAUDE.md` or another model usually pays off.

**Coste por mensaje de cada modelo, por semana** (cost per message of each model, per week). One line per model
with its average cost per message, last 13 weeks. Use it to check the effect of changing model or effort:
after the change, the line should drop.

**Errores evitables por herramienta, por semana** (avoidable errors per tool, per week). Weekly error rate of
the five tools that fail most, last 13 weeks. If you add a rule to `CLAUDE.md`, this is where you see whether
it works.

**Bytes devueltos al contexto por herramienta** (bytes returned to the context per tool). What each tool
returned to the context according to the telemetry, with approximate tokens.

### Por hora (hourly, collapsed row)

**Tokens por modelo (por hora)** (tokens per model, hourly). Tokens per hour, stacked by model, in millions. To
see at what times you work and with what.

**Coste por modelo y effort (por hora)** (cost per model and effort, hourly). Cost per hour by model and effort.
Effort is only known for requests with telemetry; the rest shows as «sin telemetría» (no telemetry).

## OpenCode

### OpenCode summary

**Coste estimado** (estimated cost). Cost of the period at API price. It is the cost OpenCode stored and, when
it stored 0 (a subscription such as Copilot, or a model it does not know), tokens × the models.dev price
([ADR 0005](adr/0005-coste-de-opencode-a-precio-de-api.md), in Spanish).

**Modelos sin precio** (models without a price). Models with zero-cost messages that cannot be valued because
`models.json` has no price for them, neither from their provider nor from their maker. Clicking it opens the
prices page.

**Tokens.** Input, output, reasoning and cache, in millions.

**USD por millón de tokens** (USD per million tokens). Effective average price, as in Claude Code.

**Acierto de caché** (cache hit rate). Share of the input read from cache.

**Sesiones** (sessions). Main sessions created in the period, without subagent ones. Clicking opens the list.

**Contexto de las sesiones recientes** (context of recent sessions). The five most recent sessions: how much
context their last message takes and how much is left, with the occupancy traffic light. Follows the selected
project, not the period.

**Cuota y uso por proveedor** (quota and usage per provider). Cost, messages and tokens of the period per
provider and, for those with a quota (with the `opencode-quota` plugin), used, available, the share used with
the occupancy traffic light and when it resets. A red quota warns you will run out before the reset.

**Evolución semanal** (weekly trend). Cost bars (left axis) and a token line (right axis) for the last 13
weeks. Follows the selected project, not the period.

**Coste por agente** (cost per agent). Bars with the cost of `plan`, `build` and your own agents.

**Coste por proyecto** (cost per project). Bars per project folder; `global` groups what OpenCode does not
associate with any project.

**Cuota de coste y de tokens por modelo** (cost share and token share per model). As in Claude Code: share of
cost against share of tokens for the ten most expensive models. A token bar much longer than the cost bar
means a cheap model.

**Comandos · Skills** (commands · skills). One table each: activations (successful and failed) and the cost of
the turns they were used in. Expanding a row shows the model and agent that answered, with their share of the
cost. The cost cannot be isolated: it includes the whole turn.

**Prompts más caros** (most expensive prompts). The 15 most expensive turns, with the agent and model that
cost most. Subagents count separately, in their own session.

**Detalle por modelo** (detail per model). One row per provider and model, from highest to lowest cost, with
totals in the footer.

### Actividad diaria por modelo (daily activity per model)

**Coste por día y modelo** (cost per day and model). Bars stacked per day with the eight most expensive models
(«Otros», others, adds up the rest). Only days with activity appear. It shows when a new model came in and how
much it weighs.

**Actividad por día y modelo** (activity per day and model). Table with messages, tokens and cost of each model
each day. Each column's filter finds a model or a day.

### Mejoras in OpenCode (improvements)

As in Claude Code, with OpenCode's report (rules D1–D11 in the [OpenCode guide](opencode.md)): **Mejoras
detectadas**, **Impacto estimado**, **Errores evitables de herramientas** (without permission blocks,
rejections or interruptions), **Compactaciones e interrupciones**, **Hallazgos**, **Hallazgos por regla** and
**Errores evitables por herramienta y modelo**. In OpenCode the rule that usually pays off goes in
`AGENTS.md`. In addition:

**Coste por mensaje de cada agente, por semana** (cost per message of each agent, per week). One line per agent
with its average cost per message, last 13 weeks. It shows whether changing an agent's model makes it cheaper.

**Errores evitables por herramienta, por semana** (avoidable errors per tool, per week). Weekly error rate of
the five tools that fail most.

**Compactaciones e interrupciones, por semana** (compactions and interruptions, per week). Two lines, last 13
weeks. If they rise, sessions are running too long or answers are not going where you want.

## Common questions when looking at the dashboards

| Question | Where to look |
| --- | --- |
| How much have I spent this month, in total? | Resumen IA → Coste total, with the «This month» range |
| Which tool or project costs the most? | Resumen IA → Coste por herramienta · Coste por proyecto |
| Which model is expensive for me? | Cuota de coste y de tokens por modelo (in each tool) |
| Is it worth lowering the effort? | Claude Code → Coste por effort · Coste por mensaje de cada modelo, por semana |
| Which request was the most expensive? | Prompts más caros |
| Why does the context fill up? | Herramientas · Bytes devueltos al contexto · Contexto de las sesiones |
| Am I going to run out of quota? | OpenCode → Cuota y uso por proveedor |
| Did the rule I added work? | Errores evitables por herramienta, por semana |
| Why is a cost 0 or missing? | Modelos sin precio → prices page |
