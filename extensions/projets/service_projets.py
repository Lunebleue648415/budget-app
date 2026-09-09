"""Ce qu'un projet a coûté.

UNE SOMME AFFICHÉE, JAMAIS UNE DONNÉE. Rien de ce qui se calcule ici n'entre
dans un solde, un budget ou un KPI du dashboard : c'est ce qui permet à une même
opération d'appartenir à trois projets sans être comptée trois fois nulle part.
Un projet est une VUE sur des opérations qui existent sans lui.

PAR MONNAIE, ET JAMAIS AUTREMENT, comme partout ailleurs dans l'application :
l'app ne stocke aucun taux de change, additionner des euros et des dollars
n'aurait aucun sens (cf. services/soldes.py). Un voyage payé moitié en euros,
moitié en francs suisses a donc deux lignes de totaux, pas un total faux.

LE SENS DÉCIDE, PAS LE TYPE, et exactement comme dans le calcul des soldes
(`soldes._solde_delta`) : une sortie est une sortie, qu'elle soit une dépense
ordinaire ou un virement vers un autre compte. C'est la seule convention qui
rende le total d'un projet lisible comme « ce que ce projet a fait bouger ». Un
virement interne dont les DEUX écritures sont versées dans le projet s'y annule
donc de lui-même, ce qui est bien ce qu'il vaut : l'argent n'a pas quitté le
patrimoine.
"""
from app.constants import CATEGORIES_SENS_ENTREE, Sens
from app.services.soldes import NB_TOP_DEPENSES

# Les deux sens qui font sortir de l'argent, et les deux qui en font entrer.
# Repris de services/soldes._solde_delta : un projet doit compter comme le reste
# de l'application, ou son total ne voudra rien dire à côté d'un solde.
SENS_SORTANTS = {Sens.depense, Sens.transfert_sortant}
SENS_ENTRANTS = {Sens.entree, Sens.transfert_entrant}


def totaux_par_monnaie(sous_filtre) -> list[dict]:
    """[{monnaie_id, monnaie_nom, monnaie_symbole, depenses, entrees, solde}]

    `depenses` et `entrees` sont des valeurs ABSOLUES — c'est ainsi qu'on les
    lit (« 1 240 € dépensés »). `solde` est leur différence, donc négatif pour un
    projet qui n'a fait que coûter : le cas ordinaire d'un voyage.

    Les monnaies sortent dans l'ordre de leur nom : une liste de totaux qui
    change de place d'une visite à l'autre se relit mal.
    """
    par_monnaie: dict[int, dict] = {}
    for operation in sous_filtre.operations:
        entree = par_monnaie.setdefault(
            operation.monnaie_id,
            {
                "monnaie_id": operation.monnaie_id,
                "monnaie_nom": operation.monnaie.nom,
                "monnaie_symbole": operation.monnaie.symbole,
                "depenses": 0.0,
                "entrees": 0.0,
                "solde": 0.0,
            },
        )
        if operation.sens in SENS_SORTANTS:
            entree["depenses"] += operation.montant
        elif operation.sens in SENS_ENTRANTS:
            entree["entrees"] += operation.montant

    for entree in par_monnaie.values():
        entree["solde"] = entree["entrees"] - entree["depenses"]

    return sorted(par_monnaie.values(), key=lambda e: e["monnaie_nom"])


# Le libellé d'une dépense qu'aucune catégorie ne classe. Une opération d'un
# projet peut parfaitement ne pas en porter : un virement sortant, un prêt, une
# ligne qu'on n'a pas encore rangée. Les laisser de côté aurait fait un
# histogramme dont la somme ne vaut plus le total affiché juste au-dessus.
CATEGORIE_SANS = "Sans catégorie"


def _lignes_de_depense(operation):
    """Ce qu'une opération apporte à l'histogramme : (catégorie, montant), une
    fois par part si elle est DÉCOUPÉE.

    L'opération découpée ne porte plus de catégorie (`categorie_id` est NULL,
    cf. models.OperationDecoupe) : ce sont ses parts qui SONT sa classification,
    et les compter en plus d'elle-même la ferait peser deux fois. C'est la même
    règle que dans services/soldes.py, appliquée ici à une liste d'opérations
    déjà en mémoire plutôt qu'en SQL — un projet en compte quelques dizaines, on
    ne fait pas de requête pour ça."""
    if operation.decoupes:
        return [
            (part.categorie.nom, part.montant, operation.nature)
            for part in operation.decoupes
        ]
    nom = operation.categorie.nom if operation.categorie else CATEGORIE_SANS
    return [(nom, operation.montant, operation.nature)]


def depenses_par_categorie(sous_filtre) -> dict[int, list[dict]]:
    """L'histogramme d'un projet, PAR MONNAIE : {monnaie_id: [barres]}.

    LA MÊME FORME QUE CELLE DU DASHBOARD (`schemas.DepenseParCategorie`), et
    c'est tout l'intérêt : l'écran le dessine avec la fonction d'histogramme du
    noyau, sans une ligne de rendu en double. D'où `total_previsionnel` égal à
    `total_reel` et `budget_alloue` à zéro — un projet n'a ni prévisionnel ni
    enveloppe, et ces deux valeurs sont ce que le rendu attend pour ne dessiner
    ni barre pâle ni trait rouge.

    SEULES LES SORTIES, comme pour le total « dépensé » juste à côté (cf.
    SENS_SORTANTS) : une entrée versée dans un projet est un remboursement ou
    une recette, elle n'a rien à faire dans un graphe de dépenses — elle se lit
    dans le total des entrées.

    L'ORDRE EST CELUI DES MONTANTS, du plus lourd au plus léger : un projet n'a
    pas la liste ordonnée des catégories du dashboard à respecter, et ce qu'on
    vient y chercher est ce qui a coûté le plus.

    LA COULEUR VIENT DE LA CATÉGORIE (`couleur_index`), comme partout : la même
    catégorie garde sa teinte du dashboard au projet. « Sans catégorie » n'en a
    pas — elle prend l'index de fin de palette, celui que le noyau réserve déjà
    aux barres qui ne sont pas des catégories.
    """
    par_monnaie: dict[int, dict[str, dict]] = {}
    for operation in sous_filtre.operations:
        if operation.sens not in SENS_SORTANTS:
            continue
        barres = par_monnaie.setdefault(operation.monnaie_id, {})
        for nom, montant, nature in _lignes_de_depense(operation):
            # Une catégorie d'ENTRÉE ne peut rien porter ici (les sorties sont
            # seules comptées) : c'est le même écart que le dashboard refuse de
            # dessiner, une barre à zéro qui n'apprend rien.
            if nom in CATEGORIES_SENS_ENTREE:
                continue
            barre = barres.setdefault(
                nom,
                {
                    "categorie": nom,
                    "total_reel": 0.0,
                    "total_previsionnel": 0.0,
                    "budget_alloue": 0.0,
                    "couleur_index": _couleur_index(operation, nom),
                    "top_depenses": [],
                },
            )
            barre["total_reel"] += montant
            barre["total_previsionnel"] += montant
            _fondre(barre["top_depenses"], nature, montant)

    return {
        monnaie_id: [
            {**barre, "top_depenses": _top(barre["top_depenses"])}
            for barre in sorted(
                barres.values(), key=lambda b: b["total_reel"], reverse=True
            )
        ]
        for monnaie_id, barres in par_monnaie.items()
    }


# L'index de palette des barres qui ne sont PAS une catégorie — le même que
# celui de la barre « Intérêts de prêts » du dashboard (cf.
# services/soldes._COULEUR_INTERETS_PRETS) : la fin de la palette, pour ne pas
# emprunter la couleur de la première catégorie créée.
_COULEUR_SANS_CATEGORIE = 7


def _couleur_index(operation, nom_categorie: str) -> int:
    if nom_categorie == CATEGORIE_SANS:
        return _COULEUR_SANS_CATEGORIE
    if operation.decoupes:
        for part in operation.decoupes:
            if part.categorie.nom == nom_categorie:
                return part.categorie.couleur_index
    return operation.categorie.couleur_index if operation.categorie else 0


def _fondre(lignes: list[dict], nature: str, montant: float) -> None:
    """Fond une dépense dans son homologue de même libellé, comme le fait
    l'infobulle du dashboard (cf. soldes._fondre_par_libelle) : trois passages
    « Hôtel » à 90 € forment une ligne de 270 €, et non trois lignes de 90."""
    libelle = (nature or "").strip()
    for ligne in lignes:
        if ligne["nature"] == libelle:
            ligne["montant"] += montant
            ligne["nombre"] += 1
            return
    lignes.append({"nature": libelle, "montant": montant, "nombre": 1})


def _top(lignes: list[dict]) -> list[dict]:
    """Les plus grosses, du plus lourd au plus léger — le libellé départageant
    deux montants égaux, pour que deux lectures donnent le même ordre."""
    return sorted(lignes, key=lambda d: (-d["montant"], d["nature"]))[:NB_TOP_DEPENSES]


def lire_sous_filtre(sous_filtre) -> dict:
    """Le projet tel que l'écran le lit : ses champs, son compte d'opérations et
    ses totaux.

    Le nombre d'opérations et les totaux sont CALCULÉS à chaque lecture, jamais
    stockés. Une colonne « total » aurait dû être maintenue à chaque création,
    modification et suppression d'opération — y compris depuis les écrans qui
    ignorent tout des projets (l'import, les virements, la récurrence) — pour ne
    rien apprendre qu'une somme ne dise déjà.
    """
    par_monnaie = depenses_par_categorie(sous_filtre)
    totaux = totaux_par_monnaie(sous_filtre)
    for total in totaux:
        total["depenses_par_categorie"] = par_monnaie.get(total["monnaie_id"], [])
    return {
        "id": sous_filtre.id,
        "nom": sous_filtre.nom,
        "description": sous_filtre.description,
        "ordre": sous_filtre.ordre,
        "nombre_operations": len(sous_filtre.operations),
        # L'histogramme est rangé DANS le total de sa monnaie : c'est déjà la
        # ligne par monnaie que l'écran affiche, et deux listes parallèles à
        # réaccorder par identifiant n'auraient été qu'une occasion de plus de
        # les laisser diverger.
        "totaux": totaux,
    }
