"use client";
import { useState } from "react";
import { Badge, PageHeader, type Column } from "@/components/ds";
import { useBoList, useDebounced } from "@/lib/useBoList";
import { DateRange, FilterBar, FilterSelect, ListView, SearchBox, dt } from "../_components/ui";

interface Row {
  id: number;
  name: string;
  phone: string | null;
  email: string | null;
  city: string | null;
  is_active: boolean;
  is_verified: boolean;
  date_joined: string;
  last_login: string | null;
  is_artisan: boolean;
  artisan_approved: boolean;
  bookings: number;
}

export default function UsersPage() {
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [active, setActive] = useState("");
  const [verified, setVerified] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const list = useBoList<Row>("/users/", { q: useDebounced(q), type, active, verified, from, to });

  const columns: Column<Row>[] = [
    { key: "name", header: "Compte", primary: true, cell: (r) => <span className="font-semibold text-ink">{r.name} <span className="font-normal text-ash">#{r.id}</span></span> },
    { key: "contact", header: "Contact", cell: (r) => <span className="text-inkSoft">{[r.phone, r.email].filter(Boolean).join(" · ") || "—"}</span> },
    { key: "city", header: "Ville", hideOnMobile: true, cell: (r) => r.city ?? "—" },
    {
      key: "roles", header: "Profil", cell: (r) => (
        <span className="flex flex-wrap gap-1.5">
          {r.is_artisan ? <Badge tone={r.artisan_approved ? "success" : "warning"}>{r.artisan_approved ? "Artisan approuvé" : "Artisan en attente"}</Badge> : <Badge tone="gray">Client</Badge>}
          {!r.is_verified ? <Badge tone="warning">Téléphone non vérifié</Badge> : null}
        </span>
      ),
    },
    { key: "bookings", header: "Réservations", align: "right", cell: (r) => r.bookings },
    { key: "joined", header: "Inscrit le", hideOnMobile: true, cell: (r) => dt(r.date_joined) },
    { key: "status", header: "Statut", cell: (r) => <Badge tone={r.is_active ? "success" : "danger"}>{r.is_active ? "Actif" : "Suspendu"}</Badge> },
  ];

  return (
    <>
      <PageHeader title="Utilisateurs" description="Comptes clients, artisans et entreprises. Les coordonnées sont masquées en liste ; le détail les affiche aux rôles autorisés." />
      <FilterBar>
        <SearchBox value={q} onChange={setQ} placeholder="Nom, téléphone, e-mail, identifiant…" />
        <FilterSelect label="Type" value={type} onChange={setType} options={[["", "Tous"], ["client", "Clients"], ["artisan", "Artisans"], ["company", "Entreprises"]]} />
        <FilterSelect label="Statut" value={active} onChange={setActive} options={[["", "Tous"], ["true", "Actifs"], ["false", "Suspendus"]]} />
        <FilterSelect label="Téléphone" value={verified} onChange={setVerified} options={[["", "Tous"], ["true", "Vérifié"], ["false", "Non vérifié"]]} />
        <DateRange from={from} to={to} onFrom={setFrom} onTo={setTo} />
      </FilterBar>
      <ListView list={list} columns={columns} rowKey={(r) => r.id} rowHref={(r) => `/backoffice/users/${r.id}`} caption="Utilisateurs" empty="Aucun compte ne correspond à ces filtres." />
    </>
  );
}
