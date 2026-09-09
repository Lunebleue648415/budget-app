"""DÉCOUPER une opération entre plusieurs catégories.

Un plein de courses à 120 € dont 30 € de produits ménagers était jusqu'ici
insoluble : soit on rangeait les 120 € dans « Courses » et l'histogramme
mentait sur « Maison », soit on saisissait deux opérations et le solde de
l'application cessait de coller au relevé bancaire. Cette migration ouvre la
troisième voie : UNE opération, PLUSIEURS parts.

DEUX TABLES, POUR DEUX MOMENTS DIFFÉRENTS.

`operation_decoupe` porte les parts d'une opération réelle : une catégorie et
un montant, dont la somme vaut exactement le montant de l'opération.
L'opération découpée passe alors `categorie_id` à NULL — ces lignes SONT sa
classification, et en garder une seconde à côté aurait ouvert la question de
laquelle compte dans l'histogramme.

`regle_decoupe` porte ce qu'une RÈGLE d'import impose : une catégorie et une
FORMULE. Une règle ne connaît pas le montant des lignes qu'elle rencontrera —
elle ne peut donc pas poser de nombres, seulement une manière d'en tirer
(« min(montant; 50) », « reste »).

RIEN N'EST MIGRÉ : les deux tables naissent vides, et une opération sans part
se comporte exactement comme avant. Redescendre la migration ne perd que les
découpes créées depuis.

Revision ID: 0049
Revises: 0048
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "operation_decoupe",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "operation_id",
            sa.Integer(),
            sa.ForeignKey("operation.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "categorie_id", sa.Integer(), sa.ForeignKey("categorie.id"), nullable=False
        ),
        sa.Column("montant", sa.Float(), nullable=False),
        sa.Column("ordre", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("montant > 0", name="ck_operation_decoupe_montant_positif"),
    )
    op.create_index(
        "ix_operation_decoupe_operation_id", "operation_decoupe", ["operation_id"]
    )
    op.create_index(
        "ix_operation_decoupe_categorie_id", "operation_decoupe", ["categorie_id"]
    )

    op.create_table(
        "regle_decoupe",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "regle_id",
            sa.Integer(),
            sa.ForeignKey("regle_categorisation.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "categorie_id",
            sa.Integer(),
            sa.ForeignKey("categorie.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("formule", sa.String(), nullable=False),
        sa.Column("ordre", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_regle_decoupe_regle_id", "regle_decoupe", ["regle_id"])


def downgrade():
    op.drop_index("ix_regle_decoupe_regle_id", table_name="regle_decoupe")
    op.drop_table("regle_decoupe")
    op.drop_index("ix_operation_decoupe_categorie_id", table_name="operation_decoupe")
    op.drop_index("ix_operation_decoupe_operation_id", table_name="operation_decoupe")
    op.drop_table("operation_decoupe")
