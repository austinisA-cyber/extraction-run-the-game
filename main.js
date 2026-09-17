const { app, BrowserWindow, Menu } = require('electron');
const path = require('path');

// The game reads raw keyboard input (WASD, Shift, Ctrl, Space, etc.) — the default Electron
// menu bar intercepts some of those (Alt in particular) for its own navigation, so it's removed
// entirely rather than just hidden.
Menu.setApplicationMenu(null);

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 560,
    autoHideMenuBar: true,
    backgroundColor: '#0a0e14', // matches the game's own loading-screen background — avoids a
                                // white flash while index.html loads
    webPreferences: {
      // The game is a single self-contained HTML file with no Node/file-system calls of its
      // own, so it runs fine fully sandboxed — no need to expose Node APIs to it.
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  win.loadFile('index.html');

  // Uncomment while testing to open DevTools automatically:
  // win.webContents.openDevTools();
}

app.whenReady().then(() => {
  createWindow();

  app.on('activate', () => {
    // macOS convention: re-open a window when the dock icon is clicked with no windows open.
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
