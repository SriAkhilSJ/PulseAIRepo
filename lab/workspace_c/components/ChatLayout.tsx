"use client";
import { useState, useEffect, useRef } from "react";
import ChatSidebar from "@/components/ChatSidebar";
import MessageList from "@/components/MessageList";
import PromptInput from "@/components/PromptInput";
import EmptyState from "@/components/EmptyState";
import { cn } from "@/lib/utils";
import { Menu, Sun, Moon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from "@/components/ui/dropdown-menu";

const ChatLayout = () => {
  const [messages, setMessages] = useState<Array<{id: string; role: "user" | "assistant"; content: string; isStreaming?: boolean; timestamp?: number}>>([]);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [theme, setTheme] = useState<"light" | "dark" | "system">("system");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Simulate sending a message and getting a response
  const handleSubmit = (prompt: string) => {
    // Add user message
    const userMessage = {
      id: Date.now().toString(),
      role: "user",
      content: prompt,
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, userMessage]);

    // Simulate AI response with streaming
    const aiMessageId = Date.now().toString() + "ai";
    const aiMessage = {
      id: aiMessageId,
      role: "assistant",
      content: "",
      isStreaming: true,
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, aiMessage]);

    // Stream the mock response
    const { streamMockResponse } = require("@/lib/mockResponse");
    const unsubscribe = streamMockResponse((chunk, done) => {
      setMessages((prev) => {
        return prev.map((msg) => {
          if (msg.id === aiMessageId) {
            if (done) {
              return { ...msg, content: msg.content + chunk, isStreaming: false };
            }
            return { ...msg, content: msg.content + chunk };
          }
          return msg;
        });
      });
    });

    // Cleanup on unmount (we'll return a cleanup function from the effect)
    return unsubscribe;
  };

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="flex h-screen bg-background text-foreground">
      {/* Sidebar */}
      <div className={cn("w-64 border-r flex flex-col", !isSidebarOpen && "w-16")}>
        <div className="flex items-center justify-between p-4">
          <h2 className="text-lg font-semibold">Chats</h2>
          <Button variant="outline" size="icon" onClick={() => setIsSidebarOpen(!isSidebarOpen)}>
            <Menu className="h-4 w-4" />
          </Button>
        </div>
        <ChatSidebar />
      </div>

      {/* Main chat area */}
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b bg-background/50 backdrop-blur">
          <div className="flex items-center space-x-2">
            <Button variant="outline" size="icon">
              <Menu className="h-4 w-4" />
            </Button>
            <span className="text-sm font-medium">ChatBot</span>
          </div>
          <div className="flex items-center space-x-2">
            <DropdownMenu>
              <DropdownMenuTrigger className="p-1 rounded-hover">
                <Button variant="outline" size="icon">
                  {theme === "dark" ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => setTheme("light")}>
                  Light
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setTheme("dark")}>
                  Dark
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setTheme("system")}>
                  System
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        {/* Chat messages */}
        {messages.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="flex-1 overflow-y-auto">
            <MessageList messages={messages} />
            <div ref={messagesEndRef} />
          </div>
        )}

        {/* Input bar */}
        <PromptInput onSubmit={handleSubmit} />
      </div>
    </div>
  );
};

export default ChatLayout;