"""La migration 0022 convertit les correspondances visant un type en règles.

C'est le point délicat de cette migration : une correspondance
« Mouvements internes créditeurs -> Virement interne » disparaît en tant que
correspondance, mais son effet doit survivre. Faute de quoi le prochain import
classerait ces lignes en dépenses classiques, silencieusement.
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


def _seed_base_0021(db_path: Path):
    """Un preset avec deux correspondances vers un type et une vers une
    catégorie, plus une règle préexistante — de quoi vérifier la conversion, la
    préservation et le réordonnancement."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO import_preset (nom, colonnes, colonnes_exclues_comparaison, "
        "ignorer_premiere_ligne) VALUES ('Banque', '[]', '[]', 0)"
    )
    preset = conn.execute("select id from import_preset").fetchone()[0]
    type_virement = conn.execute(
        "select id from type_operation where code='virement'"
    ).fetchone()[0]
    categorie = conn.execute("select id from categorie where nom='Autres'").fetchone()[0]
    type_classique = conn.execute(
        "select id from type_operation where code='classique'"
    ).fetchone()[0]

    for nom in ("Mouvements internes créditeurs", "Mouvements internes débiteurs"):
        conn.execute(
            "INSERT INTO import_categorie_mapping (preset_id, nom_banque, categorie_id, type_id) "
            "VALUES (?, ?, NULL, ?)",
            (preset, nom, type_virement),
        )
    conn.execute(
        "INSERT INTO import_categorie_mapping (preset_id, nom_banque, categorie_id, type_id) "
        "VALUES (?, 'Divers', ?, NULL)",
        (preset, categorie),
    )
    conn.execute(
        "INSERT INTO regle_categorisation (nom, ordre, actif, type_id, categorie_id, conditions) "
        "VALUES ('Règle existante', 0, 1, ?, NULL, '{}')",
        (type_classique,),
    )
    conn.commit()
    conn.close()


def test_les_correspondances_vers_un_type_deviennent_des_regles(tmp_path):
    db_path = tmp_path / "repro_0022.db"
    _alembic(db_path, "upgrade", "0021")
    _seed_base_0021(db_path)

    _alembic(db_path, "upgrade", "0022")

    conn = sqlite3.connect(db_path)
    # Les deux correspondances vers un type sont parties…
    restantes = conn.execute(
        "select nom_banque, categorie_id from import_categorie_mapping"
    ).fetchall()
    assert restantes == [("Divers", 6)] or [r[0] for r in restantes] == ["Divers"]

    # …et sont devenues des règles d'égalité exacte sur la catégorie bancaire.
    regles = conn.execute(
        "select r.nom, r.ordre, t.code, r.conditions from regle_categorisation r "
        "join type_operation t on t.id = r.type_id order by r.ordre"
    ).fetchall()
    converties = [r for r in regles if "correspondance convertie" in r[0]]
    assert len(converties) == 2
    assert {r[2] for r in converties} == {"virement"}
    conditions = json.loads(converties[0][3])
    condition = conditions["groupes"][0]["conditions"][0]
    assert condition["champ"] == "categorie_banque"
    assert condition["operateur"] == "est"
    assert condition["valeur"].startswith("Mouvements internes")

    # Les règles converties passent devant la règle préexistante : une égalité
    # exacte doit primer sur une règle générique.
    ordres = {nom: ordre for nom, ordre, _, _ in regles}
    assert max(o for nom, o in ordres.items() if "convertie" in nom) < ordres["Règle existante"]

    # La colonne type_id a disparu, categorie_id est redevenue obligatoire.
    colonnes = {
        row[1]: row for row in conn.execute("PRAGMA table_info(import_categorie_mapping)")
    }
    assert "type_id" not in colonnes
    assert colonnes["categorie_id"][3] == 1  # notnull
    conn.close()


def test_downgrade_0022_restaure_les_correspondances(tmp_path):
    db_path = tmp_path / "downgrade_0022.db"
    _alembic(db_path, "upgrade", "0021")
    _seed_base_0021(db_path)
    _alembic(db_path, "upgrade", "0022")

    _alembic(db_path, "downgrade", "0021")

    conn = sqlite3.connect(db_path)
    # Faute de savoir de quel preset venait chaque correspondance, le downgrade
    # les restaure sur tous — ce qui reproduit la portée globale de la règle. Une
    # base migrée en compte au moins un ("Défaut", créé par 0014), d'où le
    # dédoublonnage sur le libellé plutôt qu'un compte de lignes.
    vers_type = conn.execute(
        "select distinct nom_banque from import_categorie_mapping where type_id is not null "
        "order by nom_banque"
    ).fetchall()
    assert [r[0] for r in vers_type] == [
        "Mouvements internes créditeurs",
        "Mouvements internes débiteurs",
    ]
    # Les règles converties ont été reprises, pas laissées en double.
    assert conn.execute(
        "select count(*) from regle_categorisation where nom like '%convertie)'"
    ).fetchone() == (0,)
    conn.close()
