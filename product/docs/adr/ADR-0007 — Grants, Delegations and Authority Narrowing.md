# ADR-0007 — Grants, Delegations and Authority Narrowing

**Status:** Accepted  
**Project:** Sofia's Assistant  
**Decision date:** 2026-08-31  
**Scope:** Permission Grants, Delegations, authority inheritance, revocation and temporal/resource scopes

---

# 1. Context

O ADR-0006 estabeleceu que:

> AI proposes. Runtime authorizes. Executor acts.

Também ficou definido que nenhum LLM, Agent, Plugin ou Tool pode conceder autoridade a si próprio.

Para que Sofia possa agir de forma autônoma sem exigir confirmação constante, o runtime precisa representar explicitamente:

- permissões persistentes;
- permissões temporárias;
- delegações;
- resource scopes;
- limites;
- validade temporal;
- revogação;
- autoridade derivada para sub-agents.

Esse modelo precisa permitir autonomia útil sem criar autoridade implícita ou ilimitada.

---

# 2. Decision

O Sofia's Assistant adotará dois conceitos distintos:

```text
Permission Grant
```

e:

```text
Delegation
```

Um `Permission Grant` representa autoridade concedida.

Uma `Delegation` representa trabalho/objetivo delegado dentro de limites explícitos.

Eles poderão se relacionar, mas não serão a mesma entidade.

---

# 3. Fundamental Separation

A regra principal será:

```text
Objective ≠ Authority
```

Exemplo:

> “Sofia, mantenha este repositório atualizado.”

define um objetivo.

Não significa automaticamente:

```text
filesystem.write = all
shell.execute = unrestricted
git.push = always
network.upload = unrestricted
```

A autoridade necessária deverá existir explicitamente ou ser solicitada ao usuário.

---

# 4. Permission Grant

Um `PermissionGrant` representa autorização explícita para determinado subject utilizar uma capability dentro de um scope.

Conceitualmente:

```text
PermissionGrant
├── id
├── subject
├── capability
├── resource_scope
├── constraints
├── issued_at
├── valid_from
├── expires_at
├── revoked_at
├── issued_by
└── metadata
```

O schema físico será definido posteriormente.

---

# 5. Grant Subject

O subject identifica quem pode utilizar a autorização.

Subjects poderão incluir:

```text
SOFIA_ROOT
AGENT_DEFINITION
AGENT_RUN
PLUGIN
INTEGRATION
SYSTEM_RUNTIME
```

Nem todos precisarão existir no MVP.

---

# 6. Root Authority

Sofia/root não possuirá autoridade ilimitada apenas por ser root orchestrator.

Ela continuará sujeita aos Grants e policies válidos para o contexto.

“Root” significa:

> autoridade de coordenação.

Não significa:

> superuser irrestrito.

---

# 7. Resource Scope

Grants poderão restringir recursos.

Exemplos:

```text
capability = filesystem.read
scope = D:\Projects\sofias_assistant\**
```

```text
capability = memory.read
scope = project-sofias-assistant
```

```text
capability = git.push
scope = repository:sofias_assistant
```

Um Grant nunca deverá ser interpretado como mais amplo que seu resource scope.

---

# 8. Constraints

Um Grant poderá possuir constraints adicionais.

Exemplos futuros:

```text
allowed_extensions
allowed_commands
allowed_hosts
allowed_branches
max_file_size
network_access
max_execution_time
max_actions
cost_limit
```

Constraints deverão reduzir autoridade, nunca ampliá-la implicitamente.

---

# 9. Temporal Scope

Grants poderão possuir diferentes lifecycles.

Baseline conceitual:

```text
ONE_SHOT
SESSION
UNTIL_TIME
UNTIL_REVOKED
WHILE_RESOURCE_ACTIVE
```

A implementação inicial poderá suportar apenas um subconjunto.

O modelo, entretanto, não deverá pressupor apenas:

```text
temporary / permanent
```

---

# 10. One-shot Authorization

Uma confirmação para uma operação específica poderá resultar em Grant consumível.

Exemplo:

```text
git.push
repository = X
branch = main
Task = T
uses = 1
```

Após execução válida, a autoridade deixa de existir.

---

# 11. Session Grant

O usuário poderá autorizar uma capability apenas durante determinada sessão.

Exemplo:

> “Durante esta sessão pode ler os arquivos deste projeto sem me perguntar.”

O Grant deverá expirar junto da sessão relevante.

---

# 12. Time-bounded Grant

Poderá existir autorização até determinado instante.

Exemplo:

> “Pode executar esses testes até as 18h.”

Após expiração:

```text
Grant no longer effective
```

mesmo que permaneça armazenado para audit.

---

# 13. Until Revoked

O usuário poderá conceder autorização persistente.

Exemplo:

> “Pode sempre ler meus projetos em `D:\Projects`.”

Esse Grant continuará válido até:

- revogação explícita;
- mudança de policy que o invalide;
- recurso deixar de existir, quando aplicável.

---

# 14. Revocation

Revogação deverá ser explícita e persistente.

Preferir:

```text
revoked_at
```

em vez de apagar silenciosamente o Grant.

Isso preserva Audit Trail.

Um Grant revogado não poderá voltar a ser efetivo sem nova concessão explícita.

---

# 15. Grant Mutation

Alterar o scope de um Grant existente deverá ser tratado com cuidado.

Quando houver impacto significativo de autoridade, preferir semanticamente:

```text
revoke old Grant
create new Grant
```

em vez de reescrever histórico de autorização.

---

# 16. Delegation

Uma `Delegation` representa um objetivo confiado à Sofia.

Conceitualmente:

```text
Delegation
├── id
├── objective
├── resource_scope
├── authority_scope
├── constraints
├── lifecycle
├── created_at
├── expires_at
├── revoked_at
├── status
└── metadata
```

Delegation não substitui Permission Grants.

---

# 17. Delegation Example

Usuário:

> “Cuide deste projeto até terminarmos a versão 1.”

Poderemos ter:

```text
Delegation
objective:
  maintain project until v1

resources:
  D:\Projects\sofias_assistant

allowed:
  filesystem.read
  filesystem.write
  shell.execute
  git.local

restricted:
  git.push → confirmation

forbidden:
  access outside workspace
```

A representação final dependerá do modelo de Grants.

---

# 18. Delegation Authority

Delegation poderá referenciar ou derivar authority já concedida.

Ela não poderá criar authority que não existe.

Formalmente:

```text
Delegation authority
    ⊆ Root authorized authority
```

---

# 19. Root Creates Delegation Context

Somente Sofia/root será autoridade de coordenação para transformar uma Delegation em execuções concretas.

Uma Delegation poderá originar:

```text
Task
AgentRun
ToolCall
```

mas essas execuções continuarão sujeitas ao PolicyEngine.

---

# 20. Agent Authority

Um sub-agent receberá authority derivada exclusivamente para seu `AgentRun`.

Formalmente:

```text
AgentRun authority
    ⊆ Delegation authority
    ⊆ Root effective authority
```

---

# 21. No Transitive Privilege Expansion

Um Agent não poderá ampliar autoridade solicitando outro Agent.

Exemplo proibido:

```text
Development Agent
  has filesystem.read
      ↓
requests Shell Agent
      ↓
Shell Agent gets unrestricted shell
```

Isso viola narrowing.

---

# 22. Root-only Agent Instantiation

Sub-agents não criarão outros sub-agents diretamente.

Quando Agent A precisar de outra especialização:

```text
Agent A
   ↓
DelegationRequest
   ↓
Sofia/root
   ↓
Policy / Authority check
   ↓
Agent B
```

Todos permanecem subordinados à root.

---

# 23. Delegated Context

Delegation deverá restringir não apenas capabilities, mas também contexto.

Exemplo:

```text
Research Agent
```

poderá receber:

- objetivo;
- documentos relevantes;
- project memory;
- web access.

Sem receber automaticamente:

- memória pessoal inteira;
- secrets;
- unrelated conversation history.

---

# 24. Authority Snapshot

Para execuções relevantes, o runtime poderá materializar um snapshot de autoridade efetiva.

Isso permite saber posteriormente:

> Qual autoridade estava disponível exatamente quando essa ação foi solicitada?

Essa capability será importante para Audit Trail.

A representação concreta será definida futuramente.

---

# 25. Effective Authority

A autoridade efetiva será resultado da interseção entre:

```text
Grants
∩ Delegation
∩ Resource scope
∩ Constraints
∩ Policy
∩ Runtime context
```

Não será uma simples consulta:

```text
has_permission("filesystem.write")
```

---

# 26. Deny Overrides

Policies explícitas de negação poderão restringir Grants.

Exemplo:

```text
Grant:
  filesystem.write D:\Projects\**

Policy:
  deny write *.pem
```

Resultado:

```text
write private-key.pem → DENY
```

A autoridade efetiva nunca será calculada apenas por acumulação positiva de Grants.

---

# 27. Grant Precedence

Este ADR não congela uma linguagem completa de precedência.

Mas a regra geral será conservadora:

```text
explicit restriction > broad allow
```

e:

```text
narrower scope > broader scope
```

quando aplicável.

---

# 28. Confirmation Can Create Grant

Uma confirmação do usuário poderá resultar em:

### One-shot authority

> “Sim, faça isso agora.”

ou:

### Persistent authority

> “Pode fazer isso sempre neste projeto.”

Essas duas ações deverão produzir estados diferentes.

A UI deverá deixar essa diferença clara.

---

# 29. Confirmation Cannot Be Ambiguous

O runtime não deverá transformar automaticamente:

```text
"sim"
```

em Grant persistente amplo.

A confirmação deverá estar ligada ao request apresentado.

Qualquer expansão de scope deverá ser explícita.

---

# 30. Permission Requests

Quando autoridade suficiente não existir, o runtime poderá gerar um `PermissionRequest`.

Exemplo:

```text
Task requires:
  shell.execute

Current authority:
  filesystem.read/write only
```

A Sofia poderá explicar:

> “Para continuar, preciso executar `pytest` neste workspace.”

O usuário poderá:

- negar;
- autorizar uma vez;
- autorizar durante a sessão;
- criar Grant persistente compatível.

---

# 31. Permission Negotiation

Sofia poderá sugerir o **menor Grant suficiente**.

Exemplo:

Preferir:

```text
shell.execute
command = pytest
cwd = project X
```

em vez de:

```text
unrestricted shell forever
```

Isso implementa least privilege na UX.

---

# 32. Persistent Delegations

Delegations poderão sobreviver a:

- fechamento da conversa;
- restart do Core;
- reboot.

Desde que seu lifecycle continue válido.

Exemplo:

> “Monitore esse projeto esta semana.”

Não deve desaparecer porque a janela foi fechada.

---

# 33. Delegation Revocation

Usuário poderá encerrar Delegation.

Revogação deverá impedir novas execuções derivadas.

Tasks já em andamento deverão ser avaliadas conforme sua semântica:

```text
cancel
pause
finish safe step
request user decision
```

A regra concreta será definida junto do Task Runtime.

---

# 34. Delegation Expiration

Uma Delegation poderá expirar por:

- horário;
- conclusão do objetivo;
- conclusão de Task;
- recurso deixar de estar ativo;
- revogação;
- policy change.

---

# 35. Delegation Status

Estados conceituais poderão incluir:

```text
ACTIVE
PAUSED
COMPLETED
EXPIRED
REVOKED
```

A state machine concreta não é definida aqui.

---

# 36. Grant vs Delegation Example

Considere:

```text
Grant:
  Sofia may read/write D:\Projects\**
```

Isso concede authority.

Agora:

```text
Delegation:
  Prepare release of project X
```

define objective e scope.

A combinação permite Sofia atuar autonomamente em X dentro da autoridade existente.

---

# 37. Global Grants

Grants globais serão possíveis, porém deverão ser usados com cautela.

Exemplo:

```text
desktop.open_app = allowed
```

pode ser razoável globalmente.

Já:

```text
shell.execute = unrestricted global
```

deverá ser tratado como autoridade de alto impacto.

---

# 38. Resource-specific Grants

O modelo deverá incentivar Grants específicos.

Exemplo:

```text
filesystem.write:
  D:\Projects\sofias_assistant\**
```

é preferível a:

```text
filesystem.write:
  C:\**
```

---

# 39. Secrets and Grants

Um Grant de acesso a determinado recurso não significa acesso automático aos secrets usados pela Integration.

Exemplo:

```text
GitHub Integration authorized
```

não significa que Agent possa ler o GitHub token bruto.

A Integration poderá executar em nome do Agent sem revelar a credencial.

---

# 40. Memory Authority

Grants poderão restringir memória.

Exemplo:

```text
Development Agent
  memory.read:
    project-sofias-assistant
```

sem:

```text
personal
finance
other projects
```

Isso reforça context isolation.

---

# 41. Network Authority

Delegations e Grants poderão limitar rede.

Exemplo:

```text
network.request:
  allow docs.python.org
  allow github.com
```

sem upload arbitrário para qualquer host.

Essa capability será importante para sandbox e generated code.

---

# 42. Shell Authority

Shell deverá suportar narrowing forte.

Exemplo conceitual:

```text
shell.execute
├── cwd = project X
├── executable = pytest
├── network = deny
├── elevation = deny
└── timeout = 300s
```

Isso é authority muito diferente de shell irrestrito.

---

# 43. Data Locality Authority

Grants/Delegations poderão restringir envio de dados para cloud.

Exemplo:

```text
data_locality:
  project-secret = LOCAL_ONLY
```

Essa regra deverá ser respeitada mesmo que Agent possua acesso ao conteúdo.

Acesso ao dado não implica direito de exfiltração.

---

# 44. Audit Requirements

Mudanças em Grants e Delegations deverão ser auditáveis.

Registrar, quando aplicável:

```text
who created
what changed
previous scope
new scope
reason/context
timestamp
correlation IDs
```

---

# 45. Persistence

Grants e Delegations persistentes serão armazenados no Operational Store definido no ADR-0002.

O Sofias Memory não será authority sobre permissions.

---

# 46. Startup and Recovery

Após restart, o Core deverá reconstruir:

- Grants ativos;
- Delegations ativas;
- expirations;
- revocations;
- Tasks vinculadas;
- confirmations pendentes.

Nenhuma authority deverá ser recriada apenas com base em conversation history.

---

# 47. Policy Changes

Uma mudança de Policy poderá tornar um Grant existente não efetivo.

Exemplo:

```text
Grant exists
+
new security policy forbids operation
=
operation denied
```

Não é necessário apagar o Grant para que ele deixe de produzir authority efetiva.

---

# 48. Grant Validation

Um Grant inválido ou com scope não reconhecido deverá falhar de forma conservadora.

Não será permitido:

```text
unknown scope → treat as wildcard
```

Preferir:

```text
unknown scope → ineffective / deny
```

---

# 49. Revocation Propagation

Quando um Grant for revogado, novas ToolCalls dependentes dele deverão ser recusadas imediatamente.

Operações já em execução serão tratadas conforme seu execution model e cancellation semantics.

---

# 50. Authority Caching

O runtime poderá cachear resultados de authority evaluation por performance.

Contudo, cache não poderá ignorar:

- revocation;
- expiration;
- Policy change;
- Delegation state change.

A implementação deverá preservar invalidação correta.

---

# 51. Alternatives Considered

## Alternative A — Permissions embedded only in prompts

Exemplo:

```text
"You may edit files in project X."
```

### Rejected because

- não determinístico;
- não auditável;
- vulnerável a prompt injection;
- difícil de revogar;
- provider-dependent.

---

## Alternative B — Boolean permission flags

Exemplo:

```text
can_use_shell = true
can_write_files = true
```

### Rejected because

não representa:

- resource scopes;
- temporal scopes;
- constraints;
- Agents;
- Delegations;
- one-shot authorization.

---

## Alternative C — Delegation implies all required permissions

### Rejected because

mistura objetivo e autoridade.

Uma Task pode exigir poderes que o usuário nunca pretendeu conceder.

---

## Alternative D — Agents own permanent permissions

### Rejected because

facilita privilege accumulation e quebra least privilege.

Agents recebem autoridade derivada e limitada por execução/contexto.

---

# 52. Consequences

## Positive

- autonomia segura;
- menor confirmation fatigue;
- least privilege;
- revogação explícita;
- context isolation;
- delegações persistentes;
- Agents limitados;
- auditabilidade;
- resource-level authorization.

## Negative

- modelo mais complexo que permission flags;
- UX precisa explicar scopes de maneira compreensível;
- matching de resources exige implementação cuidadosa;
- revocation e expiration precisam ser eficientes;
- testes de segurança serão essenciais.

Os custos são considerados compatíveis com a autonomia pretendida.

---

# 53. Architectural Invariants

### INV-001

Objective nunca concede authority implicitamente.

### INV-002

Delegation authority nunca excede Root effective authority.

### INV-003

AgentRun authority nunca excede Delegation authority.

### INV-004

Grant possui scope explícito.

### INV-005

Revoked Grant nunca volta a ser efetivo automaticamente.

### INV-006

Confirmation é vinculada à ação/scope apresentado.

### INV-007

Persistent authority exige concessão explícita.

### INV-008

Unknown scope nunca vira wildcard.

### INV-009

Child authority nunca amplia parent authority.

### INV-010

Conversation text não é authority source.

### INV-011

Permission state pertence ao Operational Store.

### INV-012

Possuir acesso a dado não implica autoridade para enviá-lo externamente.

---

# 54. Deferred Decisions

Serão definidos posteriormente:

- schemas finais de Grant e Delegation;
- resource scope language;
- matcher de paths;
- inheritance algorithm;
- permission request UI;
- confirmation UX;
- Grant templates;
- default Grants;
- constraint vocabulary;
- expiration scheduler;
- exact status machines;
- representation of authority snapshots;
- policy precedence rules.

---

# 55. Decision Summary

Sofia's Assistant utilizará `Permission Grants` para representar autoridade explícita e `Delegations` para representar objetivos confiados à Sofia.

Objetivo e autoridade permanecerão separados.

Toda autoridade derivada será progressivamente reduzida:

```text
Root effective authority
        ↓
Delegation authority
        ↓
AgentRun authority
        ↓
Tool execution authority
```

Sub-agents nunca poderão ampliar authority.

Grants poderão possuir resource scopes, constraints, temporal scopes, expiration e revocation.

Confirmações poderão criar autoridade one-shot ou persistente apenas quando isso for explicitamente solicitado pelo usuário.

O modelo deverá permitir autonomia significativa sem depender de prompts como mecanismo de segurança.