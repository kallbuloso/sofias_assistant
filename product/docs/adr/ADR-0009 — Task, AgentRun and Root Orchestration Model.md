# ADR-0009 — Task, AgentRun and Root Orchestration Model

**Status:** Accepted  
**Project:** Sofia's Assistant  
**Decision date:** 2026-08-31  
**Scope:** Task model, AgentRun model, root orchestration, delegation, context isolation and execution strategy selection

---

# 1. Context

O Sofia's Assistant deverá ser capaz de executar desde operações simples até objetivos compostos.

Exemplos simples:

- abrir uma aplicação;
- ler um arquivo;
- consultar janela ativa;
- criar reminder.

Exemplos compostos:

- pesquisar múltiplas fontes;
- analisar um repositório;
- executar testes;
- modificar código;
- produzir um relatório;
- acompanhar uma Delegation ao longo do tempo.

Nem toda operação complexa exige Agent.

Também não é desejável transformar cada operação em comportamento agentic.

O projeto adotou o princípio:

> **Use the least complex execution mechanism capable of solving the task.**

Além disso, ficou decidido que:

- Sofia/root é a única autoridade de coordenação;
- apenas Sofia/root pode instanciar sub-agents;
- todos os Agents respondem à Sofia/root;
- Agents recebem contexto reduzido;
- Agents recebem authority reduzida;
- Agents utilizam subset explícito de Tools;
- um Agent não pode ampliar sua própria autoridade;
- um Agent pode solicitar outra especialização, mas não instanciá-la diretamente.

Esses princípios exigem separar claramente:

```text
Task
```

de:

```text
AgentRun
```

---

# 2. Decision

O Sofia's Assistant adotará `Task` como unidade principal de trabalho persistente.

`AgentRun` será uma estratégia possível para executar uma Task.

Conceitualmente:

```text
Task
 ├── Direct Tool
 ├── Workflow
 └── AgentRun
```

Portanto:

```text
Task ≠ AgentRun
```

e:

> Nem toda Task utiliza Agent.

---

# 3. Fundamental Rule

A regra central será:

> **Work is represented as Task. Agents are execution strategies.**

Isso impede que Agent se torne a unidade universal do runtime.

---

# 4. Task

Uma `Task` representa trabalho solicitado, delegado ou gerado pelo runtime.

Ela poderá ter origem em:

- input explícito do usuário;
- Delegation;
- Event;
- Scheduler;
- outra Task;
- Sofia/root;
- future automation.

Conceitualmente:

```text
Task
├── id
├── objective
├── origin
├── status
├── priority
├── conversation_id
├── delegation_id
├── parent_task_id
├── execution_strategy
├── created_at
├── started_at
├── finished_at
└── metadata
```

O schema definitivo será definido posteriormente.

---

# 5. Task Is Stable

Task deverá possuir identidade persistente independentemente da estratégia de execução.

Uma Task poderá inicialmente tentar:

```text
AgentRun A
```

e posteriormente:

```text
AgentRun B
```

sem deixar de ser a mesma unidade de trabalho.

---

# 6. Task Origins

Origin deverá permitir identificar por que a Task existe.

Exemplos conceituais:

```text
USER_REQUEST
DELEGATION
SCHEDULE
EXTERNAL_EVENT
DOMAIN_EVENT
ROOT_GENERATED
CHILD_TASK
```

A taxonomia final poderá mudar.

---

# 7. Task Objective

Objective descreve o resultado desejado.

Exemplo:

```text
"Compare três bibliotecas de automação de browser e recomende uma."
```

Objective não define automaticamente:

- Tools;
- permissions;
- Agent;
- provider;
- workflow.

Esses elementos pertencem ao planejamento/orchestration.

---

# 8. Direct Tool Execution

Tasks simples deverão preferir execução direta.

Exemplo:

```text
User:
"Abra o VS Code."

Task
   ↓
Tool: desktop.open_app
```

Não deverá ser necessário:

```text
Planner
   ↓
Desktop Agent
   ↓
Tool selection
```

quando a operação já é clara.

---

# 9. Workflow Execution

Uma Task poderá utilizar workflow determinístico quando múltiplas etapas conhecidas forem necessárias.

Exemplo:

```text
backup project
   ↓
validate directory
   ↓
create archive
   ↓
verify archive
```

Se a sequência for conhecida, não há motivo obrigatório para Agent.

---

# 10. Agent Execution

AgentRun será utilizado quando o objetivo exigir capacidade significativa de:

- decidir próximos passos;
- selecionar Tools;
- reagir a resultados;
- pesquisar;
- decompor problema;
- adaptar estratégia;
- lidar com incerteza.

---

# 11. Agent Definition

Um Agent será definido por metadata explícita.

Conceitualmente:

```text
AgentDefinition
├── id
├── name
├── description
├── capabilities
├── allowed_tool_classes
├── context_policy
├── provider_requirements
├── default_limits
├── execution_policy
└── version
```

---

# 12. AgentRun

`AgentRun` representa uma instância concreta de Agent executando trabalho.

Conceitualmente:

```text
AgentRun
├── id
├── task_id
├── agent_definition_id
├── objective
├── status
├── delegated_context
├── authority_scope
├── tool_subset
├── workspace
├── provider_requirements
├── created_at
├── started_at
├── finished_at
└── result
```

---

# 13. Root Orchestrator

Sofia/root será a única autoridade responsável por:

- criar AgentRuns;
- escolher Agent;
- aprovar delegação entre especializações;
- construir delegated context;
- determinar Tool subset;
- determinar authority scope;
- receber resultados;
- integrar resultados ao trabalho principal.

---

# 14. Root Is Not Necessarily an LLM Call

`Sofia/root` representa papel arquitetural de coordenação.

Não significa que toda decisão precise ser produzida por um único prompt/LLM.

Root orchestration poderá utilizar:

- regras;
- routing;
- planner;
- provider;
- policy;
- Task state.

A autoridade continua no runtime.

---

# 15. Agent Cannot Instantiate Agent

Um Agent nunca criará outro Agent diretamente.

Proibido:

```text
Development Agent
    ↓
spawn Research Agent
```

O fluxo será:

```text
Development Agent
    ↓
Delegation Request
    ↓
Sofia/root
    ↓
authorization/context evaluation
    ↓
Research AgentRun
```

---

# 16. Flat Agent Hierarchy

Do ponto de vista de autoridade, AgentRuns formarão hierarquia coordenada pela root.

Mesmo quando Agent B auxilia Agent A:

```text
        Sofia/root
        /        \
 AgentRun A    AgentRun B
```

Agent B não será authority child direto de A.

---

# 17. Logical Dependency Between AgentRuns

Apesar da autoridade permanecer flat, poderá existir relação operacional:

```text
AgentRun B
requested_for = AgentRun A
```

ou equivalente.

Isso permite:

- audit;
- result routing;
- dependency tracking.

---

# 18. Agent Delegation Request

Agent poderá emitir pedido estruturado.

Exemplo:

```text
DelegationRequest
├── requesting_agent_run
├── capability_needed
├── objective
├── relevant_context
├── requested_resources
└── reason
```

Root decide se:

- resolve diretamente;
- cria outro AgentRun;
- nega;
- solicita confirmação;
- modifica scope.

---

# 19. Agent Context Isolation

Agents não receberão Conversation inteira automaticamente.

Root construirá `DelegatedContext`.

Esse contexto poderá incluir:

- objective;
- relevant facts;
- Task state;
- selected memory;
- selected artifacts;
- ToolResults;
- workspace;
- limits.

---

# 20. Delegated Context Is a Projection

Assim como Context Builder cria contexto para providers, root criará contexto específico para AgentRun.

Regra:

```text
Root context
   ↓
projection
   ↓
Agent context
```

não:

```text
copy everything
```

---

# 21. Memory Isolation

Agent poderá receber apenas memory scopes relevantes.

Exemplo:

```text
Development Agent
memory:
  project-sofias-assistant
```

sem acesso automático a:

```text
personal
finance
other projects
```

---

# 22. Tool Subset

Todo AgentRun possuirá subset explícito de Tools.

Exemplo:

```text
Research Agent
├── web.search
├── web.read
├── memory.read(project)
└── artifact.write(report)
```

Tool registrada globalmente não significa Tool disponível para todo Agent.

---

# 23. Authority Scope

AgentRun possuirá authority derivada.

Invariante:

```text
AgentRun authority
    ⊆ Delegation authority
    ⊆ Root effective authority
```

---

# 24. Workspace

Quando aplicável, AgentRun deverá possuir workspace/resource boundary explícito.

Exemplo:

```text
Development AgentRun
workspace:
  D:\Projects\sofias_assistant
```

---

# 25. Workspace Does Not Automatically Grant Authority

Definir workspace não significa conceder:

```text
filesystem.write
shell.execute
```

Essas capabilities continuam dependentes de Grants/Delegation/Policy.

Workspace restringe onde a authority pode ser aplicada.

---

# 26. Agent Provider Selection

AgentDefinition poderá declarar requirements de provider.

Exemplo:

```text
reasoning = required
tool_calling = required
vision = optional
```

AI Router escolherá provider/model conforme ADR-0004.

Agent não deverá hardcode provider.

---

# 27. Agent Identity vs Sofia Identity

Agents são especializações internas.

Eles não substituirão a identidade da Sofia perante o usuário como regra.

Usuário continua interagindo com Sofia.

Sofia poderá informar:

> “Deleguei essa análise ao meu agente de pesquisa.”

Mas não é necessário simular múltiplas personas independentes.

---

# 28. Agent Persona

Agent poderá possuir instruções especializadas.

Exemplo:

```text
"You specialize in repository analysis."
```

Isso é execution behavior, não nova authority ou identidade principal.

---

# 29. Agent Registry

Sofia Core possuirá `Agent Registry`.

Responsabilidades:

- registrar AgentDefinitions;
- impedir collisions;
- listar Agents disponíveis;
- validar requirements;
- controlar enable/disable;
- resolver definição para criação de AgentRun.

---

# 30. Dynamic Agent Registration

Plugins poderão futuramente registrar AgentDefinitions.

Esses Agents continuarão sujeitos a:

- Agent Registry;
- Policy;
- Tool subsets;
- authority narrowing;
- context isolation.

---

# 31. Agent Selection

Root poderá selecionar Agent com base em:

- objective;
- capabilities;
- availability;
- Task type;
- Tool requirements;
- provider requirements;
- user preference.

O algoritmo concreto será definido depois.

---

# 32. Avoid Agent Overuse

O runtime deverá evitar uso de Agent quando execução determinística mais simples for suficiente.

Exemplo inadequado:

```text
"What time is it?"
   ↓
Planning Agent
```

Exemplo adequado:

```text
"What time is it?"
   ↓
utility/tool
```

---

# 33. Planner

Planner poderá existir como componente do runtime.

Ele não será automaticamente um Agent persistente separado.

Planner poderá ajudar root a decidir:

- decomposição;
- execution strategy;
- Tool sequence;
- Agent need.

---

# 34. Plan

Tasks complexas poderão possuir Plan.

Conceitualmente:

```text
Plan
├── steps
├── dependencies
├── expected_tools
├── expected_outputs
└── status
```

Este ADR não congela Plan como entidade persistente obrigatória.

---

# 35. Plan Validation

Qualquer Plan produzido por LLM deverá ser validado antes de execução.

Validation poderá verificar:

- Tool existence;
- capability availability;
- resource scope;
- authority;
- unsupported dependencies;
- circular dependencies;
- excessive complexity.

---

# 36. Plan Is Not Authority

Um Plan dizendo:

```text
step 3: delete file
```

não concede autorização.

Cada execução protegida continua passando pelo PolicyEngine.

---

# 37. Agent Tool Loop

AgentRun poderá executar ciclo semelhante a:

```text
observe
  ↓
reason
  ↓
request Tool
  ↓
Tool Runtime
  ↓
result
  ↓
reason
```

sempre sob controle do runtime.

---

# 38. Maximum Steps / Limits

AgentRun deverá possuir limites configuráveis.

Exemplos:

- max steps;
- max duration;
- max ToolCalls;
- max tokens/cost;
- max retries.

Isso evita loops indefinidos.

---

# 39. Agent Cancellation

AgentRun deverá respeitar cancellation da Task.

Se Task entrar em cancellation:

```text
AgentRun
   ↓
stop planning new actions
   ↓
cancel safe in-flight operations when possible
```

Semântica detalhada será definida no ADR-0010.

---

# 40. Agent Failure

Falha de AgentRun não significa necessariamente falha final da Task.

Root poderá:

- retry;
- escolher outro Agent;
- usar workflow;
- executar diretamente;
- solicitar usuário.

---

# 41. Agent Result

AgentRun deverá retornar resultado estruturado.

Conceitualmente:

```text
AgentRunResult
├── status
├── summary
├── artifacts
├── findings
├── unresolved_items
├── tool_usage
└── metadata
```

O schema final será definido posteriormente.

---

# 42. Result Handoff

Agent não conversa diretamente com usuário como authority final por padrão.

Resultado retorna à Sofia/root.

Root decide:

- responder;
- continuar Task;
- delegar nova operação;
- criar Memory Candidate;
- solicitar confirmação.

---

# 43. Direct User Interaction by Agent

Futuramente poderá haver casos onde Agent especializado participa diretamente de uma interface.

Isso exigirá decisão explícita.

Não será baseline do MVP.

---

# 44. Task Composition

Task poderá criar child Tasks quando trabalho precisar ser decomposto em unidades persistentes independentes.

Exemplo:

```text
Parent Task
├── research dependency options
├── run benchmark
└── summarize result
```

Nem toda etapa precisa virar child Task.

---

# 45. Child Task Authority

Child Task não herda authority irrestrita.

Sua authority será derivada do contexto da parent/Delegation.

---

# 46. Task Dependencies

Tasks poderão futuramente possuir dependências.

Exemplo:

```text
Task B waits for Task A
```

Isso permitirá workflows mais robustos.

A implementação concreta será posterior.

---

# 47. Task Priority

Tasks poderão possuir prioridade.

Exemplo conceitual:

```text
LOW
NORMAL
HIGH
URGENT
```

A taxonomia concreta não é congelada aqui.

---

# 48. Background Execution

Task poderá continuar executando sem Conversation ativa ou UI conectada.

Isso decorre do ADR-0001.

---

# 49. Conversation Is Not Task Runtime

Conversation poderá criar Task, mas não executá-la diretamente.

Exemplo:

```text
Conversation
   ↓
Task created
   ↓
Task Runtime
```

Isso permite continuar conversando enquanto trabalho ocorre.

---

# 50. Events Can Create Tasks

Event Runtime poderá criar Task através de root/orchestration.

Exemplo:

```text
ReminderDue
   ↓
Task/notification decision
```

Scheduler não executará Agent diretamente.

---

# 51. Delegation Can Create Tasks

Delegation persistente poderá originar novas Tasks ao longo do tempo.

Exemplo:

```text
"Monitor repository during this week."
```

Cada evento relevante poderá originar Task dentro da Delegation.

---

# 52. Task Execution Strategy

Task poderá registrar strategy selecionada:

```text
DIRECT_TOOL
WORKFLOW
AGENT
```

ou estrutura equivalente.

Strategy poderá mudar após failure/replan.

---

# 53. Strategy Selection Is Root Responsibility

Provider não determina sozinho:

```text
"use agent"
```

Root orchestration decide com base em:

- complexity;
- capabilities;
- determinism;
- cost;
- risk;
- context.

---

# 54. Least Complexity Rule

Baseline:

### Direct Tool

Use quando uma operação clara resolve o objetivo.

### Workflow

Use quando sequência é conhecida/determinística.

### Agent

Use quando decisões adaptativas são necessárias.

---

# 55. Examples

## Example A — Open app

```text
Task
objective = open VS Code

strategy = DIRECT_TOOL
```

---

## Example B — Reminder

```text
Task
objective = remind user tomorrow

strategy = deterministic scheduler workflow
```

---

## Example C — Research

```text
Task
objective = compare three technologies

strategy = AGENT
agent = ResearchAgent
```

---

## Example D — Development

```text
Task
objective = investigate failing test and propose fix

strategy = AGENT
agent = DevelopmentAgent
workspace = repository X
```

---

# 56. Experimental Agent in MVP

MVP deverá possuir ao menos um Agent experimental.

Seu objetivo principal será validar:

- Agent Registry;
- AgentRun persistence;
- root-only instantiation;
- context isolation;
- Tool subset;
- authority narrowing;
- provider routing;
- result handoff.

A escolha específica do primeiro Agent será definida no Technical Backlog.

---

# 57. Agent Definition Persistence

AgentDefinitions built-in poderão inicialmente vir de configuração/código versionado.

AgentRuns são estado operacional persistente.

Future plugin-provided definitions poderão exigir metadata persistente.

---

# 58. Agent Version

AgentRun deverá conseguir identificar qual versão de AgentDefinition executou.

Isso ajuda:

- audit;
- reproducibility;
- debugging.

---

# 59. Prompt Versioning

Prompts/instructions relevantes de Agent poderão possuir version identifier.

Não é necessário armazenar prompt integral em toda execução, desde que seja possível identificar a versão correspondente quando necessário.

---

# 60. Agent Memory

Agents não terão long-term memory própria independente por padrão.

Eles utilizarão:

```text
Sofias Memory
```

através dos scopes fornecidos pela root.

Isso evita silos cognitivos por Agent.

---

# 61. Agent Working State

AgentRun poderá possuir Working State temporário.

Esse estado pode ser persistido operacionalmente quando necessário para recovery.

Não é Long-Term Cognitive Memory.

---

# 62. Agent Learning

Agent poderá futuramente produzir Memory Candidates ou Skill Candidates.

Esses candidates deverão passar pelos mecanismos normais de memória/procedural memory.

Agent não grava fatos authoritative diretamente.

---

# 63. Agent-created Skills

Futuramente:

```text
successful repeated workflow
   ↓
Skill Candidate
   ↓
validation
   ↓
Procedural Memory
```

Agent não deverá auto-instalar capability persistente sem controle do runtime/usuário.

---

# 64. Agent Resource Limits

AgentRun deverá permitir limites de:

- CPU/process;
- runtime;
- network;
- ToolCalls;
- workspace;
- provider usage.

Implementação detalhada poderá depender do sandbox.

---

# 65. Concurrency

Mais de uma Task e mais de um AgentRun poderão executar simultaneamente.

Concurrency deverá respeitar:

- resource locks;
- Task limits;
- provider quotas;
- workspace conflicts;
- user configuration.

---

# 66. Same Workspace Concurrency

Dois Agents modificando o mesmo workspace simultaneamente poderão causar conflito.

Runtime deverá permitir política de exclusão/coordenação.

A estratégia concreta será definida posteriormente.

---

# 67. Agent Communication

Agents não possuirão canal peer-to-peer irrestrito.

Comunicação ocorre através da root/runtime.

Isso preserva:

- audit;
- authority;
- context boundaries.

---

# 68. No Hidden Agent Swarms

Runtime não deverá criar AgentRuns invisíveis apenas porque modelo decidiu.

Toda criação deve ser representada operacionalmente.

Isso permite observar:

```text
which agents are running
why
for what Task
with which authority
```

---

# 69. User Visibility

UI deverá futuramente permitir visualizar:

- Task ativa;
- Agent responsável;
- status;
- progresso quando disponível;
- solicitações de confirmação;
- resultados.

Detalhes de UX pertencem ao backlog.

---

# 70. Agent Availability

Agent poderá estar:

```text
enabled
disabled
unavailable
```

por falta de:

- Tool;
- provider;
- integration;
- platform support.

Root não deverá selecionar Agent indisponível.

---

# 71. Agent Fallback

Se Agent especializado estiver indisponível, root poderá:

- selecionar outro Agent compatível;
- usar workflow;
- usar direct tools;
- informar limitação.

Não haverá fallback que amplie authority.

---

# 72. Agent Errors

Errors deverão ser estruturados.

Exemplos:

```text
PLANNING_FAILED
TOOL_UNAVAILABLE
AUTHORIZATION_REQUIRED
CONTEXT_INSUFFICIENT
LIMIT_EXCEEDED
CANCELLED
```

A taxonomia final será definida depois.

---

# 73. Waiting for Permission

AgentRun poderá causar Task a entrar em estado de espera quando ToolCall exigir confirmação.

O Agent não deve continuar assumindo que ação ocorreu.

---

# 74. Waiting for External Result

Tasks poderão futuramente aguardar evento externo.

Exemplo:

```text
waiting for CI
```

Isso não é failure.

---

# 75. Recovery

AgentRun persistido como RUNNING no momento de crash não será automaticamente retomado como se nada tivesse ocorrido.

Task Runtime deverá aplicar recovery explícito conforme ADR-0010.

---

# 76. Replanning

Agent poderá solicitar replanning quando:

- Tool falhar;
- contexto mudar;
- authority for negada;
- dependency mudar.

Root mantém controle do lifecycle.

---

# 77. Root May Replan Without Agent

Replanning não precisa obrigatoriamente invocar novo Agent.

Pode ser regra/workflow dependendo da Task.

---

# 78. Auditability

Deverá ser possível correlacionar:

```text
Task
  ↓
execution strategy
  ↓
AgentRun
  ↓
ToolCalls
  ↓
PolicyDecisions
  ↓
ToolResults
```

---

# 79. Observability

Métricas poderão incluir:

- Task duration;
- AgentRun duration;
- ToolCalls per Agent;
- retries;
- replans;
- provider usage;
- success rate.

Isso poderá ajudar a identificar Agents ineficientes.

---

# 80. Testing

Deverão existir testes para:

- direct Tool strategy;
- Agent strategy;
- root-only Agent creation;
- delegated context;
- Tool subset;
- permission narrowing;
- Agent requesting another specialization;
- cancellation;
- Agent failure;
- result handoff;
- multiple AgentRuns.

---

# 81. Fake Agent

Runtime deverá permitir Agent fake/determinístico em testes.

Isso permite validar orchestration sem depender de LLM real.

---

# 82. Alternatives Considered

## Alternative A — Everything is an Agent

### Advantages

- modelo conceitualmente uniforme;
- fácil de vender como "multi-agent".

### Rejected because

- custo;
- latência;
- complexidade;
- baixa previsibilidade;
- overengineering;
- dificulta tarefas triviais.

---

## Alternative B — No Agents, only Tools

### Advantages

- runtime simples;
- altamente controlável.

### Rejected because

limita objetivos adaptativos complexos, especialmente:

- research;
- development;
- troubleshooting;
- multi-step reasoning.

---

## Alternative C — Agents freely spawn agents

### Advantages

- flexibilidade;
- emergent orchestration.

### Rejected because

- autoridade difícil de controlar;
- contexto espalhado;
- custos imprevisíveis;
- difícil auditabilidade;
- possibilidade de agent explosion.

---

## Alternative D — Agent owns Task

### Rejected because

Task lifecycle ficaria acoplado a uma estratégia específica e dificultaria retry/fallback entre mecanismos.

---

# 83. Consequences

## Positive

- Task permanece conceito simples e durável;
- Agents usados apenas quando necessários;
- root mantém autoridade;
- evita agent swarms;
- contexto permanece isolado;
- permissions são reduzidas;
- estratégias podem mudar;
- background execution fica consistente;
- audit melhora.

## Negative

- root orchestration torna-se componente importante;
- Task e AgentRun exigem state models distintos;
- delegated context precisa ser bem modelado;
- replan/fallback adicionam complexidade;
- concurrency entre Tasks/Agents exige controle.

Esses custos são considerados adequados.

---

# 84. Architectural Invariants

### INV-001

Task é unidade principal de trabalho.

### INV-002

Task e AgentRun são entidades distintas.

### INV-003

Nem toda Task exige Agent.

### INV-004

Somente Sofia/root cria AgentRun.

### INV-005

Agent não cria outro Agent diretamente.

### INV-006

Todos os AgentRuns respondem à root.

### INV-007

Agent recebe contexto reduzido.

### INV-008

Agent recebe Tool subset explícito.

### INV-009

Agent authority nunca excede Delegation/root authority.

### INV-010

Plan nunca constitui authority.

### INV-011

Agent result retorna à root.

### INV-012

Agents não mantêm long-term memory paralela independente por padrão.

### INV-013

Agent creation é estado operacional observável.

### INV-014

Use o mecanismo menos complexo capaz de resolver a Task.

---

# 85. Deferred Decisions

Serão definidos posteriormente:

- schemas concretos de Task e AgentRun;
- exact Task state machine;
- AgentRun state machine;
- planner architecture;
- plan schema;
- Agent Registry API;
- first experimental Agent;
- Agent selection algorithm;
- Agent limits;
- concurrency policy;
- workspace locking;
- child Task model;
- Task dependency graph;
- progress semantics;
- Agent prompt representation.

---

# 86. Decision Summary

Sofia's Assistant utilizará `Task` como unidade persistente de trabalho e `AgentRun` como uma das estratégias possíveis para executar esse trabalho.

Tasks poderão ser resolvidas por:

```text
Direct Tool
Workflow
AgentRun
```

Sofia/root será a única autoridade de coordenação e criação de sub-agents.

Agents operarão sob contexto, Tools, workspace e authority explicitamente reduzidos.

Um Agent poderá solicitar outra especialização, mas somente Sofia/root poderá decidir e instanciar outro AgentRun.

Essa arquitetura preserva autonomia e capacidade de resolução complexa sem transformar toda operação em um sistema multi-agent desnecessário.