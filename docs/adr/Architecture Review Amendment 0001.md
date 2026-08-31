# Architecture Review Amendment 0001

**Project:** Sofia's Assistant  
**Status:** Accepted  
**Decision date:** 2026-08-31  
**Applies to:** ADR-0001, ADR-0004, ADR-0007, ADR-0009, ADR-0010, ADR-0015  
**Origin:** Architecture Gate Review  
**Purpose:** corrigir inconsistências identificadas na revisão cruzada dos ADRs antes do fechamento do Architecture Gate

---

# 1. Context

Após a materialização dos ADR-0001 a ADR-0015, foi realizada uma revisão arquitetural cruzada com o objetivo de identificar:

- conflitos entre decisões;
- decisões que se tornaram mais amplas do que o necessário;
- boundaries sem ownership explícito;
- pressupostos implícitos que poderiam levar a implementações incompatíveis.

A revisão identificou quatro ajustes necessários:

1. `Task` havia sido materializada como wrapper praticamente universal;
2. a cadeia de authority pressupunha existência obrigatória de `Delegation`;
3. o Local Client API não possuía trust boundary explícito;
4. `SecretStore` havia ficado conceitualmente associado ao AI Provider subsystem, embora seja uma capability transversal.

Nenhuma dessas correções exige novo ADR independente.

Este Amendment modifica apenas os pontos explicitamente descritos abaixo.

Todos os demais princípios e decisões dos ADRs originais permanecem válidos.

---

# 2. Precedence

Quando houver conflito entre este Amendment e qualquer trecho dos ADRs afetados:

> **Architecture Review Amendment 0001 prevalece.**

Trechos não conflitantes permanecem vigentes.

---

# 3. Amendment A — Task Is Not a Universal Wrapper

**Afeta:** ADR-0009, ADR-0010, ADR-0015

## 3.1 Decision

`Task` não será obrigatória para toda operação executável.

O runtime distinguirá:

```text
Intent
  │
  ▼
Execution Decision
  │
  ├── Direct Invocation
  │       │
  │       └── ToolCall
  │
  └── Task
          │
          ├── Tool execution
          ├── Workflow
          └── AgentRun
```

Operações imediatas, delimitadas e que não necessitem lifecycle durável poderão executar diretamente através do Tool Runtime.

---

# 4. Direct Invocation

Uma `Direct Invocation` será adequada quando:

- a operação for imediata;
- houver uma Tool claramente aplicável;
- não houver necessidade de background execution;
- não houver waiting state;
- não houver AgentRun;
- não houver workflow persistente;
- não houver necessidade relevante de progress tracking;
- recovery como Task não for necessário.

Exemplos:

```text
"Abra o VS Code."
    ↓
desktop.open_app
```

```text
"Qual é a janela ativa?"
    ↓
desktop.active_window
```

Não será criada Task artificial apenas para uniformizar o runtime.

---

# 5. When Task Is Required

Task deverá existir quando o trabalho necessitar de uma ou mais propriedades como:

```text
durability
background execution
multiple coordinated steps
AgentRun
workflow
waiting
scheduling
delegation
retry semantics
recovery
progress tracking
dependencies
long-running execution
```

A decisão concreta deverá seguir o princípio:

> **Use the least complex execution mechanism capable of solving the work correctly.**

---

# 6. ToolCall Without Task

Uma ToolCall direta continuará possuindo:

- stable identity;
- validated arguments;
- resource resolution;
- PolicyDecision;
- timeout;
- cancellation semantics quando aplicável;
- ToolResult;
- Audit correlation.

Ausência de Task não significa ausência de controle arquitetural.

---

# 7. ADR-0010 Scope Amendment

O lifecycle definido no ADR-0010 aplica-se a **Tasks existentes**.

Ele não cria obrigação de transformar toda ToolCall em Task.

ToolCalls diretas terão lifecycle próprio apenas no nível necessário para:

- execution;
- timeout;
- cancellation;
- result;
- audit;
- recovery quando a operação especificamente exigir.

Se a operação precisar de recovery durável complexo, isso é sinal de que provavelmente deveria ser promovida a Task.

---

# 8. ADR-0015 Trace Amendment

Audit deverá suportar pelo menos duas formas de causalidade.

## Direct Invocation

```text
User / Conversation / Runtime
          ↓
       ToolCall
          ↓
   PolicyDecision
          ↓
      Execution
          ↓
      ToolResult
```

## Task-based Execution

```text
User / Event / Schedule / Delegation
              ↓
             Task
              ↓
     Workflow / AgentRun / Tool
              ↓
           ToolCall
              ↓
       PolicyDecision
              ↓
          Execution
              ↓
          ToolResult
```

Task ID não será campo obrigatório de toda execução auditável.

---

# 9. Amendment B — Authority Does Not Require Delegation

**Afeta:** ADR-0007, ADR-0009

## 9.1 Problem Corrected

Os ADRs originais utilizavam frequentemente:

```text
AgentRun Authority
    ⊆ Delegation Authority
    ⊆ Root Effective Authority
```

Essa cadeia permanece válida quando uma Delegation existe.

Porém, Delegation não será criada artificialmente para toda Task ou AgentRun.

---

# 10. General Authority Rule

A regra geral passa a ser:

```text
Execution Authority
       ⊆
Originating Authority Context
       ⊆
Root Effective Authority
```

Nenhuma execução derivada poderá ampliar authority.

---

# 11. Task Authority Context

Uma Task poderá possuir `Authority Context` próprio.

Ele representa a authority efetivamente disponível para aquela unidade de trabalho.

Conceitualmente, poderá ser derivado de:

```text
existing Permission Grants
+
current Policy
+
resource scopes
+
explicit confirmations
+
Delegation, when present
+
runtime constraints
```

---

# 12. User Request Is Not a Permission Grant

Uma solicitação explícita do usuário demonstra intenção.

Ela não cria authority ilimitada.

Exemplo:

> “Analise este repositório.”

não significa automaticamente:

```text
filesystem = unrestricted
shell = unrestricted
network = unrestricted
```

O runtime continuará avaliando cada capability necessária.

---

# 13. Authority Chain Without Delegation

Quando nenhuma Delegation existir:

```text
Root Effective Authority
          ↓
    Task Authority
          ↓
   AgentRun Authority
          ↓
Tool Execution Authority
```

Formalmente:

```text
Tool Execution Authority
    ⊆ AgentRun Authority
    ⊆ Task Authority
    ⊆ Root Effective Authority
```

---

# 14. Authority Chain With Delegation

Quando uma Delegation existir:

```text
Root Effective Authority
          ↓
  Delegation Authority
          ↓
      Task Authority
          ↓
   AgentRun Authority
          ↓
Tool Execution Authority
```

Formalmente:

```text
Tool Execution Authority
    ⊆ AgentRun Authority
    ⊆ Task Authority
    ⊆ Delegation Authority
    ⊆ Root Effective Authority
```

---

# 15. Delegation Semantics Remain Unchanged

Delegation continua representando objetivo/autonomia delegada que pode sobreviver além de uma interação imediata.

Exemplo típico:

> “Durante esta semana acompanhe os PRs desse projeto e me avise quando houver algo importante.”

Isso deve ser representado como Delegation.

Já:

> “Analise este PR agora.”

pode ser apenas Task.

---

# 16. Agent Creation

Sofia/root continua sendo a única authority de coordenação para criar AgentRuns.

Esse Amendment não altera:

- root-only instantiation;
- context isolation;
- Tool subset;
- authority narrowing;
- no uncontrolled agent trees.

---

# 17. Amendment C — Local Client Trust Boundary

**Afeta:** ADR-0001

## 17.1 Decision

A interface Client ↔ Sofia Core será **local-only e autenticada por padrão**.

A presença do client na mesma máquina não será considerada prova suficiente de confiança.

Regra:

```text
localhost ≠ trusted identity
```

---

# 18. Baseline Client Boundary

A interface deverá garantir, por mecanismo adequado ao transporte escolhido:

```text
local-only by default
+
client authentication or OS-level authentication
+
no LAN exposure by default
```

---

# 19. Allowed Implementation Families

Este Amendment não escolhe transporte.

Implementações futuras poderão utilizar mecanismos como:

```text
Named Pipe + OS ACL / identity
```

ou:

```text
local socket + OS permissions
```

ou:

```text
loopback HTTP/WebSocket
+
session/ephemeral credential
```

desde que preservem o boundary.

---

# 20. Network Binding

Baseline obrigatório:

```text
external interface binding = disabled
LAN access = disabled
remote access = disabled
```

O Core não deverá escutar em interfaces externas por default.

---

# 21. Client Authentication vs Authorization

Client authentication responde:

> Qual client realizou este request?

Policy responde:

> Esta ação está autorizada?

São boundaries independentes.

Fluxo:

```text
Authenticated Client
        ↓
   Core Command
        ↓
   PolicyEngine
        ↓
    Execution
```

Desktop Client autenticado não recebe authority ilimitada.

---

# 22. Compromised Local Process

O modelo deverá considerar que outro processo executando na mesma máquina pode ser:

- defeituoso;
- malicioso;
- comprometido;
- executado por Plugin;
- código gerado.

Portanto ele não deverá conseguir chamar livremente a API local apenas por conhecer a porta.

---

# 23. Future Remote Clients

Qualquer futura capability de:

- Mobile Companion;
- LAN access;
- Remote Client;

deverá introduzir explicitamente:

- authentication;
- encryption;
- device trust;
- pairing;
- revocation;
- network exposure.

Remote access não será ativado implicitamente pela implementação do Local Client API.

---

# 24. Amendment D — SecretStore Is a Core Service

**Afeta:** ADR-0004 e referências subsequentes

## 24.1 Decision

`SecretStore` será uma capability transversal do Sofia Core.

Não pertence ao AI Provider subsystem.

Arquitetura:

```text
                  Sofia Core
                      │
                Secret Service
                      │
                 SecretStore
               /      |       \
              /       |        \
             ▼        ▼         ▼
        Providers   Plugins   Integrations
                               │
                               ▼
                              Tools
```

---

# 25. Secret Service

O Core deverá expor uma abstração controlada de secrets para componentes autorizados.

Responsabilidades conceituais:

- create/store;
- retrieve by reference;
- update;
- revoke/remove;
- metadata;
- controlled secret injection.

---

# 26. Secret References

Componentes deverão preferir trabalhar com:

```text
secret_ref
```

em vez de persistir valores brutos.

Exemplo:

```text
provider:
  credential_ref = openai/default
```

---

# 27. Provider Integration

ADR-0004 permanece correto ao exigir que Provider Adapters obtenham credentials através do SecretStore.

Apenas o ownership muda:

```text
Provider Adapter
    ↓
Secret Service
    ↓
SecretStore
```

---

# 28. Plugin Integration

Plugins não receberão acesso irrestrito ao SecretStore.

Uma Integration de Plugin poderá receber referência ou acesso controlado apenas ao secret necessário.

---

# 29. Tool Execution

Tool/Subprocess poderá receber secret temporariamente quando explicitamente necessário.

A Secret Service deverá cooperar com Execution Boundary para minimizar exposição.

---

# 30. CLI Future

Uma futura CLI deverá utilizar a mesma Secret Service.

Não deverá criar arquivo de credentials paralelo.

---

# 31. SecretStore Implementation Remains Deferred

Este Amendment não escolhe:

- Windows Credential Manager;
- DPAPI-backed encrypted storage;
- custom encrypted store.

Essa é implementation decision posterior.

Novo ADR só será necessário se a escolha futura tiver consequência arquitetural significativa.

---

# 32. Derived Technical Components

A Architecture Gate Review também identificou alguns componentes transversais que deverão aparecer explicitamente no Technical Backlog.

Eles não exigem ADR próprio neste momento.

---

# 33. Artifact Service

Deverá existir boundary para artifacts produzidos pelo runtime.

Exemplos:

- screenshots;
- generated files;
- reports;
- sandbox outputs;
- downloaded files;
- diffs.

Fluxo conceitual:

```text
Tool / Agent / Sandbox
        ↓
      Artifact
        ↓
   Artifact Service
        ↓
 stable reference
```

ToolResult deverá preferir referências em vez de carregar grandes blobs indiscriminadamente.

---

# 34. Notification and Attention Service

Deverá existir serviço responsável pela apresentação de acontecimentos que merecem atenção.

Exemplos:

- reminder;
- Task completion;
- confirmation request;
- proactive notification;
- integration degradation.

A futura `Attention Policy` decidirá quando eventos devem resultar em:

```text
IGNORE
NOTIFY
PLAN
ACT
```

ou semântica equivalente.

---

# 35. Client Session / Local Authentication

Deverá existir componente técnico responsável pelo Amendment C.

Sua implementação dependerá do protocolo Core ↔ Client escolhido.

---

# 36. Runtime Health / Readiness

O Core deverá conseguir representar health por subsystem.

Exemplos:

```text
AI provider = degraded
Sofias Memory = unavailable
Scheduler = healthy
Plugin X = degraded
```

Readiness do produto não deverá ser apenas boolean global sem diagnóstico.

---

# 37. Architectural Model After Amendment

O modelo consolidado passa a ser:

```text
                         Clients
                            │
              Authenticated Local Boundary
                            │
                            ▼
┌──────────────────────────────────────────────────────┐
│                     Sofia Core                       │
│                                                      │
│ Conversation Runtime                                 │
│ Context Builder                                      │
│ Root Orchestrator                                    │
│                                                      │
│ Execution Decision                                   │
│    │                                                 │
│    ├── Direct Invocation ───────┐                    │
│    │                            │                    │
│    └── Task Runtime             │                    │
│          ├── Workflow           │                    │
│          └── AgentRun           │                    │
│                                 ▼                    │
│                            Tool Runtime               │
│                                 │                    │
│                           PolicyEngine                │
│                                 │                    │
│                       Execution Boundary              │
│                                                      │
│ Event Runtime / Scheduler                            │
│ Memory Orchestrator                                  │
│ Audit                                                │
│ Secret Service                                       │
│ Artifact Service                                     │
│ Notification / Attention                             │
│ Runtime Health                                       │
└───────────────┬───────────────────────┬──────────────┘
                │                       │
                ▼                       ▼
       Operational Store          Sofias Memory
            SQLite             Persistent Cognition
```

---

# 38. Revised Architectural Invariants

Os seguintes invariants passam a integrar a baseline arquitetural.

### REV-INV-001

Task não é wrapper obrigatório para ToolCall.

### REV-INV-002

Direct Invocation pode executar Tool sem criar Task quando lifecycle durável não é necessário.

### REV-INV-003

Task será utilizada quando o trabalho exigir durabilidade, waiting, Agent, workflow, recovery ou lifecycle próprio.

### REV-INV-004

Delegation não é obrigatória para criar Task ou AgentRun.

### REV-INV-005

Authority derivada sempre narrowa o Originating Authority Context.

### REV-INV-006

Quando Delegation existir, ela limita Task/Agent authority.

### REV-INV-007

Local Client API exige trust boundary explícito.

### REV-INV-008

Loopback/localhost sozinho não constitui autenticação.

### REV-INV-009

Core não é exposto para LAN/remote access por default.

### REV-INV-010

Client authentication não substitui Policy authorization.

### REV-INV-011

SecretStore é capability transversal do Core.

### REV-INV-012

Providers, Plugins e Integrations consomem secrets através de boundary controlado.

---

# 39. Impact on Existing ADRs

## ADR-0001

**AMENDED**

Adicionada exigência de Local Client trust/authentication boundary.

---

## ADR-0004

**AMENDED**

SecretStore passa a pertencer ao Core, mantendo integração com Provider Adapters.

---

## ADR-0007

**AMENDED**

Authority narrowing deixa de pressupor Delegation obrigatória.

---

## ADR-0009

**AMENDED**

Task deixa de ser wrapper universal.

AgentRun poderá existir dentro de Task sem Delegation persistente obrigatória.

---

## ADR-0010

**AMENDED**

Task lifecycle aplica-se apenas quando Task existe.

Direct ToolCall não precisa assumir Task state machine.

---

## ADR-0015

**AMENDED**

Audit trace passa a suportar Direct Invocation e Task-based execution.

---

# 40. ADRs Not Changed

Os seguintes ADRs permanecem integralmente válidos:

```text
ADR-0002 — Operational Persistence Architecture
ADR-0003 — Internal Event and Scheduler Architecture
ADR-0005 — Conversation, Realtime Voice and Context Ownership
ADR-0006 — Deterministic Authorization Boundary
ADR-0008 — Tool Contract, Registry and Execution Boundary
ADR-0011 — Sofia's Memory Integration Boundary
ADR-0012 — Cognitive Memory Model and Lifecycle
ADR-0013 — Execution Isolation and Sandbox Model
ADR-0014 — Plugin and Extensibility Architecture
```

---

# 41. Architecture Gate

Após aplicação deste Amendment:

## Gate 2 — Architecture Definition

**Status: CLOSED**

Os architectural boundaries necessários para decomposição do MVP estão definidos.

Não existem questões estruturais abertas que bloqueiem a criação do Technical Backlog.

---

# 42. Decisions Still Deferred

Gate 2 fechado não significa que toda technology choice já foi feita.

Continuam corretamente deferred para Technical Backlogs:

```text
Core local API technology
Core ↔ Client protocol
Desktop shell
ORM
migration framework
Event Bus implementation
Scheduler implementation
Realtime provider
audio/VAD stack
Task schemas
ToolSpec schemas
sandbox backend
Plugin packaging
Audit physical schema
SecretStore implementation
Sofias Memory cognitive schemas
```

Essas escolhas deverão respeitar os ADRs e este Amendment.

---

# 43. Implementation Rule

Durante Technical Backlog e implementação:

> Se uma decisão proposta contradizer um invariant aprovado, ela não poderá ser tratada como simples implementation detail.

Será necessário:

1. corrigir a implementação;
2. ou, se houver justificativa arquitetural real, criar novo ADR que substitua explicitamente a decisão anterior.

---

# 44. Final Decision

Architecture Review Amendment 0001 é aprovado.

Ele corrige:

1. Task universal;
2. Delegation obrigatória na authority chain;
3. ausência de trust boundary no Local Client API;
4. ownership incorreto do SecretStore.

Com essas correções, **PRD v0.1 + ADR-0001…ADR-0015 + Architecture Review Amendment 0001** passam a constituir a baseline arquitetural oficial do Sofia's Assistant.

**Gate 2 — Architecture Definition: CLOSED.**