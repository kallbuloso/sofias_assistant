# Sofia's Assistant — Technical Backlog Slice 03

**Slice:** SA-B009 — Realtime Voice / Gate I3

**Status:** ACTIVE — APPROVED

**Baseline auditado:** `9fa1a5168ac70ff5af738eba476679afe4496f01`
**Idioma:** pt-BR; nomes técnicos e contratos em inglês

## Execution Ledger

Este ledger é a fonte versionada do estado operacional da Slice 03. Prompts e
reports de chat não são source of truth. As decisões arquiteturais continuam
pertencendo aos ADRs e às seções arquiteturais deste exec-plan; o ledger
registra execução, checkpoints, commits, CI e o próximo passo.

**Slice:** SA-B009 — Realtime Voice / Gate I3
**Slice status:** ACTIVE
**Gate I3:** OPEN
**Current implementation HEAD:** `48b635d0decf0489657070cafe8718f082d91ebc`
**Current active block:** SA-B009.5b — Provider Session Loss & Failure Lifecycle
**Current next micro-step:** SA-B009.5b.1 — Provider-generation ownership

### Checkpoints concluídos

| Checkpoint | Status | Commit / evidência |
| --- | --- | --- |
| SA-B009.1 — Realtime Contracts, Audio & Routing | DONE — REMOTE VERIFIED | `1fc4045828a865851d224d27e2ca64809a637683` |
| SA-B009.2 — Shared Conversation Coordination, Voice Persistence & Context Seed | DONE — REMOTE VERIFIED | `b1756bdc5d790c521db3ec8a3f66573ad47d0625` |
| SA-B009.3 — Fake Realtime Provider & RealtimeConversationRuntime | DONE — REMOTE VERIFIED | `c2b7cb2c961293a348006623e6567d3b41d42279` |
| SA-B009.4 — Authenticated Local WebSocket Boundary | DONE — REMOTE VERIFIED | Feature `624024444441790bf0d790fef51d4011edab1e40`; docs closeout `80ad7fd53c23f682d509be7e43d4dd427022a471` |
| SA-B009.5a — Interruption / Barge-in / Wire Controls | DONE — REMOTE VERIFIED | Core checkpoint `3fb137f41e22bad731cb2c15ea66afde84f48aab`; WebSocket/vertical checkpoint `48b635d0decf0489657070cafe8718f082d91ebc`; GitHub Actions run `34434466878` SUCCESS |

### SA-B009.5a — ledger de micro-steps

| Micro-step | Status | Result |
| --- | --- | --- |
| SA-B009.5a.1 | DONE | Coordinator Voice Transition Primitive |
| SA-B009.5a.2 | DONE | Runtime Interrupt & Cancel Primitive |
| SA-B009.5a.3a | DONE | Interaction Epoch & Bounded Retirement |
| SA-B009.5a.3b | DONE | Provider Event Gate & Terminal Linearization |
| SA-B009.5a.4 | DONE | Automatic Barge-in & Replacement Lifecycle |
| SA-B009.5a.5a | DONE | WebSocket Controls & Interaction Ownership |
| SA-B009.5a.5b | DONE | Real WebSocket Barge-in Vertical |

Decisões congeladas em SA-B009.5a:

- `voice_transition` serializa decisões de lifecycle por Conversation.
- `response_epoch` de interaction é efêmero e Core-internal; retired interaction IDs são bounded.
- Eventos tardios `RETIRED_KNOWN` são descartados; `UNKNOWN` continua fail-closed.
- Completion versus interrupt é decidido pela ordem de `voice_transition`, nunca por timestamps.
- Automatic barge-in reutiliza/transfere o mesmo `ConversationActivityLease`, sem release/reacquire gap.
- `input_started` com resposta committed delega o replacement atômico ao Core.
- `input_cancelled` e `response.interrupt` usam as primitives Core.
- Evento terminal OLD não pode limpar a ownership de NEW.
- Nenhum epoch ou provider-native ID entra no wire ou na persistence.

### SA-B009.5b — preflight

**SA-B009.5b.0 — Provider Session Loss & Failure Lifecycle Preflight**
**Status:** DONE — REVIEWED
**Code changes:** none

Conclusões arquiteturais congeladas:

- `RealtimeResponseFailed` permanece interaction-scoped.
- `RealtimeSessionFailed` é session-scoped e terminal para aquela Core `RealtimeSession`.
- Provider session loss leva Turn `PROCESSING` a `FAILED` quando materializado, leva a Core realtime session a `FAILED` e preserva a Conversation.
- Explicit close/client disconnect leva Turn `PROCESSING` a `INTERRUPTED` e a Core realtime session a `CLOSED`.
- Session loss não é interruption.
- Completion/session-loss e interrupt/session-loss devem ser linearizados pelo mesmo `voice_transition`.
- Normal-end/exception do provider stream representa session/transport loss; malformed/correlation/ordering continua protocol failure.
- Não haverá retry, fallback ou reconnect transparente nesta slice.

Decisão de provider generation:

`provider_generation` será um contador process-local, monotônico, efêmero, não
persistido, não exposto no wire e não exposto em AI contracts. Cada provider
consumer capturará `provider_session_instance` e `provider_generation`; um
consumer de geração antiga não poderá falhar nem fechar a provider session da
geração nova. `provider_generation` não reutiliza `response_epoch`, pois as
responsabilidades de interaction generation e provider-session generation são
distintas.

### Plano operacional SA-B009.5b

| Micro-step | Status | Objective |
| --- | --- | --- |
| SA-B009.5b.0 | DONE — REVIEWED | Session-loss preflight |
| SA-B009.5b.1 | NEXT | Provider-generation ownership |
| SA-B009.5b.2 | PLANNED | Session-failure terminal semantics |
| SA-B009.5b.3 | PLANNED | Completion/interrupt/session-loss race matrix |
| SA-B009.5b.4 | PLANNED | Boundary/session-loss acceptance |
| SA-B009.5b.5 | PLANNED | Regression and remote checkpoint |

Depois seguem, sem detalhamento adicional neste ledger: `SA-B009.5c` —
Backpressure & Resource Bounds; `SA-B009.5d` — Final Hardening / Gate Evidence;
`SA-B009.6` — OpenAI Realtime Adapter.

Regra do ledger: em cada checkpoint remoto relevante, atualizar o status do
micro-step, registrar commit SHA, registrar CI quando aplicável, registrar nova
decisão congelada relevante e atualizar `NEXT`. Não registrar comandos
individuais, logs completos de pytest, prompts ou reports brutos.

## 1. Objetivo e Gate I3

Entregar a primeira vertical slice de voz realtime preservando uma única
`Conversation` Core-owned: áudio por `push-to-talk` (PTT), streaming de áudio
bidirecional, transcript final durável, resposta falada, `barge-in`, autenticação
local e reload da Conversation. O Gate I3 passa somente se a voz for mais uma
modalidade da Conversation — jamais uma sessão do provider que passou a ser
autoridade.

Não é objetivo criar wake word, VAD, escuta contínua, UI desktop, política,
tools, memória, um segundo router, nem recovery geral de sessões realtime.

## 2. Baseline e invariantes herdados

G1 e G2 estão fechados no remoto. Mantêm-se ADR-0001 (Core persistente, client
desacoplado), ADR-0002 (SQLite operacional e migrations), ADR-0004 (routing por
capability/locality), ADR-0005 (Conversation e Context pertencem ao Core),
ADR-0006/0007 (nenhuma autoridade implícita), ADR-0008 (nenhuma execução de
Tool) e ADR-0015 (correlação sem registrar payloads excessivos).

O estado atual tem `TextConversationRuntime`, `ContextBuilder`,
`CapabilityRouter`, `ModelRegistry`, `ProviderBinding`, `Turn` durável e
HTTP/NDJSON autenticado. `TurnInputModality` contém somente `TEXT`; portanto
`VOICE` requer evolução explícita do domínio e migration. O lock atual de texto
declara expressamente que streaming/realtime revisitará sua granularidade.

## 3. Decisões de planejamento

| Estado | Decisão |
| --- | --- |
| FROZEN | MVP é PTT/hotkey explícito; wake word, VAD e escuta contínua estão deferred. |
| FROZEN | Uma `Conversation` é a autoridade para texto e voz; identidade de provider nunca é identidade Core. |
| FROZEN | Audio bruto, frames, parciais e IDs de sessão do provider são efêmeros e não entram no Operational Store. |
| FROZEN | O HTTP NDJSON de texto existente permanece compatível e inalterado. |
| FROZEN | O primeiro realtime provider da Slice 03 é OpenAI; modelo realtime, transporte SDK/API e acesso/custo atual são pré-condições a validar antes do adapter. |
| FROZEN | O perfil canônico MVP é `PCM16`, 24 kHz, mono; `AudioFormat` permanece explícito e provider-neutral. |
| FROZEN | Realtime usa WebSocket local autenticado, separado do HTTP, com controles JSON e frames binários. Materializado em SA-B009.4/SA-B009.5a. |
| FROZEN | `RealtimeProvider` é contrato especializado; `TextGenerationProvider` não é ampliado para áudio. Materializado em SA-B009.1. |
| FROZEN | Uma única `RealtimeSession` efêmera ativa por `Conversation`; não criar tabela de realtime session. Materializado em SA-B009.3. |
| FROZEN | Uma `ConversationActivityCoordinator` única, Core-owned, coordena texto e voz sem tratar sessão idle como conflito. Materializado em SA-B009.2/SA-B009.5a. |

As decisões PROPOSED devem ser congeladas no início do subpass que as materializa;
nenhuma altera ADR aceita.

## 4. Limites de arquitetura

```text
Desktop/CLI futuro
        │ PTT controls + binary audio
        ▼
LocalClientBoundary WebSocket ── transport DTOs ── RealtimeConversationRuntime
                                                       │
                         ContextBuilder ─ Router ─ RealtimeProvider
                                                       │
                                    Conversation / Turn repositories / SQLite
```

O WebSocket não entra em `conversation/`, `context/`, `ai/` ou persistence.
O provider não recebe `AsyncSession`, rota HTTP, credencial de client ou poder
de gravar Conversation. O Core não importa FastAPI/WebSocket/SDK. Não haverá
store de áudio, event sourcing, `alembic.ini`, novo processo, generic media
framework, VAD engine ou abstração para plataformas inexistentes.

## 5. Contrato especializado de provider

**PROPOSED.** Acrescentar em `ai/contracts.py` tipos explícitos, imutáveis e
provider-neutral: `AudioFormat`, `RealtimeSessionId`, `RealtimeInteractionId`,
`RealtimeSessionRequest`, `RealtimeContextSeed`, `AudioInputFrame` e
`RealtimeProviderEvent`. `AudioFormat` valida codec, sample rate, canais e
limites. O profile MVP é validado no boundary como `PCM16/24000/1`; o contrato
não embute endian ou outro detalhe de wire antes da validação do adapter OpenAI.

Em `ai/providers.py`, introduzir `RealtimeProvider` e uma sessão retornada por
`open_realtime_session(...)`, com operações separadas `send_audio`,
`commit_interaction`, `interrupt` e `close`, e um `AsyncIterator` de eventos.
Eventos normalizados incluem `UserTranscriptPartial`, `UserTranscriptFinal`,
`AssistantAudioChunk`, `AssistantTranscriptPartial`, `AssistantTranscriptFinal`,
`RealtimeResponseCompleted` e `RealtimeResponseFailed`. Eles carregam IDs Core
de session/interaction, sequência monotônica e metadados seguros; IDs nativos só
ficam no adapter efêmero.

O contrato permite eventos de resposta do assistant antes de `UserTranscriptFinal`.
Até a finalização do transcript, eles pertencem apenas à
`RealtimeInteraction` efêmera; o runtime não cria Turn fictício nem exige buffer
de áudio ilimitado. Quando o transcript final não vazio chega, a interação é
associada ao Turn durável que então poderá receber a terminalização correta.
`ProviderError` e sua taxonomia existente
continuam a origem da falha normalizada; erros de protocolo/boundary recebem um
erro Core seguro específico, não uma exceção de SDK.

## 6. Capabilities, registry e routing

**PROPOSED.** Estender `Capability` minimamente com `REALTIME`, `AUDIO_INPUT`
e `AUDIO_OUTPUT`. Um modelo elegível a voz requer as três; o binding exigirá
`realtime: RealtimeProvider` quando `REALTIME` estiver declarado. O
`CapabilityRouter` existente continua sendo o único router e recebe
`AIRequestRequirements(required_capabilities=...)` e `DataLocality` do comando
realtime. Não há `RealtimeRouter`, fallback oculto ou downgrade para STT → LLM
→ TTS.

`ModelDescriptor.execution_location` e a filtragem de `ContextBuilder` seguem
valendo. `LOCAL_ONLY` jamais seleciona cloud. A escolha de modelo é resolvida no
início da sessão e é registrada em campos já existentes apenas quando um Turn
durável é criado; trocar provider não troca Conversation.

## 7. Sessão Core-owned e concorrência

**PROPOSED.** `RealtimeConversationRuntime` será um runtime separado de
`TextConversationRuntime`, injetado por `SofiaCore`, mas ambos compartilham uma
única `ConversationActivityCoordinator` Core-owned. Não é storage, lock
distribuído nem framework genérico: ela serializa a decisão de iniciar,
terminalizar ou interromper trabalho por `Conversation`. Uma sessão conectada e
`IDLE` não bloqueia texto; somente uma `RealtimeInteraction` capturando/aguardando
resposta ou assistant output in-flight conflita com nova operação textual.
Uma segunda sessão realtime para a mesma Conversation falha conflito;
Conversation distintas podem avançar concorrentemente.

`RealtimeSession` é dataclass efêmera com UUID Core, `conversation_id`, modelo
selecionado, formato, `provider_context_stale` e estado (`OPEN`, `IDLE`,
`ACTIVE`, `CLOSED`, `FAILED`). `RealtimeInteraction` é o objeto efêmero entre
`input_started` e `UserTranscriptFinal`/terminalização; não é Turn. A sessão não
persiste e desaparece em restart. A reabertura reconstitui contexto do store,
não uma sessão nativa do provider. Desconexão fecha a sessão e interrompe apenas
o Turn que ainda esteja `PROCESSING`.

## 8. Contexto realtime antes da fala

**PROPOSED.** Adicionar uma seam explícita em `ContextBuilder`, por exemplo
`build_realtime_seed(conversation_id, locality, model) -> RealtimeContextSeed`.
Ela produz `SYSTEM` mais o mesmo sufixo contíguo, elegível, limitado por
`max_recent_turns`, budget e `context_window` que o texto usa. Não recebe
`user_text`, não cria Turn e não envia transcript integral ao provider.

O seed é entregue no `RealtimeSessionRequest` ao abrir o provider. A interaction
de áudio só gera material durável depois de `UserTranscriptFinal` não vazio.
Assim a regra é explícita: ContextBuilder continua sendo dono da projeção; a
conversation interna do provider, se houver, é cache de transporte descartável
e não deve receber histórico além do seed Core-owned.

Quando um `TextConversationRuntime` terminaliza um Turn enquanto a
`RealtimeSession` correspondente está conectada e `IDLE`, a
`ConversationActivityCoordinator` marca `provider_context_stale=True`; o texto
não é bloqueado. Antes de `input_started` seguinte, `RealtimeConversationRuntime`
fecha a sessão nativa, reconstrói o seed com `ContextBuilder` e abre nova sessão
do provider. A prova mixed-modality deve observar essa recriação e confirmar que
o próximo Turn de voz vê o Turn textual novo.

## 9. Durabilidade de Turn de voz

**PROPOSED.** `RealtimeInteraction` começa em `input_started`, recebe os frames,
parciais e até eventual áudio/transcript do assistant, mas não é persistida.
Após transcript final válido, o runtime cria e commita um `Turn`
`PROCESSING` com `input_modality=VOICE`, `user_text=<transcript final>` e a
mesma sequência da Conversation. Parciais de usuário/assistant e áudio jamais
são persistidos. `AssistantTranscriptFinal` + término bem-sucedido produzem
`COMPLETED` com `assistant_text` final; falha segura produz `FAILED`; barge-in
produz `INTERRUPTED` com o texto parcial já recebido, se existir.

Um Turn `INTERRUPTED` é excluído da projeção histórica padrão atual, pois não é
resposta final confiável; isso usa o mesmo `ContextBuilder`, não uma exceção
realtime. Se PTT for cancelado antes de transcript final, não existe Turn. Não
se armazena áudio, blob, URL de áudio, transcript parcial, sessão provider ou
um novo `realtime_sessions` table.

Se provider/sessão falhar antes de `UserTranscriptFinal`, o runtime terminaliza
somente a `RealtimeInteraction` efêmera e a Conversation permanece inalterada.
Se falhar depois da materialização, terminaliza o Turn `FAILED` ou
`INTERRUPTED`, conforme a causa e a decisão já serializada; nunca o marca
`COMPLETED` sem término bem-sucedido da interação.

## 10. Schema e migration mínima

**PROPOSED para execução futura; não migrar nesta slice de planejamento.**
Adicionar `VOICE` a `TurnInputModality`, ao `SqlEnum` de `TurnRecord` e criar
uma migration Alembic incremental após `0003`. Como SQLite materializa a
constraint enum, a migration deve recriar/alterar a tabela por operação Alembic
segura preservando todos os valores, índices, FK/unique/check constraints e
linhas existentes; o downgrade deve remover `VOICE` somente quando não houver
linhas VOICE (ou falhar explicitamente, nunca apagar dados). Testes de migration
devem provar upgrade de banco no head anterior e reload de ambos TEXT/VOICE.

Não há mudança em schema de Conversation, nova tabela, coluna de áudio ou
migration dinâmica no runtime.

## 11. PTT e comando de áudio

**PROPOSED.** O client inicia `input_started(interaction_id)`; envia frames
binários em ordem; emite `input_committed(interaction_id)` para finalizar a fala
e solicitar resposta. `input_cancelled(interaction_id)` descarta uma captura sem
transcript final. Nenhum controle contém
bytes em base64. O hotkey é responsabilidade do client futuro e se traduz
somente nesses comandos; o Core não conhece teclado, microfone ou device.

Cada `RealtimeSession` tem uma interação de entrada ativa por vez. Portanto os
frames binários não precisam de envelope customizado ou cabeçalho
provider-specific: ficam correlacionados ao `interaction_id` do controle ativo;
uma sequência monotônica interna detecta duplicação/gap. Antes de
`input_committed`, não há geração automática, timeout de silêncio ou detecção de
voz.

## 12. WebSocket local autenticado

**PROPOSED.** Adicionar ao `LocalClientBoundary` uma rota WebSocket dedicada,
por exemplo `/api/v1/realtime`, limitada ao mesmo loopback do servidor atual.
O socket abre `UNAUTHENTICATED`; o primeiro frame JSON, limitado e sem logging,
é `authenticate` com o Bearer credential existente e `ClientSession` UUID. O
autenticador/registry existentes validam ambos e somente então o socket torna-se
`AUTHENTICATED`. Não depende de `Authorization` no upgrade. A credencial nunca
aparece em URL/query, log, repr ou evento. Bearer sozinho, sessão sozinha, UUID
inválido e sessão revogada fecham sem revelar detalhes; antes da autenticação não
há áudio, controle privilegiado ou abertura de sessão.

O HTTP continua para lifecycle/texto/estado; não se converte NDJSON em
WebSocket e não se usa SSE para áudio bidirecional. DTOs Pydantic, códigos e
redaction ficam em `client_boundary`; o runtime recebe somente comandos Core.

## 13. Wire contract e correlação

**PROPOSED, versionado como `realtime.v1`.** Controles JSON cliente→Core:
`authenticate`, `session.open`, `input_started`, `input_committed`,
`input_cancelled`, `response.interrupt`,
`session.close`. Controles Core→cliente: `session.opened`, `interaction.started`,
`user_transcript.partial`, `user_transcript.final`, `turn.started`,
`assistant_output.started`, `assistant_transcript.partial`,
`assistant_transcript.final`, `turn.completed`, `turn.interrupted`,
`turn.failed`, `session.failed`, `session.closed`.

Todo controle traz `protocol_version`, `realtime_session_id`,
`conversation_id`, `interaction_id` quando aplicável e `sequence`; nenhum contém
segredo ou ID nativo. Após `assistant_output.started`, os bytes binários
Core→cliente pertencem à interaction anunciada até o próximo controle terminal.
Áudio cliente→Core é permitido apenas entre `input_started` e
`input_committed`/`input_cancelled`. Frames
fora de estado, JSON inválido, tamanho excessivo ou sequência inválida fecham
ou falham a sessão de modo client-safe.

## 14. Barge-in: semântica e corrida

**PROPOSED.** Um `input_started` durante output do assistant é o sinal de
barge-in: o Core primeiro lineariza a sessão em `INTERRUPTING`, invalida o epoch
da resposta, para entrega de áudio local e ordena `RealtimeProvider.interrupt`.
Somente depois anuncia a nova `RealtimeInteraction`. Eventos tardios do epoch anterior são
descartados e nunca retornam ao client nem completam Turn.

Se a interrupção vence antes da persistência terminal, o Turn em processamento
é commitado `INTERRUPTED` uma única vez; se `COMPLETED` já foi commitado antes
de o interrupt ser aceito, não há reescrita retroativa e o novo PTT cria outra
interação/Turn. O vencedor completion-versus-interrupt é definido pela ordem
serializada no `ConversationActivityCoordinator`, nunca por timestamps. Uma
chamada interrupt sem resposta ativa é idempotente no Core. Provider cancel
falho/timeout produz falha segura da sessão, preservando o terminal já gravado e
fechando o lease. Esta regra evita áudio pós-interrupt e também evita uma corrida
transformar cancelamento em sucesso.

## 15. Backpressure, limites e shutdown

**PROPOSED.** As filas de entrada e saída são `asyncio.Queue` pequenas e
limitadas por contagem e bytes; `max_frame_bytes`, frames pendentes e bytes
pendentes são constantes/configuração validada no boundary. Não há fila
infinita, concatenação de áudio em memória ou `sleep` em testes. Ao atingir
limite de entrada o reader deixa de consumir até haver capacidade (TCP aplica
backpressure); frame que viola limite encerra a sessão. Saída lenta aguarda o
drain limitado; se a conexão some, cancela a entrega e aplica a semântica de
desconexão da seção 7.

`session.close`, shutdown do boundary e shutdown do Core são cooperativos:
parar input, interromper provider, fechar iterators/tasks, terminalizar Turn
PROCESSING quando existente e liberar lease. Nenhum raw frame vira AuditEntry;
observabilidade futura usa IDs/estado/tamanho/erro seguro, sem transcript ou
áudio por padrão.

## 16. Provider real OpenAI: pré-condições delimitadas

**FROZEN.** OpenAI é o primeiro realtime provider da Slice 03. O adapter continua
isolado e não decorre do adapter textual existente. Antes do subpass do adapter,
validar somente as pré-condições externas: modelo realtime exato, mecanismo
atual de SDK/API/transport e compatibilidade atual de acesso/custo. A validação
também confirma que o adapter pode preservar PTT, cancelamento, transcript e
SecretService sem vazar SDK ao Core. Referência técnica: [OpenAI Realtime API](https://platform.openai.com/docs/api-reference/realtime) e [eventos de cancelamento](https://platform.openai.com/docs/api-reference/realtime-client-events).

Se a pré-condição não for satisfeita, não se adiciona dependência nem se troca o
design por pipeline STT/LLM/TTS; a implementação para antes do adapter. Isso não
reabre a escolha de provider congelada nesta revisão.

## 17. Secrets, segurança e privacy

O adapter real resolve somente `SecretRef("providers/openai/api-key")` por
`SecretService`, no menor escopo, como o smoke de texto já comprovou. Não usar
variável `OPENAI_API_KEY`, fixtures com segredo, URL, configuração serializada,
logs ou erro para transportar credenciais. O adapter recebe `SecretValue`, não
o boundary.

Audio bruto e transcript parcial não vão para SQLite, audit ou logs. O transcript
final é o conteúdo escolhido pelo usuário ao commitar PTT e segue a política
`cloud_context_eligible`; isso não concede envio cloud — ContextBuilder e Router
continuam aplicando suas responsabilidades distintas. Não há ToolCall/policy
execution introduzidos por voz.

## 18. Fake determinístico e testes de contrato

Criar `ScriptedFakeRealtimeProvider` em `core/tests/support/ai.py` ou módulo de
suporte coeso. Ele recebe roteiro explícito de frames/eventos, grava requests
normalizados e expõe barreiras `asyncio.Event` para orquestrar corrida. Não usa
rede, hardware, SDK, relógio real, aleatoriedade ou `sleep`. Seus bytes são
payloads sintéticos curtos, não gravações.

Testes unitários cobrem validação de contracts, formatos, capability/binding,
ordem de eventos, seed sem user fictício, fila/limites, transições de sessão,
barge-in e ignorar evento tardio. Contract tests cobrem resposta anterior ao
transcript final dentro de `RealtimeInteraction`, materialização posterior do
Turn, falha antes/depois dela, normalização de failure/cancel e `close`
idempotente.

## 19. Integração, migration e boundary tests

Integration tests usam SQLite Alembic em `tmp_path`, runtime/Core reconstruído,
router real e fake. Cobrir VOICE `PROCESSING → COMPLETED`, falha e interrupted;
turns TEXT e VOICE mistos e reload; upgrade da migration; contexto limitado e
locality; e exclusão de audio/raw partial do store.

Boundary tests usam Uvicorn real em loopback/porta `0`, WebSocket real e sessão
real registrada. Cobrir missing/invalid/revoked Bearer+ClientSession, binário
antes de PTT, oversize/backpressure, disconnect e redaction. Não depender de
microfone, speaker, 0.0.0.0, porta fixa, browser ou provider externo.

## 20. Smoke real opt-in

No subpass OpenAI, adicionar teste separado marcado por variável
explícita, por exemplo `SOFIAS_ASSISTANT_RUN_OPENAI_REALTIME_TESTS=1`. Ele usa
`SecretService`/Windows Credential Store, nunca CI padrão, não imprime chave e
não substitui Gate determinístico. Um fixture PCM pequeno, versionado, não
sensível e com licença/proveniência aprovada será introduzido somente nesse
subpass; o teste pode validar connect → PTT → transcript/resposta → cancel/close
sem device humano. Se a fixture/proveniência ainda exigir decisão, ela é o único
item `OPEN`; modelo, SDK/API transport e acesso/custo são pré-condições
`DEFERRED` da seção 16. O Gate I3 determinístico não é falsamente promovido a
evidência externa.

## 21. Subpassos e commits

### SA-B009.1 — Realtime Contracts, Audio & Routing

**Status:** DONE — REMOTE VERIFIED (`1fc4045828a865851d224d27e2ca64809a637683`)

**Goal:** contracts especializados, `AudioFormat` e routing mínimo. **Scope:**
seção 5/6, perfil `PCM16/24000/1` no boundary e binding `RealtimeProvider`.
**Non-goals:** fake, persistence, runtime, transport e SDK. **Invariants:**
contrato provider-neutral, sem áudio em DB, sem alterar texto. **Acceptance:**
modelo sem as três capabilities é rejeitado e formato incompatível falha claro.
**Likely files:** `ai/contracts.py`, `ai/providers.py`, `ai/registry.py`, testes
AI. **Commit:** `feat(ai): add realtime contracts and routing`.
**Dependency:** nenhuma.

### SA-B009.2 — Shared Conversation Coordination, Voice Persistence & Context Seed

**Status:** DONE — REMOTE VERIFIED (`b1756bdc5d790c521db3ec8a3f66573ad47d0625`)

**Goal:** estabelecer autoridade comum de texto/voz antes de streaming.
**Scope:** `ConversationActivityCoordinator`, `VOICE`, migration, seed/rebuild e
marca de contexto stale. **Non-goals:** provider real, fake, WebSocket e
orchestration realtime. **Invariants:** sessão idle permite texto; texto torna o
contexto realtime stale; Turn nasce somente após transcript final; transações não
abrangem I/O. **Acceptance:** migration/reload, mixed modality idle→text→stale e
seed bounded/locality-safe. **Likely files:** `conversation/`, `context/`,
`core/`, `persistence/migrations/versions/`, tests. **Commit:**
`feat(conversation): coordinate voice persistence and context`. **Dependency:**
B009.1.

### SA-B009.3 — Fake Realtime Provider & RealtimeConversationRuntime

**Status:** DONE — REMOTE VERIFIED (`c2b7cb2c961293a348006623e6567d3b41d42279`)

**Goal:** materializar orchestration de domínio antes do transporte.
**Scope:** `ScriptedFakeRealtimeProvider`, `RealtimeConversationRuntime`,
`RealtimeInteraction`, materialização/falha antes/depois do Turn e lifecycle de
sessão provider. **Non-goals:** WebSocket, SDK, hardware. **Invariants:**
WebSocket não orquestra lifecycle; provider output pré-transcript fica efêmero;
uma instância de coordinator é compartilhada. **Acceptance:** roteiros
determinísticos para output precoce, failure, close e session loss. **Likely
files:** `conversation/` ou módulo runtime coeso, `core/`, `tests/support/`,
unit/integration tests. **Commit:** `feat(conversation): add realtime runtime`.
**Dependency:** B009.2.

### SA-B009.4 — Authenticated Local WebSocket Boundary

**Status:** DONE — REMOTE VERIFIED (`624024444441790bf0d790fef51d4011edab1e40`)

**Goal:** bridge loopback real, sem lógica de domínio. **Scope:** primeiro frame
`authenticate`, JSON/binary, `input_started`/`input_committed`, DTOs/redaction e
real socket. **Non-goals:** orchestration, UI/hotkey, SSE e alteração HTTP.
**Invariants:** nenhum controle privilegiado/audio pré-auth; sem credencial URL;
binário usa interação ativa, não envelope próprio. **Acceptance:** autenticação
adversarial, frames inválidos e happy path loopback. **Likely files:**
`client_boundary/`, boundary tests. **Commit:**
`feat(client): add authenticated realtime websocket`. **Dependency:** B009.3.

**Local verification (2026-09-08):** authenticated TCP loopback WebSocket,
authentication/protocol/security matrix, Core-terminal and disconnect cleanup,
explicit outbound event/audio framing, real SofiaCore + SQLite + Uvicorn
vertical with durable VOICE Turn, and HTTP/NDJSON coexistence all pass locally.
Evidence: Gate I3 `2 passed`; HTTP/client-boundary targeted regression `96
passed`; realtime runtime targeted regression `6 passed`; full suite `428
passed, 2 skipped`; Ruff, format, mypy, `uv lock --check`, and `git diff
--check` pass.

**Remote verification:** Commit `624024444441790bf0d790fef51d4011edab1e40`.
GitHub Actions CI run `34305314695` concluded `success`; `main` points to the
commit above, and remote CI passed lint, format, mypy/type check, and tests.
Gate I3 remains OPEN; SA-B009.5 is the next step and SA-B009.6 remains
subsequent work.

### SA-B009.5 — Barge-in, Session Loss & Backpressure Hardening

**Goal:** fechar corridas e limites de recurso. **Scope:** epoch interno,
ordenação pelo coordinator, cancel, late events, disconnect, stale-session
recreate e filas bounded. **Non-goals:** retry/fallback, VAD e recovery geral.
**Invariants:** interrupt não vira completed; sessão idle não bloqueia texto;
output tardio não escapa. **Acceptance:** barreiras determinísticas cobrem
completion-versus-interrupt, session loss e mixed-modality reseed. **Likely
files:** realtime runtime/boundary/tests. **Commit:**
`feat(realtime): harden interruption and session lifecycle`. **Dependency:**
B009.4.

### SA-B009.6 — OpenAI Realtime Adapter

**Goal:** adapter real isolado e smoke opt-in. **Scope:** adapter, SecretService,
mecanismo SDK/API aprovado, fixture/evidence de smoke. **Non-goals:** alterar
contracts Core ou adicionar lockfile sem dependency aprovada. **Invariants:** SDK
só no adapter; OpenAI session é cache efêmero; nenhuma chave no wire. **Acceptance:**
pré-condições externas satisfeitas, smoke opt-in e fake suite preservada.
**Likely files:** `ai/adapters/`, config/tests/live. **Commit:**
`feat(ai): add openai realtime adapter`. **Dependency:** B009.1–B009.5 e
pré-condições da seção 16.

### Integration Hardening → Gate I3 Audit/Smoke

**Goal:** auditar implementação e registrar evidence. **Scope:** harness final,
quality gates e fechamento documental. **Non-goals:** feature adicional.
**Invariants:** smoke externo só opt-in. **Acceptance:** cenário da seção 22.
**Likely files:** `tests/integration/gate/`, `docs/exec-plans/`. **Commit:**
`docs(gate): close realtime voice evidence`. **Dependency:** B009.1–B009.6.

## 22. Cenário final Gate I3 (determinístico)

1. iniciar `SofiaCore` e `LocalClientBoundary` loopback em porta `0`;
2. abrir `ClientSession` com credential runtime;
3. provar que JSON privilegiado e binário antes de `authenticate` falham;
4. provar que Bearer sem sessão e sessão sem Bearer no primeiro frame falham;
5. autenticar WebSocket e criar Conversation pelo HTTP existente;
6. abrir `RealtimeSession` na mesma Conversation com modelo fake compatível;
7. confirmar seed `SYSTEM` e history bounded/locality-safe;
8. enviar `input_started(interaction_id)`, frames binários e
   `input_committed(interaction_id)`;
9. observar transcript parcial e eventual output precoce somente na
   `RealtimeInteraction` efêmera;
10. receber `UserTranscriptFinal`, materializar `Turn 1 VOICE PROCESSING` e
    completar `Turn 1` com transcript/audio final;
11. manter a mesma `RealtimeSession` conectada e `IDLE`;
12. enviar texto pelo HTTP na mesma Conversation e completar `Turn 2 TEXT`,
    sem bloquear pela sessão idle;
13. provar `provider_context_stale=True`, fechamento/recriação da sessão nativa
    e novo seed contendo `Turn 2` antes da próxima voz;
14. iniciar/completar `Turn 3 VOICE`, provando continuidade mixed-modality;
15. iniciar `Turn 4 VOICE`, bloquear o fake durante output e iniciar nova input
    interaction para barge-in;
16. provar que `Turn 4` torna-se `INTERRUPTED` pela ordem do coordinator e que
    áudio/eventos tardios do epoch anterior não chegam;
17. completar a nova interação como `Turn 5 VOICE COMPLETED`;
18. provocar session/provider failure antes de transcript final e provar que
    nenhuma fake durable Turn existe e a Conversation sobrevive;
19. provocar failure após materialização em nova interação e obter `FAILED`,
    depois abrir outra sessão para a mesma Conversation;
20. parar boundary antes do Core, recriar Core/store e carregar a mesma
    Conversation com turns TEXT/VOICE e estados terminais corretos.

Também provar que nenhum evento contém segredo/raw audio e que não há mais de
uma sessão realtime ativa por Conversation.

## 23. Quality gates futuros

Em `core/`, cada subpass executa:

```text
uv sync --locked
uv run python -m sofias_assistant
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
git diff --check
```

Dependency aprovada em B009.5 exige primeiro revisão explícita do diff
`pyproject.toml`/`uv.lock`, depois `uv sync` e ao final `uv sync --locked`.
O smoke real nunca é parte do `pytest` default/CI.

## 24. Arquivos prováveis

Produção futura, somente quando o subpass correspondente for autorizado:
`ai/contracts.py`, `ai/providers.py`, `ai/registry.py`, adapter isolado,
`conversation/models.py`, novo módulo realtime coeso em `conversation/` ou
`core/`, `context/models.py`, `context/builder.py`, `core/core.py`,
`core/composition.py`, `client_boundary/http_api.py`/módulo WebSocket dedicado,
`persistence/models.py` e uma migration. Testes: `unit/ai`, `unit/context`,
`unit/conversation`, `integration/conversation`, `integration/client_boundary`,
`integration/persistence`, `integration/gate` e suporte fake.

Não se prevê mudança em `README`, root, arquitetura de processo, docs de ADR ou
o endpoint NDJSON de texto, salvo documentação de evidence após execução.

## 25. Riscos e respostas

- **Provider dita Conversation:** seed Core-owned, sessão nativa descartável e
  testes de troca/reload.
- **Turn falso ou transcript parcial durável:** barreira `UserTranscriptFinal`
  antes de persistência e contract test.
- **Barge-in com áudio tardio:** epoch Core + terminalização atômica testada
  com `asyncio.Event`.
- **Memória ilimitada:** queues/frame bounds e ausência de concatenação/blob.
- **Vazamento de segredo/áudio:** secrets no adapter, redaction e asserts de
  boundary; não registrar payloads.
- **Escopo crescer para VAD/UI:** PTT é o único ativador; demais itens deferred.
- **Migration SQLite destruir dados:** upgrade/downgrade e reload em banco real.

## 26. Deferred e open items

**DEFERRED:** wake word, VAD, continuous listening, device capture/playback,
desktop hotkey, codecs alternativos/transcoding, multi-session/provider
fallback, live transcription UI, audio persistence, recovery de sessão após
crash, audit schema, tools/policy/memory e acesso remoto.

**OPEN:** somente a necessidade de aprovação de fixture/licença/proveniência do
smoke, caso ela permaneça após o desenho do adapter. Modelo OpenAI, SDK/API
transport e acesso/custo são pré-condições `DEFERRED`, não escolhas abertas.

## 27. Definition of Done e pedido de revisão

Gate I3 estará pronto para revisão apenas quando os subpassos aprovados tiverem
preservado texto/HTTP/G2, migrations reais, contexto bounded/locality-safe,
autenticação loopback, fake determinístico, barge-in sem corrida observável,
reload mixed-modality, testes/quality gates verdes e evidence externa opt-in
registrada separadamente. Nenhum commit/push é produzido por este planejamento.

**Decisões PROPOSED para aprovação:** WebSocket `realtime.v1` com autenticação
no primeiro JSON limitado; `RealtimeProvider` especializado; capabilities
`REALTIME`, `AUDIO_INPUT`, `AUDIO_OUTPUT`; `RealtimeSession` efêmera única por
Conversation; `ConversationActivityCoordinator` mínimo; seed realtime em
`ContextBuilder` com stale/reseed; `RealtimeInteraction` efêmera; semântica de
`VOICE`/Turn e exclusão de interrupted history; filas bounded e epoch de
barge-in. OpenAI e `PCM16/24 kHz/mono` são FROZEN.
