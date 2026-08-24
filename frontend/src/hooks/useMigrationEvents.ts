import { useEffect, useState } from "react";

import { eventUrl } from "../api/client";

export interface MigrationEvent {
  type: string;
  payload: Record<string, unknown>;
}

export function useMigrationEvents(token: string | null, migrationId: string | null) {
  const [events, setEvents] = useState<MigrationEvent[]>([]);

  useEffect(() => {
    if (!token || !migrationId) {
      return;
    }

    let cancelled = false;
    void fetch(eventUrl(migrationId))
      .then((response) => response.text())
      .then((body) => {
        if (cancelled) {
          return;
        }
        const dataLine = body.split("\n").find((line) => line.startsWith("data: "));
        if (!dataLine) {
          return;
        }
        const parsed = JSON.parse(dataLine.replace("data: ", "")) as MigrationEvent;
        setEvents((current) => [parsed, ...current].slice(0, 8));
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
    };
  }, [migrationId, token]);

  return events;
}
