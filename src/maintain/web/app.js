/* All document/user values go through textContent, never through innerHTML. */
const $ = (id) => document.getElementById(id);
let token = '', assets = [], currentRun = null, ticketKey = null;
function node(tag, text, className) {
  const el = document.createElement(tag); el.textContent = text;
  if (className) el.className = className; return el;
}
function message(text) { $('message').textContent = text; }
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: {
    'Content-Type': 'application/json', 'Authorization': `Bearer ${token}`,
    ...(options.headers || {})
  }});
  const data = await response.json();
  if (!response.ok) throw new Error(`${data.error?.message || data.error?.code || 'Erreur'} (${response.status})`);
  return data;
}
function clearRun() {
  currentRun = null; ticketKey = null;
  $('ticket-panel').hidden = true; $('ticket-status').textContent = '';
}
function variant() {
  clearRun();
  const item = assets.find(a => a.id === $('asset').value);
  $('variant').textContent = item ? `${item.model} / ${item.hardware} / firmware ${item.firmware || 'à confirmer'}` : '';
}
$('login').addEventListener('submit', async (event) => {
  event.preventDefault(); clearRun(); token = $('token').value.trim();
  try {
    const identity = await api('/v1/me'); assets = await api('/v1/assets');
    $('identity').textContent = `${identity.id} · ${identity.site} · ${identity.role}`;
    $('asset').replaceChildren(...assets.map(a => {
      const option = node('option', `${a.id} · ${a.model}`); option.value = a.id; return option;
    }));
    for (const id of ['asset', 'question', 'search-button']) $(id).disabled = false;
    $('token').value = ''; $('login').hidden = true; $('logout').hidden = false;
    $('results').replaceChildren(node('p', 'Workspace connecté. Lancez une recherche.', 'subtle'));
    variant(); message('Connexion établie. La clé reste uniquement en mémoire dans cet onglet.');
  } catch (error) { token = ''; message(error.message); }
});
$('logout').addEventListener('click', () => { token = ''; window.location.reload(); });
$('asset').addEventListener('change', () => {
  variant(); $('results').replaceChildren(node('p', 'Équipement modifié. Relancez la recherche.', 'subtle'));
});
$('question').addEventListener('input', clearRun);
document.querySelectorAll('[data-query]').forEach(button => button.addEventListener('click', () => {
  $('question').value = button.dataset.query; clearRun(); $('question').focus();
}));
$('search').addEventListener('submit', async event => {
  event.preventDefault(); clearRun(); $('search-button').disabled = true; message('Recherche en cours…');
  const assetId = $('asset').value, question = $('question').value;
  $('results').replaceChildren(node('p', 'Recherche des références applicables…', 'subtle'));
  try {
    const result = await api('/v1/answers', { method: 'POST', body: JSON.stringify({asset_id: assetId, question}) });
    if (assetId !== $('asset').value || question !== $('question').value) {
      $('results').replaceChildren(node('p', 'Contexte modifié. Relancez la recherche.', 'subtle')); return;
    }
    $('results').replaceChildren();
    $('results').append(node('div', result.status === 'evidence_found' ? `${result.sources.length} référence(s) applicable(s)` : 'Abstention documentaire', 'result-title'));
    if (result.reason) $('results').append(node('p', result.reason, 'notice'));
    result.sources.forEach((source, index) => {
      const card = node('article', '', 'source');
      card.append(node('p', `SOURCE ${String(index + 1).padStart(2, '0')} / RÉVISION ${source.revision} / PAGE ${source.page}`, 'eyebrow'));
      card.append(node('h3', source.title), node('p', source.text, 'excerpt'));
      const open = node('button', 'Vérifier la page source ↗', 'secondary'); open.type = 'button';
      open.addEventListener('click', async () => {
        try {
          const page = await api(`/v1/documents/${encodeURIComponent(source.document_id)}/pages/${source.page}`);
          card.append(node('pre', page.text, 'page-preview')); open.disabled = true;
        } catch (error) { message(error.message); }
      });
      card.append(open); $('results').append(card);
    });
    if (result.status === 'evidence_found') {
      currentRun = { ...result, asset_id: assetId }; ticketKey = crypto.randomUUID();
      $('ticket-panel').hidden = false; $('observations').value = ''; $('confirmed').checked = false;
    }
    message('Recherche terminée. Vérifiez les références avant toute utilisation.');
  } catch (error) { message(error.message); }
  finally { $('search-button').disabled = false; }
});
$('ticket-form').addEventListener('submit', async event => {
  event.preventDefault(); if (!currentRun) return;
  $('ticket-button').disabled = true;
  try {
    const result = await api('/v1/tickets', {method: 'POST', headers: {'Idempotency-Key': ticketKey},
      body: JSON.stringify({run_id: currentRun.run_id, asset_id: currentRun.asset_id,
        observations: $('observations').value, confirmed: $('confirmed').checked})});
    $('ticket-status').textContent = `Ticket ${result.id} · ${result.status}. Exécutez « maintain dispatch » pour la livraison simulée.`;
    message('Ticket enregistré avec confirmation. Un nouvel envoi identique réutilisera le même ticket.');
  } catch (error) { message(error.message); }
  finally { $('ticket-button').disabled = false; }
});
