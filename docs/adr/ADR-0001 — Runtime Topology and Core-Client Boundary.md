# ADR-0001 — Runtime Topology and Core/Client Boundary

**Status:** Accepted  
**Project:** Sofia's Assistant  
**Decision date:** 2026-08-31  
**Scope:** Runtime topology, process boundaries and client/core relationship

---

# 1. Context

Sofia's Assistant será um sistema pessoal de IA local-first, single-user por instalação, capaz de:

- manter conversas por texto e realtime voice;
- permanecer ativo em background;
- executar Tasks longas;
- processar reminders;
- reagir a eventos externos;
- operar proativamente dentro de políticas;
- utilizar Tools;
- instanciar sub-agents;
- integrar-se ao Sofias Memory;
- continuar operando mesmo quando a janela principal estiver fechada.

Essas características tornam inadequado um desenho onde toda a aplicação exista dentro do processo da interface gráfica.

Também não existe justificativa para introduzir uma arquitetura distribuída baseada em microservices no MVP.

A arquitetura precisa equilibrar:

- simplicidade operacional;
- separação de responsabilidades;
- crash isolation;
- extensibilidade;
- execução em background;
- múltiplos clients futuros;
- isolamento seletivo de código inseguro;
- capacidade de evolução.

---

# 2. Decision

Sofia's Assistant adotará inicialmente uma arquitetura de **modular monolith com Sofia Core persistente e clients desacoplados**.

A topologia conceitual será:

```text
                    ┌─────────────────┐
                    │  Desktop Client │
                    └────────┬────────┘
                             │
                    Local Client API
                             │
                             ▼
                    ┌─────────────────┐
                    │    Sofia Core   │
                    │                 │
                    │ persistent      │
                    │ background      │
                    │ runtime         │
                    └────────┬────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
          ▼                  ▼                  ▼
   Operational DB      Sofias Memory      Auxiliary Workers
       SQLite            external        subprocess/sandbox
```

O Sofia Core será a autoridade do runtime.

A Desktop UI será um client.

---

# 3. Sofia Core

O `Sofia Core` será responsável por executar o domínio e runtime principal do produto.

Ele deverá possuir módulos internos independentes para responsabilidades como:

- application lifecycle;
- conversation runtime;
- realtime sessions;
- Context Builder;
- AI routing;
- PolicyEngine;
- permission grants;
- delegations;
- Tool Registry;
- Tool Runtime;
- Task Runtime;
- Agent orchestration;
- Event Runtime;
- Scheduler;
- Memory Orchestrator;
- operational persistence;
- audit;
- client communication.

Esses módulos permanecerão dentro da mesma aplicação implantável inicialmente.

A escolha por modular monolith não autoriza dependências arbitrárias entre módulos.

Boundaries internos deverão permanecer explícitos.

---

# 4. Core Lifecycle

O Sofia Core deverá possuir lifecycle independente da Desktop UI.

O Core poderá continuar executando quando:

- a janela principal for fechada;
- a aplicação estiver apenas no system tray;
- nenhuma conversa estiver visualmente aberta.

Essa característica é necessária para:

- reminders;
- Tasks em background;
- realtime voice activation;
- wake word futuro;
- event sources;
- scheduler;
- delegated Tasks;
- proatividade;
- monitoramento autorizado;
- recovery.

Encerrar a janela principal não deverá ser semanticamente equivalente a desligar Sofia.

Deverá existir uma ação explícita para encerrar o Core.

---

# 5. Client Boundary

Interfaces de usuário não poderão importar ou controlar diretamente serviços internos do domínio.

O relacionamento será:

```text
Client
  ↓
Client API / IPC contract
  ↓
Sofia Core
```

e não:

```text
UI
 ↓
import TaskService
 ↓
database
```

A UI poderá solicitar operações e assinar estados/eventos expostos pelo Core.

A UI não será autoridade sobre:

- Task state;
- permission state;
- memory state;
- scheduler;
- AgentRun;
- Tool execution;
- policy decisions.

---

# 6. Local Client API

O Core deverá possuir uma interface local formal para comunicação com clients.

Essa interface deverá suportar, conceitualmente:

## Request/response

Exemplos:

```text
send message
create reminder
approve permission request
cancel task
read task state
read settings
```

## Streaming

Exemplos:

```text
conversation tokens
realtime voice state
Task progress
Agent progress
Tool execution state
```

## Events

Exemplos:

```text
PermissionRequested
TaskCompleted
ReminderDue
ConversationUpdated
ProviderStateChanged
```

A tecnologia concreta será definida posteriormente.

Candidatos incluem:

- HTTP;
- WebSocket;
- local sockets;
- named pipes;
- combinação entre eles.

Este ADR define o boundary, não o protocolo.

---

# 7. Clients

O primeiro client será o Desktop Client.

A arquitetura deverá permitir futuramente outros clients sem alteração fundamental do Sofia Core.

Exemplos:

```text
Desktop Client
CLI
Web Client
Mobile Companion
Remote Client
```

Isso não significa que todas essas interfaces farão parte do MVP.

Apenas significa que o domínio não ficará preso à primeira UI.

---

# 8. Desktop Client

O Desktop Client deverá ser responsável principalmente por apresentação e interação.

Exemplos de responsabilidades:

- chat;
- input textual;
- controle visual de voz;
- task visualization;
- permission confirmations;
- notifications;
- settings UI;
- tray integration;
- visualização de estados;
- superfícies contextuais.

Ele não deverá implementar regras de negócio que precisem continuar válidas na ausência da interface.

---

# 9. System Tray

O Desktop Client poderá oferecer integração com system tray.

A ação de fechar a janela deverá poder significar:

```text
hide UI
```

em vez de:

```text
shutdown Sofia
```

O tray poderá futuramente disponibilizar ações como:

- abrir Sofia;
- ativar/mutar voz;
- consultar status;
- pausar proatividade;
- acessar Tasks;
- encerrar Sofia Core.

Os detalhes pertencem ao backlog de UI.

---

# 10. Auxiliary Processes

Modular monolith não significa que toda execução deve ocorrer dentro do processo principal.

O Sofia Core poderá criar ou coordenar processos auxiliares quando houver justificativa.

Exemplos:

```text
Plugin Worker
Sandbox Worker
Tool subprocess
Code execution environment
Media/audio worker
```

Esses processos são extensões operacionais do Core, não microservices independentes.

O Sofia Core continuará sendo a autoridade sobre:

- lifecycle;
- authorization;
- Task state;
- coordination;
- audit.

---

# 11. Process Isolation

Capacidades com risco ou instabilidade poderão executar fora do processo principal.

Exemplos:

- código desconhecido;
- plugins não confiáveis;
- shell;
- generated code;
- bibliotecas nativas instáveis.

O objetivo é evitar que:

```text
plugin crash
```

resulte automaticamente em:

```text
Sofia Core crash
```

Os detalhes de `IN_PROCESS`, `SUBPROCESS` e `SANDBOX` serão definidos em ADR específico.

---

# 12. Sofias Memory Boundary

Sofias Memory permanecerá um serviço independente.

Sofia Core se integrará através de contrato explícito.

Não será permitido:

```python
from sofias_memory.services import ...
```

como dependência arquitetural entre os projetos.

A integração deverá conceitualmente ocorrer como:

```text
Sofia Core
    ↓
Memory Provider / Adapter
    ↓
Sofias Memory API
```

Assim:

- os dois projetos podem possuir releases independentes;
- Sofias Memory permanece reutilizável;
- Sofia Core não depende de PostgreSQL/Neo4j internos;
- mudanças internas no Sofias Memory não contaminam o Assistant.

---

# 13. Operational Database Boundary

O banco operacional pertence ao Sofia Core.

Clients não deverão acessar SQLite diretamente.

Não será permitido:

```text
Desktop Client
     ↓
   SQLite
```

O fluxo será:

```text
Desktop Client
     ↓
Sofia Core API
     ↓
Persistence layer
     ↓
SQLite
```

Isso preserva invariantes do domínio e permite futura mudança de implementação.

---

# 14. Startup

O produto deverá possuir um processo de startup controlado.

Conceitualmente:

```text
Start Sofia
    ↓
Load configuration
    ↓
Initialize SecretStore
    ↓
Open operational storage
    ↓
Run persistence compatibility checks
    ↓
Recover runtime state
    ↓
Initialize core services
    ↓
Start Event Runtime / Scheduler
    ↓
Start local client interface
    ↓
Start Desktop Client
```

A sequência concreta poderá evoluir.

O princípio é que Core readiness seja distinguível de UI readiness.

---

# 15. Shutdown

Shutdown deverá ser explícito e gracioso.

O Core deverá, quando possível:

- parar de aceitar novas operações;
- persistir estado necessário;
- interromper workers de forma controlada;
- cancelar ou marcar corretamente Tasks;
- finalizar conexões;
- liberar recursos.

Fechar a UI não deverá automaticamente iniciar esse processo.

---

# 16. Crash Recovery

Após restart não gracioso, o Core deverá consultar seu estado persistido antes de assumir que está limpo.

Exemplos:

```text
RUNNING Task
RUNNING AgentRun
pending confirmation
scheduled reminder
active delegation
```

deverão ser reconciliados.

A semântica detalhada pertence ao ADR de Task Recovery.

---

# 17. Technology Constraints

Este ADR não escolhe ainda:

- FastAPI;
- Flask;
- gRPC;
- WebSocket implementation;
- Tauri;
- Electron;
- PySide;
- native Windows shell;
- SQLAlchemy;
- SQLModel;
- outro ORM;
- IPC protocol.

Essas decisões deverão respeitar o boundary definido aqui.

---

# 18. Alternatives Considered

## Alternative A — UI and Core in one process

```text
Desktop App
├── UI
├── AI
├── Tasks
├── Memory
└── Tools
```

### Advantages

- desenvolvimento inicial aparentemente mais simples;
- menos comunicação entre processos.

### Rejected because

- fechar UI poderia interromper runtime;
- dificulta reminders e Tasks em background;
- mistura presentation e domain lifecycle;
- reduz possibilidade de CLI/mobile/remote client;
- piora crash isolation;
- tende a gerar God UI semelhante aos projetos analisados.

---

## Alternative B — Microservices

Separar desde o início:

```text
conversation-service
task-service
memory-service
policy-service
tool-service
agent-service
event-service
```

### Advantages

- isolamento forte;
- deployment independente.

### Rejected because

- complexidade operacional excessiva;
- comunicação distribuída;
- observabilidade mais difícil;
- transações e consistency mais difíceis;
- deployment local muito mais complexo;
- nenhum requisito atual justifica o custo.

---

## Alternative C — Embedded library architecture

Sofia seria primariamente uma biblioteca Python importada pela UI.

### Advantages

- integração simples;
- pouco overhead.

### Rejected because

não representa adequadamente o lifecycle persistente e orientado a eventos esperado para o produto.

---

# 19. Consequences

## Positive

- Core continua ativo sem UI;
- separação clara de responsabilidades;
- clients futuros são possíveis;
- melhora testabilidade;
- permite crash isolation;
- evita microservices prematuros;
- Sofia Core permanece autoridade única do runtime;
- facilita Tasks, events e reminders em background.

## Negative

- exige protocolo entre Core e UI;
- lifecycle fica mais complexo;
- haverá sincronização de estado UI/Core;
- debugging atravessa um boundary adicional;
- startup/shutdown precisam ser formalizados.

Esses custos são considerados aceitáveis.

---

# 20. Architectural Invariants

As seguintes regras tornam-se obrigatórias:

### INV-001

UI não acessa persistence diretamente.

### INV-002

UI não executa Tools diretamente.

### INV-003

UI não decide Policy.

### INV-004

Fechar UI não equivale a shutdown do Core.

### INV-005

Core pode funcionar sem Desktop Client.

### INV-006

Processos auxiliares respondem ao Core.

### INV-007

Sofias Memory é integração externa ao Core.

### INV-008

Módulos do modular monolith mantêm boundaries explícitos.

---

# 21. Deferred Decisions

Serão resolvidos posteriormente:

- protocolo local Core ↔ Client;
- desktop shell;
- mecanismo de auto-start;
- processo Windows/background implementation;
- comportamento detalhado do tray;
- comunicação Core ↔ worker;
- packaging;
- instalação;
- updates;
- remote access.

---

# 22. Decision Summary

Sofia's Assistant será inicialmente uma aplicação **modular monolith com Sofia Core persistente em background e clients desacoplados**.

A Desktop UI será cliente do Core.

Estado operacional, políticas, Tasks, Agents, Events e Tool execution pertencem ao Sofia Core.

Processos auxiliares poderão ser utilizados para isolamento, mas permanecerão subordinados ao Core.

Sofias Memory permanecerá um serviço independente acessado por contrato explícito.