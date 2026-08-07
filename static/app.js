'use strict';

// 현재 페이지 경로 기준 상대 URL — JupyterHub 프록시 경로에서도 동작
const API = window.location.pathname.replace(/\/[^/]*$/, '') || '.';
const SESSION_ID = 'sess_' + Date.now();

// ── 상태 ──────────────────────────────────────────────────────────────────
let isCallActive = false;
let aiModeActive = false;
let recognition = null;
let callTimer = null;
let callSeconds = 0;
let profanityTotal = 0;
let threatTotal = 0;
let turnTotal = 0;
let lastLevel = 'normal';
let lastComplaintType = '-';
let lastDept = '-';
let logEntries = [];

// ── DOM 참조 ──────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

const micBtn       = $('mic-btn');
const micLabel     = $('mic-label');
const textInput    = $('text-input');
const sendBtn      = $('send-btn');
const chatArea     = $('chat-area');
const callStatus   = $('call-status-text');
const callTimerEl  = $('call-timer');
const callIndicator= $('call-indicator');
const systemBadge  = $('system-badge');
const summaryBtn   = $('summary-btn');
const summaryReport= $('summary-report');

// ── 초기화 ────────────────────────────────────────────────────────────────
function init() {
  clearChatArea();

  micBtn.addEventListener('click', toggleCall);
  sendBtn.addEventListener('click', () => sendText());
  textInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendText(); });
  summaryBtn.addEventListener('click', generateSummary);
  $('demo-btn').addEventListener('click', runDemo);

  initSpeechRecognition();
}

function initSpeechRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    micBtn.title = '이 브라우저는 음성 인식을 지원하지 않습니다. 텍스트 입력을 사용하세요.';
    micBtn.style.opacity = '0.5';
    return;
  }
  recognition = new SR();
  recognition.lang = 'ko-KR';
  recognition.continuous = true;
  recognition.interimResults = true;

  recognition.onresult = evt => {
    let interim = '', final = '';
    for (let i = evt.resultIndex; i < evt.results.length; i++) {
      const t = evt.results[i][0].transcript;
      if (evt.results[i].isFinal) final += t;
      else interim += t;
    }
    if (interim) showInterim(interim);
    if (final.trim()) processUtterance(final.trim());
  };

  recognition.onerror = evt => {
    if (evt.error !== 'no-speech') console.warn('STT 오류:', evt.error);
  };

  recognition.onend = () => {
    if (isCallActive) {
      try { recognition.start(); } catch {}
    }
  };
}

// ── 통화 제어 ─────────────────────────────────────────────────────────────
function toggleCall() {
  if (isCallActive) stopCall();
  else startCall();
}

function startCall() {
  isCallActive = true;
  clearChatArea();
  resetStats();

  micBtn.classList.add('active');
  micLabel.textContent = '통화 종료';
  callIndicator.classList.add('active');
  setCallStatus('통화 중', 'active');

  callSeconds = 0;
  callTimer = setInterval(() => {
    callSeconds++;
    const m = String(Math.floor(callSeconds / 60)).padStart(2, '0');
    const s = String(callSeconds % 60).padStart(2, '0');
    callTimerEl.textContent = `${m}:${s}`;
  }, 1000);

  if (recognition) {
    try { recognition.start(); } catch {}
  }
}

function stopCall() {
  isCallActive = false;
  if (recognition) { try { recognition.stop(); } catch {} }
  clearInterval(callTimer);

  micBtn.classList.remove('active');
  micLabel.textContent = '통화 시작';
  callIndicator.classList.remove('active', 'ai-mode');
  setCallStatus('통화 종료', '');

  summaryBtn.disabled = false;
  speechSynthesis.cancel();
}

// ── 텍스트 입력 전송 ─────────────────────────────────────────────────────
function sendText() {
  const txt = textInput.value.trim();
  if (!txt) return;
  textInput.value = '';
  if (!isCallActive) startCall();
  processUtterance(txt);
}

// ── 핵심: 발화 처리 ──────────────────────────────────────────────────────
async function processUtterance(text) {
  removeInterim();
  addChatMsg('caller', '민원인', text, 'normal');

  let analysis;
  try {
    const res = await fetch(`${API}/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, session_id: SESSION_ID }),
    });
    analysis = await res.json();
  } catch (e) {
    // 백엔드 없으면 클라이언트 측 간이 분석
    analysis = clientSideAnalyze(text);
  }

  // 채팅 메시지 위험도 반영
  const lastMsg = chatArea.querySelector('.chat-msg.caller:last-child');
  if (lastMsg) lastMsg.classList.add(`risk-${analysis.level}`);

  updateAnalysisPanel(analysis);
  updateDashboard(analysis);
  addDetectedEntry(text, analysis);
  addLogEntry(text, analysis);

  lastComplaintType = analysis.complaint_type || '기타';
  lastDept = analysis.department || '-';

  // AI 전환 여부 결정
  if (!aiModeActive && analysis.risk_score >= 30) {
    await activateAI(analysis.risk_score);
  } else if (analysis.risk_score >= 30 && analysis.warning_message) {
    // 주의 단계 안내
    showWarning(analysis.warning_message, analysis.level);
  }

  // AI 모드이면 응답 생성
  if (aiModeActive || analysis.ai_activated) {
    await generateAIResponse(text, lastComplaintType);
  }
}

// ── AI 전환 ──────────────────────────────────────────────────────────────
async function activateAI(score) {
  aiModeActive = true;

  let msg;
  if (score >= 80) {
    msg = '심각한 폭언이 감지되었습니다. 담당자 보호를 위해 AI 음성 상담으로 즉시 전환합니다. 민원 내용은 계속 처리됩니다.';
  } else {
    msg = '폭언이 감지되었습니다. 담당자 보호를 위해 AI 음성 상담으로 전환합니다. 민원 내용은 계속 처리됩니다.';
  }

  showBadge('ai');
  setCallStatus('AI 상담 전환', 'ai');
  callIndicator.classList.remove('active');
  callIndicator.classList.add('ai-mode');
  updateSystemBadge('ai-dot', 'AI 상담 전환 중');

  addChatMsg('ai', '🤖 시스템', msg, '');
  speak(msg);

  $('db-ai-state').textContent = '🤖 AI 전환됨';
  $('db-ai-state').style.color = 'var(--ai)';
}

// ── AI 응답 생성 ──────────────────────────────────────────────────────────
async function generateAIResponse(question, complaintType) {
  // 잠깐 기다렸다가 응답 (자연스러움)
  await sleep(600);

  let response;
  try {
    const res = await fetch(`${API}/respond`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        complaint_type: complaintType,
        question,
        session_id: SESSION_ID,
        use_ai: !!window.__USE_AI_API__,
      }),
    });
    const data = await res.json();
    response = data.response;
  } catch {
    response = fallbackResponse(complaintType);
  }

  if (response) {
    addChatMsg('ai', '🤖 AI 상담원', response, '');
    speak(response);
  }
}

// ── 음성 출력 ─────────────────────────────────────────────────────────────
function speak(text) {
  if (!window.speechSynthesis) return;
  speechSynthesis.cancel();
  const utt = new SpeechSynthesisUtterance(text);
  utt.lang = 'ko-KR';
  utt.rate = 0.92;
  utt.pitch = 1.05;
  speechSynthesis.speak(utt);
}

// ── UI 업데이트 함수들 ────────────────────────────────────────────────────
function updateAnalysisPanel(a) {
  const score = a.risk_score || 0;
  const level = a.level || 'normal';
  lastLevel = level;

  // 게이지
  $('gauge-fill').style.width = score + '%';
  $('gauge-fill').style.background = levelColor(level);
  $('risk-score-num').textContent = score;
  $('risk-score-num').className = 'risk-score-num ' + level;

  // 레벨 배지
  const lb = $('level-badge');
  lb.className = 'level-badge ' + level;
  lb.textContent = levelLabel(level);

  // 세부 바
  setBar('profanity', a.profanity_score || 0);
  setBar('threat',    a.threat_score || 0);
  setBar('anger',     a.anger_score || 0);
  setBar('repetition',a.repetition_score || 0);

  // 카운터
  profanityTotal = a.profanity_total || profanityTotal;
  threatTotal    = a.threat_total    || threatTotal;
  turnTotal      = a.total_turns     || turnTotal;

  $('cnt-profanity').textContent = profanityTotal;
  $('cnt-threat').textContent    = threatTotal;
  $('cnt-turns').textContent     = turnTotal;
  $('cnt-repeat').textContent    = a.repeat_count || 0;

  // 상태 배지 (왼쪽 패널)
  showBadge(aiModeActive ? 'ai' : level);
}

function updateDashboard(a) {
  const score = a.risk_score || 0;
  const level = a.level || 'normal';

  const riskEl = $('db-risk');
  riskEl.textContent = `${score}점 · ${levelLabel(level)}`;
  riskEl.className = 'summary-val risk-val ' + level;

  $('db-toxic').textContent = `욕설 ${profanityTotal}회 / 위협 ${threatTotal}회`;

  const type = a.complaint_type || '-';
  const dept = a.department || '-';
  $('db-type').textContent   = type;
  $('db-dept').textContent   = dept;
  $('db-action').textContent = actionText(level, aiModeActive);

  if (type !== '기타' && type !== '-') {
    $('db-type').style.color = 'var(--ai)';
  }
}

function addDetectedEntry(text, a) {
  const list = $('detected-list');
  const empty = list.querySelector('.detected-empty');
  if (empty) empty.remove();

  const el = document.createElement('div');
  el.className = `detected-entry ${a.level}`;

  const shortText = text.length > 50 ? text.slice(0, 50) + '…' : text;
  const tags = [];
  if (a.matched_bad_words?.length)   tags.push('<span class="tag profanity">욕설</span>');
  if (a.matched_threats?.length)     tags.push('<span class="tag threat">위협</span>');
  if (a.anger_score > 30)            tags.push('<span class="tag anger">분노</span>');
  if (a.repeat_count > 0)            tags.push('<span class="tag repeat">반복</span>');
  tags.push(`<span class="tag score">${a.risk_score}점</span>`);

  el.innerHTML = `<div class="entry-text">${escHtml(shortText)}</div><div class="entry-tags">${tags.join('')}</div>`;
  list.insertBefore(el, list.firstChild);

  // 최대 6개
  while (list.children.length > 6) list.removeChild(list.lastChild);
}

function addLogEntry(text, a) {
  logEntries.push({ text, score: a.risk_score, level: a.level });
  const list = $('log-list');
  const empty = list.querySelector('.log-empty');
  if (empty) empty.remove();

  const el = document.createElement('div');
  el.className = 'log-entry';
  el.innerHTML = `<span class="log-score ${a.level}">${a.risk_score}</span><span class="log-text">${escHtml(text.slice(0, 60))}${text.length > 60 ? '…' : ''}</span>`;
  list.insertBefore(el, list.firstChild);
  while (list.children.length > 10) list.removeChild(list.lastChild);

  $('log-count').textContent = logEntries.length + '건';
}

function addChatMsg(type, sender, text, extra) {
  const empty = chatArea.querySelector('.chat-placeholder');
  if (empty) empty.remove();

  const el = document.createElement('div');
  el.className = `chat-msg ${type} ${extra}`;
  el.innerHTML = `<div class="msg-sender">${sender}</div><div>${escHtml(text)}</div>`;
  chatArea.appendChild(el);
  chatArea.scrollTop = chatArea.scrollHeight;
}

let interimEl = null;
function showInterim(text) {
  if (!interimEl) {
    interimEl = document.createElement('div');
    interimEl.className = 'chat-msg caller';
    interimEl.style.opacity = '0.45';
    chatArea.appendChild(interimEl);
  }
  interimEl.innerHTML = `<div class="msg-sender">민원인 (입력 중)</div><div>${escHtml(text)}</div>`;
  chatArea.scrollTop = chatArea.scrollHeight;
}
function removeInterim() {
  if (interimEl) { interimEl.remove(); interimEl = null; }
}

function showWarning(msg, level) {
  if (level === 'caution' || level === 'danger') {
    addChatMsg('ai', '⚠️ 시스템', msg, '');
    if (level === 'danger') speak(msg);
  }
}

// ── 요약 보고서 ───────────────────────────────────────────────────────────
async function generateSummary() {
  summaryBtn.disabled = true;
  summaryBtn.textContent = '생성 중...';

  let data;
  try {
    const res = await fetch(`${API}/summary/${SESSION_ID}`);
    data = await res.json();
  } catch {
    data = {
      main_complaint_type: lastComplaintType,
      department: lastDept,
      max_risk_score: lastLevel,
      profanity_total: profanityTotal,
      threat_total: threatTotal,
      ai_activated: aiModeActive,
      total_turns: turnTotal,
    };
  }

  const rows = [
    ['민원 종류', data.main_complaint_type || '-'],
    ['담당 부서', data.department || '-'],
    ['최고 위험도', `${data.max_risk_score || 0}점`],
    ['욕설 감지', `${data.profanity_total || 0}회`],
    ['위협 감지', `${data.threat_total || 0}회`],
    ['AI 전환', data.ai_activated ? '✅ 전환됨' : '❌ 전환 없음'],
    ['총 발화 수', `${data.total_turns || 0}회`],
  ];

  summaryReport.classList.remove('hidden');
  summaryReport.innerHTML = `
    <h3>📋 상담 요약 보고서</h3>
    ${rows.map(([k, v]) => `<div class="report-row"><span class="report-key">${k}</span><span class="report-val">${v}</span></div>`).join('')}
  `;

  summaryBtn.textContent = '📋 상담 요약 보고서 생성';
  summaryBtn.disabled = false;
}

// ── 데모 시나리오 ─────────────────────────────────────────────────────────
const DEMO_SCRIPT = [
  { delay: 0,    text: '여보세요, 주차 과태료 이의신청 하려고 하는데요.' },
  { delay: 3000, text: '어디로 신청해야 하나요?' },
  { delay: 6000, text: '담당자 바꿔요! 이게 뭐야 진짜.' },
  { delay: 9000, text: '야, 이따위로 일할 거야? 당장 담당자 나오라고!' },
  { delay: 12000, text: '미치겠네 진짜, 가만 안 둬!' },
  { delay: 15500, text: '과태료 취소하려면 서류가 뭐가 필요해요?' },
];

let demoRunning = false;
let demoTimeouts = [];

function runDemo() {
  if (demoRunning) {
    demoTimeouts.forEach(clearTimeout);
    demoTimeouts = [];
    demoRunning = false;
    $('demo-btn').textContent = '▶ 데모 실행';
    return;
  }

  demoRunning = true;
  $('demo-btn').textContent = '■ 데모 중지';
  if (!isCallActive) startCall();

  DEMO_SCRIPT.forEach(({ delay, text }) => {
    const tid = setTimeout(() => processUtterance(text), delay);
    demoTimeouts.push(tid);
  });

  const total = DEMO_SCRIPT[DEMO_SCRIPT.length - 1].delay + 5000;
  const tid = setTimeout(() => {
    demoRunning = false;
    $('demo-btn').textContent = '▶ 데모 실행';
  }, total);
  demoTimeouts.push(tid);
}

// ── 헬퍼 ─────────────────────────────────────────────────────────────────
function setBar(name, score) {
  const bar = $(`${name}-bar`);
  const pct = $(`${name}-pct`);
  if (bar) bar.style.width = score + '%';
  if (pct) pct.textContent = score + '%';
}

function setCallStatus(text, cls) {
  callStatus.textContent = text;
  callStatus.className = cls;
}

function showBadge(level) {
  ['normal', 'caution', 'danger', 'ai'].forEach(l => {
    const el = $(`badge-${l}`);
    if (el) el.classList.toggle('hidden', l !== level);
  });
}

function updateSystemBadge(dotClass, text) {
  const dot = systemBadge.querySelector('.dot');
  dot.className = `dot ${dotClass}`;
  $('system-status-text').textContent = text;
}

function clearChatArea() {
  chatArea.innerHTML = '<div class="chat-placeholder">통화를 시작하면 대화 내용이 여기에 표시됩니다.</div>';
}

function resetStats() {
  profanityTotal = 0; threatTotal = 0; turnTotal = 0; lastLevel = 'normal';
  aiModeActive = false; logEntries = [];
  ['cnt-profanity','cnt-threat','cnt-turns','cnt-repeat'].forEach(id => { $(id).textContent = '0'; });
  ['profanity','threat','anger','repetition'].forEach(n => { setBar(n, 0); });
  $('gauge-fill').style.width = '0%';
  $('risk-score-num').textContent = '0';
  $('risk-score-num').className = 'risk-score-num';
  $('level-badge').className = 'level-badge';
  $('level-badge').textContent = '정상';
  $('db-risk').textContent = '0점 · 정상';
  $('db-risk').className = 'summary-val risk-val normal';
  $('db-toxic').textContent = '0회';
  $('db-ai-state').textContent = '담당자 응대 중';
  $('db-ai-state').style.color = '';
  $('db-type').textContent = '-'; $('db-dept').textContent = '-'; $('db-action').textContent = '-';
  $('log-list').innerHTML = '<div class="log-empty">상담 기록이 없습니다.</div>';
  $('detected-list').innerHTML = '<div class="detected-empty">아직 분석된 내용이 없습니다.</div>';
  $('log-count').textContent = '0건';
  summaryReport.classList.add('hidden');
  summaryBtn.disabled = true;
  showBadge('normal');
  updateSystemBadge('normal-dot', '상담 중');
}

function levelColor(level) {
  return { normal: 'var(--normal)', caution: 'var(--caution)', danger: 'var(--danger)', critical: 'var(--critical)' }[level] || 'var(--normal)';
}
function levelLabel(level) {
  return { normal: '정상', caution: '주의', danger: '위험', critical: '심각' }[level] || '정상';
}
function actionText(level, aiOn) {
  if (aiOn) return 'AI 상담 유지';
  if (level === 'critical') return '즉시 AI 전환 권장';
  if (level === 'danger')   return 'AI 전환 고려';
  if (level === 'caution')  return '주의 요망';
  return '정상 상담 유지';
}
function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ── 클라이언트 측 간이 분석 (백엔드 없을 때 fallback) ────────────────────
const BAD = ['미친','병신','씨발','꺼져','닥쳐','죽어','이따위','개판'];
const THREAT = ['찾아가겠다','가만두지','죽이겠다','신상','고소할','가만 안 둬'];
const ANGER = ['당장','지금 당장','빨리','도대체','왜 이래','어떻게 된 거야'];

function clientSideAnalyze(text) {
  const profanity = BAD.filter(w => text.includes(w)).length;
  const threat    = THREAT.filter(w => text.includes(w)).length;
  const anger     = ANGER.filter(w => text.includes(w)).length;

  const ps = Math.min(100, profanity * 30);
  const ts = Math.min(100, threat * 35);
  const as = Math.min(100, anger * 20);
  const risk = Math.round(ps * 0.30 + ts * 0.35 + as * 0.20);

  const level = risk < 30 ? 'normal' : risk < 60 ? 'caution' : risk < 80 ? 'danger' : 'critical';

  // 단순 민원 분류
  let complaint_type = '기타';
  if (['주차','과태료','주정차'].some(w => text.includes(w))) complaint_type = '불법주정차';
  else if (['등본','초본','주민등록'].some(w => text.includes(w))) complaint_type = '주민등록';
  else if (['여권','passport'].some(w => text.includes(w))) complaint_type = '여권';
  else if (['쓰레기','투기'].some(w => text.includes(w))) complaint_type = '쓰레기';
  else if (['소음','층간'].some(w => text.includes(w))) complaint_type = '소음';

  const deptMap = { 불법주정차: '교통행정과', 주민등록: '민원여권과', 여권: '민원여권과', 쓰레기: '환경위생과', 소음: '환경위생과', 기타: '민원안내실' };

  return {
    risk_score: risk, profanity_score: ps, threat_score: ts, anger_score: as, repetition_score: 0,
    level, complaint_type, department: deptMap[complaint_type],
    matched_bad_words: BAD.filter(w => text.includes(w)),
    matched_threats: THREAT.filter(w => text.includes(w)),
    repeat_count: 0, total_turns: ++turnTotal,
    profanity_total: ps > 0 ? ++profanityTotal : profanityTotal,
    threat_total: ts > 0 ? ++threatTotal : threatTotal,
    ai_activated: aiModeActive,
    warning_message: level === 'caution' ? '원활한 상담을 위해 차분한 표현을 사용해 주시기 바랍니다.' :
                     level === 'danger'  ? '폭언이 지속될 경우 AI 상담으로 전환될 수 있습니다.' : null,
  };
}

function fallbackResponse(type) {
  const RESPONSES = {
    불법주정차: '불법주정차 과태료 이의신청은 고지서 수령일로부터 60일 이내에 교통행정과에 접수하실 수 있습니다. 이의신청서와 증빙자료가 필요합니다.',
    주민등록:   '주민등록등본은 정부24 홈페이지 또는 주민센터에서 발급받으실 수 있습니다. 온라인 발급 시 수수료는 무료입니다.',
    여권:       '여권 발급은 가까운 주민센터 민원여권과를 방문하시거나 온라인으로 신청하실 수 있습니다. 여권용 사진과 신분증이 필요합니다.',
    쓰레기:     '쓰레기 무단투기는 120 다산콜센터 또는 구청 환경위생과에 신고하실 수 있습니다.',
    소음:       '층간소음 민원은 층간소음이웃사이센터(1661-2642) 또는 구청 환경위생과에 접수하실 수 있습니다.',
    기타:       '문의하신 내용은 담당 부서로 안내드리겠습니다. 주민센터 방문 또는 120 다산콜센터로 문의해 주시기 바랍니다.',
  };
  return RESPONSES[type] || RESPONSES['기타'];
}

// 시작
init();
