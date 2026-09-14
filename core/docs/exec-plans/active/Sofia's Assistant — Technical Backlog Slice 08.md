# Sofia's Assistant — Technical Backlog Slice 08

**Nome operacional:** Recovery & MVP Release  
**Escopo:** SA-B033 + SA-B034  
**Gates-alvo:** I12 — Recovery Validated; I13 — MVP Ready  
**Status:** APPROVED
**Projeto:** Sofia's Assistant  
**Baseline auditado:** `436bcf4a4d4ce179e8667da24ef62005e8fc0e2c`  
**Último Slice concluído:** Slice 05 — Sofia Remembers — DONE / REMOTE VERIFIED / POST-CLOSURE HARDENING VERIFIED  
**Estratégia de execução:** um Gate por vez, checkpoints retomáveis, Reference Harvest dirigido, simulação de crash e integração de release  
**Fonte:** Technical Backlog Map aprovado + ADRs + Architecture Review Amendments + Slices 01–07 concluídos + auditoria da implementação atual

---

# 1. Objetivo

O Slice 08 é o último Slice de implementação do MVP.

Ele precisa provar duas coisas diferentes, nesta ordem:

```text
Gate I12
Recovery é confiável
↓
Gate I13
O MVP completo funciona como um único produto
↓
MVP RELEASE READINESS
```

Portanto, o Slice possui dois Runs:

```text
Slice 08 — Recovery & MVP Release
│
├── Run 1 — Gate I12
│     └── SA-B033 Recovery Hardening
│
└── Run 2 — Gate I13
      └── SA-B034 MVP Integration & Release Gate
```

O Gate I13 não deve começar enquanto o Gate I12 ainda tiver findings de correctness não resolvidos.

---

# 2. Baseline na materialização

O `main` remoto foi auditado independentemente em:

```text
436bcf4a4d4ce179e8667da24ef62005e8fc0e2c
```

Último commit observado:

```text
docs(plan): record slice 05 post-closure hardening
```

Neste baseline:

```text
I1  ✅ Core Alive
I2  ✅ Sofia Can Converse
I3  ✅ Sofia Can Speak
I4  ✅ Sofia Can Act Safely
I5  ✅ Sofia Can Work
I6  ✅ Sofia Can Remember
I7  ✅ Sofia Can React
I8  ✅ Sofia Can Use the Computer
I9  ✅ Sofia Can Delegate
I10 ✅ Sofia Is Traceable
I11 ✅ Product Interface

I12 ⏳ Recovery Validated
I13 ⏳ MVP Ready
```

Não existe mais dependência arquitetural bloqueada pelo Sofias Memory.

---

# 3. Por que o Slice 08 está desbloqueado

Todos os blockers anteriores do MVP já existem em forma implementada:

```text
Conversation
Voice
Context Builder
Policy
Permission Grants
Tool Runtime
Tasks
Agents
Execution Isolation
Cognitive Memory
Events
Scheduler
Notifications
Filesystem
Shell
Web
Desktop basics
Vision
Development Analysis Agent
Audit
Desktop Client
```

O trabalho restante já não é adicionar outra grande família de capabilities.

Agora o foco é:

```text
correção após interrupção
+
integração do produto completo
+
evidência de release
```

---

# 4. Organização por Gate

```text
Gate I12 — Recovery Validated
    SA-B033 Recovery Hardening

Gate I13 — MVP Ready
    SA-B034 MVP Integration & Release Gate
```

A ordem de execução é rígida:

```text
I12
↓
verificação remota
↓
I13
```

Não consolidar commits de fechamento ou evidências de forma tão agressiva que um defeito de recovery possa ficar escondido dentro do trabalho de release gate.

---

# 5. Modelo de execução

A unidade de implementação/revisão continua sendo o Gate.

Fluxo esperado:

```text
objective
↓
pre-flight
↓
Reference Harvest
↓
auditoria do estado atual
↓
implementação mínima
↓
testes direcionados
↓
testes de crash / restart
↓
testes verticais do Gate
↓
regressão completa
↓
quality gates
↓
commit
↓
push
↓
CI remoto
↓
revisão independente
↓
fechamento do Gate
```

O Gate I13 exige adicionalmente:

```text
release candidate
↓
packaging
↓
smoke de processo
↓
matriz de cenários do MVP
↓
decisão de release readiness
```

---

# 6. Resume Capsule

Se o trabalho for interrompido, atualizar este Slice com:

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

A continuação deve começar pela Capsule, pelo diff atual, pelos arquivos afetados e pelas seções relevantes dos ADRs.

Não reiniciar discovery arquitetural.

---

# 7. Fontes arquiteturais obrigatórias

Authority principal:

```text
product/docs/adr/ADR-0010 — Task Lifecycle, Cancellation and Recovery.md

product/docs/Sofia's Assistant — Technical Backlog Map.md

product/docs/adr/ADR-0002 — Operational Persistence and Runtime Process Model.md

product/docs/adr/ADR-0003 — Internal Event and Scheduler Architecture.md

product/docs/adr/ADR-0009 — Task, Agent and Tool Execution Model.md

product/docs/adr/ADR-0015 — Audit and Execution Traceability.md
```

Consultar também, somente quando necessário:

```text
Architecture Review Amendment 0002.md

Slice 04 concluído
Slice 05 concluído
Slice 06 concluído
Slice 07 concluído
```

O Gate I12 é governado principalmente pelo ADR-0010.

Não criar novo ADR, a menos que a implementação revele uma contradição arquitetural real ainda não coberta.

---

# 8. Reference Harvest

O Reference Harvest é obrigatório antes de cada Gate.

## 8.1 Harvest do Gate I12

Inspecionar, nesta prioridade:

```text
A. implementação atual do Sofia's Assistant
B. ADR-0010
C. padrões de recovery/replanning do Brahma / Mark LI, somente se relevantes
D. semântica de processos Python/asyncio/Windows quando a implementação exigir confirmação
```

Inspiração externa útil pode incluir:

```text
durable work seguro após restart
replanning após interrupção
checkpoints explícitos de execução
evidência de lifecycle de processo
```

Projetos externos não são authority para:

```text
authorization
confirmation
grants
segurança de ToolCall
audit
secret handling
prevenção de side effects duplicados
```

Registrar:

```text
REUSED
ADAPTED
REJECTED
```

Se não houver padrão externo útil, registrar isso e seguir.

## 8.2 Harvest do Gate I13

Não se espera novo harvest arquitetural amplo.

Inspecionar:

```text
Gate tests já concluídos
cenários MVP do PRD
workflow atual de CI
packaging atual do Desktop
convenções atuais de smoke
convenções de release/versionamento do repositório
```

O Gate I13 deve integrar o que já existe, não disparar uma reescrita.

---

# 9. Princípios congelados de recovery

As seguintes semânticas do ADR-0010 são obrigatórias.

## 9.1 RUNNING persistido não é verdade após restart

```text
RUNNING
```

significa que a execução foi observada em uma Runtime Session.

Depois da perda do runtime:

```text
old RUNNING
!=
still running
```

Um startup recovery pass precisa reconciliar esse estado.

## 9.2 Waiting não é Failure

Estes estados sobrevivem semanticamente ao restart:

```text
WAITING_CONFIRMATION
WAITING_EXTERNAL
WAITING_SCHEDULE
PAUSED
```

Eles não devem virar `FAILED` apenas porque o Core reiniciou.

## 9.3 Crash não prova ausência de side effect

Um ToolCall com:

```text
STARTED/RUNNING
+
sem evidência de completion
```

tem outcome incerto.

Nunca implementar:

```text
crash
↓
mark FAILED
↓
blind retry
```

para uma operação que possa ter causado side effects.

## 9.4 Retry exige evidência positiva de segurança

Retry automático exige uma razão explícita, como:

```text
read-only
idempotent
ou
reconciliation provou ausência do efeito original
```

## 9.5 Raciocínio do Agent não é estado durável de recovery

Não depender de:

```text
chain-of-thought
provider hidden state
continuação opaca de sessão do modelo
```

Recovery usa estado explícito e durável.

## 9.6 Policy é recalculada

Recovery nunca pode reviver authority obsoleta apenas porque uma execução anterior tinha permissão.

No momento da execução:

```text
Task intent
↓
Tool registration atual
↓
Policy atual
↓
estado atual de Grant/Delegation
↓
executar ou negar
```

## 9.7 Sem promessa falsa de exactly-once

O runtime pode oferecer:

```text
deduplicação
idempotência
reconciliation
safe pause
decisão do usuário
```

Ele não deve afirmar garantia universal de exactly-once execution.

---

# 10. Auditoria atual de recovery

Na materialização, a implementação já contém comportamento substancial de recovery.

Este Slice deve preservá-lo em vez de substituí-lo.

---

# 11. Já implementado — RuntimeSession recovery

`RuntimeSessionLifecycle.start()` já:

```text
encontra RuntimeSession anterior == RUNNING
↓
marca como INTERRUPTED
↓
cria sessão atual RUNNING
```

Isso fornece ao startup um sinal durável de que o Core anterior não encerrou normalmente.

Status:

```text
✅ IMPLEMENTADO
```

O Gate I12 deve reutilizar isso.

---

# 12. Já implementado — Scheduler/Event recovery

O Proactivity runtime existente já executa:

```text
recover_scheduled_tasks(startup=True)
↓
Scheduler tick
↓
coleta de Notifications
↓
dispatch de Events duráveis
```

Os testes existentes já cobrem:

```text
Reminder sobrevive a Core restart
claim expirado de durable Event delivery é recuperado
WAITING_SCHEDULE acorda após restart
Grant revogado é reavaliado
duplicate scheduled wakeup é limitado
```

Status:

```text
✅ BASELINE FORTE
```

Não construir um segundo sistema de Scheduler recovery.

---

# 13. Já implementado — execução agendada incerta

Para uma Task agendada observada como stale `RUNNING` no startup:

```text
ToolCall ausente ou RUNNING
↓
Task -> PAUSED
error_code = SCHEDULE_RECONCILIATION_REQUIRED
```

Isso já é uma implementação concreta do princípio do ADR:

```text
incerteza != blind retry
```

Status:

```text
✅ PADRÃO PARCIAL DE RECOVERY A GENERALIZAR
```

---

# 14. Já implementado — replay seguro de Cognitive Memory

O Slice 05 já fornece:

```text
Create:
Idempotency-Key derivada do UUID do MemoryCandidate

Supersede:
MemoryOperation UUID durável

Forget:
MemoryOperation UUID durável
```

e os métodos de retry preservam a identidade da operação.

Portanto:

```text
remote commit
↓
Assistant crash antes da conclusão local
↓
mesma identidade de operação
↓
safe replay
```

já foi desenhado.

Status:

```text
✅ RECOVERY LOCAL DO DOMÍNIO PRONTO
```

O Gate I12 pode integrar recovery de Memory operations pendentes, mas não deve redesenhar o protocolo de Memory.

---

# 15. Gap A — Intent durável de Task geral

Atualmente `TaskRuntime.create_task()` persiste a `Task` e depois inicia um runner asyncio em memória.

O próprio ToolCall só se torna duravelmente persistido dentro de `ExecutionRuntime.invoke()`.

Isso deixa uma possível janela de crash:

```text
Task salva
↓
Core crash
↓
ToolCall ainda não persistido
↓
Task continua durável
mas os detalhes da intenção de execução podem não ser recuperáveis
```

Isso precisa ser corrigido para o I12.

## 15.1 Requisito

Uma Task durável precisa conter intent de execução suficiente para responder após restart:

```text
o que deveria ser executado?
com quais argumentos normalizados?
sob qual subject?
qual identidade de ToolCall?
qual execution strategy?
```

antes de qualquer execução externa começar.

## 15.2 Direção mínima preferida

Reutilizar:

```text
ToolCallRecord
TaskAttemptRecord
TaskRecord
```

em vez de introduzir um workflow engine genérico.

Uma implementação válida pode, por exemplo:

```text
persistir ToolCall em estado pré-execução
+
ligar Task/Attempt duráveis a ele
+
só então agendar o runner em memória
```

O layout físico exato pertence à implementação.

## 15.3 Restrição

Não persistir secrets que foram deliberadamente excluídos dos argumentos do ToolCall.

Não serializar callables arbitrários de runtime.

---

# 16. Gap B — Startup recovery geral de Task

O startup recovery atual foca Tasks agendadas.

O Gate I12 precisa de um startup pass geral para Tasks duráveis stale.

Deve classificar pelo menos:

```text
QUEUED
RUNNING
WAITING_CONFIRMATION
WAITING_EXTERNAL
WAITING_SCHEDULE
PAUSED
CANCELLING
terminal
```

## 16.1 QUEUED

Se o execution intent for duravelmente reconstruível e a authority puder ser recalculada:

```text
elegível para claim normal
```

Nenhum runner duplicado em memória pode ser criado.

## 16.2 RUNNING

Nunca retomar às cegas.

Inspecionar:

```text
último TaskAttempt
estado do ToolCall
execution mode
características de recovery do ToolSpec
AgentRun, quando aplicável
Audit/evidence
```

Depois classificar.

## 16.3 WAITING_CONFIRMATION

Manter waiting se:

```text
ConfirmationRequest ainda PENDING
relação com ToolCall é válida
authority solicitada ainda é coerente
```

Caso contrário, fail closed / invalidar com segurança.

Não autoaprovar.

## 16.4 WAITING_EXTERNAL

Preservar waiting.

Se o watcher correspondente à condição externa não existir no MVP, manter a Task explicitamente aguardando em vez de inventar progresso.

## 16.5 WAITING_SCHEDULE

Continuar usando o path de Scheduler recovery existente.

## 16.6 PAUSED

Permanecer paused até que uma ação explícita de recovery faça a transição.

## 16.7 CANCELLING

O startup precisa reconciliar para um estado verdadeiro.

Não deixar `CANCELLING` stale indefinidamente.

Possíveis outcomes incluem:

```text
CANCELLED
PAUSED / RECOVERY_REQUIRED
```

dependendo da incerteza.

---

# 17. Classificação de recovery

O ADR-0010 define categorias conceituais.

O Gate I12 deve materializar uma representação pequena e explícita equivalente a:

```text
SAFE_TO_RETRY
SAFE_TO_RESUME
REQUIRES_RECONCILIATION
REQUIRES_USER_DECISION
FAILED_BY_INTERRUPTION
```

Os nomes podem variar.

A classificação deve ser:

```text
determinística
auditável
limitada
não autorizada por LLM
```

Um provider/LLM poderá futuramente ajudar a interpretar evidence, mas não pode decidir authority ou segurança.

---

# 18. Startup Recovery Coordinator

Arquitetura preferida:

```text
RuntimeSessionLifecycle.start()
        ↓
compose ExecutionRuntime
compose TaskRuntime
compose AgentRuntime
compose Memory
        ↓
StartupRecoveryCoordinator
        ├── reconcile stale Tasks
        ├── reconcile ToolCalls
        ├── reconcile AgentRuns
        ├── reconcile subprocess evidence
        ├── reconcile pending Memory operations
        └── validate waiting/confirmation state
        ↓
start ProactivityRuntime
        ↓
Core -> RUNNING
```

O nome pode variar:

```text
RecoveryCoordinator
StartupRecoveryService
RecoveryRuntime
```

Manter pequeno.

Ele coordena runtimes de domínio existentes; não vira um domain owner universal.

---

# 19. Ordem de startup

Recovery precisa acontecer antes que trabalho antigo possa voltar a ser executado normalmente.

Ordem semântica obrigatória:

```text
acquire single-instance ownership
↓
bootstrap persistence
↓
RuntimeSessionLifecycle.start()
↓
compose execution domains
↓
startup recovery
↓
start Scheduler/Event processing
↓
Core RUNNING
```

Motivo:

```text
Scheduler/Event wakeup
não deve correr
contra stale Task reconciliation
```

---

# 20. Ownership de Task

O `TaskRuntime` atual usa owner semelhante a:

```text
core-<random UUID>
```

O Gate I12 deve tornar ownership correlacionável de forma útil com a RuntimeSession atual, quando prático.

Preferência:

```text
claimed_by = runtime:<RuntimeSession UUID>
```

ou equivalente.

Isso provavelmente pode ser feito sem expansão de schema, pois `claimed_by` já existe.

Não adicionar schema apenas para duplicar informação já representável.

---

# 21. Incerteza de ToolCall

Um `ToolCallRecord.status == RUNNING` persistido no startup não é uma operação ativa em voo.

É:

```text
execution outcome unknown
```

O Gate I12 precisa impedir que ele permaneça para sempre interpretado apenas como `DUPLICATE_IN_FLIGHT` normal.

## 21.1 Distinção obrigatória

No startup:

```text
RUNNING do runtime anterior
↓
semântica UNCERTAIN / RECOVERY_REQUIRED
```

A representação física pode ser:

```text
novo status explícito
recovery metadata
Task state + audit evidence
```

mas precisa ser consultável e testável.

## 21.2 Caso read-only/idempotent

Retry automático só é permitido quando o ToolSpec suportar positivamente.

Regra conservadora de baseline:

```text
ToolSpec.idempotent == True
AND
ToolSpec.side_effect == NONE
```

pode qualificar para retry automático.

A implementação pode ser ainda mais restritiva.

## 21.3 Caso mutating/non-idempotent

Para:

```text
side_effect == MUTATING
ou
idempotent == False
```

nunca blind-retry um call incerto.

Preferir:

```text
REQUIRES_RECONCILIATION
ou
REQUIRES_USER_DECISION
```

---

# 22. Seam de reconciliation específico de Tool

Não construir um grande plugin framework.

Se necessário, estender `ToolSpec` minimamente com semântica equivalente a:

```text
recovery classification
optional reconciliation capability
```

Modelo conceitual possível:

```text
ToolRecoveryPolicy
├── retry_safe
├── reconciliation_supported
└── reconcile(...)
```

Mas só implementar hook se pelo menos um Tool real do MVP precisar dele para satisfazer o I12.

Uma classificação estática e determinística baseada no metadata atual do ToolSpec é aceitável para o MVP quando for mais segura.

Evitar construção especulativa de framework.

---

# 23. Filesystem recovery

Comportamento atual do MVP:

```text
filesystem.read
    read-only / candidato a retry-safe

filesystem.list
    read-only / candidato a retry-safe

filesystem.write
    mutating
    idempotent=False
```

Recovery esperado:

```text
read/list incertos
    podem ser repetidos com segurança se todos os predicates passarem

write incerto
    NÃO deve ser repetido às cegas
```

O usuário pode inspecionar o arquivo/recurso alvo antes de decidir.

O Gate I12 não precisa de filesystem transaction journal genérico.

---

# 24. Shell recovery

O Shell Tool atual é:

```text
SUBPROCESS
idempotent=False
```

Portanto um `shell.execute` interrompido não é auto-retryable.

Comportamento obrigatório:

```text
stale shell ToolCall RUNNING
↓
incerto
↓
Task PAUSED / reconciliation-required
↓
notification/audit evidence
```

Nunca assumir:

```text
process desapareceu => command não teve efeito
```

---

# 25. Evidência de execução de subprocess

`TaskAttemptRecord` já inclui:

```text
process_id
```

mas o dispatcher atual não projeta o PID criado de volta para o attempt.

O Gate I12 deve conectar a evidência de process start ao estado durável do attempt.

## 25.1 Requisito

Quando um SUBPROCESS associado a Task começar:

```text
TaskAttempt.process_id
```

deve ser registrado o mais cedo possível com segurança.

## 25.2 Limitações do PID

PID isolado não é authority para:

```text
adotar
terminar
ou confiar
```

em um processo após restart.

PID pode ser reutilizado.

Para o MVP, `process_id` é evidence.

Não matar processo no startup apenas porque o PID coincide com um record stale.

## 25.3 Default seguro

Se o outcome de subprocess for incerto após perda do runtime:

```text
não relançar automaticamente command não idempotente
não matar silenciosamente PID possivelmente não relacionado
expor reconciliation required
```

---

# 26. Seam de lifecycle do Dispatcher

Uma implementação mínima pode permitir que `ExecutionDispatcher` reporte:

```text
process started
process id
process exited
```

de volta à persistência de Execution/Task.

Não permitir que o Dispatcher passe a ser owner do lifecycle da Task.

Ownership preferido continua:

```text
TaskRuntime / ExecutionRuntime
    controla estado durável de execução

ExecutionDispatcher
    controla launch/termination concreto do processo
```

---

# 27. AgentRun recovery

Um `AgentRun` deixado em `RUNNING` após restart nunca pode continuar provider state opaco.

Obrigatório:

```text
RUNNING AgentRun do runtime perdido
↓
inspecionar Task + ToolCalls + evidence do AgentRun
↓
deixar de tratar run antigo como ativo
↓
determinar continuação segura da Task
```

## 27.1 Comportamento mínimo do MVP

Um default seguro é:

```text
stale AgentRun.RUNNING
    -> outcome de interruption/failed recovery

parent Task
    -> PAUSED / recovery decision required
```

quando qualquer ToolCall executado puder ter side effect incerto.

## 27.2 Replanning

Uma ação futura ou explícita de recovery pode criar novo AgentRun usando:

```text
Task objective
Tool results concluídos
artifacts
delegated context durável
authority atual
```

Não deve recuperar reasoning oculto.

## 27.3 Sem Agent restart silencioso

Não reiniciar automaticamente o Agent desde o começo só porque o run anterior foi interrompido.

Isso pode duplicar side effects de Tools.

---

# 28. Terminalização de AgentRun

Estados atuais de AgentRun:

```text
QUEUED
RUNNING
WAITING_CONFIRMATION
SUCCEEDED
FAILED
CANCELLED
```

A implementação pode:

```text
reutilizar FAILED com structured interruption result
```

ou introduzir estado mínimo específico de recovery se realmente necessário.

Evitar proliferação de enums sem ganho de correctness.

Qualquer representação escolhida precisa distinguir:

```text
falha normal de agent
vs
runtime interruption / uncertain recovery
```

por evidence estruturado e durável.

---

# 29. Confirmation recovery

Confirmation já é durável.

O Gate I12 precisa garantir que:

```text
ConfirmationRequest pendente
+
ToolCall WAITING_CONFIRMATION
+
Task WAITING_CONFIRMATION
```

permaneçam coerentemente ligados após restart.

## 29.1 Não pode

```text
autoaprovar
criar ConfirmationRequest duplicado
consumir Grant duas vezes
```

## 29.2 Approval após restart

Quando o usuário aprovar depois do restart:

```text
semântica atual de Policy / Grant continua valendo
```

Se a confirmation não puder mais ser honrada com segurança:

```text
invalidar/fail closed
```

em vez de executar authority stale.

---

# 30. Recalcular authority

Recovery deve preservar intent, não authorization stale.

Os itens abaixo podem mudar através de restart:

```text
Grant revoked
Grant expired
SESSION Grant deixou de ser válido
Delegation expirou/revogada
Tool disabled
Tool registration/version mudou
resource deixou de ser permitido
```

Toda execução retomada/repetida deve passar pelos paths normais atuais de autorização.

Não adicionar bypass de recovery no PolicyEngine.

---

# 31. SESSION Grants

Um `SESSION` Grant pertence à semântica explícita da client/session.

Recovery não deve tratar uma nova Core RuntimeSession como prova de que um SESSION Grant antigo continua válido.

A semântica existente de `PermissionGrant.matches()` continua authoritative.

Sem widening implícito de authority.

---

# 32. Integração de Memory recovery

No startup, detectar trabalho de Memory durável que esteja:

```text
candidate APPROVED + persistence PENDING/FAILED quando replay for permitido
memory operation PENDING/FAILED quando replay for permitido
```

Não retry automaticamente todo `FAILED`.

Usar a semântica de errors existente do Memory.

Recovery automático elegível deve ser conservador, por exemplo falha de transporte/interruption quando a mesma identidade idempotente torna replay seguro.

Nunca retry automaticamente:

```text
validation failure
policy rejection
idempotency conflict
memory lifecycle conflict
authentication/configuration error
```

Uma primeira implementação pode apenas expor evidence de recovery pendente em vez de fazer replay automático caso a classificação não possa ser feita com segurança.

---

# 33. Scheduler recovery continua especializado

Não incorporar o Scheduler inteiro a uma state machine genérica de recovery.

A semântica atual do Scheduler já trata:

```text
missed one-shot
durable occurrence
Task wakeup
limite de duplicate wakeup
```

O I12 deve integrar a ordem de startup e reutilizar os métodos de recovery existentes.

---

# 34. Notification / attention para recovery

Situações de recovery que exigem atenção humana devem produzir Notification durável voltada ao usuário usando o boundary existente.

Exemplos:

```text
Task pausada após side effect incerto
outcome de shell execution incerto
AgentRun interrompido exigindo restart/replan decision
confirmation invalidada
```

Notification não é authority.

Acknowledge de Notification não pode por si só executar retry de Tool.

---

# 35. Requisitos de Audit para I12

Reutilizar `AuditService`.

Evidence obrigatório inclui eventos semanticamente equivalentes a:

```text
RECOVERY_PASS_STARTED
RECOVERY_TASK_CLASSIFIED
RECOVERY_TOOLCALL_UNCERTAIN
RECOVERY_TASK_REQUEUED
RECOVERY_TASK_PAUSED
RECOVERY_AGENT_INTERRUPTED
RECOVERY_MEMORY_OPERATION_DETECTED
RECOVERY_PASS_COMPLETED
```

Os nomes exatos pertencem à implementação.

Audit deve preservar:

```text
runtime session
Task
Attempt
AgentRun
ToolCall
correlation
causation
classification/reason seguros
```

Nunca incluir:

```text
secret
full shell output
argumentos sensíveis de Tool além das regras existentes de minimização
provider hidden state
```

---

# 36. Recovery health

Expor recovery como health de startup/runtime quando útil.

Componente conceitual:

```text
recovery
```

Possíveis estados:

```text
HEALTHY
DEGRADED
```

O Core pode iniciar mesmo quando trabalho recuperável exige decisão humana, desde que:

```text
trabalho incerto esteja pausado com segurança
nenhuma execução duplicada esteja acontecendo
usuário possa inspecionar
```

Falhar startup somente quando recovery não conseguir estabelecer um estado operacional seguro.

---

# 37. Estratégia de crash simulation

O Gate I12 exige crash tests determinísticos.

Não depender exclusivamente de:

```text
await core.stop()
```

porque graceful shutdown não é crash.

Os testes precisam simular estado persistido como se o processo tivesse desaparecido entre checkpoints significativos.

Usar combinação de:

```text
fixtures diretas de persistência
child Core process tests quando agregarem valor
Fake Tools com synchronization barriers
fixture commands de subprocess
```

Evitar sleeps de timing frágeis quando um barrier/event puder tornar a janela de crash determinística.

---

# 38. Janelas de crash obrigatórias

Testar no mínimo estas janelas.

## 38.1 Task persistida, execução ainda não iniciada

```text
Task + intent durável persistidos
↓ CRASH
startup
↓
Task continua recuperável
```

## 38.2 Tool read-only iniciou, resultado não persistido

```text
ToolCall RUNNING
↓ CRASH
startup
↓
classificação segura
↓
retry limitado
↓
single final success
```

## 38.3 Tool mutating pode ter commitado

```text
ToolCall RUNNING
↓ side effect acontece
↓ CRASH antes do persistence de completion
startup
↓
SEM blind retry
↓
PAUSED / reconciliation required
```

## 38.4 Subprocess iniciou

```text
TaskAttempt.process_id persistido
↓ CRASH
startup
↓
sem adoção/kill inseguro de PID
↓
incerteza exposta
```

## 38.5 AgentRun executando

```text
AgentRun RUNNING
↓ pelo menos um ToolCall concluído/incerto
↓ CRASH
startup
↓
sem continuação de reasoning oculto
↓
Task/Agent classificados com segurança
```

## 38.6 WAITING_CONFIRMATION

```text
confirmation persistida
↓ CRASH
startup
↓
continua existindo apenas uma confirmation
↓
approval path continua seguro
```

## 38.7 WAITING_SCHEDULE

O comportamento existente deve continuar verde.

## 38.8 Janela de remote commit de Memory

Usar FakeMemoryProvider para provar:

```text
remote create/supersede/forget succeeded
↓ completion local ausente
↓ restart/replay com mesma idempotency identity
↓ converge sem recurso duplicado
```

---

# 39. Teste vertical do Gate I12

Criar teste dedicado do Gate, por exemplo:

```text
tests/integration/gate/test_gate_i12_recovery.py
```

Ele precisa provar a invariável de produto:

```text
Trabalho durável interrompido
não desaparece
e
não duplica silenciosamente side effects críticos.
```

Não exige OpenAI real.

Não exige Sofias Memory real na suite padrão.

---

# 40. Matriz de aceite do Gate I12

```text
[ ] interruption de RuntimeSession anterior é detectada
[ ] startup recovery ocorre antes da execução normal de trabalho antigo
[ ] durable Task intent sobrevive a crash pré-execução
[ ] stale QUEUED Task pode ser reconstruída quando seguro
[ ] stale RUNNING Task nunca é retomada às cegas
[ ] incerteza de Tool read-only/idempotent pode recuperar com segurança
[ ] incerteza mutating/non-idempotent nunca blind-retries
[ ] stale ToolCall RUNNING deixa de permanecer ordinary DUPLICATE_IN_FLIGHT para sempre
[ ] PID/start evidence de subprocess é capturado duravelmente em Task execution
[ ] startup nunca mata/adota stale PID apenas pela identidade numérica
[ ] AgentRun stale RUNNING é reconciliado sem hidden-state continuation
[ ] WAITING_CONFIRMATION sobrevive sem confirmation duplicada
[ ] baseline WAITING_SCHEDULE continua verde
[ ] Grant/Delegation/Tool Policy é recalculada antes de execução retomada
[ ] pending Memory replay usa identidade de operação estável existente
[ ] recovery que exige decisão humana produz attention/evidence durável
[ ] recovery é totalmente auditável
[ ] não existe novo authorization bypass
[ ] crash tests são determinísticos
[ ] regressão completa passa
[ ] CI remoto passa
```

---

# 41. Não objetivos explícitos de I12

Não implementar:

```text
distributed worker leases
multi-host recovery
universal transaction coordinator
global exactly-once delivery
workflow engine
process checkpoint/restore
Agent chain-of-thought persistence
automatic compensation framework
generic saga framework
Windows service manager
container orchestration
```

Não adicionar complexidade apenas porque talvez seja útil pós-MVP.

---

# 42. Formato esperado da implementação de I12

Áreas provavelmente afetadas:

```text
core/runtime/
    recovery.py ou equivalente

core/core/
    startup composition/order

core/execution/
    task_runtime.py
    runtime.py
    dispatcher.py
    store.py
    models.py

core/memory/
    somente recovery seam se necessário

core/proactivity/
    integração de startup apenas quando necessário

core/persistence/
    migration somente se recovery metadata durável não couber no schema existente

core/tests/
    recovery unit/integration direcionado
    Gate I12
```

Isso é orientação, não layout obrigatório.

---

# 43. Política de migration para I12

A última migration atual do Slice 05 deve ser:

```text
0009_cognitive_memory_runtime
```

Se recovery durável exigir mudanças de schema:

```text
criar próxima migration
não reescrever migrations anteriores
```

Possíveis candidatos, somente se realmente necessários:

```text
ToolCall recovery status/timestamps
Task recovery metadata
AgentRun interruption reason
runtime-session ownership linkage
```

Preferir fields existentes quando a semântica continuar clara.

Não criar migration apenas para espelhar enums em memória.

---

# 44. Quality gates de I12

Antes do fechamento:

```text
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
git diff --check
```

Também executar baseline de Desktop package se o CI continuar exigindo:

```text
uv run python -m PyInstaller --noconfirm client/SofiaAssistant.spec
```

O Gate I12 só fecha após:

```text
local green
+
push
+
CI remoto verde
+
revisão independente
```

---

# 45. Fechamento do Gate I12

Em caso de sucesso, registrar:

```text
Gate I12 — CLOSED — REMOTE VERIFIED
SA-B033 — DONE
```

Manter o Slice 08 em:

```text
core/docs/exec-plans/active/
```

porque o Gate I13 ainda permanece.

Não mover o Slice 08 para `completed/` após o I12.

---

# 46. Gate I13 — MVP Ready

**Escopo:** SA-B034  
**Status inicial:** BLOCKED BY I12

Quando I12 fechar:

```text
Gate I13 = READY
```

---

# 47. Objetivo do Gate I13

Provar que todo o produto funciona como um MVP integrado.

Este Gate não é desculpa para desenvolvimento arbitrário de novas features.

A ação padrão para um cenário falhando é:

```text
encontrar a menor integração ausente
↓
corrigir
↓
adicionar evidence
```

e não:

```text
redesenhar subsystem
```

---

# 48. Matriz de cenários do PRD

O Gate I13 precisa provar os dez cenários definidos no Technical Backlog Map.

```text
A — Text Conversation
B — Realtime Voice
C — Memory
D — Filesystem
E — Shell
F — Web Research
G — Reminder
H — Agent
I — Recovery
J — Provider Routing
```

Cada cenário precisa ter:

```text
evidência determinística padrão de Gate
```

e smoke de integração real quando explicitamente apropriado.

---

# 49. Cenário A — Text Conversation

Precisa provar:

```text
client autenticado
↓
Conversation
↓
Turn
↓
ContextBuilder
↓
provider abstraction
↓
stream/final response
↓
durable Conversation continua authoritative
```

Reutilizar testes existentes do I2.

I13 deve adicionar apenas cenário end-to-end de release caso os Gate tests atuais ainda não exercitem a composição atual/empacotada.

OpenAI real não é requisito apenas para A.

---

# 50. Cenário B — Realtime Voice

Precisa provar:

```text
authenticated realtime connection
↓
audio/transcript lifecycle
↓
barge-in/interruption
↓
canonical Turn
↓
Conversation authority preservada
```

Reutilizar Gate I3.

Não exigir hardware de microfone no CI.

Fake realtime provider determinístico continua válido como evidence de release.

Um live provider smoke já bem-sucedido pode permanecer como evidence histórica, salvo se mudanças atuais afetarem essa integração.

---

# 51. Cenário C — Memory

Precisa provar:

```text
Conversation A
↓
MemoryCandidate
↓
Sofias Memory
↓
Conversation B recall
↓
ContextBuilder
↓
provider context
```

O Gate test padrão pode usar FakeMemoryProvider.

Evidence de release também deve preservar o smoke real já comprovado contra:

```text
https://pefil-sofias-memory.q8cqqr.easypanel.host
```

quando a instância estiver alcançável e configurada via SecretService.

Não colocar API key em CI ou no repositório.

---

# 52. Cenário D — Filesystem

Precisa provar:

```text
filesystem.read
filesystem.write
```

através de:

```text
Tool Registry
Policy
Grant/Confirmation
Execution
Audit
```

Incluir evidence de path canonicalization/traversal safety.

Reutilizar I8.

---

# 53. Cenário E — Shell

Precisa provar:

```text
explicit executable + argv
scoped execution
confirmation/authority
filtered environment
timeout
bounded output
Audit
```

Sem shell-string execution.

Sem herança de secrets além do comportamento de environment aprovado.

Reutilizar I8 mais evidence de I12 para shell execution interrompido.

---

# 54. Cenário F — Web Research

Requisito do backlog:

```text
Search
+
multiple sources
+
synthesis
```

O baseline atual já prova capability segura de Web Search/Read.

I13 precisa fechar o vertical de produto ausente:

```text
research query
↓
search results
↓
leitura de múltiplas fontes distintas
↓
evidence/context limitado
↓
provider synthesis
↓
resultado com attribution/evidence references das fontes
```

Usar fixtures fake determinísticas de web/search/provider no CI padrão.

Não exigir disponibilidade de internet na suite normal.

## 54.1 Regra mínima de implementação

Se não existir seam de orchestration que faça multi-source synthesis, adicionar o menor seam explícito possível.

Possíveis casas:

```text
bounded research service
ou
specialized Task/Agent flow
```

Preferir reutilizar Agent runtime e Web Tools existentes se isso produzir um caminho limpo de MVP.

Não construir navegador autônomo genérico.

---

# 55. Cenário G — Reminder

Precisa provar:

```text
criação autenticada de reminder
↓
persist
↓
Core restart
↓
missed/due schedule
↓
durable Event
↓
Notification
↓
client recupera/exibe
```

I7 já cobre grande parte disso.

I13 deve reutilizar, não duplicar arquitetura do Scheduler.

---

# 56. Cenário H — Agent

Precisa provar Agent especializado criado pela root com:

```text
Task
↓
AgentRun
↓
contexto reduzido
↓
subset reduzido de Tools
↓
authority reduzida
↓
múltiplos ToolCalls
↓
bounded result
↓
Audit
```

O Development Analysis Agent já fornece esse vertical.

I13 deve incluir as semânticas de recovery do I12 na assurance story, mas não precisa tornar Agent universalmente resumível.

---

# 57. Cenário I — Recovery

Gate I13 consome evidence do Gate I12.

Precisa provar:

```text
Task interrompida
↓
Core restart
↓
reconciliation seguro
↓
nenhum side effect crítico duplicado
↓
durable work não é perdido silenciosamente
```

I13 não pode ignorar findings de I12.

---

# 58. Cenário J — Provider Routing

Requisito do backlog:

```text
mais de um provider/model pode participar
sem alterar a identidade da Sofia
```

O ModelRegistry/CapabilityRouter existente já suporta múltiplos model registrations.

I13 precisa fornecer um vertical explícito provando:

```text
Sofia identity / Conversation
permanece constante
enquanto
capability/locality seleciona bindings diferentes de provider/model
```

Exemplos:

```text
TEXT -> provider/model A
VISION -> provider/model B
```

ou:

```text
LOCAL_ONLY -> local model
CLOUD_ALLOWED -> cloud model
```

O teste precisa mostrar que provider identity é escolha de execução, não identidade da Sofia.

Não é necessário segundo provider cloud de produção apenas para satisfazer esse cenário.

Fakes determinísticos com provider/model identities distintos são aceitáveis.

---

# 59. Teste integrado de release do I13

Criar módulo ou suite de release-level test, por exemplo:

```text
tests/integration/gate/test_gate_i13_mvp_release.py
```

Não copiar todos os testes anteriores para um único teste gigante.

Em vez disso:

```text
pequenos verticals integrados
+
referências explícitas à coverage dos Gates anteriores
```

A suite deve ser legível como documento executável de release acceptance.

---

# 60. Smoke de composição em nível de produto

I13 precisa testar composição real do `SofiaCore`, não apenas services instanciados individualmente.

Ao menos um smoke determinístico deve:

```text
criar Core
↓
start
↓
client session autenticada
↓
exercitar operações representativas do MVP
↓
stop
↓
restart
↓
verificar estado durável
```

Usar diretório de dados temporário.

Não usar estado da máquina do usuário.

---

# 61. Smoke do Desktop empacotado

CI já constrói com PyInstaller.

I13 deve adicionalmente provar que o executável empacotado inicia em um modo de smoke relevante para release.

Preferência:

```text
SofiaAssistant.exe --smoke
```

ou equivalente atual.

Aceite:

```text
process starts
imports/resources críticos resolvem
exit 0
```

Não exigir automação interativa de GUI no CI, salvo se já estiver estável.

---

# 62. Versão de release candidate

A versão atual do package é:

```text
0.1.0.dev0
```

I13 precisa decidir e registrar a primeira versão de release MVP de acordo com a convenção existente do repositório.

Candidato padrão:

```text
0.1.0
```

Não publicar/taguear silenciosamente outra versão.

A versão precisa ser consistente entre:

```text
pyproject
runtime/version surface
packaging metadata
release notes
tag/release metadata, quando criado
```

---

# 63. Release readiness vs publicação

Aceite do Gate I13 significa:

```text
MVP está pronto para release
```

Etapas públicas como:

```text
Git tag
GitHub Release
binary attachment/distribution
```

devem acontecer como ação explícita de fechamento de release.

O LLM executor pode preparar toda a evidence automaticamente.

Não publicar secrets, `.env` local, credential material ou databases de desenvolvimento.

---

# 64. Release notes

Preparar release notes concisas contendo:

```text
o que Sofia consegue fazer
boundaries arquiteturais/de segurança
cenários MVP suportados
limitações conhecidas
dependências externas opcionais
notas de setup
garantias de recovery
```

Não anunciar features deferred como implementadas.

Identificar explicitamente limitações relevantes do MVP, como:

```text
SANDBOX backend pode continuar fail-closed se ainda não houver backend de produção
sem workflow engine universal
sem autonomous plugin marketplace
sem wake word / continuous listening salvo se implementado em outro ponto
sem garantia exactly-once
```

---

# 65. Auditoria de configuração para release

Antes do fechamento do I13, auditar:

```text
.env.example
paths do SecretService
configuração da base URL do Memory
configuração do provider OpenAI
local client binding
data/artifact directories
timeouts
```

Garantir:

```text
nenhum secret no repo
nenhuma dependência de produção em descoberta implícita de .env
localhost continua autenticado
LAN não fica exposta por padrão
```

---

# 66. Auditoria de persistence para release

Verificar upgrade path:

```text
fresh database -> head
existing prior migration -> head
```

I13 deve rodar migration tests incluindo qualquer migration nova de I12.

Nenhum destructive reset faz parte do startup normal da aplicação salvo se isso estiver explicitamente desenhado.

---

# 67. Matriz de regressão de segurança

Antes do release MVP, provar que o trabalho de integração não enfraqueceu:

```text
autenticação de localhost
Policy antes de side effect protegido
semântica de confirmation
Grant narrowing
subset de Tools do Agent
workspace/path bounds
proteções SSRF de Web
shell argv/no-shell behavior
secrets somente via SecretService
Memory como untrusted context
cloud-context eligibility
redaction de Audit
recovery sem authorization bypass
```

---

# 68. Matriz de comportamento de failure/degraded

Release acceptance precisa incluir comportamento explícito em estado degradado para:

```text
Memory unavailable
AI provider unavailable
Realtime provider unavailable
falha de operação do Scheduler
falha de delivery de Notification
falha de Web source
recovery exigindo decisão humana
```

Core deve continuar utilizável quando a arquitetura define o subsystem como opcional/degradável.

Não transformar outage de subsystem opcional em global startup failure.

---

# 69. CI release gate

Baseline atual de CI roda:

```text
ruff
format check
mypy
pytest
PyInstaller
```

I13 pode adicionar job dedicado de release se for útil.

Não adicionar infraestrutura pesada de CI sem ganho material de confiança.

Um bom CI final inclui:

```text
quality
full deterministic tests
desktop package
package smoke
```

Integrações live opcionais devem continuar opt-in e protegidas por secrets.

---

# 70. Evidence de integração live

O MVP possui integrações reais cujo live smoke pode ser valioso:

```text
OpenAI text/realtime
Sofias Memory
```

Regras:

```text
não repetir live provider tests caros apenas por cerimônia
```

Reexecutar integrações live quando:

```text
o Slice atual alterar seu boundary
release evidence estiver stale/insuficiente
ou
usuário pedir explicitamente fresh release smoke
```

O live smoke do Sofias Memory feito no Slice 05 já é evidence histórica válida, salvo se I12/I13 alterar a integração de Memory.

---

# 71. Matriz de aceite do I13

```text
[ ] Cenário A — Text Conversation PASS
[ ] Cenário B — Realtime Voice PASS
[ ] Cenário C — Memory PASS
[ ] Cenário D — Filesystem PASS
[ ] Cenário E — Shell PASS
[ ] Cenário F — Web multi-source research + synthesis PASS
[ ] Cenário G — Reminder survives restart PASS
[ ] Cenário H — Root Agent with narrowed context/tools/authority PASS
[ ] Cenário I — Recovery sem silent duplicate side effect PASS
[ ] Cenário J — multi-provider/model routing sem alterar Sofia identity PASS

[ ] SofiaCore integrated smoke PASS
[ ] fresh migration PASS
[ ] upgrade migration PASS
[ ] full regression PASS
[ ] security regression PASS
[ ] PyInstaller package PASS
[ ] packaged executable smoke PASS
[ ] release configuration não contém secrets
[ ] release notes preparadas
[ ] versão finalizada de forma consistente
[ ] CI remoto verde
[ ] nenhum MVP release blocker restante
```

---

# 72. Não objetivos explícitos de I13

Não atrasar o MVP por:

```text
Plugin marketplace
SA-B032 salvo se explicitamente promovido para o release
full SANDBOX implementation se o contrato fail-closed aceito continuar suficiente
mobile client
cloud multi-user SaaS
distributed scheduler
advanced attention policy
wake word
continuous camera/microphone perception
Episode engine
Procedural Memory
generic workflow designer
universal autonomous browser
auto-update infrastructure
installer polish além do requisito de release
```

Trabalho pós-MVP deve continuar pós-MVP.

---

# 73. SA-B032 deferred

`SA-B032 Plugin Foundation` permanece:

```text
POST-KERNEL / OPTIONAL FOR FIRST MVP RELEASE
```

Slice 08 não deve puxar Plugin Foundation para o critical path, salvo se o Gate I13 revelar blocker concreto impossível de resolver sem ela.

Default:

```text
deferred
```

---

# 74. Quality commands do Gate I13

No mínimo:

```text
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
git diff --check

uv run python -m PyInstaller --noconfirm client/SofiaAssistant.spec
```

Depois executar o packaged smoke command estabelecido pela implementação.

---

# 75. Ledger de evidence de release

Antes do fechamento, registrar neste Slice:

```text
baseline SHA
I12 feature commit(s)
I12 closure commit
I12 CI run
I13 feature/integration commit(s)
release version commit
I13 closure commit
final HEAD
origin/main
CI run
package smoke
live smoke(s), se executados
known limitations
deferred findings
```

---

# 76. Estratégia de commits

Recomendada, não obrigatória.

## Gate I12

```text
feat(recovery): add startup recovery classification
feat(recovery): harden task tool and agent restart semantics
test(recovery): close Gate I12 crash scenarios
docs(plan): close Gate I12
```

Combinar quando um pacote for naturalmente coeso.

## Gate I13

```text
feat(mvp): close release integration gaps
test(mvp): add Gate I13 release scenarios
build(release): prepare MVP package/version
docs(release): close Slice 08 MVP gate
```

Não criar microcommits por arquivo.

---

# 77. Política de push / CI remoto

Depois que cada Gate chegar a um checkpoint local coerente:

```text
push origin/main
```

Observar CI.

Se a falha for causada pelo Gate:

```text
diagnosticar
corrigir
rerodar gates locais relevantes
commit
push
```

Não parar na primeira falha de CI quando a causa for conhecida e corrigível.

Após commit limpo/push de Gate, a revisão independente deve usar o repositório/CI do GitHub em vez de pedir outro self-audit verboso ao LLM executor.

---

# 78. Stop conditions — Gate I12

Parar para decisão humana somente se:

```text
ADR-0010 não puder ser implementado sem contradição
recovery seguro exigir mudança de authority boundary congelado
correctness exigir handling destrutivo de external side effects incertos
Tool obrigatório não conseguir expor durable intent suficiente para safe recovery
uma decisão de recovery exigir LLM authority
uma migration destruir durable work existente
```

Não parar por:

```text
naming
file layout
small helper abstractions
design de test fixture
formato menor de migration
```

---

# 79. Stop conditions — Gate I13

Parar para decisão humana se:

```text
um cenário MVP do PRD estiver genuinamente não implementado e exigir nova decisão de produto
release version conflitar com convenção documentada já existente
executável empacotado não atender baseline da plataforma MVP
security regression não puder ser corrigida localmente
dependência externa obrigatória estiver indisponível sem evidence determinística alternativa
```

Não inventar novo escopo de produto apenas porque release testing revelar oportunidades de polish.

---

# 80. Estado final esperado

Na conclusão bem-sucedida:

```text
Gate I12 — CLOSED — REMOTE VERIFIED
SA-B033 — DONE

Gate I13 — CLOSED — REMOTE VERIFIED
SA-B034 — DONE

Slice 08 — COMPLETED — REMOTE VERIFIED

MVP RELEASE READINESS — PASSED
```

Então mover:

```text
core/docs/exec-plans/active/
Sofia's Assistant — Technical Backlog Slice 08.md
```

para:

```text
core/docs/exec-plans/completed/
Sofia's Assistant — Technical Backlog Slice 08.md
```

---

# 81. Definição de MVP readiness

MVP readiness não significa que toda capability futura existe.

Significa que a arquitetura já aprovada sobreviveu a execução integrada realista.

O release precisa demonstrar:

```text
Sofia consegue conversar
Sofia consegue falar
Sofia consegue lembrar
Sofia consegue agir sob Policy
Sofia consegue executar trabalho durável
Sofia consegue delegar
Sofia consegue reagir depois
Sofia consegue usar o computador
Sofia pode ser auditada
Sofia consegue sobreviver a restart com segurança
Sofia pode ser usada por um client real
```

preservando:

```text
AI proposes
Runtime authorizes
Executor acts
```

---

# 82. Template de resumo de execução do Gate I12

Ao concluir I12, acrescentar:

```text
## Gate I12 Closure Ledger

Baseline:
Feature commits:
Closure commit:
Final Gate HEAD:
CI run:

Recovery architecture:
Migration:
Task recovery:
ToolCall uncertainty:
Subprocess recovery:
AgentRun recovery:
Confirmation recovery:
Memory operation recovery:
Authority recalculation:
Scheduler regression:

Crash tests:
Full pytest:
Ruff:
Format:
Mypy:
Packaging:

Deferred findings:
Real blockers:

Gate I12 — CLOSED — REMOTE VERIFIED
```

---

# 83. Template de resumo de execução do Gate I13

Ao concluir I13, acrescentar:

```text
## Gate I13 / Slice 08 Closure Ledger

Baseline:
Feature/integration commits:
Version/release commit:
Closure commit:
Final HEAD:
origin/main:
CI run:

Scenario A:
Scenario B:
Scenario C:
Scenario D:
Scenario E:
Scenario F:
Scenario G:
Scenario H:
Scenario I:
Scenario J:

Migration fresh:
Migration upgrade:
Security regression:
Full pytest:
Ruff:
Format:
Mypy:
PyInstaller:
Packaged smoke:
Live integrations:

Release version:
Release notes:
Known limitations:
Deferred:
Blockers:

Gate I13 — CLOSED — REMOTE VERIFIED
Slice 08 — COMPLETED — REMOTE VERIFIED
MVP RELEASE READINESS — PASSED
```

---

# 84. Conclusão da auditoria inicial

A auditoria atual **não** indica necessidade de novo ADR.

O principal trabalho faltante do Gate I12 é:

```text
durable general Task execution intent
+
startup reconciliation para Tasks não agendadas
+
classificação de ToolCall uncertainty
+
subprocess start evidence
+
semântica de interruption de AgentRun
+
recalcular authority atual
```

Os principais gaps remanescentes de integração do Gate I13 são:

```text
Cenário F
Web Search + multiple source reads + synthesis

Cenário I
depende do Gate I12

Cenário J
prova explícita em nível de produto de multi-provider/model routing

mais
packaged MVP smoke / version / release ledger
```

Todo o restante deve, preferencialmente, ser provado reutilizando evidence dos Gates já concluídos.

---

# 85. Status inicial

```text
Slice 08
    MATERIALIZADO PARA REVISÃO

Gate I12
    READY APÓS APROVAÇÃO DO SLICE

Gate I13
    BLOQUEADO PELO I12

Real external blocker
    NONE
```

Nenhuma implementação deve começar antes da revisão/aprovação deste Slice.

---

# 86. Gate I12 Closure Ledger

```text
Baseline:
436bcf4a4d4ce179e8667da24ef62005e8fc0e2c

Feature commits:
ae4e2d3 feat(recovery): add startup recovery coordinator and durable Task intent
4ce1749 test(recovery): close Gate I12 crash scenarios

Closure commit:
(recorded after this commit lands)

Final Gate HEAD:
4ce1749fbf11aa9cd2a497f275a7232fd9fea0f2

CI run:
(recorded after remote verification)

Recovery architecture:
StartupRecoveryCoordinator (core/src/sofias_assistant/runtime/recovery.py),
composed in SofiaCore.start() after ExecutionRuntime/TaskRuntime/
AgentRuntime/Memory and before ProactivityRuntime.start(). It owns no
recovery logic itself; it calls TaskRuntime.recover_stale_work() and
MemoryOrchestrator.recover_pending_operations() and wraps the whole pass
with RECOVERY_PASS_STARTED/RECOVERY_PASS_COMPLETED audit. Reference
harvest: no external Brahma/Mark LI clone was available in this
environment (same finding as Slice 05); implementation is clean-room
from ADR-0010 and the existing runtime.

Migration:
0010_task_attempt_grant — adds task_attempts.grant_id (nullable UUID).
No other schema change was needed; every other recovery signal reuses
existing TaskRecord/TaskAttemptRecord/ToolCallRecord/AgentRunRecord
fields (status strings, error_code/message, process_id).

Task recovery:
TaskRuntime.create_task() now persists the ToolCall (status QUEUED) and
attempt_number=1 (status QUEUED) synchronously, before scheduling any
in-memory runner — closing the Gap A crash window. recover_stale_work()
reconciles every non-WAITING_SCHEDULE non-terminal Task: QUEUED
reconstructs and re-claims when durable intent exists; RUNNING never
blind-resumes (reconciles from a completed ToolCall's durable evidence,
retries when idempotent/NONE-side-effect and uncertain, pauses
otherwise); WAITING_CONFIRMATION is validated for a single coherent
PENDING confirmation; CANCELLING reconciles to CANCELLED or pauses.
WAITING_SCHEDULE Tasks are explicitly skipped, left to the existing
specialized recover_scheduled_tasks() path.

ToolCall uncertainty:
A ToolCall left RUNNING by a lost runtime session is classified, never
left as ordinary DUPLICATE_IN_FLIGHT indefinitely: retry-safe
(idempotent AND side_effect NONE) resets it to QUEUED and requeues the
Task; otherwise its status becomes "RECOVERY_REQUIRED" and the Task
pauses.

Subprocess recovery:
ExecutionDispatcher.dispatch()/_subprocess() gained an
on_process_started callback invoked right after the child process
starts; TaskRuntime._run() persists the PID into
TaskAttempt.process_id via this callback. Recovery reads process_id
only as evidence — it never adopts or kills a process by PID alone.

AgentRun recovery:
A stale RUNNING AgentRun is marked FAILED with a structured
{"error": "runtime_interruption", "recovery_required": True} result;
its parent Task is paused (REQUIRES_USER_DECISION) instead of
resuming hidden provider reasoning or restarting the Agent silently.

Confirmation recovery:
WAITING_CONFIRMATION Tasks are reconciled against the durable
ConfirmationRequest: still PENDING survives untouched; missing or
already-resolved-but-unobserved fails closed to PAUSED/
RECOVERY_REQUIRED rather than auto-approving or duplicating.

Memory operation recovery:
MemoryOrchestrator.recover_pending_operations() detects APPROVED
candidates and operations left PENDING/FAILED. Auto-replay (via the
existing idempotent retry_pending_candidate()/retry_pending_operation())
is limited to never-attempted work and to transport-interruption
failures (safe_failure_code == UNAVAILABLE); every other failure
category is only ever surfaced as durable evidence
(RECOVERY_MEMORY_OPERATION_DETECTED), never auto-replayed.

Authority recalculation:
No recovery path bypasses PolicyEngine. Every resumed/retried
execution re-enters ExecutionRuntime.invoke(), which always evaluates
Policy fresh. TaskAttempt.grant_id (migration 0010) lets a
reconstructed/retried attempt reference the grant it originally used,
but that reference is always re-validated live (ACTIVE/expiry/
revocation/scope) at the moment of use — never a cached decision, and
never invented when none is known.

Scheduler regression:
recover_scheduled_tasks() and its existing test coverage
(test_gate_i7_proactivity.py) are unchanged and green; the new general
recovery pass explicitly excludes any Task tied to a TASK_WAKEUP
schedule so the two passes never race on the same Task (proven by
Window G).

Crash tests:
tests/integration/gate/test_gate_i12_recovery.py — 10 passed. Windows
A–H from Slice §38 plus a durable-evidence reconciliation case and a
recovery-notification case, all using deterministic direct-persistence
fixtures (no real process kills, no sleeps).

Full pytest:
660 passed, 4 skipped (pre-existing opt-in OpenAI/OpenAI Realtime/
Sofias Memory live/Windows Credential Manager smokes; no Gate
correctness skipped).

Ruff:      PASS (uv run ruff check .)
Format:    PASS (uv run ruff format --check . — 175 files already formatted)
Mypy:      PASS (uv run mypy src tests — 175 source files, no issues)
Packaging: PASS (uv run python -m PyInstaller --noconfirm client/SofiaAssistant.spec;
           dist/SofiaAssistant.exe --smoke → exit code 0)

Deferred findings:
- Fine-grained per-ToolCall side-effect analysis for AgentRun recovery
  (proving zero side effects before offering auto-resume) remains
  future work, per Slice §27.1's explicit minimal-safe-behavior
  allowance; MVP always pauses a stale AgentRun for human decision.
- Recovery evidence age/retention and any UI-level surfacing beyond the
  existing Notification boundary remain out of scope for I12.

Real blockers: none.

Gate I12 — CLOSED — REMOTE VERIFIED (pending final CI confirmation below)
```
