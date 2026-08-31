# Sofia's Assistant — Technical Backlog Slice 01

**Scope:** SA-B001 → SA-B006  
**Target Gate:** I1 — Core Alive  
**Status:** Baseline para implementação  
**Source:** Technical Backlog Map aprovado  
**Architecture baseline:** PRD v0.1 + ADR-0001…ADR-0015 + Architecture Review Amendment 0001

---

# 1. Objective

Este primeiro slice deverá construir o **runtime fundamental do Sofia's Assistant antes da introdução de qualquer LLM**.

Ao final deste slice, Sofia ainda não precisará conversar.

Ela deverá, porém, possuir um Core real capaz de:

```text
start
↓
validate configuration
↓
initialize persistence
↓
initialize secrets
↓
start authenticated local interface
↓
report health/readiness
↓
remain alive independently from a UI
↓
shutdown gracefully
```

Esse é o foundation necessário para todo o restante do produto.

---

# 2. Gate I1 — Core Alive

O Gate I1 somente será considerado concluído quando for demonstrado:

1. Sofia Core inicia independentemente de qualquer Desktop Client;
2. Operational Store é inicializado e migrado;
3. runtime session é registrada;
4. configuração inválida impede startup de forma clara;
5. Secret Service funciona sem plaintext credentials no banco/config comum;
6. Local Client consegue autenticar;
7. Client não autenticado é rejeitado;
8. Core não é exposto à LAN por default;
9. health/readiness podem ser consultados;
10. Core encerra graciosamente;
11. restart preserva estado operacional esperado;
12. suíte automatizada do slice passa.

---

# 3. SA-B001 — Project Foundation

## Goal

Criar uma base de projeto pequena, disciplinada e apropriada para modular monolith.

Não implementar domínio de produto ainda.

---

## 3.1 Repository Baseline

O repositório deverá possuir estrutura equivalente a:

```text
sofias_assistant/
├── pyproject.toml
├── README.md
├── .gitignore
├── .editorconfig
├── .env.example
│
├── src/
│   └── sofias_assistant/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── scripts/
│
└── docs/
    ├── prd/
    ├── adr/
    └── backlog/
```

A estrutura concreta poderá variar ligeiramente desde que preserve os boundaries.

---

## 3.2 Initial Package Structure

Dentro do package principal, iniciar somente os módulos necessários ao primeiro slice:

```text
sofias_assistant/
├── core/
├── config/
├── persistence/
├── client_api/
├── secrets/
├── health/
└── observability/
```

Não criar prematuramente dezenas de módulos vazios como:

```text
agents/
memory/
browser/
calendar/
smart_home/
```

antes de seus backlogs chegarem à implementação.

---

## 3.3 Python Version

Definir uma versão mínima moderna e estável de Python.

A escolha concreta deverá considerar:

- suporte das libraries selecionadas;
- Windows;
- typing;
- async runtime;
- packaging.

A versão deverá ficar pinned como requisito do projeto.

---

## 3.4 Dependency Management

Utilizar `pyproject.toml` como authority de packaging/dependencies.

Separar conceitualmente:

```text
runtime dependencies
development dependencies
test dependencies
```

Evitar múltiplas fontes conflitantes de dependency truth.

---

## 3.5 Quality Tooling

O projeto deverá possuir desde o primeiro commit funcional:

- formatter;
- linter;
- static typing;
- pytest;
- coverage;
- import/order validation quando aplicável.

A escolha concreta das ferramentas pode favorecer o ecossistema já consolidado.

Uma baseline razoável é:

```text
ruff
mypy
pytest
coverage
```

sem transformar tooling em projeto próprio.

---

## 3.6 Type Discipline

Código de domínio e contracts públicos deverão utilizar type hints consistentemente.

Não será exigido typing obsessivo de toda variável local.

O objetivo é garantir contratos claros.

---

## 3.7 Async Baseline

O Core deverá ser compatível com execução assíncrona desde o início, pois posteriormente teremos:

- realtime;
- providers;
- Event Sources;
- Scheduler;
- Tasks;
- clients simultâneos.

Isso não significa tornar toda função `async`.

Usar async somente em boundaries que realmente envolvem concorrência/I/O.

---

## 3.8 Logging Baseline

Criar logging estruturado minimamente consistente.

Deverá suportar pelo menos:

```text
timestamp
level
logger/module
message
runtime_session_id when available
correlation fields when available
```

Não implementar Audit Trail completo aqui.

---

## 3.9 Application Version

Core deverá possuir version identificável.

Exemplo conceitual:

```text
0.1.0-dev
```

Essa versão será útil para:

- Client compatibility;
- migrations;
- plugins futuros;
- diagnostics.

---

## 3.10 Developer Commands

Definir comandos simples para:

```text
run
test
lint
typecheck
format
```

Evitar exigir sequência manual extensa.

---

## 3.11 CI Baseline

CI deverá executar no mínimo:

```text
lint
typecheck
tests
```

Se repository ainda for exclusivamente local durante primeira etapa, a configuração poderá ser preparada para ativação assim que remote estiver disponível.

---

## 3.12 SA-B001 Tests

Validar:

- package import;
- version availability;
- config bootstrap mínimo;
- test runner;
- lint;
- typecheck.

---

## 3.13 Acceptance Criteria

SA-B001 estará concluído quando:

```text
fresh clone
↓
install dependencies
↓
run quality checks
↓
run tests
↓
start minimal application entrypoint
```

funcionar de maneira documentada.

---

# 4. SA-B002 — Core Lifecycle

## Goal

Criar o processo persistente que representa Sofia Core.

---

## 4.1 Core Application

Criar conceito explícito de:

```text
SofiaCore
```

ou nomenclatura equivalente.

Ele deverá controlar lifecycle dos subsystems.

---

## 4.2 Lifecycle Contract

Baseline:

```text
initialize
start
ready
stop
shutdown
```

Não necessariamente como métodos literais com esses nomes, mas com essas fases semânticas.

---

## 4.3 Bootstrap Ordering

Startup inicial deverá respeitar ordem equivalente a:

```text
load configuration
↓
initialize logging
↓
initialize Secret Service
↓
initialize Operational Store
↓
validate migrations/schema
↓
create Runtime Session
↓
initialize Health Registry
↓
initialize Local Client Boundary
↓
mark Core ready
```

---

## 4.4 Core Readiness

`process running` e `Core ready` serão estados diferentes.

Exemplo:

```text
process alive
database migration failed
```

não poderá resultar em readiness positiva.

---

## 4.5 Background Lifetime

Core deverá continuar vivo independentemente da conexão de um Client.

Teste obrigatório:

```text
start Core
connect test client
disconnect client
verify Core still alive
reconnect
```

---

## 4.6 Shutdown Request

Deverá existir mecanismo explícito para shutdown controlado.

Fechar Client não deverá provocar Core shutdown automaticamente.

---

## 4.7 Graceful Shutdown

Shutdown deverá:

1. marcar Core como stopping;
2. impedir início de novas operações relevantes;
3. finalizar client connections;
4. flush/persist estado necessário;
5. encerrar subsystems em ordem reversa segura;
6. registrar runtime session encerrada;
7. liberar Operational Store.

---

## 4.8 Unexpected Shutdown Marker

Se Core terminar sem registrar shutdown correto, próxima inicialização deverá conseguir reconhecer runtime session anterior como interrompida.

Não implementar ainda Task Recovery completo.

Apenas criar foundation necessária.

---

## 4.9 OS Signals

Runtime deverá lidar adequadamente com signals/eventos de encerramento disponíveis na plataforma.

Windows-first deverá ser considerado explicitamente.

---

## 4.10 Multiple Core Instances

O MVP deverá impedir, ou pelo menos detectar claramente, duas instâncias do Sofia Core tentando utilizar o mesmo Operational Store/profile ao mesmo tempo.

Não permitir corrupção silenciosa.

Possíveis mecanismos serão escolhidos na implementação.

---

## 4.11 SA-B002 Tests

### Unit

- lifecycle ordering;
- readiness transitions;
- subsystem failure propagation.

### Integration

- Core startup;
- client disconnect does not terminate Core;
- graceful shutdown;
- interrupted runtime session detection;
- duplicate instance protection.

---

## 4.12 Acceptance Criteria

```text
Core starts
Core reaches READY
Core remains running with no client
Core shuts down gracefully
runtime session records lifecycle correctly
```

---

# 5. SA-B003 — Operational Persistence

## Goal

Criar Operational Store SQLite durável e versionado.

---

## 5.1 SQLite

SQLite será implementação inicial conforme ADR-0002.

Banco deverá residir no application data directory.

Nunca dentro do source tree como default de produção.

---

## 5.2 Application Data Directory

Definir serviço/configuration para resolver:

```text
data/
cache/
logs/
artifacts/
```

sem hardcode arbitrário espalhado pelo projeto.

No Windows, utilizar location apropriada ao perfil do usuário.

A implementação exata será decidida durante o Epic.

---

## 5.3 ORM / Query Layer Decision

Escolher uma camada coerente com:

- async quando necessário;
- migrations;
- typing;
- SQLite;
- queries explícitas;
- transactions.

A decisão é de implementação e não exige novo ADR salvo descoberta de impacto estrutural.

---

## 5.4 Migration Authority

Escolher uma única ferramenta de migrations.

Todo schema change deverá passar por migration versionada.

---

## 5.5 Initial Schema

Neste slice, criar apenas estruturas realmente necessárias.

Baseline:

```text
schema/version metadata

runtime_sessions
application_settings
```

Além de tabelas necessárias para client sessions/secrets metadata se a implementação escolhida exigir.

Não criar antecipadamente schemas completos de:

```text
Tasks
Agents
MemoryCandidates
Tools
```

se ainda não utilizados.

---

## 5.6 Runtime Session

Persistir pelo menos:

```text
id
started_at
stopped_at
status
application_version
```

Estados poderão incluir semanticamente:

```text
RUNNING
STOPPED
INTERRUPTED
```

---

## 5.7 Repository Boundary

Criar repository explícito para RuntimeSession e Settings.

Services não executarão SQL diretamente como caminho normal.

---

## 5.8 Transactions

Criar transaction/Unit of Work boundary mínimo.

Não fazer abstração genérica para múltiplos databases.

---

## 5.9 SQLite Configuration

Avaliar e testar:

```text
foreign_keys = ON
WAL mode
busy timeout
```

quando compatível com a library escolhida.

---

## 5.10 Connection Lifecycle

Connection/session lifecycle deverá ser controlado pela persistence layer.

Evitar conexão global arbitrária usada por todos os módulos.

---

## 5.11 Schema Compatibility

Startup deverá detectar:

```text
schema too old
schema too new
migration failure
```

e não entrar em READY silenciosamente.

---

## 5.12 Migration Tests

Obrigatórios:

```text
empty DB → latest
previous revision → latest
latest → no-op
```

Quando houver mais de uma revision disponível.

---

## 5.13 Persistence Test Isolation

Integration tests usarão banco temporário isolado.

Nunca usar database real do usuário.

---

## 5.14 SA-B003 Acceptance

- DB criado automaticamente;
- migrations funcionam;
- RuntimeSession persiste;
- restart preserva dados;
- schema incompatível impede readiness;
- tests usam database isolado.

---

# 6. SA-B004 — Local Client Boundary

## Goal

Criar o primeiro contrato Core ↔ Client com autenticação local.

---

## 6.1 Technology Decision

Durante este Epic deverá ser escolhida a implementação concreta.

Critérios:

- Windows-first;
- streaming futuro;
- realtime future;
- desktop integration;
- testability;
- local authentication;
- futuro CLI;
- simplicidade.

Candidatos incluem:

```text
HTTP + WebSocket loopback

Named Pipes

Local socket / IPC combination
```

---

## 6.2 Selection Rule

Não escolher tecnologia porque:

> “é a mais sofisticada.”

Escolher a menor solução que permita:

- request/response;
- streaming/event;
- client authentication;
- reconnection;
- future Desktop Client;
- future CLI.

---

## 6.3 Local-only Binding

Se TCP for utilizado:

```text
bind = loopback only
```

Baseline:

```text
127.0.0.1
::1
```

Não:

```text
0.0.0.0
```

por default.

---

## 6.4 Client Authentication

Client deverá provar que pertence a uma session autorizada.

A implementação poderá usar:

- OS identity/ACL;
- ephemeral secret;
- locally protected token;
- handshake.

Nunca confiar apenas em origem localhost.

---

## 6.5 Bootstrap Credential

Se token for utilizado, seu armazenamento/entrega deverá passar pela Secret Service ou mecanismo de proteção equivalente.

Não escrever permanentemente token sensível em `.env`.

---

## 6.6 API Version

Requests deverão possuir contract version ou endpoint versioning suficiente para evitar futuras incompatibilidades silenciosas.

---

## 6.7 Initial Commands

Implementar somente comandos de infraestrutura.

Exemplo:

```text
core.get_info
core.get_health
core.shutdown
```

`core.shutdown` deverá possuir proteção adequada e não necessariamente ser exposto a qualquer client session.

---

## 6.8 Initial Events

Client poderá receber eventos básicos:

```text
core.ready
core.stopping
health.changed
```

ou equivalentes.

---

## 6.9 Request Identity

Cada request deverá possuir correlation/request ID.

Isso prepara observability e Audit.

---

## 6.10 Error Contract

Errors deverão ser estruturados.

Exemplo conceitual:

```text
code
message
details?
request_id
```

Não retornar stack traces crus para clients.

---

## 6.11 Reconnect

Client deverá conseguir reconectar ao Core sem reiniciar o Core.

---

## 6.12 Multiple Clients

A arquitetura deverá permitir mais de um client session futuro, mesmo que o MVP principal use um Desktop Client.

Exemplo futuro:

```text
Desktop
+
CLI
```

Não hardcode singleton de conexão.

---

## 6.13 Authentication Tests

Obrigatórios:

```text
valid client → accepted
missing credential → rejected
invalid credential → rejected
```

Se transporte fornecer OS authentication, testes equivalentes deverão existir.

---

## 6.14 Network Exposure Test

Se usar TCP, teste deverá verificar que Core não escuta em interface externa por default.

---

## 6.15 SA-B004 Acceptance

Um client de teste externo ao processo consegue:

```text
authenticate
↓
get core info
↓
get health
↓
receive event
↓
disconnect
↓
reconnect
```

Processo sem authentication é rejeitado.

---

# 7. SA-B005 — Runtime Health & Configuration

## Goal

Criar uma fonte única e validada para configuração e health.

---

## 7.1 Configuration Model

Configuração deverá ser tipada/validada.

Fontes possíveis:

```text
defaults
configuration file
environment
runtime settings
```

precedência deverá ser explícita.

---

## 7.2 Config vs Secret

Regra:

```text
Configuration contains references.
SecretStore contains secret values.
```

Exemplo correto:

```text
openai_credential_ref = "provider/openai/default"
```

não:

```text
openai_api_key = "sk-..."
```

no banco/config comum.

---

## 7.3 Validation

Config inválida deverá falhar no startup antes de READY.

Mensagens deverão ser acionáveis.

---

## 7.4 Runtime Settings

Settings que possam mudar em runtime poderão futuramente estar no Operational Store.

Neste slice, evitar criar sistema sofisticado de dynamic config.

---

## 7.5 Health Registry

Criar `HealthRegistry` ou equivalente.

Cada subsystem poderá reportar estado.

---

## 7.6 Health States

Baseline:

```text
HEALTHY
DEGRADED
UNAVAILABLE
```

Pode existir:

```text
STARTING
STOPPING
```

no lifecycle global.

---

## 7.7 Core Readiness Aggregation

Readiness global será calculada com base em componentes obrigatórios.

Exemplo:

```text
Persistence unavailable
→ Core NOT READY
```

Enquanto:

```text
optional future provider unavailable
→ Core may remain READY but DEGRADED
```

---

## 7.8 Health Details

Cada subsystem deverá poder fornecer:

```text
status
message
last_changed_at
optional diagnostic code
```

Sem expor secret/internal stack trace ao client.

---

## 7.9 Initial Health Components

Neste slice:

```text
core
persistence
secret_service
client_boundary
```

---

## 7.10 Health Events

Mudança relevante deverá poder produzir evento interno/client event.

Exemplo:

```text
persistence:
  HEALTHY → UNAVAILABLE
```

---

## 7.11 SA-B005 Tests

- invalid config;
- healthy subsystem;
- degraded subsystem;
- readiness calculation;
- health transition event;
- sanitized health response.

---

## 7.12 Acceptance

Client consegue consultar health estruturado e distinguir:

```text
Core alive
Core ready
Core degraded
Core unavailable
```

---

# 8. SA-B006 — Secret Service

## Goal

Criar storage e acesso seguro para secrets do Sofia Core.

---

## 8.1 SecretService Contract

Baseline conceitual:

```text
set_secret(ref, value)
get_secret(ref)
delete_secret(ref)
exists(ref)
list_metadata()
```

Não expor listagem de valores.

---

## 8.2 Secret Reference

Utilizar identificadores estáveis.

Exemplos:

```text
provider/openai/default
provider/gemini/default
integration/github/default
client/bootstrap
```

---

## 8.3 Windows-first Backend

Selecionar backend seguro adequado ao Windows.

Candidatos principais:

```text
Windows Credential Manager

DPAPI-backed local encrypted store
```

A escolha deverá considerar:

- headless Core;
- packaging;
- CLI futura;
- testability;
- per-user protection;
- export/migration implications.

---

## 8.4 No Plaintext Fallback

Se secure backend falhar, não fazer:

```text
write secret to config.json
```

como fallback automático.

Falhar fechado.

---

## 8.5 Test Backend

Tests deverão usar backend fake/in-memory isolado.

Nunca gravar secrets reais durante testes automatizados.

---

## 8.6 Secret Metadata

Operational Store poderá conter metadata como:

```text
secret_ref
created_at
updated_at
type/provider
```

mas nunca valor bruto.

Mesmo metadata no banco só deverá existir se realmente necessária.

---

## 8.7 Secret Redaction

Logging/diagnostics deverão aplicar redaction.

Testes obrigatórios deverão garantir que valor de secret não aparece em:

- logs;
- exceptions comuns;
- health output.

---

## 8.8 Access Boundary

Neste slice, somente Core services explícitos terão acesso à SecretService.

Plugins/Agents ainda não existem.

A API deverá, porém, não pressupor acesso global irrestrito.

---

## 8.9 Client Secret Management

Não é necessário criar UI.

Pode existir interface administrativa mínima para development/test.

A futura CLI deverá reutilizar o mesmo service.

---

## 8.10 Client Authentication Integration

Se SA-B004 utilizar secret/token, deverá armazená-lo via SecretService.

---

## 8.11 Secret Rotation

API deverá permitir substituir valor mantendo referência quando apropriado.

Não é necessário implementar rotação automática.

---

## 8.12 Secret Deletion

Delete deverá ser explícito.

Settings que dependam daquele `secret_ref` poderão permanecer configurados mas unhealthy/incomplete.

---

## 8.13 SA-B006 Tests

- set/get;
- overwrite/rotation;
- delete;
- missing secret;
- backend unavailable;
- no plaintext fallback;
- logging redaction;
- metadata does not reveal value.

---

## 8.14 Acceptance

Secret real pode ser salvo e recuperado pelo Core sem aparecer:

```text
SQLite plaintext
configuration plaintext
logs
health endpoint
```

---

# 9. Cross-Epic Concerns

## 9.1 Error Model

Criar error taxonomy mínima, sem tentar prever todo produto.

Categorias úteis:

```text
ConfigurationError
PersistenceError
AuthenticationError
CompatibilityError
SecretStoreError
LifecycleError
```

Errors deverão poder ser convertidos para client-safe responses.

---

## 9.2 Time

Internamente, timestamps persistentes deverão ser normalizados.

Preferir UTC internamente.

Client será responsável por presentation timezone.

---

## 9.3 IDs

Escolher estratégia estável para IDs.

Uma única convenção deverá ser usada para entidades operacionais novas, salvo justificativa.

---

## 9.4 Dependency Injection

Services deverão receber dependências explicitamente.

Evitar:

```text
global_db
global_secret_store
global_config
```

espalhados pelos módulos.

Não é necessário framework complexo de DI.

---

## 9.5 No Service Locator

Não fornecer objeto:

```text
core.everything
```

para todos os componentes.

Isso destruiria os boundaries antes mesmo da implementação dos próximos Epics.

---

# 10. Test Strategy for Slice 01

A pirâmide inicial será:

```text
many unit tests
+
focused integration tests
+
small number of process-level smoke tests
```

---

## 10.1 Unit Tests

Cobrir:

- configuration validation;
- health aggregation;
- lifecycle logic;
- repositories;
- SecretService contract;
- auth validation.

---

## 10.2 Integration Tests

Usar componentes reais quando necessário:

- SQLite real temporário;
- migrations reais;
- local client server real;
- client authentication real;
- SecretStore test backend.

---

## 10.3 Process-level Smoke Test

Criar smoke semelhante a:

```text
spawn Sofia Core process
↓
wait for ready signal
↓
authenticate test client
↓
query health
↓
disconnect
↓
verify Core remains alive
↓
reconnect
↓
request graceful shutdown
↓
verify clean exit
↓
restart
↓
verify previous runtime session persisted
```

Esse será o teste principal do **Gate I1**.

---

# 11. Failure Scenarios Required

Antes de fechar Gate I1, testar ao menos:

### F1 — Invalid configuration

Core não entra em READY.

### F2 — SQLite unavailable/corrupt initialization

Core não anuncia readiness falsa.

### F3 — Migration failure

Startup aborta de forma controlada.

### F4 — Secret backend unavailable

Core reporta failure/degraded conforme necessidade e nunca plaintext fallback.

### F5 — Invalid client authentication

Request rejeitado.

### F6 — Client disconnect

Core continua executando.

### F7 — Duplicate Core instance

Segunda instância não corrompe profile.

### F8 — Unexpected previous shutdown

Nova runtime session identifica interrupção anterior.

---

# 12. Definition of Done — Per Epic

Um Epic só será considerado concluído quando:

1. implementação completa;
2. tests relevantes passam;
3. typing/lint passam;
4. acceptance criteria demonstrados;
5. documentação mínima atualizada;
6. nenhum architectural invariant conhecido foi violado;
7. não existem TODOs mascarando requisito obrigatório do Epic.

---

# 13. Commit Strategy

Recomenda-se commits pequenos e semanticamente completos.

Exemplo:

```text
chore(project): initialize Python project foundation

feat(core): add application lifecycle

feat(storage): add SQLite operational store

feat(api): add authenticated local client boundary

feat(health): add subsystem health registry

feat(secrets): add secure secret service
```

Não é necessário que cada Epic corresponda exatamente a um commit.

---

# 14. Gate I1 Validation Checklist

Antes de aprovar Gate I1:

```text
[ ] Project bootstrap reproducible
[ ] Lint passes
[ ] Typecheck passes
[ ] Tests pass

[ ] Core starts without UI
[ ] Core has explicit runtime session
[ ] Core remains alive after client disconnect
[ ] Core shuts down gracefully
[ ] Interrupted session detectable

[ ] SQLite Operational Store functional
[ ] Migrations functional
[ ] Schema compatibility checked

[ ] Client boundary local-only
[ ] Client authentication required
[ ] Unauthenticated client rejected
[ ] Reconnect works

[ ] Configuration validated
[ ] Health/readiness exposed
[ ] Degraded states represented

[ ] SecretService functional
[ ] Secrets absent from plaintext configuration
[ ] Secrets absent from Operational DB
[ ] Secrets redacted from logs

[ ] Process-level Gate I1 smoke passes
```

---

# 15. Out of Scope for Slice 01

Explicitamente não implementar ainda:

```text
LLM providers
Conversation
Realtime voice
Policy Engine
Permission Grants
Tool Runtime
Tasks
Agents
Sofias Memory integration
Scheduler
Reminders
Filesystem Tools
Shell
Web
Desktop automation
Plugins
Audit Trail completo
Desktop UI
```

Isso é intencional.

---

# 16. Gate 4 — Implementation Readiness

Com este Technical Backlog Slice materializado, faltam somente duas decisões processuais antes de iniciar código:

1. coding/testing conventions baseline;
2. autorização para criar o repository/project skeleton.

Não existem decisões arquiteturais adicionais obrigatórias antes de SA-B001.

---

# 17. Recommended Execution Order

Embora os Epics estejam separados, a implementação recomendada é:

```text
SA-B001
   ↓
SA-B003 foundation
   ↓
SA-B006 foundation
   ↓
SA-B005 foundation
   ↓
SA-B002 lifecycle integration
   ↓
SA-B004 client boundary
   ↓
integration hardening
   ↓
Gate I1 smoke
```

A razão é prática:

o Core Lifecycle precisa de persistence, secrets e health reais para seu startup final, embora seu conceito venha antes no mapa arquitetural.

---

# 18. Slice Completion

Quando SA-B001…SA-B006 estiverem concluídos:

```text
Gate I1 — Core Alive = CLOSED
```

e o próximo slice será:

```text
SA-B007 AI Provider Framework
SA-B008 Conversation Runtime
SA-B010 Context Builder
```

para atingir:

```text
Gate I2 — Sofia Can Converse
```