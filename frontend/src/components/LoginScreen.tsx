import { useState } from "react";
import { AuthUser, login, register } from "../auth";

export function LoginScreen({ onAuth }: { onAuth: (u: AuthUser) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = mode === "login"
        ? await login(username.trim(), password)
        : await register(username.trim(), password);
      onAuth(result.user);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-shell">
      <div className="login-card">
        <div className="login-eyebrow">TCS Knowledge Fabric</div>
        <div className="login-title">
          {mode === "login" ? "Sign in" : "Create an account"}
        </div>
        <div className="login-subtitle">
          {mode === "login"
            ? "Cases and decisions are scoped to your account."
            : "Pick a username and a password (4+ characters)."}
        </div>
        <form className="login-form" onSubmit={submit}>
          <label>Username
            <input
              type="text"
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label>Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
            />
          </label>
          {error && <div className="login-error">{error}</div>}
          <button type="submit" className="login-submit" disabled={busy}>
            {busy ? "…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>
        <div className="login-toggle">
          {mode === "login" ? (
            <>No account? <a href="#" onClick={(e) => { e.preventDefault(); setMode("register"); setError(null); }}>Register →</a></>
          ) : (
            <>Already have one? <a href="#" onClick={(e) => { e.preventDefault(); setMode("login"); setError(null); }}>Sign in →</a></>
          )}
        </div>
        {mode === "login" && (
          <div className="login-hint">
            <strong>Demo seed:</strong> <code>admin</code> / <code>admin</code>.
            Change the password from the user menu after signing in.
          </div>
        )}
      </div>
    </div>
  );
}
