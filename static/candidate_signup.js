candidateSignupPage = function (message = '') {
  const roles = ROLE_OPTIONS.filter(role => role !== 'Other');
  document.body.innerHTML = `<div class="login-shell"><section class="brand-side"><div class="brandmark">iNetz <span>Technologies</span></div><div class="brand-copy"><span class="badge" style="background:#ffffff18;color:#dceaff">CANDIDATE REGISTRATION</span><h1>Start your application.</h1><p>Create an account to access the assessments.</p></div></section><section class="login-main"><form class="login-card" id="candidateSignupForm"><h2>Create candidate account</h2><p class="muted">Complete your details and choose a password.</p><div id="signupError">${message ? errBox(message) : ''}</div><div class="field"><label>Full name</label><input name="name" required minlength="2" maxlength="160" autocomplete="name"></div><div class="field"><label>Email address</label><input name="email" type="email" required maxlength="254" autocomplete="email"></div><div class="field"><label>Password</label><input name="password" type="password" required minlength="8" maxlength="128" autocomplete="new-password"></div><div class="field"><label>Phone number</label><input name="mobile" type="tel" required minlength="7" maxlength="24" title="Enter a phone number with 7 to 15 digits" autocomplete="tel"></div><div class="field"><label>Degree</label><select name="degree" required><option value="" disabled selected>Select your degree</option>${['B.Tech / B.E.', 'M.Tech / M.E.', 'B.Sc', 'M.Sc', 'BCA', 'MCA', 'BBA', 'MBA', 'BA', 'MA', 'Diploma', 'Other'].map(value => `<option>${value}</option>`).join('')}</select><input name="custom_degree" placeholder="Enter your degree" minlength="2" maxlength="100" style="display:none;margin-top:8px"></div><div class="field"><label>Stream / Domain</label><select name="stream" required><option value="" disabled selected>Select your stream or domain</option>${['Computer Science', 'Information Technology', 'Artificial Intelligence / Machine Learning', 'Data Science', 'Cybersecurity', 'Full Stack Development', 'Cloud Computing', 'DevOps', 'UI/UX Design', 'Digital Marketing', 'Electronics and Communication', 'Electrical Engineering', 'Mechanical Engineering', 'Civil Engineering', 'Commerce', 'Business Administration', 'Arts and Humanities', 'Other'].map(value => `<option>${value}</option>`).join('')}</select><input name="custom_stream" placeholder="Enter your stream or domain" minlength="2" maxlength="100" style="display:none;margin-top:8px"></div><div class="field"><label>Current status</label><select name="candidate_status" required><option value="" disabled selected>Select your status</option>${['Fresher', 'Experienced', 'Career gap', 'Student'].map(value => `<option>${value}</option>`).join('')}</select></div><div class="field"><label>Applied role</label><select name="role">${roles.map(value => `<option>${esc(value)}</option>`).join('')}<option>Other</option></select><input name="custom_role" placeholder="Enter the applied role" minlength="2" maxlength="100" style="display:none;margin-top:8px"></div><button class="btn primary wide" type="submit">Create account</button><p class="footer-note">Already registered? <a class="link" href="/candidate">Sign in</a></p></form></section></div>`;

  const form = document.getElementById('candidateSignupForm');
  form.onsubmit = async event => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(form));
    for (const field of ['degree', 'stream', 'role']) {
      if (values[field] === 'Other') values[field] = values['custom_' + field].trim();
      delete values['custom_' + field];
    }
    try {
      const result = await api('/candidate/register', { method: 'POST', body: JSON.stringify(values) });
      if (result.account_exists) {
        document.getElementById('signupError').innerHTML = `${errBox('This email already has a candidate account. Sign in to continue.')}<a class="btn secondary wide" style="display:block;text-align:center" href="/candidate?email=${encodeURIComponent(values.email)}">Sign in with this email</a>`;
        return;
      }
      location.href = '/candidate/portal';
    } catch (error) {
      const errorNode = document.getElementById('signupError');
      errorNode.innerHTML = /already (registered|exists)/i.test(error.message)
        ? `${errBox('This email already has a candidate account. Sign in to continue.')}<a class="btn secondary wide" style="display:block;text-align:center" href="/candidate?email=${encodeURIComponent(values.email)}">Sign in with this email</a>`
        : errBox(error.message);
    }
  };
  for (const field of ['degree', 'stream', 'role']) {
    const select = form.elements[field];
    const custom = form.elements['custom_' + field];
    select.onchange = () => {
      custom.style.display = select.value === 'Other' ? 'block' : 'none';
      custom.required = select.value === 'Other';
    };
  }
};
