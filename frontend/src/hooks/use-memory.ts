"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { API, queryKeys } from "@/lib/constants";
import type {
  MemoryResponse,
  MemoryFact,
  AddFactRequest,
  UpdateContextRequest,
  RemoveFactsRequest,
} from "@/types/memory";

export function useMemory() {
  return useQuery({
    queryKey: queryKeys.memory,
    queryFn: () => api.get<MemoryResponse>(API.MEMORY.BASE),
    staleTime: 0,
    refetchOnMount: "always",
  });
}

export function useAddFact() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: AddFactRequest) =>
      api.post<{ added: number }>(API.MEMORY.FACTS, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.memory });
    },
  });
}

export function useUpdateContext() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: UpdateContextRequest) =>
      api.put<{ status: string }>(API.MEMORY.CONTEXTS, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.memory });
    },
  });
}

export function useDeleteFacts() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (factIds: string[]) =>
      api.deleteWithBody<{ removed: number }>(API.MEMORY.FACTS, { fact_ids: factIds } as RemoveFactsRequest),
    onMutate: async (factIds) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.memory });
      const previous = queryClient.getQueryData<MemoryResponse>(queryKeys.memory);
      queryClient.setQueryData<MemoryResponse>(queryKeys.memory, (old) => {
        if (!old) return old;
        return {
          ...old,
          facts: old.facts.filter((f) => !factIds.includes(f.id)),
        };
      });
      return { previous };
    },
    onError: (_err, _ids, context) => {
      if (context?.previous) {
        queryClient.setQueryData(queryKeys.memory, context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.memory });
    },
  });
}

interface MemoryConfigResponse {
  enabled: boolean;
  injection_enabled: boolean;
}

export function useMemoryConfig() {
  return useQuery({
    queryKey: [...queryKeys.memory, "config"],
    queryFn: () => api.get<MemoryConfigResponse>(API.MEMORY.CONFIG),
    staleTime: 0,
    refetchOnMount: "always",
  });
}

export function useUpdateMemoryConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<MemoryConfigResponse>) =>
      api.patch<MemoryConfigResponse>(API.MEMORY.CONFIG, data),
    onSuccess: (data) => {
      queryClient.setQueryData([...queryKeys.memory, "config"], data);
    },
  });
}

export function useClearMemory() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.delete<{ status: string }>(API.MEMORY.BASE),
    onSuccess: () => {
      queryClient.setQueryData<MemoryResponse>(queryKeys.memory, {
        contexts: {},
        facts: [],
      });
    },
  });
}
