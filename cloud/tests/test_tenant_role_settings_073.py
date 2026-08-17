"""Plan 073 — tenant role guardrails cover restart overlap."""

from cloud.db.tenant_provisioner import ROLE_CONNECTION_LIMIT, ROLE_SETTINGS, role_settings_sql


def test_role_limit_covers_two_pools():
    # fleet pool_size 2 + max_overflow 3 = 5 per process; a restart briefly
    # holds old + new → must fit.
    assert ROLE_CONNECTION_LIMIT >= 10


def test_keepalives_reap_orphans_fast():
    idle = int(ROLE_SETTINGS["tcp_keepalives_idle"])
    interval = int(ROLE_SETTINGS["tcp_keepalives_interval"])
    count = int(ROLE_SETTINGS["tcp_keepalives_count"])
    assert idle + interval * count <= 120


def test_role_settings_sql_shape():
    stmts = role_settings_sql("luna_a_x")
    assert stmts[0] == f'ALTER ROLE "luna_a_x" CONNECTION LIMIT {ROLE_CONNECTION_LIMIT}'
    assert any("idle_session_timeout = '15min'" in s for s in stmts)
    assert any("tcp_keepalives_idle = 30" in s for s in stmts)
    assert all(s.startswith('ALTER ROLE "luna_a_x"') for s in stmts)
