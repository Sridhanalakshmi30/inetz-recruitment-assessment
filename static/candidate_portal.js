candidateOverview = function () {
  const candidate = homeData.candidate;
  const attempts = homeData.attempts || [];
  const history = homeData.history || [];
  const findAttempt = key => attempts.find(item => item.round === key);
  const completed = ['aptitude', 'technical'].filter(key => findAttempt(key)?.submitted_at).length;
  const active = homeData.active_stage;
  const activeName = active === 'aptitude' ? 'Aptitude assessment' : active === 'technical' ? 'Technical MCQ' : '';
  const nextSession = homeData.assessment_sessions?.[active];
  const firstName = (candidate.name || 'Candidate').trim().split(/\s+/)[0];
  const retakeAt = homeData.retake_available_at;
  const canRetake = !!retakeAt && Date.now() >= new Date(retakeAt).getTime();
  const roundCard = (key, number, label, count, minutes, description) => {
    const attempt = findAttempt(key);
    const session = homeData.assessment_sessions?.[key];
    const done = !!attempt?.submitted_at;
    const ready = active === key && !done;
    const status = done ? 'Completed' : ready ? session?.started ? 'In progress' : 'Ready to begin' : 'Locked';
    return `<article class="candidate-round ${ready ? 'is-ready' : ''}">
      <div class="candidate-round-top"><span class="candidate-round-number">${number}</span><span class="candidate-status ${done ? 'is-done' : ready ? 'is-active' : ''}">${status}</span></div>
      <div><h3>${label}</h3><p>${description}</p></div>
      <div class="candidate-round-details"><span>${count} questions</span><span>${minutes} minutes</span></div>
      ${done ? `<div class="candidate-round-result"><span>Your score</span><strong>${attempt.score} / ${count}</strong></div>` : ready ? `<div class="candidate-round-result"><span>Answers saved</span><strong>${Object.keys(attempt?.answers || {}).length} / ${count}</strong></div>` : '<div class="candidate-round-result"><span>Opens after the previous round</span></div>'}
      ${ready ? `<button class="btn primary candidate-round-action" onclick="startAssessment('${key}')">${session?.started ? 'Continue assessment' : 'Start assessment'} <span aria-hidden="true">→</span></button>` : ''}
    </article>`;
  };
  return `<div class="candidate-dashboard">
    <div class="candidate-heading"><div><div class="candidate-eyebrow">CANDIDATE WORKSPACE</div><h1>Welcome back, ${esc(firstName)}<span class="candidate-wave" aria-hidden="true">.</span></h1><p>Everything you need for your assessment journey, in one place.</p></div><span class="candidate-date">${esc(new Date().toLocaleDateString(undefined, {weekday:'long', month:'long', day:'numeric'}))}</span></div>
    <section class="candidate-hero" aria-label="Your next step"><div class="candidate-hero-content"><span class="candidate-hero-label">YOUR NEXT STEP</span><h2>${activeName ? esc(activeName) : 'Assessment cycle complete'}</h2><p>${activeName ? nextSession?.started ? 'Pick up where you left off. Your saved answers are ready.' : 'You are ready to continue. Read the instructions before you begin.' : 'Your assessments are submitted. You can review your results below.'}</p>${activeName ? `<button class="candidate-hero-button" onclick="startAssessment('${active}')">${nextSession?.started ? 'Continue assessment' : 'Begin assessment'} <span aria-hidden="true">↗</span></button>` : retakeAt ? `<span class="candidate-hero-note">${canRetake ? 'Your next daily attempt is ready.' : `Next attempt available ${esc(new Date(retakeAt).toLocaleString())}`}</span>` : ''}</div><div class="candidate-hero-art" aria-hidden="true"><div class="candidate-art-ring ring-one"></div><div class="candidate-art-ring ring-two"></div><div class="candidate-art-center"><span>${completed}</span><small>OF 2<br>ROUNDS</small></div></div></section>
    <div class="candidate-metrics"><div class="candidate-metric"><span class="candidate-metric-icon">01</span><div><small>ASSESSMENTS DONE</small><strong>${completed} <em>/ 2</em></strong></div></div><div class="candidate-metric"><span class="candidate-metric-icon">02</span><div><small>TOTAL SCORE</small><strong>${attempts.reduce((sum, item) => sum + (item.score || 0), 0)} <em>/ 35</em></strong></div></div><div class="candidate-metric"><span class="candidate-metric-icon">03</span><div><small>APPLIED ROLE</small><strong class="candidate-role-value">${esc(candidate.role)}</strong></div></div></div>
    <div class="candidate-main-grid"><div class="candidate-primary-column"><section class="candidate-panel"><div class="candidate-section-title"><div><span class="candidate-eyebrow">YOUR JOURNEY</span><h2>Assessment rounds</h2><p>Complete each round in order. Your work is saved as you go.</p></div><span class="candidate-count">${completed} of 2 complete</span></div><div class="candidate-progress" role="progressbar" aria-valuenow="${completed}" aria-valuemin="0" aria-valuemax="2" aria-label="Assessment rounds completed"><span style="width:${completed * 50}%"></span></div><div class="candidate-rounds">${roundCard('aptitude', '01', 'Aptitude', 15, 30, 'Reasoning, problem solving and numerical skills.')}${roundCard('technical', '02', 'Technical MCQ', 20, 20, 'Questions tailored to your applied role.')}</div></section>
    ${history.length ? `<section class="candidate-panel"><div class="candidate-section-title"><div><span class="candidate-eyebrow">YOUR RECORD</span><h2>Previous attempts</h2></div></div><div class="candidate-history">${history.map(item => `<div class="candidate-history-row"><span>${esc(item.round === 'aptitude' ? 'Aptitude' : 'Technical MCQ')}</span><strong>${item.score} / ${item.round === 'aptitude' ? 15 : 20}</strong><time>${esc(new Date(item.submitted_at).toLocaleDateString())}</time></div>`).join('')}</div></section>` : ''}</div>
    <aside class="candidate-side-column"><section class="candidate-panel candidate-profile"><span class="candidate-eyebrow">YOUR APPLICATION</span><div class="candidate-avatar" aria-hidden="true">${esc(firstName.charAt(0).toUpperCase())}</div><h2>${esc(candidate.name)}</h2><p>${esc(candidate.email)}</p><div class="candidate-profile-fields"><div><span>Applied role</span><strong>${esc(candidate.role)}</strong></div><div><span>Degree</span><strong>${esc(candidate.degree || '—')}</strong></div><div><span>Stream / domain</span><strong>${esc(candidate.stream || '—')}</strong></div><div><span>Current status</span><strong>${esc(candidate.candidate_status || '—')}</strong></div></div></section>
    <section class="candidate-panel candidate-info"><span class="candidate-eyebrow">GOOD TO KNOW</span><h2>Before you begin</h2><ul><li>Find a quiet place and keep this tab open.</li><li>Your answers save while you work.</li><li>Each round has its own timer.</li></ul></section>
    ${retakeAt ? `<section class="candidate-panel candidate-retake"><span class="candidate-eyebrow">DAILY ATTEMPT</span><h2>Ready for another try?</h2><p>${canRetake ? 'A fresh assessment cycle is available now.' : `Your next attempt opens ${esc(new Date(retakeAt).toLocaleString())}.`}</p><button class="btn primary wide" onclick="retakeAssessments()" ${canRetake ? '' : 'disabled'}>Start new attempt</button></section>` : ''}</aside></div>
  </div>`;
};
