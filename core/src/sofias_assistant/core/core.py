"""Lifecycle owner for Sofia's Assistant foundation resources."""

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from sofias_assistant.ai_config.service import AIConfigurationService
from sofias_assistant.capabilities.registration import register_builtin_capabilities
from sofias_assistant.config.models import RuntimeConfig
from sofias_assistant.conversation.coordination import ConversationActivityCoordinator
from sofias_assistant.conversation.realtime_runtime import RealtimeConversationRuntime
from sofias_assistant.conversation.runtime import TextConversationRuntime
from sofias_assistant.core.composition import (
    ConversationDependenciesFactory,
    ConversationRuntimeDependencies,
    MemoryProviderFactory,
)
from sofias_assistant.execution import AgentRuntime, ExecutionRuntime, TaskRuntime
from sofias_assistant.health.models import (
    ComponentHealth,
    HealthStatus,
    RuntimeHealthSnapshot,
)
from sofias_assistant.memory.adapter import SofiasMemoryAdapter
from sofias_assistant.memory.contracts import MemoryProvider
from sofias_assistant.memory.extraction import PassthroughMemoryCandidateExtractor
from sofias_assistant.memory.models import MemoryInvocationError
from sofias_assistant.memory.orchestrator import MemoryOrchestrator
from sofias_assistant.memory.policy import MemoryPolicy
from sofias_assistant.memory.store import MemoryStore
from sofias_assistant.persistence.unit_of_work import SqlAlchemyUnitOfWork
from sofias_assistant.proactivity.models import Clock
from sofias_assistant.proactivity.runtime import ProactivityRuntime
from sofias_assistant.runtime.bootstrap import RuntimeResources, bootstrap_runtime
from sofias_assistant.runtime.instance_ownership import (
    CoreInstanceOwnership,
    InstanceOwnership,
)
from sofias_assistant.runtime.recovery import StartupRecoveryCoordinator
from sofias_assistant.runtime.session_lifecycle import RuntimeSessionLifecycle
from sofias_assistant.secrets.models import SecretRef
from sofias_assistant.secrets.service import SecretService
from sofias_assistant.secrets.store import SecretStore
from sofias_assistant.secrets.windows_store import WindowsCredentialStore


class CoreState(StrEnum):
    """Lifecycle state of the SofiaCore composition owner."""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class SofiaCore:
    """Compose and own the foundation resources for one Core lifecycle."""

    def __init__(
        self,
        config: RuntimeConfig,
        *,
        application_version: str,
        secret_store_factory: Callable[[], SecretStore] = WindowsCredentialStore,
        instance_ownership_factory: Callable[
            [Path], InstanceOwnership
        ] = CoreInstanceOwnership,
        conversation_dependencies_factory: ConversationDependenciesFactory
        | None = None,
        memory_provider_factory: MemoryProviderFactory | None = None,
        clock: Clock | None = None,
    ) -> None:
        if not application_version.strip():
            raise ValueError("Application version must not be blank")
        if conversation_dependencies_factory is not None and not callable(
            conversation_dependencies_factory
        ):
            raise ValueError("conversation_dependencies_factory must be callable")

        self._config = config
        self._application_version = application_version
        self._secret_store_factory = secret_store_factory
        self._instance_ownership_factory = instance_ownership_factory
        self._conversation_dependencies_factory = conversation_dependencies_factory
        self._memory_provider_factory = memory_provider_factory
        self._memory_orchestrator: MemoryOrchestrator | None = None
        self._state = CoreState.CREATED
        self._resources: RuntimeResources | None = None
        self._session_lifecycle: RuntimeSessionLifecycle | None = None
        self._secret_service: SecretService | None = None
        self._execution_runtime: ExecutionRuntime | None = None
        self._task_runtime: TaskRuntime | None = None
        self._agent_runtime: AgentRuntime | None = None
        self._instance_ownership: InstanceOwnership | None = None
        self._instance_ownership_acquired = False
        self._conversation_runtime: TextConversationRuntime | None = None
        self._realtime_conversation_runtime: RealtimeConversationRuntime | None = None
        self._conversation_activity_coordinator: (
            ConversationActivityCoordinator | None
        ) = None
        self._health = RuntimeHealthSnapshot(())
        self._clock = clock
        self._proactivity: ProactivityRuntime | None = None
        self._ai_configuration_service: AIConfigurationService | None = None

    @property
    def state(self) -> CoreState:
        """Return the current Core lifecycle state."""

        return self._state

    @property
    def runtime_session_id(self) -> UUID | None:
        """Return the current persisted runtime session identity, when active."""

        if self._session_lifecycle is None:
            return None
        return self._session_lifecycle.active_session_id

    @property
    def health(self) -> RuntimeHealthSnapshot:
        """Return the current transport-neutral foundation health snapshot."""

        components = self._proactivity.health if self._proactivity is not None else ()
        names = {component.name for component in components}
        return RuntimeHealthSnapshot(
            tuple(
                component
                for component in self._health.components
                if component.name not in names
            )
            + components
        )

    @property
    def proactivity(self) -> ProactivityRuntime:
        if self._state is not CoreState.RUNNING or self._proactivity is None:
            raise RuntimeError("Proactivity is only available while Core is running")
        return self._proactivity

    async def update_health(self, component: ComponentHealth) -> None:
        """Accept an explicit subsystem observation and project significant transitions."""
        await self.proactivity.notifications.observe_health(component)
        self._health = RuntimeHealthSnapshot(
            tuple(
                value
                for value in self._health.components
                if value.name != component.name
            )
            + (component,)
        )

    @property
    def secret_service(self) -> SecretService:
        """Return the composed SecretService only while the Core is running."""

        if self._state is not CoreState.RUNNING or self._secret_service is None:
            raise RuntimeError(
                "SecretService is only available while SofiaCore is running"
            )
        return self._secret_service

    @property
    def execution_runtime(self) -> ExecutionRuntime:
        """Return Core-owned authorized Tool execution while the Core is running."""

        if self._state is not CoreState.RUNNING or self._execution_runtime is None:
            raise RuntimeError(
                "Execution Runtime is only available while SofiaCore is running"
            )
        return self._execution_runtime

    @property
    def task_runtime(self) -> TaskRuntime:
        """Return Core-owned durable Task execution while running."""

        if self._state is not CoreState.RUNNING or self._task_runtime is None:
            raise RuntimeError(
                "Task Runtime is only available while SofiaCore is running"
            )
        return self._task_runtime

    @property
    def agent_runtime(self) -> AgentRuntime:
        """Return Core-owned root Agent runtime while running."""

        if self._state is not CoreState.RUNNING or self._agent_runtime is None:
            raise RuntimeError(
                "Agent Runtime is only available while SofiaCore is running"
            )
        return self._agent_runtime

    @property
    def conversation_runtime(self) -> TextConversationRuntime:
        """Return the Core-owned conversation runtime while it is configured and running."""

        if self._state is not CoreState.RUNNING:
            raise RuntimeError(
                "Conversation Runtime is only available while SofiaCore is running"
            )
        if self._conversation_runtime is None:
            raise RuntimeError("Conversation Runtime is not configured")
        return self._conversation_runtime

    @property
    def memory_orchestrator(self) -> MemoryOrchestrator | None:
        """Return the composed MemoryOrchestrator, or None when disabled."""

        if self._state is not CoreState.RUNNING:
            raise RuntimeError(
                "Memory Orchestrator is only available while SofiaCore is running"
            )
        return self._memory_orchestrator

    @property
    def ai_configuration_service(self) -> AIConfigurationService | None:
        """Return the composed AI Configuration Service, or None when absent."""

        if self._state is not CoreState.RUNNING:
            raise RuntimeError(
                "AI Configuration Service is only available while SofiaCore is running"
            )
        return self._ai_configuration_service

    @property
    def realtime_conversation_runtime(self) -> RealtimeConversationRuntime:
        """Return the composed realtime runtime only while SofiaCore is running."""

        if self._state is not CoreState.RUNNING:
            raise RuntimeError(
                "Realtime Conversation Runtime is only available while SofiaCore is running"
            )
        if self._realtime_conversation_runtime is None:
            raise RuntimeError("Realtime Conversation Runtime is not configured")
        return self._realtime_conversation_runtime

    async def start(self) -> None:
        """Compose foundation resources and persist the current runtime session."""

        if self._state is not CoreState.CREATED:
            raise RuntimeError("SofiaCore can only start from the created state")

        self._state = CoreState.STARTING
        try:
            self._instance_ownership = self._instance_ownership_factory(
                self._config.paths.data_dir
            )
            self._instance_ownership.acquire()
            self._instance_ownership_acquired = True
            self._secret_service = SecretService(self._secret_store_factory())
            self._resources = await bootstrap_runtime(self._config)
            self._session_lifecycle = RuntimeSessionLifecycle(
                self._resources.session_factory,
                application_version=self._application_version,
            )
            await self._session_lifecycle.start()
            self._execution_runtime = ExecutionRuntime(
                self._resources.session_factory,
                artifact_root=self._config.paths.data_dir / "artifacts",
            )
            register_builtin_capabilities(self._execution_runtime)
            self._task_runtime = TaskRuntime(
                self._execution_runtime,
                owner=f"runtime:{self._session_lifecycle.active_session_id}",
            )
            self._agent_runtime = AgentRuntime(self._execution_runtime)
            memory_health = await self._compose_memory_orchestrator()
            await self._compose_conversation_runtime()
            self._proactivity = ProactivityRuntime(
                self._resources.session_factory,
                self._execution_runtime.audit,
                self._clock,
            )
            # Bind the Scheduler onto TaskRuntime before recovery runs, so
            # general recovery can see which stale Tasks belong to the
            # specialized Scheduler recovery path (Gate I12 Finding 2) —
            # bind_tasks() only wires the reference, it starts no Event or
            # Scheduler processing yet.
            self._proactivity.bind_tasks(self._task_runtime)
            # Gate I12: reconcile stale durable work from a lost runtime
            # session before Scheduler/Event processing may act on it again.
            recovery = await StartupRecoveryCoordinator(
                task_runtime=self._task_runtime,
                memory_orchestrator=self._memory_orchestrator,
                audit=self._execution_runtime.audit,
                runtime_session_id=self._session_lifecycle.active_session_id,
            ).run()
            await self._proactivity.start()
            self._health = RuntimeHealthSnapshot(
                (
                    ComponentHealth("operational-store", HealthStatus.HEALTHY),
                    ComponentHealth(
                        "secret-store",
                        HealthStatus.UNKNOWN,
                        "Backend configured; no active probe performed",
                    ),
                    memory_health,
                    recovery.health,
                )
            )
            self._state = CoreState.RUNNING
        except BaseException:
            self._state = CoreState.FAILED
            await self._cleanup_failed_start()
            raise

    async def stop(self) -> None:
        """Stop the current runtime session and release owned resources."""

        if self._state is not CoreState.RUNNING:
            raise RuntimeError("SofiaCore can only stop from the running state")

        resources = self._resources
        lifecycle = self._session_lifecycle
        if resources is None or lifecycle is None:
            self._state = CoreState.FAILED
            await self._release_ownership_best_effort()
            self._clear_owned_references()
            raise RuntimeError("SofiaCore running state is missing owned resources")

        self._state = CoreState.STOPPING
        primary_error: BaseException | None = None
        if self._proactivity is not None:
            try:
                await self._proactivity.stop()
            except BaseException as error:
                primary_error = error
        realtime_runtime = self._realtime_conversation_runtime
        if realtime_runtime is not None:
            try:
                await realtime_runtime.close_all()
            except BaseException as error:
                primary_error = error
        if self._agent_runtime is not None:
            try:
                await self._agent_runtime.stop()
            except BaseException as error:
                primary_error = primary_error or error
        if self._task_runtime is not None:
            try:
                await self._task_runtime.stop()
            except BaseException as error:
                primary_error = primary_error or error
        try:
            await lifecycle.stop()
        except BaseException as error:
            primary_error = error
        try:
            await resources.close()
        except BaseException as error:
            if primary_error is None:
                primary_error = error
        ownership_error: BaseException | None = None
        try:
            self._release_ownership()
        except BaseException as error:
            ownership_error = error
        self._clear_owned_references()
        if primary_error is not None:
            self._state = CoreState.FAILED
            raise primary_error
        if ownership_error is not None:
            self._state = CoreState.FAILED
            raise ownership_error
        self._state = CoreState.STOPPED

    async def _cleanup_failed_start(self) -> None:
        lifecycle = self._session_lifecycle
        resources = self._resources

        if self._proactivity is not None:
            try:
                await self._proactivity.stop()
            except BaseException:
                pass

        if lifecycle is not None and lifecycle.active_session_id is not None:
            try:
                await lifecycle.stop()
            except BaseException:
                pass
        if resources is not None:
            try:
                await resources.close()
            except BaseException:
                pass
        await self._release_ownership_best_effort()
        self._clear_owned_references()

    def _release_ownership(self) -> None:
        ownership = self._instance_ownership
        if ownership is not None and self._instance_ownership_acquired:
            try:
                ownership.release()
            finally:
                self._instance_ownership_acquired = False

    async def _release_ownership_best_effort(self) -> None:
        try:
            self._release_ownership()
        except BaseException:
            pass

    def _clear_owned_references(self) -> None:
        self._proactivity = None
        self._conversation_runtime = None
        self._realtime_conversation_runtime = None
        self._conversation_activity_coordinator = None
        self._ai_configuration_service = None
        self._memory_orchestrator = None
        self._resources = None
        self._session_lifecycle = None
        self._secret_service = None
        self._execution_runtime = None
        self._task_runtime = None
        self._agent_runtime = None
        self._instance_ownership = None
        self._instance_ownership_acquired = False
        self._health = RuntimeHealthSnapshot(())

    async def _compose_memory_orchestrator(self) -> ComponentHealth:
        """Compose Cognitive Memory when configured; fail closed on incompatibility.

        Memory is never a hard startup dependency: any failure here disables
        only the Memory subsystem and is reflected as DEGRADED health.
        """

        resources = self._resources
        secret_service = self._secret_service
        execution_runtime = self._execution_runtime
        if resources is None or secret_service is None or execution_runtime is None:
            raise RuntimeError("SofiaCore is missing composition resources")
        memory_config = self._config.memory
        if not memory_config.enabled or memory_config.base_url is None:
            self._memory_orchestrator = None
            return ComponentHealth(
                "sofias-memory", HealthStatus.UNKNOWN, "Memory is not configured"
            )
        provider: MemoryProvider = (
            self._memory_provider_factory(secret_service)
            if self._memory_provider_factory is not None
            else SofiasMemoryAdapter(
                base_url=memory_config.base_url,
                secret_service=secret_service,
                api_key_ref=SecretRef("integrations/sofias-memory/api-key"),
                timeout_seconds=memory_config.timeout_seconds,
            )
        )
        orchestrator = MemoryOrchestrator(
            store=MemoryStore(resources.session_factory),
            provider=provider,
            policy=MemoryPolicy(),
            extractor=PassthroughMemoryCandidateExtractor(),
            audit=execution_runtime.audit,
            uow_factory=lambda: SqlAlchemyUnitOfWork(resources.session_factory),
            recall_top_k=memory_config.recall_limit,
        )
        try:
            capabilities = await orchestrator.probe()
        except MemoryInvocationError as error:
            self._memory_orchestrator = None
            return ComponentHealth(
                "sofias-memory", HealthStatus.DEGRADED, error.error.safe_message
            )
        if not capabilities.supports_cognitive_memory:
            self._memory_orchestrator = None
            return ComponentHealth(
                "sofias-memory",
                HealthStatus.DEGRADED,
                "Memory contract is incompatible with required capabilities",
            )
        self._memory_orchestrator = orchestrator
        return ComponentHealth("sofias-memory", HealthStatus.HEALTHY)

    async def _compose_conversation_runtime(self) -> None:
        factory = self._conversation_dependencies_factory
        if factory is None:
            return

        secret_service = self._secret_service
        resources = self._resources
        execution_runtime = self._execution_runtime
        if secret_service is None or resources is None:
            raise RuntimeError("SofiaCore is missing composition resources")
        dependencies = factory(
            secret_service, lambda: SqlAlchemyUnitOfWork(resources.session_factory)
        )
        if not isinstance(dependencies, ConversationRuntimeDependencies):
            raise ValueError(
                "conversation_dependencies_factory must return "
                "ConversationRuntimeDependencies"
            )
        self._ai_configuration_service = dependencies.ai_configuration_service
        audit = execution_runtime.audit if execution_runtime is not None else None

        self._conversation_activity_coordinator = ConversationActivityCoordinator()
        self._conversation_runtime = TextConversationRuntime(
            uow_factory=lambda: SqlAlchemyUnitOfWork(resources.session_factory),
            router=dependencies.router,
            context_builder=dependencies.context_builder,
            activity_coordinator=self._conversation_activity_coordinator,
            memory_orchestrator=self._memory_orchestrator,
            audit=audit,
        )
        self._realtime_conversation_runtime = RealtimeConversationRuntime(
            uow_factory=lambda: SqlAlchemyUnitOfWork(resources.session_factory),
            router=dependencies.realtime_router or dependencies.router,
            context_builder=dependencies.context_builder,
            activity_coordinator=self._conversation_activity_coordinator,
            audit=audit,
        )
        if dependencies.ai_configuration_service is not None:
            if dependencies.ai_configuration_bootstrap is not None:
                await dependencies.ai_configuration_service.bootstrap(
                    dependencies.ai_configuration_bootstrap
                )
            else:
                await dependencies.ai_configuration_service.initialize()
