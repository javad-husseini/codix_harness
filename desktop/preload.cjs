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
  taskStatus: () => ipcRenderer.invoke('codix:task-status'),
}));
