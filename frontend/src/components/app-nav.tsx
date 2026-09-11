"use client";

import { ScanLine } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "Análisis" },
  { href: "/configuracion", label: "Configuración" },
] as const;

export function AppNav() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-40 border-b border-border/60 bg-background/90 backdrop-blur-md">
      <div className="mx-auto flex h-12 max-w-7xl items-center gap-5 px-4 sm:px-6 lg:px-8">
        <Link
          href="/"
          className="flex shrink-0 cursor-pointer items-center gap-2 text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-[0_0_16px_oklch(0.7_0.18_145/0.18)]">
            <ScanLine className="size-3.5" aria-hidden="true" />
          </span>
          <span className="hidden text-sm font-semibold tracking-tight sm:inline">
            Football Ads Detector
          </span>
        </Link>
        <nav aria-label="Principal" className="flex min-w-0 flex-1 items-center gap-1">
          {LINKS.map((link) => {
            const active =
              link.href === "/"
                ? pathname === "/"
                : pathname.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "cursor-pointer rounded-md px-2.5 py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  active
                    ? "bg-primary/10 font-medium text-primary"
                    : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                )}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
        <Badge
          variant="outline"
          className="hidden gap-2 border-primary/25 bg-primary/5 px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.16em] text-primary sm:inline-flex"
        >
          <span className="size-1.5 rounded-full bg-primary shadow-[0_0_8px_currentColor]" />
          CPU / local
        </Badge>
      </div>
    </header>
  );
}
