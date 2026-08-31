# Sofia's Assistant — Architecture Gate Review

**Baseline analisada:** PRD v0.1 + ADR-0001 a ADR-0015  
**Data:** 2026-08-31  
**Resultado:** **CONDITIONALLY APPROVED**

---

# 1. Veredito

A arquitetura está suficientemente definida para avançar ao Technical Backlog.

Não identifiquei necessidade de criar novos ADRs antes dessa etapa.

Entretanto, o Gate 2 não deveria ser marcado como definitivamente fechado antes de aplicarmos quatro amendments pontuais.

| Finding | Severidade | ADRs afetados | Decisão |
|---|---|---|---|
| Task tornou-se wrapper universal | Alta | 0009, 0010, 0015 | Corrigir |
| Authority chain pressupõe Delegation | Alta | 0007, 0009 | Corrigir |
| Local Client API ainda não possui trust boundary explícito | Alta | 0001 | Corrigir |
| SecretStore ficou conceitualmente preso ao AI Provider layer | Média | 0004 + referências | Corrigir ownership |

Nenhum deles exige novo ADR.

---

# 2. Finding 1 — Task tornou-se wrapper universal

## Problema

No discovery original foi decidido que operações simples poderiam continuar como ToolCalls diretas e que Tasks seriam utilizadas quando o trabalho justificasse lifecycle próprio.

Entretanto, o ADR-0009 acabou materializando exemplos como:

```text
"Abra o VS Code"

Task
  ↓
Tool
```

Isso transforma praticamente qualquer operação em Task.

Essa decisão contraria dois princípios já aprovados:

```text
Use the least complex execution mechanism capable of solving the task.
```

e:

```text
não usar uma bazuca para matar uma mosca
```

Também introduziria persistence, scheduling e lifecycle onde não há necessidade.

---

# 3. Amendment recomendado para ADR-0009

A hierarquia deverá ser:

```text
User / Event / Runtime Intent
          │
          ▼
   Execution Decision
     /            \
    /              \
   ▼                ▼
Direct Invocation   Task
   │                │
 ToolCall           ├── Tool
                    ├── Workflow
                    └── AgentRun
```

Uma `ToolCall` simples poderá existir sem Task.

Exemplos:

```text
"Que horas são?"
→ direct invocation

"Abra o VS Code."
→ direct ToolCall
```

Enquanto:

```text
"Analise este repositório e corrija os testes."
→ Task
```

---

# 4. Quando Task passa a ser necessária

Task será criada quando o trabalho necessitar de pelo menos uma propriedade como:

```text
durability
background execution
multiple steps
AgentRun
waiting
scheduling
delegation
retry
recovery
progress tracking
dependency
long-running execution
```

Uma operação imediata não deverá ser promovida artificialmente para Task apenas para manter uniformidade.

---

# 5. Consequência para ADR-0010

ADR-0010 permanece válido integralmente.

Apenas muda seu escopo:

> Task Lifecycle aplica-se quando uma Task existe.

Ele não define lifecycle obrigatório para todo ToolCall.

ToolCalls diretas continuam possuindo:

```text
identity
PolicyDecision
ToolResult
Audit
timeout
```

e persistence quando necessária.

---

# 6. Consequência para ADR-0015

Audit deverá suportar ambas as cadeias.

### Direct Invocation

```text
User / Conversation
      ↓
ToolCall
      ↓
PolicyDecision
      ↓
Execution
      ↓
ToolResult
```

### Task execution

```text
User / Event / Schedule
      ↓
Task
      ↓
AgentRun / Workflow / Tool
      ↓
ToolCall
      ↓
PolicyDecision
      ↓
Execution
```

Assim não precisamos inventar Task apenas para obter rastreabilidade.

---

# 7. Finding 2 — Authority chain pressupõe Delegation

## Problema

ADR-0007 e ADR-0009 utilizam repetidamente:

```text
AgentRun authority
    ⊆ Delegation authority
    ⊆ Root effective authority
```

Isso funciona perfeitamente quando existe uma Delegation.

Mas Delegation não existirá em toda Task.

Exemplo:

> “Analise este repositório para mim.”

Sofia pode precisar criar um Development Agent imediatamente.

Não deveríamos ser obrigados a criar uma Delegation persistente artificial apenas para conseguir fornecer authority ao AgentRun.

---

# 8. Amendment recomendado para authority narrowing

A regra geral deverá ser:

```text
Execution Authority
      ⊆
Originating Authority Context
      ⊆
Root Effective Authority
```

Quando existir Delegation:

```text
AgentRun Authority
      ⊆
Task Authority
      ⊆
Delegation Authority
      ⊆
Root Effective Authority
```

Sem Delegation:

```text
AgentRun Authority
      ⊆
Task Authority
      ⊆
Root Effective Authority
```

---

# 9. Task Authority

Uma Task poderá possuir um `Authority Context` derivado de:

```text
existing Grants
+
current Policy
+
resource scope
+
explicit confirmations
+
originating user request
```

O user request define intenção.

Ele continua **não sendo permission grant por si só**.

O PolicyEngine determina quais ações já são permitidas e quais precisam de confirmação.

---

# 10. Delegation continua importante

Essa correção não reduz o papel de Delegation.

Delegation continuará sendo necessária quando houver intenção persistente ou autonomia delegada além da operação imediata.

Exemplo:

```text
"Durante esta semana acompanhe os PRs deste projeto."
```

é claramente uma Delegation.

Já:

```text
"Analise este PR agora."
```

pode ser simplesmente Task + Authority Context.

---

# 11. Finding 3 — Local Client API sem trust boundary explícito

## Problema

ADR-0001 define corretamente:

```text
Desktop Client
     ↓
Local Client API
     ↓
Sofia Core
```

mas deixa transporte e protocolo para depois.

Isso é correto.

O problema é que ainda não afirmamos explicitamente que:

```text
localhost ≠ trusted
```

Se utilizarmos HTTP/WebSocket local, qualquer processo executado na máquina poderia tentar conversar com Sofia Core.

Como o Core controla:

- filesystem;
- shell;
- Tasks;
- permissions;
- Agents;

isso precisa ser um invariant arquitetural já agora.

---

# 12. Amendment recomendado para ADR-0001

A interface Client ↔ Core deverá ser:

```text
local-only by default
+
authenticated or OS-authenticated
+
not exposed to LAN by default
```

O mecanismo concreto dependerá do transporte escolhido.

Exemplos possíveis:

```text
named pipe + OS identity

local socket + OS permissions

loopback HTTP/WebSocket
+ ephemeral/session credential
```

A tecnologia continuará deferred.

---

# 13. Client authentication não substitui Policy

Autenticar o Desktop Client significa apenas:

> este request veio de um client reconhecido.

Não significa:

> toda ação pedida por esse client está automaticamente autorizada.

Fluxo permanece:

```text
Authenticated Client
       ↓
Core Command
       ↓
PolicyEngine
       ↓
Execution
```

---

# 14. Network exposure

Baseline deverá ser:

```text
LAN access = disabled
remote access = disabled
```

Remote Companion futuro deverá exigir decisão própria de:

- authentication;
- encryption;
- device trust;
- revocation;
- network exposure.

Não devemos antecipar esse problema no MVP.

---

# 15. Finding 4 — SecretStore ownership

## Problema

SecretStore foi introduzido dentro do ADR-0004, referente a AI Providers.

Depois passou corretamente a ser utilizado por:

- Providers;
- Plugins;
- Integrations;
- Tools;
- sandbox execution.

Isso revela que SecretStore não é parte do AI Provider subsystem.

É uma capability transversal do Sofia Core.

---

# 16. Amendment recomendado

A arquitetura conceitual deverá ser:

```text
                  Sofia Core
                      │
                 Secret Service
                      │
                  SecretStore
                 /    |     \
                /     |      \
               ▼      ▼       ▼
          Providers Plugins Integrations
                         \
                          Tools
```

ADR-0004 continuará dizendo:

> Provider Adapters obtêm credentials pelo SecretStore.

Mas não deverá sugerir ownership pelo AI subsystem.

---

# 17. Não criar ADR separado para SecretStore agora

Ainda não há necessidade.

A implementação concreta continua deferred:

```text
Windows Credential Manager
DPAPI
encrypted local store
```

Se a escolha futura produzir consequências estruturais relevantes, ela poderá gerar ADR próprio.

Por enquanto o boundary é suficiente.

---

# 18. Verificação de conflitos entre ADRs

Após essas correções, não identifiquei conflito entre:

| Boundary | Resultado |
|---|---|
| Core vs UI | Coerente |
| Operational Store vs Sofias Memory | Coerente |
| Provider vs Sofia identity | Coerente |
| LLM vs Policy authority | Coerente |
| Grant vs Delegation | Coerente após amendment |
| Tool vs Agent | Coerente |
| Tool vs Task | Coerente após amendment |
| Agent vs root | Coerente |
| Event vs Task | Coerente |
| Scheduler vs Executor | Coerente |
| Working Memory vs Cognitive Memory | Coerente |
| Knowledge Source vs Cognitive Memory | Coerente |
| Plugin vs Core | Coerente |
| Trust vs Authority | Coerente |
| Audit vs Event vs Log | Coerente |

---

# 19. Areas deliberadamente ainda abertas

As seguintes questões continuam abertas corretamente e **não bloqueiam o Architecture Gate**:

| Área | Deve ser resolvida em |
|---|---|
| FastAPI ou alternativa | Technical Backlog / implementation decision |
| HTTP/WebSocket/Named Pipe | Technical Backlog |
| Desktop shell / Tauri etc. | Technical Backlog |
| ORM | Technical Backlog |
| Migration library | Technical Backlog |
| Event Bus implementation | Technical Backlog |
| Scheduler library | Technical Backlog |
| First realtime provider | Technical Backlog |
| Audio/VAD implementation | Technical Backlog |
| Task enum físico | Technical Backlog |
| ToolSpec Python schema | Technical Backlog |
| Sandbox backend Windows | Technical Backlog |
| Plugin packaging | Post-foundation backlog |
| Audit schema físico | Technical Backlog |
| Sofias Memory typed schemas | Sofias Memory Technical Backlog |

Essas são implementation decisions, não lacunas de produto.

---

# 20. Domínios técnicos que precisam aparecer no Backlog

A revisão identificou alguns componentes que aparecem transversalmente nos ADRs e precisam existir explicitamente no Technical Backlog, mesmo não merecendo ADR próprio.

### Artifact Service

Necessário para:

```text
Tool artifacts
screenshots
generated files
sandbox outputs
reports
attachments
```

Deverá fornecer references estáveis e não depender de blobs indiscriminadamente dentro de ToolResult.

### Notification / Attention Service

Necessário para:

```text
reminders
Task completion
proactive notifications
permission requests
```

`Attention Policy` poderá amadurecer nesse domínio.

### Client Session / Local Authentication

Necessário para implementar o amendment do ADR-0001.

### Secret Service

Boundary transversal sobre SecretStore.

### Runtime Health / Readiness

Necessário para representar:

```text
provider degraded
memory unavailable
scheduler unavailable
plugin degraded
```

Esses componentes são Technical Backlog items, não novos ADRs.

---

# 21. Revisão do modelo geral

Após os amendments, a arquitetura pode ser resumida como:

```text
                         Clients
                            │
                   authenticated local boundary
                            │
                            ▼
┌──────────────────────────────────────────────────────┐
│                     Sofia Core                       │
│                                                      │
│ Conversation Runtime                                 │
│ Context Builder                                      │
│ Root Orchestrator                                    │
│                                                      │
│ Direct Invocation ───────────────┐                   │
│                                 │                    │
│ Task Runtime                    │                    │
│   ├── Workflow                  │                    │
│   └── AgentRun                  │                    │
│                                 ▼                    │
│                         Tool Runtime                  │
│                                 │                    │
│                         PolicyEngine                  │
│                                 │                    │
│                      Execution Boundary               │
│                                                      │
│ Event Runtime / Scheduler                            │
│ Memory Orchestrator                                  │
│ Audit                                                │
│ Secret Service                                       │
│ Artifact Service                                     │
└───────────────┬──────────────────────────┬───────────┘
                │                          │
                ▼                          ▼
       Operational Store             Sofias Memory
            SQLite                Cognitive Persistence
```

---

# 22. Architecture principles confirmed by review

O conjunto preserva corretamente os princípios fundamentais:

```text
Local-first.

UI is a client.

Sofia Core owns runtime.

Provider does not define Sofia.

AI proposes; Runtime authorizes.

Objective does not imply authority.

Least privilege.

Least complex execution mechanism.

Task is durable work, not mandatory wrapper.

Root controls Agents.

Agent authority only narrows.

Events describe occurrences.

Tasks represent work.

Scheduler never performs side effects directly.

Working Memory is not Cognitive Memory.

Conversation History is not Long-Term Memory.

Sofias Memory owns persistent cognition.

Plugins extend existing contracts.

Trust is not Authority.

Audit explains consequential actions.
```

---

# 23. Architecture Gate decision

## Gate 2 — Architecture Definition

**Status recomendado: CONDITIONALLY PASSED**

Condição para fechamento definitivo:

```text
Apply amendments to:
ADR-0001
ADR-0004
ADR-0007
ADR-0009
ADR-0010
ADR-0015
```

Não é necessário reescrever esses ADRs inteiros.

Um **Architecture Review Amendment 0001** poderá registrar todas as correções e declarar que ele prevalece sobre os trechos conflitantes dos ADRs originais.

Depois disso:

```text
Gate 2 = CLOSED
```

---

# 24. Próxima etapa após fechamento

Com Gate 2 fechado, a sequência correta será:

```text
Architecture Gate
        ↓
Technical Backlog Map
        ↓
Epics + dependencies
        ↓
Implementation Gates
        ↓
Project Skeleton
```

Não há necessidade de nova rodada de Product Discovery ou novos ADRs antes disso.