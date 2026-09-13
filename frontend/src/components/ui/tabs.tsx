import type { ReactNode } from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

export const Tabs = TabsPrimitive.Root;
export const TabsContent = ({ className, ...props }: TabsPrimitive.TabsContentProps) => (
  <TabsPrimitive.Content className={cn("focus:outline-none", className)} {...props} />
);

export function TabsList({
  tabs,
  className,
}: {
  tabs: { value: string; label: ReactNode; count?: number }[];
  className?: string;
}) {
  return (
    <TabsPrimitive.List className={cn("flex gap-1 border-b border-line", className)}>
      {tabs.map((tab) => (
        <TabsPrimitive.Trigger
          key={tab.value}
          value={tab.value}
          className="relative -mb-px flex items-center gap-2 border-b-2 border-transparent px-3 py-2.5 text-sm font-medium text-muted transition-colors hover:text-ink data-[state=active]:border-saffron data-[state=active]:text-ink"
        >
          {tab.label}
          {tab.count !== undefined ? (
            <span className="num rounded-full bg-raised px-1.5 text-2xs text-muted">{tab.count}</span>
          ) : null}
        </TabsPrimitive.Trigger>
      ))}
    </TabsPrimitive.List>
  );
}
