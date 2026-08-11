import { useState, useRef, useEffect } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuCheckboxItem } from "@/components/ui/dropdown-menu";
import { Paperclip, ArrowUp, Menu, CircleHelp } from "lucide-react";
import { Separator } from "@/components/ui/separator";

const models = ["GPT 5.5", "GPT 4o", "Claude 3 Opus"];
const efforts = ["Medium", "High"];

const PromptInput = ({ onSubmit, onAttach }: { onSubmit: (prompt: string) => void; onAttach?: () => void }) => {
  const [prompt, setPrompt] = useState("");
  const [model, setModel] = useState(models[0]);
  const [effort, setEffort] = useState(efforts[0]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (prompt.trim()) {
      onSubmit(prompt);
      setPrompt("");
    }
  };

  const handleKeyDown = (e: React.KeyEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <div className="flex items-start space-x-3">
        {/* Left actions: Attach */}
        <Button
          variant="outline"
          size="icon"
          onClick={onAttach}
          aria-label="Attach files"
        >
          <Paperclip className="h-4 w-4" />
        </Button>

        {/* Textarea */}
        <textarea
          ref={textareaRef}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask anything..."
          className="flex-1 min-h-[60px] rounded-md border border-input bg-background px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 resize-none"
          rows={1}
          maxRows={6}
        />

        {/* Right actions: Send */}
        <Button
          type="submit"
          disabled={!prompt.trim()}
          variant="default"
          size="icon"
          aria-label="Send message"
        >
          <ArrowUp className="h-4 w-4" />
        </Button>
      </div>

      {/* Model and Effort selectors */}
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <div className="flex items-center space-x-2">
          <Button variant="outline" size="icon" aria-label="Model">
            <Menu className="h-4 w-4" />
            <span className="ml-2">{model}</span>
          </Button>
          <DropdownMenu align="end" className="ml-2">
            <DropdownMenuTrigger className="p-1 rounded-hover">
              <Button variant="outline" size="icon">
                <Menu className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent className="w-48">
              {models.map((m) => (
                <DropdownMenuItem key={m} onClick={() => setModel(m)}>
                  {m}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <div className="flex items-center space-x-2">
          <Button variant="outline" size="icon" aria-label="Effort level">
            <CircleHelp className="h-4 w-4" />
            <span className="ml-2">{effort}</span>
          </Button>
          <DropdownMenu align="end" className="ml-2">
            <DropdownMenuTrigger className="p-1 rounded-hover">
              <Button variant="outline" size="icon">
                <CircleHelp className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent className="w-36">
              {efforts.map((e) => (
                <DropdownMenuItem key={e} onClick={() => setEffort(e)}>
                  {e}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </form>
  );
};

export default PromptInput;