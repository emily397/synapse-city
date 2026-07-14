// Synapse City stable front door.
//
// A Cloudflare Worker at a NEVER-rotating *.workers.dev URL that transparently
// proxies to whatever the current cloudflared quick-tunnel is. The supervisor
// already publishes the live tunnel URL to the TUNNEL file on GitHub main; this
// Worker reads it (cached briefly) and forwards every request — HTTP and the
// /ws WebSocket alike. The frontend points here forever, so a tunnel rotation
// never shows "offline" again.
const TUNNEL_SRC =
  "https://raw.githubusercontent.com/emily397/synapse-city/main/TUNNEL";

let cache = { url: null, at: 0 };

async function backend() {
  const now = Date.now();
  if (cache.url && now - cache.at < 15000) return cache.url; // 15s cache
  try {
    const r = await fetch(TUNNEL_SRC + "?t=" + now, {
      cf: { cacheTtl: 0 },
      headers: { "cache-control": "no-cache" },
    });
    const u = (await r.text()).trim();
    if (/^https:\/\//.test(u)) cache = { url: u.replace(/\/$/, ""), at: now };
  } catch (_) {}
  return cache.url;
}

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "*",
  "Access-Control-Allow-Headers": "*",
};

export default {
  async fetch(request) {
    const inUrl = new URL(request.url);

    if (request.method === "OPTIONS")
      return new Response(null, { headers: CORS });

    // tiny health page at /
    if (inUrl.pathname === "/" ) {
      const b = await backend();
      return new Response(
        JSON.stringify({ ok: !!b, proxies_to: b }, null, 2),
        { headers: { "content-type": "application/json", ...CORS } }
      );
    }

    const b = await backend();
    if (!b) return new Response("no live backend", { status: 502, headers: CORS });
    const target = b + inUrl.pathname + inUrl.search;

    // WebSocket (/ws): pass the upgrade straight through to the tunnel
    if ((request.headers.get("Upgrade") || "").toLowerCase() === "websocket") {
      return fetch(target, request);
    }

    // normal HTTP proxy
    const init = {
      method: request.method,
      headers: request.headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
      redirect: "manual",
    };
    const resp = await fetch(target, init);
    const headers = new Headers(resp.headers);
    for (const [k, v] of Object.entries(CORS)) headers.set(k, v);
    return new Response(resp.body, { status: resp.status, headers });
  },
};
