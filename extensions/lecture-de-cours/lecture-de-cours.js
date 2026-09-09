/* ---------- Extension « Placements financiers — cours en ligne » ----------
 *
 * UNE GREFFE, PAS UN ÉCRAN. Cette extension n'a pas de page à elle : elle
 * ajoute trois choses à celle de l'extension « placements », qui reste
 * entièrement fonctionnelle sans elle —
 *
 *   1. un champ « lien » sur chaque titre suivi ;
 *   2. un bouton « Mettre à jour les cours » en haut de la page ;
 *   3. une mise à jour automatique au lancement de l'application.
 *
 * COMMENT ON SE GREFFE, ET POURQUOI COMME ÇA. Le noyau ne prévoit qu'un point
 * d'accroche : `BudgetApp.extensions.enregistrer(id, { chargeur })`, appelé à
 * chaque ouverture d'un écran. Il n'existe pas d'API « ajoute-toi à l'écran
 * d'une autre extension ». On utilise donc les deux prises que le chargement
 * des extensions laisse ouvertes :
 *
 *   - on RÉ-ENREGISTRE le chargeur de « placements » avec le nôtre, qui appelle
 *     le sien puis pose la barre de mise à jour ;
 *   - on ENVELOPPE `renderTitresSuivis`, la fonction de « placements » qui
 *     redessine la liste des titres, pour rajouter nos champs après chacun de
 *     ses passages.
 *
 * Les deux tiennent parce que les scripts d'extension s'exécutent dans la
 * portée globale, dans l'ORDRE ALPHABÉTIQUE des dossiers : « placements »
 * avant « lecture-de-cours ». Si un jour ce n'était plus vrai, la greffe ne se
 * poserait pas et le reste continuerait de marcher — d'où les vérifications
 * plus bas plutôt qu'une confiance aveugle.
 *
 * TOUT PASSE PAR LE SERVEUR : cette page n'appelle jamais Google, Yahoo ni
 * Boursorama elle-même. Elle demande `/cours/...` à l'application locale, qui va lire (cf.
 * source_cours.py). C'est ce qui permet de dire précisément d'où part chaque
 * requête sortante, et de n'avoir qu'un seul endroit à regarder pour le savoir.
 */

// L'état de cotation par titre : { url_cours, cours_maj_le }, indexé par
// action_id. Tenu à jour à chaque réponse du serveur (toutes en renvoient la
// liste complète), pour que le redessin d'une ligne soit SYNCHRONE — il est
// appelé au milieu du rendu de « placements », qui ne nous attendrait pas.
const coursParTitre = new Map();

// Le dernier compte rendu affiché en haut de page. Gardé pour que rouvrir
// l'écran ne fasse pas disparaître le résultat de la mise à jour au lancement.
let dernierResume = null;

const ID_EXTENSION = "lecture-de-cours";

// La flèche du repli. Dessinée ici plutôt que reprise de `basculeDetailHtml`
// (app.js) : celui-là porte un pictogramme de feuilles, qui annonce « voici une
// explication ». Ce qui se déplie ici n'est pas un texte mais un réglage, et
// une flèche vers le bas est le seul dessin qui dise exactement cela.
/**
 * LE GLOBE « suivi en ligne », posé à gauche de la flèche de chaque titre.
 *
 * EN LIGNE PLUTÔT QUE PAR <img src="/img/connected_to_web.svg">, alors que le
 * fichier est là et servi : à travers une balise `img`, un SVG est une image
 * isolée et n'hérite d'aucune couleur de la page (cf. frontend/img/LISEZMOI.md).
 * Or c'est exactement ce qu'on lui demande — être bleu, de la MÊME teinte que
 * la flèche d'à côté, et suivre le thème si la palette change. Le dessin est
 * donc repris ici avec `fill="currentColor"`, comme les pictogrammes du noyau
 * (ICONE_POUBELLE, ICONE_OEIL…).
 *
 * Seul le tracé du globe est repris : le second chemin du fichier n'est qu'un
 * rectangle transparent de calage, sans objet une fois en ligne.
 */
const ICONE_GLOBE = `
  <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor"
       aria-hidden="true" focusable="false">
    <path d="M20.501 6.028V6h-.02A10.28 10.28 0 0 0 4.519 6H4.5v.028a10.262 10.262 0 0 0 0 12.944V19h.02a10.28 10.28 0 0 0 15.962 0h.021v-.028a10.262 10.262 0 0 0 0-12.944zM13 6V3.272A4.533 4.533 0 0 1 15.54 6zm2.935 1a16.827 16.827 0 0 1 .853 5H13V7zM12 3.272V6H9.46A4.533 4.533 0 0 1 12 3.272zM12 7v5H8.212a16.827 16.827 0 0 1 .853-5zm-4.787 5H3.226a9.234 9.234 0 0 1 1.792-5h2.984a17.952 17.952 0 0 0-.79 5zm0 1a17.952 17.952 0 0 0 .789 5H5.018a9.234 9.234 0 0 1-1.792-5zm1 0H12v5H9.065a16.827 16.827 0 0 1-.853-5zM12 19v2.728A4.533 4.533 0 0 1 9.46 19zm1 2.728V19h2.54A4.533 4.533 0 0 1 13 21.728zM13 18v-5h3.788a16.827 16.827 0 0 1-.853 5zm4.787-5h3.987a9.234 9.234 0 0 1-1.792 5h-2.984a17.952 17.952 0 0 0 .79-5zm0-1a17.952 17.952 0 0 0-.789-5h2.984a9.234 9.234 0 0 1 1.792 5zm1.352-6h-2.501a8.524 8.524 0 0 0-1.441-2.398A9.306 9.306 0 0 1 19.139 6zM9.803 3.602A8.524 8.524 0 0 0 8.363 6H5.86a9.306 9.306 0 0 1 3.942-2.398zM5.861 19h2.501a8.524 8.524 0 0 0 1.441 2.398A9.306 9.306 0 0 1 5.861 19zm9.336 2.398A8.524 8.524 0 0 0 16.637 19h2.502a9.306 9.306 0 0 1-3.942 2.398z" />
  </svg>`;

const CHEVRON_BAS = `
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
       stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"
       aria-hidden="true" focusable="false">
    <path d="m6 9 6 6 6-6" />
  </svg>`;

function actif() {
  return BudgetApp.extensions.estActive(ID_EXTENSION);
}

/* ---------- Serveur ---------- */

function memoriser(titres) {
  coursParTitre.clear();
  (titres || []).forEach((titre) => coursParTitre.set(titre.action_id, titre));
  // Le résumé de la barre découle entièrement de cette table : le remettre à
  // jour ICI, et pas chez chacun des appelants, évite qu'un chemin oublié
  // laisse affiché « 1 titre suivi » sous un titre qu'on vient de détacher.
  majEtatBarre();
}

async function chargerTitres() {
  try {
    memoriser(await apiFetch("/cours/titres"));
  } catch (err) {
    // L'extension désactivée répond 404 : ce n'est pas une panne, c'est un
    // choix de l'utilisateur. La page « placements » continue sans nous.
    console.warn("Cours en ligne indisponibles :", err.message);
  }
}

/* ---------- Fraîcheur d'un cours ---------- */

/**
 * « il y a 3 min », « il y a 2 h », sinon la date complète.
 *
 * Un cours n'intéresse que par sa fraîcheur : « il y a 3 min » se juge d'un
 * coup d'œil là où « 22 Août 2026 14:07 » demande de calculer. Au-delà d'une
 * journée l'écart cesse d'être parlant, et c'est la date qui reprend la main.
 */
function fraicheur(isoDateHeure) {
  if (!isoDateHeure) return t("cours saisi à la main");
  const quand = new Date(isoDateHeure);
  const secondes = (Date.now() - quand.getTime()) / 1000;
  if (secondes < 90) return t("à l'instant");
  if (secondes < 3600) return t("il y a {n} min", { n: Math.round(secondes / 60) });
  if (secondes < 86400) return t("il y a {n} h", { n: Math.round(secondes / 3600) });
  return formatDateHeure(isoDateHeure.slice(0, 19));
}

/* ---------- La barre de mise à jour, en haut de l'écran ---------- */

/**
 * Insérée juste sous le titre de la page, une seule fois.
 *
 * En HAUT et non près des « Titres suivis » (tout en bas) : c'est l'action
 * qu'on vient faire en ouvrant cet écran, et elle doit être là où le regard
 * arrive. Le compte rendu se loge à côté du bouton, pas dans un toast qui
 * s'efface : « 4 cours mis à jour il y a 2 h » est une information qu'on
 * consulte, pas une notification qu'on chasse.
 */
function poserBarre() {
  const section = document.getElementById("section-placements");
  if (!section) return; // extension « placements » absente : rien à greffer
  const existante = document.getElementById("pw-barre");
  if (!actif()) {
    // Désactivée depuis les Paramètres pendant que l'app tourne : la barre
    // disparaît à la prochaine ouverture de l'écran, sans recharger la page.
    if (existante) existante.remove();
    return;
  }
  if (existante) {
    majEtatBarre();
    return;
  }

  const barre = document.createElement("div");
  barre.id = "pw-barre";
  barre.className = "pw-barre";
  barre.innerHTML = `
    <button type="button" id="pw-rafraichir-tout" class="primary">
      ${t("Mettre à jour les cours")}
    </button>
    <span class="hint" id="pw-etat"></span>
  `;
  const titre = section.querySelector("h2");
  titre.insertAdjacentElement("afterend", barre);
  document
    .getElementById("pw-rafraichir-tout")
    .addEventListener("click", () => rafraichir("/cours/rafraichir"));
  majEtatBarre();
}

/** Le texte à côté du bouton : ce que la dernière mise à jour a donné. */
function majEtatBarre() {
  const etat = document.getElementById("pw-etat");
  if (!etat) return;
  const suivis = [...coursParTitre.values()].filter((titre) => titre.url_cours);
  if (suivis.length === 0) {
    etat.textContent = t(
      "Aucun titre n'a de lien : ajoute-en un dans « Titres suivis », en bas de page."
    );
    return;
  }
  const dates = suivis.map((titre) => titre.cours_maj_le).filter(Boolean);
  const derniere = dates.length ? dates.sort().at(-1) : null;
  const morceaux = [
    t("{n} titre(s) suivi(s) en ligne", { n: suivis.length }),
    derniere ? t("dernière lecture {quand}", { quand: fraicheur(derniere) }) : t("jamais lus"),
  ];
  if (dernierResume && dernierResume.echecs > 0) {
    morceaux.push(t("{n} en échec", { n: dernierResume.echecs }));
  }
  etat.textContent = morceaux.join(" — ");
}

/* ---------- Quelles pages coller : l'aide, au-dessus de la liste ---------- */

// Demandées une seule fois par session : la liste ne change qu'avec une
// nouvelle version de l'extension.
let sourcesConnues = null;

/**
 * Les sources reconnues, REPLIÉES au-dessus du premier champ à remplir.
 *
 * Elles viennent du serveur (`GET /cours/sources`) et non d'un texte recopié
 * ici : la liste affichée est alors, littéralement, celle du code qui lit les
 * pages — elle ne peut pas promettre une source qui n'existe plus, ni oublier
 * celle qu'on vient d'ajouter.
 *
 * DÉPLIABLE, ET NON PLUS ÉTALÉE. C'est une aide qu'on lit une fois, en collant
 * son premier lien, et qui n'a plus rien à dire ensuite : affichée en
 * permanence, elle occupait trois lignes au-dessus de la liste des titres à
 * chaque passage. Le pictogramme dépliant du noyau (`basculeDetailHtml`) est
 * exactement ce que ce cas demande — replié par défaut, un clic l'ouvre.
 *
 * UNE SEULE COULEUR. Le texte mêlait trois traitements sur la même ligne : le
 * nom en clair, l'adresse d'exemple en `<code>` (police et teinte propres),
 * la couverture en `<em>`. Trois façons d'écrire la même information n'aident
 * personne à la lire — c'est une liste, elle se lit comme une liste.
 */
async function poserAideSources() {
  const liste = document.getElementById("placements-actions-liste");
  if (!liste) return;
  const existante = document.getElementById("pw-sources");
  if (!actif()) {
    if (existante) existante.remove();
    return;
  }
  if (existante) return;

  if (sourcesConnues === null) {
    try {
      sourcesConnues = await apiFetch("/cours/sources");
    } catch (err) {
      return; // extension éteinte entre-temps : l'aide n'est pas essentielle
    }
  }
  // Une ligne par source, dans une liste : le nom, ce qu'elle couvre, puis
  // l'adresse d'exemple. Aucune mise en forme particulière — le nom en gras
  // suffit à distinguer les sources les unes des autres.
  const contenu =
    `<ul class="pw-sources-liste">` +
    sourcesConnues
      .map(
        (source) =>
          `<li><strong>${escapeHtml(source.nom)}</strong> — ` +
          `${escapeHtml(source.couvre)}<br />${escapeHtml(source.exemple)}</li>`
      )
      .join("") +
    `</ul>`;

  const detail = basculeDetailHtml("pw-sources-detail", contenu, {
    libelle: t("Afficher les pages reconnues"),
  });
  const aide = document.createElement("div");
  aide.id = "pw-sources";
  aide.className = "pw-sources";
  aide.innerHTML = `
    <div class="pw-sources-entete">
      <span class="hint">${t("Quelles pages puis-je coller ?")}</span>
      ${detail.bouton}
    </div>
    ${detail.panneau}
  `;
  liste.insertAdjacentElement("beforebegin", aide);
}

/* ---------- PLUS DE FORMULAIRE « Suivre un cours en ligne » ----------
 *
 * Il vivait ici, sous « Ajouter un titre » : un menu de titres et un champ
 * d'URL, pour attacher un lien de cotation à un titre déjà créé.
 *
 * RETIRÉ parce que la flèche de chaque rangée de « Titres suivis » fait la
 * même chose, en mieux : elle déplie le champ de lien DU titre qu'on regarde,
 * sans avoir à le rechoisir dans un menu, et le pictogramme posé à sa gauche
 * dit d'un coup d'œil lesquels sont déjà suivis (cf. greffeLiens). Le
 * formulaire ne servait plus qu'à refaire, précédé d'une sélection, un geste
 * déjà accessible juste sous le titre.
 */

/* ---------- Le champ « lien » sur chaque titre suivi ---------- */

/**
 * Ajoute une seconde ligne à chaque titre de « Titres suivis ».
 *
 * Appelée APRÈS `renderTitresSuivis` de l'extension « placements », qui vient
 * de reconstruire tout le bloc : nos champs doivent donc être reposés à
 * chaque fois, et non ajoutés une bonne fois pour toutes.
 */
function greffeLiens() {
  const bloc = document.getElementById("placements-actions-liste");
  if (!bloc || !actif()) return;

  bloc.querySelectorAll(".import-mapping-row").forEach((ligne) => {
    if (ligne.querySelector(".pw-lien")) return; // déjà greffée
    // Un titre ARCHIVÉ n'est plus relu en ligne (il ne sort même plus de
    // `/cours/titres`) : lui proposer un champ de lien promettrait une mise à
    // jour qui n'aura jamais lieu. Sa rangée n'apparaît de toute façon que
    // quand on coche « Afficher les titres archivés ».
    if (ligne.classList.contains("titre-archive")) return;
    const champCours = ligne.querySelector("input[data-action='cours']");
    if (!champCours) return;
    const actionId = Number(champCours.dataset.id);
    const titre = coursParTitre.get(actionId) || {};
    const suivi = Boolean(titre.url_cours);

    // LA FLÈCHE, posée juste après le nom du titre : c'est elle qui déplie le
    // lien. Le lien de cotation est un réglage — on le colle une fois et on n'y
    // revient plus — alors que le cours et l'archivage se lisent à chaque
    // passage. Le laisser déplié en permanence donnait à chaque titre une
    // seconde ligne d'URL, et une liste de quinze titres devenait un mur
    // d'adresses.
    const bascule = document.createElement("button");
    bascule.type = "button";
    bascule.className = "pw-bascule";
    bascule.dataset.pwBascule = String(actionId);
    bascule.setAttribute("aria-expanded", "false");
    bascule.title = t("Afficher le lien de cotation");
    bascule.setAttribute("aria-label", bascule.title);
    bascule.innerHTML = CHEVRON_BAS;
    // Un titre déjà suivi le montre sans qu'on ait à déplier : la pastille dit
    // qu'il y a quelque chose derrière la flèche.
    if (suivi) bascule.classList.add("pw-bascule-suivi");
    const nom = ligne.querySelector(".import-mapping-nom");
    // LE GLOBE, À GAUCHE DE LA FLÈCHE, et SEULEMENT pour un titre suivi en
    // ligne. C'est la seule chose de cet écran qui dise D'OÙ vient un cours :
    // rien ne distinguait un cours relu ce matin sur Internet d'un cours tapé
    // à la main il y a six mois — sinon la teinte de la flèche, qui dit aussi
    // « déplié » et ne pouvait donc pas dire cela seule.
    //
    // ABSENT, ET NON GRISÉ, quand le titre n'est pas suivi : un pictogramme
    // éteint sur chaque rangée d'une liste de quinze titres ferait une colonne
    // de bruit là où il n'y a rien à signaler.
    if (nom) nom.after(bascule);
    else ligne.prepend(bascule);
    // La flèche est posée d'abord, le globe se glisse JUSTE AVANT elle : c'est
    // la seule façon d'obtenir « nom · globe · flèche » sans dépendre de
    // l'ordre des deux insertions après le nom, qui se lit à l'envers.
    if (suivi) {
      const globe = document.createElement("span");
      globe.className = "pw-globe";
      globe.innerHTML = ICONE_GLOBE;
      globe.title = t("Cours relu en ligne");
      globe.setAttribute("role", "img");
      globe.setAttribute("aria-label", globe.title);
      bascule.before(globe);
    }

    const greffe = document.createElement("div");
    greffe.className = "pw-lien";
    greffe.hidden = true;
    greffe.innerHTML = `
      <input type="url" class="pw-url" data-pw-url data-id="${actionId}"
             placeholder="${t("Lien de la page de cotation (Google Finance, Yahoo Finance…)")}"
             value="${escapeHtml(titre.url_cours || "")}" />
      <button type="button" data-pw-rafraichir data-id="${actionId}"
              title="${t("Relire le cours maintenant")}" ${suivi ? "" : "disabled"}>
        ${t("Mettre à jour")}
      </button>
      <button type="button" data-pw-retirer data-id="${actionId}"
              title="${t("Ne plus suivre ce cours en ligne")}" ${suivi ? "" : "disabled"}>
        ${t("Détacher")}
      </button>
      <span class="pw-fraicheur">${escapeHtml(
        suivi ? fraicheur(titre.cours_maj_le) : t("cours saisi à la main")
      )}</span>
    `;
    ligne.appendChild(greffe);

    bascule.addEventListener("click", () => {
      const ouvrir = greffe.hidden;
      greffe.hidden = !ouvrir;
      bascule.setAttribute("aria-expanded", String(ouvrir));
      bascule.classList.toggle("ouvert", ouvrir);
      if (ouvrir) greffe.querySelector(".pw-url").focus();
    });
  });

  // Le lien est enregistré à la VALIDATION du champ (change), comme le cours
  // juste au-dessus : une URL se colle en une fois, mais se corrige lettre par
  // lettre, et chaque frappe ne doit pas déclencher une lecture.
  bloc.querySelectorAll("input[data-pw-url]").forEach((champ) => {
    champ.addEventListener("change", () => enregistrerLien(champ));
  });
  bloc.querySelectorAll("button[data-pw-rafraichir]").forEach((bouton) => {
    bouton.addEventListener("click", () =>
      rafraichir(`/cours/titres/${bouton.dataset.id}/rafraichir`)
    );
  });
  bloc.querySelectorAll("button[data-pw-retirer]").forEach((bouton) => {
    bouton.addEventListener("click", () => retirerLien(bouton.dataset.id));
  });
}

async function enregistrerLien(champ) {
  const actionId = Number(champ.dataset.id);
  const url = champ.value.trim();
  const precedent = coursParTitre.get(actionId) || {};

  if (!url) {
    if (precedent.url_cours) await retirerLien(actionId);
    return;
  }
  if (url === precedent.url_cours) return; // rien n'a changé

  champ.disabled = true;
  try {
    const reponse = await apiFetch(`/cours/titres/${actionId}`, {
      method: "PUT",
      body: JSON.stringify({ url }),
    });
    appliquerReponse(reponse);
    const lu = reponse.resultats[0];
    const symbole = (coursParTitre.get(actionId) || {}).monnaie_symbole || "";
    // Le nom publié par la source, pas celui du titre : c'est la seule
    // confirmation que le lien collé désigne bien l'instrument voulu.
    showMessage(
      lu && lu.libelle_source
        ? t("Cours lu sur {source} : {nom} — {cours}", {
            source: lu.source,
            nom: lu.libelle_source,
            cours: `${formatQuantite(lu.cours)} ${symbole}`.trim(),
          })
        : t("Lien enregistré"),
      "success"
    );
    await rechargerEcran();
  } catch (err) {
    // Le serveur n'a rien enregistré (cf. routeur_cours.definir_url) : le
    // champ revient à ce qu'il montrait, sans quoi il afficherait un lien que
    // la base ne connaît pas.
    champ.value = precedent.url_cours || "";
    showMessage(err.message, "error");
  } finally {
    champ.disabled = false;
  }
}

async function retirerLien(actionId) {
  try {
    await apiFetch(`/cours/titres/${actionId}`, { method: "DELETE" });
    showMessage(t("Lien retiré — le cours redevient saisi à la main"), "success");
    await chargerTitres();
    await rechargerEcran();
  } catch (err) {
    showMessage(err.message, "error");
  }
}

/* ---------- Rafraîchissement ---------- */

function appliquerReponse(reponse) {
  dernierResume = reponse;
  // Après `dernierResume` : c'est lui que la barre lit pour annoncer les échecs.
  memoriser(reponse.titres);
}

/**
 * Relit des cours et rend compte, titre par titre en cas d'échec.
 *
 * UN TOAST PAR ÉCHEC, un seul pour l'ensemble des réussites : « 4 cours mis à
 * jour » suffit quand tout va bien, alors qu'un échec ne dit quoi faire que
 * s'il nomme le titre ET la raison (lien mort, devise incohérente, site
 * injoignable). Quatre toasts pour quatre problèmes différents valent mieux
 * qu'un « 4 échecs » qu'il faudrait aller élucider ailleurs.
 */
async function rafraichir(route) {
  const bouton = document.getElementById("pw-rafraichir-tout");
  if (bouton) {
    bouton.disabled = true;
    bouton.textContent = t("Lecture en cours…");
  }
  try {
    const reponse = await apiFetch(route, { method: "POST" });
    appliquerReponse(reponse);
    if (reponse.reussis > 0) {
      showMessage(t("{n} cours mis à jour", { n: reponse.reussis }), "success");
    }
    reponse.resultats
      .filter((resultat) => !resultat.ok)
      .forEach((resultat) =>
        showMessage(`${resultat.action_nom} : ${resultat.erreur}`, "warning")
      );
    if (reponse.reussis === 0 && reponse.echecs === 0) {
      showMessage(t("Aucun titre n'a de lien à relire"), "warning");
    }
    // La valorisation, les plus-values et les KPI découlent des cours : la
    // page entière doit se recalculer, pas seulement la ligne du titre.
    await rechargerEcran();
  } catch (err) {
    showMessage(err.message, "error");
  } finally {
    if (bouton) {
      bouton.disabled = false;
      bouton.textContent = t("Mettre à jour les cours");
    }
  }
}

/** Redemande la page « placements » — mais seulement si elle est à l'écran.
 *
 * `.active` et non `display` : c'est par cette classe que le noyau montre et
 * masque ses écrans (cf. app.js::switchSection). Recharger un écran caché
 * ferait travailler le serveur pour un rendu que personne ne regarde, et
 * l'ouverture suivante le referait de toute façon.
 */
async function rechargerEcran() {
  const section = document.getElementById("section-placements");
  if (!section || !section.classList.contains("active")) return;
  if (typeof loadPlacements === "function") await loadPlacements();
}

/**
 * LA MISE À JOUR AU LANCEMENT.
 *
 * Différée d'une seconde et jamais attendue : l'application doit s'ouvrir sur
 * son tableau de bord à la vitesse habituelle, sans dépendre d'un site
 * distant. Trois secondes de lecture réseau au démarrage se remarqueraient
 * immédiatement, et pour un chiffre dont personne n'a besoin dans la seconde.
 *
 * DISCRÈTE QUAND ELLE RÉUSSIT, VISIBLE QUAND ELLE ÉCHOUE : un toast de succès
 * à chaque ouverture deviendrait du bruit, mais un cours qu'on croit frais et
 * qui ne l'est pas est précisément le piège que cette extension doit éviter.
 * Le compte rendu complet, lui, attend sur la page Placements.
 */
async function rafraichirAuLancement() {
  if (!actif()) return;
  try {
    const reponse = await apiFetch("/cours/rafraichir", { method: "POST" });
    appliquerReponse(reponse);
    if (reponse.echecs > 0) {
      showMessage(
        t("{n} cours n'ont pas pu être relus au lancement (voir Placements)", {
          n: reponse.echecs,
        }),
        "warning"
      );
    }
    await rechargerEcran();
  } catch (err) {
    console.warn("Mise à jour des cours au lancement :", err.message);
  }
}

/* ---------- Accroche à l'extension « placements » ---------- */

/**
 * Notre chargeur : celui de « placements », puis la greffe.
 *
 * Les titres sont chargés AVANT, parce que `renderTitresSuivis` (appelée au
 * milieu de `loadPlacements`) lit `coursParTitre` de façon synchrone : sans
 * cela, la première ouverture de l'écran afficherait des champs de lien vides
 * sur des titres qui en ont un.
 */
async function chargerPlacementsAvecCours() {
  if (actif()) await chargerTitres();
  if (typeof loadPlacements === "function") await loadPlacements();
  poserBarre();
  greffeLiens();
  ajusterInfoBulle();
  await poserAideSources();
}

/**
 * L'info-bulle de « Titres suivis » affirme que l'application n'interroge
 * aucun service de marché. C'était vrai, ça ne l'est plus sur cette
 * installation : le texte est réécrit plutôt que laissé à mentir.
 *
 * Réécrit ICI et non dans le HTML de l'autre extension : celle-ci doit rester
 * exacte quand elle est seule, ce qu'elle est chez tous ceux qui n'ont pas
 * installé la nôtre.
 */
let infoBulleOrigine = null;

function ajusterInfoBulle() {
  const bulle = document.querySelector("#section-placements h3 .info-bulle");
  if (!bulle) return;
  // Le texte d'origine est gardé au premier passage : désactiver l'extension
  // doit rendre la page telle qu'elle serait sans elle, texte compris.
  if (infoBulleOrigine === null) infoBulleOrigine = bulle.dataset.info;
  bulle.dataset.info = actif()
    ? t(
        "Tes titres, communs à tous tes comptes. Colle le lien d'une page de " +
          "cotation à côté d'un titre et son cours se relira tout seul : c'est la " +
          "seule chose que l'app va chercher sur Internet, et seulement pour les " +
          "titres qui ont un lien. Le cours dit ce que ça vaut aujourd'hui, jamais " +
          "comment un solde est calculé."
      )
    : infoBulleOrigine;
}

/**
 * Pose la greffe sur l'extension « placements ». Rend false si elle n'est pas
 * là — auquel cas il n'y a rien à greffer, et surtout rien à casser.
 *
 * DEUX ACCROCHES, ET RIEN D'AUTRE :
 *
 *   1. `renderTitresSuivis` est ENVELOPPÉE, pour que nos champs soient reposés
 *      après chacun de ses passages (modifier un cours la rappelle) ;
 *   2. le chargeur de « placements » est RÉ-ENREGISTRÉ avec le nôtre, qui
 *      appelle le sien — le retirer casserait son écran.
 *
 * Idempotente : `greffePosee` empêche d'envelopper deux fois la même fonction,
 * ce qui ferait courir la greffe en double à chaque rendu.
 */
let greffePosee = false;

function poserGreffe() {
  if (greffePosee) return true;
  if (typeof renderTitresSuivis !== "function" || typeof loadPlacements !== "function") {
    return false;
  }
  const rendreTitresOrigine = renderTitresSuivis;
  window.renderTitresSuivis = function () {
    rendreTitresOrigine.apply(this, arguments);
    greffeLiens();
  };
  BudgetApp.extensions.enregistrer("placements", { chargeur: chargerPlacementsAvecCours });
  greffePosee = true;
  return true;
}

if (!poserGreffe()) {
  // « placements » n'est pas (encore) chargée : soit elle n'est pas installée,
  // soit elle est éteinte et l'utilisateur va peut-être l'allumer dans un
  // instant. Le noyau prévient quand une extension est chargée à chaud — on
  // réessaie alors, plutôt que d'exiger un redémarrage pour deux cases cochées
  // dans le mauvais ordre.
  console.warn(
    "lecture-de-cours : l'extension « placements » n'est pas chargée, la greffe attend."
  );
  document.addEventListener("budgetapp:extension-chargee", (evenement) => {
    if (evenement.detail && evenement.detail.id === "placements") poserGreffe();
  });
}

// Le lancement de l'application, une fois le reste posé.
setTimeout(rafraichirAuLancement, 1000);
