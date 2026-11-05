import { useQuery } from "@tanstack/vue-query";

import { recordsClient } from "../api/clients";
import type { components } from "../api/generated/records";

export type Me = components["schemas"]["Me"];

export function useMeQuery() {
  return useQuery({
    queryKey: ["records", "me"],
    queryFn: async (): Promise<Me> => {
      const { data, error } = await recordsClient.GET("/api/records/auth/me/");
      if (error !== undefined || data === undefined) {
        throw new Error("Failed to load your profile.");
      }
      return data;
    },
  });
}

export function canWrite(role: string | null | undefined): boolean {
  return role === "editor" || role === "owner";
}

export function roleIn(me: Me | null | undefined, organizationId: number): string | null {
  return (
    me?.organizations.find((organization) => organization.id === organizationId)?.role ?? null
  );
}
