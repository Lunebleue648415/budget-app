"""LES RÈGLES QUI REGARDENT LE MONTANT, et celles qui DÉCOUPENT.

Deux ajouts qui vont ensemble : une règle peut désormais se déclencher sur un
montant (« au-delà de 200 € »), et poser non plus une catégorie mais une
répartition entre plusieurs (« les 50 premiers euros en Repas, le reste en
Sorties »). La seconde n'a de sens que grâce à la première — sans formule, une
règle écrite une fois pour toutes ne saurait quoi faire d'une ligne dont elle
ignore le montant.
"""
import io
from datetime import date

import openpyxl
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import crud, schemas
from app.constants import COLONNES_IMPORT_PAR_DEFAUT
from app.services import import_bancaire, regles_categorisation
from app.services.formule_decoupe import FormuleInvalide, evaluer_formule, repartir

from .conftest import (
    charger_module_extension,
    creer_compte,
    get_categorie_id,
    get_monnaie_id,
    get_type_id,
)

create_regle = charger_module_extension("regles", "routeur_regles.py").create_regle


def _condition(champ, operateur, valeur):
    return {"champ": champ, "operateur": operateur, "valeur": valeur}


def _conditions(*conditions):
    return {"operateur": "ET", "groupes": [{"operateur": "ET", "conditions": list(conditions)}]}


def _brute(nature="Restaurant", montant=None):
    return {
        "nature": nature,
        "categorie_banque": "",
        "compte_banque": "",
        "montant": montant,
    }


# ---------- Conditions sur le montant ----------


@pytest.mark.parametrize(
    "operateur,valeur,montant,attendu",
    [
        ("supérieur à", "50", 60.0, True),
        ("supérieur à", "50", 50.0, False),
        ("supérieur ou égal à", "50", 50.0, True),
        ("inférieur à", "50", 49.99, True),
        ("inférieur ou égal à", "50", 50.0, True),
        ("égal à", "50", 50.0, True),
        ("égal à", "50", 50.004, True),  # tolérance au centime
        ("différent de", "50", 51.0, True),
        ("différent de", "50", 50.0, False),
    ],
)
def test_les_six_operateurs_numeriques(operateur, valeur, montant, attendu):
    conditions = _conditions(_condition("montant", operateur, valeur))

    assert (
        regles_categorisation.evaluer_regle(conditions, _brute(montant=montant)) is attendu
    )


def test_un_montant_illisible_ne_correspond_a_aucun_operateur():
    """Y COMPRIS « différent de ». Une ligne dont on ignore le montant n'est pas
    une ligne dont le montant diffère de 50 : c'est une ligne sur laquelle la
    règle n'a rien à dire."""
    for operateur in ("supérieur à", "différent de", "égal à"):
        conditions = _conditions(_condition("montant", operateur, "50"))
        assert (
            regles_categorisation.evaluer_regle(conditions, _brute(montant=None)) is False
        )


def test_la_valeur_de_la_regle_accepte_la_virgule_decimale():
    """Le champ se remplit à la main, en français."""
    conditions = _conditions(_condition("montant", "supérieur à", "49,50"))

    assert regles_categorisation.evaluer_regle(conditions, _brute(montant=49.6)) is True


def test_un_operateur_de_texte_sur_le_montant_est_refuse():
    """« le montant contient 12 » ne correspondrait jamais à rien : refusé à
    l'écriture plutôt que silencieusement faux à l'import."""
    with pytest.raises(ValidationError) as erreur:
        schemas.ConditionRegle(champ="montant", operateur="contient", valeur="12")

    assert "ne s'applique pas au champ" in str(erreur.value)


def test_un_operateur_numerique_sur_un_libelle_est_refuse():
    with pytest.raises(ValidationError):
        schemas.ConditionRegle(champ="nature", operateur="supérieur à", valeur="50")


# ---------- Les formules ----------


@pytest.mark.parametrize(
    "formule,montant,attendu",
    [
        ("50", 120.0, 50.0),
        ("montant", 120.0, 120.0),
        ("total", 120.0, 120.0),
        ("30%", 120.0, 36.0),
        ("min(montant; 50)", 120.0, 50.0),
        ("min(montant; 50)", 32.0, 32.0),
        ("max(10; montant * 0,05)", 120.0, 10.0),
        ("montant - 50", 120.0, 70.0),
        ("(montant + 30) / 2", 90.0, 60.0),
    ],
)
def test_ce_que_les_formules_valent(formule, montant, attendu):
    assert evaluer_formule(formule, montant) == pytest.approx(attendu)


@pytest.mark.parametrize(
    "formule",
    [
        "montant +",
        "truc",
        "min(50)",
        "montant)",
        "__import__('os')",
        "reste + 10",
    ],
)
def test_les_formules_illisibles_sont_refusees(formule):
    """PAS D'`eval` : ces chaînes viennent d'un formulaire, et une expression
    Python arbitraire exécutée côté serveur serait une porte, pas une
    fonctionnalité."""
    with pytest.raises(FormuleInvalide):
        evaluer_formule(formule, 100.0)


def test_le_reste_prend_ce_que_les_autres_n_ont_pas_pris():
    assert repartir(["min(montant; 50)", "reste"], 120.0) == [50.0, 70.0]
    assert repartir(["min(montant; 50)", "reste"], 32.0) == [32.0, 0.0]


def test_le_reste_n_a_pas_a_etre_ecrit_en_dernier():
    assert repartir(["reste", "20"], 120.0) == [100.0, 20.0]


def test_sans_reste_la_somme_doit_tomber_juste():
    """Arrondir en silence la dernière part reviendrait à modifier une formule
    que l'utilisateur a écrite exprès."""
    assert repartir(["30%", "70%"], 120.0) == [36.0, 84.0]
    with pytest.raises(FormuleInvalide) as erreur:
        repartir(["10", "20"], 120.0)
    assert "totalisent" in str(erreur.value)


def test_des_parts_chiffrees_qui_debordent_le_montant_sont_refusees():
    with pytest.raises(FormuleInvalide) as erreur:
        repartir(["200", "reste"], 120.0)

    assert "il ne reste rien" in str(erreur.value)


# ---------- La découpe posée par une règle ----------


def _parts(db, *couples):
    return [
        schemas.RegleDecoupeInput(categorie_id=get_categorie_id(db, nom), formule=formule)
        for nom, formule in couples
    ]


def _payload(db, decoupes=None, **kwargs):
    corps = dict(
        nom="Restaurants",
        conditions=_conditions(_condition("nature", "contient", "RESTAURANT")),
        type_id=get_type_id(db, "classique"),
        decoupes=decoupes or [],
    )
    corps.update(kwargs)
    return schemas.RegleCategorisationCreate(**corps)


def test_une_regle_peut_porter_une_decoupe(db_session):
    regle = create_regle(
        _payload(
            db_session,
            decoupes=_parts(
                db_session, ("Alimentaire", "min(montant; 50)"), ("Loisirs & sorties", "reste")
            ),
        ),
        db_session,
    )

    assert [part.formule for part in regle.decoupes] == ["min(montant; 50)", "reste"]
    assert [part.ordre for part in regle.decoupes] == [0, 1]


def test_la_decoupe_efface_la_categorie_unique(db_session):
    """Elles répondent à la même question ; une règle qui y répondrait deux fois
    laisserait le moteur d'import choisir à sa place."""
    regle = create_regle(
        _payload(
            db_session,
            categorie_id=get_categorie_id(db_session, "Autres"),
            decoupes=_parts(
                db_session, ("Alimentaire", "min(montant; 50)"), ("Loisirs & sorties", "reste")
            ),
        ),
        db_session,
    )

    assert regle.categorie_id is None
    assert len(regle.decoupes) == 2


def test_une_decoupe_sur_un_type_qui_ne_se_decoupe_pas_est_refusee(db_session):
    with pytest.raises(HTTPException) as erreur:
        create_regle(
            _payload(
                db_session,
                type_id=get_type_id(db_session, "remboursable"),
                decoupes=_parts(
                    db_session, ("Alimentaire", "min(montant; 50)"), ("Loisirs & sorties", "reste")
                ),
            ),
            db_session,
        )

    assert erreur.value.status_code == 400
    assert "ne se découpe pas" in erreur.value.detail


def test_une_formule_illisible_est_refusee_des_l_ecriture(db_session):
    """Une règle enregistrée aujourd'hui s'appliquera dans six mois : découvrir
    à ce moment-là qu'elle est illisible ferait échouer des lignes sans que rien
    ne rattache la panne à la règle fautive."""
    with pytest.raises(ValidationError) as erreur:
        _payload(
            db_session,
            decoupes=_parts(
                db_session, ("Alimentaire", "min(montant;"), ("Loisirs & sorties", "reste")
            ),
        )

    assert "formule invalide" in str(erreur.value)


def test_une_decoupe_de_regle_compte_au_moins_deux_parts(db_session):
    with pytest.raises(ValidationError):
        _payload(db_session, decoupes=_parts(db_session, ("Alimentaire", "montant")))


def test_deux_parts_ne_peuvent_pas_valoir_reste(db_session):
    with pytest.raises(ValidationError):
        _payload(
            db_session,
            decoupes=_parts(
                db_session, ("Alimentaire", "reste"), ("Loisirs & sorties", "reste")
            ),
        )


# ---------- Ce que la règle impose à une ligne ----------


def test_la_decoupe_remonte_dans_le_resultat_de_la_regle(db_session):
    create_regle(
        _payload(
            db_session,
            decoupes=_parts(
                db_session, ("Alimentaire", "min(montant; 50)"), ("Loisirs & sorties", "reste")
            ),
        ),
        db_session,
    )

    resultat = regles_categorisation.appliquer_regles(
        crud.list_regles_categorisation(db_session), _brute(nature="RESTAURANT DU COIN")
    )

    assert resultat is not None
    assert resultat.categorie_id is None
    assert resultat.decoupes == [
        (get_categorie_id(db_session, "Alimentaire"), "min(montant; 50)"),
        (get_categorie_id(db_session, "Loisirs & sorties"), "reste"),
    ]


def test_les_formules_se_resolvent_en_montants_pour_une_ligne(db_session):
    decoupes = [
        (get_categorie_id(db_session, "Alimentaire"), "min(montant; 50)"),
        (get_categorie_id(db_session, "Loisirs & sorties"), "reste"),
    ]

    parts, erreur = regles_categorisation.resoudre_decoupes(decoupes, 120.0)

    assert erreur is None
    assert parts == [
        (get_categorie_id(db_session, "Alimentaire"), 50.0),
        (get_categorie_id(db_session, "Loisirs & sorties"), 70.0),
    ]


def test_une_decoupe_impossible_rend_un_message_et_pas_une_exception(db_session):
    """L'appelant est l'aperçu d'import : un relevé de trois cents lignes dont
    une seule fait tomber une formule doit rester importable pour les autres."""
    decoupes = [
        (get_categorie_id(db_session, "Alimentaire"), "200"),
        (get_categorie_id(db_session, "Loisirs & sorties"), "reste"),
    ]

    parts, erreur = regles_categorisation.resoudre_decoupes(decoupes, 120.0)

    assert parts is None
    assert "découpe impossible" in erreur


def test_une_part_nulle_est_ecartee(db_session):
    """Une formule qui rend 0 sur cette ligne-là veut dire « rien pour cette
    catégorie », pas « une part vide » — que la table refuserait de toute façon."""
    decoupes = [
        (get_categorie_id(db_session, "Alimentaire"), "min(montant; 50)"),
        (get_categorie_id(db_session, "Loisirs & sorties"), "reste"),
    ]

    parts, erreur = regles_categorisation.resoudre_decoupes(decoupes, 32.0)

    assert erreur is None
    assert parts == [(get_categorie_id(db_session, "Alimentaire"), 32.0)]


def test_une_regle_de_complement_ne_repasse_pas_sur_une_ligne_deja_decoupee(db_session):
    """La catégorie et la découpe occupent la même case : sans ce test commun,
    une règle plus basse aurait posé une catégorie sur une ligne déjà découpée,
    et l'histogramme aurait compté la dépense deux fois."""
    create_regle(
        _payload(
            db_session,
            nom="Découpe",
            arreter_apres=False,
            decoupes=_parts(
                db_session, ("Alimentaire", "min(montant; 50)"), ("Loisirs & sorties", "reste")
            ),
        ),
        db_session,
    )
    create_regle(
        _payload(db_session, nom="Fourre-tout", categorie_id=get_categorie_id(db_session, "Autres")),
        db_session,
    )

    resultat = regles_categorisation.appliquer_regles(
        crud.list_regles_categorisation(db_session), _brute(nature="RESTAURANT DU COIN")
    )

    assert resultat.categorie_id is None
    assert len(resultat.decoupes) == 2
    assert resultat.nom_regle == "Découpe"


# ---------- Bout en bout : de la règle à l'opération importée ----------


def _construire_fichier(lignes):
    """Le format du preset par défaut : la date en 1, la nature en 4, la
    catégorie bancaire en 6, le montant en 7, le compte en 10."""
    classeur = openpyxl.Workbook()
    feuille = classeur.active
    for ligne in lignes:
        row = [None] * 12
        row[0] = ligne.get("date")
        row[3] = ligne.get("nature")
        row[6] = ligne.get("montant")
        row[9] = ligne.get("compte")
        feuille.append(row)
    tampon = io.BytesIO()
    classeur.save(tampon)
    return tampon.getvalue()


def _preparer_import(db, lignes):
    compte = creer_compte(db, "CC Perso")
    preset = crud.create_import_preset(db, "Défaut", COLONNES_IMPORT_PAR_DEFAUT)
    crud.set_mapping_compte(db, preset.id, "CC Perso", compte.id)
    return compte, preset, _construire_fichier(lignes)


def _regle_de_decoupe(db, formules=("min(montant; 50)", "reste")):
    return create_regle(
        _payload(
            db,
            nom="Restaurants",
            decoupes=_parts(
                db,
                ("Alimentaire", formules[0]),
                ("Loisirs & sorties", formules[1]),
            ),
        ),
        db,
    )


def test_une_regle_decoupe_une_ligne_importee(db_session):
    _, preset, contenu = _preparer_import(
        db_session,
        [
            {
                "date": date(2026, 7, 1),
                "nature": "RESTAURANT LE PONT",
                "montant": -120.0,
                "compte": "CC Perso",
            }
        ],
    )
    _regle_de_decoupe(db_session)

    apercu = import_bancaire.previsualiser(db_session, preset.id, contenu)

    ligne = apercu.lignes[0]
    assert ligne.regle_appliquee == "Restaurants"
    # Découpée = pas de catégorie unique, et pas d'erreur pour autant : les
    # parts SONT sa classification (cf. _erreur_ligne).
    assert ligne.categorie_id is None
    assert ligne.erreur is None
    assert [(part.categorie_id, part.montant) for part in ligne.decoupes] == [
        (get_categorie_id(db_session, "Alimentaire"), 50.0),
        (get_categorie_id(db_session, "Loisirs & sorties"), 70.0),
    ]


def test_la_decoupe_survit_a_la_confirmation(db_session):
    """Les parts doivent arriver jusqu'à la table, sinon l'aperçu promet un
    classement que l'import ne tient pas."""
    _, preset, contenu = _preparer_import(
        db_session,
        [
            {
                "date": date(2026, 7, 1),
                "nature": "RESTAURANT LE PONT",
                "montant": -120.0,
                "compte": "CC Perso",
            }
        ],
    )
    _regle_de_decoupe(db_session)

    import_bancaire.confirmer(
        db_session,
        preset.id,
        contenu,
        overrides=schemas.ImportMappingOverrides(),
        nom_fichier="releve.xlsx",
    )

    operation = db_session.query(crud.models.Operation).one()
    assert operation.est_decoupee
    assert operation.categorie_id is None
    assert [part.montant for part in operation.decoupes] == [50.0, 70.0]
    # L'invariant, jusqu'au bout : la somme des parts vaut le montant.
    assert sum(part.montant for part in operation.decoupes) == operation.montant


def test_une_formule_qui_deborde_laisse_la_ligne_importable(db_session):
    """Un relevé de trois cents lignes dont une seule fait tomber une formule
    doit rester importable pour les deux cent quatre-vingt-dix-neuf autres."""
    _, preset, contenu = _preparer_import(
        db_session,
        [
            {
                "date": date(2026, 7, 1),
                "nature": "RESTAURANT LE PONT",
                "montant": -30.0,
                "compte": "CC Perso",
            }
        ],
    )
    _regle_de_decoupe(db_session, formules=("200", "reste"))

    apercu = import_bancaire.previsualiser(db_session, preset.id, contenu)

    ligne = apercu.lignes[0]
    assert ligne.decoupes == []
    assert "découpe impossible" in ligne.decoupe_erreur
    # Elle retombe sur le classement ordinaire, et reste importable.
    assert ligne.categorie_id is not None
    assert ligne.erreur is None


def test_une_condition_de_montant_filtre_les_lignes_a_l_import(db_session):
    _, preset, contenu = _preparer_import(
        db_session,
        [
            {
                "date": date(2026, 7, 1),
                "nature": "Achat",
                "montant": -300.0,
                "compte": "CC Perso",
            },
            {
                "date": date(2026, 7, 2),
                "nature": "Achat",
                "montant": -20.0,
                "compte": "CC Perso",
            },
        ],
    )
    create_regle(
        _payload(
            db_session,
            nom="Grosses dépenses",
            conditions=_conditions(_condition("montant", "supérieur à", "200")),
            categorie_id=get_categorie_id(db_session, "Charges fixes"),
        ),
        db_session,
    )

    apercu = import_bancaire.previsualiser(db_session, preset.id, contenu)

    assert apercu.lignes[0].regle_appliquee == "Grosses dépenses"
    assert apercu.lignes[0].categorie_id == get_categorie_id(db_session, "Charges fixes")
    # LE MONTANT EST COMPARÉ EN VALEUR ABSOLUE : une dépense de 300 € est bien
    # « plus de 200 € en jeu », alors que le relevé l'écrit -300.
    assert apercu.lignes[1].regle_appliquee is None
