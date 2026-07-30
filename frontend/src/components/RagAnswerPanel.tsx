/**
 * Strategy-C answer surface: the generative (RAG) answer + its citations.
 *
 * Shown when the router routes a question to RAG (no scenario fits well).
 * Mirrors backend RagAnswer (backend/rag_answerer.py).
 */
import { RagAnswer } from "../types";

export function RagAnswerPanel({ rag, onClose }: { rag: RagAnswer; onClose: () => void }) {
  return (
    <section className="rag-panel" aria-label="Generative answer">
      <div className="rag-head">
        <span className="rag-eyebrow">
          {rag.grounded ? "Grounded answer · policy corpus" : "Generative answer · not grounded in policy"}
        </span>
        <button className="rag-close" type="button" onClick={onClose} aria-label="Dismiss">×</button>
      </div>

      <p className="rag-answer">{rag.answer}</p>

      {rag.citations.length > 0 && (
        <div className="rag-cites">
          <div className="rag-cites-head">Citations</div>
          {rag.citations.map((c) => (
            <div key={c.n} className="rag-cite" title={c.snippet}>
              <span className="rag-cite-n">[{c.n}]</span>
              <span className="rag-cite-title">{c.title}</span>
              <span className="rag-cite-score">{Math.round(c.score * 100)}%</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
