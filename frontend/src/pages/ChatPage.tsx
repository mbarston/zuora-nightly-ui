import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  Loader2,
  MessageSquare,
  RotateCcw,
  Send,
} from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SseEvent {
  type: "text" | "tool_use" | "tool_result" | "thinking" | "done" | "error";
  data: Record<string, unknown>;
}

interface ChatMessage {
  role: "user" | "assistant";
  blocks: SseEvent[];
  cost_usd?: number | null;
}

// ---------------------------------------------------------------------------
// Chat page
// ---------------------------------------------------------------------------

export function ChatPage() {
  const { tenantId: idParam } = useParams();
  const tenantId = Number(idParam);

  const tenantQ = useQuery({
    queryKey: ["tenant", tenantId],
    queryFn: () => api.getTenant(tenantId),
  });

  const [sessionId, setSessionId] = useState(() => crypto.randomUUID());
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [turnCount, setTurnCount] = useState(0);

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll on new messages.
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  // Focus input on mount.
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;

    setInput("");
    setStreaming(true);

    // Add user message immediately.
    const userMsg: ChatMessage = { role: "user", blocks: [{ type: "text", data: { text } }] };
    const assistantMsg: ChatMessage = { role: "assistant", blocks: [] };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);

    try {
      const res = await fetch(`/api/tenants/${tenantId}/chat`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: sessionId, is_new: turnCount === 0 }),
      });

      if (!res.ok) {
        const errBody = await res.text();
        setMessages((prev) => {
          const copy = [...prev];
          const last = { ...copy[copy.length - 1] };
          last.blocks = [
            ...last.blocks,
            { type: "error", data: { message: `API error ${res.status}: ${errBody.slice(0, 200)}` } },
          ];
          copy[copy.length - 1] = last;
          return copy;
        });
        setStreaming(false);
        return;
      }

      // Read SSE stream from the response body.
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (line.startsWith("event: ")) {
            const eventType = line.slice(7).trim();
            // Next "data:" line has the payload.
            const dataIdx = lines.indexOf(line);
            const nextLine = lines[dataIdx + 1];
            if (nextLine?.startsWith("data: ")) {
              try {
                const payload = JSON.parse(nextLine.slice(6));
                const evt: SseEvent = { type: eventType as SseEvent["type"], data: payload };

                setMessages((prev) => {
                  const copy = [...prev];
                  const last = { ...copy[copy.length - 1] };
                  last.blocks = [...last.blocks, evt];
                  if (evt.type === "done") {
                    last.cost_usd = (payload as { cost_usd?: number }).cost_usd ?? null;
                  }
                  copy[copy.length - 1] = last;
                  return copy;
                });
              } catch {
                // malformed JSON — skip
              }
            }
          }
        }
      }
    } catch (err) {
      setMessages((prev) => {
        const copy = [...prev];
        const last = { ...copy[copy.length - 1] };
        last.blocks = [
          ...last.blocks,
          { type: "error", data: { message: `Network error: ${err}` } },
        ];
        copy[copy.length - 1] = last;
        return copy;
      });
    }

    setStreaming(false);
    setTurnCount((c) => c + 1);
    inputRef.current?.focus();
  }, [input, streaming, tenantId, sessionId, turnCount]);

  const resetConversation = () => {
    setMessages([]);
    setSessionId(crypto.randomUUID());
    setTurnCount(0);
    inputRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-4 py-2">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" asChild>
            <Link to="/">
              <ArrowLeft className="mr-1 h-4 w-4" />
              Back to dashboard
            </Link>
          </Button>
          <div className="flex items-center gap-2">
            <MessageSquare className="h-5 w-5 text-primary" />
            <span className="font-semibold">
              Chat{tenantQ.data ? ` — ${tenantQ.data.name}` : ""}
            </span>
            {tenantQ.data && (
              <Badge variant="default">{tenantQ.data.environment}</Badge>
            )}
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={resetConversation}>
          <RotateCcw className="mr-1 h-3.5 w-3.5" />
          New conversation
        </Button>
      </div>

      {/* Message area */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center text-muted-foreground space-y-3">
            <MessageSquare className="h-12 w-12 opacity-30" />
            <p className="text-lg font-medium">Ask anything about this Zuora tenant</p>
            <p className="text-sm max-w-md">
              Claude has full access to the Zuora MCP — query accounts,
              subscriptions, products, or even create test data. Try
              "show me the 5 most recent subscriptions" or "how many active accounts are there?"
            </p>
          </div>
        )}

        {messages.map((msg, idx) => (
          <MessageBubble key={idx} message={msg} streaming={streaming && idx === messages.length - 1} />
        ))}

        {streaming && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>Claude is working…</span>
          </div>
        )}
      </div>

      {/* Input bar */}
      <div className="border-t p-4">
        <div className="relative mx-auto max-w-3xl">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about this Zuora tenant…"
            rows={1}
            className="w-full resize-none rounded-lg border bg-background px-4 py-3 pr-12 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            disabled={streaming}
          />
          <Button
            className="absolute bottom-2 right-2"
            size="icon"
            onClick={sendMessage}
            disabled={!input.trim() || streaming}
          >
            <Send className="h-4 w-4" />
          </Button>
        </div>
        <p className="mt-1 text-center text-[0.65rem] text-muted-foreground">
          Enter to send · Shift+Enter for newline · costs apply per message
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Message bubble
// ---------------------------------------------------------------------------

function MessageBubble({
  message,
  streaming,
}: {
  message: ChatMessage;
  streaming: boolean;
}) {
  const isUser = message.role === "user";

  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[80%] rounded-lg px-4 py-3 text-sm",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-card border"
        )}
      >
        {message.blocks.map((evt, i) => (
          <BlockRenderer key={i} evt={evt} />
        ))}
        {!isUser && !streaming && message.cost_usd != null && (
          <div className="mt-2 text-[0.65rem] text-muted-foreground">
            ${message.cost_usd.toFixed(4)}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Block renderer
// ---------------------------------------------------------------------------

function BlockRenderer({ evt }: { evt: SseEvent }) {
  switch (evt.type) {
    case "text":
      return (
        <div className="whitespace-pre-wrap break-words">
          {String(evt.data.text ?? "")}
        </div>
      );
    case "tool_use":
      return <ToolUseCard evt={evt} />;
    case "tool_result":
      return <ToolResultCard evt={evt} />;
    case "thinking":
      return (
        <div className="my-1 flex items-center gap-1.5 text-xs text-muted-foreground italic">
          <Loader2 className="h-3 w-3 animate-spin" />
          thinking…
        </div>
      );
    case "error":
      return (
        <div className="rounded bg-destructive/20 p-2 text-xs text-destructive">
          {String(evt.data.message ?? "Unknown error")}
        </div>
      );
    case "done":
      return null; // handled by MessageBubble's cost display
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Tool-use card (expandable)
// ---------------------------------------------------------------------------

function ToolUseCard({ evt }: { evt: SseEvent }) {
  const [expanded, setExpanded] = useState(false);
  const name = String(evt.data.name ?? "?");
  const input = evt.data.input as Record<string, unknown> | undefined;

  // Compact one-liner from input
  const snippet = input
    ? Object.entries(input)
        .slice(0, 3)
        .map(([k, v]) => {
          let s = typeof v === "string" ? v : JSON.stringify(v);
          if (s.length > 60) s = s.slice(0, 60) + "…";
          return `${k}=${s}`;
        })
        .join(", ")
    : "";

  return (
    <div className="my-1.5 rounded border bg-blue-500/5 p-2">
      <button
        className="flex w-full items-center gap-1.5 text-left text-xs font-medium text-blue-400"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0" />
        )}
        <span className="font-semibold">{name}</span>
        {!expanded && snippet && (
          <span className="ml-1 truncate font-normal opacity-70">({snippet})</span>
        )}
      </button>
      {expanded && input && (
        <pre className="mt-1.5 max-h-60 overflow-auto rounded bg-muted/40 p-2 text-[0.65rem] text-muted-foreground">
          {JSON.stringify(input, null, 2)}
        </pre>
      )}
    </div>
  );
}

function ToolResultCard({ evt }: { evt: SseEvent }) {
  const [expanded, setExpanded] = useState(false);
  const content = String(evt.data.content ?? "");
  const isError = Boolean(evt.data.is_error);
  const preview = content.slice(0, 120) + (content.length > 120 ? "…" : "");

  return (
    <div
      className={cn(
        "my-1 rounded border p-2 text-xs",
        isError ? "border-destructive/30 bg-destructive/5" : "bg-muted/30"
      )}
    >
      <button
        className="flex w-full items-center gap-1.5 text-left font-medium"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDown className="h-3 w-3 shrink-0" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0" />
        )}
        <span className={isError ? "text-destructive" : "text-muted-foreground"}>
          {isError ? "✗ tool error" : "✓ result"}
        </span>
        {!expanded && (
          <span className="ml-1 truncate font-normal opacity-60">{preview}</span>
        )}
      </button>
      {expanded && (
        <pre className="mt-1.5 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded bg-muted/40 p-2 text-[0.65rem]">
          {content}
        </pre>
      )}
    </div>
  );
}
