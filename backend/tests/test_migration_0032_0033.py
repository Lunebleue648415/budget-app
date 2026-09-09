"""Migrations 0032 (compte en face d'une règle) et 0033 (bloc-notes du dashboard).

Deux ajouts purement additifs : ce qu'on vérifie, c'est qu'ils ne touchent à
rien d'existant, et que le retour en arrière rend la base à son état d'avant.
"""
import json
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


def _seed_regle(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    type_id = conn.execute("SELECT id FROM type_operation WHERE code = 'virement'").fetchone()[0]
    curseur = conn.execute(
        "INSERT INTO regle_categorisation (nom, ordre, actif, type_id, conditions) "
        "VALUES ('Épargne', 0, 1, ?, ?)",
        (
            type_id,
            json.dumps(
                {
                    "operateur": "ET",
                    "groupes": [
                        {
                            "operateur": "ET",
                            "conditions": [
                                {"champ": "nature", "operateur": "contient", "valeur": "VIR"}
                            ],
                        }
                    ],
                }
            ),
        ),
    )
    regle_id = curseur.lastrowid
    conn.commit()
    conn.close()
    return regle_id


def test_0032_les_regles_existantes_survivent_sans_compte_en_face(tmp_path):
    db_path = tmp_path / "r0032.db"
    _alembic(db_path, "upgrade", "0031")
    regle_id = _seed_regle(db_path)

    _alembic(db_path, "upgrade", "0032")

    conn = sqlite3.connect(db_path)
    nom, compte_autre = conn.execute(
        "SELECT nom, compte_autre_id FROM regle_categorisation WHERE id = ?", (regle_id,)
    ).fetchone()
    conn.close()
    assert nom == "Épargne"
    # NULL : une règle écrite avant cette migration ne désigne aucun compte, et
    # ne doit surtout pas s'en voir attribuer un.
    assert compte_autre is None


def test_0032_le_retour_arriere_retire_la_colonne(tmp_path):
    db_path = tmp_path / "r0032_retour.db"
    _alembic(db_path, "upgrade", "0032")
    regle_id = _seed_regle(db_path)

    _alembic(db_path, "downgrade", "0031")

    assert "compte_autre_id" not in _colonnes(db_path, "regle_categorisation")
    conn = sqlite3.connect(db_path)
    (nom,) = conn.execute(
        "SELECT nom FROM regle_categorisation WHERE id = ?", (regle_id,)
    ).fetchone()
    conn.close()
    assert nom == "Épargne"


def test_0033_la_table_de_notes_nait_vide(tmp_path):
    """Aucune ligne semée : une base fraîche n'a pas de note, et une note vide
    n'est pas une note (cf. crud.set_note_dashboard, qui crée à la demande)."""
    db_path = tmp_path / "r0033.db"
    _alembic(db_path, "upgrade", "0033")

    conn = sqlite3.connect(db_path)
    nb = conn.execute("SELECT COUNT(*) FROM note_dashboard").fetchone()[0]
    conn.close()
    assert nb == 0
    assert {"id", "contenu", "modifie_le"} <= _colonnes(db_path, "note_dashboard")


def test_0033_le_retour_arriere_supprime_la_table(tmp_path):
    db_path = tmp_path / "r0033_retour.db"
    _alembic(db_path, "upgrade", "0033")

    _alembic(db_path, "downgrade", "0032")

    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "note_dashboard" not in tables
    # Le reste de la base est intact.
    assert "regle_categorisation" in tables
