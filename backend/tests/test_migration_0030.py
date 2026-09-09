"""La migration 0030 introduit le mode de comparaison des doublons.

Deux exigences : les presets existants ne doivent RIEN changer à leur
comportement (mode `exclusion`, liste conservée telle quelle), et le retour en
arrière ne doit pas transformer une liste de colonnes à comparer en liste de
colonnes à ignorer — ce qui inverserait exactement la comparaison.
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


def _seed(db_path: Path, nom: str, exclues: list[int]) -> int:
    conn = sqlite3.connect(db_path)
    curseur = conn.execute(
        "INSERT INTO import_preset (nom, colonnes, colonnes_exclues_comparaison, "
        "ignorer_premiere_ligne) VALUES (?, ?, ?, 0)",
        (nom, json.dumps([{"index": 1, "propriete": "date"}]), json.dumps(exclues)),
    )
    preset_id = curseur.lastrowid
    conn.commit()
    conn.close()
    return preset_id


def _lire(db_path: Path, preset_id: int, colonnes: str) -> tuple:
    conn = sqlite3.connect(db_path)
    ligne = conn.execute(
        f"SELECT {colonnes} FROM import_preset WHERE id = ?", (preset_id,)
    ).fetchone()
    conn.close()
    return ligne


def test_les_presets_existants_gardent_leur_comportement(tmp_path):
    db_path = tmp_path / "initial_0030.db"
    _alembic(db_path, "upgrade", "0029")
    preset_id = _seed(db_path, "Banque", [5, 12])

    _alembic(db_path, "upgrade", "0030")

    liste, mode = _lire(db_path, preset_id, "colonnes_comparaison, mode_comparaison")
    # La liste survit au renommage, et le mode par défaut la lit comme avant :
    # tout est comparé sauf ces deux colonnes.
    assert json.loads(liste) == [5, 12]
    assert mode == "exclusion"


def test_le_retour_arriere_vide_la_liste_dun_preset_en_selection(tmp_path):
    db_path = tmp_path / "retour_0030.db"
    _alembic(db_path, "upgrade", "0029")
    exclusion_id = _seed(db_path, "Exclusion", [12])
    selection_id = _seed(db_path, "Selection", [])
    _alembic(db_path, "upgrade", "0030")

    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE import_preset SET mode_comparaison = 'selection', "
        "colonnes_comparaison = ? WHERE id = ?",
        (json.dumps([1, 2, 3]), selection_id),
    )
    conn.commit()
    conn.close()

    _alembic(db_path, "downgrade", "0029")

    # Le preset en exclusion retrouve sa liste inchangée...
    (liste_exclusion,) = _lire(db_path, exclusion_id, "colonnes_exclues_comparaison")
    assert json.loads(liste_exclusion) == [12]
    # ...tandis que celui en sélection repart de zéro : garder [1, 2, 3] aurait
    # voulu dire « compare tout SAUF la date, le libellé et le montant », soit
    # l'exact inverse de ce que l'utilisateur avait demandé.
    (liste_selection,) = _lire(db_path, selection_id, "colonnes_exclues_comparaison")
    assert json.loads(liste_selection) == []
