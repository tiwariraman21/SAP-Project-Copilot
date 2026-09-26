"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import "./companion.css";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Source = { kind: string; label: string; detail?: string; status?: string };
type Turn = { question: string; answer: string; sources: Source[]; asked_at?: string | null };
type Context = {
  project_id: string;
  project_name: string;
  document_name?: string;
  page_count?: number;
  requirements_count?: number;
  available_sources: Source[];
  suggested_questions: string[];
  history: Turn[];
  guardrail: string;
};

export default function CompanionChat({
  projectId,
  projectName,
  open: controlledOpen,
  onOpenChange,
}: {
  projectId: string;
  projectName: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const [internalOpen, setInternalOpen] = useState(false);
  const isOpen = controlledOpen !== undefined ? controlledOpen : internalOpen;

  const setChatOpen = (next: boolean) => {
    if (onOpenChange) onOpenChange(next);
    else setInternalOpen(next);
  };

  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [context, setContext] = useState<Context | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API}/api/projects/${projectId}/companion`)
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail || "Companion could not be loaded");
        return body as Context;
      })
      .then((value) => {
        if (cancelled) return;
        setContext(value);
        setTurns(value.history || []);
      })
      .catch((problem) => {
        if (!cancelled) setError(problem instanceof Error ? problem.message : "Companion could not be loaded");
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => {
    if (isOpen) {
      setTimeout(() => {
        listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
        inputRef.current?.focus();
      }, 50);
    }
  }, [turns, isOpen]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        setChatOpen(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen]);

  async function ask(text: string) {
    const next = text.trim();
    if (!next || busy) return;
    setBusy(true);
    setError("");
    setQuestion("");
    try {
      const response = await fetch(`${API}/api/projects/${projectId}/companion/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: next }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "The companion could not answer");
      setTurns((previous) => [
        ...previous,
        { question: body.question, answer: body.answer, sources: body.sources || [], asked_at: body.asked_at },
      ]);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "The companion could not answer");
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    ask(question);
  }

  const docName = context?.document_name || "Uploaded BRD";

  function formatContent(text: string) {
    const lines = text.split("\n");
    return lines.map((line, idx) => {
      const trimmed = line.trim();
      if (!trimmed) return <div key={idx} className="lineBreak" />;

      if (trimmed.startsWith("### ")) {
        return (
          <strong key={idx} className="chatHeading">
            {renderFormattedInline(trimmed.slice(4))}
          </strong>
        );
      }
      if (trimmed.startsWith("## ")) {
        return (
          <strong key={idx} className="chatHeading" style={{ fontSize: "15px" }}>
            {renderFormattedInline(trimmed.slice(3))}
          </strong>
        );
      }
      if (trimmed.startsWith("---") || trimmed.startsWith("━━━━")) {
        return <hr key={idx} className="chatDivider" />;
      }
      if (trimmed.startsWith("• ") || trimmed.startsWith("- ") || trimmed.startsWith("* ") || trimmed.startsWith("✦ ")) {
        const content = trimmed.replace(/^[•\-*✦]\s*/, "");
        return (
          <li key={idx} className="chatBullet">
            {renderFormattedInline(content)}
          </li>
        );
      }
      if (trimmed.startsWith("> ")) {
        return (
          <blockquote key={idx} className="chatQuote">
            {renderFormattedInline(trimmed.slice(2))}
          </blockquote>
        );
      }
      if (trimmed.startsWith("**") && trimmed.endsWith("**") && trimmed.length > 4 && !trimmed.slice(2, -2).includes("**")) {
        return (
          <strong key={idx} className="chatSubHeading">
            {trimmed.slice(2, -2)}
          </strong>
        );
      }
      return <p key={idx} className="chatPara">{renderFormattedInline(trimmed)}</p>;
    });
  }

  function renderFormattedInline(content: string) {
    // Regex matches bold **...**, code `...`, and plaintext
    const parts = content.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
    return parts.map((part, i) => {
      if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
        return <strong key={i} style={{ color: "#ffffff", fontWeight: 700 }}>{part.slice(2, -2)}</strong>;
      }
      if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
        return <code key={i} className="chatCodeInline">{part.slice(1, -1)}</code>;
      }
      return part;
    });
  }

  const defaultSuggestions = [
    "how many level of approvers are there",
    "What is the end-to-end process flow in this BRD?",
    "What SAP Fiori screens and floorplans are defined?",
    "what is my current progress status in Functional area?",
    "Which requirements are Must Have?",
  ];

  return (
    <div className="companionDock">
      {isOpen && (
        <div className="companionPanel chatDrawer" role="dialog" aria-label="AI Companion Chat">
          <header className="chatHeader">
            <div className="headerInfo">
              <div className="headerBadge">
                <span className="scAvatar">SC</span>
                <div>
                  <div className="titleRow">
                    <h3>AI Companion</h3>
                    <span className="liveDot">● Grounded in BRD & FSD</span>
                  </div>
                  <small title={docName}>{docName}</small>
                </div>
              </div>
            </div>
            <button
              type="button"
              className="companionClose"
              onClick={() => setChatOpen(false)}
              aria-label="Close companion"
              title="Close chat (Esc)"
            >
              ✕
            </button>
          </header>

          <div className="companionSources">
            <span className="sourceTag ready">
              📄 {docName}
            </span>
            {(context?.available_sources || []).filter(s => s.kind !== "brd").map((source) => (
              <span key={source.kind} className={`sourceTag ${source.status === "ready" ? "ready" : "missing"}`}>
                {source.kind === "fsd" ? "⚙️ " : source.kind === "backlog" ? "📊 " : source.kind === "test_cases" ? "🧪 " : "📋 "}
                {source.label}
              </span>
            ))}
          </div>

          <div className="companionLog" ref={listRef}>
            {turns.length === 0 ? (
              <div className="welcomePrompt">
                <div className="welcomeIcon">💬</div>
                <h4>Ask about this project's BRD & FSD</h4>
                <p>
                  I have full context of <b>{docName}</b> and generated delivery specifications. Ask about multi-level approvers, process flows, SAP Fiori floorplans, or planning progress.
                </p>
                <div className="quickPrompts">
                  <p className="quickLabel">Suggested questions:</p>
                  {defaultSuggestions.map((item) => (
                    <button type="button" key={item} disabled={busy} onClick={() => ask(item)} className="quickChip">
                      <span>✦</span> {item}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              turns.map((turn, index) => (
                <div key={`${turn.asked_at || "turn"}-${index}`} className="turnGroup">
                  <div className="messageUser">
                    <div className="userBubble">{turn.question}</div>
                  </div>
                  <div className="messageAssistant">
                    <div className="assistantAvatar">SC</div>
                    <div className="assistantContent">
                      <div className="bubbleText">{formatContent(turn.answer)}</div>
                      {!!turn.sources?.length && (
                        <div className="companionCite">
                          {turn.sources.map((source, sourceIndex) => (
                            <span key={`${source.kind}-${sourceIndex}`} className="citeChip" title={source.detail}>
                              <b>{source.label}</b>
                              {source.detail ? ` · ${source.detail}` : ""}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))
            )}
            {busy && (
              <div className="messageAssistant">
                <div className="assistantAvatar">SC</div>
                <div className="assistantContent typingBubble">
                  <span className="dot" />
                  <span className="dot" />
                  <span className="dot" />
                  <small>Consulting BRD context, business rules, and FSD specifications…</small>
                </div>
              </div>
            )}
          </div>

          {turns.length > 0 && (
            <div className="companionChips">
              {defaultSuggestions.slice(0, 3).map((item) => (
                <button type="button" key={item} disabled={busy} onClick={() => ask(item)}>
                  {item}
                </button>
              ))}
            </div>
          )}

          {error && <p className="error banner">{error}</p>}

          <form className="chatInputForm" onSubmit={onSubmit}>
            <input
              ref={inputRef}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask about approval levels, BRD rules, FSD screens..."
              disabled={busy}
            />
            <button type="submit" disabled={busy || !question.trim()} className="sendBtn" title="Send (Enter)">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13"></line>
                <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
              </svg>
            </button>
          </form>
        </div>
      )}

      {/* Floating high-contrast trigger */}
      <button
        type="button"
        className={`companionFab ${isOpen ? "open" : ""}`}
        onClick={() => setChatOpen(!isOpen)}
        aria-label={isOpen ? "Close AI Companion" : "Open AI Companion"}
        title="Chat with AI Companion (Grounded in uploaded BRD & FSD)"
      >
        <svg className="chatIcon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
          <path d="M8 10h.01"></path>
          <path d="M12 10h.01"></path>
          <path d="M16 10h.01"></path>
        </svg>
        <span className="fabText">{isOpen ? "Close" : "AI Companion"}</span>
      </button>
    </div>
  );
}
