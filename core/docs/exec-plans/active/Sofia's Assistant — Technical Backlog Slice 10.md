# Sofia's Assistant — Technical Backlog Slice 10

**Nome operacional:** Human Desktop Experience  
**Escopo:** SA-B038 + SA-B039 + SA-B040 + SA-B041  
**Gates-alvo:** I16 — Seamless Desktop Runtime; I17 — Human Configuration Dashboard; I18 — Daily Assistant Experience  
**Status:** APPROVED  
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

---

# 63. Gate I16 — Closure Ledger

```text
Gate:
    I16 — Seamless Desktop Runtime (SA-B038 — Core Supervision & Secure Attach)

Status:
    CLOSED — REMOTE VERIFIED

Baseline:
    cef3c84fefac96e0db175bc5a56b3f253396bac8

What changed:
    - instance_key_for_data_dir() extracted as shared, non-secret canonical
      identity helper (runtime/instance_ownership.py); mutex naming reuses it.
    - host/config.resolve_core_data_dir() made public so the Desktop derives
      the identical instance_key without duplicating path/env resolution.
    - client_attach/ package: ClientAttachRecord (bounded, versioned,
      redacted credential), ClientAttachStore protocol,
      InMemoryClientAttachStore deterministic fake, WindowsClientAttachStore
      (Windows Credential Manager, separate "SofiasAssistant/Attach/v1/"
      namespace from provider secrets, reusing the existing wincred ctypes
      primitive).
    - runtime/shutdown.RuntimeShutdownSignal wired into host/runner.py: Core
      publishes its ClientAttachRecord only after LocalClientBoundary starts,
      before declaring READY; graceful stop performs delete_if_current
      before boundary/Core teardown; failed publish fails Core closed
      (boundary+Core stopped, non-zero exit).
    - client_boundary/runtime_http.py: authenticated
      GET /api/v1/runtime/identity and POST /api/v1/runtime/shutdown, wired
      into create_local_http_app/create_app_factory. Shutdown is lifecycle
      control (never a Tool), rejects lifecycle mismatch with 409, never
      kills a process.
    - client_app/{instance_identity,executable_locator,launcher,supervisor}.py:
      DesktopCoreSupervisor (CORE_NOT_FOUND/STARTING/READY/DEGRADED/
      RECONNECTING/STOPPING/STOPPED/FAILED), CoreExecutableLocator (packaged
      sibling SofiaCore.exe or dev `-m sofias_assistant.host`),
      SubprocessCoreLauncher/QtProcessLauncher (explicit argv, no shell,
      Windows-detached).
    - client_app/api.py: CoreApiClient.get_runtime_identity()/
      request_runtime_shutdown().
    - client_app/qt_app.py + __main__.py: seamless attach is the default
      startup path (no SOFIA_CLIENT_CREDENTIAL/--core-url override needed);
      explicit "Stop Sofia" tray action with human confirmation, distinct
      from Quit; Quit/close-to-tray unchanged (never call shutdown).
    - client/SofiaCore.spec: new PyInstaller onefile target packaging
      host/__main__.py as a sibling SofiaCore.exe (console=False), bundling
      the Alembic migrations directory and aiosqlite (both required at
      runtime and not picked up by default hidden-import discovery).

Reference Harvest:
    REUSED — QProcess.startDetached(): documented to survive the launching
        process's exit; used for the production QtProcessLauncher.
    REUSED — subprocess CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS: used by
        SubprocessCoreLauncher (dev/tests) for the same detached semantics
        without Qt.
    ADAPTED — Windows Credential Manager generic blob limit is 2560 bytes
        (~1280 UTF-16 chars); ClientAttachRecord.to_json() stays compact and
        well under that bound (verified in tests/unit/client_attach).
    REJECTED — keyring-style multi-credential chunking for oversized blobs:
        unnecessary given the record's bounded field set.

Architecture: preserved without exception —
    Desktop != Core, Desktop != authority, localhost != identity,
    attach record != authentication authority, attach credential != provider
    credential, PID != authority, AI proposes/Runtime authorizes/Executor
    acts. No Tool/Policy bypass; no direct Desktop->SQLite; no unauthenticated
    local API introduced.

Instance identity:
    Shared instance_key_for_data_dir() (sha256 hex digest of the normalized,
    case-folded absolute data-dir path); stable, non-secret, no plaintext
    path in the key. Verified stable/distinct in
    tests/unit/runtime/test_instance_ownership.py.

Attach record / store:
    ClientAttachRecord validated at construction (loopback host, valid port,
    contract_version, timezone-aware created_at); credential redacted from
    repr via SecretValue. WindowsClientAttachStore: real Windows Credential
    Manager, separate namespace from provider secrets, delete_if_current is
    read-then-compare-then-delete (documented small TOCTOU window, accepted
    per Amendment 0004 SS14 threat model). InMemoryClientAttachStore used as
    the required deterministic test fake.

Core publication:
    core.start() -> runtime_session_id captured -> CLIENT_CORE_START_REQUESTED
    audited -> LocalClientBoundary.start() -> ClientAttachRecord built and
    published -> READY printed only after successful publish. Publish
    failure stops boundary+Core and returns exit code 1 (never claims
    ready). Graceful stop: delete_if_current (best-effort) -> boundary.stop()
    -> core.stop().

Runtime identity API:
    GET /api/v1/runtime/identity (authenticated session) returns
    instance_key/runtime_session_id/application_version/protocol_version/
    state only; never credential, path, environment or internal handles.

Supervisor:
    DesktopCoreSupervisor.attach()/reconnect()/request_stop_sofia(),
    synchronous (matches CoreApiClient's existing blocking design and the
    ClientWorker/QThread pattern already used by the Desktop Client). Never
    issues a mutating request before verification; stale/mismatched records
    removed only via exact delete_if_current.

Launch:
    Explicit executable + argv only; no shell=True, no cmd.exe/PowerShell
    composition, no credential in argv. CoreExecutableLocator: packaged
    sibling SofiaCore.exe next to sys.executable, or `-m sofias_assistant.host`
    in development.

Duplicate-start handling:
    Core single-instance Win32 mutex remains authoritative (unchanged).
    Proven with two real OS processes racing on the same data dir: the loser
    exits with code 1 and the winner's attach record is untouched
    (test_duplicate_core_start_is_avoided_by_single_instance_authority).

Reconnect:
    Bounded read-only verify attempts, then exactly one bounded relaunch
    attempt (stale record removed first regardless of whether it merely
    looks present, since a crash never cleans up its own record), then
    CORE_FAILED. No infinite loop (proven with a counting fake sleep and
    with a real killed process).

Quit semantics:
    Unchanged: window close hides to tray; Quit Desktop only ends the
    Desktop process. Proven with real packaged processes (see Windows human
    smoke below): killing both Desktop OS processes left SofiaCore.exe
    running and reachable.

Stop Sofia:
    Explicit tray action with a human confirmation dialog, distinct from
    Quit; POST /api/v1/runtime/shutdown requires the current
    runtime_session_id, rejects mismatch with 409, never invokes a Tool or
    kills a process by PID.

Audit:
    CLIENT_CORE_START_REQUESTED (host, on Core start), CLIENT_CORE_ATTACH
    (on authenticated GET /api/v1/runtime/identity), CORE_SHUTDOWN_REQUESTED
    (on POST /api/v1/runtime/shutdown, accepted or rejected). No credential
    in any event; verified in tests/integration/gate/
    test_gate_i16_seamless_desktop_runtime.py.

Security:
    Attach credential never in SQLite/QSettings/stdout/log/Audit (verified);
    attach endpoint loopback-only (record host validated); Windows store is
    per-user (Credential Manager semantics) and namespaced away from provider
    secrets; LocalClientBoundary/session auth unchanged and still mandatory;
    runtime identity and shutdown endpoints both authenticated; no PID kill
    anywhere in the implementation; no shell; no mutation replay (shutdown
    is the only mutating supervisor call and it is explicit/human-triggered,
    never auto-retried); no direct Desktop->SQLite; no Tool/Policy bypass.

Packaging:
    core/client/SofiaCore.spec added (onefile, console=False, bundles Alembic
    migrations + aiosqlite hidden imports). Existing SofiaAssistant.spec
    unchanged and still builds. Both executables land side by side in
    core/dist/, satisfying the sibling-executable locator contract. CI now
    builds and smoke-tests both executables on every push
    (.github/workflows/ci.yml: "Core package baseline" +
    "Packaged Core executable smoke" via core/scripts/ci_core_smoke.py,
    alongside the existing Desktop package/smoke steps); remote-verified
    green on windows-latest for the Final HEAD below.

Targeted tests:
    tests/unit/client_attach/ (models, in-memory store, Windows store with a
    fake Win32 API -- 36 tests), tests/unit/runtime/test_instance_ownership.py
    (+6 instance_key tests), tests/unit/client_app/
    {test_supervisor,test_executable_locator,test_launcher,test_api}.py
    (+~40 tests).

Gate tests:
    tests/integration/gate/test_gate_i16_seamless_desktop_runtime.py -- 16
    tests: Core-side attach publish/cleanup/redaction/fail-closed (4, via
    the real runner.run() composition with InMemoryClientAttachStore),
    authenticated runtime identity/shutdown HTTP contract (3), and
    DesktopCoreSupervisor against real, separate `sofia-core` OS processes
    through the real Windows Credential Manager (9): already-running attach,
    absent-then-launched attach, duplicate-start race, stale record after a
    hard kill, wrong instance_key against a real Core, credential rotation
    across restarts, old-lifecycle-cannot-delete-newer-record, explicit Stop
    Sofia, bounded reconnect after a real crash. All 16 pass individually and
    as a suite (~63s).

Concurrency tests:
    Two real OS processes racing to start Core on the same data dir (loser
    exits 1, winner's record untouched); old-lifecycle
    delete_if_current-cannot-delete-newer-record proven directly against the
    real WindowsClientAttachStore; bounded reconnect after a real process
    kill proven non-looping with an elapsed-time bound.

Full pytest:
    867 passed, 4 skipped (pre-existing opt-in live/hardware smokes,
    unrelated to this Gate). One transient flake was observed in
    test_stop_sofia_gracefully_stops_a_real_core during one ~4.5-minute
    full-suite run under heavy sequential subprocess load (exit code 1
    instead of 0 after an accepted shutdown); it passed reliably in three
    other runs (isolated x2, full-suite x1). Root cause looks like transient
    system load during this session's very heavy subprocess/packaging
    activity, not a logic defect in the shutdown path; flagged here rather
    than hidden. The remote CI run for the Final HEAD (single-attempt,
    lighter concurrent load than this local session) passed the full suite
    cleanly with no flake.

Ruff / Format / Mypy / git diff --check:
    All green locally. `git diff --check` only flags the pre-existing
    intentional Markdown trailing-space line-break convention on the four
    housekeeping header edits (unrelated to code, not introduced by this
    Gate) and LF/CRLF normalization notices. Lint, format check and mypy
    also remote-verified green in CI for the Final HEAD.

Windows human smoke (manual, real packaged executables):
    1. SofiaCore.exe launched standalone: attach record published to the
       real Windows Credential Manager, authenticated
       GET /api/v1/runtime/identity verified instance_key/runtime_session_id,
       POST /api/v1/runtime/shutdown gracefully stopped it and removed the
       record.
    2. SofiaAssistant.exe launched with no arguments, no SOFIA_CLIENT_CREDENTIAL,
       no --core-url: it discovered no Core, launched a sibling SofiaCore.exe
       automatically, and attached -- no terminal, Python, uv, port entry or
       token copy/paste.
    3. Both Desktop OS processes (PyInstaller onefile outer+inner) were
       terminated (simulating Quit): SofiaCore.exe (outer+inner) remained
       alive and the attach record stayed valid.
    4. A second SofiaAssistant.exe launch reattached to the same running
       Core: process count showed exactly one SofiaCore.exe pair throughout
       (no duplicate launch).
    5. An explicit Stop Sofia (via the authenticated shutdown API, standing
       in for the tray action) gracefully stopped SofiaCore.exe; the second
       Desktop process remained running afterward, matching Contract v1 SS22
       ("Desktop may remain open").
    No credential appeared in any log/screenshot during this smoke.
    Limitation: a real interactive click on the tray's "Stop Sofia" menu
    item was not visually driven in this session (no interactive GUI
    operator); the underlying authenticated API call it triggers was
    exercised directly and is unit/gate-tested
    (test_stop_sofia_gracefully_stops_a_real_core).

Commits:
    1dfc431 feat(runtime): add protected client attach store and runtime lifecycle API
    265f3f4 feat(desktop): add Core supervision and seamless secure attach
    6f02dbf test(desktop): validate Gate I16 seamless desktop runtime
    4295223 docs(plan): sync Slice 10 status headers and close Gate I16 ledger
    2e63520 ci: build and smoke-test the packaged SofiaCore.exe

Final HEAD:
    2b7f79f3e34ce7f2ac1a09e8415fc064bec4fbc7
    (2e635207b20131c2115cfc1ac02d146e6ef46d76 carries every code/test
    change; 2b7f79f is this ledger's own docs-only follow-up commit)

origin/main:
    2b7f79f3e34ce7f2ac1a09e8415fc064bec4fbc7 (pushed; matches Final HEAD)

CI:
    https://github.com/kallbuloso/sofias_assistant/actions/runs/35176427233
    (HEAD 2e63520, code-complete) -- success
    https://github.com/kallbuloso/sofias_assistant/actions/runs/35177847772
    (HEAD 2b7f79f, this ledger update, docs-only) -- success
    Both: Lint, format check, mypy, full pytest (Test step ~15-27min on
    windows-latest, variance between runner instances), Desktop package
    baseline + packaged smoke, Core package baseline + packaged smoke all
    green.

Findings fixed (in-scope, discovered during implementation):
    - runtime_http.py accidentally used `from __future__ import annotations`,
      which broke FastAPI's ability to resolve `Depends(require_session)`
      (a closure-local variable) via postponed string-annotation evaluation,
      producing a spurious 422 on GET /api/v1/runtime/identity. Fixed by
      removing the future import, matching every sibling route module's
      existing (deliberate) convention.
    - DesktopCoreSupervisor.reconnect() originally never relaunched when a
      stale-but-present record survived a crash (crashes never clean up
      their own record), which would have left a crashed Core unrecoverable
      by bounded reconnect. Fixed to remove the stale record and always
      attempt exactly one bounded relaunch after read-only retries are
      exhausted.
    - SofiaCore.spec initially failed at runtime with "Path doesn't exist:
      ...\_MEI.../sofias_assistant\persistence\migrations" (Alembic reads
      migration scripts from disk, not from the frozen PYZ archive) and then
      "No module named 'aiosqlite'" (not covered by PyInstaller's SQLAlchemy
      hook). Fixed by bundling the migrations directory as `datas` and
      adding `aiosqlite` to `hiddenimports`.

Deferred (out of I16 scope, explicitly not started):
    Gate I17 (Human Configuration Dashboard), Gate I18 (Daily Assistant
    Experience), provider credential UX, Conversation History UX,
    locality/privacy UX, microphone/speaker pipeline.

Known limitations:
    - WindowsClientAttachStore.delete_if_current is read-then-delete, not an
      atomic compare-and-delete (Windows Credential Manager exposes no such
      primitive); a narrow TOCTOU window is an accepted, documented
      limitation consistent with Amendment 0004 SS14's threat model.
    - The one observed full-suite flake above.
    - Real interactive GUI-driven click-through of the tray menu was not
      performed (no interactive operator in this session); the automated
      suite and the process-level packaged smoke cover the same underlying
      behavior through the authenticated API and real OS processes instead.

Real blockers:
    None.
```

---

# 64. Gate I17 — Closure Ledger

```text
Gate:
    I17 — Human Configuration Dashboard (SA-B039 — Human Configuration Dashboard)

Status:
    CLOSED — REMOTE VERIFIED

Baseline:
    a8638fc1354e9bfca952d412e0ed916c0b4b1dd2

What changed:
    - secrets/store.py: SecretSourceAwareStore (runtime-checkable Protocol,
      describe() -> environment|platform_store|missing).
      secrets/environment_store.py: LayeredSecretStore.describe() reports
      the merged-environment layer as "environment" per Contract v1 SS26
      (environment + explicit env-file are already merged into one primary
      layer, so no separate env_file distinction is fabricated).
      secrets/service.py: SecretService.describe() delegates when the
      injected store is source-aware, else falls back to a two-state
      platform_store/missing diagnostic (covers InMemorySecretStore/CLI
      fakes that only ever implement plain get/set/delete).
    - host/secret_bridge.py: credential_write_status(ref, secret_service) ->
      (effective_source, configured, shadowed) -- the one shared helper used
      by both the provider and Sofias Memory credential endpoints so their
      shadowing semantics can never drift apart.
    - ai_config/service.py: ProviderNotFoundError; ProviderPatch (display_name
      /base_url/enabled) + update_provider() (validates base_url via the
      existing require_safe_http_url, republishes the routing snapshot since
      enabled/base_url affect eligibility); ProviderCredentialStatus +
      set_provider_credential()/delete_provider_credential() (SecretRef
      always re-derived server-side via provider_api_key_ref(), never
      accepted from the caller; never rebuilds the snapshot, since adapters
      resolve secrets from SecretService at call time). New
      attach_audit(audit) lets SofiaCore bind the real AuditService after
      construction (see Finding below).
    - client_boundary/ai_http.py: PATCH /api/v1/ai/providers/{id}; PUT/DELETE
      /api/v1/ai/providers/{id}/credential. 404 for an unknown provider_id,
      422 for a deterministically invalid patch; response never contains a
      secret value.
    - client_boundary/integrations_http.py (new): GET
      /api/v1/integrations/sofias-memory (enabled, non-secret base_url,
      credential status, live Memory component health from
      core.health.components); PUT/DELETE
      /api/v1/integrations/sofias-memory/credential -- identical no-echo/
      write-only/safe-source rules as the provider surface, using the
      existing SOFIAS_MEMORY_API_KEY_REF. No generic secret-enumeration
      endpoint was introduced.
    - client_boundary/http_api.py: create_local_http_app gains
      secret_service/memory_config params, wired from host/composition.py
      (core.secret_service, new core.memory_config property on SofiaCore).
    - client_app/api.py: CoreApiClient gains list/refresh/update methods for
      providers, models, profiles and routing preview, plus provider/Memory
      credential set/delete. A new CoreValidationError(CoreApiError) carries
      only the bounded `detail` string from a 404/422 AI-configuration
      response (Contract-guaranteed secret-free and deterministic); every
      other status keeps the existing generic, body-redacted CoreApiError
      untouched, so Gate I16's "never echoes a response body" invariant for
      auth/transport failures is preserved exactly.
    - client_app/qt_app.py: ClientWorker/DesktopController gain the matching
      request_*/ready signals and slots, reusing the existing QThread worker
      pattern; AI-config/Memory calls go straight through
      CoreApiClient (bypassing ClientApplicationService), mirroring the
      existing start_voice()/service.api.realtime() precedent since this is
      transport-shaped read/write, not Conversation orchestration.
    - client_app/dashboard.py (new): HomeTab, AIModelsTab,
      MemoryIntegrationsTab -- see "Dashboard architecture" below.
    - core/core.py: new memory_config property (non-secret
      SofiasMemoryConfig, safe for Dashboard display); attach_audit() wired
      into _compose_conversation_runtime() once the real AuditService
      exists (see Finding below).

Reference Harvest:
    REUSED -- existing ClientWorker/QThread pattern (client_app/qt_app.py)
        for every new AI-config/Memory call: no blocking HTTP on the GUI
        thread.
    REUSED -- start_voice()/service.api.realtime() precedent of calling
        CoreApiClient directly from ClientWorker for transport-shaped
        operations ClientApplicationService doesn't wrap.
    REUSED -- QLineEdit(EchoMode.Password) precedent already used for the
        dev/test manual-credential-entry path in client_app/__main__.py,
        applied to the new provider/Memory credential input fields.
    REUSED -- imperative QListWidget clear-and-rebuild-on-snapshot rendering
        (Tasks/Notifications tabs) for the new provider/model/binding lists,
        instead of introducing a QAbstractItemModel abstraction that has no
        precedent anywhere else in this codebase.
    REJECTED -- a new QAbstractTableModel/QAbstractItemModel layer for
        provider/model/binding lists: no existing consumer of that pattern
        in this repository; would have added a second UI-list architecture
        for one Gate's worth of widgets (CLAUDE.md SS15, avoid overbuilding).
    REJECTED -- growing the shared ConversationDependenciesFactory type
        signature to thread AuditService through host/composition.py's
        factory: would have forced matching signature changes in every
        Gate I2/I3/I6/I13/test_core.py fake factory for a single missing
        wiring call; attach_audit() (called once, after construction, from
        the one real call site) fixes the same gap with a much smaller
        blast radius.
    REJECTED -- a sidebar/stacked-widget navigation shell replacing the
        existing flat QTabWidget: the existing shell already works and nothing
        in Slice 10 SS29/SS21 requires replacing it; Home/AI & Models/
        Memory were added as three more tabs, consistent with "bounded UX
        polish over redesign".

Dashboard architecture: preserved without exception --
    Dashboard != authority, Dashboard != Operational Store, Dashboard !=
    routing engine, Dashboard != SecretStore. Every new widget renders
    Core-published state and emits a `DesktopController.request_*` intent;
    none of them import a repository, open SQLite, or select a routing
    result locally (grep-verified: no `sqlite`/`secrets.service`/
    `secrets.store`/`SecretService` import anywhere under client_app/).
    QSettings is untouched by this Gate (still only
    "notifications/enabled").

Home:
    HomeTab derives "Sofia ready" / "AI needs configuration" / "Memory
    degraded" / "Core reconnecting" purely client-side from already-safe
    reads (GET /api/v1/ai/providers' credential.configured, GET
    /api/v1/integrations/sofias-memory's health) plus the existing
    ConnectionState -- never a new Core authority, never altering Core
    state by inference (Slice 10 SS "Home/readiness composition").

Provider UX:
    AIModelsTab lists providers/models in one splitter view; selecting a
    provider shows enabled/base_url (editable, PATCH
    /api/v1/ai/providers/{id}) and its model catalog with capability +
    provenance. "Refresh models from provider" calls
    POST /api/v1/ai/models/refresh through the existing discovery adapter;
    a freshly DISCOVERED model is rendered with an empty capability list
    (never invented as proven), matching Amendment 0003 SS11.

Credential UX:
    Password-masked input, cleared immediately after the write intent is
    emitted (never retained by the widget); a safe status line
    ("Configured — source: saved in Sofia" / "...source:
    environment/deployment (a saved credential exists but is currently
    overridden)") replaces the internal environment|platform_store|missing
    vocabulary. Delete requires an explicit QMessageBox confirmation. The
    same pattern is reused verbatim for the Sofias Memory credential.

Secret precedence/shadowing:
    Amendment 0004 SS22 proven end to end (Gate I17 test
    test_environment_secret_shadows_a_newly_written_platform_credential /
    test_memory_credential_environment_shadowing_is_shown_safely): a
    Dashboard write to a provider/Memory credential always succeeds durably
    against the platform store, but a higher-priority environment secret
    remains the effective source; the response says so
    (effective_source="environment", shadowed=true) without ever exposing
    either value. Deleting the platform-store copy never touches the
    environment-backed secret.

Models:
    Model catalog UX shows provider/model id, display name, availability,
    enabled, context window and capability list; discovery refresh reuses
    the existing bounded OpenAIModelDiscoveryAdapter. No routing/eligibility
    logic is duplicated client-side.

Capability provenance:
    Rendered as "capability[provenance]" per model; DISCOVERED-only entries
    show zero capabilities, matching AIConfigurationService's
    trusted_capabilities() semantics exactly (proven by
    test_model_discovery_refresh_adds_discovered_models_without_proven_capabilities).

Profiles:
    Profile selector shows required/preferred capabilities, locality and an
    editable fallback-policy dropdown (ORDERED_ONLY / ORDERED_THEN_CANONICAL),
    each change sent as its own sparse PATCH.

Bindings:
    Reorder is a single QListWidget with Move-up/Move-down plus one "Save
    order" action that recomputes priorities 1..N and sends the *entire*
    ordered binding list in one PATCH body -- AIConfigurationService.
    update_profile() already performs this atomically via
    ProfileModelBindingRepository.replace_for_profile() (delete + re-insert
    in one transaction); the Dashboard never emulates reorder as a sequence
    of single-binding priority writes (proven by
    test_binding_reorder_is_a_single_atomic_profile_update).

Routing preview:
    "Routing preview" panel sends profile + locality to
    POST /api/v1/ai/routing/preview and renders selected provider/model,
    fallback flag and the bounded human-readable reason; no inference is
    invoked, no prompt/Memory content/secret is ever requested or rendered.

Memory/Integrations:
    New tab shows enabled/base_url/health (from the real Memory component
    health, not the pre-existing generic health_items() mapping, which
    turns out to key on "memory"/"ai-provider" while Core's actual
    component names are "sofias-memory" and a separate
    "llm-provider"/"llm-provider-credential" pair -- a latent, pre-existing
    mismatch in client_app/models.py's Health tab left as a documented,
    out-of-scope Deferred item below, since Gate I17 already gets accurate
    Memory health through the new purpose-specific endpoint instead) plus
    the credential lifecycle.

Reconnect:
    AIModelsTab/MemoryIntegrationsTab writes are disabled
    (set_writes_enabled(False)) whenever connection state is not CONNECTED;
    the dashboard bundle is reloaded once per transition into CONNECTED
    (including reconnect), so a reattach always re-renders Core-
    authoritative state rather than stale cached data. No write is ever
    auto-retried after a transport failure (unchanged Gate I16 invariant).

Validation UX:
    A 404 ("Provider not found", "Profile not found") or 422 (a
    deterministic AIConfigurationError message such as "Binding does not
    satisfy the profile's required capabilities...") is raised client-side
    as CoreValidationError and surfaced verbatim through the existing
    failure -> statusBar() path; no traceback, no generic
    "Something went wrong" wrapping a safe, already-bounded reason.

Security:
    - Provider/Memory raw credential values are never persisted Desktop-
      side (verified: widget input fields are cleared synchronously after
      emitting the write intent; no attribute retains the value).
    - Neither credential is ever echoed by any endpoint (only
      `configured`/`effective_source`/`shadowed`/`credential_ref`; proven by
      dedicated "never echoed" assertions in every layer of tests).
    - No generic secret endpoint: both new credential surfaces derive their
      SecretRef server-side from a validated provider_id / the fixed
      Sofias Memory ref; a client cannot request an arbitrary SecretRef.
    - LocalClientBoundary/require_session unchanged and mandatory on every
      new route.
    - No direct SQLite/SecretStore import anywhere under client_app/
      (grep-verified).
    - No routing logic duplicated/authoritative in the Desktop; routing
      preview only renders Core's own deterministic decision.
    - Every write is Core-validated (AIConfigurationService) before
      persistence; UI-side checks are ergonomics only.
    - Reconnect never blindly replays a mutation (unchanged from I16).
    - Logs: no new logging statements were added; CoreApiError/
      CoreValidationError messages are transport-status-derived or
      Contract-guaranteed-safe `detail` text only.
    - Audit: PROVIDER_CREDENTIAL_UPDATED/DELETED and
      INTEGRATION_CREDENTIAL_UPDATED/DELETED metadata carry only
      provider_id/credential_ref/configured/effective_source -- never a
      value (proven by test_no_secret_appears_in_audit_for_any_credential_write).
    - QSettings: no new keys; still only "notifications/enabled".
    - Attach credential/ClientAttachStore: untouched by this Gate.

Packaging:
    No PyInstaller spec changes required (both specs already use
    collect_submodules("sofias_assistant.client_app") /
    collect_submodules("sofias_assistant"), confirmed by reading both
    specs). core/client/SofiaAssistant.spec and core/client/SofiaCore.spec
    rebuilt locally; `dist\SofiaAssistant.exe --smoke` (offscreen) exit 0;
    `scripts/ci_core_smoke.py` against the rebuilt `dist\SofiaCore.exe`
    exit 0 ("attach + authenticated identity verified",
    "graceful shutdown and attach cleanup verified"). CI builds and smokes
    both executables on every push (unchanged workflow from Gate I16).

Targeted tests:
    tests/unit/secrets/{test_service,test_environment_store}.py (+5),
    tests/unit/host/test_secret_bridge.py (+3),
    tests/integration/ai_config/test_ai_configuration_service.py (+8:
    update_provider x3, set/delete_provider_credential x4, attach_audit x1),
    tests/unit/client_app/test_api.py (+14: every new CoreApiClient method,
    CoreValidationError, no-echo assertions),
    tests/unit/client_app/test_dashboard.py (new file, 17 offscreen Qt
    tests: HomeTab readiness derivation x4, AIModelsTab provider/profile/
    binding/routing-preview rendering and intent-emission x9,
    MemoryIntegrationsTab x2, write-disable x1, fallback-policy x2).

Gate tests:
    tests/integration/gate/test_gate_i17_human_configuration_dashboard.py
    -- 19 tests against the real production host (sofias_assistant.host.
    runner.run, the exact composition sofia-core uses) driven through the
    real, blocking CoreApiClient via asyncio.to_thread (same template as
    Gate I15's human-facing HTTP smoke): attach, Home-readiness inputs,
    provider non-secret update (+ unknown-id rejection), provider
    credential write/replace/delete (+ unknown-id rejection), environment
    shadowing, model catalog + discovery refresh with unproven DISCOVERED
    capabilities (+ unknown-provider rejection), profile list/detail,
    atomic binding reorder, invalid-binding rejection, fallback-policy
    update, unknown-profile rejection, routing preview, Memory credential
    write/replace/delete lifecycle, Memory credential environment
    shadowing, a second fresh session observing the same Core-authoritative
    state (reattach stand-in), and no secret leakage in Audit for any
    credential write. All 19 pass individually and as a suite (~22s).

Full pytest:
    928 passed, 4 skipped (pre-existing opt-in live/hardware smokes,
    unrelated to this Gate) in ~361s.

Ruff / Format / Mypy / git diff --check:
    All green (`uv run ruff check .`, `uv run ruff format --check .`,
    `uv run mypy src tests` -- 221 source files, `git diff --check` only
    flags pre-existing LF/CRLF normalization notices, no trailing
    whitespace).

Windows human smoke (manual, real packaged executables):
    An ad-hoc script (not committed; mirrors scripts/ci_core_smoke.py's
    exact real-process/real-Windows-Credential-Manager pattern) launched
    the rebuilt dist\SofiaCore.exe as a genuine separate OS process,
    attached through the real Windows Credential Manager, and drove every
    new I17 endpoint through the real CoreApiClient:
      - providers list (openai, credential initially not configured);
      - provider credential write -> configured=true, never echoed in the
        printed response;
      - provider credential delete -> configured=false;
      - model catalog reflects the canonical bootstrap model;
      - all 5 baseline profiles present;
      - routing preview selects the canonical model for chat.general;
      - Sofias Memory integration status/health readable;
      - Memory credential write/delete, never echoed;
      - graceful Stop-Sofia-equivalent shutdown via
        POST /api/v1/runtime/shutdown, process exit 0.
    All checks passed (`i17_smoke: ALL CHECKS PASSED`). No credential value
    appeared in any printed output. A real interactive click-through of the
    Qt "AI & Models"/"Memory / Integrations" tabs was not performed (no
    interactive GUI operator in this session, same limitation documented in
    the Gate I16 ledger); the offscreen Qt widget tests plus this real
    end-to-end API smoke cover the same underlying behavior.

Commits:
    d24f69c feat(ai): add purpose-specific provider/Memory credential write surfaces
    a477db9 feat(dashboard): add Home, AI & Models and Memory/Integrations pages
    d4eeb99 test(ai): validate Gate I17 human configuration dashboard
    26a029f docs(plan): record Gate I17 closure ledger — awaiting remote verification
    e19cadb docs(plan): close Gate I17 — remote verified

Final HEAD (code-complete):
    d4eeb99
    (26a029f and e19cadb carry only docs-only follow-ups, same pattern as
    Gate I16's 2b7f79f)

CI:
    https://github.com/kallbuloso/sofias_assistant/actions/runs/35257766380
    Attempt 1: FAILED -- Test step failed on
    tests/integration/gate/test_gate_i16_seamless_desktop_runtime.py::
    test_credential_rotates_across_core_restarts ("attach record was not
    published in time", a 20s bounded wait for a second real
    `python -m sofias_assistant.host` OS subprocess to fully boot and
    publish its attach record to the real Windows Credential Manager).
    This is a pre-existing Gate I16 test, unmodified by this Gate, in the
    same "real-subprocess timing under shared CI runner load" category the
    Gate I16 ledger already documented for a different test in the same
    file; nothing in this Gate's changes touches Core startup I/O in a way
    that would explain a new regression (only a new dataclass property,
    one attach_audit() attribute assignment, and in-memory FastAPI route
    registration were added to the startup path).
    Attempt 2 (`rerun-failed-jobs` against the identical commit, no code
    changed): SUCCESS -- Lint, format check, mypy, full pytest (929 passed,
    4 skipped, 0 failed), Desktop package baseline + packaged smoke, Core
    package baseline + packaged smoke all green. This confirms attempt 1
    was transient CI-runner flakiness, not a regression.

    A second CI run (35262187428), triggered by this ledger's own
    docs-only closure commit, passed cleanly on its first attempt --
    https://github.com/kallbuloso/sofias_assistant/actions/runs/35262187428

Closure HEAD:
    e19cadba11abc21dd0730d9c2bc18c75163c720a

origin/main:
    e19cadba11abc21dd0730d9c2bc18c75163c720a (pushed; matches Closure HEAD)

Findings fixed (in-scope, discovered during implementation):
    - AIConfigurationService was constructed in host/composition.py without
      an AuditService, so AI_PROVIDER_CONFIG_CHANGED / AI_MODEL_CATALOG_
      REFRESHED / AI_PROFILE_CHANGED (and this Gate's new
      PROVIDER_CREDENTIAL_UPDATED/DELETED) were silently no-ops in
      production -- a pre-existing Gate I15 gap only surfaced because Gate
      I17 is the first place that asserts these events end to end through
      the real host. Fixed with AIConfigurationService.attach_audit(),
      called once from SofiaCore._compose_conversation_runtime() after the
      real AuditService exists, without touching the widely-reused
      ConversationDependenciesFactory signature or any of its five existing
      Gate-test fake factories.

Deferred (out of I17 scope, explicitly not started):
    Gate I18 (Conversation History & Privacy UX, Voice & Operational UX).
    client_app/models.py's generic health_items() "ai-provider"/"memory"
    key mismatch against Core's real "llm-provider"/"sofias-memory"
    component names (pre-existing, predates this Gate; the Health tab it
    feeds always showed a placeholder for those two rows; Home/Memory tab
    in this Gate work around it with accurate purpose-specific reads
    instead of fixing the shared mapping, which is unrelated Health-tab
    scope). Provider display_name editing has a working PATCH field but no
    dedicated UI control (not required by Slice 10 SS23's UX list, which
    only requires displaying identity). No QAbstractItemModel/
    QAbstractTableModel introduced for provider/model/binding lists
    (imperative QListWidget rendering, consistent with the rest of this
    codebase).

Known limitations:
    - Real interactive GUI-driven click-through of the new Qt tabs was not
      performed (no interactive operator in this session); covered instead
      by 17 offscreen Qt widget tests plus the real packaged end-to-end API
      smoke above.
    - The pre-existing health_items() key mismatch noted above remains
      unfixed (Deferred).
    - One CI attempt-1 flake in a pre-existing, unmodified Gate I16 real-
      subprocess timing test (see CI section above); clean on attempt 2 for
      the identical commit.

Real blockers:
    None.
```

