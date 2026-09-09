"""Migration 0037 : lien de cotation et date de dernière lecture d'un titre.

Ce qui compte : un titre déjà en base n'acquiert ni lien ni date — son cours a
été saisi à la main, à un moment que personne n'a enregistré, et une date
inventée le ferait passer pour un cours relu ce jour-là. Et le retour arrière
laisse la table telle qu'avant, cours compris.
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


def _colonnes(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    colonnes = {ligne[1] for ligne in conn.execute(f"PRAGMA table_info({table})")}
    conn.close()
    return colonnes


def _creer_action(conn, nom: str, valeur: float) -> None:
    monnaie_id = conn.execute("SELECT id FROM monnaie LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO action (nom, valeur, monnaie_id) VALUES (?, ?, ?)",
        (nom, valeur, monnaie_id),
    )
    conn.commit()


def test_0037_un_titre_existant_na_ni_lien_ni_date(tmp_path):
    db_path = tmp_path / "r0037.db"
    _alembic(db_path, "upgrade", "0036")

    conn = sqlite3.connect(db_path)
    _creer_action(conn, "Air Liquide", 167.12)
    conn.close()

    _alembic(db_path, "upgrade", "0037")

    conn = sqlite3.connect(db_path)
    ligne = conn.execute("SELECT valeur, url_cours, cours_maj_le FROM action").fetchone()
    conn.close()
    # Le cours saisi à la main est intact, et les deux nouvelles colonnes disent
    # ce qu'elles doivent dire : « aucun lien, jamais relu en ligne ».
    assert ligne == (167.12, None, None)


def test_0037_le_retour_arriere_retire_les_deux_colonnes_sans_toucher_au_cours(tmp_path):
    db_path = tmp_path / "r0037_retour.db"
    _alembic(db_path, "upgrade", "0037")

    conn = sqlite3.connect(db_path)
    _creer_action(conn, "Air Liquide", 167.12)
    conn.execute("UPDATE action SET url_cours = 'https://exemple.fr/x'")
    conn.commit()
    conn.close()

    _alembic(db_path, "downgrade", "0036")

    colonnes = _colonnes(db_path, "action")
    assert "url_cours" not in colonnes
    assert "cours_maj_le" not in colonnes
    conn = sqlite3.connect(db_path)
    # Le titre et son cours survivent : on n'a retiré qu'une provenance, pas
    # une donnée du budget.
    assert conn.execute("SELECT nom, valeur FROM action").fetchone() == (
        "Air Liquide",
        167.12,
    )
    conn.close()
