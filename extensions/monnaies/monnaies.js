/* Extension « Monnaies ».
 *
 * CE QUI EST OPTIONNEL, C'EST DE POUVOIR EN AJOUTER. Le noyau sait depuis
 * toujours qu'un montant appartient à une monnaie : la colonne existe partout,
 * les soldes sont calculés monnaie par monnaie, et rien n'additionne jamais
 * deux devises. Ce que cette extension apporte, c'est l'écran qui CRÉE,
 * renomme et supprime des monnaies — et les routes qui vont avec.
 *
 * Sans elle, la base ne contient que la monnaie posée à l'installation, et
 * toute l'interface s'y replie d'elle-même : les barres d'onglets par monnaie
 * disparaissent (elles se masquent déjà à une seule monnaie), le menu de
 * monnaie d'une opération ne s'affiche pas, et le compte n'a qu'un solde
 * initial à saisir. L'application devient mono-devise sans qu'une seule ligne
 * de son code ne s'en aperçoive.
 *
 * L'ÉTEINDRE NE REPLIE RIEN DE FORCE. Une base qui porte déjà plusieurs
 * monnaies continue de les afficher toutes : ses onglets, ses soldes et ses
 * budgets restent lisibles. On perd le droit d'en ajouter, jamais le droit de
 * voir ce qu'on a. C'est la règle du dépôt — désactiver ne fait pas
 * disparaître de données (cf. extensions/README.md).
 *
 * `refreshMonnaies` et `monnaieParId` restent dans le noyau : tout l'écran a
 * besoin de connaître les symboles pour afficher un montant, extension ou pas.
 */


async function loadMonnaies() {
  try {
    await refreshMonnaies();
    renderMonnaies();
    await loadTauxMonnaies();
  } catch (err) {
    showMessage(err.message, "error");
  }
}

function renderMonnaies() {
  const bloc = document.getElementById("monnaies-liste");
  // Le formulaire d'édition est DÉPLACÉ dans cette liste (cf.
  // ouvrirFormulaireEnLigne, dans le noyau) : le vider sans l'avoir remis à sa
  // place l'emporterait, avec tous les écouteurs posés plus bas.
  fermerFormulaireEnLigne("form-monnaie");
  bloc.innerHTML = "";
  if (state.monnaies.length === 0) {
    bloc.innerHTML = `<span class="hint">${t("Aucune monnaie.")}</span>`;
    return;
  }
  state.monnaies.forEach((monnaie) => {
    const row = document.createElement("div");
    row.className = "import-mapping-row";
    row.dataset.id = monnaie.id;
    row.innerHTML = `
      <span class="import-mapping-nom">${escapeHtml(monnaie.nom)} — ${escapeHtml(monnaie.symbole)}</span>
      <button type="button" data-action="modifier-monnaie" data-id="${monnaie.id}">${t("Modifier")}</button>
      <button type="button" data-action="supprimer-monnaie" data-id="${monnaie.id}" class="danger">${t("Supprimer")}</button>
    `;
    bloc.appendChild(row);
  });

  // Le formulaire vient se poser SOUS la ligne éditée, comme sur la page
  // Opérations et comme pour les comptes : le mécanisme est celui du noyau,
  // cette extension ne fait que le nommer.
  const editerMonnaie = (id, ligne) => {
    const monnaie = monnaieParId(id);
    if (!monnaie) return;
    ouvrirFormulaireEnLigne("form-monnaie", "form-monnaie-titre", ligne);
    document.getElementById("monnaie-id").value = monnaie.id;
    document.getElementById("monnaie-nom").value = monnaie.nom;
    document.getElementById("monnaie-symbole").value = monnaie.symbole;
    document.getElementById("form-monnaie-titre").textContent = `${t("Modifier")} « ${monnaie.nom} »`;
    document.getElementById("monnaie-annuler").style.display = "inline-block";
  };
  activerEditionDoubleClic(bloc, editerMonnaie);

  bloc.querySelectorAll("button[data-action='modifier-monnaie']").forEach((btn) => {
    btn.addEventListener("click", () =>
      editerMonnaie(Number(btn.dataset.id), btn.closest(".import-mapping-row"))
    );
  });

  bloc.querySelectorAll("button[data-action='supprimer-monnaie']").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm(t("Supprimer cette monnaie ?"))) return;
      try {
        await apiFetch(`/monnaies/${btn.dataset.id}`, { method: "DELETE" });
        showMessage(t("Monnaie supprimée"), "success");
        await loadMonnaies();
      } catch (err) {
        showMessage(err.message, "error");
      }
    });
  });
}

function resetMonnaieForm() {
  fermerFormulaireEnLigne("form-monnaie");
  document.getElementById("monnaie-id").value = "";
  document.getElementById("monnaie-nom").value = "";
  document.getElementById("monnaie-symbole").value = "";
  document.getElementById("form-monnaie-titre").textContent = t("Ajouter une monnaie");
  document.getElementById("monnaie-annuler").style.display = "none";
}

document.getElementById("form-monnaie").addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = document.getElementById("monnaie-id").value;
  const payload = {
    nom: document.getElementById("monnaie-nom").value,
    symbole: document.getElementById("monnaie-symbole").value,
  };
  try {
    if (id) {
      await apiFetch(`/monnaies/${id}`, { method: "PUT", body: JSON.stringify(payload) });
      showMessage(t("Monnaie modifiée"), "success");
    } else {
      await apiFetch("/monnaies", { method: "POST", body: JSON.stringify(payload) });
      showMessage(t("Monnaie créée"), "success");
    }
    resetMonnaieForm();
    await loadMonnaies();
  } catch (err) {
    showMessage(err.message, "error");
  }
});


/* ---------- Taux de change ----------
 *
 * CE QU'UN TAUX FAIT, ET CE QU'IL NE FAIT PAS. Il ne réécrit rien : aucun
 * solde, aucun budget, aucune opération enregistrée ne change parce qu'un taux
 * est saisi. Il sert exactement à une chose — la case « tout convertir en… »
 * du dashboard, posée par ce même fichier plus bas. Décocher la case, ou
 * éteindre cette extension, rend l'application au fonctionnement monnaie par
 * monnaie qui est le sien partout ailleurs.
 *
 * UN SEUL SENS SUFFIT. « 1 € = 1,08 $ » et « 1 $ = 0,926 € » sont la même
 * information écrite deux fois ; la conversion sait diviser (cf.
 * service_conversion.py), et exiger les deux lignes doublerait la saisie à
 * chaque devise ajoutée sans rien protéger.
 *
 * L'EXTENSION « Lecture de cours » ÉCRIT DANS LA MÊME TABLE : un taux relu en
 * ligne sert donc à convertir sans qu'on ait à le ressaisir, et il apparaît
 * dans cette liste avec la mention de sa provenance.
 */

let tauxMonnaies = [];

async function loadTauxMonnaies() {
  try {
    tauxMonnaies = await apiFetch("/conversion/taux");
  } catch (err) {
    tauxMonnaies = [];
    console.error(err);
  }
  remplirMenusTauxMonnaies();
  renderTauxMonnaies();
}

function remplirMenusTauxMonnaies() {
  const source = document.getElementById("monnaie-taux-source");
  const cible = document.getElementById("monnaie-taux-cible");
  if (!source || !cible) return;
  const options = state.monnaies
    .map((m) => `<option value="${m.id}">${escapeHtml(m.nom)} (${escapeHtml(m.symbole)})</option>`)
    .join("");
  const avant = { source: source.value, cible: cible.value };
  source.innerHTML = options;
  cible.innerHTML = options;
  if (avant.source) source.value = avant.source;
  if (avant.cible) cible.value = avant.cible;
  // Deux monnaies différentes par défaut quand il y en a assez : le couple le
  // plus courant se saisit alors sans toucher aux menus.
  else if (state.monnaies.length > 1) cible.value = String(state.monnaies[1].id);
}

/* ---------- Les modes de saisie d'un taux ----------
 *
 * DEUX FAÇONS D'OBTENIR LE MÊME TAUX : le taper, ou donner un lien de cotation
 * que l'application relira. Elles vivaient dans deux blocs séparés — deux
 * listes des mêmes couples, deux formulaires, deux titres « Taux de change »
 * l'un sous l'autre. Ce sont pourtant les mêmes taux, dans la même table, qui
 * servent à la même chose : seule la façon de les saisir change.
 *
 * D'OÙ CE PETIT REGISTRE. Cette extension déclare le mode « à la main », qui ne
 * dépend de rien ; « Lecture de cours » déclare le mode « depuis un lien »
 * quand elle tourne, et le retire quand on l'éteint. Le formulaire, la liste et
 * les deux menus de monnaies leur sont communs.
 *
 * EXPOSÉ EN GLOBAL parce que c'est la seule prise que le noyau laisse entre
 * deux extensions (cf. extensions/README.md) : les scripts s'exécutent dans la
 * portée globale, et « Lecture de cours » appelle `enregistrer` au chargement.
 */

const modesTaux = new Map();
let modeTauxActif = null;

window.MonnaiesTaux = {
  /**
   * Ajoute une façon de saisir un taux.
   *
   * `champsHtml()` rend le HTML du champ propre au mode ; `soumettre({source,
   * cible})` l'enregistre et rend une promesse. `ordre` range le bouton dans la
   * barre — le mode manuel est à 0, pour rester en tête.
   *
   * `apresRendu()`, facultatif, est appelé une fois les champs DANS la page :
   * c'est le seul moment où un mode peut les remplir depuis le serveur. Sans
   * lui, un mode qui n'est pas celui affiché au chargement n'aurait jamais
   * d'occasion de le faire.
   *
   * Idempotent : réenregistrer un mode déjà connu le remplace, ce qui permet à
   * une extension rallumée en cours de session de reposer le sien.
   */
  enregistrer(id, { libelle, ordre = 10, champsHtml, soumettre, apresRendu }) {
    modesTaux.set(id, { id, libelle, ordre, champsHtml, soumettre, apresRendu });
    renderModesTaux();
  },
  retirer(id) {
    modesTaux.delete(id);
    if (modeTauxActif === id) modeTauxActif = null;
    renderModesTaux();
  },
  /** Rafraîchit la liste des couples — pour l'extension qui vient d'en écrire un. */
  rafraichir: () => loadTauxMonnaies(),
};

function modesTauxTries() {
  return [...modesTaux.values()].sort(
    (a, b) => a.ordre - b.ordre || a.id.localeCompare(b.id)
  );
}

function renderModesTaux() {
  const barre = document.getElementById("monnaies-taux-modes");
  const saisie = document.getElementById("monnaie-taux-saisie");
  if (!barre || !saisie) return;

  const modes = modesTauxTries();
  if (modes.length === 0) return;
  if (!modeTauxActif || !modesTaux.has(modeTauxActif)) modeTauxActif = modes[0].id;

  // MASQUÉE TANT QU'ELLE EST SEULE : un bouton unique ne choisit rien et ne
  // ferait que répéter le titre du bloc. Même règle que les barres d'onglets du
  // noyau.
  barre.style.display = modes.length > 1 ? "" : "none";
  barre.innerHTML = "";
  modes.forEach((mode) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = t(mode.libelle);
    if (mode.id === modeTauxActif) btn.classList.add("active");
    btn.addEventListener("click", () => {
      modeTauxActif = mode.id;
      renderModesTaux();
    });
    barre.appendChild(btn);
  });

  const mode = modesTaux.get(modeTauxActif);
  saisie.innerHTML = mode.champsHtml();
  if (mode.apresRendu) mode.apresRendu();
}

// LE MODE PAR DÉFAUT, celui qui ne dépend d'aucune autre extension : sans
// « Lecture de cours », c'est le seul, et la barre de modes reste masquée.
window.MonnaiesTaux.enregistrer("manuel", {
  libelle: "À la main",
  ordre: 0,
  champsHtml: () => `
    <label for="monnaie-taux-valeur">${t("ce nombre d'unités")}
      <input type="number" step="any" min="0" id="monnaie-taux-valeur"
             placeholder="${t("ex. 1,08")}" required />
    </label>`,
  soumettre: async ({ source, cible }) => {
    const valeur = parseFloat(document.getElementById("monnaie-taux-valeur").value);
    if (!(valeur > 0)) {
      throw new Error(t("Le taux doit être un nombre strictement positif."));
    }
    // PUT : ressaisir un couple met son taux à jour plutôt que d'être refusé —
    // c'est le geste ordinaire, un taux bouge.
    await apiFetch("/conversion/taux", {
      method: "PUT",
      body: JSON.stringify({
        monnaie_source_id: source,
        monnaie_cible_id: cible,
        taux: valeur,
      }),
    });
    return t("Taux enregistré");
  },
});

function renderTauxMonnaies() {
  const bloc = document.getElementById("monnaies-taux-liste");
  if (!bloc) return;
  bloc.innerHTML = "";
  const formulaire = document.getElementById("form-monnaie-taux");
  if (state.monnaies.length < 2) {
    // Un taux entre une monnaie et elle-même n'existe pas : tant qu'il n'y en a
    // qu'une, ce bloc n'a rien à proposer.
    bloc.innerHTML = `<span class="hint">${t(
      "Ajoute une seconde monnaie pour pouvoir saisir un taux."
    )}</span>`;
    formulaire.style.display = "none";
    return;
  }
  formulaire.style.display = "";
  renderModesTaux();

  if (tauxMonnaies.length === 0) {
    bloc.innerHTML = `<span class="hint">${t("Aucun taux enregistré.")}</span>`;
    return;
  }
  tauxMonnaies.forEach((couple) => {
    const ligne = document.createElement("div");
    ligne.className = "import-mapping-row";
    // La PROVENANCE est dite, parce qu'elle décide de ce qui arrivera à ce
    // taux : celui qui porte un lien sera écrasé au prochain rafraîchissement,
    // celui qu'on a tapé ne bougera jamais tout seul.
    const provenance = couple.url_cours
      ? `<a class="hint" href="${escapeHtml(couple.url_cours)}" target="_blank"
            rel="noopener noreferrer" title="${escapeHtml(couple.url_cours)}">${t(
          "relu en ligne"
        )}</a>`
      : `<span class="hint">${t("saisi à la main")}</span>`;
    ligne.innerHTML = `
      <span class="import-mapping-nom">
        1 ${escapeHtml(couple.monnaie_source_symbole)} =
        <strong>${couple.taux == null ? "—" : couple.taux}</strong>
        ${escapeHtml(couple.monnaie_cible_symbole)}
      </span>
      <span class="hint">${escapeHtml(couple.monnaie_source_nom)} &rarr;
        ${escapeHtml(couple.monnaie_cible_nom)}</span>
      ${provenance}
      <button type="button" class="danger" data-taux-supprimer="${couple.id}">${t(
        "Supprimer"
      )}</button>
    `;
    bloc.appendChild(ligne);
  });

  bloc.querySelectorAll("button[data-taux-supprimer]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await apiFetch(`/conversion/taux/${btn.dataset.tauxSupprimer}`, {
          method: "DELETE",
        });
        showMessage(t("Taux supprimé"), "success");
        await loadTauxMonnaies();
      } catch (err) {
        showMessage(err.message, "error");
      }
    });
  });
}

// UN SEUL POINT DE SOUMISSION pour tous les modes : les deux menus de monnaies
// et leur validation leur sont communs, seul l'enregistrement diffère.
document.getElementById("form-monnaie-taux").addEventListener("submit", async (e) => {
  e.preventDefault();
  const source = Number(document.getElementById("monnaie-taux-source").value);
  const cible = Number(document.getElementById("monnaie-taux-cible").value);
  if (source === cible) {
    showMessage(t("Choisis deux monnaies différentes."), "error");
    return;
  }
  const mode = modesTaux.get(modeTauxActif);
  if (!mode) return;
  try {
    const message = await mode.soumettre({ source, cible });
    showMessage(message || t("Taux enregistré"), "success");
    await loadTauxMonnaies();
  } catch (err) {
    showMessage(err.message, "error");
  }
});

document.getElementById("monnaie-annuler").addEventListener("click", resetMonnaieForm);
/* ---------- La bascule d'agrégation du dashboard ----------
 *
 * CE QU'ELLE RÉSOUT. Le dashboard raisonne par monnaie : un onglet chacune, et
 * rien ne s'additionne entre elles — c'est le choix central de l'application, et
 * il a raison tant qu'on n'a aucun taux. Mais quelqu'un qui tient un compte en
 * euros et un en dollars n'a alors AUCUN endroit où lire ce qu'il possède. La
 * case répond à cette question-là, et à aucune autre.
 *
 * ELLE CONVERTIT VERS L'ONGLET ACTIF. Pas de second menu à régler : on choisit
 * la monnaie comme on l'a toujours fait, en cliquant son onglet, et la case dit
 * « tout convertir en € ». Son libellé suit donc l'onglet.
 *
 * RIEN N'EST ÉCRIT. Aucun montant en base ne change, et l'état de la case ne
 * survit pas au rechargement de la page : c'est une façon de regarder, pas un
 * réglage de l'application.
 *
 * COMMENT ON SE GREFFE. On enveloppe `loadDashboardData` du noyau : elle rend
 * le dashboard normal (et redessine les onglets, dans lesquels on repose notre
 * case), puis on remplace les chiffres par leur version convertie si la case
 * est cochée. Envelopper plutôt que réécrire garantit que les deux vues
 * viennent du même code d'affichage — c'est ce qui les empêche de diverger.
 */

const MONNAIES_ID = "monnaies";

let agregationActive = false;
// Les monnaies qu'aucun taux ne relie à celle qu'on regarde. Gardées pour
// l'avertissement affiché sous la case : un total amputé sans le dire vaudrait
// moins qu'un refus.
let agregationNonConverties = [];

function agregationDisponible() {
  return BudgetApp.extensions.estActive(MONNAIES_ID) && (state.monnaies || []).length > 1;
}

/**
 * Pose (ou retire) la case, juste après la barre d'onglets de monnaie.
 *
 * Idempotente : la barre est redessinée à chaque chargement du dashboard, la
 * case ne doit pas se dupliquer. Elle est RETIRÉE quand l'extension vient
 * d'être éteinte, sans quoi elle resterait affichée jusqu'au rechargement de
 * la page et sa route répondrait 404.
 */
function poserBasculeAgregation() {
  const barre = document.getElementById("dashboard-monnaies");
  if (!barre) return;
  let bloc = document.getElementById("monnaies-agregation");
  if (!agregationDisponible()) {
    if (bloc) bloc.remove();
    agregationActive = false;
    return;
  }
  if (!bloc) {
    bloc = document.createElement("div");
    bloc.id = "monnaies-agregation";
    bloc.className = "monnaies-agregation";
    bloc.innerHTML = `
      <label class="import-option-ligne">
        <input type="checkbox" id="monnaies-agregation-case" />
        <span id="monnaies-agregation-libelle"></span>
        <i class="info-bulle" tabindex="0" data-info="${escapeHtml(
          t(
            "Additionne tes monnaies en une seule, au taux que tu as saisi dans " +
              "Paramètres → Monnaies. Rien n'est modifié : décoche et tout revient. " +
              "Une monnaie sans taux est laissée de côté, et signalée."
          )
        )}">i</i>
      </label>
      <div class="hint" id="monnaies-agregation-alerte" style="display:none"></div>
    `;
    barre.insertAdjacentElement("afterend", bloc);
    document
      .getElementById("monnaies-agregation-case")
      .addEventListener("change", (e) => {
        agregationActive = e.target.checked;
        // On redemande le dashboard : la vue convertie est calculée côté
        // serveur, à partir des mêmes chiffres.
        loadDashboardData(state.dashboardPeriode.annee, state.dashboardPeriode.mois);
      });
  }
  document.getElementById("monnaies-agregation-case").checked = agregationActive;
  const monnaie = monnaieParId(state.dashboardMonnaieId);
  document.getElementById("monnaies-agregation-libelle").textContent = monnaie
    ? t("Tout convertir en {monnaie}", { monnaie: monnaie.nom })
    : t("Tout convertir");
  majAlerteAgregation();
}

function majAlerteAgregation() {
  const alerte = document.getElementById("monnaies-agregation-alerte");
  if (!alerte) return;
  if (!agregationActive || agregationNonConverties.length === 0) {
    alerte.style.display = "none";
    return;
  }
  alerte.style.display = "";
  alerte.textContent = t(
    "Pas de taux pour {monnaies} : ces montants ne sont pas comptés. Saisis leur taux dans Paramètres → Monnaies.",
    { monnaies: agregationNonConverties.map((m) => m.monnaie_nom).join(", ") }
  );
}

/**
 * Remplace les chiffres du dashboard par leur version convertie.
 *
 * Rend false quand il n'y a rien à convertir (monnaie visée portée par aucun
 * compte) : l'appelant laisse alors la vue par monnaie en place plutôt que de
 * vider l'écran.
 */
async function appliquerAgregation(annee, mois) {
  const vue = state.dashboardPeriode.vue;
  const parametres = new URLSearchParams({
    vers: String(state.dashboardMonnaieId),
    annee: String(annee),
    vue,
  });
  if (vue !== "annee") parametres.set("mois", String(mois));

  const reponse = await apiFetch(`/conversion/dashboard?${parametres}`);
  agregationNonConverties = reponse.non_converties || [];
  if (!reponse.dashboard) return false;

  // LES FONCTIONS D'AFFICHAGE DU NOYAU, telles quelles : la vue convertie et la
  // vue par monnaie doivent se ressembler jusqu'au pixel, et deux rendus
  // parallèles finiraient par ne plus le faire.
  renderKpisDashboard(reponse.dashboard.kpis[0]);
  return true;
}

/* ---------- La même case, pour le camembert de la Vue globale des comptes ----------
 *
 * LE CAMEMBERT A SA PROPRE MONNAIE, et donc sa propre case. Il vivait sur le
 * dashboard, où la case des onglets suffisait à le convertir avec le reste ;
 * depuis qu'il est sur la page des comptes, il choisit sa monnaie dans un menu
 * à lui, sur une page qui n'a pas d'onglets de monnaie du tout. Il lui faut
 * donc sa bascule, posée dans le conteneur que cette page réserve aux
 * extensions (`#globale-repartition-options`).
 *
 * DEUX ÉTATS INDÉPENDANTS (`agregationActive` pour le dashboard,
 * `avoirsAgreges` ici) : ce sont deux écrans qu'on ne regarde pas ensemble, et
 * partager la case aurait fait qu'ouvrir l'un change silencieusement l'autre.
 *
 * MÊME ROUTE, MÊME FONCTION DE RENDU que la vue par monnaie : le camembert
 * converti et le camembert d'une monnaie doivent se ressembler jusqu'au pixel.
 */

let avoirsAgreges = false;
let avoirsNonConvertis = [];

function poserBasculeAvoirs() {
  const ancre = document.getElementById("globale-repartition-options");
  if (!ancre) return;
  let bloc = document.getElementById("monnaies-avoirs-agregation");
  if (!agregationDisponible()) {
    if (bloc) bloc.remove();
    avoirsAgreges = false;
    return;
  }
  if (!bloc) {
    bloc = document.createElement("div");
    bloc.id = "monnaies-avoirs-agregation";
    bloc.className = "monnaies-agregation";
    bloc.innerHTML = `
      <label class="import-option-ligne">
        <input type="checkbox" id="monnaies-avoirs-case" />
        <span id="monnaies-avoirs-libelle"></span>
        <i class="info-bulle" tabindex="0" data-info="${escapeHtml(
          t(
            "Additionne tes monnaies en une seule, au taux que tu as saisi dans " +
              "Paramètres → Monnaies. Rien n'est modifié : décoche et tout revient. " +
              "Une monnaie sans taux est laissée de côté, et signalée."
          )
        )}">i</i>
      </label>
      <div class="hint" id="monnaies-avoirs-alerte" style="display:none"></div>
    `;
    ancre.appendChild(bloc);
    document.getElementById("monnaies-avoirs-case").addEventListener("change", (e) => {
      avoirsAgreges = e.target.checked;
      renderRepartitionAvoirs();
    });
  }
  document.getElementById("monnaies-avoirs-case").checked = avoirsAgreges;
  const monnaie = monnaieParId(state.comptesRepartitionMonnaieId);
  document.getElementById("monnaies-avoirs-libelle").textContent = monnaie
    ? t("Tout convertir en {monnaie}", { monnaie: monnaie.nom })
    : t("Tout convertir");
  majAlerteAvoirs();
}

function majAlerteAvoirs() {
  const alerte = document.getElementById("monnaies-avoirs-alerte");
  if (!alerte) return;
  if (!avoirsAgreges || avoirsNonConvertis.length === 0) {
    alerte.style.display = "none";
    return;
  }
  alerte.style.display = "";
  alerte.textContent = t(
    "Pas de taux pour {monnaies} : ces montants ne sont pas comptés. Saisis leur taux dans Paramètres → Monnaies.",
    { monnaies: avoirsNonConvertis.map((m) => m.monnaie_nom).join(", ") }
  );
}

/**
 * Redessine le camembert converti, par-dessus celui que le noyau vient de
 * rendre par monnaie.
 *
 * LA PÉRIODE EST CELLE PAR DÉFAUT DU SERVEUR (le mois courant), comme pour le
 * `/dashboard` que cette page demande déjà : le camembert ne lit que des soldes
 * RÉELS et la valorisation des titres, et ni l'un ni l'autre ne dépend du mois
 * qu'on regarderait.
 */
async function appliquerAgregationAvoirs() {
  const parametres = new URLSearchParams({
    vers: String(state.comptesRepartitionMonnaieId),
  });
  const reponse = await apiFetch(`/conversion/dashboard?${parametres}`);
  avoirsNonConvertis = reponse.non_converties || [];
  if (!reponse.dashboard) return;
  renderRepartitionComptes(
    reponse.dashboard.comptes,
    state.comptesRepartitionMonnaieId,
    // Déjà convertie par le serveur, comme le reste des chiffres.
    reponse.dashboard.kpis[0].valorisation_placements
  );
}

// On enveloppe le rendu du camembert du noyau, et non le chargeur de la page :
// changer de monnaie dans le menu passe par lui sans recharger quoi que ce
// soit, et la vue convertie doit suivre ce geste-là aussi.
const renderRepartitionAvoirsAvantGreffe = window.renderRepartitionAvoirs;
window.renderRepartitionAvoirs = function () {
  renderRepartitionAvoirsAvantGreffe();
  poserBasculeAvoirs();
  if (!avoirsAgreges || !agregationDisponible()) {
    avoirsNonConvertis = [];
    majAlerteAvoirs();
    return;
  }
  appliquerAgregationAvoirs()
    .catch((err) => {
      // La vue par monnaie est déjà à l'écran : on la laisse, et on dit
      // pourquoi la conversion n'a pas eu lieu.
      showMessage(err.message, "error");
      avoirsAgreges = false;
      const case_ = document.getElementById("monnaies-avoirs-case");
      if (case_) case_.checked = false;
    })
    .finally(majAlerteAvoirs);
};

const loadDashboardDataAvantGreffe = window.loadDashboardData;
window.loadDashboardData = async function (annee, mois) {
  await loadDashboardDataAvantGreffe(annee, mois);
  poserBasculeAgregation();
  if (!agregationActive || !agregationDisponible()) {
    agregationNonConverties = [];
    majAlerteAgregation();
    return;
  }
  try {
    await appliquerAgregation(annee, mois);
  } catch (err) {
    // La vue par monnaie est déjà à l'écran : on la laisse, et on dit
    // pourquoi la conversion n'a pas eu lieu.
    showMessage(err.message, "error");
    agregationActive = false;
    const case_ = document.getElementById("monnaies-agregation-case");
    if (case_) case_.checked = false;
  }
  majAlerteAgregation();
};

// Le noyau rappelle ce chargeur à chaque ouverture de la sous-page.
BudgetApp.extensions.enregistrer("monnaies", { chargeur: loadMonnaies });
