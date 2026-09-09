/**
 * Chargement des extensions côté navigateur.
 *
 * PENDANT FRONTEND de app/extensions.py. Le serveur dit quelles extensions
 * sont présentes et lesquelles sont actives (GET /extensions) ; ce module va
 * chercher leurs fichiers, injecte leur écran dans la page et leur donne un
 * point d'accroche pour s'enregistrer.
 *
 * DÉROULÉ, dans cet ordre et pas un autre :
 *
 *   1. GET /extensions          -> la liste et l'état de chacune
 *   2. pour chaque extension ACTIVE : CSS, puis fragment HTML, puis JS
 *   3. le JS appelle BudgetApp.extensions.enregistrer(...) en s'exécutant
 *   4. l'entrée de navigation apparaît
 *
 * Le HTML AVANT le JS : le script d'une extension accroche ses écouteurs sur
 * les éléments de son écran dès son exécution ; l'inverse le ferait travailler
 * sur une page où rien de tout cela n'existe encore.
 *
 * RIEN N'EST CHARGÉ D'UNE EXTENSION INACTIVE — ni sa feuille de style, ni son
 * écran, ni une ligne de son script. « Inactive » doit vouloir dire « ne
 * tourne pas », pas « tourne mais son bouton est caché » : depuis qu'une
 * extension peut ouvrir une connexion sortante (« lecture-de-cours »), la
 * nuance a cessé d'être théorique.
 *
 * Les fichiers sont donc chargés AU MOMENT OÙ ON L'ALLUME (cf.
 * `appliquerActivation`), ce qui évite quand même le rechargement de la page —
 * la propriété à laquelle tenait le chargement systématique d'avant.
 *
 * L'ÉTEINDRE, EN REVANCHE, NE DÉCHARGE RIEN : on ne retire pas un script d'une
 * page. Ses routes répondent 404 (`exiger_extension`), son bouton disparaît, et
 * son code dort jusqu'au prochain lancement où il ne sera plus chargé du tout.
 *
 * TOUT ÉCHEC EST LOCAL À UNE EXTENSION : une extension dont le JS casse ne
 * doit pas empêcher les autres de se charger, ni l'application de s'ouvrir.
 */

// Espace de noms unique exposé aux extensions. Volontairement minuscule : plus
// il offre de choses, plus il devient difficile de le faire évoluer sans
// casser les extensions écrites contre lui.
window.BudgetApp = window.BudgetApp || {};

const extensionsChargees = new Map(); // id -> { manifeste, chargeur }

window.BudgetApp.extensions = {
  /**
   * Appelé par le JS d'une extension au moment où il s'exécute.
   *
   * `chargeur` est rappelé à chaque fois que l'utilisateur ouvre l'écran de
   * l'extension — comme loadDashboard() ou loadOperations() pour les écrans
   * du noyau, et pour la même raison : les données ont pu changer depuis la
   * dernière visite.
   */
  enregistrer(id, { chargeur } = {}) {
    const entree = extensionsChargees.get(id);
    if (!entree) {
      console.warn(`Extension inconnue à l'enregistrement : ${id}`);
      return;
    }
    entree.chargeur = chargeur || null;
  },

  /** Les extensions présentes, actives ou non (lecture seule). */
  liste() {
    return [...extensionsChargees.values()].map((e) => e.manifeste);
  },

  /** Vrai si l'extension est présente ET activée. */
  estActive(id) {
    const entree = extensionsChargees.get(id);
    return Boolean(entree && entree.manifeste.actif);
  },

  /**
   * Ouvre l'écran d'une extension. Rend false si l'extension n'a pas d'écran
   * à ouvrir : l'appelant (switchSection) sait alors que la section demandée
   * ne le concerne pas.
   */
  async ouvrir(section) {
    return appelerChargeur((nav) => nav.type === "page" && nav.section === section);
  },

  /**
   * Pendant de `ouvrir` pour les SOUS-PAGES de Paramètres (« Base de
   * données » en version développeur). Séparé parce que les deux espaces de
   * noms sont indépendants : rien n'interdit qu'un écran principal et une
   * sous-page de réglages portent le même nom.
   */
  async ouvrirSousPage(sousSection) {
    return appelerChargeur(
      (nav) =>
        (nav.type === "parametres" && `parametres-${nav.sous_section}` === sousSection) ||
        // Un ONGLET posé dans un écran du noyau autre que Paramètres (la page
        // des comptes) : même mécanique, l'écran hôte le nomme.
        (nav.type === "onglet" &&
          `${nav.hote_section}-${nav.sous_section}` === sousSection) ||
        // Une GREFFE n'a pas de sous-page à elle : elle complète celle du
        // noyau qu'elle nomme, et se recharge donc quand celle-là s'ouvre.
        (nav.type === "greffe" && nav.hote === sousSection)
    );
  },
};

/** Appelle le chargeur de la première extension dont la navigation correspond. */
async function appelerChargeur(correspond) {
  const entree = [...extensionsChargees.values()].find(
    (e) => e.manifeste.navigation && correspond(e.manifeste.navigation)
  );
  if (!entree || !entree.chargeur) return false;
  try {
    await entree.chargeur();
  } catch (err) {
    console.error(`Extension ${entree.manifeste.id} : échec du chargement`, err);
  }
  return true;
}

function urlFichier(id, fichier) {
  return `/extensions/${encodeURIComponent(id)}/fichiers/${fichier}`;
}

function chargerCss(id, fichier) {
  return new Promise((resolve) => {
    const lien = document.createElement("link");
    lien.rel = "stylesheet";
    lien.href = urlFichier(id, fichier);
    // On résout dans les deux cas : une feuille de style manquante dégrade
    // l'apparence, elle n'empêche pas la fonctionnalité de marcher.
    lien.onload = resolve;
    lien.onerror = resolve;
    document.head.appendChild(lien);
  });
}

function chargerJs(id, fichier) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = urlFichier(id, fichier);
    script.onload = resolve;
    script.onerror = () => reject(new Error(`script introuvable : ${fichier}`));
    document.body.appendChild(script);
  });
}

/**
 * Injecte l'écran d'une extension dans <main>, comme une section de plus.
 *
 * Le fragment fourni par l'extension est un `<section id="section-...">`
 * complet : il se comporte donc exactement comme les écrans du noyau, y
 * compris pour switchSection qui les montre et les cache par cette classe.
 */
async function injecterHtml(id, fichier, navigation) {
  const reponse = await fetch(urlFichier(id, fichier));
  if (!reponse.ok) throw new Error(`fragment introuvable : ${fichier}`);
  const html = await reponse.text();
  // Trois hôtes possibles, selon ce que l'extension déclare (cf.
  // extensions/README.md) : un écran principal est une <section> de plus dans
  // <main> ; une sous-page de réglages, une .sous-section de plus dans la
  // section Paramètres ; une GREFFE, un bloc posé DANS une sous-page du noyau.
  const greffe = navigation && navigation.type === "greffe";
  const hote = greffe
    ? document.getElementById(`sous-section-${navigation.hote}`)
    : navigation && navigation.type === "parametres"
      ? document.getElementById("section-parametres")
      : navigation && navigation.type === "onglet"
        ? document.getElementById(`section-${navigation.hote_section}`)
        : document.querySelector("main");
  // En pratique seule une greffe peut manquer d'hôte (`<main>` et la section
  // Paramètres sont toujours là) : c'est le cas d'une greffe qui nomme une
  // sous-page inexistante, et le dire vaut mieux que de poser son bloc nulle
  // part.
  if (!hote) throw new Error(`hôte introuvable : ${greffe ? navigation.hote : "?"}`);
  // EN TÊTE pour une greffe : elle complète une page existante, dont le
  // contenu du noyau doit rester en dessous. C'est la disposition que l'écran
  // avait avant que les règles ne deviennent une extension — les règles
  // s'écrivent, les correspondances se constatent.
  const position = greffe ? "afterbegin" : "beforeend";
  // insertAdjacentHTML plutôt que innerHTML += : réécrire tout le contenu de
  // l'hôte détruirait et recréerait les écrans du noyau, et avec eux tous les
  // écouteurs que app.js y a déjà posés.
  hote.insertAdjacentHTML(position, html);
  const pose = greffe ? hote.firstElementChild : hote.lastElementChild;
  // Une greffe se montre et se cache avec sa case, contrairement aux deux
  // autres formes dont c'est le bouton de navigation qui disparaît : elle n'en
  // a pas, elle vit dans la page d'un autre.
  if (greffe) pose.dataset.extensionGreffe = id;
  // Un ONGLET a bien un bouton, mais son volet vit dans la <section> du noyau :
  // masquer le bouton laisserait le volet affiché si c'est lui qui était ouvert
  // au moment où l'extension s'éteint.
  if (navigation && navigation.type === "onglet") pose.dataset.extensionOnglet = id;

  // TRADUIRE LE FRAGMENT QU'ON VIENT DE POSER. app.js traduit `document.body`
  // au tout début, bien avant que les extensions ne soient lues : sans ce
  // rappel, un écran d'extension resterait en français dans une application
  // passée à l'anglais. La condition de sûreté de traduireDomStatique tient
  // toujours — le fragment sort d'un fichier de l'extension, aucune donnée de
  // l'utilisateur n'y a encore été rendue.
  traduireDomStatique(pose);
}

/**
 * Ajoute l'entrée de navigation d'une extension, à sa position déclarée.
 *
 * Le bouton est créé même pour une extension DÉSACTIVÉE, puis simplement
 * masqué : basculer l'extension n'a plus qu'à changer un `display`, sans
 * reconstruire la barre ni recharger la page.
 */
function ajouterNavigation(manifeste) {
  const navigation = manifeste.navigation;
  if (!navigation) return;

  // Une greffe n'ajoute AUCUN bouton : son contenu vit dans la page d'un autre,
  // et un onglet de plus qui mènerait au même endroit tromperait sur ce qu'il
  // ouvre. Elle en RENOMME un, en revanche — une page qui porte désormais deux
  // choses ne peut plus s'appeler par une seule d'entre elles.
  if (navigation.type === "greffe") {
    renommerOngletHote(navigation, manifeste.actif);
    return;
  }

  // `bouton: false` : un écran qui n'a PAS sa place dans la barre du haut.
  // C'est le cas de « Import de placements », qui est une action de la page
  // Placements et s'ouvre depuis elle — un onglet principal de plus, à côté de
  // celui qu'il complète, laisserait croire à deux fonctionnalités séparées.
  // L'extension reste de type `page` : elle a bien un écran à elle, et c'est
  // par ce type que `BudgetApp.extensions.ouvrir` sait le lui rendre.
  if (navigation.bouton === false) return;

  const bouton = document.createElement("button");
  bouton.type = "button";
  bouton.dataset.extension = manifeste.id;
  // `navigation.icone` : le nom d'un fichier de frontend/img, posé DEVANT le
  // libellé — c'est ainsi que les onglets du noyau portent le leur (cf.
  // .onglet-logo dans style.css). Facultatif : sans lui, le bouton n'a que son
  // mot, comme avant.
  if (navigation.icone) {
    const logo = document.createElement("img");
    logo.className = "onglet-logo";
    // Encodé : le nom vient d'un fichier de l'extension, pas de l'app.
    logo.src = `/img/${encodeURIComponent(navigation.icone)}`;
    // `alt` vide, et pas le nom de l'onglet : le libellé est juste à côté, un
    // lecteur d'écran le dirait deux fois.
    logo.alt = "";
    logo.width = 15;
    logo.height = 15;
    bouton.appendChild(logo);
  }
  // Un NŒUD DE TEXTE et non `textContent` : celui-ci effacerait l'image qu'on
  // vient de poser. C'est aussi ce que la traduction du DOM statique sait
  // remplacer sans toucher au reste du bouton.
  bouton.appendChild(document.createTextNode(t(navigation.libelle)));
  bouton.style.display = manifeste.actif ? "" : "none";

  // Un ONGLET DANS UN ÉCRAN DU NOYAU (autre que Paramètres). Le clic est pris
  // en charge par les gestionnaires délégués de app.js, exactement comme un
  // onglet de réglages — c'est le même `data-sous-section`, préfixé par l'écran
  // hôte au lieu de « parametres ».
  if (navigation.type === "onglet") {
    bouton.dataset.sousSection = `${navigation.hote_section}-${navigation.sous_section}`;
    const barre = document.getElementById(`${navigation.hote_section}-sous-nav`);
    if (!barre) throw new Error(`écran hôte introuvable : ${navigation.hote_section}`);
    barre.appendChild(bouton);
    renommerSectionHote(navigation, manifeste.actif);
    majBarreOnglets(navigation.hote_section);
    return;
  }

  if (navigation.type === "parametres") {
    // Onglet de réglages : le clic est pris en charge par les gestionnaires
    // délégués de app.js (affichage ET chargement), exactement comme pour un
    // onglet du noyau — rien à câbler ici.
    bouton.dataset.sousSection = `parametres-${navigation.sous_section}`;
    // La barre de Paramètres a deux groupes (cf. index.html) : à gauche ce que
    // l'app manipule, à droite ce qui la règle. Une extension dit de quel côté
    // elle tombe par `navigation.groupe` ; sans rien dire, elle va à DROITE —
    // une extension est de l'outillage jusqu'à preuve du contraire, et
    // « Monnaies », qui décrit bien un objet du modèle, se déclare.
    const groupe =
      document.getElementById(
        navigation.groupe === "gauche"
          ? "parametres-sous-nav-gauche"
          : "parametres-sous-nav-droite"
      ) || document.getElementById("parametres-sous-nav");
    groupe.appendChild(bouton);
    return;
  }

  const barre = document.querySelector("header nav");
  bouton.dataset.section = navigation.section;
  bouton.addEventListener("click", () => switchSection(navigation.section));

  // `position` est un rang souhaité, pas un index de tableau : on l'insère
  // avant le premier bouton du noyau de rang supérieur, et à la fin si aucun.
  // Un rang absent ou en doublon ne casse donc rien, il place seulement le
  // bouton un cran plus loin.
  const boutons = [...barre.querySelectorAll("button")];
  const rang = Number(navigation.position);
  const suivant = Number.isFinite(rang) ? boutons[rang] : null;
  barre.insertBefore(bouton, suivant || null);
}

/**
 * Donne à l'onglet du noyau le nom que la greffe lui impose, ou le lui rend.
 *
 * Le libellé d'origine est gardé au premier passage : éteindre l'extension
 * doit rendre la page telle qu'elle serait sans elle, nom de l'onglet compris.
 */
function renommerOngletHote(navigation, actif) {
  const bouton = document.querySelector(
    `#parametres-sous-nav button[data-sous-section="${navigation.hote}"]`
  );
  if (!bouton || !navigation.libelle) return;
  if (bouton.dataset.libelleNoyau === undefined) {
    bouton.dataset.libelleNoyau = bouton.textContent;
  }

  // `textContent` EFFACERAIT LE LOGO en même temps que le mot : le bouton est
  // reconstruit pièce par pièce, comme le fait `ajouterNavigation` pour les
  // onglets qu'une extension ajoute. L'image d'abord, le texte ensuite —
  // l'ordre du DOM est celui de la lecture (cf. .onglet-logo dans style.css).
  bouton.textContent = "";
  if (actif && navigation.icone) {
    const logo = document.createElement("img");
    logo.className = "onglet-logo";
    // Encodé : le nom vient d'un fichier de l'extension, pas de l'app.
    logo.src = `/img/${encodeURIComponent(navigation.icone)}`;
    // `alt` vide, et pas le nom de l'onglet : le libellé est juste à côté, un
    // lecteur d'écran le dirait deux fois.
    logo.alt = "";
    logo.width = 15;
    logo.height = 15;
    bouton.appendChild(logo);
  }
  // ÉTEINTE, LA GREFFE REND L'ONGLET TEL QUE LE NOYAU L'ÉCRIT : son nom
  // d'origine, et aucun logo — celui-ci appartient à l'extension, pas à la
  // page qu'elle emprunte.
  bouton.appendChild(
    document.createTextNode(actif ? t(navigation.libelle) : bouton.dataset.libelleNoyau)
  );
}

/**
 * Donne à l'écran du noyau le nom que l'onglet d'une extension lui impose, ou
 * le lui rend.
 *
 * MÊME PRINCIPE QUE `renommerOngletHote` pour les greffes, un cran plus haut :
 * une page qui porte désormais deux onglets ne peut plus s'appeler par l'un
 * d'eux. « Vue globale des comptes » descend donc d'un cran — il reste le nom
 * de l'onglet qui l'affiche, écrit une fois pour toutes dans index.html — et la
 * page prend le nom que l'extension lui donne.
 *
 * Le libellé d'origine est gardé au premier passage : éteindre l'extension doit
 * rendre la page telle qu'elle serait sans elle, nom compris.
 */
function renommerSectionHote(navigation, actif) {
  if (!navigation.section_libelle) return;
  const cibles = [
    document.querySelector(`header nav button[data-section="${navigation.hote_section}"]`),
    document.querySelector(`#section-${navigation.hote_section} > h2`),
  ];
  cibles.forEach((element) => {
    if (!element) return;
    if (element.dataset.libelleNoyau === undefined) {
      element.dataset.libelleNoyau = element.textContent;
    }
    element.textContent = actif ? t(navigation.section_libelle) : element.dataset.libelleNoyau;
  });
}

/**
 * Montre la barre d'onglets d'un écran du noyau dès qu'elle offre un choix.
 *
 * Un onglet seul ne choisit rien : il répéterait le titre de la page, une ligne
 * plus bas. La barre reste donc masquée dans l'application nue et n'apparaît
 * qu'à partir de deux onglets VISIBLES — une extension éteinte ne compte pas,
 * son bouton étant masqué.
 */
function majBarreOnglets(hoteSection) {
  const barre = document.getElementById(`${hoteSection}-sous-nav`);
  if (!barre) return;
  const visibles = [...barre.querySelectorAll("button[data-sous-section]")].filter(
    (b) => b.style.display !== "none"
  );
  barre.style.display = visibles.length > 1 ? "" : "none";
}

/**
 * Ramène l'écran hôte sur son premier onglet.
 *
 * Appelé quand l'extension qui apportait l'onglet OUVERT s'éteint : son volet
 * vient d'être masqué, et laisser la page sur un onglet qui n'affiche plus rien
 * donnerait un écran vide sans dire pourquoi.
 */
function reprendreLePremierOnglet(hoteSection) {
  const barre = document.getElementById(`${hoteSection}-sous-nav`);
  const premier = barre && barre.querySelector("button[data-sous-section]");
  if (!premier) return;
  const section = document.getElementById(`section-${hoteSection}`);
  barre
    .querySelectorAll("button[data-sous-section]")
    .forEach((b) => b.classList.toggle("active", b === premier));
  section
    .querySelectorAll(":scope > .sous-section")
    .forEach((volet) =>
      volet.classList.toggle("active", volet.id === `sous-section-${premier.dataset.sousSection}`)
    );
}

function majVisibiliteNavigation(id, actif) {
  const aMoi = document.querySelectorAll(
    `button[data-extension="${id}"], [data-extension-greffe="${id}"], ` +
      `[data-extension-onglet="${id}"]`
  );
  aMoi.forEach((element) => (element.style.display = actif ? "" : "none"));

  // ÉTEINTE ALORS QU'UN DE SES VOLETS ÉTAIT OUVERT : il vient d'être masqué, et
  // laisser la page dessus donnerait un écran vide sans dire pourquoi. L'écran
  // hôte se lit sur le volet lui-même plutôt que sur le manifeste : une
  // extension peut n'avoir AUCUNE navigation déclarée et commander tout de même
  // des volets écrits dans index.html — c'est le cas de « prets », dont les deux
  // onglets de la page Opérations appartiennent au noyau.
  if (!actif) {
    aMoi.forEach((element) => {
      if (!element.classList.contains("active")) return;
      const section = element.closest("section");
      if (section) reprendreLePremierOnglet(section.id.replace(/^section-/, ""));
    });
  }

  // Une greffe éteinte doit aussi rendre son nom à l'onglet qu'elle avait
  // rebaptisé, sans quoi « Règles » resterait affiché sur une page qui n'en
  // porte plus.
  const entree = extensionsChargees.get(id);
  const navigation = entree && entree.manifeste.navigation;
  if (navigation && navigation.type === "greffe") renommerOngletHote(navigation, actif);
  if (navigation && navigation.type === "onglet") {
    renommerSectionHote(navigation, actif);
    majBarreOnglets(navigation.hote_section);
  }
}

/**
 * Charge les fichiers d'une extension : CSS, puis écran, puis script.
 *
 * Appelée au démarrage pour les extensions déjà allumées, et à la volée quand
 * l'utilisateur en active une (fenêtre de lancement ou Paramètres). Le même
 * chemin dans les deux cas : allumer une extension doit produire exactement ce
 * qu'aurait produit un redémarrage, sans le redémarrage.
 */
async function chargerFichiers(manifeste) {
  const fichiers = manifeste.frontend || {};
  for (const css of fichiers.css || []) {
    await chargerCss(manifeste.id, css);
  }
  if (fichiers.html) {
    await injecterHtml(manifeste.id, fichiers.html, manifeste.navigation);
    ajouterNavigation(manifeste);
  }
  for (const js of fichiers.js || []) {
    await chargerJs(manifeste.id, js);
  }
}

/**
 * Applique une bascule décidée par l'utilisateur, sans recharger la page.
 *
 * Trois choses, et l'ordre compte : l'état retenu ici (c'est lui que lisent
 * les extensions via `estActive`), les fichiers si c'est un premier
 * allumage, la barre de navigation ensuite.
 *
 * Rend `false` si l'allumage a échoué (fichier manquant) : l'appelant peut
 * alors le dire, plutôt que d'afficher un bouton qui n'ouvre rien.
 */
async function appliquerActivation(id, actif) {
  const entree = extensionsChargees.get(id);
  if (!entree) return false;
  entree.manifeste.actif = actif;

  if (actif && !entree.fichiersCharges) {
    try {
      await chargerFichiers(entree.manifeste);
      entree.fichiersCharges = true;
      // POUR LES GREFFES. Une extension qui se pose sur l'écran d'une autre
      // (« lecture-de-cours » sur « placements ») n'a d'hôte que si celui-ci a
      // été chargé avant elle. Allumer les deux dans le désordre au cours
      // d'une même session est parfaitement possible : cet événement lui donne
      // le moyen de s'accrocher en retard, au lieu d'attendre un redémarrage.
      document.dispatchEvent(
        new CustomEvent("budgetapp:extension-chargee", { detail: { id } })
      );
    } catch (err) {
      console.error(`Extension ${id} : ${err.message}`);
      entree.manifeste.actif = false;
      return false;
    }
  }
  majVisibiliteNavigation(id, actif);
  return true;
}

window.BudgetApp.extensions.majVisibilite = majVisibiliteNavigation;
window.BudgetApp.extensions.appliquerActivation = appliquerActivation;

// Extensions actuellement annoncées par la fenêtre : acquittées auprès du
// serveur à sa fermeture, quel que soit le geste qui l'a fermée.
let extensionsAnnoncees = [];

/**
 * Annonce les extensions trouvées au lancement, UNE SEULE FOIS CHACUNE, et
 * propose de les allumer.
 *
 * POURQUOI CETTE ANNONCE EXISTE. L'application est livrée SANS aucune
 * extension : le dossier `extensions/` arrive vide, et c'est l'utilisateur qui
 * y dépose ce qu'il télécharge. En trouver au démarrage n'est donc jamais
 * banal — c'est la confirmation que ce qu'il vient d'installer a bien été vu,
 * et le seul moment où l'on peut le lui dire avant qu'il aille le chercher.
 *
 * CE N'EST PAS UNE CONFIRMATION, C'EST UNE DEMANDE. Une extension trouvée est
 * INACTIVE (cf. app/extensions.py::est_active) : cette fenêtre est l'endroit
 * où on l'allume, en passant son menu sur « Activée ». La fermer — bouton,
 * Échap, clic à côté — n'allume rien, par construction : le seul écouteur qui
 * active est celui du menu. Ce qui reste vrai même si la fenêtre est fermée
 * par accident, et c'est bien le but.
 *
 * SEULEMENT CELLES JAMAIS ANNONCÉES (`nouvelle`, cf. app/extensions.py). Une
 * fois l'installation confirmée, redire la même chose à chaque démarrage n'
 * apprendrait plus rien et deviendrait une porte à claquer avant d'atteindre
 * son budget. L'état est retenu côté SERVEUR, pas dans le navigateur : c'est
 * une propriété de l'installation, et le stockage local d'une fenêtre webview
 * ne survit pas toujours à une mise à jour de l'application.
 */
function afficherModaleExtensions(extensions) {
  const nouvelles = extensions.filter((e) => e.nouvelle);
  if (nouvelles.length === 0) return;
  // UNE QUESTION PLUS URGENTE EST POSÉE PAR-DESSUS : « Où ranger tes données ? »
  // (cf. app.js::verifierEmplacementBase). Deux modales empilées cachent
  // justement celle des deux qui bloque, et une annonce d'extension n'a aucune
  // raison de passer devant. On ne dit rien ET ON NE MARQUE RIEN COMME ANNONCÉ :
  // l'état des annonces vit côté serveur, le taire ici sans le noter fait
  // simplement réapparaître la fenêtre au rechargement qui suit le choix.
  const modaleBase = document.getElementById("modale-bdd");
  if (modaleBase && modaleBase.style.display !== "none") return;
  extensionsAnnoncees = nouvelles.map((e) => e.id);

  const fond = document.getElementById("modale-extensions");
  document.getElementById("modale-extensions-texte").textContent =
    nouvelles.length === 1
      ? t(
          "Une extension a été trouvée dans le dossier « extensions ». Elle ne " +
            "fonctionnera qu'une fois activée ci-dessous — fermer cette fenêtre " +
            "ne l'active pas."
        )
      : t(
          "{n} extensions ont été trouvées dans le dossier « extensions ». Elles " +
            "ne fonctionneront qu'une fois activées ci-dessous — fermer cette " +
            "fenêtre n'en active aucune.",
          { n: nouvelles.length }
        );

  document.getElementById("modale-extensions-liste").innerHTML = nouvelles
    .map((e) => {
      // Repliés derrière leur pictogramme, comme sur l'écran Paramètres : la
      // fenêtre pose une question — allumer ou non — et cette question doit
      // rester lisible d'un coup d'œil même quand trois extensions arrivent
      // ensemble. Le détail est à un clic, pas plus loin.
      const explication = basculeDetailHtml(
        `modale-explication-${e.id}`,
        e.description
          ? `<p class="modale-extension-description">${escapeHtml(e.description)}</p>`
          : "",
        { libelle: t("Afficher ce que fait cette extension") }
      );
      // Une extension qu'on ne peut pas encore allumer est quand même annoncée
      // — elle est bien là, on vient de l'installer — mais son menu est grisé
      // et le bouton d'à côté dit ce qui lui manque.
      const alerte = basculeDetailHtml(
        `modale-avertissement-${e.id}`,
        e.dependances_ok
          ? ""
          : `<p class="modale-extension-description">${t(
              "Nécessite au moins une de ces extensions, installée et activée :"
            )} ${(e.requiert_une_de || []).map((id) => `« ${escapeHtml(id)} »`).join(` ${t("ou")} `)}</p>`,
        { libelle: t("Afficher l'avertissement"), classe: "detail-bascule-alerte" }
      );
      return `<li>
        <div class="modale-extension-bascule">
          <span class="modale-extension-nom">${escapeHtml(e.nom)}</span>
          ${e.version ? `<span class="modale-extension-version">v${escapeHtml(e.version)}</span>` : ""}
          ${explication.bouton}
          ${alerte.bouton}
          <select class="extension-etat" data-activer-extension="${escapeHtml(e.id)}"
                  aria-label="${t("État de l'extension")} — ${escapeHtml(e.nom)}"
                  ${e.dependances_ok ? "" : "disabled"}>
            <option value="actif" ${e.actif ? "selected" : ""}>${t("Activée")}</option>
            <option value="inactif" ${e.actif ? "" : "selected"}>${t("Désactivée")}</option>
          </select>
        </div>
        ${explication.panneau}
        ${alerte.panneau}
      </li>`;
    })
    .join("");

  fond.style.display = "";
  // La page derrière ne doit plus défiler : une molette au-dessus d'une modale
  // fait sinon glisser le contenu grisé, ce qui donne l'impression que le clic
  // est passé au travers.
  document.body.classList.add("modale-ouverte");
  // LE FOCUS VA SUR LE PREMIER MENU, pas sur un bouton : la décision à
  // prendre est là, et une fenêtre qui met le focus sur sa sortie invite à
  // sortir. Tab circule ensuite dans la fenêtre plutôt que dans la page grisée
  // derrière.
  // `:not(:disabled)` : un menu grisé ne peut pas recevoir le focus, et le
  // lui donner le renverrait au corps de la page — donc hors de la fenêtre.
  const premiere = fond.querySelector("select[data-activer-extension]:not(:disabled)");
  (premiere || document.getElementById("btn-modale-extensions-aller")).focus();
}

/**
 * Choisir « Activée » dans le menu ALLUME l'extension, sur-le-champ.
 *
 * C'est le seul geste qui l'allume : ni l'ouverture de cette fenêtre, ni sa
 * fermeture (bouton, Échap, clic à côté) ne touchent à l'activation. Le menu
 * revient à sa position si le serveur refuse — l'écran doit dire l'état réel,
 * pas l'intention.
 *
 * UN MENU ET NON UNE CASE, ici comme dans Paramètres → Extensions, et pour la
 * même raison : allumer une extension est un geste qui doit être VOULU, pas un
 * clic qui part en fermant la fenêtre. Il faut ouvrir la liste, puis choisir.
 */
document
  .getElementById("modale-extensions-liste")
  .addEventListener("change", async (evenement) => {
    const case_ = evenement.target.closest("select[data-activer-extension]");
    if (!case_) return;
    const id = case_.dataset.activerExtension;
    const actif = case_.value === "actif";
    case_.disabled = true;
    try {
      await apiFetch(`/extensions/${encodeURIComponent(id)}`, {
        method: "PUT",
        body: JSON.stringify({ actif }),
      });
      const abouti = await BudgetApp.extensions.appliquerActivation(id, actif);
      if (!abouti && actif) {
        throw new Error(t("Extension non chargée"));
      }
      showMessage(
        actif
          ? t("Extension activée.")
          : t("Extension désactivée. Aucune donnée n'a été supprimée."),
        "success"
      );
    } catch (err) {
      case_.value = actif ? "inactif" : "actif";
      showMessage(err.message, "error");
    } finally {
      case_.disabled = false;
    }
  });

/**
 * Ferme la fenêtre et ACQUITTE les extensions qu'elle annonçait : elles ne la
 * déclencheront plus au prochain lancement.
 *
 * L'acquittement part À LA FERMETURE, jamais à l'ouverture : « annoncée » veut
 * dire « vue et fermée ». Si l'application se ferme pendant que la fenêtre est
 * encore ouverte, rien n'a été acquitté et l'annonce revient — ce qui est le
 * comportement voulu, l'utilisateur n'ayant rien lu.
 *
 * L'échec de l'appel n'est pas remonté à l'écran : la conséquence est de
 * revoir la fenêtre une fois de plus, pas de perdre quoi que ce soit. Une
 * alerte d'erreur coûterait plus d'attention que le problème qu'elle
 * signale.
 */
function fermerModaleExtensions() {
  document.getElementById("modale-extensions").style.display = "none";
  document.body.classList.remove("modale-ouverte");

  if (extensionsAnnoncees.length === 0) return;
  const ids = extensionsAnnoncees;
  extensionsAnnoncees = []; // évite un second envoi si la fermeture se rejoue
  apiFetch("/extensions/annoncees", {
    method: "POST",
    body: JSON.stringify({ ids }),
  }).catch((err) => console.warn("Annonce non acquittée :", err.message));
}

document
  .getElementById("btn-modale-extensions-fermer")
  .addEventListener("click", fermerModaleExtensions);

document.getElementById("btn-modale-extensions-aller").addEventListener("click", () => {
  fermerModaleExtensions();
  switchSection("parametres");
  // Le clic sur l'onglet plutôt qu'un appel direct : c'est lui qui porte à la
  // fois l'affichage de la sous-page et le chargement de ses données (cf. les
  // deux gestionnaires délégués de app.js).
  document
    .querySelector('#parametres-sous-nav button[data-sous-section="parametres-extensions"]')
    ?.click();
});

// Clic sur le fond (hors de la boîte) et Échap : les deux sorties qu'on essaie
// d'instinct sur une modale. Rien n'est perdu en fermant — l'information reste
// dans Paramètres → Extensions.
document.getElementById("modale-extensions").addEventListener("click", (e) => {
  if (e.target.id === "modale-extensions") fermerModaleExtensions();
});

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (document.getElementById("modale-extensions").style.display !== "none") {
    fermerModaleExtensions();
  }
});

/**
 * Charge toutes les extensions. Appelé une fois, au démarrage de app.js,
 * AVANT le premier rendu : une extension qui ajoute un écran doit avoir posé
 * son bouton avant que l'utilisateur ne regarde la barre de navigation.
 */
async function chargerExtensions() {
  let extensions;
  try {
    extensions = await apiFetch("/extensions");
  } catch (err) {
    // Une application sans extensions doit continuer de fonctionner : c'est
    // le cas normal d'une installation minimale, pas une panne.
    console.warn("Extensions indisponibles :", err.message);
    return;
  }

  const annoncables = [];
  for (const manifeste of extensions) {
    extensionsChargees.set(manifeste.id, {
      manifeste,
      chargeur: null,
      fichiersCharges: false,
    });
    if (!manifeste.actif) {
      // Éteinte : on ne touche à aucun de ses fichiers. Elle reste annonçable
      // — c'est même tout l'objet de la fenêtre de lancement, proposer de
      // l'allumer.
      annoncables.push(manifeste);
      continue;
    }
    try {
      await chargerFichiers(manifeste);
      extensionsChargees.get(manifeste.id).fichiersCharges = true;
      // MÊME ÉVÉNEMENT QU'À L'ALLUMAGE À CHAUD, et pour la même raison : une
      // greffe chargée avant son hôte doit pouvoir s'accrocher en retard.
      // L'ordre de chargement est l'ordre ALPHABÉTIQUE des dossiers, sur lequel
      // personne ne choisit rien — « lecture-de-cours » passe avant
      // « monnaies » et « placements », qu'elle greffe toutes deux. Sans cet
      // événement ici, la greffe ne se poserait qu'au redémarrage suivant…
      // c'est-à-dire jamais.
      document.dispatchEvent(
        new CustomEvent("budgetapp:extension-chargee", { detail: { id: manifeste.id } })
      );
      annoncables.push(manifeste);
    } catch (err) {
      // Une extension allumée dont les fichiers manquent n'est pas annoncée :
      // proposer de l'ouvrir enverrait chercher un écran qui n'existe pas. Son
      // erreur, elle, reste visible dans Paramètres → Extensions.
      console.error(`Extension ${manifeste.id} : ${err.message}`);
    }
  }

  afficherModaleExtensions(annoncables);
}
