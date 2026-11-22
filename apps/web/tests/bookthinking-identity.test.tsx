import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import HomePage from "../app/page";

it("uses BookThinking and keeps account controls out of local mode", () => {
  render(<HomePage />);

  expect(screen.getByText("BookThinking")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "书架", level: 1 })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "账号" })).not.toBeInTheDocument();
});

it("defines readable dark settings controls", () => {
  const stylesheet = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8");

  expect(stylesheet).toContain(".settings-form input::placeholder");
  expect(stylesheet).toContain(".settings-form input:focus-visible");
});
