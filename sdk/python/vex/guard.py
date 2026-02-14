"""Vex client -- the main developer-facing API for agent reliability.

Provides three integration patterns:

1. ``watch`` decorator -- wraps a function, captures input/output/latency,
   and sends telemetry (async mode) or performs inline verification (sync mode).

2. ``trace`` context manager -- gives fine-grained control over recording
   intermediate steps, ground truth, and schema information.

3. ``run`` explicit wrapper -- a framework-agnostic escape hatch that accepts
   a callable and optional metadata.
"""

import asyncio
import functools
import logging
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Dict, Generator, List, Optional

from vex.config import VexConfig
from vex.exceptions import VexBlockError, ConfigurationError
from vex.models import ConversationTurn, ExecutionEvent, VexResult, StepRecord
from vex.transport import AsyncTransport, SyncTransport

logger = logging.getLogger(__name__)


class Session:
    """Groups multiple trace executions into a logical session.

    **Thread Safety:** Session instances are NOT thread-safe. Do not call
    ``trace()`` concurrently from multiple threads on the same Session
    instance. Create separate Session instances per thread if needed.

    Automatically assigns a shared session_id and auto-incrementing
    sequence_number to each trace created through this session.

    Usage::

        session = vex.session(agent_id="chat-bot")
        with session.trace(task="turn 1", input_data=msg) as ctx:
            ctx.record(response)
        # session.sequence is now 1
    """

    def __init__(
        self,
        guard: "Vex",
        agent_id: str,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._guard = guard
        self._agent_id = agent_id
        self.session_id: str = session_id or str(uuid.uuid4())
        self._metadata: Dict[str, Any] = metadata or {}
        self._sequence: int = 0
        self._lock = threading.Lock()
        self._history: List[ConversationTurn] = []
        self._window_size: int = guard.config.conversation_window_size

    @property
    def sequence(self) -> int:
        """Current sequence number (incremented after each trace)."""
        return self._sequence

    @contextmanager
    def trace(
        self,
        task: Optional[str] = None,
        input_data: Any = None,
        parent_execution_id: Optional[str] = None,
    ) -> Generator["TraceContext", None, None]:
        """Create a traced execution within this session.

        Automatically injects session_id, sequence_number, and a snapshot
        of the conversation history (excluding the current turn).
        Thread-safe: sequence/history access is protected by a lock.
        """
        with self._lock:
            seq = self._sequence
            # Snapshot history BEFORE this turn (excludes current turn)
            history_snapshot: Optional[List[ConversationTurn]] = (
                list(self._history[-self._window_size:]) if self._history else None
            )
        ctx = TraceContext(
            guard=self._guard,
            agent_id=self._agent_id,
            task=task,
            input_data=input_data,
            session_id=self.session_id,
            sequence_number=seq,
            parent_execution_id=parent_execution_id,
            conversation_history=history_snapshot,
        )
        # Merge session-level metadata (trace-level overrides take precedence)
        for key, value in self._metadata.items():
            if key not in ctx._metadata:
                ctx._metadata[key] = value
        yield ctx
        ctx._finalise()
        with self._lock:
            self._sequence += 1
            self._history.append(ConversationTurn(
                sequence_number=seq,
                input=input_data,
                output=ctx._output,
                task=task,
            ))
            if len(self._history) > self._window_size:
                self._history = self._history[-self._window_size:]


class TraceContext:
    """Accumulates execution data within a ``vex.trace()`` context manager.

    Records intermediate steps, ground truth, schema, and the final output.
    On context exit, builds an :class:`ExecutionEvent` and sends it through
    the Vex processing pipeline.

    Parameters
    ----------
    guard:
        The parent :class:`Vex` instance.
    agent_id:
        Identifier for the agent being traced.
    task:
        Optional human-readable task description.
    input_data:
        The input that triggered the trace (captured from context arguments).
    """

    def __init__(
        self,
        guard: "Vex",
        agent_id: str,
        task: Optional[str] = None,
        input_data: Any = None,
        session_id: Optional[str] = None,
        sequence_number: Optional[int] = None,
        parent_execution_id: Optional[str] = None,
        conversation_history: Optional[List[ConversationTurn]] = None,
    ) -> None:
        self._guard = guard
        self._agent_id = agent_id
        self._task = task
        self._input_data = input_data
        self._output: Any = None
        self._ground_truth: Any = None
        self._schema: Optional[Dict[str, Any]] = None
        self._steps: List[StepRecord] = []
        self._start_time: float = time.monotonic()
        self._metadata: Dict[str, Any] = {}
        self._token_count: Optional[int] = None
        self._cost_estimate: Optional[float] = None
        self._session_id = session_id
        self._sequence_number = sequence_number
        self._parent_execution_id = parent_execution_id
        self._conversation_history = conversation_history
        self.result: Optional[VexResult] = None

    def set_ground_truth(self, data: Any) -> None:
        """Set the ground truth reference data for verification."""
        self._ground_truth = data

    def set_schema(self, schema: Dict[str, Any]) -> None:
        """Set the expected output schema for validation."""
        self._schema = schema

    def set_token_count(self, count: int) -> None:
        """Set the total token count for this execution."""
        self._token_count = count

    def set_cost_estimate(self, cost: float) -> None:
        """Set the estimated cost for this execution."""
        self._cost_estimate = cost

    def set_metadata(self, key: str, value: Any) -> None:
        """Set a custom metadata key-value pair for this execution."""
        self._metadata[key] = value

    def step(
        self,
        step_type: str,
        name: str,
        input: Any = None,
        output: Any = None,
        duration_ms: Optional[float] = None,
    ) -> None:
        """Record an intermediate step in the execution trace.

        Parameters
        ----------
        step_type:
            Category of the step (e.g. ``"tool_call"``, ``"llm"``, ``"custom"``).
        name:
            Human-readable name for the step.
        input:
            Input data for the step.
        output:
            Output data from the step.
        duration_ms:
            Wall-clock duration of the step in milliseconds.
        """
        self._steps.append(
            StepRecord(
                step_type=step_type,
                name=name,
                input=input,
                output=output,
                duration_ms=duration_ms,
            )
        )

    def record(self, output: Any) -> None:
        """Record the final output of the traced execution."""
        self._output = output

    def _finalise(self) -> None:
        """Build the execution event and process it through the Vex client."""
        elapsed_ms = (time.monotonic() - self._start_time) * 1000.0

        event = ExecutionEvent(
            agent_id=self._agent_id,
            session_id=self._session_id,
            parent_execution_id=self._parent_execution_id,
            sequence_number=self._sequence_number,
            task=self._task,
            input=self._input_data,
            output=self._output,
            steps=self._steps,
            token_count=self._token_count,
            cost_estimate=self._cost_estimate,
            latency_ms=elapsed_ms,
            ground_truth=self._ground_truth,
            schema_definition=self._schema,
            conversation_history=self._conversation_history,
            metadata=self._metadata,
        )

        self.result = self._guard._process_event(event)


class Vex:
    """The main Vex client for agent reliability and observability.

    Supports two operational modes:

    - **async** (default): Events are buffered and flushed in batches to the
      Ingestion API.  ``watch``/``run``/``trace`` return immediately with a
      pass-through :class:`VexResult`.

    - **sync**: Each event is sent to the Sync Verification Gateway for inline
      verification.  The returned :class:`VexResult` contains the server's
      confidence score and action recommendation.

    Parameters
    ----------
    api_key:
        API key for authenticating with Vex backend services.
    config:
        Optional configuration object.  Defaults to async mode with standard
        thresholds.
    """

    def __init__(
        self,
        api_key: str,
        config: Optional[VexConfig] = None,
    ) -> None:
        # Validate API key
        if not api_key or not api_key.strip():
            raise ConfigurationError("API key cannot be empty")
        api_key = api_key.strip()
        if len(api_key) < 10:
            raise ConfigurationError("API key appears invalid (too short)")
        self.api_key = api_key
        self.config = config or VexConfig()

        # Always create async transport for telemetry
        self._async_transport = AsyncTransport(
            api_url=self.config.api_url,
            api_key=self.api_key,
            flush_interval_s=self.config.flush_interval_s,
            flush_batch_size=self.config.flush_batch_size,
            timeout_s=self.config.timeout_s,
            max_buffer_size=self.config.max_buffer_size,
        )

        # Create sync transport only when needed for inline verification
        self._sync_transport: Optional[SyncTransport] = None
        if self.config.mode == "sync":
            self._sync_transport = SyncTransport(
                api_url=self.config.api_url,
                api_key=self.api_key,
                timeout_s=self.config.timeout_s,
                correction_timeout_s=self.config.timeout_s * 3,
            )

        # Background flush thread
        self._flush_stop = threading.Event()
        self._flush_thread = threading.Thread(
            target=self._flush_loop,
            daemon=True,
            name="vex-flush",
        )
        self._flush_thread.start()
        self._closed = False

    # ------------------------------------------------------------------
    # Background flush loop
    # ------------------------------------------------------------------

    def _flush_loop(self) -> None:
        """Periodically flush buffered events on a background thread.

        Creates its own event loop to avoid conflicting with any loop
        running on the main thread (e.g. FastAPI, asyncio applications).
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            while not self._flush_stop.is_set():
                self._flush_stop.wait(timeout=self.config.flush_interval_s)
                if not self._flush_stop.is_set():
                    try:
                        loop.run_until_complete(self._async_transport.flush())
                    except Exception:
                        logger.warning("Background flush failed", exc_info=True)
        finally:
            try:
                loop.run_until_complete(self._async_transport.close())
            except Exception:
                logger.warning("Error during final async transport close", exc_info=True)
            finally:
                loop.close()

    # ------------------------------------------------------------------
    # Internal event processing
    # ------------------------------------------------------------------

    def _process_event(self, event: ExecutionEvent) -> VexResult:
        """Process an execution event according to the configured mode.

        In sync mode, sends the event to the Verification Gateway for inline
        verification and returns the server's response as a VexResult.
        If the verification call fails, logs a warning and returns a
        pass-through result.

        In async mode, enqueues the event for batched delivery and returns
        a pass-through VexResult immediately.
        """
        if self.config.mode == "sync" and self._sync_transport is not None:
            try:
                response = self._sync_transport.verify(
                    event,
                    thresholds=self.config.confidence_threshold,
                    correction=self.config.correction,
                    transparency=self.config.transparency,
                )
                result = VexResult(
                    output=response.get("output", event.output),
                    confidence=response.get("confidence"),
                    action=response.get("action", "pass"),
                    corrections=response.get("correction_attempts"),
                    execution_id=response.get("execution_id", event.execution_id),
                    verification=response.get("checks"),
                    corrected=response.get("corrected", False),
                    original_output=response.get("original_output"),
                )

                if result.action == "block":
                    raise VexBlockError(result)

                if result.action == "flag":
                    if self.config.log_event_ids:
                        logger.warning(
                            "Agent output flagged for event %s (confidence=%s)",
                            event.execution_id,
                            result.confidence,
                        )
                    else:
                        logger.warning(
                            "Agent output flagged (confidence=%s)",
                            result.confidence,
                        )

                return result
            except VexBlockError:
                raise
            except Exception:
                if self.config.log_event_ids:
                    logger.warning(
                        "Sync verification failed for event %s; returning pass-through result",
                        event.execution_id,
                        exc_info=True,
                    )
                else:
                    logger.warning(
                        "Sync verification failed; returning pass-through result",
                        exc_info=True,
                    )
                return VexResult(
                    output=event.output,
                    action="pass",
                    execution_id=event.execution_id,
                )

        # Async mode: enqueue and return pass-through
        self._async_transport.enqueue(event)
        return VexResult(
            output=event.output,
            action="pass",
            execution_id=event.execution_id,
        )

    # ------------------------------------------------------------------
    # Public API: watch decorator
    # ------------------------------------------------------------------

    def watch(
        self,
        agent_id: str,
        task: Optional[str] = None,
    ) -> Callable:
        """Decorator that wraps a function with Vex telemetry.

        Usage::

            @vex.watch(agent_id="support-bot", task="Answer billing questions")
            def handle_support(query: str) -> str:
                return my_agent.run(query)

            result = handle_support("billing question")
            # result is a VexResult with output, confidence, action, execution_id

        Parameters
        ----------
        agent_id:
            Identifier for the agent being monitored.
        task:
            Optional human-readable description of the agent's task.

        Returns
        -------
        Callable
            A decorator that wraps the target function.
        """

        def decorator(fn: Callable) -> Callable:
            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> VexResult:
                # Capture the input arguments
                input_data: Any = args[0] if len(args) == 1 and not kwargs else {"args": args, "kwargs": kwargs}

                start = time.monotonic()
                output = fn(*args, **kwargs)
                elapsed_ms = (time.monotonic() - start) * 1000.0

                event = ExecutionEvent(
                    agent_id=agent_id,
                    task=task,
                    input=input_data,
                    output=output,
                    latency_ms=elapsed_ms,
                )

                return self._process_event(event)

            return wrapper

        return decorator

    # ------------------------------------------------------------------
    # Public API: trace context manager
    # ------------------------------------------------------------------

    @contextmanager
    def trace(
        self,
        agent_id: str,
        task: Optional[str] = None,
        input_data: Any = None,
    ) -> Generator[TraceContext, None, None]:
        """Context manager for fine-grained execution tracing.

        Usage::

            with vex.trace(agent_id="enricher", task="Enrich records") as trace:
                output = my_agent.run(data)
                trace.set_ground_truth(source_docs)
                trace.set_schema(output_schema)
                trace.record(output)
            # trace.result is a VexResult

        Parameters
        ----------
        agent_id:
            Identifier for the agent being traced.
        task:
            Optional human-readable description of the agent's task.
        input_data:
            Optional input data to record in the event.

        Yields
        ------
        TraceContext
            A context object for recording steps and the final output.
        """
        ctx = TraceContext(
            guard=self,
            agent_id=agent_id,
            task=task,
            input_data=input_data,
        )
        yield ctx
        ctx._finalise()

    # ------------------------------------------------------------------
    # Public API: run explicit wrap
    # ------------------------------------------------------------------

    def run(
        self,
        agent_id: str,
        fn: Callable,
        task: Optional[str] = None,
        ground_truth: Any = None,
        schema: Optional[Dict[str, Any]] = None,
        input_data: Any = None,
    ) -> VexResult:
        """Execute a callable and wrap the result with Vex processing.

        This is a framework-agnostic escape hatch for cases where neither
        the decorator nor the context manager is convenient.

        Usage::

            result = vex.run(
                agent_id="report-gen",
                task="Generate report",
                fn=lambda: my_agent.run(query),
                ground_truth=source_docs,
                schema=report_schema,
            )

        Parameters
        ----------
        agent_id:
            Identifier for the agent being monitored.
        fn:
            A zero-argument callable that produces the agent's output.
        task:
            Optional human-readable description of the agent's task.
        ground_truth:
            Optional reference data for verification.
        schema:
            Optional expected output schema.
        input_data:
            Optional input data to record in the event.

        Returns
        -------
        VexResult
            The processed result containing output, confidence, and action.
        """
        start = time.monotonic()
        output = fn()
        elapsed_ms = (time.monotonic() - start) * 1000.0

        event = ExecutionEvent(
            agent_id=agent_id,
            task=task,
            input=input_data,
            output=output,
            latency_ms=elapsed_ms,
            ground_truth=ground_truth,
            schema_definition=schema,
        )

        return self._process_event(event)

    # ------------------------------------------------------------------
    # Public API: session grouping
    # ------------------------------------------------------------------

    def session(
        self,
        agent_id: str,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Session:
        """Create a session for grouping related executions.

        Usage::

            session = vex.session(agent_id="chat-bot")
            with session.trace(task="turn 1") as ctx:
                ctx.record(output)
        """
        return Session(
            guard=self,
            agent_id=agent_id,
            session_id=session_id,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Shut down the Vex client, flushing any remaining events.

        Stops the background flush thread (which handles final flush and
        loop cleanup) and closes the sync transport. Safe to call multiple times.
        """
        if self._closed:
            return
        self._closed = True

        self._flush_stop.set()
        self._flush_thread.join(timeout=30.0)
        if self._flush_thread.is_alive():
            logger.warning("Flush thread did not stop within 30s; some events may be lost")

        if self._sync_transport is not None:
            try:
                self._sync_transport.close()
            except Exception:
                logger.warning("Error closing sync transport", exc_info=True)

    def __del__(self) -> None:
        """Best-effort cleanup if the user forgets to call close()."""
        if not self._closed:
            try:
                self.close()
            except Exception:
                pass
