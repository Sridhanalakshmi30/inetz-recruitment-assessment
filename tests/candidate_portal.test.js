const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const context = {
  candidateOverview: null,
  esc: value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])),
  homeData: null,
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/candidate_portal.js', 'utf8'), context);

const candidate = {name: 'Alex Rivera', email: 'alex@example.com', role: 'Data Analytics', degree: 'B.Tech', stream: 'Computer Science', candidate_status: 'Fresher'};
context.homeData = {candidate, active_stage: 'aptitude', attempts: [], assessment_sessions: {}, history: []};
let html = context.candidateOverview();
assert.match(html, /Begin assessment/);
assert.match(html, /startAssessment\('aptitude'\)/);
assert.match(html, /0 of 2 complete/);

context.homeData = {...context.homeData, active_stage: 'technical', attempts: [{round:'aptitude', submitted_at:'2026-10-30T10:00:00Z', score:12, answers:{}}]};
html = context.candidateOverview();
assert.match(html, /startAssessment\('technical'\)/);
assert.match(html, /12 <em>\/ 35<\/em>/);

context.homeData = {...context.homeData, active_stage: null, retake_available_at: '2020-01-01T00:00:00Z', attempts: [...context.homeData.attempts, {round:'technical', submitted_at:'2026-10-30T11:00:00Z', score:16, answers:{}}]};
html = context.candidateOverview();
assert.match(html, /Assessment cycle complete/);
assert.match(html, /Start new attempt/);
assert.doesNotMatch(html, /startAssessment\('/);
console.log('Candidate dashboard states passed');
