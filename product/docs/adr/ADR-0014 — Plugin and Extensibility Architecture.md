# ADR-0014 — Plugin and Extensibility Architecture

**Status:** Accepted  
**Project:** Sofia's Assistant  
**Decision date:** 2026-08-31  
**Scope:** Plugin model, manifests, registration, lifecycle, capabilities, configuration, isolation, compatibility and extension boundaries

---

# 1. Context

O Sofia's Assistant deverá evoluir continuamente com novas capabilities.

Exemplos:

- novas Tools;
- integrações;
- Event Sources;
- Agent Definitions;
- automações;
- capacidades de desktop;
- browser;
- GitHub;
- calendar;
- email;
- smart home;
- productivity;
- development.

Implementar todas essas capacidades diretamente no Sofia Core produziria:

- Core crescente;
- dependências opcionais obrigatórias;
- maior blast radius;
- dificuldade de atualização;
- dificuldade de contribuição;
- baixa capacidade de customização.

Ao mesmo tempo, criar um sistema de Plugins completamente separado dos mecanismos já definidos para Tools, Agents, Events e Policy resultaria em dois runtimes concorrentes.

Os ADRs anteriores já estabeleceram:

- Tool Registry;
- Agent Registry;
- Event Sources;
- PolicyEngine;
- Permission Grants;
- Execution isolation;
- Sofia/root orchestration.

O Plugin system deverá utilizar esses mesmos boundaries.

---

# 2. Decision

O Sofia's Assistant adotará um **Plugin Architecture baseado em composição de capabilities existentes**.

Um Plugin será um pacote extensível capaz de registrar zero ou mais:

```text
Tools
Integrations
Event Sources
Agent Definitions
Configuration schemas
```

Conceitualmente:

```text
Plugin
  │
  ├── ToolSpec(s)
  ├── Integration(s)
  ├── EventSource(s)
  ├── AgentDefinition(s)
  └── Configuration
          │
          ▼
      Sofia Registries
```

Plugins não possuirão runtime privilegiado paralelo.

---

# 3. Fundamental Rule

A regra será:

> **Plugins extend Sofia through existing architectural contracts; they do not bypass them.**

Uma Tool fornecida por Plugin será Tool comum do Tool Runtime.

Um Agent fornecido por Plugin será AgentDefinition comum do Agent Registry.

Um Event Source fornecido por Plugin será EventSource comum do Event Runtime.

---

# 4. Plugin Definition

Um Plugin representa pacote instalável ou carregável de extensão.

Conceitualmente:

```text
Plugin
├── manifest
├── implementation
├── configuration
├── capabilities
└── optional resources
```

O formato físico poderá variar.

---

# 5. Plugin Manifest

Todo Plugin deverá possuir Manifest explícito.

Conceitualmente:

```text
PluginManifest
├── id
├── name
├── version
├── description
├── author
├── compatibility
├── entrypoint
├── provided_capabilities
├── required_permissions
├── configuration_schema
├── dependencies
├── execution_requirements
└── metadata
```

O schema definitivo será definido no Technical Backlog.

---

# 6. Stable Plugin ID

Plugin deverá possuir identificador estável e único.

Exemplo conceitual:

```text
com.example.github
```

ou namespace equivalente.

Display name poderá mudar sem alterar identidade persistente.

---

# 7. Plugin Version

Plugins deverão possuir version identificável.

Version será necessária para:

- compatibility;
- upgrade;
- audit;
- AgentDefinition versioning;
- debugging;
- migration de configuração.

A estratégia de versioning será definida posteriormente.

---

# 8. Plugin Capabilities

Manifest deverá declarar o que Plugin pretende fornecer.

Exemplo:

```text
provides:
  tools:
    - github.get_pull_request
    - github.create_issue

  event_sources:
    - github.pull_requests

  agents:
    - github.review_agent
```

Runtime não deverá descobrir capabilities através de side effects arbitrários durante import.

---

# 9. Registration

Durante activation, Plugin deverá registrar suas extensões através das APIs oficiais.

Exemplo conceitual:

```text
Plugin
   ↓
Plugin Runtime
   ├── Tool Registry
   ├── Agent Registry
   └── Event Runtime
```

Não poderá modificar registries diretamente por acesso a estruturas internas.

---

# 10. Registration Validation

Toda extensão registrada deverá passar pela mesma validation de capabilities built-in.

Plugin Tool deverá possuir ToolSpec válido.

Plugin Agent deverá possuir AgentDefinition válido.

Plugin EventSource deverá possuir contrato válido.

---

# 11. No Plugin Tool Bypass

Não existirá:

```text
Plugin Tool Runtime
```

separado do Tool Runtime principal.

Fluxo será:

```text
Plugin Tool
   ↓
Tool Registry
   ↓
PolicyEngine
   ↓
Execution Boundary
```

---

# 12. No Plugin Agent Bypass

Plugin poderá registrar AgentDefinition.

Mas criação de AgentRun continuará sendo exclusiva de Sofia/root.

Plugin não poderá iniciar seu próprio Agent autonomamente fora do orchestration model.

---

# 13. No Plugin Event Bypass

Plugin EventSource publica External Events normalizados.

Não deverá executar diretamente Tool ou side effect em resposta ao evento.

Fluxo:

```text
Plugin EventSource
      ↓
External Event
      ↓
Event Runtime
      ↓
Task / Attention / Policy
```

---

# 14. Plugin Integration

Uma Integration representa conexão com sistema externo.

Exemplos:

- GitHub;
- Google Calendar;
- Home Assistant;
- Discord.

Plugin poderá encapsular Integration e fornecer Tools/Event Sources relacionados.

---

# 15. Integration Credentials

Plugins não receberão secrets arbitrários do usuário.

Credentials deverão ser obtidas através de abstração controlada.

Fluxo conceitual:

```text
Plugin Integration
      ↓
Credential reference
      ↓
SecretStore
```

---

# 16. Secret Access

Plugin receberá apenas os secrets explicitamente associados à Integration e necessários à operação.

Não deverá conseguir listar ou ler todo SecretStore.

---

# 17. Plugin Permissions

Manifest poderá declarar permissões necessárias.

Exemplo:

```text
requires:
  network.request
  filesystem.read(scope=config)
```

Essa declaração é solicitação de authority.

Não é concessão.

---

# 18. Manifest Is Not Authority

Plugin não poderá escrever:

```text
permissions = ["*"]
```

e obter acesso irrestrito.

Policy/Grants continuam authoritative.

---

# 19. Installation vs Authorization

Instalar Plugin e autorizar Plugin serão operações distintas.

Exemplo:

```text
Plugin installed
Plugin enabled
Plugin configured
Permissions granted
```

são estados diferentes.

---

# 20. Plugin Lifecycle

Baseline conceitual:

```text
DISCOVERED
INSTALLED
DISABLED
ENABLED
DEGRADED
INCOMPATIBLE
FAILED
```

A state machine concreta será definida posteriormente.

---

# 21. Installation

Installation representa disponibilidade física/logical do Plugin.

Ela não inicia automaticamente:

- Event Sources;
- Agents;
- Tools execution;
- permission grants.

---

# 22. Enable

Plugin enabled poderá registrar suas capabilities no runtime.

Mesmo enabled, cada execução continua sujeita ao PolicyEngine.

---

# 23. Disable

Desabilitar Plugin deverá:

- impedir novas execuções;
- retirar/invalidar capabilities registradas;
- parar Event Sources;
- encerrar workers quando apropriado.

Tasks em andamento precisarão ser tratadas conforme lifecycle/recovery semantics.

---

# 24. Disable Does Not Delete Configuration Automatically

Desabilitar não deverá apagar necessariamente:

- configuration;
- authorization history;
- audit;
- user data.

Uninstall terá semantics distintas.

---

# 25. Plugin Uninstall

Uninstall deverá remover o pacote/plugin.

Dados persistentes relacionados poderão exigir policy explícita de retenção.

Não haverá deletion silenciosa universal.

---

# 26. Upgrade

Upgrade de Plugin poderá alterar:

- ToolSpecs;
- AgentDefinitions;
- Event schemas;
- configuration;
- dependencies.

Runtime deverá verificar compatibility antes da activation.

---

# 27. Plugin Compatibility

Manifest deverá declarar compatibility com Sofia's Assistant.

Exemplo conceitual:

```text
requires_core >= X
requires_plugin_api = Y
```

A sintaxe concreta será definida posteriormente.

---

# 28. Plugin API Version

Existirá versionamento do contrato público de Plugins.

Mudança de internals do Core não deverá quebrar Plugins que usem API compatível.

---

# 29. No Internal Imports

Third-party Plugin não deverá depender de imports privados do Sofia Core.

Exemplo proibido:

```python
from sofia.core.internal.task_engine import ...
```

se não fizer parte da Plugin API pública.

---

# 30. Compatibility Failure

Plugin incompatível deverá permanecer desabilitado/incompatible.

Core não deverá tentar carregá-lo parcialmente.

---

# 31. Configuration Schema

Plugin poderá declarar configuration schema.

Isso permitirá:

- validation;
- UI generation;
- default values;
- migration;
- CLI futura.

---

# 32. Plugin Configuration

Configuração não sensível poderá permanecer no Operational Store ou storage específico controlado pelo Core.

Secrets permanecerão no SecretStore.

---

# 33. Configuration Validation

Plugin não deverá receber configuração inválida.

Validation ocorrerá antes da activation quando possível.

---

# 34. Configuration Migration

Upgrade poderá exigir migration de configuração.

Plugin API deverá permitir estratégia controlada.

Migration não deverá executar arbitrary side effects fora do próprio configuration scope.

---

# 35. Plugin State

Plugins poderão possuir estado operacional próprio.

Esse estado deverá utilizar storage boundary fornecido pelo Core ou mechanism explicitamente aprovado.

Não deverão criar arquivos arbitrários espalhados pelo host por padrão.

---

# 36. Plugin Data Namespace

Operational Store poderá fornecer namespace por Plugin.

Exemplo conceitual:

```text
plugin_state
  plugin_id
  key/value or structured records
```

ou mecanismo mais robusto.

A implementação é deferred.

---

# 37. Plugin Database Access

Plugin não terá acesso direto ao SQLite interno do Assistant.

Se precisar persistir estado, utilizará API/abstração fornecida.

---

# 38. Memory Access

Plugin não deverá acessar Sofias Memory diretamente por padrão.

Quando capability exigir memória:

```text
Plugin Tool/Agent
   ↓
runtime memory interface
   ↓
Policy
   ↓
MemoryProvider
```

---

# 39. Plugin Trust

Plugins serão classificados como untrusted by default.

Especialmente third-party Plugins.

Trust poderá influenciar execution mode.

---

# 40. Built-in Extensions

Capacidades distribuídas com o Sofia's Assistant poderão usar o mesmo Plugin model mesmo sendo trusted.

Isso ajuda manter boundaries consistentes.

---

# 41. Built-in Does Not Mean Unlimited Authority

Plugin built-in ainda estará sujeito ao PolicyEngine.

Trust afeta isolation.

Authority continua separada.

---

# 42. Plugin Execution Modes

Plugin implementation poderá executar:

```text
IN_PROCESS
SUBPROCESS
SANDBOX
```

conforme ADR-0013.

---

# 43. In-process Plugin

Somente Plugin explicitamente confiável e compatível deverá executar dentro do Core.

Isso poderá incluir extensões built-in.

---

# 44. Subprocess Plugin Worker

Third-party Plugin poderá preferencialmente executar em worker separado.

Arquitetura:

```text
Sofia Core
    │
Plugin RPC
    │
Plugin Worker
```

---

# 45. Plugin Worker Authority

Worker não recebe authority global.

Cada request deverá carregar execution context limitado.

---

# 46. Worker Crash

Plugin worker crash deverá:

- marcar Plugin degraded;
- falhar execuções afetadas;
- preservar Core;
- permitir restart quando apropriado.

---

# 47. Sandbox Plugin

Plugins de risco elevado poderão exigir sandbox.

Se sandbox obrigatório estiver indisponível, não haverá fallback silencioso para in-process.

---

# 48. Plugin Dependencies

Plugin poderá depender de bibliotecas próprias.

Dependências não deverão contaminar environment principal quando isso puder gerar conflito.

Workers/sandbox poderão possuir environment específico.

---

# 49. Dependency Installation

Plugin não deverá executar `pip install` no environment global do Core durante activation.

Installation de dependencies deverá ocorrer por mecanismo controlado.

---

# 50. Core Dependency Hygiene

O Core não deverá incorporar dependency pesada apenas porque um Plugin opcional precisa dela.

Esse é um dos objetivos principais do sistema de Plugins.

---

# 51. Tool Namespaces

Plugin deverá preferir namespace próprio ou domínio semântico consistente.

Exemplo:

```text
github.create_issue
github.get_pull_request
```

Evitar collisions como:

```text
create
read
execute
```

---

# 52. Agent Namespaces

AgentDefinitions também deverão possuir IDs estáveis.

Exemplo:

```text
github.review
development.repository
research.web
```

---

# 53. Event Type Namespaces

External Event types fornecidos por Plugin deverão ser identificáveis e estáveis.

Exemplo:

```text
github.pull_request.updated
```

ou convenção equivalente.

---

# 54. Collision Handling

Registration collision deverá falhar explicitamente.

Não haverá:

```text
last plugin wins
```

---

# 55. Capability Dependencies

Plugin poderá exigir capabilities de outro Plugin/Core.

Exemplo:

```text
requires tool: browser.navigate
```

Dependency graph deverá ser validado.

---

# 56. Plugin-to-Plugin Direct Calls

Plugins não deverão chamar internals uns dos outros diretamente como padrão.

Preferir contracts registrados:

- Tool;
- Event;
- Integration API;
- shared public service.

---

# 57. Optional Dependencies

Plugin poderá declarar dependency opcional.

Ausência poderá degradar capability específica sem invalidar Plugin inteiro quando possível.

---

# 58. Circular Dependencies

Dependency cycles deverão ser detectados.

Plugin activation não deverá entrar em loop.

---

# 59. Plugin Activation Order

Runtime poderá calcular order baseado em dependencies.

A implementação concreta será definida depois.

---

# 60. Event Sources from Plugins

Plugin EventSource só inicia se:

- Plugin enabled;
- configuration válida;
- permissions suficientes;
- dependencies disponíveis.

---

# 61. Agent Definitions from Plugins

Plugin AgentDefinition só estará disponível se required Tools/providers/capabilities estiverem disponíveis.

---

# 62. Partial Availability

Plugin poderá estar enabled mas parcialmente degraded.

Exemplo:

```text
GitHub Plugin:
  read tools = available
  write tools = unavailable
  EventSource = degraded
```

Runtime deverá representar capability availability individualmente.

---

# 63. Plugin Health

Plugin poderá reportar health.

Conceitualmente:

```text
HEALTHY
DEGRADED
FAILED
```

Health não substitui validation/Policy.

---

# 64. Health Checks

Workers/Integrations poderão oferecer health checks.

Core deverá evitar health polling excessivo.

---

# 65. Plugin Startup Failure

Falha de Plugin opcional não deverá impedir Sofia Core de iniciar.

Core deverá entrar em degraded capability state.

---

# 66. Essential Plugins

Algumas extensões future podem ser marcadas como required pelo produto/configuração.

Nesse caso failure poderá afetar readiness específica.

Mas não será baseline para third-party Plugins.

---

# 67. Plugin Commands

Plugins não terão permission para registrar comandos que alterem Core internals diretamente.

Toda operação deverá passar por APIs públicas e Policy aplicável.

---

# 68. UI Extensions

Plugin UI extensibility poderá existir futuramente.

Não será parte obrigatória do MVP do Plugin system.

Se implementada, deverá evitar permitir arbitrary UI code com acesso privilegiado ao Desktop Client.

---

# 69. UI Contribution Model

Possibilidades futuras incluem:

- settings panels;
- status cards;
- capability views.

A estratégia concreta deverá ter ADR próprio se introduzir risco/complexidade significativa.

---

# 70. Plugin Distribution

Marketplace/distribution pública não faz parte do MVP.

Inicialmente Plugins poderão ser:

- built-in;
- local;
- developer-installed.

---

# 71. Local Development Plugins

O sistema deverá permitir desenvolvimento local de Plugin com reload/restart controlado.

Hot reload completo não é requisito inicial.

---

# 72. Plugin Packaging

Formato poderá ser:

- Python package;
- directory bundle;
- signed archive;
- worker package.

A decisão concreta é deferred.

---

# 73. Signing

Plugin signing/trust chain poderá ser introduzido futuramente para distribuição.

Não será requisito inicial.

---

# 74. Plugin Source Provenance

Runtime deverá poder identificar de onde Plugin foi instalado.

Exemplos:

```text
built-in
local path
official registry
third-party source
```

Isso poderá influenciar trust UX.

---

# 75. Plugin Security Review

Third-party Plugin com capabilities sensíveis deverá expor ao usuário:

- permissions solicitadas;
- network access;
- filesystem scopes;
- execution mode;
- Agents/Event Sources fornecidos.

---

# 76. Permission Changes on Upgrade

Se nova versão solicitar authority adicional, upgrade não deverá concedê-la automaticamente.

Exemplo:

```text
v1 required network.read

v2 additionally requires filesystem.write
```

Novo Grant deverá ser avaliado explicitamente.

---

# 77. Tool Changes on Upgrade

Se Tool muda side effects ou required permissions, runtime deverá revalidar configuração/authority.

Version update não herda automaticamente assumptions antigas.

---

# 78. Plugin Revocation

Usuário poderá revogar Grants concedidos ao Plugin sem necessariamente desinstalá-lo.

Plugin poderá permanecer funcional parcialmente.

---

# 79. Plugin Subject

Plugin poderá ser subject de Grants quando fizer sentido.

Porém Tool execution ainda poderá ocorrer em nome de AgentRun/Task com interseção de authority.

---

# 80. Effective Plugin Authority

Conceitualmente:

```text
Plugin allowed authority
      ∩
Task/Agent authority
      ∩
Policy
      =
effective execution authority
```

Plugin-level Grant nunca amplia authority da Task.

---

# 81. Agent Provided by Plugin

Authority de AgentDefinition não vem do Plugin manifest.

AgentRun recebe authority derivada da root/Delegation.

---

# 82. EventSource Provided by Plugin

Authority para observar recursos vem de Grants apropriados.

Não vem da instalação do Plugin.

---

# 83. Data Locality

Plugins deverão respeitar data locality.

Plugin não poderá enviar dados a serviço externo apenas porque possui código para isso.

Network Tool/Integration deverá passar pelos boundaries apropriados.

---

# 84. Prompt Injection

Plugin que consome dados externos continuará tratando esse conteúdo como data.

External payload não poderá modificar Policy/Grants.

---

# 85. Plugin Logging

Plugins deverão utilizar logging API controlada quando possível.

Logs deverão respeitar redaction e não conter secrets indiscriminadamente.

---

# 86. Plugin Audit

Ações de Plugin deverão ser correlacionáveis com:

```text
Plugin
↓
Task / AgentRun
↓
ToolCall
↓
PolicyDecision
↓
Execution
```

---

# 87. Plugin Observability

Core poderá registrar:

- activation failures;
- health;
- Tool execution counts;
- EventSource status;
- worker crashes;
- compatibility errors.

---

# 88. Plugin Resource Limits

Worker Plugin poderá receber limites de:

- memory;
- CPU;
- process count;
- timeout.

A capacidade concreta dependerá do execution backend.

---

# 89. Plugin Shutdown

Durante Core shutdown:

- Event Sources deverão parar;
- workers deverão encerrar;
- state necessário deverá ser persistido.

Plugin não deverá impedir shutdown indefinidamente.

---

# 90. Plugin Recovery

Após crash/restart:

- enabled state deverá ser recuperado;
- configuration validada;
- workers recriados;
- Event Sources reiniciados;
- capabilities re-registradas.

Tasks interrompidas seguem ADR-0010.

---

# 91. Plugin State Migration

Upgrade de Plugin poderá migrar seu próprio state.

Migration deverá ser versionada e limitada ao namespace do Plugin.

---

# 92. Removal of Capability

Se upgrade remover Tool usada por Task persistente:

- Task Recovery deverá detectar indisponibilidade;
- replan/fail/wait conforme semantics.

Não executar Tool inexistente por stale handler.

---

# 93. Plugin API Stability

Public Plugin API deverá ser pequena e deliberada.

Não expor todo Sofia Core apenas para facilitar extensões.

---

# 94. Principle of Minimal Surface

Quanto menor a Plugin API, menor:

- coupling;
- security surface;
- compatibility burden.

Novas APIs devem ser adicionadas somente quando capability não pode ser representada pelos contracts existentes.

---

# 95. Service Access

Plugins poderão necessitar de serviços controlados como:

- logging;
- configuration;
- Secret references;
- HTTP client;
- artifact storage.

Esses serviços deverão ser fornecidos via restricted Plugin Context, não Service Locator irrestrito.

---

# 96. Plugin Context

Conceitualmente:

```text
PluginContext
├── plugin identity
├── configuration
├── allowed service interfaces
├── registration APIs
└── lifecycle APIs
```

Não deverá expor todo Core container.

---

# 97. No Arbitrary Monkey Patching

Plugins não poderão depender arquiteturalmente de monkey patching do Core.

Esse comportamento será considerado unsupported.

---

# 98. No Global Mutable Registry Access

Plugins registrarão através de APIs.

Não receberão referência mutável irrestrita aos registries internos.

---

# 99. Built-in Capability Migration

Algumas capabilities inicialmente built-in poderão futuramente ser transformadas em Plugins sem alterar contracts de domínio.

Essa possibilidade é uma vantagem do modelo escolhido.

---

# 100. Plugin vs Integration

Plugin é pacote.

Integration é capability/conector.

Um Plugin poderá conter nenhuma, uma ou várias Integrations.

Não serão sinônimos.

---

# 101. Plugin vs Agent

Plugin não é Agent.

Plugin pode fornecer AgentDefinition.

---

# 102. Plugin vs Tool

Plugin não é Tool.

Plugin pode fornecer Tools.

---

# 103. Plugin vs EventSource

Plugin não é EventSource.

Plugin pode fornecer Event Sources.

---

# 104. Example — GitHub Plugin

Conceitualmente:

```text
Plugin:
  github

Integration:
  GitHub API

Tools:
  github.get_repository
  github.get_pull_request
  github.create_issue
  github.comment_pull_request

Event Sources:
  github.pull_request_events

Agent Definitions:
  optional github.review

Configuration:
  account/integration settings

Secrets:
  reference to GitHub credential
```

Todas as operações continuam usando runtime normal.

---

# 105. Example — Home Assistant Plugin

```text
Plugin:
  home_assistant

Integration:
  Home Assistant

Tools:
  home.get_state
  home.turn_on
  home.turn_off

Event Sources:
  home.state_changed
```

`home.turn_off` continua sujeito a Policy.

---

# 106. Example — Development Plugin

Poderá oferecer:

```text
Tools:
  git.*
  test.*
  repository.*

Agent:
  development.repository
```

Shell continuará Tool do runtime ou capability compartilhada, não implementação privada escondida dentro do Agent.

---

# 107. Installation Safety

Installation de Plugin não deverá executar entrypoint arbitrário antes de validação básica do Manifest quando tecnicamente possível.

---

# 108. Static Manifest Inspection

Quando formato permitir, runtime deverá conseguir inspecionar Manifest antes de executar código do Plugin.

Isso ajuda apresentar permissions e compatibility.

---

# 109. Malformed Plugin

Plugin com Manifest inválido deverá ser rejeitado antes da activation.

---

# 110. Unknown Manifest Fields

Unknown critical fields/version incompatível deverão produzir erro conservador.

Não assumir semantics de segurança desconhecidas.

---

# 111. Plugin Isolation Failure

Se Plugin exige subprocess/sandbox e backend não estiver disponível:

```text
Plugin cannot safely activate
```

Não fazer fallback automático para in-process.

---

# 112. Plugin Update Failure

Se nova versão falhar activation, runtime deverá evitar deixar registry parcialmente atualizado.

Idealmente activation será transacional do ponto de vista lógico.

---

# 113. Activation Transaction

Conceitualmente:

```text
validate
↓
prepare registrations
↓
start required workers
↓
commit activation
```

Se falhar:

```text
rollback registrations
```

A implementação concreta é deferred.

---

# 114. Event Schema Evolution

Plugin que altera External Event schema deverá versionar mudança incompatível.

Consumers não devem receber payload semanticamente diferente sob mesmo contrato sem compatibility strategy.

---

# 115. Tool Schema Evolution

Mudança incompatível em Tool input/output deverá resultar em nova versão/contrato compatível com a política de versioning adotada.

---

# 116. Agent Definition Evolution

AgentRun deverá registrar AgentDefinition/version usada.

Upgrade futuro não altera retrospectivamente execuções anteriores.

---

# 117. Testing

Plugin runtime deverá possuir testes para:

- valid registration;
- invalid manifest;
- collisions;
- enable/disable;
- compatibility rejection;
- permission isolation;
- worker crash;
- partial availability;
- configuration validation;
- upgrade;
- capability removal;
- dependency graph;
- circular dependency detection.

---

# 118. Plugin Contract Test Kit

Futuramente poderá existir kit para autores validarem:

- ToolSpecs;
- Event Sources;
- AgentDefinitions;
- Manifest;
- compatibility.

Não é requisito inicial, mas API deverá permitir.

---

# 119. Security Tests

Deverão existir testes adversariais para Plugins tentando:

- acessar SecretStore inteiro;
- importar Core internals;
- registrar Tool com collision;
- ampliar permission;
- executar side effect durante registration;
- escapar workspace;
- enviar dados sem authority;
- iniciar Agent por conta própria.

---

# 120. Alternatives Considered

## Alternative A — No Plugin System

### Advantages

- Core simples inicialmente.

### Rejected because

o roadmap possui muitas capabilities opcionais e integrações.

Sem Plugin boundary o Core tenderia a crescer indefinidamente.

---

## Alternative B — Plugins Receive Full Core Object

### Advantages

- máxima flexibilidade;
- desenvolvimento rápido.

### Rejected because

- coupling extremo;
- impossível preservar segurança;
- difícil manter compatibility;
- plugins podem burlar Policy.

---

## Alternative C — Separate Plugin Runtime with Its Own Tool/Event Model

### Advantages

- independência.

### Rejected because

criaria dois sistemas de:

- Tools;
- authorization;
- Agents;
- events;
- audit.

---

## Alternative D — Every Plugin Runs in-process

### Advantages

- simples;
- baixo overhead.

### Rejected because

third-party code poderia derrubar ou comprometer o Core.

---

## Alternative E — Every Plugin Runs in a container

### Advantages

- isolamento uniforme.

### Rejected because

- complexidade excessiva;
- pior desktop experience;
- desnecessário para extensões confiáveis simples.

Isolation será risk-based.

---

# 121. Consequences

## Positive

- Core permanece enxuto;
- extensões reutilizam contracts existentes;
- nenhuma autorização paralela;
- Plugins podem fornecer Tools, Agents e Events;
- third-party code pode ser isolado;
- dependencies opcionais ficam fora do Core;
- upgrades podem ser validados;
- futura distribuição de Plugins é possível.

## Negative

- Plugin API precisa estabilidade;
- lifecycle/compatibility adicionam complexidade;
- worker protocol poderá ser necessário;
- migrations/config upgrades precisam disciplina;
- partial availability precisa ser representada;
- ecosystem security exigirá atenção contínua.

Esses custos são considerados adequados para a evolução prevista.

---

# 122. Architectural Invariants

### INV-001

Plugin estende Sofia somente através de contracts públicos.

### INV-002

Plugin não possui Tool Runtime próprio.

### INV-003

Plugin não possui Agent orchestration próprio.

### INV-004

Plugin EventSource não executa side effects diretamente.

### INV-005

Manifest nunca concede authority.

### INV-006

Installation e authorization são estados distintos.

### INV-007

Third-party Plugins são untrusted by default.

### INV-008

Plugin não acessa Operational DB diretamente.

### INV-009

Plugin não recebe SecretStore irrestrito.

### INV-010

Plugin Tool passa pelo mesmo PolicyEngine das Tools built-in.

### INV-011

Plugin Agent só é instanciado por Sofia/root.

### INV-012

Plugin Event Source precisa de authority para observar recursos protegidos.

### INV-013

Registration collision nunca é sobrescrita silenciosamente.

### INV-014

Incompatible Plugin não é carregado parcialmente.

### INV-015

Isolation requirement não pode ser reduzido silenciosamente.

### INV-016

Upgrade nunca concede nova authority automaticamente.

### INV-017

Plugin API deve permanecer menor que Core internals.

### INV-018

Trust não equivale a Authority.

---

# 123. Deferred Decisions

Serão definidos posteriormente:

- Plugin Manifest format;
- Plugin API versioning;
- packaging format;
- installation directory;
- discovery mechanism;
- dependency environment;
- Plugin worker RPC;
- PluginContext API;
- plugin state storage;
- configuration migration API;
- hot reload;
- signing;
- official registry/marketplace;
- UI extension model;
- Plugin SDK;
- compatibility test kit.

---

# 124. Decision Summary

Sofia's Assistant adotará uma arquitetura de Plugins baseada na composição dos contracts já existentes.

Um Plugin poderá fornecer:

```text
Tools
Integrations
Event Sources
Agent Definitions
Configuration
```

Essas extensões serão registradas nos runtimes oficiais do Core e permanecerão sujeitas a:

- PolicyEngine;
- Grants;
- root orchestration;
- Tool Runtime;
- Event Runtime;
- execution isolation;
- audit.

Third-party Plugins serão untrusted by default e poderão executar em subprocess ou sandbox.

Manifest descreve capabilities e requisitos, mas nunca concede authority.

Installation, enablement, configuration e authorization serão estados distintos.

O Plugin system terá uma API pública deliberadamente pequena para preservar segurança, estabilidade e compatibility do Sofia Core.