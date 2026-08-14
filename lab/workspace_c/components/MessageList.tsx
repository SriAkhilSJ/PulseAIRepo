import { useEffect, useRef, useState } from "react";
import { StreamMockResponse } from "@/lib/mockResponse";
import ReactMarkdown from "react-markdown";
import { Prism as SyntaxHighlighter } from "@components/prism-highlighter";
import { gfm } from "remark-gfm";
import { CopyButton } from "@/components/ui/copy-button";
import { Button } from "@/components/ui/button";
import { Loader2, Edit2, Trash2, ThumbsUp, ThumbsDown } from "lucide-react";
import { cn } from "@/lib/utils";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
  timestamp?: number;
}

const MessageList = ({ messages }: { messages: Message[] }) => {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [stream, setStream] = useState<(() => void) | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    // TODO: Show toast or feedback
  };

  const handleRegenerate = (messageId: string) => {
    // TODO: Implement regeneration
  };

  const handleFeedback = (messageId: string, type: "up" | "down") => {
    // TODO: Implement feedback
  };

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-4">
      {messages.map((message) => (
        <div
          key={message.id}
          className={`flex ${
            message.role === "user" ? "justify-end" : "justify-start"
          }`}
        >
          <div
            className={cn(
              "max-w-[80%] rounded-3xl p-4 px-6 py-3",
              message.role === "user"
                ? "bg-primary text-primary-foreground"
                : "bg-accent/20 border border-accent/30 text-foreground"
            )}
          >
            {message.isStreaming ? (
              <div className="flex flex-col">
                <div className="prose prose-sm max-w-none">
                  {/* Streaming content will be updated via ref */}
                  <span id={`stream-${message.id}`} className="break-words" />
                </div>
                <div className="flex items-center space-x-2 mt-2">
                  <Loader2 className="h-4 w-4" /> <span className="text-xs">Thinking...</span>
                </div>
              </div>
            ) : (
              <>
                <ReactMarkdown
                  remarkPlugins={[gfm]}
                  components={{
                    code({ node, inline, className, children, ...props }) {
                      const match = /language-(\w+)/.exec(className || "");
                      return !inline && match ? (
                        <SyntaxHighlighter
                          className="language-" + match[1]
                          style={{ padding: 16, borderRadius: 4 }}
                          children={String(children).replace(/\n$/, "")}
                        />
                      ) : (
                        <code
                          className={cn(
                            "bg-muted px-1.5 py-0.5 rounded",
                            inline ? "" : "block overflow-x-auto"
                          )}
                          {...props}
                        >
                          {children}
                        </code>
                      );
                    },
                    // Add a wrapper for code blocks to include copy button
                    pre({ children, ...props }) {
                      return (
                        <div className="relative">
                          {children}
                          <CopyButton
                            text={String(children).replace(/\n$/, "")}
                            className="absolute top-2 right-2"
                          />
                        </div>
                      );
                    },
                  }}
                >
                  {message.content}
                </ReactMarkdown>
                <div className="flex items-center space-x-2 mt-2 text-xs text-muted-foreground">
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => handleCopy(message.content)}
                  >
                    <CopyButton className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => handleRegenerate(message.id)}
                  >
                    <Edit2 className="h-4 w-4" />
                  </Button>
                  <div className="flex items-center space-x-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => handleFeedback(message.id, "up")}
                    >
                      <ThumbsUp className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => handleFeedback(message.id, "down")}
                    >
                      <ThumbsDown className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      ))}
      <div ref={messagesEndRef} />
    </div>
  );
};

export default MessageList;