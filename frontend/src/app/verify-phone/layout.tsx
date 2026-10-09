import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Vérifier mon téléphone",
  description: "Confirmez votre numéro de téléphone par un code reçu par SMS.",
  robots: { index: false, follow: false },
};

export default function VerifyPhoneLayout({ children }: { children: ReactNode }) {
  return children;
}
