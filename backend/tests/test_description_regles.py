"""La NOTE d'une règle d'importation (migration 0050).

CE QU'ELLE EST : du texte libre, écrit par l'utilisateur, que l'application ne
lit jamais. Le nom d'une règle et ses conditions disent ce qu'elle FAIT ; ils ne
disent pas pourquoi elle existe — quel relevé l'a rendue nécessaire, quel cas
particulier elle rattrape. Devant une liste de vingt règles, six mois plus tard,
c'est la seule chose qui manque.

CE QUE CES TESTS PROTÈGENT :

  - la note fait l'aller-retour par les routes, sur les DEUX familles de règles
    (relevés bancaires et relevés de compte-titres) ;
  - elle est FACULTATIVE : une règle écrite avant qu'elle existe, ou un client
    qui ne l'envoie pas, reste valide et rend une chaîne vide — jamais NULL,
    qui aurait ajouté un second cas à tester dans chaque écran ;
  - et surtout : ELLE NE DÉCIDE DE RIEN. Aucun classement ne doit changer
    parce qu'on a écrit une phrase à côté d'une règle.
"""

from app import crud, schemas
from app.constants import TypeOperationPlacement
from app.services import regles_categorisation

from .conftest import charger_module_extension, get_type_id

routeur_bancaire = charger_module_extension("regles", "routeur_regles.py")
routeur_placement = charger_module_extension(
    "import-placements", "routeur_regles_placements.py"
)

NOTE = "La banque écrit « VIR RECU M DUPONT » pour les remboursements de Paul."


def _conditions(champ="nature", valeur="DUPONT"):
    return {
        "operateur": "ET",
        "groupes": [
            {
                "operateur": "ET",
                "conditions": [
                    {"champ": champ, "operateur": "contient", "valeur": valeur}
                ],
            }
        ],
    }


# ---------- Règles bancaires ----------


def test_la_note_fait_l_aller_retour(db_session):
    lue = routeur_bancaire.create_regle(
        schemas.RegleCategorisationCreate(
            nom="Remboursements de Paul",
            description=NOTE,
            conditions=_conditions(),
            type_id=get_type_id(db_session, "classique"),
        ),
        db=db_session,
    )
    assert lue.description == NOTE
    assert routeur_bancaire.get_regle(lue.id, db=db_session).description == NOTE


def test_la_note_est_facultative_et_vaut_la_chaine_vide(db_session):
    """Jamais NULL : une chaîne vide se teste d'une seule façon."""
    lue = routeur_bancaire.create_regle(
        schemas.RegleCategorisationCreate(
            nom="Sans note",
            conditions=_conditions(),
            type_id=get_type_id(db_session, "classique"),
        ),
        db=db_session,
    )
    assert lue.description == ""


def test_la_note_se_modifie_et_s_efface(db_session):
    regle = routeur_bancaire.create_regle(
        schemas.RegleCategorisationCreate(
            nom="Règle",
            description=NOTE,
            conditions=_conditions(),
            type_id=get_type_id(db_session, "classique"),
        ),
        db=db_session,
    )

    modifiee = routeur_bancaire.update_regle(
        regle.id,
        schemas.RegleCategorisationUpdate(
            nom="Règle",
            description="Autre chose",
            conditions=_conditions(),
            type_id=get_type_id(db_session, "classique"),
        ),
        db=db_session,
    )
    assert modifiee.description == "Autre chose"

    videe = routeur_bancaire.update_regle(
        regle.id,
        schemas.RegleCategorisationUpdate(
            nom="Règle",
            conditions=_conditions(),
            type_id=get_type_id(db_session, "classique"),
        ),
        db=db_session,
    )
    assert videe.description == ""


def test_la_note_ne_change_rien_au_classement(db_session):
    """LE POINT DE TOUT LE RESTE : deux règles identiques à leur note près
    classent une même ligne exactement pareil."""
    ligne = {"nature": "VIR RECU M DUPONT", "montant": 120.0}

    nue = crud.create_regle_categorisation(
        db_session,
        nom="Nue",
        conditions=_conditions(),
        type_id=get_type_id(db_session, "virement"),
    )
    sans_note = regles_categorisation.appliquer_regles([nue], ligne)

    crud.update_regle_categorisation(db_session, nue, description=NOTE)
    avec_note = regles_categorisation.appliquer_regles([nue], ligne)

    assert sans_note == avec_note
    assert avec_note is not None


# ---------- Règles d'import de placements ----------


def test_la_note_fait_l_aller_retour_cote_placements(db_session):
    lue = routeur_placement.create_regle(
        schemas.RegleImportPlacementCreate(
            nom="Achats au comptant",
            description="Ce courtier écrit « ACHAT COMPTANT » suivi du nom du titre.",
            conditions=_conditions(champ="type_brut", valeur="ACHAT"),
            type_placement=TypeOperationPlacement.achat,
        ),
        db=db_session,
    )
    assert lue.description == "Ce courtier écrit « ACHAT COMPTANT » suivi du nom du titre."
    assert routeur_placement.get_regle(lue.id, db=db_session).description == lue.description


def test_la_note_est_facultative_cote_placements(db_session):
    lue = routeur_placement.create_regle(
        schemas.RegleImportPlacementCreate(
            nom="Sans note",
            conditions=_conditions(champ="type_brut", valeur="ACHAT"),
            type_placement=TypeOperationPlacement.achat,
        ),
        db=db_session,
    )
    assert lue.description == ""


def test_la_note_se_modifie_cote_placements(db_session):
    regle = routeur_placement.create_regle(
        schemas.RegleImportPlacementCreate(
            nom="Achats",
            conditions=_conditions(champ="type_brut", valeur="ACHAT"),
            type_placement=TypeOperationPlacement.achat,
        ),
        db=db_session,
    )
    modifiee = routeur_placement.update_regle(
        regle.id,
        schemas.RegleImportPlacementUpdate(
            nom="Achats",
            description="Vu sur le relevé de janvier.",
            conditions=_conditions(champ="type_brut", valeur="ACHAT"),
            type_placement=TypeOperationPlacement.achat,
        ),
        db=db_session,
    )
    assert modifiee.description == "Vu sur le relevé de janvier."
