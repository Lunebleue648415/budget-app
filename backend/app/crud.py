import calendar
import uuid
from datetime import date as date_type, datetime, timedelta
from typing import Optional

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from . import models, schemas
from .constants import (
    CATEGORIES_SENS_ENTREE,
    CATEGORIE_AUTRES,
    COLONNES_IMPORT_PAR_DEFAUT,
    COLONNES_IMPORT_PLACEMENT_PAR_DEFAUT,
    COLONNES_IMPORT_POSITION_PAR_DEFAUT,
    MONNAIE_INITIALE_NOM,
    MONNAIE_INITIALE_SYMBOLE,
    NB_MAX_PARTS_DECOUPE,
    NOMS_TYPES_INITIAUX,
    ORDRE_TYPES,
    TYPES_INTERNES,
    TYPES_REGLEMENT,
    TYPES_REMBOURSABLES,
    TYPES_SENS_ENTREE,
    DomaineImport,
    Frequence,
    ModeComparaison,
    ModeLecturePlacement,
    Sens,
    SensAction,
    Statut,
    TypeOperation,
)


# ---------- Monnaies ----------
#
# Aucun taux de change n'est stocké nulle part : l'app ne convertit jamais, elle
# calcule tout séparément par monnaie (cf. services/soldes.py).


def get_monnaies(db: Session) -> list[models.Monnaie]:
    return db.query(models.Monnaie).order_by(models.Monnaie.ordre, models.Monnaie.id).all()


def get_monnaie(db: Session, monnaie_id: int) -> Optional[models.Monnaie]:
    return db.query(models.Monnaie).filter(models.Monnaie.id == monnaie_id).first()


def get_monnaie_by_nom(db: Session, nom: str) -> Optional[models.Monnaie]:
    return db.query(models.Monnaie).filter(models.Monnaie.nom == nom).first()


def create_monnaie(db: Session, nom: str, symbole: str) -> models.Monnaie:
    ordre_max = db.query(func.max(models.Monnaie.ordre)).scalar()
    monnaie = models.Monnaie(
        nom=nom, symbole=symbole, ordre=(ordre_max + 1) if ordre_max is not None else 0
    )
    db.add(monnaie)
    db.commit()
    db.refresh(monnaie)
    return monnaie


def update_monnaie(
    db: Session,
    monnaie: models.Monnaie,
    *,
    nom: Optional[str] = None,
    symbole: Optional[str] = None,
) -> models.Monnaie:
    if nom is not None:
        monnaie.nom = nom
    if symbole is not None:
        monnaie.symbole = symbole
    db.commit()
    db.refresh(monnaie)
    return monnaie


# Les quatre tables qui PORTENT une monnaie. Une monnaie qui n'apparaît dans
# aucune d'elles n'existe que comme entrée de la table `monnaie` : personne ne
# s'en sert, et rien ne dépend d'elle.
_MODELES_PORTANT_UNE_MONNAIE = (
    models.CompteMonnaie,
    models.Operation,
    models.CategorieBudgetMensuel,
    models.Action,
)


def monnaie_est_utilisee(db: Session, monnaie_id: int) -> bool:
    """Une monnaie encore portée par un compte, une opération, un budget ou un
    titre ne peut pas être supprimée : les montants concernés deviendraient
    illisibles."""
    for modele in _MODELES_PORTANT_UNE_MONNAIE:
        if db.query(modele).filter(modele.monnaie_id == monnaie_id).first() is not None:
            return True
    return False


def monnaies_utilisees(db: Session) -> set[int]:
    """Les monnaies RÉELLEMENT en service, par opposition à celles qui n'ont
    été que créées.

    La distinction est ce qui permet à l'extension « Monnaies » de dire si on
    peut l'éteindre sans rien rendre illisible (cf. son backend.py) : avoir
    ajouté le dollar sans jamais s'en servir laisse l'application mono-devise,
    et il n'y a alors aucune raison de retenir l'utilisateur.

    Un `None` ne compte pas : une ligne sans monnaie n'en désigne aucune."""
    utilisees: set[int] = set()
    for modele in _MODELES_PORTANT_UNE_MONNAIE:
        utilisees.update(
            identifiant
            for (identifiant,) in db.query(modele.monnaie_id).distinct().all()
            if identifiant is not None
        )
    return utilisees


def delete_monnaie(db: Session, monnaie: models.Monnaie) -> None:
    db.delete(monnaie)
    db.commit()


def seed_monnaie_initiale(db: Session) -> models.Monnaie:
    """Crée l'euro si la base n'a aucune monnaie (bases créées hors migration :
    tests, nouvelle base de dev). Idempotent."""
    existante = get_monnaies(db)
    if existante:
        return existante[0]
    return create_monnaie(db, MONNAIE_INITIALE_NOM, MONNAIE_INITIALE_SYMBOLE)


def get_categories(db: Session):
    return db.query(models.Categorie).order_by(models.Categorie.ordre).all()


def get_categorie(db: Session, categorie_id: int):
    return db.query(models.Categorie).filter(models.Categorie.id == categorie_id).first()


def get_categorie_by_nom(db: Session, nom: str):
    return db.query(models.Categorie).filter(models.Categorie.nom == nom).first()


def _prochain_couleur_index(db: Session) -> int:
    """Le plus petit index de palette que personne n'occupe.

    Pas `max + 1` : sans cela, créer et supprimer des catégories à répétition
    ferait grimper l'index indéfiniment, et deux catégories finiraient par se
    retrouver de la même couleur alors que la palette avait de la place. Le plus
    petit index libre garantit qu'une couleur n'est reprise QUE si celle qui la
    portait a disparu — la règle que cette colonne existe pour tenir."""
    pris = {index for (index,) in db.query(models.Categorie.couleur_index).all()}
    index = 0
    while index in pris:
        index += 1
    return index


def create_categorie(db: Session, categorie: schemas.CategorieCreate) -> models.Categorie:
    ordre_max = db.query(func.max(models.Categorie.ordre)).scalar() or 0
    db_categorie = models.Categorie(
        nom=categorie.nom,
        ordre=ordre_max + 1,
        couleur_index=_prochain_couleur_index(db),
    )
    db.add(db_categorie)
    db.commit()
    db.refresh(db_categorie)
    return db_categorie


def set_visibilite_dashboard_categorie(
    db: Session, db_categorie: models.Categorie, visible: bool
) -> models.Categorie:
    db_categorie.visible_dashboard = visible
    db.commit()
    db.refresh(db_categorie)
    return db_categorie


def get_budgets_explicites_categorie(db: Session, categorie_id: int, monnaie_id: int):
    return (
        db.query(models.CategorieBudgetMensuel)
        .filter(
            models.CategorieBudgetMensuel.categorie_id == categorie_id,
            models.CategorieBudgetMensuel.monnaie_id == monnaie_id,
        )
        .order_by(models.CategorieBudgetMensuel.annee, models.CategorieBudgetMensuel.mois)
        .all()
    )


def get_budget_categorie(
    db: Session, categorie_id: int, annee: int, mois: int, monnaie_id: int
) -> float:
    """Budget résolu pour (annee, mois) DANS une monnaie : la dernière entrée
    explicite à cette date ou avant (héritage en cascade), sinon 0.0.

    L'héritage ne traverse jamais les monnaies : un budget en dollars n'hérite
    que d'un mois précédent lui aussi en dollars."""
    entree = (
        db.query(models.CategorieBudgetMensuel)
        .filter(
            models.CategorieBudgetMensuel.categorie_id == categorie_id,
            models.CategorieBudgetMensuel.monnaie_id == monnaie_id,
            or_(
                models.CategorieBudgetMensuel.annee < annee,
                and_(
                    models.CategorieBudgetMensuel.annee == annee,
                    models.CategorieBudgetMensuel.mois <= mois,
                ),
            ),
        )
        .order_by(
            models.CategorieBudgetMensuel.annee.desc(),
            models.CategorieBudgetMensuel.mois.desc(),
        )
        .first()
    )
    return entree.montant if entree else 0.0


def budget_categorie_est_explicite(
    db: Session, categorie_id: int, annee: int, mois: int, monnaie_id: int
) -> bool:
    return (
        db.query(models.CategorieBudgetMensuel)
        .filter(
            models.CategorieBudgetMensuel.categorie_id == categorie_id,
            models.CategorieBudgetMensuel.monnaie_id == monnaie_id,
            models.CategorieBudgetMensuel.annee == annee,
            models.CategorieBudgetMensuel.mois == mois,
        )
        .first()
        is not None
    )


def set_budget_categorie(
    db: Session, categorie_id: int, annee: int, mois: int, monnaie_id: int, montant: float
) -> None:
    entree = (
        db.query(models.CategorieBudgetMensuel)
        .filter(
            models.CategorieBudgetMensuel.categorie_id == categorie_id,
            models.CategorieBudgetMensuel.monnaie_id == monnaie_id,
            models.CategorieBudgetMensuel.annee == annee,
            models.CategorieBudgetMensuel.mois == mois,
        )
        .first()
    )
    if entree:
        entree.montant = montant
    else:
        db.add(
            models.CategorieBudgetMensuel(
                categorie_id=categorie_id,
                monnaie_id=monnaie_id,
                annee=annee,
                mois=mois,
                montant=montant,
            )
        )
    db.commit()


def reordonner_categories(db: Session, ids_ordonnes: list[int]) -> None:
    """Applique un nouvel ordre d'affichage (glisser-déposer) aux catégories
    listées, dans l'ordre donné. Les ids omis gardent leur ordre actuel."""
    for position, categorie_id in enumerate(ids_ordonnes):
        db.query(models.Categorie).filter(models.Categorie.id == categorie_id).update(
            {"ordre": position}
        )
    db.commit()


def rename_categorie(db: Session, db_categorie: models.Categorie, nom: str) -> models.Categorie:
    """Renomme une catégorie. RIEN D'AUTRE NE BOUGE.

    Les opérations pointent sur la LIGNE, pas sur son libellé : les
    réétiqueter n'a donc aucun coût, et leur classement, leurs budgets et leur
    historique suivent le nouveau nom sans qu'on y touche. C'est précisément ce
    qu'une colonne texte sur chaque opération n'aurait pas permis.
    """
    db_categorie.nom = nom
    db.commit()
    db.refresh(db_categorie)
    return db_categorie


def migrer_operations_vers_autres(db: Session, categorie_a_supprimer: models.Categorie) -> None:
    categorie_autres = get_categorie_by_nom(db, CATEGORIE_AUTRES)
    db.query(models.Operation).filter(
        models.Operation.categorie_id == categorie_a_supprimer.id
    ).update({"categorie_id": categorie_autres.id})
    db.commit()


def delete_categorie(db: Session, db_categorie: models.Categorie) -> None:
    db.delete(db_categorie)
    db.commit()


def _sens_pour_type(code: str, categorie_nom: Optional[str]) -> Sens:
    """Le type prime : un remboursement reçu et un prêt reçu sont des entrées
    quelle que soit la catégorie (ils n'en ont d'ailleurs plus). Pour les deux
    types à catégorie libre, le sens reste dérivé de la catégorie.

    Les virements ne passent pas par ici : leur sens (transfert_sortant ou
    transfert_entrant) est imposé à la création, le type seul ne permettant pas
    de trancher entre les deux.

    D'où le refus explicite plus bas plutôt qu'un `return Sens.depense` par
    défaut : sans lui, un virement dont personne n'aurait imposé le sens serait
    compté comme une dépense, faussant à la fois le solde du compte et la
    variation de la période — une erreur muette, que rien à l'écran ne
    distinguerait d'une vraie dépense.
    """
    if TypeOperation(code) == TypeOperation.virement:
        raise ValueError(
            "Le sens d'un virement interne ne se déduit pas de son type : il doit "
            "être imposé (transfert_sortant ou transfert_entrant) par l'appelant."
        )
    if TypeOperation(code) in TYPES_SENS_ENTREE:
        return Sens.entree
    if categorie_nom is not None and categorie_nom in CATEGORIES_SENS_ENTREE:
        return Sens.entree
    return Sens.depense


def get_types_operation(db: Session) -> list[models.TypeOperationDB]:
    return db.query(models.TypeOperationDB).order_by(models.TypeOperationDB.ordre).all()


def get_type_operation(db: Session, type_id: int) -> Optional[models.TypeOperationDB]:
    return (
        db.query(models.TypeOperationDB).filter(models.TypeOperationDB.id == type_id).first()
    )


def get_type_operation_par_code(db: Session, code: str) -> Optional[models.TypeOperationDB]:
    return (
        db.query(models.TypeOperationDB).filter(models.TypeOperationDB.code == code).first()
    )


def id_type_par_code(db: Session) -> dict:
    """Résolution code -> id, chargée une fois par requête plutôt qu'à chaque ligne."""
    return {t.code: t.id for t in db.query(models.TypeOperationDB).all()}


def seed_types_operation(db: Session) -> None:
    """Crée les types manquants (bases créées hors migration : tests, nouvelle
    base de dev). Idempotent."""
    for ordre, type_operation in enumerate(ORDRE_TYPES):
        if get_type_operation_par_code(db, type_operation.value) is None:
            db.add(
                models.TypeOperationDB(
                    code=type_operation.value,
                    nom=NOMS_TYPES_INITIAUX[type_operation],
                    ordre=ordre,
                    interne=type_operation in TYPES_INTERNES,
                )
            )
    db.commit()


def renommer_type_operation(
    db: Session, type_operation: models.TypeOperationDB, nom: str
) -> models.TypeOperationDB:
    type_operation.nom = nom
    db.commit()
    db.refresh(type_operation)
    return type_operation


def get_types_compte(db: Session):
    return db.query(models.TypeCompte).order_by(models.TypeCompte.systeme.desc(), models.TypeCompte.nom).all()


def get_type_compte(db: Session, type_compte_id: int):
    return db.query(models.TypeCompte).filter(models.TypeCompte.id == type_compte_id).first()


def get_type_compte_by_nom(db: Session, nom: str):
    return db.query(models.TypeCompte).filter(models.TypeCompte.nom == nom).first()


def type_compte_est_utilise(db: Session, type_compte_id: int) -> bool:
    return (
        db.query(models.Compte).filter(models.Compte.type_id == type_compte_id).first()
        is not None
    )


def delete_type_compte(db: Session, db_type_compte: models.TypeCompte) -> None:
    db.delete(db_type_compte)
    db.commit()


def get_comptes(db: Session):
    """Dans l'ordre choisi par l'utilisateur (cf. models.Compte.ordre), le nom
    départageant deux comptes de même position. Cet ordre vaut au sein d'un
    type : partout où les comptes s'affichent, ils sont groupés par type."""
    return db.query(models.Compte).order_by(models.Compte.ordre, models.Compte.nom).all()


def reordonner_comptes(db: Session, ids_ordonnes: list[int]) -> None:
    """Applique le nouvel ordre d'affichage issu d'un glisser-déposer. La liste
    reçue est celle d'UN type (le geste ne réordonne que la carte survolée) :
    les comptes des autres types gardent leur position, sans conséquence
    puisque l'ordre ne se lit qu'à l'intérieur d'un type."""
    for position, compte_id in enumerate(ids_ordonnes):
        db.query(models.Compte).filter(models.Compte.id == compte_id).update(
            {"ordre": position}
        )
    db.commit()


def ordre_suivant_dans_type(db: Session, type_id: int) -> int:
    """Position d'un compte qui arrive dans un type : à la fin, pour qu'une
    création ou un changement de type ne bouscule pas l'ordre en place."""
    ordre_max = (
        db.query(func.max(models.Compte.ordre))
        .filter(models.Compte.type_id == type_id)
        .scalar()
    )
    return (ordre_max + 1) if ordre_max is not None else 0


def get_compte(db: Session, compte_id: int):
    return db.query(models.Compte).filter(models.Compte.id == compte_id).first()


def get_compte_by_nom(db: Session, nom: str):
    return db.query(models.Compte).filter(models.Compte.nom == nom).first()


def _appliquer_monnaies_compte(
    db_compte: models.Compte, monnaies: list[schemas.CompteMonnaieInput]
) -> None:
    """Remplace la liste des monnaies du compte. L'ordre reçu fait foi : la
    première est celle proposée par défaut à la saisie. Les lignes existantes
    sont réutilisées quand la monnaie est conservée, pour ne pas perdre leur id
    (et donc leur solde initial) sur un simple réordonnancement."""
    existantes = {lien.monnaie_id: lien for lien in db_compte.monnaies}
    nouvelles = []
    for position, entree in enumerate(monnaies):
        lien = existantes.get(entree.monnaie_id)
        if lien is None:
            lien = models.CompteMonnaie(monnaie_id=entree.monnaie_id)
        lien.solde_initial = entree.solde_initial
        lien.ordre = position
        nouvelles.append(lien)
    # delete-orphan sur la relation : les lignes absentes de la nouvelle liste
    # sont supprimées au flush.
    db_compte.monnaies = nouvelles


def create_compte(db: Session, compte: schemas.CompteCreate) -> models.Compte:
    db_compte = models.Compte(
        nom=compte.nom,
        type_id=compte.type_id,
        ordre=ordre_suivant_dans_type(db, compte.type_id),
    )
    _appliquer_monnaies_compte(db_compte, compte.monnaies)
    db.add(db_compte)
    db.commit()
    db.refresh(db_compte)
    return db_compte


def update_compte(
    db: Session, db_compte: models.Compte, updates: schemas.CompteUpdate
) -> models.Compte:
    data = updates.model_dump(exclude_unset=True)
    monnaies = data.pop("monnaies", None)
    # Changer de type, c'est arriver dans une autre liste : le compte s'y range
    # en dernier plutôt que de garder une position qui appartenait à l'ancien
    # type (deux comptes se retrouveraient sinon à la même place). Le
    # glisser-déposer précise ensuite la position exacte voulue, via
    # /comptes/reordonner.
    nouveau_type = data.get("type_id")
    if nouveau_type is not None and nouveau_type != db_compte.type_id:
        db_compte.ordre = ordre_suivant_dans_type(db, nouveau_type)
    for field, value in data.items():
        setattr(db_compte, field, value)
    if monnaies is not None:
        _appliquer_monnaies_compte(
            db_compte, [schemas.CompteMonnaieInput(**item) for item in monnaies]
        )
    db.commit()
    db.refresh(db_compte)
    return db_compte


def compte_monnaies_utilisees(db: Session, compte_id: int) -> set:
    """Monnaies dans lesquelles ce compte porte déjà au moins une opération :
    les retirer de sa liste rendrait ces montants orphelins."""
    rows = (
        db.query(models.Operation.monnaie_id)
        .filter(models.Operation.compte_id == compte_id)
        .distinct()
        .all()
    )
    return {row[0] for row in rows}


def delete_compte(db: Session, db_compte: models.Compte) -> None:
    db.delete(db_compte)
    db.commit()


def get_operations(
    db: Session,
    compte_id: Optional[int] = None,
    categorie_id: Optional[int] = None,
    statut: Optional[str] = None,
    date_debut: Optional[date_type] = None,
    date_fin: Optional[date_type] = None,
    montant_min: Optional[float] = None,
    montant_max: Optional[float] = None,
    paires_virement: bool = False,
):
    """Chaque filtre est facultatif ; ceux qui valent None ne bornent rien.

    Les deux bornes de montant portent sur `montant`, qui est TOUJOURS positif :
    c'est le sens qui dit d'où va l'argent (cf. models.Operation). « Entre 50 et
    100 » attrape donc aussi bien une dépense de 80 € qu'une entrée de 80 €, ce
    qui est ce qu'on cherche en filtrant sur un ordre de grandeur — le signe se
    choisit déjà par l'onglet.

    `paires_virement` : UN VIREMENT EST INDIVISIBLE. Ses deux écritures ne sont
    pas deux opérations qui se ressemblent, c'est UN mouvement décrit des deux
    côtés — et aucun filtre ne s'applique pareil aux deux. Filtrer sur le compte
    émetteur ne retenait que sa jambe, filtrer sur un montant ne retenait qu'un
    côté d'un virement avec change : l'écran recevait alors une moitié de
    virement et l'affichait comme un virement à qui il manque un compte. C'est
    le drapeau que pose l'écran Opérations, qui affiche les virements PAR PAIRE
    et ne peut rien faire d'une moitié. Les autres appelants ne le posent pas :
    ils lisent des opérations, pas des virements, et une jambe hors filtre n'a
    rien à faire dans leur liste.
    """
    query = db.query(models.Operation)
    if compte_id is not None:
        query = query.filter(models.Operation.compte_id == compte_id)
    if categorie_id is not None:
        query = query.filter(models.Operation.categorie_id == categorie_id)
    if statut is not None:
        query = query.filter(models.Operation.statut == statut)
    if date_debut is not None:
        query = query.filter(models.Operation.date >= date_debut)
    if date_fin is not None:
        query = query.filter(models.Operation.date <= date_fin)
    if montant_min is not None:
        query = query.filter(models.Operation.montant >= montant_min)
    if montant_max is not None:
        query = query.filter(models.Operation.montant <= montant_max)
    tri = (models.Operation.date.desc(), models.Operation.id.desc())
    operations = query.order_by(*tri).all()
    if not paires_virement:
        return operations

    # Les jambes manquantes des virements déjà retenus. Une seconde requête
    # plutôt qu'un OR dans la première : le filtre porte sur les opérations, et
    # on ne sait quels virements compléter qu'une fois qu'on sait lesquels sont
    # retenus.
    virement_ids = {op.virement_id for op in operations if op.virement_id is not None}
    if not virement_ids:
        return operations
    deja = {op.id for op in operations}
    manquantes = (
        db.query(models.Operation)
        .filter(
            models.Operation.virement_id.in_(virement_ids),
            models.Operation.id.notin_(deja) if deja else True,
        )
        .all()
    )
    if not manquantes:
        return operations
    # Retriées ensemble : les jambes ramenées ici doivent se ranger à leur date
    # parmi les autres, et non s'empiler à la fin.
    return sorted(
        operations + manquantes, key=lambda op: (op.date, op.id), reverse=True
    )


def get_operation(db: Session, operation_id: int):
    return db.query(models.Operation).filter(models.Operation.id == operation_id).first()


# LE MONTANT DÛ N'A PAS LA MÊME BORNE DES DEUX CÔTÉS.
#
# `montant_du` porte le même nom pour les deux types remboursables, mais il n'y
# décrit pas la même chose, et sa borne y est exactement inverse :
#
#   - DÉPENSE REMBOURSABLE : j'ai avancé `montant`, on m'en rendra `montant_du`.
#     On ne peut pas me rendre plus que je n'ai avancé, donc
#     `montant_du <= montant`.
#   - PRÊT REÇU : on m'a remis `montant`, je rendrai `montant_du`. On ne rend
#     jamais moins qu'on n'a reçu, donc `montant_du >= montant` — et l'écart
#     entre les deux est l'INTÉRÊT du prêt (cf. services/soldes._INTERETS_PRET).
#
# Cette règle vivait dans schemas.OperationBase, qui ne connaît que `type_id` et
# ne peut donc pas savoir de quel type il s'agit : elle n'y tenait qu'une des
# deux moitiés — celle de la dépense remboursable, appliquée AUSSI aux prêts,
# qui ne pouvaient par conséquent porter aucun intérêt. Elle vit ici, où le
# `code` du type est connu.
#
# Écart en deçà duquel deux montants sont le même : une saisie au centime passe
# par des flottants, où 100.0 peut arriver en 99.99999999999999.
TOLERANCE_MONTANT = 1e-9


def erreur_montant_du(
    code: str, montant: float, montant_du: Optional[float]
) -> Optional[str]:
    """La phrase à rendre à l'utilisateur si `montant_du` sort de la borne de ce
    type d'opération, ou None si tout va bien.

    Rendue en 400 par les routes (cf. routers/operations.py). Les appels
    internes, eux, passent par `_borner_montant_du`, qui ramène la valeur dans
    ses bornes plutôt que de refuser."""
    if montant_du is None:
        return None
    type_operation = TypeOperation(code)
    if type_operation == TypeOperation.pret:
        if montant_du < montant - TOLERANCE_MONTANT:
            return (
                "Le montant à rembourser d'un prêt ne peut pas être inférieur au "
                "montant prêté : on rend au moins ce qu'on a reçu."
            )
        return None
    if montant_du > montant + TOLERANCE_MONTANT:
        return "montant_du ne peut pas dépasser montant"
    return None


def _borner_montant_du(code: str, montant: float, montant_du: float) -> float:
    """Ramène `montant_du` dans la borne de son type (cf. le commentaire
    ci-dessus). Le dernier filet des appels internes — import bancaire, écriture
    directe par `crud` — que ne traverse aucune validation de route."""
    if TypeOperation(code) == TypeOperation.pret:
        return max(montant, montant_du)
    return max(0.0, min(montant_du, montant))


def _resoudre_montants_remboursement(
    code: str,
    montant: float,
    montant_du: Optional[float],
    montant_a_rembourser: Optional[float],
) -> tuple[float, float]:
    """Les deux montants de dette d'une opération, dans leur forme finale.

    Non renseignés, ils se déduisent : ce qui est dû vaut le montant entier (une
    dépense qu'on se fera intégralement rendre, un prêt sans intérêts), et le
    reste à rembourser part de ce qui est dû."""
    if TypeOperation(code) not in TYPES_REMBOURSABLES:
        return 0.0, 0.0
    montant_du_resolu = montant if montant_du is None else montant_du
    montant_du_resolu = _borner_montant_du(code, montant, montant_du_resolu)
    montant_a_rembourser_resolu = (
        montant_du_resolu if montant_a_rembourser is None else montant_a_rembourser
    )
    return montant_du_resolu, min(montant_a_rembourser_resolu, montant_du_resolu)


def _normaliser_amortissement(db_operation: models.Operation) -> None:
    """Remet les bornes d'amortissement dans leur seule forme valide : effacées
    si la case est décochée, calées sur le 1er du mois sinon.

    Sur la création, schemas.OperationBase s'en charge ; une modification, elle,
    n'est qu'un fragment (OperationUpdate) et ne peut rien valider de l'état
    final. Décocher « amortie » sans effacer les bornes laisserait des dates
    qu'aucun calcul ne lit plus mais que le formulaire réafficherait à la
    prochaine ouverture."""
    if not db_operation.amorti:
        db_operation.amortissement_debut = None
        db_operation.amortissement_fin = None
        return
    if db_operation.amortissement_debut is not None:
        db_operation.amortissement_debut = db_operation.amortissement_debut.replace(day=1)
    if db_operation.amortissement_fin is not None:
        db_operation.amortissement_fin = db_operation.amortissement_fin.replace(day=1)


def _normaliser_categorie_selon_type(db: Session, type_code: str, categorie_id):
    """Une catégorie n'a de sens que pour les deux types qui l'admettent ; pour
    les autres, le type EST la classification. Renvoie (categorie_id, nom)."""
    from .constants import TYPES_AVEC_CATEGORIE_LIBRE

    if TypeOperation(type_code) not in TYPES_AVEC_CATEGORIE_LIBRE:
        return None, None
    categorie = get_categorie(db, categorie_id) if categorie_id is not None else None
    return (categorie.id if categorie else None), (categorie.nom if categorie else None)


def erreur_decoupes(code: str, montant: float, decoupes) -> Optional[str]:
    """Ce qui interdit cette découpe, ou None si elle est valable.

    LE GARDE-FOU CENTRAL : la somme des parts vaut le montant, exactement. Sans
    lui, l'histogramme cesserait de totaliser les mêmes sorties que les KPI
    posés juste à côté, et rien à l'écran ne dirait laquelle des deux valeurs
    croire.

    Écrit ici, à côté de `erreur_montant_du`, et pour la même raison : les
    routes en font un 400 lisible, et `_appliquer_decoupes` s'en sert comme
    dernier filet pour les appels internes (import bancaire) que ne traverse
    aucune validation de route.

    LA TOLÉRANCE EST D'UN DEMI-CENTIME. Les montants sont des flottants, et
    30 + 90 ne fait pas toujours exactement 120 en binaire ; exiger l'égalité
    stricte aurait refusé des découpes justes. Un demi-centime est en dessous
    de ce que l'app sait afficher, donc de ce que l'utilisateur peut vouloir
    dire.
    """
    if not decoupes:
        return None
    if TypeOperation(code) != TypeOperation.classique:
        return (
            "seule une opération classique peut être découpée : les autres "
            "types portent une catégorie imposée, un montant dû ou une "
            "contrepartie, que la découpe ne saurait pas répartir"
        )
    if len(decoupes) < 2:
        return (
            "une découpe compte au moins deux parts ; pour une seule "
            "catégorie, choisis-la directement"
        )
    if len(decoupes) > NB_MAX_PARTS_DECOUPE:
        return f"une découpe ne peut pas dépasser {NB_MAX_PARTS_DECOUPE} parts"
    categories = [part.categorie_id for part in decoupes]
    if len(set(categories)) != len(categories):
        return "une même catégorie ne peut pas apparaître deux fois dans la découpe"
    total = sum(part.montant for part in decoupes)
    if abs(total - montant) > 0.005:
        return (
            f"la somme des parts ({total:.2f}) doit valoir le montant de "
            f"l'opération ({montant:.2f})"
        )
    return None


def _appliquer_decoupes(db_operation: models.Operation, code: str, decoupes) -> None:
    """Remplace les parts d'une opération par celles fournies, ou les efface.

    `code` est passé plutôt que lu sur l'opération : à la création, la relation
    `type_operation` n'est pas encore chargée (la ligne n'est même pas dans la
    session), et `db_operation.type_code` échouerait.

    LA CATÉGORIE UNIQUE ET LES PARTS S'EXCLUENT : poser une découpe met
    `categorie_id` à NULL, et la retirer laisse l'opération sans catégorie —
    l'écran en redemande alors une, comme pour toute opération classique qui
    n'en a pas encore. Garder l'ancienne catégorie sous la découpe aurait
    ressuscité un classement que l'utilisateur avait remplacé.

    UNE DÉCOUPE INVALIDE EST IGNORÉE, PAS RATTRAPÉE. Contrairement à
    `montant_du`, qu'on peut ramener dans sa borne sans rien inventer, il n'y a
    aucune façon honnête de corriger des parts qui ne totalisent pas le
    montant : redresser la dernière reviendrait à classer de l'argent dans une
    catégorie que personne n'a choisie. Les routes refusent déjà le cas en 400
    (cf. erreur_decoupes) ; pour un appel interne, l'opération reste simplement
    non découpée.
    """
    db_operation.decoupes.clear()
    if not decoupes:
        return
    if erreur_decoupes(code, db_operation.montant, decoupes):
        return
    db_operation.categorie_id = None
    for rang, part in enumerate(decoupes):
        db_operation.decoupes.append(
            models.OperationDecoupe(
                categorie_id=part.categorie_id, montant=part.montant, ordre=rang
            )
        )


def create_operation(db: Session, operation: schemas.OperationCreate) -> models.Operation:
    type_operation = get_type_operation(db, operation.type_id)
    code = type_operation.code
    data = operation.model_dump(exclude={"operations_remboursees", "decoupes"})

    # UNE OPÉRATION DÉCOUPÉE N'A PAS DE CATÉGORIE : effacée AVANT le calcul du
    # sens, qui la lit. Un payload qui porterait les deux (un écran qui bascule
    # d'un mode à l'autre sans vider le champ qu'il quitte) aurait sinon pris
    # son sens d'une catégorie que l'opération n'allait pas garder.
    if operation.decoupes:
        data["categorie_id"] = None
    data["categorie_id"], nom_categorie = _normaliser_categorie_selon_type(
        db, code, data.get("categorie_id")
    )
    data["sens"] = _sens_pour_type(code, nom_categorie)

    # `remboursable` n'est plus une colonne : il découle du type (dépense
    # remboursable et prêt reçu, exactement les deux cas historiques). Le `code`
    # est passé tel quel plutôt qu'un booléen : les deux types remboursables ne
    # bornent pas `montant_du` du même côté (cf. _resoudre_montants_remboursement).
    data["montant_du"], data["montant_a_rembourser"] = _resoudre_montants_remboursement(
        code, data["montant"], data["montant_du"], data["montant_a_rembourser"]
    )

    db_operation = models.Operation(**data)
    # Les parts AVANT le premier commit : une opération qui naîtrait découpée
    # ET catégorisée aurait existé, ne serait-ce qu'un instant, dans l'état que
    # la table interdit.
    _appliquer_decoupes(db_operation, code, operation.decoupes)
    db.add(db_operation)
    db.commit()
    db.refresh(db_operation)

    if TypeOperation(code) in TYPES_REGLEMENT and operation.operations_remboursees:
        montants = {item.operation_id: item.montant for item in operation.operations_remboursees}
        set_operations_remboursees(db, db_operation, montants)
        db.refresh(db_operation)

    return db_operation


def update_operation(
    db: Session, db_operation: models.Operation, updates: schemas.OperationUpdate
) -> models.Operation:
    etait_remboursable = db_operation.remboursable
    # Changer de type peut rendre caducs les liens de remboursement déjà posés
    # — état capturé ici, avant mutation, pour les nettoyer plus bas.
    etait_reglement = TypeOperation(db_operation.type_code) in TYPES_REGLEMENT
    etait_virement = TypeOperation(db_operation.type_code) == TypeOperation.virement
    # Un modèle de récurrence (pas une occurrence générée) qui redevient
    # ponctuel doit nettoyer ses occurrences futures (cf. _arreter_recurrence,
    # appelé plus bas une fois le nouvel état de `recurrente` connu).
    etait_modele_recurrent = db_operation.recurrente and db_operation.recurrence_parent_id is None
    data = updates.model_dump(
        exclude_unset=True, exclude={"operations_remboursees", "decoupes"}
    )
    montant_du_fourni = "montant_du" in data
    montant_a_rembourser_fourni = "montant_a_rembourser" in data
    for field, value in data.items():
        setattr(db_operation, field, value)

    _normaliser_amortissement(db_operation)

    # Le type est relu par son id plutôt que via la relation : celle-ci reste
    # en cache après un simple setattr sur `type_id`, et renverrait l'ancien
    # code.
    code = get_type_operation(db, db_operation.type_id).code

    # LES PARTS AVANT LA CATÉGORIE ET LE SENS, qui se calculent tous deux
    # d'après elle : une opération découpée n'a pas de catégorie, et son sens ne
    # doit donc pas venir de celle qu'elle vient de perdre.
    #
    # `None` = ne touche à rien, `[]` = efface. Une découpe devenue invalide —
    # le montant a changé, ou le type est sorti de `classique` — est abandonnée
    # plutôt que rattrapée : il n'existe aucune façon honnête de décider quelle
    # part encaisse la différence. Les routes refusent déjà le cas en 400 ; ceci
    # ne concerne que les appels internes.
    if updates.decoupes is not None:
        _appliquer_decoupes(db_operation, code, updates.decoupes)
    elif db_operation.decoupes and erreur_decoupes(
        code, db_operation.montant, db_operation.decoupes
    ):
        db_operation.decoupes.clear()
    if db_operation.decoupes:
        db_operation.categorie_id = None

    db_operation.categorie_id, nom_categorie = _normaliser_categorie_selon_type(
        db, code, db_operation.categorie_id
    )

    # Un virement conserve son sens (transfert_sortant / transfert_entrant) :
    # le recalculer le ramènerait à "dépense" et fausserait le solde du compte.
    if not (etait_virement and TypeOperation(code) == TypeOperation.virement):
        db_operation.sens = _sens_pour_type(code, nom_categorie)

    est_remboursable = TypeOperation(code) in TYPES_REMBOURSABLES
    if not est_remboursable:
        db_operation.montant_du = 0.0
        db_operation.montant_a_rembourser = 0.0
    else:
        if not etait_remboursable:
            # Vient de devenir remboursable : montants par défaut si non précisés.
            if not montant_du_fourni:
                db_operation.montant_du = db_operation.montant
            if not montant_a_rembourser_fourni:
                db_operation.montant_a_rembourser = db_operation.montant_du
        elif montant_du_fourni and not montant_a_rembourser_fourni:
            # LA DETTE CHANGE DE TAILLE, ET RIEN N'EN A ENCORE ÉTÉ RÉGLÉ.
            #
            # La route interdit de toucher au montant dû dès qu'un remboursement
            # y est lié (409, cf. routers/operations.py) : arriver ici avec un
            # nouveau montant dû veut donc dire qu'aucun règlement n'est encore
            # intervenu, et que tout reste à rembourser. Sans ce report, faire
            # passer une dette de 40 à 110 laissait « reste à rembourser » à 40 :
            # l'opération s'éteignait 70 avant d'être soldée.
            db_operation.montant_a_rembourser = db_operation.montant_du
        # Changer de type change la BORNE de `montant_du` (une dépense
        # remboursable reclassée en prêt passe d'un plafond à un plancher), et
        # changer le montant peut l'en faire sortir. La route refuse déjà les
        # deux (400) ; ceci tient l'invariant pour les appels directs.
        db_operation.montant_du = _borner_montant_du(
            code, db_operation.montant, db_operation.montant_du
        )
        if db_operation.montant_a_rembourser > db_operation.montant_du:
            db_operation.montant_a_rembourser = db_operation.montant_du

    depenses_a_recalculer = _nettoyer_liens_devenus_caducs(
        db,
        db_operation,
        code_actuel=code,
        etait_reglement=etait_reglement,
        etait_remboursable=etait_remboursable,
        est_remboursable=est_remboursable,
    )

    db.commit()
    db.refresh(db_operation)

    for depense_id in depenses_a_recalculer:
        _recalculer_montant_a_rembourser(db, depense_id)

    if updates.operations_remboursees is not None:
        montants = {item.operation_id: item.montant for item in updates.operations_remboursees}
        set_operations_remboursees(db, db_operation, montants)
        db.refresh(db_operation)

    if etait_modele_recurrent and not db_operation.recurrente:
        _arreter_recurrence(db, db_operation)

    return db_operation


def _nettoyer_liens_devenus_caducs(
    db: Session,
    db_operation: models.Operation,
    *,
    code_actuel: str,
    etait_reglement: bool,
    etait_remboursable: bool,
    est_remboursable: bool,
) -> list[int]:
    """Supprime les RemboursementLien qu'un changement de type rend absurdes,
    et renvoie les dépenses dont le reste dû doit être recalculé.

    Sans ce nettoyage, changer le type d'une opération laissait des liens
    pendants : un règlement repassé en dépense classique continuait de "régler"
    des dettes, et une dette repassée en non-remboursable (montants remis à 0)
    restait la cible de remboursements qui ne correspondaient plus à rien.

    Les liens ne sont supprimés que dans le sens devenu invalide : une
    opération peut légitimement être à la fois dette et règlement d'une autre.
    """
    depenses_a_recalculer: list[int] = []

    # N'est plus un règlement : ses liens sortants (ce qu'elle remboursait)
    # n'ont plus lieu d'être, et les dettes visées redeviennent dues.
    if etait_reglement and TypeOperation(code_actuel) not in TYPES_REGLEMENT:
        depenses_a_recalculer = [
            row[0]
            for row in db.query(models.RemboursementLien.operation_depense_id)
            .filter(models.RemboursementLien.operation_remboursement_id == db_operation.id)
            .all()
        ]
        db.query(models.RemboursementLien).filter(
            models.RemboursementLien.operation_remboursement_id == db_operation.id
        ).delete(synchronize_session=False)

    # N'est plus une dette : ses montants viennent d'être remis à 0 plus haut,
    # les remboursements qui la visaient n'ont plus de cible.
    if etait_remboursable and not est_remboursable:
        db.query(models.RemboursementLien).filter(
            models.RemboursementLien.operation_depense_id == db_operation.id
        ).delete(synchronize_session=False)

    return depenses_a_recalculer


# ---------- Récurrence ----------
#
# Une opération récurrente est un modèle normal (recurrente=True,
# recurrence_parent_id=None) dont on génère paresseusement les occurrences
# futures (elles-mêmes recurrente=True, recurrence_parent_id=<id du modèle>)
# à chaque lecture des opérations (liste, dashboard) -- voir
# generer_occurrences_recurrentes, appelée depuis les routers concernés.


def _ajouter_mois(d: date_type, n: int) -> date_type:
    """Ajoute n mois à une date, en calant le jour sur le dernier jour du mois
    cible si besoin (ex. 31 janvier + 1 mois -> 28/29 février)."""
    mois_total = d.month - 1 + n
    annee = d.year + mois_total // 12
    mois = mois_total % 12 + 1
    dernier_jour = calendar.monthrange(annee, mois)[1]
    return date_type(annee, mois, min(d.day, dernier_jour))


def _prochaine_date_recurrence(d: date_type, frequence: Frequence) -> date_type:
    if frequence == Frequence.hebdomadaire:
        return d + timedelta(weeks=1)
    if frequence == Frequence.mensuelle:
        return _ajouter_mois(d, 1)
    if frequence == Frequence.trimestrielle:
        return _ajouter_mois(d, 3)
    return _ajouter_mois(d, 12)  # annuelle


# Horizon glissant au-delà duquel une récurrence infinie (recurrence_fin=None)
# n'est plus générée à l'avance -- reculé automatiquement à chaque appel
# puisque basé sur la date du jour, jamais persisté comme une vraie fin.
HORIZON_MOIS_RECURRENCE = 24


def generer_occurrences_recurrentes(db: Session) -> None:
    """Topping-up paresseux, appelé en tête de toute lecture d'opérations : crée
    les occurrences futures manquantes de chaque modèle récurrent, jusqu'à sa
    date de fin ou l'horizon glissant si infinie. Ne modifie jamais les
    occurrences déjà générées (montant/catégorie/compte y restent figés même
    si le modèle est modifié depuis)."""
    horizon = _ajouter_mois(date_type.today(), HORIZON_MOIS_RECURRENCE)
    modeles = (
        db.query(models.Operation)
        .filter(models.Operation.recurrente.is_(True), models.Operation.recurrence_parent_id.is_(None))
        .all()
    )
    a_commiter = False
    for modele in modeles:
        borne = min(modele.recurrence_fin, horizon) if modele.recurrence_fin else horizon
        dates_existantes = {
            enfant.date
            for enfant in db.query(models.Operation)
            .filter(models.Operation.recurrence_parent_id == modele.id)
            .all()
        }
        courante = _prochaine_date_recurrence(modele.date, modele.frequence)
        while courante <= borne:
            if courante not in dates_existantes:
                db.add(
                    models.Operation(
                        date=courante,
                        compte_id=modele.compte_id,
                        type_id=modele.type_id,
                        categorie_id=modele.categorie_id,
                        nature=modele.nature,
                        montant=modele.montant,
                        monnaie_id=modele.monnaie_id,
                        sens=modele.sens,
                        statut=Statut.previsionnel,
                        montant_du=modele.montant_du,
                        montant_a_rembourser=modele.montant_a_rembourser,
                        recurrente=True,
                        recurrence_parent_id=modele.id,
                    )
                )
                dates_existantes.add(courante)
                a_commiter = True
            courante = _prochaine_date_recurrence(courante, modele.frequence)
    if a_commiter:
        db.commit()


def _arreter_recurrence(db: Session, modele: models.Operation) -> None:
    """Un modèle qui redevient ponctuel (ou est supprimé) : ses occurrences
    futures pas encore survenues (prévisionnel) n'ont plus lieu d'être ;
    celles déjà survenues (réel) restent, détachées, des opérations
    indépendantes valides. Passe par delete_operation (pas un db.delete brut)
    pour bénéficier du même nettoyage des liens de remboursement qu'une
    suppression normale, au cas où une occurrence future remboursable aurait
    déjà été partiellement réglée."""
    enfants = (
        db.query(models.Operation).filter(models.Operation.recurrence_parent_id == modele.id).all()
    )
    for enfant in enfants:
        if enfant.statut == Statut.previsionnel:
            delete_operation(db, enfant)
        else:
            enfant.recurrence_parent_id = None
    db.commit()


def delete_operation(db: Session, db_operation: models.Operation) -> None:
    if db_operation.recurrente and db_operation.recurrence_parent_id is None:
        _arreter_recurrence(db, db_operation)

    depense_ids_a_recalculer = [
        row[0]
        for row in db.query(models.RemboursementLien.operation_depense_id)
        .filter(models.RemboursementLien.operation_remboursement_id == db_operation.id)
        .all()
    ]
    # Nettoyage explicite des liens : ne pas compter uniquement sur le ON DELETE
    # CASCADE de SQLite, qui exige PRAGMA foreign_keys=ON actif sur la connexion.
    db.query(models.RemboursementLien).filter(
        (models.RemboursementLien.operation_remboursement_id == db_operation.id)
        | (models.RemboursementLien.operation_depense_id == db_operation.id)
    ).delete(synchronize_session=False)
    # Idem pour la ligne brute d'import : la retirer du stock anti-doublons est
    # ce qui rend le relevé d'origine réimportable après suppression.
    db.query(models.LigneImportBrute).filter(
        models.LigneImportBrute.operation_id == db_operation.id
    ).delete(synchronize_session=False)
    # Idem pour le versant titres d'un achat/vente : les deux lignes ne
    # survivent jamais l'une sans l'autre.
    db.query(models.OperationAction).filter(
        models.OperationAction.operation_id == db_operation.id
    ).delete(synchronize_session=False)
    db.delete(db_operation)
    db.commit()
    for depense_id in depense_ids_a_recalculer:
        _recalculer_montant_a_rembourser(db, depense_id)


def delete_all_operations(db: Session) -> int:
    """Supprime toutes les opérations (et leurs liens de remboursement, et les
    lignes brutes d'import qui les référencent) — pensé pour vider rapidement
    des données de test, pas pour un usage courant."""
    nb = db.query(models.Operation).count()
    db.query(models.RemboursementLien).delete(synchronize_session=False)
    db.query(models.LigneImportBrute).filter(
        models.LigneImportBrute.operation_id.isnot(None)
    ).delete(synchronize_session=False)
    # Les mouvements de titres partent avec leur écriture d'espèces ; les
    # titres eux-mêmes (table `action`) restent, ils ne sont pas des opérations.
    db.query(models.OperationAction).delete(synchronize_session=False)
    db.query(models.Operation).delete(synchronize_session=False)
    db.commit()
    return nb


def get_operations_remboursees(db: Session, operation_remboursement_id: int) -> list[models.Operation]:
    ids = [
        row[0]
        for row in db.query(models.RemboursementLien.operation_depense_id)
        .filter(models.RemboursementLien.operation_remboursement_id == operation_remboursement_id)
        .all()
    ]
    if not ids:
        return []
    return db.query(models.Operation).filter(models.Operation.id.in_(ids)).all()


def get_remboursements_lies(db: Session, operation_depense_id: int) -> list[models.Operation]:
    ids = [
        row[0]
        for row in db.query(models.RemboursementLien.operation_remboursement_id)
        .filter(models.RemboursementLien.operation_depense_id == operation_depense_id)
        .all()
    ]
    if not ids:
        return []
    return db.query(models.Operation).filter(models.Operation.id.in_(ids)).all()


def get_operations_remboursees_detail(
    db: Session, operation_remboursement_id: int
) -> list[tuple[models.Operation, float]]:
    """Dépenses réglées par cette opération de remboursement, avec le montant
    réglé pour chacune (peut être inférieur au montant_du de la dépense si le
    remboursement est partiel)."""
    liens = (
        db.query(models.RemboursementLien)
        .filter(models.RemboursementLien.operation_remboursement_id == operation_remboursement_id)
        .all()
    )
    resultat = []
    for lien in liens:
        depense = get_operation(db, lien.operation_depense_id)
        if depense is not None:
            resultat.append((depense, lien.montant))
    return resultat


def get_remboursements_lies_detail(
    db: Session, operation_depense_id: int
) -> list[tuple[models.Operation, float]]:
    """Opérations de remboursement liées à cette dépense, avec le montant
    réglé par chacune pour CETTE dépense spécifiquement."""
    liens = (
        db.query(models.RemboursementLien)
        .filter(models.RemboursementLien.operation_depense_id == operation_depense_id)
        .all()
    )
    resultat = []
    for lien in liens:
        remboursement = get_operation(db, lien.operation_remboursement_id)
        if remboursement is not None:
            resultat.append((remboursement, lien.montant))
    return resultat


def set_operations_remboursees(
    db: Session, operation_remboursement: models.Operation, montants_par_depense: dict[int, float]
) -> None:
    anciens_liens = {
        lien.operation_depense_id: lien
        for lien in db.query(models.RemboursementLien)
        .filter(
            models.RemboursementLien.operation_remboursement_id == operation_remboursement.id
        )
        .all()
    }
    anciennes_ids = set(anciens_liens.keys())
    nouvelles_ids = set(montants_par_depense.keys())

    for depense_id in anciennes_ids - nouvelles_ids:
        db.delete(anciens_liens[depense_id])

    for depense_id, montant in montants_par_depense.items():
        if depense_id in anciens_liens:
            anciens_liens[depense_id].montant = montant
        else:
            db.add(
                models.RemboursementLien(
                    operation_remboursement_id=operation_remboursement.id,
                    operation_depense_id=depense_id,
                    montant=montant,
                )
            )

    db.commit()

    for depense_id in anciennes_ids | nouvelles_ids:
        _recalculer_montant_a_rembourser(db, depense_id)


def _recalculer_montant_a_rembourser(db: Session, operation_depense_id: int) -> None:
    depense = get_operation(db, operation_depense_id)
    if depense is None:
        return
    total_rembourse = (
        db.query(func.sum(models.RemboursementLien.montant))
        .filter(models.RemboursementLien.operation_depense_id == operation_depense_id)
        .scalar()
    ) or 0.0
    depense.montant_a_rembourser = max(0.0, depense.montant_du - total_rembourse)
    db.commit()


def _natures_virement(
    virement: schemas.VirementCreate,
    compte_source: models.Compte,
    compte_destination: models.Compte,
) -> tuple[str, str]:
    """Libellés par défaut des deux écritures (le libellé saisi, s'il existe,
    vaut pour les deux).

    Sur un même compte, « Virement vers CC Perso » depuis « CC Perso » ne
    voudrait rien dire : ce cas n'est possible qu'entre deux monnaies du compte
    (cf. VirementCreate), c'est donc une conversion de change qu'on nomme comme
    telle."""
    if virement.nature:
        return virement.nature, virement.nature
    if compte_source.id == compte_destination.id:
        libelle = f"Conversion sur {compte_source.nom}"
        return libelle, libelle
    return (
        f"Virement vers {compte_destination.nom}",
        f"Virement depuis {compte_source.nom}",
    )


def _jambe_des_frais(virement: schemas.VirementCreate) -> str:
    """Laquelle des deux écritures porte les frais : « sortante » ou « entrante ».

    SUR UNE SEULE, et c'est tout l'enjeu : les frais sont DÉJÀ compris dans les
    deux montants — ajoutés à ce qui part, ou retranchés de ce qui arrive, selon
    le côté qu'ils ont grevé (cf. services/import_bancaire._appliquer_frais).
    Les inscrire des deux côtés les ferait lire deux fois, et l'écran de
    modification en redemanderait deux fois la déduction.

    C'EST LEUR DEVISE QUI DÉSIGNE, comme à l'import : des frais en euros sur un
    virement euros → dollars ont grevé l'émission ; les mêmes en dollars ont
    grevé la réception. À devise égale des deux côtés (le cas ordinaire), c'est
    l'ÉMISSION qui les porte — payer 2 € de frais sur un envoi de 100 € fait
    102 € débités, et c'est cette lecture-là qui vaut.
    """
    if virement.monnaie_frais_id is None:
        return "sortante"
    if virement.monnaie_frais_id == virement.monnaie_id:
        return "sortante"
    if virement.monnaie_frais_id == virement.monnaie_destination_resolue:
        return "entrante"
    # Devise étrangère aux deux : l'import refuse ce cas (frais incohérents), et
    # rien d'autre ne peut le produire. On les pose côté émission plutôt que de
    # les perdre.
    return "sortante"


def create_virement(
    db: Session,
    virement: schemas.VirementCreate,
    compte_source: models.Compte,
    compte_destination: models.Compte,
) -> tuple[models.Operation, models.Operation]:
    virement_id = str(uuid.uuid4())
    nature_sortante, nature_entrante = _natures_virement(
        virement, compte_source, compte_destination
    )
    type_virement = get_type_operation_par_code(db, TypeOperation.virement.value)
    # Les frais ne vont que sur UNE jambe (cf. _jambe_des_frais) : ils sont déjà
    # compris dans son montant, les porter des deux côtés les ferait lire deux
    # fois.
    frais_sur = _jambe_des_frais(virement)

    # Les deux écritures portent chacune SA monnaie et SON montant : c'est ce
    # qui permet d'envoyer 100 € et d'en recevoir 108 $ sans qu'aucun taux de
    # change n'existe dans l'app. Quand les deux monnaies sont identiques, les
    # deux montants le sont aussi (cf. VirementCreate).
    op_sortante = models.Operation(
        date=virement.date,
        compte_id=compte_source.id,
        type_id=type_virement.id,
        categorie_id=None,
        nature=nature_sortante,
        montant=virement.montant,
        monnaie_id=virement.monnaie_id,
        sens=Sens.transfert_sortant,
        statut=virement.statut,
        montant_du=0.0,
        montant_a_rembourser=0.0,
        virement_id=virement_id,
        notes=virement.notes,
        frais=virement.frais if frais_sur == "sortante" else None,
        monnaie_frais_id=(
            virement.monnaie_frais_id if frais_sur == "sortante" else None
        ),
    )
    op_entrante = models.Operation(
        date=virement.date,
        compte_id=compte_destination.id,
        type_id=type_virement.id,
        categorie_id=None,
        nature=nature_entrante,
        montant=virement.montant_destination_resolu,
        monnaie_id=virement.monnaie_destination_resolue,
        sens=Sens.transfert_entrant,
        statut=virement.statut,
        montant_du=0.0,
        montant_a_rembourser=0.0,
        virement_id=virement_id,
        notes=virement.notes,
        frais=virement.frais if frais_sur == "entrante" else None,
        monnaie_frais_id=(
            virement.monnaie_frais_id if frais_sur == "entrante" else None
        ),
    )
    db.add(op_sortante)
    db.add(op_entrante)
    db.commit()
    db.refresh(op_sortante)
    db.refresh(op_entrante)
    return op_sortante, op_entrante


def update_virement(
    db: Session,
    operations: list[models.Operation],
    virement: schemas.VirementCreate,
    compte_source: models.Compte,
    compte_destination: models.Compte,
) -> tuple[models.Operation, models.Operation]:
    """Réécrit les deux écritures d'un virement existant, en place.

    Les deux lignes sont conservées (mêmes id, même virement_id) plutôt que
    supprimées et recréées : tout ce qui les référence — au premier chef la
    ligne brute d'import qui rend un relevé réimportable après suppression
    (cf. LigneImportBrute.operation_id, ON DELETE CASCADE) — survit ainsi à une
    simple correction de montant ou de date.

    Le sens de chaque écriture ne change jamais : c'est lui qui distingue la
    jambe sortante de l'entrante, et l'échanger reviendrait à inverser le
    virement plutôt qu'à le modifier.
    """
    sortante = next(o for o in operations if o.sens == Sens.transfert_sortant)
    entrante = next(o for o in operations if o.sens == Sens.transfert_entrant)
    nature_sortante, nature_entrante = _natures_virement(
        virement, compte_source, compte_destination
    )

    # La jambe qui portait les frais peut changer avec leur devise : l'autre est
    # remise à zéro, sans quoi des frais déplacés resteraient inscrits des deux
    # côtés.
    frais_sur = _jambe_des_frais(virement)

    sortante.date = virement.date
    sortante.compte_id = compte_source.id
    sortante.montant = virement.montant
    sortante.monnaie_id = virement.monnaie_id
    sortante.statut = virement.statut
    sortante.nature = nature_sortante
    sortante.notes = virement.notes
    sortante.frais = virement.frais if frais_sur == "sortante" else None
    sortante.monnaie_frais_id = (
        virement.monnaie_frais_id if frais_sur == "sortante" else None
    )

    entrante.date = virement.date
    entrante.compte_id = compte_destination.id
    entrante.montant = virement.montant_destination_resolu
    entrante.monnaie_id = virement.monnaie_destination_resolue
    entrante.statut = virement.statut
    entrante.nature = nature_entrante
    entrante.notes = virement.notes
    entrante.frais = virement.frais if frais_sur == "entrante" else None
    entrante.monnaie_frais_id = (
        virement.monnaie_frais_id if frais_sur == "entrante" else None
    )

    db.commit()
    db.refresh(sortante)
    db.refresh(entrante)
    return sortante, entrante


def get_virement(db: Session, virement_id: str) -> list[models.Operation]:
    return (
        db.query(models.Operation)
        .filter(models.Operation.virement_id == virement_id)
        .all()
    )


def delete_virement(db: Session, operations: list[models.Operation]) -> None:
    for db_operation in operations:
        db.delete(db_operation)
    db.commit()


# ---------- Placements financiers ----------
#
# Un titre (models.Action) est global ; ce qui est détenu se lit par couple
# (compte, titre) en sommant les mouvements — voir services/placements.py.


# ---------- Types de titre ----------
#
# Des étiquettes, et rien de plus (cf. models.TypeTitre) : aucun calcul ne les
# lit, aucune n'est protégée, et les supprimer ne fait que détyper les titres qui
# les portaient.


def get_types_titre(db: Session) -> list[models.TypeTitre]:
    return (
        db.query(models.TypeTitre)
        .order_by(models.TypeTitre.ordre, models.TypeTitre.nom)
        .all()
    )


def get_type_titre(db: Session, type_titre_id: int) -> Optional[models.TypeTitre]:
    return db.query(models.TypeTitre).filter(models.TypeTitre.id == type_titre_id).first()


def get_type_titre_by_nom(db: Session, nom: str) -> Optional[models.TypeTitre]:
    """Le type portant EXACTEMENT ce libellé.

    Sert au routeur pour refuser un doublon, et à l'import pour retrouver un type
    nommé dans un fichier plutôt que d'en créer un second à la casse près."""
    return db.query(models.TypeTitre).filter(models.TypeTitre.nom == nom).first()


def compter_titres_par_type(db: Session) -> dict[int, int]:
    """Combien de titres portent chaque type, ARCHIVÉS COMPRIS.

    Une seule requête groupée plutôt qu'un compte par ligne : l'écran de gestion
    en affiche autant qu'il y a de types, et un archivé pèse dans la décision de
    supprimer un type autant qu'un titre en service."""
    lignes = (
        db.query(models.Action.type_titre_id, func.count(models.Action.id))
        .filter(models.Action.type_titre_id.isnot(None))
        .group_by(models.Action.type_titre_id)
        .all()
    )
    return {type_id: nombre for type_id, nombre in lignes}


def create_type_titre(db: Session, nom: str) -> models.TypeTitre:
    # En fin de liste : un type qu'on vient de créer ne doit pas s'insérer au
    # milieu de l'ordre que l'utilisateur a posé.
    dernier = db.query(func.max(models.TypeTitre.ordre)).scalar()
    type_titre = models.TypeTitre(nom=nom, ordre=(dernier or 0) + 1)
    db.add(type_titre)
    db.commit()
    db.refresh(type_titre)
    return type_titre


def update_type_titre(
    db: Session,
    type_titre: models.TypeTitre,
    *,
    nom: Optional[str] = None,
    ordre: Optional[int] = None,
) -> models.TypeTitre:
    if nom is not None:
        type_titre.nom = nom
    if ordre is not None:
        type_titre.ordre = ordre
    db.commit()
    db.refresh(type_titre)
    return type_titre


def delete_type_titre(db: Session, type_titre: models.TypeTitre) -> None:
    """Supprime le type ; les titres qui le portaient redeviennent non typés.

    LE DÉTYPAGE EST FAIT ICI, à la main, et non laissé au `ON DELETE SET NULL`
    déclaré sur la colonne : SQLite n'applique ses clés étrangères que si
    `PRAGMA foreign_keys` est allumé, et une session qui aurait déjà chargé ces
    titres garderait de toute façon l'ancien identifiant en mémoire."""
    db.query(models.Action).filter(models.Action.type_titre_id == type_titre.id).update(
        {models.Action.type_titre_id: None}, synchronize_session=False
    )
    db.query(models.RegleImportPlacement).filter(
        models.RegleImportPlacement.type_titre_id == type_titre.id
    ).update({models.RegleImportPlacement.type_titre_id: None}, synchronize_session=False)
    db.delete(type_titre)
    db.commit()


def get_actions(db: Session, *, inclure_archivees: bool = False) -> list[models.Action]:
    """Les titres en service. Les ARCHIVÉS sont exclus par défaut.

    Un titre archivé n'a plus à figurer là où l'on CHOISIT un titre — le menu
    d'achat, la liste des titres suivis, la relecture des cours en ligne. Il
    reste en base, avec tous ses mouvements : c'est ce qui distingue l'archivage
    d'une suppression, que ses opérations d'espèces interdisent de toute façon
    (cf. models.Action.archivee).

    Ce qui se lit depuis les MOUVEMENTS n'est pas concerné et ne doit pas
    l'être : l'historique et les plus-values passées d'un titre archivé restent
    affichés, sans quoi archiver reviendrait à effacer (cf.
    services/placements, qui part de `operation_action` et jamais d'ici)."""
    query = db.query(models.Action)
    if not inclure_archivees:
        query = query.filter(models.Action.archivee.is_(False))
    return query.order_by(models.Action.nom).all()


def get_action(db: Session, action_id: int) -> Optional[models.Action]:
    return db.query(models.Action).filter(models.Action.id == action_id).first()


def get_action_by_nom(db: Session, nom: str) -> Optional[models.Action]:
    return db.query(models.Action).filter(models.Action.nom == nom).first()


def get_action_by_isin(db: Session, code_isin: str) -> Optional[models.Action]:
    """Le titre portant ce code ISIN, ou None.

    Les titres ARCHIVÉS sont inclus, à dessein : un relevé qui rouvre une
    position sur un titre rangé doit retomber sur celui-là, pas en créer un
    second qui partagerait son ISIN (la contrainte d'unicité le refuserait de
    toute façon, mais bien plus tard et bien moins clairement)."""
    if not code_isin:
        return None
    return db.query(models.Action).filter(models.Action.code_isin == code_isin).first()


def create_action(
    db: Session,
    nom: str,
    monnaie_id: int,
    valeur: float = 0.0,
    code_isin: Optional[str] = None,
    type_titre_id: Optional[int] = None,
) -> models.Action:
    action = models.Action(
        nom=nom,
        valeur=valeur,
        monnaie_id=monnaie_id,
        code_isin=code_isin or None,
        # 0 comme None : le menu du formulaire envoie « aucun » sous la forme
        # d'une chaîne vide, que le schéma convertit en 0 plutôt qu'en None.
        type_titre_id=type_titre_id or None,
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def update_action(
    db: Session,
    action: models.Action,
    *,
    nom: Optional[str] = None,
    nom_affichage: Optional[str] = None,
    valeur: Optional[float] = None,
    monnaie_id: Optional[int] = None,
    archivee: Optional[bool] = None,
    code_isin: Optional[str] = None,
    type_titre_id: Optional[int] = None,
) -> models.Action:
    if nom is not None:
        action.nom = nom
    # Une chaîne VIDE rend au titre son nom d'origine : c'est le seul moyen de
    # défaire un renommage, `None` voulant dire « ne change pas ».
    if nom_affichage is not None:
        action.nom_affichage = nom_affichage.strip() or None
    if valeur is not None:
        action.valeur = valeur
    if monnaie_id is not None:
        action.monnaie_id = monnaie_id
    if archivee is not None:
        action.archivee = archivee
    # Comme partout ici, None veut dire « ne change pas » : l'import de
    # placements COMPLÈTE un titre dont l'ISIN manquait, il n'a jamais à
    # l'effacer.
    if code_isin is not None:
        action.code_isin = code_isin
    # LE ZÉRO DÉTYPE. `None` veut dire « ne change pas » comme partout ici, il ne
    # peut donc pas vouloir dire aussi « retire le type » — et il faut bien un
    # geste pour défaire un choix qu'on regrette. Le menu envoie 0 quand on
    # sélectionne « aucun ».
    if type_titre_id is not None:
        action.type_titre_id = type_titre_id or None
    db.commit()
    db.refresh(action)
    return action


def definir_url_cours(
    db: Session, action: models.Action, url: Optional[str]
) -> models.Action:
    """Enregistre (ou retire, avec `None`) la page d'où relire le cours du titre.

    Une fonction à part plutôt qu'un paramètre de plus sur `update_action` :
    celle-ci traite `None` comme « ne change pas », convention qui rendrait
    impossible d'EFFACER un lien. Ici `None` veut dire ce qu'il dit.

    `cours_maj_le` n'est pas touché : retirer un lien n'invalide pas le dernier
    cours lu, il cesse seulement d'être rafraîchi. Le remettre à NULL aurait
    fait passer une valeur connue pour une valeur jamais lue.
    """
    action.url_cours = url
    db.commit()
    db.refresh(action)
    return action


def enregistrer_cours_en_ligne(
    db: Session, action: models.Action, valeur: float, horodatage: datetime
) -> models.Action:
    """Écrit un cours relu en ligne, et date la lecture.

    Les deux ensemble, jamais l'un sans l'autre : un cours sans date ne dit pas
    s'il vaut encore quelque chose, et une date sans cours daterait une lecture
    qui n'a rien changé. L'horodatage est passé par l'appelant (et non pris
    ici) pour qu'un rafraîchissement de dix titres porte la MÊME date sur les
    dix — ce qui se lit comme la seule action qu'il a été.
    """
    action.valeur = valeur
    action.cours_maj_le = horodatage
    db.commit()
    db.refresh(action)
    return action


def action_est_utilisee(db: Session, action_id: int) -> bool:
    return (
        db.query(models.OperationAction)
        .filter(models.OperationAction.action_id == action_id)
        .first()
        is not None
    )


def delete_action(db: Session, action: models.Action) -> None:
    db.delete(action)
    db.commit()


def get_operation_action(db: Session, operation_action_id: int) -> Optional[models.OperationAction]:
    return (
        db.query(models.OperationAction)
        .filter(models.OperationAction.id == operation_action_id)
        .first()
    )


def create_operation_action(
    db: Session,
    *,
    compte_id: int,
    action: models.Action,
    sens: SensAction,
    quantite: float,
    prix_unitaire: float,
    date_operation: date_type,
    nature: Optional[str] = None,
) -> models.OperationAction:
    """Crée les deux lignes solidaires d'un mouvement de titres : l'écriture
    d'espèces (une Operation ordinaire de type `action`) et son versant titres.

    Le sens de l'écriture d'espèces est un transfert, pas une dépense/entrée :
    acheter des titres ne fait pas sortir l'argent du patrimoine, il le
    convertit — il ne doit donc pas peser sur la variation du mois ni sur les
    dépenses par catégorie, exactement comme un virement interne.

    Statut toujours "réel" : un ordre de bourse est passé ou ne l'est pas, il
    n'y a pas de mouvement de titres prévisionnel à saisir ici.

    La monnaie de l'écriture est celle de cotation du titre : le prix payé est
    libellé dans cette monnaie, donc les espèces bougent dans celle-là (le
    routeur vérifie que le compte la porte).
    """
    type_action = get_type_operation_par_code(db, TypeOperation.action.value)
    montant = quantite * prix_unitaire
    prefixe = "Achat" if sens == SensAction.achat else "Vente"
    db_operation = models.Operation(
        date=date_operation,
        compte_id=compte_id,
        type_id=type_action.id,
        categorie_id=None,
        # Le nom AFFICHÉ : ce libellé se relit dans la liste des opérations,
        # et c'est justement pour ne plus lire « AMUNDI IDX SOL MSC WLD-IE-C »
        # qu'on renomme un titre.
        nature=nature or f"{prefixe} {action.nom_affiche}",
        montant=montant,
        monnaie_id=action.monnaie_id,
        sens=Sens.transfert_sortant if sens == SensAction.achat else Sens.transfert_entrant,
        statut=Statut.reel,
        montant_du=0.0,
        montant_a_rembourser=0.0,
    )
    db.add(db_operation)
    db.flush()  # l'id de l'écriture d'espèces est nécessaire ci-dessous
    db_operation_action = models.OperationAction(
        operation_id=db_operation.id,
        action_id=action.id,
        sens=sens,
        quantite=quantite,
        prix_unitaire=prix_unitaire,
    )
    db.add(db_operation_action)
    db.commit()
    db.refresh(db_operation_action)
    return db_operation_action


def delete_operation_action(db: Session, operation_action: models.OperationAction) -> None:
    """Supprime le mouvement de titres ET son écriture d'espèces : laisser
    l'une sans l'autre fausserait soit le portefeuille, soit le solde."""
    operation = get_operation(db, operation_action.operation_id)
    db.delete(operation_action)
    if operation is not None:
        db.delete(operation)
    db.commit()


# ---------- Import bancaire ----------
#
# Tout ce qui suit est scopé par preset_id (voir models.ImportPreset) : un
# même nom bancaire, ou une même ligne brute, peut légitimement exister sous
# deux presets différents sans jamais se comparer ou s'écraser entre eux.


def list_import_presets(db: Session, domaine: str) -> list[models.ImportPreset]:
    """Les presets d'UN domaine (cf. constants.DomaineImport).

    `domaine` est obligatoire, sans valeur par défaut, et c'est délibéré : un
    appel qui l'oublierait mélangerait les presets bancaires et ceux de
    placements dans un sélecteur, ou — bien pire — laisserait supprimer le
    dernier preset bancaire au prétexte qu'un preset de placements existe (cf.
    routers/import_bancaire.delete_preset). Une signature qui ne pardonne pas
    l'oubli vaut mieux qu'un défaut qui a l'air raisonnable."""
    return (
        db.query(models.ImportPreset)
        .filter(models.ImportPreset.domaine == domaine)
        .order_by(models.ImportPreset.nom)
        .all()
    )


def get_import_preset(db: Session, preset_id: int) -> Optional[models.ImportPreset]:
    return db.query(models.ImportPreset).filter(models.ImportPreset.id == preset_id).first()


def create_import_preset(
    db: Session,
    nom: str,
    colonnes: Optional[list[dict]] = None,
    colonnes_comparaison: Optional[list[int]] = None,
    ignorer_premiere_ligne: bool = False,
    compte_id: Optional[int] = None,
    mode_comparaison: Optional[str] = None,
    libelles_sens_sortie: Optional[list[str]] = None,
    libelles_sens_entree: Optional[list[str]] = None,
    libelles_statut_execute: Optional[list[str]] = None,
    libelles_statut_attente: Optional[list[str]] = None,
    libelles_statut_refuse: Optional[list[str]] = None,
    domaine: str = DomaineImport.bancaire.value,
    libelles_type_achat: Optional[list[str]] = None,
    libelles_type_vente: Optional[list[str]] = None,
    libelles_type_transfert: Optional[list[str]] = None,
    mode_lecture: Optional[str] = None,
) -> models.ImportPreset:
    # Les colonnes par défaut dépendent du domaine ET, pour les placements, du
    # mode de lecture : le format bancaire historique à 12 colonnes n'a rien à
    # faire dans un preset de placements, et une PHOTOGRAPHIE de compte ne lit
    # ni date ni type d'opération là où une liste de mouvements le fait.
    if colonnes is None:
        if domaine == DomaineImport.placement.value:
            colonnes = (
                COLONNES_IMPORT_POSITION_PAR_DEFAUT
                if mode_lecture == ModeLecturePlacement.position.value
                else COLONNES_IMPORT_PLACEMENT_PAR_DEFAUT
            )
        else:
            colonnes = COLONNES_IMPORT_PAR_DEFAUT
    preset = models.ImportPreset(
        nom=nom,
        domaine=domaine,
        compte_id=compte_id,
        colonnes=colonnes,
        colonnes_comparaison=colonnes_comparaison or [],
        mode_comparaison=mode_comparaison or ModeComparaison.exclusion.value,
        ignorer_premiere_ligne=ignorer_premiere_ligne,
        libelles_sens_sortie=libelles_sens_sortie or [],
        libelles_sens_entree=libelles_sens_entree or [],
        libelles_statut_execute=libelles_statut_execute or [],
        libelles_statut_attente=libelles_statut_attente or [],
        libelles_statut_refuse=libelles_statut_refuse or [],
        libelles_type_achat=libelles_type_achat or [],
        libelles_type_vente=libelles_type_vente or [],
        libelles_type_transfert=libelles_type_transfert or [],
        mode_lecture=mode_lecture,
    )
    db.add(preset)
    db.commit()
    db.refresh(preset)
    return preset


# None est une valeur légitime pour `compte_id` (délier le preset de son
# compte) : il ne peut donc pas signifier "ne pas y toucher" comme pour les
# autres champs, d'où ce marqueur d'absence.
_INCHANGE = object()


def update_import_preset(
    db: Session,
    preset: models.ImportPreset,
    *,
    nom: Optional[str] = None,
    colonnes: Optional[list[dict]] = None,
    colonnes_comparaison: Optional[list[int]] = None,
    mode_comparaison: Optional[str] = None,
    ignorer_premiere_ligne: Optional[bool] = None,
    compte_id=_INCHANGE,
    libelles_sens_sortie: Optional[list[str]] = None,
    libelles_sens_entree: Optional[list[str]] = None,
    libelles_statut_execute: Optional[list[str]] = None,
    libelles_statut_attente: Optional[list[str]] = None,
    libelles_statut_refuse: Optional[list[str]] = None,
    libelles_type_achat: Optional[list[str]] = None,
    libelles_type_vente: Optional[list[str]] = None,
    libelles_type_transfert: Optional[list[str]] = None,
    mode_lecture: Optional[str] = None,
) -> models.ImportPreset:
    # `domaine` n'est PAS modifiable : les colonnes, les correspondances et le
    # stock de lignes brutes d'un preset n'auraient aucun sens de l'autre côté.
    # Changer de domaine, c'est créer un autre preset.
    if nom is not None:
        preset.nom = nom
    if compte_id is not _INCHANGE:
        preset.compte_id = compte_id
    if colonnes is not None:
        preset.colonnes = colonnes
    if colonnes_comparaison is not None:
        preset.colonnes_comparaison = colonnes_comparaison
    if mode_comparaison is not None:
        preset.mode_comparaison = mode_comparaison
    if ignorer_premiere_ligne is not None:
        preset.ignorer_premiere_ligne = ignorer_premiere_ligne
    if libelles_sens_sortie is not None:
        preset.libelles_sens_sortie = libelles_sens_sortie
    if libelles_sens_entree is not None:
        preset.libelles_sens_entree = libelles_sens_entree
    if libelles_statut_execute is not None:
        preset.libelles_statut_execute = libelles_statut_execute
    if libelles_statut_attente is not None:
        preset.libelles_statut_attente = libelles_statut_attente
    if libelles_statut_refuse is not None:
        preset.libelles_statut_refuse = libelles_statut_refuse
    if libelles_type_achat is not None:
        preset.libelles_type_achat = libelles_type_achat
    if libelles_type_vente is not None:
        preset.libelles_type_vente = libelles_type_vente
    if libelles_type_transfert is not None:
        preset.libelles_type_transfert = libelles_type_transfert
    # Le mode de lecture, LUI, est modifiable : c'est un réglage de colonnes, au
    # même titre que les numéros à côté desquels il se choisit. Changer de mode
    # laisse en revanche des colonnes qui ne veulent plus rien dire — le routeur
    # revalide toute la configuration à chaque écriture.
    if mode_lecture is not None:
        preset.mode_lecture = mode_lecture
    db.commit()
    db.refresh(preset)
    return preset


def delete_import_preset(db: Session, preset: models.ImportPreset) -> None:
    db.delete(preset)
    db.commit()


def get_mapping_categorie(db: Session, preset_id: int, nom_banque: str) -> Optional[int]:
    """La catégorie mémorisée pour ce libellé bancaire, ou None s'il n'en a pas.

    Depuis 0022 une correspondance ne vise plus qu'une catégorie : le type est
    posé par les règles, évaluées avant (cf. services/import_bancaire)."""
    mapping = (
        db.query(models.ImportCategorieMapping)
        .filter(
            models.ImportCategorieMapping.preset_id == preset_id,
            models.ImportCategorieMapping.nom_banque == nom_banque,
        )
        .first()
    )
    return mapping.categorie_id if mapping else None


def set_mapping_categorie(
    db: Session, preset_id: int, nom_banque: str, categorie_id: int
) -> None:
    mapping = (
        db.query(models.ImportCategorieMapping)
        .filter(
            models.ImportCategorieMapping.preset_id == preset_id,
            models.ImportCategorieMapping.nom_banque == nom_banque,
        )
        .first()
    )
    if mapping:
        mapping.categorie_id = categorie_id
    else:
        db.add(
            models.ImportCategorieMapping(
                preset_id=preset_id, nom_banque=nom_banque, categorie_id=categorie_id
            )
        )
    db.commit()


def get_mapping_compte(db: Session, preset_id: int, nom_banque: str) -> Optional[int]:
    mapping = (
        db.query(models.ImportCompteMapping)
        .filter(
            models.ImportCompteMapping.preset_id == preset_id,
            models.ImportCompteMapping.nom_banque == nom_banque,
        )
        .first()
    )
    return mapping.compte_id if mapping else None


def set_mapping_compte(db: Session, preset_id: int, nom_banque: str, compte_id: int) -> None:
    mapping = (
        db.query(models.ImportCompteMapping)
        .filter(
            models.ImportCompteMapping.preset_id == preset_id,
            models.ImportCompteMapping.nom_banque == nom_banque,
        )
        .first()
    )
    if mapping:
        mapping.compte_id = compte_id
    else:
        db.add(models.ImportCompteMapping(preset_id=preset_id, nom_banque=nom_banque, compte_id=compte_id))
    db.commit()


def get_mapping_monnaie(db: Session, preset_id: int, nom_banque: str) -> Optional[int]:
    """La monnaie mémorisée pour ce libellé de devise du fichier (« EUR »), ou
    None. Seule source de rattachement d'une devise (cf. import_bancaire.
    _resoudre_monnaie) : rien n'est déduit d'un nom ou d'un symbole qui se
    ressemblent, c'est toujours un choix explicite de l'utilisateur."""
    mapping = (
        db.query(models.ImportMonnaieMapping)
        .filter(
            models.ImportMonnaieMapping.preset_id == preset_id,
            models.ImportMonnaieMapping.nom_banque == nom_banque,
        )
        .first()
    )
    return mapping.monnaie_id if mapping else None


def set_mapping_monnaie(db: Session, preset_id: int, nom_banque: str, monnaie_id: int) -> None:
    mapping = (
        db.query(models.ImportMonnaieMapping)
        .filter(
            models.ImportMonnaieMapping.preset_id == preset_id,
            models.ImportMonnaieMapping.nom_banque == nom_banque,
        )
        .first()
    )
    if mapping:
        mapping.monnaie_id = monnaie_id
    else:
        db.add(
            models.ImportMonnaieMapping(
                preset_id=preset_id, nom_banque=nom_banque, monnaie_id=monnaie_id
            )
        )
    db.commit()


def list_mappings_categorie(db: Session, preset_id: int) -> list[models.ImportCategorieMapping]:
    return (
        db.query(models.ImportCategorieMapping)
        .filter(models.ImportCategorieMapping.preset_id == preset_id)
        .order_by(models.ImportCategorieMapping.nom_banque)
        .all()
    )


def list_mappings_categorie_tous_presets(db: Session) -> list[tuple]:
    """(mapping, nom du compte lié au preset) pour TOUS les presets.

    La galerie des correspondances (page Règles) les montre côte à côte : c'est
    le classement lui-même qu'on y relit, et le couper par preset obligeait à
    changer de preset — depuis la page Import, qui porte le sélecteur — pour
    voir la moitié du travail. Le compte lié voyage avec chaque ligne : sans
    lui, deux banques qui exportent « Alimentation » donnent deux cartes
    indiscernables.

    Compte NULL pour un preset qui résout le compte depuis le fichier ; d'où le
    outerjoin, sans quoi ces correspondances disparaîtraient purement et
    simplement.

    BANCAIRE SEULEMENT, comme les deux fonctions suivantes. La galerie est un
    écran d'import bancaire : elle en porte le vocabulaire, et son bouton de
    suppression réécrit en masse sur /import/presets/{id}/mappings/…, chemin
    que le routeur du noyau refuse pour un preset d'un autre domaine. Les
    correspondances d'un preset de placements se relisent sur l'écran de son
    extension, sous le preset qui les a apprises."""
    return (
        db.query(models.ImportCategorieMapping, models.Compte.nom)
        .join(
            models.ImportPreset,
            models.ImportPreset.id == models.ImportCategorieMapping.preset_id,
        )
        .outerjoin(models.Compte, models.Compte.id == models.ImportPreset.compte_id)
        .filter(models.ImportPreset.domaine == DomaineImport.bancaire.value)
        .order_by(models.ImportCategorieMapping.nom_banque, models.ImportPreset.nom)
        .all()
    )


def list_mappings_compte(db: Session, preset_id: int) -> list[models.ImportCompteMapping]:
    return (
        db.query(models.ImportCompteMapping)
        .join(models.Compte)
        .filter(models.ImportCompteMapping.preset_id == preset_id)
        .order_by(models.ImportCompteMapping.nom_banque)
        .all()
    )


def list_mappings_compte_tous_presets(db: Session) -> list[models.ImportCompteMapping]:
    """Toutes les correspondances de compte, tous presets confondus.

    Contrairement aux catégories, aucune provenance n'accompagne le résultat :
    la page Règles les affiche en une seule liste commune, et le routeur y
    regroupe les entrées identiques (cf. get_mappings)."""
    return (
        db.query(models.ImportCompteMapping)
        .join(models.Compte)
        .join(
            models.ImportPreset,
            models.ImportPreset.id == models.ImportCompteMapping.preset_id,
        )
        .filter(models.ImportPreset.domaine == DomaineImport.bancaire.value)
        .order_by(models.ImportCompteMapping.nom_banque)
        .all()
    )


def list_mappings_monnaie(db: Session, preset_id: int) -> list[models.ImportMonnaieMapping]:
    return (
        db.query(models.ImportMonnaieMapping)
        .join(models.Monnaie)
        .filter(models.ImportMonnaieMapping.preset_id == preset_id)
        .order_by(models.ImportMonnaieMapping.nom_banque)
        .all()
    )


def list_mappings_monnaie_tous_presets(db: Session) -> list[models.ImportMonnaieMapping]:
    """Idem pour les devises : « EUR » se répète d'un preset à l'autre, c'est le
    routeur qui les fond en une entrée unique."""
    return (
        db.query(models.ImportMonnaieMapping)
        .join(models.Monnaie)
        .join(
            models.ImportPreset,
            models.ImportPreset.id == models.ImportMonnaieMapping.preset_id,
        )
        .filter(models.ImportPreset.domaine == DomaineImport.bancaire.value)
        .order_by(models.ImportMonnaieMapping.nom_banque)
        .all()
    )


def delete_mapping_monnaie(db: Session, preset_id: int, nom_banque: str) -> bool:
    mapping = (
        db.query(models.ImportMonnaieMapping)
        .filter(
            models.ImportMonnaieMapping.preset_id == preset_id,
            models.ImportMonnaieMapping.nom_banque == nom_banque,
        )
        .first()
    )
    if mapping is None:
        return False
    db.delete(mapping)
    db.commit()
    return True


def delete_mapping_categorie(db: Session, preset_id: int, nom_banque: str) -> bool:
    mapping = (
        db.query(models.ImportCategorieMapping)
        .filter(
            models.ImportCategorieMapping.preset_id == preset_id,
            models.ImportCategorieMapping.nom_banque == nom_banque,
        )
        .first()
    )
    if mapping is None:
        return False
    db.delete(mapping)
    db.commit()
    return True


def delete_mapping_compte(db: Session, preset_id: int, nom_banque: str) -> bool:
    mapping = (
        db.query(models.ImportCompteMapping)
        .filter(
            models.ImportCompteMapping.preset_id == preset_id,
            models.ImportCompteMapping.nom_banque == nom_banque,
        )
        .first()
    )
    if mapping is None:
        return False
    db.delete(mapping)
    db.commit()
    return True


def create_import_historique(
    db: Session,
    *,
    preset_id: int,
    nom_fichier: str,
    operations_creees: int,
    lignes_ignorees: int,
    doublons_detectes: int = 0,
) -> models.ImportHistorique:
    entree = models.ImportHistorique(
        preset_id=preset_id,
        date_import=datetime.now(),
        nom_fichier=nom_fichier or None,
        operations_creees=operations_creees,
        lignes_ignorees=lignes_ignorees,
        doublons_detectes=doublons_detectes,
    )
    db.add(entree)
    db.commit()
    db.refresh(entree)
    return entree


def get_import_historique(db: Session, preset_id: int) -> list[models.ImportHistorique]:
    return (
        db.query(models.ImportHistorique)
        .filter(models.ImportHistorique.preset_id == preset_id)
        .order_by(models.ImportHistorique.date_import.desc())
        .all()
    )


def list_lignes_import_brutes(db: Session, preset_id: int) -> list[models.LigneImportBrute]:
    """Stock de lignes déjà importées SOUS CE PRESET (format brut), pour
    comparaison lors d'un nouvel import (voir services.import_bancaire.
    detecter_doublon)."""
    return (
        db.query(models.LigneImportBrute)
        .filter(models.LigneImportBrute.preset_id == preset_id)
        .all()
    )


def create_ligne_import_brute(
    db: Session,
    *,
    preset_id: int,
    donnees: dict,
    import_historique_id: Optional[int] = None,
    operation_id: Optional[int] = None,
) -> models.LigneImportBrute:
    ligne = models.LigneImportBrute(
        preset_id=preset_id,
        donnees=donnees,
        import_historique_id=import_historique_id,
        operation_id=operation_id,
        date_creation=datetime.now(),
    )
    db.add(ligne)
    db.commit()
    db.refresh(ligne)
    return ligne


def create_operation_importee(
    db: Session,
    *,
    date_operation: date_type,
    compte_id: int,
    type_id: int,
    categorie_id: Optional[int],
    nature: str,
    montant: float,
    monnaie_id: int,
    montant_du: Optional[float] = None,
    sens: Optional[Sens] = None,
    statut: Statut = Statut.reel,
    notes: Optional[str] = None,
    amorti: bool = False,
    amortissement_debut: Optional[date_type] = None,
    amortissement_fin: Optional[date_type] = None,
    decoupes=None,
    frais: Optional[float] = None,
    monnaie_frais_id: Optional[int] = None,
) -> models.Operation:
    """Crée une opération issue d'un import bancaire : la vérification a déjà
    eu lieu ligne par ligne dans l'aperçu, avant confirmation (voir
    services/import_bancaire.confirmer). Le caractère remboursable découle du
    type (dépense remboursable et prêt reçu) ; les deux types de règlement ne
    passent en réalité jamais par cette fonction : la liaison à une
    dépense/prêt existant se fait via l'écran d'import une fois le reste
    confirmé, en créant directement l'opération via l'endpoint /operations
    habituel (seul capable de gérer operations_remboursees).

    `sens` permet à l'appelant d'imposer transfert_sortant/transfert_entrant
    pour un virement importé dont un seul compte est connu (le second compte
    absent empêche le vrai virement double-écriture, cf. confirmer()) : le type
    "Virement interne" ne dit pas à lui seul dans quel sens va l'argent, ce qui
    fausserait le solde du compte quand cette écriture est en réalité une
    entrée.

    `statut` vaut réel par défaut — une ligne de relevé décrit par nature une
    transaction déjà survenue. Il ne devient prévisionnel que pour les relevés
    qui listent aussi les autorisations en attente et le disent dans une colonne
    (cf. services/import_bancaire._statut_operation).

    `notes` et l'amortissement viennent du formulaire d'édition de l'aperçu :
    ils ne se lisent dans aucun relevé, mais c'est en classant la ligne qu'on
    sait qu'une dépense s'étale ou qu'elle mérite un mot — y revenir après
    l'import obligerait à retrouver l'opération une à une. Les bornes sont
    ramenées au 1er du mois comme partout ailleurs (cf.
    _normaliser_amortissement)."""
    type_operation = get_type_operation(db, type_id)
    if decoupes:
        # Découpée = pas de catégorie (cf. create_operation, même raison : le
        # sens se calcule d'après elle).
        categorie_id = None
    categorie_id, nom_categorie = _normaliser_categorie_selon_type(
        db, type_operation.code, categorie_id
    )

    montant_du_final, montant_a_rembourser = _resoudre_montants_remboursement(
        type_operation.code, montant, montant_du, None
    )
    db_operation = models.Operation(
        date=date_operation,
        compte_id=compte_id,
        type_id=type_id,
        categorie_id=categorie_id,
        nature=nature,
        montant=montant,
        monnaie_id=monnaie_id,
        sens=sens if sens is not None else _sens_pour_type(type_operation.code, nom_categorie),
        statut=statut,
        montant_du=montant_du_final,
        montant_a_rembourser=montant_a_rembourser,
        notes=notes,
        amorti=amorti,
        amortissement_debut=amortissement_debut,
        amortissement_fin=amortissement_fin,
        # Les frais que `montant` contient déjà (cf. models.Operation.frais) :
        # gardés pour que l'écran puisse redécomposer le montant, jamais relus
        # par un calcul.
        frais=frais,
        monnaie_frais_id=monnaie_frais_id,
    )
    _normaliser_amortissement(db_operation)
    # LA DÉCOUPE POSÉE PAR UNE RÈGLE (cf. services/regles_categorisation.
    # resoudre_decoupes). Elle a déjà été résolue en montants, et son invariant
    # revérifié ici par `_appliquer_decoupes` : une découpe qui ne tomberait pas
    # juste est simplement abandonnée, et la ligne s'importe avec sa catégorie —
    # un import de trois cents lignes ne doit pas s'arrêter sur une formule.
    _appliquer_decoupes(db_operation, type_operation.code, decoupes)
    db.add(db_operation)
    db.commit()
    db.refresh(db_operation)
    return db_operation


# ---------- Règles de catégorisation ----------


def list_regles_categorisation(db: Session) -> list[models.RegleCategorisation]:
    """Triées comme elles sont évaluées : par ordre croissant, l'id
    départageant deux règles de même ordre (voir
    services.regles_categorisation.appliquer_regles)."""
    return (
        db.query(models.RegleCategorisation)
        .order_by(models.RegleCategorisation.ordre, models.RegleCategorisation.id)
        .all()
    )


def get_regle_categorisation(db: Session, regle_id: int) -> Optional[models.RegleCategorisation]:
    return (
        db.query(models.RegleCategorisation)
        .filter(models.RegleCategorisation.id == regle_id)
        .first()
    )


def _appliquer_decoupes_regle(regle: models.RegleCategorisation, decoupes) -> None:
    """Remplace les parts d'une règle par celles fournies (schemas.RegleDecoupeInput).

    Les formules sont déjà validées par le schéma ; il ne reste ici qu'à les
    ranger dans l'ordre. `None` et `[]` valent la même chose : une règle sans
    part classe par sa catégorie unique."""
    regle.decoupes.clear()
    for rang, part in enumerate(decoupes or []):
        regle.decoupes.append(
            models.RegleDecoupe(
                categorie_id=part.categorie_id, formule=part.formule.strip(), ordre=rang
            )
        )


def create_regle_categorisation(
    db: Session,
    *,
    nom: str,
    description: str = "",
    conditions: dict,
    type_id: int,
    categorie_id: Optional[int] = None,
    compte_autre_id: Optional[int] = None,
    decoupes=None,
    actif: bool = True,
    arreter_apres: bool = True,
    ordre: Optional[int] = None,
) -> models.RegleCategorisation:
    if ordre is None:
        # En bout de liste : une nouvelle règle ne doit jamais court-circuiter
        # silencieusement celles déjà en place.
        ordre_max = db.query(func.max(models.RegleCategorisation.ordre)).scalar()
        ordre = (ordre_max + 1) if ordre_max is not None else 0
    regle = models.RegleCategorisation(
        nom=nom,
        description=description,
        conditions=conditions,
        type_id=type_id,
        categorie_id=categorie_id,
        compte_autre_id=compte_autre_id,
        actif=actif,
        arreter_apres=arreter_apres,
        ordre=ordre,
    )
    _appliquer_decoupes_regle(regle, decoupes)
    db.add(regle)
    db.commit()
    db.refresh(regle)
    return regle


def update_regle_categorisation(
    db: Session, regle: models.RegleCategorisation, **champs
) -> models.RegleCategorisation:
    """`decoupes` y est traité à part des autres champs : ce n'est pas une
    colonne mais une collection, qu'un `setattr` remplacerait par des schémas
    Pydantic au lieu de lignes de table."""
    if "decoupes" in champs:
        _appliquer_decoupes_regle(regle, champs.pop("decoupes"))
    # `categorie_id` est légitimement remis à None (passage à un type dont la
    # catégorie est imposée) : on distingue "absent" de "None" via la présence
    # de la clé, d'où **champs plutôt que des paramètres optionnels.
    for nom_champ in (
        "nom",
        "description",
        "conditions",
        "type_id",
        "categorie_id",
        "compte_autre_id",
        "actif",
        "arreter_apres",
        "ordre",
    ):
        if nom_champ in champs:
            setattr(regle, nom_champ, champs[nom_champ])
    db.commit()
    db.refresh(regle)
    return regle


def delete_regle_categorisation(db: Session, regle: models.RegleCategorisation) -> None:
    db.delete(regle)
    db.commit()


def reordonner_regles_categorisation(db: Session, ids_ordonnes: list[int]) -> None:
    """Réécrit `ordre` d'après la position dans la liste fournie."""
    for position, regle_id in enumerate(ids_ordonnes):
        regle = get_regle_categorisation(db, regle_id)
        if regle is not None:
            regle.ordre = position
    db.commit()


# ---------- Règles d'import de placements ----------
#
# Le même jeu de fonctions que ci-dessus, pour l'autre domaine d'import. Elles
# vivent dans le noyau alors que l'écran qui les écrit appartient à l'extension
# « import-placements » : une extension n'emporte jamais son schéma, ni les
# accès à sa table (cf. extensions/README.md). Éteindre l'extension arrête donc
# de consulter ces règles, sans en perdre une seule.


def list_regles_import_placement(db: Session) -> list[models.RegleImportPlacement]:
    """Triées comme elles sont évaluées : par ordre croissant, l'id départageant
    deux règles de même ordre."""
    return (
        db.query(models.RegleImportPlacement)
        .order_by(models.RegleImportPlacement.ordre, models.RegleImportPlacement.id)
        .all()
    )


def get_regle_import_placement(
    db: Session, regle_id: int
) -> Optional[models.RegleImportPlacement]:
    return (
        db.query(models.RegleImportPlacement)
        .filter(models.RegleImportPlacement.id == regle_id)
        .first()
    )


def create_regle_import_placement(
    db: Session,
    *,
    nom: str,
    description: str = "",
    conditions: dict,
    type_placement: str,
    compte_autre_id: Optional[int] = None,
    type_titre_id: Optional[int] = None,
    actif: bool = True,
    ordre: Optional[int] = None,
) -> models.RegleImportPlacement:
    if ordre is None:
        # En bout de liste, comme les règles bancaires : une règle nouvelle ne
        # court-circuite jamais silencieusement celles déjà écrites.
        ordre_max = db.query(func.max(models.RegleImportPlacement.ordre)).scalar()
        ordre = (ordre_max + 1) if ordre_max is not None else 0
    regle = models.RegleImportPlacement(
        nom=nom,
        description=description,
        conditions=conditions,
        type_placement=type_placement,
        compte_autre_id=compte_autre_id,
        type_titre_id=type_titre_id,
        actif=actif,
        ordre=ordre,
    )
    db.add(regle)
    db.commit()
    db.refresh(regle)
    return regle


def update_regle_import_placement(
    db: Session, regle: models.RegleImportPlacement, **champs
) -> models.RegleImportPlacement:
    for nom_champ in (
        "nom",
        "description",
        "conditions",
        "type_placement",
        "compte_autre_id",
        "type_titre_id",
        "actif",
        "ordre",
    ):
        if nom_champ in champs:
            setattr(regle, nom_champ, champs[nom_champ])
    db.commit()
    db.refresh(regle)
    return regle


def delete_regle_import_placement(db: Session, regle: models.RegleImportPlacement) -> None:
    db.delete(regle)
    db.commit()


def reordonner_regles_import_placement(db: Session, ids_ordonnes: list[int]) -> None:
    """Réécrit `ordre` d'après la position dans la liste fournie."""
    for position, regle_id in enumerate(ids_ordonnes):
        regle = get_regle_import_placement(db, regle_id)
        if regle is not None:
            regle.ordre = position
    db.commit()


# ---------- Sous-filtres / projets ----------
#
# Dans le noyau alors que l'écran appartient à l'extension « Projets » : une
# extension n'emporte jamais son schéma, ni les accès à sa table (cf.
# extensions/README.md). L'éteindre masque l'écran sans perdre un regroupement.


def list_sous_filtres(db: Session) -> list[models.SousFiltre]:
    """Dans l'ordre choisi par l'utilisateur, l'id départageant deux projets de
    même rang (cas d'une base antérieure au premier classement)."""
    return (
        db.query(models.SousFiltre)
        .order_by(models.SousFiltre.ordre, models.SousFiltre.id)
        .all()
    )


def get_sous_filtre(db: Session, sous_filtre_id: int) -> Optional[models.SousFiltre]:
    return (
        db.query(models.SousFiltre)
        .filter(models.SousFiltre.id == sous_filtre_id)
        .first()
    )


def get_sous_filtre_par_nom(db: Session, nom: str) -> Optional[models.SousFiltre]:
    return db.query(models.SousFiltre).filter(models.SousFiltre.nom == nom).first()


def create_sous_filtre(
    db: Session, *, nom: str, description: str = "", ordre: Optional[int] = None
) -> models.SousFiltre:
    if ordre is None:
        ordre_max = db.query(func.max(models.SousFiltre.ordre)).scalar()
        ordre = (ordre_max + 1) if ordre_max is not None else 0
    sous_filtre = models.SousFiltre(nom=nom, description=description, ordre=ordre)
    db.add(sous_filtre)
    db.commit()
    db.refresh(sous_filtre)
    return sous_filtre


def update_sous_filtre(
    db: Session, sous_filtre: models.SousFiltre, **champs
) -> models.SousFiltre:
    for nom_champ in ("nom", "description", "ordre"):
        if nom_champ in champs:
            setattr(sous_filtre, nom_champ, champs[nom_champ])
    db.commit()
    db.refresh(sous_filtre)
    return sous_filtre


def delete_sous_filtre(db: Session, sous_filtre: models.SousFiltre) -> None:
    """Supprime le projet, et LUI SEUL.

    Les opérations qu'il regroupait ne bougent pas : un projet est une vue sur
    des opérations qui existent sans lui. Seuls les liens partent, par la
    cascade de la table d'association."""
    db.delete(sous_filtre)
    db.commit()


def reordonner_sous_filtres(db: Session, ids_ordonnes: list[int]) -> None:
    """Réécrit `ordre` d'après la position dans la liste fournie."""
    for position, sous_filtre_id in enumerate(ids_ordonnes):
        sous_filtre = get_sous_filtre(db, sous_filtre_id)
        if sous_filtre is not None:
            sous_filtre.ordre = position
    db.commit()


def ajouter_operations_au_sous_filtre(
    db: Session, sous_filtre: models.SousFiltre, operation_ids: list[int]
) -> int:
    """Verse ces opérations dans le projet, et rend le nombre RÉELLEMENT ajouté.

    Une opération déjà présente est ignorée sans un mot : la clé primaire
    composite l'interdit de toute façon, et « ajouter ce qui y est déjà » est
    une intention parfaitement claire — l'utilisateur coche des lignes, il ne
    tient pas le compte de celles qu'il avait cochées la semaine dernière.

    Une opération inconnue est ignorée de même : le lot est traité pour ce qu'il
    a de valide plutôt que rejeté en bloc.
    """
    presentes = {operation.id for operation in sous_filtre.operations}
    ajoutees = 0
    for operation_id in operation_ids:
        if operation_id in presentes:
            continue
        operation = get_operation(db, operation_id)
        if operation is None:
            continue
        sous_filtre.operations.append(operation)
        presentes.add(operation_id)
        ajoutees += 1
    db.commit()
    return ajoutees


def retirer_operations_du_sous_filtre(
    db: Session, sous_filtre: models.SousFiltre, operation_ids: list[int]
) -> int:
    """Retire ces opérations du projet, et rend le nombre réellement retiré.

    RIEN N'EST SUPPRIMÉ : l'opération quitte le regroupement et reste en base,
    avec son compte, sa catégorie et son montant. C'est toute la différence entre
    ce bouton et celui de la page Opérations."""
    a_retirer = set(operation_ids)
    retirees = [op for op in sous_filtre.operations if op.id in a_retirer]
    for operation in retirees:
        sous_filtre.operations.remove(operation)
    db.commit()
    return len(retirees)


def get_date_dernier_import(db: Session, preset_id: int) -> Optional[datetime]:
    """Date du dernier import confirmé sous ce preset, ou None s'il n'a jamais
    servi (voir routers.import_bancaire.list_presets)."""
    return (
        db.query(func.max(models.ImportHistorique.date_import))
        .filter(models.ImportHistorique.preset_id == preset_id)
        .scalar()
    )


def get_import_historique_entree(
    db: Session, historique_id: int
) -> Optional[models.ImportHistorique]:
    return (
        db.query(models.ImportHistorique)
        .filter(models.ImportHistorique.id == historique_id)
        .first()
    )


def get_operations_d_un_import(
    db: Session, historique_id: int
) -> list[models.Operation]:
    """Les opérations encore en base que cet import a créées.

    LE STOCK ANTI-DOUBLONS EST LE SEUL REGISTRE de ce lien : chaque ligne
    importée y est entrée en portant à la fois l'import dont elle vient
    (`import_historique_id`) et l'opération qu'elle a créée (`operation_id`,
    ON DELETE CASCADE). Aucune colonne n'a donc été ajoutée à `operation` pour
    retrouver son import — l'information y était déjà.

    « Encore en base » n'est pas une précaution de style : le CASCADE fait
    qu'une opération supprimée à la main depuis l'import a emporté sa ligne du
    stock avec elle. Ce qui reste ici est donc exactement ce qui est encore
    annulable, et une opération déjà supprimée ne se compte pas deux fois.

    LES DEUX JAMBES D'UN VIREMENT. Le stock ne retient que la jambe sortante
    (cf. services/import_bancaire.confirmer) : la seconde est ramenée ici par
    `virement_id`, sans quoi annuler un import laisserait derrière lui une
    demi-écriture sur le compte d'en face."""
    operation_ids = [
        row[0]
        for row in db.query(models.LigneImportBrute.operation_id)
        .filter(
            models.LigneImportBrute.import_historique_id == historique_id,
            models.LigneImportBrute.operation_id.isnot(None),
        )
        .all()
    ]
    if not operation_ids:
        return []

    operations = (
        db.query(models.Operation).filter(models.Operation.id.in_(operation_ids)).all()
    )
    virement_ids = {op.virement_id for op in operations if op.virement_id is not None}
    if virement_ids:
        jambes = (
            db.query(models.Operation)
            .filter(models.Operation.virement_id.in_(virement_ids))
            .all()
        )
        connues = {op.id for op in operations}
        operations.extend(op for op in jambes if op.id not in connues)
    return operations


def compter_operations_annulables(db: Session, preset_id: int) -> dict[int, dict]:
    """historique_id -> {"annulables": n, "sans_lien": n}, pour tous les imports
    d'un preset d'un coup.

    En UNE requête plutôt qu'une par ligne d'historique : la page Import les
    affiche toutes ensemble, et vingt allers-retours pour vingt compteurs
    auraient coûté plus cher que l'affichage lui-même.

    « annulables » compte les LIGNES DE STOCK dont l'opération existe encore,
    pas les opérations elles-mêmes : les deux jambes d'un virement n'en
    occupent qu'une (cf. get_operations_d_un_import), le nombre annoncé est
    donc celui des lignes du relevé qui seront défaites — ce que l'utilisateur
    reconnaît, là où « 24 opérations » pour 12 virements ne lui dirait rien.

    « sans_lien » compte celles qui ne désignent AUCUNE opération, et sert
    uniquement à expliquer pourquoi un import n'est pas annulable. Deux
    situations n'ont rien à voir et se ressembleraient sans ce chiffre :
    l'import dont tout a déjà été supprimé à la main (plus aucune ligne du
    tout, le CASCADE les a emportées), et l'import ANTÉRIEUR à la migration
    0016, dont les lignes sont bien là mais n'ont jamais porté ce lien — celui
    -là ne sera jamais annulable, et le dire évite de chercher une opération
    disparue qui n'a jamais été suivie."""
    rows = (
        db.query(
            models.LigneImportBrute.import_historique_id,
            func.count(models.Operation.id),
            func.count(models.LigneImportBrute.id),
        )
        # OUTER : une ligne sans opération doit compter dans le total, c'est
        # tout l'objet de « sans_lien ». Un JOIN simple les ferait disparaître.
        .outerjoin(
            models.Operation, models.LigneImportBrute.operation_id == models.Operation.id
        )
        .filter(models.LigneImportBrute.preset_id == preset_id)
        .filter(models.LigneImportBrute.import_historique_id.isnot(None))
        .group_by(models.LigneImportBrute.import_historique_id)
        .all()
    )
    return {
        historique_id: {"annulables": nb_operations, "sans_lien": nb_lignes - nb_operations}
        for historique_id, nb_operations, nb_lignes in rows
    }


def delete_import_historique(db: Session, entree: models.ImportHistorique) -> None:
    """Retire la trace de l'import, une fois ses opérations supprimées.

    Les lignes de stock qui la référencent encore sont passées à NULL par le
    ON DELETE SET NULL du modèle — il n'en reste normalement aucune (le CASCADE
    des opérations les a emportées), sauf celles dont l'opération avait déjà
    disparu avant l'annulation."""
    db.delete(entree)
    db.commit()


def get_note_dashboard(db: Session) -> Optional[models.NoteDashboard]:
    """La note libre du dashboard, ou None si rien n'a jamais été écrit."""
    return db.query(models.NoteDashboard).order_by(models.NoteDashboard.id).first()


def set_note_dashboard(db: Session, contenu: str) -> models.NoteDashboard:
    """Écrit la note, en créant la ligne au premier passage.

    Une seule ligne pour toute la base : la note du dashboard est unique, et
    laisser plusieurs lignes s'accumuler ferait dépendre l'affichage d'un ordre
    de lecture."""
    note = get_note_dashboard(db)
    if note is None:
        note = models.NoteDashboard()
        db.add(note)
    note.contenu = contenu
    note.modifie_le = datetime.now()
    db.commit()
    db.refresh(note)
    return note
