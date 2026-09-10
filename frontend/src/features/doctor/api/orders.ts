/** Real lab/radiology/procedure ordering against the server-owned encounter. */
import { api } from "@/lib/api";
import type {
  CreateLabOrderItemInput,
  CreateOrderInput,
  CreateProcedureInput,
  CreateRadiologyOrderItemInput,
  DraftOrder,
  OrderStatus,
  PlacedOrder,
} from "../types";

interface OrderResponse {
  id: string;
  order_number: string;
  ordered_at: string;
  status: OrderStatus;
  fulfilment_mode: "internal" | "external_referral" | null;
  completed_at: string | null;
  order_type: DraftOrder["order_type"];
  priority: DraftOrder["priority"];
}

interface OrderListResponse {
  items: OrderResponse[];
}

interface ProcedureResponse {
  id: string;
  order_id: string | null;
  procedure_name: string;
  setting: string;
}

interface ProcedureListResponse {
  items: ProcedureResponse[];
}

export async function listOrders(encounterId: string): Promise<PlacedOrder[]> {
  const encodedEncounterId = encodeURIComponent(encounterId);
  const [response, procedures] = await Promise.all([
    api<OrderListResponse>(`/orders?encounter_id=${encodedEncounterId}`),
    api<ProcedureListResponse>(`/procedures?encounter_id=${encodedEncounterId}`),
  ]);
  const procedureByOrder = new Map(
    procedures.items
      .filter((procedure): procedure is ProcedureResponse & { order_id: string } => procedure.order_id !== null)
      .map((procedure) => [procedure.order_id, procedure]),
  );

  return response.items.map((order) => {
    const procedure = procedureByOrder.get(order.id);
    return {
      id: order.id,
      order_number: order.order_number,
      order_type: order.order_type,
      priority: order.priority,
      status: order.status,
      fulfilment_mode: order.fulfilment_mode ?? null,
      completed_at: order.completed_at ?? null,
      ordered_at: order.ordered_at,
      item_label:
        procedure?.procedure_name ??
        `${order.order_type === "lab" ? "Lab" : order.order_type === "radiology" ? "Radiology" : "Clinical"} order`,
      detail_status: procedure ? "complete" : "header_only",
    };
  });
}

export async function createOrder(
  input: CreateOrderInput,
  idempotencyKey: string,
): Promise<OrderResponse> {
  return api<OrderResponse>("/orders", {
    method: "POST",
    body: JSON.stringify(input),
    idempotencyKey,
  });
}

export async function createLabOrderItem(
  input: CreateLabOrderItemInput,
  idempotencyKey: string,
): Promise<{ id: string; accession_number: string }> {
  const { order_id, ...body } = input;
  return api(`/pathology/order-items?order_id=${encodeURIComponent(order_id)}`, {
    method: "POST",
    body: JSON.stringify(body),
    idempotencyKey,
  });
}

export async function createRadiologyOrderItem(
  input: CreateRadiologyOrderItemInput,
  idempotencyKey: string,
): Promise<{ id: string; accession_number: string }> {
  const { order_id, ...body } = input;
  return api(`/radiology/order-items?order_id=${encodeURIComponent(order_id)}`, {
    method: "POST",
    body: JSON.stringify(body),
    idempotencyKey,
  });
}

export async function createProcedure(
  input: CreateProcedureInput,
  idempotencyKey: string,
): Promise<ProcedureResponse> {
  return api<ProcedureResponse>("/procedures", {
    method: "POST",
    body: JSON.stringify(input),
    idempotencyKey,
  });
}

/**
 * Creates the common header and then its department detail row.
 * A detail failure cannot roll back the committed header, so return the
 * partial state and prevent a blind retry from creating a duplicate order.
 */
export async function placeOrder(
  draft: Omit<DraftOrder, "tempId">,
  context: { encounter_id: string; patient_id: string },
  idempotencyKey: string,
): Promise<PlacedOrder> {
  if (
    draft.order_type !== "lab" &&
    draft.order_type !== "radiology" &&
    draft.order_type !== "procedure"
  ) {
    throw new Error(`Ordering ${draft.order_type} is not supported in this workflow.`);
  }

  let header = await createOrder(
    {
      encounter_id: context.encounter_id,
      patient_id: context.patient_id,
      order_type: draft.order_type,
      priority: draft.priority,
    },
    idempotencyKey,
  );
  const label =
    draft.order_type === "lab"
      ? draft.test_name?.trim() || "Lab test"
      : draft.order_type === "radiology"
        ? draft.scan_type?.trim() || "Radiology study"
        : draft.procedure_name?.trim() || "Procedure";

  // Legacy replay snapshots predate fulfilment_mode. Read the actual order
  // before calling a department; absence must never mean "internal".
  if (!header.fulfilment_mode) {
    header = await api<OrderResponse>(`/orders/${encodeURIComponent(header.id)}`);
  }
  const base = {
    id: header.id, order_number: header.order_number, order_type: header.order_type,
    priority: header.priority, status: header.status, ordered_at: header.ordered_at,
    fulfilment_mode: header.fulfilment_mode ?? null, completed_at: header.completed_at ?? null,
    item_label: label,
  };
  if (header.fulfilment_mode === "external_referral") {
    // No local accession or department item is promised for outside care.
    return { ...base, detail_status: "header_only" };
  }
  if (header.fulfilment_mode !== "internal") {
    return { ...base, detail_status: "failed", detail_error: "Fulfilment could not be confirmed. Refresh orders; do not reorder." };
  }

  try {
    const detail = draft.order_type === "lab"
      ? await createLabOrderItem(
          {
            order_id: header.id,
            test_name: label,
            sample_type: draft.sample_type ?? "",
          },
          `${idempotencyKey}:detail`,
        )
      : draft.order_type === "radiology"
        ? await createRadiologyOrderItem(
            {
              order_id: header.id,
              modality: draft.modality ?? "xray",
              scan_type: label,
            },
            `${idempotencyKey}:detail`,
          )
        : await createProcedure(
            {
              order_id: header.id,
              procedure_name: label,
              setting: draft.setting ?? "opd_minor",
            },
            `${idempotencyKey}:detail`,
          );

    return {
      ...base,
      accession_number: "accession_number" in detail ? detail.accession_number : undefined,
      item_label: label,
      detail_status: "complete",
    };
  } catch (error) {
    return {
      ...base,
      item_label: label,
      detail_status: "failed",
      detail_error: error instanceof Error ? error.message : "Department item creation failed",
    };
  }
}
