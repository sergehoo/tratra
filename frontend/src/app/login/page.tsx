"use client";
import { useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { Button, Input, Card } from "@/components/ui";

export default function LoginPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await login(username, password);
    } catch {
      setError("Identifiants invalides.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center bg-slate-50 px-4">
      <div className="w-full max-w-md">
        <div className="mb-6 text-center text-2xl font-extrabold">
          <span className="text-primary">TRA</span><span className="text-accent">TRA</span>
        </div>
        <Card>
          <h1 className="mb-1 text-xl font-bold">Connexion</h1>
          <p className="mb-5 text-sm text-ash">Accédez à votre espace.</p>
          <form onSubmit={submit} className="flex flex-col gap-3">
            <Input placeholder="Email ou nom d'utilisateur" value={username}
                   onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
            <Input type="password" placeholder="Mot de passe" value={password}
                   onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
            {error && <p className="text-sm text-red-600">{error}</p>}
            <Button type="submit" disabled={busy}>{busy ? "Connexion…" : "Se connecter"}</Button>
          </form>
          <p className="mt-4 text-center text-sm text-ash">
            Pas de compte ? <Link href="/register" className="font-semibold text-primary">Créer un compte</Link>
          </p>
        </Card>
      </div>
    </div>
  );
}
