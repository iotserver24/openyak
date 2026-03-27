"use client";

import { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useSidebarStore } from "@/stores/sidebar-store";

export function SidebarNav() {
  const { t } = useTranslation("common");
  const { isSearchOpen, toggleSearch, searchQuery, setSearchQuery } =
    useSidebarStore();
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-focus search input when opened
  useEffect(() => {
    if (isSearchOpen) {
      // Small delay to let animation start before focusing
      const timer = setTimeout(() => inputRef.current?.focus(), 50);
      return () => clearTimeout(timer);
    }
  }, [isSearchOpen]);

  return (
    <nav className="flex flex-col gap-0.5 px-2 pt-1 pb-2">
      {/* Search toggle */}
      <button
        type="button"
        onClick={toggleSearch}
        className={cn(
          "flex items-center gap-3 rounded-xl px-3 py-2 text-[13px] transition-all duration-150 ease-out",
          isSearchOpen
            ? "bg-[var(--sidebar-active)] text-[var(--text-primary)] shadow-[var(--sidebar-active-shadow)] ring-1 ring-[var(--sidebar-active-border)]"
            : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] active:scale-[0.98]",
        )}
      >
        <Search className="h-[18px] w-[18px] shrink-0" />
        <span>{t("searchChats")}</span>
      </button>

      {/* Collapsible search input */}
      <AnimatePresence initial={false}>
        {isSearchOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15, ease: "easeOut" }}
            className="overflow-hidden"
          >
            <div className="px-1 py-1">
              <input
                ref={inputRef}
                type="search"
                name="sidebar-search"
                placeholder={t("searchConversations")}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                autoComplete="one-time-code"
                data-form-type="other"
                className="w-full rounded-lg bg-[var(--surface-secondary)] py-2 pl-3 pr-3 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none focus:ring-1 focus:ring-[var(--ring)] transition-shadow"
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Divider before chat list */}
      <div className="mt-1 border-b border-[var(--border-default)] opacity-50" />
    </nav>
  );
}
