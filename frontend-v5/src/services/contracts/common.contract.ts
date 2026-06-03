/**
 * Common contract primitives shared across endpoints.
 *
 * These mirror OpenAPI `components/schemas` definitions verbatim.
 * Field names are snake_case (matching the wire), conversion happens in mappers.
 */
import { z } from "zod";

export const ISODate = z.string().regex(/^\d{4}-\d{2}-\d{2}/, "expected ISO date");
export const ISODateTime = z.string();
export const Rupees = z.number();                                      // `*_rs` fields
export const Percentage = z.number();                                  // `*_pct` (decimal, e.g. 0.187 = 18.7%)

export const ErrorEnvelope = z.object({
  detail: z.union([
    z.string(),
    z.array(z.object({
      msg: z.string(),
      loc: z.array(z.union([z.string(), z.number()])).optional(),
      type: z.string().optional(),
    })),
  ]).optional(),
});

export type ApiErrorEnvelope = z.infer<typeof ErrorEnvelope>;
