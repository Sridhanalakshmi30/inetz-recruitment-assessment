// Live tools for the candidate analytics workspace.
const analyticsDrafts = {};
let analyticsConfig;
const analyticsTestsUrl = 'https://inetztech.com/tests';
let pythonFrame = null;
let pythonTimer = null;
let pythonBusy = false;
let pythonRunId = 0;
const previousRenderSkill = renderSkill;
const previousSelectSkill = selectSkill;
const analyticsStarters = {
  mysql: 'SELECT t.name AS team, e.name AS employee, e.salary\nFROM employees e\nJOIN teams t ON t.id = e.team_id\nWHERE e.salary = (SELECT MAX(e2.salary) FROM employees e2 WHERE e2.team_id = e.team_id);',
  'python-lambda': 'prices = [10, 25, 40]\nwith_tax = list(map(lambda price: round(price * 1.10, 2), prices))\nprint(with_tax)\n\nimport statistics\nprint("Average:", statistics.mean(with_tax))',
  'python-practice': 'values = [4, 8, 10, 14]\naverage = sum(values) / len(values)\nprint([value for value in values if value > average])'
};
selectSkill = async function(id) {
  if (!currentSkills().some(skill => skill.id === id)) return;
  const editor = document.querySelector('#analyticsSource');
  if (editor) analyticsDrafts[activeSkill] = editor.value;
  if (typeof flushCodeDraft === 'function') {
    try { await flushCodeDraft(); } catch { return; }
  }
  stopPython();
  return previousSelectSkill(id);
};
renderSkill = function() {
  if (['mysql', 'powerbi', 'python-lambda', 'python-practice'].includes(activeSkill)) return renderAnalyticsTool();
  return previousRenderSkill();
};
function analyticsLocked() {
  return typeof focusedRound !== 'undefined' && focusedRound &&
    (isAssessmentInputLocked() || focusedSession?.finished || new Date(focusedSession?.deadline_at).getTime() <= Date.now());
}
async function renderAnalyticsTool() {
  const skill = activeSkill;
  const host = document.querySelector('#codeInner');
  host.classList.remove('empty');
  const title = currentSkills().find(item => item.id === skill)?.name || skill;
  if (skill === 'powerbi') {
    host.innerHTML = '<div class="card"><h3>iNetz Analytics Tests</h3><p>Opening the in-development analytics tools...</p></div>';
  } else {
    const sql = skill === 'mysql';
    host.innerHTML = `<div class="code-layout"><section class="card"><h3>${esc(title)}</h3><p>${sql ? 'Write a query against the MySQL exercise database. Run it to see actual rows.' : 'Edit the Python code, then run it to see stdout, results, and errors.'}</p>
      ${sql ? '<h4>Exercise tables</h4><pre style="white-space:pre-wrap">teams(id, name)\nemployees(id, name, team_id, salary)\norders(id, region, amount, status)</pre><p>Find the highest salary in each team, or summarize completed orders by region.</p><p class="muted">Read-only queries. Up to 200 rows and two seconds per query.</p>' : '<p>Supports Python functions, lambda, map, filter, and the standard library. NumPy and pandas can be loaded from imports.</p><p class="muted">Python runs in your browser. First launch downloads the runtime; internet access is required. Each run starts fresh.</p>'}
      <div id="analyticsConnection" role="status"></div><p class="footer-note">These runs are practice output; they do not submit or score an assessment.</p></section>
      <section class="card"><label for="analyticsSource"><strong>${sql ? 'SQL query' : 'Python code'}</strong></label><textarea id="analyticsSource" class="codebox" spellcheck="false" maxlength="12000">${esc(analyticsDrafts[skill] ?? analyticsStarters[skill])}</textarea><div class="row" style="margin-top:12px"><button class="btn primary" id="analyticsRun" onclick="runAnalytics()">Run ${sql ? 'query' : 'Python'}</button>${sql ? '' : '<button class="btn secondary" onclick="stopPython(true)">Stop</button>'}</div><div id="analyticsOutput" class="result-box" role="status" aria-live="polite">Run your code to see output here.</div></section></div>`;
    document.querySelector('#analyticsSource').addEventListener('input', event => analyticsDrafts[skill] = event.target.value);
  }
  try {
    analyticsConfig = await api('/candidate/analytics/config');
    if (activeSkill !== skill || !host.isConnected) return;
    if (skill === 'powerbi') {
      host.innerHTML = `<section class="card analytics-embed-card"><div class="row" style="justify-content:space-between;align-items:center"><div><h3>iNetz Analytics Tests</h3><p>Use the analytics tools currently under development.</p></div><a class="btn secondary" href="${analyticsTestsUrl}" target="_blank" rel="noopener noreferrer">Open in a new tab ↗</a></div><iframe id="analyticsTestsFrame" title="iNetz Analytics Tests" src="${analyticsTestsUrl}" loading="eager" referrerpolicy="strict-origin-when-cross-origin" style="width:100%;height:min(78vh,900px);min-height:560px;border:1px solid var(--line);border-radius:8px;background:white"></iframe><p class="footer-note">If the page does not display inside the portal, open it in a new tab.</p></section>`;
    } else if (skill === 'mysql') {
      document.querySelector('#analyticsConnection').innerHTML = analyticsConfig.mysql_configured ? '<span class="badge blue">MySQL connection configured</span>' : '<div class="alert">The practice database needs administrator setup before queries can run.</div>';
    }
  } catch (error) {
    if (activeSkill === skill) (document.querySelector('#analyticsConnection') || host).textContent = error.message;
  }
  if (typeof updateFocusBanner === 'function') updateFocusBanner();
}
async function runAnalytics() {
  if (analyticsLocked()) { notify('Return to the active test to run code.'); return; }
  const editor = document.querySelector('#analyticsSource'), output = document.querySelector('#analyticsOutput');
  if (!editor || !output) return;
  const source = editor.value;
  analyticsDrafts[activeSkill] = source;
  if (activeSkill !== 'mysql') { runPython(source, output); return; }
  const button = document.querySelector('#analyticsRun');
  button.disabled = true; output.textContent = 'Running query...';
  try {
    const result = await api('/candidate/analytics/query', {method:'POST', body:JSON.stringify({source})});
    if (!output.isConnected) return;
    output.innerHTML = `<p>${result.rows.length} rows${result.truncated ? ' (limited to first 200)' : ''}</p><div class="table-wrap"><table><thead><tr>${result.columns.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${result.rows.map(row=>`<tr>${row.map(value=>`<td>${esc(value === null ? 'NULL' : value)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  } catch (error) { output.textContent = error.message; }
  finally { button.disabled = !!analyticsLocked(); }
}
function stopPython(showMessage = false) {
  clearTimeout(pythonTimer);
  pythonFrame?.remove(); pythonFrame = null; pythonBusy = false;
  if (showMessage && document.querySelector('#analyticsOutput')) document.querySelector('#analyticsOutput').textContent = 'Execution stopped.';
}
function runPython(source, output) {
  stopPython(); pythonBusy = true;
  const runId = ++pythonRunId;
  output.textContent = 'Loading Python runtime...';
  pythonFrame = document.createElement('iframe');
  pythonFrame.hidden = true;
  pythonFrame.sandbox = 'allow-scripts';
  pythonFrame.src = '/assets/python-runner.html';
  pythonFrame.onload = () => pythonFrame?.contentWindow.postMessage({type:'run', source, runId}, '*');
  document.body.append(pythonFrame);
  pythonTimer = setTimeout(() => { stopPython(); output.textContent = 'Python runtime could not load within 90 seconds. Check your internet connection and retry.'; }, 90000);
}
window.addEventListener('message', event => {
  if (!pythonFrame || event.source !== pythonFrame.contentWindow || event.data?.runId !== pythonRunId) return;
  const output = document.querySelector('#analyticsOutput');
  if (!output) { stopPython(); return; }
  if (event.data.type === 'started') {
    clearTimeout(pythonTimer); output.textContent = 'Running Python...';
    pythonTimer = setTimeout(() => { stopPython(); output.textContent = 'Stopped after the 10-second execution limit.'; }, 10000);
  } else if (event.data.type === 'result') {
    output.style.whiteSpace = 'pre-wrap';
    output.textContent = String(event.data.output || 'Completed with no output.').slice(0,30000);
    stopPython();
  }
});
