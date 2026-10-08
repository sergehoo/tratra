import type { Metadata } from "next";
import { notFound } from "next/navigation";
import Styleguide from "./Styleguide";

export const metadata: Metadata = {
  title: "Design System",
  robots: { index: false, follow: false },
};

/** Guide de style vivant : disponible en développement uniquement (404 en production). */
export default function DesignSystemPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <Styleguide />;
}
