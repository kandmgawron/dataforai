/* Ridge Insight — Internal CRM */

const API_BASE = window.RIDGE_API_BASE || '/api';

// --- Navigation ---
document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const view = btn.dataset.view;
    document.querySelectorAll('.view').forEach(v => v.hidden = true);
    document.getElementById(`view-${view}`).hidden = false;

    // Auto-load data for conversations and policies
    if (view === 'conversations') loadConversations();
    if (view === 'policies') loadPolicies();
  });
});

// --- Customers ---
const customerSearch = document.getElementById('customer-search');
const customerSearchBtn = document.getElementById('customer-search-btn');
const customerResults = document.getElementById('customer-results');
const customerDetail = document.getElementById('customer-detail');

customerSearchBtn.addEventListener('click', searchCustomers);
customerSearch.addEventListener('keydown', e => { if (e.key === 'Enter') searchCustomers(); });

async function searchCustomers() {
  const q = customerSearch.value.trim();
  if (!q) return;
  customerDetail.hidden = true;
  customerResults.innerHTML = '<p class="subtitle">Searching…</p>';

  try {
    const res = await fetch(`${API_BASE}/customers?search=${encodeURIComponent(q)}&limit=20`);
    const data = await res.json();
    if (!data.length) { customerResults.innerHTML = '<p class="subtitle">No customers found.</p>'; return; }
    customerResults.innerHTML = data.map(c => `
      <div class="result-card" data-id="${c.customer_id}">
        <h3>${esc(c.first_name)} ${esc(c.last_name)}</h3>
        <p class="meta">${esc(c.email)} · ${esc(c.customer_id)} · <span class="badge badge-${c.loyalty_tier}">${c.loyalty_tier}</span></p>
      </div>
    `).join('');
    customerResults.querySelectorAll('.result-card').forEach(card => {
      card.addEventListener('click', () => loadCustomerDetail(card.dataset.id));
    });
  } catch {
    customerResults.innerHTML = '<p class="subtitle">Error loading customers.</p>';
  }
}

async function loadCustomerDetail(id) {
  customerResults.innerHTML = '';
  customerDetail.hidden = false;
  customerDetail.innerHTML = '<p class="subtitle">Loading…</p>';

  try {
    const res = await fetch(`${API_BASE}/customers/${id}`);
    const c = await res.json();
    const convos = c.conversations || [];
    customerDetail.innerHTML = `
      <button class="back-link" onclick="this.parentElement.hidden=true">← Back to results</button>
      <div class="customer-profile">
        <h3>${esc(c.first_name)} ${esc(c.last_name)} <span class="badge badge-${c.loyalty_tier}">${c.loyalty_tier}</span></h3>
        <dl>
          <dt>Customer ID</dt><dd>${esc(c.customer_id)}</dd>
          <dt>Email</dt><dd>${esc(c.email)}</dd>
          <dt>Phone</dt><dd>${esc(c.phone || 'N/A')}</dd>
          <dt>Postcode</dt><dd>${esc(c.postcode || 'N/A')}</dd>
          <dt>Segment</dt><dd>${esc(c.segment)}</dd>
          <dt>Lifetime Value</dt><dd>£${Number(c.lifetime_value_gbp).toFixed(2)}</dd>
          <dt>Order Count</dt><dd>${c.order_count}</dd>
          <dt>Avg Order</dt><dd>£${Number(c.avg_order_value_gbp).toFixed(2)}</dd>
          <dt>Last Purchase</dt><dd>${esc(c.last_purchase_date || 'N/A')}</dd>
          <dt>Preferred Store</dt><dd>${esc(c.preferred_store || 'N/A')}</dd>
          <dt>Favourite Categories</dt><dd>${(c.favourite_categories || []).join(', ')}</dd>
        </dl>
      </div>
      ${convos.length ? `
        <h3 style="margin-top:1.25rem;font-size:1rem;">Recent Conversations</h3>
        ${convos.slice(0, 10).map(cv => `
          <div class="convo-card">
            <div class="convo-header">
              <span>${esc(cv.conversation_id)} · ${esc(cv.channel)}</span>
              <span>${esc(cv.created_at || '')}</span>
            </div>
            <p class="convo-msg">${esc(cv.topic)} — ${esc(cv.status)}</p>
          </div>
        `).join('')}
      ` : ''}
    `;
  } catch {
    customerDetail.innerHTML = '<p class="subtitle">Error loading customer.</p>';
  }
}

// --- Conversations ---
const conversationsList = document.getElementById('conversations-list');

async function loadConversations() {
  conversationsList.innerHTML = '<p class="subtitle">Loading…</p>';
  try {
    const res = await fetch(`${API_BASE}/conversations`);
    const data = await res.json();
    if (!data.length) { conversationsList.innerHTML = '<p class="subtitle">No conversations in queue.</p>'; return; }
    conversationsList.innerHTML = data.map(cv => `
      <div class="convo-card">
        <div class="convo-header">
          <span>${esc(cv.customer_id || 'Anonymous')} · ${esc(cv.channel || 'web_chat')}</span>
          <span>${esc(cv.created_at || '')}</span>
        </div>
        <p class="convo-msg">${esc(cv.message || cv.topic || '')}</p>
      </div>
    `).join('');
  } catch {
    conversationsList.innerHTML = '<p class="subtitle">Error loading conversations.</p>';
  }
}

// --- Products ---
const productSearch = document.getElementById('product-search');
const productSearchBtn = document.getElementById('product-search-btn');
const productResults = document.getElementById('product-results');

productSearchBtn.addEventListener('click', searchProducts);
productSearch.addEventListener('keydown', e => { if (e.key === 'Enter') searchProducts(); });

async function searchProducts() {
  const q = productSearch.value.trim();
  if (!q) return;
  productResults.innerHTML = '<p class="subtitle">Searching…</p>';
  try {
    const res = await fetch(`${API_BASE}/products?search=${encodeURIComponent(q)}&limit=30`);
    const data = await res.json();
    if (!data.length) { productResults.innerHTML = '<p class="subtitle">No products found.</p>'; return; }
    productResults.innerHTML = data.map(p => `
      <div class="product-row">
        <div class="product-info">
          <h4>${esc(p.name)}</h4>
          <p class="meta">${esc(p.sku)} · ${esc(p.brand)} · ${esc(p.category_l1)} · £${Number(p.price_gbp).toFixed(2)}</p>
        </div>
        <span class="product-stock">${p.total_stock} in stock</span>
      </div>
    `).join('');
  } catch {
    productResults.innerHTML = '<p class="subtitle">Error searching products.</p>';
  }
}

// --- Policies ---
const policiesList = document.getElementById('policies-list');
const policyDetail = document.getElementById('policy-detail');

async function loadPolicies() {
  policyDetail.hidden = true;
  policiesList.hidden = false;
  policiesList.innerHTML = '<p class="subtitle">Loading…</p>';
  try {
    const res = await fetch(`${API_BASE}/policies`);
    const data = await res.json();
    if (!data.length) { policiesList.innerHTML = '<p class="subtitle">No policies found.</p>'; return; }
    policiesList.innerHTML = data.map(p => `
      <div class="policy-card" data-id="${esc(p.doc_id)}">
        <strong>${esc(p.title || p.doc_id)}</strong>
        ${p.category ? `<span class="meta"> · ${esc(p.category)}</span>` : ''}
      </div>
    `).join('');
    policiesList.querySelectorAll('.policy-card').forEach(card => {
      card.addEventListener('click', () => loadPolicyDetail(card.dataset.id));
    });
  } catch {
    policiesList.innerHTML = '<p class="subtitle">Error loading policies.</p>';
  }
}

async function loadPolicyDetail(docId) {
  policiesList.hidden = true;
  policyDetail.hidden = false;
  policyDetail.innerHTML = '<p class="subtitle">Loading…</p>';
  try {
    const res = await fetch(`${API_BASE}/policies/${docId}`);
    const data = await res.json();
    policyDetail.innerHTML = `
      <button class="back-link" id="policy-back">← Back to policies</button>
      <h3>${esc(data.title || data.doc_id)}</h3>
      <div class="policy-content">${esc(data.content || '')}</div>
    `;
    document.getElementById('policy-back').addEventListener('click', loadPolicies);
  } catch {
    policyDetail.innerHTML = '<p class="subtitle">Error loading policy.</p>';
  }
}

// --- Helpers ---
function esc(str) {
  if (str == null) return '';
  const el = document.createElement('span');
  el.textContent = String(str);
  return el.innerHTML;
}
