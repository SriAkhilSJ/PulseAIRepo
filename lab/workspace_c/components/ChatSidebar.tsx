import { useState } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuCheckboxItem } from "@/components/ui/dropdown-menu";
import { MoreVert, MessageSquare, Trash2, Edit } from "lucide-react";

const ChatSidebar = () => {
  const [chats, setChats] = useState<Array<{ id: string; title: string; timestamp: number }>>([
    { id: "1", title: "How to learn React?", timestamp: Date.now() - 86400000 },
    { id: "2", title: "JavaScript async/await", timestamp: Date.now() - 172800000 },
  ]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState("");

  const handleNewChat = () => {
    const newChat = {
      id: Date.now().toString(),
      title: "New Chat",
      timestamp: Date.now(),
    };
    setChats([newChat, ...chats]);
    setActiveChatId(newChat.id);
  };

  const handleSelectChat = (id: string) => {
    setActiveChatId(id);
  };

  const handleDeleteChat = (id: string) => {
    setChats(chats.filter(chat => chat.id !== id));
    if (activeChatId === id) {
      setActiveChatId(null);
    }
  };

  const handleEditChat = (id: string) => {
    const chat = chats.find(c => c.id === id);
    if (chat) {
      setIsEditing(true);
      setEditValue(chat.title);
    }
  };

  const handleSaveEdit = (id: string) => {
    if (editValue.trim()) {
      setChats(chats.map(chat => chat.id === id ? { ...chat, title: editValue.trim() } : chat));
      setIsEditing(false);
    }
  };

  return (
    <aside className="w-64 border-r bg-background/50 backdrop-blur flex flex-col h-full p-4">
      <div className="flex-1 flex flex-col">
        <h2 className="text-lg font-semibold mb-4">Chats</h2>
        <Button variant="outline" size="icon" onClick={handleNewChat} className="w-full mb-4">
          <MessageSquare className="mr-2 h-4 w-4" />
          New Chat
        </Button>
        <ScrollArea className="flex-1">
          <div className="space-y-2">
            {chats.map(chat => (
              <div key={chat.id} className="flex items-center justify-between p-2 rounded-lg cursor-pointer hover:bg-accent/20 transition-colors" onClick={() => handleSelectChat(chat.id)}>
                <div className="flex-1 overflow-hidden text-ellipsis whitespace-nowrap">
                  {isEditing && editValue && chat.id === activeChatId ? (
                    <input
                      type="text"
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      className="border-b border-input/50 bg-transparent px-1 py-0.5 text-sm focus:outline-none focus:border-primary"
                      autoFocus
                    />
                  ) : (
                    <span className="text-sm">{chat.title}</span>
                  )}
                </div>
                <div className="text-xs text-muted-foreground">{new Date(chat.timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</div>
                {chat.id === activeChatId && <div className="w-2 h-2 bg-primary rounded-full" />}
                {!isEditing && (
                  <DropdownMenu>
                    <DropdownMenuTrigger className="p-1 rounded-hover">
                      <MoreVert className="h-4 w-4 text-muted-foreground" />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onClick={() => handleEditChat(chat.id)}>
                        Edit
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => handleDeleteChat(chat.id)} destructive>
                        Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </div>
            ))}
          </div>
        </ScrollArea>
      </div>
      {isEditing && (
        <div className="flex items-center space-x-2 p-2 border-t">
          <input
            type="text"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            className="flex-1 border border-input bg-background/50 px-3 py-2 rounded-md focus:outline-none focus:ring-2 focus:ring-primary"
            autoFocus
          />
          <Button variant="outline" size="icon" onClick={handleSaveEdit}>
            <Edit className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="icon" onClick={() => setIsEditing(false)}>
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      )}
    </aside>
  );
};

export default ChatSidebar;