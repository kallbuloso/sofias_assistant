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
