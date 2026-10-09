import Link from "next/link";
import { CalendarClock, ChevronRight, MapPin, UserRound, Wrench } from "lucide-react";
import { Card, StatusBadge } from "@/components/ds";
import type { Booking } from "@/lib/types";
import { clientName, formatWhen } from "./format";

/** Mission de la liste : carte cliquable vers le détail (/worker/missions/[id]). */
export function MissionCard({ booking: b }: { booking: Booking }) {
  const when = formatWhen(b.booking_date);
  return (
    <Link
      href={`/worker/missions/${b.id}`}
      className="group block rounded-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
    >
      <Card interactive className="flex items-center gap-4">
        <span
          aria-hidden
          className="grid h-12 w-12 shrink-0 place-items-center rounded-panel bg-primarySoft text-primary transition duration-300 ease-emphasized group-hover:bg-primaryDark group-hover:text-white"
        >
          <Wrench className="h-5 w-5" />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
          <div className="min-w-0">
            <p className="truncate font-display text-base font-bold leading-tight text-ink">
              {b.service_detail?.title ?? `Mission #${b.id}`}
            </p>
            <p className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ash">
              <span className="inline-flex items-center gap-1.5">
                <UserRound aria-hidden className="h-4 w-4 shrink-0" />
                {clientName(b) ?? "Client"}
              </span>
              {b.city ? (
                <span className="inline-flex items-center gap-1.5">
                  <MapPin aria-hidden className="h-4 w-4 shrink-0" />
                  {b.city}
                </span>
              ) : null}
              {when ? (
                <span className="inline-flex items-center gap-1.5">
                  <CalendarClock aria-hidden className="h-4 w-4 shrink-0" />
                  {when}
                </span>
              ) : null}
            </p>
          </div>
          <StatusBadge kind="booking" status={b.status} className="self-start sm:self-auto" />
        </div>
        <ChevronRight
          aria-hidden
          className="h-5 w-5 shrink-0 text-fog transition duration-200 ease-emphasized group-hover:translate-x-0.5 group-hover:text-primary"
        />
      </Card>
    </Link>
  );
}
