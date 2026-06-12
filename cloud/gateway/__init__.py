"""Credential gateway — proxies tenant traffic to keyed upstreams.

Real provider keys live only here (encrypted in the control-plane DB).
Tenant machines get a proxy base URL + an lsv1- tenant token, never a key.
"""
