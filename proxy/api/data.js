// Read the Ice: serves the files the site reads between deploys (Claude's writing, the news index, coverage),
// so pages show new stories within a minute without a rebuild. Read-only, GET only, JSON under three folders,
// cached at Vercel's edge for a minute. Works with a public or a private repo: set GH_TOKEN (a fine-grained,
// read-only "Contents" token for the one repo) in the Vercel project's environment variables for a private one.
export const config = { runtime: "edge" };

const ALLOW = /^(stories|news|coverage)\/[A-Za-z0-9_\-/.]+\.json$/;
const ORIGINS = [/^https:\/\/(www\.)?readtheice\.app$/, /^https:\/\/tolar-dio\.github\.io$/, /^http:\/\/localhost(:\d+)?$/];

function cors(origin) {
  const ok = origin && ORIGINS.some((r) => r.test(origin));
  return { "access-control-allow-origin": ok ? origin : "https://readtheice.app", "access-control-allow-methods": "GET, OPTIONS", vary: "origin" };
}

export default async function handler(req) {
  const origin = req.headers.get("origin");
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: { ...cors(origin), "access-control-max-age": "86400" } });
  if (req.method !== "GET") return new Response("GET only", { status: 405, headers: cors(origin) });
  const path = new URL(req.url).searchParams.get("path") || "";
  if (!ALLOW.test(path) || path.includes("..")) return new Response("Not allowed", { status: 404, headers: cors(origin) });
  const repo = process.env.GH_REPO || "Tolar-dio/NHL-Analytics";
  const headers = { "user-agent": "ReadTheIce/1.0 (+https://readtheice.app)" };
  if (process.env.GH_TOKEN) headers.authorization = `Bearer ${process.env.GH_TOKEN}`;
  let up;
  try {
    up = await fetch(`https://raw.githubusercontent.com/${repo}/main/data/${path}`, { headers });
  } catch (e) {
    return new Response("Upstream unreachable", { status: 502, headers: cors(origin) });
  }
  const ok = up.ok, missing = up.status === 404;
  return new Response(ok ? up.body : missing ? "Not found" : "Upstream error", {
    status: ok ? 200 : missing ? 404 : 502,
    headers: {
      ...cors(origin),
      "content-type": ok ? "application/json; charset=utf-8" : "text/plain",
      // missing files are normal (a page asks for a story that hasn't been written yet), so cache those too
      "cache-control": ok || missing ? "public, s-maxage=60, stale-while-revalidate=120" : "no-store",
    },
  });
}
