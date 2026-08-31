# ADR-0002 — Operational Persistence Architecture

**Status:** Accepted  
**Project:** Sofia's Assistant  
**Decision date:** 2026-08-31  
**Scope:** Banco operacional, ownership dos dados, migrations, repositories e recovery state

---

# 1. Context

O Sofia's Assistant precisa persistir estado operacional independente da memória cognitiva de longo prazo.

Esse estado inclui, entre outros:

- conversations;
- conversation turns;
- Tasks;
- AgentRuns;
- Permission Grants;
- Delegations;
- schedules;
- reminders;
- eventos persistentes;
- confirmations pendentes;
- settings;
- audit records;
- execution metadata;
- recovery state.

Esses dados possuem natureza diferente da memória armazenada pelo Sofias Memory.

O Sofias Memory representa conhecimento cognitivo persistente.

O banco operacional do Sofia's Assistant representa o estado necessário para o runtime continuar funcionando corretamente.

Portanto:

```text
Operational State ≠ Cognitive Memory
```

---

# 2. Decision

O Sofia's Assistant possuirá um **Operational Store próprio**, inicialmente baseado em **SQLite**.

A arquitetura será:

```text
                Sofia Core
                    │
             Domain Services
                    │
               Repositories
                    │
            Persistence Layer
                    │
                  SQLite
```

O restante do domínio não dependerá diretamente de SQLite.

SQLite será a implementação inicial do storage operacional, não a definição do domínio.

---

# 3. Ownership

O Sofia Assistant Operational Store será authoritative para estado operacional.

Exemplos:

```text
Task
AgentRun
Grant
Delegation
Schedule
Reminder
Conversation
AuditEntry
```

O Sofias Memory será authoritative para memória cognitiva persistente.

Exemplos:

```text
Profile Memory
Semantic Memory
Episodic Memory
Procedural Memory
Knowledge Sources
```

Nenhum dos dois deverá assumir a autoridade do outro.

---

# 4. Why SQLite

SQLite é adotado como implementação inicial porque o produto é:

- local-first;
- single-user por instalação;
- desktop-first;
- executado inicialmente em uma única máquina;
- sem requisito de cluster;
- sem necessidade de administração de servidor de banco;
- dependente de instalação simples.

SQLite reduz:

- dependências operacionais;
- configuração;
- consumo de recursos;
- superfície de falha;
- complexidade de distribuição.

Ao mesmo tempo, oferece:

- transações;
- constraints;
- índices;
- migrations;
- recovery após restart;
- persistência durável;
- capacidade suficiente para o MVP.

---

# 5. SQLite Is Not an Embedded Cache

O banco não será tratado como storage descartável.

Dados como:

```text
PermissionGrant
Delegation
Task
Schedule
AuditEntry
```

podem possuir consequências de segurança ou continuidade.

Portanto o schema deverá ser tratado com disciplina semelhante a qualquer banco de produção.

Isso implica:

- migrations versionadas;
- constraints;
- transações;
- testes de migration;
- backup/export quando necessário;
- startup compatibility checks.

---

# 6. Repository Boundary

Domínio e services deverão consumir contratos de persistence.

Exemplo conceitual:

```text
TaskService
    ↓
TaskRepository
    ↓
SQLiteTaskRepository
```

e não:

```text
TaskService
    ↓
sqlite3.execute(...)
```

Essa abstração existe para preservar boundaries de domínio, não para suportar dezenas de bancos.

---

# 7. Repository Philosophy

Repositories deverão representar operações de domínio relevantes.

Preferir:

```text
task_repository.claim_next(...)
grant_repository.list_effective_for_subject(...)
delegation_repository.get_active(...)
```

em vez de abstrações genéricas excessivas como:

```text
repository.find(table, filters)
repository.update_anything(...)
```

O objetivo é preservar invariantes e tornar concorrência/transações explícitas.

---

# 8. Transactions

Operações que alterem múltiplos estados relacionados deverão utilizar boundary transacional explícito.

Exemplo:

```text
create Task
+
persist Delegation relation
+
emit durable domain event
```

não deverá produzir estado parcial observável em caso de falha intermediária.

A implementação concreta de Unit of Work será definida durante o backlog técnico.

---

# 9. Concurrency Model

Mesmo sendo single-user, Sofia poderá possuir concorrência interna.

Exemplos:

- conversation ativa;
- scheduler;
- Task worker;
- AgentRun;
- EventSource;
- Desktop Client;
- background operations.

Portanto "single-user" não significa "single-threaded".

O modelo de persistence deverá considerar:

- transações curtas;
- lock contention;
- atomic state transitions;
- concorrência entre workers;
- idempotência quando aplicável.

---

# 10. SQLite Configuration

A implementação deverá avaliar configurações apropriadas para workload concorrente local.

Como baseline arquitetural, deverá ser considerado o uso de:

```text
WAL mode
foreign_keys = ON
busy timeout
```

quando tecnicamente adequado.

Valores concretos serão definidos e testados no backlog.

---

# 11. Migrations

Migrations serão obrigatórias desde a primeira versão persistente.

Não será aceitável alterar schema apenas por:

```text
if column_missing:
    alter_table()
```

durante startup normal.

O schema deverá possuir uma versão explícita.

---

# 12. Migration Authority

Uma única ferramenta/mecanismo de migrations será authoritative.

A escolha concreta será feita no Technical Backlog ou, caso gere decisão arquitetural relevante, em ADR complementar.

Possíveis alternativas incluem ferramentas associadas ao ORM escolhido ou Alembic.

O produto não manterá múltiplos sistemas concorrentes de migration.

---

# 13. Startup Compatibility

Durante startup, Sofia Core deverá verificar se o Operational Store é compatível com a versão atual da aplicação.

Casos como:

```text
database revision < application expected revision
```

ou:

```text
database revision > application supported revision
```

deverão produzir comportamento explícito.

O Core não deverá operar silenciosamente sobre schema incompatível.

---

# 14. Automatic Migrations

Este ADR não determina ainda se migrations serão aplicadas automaticamente durante upgrades do produto.

Contudo, qualquer mecanismo automático deverá:

- ser determinístico;
- ser versionado;
- falhar antes de iniciar o runtime quando incompatível;
- nunca modificar schema por heurística;
- preservar caminho de backup/recovery.

---

# 15. Core Operational Entities

O modelo deverá suportar, no mínimo, domínios persistentes equivalentes a:

```text
Conversation
ConversationTurn

Task
TaskStep / TaskExecution state

AgentRun

PermissionGrant
Delegation
ConfirmationRequest

Schedule
Reminder

PersistedEvent

AuditEntry

ApplicationSetting
```

Essa lista é conceitual.

Ela não congela tabelas ou schemas físicos.

---

# 16. Conversation Persistence

Conversation History poderá ser armazenado no Operational Store.

Isso permite:

- continuidade entre sessões;
- recuperação após restart;
- UI history;
- debugging;
- Memory Candidate extraction posterior.

Entretanto:

```text
Conversation row
```

não será automaticamente:

```text
Long-Term Memory
```

A promoção para memória cognitiva continuará sob responsabilidade do Memory Orchestrator.

---

# 17. Task Persistence

Tasks serão persisted before execution quando sua semântica exigir durabilidade.

Uma Task persistida deverá possuir identidade estável.

O sistema deverá conseguir distinguir, após restart:

- Task que nunca começou;
- Task que estava executando;
- Task aguardando confirmação;
- Task concluída;
- Task falhada;
- Task cancelada.

A state machine exata será definida no ADR-0010.

---

# 18. AgentRun Persistence

AgentRun será persistido separadamente de Task.

O Operational Store deverá permitir reconstruir:

```text
Task
    ↓
AgentRun
    ↓
ToolCall / Step
```

sem tornar AgentRun a unidade principal de trabalho.

---

# 19. Permission Persistence

Permission Grants persistentes serão armazenados no Operational Store.

Isso inclui informações como:

- subject;
- capability;
- resource scope;
- constraints;
- timestamps;
- expiration;
- revocation.

Esses registros possuem impacto direto em segurança.

Portanto alterações relevantes deverão ser auditáveis.

---

# 20. Delegation Persistence

Delegations poderão sobreviver a conversations e restarts.

O banco deverá preservar pelo menos:

- objective;
- scope;
- authority;
- lifecycle;
- resource bindings;
- status;
- timestamps.

Uma Delegation poderá existir independentemente da sessão que originalmente a criou.

---

# 21. Confirmation Persistence

Confirmações que bloqueiem Tasks longas poderão precisar sobreviver a restart.

Exemplo:

```text
Task
    status = waiting_confirmation

ConfirmationRequest
    action = git_push
```

Após reboot, Sofia deverá continuar sabendo que a operação depende de decisão do usuário.

---

# 22. Scheduler Persistence

Schedules e reminders deverão ser duráveis.

O banco deverá armazenar informações suficientes para reconstruir o Scheduler.

Timer puramente em memória não será authority.

---

# 23. Event Persistence

Nem todo Event será persistido.

Eventos cuja durabilidade seja necessária deverão possuir representação persistente.

Exemplos prováveis:

```text
PermissionGranted
TaskCompleted
ReminderDue
```

Eventos efêmeros de alta frequência poderão existir apenas no Event Bus em memória.

A policy de persistência será definida no ADR-0003.

---

# 24. Audit Persistence

Audit Trail será armazenado separadamente do logging convencional.

Registros de audit não deverão ser modificados silenciosamente para representar novo estado.

Quando possível, preferir semântica append-oriented.

Detalhes serão definidos no ADR-0015.

---

# 25. Settings

Configurações operacionais não sensíveis poderão ser persistidas no Operational Store.

Secrets não deverão ser armazenados ali em texto simples.

Exemplo:

```text
preferred_voice = ...
theme = ...
default_provider_policy = ...
```

podem ser settings.

Já:

```text
OPENAI_API_KEY
```

pertence ao SecretStore.

---

# 26. Soft Delete vs Hard Delete

Não haverá uma regra global única.

Cada domínio deverá definir sua própria semântica.

Exemplos:

### Audit

provavelmente nunca deve ser silenciosamente hard-deleted por operação comum.

### Conversation

pode permitir exclusão explícita.

### Grant

pode preferir `revoked_at` a apagar histórico.

### Task

estado histórico pode permanecer após conclusão.

A decisão deverá preservar auditabilidade e privacidade.

---

# 27. IDs

Entidades persistentes deverão possuir identificadores estáveis independentes da ordem física do SQLite.

A implementação poderá utilizar UUID/ULID ou outra estratégia apropriada.

A escolha concreta será tomada no backlog técnico.

IDs públicos/internos não deverão depender exclusivamente de `ROWID`.

---

# 28. Timestamps

Registros de domínio relevantes deverão utilizar timestamps normalizados.

Armazenamento deverá preservar tempo de forma não ambígua.

A apresentação em timezone local pertence ao client.

---

# 29. Recovery Marker

O banco deverá permitir ao runtime distinguir shutdown gracioso de interrupção inesperada quando isso for útil para recovery.

Uma estratégia possível:

```text
runtime_session
startup_at
shutdown_at
status
```

ou equivalente.

A implementação será detalhada posteriormente.

---

# 30. Recovery Responsibility

O banco preserva estado.

Ele não decide como recuperar uma operação.

Exemplo:

```text
Task.status = RUNNING
```

após crash é evidência de interrupção.

O Task Runtime deverá decidir:

```text
retry
resume
reconcile
fail
wait_user
```

conforme o tipo de operação.

---

# 31. Backup and Export

O design deverá preservar possibilidade de backup do Operational Store.

No mínimo, será necessário considerar futuramente:

- backup consistente;
- export;
- restore;
- version compatibility.

Essas capacidades não precisam fazer parte do primeiro MVP público, mas o storage não deverá impedir sua implementação.

---

# 32. Data Directory

O banco deverá residir em diretório de dados controlado pela aplicação, separado de:

- código-fonte;
- cache temporário;
- logs;
- secrets;
- arquivos sandbox.

A localização concreta por OS será definida no backlog de packaging/runtime.

---

# 33. Testability

Persistence deverá permitir testes com banco isolado.

Deverão existir testes de integração para:

- migrations;
- constraints;
- repository behavior;
- transactional boundaries;
- state transitions;
- crash/recovery scenarios relevantes.

Mocks não serão suficientes para validar toda a camada de persistence.

---

# 34. Alternatives Considered

## Alternative A — PostgreSQL

### Advantages

- concorrência robusta;
- familiaridade;
- capacidade de crescimento;
- excelente tooling.

### Rejected for initial runtime because

- exige serviço adicional;
- aumenta instalação e administração;
- piora experiência desktop local;
- é desnecessário para o workload inicial.

Poderá ser reconsiderado futuramente se requisitos mudarem significativamente.

---

## Alternative B — JSON files

### Advantages

- simples;
- fácil de inspecionar;
- nenhuma migration tool inicial.

### Rejected because

- concurrency frágil;
- transações inexistentes ou artesanais;
- constraints fracos;
- migrations difíceis;
- recovery e consistência mais arriscados;
- inadequado para Grants, Tasks e Audit.

---

## Alternative C — Sofias Memory as the only database

### Advantages

- uma única infraestrutura persistente;
- menos storages conceituais.

### Rejected because

misturaria:

```text
runtime state
```

com:

```text
cognitive memory
```

e transformaria o Sofias Memory em backend operacional específico do Assistant.

---

## Alternative D — In-memory only

### Advantages

- desenvolvimento inicial rápido.

### Rejected because

incompatível com:

- reminders;
- delegations;
- grants;
- Tasks longas;
- restart recovery;
- proatividade persistente.

---

# 35. Consequences

## Positive

- instalação local simples;
- estado durável;
- transações;
- base adequada para recovery;
- separação clara do Sofias Memory;
- testabilidade;
- evolução controlada de schema;
- ausência de servidor adicional.

## Negative

- migrations passam a ser preocupação desde cedo;
- concorrência SQLite precisa ser projetada conscientemente;
- long-running transactions devem ser evitadas;
- eventual mudança futura de banco terá custo;
- persistence layer exige disciplina arquitetural.

Os custos são considerados aceitáveis.

---

# 36. Architectural Invariants

### INV-001

Sofias Memory não é Operational Store.

### INV-002

SQLite não é acessado diretamente pela UI.

### INV-003

Services de domínio não executam SQL arbitrário como mecanismo padrão.

### INV-004

Migrations são a autoridade sobre schema evolution.

### INV-005

Tasks duráveis são persistidas antes de execução quando aplicável.

### INV-006

Secrets não são armazenados em texto simples no Operational Store.

### INV-007

Operational persistence deve suportar recovery.

### INV-008

Single-user não elimina necessidade de controle de concorrência.

### INV-009

Conversation History não vira memória cognitiva automaticamente.

### INV-010

Estados de segurança, como Grants e Delegations, possuem persistência explícita.

---

# 37. Deferred Decisions

Ainda serão definidos:

- ORM/query layer;
- migration framework;
- UUID vs ULID;
- schemas definitivos;
- exact transaction abstraction;
- SQLite connection strategy;
- backup tooling;
- encryption-at-rest strategy, caso necessária;
- retention policies;
- file system locations;
- runtime recovery schema.

---

# 38. Decision Summary

Sofia's Assistant utilizará um **Operational Store próprio baseado inicialmente em SQLite**, independente do Sofias Memory.

Esse store será authoritative para estado do runtime, incluindo Conversations, Tasks, AgentRuns, Grants, Delegations, Scheduler e Audit.

O acesso ocorrerá através de boundaries de persistence explícitos, com migrations obrigatórias desde o início.

SQLite será tratado como banco durável da aplicação, não como cache ou armazenamento descartável.

A arquitetura deverá suportar concorrência interna, recovery após restart e evolução segura do schema.