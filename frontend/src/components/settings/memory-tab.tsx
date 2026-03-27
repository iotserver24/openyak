"use client";

import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Trash2, Pencil, Briefcase, User, Target } from "lucide-react";
import { toast } from "sonner";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  useMemory,
  useMemoryConfig,
  useUpdateMemoryConfig,
  useAddFact,
  useUpdateContext,
  useDeleteFacts,
  useClearMemory,
} from "@/hooks/use-memory";
import type { MemoryCategory, ContextSection } from "@/types/memory";

const CATEGORIES: MemoryCategory[] = ["preference", "knowledge", "context", "behavior", "goal"];
const FACTS_PAGE_SIZE = 20;

const CATEGORY_COLORS: Record<MemoryCategory, string> = {
  preference: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  knowledge: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
  context: "bg-gray-100 text-gray-600 dark:bg-gray-800/50 dark:text-gray-400",
  behavior: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
  goal: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
};

const CONTEXT_SECTIONS: { section: ContextSection; labelKey: string; icon: typeof Briefcase }[] = [
  { section: "work_context", labelKey: "memoryContextWork", icon: Briefcase },
  { section: "personal_context", labelKey: "memoryContextPersonal", icon: User },
  { section: "top_of_mind", labelKey: "memoryContextFocus", icon: Target },
];

// ── Context Card ──────────────────────────────────────────

function ContextCard({
  section,
  labelKey,
  icon: Icon,
  summary,
  onSave,
  saving,
}: {
  section: ContextSection;
  labelKey: string;
  icon: typeof Briefcase;
  summary: string;
  onSave: (section: ContextSection, summary: string) => void;
  saving: boolean;
}) {
  const { t } = useTranslation("settings");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(summary);

  const handleEdit = () => {
    setDraft(summary);
    setEditing(true);
  };

  const handleSave = () => {
    onSave(section, draft);
    setEditing(false);
  };

  const handleCancel = () => {
    setDraft(summary);
    setEditing(false);
  };

  return (
    <div className="rounded-xl border border-[var(--border-default)] p-4 transition-colors hover:border-[var(--border-hover,var(--border-default))]">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-sm font-medium text-[var(--text-primary)]">
          <Icon className="h-4 w-4 text-[var(--text-secondary)]" />
          {t(labelKey)}
        </div>
        {!editing && (
          <button
            onClick={handleEdit}
            className="rounded-lg p-1.5 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-secondary)] transition-colors"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      {editing ? (
        <div className="space-y-2">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={t("memoryContextEditPlaceholder")}
            rows={3}
            className="w-full rounded-lg border border-[var(--border-default)] bg-[var(--surface-primary)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none focus:ring-1 focus:ring-[var(--ring)] resize-none"
          />
          <div className="flex gap-2 justify-end">
            <Button variant="ghost" size="sm" onClick={handleCancel}>
              {t("memoryClearCancel")}
            </Button>
            <Button size="sm" onClick={handleSave} disabled={saving}>
              {t("save")}
            </Button>
          </div>
        </div>
      ) : (
        <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
          {summary || t("memoryContextPlaceholder")}
        </p>
      )}
    </div>
  );
}

// ── Add Fact Form ─────────────────────────────────────────

function AddFactForm({ onAdd, adding }: { onAdd: (content: string, category: MemoryCategory) => void; adding: boolean }) {
  const { t } = useTranslation("settings");
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState("");
  const [category, setCategory] = useState<MemoryCategory>("context");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!content.trim()) return;
    onAdd(content.trim(), category);
    setContent("");
    setOpen(false);
  };

  if (!open) {
    return (
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)} className="gap-1.5">
        <Plus className="h-3.5 w-3.5" />
        {t("memoryAddFact")}
      </Button>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-center gap-2">
      <input
        autoFocus
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder={t("memoryAddFactPlaceholder")}
        className="flex-1 rounded-lg border border-[var(--border-default)] bg-[var(--surface-primary)] px-3 py-1.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none focus:ring-1 focus:ring-[var(--ring)]"
      />
      <Select value={category} onValueChange={(v) => setCategory(v as MemoryCategory)}>
        <SelectTrigger className="w-[120px] h-8 text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {CATEGORIES.map((cat) => (
            <SelectItem key={cat} value={cat}>
              {t(`memoryCategory${cat.charAt(0).toUpperCase() + cat.slice(1)}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button type="submit" size="sm" disabled={!content.trim() || adding}>
        {t("memoryAddFact")}
      </Button>
      <Button type="button" variant="ghost" size="sm" onClick={() => { setOpen(false); setContent(""); }}>
        {t("memoryClearCancel")}
      </Button>
    </form>
  );
}

// ── Main Memory Tab ───────────────────────────────────────

export function MemoryTab() {
  const { t } = useTranslation("settings");
  const { data, isLoading, error } = useMemory();
  const { data: config } = useMemoryConfig();
  const updateConfig = useUpdateMemoryConfig();
  const addFact = useAddFact();
  const updateContext = useUpdateContext();
  const deleteFacts = useDeleteFacts();
  const clearMemory = useClearMemory();
  const memoryEnabled = config?.enabled ?? true;

  const [filter, setFilter] = useState<MemoryCategory | "all">("all");
  const [visibleCount, setVisibleCount] = useState(FACTS_PAGE_SIZE);
  const [clearDialogOpen, setClearDialogOpen] = useState(false);

  const handleUpdateContext = useCallback(
    (section: ContextSection, summary: string) => {
      updateContext.mutate(
        { section, summary },
        { onSuccess: () => toast.success(t("memorySaved")) },
      );
    },
    [updateContext, t],
  );

  const handleAddFact = useCallback(
    (content: string, category: MemoryCategory) => {
      addFact.mutate(
        { content, category },
        { onSuccess: () => toast.success(t("memoryAdded")) },
      );
    },
    [addFact, t],
  );

  const handleDeleteFact = useCallback(
    (id: string) => {
      deleteFacts.mutate([id], {
        onSuccess: () => toast.success(t("memoryDeleted")),
      });
    },
    [deleteFacts, t],
  );

  const handleClearAll = useCallback(() => {
    clearMemory.mutate(undefined, {
      onSuccess: () => {
        toast.success(t("memoryCleared"));
        setClearDialogOpen(false);
      },
    });
  }, [clearMemory, t]);

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-4 w-48" />
        <div className="grid gap-3">
          <Skeleton className="h-24 rounded-xl" />
          <Skeleton className="h-24 rounded-xl" />
          <Skeleton className="h-24 rounded-xl" />
        </div>
        <Skeleton className="h-32 rounded-xl" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-[var(--color-destructive)]/30 bg-[var(--color-destructive)]/5 p-4">
        <p className="text-sm text-[var(--color-destructive)]">
          Failed to load memory: {error instanceof Error ? error.message : "Unknown error"}
        </p>
      </div>
    );
  }

  const contexts = data?.contexts ?? {};
  const facts = data?.facts ?? [];
  const filteredFacts = filter === "all" ? facts : facts.filter((f) => f.category === filter);
  const visibleFacts = filteredFacts.slice(0, visibleCount);
  const hasMore = filteredFacts.length > visibleCount;

  return (
    <div className="space-y-8">
      {/* Header with toggle */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-[var(--text-secondary)] flex-1">{t("memoryDesc")}</p>
        <div className="flex items-center gap-2 ml-4 shrink-0">
          <span className="text-xs text-[var(--text-tertiary)]">
            {memoryEnabled ? t("memoryEnabled") : t("memoryDisabled")}
          </span>
          <Switch
            checked={memoryEnabled}
            onCheckedChange={(checked) => updateConfig.mutate({ enabled: checked })}
          />
        </div>
      </div>

      {/* Context Section */}
      <section>
        <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-3">
          {t("memoryContexts")}
        </h2>
        <div className="grid gap-3">
          {CONTEXT_SECTIONS.map(({ section, labelKey, icon }) => (
            <ContextCard
              key={section}
              section={section}
              labelKey={labelKey}
              icon={icon}
              summary={contexts[section] ?? ""}
              onSave={handleUpdateContext}
              saving={updateContext.isPending}
            />
          ))}
        </div>
      </section>

      <Separator />

      {/* Facts Section */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">
            {t("memoryFacts")}
            {facts.length > 0 && (
              <span className="ml-2 text-xs font-normal text-[var(--text-tertiary)]">
                ({facts.length})
              </span>
            )}
          </h2>
          <AddFactForm onAdd={handleAddFact} adding={addFact.isPending} />
        </div>

        {/* Category filter pills */}
        {facts.length > 0 && (
          <div className="flex gap-1 flex-wrap mb-3">
            {(["all", ...CATEGORIES] as const).map((cat) => (
              <button
                key={cat}
                onClick={() => { setFilter(cat); setVisibleCount(FACTS_PAGE_SIZE); }}
                className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                  filter === cat
                    ? "bg-[var(--brand-primary)] text-[var(--brand-primary-text)]"
                    : "text-[var(--text-secondary)] hover:bg-[var(--surface-secondary)]"
                }`}
              >
                {t(`memoryCategory${cat === "all" ? "All" : cat.charAt(0).toUpperCase() + cat.slice(1)}`)}
              </button>
            ))}
          </div>
        )}

        {/* Fact list */}
        {filteredFacts.length === 0 ? (
          <p className="text-xs text-[var(--text-tertiary)] py-6 text-center">
            {facts.length === 0 ? t("memoryEmptyFacts") : t("memoryEmptyFiltered")}
          </p>
        ) : (
          <div className="space-y-1">
            {visibleFacts.map((fact) => (
              <div
                key={fact.id}
                className="group/fact flex items-start gap-2.5 rounded-lg px-3 py-2 transition-colors hover:bg-[var(--surface-secondary)]"
              >
                <Badge
                  variant="secondary"
                  className={`shrink-0 mt-0.5 text-[10px] px-1.5 py-0 font-medium border-0 ${CATEGORY_COLORS[fact.category]}`}
                >
                  {t(`memoryCategory${fact.category.charAt(0).toUpperCase() + fact.category.slice(1)}`)}
                </Badge>
                <span className="flex-1 text-sm text-[var(--text-primary)] leading-relaxed">
                  {fact.content}
                </span>
                <button
                  onClick={() => handleDeleteFact(fact.id)}
                  className="shrink-0 rounded-lg p-1 text-[var(--text-tertiary)] opacity-0 group-hover/fact:opacity-100 hover:text-[var(--color-destructive)] hover:bg-[var(--color-destructive)]/10 transition-all"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
            {hasMore && (
              <button
                onClick={() => setVisibleCount((c) => c + FACTS_PAGE_SIZE)}
                className="w-full rounded-lg py-2 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-secondary)] transition-colors"
              >
                {t("memoryShowMore", { remaining: filteredFacts.length - visibleCount })}
              </button>
            )}
          </div>
        )}
      </section>

      <Separator />

      {/* Clear All */}
      <section>
        <Button
          variant="ghost"
          size="sm"
          className="text-[var(--color-destructive)] hover:text-[var(--color-destructive)] hover:bg-[var(--color-destructive)]/10"
          onClick={() => setClearDialogOpen(true)}
        >
          {t("memoryClearAll")}
        </Button>
      </section>

      {/* Clear confirmation dialog */}
      <Dialog open={clearDialogOpen} onOpenChange={setClearDialogOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{t("memoryClearConfirmTitle")}</DialogTitle>
            <DialogDescription>{t("memoryClearConfirmDesc")}</DialogDescription>
          </DialogHeader>
          <div className="flex gap-2 justify-end mt-2">
            <Button variant="ghost" size="sm" onClick={() => setClearDialogOpen(false)}>
              {t("memoryClearCancel")}
            </Button>
            <Button
              size="sm"
              className="bg-[var(--color-destructive)] text-white hover:bg-[var(--color-destructive)]/90"
              onClick={handleClearAll}
              disabled={clearMemory.isPending}
            >
              {t("memoryClearConfirm")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
