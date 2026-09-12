# Sofia's Assistant — Backlog Técnico Slice 04

**Escopo:** SA-B011 → SA-B017 + SA-B030
**Gates-alvo:** I4 — Sofia Pode Agir com Segurança; I5 — Sofia Pode Trabalhar; I10 — Sofia é Rastreável
**Status:** ACTIVE
**Projeto:** Sofia's Assistant
**Baseline de implementação:** `307b1032f0da6fa7c9f7c20263afafcdc389c18d`
**Gate anterior:** I3 — Sofia Pode Falar — FECHADO / VERIFICADO REMOTAMENTE
**Estratégia de execução:** autonomia por Gate, checkpoints retomáveis e carregamento incremental de contexto
**Fonte:** Technical Backlog Map aprovado + ADRs aceitos + Architecture Review Amendment 0001 + Slices 01–03 concluídos

---

# 1. Objetivo

O Slice 04 materializa o primeiro runtime de **execução autorizada e trabalho durável** da Sofia.

Os Slices 01–03 provaram que Sofia consegue:

```text
viver
↓
persistir estado operacional
↓
autenticar clients locais
↓
usar secrets com segurança
↓
rotear AI providers
↓
conversar
↓
construir contexto pertencente ao Core
↓
falar em realtime
```

O Slice 04 deve provar que Sofia agora consegue:

```text
propor uma ação
↓
determinar se existe authority
↓
solicitar confirmação quando necessário
↓
executar através de um contrato delimitado de Tool
↓
produzir resultados/artifacts normalizados
↓
representar trabalho durável
↓
delegar para um AgentRun restrito
↓
executar através de um modo de isolamento apropriado
↓
explicar posteriormente por que a ação aconteceu
```

A regra arquitetural permanece:

> **AI proposes. Runtime authorizes. Executor acts.**
> **A IA propõe. O Runtime autoriza. O Executor executa.**

O Slice só estará concluído quando os Gates I4, I5 e I10 estiverem individualmente fechados e verificados remotamente.

---

# 2. Por que o Slice 04 agrupa estes Epics

O Technical Backlog aprovado separa:

```text
SA-B011 — Policy Engine
SA-B012 — Grants & Delegations
SA-B013 — Tool Runtime
SA-B014 — Artifact Service
SA-B015 — Task Runtime
SA-B016 — Agent Runtime
SA-B017 — Execution Isolation
SA-B030 — Audit & Traceability
```

Eles continuam sendo responsabilidades arquiteturais distintas, porém são executados dentro do mesmo Slice porque, juntos, formam uma única cadeia coerente de execução:

```text
Intent / Provider ToolCall / Runtime request
                ↓
          Proposed Action
                ↓
          Policy Engine
                ↓
   Grant / Confirmation / Delegation
                ↓
           Tool Registry
                ↓
        Execution Decision
          /             \
 Direct Invocation      Task
                         ↓
                    AgentRun?
                         ↓
              Execution Isolation
                         ↓
                    ToolResult
                         ↓
                 Artifact Service
                         ↓
                  Audit Evidence
```

Implementar esses componentes sem provar a cadeia verticalmente criaria abstrações capazes de parecer corretas isoladamente e ainda assim falhar como runtime de produto.

---

# 3. Modelo de execução por Gate

O Slice 04 é planejado como um único Slice arquitetural, mas executado como três Gates independentes e recuperáveis.

```text
Slice 04
│
├── Gate I4 — Sofia Pode Agir com Segurança
│     SA-B011 + SA-B012 + SA-B013 + SA-B014
│
├── Gate I5 — Sofia Pode Trabalhar
│     SA-B015 + SA-B016 + SA-B017
│
└── Gate I10 — Sofia é Rastreável
      SA-B030
```

A unidade de interação com o agente de implementação é o **Gate**, não cada Epic e nem cada subpass interno.

A decomposição interna pertence ao agente de implementação.

O fluxo esperado é:

```text
objetivo do Gate
↓
reference harvest
↓
implementação consciente da arquitetura
↓
testes determinísticos
↓
autorrevisão
↓
regressão completa
↓
commit(s) coesos
↓
push
↓
CI remoto
↓
fechamento do Gate
```

Não é necessário criar um ciclo de revisão para `SA-B011.1`, `SA-B011.2`, `SA-B011.2a` etc., salvo se surgir um blocker real.

---

# 4. Regra de retomada e eficiência de tokens

Um Gate pode ser maior que uma única janela de uso do modelo. Portanto, o progresso precisa sobreviver à interrupção sem exigir releitura arquitetural completa.

## 4.1 Regra de checkpoint do Gate

O agente de implementação pode criar commits locais coesos durante um Gate sempre que isso reduzir o custo de retomada.

Um checkpoint deve deixar:

- os testes relevantes ao checkpoint verdes;
- nenhum schema intermediário sabidamente quebrado;
- nenhuma reversão arquitetural não documentada;
- um estado suficientemente consistente para continuidade incremental.

Commits parciais de checkpoint são pontos de recuperação de desenvolvimento, não pontos automáticos de fechamento de Gate.

## 4.2 Resume Capsule

Se o agente não conseguir concluir o Gate dentro da janela atual de execução, deverá atualizar o Execution Ledger do Slice 04 com um `Resume Capsule` compacto:

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

REAL BLOCKERS:
- none / blocker exato

NEXT ACTION:
- ...
```

A próxima execução do agente deve começar por:

1. `Resume Capsule`;
2. commits criados no Gate ativo;
3. diff/worktree atual;
4. arquivos diretamente envolvidos no trabalho restante;
5. somente as seções de ADR necessárias ao problema restante.

O agente **não deve** reler todo PRD/ADR/Slice salvo se o `Resume Capsule` indicar conflito arquitetural não resolvido.

---

# 5. Política de Reference Harvest

Antes de materializar um subsistema importante dentro de um Gate, o agente de implementação deve fazer um reference harvest conciso.

Referências prioritárias:

```text
Mark LI
Brahma AI
codebase atual do Sofia's Assistant
Sofias Memory, quando houver padrão de infraestrutura reutilizável
documentação oficial de frameworks/providers quando APIs externas estiverem envolvidas
```

Para cada capability relevante:

1. identificar como a referência resolve o problema;
2. extrair padrões arquiteturais/de implementação reutilizáveis;
3. comparar com os ADRs aprovados da Sofia;
4. adaptar padrões compatíveis;
5. rejeitar padrões que violem o modelo de authority, persistence, locality ou lifecycle da Sofia;
6. não copiar código quando a licença não permitir;
7. não reinventar um mecanismo já resolvido sem motivo específico do projeto.

Os repositórios de referência são aceleradores, não autoridades arquiteturais.

---

# 6. Fontes arquiteturais

O Slice 04 é governado principalmente pelas decisões aceitas abaixo.

## ADR-0002 — Operational Persistence Architecture

Restrições relevantes:

- SQLite permanece como Operational Store;
- entidades de execução duráveis usam boundaries explícitos de persistence;
- IDs estáveis e timestamps UTC;
- migrations desde o primeiro dia;
- ownership de transaction permanece explícito;
- secrets não são persistidos como estado operacional comum.

## ADR-0004 — AI Provider Abstraction and Capability Routing

Restrições relevantes:

- ToolCalls vindas de providers são propostas normalizadas;
- objetos nativos do provider não se tornam authority do domínio do Core;
- identidade do provider não define identidade da Sofia;
- output estruturado do provider pode propor trabalho, mas não autorizá-lo.

## ADR-0006 — Deterministic Authorization Boundary

Regra congelada:

> **AI proposes. Runtime authorizes. Executor acts.**

Semânticas obrigatórias:

```text
PolicyRequest
PolicyDecision
ALLOW
DENY
REQUIRE_CONFIRMATION
REQUIRE_ELEVATION
```

A avaliação de Policy é determinística, sem side effects e fail-closed.

Nenhuma Tool, Agent, Plugin, provider ou UI pode conceder autoridade a si própria.

## ADR-0007 — Grants, Delegations and Authority Narrowing

Separações congeladas:

```text
Objective ≠ Authority
PermissionGrant ≠ Delegation
```

Comportamento obrigatório de authority:

```text
Execution Authority
    ⊆ Originating Authority Context
    ⊆ Root Effective Authority
```

Quando existe uma Delegation, ela restringe ainda mais a authority.

A semântica temporal mínima de Grant para o MVP deve suportar:

```text
ONE_SHOT
SESSION
UNTIL_REVOKED
```

Revogação é persistente e authority histórica não é reescrita silenciosamente.

## ADR-0008 — Tool Contract, Registry and Execution Boundary

Cadeia de execução congelada:

```text
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

O Tool Registry é autoritativo para as Tools disponíveis.

Uma Tool descreve capability; ela não possui authority.

O input da Tool é validado antes de authorization/execution.

Resource resolution acontece antes da avaliação de Policy.

ToolResult é normalizado e pode referenciar artifacts e side effects.

## Architecture Review Amendment 0001

Este Amendment possui precedência onde modifica wording mais antigo dos ADRs.

Especialmente importante:

### Task não é wrapper universal

```text
Execution Decision
├── Direct Invocation → ToolCall
└── Task
```

Trabalho imediato e delimitado não deve criar uma Task artificial apenas para uniformidade.

### Authority não exige Delegation

Delegation é opcional.

Tasks e AgentRuns podem derivar authority diretamente do contexto de authority de origem/root, preservando narrowing.

### Artifact Service

Arquivos/blobs produzidos pelo runtime devem passar por um Artifact Service explícito e referências estáveis, em vez de serem embutidos indiscriminadamente no ToolResult.

### Secret Service

SecretStore/SecretService permanece Core-wide e secrets só podem ser injetados na execução quando explicitamente necessários.

## ADR-0009 — Task, AgentRun and Root Orchestration Model

Regras relevantes:

- Task representa trabalho durável, não wrapper universal de execução;
- AgentRun é uma estratégia de execução, não a própria Task;
- usar o mecanismo de execução menos complexo capaz de resolver corretamente o trabalho;
- somente Sofia/root cria AgentRuns;
- Agents recebem contexto reduzido, authority reduzida e subconjuntos explícitos de Tools;
- Agent não pode criar outro Agent diretamente;
- resultado do Agent retorna para root.

## ADR-0010 — Task Lifecycle, Cancellation and Recovery

Regras relevantes ao Gate I5:

```text
Waiting != Failure
Cancellation is a request
Retry is not always safe
RUNNING is not durable truth across restart
```

Estados baseline de Task incluem:

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

Recovery completo de crash/restart não é fechado no Slice 04; permanece como SA-B033 / Gate I12.

Entretanto, o Task Runtime criado aqui não pode inviabilizar recovery futuro.

## ADR-0013 — Execution Isolation and Sandbox Model

Modos de execução congelados:

```text
IN_PROCESS
SUBPROCESS
SANDBOX
```

Regras importantes:

```text
SUBPROCESS ≠ SECURITY SANDBOX
workspace ≠ authority
generated code = untrusted by default
```

O Gate I5 do MVP exige execução SUBPROCESS funcional.

SANDBOX pode inicialmente existir como contrato + backend fail-closed se o backend definitivo ainda não estiver escolhido.

## ADR-0015 — Audit and Execution Traceability

Regra congelada:

> **Every consequential action should be explainable from persisted evidence.**
> **Toda ação relevante deve ser explicável a partir de evidência persistida.**

Audit não é logging, metrics, memory ou chain-of-thought.

A correlação obrigatória inclui, quando aplicável:

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
```

Audit deve suportar tanto Direct Invocation quanto execução baseada em Task.

---

# 7. Invariantes do Slice

As invariantes abaixo se aplicam a todos os Gates.

## 7.1 Authority

```text
LLM proposal != authorization
user objective != unrestricted authority
workspace != permission
ToolSpec metadata != authority
Agent request != authority expansion
```

## 7.2 Least privilege

Execução derivada não recebe authority mais ampla que sua origem.

Nenhuma ampliação implícita de privilégios é permitida.

## 7.3 Fail closed

Capability desconhecida, resource semantics desconhecidas, Grant malformado, contexto de Policy ausente ou execution mode não suportado não podem silenciosamente virar `ALLOW`.

## 7.4 Identidades estáveis

PolicyDecision, Grant, Delegation, ToolCall, Task, AgentRun, Artifact e Audit records usam IDs estáveis pertencentes ao Core quando durability/correlation exigir.

## 7.5 Sem authority oculta do provider

IDs do provider e objetos nativos de ToolCall/session permanecem detalhes do adapter salvo quando explicitamente normalizados.

## 7.6 Secrets

Valores de secret nunca entram em persistence comum, ToolResult, AuditEntry ou texto de erro visível ao provider.

## 7.7 Direct Invocation continua first-class

Uma execução simples de Tool não vira Task salvo quando semântica de trabalho durável exigir.

## 7.8 Sem framework genérico prematuro

Não criar workflow engine universal, marketplace de plugins, DAG runtime genérico, policy DSL completa, fila distribuída ou plataforma de sandbox apenas porque Epics futuros talvez precisem deles.

Materializar somente contratos e comportamento necessários aos Gates atuais e seams já aprovadas nos ADRs.

---

# 8. Gate I4 — Sofia Pode Agir com Segurança

**Escopo:** SA-B011, SA-B012, SA-B013, SA-B014
**Unidade de execução:** uma execução de Gate
**Status no início do Slice:** NÃO INICIADO

## 8.1 Objetivo do Gate

Provar que Sofia consegue executar uma Tool delimitada somente através de authority explícita do runtime.

Um caminho vertical de sucesso deve ser semelhante a:

```text
Authenticated request / normalized ToolCall
↓
Tool resolution
↓
argument validation
↓
resource resolution
↓
PolicyRequest
↓
PolicyDecision
↓
optional ConfirmationRequest / Grant
↓
authorized execution
↓
ToolResult
↓
ArtifactRef when applicable
```

## 8.2 SA-B011 — Policy Engine

Materializar no mínimo:

- `PolicyRequest`;
- `PolicyDecision`;
- `PolicyEngine` determinístico;
- subjects normalizados;
- capability;
- operation;
- resource/resource scope;
- resumo dos arguments necessários à decisão;
- Grants aplicáveis;
- Delegation/authority context opcional;
- policy version;
- constraints;
- motivo seguro da decisão;
- `ALLOW`;
- `DENY`;
- `REQUIRE_CONFIRMATION`;
- `REQUIRE_ELEVATION`.

A avaliação de Policy deve ser livre de side effects.

As primeiras regras de Policy do MVP podem ser pequenas e explícitas. Uma linguagem sofisticada de Policy não é obrigatória.

O design deve permitir que regras futuras sejam aditivas, em vez de exigir um segundo sistema de authorization.

## 8.3 SA-B012 — Grants & Delegations

Materializar estado durável de authority para o MVP.

### PermissionGrant mínimo

Deve representar:

- ID estável;
- subject;
- capability;
- resource scope;
- constraints;
- temporal scope;
- issue time;
- issuing context;
- expiration quando aplicável;
- revocation;
- remaining use/consumption quando aplicável.

Modos temporais obrigatórios:

```text
ONE_SHOT
SESSION
UNTIL_REVOKED
```

`SESSION` deve estar vinculado a um conceito explícito de Sofia/client/runtime session, e não a um booleano global ambíguo do processo.

`ONE_SHOT` deve ser consumível exatamente uma vez para a ação/scope aprovada.

### Confirmation

Uma decisão `REQUIRE_CONFIRMATION` deve produzir um request explícito de confirmação vinculado a:

- ação proposta;
- capability;
- resource;
- ToolCall ou execution request;
- scope que será concedido;
- correlation identity.

Uma aprovação do usuário pode criar:

- authority one-shot por padrão;
- authority de session somente quando explicitamente solicitada;
- authority persistente/until-revoked somente quando explicitamente solicitada.

Um simples “sim” nunca deve ampliar o scope além do request apresentado.

### Delegation

Materializar o contrato durável mínimo de Delegation necessário para Tasks/Agents posteriores:

- objective;
- resource scope;
- authority scope;
- constraints;
- lifecycle/status;
- expiration/revocation quando aplicável.

Não forçar existência de Delegation para toda Task ou AgentRun.

## 8.4 SA-B013 — Tool Runtime

Materializar:

### ToolSpec

Metadata mínima útil:

- nome estável;
- version;
- description;
- contrato de input tipado/validado;
- contrato opcional de output;
- capability necessária;
- resource semantics/resolver;
- classificação de side effects;
- metadata de idempotency/retry suficiente para Task/recovery futuro;
- execution mode padrão;
- semântica de timeout/cancellation;
- estado enabled/disabled.

### Tool Registry

Deve:

- ser authoritative para Tools disponíveis;
- rejeitar collisions;
- vincular ToolSpec a handler/implementação de execução;
- suportar enable/disable;
- listar ToolSpecs aplicáveis;
- expor specs normalizadas ao provider sem expor handlers;
- resolver execução por identidade estável de Tool.

### ToolCall

Deve possuir ID estável pertencente ao Core e arguments normalizados.

Uma proposta de ToolCall do provider não executa automaticamente.

### Tool Runtime

Deve realizar:

```text
resolve ToolSpec
↓
validate arguments
↓
resolve protected resources
↓
build PolicyRequest
↓
evaluate Policy
↓
execute only after ALLOW
↓
normalize ToolResult
```

`DENY`, `REQUIRE_CONFIRMATION` e `REQUIRE_ELEVATION` não devem ser tratados como errors do Tool handler.

### Direct Invocation

O Gate I4 deve provar Direct Invocation sem wrapper de Task.

Ainda deve preservar:

- ToolCall ID estável;
- PolicyDecision;
- semântica de timeout/cancellation quando aplicável;
- ToolResult;
- seam/correlation de Audit;
- suporte a ArtifactRef.

## 8.5 SA-B014 — Artifact Service

Materializar um boundary local explícito de Artifact.

Contrato mínimo:

- `ArtifactRef`;
- identidade estável do artifact;
- metadata de tipo/media;
- armazenamento local seguro controlado pelo Core;
- baseline de temporary/persistent;
- metadata de criação;
- metadata de tamanho;
- retrieval seguro através do service/boundary;
- baseline controlado de deletion/retention;
- integração com ToolResult.

ToolResult deve referenciar artifacts em vez de embutir payloads arbitrariamente grandes.

Artifact storage não deve transformar paths externos arbitrários em artifacts confiáveis do Core sem validação/import semantics.

## 8.6 Client boundary do Gate I4

Uma UI desktop completa de confirmação ainda não é necessária.

O authenticated local client boundary deve expor contrato suficiente para provar:

- request direto de Tool;
- resposta/evento de confirmation required;
- submissão de approval/denial;
- execução autorizada resultante;
- retrieval seguro de ToolResult/ArtifactRef quando aplicável.

A UI permanece preocupação posterior. Authorization semantics ficam no Core.

## 8.7 Tools determinísticas de teste do Gate I4

Filesystem/Shell/Web de produção não serão introduzidos apenas para provar I4.

A evidência principal do Gate deve usar Tools fake/de teste registradas e determinísticas capazes de provar:

- execução segura de leitura/sem side effect;
- execução com side effect que exige confirmação;
- denial;
- argument validation failure;
- resource scope mismatch;
- consumo de ONE_SHOT Grant;
- comportamento de SESSION Grant;
- comportamento de Tool disabled/unregistered;
- resultado que produz artifact.

Tools de teste não devem virar capabilities de produção expostas ao usuário por acidente, salvo justificativa deliberada.

## 8.8 Critérios de aceite do Gate I4

O Gate I4 só fecha quando tudo abaixo estiver provado:

```text
[ ] Tool pode ser registrada
[ ] collision de Tool falha explicitamente
[ ] Tool disabled/unregistered não executa
[ ] arguments de ToolCall são validados
[ ] resource é resolvido antes da execução
[ ] toda execução protegida possui PolicyDecision
[ ] DENY impede execução do handler
[ ] REQUIRE_CONFIRMATION impede execução até approval
[ ] confirmation fica vinculada à ação/scope exatos
[ ] authority ONE_SHOT é consumida corretamente
[ ] authority SESSION expira com sua session vinculada
[ ] UNTIL_REVOKED pode ser revogada persistentemente
[ ] Delegation não consegue ampliar authority
[ ] Direct Invocation funciona sem criar Task
[ ] handler não consegue se autoautorizar
[ ] ArtifactRef funciona através do Artifact Service
[ ] secrets/errors internos brutos não vazam
[ ] vertical do authenticated boundary está provado
[ ] regressão completa está verde
[ ] CI remoto está verde
```

Veredito esperado:

```text
GATE I4: FECHADO — VERIFICADO REMOTAMENTE
```

---

# 9. Gate I5 — Sofia Pode Trabalhar

**Escopo:** SA-B015, SA-B016, SA-B017
**Depende de:** Gate I4 fechado / verificado remotamente
**Unidade de execução:** uma execução de Gate
**Status no início do Slice:** BLOQUEADO POR I4

## 9.1 Objetivo do Gate

Provar que Sofia consegue representar trabalho duravelmente, escolher uma estratégia apropriada de execução, criar um AgentRun restrito através da root orchestration e executar trabalho em subprocess sem violar authority.

Modelo vertical:

```text
Objective
↓
Execution Decision
├── Direct Invocation (já provado pelo I4)
└── Task
      ↓
  Task Runtime
      ↓
  Strategy
  ├── Tool / deterministic workflow
  └── AgentRun
          ↓
    restricted context
    restricted tools
    restricted authority
          ↓
    Tool Runtime / Execution Dispatcher
          ↓
      ToolResult
          ↓
      TaskResult
```

## 9.2 SA-B015 — Task Runtime

Materializar semântica durável de Task.

Conceitos/campos duráveis mínimos:

- Task identity;
- objective;
- origin;
- status;
- authority context;
- relação opcional com Conversation/Delegation;
- execution strategy;
- attempts;
- progress/result;
- timestamps;
- cancellation state;
- failure/result metadata.

A semântica baseline de estado deve preservar ADR-0010:

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

Nem todo estado precisa ser exercitado por uma feature de produção neste Gate, mas o modelo não pode colapsar waiting em failure.

### Baseline de queue/claim

Task Runtime precisa de um mecanismo explícito de ownership/claim suficiente para uma instalação single-user.

Não deve introduzir complexidade de distributed queue.

### Attempts

Attempts devem ser distinguíveis.

Retry deve ser explícito e restrito; não deve haver blind retry de trabalho não idempotente.

### Cancellation

Cancellation é cooperativa e stateful:

```text
RUNNING
↓
CANCELLING
↓
CANCELLED
```

quando a execução efetivamente parar com segurança.

Side effects já concluídos não são magicamente revertidos.

### Waiting for confirmation

Uma Task cujo ToolCall exige confirmação entra em `WAITING_CONFIRMATION`, e não `FAILED`.

Depois que authority for concedida, a mesma Task pode retomar.

## 9.3 SA-B016 — Agent Runtime

Materializar:

### AgentDefinition

Mínimo:

- identidade/version estável;
- name/description;
- capability requirements;
- Tool subset permitido;
- context policy;
- provider requirements;
- runtime limits.

### Agent Registry

Deve:

- registrar AgentDefinitions;
- rejeitar collisions;
- enable/disable;
- resolver AgentDefinition;
- expor apenas metadata normalizada.

### AgentRun

Durável ou operacionalmente persistente conforme exigido pela arquitetura aprovada, correlacionado à Task.

Deve conter:

- Task ID;
- AgentDefinition/version;
- objective;
- delegated context projection;
- authority scope;
- Tool subset explícito;
- workspace quando aplicável;
- provider requirements;
- status/result;
- timing/correlation metadata.

### Criação somente pela root

Somente Sofia/root runtime cria AgentRuns.

Um Agent não pode instanciar diretamente outro Agent.

Se um Agent precisar de outra especialização, pode produzir um request estruturado que retorna para root.

### Context narrowing

Contexto do Agent é uma projeção, não cópia completa do contexto da root ou da Conversation.

### Tool narrowing

Um Agent só pode chamar o subset atribuído ao seu AgentRun, mesmo que existam mais Tools globalmente.

### Authority narrowing

Invariante obrigatória:

```text
AgentRun Authority
    ⊆ Task/Originating Authority
    ⊆ Root Effective Authority
```

Quando existe Delegation:

```text
AgentRun Authority
    ⊆ Task Authority
    ⊆ Delegation Authority
    ⊆ Root Effective Authority
```

## 9.4 Mecanismo de execução do Agent

A correctness principal deve usar comportamento determinístico de Fake/Test Agent quando possível.

Um primeiro agent loop real conduzido por provider pode ser implementado se provar materialmente o runtime sem expandir o escopo, mas não é necessário transformar I5 em um Research/Development Agent completo. Essa validação pertence a SA-B029 / Gate I9.

O Gate precisa provar a **arquitetura de Agent**, não uma especialização de Agent production-grade.

## 9.5 SA-B017 — Execution Isolation

Materializar o execution dispatcher exigido pela arquitetura aprovada.

### IN_PROCESS

Funcional para handlers trusted e delimitados.

### SUBPROCESS

Deve ser funcional para o MVP Gate.

Baseline obrigatório:

- executable + arguments estruturados quando possível;
- cwd controlado;
- environment filtering;
- timeout;
- cancellation;
- captura de stdout/stderr com limites;
- exit status;
- process ownership;
- nenhum secret inheritance implícito.

SUBPROCESS nunca deve ser descrito como security sandbox.

### SANDBOX

Deve existir contrato tipado.

Se não houver backend aprovado, `SANDBOX` deve falhar fechado, em vez de fazer downgrade silencioso para SUBPROCESS/IN_PROCESS.

## 9.6 Fixture de processo do Gate I5

Shell Capability B025 ainda não será implementada.

O Gate I5 pode provar execução SUBPROCESS usando executable/helper controlado pertencente à test suite ou fixtures do project runtime.

Não expor shell irrestrito ao usuário apenas para fechar I5.

## 9.7 Critérios de aceite do Gate I5

O Gate I5 só fecha quando tudo abaixo estiver provado:

```text
[ ] Task é durável
[ ] Direct Invocation continua existindo e não é encapsulada em Task
[ ] state machine de Task preserva Waiting != Failure
[ ] Task pode entrar/sair de WAITING_CONFIRMATION
[ ] attempts são distintos
[ ] cancellation propaga para trabalho ativo
[ ] não existe blind retry de trabalho não idempotente
[ ] Task escolhe a estratégia válida menos complexa
[ ] AgentDefinition é registrada/resolvida
[ ] somente root pode criar AgentRun
[ ] contexto de AgentRun é restrito
[ ] Tool subset do AgentRun é aplicado
[ ] authority do AgentRun é restrita
[ ] Agent não pode spawn Agent diretamente
[ ] resultado do Agent retorna para root/Task
[ ] execução IN_PROCESS funciona
[ ] execução SUBPROCESS funciona
[ ] timeout/cancellation do SUBPROCESS funciona
[ ] environment do subprocess é filtrado
[ ] stdout/stderr são bounded
[ ] SANDBOX é explícito e fail-closed se backend estiver indisponível
[ ] detalhes de provider/Tool não bypassam Policy
[ ] regressão completa está verde
[ ] CI remoto está verde
```

Veredito esperado:

```text
GATE I5: FECHADO — VERIFICADO REMOTAMENTE
```

---

# 10. Gate I10 — Sofia é Rastreável

**Escopo:** SA-B030
**Depende de:** Gates I4 e I5 fechados / verificados remotamente
**Unidade de execução:** uma execução de Gate
**Status no início do Slice:** BLOQUEADO POR I4/I5

## 10.1 Objetivo do Gate

Provar que developer/usuário consegue reconstruir por que uma ação relevante aconteceu sem depender de application logs ou hidden model reasoning.

O runtime precisa responder, a partir de evidência estruturada persistida:

```text
O que aconteceu?
Quem/o que solicitou?
Por que foi permitido ou negado?
Qual authority foi usada?
Qual Tool executou?
Foi Direct Invocation ou Task-based?
Houve Agent envolvido?
Qual resultado/efeito foi observado?
```

## 10.2 AuditEntry

Materializar Audit entries persistidos e append-oriented.

Dimensões normalizadas mínimas:

- Audit ID estável;
- timestamp;
- event type;
- actor;
- subject;
- action;
- resource/resource summary;
- outcome;
- correlation ID;
- causation ID quando significativo;
- authority context summary;
- execution context summary;
- metadata segura.

## 10.3 Eventos obrigatoriamente auditados

No mínimo, capturar evidência significativa para:

### Authority

- Grant criado;
- Grant consumido;
- Grant revogado;
- Delegation criada/revogada quando usada;
- confirmation requested;
- confirmation approved/denied;
- PolicyDecision produzida.

### Tool execution

- ToolCall requested;
- ToolCall authorized/denied/waiting;
- execution started;
- ToolResult completed/failed/cancelled/timed out;
- artifacts;
- side effects conhecidos/parciais.

### Task

- Task criada;
- state transitions importantes;
- attempt iniciado/finalizado;
- waiting;
- cancellation;
- terminal result.

### AgentRun

- AgentRun criado pela root;
- definition/version;
- Task;
- Tool subset;
- authority scope;
- provider/model metadata quando seguro;
- terminal result.

### Isolation

- execution mode;
- metadata de comando subprocess em forma redacted;
- cwd/workspace;
- outcome de exit/timeout/cancellation.

## 10.4 Privacy e redaction

Audit nunca deve persistir:

- valores de secrets;
- bearer tokens;
- hidden state completo do provider;
- chain-of-thought bruto;
- prompts irrestritos por padrão;
- arguments sensíveis completos de Tool quando references/redaction forem suficientes.

Secret references podem ser persistidas.

Hashes/references/summaries seguros podem ser usados quando preservarem traceability sem expor conteúdo sensível.

## 10.5 Trace de Direct Invocation

Deve suportar trace completo sem Task ID:

```text
Authenticated request / Conversation
↓
ToolCall
↓
PolicyDecision
↓
Confirmation/Grant if applicable
↓
Execution
↓
ToolResult
↓
Artifact / side effects
```

## 10.6 Trace de Task/Agent

Deve suportar:

```text
origin
↓
Task
↓
AgentRun or Tool
↓
ToolCall
↓
PolicyDecision
↓
Execution
↓
ToolResult
↓
Task/Agent result
```

## 10.7 Audit Query Service

Queryability mínima deve suportar filtros úteis como:

- time range;
- correlation ID;
- Task;
- AgentRun;
- ToolCall/Tool;
- PolicyDecision;
- Grant;
- resource;
- outcome/origin.

O authenticated local boundary deve expor capacidade de leitura suficiente para responder à pergunta do Gate:

> **Por que Sofia fez isso?**

Nenhuma UI sofisticada de analytics é necessária.

## 10.8 Critérios de aceite do Gate I10

O Gate I10 só fecha quando tudo abaixo estiver provado:

```text
[ ] Audit é persistido separadamente de logs
[ ] modelo é append-oriented por convenção da aplicação
[ ] Direct Invocation produz trace reconstruível
[ ] execução Task-based produz trace reconstruível
[ ] execução AgentRun produz trace reconstruível
[ ] PolicyDecision é correlacionada
[ ] authority de Grant/confirmation é correlacionada
[ ] ToolCall/ToolResult são correlacionados
[ ] Artifact references são correlacionadas
[ ] transitions significativas de Task são registradas
[ ] cancellation/retry attempts são distinguíveis
[ ] dados sensíveis são redacted
[ ] secrets brutos nunca aparecem em Audit
[ ] chain-of-thought privado não é requisito de Audit
[ ] Audit Query Service consegue responder "por que Sofia fez isso?"
[ ] authenticated local boundary consegue consultar a evidência
[ ] regressão completa está verde
[ ] CI remoto está verde
```

Veredito esperado:

```text
GATE I10: FECHADO — VERIFICADO REMOTAMENTE
```

---

# 11. Cenários verticais do Slice 04

Os cenários abaixo formam a evidência combinada do Slice.

## Cenário A — Ação direta segura

```text
authenticated client
↓
registered Tool
↓
valid arguments
↓
Policy ALLOW
↓
IN_PROCESS execution
↓
ToolResult
↓
Audit trace
```

Nenhuma Task é criada.

## Cenário B — Ação vinculada à confirmação

```text
ToolCall
↓
Policy REQUIRE_CONFIRMATION
↓
execution blocked
↓
ConfirmationRequest
↓
usuário aprova scope exato
↓
ONE_SHOT Grant
↓
Policy ALLOW
↓
execution
↓
Grant consumido
↓
Audit evidence
```

## Cenário C — Ação negada

```text
ToolCall fora do scope permitido
↓
Policy DENY
↓
handler nunca executa
↓
denial seguro
↓
Audit evidence
```

## Cenário D — Ação que produz Artifact

```text
authorized Tool
↓
execution
↓
Artifact Service
↓
ArtifactRef
↓
ToolResult
↓
safe retrieval
```

## Cenário E — Task durável aguardando permissão

```text
Task RUNNING
↓
ToolCall requires confirmation
↓
Task WAITING_CONFIRMATION
↓
usuário concede authority
↓
Task retoma
↓
Task SUCCEEDED
```

Waiting não é failure.

## Cenário F — AgentRun restrito

```text
Task
↓
Sofia/root cria AgentRun
↓
contexto restrito
↓
authority restrita
↓
Tool subset explícito
↓
Agent solicita Tool
↓
Policy + Tool Runtime
↓
resultado retorna à root
↓
Task result
```

Agent não pode criar outro Agent diretamente.

## Cenário G — Subprocess controlado

```text
authorized execution
↓
SUBPROCESS
↓
filtered environment
↓
bounded stdout/stderr
↓
timeout/cancellation support
↓
normalized result
```

## Cenário H — Explicar a ação

Dada uma Direct Invocation ou ação Task/Agent concluída, Audit Query consegue reconstruir:

```text
origin
authority
PolicyDecision
execution
result/effect
```

sem logs ou hidden chain-of-thought.

---

# 12. Plano de Persistence

O Slice 04 pode adicionar migrations para entidades duráveis como:

```text
permission_grants
delegations
confirmation_requests
policy_decisions
tool_calls
artifacts
tasks
task_attempts
agent_runs
audit_entries
```

O schema exato é decisão de implementação e deve evitar proliferação prematura de tabelas.

Regras:

- UUIDs estáveis;
- timestamps UTC;
- foreign keys/correlation quando útil;
- nenhum provider-native authority ID;
- nenhum plaintext secret;
- state transitions validadas em domain/service layer;
- boundaries de UoW/transaction permanecem explícitos;
- não manter transaction SQLite aberta durante execution externa/provider/process.

Em especial, preferir:

```text
persist intent/state
COMMIT
external execution
new transaction
persist result
```

em vez de transactions longas atravessando side effects.

---

# 13. Ownership entre Core e Boundary

SofiaCore pode compor:

- PolicyEngine;
- Grant/Delegation services;
- Tool Registry/Runtime;
- Artifact Service;
- Task Runtime;
- Agent Runtime;
- Execution Dispatcher;
- Audit Service.

O Core permanece transport-agnostic.

Adapters HTTP/WebSocket/local boundary podem traduzir requests autenticados e transmitir responses/events normalizados, mas não podem:

- consultar diretamente tabelas de domínio do SQLite;
- autorizar ações;
- bypassar PolicyEngine;
- executar handlers diretamente;
- criar Grants por convenção da UI;
- instanciar AgentRun fora da root orchestration.

---

# 14. Superfície inicial da API/local boundary

Os nomes exatos das rotas são decisão de implementação, mas a evidência do Gate provavelmente exige operações equivalentes a:

```text
Tools
- listar Tools aplicáveis
- invocar Tool diretamente

Confirmations
- listar/ler confirmation pendente
- aprovar/negar com scope/lifetime explícitos

Grants
- listar Grants efetivos/relevantes
- revogar Grant

Tasks
- criar/ler/cancelar Task
- observar status/result

Audit
- consultar execution trace/evidence

Artifacts
- resolver/ler ArtifactRef autorizado
```

Não criar APIs administrativas amplas salvo quando exigidas pelo Gate.

---

# 15. Estratégia de testes

A correctness principal do CI deve continuar determinística e offline.

## Unit tests

Usar para:

- scope matching;
- semântica temporal de Grant;
- authority narrowing;
- decisões de regras de Policy;
- validação de Tool arguments/resources;
- state transitions;
- Audit redaction.

## Integration tests

Usar para:

- persistence;
- Tool Runtime + Policy;
- confirmation → Grant → retry/continue;
- Task + waiting;
- authority/tool subset de AgentRun;
- subprocess execution/cancellation;
- Artifact Service;
- Audit trace.

## Gate vertical tests

Cada Gate deve possuir pelo menos uma integração vertical provando sua pergunta de produto.

## Serviços externos reais

Não são necessários para provar o Slice 04, salvo se a implementação optar por um agent loop real conduzido por provider.

O caminho determinístico fake/provider continua sendo a evidência principal.

## Testes de concorrência/race

Usar sincronização explícita:

```text
asyncio.Event
barriers
causal progress markers
```

Evitar sleeps baseados em timing como prova de correctness.

---

# 16. Quality Gates

Ao final de cada execução de Gate:

```text
targeted tests
Gate vertical tests
full pytest
ruff check
ruff format --check
mypy
git diff --check
```

Failures são corrigidos autonomamente salvo quando revelarem blocker arquitetural real.

---

# 17. Checkpoint e verificação remota por Gate

Cada Gate recebe seu próprio checkpoint remoto.

## Gate I4

```text
implementation
↓
full regression
↓
commit/push
↓
GitHub CI
↓
I4 FECHADO — VERIFICADO REMOTAMENTE
```

Somente então iniciar I5.

## Gate I5

Mesmo processo.

Somente então iniciar I10.

## Gate I10

Mesmo processo.

Depois da verificação remota do I10, o Slice 04 pode ser formalmente fechado.

Isso protege progresso sem retornar ao ciclo de micro-commit review.

---

# 18. Autonomia do agente de implementação

Para cada Gate, o agente está autorizado a:

- inspecionar o repositório;
- ler seções relevantes dos ADRs;
- realizar reference harvest;
- escolher layout de módulos coerente;
- adicionar migrations;
- modificar composition;
- estender authenticated local boundary;
- criar testes;
- refatorar implementação quando necessário;
- corrigir findings encontrados dentro do escopo do Gate;
- criar recovery commits locais;
- atualizar o ledger do Slice 04;
- executar quality gates;
- commit/push quando o Gate estiver completo.

O agente não deve parar por decisões comuns de implementação.

Deve parar antecipadamente somente diante de **blocker real**:

1. conflito entre ADRs aceitos sem precedência clara;
2. risco irreversível de dados/segurança sem semântica aprovada;
3. problema de licença que exija copiar código;
4. credential/serviço externo indisponível e essencial ao Gate;
5. requisito cujas alternativas alterem materialmente a semântica do produto e não possam ser inferidas com segurança.

Bugs normais, testes falhando e findings não bloqueantes são responsabilidade do agente.

---

# 19. Não objetivos / trabalho explicitamente adiado

O Slice 04 **não** inclui:

```text
SA-B018–B020 Memory integration
SA-B021–B023 Events/Scheduler/Notifications
SA-B024 production Filesystem Capability
SA-B025 production Shell Capability
SA-B026 Web Search & Read
SA-B027 Desktop Basics
SA-B028 Screenshot Vision
SA-B029 real Experimental Agent
SA-B031 Desktop Client
SA-B032 Plugin Foundation
SA-B033 full crash/restart recovery hardening
SA-B034 final MVP integration
```

Também ficam adiados, salvo descoberta de blocker de Gate:

- policy DSL production-grade;
- distributed Task queue;
- multi-machine workers;
- marketplace/plugin signing;
- seleção de backend forte de SANDBOX;
- implementação de UAC/elevation;
- UI complexa de artifact retention;
- hash chain tamper-proof de Audit;
- formatos de export de Audit;
- policy sofisticada de cost/quota;
- workflow DAG engine avançado.

A arquitetura deve deixar seams para isso sem implementar prematuramente.

---

# 20. Brief de execução do Gate I4

Quando aprovado, a primeira execução de implementação deve receber esta missão de alto nível:

> **Concluir Gate I4 — Sofia Pode Agir com Segurança.**
>
> Materialize SA-B011–SA-B014 ponta a ponta sob ADR-0006, ADR-0007, ADR-0008 e Architecture Review Amendment 0001. Use autonomia por Gate. Faça reference harvest primeiro. Não peça aprovação de microsteps. Crie checkpoints retomáveis caso o limite de uso se aproxime. Retorne somente quando I4 estiver closure-ready/remote-verified ou quando um blocker real exigir decisão humana.

O prompt de implementação pode referenciar este documento do Slice, em vez de repetir todos os contratos.

---

# 21. Brief de execução do Gate I5

Depois que I4 estiver remote verified:

> **Concluir Gate I5 — Sofia Pode Trabalhar.**
>
> Materialize SA-B015–SA-B017 ponta a ponta sob ADR-0009, ADR-0010, ADR-0013 e o authority/tool runtime já fechado no I4. Prove Task durável, AgentRun restrito e SUBPROCESS funcional. Preserve Direct Invocation e SANDBOX fail-closed. Use checkpoints retomáveis. Retorne somente quando I5 estiver closure-ready/remote-verified ou existir blocker real.

---

# 22. Brief de execução do Gate I10

Depois que I5 estiver remote verified:

> **Concluir Gate I10 — Sofia é Rastreável.**
>
> Materialize SA-B030 sob ADR-0015 através dos caminhos de Direct Invocation, Task e Agent já funcionais. Persista evidência estruturada, redacted e causalmente correlacionada e exponha superfície de query suficiente para responder “Por que Sofia fez isso?”. Retorne somente quando I10 estiver closure-ready/remote-verified ou existir blocker real.

---

# 23. Definition of Done do Slice 04

O Slice 04 só está completo quando:

```text
Gate I4 — FECHADO — VERIFICADO REMOTAMENTE
Gate I5 — FECHADO — VERIFICADO REMOTAMENTE
Gate I10 — FECHADO — VERIFICADO REMOTAMENTE
```

e todas as condições abaixo continuam verdadeiras:

- Gates I1–I3 existentes permanecem verdes;
- Conversation textual permanece funcional;
- realtime voice permanece funcional;
- nenhum provider se torna authority;
- Direct Invocation permanece first-class;
- Tasks são usadas somente quando semântica de trabalho durável exige;
- Agents permanecem subordinados à root;
- authority narrowing é aplicado;
- SUBPROCESS não é rotulado falsamente como sandbox;
- ações relevantes são rastreáveis por evidência persistida;
- nenhum secret ou hidden chain-of-thought é introduzido no Audit;
- test suite completa e quality checks passam;
- estado final do repositório está limpo e pushed.

Veredito esperado do Slice:

```text
SLICE 04 — SAFE EXECUTION & DURABLE WORK
CONCLUÍDO — VERIFICADO REMOTAMENTE
```

---

# 24. Direção pós-Slice

Depois do Slice 04, o caminho acelerado até o MVP continua com:

```text
Slice 05 — Sofia Remembers
    Gate I6

Slice 06 — Computer Capabilities & Real Agent
    Gate I8
    Gate I9

Slice 07 — Proactivity & Product Interface
    Gate I7
    Gate I11

Slice 08 — Recovery & MVP Release
    Gate I12
    Gate I13
```

`SA-B032 — Plugin Foundation` continua opcional para o primeiro release MVP salvo se Gate posterior descobrir dependência real.

---

# 25. Estado inicial do Ledger

```text
Slice 04 status:
    ACTIVE

Current active Gate:
    I5 — Sofia Can Work

Next Gate:
    Gate I5 — Sofia Can Work

Gate I4:
    CLOSED — REMOTE VERIFIED

Gate I5:
    READY / NEXT GATE

Gate I10:
    BLOCKED BY I5

Implementation baseline:
    307b1032f0da6fa7c9f7c20263afafcdc389c18d

Previous Gate:
    I3 — CLOSED — REMOTE VERIFIED

Gate I4 execution checkpoint:
    Feature SHA: 39569ebcf83376105073545a1d7199550402de0a
    Local pytest: 529 collected; 526 passed; 3 skipped; 0 failed; 0 warnings
    Local quality: ruff check PASS; ruff format --check PASS; mypy PASS; diff-check PASS
    Remote CI: run 34706985628 — success
    Remote CI URL: https://github.com/kallbuloso/sofias_assistant/actions/runs/34706985628
    Deferred findings: full Audit remains assigned to Gate I10; no I4 blockers
```
