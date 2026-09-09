"""Les intérêts se SAISISSENT au lieu de se calculer.

CE QUI CHANGE, ET POURQUOI. La migration 0044 avait posé sur `compte` un taux
annuel, une fréquence de versement et une date de départ, à partir desquels
l'extension « Taux d'épargne » RECONSTITUAIT les intérêts : découpage du temps
en périodes sans mouvement, coefficient par période, solde de fin ouvrant la
suivante. Le calcul était juste, et c'était son problème — il ne pouvait être
juste que si l'app connaissait la totalité des mouvements du compte, à leur
date exacte, depuis l'ouverture. Un compte alimenté par imports partiels, un
livret ouvert bien avant la première ligne importée, une banque qui arrondit
autrement, un taux qui change en cours d'année (le Livret A l'a fait deux fois
en 2025) : dans tous ces cas le chiffre affiché diverge de celui du relevé,
sans que rien ne dise lequel des deux croire.

Or la banque, elle, ANNONCE le montant. Il est sur le relevé de fin d'année, en
une ligne. Le saisir prend dix secondes et vaut n'importe quelle reconstitution
— c'est un fait constaté, pas une estimation. D'où cette table : un montant,
une date, un compte, une monnaie.

CE QUI NE CHANGE PAS : ça reste un CALCUL D'AFFICHAGE. Aucun intérêt n'est écrit
en opération, aucun solde ni KPI du noyau ne lit cette table. L'écran sert à
suivre ce que rapportent les comptes, pas à tenir leur comptabilité — si
l'intérêt doit bouger le solde, c'est que le relevé le porte, et il entrera donc
par l'import comme n'importe quelle autre ligne.

UNE MONNAIE PAR LIGNE, comme partout : l'app ne connaît aucun taux de change et
n'additionne jamais deux devises. Un compte multi-devises reçoit donc une ligne
par devise.

LES TROIS COLONNES DE 0044 SONT RETIRÉES. Les garder « au cas où » aurait laissé
dans le schéma du noyau trois colonnes que plus rien ne lit, et sur l'écran la
tentation permanente de réafficher un chiffre théorique à côté du chiffre réel —
deux réponses à une seule question, dont l'une devrait finir par sembler fausse.
La copie horodatée prise avant toute migration (cf. database.migrer_si_necessaire)
est ce qui permet de les retrouver si besoin.

Revision ID: 0052
Revises: 0051
Create Date: 2026-09-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "interet_percu",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("compte_id", sa.Integer(), nullable=False),
        sa.Column("monnaie_id", sa.Integer(), nullable=False),
        # La date que porte le relevé. C'est par elle que les lignes se
        # regroupent par année à l'écran.
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("montant", sa.Float(), nullable=False),
        # Texte libre, jamais lu par un calcul : « intérêts 2025 »,
        # « prime de fidélité ». Non nullable et vide par défaut, comme
        # `SousFiltre.description` et `RegleCategorisation.description` — un
        # NULL aurait ajouté un second cas à tester dans chaque écran.
        sa.Column("libelle", sa.String(), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id"),
        # CASCADE : supprimer un compte emporte ses intérêts. Ils ne décrivent
        # rien sans lui, et une ligne orpheline ne serait plus rattachable à
        # quoi que ce soit.
        sa.ForeignKeyConstraint(["compte_id"], ["compte.id"], ondelete="CASCADE"),
        # PAS de CASCADE sur la monnaie : le routeur des monnaies refuse déjà
        # d'en supprimer une qui sert, et effacer des montants parce qu'on
        # retire une devise serait une perte silencieuse.
        sa.ForeignKeyConstraint(["monnaie_id"], ["monnaie.id"]),
        # Un intérêt PERÇU est une entrée. Zéro n'a rien à dire (« la banque
        # m'a versé zéro » se dit en ne saisissant rien), et un négatif serait
        # des frais, qui ne sont pas le sujet de cette table.
        sa.CheckConstraint("montant > 0", name="ck_interet_percu_montant_positif"),
    )
    # Le seul accès de l'écran : toutes les lignes d'un compte, dans l'ordre.
    op.create_index("ix_interet_percu_compte_date", "interet_percu", ["compte_id", "date"])

    with op.batch_alter_table("compte", schema=None) as batch_op:
        batch_op.drop_column("remuneration_debut")
        batch_op.drop_column("frequence_remuneration")
        batch_op.drop_column("taux_remuneration")


def downgrade():
    with op.batch_alter_table("compte", schema=None) as batch_op:
        batch_op.add_column(sa.Column("taux_remuneration", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("frequence_remuneration", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("remuneration_debut", sa.Date(), nullable=True))

    op.drop_index("ix_interet_percu_compte_date", table_name="interet_percu")
    op.drop_table("interet_percu")
