<#assign logo = "${url.resourcesPath}/img/healthdoc-logo.png">
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sign in to HealthDoc HIMS</title>
  <link rel="icon" href="${logo}">
  <link rel="stylesheet" href="${url.resourcesPath}/css/portal.css">
</head>
<body>
  <div class="portal">
    <aside class="portal-side">
      <div class="glow glow-a"></div>
      <div class="glow glow-b"></div>
      <div class="side-brand">
        <span class="brand">
          <img src="${logo}" alt="">
          <span>
            <span class="brand-name">HealthDoc</span>
            <span class="brand-sub">Hospital Information Management System</span>
          </span>
        </span>
      </div>
      <div class="side-main">
        <div class="badge"><span class="dot"></span>Enterprise Clinical Operations Platform</div>
        <h2>Integrated Clinical, Diagnostic &amp; Administrative Excellence</h2>
        <p>Manage outpatient consultations, inpatient care, diagnostic reporting, and consent-based digital record workflows.</p>
        <div class="cards">
          <div class="card">
            <div class="icon icon-blue" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6l7-3z"/><path d="M9 12l2 2 4-4"/></svg></div>
            <div><h3>ABDM integration</h3><p>M1/M2/M3 sandbox verification in progress</p></div>
          </div>
          <div class="card">
            <div class="icon icon-green" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg></div>
            <div><h3>Consent &amp; audit</h3><p>Access controls and activity records</p></div>
          </div>
          <div class="card">
            <div class="icon icon-purple" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 8-6-16-3 8H2"/></svg></div>
            <div><h3>Ward workflows</h3><p>Vitals, medication and discharge records</p></div>
          </div>
          <div class="card">
            <div class="icon icon-cyan" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="9" r="5"/><path d="M8 14l-2 7 6-3 6 3-2-7"/></svg></div>
            <div><h3>Radiology</h3><p>Imaging integration requires facility setup</p></div>
          </div>
        </div>
      </div>
      <div class="side-foot">
        <span>HealthDoc Clinical Suite</span>
        <span>Role-based clinical workspaces</span>
      </div>
    </aside>

    <main class="portal-main">
      <section class="signin">
        <div class="signin-brand">
          <img src="${logo}" alt="">
          <span class="brand-name">HealthDoc</span>
          <span class="brand-sub">Enterprise HIMS</span>
          <h1>Clinical Portal Sign-In</h1>
          <p class="lede">Authenticate using your authorized hospital credentials</p>
        </div>

        <#if message?has_content>
          <div class="alert alert-${message.type}" role="alert">${message.summary}</div>
        </#if>

        <form id="kc-form-login" action="${url.loginAction}" method="post">
          <div class="field">
            <label for="username">Username or email</label>
            <input id="username" name="username" type="text" autocomplete="username" autofocus required value="${(login.username)!''}">
          </div>
          <div class="field">
            <label for="password">Password</label>
            <div class="password">
              <input id="password" name="password" type="password" autocomplete="current-password" required>
              <button type="button" aria-label="Show password" onclick="var p=document.getElementById('password'); var show=p.type==='password'; p.type=show?'text':'password'; this.setAttribute('aria-label', show?'Hide password':'Show password');">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>
              </button>
            </div>
          </div>
          <#if auth?has_content && auth.selectedCredential?has_content>
            <input type="hidden" name="credentialId" value="${auth.selectedCredential}">
          </#if>
          <button class="submit" id="kc-login" name="login" type="submit">Sign In</button>
        </form>

        <div class="trust">
          <div class="trust-row">
            <span>Keycloak sign-in</span>
            <span>•</span>
            <span>Role-based access</span>
            <span>•</span>
            <span>Consent controls</span>
          </div>
          <p>Authorized personnel only. Use the workspace assigned to your role.</p>
        </div>
      </section>
    </main>
  </div>
</body>
</html>
