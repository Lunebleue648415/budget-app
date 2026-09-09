"""Regroupement d'opérations par projet (extension « Projets »).

Ce que ces tests protègent, dans l'ordre de ce qui coûterait le plus cher à
casser :

  - UN PROJET NE POSSÈDE RIEN. Retirer une opération d'un projet, ou supprimer
    le projet entier, ne doit toucher à aucune opération : ce sont des données
    du budget, un projet n'en est qu'une vue. C'est LA propriété à ne jamais
    perdre — la perdre, c'est effacer des dépenses en croyant ranger ;
  - LE LIEN EST MULTIPLE. Une opération appartient à autant de projets qu'on
    veut : c'est la seule chose qui distingue un projet d'une catégorie, et
    toute la raison d'être d'une table d'association ;
  - LES TOTAUX SONT PAR MONNAIE. L'app ne stocke aucun taux de change ;
    additionner deux devises donnerait un nombre faux, affiché comme vrai.
"""
from datetime import date

import pytest
from fastapi import HTTPException

from app import crud, models, schemas
from app.constants import Sens, Statut

from .conftest import (
    charger_module_extension,
    creer_compte,
    creer_monnaie,
    get_categorie_id,
    get_monnaie_id,
    get_type_id,
)

service = charger_module_extension("projets", "service_projets.py")
routeur = charger_module_extension("projets", "routeur_projets.py")


# ---------- Outillage ----------


def _operation(db, compte, montant=100.0, sens=Sens.depense, monnaie_id=None, **kwargs):
    defaults = dict(
        date=date(2026, 8, 12),
        type_id=get_type_id(db, "classique"),
        categorie_id=get_categorie_id(db, "Autres"),
        nature="Hôtel",
        monnaie_id=monnaie_id or compte.monnaie_principale_id,
        sens=sens,
        statut=Statut.reel,
        montant=montant,
        montant_du=0.0,
        montant_a_rembourser=0.0,
    )
    defaults.update(kwargs)
    operation = models.Operation(compte_id=compte.id, **defaults)
    db.add(operation)
    db.commit()
    db.refresh(operation)
    return operation


def _projet(db, nom="Vacances Italie", description=""):
    return crud.create_sous_filtre(db, nom=nom, description=description)


# ---------- Ce qu'un projet ne possède pas ----------


def test_retirer_une_operation_ne_la_supprime_pas(db_session):
    """LA propriété à ne jamais perdre : « retirer du projet » et « supprimer »
    sont deux gestes sans rapport, et seul le second touche au budget."""
    compte = creer_compte(db_session, "Courant")
    operation = _operation(db_session, compte)
    projet = _projet(db_session)
    crud.ajouter_operations_au_sous_filtre(db_session, projet, [operation.id])

    crud.retirer_operations_du_sous_filtre(db_session, projet, [operation.id])

    assert crud.get_operation(db_session, operation.id) is not None
    assert crud.get_sous_filtre(db_session, projet.id).operations == []


def test_supprimer_un_projet_ne_supprime_aucune_operation(db_session):
    compte = creer_compte(db_session, "Courant")
    operation = _operation(db_session, compte)
    projet = _projet(db_session)
    crud.ajouter_operations_au_sous_filtre(db_session, projet, [operation.id])

    crud.delete_sous_filtre(db_session, projet)

    assert crud.get_operation(db_session, operation.id) is not None
    assert crud.list_sous_filtres(db_session) == []


def test_supprimer_une_operation_retire_le_lien(db_session):
    """La cascade de l'autre côté : une opération supprimée depuis la page
    Opérations ne doit pas laisser un lien orphelin dans un projet."""
    compte = creer_compte(db_session, "Courant")
    operation = _operation(db_session, compte)
    projet = _projet(db_session)
    crud.ajouter_operations_au_sous_filtre(db_session, projet, [operation.id])

    crud.delete_operation(db_session, operation)

    assert crud.get_sous_filtre(db_session, projet.id).operations == []


# ---------- Le lien est multiple ----------


def test_une_operation_peut_appartenir_a_plusieurs_projets(db_session):
    """C'est la seule chose qui distingue un projet d'une catégorie : les
    courses du 12 août sont légitimement dans « Vacances Italie » ET dans
    « Anniversaire de Marie »."""
    compte = creer_compte(db_session, "Courant")
    operation = _operation(db_session, compte, nature="Courses")
    italie = _projet(db_session, "Vacances Italie")
    anniversaire = _projet(db_session, "Anniversaire de Marie")

    crud.ajouter_operations_au_sous_filtre(db_session, italie, [operation.id])
    crud.ajouter_operations_au_sous_filtre(db_session, anniversaire, [operation.id])

    db_session.refresh(operation)
    assert {sf.nom for sf in operation.sous_filtres} == {
        "Vacances Italie",
        "Anniversaire de Marie",
    }


def test_retirer_d_un_projet_ne_retire_pas_de_l_autre(db_session):
    compte = creer_compte(db_session, "Courant")
    operation = _operation(db_session, compte)
    italie = _projet(db_session, "Vacances Italie")
    anniversaire = _projet(db_session, "Anniversaire de Marie")
    for projet in (italie, anniversaire):
        crud.ajouter_operations_au_sous_filtre(db_session, projet, [operation.id])

    crud.retirer_operations_du_sous_filtre(db_session, italie, [operation.id])

    assert crud.get_sous_filtre(db_session, italie.id).operations == []
    assert len(crud.get_sous_filtre(db_session, anniversaire.id).operations) == 1


def test_ajouter_deux_fois_la_meme_operation_ne_la_compte_qu_une_fois(db_session):
    """L'utilisateur coche des lignes, il ne tient pas le compte de celles qu'il
    avait cochées la semaine dernière : re-cocher ne doit rien casser."""
    compte = creer_compte(db_session, "Courant")
    operation = _operation(db_session, compte)
    projet = _projet(db_session)

    premier = crud.ajouter_operations_au_sous_filtre(db_session, projet, [operation.id])
    second = crud.ajouter_operations_au_sous_filtre(db_session, projet, [operation.id])

    assert (premier, second) == (1, 0)
    assert len(crud.get_sous_filtre(db_session, projet.id).operations) == 1


def test_une_operation_inconnue_est_ignoree_sans_faire_echouer_le_lot(db_session):
    compte = creer_compte(db_session, "Courant")
    operation = _operation(db_session, compte)
    projet = _projet(db_session)

    ajoutees = crud.ajouter_operations_au_sous_filtre(
        db_session, projet, [operation.id, 9999]
    )

    assert ajoutees == 1


# ---------- Les totaux ----------


def test_les_totaux_separent_depenses_et_entrees(db_session):
    compte = creer_compte(db_session, "Courant")
    projet = _projet(db_session)
    ids = [
        _operation(db_session, compte, montant=120.0, sens=Sens.depense).id,
        _operation(db_session, compte, montant=80.0, sens=Sens.depense).id,
        _operation(db_session, compte, montant=50.0, sens=Sens.entree).id,
    ]
    crud.ajouter_operations_au_sous_filtre(db_session, projet, ids)

    (total,) = service.totaux_par_monnaie(crud.get_sous_filtre(db_session, projet.id))
    assert total["depenses"] == 200.0
    assert total["entrees"] == 50.0
    # Négatif : le cas ordinaire d'un projet, qui coûte.
    assert total["solde"] == -150.0


def test_les_totaux_sont_separes_par_monnaie(db_session):
    """L'app ne stocke aucun taux de change : un voyage payé moitié en euros,
    moitié en francs suisses a deux lignes de totaux, pas un total faux."""
    euro = get_monnaie_id(db_session)
    franc = creer_monnaie(db_session, "Franc suisse", "CHF").id
    compte = creer_compte(
        db_session, "Courant", monnaies=[(euro, 0.0), (franc, 0.0)]
    )
    projet = _projet(db_session)
    ids = [
        _operation(db_session, compte, montant=100.0, monnaie_id=euro).id,
        _operation(db_session, compte, montant=60.0, monnaie_id=franc).id,
    ]
    crud.ajouter_operations_au_sous_filtre(db_session, projet, ids)

    totaux = service.totaux_par_monnaie(crud.get_sous_filtre(db_session, projet.id))
    assert len(totaux) == 2
    assert {t["monnaie_id"]: t["depenses"] for t in totaux} == {euro: 100.0, franc: 60.0}


def test_un_virement_interne_compte_selon_son_sens(db_session):
    """Comme le calcul des soldes du noyau : une sortie est une sortie, d'où
    qu'elle vienne. Les DEUX écritures d'un virement versées dans le même projet
    s'y annulent donc — ce qui est bien ce qu'elles valent, l'argent n'ayant pas
    quitté le patrimoine."""
    compte = creer_compte(db_session, "Courant")
    epargne = creer_compte(db_session, "Livret", type_nom="épargne")
    projet = _projet(db_session)
    virement = get_type_id(db_session, "virement")
    ids = [
        _operation(
            db_session,
            compte,
            montant=500.0,
            sens=Sens.transfert_sortant,
            type_id=virement,
            categorie_id=None,
        ).id,
        _operation(
            db_session,
            epargne,
            montant=500.0,
            sens=Sens.transfert_entrant,
            type_id=virement,
            categorie_id=None,
        ).id,
    ]
    crud.ajouter_operations_au_sous_filtre(db_session, projet, ids)

    (total,) = service.totaux_par_monnaie(crud.get_sous_filtre(db_session, projet.id))
    assert total["depenses"] == 500.0
    assert total["entrees"] == 500.0
    assert total["solde"] == 0.0


def test_un_projet_vide_n_a_aucun_total(db_session):
    projet = _projet(db_session)
    lu = service.lire_sous_filtre(crud.get_sous_filtre(db_session, projet.id))
    assert lu["totaux"] == []
    assert lu["nombre_operations"] == 0


# ---------- Le routeur ----------


def test_le_routeur_cree_lit_modifie_et_supprime(db_session):
    cree = routeur.create_projet(
        schemas.SousFiltreCreate(nom="Vacances Italie", description="août"),
        db=db_session,
    )
    assert cree["ordre"] == 0

    modifie = routeur.update_projet(
        cree["id"],
        schemas.SousFiltreUpdate(nom="Italie 2026", description="Rome et Naples"),
        db=db_session,
    )
    assert modifie["nom"] == "Italie 2026"

    routeur.delete_projet(cree["id"], db=db_session)
    assert routeur.list_projets(db=db_session) == []


def test_deux_projets_ne_peuvent_pas_porter_le_meme_nom(db_session):
    """Le nom est tout ce qu'un projet a d'identifiant pour l'utilisateur : deux
    homonymes seraient indiscernables dans la liste où on les choisit."""
    routeur.create_projet(schemas.SousFiltreCreate(nom="Vacances"), db=db_session)
    with pytest.raises(HTTPException) as erreur:
        routeur.create_projet(schemas.SousFiltreCreate(nom="Vacances"), db=db_session)
    assert erreur.value.status_code == 400


def test_renommer_un_projet_en_son_propre_nom_reste_permis(db_session):
    """Sans quoi corriger la seule description serait refusé."""
    cree = routeur.create_projet(schemas.SousFiltreCreate(nom="Vacances"), db=db_session)
    modifie = routeur.update_projet(
        cree["id"],
        schemas.SousFiltreUpdate(nom="Vacances", description="août"),
        db=db_session,
    )
    assert modifie["description"] == "août"


def test_le_routeur_repond_404_sur_un_projet_inconnu(db_session):
    with pytest.raises(HTTPException) as erreur:
        routeur.get_projet(999, db=db_session)
    assert erreur.value.status_code == 404


def test_le_routeur_verse_et_retire_par_lots(db_session):
    compte = creer_compte(db_session, "Courant")
    projet = _projet(db_session)
    ids = [_operation(db_session, compte).id for _ in range(3)]

    ajout = routeur.ajouter_operations(
        projet.id, schemas.SousFiltreOperations(operation_ids=ids), db=db_session
    )
    assert ajout == {"ajoutees": 3}
    assert len(routeur.list_operations_du_projet(projet.id, db=db_session)) == 3

    retrait = routeur.retirer_operations(
        projet.id, schemas.SousFiltreOperations(operation_ids=ids[:2]), db=db_session
    )
    assert retrait == {"retirees": 2}
    assert len(routeur.list_operations_du_projet(projet.id, db=db_session)) == 1
    # Et les trois opérations sont toujours là.
    assert all(crud.get_operation(db_session, op_id) is not None for op_id in ids)


def test_les_projets_se_reordonnent(db_session):
    premier = _projet(db_session, "A")
    second = _projet(db_session, "B")
    crud.reordonner_sous_filtres(db_session, [second.id, premier.id])
    assert [p["nom"] for p in routeur.list_projets(db=db_session)] == ["B", "A"]


# ---------- L'histogramme d'un projet ----------
#
# Le total dit ce qu'un voyage a coûté ; l'histogramme dit EN QUOI. Ce qui est
# vérifié ici est qu'il raconte la même chose que le total posé juste au-dessus
# de lui : mêmes opérations, même règle de sens, même découpage par monnaie.


def _barres(db, projet, monnaie_id=None):
    """Les barres d'un projet, pour une monnaie (la principale par défaut)."""
    lu = service.lire_sous_filtre(crud.get_sous_filtre(db, projet.id))
    monnaie_id = monnaie_id or get_monnaie_id(db)
    total = next((t for t in lu["totaux"] if t["monnaie_id"] == monnaie_id), None)
    return total["depenses_par_categorie"] if total else []


def test_la_somme_des_barres_vaut_le_total_depense(db_session):
    """L'INVARIANT DE L'ÉCRAN : le graphe est posé sous le total, les deux
    doivent s'accorder."""
    compte = creer_compte(db_session, "Courant")
    projet = _projet(db_session)
    crud.ajouter_operations_au_sous_filtre(
        db_session,
        projet,
        [
            _operation(db_session, compte, montant=120.0).id,
            _operation(
                db_session,
                compte,
                montant=80.0,
                categorie_id=get_categorie_id(db_session, "Alimentaire"),
            ).id,
        ],
    )

    lu = service.lire_sous_filtre(crud.get_sous_filtre(db_session, projet.id))
    total = lu["totaux"][0]

    assert sum(b["total_reel"] for b in total["depenses_par_categorie"]) == pytest.approx(
        total["depenses"]
    )
    assert total["depenses"] == 200.0


def test_les_barres_sont_classees_du_plus_lourd_au_plus_leger(db_session):
    compte = creer_compte(db_session, "Courant")
    projet = _projet(db_session)
    crud.ajouter_operations_au_sous_filtre(
        db_session,
        projet,
        [
            _operation(db_session, compte, montant=30.0).id,
            _operation(
                db_session,
                compte,
                montant=150.0,
                categorie_id=get_categorie_id(db_session, "Alimentaire"),
            ).id,
        ],
    )

    barres = _barres(db_session, projet)

    assert [b["categorie"] for b in barres] == ["Alimentaire", "Autres"]
    assert [b["total_reel"] for b in barres] == [150.0, 30.0]


def test_une_entree_versee_dans_le_projet_ne_dessine_aucune_barre(db_session):
    """Les entrées se lisent dans leur propre total : un graphe de DÉPENSES qui
    en porterait une contredirait la somme des barres."""
    compte = creer_compte(db_session, "Courant")
    projet = _projet(db_session)
    crud.ajouter_operations_au_sous_filtre(
        db_session,
        projet,
        [
            _operation(db_session, compte, montant=100.0).id,
            _operation(
                db_session,
                compte,
                montant=60.0,
                sens=Sens.entree,
                categorie_id=get_categorie_id(db_session, "Alimentaire"),
            ).id,
        ],
    )

    barres = _barres(db_session, projet)

    assert [b["categorie"] for b in barres] == ["Autres"]
    assert barres[0]["total_reel"] == 100.0


def test_un_virement_sortant_compte_comme_une_depense(db_session):
    """Même règle que le total : le SENS décide, pas le type (cf.
    service_projets.SENS_SORTANTS)."""
    compte = creer_compte(db_session, "Courant")
    projet = _projet(db_session)
    crud.ajouter_operations_au_sous_filtre(
        db_session,
        projet,
        [
            _operation(
                db_session,
                compte,
                montant=75.0,
                sens=Sens.transfert_sortant,
                type_id=get_type_id(db_session, "virement"),
                categorie_id=None,
            ).id
        ],
    )

    barres = _barres(db_session, projet)

    # Une opération sans catégorie garde sa barre : sans elle, la somme des
    # barres cesserait de valoir le total.
    assert [b["categorie"] for b in barres] == [service.CATEGORIE_SANS]
    assert barres[0]["total_reel"] == 75.0


def test_les_parts_d_une_operation_decoupee_font_leurs_propres_barres(db_session):
    compte = creer_compte(db_session, "Courant")
    operation = _operation(db_session, compte, montant=120.0, categorie_id=None)
    for ordre, (nom, montant) in enumerate(
        [("Alimentaire", 90.0), ("Charges fixes", 30.0)]
    ):
        db_session.add(
            models.OperationDecoupe(
                operation_id=operation.id,
                categorie_id=get_categorie_id(db_session, nom),
                montant=montant,
                ordre=ordre,
            )
        )
    db_session.commit()
    projet = _projet(db_session)
    crud.ajouter_operations_au_sous_filtre(db_session, projet, [operation.id])

    barres = _barres(db_session, projet)

    # Deux barres, et pas une troisième pour l'opération elle-même : la compter
    # en plus de ses parts l'aurait doublée.
    assert {b["categorie"]: b["total_reel"] for b in barres} == {
        "Alimentaire": 90.0,
        "Charges fixes": 30.0,
    }


def test_chaque_monnaie_a_ses_propres_barres(db_session):
    """PAR MONNAIE ET JAMAIS AUTREMENT, comme le total : l'app n'additionne
    jamais deux devises."""
    dollar = creer_monnaie(db_session, "Dollar", "$")
    compte = creer_compte(
        db_session,
        "Courant",
        monnaies=[(get_monnaie_id(db_session), 0.0), (dollar.id, 0.0)],
    )
    projet = _projet(db_session)
    crud.ajouter_operations_au_sous_filtre(
        db_session,
        projet,
        [
            _operation(db_session, compte, montant=100.0, monnaie_id=get_monnaie_id(db_session)).id,
            _operation(db_session, compte, montant=40.0, monnaie_id=dollar.id).id,
        ],
    )

    assert sum(b["total_reel"] for b in _barres(db_session, projet)) == 100.0
    assert sum(b["total_reel"] for b in _barres(db_session, projet, dollar.id)) == 40.0


def test_l_infobulle_fond_les_depenses_de_meme_libelle(db_session):
    """Même règle que l'histogramme du dashboard : trois « Hôtel » à 90 € font
    une ligne de 270, pas trois lignes de 90."""
    compte = creer_compte(db_session, "Courant")
    projet = _projet(db_session)
    crud.ajouter_operations_au_sous_filtre(
        db_session,
        projet,
        [_operation(db_session, compte, montant=90.0, nature="Hôtel").id for _ in range(3)],
    )

    top = _barres(db_session, projet)[0]["top_depenses"]

    assert top == [{"nature": "Hôtel", "montant": 270.0, "nombre": 3}]


def test_un_projet_vide_n_a_aucune_barre(db_session):
    projet = _projet(db_session)
    assert service.lire_sous_filtre(crud.get_sous_filtre(db_session, projet.id))["totaux"] == []
