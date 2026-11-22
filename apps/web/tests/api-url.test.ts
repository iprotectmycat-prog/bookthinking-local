import { expect, it } from "vitest";

import { API_BASE_URL } from "../lib/api";

it("uses a same-origin path that does not trigger browser API filters", () => {
  expect(API_BASE_URL).toBe("/local");
});
