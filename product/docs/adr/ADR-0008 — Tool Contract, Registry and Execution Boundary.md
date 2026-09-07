# ADR-0008 — Tool Contract, Registry and Execution Boundary

**Status:** Accepted  
**Project:** Sofia's Assistant  
**Decision date:** 2026-08-31  
**Scope:** ToolSpec, Tool Registry, ToolCall normalization, execution boundary, ToolResult and side-effect semantics

---

# 1. Context

O Sofia's Assistant utilizará Tools para executar capacidades delimitadas.

Exemplos:

- ler arquivos;
- escrever arquivos;
- abrir aplicações;
- consultar janela ativa;
- executar shell;
- realizar web search;
- ler conteúdo web;
- capturar screenshot;
- interagir com Git;
- futuramente enviar mensagens ou controlar integrações externas.

O ADR-0004 definiu que ToolCalls originados por providers serão normalizados antes de entrar no domínio.

O ADR-0006 definiu que toda ação protegida deve passar pelo PolicyEngine.

O ADR-0007 definiu que Grants, Delegations e resource scopes limitam authority.

Portanto, o Sofia Core precisa de um contrato formal que descreva:

- o que uma Tool faz;
- quais inputs aceita;
- quais capabilities exige;
- quais efeitos pode produzir;
- quais permissões são necessárias;
- como será executada;
- como retorna resultados;
- como é registrada e descoberta.

Uma Tool não poderá ser apenas uma função Python informal exposta diretamente ao LLM.

---

# 2. Decision

Toda Tool do Sofia's Assistant deverá possuir um contrato formal separado de sua implementação.

A arquitetura conceitual será:

```text
Provider
   ↓
Normalized ToolCall
   ↓
Tool Registry
   ↓
ToolSpec
   ↓
PolicyEngine
   ↓
Execution Boundary
   ↓
Tool Handler
   ↓
ToolResult
```

O domínio, providers, Agents e plugins trabalharão com contratos normalizados.

---

# 3. Fundamental Rule

A regra será:

> **A Tool describes a bounded capability. The runtime decides whether and how it may execute.**

Uma Tool não possui autoridade própria.

---

# 4. Tool

Uma `Tool` representa uma operação delimitada e invocável.

Exemplos válidos:

```text
filesystem.read
filesystem.write
desktop.open_app
web.search
shell.execute
```

Uma Tool deverá ser suficientemente específica para que:

- inputs sejam validáveis;
- efeitos sejam compreensíveis;
- Policy possa avaliá-la;
- resultado seja auditável.

---

# 5. Tool Is Not Agent

Uma Tool executa uma operação delimitada.

Um Agent recebe um objetivo e pode escolher múltiplas Tools.

Exemplo:

```text
read_file
```

é Tool.

```text
Development Agent
```

não é Tool.

---

# 6. ToolSpec

Toda Tool deverá possuir metadata formal.

Conceitualmente:

```text
ToolSpec
├── name
├── version
├── description
├── input_schema
├── output_schema
├── capabilities
├── required_permissions
├── resource_semantics
├── risk_profile
├── side_effects
├── idempotency
├── timeout_policy
├── execution_mode
├── cancellation_policy
└── metadata
```

O schema final será definido no Technical Backlog.

---

# 7. Tool Name

Tool names deverão ser estáveis, únicas e semanticamente claras.

Preferir namespaces:

```text
filesystem.read
filesystem.write
shell.execute
desktop.open_app
web.search
```

em vez de nomes genéricos como:

```text
run
execute
do_action
```

---

# 8. Tool Versioning

ToolSpec poderá possuir versão.

Mudanças incompatíveis em input/output semantics deverão ser tratadas explicitamente.

A estratégia concreta de versionamento será definida posteriormente.

---

# 9. Description

Description existe para ajudar:

- AI providers;
- UI;
- developers;
- Agents.

Ela não será authority source.

Uma description afirmando:

```text
"This tool is safe."
```

não altera Policy.

---

# 10. Input Schema

Toda Tool deverá validar argumentos contra schema.

Não será permitido confiar apenas no provider.

Fluxo:

```text
ToolCall arguments
      ↓
schema validation
      ↓
validated input
```

Input inválido deverá falhar antes da execução.

---

# 11. Output Schema

Quando aplicável, ToolResult poderá possuir payload validável.

Isso é especialmente importante para Tools consumidas por Agents.

Output schema não precisa tornar todos os retornos rígidos demais, mas deve reduzir contratos implícitos.

---

# 12. Tool Registry

O Sofia Core possuirá um `Tool Registry`.

Ele será authoritative para Tools atualmente disponíveis.

Responsabilidades:

- registrar ToolSpec;
- associar handler;
- impedir collisions;
- validar metadata;
- listar Tools;
- fornecer ToolSpecs para providers/Agents;
- controlar enable/disable;
- resolver execução.

---

# 13. Registration

Uma Tool só poderá ser utilizada depois de registro válido.

Tools built-in, integrations e plugins usarão o mesmo conceito de registry.

---

# 14. Collision Handling

Duas Tools não poderão registrar o mesmo nome/versão incompatível silenciosamente.

Collision deverá resultar em:

- rejeição;
- namespace explícito;
- resolução configurada.

Nunca em override silencioso.

---

# 15. Enable/Disable

Tools poderão possuir estado enabled/disabled.

Tool disabled não deverá ser enviada ao provider como disponível nem executada.

---

# 16. Tool Discovery

Provider receberá apenas ToolSpecs aplicáveis ao contexto.

Não será obrigatório enviar todas as Tools existentes em todo request.

Isso reduz:

- contexto;
- risco;
- confusão do modelo.

---

# 17. Agent Tool Subsets

AgentRun receberá subconjunto explícito de Tools.

Exemplo:

```text
Research Agent
├── web.search
├── web.read
└── memory.read(project)
```

sem:

```text
shell.execute
filesystem.write
```

quando desnecessário.

---

# 18. ToolCall

Provider ToolCalls serão normalizados pelo Adapter.

Conceitualmente:

```text
ToolCall
├── id
├── tool_name
├── arguments
├── requested_by
├── conversation_id
├── task_id
├── agent_run_id
├── correlation_id
└── provider_metadata
```

Nem todos os campos serão obrigatórios em todos os contextos.

---

# 19. ToolCall Identity

Cada ToolCall deverá possuir identidade estável durante seu lifecycle.

Isso permite:

- PolicyDecision correlation;
- retries controlados;
- audit;
- ToolResult association.

---

# 20. ToolCall Does Not Execute Immediately

Receber ToolCall não significa executar.

Fluxo obrigatório:

```text
ToolCall
   ↓
resolve ToolSpec
   ↓
validate input
   ↓
Policy evaluation
   ↓
execution decision
```

---

# 21. Policy Boundary

Toda Tool protegida será avaliada pelo PolicyEngine.

Tool Registry não decide authorization.

Tool Handler não decide authorization.

Executor não cria autoridade.

---

# 22. Policy Inputs from ToolSpec

ToolSpec poderá fornecer metadata para Policy.

Exemplos:

- required capability;
- expected side effects;
- resource argument mapping;
- default risk profile;
- execution mode.

Mas Policy poderá elevar ou restringir avaliação com base em argumentos concretos.

---

# 23. Resource Resolution

Antes de authorization, runtime deverá conseguir identificar resources relevantes.

Exemplo:

```text
filesystem.write(path="D:\Projects\x\a.py")
```

deverá produzir resource semanticamente comparável com Grants.

Resource resolution deverá ocorrer antes da execução.

---

# 24. Dynamic Risk

Risk não será apenas propriedade fixa da Tool.

Exemplo:

```text
filesystem.delete
```

pode receber:

```text
temp/build/*
```

ou:

```text
C:\Users\...
```

Os argumentos podem alterar risk evaluation.

---

# 25. Side-effect Metadata

ToolSpec deverá declarar categorias de side effects quando aplicável.

Exemplos:

```text
NONE
LOCAL_READ
LOCAL_WRITE
NETWORK_READ
NETWORK_WRITE
EXTERNAL_MUTATION
DESTRUCTIVE
```

A taxonomia final será definida depois.

---

# 26. Idempotency

ToolSpec deverá indicar semântica de idempotência.

Exemplos:

```text
read_file → idempotent
get_active_window → idempotent-ish observation
send_message → non-idempotent
git_push → potentially non-idempotent/external
```

Isso será relevante para retry e recovery.

---

# 27. Execution Mode

ToolSpec deverá permitir indicar modo de execução.

Baseline:

```text
IN_PROCESS
SUBPROCESS
SANDBOX
```

Detalhes serão definidos no ADR-0013.

---

# 28. Timeout

Toda Tool potencialmente bloqueante deverá possuir timeout policy.

Timeout poderá vir de:

- ToolSpec default;
- Policy constraint;
- Task override permitido.

Timeout não deverá ser inexistente por padrão em operations arriscadas.

---

# 29. Cancellation

ToolSpec deverá declarar cancellation semantics.

Exemplos:

```text
CANCELLABLE
COOPERATIVE
NON_INTERRUPTIBLE_SIDE_EFFECT
```

A nomenclatura final poderá mudar.

---

# 30. Executor

O `Tool Executor` será responsável por executar Tool Handler conforme decisão já autorizada.

Responsabilidades:

- preparar execution context;
- aplicar timeout;
- aplicar environment constraints;
- chamar handler;
- capturar error;
- produzir ToolResult;
- registrar side effects observados;
- propagar cancellation.

---

# 31. Executor Is Not Policy

Executor não deverá possuir regras como:

```text
if delete:
    ask_confirmation()
```

Essas decisões pertencem ao PolicyEngine.

---

# 32. Defensive Checks

Handlers e Executor poderão possuir checks defensivos.

Exemplo:

- path traversal guard;
- file existence validation;
- network SSRF guard.

Esses checks são invariantes técnicos.

Não constituem um segundo authorization system.

---

# 33. Tool Handler

Handler será implementação concreta da capability.

Exemplo:

```text
FilesystemReadHandler
```

ToolSpec e Handler poderão ser objetos separados.

Isso permite:

- ToolSpec ser consumido sem importar implementação;
- testar registry independentemente;
- trocar handler preservando contrato.

---

# 34. Handler Context

Handler deverá receber execution context controlado.

Pode incluir:

```text
validated input
effective resource scope
Task context
cancellation token
deadline
sandbox/workspace
runtime services permitidos
```

Não deverá receber acesso irrestrito a todo Core por padrão.

---

# 35. ToolResult

Toda execução deverá retornar contrato normalizado.

Conceitualmente:

```text
ToolResult
├── tool_call_id
├── status
├── data
├── artifacts
├── side_effects
├── warnings
├── error
├── started_at
├── finished_at
└── metadata
```

---

# 36. Result Status

Baseline conceitual:

```text
SUCCEEDED
FAILED
CANCELLED
TIMED_OUT
```

Estados adicionais somente se necessários.

---

# 37. Errors

Tool errors deverão ser estruturados.

Conceitualmente:

```text
ToolError
├── code
├── message
├── details
├── retryable
└── internal_cause_ref
```

Stack traces não deverão ser enviados diretamente ao provider/usuário como regra.

---

# 38. Public vs Internal Error

ToolResult poderá possuir:

- erro seguro para runtime/provider;
- detalhe interno para logs/debug.

Isso evita vazamento de paths, secrets ou internals.

---

# 39. Artifacts

Tools poderão produzir artifacts.

Exemplos:

- file created;
- screenshot;
- diff;
- report;
- downloaded file.

Artifacts deverão possuir referências explícitas, não blobs arbitrários sempre embutidos no ToolResult.

---

# 40. Side Effects Observed

ToolResult deverá poder registrar efeitos observados.

Exemplo:

```text
modified_files:
  - a.py
  - b.py
```

Isso será importante para audit e recovery.

---

# 41. Side Effects Are Not Always Fully Knowable

Para operações externas, Tool poderá não saber todo efeito produzido.

Exemplo:

```text
shell.execute
```

pode modificar muitos recursos.

Essa incerteza deverá ser representável.

---

# 42. Shell as a Tool Family

Shell poderá existir como Tool privilegiada:

```text
shell.execute
```

Mas ToolSpec deverá expor resource/risk semantics fortes.

O runtime poderá aplicar constraints como:

- cwd;
- allowed executable;
- environment;
- network;
- timeout;
- elevation.

---

# 43. Filesystem Tools

Filesystem deverá preferir Tools específicas.

Exemplos:

```text
filesystem.read
filesystem.write
filesystem.list
filesystem.move
filesystem.delete
```

em vez de obrigar shell para tudo.

Isso melhora:

- Policy;
- audit;
- portability;
- safety.

---

# 44. Web Tools

MVP poderá possuir Tools como:

```text
web.search
web.read
```

Browser automation completa será posterior.

Network access continuará sujeita a Policy/locality.

---

# 45. Desktop Tools

MVP poderá incluir:

```text
desktop.open_app
desktop.active_window
```

Controle completo de input poderá vir depois.

---

# 46. Vision Tools

Screenshot manual poderá produzir artifact/context.

Exemplo:

```text
desktop.capture_screen
```

Vision inference não precisa ser implementada como Tool se pertencer ao AI Provider layer.

A fronteira será definida no backlog.

---

# 47. Tool Composition

Tools não deverão chamar outras Tools diretamente como padrão.

Quando composição for necessária, preferir:

```text
Task / Workflow / Agent
```

coordenando múltiplas Tools.

Isso preserva audit e Policy por operação.

---

# 48. Exception: Internal Primitive Calls

Implementações poderão compartilhar bibliotecas internas.

Isso não significa que uma Tool tenha semanticamente executado outra Tool.

O boundary importante é o side effect autorizado.

---

# 49. Tool-generated ToolCalls

Uma Tool não poderá criar e executar outra ToolCall para ampliar authority.

Se precisar de ação adicional:

```text
result indicates next action needed
```

e o orchestration layer decide.

---

# 50. Tool Retry

Retry automático dependerá de:

- idempotency;
- side effects;
- failure type;
- Task policy.

Não haverá retry universal.

---

# 51. Tool Recovery

Após crash, ToolCall poderá precisar de reconciliation.

Exemplo:

```text
git.push started
core crashed
```

Não podemos assumir:

```text
push did not happen
```

Task Recovery deverá usar ToolSpec/idempotency/observability para decidir.

---

# 52. External Mutations

Tools que causam external mutation deverão preferir retornar identificadores observáveis.

Exemplo:

```text
created_issue_id
message_id
commit_sha
```

Isso ajuda recovery.

---

# 53. Tool Availability

Tool poderá estar indisponível temporariamente.

Exemplos:

- executable ausente;
- integration desconectada;
- OS incompatível;
- plugin worker offline.

Registry deverá conseguir representar availability.

---

# 54. Platform Constraints

ToolSpec poderá indicar plataforma suportada.

Exemplo:

```text
windows
linux
macos
```

Como produto é Windows-first, algumas Tools poderão inicialmente ter handler apenas para Windows.

---

# 55. Capability vs Tool Name

Policy deverá preferir capabilities semanticamente estáveis.

Exemplo:

```text
capability = filesystem.write
```

Mesmo se houver múltiplas Tools que escrevem arquivos.

Isso evita grants amarrados demais a implementações.

---

# 56. Multiple Tools per Capability

Poderemos ter:

```text
filesystem.write
editor.apply_patch
```

ambas exigindo alguma forma de:

```text
filesystem.write
```

Capability e Tool não são equivalentes.

---

# 57. Provider Tool Declaration

Provider Adapter converterá ToolSpec interno para declaration nativa.

Isso poderá exigir remover metadata não suportada pelo provider.

Policy metadata não precisa ser enviada ao LLM integralmente.

---

# 58. Tool Description Exposure

O provider verá apenas descrição necessária para uso.

Detalhes sensíveis de Policy ou infraestrutura não deverão ser colocados em Tool descriptions.

---

# 59. Confirmation Flow

Quando Policy retornar `REQUIRE_CONFIRMATION`:

```text
ToolCall
   ↓
waiting confirmation
```

Handler não é executado.

Após confirmação válida, runtime deverá continuar com authority vinculada ao request.

---

# 60. ToolCall Mutation After Confirmation

Se argumentos mudarem significativamente após confirmação, a autorização anterior poderá deixar de ser válida.

Exemplo:

usuário aprovou:

```text
delete build/temp
```

LLM altera para:

```text
delete project root
```

Isso exige nova evaluation.

---

# 61. Canonical Arguments

Policy e Audit deverão usar argumentos validados/canonicalizados quando possível.

Exemplo:

```text
D:\Projects\x\..\secret
```

deve ser resolvido antes de scope matching.

---

# 62. Path Safety

Filesystem handlers deverão proteger contra:

- traversal;
- symlink/junction escape quando relevante;
- malformed paths;
- canonicalization bugs.

Resource scope precisa refletir recurso efetivamente acessado.

---

# 63. Network Safety

Network Tools deverão considerar proteções como:

- SSRF;
- loopback;
- link-local;
- metadata endpoints;
- private networks;

conforme capability.

Policy authorization para "web" não elimina checks de segurança de rede.

---

# 64. Secrets

Tool Handler não deverá receber secrets brutos sem necessidade.

Integrations poderão utilizar SecretStore internamente.

Agent/provider não precisa ver token bruto para usar uma Tool autenticada.

---

# 65. Logging

Inputs/outputs de Tools poderão conter dados sensíveis.

Logging deverá usar redaction/policies apropriadas.

Audit e logs não significam registrar conteúdo integral indiscriminadamente.

---

# 66. Tool Metrics

Runtime poderá medir:

- duration;
- success/failure;
- timeout;
- retry;
- usage count.

Isso ajudará observability e futuras heurísticas de Agent.

---

# 67. Plugin Tools

Plugins poderão registrar Tools pelo mesmo Registry.

Não haverá "plugin tool bypass".

Tool de plugin deverá cumprir:

- ToolSpec validation;
- Policy;
- execution mode;
- ToolResult;
- audit.

---

# 68. Integration Tools

Integrations externas também registrarão capabilities através do mesmo Tool Runtime quando representarem ações invocáveis.

Exemplo:

```text
github.create_issue
calendar.create_event
```

---

# 69. Built-in Tools

Built-in não significa trusted beyond policy.

Uma Tool core ainda deverá passar pelo PolicyEngine.

---

# 70. Tool Registry and Startup

No startup, Core deverá registrar Tools disponíveis e validar:

- unique names;
- schemas;
- handlers;
- supported execution modes;
- required metadata.

Erro crítico em Tool essencial poderá afetar readiness.

Erro em plugin opcional deverá preferencialmente isolar apenas o plugin.

---

# 71. Dynamic Registration

Plugins/integrations poderão registrar Tools dinamicamente.

Registry deverá emitir eventos apropriados quando Tool availability mudar.

---

# 72. Tool Removal During Task

Se Tool ficar indisponível durante uma Task:

- nova execução deve falhar de forma explícita;
- Task/Agent poderá replanejar;
- runtime não deverá executar handler stale.

---

# 73. Tool Contract Tests

Toda Tool built-in deverá possuir contract tests.

Testes deverão cobrir:

- schema validation;
- resource resolution;
- Policy metadata;
- success;
- failure;
- timeout;
- cancellation;
- side effects relevantes.

---

# 74. Fake Tool

Task/Agent tests deverão poder registrar Tools determinísticas fake.

Isso evita depender de filesystem, shell ou network reais em todos os testes.

---

# 75. Alternatives Considered

## Alternative A — Direct Python functions exposed to LLM

### Advantages

- implementação rápida;
- pouco boilerplate.

### Rejected because

- sem schema consistente;
- Policy difícil;
- errors inconsistentes;
- plugins frágeis;
- audit ruim;
- coupling com provider.

---

## Alternative B — One universal command tool

Exemplo:

```text
execute(command)
```

para tudo.

### Advantages

- superfície pequena;
- extrema flexibilidade.

### Rejected because

- Policy quase impossível de granular;
- baixa auditabilidade;
- portability ruim;
- risco elevado;
- força shell onde capability específica seria melhor.

Shell continuará existindo, mas como capability privilegiada, não como substituto de todas as Tools.

---

## Alternative C — Tool decides its own safety

### Rejected because

quebra o ADR-0006 e cria authorization distribuída.

---

## Alternative D — Different Tool systems for Core, Plugins and Agents

### Rejected because

criaria múltiplos contratos, múltiplos caminhos de Policy e inconsistência.

---

# 76. Consequences

## Positive

- contrato uniforme;
- ToolCalls independentes de provider;
- Policy granular;
- Agents recebem subsets claros;
- plugins usam mesma infraestrutura;
- audit melhora;
- testing fica previsível;
- retries/recovery podem usar metadata;
- capability map torna-se explícito.

## Negative

- ToolSpec adiciona disciplina/boilerplate;
- resource semantics podem ser complexas;
- side effects precisam modelagem;
- handlers precisam retornar resultados estruturados;
- execução dinâmica exige registry robusto.

Esses custos são considerados essenciais.

---

# 77. Architectural Invariants

### INV-001

Toda Tool possui ToolSpec válido.

### INV-002

Provider não chama Handler diretamente.

### INV-003

ToolCall é normalizado antes da execução.

### INV-004

ToolCall protegida passa pelo PolicyEngine.

### INV-005

Handler não concede permission.

### INV-006

Tool Registry é authoritative sobre Tools disponíveis.

### INV-007

Collision nunca é resolvida por override silencioso.

### INV-008

ToolResult usa contrato normalizado.

### INV-009

Retry respeita idempotency/side effects.

### INV-010

Agent recebe Tool subset explícito.

### INV-011

Plugin Tools não possuem bypass de Policy.

### INV-012

Shell não substitui Tools específicas por conveniência arquitetural.

### INV-013

Resource scope é avaliado sobre input canonicalizado quando aplicável.

### INV-014

Tool execution não amplia authority.

---

# 78. Deferred Decisions

Serão definidos posteriormente:

- schemas Python concretos;
- JSON Schema generation;
- Tool Registry API;
- ToolSpec versioning;
- exact side-effect taxonomy;
- exact risk metadata;
- exact cancellation enum;
- resource resolver contracts;
- handler dependency injection;
- ToolResult artifact representation;
- built-in Tool catalog;
- shell implementation;
- plugin registration protocol.

---

# 79. Decision Summary

Sofia's Assistant possuirá um `Tool Runtime` formal, provider-independent e integrado ao PolicyEngine.

Toda Tool deverá possuir `ToolSpec` explícito e Handler separado.

Provider ToolCalls serão normalizados antes de chegar ao Registry.

Inputs serão validados e recursos resolvidos antes da autorização.

Após `PolicyDecision` compatível, o Executor executará o Handler conforme timeout, cancellation e execution mode.

Toda execução produzirá `ToolResult` normalizado com resultado, errors, artifacts e side effects relevantes.

Built-ins, integrations e plugins utilizarão o mesmo modelo de Tool, sem caminhos paralelos de execução ou autorização.