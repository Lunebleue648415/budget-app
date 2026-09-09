"""Une règle d'importation peut porter une DESCRIPTION.

CE QUE C'EST : une note libre, écrite par l'utilisateur, jamais lue par
l'application. Une règle se reconnaît à son nom (« Prêts reçus ») et à ses
conditions, mais ni l'un ni les autres ne disent POURQUOI elle existe — quel
relevé l'a rendue nécessaire, quel cas particulier elle rattrape, ce qu'il
faudra vérifier si elle cesse de mordre. Six mois plus tard, c'est la seule
chose qui manque devant une liste de vingt règles.

AUCUNE SÉMANTIQUE, et c'est délibéré : rien ne la filtre, rien ne la compare,
rien ne s'y déclenche. Exactement comme `SousFiltre.description` (les projets)
et comme le bloc-notes du dashboard.

LES DEUX FAMILLES DE RÈGLES D'IMPORT LA REÇOIVENT, dans la même migration :
`regle_categorisation` (relevés bancaires) et `regle_import_placement` (relevés
de compte-titres). Ce sont deux tables pour deux domaines, mais un seul geste
pour l'utilisateur — et n'en équiper qu'une aurait fait d'une note un privilège
dont on ne saurait pas dire à quelle liste il s'applique.

NON NULLABLE, DÉFAUT VIDE : comme `sous_filtre.description`. Une chaîne vide se
teste d'une seule façon (`if description:`), là où un NULL en ajoute une seconde
à chaque écran qui l'affiche.

Revision ID: 0050
Revises: 0049
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("regle_categorisation", "regle_import_placement"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "description",
                    sa.String(),
                    nullable=False,
                    server_default="",
                )
            )


def downgrade():
    for table in ("regle_categorisation", "regle_import_placement"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column("description")
