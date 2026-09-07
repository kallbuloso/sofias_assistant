# ADR-0015 — Audit and Execution Traceability

**Status:** Accepted  
**Project:** Sofia's Assistant  
**Decision date:** 2026-08-31  
**Scope:** Audit trail, execution traceability, causality, correlation, retention, privacy and separation from logs/metrics

---

# 1. Context

O Sofia's Assistant poderá:

- executar Tools;
- agir proativamente;
- iniciar Tasks;
- instanciar Agents;
- utilizar Grants e Delegations;
- processar Events;
- acessar memória;
- modificar arquivos;
- executar shell;
- interagir com sistemas externos;
- operar em background sem Conversation ativa.

Nesse contexto, não é suficiente possuir apenas logs de aplicação.

Será necessário conseguir responder perguntas como:

- Por que essa ação aconteceu?
- Qual Task originou a ação?
- Qual Event iniciou a Task?
- Qual Delegation estava ativa?
- Qual Grant autorizou a operação?
- Qual PolicyDecision foi aplicada?
- Qual AgentRun solicitou a Tool?
- Qual Tool executou?
- Quais recursos foram afetados?
- Qual resultado foi observado?
- Houve confirmação do usuário?
- Qual versão de Agent/Plugin/Tool estava ativa?
- A ação foi automática ou iniciada diretamente pelo usuário?

Isso exige uma trilha de causalidade estruturada.

---

# 2. Decision

O Sofia's Assistant possuirá um **Audit Trail estruturado e correlacionável**, separado conceitualmente de:

```text
application logs
metrics
debug traces
```

O Audit Trail registrará eventos relevantes de autoridade, decisão e execução.

Arquitetura conceitual:

```text
User / Event / Schedule
        │
        ▼
      Task
        │
        ├── Delegation
        ├── Grant
        ├── AgentRun
        │      │
        │      ▼
        │   ToolCall
        │      │
        ▼      ▼
   PolicyDecision
        │
        ▼
     Execution
        │
        ▼
     ToolResult
        │
        ▼
    Side Effects
```

Esses elementos deverão ser correlacionáveis posteriormente.

---

# 3. Fundamental Rule

A regra será:

> **Every consequential action should be explainable from persisted evidence.**

O sistema deverá conseguir explicar não apenas **o que fez**, mas também **por que estava autorizado a fazê-lo**.

---

# 4. Audit vs Logging

Audit e logging possuem objetivos diferentes.

## Logging

Serve para:

- debugging;
- diagnostics;
- errors;
- performance;
- internal development.

Exemplo:

```text
HTTP request completed in 127ms
```

## Audit

Serve para reconstruir:

- intenção;
- autoridade;
- decisão;
- execução;
- efeito.

Exemplo:

```text
ToolCall X modified file Y
because Task Z requested it
under Delegation D
authorized by Grant G
with PolicyDecision ALLOW
```

---

# 5. Audit vs Metrics

Metrics representam agregações.

Exemplos:

```text
tool executions per hour
task success rate
provider latency
```

Metrics não substituem Audit.

---

# 6. Audit Entry

Conceitualmente:

```text
AuditEntry
├── id
├── timestamp
├── event_type
├── actor
├── subject
├── action
├── resource
├── outcome
├── correlation
├── authority_context
├── execution_context
└── metadata
```

O schema final será definido posteriormente.

---

# 7. Correlation

Audit deverá permitir correlação com IDs como:

```text
conversation_id
turn_id
task_id
attempt_id
agent_run_id
tool_call_id
policy_decision_id
grant_id
delegation_id
confirmation_id
event_id
schedule_id
plugin_id
```

Nem todos estarão presentes em toda entrada.

---

# 8. Causality

Além de correlation, o sistema deverá preservar causalidade.

Exemplo:

```text
ExternalEvent
    ↓
TaskCreated
    ↓
AgentRunStarted
    ↓
ToolCallRequested
    ↓
PolicyDecision
    ↓
ToolExecuted
```

Isso permitirá construir execution traces.

---

# 9. Causation ID

Eventos relevantes poderão possuir:

```text
causation_id
```

ou mecanismo equivalente.

Isso ajuda responder:

> qual evento imediatamente causou este?

---

# 10. Correlation ID

Uma mesma operação distribuída por vários componentes poderá compartilhar:

```text
correlation_id
```

para reconstrução ponta a ponta.

---

# 11. Actor vs Subject

O Audit deverá distinguir quando possível:

```text
actor
```

de:

```text
subject
```

Exemplo:

```text
actor = Sofia/root
subject = AgentRun X
```

ou:

```text
actor = user
subject = Sofia/root
```

Isso melhora rastreabilidade de delegações.

---

# 12. User-initiated Action

Quando ação vier diretamente do usuário, Audit deverá preservar essa origem.

Exemplo:

```text
origin = USER_REQUEST
```

---

# 13. Event-initiated Action

Quando ação for proativa:

```text
origin = EXTERNAL_EVENT
```

ou equivalente.

Deverá ser possível identificar o Event que iniciou a cadeia.

---

# 14. Schedule-initiated Action

Reminders e schedules também deverão preservar origem.

Exemplo:

```text
ScheduleDue
   ↓
Task
```

---

# 15. Delegation Context

Quando Task executar sob Delegation, Audit deverá preservar referência à Delegation.

Isso permite responder:

> essa ação ocorreu por uma autorização delegada previamente?

---

# 16. Grant Context

Quando PolicyDecision utilizar Grant, Audit deverá preservar referência ao Grant relevante.

---

# 17. Authority Snapshot

Para ações sensíveis, poderá ser útil registrar snapshot resumido da authority efetiva.

Isso evita depender exclusivamente do estado atual de Grants após alterações futuras.

---

# 18. Grant Mutation Does Not Rewrite History

Se Grant for revogado amanhã, Audit de ação autorizada ontem continuará indicando que Grant era válido naquele momento.

---

# 19. PolicyDecision Audit

Toda PolicyDecision relevante deverá possuir identidade própria ou registro correlacionável.

Conceitualmente:

```text
PolicyDecision
├── id
├── decision
├── subject
├── capability
├── resource
├── matched_policy
├── matched_grants
├── constraints
├── reason
├── evaluated_at
└── policy_version
```

---

# 20. Policy Version

Audit deverá permitir identificar qual versão de Policy produziu a decisão.

Isso será importante quando regras mudarem.

---

# 21. Confirmation Audit

Quando usuário confirmar ação:

```text
ConfirmationRequest
    ↓
UserApproval
    ↓
Grant / authority
```

essa cadeia deverá ser auditável.

---

# 22. Confirmation Scope

Audit deverá preservar o que exatamente foi aprovado.

Não apenas:

```text
user said yes
```

mas o scope autorizado.

---

# 23. ToolCall Audit

ToolCall relevante deverá registrar:

- Tool name/version;
- requesting subject;
- input resumido/canonicalizado quando seguro;
- resource;
- PolicyDecision;
- execution mode;
- outcome.

---

# 24. Input Privacy

Tool arguments podem conter dados sensíveis.

Audit não deverá armazenar argumentos completos indiscriminadamente.

Deverá permitir:

- redaction;
- hashing;
- references;
- structured summaries.

---

# 25. ToolResult Audit

Result deverá permitir registrar:

- status;
- artifacts;
- side effects;
- error class;
- duration.

Conteúdo bruto do output não será obrigatório.

---

# 26. Side Effects

Ações com side effects deverão registrar efeitos observáveis quando possível.

Exemplo:

```text
modified:
  D:\Projects\x\file.py
```

ou:

```text
created remote issue #123
```

---

# 27. Unknown Side Effects

Quando não for possível determinar efeitos completos:

```text
side_effects = UNKNOWN_OR_PARTIAL
```

ou semântica equivalente deverá ser possível.

---

# 28. Shell Audit

Shell merece atenção especial.

Audit deverá preservar, quando seguro:

- executable;
- arguments redigidos;
- cwd;
- execution mode;
- exit code;
- timeout;
- affected artifacts conhecidos.

---

# 29. Command Redaction

Secrets em command line deverão ser redigidos.

Exemplo:

```text
--token ****
```

---

# 30. AgentRun Audit

AgentRun deverá registrar:

- AgentDefinition/version;
- Task;
- delegated context refs;
- authority scope;
- Tool subset;
- provider/model utilizado;
- result.

---

# 31. Agent Internal Reasoning

Private chain-of-thought não será requisito de Audit.

Audit deverá preservar decisões e ações observáveis, não raciocínio interno oculto do modelo.

---

# 32. Agent Plan

Quando Plan explícito for parte do runtime, sua versão/steps relevantes poderão ser auditados.

Isso é diferente de armazenar hidden reasoning.

---

# 33. Provider Audit

Provider usage poderá registrar:

- provider;
- model;
- request class;
- locality;
- usage metadata;
- result status.

Prompts completos não deverão ser persistidos indiscriminadamente.

---

# 34. Data Locality Audit

Quando dado sensível for enviado a provider cloud, Audit poderá registrar que uma operação `CLOUD_ALLOWED` ocorreu.

Isso ajuda verificar compliance com Policy.

---

# 35. Memory Audit

Operações cognitivas relevantes poderão registrar:

- memory read scope;
- memory write;
- MemoryCandidate;
- confirmation;
- supersession;
- Forget.

Conteúdo sensível integral não será necessário.

---

# 36. Memory Read Privacy

Audit de recall poderá registrar:

```text
memory_scope = project:sofias-assistant
items_returned = 5
```

sem persistir necessariamente o texto das cinco memories.

---

# 37. Plugin Audit

Ações originadas por Plugin deverão registrar `plugin_id` e versão quando relevante.

Isso permite identificar extensão responsável.

---

# 38. EventSource Audit

Event Source poderá registrar:

- enable/disable;
- startup failure;
- observed event identity;
- health transitions.

High-frequency events não precisarão todos virar AuditEntry.

---

# 39. Schedule Audit

Alterações relevantes em Schedules deverão ser auditáveis.

Exemplos:

- reminder created;
- schedule changed;
- schedule disabled;
- missed-run policy applied.

---

# 40. Task State Transitions

Transitions importantes de Task poderão ser auditadas.

Exemplo:

```text
QUEUED
→ RUNNING
→ WAITING_CONFIRMATION
→ RUNNING
→ SUCCEEDED
```

Não será necessário duplicar cada heartbeat interno.

---

# 41. Recovery Audit

Recovery deve produzir registro estruturado.

Exemplo:

```text
Task X found interrupted
ToolCall Y reconciled as completed
Task resumed from step 4
```

---

# 42. Retry Audit

Cada attempt deverá ser distinguível.

Audit deverá permitir responder:

- quantas tentativas ocorreram;
- por que houve retry;
- qual foi o resultado de cada attempt.

---

# 43. Cancellation Audit

Deverá ser possível saber:

- quem solicitou cancelamento;
- quando;
- quais operações já haviam ocorrido;
- se cancellation foi completa ou parcial.

---

# 44. Security-sensitive Events

Eventos como:

- Grant created;
- Grant revoked;
- Delegation created;
- Delegation revoked;
- Policy changed;
- Plugin enabled;
- Secret reference changed;

deverão ser considerados audit-relevant.

---

# 45. Secret Values

Audit nunca deverá armazenar secrets brutos.

Pode armazenar:

```text
secret_ref = github/default
```

mas não token.

---

# 46. Append-oriented Model

Audit deverá preferir modelo append-oriented.

Registros históricos não deverão ser silenciosamente reescritos para refletir estado atual.

---

# 47. Corrections

Se entrada de Audit precisar ser corrigida, preferir nova entrada de correção/relação.

Não editar histórico silenciosamente.

---

# 48. Immutable by Application Convention

O banco local não precisa necessariamente oferecer armazenamento criptograficamente imutável no MVP.

Mas aplicação deverá tratar Audit como histórico append-oriented.

---

# 49. Tamper Evidence

Futuramente poderá existir:

- hash chaining;
- signing;
- tamper evidence.

Não será requisito do MVP.

---

# 50. Audit Storage

Audit permanecerá no Operational Store do Sofia's Assistant.

Não será armazenado no Sofias Memory como memória cognitiva.

---

# 51. Audit Is Not Memory

O usuário pode desejar lembrar:

> “Ontem fizemos deploy.”

Isso poderá gerar Episodic Memory.

Mas Audit de execução do deploy é outro domínio.

---

# 52. Retention

Audit poderá crescer continuamente.

O sistema precisará de retention policy.

Possibilidades futuras:

- período mínimo;
- compactação;
- export;
- archival;
- limpeza configurável.

---

# 53. Security Retention

Algumas classes de Audit poderão ter retenção diferente.

Exemplo:

```text
debug-related audit
```

versus:

```text
permission changes
```

---

# 54. Local-first

Audit deverá funcionar totalmente localmente.

Nenhum serviço cloud será necessário para rastreabilidade básica.

---

# 55. Export

Futuramente usuário deverá poder exportar Audit.

Formatos possíveis:

- JSON;
- NDJSON;
- CSV;
- human-readable report.

Não é requisito do primeiro vertical slice.

---

# 56. Queryability

Audit deve ser consultável por:

- time range;
- Task;
- AgentRun;
- Tool;
- Plugin;
- resource;
- decision;
- origin.

---

# 57. Execution Trace

Runtime poderá fornecer visão consolidada:

```text
Task X
 ├── AgentRun A
 │    ├── ToolCall 1
 │    └── ToolCall 2
 └── Result
```

com authority e outcomes associados.

---

# 58. Explainability UX

Futuramente UI poderá oferecer algo como:

> “Por que Sofia fez isso?”

E reconstruir resposta a partir de Audit.

---

# 59. Human-readable Explanation

A explicação poderá ser gerada a partir dos registros estruturados.

LLM poderá ajudar a apresentar linguagem natural.

Mas os fatos devem vir do Audit.

---

# 60. AI Explanation Is Not Audit Authority

LLM não deverá inventar justificativa inexistente.

Se evidência não existe, resposta deverá dizer que não há informação suficiente.

---

# 61. Trace Granularity

Não será auditada cada operação interna trivial.

O foco será boundaries relevantes:

- authority;
- execution;
- state transitions importantes;
- external effects;
- security changes.

---

# 62. Avoid Audit Explosion

Eventos como token streaming, audio chunks e low-level polling não deverão gerar AuditEntry individual por padrão.

---

# 63. Audit Classification

O runtime poderá classificar operações como:

```text
AUDIT_REQUIRED
AUDIT_OPTIONAL
NO_AUDIT
```

ou mecanismo equivalente.

A taxonomia final será definida posteriormente.

---

# 64. ToolSpec Audit Metadata

ToolSpec poderá indicar default audit significance.

Mas Policy/runtime poderá elevar necessidade conforme argumentos.

---

# 65. Dynamic Audit Significance

Exemplo:

```text
filesystem.read README
```

pode exigir pouca informação.

Já:

```text
filesystem.read credentials file
```

pode ser altamente audit-relevant.

---

# 66. Failure Audit

Ações negadas também podem ser relevantes.

Exemplo:

```text
Agent attempted filesystem access outside scope → DENY
```

Isso pode indicar bug ou comportamento suspeito.

---

# 67. Repeated Denials

Observability poderá detectar padrões de denial.

Isso poderá gerar security signal futuro.

---

# 68. Plugin Misbehavior

Se Plugin repetidamente solicitar authority fora do declarado, Audit deverá permitir detectar isso.

---

# 69. Audit and Incident Analysis

Audit deverá permitir investigar:

- comportamento inesperado;
- prompt injection;
- Plugin malicioso;
- erro de Agent;
- destructive action;
- duplicate execution.

---

# 70. Time

Timestamps deverão ser armazenados de forma normalizada e não ambígua.

Presentation timezone pertence à UI.

---

# 71. Ordering

Audit dentro de uma mesma execution trace deverá possuir ordering suficiente para reconstrução.

Global total ordering não é necessário.

---

# 72. Runtime Session

Audit poderá registrar runtime session.

Isso ajuda analisar:

- startup;
- crash;
- recovery;
- shutdown.

---

# 73. Startup Audit

Eventos relevantes podem incluir:

```text
CoreStarted
RecoveryStarted
RecoveryCompleted
CoreShutdown
```

---

# 74. Readiness Failures

Falhas críticas de startup relacionadas a Plugins, Scheduler ou storage poderão ser registradas.

---

# 75. Privacy

Auditability não deverá virar surveillance irrestrita.

Registrar apenas o necessário para explicar ação e segurança.

---

# 76. Content Minimization

Preferir:

```text
resource_ref
hash
summary
classification
```

quando conteúdo integral não for necessário.

---

# 77. Personal Data

Audit pode conter informações pessoais.

Retention/export/deletion deverão respeitar privacy expectations do produto.

---

# 78. Audit Deletion

Como produto single-user, usuário deverá possuir autoridade final sobre dados locais.

Entretanto, exclusão de Audit deverá ser ação explícita e potencialmente destrutiva.

---

# 79. Forget vs Audit Delete

Solicitar Forget de Cognitive Memory não apaga Audit automaticamente.

São domínios distintos.

---

# 80. Conversation Delete vs Audit

Excluir Conversation também não deverá reescrever Audit histórico automaticamente.

Pode haver policy futura de privacy deletion coordenada.

---

# 81. Audit of Audit Changes

Alterações em retention/configuração e operações de export/delete de Audit podem, ironicamente, ser audit-relevant.

Quando tecnicamente possível, registrar antes da remoção.

---

# 82. Logging Correlation

Logs poderão carregar `correlation_id` para facilitar debugging conjunto com Audit.

---

# 83. Metrics Correlation

Métricas não precisam carregar detalhes individuais, mas poderão derivar de eventos de execução.

---

# 84. OpenTelemetry

Padrões como OpenTelemetry poderão ser utilizados futuramente para tracing técnico.

Isso não substituirá domain Audit.

---

# 85. Trace IDs

Poderemos reutilizar trace/correlation conventions de observability quando útil.

Mas domain IDs continuarão explícitos.

---

# 86. Execution Attempt Trace

Cada Task attempt deverá permitir trace independente.

Isso será importante para retry/recovery.

---

# 87. Cross-process Tracing

Subprocesses e Plugin workers deverão propagar correlation context.

Assim:

```text
Core ToolCall X
```

continua identificável dentro do worker.

---

# 88. Sandbox Tracing

Sandbox não deverá receber acesso irrestrito ao Audit Store.

Ele retorna execution evidence ao Core.

Core persiste Audit.

---

# 89. External Resource IDs

Quando ação criar recurso externo, Audit deverá preservar stable ID retornado.

Exemplo:

```text
github_issue_id = 123
```

---

# 90. External Request IDs

Quando APIs fornecem request/operation IDs, eles poderão ser preservados para reconciliation.

---

# 91. Provider Request IDs

Provider request IDs poderão ser registrados quando úteis para suporte/debug.

---

# 92. Error References

Detalhes técnicos grandes poderão ficar em logs/artifacts.

Audit poderá armazenar:

```text
error_ref
```

em vez de stack trace inteiro.

---

# 93. Audit Query Service

Core deverá oferecer serviço de consulta de Audit.

UI não acessa tabela diretamente.

---

# 94. Access Policy

Mesmo sendo single-user, sub-agents/plugins não devem possuir acesso irrestrito a Audit.

Audit pode revelar dados sensíveis.

---

# 95. Audit as Tool

Futuramente poderá existir Tool:

```text
audit.search
```

ou capability equivalente.

Ela estará sujeita a Policy.

---

# 96. Agent Audit Access

Agent de diagnóstico poderá receber Audit scoped para Task específica sem receber histórico completo.

---

# 97. Audit Schema Evolution

Schema deverá evoluir por migrations.

Entries antigas continuarão interpretáveis sempre que possível.

---

# 98. Versioned Payloads

Tipos de Audit com payload estruturado poderão possuir schema version.

Isso reduz incompatibilidade futura.

---

# 99. Audit Event Types

Baseline poderá incluir eventos equivalentes a:

```text
TASK_CREATED
TASK_STATE_CHANGED

AGENT_RUN_STARTED
AGENT_RUN_COMPLETED

TOOL_CALL_REQUESTED
TOOL_CALL_AUTHORIZED
TOOL_CALL_COMPLETED

POLICY_DECISION
CONFIRMATION_REQUESTED
CONFIRMATION_RESOLVED

GRANT_CREATED
GRANT_REVOKED

DELEGATION_CREATED
DELEGATION_REVOKED

PLUGIN_ENABLED
PLUGIN_DISABLED

RECOVERY_DECISION
```

A lista final será definida no backlog.

---

# 100. Security Boundary Audit

Mudanças em:

- Policy;
- Grants;
- execution isolation;
- Plugin trust;

merecem tratamento de alta importância.

---

# 101. Audit Failures

Falha ao persistir Audit de ação altamente sensível deverá possuir comportamento conservador.

Dependendo da operação, runtime poderá impedir execução.

---

# 102. Audit-critical Actions

Algumas ações poderão ser classificadas como:

```text
must_audit_before_execute
```

Exemplo:

- permission grant;
- elevation;
- destructive external action.

---

# 103. Audit Write Ordering

Quando segurança exigir, registrar intent/authorization antes do side effect.

Exemplo:

```text
persist authorized execution intent
    ↓
execute
    ↓
persist result
```

Isso melhora recovery.

---

# 104. Audit and Recovery

Audit poderá fornecer evidence adicional para recovery, mas não será única authority.

Task/Tool operational state continua primary runtime state.

---

# 105. No Event Sourcing Requirement

Embora Audit seja append-oriented, o sistema não adotará Event Sourcing completo.

Current state continuará persistido em tabelas de domínio.

---

# 106. Why Not Event Sourcing

Event Sourcing completo adicionaria:

- replay complexity;
- migrations de events;
- harder querying;
- maior discipline burden.

Não é necessário para o MVP.

---

# 107. Alternatives Considered

## Alternative A — Only Application Logs

### Advantages

- simples;
- já necessário para debugging.

### Rejected because

logs não garantem estrutura suficiente para reconstruir authority e causality.

---

## Alternative B — Full Event Sourcing

### Advantages

- histórico completo;
- replay.

### Rejected because

complexidade excessiva para o produto atual.

---

## Alternative C — Log Everything

### Advantages

- máxima quantidade de informação.

### Rejected because

- privacidade ruim;
- secrets;
- storage explosion;
- baixa signal-to-noise ratio.

---

## Alternative D — Audit Only Errors

### Rejected because

ações bem-sucedidas são justamente as que mais precisam de rastreabilidade quando produzem side effects.

---

# 108. Consequences

## Positive

- ações podem ser explicadas;
- melhora segurança;
- facilita debugging de Agents;
- melhora recovery;
- facilita investigação de prompt injection;
- permite UX “por que Sofia fez isso?”;
- Grants/Delegations ficam rastreáveis;
- plugins tornam-se mais observáveis.

## Negative

- storage adicional;
- exige disciplina de correlação;
- privacy/redaction aumentam complexidade;
- retention precisa ser projetada;
- cross-process tracing exige infraestrutura.

Esses custos são considerados essenciais para um assistente autônomo.

---

# 109. Architectural Invariants

### INV-001

Audit é distinto de logs e metrics.

### INV-002

Ações relevantes devem ser correlacionáveis com sua origem.

### INV-003

PolicyDecision relevante deve ser auditável.

### INV-004

Grant/Delegation changes devem preservar histórico.

### INV-005

Audit nunca armazena secrets brutos.

### INV-006

Private chain-of-thought não é requisito de Audit.

### INV-007

Audit deve ser append-oriented por convenção.

### INV-008

Tool/Agent/Plugin executions devem propagar correlation context.

### INV-009

Audit content deve seguir minimização e redaction.

### INV-010

Forget de Cognitive Memory não apaga Audit automaticamente.

### INV-011

Audit não substitui Operational State.

### INV-012

Audit não implica Event Sourcing.

### INV-013

Plugin/Sandbox não escreve diretamente no Audit Store.

### INV-014

Ação audit-critical pode falhar fechada se Audit não puder ser persistido.

### INV-015

A explicação de uma ação deve derivar de evidence persistida, não de justificativa inventada pelo LLM.

---

# 110. Deferred Decisions

Serão definidos posteriormente:

- schema físico de AuditEntry;
- event type catalog;
- correlation model;
- retention policy;
- redaction rules;
- audit-critical action catalog;
- hash chaining/tamper evidence;
- export format;
- query API;
- UI de execution trace;
- OpenTelemetry integration;
- cross-process trace propagation;
- audit storage indexing.

---

# 111. Decision Summary

Sofia's Assistant possuirá um **Audit Trail estruturado, append-oriented e correlacionável**, separado de logs e metrics.

Ações relevantes deverão permitir reconstruir:

```text
origin
↓
Task
↓
Delegation / Grant
↓
AgentRun
↓
ToolCall
↓
PolicyDecision
↓
Execution
↓
Result / Side Effects
```

Audit preservará evidência sobre authority, causality e outcome sem armazenar indiscriminadamente conteúdo sensível ou private reasoning.

Esse modelo permitirá explicar ações, investigar falhas, acompanhar autonomia, dar suporte a recovery e auditar Plugins, Agents e Tools sem adotar a complexidade de Event Sourcing completo.