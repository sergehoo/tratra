"use client";
import { useCallback } from "react";
import { get } from "@/lib/api";
import { eng, type Overview, type Rules } from "@/lib/engagements";
import { resultsOf } from "@/lib/public";
import type { Category, Paginated } from "@/lib/types";
import { useLoad } from "./common";

interface RulesIndex {
  default: Rules;
  categories: (Rules & { category: { id: number; name: string } })[];
}

/** Métiers, règles par métier (durée maximale, emploi salarié ouvert ou non…) et organisations habilitées — tout vient du serveur. */
export function useTermsContext() {
  const categories = useLoad(async () => resultsOf(await get<Paginated<Category> | Category[]>("/categories/?page_size=100&ordering=name")), []);
  const index = useLoad(() => eng.get<RulesIndex>("/rules/"), []);
  const overview = useLoad(() => eng.get<Overview>("/me/overview/"), []);
  const rules = useCallback(
    (categoryId: string): Rules | null => {
      if (!index.data) return null;
      return index.data.categories.find((c) => String(c.category.id) === categoryId) ?? index.data.default;
    },
    [index.data],
  );
  return {
    categories: categories.data ?? [],
    rules,
    organizations: overview.data?.organizations ?? [],
    ready: !categories.loading && !index.loading,
    error: categories.error || index.error,
    reload: () => {
      void categories.reload();
      void index.reload();
    },
  };
}
