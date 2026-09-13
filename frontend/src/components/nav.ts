import {
  Activity,
  Banknote,
  BarChart3,
  Briefcase,
  GraduationCap,
  SlidersHorizontal,
  Clock3,
  Copy,
  FileUp,
  Gauge,
  Inbox,
  Landmark,
  Map,
  Network,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import type { Role } from "@/lib/types";

export interface NavItem {
  to: string;
  key: string;
  icon: LucideIcon;
  roles?: Role[];
  keywords?: string;
}

export interface NavGroup {
  key: string;
  items: NavItem[];
}

const REVIEWERS: Role[] = ["MINISTRY", "STATE", "DISTRICT"];

export const NAV: NavGroup[] = [
  {
    key: "overview",
    items: [
      { to: "/", key: "command", icon: Gauge, keywords: "home dashboard kpi" },
      { to: "/map", key: "map", icon: Map, keywords: "district choropleth geography" },
      { to: "/money", key: "money", icon: Banknote, keywords: "money at risk treemap value" },
    ],
  },
  {
    key: "review",
    items: [
      { to: "/alerts", key: "alerts", icon: Inbox, keywords: "queue review inbox" },
      { to: "/cases", key: "cases", icon: Briefcase, roles: REVIEWERS, keywords: "investigation case brief pdf" },
      { to: "/duplicates", key: "duplicates", icon: Copy, keywords: "duplicate pairs split" },
      { to: "/network", key: "network", icon: Network, keywords: "vendor hhi benford concentration" },
    ],
  },
  {
    key: "monitor",
    items: [
      { to: "/delays", key: "delays", icon: Clock3, keywords: "delay early warning lapse" },
      { to: "/compliance", key: "compliance", icon: ShieldCheck, keywords: "rules completeness" },
      { to: "/trends", key: "trends", icon: BarChart3, keywords: "monthly march category cost" },
    ],
  },
  {
    key: "portfolio",
    items: [{ to: "/portfolio", key: "mp", icon: Landmark, keywords: "constituency mp member" }],
  },
  {
    key: "system",
    items: [
      { to: "/models", key: "models", icon: Activity, keywords: "recall precision holdout metrics" },
      { to: "/simulator", key: "simulator", icon: SlidersHorizontal, roles: REVIEWERS, keywords: "threshold weights what if" },
      { to: "/learning", key: "learning", icon: GraduationCap, roles: REVIEWERS, keywords: "verdicts reranker feedback" },
      { to: "/ingest", key: "ingest", icon: FileUp, roles: REVIEWERS, keywords: "upload csv score" },
    ],
  },
];

export function navFor(role: Role | undefined): NavGroup[] {
  return NAV.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.roles || (role && item.roles.includes(role))),
  })).filter((group) => group.items.length > 0);
}
