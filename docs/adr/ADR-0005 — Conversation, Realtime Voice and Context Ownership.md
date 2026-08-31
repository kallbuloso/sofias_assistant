# ADR-0005 — Conversation, Realtime Voice and Context Ownership

**Status:** Accepted  
**Project:** Sofia's Assistant  
**Decision date:** 2026-08-31  
**Scope:** Conversation lifecycle, multimodality, realtime voice, streaming, interruption, Working Memory and Context Builder

---

# 1. Context

O Sofia's Assistant deverá oferecer uma experiência contínua de conversa por:

- texto;
- realtime voice;
- futuramente imagem, câmera e outras modalidades.

Texto e voz não serão produtos separados nem sessões independentes.

O usuário deverá poder:

- iniciar por texto;
- continuar por voz;
- interromper a fala da Sofia;
- retomar a conversa;
- utilizar Tools;
- receber resultados de Tasks;
- recuperar memória;
- manter identidade e contexto consistentes mesmo quando diferentes providers forem utilizados.

Providers de realtime podem oferecer mecanismos próprios de:

- session state;
- session resumption;
- audio buffering;
- native transcripts;
- turn detection;
- Tool Calling;
- context compression.

Esses mecanismos são úteis, mas não podem se tornar a autoridade da conversa.

O Sofia Core precisa possuir seu próprio modelo de conversation, context e interruption.

---

# 2. Decision

O Sofia's Assistant adotará um **Conversation Runtime próprio e provider-independent**.

O Sofia Core será authoritative para:

- Conversation;
- Turn;
- multimodal interaction;
- Working Memory;
- conversation state;
- tool interaction;
- Task linkage;
- memory retrieval;
- context construction;
- interruption semantics.

Providers participarão como mecanismos de inference/realtime execution.

A arquitetura conceitual será:

```text
User
 │
 ├── Text
 └── Voice
      │
      ▼
Conversation Runtime
      │
      ├── Working Memory
      ├── Context Builder
      ├── Memory Retrieval
      ├── Task State
      └── Tool State
      │
      ▼
AI Router
      │
      ▼
Provider Adapter
```

---

# 3. Fundamental Rule

A regra será:

> **Conversation belongs to Sofia. Provider sessions belong to providers.**

Uma provider session poderá desaparecer e ser recriada sem que a Conversation deixe de existir.

---

# 4. Conversation

Uma `Conversation` representa um espaço lógico de interação entre usuário e Sofia.

Conceitualmente:

```text
Conversation
├── id
├── status
├── created_at
├── updated_at
├── current_context_state
└── metadata
```

O schema concreto será definido posteriormente.

---

# 5. Conversation Identity

Conversation ID será gerado e controlado pelo Sofia Core.

Não será usado como authoritative ID:

- Gemini session ID;
- OpenAI thread ID;
- WebSocket ID;
- client connection ID.

Provider IDs poderão ser armazenados como metadata associada.

---

# 6. Turns

Interações deverão possuir representação própria.

Um Turn poderá incluir:

- user text;
- user audio;
- transcript;
- Sofia text;
- Sofia audio;
- ToolCalls;
- ToolResults;
- interruption;
- attachments;
- metadata.

O domínio não deverá assumir que:

```text
one user message
=
one provider request
```

Realtime pode produzir múltiplos eventos durante um Turn.

---

# 7. Text and Voice Are Modalities

Texto e voz pertencem à mesma Conversation.

Exemplo:

```text
User types:
"Analise este erro."

Sofia responds.

User speaks:
"Agora abra o arquivo que você mencionou."
```

A segunda interação deverá possuir acesso ao contexto da primeira.

Não haverá um "voice memory" separado de "text memory".

---

# 8. Realtime Voice Is First-class

Realtime Voice será parte estrutural do Conversation Runtime.

Não será implementado apenas como camada opcional sobre um chatbot textual.

O runtime deverá suportar conceitualmente:

- live audio input;
- live audio output;
- streaming;
- partial transcripts;
- barge-in;
- interruption;
- native realtime provider sessions;
- Tool Calling durante realtime.

---

# 9. Realtime Session

Uma Conversation poderá possuir uma `RealtimeSession` temporária.

Conceitualmente:

```text
Conversation
   │
   └── RealtimeSession
          ├── provider
          ├── provider_session_id
          ├── state
          ├── started_at
          └── metadata
```

A RealtimeSession é descartável e reconstruível.

---

# 10. Provider Session Resumption

Quando provider oferecer session resumption, Sofia poderá utilizá-la.

Exemplo:

```text
provider_session_token
```

poderá ser persistido como optimization metadata.

Se esse token falhar:

```text
Conversation survives.
```

O runtime reconstrói contexto e inicia nova provider session.

---

# 11. Conversation State vs Provider State

Provider state poderá conter contexto remoto/cache.

Esse estado nunca será considerado suficiente para reconstruir Conversation.

O Sofia Core deverá persistir o estado relevante localmente.

---

# 12. Streaming

Streaming será tratado como sequência de eventos internos normalizados.

Exemplos conceituais:

```text
TextDelta
AudioChunk
TranscriptDelta
TranscriptFinal
ToolCallRequested
TurnCompleted
InterruptionDetected
ProviderError
```

Desktop Client consumirá esses eventos através do Core boundary definido no ADR-0001.

---

# 13. Partial Output

Output parcial não deverá ser automaticamente considerado resposta final persistida.

Exemplo:

```text
"This is probably..."
```

emitido em streaming pode ser interrompido.

Conversation history deverá conseguir distinguir:

- partial;
- final;
- interrupted.

---

# 14. Barge-in

Usuário poderá interromper Sofia enquanto ela fala.

Exemplo:

```text
Sofia:
"A causa mais provável é..."

User:
"Não, espera. Estou falando de outro arquivo."
```

O runtime deverá:

1. detectar intervenção;
2. interromper saída de áudio quando possível;
3. cancelar/stop generation quando suportado;
4. marcar resposta anterior como interrompida;
5. preservar contexto relevante;
6. iniciar novo Turn.

---

# 15. Interruption Is a Domain Event

Interruption não será apenas:

```text
audio.stop()
```

Ela terá significado de Conversation.

Isso é importante para histórico e contexto.

---

# 16. Provider Without Native Barge-in

Se provider não possuir cancelamento realtime adequado, o Sofia Core ainda deverá poder:

- parar playback local;
- descartar output posterior;
- marcar Turn interrompido.

Limitações do provider poderão afetar eficiência, não a semântica da Conversation.

---

# 17. User Speech Detection

A tecnologia de VAD/turn detection será definida posteriormente.

O domínio deverá permitir:

- provider-native VAD;
- local VAD;
- push-to-talk.

Nenhuma dessas estratégias será authoritative sobre Conversation.

---

# 18. Wake Word

Wake word fará parte da camada de activation, não da Conversation identity.

Exemplo:

```text
"Sofia"
```

pode abrir/ativar entrada para Conversation existente ou nova conforme contexto.

Detalhes ficam fora deste ADR.

---

# 19. Working Memory

O Sofia's Assistant possuirá Working Memory própria.

Working Memory representa estado contextual temporário relevante para a operação atual.

Exemplos:

```text
active objective
current file
recent ToolResult
current screen snapshot
temporary hypotheses
active Task
active Delegation
conversation focus
```

---

# 20. Working Memory Is Not Long-Term Memory

Working Memory poderá desaparecer sem produzir Cognitive Memory.

Exemplo:

```text
temporary compiler output
```

não precisa ser armazenado no Sofias Memory.

---

# 21. Working Memory Persistence

Parte da Working Memory poderá ser persistida operacionalmente quando necessária para recovery.

Isso não a transforma em Long-Term Cognitive Memory.

Exemplo:

```text
active Task context
```

pode sobreviver a restart.

---

# 22. Context Builder

O Sofia Core possuirá um `ContextBuilder`.

Sua responsabilidade será construir a projeção de contexto entregue ao provider.

Ele não deverá simplesmente concatenar toda a Conversation.

---

# 23. Context Projection

O contexto poderá combinar:

```text
Sofia identity
system principles
current user request
recent relevant Turns
Working Memory
active Task
active Delegation
relevant ToolResults
environment context
retrieved Long-Term Memory
```

A composição será orientada pela operação atual.

---

# 24. Context Is Not Transcript

Regra:

```text
Context != Conversation transcript
```

Conversation é histórico.

Context é projeção operacional.

Um Turn antigo poderá continuar no histórico e não entrar no prompt atual.

---

# 25. Context Ownership

Context Builder pertence ao Sofia Core.

Sofias Memory não monta prompt final.

Provider não decide sozinho quais memórias devem entrar.

---

# 26. Long-term Memory Retrieval

Quando necessário:

```text
Context Builder / Memory Orchestrator
        ↓
Sofias Memory
        ↓
relevant memory
        ↓
Context Builder
```

O Assistant decide qual memória pedir e como utilizá-la.

---

# 27. Memory Injection

Memórias recuperadas deverão carregar metadata suficiente para o runtime distinguir:

- origin;
- provenance;
- confidence;
- type;
- relevance;
- scope.

Provider não deverá receber memory sem contexto semântico quando isso for relevante.

---

# 28. Context Isolation for Agents

Sub-agents não recebem automaticamente o Context completo da Sofia.

O root orchestrator constrói um contexto delegado.

Exemplo:

```text
Root Context
   ↓
Context Projection
   ↓
Agent Context
```

Isso preserva least privilege e reduz ruído.

---

# 29. Context and Data Locality

ContextBuilder deverá respeitar data locality antes de enviar conteúdo ao provider.

Exemplo:

```text
retrieved memory = LOCAL_ONLY
```

impede sua inclusão em request cloud.

---

# 30. Context Budget

O runtime deverá considerar limites de contexto do modelo selecionado.

A estratégia poderá incluir:

- recent-turn selection;
- summaries;
- memory retrieval;
- Task state compression;
- omission of irrelevant ToolResults.

Provider context truncation não será o mecanismo principal.

---

# 31. Context Compression

Conversation longa poderá ser resumida.

Mas summaries não serão tratados automaticamente como truth.

Eles serão projeções derivadas do histórico.

A Conversation original poderá permanecer persistida conforme retention policy.

---

# 32. Provider-native Context Compression

Se provider oferecer sliding window/context compression, o recurso poderá ser utilizado.

Mas será optimization.

O Sofia Core continuará capaz de reconstruir contexto sem depender dele.

---

# 33. Context Rebuild

Quando provider session for perdida, Sofia deverá poder reconstruir contexto suficiente a partir de:

- Conversation;
- Working Memory persistida;
- Task state;
- retrieved memory;
- operational state.

---

# 34. Tool Calls During Conversation

Provider poderá solicitar ToolCall.

Fluxo:

```text
Provider
   ↓
Normalized ToolCall
   ↓
Conversation Runtime
   ↓
Task/Tool Runtime
   ↓
PolicyEngine
   ↓
Executor
```

Conversation Runtime não executa Tool diretamente.

---

# 35. Tool Result Reinjection

Resultado de Tool poderá voltar para o provider quando necessário.

Fluxo:

```text
ToolResult
   ↓
Conversation Runtime
   ↓
Context / Provider Adapter
   ↓
continuation
```

O provider não recebe automaticamente todo conteúdo de ToolResult se Policy/data locality restringir isso.

---

# 36. Long-running Tasks

Quando uma ação virar Task longa, Conversation não deverá ficar bloqueada.

Exemplo:

```text
"Analise este repositório."
```

Sofia poderá responder:

```text
Task started.
```

e continuar conversando enquanto Task roda.

---

# 37. Task Completion

Quando Task terminar:

```text
TaskCompleted
```

poderá atualizar Conversation ou gerar notificação.

O evento não precisa ocorrer no mesmo Turn que originou a Task.

---

# 38. Conversation and Task Linkage

Task poderá registrar Conversation/Turn de origem.

Isso permite:

- contexto;
- audit;
- result handoff.

Mas Task possui lifecycle próprio.

---

# 39. Conversation Closure

Fechar UI não fecha Conversation automaticamente.

Conversation poderá permanecer:

```text
OPEN
INACTIVE
ARCHIVED
```

ou estados equivalentes.

A state machine exata será definida futuramente.

---

# 40. New Conversation

Nova Conversation deverá possuir ID novo e Working Memory nova.

Long-Term Memory poderá continuar disponível conforme Policy.

---

# 41. Conversation History

Conversation History será armazenada no Operational Store quando aplicável.

Não será enviada automaticamente ao Sofias Memory.

Memory Orchestrator selecionará candidates.

---

# 42. Conversation Deletion

O usuário poderá futuramente apagar Conversation History.

Essa operação não deverá automaticamente apagar Long-Term Memory derivada.

Da mesma forma, esquecer Cognitive Memory não implica apagar audit/history operacional.

Esses domínios são distintos.

---

# 43. Audio Persistence

O sistema não deverá presumir armazenamento permanente de áudio bruto.

Possíveis estratégias incluem:

- não persistir;
- persistir temporariamente;
- persistir apenas transcript;
- persistir explicitamente quando solicitado.

A política concreta será definida posteriormente, priorizando privacidade.

---

# 44. Transcripts

Transcripts de realtime poderão ser persistidos como Conversation data.

Deverão ser distinguíveis entre:

- partial;
- final;
- provider-generated;
- locally generated;
- confidence quando disponível.

---

# 45. Input Attachments

Conversation poderá receber attachments.

Exemplos:

- screenshot;
- image;
- document;
- file reference.

Attachments poderão entrar no Context Builder conforme Task e Policy.

---

# 46. Screen Context

Screenshot manual no MVP poderá ser tratado como contextual input temporário.

Não deverá automaticamente virar Long-Term Memory.

---

# 47. Camera Context

Futuro camera awareness deverá usar a mesma filosofia:

```text
observation
    ↓
Working Context
    ↓
optional Memory Candidate
```

Nunca:

```text
camera frame → permanent memory automatically
```

---

# 48. Conversation Identity Prompt

A identidade da Sofia poderá ser representada por configuração/prompt base.

Entretanto, o system prompt final será construído pelo Sofia Core.

Provider-specific prompts poderão adaptar formato, não identidade fundamental.

---

# 49. Persona Configuration

Tom e comportamento poderão ser configuráveis.

Mudanças devem pertencer ao Sofia Core/configuration.

Não serão atributos do provider account.

---

# 50. Realtime Provider Switching

Troca de realtime provider durante uma sessão poderá exigir encerrar a provider session atual.

O Sofia Core deverá:

1. preservar Conversation;
2. preservar Working Memory;
3. criar nova provider session;
4. reconstruir contexto;
5. informar degradação/transição se necessário.

Não será prometido handoff de áudio totalmente imperceptível.

---

# 51. Provider Failure

Falha do provider deverá ser representada como erro da camada de execução.

Não deverá invalidar Conversation.

O runtime poderá:

- retry;
- fallback;
- degradar para texto;
- solicitar ação do usuário.

---

# 52. Realtime Degradation

Exemplo:

```text
native realtime unavailable
```

pode permitir fallback para:

```text
STT → text model → TTS
```

se Policy e configuração permitirem.

A identidade e Conversation permanecem.

---

# 53. Conversation Concurrency

O produto poderá futuramente possuir mais de uma Conversation lógica.

Entretanto, o MVP poderá privilegiar uma experiência principal.

O modelo não deverá depender de singleton global de Conversation.

---

# 54. Active Conversation

UI/client poderá indicar qual Conversation está ativa visualmente.

Isso não torna client authoritative sobre estado.

---

# 55. Core Without Client

Conversation Runtime deverá continuar processando Task/event results mesmo sem Desktop Client conectado.

Quando client retornar, deverá poder recuperar estado relevante.

---

# 56. Event-driven Conversation Updates

Eventos externos poderão iniciar:

- notification;
- message;
- Task;
- Conversation update.

Nem todo ExternalEvent deverá automaticamente criar novo Turn.

Attention Policy decidirá comportamento.

---

# 57. Proactive Speech

Futuramente Sofia poderá falar proativamente.

Antes de usar áudio, runtime deverá considerar:

- attention policy;
- user state;
- mute state;
- time;
- sensitivity;
- urgency.

Proactive audio não será decisão exclusiva do provider.

---

# 58. Conversation Event Model

Eventos internos poderão incluir conceitualmente:

```text
ConversationCreated
TurnStarted
UserInputReceived
AssistantOutputStarted
AssistantOutputInterrupted
TurnCompleted
RealtimeConnected
RealtimeDisconnected
```

A lista concreta será definida no backlog.

---

# 59. Persistence Strategy

Conversation data relevante será persistida no Operational Store do ADR-0002.

Realtime buffers efêmeros podem permanecer somente em memória.

---

# 60. Recovery

Após restart:

- Conversations persistidas continuam disponíveis;
- provider realtime sessions podem precisar ser recriadas;
- unfinished realtime Turns deverão ser marcados/reconciliados;
- Tasks vinculadas seguem lifecycle próprio.

---

# 61. Crash During Assistant Speech

Se Core cair durante output:

```text
Turn = incomplete/interrupted
```

não deverá ser marcado como resposta final bem-sucedida automaticamente.

---

# 62. Crash During User Audio

Áudio parcial poderá ser perdido.

O sistema não deverá inventar transcript final.

---

# 63. Observability

Conversation Runtime deverá permitir correlacionar:

```text
Conversation
Turn
ProviderRequest
ToolCall
Task
AgentRun
```

sem misturar seus lifecycles.

---

# 64. Testing

Deverão existir testes para:

- text conversation;
- voice/text continuity;
- streaming;
- partial output;
- interruption;
- provider disconnect;
- context rebuild;
- ToolCall reinjection;
- Task completion after Turn;
- memory retrieval injection.

---

# 65. Fake Realtime Provider

O projeto deverá possuir suporte a provider realtime fake/determinístico para testes.

Não será aceitável depender exclusivamente de API real para validar Conversation Runtime.

---

# 66. Alternatives Considered

## Alternative A — Provider owns conversation

### Model

```text
Provider session = conversation
```

### Rejected because

- vendor lock-in;
- provider switching difícil;
- history/recovery dependente de serviço externo;
- realtime session loss destruiria conversation;
- memória/contexto ficariam acoplados.

---

## Alternative B — Separate text and voice conversations

### Advantages

- implementação mais simples.

### Rejected because

quebra a experiência esperada de Sofia como assistente único.

---

## Alternative C — Full transcript as context

### Advantages

- implementação trivial.

### Rejected because

- custos crescentes;
- context overflow;
- informações irrelevantes;
- ToolResults enormes;
- pior controle de memória;
- pouca capacidade de isolamento.

---

## Alternative D — Sofias Memory builds complete LLM context

### Rejected because

Sofias Memory é autoridade da Long-Term Memory, não do runtime/contexto atual.

---

# 67. Consequences

## Positive

- continuidade real entre texto e voz;
- realtime provider pode mudar sem destruir Conversation;
- suporta barge-in;
- contexto controlado;
- menor vendor lock-in;
- memória e Conversation separadas;
- Tasks podem sobreviver aos Turns;
- melhor recovery;
- facilita sub-agents.

## Negative

- Conversation Runtime fica mais complexo;
- streaming exige event model sólido;
- realtime state precisa sincronização;
- Context Builder exige políticas próprias;
- provider resumption não elimina persistence local;
- multimodalidade precisa modelagem cuidadosa.

Esses custos são considerados fundamentais para a experiência pretendida.

---

# 68. Architectural Invariants

### INV-001

Conversation pertence ao Sofia Core.

### INV-002

Provider session nunca é Conversation authority.

### INV-003

Texto e voz pertencem à mesma Conversation.

### INV-004

Context é projeção, não transcript integral.

### INV-005

Working Memory não é Long-Term Memory.

### INV-006

Provider session pode ser descartada sem apagar Conversation.

### INV-007

Interruption possui semântica de domínio.

### INV-008

ToolCall durante realtime continua sujeito ao PolicyEngine.

### INV-009

Context injection respeita data locality.

### INV-010

Conversation History não é automaticamente Cognitive Memory.

### INV-011

Agent recebe Context Projection restrita.

### INV-012

Fechar UI não encerra Conversation Runtime.

---

# 69. Deferred Decisions

Serão definidos posteriormente:

- schemas concretos de Conversation/Turn;
- realtime provider inicial;
- audio library;
- VAD;
- wake-word engine;
- audio buffering;
- audio retention;
- Context Builder scoring;
- summary strategy;
- context token budgeting;
- transcript engine fallback;
- exact streaming event schema;
- conversation state machine;
- proactive speech policy.

---

# 70. Decision Summary

Sofia's Assistant possuirá um `Conversation Runtime` próprio e independente de providers.

Texto e voz serão modalidades de uma mesma Conversation.

Realtime Voice será capability de primeira classe, com suporte arquitetural a streaming, native audio e barge-in.

Provider sessions serão temporárias e reconstruíveis.

O Sofia Core será authoritative para Conversation, Working Memory, Turn lifecycle e Context Builder.

O contexto entregue aos modelos será uma projeção construída dinamicamente a partir da Conversation, Working Memory, Tasks, ambiente e memória persistente relevante, e não o histórico bruto integral.