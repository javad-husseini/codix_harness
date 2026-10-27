'use client';

import { Group, Panel, Separator } from 'react-resizable-panels';
import { cn } from '@/lib/utils';

export function ResizablePanelGroup({ className, ...props }) {
  return <Group data-slot="resizable-panel-group" className={cn('resizable-group', className)} {...props} />;
}
export function ResizablePanel(props) {
  return <Panel data-slot="resizable-panel" {...props} />;
}
export function ResizableHandle({ className, ...props }) {
  return <Separator data-slot="resizable-handle" className={cn('resizable-handle', className)} {...props}><span /></Separator>;
}
