/* ---------- Extension « Intérêts perçus » ----------
 *
 * Note ce que chaque compte d'épargne a RÉELLEMENT rapporté. Ce fichier
 * s'exécute dans la portée globale de la page, après l'injection de page.html :
 * tout ce que app.js expose lui est accessible (apiFetch, t, showMessage,
 * formatMontant, escapeHtml, formatDate…), et les éléments sur lesquels il pose
 * ses écouteurs existent déjà.
 *
 * POURQUOI ON SAISIT AU LIEU DE CALCULER. La version précédente partait d'un
 * taux annuel et d'une fréquence, et reconstituait les intérêts en découpant le
 * temps en périodes sans mouvement. Le calcul était juste, et c'était son
 * problème : il ne pouvait l'être que si l'app connaissait TOUS les mouvements
 * du compte, à leur date exacte, depuis l'ouverture. Un livret ouvert avant la
 * première ligne importée, un taux qui change en cours d'année (le Livret A l'a
 * fait deux fois en 2025), une banque qui arrondit autrement : le chiffre
 * affiché divergeait du relevé sans que rien ne dise lequel croire. La banque,
 * elle, ANNONCE le montant — le saisir prend dix secondes et vaut n'importe
 * quelle reconstitution.
 *
 * UNE FENÊTRE, PAS UNE PAGE. Ce qu'un livret rapporte se regarde en regardant
 * ses comptes d'épargne : l'écran s'ouvre par un bouton posé à côté du titre
 * « Comptes d'épargne » de la page Comptes, et la page reste visible derrière,
 * assombrie et floutée. Même mise en retrait que la fenêtre des extensions au
 * lancement — même classe `.modale-fond`, même verrou de défilement — parce que
 * c'est la même chose qui se produit : la page attend.
 *
 * RIEN N'EST ÉCRIT EN OPÉRATIONS : ni mouvement, ni solde recalculé. Ce que cet
 * écran montre ne pèse sur aucun autre chiffre de l'application.
 */

/* TOUT CE QUI EST DÉCLARÉ ICI EST GLOBAL, ET PARTAGÉ AVEC TOUTES LES AUTRES
 * EXTENSIONS. Les scripts d'extension s'exécutent en portée globale, dans
 * l'ordre alphabétique des dossiers (cf. extensions/README.md) : une fonction
 * nommée `totauxHtml` ici était purement et simplement ÉCRASÉE par celle du
 * même nom dans `projets`, qui se charge après — et l'écran affichait alors les
 * totaux d'un projet, à zéro, sans la moindre erreur en console. D'où le
 * préfixe `epargne` sur tout ce que ce fichier déclare, sans exception. */

const EPARGNE_BASE = "/interets-percus";
const EPARGNE_ID = "interets-percus";

let epargneComptes = [];
// Le versement en cours de retouche, par compte : `null` = le formulaire de ce
// compte ajoute une ligne. Un seul par compte, jamais deux en même temps.
const epargneEnEdition = {};

async function loadInteretsPercus() {
  try {
    // Les monnaies servent à formater les montants : elles ont pu changer
    // depuis la dernière visite de cet écran.
    await refreshMonnaies();
    epargneComptes = await apiFetch(`${EPARGNE_BASE}/comptes`);
  } catch (err) {
    showMessage(err.message, "error");
    return;
  }

  const aucun = epargneComptes.length === 0;
  document.getElementById("epargne-aucun-compte").style.display = aucun ? "" : "none";
  epargneRender();
}

/** Les totaux d'une monnaie à l'autre, sur une ligne. Jamais additionnés. */
function epargneTotauxHtml(totaux) {
  if (totaux.length === 0) return `<span class="epargne-vide">—</span>`;
  return totaux
    .map((total) => `<span class="epargne-total">${escapeHtml(formatMontant(total.montant, total.monnaie_id))}</span>`)
    .join("");
}

/**
 * Le récapitulatif par année.
 *
 * PAR ANNÉE parce que c'est le rythme auquel une banque verse et annonce ses
 * intérêts : « ce livret m'a rapporté 142 € en 2025 contre 96 € en 2024 » est
 * la seule comparaison qui veuille dire quelque chose. Un total par mois ne
 * dirait rien — il n'y a qu'un ou deux versements dans l'année.
 */
function epargneAnneesHtml(compte) {
  if (compte.annees.length === 0) return "";
  const lignes = compte.annees
    .map(
      (annee) => `
      <tr>
        <td>${annee.annee}</td>
        <td class="montant">${epargneTotauxHtml(annee.totaux)}</td>
      </tr>`
    )
    .join("");
  return `
    <table class="epargne-annees">
      <thead><tr><th>Année</th><th class="montant">Versé</th></tr></thead>
      <tbody>${lignes}</tbody>
    </table>`;
}

/** La liste des versements : ce qui a été saisi, tel quel. */
function epargneVersementsHtml(compte) {
  if (compte.interets.length === 0) {
    return `<p class="hint">Aucun versement saisi pour ce compte.</p>`;
  }
  const lignes = compte.interets
    .map(
      (interet) => `
      <tr>
        <td>${escapeHtml(formatDate(interet.date))}</td>
        <td>${escapeHtml(interet.libelle) || `<span class="epargne-vide">—</span>`}</td>
        <td class="montant">${escapeHtml(formatMontant(interet.montant, interet.monnaie_id))}</td>
        <td class="actions-cellule">
          <button type="button" data-epargne-modifier="${interet.id}">Modifier</button>
          <button type="button" class="danger" data-epargne-supprimer="${interet.id}"
                  title="Supprimer ce versement">${ICONE_POUBELLE}</button>
        </td>
      </tr>`
    )
    .join("");
  return `
    <table class="epargne-versements">
      <thead>
        <tr><th>Date</th><th>Libellé</th><th class="montant">Montant</th><th>Actions</th></tr>
      </thead>
      <tbody>${lignes}</tbody>
    </table>`;
}

/**
 * Le formulaire d'un compte : ajout, ou retouche du versement en cours.
 *
 * LE SÉLECTEUR DE MONNAIE N'APPARAÎT QUE SI LE COMPTE EN A PLUSIEURS. Presque
 * tous les livrets sont mono-devises : leur proposer un choix à une seule
 * option serait un champ à traverser pour rien, à chaque saisie.
 */
function epargneFormulaireHtml(compte) {
  const enEdition = epargneEnEdition[compte.id];
  const interet = enEdition ? compte.interets.find((i) => i.id === enEdition) : null;
  const monnaieChoisie = interet ? interet.monnaie_id : compte.monnaies[0]?.monnaie_id;
  const selecteurMonnaie =
    compte.monnaies.length > 1
      ? `<label>Monnaie
           <select data-epargne-champ="monnaie" data-compte="${compte.id}">
             ${compte.monnaies
               .map(
                 (m) =>
                   `<option value="${m.monnaie_id}"${
                     m.monnaie_id === monnaieChoisie ? " selected" : ""
                   }>${escapeHtml(m.monnaie_nom)}</option>`
               )
               .join("")}
           </select>
         </label>`
      : "";

  return `
    <form class="epargne-form" data-compte="${compte.id}">
      <label>Date
        <input type="date" data-epargne-champ="date" data-compte="${compte.id}"
               value="${interet ? interet.date : ""}" required />
      </label>
      <label>Montant perçu
        <input type="number" step="0.01" min="0.01" data-epargne-champ="montant"
               data-compte="${compte.id}" value="${interet ? interet.montant : ""}" required />
      </label>
      ${selecteurMonnaie}
      <label>Libellé
        <input type="text" data-epargne-champ="libelle" data-compte="${compte.id}"
               placeholder="intérêts 2025" value="${interet ? escapeHtml(interet.libelle) : ""}" />
      </label>
      <div class="actions">
        <button type="submit" class="primary">${interet ? "Enregistrer" : "Ajouter"}</button>
        ${interet ? `<button type="button" data-epargne-annuler="${compte.id}">Annuler</button>` : ""}
      </div>
    </form>`;
}

/* UN `div` ET NON UN `section`. Le noyau pose `section { display: none }` et ne
 * les révèle qu'avec la classe `.active` (c'est ainsi qu'il bascule d'un écran
 * à l'autre, cf. style.css) : un `<section>` écrit par une extension est donc
 * INVISIBLE, sans erreur ni avertissement — le contenu est bien dans le DOM,
 * `textContent` le rend, et seule la hauteur nulle du conteneur le trahit. */
function epargneRender() {
  document.getElementById("epargne-comptes").innerHTML = epargneComptes
    .map(
      (compte) => `
      <div class="epargne-compte">
        <div class="epargne-compte-entete">
          <h3>${escapeHtml(compte.nom)}</h3>
          <div class="epargne-compte-total">
            <span class="hint">Total perçu</span>
            ${epargneTotauxHtml(compte.totaux)}
          </div>
        </div>
        ${epargneAnneesHtml(compte)}
        ${epargneVersementsHtml(compte)}
        ${epargneFormulaireHtml(compte)}
      </div>`
    )
    .join("");
}

/* ---------- Écriture ---------- */

// Écouteurs DÉLÉGUÉS sur le conteneur, et non posés ligne par ligne : le
// contenu est réécrit en entier à chaque enregistrement, et des écouteurs
// individuels seraient à reposer à chaque fois — c'est le mécanisme que app.js
// emploie partout ailleurs pour la même raison.
document.getElementById("epargne-comptes").addEventListener("submit", async (e) => {
  const form = e.target.closest(".epargne-form");
  if (!form) return;
  e.preventDefault();

  const compteId = Number(form.dataset.compte);
  const lire = (champ) =>
    form.querySelector(`[data-epargne-champ="${champ}"]`)?.value.trim() ?? "";
  const monnaie = form.querySelector('[data-epargne-champ="monnaie"]');
  const corps = {
    date: lire("date"),
    montant: Number(lire("montant")),
    libelle: lire("libelle"),
    // Absent quand le compte est mono-devise : le serveur retombe alors sur sa
    // monnaie principale (cf. _valider_monnaie).
    monnaie_id: monnaie ? Number(monnaie.value) : null,
  };
  if (!corps.date || !(corps.montant > 0)) {
    showMessage(t("Une date et un montant supérieur à zéro sont nécessaires."), "error");
    return;
  }

  const enEdition = epargneEnEdition[compteId];
  try {
    const compte = enEdition
      ? await apiFetch(`${EPARGNE_BASE}/interets/${enEdition}`, {
          method: "PUT",
          body: JSON.stringify(corps),
        })
      : await apiFetch(`${EPARGNE_BASE}/comptes/${compteId}/interets`, {
          method: "POST",
          body: JSON.stringify(corps),
        });
    epargneEnEdition[compteId] = null;
    epargneRemplacerCompte(compte);
    showMessage(enEdition ? t("Versement modifié.") : t("Versement ajouté."), "success");
  } catch (err) {
    showMessage(err.message, "error");
  }
});

document.getElementById("epargne-comptes").addEventListener("click", async (e) => {
  const annuler = e.target.closest("[data-epargne-annuler]");
  if (annuler) {
    epargneEnEdition[Number(annuler.dataset.epargneAnnuler)] = null;
    epargneRender();
    return;
  }

  const modifier = e.target.closest("[data-epargne-modifier]");
  if (modifier) {
    const id = Number(modifier.dataset.epargneModifier);
    const compte = epargneComptes.find((c) => c.interets.some((i) => i.id === id));
    if (compte) {
      epargneEnEdition[compte.id] = id;
      epargneRender();
    }
    return;
  }

  const supprimer = e.target.closest("[data-epargne-supprimer]");
  if (!supprimer) return;
  const id = Number(supprimer.dataset.epargneSupprimer);
  if (!confirm(t("Supprimer ce versement d'intérêts ?"))) return;
  try {
    const compte = await apiFetch(`${EPARGNE_BASE}/interets/${id}`, { method: "DELETE" });
    // Le versement supprimé pouvait être celui en cours de retouche : le
    // formulaire doit repasser en ajout, sinon il enregistrerait vers un id
    // qui n'existe plus.
    if (epargneEnEdition[compte.id] === id) epargneEnEdition[compte.id] = null;
    epargneRemplacerCompte(compte);
    showMessage(t("Versement supprimé."), "success");
  } catch (err) {
    showMessage(err.message, "error");
  }
});

/**
 * Range à sa place le compte que le serveur vient de rendre.
 *
 * Les trois routes d'écriture rendent le COMPTE ENTIER et non la ligne touchée :
 * les totaux et les années changent à chaque saisie, et les redemander ferait
 * une seconde requête là où l'écran a besoin d'un seul état cohérent.
 */
function epargneRemplacerCompte(compte) {
  const index = epargneComptes.findIndex((c) => c.id === compte.id);
  if (index >= 0) epargneComptes[index] = compte;
  epargneRender();
}

/* ---------- La fenêtre ---------- */

function ouvrirModaleEpargne() {
  document.getElementById("modale-epargne").style.display = "";
  // La page derrière ne doit plus défiler : une molette au-dessus d'une fenêtre
  // fait sinon glisser le contenu grisé, ce qui donne l'impression que le clic
  // est passé au travers. Même classe que la fenêtre des extensions.
  document.body.classList.add("modale-ouverte");
  // Rechargé à chaque ouverture, comme n'importe quel écran.
  loadInteretsPercus();
  document.getElementById("btn-epargne-fermer").focus();
}

function fermerModaleEpargne() {
  document.getElementById("modale-epargne").style.display = "none";
  document.body.classList.remove("modale-ouverte");
}

document.getElementById("btn-epargne-fermer").addEventListener("click", fermerModaleEpargne);

// Clic sur le fond (hors de la boîte) et Échap : les deux sorties qu'on essaie
// d'instinct. Rien n'est perdu en fermant — chaque versement est enregistré par
// son propre bouton, jamais en quittant l'écran.
document.getElementById("modale-epargne").addEventListener("click", (e) => {
  if (e.target.id === "modale-epargne") fermerModaleEpargne();
});

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (document.getElementById("modale-epargne").style.display !== "none") {
    fermerModaleEpargne();
  }
});

/**
 * Pose le bouton d'ouverture à côté du titre « Comptes d'épargne ».
 *
 * Le titre est du HTML STATIQUE du noyau (index.html) : il est là dès le
 * chargement, et le bouton n'a donc à être posé qu'une fois — contrairement aux
 * greffes qui doivent se reposer après chaque rendu.
 *
 * `data-extension` suffit à le faire disparaître et réapparaître avec
 * l'extension : le noyau montre et masque tout élément qui le porte (cf.
 * majVisibiliteNavigation).
 */
function poserBoutonEpargne() {
  const bloc = document.getElementById("globale-bloc-epargne");
  if (!bloc || document.getElementById("btn-epargne-ouvrir")) return;
  const titre = bloc.querySelector("h3");
  if (!titre) return;

  titre.classList.add("epargne-titre-avec-action");
  const bouton = document.createElement("button");
  bouton.type = "button";
  bouton.id = "btn-epargne-ouvrir";
  bouton.className = "epargne-titre-action";
  bouton.dataset.extension = EPARGNE_ID;
  bouton.textContent = t("Intérêts perçus");
  bouton.style.display = BudgetApp.extensions.estActive(EPARGNE_ID) ? "" : "none";
  bouton.addEventListener("click", ouvrirModaleEpargne);
  titre.appendChild(bouton);
}

poserBoutonEpargne();
