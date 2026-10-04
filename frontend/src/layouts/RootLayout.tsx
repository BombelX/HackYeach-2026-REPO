import { useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router";
import { configureTelemetry } from "../features/telemetry/collector";
import { clearAuthDraft } from "../features/auth/pages";
import { clearTransferDraft } from "../features/transfers/pages";
import { stopCamera, useCamera } from "../features/camera/store";
import { ErrorNotice, Icon } from "../design/components";
import { queryClient, updatePermissions } from "../services/api";

export function RootLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const camera = useCamera();
  const [stopError, setStopError] = useState<unknown>();
  useEffect(() => {
    const heading = document.querySelector<HTMLElement>("main h1");
    if (heading) {
      if (!heading.hasAttribute("tabindex")) heading.tabIndex = -1;
      heading.focus();
    }
    window.scrollTo(0, 0);
  }, [location.pathname]);
  useEffect(() => {
    const expired = () => {
      stopCamera();
      configureTelemetry();
      clearAuthDraft();
      clearTransferDraft();
      queryClient.clear();
      navigate("/login", { replace: true });
    };
    window.addEventListener("bank24:expired", expired);
    return () => window.removeEventListener("bank24:expired", expired);
  }, [navigate]);
  const cameraOutsideBank =
    !location.pathname.startsWith("/app") &&
    (camera.status === "active" || camera.status === "starting");
  async function stopAndRevokeCamera() {
    stopCamera();
    try {
      await updatePermissions({ camera: false });
      setStopError(undefined);
    } catch (error) {
      setStopError(error);
    }
  }
  return (
    <>
      <Outlet />
      {cameraOutsideBank && (
        <aside className="global-camera-control" aria-label="Stan kamery">
          <span>
            <Icon name="camera" size={17} /> Kamera{" "}
            {camera.status === "active" ? "aktywna" : "uruchamia się"}
          </span>
          <button
            className="button button-secondary"
            onClick={() => void stopAndRevokeCamera()}
          >
            Wyłącz kamerę
          </button>
        </aside>
      )}
      {Boolean(stopError) && (
        <div className="global-camera-error">
          <ErrorNotice error={stopError} />
        </div>
      )}
    </>
  );
}
