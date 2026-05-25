import { useState } from "react";
import { AuthUser, login } from "../auth";

export function LoginScreen({ onAuth }: { onAuth: (u: AuthUser) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await login(username.trim(), password);
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
        <div className="login-title">Sign in</div>
        <div className="login-subtitle">
          Cases and decisions are scoped to your account. Accounts are created by an administrator.
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
              autoComplete="current-password"
              required
            />
          </label>
          {error && <div className="login-error">{error}</div>}
          <button type="submit" className="login-submit" disabled={busy}>
            {busy ? "…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
