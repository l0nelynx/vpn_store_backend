import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, setToken } from "../api";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const nav = useNavigate();

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const res = await api<{ token: string }>("/store/api/admin/login", {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      setToken(res.token);
      nav("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="card login-card stack" onSubmit={onSubmit}>
        <h1>Store Admin</h1>
        <p className="muted">Password from backend.yml (`admin_password` or `api_token`).</p>
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoFocus
        />
        {error && <div className="error">{error}</div>}
        <button className="primary" disabled={loading || !password}>
          {loading ? "…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
