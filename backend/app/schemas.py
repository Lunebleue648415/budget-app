from datetime import date as date_type, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .constants import (
    CHAMPS_REGLE_PLACEMENT_VALIDES,
    CHAMPS_REGLE_VALIDES,
    NB_MAX_PARTS_DECOUPE,
    OPERATEURS_NOMBRE,
    operateurs_admis,
    TypeOperation,
    ConnecteurRegle,
    DomaineImport,
    Frequence,
    ModeComparaison,
    ModeLecturePlacement,
    OperateurRegle,
    Sens,
    SensAction,
    Statut,
    TypeOperationPlacement,
)


class MonnaieCreate(BaseModel):
    nom: str = Field(min_length=1)
    # Ce qui s'affiche à côté des montants : "€", "$", "CHF"… Pas un code ISO,
    # l'app ne s'en sert que pour l'affichage.
    symbole: str = Field(min_length=1, max_length=8)


class MonnaieUpdate(BaseModel):
    nom: Optional[str] = Field(default=None, min_length=1)
    symbole: Optional[str] = Field(default=None, min_length=1, max_length=8)


class MonnaieRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nom: str
    symbole: str
    ordre: int


class TypeCompteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nom: str
    systeme: bool


class CompteMonnaieInput(BaseModel):
    """Une monnaie portée par un compte, et le solde de départ du compte dans
    cette monnaie. L'ordre de la liste fait foi : la première est la monnaie
    proposée par défaut à la saisie."""

    monnaie_id: int
    solde_initial: float = 0.0


class CompteMonnaieRead(CompteMonnaieInput):
    model_config = ConfigDict(from_attributes=True)

    monnaie_nom: str
    monnaie_symbole: str


class CompteBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nom: str
    type_id: int


class CompteCreate(CompteBase):
    # Au moins une : un compte sans monnaie ne pourrait porter aucune opération.
    monnaies: list[CompteMonnaieInput] = Field(min_length=1)


class CompteUpdate(BaseModel):
    nom: Optional[str] = None
    type_id: Optional[int] = None
    # None = ne pas toucher aux monnaies ; une liste les remplace toutes (le
    # routeur refuse de retirer une monnaie encore utilisée par une opération).
    monnaies: Optional[list[CompteMonnaieInput]] = Field(default=None, min_length=1)


class CompteRead(CompteBase):
    id: int
    type_nom: str
    monnaies: list[CompteMonnaieRead]


class CategorieCreate(BaseModel):
    nom: str = Field(min_length=1)


class CategorieUpdate(BaseModel):
    """Le renommage, et lui seul. Le budget se règle par sa propre route (il
    dépend d'un mois et d'une monnaie), la visibilité par la sienne."""

    nom: str = Field(min_length=1)


class CategorieRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nom: str
    ordre: int
    # Affichée dans l'histogramme du dashboard. N'a aucun effet ailleurs : la
    # catégorie reste proposée partout et garde ses opérations.
    visible_dashboard: bool = True
    # Couleur de la catégorie dans l'histogramme, sous forme d'index de palette
    # (cf. models.Categorie.couleur_index).
    couleur_index: int = 0


class CategorieVisibiliteUpdate(BaseModel):
    """Le seul réglage d'affichage d'une catégorie, isolé de tout le reste : le
    nom n'est pas modifiable et le budget a son propre endpoint (il dépend d'un
    mois et d'une monnaie, pas de la catégorie seule)."""

    visible_dashboard: bool


class TypeOperationRead(BaseModel):
    """Les familles d'opérations. `code` est la clé technique stable sur
    laquelle le frontend écrit sa logique ; `nom` n'est qu'un libellé."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    nom: str
    ordre: int
    # True = géré par une page dédiée (titres) : à exclure des menus de type
    # (formulaire d'opération, règles, correspondances d'import).
    interne: bool = False


class TypeOperationUpdate(BaseModel):
    """Seul le libellé est modifiable : le code porte la logique métier."""

    nom: str = Field(min_length=1)


class ReordonnerCategoriesInput(BaseModel):
    ordre: list[int]


class ReordonnerComptesInput(BaseModel):
    """Les ids des comptes d'UN type, dans l'ordre voulu : l'ordre d'un compte
    ne se lit qu'au sein de son type."""

    ordre: list[int]


class BudgetMensuelSet(BaseModel):
    montant: float = Field(ge=0)


class BudgetMensuelRead(BaseModel):
    annee: int
    mois: int
    # Le budget est propre à une monnaie : « 300 » ne veut rien dire si la
    # catégorie est dépensée en euros et en dollars.
    monnaie_id: int
    montant: float
    # False si ce montant est hérité d'un mois précédent (aucune entrée
    # explicite pour ce mois précis) ; True si ce mois a sa propre valeur.
    explicite: bool


class BudgetCategorieRead(BudgetMensuelRead):
    categorie_id: int
    categorie_nom: str


class OperationLieeRead(BaseModel):
    id: int
    nature: str
    # Montant réellement échangé pour CE lien spécifique (distinct du montant
    # total de l'opération liée si le remboursement est partiel).
    montant_lien: float


class OperationRembourseeInput(BaseModel):
    operation_id: int
    montant: float = Field(gt=0)


class DecoupeInput(BaseModel):
    """Une part d'une opération découpée, telle que l'écran l'envoie.

    Le montant est STRICTEMENT positif : une part à zéro ne classerait rien et
    occuperait une ligne du formulaire pour ne rien dire. Retirer la part est la
    façon de dire « rien pour cette catégorie »."""

    categorie_id: int
    montant: float = Field(gt=0)


class DecoupeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    categorie_id: int
    montant: float
    ordre: int


class OperationBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date_type
    compte_id: int
    type_id: int
    # Renseignée uniquement pour les types à catégorie libre (opération
    # classique, dépense remboursable) ; NULL pour les quatre autres, dont le
    # type porte à lui seul la classification.
    categorie_id: Optional[int] = None
    # DÉCOUPE : la liste des parts, quand une seule catégorie ne suffit pas.
    # Vide = opération ordinaire, classée par `categorie_id`. Non vide, elle
    # REMPLACE la catégorie (que crud met alors à NULL) : les deux répondent à
    # la même question, et en garder deux réponses aurait posé à chaque calcul
    # celle de savoir laquelle compte.
    #
    # La somme des parts doit valoir le montant, et le type doit être
    # `classique` : les deux se vérifient côté routeur, qui seul peut résoudre
    # `type_id` en base — comme pour `montant_du` et sa borne.
    decoupes: list[DecoupeInput] = Field(default_factory=list)
    nature: str
    montant: float = Field(ge=0)
    # Notes libres de l'utilisateur, sans aucune sémantique pour l'app :
    # affichées uniquement à l'édition. None et "" y valent la même chose.
    notes: Optional[str] = None
    # Monnaie du montant, obligatoirement l'une de celles du compte (vérifié
    # côté routeur). Un compte mono-monnaie n'oblige pas le frontend à la
    # demander : il envoie simplement la seule possible.
    monnaie_id: int
    statut: Statut
    # LES FRAIS COMPRIS DANS `montant` (migration 0051). Purement descriptif :
    # `montant` reste ce qui a bougé sur le compte, aucun solde ni agrégat ne
    # lit ce champ. Il dit de QUOI le montant est fait, pour que l'écran puisse
    # le redécomposer — et le laisser corriger.
    frais: Optional[float] = Field(default=None, ge=0)
    # La devise des frais, quand elle diffère de celle de l'opération. NULL =
    # celle de l'opération, le cas ordinaire.
    monnaie_frais_id: Optional[int] = None
    # None = non précisé : calculé côté serveur (montant si remboursable, sinon 0).
    # Montant fixe initialement dû ; ne change pas quand le remboursement a lieu.
    montant_du: Optional[float] = Field(default=None, ge=0)
    # Reste à rembourser ; diminue (jusqu'à 0) au fil des remboursements liés.
    montant_a_rembourser: Optional[float] = Field(default=None, ge=0)
    # Récurrence (voir crud.generer_occurrences_recurrentes) : recurrente=True
    # sans frequence n'a pas de sens (rejeté ci-dessous). recurrence_fin=None =
    # récurrence infinie (bornée à un horizon glissant à la génération).
    recurrente: bool = False
    frequence: Optional[Frequence] = None
    recurrence_fin: Optional[date_type] = None
    # Amortissement (voir models.Operation.amorti et services/soldes.py) :
    # l'opération a lieu une fois, à `date`, mais pèse sur les mois
    # [amortissement_debut, amortissement_fin], bornes incluses. Les deux dates
    # sont ramenées au 1er du mois ci-dessous : seul le mois porte du sens, et
    # laisser passer deux jours différents ferait dépendre le nombre de mois de
    # quelque chose qui ne compte pas.
    amorti: bool = False
    amortissement_debut: Optional[date_type] = None
    amortissement_fin: Optional[date_type] = None

    @model_validator(mode="after")
    def _check_amortissement(self):
        if not self.amorti:
            # Des bornes sans la case cochée ne seraient jamais lues : les
            # effacer garde une seule représentation de « non amortie ».
            self.amortissement_debut = None
            self.amortissement_fin = None
            return self
        if self.amortissement_debut is None or self.amortissement_fin is None:
            raise ValueError(
                "amortissement_debut et amortissement_fin sont requis pour une "
                "opération amortie"
            )
        self.amortissement_debut = self.amortissement_debut.replace(day=1)
        self.amortissement_fin = self.amortissement_fin.replace(day=1)
        if self.amortissement_fin < self.amortissement_debut:
            raise ValueError(
                "amortissement_fin ne peut pas précéder amortissement_debut"
            )
        # Un modèle récurrent réengendre la même dépense mois après mois ;
        # l'amortir reviendrait à recopier les mêmes mois de destination sur
        # chaque occurrence, donc à empiler N amortissements identiques sur la
        # même poignée de mois. Les deux cases s'excluent aussi côté formulaire.
        if self.recurrente:
            raise ValueError(
                "une opération ne peut pas être à la fois récurrente et amortie"
            )
        return self

    @model_validator(mode="after")
    def _check_montants_remboursement(self):
        # UNE SEULE DES DEUX RÈGLES DE MONTANT TIENT ICI, et c'est voulu.
        #
        # « Le reste à rembourser ne dépasse pas ce qui est dû » vaut pour tout
        # le monde : elle reste. La borne de `montant_du` par rapport à
        # `montant`, elle, DÉPEND DU TYPE — plafond pour une dépense
        # remboursable, plancher pour un prêt reçu (cf. crud.erreur_montant_du) —
        # et ce modèle ne connaît que `type_id`, un entier qu'il faudrait
        # résoudre en base pour savoir de quel côté trancher. La garder ici
        # revenait à appliquer la règle des dépenses aux prêts, qui ne pouvaient
        # donc porter aucun intérêt.
        if (
            self.montant_du is not None
            and self.montant_a_rembourser is not None
            and self.montant_a_rembourser > self.montant_du
        ):
            raise ValueError("montant_a_rembourser ne peut pas dépasser montant_du")
        return self


class OperationCreate(OperationBase):
    # Uniquement valide quand la catégorie choisie est "Remboursements" (vérifié
    # côté routeur, qui a besoin d'une résolution en base) : dépenses remboursables
    # que cette opération règle, avec le montant réglé pour chacune (remboursement
    # partiel autorisé, jusqu'au montant_du de la dépense concernée).
    operations_remboursees: list[OperationRembourseeInput] = Field(default_factory=list)

    # Sur OperationCreate seulement (pas OperationBase) : une occurrence
    # générée par une récurrence a recurrente=True mais frequence=None (seul
    # le modèle porte la fréquence, cf. crud.generer_occurrences_recurrentes)
    # -- OperationRead, qui hérite aussi de OperationBase pour lire ces lignes
    # existantes, ne doit donc pas appliquer cette contrainte.
    @model_validator(mode="after")
    def _check_recurrence(self):
        if self.recurrente and self.frequence is None:
            raise ValueError("frequence est requise pour une opération récurrente")
        return self


class OperationUpdate(BaseModel):
    date: Optional[date_type] = None
    compte_id: Optional[int] = None
    type_id: Optional[int] = None
    categorie_id: Optional[int] = None
    # None = ne touche pas aux parts existantes ; [] les efface toutes (et rend
    # l'opération à sa catégorie unique). Même convention que
    # `operations_remboursees` juste en dessous.
    decoupes: Optional[list[DecoupeInput]] = None
    nature: Optional[str] = None
    montant: Optional[float] = Field(default=None, ge=0)
    # Envoyer "" efface la note ; ne pas envoyer la clé la laisse intacte
    # (update_operation lit exclude_unset).
    notes: Optional[str] = None
    monnaie_id: Optional[int] = None
    statut: Optional[Statut] = None
    # Les frais compris dans `montant` (cf. OperationBase.frais). Envoyer null
    # les efface ; ne pas envoyer la clé les laisse intacts (update_operation lit
    # exclude_unset), comme pour les notes.
    frais: Optional[float] = Field(default=None, ge=0)
    monnaie_frais_id: Optional[int] = None
    montant_du: Optional[float] = Field(default=None, ge=0)
    montant_a_rembourser: Optional[float] = Field(default=None, ge=0)
    recurrente: Optional[bool] = None
    frequence: Optional[Frequence] = None
    recurrence_fin: Optional[date_type] = None
    # La cohérence des trois champs d'amortissement se vérifie sur l'ÉTAT FINAL
    # de l'opération, pas sur le payload : une modification partielle est
    # légitime (déplacer la seule borne de fin, par exemple). D'où la validation
    # côté routeur (_valider_amortissement) plutôt qu'ici.
    amorti: Optional[bool] = None
    amortissement_debut: Optional[date_type] = None
    amortissement_fin: Optional[date_type] = None
    operations_remboursees: Optional[list[OperationRembourseeInput]] = None


class OperationRead(OperationBase):
    # Redéclaré en lecture : les parts remontent avec leur id et leur rang,
    # que l'écran réutilise pour les réafficher dans l'ordre saisi.
    decoupes: list[DecoupeRead] = Field(default_factory=list)
    id: int
    # Dupliqué depuis la relation : évite au frontend de recharger la table des
    # types pour savoir dans quel onglet ranger la ligne.
    type_code: str
    remboursable: bool
    sens: Sens
    montant_du: float
    montant_a_rembourser: float
    virement_id: Optional[str] = None
    # Id du modèle récurrent dont cette opération a été générée (None pour un
    # modèle lui-même ou une opération jamais récurrente) : lecture seule,
    # sert au frontend à distinguer modèle / occurrence générée.
    recurrence_parent_id: Optional[int] = None
    # Déduits des deux bornes par models.Operation (jamais stockés) : le
    # formulaire affiche le nombre de mois et le montant mensuel sans avoir à
    # refaire le calcul, et sans risque de le faire autrement que le serveur.
    # None sur une opération non amortie.
    amortissement_nb_mois: Optional[int] = None
    amortissement_montant_par_mois: Optional[float] = None
    operations_remboursees: list[OperationLieeRead] = Field(default_factory=list)
    rembourse_par: list[OperationLieeRead] = Field(default_factory=list)


class VirementCreate(BaseModel):
    """Un virement porte systématiquement deux monnaies et deux montants : ce
    qui part du compte source et ce qui arrive sur le compte destination.

    C'est ce qui permet de virer 100 € et d'en recevoir 108 $ sans que l'app
    connaisse le moindre taux de change — le montant reçu est celui qu'a
    réellement constaté la banque. Quand les deux monnaies sont identiques (le
    cas courant), `monnaie_destination_id` et `montant_destination` peuvent être
    omis : ils reprennent alors ceux du départ, et le frontend n'affiche même
    pas le second champ.
    """

    date: date_type
    compte_source_id: int
    compte_destination_id: int
    montant: float = Field(gt=0)
    monnaie_id: int
    montant_destination: Optional[float] = Field(default=None, gt=0)
    monnaie_destination_id: Optional[int] = None
    nature: Optional[str] = None
    statut: Statut = Statut.reel
    # LES FRAIS DU VIREMENT, déjà compris dans les deux montants ci-dessus —
    # ajoutés à ce qui part, ou retranchés de ce qui arrive, selon la jambe que
    # leur devise désigne (cf. services/import_bancaire._appliquer_frais). Ils
    # sont posés sur CETTE jambe-là et sur elle seule : les porter des deux
    # côtés les ferait lire deux fois.
    frais: Optional[float] = Field(default=None, ge=0)
    monnaie_frais_id: Optional[int] = None
    # Notes libres : la même sur les deux écritures, comme la date et le statut.
    # Un virement se saisit et se modifie d'un bloc, une note propre à une seule
    # de ses jambes n'aurait aucun endroit où se saisir.
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _check_deux_ecritures_distinctes(self):
        """Un virement doit déplacer l'argent quelque part : soit vers un autre
        compte, soit — sur un même compte multi-devises — vers une autre
        monnaie.

        Ce second cas est une conversion de change interne (typiquement un
        compte Wise où l'on convertit 100 € en 108 $ sans quitter le compte) :
        les deux écritures sont bien distinctes puisqu'elles portent chacune sa
        monnaie et son montant, et les soldes par monnaie du compte (jamais
        additionnés, cf. models.CompteMonnaie) bougent réellement tous les
        deux. Seul reste interdit le virement strictement immobile : même
        compte ET même monnaie, qui ne serait qu'une paire d'écritures
        s'annulant l'une l'autre.
        """
        if (
            self.compte_source_id == self.compte_destination_id
            and self.monnaie_destination_resolue == self.monnaie_id
        ):
            raise ValueError(
                "Le compte source et le compte destination doivent être différents, "
                "sauf pour une conversion entre deux monnaies d'un même compte "
                "(la monnaie reçue doit alors différer de la monnaie envoyée)"
            )
        return self

    @property
    def monnaie_destination_resolue(self) -> int:
        return (
            self.monnaie_destination_id
            if self.monnaie_destination_id is not None
            else self.monnaie_id
        )

    @property
    def montant_destination_resolu(self) -> float:
        return (
            self.montant_destination if self.montant_destination is not None else self.montant
        )


class VirementRead(BaseModel):
    virement_id: str
    operation_sortante: OperationRead
    operation_entrante: OperationRead


class SoldeMonnaieRead(BaseModel):
    """Le solde d'un compte DANS une monnaie. Un compte à deux monnaies en a
    deux, jamais additionnés."""

    monnaie_id: int
    monnaie_nom: str
    monnaie_symbole: str
    solde_initial: float
    solde_reel: float
    solde_projete: float


class CompteSoldeRead(BaseModel):
    id: int
    nom: str
    type_nom: str
    soldes: list[SoldeMonnaieRead]


class DepenseTopRead(BaseModel):
    """Une des plus grosses dépenses d'une catégorie sur la période, telle
    qu'elle s'affiche au survol de sa barre dans l'histogramme.

    FONDUE PAR LIBELLÉ : trois passages « Courses Monoprix » à 25 € ne sont pas
    trois lignes de 25 € mais une de 75 €, et `nombre` vaut alors 3. C'est ce
    qui fait remonter une dépense récurrente au-dessus d'un achat isolé plus
    gros — sans quoi le classement dirait ce qu'on a payé le plus cher en une
    fois, pas ce qui pèse le plus dans le mois.
    """

    nature: str
    montant: float
    # 1 quand rien n'a été fondu. Le frontend ne montre le compte que
    # au-delà : « (1) » n'apprendrait rien et alourdirait chaque ligne.
    nombre: int = 1


class DepenseParCategorie(BaseModel):
    categorie: str
    total_reel: float
    total_previsionnel: float
    budget_alloue: float
    # Les plus grosses dépenses de la catégorie sur la période (cf.
    # services.soldes.NB_TOP_DEPENSES), de la plus lourde à la plus légère.
    # Peut être vide : toutes les catégories visibles sont listées, y compris
    # celles où rien n'a été dépensé.
    top_depenses: list[DepenseTopRead] = Field(default_factory=list)
    # Index dans la palette de l'histogramme, porté par la catégorie elle-même
    # (cf. models.Categorie.couleur_index). Envoyé ici plutôt que déduit de la
    # position dans cette liste : la liste est filtrée (catégories éteintes) et
    # réordonnable, la couleur ne doit dépendre ni de l'une ni de l'autre.
    couleur_index: int = 0


class KpisMonnaieRead(BaseModel):
    """Tout ce que le dashboard agrège, pour UNE monnaie : additionner des
    euros et des dollars demanderait un taux de change que l'app n'a pas et ne
    veut pas inventer. Le frontend en fait un onglet par monnaie."""

    monnaie_id: int
    monnaie_nom: str
    monnaie_symbole: str
    # Les 2 premiers champs excluent l'épargne et les comptes de placement
    # (soumis uniquement à des virements internes et, pour les placements, à des
    # achats/ventes de titres — hors logique de "budget courant"). total_avoirs
    # est la seule valeur qui les inclut, portefeuilles valorisés compris, pour
    # voir le patrimoine complet.
    solde_total_courant: float
    solde_projete_courant: float
    total_avoirs: float
    # Part de total_avoirs apportée par les titres détenus (au dernier cours
    # saisi) : affichée à part pour que le total reste lisible.
    valorisation_placements: float = 0.0
    # Les trois flux de la PÉRIODE demandée (mois ou année), virements internes
    # exclus — cf. services/soldes.get_flux_periode. Ils viennent du même calcul
    # et vérifient donc toujours variation = entrées − sorties : les afficher
    # côte à côte sans cette garantie exposerait trois chiffres qui ne
    # s'accordent pas.
    total_entrees: float = 0.0
    total_sorties: float = 0.0
    variation_previsionnelle: float = 0.0
    # CE QUI EST PASSÉ SUR LES COMPTES pendant la période, sans rien étaler ni
    # retrancher : une dépense amortie en entier au mois où l'argent est sorti,
    # une dépense remboursable sans déduire ce qu'on nous rendra, les règlements
    # compris (cf. services/soldes.get_variation_brute). C'est ce que la carte
    # « Variation du mois » affiche — la question qu'on se pose devant un relevé,
    # et non « qu'est-ce que ce mois me coûte », à laquelle répondent les trois
    # champs juste au-dessus.
    variation_brute: float = 0.0
    depenses_par_categorie: list[DepenseParCategorie] = Field(default_factory=list)


class SemaineDepensesRead(BaseModel):
    """Une semaine du mois, et l'histogramme qu'elle porte.

    `jour_debut` / `jour_fin` sont des JOURS DU MOIS (1 à 31), pas des dates :
    l'écran les affiche tels quels (« 8 → 14 ») et n'a besoin de rien d'autre —
    l'année et le mois sont ceux de la requête."""

    numero: int
    jour_debut: int
    jour_fin: int
    depenses: list[DepenseParCategorie] = Field(default_factory=list)


class DepensesSemainesRead(BaseModel):
    """L'histogramme du mois déplié en semaines, et leur moyenne.

    LES DEUX ENSEMBLE, en une seule réponse : la bascule « une semaine /
    Moyenne » de l'écran ne doit pas coûter un aller-retour, et la moyenne DOIT
    être celle des semaines rendues ici — la recalculer à part ouvrirait
    l'écart entre la barre moyenne et les barres qu'elle résume."""

    annee: int
    mois: int
    semaines: list[SemaineDepensesRead] = Field(default_factory=list)
    moyenne: list[DepenseParCategorie] = Field(default_factory=list)


class DashboardRead(BaseModel):
    comptes: list[CompteSoldeRead]
    # Les monnaies effectivement portées par au moins un compte, dans l'ordre
    # d'affichage — la liste des onglets.
    monnaies: list[MonnaieRead]
    kpis: list[KpisMonnaieRead]


# ---------- Placements financiers ----------


class TypeTitreCreate(BaseModel):
    """Un libellé, et c'est tout : « ETF », « Obligation », « SCPI ». Aucun
    calcul de l'application ne le lit, il ne sert qu'à regrouper des titres pour
    les regarder."""

    nom: str = Field(min_length=1)


class TypeTitreUpdate(BaseModel):
    nom: Optional[str] = Field(default=None, min_length=1)
    ordre: Optional[int] = None


class TypeTitreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nom: str
    ordre: int = 0
    # Combien de titres le portent, archivés compris. Sert à l'écran de gestion :
    # supprimer un type qui typait douze titres ne se fait pas à l'aveugle.
    nb_titres: int = 0


class ActionCreate(BaseModel):
    nom: str = Field(min_length=1)
    # Dernier cours unitaire connu, saisi à la main : sert à valoriser le
    # portefeuille, jamais à calculer un solde en espèces.
    valeur: float = Field(default=0.0, ge=0)
    # Monnaie de cotation : cours, prix payés et valorisation en découlent, et
    # le titre ne peut s'acheter que depuis un compte qui la porte.
    monnaie_id: int
    # Code ISIN, facultatif : la seule dénomination stable d'un titre, et donc
    # celle par laquelle l'import de placements le reconnaît d'un relevé à
    # l'autre. Une chaîne vide vaut « aucun » (cf. models.Action.code_isin).
    code_isin: Optional[str] = None
    # Le type du titre (« ETF », « Obligation »…), facultatif : une étiquette
    # pour regrouper, jamais une donnée de calcul (cf. models.TypeTitre).
    type_titre_id: Optional[int] = None


class ActionUpdate(BaseModel):
    nom: Optional[str] = Field(default=None, min_length=1)
    # Ce qu'on lit à l'écran, quand le nom du courtier est illisible. Une chaîne
    # VIDE rend son nom d'origine au titre — c'est le seul moyen de défaire un
    # renommage, `None` voulant dire « ne change pas » comme partout ici.
    nom_affichage: Optional[str] = None
    valeur: Optional[float] = Field(default=None, ge=0)
    monnaie_id: Optional[int] = None
    # Comme les autres champs ici, None = « ne change pas ».
    code_isin: Optional[str] = None
    # Ranger le titre, ou le remettre en service. `None` ne touche à rien : on
    # doit pouvoir corriger un cours sans se prononcer sur l'archivage.
    archivee: Optional[bool] = None
    # Le type du titre. `None` = « ne change pas », comme les autres champs ;
    # c'est **0** qui DÉTYPE le titre — il faut bien un moyen de défaire un choix,
    # et `None` est déjà pris.
    type_titre_id: Optional[int] = None


class ActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    # Le nom du COURTIER, non modifiable : c'est lui qui identifie le titre d'un
    # import à l'autre. L'écran affiche `nom_affiche`.
    nom: str
    nom_affichage: Optional[str] = None
    # Le renommage s'il existe, le nom du courtier sinon : les écrans lisent
    # celui-ci et n'ont pas à refaire le choix chacun de leur côté.
    nom_affiche: str
    valeur: float
    monnaie_id: int
    monnaie_symbole: str
    # Un titre archivé n'est rendu que sur demande explicite (cf. list_actions) :
    # le drapeau voyage quand même, pour que l'écran sache dire lequel il montre.
    archivee: bool = False
    code_isin: Optional[str] = None
    # Le type et son libellé : l'identifiant pour les formulaires, le nom pour
    # les tableaux — qui n'ont ainsi rien à aller rechercher ailleurs.
    type_titre_id: Optional[int] = None
    type_titre_nom: Optional[str] = None


class OperationActionCreate(BaseModel):
    action_id: int
    sens: SensAction
    quantite: float = Field(gt=0)
    # Prix réellement payé (achat) ou encaissé (vente) par titre : le montant
    # débité/crédité sur le compte en découle, indépendamment du cours affiché.
    prix_unitaire: float = Field(ge=0)
    date: date_type
    # Libellé de l'écriture d'espèces ; par défaut « Achat <titre> ».
    nature: Optional[str] = None


class OperationActionRead(BaseModel):
    id: int
    operation_id: int
    action_id: int
    action_nom: str
    sens: SensAction
    quantite: float
    prix_unitaire: float
    # quantite * prix_unitaire : le montant de l'écriture d'espèces.
    montant: float
    # Monnaie de cotation du titre, donc aussi celle de l'écriture d'espèces.
    monnaie_id: int
    monnaie_symbole: str
    date: date_type
    nature: str


class DetentionRead(BaseModel):
    """Ce qui est détenu d'un titre sur un compte donné, entièrement recalculé
    depuis les opérations (aucune quantité n'est stockée)."""

    action_id: int
    action_nom: str
    monnaie_id: int
    monnaie_symbole: str
    quantite: float
    # Prix de revient unitaire (coût moyen pondéré) et coût total du stock
    # restant : ce qui a réellement été déboursé pour les titres encore détenus.
    prix_revient_unitaire: float
    montant_investi: float
    # Dernier cours connu (Action.valeur) et valorisation qui en découle.
    valeur_unitaire: float
    valorisation: float
    plus_value_latente: float


class PlacementMonnaieRead(BaseModel):
    """Les deux soldes d'un compte-titres — espèces et portefeuille — pour UNE
    monnaie. Un compte qui porte des euros et des dollars en a deux jeux, jamais
    additionnés."""

    monnaie_id: int
    monnaie_nom: str
    monnaie_symbole: str
    solde_espece: float
    valorisation: float
    # Espèces + valorisation du portefeuille.
    total: float
    # Coût des titres encore détenus : la plus-value latente s'en déduit.
    montant_investi: float


class PlacementCompteRead(BaseModel):
    compte_id: int
    compte_nom: str
    par_monnaie: list[PlacementMonnaieRead] = Field(default_factory=list)
    detentions: list[DetentionRead] = Field(default_factory=list)


class PlacementDetailRead(PlacementCompteRead):
    operations: list[OperationActionRead] = Field(default_factory=list)


# ---------- Placements financiers : cours lus en ligne ----------
#
# Servent l'extension « lecture-de-cours », et elle seule — le noyau n'émet
# aucune requête réseau. Ils vivent ici comme le reste du schéma des
# placements : une extension ne devrait pas emporter ses données (cf.
# extensions/README.md), sans quoi la désactiver imposerait de choisir entre
# les perdre et refuser de s'éteindre.


class UrlCoursUpdate(BaseModel):
    """La page d'où relire le cours d'un titre, telle que collée par
    l'utilisateur. Sa validité n'est pas vérifiée ici mais en l'ESSAYANT (cf.
    l'extension) : une URL bien formée qui ne donne aucun cours est le vrai cas
    à attraper, et aucune expression régulière ne le voit."""

    url: str = Field(min_length=1)


class SourceCoursRead(BaseModel):
    """Une source de cotation reconnue, décrite pour l'écran."""

    id: str
    nom: str
    exemple: str
    couvre: str


class CoursTitreRead(BaseModel):
    """L'état de cotation d'un titre : son lien, son cours, sa fraîcheur.

    `cours_maj_le` à None se lit « jamais relu en ligne » — cours saisi à la
    main, ou lien ajouté mais encore jamais suivi d'une lecture réussie."""

    action_id: int
    action_nom: str
    url_cours: Optional[str] = None
    cours: float
    monnaie_symbole: str
    cours_maj_le: Optional[datetime] = None


class ResultatCoursRead(BaseModel):
    """Ce qu'un titre a donné lors d'un rafraîchissement.

    `ancien_cours` accompagne le nouveau pour que l'écran puisse montrer le
    mouvement : un cours qui n'a pas bougé et un cours qui vient de tomber de
    3 % s'affichent autrement, et c'est l'information qu'on regarde."""

    action_id: int
    action_nom: str
    ok: bool
    cours: Optional[float] = None
    ancien_cours: Optional[float] = None
    source: Optional[str] = None
    # Nom de l'instrument tel que la source le publie : la seule confirmation
    # que le lien collé pointe bien sur le bon titre.
    libelle_source: Optional[str] = None
    erreur: Optional[str] = None


class RafraichissementRead(BaseModel):
    """Le compte rendu d'un rafraîchissement, et l'état de TOUS les titres
    après coup — pour que l'écran se remette à jour sans second appel."""

    horodatage: Optional[datetime] = None
    reussis: int = 0
    echecs: int = 0
    resultats: list[ResultatCoursRead] = Field(default_factory=list)
    titres: list[CoursTitreRead] = Field(default_factory=list)


# ---------- Monnaies : taux lus en ligne ----------
#
# Même extension, même règle : les données restent dans le noyau, l'extension
# n'apporte que la lecture. Aucun de ces taux n'est utilisé pour convertir quoi
# que ce soit — cf. models.TauxChange.


class TauxChangeCreate(BaseModel):
    """Un couple à suivre, et la page d'où le lire.

    Les deux monnaies sont désignées par leur id : elles existent déjà dans
    l'application, on ne les crée pas ici. Leur ordre porte le sens du taux —
    « 1 source vaut n cible » — et l'inverse est un autre couple, avec sa
    propre page."""

    monnaie_source_id: int
    monnaie_cible_id: int
    url: str = Field(min_length=1)


class TauxChangeRead(BaseModel):
    """Un couple suivi, tel que l'écran l'affiche.

    Les noms et symboles accompagnent les ids pour que le frontend n'ait pas à
    recroiser la table des monnaies ligne par ligne.

    `maj_le` à None se lit « jamais relu » : le lien est enregistré, aucune
    lecture n'a encore abouti.

    `url_cours` à None se lit « saisi à la main » : ce taux n'a pas de page d'où
    le relire, et l'extension « Lecture de cours » l'ignore."""

    id: int
    monnaie_source_id: int
    monnaie_source_nom: str
    monnaie_source_symbole: str
    monnaie_cible_id: int
    monnaie_cible_nom: str
    monnaie_cible_symbole: str
    url_cours: Optional[str] = None
    taux: Optional[float] = None
    maj_le: Optional[datetime] = None


class ResultatTauxRead(BaseModel):
    """Ce qu'un couple a donné lors d'un rafraîchissement."""

    taux_id: int
    libelle: str  # « Euro -> Dollar américain », pour un message lisible
    ok: bool
    taux: Optional[float] = None
    ancien_taux: Optional[float] = None
    source: Optional[str] = None
    erreur: Optional[str] = None


class RafraichissementTauxRead(BaseModel):
    """Compte rendu d'un rafraîchissement, et état de TOUS les couples après
    coup — pour que l'écran se remette à jour sans second appel."""

    horodatage: Optional[datetime] = None
    reussis: int = 0
    echecs: int = 0
    resultats: list[ResultatTauxRead] = Field(default_factory=list)
    taux: list[TauxChangeRead] = Field(default_factory=list)


class ImportLigne(BaseModel):
    ligne: int  # numéro de ligne dans le fichier source, pour repérer une erreur
    date: Optional[date_type] = None
    nature: str = ""
    montant: Optional[float] = None  # toujours positif ; cf. montant_signe pour le sens d'origine
    # Valeur brute du fichier bancaire (négative = sortie, positive = entrée),
    # ou résultat de la formule de montant quand le preset en définit une :
    # sert uniquement à déterminer, côté frontend, quel compte de la ligne est
    # émetteur ou récepteur pour un virement interne détecté.
    montant_signe: Optional[float] = None
    nom_banque_categorie: str = ""
    nom_banque_compte: str = ""
    categorie_id: Optional[int] = None
    # DÉCOUPE posée par une règle, DÉJÀ RÉSOLUE EN MONTANTS pour cette ligne-là
    # (cf. services/regles_categorisation.resoudre_decoupes). Vide dans le cas
    # courant. Non vide, elle remplace `categorie_id`, qui vaut alors None :
    # l'aperçu montre les parts au lieu du menu de catégorie.
    #
    # Des montants et non des formules, parce que l'aperçu sert précisément à
    # VOIR ce qui sera écrit : afficher « min(montant; 50) » sur une ligne à
    # 32 € aurait laissé l'utilisateur faire le calcul lui-même.
    decoupes: list[DecoupeInput] = Field(default_factory=list)
    # Ce qui a empêché la découpe d'une règle d'aboutir sur cette ligne (formule
    # qui déborde le montant, montant illisible). Affiché en avertissement dans
    # l'aperçu : la ligne reste importable, simplement sans découpe.
    decoupe_erreur: Optional[str] = None
    compte_id: Optional[int] = None
    # Libellé de la colonne « Sens » du relevé (« Débit », « C »...), vide pour
    # un preset qui ne la lit pas. Son effet est déjà appliqué à
    # `montant_signe` : il n'est conservé que pour être affiché dans l'aperçu,
    # et pour savoir que le fichier a tranché lui-même le sens de la ligne (cf.
    # services/import_bancaire.confirmer).
    nom_banque_sens: str = ""
    # True quand le FICHIER a tranché lui-même le sens de la ligne : un libellé
    # dans la colonne « Sens », ou la colonne remplie d'un montant scindé en
    # débit/crédit. Les deux disent la même chose de deux façons, d'où ce
    # booléen plutôt qu'un test sur `nom_banque_sens`.
    #
    # Ce qu'il change : sur une opération classique, le sens du fichier impose
    # entrée/dépense là où la catégorie seule en décidait (cf.
    # services/import_bancaire.confirmer) ; dans l'aperçu, le montant s'affiche
    # précédé de son signe. Un montant simplement SIGNÉ ne suffit pas — il
    # oriente les virements, mais n'a jamais rien imposé aux opérations
    # classiques, et ce n'est pas le sujet de cette propriété.
    sens_explicite: bool = False
    # True quand la ligne a rempli SES DEUX colonnes de montant (débit et
    # crédit) : deux montants ont été lus, et rien ne dit lequel fait
    # l'opération. `montant` vaut alors None, comme pour un montant illisible,
    # mais ce n'est pas la même chose à dire — d'où ce drapeau, que
    # `_erreur_ligne` relit pour reconstruire le bon message avant l'import.
    montant_ambigu: bool = False

    # ---------- Configuration avancée (cf. constants.PROPRIETES_IMPORT_AVANCEES) ----------
    # Tous None/vides pour un preset ordinaire, qui ne lit aucune de ces colonnes.
    #
    # Monnaie du montant. None = le preset ne dit pas dans quelle monnaie la
    # ligne est libellée : elle retombe alors sur la monnaie principale du
    # compte, comme avant la configuration avancée.
    nom_banque_monnaie: str = ""
    monnaie_id: Optional[int] = None
    # Devise dans laquelle `montant` est exprimé. Vaut `monnaie_id` sauf quand
    # c'est le montant INITIAL qui fait l'opération — une sortie à un seul
    # compte, où l'argent quitte le compte dans SA monnaie de départ (cf.
    # services/import_bancaire._appliquer_frais). C'est elle qui décide de la
    # monnaie de l'écriture, et de celle affichée dans l'aperçu.
    monnaie_operation_id: Optional[int] = None
    # Ce qui PART, avant frais et avant conversion, lu dans la colonne « Montant
    # initial ». `montant` décrit alors ce qui arrive. Lui seul peut donner les
    # deux, l'app n'ayant aucun taux de change. Sur un virement interne, c'est
    # la jambe ÉMETTRICE (cf. services/import_bancaire._resoudre_comptes_virement).
    montant_envoye: Optional[float] = None
    # Vrai quand `montant_envoye` ne sort PAS d'une colonne du fichier : c'est
    # le montant unique du relevé, placé du côté « ce qui part » parce que la
    # ligne est un virement SORTANT (cf. services/import_bancaire.
    # _orienter_jambe_virement). `montant` vaut alors None — ce qui arrive sur
    # l'autre compte est inconnu, l'app ne convertit rien.
    #
    # La distinction compte en aval : un relevé qui décrit vraiment les deux
    # jambes donne aussi les deux devises, un montant déduit non
    # (cf. _monnaies_virement).
    montant_envoye_deduit: bool = False
    # Monnaie de départ : colonne « Monnaie envoyée » du relevé, ou retouche
    # manuelle de la ligne dans l'aperçu (ImportLigneOverride). None = déduction
    # habituelle depuis le compte émetteur (cf.
    # services/import_bancaire._monnaies_virement).
    nom_banque_monnaie_envoyee: str = ""
    monnaie_envoyee_id: Optional[int] = None
    # Frais prélevés par la banque, et leur devise. Ils ne créent aucune
    # écriture à eux seuls : ils s'ajoutent au montant envoyé quand ils sont
    # libellés dans SA monnaie, et se retranchent du montant quand ils sont
    # dans la sienne (cf. services/import_bancaire._appliquer_frais).
    frais: Optional[float] = None
    nom_banque_monnaie_frais: str = ""
    monnaie_frais_id: Optional[int] = None
    # Les deux montants AVANT imputation des frais, tels que le fichier les
    # écrit. `montant` et `montant_envoye` ci-dessus sont ceux qui ont
    # réellement bougé (frais compris) : ce sont eux qu'on affiche et qui font
    # les écritures. Ceux-ci sont la base de calcul, et servent à réimputer les
    # frais quand l'utilisateur les corrige dans l'aperçu — sans eux, changer
    # des frais déjà incorporés obligerait à les défalquer à l'aveugle (cf.
    # services/import_bancaire._reimputer_frais).
    montant_hors_frais: Optional[float] = None
    montant_envoye_hors_frais: Optional[float] = None
    # True quand les frais lus ne sont dans aucune des deux monnaies de la
    # ligne : ils ne peuvent alors être rattachés à aucun montant, et l'import
    # entier est bloqué tant que la lecture des frais n'est pas retirée ou la
    # monnaie corrigée (cf. services/import_bancaire.confirmer).
    frais_incoherents: bool = False
    # Où en est la ligne chez la banque (colonne « État ») : "execute",
    # "attente", "refuse", ou None pour un preset qui ne lit pas cette colonne
    # — tout est alors considéré comme exécuté, comme avant. Une ligne en
    # attente devient une opération prévisionnelle ; une ligne refusée n'est pas
    # importée du tout (cf. constants.StatutImport).
    nom_banque_statut: str = ""
    statut_import: Optional[str] = None
    # Second compte d'un virement interne, renseigné manuellement (le fichier
    # bancaire ne décrit qu'un seul côté de la transaction) : ignoré pour toute
    # autre catégorie. Tant qu'il vaut None, la ligne garde l'ancien
    # comportement (une seule écriture, cf. create_operation_importee) ; une
    # fois les deux comptes connus, confirmer() crée un vrai virement
    # double-écriture (crud.create_virement).
    compte_id_autre: Optional[int] = None
    # True si categorie_id vient d'une proposition automatique ("Autres", faute
    # de mapping mémorisé) plutôt que d'un mapping explicitement mémorisé :
    # n'empêche jamais la création de l'opération, sert uniquement à demander
    # une confirmation côté frontend.
    categorie_suggestion_auto: bool = False
    # Nom de la règle de catégorisation qui a classé cette ligne (None si
    # aucune n'a correspondu) : affiché dans l'aperçu pour rendre le
    # classement automatique traçable.
    regle_appliquee: Optional[str] = None
    # Type d'opération de la ligne (code technique). Par défaut "classique" ;
    # posé par une règle de catégorisation ou par un reclassement manuel dans
    # l'aperçu. C'est lui qui décide si la ligne est remboursable.
    type_code: str = TypeOperation.classique.value
    # Montant fixe dû, pertinent uniquement pour un type remboursable ; None = pas
    # encore précisé par l'utilisateur (create_operation_importee retombe sur
    # le montant total, comme pour une opération remboursable créée à la main).
    # Pas de champ statut : une ligne de relevé bancaire est par nature une
    # transaction déjà survenue, l'opération créée est toujours "réel".
    montant_du: Optional[float] = None
    # Note libre et amortissement saisis dans le formulaire d'édition de
    # l'aperçu : aucun relevé ne les porte, ils naissent du classement de la
    # ligne. Absents par défaut — une ligne non retouchée n'a ni note ni
    # étalement, exactement comme avant.
    notes: Optional[str] = None
    amorti: bool = False
    amortissement_debut: Optional[date_type] = None
    amortissement_fin: Optional[date_type] = None
    erreur: Optional[str] = None
    # Id de la LigneImportBrute déjà en base suspectée d'être la même
    # transaction (voir services.import_bancaire.detecter_doublon), None si
    # cette ligne n'est pas un doublon. Une ligne doublon reste une
    # ImportLigne normale à tous points de vue (même format, Modifier,
    # Supprimer) : par défaut exclue de la création d'opération, sauf si son
    # numéro figure dans ImportMappingOverrides.lignes_verifiees (l'utilisateur
    # a coché "Vérifiée", override explicite du faux positif).
    doublon_de: Optional[int] = None


class ApercuFichier(BaseModel):
    """Le fichier tel qu'il est, avant toute interprétation : sert à vérifier
    d'un coup d'œil que la configuration des colonnes tombe bien en face des
    bonnes données (une colonne décalée est sinon très difficile à repérer)."""

    # Toutes les lignes non vides du fichier ; chaque ligne est complétée à la
    # largeur maximale pour que le tableau reste rectangulaire. Rien n'est
    # tronqué ici : c'est le frontend qui borne la hauteur affichée, le reste
    # restant accessible en défilant.
    lignes: list[list[str]] = Field(default_factory=list)
    # Index de colonne (1-based, en string pour JSON) -> propriété de l'app.
    # Les colonnes absentes de ce dict ne sont pas importées.
    proprietes_par_colonne: dict[str, str] = Field(default_factory=dict)
    total_lignes: int = 0
    # True si la première ligne affichée est l'en-tête ignoré (ImportPreset).
    premiere_ligne_ignoree: bool = False


class ImportPreview(BaseModel):
    lignes: list[ImportLigne]
    categories_inconnues: list[str]
    comptes_inconnus: list[str]
    # Libellés de devise lus dans le fichier qu'aucune correspondance mémorisée
    # ni aucun nom/symbole de monnaie ne permet de rattacher (cf.
    # services/import_bancaire._resoudre_monnaie). Vide pour un preset sans
    # colonne de devise.
    monnaies_inconnues: list[str] = Field(default_factory=list)
    # L'inverse : libellé de devise du fichier -> nom de la monnaie de l'app à
    # laquelle il a été rattaché, sans rien demander. Affiché en lecture seule
    # sous les devises à confirmer — un rattachement automatique (le fichier
    # écrit « SGD », une monnaie s'appelle « SGD ») ne se voyait sinon nulle
    # part, et son absence de la liste « à confirmer » passait pour un oubli.
    monnaies_resolues: dict[str, str] = Field(default_factory=dict)
    # Version résolue (même format que ImportLigne) de chaque ligne déjà en
    # base référencée par un doublon_de ci-dessus, clé = str(id) — affichée en
    # lecture seule à côté de la ligne importée pour comparaison (voir
    # services.import_bancaire._resoudre_ligne_existante).
    lignes_existantes: dict[str, ImportLigne] = Field(default_factory=dict)
    apercu_fichier: ApercuFichier = Field(default_factory=ApercuFichier)
    # Ce que la configuration du preset laisse d'ambigu sans être faux : un
    # montant reçu ou des frais lus sans leur devise (cf. services/
    # import_bancaire.avertissements_configuration). Affichés au-dessus de
    # l'aperçu ; ils ne bloquent jamais l'import, contrairement aux erreurs de
    # ligne.
    avertissements: list[str] = Field(default_factory=list)


class ImportLigneOverride(BaseModel):
    """Modification manuelle d'une ligne de l'aperçu avant confirmation
    (édition directe sur la ligne, cf. bouton "Modifier"). Seuls les champs
    fournis sont appliqués ; les autres gardent la valeur résolue automatiquement."""

    date: Optional[date_type] = None
    nature: Optional[str] = None
    montant: Optional[float] = None
    categorie_id: Optional[int] = None
    compte_id: Optional[int] = None
    compte_id_autre: Optional[int] = None
    type_code: Optional[str] = None
    montant_du: Optional[float] = None
    # Monnaies et montant envoyé corrigés à la main : indispensables pour un
    # virement entre deux devises, que l'app ne peut jamais recalculer seule.
    monnaie_id: Optional[int] = None
    montant_envoye: Optional[float] = None
    monnaie_envoyee_id: Optional[int] = None
    # Frais corrigés à la main. Leur présence change la lecture des deux
    # montants ci-dessus : ils valent alors HORS FRAIS, et le serveur réimpute
    # (cf. services/import_bancaire._reimputer_frais). Le formulaire ne les
    # envoie que là où il les affiche — un virement entre deux devises qui
    # porte des frais — donc partout ailleurs les montants restent ceux qui ont
    # réellement bougé, exactement comme avant.
    frais: Optional[float] = None
    monnaie_frais_id: Optional[int] = None
    # Note libre et étalement, saisis au moment où l'on classe la ligne (cf.
    # ImportLigne). `amorti` est un booléen plein et non un Optional : le
    # formulaire dit toujours dans quel état est sa case, et un None
    # signifierait « ne touche pas » là où l'utilisateur vient justement de
    # décocher. Les deux bornes, elles, ne valent que si la case est cochée.
    notes: Optional[str] = None
    amorti: bool = False
    amortissement_debut: Optional[date_type] = None
    amortissement_fin: Optional[date_type] = None


class ImportMappingOverrides(BaseModel):
    # Catégorie choisie pour chaque libellé bancaire dans l'aperçu. Un simple
    # id depuis 0022 : le type ne se choisit plus ici, il est posé par les
    # règles (évaluées avant les correspondances).
    categories: dict[str, int] = Field(default_factory=dict)
    comptes: dict[str, int] = Field(default_factory=dict)
    # Monnaie choisie pour chaque libellé de devise du fichier (« EUR » -> Euro).
    monnaies: dict[str, int] = Field(default_factory=dict)
    # Modifications ponctuelles par numéro de ligne (ImportLigne.ligne).
    lignes: dict[int, ImportLigneOverride] = Field(default_factory=dict)
    # Numéros de ligne exclues de l'import (bouton "Supprimer" de l'aperçu, ou
    # suppression groupée sur une sélection).
    lignes_supprimees: list[int] = Field(default_factory=list)


class VirementCandidatDoublon(BaseModel):
    """Un virement interne tel que l'aperçu d'import le connaît À CET INSTANT.

    UN SEUL DES DEUX COMPTES SUFFIT, et c'est le cas ordinaire : un relevé ne
    nomme que le sien. Le compte d'en face n'est renseigné que quand une règle
    l'a déduit ou que l'utilisateur l'a saisi ; d'ici là il vaut None, et la
    comparaison se fait sur le compte connu (cf. _memes_virements). Exiger les
    deux revenait à réclamer ce travail de mémoire précisément dans le cas où
    il ne sert à rien — celui d'une ligne qu'on va supprimer.

    Distinct de la détection de doublons ordinaire (cf. detecter_doublon), qui
    compare des LIGNES DE FICHIER à l'intérieur d'un même preset : deux relevés
    de deux banques décrivent le même virement avec des colonnes qui n'ont rien
    de commun, et seule la transaction elle-même — un compte au moins, un
    montant, une date voisine — les rapproche."""

    ligne: int
    date: date_type
    # Ce qui PART du compte émetteur, et sa devise.
    montant: float
    monnaie_id: Optional[int] = None
    # Ce qui ARRIVE sur le récepteur : renseigné uniquement quand il diffère de
    # ce qui part (transfert entre deux devises). Les deux montants doivent
    # alors correspondre pour conclure au doublon.
    montant_recu: Optional[float] = None
    monnaie_recue_id: Optional[int] = None
    # Celui que le relevé nomme est connu ; l'autre attend souvent encore.
    compte_source_id: Optional[int] = None
    compte_destination_id: Optional[int] = None


class VirementDoublonSuspect(BaseModel):
    """Ce à quoi un candidat ressemble : une opération déjà en base
    (source="base") ou une autre ligne du fichier en cours (source="fichier")."""

    source: str
    operation_id: Optional[int] = None
    ligne: Optional[int] = None
    date: date_type
    nature: str
    montant: float
    monnaie_symbole: str = ""
    compte_source: str
    compte_destination: str
    # Le compte que la ligne importée ne nommait PAS, lu sur ce suspect. None
    # quand elle nommait déjà les deux — il n'y a alors rien à apprendre.
    compte_en_face: Optional[str] = None
    ecart_jours: int


class VirementDoublonRead(BaseModel):
    ligne: int
    suspects: list[VirementDoublonSuspect] = Field(default_factory=list)


class VirementsDoublonsInput(BaseModel):
    candidats: list[VirementCandidatDoublon] = Field(default_factory=list)


class VirementsDoublonsRead(BaseModel):
    resultats: list[VirementDoublonRead] = Field(default_factory=list)


class ImportResultat(BaseModel):
    operations_creees: int
    lignes_ignorees: list[ImportLigne]
    doublons_detectes: int = 0
    # Trace créée pour cet import (ImportHistorique.id). Le frontend s'en sert
    # pour rattacher au même import les règlements liés, qu'il crée un par un
    # après coup (cf. services/import_bancaire.enregistrer_ligne_brute) : sans
    # ce rattachement, eux seuls survivraient à l'annulation de leur import.
    historique_id: Optional[int] = None


class ImportAnnulationResultat(BaseModel):
    """Ce qu'a défait l'annulation d'un import.

    `operations_supprimees` peut être inférieur au `operations_creees` de
    l'historique : les opérations déjà supprimées à la main entre-temps ne s'y
    retrouvent plus (cf. services/import_bancaire.annuler_import)."""

    operations_supprimees: int
    historique_supprime: bool


class MappingCategorieRead(BaseModel):
    """La cible est toujours une catégorie de dépense. Un libellé qui désigne en
    réalité un TYPE (« Mouvements internes » -> Virement interne) relève d'une
    règle de catégorisation, pas d'une correspondance : ces types ne portent
    aucune catégorie (cf. migration 0022)."""

    nom_banque: str
    categorie_id: int
    categorie_nom: str


class MappingCategorieGlobalRead(MappingCategorieRead):
    """La même correspondance, vue hors de son preset : la galerie de la page
    Règles les affiche tous ensemble, il lui faut donc de quoi dire d'où chaque
    libellé sort — et de quoi viser le bon preset en le reclassant ou en le
    supprimant.

    Une carte par correspondance, sans regroupement : deux presets peuvent
    ranger le même libellé dans deux catégories différentes, et c'est justement
    ce que la galerie doit montrer."""

    preset_id: int
    # Compte auquel le preset est lié. None quand le fichier nomme lui-même le
    # compte de chaque ligne : rien n'est alors affiché, il n'y a pas UN compte
    # à nommer.
    compte_nom: Optional[str] = None


class MappingCompteRead(BaseModel):
    nom_banque: str
    compte_id: int
    compte_nom: str


class MappingCompteGlobalRead(MappingCompteRead):
    """Une correspondance de compte telle que la page Règles l'affiche : sans
    dire de quel preset elle vient.

    Les entrées identiques (même libellé, même compte) de plusieurs presets sont
    fondues en UNE, d'où la liste de presets plutôt qu'un id — la modifier ou la
    supprimer les vise tous. Sans ça, la liste commune répéterait la même ligne
    autant de fois qu'il y a de presets."""

    preset_ids: list[int]


class MappingMonnaieRead(BaseModel):
    nom_banque: str
    monnaie_id: int
    monnaie_nom: str


class MappingMonnaieGlobalRead(MappingMonnaieRead):
    """Idem pour les devises, où la répétition est la règle : « EUR » -> Euro
    existe dans chaque preset qui lit une colonne de devise."""

    preset_ids: list[int]


class MappingCategorieUpsert(BaseModel):
    nom_banque: str = Field(min_length=1)
    categorie_id: int


class MappingCompteUpsert(BaseModel):
    nom_banque: str = Field(min_length=1)
    compte_id: int


class MappingMonnaieUpsert(BaseModel):
    nom_banque: str = Field(min_length=1)
    monnaie_id: int


class ImportMappingsRead(BaseModel):
    """Tout ce qu'affiche « Correspondances mémorisées » (page Règles), tous
    presets confondus : cette page n'a pas de sélecteur de preset, et n'en
    montrer qu'un revenait à cacher le reste sans dire lequel."""

    categories: list[MappingCategorieGlobalRead]
    comptes: list[MappingCompteGlobalRead]
    monnaies: list[MappingMonnaieGlobalRead] = Field(default_factory=list)


class ColonneImportConfig(BaseModel):
    index: int = Field(ge=1)
    propriete: str


class ImportPresetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nom: str
    # Ce que ce preset sait lire (cf. constants.DomaineImport). Jamais modifié
    # après création : c'est lui qui dit quelles propriétés `colonnes` désigne.
    domaine: DomaineImport = DomaineImport.bancaire
    # Compte auquel ce format de relevé appartient. Renseigné, toutes les lignes
    # du fichier lui sont affectées, sans consulter ni la colonne « compte
    # bancaire » ni les correspondances mémorisées.
    compte_id: Optional[int] = None
    colonnes: list[ColonneImportConfig]
    # Index de colonnes (1-based, format brut) désignées pour la comparaison de
    # doublons ; `mode_comparaison` dit si ce sont celles à ignorer ou les
    # seules à comparer (cf. constants.ModeComparaison).
    colonnes_comparaison: list[int] = Field(default_factory=list)
    mode_comparaison: ModeComparaison = ModeComparaison.exclusion
    # True = la première ligne du fichier est un en-tête à sauter. False
    # (défaut) = c'est déjà une ligne de données.
    ignorer_premiere_ligne: bool = False
    # Vocabulaire de la colonne « Sens » propre à ce relevé. Listes vides =
    # celui du code (constants.LIBELLES_SENS_*), en français.
    libelles_sens_sortie: list[str] = Field(default_factory=list)
    libelles_sens_entree: list[str] = Field(default_factory=list)
    # Vocabulaire de la colonne « État ». Listes vides = celui du code
    # (constants.LIBELLES_STATUT_DEFAUT).
    libelles_statut_execute: list[str] = Field(default_factory=list)
    libelles_statut_attente: list[str] = Field(default_factory=list)
    libelles_statut_refuse: list[str] = Field(default_factory=list)
    # Vocabulaire de la colonne « Type d'opération » d'un relevé de placements
    # (domaine `placement` seulement). Listes vides = celui du code
    # (constants.LIBELLES_TYPE_PLACEMENT_DEFAUT).
    libelles_type_achat: list[str] = Field(default_factory=list)
    libelles_type_vente: list[str] = Field(default_factory=list)
    libelles_type_transfert: list[str] = Field(default_factory=list)
    # CE QUE LE FICHIER RACONTE, pour un preset de placements : une liste
    # d'opérations, ou une PHOTOGRAPHIE du compte à un instant donné. None vaut
    # « operations » — ce que sont tous les presets antérieurs. Sans objet pour
    # un preset bancaire, comme les trois vocabulaires ci-dessus.
    mode_lecture: Optional[ModeLecturePlacement] = None
    # Date du dernier import confirmé sous ce preset (None si jamais utilisé) :
    # permet au frontend de présélectionner le preset réellement utilisé plutôt
    # que le premier par ordre alphabétique, qui peut être vide.
    dernier_import: Optional[datetime] = None


class ColonnesImportEssai(BaseModel):
    """Les colonnes d'un ESSAI de lecture (cf. POST /previsualiser).

    Une enveloppe autour de la liste, et non la liste nue : le champ arrive en
    JSON dans un formulaire multipart, et une racine d'objet se valide d'une
    ligne là où une racine de tableau demande un `TypeAdapter`."""

    colonnes: list[ColonneImportConfig]


class ImportPresetCreate(BaseModel):
    nom: str = Field(min_length=1)
    compte_id: Optional[int] = None
    colonnes: list[ColonneImportConfig]
    colonnes_comparaison: list[int] = Field(default_factory=list)
    mode_comparaison: ModeComparaison = ModeComparaison.exclusion
    ignorer_premiere_ligne: bool = False
    libelles_sens_sortie: list[str] = Field(default_factory=list)
    libelles_sens_entree: list[str] = Field(default_factory=list)
    # Vocabulaire de la colonne « État ». Listes vides = celui du code
    # (constants.LIBELLES_STATUT_DEFAUT).
    libelles_statut_execute: list[str] = Field(default_factory=list)
    libelles_statut_attente: list[str] = Field(default_factory=list)
    libelles_statut_refuse: list[str] = Field(default_factory=list)
    # Vocabulaire de la colonne « Type d'opération » d'un relevé de placements
    # (domaine `placement` seulement). Listes vides = celui du code
    # (constants.LIBELLES_TYPE_PLACEMENT_DEFAUT).
    libelles_type_achat: list[str] = Field(default_factory=list)
    libelles_type_vente: list[str] = Field(default_factory=list)
    libelles_type_transfert: list[str] = Field(default_factory=list)
    # CE QUE LE FICHIER RACONTE, pour un preset de placements : une liste
    # d'opérations, ou une PHOTOGRAPHIE du compte à un instant donné. None vaut
    # « operations » — ce que sont tous les presets antérieurs. Sans objet pour
    # un preset bancaire, comme les trois vocabulaires ci-dessus.
    mode_lecture: Optional[ModeLecturePlacement] = None


class ImportPresetUpdate(BaseModel):
    nom: str = Field(min_length=1)
    # None = preset non lié (le compte vient du fichier), comme à la création.
    compte_id: Optional[int] = None
    colonnes: list[ColonneImportConfig]
    colonnes_comparaison: list[int] = Field(default_factory=list)
    mode_comparaison: ModeComparaison = ModeComparaison.exclusion
    ignorer_premiere_ligne: bool = False
    libelles_sens_sortie: list[str] = Field(default_factory=list)
    libelles_sens_entree: list[str] = Field(default_factory=list)
    # Vocabulaire de la colonne « État ». Listes vides = celui du code
    # (constants.LIBELLES_STATUT_DEFAUT).
    libelles_statut_execute: list[str] = Field(default_factory=list)
    libelles_statut_attente: list[str] = Field(default_factory=list)
    libelles_statut_refuse: list[str] = Field(default_factory=list)
    # Vocabulaire de la colonne « Type d'opération » d'un relevé de placements
    # (domaine `placement` seulement). Listes vides = celui du code
    # (constants.LIBELLES_TYPE_PLACEMENT_DEFAUT).
    libelles_type_achat: list[str] = Field(default_factory=list)
    libelles_type_vente: list[str] = Field(default_factory=list)
    libelles_type_transfert: list[str] = Field(default_factory=list)
    # CE QUE LE FICHIER RACONTE, pour un preset de placements : une liste
    # d'opérations, ou une PHOTOGRAPHIE du compte à un instant donné. None vaut
    # « operations » — ce que sont tous les presets antérieurs. Sans objet pour
    # un preset bancaire, comme les trois vocabulaires ci-dessus.
    mode_lecture: Optional[ModeLecturePlacement] = None


class ImportHistoriqueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date_import: datetime
    nom_fichier: Optional[str] = None
    operations_creees: int
    lignes_ignorees: int
    doublons_detectes: int = 0
    # Combien de ces opérations existent ENCORE, donc ce qu'annuler cet import
    # supprimerait aujourd'hui. Calculé à la lecture, jamais stocké : les
    # opérations vivent leur vie après l'import (suppression à la main,
    # notamment) et une colonne aurait figé un compte faux. Zéro = il ne reste
    # rien à annuler, le frontend n'affiche alors pas le bouton.
    operations_annulables: int = 0
    # Pourquoi il n'y a rien à annuler, quand c'est le cas : "anterieur" (import
    # d'avant la migration 0016, dont les lignes n'ont jamais désigné leurs
    # opérations — il ne sera jamais annulable) ou "deja_supprime" (ses
    # opérations ont été retirées à la main depuis). Deux situations qui se
    # ressembleraient à l'écran, alors qu'une seule demande d'aller voir.
    # None quand l'import est annulable.
    raison_non_annulable: Optional[str] = None


class NoteDashboardRead(BaseModel):
    """Bloc-notes libre du dashboard. `modifie_le` est None tant que rien n'a
    jamais été écrit."""

    contenu: str = ""
    modifie_le: Optional[datetime] = None


class NoteDashboardUpdate(BaseModel):
    # Pas de longueur minimale : vider la note est une façon légitime de la
    # supprimer, et il n'y a rien d'autre à supprimer.
    contenu: str = ""


class BaseDonneesRead(BaseModel):
    chemin_actuel: str
    chemin_dev: str
    # True si l'app pointe actuellement vers la base de test/dev (plutôt
    # qu'une base personnelle sélectionnée à la main).
    est_dev: bool
    # Version de schéma du fichier actuellement ouvert, et celle qu'attend
    # l'application : les deux sont affichées, parce qu'un écart est
    # exactement ce qui rend une base illisible après une mise à jour.
    revision_base: Optional[str] = None
    revision_app: Optional[str] = None
    # Renseignés uniquement quand la bascule vient de migrer la base : la copie
    # prise juste avant, et la version quittée. C'est le seul moment où
    # l'utilisateur doit savoir où retrouver son fichier d'origine.
    migration_appliquee: bool = False
    sauvegarde: Optional[str] = None
    revision_quittee: Optional[str] = None

    # ---------- Emplacement : ce qui décide de l'écran de configuration ----------
    # La base ouverte vit-elle dans le dossier de l'application, que la
    # prochaine mise à jour remplacera (cf. database.chemin_a_risque) ?
    a_risque: bool = False
    # Faut-il exiger un choix AVANT de laisser entrer dans l'application ?
    # `a_risque` sans les échappatoires (BUDGET_DB_PATH, mode développement) :
    # le frontend n'a pas à connaître ces règles, il lit ce booléen.
    configuration_requise: bool = False
    # L'emplacement proposé par défaut dans l'écran de configuration, et le
    # dossier de l'application dont il faut sortir : affichés pour que le choix
    # se fasse en connaissance de cause, jamais appliqués sans geste.
    chemin_propose: str = ""
    dossier_application: str = ""
    # Le chemin retenu au dernier passage, quand le fichier a disparu depuis
    # (disque débranché, dossier renommé). L'application est alors repartie sur
    # sa base par défaut, et c'est la seule chose à dire d'urgence.
    base_memorisee_introuvable: Optional[str] = None
    # Le choix survivra-t-il à la fermeture ? False quand le fichier de
    # configuration n'a pas pu être écrit (profil en lecture seule) : la
    # bascule vaut alors pour la session seulement, et il faut le dire plutôt
    # que de laisser croire que c'est réglé.
    choix_memorise: bool = True
    # Renseigné par /parametres/base/installer seulement : « ouverte »,
    # « déplacée » ou « créée ». Le frontend ne peut pas le déduire — il ne sait
    # pas si le fichier existait avant sa requête.
    action: Optional[str] = None


class BaseDonneesUpdate(BaseModel):
    chemin: str = Field(min_length=1)


class BaseDonneesInstaller(BaseModel):
    """Mise en place de la base à un emplacement choisi : ouvrir un fichier
    existant, déplacer la base actuelle, ou en créer une neuve. Un seul geste
    côté écran, d'où une seule route — c'est le serveur qui voit lequel des
    trois cas s'applique (cf. database.installer_base)."""

    chemin: str = Field(min_length=1)
    # Déplacer la base actuellement ouverte vers `chemin` plutôt que d'en créer
    # une vide. Le cas normal du premier démarrage : la base par défaut vient
    # d'être créée et remplie de ses valeurs initiales, la perdre serait
    # absurde. Sans effet si un fichier existe déjà à destination.
    deplacer_actuelle: bool = False


# ---------- Règles de catégorisation ----------


def _valider_condition(condition, champs_valides: set[str]):
    """Le contrôle commun aux deux domaines de règles : un champ connu, un
    opérateur de la bonne famille, une valeur non vide. Seule la liste des
    champs change de l'un à l'autre."""
    if condition.champ not in champs_valides:
        raise ValueError(
            f"champ inconnu : {condition.champ} "
            f"(attendus : {', '.join(sorted(champs_valides))})"
        )
    # TEXTE ET NOMBRES NE SE COMPARENT PAS PAREIL, et l'opérateur doit aller
    # avec son champ : « la nature est supérieure à 50 » et « le montant
    # contient 12 » sont l'un et l'autre des règles qui ne correspondraient
    # jamais à rien. Refusé ici plutôt que silencieusement faux à l'import.
    admis = operateurs_admis(condition.champ)
    if condition.operateur not in admis:
        raise ValueError(
            f"l'opérateur « {condition.operateur.value} » ne s'applique pas au "
            f"champ « {condition.champ} » "
            f"(possibles : {', '.join(sorted(o.value for o in admis))})"
        )
    # Une valeur vide rendrait "contient" toujours vrai et "est" quasi
    # toujours faux : dans les deux cas la règle ne veut rien dire.
    if not condition.valeur.strip():
        raise ValueError("la valeur à comparer ne peut pas être vide")
    return condition


def _valider_valeurs(condition):
    """PLUSIEURS MOTS-CLÉS POUR UNE SEULE CONDITION, combinés en ET.

    CE QUE ÇA REMPLACE : une condition par mot-clé, dans un groupe « ET ».
    Écrire « le libellé contient CARREFOUR et contient MARKET » demandait deux
    lignes de formulaire là où on pense un seul test ; à cinq mots-clés, le
    groupe devenait illisible et l'ordre des conditions donnait l'illusion de
    compter.

    `valeurs` EST LA FORME CANONIQUE, `valeur` la forme d'avant : une règle
    écrite hier ne porte que `valeur`, et la relire doit donner la même chose
    qu'aujourd'hui. La normalisation se fait donc À LA LECTURE COMME À
    L'ÉCRITURE — les deux passent par ce validateur — et l'écran ne voit jamais
    qu'une liste.

    LES OPÉRATEURS NUMÉRIQUES N'EN PORTENT QU'UNE. « le montant est supérieur à
    30 et à 50 » se dit « supérieur à 50 » : la liste n'ajouterait rien qu'un
    piège. Ils gardent donc `valeur`, et `valeurs` reste vide.
    """
    numerique = condition.operateur in OPERATEURS_NOMBRE
    mots = [mot.strip() for mot in condition.valeurs if mot and mot.strip()]

    if numerique:
        if len(mots) > 1:
            raise ValueError(
                "un opérateur numérique ne compare qu'une seule valeur"
            )
        # La liste éventuelle (un seul mot) redevient la valeur simple.
        if mots and not condition.valeur.strip():
            condition.valeur = mots[0]
        condition.valeurs = []
        return condition

    if not mots:
        # Forme d'avant : la valeur unique devient une liste d'un mot.
        if not condition.valeur.strip():
            raise ValueError("la valeur à comparer ne peut pas être vide")
        mots = [condition.valeur.strip()]

    # Deux fois le même mot-clé ne dit rien de plus, et le second ne pourrait
    # jamais être ni vrai ni faux tout seul.
    vus = set()
    uniques = []
    for mot in mots:
        cle = mot.casefold()
        if cle in vus:
            continue
        vus.add(cle)
        uniques.append(mot)

    condition.valeurs = uniques
    # `valeur` garde le PREMIER mot plutôt que d'être vidée : c'est ce que lit
    # une version de l'application antérieure à ce champ, et une règle qui
    # cesserait de mordre après un retour en arrière serait pire qu'une règle
    # qui mord un peu trop large.
    condition.valeur = uniques[0]
    return condition


class ConditionRegle(BaseModel):
    """Un test sur un champ du relevé.

    Un seul champ par condition : pour en viser plusieurs, on ajoute autant de
    conditions dans un groupe "OU", ce qui rend la combinaison explicite au
    lieu de la cacher dans un OU implicite entre cases cochées.

    PLUSIEURS MOTS-CLÉS, EN REVANCHE, tiennent dans une seule condition
    (`valeurs`), combinés en ET : « contient CARREFOUR et contient MARKET »
    est un seul test, et l'écrire en deux conditions n'apportait qu'une ligne
    de formulaire de plus. Cf. `_valider_valeurs` pour la forme d'avant.
    """

    champ: str
    operateur: OperateurRegle
    # La forme d'AVANT, gardée : une règle enregistrée avant `valeurs` ne porte
    # que ce champ, et une version antérieure de l'app ne lit que lui. Après
    # validation, il vaut toujours le premier mot-clé de `valeurs`.
    valeur: str = ""
    # LES MOTS-CLÉS, combinés en ET. Vide pour un opérateur numérique, qui n'en
    # compare qu'un seul.
    valeurs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_champ(self):
        _valider_valeurs(self)
        return _valider_condition(self, CHAMPS_REGLE_VALIDES)


class GroupeRegle(BaseModel):
    operateur: ConnecteurRegle = ConnecteurRegle.et
    conditions: list[ConditionRegle] = Field(min_length=1)


class ConditionsRegle(BaseModel):
    """Deux niveaux : des groupes de conditions, eux-mêmes combinés — de quoi
    exprimer "(A OU B) ET (C OU D)"."""

    operateur: ConnecteurRegle = ConnecteurRegle.et
    groupes: list[GroupeRegle] = Field(min_length=1)


class RegleDecoupeInput(BaseModel):
    """Une part de la découpe qu'une règle impose : une catégorie et une
    FORMULE (cf. services/formule_decoupe.py).

    La formule est relue par le parseur DÈS L'ÉCRITURE : une règle qu'on
    enregistre aujourd'hui s'appliquera à un import dans six mois, et découvrir
    à ce moment-là qu'elle est illisible ferait échouer des lignes sans que rien
    ne rattache la panne à la règle fautive."""

    categorie_id: int
    formule: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_formule(self):
        # Import local : formule_decoupe vit sous services/, que schemas
        # n'importe nulle part ailleurs. Le remonter en tête ferait dépendre
        # tout le module des services pour une validation qui ne sert qu'ici.
        from .services.formule_decoupe import FormuleInvalide, valider_formule

        try:
            valider_formule(self.formule)
        except FormuleInvalide as erreur:
            raise ValueError(f"formule invalide : {erreur}") from erreur
        return self


class RegleCategorisationBase(BaseModel):
    nom: str = Field(min_length=1)
    # Note libre sur la règle (migration 0050) : POURQUOI elle existe, ce que
    # le nom et les conditions ne disent pas. Jamais lue par l'application —
    # rien ne la filtre, rien ne s'y déclenche, comme `SousFiltre.description`.
    description: str = ""
    conditions: ConditionsRegle
    # Action, en deux temps : le type d'opération d'abord, puis la catégorie
    # -- cette dernière n'ayant de sens que pour les types à catégorie libre.
    # La cohérence des deux est vérifiée côté routeur, qui seul peut résoudre
    # le code du type depuis son id.
    type_id: int
    categorie_id: Optional[int] = None
    # DÉCOUPE imposée par la règle. Vide = la règle pose une catégorie unique
    # (`categorie_id`), comme avant. Les deux s'excluent : le routeur neutralise
    # `categorie_id` dès qu'une découpe est donnée, plutôt que de refuser — un
    # écran qui bascule d'un mode à l'autre ne doit jamais laisser en base une
    # règle qui prétend classer de deux façons.
    decoupes: list[RegleDecoupeInput] = Field(default_factory=list)
    # Compte EN FACE, pour le seul type « virement interne » : le relevé ne
    # nomme qu'un des deux comptes d'un virement, et sans le second la ligne
    # arrive incomplète dans l'aperçu. Neutralisé côté routeur pour tout autre
    # type, comme categorie_id l'est déjà.
    compte_autre_id: Optional[int] = None
    actif: bool = True
    # Faut-il cesser d'évaluer les règles quand celle-ci correspond ? True par
    # défaut : c'est le comportement historique, et celui qu'on veut sur une
    # règle qu'on vient d'écrire sans y réfléchir.
    arreter_apres: bool = True

    @model_validator(mode="after")
    def _check_decoupes(self):
        """Ce qu'une découpe de règle doit respecter INDÉPENDAMMENT du montant.

        Tout ce qui dépend du montant d'une ligne (la somme des parts, un
        « reste » négatif) ne se vérifie qu'à l'import, ligne par ligne — cf.
        services/formule_decoupe.repartir. Ici on ne juge que la forme.
        """
        if not self.decoupes:
            return self
        from .services.formule_decoupe import MOT_RESTE, est_reste

        if len(self.decoupes) < 2:
            raise ValueError(
                "une découpe compte au moins deux parts ; pour une seule "
                "catégorie, utilise categorie_id"
            )
        if len(self.decoupes) > NB_MAX_PARTS_DECOUPE:
            raise ValueError(
                f"une découpe ne peut pas dépasser {NB_MAX_PARTS_DECOUPE} parts"
            )
        categories = [part.categorie_id for part in self.decoupes]
        if len(set(categories)) != len(categories):
            # Deux parts pour la même catégorie donneraient deux lignes que
            # l'histogramme rassemblerait de toute façon : autant les écrire
            # comme une seule, avec la somme des deux formules.
            raise ValueError("une même catégorie ne peut pas apparaître deux fois")
        if sum(1 for part in self.decoupes if est_reste(part.formule)) > 1:
            raise ValueError(f"une seule part peut valoir « {MOT_RESTE} »")
        return self


class RegleCategorisationCreate(RegleCategorisationBase):
    pass


class RegleCategorisationUpdate(RegleCategorisationBase):
    pass


class RegleDecoupeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    categorie_id: int
    formule: str
    ordre: int


class RegleCategorisationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nom: str
    description: str = ""
    ordre: int
    actif: bool
    arreter_apres: bool
    type_id: int
    # Code technique du type, pour que le frontend n'ait pas à recroiser la
    # table des types.
    type_code: str
    categorie_id: Optional[int] = None
    compte_autre_id: Optional[int] = None
    conditions: ConditionsRegle
    decoupes: list[RegleDecoupeRead] = Field(default_factory=list)


class ReordonnerRegles(BaseModel):
    ids: list[int]


# ---------- Règles d'import de placements (extension « import-placements ») ----------
#
# Mêmes conditions, à trois champs près (ceux d'un relevé de compte-titres), et
# une action réduite à une seule décision : ce que la ligne décrit. Cf.
# models.RegleImportPlacement pour la raison d'être de ces règles à côté du
# vocabulaire du preset.


class ConditionReglePlacement(BaseModel):
    champ: str
    operateur: OperateurRegle
    valeur: str

    @model_validator(mode="after")
    def _check_champ(self):
        return _valider_condition(self, CHAMPS_REGLE_PLACEMENT_VALIDES)


class GroupeReglePlacement(BaseModel):
    operateur: ConnecteurRegle = ConnecteurRegle.et
    conditions: list[ConditionReglePlacement] = Field(min_length=1)


class ConditionsReglePlacement(BaseModel):
    operateur: ConnecteurRegle = ConnecteurRegle.et
    groupes: list[GroupeReglePlacement] = Field(min_length=1)


class RegleImportPlacementBase(BaseModel):
    nom: str = Field(min_length=1)
    # Note libre sur la règle (migration 0050) : POURQUOI elle existe, ce que
    # le nom et les conditions ne disent pas. Jamais lue par l'application —
    # rien ne la filtre, rien ne s'y déclenche, comme `SousFiltre.description`.
    description: str = ""
    conditions: ConditionsReglePlacement
    # Ce que la ligne décrit. Pas de catégorie : un mouvement de titres n'en
    # porte pas.
    type_placement: TypeOperationPlacement
    # Le compte EN FACE, pour le seul type « transfert » : un relevé de
    # compte-titres ne nomme qu'un côté du mouvement, et sans le second la ligne
    # arrive incomplète dans l'aperçu. Le SENS n'est pas demandé — il se déduit
    # du signe du montant. Neutralisé côté routeur pour les deux autres types.
    compte_autre_id: Optional[int] = None
    # L'ÉTIQUETTE À POSER SUR LE TITRE reconnu (« ETF », « Obligation »).
    # Facultative, et sans effet sur un transfert d'espèces, qui ne désigne aucun
    # titre — le routeur la neutralise alors, comme il neutralise le compte en
    # face hors transfert.
    type_titre_id: Optional[int] = None
    actif: bool = True


class RegleImportPlacementCreate(RegleImportPlacementBase):
    pass


class RegleImportPlacementUpdate(RegleImportPlacementBase):
    pass


class RegleImportPlacementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nom: str
    description: str = ""
    ordre: int
    actif: bool
    type_placement: TypeOperationPlacement
    compte_autre_id: Optional[int] = None
    type_titre_id: Optional[int] = None
    conditions: ConditionsReglePlacement


# ---------- Sous-filtres / projets (extension « Projets ») ----------


class SousFiltreBase(BaseModel):
    nom: str = Field(min_length=1)
    # Ce que le projet recouvre, en une phrase. Sans sémantique : jamais lue,
    # ni filtrée, ni sommée par l'application.
    description: str = ""


class SousFiltreCreate(SousFiltreBase):
    pass


class SousFiltreUpdate(SousFiltreBase):
    pass


class SousFiltreTotal(BaseModel):
    """Ce qu'un projet a coûté, POUR UNE MONNAIE.

    Par monnaie et jamais autrement, comme partout ailleurs dans l'app : rien ne
    permet d'additionner des euros et des dollars, et un projet à cheval sur
    deux devises a donc deux lignes de totaux plutôt qu'un total faux.

    `depenses` et `entrees` sont des valeurs ABSOLUES ; `solde` est leur
    différence (entrées − dépenses), donc négatif pour un projet qui n'a fait
    que coûter — ce qui est le cas ordinaire d'un voyage."""

    monnaie_id: int
    monnaie_nom: str
    monnaie_symbole: str
    depenses: float
    entrees: float
    solde: float
    # L'histogramme du projet DANS CETTE MONNAIE, dans la forme exacte de celui
    # du dashboard : l'écran le dessine avec la fonction de rendu du noyau
    # (cf. extensions/projets/service_projets.depenses_par_categorie). Rangé ici
    # plutôt qu'à côté des totaux, pour qu'une monnaie n'ait qu'un seul endroit
    # où se lire.
    depenses_par_categorie: list[DepenseParCategorie] = Field(default_factory=list)


class SousFiltreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nom: str
    description: str
    ordre: int
    # Combien d'opérations le projet regroupe, et ce qu'elles pèsent : les deux
    # seules choses qu'on veut lire sur une carte de projet sans l'ouvrir.
    nombre_operations: int = 0
    totaux: list[SousFiltreTotal] = []


class SousFiltreOperations(BaseModel):
    """Les opérations qu'on verse dans un projet, ou qu'on en retire.

    Une liste et non un identifiant seul : on remplit un projet PAR LOTS, en
    cochant plusieurs lignes d'un même séjour — une requête par opération aurait
    fait autant d'allers-retours que de cases cochées."""

    operation_ids: list[int]


class ReordonnerSousFiltres(BaseModel):
    ids: list[int]


class ExtensionEtatUpdate(BaseModel):
    """Activation ou désactivation d'une extension (cf. app/extensions.py).

    Un seul champ, et volontairement : tout le reste d'une extension (nom,
    version, écrans) vient de son manifeste sur le disque, jamais du client —
    l'application ne se laisse pas dire par une requête ce qu'une extension
    contient."""

    actif: bool


class ExtensionsAnnonceesUpdate(BaseModel):
    """Extensions dont l'utilisateur vient de fermer la fenêtre d'annonce.

    Une LISTE et non un identifiant unique : la fenêtre les annonce toutes
    ensemble et se ferme d'un seul geste — les acquitter une par une
    multiplierait les allers-retours pour un même clic, et laisserait la
    moitié de la liste non acquittée si l'un d'eux échouait."""

    ids: list[str]
