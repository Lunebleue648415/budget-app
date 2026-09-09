"""L'histogramme du mois DÉPLIÉ EN SEMAINES.

CE QUI EST VÉRIFIÉ ICI, et qui vaut plus que tout le reste : **la somme des
semaines vaut la barre du mois**, au centime. Les deux graphes sont posés l'un
sous l'autre à l'écran ; s'ils ne s'accordaient pas, on ne lirait pas une
imprécision mais une erreur.

L'invariant tient par construction et sur deux fronts :

  - ce qui est DATÉ tombe dans la semaine de sa date, et les semaines
    partitionnent les jours du mois : ce sont les semaines du CALENDRIER
    (lundi → dimanche), coupées aux bords du mois — la première commence au 1er,
    la dernière finit au dernier jour (cf. soldes.semaines_du_mois) ;
  - ce qui est posé sur le MOIS et n'a pas de jour — la part d'une dépense
    amortie, le budget d'une catégorie — est réparti au prorata des jours
    (cf. soldes.prorata_semaine).

Le second cas est le piège : compter une dépense amortie en entier dans chaque
semaine l'aurait multipliée par cinq.
"""
from datetime import date

import pytest

from app import crud, models, schemas
from app.constants import Statut
from app.services import soldes

from .conftest import creer_compte, get_categorie_id, get_monnaie_id, get_type_id


def _depense(db, compte, nature, montant, jour, **kwargs):
    defaults = dict(
        date=date(2026, 1, jour),
        compte_id=compte.id,
        monnaie_id=get_monnaie_id(db),
        type_id=get_type_id(db, "classique"),
        categorie_id=get_categorie_id(db, "Alimentaire"),
        nature=nature,
        montant=montant,
        statut=Statut.reel,
    )
    defaults.update(kwargs)
    return crud.create_operation(db, schemas.OperationCreate(**defaults))


def _total(lignes, categorie="Alimentaire"):
    ligne = next((l for l in lignes if l["categorie"] == categorie), None)
    return ligne["total_previsionnel"] if ligne else 0.0


def _semaines(db, annee=2026, mois=1):
    return soldes.get_depenses_par_semaine(db, annee, mois, get_monnaie_id(db))


# ---------- Le découpage lui-même ----------


def test_les_semaines_vont_du_lundi_au_dimanche():
    """Janvier 2026 commence un jeudi : la première semaine ne fait que quatre
    jours, les suivantes tombent bien sur des lundis."""
    assert soldes.semaines_du_mois(2026, 1) == [
        (1, 4), (5, 11), (12, 18), (19, 25), (26, 31)
    ]
    assert date(2026, 1, 5).weekday() == 0  # lundi
    assert date(2026, 1, 4).weekday() == 6  # dimanche


def test_les_deux_bouts_du_mois_peuvent_etre_courts():
    """Mars 2026 commence un dimanche et finit un mardi : une semaine d'un jour
    au début, une de deux à la fin — et six blocs en tout."""
    assert soldes.semaines_du_mois(2026, 3) == [
        (1, 1), (2, 8), (9, 15), (16, 22), (23, 29), (30, 31)
    ]


def test_fevrier_bissextile_va_jusqu_a_son_29():
    assert soldes.semaines_du_mois(2028, 2) == [
        (1, 6), (7, 13), (14, 20), (21, 27), (28, 29)
    ]


def test_chaque_semaine_entiere_commence_un_lundi_et_finit_un_dimanche():
    """Sauf aux deux bords du mois, où elle est coupée."""
    for mois in range(1, 13):
        bornes = soldes.semaines_du_mois(2026, mois)
        for rang, (debut, fin) in enumerate(bornes):
            if rang > 0:
                assert date(2026, mois, debut).weekday() == 0, (mois, debut)
            if rang < len(bornes) - 1:
                assert date(2026, mois, fin).weekday() == 6, (mois, fin)


def test_les_semaines_couvrent_tous_les_jours_du_mois_sans_recouvrement():
    for mois in range(1, 13):
        jours = []
        for debut, fin in soldes.semaines_du_mois(2026, mois):
            jours.extend(range(debut, fin + 1))
        assert jours == sorted(set(jours)), mois
        assert jours[0] == 1 and jours[-1] == (31 if mois in (1, 3, 5, 7, 8, 10, 12) else 30 if mois != 2 else 28)


# ---------- Une dépense tombe dans la semaine de sa date ----------


def test_chaque_depense_tombe_dans_sa_semaine(db_session):
    # Janvier 2026 : [1-4], [5-11], [12-18], [19-25], [26-31].
    compte = creer_compte(db_session, "Courant")
    _depense(db_session, compte, "Courses", 30.0, jour=3)   # semaine 1
    _depense(db_session, compte, "Courses", 50.0, jour=10)  # semaine 2
    _depense(db_session, compte, "Courses", 20.0, jour=30)  # semaine 5

    semaines = _semaines(db_session)["semaines"]

    assert [_total(s["depenses"]) for s in semaines] == [30.0, 50.0, 0.0, 0.0, 20.0]


def test_la_borne_de_semaine_est_inclusive_des_deux_cotes(db_session):
    """Le dimanche 4 ferme la première semaine, le lundi 5 ouvre la seconde :
    c'est là qu'une erreur d'un jour se verrait."""
    compte = creer_compte(db_session, "Courant")
    _depense(db_session, compte, "Le 4", 7.0, jour=4)
    _depense(db_session, compte, "Le 5", 8.0, jour=5)

    semaines = _semaines(db_session)["semaines"]

    assert _total(semaines[0]["depenses"]) == 7.0
    assert _total(semaines[1]["depenses"]) == 8.0


# ---------- L'invariant : la somme des semaines vaut le mois ----------


def test_la_somme_des_semaines_vaut_la_barre_du_mois(db_session):
    compte = creer_compte(db_session, "Courant")
    for jour, montant in [(2, 12.5), (9, 33.0), (16, 8.25), (23, 41.0), (31, 5.75)]:
        _depense(db_session, compte, f"Achat {jour}", montant, jour=jour)

    resultat = _semaines(db_session)
    mois = soldes.get_depenses_par_categorie(db_session, 2026, 1, get_monnaie_id(db_session))

    somme = sum(_total(s["depenses"]) for s in resultat["semaines"])
    assert somme == pytest.approx(_total(mois))
    assert somme == pytest.approx(100.5)


def test_une_depense_amortie_est_repartie_au_prorata_des_jours(db_session):
    """UNE FACTURE ÉTALÉE N'A PAS DE JOUR dans le mois : elle pèse sur tout le
    mois. Elle est donc répartie au prorata des jours de chaque semaine —
    4/31, 7/31, 7/31, 7/31, 6/31 en janvier 2026 — et la somme des cinq vaut
    bien ce que le mois lui impute."""
    compte = creer_compte(db_session, "Courant")
    _depense(
        db_session,
        compte,
        "Assurance annuelle",
        1200.0,
        jour=15,
        amorti=True,
        amortissement_debut=date(2026, 1, 1),
        amortissement_fin=date(2026, 12, 1),
    )

    resultat = _semaines(db_session)
    parts = [_total(s["depenses"]) for s in resultat["semaines"]]

    # 100 € pour le mois (1 200 sur douze mois), redécoupés par jours.
    assert sum(parts) == pytest.approx(100.0)
    assert parts[0] == pytest.approx(100.0 * 4 / 31)
    assert parts[1] == pytest.approx(100.0 * 7 / 31)
    assert parts[4] == pytest.approx(100.0 * 6 / 31)


def test_les_parts_d_une_operation_decoupee_tombent_dans_sa_semaine(db_session):
    """Une opération découpée ne porte plus de catégorie : ce sont ses parts qui
    classent, et elles doivent suivre la date de leur opération."""
    compte = creer_compte(db_session, "Courant")
    operation = _depense(
        db_session,
        compte,
        "Plein de courses",
        120.0,
        jour=10,
        categorie_id=None,
        decoupes=[
            schemas.DecoupeInput(
                categorie_id=get_categorie_id(db_session, "Alimentaire"), montant=90.0
            ),
            schemas.DecoupeInput(
                categorie_id=get_categorie_id(db_session, "Loisirs & sorties"), montant=30.0
            ),
        ],
    )
    assert operation.est_decoupee

    semaines = _semaines(db_session)["semaines"]

    assert _total(semaines[1]["depenses"], "Alimentaire") == 90.0
    assert _total(semaines[1]["depenses"], "Loisirs & sorties") == 30.0
    assert _total(semaines[0]["depenses"], "Alimentaire") == 0.0


def test_le_budget_du_mois_est_lui_aussi_decoupe_au_prorata(db_session):
    """Un budget est posé pour un MOIS : le trait rouge d'une semaine dit le
    rythme à tenir, et la somme des cinq vaut le budget mensuel."""
    compte = creer_compte(db_session, "Courant")
    categorie_id = get_categorie_id(db_session, "Alimentaire")
    crud.set_budget_categorie(
        db_session, categorie_id, 2026, 1, get_monnaie_id(db_session), 310.0
    )

    resultat = _semaines(db_session)
    budgets = [
        next(l for l in s["depenses"] if l["categorie"] == "Alimentaire")["budget_alloue"]
        for s in resultat["semaines"]
    ]

    assert sum(budgets) == pytest.approx(310.0)
    assert budgets[0] == pytest.approx(310.0 * 4 / 31)


# ---------- La moyenne ----------


def test_la_moyenne_est_celle_des_semaines_affichees(db_session):
    """« Moyenne des semaines du mois » : leur somme divisée par leur nombre,
    dernière semaine courte comprise. C'est le seul calcul qu'on puisse
    vérifier à l'œil sur les barres d'à côté."""
    compte = creer_compte(db_session, "Courant")
    _depense(db_session, compte, "Courses", 100.0, jour=3)
    _depense(db_session, compte, "Courses", 50.0, jour=10)

    resultat = _semaines(db_session)

    assert len(resultat["semaines"]) == 5
    assert _total(resultat["moyenne"]) == pytest.approx(150.0 / 5)


def test_la_moyenne_porte_les_memes_categories_et_les_memes_couleurs(db_session):
    compte = creer_compte(db_session, "Courant")
    _depense(db_session, compte, "Courses", 40.0, jour=3)
    _depense(
        db_session,
        compte,
        "Cinema",
        20.0,
        jour=20,
        categorie_id=get_categorie_id(db_session, "Loisirs & sorties"),
    )

    resultat = _semaines(db_session)
    par_nom = {l["categorie"]: l for l in resultat["moyenne"]}
    reference = {
        l["categorie"]: l
        for l in soldes.get_depenses_par_categorie(
            db_session, 2026, 1, get_monnaie_id(db_session)
        )
    }

    assert set(par_nom) == set(reference)
    for nom, ligne in par_nom.items():
        assert ligne["couleur_index"] == reference[nom]["couleur_index"]
        # Une moyenne n'a pas eu lieu : rien à détailler au survol.
        assert ligne["top_depenses"] == []


# ---------- Ce que la vue semaine ne change pas ----------


def test_la_vue_mois_reste_intacte(db_session):
    """Le paramètre `semaine` est facultatif partout : sans lui, on lit
    exactement ce qu'on lisait avant qu'il existe."""
    compte = creer_compte(db_session, "Courant")
    _depense(db_session, compte, "Courses", 60.0, jour=3)

    sans = soldes.get_depenses_par_categorie(db_session, 2026, 1, get_monnaie_id(db_session))
    assert _total(sans) == 60.0

    # Et la vue annuelle ignore le découpage : `mois=None` neutralise le prorata.
    annee = soldes.get_depenses_par_categorie(
        db_session, 2026, None, get_monnaie_id(db_session)
    )
    assert _total(annee) == 60.0


def test_une_depense_d_un_autre_mois_n_entre_dans_aucune_semaine(db_session):
    compte = creer_compte(db_session, "Courant")
    _depense(db_session, compte, "Février", 90.0, jour=3, date=date(2026, 2, 3))

    semaines = _semaines(db_session)["semaines"]

    assert sum(_total(s["depenses"]) for s in semaines) == 0.0
