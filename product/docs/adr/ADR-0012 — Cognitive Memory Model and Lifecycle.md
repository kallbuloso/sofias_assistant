# ADR-0012 — Cognitive Memory Model and Lifecycle

**Status:** Accepted  
**Project:** Sofia's Assistant  
**Decision date:** 2026-08-31  
**Scope:** Typed cognitive memory, provenance, confidence, temporal validity, contradiction, supersession, confirmation, importance, consolidation and procedural memory

---

# 1. Context

O ADR-0011 definiu que o **Sofias Memory** será authority da memória cognitiva persistente de longo prazo.

Também ficou definido que o Sofia's Assistant será responsável por:

- detectar Memory Candidates;
- classificá-los;
- aplicar Memory Policy;
- solicitar confirmação quando necessário;
- iniciar consolidation;
- recuperar memória relevante;
- injetar contexto no runtime.

O Sofias Memory atual já oferece uma base sólida para:

- knowledge sources;
- documents;
- chunks;
- embeddings;
- entities;
- relations;
- provenance;
- durable pipelines;
- recall;
- forget.

Porém, memória pessoal cognitiva de longo prazo possui semânticas que não devem ser reduzidas artificialmente a documentos e chunks.

Exemplos:

```text
"Prefiro respostas em português."
```

```text
"Decidimos usar SQLite no MVP."
```

```text
"Ontem concluímos o ADR-0005."
```

```text
"Para publicar este projeto, primeiro execute os testes, depois faça commit e push."
```

Essas informações representam tipos cognitivos diferentes.

O sistema precisa preservar essas diferenças para evitar problemas como:

- sugestões da própria Sofia se tornando fatos sobre o usuário;
- preferências antigas sobrescrevendo silenciosamente novas;
- episódios sendo confundidos com fatos permanentes;
- procedimentos sendo tratados como texto comum;
- contradictions sendo apagadas;
- memórias desatualizadas permanecendo authoritative;
- conversation history inteira sendo despejada em vector storage.

---

# 2. Decision

O Sofia's Assistant e o Sofias Memory adotarão um modelo de **Cognitive Memory tipado, proveniente, temporal e lifecycle-aware**.

O baseline possuirá quatro categorias cognitivas:

```text
PROFILE
SEMANTIC
EPISODIC
PROCEDURAL
```

Essas categorias representam semântica de domínio.

Elas não obrigam quatro storages físicos independentes.

---

# 3. Fundamental Rule

A regra central será:

> **Memory is not merely stored text. Memory is a claim, episode or procedure with provenance, temporal meaning and lifecycle.**

Persistir uma string não será considerado suficiente para representar memória cognitiva confiável.

---

# 4. Cognitive Memory vs Knowledge Source

O Sofias Memory deverá distinguir conceitualmente:

```text
Knowledge Source
```

de:

```text
Cognitive Memory
```

Knowledge Source representa conteúdo importado ou material de referência.

Exemplos:

- documento;
- página web;
- manual;
- arquivo;
- artigo.

Cognitive Memory representa informação consolidada com significado cognitivo.

Exemplos:

- preferência;
- fato;
- decisão;
- episódio;
- procedimento aprendido.

Ambos poderão compartilhar infraestrutura de retrieval, entities e relations.

Mas não serão semanticamente equivalentes.

---

# 5. PROFILE Memory

`PROFILE` representa informações relativamente duráveis sobre:

- usuário;
- preferências;
- identidade;
- relações;
- hábitos;
- estilo de trabalho;
- configurações cognitivamente relevantes.

Exemplos:

```text
"Prefere comunicação em português do Brasil."
```

```text
"Prefere PostgreSQL em novos projetos."
```

```text
"GitHub username é X."
```

Nem toda informação pessoal precisa ser `PROFILE`.

Informações transitórias deverão permanecer episódicas ou operacionais.

---

# 6. SEMANTIC Memory

`SEMANTIC` representa fatos, decisões, conceitos ou conhecimento consolidado.

Exemplos:

```text
"Sofia's Assistant adotará SQLite como Operational Store inicial."
```

```text
"O projeto usa uma arquitetura local-first."
```

```text
"Feature X depende de Y."
```

Pode representar conhecimento pessoal ou relacionado a projetos.

---

# 7. EPISODIC Memory

`EPISODIC` representa acontecimentos contextualizados no tempo.

Exemplos:

```text
"Em 31 de agosto de 2026 o ADR-0001 foi aprovado."
```

```text
"Ontem o deploy falhou por causa da configuração X."
```

```text
"Durante a última sessão o usuário decidiu alterar Y."
```

Episódios poderão servir como evidência para memórias semânticas posteriores.

---

# 8. PROCEDURAL Memory

`PROCEDURAL` representa conhecimento sobre como realizar algo.

Exemplos:

```text
"Como executar o smoke test deste projeto."
```

```text
"Como preparar release."
```

```text
"Procedimento para diagnosticar determinado equipamento."
```

Esse domínio se relaciona diretamente com skills.

---

# 9. Procedural Memory and Skills

Uma `Skill` poderá ser uma representação estruturada especializada de Procedural Memory.

Conceitualmente:

```text
Procedural Memory
      │
      └── Skill
          ├── objective
          ├── prerequisites
          ├── steps
          ├── expected outputs
          ├── constraints
          └── validation
```

Nem toda Procedural Memory precisa necessariamente ser uma Skill executável.

---

# 10. `data_skill`

A futura capability `data_skill` do Sofias Memory deverá ser tratada como parte do ecossistema de Procedural Memory.

Ela poderá possuir domínio e APIs próprios quando isso for útil.

Porém deverá preservar integração com:

- provenance;
- lifecycle;
- temporal metadata;
- confidence;
- relationships;
- retrieval.

---

# 11. Skill Is Not Authority

Uma Skill explica como realizar algo.

Ela não concede permission para executar.

Exemplo:

```text
Skill:
"Publish release"
```

pode mencionar:

```text
git push
```

Mas Tool Runtime continuará sujeito a Grants, Delegations e Policy.

---

# 12. Memory Candidate

Toda nova memória cognitiva deverá passar conceitualmente por `MemoryCandidate`.

Um candidate é uma afirmação ou estrutura ainda não necessariamente authoritative.

Conceitualmente:

```text
MemoryCandidate
├── id
├── type
├── content
├── subject
├── provenance
├── confidence
├── observed_at
├── valid_from
├── valid_until
├── source_refs
├── scope
├── sensitivity
└── metadata
```

O schema final poderá variar.

---

# 13. Candidate Sources

Memory Candidates poderão surgir de:

```text
USER_ASSERTED
USER_CONFIRMED
TOOL_OBSERVED
IMPORTED
INFERRED
ASSISTANT_GENERATED
```

Essa lista forma o baseline de provenance source classes.

---

# 14. Provenance

Toda Cognitive Memory persistente deverá possuir provenance explícita.

Provenance deverá permitir responder:

> De onde veio essa memória?

Possíveis referências:

- Conversation;
- Turn;
- Task;
- ToolCall;
- imported Source;
- Event;
- previous Memory;
- user confirmation.

---

# 15. USER_ASSERTED

`USER_ASSERTED` significa que o usuário apresentou diretamente a informação.

Exemplo:

> “Prefiro usar Vuetify.”

Isso não significa necessariamente verdade universal.

Significa que existe evidência direta do usuário.

---

# 16. USER_CONFIRMED

`USER_CONFIRMED` representa informação que recebeu confirmação explícita do usuário.

Isso poderá ter autoridade cognitiva maior em certos contextos.

Exemplo:

Sofia:

> “Posso lembrar que você prefere Vuetify?”

Usuário:

> “Sim.”

---

# 17. TOOL_OBSERVED

`TOOL_OBSERVED` representa fato observado por Tool ou Integration.

Exemplo:

```text
git branch = main
```

ou:

```text
package version = 3.2
```

Observação ainda pode envelhecer.

Portanto não é necessariamente fato permanente.

---

# 18. IMPORTED

`IMPORTED` representa informação derivada de knowledge source externo.

Exemplos:

- documentação;
- README;
- arquivo;
- manual.

A fonte deverá permanecer rastreável.

---

# 19. INFERRED

`INFERRED` representa conclusão deduzida pelo sistema.

Exemplo:

> “O usuário provavelmente prefere respostas curtas.”

Essa memória não deverá ser tratada como equivalente a USER_CONFIRMED.

---

# 20. ASSISTANT_GENERATED

`ASSISTANT_GENERATED` representa conteúdo criado pela própria Sofia.

Por padrão, isso não será suficiente para se tornar fato authoritative.

Exemplo:

Sofia sugere:

> “Talvez você prefira usar PostgreSQL.”

Não poderá resultar automaticamente em PROFILE authoritative.

---

# 21. No Self-confirming Memory

Será proibido o ciclo:

```text
Assistant generates claim
        ↓
claim stored
        ↓
future retrieval
        ↓
claim treated as user fact
```

sem provenance apropriada e validação.

---

# 22. Confidence

Memórias inferidas ou observacionais poderão possuir confidence.

Confidence deverá representar qualidade de evidência dentro de semântica definida.

Não deverá ser:

```text
0.83
```

apenas porque um LLM inventou um número.

---

# 23. Confidence Semantics

O produto poderá adotar classes ou score normalizado desde que seja possível explicar o significado.

Exemplo conceitual:

```text
LOW
MEDIUM
HIGH
CONFIRMED
```

ou score associado a regras explícitas.

A representação concreta será decidida no Sofias Memory backlog.

---

# 24. Confidence Is Not Provenance

Uma memória pode ter:

```text
provenance = USER_ASSERTED
confidence = HIGH
```

ou:

```text
provenance = TOOL_OBSERVED
confidence = HIGH
```

São dimensões distintas.

---

# 25. Temporal Metadata

Cognitive Memory deverá poder representar:

```text
observed_at
valid_from
valid_until
```

quando necessário.

---

# 26. observed_at

Representa quando a informação foi observada.

Exemplo:

```text
active project branch = feature-x
observed_at = ...
```

---

# 27. valid_from

Representa quando o fato passou a ser considerado válido.

Exemplo:

```text
"Starting next month, use provider X."
```

---

# 28. valid_until

Representa quando validade termina ou terminou.

Exemplo:

```text
"Until Friday, project uses temporary branch X."
```

---

# 29. Temporal Facts

Uma memória não deve ser considerada falsa apenas porque deixou de ser atual.

Exemplo:

```text
"Project used SQLite during MVP"
```

pode continuar historicamente verdadeiro mesmo depois de migrar para PostgreSQL.

A temporalidade preserva esse significado.

---

# 30. Current Truth

Retrieval de fatos atuais deverá considerar temporal validity e lifecycle.

O sistema não deverá simplesmente selecionar a memória semanticamente mais semelhante.

---

# 31. Memory Lifecycle

Baseline conceitual:

```text
CANDIDATE
ACTIVE
SUPERSEDED
REJECTED
ARCHIVED
FORGOTTEN
```

A state machine concreta será definida no Sofias Memory.

---

# 32. CANDIDATE

Informação ainda em avaliação.

Poderá existir operacionalmente no Assistant antes da persistência, ou nativamente no Sofias Memory no futuro.

A authority entre os dois estados deverá ser clara.

---

# 33. ACTIVE

Memória atualmente válida/utilizável conforme scope e temporalidade.

---

# 34. SUPERSEDED

Memória substituída por informação posterior.

Não deve ser apagada necessariamente.

Exemplo:

```text
Old:
"Preferred framework is Quasar"

New:
"Preferred framework is Vuetify"
```

A antiga pode permanecer para histórico como `SUPERSEDED`.

---

# 35. REJECTED

Candidate considerado inadequado para persistência authoritative.

Exemplos:

- inferência errada;
- usuário negou;
- conteúdo sem evidência suficiente.

---

# 36. ARCHIVED

Memória preservada para histórico mas normalmente excluída de retrieval corrente.

Difere de `SUPERSEDED` quando não existe necessariamente substituto direto.

---

# 37. FORGOTTEN

Memória removida ou tornada inacessível conforme Forget semantics.

O Sofias Memory deverá continuar definindo guarantees concretas de Forget.

---

# 38. Contradiction

Nova memória poderá contradizer memória existente.

Contradiction não deverá resultar automaticamente em overwrite.

Fluxo conceitual:

```text
New Candidate
      ↓
retrieve related memories
      ↓
detect contradiction
      ↓
classify relationship
      ↓
confirm / supersede / coexist
```

---

# 39. Contradiction Is Contextual

Duas afirmações aparentemente conflitantes podem ser verdadeiras em tempos ou scopes distintos.

Exemplo:

```text
"Use SQLite for MVP"
```

e:

```text
"Use PostgreSQL in production"
```

não são necessariamente contradiction.

---

# 40. Supersession

Quando nova memória substitui semanticamente antiga:

```text
new_memory.supersedes = old_memory
```

ou relação equivalente deverá ser representável.

A antiga não precisa ser hard-deleted.

---

# 41. Confirmation

Alguns candidates deverão exigir confirmação do usuário antes de se tornarem authoritative.

Especialmente:

- informações sensíveis;
- inferências de perfil;
- fatos pessoais importantes;
- contradictions relevantes.

---

# 42. Confirmation Policy

Nem toda memória exige pergunta ao usuário.

Isso criaria fatigue.

Exemplos provavelmente aceitáveis sem confirmação:

```text
"User explicitly said preference X."
```

quando claro e não sensível.

Já:

```text
"Inferred political preference"
```

ou outra inferência sensível não deverá virar authority automaticamente.

---

# 43. Confirmation Binding

Confirmação deverá estar vinculada ao candidate específico.

Não poderá transformar automaticamente várias inferências relacionadas em fatos.

---

# 44. Rejected Confirmation

Se usuário rejeitar candidate:

```text
Candidate → REJECTED
```

e o sistema deverá evitar reapresentá-lo repetidamente sem nova evidência significativa.

---

# 45. Correction

Usuário poderá corrigir memória.

Exemplo:

> “Não uso mais Quasar, agora uso Vuetify.”

Isso poderá produzir:

```text
new PROFILE memory
+
supersede old memory
```

com provenance USER_ASSERTED.

---

# 46. Explicit Forget

Usuário poderá pedir:

> “Esqueça que eu prefiro X.”

O Assistant deverá resolver a memória correspondente e utilizar Sofias Memory Forget semantics.

---

# 47. Forget Is Not Supersession

`SUPERSEDED` preserva histórico cognitivo.

`FORGOTTEN` representa remoção deliberada conforme policy.

São operações diferentes.

---

# 48. Importance

Memória poderá possuir `importance`.

Importance representa relevância persistente/estrutural para o usuário ou domínio.

Não é a mesma coisa que similarity score de retrieval.

---

# 49. Importance vs Relevance

Exemplo:

Memória:

```text
"User's preferred language is pt-BR."
```

pode possuir alta importance.

Mas numa pergunta sobre um erro de SQL, semantic relevance ao conteúdo pode ser baixa.

Ainda assim, pode afetar como resposta é apresentada.

---

# 50. Pinning

Futuramente usuário poderá marcar memória como pinned/important.

Pinned memory poderá receber tratamento especial.

Pinning não deverá impedir Forget explícito.

---

# 51. Retrieval

Recall de Cognitive Memory deverá considerar, conforme tipo de consulta:

- semantic relevance;
- lifecycle;
- temporal validity;
- importance;
- provenance;
- confidence;
- scope;
- contradiction/supersession;
- recency.

A função exata de ranking pertence ao Sofias Memory.

---

# 52. Retrieval Should Return Metadata

Recall não deverá retornar apenas:

```text
"text"
```

Idealmente deverá retornar memory items com metadata suficiente para Context Builder.

---

# 53. Context Builder Responsibility

Context Builder decide quais memórias recuperadas entram no contexto do modelo.

Sofias Memory oferece retrieval/ranking.

Assistant monta a projeção final.

---

# 54. Profile Injection

PROFILE Memory não deve necessariamente ser injetada em todo prompt.

Exemplo:

preferência de framework só é útil em contexto de desenvolvimento relacionado.

Memory Orchestrator deverá selecionar relevant profile facts.

---

# 55. Persistent Identity Context

Algumas PROFILE memories muito importantes poderão ser consideradas parte de baseline context.

Mesmo assim, retrieval/pinning deverá permanecer explícito e auditável.

---

# 56. Episodic Consolidation

Conversation ou sequência de Events poderá ser consolidada em episódio.

Exemplo:

```text
Conversation:
80 turns
```

não precisa virar 80 memórias.

Pode produzir:

```text
Episode:
"Architecture review session..."
```

---

# 57. Episode Structure

EPISODIC memory poderá incluir:

- summary;
- participants/entities;
- started_at;
- ended_at;
- decisions;
- outcomes;
- related Tasks;
- provenance refs.

O schema final é deferred.

---

# 58. Episode to Semantic Memory

Consolidation poderá derivar facts/decisions de episode.

Exemplo:

```text
Episode:
"Architecture discussion"
   ↓
Semantic:
"ADR-0005 accepted"
```

Cada derivação deverá preservar provenance.

---

# 59. Consolidation

Consolidation é processo explícito para transformar informação de baixa granularidade em memória durável mais útil.

Exemplos:

```text
many Turns
  ↓
Episode
```

```text
repeated evidence
  ↓
Profile preference
```

```text
successful repeated procedure
  ↓
Procedural Memory / Skill Candidate
```

---

# 60. Consolidation Is Not Dumping

Não utilizar como arquitetura:

```text
every 20 turns:
    concatenate conversation
    store embedding
```

Isso é armazenamento, não consolidation cognitiva.

---

# 61. Consolidation Trigger

Assistant poderá decidir quando consolidation é necessária.

Triggers possíveis:

- end of meaningful session;
- Conversation length;
- Task completion;
- explicit user request;
- idle period;
- repeated facts;
- Event-driven milestone.

---

# 62. Consolidation Ownership

O boundary será:

```text
Assistant
  decides when/why to consolidate
        ↓
Sofias Memory
  persists and manages resulting cognitive objects
```

Parte da extraction/classification poderá existir em um ou ambos os projetos conforme melhor generalização.

A API final será definida no backlog.

---

# 63. Candidate Extraction

No MVP, Memory Orchestrator poderá extrair candidates a partir de Conversation.

Esse processo poderá usar LLM.

Mas LLM output será proposal.

Não authority.

---

# 64. Candidate Validation

Validation poderá usar:

- exact user statement;
- existing memories;
- provenance;
- Tool evidence;
- contradiction checks;
- deterministic policy.

---

# 65. Sensitivity

Memory Candidate poderá possuir sensitivity classification quando necessário.

Isso poderá afetar:

- confirmation;
- retrieval;
- Agent access;
- cloud locality;
- retention.

Taxonomia concreta será definida posteriormente.

---

# 66. Sensitive Memory

Informação sensível não deverá ser amplamente injetada em contexts apenas por semantic similarity.

Policy/context deverá controlar acesso.

---

# 67. Memory Scope

Memórias deverão poder pertencer a scope/domain.

Exemplos:

```text
personal
project:sofias-assistant
project:sofias-memory
electronics
```

Dataset poderá ser uma parte dessa organização, mas não necessariamente a única representação semântica.

---

# 68. Dataset Relationship

Datasets continuarão sendo domínios relativamente estáveis do Sofias Memory.

Cognitive Memory poderá estar associada a dataset ou scope apropriado.

Não criar dataset por memory item.

---

# 69. Cross-scope Memory

Algumas memórias poderão ser relevantes em múltiplos domínios.

Exemplo:

```text
"User prefers pt-BR."
```

é global/personal.

Não deverá ser duplicada em cada projeto apenas para retrieval.

---

# 70. Relationships

Cognitive memories poderão se relacionar com:

- entities;
- sources;
- other memories;
- projects;
- episodes;
- skills.

O graph existente do Sofias Memory poderá evoluir para representar essas relações.

---

# 71. Stable Identity

Memory objects deverão possuir stable IDs.

Supersession, confirmation e references dependerão deles.

---

# 72. Versioning

Alterações relevantes em memória poderão ser representadas por:

- new memory + relationship;
- revision/version model;

conforme domínio.

Evitar mutation silenciosa que apague provenance.

---

# 73. Edit vs New Memory

Correção simples de metadata pode permitir update.

Mudança semântica significativa deverá preferir nova memória + supersession/version history.

---

# 74. Memory Deduplication

Candidate igual ou semanticamente equivalente a memória existente poderá:

- confirmá-la;
- reforçar evidence;
- atualizar observation metadata;

em vez de criar duplicata.

---

# 75. Confirmation as Evidence

Nova USER_ASSERTED evidence pode aumentar confidence ou confirmar memória existente sem necessariamente criar novo object.

A estratégia concreta será definida no Sofias Memory.

---

# 76. Repeated Observations

Exemplo:

Tool observa várias vezes:

```text
preferred branch naming pattern
```

Isso não deve automaticamente virar Profile preference.

Repeated observation pode aumentar evidência, mas inference continua distinta de user assertion.

---

# 77. Beliefs and Hypotheses

O sistema poderá futuramente representar hypotheses separadamente.

No MVP, hypotheses poderão permanecer em Working Memory ou candidate state.

Não deverão ser promovidas automaticamente para ACTIVE.

---

# 78. Negative Knowledge

Memória poderá representar explicitamente negação quando relevante.

Exemplo:

```text
"Project does not support branches in MVP."
```

Não depender apenas da ausência de uma memória positiva.

---

# 79. Source Authority

Uma fonte pode ser authoritative para determinado fato.

Exemplo:

README atual do projeto pode ser evidence forte para arquitetura atual.

Mas imported source não se torna automaticamente authoritative para profile do usuário.

---

# 80. Temporal Supersession Example

```text
M1:
type = PROFILE
content = "Prefers Quasar"
valid_from = 2025
valid_until = 2026-07
state = SUPERSEDED

M2:
type = PROFILE
content = "Prefers Vuetify"
valid_from = 2026-07
state = ACTIVE
```

Isso preserva histórico sem confundir preference atual.

---

# 81. Decision Memory Example

```text
type = SEMANTIC
scope = project:sofias-assistant
content = "Operational Store initial implementation is SQLite"
provenance = USER_CONFIRMED / PROJECT_DECISION
state = ACTIVE
```

Futuramente:

```text
"Operational Store migrated to PostgreSQL"
```

não precisa tornar primeira memória falsa historicamente.

---

# 82. Episode Example

```text
type = EPISODIC
scope = project:sofias-assistant
content = "Architecture definition session covering ADR-0001 to ADR-0012"
started_at = ...
ended_at = ...
```

---

# 83. Procedure Example

```text
type = PROCEDURAL
scope = project:sofias-assistant
content = "Release validation workflow"
```

poderá futuramente ser materializado como Skill.

---

# 84. Procedural Validation

Procedures aprendidas deverão possuir evidência de que funcionam.

Possíveis metadata:

- observed success count;
- last validated_at;
- applicable version;
- failure history.

Isso evita skills eternamente consideradas válidas após mudanças no ambiente.

---

# 85. Procedural Temporal Validity

Skill/procedure poderá perder validade.

Exemplo:

```text
procedure uses command removed in v2
```

Deverá ser possível superseder ou marcar stale.

---

# 86. Skill Execution Result Feedback

Task Runtime poderá futuramente informar ao Sofias Memory:

```text
Skill X succeeded
```

ou:

```text
Skill X failed due to changed environment
```

Isso poderá alimentar procedural maintenance.

---

# 87. Memory Feedback

User correction e explicit feedback poderão atualizar lifecycle/confidence.

O fluxo deverá preservar previous evidence.

---

# 88. Forgetting Policy

Além de Forget explícito, poderão existir policies futuras de:

- decay;
- archival;
- stale observation cleanup;
- low-value episode retention.

Nenhuma dessas será adotada silenciosamente para memórias importantes sem definição explícita.

---

# 89. Memory Decay

Semantic relevance/recency pode diminuir.

Mas isso não significa apagar automaticamente fatos importantes.

Decay de retrieval score e deletion são conceitos diferentes.

---

# 90. Memory Garbage Collection

Dados derivados ou candidates rejeitados poderão possuir cleanup policies.

O Sofias Memory deverá controlar isso.

---

# 91. Contradiction Resolution

Quando contradiction não puder ser resolvida deterministicamente:

- manter ambas;
- marcar conflito;
- solicitar user confirmation quando relevante.

Não inventar vencedor.

---

# 92. Memory Conflicts in Context

ContextBuilder deverá evitar apresentar duas memories conflitantes como fatos simultaneamente sem metadata.

Pode apresentar:

```text
"Há informações conflitantes sobre X."
```

quando necessário.

---

# 93. Memory Candidate Persistence

Candidates poderão inicialmente existir no Assistant Operational Store.

Isso permite:

- recovery;
- confirmation pending;
- retry.

Depois de persistência authoritative, Sofias Memory passa a ser owner.

---

# 94. Future Native Candidate Support

Sofias Memory poderá futuramente possuir candidate lifecycle nativo.

Se isso ocorrer, Assistant Adapter poderá simplificar sua persistência operacional.

A authority boundary deverá permanecer clara.

---

# 95. Memory Event Model

Eventos conceituais poderão incluir:

```text
MemoryCandidateCreated
MemoryCandidateConfirmed
MemoryPersisted
MemorySuperseded
MemoryRejected
MemoryForgotten
MemoryConflictDetected
```

---

# 96. Memory Audit

Mudanças importantes deverão ser correlacionáveis com:

- source;
- user confirmation;
- Task;
- AgentRun;
- lifecycle transition.

Audit não precisa armazenar conteúdo sensível integral.

---

# 97. Memory and Agents

Agent poderá:

- solicitar recall;
- sugerir candidate;
- produzir procedure candidate.

Agent não poderá:

- marcar memória como USER_CONFIRMED;
- alterar provenance;
- conceder a si acesso a scope adicional;
- tornar inference authoritative por conta própria.

---

# 98. Memory and Plugins

Plugins seguem mesmas regras.

Plugin poderá fornecer observation.

O runtime define provenance e Policy.

---

# 99. Memory and Prompt Injection

Knowledge Source ou memory pode conter texto malicioso.

Memória deverá ser apresentada ao provider como data contextual, não instruction authority.

Provenance ajudará a distinguir:

```text
user preference
```

de:

```text
text copied from a website
```

---

# 100. Persistence Model Evolution in Sofias Memory

O Sofias Memory deverá evoluir para representar Cognitive Memory como domínio explícito.

Não será obrigatório substituir seu modelo atual de Sources/Documents/Chunks.

A evolução deve ser aditiva:

```text
Knowledge Source model
+
Cognitive Memory model
```

---

# 101. Required Sofias Memory Evolution

Este ADR estabelece que o Sofias Memory precisará, progressivamente, suportar capabilities equivalentes a:

1. typed cognitive memory;
2. stable memory IDs;
3. provenance;
4. confidence;
5. observed_at / valid_from / valid_until;
6. lifecycle state;
7. supersession/contradiction relationships;
8. scope/domain;
9. importance;
10. typed retrieval;
11. procedural/skill integration.

---

# 102. Not Required Before Assistant Skeleton

Todas essas capabilities não precisam estar concluídas antes de iniciar o Sofia's Assistant.

A implementação poderá ser incremental.

O primeiro Assistant MVP precisa, no mínimo, de um vertical slice real de:

```text
Memory Candidate
    ↓
persist meaningful memory
    ↓
recall
    ↓
Context Builder
```

---

# 103. MVP Memory Slice

Para o primeiro MVP, priorizar:

- SEMANTIC;
- PROFILE básico;
- provenance;
- scope;
- candidate confirmation quando necessário;
- recall;
- supersession mínima;
- Conversation consolidation básica.

EPISODIC e PROCEDURAL poderão amadurecer progressivamente, desde que arquitetura já os comporte.

---

# 104. Existing API Compatibility

Enquanto typed APIs não existirem, Adapter poderá utilizar mecanismos atuais do Sofias Memory de forma controlada.

Contudo, qualquer compatibilidade temporária deverá estar documentada como transitional adapter.

Não transformar workaround em domain contract permanente.

---

# 105. Transitional Representation

Se for necessário representar uma Cognitive Memory usando infra atual, ela deverá carregar metadata explícita indicando:

```text
memory_type
provenance
scope
lifecycle
```

ou equivalente.

Não tratar texto chunkado sem metadata como suficiente.

---

# 106. Migration of Transitional Memories

Quando APIs nativas forem criadas, deverá existir caminho de migration/reconciliation para transitional memories relevantes.

---

# 107. API Design Principle

Novas APIs do Sofias Memory deverão ser genéricas.

Preferir:

```text
POST /memories
type=PROFILE
```

conceitualmente,

e não:

```text
POST /assistant/save-preference
```

---

# 108. Retrieval API Principle

Recall deverá poder filtrar por semântica.

Exemplos:

```text
type
scope
lifecycle
temporal validity
provenance
```

quando apropriado.

---

# 109. Memory Authority

Uma memory ACTIVE não significa verdade absoluta.

Ela significa:

> memory currently accepted as usable under its provenance, confidence, scope and temporal semantics.

Isso preserva epistemic humility do sistema.

---

# 110. Testing

Deverão existir testes para:

- PROFILE persistence;
- SEMANTIC persistence;
- EPISODIC persistence;
- PROCEDURAL persistence;
- provenance;
- USER_ASSERTED vs INFERRED;
- assistant-generated contamination prevention;
- temporal validity;
- contradiction;
- supersession;
- confirmation;
- rejection;
- deduplication;
- typed recall;
- scoped Agent recall;
- consolidation.

---

# 111. Adversarial Memory Tests

Deverão existir testes específicos para:

- prompt injection persisted in source;
- assistant inventing user fact;
- stale preference retrieval;
- contradictory memories;
- Agent attempting to alter provenance;
- cross-project memory leakage.

---

# 112. Alternatives Considered

## Alternative A — Everything is Document + Chunk

### Advantages

- reutiliza toda infraestrutura atual;
- implementação rápida.

### Rejected as long-term model because

- perde semântica cognitiva;
- awkward temporal validity;
- contradiction/supersession difíceis;
- profile facts viram fake documents;
- procedures ficam pouco estruturadas.

Document/Chunk continuará correto para Knowledge Sources.

---

## Alternative B — Store whole conversation forever and rely on semantic search

### Advantages

- simples;
- sem candidate extraction.

### Rejected because

- muito ruído;
- assistant-generated contamination;
- fatos contraditórios;
- recall ruim;
- custos crescentes;
- sem lifecycle cognitivo.

---

## Alternative C — Only key/value profile memory

### Advantages

- ótimo para preferências.

### Rejected because

não atende:

- episodes;
- semantic project knowledge;
- procedures;
- provenance rica;
- graph relationships.

---

## Alternative D — Separate memory database inside Assistant

### Rejected because

viola ADR-0011 e duplica o Sofias Memory.

---

# 113. Consequences

## Positive

- memória mais confiável;
- evita contamination por conteúdo da própria Sofia;
- suporta preferências que mudam;
- melhora retrieval;
- preserva histórico;
- permite episódios e skills;
- contradictions tornam-se explícitas;
- provenance melhora confiança e auditabilidade;
- Sofias Memory evolui para engine cognitiva mais geral.

## Negative

- Sofias Memory precisará evoluir;
- lifecycle fica mais complexo;
- consolidation exige inteligência adicional;
- retrieval precisa considerar mais metadata;
- migration das estruturas atuais poderá exigir trabalho;
- schemas cognitivos precisarão ser cuidadosamente definidos.

Esses custos são considerados parte essencial da evolução do produto.

---

# 114. Architectural Invariants

### INV-001

Cognitive Memory possui tipo explícito.

### INV-002

Persisted memory possui provenance.

### INV-003

Assistant-generated content não vira user fact automaticamente.

### INV-004

INFERRED não é equivalente a USER_CONFIRMED.

### INV-005

Conversation History não é Cognitive Memory.

### INV-006

Contradiction não é resolvida por overwrite silencioso.

### INV-007

Supersession preserva histórico quando aplicável.

### INV-008

Temporal validity é distinta de creation time.

### INV-009

Importance é distinta de retrieval relevance.

### INV-010

Procedure/Skill não concede execution authority.

### INV-011

Agent não pode auto-confirmar memory.

### INV-012

Knowledge Source e Cognitive Memory são domínios semanticamente distintos.

### INV-013

Memory scope deve ser respeitado no retrieval.

### INV-014

Forget e Supersession são operações diferentes.

### INV-015

Persistent prompt content não constitui instruction authority.

### INV-016

Sofias Memory permanece authority da Cognitive Memory persistente.

---

# 115. Deferred Decisions

Serão definidos no Technical Backlog do Sofias Memory:

- schemas físicos;
- table/model names;
- final lifecycle enum;
- confidence representation;
- provenance schema;
- scope representation;
- contradiction detector;
- consolidation pipeline;
- ranking formula;
- typed recall API;
- candidate API;
- relationship model;
- Skill schema;
- migration strategy;
- retention/decay policies;
- importance calculation;
- native vs transitional storage phases.

---

# 116. Decision Summary

O Sofia's Assistant e o Sofias Memory adotarão um modelo explícito de Cognitive Memory composto inicialmente por:

```text
PROFILE
SEMANTIC
EPISODIC
PROCEDURAL
```

Toda memória persistente deverá possuir provenance e poderá possuir confidence, temporal validity, scope, importance e lifecycle.

Memórias novas poderão confirmar, contradizer ou superseder memórias existentes sem apagar silenciosamente o histórico.

Assistant-generated content e inferências não se tornarão automaticamente fatos sobre o usuário.

Conversation History será matéria-prima para Memory Candidates e consolidation, mas não será Long-Term Memory por definição.

Procedural Memory dará suporte ao futuro ecossistema de Skills/data_skill sem conceder authority de execução.

Esse modelo exigirá evolução incremental do Sofias Memory para além de sua atual ênfase em Knowledge Sources, preservando a infraestrutura existente e adicionando um domínio cognitivo explícito e genérico.