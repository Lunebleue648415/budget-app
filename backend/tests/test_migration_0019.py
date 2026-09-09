"""Régression : la migration 0019 doit réussir sur une base contenant des
opérations des quatre types "système" (catégorie système ou remboursable=1).

Ces tests appellent alembic en sous-processus, exactement comme l'utilisateur
le ferait en ligne de commande (`BUDGET_DB_PATH=... alembic upgrade head`) --
contrairement aux autres tests du projet, qui construisent le schéma via
`Base.metadata.create_all` et ne passent donc jamais par le script de
migration lui-même. C'est précisément pour ça qu'un bug dans 0019 (l'UPDATE
qui vide `categorie_id` s'exécutait avant que la colonne soit rendue
nullable) est passé inaperçu sur la base de dev : elle ne contenait aucune
opération de ces types, donc l'UPDATE ne touchait aucune ligne et ne pouvait
pas déclencher la contrainte NOT NULL.
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
# `sys.executable` et non `.venv/Scripts/python.exe` : ce dernier suppose un
# venv Windows créé à la main, qui n'existe jamais sur les runners de CI
# (`actions/setup-python` installe directement dans le Python du système,
# quel que soit l'OS) -- l'ancien chemin n'aurait fonctionné nulle part en CI.
# `sys.executable` est l'interpréteur qui exécute déjà pytest, avec les mêmes
# dépendances installées : c'est le seul chemin garanti d'exister, en local
# comme en CI, sur les trois systèmes.
PYTHON = sys.executable


def _alembic(db_path: Path, revision: str):
    env = {**os.environ, "BUDGET_DB_PATH": str(db_path)}
    resultat = subprocess.run(
        [str(PYTHON), "-m", "alembic", "upgrade", revision],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert resultat.returncode == 0, resultat.stderr
    return resultat


def _seed_operations_type_systeme(db_path: Path):
    """Reproduit exactement le cas qui faisait échouer 0019 : une opération
    par ancien type système, plus une remboursable=1 sur une catégorie
    normale (le cas "Dépense remboursable" pré-0019)."""
    conn = sqlite3.connect(db_path)
    type_courant = conn.execute(
        "select id from type_compte where nom='courant'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO compte (nom, type_id, solde_initial) VALUES ('Courant', ?, 0)",
        (type_courant,),
    )
    categories = dict(conn.execute("select nom, id from categorie").fetchall())
    lignes = [
        ("2026-01-01", "Loyer", categories["Autres"], "dépense", 500.0, "réel", 0, 0, 0),
        ("2026-01-02", "Prêt Marie", categories["Prêts"], "entrée", 200.0, "réel", 1, 200, 200),
        ("2026-01-03", "Remb Marie", categories["Remboursements"], "entrée", 50.0, "réel", 0, 0, 0),
        ("2026-01-04", "Virement Livret", categories["Virement interne"], "transfert_sortant", 100.0, "réel", 0, 0, 0),
        ("2026-01-05", "Remb prêt", categories["Remboursement prêts"], "dépense", 50.0, "réel", 0, 0, 0),
        ("2026-01-06", "Avance boulot", categories["Autres"], "dépense", 80.0, "réel", 1, 80, 80),
    ]
    for date, nature, categorie_id, sens, montant, statut, remboursable, du, a_rembourser in lignes:
        conn.execute(
            "INSERT INTO operation (date,compte_id,categorie_id,nature,montant,sens,statut,"
            "remboursable,montant_du,montant_a_rembourser,recurrente) VALUES (?,1,?,?,?,?,?,?,?,?,0)",
            (date, categorie_id, nature, montant, sens, statut, remboursable, du, a_rembourser),
        )
    conn.commit()
    conn.close()


def test_migration_0019_reussit_sur_une_base_avec_operations_de_types_systeme(tmp_path):
    db_path = tmp_path / "repro_0019.db"
    _alembic(db_path, "0018")
    _seed_operations_type_systeme(db_path)

    _alembic(db_path, "head")

    conn = sqlite3.connect(db_path)
    lignes = dict(
        conn.execute(
            "select o.nature, t.code from operation o join type_operation t on t.id = o.type_id"
        ).fetchall()
    )
    assert lignes == {
        "Loyer": "classique",
        "Prêt Marie": "pret",
        "Remb Marie": "remboursements",
        "Virement Livret": "virement",
        "Remb prêt": "remboursement_pret",
        "Avance boulot": "remboursable",
    }

    # Les quatre types système n'ont plus de catégorie ; les deux autres la
    # gardent.
    sans_categorie = {
        r[0]
        for r in conn.execute(
            "select nature from operation where categorie_id is null"
        ).fetchall()
    }
    assert sans_categorie == {"Prêt Marie", "Remb Marie", "Virement Livret", "Remb prêt"}

    noms_categories = {r[0] for r in conn.execute("select nom from categorie").fetchall()}
    assert noms_categories == {
        "Alimentaire",
        "Autres",
        "Charges fixes",
        "Réparation & entretien",
        "Vêtements & équipement sport",
        "Entrées d'argent",
        "Loisirs & sorties",
    }
