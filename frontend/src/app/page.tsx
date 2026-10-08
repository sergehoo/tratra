"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { HOME_BY_ROLE } from "@/lib/config";
import { get } from "@/lib/api";
import type { Category, Service, Paginated } from "@/lib/types";

function list<T>(d: Paginated<T> | T[]): T[] {
  return Array.isArray(d) ? d : d.results ?? [];
}

export default function Landing() {
  const { user } = useAuth();
  const [cats, setCats] = useState<Category[]>([]);
  const [services, setServices] = useState<Service[]>([]);

  useEffect(() => {
    get<Paginated<Category>>("/categories/").then((d) => setCats(list(d).slice(0, 6))).catch(() => {});
    get<Paginated<Service>>("/services/").then((d) => setServices(list(d).slice(0, 6))).catch(() => {});
  }, []);

  const space = user ? HOME_BY_ROLE[user.user_type] ?? "/client" : null;

  return (
    <div className="min-h-screen bg-white text-ink">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-slate-100 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4">
          <Link href="/" className="flex items-center gap-2">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-primary font-extrabold text-white">T</span>
            <span className="text-xl font-extrabold"><span className="text-primary">TRA</span><span className="text-accent">TRA</span></span>
          </Link>
          <nav className="hidden items-center gap-7 md:flex">
            <a href="#categories" className="text-sm text-ash hover:text-ink">Catégories</a>
            <a href="#how" className="text-sm text-ash hover:text-ink">Fonctionnement</a>
            <a href="#trust" className="text-sm text-ash hover:text-ink">Sécurité</a>
          </nav>
          <div className="flex items-center gap-2">
            {space ? (
              <Link href={space} className="rounded-xl bg-primary px-4 py-2 font-semibold text-white hover:bg-primaryDark">Mon espace</Link>
            ) : (
              <>
                <Link href="/login" className="rounded-xl border border-primary px-4 py-2 font-semibold text-primary hover:bg-primarySoft">Connexion</Link>
                <Link href="/register" className="rounded-xl bg-primary px-4 py-2 font-semibold text-white hover:bg-primaryDark">Créer un compte</Link>
              </>
            )}
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="bg-gradient-to-b from-primarySoft to-white">
        <div className="mx-auto grid max-w-6xl items-center gap-10 px-4 py-16 md:grid-cols-2">
          <div>
            <span className="inline-block rounded-full bg-accentSoft px-3 py-1 text-sm font-semibold text-ink">
              Services à domicile, en toute confiance
            </span>
            <h1 className="mt-4 text-4xl font-extrabold leading-tight md:text-5xl">
              Trouvez un artisan <span className="text-primary">de confiance</span>, près de chez vous
            </h1>
            <p className="mt-4 max-w-md text-ash">
              Plomberie, ménage, électricité, cuisine… Réservez un professionnel vérifié,
              payez en toute sécurité (séquestre) et suivez votre intervention en temps réel.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link href="/register" className="rounded-xl bg-primary px-6 py-3 font-semibold text-white hover:bg-primaryDark">Trouver un artisan</Link>
              <Link href="/register" className="rounded-xl bg-accent px-6 py-3 font-semibold text-ink hover:brightness-95">Devenir artisan</Link>
            </div>
            <div className="mt-8 flex gap-6 text-sm">
              <span className="flex items-center gap-2 font-semibold"><span className="text-primary">✓</span> Identités vérifiées</span>
              <span className="flex items-center gap-2 font-semibold"><span className="text-primary">✓</span> Paiement séquestré</span>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            {cats.slice(0, 4).map((c) => (
              <div key={c.id} className="rounded-2xl border border-slate-100 bg-white p-5 shadow-soft">
                <p className="text-lg font-bold">{c.name}</p>
                <p className="text-sm text-ash">{c.description ?? "Professionnels qualifiés"}</p>
              </div>
            ))}
            {cats.length === 0 && <div className="col-span-2 rounded-2xl border border-dashed border-slate-200 p-8 text-center text-ash">Catégories à venir</div>}
          </div>
        </div>
      </section>

      {/* Catégories */}
      <section id="categories" className="mx-auto max-w-6xl px-4 py-16">
        <h2 className="text-3xl font-extrabold">Nos catégories</h2>
        <p className="mt-2 text-ash">Un professionnel pour chaque besoin du quotidien.</p>
        <div className="mt-8 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          {cats.map((c) => (
            <Link key={c.id} href="/register" className="rounded-xl border border-slate-200 p-4 transition hover:shadow-soft">
              <p className="font-semibold">{c.name}</p>
            </Link>
          ))}
        </div>
      </section>

      {/* Services à la une */}
      {services.length > 0 && (
        <section className="bg-primarySoft/40 py-16">
          <div className="mx-auto max-w-6xl px-4">
            <h2 className="text-3xl font-extrabold">Services à la une</h2>
            <div className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {services.map((s) => (
                <div key={s.id} className="rounded-2xl border border-slate-100 bg-white p-6 shadow-soft">
                  {s.category_detail && <span className="rounded-full bg-accentSoft px-2.5 py-1 text-xs font-semibold">{s.category_detail.name}</span>}
                  <h3 className="mt-2 font-semibold">{s.title}</h3>
                  <p className="mt-1 line-clamp-2 text-sm text-ash">{s.description}</p>
                  <p className="mt-3 font-bold text-primary">{s.price ? `${Number(s.price).toLocaleString("fr-FR")} FCFA` : "Sur devis"}</p>
                </div>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* Comment ça marche */}
      <section id="how" className="mx-auto max-w-6xl px-4 py-16">
        <h2 className="text-3xl font-extrabold">Comment ça marche</h2>
        <div className="mt-8 grid gap-6 md:grid-cols-3">
          {[
            ["1", "Décrivez votre besoin", "Catégorie, adresse, date — ou intervention immédiate."],
            ["2", "Choisissez votre artisan", "Profils vérifiés, notes et tarifs transparents."],
            ["3", "Réglez en sécurité", "Paiement sous séquestre, libéré à la fin de la mission."],
          ].map(([n, t, d]) => (
            <div key={n} className="rounded-2xl border border-slate-100 bg-white p-6 shadow-soft">
              <span className="grid h-11 w-11 place-items-center rounded-xl bg-primary font-extrabold text-white">{n}</span>
              <h3 className="mt-4 text-lg font-bold">{t}</h3>
              <p className="mt-1 text-sm text-ash">{d}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Confiance */}
      <section id="trust" className="bg-primarySoft/40 py-16">
        <div className="mx-auto grid max-w-6xl gap-6 px-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["Paiement séquestré", "Fonds libérés après validation."],
            ["Artisans vérifiés (KYC)", "Documents contrôlés avant mise en ligne."],
            ["Suivi temps réel", "Localisez votre artisan en direct."],
            ["Litiges encadrés", "Médiation et remboursement en cas de souci."],
          ].map(([t, d]) => (
            <div key={t} className="rounded-2xl bg-white p-6 shadow-soft">
              <h4 className="font-bold">{t}</h4>
              <p className="mt-1 text-sm text-ash">{d}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-ink py-12 text-slate-300">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-4 sm:flex-row">
          <span className="text-xl font-extrabold"><span className="text-white">TRA</span><span className="text-accent">TRA</span></span>
          <p className="text-sm">© Tratra — Marketplace de services à domicile.</p>
          <div className="flex gap-4 text-sm">
            <Link href="/login" className="hover:text-white">Connexion</Link>
            <Link href="/register" className="hover:text-white">Inscription</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
