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
const filterColour = document.getElementById('filter-colour');
const filterPriceMin = document.getElementById('filter-price-min');
const filterPriceMax = document.getElementById('filter-price-max');
const filterGender = document.getElementById('filter-gender');
const filterBtn = document.getElementById('filter-btn');

// --- Products ---
async function fetchProducts(params = {}) {
  const qs = new URLSearchParams();
  if (params.search) qs.set('search', params.search);
  if (params.category) qs.set('l1', params.category);
  if (params.colour) qs.set('colour', params.colour);
  if (params.price_min) qs.set('price_min', params.price_min);
  if (params.price_max) qs.set('price_max', params.price_max);
  if (params.gender) qs.set('gender', params.gender);
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
      <span class="stock-badge ${p.stock_total > 0 ? '' : 'out'}">
        ${p.stock_total > 0 ? 'In Stock' : 'Out of Stock'}
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

    // Parse attributes if string
    let attrs = p.attributes;
    if (typeof attrs === 'string') { try { attrs = JSON.parse(attrs); } catch { attrs = {}; } }
    attrs = attrs || {};

    const colours = attrs.colours || [];
    const sizes = attrs.sizes || [];

    // Data API returns arrays as {stringValues: [...]}
    const activities = Array.isArray(p.activities) ? p.activities : (p.activities?.stringValues || []);
    const seasons = Array.isArray(p.seasons) ? p.seasons : (p.seasons?.stringValues || []);

    detailContainer.innerHTML = `
      <h2>${esc(p.name)}</h2>
      <p class="detail-brand">${esc(p.brand)} · ${esc(p.l1 || 'Uncategorised')}${p.l2 ? ' > ' + esc(p.l2) : ''}${p.l3 ? ' > ' + esc(p.l3) : ''}</p>
      <p class="detail-price">£${Number(p.price_gbp).toFixed(2)}${p.sale_price_gbp ? ` <s class="sale-compare">£${Number(p.sale_price_gbp).toFixed(2)}</s>` : ''}${p.on_sale ? ' <span class="sale-badge">Sale</span>' : ''}</p>

      <div class="detail-section">
        <h3>Description</h3>
        <p>${esc(p.short_description || '')}</p>
        ${p.long_description ? `<p class="detail-long-desc">${esc(p.long_description)}</p>` : ''}
      </div>

      <div class="detail-section">
        <h3>Product Data</h3>
        <dl class="detail-meta">
          <dt>SKU</dt><dd>${esc(p.sku)}</dd>
          <dt>Brand</dt><dd>${esc(p.brand || 'Not specified')}</dd>
          <dt>Gender</dt><dd>${esc(p.gender || 'Not specified')}</dd>
          <dt>Weight</dt><dd>${p.weight_g ? p.weight_g + 'g' : 'Not specified'}</dd>
          <dt>Colours</dt><dd>${colours.length ? colours.map(c => '<span class="tag">' + esc(c) + '</span>').join(' ') : '<span class="missing">Not in structured data</span>'}</dd>
          <dt>Sizes</dt><dd>${sizes.length ? sizes.map(s => '<span class="tag">' + esc(s) + '</span>').join(' ') : '<span class="missing">Not in structured data</span>'}</dd>
          <dt>Activities</dt><dd>${activities.length ? activities.map(a => '<span class="tag">' + esc(a) + '</span>').join(' ') : '<span class="missing">Not specified</span>'}</dd>
          <dt>Seasons</dt><dd>${seasons.length ? seasons.map(s => '<span class="tag">' + esc(s) + '</span>').join(' ') : '<span class="missing">Not specified</span>'}</dd>
          <dt>Materials</dt><dd>${p.materials && p.materials.length ? p.materials.join(', ') : '<span class="missing">Not in structured data</span>'}</dd>
          <dt>In Stock</dt><dd>${p.in_stock ? 'Yes' : 'No'} (${p.stock_total || 0} units)</dd>
        </dl>
      </div>

      <div class="detail-section">
        <h3>Raw Supplier Attributes</h3>
        <p class="data-note">This is the raw JSONB data as received from the supplier. Note inconsistent naming, formatting, and missing fields across products.</p>
        <pre class="raw-json">${esc(JSON.stringify(attrs, null, 2))}</pre>
      </div>
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
  fetchProducts(getFilters());
});
searchInput.addEventListener('keydown', e => { if (e.key === 'Enter') searchBtn.click(); });

// --- Filters ---
filterBtn.addEventListener('click', () => fetchProducts(getFilters()));

function getFilters() {
  return {
    search: currentSearch || searchInput.value.trim(),
    category: currentCategory,
    colour: filterColour.value.trim(),
    price_min: filterPriceMin.value,
    price_max: filterPriceMax.value,
    gender: filterGender.value,
  };
}

// --- Category nav ---
document.querySelectorAll('.cat-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentCategory = btn.dataset.category;
    currentSearch = '';
    searchInput.value = '';
    fetchProducts(getFilters());
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
