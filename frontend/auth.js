// Cognito Hosted UI, authorization-code flow with PKCE (no client secret in the browser).
const Auth = (() => {
  const c = window.APP_CONFIG, K = "tok";
  const b64 = b => btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const rand = () => b64(crypto.getRandomValues(new Uint8Array(32)));
  async function login() {
    const verifier = rand(), state = rand();
    sessionStorage.setItem("pkce", verifier); sessionStorage.setItem("state", state);
    const challenge = b64(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
    location.href = `${c.COGNITO_DOMAIN}/oauth2/authorize?response_type=code&client_id=${c.COGNITO_CLIENT_ID}` +
      `&redirect_uri=${encodeURIComponent(c.REDIRECT_URI)}&scope=openid+email+profile&state=${state}` +
      `&code_challenge_method=S256&code_challenge=${challenge}`;
  }
  async function handleRedirect() {
    const q = new URLSearchParams(location.search), code = q.get("code");
    if (!code) return;
    if (q.get("state") !== sessionStorage.getItem("state")) throw new Error("Bad state");
    const r = await fetch(`${c.COGNITO_DOMAIN}/oauth2/token`, {method: "POST",
      headers: {"Content-Type": "application/x-www-form-urlencoded"},
      body: new URLSearchParams({grant_type: "authorization_code", client_id: c.COGNITO_CLIENT_ID, code,
        redirect_uri: c.REDIRECT_URI, code_verifier: sessionStorage.getItem("pkce")})});
    if (!r.ok) throw new Error("Sign-in failed");
    const t = await r.json();
    sessionStorage.setItem(K, JSON.stringify({id: t.id_token, exp: Date.now() + t.expires_in * 1000}));
    history.replaceState({}, "", c.REDIRECT_URI);
  }
  const token = () => { try { const t = JSON.parse(sessionStorage.getItem(K)); return t && t.exp > Date.now() ? t.id : null; } catch { return null; } };
  const logout = () => { sessionStorage.removeItem(K); location.href = `${c.COGNITO_DOMAIN}/logout?client_id=${c.COGNITO_CLIENT_ID}&logout_uri=${encodeURIComponent(c.REDIRECT_URI)}`; };
  return {login, logout, token, handleRedirect};
})();
