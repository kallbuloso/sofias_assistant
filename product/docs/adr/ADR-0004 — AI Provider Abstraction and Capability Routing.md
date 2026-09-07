# ADR-0004 — AI Provider Abstraction and Capability Routing

**Status:** Accepted  
**Project:** Sofia's Assistant  
**Decision date:** 2026-08-31  
**Scope:** Provider abstraction, model registry, capability routing, fallback, data locality and normalization

---

# 1. Context

O Sofia's Assistant deverá utilizar diferentes modelos e provedores de IA ao longo do tempo.

Entre os candidatos atuais e futuros estão:

- Gemini;
- OpenAI-compatible providers;
- OpenRouter;
- Ollama;
- modelos locais;
- providers especializados em realtime audio;
- providers especializados em embeddings;
- modelos especializados em reasoning;
- modelos menores para operações utilitárias.

Esses provedores possuem diferenças importantes.

Nem todos suportam:

- realtime audio;
- vision;
- tool calling;
- structured output;
- embeddings;
- reasoning;
- streaming;
- session resumption;
- áudio nativo;
- execução local.

Além disso, uma única conversation poderá utilizar mais de um provider conforme a necessidade.

Portanto, o Sofia Core não deverá ser arquitetado em torno de:

```text
current_provider = "gemini"
```

nem possuir condicionais específicas de provider espalhadas pelo domínio.

---

# 2. Decision

O Sofia's Assistant adotará uma arquitetura **provider-agnostic baseada em capabilities**.

O domínio solicitará capacidades de IA.

Um `AI Router` decidirá qual combinação de provider/model é compatível com a operação.

A arquitetura conceitual será:

```text
                    Sofia Core
                        │
                  AI Requirements
                        │
                        ▼
                    AI Router
                        │
          ┌─────────────┼─────────────┐
          │             │             │
          ▼             ▼             ▼
      Realtime       Reasoning      Utility
          │             │             │
          ▼             ▼             ▼
   Provider Adapter Provider Adapter Provider Adapter
          │             │             │
          ▼             ▼             ▼
     Provider A      Provider B      Provider C
```

Provider e modelo serão mecanismos de execução.

Eles não definirão a identidade da Sofia.

---

# 3. Fundamental Rule

A regra arquitetural será:

```text
Domain requests capabilities.
Router selects execution.
Provider performs inference.
```

e não:

```text
Domain asks Gemini-specific API.
```

O restante do Sofia Core não deverá depender de APIs, schemas ou objetos nativos de um provider específico.

---

# 4. Sofia Identity Is Provider-independent

A identidade, princípios e comportamento fundamental da Sofia pertencem ao Sofia's Assistant.

Não pertencem ao provider.

Trocar:

```text
Gemini → OpenAI-compatible
```

não deverá produzir semanticamente:

> “agora você está falando com outra assistente.”

O provider participa da cognição.

Ele não é a Sofia.

---

# 5. Provider Roles

A arquitetura deverá permitir que diferentes providers desempenhem funções diferentes.

Exemplo:

```text
Realtime conversation
    → Gemini Live

Complex reasoning
    → reasoning-capable provider

Background classification
    → smaller / cheaper model

Embeddings
    → embedding provider

Vision
    → vision-capable provider
```

Essas funções poderão ser executadas pelo mesmo provider ou por vários.

---

# 6. Provider Interfaces

Não será criada uma única interface gigantesca com todos os métodos possíveis.

Evitar:

```python
class AIProvider:
    chat(...)
    realtime(...)
    embed(...)
    transcribe(...)
    speak(...)
    vision(...)
    generate_image(...)
```

onde a maioria das implementações retorna:

```python
NotImplementedError
```

A arquitetura utilizará interfaces especializadas.

Conceitualmente:

```text
TextGenerationProvider
StructuredOutputProvider
ToolCallingProvider
RealtimeProvider
EmbeddingProvider
VisionProvider
```

A composição concreta poderá evoluir.

---

# 7. Provider Adapter

Cada integração com provider deverá utilizar um Adapter.

Responsabilidades do Adapter incluem:

- converter request interno para formato nativo;
- normalizar responses;
- normalizar errors;
- normalizar streaming;
- converter ToolCalls;
- converter structured output;
- mapear usage;
- expor health/capabilities;
- esconder detalhes específicos do SDK.

O domínio não deverá manipular diretamente objetos de SDK externo.

---

# 8. Model Registry

O Sofia's Assistant manterá um `Model Registry`.

O registry deverá conhecer capabilities declaradas ou verificadas de modelos disponíveis.

Metadata conceitual:

```text
ModelDescriptor
├── provider
├── model_id
├── text
├── vision
├── audio_input
├── audio_output
├── realtime
├── streaming
├── tool_calling
├── structured_output
├── embeddings
├── reasoning
├── context_window
├── local
├── cost_class
├── availability
└── metadata
```

O schema final será definido posteriormente.

---

# 9. Registry Is Configuration, Not Truth by Assumption

O registry não deverá depender apenas de listas hardcoded eternas.

Capabilities poderão vir de:

- configuração suportada pelo projeto;
- metadata oficial conhecida;
- provider introspection quando disponível;
- health/probe controlado;
- overrides do usuário.

O runtime deverá tolerar mudanças na oferta de modelos sem exigir alterações espalhadas pelo código.

---

# 10. Capability Requirements

Subsystems deverão solicitar requirements.

Exemplo:

```text
AIRequestRequirements
├── text = true
├── vision = false
├── realtime = false
├── tool_calling = true
├── structured_output = true
├── reasoning = preferred
└── data_locality = CLOUD_ALLOWED
```

O Router utilizará essas informações para selecionar candidatos.

---

# 11. Hard Requirements vs Preferences

Requirements deverão diferenciar:

```text
required
```

de:

```text
preferred
```

Exemplo:

```text
tool_calling = REQUIRED
reasoning = PREFERRED
local = PREFERRED
```

Um modelo sem Tool Calling não poderá ser selecionado quando isso for requisito obrigatório.

Já uma preferência poderá ser relaxada conforme routing policy.

---

# 12. Routing Inputs

O `AI Router` poderá considerar:

- capabilities requeridas;
- data locality;
- user preference;
- provider availability;
- provider health;
- model health;
- task type;
- context size;
- latency requirements;
- realtime requirements;
- cost policy;
- quality preference;
- fallback rules.

O algoritmo concreto não é definido neste ADR.

---

# 13. Explicit Overrides

Usuário ou configuração poderão fixar modelo/provider para determinados usos.

Exemplo:

```text
realtime:
  provider = gemini
```

ou:

```text
reasoning:
  model = ...
```

Esses overrides deverão ser validados contra os requirements.

Configurar explicitamente um modelo incompatível deverá resultar em erro claro, não comportamento silenciosamente degradado.

---

# 14. Multi-provider Conversation

Uma conversation não será vinculada obrigatoriamente a um único provider.

Exemplo:

```text
User voice
   ↓
Realtime Provider
   ↓
Sofia Conversation Runtime
   ↓
Complex task detected
   ↓
Reasoning Provider
   ↓
Result returned to same conversation
```

Do ponto de vista do usuário, a identidade e conversation permanecem as mesmas.

---

# 15. Provider Session Is Not Conversation Authority

Providers poderão possuir sessões próprias.

Exemplos:

- realtime sessions;
- server-side conversation state;
- session resumption tokens;
- provider-specific cache.

Esses mecanismos poderão ser utilizados.

Mas serão tratados como otimizações/adapters.

A autoridade sobre:

- conversation;
- turn;
- context;
- identity;
- Task;
- memory;

continua no Sofia Core.

---

# 16. Realtime Provider

Realtime deverá possuir interface especializada.

Um `RealtimeProvider` poderá suportar capacidades como:

```text
connect
send_audio
send_text
receive_audio
receive_transcript
interrupt
tool_request
resume_session
close
```

A interface final será definida no ADR-0005/Technical Backlog.

---

# 17. Native Realtime Is First-class

A arquitetura não assumirá obrigatoriamente:

```text
STT
 ↓
Text LLM
 ↓
TTS
```

Providers de áudio realtime nativo deverão poder operar diretamente dentro do Conversation Runtime.

Isso preserva:

- baixa latência;
- prosódia;
- interruptions;
- barge-in;
- native audio understanding;
- realtime tool calling.

---

# 18. Traditional Voice Pipelines Remain Possible

Mesmo com suporte a realtime nativo, a arquitetura poderá suportar:

```text
STT Provider
   ↓
Text Provider
   ↓
TTS Provider
```

como estratégia alternativa.

O produto não ficará preso a uma única implementação de voz.

---

# 19. Tool Call Normalization

Cada provider possui formato próprio para function/tool calls.

Esses formatos deverão ser convertidos para um contrato interno.

Conceitualmente:

```text
Provider Tool Call
      ↓
Provider Adapter
      ↓
Normalized ToolCall
```

Exemplo:

```text
ToolCall
├── id
├── name
├── arguments
├── provider_metadata
└── correlation
```

Após essa conversão, Tool Runtime não deverá conhecer o provider de origem para executar a operação.

---

# 20. Tool Results

O caminho inverso também será normalizado.

```text
ToolResult
    ↓
Provider Adapter
    ↓
Provider-native response
```

O Tool Runtime não deverá formatar respostas especificamente para Gemini, OpenAI ou outro provider.

---

# 21. Structured Output Normalization

Requests que precisem de output estruturado deverão utilizar contrato interno.

O Adapter será responsável por escolher mecanismo compatível:

- JSON Schema;
- native structured output;
- constrained generation;
- tool call;
- fallback parsing quando explicitamente suportado.

O domínio não deverá conhecer essas diferenças.

---

# 22. Streaming Normalization

Providers de streaming produzem eventos distintos.

O Sofia Core deverá trabalhar com eventos internos normalizados.

Exemplos conceituais:

```text
TextDelta
AudioChunk
TranscriptDelta
ToolCallStarted
ToolCallCompleted
UsageUpdated
ProviderCompleted
ProviderError
```

A nomenclatura final poderá mudar.

---

# 23. Provider Errors

Errors deverão ser normalizados em categorias úteis.

Exemplos conceituais:

```text
AUTHENTICATION_ERROR
RATE_LIMITED
MODEL_UNAVAILABLE
PROVIDER_UNAVAILABLE
INVALID_REQUEST
CONTEXT_LIMIT_EXCEEDED
TIMEOUT
CAPABILITY_UNAVAILABLE
```

O domínio não deverá depender de exception classes específicas dos SDKs.

---

# 24. Provider Health

Provider/model health deverá poder influenciar routing.

O runtime poderá manter estados como:

```text
healthy
degraded
unavailable
cooldown
```

A estratégia exata será definida posteriormente.

---

# 25. Fallback

Fallback será permitido, mas não será universal ou irrestrito.

A regra será:

> Fallback só pode ocorrer para um candidato compatível com requirements, Policy e data locality.

Exemplo válido:

```text
cheap cloud classifier unavailable
    ↓
another allowed cloud classifier
```

Exemplo inválido:

```text
LOCAL_ONLY request
    ↓
local provider fails
    ↓
silently send data to cloud
```

---

# 26. Fallback Is Policy-aware

O `AI Router` deverá consultar restrições aplicáveis antes de selecionar fallback.

Provider availability nunca substitui authorization.

---

# 27. Data Locality

Cada operação poderá possuir política de locality.

Baseline:

```text
LOCAL_ONLY
CLOUD_ALLOWED
CLOUD_PREFERRED
```

O modelo poderá evoluir se necessário.

---

# 28. LOCAL_ONLY

Quando uma operação for `LOCAL_ONLY`:

- prompts;
- attachments;
- contextual memory;
- Tool outputs;
- imagens;
- documentos;

não poderão ser enviados a providers cloud como fallback.

Se nenhum provider local compatível estiver disponível, a operação deverá falhar ou solicitar mudança explícita de policy.

---

# 29. CLOUD_ALLOWED

Cloud poderá ser utilizado, mas não é obrigatório.

Routing poderá considerar modelos locais ou remotos.

---

# 30. CLOUD_PREFERRED

Cloud poderá ser priorizado quando permitido.

Esse estado poderá ser útil para workloads onde qualidade/latência cloud seja preferida.

---

# 31. Data Locality Is Context-sensitive

Uma mesma conversation poderá conter dados de scopes distintos.

O runtime não deverá assumir que:

```text
conversation is cloud allowed
```

para sempre.

Uma operação específica pode tornar-se `LOCAL_ONLY` devido ao recurso acessado.

---

# 32. Provider Does Not Own Secrets

Providers utilizarão credenciais obtidas através do `SecretStore`.

Adapters não deverão carregar secrets diretamente de:

```text
config/api_keys.json
```

como contrato arquitetural.

Fluxo:

```text
Provider Adapter
      ↓
Credential/Secret service
      ↓
SecretStore
```

---

# 33. SecretStore

A implementação deverá suportar armazenamento seguro adequado ao sistema operacional.

Windows-first implica avaliar:

- Windows Credential Manager;
- DPAPI-backed storage;

ou equivalente.

A implementação concreta será decidida posteriormente.

---

# 34. Future CLI

Futuramente poderá existir:

```text
sofia secrets set ...
sofia secrets remove ...
sofia secrets list
```

Mas essa CLI deverá usar o mesmo `SecretStore`.

Não haverá storage paralelo de credenciais apenas por conveniência da CLI.

---

# 35. Local Models

A arquitetura deverá suportar providers locais.

Exemplos:

- Ollama;
- OpenAI-compatible local server;
- outros runtimes locais futuros.

Contudo, um provider local não será requisito funcional obrigatório do primeiro MVP.

---

# 36. OpenAI-compatible Providers

OpenAI-compatible APIs poderão compartilhar adapter base quando realmente compatíveis.

Entretanto, "OpenAI-compatible" não será assumido como garantia de comportamento idêntico.

Diferenças poderão incluir:

- Tool Calling;
- structured output;
- streaming;
- context limits;
- model discovery.

Adapters poderão especializar essas diferenças.

---

# 37. Provider-specific Optimizations

A abstração não deverá impedir o uso de recursos especiais.

Exemplo:

Gemini Live poderá oferecer:

- session resumption;
- affective dialogue;
- proactive audio;
- native tool calls.

Esses recursos poderão ser utilizados por capabilities opcionais ou extensões do Adapter.

Regra:

> Abstraction should hide incompatibility, not erase useful capability.

---

# 38. Capability Extensions

Providers poderão expor capabilities avançadas além do baseline.

Essas capabilities não deverão contaminar o Core com condicionais específicas.

Preferir feature capability explícita.

Exemplo:

```text
supports_session_resumption = true
```

em vez de:

```python
if provider == "gemini":
```

---

# 39. Context Window

ModelDescriptor deverá poder informar context capacity quando conhecida.

O Router poderá utilizar essa informação para rejeitar candidatos incapazes de atender uma operação.

Entretanto, gerenciamento do contexto será responsabilidade do ADR-0005/Context Builder.

Provider context window não substitui context management.

---

# 40. Cost Metadata

Model Registry poderá conter classe/custo aproximado.

Exemplo:

```text
FREE
LOW
STANDARD
HIGH
```

ou representação futura mais apropriada.

O sistema não dependerá necessariamente de preço hardcoded exato para routing.

---

# 41. Usage Tracking

Adapters deverão poder retornar metadata de uso quando fornecida pelo provider.

Exemplos:

- input tokens;
- output tokens;
- audio usage;
- cached tokens;
- request duration.

Esses dados poderão alimentar observability e futuras policies de orçamento.

---

# 42. Privacy

Provider Adapter deverá receber apenas os dados necessários à operação.

A existência de uma memória no Context Builder não significa que todo seu conteúdo será enviado automaticamente a qualquer modelo.

Context construction + Policy + locality controlam esse fluxo.

---

# 43. Retry

Retries de chamadas de AI deverão considerar:

- idempotency semantics;
- request type;
- streaming state;
- provider failure;
- timeout;
- possible duplicate effects.

Tool Calls produzidas por um provider não deverão ser repetidas automaticamente apenas porque a chamada de inference foi retryada.

Esse boundary será especialmente importante no Conversation Runtime.

---

# 44. Routing and Tool Side Effects

O Router decide inferência.

Ele não possui autoridade sobre Tool execution.

Mesmo quando um provider produz ToolCall:

```text
Provider
   ↓
Normalized ToolCall
   ↓
PolicyEngine
   ↓
Tool Runtime
```

O provider nunca pula Authorization Boundary.

---

# 45. Provider Configuration

Configuração poderá incluir:

- enabled providers;
- endpoint;
- model choices;
- routing preferences;
- timeout;
- credentials references;
- locality defaults.

Secrets não serão persistidos junto dessa configuração comum em texto simples.

---

# 46. Runtime Provider Changes

O produto poderá futuramente permitir mudança de provider/configuração sem recompilação.

Entretanto, mudanças deverão ocorrer através de configuração controlada.

O domínio continuará agnóstico.

---

# 47. Model Discovery

Model discovery automático poderá existir quando provider oferecer API apropriada.

Mas modelos descobertos não serão automaticamente confiáveis como capazes de todas as features.

Capability metadata ainda deverá ser validada.

---

# 48. Unknown Models

Um modelo desconhecido poderá ser registrado manualmente com capabilities explícitas.

O runtime deverá preferir fail-safe:

```text
unknown capability → unsupported
```

e não:

```text
unknown capability → assume supported
```

---

# 49. Model Removal

Se provider remover um modelo configurado:

- registry deverá detectar indisponibilidade;
- routing poderá usar fallback compatível;
- configurações inválidas deverão ser reportadas;
- conversation identity não deverá ser afetada.

---

# 50. Availability vs Authorization

Um modelo disponível não significa modelo permitido.

Exemplo:

```text
Provider cloud healthy
```

mas:

```text
operation = LOCAL_ONLY
```

Resultado:

```text
provider excluded
```

---

# 51. Realtime Fallback

Realtime sessions merecem cuidado especial.

Não será assumido que uma sessão native-audio pode migrar transparentemente entre providers no meio da fala.

Fallback poderá exigir:

- encerrar sessão;
- preservar conversation state no Core;
- iniciar nova provider session;
- informar degradação ao usuário.

Detalhes ficarão no ADR-0005.

---

# 52. Provider State Persistence

Provider-native session identifiers poderão ser persistidos se necessários para recovery/resumption.

Mas serão metadata operacional.

Eles não serão IDs authoritative da conversation.

---

# 53. Testing

Cada Provider Adapter deverá possuir contract tests para comportamentos relevantes.

Testes deverão verificar:

- request normalization;
- response normalization;
- tool calls;
- structured output;
- errors;
- streaming;
- capability declaration.

Router deverá ser testável sem chamadas reais a providers.

---

# 54. Fake/Test Provider

O architecture deverá suportar provider determinístico de testes.

Isso permitirá validar:

- Conversation Runtime;
- routing;
- Tool Calling;
- fallback;
- policy interaction;

sem depender de APIs externas.

---

# 55. Provider SDK Isolation

SDKs externos não deverão vazar para o domínio.

Se trocar versão do SDK exigir alterações em dezenas de services do Sofia Core, o boundary foi violado.

Mudanças deverão permanecer concentradas no Adapter quando possível.

---

# 56. Alternatives Considered

## Alternative A — Gemini as the Core AI Runtime

### Advantages

- realtime voice excelente;
- integração inicial mais rápida;
- Tool Calling já disponível;
- menor abstração inicial.

### Rejected because

- vendor lock-in;
- dificulta local-first;
- identity fica acoplada;
- impede routing especializado;
- future providers exigiriam refatoração estrutural.

Gemini continuará forte candidato para realtime no MVP, mas através de Adapter.

---

## Alternative B — One universal OpenAI-compatible interface

### Advantages

- aparentemente simples;
- grande ecossistema.

### Rejected because

não representa adequadamente:

- native realtime audio;
- provider-specific capabilities;
- embeddings;
- diferenças de structured output;
- session features.

---

## Alternative C — One configured model for everything

### Advantages

- configuração simples;
- comportamento fácil de prever.

### Rejected because

- desperdício de custo;
- incapacidade de usar especializações;
- limita realtime;
- limita modelos locais;
- torna fallback ruim;
- conflita com ambição do produto.

---

## Alternative D — Providers selected directly by each subsystem

### Example

```text
Memory picks OpenAI
Voice picks Gemini
Agent picks OpenRouter
```

### Rejected because

- routing espalhado;
- data locality inconsistente;
- duplicated fallback logic;
- observability fragmentada;
- difícil aplicar preference/policy global.

---

# 57. Consequences

## Positive

- reduz vendor lock-in;
- permite realtime especializado;
- suporta local models;
- possibilita múltiplos providers na mesma conversation;
- centraliza fallback;
- preserva data locality;
- facilita testes;
- provider SDKs ficam isolados;
- permite evolução independente de modelos.

## Negative

- Router adiciona complexidade;
- Model Registry precisa manutenção;
- normalização pode esconder detalhes úteis se mal projetada;
- realtime possui diferenças difíceis de abstrair;
- capability metadata pode ficar desatualizada;
- contract tests serão necessários.

Esses custos são considerados aceitáveis e necessários.

---

# 58. Architectural Invariants

### INV-001

Sofia identity não pertence ao provider.

### INV-002

Core domain não importa SDKs de AI providers.

### INV-003

Provider ToolCalls são normalizados antes do Tool Runtime.

### INV-004

Provider não autoriza Tool execution.

### INV-005

Routing respeita data locality.

### INV-006

Fallback nunca amplia permission/locality.

### INV-007

Provider session não é Conversation authority.

### INV-008

Unknown capability não é assumida como suportada.

### INV-009

Secrets são acessados através de SecretStore.

### INV-010

Provider-specific optimization não justifica conditional espalhada no domínio.

### INV-011

Mais de um provider pode participar da mesma conversation.

### INV-012

Provider failure não altera Sofia identity.

---

# 59. Deferred Decisions

Serão definidos posteriormente:

- abstrações Python concretas;
- Router algorithm;
- Model Registry storage;
- primeiro realtime provider;
- primeira lista de providers suportados;
- OpenRouter support;
- Ollama support;
- exact locality enum;
- provider health algorithm;
- cooldown strategy;
- retry policy;
- SecretStore implementation;
- usage/cost model;
- model discovery mechanism;
- SDK versions.

---

# 60. Decision Summary

Sofia's Assistant utilizará uma arquitetura **provider-agnostic orientada por capabilities**.

O Sofia Core solicitará capacidades de IA, e um `AI Router` selecionará provider/model compatível considerando requirements, disponibilidade, preferência, custo e data locality.

Providers serão integrados através de Adapters especializados.

Realtime, Text, Embedding e outras modalidades poderão possuir interfaces próprias.

Tool Calls, streaming, structured outputs e errors serão normalizados antes de alcançar o domínio.

Provider sessions serão mecanismos de execução, nunca autoridade sobre conversation ou identidade.

Fallback somente poderá ocorrer quando preservar capabilities, Policy e data locality.