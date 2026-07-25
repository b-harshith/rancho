(function portalAccessBootstrap() {
  'use strict';

  document.documentElement.classList.add('portal-auth-pending');

  const request = async (body) => {
    const response = await fetch('/api/auth', {
      method: body ? 'POST' : 'GET',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch (_) {
      payload = {};
    }
    return { response, payload };
  };

  const unlockPage = () => {
    document.documentElement.classList.remove('portal-auth-pending', 'portal-auth-locked');
    document.getElementById('portal-auth-layer')?.remove();
    window.dispatchEvent(new CustomEvent('portal:authenticated'));
  };

  const showLogin = (message = '') => {
    document.documentElement.classList.remove('portal-auth-pending');
    document.documentElement.classList.add('portal-auth-locked');
    let layer = document.getElementById('portal-auth-layer');
    if (!layer) {
      layer = document.createElement('div');
      layer.id = 'portal-auth-layer';
      layer.className = 'portal-auth-layer';
      layer.innerHTML = `
        <main class="portal-auth-card" role="dialog" aria-modal="true" aria-labelledby="portal-auth-title">
          <div class="portal-auth-mark" aria-hidden="true">RL</div>
          <p class="portal-auth-eyebrow">RanchoLabs Market Intelligence</p>
          <h1 id="portal-auth-title">Client portal access</h1>
          <p class="portal-auth-copy">Enter the client password to view the four-city research workspace.</p>
          <form id="portal-auth-form" novalidate>
            <label for="portal-auth-password">Password</label>
            <input id="portal-auth-password" name="password" type="password" autocomplete="current-password" required />
            <p id="portal-auth-message" class="portal-auth-message" role="status" aria-live="polite"></p>
            <button type="submit">Open research portal</button>
          </form>
          <p class="portal-auth-footnote">Access expires automatically. Client data is delivered only after server authentication.</p>
        </main>`;
      document.body.appendChild(layer);
      const form = document.getElementById('portal-auth-form');
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const input = document.getElementById('portal-auth-password');
        const status = document.getElementById('portal-auth-message');
        const button = form.querySelector('button[type="submit"]');
        status.textContent = '';
        button.disabled = true;
        button.textContent = 'Checking…';
        try {
          const result = await request({ password: input.value });
          if (result.response.ok && result.payload.authenticated) {
            window.location.reload();
            return;
          }
          status.textContent = result.payload.error || 'The password was not accepted.';
          input.select();
        } catch (_) {
          status.textContent = 'Access could not be checked. Please try again.';
        } finally {
          button.disabled = false;
          button.textContent = 'Open research portal';
        }
      });
    }
    const status = document.getElementById('portal-auth-message');
    if (status && message) status.textContent = message;
    window.setTimeout(() => document.getElementById('portal-auth-password')?.focus(), 0);
  };

  const start = async () => {
    try {
      const result = await request();
      if (result.response.ok && result.payload.authenticated) {
        unlockPage();
      } else {
        showLogin(result.response.status === 503 ? 'Portal access is being configured.' : '');
      }
    } catch (_) {
      showLogin('Access could not be checked. Please try again.');
    }
  };

  window.portalSignOut = async () => {
    await request({ action: 'logout' });
    window.location.reload();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
})();
