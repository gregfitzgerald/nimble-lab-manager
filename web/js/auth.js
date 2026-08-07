// auth.js -- the login view. Rendered by app.js whenever there is no session.
// Talks to the API only through ctx.api and reports success via ctx.onLogin.

const DEMO_ACCOUNTS = [
  { label: "Admin", username: "admin", password: "admin" },
  { label: "Manager", username: "manager", password: "manager" },
  { label: "Member", username: "member", password: "member" },
  { label: "Viewer", username: "viewer", password: "viewer" },
];

export function render(root, ctx) {
  const wrap = document.createElement("div");
  wrap.className = "login-wrap";
  wrap.innerHTML = `
    <div class="card login-card">
      <div class="login-brand"><span class="brand-mark"></span><span>Nimble Lab Manager</span></div>
      <h1 class="view-title">Sign in</h1>
      <p class="view-sub" id="login-sub">Enter your credentials.</p>
      <form id="login-form" novalidate>
        <div class="login-field">
          <label for="login-username">Username</label>
          <input id="login-username" name="username" autocomplete="username" required>
        </div>
        <div class="login-field">
          <label for="login-password">Password</label>
          <input id="login-password" name="password" type="password" autocomplete="current-password" required>
        </div>
        <div class="login-error" id="login-error"></div>
        <button class="btn btn-primary login-submit" type="submit">Sign in</button>
      </form>
      <div class="login-demos" id="login-demos" hidden>
        <div class="login-demos-title">Demo accounts</div>
        <div class="demo-list" id="demo-list"></div>
      </div>
    </div>`;
  root.appendChild(wrap);

  const form = wrap.querySelector("#login-form");
  const userInput = wrap.querySelector("#login-username");
  const passInput = wrap.querySelector("#login-password");
  const errBox = wrap.querySelector("#login-error");
  const submitBtn = wrap.querySelector(".login-submit");

  // The one-click demo-login helpers are shown only on a demo instance -- a
  // deployed (empty) deployment has no such accounts, so we never advertise
  // them there. Ask the server, defaulting to hidden if the check fails.
  (async () => {
    let demoMode = false;
    try {
      demoMode = !!(await ctx.api.get("/api/public-config")).demo_mode;
    } catch (_) {
      demoMode = false;
    }
    if (!demoMode) return;
    wrap.querySelector("#login-sub").textContent =
      "Pick a demo account below or enter your own credentials.";
    const demosBox = wrap.querySelector("#login-demos");
    const demoList = wrap.querySelector("#demo-list");
    for (const acct of DEMO_ACCOUNTS) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "btn demo-btn";
      const name = document.createElement("span");
      name.textContent = acct.label;
      const cred = document.createElement("span");
      cred.className = "demo-cred mono";
      cred.textContent = `${acct.username} / ${acct.password}`;
      b.append(name, cred);
      b.addEventListener("click", () => {
        userInput.value = acct.username;
        passInput.value = acct.password;
        errBox.textContent = "";
        submitBtn.focus();
      });
      demoList.appendChild(b);
    }
    demosBox.hidden = false;
  })();

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = userInput.value.trim();
    const password = passInput.value;
    if (!username || !password) {
      errBox.textContent = "Enter a username and password.";
      return;
    }
    errBox.textContent = "";
    submitBtn.disabled = true;
    try {
      const data = await ctx.api.post("/api/login", { username, password });
      ctx.onLogin(data.user);
    } catch (err) {
      const msg = err && err.message ? err.message : String(err);
      errBox.textContent = msg === "invalid credentials"
        ? "Invalid username or password."
        : "Sign in failed: " + msg;
      submitBtn.disabled = false;
      passInput.focus();
      passInput.select();
    }
  });

  userInput.focus();
}
