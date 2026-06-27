// Content-protection deterrents for the prod web app.
//
// HONEST SCOPE — read before trusting this:
//   This RAISES FRICTION for casual copying/screenshotting. It does NOT, and
//   cannot, *prevent* either. A browser renders pixels to the screen; OS-level
//   capture (Win+Shift+S, macOS Cmd+Shift+4, the Snipping Tool, a phone
//   screenshot, or a camera pointed at the monitor) happens below anything JS
//   can observe or block. There is no web equivalent of Android FLAG_SECURE.
//   Anyone can also open DevTools / "View Source" and read the DOM. Treat this
//   as a deterrent layer, not a security control. Real screenshot blocking is
//   only achievable in the native mobile shells (Android FLAG_SECURE).
//
// What this does:
//   - Blocks right-click context menu
//   - Disables text selection + image dragging (CSS + events)
//   - Blocks copy / cut (except inside form fields, so the app stays usable)
//   - Blocks Ctrl/Cmd+S (save page) and Ctrl/Cmd+P (print)
//   - Blurs the page when the tab/window loses focus — deters screenshot tools
//     that have to switch focus away from the app
//
// Form fields (input / textarea / [contenteditable]) are intentionally exempt
// from the selection/copy blocks: blocking them would break login, search, OTP
// entry, etc. This is a deliberate usability tradeoff.
//
// Gating: enabled in production builds by default. Set
// REACT_APP_CONTENT_PROTECTION=off to disable, or =on to force-enable in dev.

const STYLE_ID = "content-protection-style";
const OVERLAY_ID = "content-protection-overlay";

const isEditable = (el) => {
  if (!el || !el.closest) return false;
  return !!el.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"]');
};

const isProtectionEnabled = () => {
  const flag = (process.env.REACT_APP_CONTENT_PROTECTION || "").toLowerCase();
  if (flag === "off") return false;
  if (flag === "on") return true;
  return process.env.NODE_ENV === "production";
};

function injectStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    body.cp-active, body.cp-active * {
      -webkit-user-select: none;
      -moz-user-select: none;
      -ms-user-select: none;
      user-select: none;
    }
    /* Keep form fields usable */
    body.cp-active input,
    body.cp-active textarea,
    body.cp-active select,
    body.cp-active [contenteditable="true"] {
      -webkit-user-select: text;
      -moz-user-select: text;
      -ms-user-select: text;
      user-select: text;
    }
    body.cp-active img,
    body.cp-active svg {
      -webkit-user-drag: none;
      user-drag: none;
      -webkit-touch-callout: none;
    }
    #${OVERLAY_ID} {
      position: fixed;
      inset: 0;
      z-index: 2147483647;
      background: rgba(10, 15, 25, 0.85);
      backdrop-filter: blur(18px);
      -webkit-backdrop-filter: blur(18px);
      display: flex;
      align-items: center;
      justify-content: center;
      color: #e2e8f0;
      font: 500 15px/1.5 system-ui, -apple-system, sans-serif;
      text-align: center;
      padding: 24px;
      pointer-events: none;
    }
  `;
  document.head.appendChild(style);
}

function showOverlay() {
  if (document.getElementById(OVERLAY_ID)) return;
  const overlay = document.createElement("div");
  overlay.id = OVERLAY_ID;
  overlay.setAttribute("aria-hidden", "true");
  overlay.textContent = "Content hidden while this window is not in focus.";
  (document.body || document.documentElement).appendChild(overlay);
}

function hideOverlay() {
  const overlay = document.getElementById(OVERLAY_ID);
  if (overlay) overlay.remove();
}

/**
 * Install content-protection deterrents. Idempotent and prod-gated.
 * @returns {() => void} cleanup function that removes all listeners/styles.
 */
export function installContentProtection() {
  if (typeof window === "undefined" || !document) return () => {};
  if (!isProtectionEnabled()) return () => {};

  injectStyles();
  document.body.classList.add("cp-active");

  const onContextMenu = (e) => {
    if (isEditable(e.target)) return; // allow paste menu in fields
    e.preventDefault();
  };

  const onCopyCut = (e) => {
    if (isEditable(e.target)) return; // let users copy from fields they typed in
    e.preventDefault();
  };

  const onDragStart = (e) => {
    const t = e.target;
    if (t && (t.tagName === "IMG" || t.tagName === "SVG")) e.preventDefault();
  };

  const onKeyDown = (e) => {
    const mod = e.ctrlKey || e.metaKey;
    if (!mod) return;
    const k = (e.key || "").toLowerCase();
    // Ctrl/Cmd+S (save page), Ctrl/Cmd+P (print).
    if (k === "s" || k === "p") {
      e.preventDefault();
      e.stopPropagation();
    }
  };

  // Blur the page whenever it is backgrounded or loses focus. Many screenshot
  // utilities require switching focus away from the browser, so this hides
  // content at that moment. (Does NOT defeat same-window OS hotkey capture.)
  const onVisibility = () => {
    if (document.visibilityState === "hidden") showOverlay();
    else hideOverlay();
  };
  const onBlur = () => showOverlay();
  const onFocus = () => hideOverlay();

  document.addEventListener("contextmenu", onContextMenu, true);
  document.addEventListener("copy", onCopyCut, true);
  document.addEventListener("cut", onCopyCut, true);
  document.addEventListener("dragstart", onDragStart, true);
  document.addEventListener("keydown", onKeyDown, true);
  document.addEventListener("visibilitychange", onVisibility);
  window.addEventListener("blur", onBlur);
  window.addEventListener("focus", onFocus);

  return function cleanup() {
    document.removeEventListener("contextmenu", onContextMenu, true);
    document.removeEventListener("copy", onCopyCut, true);
    document.removeEventListener("cut", onCopyCut, true);
    document.removeEventListener("dragstart", onDragStart, true);
    document.removeEventListener("keydown", onKeyDown, true);
    document.removeEventListener("visibilitychange", onVisibility);
    window.removeEventListener("blur", onBlur);
    window.removeEventListener("focus", onFocus);
    document.body.classList.remove("cp-active");
    hideOverlay();
  };
}
