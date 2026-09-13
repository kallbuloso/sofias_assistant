# Sofia's Assistant — Backlog Técnico Slice 06

**Nome operacional:** Computer Capabilities & Real Agent  
**Escopo:** SA-B024 → SA-B029  
**Gates-alvo:** I8 — Sofia Pode Usar o Computador; I9 — Sofia Pode Delegar  
**Status:** DRAFT — READY FOR APPROVAL  
**Projeto:** Sofia's Assistant  
**Baseline de implementação:** `c611f557fd1d4c9c23b92093c3de438962ca192c`  
**Último Gate executado:** I10 — Sofia é Rastreável — FECHADO / VERIFICADO REMOTAMENTE  
**Slice 05:** deliberadamente adiado até disponibilidade do Sofias Memory v0.7.0  
**Estratégia de execução:** autonomia por Gate, checkpoints retomáveis, reference harvest dirigido e integração vertical  
**Fonte:** Technical Backlog Map + ADRs aceitos + Architecture Review Amendments + Slices 01–04 concluídos

---

# 1. Objetivo

O Slice 06 transforma a infraestrutura construída nos Slices anteriores em **capabilities reais de produto**.

Até o final do Slice 04, Sofia já consegue:

```text
viver
↓
persistir
↓
autenticar clients
↓
usar AI providers
↓
conversar
↓
falar em realtime
↓
avaliar authority
↓
executar Tools
↓
representar Tasks
↓
criar AgentRuns
↓
isolar execução
↓
auditar ações
```

Porém, o Tool Runtime existente ainda não oferece um conjunto significativo de capabilities reais do computador.

O Slice 06 deverá provar:

```text
Sofia
↓
observa uma necessidade
↓
seleciona uma capability real
↓
resolve o recurso concreto
↓
Policy avalia authority
↓
Tool executa através do runtime existente
↓
resultado é normalizado/auditado
↓
Sofia usa múltiplas Tools quando necessário
↓
Sofia/root delega um objetivo a um Agent especializado
↓
Agent opera com contexto + authority + Tools reduzidos
↓
resultado retorna à Sofia/root
```

Os dois resultados de produto do Slice serão:

```text
Gate I8 — Sofia Can Use the Computer

Gate I9 — Sofia Can Delegate
```

---

# 2. Antecipação do Slice 06

A execução original previa:

```text
Slice 05 — Sofia Remembers
    Gate I6

Slice 06 — Computer Capabilities & Real Agent
    Gate I8
    Gate I9
```

A ordem prática será temporariamente:

```text
Slice 04
    ↓
Slice 06
    ↓
Slice 05
```

até que:

```text
Sofias Memory v0.7.0 = READY
```

Isso **não altera**:

- numeração dos Slices;
- numeração dos Epics;
- dependency graph;
- ADRs;
- gates;
- escopo do Slice 05;
- definição de MVP.

É apenas uma escolha de scheduling de implementação.

Nenhum código do Slice 06 poderá criar dependência artificial de SA-B018, SA-B019 ou SA-B020.

---

# 3. Por que o Slice 06 está desbloqueado

As dependências já estão satisfeitas:

```text
SA-B024 Filesystem
    ← SA-B013 Tool Runtime
    ← SA-B017 Execution Isolation

SA-B025 Shell
    ← SA-B013 Tool Runtime
    ← SA-B017 Execution Isolation

SA-B026 Web Search & Read
    ← SA-B013 Tool Runtime
    ← SA-B007 AI Provider Framework

SA-B027 Desktop Basics
    ← SA-B013 Tool Runtime

SA-B028 Screenshot Vision
    ← SA-B007 AI Provider Framework
    ← SA-B014 Artifact Service
    ← SA-B027 Desktop Basics

SA-B029 Experimental Agent
    ← SA-B016 Agent Runtime
    ← SA-B024 and/or SA-B026
```

Portanto:

```text
Sofias Memory unavailable
```

não bloqueia nenhum requisito obrigatório dos Gates I8 ou I9.

---

# 4. Modelo de execução

O Slice será executado em dois Gates.

```text
Slice 06
│
├── Gate I8 — Sofia Pode Usar o Computador
│     ├── SA-B024 Filesystem Capability
│     ├── SA-B025 Shell Capability
│     ├── SA-B026 Web Search & Read
│     ├── SA-B027 Desktop Basics
│     └── SA-B028 Screenshot Vision
│
└── Gate I9 — Sofia Pode Delegar
      └── SA-B029 Development Analysis Agent
```

A unidade de fechamento continua sendo o **Gate**, não cada Epic.

É permitido criar commits/checkpoints intermediários durante I8 porque o Gate é significativamente maior que os anteriores.

Checkpoint sugerido:

```text
I8-A
Filesystem + Shell

I8-B
Web + Desktop + Screenshot Vision

I8
integração vertical + regression + remote CI
```

Esses checkpoints não fecham I8 isoladamente.

---

# 5. Regra de retomada

Caso uma execução precise ser interrompida, atualizar o Execution Ledger com:

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
- none / descrição exata

CURRENT HEAD:
- ...

NEXT ACTION:
- ...
```

A próxima execução deve ler primeiro:

```text
Resume Capsule
↓
commits desde o checkpoint
↓
worktree/diff
↓
arquivos diretamente envolvidos
↓
somente ADRs necessários
```

Não reler indiscriminadamente PRD + todos os ADRs + Slices anteriores.

---

# 6. Organização física recomendada

O runtime genérico deve continuar separado das implementations concretas.

Estrutura conceitual recomendada:

```text
sofias_assistant/
├── execution/
│   ├── runtime.py
│   ├── dispatcher.py
│   ├── models.py
│   ├── registry.py
│   ├── policy.py
│   ├── agents.py
│   └── ...
│
├── capabilities/
│   ├── filesystem/
│   ├── shell/
│   ├── web/
│   ├── desktop/
│   └── vision/
│
└── agents/
    └── development_analysis/
```

O layout exato continua decisão de implementação.

A separação conceitual, porém, é importante:

```text
execution/*
```

deve continuar sendo infraestrutura genérica de execução.

```text
capabilities/*
```

contém capabilities built-in reais.

```text
agents/*
```

contém especializações reais construídas sobre AgentRuntime.

Não colocar handlers concretos de filesystem/web/desktop indiscriminadamente dentro de `execution/runtime.py`.

---

# 7. Fontes arquiteturais

## ADR-0004 — AI Provider Abstraction

Continua obrigatório:

```text
provider implementation != Sofia identity
provider-native object != Core domain object
```

Screenshot Vision deve utilizar um contrato provider-neutral.

Não enviar `OpenAI-specific image object` através do Core.

## ADR-0005 — Conversation, Realtime Voice and Context Ownership

ContextBuilder continua proprietário da projeção final.

Informação derivada de screenshot pode alimentar contexto, porém screenshot ou provider não se torna proprietário do contexto.

## ADR-0006 — Deterministic Authorization Boundary

Regra invariável:

> AI proposes. Runtime authorizes. Executor acts.

Nenhuma capability pode executar porque o LLM “decidiu que é seguro”.

## ADR-0007 — Grants & Delegations

Workspace não concede authority.

Agent tool subset não concede authority.

Tool availability não concede authority.

## ADR-0008 — Tool Contract

Todas as capabilities do Slice devem utilizar:

```text
ToolSpec
Tool Registry
ToolCall
Policy
Execution Boundary
ToolResult
```

Não criar APIs paralelas para executar filesystem, shell ou desktop fora desse caminho.

## ADR-0009 — AgentRun

O primeiro Agent real permanece subordinado à Sofia/root.

Ele não pode:

```text
spawn Agent
expand authority
expand tool subset
copy entire root context
```

## ADR-0013 — Execution Isolation

Continua válido:

```text
SUBPROCESS != security sandbox
```

Shell real utilizará subprocess isolation, mas não deverá ser apresentada como sandbox forte.

## ADR-0015 — Audit

Capabilities reais devem preservar a pergunta:

> Por que Sofia fez isso?

sem registrar secrets, raw private reasoning ou conteúdo sensível indiscriminadamente.

---

# 8. Invariantes do Slice

## 8.1 Tool Runtime continua único

Nenhuma capability poderá bypassar:

```text
input validation
↓
resource resolution
↓
Policy
↓
Execution
↓
ToolResult
↓
Audit
```

## 8.2 Canonical resource before Policy

Policy deve avaliar o recurso que realmente será acessado.

Especialmente:

```text
filesystem path
shell executable
shell cwd
desktop application
URL
artifact
screen capture
```

Não autorizar representação ambígua e executar representação diferente.

## 8.3 Validated input must match executed input

Depois da Policy, não pode ocorrer transformação material silenciosa:

```text
authorized A
↓
execute B
```

Canonicalização/resolution significativa deve acontecer antes da autorização.

## 8.4 Workspace não é permission

```text
workspace = D:\Projects\foo
```

não significa automaticamente:

```text
filesystem.read
filesystem.write
shell.execute
```

## 8.5 Filesystem não depende de shell

Operações normais de arquivo devem usar filesystem Tools específicas.

Não implementar:

```text
filesystem.read → powershell Get-Content
```

como baseline.

## 8.6 Shell não usa implicit shell parsing

Baseline obrigatório:

```text
asyncio.create_subprocess_exec(...)
```

ou mecanismo semanticamente equivalente.

Proibido como implementação default:

```text
shell=True
os.system(...)
subprocess(..., shell=True)
```

## 8.7 Desktop open_app não vira shell disfarçado

`desktop.open_app` não deve aceitar arbitrary command line e se transformar numa segunda `shell.execute`.

## 8.8 Network read possui safety técnico

Policy grant para web não elimina:

```text
SSRF protection
redirect validation
scheme validation
response limits
timeouts
```

## 8.9 Screenshot é ação explícita

Nenhuma:

```text
continuous capture
background surveillance
periodic screenshot
automatic screen history
```

entra neste Slice.

## 8.10 Vision pertence ao AI boundary

Encoding/base64/provider image object é responsabilidade do Adapter.

## 8.11 Agent usa subset real

Registrar Tools globalmente não significa expô-las automaticamente ao Agent.

## 8.12 Sem Memory fake fingindo ser Memory real

Slice 06 não cria substitutes temporários para Sofias Memory.

---

# 9. Gate I8 — Sofia Pode Usar o Computador

**Escopo:** SA-B024 → SA-B028  
**Status inicial:** READY  
**Depende de:** Gates I2, I4 e I5 já fechados

## 9.1 Objetivo

Provar que o Tool Runtime existente executa capabilities úteis e concretas de forma segura.

Gate I8 não é um exercício para criar cinco classes que passam unit tests.

Deve existir execução real.

---

# 10. SA-B024 — Filesystem Capability

Tools mínimas:

```text
filesystem.read
filesystem.write
filesystem.list
```

`move` e `delete` continuam fora do baseline salvo necessidade descoberta durante o Gate.

## 10.1 filesystem.read

Input mínimo conceitual:

```text
path
max_bytes? 
encoding?
```

O runtime deverá:

```text
validate
↓
canonicalize
↓
resolve actual filesystem resource
↓
Policy
↓
bounded read
↓
normalized result
```

Não permitir leitura ilimitada de arquivo arbitrário.

Arquivos binários grandes devem preferir Artifact semantics ou erro estruturado em vez de despejo integral no ToolResult.

## 10.2 filesystem.write

Input conceitual:

```text
path
content
encoding?
overwrite?
```

Mutating capability.

Deve exigir authority explícita.

Baseline preferido para full-file replacement:

```text
temporary write
↓
flush/close
↓
atomic replace when supported
```

Não criar diretórios ancestrais silenciosamente sem semântica explícita.

Não sobrescrever arquivo existente quando `overwrite=false`.

## 10.3 filesystem.list

Baseline deve ser bounded.

Preferir inicialmente:

```text
one directory level
```

em vez de recursive traversal ilimitado.

Resultado normalizado pode informar:

```text
name
kind
relative/canonical identity
size when cheap
```

Não seguir recursivamente junctions/symlinks por padrão.

## 10.4 Windows path safety

Como Sofia é Windows-first, testes devem cobrir:

```text
drive-letter normalization
case-insensitivity
.. traversal
mixed separators
UNC paths
device-like paths
symlink/junction escapes
non-existing write targets
parent resolution
```

Path string não é resource identity suficiente antes de canonicalização.

## 10.5 Resource identity

Resource usado por Policy/Audit deve ser estável e canonicalizado.

Exemplo conceitual:

```text
file:///c:/projects/sofias_assistant/README.md
```

O formato exato pode variar.

O ponto obrigatório é:

```text
equivalent Windows paths
→ same effective resource identity
```

quando semanticamente apontarem para o mesmo recurso.

## 10.6 Critérios B024

```text
[ ] filesystem.read funciona com arquivo real
[ ] filesystem.write funciona dentro de scope autorizado
[ ] filesystem.list funciona dentro de scope autorizado
[ ] traversal não escapa do scope
[ ] junction/symlink escape é tratado
[ ] canonical resource é usado pela Policy
[ ] unauthorized path nunca chega ao handler efetivo
[ ] write é auditável
[ ] bounded reads/listings evitam resultado ilimitado
[ ] nenhum shell é usado para implementar filesystem
```

---

# 11. SA-B025 — Shell Capability

Tool:

```text
shell.execute
```

Este é um ponto de segurança importante do Slice.

## 11.1 Input baseline

Conceitualmente:

```text
executable
arguments[]
cwd
environment_overrides?
timeout_seconds?
```

Não usar como contrato primário:

```text
command: "qualquer string"
```

O modelo preferido é executable + argv explícitos.

## 11.2 Gap atual do ExecutionDispatcher

O SUBPROCESS implementado no Slice 04 utiliza `subprocess_command` estático no ToolSpec.

Isso foi adequado para provar Gate I5.

Não é suficiente para `shell.execute`.

O Slice 06 deve introduzir o menor seam necessário para representar uma **resolved dynamic subprocess invocation**.

Conceitualmente:

```text
validated shell input
↓
executable resolution
↓
cwd resolution
↓
environment filtering
↓
resolved process invocation
↓
resource identity
↓
Policy
↓
ExecutionDispatcher
↓
create_subprocess_exec
```

A execução dinâmica **não pode** ser implementada fazendo o handler chamar subprocess diretamente e ignorar o dispatcher.

O ExecutionDispatcher continua sendo o owner da execution isolation.

## 11.3 Same resolution rule

Executable e cwd autorizados devem ser os mesmos executados.

Evitar:

```text
Policy sees:
git

Executor later resolves:
different git.exe
```

quando isso puder alterar authority.

## 11.4 Environment

Não copiar o environment completo do processo pai.

Baseline deve usar environment mínimo/filterable.

Secrets só entram quando explicitamente necessários e nunca retornam em:

```text
ToolResult
Audit
stdout metadata
error
```

## 11.5 stdin

Interactive shell não é requisito do MVP.

Baseline pode não suportar stdin arbitrário.

## 11.6 stdout/stderr

Continuam bounded.

Truncation/overflow precisa ser explícito.

Não permitir processo produzir output ilimitado em memória.

## 11.7 Timeout e cancellation

Timeout deve terminar processo.

Cancellation de Task deve propagar para subprocess quando seguro.

Process tree cleanup no Windows deve ser considerado no reference harvest.

Não assumir que terminar somente o processo pai sempre encerra descendants.

## 11.8 Elevation

Slice 06 não implementa UAC elevation.

Qualquer operação que exija elevation deve:

```text
REQUIRE_ELEVATION
```

ou falhar fechado.

## 11.9 Shell grants

Default recomendado:

```text
confirmation lifetime = ONE_SHOT
```

especialmente para comandos mutating.

Não criar implicitamente:

```text
"Você autorizou um git status"
→ agora qualquer shell está autorizada
```

## 11.10 Critérios B025

```text
[ ] shell.execute executa processo real
[ ] sem shell=True
[ ] executable/argv são explícitos
[ ] cwd é canonicalizado
[ ] environment é filtrado
[ ] timeout funciona
[ ] cancellation funciona
[ ] stdout/stderr são bounded
[ ] exit não-zero vira ToolError seguro
[ ] subprocess permanece auditável
[ ] dynamic invocation passa pelo ExecutionDispatcher
[ ] SANDBOX continua fail-closed
[ ] no implicit elevation
```

---

# 12. SA-B026 — Web Search & Read

Tools:

```text
web.search
web.read
```

O objetivo não é browser automation.

## 12.1 Separação recomendada

```text
Tool
↓
Web Capability Service
↓
SearchBackend / Reader
↓
external network
```

O Tool não deve acoplar toda a arquitetura a uma única search API.

## 12.2 web.search

Contrato conceitual:

```text
query
max_results?
```

Resultado normalizado:

```text
results[]
    title
    url
    snippet
    source/provider metadata safe
```

Search provider-native payload não atravessa o Core inteiro.

## 12.3 Search backend

Criar boundary pequeno como:

```text
WebSearchBackend
```

ou equivalente.

Implementar:

- Fake backend determinístico;
- um backend real para MVP.

Escolha do backend real pode ocorrer durante reference harvest, desde que:

- possua API/uso permitido;
- credentials sejam tratadas pelo SecretService;
- contrato externo não contamine ToolSpec;
- ausência temporária do backend possa virar degraded/unavailable, não crash do Core.

A escolha de vendor de search não exige ADR novo salvo se alterar significativamente a arquitetura.

## 12.4 web.read

Baseline:

```text
HTTP/HTTPS
bounded response
timeout
limited redirects
content-type validation
text normalization
```

Não executar JavaScript.

Não implementar browser headless completo.

## 12.5 SSRF baseline

Bloquear por padrão destinos como:

```text
loopback
link-local
metadata endpoints
private network ranges
unsupported schemes
```

Redirect deve ser revalidado.

Não validar apenas URL inicial e seguir redirect livremente.

DNS rebinding e resolução de endereço devem fazer parte do threat review da implementação.

## 12.6 Result limits

Aplicar limites para:

```text
response bytes
normalized text size
redirect count
request duration
search results
```

## 12.7 Critérios B026

```text
[ ] web.search possui backend abstraction
[ ] fake backend mantém CI offline
[ ] pelo menos um backend real existe
[ ] web.read recupera página HTTP/HTTPS real
[ ] resultado é normalizado
[ ] response size é bounded
[ ] redirects são bounded/revalidados
[ ] SSRF baseline está presente
[ ] network error produz ToolError seguro
[ ] credentials não aparecem em Audit
[ ] browser automation não é introduzida
```

---

# 13. SA-B027 — Desktop Basics

Tools mínimas:

```text
desktop.open_app
desktop.active_window
```

`desktop.open_file` permanece opcional.

## 13.1 DesktopBackend

Como os testes precisam continuar determinísticos e a implementação inicial é Windows-first, preferir boundary pequeno:

```text
DesktopBackend
```

com:

```text
WindowsDesktopBackend
FakeDesktopBackend
```

Não construir framework cross-platform completo.

## 13.2 desktop.open_app

Objetivo:

```text
abrir aplicação conhecida/autorizada
```

Não:

```text
executar arbitrary command line
```

`desktop.open_app` não deve virar alias de `shell.execute`.

Input preferido:

```text
application identifier/path
```

Arguments arbitrários ficam fora do baseline ou exigem semântica explícita posterior.

## 13.3 desktop.active_window

Retorno seguro pode conter:

```text
window title
process name/id when available
```

Evitar copiar conteúdo interno da janela.

Consultar janela ativa não significa fazer screenshot.

## 13.4 Windows APIs

Preferir API do sistema operacional apropriada.

Não introduzir automação de mouse/teclado apenas para descobrir/open app.

## 13.5 Critérios B027

```text
[ ] desktop.open_app abre aplicação real no Windows
[ ] application resource passa pela Policy
[ ] desktop.active_window retorna estado normalizado
[ ] backend fake mantém CI determinístico
[ ] unsupported/headless state falha de forma segura
[ ] nenhuma automação de teclado/mouse é introduzida
[ ] open_app não vira shell genérica
```

---

# 14. SA-B028 — Screenshot Vision

O Slice deve provar:

```text
authorized capture
↓
screenshot bytes
↓
ArtifactService
↓
ArtifactRef
↓
vision-capable AI provider
↓
normalized observation
↓
Core-owned context/result
```

## 14.1 Tool de captura

Nome preferido, já coerente com ADR-0008:

```text
desktop.capture_screen
```

A Tool faz **captura**.

Ela não deve conter provider-specific vision inference.

## 14.2 Authorization

Screenshot pode capturar conteúdo sensível.

Baseline:

```text
confirmation_required = true
```

Default preferido:

```text
ONE_SHOT
```

Não manter screen capture autorizado indefinidamente por conveniência.

## 14.3 Artifact

Screenshot deve passar pelo ArtifactService.

ToolResult retorna:

```text
ArtifactRef
```

e não base64 gigantesco.

Formato inicial recomendado:

```text
PNG
```

ou outro formato lossless adequado escolhido pela implementação.

## 14.4 AI capability gap

O AI contract atual não possui image input.

Adicionar capability explícita:

```text
IMAGE_INPUT
```

ou nomenclatura final semanticamente equivalente.

Não criar um multimodal framework universal.

O Slice precisa somente do contrato mínimo necessário para:

```text
image bytes
+
media type
+
text instruction
→
normalized provider response
```

## 14.5 Provider-neutral vision contract

Preferir contrato especializado, conceitualmente:

```text
VisionRequest
VisionImageInput
VisionResponse
VisionProvider
```

em vez de transformar todos os objetos de `AIMessage` em uma árvore multimodal genérica agora.

Isso mantém baixo o blast radius sobre Conversation/Realtime.

A implementação poderá escolher nomes diferentes desde que preserve essa separação.

## 14.6 Adapter

Encoding provider-native:

```text
base64
data URL
provider image object
upload reference
```

permanece dentro do Adapter.

## 14.7 Router

Vision request deve exigir:

```text
Capability.IMAGE_INPUT
```

O AI Router deve selecionar somente modelo que declare suporte.

Não hardcode OpenAI model diretamente na capability.

## 14.8 ContextBuilder integration

Resultado de visão é uma **observação derivada**, não transcript e não Memory.

ContextBuilder deverá receber um seam explícito para contexto produzido por Tool/observation quando necessário.

Não criar generic context contributor framework neste Slice.

Uma extensão pequena para:

```text
ToolResult / Observation context
```

é suficiente.

Raw screenshot não deve ser transformado silenciosamente em texto de contexto sem passar pelo vision boundary.

## 14.9 Continuous vision

Explicitamente fora:

```text
screen polling
continuous screenshot
background visual awareness
automatic webcam
visual memory history
```

## 14.10 Critérios B028

```text
[ ] desktop.capture_screen exige authority
[ ] capture real funciona localmente no Windows
[ ] screenshot vira ArtifactRef
[ ] raw image não é persistida no Operational Store
[ ] IMAGE_INPUT existe no capability model
[ ] provider-neutral vision contract existe
[ ] OpenAI/primeiro adapter suporta o contrato
[ ] Fake Vision Provider existe
[ ] Router rejeita model sem image capability
[ ] visão produz resposta normalizada
[ ] resultado pode alimentar ContextBuilder explicitamente
[ ] não existe screen polling
[ ] CI não depende de desktop interativo real
```

---

# 15. Gate I8 — Cenários verticais

## Cenário A — Filesystem read autorizado

```text
ToolCall filesystem.read
↓
canonical path
↓
Policy
↓
Grant matches exact scope
↓
read
↓
ToolResult
↓
Audit
```

## Cenário B — Filesystem escape negado

```text
authorized workspace
↓
path with traversal/junction escape
↓
canonical resolution
↓
outside scope
↓
DENY / technical guard
↓
handler never reads target
```

## Cenário C — Shell controlado

```text
shell.execute
↓
validated executable + argv + cwd
↓
canonical process resource
↓
ONE_SHOT authority
↓
ExecutionDispatcher
↓
create_subprocess_exec
↓
bounded output
↓
ToolResult + Audit
```

## Cenário D — Shell timeout

```text
process exceeds deadline
↓
termination
↓
TIMED_OUT/FAILED normalized
↓
Audit
```

## Cenário E — Web research primitive

```text
web.search
↓
normalized search results
↓
web.read selected URL
↓
safe normalized content
```

## Cenário F — Desktop primitive

```text
desktop.open_app
↓
Policy
↓
Windows backend
↓
application opened
```

e:

```text
desktop.active_window
↓
normalized observation
```

## Cenário G — Screenshot Vision

```text
user request
↓
desktop.capture_screen
↓
confirmation
↓
ArtifactRef
↓
VisionProvider
↓
IMAGE_INPUT route
↓
normalized observation
↓
Core context/result
```

---

# 16. Critérios de fechamento do Gate I8

I8 somente fecha quando:

```text
[ ] SA-B024 DONE
[ ] SA-B025 DONE
[ ] SA-B026 DONE
[ ] SA-B027 DONE
[ ] SA-B028 DONE

[ ] filesystem capabilities usam Tool Runtime real
[ ] filesystem path safety está provada
[ ] shell real usa controlled subprocess
[ ] shell não usa shell=True
[ ] dynamic subprocess não bypassa ExecutionDispatcher
[ ] web search possui backend real + fake
[ ] web read possui SSRF/redirect/size protection
[ ] desktop basics funcionam no Windows real
[ ] screenshot é Artifact
[ ] screenshot exige authority explícita
[ ] AI Provider Framework suporta image input de forma provider-neutral
[ ] ContextBuilder mantém ownership
[ ] Audit continua reconstruível
[ ] full regression verde
[ ] ruff verde
[ ] mypy verde
[ ] diff-check verde
[ ] GitHub CI windows-latest verde
[ ] smoke local Windows das capabilities OS-dependent passa
```

Veredito esperado:

```text
GATE I8 — CLOSED — REMOTE VERIFIED
```

---

# 17. Gate I9 — Sofia Pode Delegar

**Escopo:** SA-B029  
**Depende de:** Gate I8 fechado  
**Status inicial:** BLOCKED BY I8

## 17.1 Escolha do primeiro Agent

O primeiro Agent real será:

```text
Development Analysis Agent
```

não um:

```text
General Purpose Agent
```

e não ainda um:

```text
Autonomous Development Agent
```

## 17.2 Por que Development Analysis

Ele valida uma necessidade real do produto:

```text
receber objetivo
↓
inspecionar workspace
↓
decidir quais arquivos são relevantes
↓
usar múltiplas Tools
↓
adaptar análise aos resultados
↓
produzir findings
↓
retornar à Sofia/root
```

sem exigir:

```text
Sofias Memory
browser automation
filesystem.write irrestrito
shell irrestrito
nested agents
```

É deliberadamente um primeiro passo mais restrito.

---

# 18. AgentDefinition inicial

Conceitualmente:

```text
name:
    development-analysis

capabilities:
    repository-analysis

default tools:
    filesystem.list
    filesystem.read

optional tools when explicitly delegated:
    web.search
    web.read
    shell.execute

not default:
    filesystem.write
    desktop.open_app
    desktop.capture_screen
```

O subset efetivo continua definido pela root em cada AgentRun.

---

# 19. AI-driven Agent loop

O Agent do Slice 04 provou a infraestrutura de AgentRun.

B029 precisa provar especialização **real conduzida por AI**.

O loop mínimo será:

```text
delegated objective
↓
bounded Agent context
↓
AI provider
↓
text or ToolCallProposal
↓
validate proposal
↓
Tool subset check
↓
ExecutionRuntime
↓
ToolResult
↓
append observation to Agent context
↓
next provider call
↓
final structured result
```

ToolCallProposal continua inerte.

O provider não chama Tool diretamente.

---

# 20. Runtime limits

Agent deverá respeitar limites como:

```text
max_steps
max_tool_calls
max_duration
```

Token/cost limit pode permanecer simples se ainda não houver accounting suficientemente estável.

O importante é evitar loop infinito.

Ao atingir limite:

```text
AgentRun
→ bounded terminal/failure result
```

não continuar silenciosamente.

---

# 21. Context isolation

Agent não recebe Conversation completa.

DelegatedContext inicial deve conter somente:

```text
objective
workspace
relevant user constraints
selected artifacts/context
runtime limits
```

Memory não entra até Slice 05.

---

# 22. Workspace

Development Analysis Agent deve operar dentro de workspace explícito.

Por exemplo:

```text
D:\Projects\sofias_assistant
```

Mas:

```text
workspace
```

não concede automaticamente:

```text
filesystem.read
```

A root ainda precisa construir authority compatível.

---

# 23. Default read-only posture

A configuração default do primeiro Agent deve ser efetivamente read-oriented.

I9 não exige que o primeiro Agent modifique código.

Isso é deliberado.

Queremos primeiro provar:

```text
agentic reasoning
+
multiple Tool usage
+
context narrowing
+
authority narrowing
+
result handoff
```

antes de conceder escrita autônoma.

---

# 24. Shell no Agent

`shell.execute` pode ser disponibilizada em AgentRuns específicos.

Ela **não** deve estar no default Tool subset do Development Analysis Agent.

Se uma execução precisar:

```text
git status
pytest
git diff
```

root poderá construir um AgentRun com Tool subset ampliado e authority específica.

Não transformar:

```text
Development Analysis Agent
```

em:

```text
arbitrary local command execution agent
```

por conveniência.

---

# 25. Agent result

Resultado normalizado deve conter no mínimo:

```text
summary
findings
files/references inspected
tool usage summary
unresolved items
```

Quando necessário:

```text
artifacts
```

também podem ser retornados.

Não persistir hidden chain-of-thought.

---

# 26. Specialization requests

A infraestrutura atual já permite pedido estruturado de especialização.

O primeiro Agent pode solicitar:

```text
additional capability needed
```

mas I9 não exige segundo Agent real.

Se Development Analysis Agent precisar de outra especialização:

```text
Agent
↓
SpecializationRequest
↓
Sofia/root
```

A root decide.

Não criar nested Agent.

---

# 27. Gate I9 — cenário vertical principal

Cenário obrigatório:

```text
User objective
    ↓
Sofia/root creates durable Task
    ↓
root selects Development Analysis Agent
    ↓
root builds narrowed DelegatedContext
    ↓
root builds narrowed authority
    ↓
root supplies explicit Tool subset
    ↓
AgentRun
    ↓
AI evaluates objective
    ↓
filesystem.list
    ↓
Tool Runtime + Policy
    ↓
ToolResult
    ↓
AI chooses relevant file
    ↓
filesystem.read
    ↓
Tool Runtime + Policy
    ↓
ToolResult
    ↓
additional bounded inspection when needed
    ↓
Agent final result
    ↓
Sofia/root receives result
    ↓
Task completes
    ↓
Audit explains entire chain
```

Esse cenário pode operar sobre repository fixture temporário e determinístico no CI.

---

# 28. Negative Agent scenarios

Também provar:

### Tool subset escape

```text
Agent allowed:
filesystem.read

Agent proposes:
shell.execute

→ denied before execution
```

### Workspace escape

```text
Agent workspace:
fixture/repo

Agent proposes:
../secret

→ denied
```

### Nested Agent attempt

Agent não possui API/token de root para criar AgentRun.

### Runaway loop

```text
max_steps exceeded
→ execution stops
```

### Provider malformed ToolCall

```text
invalid arguments
→ validation failure
→ no execution
```

---

# 29. Critérios de fechamento do Gate I9

```text
[ ] Development Analysis Agent existe como AgentDefinition real
[ ] runner usa AI Provider Framework
[ ] provider não executa Tools diretamente
[ ] ToolCallProposal permanece inerte
[ ] root é único creator de AgentRun
[ ] DelegatedContext é reduzido
[ ] Tool subset é reduzido
[ ] authority é reduzida
[ ] Agent usa múltiplas Tools
[ ] Tool calls passam pelo ExecutionRuntime
[ ] Agent não cria Agent diretamente
[ ] workspace escape é impedido
[ ] Tool subset escape é impedido
[ ] runtime limits impedem loop infinito
[ ] final result retorna à root
[ ] Task e AgentRun permanecem conceitos distintos
[ ] Audit reconstrói Task → Agent → Tool → Policy → Result
[ ] deterministic Gate test passa
[ ] full regression passa
[ ] GitHub CI passa
```

Veredito esperado:

```text
GATE I9 — CLOSED — REMOTE VERIFIED
```

---

# 30. Estratégia de testes

Correctness principal continua determinística e offline.

## Unit

Cobrir:

```text
filesystem canonicalization
filesystem scope
junction/symlink guards
filesystem validators
shell argument validation
executable resolution
cwd resolution
environment filtering
URL validation
SSRF decisions
redirect rules
response bounds
desktop normalization
vision contracts
Agent loop limits
Agent Tool subset
Agent context narrowing
```

## Integration

Cobrir:

```text
real temporary filesystem
ExecutionRuntime + Policy + built-in Tools
real subprocess harmless fixture
fake web backend
local HTTP fixture for web.read
fake desktop backend
fake screenshot backend
ArtifactService
fake vision provider
fake AI-driven Development Analysis Agent
Audit trace
```

## Windows-specific

Usar `windows-latest` para comportamento de path e APIs que não dependem de desktop interativo.

## Local Windows smoke

Necessário para:

```text
desktop.open_app
desktop.active_window
desktop.capture_screen
```

quando GitHub runner não puder provar desktop interativo real.

## External live smoke

Opt-in para:

```text
real web.search backend
real public web.read
real image-capable AI model
```

Credentials não entram no CI obrigatório.

---

# 31. Quality gates

Em cada checkpoint relevante:

```text
targeted tests
Gate vertical tests
full pytest
ruff check
ruff format --check
mypy
git diff --check
```

No fechamento:

```text
commit
↓
push
↓
GitHub Actions windows-latest
↓
remote success
```

---

# 32. Persistence

Não criar persistence nova apenas porque existe capability real.

Filesystem, shell, web e desktop não precisam de tabelas próprias por padrão.

Continuam suficientes:

```text
tool_calls
policy_decisions
grants
confirmation_requests
artifacts
tasks
agent_runs
audit_entries
```

Nova persistence só deverá ser adicionada se houver estado durável real não representável pelos modelos existentes.

Não persistir:

```text
raw screenshot em SQLite
raw web pages em SQLite por padrão
stdout/stderr arbitrários em Audit
full filesystem contents em Audit
```

Artifacts são usados quando conteúdo grande precisa permanecer referenciável.

---

# 33. Audit

I8/I9 reutilizam SA-B030.

Não criar segundo audit subsystem.

Audit deverá registrar referências e fatos suficientes para reconstruir:

```text
Tool
resource
authority
PolicyDecision
execution mode
result
ArtifactRef
Task
AgentRun
```

sem registrar indiscriminadamente:

```text
file contents
web contents
screen contents
shell output
provider hidden state
secrets
```

---

# 34. Health e availability

Capabilities dependentes de recursos externos/OS podem estar indisponíveis.

Exemplos:

```text
web search backend credential absent
vision model unavailable
desktop backend unsupported
screenshot backend unavailable
executable absent
```

Isso não deve necessariamente impedir o Core inteiro de iniciar.

Preferir:

```text
Core = ready
Capability = degraded/unavailable
```

quando a capability não for blocker estrutural do Core.

Tool indisponível não deve ser anunciada ao provider/Agent como utilizável.

---

# 35. Reference harvest

Antes de cada family importante:

```text
filesystem/shell
web
desktop/screenshot
real Agent
```

realizar reference harvest dirigido.

Prioridades:

```text
current Sofia's Assistant codebase
Mark LI
Brahma AI
official Python/Windows documentation
official provider/search APIs
Sofias Memory somente para padrões de infraestrutura realmente reutilizáveis
```

Para cada referência:

```text
understand pattern
↓
compare with Sofia ADRs
↓
adapt compatible idea
↓
reject architecture conflicts
↓
clean-room implementation
```

Não copiar arquitetura de Agent que permita nested authority ou Tool execution fora da Policy.

---

# 36. Não objetivos do Slice

Explicitamente fora:

```text
Sofias Memory integration
MemoryProvider
Memory Orchestrator
Cognitive Memory MVP

scheduler
reminders
notifications

full browser automation

mouse automation
keyboard automation

continuous screenshot
continuous screen awareness
webcam

filesystem.delete production capability
filesystem.move production capability

UAC elevation implementation

security sandbox backend definitivo

autonomous coding Agent
automatic code modification
automatic git push

nested Agents
multi-agent swarm

plugin framework

full crash/restart recovery
final Desktop Client
```

Alguns itens poderão possuir seams, mas não implementação prematura.

---

# 37. Brief de execução — Gate I8

Missão para o agente de implementação:

> **Concluir Gate I8 — Sofia Pode Usar o Computador.**
>
> Materialize SA-B024–SA-B028 ponta a ponta sobre o Tool Runtime, Policy, Execution Isolation, Artifact Service e Audit já fechados nos Gates I4/I5/I10.
>
> Implemente production Filesystem, controlled Shell, Web Search/Read, Windows Desktop Basics e explicit Screenshot Vision.
>
> Faça reference harvest dirigido antes das decisões concretas de backend.
>
> Preserve a cadeia `validate → canonical resource → Policy → execute → ToolResult → Audit`.
>
> Não implemente shell via handler que bypassa ExecutionDispatcher. Evolua o menor seam necessário para dynamic resolved subprocess execution mantendo `create_subprocess_exec` e fail-closed semantics.
>
> Screenshot deve produzir ArtifactRef e vision inference deve entrar pelo AI Provider Framework através de capability/provider-neutral contract, não por objetos OpenAI espalhados pelo Core.
>
> Use Fake backends para correctness determinística e smoke real apenas onde OS/network/provider exigirem.
>
> Não peça aprovação de microsteps. Faça checkpoints coesos e atualize o Resume Capsule se necessário.
>
> Retorne somente quando Gate I8 estiver closure-ready/remote-verified ou existir blocker arquitetural/credential realmente incontornável.

---

# 38. Brief de execução — Gate I9

Depois de I8 fechado:

> **Concluir Gate I9 — Sofia Pode Delegar.**
>
> Materialize SA-B029 com o primeiro Agent real: `Development Analysis Agent`.
>
> Use AgentRuntime já existente; não crie outro sistema de agents.
>
> O Agent deve ser AI-driven, criado exclusivamente pela Sofia/root, receber DelegatedContext reduzido, authority reduzida e Tool subset explícito.
>
> Seu default posture deve ser read-oriented, utilizando inicialmente `filesystem.list` e `filesystem.read`; outras Tools só entram quando a root explicitamente as delegar.
>
> ToolCall proposals do provider continuam inertes e todas as ações passam pelo ExecutionRuntime/Policy.
>
> Prove adaptive multi-Tool behavior, bounded runtime, tool subset enforcement, workspace isolation, result handoff à root e Audit causal completo.
>
> Não implemente Autonomous Development Agent, filesystem.write default, nested Agents ou Memory.
>
> Retorne somente quando Gate I9 estiver closure-ready/remote-verified ou existir blocker real.

---

# 39. Definition of Done — Slice 06

O Slice estará concluído quando:

```text
Gate I8 — CLOSED — REMOTE VERIFIED
Gate I9 — CLOSED — REMOTE VERIFIED
```

e:

```text
filesystem funciona
shell funciona controladamente
web search/read funcionam
desktop basics funcionam
screenshot vision funciona
real specialized Agent funciona
```

sem quebrar:

```text
Gate I1 — Core Alive
Gate I2 — Sofia Can Converse
Gate I3 — Sofia Can Speak
Gate I4 — Sofia Can Act Safely
Gate I5 — Sofia Can Work
Gate I10 — Sofia Is Traceable
```

Também devem continuar verdadeiras:

```text
Provider != authority
Agent != authority
Workspace != authority
Tool != authority
Artifact != raw Operational Store blob
SUBPROCESS != security sandbox
ContextBuilder owns context
Sofia/root owns orchestration
Audit != chain-of-thought
```

Veredito esperado:

```text
SLICE 06 — COMPUTER CAPABILITIES & REAL AGENT
CONCLUÍDO — VERIFICADO REMOTAMENTE
```

---

# 40. Direção pós-Slice

Se Sofias Memory v0.7.0 estiver pronto:

```text
Slice 05 — Sofia Remembers
    ↓
Gate I6
```

Caso ainda não esteja:

```text
Slice 07 — Proactivity & Product Interface
```

poderá ser reavaliado por dependências antes de qualquer nova inversão de ordem.

Não antecipar automaticamente Slice 07 sem nova análise.

---

# 41. Estado inicial do Ledger

```text
Slice 06 status:
    READY FOR APPROVAL

Execution order:
    ANTICIPATED BEFORE SLICE 05

Reason:
    Sofias Memory v0.7.0 not yet available

Current active Gate:
    none

Next Gate:
    I8 — Sofia Can Use the Computer

Gate I8:
    READY

Gate I9:
    BLOCKED BY I8

Slice 05 / Gate I6:
    DEFERRED — WAITING FOR SOFIAS MEMORY v0.7.0

Implementation baseline:
    c611f557fd1d4c9c23b92093c3de438962ca192c

Previous completed Gate:
    I10 — CLOSED — REMOTE VERIFIED
```

---

# 42. Frozen decisions for start

```text
01. Slice numbering does not change.

02. Slice 06 may execute before Slice 05.

03. No Slice 06 dependency on Sofias Memory.

04. Built-in capabilities remain behind Tool Runtime.

05. Filesystem does not use shell internally.

06. shell.execute uses explicit executable + argv semantics.

07. Production dynamic shell execution remains owned by ExecutionDispatcher.

08. No shell=True baseline.

09. Web Search uses a backend boundary; vendor is replaceable.

10. web.read is direct bounded retrieval, not browser automation.

11. Desktop implementation is Windows-first.

12. desktop.open_app is not arbitrary shell.

13. Screenshot capture is explicit and authorization-bound.

14. Screenshot becomes ArtifactRef.

15. AI capability model gains image-input support.

16. Vision encoding stays inside provider adapter.

17. No continuous visual awareness.

18. First real Agent is Development Analysis Agent.

19. Development Analysis Agent is read-oriented by default.

20. AgentRun remains root-owned and authority-narrowed.

21. Agents cannot instantiate Agents.

22. Memory remains absent until Slice 05.

23. Existing Audit subsystem remains authoritative.

24. Existing AgentRuntime remains authoritative.

25. Existing Tool Runtime remains authoritative.
```

## Execution Ledger — I8 preflight / checkpoint I8-A

```text
GATE:
    I8 — Sofia Pode Usar o Computador
STATUS:
    ACTIVE — PREFLIGHT COMPLETE
CURRENT CHECKPOINT:
    I8-A — Filesystem + Shell

COMPLETED:
- Exec-plan ativo lido antes de qualquer alteração de código.
- HEAD/worktree confirmados: c611f557fd1d4c9c23b92093c3de438962ca192c; código limpo.
- Reference harvest dirigido: asyncio subprocess, urllib redirects, ipaddress SSRF e Windows GDI capture.
- ADR-0004/0005/0006/0008/0013/0015 confrontados; nenhuma divergência arquitetural encontrada.

REMAINING:
- Implementar Filesystem, Shell, Web, Desktop e Screenshot Vision ponta a ponta.
- Adicionar testes determinísticos, integração vertical e executar quality gates.
- Commit/push e confirmar GitHub Actions verde.

FROZEN DECISIONS:
- AI proposes. Runtime authorizes. Executor acts.
- Todas as capabilities usam validate → canonical resource → Policy → ExecutionDispatcher → ToolResult → Audit.
- Não criar tabelas novas; não implementar Gate I9.

KNOWN FINDINGS:
- Não existem capabilities I8 registradas.
- SUBPROCESS aceita somente comando/cwd estáticos no ToolSpec.
- AI Capability/ProviderBinding não possui IMAGE_INPUT/Vision.
- ArtifactService, Audit e Tool Runtime existentes são reutilizáveis.

DEFERRED:
- Backend search real fica substituível e degraded quando credential ausente.
- Smokes dependentes de desktop/provider real permanecem opt-in/local.

REAL BLOCKERS:
    none

CURRENT HEAD:
    c611f557fd1d4c9c23b92093c3de438962ca192c

NEXT ACTION:
    Implementar os módulos de capabilities e o seam de subprocesso dinâmico.
```

## Execution Ledger — I8 local closure checkpoint

```text
GATE:
    I8 — Sofia Pode Usar o Computador
STATUS:
    CLOSED — REMOTE VERIFIED
CURRENT CHECKPOINT:
    I8 — vertical integration and remote verification complete

COMPLETED:
- SA-B024: filesystem.read/write/list com canonicalização Windows-first, bounds, atomic write e scope via Policy.
- SA-B025: shell.execute com executable/argv/cwd/environment filtrado/timeout e dynamic SubprocessInvocation no Dispatcher.
- SA-B026: web.search com Fake + DuckDuckGo backend substituível; web.read com HTTP(S), SSRF, redirects revalidados e bounds.
- SA-B027: desktop.open_app/active_window/capture_screen com Windows backend e fake determinístico.
- SA-B028: ArtifactRef para screenshot; VisionRequest/VisionImageInput/VisionResponse/VisionProvider, IMAGE_INPUT routing e Fake Vision.
- Nenhuma migration/tabela nova; Audit, ArtifactService e Tool Runtime existentes foram reutilizados.
- `538 passed, 3 skipped`; ruff check/format, mypy e diff-check verdes.
- Smoke Windows local: active_window e captura GDI/BMP real passaram.

REMAINING:
- Nenhum requisito do Gate I8 restante.

FROZEN DECISIONS:
- Gate I9 não foi iniciado.
- SUBPROCESS continua distinto de SANDBOX; SANDBOX permanece fail-closed.
- Não há continuous capture, browser automation, UAC, Memory ou persistence nova.

KNOWN FINDINGS:
- DuckDuckGo backend real depende de disponibilidade de rede no momento da invocação e degrada por erro normalizado.

DEFERRED:
- Smoke de provider vision real e search público real permanecem opt-in; correctness principal é offline/fake.
- DNS rebinding hardening com conexão pinada permanece follow-up de threat model, além do baseline de revalidação DNS/redirect.

REAL BLOCKERS:
    none

CURRENT HEAD:
    e2e9175f08d1309a80b6edae618750d8c6bdce73

NEXT ACTION:
    Não iniciar Gate I9 nesta execução; próxima unidade é I9 após novo planejamento.

REMOTE VERIFICATION:
    run 34780645322 — SUCCESS
    https://github.com/kallbuloso/sofias_assistant/actions/runs/34780645322
```
