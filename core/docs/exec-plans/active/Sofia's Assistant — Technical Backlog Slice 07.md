# Sofia's Assistant — Backlog Técnico Slice 07

**Nome operacional:** Proactivity & Product Interface  
**Escopo:** SA-B021 → SA-B023 + SA-B031  
**Gates-alvo:** I7 — Sofia Pode Reagir; I11 — Interface de Produto  
**Status:** COMPLETED — REMOTE VERIFIED
**Projeto:** Sofia's Assistant  
**Baseline de implementação:** `e572f1db229ec5ed18414afd81b8d161e34031f5`
**Último Slice concluído:** Slice 06 — Computer Capabilities & Real Agent — CONCLUÍDO / VERIFICADO REMOTAMENTE  
**Slice 05:** adiado até disponibilidade do Sofias Memory v0.7.0  
**Estratégia de execução:** autonomia por Gate, checkpoints retomáveis, reference harvest dirigido e integração vertical  
**Fonte:** Technical Backlog Map + ADRs aceitos + Architecture Review Amendments + Slices 01–04 e 06 concluídos

---

# 1. Objetivo

O Slice 07 transforma Sofia de um runtime reativo, capaz de conversar e executar ações quando solicitado, em um sistema capaz de:

```text
perceber eventos
↓
reagir fora de uma Conversation ativa
↓
agendar trabalho futuro
↓
retomar trabalho na hora correta
↓
notificar o usuário
↓
expor essas capacidades através de uma interface real de produto
```

Os resultados de produto esperados são:

```text
Gate I7 — Sofia Can React

Gate I11 — Product Interface
```

Ao final do Slice, Sofia deverá possuir:

```text
Core
├── Conversation
├── Voice
├── Policy
├── Tools
├── Tasks
├── Agents
├── Events
├── Scheduler
├── Notifications
└── Client Interface real
```

O objetivo não é criar uma UI sofisticada.

O objetivo é provar que o runtime já construído pode operar como produto utilizável sem mover domain logic para o Desktop Client.

---

# 2. Antecipação em relação ao Slice 05

A ordem original previa:

```text
Slice 05 — Sofia Remembers
Slice 06 — Computer Capabilities & Real Agent
Slice 07 — Proactivity & Product Interface
```

A ordem prática atual é:

```text
Slice 04
↓
Slice 06
↓
Slice 07
↓
Slice 05 quando Sofias Memory v0.7.0 estiver pronto
```

Isso não altera:

- numeração dos Slices;
- dependency graph;
- ADRs;
- ownership arquitetural;
- definição de MVP;
- Gate I6;
- requisitos do Sofias Memory.

Slice 07 não pode criar dependência artificial de Cognitive Memory.

---

# 3. Por que o Slice 07 está desbloqueado

Dependências:

```text
SA-B021 Event Runtime
    ← SA-B002 Core Lifecycle
    ← SA-B003 Operational Persistence

SA-B022 Scheduler & Reminders
    ← SA-B003 Operational Persistence
    ← SA-B015 Task Runtime
    ← SA-B021 Event Runtime

SA-B023 Notification & Attention
    ← SA-B021 Event Runtime

SA-B031 Desktop Client
    ← SA-B004 Local Client Boundary
    ← SA-B008 Conversation Runtime
    ← SA-B009 Realtime Voice
    ← SA-B023 Notification & Attention
    ← SA-B030 Audit & Traceability
```

Tudo já está pronto exceto:

```text
SA-B021
SA-B022
SA-B023
```

Portanto:

```text
Gate I7
↓
desbloqueia
↓
Gate I11
```

Nenhuma dessas dependências exige Sofias Memory.

---

# 4. Organização por Gate

```text
Slice 07
│
├── Gate I7 — Sofia Pode Reagir
│     ├── SA-B021 Event Runtime
│     ├── SA-B022 Scheduler & Reminders
│     └── SA-B023 Notification & Attention
│
└── Gate I11 — Interface de Produto
      └── SA-B031 Desktop Client
```

I7 deve fechar antes de I11.

O Desktop Client não será construído enquanto Notification & Attention ainda estiverem instáveis.

---

# 5. Modelo de execução

A unidade de execução é o Gate.

Fluxo esperado:

```text
objective
↓
reference harvest
↓
gap analysis
↓
implementation
↓
targeted tests
↓
vertical Gate tests
↓
full regression
↓
quality gates
↓
commit
↓
push
↓
remote CI
↓
Gate closure
```

Checkpoints internos podem ser usados, mas não fecham Gate.

---

# 6. Resume Capsule

Se o trabalho for interrompido:

```text
GATE:
STATUS:
CURRENT CHECKPOINT:

COMPLETED:
- ...

REMAINING:
- ...

FROZEN DECISIONS:
- ...

KNOWN FINDINGS:
- ...

DEFERRED:
- ...

REAL BLOCKERS:
- ...

CURRENT HEAD:
- ...

NEXT ACTION:
- ...
```

A retomada deve começar pelo Resume Capsule e não por releitura integral da arquitetura.

---

# 7. Fontes arquiteturais principais

O Slice é principalmente governado por decisões já aprovadas sobre:

- Core lifecycle;
- persistence;
- Local Client Boundary;
- Task lifecycle;
- authorization;
- execution;
- Agent runtime;
- Audit;
- background execution;
- client/Core separation.

As seguintes regras permanecem congeladas:

```text
Core != Desktop Client

Client != authority

Event != Task

Event != Audit

Event Runtime != Event Sourcing

Schedule != in-memory timer

Notification != domain decision

UI != domain owner
```

---

# 8. Invariantes do Slice

## 8.1 Core continua independente do Desktop Client

O Core deve continuar funcionando sem UI.

Pode executar:

```text
Task
Schedule
Event
Notification production
```

sem Desktop Client conectado.

## 8.2 Event Runtime não é Event Sourcing

Events representam fatos/sinais do runtime.

Não transformar toda mudança de estado do sistema em event sourcing.

Operational Store permanece authoritative para estado operacional.

## 8.3 Event não substitui Task

Event pode causar:

```text
Task creation
Task wakeup
Notification
```

mas não vira unidade durável de trabalho.

## 8.4 Event não substitui Audit

Audit responde:

```text
"por que isso aconteceu?"
```

Event Runtime responde:

```text
"algo aconteceu"
```

São responsabilidades distintas.

## 8.5 Scheduler usa durable truth

Timers em memória são apenas mecanismo de wakeup.

A verdade de scheduling precisa estar persistida.

## 8.6 Restart-safe

Após restart, Scheduler deve reconstruir estado a partir do Operational Store.

## 8.7 Machine clock não é lifecycle

Mudança de horário, sleep/resume e restart devem ser considerados.

## 8.8 Timezone explícita

Schedule nunca deve depender silenciosamente do timezone local do processo.

## 8.9 Notification é boundary

Produzir Notification não significa mostrar toast diretamente.

Core produz intenção/evento normalizado.

Clients decidem como renderizar.

## 8.10 Client não consulta SQLite

Desktop Client fala exclusivamente através do Local Client Boundary autenticado.

## 8.11 Client não executa domain service diretamente

UI não importa repositories/services internos.

## 8.12 Memory permanece ausente

Não criar:

```text
Fake Cognitive Memory
temporary profile persistence
event-backed memory
notification-backed memory
```

para compensar Slice 05.

---

# 9. Gate I7 — Sofia Pode Reagir

**Escopo:** SA-B021, SA-B022, SA-B023  
**Status inicial:** READY

---

# 10. Objetivo do Gate I7

Provar que Sofia consegue reagir a eventos e executar comportamento futuro mesmo sem Conversation ativa.

Fluxo principal:

```text
durable trigger
↓
Event Runtime
↓
routing/subscription
↓
Scheduler or Task action
↓
Notification
↓
client may receive later/currently
```

O Gate precisa funcionar mesmo se:

```text
conversation = none
desktop client = disconnected
```

---

# 11. SA-B021 — Event Runtime

## 11.1 Event model

Criar modelo explícito de Event.

Campos conceituais:

```text
Event
├── id
├── type
├── source
├── occurred_at
├── correlation_id
├── causation_id
├── payload
├── durability
└── metadata
```

Identidade de Event deve ser Core-owned.

## 11.2 Event classes

Baseline conceitual:

```text
DomainEvent
ExternalEvent
```

ou representação equivalente.

Não criar hierarchy excessiva se um único contrato discriminado resolver.

## 11.3 Ephemeral vs Durable

Event Runtime deve distinguir:

```text
EPHEMERAL
DURABLE
```

ou semântica equivalente.

### Ephemeral

Adequado para:

```text
UI state update
transient runtime signal
local observation
```

### Durable

Adequado quando perder o evento comprometer correctness.

Exemplos:

```text
ReminderDue
durable Task wakeup
important external event
```

Não tornar tudo durable automaticamente.

## 11.4 Event Bus

Core possuirá Event Bus explícito.

Responsabilidades:

- publish;
- subscription;
- routing;
- handler dispatch;
- correlation propagation;
- failure isolation;
- shutdown behavior.

## 11.5 Event handlers

Handler não ganha authority por receber Event.

Quando Event resultar em ação protegida:

```text
Event
↓
orchestration
↓
Task / Tool
↓
Policy
```

Nunca:

```text
Event
↓
direct side effect bypassando runtime
```

## 11.6 EventSource

Criar boundary para produtores externos.

Conceitualmente:

```text
EventSource
FakeEventSource
```

Future sources poderão incluir:

```text
filesystem watcher
email
calendar
webhook
OS events
```

Mas não entram neste Gate salvo fake/testing.

## 11.7 Delivery semantics

Baseline deve declarar claramente:

```text
at-most-once?
at-least-once?
deduplicated durable delivery?
```

Não deixar semântica implícita.

Para durable runtime interno, preferir design que permita detectar/reconciliar duplicidade.

Exactly-once global não é requisito.

## 11.8 Handler failure

Falha de um subscriber não deve corromper Event Runtime.

Definir comportamento explícito:

```text
retry?
dead-letter?
log/audit?
mark failed?
```

Sem criar infraestrutura distribuída prematura.

## 11.9 Correlation

Preservar:

```text
correlation_id
causation_id
```

quando Event nascer de:

```text
Task
ToolCall
Schedule
AgentRun
```

## 11.10 Critérios B021

```text
[ ] Event possui identidade estável
[ ] Event Bus existe como Core service
[ ] publish/subscribe funciona
[ ] durable/ephemeral distinction existe
[ ] FakeEventSource existe
[ ] correlation é preservada
[ ] subscriber failure é isolado
[ ] Event não concede authority
[ ] Event não substitui Audit
[ ] Event Runtime não virou Event Sourcing
```

---

# 12. SA-B022 — Scheduler & Reminders

## 12.1 Scheduler

Criar Scheduler como Core service independente de Conversation.

Responsabilidades:

```text
schedule persistence
next-due computation
wakeup
missed-run handling
event emission
Task wakeup
restart recovery
```

## 12.2 Schedule model

Campos conceituais:

```text
Schedule
├── id
├── kind
├── due_at
├── timezone
├── recurrence
├── status
├── payload/reference
├── next_run_at
├── last_run_at
├── created_at
└── metadata
```

Schema final é decisão de implementação.

## 12.3 One-shot

Obrigatório.

Exemplo:

```text
"me lembre amanhã às 10h"
```

## 12.4 Recurring baseline

Obrigatório em forma simples.

Suportar padrão claramente definido, sem construir calendar engine universal.

Exemplos suficientes:

```text
daily
weekly
interval
```

ou representação equivalente.

Não implementar RRULE completo salvo necessidade concreta.

## 12.5 Timezone

Schedule deve armazenar timezone explícito quando semântica depender de horário humano.

UTC continua usado para timestamps internos.

Exemplo:

```text
user intent:
09:00 America/Sao_Paulo

runtime:
resolved next UTC instant
```

## 12.6 DST

Mesmo sendo menos frequente no contexto atual do usuário, semântica deve ser correta.

Não assumir offset fixo como timezone.

## 12.7 Reminder

Criar Reminder como conceito separado de Schedule quando útil.

```text
Reminder = user-facing intent
Schedule = execution timing
```

Não obrigatoriamente uma tabela para cada conceito se domínio puder ser modelado de forma limpa.

## 12.8 ReminderDue

Quando due:

```text
Schedule
↓
ReminderDue Event
↓
Notification boundary
```

Não enviar notification diretamente do timer callback.

## 12.9 WAITING_SCHEDULE

Task Runtime já possui:

```text
WAITING_SCHEDULE
```

Scheduler deve conseguir acordar Task corretamente.

Fluxo:

```text
Task WAITING_SCHEDULE
↓
Schedule due
↓
Event
↓
claim/resume
↓
Task RUNNING
```

## 12.10 Restart

Obrigatório provar:

```text
create schedule
↓
persist
↓
Core shutdown
↓
Core restart
↓
schedule recovered
↓
event still occurs
```

## 12.11 Machine reboot

Não precisa automatizar reboot real no CI.

Mas arquitetura deve usar persistence suficiente para sobreviver a ele.

## 12.12 Missed runs

Definir policy explícita.

Baseline sugerido:

### One-shot

Se Core voltar depois do horário:

```text
emit once as missed/due
```

### Recurring

Escolher comportamento explícito, como:

```text
skip missed intervals
run once
resume next valid occurrence
```

Não executar centenas de ocorrências acumuladas por padrão.

## 12.13 Clock jumps

Scheduler deve recalcular contra wall clock persistido/next due.

Não depender somente de:

```text
sleep(N seconds)
```

como verdade de scheduling.

## 12.14 Cancellation

Schedule cancelado não deve disparar posteriormente.

## 12.15 Duplicate wakeup

Restart/race não deve disparar a mesma one-shot de forma silenciosamente duplicada.

Full recovery fica para Gate I12, mas baseline deve não inviabilizar idempotência futura.

## 12.16 Critérios B022

```text
[ ] one-shot persistence funciona
[ ] recurring baseline funciona
[ ] timezone é explícita
[ ] next_run_at é determinístico
[ ] ReminderDue é Event
[ ] WAITING_SCHEDULE Task pode ser retomada
[ ] Core restart recupera schedules
[ ] missed-run policy é explícita
[ ] cancel funciona
[ ] timer em memória não é source of truth
[ ] race/restart semantics não impedem future recovery
```

---

# 13. SA-B023 — Notification & Attention

## 13.1 Notification boundary

Criar representação Core-owned de Notification.

Conceitualmente:

```text
Notification
├── id
├── type
├── severity
├── title
├── body/summary
├── source
├── created_at
├── correlation_id
├── action_reference
├── delivery_state
└── metadata
```

## 13.2 MVP notification types

Obrigatórios:

```text
TaskCompleted
ReminderDue
PermissionRequested
SubsystemDegraded
```

Nomes concretos podem variar.

## 13.3 Notification service

Responsabilidades:

```text
normalize
persist when required
publish to connected clients
retain pending items when appropriate
track delivery/ack baseline
```

Não renderizar UI.

## 13.4 Connected client

Quando client está conectado:

```text
Notification
↓
Local Client Boundary
↓
event/stream
↓
Desktop Client
```

## 13.5 Disconnected client

Notification importante não deve desaparecer apenas porque nenhum client estava conectado.

Persistir notification pendente quando semântica exigir.

Ao reconectar:

```text
client
↓
query/sync pending notifications
```

## 13.6 Permission request

ConfirmationRequest existente pode produzir Notification.

Mas Notification:

```text
does not approve
does not create Grant
```

UI ainda precisa chamar o boundary de confirmação existente.

## 13.7 Task completion

Task Runtime deve produzir Notification via Event/Notification pipeline.

Não acoplar Task Runtime ao Desktop Client.

## 13.8 Subsystem degraded

Health subsystem pode gerar Notification quando estado relevante mudar.

Evitar spam contínuo.

Mudança de estado deve ser distinguida de polling repetido do mesmo estado.

## 13.9 Attention Policy

Não implementar ainda:

```text
IGNORE
REMEMBER
NOTIFY
PLAN
ACT
```

como sistema genérico.

Somente criar seam se necessário.

## 13.10 Critérios B023

```text
[ ] Notification é Core-owned
[ ] Task completion pode gerar notification
[ ] ReminderDue gera notification
[ ] ConfirmationRequest pode gerar notification
[ ] degraded subsystem pode gerar notification
[ ] notification pode chegar via Local Client Boundary
[ ] client desconectado não perde notification importante
[ ] notification não concede authority
[ ] notification não executa action diretamente
[ ] nenhuma Attention Policy genérica prematura
```

---

# 14. Gate I7 — Cenários verticais

## Cenário A — Reminder one-shot

```text
authenticated request
↓
create Reminder
↓
persist Schedule
↓
Scheduler observes due time
↓
ReminderDue Event
↓
Notification
```

## Cenário B — Restart survival

```text
create Reminder
↓
persist
↓
Core shutdown
↓
new Core process
↓
Scheduler loads schedule
↓
due event
↓
notification
```

## Cenário C — Missed one-shot

```text
schedule due while Core offline
↓
Core starts later
↓
missed-run policy
↓
single ReminderDue
↓
Notification
```

## Cenário D — Recurring reminder

```text
recurring schedule
↓
run
↓
next_run_at advances
↓
no uncontrolled catch-up storm
```

## Cenário E — WAITING_SCHEDULE Task

```text
Task RUNNING
↓
wait-until requested
↓
Task WAITING_SCHEDULE
↓
persist schedule
↓
due Event
↓
Task resumed
↓
Task progresses
```

## Cenário F — Client disconnected

```text
ReminderDue
↓
Notification produced
↓
no client connected
↓
notification retained
↓
client reconnects
↓
notification visible
```

## Cenário G — Permission attention

```text
ToolCall
↓
REQUIRE_CONFIRMATION
↓
ConfirmationRequest
↓
Notification
↓
Client
↓
user approves
↓
existing confirmation flow
```

Notification itself never creates Grant.

---

# 15. Critérios de fechamento do Gate I7

```text
[ ] SA-B021 DONE
[ ] SA-B022 DONE
[ ] SA-B023 DONE

[ ] Event Runtime funcional
[ ] events possuem identity/correlation
[ ] durable/ephemeral semantics existem
[ ] Scheduler usa durable state
[ ] one-shot funciona
[ ] recurring baseline funciona
[ ] timezone explícita
[ ] missed-run semantics testadas
[ ] restart recovery testado
[ ] WAITING_SCHEDULE Task wakeup funciona
[ ] Notification boundary existe
[ ] TaskCompleted notification funciona
[ ] ReminderDue notification funciona
[ ] Permission notification funciona
[ ] degraded subsystem notification funciona
[ ] client disconnected scenario funciona
[ ] Event não bypassa Policy
[ ] Event não substitui Audit
[ ] regression completa verde
[ ] ruff verde
[ ] formatting verde
[ ] mypy verde
[ ] diff-check verde
[ ] GitHub CI verde
```

Veredito:

```text
GATE I7 — CLOSED — REMOTE VERIFIED
```

---

# 16. Gate I11 — Interface de Produto

**Escopo:** SA-B031  
**Depende de:** Gate I7 fechado  
**Status inicial:** BLOCKED BY I7

---

# 17. Objetivo do Gate I11

Criar a primeira experiência de produto real da Sofia.

O Desktop Client deve expor o runtime já existente.

Não deve reconstruir o runtime dentro da UI.

Fluxo:

```text
Desktop Client
↓
authenticated Local Client Boundary
↓
Sofia Core
↓
domain/runtime
```

Nunca:

```text
Desktop Client
↓
SQLite / repositories / provider directly
```

---

# 18. Checkpoint obrigatório — Technology Selection

Antes de implementar SA-B031, realizar checkpoint curto de seleção tecnológica.

O agente deve comparar opções plausíveis para:

```text
Windows-first
desktop tray
native notifications
microphone/audio integration
WebSocket/local HTTP
packaging
auto-start future
low runtime footprint
secure local credential handling
```

Candidatos podem incluir, por exemplo:

```text
Tauri
Electron
PySide / Qt
ou outra opção tecnicamente adequada
```

A lista não é vinculante.

## 18.1 Critérios da escolha

Avaliar:

```text
Windows integration
tray support
native notifications
audio/realtime feasibility
security model
bundle size/runtime footprint
development complexity
Python Core interoperability
local authenticated API support
maintainability
testability
licensing
```

## 18.2 Resultado

Produzir:

```text
Technology Decision Record
```

ou ADR se a decisão for arquiteturalmente durável.

Não começar UI antes da escolha estar registrada.

## 18.3 Não escolher por moda

A escolha deve maximizar adequação ao Sofia's Assistant.

Não adotar stack apenas por popularidade.

---

# 19. Desktop Client — MVP UI

Superfície mínima:

```text
tray
text chat
voice state
realtime voice controls
confirmation UI
Task status
notifications
subsystem health
basic settings
```

Não é necessário dashboard sofisticado.

---

# 20. Client architecture

Preferir separação conceitual:

```text
UI
↓
Client Application Services
↓
Local Core API Client
↓
Authenticated Client Session
↓
Core
```

UI components não devem conhecer endpoints arbitrariamente.

---

# 21. Authentication

Desktop Client deve utilizar exatamente o Local Client Boundary existente.

Não adicionar trust implícito porque client roda na mesma máquina.

Preserve:

```text
localhost != trusted
```

Credential/token local deve ser tratado de forma segura.

---

# 22. Reconnect

Client deve tolerar Core temporariamente indisponível.

Estados conceituais:

```text
CONNECTING
CONNECTED
DEGRADED
DISCONNECTED
```

Reconexão deve restaurar:

```text
health
pending notifications
Task state
conversation availability
```

sem criar duplicação de ação.

---

# 23. Text Chat

UI deve permitir:

```text
create/open Conversation
send Turn
receive response/stream
show errors
```

Conversation continua pertencendo ao Core.

Client pode manter UI state local, mas não vira owner da Conversation.

---

# 24. Realtime Voice

Expor:

```text
voice idle
connecting
listening
responding
interrupted
error
```

Controles mínimos:

```text
start
stop
interrupt
```

Não implementar wake word neste Slice.

---

# 25. Confirmation UI

Quando Notification/confirmation chegar:

UI deve mostrar de forma clara:

```text
ação
resource
risk/context seguro
requested authority
lifetime quando aplicável
```

Ações:

```text
approve
deny
```

UI chama boundary existente.

Não cria Grant localmente.

---

# 26. Task status

Expor Tasks relevantes:

```text
QUEUED
RUNNING
WAITING_CONFIRMATION
WAITING_EXTERNAL
WAITING_SCHEDULE
PAUSED
CANCELLING
SUCCEEDED
FAILED
CANCELLED
```

Não precisa ser task manager avançado.

Baseline:

```text
list recent/active
open details
cancel when permitted
observe result
```

---

# 27. Notifications UI

Suportar:

```text
in-app notification
system/native notification when appropriate
notification list
unread/pending state
```

Renderização concreta depende da technology choice.

Notification Core identity deve ser preservada.

---

# 28. Tray

Tray é parte do MVP.

Operações mínimas:

```text
open Sofia
show status
start/open chat
quit client
```

Quitting Desktop Client não necessariamente encerra Core.

Isso depende do lifecycle já definido.

Preserve Core background independence.

---

# 29. Core status

Expor health resumido:

```text
Core
AI provider
Realtime
Scheduler
Memory
```

Memory poderá aparecer:

```text
unavailable / not configured / incompatible
```

sem impedir Client de operar.

Não esconder degraded state.

---

# 30. Basic settings

Somente settings já suportadas pelo Core/configuration.

Não construir novo settings subsystem dentro do client.

Possíveis exemplos:

```text
provider/model preference
voice configuration
notification preference
startup/client preference
```

somente se backend existir.

---

# 31. UI state vs domain state

UI-local:

```text
window size
selected tab
draft text
visual preference
```

Core/domain:

```text
Conversation
Task
Notification
Confirmation
Grant
Schedule
Health
```

Não duplicar authoritative domain state no client.

---

# 32. Security boundaries do Desktop Client

## 32.1 No direct filesystem privileges

UI não ganha filesystem access apenas porque Tauri/Electron/etc. permitir.

Filesystem operations continuam Tools do Core.

## 32.2 No direct shell

Client nunca executa shell para implementar feature de produto.

## 32.3 No secret exposure

Secret values não devem chegar ao renderer/frontend salvo necessidade estritamente aprovada.

## 32.4 HTML/web content

Se stack web-based for escolhida:

- CSP;
- no arbitrary remote content execution;
- no unsafe IPC bridge;
- no privileged renderer.

Devem fazer parte do security baseline.

## 32.5 Local API

Não expor API para interfaces não autenticadas por conveniência da UI.

---

# 33. Gate I11 — Cenários verticais

## Cenário A — Text conversation

```text
Desktop Client
↓
authenticate
↓
send Turn
↓
Core Conversation Runtime
↓
response
↓
render
```

## Cenário B — Voice

```text
user starts voice
↓
client audio
↓
Realtime boundary
↓
Core/provider
↓
audio/transcript state
↓
client renders
```

## Cenário C — Confirmation

```text
Core needs confirmation
↓
Notification
↓
Desktop Client
↓
confirmation UI
↓
approve
↓
Local Client API
↓
Core creates/uses Grant
↓
execution continues
```

## Cenário D — Reminder while UI disconnected

```text
Client closed
↓
ReminderDue occurs
↓
Notification persisted
↓
Client opens later
↓
auth/reconnect
↓
pending notification shown
```

## Cenário E — Task status

```text
Task starts
↓
client sees RUNNING
↓
Task waits/succeeds/fails
↓
client receives/refreshes state
```

## Cenário F — Core degraded

```text
Memory unavailable
↓
Core otherwise ready
↓
Desktop Client displays degraded Memory
↓
chat remains usable
```

---

# 34. Critérios de fechamento do Gate I11

```text
[ ] technology choice registrada
[ ] Desktop Client inicia no Windows
[ ] tray funciona
[ ] autenticação com Local Client Boundary funciona
[ ] reconnect funciona
[ ] text chat funciona
[ ] streaming/responses funcionam
[ ] realtime voice controls funcionam
[ ] confirmation UI funciona
[ ] Task status funciona
[ ] notifications funcionam
[ ] pending notification sync funciona
[ ] subsystem health funciona
[ ] basic settings baseline funciona
[ ] Core funciona sem Client
[ ] Client não acessa SQLite
[ ] Client não bypassa Policy
[ ] Client não executa Tools diretamente
[ ] no raw secrets in frontend
[ ] regression Core verde
[ ] client tests verdes
[ ] packaging/build baseline funciona
[ ] CI remoto verde
```

Veredito:

```text
GATE I11 — CLOSED — REMOTE VERIFIED
```

---

# 35. Persistence

Gate I7 pode exigir migrations para:

```text
events durable state
schedules
reminders
notifications
```

O schema deve ser mínimo.

Evitar tabelas redundantes se conceitos puderem compartilhar estrutura sem perder semântica.

Regras:

- UUIDs estáveis;
- UTC timestamps;
- timezone explícita onde necessária;
- state transitions validadas;
- correlation preservada;
- sem secrets;
- sem blobs arbitrários;
- migrations incrementais.

Desktop Client não deve criar seu próprio banco de domínio.

Pode possuir storage UI-local se necessário, claramente separado do Operational Store.

---

# 36. Concurrency

Especial atenção para:

```text
schedule due race
Core shutdown during dispatch
duplicate wakeup
client reconnect
notification delivery race
Task wakeup race
```

Usar sincronização determinística nos testes.

Evitar correctness baseada em `sleep()`.

---

# 37. Test strategy — Gate I7

## Unit

Cobrir:

```text
event identity
subscription routing
durability classification
next-run calculation
timezone calculation
recurrence
missed-run policy
notification normalization
state transitions
```

## Integration

Cobrir:

```text
durable Event persistence
Scheduler persistence
Core restart
ReminderDue
WAITING_SCHEDULE resume
notification persistence
client-boundary notification delivery
```

## Time testing

Injetar Clock/TimeProvider ou seam equivalente.

Não alterar clock real do sistema.

Testes não devem esperar minutos reais.

---

# 38. Test strategy — Gate I11

## Unit

Cobrir:

```text
client state machine
API mapping
notification state
confirmation view models
Task view models
health presentation
```

## Integration

Cobrir:

```text
real Local Client Boundary
auth
reconnect
Conversation
Task
Confirmation
Notifications
Health
```

## UI

Preferir testes de componentes/flows determinísticos.

End-to-end real apenas para cenários críticos.

Não exigir serviços cloud reais.

---

# 39. Reference harvest — Gate I7

Antes da implementação avaliar patterns em:

```text
Python asyncio scheduling
persistent scheduler patterns
APScheduler concepts if useful
event bus designs
Windows sleep/resume behavior
Mark LI
Brahma AI
current Sofia codebase
```

Referências não são authority arquitetural.

Evitar incorporar scheduler/framework inteiro se uma implementação menor cumprir o Gate.

---

# 40. Reference harvest — Gate I11

Avaliar:

```text
Tauri
Electron
PySide/Qt
Windows tray APIs
native notification APIs
audio support
secure local IPC patterns
```

Registrar comparação.

Decisão tecnológica deve ser explícita.

---

# 41. Não objetivos

Não implementar neste Slice:

```text
Sofias Memory integration
Cognitive Memory
Memory Orchestrator

wake word
continuous microphone listening
continuous screenshot
webcam

full Attention Policy
autonomous event-driven actions
"ACT" from arbitrary external event

full calendar product
cron-compatible universal scheduler
distributed queue
multi-machine scheduler

browser automation

plugin marketplace

full Recovery Hardening
Gate I12

MVP final Gate I13
```

---

# 42. Segurança — Eventos e Proatividade

Especial cuidado:

```text
external event != trusted input
event != authority
schedule != authority
notification != authority
client click != implicit unrestricted grant
```

Qualquer evento que queira causar ação protegida passa por Policy.

---

# 43. Brief de execução — Gate I7

> **Concluir Gate I7 — Sofia Pode Reagir.**
>
> Materialize SA-B021–SA-B023 ponta a ponta sob o Technical Backlog Slice 07.
>
> Implemente Event Runtime, Scheduler/Reminders e Notification/Attention baseline.
>
> Preserve Operational Store como authoritative state; não transforme Event Runtime em Event Sourcing.
>
> Event não concede authority e nenhuma ação protegida pode bypassar Policy.
>
> Scheduler deve usar persistence durável, timezone explícita, restart recovery e missed-run policy.
>
> Prove one-shot, recurring baseline, ReminderDue, WAITING_SCHEDULE wakeup e restart.
>
> Notification deve ser Core-owned, independente de UI, suportar client conectado/desconectado e integrar Task completion, ReminderDue, confirmation e degraded subsystem.
>
> Use Clock/TimeProvider ou seam equivalente para testes determinísticos.
>
> Faça reference harvest dirigido.
>
> Não peça aprovação de microsteps.
>
> Feche o Gate somente com regressão completa, quality gates e CI remoto verde.
>
> Não inicie Gate I11 nesta mesma execução.

---

# 44. Brief de execução — Gate I11

Depois de I7:

> **Concluir Gate I11 — Interface de Produto.**
>
> Antes de implementar, execute checkpoint formal de technology selection para o Desktop Client Windows-first.
>
> Compare stacks plausíveis considerando tray, notifications, realtime voice, segurança, bundle/runtime footprint, integração com o Local Client Boundary, testabilidade e manutenção.
>
> Registre a decisão antes de iniciar código de produto.
>
> Implemente SA-B031 sem mover domain logic para UI.
>
> O Client deve usar exclusivamente o authenticated Local Client Boundary.
>
> Entregue MVP UI com tray, text chat, realtime voice controls, confirmation UI, Task status, notifications, health e settings baseline.
>
> Preserve Core background independence.
>
> Client nunca acessa SQLite, Tools, Policy, providers ou repositories diretamente.
>
> Faça smoke real Windows quando necessário, além de testes determinísticos.
>
> Feche Gate somente após build/packaging baseline e CI remoto.
>
> Não iniciar Gate I12, Slice 05 ou novo Slice nesta mesma execução.

---

# 45. Definition of Done — Slice 07

O Slice termina quando:

```text
Gate I7 — CLOSED — REMOTE VERIFIED
Gate I11 — CLOSED — REMOTE VERIFIED
```

e:

```text
Events funcionam
Scheduler é durável
Reminders sobrevivem restart
Notifications existem sem UI
Desktop Client consome Core
Text funciona
Voice funciona
Confirmations funcionam
Tasks são observáveis
Health é visível
```

Sem violar:

```text
Core != UI
Event != authority
Schedule != authority
Notification != authority
Client != authority
Operational Store remains authoritative
Policy remains deterministic
Audit remains separate
```

Veredito:

```text
SLICE 07 — PROACTIVITY & PRODUCT INTERFACE
CONCLUÍDO — VERIFICADO REMOTAMENTE
```

---

# 46. Direção pós-Slice

Se Sofias Memory v0.7.0 estiver pronto:

```text
Slice 05
↓
Gate I6 — Sofia Remembers
```

Se ainda não estiver:

```text
Gate I12 — Recovery Validated
↓
SA-B033 Recovery Hardening
```

poderá ser antecipado.

Não iniciar Gate I13 antes de I6.

---

# 47. Execution Ledger

```text
Slice 07 status:
    COMPLETED — REMOTE VERIFIED

Execution order:
    ANTICIPATED BEFORE SLICE 05

Reason:
    Sofias Memory v0.7.0 still in development

Implementation baseline:
    e572f1db229ec5ed18414afd81b8d161e34031f5
    main; clean worktree; aligned with origin/main at I11 preflight

Previous Slice:
    Slice 06 — CLOSED — REMOTE VERIFIED

Current active Gate:
    none — Slice 07 complete

Next Gate:
    I12 — NOT AUTHORIZED in this execution

Gate I7:
    CLOSED — REMOTE VERIFIED

Gate I11:
    CLOSED — REMOTE VERIFIED

Slice 05 / Gate I6:
    DEFERRED — WAITING FOR SOFIAS MEMORY v0.7.0

Potential next Gate if Memory remains unavailable:
    I12 — Recovery Validated (not authorized in this execution)
```

## I7 execution evidence / Resume Capsule

```text
GATE: I7 — Sofia Pode Reagir
STATUS: CLOSED — REMOTE VERIFIED
CURRENT CHECKPOINT: I7-D — vertical integration / closure

COMPLETED:
- I7-A: discriminated Event; explicit ephemeral/durable delivery; source fake;
  bounded dispatch, per-subscriber progress, failure isolation and SA-B030 evidence.
- I7-B: persistent Scheduler; ONCE/INTERVAL/DAILY; Clock; IANA/DST;
  atomic occurrence/outbox/advancement; restart and missed-run coalescing;
  existing TaskRuntime WAITING_SCHEDULE continuation and fresh Policy evaluation.
- I7-C: durable pending/acknowledged Notifications for all four MVP flows;
  authenticated Local Client Boundary query/ack/stream; disconnected recovery;
  significant health transition deduplication; Core lifecycle composition.
- Migration 0008_proactivity: runtime_events, schedules, notifications only.
- Directed reference harvest/gap analysis documented in implementation note.

REMAINING:
- None for Gate I7.
  record verified evidence and only then mark Gate CLOSED — REMOTE VERIFIED.

FROZEN DECISIONS:
- Event/Schedule/Notification/Client != authority; Operational Store authoritative.
- ExecutionRuntime/Policy/TaskRuntime/SA-B030 reused, no parallel execution engine.
- No Memory, I11/Desktop Client, I12 or other Slice started.

KNOWN FINDINGS (corrected):
- WAITING_SCHEDULE lacked a durable continuation/wakeup seam.
- Retry-safe handlers needed per-handler progress; uncertain non-retry-safe
  effects need explicit failure rather than blind replay.
- Restart during RUNNING scheduled Tool requires PAUSED reconciliation.
- Stream subscribe-before-sync and bounded queue overflow preserve durable state.
- Repeated health samples and event replay require stable effect deduplication.
- Migration revision/table expectations and Core health projections updated.

DEFERRED (non-blocking):
- Retention/compaction, terminal-event retry UX, comprehensive I12 recovery,
  distributed coordination, broad calendar/attention policy.

REAL BLOCKERS: none
CURRENT HEAD: e572f1db229ec5ed18414afd81b8d161e34031f5
NEXT ACTION: run final staged quality gates, commit/push I11 and verify CI.
```

Architecture, semantics, API behavior, concurrency decisions and reference comparison:
[Gate I7 implementation note](../../implementation/gate-i7-proactivity.md).

Local verification (2026-09-13):

- Targeted unit/Gate/Core/HTTP/persistence/bootstrap regression: **68 passed**.
- Expanded unit + Gate I7 vertical/adversarial set: **38 passed**.
- Full `uv run pytest -q`: **583 passed, 3 skipped** (existing opt-in OpenAI,
  Realtime and Windows Credential Manager smokes; no Gate correctness skipped).
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: 145 files already formatted.
- `uv run mypy src tests`: no issues in 145 source files.
- `git diff --check`: passed.
- Real local HTTP stream and full Core restart covered by offline integration
  tests; no external service/credentials or interactive desktop required.
- First full regression exposed three stale migration/table expectations;
  corrected before the final green regression. No open blocking findings.

Remote verification: GitHub Actions `CI`, run `34789997097`, completed with
`success` for commit `90f9d9c40767d2c919c1385455bf4625f42ca761`.

Final Gate I7 status: **CLOSED — REMOTE VERIFIED**. Slice 07 remains open because
Gate I11 was completed in the current execution.

## I11 execution evidence / Resume Capsule

```text
GATE: I11 — Interface de Produto / SA-B031
STATUS: CLOSED — REMOTE VERIFIED
CURRENT CHECKPOINT: I11-D — remote verification complete

COMPLETED:
- Technology Selection recorded as TDR-0011; PySide6/Qt Widgets selected over
  Tauri and Electron for the Windows-first Python Core seam.
- Separate Desktop Client package with authenticated CoreApiClient,
  ClientApplicationService, Qt Widgets UI, QSystemTrayIcon and PyInstaller
  Windows executable baseline.
- Chat streaming, reconnect state, realtime voice controls, confirmation
  approve/deny, Task listing/cancel, notification sync/ack/native presentation,
  health projection and supported basic settings.
- No direct SQLite, repository, Policy, Tool, provider or SecretStore access.
- Client-only bounded task-list API extension and deterministic client tests.

REMAINING:
- None for Gate I11 or Slice 07.
- Gate I12, Slice 05 and other Slice work remain outside this execution.

FROZEN DECISIONS:
- Core != Desktop Client; Client != authority; localhost != trusted.
- Local Client Boundary remains the only Core integration boundary.
- Core owns Conversation, Task, Notification, Confirmation, Grant and Health.
- Memory remains unavailable/not configured and is not integrated.

KNOWN FINDINGS (corrected):
- Full pytest exposed a test module basename collision; the new client model
  test was renamed so the entire suite collects deterministically.
- Voice start state update had unreachable code; corrected before final gates.
- Deny confirmation now validates the Core response status/body.

DEFERRED (non-blocking):
- Real microphone capture/provider audio smoke requiring hardware or credentials.
- Code signing, commercial installer UX, auto-start and auto-update.

REAL BLOCKERS: none
CURRENT HEAD: 31a507548f4aed5afc635a71835fe9940554f5f1
NEXT ACTION: stop; do not start Gate I12, Slice 05 or another Slice.
```

Architecture and technology comparison: [TDR-0011](../../decisions/TDR-0011-desktop-client-technology.md).
Implementation details: [Gate I11 implementation note](../../implementation/gate-i11-desktop-client.md).

Local verification (2026-09-13):

- Targeted client unit/integration/UI tests: **12 passed**.
- Full `uv run pytest -q`: **595 passed, 3 skipped** (existing opt-in
  OpenAI, Realtime and Windows Credential Manager smokes; no Gate correctness
  skipped).
- `uv run ruff check src tests`: passed.
- `uv run ruff format --check src tests`: 155 files already formatted.
- `uv run mypy src tests`: no issues in 155 source files.
- `git diff --check`: passed.
- `uv lock --check`: passed.
- PySide6 offscreen startup smoke: passed.
- PyInstaller Windows package baseline: `dist/SofiaAssistant.exe` built.
- Packaged `SofiaAssistant.exe --smoke`: exit code 0.
- Real authenticated Local Client Boundary integration: connect, snapshot,
  Conversation creation and wrong-credential rejection passed offline.

Remote verification: GitHub Actions `CI`, run `34794557233`, completed with
`success` for commit `31a507548f4aed5afc635a71835fe9940554f5f1`.

Final Gate I11 status: **CLOSED — REMOTE VERIFIED**.
Final Slice 07 status: **COMPLETED — REMOTE VERIFIED**.

---

# 48. Frozen decisions

```text
01. Slice numbering does not change.

02. Slice 07 may execute before Slice 05.

03. Slice 07 has no dependency on Sofias Memory.

04. Event Runtime is not Event Sourcing.

05. Operational Store remains authoritative.

06. Event does not grant authority.

07. Event does not replace Task.

08. Event does not replace Audit.

09. Scheduler state is durable.

10. In-memory timer is not scheduling truth.

11. Timezone semantics are explicit.

12. ReminderDue is emitted as Event.

13. WAITING_SCHEDULE is integrated with Scheduler.

14. Notification is Core-owned.

15. Notification is not UI rendering.

16. Important notifications survive client disconnection.

17. Confirmation notification does not create Grant.

18. Full Attention Policy is deferred.

19. Gate I7 closes before Desktop Client implementation.

20. Desktop Client technology requires explicit selection checkpoint.

21. Client uses only authenticated Local Client Boundary.

22. localhost remains untrusted by default.

23. Desktop Client does not access SQLite directly.

24. Desktop Client does not own domain state.

25. Core continues functioning without Desktop Client.

26. Tray is part of MVP Client.

27. Text Chat is part of MVP Client.

28. Realtime Voice controls are part of MVP Client.

29. Confirmation UI is part of MVP Client.

30. Task status is part of MVP Client.

31. Notifications are part of MVP Client.

32. Health is part of MVP Client.

33. Memory degraded/unavailable does not prevent basic Client operation.

34. Gate I12 remains separate.

35. Gate I13 cannot close before Gate I6.
```
