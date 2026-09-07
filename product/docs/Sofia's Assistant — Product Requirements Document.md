# Sofia's Assistant — Product Requirements Document

**Produto:** Sofia's Assistant  
**Documento:** Product Requirements Document  
**Versão:** 0.1.0  
**Status:** Baseline para revisão  
**Discovery baseline:** SA-001 a SA-130  
**Idioma:** Português do Brasil

---

# 1. Resumo Executivo

O **Sofia's Assistant** será um sistema pessoal de inteligência artificial, **local-first**, single-user por instalação, multimodal, extensível e orientado a eventos.

Seu objetivo não é ser apenas um chatbot capaz de executar comandos, mas um assistente pessoal persistente capaz de:

- conversar por texto e voz em tempo real;
- compreender contexto;
- lembrar informações ao longo do tempo;
- observar elementos autorizados do ambiente do usuário;
- utilizar ferramentas;
- planejar tarefas;
- delegar trabalho a sub-agents especializados;
- executar ações locais e externas;
- reagir proativamente a eventos;
- aprender procedimentos;
- operar com diferentes provedores e modelos de IA;
- agir autonomamente dentro de permissões, políticas e delegações explicitamente controladas pelo usuário.

A autoridade final sobre ações permanecerá sempre no runtime do Sofia's Assistant.

Modelos de IA poderão propor, interpretar, planejar e recomendar ações, mas **não poderão conceder permissões a si próprios nem substituir o mecanismo determinístico de autorização do sistema**.

O **Sofias Memory** será utilizado como infraestrutura persistente de memória cognitiva de longo prazo, enquanto o Sofia's Assistant manterá seu próprio estado operacional e Working Memory.

---

# 2. Visão do Produto

> Criar um assistente pessoal de IA que acompanhe o trabalho e o ambiente do usuário, preserve conhecimento ao longo do tempo, compreenda contexto, execute tarefas e possa agir proativamente dentro de regras claras de autonomia e segurança.

O Sofia's Assistant deverá progressivamente aproximar-se da experiência de um assistente pessoal contínuo, e não de sessões isoladas de chat.

A identidade da Sofia deverá permanecer consistente independentemente do modelo ou provedor de IA utilizado.

---

# 3. Público e Modelo de Distribuição

## 3.1 Público inicial

O produto será inicialmente desenvolvido para uso pessoal do desenvolvedor.

## 3.2 Modelo arquitetural

O produto será:

- single-user por instalação;
- local-first;
- inicialmente Windows-first;
- arquitetado para futura distribuição para outros usuários;
- preparado para futura portabilidade para Linux e macOS.

Não haverá, no MVP:

- multi-tenancy;
- organizações;
- colaboração entre usuários;
- ACL multiusuário;
- infraestrutura SaaS obrigatória.

A arquitetura não deverá, entretanto, codificar identidade ou preferências pessoais diretamente no código-fonte.

---

# 4. Princípios do Produto

## 4.1 Local-first

Runtime, estado operacional, permissões e ferramentas deverão permanecer sob controle local do usuário.

Serviços externos poderão ser utilizados para inferência, busca, APIs e outras capacidades quando autorizados.

## 4.2 User in control

A disponibilidade de uma capability não implica autorização para utilizá-la.

```text
Capability available ≠ Capability authorized
```

## 4.3 Provider-agnostic

Gemini, OpenAI-compatible, OpenRouter, Ollama ou outros provedores são mecanismos de inferência.

Nenhum deles define a identidade ou arquitetura da Sofia.

## 4.4 Policy before action

Qualquer operação sobre recursos protegidos deverá passar pela camada de autorização do runtime.

## 4.5 Least privilege

Tools, plugins e sub-agents deverão receber apenas contexto, recursos e permissões necessários para sua execução.

## 4.6 Least complex execution

O Sofia's Assistant deverá utilizar o mecanismo menos complexo capaz de resolver corretamente uma tarefa.

Uma Tool não deverá ser substituída desnecessariamente por um Agent.

## 4.7 Memory has provenance

Memórias persistentes deverão preservar origem e significado cognitivo.

## 4.8 UI is a client

A interface gráfica não será a autoridade do sistema.

O Sofia Core deverá continuar operacional independentemente da janela principal.

## 4.9 Plugins are untrusted by default

Extensões não deverão obter implicitamente confiança equivalente ao Sofia Core.

## 4.10 Auditability

Ações relevantes deverão permitir reconstruir posteriormente o motivo, autorização, executor e resultado da operação.

---

# 5. Modelo de Interação

## 5.1 Texto e voz

Texto e voz terão importância equivalente.

Ambos serão modalidades de uma mesma conversa e de uma mesma identidade.

Uma conversa iniciada por texto poderá continuar por voz e vice-versa.

## 5.2 Realtime Voice

Realtime Voice é uma capability fundamental, e não uma extensão secundária.

A arquitetura deverá suportar providers capazes de fornecer:

- áudio nativo realtime;
- streaming bidirecional;
- baixa latência;
- interrupção;
- barge-in;
- continuidade da sessão.

Implementações tradicionais STT → LLM → TTS poderão coexistir, mas não deverão limitar o modelo arquitetural.

## 5.3 Ativação

O produto deverá evoluir para suportar:

- push-to-talk;
- hotkeys;
- wake word local;
- futuramente, escuta contínua quando explicitamente habilitada.

O MVP deverá priorizar mecanismos explícitos de ativação antes de escuta contínua.

---

# 6. Percepção do Ambiente

A Sofia poderá, mediante capabilities e permissões específicas, acessar contexto do ambiente local.

Exemplos:

- aplicação ativa;
- janela ativa;
- clipboard;
- processos;
- arquivos;
- screenshot;
- estado do desktop;
- reprodução de mídia;
- webcam;
- atividade ou inatividade do usuário.

Percepção contínua da tela e webcam não será requisito do MVP.

Recursos sensíveis deverão possuir estados e permissões independentes e serão desabilitados por padrão quando apropriado.

---

# 7. Autonomia e Proatividade

## 7.1 Autonomia

Autonomia não será uma configuração booleana global.

Não existirá como princípio arquitetural:

```text
autonomous = true
```

A capacidade de agir será resultante de:

```text
Autonomy =
    permissions
  + delegations
  + policies
  + risk
  + context
  + resource scope
```

## 7.2 Delegações

O usuário poderá delegar objetivos persistentes ou temporários.

Uma delegação deverá separar:

- objetivo;
- autoridade concedida;
- recursos permitidos;
- ações permitidas;
- ações restritas;
- ações proibidas;
- duração;
- políticas de confirmação.

Definir um objetivo não concede automaticamente todas as permissões necessárias para alcançá-lo.

## 7.3 Proatividade

A Sofia poderá reagir a eventos mesmo sem conversa ativa.

Exemplos futuros:

- reminders;
- calendário;
- e-mail;
- mudanças em arquivos;
- GitHub;
- conclusão de tarefas;
- eventos de smart home;
- estado do computador.

O processamento conceitual será:

```text
Event
  ↓
Attention Policy
  ↓
Ignore / Remember / Notify / Plan / Act
```

A execução automática somente será permitida dentro das políticas e delegações aplicáveis.

---

# 8. Modelo de Capabilities

O Sofia's Assistant distinguirá conceitualmente:

## Tool

Operação delimitada e executável.

Exemplos:

- read_file;
- write_file;
- web_search;
- open_application;
- git_status.

## Integration

Conector para sistema interno ou externo.

Exemplos:

- GitHub;
- Calendar;
- Home Assistant;
- e-mail.

## Event Source

Origem de eventos observáveis pelo runtime.

Exemplos:

- FileWatcher;
- Calendar;
- GitHub;
- Scheduler.

## Agent

Especialização capaz de receber um objetivo e utilizar múltiplas ferramentas para alcançá-lo.

## Plugin

Pacote extensível que poderá disponibilizar:

- Tools;
- Integrations;
- Event Sources;
- Agent definitions;
- configuração;
- permissões necessárias.

---

# 9. Modelo de Agents

## 9.1 Sofia/root

A Sofia/root será a única autoridade de coordenação de agents.

Somente ela poderá criar ou instanciar sub-agents.

Um sub-agent poderá identificar que outra especialização é necessária, mas deverá solicitar essa delegação à Sofia/root.

Todos os agents responderão à Sofia/root.

## 9.2 Instanciação

Sub-agents serão preferencialmente instanciados sob demanda.

Não serão processos permanentes apenas por serem agents.

## 9.3 Context isolation

Um Agent receberá somente o contexto necessário para sua tarefa.

Não deverá receber automaticamente toda a conversa, memória ou dados pessoais conhecidos pela Sofia.

## 9.4 Permissions

Permissões de Agent deverão obedecer:

```text
Agent permissions
    ⊆ Delegated permissions
    ⊆ Root authorized permissions
```

Um Agent não poderá elevar a própria autoridade.

## 9.5 Workspace

Execuções que atuem sobre recursos deverão possuir scope explícito.

Um Development Agent, por exemplo, poderá ser restrito a um determinado repositório.

---

# 10. AI Provider Model

O produto deverá suportar múltiplos providers e modelos.

## 10.1 Capability-based routing

Modelos poderão ser selecionados por capabilities como:

- text;
- vision;
- audio input;
- audio output;
- realtime;
- tool calling;
- structured output;
- reasoning;
- context size;
- execução local;
- classe de custo.

## 10.2 Multi-provider session

Uma mesma experiência da Sofia poderá utilizar modelos diferentes para tarefas diferentes.

Exemplo:

```text
Realtime conversation → Provider A

Complex reasoning → Provider B

Background classification → Provider C

Embeddings → Provider D
```

Essa alternância não deverá modificar a identidade da Sofia.

## 10.3 Data locality

Operações deverão poder declarar requisitos como:

- LOCAL_ONLY;
- CLOUD_ALLOWED;
- CLOUD_PREFERRED.

Fallback entre providers deverá respeitar essas políticas.

Uma operação restrita a dados locais não poderá silenciosamente migrar para um provider cloud.

## 10.4 Realtime Provider

Realtime será tratado como capability/interface especializada e não como método opcional de uma interface universal.

## 10.5 Context ownership

Conversation lifecycle e contexto pertencem ao Sofia's Assistant.

Sessões nativas de providers poderão ser utilizadas como otimização, mas não serão a autoridade da conversa.

---

# 11. Context Model

O contexto fornecido ao modelo não será simplesmente todo o transcript concatenado.

O Sofia's Assistant construirá uma projeção contextual contendo apenas informações relevantes.

Um Context Builder poderá utilizar:

- identidade da Sofia;
- conversa ativa;
- Working Memory;
- memórias relevantes;
- Task ativa;
- Delegation ativa;
- resultados recentes de Tools;
- estado ambiental;
- eventos recentes.

Long conversation history deverá ser administrado explicitamente pelo runtime.

---

# 12. Memory Architecture

## 12.1 Sofias Memory

O **Sofias Memory será a autoridade da memória cognitiva persistente de longo prazo**.

O Sofia's Assistant não implementará um segundo mecanismo independente de memória semântica.

## 12.2 Working Memory

Working Memory pertencerá ao Assistant.

Ela poderá incluir:

- estado da conversa;
- objetivo atual;
- hipóteses temporárias;
- tool results recentes;
- contexto visual recente;
- estado ambiental temporário.

Working Memory não precisa ser enviada automaticamente ao Sofias Memory.

## 12.3 Conversation History

Histórico de conversa poderá ser persistido operacionalmente pelo Assistant.

Conversation History não será equivalente a Long-Term Memory.

```text
Conversation History ≠ Cognitive Memory
```

## 12.4 Memory Candidates

Informações extraídas de conversas e eventos deverão passar por uma etapa de candidatura antes de se tornarem memória cognitiva.

Fluxo conceitual:

```text
Conversation / Event
        ↓
Memory Candidate
        ↓
Classification
        ↓
Validation
        ↓
Conflict Detection
        ↓
Memory Policy
        ↓
Persistent Memory
```

## 12.5 Tipos cognitivos

O modelo deverá distinguir conceitualmente:

- Profile Memory;
- Semantic Memory;
- Episodic Memory;
- Procedural Memory.

Essas classificações não exigem necessariamente storages físicos separados.

## 12.6 Provenance

Memórias deverão preservar origem como, por exemplo:

- USER_ASSERTED;
- USER_CONFIRMED;
- TOOL_OBSERVED;
- IMPORTED;
- INFERRED;
- ASSISTANT_GENERATED.

Conteúdo gerado pela própria Sofia não poderá automaticamente tornar-se fato sobre o usuário.

## 12.7 Confidence

Memórias inferidas poderão possuir confidence, desde que sua semântica seja explicitamente definida.

## 12.8 Temporalidade

O modelo deverá poder representar temporalidade quando necessária, incluindo conceitos como:

- observed_at;
- valid_from;
- valid_until.

## 12.9 Contradições e supersession

Uma memória poderá:

- confirmar;
- contradizer;
- substituir semanticamente;

uma memória anterior sem exigir perda do histórico.

## 12.10 Importance

Importância para o usuário será distinta de relevância semântica para uma consulta.

Memórias poderão possuir mecanismos futuros de importância ou pinning.

## 12.11 Consolidation

Conversas e eventos poderão ser consolidados em episódios e memórias duráveis de nível superior.

## 12.12 Procedural Memory

Skills poderão integrar o ecossistema cognitivo como forma de Procedural Memory, ainda que possuam domínio e API específicos no Sofias Memory.

## 12.13 Memory Orchestrator

O Sofia's Assistant terá um Memory Orchestrator responsável por:

- detectar Memory Candidates;
- classificá-las;
- aplicar Memory Policy;
- solicitar confirmação quando necessário;
- iniciar consolidação;
- solicitar retrieval ao Sofias Memory;
- injetar memória relevante no contexto.

Embeddings, knowledge graph e storage semântico continuarão sendo responsabilidades do Sofias Memory.

---

# 13. Policy & Authorization

## 13.1 Deterministic authorization boundary

Modelos de IA não serão autoridade de autorização.

Eles poderão:

- interpretar intenção;
- identificar riscos;
- explicar uma solicitação;
- recomendar uma ação.

Mas a decisão final de autorização será realizada pelo runtime através de estado e regras explícitas.

## 13.2 PolicyEngine

Operações sobre recursos protegidos passarão pelo PolicyEngine.

Isso inclui inclusive leituras quando o recurso possuir sensibilidade.

A avaliação deverá considerar, quando aplicável:

- subject;
- operação;
- recurso;
- contexto;
- delegação;
- grants;
- sensitivity;
- side effects;
- risk.

## 13.3 Policy Decisions

O runtime deverá suportar semanticamente decisões como:

- ALLOW;
- DENY;
- REQUIRE_CONFIRMATION;
- REQUIRE_ELEVATION.

## 13.4 Permission Grants

Permissões persistentes deverão ser explícitas, auditáveis e revogáveis.

Poderão incluir:

- subject;
- capability;
- resource scope;
- constraints;
- issued_at;
- expires_at;
- revoked_at.

## 13.5 Escopo temporal

Grants e delegações poderão futuramente possuir escopos como:

- ONE_SHOT;
- SESSION;
- UNTIL_TIME;
- UNTIL_REVOKED;
- WHILE_RESOURCE_ACTIVE.

---

# 14. Tool Runtime

Toda Tool deverá possuir contrato formal.

Conceitualmente, uma Tool terá informações equivalentes a:

- identidade;
- descrição;
- input schema;
- output schema;
- capabilities;
- required permissions;
- risk semantics;
- timeout;
- idempotency;
- side effects;
- execution mode.

Retornos também deverão utilizar estrutura normalizada.

Providers não conversarão diretamente com implementações concretas de Tools.

Tool calls nativas serão normalizadas pelo Provider Adapter.

---

# 15. Tasks e Execution

## 15.1 Task

Task representa uma unidade de trabalho solicitada ou delegada.

Uma Task poderá ser resolvida por:

- Tool direta;
- workflow;
- AgentRun.

## 15.2 AgentRun

AgentRun representa uma estratégia de execução baseada em um Agent.

```text
Task ≠ AgentRun
```

Nem toda Task exigirá um Agent.

## 15.3 Operações longas

Operações suficientemente longas ou compostas não deverão bloquear a conversa.

## 15.4 Persistence

Tasks deverão possuir estado persistente suficiente para sobreviver a restart.

## 15.5 Cancellation

Cancelamento será cooperativo sempre que necessário para evitar interrupção insegura de efeitos externos.

## 15.6 Recovery

Após crash/reboot, o runtime deverá identificar operações interrompidas e aplicar semântica explícita de recovery.

Recovery poderá resultar em:

- retry;
- resume;
- failure;
- confirmação do usuário.

O sistema não deverá presumir automaticamente que uma operação interrompida nunca produziu efeitos.

---

# 16. Event Runtime

O Sofia Core terá Event Runtime explícito.

Serão diferenciados conceitualmente:

## Domain Events

Eventos produzidos pelo próprio sistema.

Exemplos:

- TaskStarted;
- TaskCompleted;
- ToolExecuted;
- PermissionGranted.

## External Events

Eventos observados fora do domínio interno.

Exemplos:

- FileChanged;
- ReminderDue;
- CalendarEventStarting;
- PullRequestUpdated.

Persistência será seletiva conforme a importância e semântica do evento.

Plugins e integrations poderão futuramente registrar Event Sources.

---

# 17. Scheduler

Scheduler fará parte do Sofia Core.

Será responsável por infraestrutura temporal compartilhada para:

- reminders;
- recurring jobs;
- tarefas futuras;
- automações agendadas.

Jobs persistentes deverão sobreviver a restart.

O Scheduler não executará side effects diretamente.

Fluxo:

```text
Scheduler
   ↓
Event
   ↓
Task / Policy
   ↓
Execution
```

---

# 18. Runtime e Client Architecture

## 18.1 Sofia Core

O MVP utilizará inicialmente uma arquitetura de modular monolith.

O Core poderá utilizar subprocessos ou workers isolados quando houver justificativa de segurança ou estabilidade.

## 18.2 Core independente

Sofia Core continuará executando independentemente da janela gráfica.

Isso permitirá:

- tasks em background;
- reminders;
- wake word;
- monitoring;
- proatividade;
- event processing.

## 18.3 UI como Client

A interface Desktop será cliente do Core.

A lógica de negócio não dependerá diretamente da UI.

A arquitetura deverá permitir futuros clients como:

- CLI;
- Web;
- mobile companion;
- remote client.

## 18.4 Interface local

Deverá existir uma interface formal de comunicação entre clients e Sofia Core.

A tecnologia concreta será decidida em ADR.

---

# 19. Operational Persistence

O Sofia's Assistant possuirá banco operacional próprio, independente do Sofias Memory.

Inicialmente será preferido SQLite.

Esse storage deverá atender estados como:

- conversations;
- Tasks;
- AgentRuns;
- Delegations;
- Permission Grants;
- Policies;
- schedules;
- events persistentes;
- audit;
- settings.

O domínio não deverá depender diretamente de APIs específicas do SQLite.

Migrations deverão existir desde o início.

---

# 20. Security & Isolation Principles

O Sofia's Assistant deverá preservar possibilidade de múltiplos modos de execução, incluindo:

- IN_PROCESS;
- SUBPROCESS;
- SANDBOX.

Código desconhecido ou operações de maior risco poderão exigir isolamento.

Plugins, workers e subprocessos deverão, sempre que tecnicamente possível, falhar sem derrubar o Sofia Core.

Shell será capability poderosa e suportada, porém sujeita a:

- resource scope;
- timeout;
- policy;
- risk evaluation;
- confirmação quando aplicável.

Execução em host e sandbox poderão coexistir conforme policy.

---

# 21. Secrets

Secrets não deverão ser armazenados em texto simples em JSON ou configuração comum.

O produto deverá possuir abstração `SecretStore`.

Em Windows, deverão ser considerados mecanismos seguros nativos como Credential Manager e/ou proteção baseada em DPAPI.

Futuramente uma CLI poderá gerenciar secrets, mas deverá utilizar o mesmo serviço/abstração.

---

# 22. Audit Trail

Ações relevantes deverão permitir reconstruir:

- quem ou o que solicitou;
- Task associada;
- AgentRun quando houver;
- Tool executada;
- contexto relevante;
- Policy aplicada;
- Grant ou Delegation utilizados;
- recursos afetados;
- resultado.

Audit Trail não deverá ser tratado apenas como log de diagnóstico.

---

# 23. Capability Map

O produto terá como universo de evolução:

- System;
- Filesystem;
- Desktop;
- Browser;
- Web/Research;
- Development;
- Documents/Productivity;
- Communication;
- Calendar;
- Email;
- Smart Home;
- Media;
- Knowledge/Memory;
- Automation;
- Remote Companion.

Este mapa não representa compromisso de MVP.

---

# 24. Escopo do MVP

O MVP deverá validar o kernel arquitetural de ponta a ponta com um conjunto pequeno de capabilities úteis.

## 24.1 Conversation

- texto;
- realtime voice;
- streaming;
- barge-in;
- continuidade entre texto e voz.

## 24.2 AI

- Provider abstraction;
- capability-based provider selection;
- ao menos um realtime provider funcional.

## 24.3 Context

- Working Memory explícita;
- Context Builder;
- gerenciamento explícito do contexto.

## 24.4 Memory

- integração real com Sofias Memory;
- basic remember;
- recall;
- consolidação básica de conversas;
- Memory Orchestrator inicial.

## 24.5 Policy

- PolicyEngine;
- Permission Grants;
- risk evaluation;
- confirmation flow;
- resource scopes.

## 24.6 Tools

O MVP deverá incluir capabilities básicas para:

- filesystem read;
- filesystem write;
- shell;
- abrir aplicação;
- consultar aplicação ativa;
- web search;
- leitura de conteúdo web;
- screenshot manual;
- vision sobre screenshot.

## 24.7 Web

A primeira versão fornecerá:

- pesquisa web;
- leitura de fontes;
- síntese básica de múltiplas fontes.

Automação completa de navegador e Research Agent avançado serão posteriores.

## 24.8 Events

- Event Runtime;
- Scheduler;
- reminder;
- Task completion events.

## 24.9 Agents

O MVP deverá possuir um Agent experimental para validar:

- Agent Registry;
- criação exclusiva pela Sofia/root;
- context isolation;
- delegated permissions;
- Tool subset;
- AgentRun;
- result handoff.

O Agent específico será definido durante detalhamento técnico.

## 24.10 Desktop Client

O MVP deverá possuir inicialmente:

- tray;
- chat;
- estado da voz;
- interface de confirmação;
- visualização básica de Tasks/status.

---

# 25. Fora do Escopo do MVP

Explicitamente não são requisitos do primeiro MVP:

- full Development Agent;
- multiple specialized agents;
- advanced Research Agent;
- automação completa do navegador;
- monitoramento contínuo da tela;
- camera awareness;
- smart home;
- e-mail;
- Calendar;
- WhatsApp;
- Discord;
- Telegram;
- suíte de geração DOCX/XLSX/PPTX;
- remote/mobile companion;
- gesture control;
- plugin ecosystem completo;
- marketplace de plugins;
- escuta contínua permanente;
- multi-user;
- SaaS;
- modelo local obrigatório.

Esses recursos poderão ser adicionados posteriormente sem alterar os princípios do kernel.

---

# 26. Requisitos Funcionais

## FR-001

O usuário deverá poder conversar com Sofia por texto.

## FR-002

O usuário deverá poder conversar com Sofia por realtime voice.

## FR-003

O usuário deverá poder interromper naturalmente a resposta de voz.

## FR-004

Texto e voz deverão compartilhar contexto de conversa.

## FR-005

Sofia deverá recuperar memória persistente relevante através do Sofias Memory.

## FR-006

Sofia deverá distinguir Working Memory de Long-Term Memory.

## FR-007

Conversation History não deverá ser transformado automaticamente em memória cognitiva.

## FR-008

O sistema deverá suportar Memory Candidates e consolidação.

## FR-009

O sistema deverá executar Tools através de um runtime normalizado.

## FR-010

Operações protegidas deverão passar pelo PolicyEngine.

## FR-011

O usuário deverá poder conceder e revogar permissões persistentes.

## FR-012

O usuário deverá poder criar Delegations com recursos e limites.

## FR-013

O sistema deverá persistir Tasks longas.

## FR-014

O sistema deverá recuperar estado operacional após restart.

## FR-015

O sistema deverá suportar reminders persistentes.

## FR-016

O sistema deverá reagir a eventos internos e externos.

## FR-017

Sofia/root deverá poder instanciar sub-agents especializados.

## FR-018

Sub-agents deverão operar com contexto e permissões reduzidos.

## FR-019

O sistema deverá poder executar shell dentro de scope autorizado.

## FR-020

O sistema deverá manter Audit Trail de ações relevantes.

---

# 27. Requisitos Não Funcionais

## NFR-001 — Segurança

Nenhum LLM será autoridade final de autorização.

## NFR-002 — Privacidade

Dados restritos por política local não poderão ser enviados automaticamente a providers cloud.

## NFR-003 — Reliability

Tasks e reminders persistentes deverão sobreviver a reinícios.

## NFR-004 — Isolation

Falhas em plugins ou workers isoláveis não deverão derrubar o Sofia Core.

## NFR-005 — Extensibility

O Core deverá permitir novas Tools, Integrations, Event Sources e Agents sem alterações estruturais desnecessárias.

## NFR-006 — Provider independence

O domínio não deverá depender de formatos específicos de provider.

## NFR-007 — Memory independence

O Sofia's Assistant não deverá depender diretamente da implementação interna ou banco de dados do Sofias Memory.

A integração será realizada através de contrato explícito.

## NFR-008 — UI independence

O Sofia Core deverá funcionar sem interface gráfica ativa.

## NFR-009 — Auditability

Ações autônomas relevantes deverão ser auditáveis.

## NFR-010 — Recoverability

Operações interrompidas deverão ter tratamento explícito de recovery.

---

# 28. Critérios de Sucesso do MVP

O MVP será considerado arquiteturalmente bem-sucedido quando for possível executar, de ponta a ponta, cenários equivalentes aos seguintes:

### Cenário 1 — Conversa persistente

O usuário conversa com Sofia por texto e voz, interrompe sua fala e continua a mesma conversa sem mudança de identidade ou perda indevida de contexto.

### Cenário 2 — Memória

O usuário informa uma decisão relevante, o sistema cria um Memory Candidate, consolida-a e posteriormente recupera essa memória através do Sofias Memory.

### Cenário 3 — Filesystem protegido

O usuário solicita modificação em arquivos de um workspace e o PolicyEngine autoriza ou solicita confirmação conforme os Grants existentes.

### Cenário 4 — Shell

Sofia executa comando autorizado dentro de workspace com timeout, captura de resultado e Audit Trail.

### Cenário 5 — Web

Sofia pesquisa informações externas, lê múltiplas fontes e produz síntese contextualizada.

### Cenário 6 — Reminder

O usuário cria reminder, encerra/reinicia Sofia e o reminder continua programado e é entregue através do Event Runtime.

### Cenário 7 — Agent

Sofia/root instancia um Agent, entrega contexto e permissões reduzidas, recebe seu resultado e mantém autoridade central sobre a execução.

### Cenário 8 — Recovery

Uma Task é interrompida por restart e o Core reconhece seu estado anterior e aplica semântica de recovery.

### Cenário 9 — Provider routing

O sistema utiliza providers diferentes para capabilities diferentes sem alterar identidade, estado ou contratos internos.

---

# 29. Questões Explicitamente Transferidas para ADRs

O PRD não decide:

- framework da API local;
- HTTP/WebSocket/socket/IPC concreto;
- desktop shell;
- Tauri ou alternativa;
- ORM;
- biblioteca de migrations;
- Event Bus implementation;
- Task state machine exata;
- formato final de ToolSpec;
- estrutura final de ToolResult;
- sandbox technology;
- realtime provider inicial;
- provider routing algorithm;
- biblioteca de áudio;
- forma concreta de armazenamento seguro de secrets;
- primeiro Agent experimental;
- evolução exata da API do Sofias Memory;
- schemas definitivos das entidades operacionais.

Essas decisões deverão ser tomadas por ADRs e Backlogs Técnicos.

---

# 30. Product Gates

## Gate 1 — Product Definition

**Status: CLOSED**

Visão, escopo, princípios, MVP e limites do produto estão definidos.

## Gate 2 — Architecture Definition

**Status: READY FOR ADR MATERIALIZATION**

As principais decisões conceituais estão definidas, mas tecnologias e contratos finais deverão ser materializados em ADRs.

## Gate 3 — MVP Definition

**Status: BASELINE DEFINED**

O capability cut do MVP foi estabelecido, sujeito apenas aos refinamentos derivados dos ADRs.

## Gate 4 — Implementation Readiness

**Status: NOT STARTED**

Será considerado atingido somente após:

1. PRD aprovado;
2. ADRs mandatórios aprovados;
3. Technical Backlog criado e priorizado;
4. critérios de gates definidos;
5. estrutura inicial do projeto autorizada.

---

# 31. Declaração Final de Produto

> **Sofia's Assistant é um sistema pessoal de inteligência artificial local-first, single-user por instalação, multimodal, extensível e orientado a eventos, com realtime voice, memória persistente, ferramentas, planejamento, sub-agents especializados e capacidade de agir proativamente dentro de políticas explícitas de autonomia e segurança.**

Seu objetivo central é evoluir de uma interface conversacional para um assistente pessoal contínuo que possa compreender contexto, acumular conhecimento, aprender procedimentos e realizar trabalho real sem retirar do usuário a autoridade sobre seu ambiente.