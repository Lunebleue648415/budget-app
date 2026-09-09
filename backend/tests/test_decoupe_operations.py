"""LA DÉCOUPE D'UNE OPÉRATION entre plusieurs catégories.

Un plein de courses à 120 € dont 30 € de produits ménagers est UNE opération —
une ligne au relevé, un seul mouvement de compte — et deux catégories. Ce
fichier vérifie les trois choses qui font tenir l'ensemble :

  1. le garde-fou : la somme des parts vaut le montant, sans quoi rien d'autre
     n'a de sens ;
  2. l'histogramme répartit bien la dépense entre les barres, et son total
     continue de tomber d'accord avec le total des sorties posé juste à côté ;
  3. la découpe et la catégorie unique s'excluent — jamais les deux à la fois.
"""
from datetime import date

import pytest
from fastapi import HTTPException

from app import crud, models, schemas
from app.constants import Statut
from app.routers.operations import create_operation as route_create_operation
from app.routers.operations import update_operation as route_update_operation
from app.services import soldes

from .conftest import creer_compte, get_categorie_id, get_monnaie_id, get_type_id


def _payload(db, compte, **kwargs):
    defaults = dict(
        date=date(2026, 7, 15),
        compte_id=compte.id,
        monnaie_id=get_monnaie_id(db),
        type_id=get_type_id(db, "classique"),
        nature="Courses",
        montant=120.0,
        statut=Statut.reel,
    )
    defaults.update(kwargs)
    return schemas.OperationCreate(**defaults)


def _parts(db, *couples):
    """[(nom de catégorie, montant), ...] -> liste de DecoupeInput."""
    return [
        schemas.DecoupeInput(categorie_id=get_categorie_id(db, nom), montant=montant)
        for nom, montant in couples
    ]


# ---------- Le garde-fou ----------


def test_les_parts_qui_totalisent_le_montant_sont_acceptees(db_session):
    compte = creer_compte(db_session, "Courant")
    operation = crud.create_operation(
        db_session,
        _payload(
            db_session,
            compte,
            decoupes=_parts(db_session, ("Alimentaire", 90.0), ("Charges fixes", 30.0)),
        ),
    )

    assert operation.est_decoupee
    assert [part.montant for part in operation.decoupes] == [90.0, 30.0]


def test_une_somme_de_parts_differente_du_montant_est_refusee(db_session):
    """C'est L'INVARIANT : sans lui, l'histogramme cesserait de totaliser les
    mêmes sorties que les KPI posés juste au-dessus."""
    erreur = crud.erreur_decoupes(
        "classique", 120.0, _parts(db_session, ("Alimentaire", 90.0), ("Charges fixes", 40.0))
    )

    assert erreur is not None
    assert "130.00" in erreur and "120.00" in erreur


def test_un_ecart_de_centieme_de_centime_reste_accepte(db_session):
    """Les montants sont des flottants : 30 + 90 ne fait pas toujours exactement
    120 en binaire. Exiger l'égalité stricte aurait refusé des découpes justes."""
    assert (
        crud.erreur_decoupes(
            "classique",
            120.0,
            _parts(db_session, ("Alimentaire", 90.0), ("Charges fixes", 30.000001)),
        )
        is None
    )


def test_une_seule_part_n_est_pas_une_decoupe(db_session):
    erreur = crud.erreur_decoupes(
        "classique", 120.0, _parts(db_session, ("Alimentaire", 120.0))
    )

    assert erreur is not None and "deux parts" in erreur


def test_deux_parts_dans_la_meme_categorie_sont_refusees(db_session):
    erreur = crud.erreur_decoupes(
        "classique",
        120.0,
        _parts(db_session, ("Alimentaire", 90.0), ("Alimentaire", 30.0)),
    )

    assert erreur is not None and "deux fois" in erreur


def test_seul_le_type_classique_se_decoupe(db_session):
    """Les autres types portent une catégorie imposée, un montant dû ou une
    contrepartie, que la découpe ne saurait pas répartir."""
    erreur = crud.erreur_decoupes(
        "remboursable", 120.0, _parts(db_session, ("Alimentaire", 90.0), ("Charges fixes", 30.0))
    )

    assert erreur is not None and "classique" in erreur


# ---------- La découpe remplace la catégorie unique ----------


def test_une_operation_decoupee_ne_porte_plus_de_categorie(db_session):
    compte = creer_compte(db_session, "Courant")
    operation = crud.create_operation(
        db_session,
        _payload(
            db_session,
            compte,
            categorie_id=get_categorie_id(db_session, "Alimentaire"),
            decoupes=_parts(db_session, ("Alimentaire", 90.0), ("Charges fixes", 30.0)),
        ),
    )

    assert operation.categorie_id is None


def test_retirer_les_parts_laisse_l_operation_sans_categorie(db_session):
    """La catégorie d'avant ne revient pas : elle avait été remplacée, la
    ressusciter rétablirait un classement que l'utilisateur avait défait."""
    compte = creer_compte(db_session, "Courant")
    operation = crud.create_operation(
        db_session,
        _payload(
            db_session,
            compte,
            decoupes=_parts(db_session, ("Alimentaire", 90.0), ("Charges fixes", 30.0)),
        ),
    )

    crud.update_operation(db_session, operation, schemas.OperationUpdate(decoupes=[]))

    assert operation.decoupes == []
    assert operation.categorie_id is None


def test_les_parts_disparaissent_avec_l_operation(db_session):
    compte = creer_compte(db_session, "Courant")
    operation = crud.create_operation(
        db_session,
        _payload(
            db_session,
            compte,
            decoupes=_parts(db_session, ("Alimentaire", 90.0), ("Charges fixes", 30.0)),
        ),
    )

    crud.delete_operation(db_session, operation)

    assert db_session.query(models.OperationDecoupe).count() == 0


# ---------- L'histogramme ----------


def _barres(db, annee=2026, mois=7):
    lignes = soldes.get_depenses_par_categorie(db, annee, mois, get_monnaie_id(db))
    return {ligne["categorie"]: ligne["total_reel"] for ligne in lignes}


def test_chaque_part_alimente_sa_propre_barre(db_session):
    compte = creer_compte(db_session, "Courant")
    crud.create_operation(
        db_session,
        _payload(
            db_session,
            compte,
            decoupes=_parts(db_session, ("Alimentaire", 90.0), ("Charges fixes", 30.0)),
        ),
    )

    barres = _barres(db_session)

    assert barres["Alimentaire"] == 90.0
    assert barres["Charges fixes"] == 30.0


def test_l_histogramme_s_accorde_toujours_avec_le_total_des_sorties(db_session):
    """LE POINT DE TOUT LE GARDE-FOU. Les flux somment le montant de
    l'opération, l'histogramme somme ses parts : les deux ne peuvent tomber
    d'accord que si les parts totalisent le montant."""
    compte = creer_compte(db_session, "Courant")
    crud.create_operation(
        db_session,
        _payload(
            db_session,
            compte,
            decoupes=_parts(db_session, ("Alimentaire", 90.0), ("Charges fixes", 30.0)),
        ),
    )

    flux = soldes.get_flux_periode(db_session, 2026, 7, get_monnaie_id(db_session))

    assert flux["sorties"] == pytest.approx(sum(_barres(db_session).values()))


def test_une_decoupe_amortie_ne_compte_que_pour_sa_part_de_la_periode(db_session):
    """L'amortissement porte sur l'OPÉRATION, pas sur la part : chaque part suit
    le même calendrier, et n'apporte au mois regardé que sa fraction."""
    compte = creer_compte(db_session, "Courant")
    crud.create_operation(
        db_session,
        _payload(
            db_session,
            compte,
            montant=1200.0,
            amorti=True,
            amortissement_debut=date(2026, 7, 1),
            amortissement_fin=date(2026, 12, 1),  # six mois
            decoupes=_parts(db_session, ("Alimentaire", 900.0), ("Charges fixes", 300.0)),
        ),
    )

    barres = _barres(db_session)

    assert barres["Alimentaire"] == pytest.approx(150.0)
    assert barres["Charges fixes"] == pytest.approx(50.0)


def test_l_infobulle_detaille_la_part_et_non_le_montant_entier(db_session):
    """Une seule dépense qui se retrouve dans deux barres y apparaît deux fois,
    chaque fois pour ce que cette catégorie lui doit — sinon les lignes de
    l'infobulle dépasseraient la barre qu'elles détaillent."""
    compte = creer_compte(db_session, "Courant")
    crud.create_operation(
        db_session,
        _payload(
            db_session,
            compte,
            nature="Hypermarché",
            decoupes=_parts(db_session, ("Alimentaire", 90.0), ("Charges fixes", 30.0)),
        ),
    )

    lignes = soldes.get_depenses_par_categorie(
        db_session, 2026, 7, get_monnaie_id(db_session)
    )
    par_categorie = {ligne["categorie"]: ligne["top_depenses"] for ligne in lignes}

    assert par_categorie["Alimentaire"] == [
        {"nature": "Hypermarché", "montant": 90.0, "nombre": 1}
    ]
    assert par_categorie["Charges fixes"] == [
        {"nature": "Hypermarché", "montant": 30.0, "nombre": 1}
    ]


# ---------- Les routes ----------
#
# Par les FONCTIONS DE ROUTE plutôt qu'un client HTTP, comme le reste de la
# suite : ce qui est vérifié ici est le refus en 400, pas le transport.


def _creer(db, compte, **kwargs):
    return route_create_operation(_payload(db, compte, **kwargs), db)


def test_la_route_refuse_une_somme_de_parts_fausse(db_session):
    compte = creer_compte(db_session, "Courant")

    with pytest.raises(HTTPException) as erreur:
        _creer(
            db_session,
            compte,
            decoupes=_parts(db_session, ("Alimentaire", 90.0), ("Charges fixes", 40.0)),
        )

    assert erreur.value.status_code == 400
    assert "somme des parts" in erreur.value.detail


def test_la_route_refuse_une_decoupe_sur_un_type_qui_ne_se_decoupe_pas(db_session):
    compte = creer_compte(db_session, "Courant")

    with pytest.raises(HTTPException) as erreur:
        _creer(
            db_session,
            compte,
            type_id=get_type_id(db_session, "remboursable"),
            decoupes=_parts(db_session, ("Alimentaire", 90.0), ("Charges fixes", 30.0)),
        )

    assert erreur.value.status_code == 400
    assert "classique" in erreur.value.detail


def test_la_route_refuse_de_changer_le_seul_montant_d_une_operation_decoupee(db_session):
    """Il n'existe aucune façon honnête de décider quelle part encaisse la
    différence : renvoyer les parts avec le nouveau montant est le chemin."""
    compte = creer_compte(db_session, "Courant")
    operation = _creer(
        db_session,
        compte,
        decoupes=_parts(db_session, ("Alimentaire", 90.0), ("Charges fixes", 30.0)),
    )

    with pytest.raises(HTTPException) as erreur:
        route_update_operation(
            operation.id, schemas.OperationUpdate(montant=200.0), db_session
        )

    assert erreur.value.status_code == 400
    assert "somme des parts" in erreur.value.detail


def test_le_montant_et_les_parts_changent_ensemble_sans_encombre(db_session):
    compte = creer_compte(db_session, "Courant")
    operation = _creer(
        db_session,
        compte,
        decoupes=_parts(db_session, ("Alimentaire", 90.0), ("Charges fixes", 30.0)),
    )

    modifiee = route_update_operation(
        operation.id,
        schemas.OperationUpdate(
            montant=200.0,
            decoupes=_parts(db_session, ("Alimentaire", 150.0), ("Charges fixes", 50.0)),
        ),
        db_session,
    )

    assert [part.montant for part in modifiee.decoupes] == [150.0, 50.0]


def test_les_parts_remontent_en_lecture_dans_l_ordre_saisi(db_session):
    compte = creer_compte(db_session, "Courant")
    operation = _creer(
        db_session,
        compte,
        decoupes=_parts(db_session, ("Charges fixes", 30.0), ("Alimentaire", 90.0)),
    )

    assert [part.ordre for part in operation.decoupes] == [0, 1]
    assert operation.decoupes[0].categorie_id == get_categorie_id(db_session, "Charges fixes")
    assert operation.categorie_id is None
