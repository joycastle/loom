// Slim admin-only runtime — replaces the former chat runtime (LoomRuntimeProvider
// + loom-actions + OnboardingProvider). The admin console has no chat/agent/AI
// state; it only needs a shared Loom client (the `ledger`) plus the record-detail
// drawer's open/close state. Views reach both through useLoom().

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { createLoomClient, type LoomClient } from "@/lib/loom-client";
import type { LoomClientMode } from "@/types/loom";

export type LoomContextValue = {
  // The full Loom client (mock or live). Every view reaches every endpoint
  // through it (browse reads + admin overview/action + skills + report material).
  ledger: LoomClient;
  mode: LoomClientMode;
  // Record-detail drawer control (shared so any list can open the drawer).
  openRecordId: string | null;
  openRecord: (id: string) => void;
  closeRecord: () => void;
};

const LoomContext = createContext<LoomContextValue | null>(null);

export function LoomProvider({
  mode,
  baseUrl = "",
  adminToken = "",
  children,
}: {
  mode: LoomClientMode;
  baseUrl?: string;
  adminToken?: string;
  children: ReactNode;
}) {
  const ledger = useMemo(
    () => createLoomClient({ mode, baseUrl, adminToken }),
    [mode, baseUrl, adminToken],
  );
  const [openRecordId, setOpenRecordId] = useState<string | null>(null);
  const openRecord = useCallback((id: string) => setOpenRecordId(id), []);
  const closeRecord = useCallback(() => setOpenRecordId(null), []);

  const value = useMemo<LoomContextValue>(
    () => ({ ledger, mode, openRecordId, openRecord, closeRecord }),
    [ledger, mode, openRecordId, openRecord, closeRecord],
  );

  return <LoomContext.Provider value={value}>{children}</LoomContext.Provider>;
}

export function useLoom(): LoomContextValue {
  const value = useContext(LoomContext);
  if (!value) throw new Error("useLoom must be used within a <LoomProvider>");
  return value;
}
