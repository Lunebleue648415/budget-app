from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Enum,
    JSON,
    Table,
    Text,
    CheckConstraint,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base
from .constants import (
    TYPES_REMBOURSABLES,
    TYPE_COMPTE_PLACEMENT,
    DomaineImport,
    Frequence,
    ModeComparaison,
    Sens,
    SensAction,
    Statut,
    TypeOperation,
)


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


def _sql_in_list(values):
    parts = [f'"{v}"' if "'" in v else f"'{v}'" for v in values]
    return ", ".join(parts)


class TypeOperationDB(Base):
    """Les familles d'opérations (Opération classique, Dépense remboursable,
    Remboursement reçu, Prêt reçu, Remboursement prêt, Virement interne, et
    Achat / vente de titres).

    Auparavant ce concept n'existait pas en base : quatre de ces types étaient
    des « catégories système » rangées avec les vraies catégories de dépense,
    et les deux autres n'étaient qu'un booléen `remboursable`. D'où des tests
    métier écrits sur des noms de catégorie, fragiles au renommage.

    `code` est la clé technique stable (valeurs de constants.TypeOperation) :
    toute la logique s'y réfère. `nom` est le libellé affiché, que l'utilisateur
    peut renommer sans rien casser. Les lignes sont créées par les migrations
    (0019, puis 0020 pour les titres) et ne sont pas supprimables —
    l'application dépend de leur existence.
    """

    __tablename__ = "type_operation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String, nullable=False, unique=True)
    nom = Column(String, nullable=False)
    ordre = Column(Integer, nullable=False, default=0)
    # True = type géré exclusivement par une page dédiée (cf.
    # constants.TYPES_INTERNES) : jamais proposé dans un menu de type, et refusé
    # par les endpoints génériques /operations. Exposé au frontend pour qu'il
    # filtre ses menus sans réécrire la liste des codes concernés.
    interne = Column(Boolean, nullable=False, default=False)


class Categorie(Base):
    """Catégorie de dépense choisie par l'utilisateur (Alimentaire, Loisirs…).

    Ne contient plus que de vraies catégories depuis 0019 : les quatre
    anciennes catégories système sont devenues des TypeOperationDB. Seules les
    opérations de type `classique` ou `remboursable` en portent une.
    """

    __tablename__ = "categorie"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nom = Column(String, nullable=False, unique=True)
    # Position d'affichage (dropdowns, dashboard, onglet Catégories) ; modifiable
    # par l'utilisateur via les boutons monter/descendre.
    ordre = Column(Integer, nullable=False, default=0)
    # Affichée ou non dans l'histogramme du dashboard (œil de l'onglet
    # Catégories). Réglage d'AFFICHAGE seulement : une catégorie éteinte garde
    # ses opérations, son budget et sa place dans tous les menus — elle ne
    # disparaît que du graphe, où une barre écrasante ou sans intérêt nuit à la
    # lecture des autres.
    visible_dashboard = Column(Boolean, nullable=False, default=True)
    # Index dans la palette de l'histogramme (la palette elle-même vit côté
    # frontend). Attribué à la CRÉATION et jamais recalculé : ni un
    # réordonnancement, ni l'extinction d'une autre catégorie ne doivent changer
    # la couleur d'une barre. Un index n'est repris que si la catégorie qui le
    # portait est supprimée (cf. crud._prochain_couleur_index).
    couleur_index = Column(Integer, nullable=False, default=0)


class Monnaie(Base):
    """Une monnaie dans laquelle des montants sont libellés (Euro, Dollar…).

    L'app ne stocke aucun taux de change et n'additionne jamais deux monnaies :
    chaque solde, chaque KPI et chaque budget est calculé séparément par
    monnaie. `symbole` est ce qui s'affiche à côté des montants ; il n'a pas
    besoin d'être un code ISO, seulement d'être lisible.

    La migration 0021 en crée une seule (l'euro) pour rattacher les données
    existantes ; les suivantes sont créées par l'utilisateur.
    """

    __tablename__ = "monnaie"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nom = Column(String, nullable=False, unique=True)
    symbole = Column(String, nullable=False)
    # Ordre d'affichage (onglets du dashboard, menus) : l'ordre de création par
    # défaut, l'euro restant donc en tête sur une base migrée.
    ordre = Column(Integer, nullable=False, default=0)


class TauxChange(Base):
    """« 1 unité de `monnaie_source` vaut `taux` unités de `monnaie_cible` ».

    REMPLIE PAR L'EXTENSION « Lecture de cours », jamais par le noyau : c'est
    elle qui va lire la page désignée par `url_cours`. La table vit ici quand
    même, comme le reste du schéma, pour que retirer l'extension ne fasse
    perdre ni les liens ni les derniers taux connus (cf. extensions/README.md).

RIEN NE CONVERTIT AVEC, SAUF SUR DEMANDE. Aucun solde, aucun budget, aucune
    opération ne consulte cette table : les montants restent suivis monnaie par
    monnaie. La seule exception est la BASCULE d'agrégation du dashboard,
    apportée par l'extension « Monnaies » (migration 0048) — un geste explicite,
    qui ne réécrit rien et ne survit pas à la fermeture de l'écran. Convertir en
    silence reviendrait à défaire le choix central de l'app.

    UN COUPLE, PAS UNE MONNAIE DE RÉFÉRENCE : l'application n'en a aucune. Le
    sens compte — EUR -> USD et USD -> EUR sont deux lignes, avec deux pages
    d'où les lire, parce que c'est ainsi que les sites les publient.

    `taux` et `maj_le` sont NULL tant qu'aucune lecture n'a abouti : « jamais
    relu », là où un 1.0 par défaut aurait menti.

    `url_cours` À NULL veut dire « saisi à la main » (migration 0048) : personne
    n'ira le relire, et « Lecture de cours » l'ignore. C'est le pendant exact de
    `Action.cours_maj_le` à NULL, qui distingue déjà un cours frais d'un cours
    tapé au clavier.
    """

    __tablename__ = "taux_change"

    id = Column(Integer, primary_key=True, autoincrement=True)
    monnaie_source_id = Column(
        Integer, ForeignKey("monnaie.id", ondelete="CASCADE"), nullable=False
    )
    monnaie_cible_id = Column(
        Integer, ForeignKey("monnaie.id", ondelete="CASCADE"), nullable=False
    )
    url_cours = Column(String, nullable=True)
    taux = Column(Float, nullable=True)
    maj_le = Column(DateTime, nullable=True)

    monnaie_source = relationship("Monnaie", foreign_keys=[monnaie_source_id])
    monnaie_cible = relationship("Monnaie", foreign_keys=[monnaie_cible_id])

    __table_args__ = (
        UniqueConstraint("monnaie_source_id", "monnaie_cible_id", name="uq_taux_change_couple"),
        CheckConstraint(
            "monnaie_source_id <> monnaie_cible_id", name="ck_taux_change_monnaies_distinctes"
        ),
        Index("ix_taux_change_source", "monnaie_source_id"),
        Index("ix_taux_change_cible", "monnaie_cible_id"),
    )


class CompteMonnaie(Base):
    """Une monnaie portée par un compte, et le solde initial du compte DANS
    cette monnaie.

    Un compte multi-devises n'est pas dupliqué en base (ce qui aurait cassé
    tout ce qui pointe vers un compte : opérations, correspondances d'import,
    virements) : il reste une seule ligne `compte`, à laquelle s'accrochent
    autant de lignes ici que de monnaies. Les soldes se calculent alors par
    couple (compte, monnaie) — cf. services/soldes.py.

    `solde_initial` a quitté `compte` pour venir ici : un compte à deux
    monnaies a deux soldes de départ, et un seul champ ne pouvait pas dire
    lequel.
    """

    __tablename__ = "compte_monnaie"

    id = Column(Integer, primary_key=True, autoincrement=True)
    compte_id = Column(Integer, ForeignKey("compte.id", ondelete="CASCADE"), nullable=False)
    monnaie_id = Column(Integer, ForeignKey("monnaie.id"), nullable=False)
    solde_initial = Column(Float, nullable=False, default=0.0)
    # Position dans la liste du compte ; la première est la monnaie proposée
    # par défaut à la saisie et celle retenue pour les lignes importées.
    ordre = Column(Integer, nullable=False, default=0)

    compte = relationship("Compte", back_populates="monnaies")
    monnaie = relationship("Monnaie")

    __table_args__ = (
        UniqueConstraint("compte_id", "monnaie_id", name="uq_compte_monnaie"),
        Index("ix_compte_monnaie_compte", "compte_id"),
        Index("ix_compte_monnaie_monnaie", "monnaie_id"),
    )


class CategorieBudgetMensuel(Base):
    """Budget alloué à une catégorie pour un mois ET une monnaie donnés. Table
    volontairement creuse : un mois sans entrée hérite du budget du mois
    explicite le plus récent qui le précède, dans la même monnaie (voir
    crud.get_budget_categorie).

    La monnaie fait partie de la clé depuis 0021 : un budget « 300 » ne veut
    rien dire si l'on dépense en euros et en dollars sur la même catégorie."""

    __tablename__ = "categorie_budget_mensuel"

    id = Column(Integer, primary_key=True, autoincrement=True)
    categorie_id = Column(
        Integer, ForeignKey("categorie.id", ondelete="CASCADE"), nullable=False
    )
    monnaie_id = Column(Integer, ForeignKey("monnaie.id"), nullable=False)
    annee = Column(Integer, nullable=False)
    mois = Column(Integer, nullable=False)
    montant = Column(Float, nullable=False, default=0.0)

    categorie = relationship("Categorie")
    monnaie = relationship("Monnaie")

    __table_args__ = (
        UniqueConstraint(
            "categorie_id", "annee", "mois", "monnaie_id", name="uq_categorie_budget_mensuel"
        ),
        CheckConstraint("mois >= 1 AND mois <= 12", name="ck_categorie_budget_mensuel_mois"),
        Index("ix_categorie_budget_mensuel_categorie", "categorie_id"),
        Index("ix_categorie_budget_mensuel_monnaie", "monnaie_id"),
    )


class TypeCompte(Base):
    """Type de compte (Courant, Épargne, ou tout autre regroupement créé par
    l'utilisateur). Courant/Épargne sont protégés (systeme=True) : ils pilotent
    des règles métier (dashboard, virements réservés à l'épargne) et ne sont
    donc jamais supprimables."""

    __tablename__ = "type_compte"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nom = Column(String, nullable=False, unique=True)
    systeme = Column(Boolean, nullable=False, default=False)


class Compte(Base):
    __tablename__ = "compte"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nom = Column(String, nullable=False, unique=True)
    type_id = Column(Integer, ForeignKey("type_compte.id"), nullable=False)
    # Position d'affichage AU SEIN DE SON TYPE : les comptes se lisent toujours
    # groupés par type (cartes de la page Comptes, sections du dashboard), un
    # ordre global n'aurait donc rien à ordonner. Fixé par glisser-déposer dans
    # Paramètres > Comptes, et repris tel quel partout ailleurs — le tri par nom
    # d'avant ne laissait aucun moyen de mettre en tête le compte qu'on regarde
    # le plus.
    ordre = Column(Integer, nullable=False, default=0)

    operations = relationship("Operation", back_populates="compte")
    type_compte = relationship("TypeCompte")
    # Au moins une ligne, toujours (garanti par les routeurs) : un compte sans
    # monnaie ne pourrait porter aucune opération.
    monnaies = relationship(
        "CompteMonnaie",
        back_populates="compte",
        order_by="CompteMonnaie.ordre",
        cascade="all, delete-orphan",
    )

    @property
    def type_nom(self) -> str:
        return self.type_compte.nom

    @property
    def monnaie_ids(self) -> set:
        return {lien.monnaie_id for lien in self.monnaies}

    @property
    def monnaie_principale_id(self):
        """La première monnaie du compte : celle proposée par défaut à la
        saisie et retenue pour une ligne importée (un relevé bancaire ne dit
        pas dans quelle monnaie il est libellé)."""
        return self.monnaies[0].monnaie_id if self.monnaies else None

    @property
    def est_placement(self) -> bool:
        """Un compte-titres : son solde en espèces se calcule comme celui de
        n'importe quel compte, mais il porte en plus un portefeuille de titres
        (cf. OperationAction) et n'accepte pas d'opération classique."""
        return self.type_compte.nom == TYPE_COMPTE_PLACEMENT


class Operation(Base):
    __tablename__ = "operation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    compte_id = Column(Integer, ForeignKey("compte.id"), nullable=False)
    type_id = Column(Integer, ForeignKey("type_operation.id"), nullable=False)
    # NULL pour les quatre types à catégorie imposée (remboursement reçu, prêt
    # reçu, remboursement prêt, virement interne) : leur type EST leur
    # classification. Seuls `classique` et `remboursable` portent une catégorie.
    categorie_id = Column(Integer, ForeignKey("categorie.id"), nullable=True)
    nature = Column(String, nullable=False)
    montant = Column(Float, nullable=False)
    # Monnaie du montant. Toujours l'une de celles portées par le compte (cf.
    # CompteMonnaie, vérifié par les routeurs). Les deux écritures d'un virement
    # entre comptes de monnaies différentes en portent donc chacune une
    # distincte, avec leur propre montant — c'est ce qui permet de virer 100 €
    # et d'en recevoir 108 $ sans que l'app ait à connaître un taux.
    monnaie_id = Column(Integer, ForeignKey("monnaie.id"), nullable=False)
    # Conservé en colonne : le type ne suffit pas à le déduire, `virement`
    # recouvrant à lui seul transfert_sortant ET transfert_entrant.
    sens = Column(Enum(Sens, native_enum=False, values_callable=_enum_values), nullable=False)
    statut = Column(
        Enum(Statut, native_enum=False, values_callable=_enum_values), nullable=False
    )
    # Montant fixe initialement dû, conservé tel quel même une fois le remboursement effectué.
    montant_du = Column(Float, nullable=False, default=0.0)
    # Reste à rembourser : diminue (jusqu'à 0) au fil des remboursements liés.
    montant_a_rembourser = Column(Float, nullable=False, default=0.0)
    virement_id = Column(String, nullable=True)
    # Notes libres, sans aucune sémantique : jamais lues, filtrées ni sommées
    # par l'app. Elles n'existent que pour ce qu'aucune colonne ne porte, et ne
    # s'affichent qu'à l'édition. NULL et chaîne vide y valent la même chose.
    notes = Column(String, nullable=True)
    # Récurrence : True pour le modèle ET pour chacune de ses occurrences
    # générées (voir crud.generer_occurrences_recurrentes) -- sert à séparer
    # récurrentes/ponctuelles dans la page Opérations. frequence/recurrence_fin
    # ne sont renseignés que sur le modèle (recurrence_parent_id NULL) ;
    # recurrence_fin NULL = récurrence infinie (bornée à un horizon glissant
    # lors de la génération, jamais persistée comme telle).
    recurrente = Column(Boolean, nullable=False, default=False)
    frequence = Column(
        Enum(Frequence, native_enum=False, values_callable=_enum_values), nullable=True
    )
    recurrence_fin = Column(Date, nullable=True)
    recurrence_parent_id = Column(
        Integer, ForeignKey("operation.id", ondelete="SET NULL"), nullable=True
    )
    # Amortissement : la dépense a bien lieu une seule fois, à `date` (c'est
    # elle qui bouge le solde du compte, ce jour-là et pas un autre), mais elle
    # PÈSE sur plusieurs mois. Les deux bornes délimitent ces mois, incluses,
    # et valent toujours le 1er du mois (normalisé par schemas.OperationBase) :
    # seul le mois compte, le jour n'a rien à dire ici. Elles sont renseignées
    # exactement quand `amorti` est vrai.
    #
    # Deux dates plutôt que la liste des mois concernés : la liste est
    # contiguë par construction, donc entièrement décrite par ses bornes — et
    # surtout, deux colonnes se comparent en SQL. C'est ce qui permet à
    # services/soldes.py de ne charger que les opérations amorties dont la
    # plage recoupe la période affichée, là où une liste JSON aurait imposé de
    # relire toutes les opérations amorties de la base à chaque affichage du
    # dashboard.
    #
    # Aucune opération n'est créée pour les mois couverts : c'est le calcul des
    # agrégats de période qui lit ces colonnes (cf. soldes.part_amortie). Étaler
    # une dépense en N opérations aurait dupliqué en base ce que `montant` dit
    # déjà, et fait diverger le solde du compte du relevé bancaire.
    amorti = Column(Boolean, nullable=False, default=False)
    amortissement_debut = Column(Date, nullable=True)
    amortissement_fin = Column(Date, nullable=True)

    # LES FRAIS COMPRIS DANS `montant` (migration 0051), et rien d'autre.
    #
    # PUREMENT DESCRIPTIF : `montant` reste ce qui a bougé sur le compte, frais
    # compris — ajoutés à ce qui sort, retranchés de ce qui entre (cf.
    # services/import_bancaire._appliquer_frais). Aucun solde, aucun KPI, aucune
    # barre d'histogramme ne lit cette colonne : elle répond à « de quoi ce
    # montant est-il fait », pas à « combien ». C'est la même nature d'annotation
    # que `montant_du`.
    #
    # Sans elle, les frais disparaissaient à l'import : l'aperçu savait écrire
    # « dont frais 2 € », l'opération enregistrée ne portait plus qu'un montant
    # de 102 € dont plus rien ne disait qu'il en contenait 2 de frais.
    #
    # NULL = personne ne l'a jamais renseigné (toutes les opérations d'avant la
    # migration), ce qu'un zéro n'aurait pas su dire.
    frais = Column(Float, nullable=True)
    # La devise des frais, quand elle diffère de celle de l'opération : c'est
    # elle qui décide à quel montant ils s'appliquent sur un virement entre deux
    # monnaies. NULL = celle de l'opération, le cas ordinaire.
    monnaie_frais_id = Column(
        Integer, ForeignKey("monnaie.id", ondelete="SET NULL"), nullable=True
    )

    compte = relationship("Compte", back_populates="operations")
    categorie = relationship("Categorie")
    type_operation = relationship("TypeOperationDB")
    monnaie = relationship("Monnaie", foreign_keys=[monnaie_id])
    monnaie_frais = relationship("Monnaie", foreign_keys=[monnaie_frais_id])
    # Les projets qui la comptent (extension « Projets »). PLUSIEURS, à la
    # différence de la catégorie : un projet regroupe par événement, pas par
    # nature (cf. SousFiltre). La table de liaison est dans le noyau, comme tout
    # schéma — éteindre l'extension masque l'écran sans perdre un lien.
    sous_filtres = relationship(
        "SousFiltre", secondary="operation_sous_filtre", back_populates="operations"
    )
    # Les parts d'une opération DÉCOUPÉE (migration 0049). Vide dans l'immense
    # majorité des cas : une opération porte sa catégorie dans `categorie_id`,
    # et ces lignes n'existent que quand une seule catégorie ne suffit pas.
    # Triées par `ordre` pour que l'écran les réaffiche dans l'ordre saisi.
    decoupes = relationship(
        "OperationDecoupe",
        back_populates="operation",
        cascade="all, delete-orphan",
        order_by="OperationDecoupe.ordre",
    )

    @property
    def est_decoupee(self) -> bool:
        """Cette opération répartit-elle son montant entre plusieurs catégories ?

        LA PRÉSENCE DES PARTS EST LE SEUL TÉMOIN — pas de colonne booléenne à
        maintenir en accord avec elles. C'est la même règle que `remboursable`,
        qui se déduit du type plutôt que d'être stocké : un drapeau et la donnée
        qu'il décrit finissent toujours par diverger."""
        return bool(self.decoupes)

    @property
    def type_code(self) -> str:
        """Le code technique du type, sur lequel s'écrit toute la logique
        métier (jamais le libellé, qui est renommable)."""
        return self.type_operation.code

    @property
    def remboursable(self) -> bool:
        """Remplace l'ancienne colonne booléenne : exactement les deux types
        pour lesquels elle valait 1 (dépense remboursable et prêt reçu)."""
        return TypeOperation(self.type_operation.code) in TYPES_REMBOURSABLES

    @property
    def amortissement_nb_mois(self):
        """Nombre de mois d'amortissement, bornes incluses (None si non
        amortie ; jamais 0, un même mois de début et de fin donnant 1).

        Calculé et non stocké : il se déduit exactement des deux bornes, et une
        troisième colonne à maintenir en accord avec elles n'aurait fait
        qu'ouvrir la possibilité qu'elle ne le soit plus. Le formulaire, lui,
        laisse bien l'utilisateur saisir ce nombre — il en déduit alors la
        borne manquante, c'est-à-dire qu'il fait la conversion à l'endroit où
        elle relève de l'ergonomie, pas du stockage."""
        if not self.amorti or self.amortissement_debut is None or self.amortissement_fin is None:
            return None
        debut = self.amortissement_debut
        fin = self.amortissement_fin
        return (fin.year - debut.year) * 12 + (fin.month - debut.month) + 1

    @property
    def amortissement_montant_par_mois(self):
        """Le montant imputé à chacun des mois couverts (None si non amortie).

        Dérivé pour la même raison que ci-dessus : le stocker aurait obligé à le
        recalculer à chaque changement de `montant` ou de bornes, avec le risque
        qu'un chemin l'oublie. Attention, ce n'est PAS la part que le dashboard
        impute réellement à un mois pour une dépense remboursable : celle-ci se
        calcule sur le reste à charge (montant − montant dû), cf.
        services/soldes._sommes_amorties_par_categorie. C'est une valeur
        d'affichage."""
        nb_mois = self.amortissement_nb_mois
        if nb_mois is None:
            return None
        return self.montant / nb_mois

    __table_args__ = (
        CheckConstraint("montant >= 0", name="ck_operation_montant_positif"),
        CheckConstraint(
            f"sens IN ({_sql_in_list(_enum_values(Sens))})", name="ck_operation_sens"
        ),
        CheckConstraint(
            f"statut IN ({_sql_in_list(_enum_values(Statut))})", name="ck_operation_statut"
        ),
        CheckConstraint(
            f"frequence IS NULL OR frequence IN ({_sql_in_list(_enum_values(Frequence))})",
            name="ck_operation_frequence",
        ),
        Index("ix_operation_categorie_id", "categorie_id"),
        Index("ix_operation_type_id", "type_id"),
        Index("ix_operation_compte_id", "compte_id"),
        Index("ix_operation_date", "date"),
        Index("ix_operation_virement_id", "virement_id"),
        Index("ix_operation_recurrence_parent_id", "recurrence_parent_id"),
        Index("ix_operation_monnaie_id", "monnaie_id"),
    )



class OperationDecoupe(Base):
    """Une part d'une opération DÉCOUPÉE : un montant, une catégorie.

    POURQUOI UNE TABLE PLUTÔT QUE PLUSIEURS OPÉRATIONS. Un plein de courses à
    120 € dont 30 € de produits ménagers est UNE opération : une seule ligne au
    relevé, une seule date, un seul mouvement de compte. La découper en deux
    opérations aurait fait diverger le solde de l'app du relevé bancaire dès
    qu'on en supprime une, et dupliqué en base le libellé, le compte, la
    monnaie et le statut — exactement ce que l'amortissement a refusé de faire
    pour la même raison (cf. Operation.amorti).

    L'OPÉRATION DÉCOUPÉE NE PORTE PLUS DE CATÉGORIE : `categorie_id` passe à
    NULL, comme pour les types à catégorie imposée. Ces lignes SONT sa
    classification, et laisser en plus une catégorie sur l'opération aurait posé
    la question, à chaque calcul, de laquelle des deux compte — un histogramme
    qui additionnerait les deux compterait la dépense deux fois.

    LA SOMME DES PARTS VAUT LE MONTANT, exactement. C'est l'invariant de la
    table : sans lui, l'histogramme ne totaliserait plus les mêmes sorties que
    les KPI posés juste à côté. Il est vérifié en 400 sur les routes
    (routers/operations._valider_decoupes) et rattrapé en dernier filet par
    crud._appliquer_decoupes, sur le modèle de `montant_du` pour les prêts.

    SEUL LE TYPE `classique` EN PORTE. Les autres ont soit une catégorie imposée
    par leur type, soit un montant dû ou une contrepartie dont la répartition
    entre les parts n'aurait pas de sens univoque.
    """

    __tablename__ = "operation_decoupe"

    id = Column(Integer, primary_key=True, autoincrement=True)
    operation_id = Column(
        Integer, ForeignKey("operation.id", ondelete="CASCADE"), nullable=False
    )
    # Obligatoire : une part sans catégorie ne classerait rien, et le montant
    # qu'elle porte disparaîtrait de l'histogramme sans que la somme des parts
    # cesse pour autant de valoir le montant.
    categorie_id = Column(Integer, ForeignKey("categorie.id"), nullable=False)
    montant = Column(Float, nullable=False)
    # Rang d'affichage, posé par l'écran à l'enregistrement. Les parts n'ont pas
    # d'ordre naturel (ni date, ni hiérarchie) et une liste qui se réordonne
    # toute seule d'une ouverture à l'autre du formulaire se lit mal.
    ordre = Column(Integer, nullable=False, default=0)

    operation = relationship("Operation", back_populates="decoupes")
    categorie = relationship("Categorie")

    __table_args__ = (
        CheckConstraint("montant > 0", name="ck_operation_decoupe_montant_positif"),
        Index("ix_operation_decoupe_operation_id", "operation_id"),
        Index("ix_operation_decoupe_categorie_id", "categorie_id"),
    )


class TypeTitre(Base):
    """Une étiquette posée sur un titre : « ETF », « Action en direct »,
    « Obligation », « SCPI »… Créée par l'utilisateur, et rien d'autre qu'un
    libellé.

    AUCUN CALCUL NE LA LIT. Ni un solde, ni une valorisation, ni une plus-value :
    le type sert à REGROUPER pour regarder (cf. l'extension « Vue d'ensemble des
    placements »), jamais à décider. C'est ce qui permet de la laisser
    entièrement libre — rien dans le code ne dépend d'un libellé en particulier,
    il n'y a donc rien à protéger, et pas de `systeme` comme sur `TypeCompte`.

    Une table plutôt qu'une colonne texte sur le titre : un libellé libre saisi
    ligne par ligne donnerait « ETF », « etf » et « E.T.F. » dans le même
    portefeuille, et un camembert en ferait trois parts.
    """

    __tablename__ = "type_titre"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nom = Column(String, nullable=False, unique=True)
    # Ordre d'affichage dans les menus et les légendes : l'ordre de création par
    # défaut, réordonnable ensuite comme les comptes et les catégories.
    ordre = Column(Integer, nullable=False, default=0)


class Action(Base):
    """Un titre détenu ou négociable (action, ETF, obligation…).

    `valeur` est le dernier cours unitaire connu, saisi à la main : l'app n'a
    aucune source de marché, cette valeur ne sert qu'à valoriser le
    portefeuille à l'écran. Elle n'entre jamais dans le calcul d'un solde en
    espèces, lequel ne dépend que des prix réellement payés ou encaissés
    (OperationAction.prix_unitaire).

    Le titre est global, pas rattaché à un compte : le même ETF peut être
    détenu sur deux comptes-titres, et les quantités détenues se lisent par
    couple (compte, titre) -- cf. services/placements.detentions.

    `monnaie_id` est la monnaie de cotation : cours, prix payés et valorisation
    en découlent tous, et un titre ne peut donc s'acheter que depuis un compte
    qui porte cette monnaie.
    """

    __tablename__ = "action"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # LE NOM DU COURTIER, jamais modifié. C'est par lui, à défaut d'ISIN, que
    # l'import RECONNAÎT un titre d'un fichier à l'autre : le renommer ferait
    # que l'import suivant ne le retrouverait plus et scinderait la position en
    # deux titres. Il se lit comme l'ISIN — une donnée du relevé, pas un
    # libellé.
    nom = Column(String, nullable=False, unique=True)
    # CE QU'ON LIT À L'ÉCRAN (migration 0045), quand le nom du courtier est
    # illisible (« AMUNDI IDX SOL MSC WLD-IE-C », tronqué par un export). NULL
    # = pas renommé, et c'est alors `nom` qui s'affiche. Sans unicité : deux
    # parts d'un même fonds peuvent légitimement porter le même libellé, c'est
    # `nom` qui identifie.
    nom_affichage = Column(String, nullable=True)
    valeur = Column(Float, nullable=False, default=0.0)
    monnaie_id = Column(Integer, ForeignKey("monnaie.id"), nullable=False)
    # Page publique d'où relire le cours, et date de la dernière lecture RÉUSSIE
    # (migration 0037). Le noyau ne s'en sert jamais : il n'émet aucune requête
    # réseau, c'est l'extension « lecture-de-cours » qui lit ces deux colonnes.
    # Elles vivent ici quand même, comme le reste du schéma des placements, pour
    # que retirer l'extension ne fasse perdre aucun lien.
    #
    # `cours_maj_le` à NULL veut dire « jamais relu en ligne » : c'est le cas de
    # tout titre dont le cours est saisi à la main, et le seul moyen de
    # distinguer un cours frais d'un cours oublié.
    url_cours = Column(String, nullable=True)
    cours_maj_le = Column(DateTime, nullable=True)
    # LE TYPE DU TITRE (migration 0047) : une étiquette, facultative, que
    # l'utilisateur crée lui-même. NULL = non typé, ce qui est le cas de tous
    # les titres existants et de tout titre créé sans qu'on choisisse. La rendre
    # obligatoire ferait payer à l'import et à la saisie rapide une information
    # dont on n'a pas toujours l'usage.
    type_titre_id = Column(
        Integer, ForeignKey("type_titre.id", ondelete="SET NULL"), nullable=True
    )
    # RANGÉ, PAS EFFACÉ (migration 0040). Un titre entièrement vendu ne se
    # supprime pas — ses mouvements portent des opérations d'espèces réelles, et
    # les effacer réécrirait le solde du compte. L'archiver le retire des listes
    # où l'on choisit un titre, et de la relecture des cours en ligne ; rien
    # d'autre ne change, l'historique reste entier.
    archivee = Column(Boolean, nullable=False, default=False)

    @property
    def nom_affiche(self) -> str:
        """Ce que l'utilisateur lit : son renommage s'il en a fait un, le nom du
        courtier sinon. UN SEUL ENDROIT décide, pour que les écrans ne divergent
        pas — et `nom` reste disponible partout où c'est l'identification qui
        compte (rapprochement à l'import)."""
        return self.nom_affichage or self.nom
    # Code ISIN du titre (migration 0041), la seule dénomination qui ne change
    # jamais : un émetteur renomme son ETF, une fusion rebaptise une action, et
    # deux courtiers écrivent rarement le même nom pour la même ligne. C'est
    # donc lui qui rapproche un titre d'un relevé importé de celui déjà en
    # base, quand le fichier le porte (cf. l'extension « import-placements »).
    #
    # Facultatif : un titre saisi à la main n'en a aucun, et rien dans l'app ne
    # l'exige. Unique quand il est renseigné — un ISIN désigne une valeur et une
    # seule, deux titres qui le partageraient seraient le même. SQLite tolère
    # autant de NULL qu'on veut dans un index unique, les titres sans ISIN ne se
    # gênent donc pas entre eux.
    code_isin = Column(String, nullable=True)

    monnaie = relationship("Monnaie")
    type_titre = relationship("TypeTitre")

    __table_args__ = (
        CheckConstraint("valeur >= 0", name="ck_action_valeur_positive"),
        Index("ix_action_code_isin", "code_isin", unique=True),
    )


class OperationAction(Base):
    """Le versant "titres" d'un achat ou d'une vente ; le versant "espèces" est
    une Operation ordinaire de type `action` (cf. constants.TypeOperation),
    référencée ici.

    Deux lignes plutôt qu'une seule table autonome : le mouvement d'espèces
    reste ainsi une opération comme les autres, et le solde du compte, le
    dashboard et les projections continuent de se calculer sans exception. Les
    deux lignes naissent et meurent ensemble (voir
    services/placements.enregistrer_operation_action) ; l'unicité de
    `operation_id` interdit qu'une écriture d'espèces porte deux mouvements de
    titres.

    La quantité détenue n'est stockée nulle part : elle se somme depuis ces
    lignes (+ à l'achat, − à la vente) pour un couple (compte, titre) donné.
    Stocker un solde de titres imposerait de le maintenir à chaque
    création/suppression, avec le risque de dérive que le reste de l'app évite
    déjà en recalculant (cf. crud._recalculer_montant_a_rembourser).
    """

    __tablename__ = "operation_action"

    id = Column(Integer, primary_key=True, autoincrement=True)
    operation_id = Column(
        Integer, ForeignKey("operation.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    action_id = Column(Integer, ForeignKey("action.id"), nullable=False)
    sens = Column(
        Enum(SensAction, native_enum=False, values_callable=_enum_values), nullable=False
    )
    quantite = Column(Float, nullable=False)
    # Prix unitaire réellement payé (achat) ou encaissé (vente) : le montant de
    # l'opération d'espèces en découle (quantite * prix_unitaire), et le prix de
    # revient du portefeuille s'en déduit.
    prix_unitaire = Column(Float, nullable=False)

    operation = relationship("Operation")
    action = relationship("Action")

    __table_args__ = (
        CheckConstraint("quantite > 0", name="ck_operation_action_quantite_positive"),
        CheckConstraint("prix_unitaire >= 0", name="ck_operation_action_prix_positif"),
        CheckConstraint(
            f"sens IN ({_sql_in_list(_enum_values(SensAction))})",
            name="ck_operation_action_sens",
        ),
        Index("ix_operation_action_action_id", "action_id"),
    )


class ImportPreset(Base):
    """Un format de relevé bancaire nommé (typiquement un par banque) : porte
    sa propre configuration de colonnes (quelles colonnes lire, lesquelles
    exclure de la comparaison de doublons). Les mappings catégorie/compte,
    l'historique et le stock de doublons (ci-dessous) sont tous rattachés à un
    preset — deux formats différents ne doivent jamais se comparer entre eux."""

    __tablename__ = "import_preset"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nom = Column(String, nullable=False)
    # Ce que ce preset sait lire : un relevé bancaire, ou un relevé de compte de
    # placements (migration 0041, cf. constants.DomaineImport). Les deux jeux de
    # propriétés n'ont rien en commun ; le domaine dit lequel des deux les
    # colonnes ci-dessous parlent, et cloisonne les presets de part et d'autre.
    domaine = Column(
        String, nullable=False, default=DomaineImport.bancaire.value
    )
    # Compte de l'app auquel ce format de relevé appartient (typiquement : le
    # relevé d'un compte précis, qui ne nomme donc nulle part le compte
    # concerné). Renseigné, il s'impose à TOUTES les lignes du fichier — ni la
    # colonne « compte bancaire » ni les correspondances mémorisées ne sont
    # consultées (cf. services/import_bancaire._resoudre_ligne). Un virement
    # interne n'en reste pas moins correctement orienté : ce compte est déduit
    # émetteur ou récepteur du signe du montant, comme pour un compte résolu par
    # colonne. NULL (défaut) = comportement historique, le compte vient du
    # fichier.
    compte_id = Column(Integer, ForeignKey("compte.id", ondelete="SET NULL"), nullable=True)
    colonnes = Column(JSON, nullable=False)
    # Index de colonnes (1-based, format brut du fichier) désignées pour la
    # comparaison de doublons (voir LigneImportBrute / services.import_bancaire.
    # detecter_doublon). Ce que la liste DÉSIGNE dépend du mode ci-dessous :
    # les colonnes à ignorer, ou les seules à comparer.
    colonnes_comparaison = Column(JSON, nullable=False, default=list)
    # 'exclusion' (défaut, comportement d'avant la migration 0030) = tout est
    # comparé sauf la liste. 'selection' = rien n'est comparé sauf la liste.
    # Cf. constants.ModeComparaison, qui dit pourquoi les deux existent.
    mode_comparaison = Column(
        String, nullable=False, default=ModeComparaison.exclusion.value
    )
    # False (défaut) = la première ligne du fichier est une ligne de données.
    # True = c'est un en-tête, à sauter. Tous les formats ne mettent pas
    # d'en-tête ; le supposer systématiquement faisait perdre une opération à
    # chaque import (voir services.import_bancaire.lire_lignes_brutes).
    ignorer_premiere_ligne = Column(Boolean, nullable=False, default=False)

    # Vocabulaire de la colonne « Sens » DE CETTE BANQUE : ["Débit", "D"…] et
    # ["Crédit", "C"…]. Listes vides (défaut) = on retombe sur
    # constants.LIBELLES_SENS_SORTIE / _ENTREE, qui couvrent le vocabulaire
    # français courant. Un relevé anglophone ou portugais écrit tout autre
    # chose ; l'app ne peut pas le deviner, mais elle n'a pas non plus à le
    # redemander à chaque import — d'où le stockage ici, par preset (c'est un
    # trait du FORMAT, comme les colonnes).
    #
    # Stockées telles que saisies ; la comparaison se fait sur une forme
    # normalisée (minuscules, sans accents ni espaces, cf.
    # services/import_bancaire._normaliser_libelle).
    libelles_sens_sortie = Column(JSON, nullable=False, default=list)
    libelles_sens_entree = Column(JSON, nullable=False, default=list)

    # Même mécanique pour la colonne « État » : le vocabulaire des trois issues
    # possibles d'une ligne (exécutée, en attente, refusée — cf.
    # constants.StatutImport). Listes vides = LIBELLES_STATUT_DEFAUT.
    libelles_statut_execute = Column(JSON, nullable=False, default=list)
    libelles_statut_attente = Column(JSON, nullable=False, default=list)
    libelles_statut_refuse = Column(JSON, nullable=False, default=list)

    # Même mécanique encore, pour la colonne « Type d'opération » d'un relevé de
    # placements : ce que CE courtier écrit pour dire achat, vente, ou mouvement
    # d'espèces. Listes vides (défaut) = constants.LIBELLES_TYPE_PLACEMENT_DEFAUT.
    # Vides aussi, et pour toujours, sur un preset bancaire : il ne lit pas cette
    # colonne. Les trois vocabulaires vivent ici plutôt que dans une table à part
    # pour la même raison que les deux précédents — c'est un trait du FORMAT.
    # CE QUE LE FICHIER RACONTE, pour un preset de placements : une liste
    # d'opérations, ou une PHOTOGRAPHIE du compte à un instant donné
    # (constants.ModeLecturePlacement, migration 0046). NULL vaut `operations` —
    # ce que sont tous les presets antérieurs, et le seul mode qui existait.
    #
    # Sur `import_preset` et non sur une table à part : les deux modes partagent
    # tout le reste (correspondances, historique, annulation, stock
    # anti-doublons), et ne diffèrent que par les colonnes lues et le sens d'une
    # ligne. Sans objet pour un preset bancaire, comme les trois vocabulaires
    # ci-dessous.
    mode_lecture = Column(String, nullable=True)

    libelles_type_achat = Column(JSON, nullable=False, default=list)
    libelles_type_vente = Column(JSON, nullable=False, default=list)
    libelles_type_transfert = Column(JSON, nullable=False, default=list)

    # La « configuration avancée » ne se stocke nulle part à part : ses
    # propriétés (compte bancaire, sens, monnaie, montant/monnaie reçus, frais
    # et leur monnaie — cf. constants.PROPRIETES_IMPORT_AVANCEES) sont des
    # colonnes comme les autres, dans `colonnes` ci-dessus. Seul le frontend les
    # présente à part, pour qu'un preset ordinaire n'ait pas à les croiser.
    #
    # Les colonnes supplémentaires nommées et les formules façon tableur, qui
    # portaient auparavant le montant reçu et les frais, ont disparu avec la
    # migration 0026 : ces deux montants ont désormais leur propre propriété.

    compte = relationship("Compte")

    # L'unicité du nom porte sur le COUPLE (domaine, nom) et non sur le nom seul
    # (migration 0041) : « Boursorama » désigne légitimement un relevé bancaire
    # ET un relevé de compte-titres, ce sont deux formats sans rapport. Les
    # cloisonner jusque dans les noms aurait obligé à inventer des suffixes.
    __table_args__ = (
        UniqueConstraint("domaine", "nom", name="uq_import_preset_domaine_nom"),
    )


class ImportCategorieMapping(Base):
    """Mémorise, une fois pour toutes, à quelle catégorie de dépense renvoie une
    catégorie du relevé bancaire — pour ne pas la redemander à chaque import.
    Scopé par preset : un même nom bancaire peut légitimement correspondre à
    autre chose selon la banque.

    La cible est toujours une catégorie. Entre 0019 et 0022 elle pouvait aussi
    être un TYPE d'opération, mais les quatre types concernés ne portent par
    nature aucune catégorie : les proposer ici mélangeait deux axes. Le type est
    désormais posé exclusivement par les règles de catégorisation, évaluées
    AVANT les correspondances (cf. services/import_bancaire._resoudre_ligne).
    """

    __tablename__ = "import_categorie_mapping"

    id = Column(Integer, primary_key=True, autoincrement=True)
    preset_id = Column(Integer, ForeignKey("import_preset.id", ondelete="CASCADE"), nullable=False)
    nom_banque = Column(String, nullable=False)
    categorie_id = Column(Integer, ForeignKey("categorie.id", ondelete="CASCADE"), nullable=False)

    categorie = relationship("Categorie")

    __table_args__ = (
        UniqueConstraint("preset_id", "nom_banque", name="uq_import_categorie_mapping_preset_nom"),
    )


class ImportCompteMapping(Base):
    """Idem pour les noms de compte du relevé bancaire, scopé par preset."""

    __tablename__ = "import_compte_mapping"

    id = Column(Integer, primary_key=True, autoincrement=True)
    preset_id = Column(Integer, ForeignKey("import_preset.id", ondelete="CASCADE"), nullable=False)
    nom_banque = Column(String, nullable=False)
    compte_id = Column(Integer, ForeignKey("compte.id", ondelete="CASCADE"), nullable=False)

    compte = relationship("Compte")

    __table_args__ = (
        UniqueConstraint("preset_id", "nom_banque", name="uq_import_compte_mapping_preset_nom"),
    )


class ImportMonnaieMapping(Base):
    """Idem pour les devises du relevé, scopé par preset.

    Un fichier écrit « EUR », « USD », « BRL » ; l'app connaît des monnaies
    nommées « Euro », « Dollar »… avec leur symbole. Aucun des deux ne peut se
    déduire de l'autre en général, d'où la même mécanique de correspondance
    mémorisée que pour les catégories et les comptes : l'utilisateur tranche
    une fois, l'app se souvient. C'est la SEULE source de rattachement — même
    un libellé identique au nom d'une monnaie de l'app passe par ici (cf.
    services/import_bancaire._resoudre_monnaie)."""

    __tablename__ = "import_monnaie_mapping"

    id = Column(Integer, primary_key=True, autoincrement=True)
    preset_id = Column(Integer, ForeignKey("import_preset.id", ondelete="CASCADE"), nullable=False)
    nom_banque = Column(String, nullable=False)
    monnaie_id = Column(Integer, ForeignKey("monnaie.id", ondelete="CASCADE"), nullable=False)

    monnaie = relationship("Monnaie")

    __table_args__ = (
        UniqueConstraint("preset_id", "nom_banque", name="uq_import_monnaie_mapping_preset_nom"),
    )


class ImportHistorique(Base):
    """Trace de chaque import confirmé, affichée dans la page Import (pour le preset concerné)."""

    __tablename__ = "import_historique"

    id = Column(Integer, primary_key=True, autoincrement=True)
    preset_id = Column(Integer, ForeignKey("import_preset.id", ondelete="CASCADE"), nullable=False)
    date_import = Column(DateTime, nullable=False)
    nom_fichier = Column(String, nullable=True)
    operations_creees = Column(Integer, nullable=False, default=0)
    lignes_ignorees = Column(Integer, nullable=False, default=0)
    doublons_detectes = Column(Integer, nullable=False, default=0)

    __table_args__ = (Index("ix_import_historique_preset", "preset_id"),)


class LigneImportBrute(Base):
    """Stock centralisé de toutes les lignes déjà importées SOUS UN PRESET
    DONNÉ, dans leur format brut intégral (toutes les colonnes du fichier
    Excel, pas seulement celles mappées par ImportPreset.colonnes) — sert à
    détecter les doublons d'un import à l'autre, mais seulement au sein du
    même preset (voir services.import_bancaire.detecter_doublon). Jamais
    vidée ; une table par preset au sens logique (filtrée par preset_id),
    pas une table SQL par preset."""

    __tablename__ = "ligne_import_brute"

    id = Column(Integer, primary_key=True, autoincrement=True)
    preset_id = Column(Integer, ForeignKey("import_preset.id", ondelete="CASCADE"), nullable=False)
    # {"1": valeur_colonne_1, "2": valeur_colonne_2, ...} — clé = index de
    # colonne (1-based) en string (contrainte JSON), valeurs déjà converties
    # en types JSON-safe (dates en isoformat).
    donnees = Column(JSON, nullable=False)
    import_historique_id = Column(
        Integer, ForeignKey("import_historique.id", ondelete="SET NULL"), nullable=True
    )
    # Opération que cette ligne a créée. Le CASCADE est le cœur du mécanisme :
    # supprimer une opération retire aussi sa ligne du stock anti-doublons,
    # sans quoi le même relevé ne pourrait plus jamais être réimporté après
    # une suppression. Nullable pour les lignes historiques (antérieures à la
    # migration 0016), qui n'ont jamais porté ce lien.
    operation_id = Column(
        Integer, ForeignKey("operation.id", ondelete="CASCADE"), nullable=True
    )
    date_creation = Column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_ligne_import_brute_preset", "preset_id"),
        Index("ix_ligne_import_brute_historique", "import_historique_id"),
        Index("ix_ligne_import_brute_operation", "operation_id"),
    )


class RegleCategorisation(Base):
    """Classement automatique d'une ligne importée selon ses libellés.

    Globale (pas de preset_id) : les mots-clés visés ("PRET", "REMBOURSEMENT",
    "REMBOURSABLE"...) ne dépendent pas de la banque, une même règle sert donc
    tous les formats. Évaluées dans l'ordre de `ordre`, la première qui
    correspond pose le type (voir services/regles_categorisation) — c'est la
    hiérarchie qui permet de placer les cas particuliers avant les cas
    généraux. Une règle qui ne coche pas `arreter_apres` laisse l'évaluation
    continuer : les suivantes complètent alors ce qu'elle a laissé ouvert,
    sans jamais défaire ce qu'elle a décidé.

    L'action se lit en deux temps, comme dans le reste de l'app : d'abord le
    type d'opération, puis -- seulement pour les types qui l'admettent
    (classique et remboursable) -- la catégorie de dépense. Les quatre autres
    types ne portent aucune catégorie (leur type EST leur classification), donc
    rien à choisir : `categorie_id` reste NULL. `remboursable` n'est plus
    stocké, il se déduit du type.
    """

    __tablename__ = "regle_categorisation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nom = Column(String, nullable=False)
    ordre = Column(Integer, nullable=False, default=0)
    actif = Column(Boolean, nullable=False, default=True)
    # Une NOTE LIBRE sur la règle (migration 0050), jamais lue par
    # l'application. Le nom et les conditions disent ce qu'une règle fait ; ils
    # ne disent pas POURQUOI elle existe — quel relevé l'a rendue nécessaire,
    # quel cas particulier elle rattrape. Chaîne vide (jamais NULL) quand rien
    # n'est écrit, comme `sous_filtre.description`.
    description = Column(String, nullable=False, default="")
    # Faut-il s'arrêter là quand cette règle correspond ? Coché par défaut :
    # c'est le comportement historique (première règle gagnante). Décoché,
    # l'évaluation continue vers le bas, les règles suivantes ne pouvant que
    # compléter ce qui n'a pas encore été décidé.
    arreter_apres = Column(Boolean, nullable=False, default=True)

    # Action appliquée quand la règle correspond : le type d'abord, puis --
    # seulement pour les types à catégorie libre -- la catégorie. FK vers
    # type_operation depuis 0019, pour ne pas garder deux vocabulaires (une
    # chaîne ici, une table là) pour la même notion.
    type_id = Column(Integer, ForeignKey("type_operation.id", ondelete="CASCADE"), nullable=False)
    categorie_id = Column(
        Integer, ForeignKey("categorie.id", ondelete="CASCADE"), nullable=True
    )
    # Le compte EN FACE, uniquement pour le type « virement interne » : un
    # virement décrit deux comptes, et le relevé n'en nomme qu'un. Sans lui, la
    # ligne arrive incomplète dans l'aperçu et bloque l'import jusqu'à une
    # reprise manuelle (cf. services/import_bancaire._erreur_ligne). NULL pour
    # tous les autres types, qui ne touchent qu'un seul compte.
    compte_autre_id = Column(
        Integer, ForeignKey("compte.id", ondelete="SET NULL"), nullable=True
    )

    # {"operateur": "ET"|"OU", "groupes": [
    #     {"operateur": "ET"|"OU", "conditions": [
    #         {"champ": "nature", "operateur": "contient", "valeur": "PRET"}]}]}
    # Deux niveaux : suffisant pour "(A OU B) ET (C OU D)".
    conditions = Column(JSON, nullable=False, default=dict)

    categorie = relationship("Categorie")
    type_operation = relationship("TypeOperationDB")
    compte_autre = relationship("Compte")
    # La DÉCOUPE que la règle impose (migration 0049). Vide = la règle pose une
    # catégorie unique, comme avant. Non vide, elle remplace `categorie_id` :
    # les deux ne peuvent pas coexister, le routeur neutralise l'un dès que
    # l'autre est renseigné.
    decoupes = relationship(
        "RegleDecoupe",
        back_populates="regle",
        cascade="all, delete-orphan",
        order_by="RegleDecoupe.ordre",
    )

    @property
    def type_code(self) -> str:
        """Exposé tel quel par RegleCategorisationRead : évite au frontend de
        recroiser la table des types pour un simple affichage."""
        return self.type_operation.code

    __table_args__ = (
        Index("ix_regle_categorisation_ordre", "ordre"),
        Index("ix_regle_categorisation_compte_autre_id", "compte_autre_id"),
    )


class RegleDecoupe(Base):
    """Une part de la découpe qu'une règle impose : une catégorie, et une
    FORMULE qui dit combien lui revient.

    POURQUOI UNE FORMULE ET PAS UN MONTANT. Une règle s'applique à des lignes
    dont on ne connaît pas le montant à l'avance : « les 50 premiers euros de
    chaque note de restaurant vont en Repas, le reste en Sorties » ne se dit pas
    avec deux nombres fixes. La formule prend le montant de la ligne comme
    variable (`montant`), et sait en tirer une part : `min(montant; 50)` pour la
    première, `reste` pour la seconde.

    La grammaire acceptée tient en peu de choses — nombres, `montant`, `reste`,
    les quatre opérations, les parenthèses, `min` et `max` — et elle est lue par
    un parseur écrit à la main (cf. services/formule_decoupe.py). JAMAIS `eval` :
    ces chaînes viennent d'un formulaire, et une expression Python arbitraire
    exécutée côté serveur n'est pas une fonctionnalité, c'est une porte.

    `reste` NE VAUT QUE SUR LA DERNIÈRE PART, et c'est ce qui rend l'invariant
    « somme des parts = montant » tenable : les parts calculées prennent ce que
    leur formule dit, la dernière prend ce qui reste. Sans elle, l'utilisateur
    devrait écrire une soustraction exacte de toutes les précédentes, et la
    moindre erreur d'arrondi produirait une découpe refusée à l'import.
    """

    __tablename__ = "regle_decoupe"

    id = Column(Integer, primary_key=True, autoincrement=True)
    regle_id = Column(
        Integer, ForeignKey("regle_categorisation.id", ondelete="CASCADE"), nullable=False
    )
    categorie_id = Column(
        Integer, ForeignKey("categorie.id", ondelete="CASCADE"), nullable=False
    )
    # Expression textuelle, conservée telle que l'utilisateur l'a écrite : c'est
    # elle qu'on lui réaffiche. Sa validité est vérifiée à l'écriture (le
    # parseur la relit), jamais devinée à la lecture.
    formule = Column(String, nullable=False)
    ordre = Column(Integer, nullable=False, default=0)

    regle = relationship("RegleCategorisation", back_populates="decoupes")
    categorie = relationship("Categorie")

    __table_args__ = (Index("ix_regle_decoupe_regle_id", "regle_id"),)


class RemboursementLien(Base):
    """Lie une opération de catégorie 'Remboursements' à la dépense remboursable qu'elle règle."""

    __tablename__ = "remboursement_lien"

    id = Column(Integer, primary_key=True, autoincrement=True)
    operation_remboursement_id = Column(
        Integer, ForeignKey("operation.id", ondelete="CASCADE"), nullable=False
    )
    operation_depense_id = Column(
        Integer, ForeignKey("operation.id", ondelete="CASCADE"), nullable=False
    )
    # Montant réellement transféré pour CE lien (permet un remboursement partiel :
    # plusieurs remboursements peuvent couvrir des portions d'une même dépense).
    montant = Column(Float, nullable=False, default=0.0)

    __table_args__ = (
        UniqueConstraint(
            "operation_remboursement_id",
            "operation_depense_id",
            name="uq_remboursement_lien",
        ),
        Index("ix_remboursement_lien_remboursement", "operation_remboursement_id"),
        Index("ix_remboursement_lien_depense", "operation_depense_id"),
    )


class RegleImportPlacement(Base):
    """Ce qu'une ligne de relevé de compte-titres décrit : un achat, une vente,
    ou un transfert d'espèces — déduit de ses libellés.

    LE PENDANT DE `RegleCategorisation`, POUR L'AUTRE DOMAINE D'IMPORT, et la
    même mécanique de conditions (même JSON, même évaluateur — cf.
    services/regles_categorisation.evaluer_regle). Ce qui change est l'ACTION :
    une règle bancaire pose un type d'opération et éventuellement une catégorie,
    une règle de placement ne pose qu'une chose, le type de placement, parce
    qu'une ligne de compte-titres n'a rien d'autre à décider.

    POURQUOI ELLE EXISTE À CÔTÉ DU VOCABULAIRE DU PRESET. Les trois listes de
    mots-clés (`ImportPreset.libelles_type_*`) reconnaissent un libellé ENTIER :
    « Achat » est un achat, et rien d'autre ne l'est. Un courtier qui écrit
    « ACHAT COMPTANT ETF MSCI WORLD » sur chaque ligne, avec le nom du titre
    dedans, ne peut être lu par aucune liste fermée — il faut pouvoir dire
    « contient ACHAT ». C'est ce que ces règles ajoutent, et elles sont
    consultées AVANT le vocabulaire : ce qu'on a écrit explicitement passe avant
    ce qui est reconnu par correspondance exacte.

    GLOBALES, sans preset_id, comme les règles bancaires : une règle est une
    phrase sur des libellés, et rien n'oblige deux courtiers à en avoir de
    différentes. Le vocabulaire, lui, reste attaché au preset — c'est là qu'est
    la différence de vocabulaire d'un courtier à l'autre.

    Pas de `arreter_apres` ici, contrairement aux règles bancaires : celles-là
    peuvent se compléter (l'une pose le type, l'autre la catégorie), alors
    qu'une règle de placement ne décide QUE du type. Rien à compléter, donc
    rien à continuer : la première qui correspond a tout dit.
    """

    __tablename__ = "regle_import_placement"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nom = Column(String, nullable=False)
    ordre = Column(Integer, nullable=False, default=0)
    actif = Column(Boolean, nullable=False, default=True)
    # Une NOTE LIBRE sur la règle (migration 0050), jamais lue par
    # l'application. Le nom et les conditions disent ce qu'une règle fait ; ils
    # ne disent pas POURQUOI elle existe — quel relevé l'a rendue nécessaire,
    # quel cas particulier elle rattrape. Chaîne vide (jamais NULL) quand rien
    # n'est écrit, comme `sous_filtre.description`.
    description = Column(String, nullable=False, default="")

    # "achat" | "vente" | "transfert" (constants.TypeOperationPlacement). Une
    # chaîne et non une FK : ces trois valeurs sont câblées dans le code de
    # l'import (elles décident de créer un couple titre/espèces ou un virement),
    # une table ne les rendrait pas plus extensibles pour autant.
    type_placement = Column(String, nullable=False)

    # LE TYPE DE TITRE que cette règle pose (migration 0047), quand elle
    # reconnaît un achat ou une vente. NULL = la règle ne dit rien du type, ce
    # qui reste le cas de toutes les règles existantes.
    #
    # POSÉ SUR LE TITRE, PAS SUR LA LIGNE : un type appartient à la valeur
    # (« MSCI World » EST un ETF), pas au mouvement qui la touche. La règle ne
    # l'écrit donc qu'au moment où l'import CRÉE le titre, et ne réécrit jamais
    # celui d'un titre déjà connu — sans quoi un import mal réglé retyperait
    # silencieusement tout un portefeuille.
    type_titre_id = Column(
        Integer, ForeignKey("type_titre.id", ondelete="SET NULL"), nullable=True
    )

    # Le compte EN FACE, uniquement pour le type « transfert » (migration
    # 0045) : un relevé de compte-titres ne décrit qu'un côté du mouvement, et
    # sans ce second compte la ligne arrive incomplète dans l'aperçu et doit
    # être reprise à la main avant de pouvoir être importée. Exactement le rôle
    # que `RegleCategorisation.compte_autre_id` joue côté bancaire.
    #
    # UN SEUL COMPTE, et le SENS n'est pas demandé : il se déduit du signe du
    # montant, comme partout ailleurs dans cet import. NULL pour un achat ou une
    # vente, qui ne touchent qu'un compte.
    compte_autre_id = Column(
        Integer, ForeignKey("compte.id", ondelete="SET NULL"), nullable=True
    )

    # Même forme que RegleCategorisation.conditions, aux champs près : ici
    # `type_brut`, `nom_valeur_brut` et `code_isin_brut` — les trois colonnes
    # TEXTE que le fichier porte (cf. constants.CHAMPS_REGLE_PLACEMENT_VALIDES).
    conditions = Column(JSON, nullable=False, default=dict)

    compte_autre = relationship("Compte")
    type_titre = relationship("TypeTitre")


class InteretPercu(Base):
    """Un versement d'intérêts REÇU, tel que le relevé l'annonce (migration
    0052, extension « Intérêts perçus »).

    SAISI, ET NON CALCULÉ. La version précédente de cette extension partait d'un
    taux annuel et d'une fréquence, et reconstituait les intérêts en découpant
    le temps en périodes sans mouvement. Le calcul était juste, et c'était son
    problème : il ne pouvait l'être que si l'app connaissait TOUS les mouvements
    du compte, à leur date exacte, depuis l'ouverture. Un livret ouvert avant la
    première ligne importée, un taux qui change en cours d'année (le Livret A
    l'a fait deux fois en 2025), une banque qui arrondit autrement — et le
    chiffre affiché diverge du relevé sans que rien ne dise lequel croire. La
    banque, elle, ANNONCE le montant : le saisir prend dix secondes et vaut
    n'importe quelle reconstitution.

    UN CALCUL D'AFFICHAGE MALGRÉ TOUT : aucun solde, aucun KPI, aucune
    projection du noyau ne lit cette table, et rien n'est jamais écrit en
    opération. Si l'intérêt doit bouger le solde, c'est que le relevé le porte —
    il entrera donc par l'import, comme n'importe quelle autre ligne. Une base
    dont l'extension est éteinte se comporte exactement comme si elle n'existait
    pas.

    Dans le noyau bien que l'écran soit dans l'extension : une extension
    n'emporte jamais son schéma. L'éteindre masque l'écran et garde les
    montants.
    """

    __tablename__ = "interet_percu"

    id = Column(Integer, primary_key=True, autoincrement=True)
    compte_id = Column(Integer, ForeignKey("compte.id", ondelete="CASCADE"), nullable=False)
    # UNE MONNAIE PAR LIGNE, comme partout : l'app ne connaît aucun taux de
    # change et n'additionne jamais deux devises. Un compte multi-devises reçoit
    # donc une ligne par devise.
    monnaie_id = Column(Integer, ForeignKey("monnaie.id"), nullable=False)
    # La date du relevé. C'est par elle que les lignes se regroupent par année.
    date = Column(Date, nullable=False)
    # Strictement positif (contrainte en base) : un intérêt PERÇU est une
    # entrée. Zéro se dit en ne saisissant rien, et un négatif serait des frais.
    montant = Column(Float, nullable=False)
    # Texte libre, jamais lu par un calcul — « intérêts 2025 », « prime de
    # fidélité ». Non nullable et vide par défaut, comme les autres notes du
    # schéma : un NULL aurait ajouté un second cas à tester dans chaque écran.
    libelle = Column(String, nullable=False, default="")

    compte = relationship("Compte")
    monnaie = relationship("Monnaie")


class NoteDashboard(Base):
    """Bloc-notes libre du dashboard : une seule ligne pour toute la base.

    Aucune sémantique — l'app ne le lit jamais, ne le filtre pas, ne l'additionne
    pas. C'est l'endroit pour ce qu'aucun champ ne porte : « vérifier le
    prélèvement EDF », « relancer Marie pour les 40 € ».

    La ligne est créée à la demande (cf. crud.set_note_dashboard) plutôt que
    semée par la migration : une base fraîche n'a rien à dire, et une note vide
    n'est pas une note.
    """

    __tablename__ = "note_dashboard"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contenu = Column(Text, nullable=False, default="")
    modifie_le = Column(DateTime, nullable=True)


# ---------- Sous-filtres (extension « Projets ») ----------


# UNE TABLE D'ASSOCIATION NUE, sans classe : le lien ne porte AUCUNE donnée
# propre — ni date, ni part, ni commentaire. Lui donner une classe aurait ajouté
# un objet à charger, à valider et à faire vivre pour n'exprimer qu'un couple
# d'identifiants.
#
# CASCADE des deux côtés : supprimer une opération ou un projet retire les liens
# qui le nommaient. C'est la seule chose qu'une suppression doit emporter — les
# opérations d'un projet supprimé, elles, restent intactes, un projet n'étant
# qu'une VUE sur des opérations qui existent sans lui.
operation_sous_filtre = Table(
    "operation_sous_filtre",
    Base.metadata,
    Column(
        "operation_id",
        Integer,
        ForeignKey("operation.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "sous_filtre_id",
        Integer,
        ForeignKey("sous_filtre.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    # L'écran part TOUJOURS du projet vers ses opérations : c'est ce parcours-là
    # qu'il faut indexer. Le sens inverse est déjà servi par la clé primaire,
    # dont `operation_id` est la première colonne.
    Index("ix_operation_sous_filtre_sous_filtre", "sous_filtre_id"),
)


class SousFiltre(Base):
    """Un regroupement d'opérations choisies à la main : un voyage, un
    déménagement, un projet.

    CE N'EST PAS UNE CATÉGORIE, et c'est toute la différence. Une catégorie
    classe une dépense par NATURE, une et une seule, et porte un budget mensuel :
    « Alimentaire », « Transports ». Un projet regroupe par ÉVÉNEMENT, à travers
    les catégories et les comptes — le billet de train, l'hôtel et les courses
    d'un même voyage restent chacun dans leur catégorie, et se retrouvent
    ensemble ici.

    D'où la relation MULTIPLE : une opération appartient à autant de projets
    qu'on veut (les courses du 12 août sont à la fois « Vacances Italie » et
    « Anniversaire de Marie »), là où sa catégorie est unique par construction.

    RIEN NE SE CALCULE À PARTIR D'UN PROJET. Ni solde, ni budget, ni KPI du
    dashboard : le total d'un projet est une somme affichée, jamais une donnée
    qui influe sur le reste. C'est ce qui permet à une opération d'être dans
    trois projets sans que rien ne soit compté trois fois nulle part.

    LA PROPRIÉTÉ NE SE SAISIT PAS DEPUIS L'OPÉRATION : on constitue un projet
    depuis son écran, en y versant des opérations. Une case de plus dans le
    formulaire d'opération aurait fait payer un choix à chaque saisie, alors
    qu'un projet se remplit par lots, après coup, quand on sait qu'il existe.
    """

    __tablename__ = "sous_filtre"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nom = Column(String, nullable=False, unique=True)
    # Ce que le projet recouvre, en une phrase : « du 3 au 17 août, Rome et
    # Naples ». Sans sémantique — jamais lue, ni filtrée, ni sommée.
    description = Column(Text, nullable=False, default="")
    # L'ordre d'affichage, choisi par l'utilisateur. Un projet en cours se met
    # en tête, un projet clos descend : c'est un classement de lecture, comme
    # celui des comptes et des catégories.
    ordre = Column(Integer, nullable=False, default=0)

    operations = relationship(
        "Operation",
        secondary=operation_sous_filtre,
        back_populates="sous_filtres",
        # Trié comme la liste des opérations de l'app : les plus récentes
        # d'abord, l'id départageant deux opérations du même jour.
        order_by="desc(Operation.date), desc(Operation.id)",
    )
