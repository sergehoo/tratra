/**
 * Design System Tratra — point d'entrée unique.
 * Tokens : frontend/design-system/tokens.json (partagés avec l'app Flutter).
 * Documentation : frontend/design-system/README.md · rendu : /design-system (dev).
 */
export { cx } from "./cx";
export * from "./motion";
export { Spinner } from "./Spinner";
export { Button, ButtonLink, buttonClass, type ButtonProps, type ButtonVariant, type ButtonSize } from "./Button";
export {
  CONTROL,
  Input,
  Textarea,
  Select,
  PasswordInput,
  Field,
  TextField,
  TextareaField,
  SelectField,
  Checkbox,
  type FieldControlProps,
} from "./Field";
export { OtpInput } from "./OtpInput";
export { Card, CardHeader, Stat, type CardProps, type CardVariant } from "./Card";
export { Badge, type BadgeTone } from "./Badge";
export { StatusBadge } from "./StatusBadge";
export { Alert, type AlertTone } from "./Alert";
export { Modal, ConfirmDialog } from "./Modal";
export { Tabs, type TabItem } from "./Tabs";
export { DataTable, type Column } from "./DataTable";
export { Avatar, useImageFallback } from "./Avatar";
export { EmptyState } from "./EmptyState";
export {
  Skeleton,
  SkeletonText,
  SkeletonCard,
  SkeletonList,
  SkeletonStats,
  SkeletonTable,
  SkeletonPage,
} from "./Skeleton";
export { PageHeader, BackLink } from "./PageHeader";
export { AppShell, type NavItem } from "./AppShell";
export { CONTAINER, SECTION_Y, Container, Eyebrow, SectionHeading } from "./layout";
