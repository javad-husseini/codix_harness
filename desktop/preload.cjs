const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('codix', Object.freeze({
  health: () => ipcRenderer.invoke('codix:health'),
  prerequisites: () => ipcRenderer.invoke('codix:prerequisites'),
  selectProject: () => ipcRenderer.invoke('codix:select-project'),
  prepareProject: () => ipcRenderer.invoke('codix:prepare-project'),
  smoke: () => ipcRenderer.invoke('codix:smoke'),
  setPlan: steps => ipcRenderer.invoke('codix:set-plan', steps),
  runTool: (name, args) => ipcRenderer.invoke('codix:run-tool', name, args),
  startTask: text => ipcRenderer.invoke('codix:start-task', text),
  chatSend: text => ipcRenderer.invoke('codix:chat-send', text),
  taskStatus: () => ipcRenderer.invoke('codix:task-status'),
  readFile: path => ipcRenderer.invoke('codix:read-file', path),
  terminalOpen: () => ipcRenderer.invoke('codix:terminal-open'),
  terminalInput: (id, text) => ipcRenderer.invoke('codix:terminal-input', id, text),
  terminalPoll: (id, cursor) => ipcRenderer.invoke('codix:terminal-poll', id, cursor),
  terminalResize: (id, cols, rows) => ipcRenderer.invoke('codix:terminal-resize', id, cols, rows),
  terminalInterrupt: id => ipcRenderer.invoke('codix:terminal-interrupt', id),
  terminalClose: id => ipcRenderer.invoke('codix:terminal-close', id),
}));
