import fs from "node:fs";
import https from "node:https";
import os from "node:os";
import path from "node:path";
import { URL } from "node:url";

const [, , targetUrl, outputPathArg = "quant_runtime/artifacts/naver_strategy.md"] = process.argv;

if (!targetUrl) {
  console.error("usage: node scripts/extract_naver_article.mjs <url> [output-md]");
  process.exit(1);
}

const { chromium } = await import("playwright");

const outputPath = path.resolve(outputPathArg);
const outputDir = path.dirname(outputPath);
const outputStem = path.basename(outputPath, path.extname(outputPath));
const crawlRoot = path.join(outputDir, `${outputStem}_crawl`);
const pagesDir = path.join(crawlRoot, "pages");
const assetsRootDir = path.join(crawlRoot, "assets");

fs.mkdirSync(outputDir, { recursive: true });
fs.mkdirSync(crawlRoot, { recursive: true });
fs.mkdirSync(pagesDir, { recursive: true });
fs.mkdirSync(assetsRootDir, { recursive: true });

const chromeProfileRoot = path.join(os.homedir(), "Library", "Application Support", "Google", "Chrome");
const sourceProfile = path.join(chromeProfileRoot, "Default");
const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "naver-profile-"));
const tempProfile = path.join(tempRoot, "Default");

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyDir(srcPath, destPath);
    } else if (entry.isSymbolicLink()) {
      continue;
    } else {
      try {
        fs.copyFileSync(srcPath, destPath);
      } catch {
        // Best-effort copy for locked browser files.
      }
    }
  }
}

function cleanText(value) {
  return (value || "")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]+\n/g, "\n")
    .trim();
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

function slugify(value, fallback = "page") {
  const normalized = cleanText(value)
    .toLowerCase()
    .replace(/[^a-z0-9가-힣]+/gi, "-")
    .replace(/^-+|-+$/g, "");
  return normalized || fallback;
}

function shouldFollowLink(href) {
  if (!href) {
    return false;
  }
  try {
    const url = new URL(href);
    return (
      url.protocol.startsWith("http") &&
      (url.hostname.endsWith("naver.com") || url.hostname.endsWith("naver.me"))
    );
  } catch {
    return false;
  }
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

if (!fs.existsSync(sourceProfile)) {
  console.error(`Chrome profile not found: ${sourceProfile}`);
  process.exit(1);
}

copyDir(sourceProfile, tempProfile);

const browser = await chromium.launchPersistentContext(tempRoot, {
  channel: "chrome",
  headless: false,
  viewport: { width: 1440, height: 1600 },
});

async function extractCurrentPage(page, pageIndex) {
  await page.waitForTimeout(3000);
  for (let idx = 0; idx < 25; idx += 1) {
    await page.evaluate(() => window.scrollBy(0, window.innerHeight * 0.9));
    await page.waitForTimeout(700);
  }

  const extracted = await page.evaluate(() => {
    const selectors = [
      ".se-main-container",
      "#postViewArea",
      "article",
      "[class*='article']",
      "[class*='Article']",
      "[class*='content']",
      "main",
      "body",
    ];

    let bestText = "";
    let bestSelector = "body";
    let bestNode = document.body;
    for (const selector of selectors) {
      const nodes = Array.from(document.querySelectorAll(selector));
      for (const node of nodes) {
        const text = (node.innerText || "")
          .replace(/\n{3,}/g, "\n\n")
          .replace(/[ \t]+\n/g, "\n")
          .trim();
        if (text.length > bestText.length) {
          bestText = text;
          bestSelector = selector;
          bestNode = node;
        }
      }
    }

    const images = Array.from(bestNode.querySelectorAll("img"))
      .map((img, index) => {
        const figure = img.closest("figure");
        const caption =
          (figure?.querySelector("figcaption")?.innerText || "").trim() ||
          (img.parentElement?.querySelector("figcaption")?.innerText || "").trim() ||
          "";
        return {
          index,
          src: img.currentSrc || img.src || "",
          alt: (img.alt || "").trim(),
          title: (img.title || "").trim(),
          caption,
          width: img.naturalWidth || 0,
          height: img.naturalHeight || 0,
        };
      })
      .filter((item) => item.src);

    const links = Array.from(document.querySelectorAll("a[href]"))
      .map((anchor) => ({
        href: anchor.href,
        text: (anchor.innerText || anchor.textContent || "").trim(),
      }))
      .filter((item) => item.href);

    const title =
      (document.querySelector("h1")?.innerText || "").trim() ||
      document.title.trim();

    return {
      title,
      body: bestText || (document.body?.innerText || "").trim(),
      selector: bestSelector,
      url: location.href,
      images,
      links,
    };
  });

  const pageSlug = slugify(extracted.title, `page-${pageIndex + 1}`);
  const pageDir = path.join(pagesDir, `${String(pageIndex + 1).padStart(2, "0")}-${pageSlug}`);
  const pageAssetsDir = path.join(pageDir, "assets");
  fs.mkdirSync(pageDir, { recursive: true });
  fs.mkdirSync(pageAssetsDir, { recursive: true });

  const savedImages = [];
  for (const image of extracted.images) {
    try {
      if (image.src.startsWith("data:")) {
        const match = image.src.match(/^data:(image\/[a-zA-Z0-9.+-]+);base64,(.+)$/);
        if (!match) {
          continue;
        }
        const subtype = match[1].split("/")[1].replace(/[^a-z0-9]/gi, "") || "png";
        const filename = `image_${String(image.index).padStart(2, "0")}.${subtype}`;
        const destPath = path.join(pageAssetsDir, filename);
        fs.writeFileSync(destPath, Buffer.from(match[2], "base64"));
        savedImages.push({ ...image, localPath: destPath, filename });
        continue;
      }
      const filename = `image_${String(image.index).padStart(2, "0")}${extensionFromUrl(image.src)}`;
      const destPath = path.join(pageAssetsDir, filename);
      await downloadBinary(image.src, destPath);
      savedImages.push({ ...image, localPath: destPath, filename });
    } catch (error) {
      savedImages.push({ ...image, localPath: "", filename: "", error: String(error) });
    }
  }

  const screenshotPath = path.join(pageDir, "page.png");
  await page.screenshot({ path: screenshotPath, fullPage: true });

  const followedLinks = extracted.links.filter((item) => shouldFollowLink(item.href));

  const markdown = [
    `# ${cleanText(extracted.title) || `Page ${pageIndex + 1}`}`,
    "",
    `- URL: ${extracted.url}`,
    `- Extracted from selector: ${extracted.selector}`,
    `- Screenshot: ${screenshotPath}`,
    `- Saved image count: ${savedImages.filter((item) => item.localPath).length}`,
    `- Discovered internal links: ${followedLinks.length}`,
    "",
    "## Images",
    "",
    ...savedImages.flatMap((image) => {
      const lines = [];
      const label = cleanText(image.caption) || cleanText(image.alt) || cleanText(image.title) || `Image ${image.index + 1}`;
      lines.push(`### ${label}`);
      lines.push("");
      lines.push(`- Source: ${image.src}`);
      if (image.localPath) {
        lines.push(`- Local: ${image.localPath}`);
        lines.push("");
        lines.push(`![${label}](${image.localPath})`);
      } else {
        lines.push(`- Download: failed`);
        if (image.error) {
          lines.push(`- Error: ${image.error}`);
        }
      }
      lines.push("");
      return lines;
    }),
    "## Links",
    "",
    ...followedLinks.map((item) => `- [${cleanText(item.text) || item.href}](${item.href})`),
    "",
    "## Body",
    "",
    cleanText(extracted.body),
    "",
  ].join("\n");

  const markdownPath = path.join(pageDir, "content.md");
  fs.writeFileSync(markdownPath, markdown, "utf-8");

  return {
    title: cleanText(extracted.title) || `Page ${pageIndex + 1}`,
    url: extracted.url,
    selector: extracted.selector,
    markdownPath,
    screenshotPath,
    pageDir,
    pageSlug,
    links: followedLinks,
  };
}

const page = browser.pages()[0] ?? (await browser.newPage());
const queue = [targetUrl];
const visited = new Set();
const pageResults = [];
const maxPages = 25;

while (queue.length > 0 && pageResults.length < maxPages) {
  const nextUrl = queue.shift();
  if (!nextUrl || visited.has(nextUrl)) {
    continue;
  }
  visited.add(nextUrl);
  await page.goto(nextUrl, { waitUntil: "domcontentloaded", timeout: 120000 });
  const result = await extractCurrentPage(page, pageResults.length);
  pageResults.push(result);
  for (const link of result.links) {
    if (!visited.has(link.href) && !queue.includes(link.href)) {
      queue.push(link.href);
    }
  }
}

const coverScreenshotPath = outputPath.replace(/\.md$/i, ".png");
await page.screenshot({ path: coverScreenshotPath, fullPage: true });

const indexMarkdown = [
  `# Naver Crawl Index`,
  "",
  `- Start URL: ${targetUrl}`,
  `- Page count: ${pageResults.length}`,
  `- Cover screenshot: ${coverScreenshotPath}`,
  `- Crawl root: ${crawlRoot}`,
  "",
  "## Pages",
  "",
  ...pageResults.flatMap((result, index) => [
    `### ${index + 1}. ${result.title}`,
    `- URL: ${result.url}`,
    `- Markdown: ${result.markdownPath}`,
    `- Screenshot: ${result.screenshotPath}`,
    "",
  ]),
].join("\n");

fs.writeFileSync(outputPath, indexMarkdown, "utf-8");

console.log(outputPath);
await browser.close();
