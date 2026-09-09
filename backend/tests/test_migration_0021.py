"""La migration 0021 s'applique sur une base 0020 déjà peuplée.

Comme test_migration_0019 / 0020, ces tests appellent alembic en sous-processus :
les autres tests construisent le schéma via `Base.metadata.create_all` et ne
passeraient donc jamais par le script de migration lui-même — précisément là où
se cachent les erreurs qui ne se voient que sur une vraie base existante.

L'enjeu ici est la reprise de données : tout ce qui existait était implicitement
en euros et doit se retrouver rattaché à la monnaie créée par la migration, sans
rien perdre au passage (à commencer par les soldes initiaux, qui changent de
table).
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


def _alembic(db_path: Path, commande: str, revision: str):
    env = {**os.environ, "BUDGET_DB_PATH": str(db_path)}
    resultat = subprocess.run(
        [str(PYTHON), "-m", "alembic", commande, revision],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert resultat.returncode == 0, resultat.stderr
    return resultat


def _seed_base_0020(db_path: Path):
    """Un compte avec un solde initial, une opération, un budget et un titre :
    les quatre endroits que 0021 doit rattacher à une monnaie."""
    conn = sqlite3.connect(db_path)
    type_courant = conn.execute("select id from type_compte where nom='courant'").fetchone()[0]
    conn.execute(
        "INSERT INTO compte (nom, type_id, solde_initial) VALUES ('Courant', ?, 100)",
        (type_courant,),
    )
    categorie = conn.execute("select id from categorie where nom='Autres'").fetchone()[0]
    type_classique = conn.execute(
        "select id from type_operation where code='classique'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO operation (date,compte_id,type_id,categorie_id,nature,montant,sens,statut,"
        "montant_du,montant_a_rembourser,recurrente) "
        "VALUES ('2026-01-01',1,?,?,'Loyer',500,'dépense','réel',0,0,0)",
        (type_classique, categorie),
    )
    conn.execute(
        "INSERT INTO categorie_budget_mensuel (categorie_id, annee, mois, montant) "
        "VALUES (?, 2026, 1, 300)",
        (categorie,),
    )
    conn.execute("INSERT INTO action (nom, valeur) VALUES ('Air Liquide', 30)")
    conn.commit()
    conn.close()


def test_migration_0021_rattache_lexistant_a_leuro(tmp_path):
    db_path = tmp_path / "repro_0021.db"
    _alembic(db_path, "upgrade", "0020")
    _seed_base_0020(db_path)

    _alembic(db_path, "upgrade", "0021")

    conn = sqlite3.connect(db_path)
    # Une seule monnaie, l'euro.
    monnaies = conn.execute("select id, nom, symbole from monnaie").fetchall()
    assert len(monnaies) == 1
    monnaie_id, nom, symbole = monnaies[0]
    assert (nom, symbole) == ("Euro", "€")

    # Le solde initial a déménagé sur le compte_monnaie, sans changer de valeur.
    assert conn.execute(
        "select monnaie_id, solde_initial, ordre from compte_monnaie where compte_id=1"
    ).fetchall() == [(monnaie_id, 100.0, 0)]
    colonnes_compte = {
        row[1] for row in conn.execute("PRAGMA table_info(compte)").fetchall()
    }
    assert "solde_initial" not in colonnes_compte

    # Opération, budget et titre portent tous la monnaie.
    assert conn.execute("select nature, montant, monnaie_id from operation").fetchall() == [
        ("Loyer", 500.0, monnaie_id)
    ]
    assert conn.execute(
        "select montant, monnaie_id from categorie_budget_mensuel"
    ).fetchall() == [(300.0, monnaie_id)]
    assert conn.execute("select nom, monnaie_id from action").fetchall() == [
        ("Air Liquide", monnaie_id)
    ]
    conn.close()


def test_migration_0021_conserve_la_cle_dunicite_des_budgets(tmp_path):
    """La monnaie entre dans la clé : deux budgets du même mois dans deux
    monnaies doivent coexister, deux dans la même monnaie non."""
    db_path = tmp_path / "unicite_0021.db"
    _alembic(db_path, "upgrade", "0021")

    conn = sqlite3.connect(db_path)
    categorie = conn.execute("select id from categorie where nom='Autres'").fetchone()[0]
    euro = conn.execute("select id from monnaie").fetchone()[0]
    conn.execute("INSERT INTO monnaie (nom, symbole, ordre) VALUES ('Dollar', '$', 1)")
    dollar = conn.execute("select id from monnaie where nom='Dollar'").fetchone()[0]

    conn.execute(
        "INSERT INTO categorie_budget_mensuel (categorie_id, monnaie_id, annee, mois, montant) "
        "VALUES (?, ?, 2026, 3, 300)",
        (categorie, euro),
    )
    conn.execute(
        "INSERT INTO categorie_budget_mensuel (categorie_id, monnaie_id, annee, mois, montant) "
        "VALUES (?, ?, 2026, 3, 400)",
        (categorie, dollar),
    )
    conn.commit()

    try:
        conn.execute(
            "INSERT INTO categorie_budget_mensuel (categorie_id, monnaie_id, annee, mois, montant) "
            "VALUES (?, ?, 2026, 3, 999)",
            (categorie, euro),
        )
        conn.commit()
        doublon_accepte = True
    except sqlite3.IntegrityError:
        doublon_accepte = False
    assert doublon_accepte is False
    conn.close()


def test_downgrade_0021_rend_le_solde_initial_au_compte(tmp_path):
    db_path = tmp_path / "downgrade_0021.db"
    _alembic(db_path, "upgrade", "0020")
    _seed_base_0020(db_path)
    _alembic(db_path, "upgrade", "0021")

    _alembic(db_path, "downgrade", "0020")

    conn = sqlite3.connect(db_path)
    tables = {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}
    assert "monnaie" not in tables and "compte_monnaie" not in tables
    assert conn.execute("select solde_initial from compte where id=1").fetchone() == (100.0,)
    colonnes_operation = {
        row[1] for row in conn.execute("PRAGMA table_info(operation)").fetchall()
    }
    assert "monnaie_id" not in colonnes_operation
    conn.close()
