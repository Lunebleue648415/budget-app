"""La migration 0029 renomme « montant reçu » en « montant initial ».

Le renommage a lieu DANS le JSON `import_preset.colonnes` : un preset qui lisait
`montant_destination` doit continuer à lire la même colonne du fichier, sous le
nouveau nom. Perdre le numéro reviendrait à lui faire lire n'importe quoi au
prochain import.
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

_COLONNES_AVANT = [
    {"index": 1, "propriete": "date"},
    {"index": 2, "propriete": "nature"},
    {"index": 3, "propriete": "montant"},
    {"index": 14, "propriete": "montant_destination"},
    {"index": 15, "propriete": "monnaie_destination"},
]


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


def _seed(db_path: Path, colonnes: list[dict], nom: str = "Wise") -> int:
    conn = sqlite3.connect(db_path)
    curseur = conn.execute(
        "INSERT INTO import_preset (nom, colonnes, colonnes_exclues_comparaison, "
        "ignorer_premiere_ligne) VALUES (?, ?, ?, 0)",
        (nom, json.dumps(colonnes), json.dumps([])),
    )
    preset_id = curseur.lastrowid
    conn.commit()
    conn.close()
    return preset_id


def _colonnes(db_path: Path, preset_id: int) -> list[dict]:
    conn = sqlite3.connect(db_path)
    brut = conn.execute(
        "SELECT colonnes FROM import_preset WHERE id = ?", (preset_id,)
    ).fetchone()[0]
    conn.close()
    return json.loads(brut)


def test_les_proprietes_sont_renommees_en_place(tmp_path):
    db_path = tmp_path / "initial_0029.db"
    _alembic(db_path, "upgrade", "0028")
    preset_id = _seed(db_path, _COLONNES_AVANT)

    _alembic(db_path, "upgrade", "0029")

    colonnes = _colonnes(db_path, preset_id)
    # Les numéros de colonne du fichier ne bougent pas : seul le nom change.
    assert colonnes == [
        {"index": 1, "propriete": "date"},
        {"index": 2, "propriete": "nature"},
        {"index": 3, "propriete": "montant"},
        {"index": 14, "propriete": "montant_initial"},
        {"index": 15, "propriete": "monnaie_initiale"},
    ]


def test_un_preset_sans_ces_colonnes_nest_pas_touche(tmp_path):
    db_path = tmp_path / "intact_0029.db"
    _alembic(db_path, "upgrade", "0028")
    ordinaires = [
        {"index": 1, "propriete": "date"},
        {"index": 2, "propriete": "nature"},
        {"index": 3, "propriete": "montant"},
    ]
    preset_id = _seed(db_path, ordinaires, nom="CC Perso")

    _alembic(db_path, "upgrade", "0029")

    assert _colonnes(db_path, preset_id) == ordinaires


def test_downgrade_0029_remet_les_anciens_noms(tmp_path):
    db_path = tmp_path / "downgrade_0029.db"
    _alembic(db_path, "upgrade", "0028")
    preset_id = _seed(db_path, _COLONNES_AVANT)
    _alembic(db_path, "upgrade", "0029")

    _alembic(db_path, "downgrade", "0028")

    assert _colonnes(db_path, preset_id) == _COLONNES_AVANT
