// Single extension: login once, inject cookies

async function extension(hookName, context) {
  if (hookName === "beforeAll") {
    const baseUrl = process.env.NEXTJS_BASE_URL || "http://localhost:3000";
    const email = process.env.NEXTJS_EMAIL;
    const password = process.env.NEXTJS_PASSWORD;

    if (!email || !password) {
      throw new Error("Missing NEXTJS_EMAIL or NEXTJS_PASSWORD env vars");
    }

    const getSetCookies = (headers) => {
      if (typeof headers.getSetCookie === "function") {
        return headers.getSetCookie();
      }
      const single = headers.get("set-cookie");
      return single ? [single] : [];
    };

    const findActionHash = async () => {
      const candidates = new Set();
      try {
        const htmlResp = await fetch(`${baseUrl}/sign-in`, { method: "GET" });
        const html = await htmlResp.text();
        const scriptSrcRe = /<script[^>]+src="([^"]+)"[^>]*><\/script>/g;
        let m;
        while ((m = scriptSrcRe.exec(html)) !== null) {
          const src = m[1];
          if (src.includes("/_next/static/")) {
            const abs = src.startsWith("http") ? src : `${baseUrl}${src}`;
            candidates.add(abs);
          }
        }
      } catch (_) {}

      candidates.add(`${baseUrl}/_next/static/server/app/(auth)/sign-in/page.js`);
      candidates.add(`${baseUrl}/_next/static/chunks/app/(auth)/sign-in/page.js`);
      candidates.add(`${baseUrl}/_next/static/chunks/app/(prowler)/layout.js`);
      candidates.add(`${baseUrl}/_next/static/chunks/app/(prowler)/error.js`);

      const tryPatterns = [
        /"([a-f0-9]{40})":"authenticate"/,
        /"authenticate"\s*:\s*\{"id"\s*:\s*"([a-f0-9]{40})"\}/,
        /"([a-f0-9]{40})"\s*:\s*\["authenticate"\]/,
      ];

      for (const jsUrl of candidates) {
        try {
          const r = await fetch(jsUrl);
          if (!r.ok) continue;
          const js = await r.text();
          for (const re of tryPatterns) {
            const found = js.match(re);
            if (found && found[1]) {
              return found[1];
            }
          }
        } catch (_) {}
      }
      return null;
    };

    const actionHash = await findActionHash();
    if (!actionHash) {
      throw new Error("Could not locate Next-Action hash for authenticate()");
    }

    const resp = await fetch(`${baseUrl}/sign-in`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Next-Action": actionHash,
      },
      body: JSON.stringify([null, { email, password }]),
      redirect: "manual",
    });

    if (!(resp.ok || resp.status === 302)) {
      const t = await resp.text().catch(() => "");
      throw new Error(`Login failed: ${resp.status} ${resp.statusText} ${t}`);
    }

    const setCookies = getSetCookies(resp.headers);
    if (!setCookies.length) {
      throw new Error("Login did not return auth cookies");
    }
    const nameValues = setCookies.map((c) => c.split(";")[0]).filter(Boolean);
    const sessionOnly = nameValues.find((p) => /(^|\s)(__Secure-)?authjs\.session-token=/.test(p));
    if (!sessionOnly) {
      throw new Error("Session token not found in cookies");
    }

    process.env.AUTH_COOKIES = sessionOnly;
    return;
  }

  if (hookName === "beforeEach") {
    return;
  }

  if (hookName === "afterAll") {
    delete process.env.AUTH_COOKIES;
    return;
  }
}

module.exports = { extension };
