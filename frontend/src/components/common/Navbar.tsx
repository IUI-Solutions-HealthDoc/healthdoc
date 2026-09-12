"use client";

import { Menu, LogOut, User } from "lucide-react";
import { REALM_ROLE_LABELS } from "@/features/admin/constants";
import { useAuth } from "@/providers/auth-provider";
import { HealthDocBrand } from "./HealthDocBrand";

interface NavbarProps {
  open: boolean;
  setOpen: React.Dispatch<React.SetStateAction<boolean>>;
}

export default function Navbar({ open, setOpen }: NavbarProps) {
  const { user, logout } = useAuth();
  const roleLabel = user?.role
    ? (REALM_ROLE_LABELS[user.role] ?? user.role)
    : "Unassigned";

  return (
    <header
      className="fixed top-0 left-0 right-0 z-50 flex h-16 items-center justify-between border-b border-border/80 bg-card/95 px-5 backdrop-blur-md transition-all sm:px-6"
      style={{
        boxShadow: "0 1px 3px rgba(0, 31, 84, 0.05), 0 1px 2px rgba(0, 0, 0, 0.03)",
      }}
    >
      <div className="flex items-center gap-3 sm:gap-4">
        <button
          type="button"
          onClick={() => setOpen((prev) => !prev)}
          className="rounded-lg p-2 text-foreground/80 transition-colors hover:bg-muted hover:text-foreground focus:outline-none focus:ring-2 focus:ring-primary/20"
          aria-label="Toggle menu"
          aria-controls="workspace-sidebar"
          aria-expanded={open}
        >
          <Menu size={20} />
        </button>

        <HealthDocBrand
          size={38}
          preload
          subtitle="HMIS"
          nameClassName="text-lg font-bold tracking-tight text-[#001F54] dark:text-blue-200"
          className="text-[#001F54]"
        />

        <div className="hidden items-center gap-2 border-l border-border/70 pl-4 md:flex">
          <div className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-xs font-semibold text-foreground/75 uppercase tracking-wider">
            Clinical System Online
          </span>
        </div>
      </div>

      <div className="flex items-center gap-3 sm:gap-4">
        <div className="flex items-center gap-3 rounded-full border border-border/80 bg-muted/40 py-1 pl-1.5 pr-3 transition-colors hover:bg-muted/70">
          <div
            className="flex h-8 w-8 items-center justify-center rounded-full bg-[#001F54] text-white shadow-sm"
          >
            <User size={15} />
          </div>
          <div className="text-left">
            <p className="text-xs font-semibold leading-tight text-foreground">
              {user?.name || roleLabel}
            </p>
            <p className="text-[10px] font-medium leading-tight text-foreground/70">
              {roleLabel}
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={() => void logout()}
          className="flex h-9 w-9 items-center justify-center rounded-full border border-border/80 text-muted-foreground transition-all hover:border-red-200 hover:bg-red-50 hover:text-red-600 focus:outline-none focus:ring-2 focus:ring-red-200 dark:hover:bg-red-950/30"
          aria-label="Sign out"
          title="Sign out of HealthDoc"
        >
          <LogOut size={16} />
        </button>
      </div>
    </header>
  );
}
