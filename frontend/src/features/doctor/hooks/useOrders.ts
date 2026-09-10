"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { toast } from "@/components/ui/toast";
import { getUserFacingError } from "@/lib/api";
import { listOrders, placeOrder } from "../api";
import type { ActiveEncounter, DraftOrder, PlacedOrder } from "../types";

export function useOrders(encounter: ActiveEncounter) {
  const [placed, setPlaced] = useState<PlacedOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const live = useRef(false);
  const writing = useRef(false);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);

  useEffect(() => {
    live.current = true;
    return () => { live.current = false; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPlaced([]);
    void listOrders(encounter.id)
      .then((rows) => {
        if (!cancelled) setPlaced(rows);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setError(getUserFacingError(error, "Orders could not be loaded. Please retry."));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [encounter.id, revision]);

  const addOrder = useCallback(
    async (draft: Omit<DraftOrder, "tempId">, idempotencyKey: string) => {
      if (writing.current || encounter.ended_at) return false;
      writing.current = true;
      setAdding(true);
      try {
        // Two calls: the order header, then its clinical detail row.
        const result = await placeOrder(
          draft,
          {
            encounter_id: encounter.id,
            patient_id: encounter.patient_id,
          },
          idempotencyKey,
        );
        if (!live.current) return false;
        setPlaced((prev) => [...prev.filter((row) => row.id !== result.id), result]);
        if (result.detail_status === "failed") {
          toast.error(
            `${result.order_number} was created, but its department item failed. Do not reorder; contact support.`,
          );
        } else if (result.fulfilment_mode === "external_referral") {
          toast.success(`${result.order_number} is referred externally; no local department item was created.`);
        } else {
          toast.success(
            `${result.item_label} ordered${
              result.accession_number ? ` · ${result.accession_number}` : ""
            }`,
          );
        }
        return true;
      } catch (e) {
        if (live.current) toast.error(getUserFacingError(e, "Order submission was not confirmed. Retry the same action; do not create another order."));
        return false;
      } finally {
        writing.current = false;
        if (live.current) setAdding(false);
      }
    },
    [encounter],
  );

  return { placed, loading, adding, error, refresh, addOrder };
}
