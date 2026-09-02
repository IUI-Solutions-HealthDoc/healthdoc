// Electron shell — F1-W1-02 (shell only; weekly test builds in CI).
// Dev: loads the Next.js dev server. Prod: loads exported build.
import { app, BrowserWindow } from "electron";
import path from "node:path";

const iconPath = path.join(app.getAppPath(), "public", "healthdoc-logo.png");

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    icon: iconPath,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  const devUrl = process.env.HEALTHDOC_URL ?? "https://localhost";
  void win.loadURL(devUrl);
}

app.whenReady().then(() => {
  if (process.platform === "darwin" && app.dock) app.dock.setIcon(iconPath);
  createWindow();
});
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
