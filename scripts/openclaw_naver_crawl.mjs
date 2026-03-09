import fs from "node:fs";
import https from "node:https";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { URL } from "node:url";

const [, , targetUrl, outputPathArg = "quant_runtime/artifacts/openclaw_naver_strategy.md"] = process.argv;

if (!targetUrl) {
  console.error("usage: node scripts/openclaw_naver_crawl.mjs <url> [output-md]");
  process.exit(1);
}

const outputPath = path.resolve(outputPathArg);
const outputDir = path.dirname(outputPath);
const stem = path.basename(outputPath, path.extname(outputPath));
const crawlDir = path.join(outputDir, `${stem}_crawl`);
const pagesDir = path.join(crawlDir, "pages");
fs.mkdirSync(pagesDir, { recursive: true });
const statePath = path.join(crawlDir, "crawl_state.json");

function runOpenClaw(args) {
  const raw = execFileSync("openclaw", args, {
    cwd: process.cwd(),
    encoding: "utf-8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  return JSON.parse(raw);
}

function cleanText(value) {
  return (value || "")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]+\n/g, "\n")
    .trim();
}

function slugify(value, fallback = "page") {
  const normalized = cleanText(value)
    .toLowerCase()
    .replace(/[^a-z0-9가-힣]+/gi, "-")
    .replace(/^-+|-+$/g, "");
  return normalized || fallback;
}

function parsePageNumber(dirName) {
  const match = dirName.match(/^(\d+)-/);
  return match ? Number(match[1]) : null;
}

function shouldFollowLink(href) {
  try {
    const url = new URL(href);
    if (!url.hostname.includes("contents.premium.naver.com")) {
      return false;
    }
    if (!url.pathname.includes("/gten/gtengten")) {
      return false;
    }
    if (url.pathname.includes("/comment/")) {
      return false;
    }
    if (url.pathname.includes("/subscriptions/")) {
      return false;
    }
    if (url.pathname.endsWith("/search")) {
      return false;
    }
    if (!url.pathname.includes("/contents/")) {
      return false;
    }
    return true;
  } catch {
    return false;
  }
}

function canonicalizeUrl(href) {
  const url = new URL(href);
  url.hash = "";
  if (url.pathname.includes("/contents/")) {
    url.search = "";
  }
  return url.toString();
}

function linkPriority(link) {
  const text = cleanText(link.text || "");
  let score = 0;
  if (link.href.includes("/contents/")) {
    score += 100;
  }
  if (text.length >= 8) {
    score += 20;
  }
  if (/비트코인|이더리움|전략|시황|지표|거시|심리|매수|매도|온체인/i.test(text)) {
    score += 30;
  }
  if (/like|댓글|공유하기|전체 댓글|구독하기|검색/i.test(text)) {
    score -= 50;
  }
  return score;
}

function loadExistingPages() {
  const byUrl = new Map();
  let maxPageNumber = 0;
  if (!fs.existsSync(pagesDir)) {
    return { byUrl, maxPageNumber };
  }
  for (const entry of fs.readdirSync(pagesDir, { withFileTypes: true })) {
    if (!entry.isDirectory()) {
      continue;
    }
    const pageDir = path.join(pagesDir, entry.name);
    const metaPath = path.join(pageDir, "meta.json");
    const contentPath = path.join(pageDir, "content.md");
    const pageNumber = parsePageNumber(entry.name) ?? 0;
    maxPageNumber = Math.max(maxPageNumber, pageNumber);
    let meta = null;
    if (fs.existsSync(metaPath)) {
      try {
        meta = JSON.parse(fs.readFileSync(metaPath, "utf-8"));
      } catch {
        meta = null;
      }
    }
    if (!meta && fs.existsSync(contentPath)) {
      const text = fs.readFileSync(contentPath, "utf-8");
      const titleLine = text.split("\n").find((line) => line.startsWith("# "));
      const urlLine = text.split("\n").find((line) => line.startsWith("- URL: "));
      if (urlLine) {
        meta = {
          title: titleLine ? titleLine.replace(/^# /, "").trim() : entry.name,
          url: urlLine.replace(/^- URL:\s*/, "").trim(),
          links: [],
        };
      }
    }
    if (!meta || !meta.url) {
      continue;
    }
    const canonicalUrl = canonicalizeUrl(meta.url);
    byUrl.set(canonicalUrl, {
      pageDir,
      pageNumber,
      title: meta.title || entry.name,
      url: canonicalUrl,
      links: Array.isArray(meta.links) ? meta.links : [],
    });
  }
  return { byUrl, maxPageNumber };
}

function loadExistingState() {
  if (!fs.existsSync(statePath)) {
    return { queue: [], visited: [] };
  }
  try {
    return JSON.parse(fs.readFileSync(statePath, "utf-8"));
  } catch {
    return { queue: [], visited: [] };
  }
}

function saveState({ queue, visited }) {
  fs.writeFileSync(
    statePath,
    JSON.stringify(
      {
        queue,
        visited: Array.from(visited),
      },
      null,
      2,
    ),
    "utf-8",
  );
}

function extensionFromUrl(value) {
  try {
    const pathname = new URL(value).pathname;
    const ext = path.extname(pathname).toLowerCase();
    if (ext && ext.length <= 5) {
      return ext;
    }
  } catch {
    // ignore
  }
  return ".jpg";
}

async function downloadBinary(url, destPath) {
  return new Promise((resolve, reject) => {
    const request = https.get(url, (response) => {
      if (response.statusCode && response.statusCode >= 400) {
        reject(new Error(`download failed: ${url} status=${response.statusCode}`));
        return;
      }
      const file = fs.createWriteStream(destPath);
      response.pipe(file);
      file.on("finish", () => {
        file.close();
        resolve(destPath);
      });
      file.on("error", reject);
    });
    request.on("error", reject);
  });
}

function openPage(url) {
  return runOpenClaw(["browser", "--browser-profile", "openclaw", "open", url, "--json"]);
}

function focusPage(targetId) {
  return runOpenClaw([
    "browser",
    "--browser-profile",
    "openclaw",
    "focus",
    targetId,
    "--json",
  ]);
}

function closePage(targetId) {
  try {
    return runOpenClaw([
      "browser",
      "--browser-profile",
      "openclaw",
      "close",
      targetId,
      "--json",
    ]);
  } catch {
    return null;
  }
}

function waitMs(targetId, ms) {
  return runOpenClaw([
    "browser",
    "--browser-profile",
    "openclaw",
    "wait",
    "--target-id",
    targetId,
    "--time",
    String(ms),
    "--json",
  ]);
}

function evaluate(targetId, fnSource) {
  return runOpenClaw([
    "browser",
    "--browser-profile",
    "openclaw",
    "evaluate",
    "--target-id",
    targetId,
    "--fn",
    fnSource,
    "--json",
  ]);
}

async function extractPage(url, index, existingEntry = null) {
  const opened = openPage(url);
  const targetId = opened.targetId;
  focusPage(targetId);
  console.log(`[OPENCLAW_CRAWL] page=${index + 1} url=${url}`);
  waitMs(targetId, 4000);
  for (let i = 0; i < 15; i += 1) {
    evaluate(
      targetId,
      "() => { window.scrollBy(0, window.innerHeight * 0.9); return window.scrollY; }",
    );
    waitMs(targetId, 700);
  }

  const payload = evaluate(
    targetId,
    `() => {
      const title = (document.querySelector('h1')?.innerText || document.title || '').trim();
      const text = (document.body?.innerText || '').replace(/\\n{3,}/g, '\\n\\n').trim();
      const links = Array.from(document.querySelectorAll('a[href]')).map((a) => ({
        href: a.href,
        text: (a.innerText || a.textContent || '').trim(),
      })).filter((x) => x.href);
      const images = Array.from(document.querySelectorAll('img')).map((img, idx) => ({
        index: idx,
        src: img.currentSrc || img.src || '',
        alt: (img.alt || '').trim(),
        title: (img.title || '').trim(),
      })).filter((x) => x.src);
      return { title, text, links, images, url: location.href };
    }`,
  ).result;

  const pageSlug = slugify(payload.title, `page-${index + 1}`);
  const pageDir =
    existingEntry?.pageDir ??
    path.join(pagesDir, `${String(index + 1).padStart(2, "0")}-${pageSlug}`);
  const assetsDir = path.join(pageDir, "assets");
  fs.mkdirSync(pageDir, { recursive: true });
  fs.mkdirSync(assetsDir, { recursive: true });

  const savedImages = [];
  for (const image of payload.images) {
    try {
      if (String(image.src).startsWith("data:")) {
        continue;
      }
      const filename = `image_${String(image.index).padStart(2, "0")}${extensionFromUrl(image.src)}`;
      const destPath = path.join(assetsDir, filename);
      await downloadBinary(image.src, destPath);
      savedImages.push({ ...image, localPath: destPath });
    } catch (error) {
      savedImages.push({ ...image, localPath: "", error: String(error) });
    }
  }

  const markdownPath = path.join(pageDir, "content.md");
  const markdown = [
    `# ${cleanText(payload.title) || `Page ${index + 1}`}`,
    "",
    `- URL: ${payload.url}`,
    `- Target ID: ${targetId}`,
    `- Saved image count: ${savedImages.filter((img) => img.localPath).length}`,
    "",
    "## Images",
    "",
    ...savedImages.flatMap((image) => [
      `### ${cleanText(image.alt) || cleanText(image.title) || `Image ${image.index + 1}`}`,
      "",
      `- Source: ${image.src}`,
      image.localPath ? `- Local: ${image.localPath}` : `- Local: download failed`,
      "",
    ]),
    "## Body",
    "",
    cleanText(payload.text),
    "",
  ].join("\n");
  fs.writeFileSync(markdownPath, markdown, "utf-8");
  fs.writeFileSync(
    path.join(pageDir, "meta.json"),
    JSON.stringify(
      {
        title: cleanText(payload.title) || `Page ${index + 1}`,
        url: canonicalizeUrl(payload.url),
        links: payload.links
          .filter((item) => shouldFollowLink(item.href))
          .map((item) => ({ href: canonicalizeUrl(item.href), text: cleanText(item.text) })),
      },
      null,
      2,
    ),
    "utf-8",
  );
  closePage(targetId);

  return {
    title: cleanText(payload.title) || `Page ${index + 1}`,
    url: canonicalizeUrl(payload.url),
    markdownPath,
    links: payload.links
      .filter((item) => shouldFollowLink(item.href))
      .map((item) => ({ ...item, href: canonicalizeUrl(item.href) })),
  };
}

const { byUrl: existingPages, maxPageNumber } = loadExistingPages();
const existingState = loadExistingState();
const visited = new Set(existingState.visited || Array.from(existingPages.keys()));
const queue = [];
const queued = new Set();
let nextPageNumber = maxPageNumber;
const results = [];
const maxPages = 120;

function enqueue(url, refresh = false) {
  const canonical = canonicalizeUrl(url);
  const key = `${canonical}|${refresh ? "refresh" : "normal"}`;
  if (queued.has(key)) {
    return;
  }
  queued.add(key);
  queue.push({ url: canonical, refresh, priority: refresh ? 999 : 0 });
}

enqueue(targetUrl, true);
for (const item of existingState.queue || []) {
  enqueue(item.url || item, false);
}
for (const entry of existingPages.values()) {
  for (const link of entry.links || []) {
    enqueue(link.href || link, false);
  }
}

while (queue.length > 0 && results.length < maxPages) {
  const currentEntry = queue.shift();
  const current = currentEntry?.url;
  if (!current) {
    continue;
  }
  const normalizedCurrent = canonicalizeUrl(current);
  const existingEntry = existingPages.get(normalizedCurrent) || null;
  if (visited.has(normalizedCurrent) && !currentEntry?.refresh) {
    continue;
  }
  visited.add(normalizedCurrent);
  const pageNumber = existingEntry?.pageNumber ?? nextPageNumber + 1;
  if (!existingEntry) {
    nextPageNumber = pageNumber;
  }
  const result = await extractPage(current, pageNumber - 1, existingEntry);
  results.push(result);
  existingPages.set(normalizedCurrent, {
    pageDir: existingEntry?.pageDir ?? path.dirname(result.markdownPath),
    pageNumber,
    title: result.title,
    url: result.url,
    links: result.links,
  });
  console.log(`[OPENCLAW_CRAWL] saved=${result.markdownPath}`);
  const prioritizedLinks = [...result.links].sort((a, b) => linkPriority(b) - linkPriority(a));
  for (const link of prioritizedLinks) {
    if (!visited.has(link.href)) {
      const canonical = canonicalizeUrl(link.href);
      const key = `${canonical}|normal`;
      if (!queued.has(key)) {
        queue.push({ url: canonical, refresh: false, priority: linkPriority(link) });
        queued.add(key);
      }
    }
  }
  queue.sort((a, b) => (b.priority || 0) - (a.priority || 0));
  saveState({ queue, visited });
  console.log(`[OPENCLAW_CRAWL] queue=${queue.length} visited=${visited.size}`);
}

const indexMarkdown = [
  "# OpenClaw Naver Crawl",
  "",
  `- Start URL: ${targetUrl}`,
  `- Collected pages: ${results.length}`,
  `- Crawl root: ${crawlDir}`,
  "",
  "## Pages",
  "",
  ...results.flatMap((result, idx) => [
    `### ${idx + 1}. ${result.title}`,
    `- URL: ${result.url}`,
    `- Markdown: ${result.markdownPath}`,
    "",
  ]),
].join("\n");

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, indexMarkdown, "utf-8");
console.log(outputPath);
