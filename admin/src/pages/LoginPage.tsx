import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { KeyRound } from "lucide-react";
import { api, setToken } from "../api";
import { Button, Card, Input } from "../components/ui";

export default function LoginPage() {
  const [username, setUsername] = useState("admin"); const [password, setPassword] = useState("");
  const [error, setError] = useState(""); const [loading, setLoading] = useState(false); const nav = useNavigate();
  async function submit(e: FormEvent) {
    e.preventDefault(); setLoading(true); setError("");
    try { const result = await api<{ token: string }>("/store/api/admin/session", { method: "POST", body: JSON.stringify({ username, password }) }); setToken(result.token); nav("/"); }
    catch (err) { setError(err instanceof Error ? err.message : "Sign in failed"); }
    finally { setLoading(false); }
  }
  return <div className="login-wrap relative overflow-hidden">
    <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/60 to-transparent" />
    <Card className="login-card stack p-6">
      <div className="mb-2 grid h-10 w-10 place-items-center rounded-lg bg-white text-black"><KeyRound className="h-4 w-4" /></div>
      <div><h1 className="text-xl font-semibold tracking-tight">Store Control</h1><p className="muted mt-1">Sign in to manage delivery operations.</p></div>
      <form className="stack" onSubmit={submit}>
        <label><span className="label">Username</span><Input className="w-full" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" /></label>
        <label><span className="label">Password</span><Input className="w-full" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" autoFocus /></label>
        {error && <p className="error">{error}</p>}
        <Button className="button-primary mt-1 w-full" disabled={!username || !password || loading}>{loading ? "Signing in…" : "Sign in"}</Button>
      </form>
    </Card>
  </div>;
}
