# Sofia's Assistant — Technical Backlog Map

**Status:** Baseline para aprovação  
**Project:** Sofia's Assistant  
**Source:** PRD v0.1 + ADR-0001…ADR-0015 + Architecture Review Amendment 0001  
**Architecture Gate:** CLOSED  
**Purpose:** transformar a arquitetura aprovada em épicos técnicos ordenados por dependência e gates de implementação

---

# 1. Backlog Strategy

O backlog será organizado em três classes:

```text
MVP KERNEL
    ↓
MVP CAPABILITIES
    ↓
POST-MVP
```

## MVP Kernel

Infraestrutura mínima necessária para provar que a arquitetura funciona.

## MVP Capabilities

Capabilities reais que tornam o kernel útil e validam os boundaries arquiteturais.

## Post-MVP

Recursos importantes, mas que não precisam estar presentes para validar a primeira arquitetura funcional.

---

# 2. Regra de implementação

O projeto não será desenvolvido por feature visual isolada.

A estratégia será por **vertical slices arquiteturais**.

Exemplo:

```text
Conversation request
    ↓
Core API
    ↓
Policy
    ↓
Tool
    ↓
Result
    ↓
Persistence
    ↓
Audit
    ↓
Client
```

é preferível a implementar durante semanas:

```text
all repositories
then all services
then all APIs
then all UI
```

sem nenhum fluxo funcional de ponta a ponta.

---

# 3. Epic Map

O backlog inicial será composto por:

```text
SA-B001 Project Foundation
SA-B002 Core Lifecycle
SA-B003 Operational Persistence
SA-B004 Local Client Boundary
SA-B005 Runtime Health & Configuration
SA-B006 Secret Service

SA-B007 AI Provider Framework
SA-B008 Conversation Runtime
SA-B009 Realtime Voice
SA-B010 Context Builder

SA-B011 Policy Engine
SA-B012 Grants & Delegations
SA-B013 Tool Runtime
SA-B014 Artifact Service

SA-B015 Task Runtime
SA-B016 Agent Runtime
SA-B017 Execution Isolation

SA-B018 Sofias Memory Adapter
SA-B019 Memory Orchestrator
SA-B020 Cognitive Memory MVP

SA-B021 Event Runtime
SA-B022 Scheduler & Reminders
SA-B023 Notification & Attention

SA-B024 Filesystem Capability
SA-B025 Shell Capability
SA-B026 Web Search & Read
SA-B027 Desktop Basics
SA-B028 Screenshot Vision

SA-B029 Experimental Agent
SA-B030 Audit & Traceability
SA-B031 Desktop Client

SA-B032 Plugin Foundation

SA-B033 Recovery Hardening
SA-B034 MVP Integration & Release Gate
```

---

# 4. Phase 0 — Project Foundation

## SA-B001 — Project Foundation

### Goal

Criar a estrutura física inicial do projeto sem antecipar features.

### Scope

- repository structure;
- Python project/package;
- configuration baseline;
- test structure;
- linting;
- typing;
- formatting;
- dependency management;
- CI baseline;
- application versioning;
- development scripts.

### Architectural Constraints

- modular monolith;
- Core independente da UI;
- boundaries explícitos;
- Windows-first;
- sem microservices.

### Acceptance

Projeto inicia em ambiente de desenvolvimento, testes rodam e estrutura suporta módulos independentes.

### Depends on

Nenhum.

### Classification

**MVP KERNEL / BLOCKER**

---

# 5. Phase 1 — Core Runtime Foundation

## SA-B002 — Core Lifecycle

### Goal

Implementar lifecycle independente do Sofia Core.

### Scope

- Core bootstrap;
- startup;
- readiness;
- graceful shutdown;
- runtime session identity;
- background lifetime;
- service initialization order.

### Must validate

```text
Core can run without Desktop Client.
```

### Depends on

SA-B001.

### Classification

**MVP KERNEL / BLOCKER**

---

## SA-B003 — Operational Persistence

### Goal

Implementar Operational Store durável.

### Scope

- SQLite;
- migrations;
- persistence configuration;
- repository boundaries;
- transaction boundary;
- runtime session records;
- initial entity infrastructure.

### Initial durable domains

- Conversation;
- Task;
- AgentRun;
- Grant;
- Delegation;
- Schedule;
- Audit;
- settings.

Schemas poderão crescer incrementalmente.

### Depends on

SA-B001.

### Classification

**MVP KERNEL / BLOCKER**

---

## SA-B004 — Local Client Boundary

### Goal

Criar a interface formal entre clients e Core.

### Scope

- escolha do protocolo local;
- request/response;
- streaming/events;
- local-only binding;
- client authentication;
- client session;
- reconnect;
- API versioning baseline.

### Architectural requirement

```text
localhost ≠ trusted
```

### Acceptance

Um client de teste consegue:

- autenticar;
- consultar Core health;
- enviar command;
- receber streaming/event.

Processo local sem credencial não consegue controlar o Core.

### Depends on

SA-B002.

### Classification

**MVP KERNEL / BLOCKER**

---

## SA-B005 — Runtime Health & Configuration

### Goal

Centralizar configuração e health dos subsystems.

### Scope

- runtime configuration;
- subsystem health;
- readiness;
- degraded states;
- configuration validation;
- local settings.

### Example

```text
Core = ready
Memory = unavailable
Realtime provider = healthy
Scheduler = healthy
```

### Depends on

SA-B002, SA-B003.

### Classification

**MVP KERNEL**

---

## SA-B006 — Secret Service

### Goal

Implementar boundary transversal de secrets.

### Scope

- SecretService interface;
- SecretStore implementation inicial;
- secret references;
- controlled retrieval;
- redaction;
- integration with configuration.

### Security requirement

Secrets não poderão ser armazenados em plaintext no Operational Store ou configuração comum.

### Depends on

SA-B001.

### Classification

**MVP KERNEL**

---

# 6. Phase 2 — AI & Conversation Kernel

## SA-B007 — AI Provider Framework

### Goal

Implementar provider abstraction e capability routing.

### Scope

- provider interfaces;
- Provider Adapter;
- Model Registry;
- capability metadata;
- AI Router;
- locality requirements;
- normalized errors;
- structured outputs;
- tool-call normalization;
- Fake/Test Provider.

### Initial implementation

Suporte mínimo para:

```text
text generation
streaming
structured output
tool calling
```

Realtime poderá utilizar interface própria.

### Depends on

SA-B005, SA-B006.

### Classification

**MVP KERNEL / BLOCKER**

---

## SA-B008 — Conversation Runtime

### Goal

Implementar authority da Conversation no Sofia Core.

### Scope

- Conversation;
- Turn;
- text interaction;
- streaming;
- interrupted output;
- provider request correlation;
- operational history;
- Task linkage.

### Acceptance

Provider session pode ser descartada e Conversation continua recuperável.

### Depends on

SA-B003, SA-B007.

### Classification

**MVP KERNEL / BLOCKER**

---

## SA-B009 — Realtime Voice

### Goal

Validar realtime voice como capability nativa.

### Scope

- RealtimeProvider contract;
- audio input/output;
- streaming;
- barge-in;
- interruption semantics;
- partial/final transcripts;
- provider session lifecycle;
- Fake Realtime Provider;
- primeiro provider real.

### Does not include yet

- wake word;
- continuous listening;
- webcam.

### Depends on

SA-B007, SA-B008.

### Classification

**MVP CAPABILITY / BLOCKER FOR MVP**

---

## SA-B010 — Context Builder

### Goal

Construir contexto como projeção controlada.

### Scope

- recent Turn selection;
- Working Memory;
- Task context;
- ToolResults;
- memory injection hook;
- locality filtering;
- context budget;
- provider capability awareness.

### Rule

```text
Context != Full Transcript
```

### Depends on

SA-B008.

### Classification

**MVP KERNEL / BLOCKER**

---

# 7. Phase 3 — Authority & Tools

## SA-B011 — Policy Engine

### Goal

Implementar deterministic authorization boundary.

### Scope

- PolicyRequest;
- PolicyDecision;
- capability evaluation;
- resource evaluation;
- ALLOW;
- DENY;
- REQUIRE_CONFIRMATION;
- REQUIRE_ELEVATION;
- failure closed;
- policy version;
- Fake policy fixtures.

### Depends on

SA-B003.

### Classification

**MVP KERNEL / BLOCKER**

---

## SA-B012 — Grants & Delegations

### Goal

Materializar authority persistente.

### Scope

- PermissionGrant;
- resource scopes;
- constraints;
- expiration;
- revocation;
- Task Authority Context;
- Delegation;
- authority narrowing;
- confirmation-created Grants.

### Must support MVP

At least:

```text
ONE_SHOT
SESSION
UNTIL_REVOKED
```

Outros temporal scopes podem vir depois.

### Depends on

SA-B003, SA-B011.

### Classification

**MVP KERNEL / BLOCKER**

---

## SA-B013 — Tool Runtime

### Goal

Implementar contrato único de execução de Tools.

### Scope

- ToolSpec;
- Tool Registry;
- ToolCall;
- argument validation;
- resource resolution;
- Policy integration;
- Executor;
- ToolResult;
- timeout;
- cancellation baseline;
- Fake Tools.

### Must support

```text
Direct Invocation
Task-based Invocation
Agent-based Invocation
```

### Depends on

SA-B007, SA-B011, SA-B012.

### Classification

**MVP KERNEL / BLOCKER**

---

## SA-B014 — Artifact Service

### Goal

Criar boundary para arquivos e artifacts produzidos pelo runtime.

### Scope

- ArtifactRef;
- local artifact storage;
- temporary artifacts;
- retention baseline;
- safe access;
- ToolResult integration.

### Example artifacts

- screenshot;
- report;
- generated file;
- diff;
- sandbox output.

### Depends on

SA-B003.

### Classification

**MVP KERNEL**

---

# 8. Phase 4 — Durable Work & Agents

## SA-B015 — Task Runtime

### Goal

Implementar trabalho durável sem tornar Task wrapper universal.

### Scope

- Task;
- state machine;
- attempts;
- queue/claim;
- WAITING states;
- cancellation;
- retry baseline;
- progress;
- TaskResult;
- Direct Invocation vs Task decision boundary.

### Must preserve

```text
Waiting != Failure
```

### Depends on

SA-B003, SA-B011, SA-B013.

### Classification

**MVP KERNEL / BLOCKER**

---

## SA-B016 — Agent Runtime

### Goal

Implementar AgentRun subordinado à Sofia/root.

### Scope

- AgentDefinition;
- Agent Registry;
- AgentRun;
- root-only creation;
- delegated context;
- Tool subsets;
- authority narrowing;
- workspace;
- result handoff;
- Fake Agent.

### Does not require yet

Production Development Agent.

### Depends on

SA-B010, SA-B012, SA-B013, SA-B015.

### Classification

**MVP KERNEL / BLOCKER**

---

## SA-B017 — Execution Isolation

### Goal

Implementar execution backends fundamentais.

### Scope

- IN_PROCESS;
- SUBPROCESS;
- execution dispatcher;
- process ownership;
- timeout;
- cancellation;
- environment filtering;
- workspace handling;
- sandbox interface.

### MVP requirement

`SUBPROCESS` funcional.

`SANDBOX` pode inicialmente possuir contract + fail-closed implementation se backend final ainda não estiver pronto.

### Depends on

SA-B013, SA-B015.

### Classification

**MVP KERNEL**

---

# 9. Phase 5 — Memory Integration

## SA-B018 — Sofias Memory Adapter

### Goal

Integrar o Assistant ao Sofias Memory por contrato explícito.

### Scope

- MemoryProvider interface;
- SofiasMemoryAdapter;
- health;
- compatibility;
- recall;
- remember/persist;
- forget;
- FakeMemoryProvider;
- timeout;
- retry/idempotency baseline.

### Depends on

SA-B005, SA-B010.

### Classification

**MVP KERNEL / BLOCKER**

---

## SA-B019 — Memory Orchestrator

### Goal

Coordenar uso de memória persistente pelo Assistant.

### Scope

- MemoryCandidate;
- candidate extraction;
- classification;
- confirmation requirement;
- scope;
- provenance;
- retrieval orchestration;
- pending memory operations;
- Context Builder integration.

### Depends on

SA-B010, SA-B011, SA-B018.

### Classification

**MVP KERNEL / BLOCKER**

---

## SA-B020 — Cognitive Memory MVP

### Goal

Criar o primeiro vertical slice cognitivo real no Sofias Memory.

### Initial target

```text
PROFILE
SEMANTIC
```

com:

- provenance;
- stable ID;
- scope;
- lifecycle básico;
- supersession básica;
- typed recall.

### Also include

Consolidation inicial de Conversation para memória significativa.

### Not required in first slice

Procedural system completo e Episode engine sofisticada.

### Important

Este Epic provavelmente será implementado principalmente no repositório **Sofias Memory**, não no Assistant.

### Depends on

SA-B018, SA-B019.

### Classification

**MVP CAPABILITY / BLOCKER FOR MEMORY MVP**

---

# 10. Phase 6 — Events & Proactivity

## SA-B021 — Event Runtime

### Goal

Implementar Internal Event Bus e Event Sources.

### Scope

- Domain Events;
- External Events;
- event identity;
- subscriptions;
- correlation;
- ephemeral/durable classification;
- FakeEventSource.

### Depends on

SA-B002, SA-B003.

### Classification

**MVP KERNEL**

---

## SA-B022 — Scheduler & Reminders

### Goal

Criar scheduling persistente e primeiro recurso proativo real.

### Scope

- one-shot schedules;
- recurring baseline;
- timezone;
- persistence;
- missed-run policy;
- Reminder;
- Scheduler → Event;
- WAITING_SCHEDULE wakeup.

### Must validate

Reminder sobrevive a:

```text
Core restart
machine reboot
```

quando aplicável.

### Depends on

SA-B003, SA-B015, SA-B021.

### Classification

**MVP CAPABILITY / BLOCKER FOR MVP**

---

## SA-B023 — Notification & Attention

### Goal

Criar boundary entre Event e atenção do usuário.

### MVP scope

- Task completion notification;
- ReminderDue;
- Permission request;
- degraded subsystem notification.

### Future

Attention Policy sofisticada:

```text
IGNORE / REMEMBER / NOTIFY / PLAN / ACT
```

### Depends on

SA-B021.

### Classification

**MVP KERNEL**

---

# 11. Phase 7 — Initial Capabilities

## SA-B024 — Filesystem Capability

### Goal

Implementar filesystem sem depender de shell.

### Initial Tools

```text
filesystem.read
filesystem.write
filesystem.list
```

Possivelmente:

```text
filesystem.move
filesystem.delete
```

apenas quando Policy estiver madura.

### Must validate

- path canonicalization;
- workspace scopes;
- traversal prevention;
- ToolResult;
- audit.

### Depends on

SA-B013, SA-B017.

### Classification

**MVP CAPABILITY / BLOCKER**

---

## SA-B025 — Shell Capability

### Goal

Permitir shell controlado.

### Scope

- executable + arguments;
- cwd;
- environment filtering;
- timeout;
- subprocess;
- cancellation;
- Policy;
- stdout/stderr limits.

### Depends on

SA-B013, SA-B017.

### Classification

**MVP CAPABILITY**

---

## SA-B026 — Web Search & Read

### Goal

Oferecer pesquisa e leitura web básicas.

### Tools

```text
web.search
web.read
```

### MVP capability

- search;
- retrieve sources;
- normalize content;
- multi-source synthesis through Conversation/Agent runtime.

### Does not include

Browser automation completa.

### Depends on

SA-B013, SA-B007.

### Classification

**MVP CAPABILITY**

---

## SA-B027 — Desktop Basics

### Goal

Criar integração desktop mínima.

### Initial Tools

```text
desktop.open_app
desktop.active_window
```

Possivelmente:

```text
desktop.open_file
```

### Does not include

Full mouse/keyboard automation.

### Depends on

SA-B013.

### Classification

**MVP CAPABILITY**

---

## SA-B028 — Screenshot Vision

### Goal

Permitir percepção visual manual da tela.

### Scope

- screenshot capture;
- Artifact Service integration;
- image input to vision-capable provider;
- Context Builder integration;
- explicit user action/authorization.

### Does not include

Continuous screen awareness.

### Depends on

SA-B007, SA-B014, SA-B027.

### Classification

**MVP CAPABILITY**

---

# 12. Phase 8 — Agent Validation

## SA-B029 — Experimental Agent

### Goal

Validar Agent architecture em caso real.

### Selection criteria

O primeiro Agent deverá exigir:

- múltiplas Tools;
- reasoning adaptativo;
- delegated context;
- Tool subset;
- AgentRun;
- Policy;
- result handoff.

### Preferred candidates

```text
Research Agent
```

ou:

```text
Development Analysis Agent
```

A escolha final será feita quando Tools disponíveis forem conhecidas.

### Acceptance

Deve provar:

```text
Sofia/root creates AgentRun
↓
restricted context
↓
restricted authority
↓
Agent uses multiple Tools
↓
result returns to Sofia/root
```

### Depends on

SA-B016, SA-B024 and/or SA-B026.

### Classification

**MVP CAPABILITY / BLOCKER**

---

# 13. Phase 9 — Audit & Desktop Experience

## SA-B030 — Audit & Traceability

### Goal

Materializar Audit Trail da arquitetura.

### Scope

- AuditEntry;
- correlation IDs;
- causation;
- PolicyDecision trace;
- ToolCall trace;
- Task/Agent trace;
- redaction;
- query service;
- runtime session correlation.

### Must support

Direct Invocation e Task-based execution.

### Depends on

SA-B003, SA-B011, SA-B013, SA-B015.

### Classification

**MVP KERNEL / BLOCKER**

---

## SA-B031 — Desktop Client

### Goal

Criar primeira experiência de usuário real.

### MVP UI

- tray;
- text chat;
- voice state;
- realtime voice controls;
- confirmation UI;
- Task status;
- notifications;
- subsystem health;
- basic settings.

### Architectural rule

Client nunca acessa SQLite ou services internos diretamente.

### Depends on

SA-B004, SA-B008, SA-B009, SA-B023, SA-B030.

### Classification

**MVP CAPABILITY / BLOCKER**

---

# 14. Phase 10 — Extensibility Foundation

## SA-B032 — Plugin Foundation

### Goal

Validar extension boundary sem construir marketplace.

### MVP-ish scope

- PluginManifest;
- local plugin discovery;
- enable/disable;
- compatibility;
- Tool registration;
- EventSource registration;
- AgentDefinition registration;
- no bypass of Policy;
- PluginContext baseline.

### Explicitly not required

- marketplace;
- signing infrastructure;
- public registry;
- complex UI extensions.

### Depends on

SA-B013, SA-B016, SA-B021, SA-B017.

### Classification

**POST-KERNEL / OPTIONAL FOR FIRST MVP RELEASE**

---

# 15. Phase 11 — Recovery Hardening

## SA-B033 — Recovery Hardening

### Goal

Validar comportamento após crashes reais.

### Scope

- interrupted Task recovery;
- ToolCall uncertainty;
- subprocess recovery;
- AgentRun recovery;
- schedule recovery;
- authority recalculation;
- duplicate execution prevention.

### Includes

Crash simulation tests.

### Depends on

SA-B015, SA-B017, SA-B022, SA-B030.

### Classification

**MVP KERNEL / RELEASE BLOCKER**

---

# 16. Phase 12 — MVP Integration

## SA-B034 — MVP Integration & Release Gate

### Goal

Executar todos os cenários de sucesso definidos no PRD.

### Must prove

## Scenario A — Text Conversation

Texto funciona ponta a ponta.

## Scenario B — Realtime Voice

Voice streaming + barge-in.

## Scenario C — Memory

Candidate → Sofias Memory → recall → Context Builder.

## Scenario D — Filesystem

Read/write com Policy.

## Scenario E — Shell

Scoped execution + timeout + Audit.

## Scenario F — Web Research

Search + multiple sources + synthesis.

## Scenario G — Reminder

Reminder survives restart.

## Scenario H — Agent

Root-instantiated Agent com context/tool/authority narrowing.

## Scenario I — Recovery

Interrupted Task recovered sem duplicate side effects.

## Scenario J — Provider Routing

Mais de um provider/model pode participar sem alterar Sofia identity.

### Depends on

Todos os MVP blockers anteriores.

### Classification

**MVP RELEASE GATE**

---

# 17. Dependency Graph

Visão simplificada:

```text
SA-B001 Project Foundation
        │
        ├─────────────┐
        ▼             ▼
SA-B002 Core      SA-B003 Persistence
        │             │
        ▼             ├──────────────┐
SA-B004 Client    SA-B011 Policy     │
        │             │              │
        │             ▼              │
        │         SA-B012 Grants     │
        │             │              │
        │             ▼              │
        │         SA-B013 Tools ◄────┘
        │             │
        │             ├─────► SA-B017 Isolation
        │             ├─────► SA-B024 Filesystem
        │             └─────► SA-B025 Shell
        │
        └─────────────────────────────────────┐

SA-B005 Health
   │
   ├──► SA-B006 Secrets
   │
   └──► SA-B007 Providers
             │
             ▼
        SA-B008 Conversation
             │
        ┌────┴─────┐
        ▼          ▼
SA-B009 Voice   SA-B010 Context
                       │
                       ├──► SA-B018 Memory Adapter
                       │         │
                       │         ▼
                       │    SA-B019 Orchestrator
                       │         │
                       │         ▼
                       │    SA-B020 Cognitive Memory
                       │
                       ▼
                  SA-B016 Agents
                       ▲
                       │
                  SA-B015 Tasks
                       ▲
                       │
                  SA-B013 Tools

SA-B021 Events
   │
   ▼
SA-B022 Scheduler
   │
   └──► SA-B023 Notifications

Capabilities
SA-B024 Filesystem
SA-B025 Shell
SA-B026 Web
SA-B027 Desktop
SA-B028 Vision
        │
        ▼
SA-B029 Experimental Agent

SA-B030 Audit
        │
        ▼
SA-B031 Desktop Client

SA-B033 Recovery
        │
        ▼
SA-B034 MVP Gate
```

---

# 18. Implementation Gates

## Gate I0 — Repository Ready

Requires:

```text
SA-B001
```

Success means:

- repository created;
- quality tooling ready;
- project can run tests.

---

# 19. Gate I1 — Core Alive

Requires:

```text
SA-B002
SA-B003
SA-B004
SA-B005
SA-B006
```

Success means:

- Core runs independently;
- storage migrates;
- authenticated local client connects;
- health works;
- secrets boundary exists.

No LLM is required yet.

---

# 20. Gate I2 — Sofia Can Converse

Requires:

```text
SA-B007
SA-B008
SA-B010
```

Success means:

- text conversation works;
- provider can be changed through Adapter;
- Context Builder owns prompt/context.

---

# 21. Gate I3 — Sofia Can Speak

Requires:

```text
SA-B009
```

Success means:

- realtime session;
- audio streaming;
- barge-in;
- Conversation remains authoritative.

---

# 22. Gate I4 — Sofia Can Act Safely

Requires:

```text
SA-B011
SA-B012
SA-B013
SA-B014
```

Success means:

- Tool registered;
- ToolCall validated;
- PolicyDecision required;
- confirmation works;
- Direct Invocation works;
- artifact references work.

---

# 23. Gate I5 — Sofia Can Work

Requires:

```text
SA-B015
SA-B016
SA-B017
```

Success means:

- durable Tasks;
- AgentRun;
- subprocess execution;
- cancellation;
- authority narrowing.

---

# 24. Gate I6 — Sofia Can Remember

Requires:

```text
SA-B018
SA-B019
SA-B020
```

Success means:

```text
Conversation
→ MemoryCandidate
→ persistent memory
→ recall
→ Context Builder
```

using real Sofias Memory.

---

# 25. Gate I7 — Sofia Can React

Requires:

```text
SA-B021
SA-B022
SA-B023
```

Success means:

- Event Runtime functional;
- reminder survives restart;
- Core can notify without active Conversation.

---

# 26. Gate I8 — Sofia Can Use the Computer

Requires:

```text
SA-B024
SA-B025
SA-B026
SA-B027
SA-B028
```

Success means useful local capabilities exist without requiring full desktop automation.

---

# 27. Gate I9 — Sofia Can Delegate

Requires:

```text
SA-B029
```

Success means one real specialized Agent completes work through the approved root orchestration model.

---

# 28. Gate I10 — Sofia Is Traceable

Requires:

```text
SA-B030
```

Success means user/developer can answer:

> Why did Sofia do this?

using structured evidence.

---

# 29. Gate I11 — Product Interface

Requires:

```text
SA-B031
```

Success means Desktop Client exposes the completed runtime without owning domain logic.

---

# 30. Gate I12 — Recovery Validated

Requires:

```text
SA-B033
```

Success means crash/restart does not silently duplicate critical side effects or lose durable Tasks.

---

# 31. Gate I13 — MVP Ready

Requires:

```text
SA-B034
```

All PRD MVP scenarios pass.

At this point:

```text
Gate 4 — Implementation Readiness
```

will already have been passed earlier, and this gate represents:

```text
MVP RELEASE READINESS
```

---

# 32. Gate 4 — Implementation Readiness

Given the current state:

```text
PRD approved
Architecture Gate closed
Technical Backlog Map defined
```

Gate 4 should not yet be marked CLOSED.

Before implementation starts, the following are still required:

1. approve this Technical Backlog Map;
2. choose the first implementation slice;
3. materialize detailed backlog for SA-B001 through the next Implementation Gate;
4. define coding/testing conventions;
5. authorize creation of the project skeleton.

After those items:

```text
Gate 4 — Implementation Readiness = CLOSED
```

---

# 33. Recommended First Delivery Slice

Do not attempt SA-B001 through SA-B034 at once.

The first delivery slice should be:

```text
SA-B001 Project Foundation
SA-B002 Core Lifecycle
SA-B003 Operational Persistence
SA-B004 Local Client Boundary
SA-B005 Runtime Health & Configuration
SA-B006 Secret Service
```

This closes:

```text
Gate I1 — Core Alive
```

before introducing an AI provider.

That is deliberate.

If Sofia cannot reliably:

- start;
- stop;
- persist;
- authenticate a local client;
- report health;
- protect secrets;

adding an LLM first only hides architectural problems behind a chatbot demo.

---

# 34. Second Delivery Slice

After Core Alive:

```text
SA-B007 AI Provider Framework
SA-B008 Conversation Runtime
SA-B010 Context Builder
```

closing:

```text
Gate I2 — Sofia Can Converse
```

Only then:

```text
SA-B009 Realtime Voice
```

closing:

```text
Gate I3 — Sofia Can Speak
```

---

# 35. Third Delivery Slice

Next:

```text
SA-B011 Policy Engine
SA-B012 Grants & Delegations
SA-B013 Tool Runtime
SA-B014 Artifact Service
```

closing:

```text
Gate I4 — Sofia Can Act Safely
```

Nesse ponto teremos o primeiro kernel realmente interessante:

```text
Conversation
     ↓
AI
     ↓
ToolCall
     ↓
Policy
     ↓
Tool
     ↓
Result
```

---

# 36. Backlog Principle for Epics

Cada Epic deverá ser posteriormente materializado em documento próprio contendo:

```text
Goal
Context
In Scope
Out of Scope
Architecture Constraints
Implementation Tasks
Data Model
Interfaces
Tests
Failure Cases
Acceptance Criteria
Dependencies
Gate
```

Não criaremos agora 34 documentos detalhados de uma só vez.

Eles serão materializados conforme se aproximarem da implementação.

---

# 37. No Premature Backlog Expansion

Não detalhar ainda:

```text
SA-B026 Web Search
SA-B028 Vision
SA-B032 Plugins
```

em dezenas de subtasks se estamos implementando SA-B001.

Isso evita backlog especulativo que envelhece antes de ser usado.

---

# 38. Backlog Change Policy

Um Epic poderá evoluir durante implementação desde que:

- não viole PRD;
- não viole ADR;
- não altere architectural invariant.

Se mudança necessária violar arquitetura:

```text
stop
↓
ADR review
↓
explicit amendment/replacement
```

Não esconder mudança arquitetural dentro de ticket técnico.

---

# 39. Post-MVP Map

Após o MVP, os próximos capability tracks poderão incluir:

```text
Advanced Development Agent
Advanced Research Agent
Browser Automation
Continuous Screen Awareness
Camera
Email
Calendar
GitHub deep integration
Document Productivity
Smart Home
Remote Companion
Messaging integrations
Plugin distribution
Wake Word
Continuous Listening
Procedural Skill Learning
Advanced Proactivity
```

A ordem será decidida após feedback real do MVP.

---

# 40. Final Backlog Baseline

A implementação do Sofia's Assistant seguirá a sequência conceitual:

```text
Foundation
    ↓
Core
    ↓
Persistence
    ↓
Client Boundary
    ↓
AI
    ↓
Conversation
    ↓
Realtime Voice
    ↓
Policy
    ↓
Tools
    ↓
Tasks
    ↓
Agents
    ↓
Memory
    ↓
Events
    ↓
Capabilities
    ↓
Desktop Client
    ↓
Recovery
    ↓
MVP
```

A arquitetura será validada progressivamente através de Implementation Gates, evitando construir grandes quantidades de infraestrutura sem um fluxo funcional correspondente.