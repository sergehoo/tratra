"use client";
import { useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { ApiError } from "@/lib/api";
import { Button, Input, Card } from "@/components/ui";

const ROLES = [
  { value: "client", label: "Client (particulier)" },
  { value: "handyman", label: "Artisan / ouvrier" },
  { value: "entreprise", label: "Entreprise (B2B)" },
];

export default function RegisterPage() {
  const { register } = useAuth();
  const [f, setF] = useState({ username: "", email: "", password: "", user_type: "client", first_name: "", last_name: "", phone: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF((s) => ({ ...s, [k]: e.target.value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await register(f);
    } catch (err) {
      const data = err instanceof ApiError ? err.data : null;
      setError(typeof data === "object" && data ? Object.values(data).flat().join(" ") : "Inscription impossible.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center bg-slate-50 px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 text-center text-2xl font-extrabold">
          <span className="text-primary">TRA</span><span className="text-accent">TRA</span>
        </div>
        <Card>
          <h1 className="mb-1 text-xl font-bold">Créer un compte</h1>
          <p className="mb-5 text-sm text-ash">Choisissez votre profil.</p>
          <form onSubmit={submit} className="flex flex-col gap-3">
            <select value={f.user_type} onChange={set("user_type")}
                    className="w-full rounded-xl border border-slate-200 px-4 py-2.5 outline-none focus:ring-2 focus:ring-accent">
              {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
            <div className="grid grid-cols-2 gap-3">
              <Input placeholder="Prénom" value={f.first_name} onChange={set("first_name")} />
              <Input placeholder="Nom" value={f.last_name} onChange={set("last_name")} />
            </div>
            <Input placeholder="Nom d'utilisateur" value={f.username} onChange={set("username")} />
            <Input type="email" placeholder="Email" value={f.email} onChange={set("email")} />
            <Input placeholder="Téléphone" value={f.phone} onChange={set("phone")} />
            <Input type="password" placeholder="Mot de passe" value={f.password} onChange={set("password")} />
            {error && <p className="text-sm text-red-600">{error}</p>}
            <Button type="submit" disabled={busy}>{busy ? "Création…" : "Créer mon compte"}</Button>
          </form>
          <p className="mt-4 text-center text-sm text-ash">
            Déjà inscrit ? <Link href="/login" className="font-semibold text-primary">Se connecter</Link>
          </p>
        </Card>
      </div>
    </div>
  );
}
