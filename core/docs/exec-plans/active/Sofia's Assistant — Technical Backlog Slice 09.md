# Sofia's Assistant — Technical Backlog Slice 09

**Nome operacional:** Core Runtime Configuration & Intelligent AI Routing  
**Escopo:** SA-B035 + SA-B036 + SA-B037  
**Gates-alvo:** I14 — Core Runtime Ready; I15 — Intelligent AI Routing  
**Status:** APPROVED  
**Projeto:** Sofia's Assistant  
**Baseline remoto auditado:** `aa273a9eed7643b89ba317da95387cd26d7ca77e`  
**Release baseline:** `v0.1.0` — publicado  
**Último Slice concluído:** Slice 08 — Recovery & MVP Release — COMPLETED / REMOTE VERIFIED  
**Fonte:** PRD + ADR-0004 + Architecture Review Amendments + CLAUDE.md + decisões pós-MVP sobre configuração, multi-provider e human runtime

---

# 1. Objetivo

O Slice 09 inicia a fase pós-MVP.

O `v0.1.0` provou o kernel técnico. Agora o Core precisa se tornar operacionalmente configurável e pronto para sustentar uma experiência humana real sem depender de hardcodes de provider/model ou de edição frequente do `.env`.

```text
Gate I14
Core inicia como processo real e configurável
↓
Gate I15
Core seleciona providers/modelos dinamicamente por profile/capability
↓
Core pronto para receber o Dashboard humano
```

O Slice possui dois Runs:

```text
Slice 09 — Core Runtime Configuration & Intelligent AI Routing
│
├── Run 1 — Gate I14
│     ├── SA-B035 Runtime Configuration & Provider Bootstrap
│     └── SA-B036 Production Core Host
│
└── Run 2 — Gate I15
      └── SA-B037 Dynamic Model Catalog & Inference Profiles
```

O novo Dashboard/Desktop UX fica fora deste Slice.

---

# 2. Estado de partida

O baseline remoto oficial é:

```text
aa273a9eed7643b89ba317da95387cd26d7ca77e
```

O produto já possui:

```text
Conversation
Realtime Voice
ContextBuilder
Sofias Memory integration
Policy / Grants / Confirmations
Tool Runtime
Task Runtime
Agent Runtime
Execution Isolation
Scheduler
Notifications
Filesystem
Shell
Web
Vision
Audit
Recovery
Desktop Client
CapabilityRouter
ModelRegistry
OpenAI adapter
```

Também já está provado que uma mesma Sofia/Conversation pode usar bindings de provider/model diferentes sem alterar identidade ou autoridade da conversa.

O gap atual é:

```text
bootstrap/configuração ainda rígidos
+
Core production host incompleto
+
model registry apenas process-local
+
routing pouco configurável por workload/profile
+
falta contrato operacional para o futuro Dashboard
```

---

# 3. Dependências documentais

Antes da implementação do Run 1 devem existir e estar aprovados:

```text
CLAUDE.md

Architecture Review Amendment 0003
AI Runtime Configuration, Secrets and Dynamic Routing

Sofia's Assistant — AI Runtime Configuration Contract v1
```

Este Slice pode ser aprovado antes deles, mas a implementação não deve começar até esses documentos existirem.

Precedência:

```text
instrução explícita do usuário
↓
active Slice
↓
Architecture Review Amendment 0003
↓
AI Runtime Configuration Contract v1
↓
accepted ADRs
↓
PRD
↓
existing implementation
```

---

# 4. Invariantes

Este Slice não substitui a arquitetura de AI existente.

```text
CapabilityRouter       permanece
ModelRegistry          permanece
Provider Adapters      permanecem
Conversation authority permanece no Core
Sofias Memory          permanece Long-Term Memory authority
UI                     permanece Client
```

Regra fundamental:

```text
Domain requests capabilities/profile.
Routing policy selects compatible execution.
CapabilityRouter validates/selects.
Provider performs inference.
```

Hard requirements sempre vencem preferences.

Nenhum override, profile binding, fallback ou canonical model pode ignorar:

```text
required capabilities
data locality
policy
execution compatibility
```

Secrets podem vir de `.env`/environment por decisão explícita do produto, mas não devem virar rows plaintext no Operational Store nem ser lidos diretamente por adapters.

---

# 5. Modelo de execução

Cada Run segue:

```text
pre-flight
↓
read CLAUDE.md
↓
read active Slice
↓
read Amendment 0003 + Runtime Configuration Contract
↓
Reference Harvest
↓
audit current code
↓
implement minimum coherent package
↓
targeted tests
↓
vertical Gate tests
↓
full regression
↓
quality
↓
commit
↓
push
↓
remote CI
↓
independent review
↓
Gate closure
```

Não iniciar Run 2 antes do fechamento de I14, salvo autorização explícita.

---

# 6. Reference Harvest obrigatório

Cada Run começa com harvest dirigido.

Referências principais:

```text
Mark LI
Brahma AI
Sofia's Assistant current implementation
```

Quando útil:

```text
OpenAI-compatible configuration conventions
Ollama/OpenRouter model discovery patterns
provider SDK model listing mechanisms
```

Registrar:

```text
REUSED
ADAPTED
REJECTED
```

Observar especialmente:

- runtime launcher/process host;
- provider configuration;
- model discovery;
- model selection;
- workload specialization;
- fallback;
- health;
- diagnostics.

Não importar:

- direct LLM → Tool execution;
- provider lock-in;
- UI as authority;
- weak local trust;
- insecure secret handling.

---

# 7. Resume Capsule

Se houver interrupção, atualizar este Slice com:

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

---

# 8. Gate I14 — Core Runtime Ready

**Escopo:** SA-B035 + SA-B036.

Objetivo:

```text
configure
↓
start Core process
↓
bootstrap provider
↓
bootstrap Memory
↓
bind authenticated local API
↓
report health/readiness
↓
remain alive
↓
shutdown gracefully
```

## SA-B035 — Runtime Configuration & Provider Bootstrap

Materializar configuration boundary real para Windows local, Linux local, VPS, Docker e systemd.

Baseline conceitual:

```env
# Core
SOFIA_CORE_HOST=127.0.0.1
SOFIA_CORE_PORT=8989

# Canonical/default LLM
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-change-me
LLM_MODEL=example-model

# Sofias Memory
SOFIAS_MEMORY_ENABLED=true
SOFIAS_MEMORY_BASE_URL=https://example.invalid
SOFIAS_MEMORY_API_KEY=change-me
```

Os nomes finais podem ser refinados pelo Amendment/Contract.

Precedência:

```text
process environment
    overrides
.env
    overrides
code defaults
```

Não fazer busca arbitrária por vários `.env`.

`.env` permanece git-ignored. `.env.example` contém apenas placeholders.

---

# 9. Secret bridge

Permitir API keys em `.env` não autoriza provider adapters a chamar `os.getenv()` diretamente.

Fluxo:

```text
.env / process environment
        ↓
configuration / secret bridge
        ↓
SecretService
        ↓
Provider / Integration Adapter
```

O nome concreto pode ser `EnvironmentSecretStore`, `EnvironmentSecretSource` ou equivalente.

Objetivos:

- manter `SecretService` Core-wide;
- suportar Windows e Linux;
- permitir futura troca por secret store criptografado;
- não persistir API keys em plaintext no SQLite;
- não vazar secrets em logs/Audit.

---

# 10. Canonical/default model

`LLM_MODEL` significa:

```text
bootstrap/default model
```

e não:

```text
universal routing model
```

Pode servir para:

- first boot;
- default profile ainda não configurado;
- compatible fallback;
- diagnostics/setup.

O canonical model só pode ser escolhido se satisfizer os hard requirements.

---

# 11. Provider bootstrap

Run 1 deve materializar composition production-grade para o provider canônico.

Fluxo:

```text
provider configuration
↓
Adapter
↓
ProviderBinding
↓
ModelRegistration
↓
CapabilityRouter
```

Reutilizar o OpenAI adapter existente.

Se `LLM_BASE_URL` exigir evolução para OpenAI-compatible endpoints, fazer isso pelo Adapter boundary.

Não espalhar base URL, API shape ou SDK details pelo domínio.

O Core deve ficar arquiteturalmente pronto para:

```text
OpenAI
OpenAI-compatible cloud providers
OpenAI-compatible local endpoints
```

sem assumir compatibilidade perfeita.

---

# 12. Sofias Memory bootstrap

Configuração real deve suportar:

```text
SOFIAS_MEMORY_ENABLED
SOFIAS_MEMORY_BASE_URL
SOFIAS_MEMORY_API_KEY
```

O Adapter continua consumindo secrets através do `SecretService`.

Memory continua degradável:

```text
Memory unavailable ≠ Core dead
```

salvo incompatibilidade explicitamente fatal no contrato.

---

# 13. Config validation

Startup deve falhar claramente para configuração estruturalmente inválida.

Exemplos:

- invalid Core port;
- malformed URL;
- blank required provider/model;
- invalid timeout;
- invalid data directory.

Secret ausente deve resultar em health/config status claro conforme o subsystem.

Nunca logar secret value.

---

# 14. SA-B036 — Production Core Host

Criar entrypoint real de processo para Sofia Core.

Nome conceitual preferido:

```text
sofia-core
```

Responsabilidades:

1. carregar RuntimeConfig;
2. construir SecretService;
3. construir AI/provider composition;
4. construir Memory integration;
5. construir `SofiaCore`;
6. iniciar `SofiaCore`;
7. iniciar `LocalClientBoundary`;
8. registrar readiness;
9. permanecer vivo;
10. tratar shutdown;
11. parar LocalClientBoundary;
12. parar SofiaCore;
13. retornar exit code coerente.

Não colocar domain logic no host.

Lifecycle:

```text
process start
↓
config load
↓
Core composition
↓
Core.start()
↓
LocalClientBoundary.start()
↓
READY
↓
wait for shutdown signal
↓
LocalClientBoundary.stop()
↓
Core.stop()
↓
exit 0
```

Cobrir Windows-first sem impedir Linux:

```text
Ctrl+C / KeyboardInterrupt
SIGINT
SIGTERM
```

Preservar single-instance protection.

Bind default continua loopback only.

Não usar `0.0.0.0` para facilitar VPS.

---

# 15. Client credential no Run 1

A credencial efêmera do Local Client Boundary não deve ser confundida com API key de LLM.

Neste Slice:

- não transformar essa credential em secret permanente de `.env`;
- não enfraquecer localhost authentication;
- não projetar toda a UX de pairing do futuro Dashboard;
- permitir apenas diagnostics/dev surface controlada se necessária para human smoke.

A UX final de Core+Desktop attach/start fica para o Slice seguinte.

---

# 16. Gate I14 human smoke

Ao final do Run 1 deve ser possível executar algo equivalente a:

```powershell
cd core
copy .env.example .env
# edit .env
uv run sofia-core
```

Esperado:

```text
Core inicia
porta loopback é aberta
health/readiness ficam disponíveis
processo permanece vivo
Ctrl+C encerra limpo
```

O novo Dashboard ainda não é requisito.

Criar Gate test:

```text
tests/integration/gate/test_gate_i14_core_runtime.py
```

Cobrir pelo menos:

- env precedence;
- `.env` load explícito;
- secret redaction;
- provider bootstrap;
- invalid config;
- Memory enabled/disabled;
- Core host startup;
- LocalClientBoundary;
- readiness;
- graceful shutdown;
- failed-start cleanup;
- duplicate instance;
- no external bind default.

Acceptance:

```text
[ ] .env/environment configuration real
[ ] SecretService-compatible env secret source
[ ] canonical/default model bootstrap
[ ] OpenAI production composition
[ ] Sofias Memory production composition
[ ] persistent Core host
[ ] authenticated loopback boundary
[ ] health/readiness
[ ] graceful shutdown
[ ] Windows-first
[ ] Linux-portable
[ ] README run instructions corretos
[ ] Gate I14 tests green
[ ] full regression green
[ ] remote CI green
```

Fechamento:

```text
GATE I14 CLOSED — REMOTE VERIFIED
```

---

## Gate I14 — closure ledger

```text
Gate: I14 — Production Core Runtime
Status: CLOSED — REMOTE VERIFIED

Baseline: f64870daca04aec09389665fffec2d31161c7ca8

Feature commits:
  3252194 feat(config): add production runtime configuration bootstrap seams
  817b791 feat(host): add standalone Core process host and production AI/secret composition

Test commits:
  75724ab test(host): validate Gate I14 runtime configuration and lifecycle

Docs commits:
  24d1f40 docs: document sofia-core host setup and update .env.example
  967fec7 docs(plan): record Gate I14 ledger — implemented, awaiting remote verification

Final HEAD: 967fec77074e4c1d5e788285a64b0dd11b64ba3c
Remote CI: run 35020701564 — SUCCESS
  https://github.com/kallbuloso/sofias_assistant/actions/runs/35020701564
  Lint / Check formatting / Type check / Test / Desktop package baseline /
  Packaged executable smoke — all green on windows-latest.

Tests:
  - tests/unit/host/test_config.py (SA-B035 bootstrap key set, precedence,
    validation, boolean parsing, non-loopback rejection)
  - tests/unit/host/test_secret_bridge.py (known env->SecretRef mappings,
    secret-source diagnostics)
  - tests/unit/secrets/test_environment_store.py (EnvironmentSecretStore /
    LayeredSecretStore precedence, redaction, no arbitrary enumeration)
  - tests/integration/gate/test_gate_i14_core_runtime.py (16 scenarios:
    env-file + process-env precedence, no implicit `.env` discovery,
    provider bootstrap + SecretService bridge end-to-end through the real
    OpenAI adapter with a fake transport, invalid-configuration fail-fast
    with zero side effects, Memory disabled/degraded, readiness
    credential-state distinction, graceful shutdown, failed-start cleanup,
    duplicate-instance rejection, loopback-only default)
  - full existing regression suite (Gates I2-I13)

Quality: ruff check/format, mypy (src+tests), pytest — all green locally.

Architecture findings: none requiring an Amendment/Contract change.
  `SofiaCore`'s existing `secret_store_factory` and
  `conversation_dependencies_factory` seams, and `LocalClientBoundary`'s
  `app_factory` seam, were sufficient to compose the whole production host
  without modifying `core/core.py`.

Deferred (explicitly out of Gate I14 scope, per Slice SS "Não escopo"):
  persistent ProviderConfiguration/ModelCatalogEntry, capability
  provenance, Inference Profiles, ProfileModelBinding, AI Configuration
  API, routing preview, Dashboard — all Gate I15.

Known limitations:
  - Human smoke could not script a literal OS-level Ctrl+C keypress from
    this non-interactive environment (Windows console signal delivery to
    a detached child process is not reliably scriptable); the real
    `sofia-core` executable was proven to start, bind loopback, serve the
    authenticated readiness endpoint, and stay alive. The graceful
    shutdown code path itself (signal handler -> shutdown_event ->
    boundary.stop() -> core.stop() -> exit 0) is fully covered
    deterministically by
    test_gate_i14_core_runtime.py::test_graceful_shutdown_stops_boundary_and_core.
  - `CoreApiClient.stream_text` (existing Desktop convenience helper,
    unrelated to this Gate) still hardcodes `local_only` locality; it is
    unchanged here and remains a Slice 10 UX concern.

Blockers: none.
```

---

# 17. Gate I15 — Intelligent AI Routing

**Escopo:** SA-B037.

Objetivo:

```text
provider configurations
+
dynamic model catalog
+
capability metadata
+
inference profiles
+
ordered model bindings
+
fallback
+
health/availability
+
routing API
+
runtime integration
```

O objetivo não é escolher hoje o melhor modelo do mercado.

O objetivo é fazer com que essa escolha deixe de ser hardcoded.

---

# 18. ProviderConfiguration

Persistir configuração não secreta necessária para providers.

Conceitualmente:

```text
ProviderConfiguration
├── id
├── display_name
├── adapter_type
├── base_url
├── enabled
├── execution_location
├── credential_ref/source
├── created_at
└── updated_at
```

Regras:

- API key não entra plaintext nessa tabela;
- canonical provider do `.env` pode materializar/seedar configuração inicial idempotente;
- provider configuration deve poder ser lida pelo futuro Dashboard;
- provider config inválida não pode ser publicada ao runtime.

---

# 19. ModelCatalogEntry

Persistir catálogo de modelos.

Conceitualmente:

```text
ModelCatalogEntry
├── provider_id
├── model_id
├── display_name
├── context_window
├── execution_location
├── availability
├── enabled
├── discovery_source
├── last_seen_at
└── metadata
```

Identidade estável:

```text
provider_id / model_id
```

Não usar nome de display como identity.

---

# 20. Model existence ≠ capabilities

O fato de um provider listar um modelo não prova que ele suporta:

```text
tool calling
vision
realtime
audio
structured output
reasoning
etc.
```

Capabilities precisam de provenance.

Baseline conceitual:

```text
BUILTIN_METADATA
PROBED
USER_OVERRIDE
DISCOVERED
```

`DISCOVERED` sozinho não deve inventar hard capabilities.

O Router deve falhar conservadoramente quando não consegue provar compatibilidade obrigatória.

---

# 21. Model discovery

Criar provider-neutral discovery boundary quando suportado.

Fluxo:

```text
ProviderConfiguration
↓
ModelDiscoveryAdapter
↓
provider model listing
↓
normalized model identities
↓
Model Catalog reconciliation
```

Regras:

- discovery é bounded;
- não fazer polling agressivo;
- não apagar configuração do usuário porque um modelo sumiu temporariamente;
- preferir `last_seen_at` + availability/state a physical delete;
- provider sem discovery continua podendo usar manual catalog entry pelo Core contract.

Implementar somente os adapters necessários ao Gate.

OpenAI/OpenAI-compatible pode ser o primeiro.

---

# 22. InferenceProfile

Persistir profiles de workload.

Conceitualmente:

```text
InferenceProfile
├── key
├── display_name
├── description
├── required_capabilities
├── preferred_capabilities
├── locality
├── enabled
└── fallback_policy
```

Baseline inicial deve refletir workloads reais.

Sugestão:

```text
chat.general
coding
research
vision
realtime
utility
```

Adicionar apenas profiles com consumer real.

Profiles futuros como:

```text
chat.fast
reasoning
transcription
tts
embedding
video
```

devem entrar quando houver runtime consumer ou quando o Contract aprovado exigir explicitamente.

---

# 23. Capability vs profile

Não confundir:

```text
Capability
    = o que o modelo consegue fazer

InferenceProfile
    = que tipo de trabalho o Core quer executar
```

Exemplo:

```text
coding profile
    required: TEXT_GENERATION + TOOL_CALLING
    preferred: reasoning-capable
    model preference: user-configured
```

Profile não substitui Capability.

---

# 24. ProfileModelBinding

Permitir preferência ordenada por profile.

Conceitualmente:

```text
ProfileModelBinding
├── profile_key
├── provider_id
├── model_id
├── priority
├── enabled
└── source
```

Exemplo:

```text
coding
    1. openai/model-strong
    2. provider-b/model-code
    3. canonical model if compatible
```

A ordem representa preference, não authority.

---

# 25. Routing resolution

A resolução semântica deve obedecer algo equivalente a:

```text
explicit per-call model override
        ↓
profile bindings by priority
        ↓
other compatible candidates
        ↓
canonical/default model if compatible
        ↓
clear routing failure
```

O Contract v1 pode ajustar a ordem final.

Hard requirements nunca são relaxados silenciosamente.

---

# 26. RoutingPolicy boundary

Evitar acoplar persistence diretamente ao `CapabilityRouter`.

Preferência arquitetural:

```text
Operational Store
      ↓
AI Configuration Service
      ↓
immutable routing snapshot
      ↓
Routing Policy / ModelRegistry
      ↓
CapabilityRouter
```

O `CapabilityRouter` continua puro/determinístico.

A camada acima resolve configuração dinâmica.

Mudança de configuração deve gerar novo snapshot coerente.

Requests já em voo podem terminar com o snapshot com que começaram.

Novos requests usam o snapshot novo.

---

# 27. Runtime reconfiguration

Mudanças de profile/binding devem entrar em vigor sem restart sempre que seguro.

Requisitos:

```text
validated write transaction
↓
rebuild routing snapshot
↓
atomic publication
↓
Audit
```

Se rebuild falhar:

```text
rollback / previous snapshot remains active
```

Não deixar runtime metade antigo/metade novo.

---

# 28. Compatibility validation

Ao selecionar modelo para profile:

```text
model satisfies required capabilities
+
locality is compatible
+
provider binding supports required interface
+
model/provider enabled
+
availability permits selection
```

Configuração deterministicamente incompatível deve ser rejeitada no write path.

Não aceitar configuration inválida apenas para falhar depois durante inference.

---

# 29. Fallback

Fallback precisa ser profile-aware.

Permitido:

```text
primary unavailable
↓
next configured compatible binding
```

Proibido:

```text
LOCAL_ONLY
↓
local unavailable
↓
silent cloud fallback
```

Fallback deve gerar Audit/diagnostic evidence.

---

# 30. Provider/model deprecation

Quando provider deixa de oferecer um modelo:

```text
profile binding permanece
model catalog marca ausência/unavailability
router pula candidato
fallback compatível pode assumir
future Dashboard mostra warning
```

Não apagar user preference automaticamente.

Vertical obrigatório:

```text
coding primary = provider-a/model-old
fallback       = provider-b/model-new

model-old unavailable
↓
router selects model-new
↓
fallback audited
↓
profile preference original permanece persistida
```

---

# 31. Availability / health

Reutilizar a noção atual de `ModelAvailability`.

Baseline suficiente:

```text
AVAILABLE
UNAVAILABLE
```

Pode existir estado transitório/cooldown se necessário, mas não criar circuit-breaker platform por antecipação.

Não transformar um timeout isolado em disable permanente sem regra clara.

---

# 32. Canonical model com DB vazio

First boot:

```text
.env canonical provider/model
↓
bootstrap registration
↓
compatible default profile binding
```

O Core deve funcionar antes de qualquer configuração via Dashboard.

Canonical model continua sujeito a compatibility checks.

---

# 33. Agent integration

Agents não devem hardcode provider/model.

Targets obrigatórios:

```text
DevelopmentAnalysisAgent
    → profile = coding

ResearchAgent
    → profile = research
```

Os Agents continuam declarando hard capability requirements.

Profile escolhe preferences e bindings.

Não remover narrowing de context/tools/authority.

---

# 34. Conversation integration

Text Conversation usa profile apropriado.

Baseline:

```text
chat.general
```

Este Slice não deve criar um LLM classifier caro para cada mensagem.

Evitar:

```text
call expensive router model
just to discover that "bom dia" is simple
```

Operações especializadas devem migrar para Agent/Task/profile específico quando apropriado.

Uma futura classificação semântica de workload pode ser adicionada depois se houver evidência de necessidade.

---

# 35. Vision integration

Vision runtime usa:

```text
profile = vision
```

mantendo hard requirement:

```text
Capability.IMAGE_INPUT
```

---

# 36. Realtime integration

Realtime runtime usa:

```text
profile = realtime
```

mantendo hard requirements:

```text
REALTIME
AUDIO_INPUT
AUDIO_OUTPUT
```

Não degradar silenciosamente para text model incompatível.

STT → LLM → TTS continua estratégia futura possível, não requisito deste Gate.

---

# 37. Utility profile

`utility` só deve ser usado onde houver workload bounded coerente.

Não substituir lógica determinística simples por LLM.

---

# 38. Core AI Configuration API

Criar authenticated Core API para o futuro Dashboard.

Baseline:

```text
GET  /api/v1/ai/providers
GET  /api/v1/ai/models
POST /api/v1/ai/models/refresh

GET  /api/v1/ai/profiles
GET  /api/v1/ai/profiles/{key}
PATCH /api/v1/ai/profiles/{key}

POST /api/v1/ai/routing/preview
```

CRUD adicional pode existir se o Runtime Configuration Contract v1 exigir.

Não aceitar secret values em endpoints genéricos de provider config neste Gate sem decisão arquitetural explícita.

---

# 39. Routing preview

`routing/preview` explica seleção sem realizar inference.

Exemplo:

```json
{
  "profile": "coding",
  "selected": {
    "provider_id": "openai",
    "model_id": "example-model"
  },
  "reason": "primary profile binding is available and compatible",
  "fallback": false
}
```

Não expor:

- API keys;
- hidden chain-of-thought;
- sensitive prompt/context.

`reason` é evidence determinística, não reasoning privado de LLM.

---

# 40. Audit

Registrar eventos equivalentes a:

```text
AI_PROVIDER_CONFIG_CHANGED
AI_MODEL_CATALOG_REFRESHED
AI_PROFILE_CHANGED
AI_ROUTING_SELECTED
AI_ROUTING_FALLBACK
AI_ROUTING_FAILED
```

Metadata segura pode incluir:

- profile;
- provider_id;
- model_id;
- reason code;
- availability;
- fallback flag.

Nunca secret.

---

# 41. Usage observability

Quando provider reportar usage, preservar metadata normalizada existente.

Não transformar Slice 09 em billing engine.

Mas garantir que evidence de Turn/Agent/Audit consiga responder:

```text
qual profile?
qual provider?
qual model?
houve fallback?
```

---

# 42. Data locality

Profile nunca amplia locality.

Se profile prefere cloud mas request é `LOCAL_ONLY`:

```text
cloud candidate is ineligible
```

sem exceção silenciosa.

---

# 43. Persistence

Adicionar migrations incrementais.

Não alterar migrations publicadas até:

```text
0010_task_attempt_grant
```

Testes obrigatórios:

```text
fresh DB → new head
v0.1.0 DB → new head
new head → no-op
```

Seed de defaults, se necessário, deve ser idempotente.

---

# 44. Gate I15 tests

Criar:

```text
tests/integration/gate/test_gate_i15_intelligent_ai_routing.py
```

Cobrir pelo menos:

- first boot canonical model;
- persisted provider config;
- discovered model reconciliation;
- missing model not physically deleted;
- capability provenance;
- profile defaults;
- profile binding priority;
- incompatible binding rejected;
- explicit override;
- canonical fallback only when compatible;
- unavailable primary fallback;
- `LOCAL_ONLY` blocks cloud fallback;
- coding Agent profile;
- research Agent profile;
- Vision profile;
- Realtime profile;
- config update without restart;
- routing snapshot consistency;
- routing preview;
- Audit;
- no secret leakage.

---

# 45. Multi-provider vertical

Gate I15 deve provar pelo menos dois provider identities no mesmo Core.

CI pode usar deterministic fakes/adapters.

Exemplo:

```text
chat.general
    → provider/model A

coding
    → provider/model B

same Sofia
same Core
same Conversation/Task authority model
```

Não exigir dois serviços live pagos.

---

# 46. Human-facing diagnostic smoke

Ao final do Run 2 deve ser possível iniciar o Core real e observar de forma segura:

```text
Core READY
canonical provider/model
configured profiles
provider/model health
routing preview
```

Pode ser CLI diagnostics ou authenticated API.

Não criar uma segunda UI provisória.

---

# 47. Live provider tests

Default CI permanece sem billing/network dependency.

Live tests são opt-in.

Rodar live smoke somente se:

- Adapter boundary mudou de forma relevante;
- discovery real precisa ser provado;
- houver autorização explícita.

Caso contrário, deterministic fakes + historical evidence são suficientes.

---

# 48. Security regressions

Preservar explicitamente:

- localhost authentication;
- no LAN bind by default;
- SecretService boundary;
- no secret plaintext em normal SQLite config;
- no secret em Audit/logs;
- no Policy bypass;
- data locality;
- memory trust rules;
- Agent narrowing;
- tool authorization;
- recovery semantics.

---

# 49. Não escopo

Fora deste Slice:

```text
novo Dashboard visual
Desktop redesign
one-click Core+Desktop launcher UX
remote/VPS public API exposure
TLS termination
multi-user
OAuth provider accounts
billing/cost accounting engine
generic model marketplace
plugin marketplace
LLM semantic router obrigatório
wake word
continuous microphone
continuous camera
full STT→LLM→TTS pipeline
distributed Core
central cloud control plane
```

Não puxar esses itens por conveniência.

---

# 50. Slice 10 boundary

O próximo Slice esperado consumirá o Core configurável entregue aqui.

Conceitualmente:

```text
Slice 10 — Human Desktop Experience
```

Ele poderá tratar:

- real dashboard;
- provider/model settings;
- profile editor;
- connection tests;
- conversation history UX;
- automatic Core attach/start;
- invisible client credential flow;
- health UI;
- voice UX;
- Tasks/Notifications ergonomics.

O Slice 10 não deve precisar redefinir routing/storage contracts.

---

# 51. Quality gates

Em cada Run:

```powershell
cd core
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
git diff --check
```

Quando packaging/entrypoint for afetado:

```powershell
uv run python -m PyInstaller --noconfirm client/SofiaAssistant.spec
dist\SofiaAssistant.exe --smoke
```

Se um Core executable/spec passar a existir, criar smoke equivalente.

Não rodar live paid provider tests por default.

---

# 52. CI

Cada Gate exige remote CI no HEAD correspondente.

Estados honestos:

```text
IMPLEMENTED — LOCAL VERIFIED
IMPLEMENTED — AWAITING REMOTE VERIFICATION
CLOSED — REMOTE VERIFIED
```

Não declarar remote verified sem CI real para o commit pretendido.

---

# 53. Commit strategy

Preferir commits por pacote funcional.

Run 1, por exemplo:

```text
feat(config): add environment-backed runtime configuration
feat(core): add production Core process host
test(core): validate Gate I14 runtime lifecycle
docs(plan): close Gate I14
```

Run 2:

```text
feat(ai): add persistent model catalog and inference profiles
feat(routing): add profile-aware dynamic model routing
feat(api): expose AI configuration boundary
test(ai): validate Gate I15 intelligent routing
docs(plan): close Slice 09
```

Evitar microcommits sem valor de revisão.

Não reescrever histórico já publicado do `v0.1.0`.

---

# 54. Gate closure ledgers

Ao fechar cada Gate, registrar neste arquivo:

```text
Gate:
Status:
Baseline:
Feature commits:
Test commits:
Docs commits:
Final HEAD:
Remote CI:
Tests:
Quality:
Architecture findings:
Deferred:
Blockers:
```

Slice 09 só vai para `completed/` quando Gate I15 estiver fechado.

---

# 55. Acceptance final — Gate I14

```text
[ ] production RuntimeConfig
[ ] `.env` + process environment precedence
[ ] SecretService-compatible environment secret source
[ ] canonical/default model bootstrap
[ ] production provider composition
[ ] Sofias Memory production composition
[ ] persistent Core host
[ ] authenticated LocalClientBoundary
[ ] health/readiness
[ ] graceful shutdown
[ ] single-instance preservation
[ ] Windows-first
[ ] Linux-portable
[ ] real human Core smoke
[ ] README run instructions correct
[ ] Gate I14 tests
[ ] full regression
[ ] quality gates
[ ] remote CI
```

Fechamento esperado:

```text
GATE I14 CLOSED — REMOTE VERIFIED
```

---

# 56. Acceptance final — Gate I15

```text
[ ] persistent ProviderConfiguration
[ ] persistent ModelCatalog
[ ] provider-neutral discovery boundary
[ ] capability provenance
[ ] InferenceProfile
[ ] ProfileModelBinding
[ ] ordered preference
[ ] hard compatibility validation
[ ] explicit override validation
[ ] compatible fallback
[ ] model deprecation handling
[ ] runtime reconfiguration without restart
[ ] routing snapshot consistency
[ ] coding Agent profile
[ ] research Agent profile
[ ] Vision profile
[ ] Realtime profile
[ ] AI Configuration API
[ ] routing preview
[ ] routing Audit
[ ] multi-provider vertical
[ ] no secret leakage
[ ] migration fresh/upgrade/no-op
[ ] Gate I15 tests
[ ] full regression
[ ] quality gates
[ ] remote CI
```

Fechamento esperado:

```text
GATE I15 CLOSED — REMOTE VERIFIED
SLICE 09 COMPLETED — REMOTE VERIFIED
CORE READY FOR DASHBOARD UX
```

---

## Gate I15 — closure ledger

```text
Gate: I15 — Intelligent AI Routing
Status: CLOSED — REMOTE VERIFIED

Baseline: 77a1a18f7b91780e69abb24f1e6a3043c81571be

Reference Harvest:
  Mark LI / Brahma AI / OpenAI model listing / OpenRouter / Ollama patterns
  were reviewed conceptually against the plan's constraints. No external
  code was imported. Findings:
    REJECTED  direct provider -> Tool authority (never applicable here;
              routing config never grants filesystem/shell/network/desktop
              authority — preserved).
    REJECTED  "discovery == capability truth" (every discovery adapter in
              this Gate returns identity only; capability claims always
              require explicit BUILTIN_METADATA/PROBED/USER_OVERRIDE
              provenance before they count for hard compatibility).
    REJECTED  unrestricted auto-model selection from the full catalog
              (fallback is limited to ORDERED_ONLY / ORDERED_THEN_CANONICAL;
              Contract v1 explicitly forbids "any other compatible model").
    ADAPTED   OpenAI-compatible `GET /v1/models` listing shape, normalized
              into `DiscoveredModel(model_id, display_name)` only.
    REUSED    existing project seams: Alembic migration convention,
              SqlAlchemyUnitOfWork/repository pattern, AuditService safe
              metadata redaction, FastAPI `register_x_routes(app,
              require_session, ...)` convention, ScriptedFakeProvider test
              support.

Persistence:
  Migration 0011_ai_provider_model_profile_routing (incremental, after
  0010_task_attempt_grant): ai_provider_configurations,
  ai_model_catalog_entries (FK to providers, unique (provider_id, model_id)),
  ai_inference_profiles, ai_profile_model_bindings (FK to profiles, unique
  (profile_key, provider_id, model_id)). No published migration modified.
  credential_ref persists only a SecretRef identity string; no secret value
  in any AI table.

Migration tests:
  tests/integration/persistence/test_migrations.py — fresh DB -> head,
  0010 (v0.1.0/Gate I14 baseline) -> head adds exactly the four new tables
  without touching existing data, head -> head is a no-op. Updated
  HEAD_REVISION/DOMAIN_TABLES fixtures accordingly.

ProviderConfiguration / ModelCatalog:
  sofias_assistant.ai_config.models — frozen domain dataclasses separate
  from both ai.contracts (provider-neutral inference DTOs) and the ORM
  records. Stable identity is (provider_id, model_id); display_name is
  never identity. `ModelCatalogEntry.trusted_capabilities()` excludes any
  capability whose provenance is DISCOVERED.

Capability provenance:
  Capability.CapabilityProvenance added to ai/contracts.py
  (BUILTIN_METADATA/PROBED/USER_OVERRIDE/DISCOVERED). Enforced at snapshot-
  build time in AIConfigurationService._rebuild_and_publish: only non-
  DISCOVERED claims are registered into the in-memory ModelRegistry
  CapabilityRouter actually uses, so a bare discovery listing can never
  satisfy a hard requirement — CapabilityRouter itself needed no change.

Discovery:
  ai/discovery.py — provider-neutral `ModelDiscoveryAdapter` Protocol,
  bounded `OpenAIModelDiscoveryAdapter` (`asyncio.timeout`, normalizes
  provider failures/timeouts to `ModelDiscoveryError`, closes its client),
  `FakeModelDiscoveryAdapter` for tests. `AIConfigurationService.
  refresh_models` reconciles idempotently: new identities are added
  disabled (discovery never authorizes usage); identities no longer
  reported are marked UNAVAILABLE, never physically deleted.

Inference profiles:
  ai/routing_policy.py `ProfileSpec` + ai_config `InferenceProfile`.
  Bootstrap seeds exactly chat.general/coding/research/vision/realtime with
  the Contract v1 SS22 baseline required_capabilities; no speculative
  `utility` profile (no real consumer).

Bindings:
  ProfileModelBinding persisted with deterministic `priority` ordering.
  `AIConfigurationService.update_profile` validates every candidate binding
  against the profile's required_capabilities/locality before any write
  (unknown model or missing capability/locality raises AIConfigurationError
  and nothing is persisted).

Routing policy:
  ai/routing_policy.py `RoutingPolicy` sits strictly above
  `CapabilityRouter`: it resolves profile + explicit-override + ordered
  bindings + canonical fallback purely from an immutable `RoutingSnapshot`,
  and always delegates the actual hard-compatibility decision to
  `CapabilityRouter.route(model_override=...)` — CapabilityRouter and
  ModelRegistry required zero code changes (boundary crítico preserved).
  `RoutingPolicy` structurally satisfies the same `Router` Protocol as
  `CapabilityRouter.route(...)`, so every existing consumer constructor
  needed only a widened type hint, not a call-site rewrite.

Fallback:
  FallbackPolicy.ORDERED_ONLY / ORDERED_THEN_CANONICAL implemented exactly
  as specified; canonical is a separate resolution step, never a
  ProfileModelBinding row. Proven vertical: coding primary
  provider-b/model-new configured explicitly; when it becomes UNAVAILABLE,
  routing fails closed (no synonymous discovery-based substitute), and the
  original binding preference remains persisted untouched.

Locality:
  `_narrow_locality` guarantees a profile can only push a request toward
  LOCAL_ONLY, never widen it; LOCAL_ONLY requests never receive a cloud
  candidate, canonical fallback included.

Runtime snapshot:
  `RoutingSnapshot` is an immutable dataclass built entirely inside
  `AIConfigurationService._rebuild_and_publish` from one consistent read of
  ProviderConfiguration/ModelCatalogEntry/InferenceProfile/
  ProfileModelBinding, then published via a single attribute assignment.
  Captured snapshot references remain valid after a later publish (proven
  by test_routing_snapshot_is_immutable_and_in_flight_requests_keep_their_version).
  A failed rebuild (simulated persistence outage) leaves the previously
  published snapshot active and surfaces `SnapshotPublicationError`.

Runtime reconfiguration:
  Provider/model enable-disable, binding order, and fallback policy all
  take effect on the next `RoutingPolicy.resolve()` call against the same
  long-lived instance, with no Core restart (proven end-to-end through the
  real `sofia-core` host in the Gate's human-facing diagnostic smoke).

Consumer integration:
  Conversation (chat.general) and RealtimeConversationRuntime (realtime)
  now receive a profile-bound `RoutingPolicy` from
  `host/composition.py::build_conversation_dependencies_factory` instead of
  a single hardcoded in-memory registration; both keep their own hard
  capability requirements and existing exception contracts unchanged.
  DevelopmentAnalysisAgent (coding), ResearchAgent (research) and
  VisionCapability (vision, IMAGE_INPUT hard requirement, no text-only
  fallback) accept the same `Router`-shaped policy and emit
  AI_ROUTING_SELECTED/FALLBACK/FAILED Audit through their existing
  AuditService. None of these three are wired into the production
  `sofia-core` host itself (unchanged from Gate I14 — still test/consumer-
  composed only), matching the Slice's Dashboard/agent-invocation UX being
  out of scope until Slice 10.

AI Configuration API:
  client_boundary/ai_http.py, registered conditionally in
  create_local_http_app via a new `ai_configuration` parameter, wired from
  `core.ai_configuration_service` (new SofiaCore property, mirroring
  `memory_orchestrator`). GET providers/models, POST models/refresh, GET/
  PATCH profiles, POST routing/preview — all behind the existing
  `require_session` authenticated boundary; no second auth subsystem.

Routing preview:
  Deterministic only (`AIConfigurationService.preview_routing` ->
  `RoutingPolicy.resolve`); never invokes a provider; response carries
  profile/selected/fallback/reason_code/reason only.

Audit:
  AI_PROVIDER_CONFIG_CHANGED (bootstrap), AI_MODEL_CATALOG_REFRESHED
  (refresh_models), AI_PROFILE_CHANGED (update_profile),
  AI_ROUTING_SELECTED/AI_ROUTING_FALLBACK/AI_ROUTING_FAILED
  (route_with_audit / consumer-side record_routing_decision) all verified
  present with safe metadata (profile, provider_id, model_id, reason_code,
  fallback) and no secret/prompt content.

Security:
  No raw secret ever leaves SecretService (verified via repr/API/Audit
  assertions across ai_config and Gate I15 tests); credential API
  representation exposes only `{ref, configured: bool}`. Loopback-only
  authenticated boundary, Policy/Grant/Tool authorization, Memory trust,
  Agent narrowing and recovery semantics are all untouched by this Gate.

Targeted tests:
  tests/unit/ai/test_routing_policy.py (12), tests/unit/ai/test_discovery.py
  (6), tests/integration/ai_config/test_ai_configuration_service.py (10).

Gate tests:
  tests/integration/gate/test_gate_i15_intelligent_ai_routing.py (24
  scenarios: first boot, persisted config survives reinitialize, discovery
  reconciliation without deletion, DISCOVERED-only capability rejected,
  profile defaults, incompatible binding rejected, unavailable-primary
  fallback with preserved preference, LOCAL_ONLY blocks cloud, disabled/
  invalid profile, explicit incompatible override without fallthrough,
  canonical fallback only when compatible, coding/research Agent profile
  integration with Audit, Vision profile with no text fallback, realtime
  hard-requirement fail-closed, config update without restart, immutable
  snapshot versioning, failed-rebuild keeps previous snapshot, preview
  response shape, Audit coverage, no secret leakage, multi-provider
  vertical, and a human-facing diagnostic smoke against the real
  `sofia-core` host over HTTP).

Migration tests: included above (test_migrations.py).

Full pytest: 788 passed, 4 skipped (pre-existing opt-in live-provider/
  Windows-credential-store smokes) locally.

Ruff: clean. Format: clean. Mypy (src+tests): clean. git diff --check: clean.

Diagnostic smoke:
  test_human_facing_diagnostic_smoke_exposes_ai_configuration_over_http
  starts the real `sofias_assistant.host.runner.run` lifecycle (same
  composition sofia-core uses), then calls GET /api/v1/ai/providers,
  /models, /profiles and POST /api/v1/ai/routing/preview over real HTTP
  loopback with a fake OpenAI SDK transport, asserting providers/models/
  profiles are visible and routing preview resolves chat.general to the
  canonical bootstrap model.

Commits:
  <feature commit>  feat(ai): add persistent AI provider/model/profile
                     configuration and dynamic routing
  <test commit>      test(ai): validate Gate I15 intelligent routing
  <docs commit>      docs(plan): record Gate I15 ledger — implemented,
                     awaiting remote verification
  <docs commit>      docs(plan): close Gate I15 — remote verified;
                     complete Slice 09

Final HEAD: <to be filled after remote verification>
Remote CI: <to be filled after remote verification>

Architecture findings: none requiring a new Amendment/Contract revision.
  `CapabilityRouter`/`ModelRegistry` required zero code changes; the
  profile-aware layer above them (`RoutingPolicy`/`RoutingSnapshot`) fully
  satisfied Amendment 0003 SS13's "Operational Store -> AI Configuration
  Service -> validated immutable Routing Snapshot -> Routing Policy ->
  CapabilityRouter" shape without new persistence-awareness inside the
  router.

Deferred (explicitly out of Gate I15 scope, per Slice "Não escopo"):
  Desktop Dashboard, profile editor UI, provider settings UI, wiring
  DevelopmentAnalysisAgent/ResearchAgent/VisionCapability into the
  production sofia-core host itself (still test/consumer-composed only,
  same as Gate I14), OAuth provider accounts, public/VPS API exposure,
  billing/cost engine, universal model marketplace, semantic LLM router,
  full STT->LLM->TTS pipeline.

Known limitations:
  - `OpenAIProviderAdapter`/`ai/adapters/openai.py` now honors a configured
    `base_url` for the default client factory (a narrow, backward-
    compatible completion of the existing Gate I14 seam), but no live
    OpenAI-compatible endpoint was exercised in CI; discovery/binding
    correctness against a real OpenAI-compatible server remains opt-in
    live-smoke territory, consistent with "Não exigir live OpenAI em CI".
  - `CoreApiClient.stream_text` still hardcodes `local_only` locality
    (pre-existing Gate I14 note, unrelated to this Gate, Slice 10 UX
    concern).

Blockers: none.
```

---

# 57. Stop conditions

Parar para decisão humana apenas se:

- Amendment 0003 / Contract v1 conflitarem com este Slice;
- for necessário alterar invariant arquitetural aceita;
- storage de secrets exigir nova decisão de produto;
- provider discovery exigir comportamento inseguro;
- external network exposure for necessário;
- migration destrutiva for necessária;
- mudança exigir quebrar compatibilidade do `v0.1.0` sem transition path razoável;
- um provider real obrigatório não possuir deterministic substitute para o Gate.

Não parar por:

- naming;
- fixture design;
- pequenas refactors;
- endpoint naming consistente;
- helper organization;
- exact internal snapshot implementation;
- test arrangement.

---

# 58. Final report por Run

Retornar relatório compacto:

```text
Gate:
Status:

Baseline:
Reference Harvest:

Implemented:
Architecture:
Persistence:
API:
Security:

Targeted tests:
Full pytest:
Ruff:
Format:
Mypy:
git diff --check:

Packaging/smoke:

Commits:
Final HEAD:
origin/main:
CI run:
CI conclusion:

Deferred:
Known limitations:
Real blockers:
```

Fechar com um único estado coerente, por exemplo:

```text
GATE I14 CLOSED — REMOTE VERIFIED
```

ou:

```text
GATE I15 IMPLEMENTED — AWAITING REMOTE VERIFICATION
```

ou:

```text
BLOCKED — HUMAN DECISION REQUIRED
```

---

# 59. Nota arquitetural final

O objetivo deste Slice não é selecionar definitivamente quais modelos o produto usará.

O objetivo é permitir que essa escolha mude sem alterar a identidade da Sofia, sem perder contexto e sem exigir mudança recorrente de código ou `.env`.

A arquitetura desejada ao final é:

```text
stable Sofia identity
+
stable Core contracts
+
dynamic provider/model configuration
+
deterministic validated routing
+
persistent user preferences
+
safe fallback
+
observable provider/model health
```

Modelos podem surgir, mudar ou ser descontinuados.

O Core deve continuar estável.
