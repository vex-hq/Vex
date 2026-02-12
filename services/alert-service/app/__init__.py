"""AgentGuard Alert Service.

Consumes verified events from ``executions.verified``, filters for
flag/block actions, delivers webhook notifications, and records alert
delivery status in the database.
"""
