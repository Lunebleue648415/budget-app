/* ---------- Extension « Import de placements » ----------
 *
 * L'écran d'import du noyau, transposé aux relevés de compte-titres : mêmes
 * gestes, même ordre, mêmes classes CSS — seules les colonnes lues et les
 * sections de l'aperçu changent.
 *
 * CHARGÉ PAR frontend/extensions.js, après que le fragment page.html a été
 * injecté dans <main> : les écouteurs posés plus bas trouvent donc bien leurs
 * éléments. Le script s'exécute dans la portée globale de la page, il a donc
 * accès à tout ce que app.js expose (apiFetch, apiFetchForm, showMessage,
 * formatMontant, escapeHtml, state, t, ICONE_OEIL…) — c'est ce qui évite de
 * dupliquer ces utilitaires ici.
 *
 * TOUS LES IDENTIFIANTS SONT PRÉFIXÉS `impl-` et toutes les variables `impl`.
 * Cet écran vit dans le MÊME document que la page Import du noyau : un
 * identifiant partagé ferait travailler l'un sur les éléments de l'autre, avec
 * des symptômes indébrouillables (un aperçu qui se vide, une configuration qui
 * s'écrit dans le mauvais preset).
 *
 * L'enregistrement auprès du noyau est en FIN de fichier : `loadImportPlacements`
 * doit exister au moment où on la référence.
 */

const IMPL_BASE = "/import-placements";

// Les sept propriétés lisibles, dans l'ordre où l'écran les présente (miroir de
// constants.PROPRIETES_IMPORT_PLACEMENT).
const IMPL_PROPRIETES = [
  ["date", "Date de l'opération"],
  ["type_placement", "Type d'opération"],
  ["nom_valeur", "Nom de la valeur"],
  ["code_isin", "Code ISIN"],
  ["montant", "Montant de l'opération"],
  ["quantite", "Quantité"],
  ["cours", "Cours"],
  ["type_titre", "Type de titre"],
];

// Celles qu'un preset lit forcément (miroir de
// constants.PROPRIETES_IMPORT_PLACEMENT_OBLIGATOIRES) : leur œil est
// désactivé, plutôt que de laisser éteindre une colonne que le serveur
// refusera d'enregistrer.
const IMPL_PROPRIETES_OBLIGATOIRES = new Set([
  "date",
  "type_placement",
  "montant",
  "quantite",
]);

// Le nom et l'ISIN : facultatifs SÉPARÉMENT, jamais ensemble. Éteindre le
// dernier des deux est refusé côté serveur ; ici, l'œil est simplement grisé
// pour que le geste n'ait pas lieu (cf. implProprieteObligatoire).
const IMPL_PROPRIETES_IDENTITE = ["nom_valeur", "code_isin"];

/* ---------- Ce que le fichier raconte ----------
 *
 * Une LISTE D'OPÉRATIONS rejoue l'histoire du compte : une ligne par achat,
 * vente ou transfert, chacune datée. Une PHOTOGRAPHIE constate son état à un
 * instant donné : une ligne par titre détenu, sans aucune date.
 *
 * Les deux jeux de colonnes ne se recouvrent qu'à moitié (le titre, la
 * quantité), et surtout ne veulent pas dire la même chose : proposer les deux
 * ensemble donnerait une configuration qui a l'air complète et n'importe rien.
 * D'où deux tables, et un aiguillage unique (`implProprietesLues`).
 */
const IMPL_PROPRIETES_POSITION = [
  ["nom_valeur", "Nom de la valeur"],
  ["code_isin", "Code ISIN"],
  ["quantite", "Quantité détenue"],
  ["prix_revient", "Prix de revient unitaire"],
  ["valeur_totale", "Valorisation actuelle"],
  ["type_titre", "Type de titre"],
];

const IMPL_PROPRIETES_POSITION_OBLIGATOIRES = new Set(["quantite", "prix_revient"]);

// Écrit une fois : la colonne veut dire la même chose dans les deux modes de
// lecture, et deux textes qui se répondent finiraient par diverger.
const IMPL_INFO_COLONNE_TYPE_TITRE =
  "L'étiquette du titre, si ton fichier la porte : ETF, obligation, action…\n\n" +
  "Facultative, et sans effet sur un montant. Un libellé que tu n'as pas encore " +
  "créé le sera à l'import. Un titre que l'app connaît déjà garde le type que tu " +
  "lui as posé.";

const IMPL_INFOS_PROPRIETES_POSITION = {
  quantite:
    "Le nombre de titres que tu DÉTIENS au moment de la photographie.\n\n" +
    "C'est cette quantité qui part en base : l'app ne sait pas comment tu y es " +
    "arrivé, seulement ce que tu as.",
  prix_revient:
    "Ce qu'UN titre t'a coûté en moyenne, frais compris (le PRU).\n\n" +
    "Par titre, pas le total investi. Si ton relevé donne le total, divise-le " +
    "avant d'importer.",
  valeur_totale:
    "Ce que la ligne vaut aujourd'hui, tous titres confondus.\n\n" +
    "Elle ne crée aucune détention : elle sert à déduire le cours du titre " +
    "(valeur ÷ quantité), que ce genre d'export ne donne pas.",
  type_titre: IMPL_INFO_COLONNE_TYPE_TITRE,
};

/** Le mode déclaré par l'écran, `operations` tant qu'on n'a rien dit. */
function implModeLecture() {
  const champ = document.getElementById("impl-mode-lecture");
  return champ ? champ.value : "operations";
}

function implLitUnePosition() {
  return implModeLecture() === "position";
}

/** Les propriétés lisibles, et lesquelles sont obligatoires, selon le mode. */
function implProprietesLues() {
  return implLitUnePosition() ? IMPL_PROPRIETES_POSITION : IMPL_PROPRIETES;
}

function implProprietesObligatoires() {
  return implLitUnePosition()
    ? IMPL_PROPRIETES_POSITION_OBLIGATOIRES
    : IMPL_PROPRIETES_OBLIGATOIRES;
}

function implInfosProprietes() {
  return implLitUnePosition() ? IMPL_INFOS_PROPRIETES_POSITION : IMPL_INFOS_PROPRIETES;
}

const IMPL_INFOS_PROPRIETES = {
  type_placement:
    "Ce que la ligne décrit : un achat, une vente, ou un transfert d'espèces.\n\n" +
    "Les mots-clés se règlent juste en dessous. Un libellé inconnu met la ligne " +
    "en erreur plutôt que d'être deviné.",
  nom_valeur:
    "Le nom du titre tel que ton courtier l'écrit.\n\n" +
    "Facultatif si tu lis l'ISIN, mais il faut l'un des deux : sans eux, une " +
    "ligne d'achat ne dit pas de quelle valeur elle parle.",
  code_isin:
    "Le code ISIN du titre (FR0000120073, LU1681043599…).\n\n" +
    "Seul nom qui ne change jamais : c'est par lui qu'un titre est reconnu d'un " +
    "import à l'autre. Facultatif si tu lis le nom de la valeur.",
  montant:
    "Ce que l'opération a coûté ou rapporté en espèces.\n\n" +
    "C'est lui qui fait foi : le prix par titre vaut montant ÷ quantité, pas le " +
    "cours annoncé. Ton solde colle ainsi au relevé, frais de courtage compris.",
  quantite:
    "Le nombre de titres achetés ou vendus.\n\n" +
    "Sans objet sur une ligne de transfert d'espèces, qui peut la laisser vide.",
  cours:
    "Le prix par titre annoncé par le relevé.\n\n" +
    "Il ne décide de rien, il sert de contrôle : un écart de plus de 1 % avec " +
    "le montant divisé par la quantité est signalé au-dessus de l'aperçu, sans " +
    "bloquer l'import.",
  type_titre: IMPL_INFO_COLONNE_TYPE_TITRE,
};

// Ce que l'en-tête de « Le fichier tel qu'il est » écrit pour chaque propriété.
const IMPL_APERCU_PROPRIETES = Object.fromEntries(IMPL_PROPRIETES);

const IMPL_LIBELLES_TYPE = {
  achat: "Achat",
  vente: "Vente",
  transfert: "Transfert interne",
};

const IMPL_CLE_PRESET_MEMORISE = "budget-app.import-placements.preset";

/* ---------- État de l'écran ---------- */

let implPresets = [];
let implPresetId = null;
let implComptesPlacement = [];
let implTitres = [];
// Les virements déjà en base qui ressemblent à une ligne de l'aperçu, par
// numéro de ligne. Rempli par la veille (`rafraichirDoublonsTransferts`), lu par
// le rendu pour ranger ces lignes dans leur propre section.
let implSuspectsParLigne = {};
let implVocabulaireDefaut = {};

let implConfigColonnes = [];
let implConfigColonnesComparaison = [];
// Le numéro d'une colonne éteinte, mis de côté : la rallumer doit redonner
// exactement la même configuration.
const implIndexMemorises = {};

let implFichier = null;
let implApercu = null;
let implReglageDelimiteur = null;
let implReglageSeparateurDecimal = null;

// Retouches de l'aperçu, par numéro de ligne.
const implOverrides = {};
const implLignesSupprimees = new Set();
const implLignesSelectionnees = new Set();
let implLigneEnEdition = null;

/* ---------- Utilitaires ---------- */

function implUrl(chemin) {
  return `${IMPL_BASE}/presets/${implPresetId}${chemin}`;
}

function implPresetActuel() {
  return implPresets.find((p) => p.id === implPresetId) || null;
}

function implCompteDuFichier() {
  const preset = implPresetActuel();
  if (preset && preset.compte_id) return preset.compte_id;
  const select = document.getElementById("impl-compte-defaut");
  return select && select.value ? Number(select.value) : null;
}

function implNomCompte(compteId) {
  const compte = state.comptes.find((c) => c.id === compteId);
  return compte ? compte.nom : "—";
}

/** Un nombre tel qu'on l'écrirait : « 12 » et non « 12.0 », « 0,5 » si la
 *  fraction compte (les ETF s'achètent en fractions). */
function implQuantite(valeur) {
  if (valeur === null || valeur === undefined) return "—";
  const arrondie = Math.round(valeur * 1e6) / 1e6;
  return Number.isInteger(arrondie) ? String(arrondie) : String(arrondie);
}

/* ---------- Presets ---------- */

function renderImplPresetChips() {
  const bloc = document.getElementById("impl-preset-chips");
  bloc.innerHTML = "";
  if (implPresets.length === 0) {
    bloc.innerHTML = `<span class="hint">${t("Aucun preset. Crée-en un pour commencer.")}</span>`;
    return;
  }
  implPresets.forEach((p) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = p.nom;
    btn.classList.toggle("active", p.id === implPresetId);
    btn.addEventListener("click", async () => {
      if (p.id === implPresetId) return;
      implPresetId = p.id;
      localStorage.setItem(IMPL_CLE_PRESET_MEMORISE, String(implPresetId));
      renderImplPresetChips();
      await chargerPresetImpl();
    });
    bloc.appendChild(btn);
  });
}

async function loadImplPresets() {
  implPresets = await apiFetch(`${IMPL_BASE}/presets`);
  if (!implPresets.some((p) => p.id === implPresetId)) {
    const memorise = Number(localStorage.getItem(IMPL_CLE_PRESET_MEMORISE));
    implPresetId = implPresets.some((p) => p.id === memorise)
      ? memorise
      : implPresetParDefaut();
  }
  if (implPresetId) localStorage.setItem(IMPL_CLE_PRESET_MEMORISE, String(implPresetId));
  renderImplPresetChips();
}

// Le preset le plus récemment utilisé plutôt que le premier par ordre
// alphabétique, qui peut être vide et donner l'impression que tout a disparu.
function implPresetParDefaut() {
  if (implPresets.length === 0) return null;
  const utilises = implPresets.filter((p) => p.dernier_import);
  if (utilises.length === 0) return implPresets[0].id;
  return utilises.reduce((a, b) => (a.dernier_import >= b.dernier_import ? a : b)).id;
}

/* ---------- Configuration des colonnes ---------- */

/**
 * Une propriété dont l'œil est désactivé, parce que l'éteindre donnerait une
 * configuration que le serveur refuse d'enregistrer.
 *
 * Le nom de la valeur et le code ISIN en font partie DÈS QUE L'AUTRE EST
 * ÉTEINT : les deux sont facultatifs, mais pas en même temps — sans eux, aucune
 * ligne d'achat ou de vente ne peut désigner de titre. Griser l'œil du dernier
 * survivant dit la règle au moment où elle s'applique, plutôt que de laisser
 * faire le geste et de le refuser ensuite.
 */
function implProprieteObligatoire(propriete) {
  if (implProprietesObligatoires().has(propriete)) return true;
  if (!IMPL_PROPRIETES_IDENTITE.includes(propriete)) return false;
  const actives = IMPL_PROPRIETES_IDENTITE.filter((p) =>
    implConfigColonnes.some((c) => c.propriete === p)
  );
  return actives.length === 1 && actives[0] === propriete;
}

function implProchainIndexLibre() {
  const pris = new Set(implConfigColonnes.map((c) => c.index));
  let index = 1;
  while (pris.has(index)) index += 1;
  return index;
}

function implBasculerPropriete(propriete, allumer) {
  if (allumer) {
    if (implConfigColonnes.some((c) => c.propriete === propriete)) return;
    implConfigColonnes.push({
      propriete,
      index: implIndexMemorises[propriete] ?? implProchainIndexLibre(),
    });
    return;
  }
  const colonne = implConfigColonnes.find((c) => c.propriete === propriete);
  if (!colonne) return;
  implIndexMemorises[propriete] = colonne.index;
  implConfigColonnes.splice(implConfigColonnes.indexOf(colonne), 1);
}

function creerLigneConfigImpl(propriete, libelle, actif) {
  const colonne = actif ? implConfigColonnes.find((c) => c.propriete === propriete) : null;
  const obligatoire = implProprieteObligatoire(propriete);
  const index = colonne ? colonne.index : implIndexMemorises[propriete] ?? "";
  const info = implInfosProprietes()[propriete];
  const bulle = info
    ? `<i class="info-bulle info-bulle-texte" tabindex="0" data-info="${escapeHtml(t(info))}">i</i>`
    : "";

  // L'infobulle du bouton dit POURQUOI il est grisé quand il l'est : « cette
  // propriété est obligatoire » n'explique rien pour le nom et l'ISIN, dont
  // c'est le couple qui est obligatoire, pas chacun.
  const titreBouton = !obligatoire
    ? actif
      ? t("Ne plus lire cette colonne")
      : t("Lire cette colonne")
    : IMPL_PROPRIETES_IDENTITE.includes(propriete)
      ? t("Garde le nom de la valeur ou le code ISIN : sans l'un des deux, aucune ligne ne peut dire de quel titre elle parle.")
      : t("Cette propriété est obligatoire : elle ne peut pas être désactivée.");

  const row = document.createElement("div");
  row.className = `import-mapping-row import-config-ligne${actif ? "" : " inactive"}`;
  row.innerHTML = `
    <span class="import-config-propriete">${escapeHtml(t(libelle))}${bulle}</span>
    <label class="import-config-index">${t("Colonne n°")}
      <input type="number" min="1" value="${index}" ${actif ? "" : "disabled"} />
    </label>
    <button type="button" class="import-config-oeil" data-action="basculer"
            title="${escapeHtml(titreBouton)}"
            ${obligatoire ? "disabled" : ""}>${actif ? ICONE_OEIL : ICONE_OEIL_BARRE}</button>
  `;
  row.querySelector("input").addEventListener("input", (e) => {
    if (colonne) colonne.index = Number(e.target.value) || 0;
  });
  row.querySelector("button[data-action='basculer']").addEventListener("click", () => {
    implBasculerPropriete(propriete, !actif);
    renderImplConfig();
  });
  return row;
}

function renderImplConfig() {
  const bloc = document.getElementById("impl-config-colonnes");
  bloc.innerHTML = "";
  const estActive = (p) => implConfigColonnes.some((c) => c.propriete === p);
  implProprietesLues().forEach(([propriete, libelle]) => {
    bloc.appendChild(creerLigneConfigImpl(propriete, libelle, estActive(propriete)));
  });
  renderImplConfigComparaison();
  majVisibiliteModeImpl();
}

/**
 * Ce que le mode de lecture montre et cache, d'un bout à l'autre de l'écran.
 *
 * Le vocabulaire du type d'opération et l'onglet « Règles » ne servent qu'à une
 * LISTE D'OPÉRATIONS : ils décident de ce qu'une ligne décrit, question qui ne
 * se pose pas sur une photographie où toute ligne décrit un titre détenu. Les
 * laisser visibles proposerait de régler quelque chose qui ne sera jamais lu.
 *
 * La date de la photographie fait l'inverse : elle n'existe que là, parce que
 * c'est la seule chose qu'un relevé de position ne dit pas.
 */
function majVisibiliteModeImpl() {
  const position = implLitUnePosition();
  const vocabulaire = document.getElementById("impl-vocabulaire-section");
  if (vocabulaire) vocabulaire.style.display = position ? "none" : "";
  const dateBloc = document.getElementById("impl-date-position-bloc");
  if (dateBloc) dateBloc.style.display = position ? "" : "none";
  const ongletRegles = document.querySelector(
    '#impl-onglets button[data-onglet-impl="regles"]'
  );
  if (ongletRegles) ongletRegles.style.display = position ? "none" : "";
}

function implModeComparaison() {
  return document.getElementById("impl-mode-comparaison").value;
}

/**
 * Les colonnes de la comparaison de doublons, et surtout ce que veut dire une
 * liste VIDE — qui n'est pas la même chose des deux côtés : en exclusion tout
 * est comparé, en sélection plus rien ne le serait (chaque ligne deviendrait
 * le doublon de la première). Le serveur refuse le second cas ; on le dit ici
 * avant d'y arriver.
 */
function renderImplConfigComparaison() {
  const bloc = document.getElementById("impl-config-colonnes-comparaison");
  const selection = implModeComparaison() === "selection";
  const nb = implConfigColonnesComparaison.length;
  document.getElementById("impl-config-fichier-resume").textContent =
    `${implConfigColonnes.length} ${t("colonne(s) lue(s)")} · ` +
    (selection
      ? `${t("doublons : {n} colonne(s) comparée(s)").replace("{n}", nb)}`
      : nb === 0
        ? t("doublons : toutes les colonnes")
        : `${t("doublons : toutes sauf {n}").replace("{n}", nb)}`);

  bloc.innerHTML = "";
  if (nb === 0) {
    bloc.innerHTML = selection
      ? `<p class="hint erreur-hint">${t("Aucune colonne choisie : ajoute-en au moins une, sinon plus rien ne distingue deux lignes.")}</p>`
      : `<p class="hint">${t("Aucune colonne exclue : toutes les colonnes du fichier sont comparées.")}</p>`;
    return;
  }
  implConfigColonnesComparaison.forEach((index, i) => {
    const row = document.createElement("div");
    row.className = "import-mapping-row";
    row.innerHTML = `
      <label class="import-config-index">${t("Colonne n°")}
        <input type="number" min="1" value="${index}" />
      </label>
      <button type="button" class="danger" data-action="supprimer">${t("Supprimer")}</button>
    `;
    row.querySelector("input").addEventListener("input", (e) => {
      implConfigColonnesComparaison[i] = Number(e.target.value) || 0;
    });
    row.querySelector("button[data-action='supprimer']").addEventListener("click", () => {
      implConfigColonnesComparaison.splice(i, 1);
      renderImplConfigComparaison();
    });
    bloc.appendChild(row);
  });
}

/* ---------- Vocabulaire des trois types (mots-clés) ---------- */

/**
 * L'ÉDITEUR EST CELUI DU NOYAU (`creerEditeurMotsCles`, app.js) : un champ, son
 * « + », les jetons qui montrent la liste, et le menu « Actualisation » qui en
 * retire. C'est le même geste que pour les colonnes « Sens » et « État » d'un
 * relevé bancaire, et deux implémentations auraient fini par diverger.
 *
 * Il ne reste ici que ce qui est propre aux placements : les trois listes, et
 * la table qui relie la clé du DOM au champ du preset.
 */
const IMPL_GROUPE_VOCABULAIRE = "impl-type";

// clé du DOM (`data-vocabulaire`) -> champ du preset qui part au serveur.
const IMPL_CHAMPS_VOCABULAIRE = {
  achat: "libelles_type_achat",
  vente: "libelles_type_vente",
  transfert: "libelles_type_transfert",
};

// Les noms lisibles des trois listes, pour le message qui refuse un mot-clé
// déjà pris par une autre : confondre un achat et une vente inverserait une
// position entière, autant le dire avant l'enregistrement.
const IMPL_LIBELLES_TYPES = {
  achat: "Achat",
  vente: "Vente",
  transfert: "Transfert interne",
};

creerEditeurMotsCles(IMPL_GROUPE_VOCABULAIRE, {
  conteneur: "impl-vocabulaire-bloc",
  libelles: IMPL_LIBELLES_TYPES,
});

function renderImplVocabulaire(preset) {
  const valeurs = {};
  Object.entries(IMPL_CHAMPS_VOCABULAIRE).forEach(([cle, champ]) => {
    valeurs[cle] = preset[champ] || [];
    // Les mots par défaut sont rappelés sous le champ : sans eux, « laisser
    // vide » ne veut rien dire, et on recopie par prudence un vocabulaire
    // qu'on a déjà. Ceux-là restent en liste séparée par des virgules — ils ne
    // se saisissent pas, ils se lisent.
    document.getElementById(`impl-type-${cle}-defaut`).textContent = (
      implVocabulaireDefaut[cle] || []
    ).join(", ");
  });
  chargerMotsCles(IMPL_GROUPE_VOCABULAIRE, valeurs);
}

function implVocabulaireSaisi() {
  const mots = motsClesSaisis(IMPL_GROUPE_VOCABULAIRE);
  const saisi = {};
  Object.entries(IMPL_CHAMPS_VOCABULAIRE).forEach(
    ([cle, champ]) => (saisi[champ] = mots[cle] || [])
  );
  return saisi;
}

async function loadImplConfiguration() {
  const preset = await apiFetch(implUrl(""));
  implConfigColonnes = preset.colonnes.map((c) => ({ ...c }));
  implConfigColonnesComparaison = [...(preset.colonnes_comparaison || [])];
  document.getElementById("impl-mode-comparaison").value = preset.mode_comparaison;
  document.getElementById("impl-ignorer-premiere-ligne").checked =
    preset.ignorer_premiere_ligne;
  document.getElementById("impl-preset-compte").value = preset.compte_id || "";
  // AVANT `renderImplConfig` : c'est le mode qui décide des colonnes proposées.
  document.getElementById("impl-mode-lecture").value =
    preset.mode_lecture || "operations";
  renderImplVocabulaire(preset);
  renderImplConfig();
  updateImplCompteDefautVisibilite();
}

async function enregistrerImplConfiguration() {
  const preset = implPresetActuel();
  if (!preset) return;
  const compteSelect = document.getElementById("impl-preset-compte");
  try {
    await apiFetch(implUrl(""), {
      method: "PUT",
      body: JSON.stringify({
        nom: preset.nom,
        compte_id: compteSelect.value ? Number(compteSelect.value) : null,
        colonnes: implConfigColonnes,
        colonnes_comparaison: implConfigColonnesComparaison,
        mode_comparaison: implModeComparaison(),
        ignorer_premiere_ligne: document.getElementById("impl-ignorer-premiere-ligne")
          .checked,
        mode_lecture: implModeLecture(),
        ...implVocabulaireSaisi(),
      }),
    });
    showMessage(t("Configuration enregistrée"), "success");
    await loadImplPresets();
    await loadImplConfiguration();
    // Un fichier déjà chargé doit être relu avec la nouvelle configuration :
    // le laisser tel quel afficherait un aperçu que la configuration
    // enregistrée ne produit plus.
    if (implFichier) await analyserFichierImpl();
  } catch (err) {
    showMessage(err.message, "error");
  }
}

/* ---------- Le fichier ---------- */

function reinitialiserImpl() {
  implFichier = null;
  implApercu = null;
  Object.keys(implOverrides).forEach((k) => delete implOverrides[k]);
  implLignesSupprimees.clear();
  implLignesSelectionnees.clear();
  implLigneEnEdition = null;
  implReglageDelimiteur = null;
  implReglageSeparateurDecimal = null;
  const fichier = document.getElementById("impl-fichier");
  if (fichier) fichier.value = "";
  document.getElementById("impl-fichier-nom").textContent = "";
  document.getElementById("impl-reglage-delimiteur").value = "";
  document.getElementById("impl-reglage-separateur-decimal").value = "";
  document.getElementById("impl-reglages-lecture").open = false;
  document.getElementById("impl-reglages-lecture-alerte").style.display = "none";
  [
    "impl-apercu-bloc",
    "impl-apercu-fichier-bloc",
    "impl-avertissements",
    "impl-titres-a-creer-bloc",
    "impl-resultat",
  ].forEach((id) => {
    document.getElementById(id).style.display = "none";
  });
  // Les ressemblances vivent maintenant DANS l'aperçu (une section de plus) :
  // masquer le bloc d'aperçu les emporte, il ne reste qu'à oublier ce que la
  // veille avait trouvé pour le fichier précédent.
  implSuspectsParLigne = {};
}

function definirFichierImpl(fichier) {
  implFichier = fichier || null;
  document.getElementById("impl-fichier-nom").textContent = fichier ? fichier.name : "";
  if (fichier) analyserFichierImpl();
}

const IMPL_DELIMITEURS = { PV: ";", VIRGULE: ",", TAB: "\t" };

/**
 * Le fichier et tout ce qui conditionne sa lecture, pour la prévisualisation
 * comme pour la confirmation.
 *
 * LES RETOUCHES EN FONT PARTIE. C'est le serveur qui recalcule ce qu'une
 * correction entraîne (le prix unitaire d'une quantité changée, la monnaie
 * d'un titre choisi, l'erreur qui tombe quand le compte en face arrive) : ne
 * pas les lui envoyer à la prévisualisation ferait afficher un aperçu qui
 * n'est plus celui qu'on va importer.
 */
function implFormDataFichier() {
  const formData = new FormData();
  formData.append("fichier", implFichier);
  formData.append("overrides", JSON.stringify({ lignes: implOverrides }));
  const compteId = implCompteDuFichier();
  if (compteId) formData.append("compte_id_defaut", compteId);
  if (implReglageDelimiteur) formData.append("delimiteur", implReglageDelimiteur);
  if (implReglageSeparateurDecimal)
    formData.append("separateur_decimal", implReglageSeparateurDecimal);
  // La date de la PHOTOGRAPHIE, que le fichier ne porte pas. Aujourd'hui à
  // défaut : c'est le cas de très loin le plus fréquent, un relevé de position
  // se télécharge le jour où on le regarde.
  if (implLitUnePosition()) {
    formData.append("date_position", implDatePosition());
  }
  return formData;
}

/** La date de la photo, ou aujourd'hui tant qu'on n'en a pas choisi une. */
function implDatePosition() {
  const champ = document.getElementById("impl-date-position");
  if (champ && champ.value) return champ.value;
  return new Date().toISOString().slice(0, 10);
}

async function analyserFichierImpl() {
  if (!implFichier || !implPresetId) return;
  // Un nouvel aperçu remplace l'ancien : les retouches faites sur les lignes
  // du précédent ne veulent plus rien dire (les numéros peuvent avoir changé).
  Object.keys(implOverrides).forEach((k) => delete implOverrides[k]);
  implLignesSupprimees.clear();
  implLignesSelectionnees.clear();
  implLigneEnEdition = null;
  try {
    implApercu = await apiFetchForm(implUrl("/previsualiser"), implFormDataFichier());
  } catch (err) {
    showMessage(err.message, "error");
    return;
  }
  // Les doublons sont pré-sélectionnés : tant qu'une ligne reste sélectionnée,
  // la confirmation est bloquée. L'utilisateur supprime, ou décoche.
  implApercu.lignes
    .filter((l) => l.doublon_de !== null && l.doublon_de !== undefined)
    .forEach((l) => implLignesSelectionnees.add(l.ligne));
  // Un titre DÉJÀ DÉTENU est pré-sélectionné pour les mêmes raisons qu'un
  // doublon : l'importer s'ajouterait à ce qui est là, et c'est presque
  // toujours une photo qu'on rejoue. Presque, pas toujours — d'où une case
  // qu'on décoche plutôt qu'un blocage.
  implApercu.lignes
    .filter(
      (l) => l.quantite_deja_detenue !== null && l.quantite_deja_detenue !== undefined
    )
    .forEach((l) => implLignesSelectionnees.add(l.ligne));

  renderApercuFichierImpl();
  renderImplAvertissements();
  renderImplTitresACreer();
  renderImplApercu();
  await rafraichirDoublonsTransferts();
  proposerReglagesLectureImpl();
}

/**
 * Ouvre d'office les réglages de lecture quand l'aperçu est manifestement
 * illisible.
 *
 * Une majorité de lignes en « date illisible » ou « montant illisible » n'est
 * presque jamais un problème de données : c'est un délimiteur hors des
 * candidats usuels, ou un format anglo-saxon où la virgule sépare les
 * milliers. Le dire ici évite de chercher du côté de la configuration des
 * colonnes, qui n'y est pour rien.
 */
function proposerReglagesLectureImpl() {
  const lignes = implApercu ? implApercu.lignes : [];
  const illisibles = lignes.filter(
    (l) => l.erreur === "date illisible" || l.erreur === "montant illisible"
  ).length;
  const alerte = document.getElementById("impl-reglages-lecture-alerte");
  if (lignes.length === 0 || illisibles < lignes.length / 2) {
    alerte.style.display = "none";
    return;
  }
  alerte.style.display = "";
  alerte.textContent = t(
    "La plupart des lignes sont illisibles : le délimiteur ou le séparateur décimal ne convient probablement pas à ce fichier."
  );
  document.getElementById("impl-reglages-lecture").open = true;
}

function renderApercuFichierImpl() {
  const bloc = document.getElementById("impl-apercu-fichier-bloc");
  const apercu = implApercu && implApercu.apercu_fichier;
  if (!apercu || apercu.lignes.length === 0) {
    bloc.style.display = "none";
    return;
  }
  bloc.style.display = "";
  const largeur = apercu.lignes.reduce((max, l) => Math.max(max, l.length), 0);
  const classe = (i) => {
    const propriete = apercu.proprietes_par_colonne[String(i)];
    return propriete ? `col-${propriete}` : "col-ignoree";
  };

  const entetes = [];
  for (let i = 1; i <= largeur; i++) {
    const propriete = apercu.proprietes_par_colonne[String(i)];
    const libelle = propriete
      ? IMPL_APERCU_PROPRIETES[propriete] || propriete
      : "non importée";
    entetes.push(
      `<th class="${classe(i)}"><span class="apercu-col-num">n°${i}</span>${escapeHtml(t(libelle))}</th>`
    );
  }
  const corps = apercu.lignes
    .map((ligne, index) => {
      // La ligne d'en-tête ignorée est montrée mais barrée : voir qu'elle est
      // bien exclue vaut mieux que de la faire disparaître silencieusement.
      const enteteIgnoree = apercu.premiere_ligne_ignoree && index === 0;
      const cellules = [];
      for (let i = 1; i <= largeur; i++) {
        cellules.push(`<td class="${classe(i)}">${escapeHtml(ligne[i - 1] || "")}</td>`);
      }
      return `<tr class="${enteteIgnoree ? "apercu-ligne-ignoree" : ""}">${cellules.join("")}</tr>`;
    })
    .join("");
  document.getElementById("impl-apercu-fichier-table").innerHTML =
    `<thead><tr>${entetes.join("")}</tr></thead><tbody>${corps}</tbody>`;
  document.getElementById("impl-apercu-fichier-info").textContent = `${apercu.total_lignes} ${t(
    "ligne(s) au total — fais défiler le tableau pour les voir toutes."
  )}`;
}

function renderImplAvertissements() {
  const bloc = document.getElementById("impl-avertissements");
  const messages = (implApercu && implApercu.avertissements) || [];
  if (messages.length === 0) {
    bloc.style.display = "none";
    return;
  }
  bloc.style.display = "";
  bloc.innerHTML = messages
    .map((m) => `<p class="import-avertissement">${escapeHtml(t(m))}</p>`)
    .join("");
}

function renderImplTitresACreer() {
  const bloc = document.getElementById("impl-titres-a-creer-bloc");
  const noms = (implApercu && implApercu.titres_a_creer) || [];
  if (noms.length === 0) {
    bloc.style.display = "none";
    return;
  }
  bloc.style.display = "";
  document.getElementById("impl-titres-a-creer").innerHTML = noms
    .map((nom) => `<div class="import-mapping-row"><span>${escapeHtml(nom)}</span></div>`)
    .join("");
}

/* ---------- Rapprochement des transferts ---------- */

/**
 * Les transferts de l'aperçu confrontés aux virements DÉJÀ en base.
 *
 * C'est le pendant de la veille du noyau, et elle interroge le même détecteur :
 * un transfert lu ici se rapproche aussi bien d'un virement saisi à la main que
 * d'un virement importé d'un relevé bancaire. Le même mouvement figure sur les
 * deux relevés — c'est précisément le cas qu'il faut voir.
 *
 * Rappelée à chaque changement de l'aperçu (chargement, saisie du compte en
 * face) et non au moment de confirmer : la question se pose pendant qu'on
 * compose l'import, pas une fois qu'il est parti.
 */
async function rafraichirDoublonsTransferts() {
  if (!implApercu) {
    implSuspectsParLigne = {};
    return;
  }
  // Les lignes du serveur portent déjà les retouches (elles lui sont envoyées
  // à la prévisualisation) : les refusionner ici ferait un second endroit où
  // la même chose se décide.
  const lignes = implApercu.lignes.filter((l) => !implLignesSupprimees.has(l.ligne));
  let reponse;
  try {
    reponse = await apiFetch(implUrl("/doublons-transferts"), {
      method: "POST",
      body: JSON.stringify({ lignes }),
    });
  } catch {
    // Purement consultatif : un échec ici ne doit pas empêcher d'importer.
    implSuspectsParLigne = {};
    renderImplApercu();
    return;
  }
  implSuspectsParLigne = {};
  (reponse.resultats || []).forEach((r) => {
    if (r.suspects && r.suspects.length) implSuspectsParLigne[r.ligne] = r.suspects;
  });
  // Le rendu range les lignes concernées dans leur propre section : la veille
  // arrive APRÈS le premier affichage de l'aperçu (elle est un aller-retour de
  // plus), il faut donc le refaire une fois qu'on sait.
  renderImplApercu();
}

/* ---------- L'aperçu ---------- */

/**
 * Un transfert dont le SEUL manque est le compte en face reste dans la section
 * « Transferts internes ».
 *
 * C'est le cas ordinaire et non un accident : un relevé de compte-titres ne
 * nomme JAMAIS le compte d'en face, il ne décrit qu'un côté du mouvement. Le
 * ranger dans « Lignes en erreur » enverrait chaque transfert du fichier dans
 * la corbeille, alors que la colonne où le renseigner est précisément dans la
 * section des transferts. L'import reste refusé côté serveur tant que le compte
 * manque — c'est là que la règle est tenue, pas dans le classement à l'écran.
 */
function transfertACompleter(ligne) {
  return (
    ligne.type_placement === "transfert" &&
    ligne.date &&
    ligne.montant !== null &&
    ligne.montant !== undefined &&
    ligne.compte_id_autre === null
  );
}

/**
 * Les six sections de l'aperçu, dans l'ordre où elles se décident.
 *
 * NI LES DOUBLONS NI LES RESSEMBLANCES NE REJOIGNENT LEUR SECTION DE TYPE,
 * exactement comme dans l'aperçu d'un relevé bancaire : ce ne sont pas des
 * lignes de plus à relire, ce sont des décisions à prendre, et les noyer parmi
 * trente achats revenait à demander de les chercher.
 *
 * L'ORDRE COMPTE. Un doublon avéré (la même ligne déjà importée sous ce preset)
 * passe avant une ressemblance (un virement qui pourrait être le même
 * mouvement) : le premier est un fait, le second une question.
 */
function implGroupes() {
  const groupes = {
    position: [],
    achat: [],
    vente: [],
    transfert: [],
    doublon: [],
    ressemblance: [],
    erreur: [],
  };
  if (!implApercu) return groupes;
  const position = implLitUnePosition();
  implApercu.lignes
    .filter((l) => !implLignesSupprimees.has(l.ligne))
    .forEach((brute) => {
      // La ligne du SERVEUR fait foi, retouches comprises : elles lui sont
      // envoyées à la prévisualisation, et toute retouche déclenche une
      // relecture (cf. appliquerRetoucheImpl). Rien n'est recalculé ici.
      const ligne = brute;
      if (ligne.doublon_de !== null && ligne.doublon_de !== undefined) {
        groupes.doublon.push(ligne);
      } else if (position) {
        // Une photographie n'a qu'une section : toutes ses lignes décrivent la
        // même chose, un titre détenu. Seules les lignes en erreur s'en
        // détachent, comme partout ailleurs.
        if (ligne.erreur) groupes.erreur.push(ligne);
        else groupes.position.push(ligne);
      } else if (implSuspectsParLigne[ligne.ligne]) {
        groupes.ressemblance.push(ligne);
      } else if (transfertACompleter(ligne)) groupes.transfert.push(ligne);
      else if (ligne.erreur) groupes.erreur.push(ligne);
      else if (ligne.type_placement) groupes[ligne.type_placement].push(ligne);
      else groupes.erreur.push(ligne);
    });
  return groupes;
}

function implCaseSelection(ligne) {
  const coche = implLignesSelectionnees.has(ligne.ligne) ? "checked" : "";
  return `<td><input type="checkbox" data-selection="${ligne.ligne}" ${coche} /></td>`;
}

function implBoutonsLigne(ligne) {
  return `<td class="impl-actions-cellule">
    <button type="button" data-modifier="${ligne.ligne}">${t("Modifier")}</button>
    <button type="button" class="danger" data-supprimer="${ligne.ligne}">${t("Supprimer")}</button>
  </td>`;
}

/**
 * Les colonnes communes aux deux sections de décision (doublons, ressemblances)
 * et à celle des erreurs : de quoi lire une ligne quel que soit son type.
 *
 * Une seule table à colonnes fixes plutôt qu'une mise en page par ligne, comme
 * côté bancaire : ces sections MÉLANGENT les types, et trois gabarits empilés
 * dans le même tableau ne se comparent plus d'un regard.
 */
function implCellulesGeneriques(ligne) {
  return `
    <td>${escapeHtml(ligne.date ? formatDate(ligne.date) : "—")}</td>
    <td>${escapeHtml(
      ligne.type_placement
        ? t(IMPL_LIBELLES_TYPE[ligne.type_placement])
        : ligne.libelle_type || "—"
    )}</td>
    <td>${escapeHtml(ligne.action_nom || ligne.nom_valeur || ligne.code_isin || "—")}</td>
    <td>${implQuantite(ligne.quantite)}</td>
    <td>${
      ligne.montant === null || ligne.montant === undefined
        ? "—"
        : formatMontant(ligne.montant, ligne.monnaie_id)
    }</td>`;
}

/**
 * La ligne DÉJÀ EN BASE que le doublon vise, en lecture seule, juste dessous.
 *
 * Mêmes colonnes, sans Actions ni Sélection : la comparaison se fait alors d'un
 * regard, sans avoir à retenir des chiffres d'une section à l'autre. C'est
 * exactement ce que fait l'aperçu d'un relevé bancaire.
 */
function implLigneExistanteHtml(ligne) {
  const existante = implApercu.lignes_existantes[String(ligne.doublon_de)];
  if (!existante) return "";
  return `<tr class="import-doublon-existante">
    <td><span class="hint">${t("déjà en base")}</span></td>
    ${implCellulesGeneriques(existante)}
    <td colspan="2"></td>
  </tr>`;
}

/**
 * La rangée « Ressemble à … », sous une ligne suspectée de doubler un virement.
 *
 * Le suspect n'est pas une ligne de fichier mais une TRANSACTION déjà
 * enregistrée : il n'y a pas de colonnes à remplir, d'où la rangée descriptive.
 * Elle porte les DEUX comptes, toujours : c'est sur eux que le rapprochement
 * porte, et c'est d'eux que vient le compte en face qu'on venait chercher.
 */
function implLigneSuspectHtml(suspect, nbColonnes) {
  const quand =
    suspect.ecart_jours === 0
      ? t("le même jour")
      : `${t("à")} ${suspect.ecart_jours} ${t("jour(s) d'écart")}`;
  const origine =
    suspect.source === "fichier"
      ? `${t("ligne")} ${suspect.ligne} ${t("du même fichier")}`
      : `${t("virement déjà enregistré")}${
          suspect.nature ? ` — « ${escapeHtml(suspect.nature)} »` : ""
        }`;
  const face = suspect.compte_en_face
    ? ` <span class="hint">— ${t("compte en face")} : <strong>${escapeHtml(
        suspect.compte_en_face
      )}</strong></span>`
    : "";
  return `<tr class="import-doublon-existante impl-doublon-virement">
    <td colspan="${nbColonnes}">
      <span class="hint">${t("Ressemble à :")}</span>
      ${escapeHtml(formatDate(suspect.date))} ·
      ${formatMontant(suspect.montant, null)} ·
      <strong>${escapeHtml(suspect.compte_source || "?")}</strong> →
      <strong>${escapeHtml(suspect.compte_destination || "?")}</strong>
      <span class="hint">(${origine}, ${quand})</span>${face}
    </td>
  </tr>`;
}

function ligneTitreHtml(ligne) {
  // Le nom EN BASE quand le titre est déjà connu : c'est celui qui fera foi,
  // et le voir avant l'import évite la surprise d'un titre qu'on croyait créer.
  const nom = ligne.action_nom || ligne.nom_valeur || "—";
  const neuf = ligne.titre_a_creer
    ? ` <span class="badge-partiel">${t("nouveau")}</span>`
    : "";
  return `${escapeHtml(nom)}${neuf}`;
}

function rendreSectionImpl(cle, lignes) {
  const section = document.getElementById(`impl-apercu-section-${cle}`);
  const corps = document.getElementById(`impl-apercu-liste-${cle}`);
  document.getElementById(`impl-apercu-nombre-${cle}`).textContent = lignes.length;
  section.style.display = lignes.length === 0 ? "none" : "";
  const nbColonnes = section.querySelector("thead tr").children.length;
  corps.innerHTML = lignes
    .map((ligne) => {
      if (implLigneEnEdition === ligne.ligne) return formulaireEditionImpl(ligne);
      // Un titre DÉTENU, tel que la photographie le décrit. Les colonnes sont
      // celles du relevé (quantité, prix de revient) et ce que l'app en déduit
      // (montant investi, cours) — pas un montant et une date, qui n'y sont pas.
      if (cle === "position") {
        const deja =
          ligne.quantite_deja_detenue !== null && ligne.quantite_deja_detenue !== undefined
            ? ` <span class="badge-partiel" title="${escapeHtml(
                t(
                  "Ce compte détient déjà ce titre : importer cette ligne s'ajoutera à ce qui s'y trouve."
                )
              )}">${t("déjà")} ${implQuantite(ligne.quantite_deja_detenue)}</span>`
            : "";
        return `<tr>
          <td>${ligne.ligne}</td>
          <td>${ligneTitreHtml(ligne)}${deja}</td>
          <td>${escapeHtml(ligne.code_isin || "—")}</td>
          <td>${implQuantite(ligne.quantite)}</td>
          <td>${
            ligne.prix_unitaire === null || ligne.prix_unitaire === undefined
              ? "—"
              : formatMontant(ligne.prix_unitaire, ligne.monnaie_id)
          }</td>
          <td>${formatMontant(ligne.montant, ligne.monnaie_id)}</td>
          <td>${
            ligne.cours === null || ligne.cours === undefined
              ? "—"
              : formatMontant(ligne.cours, ligne.monnaie_id)
          }</td>
          ${implBoutonsLigne(ligne)}
          ${implCaseSelection(ligne)}
        </tr>`;
      }
      // Une ligne DÉJÀ IMPORTÉE sous ce preset, suivie de celle qu'elle double.
      if (cle === "doublon") {
        return `<tr class="import-doublon-nouvelle">
          <td>${ligne.ligne}</td>
          ${implCellulesGeneriques(ligne)}
          ${implBoutonsLigne(ligne)}
          ${implCaseSelection(ligne)}
        </tr>${implLigneExistanteHtml(ligne)}`;
      }
      // Un transfert qui ressemble à un virement déjà enregistré : mêmes
      // colonnes que la section « Transferts internes », puisque c'en est un.
      if (cle === "ressemblance") {
        const emetteurR = (ligne.montant_signe || 0) < 0;
        const iciR = implNomCompte(ligne.compte_id);
        const faceR = ligne.compte_id_autre
          ? escapeHtml(implNomCompte(ligne.compte_id_autre))
          : `<span class="badge-partiel">${t("à renseigner")}</span>`;
        const suspects = (implSuspectsParLigne[ligne.ligne] || [])
          .map((suspect) => implLigneSuspectHtml(suspect, nbColonnes))
          .join("");
        return `<tr class="import-doublon-nouvelle">
          <td>${ligne.ligne}</td>
          <td>${escapeHtml(formatDate(ligne.date))}</td>
          <td>${formatMontant(ligne.montant, ligne.monnaie_id)}</td>
          <td>${emetteurR ? escapeHtml(iciR) : faceR}</td>
          <td>${emetteurR ? faceR : escapeHtml(iciR)}</td>
          ${implBoutonsLigne(ligne)}
          ${implCaseSelection(ligne)}
        </tr>${suspects}`;
      }
      if (cle === "transfert") {
        const emetteur = (ligne.montant_signe || 0) < 0;
        const ici = implNomCompte(ligne.compte_id);
        const face = ligne.compte_id_autre
          ? escapeHtml(implNomCompte(ligne.compte_id_autre))
          : `<span class="badge-partiel">${t("à renseigner")}</span>`;
        return `<tr>
          <td>${ligne.ligne}</td>
          <td>${escapeHtml(formatDate(ligne.date))}</td>
          <td>${formatMontant(ligne.montant, ligne.monnaie_id)}</td>
          <td>${emetteur ? escapeHtml(ici) : face}</td>
          <td>${emetteur ? face : escapeHtml(ici)}</td>
          ${implBoutonsLigne(ligne)}
          ${implCaseSelection(ligne)}
        </tr>`;
      }
      if (cle === "erreur") {
        return `<tr class="impl-ligne-erreur">
          <td>${ligne.ligne}</td>
          <td>${escapeHtml(ligne.date ? formatDate(ligne.date) : "—")}</td>
          <td>${escapeHtml(
            ligne.type_placement ? t(IMPL_LIBELLES_TYPE[ligne.type_placement]) : ligne.libelle_type || "—"
          )}</td>
          <td>${escapeHtml(ligne.action_nom || ligne.nom_valeur || ligne.code_isin || "—")}</td>
          <td>${ligne.montant === null ? "—" : formatMontant(ligne.montant, ligne.monnaie_id)}</td>
          <td class="impl-erreur-cellule">${escapeHtml(t(ligne.erreur || ""))}</td>
          ${implBoutonsLigne(ligne)}
          ${implCaseSelection(ligne)}
        </tr>`;
      }
      // Achat / vente. Le prix unitaire est celui qui partira en base : le
      // montant divisé par la quantité, pas le cours lu. Quand les deux
      // divergent, la cellule le dit — c'est le seul endroit où l'écart se
      // voit ligne par ligne.
      const ecart =
        ligne.ecart_cours !== null && ligne.ecart_cours !== undefined
          ? `<span class="apercu-frais">${t("cours du fichier")} : ${ligne.cours}</span>`
          : "";
      return `<tr>
        <td>${ligne.ligne}</td>
        <td>${escapeHtml(formatDate(ligne.date))}</td>
        <td>${ligneTitreHtml(ligne)}</td>
        <td>${escapeHtml(ligne.code_isin || "—")}</td>
        <td>${implQuantite(ligne.quantite)}</td>
        <td>${formatMontant(ligne.montant, ligne.monnaie_id)}</td>
        <td>${
          ligne.prix_unitaire === null || ligne.prix_unitaire === undefined
            ? "—"
            : formatMontant(ligne.prix_unitaire, ligne.monnaie_id)
        }${ecart}</td>
        ${implBoutonsLigne(ligne)}
        ${implCaseSelection(ligne)}
      </tr>`;
    })
    .join("");
}

/**
 * Le formulaire d'édition, à la place de la ligne.
 *
 * Une ligne et non une modale : la correction se fait en regard des autres
 * lignes, dont on a besoin pour savoir ce qu'on corrige (le compte en face
 * d'un transfert se devine souvent de la ligne d'à côté).
 *
 * `colspan` couvre toute la largeur de la section, quelle qu'elle soit : les
 * quatre tableaux n'ont pas le même nombre de colonnes, et compter juste ici
 * n'apporterait rien qu'un décalage à la prochaine colonne ajoutée.
 */
function formulaireEditionImpl(ligne) {
  const titres = implTitres
    .map(
      (a) =>
        `<option value="${a.id}" ${a.id === ligne.action_id ? "selected" : ""}>${escapeHtml(
          a.nom_affiche
        )}${a.code_isin ? ` (${escapeHtml(a.code_isin)})` : ""}</option>`
    )
    .join("");
  const comptes = state.comptes
    .filter((c) => c.id !== ligne.compte_id)
    .map(
      (c) =>
        `<option value="${c.id}" ${c.id === ligne.compte_id_autre ? "selected" : ""}>${escapeHtml(
          c.nom
        )}</option>`
    )
    .join("");
  const types = Object.entries(IMPL_LIBELLES_TYPE)
    .map(
      ([cle, libelle]) =>
        `<option value="${cle}" ${cle === ligne.type_placement ? "selected" : ""}>${t(libelle)}</option>`
    )
    .join("");

  // LES CLASSES DU NOYAU (`ligne-apercu-edition`, `ligne-edition-form`) et non
  // les nôtres : c'est le même geste sur le même écran, et l'aperçu d'un relevé
  // bancaire s'édite déjà comme ça. Les champs y prennent fond, bordure et
  // couleur de l'application — sans elles ils tombaient au style natif du
  // navigateur, seuls contrôles de l'écran à ne pas suivre le thème.
  return `<tr class="ligne-apercu-edition"><td colspan="9">
    <div class="ligne-edition-form">
      <label>${t("Date")}
        <input type="date" data-champ="date" value="${ligne.date || ""}" />
      </label>
      <label>${t("Type d'opération")}
        <select data-champ="type_placement">${types}</select>
      </label>
      <label>${t("Titre")}
        <select data-champ="action_id">
          <option value="">${t("— d'après le fichier —")}</option>
          ${titres}
        </select>
      </label>
      <label>${t("Quantité")}
        <input type="number" step="any" min="0" data-champ="quantite" value="${
          ligne.quantite ?? ""
        }" />
      </label>
      <label>${t("Montant")}
        <input type="number" step="0.01" data-champ="montant" value="${ligne.montant ?? ""}" />
      </label>
      <label>${t("Compte en face (transfert)")}
        <select data-champ="compte_id_autre">
          <option value="">${t("— aucun —")}</option>
          ${comptes}
        </select>
      </label>
      <div class="actions">
        <button type="button" class="primary" data-action="valider-edition">${t("Appliquer")}</button>
        <button type="button" data-action="annuler-edition">${t("Annuler")}</button>
      </div>
    </div>
  </td></tr>`;
}

function renderImplApercu() {
  const bloc = document.getElementById("impl-apercu-bloc");
  if (!implApercu) {
    bloc.style.display = "none";
    return;
  }
  bloc.style.display = "";
  const groupes = implGroupes();
  const total = Object.values(groupes).reduce((n, l) => n + l.length, 0);
  document.getElementById("impl-apercu-nombre").textContent = total;
  Object.entries(groupes).forEach(([cle, lignes]) => rendreSectionImpl(cle, lignes));
  brancherEcouteursApercuImpl();
  updateBoutonsSelectionImpl();
}

function brancherEcouteursApercuImpl() {
  const bloc = document.getElementById("impl-apercu-bloc");
  bloc.querySelectorAll("[data-modifier]").forEach((btn) => {
    btn.addEventListener("click", () => {
      implLigneEnEdition = Number(btn.dataset.modifier);
      renderImplApercu();
    });
  });
  bloc.querySelectorAll("[data-supprimer]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const numero = Number(btn.dataset.supprimer);
      implLignesSupprimees.add(numero);
      implLignesSelectionnees.delete(numero);
      renderImplApercu();
      await rafraichirDoublonsTransferts();
    });
  });
  bloc.querySelectorAll("[data-selection]").forEach((input) => {
    input.addEventListener("change", () => {
      const numero = Number(input.dataset.selection);
      if (input.checked) implLignesSelectionnees.add(numero);
      else implLignesSelectionnees.delete(numero);
      updateBoutonsSelectionImpl();
    });
  });
  const valider = bloc.querySelector("[data-action='valider-edition']");
  if (valider) {
    valider.addEventListener("click", () => appliquerRetoucheImpl(bloc));
  }
  const annuler = bloc.querySelector("[data-action='annuler-edition']");
  if (annuler) {
    annuler.addEventListener("click", () => {
      implLigneEnEdition = null;
      renderImplApercu();
    });
  }
}

/**
 * Applique la retouche, puis RELIT LE FICHIER.
 *
 * La relecture n'est pas un luxe : changer une quantité change le prix
 * unitaire, changer un titre change la monnaie de l'écriture, et changer le
 * type fait passer la ligne d'une section à l'autre. Tout cela se recalcule
 * côté serveur (`_completer_ligne`), et le refaire ici en aurait fait une
 * seconde version, condamnée à diverger.
 */
async function appliquerRetoucheImpl(bloc) {
  const numero = implLigneEnEdition;
  const edition = bloc.querySelector(".ligne-edition-form");
  const retouches = {};
  edition.querySelectorAll("[data-champ]").forEach((champ) => {
    const nom = champ.dataset.champ;
    const valeur = champ.value;
    if (valeur === "") return;
    retouches[nom] =
      nom === "quantite" || nom === "montant"
        ? Number(valeur)
        : nom === "action_id" || nom === "compte_id_autre"
          ? Number(valeur)
          : valeur;
  });
  implOverrides[numero] = { ...(implOverrides[numero] || {}), ...retouches };
  implLigneEnEdition = null;
  await relireApercuImpl();
}

/** Redemande l'aperçu au serveur en conservant les retouches et les
 *  suppressions déjà faites. */
async function relireApercuImpl() {
  const overrides = { ...implOverrides };
  const supprimees = new Set(implLignesSupprimees);
  const selectionnees = new Set(implLignesSelectionnees);
  try {
    implApercu = await apiFetchForm(implUrl("/previsualiser"), implFormDataFichier());
  } catch (err) {
    showMessage(err.message, "error");
    return;
  }
  Object.assign(implOverrides, overrides);
  supprimees.forEach((n) => implLignesSupprimees.add(n));
  implLignesSelectionnees.clear();
  selectionnees.forEach((n) => implLignesSelectionnees.add(n));
  renderImplTitresACreer();
  renderImplAvertissements();
  renderImplApercu();
  await rafraichirDoublonsTransferts();
}

function updateBoutonsSelectionImpl() {
  const nb = implLignesSelectionnees.size;
  document.getElementById("impl-selection-nombre").textContent = nb;
  document.getElementById("btn-impl-supprimer-selection").disabled = nb === 0;
  const bouton = document.getElementById("btn-impl-confirmer");
  const blocage = document.getElementById("impl-blocage");
  // La confirmation reste bloquée tant qu'une ligne est sélectionnée : c'est
  // ce qui force à trancher sur les doublons plutôt qu'à les importer par
  // inadvertance.
  bouton.disabled = nb > 0;
  blocage.textContent =
    nb > 0
      ? t("Supprime ou décoche les lignes sélectionnées pour pouvoir confirmer.")
      : "";
}

/* ---------- Confirmation ---------- */

async function confirmerImportImpl() {
  if (!implFichier || !implPresetId) return;
  const formData = implFormDataFichier();
  // `set` et non `append` : implFormDataFichier a déjà posé les retouches, il
  // s'agit de les compléter des suppressions — deux valeurs pour le même champ
  // laisseraient le serveur lire la première, donc sans elles.
  formData.set(
    "overrides",
    JSON.stringify({
      lignes: implOverrides,
      lignes_supprimees: [...implLignesSupprimees],
      comptes: {},
    })
  );
  let resultat;
  try {
    resultat = await apiFetchForm(implUrl("/confirmer"), formData);
  } catch (err) {
    showMessage(err.message, "error");
    return;
  }
  afficherResultatImpl(resultat);
  reinitialiserImpl();
  await loadImplPresets();
  await loadImplHistorique();
  // Les titres créés doivent apparaître dans le menu d'édition du prochain
  // import, et la page Placements a de nouveaux mouvements à montrer.
  await refreshTitresImpl();
  await refreshComptes();
}

function afficherResultatImpl(resultat) {
  const bloc = document.getElementById("impl-resultat");
  bloc.style.display = "";
  const ignorees = resultat.lignes_ignorees || [];
  const titres = resultat.titres_crees || [];
  const details = ignorees
    .map(
      (l) =>
        `<li>${t("Ligne")} ${l.ligne} — ${escapeHtml(t(l.erreur || ""))}</li>`
    )
    .join("");
  bloc.innerHTML = `
    <p class="message success">${resultat.operations_creees} ${t("opération(s) créée(s)")}${
      titres.length ? ` · ${titres.length} ${t("titre(s) créé(s)")} : ${escapeHtml(titres.join(", "))}` : ""
    }${
      resultat.doublons_detectes
        ? ` · ${resultat.doublons_detectes} ${t("doublon(s) signalé(s)")}`
        : ""
    }</p>
    ${
      ignorees.length
        ? `<p class="hint">${ignorees.length} ${t(
            "ligne(s) non importée(s) :"
          )}</p><ul class="hint">${details}</ul>`
        : ""
    }
  `;
  showMessage(
    `${resultat.operations_creees} ${t("opération(s) créée(s)")}`,
    ignorees.length ? "warning" : "success"
  );
}

/* ---------- Historique ---------- */

async function loadImplHistorique() {
  const bloc = document.getElementById("impl-historique");
  if (!implPresetId) {
    bloc.innerHTML = "";
    return;
  }
  const historique = await apiFetch(implUrl("/historique"));
  if (historique.length === 0) {
    bloc.innerHTML = `<span class="hint">${t("Aucun import sous ce preset.")}</span>`;
    return;
  }
  bloc.innerHTML = "";
  historique.forEach((entree) => {
    const row = document.createElement("div");
    row.className = "import-mapping-row";
    const annulable = entree.operations_annulables > 0;
    row.innerHTML = `
      <span>${escapeHtml(formatDateHeure(entree.date_import))} — ${escapeHtml(
        entree.nom_fichier || t("(sans nom)")
      )}</span>
      <span class="hint">${entree.operations_creees} ${t("opération(s)")} · ${
        entree.lignes_ignorees
      } ${t("ignorée(s)")} · ${entree.doublons_detectes} ${t("doublon(s)")}</span>
      ${
        annulable
          ? `<button type="button" class="danger" data-annuler="${entree.id}">${t(
              "Annuler cet import"
            )} (${entree.operations_annulables})</button>`
          : `<span class="hint">${
              entree.raison_non_annulable === "anterieur"
                ? t("import antérieur au suivi des opérations")
                : t("plus rien à annuler")
            }</span>`
      }
    `;
    const bouton = row.querySelector("[data-annuler]");
    if (bouton) {
      bouton.addEventListener("click", async () => {
        if (
          !window.confirm(
            t(
              "Annuler cet import supprimera les opérations qu'il a créées, y compris celles modifiées depuis. Continuer ?"
            )
          )
        )
          return;
        try {
          const resultat = await apiFetch(implUrl(`/historique/${entree.id}`), {
            method: "DELETE",
          });
          showMessage(
            `${resultat.operations_supprimees} ${t("opération(s) supprimée(s)")}`,
            "success"
          );
          await loadImplHistorique();
          await refreshComptes();
        } catch (err) {
          showMessage(err.message, "error");
        }
      });
    }
    bloc.appendChild(row);
  });
}

/* ---------- Chargement de l'écran ---------- */

async function refreshTitresImpl() {
  // Les archivés compris : un relevé peut rouvrir une position sur un titre
  // rangé, et le choisir à la main doit rester possible.
  implTitres = await apiFetch("/actions?inclure_archivees=true");
}

function remplirSelectComptesPlacement(select, valeurCourante) {
  const premier = select.firstElementChild;
  select.innerHTML = "";
  if (premier) select.appendChild(premier);
  implComptesPlacement.forEach((compte) => {
    const option = document.createElement("option");
    option.value = compte.id;
    option.textContent = compte.nom;
    if (compte.id === valeurCourante) option.selected = true;
    select.appendChild(option);
  });
}

/**
 * Le sélecteur « compte pour ce fichier » n'apparaît que si le preset n'est
 * lié à aucun compte : lié, ce compte s'impose à toutes les lignes et proposer
 * d'en choisir un autre ne ferait qu'induire en erreur.
 */
function updateImplCompteDefautVisibilite() {
  const preset = implPresetActuel();
  document.getElementById("impl-compte-defaut-bloc").style.display =
    preset && !preset.compte_id ? "" : "none";
}

async function chargerPresetImpl() {
  reinitialiserImpl();
  if (!implPresetId) {
    document.getElementById("impl-config-fichier").style.display = "none";
    return;
  }
  document.getElementById("impl-config-fichier").style.display = "";
  await loadImplConfiguration();
  await loadImplHistorique();
}

async function loadImportPlacements() {
  // On entre ici par le bouton d'import de la page Placements : l'écran doit
  // s'ouvrir sur son volet d'import, jamais sur l'onglet « Règles » laissé
  // ouvert d'une visite précédente.
  reinitialiserOngletsImpl();
  await refreshComptes();
  implComptesPlacement = await apiFetch(`${IMPL_BASE}/comptes`);
  await refreshTitresImpl();
  if (Object.keys(implVocabulaireDefaut).length === 0) {
    implVocabulaireDefaut = await apiFetch(`${IMPL_BASE}/vocabulaire-defaut`);
  }

  const aucun = implComptesPlacement.length === 0;
  document.getElementById("impl-aucun-compte").style.display = aucun ? "" : "none";
  document.getElementById("impl-contenu").style.display = aucun ? "none" : "";
  if (aucun) return;

  remplirSelectComptesPlacement(document.getElementById("impl-compte-defaut"), null);
  await loadImplPresets();
  remplirSelectComptesPlacement(
    document.getElementById("impl-preset-compte"),
    implPresetActuel() ? implPresetActuel().compte_id : null
  );
  await chargerPresetImpl();
}

/* ---------- Onglet « Règles » ----------
 *
 * Les règles disent ce qu'une ligne du fichier DÉCRIT : un achat, une vente, un
 * transfert d'espèces. Elles répondent à la même question que les trois listes
 * de mots-clés de la « Configuration du fichier », mais autrement : un mot-clé
 * reconnaît un libellé ENTIER, une règle reconnaît un morceau de libellé
 * (« contient ACHAT »). C'est ce qui permet de lire un courtier qui écrit une
 * phrase par ligne, avec le nom du titre dedans — cas où aucune liste fermée ne
 * peut rien reconnaître.
 *
 * CALQUÉES SUR LES RÈGLES BANCAIRES (extension « regles ») : mêmes conditions
 * sur deux niveaux, mêmes quatre opérateurs, même ordre d'évaluation, mêmes
 * classes CSS (`.regle-editeur`, `.regle-groupe`, `.regle-carte` — toutes dans
 * frontend/style.css, donc disponibles sans que cette extension dépende de
 * l'autre). Ce qui change tient à l'action : ici il n'y a qu'une décision à
 * prendre, d'où l'absence de catégorie, de compte en face et de « arrêter la
 * lecture ici » — sans second champ à compléter, une règle qui correspond a
 * tout dit.
 *
 * L'ORDRE SE CHANGE À LA SOURIS, comme dans l'autre écran : l'ordre EST la
 * sémantique (première règle qui correspond gagne), le réorganiser doit être
 * direct.
 */

const IMPL_REGLES_BASE = "/regles-import-placements";

const IMPL_OPERATEURS_REGLE = ["est", "n'est pas", "contient", "ne contient pas"];

// Les trois colonnes TEXTE d'un relevé de compte-titres (miroir de
// constants.CHAMPS_REGLE_PLACEMENT_VALIDES). Ni la date ni les trois nombres :
// les opérateurs disponibles sont textuels, et « le montant contient 12 » ne
// veut rien dire.
const IMPL_CHAMPS_REGLE = [
  ["type_brut", "Type d'opération"],
  ["nom_valeur_brut", "Nom de la valeur"],
  ["code_isin_brut", "Code ISIN"],
];

const IMPL_TYPES_REGLE = [
  ["achat", "Un achat de titres"],
  ["vente", "Une vente de titres"],
  ["transfert", "Un transfert interne (espèces)"],
];

// Les étiquettes de titre, pour le menu de l'éditeur de règles. Chargées avec
// les règles : l'extension « placements » les gère, celle-ci ne fait que les
// désigner.
let implTypesTitre = [];

let implRegles = [];
// Brouillon des groupes en cours d'édition : rien n'est écrit en base avant
// « Enregistrer », l'éditeur travaille sur cette structure.
let implRegleBrouillonGroupes = [];

function implConditionVide() {
  return { champ: "type_brut", operateur: "contient", valeur: "" };
}

function implGroupeVide() {
  return { operateur: "ET", conditions: [implConditionVide()] };
}

async function loadImplRegles() {
  try {
    // Les comptes nomment le « compte en face » d'une règle de transfert, dans
    // la liste comme dans l'éditeur : ils ont pu changer depuis la dernière
    // ouverture de l'onglet.
    await refreshComptes();
    // Les étiquettes de titre appartiennent à l'extension « placements » — dont
    // celle-ci dépend, elle est donc toujours allumée quand on arrive ici. Un
    // échec ne doit pas pour autant emporter les règles : sans étiquettes, le
    // menu est simplement vide.
    try {
      implTypesTitre = await apiFetch("/types-titre");
    } catch (err) {
      implTypesTitre = [];
      console.error(err);
    }
    implRegles = await apiFetch(IMPL_REGLES_BASE);
    renderImplRegles();
  } catch (err) {
    showMessage(err.message, "error");
  }
}

function implLibelleChamp(champ) {
  return t((IMPL_CHAMPS_REGLE.find(([v]) => v === champ) || [champ, champ])[1]);
}

function implLibelleType(type) {
  return t((IMPL_TYPES_REGLE.find(([v]) => v === type) || [type, type])[1]);
}

function implResumeRegle(regle) {
  const groupes = (regle.conditions.groupes || []).map((groupe) => {
    const conditions = groupe.conditions.map(
      (c) => `${implLibelleChamp(c.champ)} ${t(c.operateur)} « ${escapeHtml(c.valeur)} »`
    );
    return conditions.length > 1
      ? `(${conditions.join(` ${t(groupe.operateur)} `)})`
      : conditions[0];
  });
  return groupes.join(` ${t(regle.conditions.operateur)} `);
}

/**
 * Ce que la règle POSE, en une ligne lisible depuis la liste.
 *
 * Un transfert sans compte en face n'est pas une erreur — c'est le cas
 * ordinaire, le relevé ne le nomme jamais — mais il coûtera une reprise à la
 * main sur chaque ligne. Le badge le dit avant l'import, pas pendant.
 */
function implActionRegleHtml(regle) {
  const type = implLibelleType(regle.type_placement);
  if (regle.type_placement !== "transfert") return type;
  const etiquette = implTypesTitre.find((x) => x.id === regle.type_titre_id);
  const typeTitre = etiquette
    ? `, ${t("titre typé")} « ${escapeHtml(etiquette.nom)} »`
    : "";
  return regle.compte_autre_id != null
    ? `${type}${typeTitre}, ${t("avec")} « ${escapeHtml(nomCompte(regle.compte_autre_id))} » ${t("en face")}`
    : `${type}${typeTitre} <span class="badge-partiel">${t(
        "compte en face à renseigner à l'import"
      )}</span>`;
}

/**
 * Le compte en face n'existe que pour un transfert : seul type qui touche DEUX
 * comptes, dont le relevé du courtier ne nomme jamais que le premier.
 *
 * La valeur choisie survit à un aller-retour entre deux types, le temps de
 * l'édition : revenir sur « transfert » après s'être trompé ne doit pas coûter
 * de la retrouver. Elle n'est envoyée que si le type final l'accepte — et le
 * serveur la neutralise de toute façon (cf. routeur_regles_placements).
 */
let implRegleCompteMemorise = "";

function majVisibiliteCompteRegleImpl() {
  const transfert = document.getElementById("impl-regle-type").value === "transfert";
  const bloc = document.getElementById("impl-regle-compte-bloc");
  const select = document.getElementById("impl-regle-compte");
  bloc.style.display = transfert ? "" : "none";
  if (transfert) {
    if (
      implRegleCompteMemorise &&
      select.querySelector(`option[value="${implRegleCompteMemorise}"]`)
    ) {
      select.value = implRegleCompteMemorise;
    }
    return;
  }
  if (select.value) implRegleCompteMemorise = select.value;
  select.value = "";
}

/**
 * L'étiquette de titre, à l'inverse du compte en face : partout SAUF sur un
 * transfert, qui ne désigne aucun titre. Même mémorisation, pour la même
 * raison — un aller-retour entre deux types ne doit pas coûter de la
 * retrouver.
 */
let implRegleTypeTitreMemorise = "";

function majVisibiliteTypeTitreRegleImpl() {
  const transfert = document.getElementById("impl-regle-type").value === "transfert";
  const bloc = document.getElementById("impl-regle-type-titre-bloc");
  const select = document.getElementById("impl-regle-type-titre");
  if (!bloc || !select) return;
  bloc.style.display = transfert ? "none" : "";
  if (!transfert) {
    if (
      implRegleTypeTitreMemorise &&
      select.querySelector(`option[value="${implRegleTypeTitreMemorise}"]`)
    ) {
      select.value = implRegleTypeTitreMemorise;
    }
    return;
  }
  if (select.value) implRegleTypeTitreMemorise = select.value;
  select.value = "";
}

/**
 * Remplit le menu des étiquettes. Vide et DÉSACTIVÉ tant qu'aucune n'existe :
 * un menu qui ne propose rien laisse croire à une panne, là où « aucun type de
 * titre créé » dit où aller en créer un.
 */
function remplirMenuTypesTitreRegle() {
  const select = document.getElementById("impl-regle-type-titre");
  if (!select) return;
  const avant = select.value;
  select.innerHTML =
    `<option value="">${escapeHtml(
      implTypesTitre.length === 0
        ? t("— aucun type de titre créé —")
        : t("— aucun —")
    )}</option>` +
    implTypesTitre
      .map((type) => `<option value="${type.id}">${escapeHtml(type.nom)}</option>`)
      .join("");
  select.disabled = implTypesTitre.length === 0;
  if (avant) select.value = avant;
}

function renderImplRegles() {
  const bloc = document.getElementById("impl-regles-liste");
  bloc.innerHTML = "";
  if (implRegles.length === 0) {
    bloc.innerHTML = `<p class="hint">${t(
      "Aucune règle : le type de chaque ligne est reconnu par les mots-clés du preset."
    )}</p>`;
    return;
  }

  implRegles.forEach((regle, i) => {
    const carte = document.createElement("div");
    carte.className = "regle-carte" + (regle.actif ? "" : " regle-inactive");
    carte.dataset.index = i;
    carte.innerHTML = `
      <div class="regle-carte-ordre" title="${t("Glisse pour changer l'ordre")}">
        <span class="regle-poignee" aria-hidden="true">⠿</span>
        <span class="regle-rang">${i + 1}</span>
      </div>
      <div class="regle-carte-corps">
        <div class="regle-carte-titre">
          ${escapeHtml(regle.nom)}
          ${regle.actif ? "" : `<span class="badge-aucun">${t("inactive")}</span>`}
        </div>
        ${
          // La note de la règle, quand elle en porte une : au-dessus des
          // conditions, c'est ce qu'on lit d'abord pour reconnaître la bonne
          // règle. Même rendu que côté bancaire (cf. extensions/regles).
          (regle.description || "").trim()
            ? `<div class="regle-carte-description">${escapeHtml(regle.description.trim())}</div>`
            : ""
        }
        <div class="regle-carte-conditions">${t("Si")} ${implResumeRegle(regle)}</div>
        <div class="regle-carte-action">→ ${implActionRegleHtml(regle)}</div>
      </div>
      <div class="regle-carte-actions">
        <button type="button" data-action="modifier">${t("Modifier")}</button>
        <button type="button" data-action="supprimer" class="danger">${t("Supprimer")}</button>
      </div>
    `;

    implCablerGlisserRegle(carte);
    carte
      .querySelector("[data-action='modifier']")
      .addEventListener("click", () => ouvrirEditeurImplRegle(regle));
    carte.querySelector("[data-action='supprimer']").addEventListener("click", async () => {
      if (!confirm(`Supprimer la règle « ${regle.nom} » ?`)) return;
      try {
        await apiFetch(`${IMPL_REGLES_BASE}/${regle.id}`, { method: "DELETE" });
        showMessage(t("Règle supprimée"), "success");
        fermerEditeurImplRegle();
        await loadImplRegles();
      } catch (err) {
        showMessage(err.message, "error");
      }
    });

    bloc.appendChild(carte);
  });
}

/* ----- Ordre des règles : glisser-déposer ----- */

let implRegleGlisseeIndex = null;

function implCablerGlisserRegle(carte) {
  // Déplaçable par sa poignée seulement (⠿, à gauche du rang) : sans cela,
  // le nom de la règle et le résumé de ses conditions ne pouvaient pas être
  // sélectionnés — la carte entière avalait le glissement de la souris.
  rendreDeplacableParPoignee(carte, ".regle-carte-ordre");
  carte.addEventListener("dragstart", (e) => {
    implRegleGlisseeIndex = Number(carte.dataset.index);
    carte.classList.add("regle-carte-glissee");
    e.dataTransfer.effectAllowed = "move";
    // Firefox n'amorce pas le glisser sans données attachées.
    e.dataTransfer.setData("text/plain", String(implRegleGlisseeIndex));
  });

  carte.addEventListener("dragend", () => {
    implRegleGlisseeIndex = null;
    document
      .querySelectorAll(
        "#impl-regles-liste .regle-carte-glissee, " +
          "#impl-regles-liste .regle-carte-cible-avant, " +
          "#impl-regles-liste .regle-carte-cible-apres"
      )
      .forEach((el) =>
        el.classList.remove(
          "regle-carte-glissee",
          "regle-carte-cible-avant",
          "regle-carte-cible-apres"
        )
      );
  });

  carte.addEventListener("dragover", (e) => {
    if (implRegleGlisseeIndex === null) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    // Le trait se place au-dessus ou en dessous selon la moitié survolée :
    // sans lui, on ne sait pas où la carte va atterrir avant de lâcher.
    const rect = carte.getBoundingClientRect();
    const avant = e.clientY < rect.top + rect.height / 2;
    carte.classList.toggle("regle-carte-cible-avant", avant);
    carte.classList.toggle("regle-carte-cible-apres", !avant);
  });

  carte.addEventListener("dragleave", () => {
    carte.classList.remove("regle-carte-cible-avant", "regle-carte-cible-apres");
  });

  carte.addEventListener("drop", (e) => {
    if (implRegleGlisseeIndex === null) return;
    e.preventDefault();
    const rect = carte.getBoundingClientRect();
    const avant = e.clientY < rect.top + rect.height / 2;
    deposerImplRegle(implRegleGlisseeIndex, Number(carte.dataset.index) + (avant ? 0 : 1));
  });
}

// `cible` est la position d'insertion AVANT retrait de la carte déplacée : on
// décale d'un rang quand elle vient d'au-dessus, sinon déposer une carte juste
// sous sa voisine ne la déplacerait pas.
async function deposerImplRegle(depuis, cible) {
  const destination = cible > depuis ? cible - 1 : cible;
  if (destination === depuis) return;
  const ids = implRegles.map((r) => r.id);
  const [deplace] = ids.splice(depuis, 1);
  ids.splice(destination, 0, deplace);
  try {
    await apiFetch(`${IMPL_REGLES_BASE}/reordonner`, {
      method: "PUT",
      body: JSON.stringify({ ids }),
    });
    await loadImplRegles();
  } catch (err) {
    showMessage(err.message, "error");
  }
}

/* ----- L'éditeur ----- */

function renderImplRegleGroupes() {
  const bloc = document.getElementById("impl-regle-groupes");
  bloc.innerHTML = "";

  implRegleBrouillonGroupes.forEach((groupe, iGroupe) => {
    const carte = document.createElement("div");
    carte.className = "regle-groupe";

    const entete = document.createElement("div");
    entete.className = "regle-groupe-entete";
    entete.innerHTML = `
      <span class="regle-groupe-titre">${t("Groupe")} ${iGroupe + 1}</span>
      <label>${t("Combiner avec")}
        <select data-role="connecteur">
          <option value="ET" ${groupe.operateur === "ET" ? "selected" : ""}>ET</option>
          <option value="OU" ${groupe.operateur === "OU" ? "selected" : ""}>OU</option>
        </select>
      </label>
      <button type="button" class="danger" data-role="supprimer-groupe" ${
        implRegleBrouillonGroupes.length === 1 ? "disabled" : ""
      }>${t("Supprimer le groupe")}</button>
    `;
    entete.querySelector("[data-role='connecteur']").addEventListener("change", (e) => {
      groupe.operateur = e.target.value;
    });
    entete.querySelector("[data-role='supprimer-groupe']").addEventListener("click", () => {
      implRegleBrouillonGroupes.splice(iGroupe, 1);
      renderImplRegleGroupes();
    });
    carte.appendChild(entete);

    groupe.conditions.forEach((condition, iCondition) => {
      const ligne = document.createElement("div");
      ligne.className = "regle-condition";

      // Un seul champ par condition, en boutons radio : l'exclusivité se voit,
      // et pour viser plusieurs champs on ajoute des conditions dans un groupe
      // OU. `name` unique par condition, sinon toutes les lignes de l'éditeur
      // partageraient le même groupe radio.
      const nomGroupeRadio = `impl-regle-champ-${iGroupe}-${iCondition}`;
      const champsHtml = IMPL_CHAMPS_REGLE.map(
        ([valeur, label]) => `
          <label class="regle-champ-case">
            <input type="radio" name="${nomGroupeRadio}" value="${valeur}" ${
              condition.champ === valeur ? "checked" : ""
            } />
            ${t(label)}
          </label>`
      ).join("");

      ligne.innerHTML = `
        <div class="regle-condition-champs">${champsHtml}</div>
        <select data-role="operateur">
          ${IMPL_OPERATEURS_REGLE.map(
            (o) =>
              `<option value="${o}" ${o === condition.operateur ? "selected" : ""}>${t(o)}</option>`
          ).join("")}
        </select>
        <input type="text" data-role="valeur" placeholder="ex. ACHAT"
               value="${(condition.valeur || "").replace(/"/g, "&quot;")}" />
        <button type="button" class="danger" data-role="supprimer-condition" ${
          groupe.conditions.length === 1 ? "disabled" : ""
        }>×</button>
      `;

      ligne.querySelectorAll(".regle-condition-champs input").forEach((radio) => {
        radio.addEventListener("change", () => {
          if (radio.checked) condition.champ = radio.value;
        });
      });
      ligne.querySelector("[data-role='operateur']").addEventListener("change", (e) => {
        condition.operateur = e.target.value;
      });
      ligne.querySelector("[data-role='valeur']").addEventListener("input", (e) => {
        condition.valeur = e.target.value;
      });
      ligne.querySelector("[data-role='supprimer-condition']").addEventListener("click", () => {
        groupe.conditions.splice(iCondition, 1);
        renderImplRegleGroupes();
      });

      carte.appendChild(ligne);
    });

    const ajout = document.createElement("div");
    ajout.className = "actions";
    ajout.innerHTML = `<button type="button">+ ${t("Ajouter une condition")}</button>`;
    ajout.querySelector("button").addEventListener("click", () => {
      groupe.conditions.push(implConditionVide());
      renderImplRegleGroupes();
    });
    carte.appendChild(ajout);

    bloc.appendChild(carte);
  });
}

function ouvrirEditeurImplRegle(regle = null) {
  document.getElementById("impl-regle-editeur").style.display = "";
  document.getElementById("impl-regle-editeur-titre").textContent = regle
    ? t("Modifier la règle")
    : t("Nouvelle règle");
  document.getElementById("impl-regle-id").value = regle ? regle.id : "";
  document.getElementById("impl-regle-nom").value = regle ? regle.nom : "";
  document.getElementById("impl-regle-description").value = regle
    ? regle.description || ""
    : "";
  document.getElementById("impl-regle-connecteur").value = regle
    ? regle.conditions.operateur
    : "ET";
  document.getElementById("impl-regle-type").value = regle ? regle.type_placement : "achat";
  document.getElementById("impl-regle-actif").checked = regle ? regle.actif : true;

  // Les comptes ont pu changer depuis la dernière ouverture de l'éditeur.
  const select = document.getElementById("impl-regle-compte");
  _refillPreservingSelection(select, (el) =>
    fillComptesSelect(el, state.comptes, { keepFirst: true })
  );
  implRegleCompteMemorise =
    regle && regle.compte_autre_id != null ? String(regle.compte_autre_id) : "";
  select.value = implRegleCompteMemorise;
  majVisibiliteCompteRegleImpl();

  remplirMenuTypesTitreRegle();
  implRegleTypeTitreMemorise =
    regle && regle.type_titre_id != null ? String(regle.type_titre_id) : "";
  document.getElementById("impl-regle-type-titre").value = implRegleTypeTitreMemorise;
  majVisibiliteTypeTitreRegleImpl();

  // Copie profonde : annuler ne doit rien laisser derrière dans la liste.
  implRegleBrouillonGroupes = regle
    ? JSON.parse(JSON.stringify(regle.conditions.groupes))
    : [implGroupeVide()];
  renderImplRegleGroupes();
  document
    .getElementById("impl-regle-editeur")
    .scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function fermerEditeurImplRegle() {
  document.getElementById("impl-regle-editeur").style.display = "none";
  implRegleBrouillonGroupes = [];
}

/**
 * Ramène l'écran sur son volet « Import ».
 *
 * Appelé à chaque ouverture de l'écran : on y entre pour importer un fichier,
 * jamais pour écrire une règle. Revenir sur un volet « Règles » resté ouvert
 * d'une visite précédente donnerait l'impression d'avoir cliqué sur autre chose
 * que le bouton d'import.
 */
function reinitialiserOngletsImpl() {
  majVisibiliteModeImpl();
  document
    .querySelectorAll("#impl-onglets button[data-onglet-impl]")
    .forEach((b) => b.classList.toggle("active", b.dataset.ongletImpl === "import"));
  document.getElementById("impl-volet-import").style.display = "";
  document.getElementById("impl-volet-regles").style.display = "none";
  fermerEditeurImplRegle();
}

/* ---------- Écouteurs ---------- */

/* ----- Le mode de lecture ----- */

/**
 * Changer de mode REPREND LES COLONNES PAR DÉFAUT du nouveau.
 *
 * Les deux jeux ne se recouvrent qu'à moitié : garder la configuration
 * précédente laisserait des colonnes qui n'existent plus dans le mode choisi
 * (une date sur une photographie) et en laisserait manquer d'autres. Le serveur
 * refuserait de toute façon d'enregistrer — autant repartir d'une configuration
 * valide, que les numéros se corrigent ensuite.
 *
 * Rien n'est enregistré ici : c'est « Enregistrer la configuration » qui écrit,
 * comme pour n'importe quel autre réglage de ce panneau.
 */
document.getElementById("impl-mode-lecture").addEventListener("change", () => {
  implConfigColonnes = implProprietesLues().map(([propriete], i) => ({
    propriete,
    index: i + 1,
  }));
  renderImplConfig();
  showMessage(
    t("Colonnes remises à celles de ce type de fichier. Enregistre pour confirmer."),
    "success"
  );
});

/* ----- Onglets de l'écran (Import / Règles) ----- */

document.getElementById("impl-onglets").addEventListener("click", (e) => {
  const bouton = e.target.closest("button[data-onglet-impl]");
  if (!bouton) return;
  const onglet = bouton.dataset.ongletImpl;
  document
    .querySelectorAll("#impl-onglets button[data-onglet-impl]")
    .forEach((b) => b.classList.toggle("active", b === bouton));
  document.getElementById("impl-volet-import").style.display =
    onglet === "import" ? "" : "none";
  document.getElementById("impl-volet-regles").style.display =
    onglet === "regles" ? "" : "none";
  // Rechargées à chaque ouverture de l'onglet, comme n'importe quel écran :
  // elles ont pu changer depuis la dernière visite.
  if (onglet === "regles") loadImplRegles();
});

/* ----- Éditeur de règles ----- */

document.getElementById("impl-regle-type").addEventListener("change", () => {
  majVisibiliteCompteRegleImpl();
  majVisibiliteTypeTitreRegleImpl();
});
document.getElementById("impl-regle-type-titre").addEventListener("change", (e) => {
  implRegleTypeTitreMemorise = e.target.value;
});
document.getElementById("impl-regle-compte").addEventListener("change", (e) => {
  implRegleCompteMemorise = e.target.value;
});
document
  .getElementById("btn-impl-regle-nouvelle")
  .addEventListener("click", () => ouvrirEditeurImplRegle());
document
  .getElementById("btn-impl-regle-annuler")
  .addEventListener("click", fermerEditeurImplRegle);
document.getElementById("btn-impl-regle-ajouter-groupe").addEventListener("click", () => {
  implRegleBrouillonGroupes.push(implGroupeVide());
  renderImplRegleGroupes();
});

document.getElementById("btn-impl-regle-enregistrer").addEventListener("click", async () => {
  const nom = document.getElementById("impl-regle-nom").value.trim();
  if (!nom) {
    showMessage(t("Donne un nom à la règle."), "error");
    return;
  }
  // Contrôles côté client pour un message immédiat et situé ; le serveur
  // revalide de toute façon la même chose (schemas.ConditionReglePlacement).
  for (const groupe of implRegleBrouillonGroupes) {
    for (const condition of groupe.conditions) {
      if (!condition.valeur.trim()) {
        showMessage(t("Chaque condition doit avoir une valeur à comparer."), "error");
        return;
      }
    }
  }

  const type = document.getElementById("impl-regle-type").value;
  // Le compte n'est transmis que si le type l'accepte : basculer vers un achat
  // l'outrepasse, sans avoir à le vider à la main.
  const compte = type === "transfert" ? document.getElementById("impl-regle-compte").value : "";
  // Symétrique : l'étiquette ne part que si le type désigne un titre.
  const typeTitre =
    type === "transfert" ? "" : document.getElementById("impl-regle-type-titre").value;

  const payload = {
    nom,
    description: document.getElementById("impl-regle-description").value.trim(),
    conditions: {
      operateur: document.getElementById("impl-regle-connecteur").value,
      groupes: implRegleBrouillonGroupes,
    },
    type_placement: type,
    compte_autre_id: compte ? Number(compte) : null,
    type_titre_id: typeTitre ? Number(typeTitre) : null,
    actif: document.getElementById("impl-regle-actif").checked,
  };

  const id = document.getElementById("impl-regle-id").value;
  try {
    if (id) {
      await apiFetch(`${IMPL_REGLES_BASE}/${id}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      showMessage(t("Règle modifiée"), "success");
    } else {
      await apiFetch(IMPL_REGLES_BASE, { method: "POST", body: JSON.stringify(payload) });
      showMessage(t("Règle créée"), "success");
    }
    fermerEditeurImplRegle();
    await loadImplRegles();
  } catch (err) {
    showMessage(err.message, "error");
  }
});


document.getElementById("btn-impl-preset-creer").addEventListener("click", async () => {
  const nom = window.prompt(t("Nom du nouveau preset (le nom de ton courtier, par exemple)"));
  if (!nom) return;
  // CE QUE LE FICHIER RACONTE se demande DÈS LA CRÉATION : c'est ce qui décide
  // des colonnes du preset, et changer d'avis ensuite oblige à toutes les
  // reprendre. Une confirmation plutôt qu'un troisième menu : deux réponses,
  // dont l'une est le cas ordinaire.
  const photo = window.confirm(
    t(
      "Ce fichier est-il une PHOTOGRAPHIE du compte (une ligne par titre détenu) ?\n\nOK : photographie.\nAnnuler : liste d'opérations (achats, ventes, transferts)."
    )
  );
  const proprietes = photo ? IMPL_PROPRIETES_POSITION : IMPL_PROPRIETES;
  try {
    const preset = await apiFetch(`${IMPL_BASE}/presets`, {
      method: "POST",
      body: JSON.stringify({
        nom,
        // Les colonnes du mode, dans l'ordre : le point de départ le plus
        // probable, et surtout une configuration valide dès la création.
        colonnes: proprietes.map(([propriete], i) => ({
          propriete,
          index: i + 1,
        })),
        ignorer_premiere_ligne: true,
        mode_lecture: photo ? "position" : "operations",
      }),
    });
    implPresetId = preset.id;
    localStorage.setItem(IMPL_CLE_PRESET_MEMORISE, String(implPresetId));
    await loadImplPresets();
    remplirSelectComptesPlacement(
      document.getElementById("impl-preset-compte"),
      preset.compte_id
    );
    await chargerPresetImpl();
    showMessage(t("Preset créé"), "success");
  } catch (err) {
    showMessage(err.message, "error");
  }
});

document.getElementById("btn-impl-preset-renommer").addEventListener("click", async () => {
  const preset = implPresetActuel();
  if (!preset) return;
  const nom = window.prompt(t("Nouveau nom"), preset.nom);
  if (!nom || nom === preset.nom) return;
  try {
    await apiFetch(implUrl(""), {
      method: "PUT",
      body: JSON.stringify({
        nom,
        compte_id: preset.compte_id,
        colonnes: implConfigColonnes,
        colonnes_comparaison: implConfigColonnesComparaison,
        mode_comparaison: implModeComparaison(),
        ignorer_premiere_ligne: document.getElementById("impl-ignorer-premiere-ligne")
          .checked,
        ...implVocabulaireSaisi(),
      }),
    });
    await loadImplPresets();
  } catch (err) {
    showMessage(err.message, "error");
  }
});

document.getElementById("btn-impl-preset-supprimer").addEventListener("click", async () => {
  const preset = implPresetActuel();
  if (!preset) return;
  if (
    !window.confirm(
      t(
        "Supprimer ce preset effacera aussi son historique d'imports et ses lignes de comparaison. Les opérations déjà importées, elles, restent. Continuer ?"
      )
    )
  )
    return;
  try {
    await apiFetch(implUrl(""), { method: "DELETE" });
    implPresetId = null;
    await loadImplPresets();
    await chargerPresetImpl();
    showMessage(t("Preset supprimé"), "success");
  } catch (err) {
    showMessage(err.message, "error");
  }
});

document
  .getElementById("btn-impl-config-enregistrer")
  .addEventListener("click", enregistrerImplConfiguration);

document.getElementById("impl-mode-comparaison").addEventListener("change", () => {
  renderImplConfigComparaison();
});

document.getElementById("btn-impl-comparaison-ajouter").addEventListener("click", () => {
  implConfigColonnesComparaison.push(implConfigColonnesComparaison.length + 1);
  renderImplConfigComparaison();
});

document.getElementById("impl-preset-compte").addEventListener("change", () => {
  // La visibilité du sélecteur « compte pour ce fichier » suit immédiatement,
  // avant même l'enregistrement : c'est le choix affiché qui compte pour
  // l'utilisateur, pas encore celui qui est en base.
  const preset = implPresetActuel();
  const select = document.getElementById("impl-preset-compte");
  if (preset) preset.compte_id = select.value ? Number(select.value) : null;
  updateImplCompteDefautVisibilite();
});

document.getElementById("btn-impl-choisir-fichier").addEventListener("click", () => {
  document.getElementById("impl-fichier").click();
});

document.getElementById("impl-fichier").addEventListener("change", (e) => {
  definirFichierImpl(e.target.files[0]);
});

const implDropzone = document.getElementById("impl-dropzone");
["dragenter", "dragover"].forEach((evenement) => {
  implDropzone.addEventListener(evenement, (e) => {
    e.preventDefault();
    implDropzone.classList.add("dragover");
  });
});
["dragleave", "drop"].forEach((evenement) => {
  implDropzone.addEventListener(evenement, (e) => {
    e.preventDefault();
    implDropzone.classList.remove("dragover");
  });
});
implDropzone.addEventListener("drop", (e) => {
  const fichier = e.dataTransfer.files && e.dataTransfer.files[0];
  if (fichier) definirFichierImpl(fichier);
});

document.getElementById("btn-impl-relire").addEventListener("click", async () => {
  const choix = document.getElementById("impl-reglage-delimiteur").value;
  implReglageDelimiteur = IMPL_DELIMITEURS[choix] || null;
  implReglageSeparateurDecimal =
    document.getElementById("impl-reglage-separateur-decimal").value || null;
  await analyserFichierImpl();
});

document.getElementById("btn-impl-tout-selectionner").addEventListener("click", () => {
  const groupes = implGroupes();
  const toutes = Object.values(groupes).flat();
  const tout = toutes.every((l) => implLignesSelectionnees.has(l.ligne));
  implLignesSelectionnees.clear();
  if (!tout) toutes.forEach((l) => implLignesSelectionnees.add(l.ligne));
  renderImplApercu();
});

document
  .getElementById("btn-impl-supprimer-selection")
  .addEventListener("click", async () => {
    implLignesSelectionnees.forEach((n) => implLignesSupprimees.add(n));
    implLignesSelectionnees.clear();
    renderImplApercu();
    await rafraichirDoublonsTransferts();
  });

document.getElementById("btn-impl-confirmer").addEventListener("click", confirmerImportImpl);

// Le compte choisi pour le fichier change ce que l'aperçu résout (la monnaie
// des lignes, le compte de chaque écriture) : le fichier est donc relu.
document.getElementById("impl-compte-defaut").addEventListener("change", () => {
  if (implFichier) analyserFichierImpl();
});

BudgetApp.extensions.enregistrer("import-placements", {
  chargeur: loadImportPlacements,
});

/* ---------- La porte d'entrée : un bouton sur la page Placements ----------
 *
 * CE QUI A CHANGÉ, ET POURQUOI. Cet écran avait son propre onglet dans la
 * barre du haut, juste à côté de « Placements financiers ». Deux onglets
 * voisins pour un même portefeuille — l'un pour le consulter, l'autre pour
 * l'alimenter — obligeaient à choisir avant de savoir : on ouvrait
 * « Placements », puis on repartait chercher l'autre. L'import est une ACTION
 * sur ce portefeuille, pas une destination parallèle : il se déclenche donc
 * depuis la page qu'il remplit, par un bouton posé au bord droit de son titre.
 *
 * COMMENT ON SE GREFFE. Le noyau n'offre aucune API « ajoute-toi à l'écran
 * d'une autre extension » ; on pose donc le bouton nous-même dans le titre de
 * `#section-placements`, dès que celui-ci existe.
 *
 * ON NE RÉ-ENREGISTRE PAS LE CHARGEUR DE « placements », contrairement à la
 * greffe des cours (cf. lecture-de-cours.js). Deux raisons, et la seconde
 * suffirait : le bouton est statique, il n'a rien à redessiner à chaque
 * ouverture de l'écran ; et il n'y a qu'UN chargeur par extension — les deux
 * greffes se le disputeraient, la dernière enregistrée effaçant l'autre.
 *
 * L'ORDRE DE CHARGEMENT NE NOUS EST PAS FAVORABLE : les scripts d'extension
 * s'exécutent dans l'ordre alphabétique des dossiers, « import-placements »
 * avant « placements ». La pose échoue donc au premier essai et se rejoue sur
 * l'événement `budgetapp:extension-chargee`, comme la greffe des cours.
 */

const IMPL_ID = "import-placements";

/**
 * Pose le bouton d'import au bord droit du titre de la page Placements.
 *
 * DANS le `<h2>` et non après lui : c'est ce qui le met sur la ligne du titre
 * sans introduire d'élément entre le titre et ce qui le suit — la barre de
 * mise à jour des cours s'insère précisément là (`h2` + `afterend`), et
 * envelopper le titre la ferait atterrir dans notre conteneur.
 *
 * Plus précisément dans le `.placements-titre-actions` que l'hôte y déclare :
 * c'est lui qui groupe les boutons au bord droit, et c'est ce qui permet à
 * plusieurs extensions d'en poser un sans se marcher dessus.
 *
 * `data-extension` fait le reste : le noyau montre et masque tout élément qui
 * le porte quand l'extension change d'état (cf. majVisibiliteNavigation).
 * Éteindre l'import depuis les Paramètres retire donc la porte d'entrée
 * sur-le-champ, sans une ligne de plus ici.
 *
 * Rend false tant que la page Placements n'est pas là : l'appelant réessaiera.
 */
function poserBoutonImportPlacements() {
  const section = document.getElementById("section-placements");
  if (!section) return false;
  if (document.getElementById("btn-impl-ouvrir")) return true;
  const titre = section.querySelector("h2");
  if (!titre) return false;
  // Le conteneur des actions, déclaré par l'hôte dans son page.html. C'est LUI
  // qui porte la marge automatique : chaque bouton portant la sienne, deux
  // extensions se partageaient l'espace libre au lieu de se grouper à droite,
  // et le premier bouton se retrouvait planté au milieu du titre.
  const actions = titre.querySelector(".placements-titre-actions");
  if (!actions) return false;

  const bouton = document.createElement("button");
  bouton.type = "button";
  bouton.id = "btn-impl-ouvrir";
  bouton.className = "placements-titre-action";
  bouton.dataset.extension = IMPL_ID;
  bouton.textContent = t("Importer des opérations");
  bouton.style.display = BudgetApp.extensions.estActive(IMPL_ID) ? "" : "none";
  // `ongletActif` : cet écran n'a pas de bouton à lui dans la barre du haut
  // (cf. `bouton: false` dans le manifeste). Sans ce second argument, plus
  // aucun onglet ne serait allumé et l'application aurait l'air d'avoir quitté
  // toutes ses pages.
  bouton.addEventListener("click", () =>
    switchSection("import-placements", { ongletActif: "placements" })
  );
  actions.appendChild(bouton);
  return true;
}

if (!poserBoutonImportPlacements()) {
  document.addEventListener("budgetapp:extension-chargee", (evenement) => {
    if (evenement.detail && evenement.detail.id === "placements") {
      poserBoutonImportPlacements();
    }
  });
}

// La sortie : on revient d'où l'on vient, jamais ailleurs.
document
  .getElementById("btn-impl-retour")
  .addEventListener("click", () => switchSection("placements"));
