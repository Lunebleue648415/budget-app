"""L'emplacement de la base : détection du danger, installation, mémorisation.

CE QUI EST EN JEU. L'emplacement par défaut de la base vit DANS le dossier de
l'application, que la prochaine mise à jour remplace — systématiquement sur
macOS, où il est dans le bundle `.app`. Ce fichier vérifie les trois pièces qui
protègent l'utilisateur de ça : `chemin_a_risque` (savoir qu'on y est),
`installer_base` (en sortir sans rien perdre) et `config_utilisateur` (s'en
souvenir au prochain lancement).

TOUT SE PASSE DANS DES DOSSIERS TEMPORAIRES, jamais dans la configuration réelle
de la machine : `BUDGET_CONFIG_DIR` la détourne, exactement comme
`BUDGET_DB_PATH` détourne la base. Sans lui, la suite écrirait un chemin de base
temporaire dans le profil, que l'application relirait au démarrage suivant.
"""
import json

import pytest

from app import config_utilisateur, database
from app.routers import parametres_base


@pytest.fixture
def config_temporaire(tmp_path, monkeypatch):
    """Détourne la configuration utilisateur vers un dossier jetable."""
    dossier = tmp_path / "conf"
    monkeypatch.setenv("BUDGET_CONFIG_DIR", str(dossier))
    return dossier


@pytest.fixture
def base_restauree():
    """Rend à l'application la base sur laquelle elle était ouverte.

    `installer_base` bascule le moteur global : sans cette remise en place, un
    test laisserait les suivants branchés sur un fichier temporaire effacé
    depuis.

    LA REMISE EN PLACE EST CONDITIONNELLE. La base de départ peut parfaitement
    ne pas exister en tant que fichier — c'est le cas quand la suite tourne
    avec un BUDGET_DB_PATH qui désigne un bac à sable jamais créé, et
    `changer_base` refuse (à raison) un fichier absent. Rien à restaurer alors,
    et surtout rien à faire échouer : ces tests-ci n'écrivent jamais dans la
    base de l'application, ils travaillent tous dans `tmp_path`."""
    depart = database.get_chemin_actuel()
    yield
    if depart.is_file():
        database.changer_base(str(depart))


# ---------- Savoir qu'on est au mauvais endroit ----------


def test_la_base_du_dossier_de_l_application_est_a_risque():
    """C'est TOUT le point de départ : l'emplacement par défaut est celui qu'une
    mise à jour efface."""
    assert database.chemin_a_risque(database.DEV_DB_PATH)


def test_une_base_ailleurs_n_est_pas_a_risque(tmp_path):
    assert not database.chemin_a_risque(tmp_path / "budget.db")


def test_l_emplacement_propose_est_hors_du_dossier_de_l_application():
    """Proposer un emplacement lui aussi à risque ferait reposer la question au
    lancement suivant, indéfiniment."""
    assert not database.chemin_a_risque(database.emplacement_propose())


# ---------- En sortir ----------


def test_installer_cree_une_base_utilisable(tmp_path, config_temporaire, base_restauree):
    """Une base créée de toutes pièces doit arriver au schéma courant, sans quoi
    l'application répondrait 500 sur ses pages principales dès l'ouverture."""
    cible = tmp_path / "neuve" / "budget.db"
    chemin, action = database.installer_base(str(cible))

    assert action == "créée"
    assert chemin == cible.resolve()
    assert cible.is_file()
    assert database.revision_actuelle(cible) == database.revision_cible()


def test_installer_deplace_la_base_au_lieu_de_la_copier(
    tmp_path, config_temporaire, base_restauree
):
    """DÉPLACEMENT et non copie : deux fichiers identiques dont un seul est lu
    sont une invitation à travailler des semaines dans le mauvais — et celui
    qu'on laisserait derrière est justement dans le dossier condamné."""
    source = tmp_path / "app" / "data" / "budget.db"
    source.parent.mkdir(parents=True)
    database.installer_base(str(source))

    cible = tmp_path / "mes-documents" / "budget.db"
    chemin, action = database.installer_base(str(cible), str(source))

    assert action == "déplacée"
    assert chemin == cible.resolve()
    assert cible.is_file()
    assert not source.exists(), "la base est restée dans le dossier de l'application"


def test_installer_ouvre_un_fichier_deja_present(tmp_path, config_temporaire, base_restauree):
    """Le cas de qui retrouve sa base après une mise à jour : on l'ouvre, on ne
    la remplace pas par une base vierge."""
    cible = tmp_path / "budget.db"
    database.installer_base(str(cible))
    database.changer_base(str(database.DEV_DB_PATH))

    _, action = database.installer_base(str(cible))
    assert action == "ouverte"


def test_installer_refuse_un_dossier(tmp_path, config_temporaire, base_restauree):
    """Un dossier donné pour un fichier doit échouer clairement plutôt que de
    fabriquer quoi que ce soit à côté."""
    with pytest.raises(ValueError, match="dossier"):
        database.installer_base(str(tmp_path))


# ---------- S'en souvenir ----------


def test_le_chemin_choisi_est_memorise_hors_du_dossier_de_l_application(
    tmp_path, config_temporaire
):
    """Le fichier de configuration existe POUR survivre à la mise à jour : le
    chemin doit y arriver, et depuis un dossier qui n'est pas celui de l'app."""
    cible = tmp_path / "mes-documents" / "budget.db"
    config_utilisateur.ecrire(**{config_utilisateur.CLE_CHEMIN_BASE: str(cible)})

    ecrit = json.loads((config_temporaire / "config.json").read_text(encoding="utf-8"))
    assert ecrit[config_utilisateur.CLE_CHEMIN_BASE] == str(cible)
    assert config_utilisateur.chemin_base_memorise() == cible
    assert not database.chemin_a_risque(config_utilisateur.fichier_config())


def test_une_configuration_absente_ne_leve_jamais(config_temporaire):
    """Un profil neuf : lire ne doit rien casser, l'application doit démarrer
    comme au premier lancement."""
    assert config_utilisateur.lire() == {}
    assert config_utilisateur.chemin_base_memorise() is None


def test_une_configuration_abimee_ne_leve_jamais(config_temporaire):
    """Le pire service à rendre à quelqu'un dont le fichier est corrompu serait
    de l'empêcher d'ouvrir l'application pour le réparer."""
    config_temporaire.mkdir(parents=True)
    (config_temporaire / "config.json").write_text("{ pas du json", encoding="utf-8")

    assert config_utilisateur.lire() == {}
    assert config_utilisateur.chemin_base_memorise() is None


def test_oublier_le_chemin_ramene_au_premier_demarrage(tmp_path, config_temporaire):
    """« Revenir à la base par défaut » ne doit pas mémoriser un chemin à
    risque : il efface au contraire ce qui était retenu, et la question sera
    reposée au prochain lancement."""
    config_utilisateur.ecrire(**{config_utilisateur.CLE_CHEMIN_BASE: str(tmp_path / "b.db")})
    assert config_utilisateur.chemin_base_memorise() is not None

    config_utilisateur.oublier_chemin_base()
    assert config_utilisateur.chemin_base_memorise() is None


# ---------- Ne rien faire de dangereux tout seul ----------


def test_pas_de_configuration_forcee_quand_l_environnement_impose_la_base(monkeypatch):
    """BUDGET_DB_PATH désigne déjà explicitement une cible : les tests et les
    bacs à sable n'ont rien à demander à personne."""
    monkeypatch.setenv("BUDGET_DB_PATH", "/tmp/quelconque.db")
    monkeypatch.delenv("BUDGET_FORCER_CHOIX_BASE", raising=False)
    assert not database.configuration_requise()


def test_pas_de_configuration_forcee_en_developpement(monkeypatch):
    """La base du dépôt n'est jamais remplacée par une archive : y forcer un
    choix ne protégerait de rien et casserait le serveur de dev."""
    monkeypatch.delenv("BUDGET_DB_PATH", raising=False)
    monkeypatch.delenv("BUDGET_FORCER_CHOIX_BASE", raising=False)
    assert not database.configuration_requise()


# ---------- Isolation des builds de test ----------
#
# CE QUE CES TESTS PROTÈGENT : qu'un bundle reconstruit pour essayer trois
# lignes de code n'ouvre JAMAIS la vraie base personnelle. Le chemin est
# mémorisé dans le profil de l'utilisateur, lequel est partagé par toutes les
# copies de l'application présentes sur la machine — sans cette isolation, une
# manipulation de mise au point se fait sur de vraies finances.


def test_en_developpement_ce_n_est_jamais_un_build_de_test(monkeypatch):
    """Le marqueur ne concerne que les bundles packagés : en développement, la
    base du dépôt est déjà la bonne, et il n'y a pas d'exécutable à côté duquel
    chercher quoi que ce soit."""
    monkeypatch.setattr(database.sys, "frozen", False, raising=False)
    assert not database.est_build_de_test()


def test_le_marqueur_pose_a_cote_de_l_executable_fait_un_build_de_test(tmp_path, monkeypatch):
    monkeypatch.setattr(database.sys, "frozen", True, raising=False)
    monkeypatch.setattr(database, "dossier_application", lambda: tmp_path)

    assert not database.est_build_de_test(), "sans marqueur, ce n'est pas un build de test"
    (tmp_path / database.NOM_MARQUEUR_BUILD_TEST).write_text("peu importe", encoding="utf-8")
    assert database.est_build_de_test(), "le marqueur seul doit suffire"


def test_un_build_de_test_n_ecrit_jamais_dans_le_profil(tmp_path, config_temporaire, monkeypatch):
    """LA garantie : laisser un bundle de mise au point écrire dans le profil
    ferait pointer la VRAIE application sur la base ouverte pour un essai."""
    monkeypatch.setattr(database, "est_build_de_test", lambda: True)

    assert parametres_base._memoriser(tmp_path / "essai.db") is False
    assert config_utilisateur.chemin_base_memorise() is None
    assert not config_utilisateur.fichier_config().exists()


def test_hors_build_de_test_le_choix_est_bien_memorise(tmp_path, config_temporaire, monkeypatch):
    """Le pendant du test précédent : sans marqueur, la mémorisation doit
    fonctionner — c'est elle qui protège les données des mises à jour."""
    monkeypatch.setattr(database, "est_build_de_test", lambda: False)
    cible = tmp_path / "mes-documents" / "budget.db"

    assert parametres_base._memoriser(cible) is True
    assert config_utilisateur.chemin_base_memorise() == cible
