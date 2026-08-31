# Sofia's Assistant — Coding & Testing Conventions Baseline

**Status:** Baseline proposta para implementação  
**Project:** Sofia's Assistant  
**Applies from:** SA-B001  
**Purpose:** estabelecer convenções mínimas de código, arquitetura, testes e qualidade antes da criação do skeleton

---

# 1. General Principle

O projeto seguirá a regra:

> **Clarity over cleverness. Explicit boundaries over implicit magic.**

Código deverá favorecer:

- legibilidade;
- previsibilidade;
- typing;
- testabilidade;
- separação de responsabilidades;
- baixo acoplamento.

Evitar abstrações prematuras.

---

# 2. Language

Código, nomes de:

- classes;
- funções;
- métodos;
- variáveis;
- arquivos;
- módulos;
- schemas;
- exceptions;

serão em **inglês**.

Documentação de produto e comunicação podem permanecer em **português do Brasil**.

---

# 3. Python Style

Seguir convenções Python modernas:

```text
snake_case       functions / variables / modules
PascalCase       classes / exceptions
UPPER_SNAKE_CASE constants
```

Preferir código idiomático Python sem excesso de metaprogramming.

---

# 4. Formatting and Linting

Baseline:

```text
ruff
```

como formatter/linter principal quando adequado.

Evitar múltiplas ferramentas com responsabilidades redundantes.

O formatter será authority de estilo.

Não discutir manualmente espaçamento que a ferramenta resolve.

---

# 5. Static Typing

Baseline:

```text
mypy
```

ou equivalente compatível com o projeto.

Contracts públicos deverão ser tipados.

Exemplo:

```python
def get_runtime_session(session_id: RuntimeSessionId) -> RuntimeSession:
    ...
```

Evitar:

```python
def get_session(data):
    ...
```

em boundaries relevantes.

---

# 6. Typing Strictness

Typing deverá ser progressivamente rigoroso.

Baseline:

- APIs internas importantes tipadas;
- public contracts tipados;
- repositories tipados;
- services tipados;
- DTOs/schemas tipados.

Não exigir anotações redundantes em todo detalhe trivial.

---

# 7. `Any`

`Any` será permitido apenas quando:

- library externa exigir;
- parsing inicial de payload desconhecido;
- boundary de interoperabilidade.

Deverá ser reduzido o mais cedo possível.

Não utilizar `Any` para fugir do type system.

---

# 8. Models and Contracts

Dados que cruzam boundaries deverão usar estruturas explícitas.

Preferir:

- dataclasses;
- typed schemas;
- validated models;

conforme necessidade.

Evitar dictionaries genéricos como contrato principal:

```python
dict[str, Any]
```

quando estrutura é conhecida.

---

# 9. Domain vs Transport Models

Modelos de domínio não deverão depender automaticamente de:

- HTTP;
- WebSocket;
- provider SDK;
- ORM response shape.

Exemplo:

```text
Client payload
    ↓
transport schema
    ↓
domain command
```

e não:

```text
HTTP schema = domain model = DB model
```

por conveniência.

---

# 10. Dependency Direction

Módulos de domínio não deverão depender de adapters externos.

Regra conceitual:

```text
Domain/Core
    ↑
Application Services
    ↑
Adapters/Infrastructure
```

Não será exigida arquitetura hexagonal cerimonial.

O objetivo é preservar dependency direction, não criar dezenas de interfaces sem necessidade.

---

# 11. Explicit Dependencies

Preferir constructor/function injection.

Exemplo:

```python
class RuntimeSessionService:
    def __init__(self, repository: RuntimeSessionRepository):
        self._repository = repository
```

Evitar globals como:

```python
DB = ...
CONFIG = ...
SECRET_STORE = ...
```

espalhados pelo código.

---

# 12. No Global Service Locator

Não criar padrão como:

```python
core.services.persistence
core.services.secrets
core.services.everything
```

disponível indiscriminadamente.

Dependências deverão ser fornecidas de forma controlada.

---

# 13. Modules

Cada módulo deverá representar responsabilidade coerente.

Evitar:

```text
utils.py
helpers.py
common.py
misc.py
```

como depósitos genéricos.

Se algo possui conceito próprio, deve possuir nome próprio.

---

# 14. Utility Functions

Função compartilhada só vira utility quando realmente não pertence a domínio específico.

Preferir:

```text
filesystem/path_resolution.py
```

a:

```text
utils.py
```

contendo path logic aleatória.

---

# 15. Functions

Funções devem ser pequenas o suficiente para serem compreendidas.

Não haverá limite artificial de número de linhas.

O critério será responsabilidade única e legibilidade.

---

# 16. Classes

Não criar classes apenas para transformar cada função em método.

Classes serão usadas quando existir:

- estado;
- lifecycle;
- contract;
- dependency grouping;
- polymorphism real.

---

# 17. Interfaces / Protocols

Criar abstração quando houver boundary arquitetural ou necessidade real de substituição.

Exemplos legítimos:

```text
SecretStore
MemoryProvider
AIProvider
ToolExecutor
```

Não criar interface para cada repository/service apenas por padrão.

---

# 18. Exceptions

Exceptions deverão representar erros semanticamente úteis.

Exemplos:

```text
ConfigurationError
PersistenceError
AuthenticationError
SecretStoreError
CompatibilityError
LifecycleError
```

Evitar lançar `Exception("something failed")` em boundaries importantes.

---

# 19. Exception Chaining

Preservar causa original quando fizer sentido:

```python
raise PersistenceError(...) from exc
```

Isso ajuda debugging sem expor detalhes indevidos ao client.

---

# 20. Public Errors

Internal exceptions não serão enviadas diretamente ao client.

Boundary deverá converter:

```text
internal error
↓
client-safe error
```

com:

- code;
- message;
- request_id.

---

# 21. Logging

Utilizar logging estruturado.

Nunca usar `print()` como logging permanente.

Campos de contexto poderão incluir:

```text
runtime_session_id
request_id
correlation_id
task_id
tool_call_id
```

quando disponíveis.

---

# 22. Logging and Secrets

Proibido logar:

- API keys;
- passwords;
- access tokens;
- refresh tokens;
- raw credentials.

Redaction deverá ser aplicada defensivamente.

---

# 23. Logging Payloads

Não logar bodies completos por padrão.

Especialmente:

- provider prompts;
- memory content;
- file content;
- external payloads.

Registrar metadata suficiente para debugging.

---

# 24. Async Rules

`async` será usado em I/O concorrente ou streaming.

Não transformar funções puramente computacionais em async.

Evitar:

```text
async everywhere
```

apenas porque o Core é assíncrono.

---

# 25. Blocking Operations

Operação bloqueante relevante não deverá bloquear event loop.

Executar em:

- async-native implementation;
- thread;
- subprocess;

conforme caso.

---

# 26. Cancellation

Código async de longa duração deverá considerar cancellation.

Não capturar `CancelledError` e ignorar silenciosamente.

---

# 27. Time

Persistir timestamps normalizados em UTC.

Utilizar timezone-aware datetime.

Evitar datetime naive em persisted/domain boundaries.

---

# 28. IDs

Entidades persistentes relevantes utilizarão identificadores estáveis independentes do SQLite ROWID.

Uma única estratégia será adotada no skeleton.

---

# 29. Configuration

Configuração deverá ser validada no boundary.

Evitar leitura de environment diretamente em módulos aleatórios:

```python
os.getenv(...)
```

espalhado pelo domínio.

Somente configuration layer deverá conhecer fontes concretas.

---

# 30. Secrets

Código não deverá receber secrets através de configuration object comum quando puder receber `secret_ref`.

Secret values devem existir somente no menor scope necessário.

---

# 31. Persistence

Services não executarão SQL diretamente como padrão.

Fluxo:

```text
Service
  ↓
Repository
  ↓
Persistence implementation
```

---

# 32. Repositories

Repository será orientado ao domínio.

Preferir:

```python
get_active_runtime_session(...)
mark_interrupted(...)
```

quando semanticamente útil.

Evitar repository genérico universal como:

```python
GenericRepository[T]
```

apenas para reduzir linhas.

---

# 33. Transactions

Transaction boundaries deverão estar explícitos.

Não depender de commits implícitos dispersos em repositories.

---

# 34. Migrations

Schema changes somente via migrations.

Nunca:

```text
if column missing:
    alter table dynamically
```

no runtime normal.

---

# 35. API Contracts

Client API deverá possuir schemas versionáveis.

Mudança incompatível não deverá ser introduzida silenciosamente.

---

# 36. Tests — General Rule

Testar comportamento e contracts.

Evitar testes que apenas reproduzem a implementação linha por linha.

---

# 37. Test Framework

Baseline:

```text
pytest
```

---

# 38. Test Categories

Estrutura:

```text
tests/
├── unit/
├── integration/
└── smoke/
```

`smoke/` poderá ser criado quando primeiro process-level test entrar.

---

# 39. Unit Tests

Unit test deverá:

- ser rápido;
- não depender de network real;
- não usar banco real do usuário;
- testar componente isoladamente quando isso trouxer valor.

---

# 40. Integration Tests

Integration tests deverão usar implementações reais do boundary testado.

Exemplos:

```text
SQLite temporário real
Local Client server real
Migration real
```

Mocks não substituem integration tests de contracts críticos.

---

# 41. Smoke Tests

Smoke tests validam fluxo de processo real.

No Gate I1:

```text
spawn Core
authenticate client
query health
disconnect
reconnect
shutdown
restart
```

---

# 42. External Services

Quando tests futuros dependerem de provider externo:

- unit tests usam fake;
- integration real deverá ser opt-in;
- não consumir API paga por default.

---

# 43. Fake Implementations

Fakes serão preferidos a mocks profundos para boundaries importantes.

Exemplos futuros:

```text
FakeAIProvider
FakeRealtimeProvider
FakeMemoryProvider
FakeTool
FakeEventSource
```

---

# 44. Mocking

Mocks serão usados para verificar colaboração local quando necessário.

Evitar mockar cinco níveis internos de uma mesma operação.

Isso normalmente indica design excessivamente acoplado.

---

# 45. Database Tests

Cada integration test deverá usar banco isolado.

Nunca apontar para Operational Store real.

---

# 46. Test Determinism

Tests deverão ser determinísticos.

Evitar:

```python
sleep(5)
```

para esperar condição arbitrária.

Preferir:

- event synchronization;
- fake clock;
- explicit readiness;
- polling limitado com condição objetiva.

---

# 47. Test Naming

Nome do teste deverá comunicar comportamento.

Exemplo:

```python
def test_core_remains_running_after_client_disconnect():
```

em vez de:

```python
def test_core_2():
```

---

# 48. Arrange / Act / Assert

Tests poderão seguir mentalmente:

```text
Arrange
Act
Assert
```

Não é necessário adicionar comentários AAA em todo teste.

---

# 49. Regression Tests

Todo bug significativo corrigido deverá, quando viável, ganhar teste que falhava antes da correção.

---

# 50. Failure-path Testing

Happy path sozinho não é suficiente.

Cada Epic deverá considerar seus principais failure modes.

Especialmente:

- startup;
- persistence;
- authentication;
- authorization;
- external effects;
- recovery.

---

# 51. Coverage

Coverage será indicador, não meta artificial.

Não perseguir 100% sacrificando qualidade.

O objetivo será cobertura alta nas áreas críticas.

---

# 52. Critical Paths

Boundaries como:

- Policy;
- Grants;
- Tool Runtime;
- recovery;
- migrations;
- authentication;
- secrets;

deverão possuir cobertura especialmente forte.

---

# 53. No Test-only Production Logic

Não adicionar branches como:

```python
if TESTING:
    bypass_authentication()
```

em production paths.

Utilizar dependency substitution adequada.

---

# 54. Security Tests

Toda capability com security boundary deverá possuir adversarial tests.

Exemplos futuros:

- unauthenticated client;
- path traversal;
- secret leakage;
- authority escalation;
- sandbox downgrade.

---

# 55. Quality Gate Per Commit/PR

Antes de considerar mudança pronta:

```text
format
lint
typecheck
tests
```

devem passar.

---

# 56. No Ignored Failures

Não usar permanentemente:

```text
|| true
```

ou equivalente para esconder failure de quality gate.

---

# 57. Type Ignore

`# type: ignore` deverá ser específico e justificado quando necessário.

Evitar ignores globais.

---

# 58. Lint Ignore

Mesmo princípio:

- específico;
- local;
- justificável.

Não desligar regra global apenas porque um trecho incomoda.

---

# 59. TODO Policy

TODO permitido para trabalho realmente deferred.

Formato deverá explicar motivo.

Não usar TODO para requisito obrigatório da issue atual.

Um Epic não fecha com TODO que representa Acceptance Criterion não implementado.

---

# 60. Comments

Comentários devem explicar **por quê**, não repetir o código.

Evitar:

```python
# Increment counter
counter += 1
```

Preferir explicar invariant ou workaround quando necessário.

---

# 61. Docstrings

Docstrings obrigatórias quando contract/comportamento não for óbvio.

Não exigir docstring inútil em toda função trivial privada.

---

# 62. Architecture Documentation

Mudança que altera architectural invariant exige:

- ADR;
- amendment;
- ou revisão explícita.

Não esconder decisão estrutural em comentário de código.

---

# 63. Backlog Traceability

Commits e PRs deverão poder ser relacionados aos Epics:

```text
SA-B001
SA-B002
...
```

Não é necessário colocar ID em todo commit se contexto do branch/PR já for suficiente.

---

# 64. Git Commit Style

Preferir Conventional Commits ou formato equivalente:

```text
feat(core): add runtime lifecycle
fix(storage): recover interrupted session
test(api): cover invalid local credential
chore(project): configure ruff
```

---

# 65. Commit Principle

Commit deverá representar unidade coerente.

Evitar:

```text
"updates"
"changes"
"stuff"
```

---

# 66. Generated Code

Código produzido por AI passa pelas mesmas regras:

- review;
- lint;
- typing;
- tests.

AI-generated não é sinônimo de accepted.

---

# 67. No Blind Refactor

Não refatorar área estável apenas porque há preferência estilística diferente durante Epic não relacionado.

Mudanças devem possuir propósito.

---

# 68. Backward Compatibility

Antes do primeiro release público, migrations/interfaces poderão evoluir mais livremente.

Mesmo assim, mudanças devem continuar explícitas e versionadas.

---

# 69. Platform-specific Code

Windows-specific implementation deverá ficar atrás de boundary quando houver possibilidade real de portabilidade futura.

Exemplo:

```text
secrets/
    interface
    windows_backend
```

Não construir camada abstrata para sistemas operacionais ainda inexistentes sem necessidade.

---

# 70. Defensive Programming

Validar inputs em boundaries.

Não repetir validações em toda camada sem motivo.

---

# 71. Assertions

`assert` poderá ser usado para programmer invariants.

Não utilizar `assert` como validação de input externo/security boundary.

---

# 72. Fail Closed

Security boundaries seguem:

> ambiguity or failure does not increase authority.

Isso valerá futuramente para:

- Policy;
- authentication;
- SecretStore;
- sandbox;
- plugins.

---

# 73. Performance

Não otimizar prematuramente.

Mas evitar designs obviamente ruins como:

- carregar Conversation inteira sempre;
- abrir connection nova sem controle para cada operação;
- guardar blobs enormes no SQLite sem necessidade.

---

# 74. Observability

Código relevante deverá permitir diagnosis sem exigir debugger.

Isso significa:

- structured errors;
- useful logs;
- IDs;
- health.

Não significa logging excessivo.

---

# 75. First Slice Specific Rules

Durante SA-B001…SA-B006:

- nenhum LLM SDK;
- nenhum Agent framework;
- nenhum LangChain-like abstraction;
- nenhum vector database;
- nenhum plugin framework;
- nenhuma UI desktop.

Dependências só entram quando justificadas pelo slice atual.

---

# 76. Architecture Enforcement

Durante implementação, toda mudança deverá passar mentalmente por três perguntas:

```text
Does this violate the PRD?

Does this violate an ADR/invariant?

Is this complexity required now?
```

Se resposta da terceira for "não":

não implementar ainda.

---

# 77. Definition of Ready for a Technical Task

Uma task de implementação deverá possuir:

- objetivo claro;
- scope;
- acceptance criterion;
- dependency conhecida;
- architectural constraints relevantes.

Não precisamos de especificação burocrática para alteração trivial.

---

# 78. Definition of Done

Código estará Done quando:

```text
implementation complete
+
tests pass
+
lint passes
+
typecheck passes
+
acceptance criteria pass
+
no known architecture violation
```

---

# 79. Gate 4 Assessment

Após esta baseline, temos:

```text
PRD approved
Architecture Gate CLOSED
Technical Backlog Map approved
Slice 01 detailed
Coding conventions defined
Testing conventions defined
```

Portanto, do ponto de vista de definição:

**Gate 4 — Implementation Readiness está pronto para fechamento.**

O único passo restante é autorização explícita para iniciar a implementação.

---

# 80. Final Baseline

Sofia's Assistant será desenvolvido com:

```text
Python moderno e tipado
modular monolith
explicit dependencies
validated boundaries
SQLite migrations
structured logging
pytest
real integration tests
process-level smoke tests
security-oriented failure testing
progressive vertical slices
```

A prioridade será sempre:

```text
correctness
↓
clarity
↓
security
↓
testability
↓
performance
↓
cleverness
```