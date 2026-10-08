/**
 * Compatibilité : les pages existantes importent encore `@/components/ui`.
 * Les briques vivent désormais dans le Design System (`@/components/ds`) ;
 * ce fichier se contente de les ré-exporter (mêmes noms, mêmes props).
 */
export { Button, Input, Card, Stat, Badge } from "./ds";
