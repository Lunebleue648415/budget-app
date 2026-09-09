"""Panneau « Base de données » — DU NOYAU, et non plus une extension de dev.

CE QUI A CHANGÉ ET POURQUOI. Ces routes vivaient dans `extensions-dev/`, au
motif qu'ouvrir une base par son chemin est un outil de mise au point : livré à
tout le monde, ça offrait surtout un bon moyen de travailler sans s'en rendre
compte sur la mauvaise base.

Le raisonnement tenait tant que la base par défaut était sûre. Elle ne l'est
pas : elle vit dans le dossier de l'application, que la prochaine mise à jour
remplace — systématiquement sur macOS, où elle est DANS le bundle `.app`.
Choisir où ranger ses données cesse alors d'être un confort de développeur pour
devenir la seule chose qui les protège, et une fonctionnalité que l'utilisateur
n'a pas ne le protège de rien.

CONSÉQUENCE SUR LA MÉMORISATION. L'extension ne retenait délibérément aucun
chemin au-delà de la session : redémarrer revenait toujours à la base de test.
C'était la bonne règle pour un outil de dev, et c'est exactement l'inverse de
ce qu'il faut ici — une base qu'on doit redésigner à chaque lancement n'est pas
une base, c'est une manipulation. Le choix est donc écrit dans le fichier de
configuration de l'utilisateur (cf. app/config_utilisateur.py), hors du dossier
de l'application pour survivre à ce qui l'efface.

UN CHEMIN À RISQUE N'EST JAMAIS MÉMORISÉ : le retenir reviendrait à graver le
problème qu'on cherche à résoudre. Revenir à la base de test OUBLIE au
contraire le choix, et le prochain démarrage redemandera où ranger la base.
"""
from fastapi import APIRouter, HTTPException

from .. import config_utilisateur, database, schemas

router = APIRouter(prefix="/parametres", tags=["parametres"])


def _memoriser(chemin) -> bool:
    """Retient `chemin` pour les prochains lancements — sauf s'il est à risque,
    auquel cas on efface au contraire ce qui était retenu. Rend False quand
    l'écriture a échoué (profil en lecture seule) : la bascule ne vaut alors
    que pour la session, et l'écran le dit.

    UN BUILD DE TEST N'ÉCRIT JAMAIS DANS LE PROFIL. Le fichier de configuration
    est partagé par toutes les copies de l'application présentes sur la machine :
    laisser un bundle de mise au point y écrire reviendrait à faire pointer la
    VRAIE application sur la base qu'on venait d'ouvrir pour un essai. Il se
    comporte donc comme l'ancienne extension développeur — la bascule vaut pour
    la session, et rien au-delà."""
    if database.est_build_de_test():
        return False
    if database.chemin_a_risque(chemin):
        config_utilisateur.oublier_chemin_base()
        return True
    return config_utilisateur.ecrire(**{config_utilisateur.CLE_CHEMIN_BASE: str(chemin)})


def _lire_etat(migration=None, choix_memorise: bool = True) -> schemas.BaseDonneesRead:
    """`migration` = (sauvegarde, révision quittée) quand la bascule qui vient
    d'avoir lieu a mis le schéma à jour ; None pour une simple lecture."""
    chemin_actuel = database.get_chemin_actuel()
    sauvegarde, revision_quittee = migration or (None, None)
    introuvable = database.BASE_MEMORISEE_INTROUVABLE
    return schemas.BaseDonneesRead(
        chemin_actuel=str(chemin_actuel),
        chemin_dev=str(database.DEV_DB_PATH),
        est_dev=chemin_actuel == database.DEV_DB_PATH,
        revision_base=database.revision_actuelle(chemin_actuel),
        revision_app=database.revision_cible(),
        migration_appliquee=sauvegarde is not None,
        sauvegarde=str(sauvegarde) if sauvegarde else None,
        revision_quittee=revision_quittee,
        a_risque=database.chemin_a_risque(chemin_actuel),
        configuration_requise=database.configuration_requise(),
        chemin_propose=str(database.emplacement_propose()),
        dossier_application=str(database.dossier_application()),
        base_memorisee_introuvable=str(introuvable) if introuvable else None,
        choix_memorise=choix_memorise,
        build_de_test=database.est_build_de_test(),
    )


@router.get("/base", response_model=schemas.BaseDonneesRead)
def get_base():
    return _lire_etat()


@router.put("/base", response_model=schemas.BaseDonneesRead)
def set_base(payload: schemas.BaseDonneesUpdate):
    """Bascule vers un fichier .db DÉJÀ EXISTANT — jamais de création
    implicite : un chemin fautif doit échouer clairement plutôt que fabriquer
    une base vide (cf. database.changer_base ; la création passe par
    /parametres/base/installer, qui la demande explicitement).

    La bascule met AUSSI le schéma de la base visée à jour : sans cela, une
    base rejointe après le démarrage restait à son ancienne version sous une
    application neuve et répondait 500 sur ses pages principales. Une copie est
    prise avant toute migration, et son chemin renvoyé ici."""
    try:
        chemin = database.changer_base(payload.chemin)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _lire_etat(database.derniere_migration(), _memoriser(chemin))


@router.post("/base/installer", response_model=schemas.BaseDonneesRead)
def installer_base(payload: schemas.BaseDonneesInstaller):
    """Met la base en place à l'emplacement choisi : ouvre le fichier s'il est
    déjà là, déplace la base actuelle si on le demande, en crée une neuve
    sinon. C'est la route de l'écran de premier démarrage.

    LE DÉPLACEMENT EST LE CAS NORMAL. Au premier lancement, l'application a
    déjà créé et rempli sa base par défaut (schéma et valeurs initiales, cf.
    desktop/app_desktop.py) : en créer une seconde, vide, et abandonner la
    première dans le dossier que la mise à jour effacera serait le plus mauvais
    des deux mondes."""
    source = str(database.get_chemin_actuel()) if payload.deplacer_actuelle else None
    try:
        chemin, action = database.installer_base(payload.chemin, source)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Impossible d'écrire à cet emplacement : {exc}")

    etat = _lire_etat(database.derniere_migration(), _memoriser(chemin))
    # Lequel des trois gestes a eu lieu : le frontend ne peut pas le déduire,
    # il ne sait pas si le fichier existait avant sa requête. « Base déplacée »
    # et « base créée » n'appellent pas le même message — le premier dit que
    # les données ont suivi, le second qu'on repart de zéro.
    etat.action = action
    return etat
