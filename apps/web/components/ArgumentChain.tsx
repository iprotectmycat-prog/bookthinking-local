export function ArgumentChain({ steps }: { steps: string[] }) {
  if (!steps.length) return <p className="chain-empty">本章未提取到清晰的分步论证。</p>;
  return (
    <ol className="argument-chain is-vertical is-compact" aria-label="作者论证链">
      {steps.map((step, index) => <li key={`${index}-${step}`}><span className="argument-step-number is-outlined">{index + 1}</span><p>{step}</p></li>)}
    </ol>
  );
}
