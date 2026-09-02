import { setUser } from "./api.js";

const $ = (s) => document.querySelector(s);

export function initAuth(onReady) {
  $("#logout-btn").addEventListener("click", () => location.reload());

  if (window.DEV_AUTH) {
    const devLogin = $("#dev-login");
    if (devLogin) {
      devLogin.onclick = () => {
        const uid = $("#dev-uid").value.trim() || `user${Math.floor(Math.random() * 900 + 100)}`;
        setUser({ uid, displayName: uid }, async () => null);
        enterApp({ displayName: uid });
      };
      // Allow enter key
      $("#dev-uid").addEventListener("keydown", e => {
        if (e.key === "Enter") devLogin.click();
      });
    }
  }

  const cfg = window.FIREBASE_CONFIG || {};
  const hasFirebase = !window.DEV_AUTH && cfg && cfg.apiKey;
  const msgEl = $("#auth-msg");
  if (msgEl) {
    msgEl.textContent = hasFirebase
      ? ""
      : window.DEV_AUTH
        ? ""
        : "Firebase config missing. Set FIREBASE_CONFIG_JSON env var.";
  }

  if (!hasFirebase) {
    ["#login-btn", "#signup-btn", "#google-btn"].forEach(s => {
      const el = $(s);
      if (el) el.disabled = true;
    });
    return;
  }

  firebase.initializeApp(cfg);
  const auth = firebase.auth();

  const loginBtn = $("#login-btn");
  const signupBtn = $("#signup-btn");
  const googleBtn = $("#google-btn");

  if (loginBtn) loginBtn.onclick = () => doEmail(auth.signInWithEmailAndPassword.bind(auth));
  if (signupBtn) signupBtn.onclick = () => doEmail(auth.createUserWithEmailAndPassword.bind(auth));
  if (googleBtn) {
    googleBtn.onclick = async () => {
      googleBtn.disabled = true;
      googleBtn.innerHTML = '<span class="spinner"></span> Connecting…';
      try {
        await auth.signInWithPopup(new firebase.auth.GoogleAuthProvider());
      } catch (e) {
        authFail(e.message);
        googleBtn.disabled = false;
        googleBtn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none">…</svg> Continue with Google`;
      }
    };
  }

  function doEmail(fn) {
    const email = $("#auth-email").value.trim();
    const pass = $("#auth-pass").value;
    if (!email || !pass) { authFail("Please fill in email and password."); return; }
    fn(email, pass).catch(e => authFail(e.message));
  }

  function authFail(m) {
    if (msgEl) msgEl.textContent = m;
  }

  auth.onAuthStateChanged(async (user) => {
    if (!user) return;
    setUser(
      { uid: user.uid, displayName: user.displayName || user.email.split("@")[0], email: user.email },
      () => user.getIdToken()
    );
    enterApp({ displayName: user.displayName || user.email });
  });
}

function enterApp(me) {
  $("#auth-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  $("#userchip").classList.remove("hidden");

  const name = me.displayName || "studier";
  const nameEl = $("#uname");
  if (nameEl) nameEl.textContent = name;

  // Set avatar initials
  const avatarEl = $("#uavatar");
  if (avatarEl) {
    const parts = name.trim().split(/\s+/);
    const initials = parts.length >= 2
      ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
      : name.slice(0, 2).toUpperCase();
    avatarEl.textContent = initials;
  }

  document.dispatchEvent(new CustomEvent("sp-ready"));
}
