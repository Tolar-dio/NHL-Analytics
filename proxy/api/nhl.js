// Read the Ice: a small read-only proxy for the NHL's public game data, so the site's live pages can use it
// (api-web.nhle.com sends no CORS headers). GET only, an allowlist of paths, and every response is cached
// at Vercel's edge for a few seconds, so a busy night sends the NHL about one request per game every 15 s.
export const config = { runtime: "edge" };

const ALLOW = [
  /^score\/now$/,
  /^score\/\d{4}-\d{2}-\d{2}$/,
  /^gamecenter\/\d{10}\/(play-by-play|landing|boxscore)$/,
];
const ORIGINS = [/^https:\/\/tolar-dio\.github\.io$/, /^https:\/\/(www\.)?readtheice\.(app|hockey)$/, /^http:\/\/localhost(:\d+)?$/];
const UA = "ReadTheIce/1.0 (+https://readtheice.app)";

function cors(origin) {
  const ok = origin && ORIGINS.some((r) => r.test(origin));
  return { "access-control-allow-origin": ok ? origin : "https://readtheice.app", "access-control-allow-methods": "GET, OPTIONS", vary: "origin" };
}

export default async function handler(req) {
  const origin = req.headers.get("origin");
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: { ...cors(origin), "access-control-max-age": "86400" } });
  if (req.method !== "GET") return new Response("GET only", { status: 405, headers: cors(origin) });
  const path = new URL(req.url).searchParams.get("path") || "";
  if (!ALLOW.some((r) => r.test(path))) return new Response("Not allowed", { status: 404, headers: cors(origin) });
  let up;
  try {
    const opts = { headers: { "user-agent": UA, accept: "application/json" }, redirect: "manual" };
    up = await fetch(`https://api-web.nhle.com/v1/${path}`, opts);
    const loc = up.headers.get("location");   // score/now answers with a redirect to today's date
    if (up.status >= 300 && up.status < 400 && loc) up = await fetch(new URL(loc, `https://api-web.nhle.com/v1/${path}`).href, opts);
  } catch (e) {
    return new Response("Upstream unreachable", { status: 502, headers: cors(origin) });
  }
  const live = path.startsWith("score/now") || path.endsWith("play-by-play");
  return new Response(up.body, {
    status: up.status,
    headers: {
      ...cors(origin),
      "content-type": up.headers.get("content-type") || "application/json",
      "cache-control": up.ok ? `public, s-maxage=${live ? 15 : 60}, stale-while-revalidate=30` : "no-store",
    },
  });
}
