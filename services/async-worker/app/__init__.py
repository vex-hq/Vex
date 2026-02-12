"""AgentGuard Async Verification Worker.

Consumes execution events from the ``executions.raw`` Redis Stream,
runs verification via the engine pipeline, and publishes verified
results to ``executions.verified``.
"""
