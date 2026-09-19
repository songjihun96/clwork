import { unwrap } from "@audiobook/api-client";
import { useQuery } from "@tanstack/react-query";

import { api } from "../../services/api";
import { useAuthStore } from "./authStore";

export const meQueryKey = ["users", "me"] as const;

export function useMe() {
  const signedIn = useAuthStore((s) => s.status === "signedIn");
  return useQuery({
    queryKey: meQueryKey,
    queryFn: async () => unwrap(await api.GET("/v1/users/me")),
    enabled: signedIn,
  });
}
