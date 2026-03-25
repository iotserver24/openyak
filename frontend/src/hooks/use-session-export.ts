"use client";

import { useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { API, IS_DESKTOP, resolveApiUrl } from "@/lib/constants";

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function parseFilename(res: Response, fallback: string): string {
  const disposition = res.headers.get("Content-Disposition");
  if (!disposition) return fallback;
  const utf8Match = disposition.match(/filename\*=UTF-8''(.+?)(?:;|$)/);
  if (utf8Match) return decodeURIComponent(utf8Match[1]);
  const asciiMatch = disposition.match(/filename="(.+?)"/);
  if (asciiMatch) return asciiMatch[1];
  return fallback;
}

export function useSessionExport() {
  const { t } = useTranslation("common");
  const tRef = useRef(t);
  tRef.current = t;

  const exportPdf = useCallback(async (id: string, title: string) => {
    try {
      const exportUrl = resolveApiUrl(API.SESSIONS.EXPORT_PDF(id));
      if (IS_DESKTOP) {
        const { desktopAPI } = await import("@/lib/tauri-api");
        await desktopAPI.downloadAndSave({ url: exportUrl, defaultName: `${title}.pdf` });
      } else {
        const res = await fetch(exportUrl);
        if (!res.ok) throw new Error("PDF export failed");
        const blob = await res.blob();
        downloadBlob(blob, parseFilename(res, `${title}.pdf`));
      }
    } catch (err) {
      console.error("PDF export failed:", err);
      toast.error(tRef.current("failedExportPdf"));
    }
  }, []);

  const exportMarkdown = useCallback(async (id: string, title: string) => {
    try {
      const exportUrl = resolveApiUrl(API.SESSIONS.EXPORT_MD(id));
      if (IS_DESKTOP) {
        const { desktopAPI } = await import("@/lib/tauri-api");
        await desktopAPI.downloadAndSave({ url: exportUrl, defaultName: `${title}.md` });
      } else {
        const res = await fetch(exportUrl);
        if (!res.ok) throw new Error("Markdown export failed");
        const blob = await res.blob();
        downloadBlob(blob, `${title}.md`);
      }
    } catch (err) {
      console.error("Markdown export failed:", err);
      toast.error(tRef.current("failedExportMarkdown", { defaultValue: "Failed to export Markdown" }));
    }
  }, []);

  return { exportPdf, exportMarkdown };
}
