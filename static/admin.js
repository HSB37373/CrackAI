'use strict';

const API = window.location.pathname.replace(/\/[^/]*$/, '') || '.';
let faqData = {};
let currentType = null;

// ── 초기 로드 ──────────────────────────────────────────────────────────────
async function loadFaq() {
  try {
    const res = await fetch(`${API}/admin/faq`);
    faqData = await res.json();
  } catch {
    faqData = {};
  }
  renderSidebar();
  const first = Object.keys(faqData)[0];
  if (first) selectType(first);
}

// ── 사이드바 ───────────────────────────────────────────────────────────────
function renderSidebar() {
  const list = document.getElementById('type-list');
  list.innerHTML = '';
  for (const type of Object.keys(faqData)) {
    const btn = document.createElement('button');
    btn.className = 'type-btn' + (type === currentType ? ' active' : '');
    btn.textContent = type;
    btn.onclick = () => selectType(type);
    list.appendChild(btn);
  }
}

function selectType(type) {
  currentType = type;
  renderSidebar();
  renderForm(faqData[type] || {});
}

// ── 편집 폼 렌더링 ────────────────────────────────────────────────────────
function renderForm(data) {
  const form = document.getElementById('edit-form');

  form.innerHTML = `
    <div class="form-type-title">${esc(currentType)}</div>

    <!-- 기본 정보 -->
    <div class="form-section">
      <div class="form-section-title">기본 정보</div>
      <div class="form-row">
        <span class="form-label">민원명</span>
        <input class="form-input" id="f-name" value="${esc(data['민원명'] || '')}" placeholder="민원 이름">
      </div>
      <div class="form-row">
        <span class="form-label">담당 부서</span>
        <input class="form-input" id="f-dept" value="${esc(data['담당부서'] || '')}" placeholder="예: 교통행정과">
      </div>
      <div class="form-row">
        <span class="form-label">연락처</span>
        <input class="form-input" id="f-tel" value="${esc(data['연락처'] || '')}" placeholder="예: 031-XXX-XXXX">
      </div>
      <div class="form-row">
        <span class="form-label">처리 기간</span>
        <input class="form-input" id="f-period" value="${esc(data['처리기간'] || '')}" placeholder="예: 접수 후 14일 이내">
      </div>
    </div>

    <!-- 필요 서류 -->
    <div class="form-section">
      <div class="form-section-title">필요 서류</div>
      <div class="tags-area" id="docs-tags">
        ${(data['필요서류'] || []).map(d => tagHtml(d)).join('')}
        <input class="tag-add-input" id="doc-input" placeholder="서류 입력 후 Enter">
      </div>
    </div>

    <!-- 기본 안내문 -->
    <div class="form-section">
      <div class="form-section-title">기본 안내문</div>
      <textarea class="form-textarea" id="f-guide" style="min-height:100px">${esc(data['안내'] || '')}</textarea>
    </div>

    <!-- AI 응대 기준 -->
    <div class="form-section">
      <div class="form-section-title">AI 응대 기준</div>
      <textarea class="form-textarea" id="f-standard" style="min-height:80px" placeholder="AI가 응대 시 지켜야 할 기준을 입력하세요.&#10;예) 과태료 금액은 정확히 안내하고, 이의신청 기간(60일)을 반드시 언급할 것. 모르는 내용은 담당 부서 연락처를 안내할 것.">${esc(data['응대기준'] || '')}</textarea>
    </div>

    <!-- FAQ -->
    <div class="form-section">
      <div class="form-section-title">FAQ</div>
      <div id="faq-list">
        ${(data['faq'] || []).map((item, i) => faqItemHtml(item, i)).join('')}
      </div>
      <button class="add-faq-btn" onclick="addFaqItem()">+ FAQ 항목 추가</button>
    </div>

    <!-- 액션 -->
    <div class="form-actions">
      <button class="delete-type-btn" onclick="deleteType()">유형 삭제</button>
      <button class="save-btn" onclick="saveType()">저장</button>
    </div>
  `;

  // 필요서류 입력 핸들러
  document.getElementById('doc-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      const val = e.target.value.trim();
      if (val) {
        const span = document.createElement('span');
        span.className = 'tag-item';
        span.dataset.val = val;
        span.innerHTML = `${esc(val)}<button class="tag-del" onclick="this.parentElement.remove()">×</button>`;
        e.target.parentElement.insertBefore(span, e.target);
        e.target.value = '';
      }
    }
  });
}

function tagHtml(val) {
  return `<span class="tag-item" data-val="${esc(val)}">${esc(val)}<button class="tag-del" onclick="this.parentElement.remove()">×</button></span>`;
}

function faqItemHtml(item, index) {
  return `
    <div class="faq-item">
      <div class="faq-item-header">
        <span class="faq-num">FAQ ${index + 1}</span>
        <button class="faq-del-btn" onclick="this.closest('.faq-item').remove(); reNumberFaq()">삭제</button>
      </div>
      <div class="faq-sub-label">키워드 (쉼표로 구분)</div>
      <input class="form-input faq-keywords" value="${esc((item.keywords || []).join(', '))}"
             placeholder="예: 취소, 이의, 어떻게" style="margin-bottom:8px">
      <div class="faq-sub-label">답변</div>
      <textarea class="form-textarea faq-answer" style="min-height:70px">${esc(item.answer || '')}</textarea>
    </div>
  `;
}

function addFaqItem() {
  const list = document.getElementById('faq-list');
  const count = list.querySelectorAll('.faq-item').length;
  const div = document.createElement('div');
  div.innerHTML = faqItemHtml({ keywords: [], answer: '' }, count);
  list.appendChild(div.firstElementChild);
}

function reNumberFaq() {
  document.querySelectorAll('.faq-item').forEach((item, i) => {
    const num = item.querySelector('.faq-num');
    if (num) num.textContent = `FAQ ${i + 1}`;
  });
}

// ── 데이터 수집 ───────────────────────────────────────────────────────────
function collectFormData() {
  const data = {
    '민원명':   document.getElementById('f-name').value.trim(),
    '담당부서': document.getElementById('f-dept').value.trim(),
    '연락처':   document.getElementById('f-tel').value.trim(),
    '처리기간': document.getElementById('f-period').value.trim(),
    '필요서류': [],
    '안내':     document.getElementById('f-guide').value.trim(),
    '응대기준': document.getElementById('f-standard').value.trim(),
    'faq': [],
  };

  document.querySelectorAll('#docs-tags .tag-item').forEach(tag => {
    if (tag.dataset.val) data['필요서류'].push(tag.dataset.val);
  });

  document.querySelectorAll('.faq-item').forEach(item => {
    const kwStr  = item.querySelector('.faq-keywords').value.trim();
    const answer = item.querySelector('.faq-answer').value.trim();
    if (answer) {
      data['faq'].push({
        keywords: kwStr ? kwStr.split(',').map(k => k.trim()).filter(Boolean) : [],
        answer,
      });
    }
  });

  return data;
}

// ── 저장 ──────────────────────────────────────────────────────────────────
async function saveType() {
  const data = collectFormData();
  faqData[currentType] = data;
  try {
    const res = await fetch(`${API}/admin/faq/${encodeURIComponent(currentType)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error();
    showToast('✅ 저장되었습니다.');
  } catch {
    showToast('❌ 저장 실패 — 서버를 확인하세요.', true);
  }
}

// ── 유형 추가 ─────────────────────────────────────────────────────────────
async function addNewType() {
  const name = prompt('새 민원 유형 이름을 입력하세요\n예: 복지상담, 건축허가, 세금납부');
  if (!name || !name.trim()) return;
  const trimmed = name.trim();
  if (faqData[trimmed]) { showToast('이미 존재하는 유형입니다.', true); return; }

  const newData = {
    '민원명': trimmed, '담당부서': '', '연락처': '', '처리기간': '',
    '필요서류': [], '안내': '', '응대기준': '', 'faq': [],
  };
  try {
    await fetch(`${API}/admin/faq/${encodeURIComponent(trimmed)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newData),
    });
    faqData[trimmed] = newData;
    renderSidebar();
    selectType(trimmed);
    showToast(`✅ "${trimmed}" 유형이 추가되었습니다.`);
  } catch {
    showToast('❌ 추가 실패', true);
  }
}

// ── 유형 삭제 ─────────────────────────────────────────────────────────────
async function deleteType() {
  if (!confirm(`"${currentType}" 유형을 삭제하시겠습니까?\n삭제된 정보는 복구되지 않습니다.`)) return;
  try {
    await fetch(`${API}/admin/faq/${encodeURIComponent(currentType)}`, { method: 'DELETE' });
    delete faqData[currentType];
    currentType = null;
    renderSidebar();
    const first = Object.keys(faqData)[0];
    if (first) selectType(first);
    else document.getElementById('edit-form').innerHTML = '<div class="empty-state">민원 유형이 없습니다. 유형을 추가해주세요.</div>';
    showToast('✅ 삭제되었습니다.');
  } catch {
    showToast('❌ 삭제 실패', true);
  }
}

// ── 토스트 ────────────────────────────────────────────────────────────────
function showToast(msg, isError = false) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show' + (isError ? ' error' : '');
  setTimeout(() => { t.className = 'toast'; }, 2800);
}

function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── 시작 ──────────────────────────────────────────────────────────────────
document.getElementById('add-type-btn').addEventListener('click', addNewType);
loadFaq();
