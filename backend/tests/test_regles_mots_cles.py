"""PLUSIEURS MOTS-CLÉS DANS UNE SEULE CONDITION, combinés en ET.

CE QUE ÇA REMPLACE : une condition par mot-clé, dans un groupe « ET ». Écrire
« le libellé contient CARREFOUR et contient MARKET » demandait deux lignes de
formulaire là où on pense un seul test ; à cinq mots-clés, le groupe devenait
illisible.

CE QUE CES TESTS PROTÈGENT, dans l'ordre de ce qui coûterait le plus cher :

  - LES RÈGLES ÉCRITES AVANT continuent de mordre exactement pareil. Le JSON des
    conditions est libre et n'a pas été migré : `valeur` seule reste lisible, et
    doit l'être encore dans six mois ;
  - le ET, y compris pour les opérateurs NÉGATIFS : « ne contient pas A ni B »
    est ce qu'on veut dire en écrivant les deux ;
  - un opérateur NUMÉRIQUE n'en compare qu'un seul, et le dit plutôt que de
    choisir en silence lequel des deux compte.
"""
import pytest
from pydantic import ValidationError

from app import crud, schemas
from app.constants import OperateurRegle
from app.services import regles_categorisation

from .conftest import charger_module_extension, get_type_id

routeur = charger_module_extension("regles", "routeur_regles.py")


def _condition(**kwargs):
    defaults = dict(champ="nature", operateur=OperateurRegle.contient)
    defaults.update(kwargs)
    return schemas.ConditionRegle(**defaults)


def _conditions(condition):
    return {
        "operateur": "ET",
        "groupes": [{"operateur": "ET", "conditions": [condition]}],
    }


def _evaluer(condition, nature):
    """Évalue une condition Pydantic sur un libellé, comme le fait l'import."""
    return regles_categorisation.evaluer_condition(
        condition.model_dump(mode="json"), {"nature": nature}
    )


# ---------- La forme d'avant reste lisible ----------


def test_une_condition_a_valeur_unique_devient_une_liste_d_un_mot(db_session):
    """C'est ce qui permet à l'écran de ne connaître qu'une seule forme."""
    condition = _condition(valeur="PRET")
    assert condition.valeurs == ["PRET"]
    assert condition.valeur == "PRET"


def test_un_json_ancien_s_evalue_sans_passer_par_le_schema():
    """Une règle en base porte le JSON tel qu'il a été écrit : l'évaluateur doit
    le lire sans que rien ne l'ait normalisé au passage."""
    ancienne = {"champ": "nature", "operateur": "contient", "valeur": "PRET"}
    assert regles_categorisation.evaluer_condition(ancienne, {"nature": "VIR PRET"})
    assert not regles_categorisation.evaluer_condition(ancienne, {"nature": "SALAIRE"})


def test_valeur_suit_le_premier_mot_cle():
    """Une version de l'application antérieure à `valeurs` ne lit que `valeur` :
    une règle qui y perdrait sa valeur cesserait de mordre du jour au
    lendemain."""
    condition = _condition(valeurs=["CARREFOUR", "MARKET"])
    assert condition.valeur == "CARREFOUR"


# ---------- Le ET entre mots-clés ----------


def test_tous_les_mots_cles_doivent_correspondre():
    condition = _condition(valeurs=["CARREFOUR", "MARKET"])
    assert _evaluer(condition, "ACHAT CARREFOUR MARKET PARIS")
    assert not _evaluer(condition, "ACHAT CARREFOUR CITY")
    assert not _evaluer(condition, "ACHAT MARKET BIO")


def test_l_ordre_des_mots_dans_le_libelle_ne_compte_pas():
    condition = _condition(valeurs=["MARKET", "CARREFOUR"])
    assert _evaluer(condition, "ACHAT CARREFOUR MARKET")


def test_la_casse_et_les_accents_sont_ignores_comme_avant():
    condition = _condition(valeurs=["remboursé", "PAUL"])
    assert _evaluer(condition, "VIR REMBOURSE DE PAUL")


def test_un_operateur_negatif_ecarte_tous_les_mots():
    """« ne contient pas A ni B » : le ET dit exactement cela."""
    condition = _condition(operateur=OperateurRegle.ne_contient_pas, valeurs=["A", "B"])
    assert _evaluer(condition, "ZZZ")
    assert not _evaluer(condition, "AZZ")
    assert not _evaluer(condition, "ZBZ")


def test_est_avec_deux_mots_ne_correspond_jamais():
    """Un libellé ne peut pas être égal à deux choses à la fois. La règle est
    inutile, mais elle ne doit surtout pas mordre au hasard de l'ordre."""
    condition = _condition(operateur=OperateurRegle.est, valeurs=["A", "B"])
    assert not _evaluer(condition, "A")
    assert not _evaluer(condition, "B")


# ---------- Ce que le schéma refuse ou range ----------


def test_les_doublons_sont_retires():
    condition = _condition(valeurs=["Carrefour", "CARREFOUR", "Market"])
    assert condition.valeurs == ["Carrefour", "Market"]


def test_les_blancs_sont_retires():
    condition = _condition(valeurs=["  CARREFOUR  ", "", "   ", "MARKET"])
    assert condition.valeurs == ["CARREFOUR", "MARKET"]


def test_une_liste_entierement_vide_est_refusee():
    with pytest.raises(ValidationError):
        _condition(valeurs=["", "  "])


def test_ni_valeur_ni_valeurs_est_refuse():
    with pytest.raises(ValidationError):
        _condition()


def test_un_operateur_numerique_n_admet_qu_une_valeur():
    with pytest.raises(ValidationError) as erreur:
        _condition(champ="montant", operateur=OperateurRegle.superieur, valeurs=["30", "50"])
    assert "une seule valeur" in str(erreur.value)


def test_un_operateur_numerique_garde_sa_valeur_simple():
    condition = _condition(
        champ="montant", operateur=OperateurRegle.superieur_ou_egal, valeur="50"
    )
    assert condition.valeur == "50"
    assert condition.valeurs == []


def test_un_seul_mot_cle_numerique_redevient_la_valeur():
    condition = _condition(
        champ="montant", operateur=OperateurRegle.superieur, valeurs=["50"]
    )
    assert condition.valeur == "50"
    assert condition.valeurs == []


# ---------- L'aller-retour par les routes ----------


def test_les_mots_cles_font_l_aller_retour(db_session):
    lue = routeur.create_regle(
        schemas.RegleCategorisationCreate(
            nom="Courses Carrefour Market",
            conditions=_conditions(
                {
                    "champ": "nature",
                    "operateur": "contient",
                    "valeurs": ["CARREFOUR", "MARKET"],
                }
            ),
            type_id=get_type_id(db_session, "classique"),
        ),
        db=db_session,
    )
    # Le routeur rend l'objet SQLAlchemy, dont `conditions` est le JSON brut :
    # c'est `RegleCategorisationRead` qui le relit, et c'est bien cette lecture
    # que l'écran reçoit.
    def _mots(regle):
        lue = schemas.RegleCategorisationRead.model_validate(regle)
        return lue.conditions.groupes[0].conditions[0].valeurs

    assert _mots(lue) == ["CARREFOUR", "MARKET"]
    assert _mots(routeur.get_regle(lue.id, db=db_session)) == ["CARREFOUR", "MARKET"]


def test_une_regle_a_mots_cles_classe_une_ligne(db_session):
    """De bout en bout : la règle est en base, l'import la lit."""
    regle = crud.create_regle_categorisation(
        db_session,
        nom="Courses",
        conditions=_conditions(
            {
                "champ": "nature",
                "operateur": "contient",
                "valeurs": ["CARREFOUR", "MARKET"],
            }
        ),
        type_id=get_type_id(db_session, "classique"),
    )

    resultat = regles_categorisation.appliquer_regles(
        [regle], {"nature": "CB CARREFOUR MARKET 12/03"}
    )
    assert resultat is not None and resultat.nom_regle == "Courses"

    assert (
        regles_categorisation.appliquer_regles([regle], {"nature": "CB CARREFOUR CITY"})
        is None
    )
