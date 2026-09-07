"""Per-Luna caps: hosting holds must not drain into agent_limit_periods;
partner signup gifts get their own source_type.

Bug (found 2026-09-07 via daniel-b/Gustavo): `ledger.authorize` skipped the
day/month caps for hosting holds (count_toward_limits=False) but the hold did
not remember that, so `settle` credited the 999-credit hosting month into the
new Luna's daily AND monthly periods — over both trial caps (75/800) from its
first minute, every chat 402 "luna_monthly_limit" until the calendar month
rolled over, wallet balance irrelevant.

- billing_holds.count_toward_limits (default true; hosting rows → false)
- repair: subtract each settled hosting hold from the periods it landed in
- credit_grants.source_type gains 'partner_gift'; existing partner/individual
  signup-offer trial lots are reclassified (their grant txn reason says so)

Revision ID: 0021
Revises: 0020
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

_SOURCE_TYPES_OLD = (
    "'subscription_paid','subscription_bonus','topup','free_recurring','gift','refund','admin'"
)
_SOURCE_TYPES_NEW = (
    "'subscription_paid','subscription_bonus','topup','free_recurring','gift','partner_gift','refund','admin'"
)


def upgrade() -> None:
    op.add_column(
        "billing_holds",
        sa.Column(
            "count_toward_limits", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )
    op.execute("UPDATE billing_holds SET count_toward_limits = false WHERE service = 'hosting'")

    # Repair the periods polluted by settled hosting holds. Only provisioning
    # settles went through ledger.settle (renewals charge directly), and only
    # those drained; the settle landed in the period containing settled_at.
    op.execute(
        """
        WITH h AS (
            SELECT agent_id, settled_at AS at, estimated_credits AS credits
            FROM billing_holds
            WHERE service = 'hosting' AND status = 'settled'
              AND agent_id IS NOT NULL AND settled_at IS NOT NULL
        ),
        agg AS (
            SELECT p.id AS pid, SUM(h.credits) AS credits
            FROM agent_limit_periods p
            JOIN h ON h.agent_id = p.agent_id
                  AND p.period_start <= h.at AND p.period_end > h.at
            GROUP BY p.id
        )
        UPDATE agent_limit_periods p
        SET settled_credits = GREATEST(p.settled_credits - agg.credits, 0)
        FROM agg
        WHERE p.id = agg.pid
        """
    )

    op.drop_constraint("ck_grant_source_type", "credit_grants", type_="check")
    op.create_check_constraint(
        "ck_grant_source_type", "credit_grants", f"source_type IN ({_SOURCE_TYPES_NEW})"
    )
    op.execute(
        """
        UPDATE credit_grants g
        SET source_type = 'partner_gift'
        FROM credit_ledger_transactions t
        WHERE t.id = g.grant_transaction_id
          AND g.source_type = 'gift'
          AND g.source_key LIKE 'trial:%'
          AND t.reason LIKE 'trial gift (% signup offer)'
        """
    )


def downgrade() -> None:
    op.execute("UPDATE credit_grants SET source_type = 'gift' WHERE source_type = 'partner_gift'")
    op.drop_constraint("ck_grant_source_type", "credit_grants", type_="check")
    op.create_check_constraint(
        "ck_grant_source_type", "credit_grants", f"source_type IN ({_SOURCE_TYPES_OLD})"
    )
    op.drop_column("billing_holds", "count_toward_limits")
