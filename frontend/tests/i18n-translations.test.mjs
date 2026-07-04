import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const mainPath = new URL("../src/main.tsx", import.meta.url);
const apiPath = new URL("../src/lib/api.ts", import.meta.url);
const enLocalePath = new URL("../src/i18n/locales/en.json", import.meta.url);
const zhLocalePath = new URL("../src/i18n/locales/zh-CN.json", import.meta.url);

test("frontend uses the upstream react-i18next runtime", async () => {
  const source = await readFile(mainPath, "utf8");

  assert.doesNotMatch(source, /DomTranslator/);
  assert.doesNotMatch(source, /I18nProvider/);
});

test("ranking navigation has locale entries", async () => {
  const en = JSON.parse(await readFile(enLocalePath, "utf8"));
  const zh = JSON.parse(await readFile(zhLocalePath, "utf8"));

  assert.equal(en.layout.ranking, "Ranking");
  assert.equal(zh.layout.ranking, "成交排行");
});

test("RankingItem type is declared once", async () => {
  const source = await readFile(apiPath, "utf8");
  const matches = source.match(/export interface RankingItem/g) ?? [];

  assert.equal(matches.length, 1);
});
