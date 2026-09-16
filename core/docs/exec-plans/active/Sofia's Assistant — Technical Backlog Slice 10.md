# Sofia's Assistant — Technical Backlog Slice 10

**Nome operacional:** Human Desktop Experience  
**Escopo:** SA-B038 + SA-B039 + SA-B040 + SA-B041  
**Gates-alvo:** I16 — Seamless Desktop Runtime; I17 — Human Configuration Dashboard; I18 — Daily Assistant Experience  
**Status:** READY FOR APPROVAL  
**Projeto:** Sofia's Assistant  
**Baseline remoto auditado:** `dcf25a3b7231c264d3c3ad860eac7df24bb56532`  
**Release baseline:** `v0.1.0` — publicado  
**Último Slice concluído:** Slice 09 — Core Runtime Configuration & Intelligent AI Routing — COMPLETED / REMOTE VERIFIED  
**Fonte:** PRD + CLAUDE.md + ADRs aceitos + Architecture Review Amendments + AI Runtime Configuration Contract v1 + TDR-0011 + Slices 07/09 concluídos

---

# 1. Objetivo

O Slice 10 transforma o Desktop Client técnico já existente em uma experiência humana coerente para uso real da Sofia.

O objetivo não é reescrever o Core nem criar uma nova UI authority.

O objetivo é tornar invisíveis ao usuário normal detalhes como:

```text
LocalClientBoundary
Bearer credential
porta 8989
sofia-core manual
SecretRef
CapabilityRouter
routing snapshot
runtime session ids
```

A experiência-alvo é:

```text
usuário inicia Sofia
        ↓
Desktop localiza ou inicia o Core
        ↓
Desktop se autentica automaticamente
        ↓
Dashboard informa estado real
        ↓
usuário configura providers/models/profiles sem editar arquivos
        ↓
usuário conversa, retoma conversas, usa voz, acompanha Tasks e confirmações
        ↓
Core continua independente da janela/UI
```

O Slice deve fechar com uma baseline desktop pronta para validação humana real, sem sacrificar boundaries de segurança ou ownership.

---

# 2. Estado de partida

O baseline `dcf25a3b7231c264d3c3ad860eac7df24bb56532` já possui:

```text
Production Core Host (`sofia-core`)
RuntimeConfig production-grade
SecretService bridge
Sofias Memory integration
Persistent AI Provider Configuration
Dynamic Model Catalog
Capability provenance
Inference Profiles
ProfileModelBinding
Dynamic Routing
Authenticated AI Configuration API
Routing Preview
Conversation Runtime
Realtime Runtime
Tasks
Agents
Scheduler
Notifications
Confirmations
Audit
Recovery
PySide6 Desktop Client
QSystemTrayIcon
CoreApiClient
ClientApplicationService
PyInstaller baseline
```

O Desktop Client atual ainda é uma primeira superfície técnica. Em especial:

- espera `base_url` + bearer credential já conhecidos;
- não inicia/localiza o Core como experiência humana;
- não possui secure attach UX;
- não configura provider credentials de forma humana;
- não expõe de forma completa Providers / Models / Profiles / Bindings;
- não oferece Conversation History como produto;
- `CoreApiClient.stream_text()` ainda fixa `local_only`;
- Realtime possui controles/protocolo, mas não fecha ainda toda a experiência real de microphone/speaker;
- Tasks/Notifications/Health existem, porém com ergonomia mínima;
- o usuário ainda pode precisar entender detalhes internos para operar o produto.

O Slice 09 encerrou com:

```text
CORE READY FOR DASHBOARD UX
```

O Slice 10 consome esse Core. Ele não redefine routing/storage contracts.

---

# 3. Organização por Runs/Gates

```text
Slice 10 — Human Desktop Experience
│
├── Run 1 — Gate I16 — Seamless Desktop Runtime
│     └── SA-B038 Core Supervision & Secure Attach
│
├── Run 2 — Gate I17 — Human Configuration Dashboard
│     └── SA-B039 Human Configuration Dashboard
│
└── Run 3 — Gate I18 — Daily Assistant Experience
      ├── SA-B040 Conversation History & Privacy UX
      └── SA-B041 Voice & Operational UX
```

I16 fecha antes de I17.

I17 fecha antes de I18.

Não iniciar Run seguinte antes do fechamento remoto do Gate anterior, salvo autorização explícita do usuário.

---

# 4. Dependências documentais propostas

Este Slice introduz decisões duráveis novas sobre:

- Desktop/Core process lifecycle;
- secure local attach;
- human credential handoff;
- Core shutdown UX;
- secure provider credential update from Desktop;
- request locality/privacy UX.

Antes da implementação do Run 1 devem existir e estar aprovados documentos equivalentes a:

```text
Architecture Review Amendment 0004
Human Desktop Lifecycle, Secure Attach and Credential UX

Sofia's Assistant — Desktop/Core Interaction Contract v1
```

O Slice pode ser aprovado antes desses documentos, mas implementação não deve começar até eles existirem e estiverem aprovados.

Precedência:

```text
instrução explícita do usuário
↓
active Slice
↓
Architecture Review Amendment 0004
↓
Desktop/Core Interaction Contract v1
↓
Architecture Review Amendment 0003
↓
AI Runtime Configuration Contract v1
↓
accepted ADRs / TDR-0011
↓
PRD
↓
existing implementation
```

---

# 5. Decisões de produto/arquitetura propostas para aprovação

A aprovação deste Slice significa concordância com a direção abaixo, sujeita ao detalhamento normativo do Amendment/Contract.

## 5.1 Desktop pode iniciar o Core, mas não é dono do Core

```text
Desktop may start Core
        !=
Desktop owns Core
```

Core continua processo independente.

Fechar a janela ou encerrar o Desktop não deve automaticamente matar o Core.

Scheduler, reminders, background Tasks, notifications e recovery devem poder continuar sem UI.

## 5.2 Close vs Quit vs Stop Sofia

Semântica proposta:

```text
Close main window
    -> hide/minimize to tray

Quit Desktop
    -> encerra apenas o Desktop Client
    -> Core continua rodando

Stop Sofia
    -> ação explícita separada
    -> solicita graceful Core shutdown
    -> depois encerra Desktop quando aplicável
```

Nenhuma dessas ações deve matar processos por PID arbitrário.

## 5.3 Auto-start/attach

Ao iniciar o Desktop:

```text
matching Core already running
    -> verify identity
    -> secure attach

no matching Core
    -> launch packaged `sofia-core` equivalent
    -> wait bounded readiness
    -> secure attach
```

Não iniciar segundo Core para a mesma instance/data identity.

## 5.4 Client credential continua real

`localhost != trusted identity` permanece.

A autenticação não será removida para melhorar UX.

A credential deve desaparecer da experiência humana, não da arquitetura.

## 5.5 Core owns credential generation

Desktop não inventa bearer token próprio.

O Core/LocalClientBoundary continua gerando/possuindo a credential efetiva.

O Desktop apenas obtém acesso por um secure attach mechanism aprovado.

## 5.6 Secure attach state não pertence ao SQLite normal

A credential de attach não deve ser persistida como plaintext no Operational Store, `.env`, logs ou QSettings.

A direção Windows-first é usar abstraction equivalente a:

```text
ClientAttachStore
    ↓
Windows protected credential mechanism
```

com seam portátil para outras plataformas futuras.

Metadata não secreta de instance/endpoint pode usar runtime state apropriado.

## 5.7 Core shutdown deve ser Core-owned

Se houver endpoint/surface para `Stop Sofia`, ele deve solicitar shutdown ao Core.

Não implementar shutdown como:

```text
Desktop finds PID
Desktop kills process
```

PID é evidence, não authority.

## 5.8 PySide6 permanece

TDR-0011 permanece vigente.

Slice 10 evolui o Desktop Client PySide6/Qt Widgets existente.

Não reabrir Tauri/Electron/PySide sem blocker material.

## 5.9 Dashboard é client

Dashboard/UI:

- lê Core state via authenticated API;
- envia intents/updates ao Core;
- não acessa SQLite;
- não acessa repositories;
- não executa Tool diretamente;
- não decide routing por conta própria;
- não armazena provider/model state como authority.

## 5.10 Provider credentials precisam de UX segura

Human UX não pode exigir edição permanente de `.env`.

Slice 10 deve permitir atualizar credential de provider/integração por uma purpose-specific authenticated surface que:

- recebe secret somente no write path;
- entrega ao `SecretService`/platform secret store;
- nunca retorna o secret;
- nunca registra valor em Audit/log;
- nunca persiste valor no SQLite normal.

Não criar generic secret dump API.

## 5.11 Conversation History != Cognitive Memory

Conversation History permanece Core-owned operational data.

```text
Conversation History != Sofias Memory
```

Exibir/resumir conversas não cria segundo semantic-memory subsystem.

## 5.12 Privacy/locality deixa de ser hardcode

Desktop não deve mais fixar `local_only` silenciosamente.

O usuário deve poder escolher explicitamente sua policy de inferência.

Baseline proposta para first-run:

```text
Local only
Allow cloud
Prefer cloud
```

A escolha vira parâmetro explícito nas requests.

`cloud_context_eligible` permanece uma decisão separada e deve começar como `false` até opt-in explícito do usuário.

Profiles/routing nunca podem ampliar a policy da request.

---

# 6. Reference Harvest obrigatório

Cada Run começa com harvest dirigido.

Referências principais:

```text
Mark LI
Brahma AI
Sofia's Assistant current implementation
Qt / PySide6 official patterns quando necessário
```

Observar especialmente:

- one-launch desktop UX;
- background Core/service supervision;
- secure local process attach;
- tray ergonomics;
- settings/dashboard information architecture;
- provider/model configuration UX;
- conversation history UX;
- voice device UX;
- degraded/offline state handling.

Registrar:

```text
REUSED
ADAPTED
REJECTED
```

Não importar:

- UI-owned state authority;
- unauthenticated localhost assumptions;
- direct shell execution for product lifecycle;
- renderer privilege shortcuts;
- provider-specific domain coupling;
- secret plaintext settings.

---

# 7. Resume Capsule

Se houver interrupção:

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

# 8. Gate I16 — Seamless Desktop Runtime

**Escopo:** SA-B038 — Core Supervision & Secure Attach.

Objetivo:

```text
launch Desktop
↓
find matching Core
   or
start Core safely
↓
securely obtain attach credential
↓
authenticate
↓
show usable app
↓
Core survives Desktop close/quit
```

O usuário normal não deve abrir terminal nem copiar token.

---

# 9. SA-B038 — Core Supervision & Secure Attach

Criar application boundary dedicado, conceitualmente:

```text
DesktopCoreSupervisor
```

Responsabilidades:

- discover expected Core instance;
- distinguish absent/running/starting/unhealthy Core;
- launch packaged Core when absent;
- wait bounded readiness;
- resolve secure attach credential;
- create authenticated `CoreApiClient`;
- observe Core process when Desktop started it;
- reconnect after bounded interruption;
- expose safe lifecycle state to UI;
- request graceful stop only on explicit user action.

Não colocar esse comportamento dentro de widgets isolados.

---

# 10. Core supervision states

Baseline semântico:

```text
CORE_NOT_FOUND
CORE_STARTING
CORE_READY
CORE_DEGRADED
CORE_RECONNECTING
CORE_STOPPING
CORE_STOPPED
CORE_FAILED
```

UI pode mapear para labels amigáveis.

States são presentation/application state; authoritative subsystem health continua no Core.

---

# 11. Instance identity

Attach só pode ocorrer ao Core esperado.

Validar identity suficiente para evitar conectar a processo arbitrário na porta esperada.

Pode considerar evidence como:

- instance id;
- data-dir identity;
- authenticated attach record;
- Core version/protocol;
- loopback endpoint.

Não usar apenas:

```text
port 8989 is open => must be Sofia
```

---

# 12. Secure attach contract

O mecanismo concreto será congelado no Desktop/Core Interaction Contract.

Requisitos mínimos:

```text
Core generates LocalClientBoundary credential
↓
Core publishes attach material through OS-protected/local-user mechanism
↓
Desktop resolves matching instance attach material
↓
Desktop authenticates normally
```

A credential:

- não aparece em stdout normal;
- não aparece em log;
- não aparece em Audit;
- não entra em QSettings;
- não entra no Operational Store;
- deve ser removida/invalidada quando o Core encerra;
- deve ser rotacionada em novo Core lifecycle.

Testes devem usar fake attach store determinístico.

---

# 13. Windows-first attach

Implementação inicial deve funcionar sem prompt manual no Windows.

É aceitável usar Windows Credential Manager ou mecanismo equivalente sob abstraction dedicada.

Não acoplar widgets diretamente ao Windows Credential API.

Linux/macOS support completo pode ficar futuro, mas contracts/seams não devem impedir implementação posterior.

---

# 14. Launch packaged Core

Human UX final não pode depender de:

```text
uv run sofia-core
python -m ...
terminal aberto
```

O pacote Desktop deve localizar um Core executable/entrypoint distribuído junto ao produto, ou solução equivalente aprovada.

Launch deve usar executable path + argv explícitos.

Nunca:

```text
shell=True
cmd.exe /c arbitrary string
```

---

# 15. Core failure/restart behavior

Se Core cair inesperadamente durante uma sessão Desktop:

```text
CONNECTED
↓
CORE_RECONNECTING / DEGRADED
↓
try bounded recovery/reattach
```

Se auto-restart for implementado, deve ser bounded e distinguir crash de shutdown intencional.

Não criar restart storm.

Recovery interno do Core continua authority para Tasks/side effects.

Desktop não replaya operações mutating automaticamente.

---

# 16. Quit / tray semantics

Baseline:

- fechar janela -> hide to tray;
- tray continua mostrando status;
- `Quit Desktop` encerra Client process;
- Core fica vivo;
- `Stop Sofia` é ação separada e explícita.

Se Desktop for encerrado, reabrir deve conseguir attach ao Core existente sem novo Core nem token manual.

---

# 17. Graceful Core shutdown UX

Implementar Core-owned shutdown request surface apropriada.

A ação deve:

- exigir client authentication;
- representar intenção humana explícita;
- iniciar shutdown gracioso;
- não retornar raw lifecycle secret;
- não bypassar single-instance/recovery cleanup;
- ser testável deterministically.

A implementação concreta pode ser endpoint/application service aprovado no Contract.

---

# 18. Packaging — Gate I16

Provar distribution baseline onde um usuário pode executar o Desktop sem Python instalado.

O package deve conter tudo necessário para:

```text
Desktop startup
Core startup/attach
CoreApiClient auth
tray/background behavior
```

Code signing/installer comercial ainda não é requisito.

---

# 19. Gate I16 tests

Criar:

```text
tests/integration/gate/test_gate_i16_seamless_desktop_runtime.py
```

Cobrir no mínimo:

- Core already running -> attach;
- Core absent -> start -> attach;
- wrong/non-Sofia process on expected port is rejected;
- stale attach record rejected;
- credential never logged/serialized;
- credential rotates after Core restart;
- Desktop quit leaves Core alive;
- reopen attaches existing Core;
- explicit Stop Sofia gracefully stops Core;
- duplicate Core start avoided;
- Core crash -> bounded reconnect/restart behavior;
- no replay of mutating Desktop request;
- packaged Desktop + packaged Core smoke;
- no terminal required.

Acceptance:

```text
[ ] Desktop starts/attaches Core automatically
[ ] authentication remains real
[ ] secure attach mechanism
[ ] no token copy/paste
[ ] no secret plaintext persistence
[ ] Core survives Desktop quit
[ ] explicit graceful Stop Sofia
[ ] no PID-kill authority
[ ] packaged human startup
[ ] reconnect/recovery baseline
[ ] Gate I16 tests green
[ ] full regression green
[ ] remote CI green
```

Fechamento:

```text
GATE I16 CLOSED — REMOTE VERIFIED
```

---

# 20. Gate I17 — Human Configuration Dashboard

**Escopo:** SA-B039 — Human Configuration Dashboard.

Objetivo:

```text
Core AI configuration APIs
        ↓
Dashboard
        ↓
provider/model/profile configuration
        ↓
Core validates/persists/publishes routing snapshot
```

O usuário deve conseguir configurar Sofia sem editar SQLite ou conhecer internal schemas.

---

# 21. Dashboard information architecture

Baseline proposta:

```text
Home
Chat
AI & Models
Memory / Integrations
Tasks
Notifications
Voice
Settings
```

A estrutura concreta pode ser refinada durante implementation/reference harvest, mantendo os workflows obrigatórios.

Não construir dezenas de páginas antes dos flows funcionarem.

---

# 22. Home / Overview

Home deve responder rapidamente:

```text
Sofia está pronta?
Core está conectado?
AI está configurada?
Memory está disponível?
Há Tasks/confirmations/notifications pendentes?
```

Não mostrar low-level technical detail por default.

Permitir drill-down quando houver problema.

---

# 23. Provider configuration UX

Dashboard deve permitir visualizar e editar configuração não secreta permitida pelo Core contract:

- provider identity/display;
- enabled;
- adapter type quando aplicável;
- base URL;
- execution location;
- credential configured/missing state;
- health/availability.

Não mostrar secret existente.

---

# 24. Secure provider credential UX

Adicionar purpose-specific write path.

Exemplo conceitual:

```text
PUT /api/v1/ai/providers/{provider_id}/credential
```

ou contrato equivalente.

Requisitos:

- raw value existe apenas no request transitório;
- Core grava via `SecretService`/platform store;
- response retorna apenas configured/source/status;
- API nunca oferece GET do raw value;
- logs/Audit redigem valor;
- update/delete são explícitos;
- provider config continua apontando para `SecretRef`.

A mesma arquitetura pode ser usada para credentials de integrações aprovadas, como Sofias Memory, sem criar generic secret API irrestrita.

---

# 25. Model Catalog UX

Mostrar:

- provider;
- model id/display;
- availability;
- enabled;
- capabilities;
- capability provenance;
- context window quando conhecido;
- last seen/discovery state.

Permitir model refresh através do API existente.

Não apresentar capability `DISCOVERED` como comprovada se não for.

---

# 26. Inference Profiles UX

Profiles baseline:

```text
chat.general
coding
research
vision
realtime
```

Dashboard deve permitir:

- visualizar required/preferred capabilities;
- visualizar/editar allowed settings do profile;
- ordenar bindings;
- enable/disable binding;
- configurar fallback policy;
- visualizar incompatibilidade;
- salvar apenas configuração validada.

UI não valida sozinha como authority.

Core sempre valida novamente.

---

# 27. Routing Preview UX

Dashboard deve expor routing preview existente de forma humana.

Mostrar:

```text
profile
selected provider/model
fallback yes/no
reason code/explanation
```

Nunca mostrar:

- prompt;
- secret;
- Memory content;
- hidden reasoning.

Preview não executa inference.

---

# 28. Memory / Integration UX

Expor ao menos:

- enabled/disabled;
- base URL non-secret quando configurável;
- credential configured/missing;
- compatibility/health;
- degraded explanation;
- secure credential update quando aprovado.

Não duplicar Sofias Memory domain dentro da UI.

---

# 29. Settings separation

Separar claramente:

```text
Core settings
    -> authority in Core

UI preferences
    -> QSettings/local presentation
```

QSettings pode guardar:

- window geometry;
- theme/presentation;
- selected page;
- notification display preference;
- Desktop startup preference.

QSettings não pode virar authority para:

- provider config;
- model bindings;
- conversations;
- Tasks;
- notifications;
- secrets.

---

# 30. Gate I17 tests

Criar:

```text
tests/integration/gate/test_gate_i17_human_configuration_dashboard.py
```

Cobrir no mínimo:

- providers load/display;
- provider non-secret update;
- credential configured without secret echo;
- credential replace/delete lifecycle;
- models list + refresh;
- capability provenance rendered correctly;
- profiles list/detail;
- binding reorder/update;
- invalid binding rejected by Core and surfaced clearly;
- fallback policy update;
- routing preview;
- Memory integration health/config;
- dashboard reconnect;
- no direct SQLite access;
- no secret in logs/API/Audit/UI model dump.

Acceptance:

```text
[ ] Home dashboard usable
[ ] provider configuration UI
[ ] secure credential UX
[ ] model catalog UI
[ ] model discovery refresh
[ ] profile/binding editor
[ ] routing preview UI
[ ] Memory/integration state UI
[ ] Core remains validation authority
[ ] no secret leakage
[ ] Gate I17 tests green
[ ] full regression green
[ ] remote CI green
```

Fechamento:

```text
GATE I17 CLOSED — REMOTE VERIFIED
```

---

# 31. Gate I18 — Daily Assistant Experience

**Escopo:** SA-B040 + SA-B041.

Objetivo:

```text
open Sofia
↓
resume/new conversation
↓
chat with explicit privacy policy
↓
voice when desired
↓
handle confirmations/tasks/notifications naturally
↓
close window and Sofia keeps working
```

Esse Gate transforma capabilities já existentes em workflow diário coerente.

---

# 32. SA-B040 — Conversation History & Privacy UX

Conversation History deve ser uma primeira-classe product surface.

Core deve oferecer APIs bounded para:

- listar Conversations;
- abrir Conversation;
- listar Turn history;
- criar nova Conversation;
- resumir metadata básica para list UI.

Paginação/bounds obrigatórios.

Não carregar histórico ilimitado em uma chamada.

---

# 33. Conversation list semantics

Cada item deve fornecer o suficiente para UX, por exemplo:

```text
conversation_id
created_at
updated_at
preview/title
last_turn_state
```

Não usar LLM pago apenas para gerar título no MVP desse Slice.

Baseline simples/determinístico é suficiente, como first user turn truncada com segurança.

Rename/delete podem ser futuros se não forem necessários ao workflow principal.

---

# 34. Resume conversation

Usuário deve poder:

```text
select existing Conversation
↓
load bounded history
↓
continue conversation
```

Provider/model pode mudar entre Turns sem mudar Conversation identity.

ContextBuilder/Memory continuam Core-owned.

---

# 35. Fix do locality hardcode

`CoreApiClient.stream_text()` e Realtime não podem mais forçar:

```text
locality = local_only
cloud_context_eligible = false
```

como comportamento invisível.

Application service deve receber explicit inference privacy preferences.

---

# 36. First-run privacy choice

Antes da primeira inferência humana real, Desktop deve apresentar escolha compreensível equivalente a:

```text
Local only
Allow cloud
Prefer cloud
```

Essa escolha define a policy enviada nas requests.

Separadamente:

```text
Allow cognitive memory/context to be sent to cloud models
```

deve ser opt-in e iniciar `false`.

Não usar linguagem interna como `DataLocality` ou `cloud_context_eligible` na UI principal.

---

# 37. Privacy preference storage

Como request policy, a preferência pode ser UI/client preference desde que:

- seja explícita;
- seja enviada a cada operação relevante;
- Core valide;
- profile não consiga ampliá-la;
- não seja tratada como authorization authority.

Se o Contract definir Core-owned storage, seguir o Contract.

---

# 38. Streaming/chat UX

Melhorar Chat para suportar:

- conversation sidebar/history;
- new conversation;
- resume;
- streaming state;
- cancel/interruption quando runtime suportar;
- safe error recovery;
- current profile/model evidence opcional e não intrusiva;
- no duplicated Turn on reconnect.

Não transformar Chat em provider-specific UI.

---

# 39. SA-B041 — Voice & Operational UX

Fechar a experiência real de voice/operations do Desktop.

Inclui:

- microphone capture;
- audio output playback;
- device selection baseline quando necessário;
- realtime state feedback;
- interrupt/stop;
- confirmation UX;
- Task UX;
- Notification UX;
- Health/degraded UX;
- tray behavior.

---

# 40. Realtime voice hardware loop

A baseline deve provar em Windows real:

```text
microphone PCM/input
↓
existing Realtime protocol
↓
Core/provider
↓
audio output events
↓
speaker playback
```

Não criar segundo Realtime runtime.

Desktop apenas captura/renderiza audio.

Formato deve respeitar contracts atuais ou evolução explicitamente documentada.

---

# 41. Voice privacy/locality

Voice usa a mesma privacy policy escolhida pelo usuário.

`realtime` profile permanece hard requirement de model selection.

Não degradar silenciosamente voice para cloud/local incompatível.

Microphone não fica ouvindo continuamente em background.

Sem wake word neste Slice.

---

# 42. Confirmation UX

Confirmation deve mostrar informação humana útil:

- o que Sofia quer fazer;
- resource alvo;
- efeito esperado;
- permission lifetime quando relevante;
- approve/deny.

Não exibir raw internal objects.

Notification não concede authority.

Approval continua Core-owned flow.

---

# 43. Tasks UX

Melhorar visualização para:

- active/recent tasks;
- status;
- progress/evidence disponível;
- waiting states;
- failure/result;
- cancel quando permitido;
- recovery/reconciliation state quando relevante.

Não criar Task logic no Desktop.

---

# 44. Notifications UX

Suportar:

- unread/pending count;
- native notification quando habilitada;
- in-app list;
- acknowledge;
- actionable navigation para Task/confirmation relevante;
- reconnect sync.

Evitar duplicate native toast para mesma Notification identity.

---

# 45. Health/degraded UX

Human-friendly states devem distinguir:

```text
Sofia ready
AI needs configuration
Memory degraded
Core reconnecting
Realtime unavailable
Scheduler degraded
```

Evitar mostrar stack trace ou component ids como primeira resposta ao usuário.

Advanced diagnostics podem existir em detail panel.

---

# 46. First-run onboarding baseline

Ao final do Slice, uma instalação limpa deve conduzir o usuário por workflow equivalente a:

```text
launch Sofia
↓
Core starts
↓
choose privacy policy
↓
configure provider credential if needed
↓
confirm provider/model/profile readiness
↓
optionally configure Memory
↓
start first conversation
```

Não criar onboarding longo ou marketing tour.

Setup deve focar apenas blockers reais para uso.

---

# 47. Gate I18 tests

Criar:

```text
tests/integration/gate/test_gate_i18_daily_assistant_experience.py
```

Cobrir no mínimo:

- list/create/resume Conversation;
- bounded Turn history;
- history is operational data, not Memory;
- first-run privacy selection;
- `local_only` request actually blocks cloud;
- `cloud_allowed` can select cloud-compatible profile binding;
- cloud Memory context remains disabled until opt-in;
- no duplicate Turn on reconnect;
- microphone/device failure surfaced safely;
- realtime start/stop/interrupt;
- deterministic audio pipeline tests with fake device;
- Task status/cancel;
- confirmation approve/deny;
- Notification acknowledge/reconnect;
- degraded subsystem presentation;
- close-to-tray behavior;
- Core remains alive after UI window closes.

Windows human smoke deve cobrir, quando hardware disponível:

- microphone input;
- speaker output;
- real Desktop startup;
- new/resumed chat;
- tray behavior.

Hardware/provider live smokes podem ser opt-in; deterministic fake correctness permanece CI authority.

Acceptance:

```text
[ ] Conversation History
[ ] create/resume conversation
[ ] locality/privacy UX
[ ] no hardcoded local_only
[ ] cloud context explicit opt-in
[ ] chat streaming UX
[ ] real voice device pipeline baseline
[ ] confirmation UX
[ ] Tasks UX
[ ] Notifications UX
[ ] human degraded states
[ ] first-run flow
[ ] Gate I18 tests green
[ ] full regression green
[ ] remote CI green
```

Fechamento:

```text
GATE I18 CLOSED — REMOTE VERIFIED
SLICE 10 COMPLETED — REMOTE VERIFIED
HUMAN DESKTOP BASELINE READY
```

---

# 48. Security invariants

Preservar explicitamente:

```text
AI proposes. Runtime authorizes. Executor acts.
```

E:

```text
Desktop != authority
localhost != identity
attach credential != provider credential
UI preference != Core authority
Conversation History != Cognitive Memory
profile != authority
```

Nenhum UX improvement autoriza:

- direct Tool execution from UI;
- SQLite access from Desktop;
- provider secret plaintext storage;
- unauthenticated local API;
- arbitrary PID kill;
- direct repository imports from widgets;
- silent cloud fallback;
- Memory as authority.

---

# 49. Persistence

Adicionar migration apenas se necessário para novas Core-owned semantics.

Conversation list/history deve preferir dados já persistidos em Conversation/Turn.

Não criar duplicação de transcript no Desktop.

UI-only state permanece QSettings/local presentation.

Secure attach secret permanece fora do Operational Store.

---

# 50. Audit

Audit deve preservar evidence segura para novas ações relevantes, como:

```text
CLIENT_CORE_ATTACH
CLIENT_CORE_START_REQUESTED
CORE_SHUTDOWN_REQUESTED
PROVIDER_CREDENTIAL_UPDATED
PRIVACY_POLICY_APPLIED
```

Nomes concretos podem seguir conventions existentes.

Nunca registrar:

- bearer credential;
- provider credential;
- audio payload bruto por default;
- full conversation content desnecessário;
- hidden reasoning.

---

# 51. Packaging

Ao final do Slice 10, packaged Windows experience deve ser validada.

Baseline:

```text
user launches Desktop executable
Core starts/attaches automatically
no Python/uv/terminal required
```

Code signing, installer comercial, auto-update e auto-start on login permanecem futuros, salvo necessidade estrita de acceptance aprovada depois.

---

# 52. Quality Gates

Em cada Run:

```powershell
cd core
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
git diff --check
```

Quando Desktop/package mudar:

```powershell
uv run python -m PyInstaller --noconfirm client/SofiaAssistant.spec
# + packaged Core build/spec quando materializado
# + smoke dos executáveis produzidos
```

Não exigir provider pago live no CI.

---

# 53. CI / Remote Verification

Cada Gate exige CI remoto no HEAD correspondente.

Estados:

```text
IMPLEMENTED — LOCAL VERIFIED
IMPLEMENTED — AWAITING REMOTE VERIFICATION
CLOSED — REMOTE VERIFIED
```

Não declarar Slice concluído antes do Gate I18 remoto-verificado.

---

# 54. Commit strategy

Preferir commits por pacote funcional.

Exemplos:

```text
feat(desktop): add secure Core supervision and attach
feat(dashboard): add human AI configuration experience
feat(conversation): add history and privacy controls
feat(voice): add desktop audio device pipeline
test(desktop): validate human experience gates
docs(plan): close Slice 10
```

Não precisa seguir exatamente essa divisão.

---

# 55. Gate closure ledgers

Ao fechar cada Gate registrar:

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

Slice 10 só vai para `completed/` após I18.

---

# 56. Não escopo

Fora deste Slice:

```text
public/VPS Core API
TLS termination
multi-user authentication
mobile client
web client remoto
OAuth provider accounts
billing/cost budget engine
plugin marketplace
full generic settings framework
wake word
continuous microphone
continuous camera
screen awareness loop
code signing
commercial installer
self-update system
auto-update service
distributed Core
central cloud control plane
```

Também não reabrir:

- PySide6 technology selection;
- AI routing architecture;
- Sofias Memory ownership;
- Policy/Tool authority model.

---

# 57. Stop conditions

Parar para decisão humana apenas se:

- secure attach exigir mudança de trust boundary não coberta pelo Amendment/Contract;
- provider credential UX exigir plaintext persistence;
- Core shutdown exigir nova authority model incompatível;
- packaging exigir fundir Core/UI em um único authority process;
- Conversation History exigir redefinir Memory ownership;
- voice hardware contract exigir breaking protocol sem transition path;
- migration destrutiva for necessária;
- network exposure não-loopback se tornar necessário.

Não parar por:

- widget layout;
- naming;
- icon choice;
- view-model organization;
- fixture design;
- minor refactors;
- safe endpoint naming coerente;
- bounded UX polish.

---

# 58. Acceptance final — Gate I16

```text
[ ] Core auto-discovery/start
[ ] secure attach
[ ] authenticated client flow invisible to user
[ ] Core independent from Desktop
[ ] Quit Desktop leaves Core alive
[ ] Stop Sofia graceful and explicit
[ ] duplicate Core prevention
[ ] reconnect baseline
[ ] packaged human startup
[ ] no terminal/token copy
[ ] no secret leakage
[ ] Gate I16 tests
[ ] full regression
[ ] quality gates
[ ] remote CI
```

---

# 59. Acceptance final — Gate I17

```text
[ ] Home dashboard
[ ] provider config UI
[ ] secure provider credential UX
[ ] model catalog UI
[ ] model refresh/discovery UX
[ ] capability provenance UX
[ ] profile/binding editor
[ ] fallback configuration
[ ] routing preview
[ ] Memory/integration status/config UX
[ ] Core validates all writes
[ ] no secret leakage
[ ] Gate I17 tests
[ ] full regression
[ ] quality gates
[ ] remote CI
```

---

# 60. Acceptance final — Gate I18 / Slice 10

```text
[ ] Conversation History
[ ] bounded Turn history
[ ] new/resume conversation
[ ] privacy/locality choice
[ ] no hidden local_only hardcode
[ ] cloud Memory context explicit opt-in
[ ] chat streaming product UX
[ ] realtime microphone/speaker baseline
[ ] confirmations ergonomic
[ ] Tasks ergonomic
[ ] notifications ergonomic
[ ] health/degraded UX
[ ] first-run setup flow
[ ] packaged Windows smoke
[ ] Gate I18 tests
[ ] full regression
[ ] quality gates
[ ] remote CI
```

Fechamento esperado:

```text
GATE I16 CLOSED — REMOTE VERIFIED
GATE I17 CLOSED — REMOTE VERIFIED
GATE I18 CLOSED — REMOTE VERIFIED
SLICE 10 COMPLETED — REMOTE VERIFIED
HUMAN DESKTOP BASELINE READY
```

---

# 61. Estado inicial do Ledger

```text
Slice 10 status:
    READY FOR APPROVAL

Baseline:
    dcf25a3b7231c264d3c3ad860eac7df24bb56532

Previous Slice:
    Slice 09 — COMPLETED — REMOTE VERIFIED

Gate I16:
    BLOCKED BY SLICE APPROVAL + DOCUMENTARY PREREQUISITES

Gate I17:
    BLOCKED BY I16

Gate I18:
    BLOCKED BY I17

Required before implementation:
    Architecture Review Amendment 0004
    Desktop/Core Interaction Contract v1

Next action after Slice approval:
    materialize and approve those two documents
```

---

# 62. Approval effect

Ao alterar este Slice para `APPROVED`, ficam aprovados como direção de produto/arquitetura:

```text
Desktop may start Core but does not own Core
Core remains background-independent
Close -> tray
Quit Desktop -> Core remains alive
Stop Sofia -> explicit graceful Core shutdown
secure attach keeps localhost authentication
client credential remains hidden but real
provider credentials receive purpose-specific secure UX
Dashboard remains Core client
Conversation History remains distinct from Cognitive Memory
privacy/locality becomes explicit human choice
cloud cognitive context remains opt-in
PySide6 remains the Desktop technology
```

A aprovação do Slice não dispensa a materialização/aprovação do Amendment 0004 e do Desktop/Core Interaction Contract v1 antes do Run 1.
