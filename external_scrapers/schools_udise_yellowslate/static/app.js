const $ = (selector) => document.querySelector(selector);
const loadedChallenges = new Map();
let renderedChallengeSignature = '';

async function call(url, options = {}) {
  const response = await fetch(url, {headers: {'Content-Type': 'application/json'}, ...options});
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

function esc(value) {
  return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

async function refresh() {
  try {
    const data = await call('/api/status');
    const job = data.job;
    if (!job) return;
    $('#status').textContent = job.status.replaceAll('_', ' ');
    $('#pins').textContent = `${job.completed_pincodes} / ${job.total_pincodes}`;
    $('#schools').textContent = `${job.completed_schools} / ${job.total_schools}`;
    $('#responses').textContent = data.responses;
    $('#currentSchool').textContent = job.current_school_id ? `Current school: ${job.current_school_id}` : '';
    $('#export').href = `/api/export/${job.id}`;
    $('#export').classList.remove('hidden');
    $('#retry').dataset.jobId = job.id;
    $('#retry').classList.toggle('hidden', !['completed_with_errors','failed','stopped'].includes(job.status));
    $('#pinRows').innerHTML = data.pins.map(pin => `<tr>
      <td>${esc(pin.pincode)}</td><td><span class="pill ${esc(pin.status)}">${esc(pin.status)}</span></td>
      <td>${pin.captcha_attempts}</td><td>${pin.school_count}</td><td class="error">${esc(pin.error || '')}</td>
    </tr>`).join('');
    $('#eventRows').innerHTML = (data.events || []).map(event => `<article class="event ${esc(event.level)}">
      <time>${esc(new Date(event.created_at).toLocaleTimeString())}</time>
      <strong>${esc(event.event)}</strong><span>${esc(event.message)}</span>
      ${Object.keys(event.details || {}).length ? `<code>${esc(JSON.stringify(event.details))}</code>` : ''}
    </article>`).join('') || '<p class="empty">No events yet.</p>';

    const waiting = data.challenges || [];
    const waitingIds = new Set(waiting.map(item => item.id));
    for (const id of [...loadedChallenges.keys()]) if (!waitingIds.has(id)) loadedChallenges.delete(id);
    await Promise.all(waiting.map(async challenge => {
      if (!loadedChallenges.has(challenge.id)) {
        const captcha = await call(`/api/captcha/${challenge.id}`);
        loadedChallenges.set(challenge.id, captcha.image);
      }
    }));
    const pinByTask = new Map(data.pins.map(pin => [pin.id, pin.pincode]));
    const challengeSignature = waiting.map(item => item.id).join(',');
    if (challengeSignature !== renderedChallengeSignature) {
      renderedChallengeSignature = challengeSignature;
      $('#captchaCards').innerHTML = waiting.map(challenge => `<article class="captcha card" data-challenge="${challenge.id}">
        <div><p class="eyebrow">PIN ${esc(pinByTask.get(challenge.pin_task_id) || '')}</p><strong>Session #${challenge.id}</strong></div>
        <img src="${esc(loadedChallenges.get(challenge.id))}" alt="CAPTCHA challenge">
        <form class="captcha-form"><input name="code" maxlength="6" pattern="[A-Za-z0-9]{6}" autocomplete="off" required><button>Submit</button></form>
        <p class="error"></p>
      </article>`).join('');
      $('#captchaCards input')?.focus();
    }
    $('#captchaPanel').classList.toggle('hidden', waiting.length === 0);
  } catch (error) {
    $('#status').textContent = error.message;
  }
}

$('#start').addEventListener('click', async () => {
  try {
    const raw = $('#limit').value.trim();
    await call('/api/start', {method: 'POST', body: JSON.stringify(raw ? {limit: Number(raw)} : {})});
    await refresh();
  } catch (error) { alert(error.message); }
});

$('#stop').addEventListener('click', async () => {
  try { await call('/api/stop', {method: 'POST', body: '{}'}); } catch (error) { alert(error.message); }
});

$('#retry').addEventListener('click', async () => {
  try {
    const result = await call(`/api/retry/${$('#retry').dataset.jobId}`, {method:'POST',body:'{}'});
    alert(`Retrying ${result.retry_pincodes} PIN codes and ${result.retry_schools} failed schools.`);
    await refresh();
  } catch (error) { alert(error.message); }
});

$('#captchaCards').addEventListener('submit', async (event) => {
  if (!event.target.matches('.captcha-form')) return;
  event.preventDefault();
  const card = event.target.closest('[data-challenge]');
  try {
    await call('/api/captcha', {method:'POST', body:JSON.stringify({challenge_id:Number(card.dataset.challenge),code:event.target.code.value})});
    card.remove();
  } catch (error) { card.querySelector('.error').textContent = error.message; }
});

refresh();
setInterval(refresh, 1500);
