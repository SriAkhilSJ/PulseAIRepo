import type * as React from 'react'

import { cn } from '@/lib/utils'

// Verbatim port: hermes apps/desktop/src/components/ui/codicon.tsx (glyphs
// served by the vendored VS Code codicon font — codicon.css subset in
// styles/app.css).
export interface CodiconProps extends React.HTMLAttributes<HTMLElement> {
  name: string
  size?: number | string
  spinning?: boolean
}

export function Codicon({ className, name, size, spinning, style, ...props }: CodiconProps) {
  return (
    <i
      aria-hidden="true"
      className={cn('codicon', `codicon-${name}`, spinning && 'codicon-modifier-spin', className)}
      style={{ ...(size != null && size !== '' ? { fontSize: size } : {}), ...style }}
      {...props}
    />
  )
}
