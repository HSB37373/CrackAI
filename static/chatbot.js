'use strict';

const API = window.location.pathname.replace(/\/[^/]*$/, '') || '.';
const SESSION_ID = 'chatbot_' + Date.now();

const TYPE_ICONS = {
  '불법주정차': '🚗', '주민등록': '📋', '여권': '✈️',
  '쓰레기': '🗑️', '소음': '🔊',
};
function icon(type) { return TYPE_ICONS[type] || '📌'; }

let faqData = {};
let currentType = null;

// ── 초기화 ─────────────────────────────────────────────────────────────────
async function init() {
  try {
    const res = await fetch(`${API}/faq`);
    faqData = await res.json();
  } catch {
    faqData = {};
  }
  renderTypeGrid();
  document.getElementById('back-btn').addEventListener('click', goBack);
  document.getElementById('chat-send').addEventListener('click', handleSend);
  document.getElementById('chat-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') handleSend();
  });
}

// ── 화면 1: 유형 선택 ──────────────────────────────────────────────────────
function renderTypeGrid() {
  const grid = document.getElementById('type-grid');
  grid.innerHTML = '';
  for (const [type, data] of Object.entries(faqData)) {
    const card = document.createElement('div');
    card.className = 'type-card';
    card.innerHTML = `
      <div class="type-card-icon">${icon(type)}</div>
      <div class="type-card-name">${esc(type)}</div>
      <div class="type-card-dept">${esc(data['담당부서'] || '')}</div>
    `;
    card.addEventListener('click', () => selectType(type));
    grid.appendChild(card);
  }
}

// ── 화면 2: 채팅 ───────────────────────────────────────────────────────────
function selectType(type) {
  currentType = type;
  const data = faqData[type];

  document.getElementById('chat-icon').textContent  = icon(type);
  document.getElementById('chat-title').textContent = type;
  document.getElementById('chat-dept').textContent  = data['담당부서'] || '';

  renderInfoCard(data);
  renderFaq(data['faq'] || []);
  document.getElementById('chat-messages').innerHTML = '';
  addAiMessage(`안녕하세요! ${type} 관련 민원을 안내해 드리겠습니다. 궁금하신 점을 자유롭게 질문해 주세요.`);

  showScreen('screen-chat');
  document.getElementById('chat-body').scrollTop = 0;
}

function renderInfoCard(data) {
  const rows = [
    ['담당 부서', data['담당부서']],
    ['연락처',   data['연락처']],
    ['처리 기간', data['처리기간']],
    ['필요 서류', (data['필요서류'] || []).join(', ')],
  ].filter(([, v]) => v);

  document.getElementById('info-card').innerHTML = `
    <div class="info-card-header">📌 기본 정보</div>
    ${rows.map(([k, v]) => `
      <div class="info-row">
        <span class="info-key">${esc(k)}</span>
        <span class="info-val">${esc(v)}</span>
      </div>`).join('')}
    ${data['안내'] ? `<div class="info-guide">${esc(data['안내'])}</div>` : ''}
  `;
}

function renderFaq(faqs) {
  const sec = document.getElementById('faq-section');
  if (!faqs.length) { sec.innerHTML = ''; return; }

  sec.innerHTML = `
    <div class="faq-header">❓ 자주 묻는 질문</div>
    ${faqs.map((item, i) => `
      <div class="faq-item" id="faq-${i}">
        <div class="faq-q" onclick="toggleFaq(${i})">
          <span>${esc(item.keywords?.join(' · ') || `FAQ ${i+1}`)}</span>
          <span class="faq-chevron">▼</span>
        </div>
        <div class="faq-a">${esc(item.answer || '')}</div>
      </div>`).join('')}
  `;
}

function toggleFaq(i) {
  const el = document.getElementById(`faq-${i}`);
  el.classList.toggle('open');
}

// ── 메시지 전송 ────────────────────────────────────────────────────────────
async function handleSend() {
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  input.disabled = true;
  document.getElementById('chat-send').disabled = true;

  addUserMessage(text);
  const typing = addTyping();

  let response;
  try {
    const res = await fetch(`${API}/respond`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        complaint_type: currentType,
        question: text,
        session_id: SESSION_ID,
        use_ai: false,
      }),
    });
    const data = await res.json();
    response = data.response;
  } catch {
    response = '죄송합니다. 일시적인 오류가 발생했습니다. 잠시 후 다시 시도하거나 담당 부서로 직접 문의해 주세요.';
  }

  typing.remove();
  addAiMessage(response);

  input.disabled = false;
  document.getElementById('chat-send').disabled = false;
  input.focus();
}

// ── 메시지 렌더링 ──────────────────────────────────────────────────────────
function addUserMessage(text) {
  const msgs = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = 'msg-row user';
  div.innerHTML = `<div class="msg-bubble">${esc(text)}</div>`;
  msgs.appendChild(div);
  scrollBottom();
}

function addAiMessage(text) {
  const msgs = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = 'msg-row ai';
  div.innerHTML = `
    <div class="msg-sender">🤖 AI 상담원</div>
    <div class="msg-bubble">${esc(text)}</div>
  `;
  msgs.appendChild(div);
  scrollBottom();
}

function addTyping() {
  const msgs = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = 'msg-row ai';
  div.innerHTML = `<div class="msg-bubble msg-typing">···</div>`;
  msgs.appendChild(div);
  scrollBottom();
  return div;
}

// ── 유틸 ───────────────────────────────────────────────────────────────────
function showScreen(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}

function goBack() {
  currentType = null;
  showScreen('screen-select');
}

function scrollBottom() {
  const body = document.getElementById('chat-body');
  setTimeout(() => { body.scrollTop = body.scrollHeight; }, 50);
}

function esc(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;')
    .replace(/\n/g,'<br>');
}

init();
