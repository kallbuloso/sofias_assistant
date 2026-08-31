# Sofia's Assistant — ADR Candidate Map

**Status:** Baseline para materialização  
**Origem:** PRD v0.1 aprovado  
**Objetivo:** identificar somente as decisões arquiteturais que precisam ser preservadas formalmente antes do Technical Backlog.

---

# 1. Critério para criação de ADR

Uma decisão deverá virar ADR quando:

1. alterar significativamente a arquitetura ou seus boundaries;
2. possuir alternativas tecnicamente plausíveis;
3. tiver consequências difíceis ou caras de reverter;
4. afetar vários módulos;
5. precisar permanecer compreensível no futuro sem depender do histórico de discussão.

Decisões locais de implementação não deverão gerar ADR.

---

# 2. ADRs Mandatórios

## ADR-0001 — Runtime Topology and Core/Client Boundary

### Questão

Como Sofia Core, Desktop UI e processos auxiliares serão organizados?

### Deve consolidar

- modular monolith inicial;
- Core persistente em background;
- UI como client;
- Core funcionando sem interface gráfica;
- interface formal entre Core e clients;
- processos auxiliares somente quando houver necessidade de isolamento.

### Dependências

Nenhuma.

### Impacta

Todo o projeto.

---

## ADR-0002 — Operational Persistence Architecture

### Questão

Onde o Sofia's Assistant persiste seu estado operacional?

### Deve consolidar

- storage independente do Sofias Memory;
- SQLite como banco inicial;
- migrations obrigatórias;
- repositories/contracts;
- separação entre estado operacional e memória cognitiva;
- recovery após restart.

### Dependências

ADR-0001.

### Impacta

Tasks, conversations, permissions, delegations, events, scheduler, audit e settings.

---

## ADR-0003 — Internal Event and Scheduler Architecture

### Questão

Como eventos, proatividade, reminders e scheduling serão representados?

### Deve consolidar

- Event Bus interno;
- Domain Events;
- External Events;
- persistência seletiva;
- Event Sources extensíveis;
- Scheduler central;
- jobs persistentes;
- Scheduler produz eventos, não side effects diretamente.

### Dependências

ADR-0001, ADR-0002.

---

## ADR-0004 — AI Provider Abstraction and Capability Routing

### Questão

Como diferentes modelos/providers participam do runtime sem contaminar o domínio?

### Deve consolidar

- provider-agnostic Core;
- Provider Adapters;
- Model Registry;
- capability-based routing;
- providers diferentes na mesma sessão;
- fallback conforme policy;
- data-locality requirements;
- normalização de tool calls;
- normalização de structured outputs;
- SecretStore boundary.

### Dependências

ADR-0001.

---

## ADR-0005 — Conversation, Realtime Voice and Context Ownership

### Questão

Quem é autoridade sobre conversation lifecycle e contexto?

### Deve consolidar

- texto e voz na mesma conversa;
- Sofia como identidade independente do provider;
- realtime voice como capability nativa;
- streaming;
- barge-in;
- provider-native session como otimização, nunca autoridade;
- Context Builder;
- contexto como projeção, não transcript bruto;
- Working Memory.

### Dependências

ADR-0004.

---

## ADR-0006 — Deterministic Authorization Boundary

### Questão

Quem pode autorizar uma ação?

### Decisão central

> LLMs podem propor e interpretar ações, mas nunca conceder autoridade.

### Deve consolidar

- PolicyEngine obrigatório;
- reads também podem ser protegidos;
- decisão determinística;
- ALLOW;
- DENY;
- REQUIRE_CONFIRMATION;
- REQUIRE_ELEVATION;
- risk semantics sem congelar prematuramente quantidade de níveis;
- separação entre interpretação e autorização.

### Dependências

ADR-0001.

### Observação

Este é um dos ADRs mais importantes do projeto.

---

## ADR-0007 — Grants, Delegations and Authority Narrowing

### Questão

Como autoridade persistente é concedida, limitada e delegada?

### Deve consolidar

- Permission Grants;
- Delegations;
- objetivo separado de autoridade;
- resource scopes;
- temporal scopes;
- revogação;
- subjects;
- least privilege;
- Agent permissions ⊆ Delegation ⊆ Root authorization;
- nenhuma elevação autônoma de permissões.

### Dependências

ADR-0006, ADR-0002.

---

## ADR-0008 — Tool Contract, Registry and Execution Boundary

### Questão

O que é uma Tool e como ela é executada?

### Deve consolidar

- ToolSpec;
- Tool handler separado do contrato;
- schemas;
- capabilities;
- permissions;
- risk semantics;
- side effects;
- timeout;
- idempotency;
- execution mode;
- ToolResult normalizado;
- Tool Registry;
- provider-independent ToolCall;
- toda execução protegida passa pelo PolicyEngine.

### Dependências

ADR-0004, ADR-0006.

---

## ADR-0009 — Task, AgentRun and Root Orchestration Model

### Questão

Como trabalho complexo é representado e como sub-agents participam?

### Deve consolidar

- Task como unidade de trabalho;
- AgentRun como estratégia de execução;
- Task podendo usar Tool, Workflow ou Agent;
- somente Sofia/root instancia agents;
- sub-agent pode solicitar nova delegação, mas não criá-la diretamente;
- todos os agents respondem à root;
- context isolation;
- Tool subset;
- permission narrowing;
- workspace explícito;
- mínimo mecanismo necessário para cada tarefa.

### Dependências

ADR-0007, ADR-0008, ADR-0002.

---

## ADR-0010 — Task Lifecycle, Cancellation and Recovery

### Questão

Como Tasks sobrevivem a falhas, reinícios e cancelamentos?

### Deve consolidar

- persistence;
- estados;
- waiting states;
- cancellation cooperativa;
- recovery;
- retry;
- resume;
- operações com side effects desconhecidos após crash;
- reconciliação antes de repetir ação quando necessário.

### Dependências

ADR-0002, ADR-0009.

---

## ADR-0011 — Sofia's Memory Integration Boundary

### Questão

Qual é a fronteira entre memória operacional e memória cognitiva persistente?

### Deve consolidar

- Sofias Memory como autoridade de Long-Term Cognitive Memory;
- Assistant DB como autoridade operacional;
- integração por contrato/API;
- nenhuma dependência direta do banco ou implementação interna do Sofias Memory;
- Memory Orchestrator no Assistant;
- retrieval solicitado pelo Assistant;
- Context Builder permanece no Assistant.

### Dependências

ADR-0002, ADR-0005.

---

## ADR-0012 — Cognitive Memory Model and Lifecycle

### Questão

Como memórias pessoais são classificadas, validadas e evoluem?

### Deve consolidar

- PROFILE;
- SEMANTIC;
- EPISODIC;
- PROCEDURAL;
- Memory Candidate;
- provenance;
- confidence;
- temporal validity;
- contradiction;
- supersession;
- importance;
- consolidation;
- lifecycle;
- Assistant-generated content não vira fato automaticamente;
- confirmation de memórias sensíveis quando aplicável;
- skills como procedural memory.

### Dependências

ADR-0011.

### Consequência

Este ADR provavelmente gerará requisitos de evolução no próprio Sofias Memory.

---

## ADR-0013 — Execution Isolation and Sandbox Model

### Questão

Onde e sob quais condições código/tools/plugins podem executar?

### Deve consolidar

- IN_PROCESS;
- SUBPROCESS;
- SANDBOX;
- host execution quando autorizado;
- código desconhecido preferencialmente isolado;
- workspace;
- timeout;
- filesystem boundaries;
- crash isolation;
- shell como capability privilegiada;
- política para instalação de dependências e execução de código gerado.

### Dependências

ADR-0006, ADR-0008.

---

## ADR-0014 — Plugin and Extensibility Architecture

### Questão

Como capacidades externas são adicionadas sem inflar o Core?

### Deve consolidar

Plugin capaz de registrar:

- Tools;
- Integrations;
- Event Sources;
- Agent Definitions;
- configuration schema;
- required permissions.

Também:

- manifest;
- version;
- enable/disable;
- collision handling;
- validation;
- lifecycle;
- process isolation quando necessário.

### Dependências

ADR-0003, ADR-0008, ADR-0009, ADR-0013.

---

## ADR-0015 — Audit and Execution Traceability

### Questão

Como reconstruir por que uma ação ocorreu?

### Deve consolidar

correlação entre:

- request/event;
- Task;
- Delegation;
- Grant;
- AgentRun;
- ToolCall;
- PolicyDecision;
- effects;
- result.

Também deverá separar:

- audit;
- logs;
- metrics/debugging.

### Dependências

ADR-0002, ADR-0006, ADR-0008, ADR-0009.

---

# 3. ADRs que não devem existir separadamente

Alguns candidatos anteriores deverão ser absorvidos pelos ADRs acima.

## Não criar ADR separado para SQLite

Pertence ao ADR-0002.

## Não criar ADR separado para Realtime Provider

Pertence aos ADR-0004 e ADR-0005.

## Não criar ADR separado para Context Builder

Pertence ao ADR-0005.

## Não criar ADR separado para Event Source

Pertence ao ADR-0003.

## Não criar ADR separado para Scheduler

Pertence ao ADR-0003.

## Não criar ADR separado para ToolResult

Pertence ao ADR-0008.

## Não criar ADR separado para Agent Registry

Pertence ao ADR-0009.

## Não criar ADR separado para Permission Risk Levels

Pertence ao ADR-0006.

## Não criar ADR separado para Working Memory

Pertence aos ADR-0005 e ADR-0011.

## Não criar ADR separado para Secrets

SecretStore boundary deverá inicialmente fazer parte do ADR-0004.

Uma decisão futura sobre implementação concreta de secrets só deverá gerar ADR caso existam alternativas relevantes com consequências arquiteturais.

---

# 4. Ordem recomendada de materialização

Os ADRs não devem ser escritos na sequência numérica por conveniência.

A sequência recomendada é:

```text
ADR-0001 Runtime topology
        ↓
ADR-0002 Operational persistence
        ↓
ADR-0006 Authorization boundary
        ↓
ADR-0007 Grants & delegations
        ↓
ADR-0004 Provider architecture
        ↓
ADR-0005 Conversation & context
        ↓
ADR-0008 Tool runtime
        ↓
ADR-0009 Task & AgentRun
        ↓
ADR-0010 Recovery
        ↓
ADR-0003 Events & Scheduler
        ↓
ADR-0011 Memory integration
        ↓
ADR-0012 Cognitive memory
        ↓
ADR-0013 Sandbox
        ↓
ADR-0014 Plugins
        ↓
ADR-0015 Audit
```

Alguns poderão ser desenvolvidos em paralelo após os foundations.

---

# 5. ADRs necessários antes do primeiro Technical Backlog executável

Nem todos os 15 precisam estar completamente materializados antes de iniciarmos qualquer backlog.

O primeiro Implementation Readiness Gate deverá exigir, no mínimo:

### Foundation Set

- ADR-0001 — Runtime topology
- ADR-0002 — Operational persistence
- ADR-0004 — Provider architecture
- ADR-0005 — Conversation & context
- ADR-0006 — Authorization boundary
- ADR-0007 — Grants & delegations
- ADR-0008 — Tool runtime
- ADR-0009 — Task & AgentRun
- ADR-0011 — Memory integration

### Pode amadurecer logo depois

- ADR-0003 — Events/Scheduler
- ADR-0010 — Recovery
- ADR-0012 — Cognitive memory
- ADR-0013 — Sandbox
- ADR-0014 — Plugins
- ADR-0015 — Audit

Isso não autoriza ignorar os últimos seis.

Significa apenas que eles podem ser materializados junto dos respectivos Technical Backlogs, desde que nenhuma implementação viole os princípios já aprovados no PRD.

---

# 6. Technical Backlog derivado

Após os ADRs fundamentais, o backlog poderá ser dividido inicialmente em épicos semelhantes a:

```text
SA-B001 Project Foundation
SA-B002 Core Lifecycle
SA-B003 Operational Persistence
SA-B004 Local Core API
SA-B005 Provider Framework
SA-B006 Conversation Runtime
SA-B007 Realtime Voice
SA-B008 Context Builder
SA-B009 Policy Engine
SA-B010 Grants & Delegations
SA-B011 Tool Runtime
SA-B012 Task Runtime
SA-B013 Sofias Memory Integration
SA-B014 Event Runtime
SA-B015 Scheduler & Reminders
SA-B016 Filesystem Tools
SA-B017 Shell Execution
SA-B018 Web Search & Reading
SA-B019 Desktop Basics
SA-B020 Screenshot Vision
SA-B021 Experimental Agent
SA-B022 Desktop Client
SA-B023 Recovery
SA-B024 Audit & Observability
```

Esses identificadores são provisórios.

O Technical Backlog só deverá ser congelado depois dos ADRs correspondentes.

---

# 7. Architecture Gate

O **Gate 2 — Architecture Definition** será considerado fechado quando:

1. os ADRs do Foundation Set forem aprovados;
2. conflitos entre ADRs forem resolvidos;
3. interfaces arquiteturais principais estiverem definidas;
4. nenhuma questão estrutural bloquear a decomposição do MVP;
5. o Technical Backlog puder ser escrito sem inventar arquitetura durante a implementação.

Somente então avançaremos para:

```text
Gate 3 refinement
      ↓
Technical Backlog
      ↓
Implementation Readiness
      ↓
Project Skeleton
```