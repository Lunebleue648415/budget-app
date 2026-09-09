"""Soldes et agrégats, calculés séparément POUR CHAQUE MONNAIE.

L'app ne stocke aucun taux de change : additionner des euros et des dollars
n'aurait donc aucun sens, et inventer une conversion en aurait encore moins.
Tout ce qui somme des montants ici est donc groupé par monnaie — un compte à
deux monnaies a deux soldes, le dashboard a un jeu de KPI par monnaie, et une
catégorie a un budget par monnaie.

La clé de groupement est partout le couple (compte, monnaie) : c'est ce qui
permet à un compte multi-devises de rester UNE ligne en base (cf.
models.CompteMonnaie) au lieu d'être dupliqué.
"""
import calendar
from datetime import date as date_type
from typing import Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from .. import crud, extensions, models
from ..constants import (
    CATEGORIES_SENS_ENTREE,
    EXTENSION_PRETS,
    LIBELLE_INTERETS_PRETS,
    TYPES_COMPTE_HORS_COURANT,
    TYPES_HORS_FLUX,
    TYPES_REMBOURSABLES,
    Sens,
    Statut,
    TypeOperation,
)


# Codes des types dont l'opération est remboursable, pour les filtres SQL.
_CODES_REMBOURSABLES = [t.value for t in TYPES_REMBOURSABLES]
_CODES_HORS_FLUX = [t.value for t in TYPES_HORS_FLUX]

# LES INTÉRÊTS D'UN PRÊT : ce qu'on rendra moins ce qu'on a reçu, JAMAIS négatif.
#
# `montant_du >= montant` est désormais la règle du type « prêt reçu », tenue à
# l'écriture (cf. crud.erreur_montant_du / _borner_montant_du) : l'écart est donc
# positif ou nul par construction, et c'est lui qui coûte quelque chose.
#
# LA BORNE À ZÉRO RESTE, pour les lignes écrites AVANT que cette règle existe.
# Jusque-là un prêt voyait son `montant_du` forcé à `montant` — l'écart valait
# zéro — mais rien ne garantit qu'aucune base ne porte une valeur inférieure
# (import, reclassement d'une dépense remboursable). Sans cette borne, un tel
# prêt RETIRERAIT des sorties du mois : emprunter ferait baisser les dépenses.
_INTERETS_PRET = func.max(
    0.0, models.Operation.montant_du - models.Operation.montant
)


def _sums_by_compte_monnaie_and_sens(
    db: Session, statut: Optional[Statut], date_fin: Optional[date_type] = None
):
    query = db.query(
        models.Operation.compte_id,
        models.Operation.monnaie_id,
        models.Operation.sens,
        func.sum(models.Operation.montant).label("total"),
    )
    if statut is not None:
        query = query.filter(models.Operation.statut == statut)
    if date_fin is not None:
        query = query.filter(models.Operation.date <= date_fin)
    query = query.group_by(
        models.Operation.compte_id, models.Operation.monnaie_id, models.Operation.sens
    )

    result: dict = {}
    for compte_id, monnaie_id, sens, total in query.all():
        result.setdefault((compte_id, monnaie_id), {})[sens] = total or 0.0
    return result


def _solde_delta(sums: dict) -> float:
    return (
        sums.get(Sens.entree, 0.0)
        + sums.get(Sens.transfert_entrant, 0.0)
        - sums.get(Sens.depense, 0.0)
        - sums.get(Sens.transfert_sortant, 0.0)
    )


def fin_de_periode(annee: int, mois: Optional[int]) -> date_type:
    """Dernier jour de la période affichée : fin du mois, ou fin de l'année en
    vue annuelle. Sert de borne à la projection des soldes."""
    if mois is None:
        return date_type(annee, 12, 31)
    return date_type(annee, mois, calendar.monthrange(annee, mois)[1])


def _reste_du_prets_par_compte_monnaie(
    db: Session, date_fin: Optional[date_type] = None
) -> dict:
    """Reste à rembourser sur les prêts reçus, par couple (compte, monnaie).

    Un prêt reçu est une entrée d'argent : l'argent est bien là, mais il devra
    être rendu. Il gonfle donc légitimement le solde réel, jamais le solde
    projeté, qui doit refléter ce qu'il restera une fois les engagements soldés.

    C'est `montant_a_rembourser` (le reste dû, qui décroît au fil des
    remboursements) et non `montant` qui est soustrait : sinon rembourser
    pénaliserait deux fois (le prêt jamais compté, et la sortie de trésorerie
    du remboursement en plus)."""
    query = (
        db.query(
            models.Operation.compte_id,
            models.Operation.monnaie_id,
            func.sum(models.Operation.montant_a_rembourser).label("total"),
        )
        .join(models.TypeOperationDB, models.Operation.type_id == models.TypeOperationDB.id)
        .filter(models.TypeOperationDB.code == TypeOperation.pret.value)
    )
    if date_fin is not None:
        query = query.filter(models.Operation.date <= date_fin)
    rows = query.group_by(models.Operation.compte_id, models.Operation.monnaie_id).all()
    return {(compte_id, monnaie_id): (total or 0.0) for compte_id, monnaie_id, total in rows}


def get_soldes_comptes(db: Session, date_fin: Optional[date_type] = None):
    """Un élément par compte, chacun portant un solde PAR MONNAIE :

        [{"compte": <Compte>, "soldes": {monnaie_id: {"monnaie": <Monnaie>,
                                                      "solde_initial": ...,
                                                      "solde_reel": ...,
                                                      "solde_projete": ...}}}]

    Les monnaies déclarées sur le compte apparaissent toutes, même sans aucune
    opération (leur solde vaut alors le solde initial) : c'est ce qui rend
    visible un compte en dollars fraîchement ouvert.

    `date_fin` borne la **projection** : le solde projeté ne tient compte que
    des opérations jusqu'à cette date incluse. Sans borne, le projeté intégrait
    toutes les opérations futures connues, y compris les occurrences récurrentes
    générées jusqu'à 24 mois à l'avance — il ne répondait donc pas à "où j'en
    serai à la fin de la période affichée", mais à "où j'en serai une fois tout
    l'horizon écoulé".

    Le solde **réel** n'est jamais borné : il ne compte que des opérations au
    statut réel, déjà survenues par construction.
    """
    # Dans l'ordre choisi par l'utilisateur (crud.get_comptes) : les cartes du
    # dashboard se rangent alors comme les lignes de la page Comptes, type par
    # type — c'est là que cet ordre se décide.
    comptes = crud.get_comptes(db)
    sums_reel = _sums_by_compte_monnaie_and_sens(db, statut=Statut.reel)
    sums_total = _sums_by_compte_monnaie_and_sens(db, statut=None, date_fin=date_fin)
    reste_prets = _reste_du_prets_par_compte_monnaie(db, date_fin=date_fin)

    results = []
    for compte in comptes:
        soldes_initiaux = {lien.monnaie_id: lien.solde_initial for lien in compte.monnaies}
        monnaies = {lien.monnaie_id: lien.monnaie for lien in compte.monnaies}
        soldes = {}
        for monnaie_id, monnaie in monnaies.items():
            cle = (compte.id, monnaie_id)
            solde_initial = soldes_initiaux[monnaie_id]
            soldes[monnaie_id] = {
                "monnaie": monnaie,
                "solde_initial": solde_initial,
                "solde_reel": solde_initial + _solde_delta(sums_reel.get(cle, {})),
                "solde_projete": (
                    solde_initial
                    + _solde_delta(sums_total.get(cle, {}))
                    - reste_prets.get(cle, 0.0)
                ),
            }
        results.append({"compte": compte, "soldes": soldes})
    return results


def calculer_totaux_par_monnaie(
    comptes_soldes: list[dict], valorisation_placements: Optional[dict] = None
) -> dict:
    """À partir du résultat de get_soldes_comptes : les totaux du dashboard,
    **par monnaie**.

    solde_total_courant / solde_projete_courant sont limités aux comptes du
    budget courant (l'épargne et les comptes-titres ne sont soumis qu'à des
    virements internes — et à des achats/ventes de titres pour les seconds).
    total_avoirs est la seule valeur qui les inclut, pour voir le patrimoine
    complet ; il ajoute la valorisation des portefeuilles, car sur un
    compte-titres le solde du compte ne reflète que les espèces qui y dorment,
    et l'essentiel de l'avoir est justement ce qui n'y est plus.

    `valorisation_placements` est un dict {monnaie_id: montant} : un titre est
    coté dans une monnaie, sa valorisation ne peut donc entrer que dans le total
    de celle-là.
    """
    valorisation_placements = valorisation_placements or {}
    totaux: dict = {}

    def _entree(monnaie_id: int) -> dict:
        return totaux.setdefault(
            monnaie_id,
            {
                "solde_total_courant": 0.0,
                "solde_projete_courant": 0.0,
                "total_avoirs": 0.0,
                "valorisation_placements": 0.0,
            },
        )

    for item in comptes_soldes:
        est_courant = item["compte"].type_nom not in TYPES_COMPTE_HORS_COURANT
        for monnaie_id, solde in item["soldes"].items():
            entree = _entree(monnaie_id)
            entree["total_avoirs"] += solde["solde_reel"]
            if est_courant:
                entree["solde_total_courant"] += solde["solde_reel"]
                entree["solde_projete_courant"] += solde["solde_projete"]

    for monnaie_id, valorisation in valorisation_placements.items():
        entree = _entree(monnaie_id)
        entree["valorisation_placements"] += valorisation
        entree["total_avoirs"] += valorisation

    return totaux


# ---------- Le mois découpé en semaines ----------
#
# UNE SEMAINE VA DU LUNDI AU DIMANCHE, celle du calendrier — c'est la seule qui
# corresponde à quelque chose de vécu. « La semaine du 6 » se retrouve sur un
# relevé ; « le deuxième bloc de sept jours du mois » ne se retrouve nulle part.
#
# ELLE EST COUPÉE AUX BORDS DU MOIS : la première commence au 1er (donc courte
# si le 1er n'est pas un lundi), la dernière finit au dernier jour (donc courte
# si le mois ne finit pas un dimanche). Les semaines PARTITIONNENT ainsi le mois
# exactement, ce qui est ce dont tout le reste dépend : la somme des semaines
# vaut la barre du mois, et ce qui est posé sur le mois sans avoir de jour —
# part amortie, budget d'une catégorie — se répartit au prorata des jours.
#
# Une semaine à cheval sur deux mois est donc lue deux fois, une part de chaque
# côté. C'est voulu : on regarde un mois, pas une semaine flottante.
JOURS_PAR_SEMAINE = 7


def semaines_du_mois(annee: int, mois: int) -> list[tuple[int, int]]:
    """Les bornes (premier jour, dernier jour) de chaque semaine du mois.

    Quatre à six blocs selon le calendrier : du 1er au premier dimanche, puis
    des lundis aux dimanches, puis du dernier lundi à la fin du mois."""
    dernier = calendar.monthrange(annee, mois)[1]
    bornes = []
    debut = 1
    while debut <= dernier:
        # `weekday()` : lundi = 0 … dimanche = 6. Ce qui reste jusqu'au
        # dimanche vaut donc 6 − weekday, et zéro si on y est déjà.
        jour = date_type(annee, mois, debut)
        fin = min(debut + (6 - jour.weekday()), dernier)
        bornes.append((debut, fin))
        debut = fin + 1
    return bornes


def _bornes_semaine(annee: int, mois: int, semaine: int) -> tuple[date_type, date_type]:
    """Les deux dates d'une semaine, par son rang (1 pour la première)."""
    debut, fin = semaines_du_mois(annee, mois)[semaine - 1]
    return date_type(annee, mois, debut), date_type(annee, mois, fin)


def prorata_semaine(annee: int, mois: Optional[int], semaine: Optional[int]) -> float:
    """La part du mois que cette semaine représente, en JOURS (1.0 hors vue
    semaine).

    CE QUE CE COEFFICIENT SERT À ÉTALER : ce qui est posé sur le MOIS et non sur
    une date — la part d'une dépense amortie, et le budget d'une catégorie. Ni
    l'une ni l'autre n'a de jour dans le mois : une facture étalée sur douze
    mois pèse sur tout le mois, pas sur le 3. La répartir au prorata des jours
    est la seule façon de la faire compter sans inventer une date, et c'est ce
    qui garantit que la somme des semaines vaut toujours le mois.

    Une dépense DATÉE, elle, n'est jamais prorata­tisée : elle tombe dans la
    semaine de sa date, entière."""
    if mois is None or semaine is None:
        return 1.0
    debut, fin = _bornes_semaine(annee, mois, semaine)
    return (fin.day - debut.day + 1) / calendar.monthrange(annee, mois)[1]


def _filtre_periode(annee: int, mois: Optional[int], semaine: Optional[int] = None):
    """mois=None : agrège sur toute l'année plutôt qu'un mois précis (vue
    annuelle du dashboard) — même colonne de date, seul le format strftime
    change (comparaison sur l'année seule).

    `semaine` (1 pour la première du mois) restreint en plus à la semaine
    correspondante : c'est le seul ajout de la vue semaine, et il ne concerne
    que les opérations DATÉES — cf. prorata_semaine pour ce qui est posé sur le
    mois entier.

    LES OPÉRATIONS AMORTIES SONT EXCLUES ICI, et c'est le point : pour elles, la
    date ne dit plus QUAND la dépense pèse, seulement quand l'argent est sorti.
    Ce qu'elles apportent à la période se calcule à part
    (_filtre_periode_amortie + part_amortie), et les compter aussi par leur date
    les ferait peser deux fois sur leur mois d'origine. L'exclusion est posée
    dans ce filtre plutôt qu'à chaque appel : les deux agrégats de période
    (histogramme par catégorie, flux entrées/sorties) doivent l'appliquer, et
    aucun futur appelant n'a de raison de vouloir l'inverse."""
    return and_(
        models.Operation.amorti.is_(False), filtre_date_periode(annee, mois, semaine)
    )


def filtre_date_periode(
    annee: int, mois: Optional[int], semaine: Optional[int] = None
):
    """La seule contrainte de DATE de la période, sans l'exclusion des opérations
    amorties que `_filtre_periode` y ajoute.

    Séparé parce qu'un calcul en a besoin nu : la VARIATION BRUTE compte une
    dépense amortie au mois où l'argent est sorti, pour son montant entier (cf.
    get_variation_brute). Tous les autres agrégats de période veulent l'exclusion
    et passent donc par `_filtre_periode`."""
    if mois is None:
        return func.strftime("%Y", models.Operation.date) == f"{annee:04d}"
    if semaine is None:
        return func.strftime("%Y-%m", models.Operation.date) == f"{annee:04d}-{mois:02d}"
    debut, fin = _bornes_semaine(annee, mois, semaine)
    return and_(models.Operation.date >= debut, models.Operation.date <= fin)


# ---------- Amortissement sur plusieurs mois ----------
#
# Une opération amortie n'existe qu'en un seul exemplaire (cf. models.Operation)
# : ni occurrences générées, ni montant redécoupé en base. Ce sont les agrégats
# de période qui, en les rencontrant, n'en prennent qu'une fraction — celle des
# mois d'amortissement qui tombent dans la période affichée.
#
# Ne sont concernés que les agrégats de PÉRIODE (histogramme des dépenses par
# catégorie, KPI entrées / sorties / différence). Les soldes du haut de page
# n'en tiennent aucun compte, et ne le doivent pas : ils disent où en sont
# réellement les comptes, or l'argent est bien parti en une fois.


def _index_mois(d: date_type) -> int:
    """Numérote les mois d'affilée depuis l'an 0, pour que deux mois se
    comparent et se soustraient sans se soucier du passage d'année."""
    return d.year * 12 + d.month


def _bornes_periode_en_mois(annee: int, mois: Optional[int]) -> tuple[int, int]:
    """Premier et dernier mois de la période affichée, en index de mois."""
    if mois is None:
        return _index_mois(date_type(annee, 1, 1)), _index_mois(date_type(annee, 12, 1))
    borne = _index_mois(date_type(annee, mois, 1))
    return borne, borne


def _filtre_periode_amortie(annee: int, mois: Optional[int]):
    """Les opérations amorties dont la plage recoupe la période — le pendant de
    _filtre_periode pour elles.

    Le chevauchement se teste en SQL (deux comparaisons de dates) plutôt qu'en
    Python : c'est ce qui évite de charger toutes les opérations amorties de la
    base à chaque affichage du dashboard. Les bornes sont normalisées au 1er du
    mois (cf. schemas.OperationBase), la comparaison au premier et au dernier
    jour de la période est donc exacte."""
    debut_periode = date_type(annee, 1 if mois is None else mois, 1)
    fin_periode = fin_de_periode(annee, mois)
    return and_(
        models.Operation.amorti.is_(True),
        models.Operation.amortissement_debut <= fin_periode,
        models.Operation.amortissement_fin >= debut_periode,
    )


def part_amortie(operation: models.Operation, annee: int, mois: Optional[int]) -> float:
    """Quelle FRACTION du montant d'une opération amortie revient à la période
    (0 si elle n'y déborde pas, 1 si toute sa plage y tient).

    Une fraction plutôt qu'un montant : l'appelant décide de ce qu'il étale.
    L'histogramme n'impute pas le montant d'une dépense remboursable mais son
    reste à charge (montant − montant dû) ; renvoyer ici un montant tout fait
    aurait obligé à traiter ce cas deux fois, ou à l'oublier une fois.

    En vue annuelle, la période compte douze mois : un amortissement à cheval
    sur deux années n'apporte à chacune que les mois qui lui reviennent — c'est
    exactement ce que la vue annuelle doit montrer."""
    nb_mois = operation.amortissement_nb_mois
    if not nb_mois:
        return 0.0
    debut_periode, fin_periode = _bornes_periode_en_mois(annee, mois)
    debut_amortissement = _index_mois(operation.amortissement_debut)
    fin_amortissement = _index_mois(operation.amortissement_fin)
    mois_couverts = min(fin_amortissement, fin_periode) - max(
        debut_amortissement, debut_periode
    ) + 1
    if mois_couverts <= 0:
        return 0.0
    return mois_couverts / nb_mois


# UNE OPÉRATION DÉCOUPÉE N'A PAS DE CATÉGORIE, et c'est ce qui rend tout ce
# fichier juste sans le réécrire : `categorie_id` passe à NULL dès qu'elle porte
# des parts (cf. models.OperationDecoupe), donc les quatre jointures internes
# sur `categorie` ci-dessous l'écartent d'elles-mêmes. Il ne restait qu'à
# AJOUTER ce que ses parts apportent — d'où les trois fonctions qui suivent,
# chacune le pendant exact d'une agrégation existante.
#
# Rien à faire du côté des FLUX (cf. get_flux_periode) ni des SOLDES : ils
# somment `Operation.montant` sans jamais passer par la catégorie, et la somme
# des parts vaut ce montant. C'est précisément l'intérêt du garde-fou : sans
# lui, l'histogramme et le total des sorties posé juste au-dessus auraient
# cessé de tomber d'accord.
#
# LA BASE IMPOSABLE D'UNE PART EST SON MONTANT, sans exception. Seul le type
# `classique` se découpe (cf. crud.erreur_decoupes), et c'est justement celui
# pour lequel _base_imposable rend le montant tel quel : il n'y a donc aucun
# `montant_du` à répartir entre les parts, et pas de second cas à tenir
# d'accord avec le premier.


def _sommes_decoupes_par_categorie(
    db: Session,
    annee: int,
    mois: Optional[int],
    statut: Statut,
    monnaie_id: int,
    semaine: Optional[int] = None,
) -> dict:
    """Ce que les PARTS des opérations découpées non amorties apportent à la
    période, par catégorie."""
    lignes = (
        db.query(
            models.Categorie.nom,
            func.sum(models.OperationDecoupe.montant).label("total"),
        )
        .join(
            models.Operation,
            models.OperationDecoupe.operation_id == models.Operation.id,
        )
        .join(
            models.Categorie,
            models.OperationDecoupe.categorie_id == models.Categorie.id,
        )
        .filter(
            models.Operation.sens == Sens.depense,
            models.Operation.statut == statut,
            models.Operation.monnaie_id == monnaie_id,
            _filtre_periode(annee, mois, semaine),
        )
        .group_by(models.Categorie.nom)
        .all()
    )
    return {nom: total or 0.0 for nom, total in lignes}


def _sommes_decoupes_amorties_par_categorie(
    db: Session,
    annee: int,
    mois: Optional[int],
    statut: Statut,
    monnaie_id: int,
    semaine: Optional[int] = None,
) -> dict:
    """Le pendant amorti du précédent : chaque part ne compte que pour la
    fraction de l'amortissement qui tombe dans la période.

    L'AMORTISSEMENT PORTE SUR L'OPÉRATION, PAS SUR LA PART : une facture étalée
    sur douze mois l'est en entier, et chacune de ses parts suit le même
    calendrier. Il n'y a donc rien à décider ici — la même `part_amortie`
    s'applique à chaque part."""
    lignes = (
        db.query(models.Categorie.nom, models.OperationDecoupe.montant, models.Operation)
        .join(
            models.Operation,
            models.OperationDecoupe.operation_id == models.Operation.id,
        )
        .join(
            models.Categorie,
            models.OperationDecoupe.categorie_id == models.Categorie.id,
        )
        .filter(
            models.Operation.sens == Sens.depense,
            models.Operation.statut == statut,
            models.Operation.monnaie_id == monnaie_id,
            _filtre_periode_amortie(annee, mois),
        )
        .all()
    )
    totaux: dict = {}
    prorata = prorata_semaine(annee, mois, semaine)
    for nom, montant, operation in lignes:
        totaux[nom] = (
            totaux.get(nom, 0.0)
            + montant * part_amortie(operation, annee, mois) * prorata
        )
    return totaux


def _sommes_par_categorie(
    db: Session,
    annee: int,
    mois: Optional[int],
    statut: Statut,
    monnaie_id: int,
    semaine: Optional[int] = None,
) -> dict:
    """Pour une période (mois précis, ou année entière si mois=None), un statut
    et une monnaie donnés : somme des opérations classiques + somme (montant -
    montant dû) des dépenses remboursables, par catégorie."""
    filtre_commun = [
        models.Operation.sens == Sens.depense,
        models.Operation.statut == statut,
        models.Operation.monnaie_id == monnaie_id,
        _filtre_periode(annee, mois, semaine),
    ]

    classiques = (
        db.query(models.Categorie.nom, func.sum(models.Operation.montant).label("total"))
        .join(models.Categorie, models.Operation.categorie_id == models.Categorie.id)
        .join(models.TypeOperationDB, models.Operation.type_id == models.TypeOperationDB.id)
        .filter(models.TypeOperationDB.code.notin_(_CODES_REMBOURSABLES), *filtre_commun)
        .group_by(models.Categorie.nom)
        .all()
    )
    remboursables = (
        db.query(
            models.Categorie.nom,
            func.sum(models.Operation.montant - models.Operation.montant_du).label("total"),
        )
        .join(models.Categorie, models.Operation.categorie_id == models.Categorie.id)
        .join(models.TypeOperationDB, models.Operation.type_id == models.TypeOperationDB.id)
        .filter(models.TypeOperationDB.code.in_(_CODES_REMBOURSABLES), *filtre_commun)
        .group_by(models.Categorie.nom)
        .all()
    )

    totaux: dict = {}
    for nom, total in classiques:
        totaux[nom] = totaux.get(nom, 0.0) + (total or 0.0)
    for nom, total in remboursables:
        totaux[nom] = totaux.get(nom, 0.0) + (total or 0.0)
    for nom, total in _sommes_amorties_par_categorie(
        db, annee, mois, statut, monnaie_id, semaine
    ).items():
        totaux[nom] = totaux.get(nom, 0.0) + total
    # Les opérations DÉCOUPÉES, que les deux requêtes ci-dessus n'ont pas vues :
    # leur `categorie_id` est NULL, la jointure interne sur `categorie` les
    # écarte (cf. le commentaire au-dessus de _sommes_decoupes_par_categorie).
    for source in (
        _sommes_decoupes_par_categorie(db, annee, mois, statut, monnaie_id, semaine),
        _sommes_decoupes_amorties_par_categorie(
            db, annee, mois, statut, monnaie_id, semaine
        ),
    ):
        for nom, total in source.items():
            totaux[nom] = totaux.get(nom, 0.0) + total
    return totaux


def _sommes_amorties_par_categorie(
    db: Session,
    annee: int,
    mois: Optional[int],
    statut: Statut,
    monnaie_id: int,
    semaine: Optional[int] = None,
) -> dict:
    """Ce que les opérations AMORTIES apportent à la période, par catégorie —
    le complément de _sommes_par_categorie, qui les exclut (cf. _filtre_periode).

    L'agrégation se fait en Python et non en SQL : la part imputée dépend du
    nombre de mois d'amortissement tombant dans la période, que SQLite ne sait
    calculer qu'au prix d'une arithmétique de dates illisible. Le filtre de
    chevauchement, lui, reste en SQL — c'est lui qui borne le nombre de lignes
    remontées à celles qui pèsent réellement sur la période."""
    lignes = (
        db.query(models.Categorie.nom, models.Operation, models.TypeOperationDB.code)
        .join(models.Categorie, models.Operation.categorie_id == models.Categorie.id)
        .join(models.TypeOperationDB, models.Operation.type_id == models.TypeOperationDB.id)
        .filter(
            models.Operation.sens == Sens.depense,
            models.Operation.statut == statut,
            models.Operation.monnaie_id == monnaie_id,
            _filtre_periode_amortie(annee, mois),
        )
        .all()
    )

    totaux: dict = {}
    prorata = prorata_semaine(annee, mois, semaine)
    for nom, operation, code in lignes:
        # Même base imposable que pour les non amorties (cf. _base_imposable) :
        # le montant, sauf pour une dépense remboursable, dont seule la part
        # restant à ma charge est une dépense.
        base = _base_imposable(operation.montant, operation.montant_du, code)
        totaux[nom] = (
            totaux.get(nom, 0.0)
            + base * part_amortie(operation, annee, mois) * prorata
        )
    return totaux


# Combien de dépenses l'infobulle d'une barre de l'histogramme détaille. Trois :
# assez pour dire ce qui fait le montant de la barre, assez peu pour se lire
# d'un coup d'œil sans que l'infobulle recouvre le graphique.
NB_TOP_DEPENSES = 3


def _base_imposable(montant: float, montant_du: Optional[float], code: str) -> float:
    """Ce qu'une opération apporte à l'histogramme : son montant, sauf pour une
    dépense remboursable, dont seule la part restant à ma charge est une dépense.

    Extrait ici parce que QUATRE calculs doivent s'accorder sur cette règle —
    les sommes par catégorie, leur pendant amorti, le détail par libellé, et le
    total des entrées/sorties. Une infobulle qui compterait le montant entier
    d'une dépense remboursable annoncerait des lignes dont la somme dépasserait
    la barre qu'elles détaillent ; un total des sorties qui le ferait ne
    tomberait jamais d'accord avec l'histogramme posé juste à côté.

    LE PRÊT REÇU N'EST PAS TRAITÉ ICI, alors que c'est l'autre type remboursable.
    Ses intérêts se calculent à l'envers (`montant_du - montant`, cf.
    _INTERETS_PRET) et il n'a AUCUNE catégorie — son type EST sa classification.
    Or les trois appelants de cette fonction partent tous d'une jointure sur
    `categorie` et d'un `sens = dépense` : un prêt n'y arrive jamais. Il compte
    dans sa propre barre (cf. _barre_interets_prets) et nulle part ailleurs. Le
    tester sur `_CODES_REMBOURSABLES`, qui le contient, rendrait donc ici un
    intérêt NÉGATIF le jour où quelqu'un réemploierait cette fonction."""
    if code == TypeOperation.remboursable.value:
        return montant - (montant_du or 0.0)
    return montant


def _fondre_par_libelle(cumuls: dict, categorie: str, nature: str, montant: float) -> None:
    """Ajoute une dépense au cumul {catégorie: {libellé: [montant, nombre]}}.

    LE LIBELLÉ EST PRIS TEL QUEL, aux espaces de bord près : « Café » et
    « CAFE » restent deux dépenses distinctes. C'est la même règle que la
    détection de doublons d'import (cf. import_bancaire.normaliser_pour_
    comparaison) — confondre deux libellés visiblement différents reviendrait à
    décider à la place de l'utilisateur qu'ils n'en font qu'un."""
    libelle = (nature or "").strip()
    par_libelle = cumuls.setdefault(categorie, {})
    entree = par_libelle.setdefault(libelle, [0.0, 0])
    entree[0] += montant
    entree[1] += 1


def _top_depenses_par_categorie(
    db: Session,
    annee: int,
    mois: Optional[int],
    monnaie_id: int,
    semaine: Optional[int] = None,
) -> dict[str, list[dict]]:
    """Les plus grosses dépenses de la période, par catégorie et fondues par
    libellé — ce que montre l'infobulle d'une barre de l'histogramme.

    MÊME PÉRIMÈTRE QUE LA BARRE, ET C'EST TOUT L'ENJEU : mêmes filtres (sens,
    monnaie, période), même base imposable, et les deux statuts confondus —
    réel ET prévisionnel — parce que c'est la hauteur totale de la barre que
    l'infobulle détaille. Ne prendre que le réel aurait fait survoler une barre
    et lire des lignes qui n'en expliquent qu'une partie.

    Les opérations AMORTIES comptent pour leur seule part de la période, comme
    partout ailleurs (cf. part_amortie) : une facture de 1 200 € étalée sur
    douze mois apparaît à 100 € dans le mois qu'on regarde, pas à 1 200 €.

    L'agrégation se fait en Python : fondre par libellé APRÈS avoir appliqué la
    part amortie ne se dit pas en SQL sans réécrire part_amortie en
    arithmétique de dates. Le volume reste celui d'une période (un mois, ou une
    année) pour une seule monnaie."""
    filtre_commun = [
        models.Operation.sens == Sens.depense,
        models.Operation.monnaie_id == monnaie_id,
    ]
    colonnes = (
        models.Categorie.nom,
        models.Operation.nature,
        models.Operation.montant,
        models.Operation.montant_du,
        models.TypeOperationDB.code,
    )

    def requete(filtre_periode):
        return (
            db.query(*colonnes)
            .join(models.Categorie, models.Operation.categorie_id == models.Categorie.id)
            .join(
                models.TypeOperationDB,
                models.Operation.type_id == models.TypeOperationDB.id,
            )
            .filter(filtre_periode, *filtre_commun)
        )

    cumuls: dict = {}
    prorata = prorata_semaine(annee, mois, semaine)
    for categorie, nature, montant, montant_du, code in requete(
        _filtre_periode(annee, mois, semaine)
    ).all():
        _fondre_par_libelle(
            cumuls, categorie, nature, _base_imposable(montant, montant_du, code)
        )

    # Les amorties, avec la même colonne d'opération en plus : part_amortie a
    # besoin de l'objet, pas seulement de ses montants.
    amorties = (
        db.query(models.Categorie.nom, models.Operation, models.TypeOperationDB.code)
        .join(models.Categorie, models.Operation.categorie_id == models.Categorie.id)
        .join(models.TypeOperationDB, models.Operation.type_id == models.TypeOperationDB.id)
        .filter(_filtre_periode_amortie(annee, mois), *filtre_commun)
        .all()
    )
    for categorie, operation, code in amorties:
        part = (
            _base_imposable(operation.montant, operation.montant_du, code)
            * part_amortie(operation, annee, mois)
            * prorata
        )
        _fondre_par_libelle(cumuls, categorie, operation.nature, part)

    # LES PARTS DES OPÉRATIONS DÉCOUPÉES, sous le libellé de leur opération.
    # Une seule dépense qui se retrouve dans trois barres y apparaît trois fois,
    # chaque fois pour ce que cette catégorie lui doit : c'est exactement ce que
    # l'infobulle promet — dire ce qui fait la hauteur de LA barre survolée.
    for filtre_periode, amortir in (
        (_filtre_periode(annee, mois, semaine), False),
        (_filtre_periode_amortie(annee, mois), True),
    ):
        lignes_decoupees = (
            db.query(
                models.Categorie.nom, models.OperationDecoupe.montant, models.Operation
            )
            .join(
                models.Operation,
                models.OperationDecoupe.operation_id == models.Operation.id,
            )
            .join(
                models.Categorie,
                models.OperationDecoupe.categorie_id == models.Categorie.id,
            )
            .filter(filtre_periode, *filtre_commun)
            .all()
        )
        for categorie, montant_part, operation in lignes_decoupees:
            if amortir:
                montant_part *= part_amortie(operation, annee, mois) * prorata
            _fondre_par_libelle(cumuls, categorie, operation.nature, montant_part)

    resultats: dict[str, list[dict]] = {}
    for categorie, par_libelle in cumuls.items():
        classees = sorted(
            (
                {"nature": libelle, "montant": montant, "nombre": nombre}
                for libelle, (montant, nombre) in par_libelle.items()
                # Une catégorie peut porter des lignes à 0 (dépense remboursable
                # intégralement due, amortie hors période) : elles ne détaillent
                # rien et occuperaient une des trois places.
                if montant > 0
            ),
            # Le libellé départage deux montants égaux : sans lui, deux
            # affichages successifs des mêmes données pourraient ne pas donner
            # le même ordre.
            key=lambda d: (-d["montant"], d["nature"]),
        )
        resultats[categorie] = classees[:NB_TOP_DEPENSES]
    return resultats


def _budget_alloue_periode(
    db: Session,
    categorie_id: int,
    annee: int,
    mois: Optional[int],
    monnaie_id: int,
    semaine: Optional[int] = None,
) -> float:
    """Budget d'un mois précis, ou somme des 12 mois de l'année si mois=None
    (vue annuelle) — chaque mois résolu par héritage habituel, dans la monnaie
    demandée (cf. crud.get_budget_categorie).

    EN VUE SEMAINE, LE BUDGET EST DÉCOUPÉ AU PRORATA DES JOURS. Un budget est
    posé pour un MOIS (cf. models.Categorie) : il n'y a pas d'enveloppe
    hebdomadaire à lire quelque part. Le trait rouge d'une semaine dit donc « le
    rythme qu'il faudrait tenir », et non une limite qu'on aurait fixée — c'est
    la seule lecture qui garde la somme des semaines égale au budget du mois."""
    if mois is not None:
        return (
            crud.get_budget_categorie(db, categorie_id, annee, mois, monnaie_id)
            * prorata_semaine(annee, mois, semaine)
        )
    return sum(
        crud.get_budget_categorie(db, categorie_id, annee, m, monnaie_id)
        for m in range(1, 13)
    )


def get_depenses_par_categorie(
    db: Session,
    annee: int,
    mois: Optional[int],
    monnaie_id: int,
    semaine: Optional[int] = None,
):
    """Valeur réelle = opérations classiques (réel) + (montant - montant dû)
    des dépenses remboursables (réel), pour la période et la monnaie données.
    Valeur prévisionnelle = valeur réelle + la même formule en statut
    prévisionnel.

    Toutes les catégories sont concernées : depuis 0019 la table n'en contient
    plus que de vraies (les quatre anciennes catégories système sont devenues
    des types, et leurs opérations n'ont plus de catégorie du tout).

    Sauf celles que l'utilisateur a éteintes (œil de l'onglet Catégories) : le
    filtre est ici, à la source, plutôt que côté frontend, pour que l'échelle de
    l'histogramme se recalcule sur les seules barres montrées — masquer après
    coup aurait laissé une catégorie invisible écraser toutes les autres.

    ET SAUF LES CATÉGORIES D'ENTRÉE (cf. constants.CATEGORIES_SENS_ENTREE). Une
    catégorie dont les opérations sont des ENTRÉES ne peut rien porter ici : les
    sommes ne comptent que le sens « dépense », et c'est ce filtre qui fait que
    la somme des barres vaut exactement le total des sorties affiché juste
    au-dessus. Sa barre restait donc à zéro quoi qu'on y range, avec une
    infobulle annonçant qu'il ne s'y passait rien alors qu'elle pouvait contenir
    tout un salaire. Mieux vaut ne pas la dessiner : l'argent qu'elle porte se
    lit dans « Total entrées », à côté."""
    categories = (
        db.query(models.Categorie)
        .filter(
            models.Categorie.visible_dashboard.is_(True),
            models.Categorie.nom.notin_(CATEGORIES_SENS_ENTREE),
        )
        .order_by(models.Categorie.ordre)
        .all()
    )

    reel = _sommes_par_categorie(db, annee, mois, Statut.reel, monnaie_id, semaine)
    previsionnel_seul = _sommes_par_categorie(
        db, annee, mois, Statut.previsionnel, monnaie_id, semaine
    )
    # Calculé une fois pour toutes les catégories, pas une requête par barre.
    tops = _top_depenses_par_categorie(db, annee, mois, monnaie_id, semaine)

    resultats = []
    for categorie in categories:
        valeur_reelle = reel.get(categorie.nom, 0.0)
        valeur_previsionnelle = valeur_reelle + previsionnel_seul.get(categorie.nom, 0.0)
        resultats.append(
            {
                "categorie": categorie.nom,
                "total_reel": valeur_reelle,
                "total_previsionnel": valeur_previsionnelle,
                "budget_alloue": _budget_alloue_periode(
                    db, categorie.id, annee, mois, monnaie_id, semaine
                ),
                "couleur_index": categorie.couleur_index,
                "top_depenses": tops.get(categorie.nom, []),
            }
        )

    ligne_prets = _barre_interets_prets(db, annee, mois, monnaie_id, semaine)
    if ligne_prets is not None:
        resultats.append(ligne_prets)
    return resultats


def get_depenses_par_semaine(db: Session, annee: int, mois: int, monnaie_id: int):
    """L'histogramme du mois DÉPLIÉ : une liste de dépenses par catégorie pour
    chaque semaine, plus la moyenne de ces semaines.

    POURQUOI UNE ROUTE À PART, ET PAS UNE `vue="semaine"` DE PLUS SUR LE
    DASHBOARD. Seul l'histogramme se déplie. Les soldes, le total des avoirs et
    la répartition des comptes n'ont pas de version hebdomadaire à offrir — un
    solde ne se découpe pas, il est ce qu'il est à une date. Faire descendre la
    vue du dashboard entier à la semaine aurait obligé chacun de ces chiffres à
    répondre à une question qu'on ne lui pose pas.

    LA SOMME DES SEMAINES VAUT LE MOIS, au centime : les semaines partitionnent
    les jours (cf. semaines_du_mois), et ce qui n'a pas de jour — part amortie,
    budget — est réparti au prorata des jours (cf. prorata_semaine). C'est le
    même invariant que celui des découpes d'opération, et pour la même raison :
    deux chiffres posés l'un à côté de l'autre qui ne s'accordent pas ne passent
    pas pour une imprécision, mais pour une erreur.

    LA MOYENNE EST CELLE DES SEMAINES AFFICHÉES — leur somme divisée par leur
    nombre, dernière semaine courte comprise. C'est le seul calcul qu'on puisse
    vérifier à l'œil sur les barres d'à côté ; normaliser sur sept jours
    donnerait un chiffre plus juste « par semaine pleine », mais qui ne
    correspondrait à aucune moyenne des barres qu'on regarde. L'écran dit sur
    combien de semaines elle porte.
    """
    bornes = semaines_du_mois(annee, mois)
    semaines = [
        {
            "numero": rang,
            "jour_debut": debut,
            "jour_fin": fin,
            "depenses": get_depenses_par_categorie(
                db, annee, mois, monnaie_id, semaine=rang
            ),
        }
        for rang, (debut, fin) in enumerate(bornes, start=1)
    ]

    # La moyenne, catégorie par catégorie. On repart des lignes déjà calculées
    # plutôt que d'interroger la base une fois de plus : c'est ce qui garantit
    # que la barre « Moyenne » est bien la moyenne des barres montrées, et non
    # un second calcul qui pourrait en différer.
    nombre = len(semaines) or 1
    moyenne: dict[str, dict] = {}
    for semaine in semaines:
        for ligne in semaine["depenses"]:
            cumul = moyenne.setdefault(
                ligne["categorie"],
                {
                    "categorie": ligne["categorie"],
                    "total_reel": 0.0,
                    "total_previsionnel": 0.0,
                    "budget_alloue": 0.0,
                    "couleur_index": ligne["couleur_index"],
                    # Le détail par libellé n'a pas de sens sur une moyenne : une
                    # dépense moyenne n'a pas eu lieu. L'infobulle dira
                    # simplement qu'il n'y a rien à détailler.
                    "top_depenses": [],
                },
            )
            for champ in ("total_reel", "total_previsionnel", "budget_alloue"):
                cumul[champ] += ligne[champ] / nombre

    return {
        "annee": annee,
        "mois": mois,
        "semaines": semaines,
        "moyenne": list(moyenne.values()),
    }


# La couleur de la barre des intérêts. Prise EN FIN de palette (cf. app.js,
# PALETTE_CATEGORIES) : cette barre n'est pas une catégorie, et lui donner
# l'index 0 la ferait porter la couleur de la première catégorie créée.
_COULEUR_INTERETS_PRETS = 7


def _barre_interets_prets(db: Session, annee, mois, monnaie_id, semaine=None):
    """La barre « Intérêts de prêts », ou None s'il n'y a rien à montrer.

    CE QU'ELLE EST. Pas une catégorie : aucune ligne de `categorie` ne porte ce
    nom, on ne peut ni la renommer, ni lui poser un budget, ni l'éteindre. C'est
    une barre de plus, qui existe pour que l'histogramme dise la MÊME CHOSE que
    le total des sorties — lequel compte les intérêts d'un prêt
    (cf. get_flux_periode). Sans elle, chaque prêt rouvrirait l'écart entre les
    deux chiffres que tout le reste de ce module s'emploie à tenir fermé.

    DEUX CONDITIONS, et les deux comptent :

      - l'extension « Prêts » tourne. Sinon les intérêts ne sont pas non plus
        dans les sorties, et une barre sans rien en face n'aurait pas de sens ;
      - le total n'est pas nul. Un prêt sans intérêts (on rend exactement ce
        qu'on a reçu, `montant_du == montant`) ne coûte rien : afficher une
        barre à zéro ajouterait une colonne vide à chaque histogramme de
        quiconque a emprunté.
    """
    if not extensions.est_active(EXTENSION_PRETS):
        return None

    def _interets(statut):
        total = (
            db.query(func.sum(_INTERETS_PRET))
            .join(models.Compte, models.Operation.compte_id == models.Compte.id)
            .join(models.TypeCompte, models.Compte.type_id == models.TypeCompte.id)
            .join(
                models.TypeOperationDB,
                models.Operation.type_id == models.TypeOperationDB.id,
            )
            .filter(
                models.TypeOperationDB.code == TypeOperation.pret.value,
                models.Operation.monnaie_id == monnaie_id,
                models.Operation.statut == statut,
                models.TypeCompte.nom.notin_(TYPES_COMPTE_HORS_COURANT),
                _filtre_periode(annee, mois, semaine),
            )
            .scalar()
        )
        return total or 0.0

    reel = _interets(Statut.reel)
    previsionnel = reel + _interets(Statut.previsionnel)
    if abs(previsionnel) < 0.005 and abs(reel) < 0.005:
        return None

    return {
        "categorie": LIBELLE_INTERETS_PRETS,
        "total_reel": reel,
        "total_previsionnel": previsionnel,
        # AUCUN BUDGET : on ne se fixe pas une enveloppe d'intérêts, on les
        # subit. Un trait rouge sur cette barre n'aurait rien à annoncer.
        "budget_alloue": 0.0,
        "couleur_index": _COULEUR_INTERETS_PRETS,
        # Le détail par libellé n'a pas de sens ici : chaque prêt est une ligne,
        # et son libellé est déjà celui de la barre.
        "top_depenses": [],
    }


def get_flux_periode(
    db: Session, annee: int, mois: Optional[int], monnaie_id: int
) -> dict:
    """Ce qui est entré, ce qui est sorti, et leur différence, pour la période
    et la monnaie données — réel et prévisionnel confondus.

    LES VIREMENTS INTERNES SONT EXCLUS PAR CONSTRUCTION, et c'est le point de
    cette fonction : le filtre porte sur `sens IN (entrée, dépense)`, il ne se
    contente pas d'espérer qu'aucun transfert ne s'y glisse. Un virement déplace
    de l'argent entre mes propres comptes sans changer mon solde global ; le
    compter d'un côté sans l'autre gonflerait aussi bien les entrées que les
    sorties. La version précédente soustrayait deux totaux groupés par sens sans
    filtrer : elle donnait le bon résultat tant que rien d'autre que
    `transfert_*` ne portait un virement, mais rien ne le garantissait — le
    calcul dépendait d'une absence plutôt que d'une règle.

    Les achats et ventes de titres sont eux aussi des `transfert_*` (acheter des
    titres convertit l'argent, ne le dépense pas) : ils tombent sous le même
    filtre.

    Les comptes d'épargne et de placements sont écartés à part : ils ne
    reçoivent que des virements internes, donc rien qui puisse compter ici, mais
    les exclure explicitement garde le total cohérent avec les KPI de solde, qui
    les excluent aussi.

    Renvoie un dict plutôt qu'un seul nombre : le dashboard affiche désormais
    les deux composantes à côté de leur différence, et les recalculer
    séparément ouvrirait la porte à trois chiffres qui ne s'accordent pas.

    Les opérations amorties comptent pour leur seule part de la période (cf.
    part_amortie), et non pour leur montant entier au mois où l'argent est
    sorti : ces trois chiffres répondent à « qu'est-ce que cette période me
    coûte », pas à « qu'est-ce qui est passé sur le compte » — sans quoi
    amortir n'aurait d'effet que sur l'histogramme, qui cesserait aussitôt de
    s'accorder avec le total des sorties juste à côté.

    CE QUI EST COMPTÉ, ET POUR COMBIEN — la règle tient en trois lignes :

      - une opération CLASSIQUE, pour son montant entier ;
      - une DÉPENSE REMBOURSABLE, pour `montant - montant_du` : seulement ce qui
        reste à ma charge une fois qu'on m'aura rendu le reste ;
      - un PRÊT REÇU, pour `montant_du - montant` : ses seuls intérêts, et du
        côté des SORTIES — l'argent emprunté n'est pas un revenu, il faudra le
        rendre ; ce qu'il coûte est l'écart entre les deux.

    TOUT LE RESTE EST ÉCARTÉ. Les virements internes et les mouvements de titres
    par le filtre de sens (déplacer de l'argent n'est ni le gagner ni le
    dépenser), et les deux types de RÈGLEMENT — remboursement reçu, remboursement
    de prêt — par `TYPES_HORS_FLUX` : ils soldent une dette déjà comptée quand
    elle est née, et la compter deux fois donnerait un total faux dans le mauvais
    sens.

    `montant_du` est ce qu'on doit AU DÉPART, figé — pas `montant_a_rembourser`,
    qui décroît au fil des règlements. C'est le bon des deux : ce qu'une dépense
    coûte vraiment ne dépend pas de la date à laquelle on est remboursé.
    """
    filtres_communs = [
        models.Operation.monnaie_id == monnaie_id,
        models.TypeCompte.nom.notin_(TYPES_COMPTE_HORS_COURANT),
        models.Operation.sens.in_([Sens.entree, Sens.depense]),
        # Les RÈGLEMENTS ne comptent jamais : ils soldent une dette déjà comptée
        # quand elle est née (cf. constants.TYPES_HORS_FLUX).
        models.TypeOperationDB.code.notin_(_CODES_HORS_FLUX),
    ]

    def _requete(montant):
        return (
            db.query(models.Operation.sens, func.sum(montant).label("total"))
            .join(models.Compte, models.Operation.compte_id == models.Compte.id)
            .join(models.TypeCompte, models.Compte.type_id == models.TypeCompte.id)
            .join(
                models.TypeOperationDB,
                models.Operation.type_id == models.TypeOperationDB.id,
            )
            .filter(_filtre_periode(annee, mois), *filtres_communs)
            .group_by(models.Operation.sens)
        )

    est_pret = models.TypeOperationDB.code == TypeOperation.pret.value
    est_depense_remboursable = and_(
        models.TypeOperationDB.code == TypeOperation.remboursable.value,
        models.Operation.sens == Sens.depense,
    )

    totaux: dict = {}

    # 1. Tout le reste, pour son montant entier.
    for sens, total in _requete(models.Operation.montant).filter(
        ~est_pret, ~est_depense_remboursable
    ):
        totaux[sens] = totaux.get(sens, 0.0) + (total or 0.0)

    # 2. Une dépense remboursable ne pèse que pour ce qui reste à ma charge.
    for sens, total in _requete(
        models.Operation.montant - models.Operation.montant_du
    ).filter(est_depense_remboursable):
        totaux[sens] = totaux.get(sens, 0.0) + (total or 0.0)

    # 3. Un prêt reçu pèse pour ses SEULS INTÉRÊTS, et du côté des SORTIES.
    #
    # L'argent d'un prêt n'est pas un revenu : il faudra le rendre. Ce qu'il
    # coûte vraiment, c'est l'écart entre ce qu'on rendra et ce qu'on a reçu —
    # `montant_du - montant`, qui est positif puisqu'on ne rembourse jamais
    # moins qu'on n'a emprunté — c'est même la borne que le type impose à la
    # saisie (cf. crud.erreur_montant_du). C'est un COÛT, il va donc aux
    # sorties, alors
    # même que l'opération porte `sens = entrée` : c'est la seule endroit de ce
    # calcul où le sens de l'écriture ne décide pas de la colonne.
    #
    # SEULEMENT SI L'EXTENSION TOURNE. Sans elle, aucun écran n'explique d'où
    # sortent ces intérêts, et l'histogramme ne porte pas la barre qui leur
    # correspond : les compter creuserait un écart au lieu d'en combler un.
    if extensions.est_active(EXTENSION_PRETS):
        interets = _requete(_INTERETS_PRET).filter(est_pret)
        for _sens, total in interets:
            totaux[Sens.depense] = totaux.get(Sens.depense, 0.0) + (total or 0.0)

    amorties = (
        db.query(models.Operation)
        .join(models.Compte, models.Operation.compte_id == models.Compte.id)
        .join(models.TypeCompte, models.Compte.type_id == models.TypeCompte.id)
        .join(
            models.TypeOperationDB,
            models.Operation.type_id == models.TypeOperationDB.id,
        )
        .filter(_filtre_periode_amortie(annee, mois), *filtres_communs)
        .all()
    )
    for operation in amorties:
        code = operation.type_operation.code
        if code == TypeOperation.pret.value:
            # Même règle qu'au point 3, part amortie comprise.
            if not extensions.est_active(EXTENSION_PRETS):
                continue
            base = max(0.0, operation.montant_du - operation.montant)
            sens_impute = Sens.depense
        else:
            base = _base_imposable(operation.montant, operation.montant_du, code)
            sens_impute = operation.sens
        totaux[sens_impute] = totaux.get(sens_impute, 0.0) + (
            base * part_amortie(operation, annee, mois)
        )

    entrees = totaux.get(Sens.entree, 0.0)
    sorties = totaux.get(Sens.depense, 0.0)
    return {"entrees": entrees, "sorties": sorties, "variation": entrees - sorties}


def get_variation_brute(
    db: Session, annee: int, mois: Optional[int], monnaie_id: int
) -> float:
    """De combien les comptes courants ont bougé sur la période, SANS RIEN
    ÉTALER NI RETRANCHER.

    CE QU'ELLE RÉPOND, et que rien d'autre ne répondait : « qu'est-ce qui est
    passé sur le compte ce mois-ci ». Pas « qu'est-ce que ce mois me coûte » —
    c'est la question de `get_flux_periode`, et les deux ne se confondent pas :

      - une DÉPENSE AMORTIE compte ici en ENTIER, au mois où l'argent est sorti.
        L'étalement dit ce qu'elle pèse, pas ce qui a quitté le compte ;
      - une DÉPENSE REMBOURSABLE compte pour son montant ENTIER, sans retrancher
        ce qu'on nous rendra. L'argent est parti, même s'il reviendra ;
      - un PRÊT REÇU compte pour son montant entier, du côté des entrées : cet
        argent est bien arrivé, même s'il faudra le rendre ;
      - un RÈGLEMENT (remboursement reçu, remboursement de prêt) compte lui
        aussi, alors que les flux l'écartent : il solde une dette déjà comptée,
        mais il déplace bel et bien de l'argent.

    CE QUI RESTE ÉCARTÉ, et pour la même raison que dans les flux : les
    VIREMENTS INTERNES et les mouvements de titres (`sens IN (entrée, dépense)`
    ne les retient pas) — déplacer de l'argent entre ses propres comptes ne fait
    bouger aucun total ; et les comptes d'ÉPARGNE et de PLACEMENTS, pour que ce
    chiffre reste comparable au « Solde total » posé à côté de lui, qui les
    exclut déjà.

    RÉEL ET PRÉVISIONNEL CONFONDUS, comme les flux : une opération à venir dans
    le mois en fait partie.
    """
    lignes = (
        db.query(models.Operation.sens, func.sum(models.Operation.montant))
        .join(models.Compte, models.Operation.compte_id == models.Compte.id)
        .join(models.TypeCompte, models.Compte.type_id == models.TypeCompte.id)
        .filter(
            # `filtre_date_periode` et non `_filtre_periode` : les opérations
            # amorties comptent ici, à leur date et pour leur montant entier.
            filtre_date_periode(annee, mois),
            models.Operation.monnaie_id == monnaie_id,
            models.TypeCompte.nom.notin_(TYPES_COMPTE_HORS_COURANT),
            models.Operation.sens.in_([Sens.entree, Sens.depense]),
        )
        .group_by(models.Operation.sens)
        .all()
    )
    totaux = {sens: (total or 0.0) for sens, total in lignes}
    return totaux.get(Sens.entree, 0.0) - totaux.get(Sens.depense, 0.0)


def get_variation_previsionnelle(
    db: Session, annee: int, mois: Optional[int], monnaie_id: int
) -> float:
    """Entrées moins sorties de la période : d'un coup d'œil, la période
    s'annonce-t-elle positive ou négative. Voir get_flux_periode, dont ce n'est
    qu'une des trois valeurs."""
    return get_flux_periode(db, annee, mois, monnaie_id)["variation"]


def get_total_a_rembourser(db: Session) -> dict:
    """Net de ce qu'on me doit, PAR MONNAIE : dépenses remboursables encore
    dues, moins ce que je dois moi-même sur des prêts qu'on m'a accordés. Une
    dette en dollars ne compense pas une créance en euros, d'où le dict."""
    totaux: dict = {}

    du_par_depenses = (
        db.query(
            models.Operation.monnaie_id, func.sum(models.Operation.montant_a_rembourser)
        )
        .join(models.TypeOperationDB, models.Operation.type_id == models.TypeOperationDB.id)
        .filter(
            models.Operation.sens == Sens.depense,
            models.TypeOperationDB.code == TypeOperation.remboursable.value,
            models.Operation.statut == Statut.reel,
        )
        .group_by(models.Operation.monnaie_id)
        .all()
    )
    for monnaie_id, total in du_par_depenses:
        totaux[monnaie_id] = totaux.get(monnaie_id, 0.0) + (total or 0.0)

    du_par_prets = (
        db.query(
            models.Operation.monnaie_id, func.sum(models.Operation.montant_a_rembourser)
        )
        .join(models.TypeOperationDB, models.Operation.type_id == models.TypeOperationDB.id)
        .filter(models.TypeOperationDB.code == TypeOperation.pret.value)
        .group_by(models.Operation.monnaie_id)
        .all()
    )
    for monnaie_id, total in du_par_prets:
        totaux[monnaie_id] = totaux.get(monnaie_id, 0.0) - (total or 0.0)

    return totaux
