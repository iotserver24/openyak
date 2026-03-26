"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { API, queryKeys } from "@/lib/constants";
import type { ChannelsResponse, OpenClawStatus } from "@/types/channels";

export function useChannels() {
  return useQuery({
    queryKey: queryKeys.channels,
    queryFn: () => api.get<ChannelsResponse>(API.CHANNELS.LIST),
    staleTime: 10_000,
    refetchInterval: 30_000,
  });
}

export function useOpenClawStatus() {
  return useQuery({
    queryKey: queryKeys.openclawStatus,
    queryFn: () => api.get<OpenClawStatus>(API.CHANNELS.OPENCLAW_STATUS),
    refetchInterval: 10_000,
  });
}

export function useOpenClawStart() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ status: string }>(API.CHANNELS.OPENCLAW_START),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.openclawStatus });
      qc.invalidateQueries({ queryKey: queryKeys.channels });
    },
  });
}

export function useOpenClawStop() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ status: string }>(API.CHANNELS.OPENCLAW_STOP),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.openclawStatus });
      qc.invalidateQueries({ queryKey: queryKeys.channels });
    },
  });
}

export function useAddChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, string>) =>
      api.post<{ ok: boolean; message: string }>(API.CHANNELS.ADD, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.channels });
    },
  });
}

export function useRemoveChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { channel: string; account?: string }) =>
      api.post<{ ok: boolean; message: string }>(API.CHANNELS.REMOVE, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.channels });
    },
  });
}
