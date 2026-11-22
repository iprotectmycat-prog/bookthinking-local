import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ArgumentChain } from "../components/ArgumentChain";

describe("ArgumentChain", () => {
  it("uses compact outlined number markers in a vertical sequence", () => {
    render(<ArgumentChain steps={["第一步", "第二步"]} />);

    expect(screen.getByRole("list", { name: "作者论证链" })).toHaveClass("is-vertical", "is-compact");
    expect(screen.getByText("1")).toHaveClass("argument-step-number", "is-outlined");
  });
});
