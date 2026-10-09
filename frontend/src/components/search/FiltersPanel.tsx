"use client";
import { useId, useMemo } from "react";
import { BadgeCheck, LocateFixed, RotateCcw, TriangleAlert, Zap } from "lucide-react";
import { Alert } from "@/components/ds/Alert";
import { Button } from "@/components/ds/Button";
import { CONTROL, Select } from "@/components/ds/Field";
import type { Category } from "@/lib/types";
import type { ResolvedTrade } from "@/lib/trades";
import { FilterSection, FOCUS_RING, Segmented, SwitchButton } from "./controls";
import {
  DEFAULT_RADIUS,
  PRICE_TYPE_OPTIONS,
  RADIUS_OPTIONS,
  SORT_OPTIONS,
  isLocated,
  useDebouncedDraft,
  type PriceTypeKey,
  type SearchState,
  type SortKey,
} from "./useSearchState";

export type CategoriesStatus = "loading" | "ready" | "error";

export interface FiltersPanelProps {
  state: SearchState;
  update: (patch: Partial<SearchState>) => void;
  categories: Category[];
  trades: ResolvedTrade[];
  categoriesStatus: CategoriesStatus;
  onRetryCategories: () => void;
  /**
   * true en mode « Autour de moi » : /services/nearby/ classe par distance et
   * n'applique ni le type de tarif ni le tri (le budget, lui, s'applique).
   */
  distanceSorted: boolean;
  /** Affiche aussi le tri (panneau mobile ; sur bureau il est dans la barre de résultats). */
  showSort?: boolean;
}

const collator = new Intl.Collator("fr", { sensitivity: "base" });
const byName = (a: Category, b: Category) => collator.compare(a.name, b.name);

/**
 * Catégories actives regroupées par famille de métiers (ordre alphabétique),
 * puis les autres catégories réelles en fin de liste.
 */
function groupCategories(categories: Category[], trades: ResolvedTrade[]) {
  const used = new Set<string>();
  const groups = [...trades]
    .sort((a, b) => collator.compare(a.label, b.label))
    .map((t) => {
      t.categories.forEach((c) => used.add(c.slug));
      return { label: t.label, items: [...t.categories].sort(byName) };
    });
  const others = categories.filter((c) => !used.has(c.slug)).sort(byName);
  if (others.length) groups.push({ label: groups.length ? "Autres catégories" : "Catégories", items: others });
  return groups;
}

function optionLabel(c: Category): string {
  return typeof c.services_count === "number" ? `${c.name} (${c.services_count})` : c.name;
}

function PriceInput({
  label,
  value,
  onCommit,
  disabled,
}: {
  label: string;
  value: string;
  onCommit: (v: string) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const [draft, setDraft, flush] = useDebouncedDraft(value, onCommit);
  return (
    <div className="min-w-0">
      <label htmlFor={id} className="mb-1.5 block text-xs font-semibold text-ash">
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          autoComplete="off"
          placeholder="—"
          value={draft}
          disabled={disabled}
          onChange={(e) => setDraft(e.target.value.replace(/\D/g, "").slice(0, 9))}
          onBlur={flush}
          onKeyDown={(e) => {
            if (e.key === "Enter") flush();
          }}
          className={`${CONTROL} min-h-[44px] pl-3 pr-12 font-semibold`}
        />
        <span
          aria-hidden
          className="pointer-events-none absolute inset-y-0 right-3 grid place-items-center text-[11px] font-bold text-ash"
        >
          FCFA
        </span>
      </div>
    </div>
  );
}

export default function FiltersPanel({
  state,
  update,
  categories,
  trades,
  categoriesStatus,
  onRetryCategories,
  distanceSorted,
  showSort = false,
}: FiltersPanelProps) {
  const uid = useId();
  const ids = {
    category: `${uid}-category`,
    availability: `${uid}-availability`,
    radius: `${uid}-radius`,
    priceType: `${uid}-price-type`,
    budget: `${uid}-budget`,
    sort: `${uid}-sort`,
  };
  const groups = useMemo(() => groupCategories(categories, trades), [categories, trades]);
  const located = isLocated(state);
  const selectValue = state.metier.length === 1 ? state.metier[0] : state.metier.length > 1 ? "__multi" : "";
  const quoteOnly = !distanceSorted && state.priceType === "quote";
  const invalidRange =
    Boolean(state.minPrice && state.maxPrice) && Number(state.minPrice) > Number(state.maxPrice);

  return (
    <div className="space-y-7">
      <FilterSection title="Métier" titleId={ids.category}>
        <div>
          <label htmlFor={`${ids.category}-select`} className="sr-only">
            Catégorie de prestation
          </label>
          <Select
            id={`${ids.category}-select`}
            value={categoriesStatus === "ready" ? selectValue : ""}
            disabled={categoriesStatus !== "ready"}
            onChange={(e) => update({ metier: e.target.value ? [e.target.value] : [] })}
          >
            <option value="">
              {categoriesStatus === "loading" ? "Chargement des métiers…" : "Toutes les catégories"}
            </option>
            {state.metier.length > 1 ? (
              <option value="__multi" disabled>
                {state.metier.length} métiers sélectionnés
              </option>
            ) : null}
            {groups.map((g) => (
              <optgroup key={g.label} label={g.label}>
                {g.items.map((c) => (
                  <option key={c.id} value={c.slug}>
                    {optionLabel(c)}
                  </option>
                ))}
              </optgroup>
            ))}
          </Select>
        </div>
        {categoriesStatus === "error" ? (
          <p className="flex flex-wrap items-center gap-x-2 text-xs text-ash">
            Liste des métiers indisponible.
            <button
              type="button"
              onClick={onRetryCategories}
              className={`inline-flex min-h-[44px] items-center gap-1 font-semibold text-primaryDark hover:underline ${FOCUS_RING}`}
            >
              <RotateCcw aria-hidden className="h-3.5 w-3.5" />
              Réessayer
            </button>
          </p>
        ) : null}
      </FilterSection>

      <FilterSection title="Disponibilité" titleId={ids.availability}>
        <div className="space-y-2">
          <SwitchButton
            pressed={state.online}
            onToggle={() => update({ online: !state.online })}
            icon={Zap}
            label="En ligne maintenant"
            description="Disponibles immédiatement"
          />
          <SwitchButton
            pressed={state.verified}
            onToggle={() => update({ verified: !state.verified })}
            icon={BadgeCheck}
            label="Profils vérifiés uniquement"
            description="Identité et documents contrôlés"
          />
        </div>
      </FilterSection>

      {located ? (
        <FilterSection title="Rayon autour de vous" titleId={ids.radius}>
          <Segmented<number>
            labelledBy={ids.radius}
            columns={5}
            value={state.radius}
            onChange={(radius) => update({ radius })}
            options={RADIUS_OPTIONS.map((r) => ({ value: r, label: `${r}`, ariaLabel: `${r} km` }))}
          />
          <p className="text-xs text-ash">Distance maximale en kilomètres.</p>
        </FilterSection>
      ) : null}

      {distanceSorted ? (
        <Alert
          tone="brand"
          icon={<LocateFixed />}
          action={
            <Button
              type="button"
              variant="outline"
              block
              className="!whitespace-normal text-center"
              onClick={() => update({ lat: null, lng: null, radius: DEFAULT_RADIUS })}
            >
              Rechercher sans localisation
            </Button>
          }
        >
          Autour de vous, les résultats sont classés <strong>par distance</strong>. Le type de tarif et le tri
          s&apos;appliquent à la recherche sans localisation.
        </Alert>
      ) : (
        <FilterSection title="Type de tarif" titleId={ids.priceType}>
          <Segmented<PriceTypeKey | "">
            labelledBy={ids.priceType}
            value={state.priceType}
            onChange={(priceType) =>
              update(priceType === "quote" ? { priceType, minPrice: "", maxPrice: "" } : { priceType })
            }
            options={[{ value: "", label: "Tous" }, ...PRICE_TYPE_OPTIONS]}
          />
        </FilterSection>
      )}

      <FilterSection
        title="Budget"
        titleId={ids.budget}
        hint={quoteOnly ? "Les prestations sur devis n'affichent pas de prix." : "Montants en FCFA."}
      >
        <div className="grid grid-cols-2 gap-2">
          <PriceInput
            label="Minimum"
            value={state.minPrice}
            disabled={quoteOnly}
            onCommit={(minPrice) => update({ minPrice })}
          />
          <PriceInput
            label="Maximum"
            value={state.maxPrice}
            disabled={quoteOnly}
            onCommit={(maxPrice) => update({ maxPrice })}
          />
        </div>
        {invalidRange ? (
          <p role="status" className="flex items-start gap-1.5 text-xs font-medium text-warningInk">
            <TriangleAlert aria-hidden className="mt-px h-3.5 w-3.5 shrink-0" />
            Le minimum dépasse le maximum : aucun prix ne peut correspondre.
          </p>
        ) : null}
      </FilterSection>

      {showSort && !distanceSorted ? (
        <FilterSection title="Trier par" titleId={ids.sort}>
          <Segmented<SortKey>
            labelledBy={ids.sort}
            value={state.sort}
            onChange={(sort) => update({ sort })}
            options={SORT_OPTIONS}
          />
        </FilterSection>
      ) : null}
    </div>
  );
}
