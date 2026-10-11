export function appPathname(pathname: string): string {
  const base = import.meta.env.BASE_URL.replace(/\/$/, "");
  return pathname.startsWith(base + "/") ? pathname.slice(base.length) : pathname;
}
