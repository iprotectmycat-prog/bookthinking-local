/**
 * 体裁专属字段的展示规则。
 *
 * 后端把这些字段统一存在一个 JSON 列里（四套体裁各有 3-5 个字段，若各自建列会让
 * 表膨胀到 30 多列且大部分为空）。代价是前端拿到的是一个开放对象，所以展示顺序和
 * 标签都必须由这里显式声明——照 `Object.entries` 的顺序渲染，会让同一体裁的两章
 * 出现不同的字段排列。
 *
 * 未在此登记的键一律不显示：后端白名单已经过滤过一轮，这里是第二道，确保新增体裁
 * 字段时必须同时想清楚它在界面上叫什么。
 */

export type GenreFieldValue = string | string[];

type FieldSpec = {
  key: string;
  label: string;
};

// 每套体裁内的顺序即渲染顺序，按「读者先想知道什么」排，不按字母序。
const FIELD_SPECS: Record<string, FieldSpec[]> = {
  narrative: [
    { key: "timeline_anchor", label: "发生时间" },
    { key: "attribution", label: "作者的归因" },
    { key: "counterfactual", label: "如果不这样会怎样" },
  ],
  propositional: [
    { key: "grounds_type", label: "论据类型" },
    { key: "scope_condition", label: "适用条件" },
    { key: "rebuttal", label: "作者回应的反对意见" },
  ],
  practical: [
    { key: "action_steps", label: "可执行步骤" },
    { key: "precondition", label: "前置条件" },
    { key: "failure_mode", label: "常见失效场景" },
    { key: "applies_to", label: "适用人群" },
  ],
  scholarly: [
    { key: "research_question", label: "研究问题" },
    { key: "method", label: "方法" },
    { key: "data_basis", label: "证据基础" },
    { key: "claim_strength", label: "结论强度" },
    { key: "limitation", label: "作者自陈的局限" },
  ],
};

// 取值是固定枚举的字段，翻成中文再显示。模型按英文枚举输出，直接渲染会让界面上
// 出现 "empirical" 这种词。
const VALUE_LABELS: Record<string, Record<string, string>> = {
  attribution: {
    explicit: "明确指出成因",
    implied: "通过叙述暗示",
    none: "只叙述，未归因",
  },
  grounds_type: {
    empirical: "实证数据",
    case: "案例",
    analogy: "类比",
    authority: "权威引用",
    thought_experiment: "思想实验",
    deduction: "逻辑推演",
    none: "未给出论据",
  },
  claim_strength: {
    proves: "证明",
    indicates: "表明",
    suggests: "提示",
    cannot_rule_out: "不能排除",
  },
};

export type GenreFieldEntry = {
  key: string;
  label: string;
  value: string | string[];
};

export function genreFieldEntries(
  genreFields: Record<string, unknown> | undefined,
  genre: string | null | undefined,
): GenreFieldEntry[] {
  if (!genreFields) return [];
  const specs = FIELD_SPECS[genre ?? ""] ?? [];
  const entries: GenreFieldEntry[] = [];
  for (const spec of specs) {
    const raw = genreFields[spec.key];
    if (Array.isArray(raw)) {
      const items = raw.map((item) => String(item).trim()).filter(Boolean);
      if (items.length > 0) entries.push({ key: spec.key, label: spec.label, value: items });
      continue;
    }
    if (typeof raw !== "string") continue;
    const text = raw.trim();
    // 后端对「作者没说」的字段存空字符串，展示时应当整条隐藏而不是留一个空标签。
    if (!text) continue;
    entries.push({ key: spec.key, label: spec.label, value: VALUE_LABELS[spec.key]?.[text] ?? text });
  }
  return entries;
}
