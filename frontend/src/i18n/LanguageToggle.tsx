import { Languages } from "lucide-react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n/I18nProvider";

interface Props {
  compact?: boolean;
}

export function LanguageToggle({ compact = false }: Props) {
  const { language, setLanguage, t } = useI18n();
  const isChinese = language === "zh-CN";

  if (compact) {
    return (
      <button
        type="button"
        onClick={() => setLanguage(isChinese ? "en-US" : "zh-CN")}
        className="p-1.5 text-muted-foreground hover:text-foreground rounded transition-colors"
        title={t("Language")}
        aria-label={t("Language")}
      >
        <Languages className="h-3.5 w-3.5" />
      </button>
    );
  }

  return (
    <div className="flex items-center justify-between gap-2">
      <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
        <Languages className="h-3.5 w-3.5" />
        {t("Language")}
      </span>
      <div className="inline-grid grid-cols-2 rounded-md border bg-muted/30 p-0.5 text-[11px]">
        <button
          type="button"
          onClick={() => setLanguage("zh-CN")}
          className={cn(
            "rounded px-2 py-0.5 transition-colors",
            isChinese ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {t("Chinese")}
        </button>
        <button
          type="button"
          onClick={() => setLanguage("en-US")}
          className={cn(
            "rounded px-2 py-0.5 transition-colors",
            !isChinese ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}
        >
          EN
        </button>
      </div>
    </div>
  );
}
