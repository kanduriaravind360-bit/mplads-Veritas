import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import * as ToastPrimitive from "@radix-ui/react-toast";
import { CheckCircle2, AlertTriangle, X } from "lucide-react";
import { cn } from "@/lib/utils";

type ToastKind = "success" | "error" | "info";
interface ToastItem {
  id: number;
  kind: ToastKind;
  title: string;
  body?: string;
}

const ToastContext = createContext<(kind: ToastKind, title: string, body?: string) => void>(() => undefined);

export function Toaster({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((kind: ToastKind, title: string, body?: string) => {
    setItems((list) => [...list.slice(-3), { id: Date.now() + Math.random(), kind, title, body }]);
  }, []);
  const value = useMemo(() => push, [push]);

  return (
    <ToastContext.Provider value={value}>
      <ToastPrimitive.Provider swipeDirection="right" duration={4500}>
        {children}
        {items.map((item) => (
          <ToastPrimitive.Root
            key={item.id}
            onOpenChange={(open) => !open && setItems((list) => list.filter((x) => x.id !== item.id))}
            className={cn(
              "flex items-start gap-3 rounded-lg border bg-raised p-4 text-sm shadow-pop",
              item.kind === "error" ? "border-danger/40" : "border-line",
            )}
          >
            {item.kind === "error" ? (
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-danger" />
            ) : (
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" />
            )}
            <div className="min-w-0 flex-1">
              <ToastPrimitive.Title className="font-medium text-ink">{item.title}</ToastPrimitive.Title>
              {item.body ? (
                <ToastPrimitive.Description className="mt-1 text-muted">{item.body}</ToastPrimitive.Description>
              ) : null}
            </div>
            <ToastPrimitive.Close aria-label="Dismiss" className="text-muted hover:text-ink">
              <X className="size-4" />
            </ToastPrimitive.Close>
          </ToastPrimitive.Root>
        ))}
        <ToastPrimitive.Viewport className="fixed bottom-6 right-6 z-[90] flex w-[380px] max-w-[92vw] flex-col gap-2 outline-none" />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
