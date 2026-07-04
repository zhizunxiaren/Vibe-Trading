import { useEffect, useRef } from "react";
import { isKnownChineseTranslation, translateText, type Language } from "@/i18n/translations";
import { useI18n } from "@/i18n/I18nProvider";

const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "CODE", "PRE", "TEXTAREA", "SVG"]);
const ATTRIBUTES = ["title", "placeholder", "aria-label"] as const;

function shouldSkipTextNode(node: Text): boolean {
  const parent = node.parentElement;
  if (!parent) return true;
  return !!parent.closest(Array.from(SKIP_TAGS).join(","));
}

function splitWhitespace(value: string): { leading: string; core: string; trailing: string } {
  const match = value.match(/^(\s*)(.*?)(\s*)$/s);
  return {
    leading: match?.[1] ?? "",
    core: match?.[2] ?? value,
    trailing: match?.[3] ?? "",
  };
}

function nextOriginal(current: string, previousOriginal: string | undefined, language: Language): string {
  if (!previousOriginal) return current;
  if (language === "zh-CN" && current === translateText(previousOriginal, language)) return previousOriginal;
  if (language === "zh-CN" && isKnownChineseTranslation(current)) return previousOriginal;
  return current;
}

export function DomTranslator() {
  const { language } = useI18n();
  const originalTexts = useRef<WeakMap<Text, string>>(new WeakMap());
  const originalAttributes = useRef<WeakMap<Element, Map<string, string>>>(new WeakMap());

  useEffect(() => {
    const translateTextNode = (node: Text) => {
      if (shouldSkipTextNode(node)) return;
      const { leading, core, trailing } = splitWhitespace(node.nodeValue ?? "");
      if (!core.trim()) return;

      const original = nextOriginal(core, originalTexts.current.get(node), language);
      originalTexts.current.set(node, original);
      const nextValue = `${leading}${translateText(original, language)}${trailing}`;
      if (node.nodeValue !== nextValue) {
        node.nodeValue = nextValue;
      }
    };

    const translateElementAttributes = (element: Element) => {
      if (SKIP_TAGS.has(element.tagName)) return;

      let originals = originalAttributes.current.get(element);
      if (!originals) {
        originals = new Map<string, string>();
        originalAttributes.current.set(element, originals);
      }

      for (const attr of ATTRIBUTES) {
        const current = element.getAttribute(attr);
        if (!current) continue;
        const original = nextOriginal(current, originals.get(attr), language);
        originals.set(attr, original);
        const nextValue = translateText(original, language);
        if (current !== nextValue) {
          element.setAttribute(attr, nextValue);
        }
      }
    };

    const translateNode = (root: Node) => {
      if (root.nodeType === Node.TEXT_NODE) {
        translateTextNode(root as Text);
        return;
      }
      if (root.nodeType !== Node.ELEMENT_NODE) return;

      const element = root as Element;
      translateElementAttributes(element);

      const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
      let current = walker.nextNode();
      while (current) {
        translateTextNode(current as Text);
        current = walker.nextNode();
      }

      for (const child of element.querySelectorAll("*")) {
        translateElementAttributes(child);
      }
    };

    translateNode(document.body);

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          translateNode(node);
        }
        if (mutation.type === "characterData") {
          translateNode(mutation.target);
        }
        if (mutation.type === "attributes") {
          translateNode(mutation.target);
        }
      }
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: [...ATTRIBUTES],
    });

    return () => observer.disconnect();
  }, [language]);

  return null;
}
