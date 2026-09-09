import enum


class Sens(str, enum.Enum):
    depense = "dépense"
    entree = "entrée"
    transfert_sortant = "transfert_sortant"
    transfert_entrant = "transfert_entrant"


class Statut(str, enum.Enum):
    reel = "réel"
    previsionnel = "prévisionnel"


class Frequence(str, enum.Enum):
    hebdomadaire = "hebdomadaire"
    mensuelle = "mensuelle"
    trimestrielle = "trimestrielle"
    annuelle = "annuelle"


# Catégories créées par défaut (seed de la migration). L'utilisateur peut en
# ajouter/supprimer d'autres depuis l'onglet Catégories ; celles listées ici avec
# systeme=True sont protégées (gérées automatiquement par l'application).
# Catégories de dépense créées au premier lancement. Depuis la migration 0019
# elles ne contiennent plus que de vraies catégories : les quatre anciennes
# "catégories système" (Remboursements, Virement interne, Prêts, Remboursement
# prêts) sont devenues des TYPES d'opération (voir TypeOperation ci-dessous).
CATEGORIES_INITIALES = [
    "Alimentaire",
    "Loisirs & sorties",
    "Charges fixes",
    "Réparation & entretien",
    "Vêtements & équipement sport",
    "Autres",
    "Entrées d'argent",
]

CATEGORIE_ENTREES_ARGENT = "Entrées d'argent"
# "Autres" est protégée : non supprimable, et sert de repli pour les opérations
# dont la catégorie a été supprimée.
CATEGORIE_AUTRES = "Autres"
# Seule catégorie dont le sens est "entrée" ; les autres entrées d'argent
# (remboursement reçu, prêt reçu) sont désormais portées par le TYPE.
CATEGORIES_SENS_ENTREE = {CATEGORIE_ENTREES_ARGENT}


# ---------- Monnaies ----------
# L'app ne connaît aucun taux de change et n'additionne JAMAIS deux monnaies :
# tout ce qui agrège (solde d'un compte, KPI du dashboard, budget d'une
# catégorie, valorisation d'un portefeuille) est calculé séparément par
# monnaie. C'est le parti pris qui évite d'inventer une conversion que
# l'utilisateur devrait ensuite corriger à la main.
#
# Une seule monnaie est créée par la migration 0021, pour rattacher les données
# existantes (qui étaient toutes implicitement en euros) ; toutes les autres
# sont créées par l'utilisateur depuis Paramètres > Monnaies.
MONNAIE_INITIALE_NOM = "Euro"
MONNAIE_INITIALE_SYMBOLE = "€"


class TypeOperation(str, enum.Enum):
    """Les familles d'opérations, telles que stockées dans `type_operation`.

    Ces valeurs sont les `code` de la table : des clés techniques stables sur
    lesquelles repose toute la logique métier. Le libellé affiché (`nom`) est
    renommable par l'utilisateur et ne doit jamais servir de test.
    """

    classique = "classique"
    remboursable = "remboursable"
    remboursements = "remboursements"
    virement = "virement"
    pret = "pret"
    remboursement_pret = "remboursement_pret"
    # Mouvement d'espèces d'un achat ou d'une vente de titres. Type "interne"
    # (cf. TYPES_INTERNES) : il n'est jamais choisi à la main, il naît toujours
    # avec sa ligne OperationAction depuis la page Placements financiers.
    action = "action"


# Libellés initiaux, posés par la migration puis modifiables par l'utilisateur.
NOMS_TYPES_INITIAUX = {
    TypeOperation.classique: "Opération classique",
    TypeOperation.remboursable: "Dépense remboursable",
    TypeOperation.remboursements: "Remboursement reçu",
    TypeOperation.pret: "Prêt reçu",
    TypeOperation.remboursement_pret: "Remboursement prêt",
    TypeOperation.virement: "Virement interne",
    TypeOperation.action: "Achat / vente de titres",
}

# Ordre d'affichage (onglets de la page Opérations).
ORDRE_TYPES = [
    TypeOperation.classique,
    TypeOperation.remboursable,
    TypeOperation.remboursements,
    TypeOperation.virement,
    TypeOperation.pret,
    TypeOperation.remboursement_pret,
    TypeOperation.action,
]

# Types gérés exclusivement par une page dédiée : jamais proposés dans le
# formulaire d'opération, l'éditeur de règles, les correspondances d'import ni
# les onglets de la page Opérations, et refusés par les endpoints génériques
# /operations. Ils existent quand même dans `type_operation` pour que le sens,
# le solde et les agrégats du dashboard se calculent comme pour n'importe
# quelle opération.
TYPES_INTERNES = {TypeOperation.action}

# Les deux seuls types qui acceptent une catégorie de dépense. Les quatre
# autres n'en portent aucune : leur type EST leur classification.
TYPES_AVEC_CATEGORIE_LIBRE = {TypeOperation.classique, TypeOperation.remboursable}

# Types dont l'opération est remboursable — exactement les deux cas où la
# colonne booléenne `remboursable` valait 1 avant la migration 0019.
TYPES_REMBOURSABLES = {TypeOperation.remboursable, TypeOperation.pret}

# L'identifiant de l'extension qui tient les prêts. Le noyau garde le SCHÉMA
# (une extension n'emporte jamais ses tables) mais ne compte les prêts dans ses
# totaux que si l'écran qui les explique est là — sans quoi des intérêts
# apparaîtraient dans les sorties sans qu'aucun écran ne dise d'où ils
# viennent. Même procédé que `import_bancaire`, qui interroge « regles ».
EXTENSION_PRETS = "prets"

# CE QUI NE COMPTE JAMAIS DANS LES FLUX D'UNE PÉRIODE.
#
# Un remboursement reçu solde une dépense remboursable ; un remboursement de
# prêt solde un prêt reçu. Dans les deux cas la dette a DÉJÀ été comptée au
# moment où elle est née — une dépense remboursable ne pèse que pour ce qui
# reste à ma charge, un prêt ne pèse que pour ses intérêts. Compter en plus le
# règlement ferait payer deux fois la même chose, et dans le mauvais sens :
# recevoir 60 € de remboursement apparaissait comme 60 € d'entrées, après
# qu'on avait déjà retiré ces 60 € de la dépense.
#
# C'est aussi ce qui explique les « dépenses sans catégorie » qui creusaient
# l'écart avec l'histogramme : un remboursement de prêt n'en porte aucune (son
# type EST sa classification), il ne pouvait donc apparaître dans aucune barre
# tout en pesant sur le total.
TYPES_HORS_FLUX = {TypeOperation.remboursements, TypeOperation.remboursement_pret}

# Le libellé de la barre que les prêts ajoutent à l'histogramme. Ce n'est pas
# une catégorie — aucune ligne de `categorie` ne porte ce nom, et l'utilisateur
# ne peut ni la renommer ni lui poser un budget. C'est une barre de plus, qui
# n'apparaît que si des intérêts sont dus sur la période.
LIBELLE_INTERETS_PRETS = "Intérêts de prêts"

# Types qui règlent une dette (jamais eux-mêmes remboursables), et la cible
# qu'ils ont le droit de régler : un remboursement reçu solde une dépense
# remboursable, un remboursement de prêt solde un prêt reçu.
CIBLE_PAR_TYPE_REGLEMENT = {
    TypeOperation.remboursements: TypeOperation.remboursable,
    TypeOperation.remboursement_pret: TypeOperation.pret,
}
TYPES_REGLEMENT = set(CIBLE_PAR_TYPE_REGLEMENT)

# Types dont le sens est "entrée" (argent qui rentre), indépendamment de toute
# catégorie.
TYPES_SENS_ENTREE = {TypeOperation.remboursements, TypeOperation.pret}

# Types de comptes créés par défaut (seed de la migration), protégés (systeme=True) :
# ils pilotent des règles métier (dashboard, virements réservés à l'épargne) et ne
# sont donc jamais supprimables. L'utilisateur peut en ajouter d'autres librement
# depuis la page Comptes (purement organisationnels, ceux-là supprimables).
TYPE_COMPTE_COURANT = "courant"
TYPE_COMPTE_EPARGNE = "épargne"
# Compte-titres : deux soldes à la fois, des espèces (alimentées par virement
# interne, dépensées à l'achat de titres) et un portefeuille de titres détenus
# (cf. models.Action / models.OperationAction, page Placements financiers).
TYPE_COMPTE_PLACEMENT = "placements financiers"
TYPES_COMPTE_INITIAUX = [TYPE_COMPTE_COURANT, TYPE_COMPTE_EPARGNE, TYPE_COMPTE_PLACEMENT]
TYPES_COMPTE_SYSTEME = {TYPE_COMPTE_COURANT, TYPE_COMPTE_EPARGNE, TYPE_COMPTE_PLACEMENT}
# Comptes hors "budget courant" : ils ne reçoivent pas d'opérations classiques
# (uniquement des virements internes, plus des opérations sur titres pour les
# comptes de placement) et sont donc exclus des KPI courants du dashboard.
TYPES_COMPTE_HORS_COURANT = {TYPE_COMPTE_EPARGNE, TYPE_COMPTE_PLACEMENT}


class SensAction(str, enum.Enum):
    """Direction d'une opération sur titres. Source de vérité du couple
    (OperationAction, Operation) : le sens de l'écriture d'espèces en découle
    (achat -> transfert_sortant, vente -> transfert_entrant)."""

    achat = "achat"
    vente = "vente"

# Propriétés de l'app qu'une colonne du fichier d'import peut représenter, et
# configuration par défaut (format d'export bancaire historique à 12 colonnes).
#
# Les propriétés « de base » sont celles que tout relevé porte : une date, un
# libellé, un montant, éventuellement une catégorie bancaire. Elles se
# configurent dans « Configuration du fichier ».
PROPRIETES_IMPORT_BASE = {
    "date",
    "nature",
    "categorie_banque",
    "montant",
}

# Propriétés de la « configuration avancée ». Elles répondent toutes à la même
# question : qu'est-ce que cette ligne ne dit pas d'elle-même ?
#
#  - `compte_banque` : le compte visé, quand le fichier le nomme ligne par
#    ligne (un preset lié à un compte n'en a pas besoin) ;
#  - `sens` : le signe du montant, pour les relevés qui n'écrivent QUE des
#    montants positifs et portent « Débit »/« Crédit » dans une colonne à part
#    (cf. services/import_bancaire._signe_depuis_sens). Sans elle, le signe du
#    montant fait foi ;
#  - `monnaie` : devise du montant. Sans elle, une ligne est libellée dans la
#    monnaie principale de son compte, ce qui est faux dès qu'un compte en
#    porte plusieurs ;
#  - `montant_initial` / `monnaie_initiale` (affichés « Montant envoyé » /
#    « Monnaie envoyée ») : ce qui PART, avant frais et avant
#    conversion. `montant` (obligatoire) décrit alors ce qui arrive. L'app ne
#    connaît aucun taux de change : seul le relevé peut donner les deux ;
#  - `frais` / `monnaie_frais` : les frais prélevés par la banque. Ils
#    s'ajoutent au montant envoyé, ou se retranchent du montant, selon la
#    devise dans laquelle ils sont libellés (cf. services/import_bancaire.
#    _appliquer_frais) — c'est la seule combinaison de montants que l'app fait
#    d'elle-même, et elle n'est possible que parce que les monnaies sont lues.
#  - `montant_debit` / `montant_credit` : le montant, quand le relevé le SCINDE
#    en deux colonnes au lieu de le signer. Une ligne n'en remplit qu'une, et
#    laquelle vaut exactement ce que dirait une colonne « Sens » — d'où le même
#    traitement : le signe rejoint `montant_signe`, et tout l'aval continue de
#    raisonner dessus (cf. services/import_bancaire._montant_scinde). Ce couple
#    REMPLACE `montant`, il ne s'y ajoute pas.
#
# Ces quatre dernières remplacent le couple « colonnes supplémentaires nommées +
# formules façon tableur » qui les portait avant : le calcul libre pouvait tout
# exprimer, au prix d'une configuration que plus personne ne relisait. Une
# propriété par montant, plus une par devise, couvre les cas réels (Wise en
# tête) sans demander d'écrire quoi que ce soit.
#  - `statut` : où en est l'opération chez la banque — exécutée, en attente, ou
#    refusée/annulée (cf. StatutImport ci-dessous). Une ligne en attente devient
#    une opération prévisionnelle ; une ligne refusée n'est pas importée du tout.
PROPRIETES_IMPORT_AVANCEES = {
    "compte_banque",
    "sens",
    "monnaie",
    # Ces deux clés-là ne suivent PAS le renommage `montant_initial` ->
    # `montant_envoye` fait ailleurs : elles sont écrites telles quelles dans
    # ImportPreset.colonnes (JSON), donc dans la base. Les changer demanderait
    # une migration des presets existants pour un gain purement cosmétique —
    # personne ne les lit, seuls leurs libellés d'écran sont visibles (« Montant
    # envoyé », « Monnaie envoyée », cf. LIBELLES_PROPRIETES_IMPORT côté
    # frontend).
    "montant_initial",
    "monnaie_initiale",
    "frais",
    "monnaie_frais",
    "statut",
    "montant_debit",
    "montant_credit",
}
PROPRIETES_IMPORT_VALIDES = PROPRIETES_IMPORT_BASE | PROPRIETES_IMPORT_AVANCEES

# Le montant scindé en deux colonnes, l'une pour ce qui sort, l'autre pour ce
# qui entre. Les deux vont ensemble : n'en lire qu'une reviendrait à perdre
# toutes les lignes de l'autre côté (cf. routers/import_bancaire.
# _valider_configuration).
PROPRIETES_MONTANT_SCINDE = ("montant_debit", "montant_credit")

# `montant` n'y figure pas : il est obligatoire SAUF quand le couple
# débit/crédit le remplace, ce qu'un simple ensemble ne sait pas dire. La règle
# complète est dans routers/import_bancaire._valider_configuration.
PROPRIETES_IMPORT_OBLIGATOIRES = {"date", "nature"}

# Propriétés de montant de la configuration avancée, et la propriété de devise
# qui les qualifie : lire l'une sans l'autre n'est pas une erreur (la devise
# retombe sur celle du montant d'émission), mais mérite un avertissement à
# l'import — cf. services/import_bancaire.avertissements_configuration.
DEVISE_PAR_MONTANT_AVANCE = {
    "montant_initial": "monnaie_initiale",
    "frais": "monnaie_frais",
}

COLONNES_IMPORT_PAR_DEFAUT = [
    {"index": 1, "propriete": "date"},
    {"index": 4, "propriete": "nature"},
    {"index": 6, "propriete": "categorie_banque"},
    {"index": 7, "propriete": "montant"},
    {"index": 10, "propriete": "compte_banque"},
]


class ModeComparaison(str, enum.Enum):
    """Comment ImportPreset.colonnes_comparaison est lu par la détection de
    doublons (cf. services/import_bancaire.detecter_doublon).

    Les deux modes disent la même chose par les deux bouts, et selon le relevé
    l'un est bien plus court à décrire que l'autre :

     - `exclusion` : tout est comparé SAUF les colonnes listées. Le défaut, et
       le seul comportement qui existait jusqu'à la migration 0030. Convient
       quand une ou deux colonnes seulement bougent d'un export à l'autre
       (solde courant, référence interne, date de valeur) ;
     - `selection` : RIEN n'est comparé sauf les colonnes listées. Convient au
       cas inverse — un relevé large dont on sait que la date, le libellé et le
       montant suffisent à identifier une ligne, sans avoir à recenser les
       douze autres colonnes.

    Une liste vide n'a donc pas le même sens des deux côtés : en `exclusion`
    elle compare tout, en `selection` elle ne comparerait rien — ce qui ferait
    de chaque ligne le doublon de la première. Ce cas est refusé à
    l'enregistrement (routers/import_bancaire) et neutralisé par sécurité dans
    le détecteur.
    """

    exclusion = "exclusion"
    selection = "selection"


# ---------- Colonne « Sens » ----------
# Ce qu'un relevé écrit pour dire qu'une ligne est une sortie ou une entrée,
# quand il n'écrit que des montants positifs. Comparé après passage en
# minuscules, sans accents ni espaces (cf. services/import_bancaire.
# _signe_depuis_sens) : « Débit », « DEBIT » et « débit » sont donc le même
# libellé.
#
# Ce ne sont que les valeurs PAR DÉFAUT : depuis la migration 0027, chaque
# preset peut déclarer son propre vocabulaire (ImportPreset.libelles_sens_*),
# pour les relevés qui n'écrivent pas en français. Ces listes-ci s'appliquent
# tant qu'un preset n'en définit aucune.
#
# Liste fermée, volontairement : un libellé inconnu met la ligne en erreur avec
# la liste des valeurs acceptées, plutôt que de deviner un sens au hasard — se
# tromper ici inverse une opération dans tous les soldes.
LIBELLES_SENS_SORTIE = {
    "d",
    "db",
    "dr",
    "debit",
    "sortie",
    "sortant",
    "retrait",
    "paiement",
    "-",
}
LIBELLES_SENS_ENTREE = {
    "c",
    "cr",
    "credit",
    "entree",
    "entrant",
    "depot",
    "versement",
    "recette",
    "+",
}


# ---------- Colonne « État » ----------
class StatutImport(str, enum.Enum):
    """Où en est une ligne du relevé chez la banque.

    Trois issues seulement, et chacune donne un traitement différent :

     - `execute` : l'argent a bougé. C'est le cas ordinaire, et le seul que
       l'app supposait jusqu'ici pour toute ligne importée (opération réelle) ;
     - `attente` : autorisation prise, opération pas encore passée. Elle devient
       une opération PRÉVISIONNELLE — le montant est connu, la date de
       comptabilisation non. C'est exactement ce que `Statut.previsionnel`
       décrit déjà pour une opération saisie à la main ;
     - `refuse` : paiement refusé, virement annulé. Rien n'a bougé et rien ne
       bougera : la ligne n'est pas importée DU TOUT, et n'entre pas non plus au
       stock anti-doublons (cf. services/import_bancaire.confirmer). L'y mettre
       ferait disparaître la ligne d'un prochain import alors qu'aucune
       opération ne la représente.
    """

    execute = "execute"
    attente = "attente"
    refuse = "refuse"


# Vocabulaire par défaut de la colonne « État », même mécanique que pour le sens
# (comparaison normalisée, et chaque preset peut déclarer le sien via
# ImportPreset.libelles_statut_*). Les espaces disparaissent à la
# normalisation : « en attente » s'écrit donc « enattente » ici.
LIBELLES_STATUT_DEFAUT = {
    StatutImport.execute: {
        "execute",
        "executee",
        "effectue",
        "effectuee",
        "realise",
        "realisee",
        "comptabilise",
        "comptabilisee",
        "valide",
        "validee",
        "termine",
        "terminee",
        "ok",
    },
    StatutImport.attente: {
        "enattente",
        "attente",
        "encours",
        "pending",
        "autorisation",
        "provisoire",
        "noncomptabilise",
    },
    StatutImport.refuse: {
        "refuse",
        "refusee",
        "rejete",
        "rejetee",
        "annule",
        "annulee",
        "echec",
        "cancelled",
        "declined",
    },
}


# ---------- Règles de catégorisation ----------
# Classement automatique des lignes importées (voir
# services/regles_categorisation.py). Les règles sont globales : les mots-clés
# visés ("PRET", "REMBOURSEMENT"...) ne dépendent pas de la banque, une seule
# règle sert donc tous les presets.


class OperateurRegle(str, enum.Enum):
    """Les comparaisons qu'une condition de règle sait faire.

    DEUX FAMILLES, et elles ne se mélangent pas : les quatre premières
    comparent du TEXTE, les cinq suivantes des NOMBRES. Un champ n'admet que
    celles de sa famille (cf. OPERATEURS_PAR_CHAMP) — « la nature est
    supérieure à 50 » ne veut rien dire, et « le montant contient 12 » non plus.
    """

    est = "est"
    nest_pas = "n'est pas"
    contient = "contient"
    ne_contient_pas = "ne contient pas"
    # Numériques (montant). « égal à » double `est` plutôt que de le réemployer :
    # 50 et 50,00 sont le même nombre et deux textes différents, et c'est
    # justement ce que la famille numérique change.
    egal = "égal à"
    different = "différent de"
    superieur = "supérieur à"
    superieur_ou_egal = "supérieur ou égal à"
    inferieur = "inférieur à"
    inferieur_ou_egal = "inférieur ou égal à"


#: Les opérateurs qui comparent du texte, et ceux qui comparent des nombres.
OPERATEURS_TEXTE = {
    OperateurRegle.est,
    OperateurRegle.nest_pas,
    OperateurRegle.contient,
    OperateurRegle.ne_contient_pas,
}
OPERATEURS_NOMBRE = {
    OperateurRegle.egal,
    OperateurRegle.different,
    OperateurRegle.superieur,
    OperateurRegle.superieur_ou_egal,
    OperateurRegle.inferieur,
    OperateurRegle.inferieur_ou_egal,
}


class ConnecteurRegle(str, enum.Enum):
    """Comment combiner plusieurs conditions (dans un groupe) ou plusieurs
    groupes (dans une règle) — équivalent des filtres Notion."""

    et = "ET"
    ou = "OU"


# Champs comparables d'un relevé bancaire, et LA FAMILLE D'OPÉRATEURS de
# chacun. Trois champs de texte, plus le MONTANT, qui ne se compare qu'avec des
# opérateurs numériques.
#
# LE MONTANT EST TOUJOURS POSITIF ICI, comme dans toute l'application : le sens
# (dépense / recette) est une colonne à part, jamais un signe. « supérieur à
# 50 » veut donc dire « plus de 50 € en jeu », quel que soit le sens — et c'est
# la seule lecture qui permette d'écrire une règle sans savoir à l'avance de
# quel côté la ligne tombera.
CHAMPS_REGLE_NUMERIQUES = {"montant"}
CHAMPS_REGLE_VALIDES = {
    "nature",
    "categorie_banque",
    "compte_banque",
} | CHAMPS_REGLE_NUMERIQUES


def operateurs_admis(champ: str) -> set:
    """Les opérateurs qu'un champ accepte — l'unique endroit qui le dit.

    Le schéma Pydantic le lit pour refuser une condition incohérente, et le
    frontend expose la même partition dans son menu déroulant : sans cette
    fonction, les deux listes auraient divergé au premier ajout d'opérateur."""
    return OPERATEURS_NOMBRE if champ in CHAMPS_REGLE_NUMERIQUES else OPERATEURS_TEXTE

# Pendant du précédent pour les relevés de compte-titres (modèle
# RegleImportPlacement) : les clés du dict de ligne brute que
# services/import_bancaire.lire_lignes_brutes produit dans ce domaine, réduites
# aux trois qui portent du TEXTE. Ni la date ni les trois nombres (montant,
# quantité, cours) n'y figurent : les opérateurs disponibles sont textuels, et
# « le montant contient 12 » ne veut rien dire.
CHAMPS_REGLE_PLACEMENT_VALIDES = {"type_brut", "nom_valeur_brut", "code_isin_brut"}

#: Combien de parts une découpe peut porter, au plus. Une borne haute plutôt
#: qu'aucune : rien dans le calcul ne s'écroule à cent parts, mais un formulaire
#: qui en laisse créer autant n'a plus rien d'un formulaire, et une opération
#: qu'on ne peut plus lire d'un coup d'oeil n'est plus classée, elle est
#: éparpillée.
NB_MAX_PARTS_DECOUPE = 20


# ---------- Import de placements (extension « import-placements ») ----------
# Un relevé de compte-titres ne décrit pas les mêmes choses qu'un relevé
# bancaire : pas de catégorie ni de sens, mais une valeur, une quantité et un
# cours. Il lui faut donc son propre jeu de propriétés — d'où le DOMAINE, qui
# dit lequel des deux jeux un preset parle.
#
# POURQUOI UN DOMAINE PLUTÔT QU'UNE SECONDE TABLE. Tout ce qui entoure les
# colonnes est rigoureusement identique d'un domaine à l'autre : les
# correspondances mémorisées, l'historique, l'annulation, et surtout le stock
# anti-doublons (models.LigneImportBrute), tous scopés par preset_id. Les
# dédoubler aurait dupliqué quatre tables et toute leur mécanique pour la seule
# raison que les colonnes lues diffèrent.


class DomaineImport(str, enum.Enum):
    """Ce qu'un preset d'import sait lire.

    `bancaire` est le seul domaine qui existait jusqu'à la migration 0041 :
    c'est donc la valeur de tous les presets déjà en base, et le défaut partout
    où le domaine n'est pas dit.

    Le domaine cloisonne : le routeur du noyau ne voit que les presets
    bancaires, celui de l'extension que les presets de placements (cf.
    routers/import_bancaire._get_preset_ou_404). Un preset ne change jamais de
    domaine — ses colonnes, ses correspondances et son stock de lignes brutes
    n'auraient aucun sens de l'autre côté.
    """

    bancaire = "bancaire"
    placement = "placement"


class TypeOperationPlacement(str, enum.Enum):
    """Ce qu'une ligne d'un relevé de compte-titres peut décrire.

    Trois cas, et trois traitements entièrement différents :

     - `achat` / `vente` : un mouvement de titres, qui crée le couple
       (OperationAction, Operation) habituel — cf.
       crud.create_operation_action ;
     - `transfert` : un mouvement d'ESPÈCES entre ce compte et un autre
       (l'alimentation d'un PEA, un retrait vers le compte courant). Aucun
       titre n'y bouge : c'est un virement interne ordinaire, et il se compare
       donc aux virements déjà en base d'où qu'ils viennent (cf.
       services/import_bancaire.detecter_doublons_virements).
    """

    achat = "achat"
    vente = "vente"
    transfert = "transfert"


# Propriétés qu'une colonne d'un fichier de placements peut représenter.
#
#  - `date` : la date de l'opération ;
#  - `type_placement` : achat, vente ou transfert interne (cf. ci-dessus) ;
#  - `nom_valeur` / `code_isin` : de quel titre il s'agit. Les deux sont
#    facultatifs SÉPARÉMENT mais pas ensemble — sans l'un des deux, aucune
#    ligne d'achat ou de vente ne pourrait désigner quoi que ce soit (cf.
#    PROPRIETES_IMPORT_PLACEMENT_IDENTITE) ;
#  - `montant` : ce que l'opération a coûté ou rapporté en espèces. C'est LUI
#    qui fait foi : le solde du compte doit coller au relevé ;
#  - `quantite` : le nombre de titres achetés ou vendus ;
#  - `cours` : le prix unitaire annoncé par le relevé. Facultative sans
#    condition : le prix réellement payé se déduit de montant / quantité, et le
#    cours lu ne sert qu'à signaler un écart (frais de courtage, arrondi) ;
#  - `type_titre` : l'étiquette du titre (« ETF », « Obligation »), quand le
#    fichier la porte. Facultative elle aussi, et sans le moindre effet sur un
#    montant : elle ne fait que typer le titre que la ligne désigne (cf.
#    models.TypeTitre).
PROPRIETES_IMPORT_PLACEMENT = {
    "date",
    "type_placement",
    "nom_valeur",
    "code_isin",
    "montant",
    "quantite",
    "cours",
    "type_titre",
}

# Le titre se désigne par son nom, par son code ISIN, ou par les deux — mais
# jamais par aucun des deux. Le routeur refuse d'enregistrer une configuration
# qui les éteindrait tous les deux, et le frontend empêche le geste en amont.
PROPRIETES_IMPORT_PLACEMENT_IDENTITE = ("nom_valeur", "code_isin")

# `cours` n'y figure pas (facultatif), ni les deux propriétés d'identité
# ci-dessus (dont une seule suffit). `quantite` si : un fichier qui ne la porte
# pas ne pourrait décrire aucun achat ni aucune vente, seulement des transferts.
PROPRIETES_IMPORT_PLACEMENT_OBLIGATOIRES = {
    "date",
    "type_placement",
    "montant",
    "quantite",
}

class ModeLecturePlacement(str, enum.Enum):
    """Ce qu'un fichier de placements RACONTE.

    `operations` : une liste de mouvements — achats, ventes, transferts
    d'espèces, chacun daté. C'est le seul mode qui existait, et celui de tous
    les presets déjà en base.

    `position` : une PHOTOGRAPHIE du compte à un instant donné — une ligne par
    titre détenu, avec sa quantité et son prix de revient. Aucune date dans le
    fichier : la photo est datée du jour qu'on choisit à l'import.

    POURQUOI LES DEUX COHABITENT DANS LE MÊME ÉCRAN. C'est le même compte, le
    même courtier, le même geste : on dépose un fichier et on relit un aperçu
    avant de valider. Ce qui change tient aux colonnes lues et à ce qu'une ligne
    veut dire ; tout le reste — presets, historique, annulation, stock
    anti-doublons — est rigoureusement identique et déjà en place.

    ET POURQUOI PAS UN TROISIÈME DOMAINE (cf. DomaineImport) : le domaine
    cloisonne des ÉCRANS (le routeur bancaire ne voit pas les presets de
    placements). Ici les deux modes vivent dans le même écran et se choisissent
    dans la configuration du fichier, comme un numéro de colonne.
    """

    operations = "operations"
    position = "position"


# Propriétés qu'une colonne d'une PHOTOGRAPHIE de compte peut représenter.
#
#  - `nom_valeur` / `code_isin` : de quel titre il s'agit. Comme pour une liste
#    d'opérations, les deux sont facultatifs SÉPARÉMENT mais pas ensemble ;
#  - `quantite` : le nombre de titres DÉTENUS à l'instant de la photo ;
#  - `prix_revient` : le prix de revient UNITAIRE (PRU), c'est-à-dire ce qu'un
#    titre a coûté en moyenne. C'est lui qui part en base
#    (OperationAction.prix_unitaire) et dont découlent les plus-values ;
#  - `valeur_totale` : la valorisation actuelle de la ligne, facultative. Elle
#    ne décide d'aucune détention : elle sert à en déduire le COURS du titre
#    (valeur totale ÷ quantité), qui n'a pas de colonne à lui dans ce genre
#    d'export. Facultative parce qu'un courtier peut ne pas l'exporter, et parce
#    qu'un cours se saisit très bien à la main ensuite.
#  - `type_titre` : l'étiquette du titre, quand le fichier la porte. C'est
#    surtout ici qu'elle a des chances d'exister : un relevé de position range
#    volontiers ses lignes par catégorie de support.
PROPRIETES_IMPORT_POSITION = {
    "nom_valeur",
    "code_isin",
    "quantite",
    "prix_revient",
    "valeur_totale",
    "type_titre",
}

# `valeur_totale` n'y figure pas (facultative), ni les deux propriétés
# d'identité (dont une seule suffit, cf. PROPRIETES_IMPORT_PLACEMENT_IDENTITE).
PROPRIETES_IMPORT_POSITION_OBLIGATOIRES = {"quantite", "prix_revient"}

COLONNES_IMPORT_POSITION_PAR_DEFAUT = [
    {"index": 1, "propriete": "nom_valeur"},
    {"index": 2, "propriete": "code_isin"},
    {"index": 3, "propriete": "quantite"},
    {"index": 4, "propriete": "prix_revient"},
    {"index": 5, "propriete": "valeur_totale"},
]

COLONNES_IMPORT_PLACEMENT_PAR_DEFAUT = [
    {"index": 1, "propriete": "date"},
    {"index": 2, "propriete": "type_placement"},
    {"index": 3, "propriete": "nom_valeur"},
    {"index": 4, "propriete": "code_isin"},
    {"index": 5, "propriete": "montant"},
    {"index": 6, "propriete": "quantite"},
    {"index": 7, "propriete": "cours"},
]

# Vocabulaire par défaut de la colonne « Type d'opération », même mécanique que
# pour le sens et l'état d'un relevé bancaire : comparaison normalisée
# (minuscules, sans accents ni espaces — « Transfert interne » s'écrit donc
# « transfertinterne » ici), et chaque preset peut déclarer le sien via
# ImportPreset.libelles_type_*.
#
# Liste fermée : un libellé inconnu met la ligne en erreur plutôt que d'être
# deviné. Confondre un achat et une vente inverserait une position entière.
LIBELLES_TYPE_PLACEMENT_DEFAUT = {
    TypeOperationPlacement.achat: {
        "achat",
        "achats",
        "acquisition",
        "souscription",
        "buy",
        "compra",
    },
    TypeOperationPlacement.vente: {
        "vente",
        "ventes",
        "cession",
        "rachat",
        "remboursement",
        "sell",
        "venda",
    },
    TypeOperationPlacement.transfert: {
        "transfert",
        "transfertinterne",
        "virement",
        "virementinterne",
        "versement",
        "retrait",
        "alimentation",
        "apport",
    },
}

# Au-delà de cet écart RELATIF entre le cours lu dans le fichier et le prix
# unitaire réellement payé (montant / quantité), la ligne porte un
# avertissement. 1 % : les frais de courtage d'un ordre ordinaire pèsent
# quelques dixièmes de pourcent, un arrondi bien moins — au-delà, c'est
# probablement une colonne mal configurée, ce qu'il vaut mieux voir.
#
# Jamais bloquant : c'est le montant qui fait l'écriture, et le relevé a
# toujours raison sur ce qui a réellement quitté le compte.
ECART_COURS_TOLERE = 0.01
