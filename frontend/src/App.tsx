import { FormEvent, startTransition, useEffect, useRef, useState } from "react";

import {
  clearChatHistory,
  fetchChatHistory,
  fetchQuestion,
  fetchStatus,
  fetchTopics,
  login,
  signup,
  streamChatResponse,
  submitAttempt,
} from "./lib/api";
import { useAppStore } from "./store/useAppStore";
import type { ChatEntry, QuestionItem, StatusResponse, SubmitResult, TopicMap, ModeMap } from "./types";

type AuthMode = "signup" | "login";

function accentClasses(accent: string): string {
  if (accent === "red") return "from-rose-500/18 to-rose-500/5 ring-rose-400/25";
  if (accent === "green") return "from-emerald-500/18 to-emerald-500/5 ring-emerald-400/25";
  if (accent === "gold") return "from-amber-400/18 to-amber-400/5 ring-amber-300/25";
  return "from-cyan-400/18 to-cyan-400/5 ring-cyan-300/25";
}

function providerLabel(provider: string): string {
  if (provider === "openai") return "OpenAI";
  if (provider === "anthropic") return "Anthropic";
  if (provider === "gemini") return "Gemini";
  if (provider === "local") return "Local";
  return "Auto";
}

function formatAssistantText(raw: string): string {
  let text = String(raw || "").replace(/\r\n/g, "\n").trim();
  if (!text) return "";
  text = text.replace(/```[a-zA-Z0-9_-]*\s*\n?/g, "").replace(/```/g, "");
  text = text.replace(/\*\*(.*?)\*\*/g, "$1");
  text = text.replace(/direct answer\s*:/gi, "");
  text = text.replace(/\bdirect answer\b/gi, "");
  ["Syntax/Core Concept", "Example", "Common Mistakes", "When to Use"].forEach((title) => {
    const re = new RegExp(`\\s*${title}\\s*:?\\s*`, "gi");
    text = text.replace(re, `\n\n${title}:\n`);
  });
  return text.replace(/\n{3,}/g, "\n\n").trim();
}

export default function App() {
  const {
    authUser,
    provider,
    selectedTopic,
    selectedMode,
    isChatOpen,
    setAuthUser,
    logout,
    setProvider,
    setSelection,
    clearSelection,
    setChatOpen,
  } = useAppStore();

  const [authMode, setAuthMode] = useState<AuthMode>("signup");
  const [authForm, setAuthForm] = useState({ username: "", password: "" });
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState("");
  const [authNotice, setAuthNotice] = useState("");
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [topics, setTopics] = useState<TopicMap>({});
  const [modes, setModes] = useState<ModeMap>({ mcq: "MCQ", coding: "Coding" });
  const [question, setQuestion] = useState<QuestionItem | null>(null);
  const [questionError, setQuestionError] = useState("");
  const [loadingQuestion, setLoadingQuestion] = useState(false);
  const [answer, setAnswer] = useState("");
  const [result, setResult] = useState<SubmitResult | null>(null);
  const [showSolution, setShowSolution] = useState(false);
  const [questionPosition, setQuestionPosition] = useState(0);
  const [bankSize, setBankSize] = useState(0);
  const [chatHistory, setChatHistory] = useState<ChatEntry[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);

  const chatPanelRef = useRef<HTMLDivElement | null>(null);
  const chatInputRef = useRef<HTMLTextAreaElement | null>(null);

  const resetPracticeState = () => {
    clearSelection();
    setQuestion(null);
    setQuestionError("");
    setAnswer("");
    setResult(null);
    setShowSolution(false);
    setQuestionPosition(0);
    setBankSize(0);
  };

  const loadMeta = async () => {
    const data = await fetchTopics();
    setTopics(data.topics ?? {});
    setModes(data.modes ?? { mcq: "MCQ", coding: "Coding" });
  };

  const loadStatus = async () => {
    const nextStatus = await fetchStatus();
    setStatus(nextStatus);
    if (provider === "auto") {
      setProvider(nextStatus.default_provider || "auto");
    }
  };

  const loadChatLog = async (userId: string) => {
    const data = await fetchChatHistory(userId);
    setChatHistory(data.history ?? []);
  };

  const loadQuestionAt = async (position: number) => {
    if (!authUser || !selectedTopic || !selectedMode) return;

    setLoadingQuestion(true);
    setQuestionError("");
    setResult(null);
    setShowSolution(false);
    setAnswer("");

    try {
      const nextQuestion = await fetchQuestion(selectedTopic, selectedMode, position);
      setQuestion(nextQuestion);
      setQuestionPosition(nextQuestion.position ?? position);
      setBankSize(nextQuestion.pool_size ?? 0);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not load question.";
      setQuestion(null);
      setQuestionError(message);
    } finally {
      setLoadingQuestion(false);
    }
  };

  useEffect(() => {
    void loadStatus();
  }, []);

  useEffect(() => {
    if (!authUser) {
      setTopics({});
      setChatHistory([]);
      resetPracticeState();
      return;
    }

    void loadMeta();
    void loadChatLog(authUser.user_id);
  }, [authUser]);

  useEffect(() => {
    if (!authUser || !selectedTopic || !selectedMode) return;
    void loadQuestionAt(0);
  }, [authUser, selectedTopic, selectedMode]);

  const handleAuthSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const username = authForm.username.trim();
    const password = authForm.password;

    if (!username || !password) {
      setAuthError("Enter username and password.");
      return;
    }

    setAuthLoading(true);
    setAuthError("");
    setAuthNotice("");

    try {
      if (authMode === "signup") {
        await signup(username, password);
        setAuthNotice("Account created. Log in with the same username and password.");
        setAuthForm({ username, password: "" });
        setAuthMode("login");
      } else {
        const user = await login(username, password);
        setAuthUser(user);
        setAuthForm({ username: user.username, password: "" });
      }
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Authentication failed.");
    } finally {
      setAuthLoading(false);
    }
  };

  const handleTopicModeSelect = (topic: string, mode: string) => {
    startTransition(() => {
      setSelection(topic, mode);
    });
  };

  const handleSubmitAttempt = async () => {
    if (!authUser || !question) return;

    setResult(null);
    try {
      const nextResult = await submitAttempt({
        user_id: authUser.user_id,
        topic: selectedTopic,
        mode: selectedMode,
        question_id: question.id,
        answer,
        provider,
      });
      setResult(nextResult);
      if (!nextResult.is_correct) {
        setShowSolution(false);
      }
    } catch (error) {
      setResult({
        is_correct: false,
        feedback: error instanceof Error ? error.message : "Could not submit answer.",
        solution: "",
        correct_answer: "",
        expected_approach: "",
      });
    }
  };

  const handleClearChat = async () => {
    if (!authUser) return;
    await clearChatHistory(authUser.user_id);
    setChatHistory([]);
    setChatInput("");
  };

  const focusChat = () => {
    setChatOpen(true);
    requestAnimationFrame(() => {
      chatPanelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      chatInputRef.current?.focus();
    });
  };

  const handleSendChat = async () => {
    if (!authUser || !chatInput.trim()) return;

    const message = chatInput.trim();
    const clientId = crypto.randomUUID();
    setChatInput("");
    setChatLoading(true);
    setChatOpen(true);

    setChatHistory((previous) => [
      ...previous,
      {
        client_id: clientId,
        user_id: authUser.user_id,
        user_message: message,
        assistant_message: "",
        related_suggestions: [],
        provider,
        created_at: new Date().toISOString(),
      },
    ]);

    try {
      await streamChatResponse(
        {
          user_id: authUser.user_id,
          message,
          topic: selectedTopic || null,
          mode: selectedMode || null,
          provider,
        },
        {
          onToken: (value) => {
            setChatHistory((previous) =>
              previous.map((entry) =>
                entry.client_id === clientId
                  ? { ...entry, assistant_message: `${entry.assistant_message}${value}` }
                  : entry,
              ),
            );
          },
          onDone: (event) => {
            setChatHistory((previous) =>
              previous.map((entry) =>
                entry.client_id === clientId
                  ? {
                      ...entry,
                      assistant_message: event.answer,
                      related_suggestions: event.related_suggestions ?? [],
                      provider: event.provider,
                    }
                  : entry,
              ),
            );
          },
        },
      );
    } catch (error) {
      const messageText = error instanceof Error ? error.message : "Chat failed.";
      setChatHistory((previous) =>
        previous.map((entry) =>
          entry.client_id === clientId
            ? {
                ...entry,
                assistant_message: messageText,
                related_suggestions: [],
                provider: "local",
              }
            : entry,
        ),
      );
    } finally {
      setChatLoading(false);
    }
  };

  const handleLogout = () => {
    logout();
    setAuthMode("login");
    setAuthForm({ username: "", password: "" });
    setAuthError("");
    setAuthNotice("");
    setChatHistory([]);
    resetPracticeState();
  };

  const providerOptions = [
    { value: "auto", label: "Auto" },
    { value: "openai", label: "OpenAI" },
    { value: "anthropic", label: "Anthropic" },
    { value: "gemini", label: "Gemini" },
    { value: "local", label: "Local" },
  ];

  return (
    <div className="mx-auto flex min-h-screen max-w-[1600px] flex-col gap-6 px-4 py-4 sm:px-6 lg:px-8">
      <header className="glass-panel flex flex-col gap-4 px-5 py-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="space-y-2">
          <p className="soft-label">Smart Interview Practice</p>
          <h1 className="font-display text-3xl tracking-tight text-white sm:text-4xl">Interview Prep AI Stack</h1>
          <p className="max-w-3xl text-sm text-slate-300">
            Practice interview questions, review answers, and get guided AI support in one place.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {authUser ? (
            <>
              <button className="action-btn" onClick={focusChat}>
                Open Chat
              </button>
              <button className="action-btn" onClick={handleLogout}>
                Logout
              </button>
            </>
          ) : null}
        </div>
      </header>

      {!authUser ? (
        <section className="grid gap-6 xl:grid-cols-[1.1fr,0.9fr]">
          <div className="order-2 glass-panel overflow-hidden p-8 sm:p-10 xl:order-1">
            <div className="space-y-6">
              <p className="soft-label">Guided Practice</p>
              <h2 className="max-w-2xl font-display text-4xl leading-tight text-white sm:text-5xl">
                Prepare with structured questions, feedback, and focused AI help.
              </h2>
              <p className="max-w-2xl text-base leading-7 text-slate-300">
                Work through topic-based MCQ and coding rounds, review your answers, and use chat support whenever you want a quick explanation.
              </p>
            </div>

            <div className="mt-8 grid gap-4 sm:grid-cols-3">
              <div className="rounded-[24px] border border-cyan/20 bg-cyan/10 p-5">
                <p className="soft-label text-cyan">Step 1</p>
                <p className="mt-3 text-sm font-semibold text-white">Create an account</p>
                <p className="mt-2 text-sm text-slate-300">Set up your login so your progress and chat history stay saved.</p>
              </div>
              <div className="rounded-[24px] border border-white/10 bg-white/5 p-5">
                <p className="soft-label">Step 2</p>
                <p className="mt-3 text-sm font-semibold text-white">Choose a section</p>
                <p className="mt-2 text-sm text-slate-300">Pick a topic and start with either MCQ or coding practice.</p>
              </div>
              <div className="rounded-[24px] border border-rose-300/20 bg-rose-400/10 p-5">
                <p className="soft-label text-rose-200">Step 3</p>
                <p className="mt-3 text-sm font-semibold text-white">Practice + review</p>
                <p className="mt-2 text-sm text-slate-300">Solve questions, check feedback, and use chat when you need extra clarity.</p>
              </div>
            </div>
          </div>

          <form className="order-1 glass-panel p-8 sm:p-10 xl:order-2" onSubmit={handleAuthSubmit}>
            <div className="flex rounded-full border border-white/10 bg-white/5 p-1">
              <button
                type="button"
                className={`flex-1 rounded-full px-4 py-3 text-sm font-semibold transition ${authMode === "signup" ? "bg-white text-slate-950" : "text-slate-300"}`}
                onClick={() => {
                  setAuthMode("signup");
                  setAuthError("");
                  setAuthNotice("");
                }}
              >
                Sign Up
              </button>
              <button
                type="button"
                className={`flex-1 rounded-full px-4 py-3 text-sm font-semibold transition ${authMode === "login" ? "bg-white text-slate-950" : "text-slate-300"}`}
                onClick={() => {
                  setAuthMode("login");
                  setAuthError("");
                  setAuthNotice("");
                }}
              >
                Login
              </button>
            </div>

            <div className="mt-8 space-y-3">
              <p className="soft-label">{authMode === "signup" ? "Create account" : "Welcome back"}</p>
              <h3 className="font-display text-3xl text-white">
                {authMode === "signup" ? "Create your account to begin practicing." : "Continue your interview practice."}
              </h3>
              <p className="text-sm leading-7 text-slate-300">
                {authMode === "signup"
                  ? "Choose a simple username and password, then log in to enter the dashboard."
                  : "Your practice history and chat history stay connected to the same login."}
              </p>
            </div>

            {authError ? (
              <div className="mt-6 rounded-2xl border border-rose-300/25 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">{authError}</div>
            ) : null}
            {authNotice ? (
              <div className="mt-6 rounded-2xl border border-cyan/25 bg-cyan/10 px-4 py-3 text-sm text-cyan">{authNotice}</div>
            ) : null}

            <div className="mt-6 space-y-5">
              <label className="block">
                <span className="soft-label">Username</span>
                <input
                  className="input-shell mt-2"
                  value={authForm.username}
                  onChange={(event) => setAuthForm((previous) => ({ ...previous, username: event.target.value }))}
                  placeholder="Enter username"
                  autoComplete="username"
                />
              </label>

              <label className="block">
                <span className="soft-label">Password</span>
                <input
                  className="input-shell mt-2"
                  type="password"
                  value={authForm.password}
                  onChange={(event) => setAuthForm((previous) => ({ ...previous, password: event.target.value }))}
                  placeholder="Enter password"
                  autoComplete={authMode === "signup" ? "new-password" : "current-password"}
                />
              </label>

              <button className="action-btn-primary w-full" type="submit" disabled={authLoading}>
                {authLoading ? "Please wait..." : authMode === "signup" ? "Create Account" : "Login"}
              </button>
            </div>
          </form>
        </section>
      ) : (
        <section className="grid gap-6 xl:grid-cols-[320px,minmax(0,1fr)]">
          <aside className="space-y-6">
            <div className="glass-panel p-6">
              <p className="soft-label">Signed In</p>
              <div className="mt-3 flex items-center justify-between gap-3">
                <div>
                  <p className="text-xl font-semibold text-white">{authUser.username}</p>
                  <p className="text-sm text-slate-400">Provider: {providerLabel(provider)}</p>
                </div>
                <button className="action-btn" onClick={resetPracticeState}>
                  Start Over
                </button>
              </div>
            </div>

            <div className="glass-panel p-6">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="soft-label">Topics</p>
                  <h2 className="mt-2 text-xl font-semibold text-white">Pick a section</h2>
                </div>
                <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-300">
                  {Object.keys(topics).length} topics
                </span>
              </div>

              <div className="mt-5 space-y-4">
                {Object.entries(topics).map(([slug, item]) => {
                  const selected = selectedTopic === slug;
                  return (
                    <article
                      key={slug}
                      className={`rounded-[26px] border border-white/10 bg-gradient-to-br ${accentClasses(item.accent)} p-5 ring-1 ${selected ? "border-cyan/40" : "border-white/10"}`}
                    >
                      <div className="space-y-2">
                        <div className="flex items-center justify-between gap-3">
                          <h3 className="text-lg font-semibold text-white">{item.name}</h3>
                          <span className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-[10px] uppercase tracking-[0.24em] text-slate-200">
                            {item.accent}
                          </span>
                        </div>
                        <p className="text-sm leading-6 text-slate-300">{item.description}</p>
                      </div>

                      <div className="mt-4 flex gap-3">
                        {Object.entries(modes).map(([modeKey, modeLabel]) => (
                          <button
                            key={modeKey}
                            className={`flex-1 rounded-full px-4 py-2 text-sm font-semibold transition ${
                              selected && selectedMode === modeKey
                                ? "bg-white text-slate-950"
                                : "border border-white/10 bg-white/5 text-slate-100 hover:bg-white/10"
                            }`}
                            onClick={() => handleTopicModeSelect(slug, modeKey)}
                          >
                            {modeLabel}
                          </button>
                        ))}
                      </div>
                    </article>
                  );
                })}
              </div>
            </div>
          </aside>

          <div className="grid gap-6 2xl:grid-cols-[minmax(0,1fr),390px]">
            <div className="space-y-6">
              <div className="glass-panel p-6">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <p className="soft-label">Practice Flow</p>
                    <h2 className="mt-2 text-2xl font-semibold text-white">
                      {selectedTopic && selectedMode
                        ? `${topics[selectedTopic]?.name ?? selectedTopic} · ${modes[selectedMode] ?? selectedMode}`
                        : "Choose a topic and mode to begin"}
                    </h2>
                    <p className="mt-2 text-sm text-slate-300">
                      {bankSize > 0
                        ? `You are working through ${bankSize} ordered questions.`
                        : "MCQ and coding both use their own ordered question banks."}
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center gap-3">
                    <span className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold text-slate-200">
                      {question ? `Q${question.sequence}` : "No question"}
                    </span>
                    <span className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold text-slate-200">
                      {bankSize ? `${questionPosition + 1} / ${bankSize}` : "0 / 0"}
                    </span>
                    <button className="action-btn" onClick={() => void loadQuestionAt(Math.max(questionPosition - 1, 0))} disabled={!question || questionPosition === 0}>
                      Previous
                    </button>
                    <button className="action-btn" onClick={() => void loadQuestionAt(questionPosition + 1)} disabled={!question}>
                      Next
                    </button>
                  </div>
                </div>
              </div>

              <div className="glass-panel p-6 sm:p-8">
                {!selectedTopic || !selectedMode ? (
                  <div className="rounded-[26px] border border-dashed border-white/10 bg-white/5 p-10 text-center">
                    <p className="soft-label">Ready When You Are</p>
                    <h3 className="mt-3 text-2xl font-semibold text-white">Pick a topic card on the left.</h3>
                    <p className="mx-auto mt-3 max-w-2xl text-sm leading-7 text-slate-300">
                      Start with one subject, move question by question, and use the chat panel whenever you want a quick explanation, comparison, or code walkthrough.
                    </p>
                  </div>
                ) : loadingQuestion ? (
                  <div className="rounded-[26px] border border-white/10 bg-white/5 p-10 text-center text-slate-300">Loading next question...</div>
                ) : questionError ? (
                  <div className="rounded-[26px] border border-rose-300/25 bg-rose-400/10 p-6 text-rose-100">{questionError}</div>
                ) : question ? (
                  <div className="space-y-6">
                    <div className="space-y-4">
                      <div className="flex flex-wrap items-center gap-3">
                        <span className="rounded-full bg-cyan/15 px-3 py-1 text-xs font-semibold uppercase tracking-[0.24em] text-cyan">
                          {modes[selectedMode]}
                        </span>
                        <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs uppercase tracking-[0.24em] text-slate-300">
                          {question.difficulty}
                        </span>
                      </div>
                      <h3 className="text-2xl font-semibold leading-snug text-white">{question.question}</h3>
                    </div>

                    {selectedMode === "mcq" ? (
                      <div className="grid gap-3">
                        {(question.options ?? []).map((option) => (
                          <label
                            key={option}
                            className={`flex cursor-pointer items-start gap-3 rounded-2xl border px-4 py-4 transition ${
                              answer === option
                                ? "border-cyan/60 bg-cyan/10"
                                : "border-white/10 bg-white/5 hover:border-white/20 hover:bg-white/10"
                            }`}
                          >
                            <input
                              className="mt-1"
                              type="radio"
                              name="mcq-answer"
                              checked={answer === option}
                              onChange={() => setAnswer(option)}
                            />
                            <span className="text-sm leading-7 text-slate-200">{option}</span>
                          </label>
                        ))}
                      </div>
                    ) : (
                      <div className="space-y-4">
                        <div className="grid gap-4 rounded-[24px] border border-white/10 bg-white/5 p-5 lg:grid-cols-3">
                          <div>
                            <p className="soft-label">Constraints</p>
                            <p className="mt-2 text-sm leading-7 text-slate-300">{question.constraints}</p>
                          </div>
                          <div>
                            <p className="soft-label">Sample Input</p>
                            <pre className="mt-2 whitespace-pre-wrap text-sm leading-7 text-slate-200">{question.sample_input}</pre>
                          </div>
                          <div>
                            <p className="soft-label">Sample Output</p>
                            <pre className="mt-2 whitespace-pre-wrap text-sm leading-7 text-slate-200">{question.sample_output}</pre>
                          </div>
                        </div>

                        <textarea
                          className="input-shell min-h-[240px] resize-y font-mono text-sm"
                          value={answer}
                          onChange={(event) => setAnswer(event.target.value)}
                          placeholder="Write your approach or code here..."
                        />
                      </div>
                    )}

                    <div className="flex flex-wrap gap-3">
                      <button className="action-btn-primary" onClick={handleSubmitAttempt}>
                        Submit
                      </button>
                      {result ? (
                        <button className="action-btn" onClick={() => setShowSolution((value) => !value)}>
                          {showSolution ? "Hide Solution" : "Show Solution"}
                        </button>
                      ) : null}
                    </div>

                    {result ? (
                      <div
                        className={`rounded-[24px] border p-5 ${
                          result.is_correct
                            ? "border-emerald-300/25 bg-emerald-400/10"
                            : "border-rose-300/25 bg-rose-400/10"
                        }`}
                      >
                        <p className="soft-label">{result.is_correct ? "Correct" : "Needs Work"}</p>
                        <p className="mt-3 text-sm leading-7 text-white">{result.feedback}</p>

                        {!result.is_correct && result.correct_answer ? (
                          <p className="mt-4 text-sm text-slate-200">
                            <span className="font-semibold text-white">Correct answer:</span> {result.correct_answer}
                          </p>
                        ) : null}

                        {showSolution ? (
                          <div className="mt-4 space-y-4 rounded-[22px] border border-white/10 bg-slate-950/60 p-5">
                            {result.expected_approach ? (
                              <div>
                                <p className="soft-label">Expected Approach</p>
                                <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-slate-200">{result.expected_approach}</p>
                              </div>
                            ) : null}
                            {result.solution ? (
                              <div>
                                <p className="soft-label">Reference Solution</p>
                                <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-slate-200">{result.solution}</p>
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </div>

            <section
              ref={chatPanelRef}
              className={`glass-panel p-6 ${isChatOpen ? "block" : "hidden lg:block"}`}
            >
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="soft-label">Streaming Mentor</p>
                  <h2 className="mt-2 text-xl font-semibold text-white">AI Chat</h2>
                </div>
                <div className="flex gap-2">
                  <button className="action-btn" onClick={handleClearChat}>
                    New Chat
                  </button>
                  <button className="action-btn lg:hidden" onClick={() => setChatOpen(false)}>
                    Close
                  </button>
                </div>
              </div>

              <div className="mt-5 h-[460px] space-y-4 overflow-y-auto pr-1">
                {chatHistory.length === 0 ? (
                  <div className="rounded-[24px] border border-dashed border-white/10 bg-white/5 p-6 text-sm leading-7 text-slate-300">
                    Ask for definitions, comparisons, code examples, debugging help, or interview-style explanations.
                  </div>
                ) : (
                  chatHistory.map((row) => (
                    <div key={row.id ?? row.client_id ?? row.created_at} className="space-y-3">
                      <div className="rounded-[20px] border border-cyan/20 bg-cyan/10 p-4 text-sm leading-7 text-slate-100">
                        {row.user_message}
                      </div>
                      <div className="rounded-[20px] border border-white/10 bg-white/5 p-4 text-sm leading-7 text-slate-200">
                        <pre className="whitespace-pre-wrap font-sans">{formatAssistantText(row.assistant_message)}</pre>
                        <div className="mt-3 flex flex-wrap items-center gap-2">
                          <span className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-[10px] uppercase tracking-[0.24em] text-slate-300">
                            {providerLabel(row.provider ?? "local")}
                          </span>
                        </div>
                      </div>

                      {(row.related_suggestions ?? []).length > 0 ? (
                        <div className="flex flex-wrap gap-2">
                          {row.related_suggestions.map((suggestion) => (
                            <button
                              key={`${row.created_at}-${suggestion}`}
                              className="rounded-full border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-200 transition hover:border-cyan/40 hover:bg-cyan/10"
                              onClick={() => {
                                setChatInput(suggestion);
                                focusChat();
                              }}
                            >
                              {suggestion}
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ))
                )}
              </div>

              <div className="mt-5 space-y-3">
                <textarea
                  ref={chatInputRef}
                  className="input-shell min-h-[120px] resize-y"
                  value={chatInput}
                  onChange={(event) => setChatInput(event.target.value)}
                  placeholder="Ask about pointers, OOP, SQL joins, linked lists, or any interview topic..."
                />
                <button className="action-btn-primary w-full" onClick={handleSendChat} disabled={chatLoading}>
                  {chatLoading ? "Streaming..." : "Send"}
                </button>
              </div>
            </section>
          </div>
        </section>
      )}
    </div>
  );
}
