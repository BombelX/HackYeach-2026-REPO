export async function collectEnvironment(): Promise<Record<string, unknown>> {
  const nav = navigator as Navigator & {
    deviceMemory?: number;
    connection?: {
      effectiveType?: string;
      rtt?: number;
      downlink?: number;
      saveData?: boolean;
    };
    userAgentData?: {
      brands: Array<{ brand: string; version: string }>;
      mobile: boolean;
      platform: string;
      getHighEntropyValues: (h: string[]) => Promise<Record<string, unknown>>;
    };
  };

  let uaData: Record<string, unknown> | null = null;
  try {
    if (nav.userAgentData?.getHighEntropyValues) {
      uaData = await nav.userAgentData.getHighEntropyValues([
        "architecture",
        "bitness",
        "model",
        "platformVersion",
        "uaFullVersion",
        "fullVersionList",
      ]);
      uaData.brands = nav.userAgentData.brands;
      uaData.mobile = nav.userAgentData.mobile;
      uaData.platform = nav.userAgentData.platform;
    }
  } catch {
    uaData = null;
  }

  let webgl: string | null = null;
  try {
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
    if (gl && gl instanceof WebGLRenderingContext) {
      const ext = gl.getExtension("WEBGL_debug_renderer_info");
      webgl = ext
        ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL))
        : String(gl.getParameter(gl.RENDERER));
    }
  } catch {
    webgl = null;
  }

  let devices: Array<{ kind: string; label: string }> = [];
  try {
    const list = await navigator.mediaDevices.enumerateDevices();
    devices = list.map((d) => ({ kind: d.kind, label: d.label || d.kind }));
  } catch {
    devices = [];
  }

  const navEntries = performance.getEntriesByType("navigation") as PerformanceNavigationTiming[];
  const resources = performance.getEntriesByType("resource") as PerformanceResourceTiming[];

  return {
    userAgent: navigator.userAgent,
    language: navigator.language,
    languages: navigator.languages,
    platform: navigator.platform,
    hardwareConcurrency: navigator.hardwareConcurrency,
    deviceMemory: nav.deviceMemory ?? null,
    maxTouchPoints: navigator.maxTouchPoints,
    cookieEnabled: navigator.cookieEnabled,
    doNotTrack: navigator.doNotTrack,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    timezoneOffset: new Date().getTimezoneOffset(),
    screen: {
      width: window.screen.width,
      height: window.screen.height,
      availWidth: window.screen.availWidth,
      availHeight: window.screen.availHeight,
      colorDepth: window.screen.colorDepth,
      pixelDepth: window.screen.pixelDepth,
    },
    devicePixelRatio: window.devicePixelRatio,
    inner: { width: window.innerWidth, height: window.innerHeight },
    connection: nav.connection
      ? {
          effectiveType: nav.connection.effectiveType,
          rtt: nav.connection.rtt,
          downlink: nav.connection.downlink,
          saveData: nav.connection.saveData,
        }
      : null,
    uaData,
    webgl,
    devices,
    navigationTiming: navEntries[0]
      ? {
          type: navEntries[0].type,
          startTime: navEntries[0].startTime,
          duration: navEntries[0].duration,
          dns: navEntries[0].domainLookupEnd - navEntries[0].domainLookupStart,
          connect: navEntries[0].connectEnd - navEntries[0].connectStart,
          tls: navEntries[0].secureConnectionStart
            ? navEntries[0].connectEnd - navEntries[0].secureConnectionStart
            : null,
          ttfb: navEntries[0].responseStart - navEntries[0].requestStart,
          download: navEntries[0].responseEnd - navEntries[0].responseStart,
          domInteractive: navEntries[0].domInteractive,
          load: navEntries[0].loadEventEnd,
          transferSize: navEntries[0].transferSize,
        }
      : null,
    resourceTiming: resources.slice(0, 80).map((r) => ({
      name: r.name.replace(/https?:\/\/[^/]+/, ""),
      duration: r.duration,
      transferSize: r.transferSize,
      initiatorType: r.initiatorType,
      startTime: r.startTime,
    })),
  };
}

export function startPings(
  sessionId: string,
  onRow: (row: Record<string, unknown>) => void,
): () => void {
  let timer: number | null = null;
  const tick = async () => {
    const t0 = performance.now();
    try {
      const res = await fetch("/api/ping", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Session-Id": sessionId },
        body: JSON.stringify({ t_perf: t0, t_epoch: Date.now() }),
      });
      const t1 = performance.now();
      const json = await res.json();
      onRow({
        type: "ping",
        t_perf: t0,
        t_epoch: Date.now(),
        rtt_ms: t1 - t0,
        server_epoch_ms: json.server_epoch_ms,
      });
    } catch (err) {
      onRow({
        type: "ping_error",
        t_perf: t0,
        t_epoch: Date.now(),
        error: String(err),
      });
    }
    timer = window.setTimeout(tick, 5000);
  };
  void tick();
  return () => {
    if (timer) window.clearTimeout(timer);
  };
}

export function startMotion(onRow: (row: Record<string, unknown>) => void): () => void {
  const handler = (ev: DeviceMotionEvent) => {
    onRow({
      type: "devicemotion",
      t_perf: performance.now(),
      t_epoch: Date.now(),
      acc: ev.acceleration
        ? { x: ev.acceleration.x, y: ev.acceleration.y, z: ev.acceleration.z }
        : null,
      accG: ev.accelerationIncludingGravity
        ? {
            x: ev.accelerationIncludingGravity.x,
            y: ev.accelerationIncludingGravity.y,
            z: ev.accelerationIncludingGravity.z,
          }
        : null,
      rot: ev.rotationRate
        ? {
            a: ev.rotationRate.alpha,
            b: ev.rotationRate.beta,
            g: ev.rotationRate.gamma,
          }
        : null,
      interval: ev.interval,
    });
  };
  window.addEventListener("devicemotion", handler);
  return () => window.removeEventListener("devicemotion", handler);
}
