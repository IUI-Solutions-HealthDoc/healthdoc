/** Only return to this application; never navigate to an untrusted login target. */
export function safeReturnUrl(value: string | null | undefined, origin: string, fallback = "/"): string {
  const safeFallback = new URL(fallback, origin).href;
  if (!value || /[\\\u0000-\u0020\u007f]/.test(value)) return safeFallback;
  try {
    const decoded = decodeURIComponent(value);
    if (/[\\\u0000-\u001f\u007f]/.test(decoded) || decoded.startsWith("//")) return safeFallback;
    const target = new URL(value, origin);
    if (target.origin !== origin || target.username || target.password) return safeFallback;
    if (!value.startsWith("/") && !value.startsWith(origin + "/")) return safeFallback;
    if (target.pathname.startsWith("/auth/") || target.pathname === "/auth") return safeFallback;
    return target.href;
  } catch {
    return safeFallback;
  }
}
