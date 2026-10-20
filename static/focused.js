// Browser signals are review indicators. The server owns warning counts, deadlines and submission locks.
const baseRenderAssessment = renderAssessment;
const baseRenderCoding = renderCoding;
const baseLoadCode = loadCode;
const baseShowReport = showReport;
const baseSettingsPage = settingsPage;
const baseRender = render;
const baseCandidateOverview = candidateOverview;
const baseNavigate = navigate;
const baseLogout = logout;
let focusedRound = null;
let focusedSession = null;
let focusSave = Promise.resolve();
let focusEvents = Promise.resolve();
let codeSaveTimer = null;
let hasUnsavedWork = false;
let focusWarningShown = 0;
let assessmentDialogOpen = false;
let timeoutSubmitting = false;
let ignoreFocusUntil = 0;
let pauseSyncPending = false;
let resumeSync = null;
const localDraftKey = (name, extra = '') => `inetz-draft:${me?.id}:${name}:${extra}`;

const focusStyle = document.createElement('style');
focusStyle.textContent = `body.focused .sidebar, body.focused .topbar { display:none!important }
body.focused .layout { display:block } body.focused .content { max-width:1250px; padding:18px }
body.focused .main { min-height:100vh } body.focused .protected-content { user-select:none; -webkit-user-select:none }
.focus-banner { background:#102943; color:white; padding:12px 16px; border-radius:9px; display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:14px }
.focus-banner small { color:#cfdded } .focus-warning { background:#fff4e3; color:#8a5204; padding:12px 14px; border-radius:8px; margin-bottom:14px }
@media(max-width:650px){body.focused .content{padding:10px}}`;
document.head.append(focusStyle);

function focusedPayload(kind) {
  const body = {kind, event_key: crypto.randomUUID()};
  if (focusedRound === 'coding') {
    const editor = document.querySelector('#sourceCode');
    if (editor && !editor.disabled) {
      body.question_id = Number(editor.dataset.question || codeQ);
      body.language = editor.dataset.language || codeLang;
      body.source = editor.value;
    }
  } else if (assessment) body.answers = {...assessment.answers};
  return body;
}

async function reportFocus(kind) {
  if (!focusedRound || !focusedSession || focusedSession.finished) return;
  const roundAtEvent = focusedRound;
  const payload = focusedPayload(kind);
  focusEvents = focusEvents.catch(() => {}).then(async () => {
    await focusSave.catch(() => {});
    const result = await api(`/candidate/assessment/${roundAtEvent}/monitor`, {method:'POST', body:JSON.stringify(payload), keepalive:true});
    focusedSession = result;
    hasUnsavedWork = false;
    if (result.auto_submitted || result.finished) {
      stopFocusedMode();
      assessment = null;
      notify(result.submitted_reason || 'Assessment submitted.');
      view = 'home';
      await render();
      return false;
    }
    updateFocusBanner();
    if (kind === 'returned' && result.warning_count > focusWarningShown) {
      focusWarningShown = result.warning_count;
      showFocusWarning(`Assessment warning ${result.warning_count} of 3. Answers are paused until fullscreen is restored. Your saved work is preserved.`);
    }
    return true;
  }).catch(error => { notify(`Monitoring could not sync: ${error.message}. Your saved work is preserved.`); return false; });
  return focusEvents;
}

function resumeFocusedAssessment() {
  if (!focusedRound || resumeSync) return resumeSync;
  if (!document.fullscreenElement || !document.hasFocus() || document.hidden) {
    setAssessmentControlsLocked(true);
    updateFocusBanner();
    return null;
  }
  pauseSyncPending = true;
  setAssessmentControlsLocked(true);
  updateFocusBanner();
  resumeSync = reportFocus('returned').then(ok => {
    if (ok) pauseSyncPending = false;
    resumeSync = null;
    setAssessmentControlsLocked(isAssessmentInputLocked());
    updateFocusBanner();
    return ok;
  });
  return resumeSync;
}

function showFocusWarning(message) {
  let node = document.querySelector('#focusWarning');
  if (!node) {
    node = document.createElement('div'); node.id = 'focusWarning'; node.className = 'focus-warning';
    document.querySelector('#content')?.prepend(node);
  }
  node.textContent = message;
}

function updateFocusBanner() {
  if (!focusedRound || !focusedSession) return;
  let banner = document.querySelector('#focusBanner');
  if (!banner) {
    banner = document.createElement('div'); banner.id = 'focusBanner'; banner.className = 'focus-banner';
    document.querySelector('#content')?.prepend(banner);
  }
  const remainingSeconds = Math.max(0, Math.ceil((new Date(focusedSession.deadline_at).getTime() - Date.now()) / 1000));
  const remaining = `${String(Math.floor(remainingSeconds / 60)).padStart(2, '0')}:${String(remainingSeconds % 60).padStart(2, '0')}`;
  const locked = isAssessmentInputLocked();
  banner.innerHTML = `<div><strong>Focused assessment Â· ${esc(focusedRound === 'coding' ? 'Coding' : focusedRound === 'technical' ? 'Technical MCQ' : 'Aptitude MCQ')}</strong><br><small>${locked ? 'Timer paused' : `${remaining} remaining`} Â· ${focusedSession.warning_count} warning${focusedSession.warning_count === 1 ? '' : 's'} of 3</small>${locked ? '<br><small>Answers are paused. Return to the assessment in fullscreen to continue.</small>' : ''}</div><div class="row"><span class="badge blue">Drafts save to database</span>${locked ? '<button class="btn secondary small" id="returnFullscreen">Re-enter fullscreen</button>' : ''}</div>`;
  document.querySelector('#returnFullscreen')?.addEventListener('click', async () => {
    try { await document.documentElement.requestFullscreen(); updateFocusBanner(); }
    catch { showFocusWarning('Fullscreen is required to continue. Allow fullscreen in your browser, then try again.'); }
  });
  setAssessmentControlsLocked(locked);
}

function isAssessmentInputLocked() {
  return !!focusedRound && (pauseSyncPending || !document.fullscreenElement || !document.hasFocus() || document.hidden);
}

function setAssessmentControlsLocked(locked) {
  if (focusedRound === 'coding') {
    const submitted = ['Awaiting review', 'Completed'].includes(codeData?.status);
    document.querySelectorAll('#sourceCode, #analyticsSource, #codeInner button, #codeInner select').forEach(control => { control.disabled = locked || submitted; });
  } else if (focusedRound) {
    const submitted = !!assessment?.submitted_at;
    document.querySelectorAll('#content .assessment-layout input, #content .assessment-layout button').forEach(control => { control.disabled = locked || submitted; });
  }
}

function startFocusedMode(roundName, session) {
  focusedRound = roundName; focusedSession = session; focusWarningShown = session.warning_count;
  document.body.classList.add('focused');
  updateFocusBanner();
}

function stopFocusedMode() {
  if (typeof stopPython === 'function') stopPython();
  focusedRound = null; focusedSession = null; hasUnsavedWork = false;
  pauseSyncPending = false; resumeSync = null;
  document.body.classList.remove('focused');
  clearTimeout(codeSaveTimer);
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
}

function rulesScreen(roundName, resumed = false) {
  stopFocusedMode();
  if (resumed) document.body.classList.add('focused');
  const label = roundName === 'coding' ? 'Coding assessment' : roundName === 'technical' ? 'Technical MCQ' : 'Aptitude MCQ';
  document.querySelector('#content').innerHTML = `<div class="page-head"><div><h1>${label}</h1><p>Read the rules before entering the assessment.</p></div></div>
  <div class="card" style="max-width:760px"><div class="card-head"><h3>${resumed ? 'Resume your assessment' : 'Assessment rules'}</h3></div>
  <div class="protected-content" style="line-height:1.8"><p>Enter fullscreen to start. The assessment page records when it becomes hidden, loses focus, or exits fullscreen. While away from fullscreen, answers are locked and the timer pauses. Return to fullscreen to continue. Related browser signals count as one warning. On the third warning, this test ends automatically and your saved answers are submitted.</p>
  <p>Pasting and drag-and-drop text insertion are disabled in answer controls and the coding editor. Drafts save to the database. You may continue through every round regardless of your score.</p>
  <p>Browser signals are indicators for HR review, not proof of misconduct. Browser monitoring cannot prevent another tab, application or device, nor can question copy restrictions prevent screenshots or browser-tool extraction.</p></div>
  <label style="display:flex;gap:10px;align-items:center;margin:18px 0"><input id="rulesAck" type="checkbox"> I understand the rules and want to ${resumed ? 'resume' : 'start'}.</label>
  <div class="row"><button class="btn primary" id="beginFocused">${resumed ? 'Re-enter fullscreen and resume' : 'Enter fullscreen and start'}</button>${resumed ? '<button class="btn secondary" onclick="backToCandidateOverview()">Back to my overview</button>' : '<button class="btn secondary" onclick="navigate(\'home\')">Back</button>'}</div><div id="focusStartError"></div></div>`;
  document.querySelector('#beginFocused').onclick = () => beginFocused(roundName);
}

function backToCandidateOverview() {
  stopFocusedMode();
  view = 'home';
  render();
}

async function beginFocused(roundName) {
  if (!document.querySelector('#rulesAck')?.checked) {
    document.querySelector('#focusStartError').innerHTML = errBox('Acknowledge the rules before starting.'); return;
  }
  try {
    if (!document.documentElement.requestFullscreen) throw Error('This browser does not support fullscreen assessment mode.');
    await document.documentElement.requestFullscreen();
    const session = await api(`/candidate/assessment/${roundName}/start`, {method:'POST', body:JSON.stringify({acknowledged:true})});
    pauseSyncPending = true;
    startFocusedMode(roundName, session);
    await resumeFocusedAssessment();
    if (!focusedRound) return;
    if (roundName === 'coding') await renderCoding();
    else {
      assessment = await api(`/candidate/assessment/${roundName}`);
      try {
        const cached = JSON.parse(localStorage.getItem(localDraftKey(roundName)) || 'null');
        if (cached && typeof cached === 'object') {
          assessment.answers = {...assessment.answers, ...cached};
          focusSave = api(`/candidate/assessment/${roundName}`, {method:'PUT', body:JSON.stringify({answers:assessment.answers})});
          await focusSave;
          localStorage.removeItem(localDraftKey(roundName));
        }
      } catch (error) { showFocusWarning(`A local draft is available, but could not sync: ${error.message}`); }
      await renderAssessment();
    }
  } catch (error) {
    document.querySelector('#focusStartError').innerHTML = errBox(error.message);
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }
}

startAssessment = async function(roundName) {
  round = roundName; view = 'assessment'; selectedQ = 0;
  try {
    assessment = await api(`/candidate/assessment/${roundName}`);
    if (assessment.submitted_at) { await renderAssessment(); return; }
    try {
      const cached = JSON.parse(localStorage.getItem(localDraftKey(roundName)) || 'null');
      if (cached && typeof cached === 'object') assessment.answers = {...assessment.answers, ...cached};
    } catch {}
    if (assessment.session.started) { focusedSession = assessment.session; rulesScreen(roundName, true); }
    else rulesScreen(roundName);
  } catch (error) { notify(error.message); view = 'home'; await render(); }
};

render = async function() {
  await baseRender();
  if (me?.role !== 'candidate' || !homeData) return;
  const stage = homeData.active_stage;
  if (view !== 'home') return;
  if (stage === 'aptitude' || stage === 'technical') {
    const session = homeData.assessment_sessions?.[stage];
    if (session?.started && !session.finished) { focusedSession = session; round = stage; assessment = null; }
  } else if (stage === 'coding') {
    const session = homeData.coding_session;
    if (session?.started && !session.finished) focusedSession = session;
  }
};
candidateOverview = function() { return baseCandidateOverview(); };

renderAssessment = async function() {
  if (!assessment) assessment = await api(`/candidate/assessment/${round}`);
  if (!assessment.submitted_at && !focusedRound) {
    if (assessment.session?.started) focusedSession = assessment.session;
    rulesScreen(round, !!assessment.session?.started); return;
  }
  if (assessment.submitted_at) stopFocusedMode();
  await baseRenderAssessment();
  if (focusedRound) updateFocusBanner();
  document.querySelectorAll('.question-title, .option span').forEach(node => node.classList.add('protected-content'));
};

setAnswer = async function(index, value) {
  if (!focusedRound || !assessment || assessment.submitted_at) return;
  assessment.answers[String(index + 1)] = value;
  hasUnsavedWork = true;
  localStorage.setItem(localDraftKey(round), JSON.stringify(assessment.answers));
  const snapshot = {...assessment.answers};
  await renderAssessment();
  focusSave = focusSave.catch(() => {}).then(() => api(`/candidate/assessment/${round}`, {method:'PUT', body:JSON.stringify({answers:snapshot})}));
  try { await focusSave; if (JSON.stringify(snapshot) === JSON.stringify(assessment.answers)) { hasUnsavedWork = false; localStorage.removeItem(localDraftKey(round)); } }
  catch (error) { showFocusWarning(`Draft save failed: ${error.message}. Retry by selecting an answer again or submit when connected.`); }
};

confirmSubmit = async function() {
  if (!focusedRound || !assessment) return;
  assessmentDialogOpen = true;
  const accepted = confirm(`Submit this assessment? ${15 - Object.keys(assessment.answers || {}).length} questions are unanswered. You cannot change answers after submission.`);
  assessmentDialogOpen = false;
  ignoreFocusUntil = Date.now() + 600;
  if (!accepted) return;
  try {
    await focusSave.catch(() => {});
    await api(`/candidate/assessment/${round}/monitor`, {method:'POST', body:JSON.stringify(focusedPayload('returned'))});
    const result = await api(`/candidate/assessment/${round}/submit`, {method:'POST'});
    stopFocusedMode();
    localStorage.removeItem(localDraftKey(round));
    assessment = await api(`/candidate/assessment/${round}`);
    notify(`Submitted Â· ${result.score}/15`);
    await renderAssessment();
  } catch (error) { showFocusWarning(`Submission could not complete: ${error.message}. Your last saved answers remain available.`); }
};

async function submitTimedOutAssessment() {
  if (!focusedRound || !assessment || assessment.submitted_at || timeoutSubmitting) return;
  timeoutSubmitting = true;
  try {
    await focusSave.catch(() => {});
    if (hasUnsavedWork) {
      await api(`/candidate/assessment/${round}`, {method:'PUT', body:JSON.stringify({answers:{...assessment.answers}})});
      hasUnsavedWork = false;
      localStorage.removeItem(localDraftKey(round));
    }
    const result = await api(`/candidate/assessment/${round}/submit`, {method:'POST'});
    assessment = await api(`/candidate/assessment/${round}`);
    stopFocusedMode();
    notify(`Time is up. Submitted ${Object.keys(assessment.answers || {}).length}/15 answered · score ${result.score}/15.`);
    await renderAssessment();
  } catch (error) { timeoutSubmitting = false; showFocusWarning(`Time is up. Finalizing your saved answers: ${error.message}`); }
}

renderCoding = async function() {
  const session = homeData?.coding_session;
  const codingStage = homeData?.active_stage === 'coding';
  if (!codingStage && !focusedRound) { await baseRenderCoding(); return; }
  if (!focusedRound && session && !session.finished) {
    focusedSession = session; rulesScreen('coding', !!session.started); return;
  }
  if (!focusedRound && !session?.started) { rulesScreen('coding'); return; }
  if (session?.finished && !focusedRound) { view = 'home'; await render(); return; }
  await baseRenderCoding();
  updateFocusBanner();
};

loadCode = async function() {
  await flushCodeDraft();
  await baseLoadCode();
  const editor = document.querySelector('#sourceCode');
  if (editor) {
    editor.dataset.question = String(codeQ); editor.dataset.language = codeLang;
    if (!codeData.status || codeData.status === 'Not submitted') {
      const cached = localStorage.getItem(localDraftKey('coding', `${codeQ}:${codeLang}`));
      if (cached !== null) { editor.value = cached; hasUnsavedWork = true; queueCodeDraft(codeQ, codeLang, cached).catch(() => {}); }
    }
    editor.addEventListener('input', () => {
      hasUnsavedWork = true; clearTimeout(codeSaveTimer);
      const qid = Number(editor.dataset.question), language = editor.dataset.language;
      localStorage.setItem(localDraftKey('coding', `${qid}:${language}`), editor.value);
      codeSaveTimer = setTimeout(() => queueCodeDraft(qid, language, editor.value).catch(() => {}), 650);
    });
    if (['Awaiting review','Completed'].includes(codeData.status)) {
      editor.disabled = true;
      document.querySelectorAll('#codeInner button').forEach(button => button.disabled = true);
    }
  }
  document.querySelectorAll('.code-layout > .card:first-child h3, .code-layout > .card:first-child p, .code-layout > .card:first-child .detail-item, .code-layout > .card:first-child .result-box').forEach(node => node.classList.add('protected-content'));
};

function queueCodeDraft(questionId, language, source) {
  if (!focusedRound) return Promise.resolve();
  focusSave = focusSave.catch(() => {}).then(() => api('/candidate/code', {method:'PUT', body:JSON.stringify({question_id:questionId, language, source})}));
  return focusSave.then(() => {
    const key = localDraftKey('coding', `${questionId}:${language}`);
    if (localStorage.getItem(key) === source) localStorage.removeItem(key);
    hasUnsavedWork = false;
  }).catch(error => { showFocusWarning(`Draft save failed: ${error.message}. Keep this page open and retry saving.`); throw error; });
}

async function flushCodeDraft() {
  clearTimeout(codeSaveTimer);
  const editor = document.querySelector('#sourceCode');
  if (editor && hasUnsavedWork && !editor.disabled && focusedRound === 'coding') {
    await queueCodeDraft(Number(editor.dataset.question), editor.dataset.language, editor.value);
  }
}

saveCode = async function(submit) {
  const editor = document.querySelector('#sourceCode');
  if (!editor || editor.disabled || !focusedRound) return;
  try {
    clearTimeout(codeSaveTimer);
    await queueCodeDraft(Number(editor.dataset.question), editor.dataset.language, editor.value);
    if (submit) {
      assessmentDialogOpen = true;
      const accepted = confirm('Submit this solution for Admin review? You cannot edit it after submission.');
      assessmentDialogOpen = false;
      ignoreFocusUntil = Date.now() + 600;
      if (!accepted) return;
      await api(`/candidate/code/${codeQ}/submit`, {method:'POST'});
      notify('Solution submitted for Admin review.');
      homeData = await api('/candidate/home');
      if (homeData.coding_session.finished) { stopFocusedMode(); view = 'home'; await render(); return; }
    } else notify('Draft saved');
    await loadCode();
  } catch (error) { showFocusWarning(`Could not save or submit: ${error.message}`); }
};

navigate = function(target) {
  if (focusedRound) { showFocusWarning('Finish this assessment before leaving the focused assessment screen.'); return; }
  return baseNavigate(target);
};
logout = async function() {
  if (focusedRound) { showFocusWarning('Your assessment is active. Finish the round before signing out.'); return; }
  return baseLogout();
};

settingsPage = async function() {
  const config = await api('/super-admin/config');
  let html = await baseSettingsPage();
  html = html.replace('<form id="configForm" class="row">', '<form id="configForm" class="row" onsubmit="saveAssessmentConfig(event)">');
  const fields = `<div class="field"><label>Focus warning reference count</label><input type="number" name="violation_limit" min="0" max="20" value="${config.violation_limit}" required></div><div class="field"><label>Assessment duration Â· minutes</label><input type="number" name="assessment_minutes" min="5" max="240" value="${config.assessment_minutes}" required></div>`;
  return html.replace('<button class="btn primary">Save benchmarks</button>', fields + '<button class="btn primary">Save assessment settings</button>')
    .replace('Benchmarks inform review only. Low scores never stop progression.', 'Benchmarks inform review only. Focus warnings are recorded for staff review and never submit an assessment.');
};

async function saveAssessmentConfig(event) {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  try {
    await api('/super-admin/config', {method:'PUT', body:JSON.stringify({pass_marks:{aptitude:Number(data.aptitude),technical:Number(data.technical),coding:Number(data.coding)}, violation_limit:Number(data.violation_limit), assessment_minutes:Number(data.assessment_minutes)})});
    notify('Assessment settings saved for new attempts');
  } catch (error) { notify(error.message); }
}

showReport = function() {
  baseShowReport();
  const modal = document.querySelector('.modal-back .modal');
  if (!modal || !report) return;
  if (me.role === 'super_admin' || (me.responsibilities || []).includes('technical_team')) {
    const heading = [...modal.querySelectorAll('h3')].find(node => node.textContent === 'Coding submissions');
    let card = heading?.nextElementSibling;
    for (const item of report.coding) {
      if (item.submitted && card) card.insertAdjacentHTML('beforeend', `<div class="field" style="margin-top:12px"><label for="codeScore-${item.id}">Admin score (0-${item.max_score})</label><input id="codeScore-${item.id}" type="number" min="0" max="${item.max_score}" value="${item.score ?? ''}" required><label for="codeFeedback-${item.id}">Review feedback</label><textarea id="codeFeedback-${item.id}" maxlength="5000" required>${esc(item.result?.feedback || '')}</textarea><button class="btn primary small" onclick="saveCodeReview(${item.id})">Save coding review</button></div>`);
      card = card?.nextElementSibling;
    }
  }
  const monitoring = report.monitoring || [];
  const html = `<div class="card" style="margin-top:18px"><div class="card-head"><h3>Assessment monitoring</h3><span class="muted">Review signals separately from scores and recommendations</span></div>
    <p class="muted">Browser events are indicators for review, not proof of misconduct. A candidate's hiring decision is made by authorized HR staff.</p>
    ${monitoring.length ? monitoring.map(session => `<div class="question"><div class="row between"><strong>${esc(session.round)}</strong><span class="chip">${session.warning_count} warning${session.warning_count === 1 ? '' : 's'} Â· limit ${session.violation_limit}</span></div>
    <p class="muted">Started ${esc(new Date(session.started_at).toLocaleString())} Â· Submitted ${session.submitted_at ? esc(new Date(session.submitted_at).toLocaleString()) : 'not yet'} Â· Submission reason: ${esc(session.submission_reason || 'In progress')}</p>
    ${session.round !== 'coding' ? (() => {
      const attempt = report.attempts.find(item => item.round === session.round);
      if (!attempt) return '';
      return `<p class="muted">Saved answers: ${Object.entries(attempt.answers).sort((a,b) => Number(a[0]) - Number(b[0])).map(([number, answer]) => `Q${esc(number)}: ${String.fromCharCode(65 + Number(answer))}`).join(' Â· ') || 'None'}<br>Submitted: ${attempt.submitted_at ? esc(new Date(attempt.submitted_at).toLocaleString()) : 'Not submitted'}</p>`;
    })() : `<p class="muted">Saved coding sources and evaluation feedback are shown above.</p>`}
    ${session.events.length ? `<div class="table-wrap"><table><thead><tr><th>Event</th><th>Timestamp</th><th>Duration</th></tr></thead><tbody>${session.events.map(event => `<tr><td>${esc(event.kind.replaceAll('_',' '))}</td><td>${esc(new Date(event.at).toLocaleString())}</td><td>${event.duration_ms == null ? 'â€”' : `${(event.duration_ms / 1000).toFixed(1)} s`}</td></tr>`).join('')}</tbody></table></div>` : '<p class="muted">No monitoring events recorded.</p>'}
    ${session.review ? `<p class="muted">Reviewed by ${esc(session.review.reviewed_by)} Â· ${esc(new Date(session.review.reviewed_at).toLocaleString())}</p>` : ''}
    ${(me.role === 'super_admin' || (me.responsibilities || []).some(role => ['technical_hr','general_hr'].includes(role))) ? `<div class="field" style="margin-top:12px"><label>HR monitoring review Â· circumstances and follow-up</label><textarea id="monitorReview-${esc(session.round)}">${esc(session.review?.note || '')}</textarea><button class="btn secondary small" onclick="saveMonitorReview(${report.candidate.id},'${session.round}')">Save review</button></div>` : ''}</div>`).join('') : '<p class="muted">No assessment sessions started.</p>'}</div>`;
  const activity = [...modal.querySelectorAll('h3')].find(node => node.textContent === 'Activity');
  if (activity) activity.insertAdjacentHTML('beforebegin', html);
};

async function saveCodeReview(submissionId) {
  const score = document.querySelector(`#codeScore-${submissionId}`);
  const feedback = document.querySelector(`#codeFeedback-${submissionId}`);
  if (!score.reportValidity() || !feedback.reportValidity()) return;
  try {
    const candidateId = report.candidate.id;
    await api(`/admin/coding/${submissionId}/review`, {method:'PUT', body:JSON.stringify({score:Number(score.value), feedback:feedback.value.trim()})});
    document.querySelector('.modal-back')?.remove();
    await render();
    report = await api(`/admin/candidates/${candidateId}`);
    showReport();
    notify('Coding review saved');
  } catch (error) { notify(error.message); }
}

async function saveMonitorReview(candidateId, roundName) {
  try {
    const note = document.querySelector(`#monitorReview-${roundName}`).value;
    await api(`/admin/candidates/${candidateId}/monitoring/${roundName}/review`, {method:'PUT', body:JSON.stringify({note})});
    report = await api(`/admin/candidates/${candidateId}`);
    document.querySelector('.modal-back')?.remove();
    showReport();
    notify('Monitoring review saved');
  } catch (error) { notify(error.message); }
}

document.addEventListener('visibilitychange', () => {
  if (!focusedRound || assessmentDialogOpen || Date.now() < ignoreFocusUntil) return;
  if (document.hidden) reportFocus('page_hidden');
  else if (document.hasFocus()) resumeFocusedAssessment();
});
window.addEventListener('blur', () => { if (focusedRound && !assessmentDialogOpen && Date.now() >= ignoreFocusUntil && !document.hidden) { setAssessmentControlsLocked(true); updateFocusBanner(); reportFocus('focus_lost'); } });
window.addEventListener('focus', () => { if (focusedRound && !assessmentDialogOpen && Date.now() >= ignoreFocusUntil && !document.hidden) resumeFocusedAssessment(); });
document.addEventListener('fullscreenchange', () => {
  if (!focusedRound || assessmentDialogOpen || Date.now() < ignoreFocusUntil) return;
  if (document.fullscreenElement) { resumeFocusedAssessment(); return; }
  setAssessmentControlsLocked(isAssessmentInputLocked());
  updateFocusBanner();
  if (!document.fullscreenElement) reportFocus('fullscreen_exit');
});
window.addEventListener('beforeunload', event => {
  if (!focusedRound || !hasUnsavedWork) return;
  event.preventDefault(); event.returnValue = '';
});
document.addEventListener('paste', event => {
  if (!focusedRound || !event.target.closest('.options, #sourceCode, #analyticsSource')) return;
  event.preventDefault();
  notify('Pasting is disabled during this assessment. Please enter your own answer.');
  reportFocus('paste_blocked');
}, true);
document.addEventListener('drop', event => {
  if (!focusedRound || !event.target.closest('.options, #sourceCode, #analyticsSource')) return;
  event.preventDefault();
  notify('Pasting is disabled during this assessment. Please enter your own answer.');
  reportFocus('drag_blocked');
}, true);
document.addEventListener('dragover', event => {
  if (focusedRound && event.target.closest('.options, #sourceCode, #analyticsSource')) event.preventDefault();
}, true);
for (const type of ['copy','cut','contextmenu']) {
  document.addEventListener(type, event => {
    if (document.body.classList.contains('focused') && event.target.closest('.protected-content')) event.preventDefault();
  }, true);
}
setInterval(() => {
  if (!focusedRound || !focusedSession) return;
  if (pauseSyncPending && document.fullscreenElement && document.hasFocus() && !document.hidden) resumeFocusedAssessment();
  updateFocusBanner();
  if (!isAssessmentInputLocked() && new Date(focusedSession.deadline_at).getTime() <= Date.now() && focusedRound !== 'coding') submitTimedOutAssessment();
  if (!isAssessmentInputLocked() && new Date(focusedSession.deadline_at).getTime() <= Date.now() && focusedRound === 'coding') reportFocus('returned');
}, 1000);
