'use strict';

// 현재 페이지 경로 기준 상대 URL — JupyterHub 프록시 경로에서도 동작
const API = window.location.pathname.replace(/\/[^/]*$/, '') || '.';
const SESSION_ID = 'sess_' + Date.now();

// ── 데모 모드 ─────────────────────────────────────────────────────────────
// true  → 데모 시나리오 발화에 대해 GPT 분석 결과처럼 보이는 하드코딩 응답 사용
// false → 실제 /route API 호출 (OPENAI_API_KEY 있으면 GPT, 없으면 룰 기반)
const DEMO_MODE = true;

// 데모 발화 → 미리 작성된 GPT 스타일 분석 결과
const DEMO_ROUTES = {
  '제가 어제 동탄에서 주차위반 딱지를 받았는데 이거 이의신청을 어떻게 해야 하는지 모르겠어요.': {
    complaint_type: '불법주정차',
    sub_type:       '주차위반 과태료 이의신청',
    location:       '동탄',
    urgency:        '보통',
    department:     '교통행정과',
    summary:        '동탄 지역에서 주차위반 과태료 고지서를 수령한 시민이 이의신청 방법 및 필요 절차에 대한 안내를 요청하고 있음.',
    source:         'gpt',
  },
  '동탄 ○○동에 밤마다 불법주차가 너무 많아요. 특히 어린이집 앞이라 위험합니다.': {
    complaint_type: '불법주정차',
    sub_type:       '어린이보호구역 / 반복 불법주정차',
    location:       '동탄 ○○동',
    urgency:        '높음',
    department:     '교통행정과',
    summary:        '어린이집 인근 어린이보호구역에서 야간 불법주정차가 반복되어 보행 안전에 위험이 발생하고 있음. 신속한 현장 단속 및 계도 조치 필요.',
    source:         'gpt',
  },
};

// 데모 상담원 응답 — 민원인 발화 → 상담원이 할 법한 답변
const DEMO_AGENT_RESPONSES = {
  '서류는 뭐가 필요한가요?':
    '이의신청에 필요한 서류는 이의신청서, 차량등록증 사본, 그리고 증빙자료(현장 사진 등)입니다. 고지서 수령 후 60일 이내에 신청하셔야 하며, 교통행정과 방문 또는 정부24 온라인으로 접수하실 수 있습니다.',
  '이의신청 서류 제출 기한이 언제까지예요?':
    '이의신청 기간은 과태료 고지서를 받으신 날로부터 60일 이내입니다. 처리 기간은 접수 후 14일이며, 결과는 등기우편으로 통보해 드립니다.',
};

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

// 악성민원 이력 관련
let callerPhone = '';
let callerName = '';
let callerOffenseCount = 0;
let aiThreshold = 3;
let banTimerInterval = null;

// AI 라우팅 단계
let routingPhase = true;   // 첫 발화 전까지 true
let routingDone  = false;  // 라우팅 브리핑 표시 완료 여부

// TTS 재생 중 STT 피드백 루프 방지 플래그
let suppressSTT  = false;

// ── DOM 참조 ──────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

const micBtn       = $('mic-btn');
const micLabel     = $('mic-label');
const textInput    = $('text-input');
const sendBtn      = $('send-btn');
const agentInput   = $('agent-input');
const agentSendBtn = $('agent-send-btn');
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
  agentSendBtn.addEventListener('click', () => sendAgentText());
  agentInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendAgentText(); });
  summaryBtn.addEventListener('click', generateSummary);
  $('demo-btn').addEventListener('click', runDemo);
  $('register-caller-btn').addEventListener('click', registerCaller);
  $('caller-phone-input').addEventListener('keydown', e => { if (e.key === 'Enter') registerCaller(); });

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
    if (suppressSTT) return; // TTS 재생 중 피드백 루프 차단
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

// ── 민원인 조회 ───────────────────────────────────────────────────────────
async function registerCaller() {
  const name  = $('caller-name-input').value.trim();
  const phone = $('caller-phone-input').value.trim();
  if (!phone) return;

  const badge = $('penalty-badge');

  try {
    const res = await fetch(`${API}/caller/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: SESSION_ID, name, phone }),
    });
    const data = await res.json();

    callerName        = data.name;
    callerPhone       = data.phone;
    callerOffenseCount= data.offense_count;
    aiThreshold       = data.ai_threshold;

    badge.classList.remove('hidden', 'clean', 'warn1', 'warn2', 'ban');

    const count = data.offense_count;
    if (count === 0) {
      badge.className = 'penalty-badge clean';
      badge.textContent = '신규 민원인 · 경고 3회 허용';
    } else if (count === 1) {
      badge.className = 'penalty-badge warn1';
      badge.textContent = `⚠️ 악성민원 이력 ${count}회 · 경고 2회 허용`;
    } else if (count === 2) {
      badge.className = 'penalty-badge warn2';
      badge.textContent = `🔴 악성민원 이력 ${count}회 · 경고 1회 허용`;
    } else {
      badge.className = 'penalty-badge ban';
      badge.textContent = `🚨 악성민원 이력 ${count}회 이상 · 욕설 즉시 AI 전환`;
    }

    // 통화 제한 상태 표시
    if (data.ban_status && data.ban_status.is_banned) {
      startBanCountdown(data.ban_status.remaining_seconds);
    } else {
      clearBanStatus();
    }
  } catch {
    badge.className = 'penalty-badge warn1';
    badge.classList.remove('hidden');
    badge.textContent = '⚠️ 서버 조회 실패 — 기본 경고 3회 적용';
  }
}

function startBanCountdown(remainingSeconds) {
  clearInterval(banTimerInterval);
  const banEl  = $('ban-status');
  const timerEl = $('ban-timer');
  banEl.classList.remove('hidden', 'lifted');

  function tick() {
    if (remainingSeconds <= 0) {
      clearInterval(banTimerInterval);
      banEl.classList.add('lifted');
      $('ban-label').textContent = '✅ 통화 제한 해제됨';
      timerEl.textContent = '00:00:00';
      $('ban-sub').textContent = '상담원 통화 재개 가능';
      return;
    }
    const h = Math.floor(remainingSeconds / 3600);
    const m = Math.floor((remainingSeconds % 3600) / 60);
    const s = remainingSeconds % 60;
    timerEl.textContent =
      `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    remainingSeconds--;
  }
  tick();
  banTimerInterval = setInterval(tick, 1000);
}

function clearBanStatus() {
  clearInterval(banTimerInterval);
  $('ban-status').classList.add('hidden');
  $('ban-status').classList.remove('lifted');
  $('ban-label').textContent = '🚫 상담원 통화 제한 중';
  $('ban-sub').textContent = 'AI 챗봇 · 음성 상담만 가능';
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
  resetRoutingBrief();

  micBtn.classList.add('active');
  micLabel.textContent = '통화 종료';
  callIndicator.classList.add('active');
  setCallStatus('AI 민원 분석 중', 'normal');

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

function sendAgentText() {
  const txt = agentInput.value.trim();
  if (!txt) return;
  agentInput.value = '';
  if (!isCallActive) startCall();
  addChatMsg('agent', '🎧 상담사', txt, '');
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

  // 라우팅 단계: 민원 유형이 분류되면 브리핑 카드 표시 후 상담원 연결
  if (routingPhase && !routingDone && lastComplaintType !== '기타') {
    routingDone = true;
    await triggerRouting(text, lastComplaintType);
  }

  // AI 전환 여부 결정
  const justActivated = !aiModeActive && analysis.ai_activated;
  if (justActivated) {
    await activateAI(analysis.risk_score);
  } else if (!aiModeActive) {
    updateWarningCounter(analysis);
    if (analysis.warning_message && analysis.level !== 'normal') {
      const count = analysis.profanity_warning_count || 0;
      const prefix = count >= 3 ? '반복적인 ' : `욕설 경고 ${count}회. `;
      showWarning(prefix + analysis.warning_message, analysis.level);
    }
  }

  // AI 모드이면 AI 응답 생성 (전환된 바로 그 순간은 제외)
  if (!justActivated && (aiModeActive || analysis.ai_activated)) {
    await generateAIResponse(text, lastComplaintType);
  }

  // 모니터링 단계: 욕설·위협이 없는 발화에 상담원 응답
  if (!routingPhase && !aiModeActive && !justActivated &&
      !analysis.matched_bad_words?.length && !analysis.matched_threats?.length) {
    await generateAgentResponse(text, lastComplaintType);
  }
}

// ── AI 라우팅: 민원 분류 → 브리핑 카드 → 상담원 연결 ──────────────────────
async function triggerRouting(text, complaintType) {
  // 브리핑 카드 표시 (로딩 상태)
  const brief = $('routing-brief');
  brief.classList.remove('hidden');

  let routeData = {
    complaint_type: complaintType,
    sub_type: complaintType + ' 일반 문의',
    location: '',
    urgency: '보통',
    department: lastDept,
    summary: '민원 내용이 접수됨.',
    source: 'rule',
  };

  // 데모 모드: 미리 작성된 GPT 스타일 응답 사용
  if (DEMO_MODE && DEMO_ROUTES[text]) {
    await sleep(600); // GPT 호출처럼 잠깐 딜레이
    routeData = DEMO_ROUTES[text];
  } else {
    try {
      const res = await fetch(`${API}/route`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, session_id: SESSION_ID }),
      });
      routeData = await res.json();
    } catch {}
  }

  // 브리핑 카드 데이터 채우기
  $('brief-type').textContent = routeData.complaint_type || '-';
  $('brief-sub-type').textContent = routeData.sub_type || '-';
  $('brief-location').textContent = routeData.location || '화성시';
  $('brief-dept').textContent = routeData.department || '-';
  $('brief-summary').textContent = routeData.summary || '-';

  const urg = $('brief-urgency');
  const urgLevel = routeData.urgency || '보통';
  urg.textContent = urgLevel === '높음' ? '높음 ⚠️' : urgLevel === '중간' ? '중간' : '보통';
  urg.className = 'brief-val ' +
    (urgLevel === '높음' ? 'brief-urgency-high' : urgLevel === '중간' ? 'brief-urgency-mid' : 'brief-urgency-low');

  $('routing-badge').textContent = '분석 완료';
  $('routing-badge').classList.add('done');

  // GPT / 룰 기반 출처 배지
  const srcBadge = $('routing-source-badge');
  if (srcBadge) {
    const isGpt = routeData.source === 'gpt';
    srcBadge.textContent = isGpt ? 'GPT' : '규칙 기반';
    srcBadge.className = 'routing-source-badge ' + (isGpt ? 'src-gpt' : 'src-rule');
    srcBadge.classList.remove('hidden');
  }

  // TTS: 담당 부서 연결 안내
  const dept = routeData.department || '담당';
  const connMsg = `${dept} 상담원에게 연결해드리겠습니다. 잠시만 기다려 주세요.`;
  addChatMsg('ai', '🔔 AI 안내', connMsg, '');
  speak(connMsg);

  // 연결 중 애니메이션
  await sleep(400);
  $('routing-connecting').classList.remove('hidden');
  $('routing-dept-label').textContent = `${dept}에 연결 중...`;
  setCallStatus('연결 중...', 'normal');

  await sleep(2200);

  // 연결 완료
  $('routing-connecting').classList.add('hidden');
  $('routing-connected').classList.remove('hidden');
  setCallStatus('모니터링 중', 'active');
  addChatMsg('ai', '🔔 시스템', `✅ ${dept} 상담원에게 연결되었습니다. 통화 모니터링을 시작합니다.`, '');

  // 라우팅 단계 종료 → 악성 민원 모니터링 단계로 전환
  routingPhase = false;
}

// ── AI 전환 ──────────────────────────────────────────────────────────────
async function activateAI(score) {
  aiModeActive = true;

  const newCount = callerOffenseCount + 1;
  const banHours = newCount >= 3 ? 24 : newCount === 2 ? 3 : 1;

  const systemMsg = score >= 80
    ? `⚠️ 심각한 폭언이 감지되어 AI 음성 상담으로 즉시 전환합니다.\n\n🚫 이번 통화 종료 후 상담원 직접 통화가 ${banHours}시간 제한됩니다.\n반복 발생 시 1회→1시간 / 2회→3시간 / 3회 이상→24시간으로 늘어납니다.\n\n📞 상담원 연결이 필요하시면 제한 해제 후 화성시 콜센터(1577-4200 또는 031-370-3900, 평일 08:30~18:30)로 연락해 주시기 바랍니다.`
    : `⚠️ 폭언이 감지되어 AI 음성 상담으로 전환합니다.\n\n🚫 이번 통화 종료 후 상담원 직접 통화가 ${banHours}시간 제한됩니다.\n반복 발생 시 1회→1시간 / 2회→3시간 / 3회 이상→24시간으로 늘어납니다.\n\n📞 상담원 연결이 필요하시면 제한 해제 후 화성시 콜센터(1577-4200 또는 031-370-3900, 평일 08:30~18:30)로 연락해 주시기 바랍니다.`;

  const aiGreeting = '안녕하세요. AI 상담원입니다. 원하시는 민원 내용을 말씀해 주세요';

  showBadge('ai');
  setCallStatus('AI 상담 전환', 'ai');
  callIndicator.classList.remove('active');
  callIndicator.classList.add('ai-mode');
  updateSystemBadge('ai-dot', 'AI 상담 전환 중');

  const systemMsgShort = score >= 80
    ? `심각한 폭언이 감지되어 AI 음성 상담으로 전환합니다. 이번 통화 종료 후 상담원 직접 통화가 ${banHours}시간 제한됩니다.`
    : `폭언이 감지되어 AI 음성 상담으로 전환합니다. 이번 통화 종료 후 상담원 직접 통화가 ${banHours}시간 제한됩니다.`;
  addChatMsg('ai', '🔔 시스템 안내', systemMsg, '');
  speak(systemMsgShort);
  await sleep(3500);
  addChatMsg('ai', '🤖 AI 상담원', aiGreeting, '');
  speak(aiGreeting);

  $('db-ai-state').textContent = '🤖 AI 전환됨';
  $('db-ai-state').style.color = 'var(--ai)';
}

// ── 모니터링 단계 상담원 응답 ──────────────────────────────────────────────
async function generateAgentResponse(question, complaintType) {
  await sleep(800);

  let response;

  // 데모 모드: 발화별 하드코딩 응답 우선
  if (DEMO_MODE && DEMO_AGENT_RESPONSES[question]) {
    response = DEMO_AGENT_RESPONSES[question];
  } else {
    try {
      const res = await fetch(`${API}/respond`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          complaint_type: complaintType,
          question,
          session_id: SESSION_ID,
          use_ai: false,
        }),
      });
      const data = await res.json();
      response = data.response;
    } catch {
      response = null;
    }
  }

  if (response) {
    addChatMsg('agent', '🎧 상담원', response, '');
    speak(response);
  }
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
  suppressSTT = true;
  speechSynthesis.cancel();

  if (recognition && isCallActive) {
    try { recognition.stop(); } catch {}
  }

  const utt = new SpeechSynthesisUtterance(text);
  utt.lang  = 'ko-KR';
  utt.rate  = 0.92;
  utt.pitch = 1.05;

  const resume = () => {
    // TTS 종료 후 500ms 대기 후 STT 재개 (에코 유입 방지)
    setTimeout(() => {
      suppressSTT = false;
      if (isCallActive && recognition) {
        try { recognition.start(); } catch {}
      }
    }, 500);
  };
  utt.onend   = resume;
  utt.onerror = resume;

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

function updateWarningCounter(a) {
  const warnEl = $('db-warnings');
  if (!warnEl) return;
  const count  = a.profanity_warning_count || 0;
  const thresh = a.ai_threshold ?? aiThreshold;

  if (thresh === 0) {
    warnEl.textContent = '즉시 전환 적용 중';
    warnEl.style.color = 'var(--critical)';
  } else if (count === 0) {
    warnEl.textContent = `-`;
    warnEl.style.color = '';
  } else {
    const remaining = Math.max(0, thresh - count);
    warnEl.textContent = `${count}/${thresh}회 (${remaining}회 남음)`;
    warnEl.style.color = remaining === 0 ? 'var(--danger)' : remaining === 1 ? 'var(--caution)' : '';

    if (count > 0 && remaining > 0) {
      const warnMsg = `욕설 경고 ${count}/${thresh} — 경고 ${remaining}회 남았습니다. 다음 욕설 시 AI 상담으로 전환됩니다.`;
      addChatMsg('ai', '⚠️ 시스템', warnMsg, '');
      // speak는 showWarning에서 담당 (두 번 호출 시 덮어쓰기 방지)
    }
  }
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
    speak(msg); // caution, danger 모두 음성 안내
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
  // ① 라우팅 단계: 자연어 발화 → AI 분류 → 상담원 연결
  { delay: 0,    text: '제가 어제 동탄에서 주차위반 딱지를 받았는데 이거 이의신청을 어떻게 해야 하는지 모르겠어요.' },
  // ② 라우팅 완료 후 모니터링 단계 (약 4초 소요)
  { delay: 5500, text: '서류는 뭐가 필요한가요?' },
  { delay: 8500, text: '왜 이렇게 복잡해요? 담당자 바꿔요!' },
  { delay: 11500, text: '야, 이따위로 일할 거야? 당장 책임자 나오라고!' },
  { delay: 14500, text: '미치겠네 진짜, 가만 안 둬!' },
  { delay: 18000, text: '이의신청 서류 제출 기한이 언제까지예요?' },
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
  const warnEl = $('db-warnings');
  if (warnEl) { warnEl.textContent = '-'; warnEl.style.color = ''; }
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

function resetRoutingBrief() {
  routingPhase = true;
  routingDone  = false;
  const brief = $('routing-brief');
  if (!brief) return;
  brief.classList.add('hidden');
  $('routing-badge').textContent = '분석 중';
  $('routing-badge').classList.remove('done');
  const srcBadge = $('routing-source-badge');
  if (srcBadge) { srcBadge.textContent = ''; srcBadge.classList.add('hidden'); }
  ['brief-type','brief-sub-type','brief-location','brief-urgency','brief-dept','brief-summary']
    .forEach(id => { const el = $(id); if (el) el.textContent = '-'; });
  $('routing-connecting').classList.add('hidden');
  $('routing-connected').classList.add('hidden');
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
    쓰레기:     '쓰레기 무단투기는 화성시 콜센터(1577-4200) 또는 화성시청 환경위생과에 신고하실 수 있습니다.',
    소음:       '층간소음 민원은 층간소음이웃사이센터(1661-2642) 또는 구청 환경위생과에 접수하실 수 있습니다.',
    기타:       '문의하신 내용은 담당 부서로 안내드리겠습니다. 화성시 콜센터(1577-4200 또는 031-370-3900, 평일 08:30~18:30)로 문의해 주시기 바랍니다.',
  };
  return RESPONSES[type] || RESPONSES['기타'];
}

// 시작
init();
