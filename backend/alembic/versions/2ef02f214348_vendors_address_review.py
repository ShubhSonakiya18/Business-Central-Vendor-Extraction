"""vendors address_review

Adds the nullable JSON column that records a reviewer's one-click
confirmation of an automatic Address / Address 2 rebalance
(docs/ADDRESS_SEGMENTATION_PLAN.md section 7-8). Written only by
POST /business-central/vendors/{id}/address-review/confirm; never by the
create/update payload.

Revision ID: 2ef02f214348
Revises: 3ec3dbd46e1b
Create Date: 2026-09-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2ef02f214348'
down_revision: Union[str, None] = '3ec3dbd46e1b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('vendors', schema=None) as batch_op:
        batch_op.add_column(sa.Column('address_review', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('vendors', schema=None) as batch_op:
        batch_op.drop_column('address_review')
