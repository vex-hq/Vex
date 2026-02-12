"""AgentGuard Sync Verification Gateway.

Receives execution events from the SDK in sync mode, runs verification
via the engine pipeline, and returns the result inline.  Also emits
events to Redis for async storage and alerting.
"""
