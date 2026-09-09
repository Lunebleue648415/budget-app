"""Import d'un relevé bancaire au format Excel.

Les colonnes à lire (et à quelle propriété de l'app chacune correspond) sont
configurables (voir crud.get_import_configuration / ImportConfiguration) : par
défaut, le format d'export bancaire historique à 12 colonnes (1=date,
4=nature, 6=catégorie bancaire, 7=montant négatif=sortie/positif=entrée,
10=compte bancaire).

Chaque ligne devient, une fois confirmée, une opération "classique" (réel,
non remboursable) : le sens (dépense/entrée) est ensuite dérivé de la
catégorie app choisie, comme pour toute opération classique. La revue ligne
par ligne a lieu côté frontend, dans l'aperçu, avant confirmation — aucun état
de revue n'est persisté après coup.

La première ligne du fichier est une ligne de données par défaut ; les formats
qui commencent par un en-tête le déclarent via ImportPreset.
ignorer_premiere_ligne (cf. lire_lignes_brutes).

Une catégorie bancaire non mémorisée est proposée automatiquement dans
"Autres" (jamais laissée bloquante) — c'est une suggestion à confirmer côté
frontend, pas une règle de classification en dur. Rien n'est catégorisé
automatiquement en "Virement interne" : comme toute autre catégorie,
l'utilisateur doit l'assigner lui-même (à la ligne, ou via un mapping mémorisé).

PRESET LIÉ À UN COMPTE (ImportPreset.compte_id). Beaucoup de relevés sont
l'export d'UN compte précis : ils ne nomment donc nulle part le compte
concerné. Le preset peut alors porter ce compte une fois pour toutes, et il
s'impose à TOUTES les lignes du fichier — ni la colonne « compte bancaire » ni
les correspondances mémorisées ne sont consultées (cf. _resoudre_ligne). Rien
n'est perdu pour autant sur les virements internes : ce compte est déduit
émetteur ou récepteur du signe du montant, exactement comme un compte résolu
par colonne (voir ci-dessous). Non lié (défaut), le compte se résout comme
avant, avec pour dernier recours le compte choisi pour le fichier
(compte_id_defaut).

Une ligne classée par l'utilisateur en "Virement interne" ne décrit qu'un
compte via le fichier bancaire : le compte connu de la ligne (ImportLigne.
compte_id) est déduit émetteur ou récepteur selon le signe du montant
bancaire d'origine (négatif = émetteur, positif = récepteur), affiché côté
frontend. L'autre côté se complète à la main (ImportLigne.compte_id_autre), et
TANT QU'IL MANQUE LA LIGNE EST REFUSÉE (cf. _erreur_ligne) : n'en importer
qu'une jambe laisserait une écriture orpheline, qu'aucun écran ne sait plus
réparer ensuite — l'écran des virements l'affiche avec « - » en face et son
édition ne peut que proposer de la supprimer. Dès que les deux comptes sont
connus, confirmer() crée un vrai virement double-écriture (crud.create_virement,
mêmes deux opérations liées par virement_id qu'un virement créé à la main).

Des bases anciennes portent encore de telles demi-écritures, importées avant ce
refus : elles n'ont pas de virement_id, l'écran les regroupe sous une clé
`solo-<id>` et propose de les recréer. C'est le SEUL cas où un virement affiché
sans compte en face l'est réellement — sinon, c'est un filtre de la page
Opérations qui en cache la seconde jambe (cf. crud.get_operations,
`paires_virement`).

Détection de doublons : chaque ligne du fichier est comparée, dans son format
brut intégral (toutes les colonnes, pas seulement celles mappées ci-dessus),
au stock centralisé LigneImportBrute (voir detecter_doublon). Les colonnes qui
comptent sont celles que le preset désigne (ImportPreset.colonnes_comparaison),
soit comme exceptions soit comme seule liste retenue selon
ImportPreset.mode_comparaison. La comparaison ignore ce qui distingue deux
valeurs sans se voir — forme Unicode, espaces insécables, espaces de bord (cf.
normaliser_pour_comparaison). Une ligne identique reste une ImportLigne normale
(même format, Modifier/Supprimer) mais porte doublon_de (id de la ligne
existante suspectée). Un doublon n'est **pas** exclu de l'import : un doublon détecté
peut être un faux positif légitime (deux achats identiques le même jour).
Il est simplement compté pour l'historique et pré-sélectionné côté frontend,
qui bloque la confirmation tant que des lignes restent sélectionnées — donc
tant que l'utilisateur ne les a pas supprimées ou explicitement désélectionnées.

confirmer() n'alimente le stock qu'avec les lignes ayant réellement créé une
opération, en portant LigneImportBrute.operation_id (ON DELETE CASCADE) :
supprimer l'opération retire donc la ligne du stock, et le même relevé
redevient réimportable. Une ligne supprimée à la main ou en erreur n'entre
jamais au stock — elle n'a rien importé.

Fichier accepté au format Excel (.xlsx) ou CSV (peu importe l'extension : le
format est détecté sur le contenu, cf. _est_xlsx). Pour un CSV, le
délimiteur (`;`, standard des exports bancaires français, ou `,`) est détecté
automatiquement et l'encodage est décodé avec repli successif (cf.
_decoder_texte) — le reste du pipeline (parsing date/montant, détection de
doublons...) ne fait aucune différence entre les deux formats, puisqu'il
travaille déjà sur du texte brut.

RÉGLAGES DE LECTURE EN DERNIER RECOURS (`delimiteur`, `separateur_decimal` de
previsualiser/confirmer). La détection automatique du délimiteur et la
lecture permissive des nombres couvrent l'immense majorité des relevés, mais
pas tous : un délimiteur hors des trois candidats usuels, ou un format
anglo-saxon où la virgule sépare les milliers («1,234.56»), la font échouer —
et se traduit alors, dans l'aperçu, par une majorité de lignes en « date
illisible » ou « montant illisible ». C'est le signal que le frontend guette
pour proposer ces deux réglages à la main, comme le ferait l'import CSV
d'Excel. Ni l'un ni l'autre n'est mémorisé sur le preset : ce sont des
réglages DE CET ESSAI, pas du format de la banque (cf. _lire_lignes_csv,
parser_montant).

COLONNE « SENS » (facultative). Tout ce qui précède suppose un relevé qui
SIGNE ses montants : négatif = sortie, positif = entrée. Beaucoup n'en font
rien et n'écrivent que des montants positifs, le sens étant porté par une
colonne à part (« Débit »/« Crédit », « D »/« C »...). La propriété `sens` lit
cette colonne et en tire le signe manquant, qu'elle applique au montant (cf.
_signe_depuis_sens) : tout l'aval — orientation émetteur/récepteur d'un
virement en tête — continue alors de raisonner sur `montant_signe` sans rien
savoir de cette colonne. Sur une opération classique, le sens lu impose en plus
entrée/dépense, là où la catégorie seule en aurait décidé.

Le vocabulaire accepté est une liste fermée, et PROPRE AU PRESET
(ImportPreset.libelles_sens_*, cf. vocabulaire_sens) : chaque banque écrit le
sien, et un relevé anglophone ou portugais n'a aucune raison de dire « Débit ».
Un preset qui n'en déclare aucun retombe sur le vocabulaire français par défaut
(constants.LIBELLES_SENS_*). Un libellé inconnu met la ligne en erreur plutôt
que d'être deviné, se tromper ici inversant une opération dans tous les soldes.

MONTANT SCINDÉ (`montant_debit` / `montant_credit`). Autre façon, très répandue,
de ne pas signer les montants : deux colonnes au lieu d'une, chaque ligne n'en
remplissant qu'une. C'est la colonne remplie qui dit le sens, exactement comme
un mot le dirait dans une colonne « Sens » — d'où le même aboutissement, le
signe posé sur `montant_signe` (cf. _montant_scinde), et rien de nouveau en
aval. Ce couple REMPLACE `montant` (le preset lit l'un ou l'autre, cf.
routers/import_bancaire._valider_lecture_du_montant), et les deux colonnes
remplies sur une même ligne mettent celle-ci en erreur : compenser un débit par
un crédit reviendrait à inventer une opération que le relevé ne décrit pas.

Un zéro y compte comme une case vide : bien des relevés écrivent « 0,00 » du
côté inutilisé au lieu de laisser blanc, et les deux façons de dire la même
chose doivent se lire de la même façon.

CONFIGURATION AVANCÉE (voir constants.PROPRIETES_IMPORT_AVANCEES). Tout ce qui
précède décrit une ligne qui tient dans un seul couple (montant, monnaie).
Certains relevés — Wise en tête — n'en donnent jamais un : ils décrivent ce qui
part, les frais prélevés, et ce qui arrive, chacun dans sa propre devise. Le
preset lit alors, en plus des colonnes ordinaires, jusqu'à huit colonnes
« avancées » : `compte_banque`, `sens`, `monnaie`, `montant_envoye`,
`monnaie_initiale`, `frais`, `monnaie_frais`, `statut`. Ce sont des colonnes
comme les autres (même `ImportPreset.colonnes`) : seul le frontend les présente
à part.

DEUX MONTANTS. `montant` (obligatoire) est ce qui ARRIVE ; `montant_envoye`,
quand le preset le lit, est ce qui PART — avant frais et avant conversion. Sur
un virement interne, l'envoyé est donc la jambe émettrice et `montant` la jambe
réceptrice. Sans cette colonne, rien ne change : `montant` est le seul montant
de la ligne, comme pour n'importe quel relevé.

Ces deux montants ne disent RIEN du sens de l'opération : c'est le signe du
montant bancaire — ou la colonne « Sens » quand le relevé n'écrit que du
positif — qui décide si le compte du fichier émet ou reçoit, pour toute ligne
sans exception (cf. _resoudre_comptes_virement). Un compte multi-devises émet et
reçoit des virements dans des monnaies différentes, et les deux cas demandent
exactement les mêmes colonnes.

Chaque devise lue est rattachée aux monnaies de l'app par la seule
correspondance mémorisée (cf. _resoudre_monnaie) — jamais déduite d'un nom ou
d'un symbole qui se ressemblent : c'est l'utilisateur qui rattache, une fois,
et l'app s'en souvient. Les trois colonnes de devise partagent ce stock : un
relevé écrit « EUR » de la même façon qu'il s'agisse du montant, de l'envoyé
ou des frais.

FRAIS. Un relevé qui les isole les prélève sur l'un OU l'autre des deux
montants, et c'est leur DEVISE qui dit lequel : dans la monnaie envoyée ils
s'ajoutent au montant envoyé (ce qui est parti coûte plus que ce qui était
annoncé), dans celle du montant ils s'en retranchent (ce qui reste est amputé de
la commission). Aucune des deux ne correspond ? Rien n'est deviné — la ligne
porte une erreur et l'import entier est refusé (ImportBloque) tant que la
lecture des frais n'est pas retirée ou la monnaie corrigée. Additionner deux
devises fausserait un solde sans que rien ne le signale. Et une devise inconnue
ne vaut jamais accord : voir _appliquer_frais, dont c'était le défaut.

Le montant envoyé et les frais s'obtenaient auparavant par des formules façon
tableur sur des colonnes nommées librement (migration 0023) : tout était
exprimable, plus rien n'était relisible. La 0026 les a ramenés à des propriétés.
"""
import csv
import io
import re
from datetime import date as date_type, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from typing import Any, NamedTuple, Optional

import openpyxl
from pydantic import ValidationError

import unicodedata

from .. import crud, extensions, models, schemas
from . import regles_categorisation
from ..constants import (
    CATEGORIE_AUTRES,
    DEVISE_PAR_MONTANT_AVANCE,
    LIBELLES_SENS_ENTREE,
    LIBELLES_SENS_SORTIE,
    LIBELLES_STATUT_DEFAUT,
    TYPES_AVEC_CATEGORIE_LIBRE,
    ModeComparaison,
    Sens,
    Statut,
    StatutImport,
    TypeOperation,
)


class ImportBloque(Exception):
    """Un import refusé EN BLOC, message destiné tel quel à l'utilisateur.

    Réservé à ce qu'aucune ligne ne peut résoudre seule : des frais libellés
    dans une monnaie étrangère aux deux montants de la ligne. Laisser passer le
    reste du fichier donnerait un import à moitié fait, dont il faudrait ensuite
    retrouver ce qui manque (cf. confirmer)."""


# Propriété de l'app -> clé du dict de ligne brute produit par lire_lignes_brutes.
_PROPRIETE_VERS_CLE = {
    "date": "date_brute",
    "nature": "nature",
    "categorie_banque": "categorie_banque",
    "montant": "montant_brut",
    # Configuration avancée.
    "compte_banque": "compte_banque",
    "sens": "sens_banque",
    "monnaie": "monnaie_banque",
    # À gauche la clé PERSISTÉE dans ImportPreset.colonnes (inchangée, cf.
    # constants.PROPRIETES_IMPORT_AVANCEES) ; à droite le nom interne, qui suit
    # le vocabulaire « envoyé / reçu » du reste du module.
    "montant_initial": "montant_envoye_brut",
    "monnaie_initiale": "monnaie_envoyee_banque",
    "frais": "frais_brut",
    "monnaie_frais": "monnaie_frais_banque",
    "statut": "statut_banque",
    # Le montant scindé : deux colonnes qui alimentent le MÊME montant, la
    # position tenant lieu de signe (cf. _montant_scinde).
    "montant_debit": "debit_brut",
    "montant_credit": "credit_brut",
}

# Champ de ImportPreset portant le vocabulaire de chaque état.
_CHAMP_LIBELLES_STATUT = {
    StatutImport.execute: "libelles_statut_execute",
    StatutImport.attente: "libelles_statut_attente",
    StatutImport.refuse: "libelles_statut_refuse",
}


_FORMATS_DATE = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y")


def parser_date(valeur) -> Optional[date_type]:
    """La date d'une ligne, HEURE RETIRÉE.

    Une opération bancaire est datée du jour, jamais de la minute : l'app ne
    stocke qu'une date (models.Operation.date), et tout ce qui s'affiche —
    aperçu compris — est donc au même format partout. Les relevés qui
    horodatent (« 14/07/2026 09:32 », fréquent chez les néobanques) sont lus en
    ignorant simplement ce qui suit la date."""
    if valeur is None:
        return None
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date_type):
        return valeur

    texte = str(valeur).strip()
    # La partie horaire est séparée de la date par un espace ou le « T » ISO :
    # la retirer d'abord permet de garder UNE liste de formats de date, au lieu
    # de la dupliquer avec et sans heure, à la minute et à la seconde.
    date_seule = texte.replace("T", " ", 1).split(" ", 1)[0]
    for candidat in (texte, date_seule):
        for fmt in _FORMATS_DATE:
            try:
                return datetime.strptime(candidat, fmt).date()
            except ValueError:
                continue
    try:
        # Format produit par _valeur_json_safe pour une ligne déjà stockée
        # (LigneImportBrute.donnees), et accepté tel quel d'un fichier
        # horodaté en ISO.
        return datetime.fromisoformat(texte).date()
    except ValueError:
        return None


def parser_montant(valeur, separateur_decimal: Optional[str] = None) -> Optional[float]:
    """Lecture tolérante d'une cellule en nombre, ou None si ce n'en est pas un.

    Un CSV français écrit « 1 234,50 » (avec un espace insécable une fois sur
    deux) ; un xlsx rend déjà un float.

    `separateur_decimal` (None par défaut) : quand l'app ne parvient pas à
    lire un fichier (beaucoup de lignes en « montant illisible »),
    l'utilisateur peut préciser ce réglage à la main, comme le ferait l'import
    CSV d'Excel.

    - None (par défaut) : comportement historique, permissif — la virgule est
      lue comme décimale française, un point déjà présent est laissé tel quel
      (déjà un format valide pour float()). Fonctionne pour l'immense
      majorité des relevés, français ou déjà en point décimal.
    - "," ou "." explicite : c'est alors l'AUTRE caractère qui sert de
      séparateur de MILLIERS et qui est retiré, exactement comme le ferait
      Excel. Nécessaire pour les formats que le mode permissif lit mal — un
      relevé européen qui écrit "1.234,56" (point de milliers), ou un relevé
      anglo-saxon qui écrit "1,234.56" ou "1,234" (virgule de milliers, la
      confondre avec une décimale française changerait la valeur)."""
    if valeur is None:
        return None
    if isinstance(valeur, bool):
        # bool est un int en Python : sans ce garde-fou, une cellule VRAI/FAUX
        # deviendrait silencieusement 1/0.
        return None
    if isinstance(valeur, (int, float)):
        return float(valeur)
    texte = str(valeur).strip().replace(" ", "").replace(" ", "")
    if not texte:
        return None
    if separateur_decimal is None:
        texte = texte.replace(",", ".")
    else:
        separateur_milliers = "." if separateur_decimal == "," else ","
        texte = texte.replace(separateur_milliers, "")
        if separateur_decimal == ",":
            texte = texte.replace(",", ".")
    if not texte:
        return None
    try:
        return float(texte)
    except ValueError:
        return None


def _texte(valeur) -> str:
    return str(valeur).strip() if valeur is not None else ""


def normaliser_libelle(texte: str) -> str:
    """Minuscules, sans accents ni espaces : « Débit », « DEBIT » et « débit »
    doivent désigner le même sens, sans demander à l'utilisateur de deviner la
    casse exacte attendue."""
    sans_accents = "".join(
        c
        for c in unicodedata.normalize("NFD", texte)
        if unicodedata.category(c) != "Mn"
    )
    return "".join(sans_accents.split()).casefold()


def vocabulaire_sens(preset) -> tuple[set[str], set[str]]:
    """(libellés de sortie, libellés d'entrée) normalisés, pour ce preset.

    Ceux que l'utilisateur a saisis s'il l'a fait, sinon le vocabulaire
    français par défaut (constants.LIBELLES_SENS_*) : un preset qui ne touche à
    rien se comporte exactement comme avant la migration 0027.

    Les deux listes sont indépendantes — n'en renseigner qu'une (le relevé dit
    « OUT » et rien pour les entrées) laisse l'autre aux valeurs par défaut,
    plutôt que de la vider et de mettre en erreur la moitié du fichier."""
    saisis_sortie = {
        normalise
        for libelle in (preset.libelles_sens_sortie or [])
        if (normalise := normaliser_libelle(str(libelle)))
    }
    saisis_entree = {
        normalise
        for libelle in (preset.libelles_sens_entree or [])
        if (normalise := normaliser_libelle(str(libelle)))
    }
    return (
        saisis_sortie or set(LIBELLES_SENS_SORTIE),
        saisis_entree or set(LIBELLES_SENS_ENTREE),
    )


def vocabulaire_statut(preset) -> dict[StatutImport, set[str]]:
    """Les mots-clés normalisés de chaque état, pour ce preset.

    Même règle que pour le sens (cf. vocabulaire_sens) : ceux que l'utilisateur
    a saisis s'il l'a fait, sinon ceux du code, état par état — ne renseigner
    que « refusé » laisse les deux autres à leurs valeurs par défaut."""
    vocabulaire = {}
    for statut, champ in _CHAMP_LIBELLES_STATUT.items():
        saisis = {
            normalise
            for libelle in (getattr(preset, champ) or [])
            if (normalise := normaliser_libelle(str(libelle)))
        }
        vocabulaire[statut] = saisis or set(LIBELLES_STATUT_DEFAUT[statut])
    return vocabulaire


def _statut_depuis_libelle(
    libelle: str, vocabulaire: dict[StatutImport, set[str]]
) -> Optional[StatutImport]:
    """L'état d'une ligne, ou None si le libellé n'est reconnu nulle part.

    Comme pour le sens, aucune devinette : un libellé inconnu met la ligne en
    erreur. Se tromper importerait une opération refusée, ou daterait comme
    réelle une autorisation qui peut encore tomber."""
    normalise = normaliser_libelle(libelle)
    if not normalise:
        return None
    for statut, libelles in vocabulaire.items():
        if normalise in libelles:
            return statut
    return None


def _signe_depuis_sens(
    libelle: str, libelles_sortie: set[str], libelles_entree: set[str]
) -> Optional[int]:
    """-1 (sortie), +1 (entrée), ou None si le libellé n'est pas reconnu.

    C'est la seule chose que la colonne « Sens » apporte : le signe que le
    fichier n'écrit pas sur le montant. Tout le reste de l'import continue de
    raisonner sur `montant_signe`, exactement comme pour un relevé qui écrit
    « -45,20 » — orientation d'un virement comprise."""
    normalise = normaliser_libelle(libelle)
    if not normalise:
        return None
    if normalise in libelles_sortie:
        return -1
    if normalise in libelles_entree:
        return 1
    return None


# Écrit ici plutôt qu'aux deux endroits qui le disent : la lecture de la ligne
# (_montant_scinde) et la vérification d'avant import (_erreur_ligne), qui
# reconstruit ses messages à partir du seul état de la ligne.
ERREUR_MONTANT_AMBIGU = "montant présent au débit et au crédit"


class MontantScinde(NamedTuple):
    """Ce que deux colonnes débit/crédit disent d'une ligne.

    `signe` est None quand la ligne ne tranche pas (aucune des deux colonnes
    remplie, ou les deux) : c'est lui, et non `montant`, qui dit si le fichier a
    exprimé un sens — un montant nul est lisible, il n'oriente rien."""

    montant: Optional[float]
    signe: Optional[int]
    erreur: Optional[str] = None


def _montant_scinde(
    debit_brut, credit_brut, separateur_decimal: Optional[str] = None
) -> MontantScinde:
    """Le montant d'une ligne dont le relevé sépare ce qui sort de ce qui entre.

    UN ZÉRO VAUT UNE CASE VIDE. Beaucoup de relevés écrivent « 0,00 » du côté
    inutilisé plutôt que de le laisser blanc ; les prendre au mot ferait de
    chacune de leurs lignes un débit ET un crédit, c'est-à-dire une erreur à
    chaque ligne. Même convention que pour le montant envoyé et les frais.

    LES DEUX CÔTÉS REMPLIS NE SE COMPENSENT PAS. Retrancher l'un de l'autre
    fabriquerait une opération que le relevé ne décrit nulle part, et en
    choisir un arbitrairement se tromperait une fois sur deux. La ligne part
    donc sans montant et le dit — elle reste corrigeable à la main dans
    l'aperçu, comme une date illisible.

    `separateur_decimal` : cf. parser_montant, à qui c'est simplement
    transmis."""
    debit = parser_montant(debit_brut, separateur_decimal) or None
    credit = parser_montant(credit_brut, separateur_decimal) or None
    if debit is not None and credit is not None:
        return MontantScinde(None, None, ERREUR_MONTANT_AMBIGU)
    if debit is not None:
        return MontantScinde(-abs(debit), -1)
    if credit is not None:
        return MontantScinde(abs(credit), 1)
    return MontantScinde(None, None)


def _valeur_json_safe(valeur):
    """Les valeurs brutes d'openpyxl (date/datetime notamment) ne sont pas
    JSON-sérialisables telles quelles : converties en isoformat pour le
    stockage (LigneImportBrute.donnees) et la comparaison de doublons."""
    if isinstance(valeur, (datetime, date_type)):
        return valeur.isoformat()
    return valeur


def _est_xlsx(contenu: bytes) -> bool:
    """Détecte le format sur le contenu (signature ZIP d'un .xlsx), pas sur le
    nom de fichier -- une extension trompeuse ne doit jamais faire échouer
    silencieusement le mauvais parseur."""
    return contenu[:4] == b"PK\x03\x04"


def _decoder_texte(contenu: bytes) -> str:
    """Décodage tolérant d'un CSV : utf-8 en priorité, puis cp1252 (Windows,
    le plus courant pour un export bancaire français), puis latin-1 en
    dernier repli -- celui-ci ne lève jamais (tout octet y est un caractère
    valide), donc cette fonction ne peut pas échouer."""
    for encodage in ("utf-8-sig", "cp1252"):
        try:
            return contenu.decode(encodage)
        except UnicodeDecodeError:
            continue
    return contenu.decode("latin-1")


# Ordre de préférence à égalité : ";" est le standard des exports bancaires
# français, "," le plus piégeux (il est aussi le séparateur décimal français).
_DELIMITEURS_CANDIDATS = (";", "\t", ",")


def _detecter_delimiteur(echantillon: str) -> str:
    """Choisit le délimiteur qui découpe l'échantillon en un nombre de colonnes
    à la fois stable d'une ligne à l'autre et le plus grand possible.

    csv.Sniffer ne convient pas ici : sur un relevé français sans en-tête, les
    montants à virgule décimale ("-45,2") lui font élire "," alors que les
    vraies colonnes sont séparées par ";". Compter les colonnes est bien plus
    fiable — le bon délimiteur produit le même découpage sur toutes les
    lignes, le mauvais un découpage erratique.
    """
    lignes = [ligne for ligne in echantillon.splitlines() if ligne.strip()]
    if not lignes:
        return ";"

    meilleur = ";"
    meilleur_score = 0
    for delimiteur in _DELIMITEURS_CANDIDATS:
        nb_colonnes = [len(ligne.split(delimiteur)) for ligne in lignes]
        # Un délimiteur absent donne 1 colonne partout : stable, mais inutile.
        if min(nb_colonnes) < 2 or len(set(nb_colonnes)) != 1:
            continue
        if nb_colonnes[0] > meilleur_score:
            meilleur, meilleur_score = delimiteur, nb_colonnes[0]

    # Aucun candidat régulier (échantillon d'une seule ligne tronquée, guillemets
    # contenant le délimiteur...) : repli sur le standard français.
    return meilleur


def _lire_lignes_csv(contenu: bytes, delimiteur: Optional[str] = None) -> list[tuple]:
    """`delimiteur` explicite (None par défaut) : quand la détection
    automatique se trompe — un relevé qui n'utilise ni ";", ni ",", ni la
    tabulation, ou dont l'échantillon ne suffit pas à trancher — l'utilisateur
    peut l'imposer à la main, comme le ferait l'import CSV d'Excel. Sans lui,
    comportement inchangé : détection sur les 20 premières lignes."""
    texte = _decoder_texte(contenu)
    if delimiteur is None:
        # Échantillon en lignes entières (et non une tranche de caractères,
        # qui couperait la dernière ligne en plein milieu et fausserait le
        # comptage de colonnes de _detecter_delimiteur).
        echantillon = "\n".join(texte.splitlines()[:20])
        delimiteur = _detecter_delimiteur(echantillon)
    return [tuple(ligne) for ligne in csv.reader(io.StringIO(texte), delimiter=delimiteur)]


def _lire_lignes_xlsx(contenu: bytes) -> list[tuple]:
    classeur = openpyxl.load_workbook(io.BytesIO(contenu), data_only=True)
    feuille = classeur.active
    return list(feuille.iter_rows(values_only=True))


def _lire_toutes_les_lignes(contenu: bytes, delimiteur: Optional[str] = None) -> list[tuple]:
    # `delimiteur` ne concerne que le CSV (un xlsx n'a pas de délimiteur, ses
    # colonnes sont déjà structurées) : ignoré sans effet pour ce format.
    return (
        _lire_lignes_xlsx(contenu)
        if _est_xlsx(contenu)
        else _lire_lignes_csv(contenu, delimiteur)
    )


def _brute_vide(ligne_num: int, propriete_vers_cle: dict) -> dict:
    """Le squelette d'une ligne brute : toutes les propriétés lisibles à None.
    Construit depuis la table de correspondance pour qu'ajouter une propriété à
    l'import n'oblige jamais à penser à l'ajouter ici aussi."""
    brute = {cle: None for cle in propriete_vers_cle.values()}
    brute["ligne"] = ligne_num
    return brute


def lire_lignes_brutes(
    contenu: bytes,
    colonnes_config: list[dict],
    ignorer_premiere_ligne: bool = False,
    delimiteur: Optional[str] = None,
    propriete_vers_cle: Optional[dict] = None,
) -> list[dict]:
    """`ignorer_premiere_ligne` (ImportPreset) : tous les formats de relevé ne
    commencent pas par un en-tête. Le supposer systématiquement faisait perdre
    une opération à chaque import des formats qui n'en ont pas. `ligne` reste
    dans tous les cas le numéro de ligne physique dans le fichier (1-based),
    donc directement comparable à ce que l'utilisateur voit dans Excel.

    `delimiteur` : cf. _lire_lignes_csv, à qui c'est simplement transmis.

    `propriete_vers_cle` : quelles propriétés lire, et sous quel nom les ranger.
    None = celles d'un relevé bancaire (_PROPRIETE_VERS_CLE). L'extension
    « import-placements » passe la sienne — un relevé de compte-titres n'a
    aucune propriété en commun avec un relevé bancaire hormis la date et le
    montant. TOUT LE RESTE DE CETTE FONCTION LUI EST COMMUN, y compris
    `donnees_completes`, qui ne dépend d'aucune configuration : c'est ce qui
    permet aux deux domaines de partager le même détecteur de doublons."""
    propriete_vers_cle = (
        _PROPRIETE_VERS_CLE if propriete_vers_cle is None else propriete_vers_cle
    )
    toutes = _lire_toutes_les_lignes(contenu, delimiteur)
    depart = 2 if ignorer_premiere_ligne else 1
    lignes = []
    for i, row in enumerate(toutes[1:] if ignorer_premiere_ligne else toutes, start=depart):
        if row is None or all(v is None or v == "" for v in row):
            continue

        def col(index):
            return row[index - 1] if len(row) >= index else None

        brute = _brute_vide(i, propriete_vers_cle)
        for c in colonnes_config:
            cle = propriete_vers_cle.get(c["propriete"])
            if cle is not None:
                brute[cle] = col(c["index"])

        # Ligne brute intégrale (toutes les colonnes du fichier, pas
        # seulement celles mappées ci-dessus) : base de la détection de
        # doublons et du stockage centralisé (voir detecter_doublon /
        # LigneImportBrute).
        # Clé = index de colonne (1-based) en string (contrainte JSON) ; les
        # colonnes vides ne sont pas stockées (une absence de clé équivaut à
        # None des deux côtés d'une comparaison) -- une cellule vide est None
        # en xlsx, "" en CSV, les deux sont exclus.
        brute["donnees_completes"] = {
            str(idx): _valeur_json_safe(valeur)
            for idx, valeur in enumerate(row, start=1)
            if valeur not in (None, "")
        }
        lignes.append(brute)
    return lignes


# Caractères de largeur nulle : jamais visibles, parfois présents dans un
# export (marqueur d'ordre des octets égaré en plein fichier, liant de mise en
# forme). Retirés avant comparaison, sinon deux libellés rigoureusement
# identiques à l'écran ne le sont pas pour l'app.
_LARGEUR_NULLE = dict.fromkeys(map(ord, "​‌‍⁠﻿"))


# Un nombre écrit intégralement dans une cellule : signe optionnel, chiffres,
# et au plus un séparateur décimal (point ou virgule). Volontairement strict —
# ni espace de milliers, ni symbole de devise, ni exposant : tout ce qui n'est
# pas exactement un nombre reste du texte, et se compare comme du texte.
_MOTIF_NOMBRE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")


def _valeur_numerique(valeur):
    """Le nombre que porte une cellule, ou None si elle n'en porte pas.

    Decimal et non float : une référence bancaire à vingt chiffres dépasse la
    précision d'un float, et deux références distinctes s'y confondraient — ce
    qui inventerait des doublons au lieu d'en rater. Decimal compare par
    ailleurs 3500 et 3500.0 comme égaux, ce qu'on veut ici.

    Les booléens sont écartés explicitement : `isinstance(True, int)` est vrai
    en Python, et Decimal("True") lèverait."""
    if isinstance(valeur, bool):
        return None
    if isinstance(valeur, Decimal):
        return valeur
    if isinstance(valeur, (int, float)):
        # str() d'un float donne sa représentation la plus courte : "45.2", pas
        # "45.199999999999996".
        return Decimal(str(valeur))
    if isinstance(valeur, str) and _MOTIF_NOMBRE.match(valeur):
        return Decimal(valeur.replace(",", "."))
    return None


def _normaliser_valeur(valeur):
    """Cf. normaliser_pour_comparaison, dont ceci est le calcul réel."""
    if isinstance(valeur, str):
        texte = unicodedata.normalize("NFC", valeur).translate(_LARGEUR_NULLE)
        # split() sans argument découpe sur TOUTE espace Unicode (insécables
        # comprises) : le rejointoiement uniformise donc l'espacement du même coup.
        valeur = " ".join(texte.split())

    # Le nombre AVANT la date, et c'est important : datetime.fromisoformat
    # accepte la forme compacte « 20260709 », une référence purement numérique
    # deviendrait donc une date. Un nombre reste un nombre.
    nombre = _valeur_numerique(valeur)
    if nombre is not None:
        return nombre

    jour = parser_date(valeur)
    if jour is not None:
        return jour
    return valeur


def normaliser_pour_comparaison(valeur):
    """La valeur d'une cellule, débarrassée de ce qui la distingue SANS SE VOIR.

    Cinq pièges, tous invisibles à l'œil et tous rencontrés dans de vrais
    relevés — ils faisaient échouer la détection de doublons sur des lignes que
    l'utilisateur voyait pourtant identiques, jusque dans la base :

    - forme Unicode : « CAFÉ » s'écrit « É » précomposé (NFC) ou « E » + accent
      combinant (NFD) ; deux chaînes différentes, un seul rendu. D'où le NFC.
    - espaces exotiques : l'insécable (U+00A0) et la fine insécable (U+202F)
      abondent dans les exports français, et alternent avec l'espace ordinaire
      d'un export à l'autre. Tous ramenés à l'espace ordinaire.
    - espaces de bord et espaces doublés, qu'un passage par un tableur ajoute
      ou retire sans prévenir.
    - NOMBRE ÉCRIT EN TEXTE. Une même cellule ressort tantôt en nombre, tantôt
      en texte selon le typage que le tableur a décidé pour la colonne, et le
      texte garde alors les zéros de tête que le nombre perd. Constaté sur deux
      exports du même compte, à quelques minutes d'intervalle : la référence de
      compte y valait « 00040316718 » dans l'un et 40316718 dans l'autre.
    - DATE ÉCRITE AUTREMENT, le plus coûteux des cinq. Une cellule de date sort
      en texte (« 2026-07-09 ») quand la colonne est au format Général, et en
      horodatage (« 2026-07-09T00:00:00 ») quand c'est une vraie date Excel ; un
      CSV français écrit « 09/07/2026 ». Trois écritures du même jour, une seule
      à l'écran. Comparées comme du texte, elles ne coïncident JAMAIS — et comme
      une colonne de date figure dans presque toutes les comparaisons, c'est un
      fichier entier qui cesse d'être reconnu, pas une ligne isolée.

      D'où la comparaison AU JOUR : une opération bancaire n'est datée que du
      jour dans toute l'app (models.Operation.date, parser_date, l'aperçu),
      comparer plus finement que ce qu'on garde rejetterait des lignes que
      l'import traiterait de toute façon comme identiques. Un relevé horodaté
      voit donc son heure ignorée ici, comme partout ailleurs.

    Volontairement limité à l'invisible : ni casse, ni accents retirés (cf.
    normaliser_libelle, bien plus agressif, réservé au vocabulaire d'un
    preset). « Café » et « CAFE » restent deux libellés distincts — les
    confondre reviendrait à décider à la place de l'utilisateur que deux lignes
    visiblement différentes n'en font qu'une.

    Mise en cache : detecter_doublon repasse ici toutes les valeurs du stock
    pour CHAQUE ligne du fichier (cf. sa boucle), les mêmes cellules sont donc
    normalisées des milliers de fois. La fonction ne dépend que de son
    argument, le cache est donc sans effet de bord — il n'accélère pas
    seulement la lecture des dates ajoutée ici, mais tout ce qui la précède.
    """
    try:
        return _normaliser_valeur_cache(valeur)
    except TypeError:
        # Valeur non hachable (une cellule qui serait une liste ou un objet
        # JSON) : le cache ne s'applique pas, le calcul si.
        return _normaliser_valeur(valeur)


_normaliser_valeur_cache = lru_cache(maxsize=100_000)(_normaliser_valeur)


def _cles_comparees(
    donnees_a: dict, donnees_b: dict, colonnes: list[int], mode: str
) -> Optional[set[str]]:
    """Les index de colonne (en string) sur lesquels deux lignes se comparent,
    ou None si la comparaison n'a pas de sens.

    En `exclusion`, on part de toutes les colonnes présentes d'un côté ou de
    l'autre et on retire la liste — une colonne absente des deux côtés compte
    comme égale (cf. lire_lignes_brutes).

    En `selection`, seules les colonnes listées comptent, qu'elles soient
    remplies ou non. Une liste vide ne comparerait rien et ferait de chaque
    ligne le doublon de la première : le routeur l'interdit à
    l'enregistrement, et on rend None ici pour qu'une base déjà dans cet état
    (import en ligne de commande, reprise manuelle) ne produise pas un
    massacre silencieux."""
    designees = {str(idx) for idx in colonnes}
    if mode == ModeComparaison.selection.value:
        return designees or None
    return (set(donnees_a) | set(donnees_b)) - designees


def detecter_doublon(
    donnees_completes: dict[str, Any],
    lignes_existantes: list["models.LigneImportBrute"],
    colonnes_comparaison: list[int],
    mode_comparaison: str = ModeComparaison.exclusion.value,
) -> Optional["models.LigneImportBrute"]:
    """Première ligne déjà en base identique à donnees_completes sur les
    colonnes comparées (cf. _cles_comparees, qui dépend du mode), les deux
    côtés passés par normaliser_pour_comparaison.

    La normalisation a lieu ICI et pas au stockage : LigneImportBrute.donnees
    garde le fichier tel qu'il était (c'est ce qui est réaffiché à côté de la
    ligne suspectée), et les lignes déjà en base profitent du correctif sans
    aucune reprise de données."""
    normalisee = {
        cle: normaliser_pour_comparaison(valeur)
        for cle, valeur in donnees_completes.items()
    }
    for existante in lignes_existantes:
        cles = _cles_comparees(
            donnees_completes, existante.donnees, colonnes_comparaison, mode_comparaison
        )
        if cles is None:
            return None
        if all(
            normalisee.get(cle) == normaliser_pour_comparaison(existante.donnees.get(cle))
            for cle in cles
        ):
            return existante
    return None


# Deux virements du même montant, entre les deux mêmes comptes, à moins d'une
# semaine d'écart : c'est très probablement la même transaction, décrite une
# fois par le relevé du compte émetteur et une fois par celui du récepteur. Une
# semaine, parce que c'est l'ordre de grandeur du décalage entre la date de
# valeur d'une banque et celle de l'autre — au-delà, un virement récurrent (un
# loyer, une mise de côté mensuelle) tomberait dans la fenêtre et serait signalé
# tous les mois pour rien.
FENETRE_DOUBLON_VIREMENT_JOURS = 7


def _virements_en_base(
    db, debut: date_type, fin: date_type, comptes: Optional[set[int]] = None
) -> list[dict]:
    """Les virements internes DÉJÀ enregistrés dans la fenêtre demandée, réduits
    à ce qui identifie une transaction : deux comptes, un montant, une monnaie.

    D'OÙ QU'ILS VIENNENT : importés d'un relevé bancaire, importés d'un relevé de
    courtier, ou saisis à la main. Ce sont tous les mêmes `Operation` liées par
    `virement_id`, et c'est bien le but — le même mouvement figure sur le relevé
    du courtier ET sur celui du compte courant.

    Seuls les virements à double écriture sont retenus (deux jambes partageant
    un `virement_id`). Un virement importé sans son second compte n'en a qu'une :
    on ignore de quel compte l'argent vient ou va, et le rapprocher sur le seul
    compte connu signalerait comme doublon tout virement de même montant partant
    du même compte vers n'importe où.

    `comptes` RESTREINT LA RECHERCHE aux virements qui touchent l'un d'eux. Sans
    lui, un relevé de courtier se compare à tous les virements de la base, et
    deux mouvements de même montant faits la même semaine entre deux comptes
    sans rapport se signalent l'un l'autre. Avec le compte du preset, on ne
    regarde que ce qui a pu passer par le compte que le relevé décrit — ce qui
    est la seule chose qu'il puisse décrire. Un preset sans compte lié n'a rien
    à restreindre : on regarde alors tout, comme avant.
    """
    query = db.query(models.Operation).filter(
        models.Operation.virement_id.isnot(None),
        models.Operation.sens.in_([Sens.transfert_sortant, Sens.transfert_entrant]),
        models.Operation.date >= debut,
        models.Operation.date <= fin,
    )
    if comptes:
        # Le filtre porte sur le VIREMENT, pas sur la jambe : on garde les deux
        # écritures de tout virement dont au moins une touche un compte visé,
        # sans quoi la paire serait cassée et le virement écarté plus bas.
        vises = {
            identifiant
            for (identifiant,) in query.with_entities(models.Operation.virement_id)
            .filter(models.Operation.compte_id.in_(comptes))
            .distinct()
            .all()
        }
        if not vises:
            return []
        query = query.filter(models.Operation.virement_id.in_(vises))
    lignes = query.all()
    par_virement: dict[str, dict] = {}
    for operation in lignes:
        paire = par_virement.setdefault(operation.virement_id, {})
        paire["sortante" if operation.sens == Sens.transfert_sortant else "entrante"] = operation

    virements = []
    for paire in par_virement.values():
        sortante, entrante = paire.get("sortante"), paire.get("entrante")
        if sortante is None or entrante is None:
            continue
        virements.append(
            {
                "operation_id": sortante.id,
                "date": sortante.date,
                "nature": sortante.nature,
                "montant": sortante.montant,
                "monnaie_id": sortante.monnaie_id,
                "monnaie_symbole": sortante.monnaie.symbole if sortante.monnaie else "",
                # Ce qui ARRIVE, distinct de ce qui part dès qu'il y a change :
                # les deux montants doivent alors correspondre pour conclure au
                # doublon (cf. _memes_virements).
                "montant_recu": entrante.montant,
                "monnaie_recue_id": entrante.monnaie_id,
                "compte_source_id": sortante.compte_id,
                "compte_destination_id": entrante.compte_id,
                "compte_source": sortante.compte.nom,
                "compte_destination": entrante.compte.nom,
            }
        )
    return virements


def _montants_concordent(a: Optional[float], b: Optional[float]) -> bool:
    """Vrai seulement si les deux montants sont CONNUS et égaux au centime
    près. Un montant inconnu ne concorde pas : il ne dit rien."""
    if a is None or b is None:
        return False
    return abs(a - b) <= 0.005


def _jambes(profil: dict) -> list[tuple[float, Optional[int]]]:
    """Ce qu'une description de virement dit de ses jambes : (montant, monnaie),
    pour celles qu'elle connaît — une seule le plus souvent.

    Le montant et sa devise voyagent ENSEMBLE, et c'est le point : les comparer
    séparément laissait rapprocher un montant lu sur une jambe avec une devise
    lue sur l'autre."""
    jambes = []
    if profil.get("montant") is not None:
        jambes.append((profil["montant"], profil.get("monnaie_id")))
    if profil.get("montant_recu") is not None:
        jambes.append((profil["montant_recu"], profil.get("monnaie_recue_id")))
    return jambes


def _jambes_compatibles(candidat: dict, autre: dict) -> bool:
    """Les deux transactions portent-elles le même montant quelque part ?

    MÊME RAISONNEMENT QUE POUR LES COMPTES, et le même angle mort réparé. Un
    relevé ne décrit QU'UNE jambe : celui de l'émetteur ce qui part, celui du
    récepteur ce qui arrive. L'aperçu range pourtant ce montant unique dans
    `montant` — le champ de ce qui PART — quel que soit le bord d'où il vient
    (cf. candidatsDoublonsVirements). Le comparer au seul `montant` du virement
    en base revenait donc à confronter « ce qui est arrivé sur B » à « ce qui
    est parti de A ».

    Tant que les deux jambes sont égales, personne ne le voit. Elles cessent de
    l'être dès qu'il y a des FRAIS ou un CHANGE : 1 000 € partent, 998,50 €
    arrivent, et le relevé du récepteur ne se rapproche plus de rien. C'est la
    dernière chose qui restait accrochée aux rôles.

    LA RÈGLE : il suffit qu'UNE jambe de l'un concorde avec UNE jambe de
    l'autre — même montant au centime près, et devises non contradictoires. Les
    rôles ne sont réappariés que lorsque les deux descriptions connaissent leurs
    DEUX jambes, seul cas où « ce qui part » et « ce qui arrive » sont sûrs des
    deux côtés.
    """
    mes_jambes, ses_jambes = _jambes(candidat), _jambes(autre)
    if not mes_jambes or not ses_jambes:
        return False
    if len(mes_jambes) == 2 and len(ses_jambes) == 2:
        paires = zip(mes_jambes, ses_jambes)
    else:
        paires = ((mienne, sienne) for mienne in mes_jambes for sienne in ses_jambes)
    return any(
        _montants_concordent(mon_montant, son_montant)
        # Une devise inconnue d'un côté ne contredit pas : elle ne départage
        # rien. Deux devises connues et différentes, si.
        and (ma_monnaie is None or sa_monnaie is None or ma_monnaie == sa_monnaie)
        for (mon_montant, ma_monnaie), (son_montant, sa_monnaie) in paires
    )


def _comptes_compatibles(candidat: dict, autre: dict) -> bool:
    """Les deux transactions peuvent-elles concerner les mêmes comptes ?

    DEUX RÉGIMES, selon ce que l'on sait réellement.

    1. LES DEUX COMPTES DU CANDIDAT SONT CONNUS (une règle a déduit celui d'en
       face, ou l'utilisateur l'a saisi). On compare alors les PAIRES ORIENTÉES :
       émetteur avec émetteur, récepteur avec récepteur. A→B et B→A restent deux
       virements distincts — un aller et son retour ne sont pas un doublon, et
       ici on a de quoi le dire.

    2. UN DES DEUX MANQUE — le cas ordinaire, puisqu'un relevé ne nomme jamais
       que son propre compte. Il suffit alors qu'un compte soit COMMUN aux deux
       transactions, quel que soit son rôle de chaque côté.

       POURQUOI LE RÔLE EST ABANDONNÉ LÀ, et pas seulement le second compte : le
       rôle du compte connu se déduit du SIGNE du montant (cf.
       candidatsDoublonsVirements), et ce signe est parfois absent — montant
       corrigé à la main, colonnes débit/crédit vides ou toutes deux remplies,
       relevé sans colonne de sens. La ligne est alors rangée d'un côté par
       défaut, c'est-à-dire au hasard une fois sur deux, et un rapprochement
       aligné sur les rôles ratait précisément les lignes qu'on cherche. Une
       déduction incertaine ne doit pas servir à ÉCARTER : elle peut proposer,
       elle ne peut pas trancher.

    LA BORNE, dans les deux régimes : il faut au moins un compte en commun.
    Sans elle, deux lignes ne connaissant chacune qu'un compte, et pas le même,
    ne partageraient plus qu'un montant et une date — n'importe quels deux
    virements de même montant dans la semaine se signaleraient l'un l'autre. Le
    cas ne se pose pas face à un virement DÉJÀ EN BASE (il a forcément ses deux
    comptes, cf. `_virements_en_base`) mais bien entre deux lignes d'un même
    fichier.
    """
    mes_comptes = (candidat.get("compte_source_id"), candidat.get("compte_destination_id"))
    ses_comptes = (autre.get("compte_source_id"), autre.get("compte_destination_id"))
    if None not in mes_comptes and None not in ses_comptes:
        return mes_comptes == ses_comptes
    connus_miens = {compte for compte in mes_comptes if compte is not None}
    connus_siens = {compte for compte in ses_comptes if compte is not None}
    return bool(connus_miens & connus_siens)


def _memes_virements(candidat: dict, autre: dict) -> Optional[int]:
    """L'écart en jours si les deux décrivent probablement la même transaction,
    None sinon.

    QUATRE CRITÈRES, ET EUX SEULS : le compte émetteur, le compte récepteur, les
    devises, et UN MONTANT — celui qui part ou celui qui arrive, il suffit que
    l'un des deux corresponde. Plus la date, en dernier. Le libellé n'entre
    JAMAIS en jeu, c'est tout l'intérêt : le même virement décrit par deux
    banques porte deux libellés sans rapport (« VIR SEPA M. DUPONT » d'un côté,
    « Virement reçu » de l'autre), et les comparer ne ferait que rater le
    doublon qu'on cherche.

    UN SEUL COMPTE CONNU SUFFIT, et son RÔLE ne compte pas — cf.
    `_comptes_compatibles`, qui porte le détail.

    UNE JAMBE QUI CONCORDE SUFFIT, et son RÔLE ne compte pas non plus — cf.
    `_jambes_compatibles`, qui porte le détail. Une devise inconnue ne contredit
    rien : elle ne départage pas.

    Le sens compte quand on le connaît des deux côtés : A→B et B→A sont deux
    virements distincts. Il cesse de compter dès qu'une moitié manque, où il
    n'est plus qu'une déduction (cf. `_comptes_compatibles`).
    """
    if not _comptes_compatibles(candidat, autre):
        return None
    if not _jambes_compatibles(candidat, autre):
        return None
    ecart = abs((candidat["date"] - autre["date"]).days)
    # « Espacées d'au plus 7 jours » : la borne est incluse.
    return ecart if ecart <= FENETRE_DOUBLON_VIREMENT_JOURS else None


def _compte_en_face(candidat: dict, suspect: dict) -> Optional[str]:
    """Le compte que la ligne importée ne nommait PAS, tel que le virement
    auquel elle ressemble le donne. None quand elle nommait déjà les deux.

    C'est la moitié utile du rapprochement partiel : dire « tu as peut-être
    déjà cette ligne » sans dire d'où à où allait l'argent laisserait à vérifier
    à la main ce que la comparaison vient précisément d'établir.

    DÉSIGNÉ PAR ÉLIMINATION, et non par son rôle : c'est celui des deux comptes
    du suspect que la ligne ne connaît pas encore. Le rôle ne peut pas servir de
    repère — le rapprochement partiel ne s'en sert plus (cf.
    `_comptes_compatibles`), et prendre « l'émetteur du suspect parce que la
    ligne n'a pas d'émetteur » rendrait le compte que la ligne nomme déjà dès
    que le sens a été déduit à l'envers."""
    connus = {
        compte
        for compte in (candidat.get("compte_source_id"), candidat.get("compte_destination_id"))
        if compte is not None
    }
    if len(connus) >= 2:
        return None
    for identifiant, nom in (
        (suspect.get("compte_source_id"), suspect.get("compte_source")),
        (suspect.get("compte_destination_id"), suspect.get("compte_destination")),
    ):
        if identifiant is not None and identifiant not in connus:
            return nom
    return None


def detecter_doublons_virements(
    db,
    candidats: list[schemas.VirementCandidatDoublon],
    comptes: Optional[set[int]] = None,
) -> list[schemas.VirementDoublonRead]:
    """Pour chaque virement interne de l'aperçu, ceux qui lui ressemblent assez
    pour être la même transaction : déjà en base, ou plus haut dans le même
    fichier.

    Purement consultatif — rien n'est bloqué, rien n'est écarté. L'app ne peut
    pas savoir si l'utilisateur a réellement fait deux fois le même virement à
    trois jours d'intervalle ; elle peut seulement le lui montrer.

    Appelé à chaque changement de l'aperçu (chargement du fichier, reclassement
    d'une ligne en virement, saisie du compte en face) et non au moment de
    confirmer : la question se pose pendant qu'on compose l'import, pas une fois
    qu'il est parti.

    `comptes` restreint les virements DÉJÀ EN BASE auxquels on se compare (cf.
    `_virements_en_base`). L'import bancaire ne s'en sert pas — un relevé peut y
    nommer plusieurs comptes ; l'import de placements lui passe le compte de son
    preset, qui est le seul que son relevé décrive."""
    if not candidats:
        return []

    marge = timedelta(days=FENETRE_DOUBLON_VIREMENT_JOURS)
    dates = [c.date for c in candidats]
    existants = _virements_en_base(db, min(dates) - marge, max(dates) + marge, comptes)

    def profil(c) -> dict:
        return {
            "date": c.date,
            "montant": c.montant,
            "monnaie_id": c.monnaie_id,
            "montant_recu": c.montant_recu,
            "monnaie_recue_id": c.monnaie_recue_id,
            "compte_source_id": c.compte_source_id,
            "compte_destination_id": c.compte_destination_id,
        }

    resultats = []
    for index, candidat in enumerate(candidats):
        suspects = []
        for existant in existants:
            ecart = _memes_virements(profil(candidat), existant)
            if ecart is None:
                continue
            suspects.append(
                schemas.VirementDoublonSuspect(
                    source="base",
                    operation_id=existant["operation_id"],
                    date=existant["date"],
                    nature=existant["nature"],
                    montant=existant["montant"],
                    monnaie_symbole=existant["monnaie_symbole"],
                    compte_source=existant["compte_source"],
                    compte_destination=existant["compte_destination"],
                    compte_en_face=_compte_en_face(profil(candidat), existant),
                    ecart_jours=ecart,
                )
            )
        # Le même fichier peut décrire deux fois le même virement : on ne
        # rapproche qu'avec les lignes PRÉCÉDENTES, sinon chaque paire serait
        # signalée deux fois, une fois de chaque côté.
        for precedent in candidats[:index]:
            ecart = _memes_virements(profil(candidat), profil(precedent))
            if ecart is None:
                continue
            monnaie = crud.get_monnaie(db, precedent.monnaie_id) if precedent.monnaie_id else None
            suspects.append(
                schemas.VirementDoublonSuspect(
                    source="fichier",
                    ligne=precedent.ligne,
                    date=precedent.date,
                    nature="",
                    montant=precedent.montant,
                    monnaie_symbole=monnaie.symbole if monnaie else "",
                    compte_source=_nom_compte(db, precedent.compte_source_id),
                    compte_destination=_nom_compte(db, precedent.compte_destination_id),
                    ecart_jours=ecart,
                    # Rien à déduire ici en général : deux lignes d'un même
                    # fichier ignorent souvent le même compte d'en face.
                    # Même forme que pour un virement en base (identifiants ET
                    # noms) : `_compte_en_face` désigne par élimination, il lui
                    # faut de quoi reconnaître ce que la ligne connaît déjà.
                    compte_en_face=_compte_en_face(
                        profil(candidat),
                        {
                            "compte_source_id": precedent.compte_source_id,
                            "compte_source": _nom_compte(db, precedent.compte_source_id),
                            "compte_destination_id": precedent.compte_destination_id,
                            "compte_destination": _nom_compte(
                                db, precedent.compte_destination_id
                            ),
                        },
                    ),
                )
            )
        if suspects:
            resultats.append(
                schemas.VirementDoublonRead(ligne=candidat.ligne, suspects=suspects)
            )
    return resultats


def _nom_compte(db, compte_id: Optional[int]) -> str:
    """Le nom d'un compte, ou « ? » — y compris quand la ligne ne le nomme pas
    encore : depuis qu'un seul compte suffit à rapprocher, le second côté d'un
    candidat est régulièrement inconnu."""
    if compte_id is None:
        return "?"
    compte = crud.get_compte(db, compte_id)
    return compte.nom if compte else "?"


class PresetAvecColonnes:
    """Le preset tel qu'il SERAIT si ses colonnes étaient celles-ci.

    POURQUOI UN MASQUE PLUTÔT QU'UN PARAMÈTRE DE PLUS. `preset.colonnes` est lu
    à sept endroits de ce module — la lecture des lignes, l'aperçu du fichier,
    et cinq drapeaux de `ContextePreset` — souvent à travers `_index_propriete`.
    Faire descendre une liste de colonnes jusqu'à chacun aurait ajouté un
    paramètre à toute la chaîne pour un cas qui ne concerne que la
    prévisualisation.

    RIEN N'EST ÉCRIT. Mutter `preset.colonnes` sur l'objet de session aurait
    suffi à le rendre « sale », et la première écriture venue l'aurait
    enregistré — c'est-à-dire aurait modifié le preset de l'utilisateur parce
    qu'il a déplacé un en-tête pour voir. Le masque, lui, ne touche à rien : il
    répond `colonnes` et laisse passer tout le reste.
    """

    __slots__ = ("_preset", "colonnes")

    def __init__(self, preset, colonnes):
        object.__setattr__(self, "_preset", preset)
        object.__setattr__(self, "colonnes", colonnes)

    def __getattr__(self, nom):
        return getattr(self._preset, nom)


def _index_propriete(preset, propriete: str) -> Optional[int]:
    """Le numéro de colonne affecté à une propriété, ou None si le preset ne la
    lit pas."""
    return next((c["index"] for c in preset.colonnes if c["propriete"] == propriete), None)


class ContextePreset:
    """Tout ce qu'un preset apporte à la résolution d'une ligne, calculé UNE
    fois pour tout le fichier.

    Monnaies et règles de catégorisation : les recharger à chaque ligne
    coûterait cher sur un relevé de plusieurs centaines de lignes, pour un
    résultat identique. Regroupés ici plutôt que passés un par un, la
    résolution d'une ligne en dépendant de plusieurs choses."""

    __slots__ = (
        "preset",
        "preset_id",
        "compte_lie_id",
        "monnaies",
        "regles",
        "lit_le_sens",
        "libelles_sens_sortie",
        "libelles_sens_entree",
        "lit_le_statut",
        "vocabulaire_statut",
        "lit_montant_envoye",
        "lit_la_monnaie_frais",
        "lit_montant_scinde",
        "separateur_decimal",
    )

    def __init__(self, db, preset, separateur_decimal: Optional[str] = None):
        self.preset = preset
        self.preset_id = preset.id
        # Réglage de LA REQUÊTE (pas du preset, jamais mémorisé) : cf.
        # parser_montant, dont c'est le seul consommateur via _resoudre_ligne.
        self.separateur_decimal = separateur_decimal
        # Compte auquel le preset est lié, s'il l'est (cf. models.ImportPreset.
        # compte_id) : il court-circuite alors toute la résolution du compte.
        self.compte_lie_id = preset.compte_id
        self.monnaies = crud.get_monnaies(db)
        # Le classement automatique est une EXTENSION (extensions/regles) : sans
        # elle, les règles dorment en base mais ne s'appliquent plus. Le moteur
        # reste ici parce qu'il appartient à l'import ; ce qui est optionnel,
        # c'est de s'en servir. Une liste vide plutôt qu'un `if` plus bas : tout
        # le reste de la résolution continue de s'écrire sans se demander si
        # l'extension est là.
        self.regles = (
            crud.list_regles_categorisation(db) if extensions.est_active("regles") else []
        )
        # Le preset lit-il une colonne « Sens » ? Distingue une cellule vide
        # (erreur : la ligne ne dit pas son sens alors que le format l'annonce)
        # d'un preset qui ne lit simplement pas cette colonne (cas ordinaire,
        # le signe du montant fait foi).
        self.lit_le_sens = _index_propriete(preset, "sens") is not None
        # Le montant est-il scindé en deux colonnes ? Les deux vont ensemble
        # (le serveur refuse d'enregistrer une configuration qui n'en lit
        # qu'une, cf. routers/import_bancaire._valider_lecture_du_montant) : une
        # seule suffit donc à reconnaître le cas.
        self.lit_montant_scinde = _index_propriete(preset, "montant_debit") is not None
        self.libelles_sens_sortie, self.libelles_sens_entree = vocabulaire_sens(preset)
        # Même distinction pour l'état : un preset qui ne lit pas la colonne
        # traite toute ligne comme exécutée, comme avant.
        self.lit_le_statut = _index_propriete(preset, "statut") is not None
        self.vocabulaire_statut = vocabulaire_statut(preset)
        # Le preset décrit-il ce qui PART séparément de ce qui arrive ? C'est ce
        # qui fait d'une ligne un mouvement à deux montants : sans cette
        # colonne, `montant` est le seul, et rien ne change par rapport à un
        # relevé ordinaire.
        self.lit_montant_envoye = _index_propriete(preset, "montant_initial") is not None
        # Le preset annonce-t-il la devise des frais ? Distingue une cellule
        # vide (erreur : la ligne porte des frais sans dire dans quoi) d'un
        # preset qui ne lit simplement pas cette colonne — c'est la dernière
        # façon dont des frais pouvaient être appliqués sans vérification.
        self.lit_la_monnaie_frais = _index_propriete(preset, "monnaie_frais") is not None


def _resoudre_monnaie(db, preset_id: int, libelle: str) -> Optional[int]:
    """Rattache un libellé de devise du fichier (« EUR », « $ », « Dollar ») à
    une monnaie de l'app.

    Une seule source : la correspondance mémorisée, c'est-à-dire un choix
    explicite de l'utilisateur (cf. ImportMonnaieMapping). Sans elle, None : le
    libellé rejoint `monnaies_inconnues` et l'utilisateur tranche dans l'aperçu.

    Aucune reconnaissance sur le nom ou le symbole : un libellé qui ressemble à
    une monnaie de l'app n'est PAS la même chose qu'un rattachement voulu, et le
    déduire silencieusement libellait des lignes dans une monnaie que personne
    n'avait choisie. C'est le premier rattachement, fait à la main, qui décide —
    il est mémorisé, et ne se redemande plus."""
    if not libelle:
        return None
    return crud.get_mapping_monnaie(db, preset_id, libelle)


class ResultatFrais(NamedTuple):
    """Ce que devient une ligne une fois ses frais rapportés au bon montant.

    `monnaie_operation_id` est la devise dans laquelle `montant` est exprimé :
    elle change quand c'est le montant INITIAL qui devient le montant de
    l'opération (opération sortante à un seul compte, cf. _appliquer_frais).

    `incoherents` est distingué de `erreur` parce qu'il ne se corrige pas ligne
    par ligne : il dit que la CONFIGURATION du preset ne tient pas, et c'est lui
    seul qui refuse l'import en bloc (cf. confirmer)."""

    montant: Optional[float]
    montant_envoye: Optional[float]
    monnaie_operation_id: Optional[int] = None
    erreur: Optional[str] = None
    incoherents: bool = False


def _orienter_jambe_virement(
    resultat: ResultatFrais,
    *,
    est_virement: bool,
    lit_montant_envoye: bool,
    lit_la_monnaie: bool,
    sortante: bool,
) -> ResultatFrais:
    """Sur un virement dont le fichier ne décrit qu'UNE jambe, dit laquelle.

    Un relevé sans colonne « Montant envoyé » NI colonne de devise n'écrit
    qu'un montant, et forcément dans la monnaie de son propre compte. Sur une
    ligne SORTANTE, ce montant est donc ce qui PART — le montant envoyé — et ce
    qui arrive sur l'autre compte reste inconnu (l'app ne convertit rien). Le
    laisser dans `montant`, qui décrit ce qui ARRIVE depuis la migration 0029,
    inversait les deux : le débit s'affichait en « montant reçu » et le champ
    « montant envoyé (envoyé) » restait vide, à rebours du relevé.

    Trois abstentions, chacune parce que la jambe décrite n'est plus évidente :

    - ligne ENTRANTE : le montant lu est bien ce qui arrive, `montant` est déjà
      le bon champ, et c'est la jambe émettrice qui manque (cf.
      _montants_virement) ;
    - colonne « Montant envoyé » lue : le fichier décrit les deux jambes, il
      n'y a rien à orienter ;
    - colonne de DEVISE lue : le montant peut alors être libellé dans une
      monnaie que le compte du relevé ne porte pas (un relevé Wise qui sort
      108 $ d'une poche en euros décrit ce qui ARRIVE), et c'est l'utilisateur
      qui complète l'autre jambe dans l'aperçu. Deviner ici inverserait
      précisément ce qu'on cherche à remettre à l'endroit.
    """
    if not est_virement or lit_montant_envoye or lit_la_monnaie or not sortante:
        return resultat
    if resultat.montant is None or resultat.montant_envoye is not None:
        return resultat
    return resultat._replace(montant=None, montant_envoye=resultat.montant)


def _frais_incoherents(
    nom_monnaie_frais: str, cote: str, monnaie_operation_id: Optional[int] = None
) -> ResultatFrais:
    """Les montants sont abandonnés (la ligne ne sera pas importée) mais la
    devise est conservée : l'aperçu continue d'afficher la ligne, et une
    monnaie perdue en route l'y rendrait illisible."""
    return ResultatFrais(
        None,
        None,
        monnaie_operation_id,
        erreur=(
            f"frais en « {nom_monnaie_frais} » : ce n'est pas la monnaie "
            f"{cote} à laquelle ils devraient s'appliquer"
        ),
        incoherents=True,
    )


def _grever(montant: Optional[float], frais: float, sortante: bool) -> tuple[Optional[float], Optional[str]]:
    """LA règle générale : des frais font toujours perdre de la valeur.

    Sur une sortie, ils s'ajoutent — le compte est débité de plus que le montant
    annoncé. Sur une entrée, ils se retranchent — il arrive moins que ce qui a
    été envoyé. Tout le reste de ce module n'est que le choix du montant auquel
    les appliquer."""
    if montant is None:
        return None, None
    magnitude = abs(montant) + frais if sortante else abs(montant) - frais
    if frais and magnitude <= 0:
        # Sans frais, un montant nul est le problème d'une autre vérification
        # (« montant illisible ») : ne le réclamer ici qu'en présence de frais
        # garde le message juste.
        return None, "frais supérieurs au montant de la ligne"
    return magnitude, None


def _appliquer_frais(
    montant_op: Optional[float],
    montant_envoye: Optional[float],
    frais: Optional[float],
    monnaie_id: Optional[int],
    monnaie_envoyee_id: Optional[int],
    monnaie_frais_id: Optional[int],
    nom_monnaie_frais: str = "",
    sortante: bool = True,
    est_virement: bool = False,
) -> ResultatFrais:
    """Quel montant l'opération porte, et ce que les frais lui font.

    RÈGLE GÉNÉRALE : des frais font toujours perdre de la valeur à
    l'utilisateur (cf. _grever). Le reste est le choix du montant auquel les
    appliquer, et il dépend de trois choses : la présence d'un montant envoyé,
    le type d'opération, et le sens.

    SANS MONTANT INITIAL — seul `montant` existe et fait l'opération. Les frais
    s'y ajoutent si elle sort, s'en retranchent si elle entre.

    AVEC MONTANT INITIAL, VIREMENT INTERNE — la ligne décrit deux jambes :
    l'envoyé est ce qui part du compte émetteur, `montant` ce qui arrive sur le
    récepteur (lequel des deux est le compte du fichier se lit sur le sens, cf.
    _resoudre_comptes_virement). Les frais grèvent la jambe que LEUR DEVISE
    désigne, avec priorité à l'émission quand les deux monnaies sont les mêmes :
    payer 2 € de frais sur un envoi de 100 € fait 102 € débités, et c'est cette
    lecture-là qui vaut, pas « 100 € envoyés, 98 € reçus ».

    AVEC MONTANT INITIAL, OPÉRATION À UN SEUL COMPTE — un seul des deux montants
    concerne le compte, et c'est le sens qui dit lequel. Sortante, l'argent
    quitte le compte : le montant envoyé fait l'opération, frais en plus, dans
    SA monnaie. Entrante, l'argent arrive : `montant` fait l'opération, frais en
    moins. L'autre montant ne décrit que la contrepartie et n'est pas importé.

    LES INCONNUES NE VALENT PAS ACCORD. Une devise non résolue (« EUR » pas
    encore rattaché) ou une colonne de devise non lue ne fait jamais passer une
    comparaison pour concluante — c'était le défaut qui laissait des frais
    s'ajouter sans la moindre vérification :

     - devise des frais LUE mais non rattachée : on n'applique rien, la ligne
       porte déjà l'erreur « monnaie non résolue » et ne sera pas importée ;
     - devise des frais PAS LUE : rien à comparer, on applique au montant que le
       cas désigne. C'est ce que `avertissements_configuration` signale à chaque
       import ;
     - devise de l'autre côté inconnue : elle ne peut pas contredire, la
       comparaison qui reste tranche seule.
    """
    monnaie_operation_id = monnaie_id
    # Zéro frais suit exactement le même chemin : le choix du montant qui fait
    # l'opération ne dépend pas d'eux, seulement du cas. Les traiter à part
    # aurait fait diverger les deux (une sortie à un seul compte doit porter le
    # montant envoyé, frais ou pas).
    frais = abs(frais) if frais else 0.0

    # Devise annoncée mais pas encore rattachée : on ne touche à rien, la ligne
    # porte déjà l'erreur « monnaie non résolue ».
    if frais and nom_monnaie_frais and monnaie_frais_id is None:
        return ResultatFrais(
            abs(montant_op) if montant_op is not None else None,
            abs(montant_envoye) if montant_envoye is not None else None,
            monnaie_operation_id,
        )
    devise_frais_connue = bool(frais) and bool(nom_monnaie_frais) and monnaie_frais_id is not None

    def concorde(autre_monnaie_id: Optional[int]) -> bool:
        """Vrai tant que rien ne CONTREDIT : une devise inconnue d'un côté ou de
        l'autre laisse passer, seule une différence avérée bloque."""
        return (
            not devise_frais_connue
            or autre_monnaie_id is None
            or monnaie_frais_id == autre_monnaie_id
        )

    # ---------- Sans montant envoyé : un seul montant, un seul choix ----------
    if montant_envoye is None:
        if not concorde(monnaie_id):
            if est_virement:
                # Un virement a deux jambes, et le fichier n'en décrit qu'une :
                # des frais dans une autre monnaie appartiennent à celle qui
                # manque. On les laisse en attente plutôt que de bloquer tout
                # l'import — la jambe émettrice se saisit dans l'aperçu, et les
                # frais s'y ajoutent alors (cf. _reimputer_frais).
                return ResultatFrais(
                    abs(montant_op) if montant_op is not None else None,
                    None,
                    monnaie_operation_id,
                )
            return _frais_incoherents(nom_monnaie_frais, "du montant", monnaie_operation_id)
        magnitude, erreur = _grever(montant_op, frais, sortante)
        return ResultatFrais(magnitude, None, monnaie_operation_id, erreur=erreur)

    # ---------- Virement interne : deux jambes, la devise désigne laquelle ----------
    if est_virement:
        montant_abs = abs(montant_op) if montant_op is not None else None
        initial_abs = abs(montant_envoye)
        # Priorité à l'émission : quand les deux monnaies sont les mêmes, c'est
        # l'envoi qui coûte plus cher, pas la réception qui rapporte moins.
        if devise_frais_connue and monnaie_envoyee_id is not None:
            sur_lemission = monnaie_frais_id == monnaie_envoyee_id
        elif devise_frais_connue and monnaie_id is not None:
            sur_lemission = monnaie_frais_id != monnaie_id
        else:
            sur_lemission = True
        if sur_lemission:
            if not concorde(monnaie_envoyee_id):
                return _frais_incoherents(nom_monnaie_frais, "initiale", monnaie_operation_id)
            return ResultatFrais(montant_abs, initial_abs + frais, monnaie_operation_id)
        if not concorde(monnaie_id):
            return _frais_incoherents(nom_monnaie_frais, "du montant", monnaie_operation_id)
        reste, erreur = _grever(montant_op, frais, sortante=False)
        return ResultatFrais(reste, initial_abs, monnaie_operation_id, erreur=erreur)

    # ---------- Un seul compte : le sens désigne le montant qui compte ----------
    if sortante:
        monnaie_operation_id = monnaie_envoyee_id or monnaie_id
        if not concorde(monnaie_envoyee_id):
            return _frais_incoherents(nom_monnaie_frais, "initiale", monnaie_operation_id)
        magnitude, erreur = _grever(montant_envoye, frais, sortante=True)
        return ResultatFrais(magnitude, None, monnaie_operation_id, erreur=erreur)

    if not concorde(monnaie_id):
        return _frais_incoherents(nom_monnaie_frais, "du montant", monnaie_operation_id)
    magnitude, erreur = _grever(montant_op, frais, sortante=False)
    return ResultatFrais(magnitude, None, monnaie_operation_id, erreur=erreur)


def _resoudre_ligne(
    db,
    contexte: ContextePreset,
    brute: dict,
    compte_id_defaut: Optional[int] = None,
) -> schemas.ImportLigne:
    preset_id = contexte.preset_id

    date_op = parser_date(brute["date_brute"])
    nature = _texte(brute["nature"])
    nom_categorie_banque = _texte(brute["categorie_banque"])
    nom_compte_banque = _texte(brute["compte_banque"])

    erreurs = []
    # Le montant vient d'UNE colonne signée, ou de DEUX dont la position tient
    # lieu de signe — jamais des deux façons à la fois (cf.
    # routers/import_bancaire._valider_lecture_du_montant).
    if contexte.lit_montant_scinde:
        scinde = _montant_scinde(
            brute["debit_brut"], brute["credit_brut"], contexte.separateur_decimal
        )
    else:
        scinde = MontantScinde(
            parser_montant(brute["montant_brut"], contexte.separateur_decimal), None
        )
    montant_op = scinde.montant
    # Montant envoyé et frais (configuration avancée) : None pour tout preset
    # qui ne lit pas ces colonnes.
    #
    # Zéro compte comme absent : un virement qui fait partir 0 n'existe pas, et
    # une colonne de frais vide vaut 0 sur bien des relevés. Sans cela, l'erreur
    # affichée parlerait de comptes identiques au lieu du montant envoyé manquant.
    montant_envoye = (
        parser_montant(brute["montant_envoye_brut"], contexte.separateur_decimal) or None
    )
    frais = parser_montant(brute["frais_brut"], contexte.separateur_decimal) or None

    # Devises du relevé (configuration avancée) : None pour un preset qui ne les
    # lit pas, la ligne retombant alors sur la monnaie principale de son compte.
    # Les trois puisent dans le même stock de correspondances : un relevé écrit
    # « EUR » de la même façon quel que soit le montant qualifié.
    nom_monnaie_banque = _texte(brute["monnaie_banque"])
    monnaie_id = _resoudre_monnaie(db, preset_id, nom_monnaie_banque)
    nom_monnaie_envoyee_banque = _texte(brute["monnaie_envoyee_banque"])
    monnaie_envoyee_id = _resoudre_monnaie(db, preset_id, nom_monnaie_envoyee_banque)
    nom_monnaie_frais_banque = _texte(brute["monnaie_frais_banque"])
    monnaie_frais_id = _resoudre_monnaie(db, preset_id, nom_monnaie_frais_banque)

    # Gardés avant toute imputation de frais : ce sont eux que l'aperçu propose
    # à la correction, et la base sur laquelle les frais sont RÉIMPUTÉS dès que
    # le type ou le sens de la ligne change (cf. _reimputer_frais). Sans eux,
    # repasser une ligne de virement à opération classique demanderait de
    # défalquer à l'aveugle des frais déjà incorporés.
    montant_hors_frais = abs(montant_op) if montant_op is not None else None
    montant_envoye_hors_frais = abs(montant_envoye) if montant_envoye is not None else None

    # Colonne « Sens » : le signe que le fichier n'écrit pas sur le montant.
    # Appliqué au montant, il rend le reste de l'import identique à celui d'un
    # relevé signé — c'est `montant_signe` qui oriente les virements, et lui
    # seul. Le sens explicite prime donc sur un éventuel signe déjà présent.
    #
    # Lu AVANT l'imputation des frais : c'est le sens qui décide si les frais
    # s'ajoutent ou se retranchent, et à quel montant.
    nom_sens_banque = _texte(brute["sens_banque"])
    signe_sens = _signe_depuis_sens(
        nom_sens_banque, contexte.libelles_sens_sortie, contexte.libelles_sens_entree
    )
    if signe_sens is not None and montant_op is not None:
        montant_op = abs(montant_op) * signe_sens

    # Le fichier a-t-il dit LUI-MÊME si l'argent entre ou sort ? Par un mot dans
    # une colonne « Sens », ou par le choix de la colonne remplie sur un montant
    # scindé : les deux tranchent, là où un montant signé se contente
    # d'orienter les virements (cf. confirmer, qui n'impose entrée/dépense sur
    # une opération classique que dans ce cas).
    sens_explicite = bool(nom_sens_banque) or scinde.signe is not None

    if date_op is None:
        erreurs.append("date illisible")
    if scinde.erreur:
        # Précède « montant illisible », qui serait vrai aussi mais dirait que
        # rien n'a été lu — alors qu'ici deux montants l'ont été.
        erreurs.append(scinde.erreur)
    elif montant_op is None:
        erreurs.append("montant illisible")
    if not nature:
        erreurs.append("nature manquante")
    if contexte.lit_le_sens and signe_sens is None:
        # Le vocabulaire étant désormais modifiable (cf. vocabulaire_sens), le
        # message cite celui du preset : sans ça, l'utilisateur ne sait pas
        # contre quoi son libellé a été comparé.
        acceptes = ", ".join(
            sorted(contexte.libelles_sens_sortie | contexte.libelles_sens_entree)
        )
        erreurs.append(
            f"sens « {nom_sens_banque} » non reconnu (attendus : {acceptes})"
            if nom_sens_banque
            else "sens manquant"
        )

    # Colonne « État » : exécutée, en attente, ou refusée. Un preset qui ne la
    # lit pas laisse `statut_import` à None, ce que tout l'aval traite comme
    # « exécutée » — le comportement d'avant.
    nom_statut_banque = _texte(brute["statut_banque"])
    statut_import = _statut_depuis_libelle(nom_statut_banque, contexte.vocabulaire_statut)
    if contexte.lit_le_statut and statut_import is None:
        acceptes = ", ".join(
            sorted(set().union(*contexte.vocabulaire_statut.values()))
        )
        erreurs.append(
            f"état « {nom_statut_banque} » non reconnu (attendus : {acceptes})"
            if nom_statut_banque
            else "état manquant"
        )

    # Règles de catégorisation : le seul mécanisme capable de poser le type
    # automatiquement à partir des libellés (voir services.regles_categorisation).
    resultat_regle = regles_categorisation.appliquer_regles(
        contexte.regles,
        {
            "nature": nature,
            "categorie_banque": nom_categorie_banque,
            "compte_banque": nom_compte_banque,
            # LE MONTANT EN VALEUR ABSOLUE, comme partout dans l'app : le sens
            # est une colonne, jamais un signe. « supérieur à 50 » veut donc
            # dire « plus de 50 € en jeu », de quelque côté que la ligne tombe.
            #
            # Le montant du FICHIER, pas celui qu'aura l'opération : les frais
            # ne sont imputés qu'après (ils dépendent du type, que ces règles
            # sont justement en train de poser). Une règle qui vise « plus de
            # 50 € » compare donc ce qu'on lit sur le relevé, ce qui est aussi
            # la seule valeur que l'utilisateur a sous les yeux en l'écrivant.
            "montant": abs(montant_op) if montant_op is not None else None,
        },
    )
    type_code = resultat_regle.type_code if resultat_regle else TypeOperation.classique.value

    # LES FRAIS, MAINTENANT SEULEMENT : quel montant fait l'opération et ce que
    # les frais lui font dépendent du SENS et du TYPE, tous deux connus depuis
    # les lignes précédentes. C'est aussi pourquoi ce calcul est rejoué dès
    # qu'une retouche change l'un ou l'autre (cf. _reimputer_frais).
    resultat_frais = _appliquer_frais(
        montant_op,
        montant_envoye,
        frais,
        monnaie_id,
        monnaie_envoyee_id,
        monnaie_frais_id,
        nom_monnaie_frais_banque,
        sortante=montant_op is None or montant_op < 0,
        est_virement=TypeOperation(type_code) == TypeOperation.virement,
    )
    resultat_frais = _orienter_jambe_virement(
        resultat_frais,
        est_virement=TypeOperation(type_code) == TypeOperation.virement,
        lit_montant_envoye=contexte.lit_montant_envoye,
        lit_la_monnaie=_index_propriete(contexte.preset, "monnaie") is not None,
        sortante=montant_op is None or montant_op < 0,
    )
    # Le montant envoyé n'a pas été LU : il a été déduit de l'orientation
    # ci-dessus. La distinction compte en aval — un fichier qui décrit vraiment
    # les deux jambes donne aussi les deux devises (cf. _monnaies_virement).
    montant_envoye_deduit = resultat_frais.montant_envoye is not None and not contexte.lit_montant_envoye
    # Les valeurs HORS FRAIS suivent la même orientation : c'est d'elles que
    # repart _reimputer_frais quand une retouche change le type ou le sens.
    if montant_envoye_deduit:
        montant_hors_frais, montant_envoye_hors_frais = None, montant_hors_frais
    montant_final = resultat_frais.montant
    montant_envoye = resultat_frais.montant_envoye
    monnaie_operation_id = resultat_frais.monnaie_operation_id
    if resultat_frais.erreur:
        erreurs.append(resultat_frais.erreur)
    # Le format annonce une colonne de devise des frais, la ligne porte des
    # frais, et la cellule est vide : elle ne dit pas dans quelle monnaie ils
    # sont, et rien ne permet de le supposer. Même règle que pour le sens et
    # l'état — c'est le dernier chemin par lequel des frais pouvaient être
    # rapportés à un montant sans vérification.
    elif frais and contexte.lit_la_monnaie_frais and not nom_monnaie_frais_banque:
        erreurs.append("monnaie des frais manquante")

    # LA RÈGLE PASSE AVANT LA CORRESPONDANCE, et elle est seule maîtresse du
    # type. Une correspondance ne renseigne plus que la catégorie.
    #
    # C'est ce qui rend l'ensemble cohérent : les quatre types sans catégorie
    # libre (virement interne, prêt reçu, remboursement reçu, remboursement de
    # prêt) sont détectés par une règle, et la catégorie n'est alors même pas
    # consultée — elle vaut NULL par construction pour ces types. Une
    # correspondance fourre-tout (« Divers » -> Autres) ne peut donc plus
    # rétrograder en dépense classique une ligne qu'une règle a reconnue comme
    # un virement.
    categorie_id = None
    categorie_suggestion_auto = False

    # LA DÉCOUPE D'UNE RÈGLE PASSE AVANT TOUT LE RESTE, et pour la même raison
    # que la catégorie d'une règle : c'est une intention explicite. Résolue ici
    # sur le montant FINAL (frais compris), qui est celui de l'opération à
    # écrire — l'invariant « somme des parts = montant » porte sur lui.
    decoupes_ligne: list = []
    decoupe_erreur = None
    if (
        resultat_regle is not None
        and resultat_regle.decoupes
        and TypeOperation(type_code) in TYPES_AVEC_CATEGORIE_LIBRE
    ):
        parts, decoupe_erreur = regles_categorisation.resoudre_decoupes(
            resultat_regle.decoupes, montant_final
        )
        decoupes_ligne = [
            schemas.DecoupeInput(categorie_id=categorie, montant=part)
            for categorie, part in (parts or [])
        ]
        # Une part unique ne serait pas une découpe (cf. crud.erreur_decoupes) :
        # les formules ont beau être deux, elles ont pu n'en laisser qu'une
        # au-dessus de zéro sur cette ligne. La catégorie ordinaire reprend
        # alors la main, plus bas.
        if len(decoupes_ligne) < 2:
            decoupes_ligne = []

    if decoupes_ligne:
        pass
    elif TypeOperation(type_code) in TYPES_AVEC_CATEGORIE_LIBRE:
        if resultat_regle is not None and resultat_regle.categorie_id is not None:
            # Catégorie posée par une règle : intention explicite de
            # l'utilisateur, elle ne redemande pas de confirmation (tout
            # l'intérêt des règles) et prime sur la correspondance.
            categorie_id = resultat_regle.categorie_id
        elif nom_categorie_banque:
            categorie_id = crud.get_mapping_categorie(db, preset_id, nom_categorie_banque)

        if categorie_id is None:
            # Ni règle ni correspondance : on propose "Autres" par défaut plutôt
            # que de bloquer la ligne — l'utilisateur confirme ou change ce choix
            # avant de valider l'import (voir frontend).
            categorie_suggeree = crud.get_categorie_by_nom(db, CATEGORIE_AUTRES)
            categorie_id = categorie_suggeree.id if categorie_suggeree else None
            categorie_suggestion_auto = True

    # Un preset lié à un compte tranche pour toutes ses lignes : c'est le relevé
    # DE ce compte, le fichier n'a donc rien à en dire. Ni la colonne « compte
    # bancaire » ni les correspondances mémorisées ne sont consultées — les
    # laisser passer devant reviendrait à ignorer un choix explicite de
    # l'utilisateur, et à réintroduire les lignes « compte non résolu » que la
    # liaison sert précisément à supprimer.
    if contexte.compte_lie_id is not None:
        compte_id = contexte.compte_lie_id
    else:
        compte_id = (
            crud.get_mapping_compte(db, preset_id, nom_compte_banque)
            if nom_compte_banque
            else None
        )
        if compte_id is None and not nom_compte_banque and compte_id_defaut is not None:
            compte_id = compte_id_defaut

    # Le compte EN FACE d'un virement, quand une règle le désigne : le relevé ne
    # décrit qu'un côté de la transaction, et sans l'autre la ligne est refusée
    # à la confirmation (cf. _erreur_ligne). Une règle qui reconnaît « VIREMENT
    # VERS LIVRET A » sait pourtant parfaitement où va l'argent.
    #
    # Jamais le même compte des deux côtés : ce serait une conversion de change,
    # qui n'a rien à faire ici (et qu'un virement à monnaie unique refuserait de
    # toute façon, cf. VirementCreate).
    compte_id_autre = None
    if resultat_regle is not None and resultat_regle.compte_autre_id is not None:
        if resultat_regle.compte_autre_id != compte_id:
            compte_id_autre = resultat_regle.compte_autre_id

    return schemas.ImportLigne(
        ligne=brute["ligne"],
        date=date_op,
        nature=nature,
        # Le montant de l'opération, frais compris : ce n'est pas forcément la
        # magnitude de `montant_signe` (une sortie à un seul compte porte le
        # montant envoyé, cf. _appliquer_frais).
        montant=montant_final,
        # Le montant du fichier, SIGNÉ et hors frais : il ne sert qu'à orienter
        # (sens de l'opération, émetteur/récepteur d'un virement) et ne doit
        # donc jamais suivre l'imputation des frais.
        montant_signe=montant_op,
        nom_banque_categorie=nom_categorie_banque,
        nom_banque_compte=nom_compte_banque,
        categorie_id=categorie_id,
        decoupes=decoupes_ligne,
        decoupe_erreur=decoupe_erreur,
        compte_id=compte_id,
        compte_id_autre=compte_id_autre,
        categorie_suggestion_auto=categorie_suggestion_auto,
        type_code=type_code,
        regle_appliquee=resultat_regle.nom_regle if resultat_regle is not None else None,
        erreur=", ".join(erreurs) if erreurs else None,
        # Libellé de sens lu dans le fichier, affiché tel quel dans l'aperçu :
        # son effet (le signe) se lit déjà dans montant_signe.
        nom_banque_sens=nom_sens_banque,
        sens_explicite=sens_explicite,
        montant_ambigu=scinde.erreur is not None,
        # Configuration avancée. Les montants calculés sont stockés en valeur
        # absolue comme `montant` : le sens d'une opération vient de son type et
        # de son signe (montant_signe), jamais de ces montants annexes.
        nom_banque_monnaie=nom_monnaie_banque,
        monnaie_id=monnaie_id,
        monnaie_operation_id=monnaie_operation_id,
        montant_envoye=abs(montant_envoye) if montant_envoye is not None else None,
        montant_envoye_deduit=montant_envoye_deduit,
        nom_banque_monnaie_envoyee=nom_monnaie_envoyee_banque,
        monnaie_envoyee_id=monnaie_envoyee_id,
        frais=abs(frais) if frais is not None else None,
        nom_banque_monnaie_frais=nom_monnaie_frais_banque,
        monnaie_frais_id=monnaie_frais_id,
        montant_hors_frais=montant_hors_frais,
        montant_envoye_hors_frais=montant_envoye_hors_frais,
        frais_incoherents=resultat_frais.incoherents,
        nom_banque_statut=nom_statut_banque,
        statut_import=statut_import.value if statut_import is not None else None,
    )


def _brute_depuis_donnees(donnees: dict[str, Any], preset, ligne_num: int) -> dict:
    """Reconstruit la structure attendue par _resoudre_ligne à partir d'une
    LigneImportBrute.donnees déjà stockée (clé = index de colonne en string),
    en la faisant repasser par la configuration de colonnes ACTUELLE — comme
    pour une ligne fraîchement lue du fichier (cf. lire_lignes_brutes)."""
    brute = _brute_vide(ligne_num, _PROPRIETE_VERS_CLE)
    for c in preset.colonnes:
        cle = _PROPRIETE_VERS_CLE.get(c["propriete"])
        if cle is not None:
            brute[cle] = donnees.get(str(c["index"]))
    brute["donnees_completes"] = donnees
    return brute


def _resoudre_ligne_existante(
    db, contexte: ContextePreset, existante: "models.LigneImportBrute"
) -> schemas.ImportLigne:
    """Version résolue (même format qu'une ligne fraîchement importée) d'une
    ligne déjà en base, pour l'affichage en lecture seule à côté de la ligne
    suspectée doublon (voir ImportPreview.lignes_existantes)."""
    brute = _brute_depuis_donnees(existante.donnees, contexte.preset, existante.id)
    return _resoudre_ligne(db, contexte, brute, compte_id_defaut=None)


def _texte_cellule_apercu(valeur) -> str:
    """Une cellule telle qu'affichée dans « Le fichier tel qu'il est ».

    Les dates y sont écrites JJ/MM/AAAA, heure retirée : c'est le format de
    l'app, et une opération n'est de toute façon datée que du jour (cf.
    parser_date). Sans cela, un xlsx horodaté affichait
    « 2026-07-14T09:32:00 » ici et « 14/07/2026 » deux blocs plus bas, pour la
    même ligne."""
    if isinstance(valeur, (datetime, date_type)):
        return valeur.strftime("%d/%m/%Y")
    texte = _texte(valeur)
    # Un CSV donne du texte : la date y est déjà écrite JJ/MM/AAAA, il ne reste
    # qu'une heure éventuelle à retirer. Volontairement limité à ce cas — passer
    # TOUTE cellule par parser_date reformaterait au passage des références
    # bancaires qui ressemblent à une date sans en être une (« 20260714… »).
    if " " in texte or "T" in texte:
        date_lue = parser_date(texte)
        if date_lue is not None:
            return date_lue.strftime("%d/%m/%Y")
    return texte


def construire_apercu_fichier(
    contenu: bytes,
    colonnes_config: list[dict],
    ignorer_premiere_ligne: bool,
    delimiteur: Optional[str] = None,
    propriete_vers_cle: Optional[dict] = None,
) -> schemas.ApercuFichier:
    """Le fichier tel quel (lignes non vides), INTÉGRAL, avec la propriété
    affectée à chaque colonne — de quoi vérifier visuellement que la
    configuration tombe en face des bonnes données.

    Plus aucune troncature : une colonne décalée ne l'est pas forcément dès les
    premières lignes (un relevé change de format en cours de fichier, une
    ligne de solde s'intercale…), et vérifier cela demande de pouvoir tout
    parcourir. C'est le frontend qui borne la HAUTEUR du tableau (cf.
    --apercu-lignes-visibles), le reste restant accessible en défilant.

    `delimiteur` : cf. _lire_lignes_csv, à qui c'est simplement transmis —
    l'aperçu du fichier brut doit refléter la même lecture que les lignes
    résolues, sans quoi les deux se contrediraient à l'écran.

    `propriete_vers_cle` : cf. lire_lignes_brutes. Même table des deux côtés,
    sans quoi l'aperçu colorerait des colonnes que la lecture n'a pas lues."""
    propriete_vers_cle = (
        _PROPRIETE_VERS_CLE if propriete_vers_cle is None else propriete_vers_cle
    )
    toutes = [
        ligne
        for ligne in _lire_toutes_les_lignes(contenu, delimiteur)
        if ligne is not None and not all(v is None or v == "" for v in ligne)
    ]
    largeur = max((len(ligne) for ligne in toutes), default=0)
    lignes = [
        [_texte_cellule_apercu(ligne[i]) if i < len(ligne) else "" for i in range(largeur)]
        for ligne in toutes
    ]
    proprietes = {
        str(c["index"]): c["propriete"]
        for c in colonnes_config
        if c.get("propriete") in propriete_vers_cle
    }
    return schemas.ApercuFichier(
        lignes=lignes,
        proprietes_par_colonne=proprietes,
        total_lignes=len(toutes),
        premiere_ligne_ignoree=ignorer_premiere_ligne,
    )


# Les trois couples (libellé lu, monnaie résolue) d'une ligne : la devise du
# montant, celle du montant envoyé, celle des frais. Elles partagent le même stock
# de correspondances, et une seule à rattacher suffit à traiter les trois.
_CHAMPS_MONNAIE = (
    ("nom_banque_monnaie", "monnaie_id"),
    ("nom_banque_monnaie_envoyee", "monnaie_envoyee_id"),
    ("nom_banque_monnaie_frais", "monnaie_frais_id"),
)


def _monnaies_inconnues(lignes: list[schemas.ImportLigne]) -> list[str]:
    """Les libellés de devise du fichier qu'aucune correspondance mémorisée n'a
    permis de rattacher, toutes colonnes de devise confondues."""
    return sorted(
        {
            getattr(ligne, champ_nom)
            for ligne in lignes
            for champ_nom, champ_id in _CHAMPS_MONNAIE
            if getattr(ligne, champ_nom) and getattr(ligne, champ_id) is None
        }
    )


def _monnaies_resolues(lignes: list[schemas.ImportLigne], monnaies) -> dict[str, str]:
    """Les libellés de devise du fichier DÉJÀ rattachés, et à quelle monnaie.

    Contrepartie de `_monnaies_inconnues` : ce que l'aperçu ne redemande pas,
    parce qu'une correspondance mémorisée l'a déjà tranché. Les voir permet de
    relire ce qui va être appliqué sans ouvrir les correspondances du preset.

    Rien de plus qu'un affichage : la résolution, elle, se fait dans
    `_resoudre_monnaie`."""
    par_id = {monnaie.id: monnaie.nom for monnaie in monnaies}
    return {
        getattr(ligne, champ_nom): par_id.get(getattr(ligne, champ_id), "")
        for ligne in lignes
        for champ_nom, champ_id in _CHAMPS_MONNAIE
        if getattr(ligne, champ_nom) and getattr(ligne, champ_id) is not None
    }


def avertissements_configuration(preset) -> list[str]:
    """Ce que la configuration laisse d'ambigu sans être faux : un montant
    initial ou des frais lus SANS la devise qui les qualifie.

    Ce n'est pas une erreur — la ligne retombe alors sur le comportement par
    défaut, qui est juste dans le cas courant (une seule devise). Mais c'est
    précisément l'hypothèse qu'un relevé multi-devises vient contredire, et la
    seule façon de s'en apercevoir serait un solde faux : d'où l'avertissement,
    affiché à chaque import tant que la colonne de devise n'est pas configurée.

    Le cas des FRAIS est le plus sensible : sans leur devise, l'app ne peut pas
    vérifier à quel montant ils se rapportent, et c'est la seule vérification qui
    protège d'une addition entre deux monnaies (cf. _appliquer_frais)."""
    # Clés = propriétés persistées (cf. DEVISE_PAR_MONTANT_AVANCE), donc
    # « montant_initial » ; les libellés, eux, parlent d'envoi comme partout
    # ailleurs à l'écran.
    libelles = {
        "montant_initial": (
            "Le montant envoyé est lu sans sa monnaie",
            "Monnaie envoyée",
            "elle sera supposée identique à celle du montant reçu",
        ),
        "frais": (
            "Les frais sont lus sans leur monnaie",
            "Monnaie des frais",
            "ils seront rapportés au montant envoyé sans vérification possible",
        ),
    }
    proprietes = {c["propriete"] for c in preset.colonnes}
    messages = []
    for propriete_montant, propriete_devise in DEVISE_PAR_MONTANT_AVANCE.items():
        if propriete_montant not in proprietes or propriete_devise in proprietes:
            continue
        constat, colonne_a_ajouter, consequence = libelles[propriete_montant]
        messages.append(
            f"{constat} : {consequence}. Ajoute une colonne "
            f"« {colonne_a_ajouter} » dans la configuration avancée si ce n'est "
            f"pas le cas."
        )
    return messages


def previsualiser(
    db,
    preset_id: int,
    contenu: bytes,
    compte_id_defaut: Optional[int] = None,
    delimiteur: Optional[str] = None,
    separateur_decimal: Optional[str] = None,
    colonnes: Optional[list] = None,
) -> schemas.ImportPreview:
    """`delimiteur` et `separateur_decimal` (None par défaut, tous les deux) :
    réglages de LECTURE que l'utilisateur peut préciser à la main quand l'app
    n'arrive pas à lire le fichier (beaucoup de lignes en « date illisible »
    ou « montant illisible » dans l'aperçu qui en résulte) — jamais mémorisés
    sur le preset, ils ne valent que pour cet essai. Cf. _lire_lignes_csv et
    parser_montant, à qui ils sont simplement transmis.

    `colonnes` est de la même famille : ce que l'écran a SOUS LES YEUX, qui n'est
    pas forcément ce que le preset porte en base. C'est ce qui permet de
    réorganiser les colonnes — en déplaçant les en-têtes de l'aperçu, ou en
    corrigeant leurs numéros — et de VOIR le résultat avant de décider de
    l'enregistrer. Rien n'est écrit : le preset ne change qu'au moment où on le
    demande (cf. PresetAvecColonnes)."""
    preset = crud.get_import_preset(db, preset_id)
    if colonnes is not None:
        preset = PresetAvecColonnes(preset, colonnes)
    lignes_existantes_brutes = crud.list_lignes_import_brutes(db, preset_id)
    colonnes_comparaison = preset.colonnes_comparaison
    mode_comparaison = preset.mode_comparaison

    # Monnaies et règles : chargées une seule fois pour tout le fichier plutôt
    # qu'à chaque ligne.
    contexte = ContextePreset(db, preset, separateur_decimal)

    lignes = []
    lignes_existantes = {}
    for brute in lire_lignes_brutes(
        contenu,
        preset.colonnes,
        preset.ignorer_premiere_ligne,
        delimiteur,
    ):
        doublon = detecter_doublon(
            brute["donnees_completes"],
            lignes_existantes_brutes,
            colonnes_comparaison,
            mode_comparaison,
        )
        ligne_resolue = _resoudre_ligne(db, contexte, brute, compte_id_defaut)
        if doublon is not None:
            ligne_resolue = ligne_resolue.model_copy(update={"doublon_de": doublon.id})
            if str(doublon.id) not in lignes_existantes:
                lignes_existantes[str(doublon.id)] = _resoudre_ligne_existante(
                    db, contexte, doublon
                )
        lignes.append(ligne_resolue)

    # "à confirmer" = pas de mapping explicite mémorisé, même si une valeur
    # par défaut a déjà été proposée pour la catégorie. Inclut les lignes
    # doublons : si l'utilisateur les vérifie quand même (faux positif), leur
    # mapping doit lui aussi avoir été confirmé.
    categories_inconnues = sorted(
        {l.nom_banque_categorie for l in lignes if l.nom_banque_categorie and l.categorie_suggestion_auto}
    )
    comptes_inconnus = sorted(
        {l.nom_banque_compte for l in lignes if l.nom_banque_compte and l.compte_id is None}
    )
    return schemas.ImportPreview(
        lignes=lignes,
        lignes_existantes=lignes_existantes,
        categories_inconnues=categories_inconnues,
        comptes_inconnus=comptes_inconnus,
        monnaies_inconnues=_monnaies_inconnues(lignes),
        monnaies_resolues=_monnaies_resolues(lignes, contexte.monnaies),
        apercu_fichier=construire_apercu_fichier(
            contenu,
            preset.colonnes,
            preset.ignorer_premiere_ligne,
            delimiteur,
        ),
        avertissements=avertissements_configuration(preset),
    )


def _erreur_ligne(ligne: schemas.ImportLigne) -> Optional[str]:
    manques = []
    est_virement = TypeOperation(ligne.type_code) == TypeOperation.virement
    if ligne.date is None:
        manques.append("date illisible")
    # Un virement sortant lu sans colonne « Montant envoyé » porte son montant
    # dans `montant_envoye` et rien dans `montant` : ce qui arrive sur l'autre
    # compte est inconnu tant que les deux monnaies ne sont pas connues (cf.
    # _orienter_jambe_virement). La ligne est complète pour autant — c'est
    # `confirmer` qui réclamera le montant reçu, et seulement s'il y a change.
    if ligne.montant is None and not (est_virement and ligne.montant_envoye is not None):
        # « Illisible » serait faux pour une ligne qui a rempli SES DEUX
        # colonnes de montant : deux montants ont bien été lus, c'est de savoir
        # lequel compte qu'il s'agit. Le message disparaît de lui-même dès
        # qu'une retouche fournit le montant.
        manques.append(ERREUR_MONTANT_AMBIGU if ligne.montant_ambigu else "montant illisible")
    # Un virement s'oriente par le SIGNE du montant bancaire, et par lui seul
    # (cf. _resoudre_comptes_virement). Sans signe, l'émetteur et le récepteur
    # seraient intervertis en silence : une ligne dont le montant a été corrigé
    # à la main (le fichier n'en donnait pas, ou en donnait deux, cf.
    # _montant_scinde) porte un montant sans porter de sens, et c'est
    # exactement ce cas-là. Refusée plutôt qu'importée à l'envers.
    if est_virement and ligne.montant_signe is None:
        manques.append("virement interne : le sens de la ligne est indéterminé")
    if not ligne.nature:
        manques.append("nature manquante")
    # UNE LIGNE DÉCOUPÉE EST CLASSÉE, même sans `categorie_id` : ses parts SONT
    # sa classification (cf. models.OperationDecoupe), exactement comme un type
    # à catégorie imposée dispense des deux lignes suivantes.
    if (
        ligne.categorie_id is None
        and not ligne.decoupes
        and TypeOperation(ligne.type_code) in TYPES_AVEC_CATEGORIE_LIBRE
    ):
        manques.append("catégorie non résolue")
    if ligne.compte_id is None:
        manques.append("compte non résolu")
    # Une devise lue mais non rattachée décide de la monnaie de l'écriture :
    # laisser passer la ligne reviendrait à la libeller silencieusement dans la
    # monnaie principale du compte, c'est-à-dire dans la mauvaise. Vrai des
    # trois colonnes de devise — celle des frais décide en plus à quel montant
    # ils s'appliquent (cf. _appliquer_frais).
    for champ_nom, champ_id in _CHAMPS_MONNAIE:
        libelle = getattr(ligne, champ_nom)
        if libelle and getattr(ligne, champ_id) is None:
            manques.append(f"monnaie « {libelle} » non résolue")
    if ligne.frais_incoherents:
        manques.append("frais dans une monnaie étrangère aux montants de la ligne")
    # Un virement interne décrit DEUX comptes : n'en importer qu'un laisserait
    # une écriture orpheline, à retrouver et compléter à la main plus tard. On
    # préfère refuser la ligne tant que l'autre côté n'est pas désigné.
    if est_virement and ligne.compte_id_autre is None:
        manques.append("virement interne : le compte en face n'est pas renseigné")
    # Amortissement coché sans ses deux bornes : la ligne dit qu'elle s'étale
    # sans dire sur quoi. Refusée plutôt qu'importée sans étalement — l'oubli
    # se verrait alors seulement dans l'histogramme, des mois plus tard.
    if ligne.amorti and (
        ligne.amortissement_debut is None or ligne.amortissement_fin is None
    ):
        manques.append("amortissement : premier et dernier mois attendus")
    if (
        ligne.amorti
        and ligne.amortissement_debut is not None
        and ligne.amortissement_fin is not None
        and ligne.amortissement_fin < ligne.amortissement_debut
    ):
        manques.append("amortissement : le dernier mois précède le premier")
    return ", ".join(manques) if manques else None


def _statut_operation(ligne: schemas.ImportLigne) -> Statut:
    """Réel, sauf pour une ligne que la banque annonce en attente.

    Une autorisation non encore comptabilisée décrit exactement ce que
    `Statut.previsionnel` recouvre déjà pour une opération saisie à la main : le
    montant est connu, le passage en banque non. La compter comme réelle
    fausserait le solde réel jusqu'à ce qu'elle passe vraiment."""
    if ligne.statut_import == StatutImport.attente.value:
        return Statut.previsionnel
    return Statut.reel


def _resoudre_comptes_virement(ligne: schemas.ImportLigne) -> tuple[Optional[int], Optional[int]]:
    """(compte_source_id, compte_destination_id). `compte_id` est le compte
    connu du fichier, `compte_id_autre` celui complété à la main.

    UNE SEULE RÈGLE, pour toutes les lignes : le signe du montant bancaire —
    négatif, le compte du fichier est l'émetteur. La colonne « Sens » y est déjà
    incorporée, puisqu'elle sert précisément à donner ce signe aux relevés qui
    ne l'écrivent pas (cf. _signe_depuis_sens).

    Lire « Montant envoyé » ne dit rien du sens : un compte multi-devises
    ÉMET et REÇOIT des virements dans des monnaies différentes, et les deux cas
    demandent les mêmes colonnes. En tirer que le compte du fichier est
    l'émetteur classait toutes ses lignes en sortie."""
    emetteur = ligne.montant_signe is not None and ligne.montant_signe < 0
    return (
        (ligne.compte_id, ligne.compte_id_autre)
        if emetteur
        else (ligne.compte_id_autre, ligne.compte_id)
    )


def _reimputer_frais(ligne: schemas.ImportLigne) -> schemas.ImportLigne:
    """Rejoue le calcul des montants à partir des valeurs HORS FRAIS de la
    ligne, avec son type et son sens ACTUELS.

    C'est le pendant dynamique de `_appliquer_frais` : les mêmes règles, mais
    appliquées après coup. Indispensable parce que le montant qui fait
    l'opération dépend du type et du sens, tous deux modifiables dans l'aperçu —
    repasser une ligne de virement interne à opération classique change la jambe
    qui compte, donc le montant importé. Sans ce recalcul, l'aperçu montrerait
    un montant qui ne correspond plus à ce que la ligne est devenue.

    Trois déclencheurs (cf. confirmer) : une retouche qui change le type, une
    qui change le sens, ou une qui fournit des frais. Les montants hors frais
    sont conservés sur la ligne précisément pour que ce recalcul reparte d'une
    base propre, sans avoir à défalquer une imputation précédente.

    `montant_signe` est laissé intact : il porte le montant du fichier, qui
    n'appartient pas au calcul et sert uniquement à orienter."""
    resultat = _appliquer_frais(
        ligne.montant_hors_frais,
        ligne.montant_envoye_hors_frais,
        ligne.frais,
        ligne.monnaie_id,
        ligne.monnaie_envoyee_id,
        ligne.monnaie_frais_id,
        # La devise des frais peut venir ici d'un choix explicite dans l'aperçu
        # et non d'une cellule : elle est « lue » dès qu'elle est renseignée.
        nom_monnaie_frais=ligne.nom_banque_monnaie_frais
        or ("x" if ligne.monnaie_frais_id is not None else ""),
        sortante=(ligne.montant_signe or 0) < 0,
        est_virement=TypeOperation(ligne.type_code) == TypeOperation.virement,
    )
    # Repasser une ligne EN virement dans l'aperçu doit l'orienter comme si le
    # fichier l'avait donnée telle quelle : sans ça, le montant du relevé
    # resterait du côté « reçu » sur une ligne sortante, exactement le défaut
    # que _orienter_jambe_virement corrige à la lecture.
    resultat = _orienter_jambe_virement(
        resultat,
        est_virement=TypeOperation(ligne.type_code) == TypeOperation.virement,
        lit_montant_envoye=ligne.montant_envoye_hors_frais is not None
        and not ligne.montant_envoye_deduit,
        lit_la_monnaie=bool(ligne.nom_banque_monnaie),
        sortante=(ligne.montant_signe or 0) < 0,
    )
    montant = abs(resultat.montant) if resultat.montant is not None else None
    montant_envoye = (
        abs(resultat.montant_envoye) if resultat.montant_envoye is not None else None
    )
    # L'orientation vient d'avoir lieu si un montant envoyé apparaît alors que
    # la ligne n'en portait aucun hors frais. Le drapeau, lui, ne se relève
    # jamais tout seul : « ce montant envoyé n'a jamais été lu dans une
    # colonne » reste vrai même si la ligne repasse par un autre type. Seule une
    # saisie explicite l'efface (cf. confirmer).
    orientation_appliquee = montant_envoye is not None and ligne.montant_envoye_hors_frais is None
    return ligne.model_copy(
        update={
            "montant": montant,
            "monnaie_operation_id": resultat.monnaie_operation_id,
            "montant_envoye": montant_envoye,
            "montant_envoye_deduit": ligne.montant_envoye_deduit or orientation_appliquee,
            # Les valeurs hors frais suivent l'orientation, pour que la
            # réimputation suivante reparte du bon côté.
            "montant_hors_frais": None if orientation_appliquee else ligne.montant_hors_frais,
            "montant_envoye_hors_frais": (
                ligne.montant_hors_frais
                if orientation_appliquee
                else ligne.montant_envoye_hors_frais
            ),
            "frais_incoherents": resultat.incoherents,
            "erreur": resultat.erreur or ligne.erreur,
        }
    )


def _montants_virement(
    ligne: schemas.ImportLigne,
) -> tuple[Optional[float], Optional[float]]:
    """(montant envoyé, montant reçu) d'un virement importé, l'inconnu à None.

    Un preset qui lit « Montant envoyé » donne les deux : ce qui part, et ce
    qui arrive (`montant`).

    Sans cette colonne, le relevé ne décrit qu'une jambe : celle de SON compte,
    et c'est le sens qui dit laquelle. Sortante, le montant lu a été placé dans
    `montant_envoye` (cf. _orienter_jambe_virement) et c'est le montant reçu
    qui manque ; entrante, `montant` est ce qui est arrivé et c'est le montant
    envoyé qui manque. Rien n'est déduit de l'autre ici : entre deux monnaies,
    l'app ne connaît aucun taux (cf. confirmer, qui réclame le manquant)."""
    if ligne.montant_envoye is not None:
        return ligne.montant_envoye, ligne.montant
    sortante = (ligne.montant_signe or 0) < 0
    return (ligne.montant, None) if sortante else (None, ligne.montant)


def _jambe_manquante(
    ligne: schemas.ImportLigne,
    montant_envoye: Optional[float],
    montant_recu: Optional[float],
) -> tuple[Optional[float], Optional[float]]:
    """La jambe que le relevé ne décrit pas, déduite de celle qu'il décrit ET
    DES FRAIS.

    LES FRAIS NE TRAVERSENT PAS. Ils vont à la banque, pas au compte d'en face :
    virer 100 € avec 2 € de frais fait perdre 102 € à l'émetteur et n'en fait
    gagner que 100 au récepteur. Le patrimoine perd donc 2 € — et c'est
    exactement ce qui manquait.

    LE DÉFAUT QUE ÇA CORRIGE. La jambe manquante reprenait purement et
    simplement l'autre, frais compris : l'émetteur perdait 102, le récepteur
    gagnait 102, et les frais s'annulaient d'un compte à l'autre. Le solde total
    de l'app dépassait alors celui de la banque de la somme de tous les frais de
    virement jamais importés — un écart qui grandit à chaque import, sans que
    rien ne le signale.

    LES DEUX SENS SE DÉDUISENT PAREIL, parce que `_appliquer_frais` a déjà posé
    les frais sur la jambe que le relevé décrit :

      - relevé de l'ÉMETTEUR : `montant_envoye` vaut le viré + les frais ; ce
        qui arrive en face est donc `montant_envoye - frais` ;
      - relevé du RÉCEPTEUR : `montant` vaut le viré - les frais ; ce qui est
        parti d'en face est donc `montant + frais`.

    Dans les deux cas, la jambe manquante vaut le montant HORS FRAIS.

    SEULEMENT SANS CHANGE — l'appelant ne s'en sert que là (cf. confirmer). Entre
    deux monnaies, retrancher des frais à ce qui part ne dit rien de ce qui
    arrive : il faudrait un taux, et l'app n'en connaît aucun.
    """
    frais = abs(ligne.frais) if ligne.frais else 0.0
    if montant_envoye is None and montant_recu is not None:
        return montant_recu + frais, montant_recu
    if montant_recu is None and montant_envoye is not None:
        # Jamais négatif : `montant_envoye` vaut le hors-frais PLUS les frais
        # (cf. _appliquer_frais), la soustraction rend donc le hors-frais.
        return montant_envoye, max(0.0, montant_envoye - frais)
    return montant_envoye, montant_recu


def _monnaies_virement(
    ligne: schemas.ImportLigne,
    compte_source: "models.Compte",
    compte_destination: "models.Compte",
) -> tuple[int, int]:
    """(monnaie envoyée, monnaie reçue) d'un virement importé.

    Quand le preset lit « Montant envoyé », le fichier décrit les deux jambes :
    « Monnaie envoyée » dit dans quoi l'argent est parti, `monnaie_id` dans
    quoi il est arrivé. C'est tout l'intérêt de lire ces colonnes.

    Sans montant envoyé, le fichier ne décrit qu'un côté : `monnaie_id` est
    alors celle de l'envoi (le compte du fichier est l'émetteur), et la monnaie
    reçue se déduit du compte récepteur — la même si ce compte la porte (le
    montant reçu est alors identique), sinon sa monnaie principale.

    Un montant envoyé DÉDUIT ne compte pas comme deux jambes décrites : il n'a
    aucune devise propre (le relevé ne porte pas de colonne de devise, sans quoi
    rien n'aurait été déduit — cf. _orienter_jambe_virement), et le prendre pour
    tel ferait partir le virement dans la monnaie principale du compte émetteur
    et arriver dans celle du récepteur, soit un change là où il n'y en a pas."""
    if ligne.montant_envoye is not None and not ligne.montant_envoye_deduit:
        return (
            ligne.monnaie_envoyee_id or compte_source.monnaie_principale_id,
            ligne.monnaie_id or compte_destination.monnaie_principale_id,
        )

    monnaie_source_id = ligne.monnaie_id or compte_source.monnaie_principale_id
    monnaie_destination_id = (
        monnaie_source_id
        if monnaie_source_id in compte_destination.monnaie_ids
        else compte_destination.monnaie_principale_id
    )
    return monnaie_source_id, monnaie_destination_id


def _erreur_monnaie_compte(
    monnaie_id: Optional[int], compte: "models.Compte", role: str
) -> Optional[str]:
    """Une opération est toujours libellée dans une monnaie que son compte
    porte (cf. models.Operation.monnaie_id) : le vérifier ici évite de créer
    une écriture invisible dans tous les soldes, que rien ne rattraperait."""
    if monnaie_id is not None and monnaie_id in compte.monnaie_ids:
        return None
    possibles = ", ".join(sorted(lien.monnaie.nom for lien in compte.monnaies))
    return (
        f"le compte {role} « {compte.nom} » ne porte pas la monnaie de cette ligne "
        f"(possibles : {possibles})"
    )


def confirmer(
    db,
    preset_id: int,
    contenu: bytes,
    overrides: schemas.ImportMappingOverrides,
    nom_fichier: str = "",
    compte_id_defaut: Optional[int] = None,
    delimiteur: Optional[str] = None,
    separateur_decimal: Optional[str] = None,
    colonnes: Optional[list] = None,
) -> schemas.ImportResultat:
    # `delimiteur` / `separateur_decimal` / `colonnes` : cf. previsualiser,
    # mêmes réglages — et TOUS LES TROIS doivent être ceux avec lesquels
    # l'aperçu confirmé a été construit, sans quoi le fichier serait relu
    # autrement à la confirmation qu'à l'aperçu (mêmes lignes en erreur qu'avant,
    # silencieusement, ou pire, des lignes importées avec des montants faux).
    # C'est ce qui permet de valider une réorganisation de colonnes SANS l'avoir
    # enregistrée : on importe exactement ce qu'on vient de relire.
    #
    # Mémorise les choix de reclassification pour les imports suivants avant
    # de relire les lignes, pour qu'elles bénéficient immédiatement des
    # mappings tout juste renseignés.
    for nom_banque, categorie_id in overrides.categories.items():
        crud.set_mapping_categorie(db, preset_id, nom_banque, categorie_id)
    for nom_banque, compte_id in overrides.comptes.items():
        crud.set_mapping_compte(db, preset_id, nom_banque, compte_id)
    for nom_banque, monnaie_id in overrides.monnaies.items():
        crud.set_mapping_monnaie(db, preset_id, nom_banque, monnaie_id)

    preset = crud.get_import_preset(db, preset_id)
    if colonnes is not None:
        preset = PresetAvecColonnes(preset, colonnes)
    lignes_existantes_brutes = crud.list_lignes_import_brutes(db, preset_id)
    colonnes_comparaison = preset.colonnes_comparaison
    mode_comparaison = preset.mode_comparaison

    contexte = ContextePreset(db, preset, separateur_decimal)
    ids_types = crud.id_type_par_code(db)

    lignes = []
    donnees_par_ligne = {}  # numéro de ligne -> données brutes complètes (pour le stockage en fin d'import)
    for brute in lire_lignes_brutes(
        contenu,
        preset.colonnes,
        preset.ignorer_premiere_ligne,
        delimiteur,
    ):
        doublon = detecter_doublon(
            brute["donnees_completes"],
            lignes_existantes_brutes,
            colonnes_comparaison,
            mode_comparaison,
        )
        ligne_resolue = _resoudre_ligne(db, contexte, brute, compte_id_defaut)
        if doublon is not None:
            ligne_resolue = ligne_resolue.model_copy(update={"doublon_de": doublon.id})
        donnees_par_ligne[brute["ligne"]] = brute["donnees_completes"]
        lignes.append(ligne_resolue)

    # Des frais qu'aucun des deux montants de la ligne ne peut porter : c'est la
    # CONFIGURATION du preset qui ne tient pas, pas une ligne isolée. Importer
    # le reste laisserait un fichier à moitié passé, dont il faudrait ensuite
    # reconstituer ce qui manque — on refuse tout, en nommant les lignes.
    # Une ligne refusée n'est pas importée : ses frais ne servent à rien, et
    # bloquer le fichier à cause d'eux ferait corriger une colonne pour une
    # opération qui n'aura jamais lieu.
    bloquantes = [
        ligne.ligne
        for ligne in lignes
        if ligne.frais_incoherents and ligne.statut_import != StatutImport.refuse.value
    ]
    if bloquantes:
        apercu = ", ".join(str(numero) for numero in bloquantes[:5])
        suite = "…" if len(bloquantes) > 5 else ""
        raise ImportBloque(
            f"Import bloqué : {len(bloquantes)} ligne(s) portent des frais dans une "
            f"monnaie qui n'est ni celle du montant ni celle du montant envoyé "
            f"(ligne {apercu}{suite}). Retire la colonne « Frais » de la "
            f"configuration avancée, ou corrige la colonne de devise qui la qualifie."
        )

    operations_creees = 0
    lignes_ignorees = []
    doublons_detectes = 0
    lignes_refusees = 0
    # (données brutes, id de l'opération créée) : le stock anti-doublons n'est
    # alimenté qu'après création réussie, pour que chaque ligne stockée pointe
    # vers une opération réelle. Une ligne supprimée à la main ou en erreur
    # n'entre donc pas au stock — elle n'a rien importé, la revoir au prochain
    # import est le comportement attendu.
    a_stocker: list[tuple[dict, int]] = []
    for ligne in lignes:
        # Un doublon n'est plus exclu d'office : il est simplement compté pour
        # l'historique, pré-sélectionné côté frontend, et importé si
        # l'utilisateur le laisse passer (un doublon détecté peut être un faux
        # positif légitime — deux achats identiques le même jour).
        if ligne.doublon_de is not None:
            doublons_detectes += 1

        # Ligne refusée par la banque : rien n'a bougé et rien ne bougera. Elle
        # ne crée aucune opération et — c'est le point important — n'entre PAS
        # au stock anti-doublons : l'y mettre la ferait disparaître d'un
        # prochain import alors qu'aucune opération ne la représente, et si la
        # banque finit par la repasser (un paiement refusé est souvent
        # réessayé), la vraie ligne serait alors prise pour un doublon.
        #
        # Placé avant tout le reste : une ligne refusée n'a pas à être complète
        # pour être écartée (compte non résolu, catégorie à confirmer… on s'en
        # moque, elle ne sera pas importée).
        if ligne.statut_import == StatutImport.refuse.value:
            lignes_refusees += 1
            continue

        if ligne.ligne in overrides.lignes_supprimees:
            continue

        # Édition manuelle directement sur la ligne (bouton "Modifier" de
        # l'aperçu) : ne remplace que les champs explicitement fournis, et
        # recalcule l'erreur à partir de l'état final (une correction peut
        # lever l'erreur d'origine, ex. date corrigée à la main).
        override = overrides.lignes.get(ligne.ligne)
        # Erreur née de la réimputation des frais (« frais supérieurs au
        # montant ») : _erreur_ligne reconstruit l'erreur à partir du seul état
        # de la ligne et ne saurait pas la retrouver, d'où ce report explicite.
        erreur_frais = None
        if override is not None:
            type_avant = ligne.type_code
            retouches = override.model_dump(exclude_none=True)
            # Un montant envoyé SAISI n'est plus déduit : l'utilisateur dit
            # lui-même ce qui est parti, et la ligne décrit dès lors ses deux
            # jambes comme le ferait un relevé qui porte la colonne.
            if "montant_envoye" in retouches:
                retouches["montant_envoye_deduit"] = False
            # UNE RETOUCHE QUI CONTREDIT LA DÉCOUPE LA DÉFAIT. Trois cas, et un
            # seul geste : choisir une catégorie à la main, c'est dire qu'on ne
            # veut plus des parts ; changer le montant rompt l'égalité « somme
            # des parts = montant », qu'aucune répartition automatique ne peut
            # rétablir sans décider à la place de l'utilisateur ; changer le
            # type peut sortir de `classique`, seul type qui se découpe.
            #
            # La ligne repasse alors « catégorie non résolue » si rien ne la
            # classe (cf. _erreur_ligne) : l'aperçu la signale et en redemande
            # une, plutôt que d'importer en silence une ligne dont le classement
            # vient de disparaître.
            if ligne.decoupes and (
                "categorie_id" in retouches
                or "montant" in retouches
                or retouches.get("type_code", ligne.type_code) != ligne.type_code
            ):
                retouches["decoupes"] = []
            ligne = ligne.model_copy(update=retouches)
            # Le montant qui fait l'opération dépend du TYPE et du SENS : les
            # changer dans l'aperçu change la jambe qui compte, donc le montant
            # importé. Une retouche qui porte des frais redéfinit en plus la
            # lecture des deux montants — ils valent alors HORS FRAIS, c'est ce
            # que le formulaire affiche dès qu'il montre les frais.
            #
            # Recalculer dans ces trois cas seulement : ailleurs, les montants
            # de la ligne sont déjà ceux qui ont bougé, et les refaire écraserait
            # une correction manuelle du montant.
            montants_a_refaire = "frais" in retouches or (
                retouches.get("type_code", type_avant) != type_avant
            )
            # Un montant envoyé SAISI compte au même titre que des frais : il
            # redéfinit la base de calcul. Sans lui, un reclassement EN virement
            # interne (qui déclenche la réimputation ci-dessous) repartait des
            # montants du FICHIER — lequel ne porte aucune colonne « Montant
            # initial », sans quoi l'utilisateur n'aurait rien eu à saisir — et
            # effaçait la jambe émettrice qu'on venait de lui demander.
            if "frais" in retouches or "montant_envoye" in retouches:
                ligne = ligne.model_copy(
                    update={
                        "montant_hors_frais": retouches.get("montant", ligne.montant_hors_frais),
                        "montant_envoye_hors_frais": retouches.get(
                            "montant_envoye", ligne.montant_envoye_hors_frais
                        ),
                    }
                )
            if montants_a_refaire:
                avant = ligne.erreur
                ligne = _reimputer_frais(ligne)
                if ligne.erreur and ligne.erreur != avant:
                    erreur_frais = ligne.erreur
        manques = _erreur_ligne(ligne)
        ligne = ligne.model_copy(
            update={"erreur": ", ".join(m for m in (manques, erreur_frais) if m) or None}
        )

        if ligne.erreur:
            lignes_ignorees.append(ligne)
            continue

        # Les deux comptes d'un virement sont connus (compte_id résolu depuis
        # le fichier + compte_id_autre complété à la main) : un vrai virement
        # double-écriture remplace la simple opération sur le seul compte
        # connu (cf. docstring du module). Sans compte_id_autre, on retombe
        # sur le comportement historique plus bas.
        if (
            TypeOperation(ligne.type_code) == TypeOperation.virement
            and ligne.compte_id_autre is not None
        ):
            compte_source_id, compte_destination_id = _resoudre_comptes_virement(ligne)
            compte_source = crud.get_compte(db, compte_source_id) if compte_source_id is not None else None
            compte_destination = (
                crud.get_compte(db, compte_destination_id) if compte_destination_id is not None else None
            )
            if compte_source is None or compte_destination is None:
                lignes_ignorees.append(ligne.model_copy(update={"erreur": "compte introuvable"}))
                continue
            monnaie_source_id, monnaie_destination_id = _monnaies_virement(
                ligne, compte_source, compte_destination
            )
            erreur_monnaie = _erreur_monnaie_compte(
                monnaie_source_id, compte_source, "émetteur"
            ) or _erreur_monnaie_compte(monnaie_destination_id, compte_destination, "récepteur")
            if erreur_monnaie:
                lignes_ignorees.append(ligne.model_copy(update={"erreur": erreur_monnaie}))
                continue
            montant_envoye, montant_recu = _montants_virement(ligne)
            memes_monnaies = monnaie_source_id == monnaie_destination_id
            # Le relevé ne décrit que la jambe de son compte. SANS CHANGE, la
            # jambe manquante se déduit de l'autre — au montant près des FRAIS,
            # qui vont à la banque et ne traversent donc pas (cf.
            # _jambe_manquante). Avec change, elle reste inconnue et c'est à
            # l'utilisateur de la dire (message plus bas pour le montant reçu,
            # ci-dessous pour l'envoyé, qui manque quand le relevé est celui du
            # compte RÉCEPTEUR).
            if memes_monnaies:
                montant_envoye, montant_recu = _jambe_manquante(
                    ligne, montant_envoye, montant_recu
                )
            if montant_envoye is None:
                if not memes_monnaies:
                    lignes_ignorees.append(
                        ligne.model_copy(
                            update={
                                "erreur": (
                                    "virement entre deux monnaies sans montant envoyé : "
                                    "renseigne le montant envoyé (l'app ne convertit rien)"
                                )
                            }
                        )
                    )
                    continue
                montant_envoye = montant_recu
            try:
                virement = schemas.VirementCreate(
                    date=ligne.date,
                    compte_source_id=compte_source.id,
                    compte_destination_id=compte_destination.id,
                    montant=montant_envoye,
                    monnaie_id=monnaie_source_id,
                    # Ce qui arrive réellement de l'autre côté. Un preset qui lit
                    # « Montant envoyé » donne les deux côtés (l'envoyé part,
                    # `montant` arrive) ; sinon c'est None, et le virement
                    # reprend le montant envoyé — ce qui n'est juste que si les
                    # deux monnaies sont identiques, d'où l'erreur ci-dessous.
                    montant_destination=montant_recu,
                    monnaie_destination_id=monnaie_destination_id,
                    # Les frais que les deux montants contiennent déjà : gardés
                    # pour que l'écran puisse redécomposer la jambe qu'ils
                    # grèvent, jamais relus par un calcul (cf.
                    # models.Operation.frais). C'est `crud._jambe_des_frais` qui
                    # décide laquelle des deux les porte.
                    frais=ligne.frais or None,
                    monnaie_frais_id=ligne.monnaie_frais_id,
                    nature=ligne.nature or None,
                    # Portée par les deux jambes, comme pour un virement saisi à
                    # la main (cf. VirementCreate.notes). L'amortissement, lui,
                    # n'a pas de sens ici : un virement ne pèse sur aucun total
                    # de période, il déplace de l'argent entre mes comptes — le
                    # formulaire ne propose donc pas la case.
                    notes=ligne.notes,
                )
            except ValidationError:
                lignes_ignorees.append(
                    ligne.model_copy(
                        update={
                            "erreur": (
                                "le compte émetteur et le compte récepteur doivent être "
                                "différents, sauf conversion entre deux monnaies d'un même compte"
                            )
                        }
                    )
                )
                continue
            if monnaie_source_id != monnaie_destination_id and montant_recu is None:
                # Reprendre le montant envoyé comme montant reçu serait un taux
                # de change inventé à 1 : l'app n'en connaît aucun, et le relevé
                # ne l'a pas dit. L'utilisateur complète le montant reçu dans
                # l'aperçu (bouton Modifier) ou configure la colonne qui le porte.
                lignes_ignorees.append(
                    ligne.model_copy(
                        update={
                            "erreur": (
                                "virement entre deux monnaies sans montant reçu : "
                                "renseigne-le (l'app ne convertit rien)"
                            )
                        }
                    )
                )
                continue
            op_sortante, _ = crud.create_virement(db, virement, compte_source, compte_destination)
            # Rattaché à la jambe sortante : supprimer le virement supprime
            # les deux opérations, donc le CASCADE libère la ligne du stock
            # quelle que soit la jambe retenue ici.
            a_stocker.append((donnees_par_ligne[ligne.ligne], op_sortante.id))
            operations_creees += 2
            continue

        # Un virement importé sans second compte connu (ligne.compte_id_autre
        # None) reste une écriture simple sur le seul compte connu, mais doit
        # quand même porter le bon sens transfert_sortant/transfert_entrant
        # (déduit du signe du montant bancaire d'origine) plutôt que le
        # "dépense" par défaut de _sens_pour_categorie pour "Virement
        # interne" : sinon un virement reçu (entrant) serait compté comme une
        # sortie dans le solde du compte, et l'opération n'apparaîtrait pas
        # dans l'onglet Virements du frontend (qui se fie à ce sens pour
        # distinguer émetteur/récepteur, cf. loadOperations côté app.js).
        sens_impose = None
        if TypeOperation(ligne.type_code) == TypeOperation.virement:
            emetteur = ligne.montant_signe is not None and ligne.montant_signe < 0
            sens_impose = Sens.transfert_sortant if emetteur else Sens.transfert_entrant
        elif (
            ligne.sens_explicite
            and TypeOperation(ligne.type_code) == TypeOperation.classique
        ):
            # Le fichier dit lui-même si l'argent entre ou sort : cela prime sur
            # la déduction par la catégorie (_sens_pour_type), qui ne connaît
            # qu'une seule catégorie d'entrée et classerait donc en dépense un
            # salaire rangé ailleurs qu'« Entrées d'argent ».
            #
            # Uniquement pour `classique` : les autres types portent leur sens
            # par nature (une dépense remboursable est une sortie, un prêt reçu
            # une entrée), et un libellé du relevé ne doit pas pouvoir les
            # inverser.
            entree = ligne.montant_signe is not None and ligne.montant_signe > 0
            sens_impose = Sens.entree if entree else Sens.depense

        # Monnaie de la ligne : celle que le fichier déclare (colonne
        # « monnaie » de la configuration avancée) si le preset la lit, sinon
        # la monnaie principale du compte visé — la seule pour un compte
        # mono-monnaie. Un compte multi-devises sans colonne de monnaie demande
        # donc toujours une reprise à la main dans l'aperçu si la ligne
        # concerne une autre de ses monnaies.
        compte_ligne = crud.get_compte(db, ligne.compte_id)
        if compte_ligne is None or compte_ligne.monnaie_principale_id is None:
            lignes_ignorees.append(ligne.model_copy(update={"erreur": "compte introuvable"}))
            continue
        # `monnaie_operation_id` et non `monnaie_id` : sur une sortie à un seul
        # compte, c'est le montant INITIAL qui fait l'opération, dans sa propre
        # monnaie (cf. _appliquer_frais).
        monnaie_ligne_id = (
            ligne.monnaie_operation_id
            or ligne.monnaie_id
            or compte_ligne.monnaie_principale_id
        )
        erreur_monnaie = _erreur_monnaie_compte(monnaie_ligne_id, compte_ligne, "de la ligne")
        if erreur_monnaie:
            lignes_ignorees.append(ligne.model_copy(update={"erreur": erreur_monnaie}))
            continue

        operation = crud.create_operation_importee(
            db,
            date_operation=ligne.date,
            compte_id=ligne.compte_id,
            type_id=ids_types[ligne.type_code],
            categorie_id=ligne.categorie_id,
            decoupes=ligne.decoupes,
            nature=ligne.nature,
            montant=ligne.montant,
            monnaie_id=monnaie_ligne_id,
            montant_du=ligne.montant_du,
            sens=sens_impose,
            statut=_statut_operation(ligne),
            notes=ligne.notes,
            amorti=ligne.amorti,
            amortissement_debut=ligne.amortissement_debut,
            amortissement_fin=ligne.amortissement_fin,
            # Déjà compris dans `montant` (ajoutés à ce qui sort, retranchés de
            # ce qui entre) : conservés pour que l'écran sache de quoi ce montant
            # est fait, et puisse le laisser corriger.
            frais=ligne.frais or None,
            monnaie_frais_id=ligne.monnaie_frais_id,
        )
        a_stocker.append((donnees_par_ligne[ligne.ligne], operation.id))
        operations_creees += 1

    historique = crud.create_import_historique(
        db,
        preset_id=preset_id,
        nom_fichier=nom_fichier,
        operations_creees=operations_creees,
        lignes_ignorees=len(lignes_ignorees),
        doublons_detectes=doublons_detectes,
    )
    # Stock centralisé de CE preset, alimenté uniquement par les lignes ayant
    # réellement créé une opération : le lien operation_id (ON DELETE CASCADE)
    # fait que supprimer l'opération retire aussi la ligne du stock, et donc
    # que le même relevé redevient réimportable.
    for donnees, operation_id in a_stocker:
        crud.create_ligne_import_brute(
            db,
            preset_id=preset_id,
            donnees=donnees,
            import_historique_id=historique.id,
            operation_id=operation_id,
        )

    return schemas.ImportResultat(
        operations_creees=operations_creees,
        lignes_ignorees=lignes_ignorees,
        doublons_detectes=doublons_detectes,
        historique_id=historique.id,
    )


def enregistrer_ligne_brute(
    db,
    preset_id: int,
    contenu: bytes,
    numero_ligne: int,
    operation_id: int,
    delimiteur: Optional[str] = None,
    import_historique_id: Optional[int] = None,
) -> bool:
    """Ajoute au stock anti-doublons UNE ligne du fichier, celle qui a créé
    `operation_id`. Renvoie False si le fichier ne porte pas ce numéro.

    POURQUOI CETTE PORTE À PART. `confirmer` alimente le stock lui-même, pour
    toutes les lignes qu'il importe — mais les RÈGLEMENTS liés n'y passent
    jamais : lier un remboursement à la dépense qu'il solde demande
    `operations_remboursees`, que seul POST /operations sait traiter, et le
    frontend les crée donc une par une hors du confirm groupé (cf.
    creerOperationReglementLiee). Ces lignes-là entraient en base sans laisser
    la moindre trace dans le stock : au relevé suivant, la même ligne de
    fichier n'était reconnue par personne et repassait comme neuve, alors que
    remboursables, prêts et virements, eux, étaient bien signalés.

    Le fichier est relu ici plutôt que d'accepter les données brutes du client :
    c'est le fichier qui fait foi pour la comparaison, et une ligne recopiée en
    chemin ne se comparerait plus à ce que `confirmer` aurait stocké.

    `import_historique_id` RATTACHE CETTE LIGNE À L'IMPORT QUI L'A AMENÉE.
    C'est ce qui la rend annulable avec lui (cf. annuler_import, qui ne
    retrouve les opérations d'un import que par ce lien) : un règlement lié
    naît bien du même fichier que le reste, à quelques secondes près, et le
    laisser à None l'aurait fait survivre seul à l'annulation de son propre
    import. Le frontend le reprend du résultat de `confirmer`
    (ImportResultat.historique_id). Reste facultatif : une ligne enregistrée
    sans lui garde exactement l'ancien comportement, stock anti-doublons
    compris.

    `delimiteur` : cf. previsualiser/confirmer — doit être celui avec lequel
    l'aperçu confirmé a été construit, sans quoi la ligne relue ne
    correspondrait plus à celle que l'utilisateur a vue et liée."""
    preset = crud.get_import_preset(db, preset_id)
    for brute in lire_lignes_brutes(
        contenu, preset.colonnes, preset.ignorer_premiere_ligne, delimiteur
    ):
        if brute["ligne"] == numero_ligne:
            crud.create_ligne_import_brute(
                db,
                preset_id=preset_id,
                donnees=brute["donnees_completes"],
                import_historique_id=import_historique_id,
                operation_id=operation_id,
            )
            return True
    return False


def annuler_import(db, historique_id: int) -> schemas.ImportAnnulationResultat:
    """Défait un import : supprime les opérations qu'il a créées, puis sa trace.

    CE QUI PART. Les opérations encore rattachées à cet import (cf.
    crud.get_operations_d_un_import), les deux jambes de chaque virement, les
    liens de remboursement qui les désignent, et leurs lignes du stock
    anti-doublons — ce dernier point étant l'essentiel : sans lui, le relevé
    resterait « déjà importé » alors qu'il n'en resterait plus rien en base, et
    le réimporter le verrait comme un doublon de lignes disparues.

    Chaque suppression passe par crud.delete_operation plutôt que par un
    DELETE en masse : c'est lui qui sait déjà défaire tout ce qu'une opération
    traîne derrière elle (liens de remboursement dans les deux sens, versant
    titres d'un achat/vente, et surtout le RECALCUL du reste à rembourser des
    dépenses que l'opération soldait). Refaire cette liste ici l'aurait
    condamnée à diverger au premier ajout.

    CE QUI RESTE. Une opération déjà supprimée à la main n'est plus comptée :
    le CASCADE avait emporté sa ligne de stock avec elle, elle ne figure donc
    plus nulle part. Et une opération MODIFIÉE depuis l'import part quand même
    — elle vient bien de ce fichier, et la garder laisserait dans les comptes
    une écriture que plus rien ne rattacherait à quoi que ce soit. C'est ce que
    l'avertissement du frontend annonce avant de lancer l'annulation.

    RIEN N'EST RÉIMPORTÉ AUTOMATIQUEMENT : annuler rend le fichier
    réimportable, ce que l'utilisateur fait (ou non) ensuite, avec la
    configuration qu'il veut. C'est tout l'intérêt d'annuler plutôt que de
    corriger ligne à ligne — un preset mal configuré se répare une fois, puis
    se rejoue."""
    entree = crud.get_import_historique_entree(db, historique_id)
    if entree is None:
        return schemas.ImportAnnulationResultat(
            operations_supprimees=0, historique_supprime=False
        )

    operations = crud.get_operations_d_un_import(db, historique_id)
    for operation in operations:
        crud.delete_operation(db, operation)

    crud.delete_import_historique(db, entree)
    return schemas.ImportAnnulationResultat(
        operations_supprimees=len(operations), historique_supprime=True
    )
