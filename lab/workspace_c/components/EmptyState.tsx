import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { MessageSquare, BotMessageSquare } from "lucide-react";

const EmptyState = () => {
  return (
    <div className="flex flex-col items-center justify-center min-h-[calc(100vh-4rem)] p-6 text-center bg-empty-state">
      <div className="mb-6">
        <BotMessageSquare className="h-12 w-12 mb-4" aria-hidden="true" />
        <h1 className="text-4xl font-semibold text-foreground">
          How Can I Help You
        </h1>
        <p className="mt-2 text-muted-foreground max-w-xl">
          Ask me anything — I'm here to help with writing, analysis, questions, and more.
        </p>
      </div>
      <Button
        variant="outline"
        size="lg"
        className="w-full max-w-xs"
      >
        <MessageSquare className="mr-2 h-4 w-4" />
        Start chatting
      </Button>
    </div>
  );
};

export default EmptyState;