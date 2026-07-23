// Capture the admin token the sidecar puts in the WebView URL (?token=…),
// store it, and strip it from the address bar — mirrors browse.html exactly.
export function captureBootToken(): void {
  const params = new URLSearchParams(location.search);
  // Mark the surface (desktop vs web) so CSS can inset the topbar under the
  // native window's traffic lights and make it a drag region.
  const surface = params.get("surface") === "desktop" ? "desktop" : "web";
  document.documentElement.dataset.surface = surface;
  const token = params.get("token");
  if (token) {
    sessionStorage.setItem("loom_admin_token", token);
    params.delete("token");
    const query = params.toString();
    history.replaceState(null, "", location.pathname + (query ? "?" + query : "") + location.hash);
  }
}

export function hasLoomToken(): boolean {
  return !!sessionStorage.getItem("loom_admin_token");
}
