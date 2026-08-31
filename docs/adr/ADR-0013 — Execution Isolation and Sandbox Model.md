# ADR-0013 — Execution Isolation and Sandbox Model

**Status:** Accepted  
**Project:** Sofia's Assistant  
**Decision date:** 2026-08-31  
**Scope:** Execution modes, subprocess isolation, sandboxing, shell execution, generated code, plugin workers, workspace boundaries and resource constraints

---

# 1. Context

O Sofia's Assistant deverá executar capacidades com níveis muito diferentes de confiança e risco.

Exemplos:

- ler um arquivo conhecido;
- abrir uma aplicação;
- executar `pytest`;
- rodar um script;
- executar comando de shell;
- executar código produzido dinamicamente;
- carregar Plugin de terceiros;
- utilizar biblioteca nativa;
- executar automação de browser;
- instalar dependências;
- manipular recursos fora de um workspace.

Executar tudo dentro do processo principal do Sofia Core criaria riscos de:

- crash do Core;
- memory corruption;
- deadlocks;
- vazamento de secrets;
- acesso excessivo ao filesystem;
- runaway processes;
- execução arbitrária;
- dependências conflitantes.

Ao mesmo tempo, executar toda operação em containers ou VMs seria desnecessariamente complexo para um produto local-first e Windows-first.

O runtime precisa escolher isolamento proporcional ao risco.

---

# 2. Decision

O Sofia's Assistant adotará três modos arquiteturais fundamentais de execução:

```text
IN_PROCESS
SUBPROCESS
SANDBOX
```

O `ToolSpec`, PolicyEngine e runtime determinarão qual modo é permitido para determinada operação.

A arquitetura será:

```text
                 ToolCall
                    │
                    ▼
               PolicyEngine
                    │
                    ▼
           Execution Dispatcher
          /          |          \
         /           |           \
        ▼            ▼            ▼
 IN_PROCESS     SUBPROCESS      SANDBOX
        │            │            │
        └────────────┴────────────┘
                     │
                 ToolResult
```

---

# 3. Fundamental Rule

A regra será:

> **Execution receives only the environment, resources and authority required for the operation.**

Isolamento deverá ser proporcional ao risco e não apenas ao tipo nominal da Tool.

---

# 4. IN_PROCESS

`IN_PROCESS` significa execução dentro do Sofia Core.

Será adequado somente para código:

- confiável;
- controlado pelo projeto;
- previsível;
- sem risco relevante de bloquear o runtime;
- que não exija isolamento de dependências.

Exemplos possíveis:

```text
read application setting
resolve ToolSpec
query active runtime state
simple deterministic transformation
```

---

# 5. IN_PROCESS Restrictions

Não deverá ser utilizado por conveniência para:

- código desconhecido;
- shell arbitrário;
- Plugins não confiáveis;
- generated code;
- operações potencialmente bloqueantes longas;
- bibliotecas nativas instáveis.

---

# 6. SUBPROCESS

`SUBPROCESS` representa execução em processo separado do Core, mas ainda no host.

Será apropriado para:

- shell;
- executáveis externos;
- comandos de desenvolvimento;
- ferramentas CLI;
- workers;
- bibliotecas que mereçam crash isolation;
- processos de media/audio;
- Plugins quando isolamento completo não for necessário.

---

# 7. SUBPROCESS Benefits

Subprocess permite:

- crash isolation;
- timeout;
- cancellation;
- captura de stdout/stderr;
- environment control;
- working directory control;
- resource observation.

Mas não é boundary de segurança forte por si só.

---

# 8. SUBPROCESS Is Not Sandbox

Um processo filho normal ainda pode potencialmente acessar recursos disponíveis ao usuário do sistema operacional.

Portanto:

```text
SUBPROCESS ≠ SECURITY SANDBOX
```

Esse distinction deverá permanecer explícito.

---

# 9. SANDBOX

`SANDBOX` representa ambiente com restrições de segurança mais fortes.

Poderá limitar:

- filesystem;
- network;
- processes;
- environment;
- credentials;
- CPU;
- memory;
- execution time;
- OS capabilities.

---

# 10. Sandbox Technology

Este ADR não congela a tecnologia concreta.

Possibilidades futuras incluem:

- Windows Sandbox;
- Job Objects + restricted tokens;
- AppContainer;
- container;
- WSL/container;
- VM;
- dedicated worker runtime.

A solução poderá variar por capability.

---

# 11. Risk-based Mode Selection

Execution mode poderá ser definido por combinação de:

```text
Tool default
+
Policy
+
input
+
resource sensitivity
+
code trust
+
Delegation
```

Exemplo:

```text
shell.execute
command = pytest
workspace = trusted project
```

pode ser permitido como `SUBPROCESS`.

Já:

```text
execute downloaded unknown Python
```

pode exigir `SANDBOX`.

---

# 12. Policy Can Increase Isolation

Policy poderá exigir modo mais restritivo que ToolSpec default.

Exemplo:

```text
ToolSpec default = SUBPROCESS
Policy result = require SANDBOX
```

---

# 13. Tool Cannot Reduce Isolation

Tool Handler não poderá unilateralmente trocar:

```text
SANDBOX → IN_PROCESS
```

para facilitar execução.

---

# 14. Execution Dispatcher

O Core possuirá componente responsável por selecionar e iniciar backend de execução.

Conceitualmente:

```text
ExecutionDispatcher
├── InProcessExecutor
├── SubprocessExecutor
└── SandboxExecutor
```

---

# 15. Execution Context

Cada execução deverá receber contexto explícito.

Pode incluir:

```text
execution_id
tool_call_id
task_id
workspace
resource_scope
deadline
environment policy
network policy
cancellation token
allowed secrets refs
```

---

# 16. Workspace

Operações sobre filesystem/development deverão preferencialmente possuir workspace explícito.

Exemplo:

```text
D:\Projects\sofias_assistant
```

Workspace representa boundary operacional.

---

# 17. Workspace Is Not Permission

Como definido anteriormente:

```text
workspace ≠ authority
```

A existência de workspace não concede automaticamente filesystem read/write.

---

# 18. Workspace Canonicalization

Paths deverão ser canonicalizados antes da criação do execution environment.

Runtime deverá considerar:

- `..`;
- symlinks;
- junctions;
- mount points;
- case semantics;
- path aliases.

---

# 19. Workspace Escape

Uma operação autorizada para workspace X não deverá conseguir acessar arbitrariamente:

```text
..\..\other-secret-project
```

através de path traversal.

Sandbox e handlers deverão aplicar defesas apropriadas.

---

# 20. Symlink and Junction Escape

Windows junctions e symlinks podem permitir sair do workspace aparente.

Filesystem policy deverá avaliar recurso real/resolvido quando tecnicamente possível.

---

# 21. Shell

Shell será capability privilegiada.

O baseline será execução por `SUBPROCESS`.

Shell irrestrito não será equivalente a Tool comum de baixo risco.

---

# 22. Shell Execution Context

Uma execução poderá limitar:

```text
cwd
command
arguments
environment
timeout
network
elevation
workspace
```

---

# 23. Shell Command Representation

Preferir execução estruturada:

```text
executable
arguments[]
```

quando possível.

Evitar concatenar string arbitrária via shell interpreter sem necessidade.

---

# 24. Shell Interpreter

Quando PowerShell, cmd ou shell equivalente for necessário, isso deverá ser explícito no ToolCall/handler.

---

# 25. Shell and Least Privilege

Preferir:

```text
pytest
```

diretamente,

em vez de:

```text
powershell -Command "pytest"
```

quando não houver necessidade de shell semantics.

---

# 26. Environment Variables

Subprocess não deverá herdar indiscriminadamente todo environment do Core.

O runtime deverá construir environment controlado.

Secrets presentes no processo principal não deverão vazar automaticamente.

---

# 27. Secret Injection

Quando execução realmente precisar de secret:

```text
SecretStore
   ↓
controlled injection
   ↓
specific execution
```

O secret deverá ser disponibilizado apenas no scope necessário.

---

# 28. Secret Lifetime

Secrets temporariamente injetados deverão existir pelo menor tempo possível e não ser persistidos em ToolResult/logs.

---

# 29. Generated Code

Código produzido por LLM será considerado **untrusted by default**.

Mesmo quando produzido pela Sofia.

Isso inclui:

- Python;
- shell;
- JavaScript;
- PowerShell;
- binaries/build scripts gerados dinamicamente.

---

# 30. Generated Code Is Proposal

LLM produzir código não implica autorização para executá-lo.

Fluxo:

```text
Generated Code
     ↓
proposed execution
     ↓
Policy
     ↓
Execution mode
     ↓
run
```

---

# 31. Generated Code Execution

Código gerado poderá executar:

- em workspace autorizado no host;
- em sandbox;

conforme Policy.

O sistema não adotará:

```text
generate → immediately execute unrestricted
```

---

# 32. Unknown Downloaded Code

Código obtido externamente deverá receber trust inferior a código versionado/controlado localmente.

Execução deverá preferir sandbox ou exigir confirmação apropriada.

---

# 33. Dependency Installation

Instalar dependências é side effect relevante.

Operações como:

```text
pip install
npm install -g
winget install
```

não poderão ocorrer silenciosamente porque Agent detectou módulo ausente.

---

# 34. Project-local Dependencies

Instalação dentro de ambiente isolado do projeto poderá possuir policy distinta de instalação global.

Exemplo:

```text
venv local
```

é semanticamente diferente de alterar Python global.

---

# 35. System-wide Installation

Instalação global deverá ser considerada operação de maior impacto e provavelmente exigir confirmation/elevation.

---

# 36. UAC / Elevation

Operações administrativas deverão utilizar `REQUIRE_ELEVATION` conforme ADR-0006.

O runtime não deverá tentar burlar UAC.

---

# 37. Administrator Process

Sofia Core não deverá executar permanentemente como Administrator apenas para facilitar Tools ocasionais.

Preferir least privilege + elevação pontual.

---

# 38. Network Access

Execution context deverá poder restringir network.

Baseline conceitual:

```text
NETWORK_DENY
NETWORK_SCOPED
NETWORK_ALLOWED
```

A enum final é deferred.

---

# 39. Sandbox Network Default

Código não confiável deverá preferir:

```text
network = DENY
```

salvo necessidade explicitamente autorizada.

---

# 40. Host Network Access

Subprocess executado no host ainda dependerá de Policy.

Se isolamento técnico de network não estiver disponível, runtime deverá reconhecer limitação.

---

# 41. Network Scope

Futuramente poderá limitar hosts/domains.

Exemplo:

```text
allow:
  github.com
  pypi.org
```

---

# 42. Filesystem Exposure

Sandbox deverá receber somente arquivos/diretórios necessários.

Preferir montagem/cópia explícita de workspace em vez de host filesystem inteiro.

---

# 43. Read-only Mounts

Quando operação precisar apenas ler:

```text
workspace = READ_ONLY
```

deverá ser possível tecnicamente quando backend suportar.

---

# 44. Temporary Files

Execuções isoladas deverão usar diretórios temporários próprios.

Isso reduz collisions e cleanup problems.

---

# 45. Artifacts

Arquivos produzidos em sandbox não deverão ser copiados automaticamente para host sem validação.

Fluxo:

```text
sandbox artifact
   ↓
runtime validation
   ↓
authorized destination
```

---

# 46. Resource Limits

Execution backend deverá suportar quando possível:

- timeout;
- CPU limit;
- memory limit;
- process count;
- disk quota;
- output size.

Nem todo backend oferecerá todas as garantias.

---

# 47. Output Limits

Processo que gera output ilimitado não deverá consumir memória do Core indefinidamente.

stdout/stderr deverão possuir buffering/streaming com limites.

---

# 48. Process Tree

Cancellation de subprocess deverá considerar child processes.

Encerrar somente parent pode deixar processos órfãos.

---

# 49. Windows Job Objects

Como produto é Windows-first, Job Objects são candidato importante para controle de process trees e recursos.

A adoção concreta será definida no backlog.

---

# 50. Process Ownership

Core deverá saber quais processos foram criados por determinada execução.

Isso será importante para:

- cancellation;
- recovery;
- cleanup;
- audit.

---

# 51. Process Identity

Metadata poderá incluir:

```text
pid
start_time
execution_id
worker_id
```

Não confiar apenas em PID após restart devido a reutilização de IDs.

---

# 52. Orphan Detection

Após crash do Core, subprocesses podem continuar vivos.

Recovery poderá detectar processos associados quando tecnicamente seguro.

---

# 53. Do Not Kill Unknown Processes

Runtime não deverá matar processo apenas por coincidência de nome ou PID stale.

Ownership precisa ser verificável.

---

# 54. Worker Processes

Algumas capabilities poderão possuir workers persistentes.

Exemplos:

- plugin host;
- browser automation worker;
- audio subsystem.

Workers continuam subordinados ao Core.

---

# 55. Worker Protocol

Comunicação Core ↔ worker deverá usar contrato explícito.

Worker não recebe acesso arbitrário a internals do Core.

---

# 56. Worker Crash

Worker crash deverá produzir estado observável.

Core poderá:

- restart;
- degrade capability;
- fail Task;
- replan.

Core não deverá cair junto sem necessidade.

---

# 57. Worker Health

Workers persistentes deverão possuir health/liveness.

A estratégia concreta é deferred.

---

# 58. Plugin Isolation

Plugins não confiáveis deverão preferencialmente executar fora do Core.

O plugin architecture do ADR-0014 definirá detalhes de lifecycle.

---

# 59. Trusted Built-in Plugin

Mesmo plugin distribuído junto do produto poderá executar in-process quando explicitamente classificado como trusted e seguro.

Não haverá regra absoluta de que todo plugin é subprocess.

---

# 60. Third-party Plugin

Third-party plugin será considerado untrusted by default.

O runtime poderá exigir:

```text
SUBPROCESS
```

ou:

```text
SANDBOX
```

dependendo da capability.

---

# 61. Plugin Manifest Cannot Self-declare Trust

Manifest poderá declarar requirements.

Não poderá dizer:

```text
trust = full
```

e obter isso automaticamente.

---

# 62. Native Libraries

Bibliotecas nativas com histórico de instability poderão ser movidas para worker separado mesmo sendo confiáveis.

Isolation não é apenas security.

Também é reliability.

---

# 63. Browser Automation

Browser automation futura deverá preferir processo/browser profile isolado.

Sofia não deverá necessariamente controlar o browser pessoal principal para toda automação.

---

# 64. Browser Profiles

Poderão existir:

```text
personal browser context
automation browser context
```

com policies distintas.

A decisão detalhada será futura.

---

# 65. Desktop Automation

Controle de mouse/teclado atua diretamente na sessão do usuário e dificilmente pode ser sandboxed de forma útil.

Portanto deverá depender fortemente de:

- explicit capability;
- context;
- confirmation/delegation;
- visibility;
- cancellation.

---

# 66. Execution Trust Classes

Runtime poderá futuramente classificar código/origem como:

```text
CORE_TRUSTED
PROJECT_TRUSTED
PLUGIN_UNTRUSTED
GENERATED_UNTRUSTED
DOWNLOADED_UNTRUSTED
```

A taxonomia concreta é deferred.

---

# 67. Trust Does Not Replace Policy

Mesmo `CORE_TRUSTED` code não possui automaticamente authority ilimitada.

Trust determina isolamento.

Policy determina autorização.

---

# 68. Trust vs Authority

Regra importante:

```text
Trust ≠ Authority
```

Código confiável pode não estar autorizado a acessar determinado recurso.

Código não confiável pode ser autorizado dentro de sandbox restrito.

---

# 69. Execution Plan Validation

Antes de iniciar execução isolada, runtime deverá validar:

- mode;
- workspace;
- resources;
- environment;
- network policy;
- secrets;
- limits.

---

# 70. Fail Closed

Se sandbox obrigatório não estiver disponível:

```text
required SANDBOX unavailable
```

não deverá automaticamente virar:

```text
run on host instead
```

Sem confirmação/policy explícita, a operação deve falhar.

---

# 71. Capability Degradation

Runtime poderá informar:

> “Esta operação exige sandbox, mas o ambiente de sandbox não está disponível.”

E permitir outra estratégia.

---

# 72. Sandbox Escape Assumption

Nenhum sandbox será considerado perfeito.

Design deverá aplicar defense in depth:

- least privilege;
- no unnecessary secrets;
- limited network;
- limited filesystem;
- time/resource limits.

---

# 73. ToolResult from Isolated Process

Worker/executor deverá normalizar resultado para `ToolResult`.

Provider/Agent não deverá consumir stdout bruto como contrato principal.

---

# 74. Structured Worker Protocol

Preferir protocolo estruturado para:

- command;
- status;
- result;
- errors;
- cancellation.

---

# 75. Stdout/Stderr

Poderão ser capturados como diagnostics/artifacts.

Não serão necessariamente o `data` principal do ToolResult.

---

# 76. Sensitive Output

Runtime deverá aplicar redaction quando output contiver secrets ou dados restritos.

---

# 77. Crash During Execution

Process crash deverá produzir evidence suficiente para Task Recovery.

Exemplo:

```text
process exited unexpectedly
exit_code = ...
```

Isso não necessariamente informa se side effects ocorreram.

---

# 78. Timeout During External Effect

Matar processo por timeout não prova que efeito externo não ocorreu.

Task Runtime continuará aplicando reconciliation quando necessário.

---

# 79. Sandbox Persistence

Sandbox será preferencialmente efêmera.

Persistência entre runs somente quando um caso de uso justificar.

---

# 80. Agent Sandbox

AgentRun inteiro poderá futuramente receber sandbox persistente durante uma Task.

Isso pode ser útil para Development Agent.

Mas não será requisito de todo Agent.

---

# 81. Development Agent Example

Possível fluxo:

```text
Task
  ↓
Development Agent
  ↓
workspace snapshot / authorized workspace
  ↓
shell + filesystem tools
  ↓
SUBPROCESS or SANDBOX
```

A escolha dependerá de trust e Delegation.

---

# 82. Host Execution Use Case

O usuário poderá explicitamente autorizar Agent a trabalhar diretamente em repositório local.

Nesse caso host execution pode ser válida.

A arquitetura não obrigará container para todo desenvolvimento.

---

# 83. Safe Defaults

Defaults deverão favorecer:

- IN_PROCESS somente para Core trusted primitives;
- SUBPROCESS para shell/external executables;
- SANDBOX para generated/downloaded/untrusted code.

Policy poderá especializar.

---

# 84. Execution Configuration

Configurações poderão incluir:

- default sandbox backend;
- global limits;
- allowed interpreters;
- allowed workspace roots;
- network defaults;
- plugin isolation policy.

---

# 85. User Overrides

Usuário poderá alterar algumas policies.

Mas UI deverá deixar claro quando override reduz isolamento.

---

# 86. Audit

Execution deverá permitir correlação:

```text
Task
↓
ToolCall
↓
PolicyDecision
↓
ExecutionMode
↓
Process/Sandbox
↓
ToolResult
```

---

# 87. Observability

Métricas poderão incluir:

- processes started;
- sandbox runs;
- timeouts;
- forced terminations;
- crashes;
- resource usage;
- orphan cleanup;
- isolation failures.

---

# 88. Logging

Logs não deverão incluir automaticamente:

- full environment;
- secrets;
- arbitrary file contents.

---

# 89. Testing

Deverão existir testes para:

- in-process execution;
- subprocess success;
- subprocess timeout;
- cancellation;
- process tree cleanup;
- workspace restriction;
- environment filtering;
- secret non-leakage;
- sandbox unavailable fail-closed;
- generated code requiring isolation;
- worker crash isolation.

---

# 90. Security Tests

Deverão existir testes adversariais para:

- path traversal;
- junction/symlink escape;
- environment secret leakage;
- subprocess spawning child processes;
- network restriction bypass;
- oversized output;
- untrusted Plugin attempting Core access.

---

# 91. Platform Abstraction

Execution architecture deverá preservar interface que permita futuros backends Linux/macOS.

Windows-specific implementations permanecerão atrás de adapters.

---

# 92. Windows-first

MVP poderá utilizar mecanismos Windows específicos onde eles simplifiquem e fortaleçam isolamento.

Portabilidade futura não justifica escolher solução pior no Windows.

---

# 93. Alternatives Considered

## Alternative A — Everything in-process

### Advantages

- extrema simplicidade;
- baixa latência.

### Rejected because

- Core vulnerable a crashes;
- sem isolamento de plugins;
- generated code extremamente perigoso;
- cancellation ruim.

---

## Alternative B — Everything in Docker

### Advantages

- isolamento consistente;
- ambientes reproduzíveis.

### Rejected because

- dependência operacional pesada;
- experiência ruim para desktop comum;
- integração com Windows/filesystem/desktop mais complexa;
- desnecessário para Tools simples.

---

## Alternative C — Run all shell directly on host unrestricted

### Advantages

- máxima compatibilidade.

### Rejected because

- authority excessiva;
- difícil limitar Agents;
- generated code perigoso;
- accidental damage.

Host shell continuará possível, porém scoped e policy-controlled.

---

## Alternative D — Trust LLM-generated code because Sofia generated it

### Rejected because

modelo pode:

- errar;
- sofrer prompt injection;
- produzir código destrutivo;
- importar dependências maliciosas.

Generated code será untrusted by default.

---

# 94. Consequences

## Positive

- protege estabilidade do Core;
- reduz blast radius;
- generated code tratado corretamente;
- Plugins podem ser isolados;
- shell ganha boundaries claros;
- permite host execution pragmática;
- prepara Development Agent;
- melhora cancellation/recovery.

## Negative

- execução possui múltiplos backends;
- Windows sandboxing pode ser complexo;
- workspace/security tests serão difíceis;
- nem toda restrição é tecnicamente perfeita;
- subprocess communication requer contratos.

Esses custos são considerados necessários para o nível de autonomia pretendido.

---

# 95. Architectural Invariants

### INV-001

Generated code é untrusted by default.

### INV-002

SUBPROCESS não é considerado sandbox de segurança.

### INV-003

Tool não reduz unilateralmente isolation requirement.

### INV-004

Policy pode exigir isolamento maior.

### INV-005

Sandbox obrigatório indisponível não faz fallback silencioso para host.

### INV-006

Trust e Authority são conceitos distintos.

### INV-007

Secrets não são herdados indiscriminadamente por subprocesses.

### INV-008

Workspace não concede permission.

### INV-009

Shell é capability privilegiada.

### INV-010

Dependency installation é side effect explícito.

### INV-011

Third-party Plugins são untrusted by default.

### INV-012

Worker crash não deve derrubar Core quando isolamento for possível.

### INV-013

Runtime não mata processo sem ownership verificável.

### INV-014

Isolated execution ainda retorna ToolResult normalizado.

### INV-015

Sandbox não substitui least privilege e Policy.

---

# 96. Deferred Decisions

Serão definidos posteriormente:

- Windows sandbox backend;
- Job Objects usage;
- restricted token/AppContainer usage;
- container support;
- WSL integration;
- worker RPC protocol;
- environment filtering implementation;
- network isolation implementation;
- resource limits;
- process lease/heartbeat;
- trust taxonomy;
- sandbox artifact transfer;
- Development Agent execution environment.

---

# 97. Decision Summary

Sofia's Assistant utilizará três modos fundamentais de execução:

```text
IN_PROCESS
SUBPROCESS
SANDBOX
```

Código confiável e simples poderá executar no Core.

Shell, executáveis externos e workers deverão preferir subprocesses.

Código gerado, baixado ou de terceiros será considerado não confiável por padrão e poderá exigir sandbox.

O modo efetivo será determinado pelo ToolSpec, Policy, resource scope, origem do código e contexto da execução.

Workspace, network, environment, secrets, timeout e resource limits deverão ser explicitamente controláveis.

O objetivo não é executar tudo em sandbox, mas aplicar o **menor nível de confiança e o maior isolamento necessário para cada operação**, sem criar complexidade operacional desnecessária.