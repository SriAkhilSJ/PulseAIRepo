import * as React from "react"
import { Check, Copy } from "lucide-react"
import { cn } from "@/lib/utils"

interface CopyButtonProps {
  text: string
  className?: string
}

const CopyButton = React.forwardRef<
  HTMLButtonElement,
  CopyButtonProps
>(({ text, className }, ref) => {
  const [copied, setCopied] = React.useState(false)

  const handleCopy = () {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <button
      ref={ref}
      className={cn(
        "flex items-center gap-1.5 h-8 w-8 rounded-md bg-muted px-2.5 text-sm text-muted-foreground ring-offset-background transition-colors hover:bg-accent/20 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
        className
      )}
      onClick={handleCopy}
      aria-label="Copy to clipboard"
    >
      {!copied ? (
        <Copy className="h-4 w-4" aria-hidden="true" />
      ) : (
        <Check className="h-4 w-4" aria-hidden="true" />
      )}
    </button>
  )
})
CopyButton.displayName = "CopyButton"

export { CopyButton }