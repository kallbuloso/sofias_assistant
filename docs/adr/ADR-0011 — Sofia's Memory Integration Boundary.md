# ADR-0011 — Sofia's Memory Integration Boundary

**Status:** Accepted  
**Project:** Sofia's Assistant  
**Decision date:** 2026-08-31  
**Scope:** Long-term cognitive memory authority, operational memory boundary, integration contract, Memory Orchestrator and Context Builder interaction

---

# 1. Context

O Sofia's Assistant precisa manter continuidade cognitiva ao longo do tempo.

Essa continuidade inclui capacidades como:

- lembrar fatos relevantes;
- lembrar preferências;
- lembrar decisões;
- recuperar contexto de projetos;
- preservar episódios;
- aprender procedimentos;
- relacionar entidades e conceitos;
- consolidar experiências;
- esquecer ou superseder memória quando necessário.

O projeto já possui o **Sofias Memory**, desenvolvido como serviço independente de memória persistente e conhecimento.

O Sofias Memory já possui infraestrutura própria para:

- persistência;
- datasets;
- sources;
- documents;
- chunks;
- embeddings;
- entities;
- relations;
- graph projection;
- provenance;
- recall;
- forget;
- durable pipelines.

Ao mesmo tempo, o Sofia's Assistant precisa manter outros tipos de estado que não pertencem à memória cognitiva.

Exemplos:

- Conversation;
- current Turn;
- Working Memory;
- Task;
- AgentRun;
- Permission Grant;
- Delegation;
- ConfirmationRequest;
- Schedule;
- Event;
- Audit.

Misturar esses dois tipos de estado produziria acoplamento inadequado.

---

# 2. Decision

O **Sofias Memory será a autoridade da memória cognitiva persistente de longo prazo**.

O **Sofia's Assistant Operational Store será a autoridade do estado operacional do runtime**.

A integração ocorrerá através de contrato explícito.

Arquitetura conceitual:

```text
                 Sofia's Assistant
┌─────────────────────────────────────────┐
│                                         │
│ Conversation Runtime                    │
│ Working Memory                          │
│ Tasks / AgentRuns                       │
│ Grants / Delegations                    │
│ Events / Scheduler                      │
│                                         │
│ Context Builder                         │
│       │                                 │
│ Memory Orchestrator                     │
│       │                                 │
└───────┼─────────────────────────────────┘
        │
        │ Memory Provider Contract
        ▼
┌─────────────────────────────────────────┐
│              Sofias Memory              │
│                                         │
│ Persistent Cognitive Memory             │
│ Retrieval                               │
│ Provenance                              │
│ Knowledge Graph                         │
│ Embeddings                              │
│ Consolidation support                   │
│ Forget / lifecycle                      │
└─────────────────────────────────────────┘
```

---

# 3. Fundamental Rule

A regra central será:

```text
Assistant owns runtime cognition.
Sofias Memory owns persistent cognition.
```

O Assistant decide:

- o que está acontecendo agora;
- qual contexto precisa;
- o que pode virar memória;
- quando recuperar memória;
- como utilizar memória recuperada.

Sofias Memory decide:

- como persistir memória;
- como indexá-la;
- como relacioná-la;
- como recuperá-la;
- como manter seu lifecycle persistente.

---

# 4. Operational State

Os seguintes domínios pertencem ao Sofia's Assistant:

```text
Conversation
Turn
Working Memory
Task
AgentRun
PermissionGrant
Delegation
ConfirmationRequest
Schedule
Event
AuditEntry
Runtime settings
```

Esses dados não deverão ser persistidos no Sofias Memory apenas porque são "informação".

---

# 5. Cognitive Memory

Os seguintes domínios pertencem conceitualmente ao Sofias Memory:

```text
Profile Memory
Semantic Memory
Episodic Memory
Procedural Memory
Knowledge Sources
Persistent relationships
Long-term facts
Decisions
Learned procedures
```

O modelo exato será detalhado no ADR-0012.

---

# 6. Conversation History Is Operational

Conversation History pertence inicialmente ao Operational Store.

Ela existe para:

- continuidade de interface;
- reconstrução de Conversation;
- debugging;
- audit contextual;
- Memory Candidate extraction.

Conversation History não será automaticamente autoridade de Long-Term Memory.

---

# 7. Working Memory Is Operational

Working Memory pertence exclusivamente ao Sofia's Assistant.

Exemplos:

```text
current objective
temporary hypothesis
recent compiler error
active file
recent screenshot
active Task state
temporary ToolResult
```

Esses dados poderão desaparecer sem serem persistidos cognitivamente.

---

# 8. Persistent Memory Is Selective

Nem todo conteúdo observado pelo Assistant deverá ser persistido no Sofias Memory.

O fluxo será seletivo:

```text
Conversation / Event / Tool Observation
                ↓
         Memory Candidate
                ↓
        Memory Orchestrator
                ↓
       policy / classification
                ↓
          Sofias Memory
```

---

# 9. No Duplicate Semantic Memory Engine

O Sofia's Assistant não implementará uma segunda infraestrutura própria de:

- embeddings persistentes;
- vector database cognitivo;
- knowledge graph pessoal;
- semantic fact store;
- persistent memory ranking engine.

Essas responsabilidades pertencem ao Sofias Memory.

---

# 10. Local Operational Cache

O Assistant poderá manter caches temporários por performance.

Exemplo:

```text
recently retrieved memories
```

Isso não cria nova authority.

Cache deve ser considerado reconstruível.

---

# 11. Integration Boundary

A integração será feita através de contrato explícito.

Conceitualmente:

```text
MemoryProvider
```

com uma implementação:

```text
SofiasMemoryAdapter
```

O domínio do Assistant deverá depender da abstração, não de internals do Sofias Memory.

---

# 12. Forbidden Coupling

Não será permitido como arquitetura:

```python
from sofias_memory.repositories import EntityRepository
```

ou:

```python
from sofias_memory.services import RecallService
```

dentro do Sofia's Assistant.

Também não será permitido acessar diretamente:

- PostgreSQL do Sofias Memory;
- pgvector;
- Neo4j;
- tabelas internas;
- graph_outbox.

---

# 13. Why the API Boundary Matters

Essa separação permite:

- releases independentes;
- testes isolados;
- evolução interna do Sofias Memory;
- reutilização por outros projetos;
- troca futura de implementação por adapter;
- menor coupling.

---

# 14. Protocol

O contrato deverá funcionar sobre comunicação explícita entre processos.

O protocolo inicial provavelmente será HTTP/local network contract compatível com a API existente do Sofias Memory.

A escolha concreta poderá evoluir.

Este ADR define o boundary, não o transporte específico.

---

# 15. MemoryProvider Contract

O Assistant deverá trabalhar com operações de domínio, não endpoints arbitrários.

Conceitualmente:

```text
MemoryProvider
├── remember(...)
├── recall(...)
├── forget(...)
├── query(...)
├── create_candidate_memory(...)
├── persist_memory(...)
├── supersede_memory(...)
├── confirm_memory(...)
└── consolidate(...)
```

Essa lista é ilustrativa.

A evolução exata dependerá do ADR-0012 e do backlog do Sofias Memory.

---

# 16. Existing Sofias Memory API

As APIs existentes de:

- Remember;
- Recall;
- Cognify;
- Improve;
- Forget;
- datasets;

poderão ser utilizadas inicialmente.

Entretanto, elas não deverão limitar permanentemente o modelo cognitivo do Assistant.

---

# 17. No Fake Documents

Novos tipos cognitivos não deverão ser forçados artificialmente para:

```text
Document
  ↓
Chunk
```

apenas porque esse modelo já existe.

Exemplo inadequado:

```text
"user prefers dark theme"
    ↓
create fake text document
    ↓
chunk it
```

se houver necessidade recorrente de tratar isso como Profile Memory nativa.

---

# 18. Evolution of Sofias Memory

Quando uma necessidade for:

- genérica;
- persistente;
- cognitiva;
- reutilizável por outros agentes/aplicações;

ela deverá preferencialmente evoluir o Sofias Memory.

Exemplo:

```text
temporal memory validity
```

é uma capability geral do memory engine.

Não deve ser implementada apenas como hack dentro do Assistant.

---

# 19. Assistant-specific Logic

Quando uma necessidade pertencer a:

- current conversation;
- active Task;
- permissions;
- UI;
- provider routing;
- current context;
- execution orchestration;

ela permanecerá no Assistant.

---

# 20. Generalization Test

Regra prática:

> Se outro agente pessoal independente também precisaria dessa capability persistente, ela provavelmente pertence ao Sofias Memory.

Exemplo:

```text
remember that user prefers Portuguese
```

→ Sofias Memory.

Exemplo:

```text
Task X is waiting for confirmation
```

→ Assistant Operational Store.

---

# 21. Memory Orchestrator

O Sofia's Assistant possuirá `Memory Orchestrator`.

Ele será responsável por coordenar a utilização cognitiva do Sofias Memory.

Responsabilidades incluem:

- detectar Memory Candidates;
- classificar candidates;
- validar provenance;
- decidir necessidade de confirmação;
- aplicar Memory Policy;
- solicitar persistência;
- solicitar retrieval;
- iniciar consolidation;
- resolver conflitos no contexto do runtime;
- fornecer memória ao Context Builder.

---

# 22. Memory Orchestrator Is Not Memory Database

Memory Orchestrator não implementará:

- vector index;
- graph storage;
- persistent semantic ranking;
- knowledge persistence.

Ele coordena o uso do memory engine.

---

# 23. Memory Candidate

Um `MemoryCandidate` representa informação potencialmente digna de persistência.

Pode surgir de:

- user statement;
- explicit user command;
- Tool observation;
- Event;
- completed Task;
- imported source;
- inferred conclusion.

O modelo final será definido no ADR-0012.

---

# 24. Candidate Processing

Conceitualmente:

```text
Observation
    ↓
Candidate Extraction
    ↓
Classification
    ↓
Provenance Assignment
    ↓
Policy
    ↓
Validation / Confirmation
    ↓
Persist / Reject
```

---

# 25. Explicit Remember

Quando usuário disser algo equivalente a:

> “Lembre que prefiro respostas em português.”

isso poderá gerar MemoryCandidate com alta evidência de intenção explícita.

Ainda assim, runtime manterá provenance apropriada.

---

# 26. Implicit Candidate

Conversation também poderá produzir candidates sem comando explícito.

Exemplo:

> “Eu sempre uso PostgreSQL nos meus projetos novos.”

Pode ser candidate de preferência.

Mas inferência e persistência deverão respeitar Memory Policy.

---

# 27. Assistant-generated Content

Conteúdo gerado pela própria Sofia não deverá retornar ao Sofias Memory como fato authoritative sem provenance adequada.

Exemplo:

Sofia diz:

> “Você provavelmente prefere arquitetura hexagonal.”

Isso não deve virar:

```text
User prefers hexagonal architecture
```

como fato.

---

# 28. Memory Retrieval

Assistant será responsável por decidir quando retrieval é necessário.

O provider não acessará Sofias Memory diretamente por padrão.

Fluxo:

```text
Conversation / Task
        ↓
Context Builder
        ↓
Memory Orchestrator
        ↓
MemoryProvider
        ↓
Sofias Memory
```

---

# 29. Retrieval Query

Memory retrieval poderá considerar:

- user request;
- Conversation focus;
- active project;
- Task;
- AgentRun;
- relevant entities;
- temporal context;
- dataset/domain scope.

---

# 30. Dataset Scope

Datasets no Sofias Memory representarão domínios relativamente estáveis.

Não haverá dataset novo por Conversation.

Exemplos possíveis:

```text
main
personal
projects
project-sofias-assistant
electronics
```

A granularidade final será definida conforme evolução prática.

---

# 31. Conversation Is Not Dataset

Não utilizar:

```text
conversation-123
conversation-124
conversation-125
```

como modelo padrão de datasets.

Conversation é runtime state, não cognitive domain.

---

# 32. Dataset Selection

Memory Orchestrator poderá selecionar dataset(s) relevantes conforme:

- active project;
- user context;
- Task;
- Delegation;
- Memory Policy.

---

# 33. Memory Access and Policy

Memory retrieval também estará sujeito ao PolicyEngine quando necessário.

Isso é especialmente importante para sub-agents.

Exemplo:

```text
Development Agent
```

poderá receber:

```text
memory.read
scope = project-sofias-assistant
```

sem receber memória pessoal irrestrita.

---

# 34. Root Memory Access

Sofia/root também não deverá pressupor acesso irrestrito em todos os contextos futuros.

Policy poderá restringir dados sensíveis ou data locality.

---

# 35. Memory Writes and Policy

Persistência de memória poderá exigir authority.

Exemplo:

```text
memory.write
scope = personal
```

Isso permitirá controle futuro sobre plugins/agents que tentem gravar memória.

---

# 36. Sub-agent Memory

Agents não acessarão Sofias Memory diretamente sem mediação runtime.

Fluxo:

```text
AgentRun
   ↓
Memory request
   ↓
Root/runtime policy
   ↓
Memory Orchestrator
   ↓
Sofias Memory
```

ou interface equivalente controlada.

---

# 37. Memory Context Narrowing

Sub-agent receberá apenas memória necessária para sua Task.

Não deverá receber todo resultado bruto de recall sem seleção.

---

# 38. Context Builder

`ContextBuilder` pertence ao Assistant.

Ele decide como combinar:

- recent Turns;
- Working Memory;
- Task state;
- ToolResults;
- environment;
- persistent memories recuperadas.

Sofias Memory não produzirá o prompt final.

---

# 39. Retrieval Result Is Evidence

Uma memória recuperada deverá ser tratada como item com metadata.

Conceitualmente:

```text
MemoryItem
├── id
├── type
├── content
├── provenance
├── confidence
├── temporal metadata
├── importance
├── relevance
├── source
└── lifecycle state
```

O schema final dependerá do ADR-0012.

---

# 40. Relevance vs Importance

Sofias Memory poderá calcular relevance para retrieval.

Importance representa significado persistente distinto.

Context Builder poderá combinar ambos.

---

# 41. Memory IDs

Memórias persistentes deverão possuir IDs estáveis controlados pelo Sofias Memory.

Assistant poderá persistir referências a esses IDs.

---

# 42. Memory References in Operational Store

Assistant poderá armazenar:

```text
Task related_memory_ids
Conversation memory_refs
```

quando necessário.

Essas referências não duplicam o conteúdo authoritative.

---

# 43. Memory Availability

Sofia's Assistant deverá continuar operando parcialmente se Sofias Memory estiver temporariamente indisponível.

Features afetadas:

- persistent recall;
- new long-term memory writes;
- consolidation.

Features que poderão continuar:

- Conversation;
- Working Memory;
- local Tools;
- Tasks;
- Scheduler;
- current session state.

---

# 44. Memory Degraded Mode

O runtime deverá representar claramente estado:

```text
memory_provider = degraded/unavailable
```

Não deverá fingir que memória persistente foi salva quando operação falhou.

---

# 45. Failed Memory Write

Se persistência falhar, Assistant poderá:

- retry;
- manter MemoryCandidate pendente;
- informar usuário quando relevante.

Não deverá marcar candidate como persistido sem confirmação do provider.

---

# 46. Pending Memory Operations

MemoryCandidates importantes poderão permanecer no Operational Store enquanto aguardam persistência.

Esse estado é operacional.

Após persistência confirmada, authority passa ao Sofias Memory.

---

# 47. Duplicate Memory Writes

Adapter deverá utilizar idempotency quando suportada.

MemoryCandidate deverá possuir identidade/correlation suficiente para evitar duplicação após retry.

---

# 48. Memory Retrieval Failure

Recall failure não deverá necessariamente falhar a Conversation inteira.

Runtime poderá continuar com contexto reduzido e sinalizar limitação.

---

# 49. Memory Latency

ContextBuilder deverá possuir timeout/budget para retrieval.

Conversation realtime não deverá bloquear indefinidamente aguardando memória.

Poderão existir estratégias como:

- fast recall;
- background enrichment;
- prefetch.

Detalhes são deferred.

---

# 50. Realtime Memory Retrieval

Durante realtime voice, retrieval precisa respeitar latency.

Nem toda fala deverá disparar graph retrieval profundo.

Memory Orchestrator poderá usar heurísticas/routing.

---

# 51. Memory Prefetch

Runtime poderá antecipar memórias relevantes baseado em:

- active project;
- active Conversation;
- active Task.

Prefetch é optimization.

Não altera authority.

---

# 52. Consolidation

Assistant deverá poder solicitar consolidação.

Exemplo:

```text
Conversation
    ↓
episode extraction
    ↓
durable facts/decisions
```

O boundary exato entre orchestration no Assistant e persistence/consolidation no Sofias Memory será detalhado no ADR-0012.

---

# 53. Cognitive Consolidation Is Explicit

Não haverá regra:

```text
every N messages → dump transcript into vector DB
```

como arquitetura principal.

Consolidation deverá produzir memória semanticamente útil.

---

# 54. Forget

Quando usuário solicitar esquecer memória cognitiva:

```text
Assistant
   ↓
MemoryProvider.forget(...)
   ↓
Sofias Memory
```

O Assistant não deverá alterar diretamente persistence interna.

---

# 55. Forget vs Conversation Delete

Apagar Conversation History e esquecer memória são operações distintas.

Exemplo:

```text
delete conversation
```

não implica automaticamente:

```text
forget all memories derived from it
```

e vice-versa.

Quando provenance permitir relação, produto poderá oferecer operações coordenadas no futuro.

---

# 56. Provenance Across Boundary

Sofias Memory deverá preservar provenance suficiente para indicar origem da memória.

Possíveis referências:

- Conversation ID;
- Turn ID;
- Task ID;
- Tool observation;
- imported source.

O Assistant poderá fornecer correlation metadata ao persistir.

---

# 57. No Operational Foreign Keys Across Services

Não haverá foreign key física entre SQLite do Assistant e PostgreSQL do Sofias Memory.

Relacionamentos serão por stable IDs/correlation metadata.

---

# 58. Eventual Consistency

A integração entre Assistant e Sofias Memory será naturalmente distribuída.

Portanto:

```text
Assistant state
+
Memory state
```

não terá transação ACID única.

O design deverá considerar retries/idempotency/reconciliation.

---

# 59. No Distributed Transaction

Não será introduzido two-phase commit entre SQLite e Sofias Memory.

Isso adicionaria complexidade injustificada.

---

# 60. Persist Intent Before Remote Memory Write

Para writes relevantes:

```text
persist MemoryCandidate operationally
        ↓
call Sofias Memory
        ↓
record persistent memory ID/result
```

permite recovery caso Core caia.

---

# 61. Memory Candidate Recovery

Após restart, candidates pendentes poderão ser reavaliados/retryados de forma idempotente.

---

# 62. MemoryProvider Version Compatibility

Assistant deverá detectar incompatibilidade relevante entre seu adapter e a API disponível do Sofias Memory.

Não deve continuar silenciosamente usando contrato incompatível.

---

# 63. Capability Discovery

Adapter poderá futuramente detectar capabilities disponíveis.

Exemplo:

```text
supports_profile_memory
supports_episode_memory
supports_procedural_memory
```

Isso será útil durante evolução incremental.

---

# 64. Backward Compatibility

Enquanto Sofias Memory evolui, Adapter poderá implementar fallback temporário usando APIs existentes.

Mas fallback não deverá comprometer semanticamente tipos cognitivos importantes.

---

# 65. Migration Path

Possível evolução:

```text
Phase 1
existing Remember / Recall

Phase 2
typed cognitive memory APIs

Phase 3
native consolidation / lifecycle APIs
```

A sequência real será definida no backlog.

---

# 66. Sofias Memory Remains Generic

Mudanças feitas no Sofias Memory para atender o Assistant deverão, quando possível, preservar caráter de engine genérica.

Evitar endpoints como:

```text
POST /sofias-assistant/save-user-preference
```

Preferir domínio genérico:

```text
memory type = PROFILE
```

ou API equivalente.

---

# 67. Assistant Does Not Own Graph Semantics

Assistant poderá solicitar relações ou consultas cognitivas.

Mas não deverá conhecer internals como:

- Neo4j labels específicos;
- graph projection queues;
- internal relation schema SQL.

---

# 68. Embeddings

Embedding provider do Sofias Memory pertence ao próprio Sofias Memory para seu storage/retrieval.

O AI Provider framework do Assistant não deverá assumir controle dessas embeddings.

---

# 69. Potential Shared Providers

Assistant e Sofias Memory poderão usar o mesmo vendor/model configurado.

Isso não significa que devam compartilhar implementação interna.

Cada serviço mantém seu boundary.

---

# 70. Secrets

Sofias Memory continuará responsável pelos secrets necessários ao próprio serviço.

Assistant não deverá fornecer automaticamente suas API keys ao memory service, salvo configuração explícita.

---

# 71. Health

Adapter deverá possuir health/status suficiente para informar:

```text
available
degraded
unavailable
incompatible
```

ou equivalente.

---

# 72. Startup

Sofias Memory availability poderá ser verificada no startup.

Sua indisponibilidade não precisa impedir totalmente Core startup.

Sofia poderá iniciar em degraded mode.

---

# 73. Memory-critical Tasks

Uma Task cujo objetivo exija memória persistente poderá declarar dependency.

Nesse caso, memory provider unavailable poderá:

- colocar Task em waiting;
- falhar;
- pedir usuário;

conforme semantics.

---

# 74. Memory and Events

Memory operations poderão emitir Domain Events.

Exemplos:

```text
MemoryCandidateCreated
MemoryPersisted
MemoryRejected
MemorySuperseded
MemoryProviderUnavailable
```

A lista final é deferred.

---

# 75. Memory and Audit

Persistência e recuperação sensível poderão ser auditadas quando necessário.

Audit não exige registrar conteúdo integral da memória.

---

# 76. Privacy

Memory queries poderão conter informação sensível.

Logging deverá usar redaction.

Provider boundary não justifica registrar bodies completos indiscriminadamente.

---

# 77. Data Locality

Se Sofias Memory estiver local, retrieval local continua compatível com local-first.

Porém memória recuperada posteriormente enviada a AI provider cloud continua sujeita à data locality do Assistant.

---

# 78. MemoryProvider Is Trusted Component, Not Universal Authority

Sofias Memory é authority sobre conteúdo persistido.

Ele não possui authority para:

- executar Tools;
- conceder Grants;
- iniciar shell;
- modificar Task state arbitrariamente.

---

# 79. Memory-triggered Actions

Uma memória recuperada pode influenciar planning.

Não pode executar ação sozinha.

Exemplo:

```text
Memory:
"user prefers automatic backups"
```

não significa:

```text
start deleting/copying files now
```

Task/Policy continuam necessários.

---

# 80. Memory Injection Safety

Memórias persistidas podem conter texto originalmente vindo de fontes externas.

ContextBuilder deverá tratá-las como data/provenance, não instructions supremas.

Isso reduz risco de persistent prompt injection.

---

# 81. Imported Knowledge

Documentos e fontes importadas podem continuar utilizando o modelo de knowledge sources já existente no Sofias Memory.

Nem todo conteúdo persistente precisa ser convertido para typed personal memory.

---

# 82. Cognitive Memory vs Knowledge Base

Sofias Memory poderá conter ambos:

```text
Knowledge Sources
```

e:

```text
Cognitive Memory
```

Esses domínios podem compartilhar infraestrutura sem serem semanticamente idênticos.

---

# 83. Skills

Future `data_skill` / procedural memory pertence ao ecossistema do Sofias Memory.

Assistant poderá:

- descobrir skills;
- recuperar procedures;
- sugerir Skill Candidates;
- executar skills através do Tool/Task Runtime.

Persistência procedural continua no memory ecosystem.

---

# 84. Skill Is Not Tool Authority

Uma skill pode descrever procedimento.

Ela não concede permissions necessárias para executá-lo.

Exemplo:

```text
Skill:
"How to deploy project X"
```

pode mencionar `git push`.

Policy ainda decide.

---

# 85. Skill Execution

Fluxo futuro:

```text
Procedural Memory / Skill
       ↓
Assistant planning
       ↓
Task / Workflow
       ↓
Tool Runtime
       ↓
Policy
```

Sofias Memory não executa a procedure diretamente.

---

# 86. Testing

Deverão existir testes para:

- Adapter contract;
- remember/persist;
- recall;
- provider unavailable;
- timeout;
- idempotent retry;
- pending MemoryCandidate recovery;
- dataset scope;
- Agent memory restriction;
- data locality;
- API compatibility.

---

# 87. Fake MemoryProvider

Assistant deverá possuir `FakeMemoryProvider` ou equivalente para testes.

Isso permitirá validar:

- ContextBuilder;
- Memory Orchestrator;
- Tasks;
- Agent context;

sem serviço real.

---

# 88. Integration Tests

Também deverão existir integration tests reais contra Sofias Memory para validar o contrato entre os dois projetos.

Mocks não serão suficientes para esse boundary.

---

# 89. Contract Versioning

Mudanças incompatíveis na integração deverão possuir versioning/migration explícitos.

Evitar coupling baseado em assumptions não documentadas.

---

# 90. Alternatives Considered

## Alternative A — Reimplement memory inside Assistant

### Advantages

- integração simples;
- uma única aplicação.

### Rejected because

- duplica Sofias Memory;
- divide evolução;
- cria dois graph/vector systems;
- aumenta manutenção;
- perde reutilização.

---

## Alternative B — Use Sofias Memory for all state

### Advantages

- um único storage conceitual.

### Rejected because

mistura:

```text
cognitive memory
```

com:

```text
runtime state
```

e cria acoplamento indevido.

---

## Alternative C — Import Sofias Memory as Python library

### Advantages

- baixa latência;
- sem network boundary.

### Rejected because

- coupling forte;
- lifecycle compartilhado;
- DB internals vazam;
- releases deixam de ser independentes;
- dificulta reutilização.

---

## Alternative D — Store every Conversation Turn as memory immediately

### Advantages

- implementação simples;
- nada é perdido.

### Rejected because

- memória ruidosa;
- facts falsos;
- assistant-generated content contaminando perfil;
- baixa qualidade de recall;
- contradiz modelo cognitivo proposto.

---

# 91. Consequences

## Positive

- reutiliza Sofias Memory;
- evita duplicação de infraestrutura;
- boundaries claros;
- Assistant permanece focado em runtime cognition;
- Sofias Memory evolui como engine genérica;
- permite context isolation;
- suporta degraded mode;
- melhor testabilidade;
- evolução independente dos projetos.

## Negative

- comunicação entre processos;
- eventual consistency;
- API precisa evoluir;
- recovery de writes remotos exige cuidado;
- algumas capacidades atuais do Sofias Memory ainda são document-centric;
- contract tests entre projetos tornam-se necessários.

Esses custos são considerados aceitáveis e desejáveis.

---

# 92. Architectural Invariants

### INV-001

Sofias Memory é authority da Long-Term Cognitive Memory.

### INV-002

Assistant Operational Store é authority do runtime state.

### INV-003

Working Memory pertence ao Assistant.

### INV-004

Conversation History não é automaticamente Cognitive Memory.

### INV-005

Assistant não acessa banco interno do Sofias Memory.

### INV-006

Assistant não importa services/repositories internos do Sofias Memory.

### INV-007

Integração ocorre através de contrato explícito.

### INV-008

Assistant não implementa segundo semantic/vector/graph memory engine persistente.

### INV-009

Memory Orchestrator coordena memória, mas não substitui Sofias Memory.

### INV-010

Context Builder pertence ao Assistant.

### INV-011

Sofias Memory não monta prompt final.

### INV-012

Sub-agent memory access é scoped e policy-controlled.

### INV-013

Memory write failure nunca é tratado como persistência bem-sucedida.

### INV-014

Conversation dataset por padrão é proibido como modelo de organização cognitiva.

### INV-015

Procedural Memory/skills não concedem execution authority.

### INV-016

Persistent memory content nunca constitui authorization source.

---

# 93. Deferred Decisions

Serão definidos posteriormente:

- interface Python concreta de MemoryProvider;
- endpoints novos do Sofias Memory;
- typed memory API;
- candidate persistence schema;
- dataset strategy detalhada;
- retrieval latency strategy;
- memory prefetch;
- consolidation contract;
- compatibility/version negotiation;
- health protocol;
- idempotency contract;
- memory write queue;
- offline buffering;
- Skill API;
- exact relation between `data_skill` and procedural memory.

---

# 94. Decision Summary

O Sofia's Assistant utilizará o **Sofias Memory como autoridade externa da memória cognitiva persistente de longo prazo**.

O Assistant manterá separadamente seu Operational Store para Conversations, Working Memory, Tasks, Agents, Grants, Delegations, Events e demais estados do runtime.

A integração ocorrerá por um `MemoryProvider` explícito, implementado inicialmente através de um `SofiasMemoryAdapter`.

O `Memory Orchestrator`, residente no Assistant, decidirá o que deve ser lembrado, quando memória deve ser recuperada e qual informação deverá entrar no contexto.

Embeddings, persistent semantic retrieval, knowledge graph e lifecycle da memória permanecerão no Sofias Memory.

O Sofias Memory poderá evoluir de seu modelo atualmente mais orientado a knowledge sources para suportar memória cognitiva tipada, desde que essas evoluções permaneçam genéricas e reutilizáveis.