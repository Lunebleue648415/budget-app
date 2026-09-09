"""Une opération garde LES FRAIS qu'elle porte.

CE QUI MANQUAIT. Les frais n'existaient qu'à l'import : `_appliquer_frais` les
fondait dans le montant (ajoutés à ce qui sort, retranchés de ce qui entre) et
ils disparaissaient. L'aperçu d'import savait encore écrire « dont frais 2 € » ;
l'opération enregistrée, elle, ne portait plus qu'un montant de 102 € dont plus
rien ne disait qu'il contenait 2 € de frais — impossible de les relire, de les
corriger, ou même de savoir qu'il y en avait eu.

PUREMENT DESCRIPTIF, ET C'EST VOULU. `montant` reste ce qui a bougé sur le
compte, frais compris : aucun solde, aucun KPI, aucune barre d'histogramme ne
change de valeur parce que cette colonne existe. Elle répond à « de quoi ce
montant est-il fait », pas à « combien ». C'est la même règle que
`montant_du` — une annotation sur un montant qui, lui, ne bouge pas.

LA MONNAIE DES FRAIS À CÔTÉ, parce qu'elle décide à quel montant ils
s'appliquent (cf. services/import_bancaire._appliquer_frais) : sur un virement
entre deux monnaies, des frais en euros grèvent la jambe émettrice, les mêmes en
dollars grèvent celle qui arrive. NULL = celle de l'opération, le cas ordinaire.

NULLABLE, et non zéro par défaut : « pas de frais » et « des frais de zéro » se
disent pareil, mais NULL dit en plus « personne n'a jamais renseigné ce champ »,
ce qui est le cas de toutes les opérations d'avant cette migration.

Revision ID: 0051
Revises: 0050
Create Date: 2026-09-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("operation", schema=None) as batch_op:
        batch_op.add_column(sa.Column("frais", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("monnaie_frais_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_operation_monnaie_frais",
            "monnaie",
            ["monnaie_frais_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade():
    with op.batch_alter_table("operation", schema=None) as batch_op:
        batch_op.drop_constraint("fk_operation_monnaie_frais", type_="foreignkey")
        batch_op.drop_column("monnaie_frais_id")
        batch_op.drop_column("frais")
