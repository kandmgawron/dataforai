/* Ridge Assist — Meridian Outdoor Co. customer shop */

// ponytail: API_BASE is overridden per environment; default assumes local or API Gateway
const API_BASE = window.RIDGE_API_BASE || '/api';

// --- State ---
let currentCategory = '';
let currentSearch = '';

// --- DOM refs ---
const grid = document.getElementById('product-grid');
const gridSection = document.getElementById('product-grid-section');
const detailSection = document.getElementById('product-detail-section');
const detailContainer = document.getElementById('product-detail');
const searchInput = document.getElementById('search-input');
const searchBtn = document.getElementById('search-btn');
const backBtn = document.getElementById('back-btn');
const loading = document.getElementById('loading');
const noResults = document.getElementById('no-results');
const chatToggle = document.getElementById('chat-toggle');
const chatPanel = document.getElementById('chat-panel');
const chatClose = document.getElementById('chat-close');
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const chatMessages = document.getElementById('chat-messages');

// --- Products ---
async function fetchProducts(params = {}) {
  const qs = new URLSearchParams();
  if (params.search) qs.set('search', params.search);
  if (params.category) qs.set('l1', params.category);
  qs.set('limit', '40');

  grid.innerHTML = '';
  loading.hidden = false;
  noResults.hidden = true;

  try {
    const res = await fetch(`${API_BASE}/products?${qs}`);
    const data = await res.json();
    loading.hidden = true;
    if (!data.length) { noResults.hidden = false; return; }
    renderGrid(data);
  } catch (err) {
    loading.hidden = true;
    grid.innerHTML = `<p class="no-results">Unable to load products. Please try again.</p>`;
  }
}

function renderGrid(products) {
  grid.innerHTML = products.map(p => `
    <article class="product-card" data-sku="${p.sku}">
      <span class="brand-name">${esc(p.brand)}</span>
      <h3 class="product-name">${esc(p.name)}</h3>
      <p class="product-desc">${esc(p.short_description || '')}</p>
      <span class="product-price">£${Number(p.price_gbp).toFixed(2)}</span>
      <span class="stock-badge ${p.total_stock > 0 ? '' : 'out'}">
        ${p.total_stock > 0 ? 'In Stock' : 'Out of Stock'}
      </span>
    </article>
  `).join('');

  grid.querySelectorAll('.product-card').forEach(card => {
    card.addEventListener('click', () => showDetail(card.dataset.sku));
  });
}

async function showDetail(sku) {
  gridSection.hidden = true;
  detailSection.hidden = false;

  detailContainer.innerHTML = '<p class="loading">Loading…</p>';
  try {
    const res = await fetch(`${API_BASE}/products/${sku}`);
    const p = await res.json();
    detailContainer.innerHTML = `
      <h2>${esc(p.name)}</h2>
      <p class="detail-brand">${esc(p.brand)} · ${esc(p.category_l1)}</p>
      <p class="detail-price">£${Number(p.price_gbp).toFixed(2)}${p.sale_price_gbp ? ` <s style="color:#999;font-size:0.9rem">£${Number(p.sale_price_gbp).toFixed(2)}</s>` : ''}</p>
      <p class="detail-desc">${esc(p.long_description || p.short_description || '')}</p>
      <dl class="detail-meta">
        ${p.activity_tags ? `<dt>Activities</dt><dd>${p.activity_tags.join(', ')}</dd>` : ''}
        ${p.season ? `<dt>Season</dt><dd>${Array.isArray(p.season) ? p.season.join(', ') : p.season}</dd>` : ''}
        ${p.gender ? `<dt>Gender</dt><dd>${p.gender}</dd>` : ''}
        ${p.weight_grams ? `<dt>Weight</dt><dd>${p.weight_grams}g</dd>` : ''}
        ${p.materials ? `<dt>Materials</dt><dd>${p.materials.join('; ')}</dd>` : ''}
        <dt>Stock</dt><dd>${p.total_stock > 0 ? p.total_stock + ' units available' : 'Out of stock'}</dd>
      </dl>
    `;
  } catch {
    detailContainer.innerHTML = '<p class="no-results">Unable to load product details.</p>';
  }
}

function showGrid() {
  detailSection.hidden = true;
  gridSection.hidden = false;
}

// --- Search ---
searchBtn.addEventListener('click', () => {
  currentSearch = searchInput.value.trim();
  currentCategory = '';
  document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
  document.querySelector('.cat-btn[data-category=""]').classList.add('active');
  fetchProducts({ search: currentSearch });
});
searchInput.addEventListener('keydown', e => { if (e.key === 'Enter') searchBtn.click(); });

// --- Category nav ---
document.querySelectorAll('.cat-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentCategory = btn.dataset.category;
    currentSearch = '';
    searchInput.value = '';
    fetchProducts({ category: currentCategory });
  });
});

// --- Back button ---
backBtn.addEventListener('click', showGrid);

// --- Chat widget ---
chatToggle.addEventListener('click', () => { chatPanel.hidden = !chatPanel.hidden; });
chatClose.addEventListener('click', () => { chatPanel.hidden = true; });

chatForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;

  appendMsg(text, 'user');
  chatInput.value = '';

  try {
    await fetch(`${API_BASE}/conversations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, channel: 'web_chat' })
    });
  } catch { /* best effort */ }

  appendMsg('A member of our team will respond shortly.', 'system');
});

function appendMsg(text, type) {
  const div = document.createElement('div');
  div.className = `msg ${type}`;
  div.textContent = text;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

// --- Helpers ---
function esc(str) {
  const el = document.createElement('span');
  el.textContent = str;
  return el.innerHTML;
}

// --- Init ---
fetchProducts();
