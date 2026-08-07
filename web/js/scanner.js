// scanner.js -- camera barcode/QR scanning for phones at the bench.
//
// Zero dependencies, in keeping with the buildless rule: this uses the browser's
// native BarcodeDetector rather than bundling a decoder. That works on Android
// Chrome and desktop Chrome/Edge -- the realistic "phone in a lab" case. Where it
// is unavailable (notably iOS Safari), we say so plainly and fall back to typing
// the code, and the printed QR labels still work with the phone's own camera app
// because they encode a deep link (/?item=<id>).
//
// Used by counts.js (scan to count) and app.js (global scan -> open the item).

const FORMATS = ["qr_code", "code_128", "code_39", "ean_13", "ean_8", "upc_a", "upc_e"];

export function isSupported() {
  return (
    typeof window !== "undefined"
    && "BarcodeDetector" in window
    && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)
  );
}

export function unsupportedReason() {
  if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) {
    return "This browser cannot open a camera (a secure origin -- https or "
      + "localhost -- is required).";
  }
  if (!("BarcodeDetector" in window)) {
    return "This browser has no built-in barcode reader. Chrome or Edge on "
      + "Android or desktop supports it; on iPhone, use the Camera app to scan "
      + "the printed QR label, or type the code below.";
  }
  return "Camera scanning is unavailable.";
}

/**
 * Open a scanning modal. Calls onCode(value) for each distinct code detected.
 * Return true from onCode (or resolve true) to keep scanning; anything else
 * closes the scanner. Always stops the camera when dismissed.
 *
 * openScanner(ctx, { title, hint, continuous, onCode })
 */
export function openScanner(ctx, opts) {
  opts = opts || {};
  const continuous = !!opts.continuous;
  let stream = null;
  let stopped = false;
  let raf = null;
  let lastCode = null;
  let lastAt = 0;

  const video = document.createElement("video");
  video.setAttribute("playsinline", "");   // iOS: don't go fullscreen
  video.muted = true;
  video.style.width = "100%";
  video.style.maxHeight = "60vh";
  video.style.background = "#000";

  const status = document.createElement("div");
  status.className = "muted";
  status.style.marginTop = "8px";
  status.textContent = "Starting camera...";

  const handle = ctx.modal({
    title: opts.title || "Scan a code",
    render: (body) => {
      if (opts.hint) {
        const p = document.createElement("p");
        p.className = "muted";
        p.textContent = opts.hint;
        body.appendChild(p);
      }
      body.appendChild(video);
      body.appendChild(status);
    },
    actions: [{ label: "Done", onClick: (h) => h.close() }],
    onClose: () => {
      stop();
      if (typeof opts.onClose === "function") opts.onClose();
    },
  });

  function stop() {
    stopped = true;
    if (raf) { cancelAnimationFrame(raf); raf = null; }
    if (stream) {
      for (const track of stream.getTracks()) track.stop();
      stream = null;
    }
  }

  (async () => {
    if (!isSupported()) {
      status.textContent = unsupportedReason();
      return;
    }
    let detector;
    try {
      // Only ask for formats this browser actually knows about.
      let supported = FORMATS;
      if (window.BarcodeDetector.getSupportedFormats) {
        const avail = await window.BarcodeDetector.getSupportedFormats();
        supported = FORMATS.filter((f) => avail.includes(f));
      }
      detector = new window.BarcodeDetector({ formats: supported.length ? supported : undefined });
    } catch (err) {
      status.textContent = "Could not start the barcode reader: " + err.message;
      return;
    }

    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },  // rear camera on phones
        audio: false,
      });
    } catch (err) {
      status.textContent = err && err.name === "NotAllowedError"
        ? "Camera permission was denied. Allow camera access, or type the code."
        : "Could not open the camera: " + (err && err.message ? err.message : err);
      return;
    }
    if (stopped) { stop(); return; }

    video.srcObject = stream;
    try { await video.play(); } catch (_) { /* autoplay guard; frame loop still runs */ }
    status.textContent = "Point the camera at a QR code or barcode.";

    const tick = async () => {
      if (stopped) return;
      try {
        const found = await detector.detect(video);
        if (found && found.length) {
          const value = found[0].rawValue;
          const now = Date.now();
          // Debounce: the same code sits in frame for many frames.
          if (value && (value !== lastCode || now - lastAt > 2500)) {
            lastCode = value;
            lastAt = now;
            status.textContent = "Scanned: " + value;
            let keepGoing = continuous;
            try {
              const res = await opts.onCode(value);
              if (res === false) keepGoing = false;
              else if (res === true) keepGoing = true;
            } catch (err) {
              status.textContent = "Scan failed: "
                + (err && err.message ? err.message : err);
            }
            if (!keepGoing) { handle.close(); return; }
          }
        }
      } catch (_) {
        // A transient detect() failure (e.g. a frame arriving mid-resize) is
        // not fatal -- keep scanning.
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
  })();

  return handle;
}
