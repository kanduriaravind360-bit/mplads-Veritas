import { keepPreviousData, QueryClient, useQuery, type UseQueryOptions } from "@tanstack/react-query";
import { api, ApiError, qs, type Params } from "@/lib/api";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
      // Retry network hiccups and timeouts, never an auth or validation error.
      retry: (failures, error) =>
        failures < 2 && error instanceof ApiError && (error.status <= 0 || error.status >= 500),
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 4000),
    },
  },
});

/** GET an API path; the path and params form the cache key. */
export function useApi<T>(
  path: string | null,
  params?: Params,
  options: Omit<UseQueryOptions<T, ApiError>, "queryKey" | "queryFn"> = {},
) {
  const url = path ? `${path}${qs(params)}` : "";
  return useQuery<T, ApiError>({
    queryKey: [url],
    queryFn: ({ signal }) => api<T>(url, { signal }),
    enabled: !!path && (options.enabled ?? true),
    placeholderData: keepPreviousData,
    ...options,
  });
}
