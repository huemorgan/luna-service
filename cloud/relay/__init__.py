"""Composio trigger relay — plan 015.

One Composio webhook subscription for the whole managed project arrives at
the control plane, gets verified, resolved to a tenant, queued, and
re-signed per-tenant for delivery to the agent machine's connector ingress.
"""
