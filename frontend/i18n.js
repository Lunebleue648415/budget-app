/**
 * Traduction de l'interface. Deux langues : le français, langue SOURCE, et
 * l'anglais.
 *
 * POURQUOI LE FRANÇAIS SERT DE CLÉ. Un dictionnaire de clés abstraites
 * (« dashboard.kpi.solde ») aurait voulu dire toucher chaque libellé de
 * index.html et de app.js pour y poser une clé, puis maintenir deux fichiers en
 * regard sans jamais voir le texte réel en écrivant le code. Ici la clé EST la
 * phrase française : le code reste lisible tel quel, et une phrase sans
 * traduction s'affiche simplement en français plutôt que de casser l'écran.
 *
 * DEUX CHEMINS, ET UN SEUL DICTIONNAIRE :
 *
 *  - le texte STATIQUE de index.html est traduit une fois, au chargement, en
 *    parcourant le DOM (cf. traduireDomStatique). Aucun attribut à poser dans
 *    le HTML ;
 *  - le texte CONSTRUIT en JavaScript passe par `t("...")`, qui accepte des
 *    paramètres nommés pour les phrases qui portent un nombre ou un nom.
 *
 * CE QUI N'EST JAMAIS TRADUIT : les données. Noms de comptes, de catégories, de
 * monnaies, libellés d'opérations, natures lues dans un relevé — c'est le texte
 * de l'utilisateur, pas celui de l'application. C'est la raison pour laquelle le
 * parcours du DOM n'a lieu qu'AU CHARGEMENT, avant que la moindre donnée n'ait
 * été rendue : à ce moment-là, tout ce qui est à l'écran vient de index.html.
 * Changer de langue recharge donc la page (cf. changerLangue) plutôt que de
 * retraduire un DOM où les deux se mélangent.
 */

const LANGUES = ["fr", "en"];
const LANGUE_PAR_DEFAUT = "fr";
const CLE_STOCKAGE = "budget-app-langue";

function langueEnregistree() {
  try {
    const valeur = localStorage.getItem(CLE_STOCKAGE);
    return LANGUES.includes(valeur) ? valeur : LANGUE_PAR_DEFAUT;
  } catch (err) {
    // Stockage indisponible (navigation privée stricte) : le français, et rien
    // de cassé.
    return LANGUE_PAR_DEFAUT;
  }
}

let langueActuelle = langueEnregistree();

function langue() {
  return langueActuelle;
}

/**
 * Traduit une phrase, et remplace ses paramètres.
 *
 * Les paramètres s'écrivent `{nom}` dans les deux langues : c'est ce qui permet
 * à l'anglais de les remettre dans un autre ordre, ce qu'une simple
 * concaténation aurait interdit.
 *
 * Une phrase absente du dictionnaire ressort telle quelle : en français c'est
 * le comportement voulu, en anglais c'est un trou visible — préférable à un
 * écran vide ou à une clé technique affichée à l'utilisateur.
 */
function t(texte, params) {
  const table = TRADUCTIONS[langueActuelle];
  let resultat = (table && table[texte]) || texte;
  if (params) {
    Object.keys(params).forEach((cle) => {
      resultat = resultat.split(`{${cle}}`).join(params[cle]);
    });
  }
  return resultat;
}

/**
 * Traduit un texte VENU DU SERVEUR (message d'erreur d'un endpoint, libellé
 * d'erreur d'une ligne d'import).
 *
 * Le serveur ne parle que français : ses messages sont donc traduits ici, à
 * l'affichage. Deux passes, parce que beaucoup de ces messages portent un nom
 * de compte ou un nombre et ne peuvent pas être retrouvés à l'identique :
 *
 *  1. correspondance exacte dans le dictionnaire ordinaire ;
 *  2. à défaut, les motifs de MOTIFS_SERVEUR, qui capturent la partie variable
 *     et la réinjectent telle quelle — un nom de compte n'est pas à traduire.
 *
 * Un message inconnu ressort en français : mieux vaut une phrase juste dans la
 * mauvaise langue qu'une erreur avalée.
 */
function traduireMessageServeur(message) {
  if (langueActuelle === LANGUE_PAR_DEFAUT || !message) return message;
  const direct = TRADUCTIONS[langueActuelle][message];
  if (direct) return direct;
  // Plusieurs manques peuvent être concaténés par le serveur (cf.
  // _erreur_ligne, qui joint par ", ") : on traduit morceau par morceau.
  if (message.includes(", ")) {
    const morceaux = message.split(", ");
    const traduits = morceaux.map((m) => traduireFragmentServeur(m));
    if (traduits.some((m, i) => m !== morceaux[i])) return traduits.join(", ");
  }
  return traduireFragmentServeur(message);
}

function traduireFragmentServeur(fragment) {
  const table = TRADUCTIONS[langueActuelle];
  if (table[fragment]) return table[fragment];
  for (const [motif, remplacement] of MOTIFS_SERVEUR) {
    const trouve = fragment.match(motif);
    if (trouve) {
      return remplacement.replace(/\$(\d)/g, (_, n) => trouve[Number(n)] ?? "");
    }
  }
  return fragment;
}

// Les attributs porteurs de texte visible. `data-info` alimente les info-bulles
// de l'app (cf. .info-bulle), `value` ne concerne que les boutons de formulaire.
const ATTRIBUTS_TRADUISIBLES = ["placeholder", "title", "aria-label", "data-info"];

/**
 * Traduit tout le texte statique de la page, une seule fois, au chargement.
 *
 * Sûr parce qu'appelé AVANT tout rendu de données : ce qui est dans le DOM à cet
 * instant vient intégralement de index.html. Un nom de catégorie qui
 * ressemblerait à un libellé de l'interface ne peut donc pas être traduit par
 * mégarde — il n'est pas encore là.
 */
function traduireDomStatique(racine) {
  if (langueActuelle === LANGUE_PAR_DEFAUT) return;
  const table = TRADUCTIONS[langueActuelle];

  const parcours = document.createTreeWalker(racine, NodeFilter.SHOW_TEXT, {
    acceptNode(noeud) {
      if (!noeud.nodeValue || !noeud.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
      const parent = noeud.parentElement;
      if (!parent || parent.tagName === "SCRIPT" || parent.tagName === "STYLE") {
        return NodeFilter.FILTER_REJECT;
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const noeuds = [];
  for (let n = parcours.nextNode(); n; n = parcours.nextNode()) noeuds.push(n);
  noeuds.forEach((noeud) => {
    // Les espaces et retours à la ligne de l'indentation HTML ne font pas
    // partie de la phrase : on les met de côté et on les remet après, pour ne
    // pas avoir à répéter dans le dictionnaire la mise en forme du fichier.
    const brut = noeud.nodeValue;
    const avant = brut.match(/^\s*/)[0];
    const apres = brut.match(/\s*$/)[0];
    const phrase = brut.trim().replace(/\s+/g, " ");
    const traduction = table[phrase];
    if (!traduction) return;
    // …SAUF quand la traduction porte elle-même son espace. Certaines phrases
    // de l'aide sont coupées en morceaux par un <strong> ou un <em> au milieu,
    // et les deux langues n'attachent pas les mots de la même façon : le
    // français élide (« ils s'<em>ajoutent</em> »), l'anglais sépare (« they
    // are <em>added</em> »). La traduction décide donc de ses propres bords, et
    // l'indentation d'origine ne revient que là où elle n'en pose pas.
    const debut = /^\s/.test(traduction) ? "" : avant;
    const fin = /\s$/.test(traduction) ? "" : apres;
    noeud.nodeValue = `${debut}${traduction}${fin}`;
  });

  racine.querySelectorAll("*").forEach((el) => {
    ATTRIBUTS_TRADUISIBLES.forEach((attribut) => {
      const valeur = el.getAttribute(attribut);
      if (!valeur) return;
      const traduction = table[valeur.trim().replace(/\s+/g, " ")];
      if (traduction) el.setAttribute(attribut, traduction);
    });
  });

  document.documentElement.lang = langueActuelle;
}

/**
 * Change de langue et RECHARGE la page.
 *
 * Retraduire à chaud demanderait de distinguer, dans un DOM déjà rempli, ce qui
 * vient de l'application de ce qui vient de la base — exactement la confusion
 * que ce module évite en ne traduisant qu'au chargement. Un rechargement est
 * instantané (tout est local) et repart d'un écran propre.
 */
function changerLangue(nouvelle) {
  if (!LANGUES.includes(nouvelle) || nouvelle === langueActuelle) return;
  try {
    localStorage.setItem(CLE_STOCKAGE, nouvelle);
  } catch (err) {
    /* Sans stockage, la langue ne survivra pas au rechargement : tant pis, on
       ne bloque pas le changement pour autant. */
  }
  window.location.reload();
}

/**
 * FRANÇAIS → ANGLAIS.
 *
 * Une entrée par phrase de l'interface, groupées par écran dans l'ordre où on
 * les rencontre. Les phrases que le HTML coupe par un <strong> ou un <em>
 * figurent morceau par morceau, avec leurs espaces de jonction quand l'anglais
 * les attache autrement que le français.
 *
 * Ne contient AUCUN nom de compte, de catégorie, de monnaie ni de type
 * d'opération : ce sont des données saisies par l'utilisateur, et les traduire
 * les rendrait introuvables dans sa propre base.
 */
const TRADUCTIONS = {
  en: {
    // ---------- En-tête ----------
    "Rechercher dans la page (Ctrl+F)": "Search this page (Ctrl+F)",
    Rechercher: "Search",
    "Rechercher dans la page\u2026": "Search this page\u2026",
    "Rechercher dans la page": "Search this page",
    "Correspondance pr\u00e9c\u00e9dente (Maj+Entr\u00e9e)": "Previous match (Shift+Enter)",
    "Correspondance pr\u00e9c\u00e9dente": "Previous match",
    "Correspondance suivante (Entr\u00e9e)": "Next match (Enter)",
    "Correspondance suivante": "Next match",
    "Op\u00e9rations": "Transactions",
    "Placements financiers": "Investments",
    "Param\u00e8tres": "Settings",

    // ---------- Dashboard ----------
    "Solde total": "Total balance",
    "Comptes courants, op\u00e9rations r\u00e9elles": "Current accounts, settled transactions",
    "Solde projet\u00e9": "Projected balance",
    "Comptes courants, pr\u00e9visionnel inclus": "Current accounts, forecast included",
    // Carte \u00ab Solde total \u00bb, qui porte d\u00e9sormais le projet\u00e9 \u00e0 c\u00f4t\u00e9 du r\u00e9el.
    "projet\u00e9": "projected",
    "Comptes courants \u2014 r\u00e9el, puis pr\u00e9visionnel inclus":
      "Current accounts \u2014 settled, then forecast included",
    "Comptes": "Accounts",
    "Variation du mois": "Change this month",
    // Le titre suit la vue : en vue annuelle, \u00ab du mois \u00bb annoncerait le
    // mauvais ordre de grandeur (cf. renderKpisDashboard).
    "Variation de l'ann\u00e9e": "Change this year",
    "Entr\u00e9es \u2212 sorties (pr\u00e9visionnel inclus)": "Money in \u2212 money out (forecast included)",
    "Total des avoirs": "Total assets",
    "Tous comptes confondus, courant + \u00e9pargne": "All accounts, current + savings",
    "R\u00e9partition des avoirs": "Asset allocation",
    "La part du total des avoirs pos\u00e9e sur chaque type de compte, dans la monnaie choisie. Solde R\u00c9EL, titres d\u00e9tenus compris \u2014 pas le pr\u00e9visionnel.":
      "The share of total holdings sitting on each account type, in the chosen currency. REAL balance, securities held included \u2014 not the projected one.",
    "Aucun solde positif \u00e0 r\u00e9partir.": "No positive balance to break down.",
    "R\u00e9partition des avoirs par type de compte": "Asset breakdown by account type",
    "Comptes courants": "Current accounts",
    "Comptes d'\u00e9pargne": "Savings accounts",
    "Comptes de placements": "Investment accounts",
    "Le solde affich\u00e9 est celui des esp\u00e8ces disponibles sur le compte ; les titres d\u00e9tenus sont valoris\u00e9s dans \u00ab Total des avoirs \u00bb et d\u00e9taill\u00e9s dans la page Placements financiers.":
      "The balance shown is the cash available on the account; the securities you hold are valued under \u201cTotal assets\u201d and detailed on the Investments page.",

    // ---------- Vue globale des comptes ----------
    "Vue globale des comptes": "Global account overview",
    "Le solde affich\u00e9 repr\u00e9sente les esp\u00e8ces disponibles. La valeur de tes titres se lit dans Placements financiers.":
      "The balance shown is the available cash. What your holdings are worth is on the Investments page.",
    "D\u00e9penses par cat\u00e9gorie \u2014": "Spending by category \u2014",
    "Total entr\u00e9es": "Money in",
    "Total sorties": "Money out",
    "Diff\u00e9rence": "Difference",
    "Notes": "Notes",
    "Un pense-b\u00eate, non lu par l'app. \u00c7a s'enregistre tout seul.":
      "A scratchpad, never read by the app. It saves itself.",
    "ex. v\u00e9rifier que le pr\u00e9l\u00e8vement EDF de mars est bien pass\u00e9 relancer Marie pour les 40 \u20ac du restaurant":
      "e.g. check the March electricity direct debit went through chase Marie for the \u20ac40 from dinner",

    // ---------- Op\u00e9rations ----------
    "Supprimer toutes les op\u00e9rations": "Delete all transactions",
    "Op\u00e9rations classiques": "Standard transactions",
    "D\u00e9penses remboursables": "Reimbursable expenses",
    "Remboursements re\u00e7us": "Reimbursements received",
    "Virements internes": "Internal transfers",
    "Pr\u00eats re\u00e7us": "Loans received",
    "Remboursements de pr\u00eats": "Loan repayments",
    "Trier par": "Sort by",
    "+ Ajouter une op\u00e9ration": "+ Add a transaction",
    "Ponctuelles": "One-off",
    "R\u00e9currentes": "Recurring",
    "Compte": "Account",
    "Tous": "All",
    "Cat\u00e9gorie": "Category",
    "Toutes": "All",
    "Statut": "Status",
    "Du": "From",
    "Au": "To",
    "Filtrer": "Filter",
    "R\u00e9initialiser": "Reset",
    "Ajouter une op\u00e9ration": "Add a transaction",
    "Nature": "Description",
    "Montant": "Amount",
    "Monnaie": "Currency",
    "Montant re\u00e7u": "Amount received",
    "Monnaie re\u00e7ue": "Currency received",
    "Date": "Date",
    "Compte source": "Source account",
    "Compte destination": "Destination account",
    "R\u00e9currente": "Recurring",
    "G\u00e9n\u00e9r\u00e9e automatiquement par une op\u00e9ration r\u00e9currente : modifie ou arr\u00eate la r\u00e9currence depuis l'op\u00e9ration d'origine.":
      "Generated automatically by a recurring transaction: edit or stop the recurrence from the original transaction.",
    "Fr\u00e9quence": "Frequency",
    "Hebdomadaire": "Weekly",
    "Mensuelle": "Monthly",
    "Trimestrielle": "Quarterly",
    "Annuelle": "Yearly",
    "Sans date de fin": "No end date",
    "Date de fin": "End date",
    "Colonnes lues": "Columns read",
    "{n} colonne(s) lue(s)": "{n} column(s) read",
    "doublons : toutes les colonnes": "duplicates: every column",
    "doublons : toutes sauf {n}": "duplicates: all but {n}",
    "doublons : {n} colonne(s) comparée(s)": "duplicates: {n} column(s) compared",
    "Amortie sur plusieurs mois": "Spread over several months",
    // Découpe d'une opération entre plusieurs catégories.
    "Découper entre plusieurs catégories": "Split across several categories",
    // Les six opérateurs numériques d'une condition de règle (le champ
    // « Montant »). Les quatre opérateurs de texte sont déjà plus haut.
    "égal à": "equal to",
    "différent de": "different from",
    "supérieur à": "greater than",
    "supérieur ou égal à": "greater than or equal to",
    "inférieur à": "less than",
    "inférieur ou égal à": "less than or equal to",
    // La découpe posée par une règle.
    "découpée": "split",
    "La découpe ci-dessous tient lieu de catégorie.":
      "The split below stands in for the category.",
    "Une seule part peut valoir « reste ».": "Only one part can be \u00ab reste \u00bb.",
    "La règle répartit le montant de la ligne entre plusieurs catégories, au lieu d'en poser une seule. Réservé aux opérations classiques.":
      "The rule spreads the amount of the line across several categories instead of setting a single one. Plain operations only.",
    "+ Ajouter une part": "+ Add a part",
    "Chaque part dit combien elle prend. On peut écrire un nombre (50), un pourcentage (30%), une opération (montant - 50), ou utiliser min et max — par exemple min(montant; 50) pour « au plus 50 € ». Le mot reste donne à une part tout ce que les autres n'ont pas pris ; une seule part peut le porter, et la somme doit valoir le montant de la ligne.":
      "Each part says how much it takes. Write a number (50), a percentage (30%), an expression (montant - 50), or use min and max \u2014 for instance min(montant; 50) for \u00ab at most 50 \u20ac \u00bb. The word reste gives a part whatever the others did not take; only one part can carry it, and the total must match the amount of the line.",
    "Une seule opération, plusieurs catégories : un plein de courses dont une part de produits ménagers. Le total des parts doit valoir le montant de l'opération.":
      "One operation, several categories: a grocery run with a share of household products. The parts must add up to the amount of the operation.",
    "Ajouter une part": "Add a part",
    "Retirer cette part": "Remove this part",
    "Réparti": "Allocated",
    "reste à placer": "left to allocate",
    "Une découpe compte au moins deux parts remplies.":
      "A split needs at least two filled parts.",
    "Une même catégorie ne peut pas apparaître deux fois dans la découpe.":
      "The same category cannot appear twice in a split.",
    "Le total des parts doit valoir le montant de l'opération.":
      "The parts must add up to the amount of the operation.",
    "Découpée": "Split",
    "parts": "parts",
    "Voir le détail de la découpe": "Show the split details",
    "La dépense reste datée du jour où l'argent est sorti — les soldes et les KPI du haut du dashboard ne bougent pas. Seuls l'histogramme et les totaux de la période répartissent son montant sur les mois choisis.":
      "The expense keeps the date the money actually left — balances and the KPIs at the top of the dashboard do not move. Only the chart and the period totals spread its amount over the chosen months.",
    "Premier mois": "First month",
    "Dernier mois": "Last month",
    "Nombre de mois": "Number of months",
    // Les deux listes déroulantes d'un champ mois + année (cf. creerChampMoisAnnee).
    "Mois": "Month",
    "Année": "Year",
    "ex. facture partagée avec Léa": "e.g. invoice split with Lea",
    "Renseigne deux des trois cases d'amortissement (premier mois, dernier mois, nombre de mois).":
      "Fill in two of the three spreading fields (first month, last month, number of months).",
    "Montant \u00e0 rembourser": "Amount owed to you",
    "Reste \u00e0 rembourser": "Still outstanding",
    "Op\u00e9rations rembours\u00e9es": "Expenses settled",
    "Un commentaire non lu par l'app. Sur un virement, il vaut pour les deux comptes.":
      "A comment never read by the app. On a transfer, it applies to both accounts.",
    "ex. facture partag\u00e9e avec L\u00e9a, \u00e0 rev\u00e9rifier sur le relev\u00e9 de mars":
      "e.g. bill split with L\u00e9a, double-check on the March statement",
    "Enregistrer": "Save",
    "Annuler": "Cancel",

    // ---------- Placements financiers ----------
    "Aucun compte de placements financiers. Cr\u00e9e-en un depuis la page Comptes en choisissant le type \"Placements financiers\", puis alimente-le par un virement interne.":
      "No investment account yet. Create one from the Accounts page by choosing the \"Placements financiers\" type, then fund it with an internal transfer.",
    "Titres d\u00e9tenus": "Holdings",
    "Titre": "Security",
    "Quantit\u00e9": "Quantity",
    "Prix de revient": "Cost price",
    "Investi": "Invested",
    "Cours": "Price",
    "Valorisation": "Market value",
    "+/- value": "Gain / loss",
    "Acheter / vendre": "Buy / sell",
    "Achat": "Buy",
    "Vente": "Sell",
    "Prix unitaire": "Unit price",
    "Mouvements sur titres": "Security movements",
    "Sens": "Direction",
    "Actions": "Actions",
    "Titres suivis": "Tracked securities",
    "Tes titres, communs \u00e0 tous tes comptes : le m\u00eame ETF peut \u00eatre d\u00e9tenu sur deux comptes. Le cours se saisit \u00e0 la main, ou se relit en ligne avec l'extension Lecture de cours. Il ne sert qu'\u00e0 la valorisation, jamais \u00e0 un solde.":
      "Your holdings, shared across every account: the same ETF can be held on two of them. The price is entered by hand, or read online with the Price lookup extension. It only feeds valuation, never a balance.",
    "Nom du titre": "Security name",
    "ex. Air Liquide": "e.g. Air Liquide",
    "Monnaie de cotation": "Quote currency",
    "Cours actuel": "Current price",
    "Ajouter le titre": "Add security",
    // ----- Archiver un titre : rangé, jamais effacé -----
    "Afficher les titres archiv\u00e9s": "Show archived securities",
    "Archiver, c'est ranger, pas effacer : le titre quitte les listes, son historique reste. C'est ici qu'on le remet en service.":
      "Archiving files away, it does not erase: the holding leaves the lists, its history stays. This is where you bring it back.",
    "Archiver": "Archive",
    "Remettre en service": "Bring back",
    "archiv\u00e9": "archived",
    "Ranger ce titre : il quitte les listes, son historique reste":
      "File this security away: it leaves the lists, its history stays",
    "Remettre ce titre dans les listes": "Put this security back in the lists",
    "Titre archiv\u00e9. Ses mouvements et ses plus-values sont intacts.":
      "Security archived. Its movements and capital gains are intact.",
    "Titre remis en service.": "Security brought back.",

    // ---------- Extension \u00ab Lecture de cours \u00bb ----------
    // Deux greffes : l'\u00e9cran Placements (un lien de cotation par titre) et
    // l'\u00e9cran Monnaies (un taux par couple). Cf. extensions/lecture-de-cours.

    "Mettre \u00e0 jour les cours": "Update prices",
    "Pages reconnues": "Supported pages",
    "mis \u00e0 jour {quand}": "updated {quand}",
    // ----- Volet titres : le lien de cotation déplié sous chaque titre -----
    // Le formulaire « Suivre un cours en ligne » a été retiré : la flèche de
    // chaque rangée déplie le champ de lien du titre qu'on regarde déjà.
    "Lien de la page de cotation": "Quote page link",
    // ----- Volet monnaies : les taux de change -----
    "Taux de change": "Exchange rates",
    "Le taux d'un couple de monnaies, relu sur la page de cotation dont tu colles le lien. Rien n'est converti avec : les soldes, les budgets et les KPI restent suivis monnaie par monnaie, et ce taux ne sert qu'\u00e0 \u00eatre lu ici.":
      "The rate of a currency pair, read again from the quote page whose link you paste. Nothing is converted with it: balances, budgets and KPIs stay tracked currency by currency, and this rate is only there to be read.",
    "Mettre \u00e0 jour les taux": "Update rates",
    "Monnaie de d\u00e9part": "From currency",
    "Monnaie d'arriv\u00e9e": "To currency",
    "Suivre ce couple": "Track this pair",
    "Aucun couple suivi pour le moment.": "No pair tracked yet.",
    "la page": "the page",
    "Ne plus suivre": "Stop tracking",
    "jamais relu": "never read",
    "{n} couple(s) suivi(s)": "{n} pair(s) tracked",
    "jamais mis \u00e0 jour": "never updated",
    "{n} taux mis \u00e0 jour": "{n} rates updated",
    "Colle le lien de la page de cotation.": "Paste the link to the quote page.",
    "Taux lu sur {source} : {libelle} = {taux}": "Rate read on {source}: {libelle} = {taux}",
    "Couple enregistr\u00e9": "Pair saved",
    "Couple retir\u00e9. Aucun montant n'en d\u00e9pendait.":
      "Pair removed. No amount depended on it.",
    "Lecture en cours\u2026": "Reading\u2026",
    "Mettre \u00e0 jour": "Update",
    "D\u00e9tacher": "Detach",
    "Relire le cours maintenant": "Read this price now",
    "Ne plus suivre ce cours en ligne": "Stop tracking this price online",
    "Lien de la page de cotation (Google Finance, Yahoo Finance\u2026)":
      "Link to the quote page (Google Finance, Yahoo Finance\u2026)",
    "cours saisi \u00e0 la main": "price entered by hand",
    "\u00e0 l'instant": "just now",
    "il y a {n} min": "{n} min ago",
    "il y a {n} h": "{n} h ago",
    "jamais lus": "never read",
    "derni\u00e8re lecture {quand}": "last read {quand}",
    "{n} titre(s) suivi(s) en ligne": "{n} security(ies) tracked online",
    "{n} en \u00e9chec": "{n} failed",
    "{n} cours mis \u00e0 jour": "{n} prices updated",
    "Aucun titre n'a de lien \u00e0 relire": "No security has a link to read",
    "Aucun titre n'a de lien : ajoute-en un dans \u00ab Titres suivis \u00bb, en bas de page.":
      "No security has a link yet: add one under \u201cTracked securities\u201d, at the bottom of the page.",
    "Cours lu sur {source} : {nom} \u2014 {cours}": "Price read on {source}: {nom} \u2014 {cours}",
    "Lien enregistr\u00e9": "Link saved",
    "Lien retir\u00e9 \u2014 le cours redevient saisi \u00e0 la main":
      "Link removed \u2014 the price goes back to being entered by hand",
    "{n} cours n'ont pas pu \u00eatre relus au lancement (voir Placements)":
      "{n} prices could not be read at startup (see Investments)",
    "Tes titres, communs \u00e0 tous tes comptes. Colle le lien d'une page de cotation \u00e0 c\u00f4t\u00e9 d'un titre et son cours se relira tout seul : c'est la seule chose que l'app va chercher sur Internet, et seulement pour les titres qui ont un lien. Le cours dit ce que \u00e7a vaut aujourd'hui, jamais comment un solde est calcul\u00e9.":
      "Your securities, shared across all your accounts. Paste the link of a quotation page next to a security and its price will refresh on its own: that is the only thing the app fetches from the Internet, and only for securities that have a link. The price says what things are worth today, never how a balance is computed.",

    // ---------- Param\u00e8tres : onglets ----------
    "Comptes": "Accounts",
    "Cat\u00e9gories": "Categories",
    "Monnaies": "Currencies",
    "R\u00e8gles": "Rules",
    "Import": "Import",
    "Base de donn\u00e9es": "Database",

    // ---------- Modale d'annonce des extensions trouv\u00e9es au lancement ----------
    "Extensions d\u00e9tect\u00e9es": "Extensions detected",
    "Une extension a \u00e9t\u00e9 trouv\u00e9e dans le dossier \u00ab extensions \u00bb. Elle ne fonctionnera qu'une fois activ\u00e9e ci-dessous \u2014 fermer cette fen\u00eatre ne l'active pas.":
      "One extension was found in the \u201cextensions\u201d folder. It will not run until you set it to Enabled below \u2014 closing this window does not enable it.",
    "{n} extensions ont \u00e9t\u00e9 trouv\u00e9es dans le dossier \u00ab extensions \u00bb. Elles ne fonctionneront qu'une fois activ\u00e9es ci-dessous \u2014 fermer cette fen\u00eatre n'en active aucune.":
      "{n} extensions were found in the \u201cextensions\u201d folder. They will not run until you set them to Enabled below \u2014 closing this window enables none of them.",
    "Fermer": "Close",
    "Aller au menu extensions": "Go to the extensions menu",

    // ---------- Param\u00e8tres : extensions ----------
    "Extensions": "Extensions",
    "N\u00e9cessite au moins une de ces extensions, install\u00e9e et activ\u00e9e :":
      "Needs at least one of these extensions, installed and enabled:",
    "Une extension ajoute une fonctionnalit\u00e9. La d\u00e9sactiver fait dispara\u00eetre son \u00e9cran sans rien effacer \u2014 tout revient si tu la rallumes.":
      "An extension adds a feature. Turning it off makes its screen disappear without erasing anything \u2014 it all comes back if you turn it on again.",
    "Aucune extension install\u00e9e.": "No extensions installed.",
    "Activ\u00e9e": "Enabled",
    "D\u00e9sactiv\u00e9e": "Disabled",
    "\u00c9tat de l'extension": "Extension state",
    "Afficher ce que fait cette extension": "Show what this extension does",
    "Afficher l'avertissement": "Show the warning",
    "Afficher l'explication": "Show the explanation",
    "Ajouter une monnaie": "Add a currency",
    "d\u00e9veloppeur": "developer",
    "Extension activ\u00e9e.": "Extension enabled.",
    "Extension d\u00e9sactiv\u00e9e. Aucune donn\u00e9e n'a \u00e9t\u00e9 supprim\u00e9e.":
      "Extension disabled. No data was deleted.",
    "Extension non charg\u00e9e": "Extension failed to load",

    // ---------- Param\u00e8tres : comptes ----------
    "Double-clique une ligne pour modifier un compte, fais-la glisser d'une carte \u00e0 l'autre pour changer son type.":
      "Double-click a row to edit an account, drag it from one card to another to change its type.",
    "Ajouter un compte": "Add an account",
    "Nom": "Name",
    "Type": "Type",
    "Monnaies du compte": "Account currencies",
    "Chaque monnaie du compte garde son propre solde, jamais m\u00e9lang\u00e9 aux autres \u2014 d'o\u00f9 un solde initial par monnaie.":
      "Each of the account's currencies keeps its own balance, never mixed with the others \u2014 hence one opening balance per currency.",
    "Types de comptes": "Account types",
    "Les trois types livr\u00e9s avec l'application sont prot\u00e9g\u00e9s : ils pilotent le dashboard et les r\u00e8gles de virement. Un compte passe de l'un \u00e0 l'autre en le faisant glisser d'une carte \u00e0 l'autre, plus haut sur cette page.":
      "The three types shipped with the application are protected: they drive the dashboard and the transfer rules. An account moves from one to another by dragging it from one card to another, higher up on this page.",
    "Ajouter": "Add",

    // ---------- Param\u00e8tres : cat\u00e9gories ----------
    "Cat\u00e9gories de d\u00e9penses": "Spending categories",
    "Un budget vaut pour un mois et une monnaie, choisis par les onglets ci-dessous ; un mois non rempli reprend le dernier renseign\u00e9. L'\u0153il de la colonne Dashboard ne fait qu'afficher ou masquer la cat\u00e9gorie dans l'histogramme.":
      "A budget applies to one month and one currency, picked by the tabs below; a month you leave empty inherits the last one filled in. The eye in the Dashboard column only shows or hides the category in the chart.",
    "Ordre": "Order",
    "Budget": "Budget",
    "Ajouter une cat\u00e9gorie": "Add a category",

    // ---------- Param\u00e8tres : monnaies ----------
    "Chaque monnaie garde ses propres soldes et budgets, jamais m\u00e9lang\u00e9s aux autres. Le symbole est ce qui s'affiche \u00e0 c\u00f4t\u00e9 des montants.":
      "Each currency keeps its own balances and budgets, never mixed with the others. The symbol is what shows next to amounts.",
    "ex. Dollar am\u00e9ricain": "e.g. US Dollar",
    "Symbole": "Symbol",
    "ex. $": "e.g. $",

    // ---------- Param\u00e8tres : base de donn\u00e9es ----------
    "Bascule toutes les op\u00e9rations de l'app (lecture et \u00e9criture) vers un autre fichier .db. Ce choix n'est jamais m\u00e9moris\u00e9 au-del\u00e0 de cette session : red\u00e9marrer le serveur revient toujours \u00e0 la base de test.":
      "Switches everything the app reads and writes to another .db file. This choice is never remembered beyond the current session: restarting the server always returns to the test database.",
    "Une base rest\u00e9e \u00e0 une version de sch\u00e9ma ant\u00e9rieure est mise \u00e0 jour \u00e0 la bascule, apr\u00e8s copie horodat\u00e9e \u00e0 c\u00f4t\u00e9 du fichier d'origine : une application neuve ne sait pas lire une base ancienne, et \u00e9chouerait sinon sur ses pages principales sans dire pourquoi.":
      "A database left on an older schema version is upgraded when you switch to it, after a timestamped copy is made next to the original file: a newer app cannot read an older database, and would otherwise fail on its main pages without saying why.",
    "Base actuelle": "Current database",
    "Chemin complet du fichier .db": "Full path to the .db file",
    "C:\\chemin\\vers\\ma_base.db": "C:\\path\\to\\my_database.db",
    "Le navigateur ne transmet jamais le chemin complet d'un fichier choisi via \"Parcourir\" (limite de s\u00e9curit\u00e9) : ce bouton pr\u00e9-remplit seulement le nom du fichier, compl\u00e8te le dossier \u00e0 la main.":
      "The browser never passes on the full path of a file chosen through \"Browse\" (a security limit): this button only pre-fills the file name, complete the folder by hand.",
    "Parcourir\u2026": "Browse\u2026",
    "Basculer sur ce fichier": "Switch to this file",
    "Revenir \u00e0 la base de test": "Back to the test database",

    // ---------- Param\u00e8tres : r\u00e8gles ----------
    "Une r\u00e8gle classe automatiquement les lignes import\u00e9es d'apr\u00e8s leurs libell\u00e9s \u2014 c'est le seul moyen de marquer une ligne \"remboursable\" ou de la classer en Pr\u00eat / Remboursement sans le faire \u00e0 la main. Les r\u00e8gles sont communes \u00e0 tous les presets d'import.":
      "A rule classifies imported rows automatically from their descriptions \u2014 it is the only way to mark a row as reimbursable, or to file it as a loan or a repayment, without doing it by hand. Rules are shared by every import preset.",
    "Elles sont \u00e9valu\u00e9es": "They are evaluated",
    "de haut en bas": "top to bottom",
    ", et s'arr\u00eatent \u00e0 la premi\u00e8re qui correspond \u2014 sauf si celle-ci d\u00e9coche \u00ab Arr\u00eater la lecture des r\u00e8gles ici \u00bb. Plusieurs r\u00e8gles peuvent alors s'appliquer \u00e0 une m\u00eame ligne, mais aucune ne d\u00e9fait ce qu'une r\u00e8gle plus haute a d\u00e9cid\u00e9 :":
      ", stopping at the first one that matches \u2014 unless it unticks \u201cStop reading rules here\u201d. Several rules can then apply to the same row, but none undoes what a higher rule decided:",
    "en cas de d\u00e9saccord, la plus haute gagne": "when they disagree, the highest one wins",
    ". Place les cas particuliers au-dessus des cas g\u00e9n\u00e9raux.":
      ". Put the special cases above the general ones.",
    "Les r\u00e8gles passent": "Rules come",
    "avant": "before",
    // ----- Vue galerie -----
    "Vue liste": "List view",
    "Vue galerie": "Gallery view",
    "+ Nouveau dossier": "+ New folder",
    "Les dossiers ne servent qu'\u00e0 s'y retrouver : ils": "Folders are only there to find your way around: they",
    "ne changent pas l'ordre d'\u00e9valuation": "do not change the evaluation order",
    ", qui reste celui de la vue liste (le num\u00e9ro sur chaque carte le rappelle). Fais glisser une r\u00e8gle d'un dossier \u00e0 l'autre pour la ranger. Ce classement reste sur cet ordinateur \u2014 il n'est pas enregistr\u00e9 dans la base.":
      ", which stays that of the list view (the number on each card is a reminder). Drag a rule from one folder to another to file it. This filing stays on this computer \u2014 it is not stored in the database.",
    "Glisse une r\u00e8gle ici.": "Drag a rule here.",
    "Rang d'\u00e9valuation": "Evaluation rank",
    "inactive": "inactive",
    "Nom du nouveau dossier": "Name of the new folder",
    "Nouveau nom du dossier": "New folder name",
    "Un dossier porte d\u00e9j\u00e0 ce nom.": "A folder already has that name.",
    "Supprimer le dossier": "Delete folder",
    "Ses r\u00e8gles reviendront dans \u00ab Autres \u00bb.": "Its rules will move back to \u201cOthers\u201d.",
    "\u21b3 la lecture continue avec les r\u00e8gles suivantes":
      "\u21b3 reading continues with the rules below",
    "les correspondances m\u00e9moris\u00e9es : un type reconnu ici ne peut plus \u00eatre d\u00e9fait par une correspondance de cat\u00e9gorie.":
      "the remembered mappings: a type recognised here can no longer be undone by a category mapping.",
    "R\u00e8gles de cat\u00e9gorisation": "Categorisation rules",
    "Une r\u00e8gle reconna\u00eet des lignes \u00e0 leur libell\u00e9 et dit ce qu'elles sont : virement interne, pr\u00eat, d\u00e9pense remboursable\u2026 Elle peut aussi poser la cat\u00e9gorie, et passe avant tout le reste.":
      "A rule recognises rows by their label and says what they are: internal transfer, loan, reimbursable expense\u2026 It can also set the category, and comes before everything else.",
    "+ Nouvelle r\u00e8gle": "+ New rule",
    "Nouvelle r\u00e8gle": "New rule",
    "Nom de la r\u00e8gle": "Rule name",
    "ex. Pr\u00eats re\u00e7us": "e.g. Loans received",
    "Conditions": "Conditions",
    "Les groupes se combinent entre eux ; \u00e0 l'int\u00e9rieur d'un groupe, les conditions se combinent selon leur propre connecteur. Deux niveaux suffisent \u00e0 \u00e9crire \u00ab (A ou B) et C \u00bb.":
      "Groups combine with one another; inside a group, conditions combine using their own connector. Two levels are enough to write \u201c(A or B) and C\u201d.",
    "Combiner les groupes avec": "Combine groups with",
    "ET (tous les groupes)": "AND (every group)",
    "OU (au moins un groupe)": "OR (at least one group)",
    "+ Ajouter un groupe": "+ Add a group",
    "Action": "Action",
    "Le type d\u00e9termine ce qui suit : seules \u00ab Op\u00e9ration classique \u00bb et \u00ab D\u00e9pense remboursable \u00bb laissent choisir une cat\u00e9gorie \u2014 les autres types imposent la leur.":
      "The type decides what follows: only a standard transaction and a reimbursable expense let you pick a category \u2014 the other types impose their own.",
    "Classer comme": "File as",
    "Dans la cat\u00e9gorie": "In category",
    "\u2014 ne pas changer \u2014": "\u2014 leave unchanged \u2014",
    "Avec le compte en face": "With the facing account",
    "L'autre compte du virement, celui que le relev\u00e9 ne nomme pas. Le sens se d\u00e9duit du signe du montant. Sans lui, la ligne est \u00e0 compl\u00e9ter \u00e0 la main dans l'aper\u00e7u.":
      "The transfer's other account, the one the statement does not name. The direction follows the sign of the amount. Without it, the row must be completed by hand in the preview.",
    "\u2014 \u00e0 renseigner \u00e0 l'import \u2014": "\u2014 to be filled in at import \u2014",
    "R\u00e8gle active": "Rule active",
    "Arr\u00eater la lecture des r\u00e8gles ici": "Stop reading rules here",
    "Coch\u00e9, le r\u00e9glage habituel : cette r\u00e8gle d\u00e9cide, on s'arr\u00eate l\u00e0. D\u00e9coch\u00e9, les r\u00e8gles suivantes peuvent compl\u00e9ter ce qu'elle laisse ouvert \u2014 la cat\u00e9gorie, le compte en face. Le type reste celui de la premi\u00e8re r\u00e8gle qui a mordu.":
      "Ticked, the usual setting: this rule decides and we stop there. Unticked, the rules after it can fill in what it leaves open \u2014 the category, the facing account. The type stays that of the first rule that matched.",
    // Onglet des Param\u00e8tres (les r\u00e8gles \u00e9tant parties dans une extension).
    "Correspondances": "Mappings",
    "Correspondances m\u00e9moris\u00e9es": "Remembered mappings",
    "Tout ce que l'app a retenu de tes imports : un libell\u00e9 rang\u00e9 une fois dans une cat\u00e9gorie y repart tout seul les fois suivantes.":
      "Everything the app has remembered from your imports: a label filed once under a category goes back there on its own next time.",
    "Cat\u00e9gories bancaires": "Bank categories",
    "Chaque libell\u00e9 de tes relev\u00e9s, sous la cat\u00e9gorie o\u00f9 il part. Fais-en glisser un dans une autre colonne pour le reclasser. Entre parenth\u00e8ses, le compte d'o\u00f9 vient le relev\u00e9.":
      "Each label from your statements, under the category it goes to. Drag one into another column to refile it. In brackets, the account the statement came from.",
    "Comptes bancaires": "Bank accounts",
    "Les noms de compte lus dans tes relev\u00e9s, et le compte de l'app en face. Une entr\u00e9e partag\u00e9e par plusieurs presets les met tous \u00e0 jour.":
      "The account names read from your statements, and the app account facing each one. An entry shared by several presets updates them all.",
    "Devises": "Currencies",
    "Les libell\u00e9s de devise de tes relev\u00e9s (\u00ab EUR \u00bb), et la monnaie de l'app en face. Vide si aucun preset ne lit de colonne de devise.":
      "The currency labels from your statements (\u201cEUR\u201d), and the app currency facing each one. Empty if no preset reads a currency column.",

    // ---------- Param\u00e8tres : import ----------
    "D\u00e9pose l'export Excel ou CSV de ta banque. Avant de valider, tu auras deux choses \u00e0 faire : dire dans quelles cat\u00e9gories ranger les libell\u00e9s que l'app ne conna\u00eet pas encore, et jeter un \u0153il aux doublons qu'elle a rep\u00e9r\u00e9s.":
      "Drop in your bank's Excel or CSV export. Before you can confirm, two things to do: say which categories the labels the app does not know yet belong to, and take a look at the duplicates it has spotted.",

    // ---------- Les cat\u00e9gories pos\u00e9es \u00e0 l'installation ----------
    // Une cat\u00e9gorie est une DONN\u00c9E, pas un texte d'interface : celles que
    // l'utilisateur cr\u00e9e gardent le nom qu'il leur a donn\u00e9. Seules celles que
    // l'application pose elle-m\u00eame \u00e0 l'installation ont un \u00e9quivalent anglais,
    // et `t()` ne rend que ce qu'il conna\u00eet (cf. libelleCategorie dans app.js).
    "Autres": "Others",

    // ---------- Param\u00e8tres : import, annulation d'un import ----------
    "Annuler un import retire les op\u00e9rations qu'il avait cr\u00e9\u00e9es, celles que tu as modifi\u00e9es depuis comprises. Le fichier redevient importable.":
      "Undoing an import removes the transactions it created, including those you have edited since. The file becomes importable again.",
    "plus rien \u00e0 annuler": "nothing left to cancel",
    "import trop ancien": "import too old",
    "Cet import est ant\u00e9rieur au suivi des op\u00e9rations import\u00e9es : l'app ne sait pas lesquelles il a cr\u00e9\u00e9es, elle ne peut donc pas les retirer. Seuls les imports faits depuis sont annulables.":
      "This import predates the tracking of imported transactions: the app does not know which ones it created, so it cannot remove them. Only imports made since can be cancelled.",
    "Aucun import pour le moment.": "No imports yet.",
    "Annuler cet import supprimera {n} op\u00e9ration(s) et le rendra r\u00e9importable. Cette action est irr\u00e9versible. Continuer ?":
      "Cancelling this import will delete {n} transaction(s) and make it importable again. This cannot be undone. Continue?",
    "Import annul\u00e9 : {n} op\u00e9ration(s) supprim\u00e9e(s).":
      "Import cancelled: {n} transaction(s) deleted.",

    // R\u00e9glages de lecture en dernier recours (d\u00e9limiteur, s\u00e9parateur d\u00e9cimal).
    "R\u00e9glages de lecture (d\u00e9limiteur, s\u00e9parateur d\u00e9cimal)":
      "Reading settings (delimiter, decimal separator)",
    "\u00c0 r\u00e9gler seulement si le fichier est mal lu : colonnes m\u00e9lang\u00e9es, montants illisibles. L'app devine seule dans la plupart des cas.":
      "Only worth setting if the file is read wrongly: mixed-up columns, unreadable amounts. The app works it out on its own most of the time.",
    "D\u00e9limiteur de colonnes": "Column delimiter",
    "D\u00e9tecter automatiquement": "Detect automatically",
    "Point-virgule ( ; )": "Semicolon ( ; )",
    "Virgule ( , )": "Comma ( , )",
    "Tabulation": "Tab",
    "Autre\u2026": "Other\u2026",
    "ex. |": "e.g. |",
    "S\u00e9parateur d\u00e9cimal": "Decimal separator",
    "D\u00e9tecter automatiquement (virgule fran\u00e7aise)": "Detect automatically (French comma)",
    "Virgule \u2014 1234,56": "Comma \u2014 1234,56",
    "Point \u2014 1234.56": "Point \u2014 1234.56",
    "Relire le fichier avec ces r\u00e9glages": "Re-read the file with these settings",
    "La plupart des lignes sont illisibles : le fichier n'utilise sans doute pas le d\u00e9limiteur ou le s\u00e9parateur d\u00e9cimal d\u00e9tect\u00e9s automatiquement. Pr\u00e9cise-les ci-dessous, puis relis le fichier.":
      "Most rows are unreadable: the file probably does not use the automatically detected delimiter or decimal separator. Set them below, then re-read the file.",

    "Preset": "Preset",
    "Tout ce qui est propre au format d'une banque : colonnes \u00e0 lire, libell\u00e9s d\u00e9j\u00e0 rang\u00e9s, lignes d\u00e9j\u00e0 import\u00e9es. Un preset par banque.":
      "Everything specific to one bank's format: which columns to read, labels already filed, rows already imported. One preset per bank.",
    "+ Nouveau preset": "+ New preset",
    "Renommer": "Rename",
    "Supprimer ce preset": "Delete this preset",
    "Compte bancaire de ce preset": "Bank account for this preset",
    "Toutes les lignes du fichier iront sur ce compte. Laisse \u00ab aucun \u00bb si le fichier nomme lui-m\u00eame le compte de chaque ligne.":
      "Every row in the file will go to this account. Leave \u201cnone\u201d if the file names each row's account itself.",
    "\u2014 aucun : le compte vient du fichier \u2014": "\u2014 none: the account comes from the file \u2014",
    "Configuration du fichier": "File configuration",
    "Indique quelles colonnes lire dans ton fichier (le nombre est libre) et \u00e0 quelle information de l'app chacune correspond. Date, Nature et Montant sont obligatoires ; Cat\u00e9gorie bancaire est facultative. Tout le reste \u2014 compte, sens, devises, montant envoy\u00e9, frais, \u00e9tat \u2014 se configure dans \u00ab Configuration avanc\u00e9e \u00bb plus bas.":
      "State which columns to read in your file (there is no limit) and which piece of app information each one holds. Date, Description and Amount are required; Bank category is optional. Everything else \u2014 account, direction, currencies, amount sent, fees, status \u2014 is configured under \u201cAdvanced configuration\u201d below.",
    "Clique sur l'\u0153il pour lire ou ignorer une colonne. Date, Nature et Montant sont obligatoires et ne s'\u00e9teignent pas.":
      "Click the eye to read or ignore a column. Date, Description and Amount are required and cannot be switched off.",
    "La premi\u00e8re ligne du fichier est un en-t\u00eate (\u00e0 ne pas importer)":
      "The first row of the file is a header (do not import it)",
    "Comparaison des doublons": "Duplicate comparison",
    "Une ligne import\u00e9e est compar\u00e9e aux lignes d\u00e9j\u00e0 import\u00e9es pour d\u00e9tecter les doublons. Deux fa\u00e7ons de dire la m\u00eame chose : pars de toutes les colonnes et retire celles qui bougent d'un export \u00e0 l'autre (solde courant, r\u00e9f\u00e9rence, date de valeur), ou ne d\u00e9signe que celles qui identifient une ligne (souvent date + libell\u00e9 + montant). La comparaison ignore ce qui ne se voit pas : espaces ins\u00e9cables, accents d\u00e9compos\u00e9s, espaces en trop.":
      "An imported row is compared with rows already imported in order to detect duplicates. Two ways of saying the same thing: start from every column and remove those that shift between exports (running balance, reference, value date), or name only those that identify a row (usually date + description + amount). The comparison ignores what cannot be seen: non-breaking spaces, decomposed accents, extra spaces.",
    "Comparer": "Compare",
    "toutes les colonnes, sauf celles-ci": "every column except these",
    "uniquement ces colonnes": "only these columns",
    "+ Ajouter une colonne": "+ Add a column",
    "Configuration avanc\u00e9e": "Advanced configuration",
    "Compte bancaire": "Bank account",
    "Montant envoy\u00e9": "Amount sent",
    "Monnaie envoy\u00e9e": "Currency sent",
    "Frais": "Fees",
    "Monnaie des frais": "Fee currency",
    "\u00c9tat": "Status",
    "Montant au d\u00e9bit": "Debit amount",
    "Montant au cr\u00e9dit": "Credit amount",
    "Pour ce que ton relev\u00e9 dit en plus : le compte, le sens, les devises, les frais. Laisse vide si ton relev\u00e9 tient dans une seule colonne de montant et une seule monnaie. Le \u00ab i \u00bb de chaque ligne dit \u00e0 quoi elle sert.":
      "For whatever your statement says on top: the account, the direction, the currencies, the fees. Leave it empty if your statement fits in a single amount column and a single currency. The \u201ci\u201d on each row says what it is for.",

    // Les explications des propri\u00e9t\u00e9s d'import, une entr\u00e9e par info-bulle
    // (cf. INFOS_PROPRIETES_IMPORT). Les sauts de ligne font partie de la
    // cha\u00eene : la bulle les rend tels quels. Ces textes \u00e9taient auparavant
    // d\u00e9coup\u00e9s en fragments par les <strong> du HTML, ce qui produisait des
    // cl\u00e9s comme \u00ab et \u00bb ou \u00ab , ils s' \u00bb : intraduisibles isol\u00e9ment, et
    // cass\u00e9es au moindre remaniement de la phrase.
    "La cat\u00e9gorie que la banque a elle-m\u00eame pos\u00e9e sur la ligne.\n\nElle ne devient jamais une cat\u00e9gorie de l'app toute seule : tu fais la correspondance une fois, et elle est m\u00e9moris\u00e9e pour les imports suivants.":
      "The category the bank itself put on the row.\n\nIt never becomes an app category on its own: you make the match once, and it is remembered for later imports.",
    "Le compte que la ligne concerne, quand le fichier le nomme.\n\nInutile si le preset est d\u00e9j\u00e0 li\u00e9 \u00e0 un compte : ce lien-l\u00e0 s'impose \u00e0 toutes les lignes et cette colonne n'est alors m\u00eame pas consult\u00e9e.":
      "The account the row concerns, when the file names it.\n\nPointless if the preset is already tied to an account: that link applies to every row, and this column is then never even read.",
    "\u00c0 ne configurer que si ton relev\u00e9 n'\u00e9crit que des montants positifs et indique \u00e0 part si l'argent entre ou sort.\n\nLes mots-cl\u00e9s reconnus se r\u00e8glent juste en dessous. Une valeur non reconnue met la ligne en erreur plut\u00f4t que d'\u00eatre devin\u00e9e.":
      "Only worth configuring if your statement writes positive amounts only and says separately whether money comes in or goes out.\n\nThe recognised keywords are set just below. An unrecognised value puts the row in error rather than being guessed.",
    "La devise du montant.\n\nSans elle, une ligne est libell\u00e9e dans la monnaie principale de son compte \u2014 ce qui est faux d\u00e8s qu'un compte en porte plusieurs.":
      "The currency of the amount.\n\nWithout it, a row is denominated in its account's main currency \u2014 which is wrong as soon as an account holds several.",
    "Ce qui PART, avant frais et avant conversion. \u00ab Montant \u00bb d\u00e9crit alors ce qui ARRIVE (le formulaire l'appelle \u00ab Montant re\u00e7u \u00bb d\u00e8s que les deux devises diff\u00e8rent).\n\nC'est le couple qui permet d'importer un virement entre deux devises, ou une conversion au sein d'un compte multi-devises : l'app ne conna\u00eet aucun taux de change, seul ton relev\u00e9 peut donner les deux montants. Sur un virement interne, le montant envoy\u00e9 est la jambe \u00e9mettrice.":
      "What LEAVES, before fees and before conversion. \u201cAmount\u201d then describes what ARRIVES (the form calls it \u201cAmount received\u201d as soon as the two currencies differ).\n\nThis is the pair that makes it possible to import a transfer between two currencies, or a conversion inside a multi-currency account: the app knows no exchange rate, only your statement can give both amounts. On an internal transfer, the amount sent is the outgoing leg.",
    "La devise du montant envoy\u00e9.\n\nSans elle, elle est suppos\u00e9e identique \u00e0 celle du montant re\u00e7u \u2014 ce qui revient \u00e0 supposer qu'il n'y a pas eu de change.":
      "The currency of the amount sent.\n\nWithout it, it is assumed identical to the currency received \u2014 which amounts to assuming there was no exchange.",
    "Les frais pr\u00e9lev\u00e9s par la banque.\n\nC'est leur DEVISE, et elle seule, qui d\u00e9cide auquel des deux montants ils se rapportent. Dans la monnaie envoy\u00e9e, ils s'AJOUTENT au montant envoy\u00e9 : ce qui est parti co\u00fbte plus que ce qui \u00e9tait annonc\u00e9. Dans la monnaie du montant re\u00e7u, ils s'en RETRANCHENT : ce qui reste est amput\u00e9 de la commission.\n\nS'ils ne sont dans ni l'une ni l'autre, l'import est refus\u00e9 \u2014 additionner deux devises fausserait un solde sans rien signaler. Retire alors cette colonne, ou corrige la colonne de devise qui la qualifie.":
      "The fees charged by the bank.\n\nIt is their CURRENCY, and it alone, that decides which of the two amounts they belong to. In the currency sent, they are ADDED to the amount sent: what left costs more than what was announced. In the currency of the amount received, they are SUBTRACTED from it: what remains is reduced by the commission.\n\nIf they are in neither, the import is refused \u2014 adding two currencies together would falsify a balance without a word. Remove this column, or correct the currency column that qualifies it.",
    "La devise des frais, celle qui d\u00e9cide \u00e0 quel montant ils s'appliquent.\n\nSans elle, l'app ne peut rien v\u00e9rifier : elle rapporte les frais au montant envoy\u00e9 (ou au montant, si le preset ne lit pas de montant envoy\u00e9) et le signale par un avertissement \u00e0 chaque import.":
      "The currency of the fees, the one that decides which amount they apply to.\n\nWithout it the app can check nothing: it applies the fees to the amount sent (or to the amount, if the preset reads no amount sent) and says so with a warning at every import.",
    "O\u00f9 en est l'op\u00e9ration chez la banque.\n\nUne ligne EN ATTENTE (autorisation pas encore comptabilis\u00e9e) devient une op\u00e9ration pr\u00e9visionnelle. Une ligne REFUS\u00c9E ou annul\u00e9e n'est pas import\u00e9e du tout, et n'entre pas non plus dans les lignes d\u00e9j\u00e0 vues qui servent \u00e0 d\u00e9tecter les doublons.\n\nLes mots-cl\u00e9s se r\u00e8glent plus bas.":
      "Where the transaction stands at the bank.\n\nA PENDING row (an authorisation not yet booked) becomes a forecast transaction. A DECLINED or cancelled row is not imported at all, and does not join the already-seen rows used to detect duplicates either.\n\nThe keywords are set below.",
    "Le montant de la ligne, sign\u00e9 : n\u00e9gatif il sort, positif il entre.\n\nSi ton relev\u00e9 s\u00e9pare au contraire les sorties et les entr\u00e9es dans deux colonnes, \u00e9teins celle-ci et configure \u00ab Montant au d\u00e9bit \u00bb et \u00ab Montant au cr\u00e9dit \u00bb dans la configuration avanc\u00e9e.":
      "The row's amount, signed: negative it goes out, positive it comes in.\n\nIf your statement instead splits money out and money in across two columns, switch this one off and configure \u201cDebit amount\u201d and \u201cCredit amount\u201d in the advanced configuration.",
    "\u00c0 configurer quand ton relev\u00e9 S\u00c9PARE les sorties et les entr\u00e9es dans deux colonnes, chaque ligne n'en remplissant qu'une. Les deux colonnes remplacent \u00ab Montant \u00bb et se r\u00e8glent ensemble.\n\nLa colonne remplie dit le sens, exactement comme le ferait une colonne \u00ab Sens \u00bb : ce qui est au d\u00e9bit sort, ce qui est au cr\u00e9dit entre. Un z\u00e9ro compte comme une case vide. Une ligne qui remplit les deux part en erreur \u2014 compenser l'un par l'autre inventerait une op\u00e9ration que ton relev\u00e9 ne d\u00e9crit pas.":
      "Worth configuring when your statement SPLITS money out and money in across two columns, each row filling only one. The two columns replace \u201cAmount\u201d and are set together.\n\nThe filled column says the direction, exactly as a \u201cDirection\u201d column would: what sits in debit goes out, what sits in credit comes in. A zero counts as an empty cell. A row that fills both goes into error \u2014 netting one against the other would invent a transaction your statement does not describe.",
    "L'autre moiti\u00e9 du montant scind\u00e9 : ce qui ENTRE.\n\nElle va toujours de pair avec \u00ab Montant au d\u00e9bit \u00bb \u2014 allumer ou \u00e9teindre l'une fait la m\u00eame chose \u00e0 l'autre.":
      "The other half of the split amount: what COMES IN.\n\nIt always goes with \u201cDebit amount\u201d \u2014 switching one on or off does the same to the other.",
    "Mots-cl\u00e9s de la colonne \u00ab Sens \u00bb": "Keywords for the \u201cDirection\u201d column",
    "Les mots que ta banque emploie pour dire qu'une ligne sort ou entre. Ajoute-les un par un avec \u00ab + \u00bb ou Entr\u00e9e ; majuscules et accents sont ignor\u00e9s. Retenus avec le preset.":
      "The words your bank uses to say a row goes out or comes in. Add them one at a time with \u201c+\u201d or Enter; case and accents are ignored. Kept with the preset.",
    "Laisse vide pour garder les mots-cl\u00e9s reconnus par d\u00e9faut, rappel\u00e9s sous chaque champ. D\u00e8s que tu en ajoutes un, il remplace toute la liste par d\u00e9faut de ce sens-l\u00e0.":
      "Leave it empty to keep the keywords recognised by default, recalled under each field. As soon as you add one, it replaces the whole default list for that direction.",
    "Sortie (argent qui part)": "Money out (leaving)",
    "Par d\u00e9faut :": "Default:",
    "Entr\u00e9e (argent qui rentre)": "Money in (arriving)",
    "Mots-cl\u00e9s de la colonne \u00ab \u00c9tat \u00bb": "Keywords for the \u201cStatus\u201d column",
    "Les mots que ta banque emploie pour dire o\u00f9 en est une op\u00e9ration, m\u00eame fonctionnement qu'au-dessus. Un mot inconnu met la ligne en erreur plut\u00f4t que d'\u00eatre devin\u00e9.":
      "The words your bank uses to say where a transaction stands, same as above. An unknown word puts the row in error rather than being guessed.",
    "Laisse vide pour garder les mots-cl\u00e9s reconnus par d\u00e9faut. D\u00e8s que tu en ajoutes un, il remplace toute la liste par d\u00e9faut de cet \u00e9tat-l\u00e0.":
      "Leave it empty to keep the keywords recognised by default. As soon as you add one, it replaces the whole default list for that status.",
    Sortie: "Money out",
    "Entr\u00e9e": "Money in",
    "Ex\u00e9cut\u00e9": "Settled",
    "Refus\u00e9 / annul\u00e9": "Declined / cancelled",
    "D\u00e9bit": "Debit",
    "Cr\u00e9dit": "Credit",
    "Refus\u00e9": "Declined",
    "Ex\u00e9cut\u00e9 (l'argent a boug\u00e9)": "Settled (the money moved)",
    "En attente \u2192 op\u00e9ration pr\u00e9visionnelle": "Pending \u2192 forecast transaction",
    "Refus\u00e9 / annul\u00e9 \u2192 ligne non import\u00e9e": "Declined / cancelled \u2192 row not imported",
    "Enregistrer la configuration": "Save configuration",
    "Compte pour ce fichier (aucune colonne \"Compte bancaire\" configur\u00e9e)":
      "Account for this file (no \"Bank account\" column configured)",
    "\u2014 choisir \u2014": "\u2014 choose \u2014",
    "S\u00e9lectionner un fichier Excel ou CSV": "Select an Excel or CSV file",
    "ou glisse-d\u00e9pose ton fichier ici \u2014 l'analyse d\u00e9marre automatiquement":
      "or drop your file here \u2014 analysis starts on its own",
    "Le fichier tel qu'il est": "The file as it is",
    "Chaque colonne lue est color\u00e9e et porte le nom de la propri\u00e9t\u00e9 qui sera import\u00e9e. Les colonnes grises sont ignor\u00e9es. Si une couleur ne tombe pas en face des bonnes donn\u00e9es, corrige les num\u00e9ros de colonne dans \"Configuration du fichier\" au-dessus.":
      "Each column being read is coloured and carries the name of the property that will be imported. Grey columns are ignored. If a colour does not land on the right data, correct the column numbers under \"File configuration\" above.",
    "Cat\u00e9gories bancaires \u00e0 confirmer": "Bank categories to confirm",
    "Une cat\u00e9gorie sans correspondance m\u00e9moris\u00e9e est propos\u00e9e par d\u00e9faut dans \"Autres\" : coche \"Confirmer\" pour la garder telle quelle, ou change la avant de confirmer l'import. Tant que ce n'est pas fait, tu peux continuer \u00e0 utiliser l'app normalement (cr\u00e9er des cat\u00e9gories, etc.) \u2014 seule la validation de cet import attend.":
      "A category with no remembered mapping is proposed under \"Autres\" by default: tick \"Confirmer\" to keep it as is, or change it before confirming the import. Until that is done you can carry on using the app normally (creating categories and so on) \u2014 only this import's validation waits.",
    "Tout confirmer": "Confirm all",
    "Comptes bancaires \u00e0 faire correspondre": "Bank accounts to map",
    "Devises \u00e0 faire correspondre": "Currencies to map",
    "Ton relev\u00e9 \u00e9crit \u00ab EUR \u00bb, l'app conna\u00eet les monnaies que tu as nomm\u00e9es. Dis-le une fois, c'est retenu pour la suite.":
      "Your statement writes \u201cEUR\u201d, the app knows the currencies you named. Say it once, it is remembered from then on.",
    "Devises d\u00e9j\u00e0 rattach\u00e9es": "Currencies already linked",
    "Ces libell\u00e9s ont d\u00e9j\u00e0 leur correspondance : rien \u00e0 faire, c'est l\u00e0 pour v\u00e9rifier avant de confirmer.":
      "These labels already have their match: nothing to do, it is here so you can check before confirming.",
    "Aper\u00e7u \u2014": "Preview \u2014",
    "ligne(s)": "row(s)",
    "Les doublons d\u00e9tect\u00e9s sont pr\u00e9-s\u00e9lectionn\u00e9s. Tant qu'il reste des lignes s\u00e9lectionn\u00e9es, l'import est bloqu\u00e9 : supprime-les, ou d\u00e9coche-les pour les importer quand m\u00eame. Le bouton \"Modifier\" permet aussi de reclasser une ligne dans une autre cat\u00e9gorie d'op\u00e9ration.":
      "Detected duplicates are pre-selected. As long as rows remain selected the import is blocked: delete them, or untick them to import them anyway. The \"Modifier\" button also lets you refile a row under another transaction type.",
    "Tout s\u00e9lectionner": "Select all",
    "Supprimer la s\u00e9lection (": "Delete selection (",
    "Op\u00e9rations classiques \u2014": "Standard transactions \u2014",
    "Ligne": "Row",
    "Cat\u00e9gorie (banque)": "Category (bank)",
    "Compte (banque)": "Account (bank)",
    "S\u00e9lection": "Selection",
    "D\u00e9penses remboursables \u2014": "Reimbursable expenses \u2014",
    "Remboursements re\u00e7us \u2014": "Reimbursements received \u2014",
    "Virements internes \u2014": "Internal transfers \u2014",
    "Compte \u00e9metteur": "Sending account",
    "Compte r\u00e9cepteur": "Receiving account",
    "Pr\u00eats re\u00e7us \u2014": "Loans received \u2014",
    "Remboursements de pr\u00eats \u2014": "Loan repayments \u2014",
    "Ressemblances \u2014": "Look-alikes \u2014",
    "Doublons de virement interne possibles.": "Possible internal-transfer duplicates.",
    "Veille des doublons de virement : {compares} ligne(s) compar\u00e9e(s) sur {total}":
      "Transfer-duplicate watch: {compares} row(s) compared out of {total}",
    "{n} ressemblance(s) trouv\u00e9e(s).": "{n} look-alike(s) found.",
    "aucune ressemblance.": "no look-alike.",
    "{n} ligne(s) n'ont pas pu \u00eatre compar\u00e9es : il leur manque une date ou un compte reconnu.":
      "{n} row(s) could not be compared: they lack a date or a recognised account.",
    "Deux relev\u00e9s de deux banques d\u00e9crivent le m\u00eame virement avec des colonnes qui n'ont rien de commun : la d\u00e9tection de doublons ordinaire, qui compare des lignes de fichier, ne peut structurellement pas les voir. Celle-ci compare la":
      "Two statements from two banks describe the same transfer with columns that have nothing in common: ordinary duplicate detection, which compares file rows, structurally cannot see them. This one compares the",
    "transaction": "transaction",
    "\u2014 le compte que ton relev\u00e9 nomme, les devises, un des deux montants, et une date voisine.":
      "itself \u2014 the account your statement names, the currencies, one of the two amounts, and a nearby date.",
    "Un seul compte suffit": "One account is enough",
    ": tu n'as pas \u00e0 retrouver le compte d'en face pour savoir si tu as d\u00e9j\u00e0 la ligne. C'est m\u00eame l'inverse \u2014 le compte d'en face montr\u00e9 en italique est celui que l'op\u00e9ration ressemblante te donne, et rien n'est enregistr\u00e9 tant que tu ne l'as pas repris \u00e0 la main. Rien n'est bloqu\u00e9 ni pr\u00e9-s\u00e9lectionn\u00e9 : toi seul sais si tu as vraiment vir\u00e9 deux fois. Chaque ligne est suivie de ce \u00e0 quoi elle ressemble.":
      ": you do not have to track down the facing account to know whether you already have the row. It is the other way round \u2014 the facing account shown in italics is the one the look-alike transaction gives you, and nothing is stored until you enter it yourself. Nothing is blocked or pre-selected: you alone know whether you really transferred twice. Each row is followed by what it resembles.",
    "\u00c9metteur": "Sender",
    "R\u00e9cepteur": "Receiver",
    "Compte lu sur l'op\u00e9ration \u00e0 laquelle cette ligne ressemble. Rien n'est enregistr\u00e9 : reprends-le par \u00ab Modifier \u00bb si tu veux vraiment importer cette ligne.":
      "Account read from the transaction this row resembles. Nothing is stored: enter it through \u201cEdit\u201d if you really want to import this row.",
    "Doublons d\u00e9tect\u00e9s \u2014": "Duplicates detected \u2014",
    "Ces lignes sont identiques \u00e0 des lignes d\u00e9j\u00e0 import\u00e9es : chacune est suivie de celle qu'elle recopie. Elles sont coch\u00e9es pour \u00eatre \u00e9cart\u00e9es d'un clic \u2014 d\u00e9coches-en une pour l'importer quand m\u00eame, deux achats identiques le m\u00eame jour \u00e7a arrive.":
      "These rows are identical to rows already imported: each is followed by the one it repeats. They are ticked so you can drop them in one click \u2014 untick one to import it anyway, two identical purchases on the same day do happen.",
    "Confirmer l'import": "Confirm import",
    "Historique des importations": "Import history",
    "Fichier": "File",
    "Op\u00e9rations cr\u00e9\u00e9es": "Transactions created",
    "Lignes ignor\u00e9es": "Rows skipped",
    "Doublons d\u00e9tect\u00e9s": "Duplicates detected",

    // ---------- Messages et confirmations (app.js) ----------
    "Supprimer cette monnaie ?": "Delete this currency?",
    "Monnaie supprim\u00e9e": "Currency deleted",
    "Monnaie modifi\u00e9e": "Currency updated",
    "Monnaie cr\u00e9\u00e9e": "Currency created",
    "Renseigne le chemin complet du fichier .db.": "Enter the full path to the .db file.",
    "Revenir \u00e0 la base de test ?": "Go back to the test database?",
    "Supprimer ce type de compte ?": "Delete this account type?",
    "Type de compte supprim\u00e9": "Account type deleted",
    "Supprimer ce compte ?": "Delete this account?",
    "Compte supprim\u00e9": "Account deleted",
    "Type de compte modifi\u00e9": "Account type changed",
    "Ordre des comptes modifi\u00e9": "Account order changed",
    "Choisis au moins une monnaie pour ce compte.": "Pick at least one currency for this account.",
    "Compte modifi\u00e9": "Account updated",
    "Compte cr\u00e9\u00e9": "Account created",
    "Supprimer cette cat\u00e9gorie ?": "Delete this category?",
    "Cat\u00e9gorie supprim\u00e9e": "Category deleted",
    "Budget modifi\u00e9": "Budget updated",
    "Cat\u00e9gorie cr\u00e9\u00e9e": "Category created",
    "Supprimer cette op\u00e9ration ?": "Delete this transaction?",
    "Op\u00e9ration supprim\u00e9e": "Transaction deleted",
    "Renseigne le montant re\u00e7u : les deux comptes sont dans des monnaies diff\u00e9rentes ":
      "Enter the amount received: the two accounts are in different currencies ",
    "Virement modifi\u00e9": "Transfer updated",
    "Virement cr\u00e9\u00e9": "Transfer created",
    "La nature de l'op\u00e9ration est obligatoire.": "The description is required.",
    "Renseigne un montant r\u00e9gl\u00e9 pour au moins une op\u00e9ration.":
      "Enter a settled amount for at least one transaction.",
    "Op\u00e9ration modifi\u00e9e": "Transaction updated",
    "Op\u00e9ration cr\u00e9\u00e9e": "Transaction created",
    "Pr\u00eat modifi\u00e9": "Loan updated",
    "Pr\u00eat cr\u00e9\u00e9": "Loan created",
    "Supprimer TOUTES les op\u00e9rations ? Action irr\u00e9versible \u2014 pens\u00e9 pour vider des donn\u00e9es de test.":
      "Delete EVERY transaction? This cannot be undone \u2014 meant for clearing test data.",
    "Cours mis \u00e0 jour": "Price updated",
    "Supprimer ce titre ?": "Delete this security?",
    "Titre supprim\u00e9": "Security deleted",
    "Supprimer ce mouvement ? Le solde du compte sera recalcul\u00e9.":
      "Delete this movement? The account balance will be recalculated.",
    "Mouvement supprim\u00e9": "Movement deleted",
    "Titre ajout\u00e9": "Security added",
    "Preset renomm\u00e9": "Preset renamed",
    "Preset supprim\u00e9": "Preset deleted",
    "Configuration enregistr\u00e9e": "Configuration saved",
    "Choisis d'abord un fichier \u00e0 analyser.": "Choose a file to analyse first.",
    "Aucun preset d'import disponible : cr\u00e9es-en un d'abord.":
      "No import preset available: create one first.",
    "Un aper\u00e7u est d\u00e9j\u00e0 en cours : analyser ce fichier l'abandonnera (lignes en attente comprises). Continuer ?":
      "A preview is already open: analysing this file will discard it, pending rows included. Continue?",
    "Ce compte ne porte aucune monnaie : impossible de cr\u00e9er l'op\u00e9ration.":
      "This account holds no currency: the transaction cannot be created.",
    "Renseigne une date valide.": "Enter a valid date.",
    "La nature ne peut pas \u00eatre vide.": "The description cannot be empty.",
    "Choisis un compte.": "Choose an account.",
    "Le compte \u00e9metteur et le compte r\u00e9cepteur doivent \u00eatre diff\u00e9rents, sauf pour une ":
      "The sending and receiving accounts must differ, except for a ",
    "Renseigne le montant envoy\u00e9 : les deux monnaies diff\u00e8rent et l'app ne convertit rien.":
      "Enter the amount sent: the two currencies differ and the app converts nothing.",
    "Choisis une cat\u00e9gorie.": "Choose a category.",
    "Import termin\u00e9 : toutes les lignes ont \u00e9t\u00e9 trait\u00e9es.":
      "Import finished: every row has been processed.",
    "Termine maintenant les remboursements / remboursements de pr\u00eats en attente, ci-dessous.":
      "Now finish the pending reimbursements and loan repayments below.",
    "Correspondance supprim\u00e9e": "Mapping deleted",
    "Correspondance reclass\u00e9e": "Mapping refiled",
    "Correspondance mise \u00e0 jour": "Mapping updated",
    "Mapping mis \u00e0 jour": "Mapping updated",
    "Mapping supprim\u00e9": "Mapping deleted",
    "R\u00e8gle supprim\u00e9e": "Rule deleted",
    "Donne un nom \u00e0 la r\u00e8gle.": "Give the rule a name.",
    "Chaque condition doit porter sur un champ.": "Every condition must target a field.",
    "Chaque condition doit avoir une valeur \u00e0 comparer.":
      "Every condition must have a value to compare.",
    "R\u00e8gle modifi\u00e9e": "Rule updated",
    "R\u00e8gle cr\u00e9\u00e9e": "Rule created",

    // ---------- Messages du serveur ----------
    // Le serveur ne parle que fran\u00e7ais ; ces phrases sont traduites \u00e0
    // l'affichage (cf. traduireMessageServeur). Celles qui portent un nom ou un
    // nombre sont dans MOTIFS_SERVEUR plus bas.
    "Monnaie introuvable": "Currency not found",
    "Un titre avec ce nom existe d\u00e9j\u00e0": "A security with this name already exists",
    "Titre introuvable": "Security not found",
    "Ce titre a des mouvements enregistr\u00e9s : sa monnaie de cotation ne peut plus changer (les montants d\u00e9j\u00e0 pay\u00e9s sont libell\u00e9s dans l'ancienne).":
      "This security has recorded movements: its quote currency can no longer change (the amounts already paid are denominated in the old one).",
    "Ce titre a des mouvements enregistr\u00e9s : supprime-les d'abord (les soldes du compte en d\u00e9pendent).":
      "This security has recorded movements: delete them first (the account balances depend on them).",
    "Une cat\u00e9gorie avec ce nom existe d\u00e9j\u00e0": "A category with this name already exists",
    "mois doit \u00eatre entre 1 et 12": "month must be between 1 and 12",
    "Cat\u00e9gorie introuvable": "Category not found",
    "La cat\u00e9gorie 'Autres' ne peut pas \u00eatre supprim\u00e9e": "The 'Autres' category cannot be deleted",
    "Type de compte introuvable": "Account type not found",
    "Une m\u00eame monnaie ne peut pas \u00eatre ajout\u00e9e deux fois":
      "The same currency cannot be added twice",
    "Un compte avec ce nom existe d\u00e9j\u00e0": "An account with this name already exists",
    "Compte introuvable": "Account not found",
    "Impossible de supprimer un compte qui a des op\u00e9rations li\u00e9es":
      "An account with linked transactions cannot be deleted",
    "vue doit \u00eatre 'mois' ou 'annee'": "view must be 'mois' or 'annee'",
    "Preset d'import introuvable": "Import preset not found",
    "Au moins une colonne est requise": "At least one column is required",
    "Chaque propri\u00e9t\u00e9 ne peut \u00eatre assign\u00e9e qu'\u00e0 une seule colonne":
      "Each property can be assigned to only one column",
    "Chaque colonne ne peut \u00eatre utilis\u00e9e qu'une fois": "Each column can be used only once",
    "Les colonnes de la comparaison doivent \u00eatre num\u00e9rot\u00e9es \u00e0 partir de 1":
      "Comparison columns must be numbered from 1",
    "Choisis au moins une colonne \u00e0 comparer, ou repasse en \u00ab comparer toutes les colonnes sauf \u00bb.":
      "Pick at least one column to compare, or switch back to \u201ccompare every column except\u201d.",
    "Impossible de supprimer le dernier preset restant": "The last remaining preset cannot be deleted",
    "Mapping introuvable": "Mapping not found",
    "mappings invalide (JSON attendu)": "invalid mappings (JSON expected)",
    "Une monnaie avec ce nom existe d\u00e9j\u00e0": "A currency with this name already exists",
    "Cette monnaie est encore utilis\u00e9e par un compte, une op\u00e9ration, un budget ou un titre : elle ne peut pas \u00eatre supprim\u00e9e.":
      "This currency is still used by an account, a transaction, a budget or a security: it cannot be deleted.",
    "Les op\u00e9rations classiques et remboursements ne peuvent pas cibler un compte d'\u00e9pargne ; utilise un virement interne.":
      "Standard transactions and reimbursements cannot target a savings account; use an internal transfer.",
    "Un compte de placements financiers n'accepte que des virements internes et des achats/ventes de titres (page Placements financiers).":
      "An investment account only accepts internal transfers and security purchases or sales (Investments page).",
    "Type d'op\u00e9ration introuvable": "Transaction type not found",
    "Le type 'Virement interne' est r\u00e9serv\u00e9 aux virements, cr\u00e9\u00e9s via /virements (deux \u00e9critures li\u00e9es).":
      "The 'Virement interne' type is reserved for transfers, created through /virements (two linked entries).",
    "Cette \u00e9criture appartient \u00e0 un achat/vente de titres : modifie-la depuis la page Placements financiers.":
      "This entry belongs to a security purchase or sale: edit it from the Investments page.",
    "Op\u00e9ration introuvable": "Transaction not found",
    "Cette op\u00e9ration fait partie d'un virement : supprimez le virement et recr\u00e9ez l'op\u00e9ration pour en changer le type.":
      "This transaction is part of a transfer: delete the transfer and recreate the transaction to change its type.",
    "montant_du ne peut pas d\u00e9passer montant": "montant_du cannot exceed montant",
    "montant_a_rembourser ne peut pas d\u00e9passer montant_du":
      "montant_a_rembourser cannot exceed montant_du",
    "Cette op\u00e9ration fait partie d'un virement interne ; elle doit \u00eatre supprim\u00e9e via l'endpoint de virement.":
      "This transaction is part of an internal transfer; it must be deleted through the transfer endpoint.",
    "Cette op\u00e9ration est marqu\u00e9e comme rembours\u00e9e via un remboursement li\u00e9 ; d\u00e9liez-la d'abord (depuis l'op\u00e9ration de remboursement) pour modifier ce montant manuellement.":
      "This transaction is marked as reimbursed through a linked reimbursement; unlink it first (from the reimbursement transaction) to change this amount by hand.",
    "Ce compte n'est pas un compte de placements financiers": "This is not an investment account",
    "Mouvement de titres introuvable": "Security movement not found",
    "R\u00e8gle introuvable": "Rule not found",
    "Compte en face introuvable": "Facing account not found",
    "Un type de compte avec ce nom existe d\u00e9j\u00e0": "An account type with this name already exists",
    "Ce type de compte est prot\u00e9g\u00e9 (utilis\u00e9 par les r\u00e8gles de l'application) et ne peut pas \u00eatre supprim\u00e9":
      "This account type is protected (used by the application's rules) and cannot be deleted",
    "Impossible de supprimer un type utilis\u00e9 par au moins un compte":
      "A type used by at least one account cannot be deleted",
    "Compte source introuvable": "Source account not found",
    "Compte destination introuvable": "Destination account not found",
    "Virement introuvable": "Transfer not found",
    "Ce virement n'a qu'une seule \u00e9criture (second compte inconnu \u00e0 l'import) : modifie-la comme une op\u00e9ration ordinaire.":
      "This transfer has only one entry (the second account was unknown at import): edit it like an ordinary transaction.",
    "frequence est requise pour une op\u00e9ration r\u00e9currente":
      "frequence is required for a recurring transaction",
    "Le compte source et le compte destination doivent \u00eatre diff\u00e9rents, sauf pour une conversion entre deux monnaies d'un m\u00eame compte (la monnaie re\u00e7ue doit alors diff\u00e9rer de la monnaie envoy\u00e9e)":
      "The source and destination accounts must differ, except for a conversion between two currencies of the same account (the currency received must then differ from the currency sent)",
    "la valeur \u00e0 comparer ne peut pas \u00eatre vide": "the value to compare cannot be empty",
    "Le sens d'un virement interne ne se d\u00e9duit pas de son type : il doit \u00eatre impos\u00e9 (transfert_sortant ou transfert_entrant) par l'appelant.":
      "The direction of an internal transfer cannot be deduced from its type: the caller must impose it (transfert_sortant or transfert_entrant).",

    // Erreurs par ligne, affich\u00e9es dans l'aper\u00e7u d'import.
    "date illisible": "unreadable date",
    "montant illisible": "unreadable amount",
    "nature manquante": "missing description",
    "cat\u00e9gorie non r\u00e9solue": "category not resolved",
    "compte non r\u00e9solu": "account not resolved",
    "frais dans une monnaie \u00e9trang\u00e8re aux montants de la ligne":
      "fees in a currency foreign to the row's amounts",
    "virement interne : le compte en face n'est pas renseign\u00e9":
      "internal transfer: the facing account is not filled in",
    "monnaie des frais manquante": "missing fee currency",
    "sens manquant": "missing direction",
    "montant présent au débit et au crédit": "amount present in both debit and credit",
    "virement interne : le sens de la ligne est indéterminé":
      "internal transfer: the row's direction is undetermined",
    "\u00e9tat manquant": "missing status",
    "frais sup\u00e9rieurs au montant de la ligne": "fees larger than the row's amount",
    "compte introuvable": "account not found",
    "virement entre deux monnaies sans montant envoy\u00e9 : renseigne le montant initial (l'app ne convertit rien)":
      "transfer between two currencies with no amount sent: fill in the amount sent (the app converts nothing)",
    "virement entre deux monnaies sans montant re\u00e7u : renseigne-le (l'app ne convertit rien)":
      "transfer between two currencies with no amount received: fill it in (the app converts nothing)",
    "le compte \u00e9metteur et le compte r\u00e9cepteur doivent \u00eatre diff\u00e9rents, sauf conversion entre deux monnaies d'un m\u00eame compte":
      "the sending and receiving accounts must differ, except for a conversion between two currencies of the same account",

    // ---------- Libell\u00e9s des gabarits (boutons, badges, listes vides) ----------
    "Modifier": "Edit",
    "Supprimer": "Delete",
    "Confirmer": "Confirm",
    "Rembours\u00e9": "Reimbursed",
    "En attente": "Pending",
    "Prot\u00e9g\u00e9": "Protected",
    "OK": "OK",
    "Esp\u00e8ces": "Cash",
    "Portefeuille": "Portfolio",
    "Total du compte": "Account total",
    "Plus-value latente": "Unrealised gain",
    "Liquidit\u00e9s disponibles pour acheter": "Cash available to buy with",
    "Titres d\u00e9tenus, au dernier cours saisi": "Securities held, at the last price entered",
    "Esp\u00e8ces + portefeuille": "Cash + portfolio",
    "Valorisation \u2212 capital investi": "Market value \u2212 capital invested",
    "Aucune monnaie.": "No currency.",
    "Aucun compte.": "No account.",
    "Aucun compte dans cette monnaie.": "No account in this currency.",
    "Aucune d\u00e9pense enregistr\u00e9e.": "No spending recorded.",
    // ----- Le détail par semaine de l'histogramme -----
    "D\u00e9tailler par semaine": "Break down by week",
    "Moyenne": "Average",
    "Replier les semaines": "Collapse the weeks",
    "ann\u00e9e {annee}": "year {annee}",
    "du {debut} au {fin} {mois}": "{mois} {debut} to {fin}",
    "moyenne des {n} semaines de {mois}": "average of the {n} weeks of {mois}",
    // ----- Les cartes de flux, sous le sélecteur de période -----
    "Total Entr\u00e9es": "Total money in",
    "Total D\u00e9penses": "Total spending",
    "Ce que la p\u00e9riode rapporte, virements internes exclus. Un pr\u00eat re\u00e7u n'y entre pas : il faudra le rendre. Reste sur le mois entier, semaine d\u00e9pli\u00e9e ou non.":
      "What the period brings in, internal transfers excluded. A loan received is not counted: it will have to be paid back. Stays on the whole month, week unfolded or not.",
    "Ce que la p\u00e9riode co\u00fbte, et non ce qui sort du compte : une d\u00e9pense amortie ne compte que pour sa part du mois, une remboursable pour le reste \u00e0 charge. Virements internes exclus. Reste sur le mois entier, semaine d\u00e9pli\u00e9e ou non.":
      "What the period costs, not what leaves the account: an amortised expense only counts for its share of the month, a reimbursable one for the amount left to bear. Internal transfers excluded. Stays on the whole month, week unfolded or not.",
    "De combien les comptes courants ont boug\u00e9 sur la p\u00e9riode. Tout compte \u00e0 sa date et pour son montant : une d\u00e9pense amortie en entier, une d\u00e9pense remboursable sans d\u00e9duire ce qu'on rendra. Virements internes exclus.":
      "How much the current accounts moved over the period. Everything counts on its date and for its amount: an amortised expense in full, a reimbursable one without deducting what will come back. Internal transfers excluded.",
    // ----- L'histogramme d'un projet (extension « Projets ») -----
    "R\u00e9partition par cat\u00e9gorie": "Breakdown by category",
    "Les sorties du projet, r\u00e9parties par cat\u00e9gorie \u2014 virements sortants compris, comme dans le total ci-dessus. Les entr\u00e9es n'y figurent pas : elles se lisent dans le total des entr\u00e9es.":
      "The project's outflows, split by category \u2014 outgoing transfers included, as in the total above. Inflows are not shown: they are read in the inflow total.",
    // ----- La note d'une règle d'import (migration 0050) -----
    "ex. la banque \u00e9crit \u00ab VIR RECU M DUPONT \u00bb pour les remboursements de Paul":
      "e.g. the bank writes \u201cVIR RECU M DUPONT\u201d for Paul's repayments",
    "ex. ce courtier \u00e9crit \u00ab ACHAT COMPTANT \u00bb suivi du nom du titre":
      "e.g. this broker writes \u201cACHAT COMPTANT\u201d followed by the security's name",
    "Note libre : pourquoi cette r\u00e8gle existe, quel relev\u00e9 l'a rendue n\u00e9cessaire, ce qu'il faudra v\u00e9rifier si elle cesse de mordre. Jamais lue par l'application.":
      "Free note: why this rule exists, which statement made it necessary, what to check if it stops matching. Never read by the application.",
    "Note libre : pourquoi cette r\u00e8gle existe, quel relev\u00e9 l'a rendue n\u00e9cessaire. Jamais lue par l'application.":
      "Free note: why this rule exists, which statement made it necessary. Never read by the application.",
    // Infobulle d'une barre de l'histogramme (cf. contenuInfobulleHistogramme).
    "Aucune op\u00e9ration sur la p\u00e9riode.": "No transaction over this period.",
    "Sans libell\u00e9": "No label",
    "La cat\u00e9gorie que ta banque a pos\u00e9e elle-m\u00eame sur la ligne.\n\nElle ne devient pas une cat\u00e9gorie de l'app toute seule : tu fais le rapprochement une fois, il est retenu.":
      "The category your bank put on the row itself.\n\nIt does not become an app category on its own: you match it once, and that is remembered.",
    "Le compte concern\u00e9, quand le fichier le nomme.\n\nInutile si le preset est d\u00e9j\u00e0 li\u00e9 \u00e0 un compte : ce lien vaut pour toutes les lignes.":
      "The account concerned, when the file names it.\n\nPointless if the preset is already linked to an account: that link covers every row.",
    "\u00c0 r\u00e9gler seulement si ton relev\u00e9 n'\u00e9crit que des montants positifs et dit \u00e0 part si l'argent entre ou sort.\n\nLes mots-cl\u00e9s reconnus se r\u00e8glent juste en dessous.":
      "Only needed if your statement writes positive amounts only and says separately whether money comes in or goes out.\n\nThe recognised keywords are set just below.",
    "La devise du montant.\n\nSans elle, la ligne part dans la monnaie principale de son compte \u2014 faux d\u00e8s qu'un compte en porte plusieurs.":
      "The currency of the amount.\n\nWithout it, the row goes to its account's main currency \u2014 wrong as soon as an account carries several.",
    "Ce qui PART du compte, avant frais et avant conversion ; \u00ab Montant \u00bb d\u00e9crit alors ce qui ARRIVE.\n\nC'est le couple qu'il faut pour importer un virement entre deux devises : seul ton relev\u00e9 conna\u00eet les deux montants.":
      "What LEAVES the account, before fees and before conversion; \u201cAmount\u201d then describes what ARRIVES.\n\nThis is the pair needed to import a transfer between two currencies: only your statement knows both amounts.",
    "La devise du montant envoy\u00e9.\n\nSans elle, l'app la suppose identique \u00e0 celle du montant re\u00e7u, donc sans change.":
      "The currency of the amount sent.\n\nWithout it, the app assumes it is the same as the amount received, so no exchange took place.",
    "Les frais pr\u00e9lev\u00e9s par la banque.\n\nC'est leur DEVISE qui d\u00e9cide auquel des deux montants ils se rapportent : dans la monnaie envoy\u00e9e ils s'y ajoutent, dans celle re\u00e7ue ils s'en retranchent. Dans une troisi\u00e8me, l'import est refus\u00e9 plut\u00f4t que de fausser un solde.":
      "The fees charged by the bank.\n\nIt is their CURRENCY that decides which of the two amounts they attach to: in the currency sent they add to it, in the one received they are taken from it. In a third one, the import is refused rather than falsifying a balance.",
    "La devise des frais, celle qui dit \u00e0 quel montant ils s'appliquent.\n\nSans elle, l'app les rattache au montant envoy\u00e9 et te le signale \u00e0 chaque import.":
      "The currency of the fees, the one that says which amount they apply to.\n\nWithout it, the app attaches them to the amount sent and tells you so at every import.",
    "Le montant de la ligne, avec son signe : n\u00e9gatif il sort, positif il entre.\n\nSi ton relev\u00e9 s\u00e9pare sorties et entr\u00e9es en deux colonnes, \u00e9teins celle-ci et r\u00e8gle \u00ab Montant au d\u00e9bit \u00bb et \u00ab Montant au cr\u00e9dit \u00bb.":
      "The amount of the row, with its sign: negative it goes out, positive it comes in.\n\nIf your statement splits money out and money in across two columns, turn this one off and set \u201cDebit amount\u201d and \u201cCredit amount\u201d.",
    "Pour les relev\u00e9s qui S\u00c9PARENT sorties et entr\u00e9es en deux colonnes, chaque ligne n'en remplissant qu'une.\n\nLa colonne remplie dit le sens. Un z\u00e9ro vaut une case vide, une ligne qui remplit les deux part en erreur.":
      "For statements that SPLIT money out and money in across two columns, each row filling only one.\n\nThe column filled tells the direction. A zero counts as an empty box, a row filling both goes to error.",
    "L'autre moiti\u00e9 : ce qui ENTRE.\n\nElle va toujours avec \u00ab Montant au d\u00e9bit \u00bb \u2014 allumer ou \u00e9teindre l'une fait la m\u00eame chose \u00e0 l'autre.":
      "The other half: what COMES IN.\n\nIt always goes with \u201cDebit amount\u201d \u2014 turning one on or off does the same to the other.",
    "O\u00f9 en est l'op\u00e9ration chez ta banque.\n\nUne ligne en attente devient une op\u00e9ration pr\u00e9visionnelle, une ligne refus\u00e9e n'est pas import\u00e9e. Les mots-cl\u00e9s se r\u00e8glent plus bas.":
      "Where the transaction stands at your bank.\n\nA pending row becomes a forecast transaction, a declined row is not imported. The keywords are set further down.",
    "Le nombre de titres que tu D\u00c9TIENS au moment de la photographie.\n\nC'est cette quantit\u00e9 qui part en base : l'app ne sait pas comment tu y es arriv\u00e9, seulement ce que tu as.":
      "The number of securities you HOLD at the time of the snapshot.\n\nThat quantity is what goes into the database: the app does not know how you got there, only what you have.",
    "Ce qu'UN titre t'a co\u00fbt\u00e9 en moyenne, frais compris (le PRU).\n\nPar titre, pas le total investi. Si ton relev\u00e9 donne le total, divise-le avant d'importer.":
      "What ONE security cost you on average, fees included.\n\nPer security, not the total invested. If your statement gives the total, divide it before importing.",
    "Ce que la ligne vaut aujourd'hui, tous titres confondus.\n\nElle ne cr\u00e9e aucune d\u00e9tention : elle sert \u00e0 d\u00e9duire le cours du titre (valeur \u00f7 quantit\u00e9), que ce genre d'export ne donne pas.":
      "What the row is worth today, all securities together.\n\nIt creates no holding: it serves to derive the security's price (value \u00f7 quantity), which this kind of export does not give.",
    "Ce que la ligne d\u00e9crit : un achat, une vente, ou un transfert d'esp\u00e8ces.\n\nLes mots-cl\u00e9s se r\u00e8glent juste en dessous. Un libell\u00e9 inconnu met la ligne en erreur plut\u00f4t que d'\u00eatre devin\u00e9.":
      "What the row describes: a purchase, a sale, or a cash transfer.\n\nThe keywords are set just below. An unknown label puts the row in error rather than being guessed.",
    "Le nom du titre tel que ton courtier l'\u00e9crit.\n\nFacultatif si tu lis l'ISIN, mais il faut l'un des deux : sans eux, une ligne d'achat ne dit pas de quelle valeur elle parle.":
      "The name of the security as your broker writes it.\n\nOptional if you read the ISIN, but one of the two is needed: without them, a purchase row does not say which security it is about.",
    "Le code ISIN du titre (FR0000120073, LU1681043599\u2026).\n\nSeul nom qui ne change jamais : c'est par lui qu'un titre est reconnu d'un import \u00e0 l'autre. Facultatif si tu lis le nom de la valeur.":
      "The security's ISIN code (FR0000120073, LU1681043599\u2026).\n\nThe only name that never changes: it is how a security is recognised from one import to the next. Optional if you read the security name.",
    "Ce que l'op\u00e9ration a co\u00fbt\u00e9 ou rapport\u00e9 en esp\u00e8ces.\n\nC'est lui qui fait foi : le prix par titre vaut montant \u00f7 quantit\u00e9, pas le cours annonc\u00e9. Ton solde colle ainsi au relev\u00e9, frais de courtage compris.":
      "What the transaction cost or brought in, in cash.\n\nThis is what counts: the price per security is amount \u00f7 quantity, not the price quoted. Your balance then matches the statement, brokerage fees included.",
    "Le prix par titre annonc\u00e9 par le relev\u00e9.\n\nIl ne d\u00e9cide de rien, il sert de contr\u00f4le : un \u00e9cart de plus de 1 % avec le montant divis\u00e9 par la quantit\u00e9 est signal\u00e9 au-dessus de l'aper\u00e7u, sans bloquer l'import.":
      "The price per security quoted by the statement.\n\nIt decides nothing, it is a check: a gap of more than 1% with the amount divided by the quantity is flagged above the preview, without blocking the import.",
    "L'\u00e9tiquette du titre, si ton fichier la porte : ETF, obligation, action\u2026\n\nFacultative, et sans effet sur un montant. Un libell\u00e9 que tu n'as pas encore cr\u00e9\u00e9 le sera \u00e0 l'import. Un titre que l'app conna\u00eet d\u00e9j\u00e0 garde le type que tu lui as pos\u00e9.":
      "The security's label, if your file carries it: ETF, bond, share\u2026\n\nOptional, and with no effect on any amount. A label you have not created yet will be created on import. A security the app already knows keeps the type you gave it.",
    "Quelle colonne de ton fichier porte quelle information. Date, Nature et Montant sont obligatoires ; le reste est dans \u00ab Configuration avanc\u00e9e \u00bb.":
      "Which column of your file carries which information. Date, Description and Amount are required; the rest is under \u201cAdvanced configuration\u201d.",
    "Comment l'app reconna\u00eet une ligne d\u00e9j\u00e0 import\u00e9e. Soit toutes les colonnes moins celles qui bougent d'un export \u00e0 l'autre (solde courant, r\u00e9f\u00e9rence), soit les seules qui identifient une ligne \u2014 souvent date + libell\u00e9 + montant.":
      "How the app recognises a row it has already imported. Either every column minus those that shift between exports (running balance, reference), or only those that identify a row \u2014 usually date + label + amount.",
    "Un preset par courtier : colonnes \u00e0 lire et vocabulaire de ses relev\u00e9s. Ceux des relev\u00e9s bancaires vivent \u00e0 part, sur la page Import.":
      "One preset per broker: which columns to read and the vocabulary of its statements. Bank statement presets live apart, on the Import page.",
    "Un relev\u00e9 de courtier ne dit jamais quel compte il d\u00e9crit. Le lier ici \u00e9vite de le choisir \u00e0 chaque import ; laisse vide si plusieurs comptes ont le m\u00eame format.":
      "A broker statement never says which account it describes. Linking it here saves picking it at every import; leave empty if several accounts share the same format.",
    "Comment l'app reconna\u00eet une ligne d\u00e9j\u00e0 import\u00e9e sous ce preset. Soit toutes les colonnes moins celles qui bougent d'un export \u00e0 l'autre (num\u00e9ro d'ordre, solde courant), soit les seules qui identifient une ligne \u2014 souvent date + valeur + montant + quantit\u00e9.":
      "How the app recognises a row already imported under this preset. Either every column minus those that shift between exports (order number, running balance), or only those that identify a row \u2014 usually date + holding + amount + quantity.",
    "L'app ne conna\u00eet pas encore ces valeurs et les cr\u00e9era \u00e0 l'import. Si l'une existe d\u00e9j\u00e0 chez toi sous un autre nom, choisis-la \u00e0 la main sur sa ligne.":
      "The app does not know these holdings yet and will create them on import. If one already exists under another name, pick it by hand on its row.",
    "Une \u00e9tiquette pos\u00e9e sur le titre que la ligne d\u00e9signe \u2014 ETF, obligation, action. Uniquement \u00e0 la cr\u00e9ation d'un titre : un titre d\u00e9j\u00e0 typ\u00e9 garde le sien. Purement descriptif.":
      "A label put on the holding the row names \u2014 ETF, bond, share. Only when a holding is created: one already typed keeps its own. Purely descriptive.",
    "La part de ton portefeuille en ETF, en obligations, en actions \u2014 \u00e0 la valeur d'aujourd'hui, tous comptes confondus. Survole une part pour voir les titres qui la composent.":
      "How much of your portfolio sits in ETFs, bonds, shares \u2014 at today's value, across every account. Hover a slice to see the holdings it is made of.",
    "Ce que vaut une monnaie dans une autre. Sert uniquement \u00e0 la case \u00ab tout convertir \u00bb du dashboard, et ne modifie aucun montant enregistr\u00e9. Un seul sens par couple suffit, l'inverse se calcule.":
      "What one currency is worth in another. Used only by the dashboard's \u201cconvert everything\u201d box, and changes no recorded amount. One direction per pair is enough, the reverse is computed.",
    "Tes propres \u00e9tiquettes \u2014 ETF, action en direct, obligation, SCPI \u2014 pour regrouper les titres. Purement descriptif : aucun solde ni aucune valorisation n'en d\u00e9pend.":
      "Your own labels \u2014 ETF, direct share, bond, property fund \u2014 to group holdings. Purely descriptive: no balance and no valuation depends on them.",
    "Aucun titre d\u00e9tenu sur ce compte.": "No securities held on this account.",
    "Aucun mouvement.": "No movements.",
    "Aucun compte \u2014 d\u00e9pose-en un ici.": "No account \u2014 drop one here.",
    "Aucun pr\u00eat non rembours\u00e9 disponible.": "No outstanding loan available.",
    "Aucune d\u00e9pense non rembours\u00e9e disponible.": "No unreimbursed expense available.",
    "Aucun titre. Ajoute-en un ci-dessous.": "No securities. Add one below.",
    "Glisser pour r\u00e9ordonner": "Drag to reorder",
    "Glisser pour r\u00e9ordonner, ou vers une autre carte pour changer de type":
      "Drag to reorder, or onto another card to change its type",
    "Solde initial dans cette monnaie": "Opening balance in this currency",
    "Cours unitaire actuel": "Current unit price",
    "aucun r\u00e9sultat": "no results",
    "Ne plus afficher sur le dashboard": "Stop showing on the dashboard",
    "Afficher sur le dashboard": "Show on the dashboard",
    "Masquer": "Hide",
    "Afficher": "Show",
    "Filtrer sur l'ann\u00e9e enti\u00e8re": "Filter on the whole year",
    "Filtrer sur un mois": "Filter on a single month",
    "Enregistr\u00e9": "Saved",
    "Nouvelle op\u00e9ration": "New transaction",
    "Modifier l'op\u00e9ration": "Edit transaction",
    "Pr\u00eats r\u00e9gl\u00e9s": "Loans settled",
    "Op\u00e9rations r\u00e9gl\u00e9es": "Transactions settled",
    "Date (r\u00e9cent \u2192 ancien)": "Date (newest first)",
    "Date (ancien \u2192 r\u00e9cent)": "Date (oldest first)",
    "Montant (d\u00e9croissant)": "Amount (highest first)",
    "Cat\u00e9gorie (A \u2192 Z)": "Category (A \u2192 Z)",
    "Reste \u00e0 rembourser (d\u00e9croissant)": "Outstanding (highest first)",
    "Reste \u00e0 rembourser (croissant)": "Outstanding (lowest first)",
    "Compte source (A \u2192 Z)": "Source account (A \u2192 Z)",
    "Montant (croissant)": "Amount (lowest first)",
    "Nature (A \u2192 Z)": "Description (A \u2192 Z)",
    "Compte (A \u2192 Z)": "Account (A \u2192 Z)",

    // ---------- Divers construits en JavaScript ----------
    "Projet\u00e9": "Projected",
    "cot\u00e9 en": "quoted in",
    "r\u00e9el": "settled",
    "pr\u00e9visionnel": "forecast",
    "{montant} seront d\u00e9bit\u00e9s des esp\u00e8ces du compte.":
      "{montant} will be debited from the account's cash.",
    "{montant} seront cr\u00e9dit\u00e9s sur les esp\u00e8ces du compte.":
      "{montant} will be credited to the account's cash.",
    "virement : compte en face \u00e0 renseigner": "transfer: facing account to be filled in",
    "compte en face \u00e0 renseigner \u00e0 l'import": "facing account to be filled in at import",
    "D\u00e9pose un libell\u00e9 ici.": "Drop a label here.",
    "Aucune correspondance de devise m\u00e9moris\u00e9e (aucun preset ne lit peut-\u00eatre de colonne de devise).":
      "No currency mapping remembered (perhaps no preset reads a currency column).",
    "Colonne n\u00b0": "Column no.",
    "Cette propri\u00e9t\u00e9 est obligatoire : elle ne peut pas \u00eatre d\u00e9sactiv\u00e9e.":
      "This property is required: it cannot be switched off.",
    "Ne plus lire cette colonne": "Stop reading this column",
    "Lire cette colonne": "Read this column",
    "Renseigne le num\u00e9ro de colonne de : {proprietes}.":
      "Enter the column number for: {proprietes}.",

    // Propri\u00e9t\u00e9s d'import (tables PROPRIETES_IMPORT*), champs et op\u00e9rateurs de r\u00e8gle.
    "Cat\u00e9gorie bancaire": "Bank category",
    "Nature / libell\u00e9": "Description / label",
    "est": "is",
    "n'est pas": "is not",
    "contient": "contains",
    "ne contient pas": "does not contain",
    "Si": "If",
    // Un virement dont une seule jambe est à l'écran : deux causes, deux gestes.
    "Cette \u00e9criture n'a pas de seconde jambe (virement import\u00e9 sans compte en face) : supprime-la et recr\u00e9e le virement avec ses deux comptes.":
      "This entry has no second leg (transfer imported without a facing account): delete it and create the transfer again with both accounts.",
    "La seconde \u00e9criture de ce virement n'est pas dans la liste affich\u00e9e : vide les filtres pour la modifier.":
      "The second entry of this transfer is not in the list shown: clear the filters to edit it.",
    "ET": "AND",
    "OU": "OR",
    "ou": "or",
    // Ce qui relie les mots-clés d'une seule condition (cf. extensions/regles).
    "et": "and",

    // ---------- Extension « Import de placements » ----------
    "Import de placements": "Investment import",
    "Importer des op\u00e9rations": "Import transactions",
    "\u2190 Retour aux placements": "\u2190 Back to investments",
    "Lit une liste d'opérations exportée depuis un compte de placements : achats, ventes et transferts d'espèces. Rien n'entre en base avant que tu ne valides l'aperçu.":
      "Reads a list of transactions exported from an investment account: purchases, sales and cash transfers. Nothing is saved until you validate the preview.",
    "Aucun compte de placements financiers. Crée-en un depuis la page Comptes en choisissant le type \"Placements financiers\", puis reviens ici.":
      "No investment account. Create one from the Accounts page by choosing the \"Investments\" type, then come back here.",
    "Format du fichier": "File format",
    "Un preset par courtier : il retient quelles colonnes lire, comment comparer les doublons et le vocabulaire de la colonne « Type d'opération ». Les presets de relevés bancaires vivent sur la page Import et ne se mélangent jamais avec ceux-ci.":
      "One preset per broker: it remembers which columns to read, how to compare duplicates and the wording of the “Transaction type” column. Bank statement presets live on the Import page and never mix with these.",
    "Compte de placements de ce preset": "Investment account for this preset",
    "Un relevé de courtier ne nomme nulle part le compte qu'il décrit : il EST ce compte. Lier le preset une fois évite de le choisir à chaque import. Laisse vide si tu importes plusieurs comptes avec le même format — le compte se choisira alors fichier par fichier.":
      "A broker statement never names the account it describes: it IS that account. Linking the preset once saves choosing it at every import. Leave empty if you import several accounts with the same format — the account will then be chosen file by file.",
    "— aucun (choisir à chaque fichier) —": "— none (choose for each file) —",
    "Quelle colonne du fichier porte quoi. Les numéros sont ceux d'Excel : la première colonne est la n°1. L'œil barré ne lit pas la colonne.":
      "Which column of the file carries what. Numbers are Excel's: the first column is n°1. A crossed-out eye means the column is not read.",
    "Mots-clés de la colonne « Type d'opération »": "Keywords for the “Transaction type” column",
    "Ce que TON courtier écrit pour dire achat, vente, ou mouvement d'espèces. Sépare les mots-clés par des virgules. La casse, les accents et les espaces sont ignorés : « Transfert interne », « TRANSFERT INTERNE » et « transfertinterne » sont le même mot-clé. Une liste laissée vide retombe sur les mots par défaut, indépendamment des deux autres. Un libellé qui ne figure dans aucune des trois listes met la ligne en erreur plutôt que d'être deviné : confondre un achat et une vente inverserait une position entière.":
      "What YOUR broker writes for a purchase, a sale, or a cash movement. Separate keywords with commas. Case, accents and spaces are ignored: “Internal transfer”, “INTERNAL TRANSFER” and “internaltransfer” are the same keyword. A list left empty falls back on the default words, independently of the other two. A label that appears in none of the three lists puts the row in error rather than being guessed: mistaking a purchase for a sale would reverse a whole position.",
    "Achat, Souscription, Buy": "Purchase, Subscription, Buy",
    "Vente, Cession, Rachat": "Sale, Disposal, Redemption",
    "Transfert interne (espèces)": "Internal transfer (cash)",
    "Versement, Retrait, Virement": "Deposit, Withdrawal, Transfer",
    "Une ligne importée est comparée aux lignes déjà importées SOUS CE PRESET pour détecter les doublons. Deux façons de dire la même chose : pars de toutes les colonnes et retire celles qui bougent d'un export à l'autre (numéro d'ordre, solde courant), ou ne désigne que celles qui identifient une ligne (souvent date + valeur + montant + quantité). Les transferts d'espèces, eux, sont EN PLUS rapprochés des virements déjà en base, d'où qu'ils viennent — c'est un mécanisme à part, qui ne dépend pas de ce réglage.":
      "An imported row is compared with rows already imported UNDER THIS PRESET to detect duplicates. Two ways of saying the same thing: start from every column and remove those that change from one export to the next (order number, running balance), or name only those that identify a row (often date + security + amount + quantity). Cash transfers are ALSO matched against transfers already recorded, wherever they came from — that is a separate mechanism, independent of this setting.",
    "Compte de placements pour ce fichier": "Investment account for this file",
    "Titres qui seront créés": "Securities that will be created",
    "Ces valeurs ne sont pas encore connues de l'application : l'import les créera, avec leur nom et leur code ISIN, cotées dans la monnaie principale du compte. Si l'une d'elles existe déjà sous un autre nom, choisis le titre à la main sur la ligne concernée (bouton Modifier) plutôt que de laisser créer un doublon.":
      "These securities are not known to the application yet: the import will create them, with their name and ISIN code, quoted in the account's main currency. If one of them already exists under another name, pick the security by hand on the row concerned (Edit button) rather than letting a duplicate be created.",
    "Transferts déjà connus": "Transfers already known",
    "Achats —": "Purchases —",
    "Ventes —": "Sales —",
    "Transferts internes —": "Internal transfers —",
    "Lignes en erreur —": "Rows in error —",
    "Valeur": "Security",
    "ISIN": "ISIN",
    "Le relevé ne décrit qu'un côté du mouvement : indique le compte en face. Le sens (émetteur ou récepteur) est déduit du signe du montant.":
      "The statement describes only one side of the movement: name the account facing it. The direction (sender or receiver) is deduced from the sign of the amount.",
    "Ces lignes ne seront pas importées telles quelles. Corrige-les avec \"Modifier\", ou supprime-les de l'aperçu — le reste du fichier s'importe normalement.":
      "These rows will not be imported as they stand. Fix them with \"Edit\", or remove them from the preview — the rest of the file imports normally.",

    // Libellés construits en JavaScript (import-placements.js).
    "Date de l'opération": "Transaction date",
    "Type d'opération": "Transaction type",
    "Nom de la valeur": "Security name",
    "Code ISIN": "ISIN code",
    "Montant de l'opération": "Transaction amount",
    "Cours": "Price",
    "Achat": "Purchase",
    "Vente": "Sale",
    "Transfert interne": "Internal transfer",
    "Ce que la ligne décrit : un achat, une vente, ou un transfert d'espèces vers ou depuis un autre compte.\n\nLes mots-clés reconnus se règlent juste en dessous. Un libellé inconnu met la ligne en erreur plutôt que d'être deviné.":
      "What the row describes: a purchase, a sale, or a cash transfer to or from another account.\n\nThe recognised keywords are set just below. An unknown label puts the row in error rather than being guessed.",
    "Le nom du titre tel que ton courtier l'écrit.\n\nFacultatif si tu lis le code ISIN, mais l'un des deux est indispensable : sans eux, une ligne d'achat ne dit pas de quelle valeur elle parle.":
      "The security name as your broker writes it.\n\nOptional if you read the ISIN code, but one of the two is essential: without them, a purchase row does not say which security it is about.",
    "Le code ISIN du titre (FR0000120073, LU1681043599…).\n\nC'est la seule dénomination qui ne change jamais : c'est par lui qu'un titre est reconnu d'un import à l'autre, même si son nom a changé. Facultatif si tu lis le nom de la valeur.":
      "The security's ISIN code (FR0000120073, LU1681043599…).\n\nIt is the only name that never changes: it is how a security is recognised from one import to the next, even if its name has changed. Optional if you read the security name.",
    "Ce que l'opération a coûté ou rapporté en espèces.\n\nC'est LUI qui fait foi : le prix unitaire importé vaut montant ÷ quantité, jamais le cours annoncé. Le solde du compte colle ainsi au relevé, et les frais de courtage entrent dans le prix de revient.":
      "What the transaction cost or returned in cash.\n\nIT is what counts: the imported unit price is amount ÷ quantity, never the quoted price. The account balance thus matches the statement, and brokerage fees enter the cost basis.",
    "Le nombre de titres achetés ou vendus.\n\nSans objet sur une ligne de transfert d'espèces, qui peut la laisser vide.":
      "The number of securities bought or sold.\n\nIrrelevant on a cash transfer row, which may leave it empty.",
    "Le prix unitaire annoncé par le relevé. La seule colonne entièrement facultative.\n\nElle ne décide de rien : elle sert de contrôle. Un écart de plus de 1 % avec le montant divisé par la quantité est signalé au-dessus de l'aperçu, sans jamais bloquer l'import.":
      "The unit price stated by the statement. The only entirely optional column.\n\nIt decides nothing: it serves as a check. A gap of more than 1% with the amount divided by the quantity is reported above the preview, without ever blocking the import.",
    "Garde le nom de la valeur ou le code ISIN : sans l'un des deux, aucune ligne ne peut dire de quel titre elle parle.":
      "Keep the security name or the ISIN code: without one of the two, no row can say which security it is about.",
    "Aucun preset. Crée-en un pour commencer.": "No preset. Create one to get started.",
    "Aucune colonne choisie : ajoute-en au moins une, sinon plus rien ne distingue deux lignes.":
      "No column chosen: add at least one, otherwise nothing tells two rows apart.",
    "Aucune colonne exclue : toutes les colonnes du fichier sont comparées.":
      "No column excluded: every column of the file is compared.",
    "colonne(s) lue(s)": "column(s) read",
    "La plupart des lignes sont illisibles : le délimiteur ou le séparateur décimal ne convient probablement pas à ce fichier.":
      "Most rows are unreadable: the delimiter or the decimal separator probably does not suit this file.",
    "ligne(s) au total — fais défiler le tableau pour les voir toutes.":
      "row(s) in total — scroll the table to see them all.",
    "Une ligne identique a déjà été importée sous ce preset.":
      "An identical row has already been imported under this preset.",
    "doublon": "duplicate",
    "nouveau": "new",
    "à renseigner": "to be filled in",
    "cours du fichier": "price from the file",
    "compte en face": "account facing it",
    "jour(s) d'écart": "day(s) apart",
    "Compte en face (transfert)": "Account facing it (transfer)",
    "— d'après le fichier —": "— from the file —",
    "— aucun —": "— none —",
    "Appliquer": "Apply",
    "Supprime ou décoche les lignes sélectionnées pour pouvoir confirmer.":
      "Delete or uncheck the selected rows before you can confirm.",
    "opération(s) créée(s)": "transaction(s) created",
    "titre(s) créé(s)": "security(ies) created",
    "doublon(s) signalé(s)": "duplicate(s) flagged",
    "ligne(s) non importée(s) :": "row(s) not imported:",
    "Aucun import sous ce preset.": "No import under this preset.",
    "(sans nom)": "(unnamed)",
    "opération(s)": "transaction(s)",
    "ignorée(s)": "skipped",
    "doublon(s)": "duplicate(s)",
    "Annuler cet import": "Undo this import",
    "import antérieur au suivi des opérations": "import predating transaction tracking",
    "Annuler cet import supprimera les opérations qu'il a créées, y compris celles modifiées depuis. Continuer ?":
      "Undoing this import will delete the transactions it created, including those modified since. Continue?",
    "opération(s) supprimée(s)": "transaction(s) deleted",
    "Nom du nouveau preset (le nom de ton courtier, par exemple)":
      "Name of the new preset (your broker's name, for instance)",
    "Preset créé": "Preset created",
    "Nouveau nom": "New name",
    "Supprimer ce preset effacera aussi son historique d'imports et ses lignes de comparaison. Les opérations déjà importées, elles, restent. Continuer ?":
      "Deleting this preset will also erase its import history and its comparison rows. The transactions already imported do remain. Continue?",
    "Les doublons détectés sont pré-sélectionnés. Tant qu'il reste des lignes sélectionnées, l'import est bloqué : supprime-les, ou décoche-les pour les importer quand même.":
      "Detected duplicates are pre-selected. As long as rows remain selected, the import is blocked: delete them, or uncheck them to import them anyway.",
    "Problème": "Problem",
    "Imports précédents": "Previous imports",

    // ---------- Galerie des correspondances : ordre des colonnes ----------
    "Fais glisser cet en-t\u00eate pour d\u00e9placer la colonne":
      "Drag this header to move the column",
    "Ordre des colonnes enregistr\u00e9": "Column order saved",

    // ---------- Import de placements : mots-cl\u00e9s ----------
    "Les mots que ton courtier emploie pour dire achat, vente ou mouvement d'esp\u00e8ces. Ajoute-les un par un avec \u00ab + \u00bb ou Entr\u00e9e ; majuscules, accents et espaces sont ignor\u00e9s. Une liste vide retombe sur les mots par d\u00e9faut, un libell\u00e9 inconnu met la ligne en erreur.":
      "The words your broker uses for purchase, sale or cash movement. Add them one at a time with \u201c+\u201d or Enter; case, accents and spaces are ignored. An empty list falls back on the default words, an unknown label puts the row in error.",
    "Ajouter ce mot-cl\u00e9": "Add this keyword",
    // ----- Les frais d'une opération, décomposés dans le formulaire -----
    "Frais": "Fees",
    "Monnaie des frais": "Fee currency",
    " (hors frais)": " (before fees)",
    "Montant re\u00e7u": "Amount received",
    "Les frais que la banque a pr\u00e9lev\u00e9s, d\u00e9j\u00e0 compris dans le montant : ajout\u00e9s \u00e0 ce qui sort, retranch\u00e9s de ce qui entre. Le montant au-dessus est donc affich\u00e9 hors frais, et les deux se recomposent \u00e0 l'enregistrement.":
      "The fees the bank charged, already included in the amount: added to what goes out, taken from what comes in. The amount above is therefore shown before fees, and the two are recombined on save.",
    "La devise des frais dit \u00e0 quel montant ils s'appliquent : sur un virement entre deux monnaies, des frais dans la monnaie envoy\u00e9e gr\u00e8vent ce qui part, dans la monnaie re\u00e7ue ce qui arrive.":
      "The fee currency says which amount they apply to: on a transfer between two currencies, fees in the sent currency weigh on what leaves, in the received currency on what arrives.",
    // ----- Réorganiser les colonnes en glissant les en-têtes de l'aperçu -----
    "Cette colonne n'existe pas dans le fichier : d\u00e9place son en-t\u00eate sur une colonne r\u00e9elle.":
      "This column does not exist in the file: drag its header onto a real column.",
    "Les colonnes color\u00e9es sont celles que l'app va lire, les grises sont ignor\u00e9es. Deux fa\u00e7ons de corriger un d\u00e9calage : glisser un en-t\u00eate sur un autre pour \u00e9changer les deux colonnes, ou saisir les num\u00e9ros dans \u00ab Configuration du fichier \u00bb au-dessus.":
      "Coloured columns are the ones the app will read, grey ones are ignored. Two ways to fix a mismatch: drag one header onto another to swap the two columns, or type the numbers in \u201cFile configuration\u201d above.",
    "Les colonnes ont chang\u00e9 depuis la derni\u00e8re lecture. Relire le fichier pour voir ce que l'import donnera, puis \u00ab Enregistrer la configuration \u00bb pour garder cet ordre dans le preset.":
      "The columns have changed since the last read. Read the file again to see what the import will give, then use \u201cSave configuration\u201d to keep this order in the preset.",
    "Glisse cet en-t\u00eate sur un autre pour \u00e9changer les deux colonnes":
      "Drag this header onto another one to swap the two columns",
    "Relire le fichier avec la configuration actuelle":
      "Read the file again with the current configuration",
    "Les colonnes ont chang\u00e9 : relire le fichier pour voir ce que l'import donnera.":
      "The columns have changed: read the file again to see what the import will give.",
    "Aucun fichier charg\u00e9 \u00e0 relire.": "No file loaded to read again.",
    "Fichier relu. \u00ab Enregistrer la configuration \u00bb pour garder cet ordre de colonnes dans le preset.":
      "File read again. Use \u201cSave configuration\u201d to keep this column order in the preset.",
    // Les mots-clés d'une condition de règle : le même éditeur, dans une rangée
    // où le mot « Actualisation » de l'import n'aurait rien dit.
    "Retirer": "Remove",
    "Mots-cl\u00e9s": "Keywords",
    "Aucun mot-cl\u00e9 : la condition ne compare rien.":
      "No keyword: the condition compares nothing.",
    "ex. PRET": "e.g. LOAN",
    Actualisation: "Refresh",
    Versement: "Deposit",
    "Aucun mot-cl\u00e9 \u2014 les mots par d\u00e9faut s'appliquent.":
      "No keyword \u2014 the default words apply.",
    "Rien \u00e0 supprimer.": "Nothing to remove.",
    "Ce mot-cl\u00e9 est d\u00e9j\u00e0 dans la liste.": "That keyword is already in the list.",
    "\u00ab {mot} \u00bb est d\u00e9j\u00e0 un mot-cl\u00e9 de \u00ab {type} \u00bb.":
      "\u201c{mot}\u201d is already a keyword of \u201c{type}\u201d.",

    // ---------- Import de placements : onglet R\u00e8gles ----------
    "R\u00e8gles de type d'op\u00e9ration": "Transaction type rules",
    "Une r\u00e8gle reconna\u00eet une ligne \u00e0 son libell\u00e9 et dit ce qu'elle est : achat, vente, transfert d'esp\u00e8ces. Elle vaut pour tous tes courtiers et passe avant les mots-cl\u00e9s du preset.":
      "A rule recognises a row by its label and says what it is: purchase, sale, cash transfer. It applies to all your brokers and comes before the preset's keywords.",
    "Les mots-cl\u00e9s de la \u00ab Configuration du fichier \u00bb comparent un libell\u00e9":
      "The keywords under \u201cFile configuration\u201d compare a",
    entier: "whole label",
    ": \u00ab Achat \u00bb est un achat, et rien d'autre ne l'est. Quand le courtier \u00e9crit une phrase \u2014 \u00ab ACHAT COMPTANT ETF MSCI WORLD \u00bb, avec le nom du titre dedans \u2014 aucune liste de mots-cl\u00e9s ne peut la reconna\u00eetre, parce qu'il n'y a pas deux fois le m\u00eame libell\u00e9 dans le fichier. Une r\u00e8gle, elle, sait dire \u00ab":
      ": \u201cBuy\u201d is a buy, and nothing else is. When the broker writes a sentence \u2014 \u201cCASH BUY ETF MSCI WORLD\u201d, with the security's name inside \u2014 no keyword list can recognise it, because no two rows of the file carry the same label. A rule, however, can say \u201c",
    "ACHAT \u00bb.": "contains BUY\u201d.",
    "et s'arr\u00eatent \u00e0 la premi\u00e8re qui correspond : contrairement aux r\u00e8gles bancaires, une r\u00e8gle de placement ne d\u00e9cide que d'une chose, il n'y a donc rien \u00e0 compl\u00e9ter en dessous. Place les cas particuliers au-dessus des cas g\u00e9n\u00e9raux.":
      "and stop at the first one that matches: unlike bank rules, an investment rule decides one thing only, so there is nothing left for the ones below to fill in. Put the special cases above the general ones.",
    "Une ligne qu'aucune r\u00e8gle ne reconna\u00eet retombe sur les":
      "A row no rule recognises falls back on the",
    "mots-cl\u00e9s du preset": "preset's keywords",
    ". Sans aucune r\u00e8gle, l'import se comporte donc exactement comme avant.":
      ". With no rule at all, the import therefore behaves exactly as before.",
    "ex. Achats au comptant": "e.g. Cash buys",
    "Une ligne de compte-titres n'a que son type \u00e0 d\u00e9cider : ni cat\u00e9gorie (un mouvement de titres n'en porte pas), ni compte en face (le transfert le d\u00e9duit du signe du montant).":
      "A securities-account row has only its type to decide: no category (a securities movement carries none), and no facing account (a transfer infers it from the sign of the amount).",
    "La ligne d\u00e9crit": "The row describes",
    "Un achat de titres": "A securities purchase",
    "Une vente de titres": "A securities sale",
    "Un transfert interne (esp\u00e8ces)": "An internal transfer (cash)",
    "Aucune r\u00e8gle : le type de chaque ligne est reconnu par les mots-cl\u00e9s du preset.":
      "No rule: each row's type is recognised by the preset's keywords.",
    "Glisse pour changer l'ordre": "Drag to reorder",
    Groupe: "Group",
    "Combiner avec": "Combine with",
    "Supprimer le groupe": "Delete the group",
    "Ajouter une condition": "Add a condition",
    "Modifier la r\u00e8gle": "Edit the rule",

    // ---------- Projets ----------
    Projets: "Projects",
    "Rassemble des op\u00e9rations d\u00e9j\u00e0 saisies, quelles que soient leur cat\u00e9gorie et leur compte, pour lire ce qu'un voyage ou un d\u00e9m\u00e9nagement t'a co\u00fbt\u00e9. Une op\u00e9ration peut appartenir \u00e0 plusieurs projets, et rien d'autre dans l'app n'en tient compte.":
      "Gathers transactions you have already entered, whatever their category and account, to read what a trip or a move cost you. A transaction can belong to several projects, and nothing else in the app takes them into account.",
    "Un projet ne se saisit pas depuis une op\u00e9ration : on le cr\u00e9e ici, puis on y verse les op\u00e9rations concern\u00e9es. C'est un":
      "A project is not entered from a transaction: you create it here, then pour the relevant transactions into it. It is a",
    "regroupement de lecture": "reading grouping",
    "\u2014 retirer une op\u00e9ration d'un projet ne la supprime pas, et supprimer un projet ne supprime aucune d\u00e9pense.":
      "\u2014 removing a transaction from a project does not delete it, and deleting a project deletes no spending.",
    "+ Nouveau projet": "+ New project",
    "Nouveau projet": "New project",
    "Modifier le projet": "Edit the project",
    "ex. Vacances Italie": "e.g. Italy holiday",
    "ex. du 3 au 17 ao\u00fbt, Rome et Naples": "e.g. 3\u201317 August, Rome and Naples",
    "\u2190 Retour aux projets": "\u2190 Back to projects",
    "+ Ajouter des op\u00e9rations": "+ Add transactions",
    "Ajouter des op\u00e9rations": "Add transactions",
    "Ajouter une op\u00e9ration ici ne la retire d'aucun autre projet, et ne change ni sa cat\u00e9gorie ni son compte.":
      "Adding a transaction here removes it from no other project, and changes neither its category nor its account.",
    "Montant min": "Min amount",
    "Montant max": "Max amount",
    "ex. 50": "e.g. 50",
    "ex. 500": "e.g. 500",
    "La valeur du montant sans son signe : \u00ab au moins 50 \u00bb attrape aussi bien une d\u00e9pense de 80 \u20ac qu'une entr\u00e9e de 80 \u20ac. Laisse une case vide pour ne pas borner de ce c\u00f4t\u00e9.":
      "The amount without its sign: \u201cat least 50\u201d catches an 80 \u20ac expense as well as 80 \u20ac coming in. Leave a box empty not to bound that side.",
    "Sur une d\u00e9pense remboursable, ce qu'on te rendra : au plus ce que tu as avanc\u00e9. Sur un pr\u00eat re\u00e7u, ce que tu rendras : au moins ce qu'on t'a remis \u2014 l'\u00e9cart est l'int\u00e9r\u00eat du pr\u00eat.":
      "On a reimbursable expense, what you will be paid back: at most what you advanced. On a loan received, what you will pay back: at least what you were given \u2014 the gap is the loan's interest.",
    "Nature contient": "Description contains",
    "\u2014 tous \u2014": "\u2014 all \u2014",
    // Le champ libre d'un projet. Le noyau, lui, traduit \u00ab Nature \u00bb par
    // "Description" (la colonne des op\u00e9rations) : deux mots fran\u00e7ais
    // diff\u00e9rents qui tombent sur le m\u00eame mot anglais, ce qui est sans
    // cons\u00e9quence \u2014 ils ne se croisent jamais dans un m\u00eame \u00e9cran.
    Description: "Description",
    "ex. h\u00f4tel": "e.g. hotel",
    Chercher: "Search",
    "Ajouter au projet (": "Add to project (",
    "Op\u00e9rations du projet \u2014": "Transactions in this project \u2014",
    "Aucun projet. Cr\u00e9e-en un, puis verses-y les op\u00e9rations d'un m\u00eame voyage ou d'un m\u00eame \u00e9v\u00e9nement.":
      "No project yet. Create one, then pour into it the transactions of a single trip or event.",
    Ouvrir: "Open",
    "Aucune op\u00e9ration.": "No transaction.",
    "Aucune op\u00e9ration dans ce projet.": "No transaction in this project.",
    Retirer: "Remove",
    "Projet cr\u00e9\u00e9": "Project created",
    "Projet modifi\u00e9": "Project updated",
    "Projet supprim\u00e9. Aucune op\u00e9ration n'a \u00e9t\u00e9 supprim\u00e9e.":
      "Project deleted. No transaction was deleted.",
    "Op\u00e9ration retir\u00e9e du projet (elle reste en base).":
      "Transaction removed from the project (it stays in the database).",
    "Donne un nom au projet.": "Give the project a name.",
    "{n} op\u00e9ration(s) propos\u00e9e(s). Celles d\u00e9j\u00e0 dans ce projet ne sont pas list\u00e9es.":
      "{n} transaction(s) offered. Those already in this project are not listed.",
    "{n} op\u00e9ration(s) ajout\u00e9e(s) au projet.": "{n} transaction(s) added to the project.",

    // ---------- Taux d'\u00e9pargne ----------
    "\u00c9pargne": "Savings",
    "Comptes d'\u00e9pargne": "Savings accounts",
    "Le taux est annuel, comme ta banque l'annonce. La fr\u00e9quence ne le change pas : elle dit \u00e0 quelles dates il s'applique, donc sur quel solde. Seuls les comptes d'\u00e9pargne sont ici.":
      "The rate is annual, as your bank quotes it. The frequency does not change it: it says on which dates it applies, and therefore on which balance. Only savings accounts are here.",
    "Ce que ces taux produisent est un": "What these rates produce is a",
    "calcul d'affichage": "display-only calculation",
    ": aucun int\u00e9r\u00eat n'est \u00e9crit en op\u00e9ration, aucun solde et aucun chiffre du dashboard n'en d\u00e9pend. C'est voulu \u2014 les int\u00e9r\u00eats changent \u00e0 chaque virement sur le compte et \u00e0 chaque jour qui passe, les inscrire en base ferait diverger l'application du relev\u00e9 de la banque.":
      ": no interest is written as a transaction, and no balance or dashboard figure depends on it. That is deliberate \u2014 interest changes with every transfer into the account and with every passing day, and writing it to the database would drift the app away from the bank statement.",
    "Aucun compte d'\u00e9pargne. Cr\u00e9e-en un depuis Param\u00e8tres \u2192 Comptes en choisissant le type \u00ab \u00e9pargne \u00bb, puis reviens ici.":
      "No savings account. Create one from Settings \u2192 Accounts by choosing the \u201csavings\u201d type, then come back here.",
    "Calculer jusqu'au": "Calculate up to",
    "Aujourd'hui par d\u00e9faut : \u00ab o\u00f9 j'en suis \u00bb. Une date future montre ce que \u00e7a rapportera si rien ne bouge d'ici l\u00e0.":
      "Today by default: \u201cwhere I stand\u201d. A future date shows what it will earn if nothing moves before then.",
    Recalculer: "Recalculate",
    "Taux annuel": "Annual rate",
    "Fr\u00e9quence de versement": "Payment frequency",
    "Rapporte depuis": "Earns since",
    "La date d'ouverture du compte, ou celle \u00e0 partir de laquelle il rapporte. Elle fixe aussi le calendrier des versements : un compte qui d\u00e9marre un 17 est r\u00e9mun\u00e9r\u00e9 le 17 de chaque mois. Laiss\u00e9e vide, le calcul part de la premi\u00e8re op\u00e9ration du compte \u2014 ce qui fausse un compte ouvert bien avant sa premi\u00e8re ligne import\u00e9e.":
      "The account's opening date, or the date from which it earns. It also sets the payment calendar: an account starting on the 17th is paid on the 17th of each month. Left empty, the calculation starts from the account's first transaction \u2014 which skews an account opened well before its first imported row.",
    "Journali\u00e8re": "Daily",
    "Retirer le taux": "Remove the rate",
    "Pas de taux : rien \u00e0 calculer.": "No rate: nothing to calculate.",
    "Aucun point de d\u00e9part : renseigne \u00ab Rapporte depuis \u00bb, ou attends la premi\u00e8re op\u00e9ration du compte.":
      "No starting point: fill in \u201cEarns since\u201d, or wait for the account's first transaction.",
    "Un taux et une fr\u00e9quence vont ensemble : renseigne les deux, ou aucun.":
      "A rate and a frequency go together: fill in both, or neither.",
    "Taux enregistr\u00e9": "Rate saved",
    "Taux retir\u00e9. Aucune op\u00e9ration n'a \u00e9t\u00e9 touch\u00e9e.":
      "Rate removed. No transaction was touched.",
    "P\u00e9riode": "Period",
    "Solde au d\u00e9part": "Balance at the start",
    "Versements": "Payments",
    Coefficient: "Coefficient",
    "Int\u00e9r\u00eats": "Interest",
    "Solde \u00e0 la fin": "Balance at the end",
    "Solde au": "Balance on",
    Mouvement: "Movement",
    "Afficher le d\u00e9tail du calcul": "Show the calculation in detail",
    "Les int\u00e9r\u00eats d'une p\u00e9riode sont vers\u00e9s avant les op\u00e9rations de son dernier jour : l'argent qui arrive un jour donn\u00e9 commence \u00e0 rapporter le lendemain.":
      "A period's interest is paid before that period's last-day transactions: money arriving on a given day starts earning the next day.",

    // ---------- Import de placements : doublons et ressemblances ----------
    "Chaque ligne jug\u00e9e identique (hors colonnes exclues, cf. Configuration du fichier) \u00e0 une ligne d\u00e9j\u00e0 import\u00e9e sous ce preset est affich\u00e9e ici, suivie en lecture seule de celle qu'elle double. Elles sont pr\u00e9-s\u00e9lectionn\u00e9es pour \u00eatre supprim\u00e9es d'un clic \u2014 d\u00e9coche-en une pour l'importer quand m\u00eame (deux achats identiques le m\u00eame jour sont un doublon d\u00e9tect\u00e9 l\u00e9gitime).":
      "Every row judged identical (excluded columns aside, see File configuration) to a row already imported under this preset appears here, followed read-only by the one it duplicates. They are pre-selected to be removed in one click \u2014 untick one to import it anyway (two identical purchases on the same day are a legitimate detected duplicate).",
    "Transferts d\u00e9j\u00e0 connus \u2014": "Transfers already known \u2014",
    "Ces transferts ressemblent \u00e0 un virement d\u00e9j\u00e0 enregistr\u00e9 : m\u00eame montant, m\u00eames comptes, \u00e0 quelques jours pr\u00e8s. C'est normal \u2014 le m\u00eame mouvement figure sur le relev\u00e9 du courtier":
      "These transfers look like a transfer already recorded: same amount, same accounts, within a few days. That is normal \u2014 the same movement appears on the broker's statement",
    "sur celui du compte courant. Seuls les virements qui touchent le compte de ce preset sont compar\u00e9s. Rien n'est bloqu\u00e9 ni pr\u00e9-s\u00e9lectionn\u00e9 : toi seul sais si tu as vraiment fait deux fois le mouvement. Chaque ligne est suivie de ce \u00e0 quoi elle ressemble.":
      "on the current account's. Only transfers touching this preset's account are compared. Nothing is blocked or pre-selected: only you know whether you really made the movement twice. Each row is followed by what it looks like.",
    "Ressemble \u00e0 :": "Looks like:",
    "d\u00e9j\u00e0 en base": "already in the database",
    "virement d\u00e9j\u00e0 enregistr\u00e9": "transfer already recorded",
    "du m\u00eame fichier": "of the same file",
    "le m\u00eame jour": "on the same day",

    // ---------- Import de placements : le compte en face d'une r\u00e8gle ----------
    "Une ligne de compte-titres n'a pas de cat\u00e9gorie : un mouvement de titres n'en porte pas. Un transfert, lui, touche deux comptes et le relev\u00e9 n'en nomme qu'un \u2014 la r\u00e8gle peut donc d\u00e9signer le second.":
      "A securities-account row has no category: a securities movement carries none. A transfer, however, touches two accounts and the statement names only one \u2014 so the rule can designate the second.",
    "L'autre compte : celui d'o\u00f9 vient l'argent vers\u00e9, ou celui o\u00f9 va l'argent retir\u00e9. Le sens se d\u00e9duit du signe du montant. Sans lui, la ligne est \u00e0 compl\u00e9ter \u00e0 la main dans l'aper\u00e7u.":
      "The other account: where the money paid in comes from, or where the money taken out goes. The direction follows the sign of the amount. Without it, the row must be completed by hand in the preview.",
    avec: "with",
    et: "and",
    "en face": "facing",

    // ---------- Titres suivis ----------
    "Nom du courtier :": "Broker's name:",
    "renomm\u00e9": "renamed",
    "Changer le nom affich\u00e9 (le nom du courtier ne bouge pas)":
      "Change the displayed name (the broker's name does not move)",
    "Nom \u00e0 afficher pour \u00ab {nom} \u00bb (laisse vide pour revenir au nom du courtier)":
      "Name to display for \u201c{nom}\u201d (leave empty to go back to the broker's name)",
    "Titre renomm\u00e9": "Security renamed",
    "Nom du courtier r\u00e9tabli": "Broker's name restored",
    "Afficher le lien de cotation": "Show the quotation link",
    "Cours relu en ligne": "Price read online",

    // ---------- Taux d'\u00e9pargne : la fen\u00eatre ----------
    "G\u00e9rer les taux d'int\u00e9r\u00eat": "Manage interest rates",
    ": aucun int\u00e9r\u00eat n'est \u00e9crit en op\u00e9ration, aucun solde et aucun chiffre du dashboard n'en d\u00e9pend.":
      ": no interest is written as a transaction, and no balance or dashboard figure depends on it.",

    // ---------- Import de placements : photographie du compte ----------
    "Le fichier contient": "The file contains",
    "Une liste d'op\u00e9rations rejoue l'histoire du compte : une ligne par achat, vente ou transfert, chacune dat\u00e9e. Une photographie dit ce que tu d\u00e9tiens aujourd'hui : une ligne par titre, sa quantit\u00e9, son prix de revient. La photographie \u00e9vite de r\u00e9importer dix ans de mouvements.":
      "A list of transactions replays the account's history: one row per purchase, sale or transfer, each dated. A snapshot says what you hold today: one row per holding, its quantity, its cost price. The snapshot saves re-importing ten years of movements.",
    "Une liste d'op\u00e9rations (achats, ventes, transferts)":
      "A list of transactions (purchases, sales, transfers)",
    "Une photographie du compte (titres d\u00e9tenus)":
      "A snapshot of the account (securities held)",
    "Date de la photographie": "Snapshot date",
    "Le jour o\u00f9 la photographie a \u00e9t\u00e9 prise : c'est de cette date que l'app te consid\u00e8re d\u00e9tenteur de ces titres. Aujourd'hui par d\u00e9faut.":
      "The day the snapshot was taken: from that date on, the app considers you hold these securities. Today by default.",
    "Titres d\u00e9tenus \u2014": "Securities held \u2014",
    "Chaque ligne devient un": "Each row becomes a",
    "dat\u00e9 du jour de la photographie : c'est ainsi qu'une d\u00e9tention existe dans l'application, et c'est ce qui rend justes d'un coup la valorisation et les plus-values. Les esp\u00e8ces du compte baissent donc du total investi \u2014 pense \u00e0 poser son solde initial en cons\u00e9quence.":
      "dated the day of the snapshot: that is how a holding exists in the application, and it is what makes the valuation and the gains right at once. The account's cash therefore drops by the total invested \u2014 remember to set its opening balance accordingly.",
    "Montant investi": "Amount invested",
    // Le mot en gras au milieu de la phrase de la section « Titres détenus ».
    achat: "purchase",
    "Cours d\u00e9duit": "Price inferred",
    "Quantit\u00e9 d\u00e9tenue": "Quantity held",
    "Prix de revient unitaire": "Unit cost price",
    "Valorisation actuelle": "Current valuation",
    "d\u00e9j\u00e0": "already",
    "Ce compte d\u00e9tient d\u00e9j\u00e0 ce titre : importer cette ligne s'ajoutera \u00e0 ce qui s'y trouve.":
      "This account already holds this security: importing this row will add to what is there.",
    "Colonnes remises \u00e0 celles de ce type de fichier. Enregistre pour confirmer.":
      "Columns reset to those of this kind of file. Save to confirm.",
    "Ce fichier est-il une PHOTOGRAPHIE du compte (une ligne par titre d\u00e9tenu) ?\n\nOK : photographie.\nAnnuler : liste d'op\u00e9rations (achats, ventes, transferts).":
      "Is this file a SNAPSHOT of the account (one row per security held)?\n\nOK: snapshot.\nCancel: list of transactions (purchases, sales, transfers).",
    "Le nombre de titres D\u00c9TENUS au moment de la photographie.\n\nC'est cette quantit\u00e9 qui sera enregistr\u00e9e : l'application ne sait pas comment tu y es arriv\u00e9, seulement ce que tu d\u00e9tiens.":
      "The number of securities HELD at the moment of the snapshot.\n\nThat is the quantity that will be recorded: the application does not know how you got there, only what you hold.",
    "Le prix de revient d'UN titre (PRU) \u2014 ce qu'il t'a co\u00fbt\u00e9 en moyenne, frais compris.\n\nUnitaire, et non le montant total investi : c'est ce qu'\u00e9crivent la plupart des courtiers, et le total s'en d\u00e9duit (PRU \u00d7 quantit\u00e9). Si ton relev\u00e9 donne le montant total, divise-le avant d'importer \u2014 sinon chaque position sera multipli\u00e9e par sa quantit\u00e9.":
      "The cost price of ONE security (average unit cost) \u2014 what it cost you on average, fees included.\n\nPer unit, not the total amount invested: that is what most brokers write, and the total follows from it (unit cost \u00d7 quantity). If your statement gives the total, divide it before importing \u2014 otherwise each position will be multiplied by its quantity.",
    "Ce que la ligne vaut aujourd'hui, tous titres confondus. La seule colonne enti\u00e8rement facultative.\n\nElle ne cr\u00e9e aucune d\u00e9tention : elle sert \u00e0 en d\u00e9duire le COURS du titre (valorisation \u00f7 quantit\u00e9), qui n'a pas de colonne \u00e0 lui dans ce genre d'export. Sans elle, le cours reste celui d\u00e9j\u00e0 connu, \u00e0 saisir \u00e0 la main.":
      "What the row is worth today, all securities together. The only entirely optional column.\n\nIt creates no holding: it serves to infer the security's PRICE (valuation \u00f7 quantity), which has no column of its own in this kind of export. Without it, the price stays the one already known, to be entered by hand.",
  },
};

// Messages du serveur qui portent une partie variable (un nom de compte, un
// nombre, un libellé lu dans un relevé) : la correspondance exacte ne peut pas
// les retrouver. Le groupe capturé est réinjecté tel quel — c'est de la donnée,
// elle ne se traduit pas. Ordre significatif : le premier motif qui accroche
// gagne, donc du plus précis au plus général.
const MOTIFS_SERVEUR = [
  [/^Monnaie du compte (.+) introuvable$/, "Currency of account $1 not found"],
  [/^Monnaie (.+) introuvable$/, "Currency $1 not found"],
  [/^Opération (.+) introuvable$/, "Transaction $1 not found"],
  [
    /^Fichier illisible en tant que base SQLite : (.+)$/,
    "File unreadable as a SQLite database: $1",
  ],
  [/^Fichier illisible : (.+)$/, "Unreadable file: $1"],
  [
    /^Impossible de mettre à jour le schéma de (.+) : (.+)$/,
    "Could not upgrade the schema of $1: $2",
  ],
  [
    /^Ce compte porte déjà des opérations en (.+) : supprime-les avant de retirer cette monnaie\.$/,
    "This account already carries transactions in $1: delete them before removing this currency.",
  ],
  [
    /^Un même mot-clé ne peut pas désigner deux (.+) différents : (.+)$/,
    "The same keyword cannot designate two different $1: $2",
  ],
  [/^Propriétés invalides : (.+)$/, "Invalid properties: $1"],
  [/^Propriétés obligatoires manquantes : (.+)$/, "Missing required properties: $1"],
  [
    /^Le compte « (.+) » ne porte pas cette monnaie \(possibles : (.+)\)\.$/,
    "Account “$1” does not hold this currency (possible: $2).",
  ],
  [
    /^Le compte (.+) « (.+) » ne porte pas la monnaie de cette ligne \(possibles : (.+)\)$/,
    "The $1 account “$2” does not hold this row's currency (possible: $3)",
  ],
  [
    /^Le compte (.+) « (.+) » ne porte pas cette monnaie \(possibles : (.+)\)\.$/,
    "The $1 account “$2” does not hold this currency (possible: $3).",
  ],
  [
    /^Le type « (.+) » est géré par la page Placements financiers et ne peut pas être posé ici\.$/,
    "The “$1” type is managed by the Investments page and cannot be set here.",
  ],
  [
    /^Le type « (.+) » ne peut pas être posé par une règle : les achats\/ventes de titres se saisissent depuis la page Placements financiers\.$/,
    "The “$1” type cannot be set by a rule: security purchases and sales are entered from the Investments page.",
  ],
  [
    /^Le total réglé \((.+)\) dépasse le montant de l'opération de règlement \((.+)\)$/,
    "The total settled ($1) exceeds the amount of the settling transaction ($2)",
  ],
  [
    /^operations_remboursees n'est valide que pour les types (.+)$/,
    "operations_remboursees is only valid for the types $1",
  ],
  [
    /^L'opération (.+) ne peut pas être réglée par une opération de type '(.+)'$/,
    "Transaction $1 cannot be settled by a transaction of type '$2'",
  ],
  [
    /^L'opération (.+) n'est pas dans la même monnaie que ce règlement : l'app ne convertit rien, règle-la depuis une opération de sa monnaie\.$/,
    "Transaction $1 is not in the same currency as this settlement: the app converts nothing, settle it from a transaction in its own currency.",
  ],
  [
    /^Le montant réglé pour l'opération (.+) dépasse le montant dû \((.+)\)$/,
    "The amount settled for transaction $1 exceeds the amount owed ($2)",
  ],
  [
    /^« (.+) » est coté en (.+), monnaie que le compte « (.+) » ne porte pas : ajoute-la au compte \(Paramètres > Comptes\) ou choisis un autre titre\.$/,
    "“$1” is quoted in $2, a currency account “$3” does not hold: add it to the account (Settings > Accounts) or choose another security.",
  ],
  [
    /^Quantité insuffisante : (.+) « (.+) » détenu\(s\) sur ce compte, (.+) demandé\(s\)$/,
    "Not enough held: $1 “$2” on this account, $3 requested",
  ],
  [/^champ inconnu : (.+) \(attendus : (.+)\)$/, "unknown field: $1 (expected: $2)"],
  [
    /^Import bloqué : (.+) ligne\(s\) portent des frais dans une monnaie qui n'est ni celle du montant ni celle du montant envoyé \(ligne (.+)\)\. Retire la colonne « Frais » de la configuration avancée, ou corrige la colonne de devise qui la qualifie\.$/,
    "Import blocked: $1 row(s) carry fees in a currency that is neither the amount's nor the amount sent's (row $2). Remove the “Fees” column from the advanced configuration, or correct the currency column that qualifies it.",
  ],
  [/^monnaie « (.+) » non résolue$/, "currency “$1” not resolved"],
  [
    /^sens « (.+) » non reconnu \(attendus : (.+)\)$/,
    "direction “$1” not recognised (expected: $2)",
  ],
  [/^état « (.+) » non reconnu \(attendus : (.+)\)$/, "status “$1” not recognised (expected: $2)"],
  [
    /^frais en « (.+) » : ce n'est pas la monnaie (.+) à laquelle ils devraient s'appliquer$/,
    "fees in “$1”: that is not the $2 currency they should apply to",
  ],
];

