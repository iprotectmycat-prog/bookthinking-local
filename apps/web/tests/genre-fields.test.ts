import { describe, expect, it } from "vitest";

import { genreFieldEntries } from "../lib/genre-fields";

describe("genreFieldEntries", () => {
  it("orders fields by the spec, not by the object's key order", () => {
    // Iterating the raw object would let two chapters of one book show the same
    // fields in different orders, depending on what the model emitted first.
    const entries = genreFieldEntries(
      { limitation: "样本偏小", research_question: "组织为何僵化" },
      "scholarly",
    );

    expect(entries.map((entry) => entry.key)).toEqual(["research_question", "limitation"]);
  });

  it("translates enumerated values into Chinese", () => {
    const entries = genreFieldEntries({ grounds_type: "empirical" }, "propositional");

    expect(entries).toEqual([{ key: "grounds_type", label: "论据类型", value: "实证数据" }]);
  });

  it("keeps an unrecognised enumerated value rather than hiding it", () => {
    const entries = genreFieldEntries({ claim_strength: "hedged" }, "scholarly");

    expect(entries[0].value).toBe("hedged");
  });

  it("hides fields the author never addressed", () => {
    // The backend stores "" for absent fields, which would otherwise render as a
    // label with nothing under it.
    expect(genreFieldEntries({ precondition: "", failure_mode: "   " }, "practical")).toEqual([]);
  });

  it("keeps action_steps as an ordered list", () => {
    const entries = genreFieldEntries({ action_steps: ["列出待办", "删掉无关项"] }, "practical");

    expect(entries[0].value).toEqual(["列出待办", "删掉无关项"]);
  });

  it("ignores fields belonging to another genre", () => {
    expect(genreFieldEntries({ action_steps: ["x"] }, "narrative")).toEqual([]);
  });

  it("renders nothing when the genre is unknown or missing", () => {
    expect(genreFieldEntries({ grounds_type: "case" }, null)).toEqual([]);
    expect(genreFieldEntries(undefined, "propositional")).toEqual([]);
  });
});
