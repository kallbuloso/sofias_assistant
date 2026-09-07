# ADR-0010 — Task Lifecycle, Cancellation and Recovery

**Status:** Accepted  
**Project:** Sofia's Assistant  
**Decision date:** 2026-08-31  
**Scope:** Task state model, waiting semantics, cancellation, retry, reconciliation and crash/restart recovery

---

# 1. Context

O Sofia's Assistant executará trabalho que poderá durar além de um único Turn ou de uma única sessão de UI.

Exemplos:

- análise de repositório;
- pesquisa;
- execução de testes;
- workflows;
- operações dependentes de confirmação;
- reminders;
- tarefas aguardando eventos externos;
- AgentRuns;
- operações que continuam em background.

O ADR-0002 definiu que Tasks são persistidas no Operational Store.

O ADR-0009 definiu que `Task` é a unidade principal de trabalho, podendo utilizar:

- Direct Tool;
- Workflow;
- AgentRun.

Para que o runtime seja confiável, é necessário definir semanticamente:

- quando uma Task está executando;
- quando está apenas aguardando;
- como cancelar;
- como lidar com timeout;
- quando retry é seguro;
- o que fazer após crash;
- como diferenciar falha de espera;
- como tratar side effects cujo resultado ficou incerto.

Uma Task persistida como `RUNNING` antes de um crash não pode simplesmente voltar como `RUNNING` depois do reboot.

---

# 2. Decision

O Sofia's Assistant adotará um **Task Lifecycle explícito e persistente**, com recovery semântico após interrupção do runtime.

A regra central será:

> **Persisted state describes what was known. Recovery determines what is true now.**

O runtime nunca presumirá que uma operação marcada como `RUNNING` continuou executando durante uma interrupção do Core.

---

# 3. Fundamental Rules

## 3.1 Waiting Is Not Failure

Uma Task aguardando:

- confirmação;
- horário;
- evento externo;
- recurso;
- dependência;

não será tratada como falha.

## 3.2 Running Is Not Durable Truth Across Restart

`RUNNING` representa execução observada durante determinada runtime session.

Após perda dessa session, o estado precisa ser reconciliado.

## 3.3 Retry Is Not Always Safe

Operações com side effects não idempotentes não poderão ser repetidas apenas porque houve erro ou crash.

## 3.4 Cancellation Is a Request

Cancelar uma Task não significa que todos os efeitos em andamento desapareceram instantaneamente.

---

# 4. Task State Model

O baseline semântico será:

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

Durante recovery poderá existir semanticamente um estado intermediário:

```text
RECOVERY_REQUIRED
```

ou mecanismo equivalente.

A representação física exata será definida no Technical Backlog.

---

# 5. Terminal States

Os estados terminais serão semanticamente equivalentes a:

```text
SUCCEEDED
FAILED
CANCELLED
```

Uma Task terminal não deverá retornar a estado executável comum sem operação explícita como retry/reopen.

---

# 6. QUEUED

`QUEUED` significa:

- Task existe;
- ainda não está executando;
- está elegível ou aguardando disponibilidade para iniciar.

Uma Task deverá preferencialmente ser persistida antes de entrar em execução quando sua durabilidade for necessária.

---

# 7. RUNNING

`RUNNING` significa:

- runtime possui uma execução ativa correspondente;
- existe ownership operacional daquela execução;
- Task iniciou trabalho.

Não significa apenas:

```text
work intended
```

mas:

```text
work observed as executing in current runtime context
```

---

# 8. WAITING_CONFIRMATION

Utilizado quando execução depende de decisão explícita do usuário.

Exemplo:

```text
Task
   ↓
ToolCall requires confirmation
   ↓
WAITING_CONFIRMATION
```

A Task permanece válida.

Não é failure.

---

# 9. WAITING_EXTERNAL

Utilizado quando progresso depende de algo fora do runtime imediato.

Exemplos:

- CI completion;
- resposta de API assíncrona;
- arquivo esperado;
- alteração no GitHub;
- chegada de mensagem;
- device state.

A Task poderá ser retomada por Event.

---

# 10. WAITING_SCHEDULE

Utilizado quando a Task depende de um instante futuro.

Exemplo:

```text
run tomorrow at 09:00
```

O Scheduler será responsável por produzir o evento que torna a Task elegível.

---

# 11. PAUSED

`PAUSED` representa suspensão deliberada preservando intenção de continuidade.

Poderá ser causada por:

- usuário;
- policy;
- runtime administration;
- resource conflict.

Pause não deverá ser usado como substituto genérico de waiting.

---

# 12. CANCELLING

`CANCELLING` representa cancelamento solicitado, ainda não totalmente concluído.

É necessário porque:

```text
cancel requested
```

e:

```text
execution stopped safely
```

não são o mesmo evento.

---

# 13. CANCELLED

`CANCELLED` significa que o runtime concluiu o processo de cancelamento da Task.

Isso não garante reversão dos side effects já realizados.

O resultado de cancelamento deverá poder registrar efeitos já ocorridos.

---

# 14. SUCCEEDED

`SUCCEEDED` significa que os critérios de conclusão da Task foram satisfeitos.

Não deve ser inferido apenas porque uma função retornou sem exception.

Task Runtime deverá saber qual resultado representa sucesso.

---

# 15. FAILED

`FAILED` representa conclusão sem alcançar objetivo e sem caminho automático de continuidade aplicável.

A falha deverá possuir causa estruturada.

---

# 16. RECOVERY_REQUIRED

Após restart/crash, Tasks previamente ativas poderão precisar passar por recovery.

Conceitualmente:

```text
RUNNING
   ↓ runtime lost
RECOVERY_REQUIRED
```

Esse estado poderá ser:

- persistido explicitamente;
- ou representado internamente por recovery metadata.

A escolha concreta é deferred.

O importante é que não exista:

```text
old RUNNING → blindly RUNNING again
```

---

# 17. Runtime Session

O Core deverá possuir identidade de runtime session ou conceito equivalente.

Exemplo:

```text
RuntimeSession
├── id
├── started_at
├── shutdown_at
└── status
```

Tasks em execução poderão registrar qual runtime session era owner.

---

# 18. Graceful Shutdown

Durante shutdown gracioso, o Core deverá:

1. parar de iniciar novo trabalho;
2. solicitar cancellation/pause quando apropriado;
3. persistir estados;
4. finalizar workers;
5. marcar runtime session como encerrada corretamente.

Tasks que não possam ser encerradas imediatamente deverão receber estado coerente antes do término.

---

# 19. Ungraceful Shutdown

Se runtime session não possuir encerramento gracioso:

```text
previous session = interrupted
```

No próximo startup, recovery pass deverá localizar Tasks potencialmente afetadas.

---

# 20. Startup Recovery Pass

Conceitualmente:

```text
Core starts
   ↓
identify previous runtime session
   ↓
detect interrupted executions
   ↓
classify recovery semantics
   ↓
reconcile Tasks / AgentRuns / ToolCalls
   ↓
start normal scheduling
```

Recovery deverá ocorrer antes de tratar Tasks antigas como normalmente executáveis.

---

# 21. Recovery Classification

Uma execução interrompida poderá cair em categorias como:

```text
SAFE_TO_RETRY
SAFE_TO_RESUME
REQUIRES_RECONCILIATION
REQUIRES_USER_DECISION
FAILED_BY_INTERRUPTION
```

A nomenclatura final poderá mudar.

---

# 22. Safe Retry

Retry automático poderá ocorrer quando a operação for comprovadamente segura.

Exemplo típico:

```text
read-only operation
```

ou ação declaradamente idempotente.

Mesmo assim, limites de retry deverão existir.

---

# 23. Unsafe Retry

Não repetir automaticamente operações como:

- enviar mensagem;
- realizar compra;
- publicar conteúdo;
- criar recurso remoto sem idempotency key;
- executar comando com side effects desconhecidos.

Crash não prova que ação não aconteceu.

---

# 24. Reconciliation

Quando resultado puder ser verificado externamente, preferir reconciliation antes de retry.

Exemplo:

```text
git push started
Core crashed
```

Após restart:

```text
inspect remote branch
   ↓
determine whether push occurred
```

Só depois decidir próximo passo.

---

# 25. Reconciliation Capability

ToolSpec poderá fornecer metadata/hook para recovery quando apropriado.

Conceitualmente:

```text
ToolRecoveryPolicy
├── retry_semantics
├── reconciliation_supported
└── reconciliation_handler
```

O contrato concreto será definido posteriormente.

---

# 26. Idempotency Keys

Integrations que suportem idempotency keys deverão utilizá-las quando aplicável.

Exemplo:

```text
create remote resource
idempotency_key = Task/ToolCall identity
```

Isso reduz risco de duplicação após retry.

---

# 27. ToolCall Persistence

ToolCalls relevantes deverão ser persistidos quando necessários para recovery/audit.

O runtime deverá poder distinguir:

```text
REQUESTED
AUTHORIZED
STARTED
COMPLETED
FAILED
```

ou semântica equivalente.

O state model concreto pertence ao backlog.

---

# 28. Started but No Result

Um ToolCall com evidência de:

```text
STARTED
```

mas sem completion após crash deverá ser considerado de resultado incerto.

Não poderá ser automaticamente convertido para:

```text
FAILED, therefore retry
```

---

# 29. Execution Evidence

Recovery poderá usar:

- persisted ToolCall state;
- external resource state;
- process exit information;
- artifacts;
- audit records;
- idempotency keys;
- Tool-specific reconciliation.

---

# 30. AgentRun Recovery

AgentRun interrompido não deverá simplesmente continuar prompt interno de onde parou, a menos que exista mecanismo explícito de checkpoint seguro.

O padrão será:

1. recuperar Task;
2. recuperar AgentRun state;
3. identificar ToolCalls concluídas;
4. reconstruir contexto;
5. decidir resume/replan/restart.

---

# 31. Agent Reasoning Is Not Durable State by Default

Chain-of-thought/provider hidden state não será dependência de recovery.

Recovery deverá se apoiar em estado explícito como:

- Task objective;
- AgentRun goal;
- Plan;
- ToolResults;
- artifacts;
- relevant context.

---

# 32. Workflow Recovery

Workflows determinísticos deverão, quando possível, persistir steps concluídos.

Exemplo:

```text
Step 1 ✓
Step 2 ✓
Step 3 running when crash
```

Recovery poderá retomar a partir da etapa correta se isso for seguro.

---

# 33. Direct Tool Task Recovery

Task de Direct Tool dependerá da Tool recovery semantics.

Read-only Tool pode ser repetida.

External mutation pode exigir reconciliation.

---

# 34. Waiting State Recovery

Estados de espera normalmente sobrevivem a restart diretamente.

Exemplo:

```text
WAITING_CONFIRMATION
```

continua aguardando confirmação.

Não deve voltar para `QUEUED` apenas porque Core reiniciou.

---

# 35. Confirmation Recovery

Uma `ConfirmationRequest` persistida deverá continuar vinculada à operação correspondente.

Se o contexto que justificava a confirmação mudou, runtime poderá invalidar a confirmação e exigir nova avaliação.

---

# 36. Scheduled Task Recovery

Schedules persistentes deverão ser reconstruídos.

Se horário ocorreu enquanto Sofia estava desligada, runtime deverá possuir política para missed execution.

Possíveis comportamentos:

```text
RUN_IMMEDIATELY
SKIP
RESCHEDULE_NEXT
ASK_USER
```

A decisão dependerá do tipo de Schedule.

---

# 37. Reminder Missed While Offline

Para reminders pessoais, comportamento provável será:

```text
deliver after startup
```

com indicação de que horário previsto já passou.

A policy concreta será definida no Scheduler backlog.

---

# 38. Cancellation Request

Usuário ou runtime poderá solicitar cancellation.

Fluxo:

```text
RUNNING
   ↓ cancel requested
CANCELLING
   ↓ execution safely stops
CANCELLED
```

---

# 39. Cancellation Propagation

Cancelar parent Task deverá propagar intenção de cancellation para trabalho derivado quando aplicável.

Exemplo:

```text
Task
  └── AgentRun
       └── ToolCall
```

Todos deverão receber cancellation signal apropriado.

---

# 40. Cancellation Does Not Bypass Safety

Não será permitido matar indiscriminadamente processo que possa deixar estado corrompido apenas porque cancellation foi solicitada.

A política dependerá da execução.

---

# 41. Cooperative Cancellation

Operações compatíveis deverão observar cancellation token ou mecanismo equivalente.

Exemplo:

- loops;
- downloads;
- analysis;
- Agent planning;
- workflows.

---

# 42. Forced Termination

Subprocess poderá eventualmente ser finalizado à força quando:

- safe;
- necessário;
- permitido pela execution policy.

Isso não será comportamento universal.

---

# 43. Non-interruptible Side Effects

Algumas operações poderão atingir ponto onde cancellation segura não é mais possível.

Exemplo:

```text
remote transaction committed
```

Nesse caso cancellation poderá impedir etapas futuras, mas não desfazer efeito concluído.

---

# 44. Compensation

Futuramente algumas operações poderão fornecer compensation.

Exemplo:

```text
create temporary resource
   ↓ cancel
delete temporary resource
```

Compensation não será assumida como rollback transacional universal.

---

# 45. Timeout

Timeout poderá resultar em:

- cancellation request;
- failure;
- recovery/reconciliation;

dependendo do Tool/Task.

Timeout não significa necessariamente que side effect não ocorreu.

---

# 46. Deadline

Task poderá possuir deadline distinta de timeout individual.

Exemplo:

```text
Task deadline = 30 min
Tool timeout = 5 min
```

A semântica final será definida posteriormente.

---

# 47. Retry Policy

Retry deverá considerar:

```text
failure type
+
idempotency
+
attempt count
+
Task policy
+
Tool semantics
+
external state
```

Não haverá:

```text
except Exception:
    retry()
```

universal.

---

# 48. Retry Limits

Toda política de retry deverá possuir limite.

Exemplos:

- max attempts;
- backoff;
- deadline;
- provider cooldown.

Isso evita loops infinitos.

---

# 49. Backoff

Operações dependentes de recursos temporariamente indisponíveis poderão usar backoff.

Estratégia concreta será definida conforme subsystem.

---

# 50. Replanning vs Retry

Retry repete operação semanticamente equivalente.

Replanning muda estratégia.

Exemplo:

```text
provider unavailable
```

pode causar routing fallback.

Já:

```text
approach failed logically
```

pode exigir replan.

Esses conceitos não deverão ser confundidos.

---

# 51. Pause vs Cancel

`PAUSED` preserva intenção de continuar.

`CANCELLED` encerra a Task.

Usuário deverá poder distinguir essas ações na UI quando ambas forem suportadas.

---

# 52. Policy-triggered Pause

Policy change ou Grant revocation poderá interromper novas ações de Task.

Dependendo do contexto, Task poderá entrar em:

```text
PAUSED
```

ou:

```text
WAITING_CONFIRMATION
```

em vez de failure imediata.

---

# 53. Grant Revocation During Execution

Novas ToolCalls dependentes de Grant revogado deverão ser negadas.

ToolCall já em andamento seguirá sua cancellation/execution semantics.

---

# 54. Delegation Revocation

Revogar Delegation deverá impedir novo trabalho derivado.

Tasks existentes serão avaliadas para:

- cancellation;
- pause;
- safe completion;
- user decision.

---

# 55. External Events

`WAITING_EXTERNAL` deverá ser retomada por Event correlacionável.

Exemplo:

```text
Task waiting for CI run 123
```

não deve ser retomada por qualquer evento de CI.

---

# 56. Event Correlation

Waiting conditions deverão registrar filtros/identidade suficiente para determinar qual evento é relevante.

---

# 57. Lost Events

Para eventos críticos, Event Runtime deverá possuir mecanismo de persistência/reconciliation suficiente para não depender exclusivamente de evento em memória.

Detalhes serão definidos no ADR-0003.

---

# 58. Task Ownership

Runtime deverá evitar que dois workers executem simultaneamente a mesma Task sem intenção explícita.

Task claiming deverá ser atômico.

---

# 59. Task Lease / Ownership Model

Implementação poderá usar:

- owner runtime;
- lease;
- generation;
- execution attempt;

ou mecanismo equivalente.

A escolha concreta será definida no Technical Backlog.

---

# 60. Execution Attempt

Task poderá possuir múltiplas tentativas.

Conceitualmente:

```text
Task
├── Attempt 1
├── Attempt 2
└── Attempt 3
```

Isso melhora audit e recovery.

A modelagem física é deferred.

---

# 61. Attempt Identity

Retry não deverá apagar evidência de attempt anterior.

Uma nova tentativa deve ser distinguível.

---

# 62. Failure Classification

Failures deverão ser estruturadas.

Exemplos conceituais:

```text
VALIDATION_FAILED
AUTHORIZATION_DENIED
DEPENDENCY_UNAVAILABLE
EXECUTION_FAILED
TIMEOUT
INTERRUPTED
LIMIT_EXCEEDED
RECOVERY_UNCERTAIN
```

Taxonomia final será definida posteriormente.

---

# 63. Authorization Denied

`DENY` não precisa sempre significar Task `FAILED`.

Exemplo:

Task pode tentar estratégia alternativa que não exige capability negada.

Se nenhuma alternativa existir, poderá falhar.

---

# 64. Waiting for Authorization

`REQUIRE_CONFIRMATION` deverá preferir `WAITING_CONFIRMATION`.

Agent/Task não deve continuar presumindo aprovação.

---

# 65. User Rejection

Se usuário rejeitar confirmação, root poderá:

- replan;
- concluir parcialmente;
- cancelar;
- falhar.

A ação rejeitada jamais será executada.

---

# 66. Partial Success

Task poderá produzir resultados úteis mesmo se objetivo total falhar.

TaskResult deverá poder registrar:

- completed work;
- artifacts;
- unresolved items;
- side effects.

Estado terminal ainda deverá refletir objetivo global.

---

# 67. Task Result

Task terminal deverá possuir resultado estruturado quando aplicável.

Conceitualmente:

```text
TaskResult
├── status
├── summary
├── artifacts
├── side_effects
├── unresolved_items
├── error
└── metadata
```

---

# 68. Recovery Result

Recovery deverá produzir registro explicando decisão tomada.

Exemplo:

```text
Task interrupted
ToolCall reconciled as completed
Task resumed at step 4
```

Isso deverá ser auditável.

---

# 69. Recovery Must Be Deterministic Where Possible

Recovery não deverá depender exclusivamente de LLM perguntado:

> “O que você acha que aconteceu?”

LLM poderá ajudar na interpretação, mas evidence/runtime rules serão authority.

---

# 70. Recovery and Policy

Toda nova ação gerada por recovery continua sujeita ao PolicyEngine.

Recovery não constitui bypass de authorization.

---

# 71. Restart and Grants

Recovery deverá recalcular authority efetiva.

Grant válido durante execução original pode ter:

- expirado;
- sido revogado;
- sofrido Policy change.

Task não mantém authority eterna apenas porque começou antes.

---

# 72. Restart and Data Locality

Context reconstruído deverá reavaliar locality antes de ser enviado para providers.

---

# 73. Process Recovery

Subprocess perdido após Core crash poderá ainda existir dependendo do OS/topologia.

Startup recovery deverá evitar assumir automaticamente que processo morreu.

Quando necessário, workers poderão possuir identifiers/heartbeats.

Detalhes pertencem ao ADR-0013.

---

# 74. Orphan Processes

Runtime deverá eventualmente detectar subprocessos órfãos sob sua responsabilidade.

Não deverá reconectar ou matar arbitrariamente sem identificar ownership.

---

# 75. Core Crash vs Worker Crash

Worker crash poderá ser tratado sem Core restart.

Task Runtime deverá receber failure event e decidir retry/replan/fail.

---

# 76. Provider Session Loss

Perda de provider session não implica Task failure automática.

Conversation Runtime poderá reconstruir contexto.

AgentRun poderá continuar/replan conforme estado explícito.

---

# 77. Human-readable Status

Task deverá permitir descrição compreensível ao usuário.

Exemplos:

- “Executando testes”
- “Aguardando sua confirmação”
- “Aguardando CI”
- “Recuperando após reinicialização”

UI não deverá expor apenas enums internos.

---

# 78. Progress

Progress poderá ser:

- percentual;
- steps completed;
- textual;
- indeterminado.

Runtime não deverá inventar porcentagem quando não há base objetiva.

---

# 79. Task History

Transitions relevantes deverão ser registráveis para audit/debug.

Exemplo:

```text
QUEUED
→ RUNNING
→ WAITING_CONFIRMATION
→ RUNNING
→ SUCCEEDED
```

---

# 80. Invalid Transitions

Task Runtime deverá rejeitar transitions inválidas.

Exemplo:

```text
SUCCEEDED → RUNNING
```

não poderá ocorrer por mutation arbitrária.

---

# 81. State Transition Authority

Somente Task Runtime/recovery services autorizados deverão alterar Task lifecycle.

UI não modifica status diretamente.

---

# 82. Persistence Ordering

Transitions críticas deverão ser persistidas na ordem adequada.

Exemplo:

antes de executar side effect relevante, runtime deverá ter persistido informação suficiente para recovery.

Evitar:

```text
execute external mutation
   ↓
persist that execution started
```

quando isso cria janela de incerteza evitável.

---

# 83. Durable Intent Before Effect

Quando aplicável:

```text
persist intent / ToolCall
   ↓
authorize
   ↓
mark execution start
   ↓
perform effect
   ↓
persist result
```

Esse padrão reduz ambiguidades de recovery.

---

# 84. Exactly-once Is Not Assumed

O Sofia's Assistant não presumirá garantia genérica de exactly-once execution.

O modelo deverá trabalhar realisticamente com:

- at-most-once em alguns casos;
- at-least-once em outros;
- idempotency;
- reconciliation.

---

# 85. External APIs

Integrations deverão aproveitar:

- request IDs;
- idempotency keys;
- resource identifiers;
- operation status endpoints;

quando disponíveis.

---

# 86. Conversation Notifications

Task status transitions poderão gerar Domain Events.

Exemplo:

```text
TaskSucceeded
TaskFailed
TaskWaitingConfirmation
```

Conversation/UI poderão reagir.

---

# 87. Scheduler Integration

Scheduler torna Task elegível.

Ele não deve modificar diretamente Task para `RUNNING` sem passar pelo Task Runtime.

---

# 88. Event Integration

External Event poderá satisfazer waiting condition.

Task Runtime será responsável pela transition correspondente.

---

# 89. Audit Integration

Deverá ser possível reconstruir:

```text
Task
↓
Attempts
↓
state transitions
↓
AgentRuns
↓
ToolCalls
↓
recovery decisions
↓
final result
```

---

# 90. Retention

Tasks concluídas poderão permanecer no Operational Store para histórico/audit.

Retention policy poderá permitir limpeza futura.

A política exata é deferred.

---

# 91. Testing

Deverão existir testes para:

- normal success;
- waiting confirmation;
- waiting external;
- pause/resume;
- cancellation;
- timeout;
- safe retry;
- unsafe retry blocked;
- crash during ToolCall;
- startup recovery;
- AgentRun interruption;
- workflow resume;
- expired Grant during recovery;
- duplicate worker claim prevention.

---

# 92. Crash Simulation Tests

Recovery não deverá ser validado apenas com mocks.

Testes deverão simular interrupções em boundaries críticos.

Exemplos:

```text
persist STARTED
crash
restart
```

e:

```text
external effect
crash before local completion record
```

quando tecnicamente viável.

---

# 93. Alternatives Considered

## Alternative A — In-memory TaskQueue

### Advantages

- muito simples;
- baixa persistência.

### Rejected because

- perde estado em restart;
- reminders/delegations ficam frágeis;
- recovery impossível;
- repete limitação observada em arquiteturas anteriores analisadas.

---

## Alternative B — Mark all RUNNING tasks as FAILED on startup

### Advantages

- simples;
- previsível.

### Rejected because

- perde possibilidade de reconciliation/resume;
- confunde interrupção com falha lógica;
- pode causar duplicação quando usuário retry manualmente.

---

## Alternative C — Retry every interrupted Task automatically

### Rejected because

pode duplicar side effects irreversíveis ou externos.

---

## Alternative D — Persist every internal micro-step

### Advantages

- máxima observabilidade.

### Rejected because

- complexidade excessiva;
- write amplification;
- acoplamento entre implementação e persistence.

Persistir somente boundaries necessários para durabilidade/recovery.

---

# 94. Consequences

## Positive

- Tasks sobrevivem a restart;
- waiting não é confundido com failure;
- recovery explícito;
- menor risco de duplicate side effects;
- cancellation model consistente;
- Agent/workflow recovery possível;
- audit melhora;
- scheduler e eventos integram-se naturalmente.

## Negative

- Task Runtime torna-se mais complexo;
- Tools precisam declarar idempotency/recovery semantics;
- testes de crash são mais trabalhosos;
- algumas ações externas exigem reconciliation customizada;
- state machine precisa disciplina rigorosa.

Esses custos são necessários para um assistente capaz de agir autonomamente.

---

# 95. Architectural Invariants

### INV-001

Waiting nunca é representado genericamente como failure.

### INV-002

Task previamente RUNNING não volta automaticamente a RUNNING após restart.

### INV-003

Retry nunca é universal.

### INV-004

Side effect incerto exige reconciliation ou decisão explícita.

### INV-005

Cancellation request e cancellation completion são estados distintos quando necessário.

### INV-006

Task terminal não é reativada por mutation arbitrária.

### INV-007

Recovery não bypassa PolicyEngine.

### INV-008

Authority é recalculada durante retomada/recovery.

### INV-009

Task execution possui ownership operacional explícito.

### INV-010

Durable intent deve preceder side effects relevantes quando possível.

### INV-011

Exactly-once não é assumido genericamente.

### INV-012

Agent hidden reasoning não é dependência de recovery.

### INV-013

Missed schedules possuem policy explícita.

### INV-014

UI não altera Task state diretamente.

---

# 96. Deferred Decisions

Serão definidos posteriormente:

- enum final de Task states;
- se `RECOVERY_REQUIRED` será persisted state;
- Attempt schema;
- lease/ownership mechanism;
- retry/backoff policy;
- recovery handler contract;
- TaskResult schema;
- ToolCall lifecycle schema;
- workflow checkpoint model;
- missed schedule policies;
- cancellation tokens implementation;
- worker concurrency;
- retention policy;
- progress model.

---

# 97. Decision Summary

Sofia's Assistant utilizará um lifecycle de Tasks explícito, durável e orientado a recovery.

Tasks poderão executar, aguardar confirmação, eventos ou schedules, ser pausadas e canceladas sem confundir esses estados com failure.

Após crash ou restart, operações anteriormente ativas serão reconciliadas antes de qualquer retomada.

Retry dependerá de idempotency, side effects e evidência disponível.

Operações de resultado incerto deverão ser verificadas antes de repetição.

Task Runtime será authoritative sobre transitions, enquanto PolicyEngine continuará authoritative sobre autorização de qualquer nova ação gerada durante execução ou recovery.