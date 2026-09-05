import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

// Verbatim port: hermes apps/desktop/src/lib/utils.ts
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
