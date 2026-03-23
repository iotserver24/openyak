"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  Loader2,
  AlertCircle,
  Trash2,
  Download,
  HardDrive,
  Play,
  Square,
  RefreshCw,
  Search,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import { API, queryKeys, getBackendUrl } from "@/lib/constants";
import { useSettingsStore } from "@/stores/settings-store";
import { cn } from "@/lib/utils";

// ── Types ────────────────────────────────────────────────────────────────

interface OllamaRuntimeStatus {
  binary_installed: boolean;
  running: boolean;
  port: number;
  base_url: string | null;
  version: string | null;
  models_dir: string | null;
  disk_usage_bytes: number;
}

interface OllamaModel {
  name: string;
  size: number;
  digest: string;
  details?: {
    parameter_size?: string;
    quantization_level?: string;
    family?: string;
  };
}

interface LibraryModel {
  name: string;
  category: string;
  sizes: string[];
  desc: string;
  provider: string;
  pulls?: number;
  pulls_formatted?: string;
  capabilities?: string[];
}

interface LibraryData {
  categories: string[];
  models: LibraryModel[];
  has_more?: boolean;
  page?: number;
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

// ── Main Component ───────────────────────────────────────────────────────

export function OllamaPanel() {
  const { t } = useTranslation("settings");
  const qc = useQueryClient();
  const { setActiveProvider } = useSettingsStore();

  // Runtime status
  const { data: runtimeStatus, refetch: refetchStatus } = useQuery({
    queryKey: ["ollamaRuntime"],
    queryFn: () => api.get<OllamaRuntimeStatus>(API.OLLAMA.STATUS),
    refetchInterval: 10_000, // Poll every 10s
  });

  // Installed models
  const { data: installedModels, refetch: refetchModels } = useQuery({
    queryKey: ["ollamaInstalledModels"],
    queryFn: () => api.get<{ models: OllamaModel[] }>(API.OLLAMA.MODELS),
    enabled: !!runtimeStatus?.running,
  });

  // Library
  const { data: library } = useQuery({
    queryKey: ["ollamaLibrary"],
    queryFn: () => api.get<LibraryData>(API.OLLAMA.LIBRARY),
  });

  const isSetup = runtimeStatus?.binary_installed && runtimeStatus?.running;

  if (!runtimeStatus) {
    return (
      <div className="flex items-center gap-2 py-4">
        <Loader2 className="h-4 w-4 animate-spin text-[var(--text-tertiary)]" />
        <span className="text-xs text-[var(--text-secondary)]">Loading...</span>
      </div>
    );
  }

  if (!runtimeStatus.binary_installed) {
    return (
      <SetupFlow
        onComplete={() => {
          refetchStatus();
          setActiveProvider("ollama");
          qc.invalidateQueries({ queryKey: queryKeys.models });
        }}
      />
    );
  }

  const handleRemoved = () => {
    refetchStatus();
    qc.invalidateQueries({ queryKey: queryKeys.models });
    setActiveProvider(null);
  };

  if (!runtimeStatus.running) {
    return (
      <NotRunningPanel
        runtimeStatus={runtimeStatus}
        onStarted={() => {
          refetchStatus();
          refetchModels();
          setActiveProvider("ollama");
          qc.invalidateQueries({ queryKey: queryKeys.models });
        }}
        onRemoved={handleRemoved}
      />
    );
  }

  return (
    <div className="space-y-4">
      {/* Status bar */}
      <StatusBar
        status={runtimeStatus}
        onStop={() => {
          refetchStatus();
          qc.invalidateQueries({ queryKey: queryKeys.models });
        }}
        onRemoved={handleRemoved}
      />

      {/* Installed models */}
      <InstalledModelsList
        models={installedModels?.models ?? []}
        onDeleted={() => {
          refetchModels();
          qc.invalidateQueries({ queryKey: queryKeys.models });
        }}
      />

      {/* Model library browser */}
      {library && (
        <ModelLibrary
          library={library}
          installedNames={new Set((installedModels?.models ?? []).map((m) => m.name))}
          onPulled={() => {
            refetchModels();
            refetchStatus();
            qc.invalidateQueries({ queryKey: queryKeys.models });
          }}
        />
      )}
    </div>
  );
}

// ── Setup Flow ───────────────────────────────────────────────────────────

function SetupFlow({ onComplete }: { onComplete: () => void }) {
  const { t } = useTranslation("settings");
  const [progress, setProgress] = useState<{
    status: string;
    completed?: number;
    total?: number;
    message?: string;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const startSetup = async () => {
    setError(null);
    setProgress({ status: "starting" });

    try {
      const backendUrl = await getBackendUrl();
      const resp = await fetch(`${backendUrl}${API.OLLAMA.SETUP}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });

      if (!resp.ok || !resp.body) {
        setError("Failed to start setup");
        setProgress(null);
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6));
              setProgress(data);
              if (data.status === "error") {
                setError(data.message || "Setup failed");
                return;
              }
              if (data.status === "ready") {
                onComplete();
                return;
              }
            } catch {
              // ignore parse errors
            }
          }
        }
      }
    } catch (e) {
      setError(String(e));
      setProgress(null);
    }
  };

  const downloadPercent =
    progress?.total && progress.total > 0
      ? Math.round((progress.completed ?? 0) / progress.total * 100)
      : 0;

  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--text-secondary)]">
        {t("ollamaSetupDesc", "Ollama lets you run AI models locally on your computer. Set up takes about a minute.")}
      </p>

      {!progress ? (
        <Button variant="outline" size="sm" onClick={startSetup}>
          <Download className="h-3.5 w-3.5 mr-1.5" />
          {t("ollamaSetup", "Set Up Ollama")}
          <span className="ml-1.5 text-[var(--text-tertiary)]">(~100 MB)</span>
        </Button>
      ) : (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            <span>
              {progress.status === "downloading"
                ? `Downloading... ${downloadPercent}%`
                : progress.status === "extracting"
                  ? "Extracting..."
                  : progress.status === "starting"
                    ? "Starting Ollama..."
                    : progress.status}
            </span>
          </div>
          {progress.status === "downloading" && progress.total && progress.total > 0 && (
            <div className="w-full bg-[var(--surface-tertiary)] rounded-full h-1.5">
              <div
                className="bg-[var(--brand-primary)] h-1.5 rounded-full transition-all duration-300"
                style={{ width: `${downloadPercent}%` }}
              />
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="flex items-center gap-1.5 text-xs text-[var(--color-destructive)]">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
}

// ── Not Running Panel ────────────────────────────────────────────────────

function NotRunningPanel({
  runtimeStatus,
  onStarted,
  onRemoved,
}: {
  runtimeStatus: OllamaRuntimeStatus;
  onStarted: () => void;
  onRemoved: () => void;
}) {
  const { t } = useTranslation("settings");
  const [showRemoveConfirm, setShowRemoveConfirm] = useState(false);
  const [deleteModels, setDeleteModels] = useState(true);

  const startMutation = useMutation({
    mutationFn: () => api.post(API.OLLAMA.START, {}),
    onSuccess: () => onStarted(),
  });

  const removeMutation = useMutation({
    mutationFn: () =>
      api.delete(API.OLLAMA.UNINSTALL(deleteModels)),
    onSuccess: () => {
      setShowRemoveConfirm(false);
      onRemoved();
    },
  });

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-[var(--color-warning)]/30 bg-[var(--color-warning)]/5 p-3">
        <div className="flex items-center gap-2 text-xs">
          <Square className="h-3.5 w-3.5 text-[var(--color-warning)]" />
          <span className="text-[var(--text-secondary)]">
            {t("ollamaStopped", "Ollama is installed but not running")}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => startMutation.mutate()}
          disabled={startMutation.isPending}
        >
          {startMutation.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
          ) : (
            <Play className="h-3.5 w-3.5 mr-1.5" />
          )}
          {t("ollamaStart", "Start Ollama")}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="text-[var(--text-tertiary)] hover:text-[var(--color-destructive)]"
          onClick={() => setShowRemoveConfirm(true)}
        >
          <Trash2 className="h-3.5 w-3.5 mr-1.5" />
          {t("ollamaRemove", "Remove")}
        </Button>
      </div>
      {startMutation.isError && (
        <div className="flex items-center gap-1.5 text-xs text-[var(--color-destructive)]">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
          <span>
            {startMutation.error instanceof ApiError
              ? ((startMutation.error.body as any)?.detail ?? "Failed to start")
              : "Failed to start Ollama"}
          </span>
        </div>
      )}

      {showRemoveConfirm && (
        <RemoveConfirmation
          diskUsage={runtimeStatus.disk_usage_bytes}
          deleteModels={deleteModels}
          setDeleteModels={setDeleteModels}
          isPending={removeMutation.isPending}
          onConfirm={() => removeMutation.mutate()}
          onCancel={() => setShowRemoveConfirm(false)}
        />
      )}
    </div>
  );
}

// ── Status Bar ───────────────────────────────────────────────────────────

function StatusBar({
  status,
  onStop,
  onRemoved,
}: {
  status: OllamaRuntimeStatus;
  onStop: () => void;
  onRemoved: () => void;
}) {
  const { t } = useTranslation("settings");
  const [showRemoveConfirm, setShowRemoveConfirm] = useState(false);
  const [deleteModels, setDeleteModels] = useState(true);

  const stopMutation = useMutation({
    mutationFn: () => api.post(API.OLLAMA.STOP, {}),
    onSuccess: () => onStop(),
  });

  const removeMutation = useMutation({
    mutationFn: () =>
      api.delete(API.OLLAMA.UNINSTALL(deleteModels)),
    onSuccess: () => {
      setShowRemoveConfirm(false);
      onRemoved();
    },
  });

  return (
    <div className="space-y-2">
      <div className="rounded-lg border border-[var(--border-default)] p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[var(--color-success)]" />
            <span className="text-xs font-medium text-[var(--text-primary)]">
              Ollama {status.version && `v${status.version}`}
            </span>
          </div>
          <div className="flex items-center gap-3 text-[10px] text-[var(--text-tertiary)]">
            <span className="flex items-center gap-1">
              <HardDrive className="h-3 w-3" />
              {formatBytes(status.disk_usage_bytes)}
            </span>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-[10px]"
              onClick={() => stopMutation.mutate()}
              disabled={stopMutation.isPending}
              title={t("ollamaStop", "Stop Ollama")}
            >
              {stopMutation.isPending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Square className="h-3 w-3" />
              )}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-[10px] text-[var(--text-tertiary)] hover:text-[var(--color-destructive)]"
              onClick={() => setShowRemoveConfirm(true)}
              title={t("ollamaRemove", "Remove Ollama")}
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          </div>
        </div>
      </div>

      {/* Remove confirmation */}
      {showRemoveConfirm && (
        <RemoveConfirmation
          diskUsage={status.disk_usage_bytes}
          deleteModels={deleteModels}
          setDeleteModels={setDeleteModels}
          isPending={removeMutation.isPending}
          onConfirm={() => removeMutation.mutate()}
          onCancel={() => setShowRemoveConfirm(false)}
        />
      )}
    </div>
  );
}

// ── Remove Confirmation ──────────────────────────────────────────────────

function RemoveConfirmation({
  diskUsage,
  deleteModels,
  setDeleteModels,
  isPending,
  onConfirm,
  onCancel,
}: {
  diskUsage: number;
  deleteModels: boolean;
  setDeleteModels: (v: boolean) => void;
  isPending: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation("settings");

  return (
    <div className="rounded-lg border border-[var(--color-destructive)]/30 bg-[var(--color-destructive)]/5 p-3 space-y-3">
      <p className="text-xs text-[var(--text-secondary)]">
        {t("ollamaRemoveConfirm", "Are you sure you want to remove Ollama? This will stop the server and delete the binary.")}
      </p>
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={deleteModels}
          onChange={(e) => setDeleteModels(e.target.checked)}
          className="rounded border-[var(--border-default)]"
        />
        <span className="text-xs text-[var(--text-secondary)]">
          {t("ollamaDeleteModels", "Also delete all downloaded models")}
          {diskUsage > 0 && (
            <span className="text-[var(--text-tertiary)]"> ({formatBytes(diskUsage)})</span>
          )}
        </span>
      </label>
      <div className="flex items-center gap-2">
        <Button
          variant="destructive"
          size="sm"
          onClick={onConfirm}
          disabled={isPending}
        >
          {isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
          ) : (
            <Trash2 className="h-3.5 w-3.5 mr-1.5" />
          )}
          {t("ollamaRemoveBtn", "Remove Ollama")}
        </Button>
        <Button variant="ghost" size="sm" onClick={onCancel} disabled={isPending}>
          {t("cancel", "Cancel")}
        </Button>
      </div>
    </div>
  );
}

// ── Installed Models List ────────────────────────────────────────────────

function InstalledModelsList({
  models,
  onDeleted,
}: {
  models: OllamaModel[];
  onDeleted: () => void;
}) {
  const { t } = useTranslation("settings");
  const [deletingModel, setDeletingModel] = useState<string | null>(null);

  const deleteMutation = useMutation({
    mutationFn: async (name: string) => {
      setDeletingModel(name);
      return api.delete(API.OLLAMA.DELETE(name));
    },
    onSuccess: () => {
      setDeletingModel(null);
      onDeleted();
    },
    onError: () => setDeletingModel(null),
  });

  if (models.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-[var(--border-default)] p-4 text-center">
        <p className="text-xs text-[var(--text-tertiary)]">
          {t("ollamaNoModels", "No models installed yet. Browse the library below to get started.")}
        </p>
      </div>
    );
  }

  return (
    <div>
      <h3 className="text-xs font-medium text-[var(--text-primary)] mb-2">
        {t("ollamaInstalled", "Installed Models")}
      </h3>
      <div className="space-y-1">
        {models.map((model) => (
          <div
            key={model.name}
            className="flex items-center justify-between rounded-md border border-[var(--border-default)] px-3 py-2"
          >
            <div className="flex items-center gap-2 min-w-0">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-success)] shrink-0" />
              <span className="text-xs font-mono truncate">{model.name}</span>
              <span className="text-[10px] text-[var(--text-tertiary)] shrink-0">
                {formatBytes(model.size)}
              </span>
            </div>
            <button
              onClick={() => deleteMutation.mutate(model.name)}
              disabled={deletingModel === model.name}
              className="text-[var(--text-tertiary)] hover:text-[var(--color-destructive)] transition-colors shrink-0 ml-2"
              title={t("delete", "Delete")}
            >
              {deletingModel === model.name ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Trash2 className="h-3.5 w-3.5" />
              )}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Model Library Browser ────────────────────────────────────────────────

type SortMode = "popular" | "name" | "provider";

function ModelLibrary({
  library,
  installedNames,
  onPulled,
}: {
  library: LibraryData;
  installedNames: Set<string>;
  onPulled: () => void;
}) {
  const { t } = useTranslation("settings");
  const [activeCategory, setActiveCategory] = useState("all");
  const [searchInput, setSearchInput] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [sortBy, setSortBy] = useState<SortMode>("popular");
  const [pullingModel, setPullingModel] = useState<string | null>(null);
  const [pullProgress, setPullProgress] = useState<{
    status: string;
    completed?: number;
    total?: number;
  } | null>(null);
  const [customModel, setCustomModel] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Infinite scroll state
  const [allModels, setAllModels] = useState<LibraryModel[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const sentinelRef = useRef<HTMLDivElement>(null);

  // Debounce search input (400ms)
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setDebouncedQuery(searchInput);
    }, 400);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [searchInput]);

  // Reset pages when search/sort/category changes
  useEffect(() => {
    setPage(1);
    setAllModels([]);
    setHasMore(true);
  }, [debouncedQuery, activeCategory, sortBy]);

  // Fetch page of results
  const { data: libraryData, isLoading: libraryLoading } = useQuery({
    queryKey: ["ollamaLibrary", debouncedQuery, activeCategory, sortBy, page],
    queryFn: () => {
      const params = new URLSearchParams({ sort: sortBy, page: String(page) });
      if (debouncedQuery) params.set("q", debouncedQuery);
      if (activeCategory !== "all") params.set("category", activeCategory);
      return api.get<LibraryData>(`${API.OLLAMA.LIBRARY}?${params.toString()}`);
    },
  });

  // Append new page results to accumulated list
  useEffect(() => {
    if (!libraryData) return;
    setHasMore(!!libraryData.has_more);
    setLoadingMore(false);
    if (page === 1) {
      setAllModels(libraryData.models);
    } else {
      setAllModels((prev) => {
        // Deduplicate by name
        const existing = new Set(prev.map((m) => m.name));
        const newModels = libraryData.models.filter((m) => !existing.has(m.name));
        return [...prev, ...newModels];
      });
    }
  }, [libraryData, page]);

  // IntersectionObserver for infinite scroll
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !loadingMore && !libraryLoading) {
          setLoadingMore(true);
          setPage((p) => p + 1);
        }
      },
      { threshold: 0.1 },
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, loadingMore, libraryLoading]);

  const models = allModels.length > 0 ? allModels : (libraryData?.models ?? library.models);

  const pullAbortRef = useRef<AbortController | null>(null);

  const pullModel = useCallback(
    async (modelName: string) => {
      // Abort any existing pull
      pullAbortRef.current?.abort();
      const abortController = new AbortController();
      pullAbortRef.current = abortController;

      setPullingModel(modelName);
      setPullProgress({ status: "starting" });

      try {
        const backendUrl = await getBackendUrl();
        const resp = await fetch(`${backendUrl}${API.OLLAMA.PULL}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: modelName }),
          signal: abortController.signal,
        });

        if (!resp.ok || !resp.body) {
          setPullProgress(null);
          setPullingModel(null);
          return;
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              try {
                const data = JSON.parse(line.slice(6));
                setPullProgress(data);
                if (data.status === "error") {
                  setTimeout(() => {
                    setPullProgress(null);
                    setPullingModel(null);
                  }, 3000);
                  return;
                }
              } catch {
                // ignore
              }
            }
          }
        }

        setPullProgress(null);
        setPullingModel(null);
        pullAbortRef.current = null;
        onPulled();
      } catch (e) {
        if (e instanceof DOMException && e.name === "AbortError") {
          // User cancelled — clean up silently
        }
        setPullProgress(null);
        setPullingModel(null);
        pullAbortRef.current = null;
      }
    },
    [onPulled],
  );

  const cancelPull = useCallback(() => {
    pullAbortRef.current?.abort();
    pullAbortRef.current = null;
    setPullProgress(null);
    setPullingModel(null);
  }, []);

  const pullPercent =
    pullProgress?.total && pullProgress.total > 0
      ? Math.round(((pullProgress.completed ?? 0) / pullProgress.total) * 100)
      : 0;

  const categories = ["all", ...library.categories];
  const sortOptions: { key: SortMode; label: string }[] = [
    { key: "popular", label: t("sortPopular", "Popular") },
    { key: "name", label: t("sortName", "Name") },
    { key: "provider", label: t("sortProvider", "Provider") },
  ];

  return (
    <div>
      <h3 className="text-xs font-medium text-[var(--text-primary)] mb-2">
        {t("ollamaAddModels", "Add Models")}
      </h3>

      {/* Pull progress banner */}
      {pullingModel && pullProgress && (
        <div className="mb-3 rounded-lg border border-[var(--brand-primary)]/20 bg-[var(--brand-primary)]/5 p-3 space-y-1.5">
          <div className="flex items-center gap-2 text-xs">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--brand-primary)] shrink-0" />
            <span className="text-[var(--text-secondary)] flex-1">
              {pullProgress.status === "error"
                ? `Error: ${(pullProgress as any).message}`
                : `Pulling ${pullingModel}... ${pullProgress.total ? `${pullPercent}%` : pullProgress.status}`}
            </span>
            <button
              onClick={cancelPull}
              className="text-[var(--text-tertiary)] hover:text-[var(--color-destructive)] transition-colors shrink-0"
              title={t("cancel", "Cancel")}
            >
              <Square className="h-3.5 w-3.5" />
            </button>
          </div>
          {pullProgress.total && pullProgress.total > 0 && (
            <div className="w-full bg-[var(--surface-tertiary)] rounded-full h-1.5">
              <div
                className="bg-[var(--brand-primary)] h-1.5 rounded-full transition-all duration-300"
                style={{ width: `${pullPercent}%` }}
              />
            </div>
          )}
        </div>
      )}

      {/* Search + sort + category tabs */}
      <div className="space-y-2 mb-3">
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-[var(--text-tertiary)]" />
            <Input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder={t("ollamaSearch", "Search models...")}
              className="pl-8 text-xs h-8"
            />
          </div>
          {/* Sort buttons */}
          <div className="flex items-center border border-[var(--border-default)] rounded-md overflow-hidden shrink-0">
            {sortOptions.map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setSortBy(key)}
                className={cn(
                  "px-2 py-1 text-[10px] transition-colors",
                  sortBy === key
                    ? "bg-[var(--surface-secondary)] text-[var(--text-primary)] font-medium"
                    : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-1 flex-wrap">
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setActiveCategory(cat)}
              className={cn(
                "px-2.5 py-1 text-[11px] rounded-md transition-colors capitalize",
                activeCategory === cat
                  ? "bg-[var(--surface-secondary)] text-[var(--text-primary)] font-medium"
                  : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]",
              )}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* Model cards */}
      {libraryLoading && page === 1 ? (
        <div className="flex items-center gap-2 py-4 justify-center">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--text-tertiary)]" />
          <span className="text-xs text-[var(--text-tertiary)]">
            {debouncedQuery ? "Searching..." : "Loading..."}
          </span>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 mb-3">
            {models.map((model) => (
              <ModelCard
                key={model.name}
                model={model}
                installedNames={installedNames}
                isPulling={pullingModel !== null}
                onPull={pullModel}
              />
            ))}
          </div>

          {models.length === 0 && !libraryLoading && (
            <p className="text-xs text-[var(--text-tertiary)] text-center py-3">
              {t("ollamaNoResults", "No models match your search.")}
            </p>
          )}

          {/* Infinite scroll sentinel */}
          {hasMore && (
            <div ref={sentinelRef} className="flex items-center justify-center py-3">
              {loadingMore && (
                <Loader2 className="h-4 w-4 animate-spin text-[var(--text-tertiary)]" />
              )}
            </div>
          )}
        </>
      )}

      {/* Custom pull */}
      <div className="pt-2 border-t border-[var(--border-default)]">
        <p className="text-[10px] text-[var(--text-tertiary)] mb-1.5">
          {t("ollamaCustomPull", "Or pull any model by name:")}
        </p>
        <div className="flex items-center gap-2">
          <Input
            type="text"
            value={customModel}
            onChange={(e) => setCustomModel(e.target.value)}
            placeholder="e.g. llama3.2:1b"
            className="font-mono text-xs h-8"
          />
          <Button
            variant="outline"
            size="sm"
            className="h-8"
            onClick={() => {
              if (customModel.trim()) {
                pullModel(customModel.trim());
                setCustomModel("");
              }
            }}
            disabled={!customModel.trim() || pullingModel !== null}
          >
            {t("pull", "Pull")}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── Model Card ───────────────────────────────────────────────────────────

function ModelCard({
  model,
  installedNames,
  isPulling,
  onPull,
}: {
  model: LibraryModel;
  installedNames: Set<string>;
  isPulling: boolean;
  onPull: (name: string) => void;
}) {
  // Check which sizes are installed
  const installedSizes = model.sizes.filter((size) => {
    const fullName = `${model.name}:${size}`;
    return installedNames.has(fullName) || installedNames.has(`${model.name}:latest`);
  });

  return (
    <div className="rounded-lg border border-[var(--border-default)] p-3 space-y-2">
      <div>
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-[var(--text-primary)]">{model.name}</span>
          {(model.pulls_formatted || (model.pulls != null && model.pulls > 0)) && (
            <span className="text-[9px] text-[var(--text-tertiary)]">
              {model.pulls_formatted || `${model.pulls?.toLocaleString()}`} pulls
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          {model.provider && (
            <span className="text-[10px] text-[var(--text-tertiary)]">{model.provider}</span>
          )}
          {model.capabilities?.map((cap) => (
            <span
              key={cap}
              className="text-[9px] px-1 py-px rounded bg-[var(--surface-tertiary)] text-[var(--text-tertiary)]"
            >
              {cap}
            </span>
          ))}
        </div>
      </div>
      {model.desc && (
        <p className="text-[10px] text-[var(--text-secondary)] line-clamp-2">{model.desc}</p>
      )}
      <div className="flex items-center gap-1 flex-wrap">
        {model.sizes.map((size) => {
          const fullName = `${model.name}:${size}`;
          const isInstalled = installedNames.has(fullName);
          return (
            <button
              key={size}
              onClick={() => !isInstalled && !isPulling && onPull(fullName)}
              disabled={isInstalled || isPulling}
              className={cn(
                "px-1.5 py-0.5 text-[10px] rounded border transition-colors",
                isInstalled
                  ? "border-[var(--color-success)]/30 bg-[var(--color-success)]/10 text-[var(--color-success)] cursor-default"
                  : "border-[var(--border-default)] text-[var(--text-secondary)] hover:border-[var(--brand-primary)] hover:text-[var(--brand-primary)] cursor-pointer",
                isPulling && !isInstalled && "opacity-50 cursor-not-allowed",
              )}
              title={isInstalled ? "Installed" : `Pull ${fullName}`}
            >
              {isInstalled && <Check className="h-2.5 w-2.5 inline mr-0.5" />}
              {size}
            </button>
          );
        })}
      </div>
    </div>
  );
}
