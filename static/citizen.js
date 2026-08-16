'use strict';

const API = window.location.pathname.replace(/\/[^/]*$/, '') || '.';

// 구별 담당 부서 + 크롤링 기준 전화번호
const DISTRICT_INFO = {
  만세구: { dept: '경제교통과', phone: '031-5189-1223' },
  효행구: { dept: '안전건설과', phone: '031-5189-7555' },
  병점구: { dept: '안전건설과', phone: '031-5189-4791' },
  동탄구: { dept: '경제교통과', phone: '031-5189-6980' },
};

// 발화 키워드 → 구 매핑
const DISTRICT_KEYWORDS = {
  만세: '만세구', 만세구: '만세구',
  효행: '효행구', 효행구: '효행구',
  병점: '병점구', 병점구: '병점구',
  동탄: '동탄구', 동탄구: '동탄구',
  오산: '병점구',
};

// 흐름 단계
const PHASE = {
  IDLE: 'idle',
  GREETING: 'greeting',
  LISTEN_COMPLAINT: 'listen_complaint',
  ASK_DISTRICT: 'ask_district',
  LISTEN_DISTRICT: 'listen_district',
  DONE: 'done',
};

let phase = PHASE.IDLE;
let recognition = null;
let isCallActive = false;
let suppressSTT = false;
let ttsAborted = false;
let lastComplaintType = '';
let lastDept = '';
let lastDistrict = '';

const $ = id => document.getElementById(id);

function init() {
  $('call-btn').addEventListener('click', toggleCall);
  $('stop-tts-btn').addEventListener('click', () => {
    ttsAborted = true;
    speechSynthesis.cancel();
  });
  initSTT();
}

function initSTT() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return;
  recognition = new SR();
  recognition.lang = 'ko-KR';
  recognition.continuous = true;
  recognition.interimResults = true;

  recognition.onresult = evt => {
    if (suppressSTT) return;
    let interim = '', final = '';
    for (let i = evt.resultIndex; i < evt.results.length; i++) {
      if (evt.results[i].isFinal) final += evt.results[i][0].transcript;
      else interim += evt.results[i][0].transcript;
    }
    if (interim) showTranscript(interim, true);
    if (final.trim()) handleUtterance(final.trim());
  };

  recognition.onerror = evt => {
    if (evt.error !== 'no-speech') console.warn('STT 오류:', evt.error);
  };

  recognition.onend = () => {
    if (isCallActive && !suppressSTT) {
      try { recognition.start(); } catch {}
    }
  };
}

function toggleCall() {
  if (isCallActive) stopCall();
  else startCall();
}

function startCall() {
  isCallActive = true;
  phase = PHASE.GREETING;
  lastDistrict = '';
  lastComplaintType = '';
  lastDept = '';

  $('call-btn').classList.add('active');
  $('call-btn-label').textContent = '통화 종료';
  $('result-card').classList.add('hidden');
  clearTranscript();

  if (recognition) { try { recognition.start(); } catch {} }

  setStatus('📞', 'AI 상담 연결 중...', '');
  $('wave-container').classList.add('active');

  runGreeting();
}

function stopCall() {
  isCallActive = false;
  phase = PHASE.IDLE;
  ttsAborted = true;
  speechSynthesis.cancel();
  if (recognition) { try { recognition.stop(); } catch {} }

  $('call-btn').classList.remove('active');
  $('call-btn-label').textContent = '통화 시작';
  $('wave-container').classList.remove('active');
  $('stop-tts-btn').classList.add('hidden');
  setStatus('📞', '통화를 시작하려면 버튼을 눌러주세요', '');
}

async function runGreeting() {
  const greeting = '안녕하세요. 화성시 민원 AI 자동연결 서비스입니다. 불편하신 사항을 말씀해 주시면 담당 부서로 바로 안내해 드리겠습니다.';
  setStatus('🤖', 'AI 안내 중', '');
  await speak(greeting);

  if (!isCallActive) return;
  phase = PHASE.LISTEN_COMPLAINT;
  setStatus('🎤', '민원 내용을 말씀해 주세요', '');
}

async function handleUtterance(text) {
  showTranscript(text, false);

  if (phase === PHASE.LISTEN_COMPLAINT) {
    await classifyComplaint(text);
  } else if (phase === PHASE.LISTEN_DISTRICT) {
    // 지역 변경 버그 수정: 매 발화마다 구를 새로 감지
    const district = detectDistrict(text);
    if (district) {
      await handleDistrictConfirmed(text, district);
    } else {
      // 지역 매칭 실패
      const failMsg = `${text} 지역 담당 부서인 ${lastDept}로 연결해 드리겠습니다. 불편하신 점 양해 부탁드립니다.`;
      setStatus('📋', '안내 중', '');
      await speak(failMsg);
      if (!isCallActive) return;
      showResult(lastComplaintType, text, lastDept, '031-370-3900');
      await wrapUp();
    }
  }
}

async function classifyComplaint(text) {
  setStatus('🔍', '민원 분류 중...', '');

  let complaintType = '기타';
  let dept = '민원안내실';

  try {
    const res = await fetch(`${API}/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, session_id: 'citizen_' + Date.now() }),
    });
    const data = await res.json();
    complaintType = data.complaint_type || '기타';
    dept = data.department || '민원안내실';
  } catch {
    complaintType = clientClassify(text);
    dept = DEPT_MAP[complaintType] || '민원안내실';
  }

  lastComplaintType = complaintType;
  lastDept = dept;

  // 민원 분류 안내
  const classifyMsg = `${complaintType} 관련 민원으로 접수되었습니다. 민원 처리가 필요하신 지역을 말씀해 주세요. 만세구, 효행구, 병점구, 동탄구 중에서 말씀해 주시면 담당 부서로 바로 안내해 드립니다.`;
  setStatus('📍', '지역 확인 중', complaintType + ' 민원 접수됨');
  phase = PHASE.LISTEN_DISTRICT;
  await speak(classifyMsg);
}

function detectDistrict(text) {
  for (const [kw, dist] of Object.entries(DISTRICT_KEYWORDS)) {
    if (text.includes(kw)) return dist;
  }
  return null;
}

async function handleDistrictConfirmed(text, district) {
  lastDistrict = district;
  const info = DISTRICT_INFO[district];
  if (!info) return;

  const deptMsg = `${district} 담당 부서인 ${info.dept}로 안내해 드리겠습니다. 직통 전화번호는 ${info.phone.split('').join(' ')} 입니다. 방문 또는 전화로 접수하실 수 있습니다.`;
  setStatus('✅', '안내 완료', `${district} · ${info.dept}`);
  await speak(deptMsg);

  if (!isCallActive) return;
  showResult(lastComplaintType, district, info.dept, info.phone);
  await wrapUp();
}

async function wrapUp() {
  if (!isCallActive) return;
  phase = PHASE.DONE;
  const closingMsg = '더 궁금하신 사항은 화성시 콜센터 1577-4200으로 문의해 주시기 바랍니다. 이용해 주셔서 감사합니다.';
  await speak(closingMsg);
}

function showResult(type, location, dept, phone) {
  $('res-type').textContent = type || '-';
  $('res-location').textContent = location || '-';
  $('res-dept').textContent = dept || '-';
  $('res-phone').textContent = phone || '-';
  $('result-card').classList.remove('hidden');
}

// ── TTS ──────────────────────────────────────────────────────────────────────
function speak(text) {
  return new Promise(resolve => {
    if (!window.speechSynthesis) { resolve(); return; }
    ttsAborted = false;
    suppressSTT = true;
    speechSynthesis.cancel();
    $('stop-tts-btn').classList.remove('hidden');

    const sentences = text.match(/[^。.!?！？\n]+[。.!?！？\n]?/g) || [text];
    let idx = 0;

    const speakNext = () => {
      if (ttsAborted) {
        suppressSTT = false;
        $('stop-tts-btn').classList.add('hidden');
        resolve();
        return;
      }
      if (idx >= sentences.length) {
        setTimeout(() => {
          suppressSTT = false;
          $('stop-tts-btn').classList.add('hidden');
          if (isCallActive && recognition) {
            try { recognition.start(); } catch {}
          }
          resolve();
        }, 500);
        return;
      }
      const utt = new SpeechSynthesisUtterance(sentences[idx++]);
      utt.lang = 'ko-KR';
      utt.rate = 0.92;
      utt.pitch = 1.05;
      utt.onend = speakNext;
      utt.onerror = speakNext;
      speechSynthesis.speak(utt);
    };

    setTimeout(speakNext, 150);
  });
}

// ── UI 헬퍼 ──────────────────────────────────────────────────────────────────
function setStatus(icon, text, sub) {
  $('status-icon').textContent = icon;
  $('status-text').textContent = text;
  $('status-sub').textContent = sub || '';
}

function showTranscript(text, isInterim) {
  const box = $('transcript-box');
  box.innerHTML = `<span style="opacity:${isInterim ? 0.5 : 1}">${escHtml(text)}</span>`;
}

function clearTranscript() {
  $('transcript-box').innerHTML = '<div class="transcript-placeholder">말씀하신 내용이 여기에 표시됩니다.</div>';
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── 클라이언트 측 간이 분류 (fallback) ─────────────────────────────────────
const DEPT_MAP = {
  불법주정차: '교통행정과', 주민등록: '민원여권과',
  여권: '민원여권과', 쓰레기: '환경위생과',
  소음: '환경위생과', 기타: '민원안내실',
};

function clientClassify(text) {
  if (['주차','과태료','주정차'].some(w => text.includes(w))) return '불법주정차';
  if (['등본','초본','주민등록'].some(w => text.includes(w))) return '주민등록';
  if (['여권'].some(w => text.includes(w))) return '여권';
  if (['쓰레기','투기'].some(w => text.includes(w))) return '쓰레기';
  if (['소음','층간'].some(w => text.includes(w))) return '소음';
  return '기타';
}

init();
