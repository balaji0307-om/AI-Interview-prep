const { useEffect, useRef, useState } = React;
const QUESTION_BANK_TARGET = 120;

function getStoredAuthUser() {
  try {
    const raw = localStorage.getItem("auth_user");
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || !parsed.user_id || !parsed.username) return null;
    return parsed;
  } catch {
    return null;
  }
}

function persistAuthUser(user) {
  localStorage.setItem("auth_user", JSON.stringify(user));
}

function clearStoredAuthUser() {
  localStorage.removeItem("auth_user");
  localStorage.removeItem("user_id");
}

function App() {
  const [authUser, setAuthUser] = useState(() => getStoredAuthUser());
  const [authMode, setAuthMode] = useState("signup");
  const [authForm, setAuthForm] = useState({ username: "", password: "" });
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState("");
  const [authNotice, setAuthNotice] = useState("");
  const [topics, setTopics] = useState({});
  const [modes, setModes] = useState({ mcq: "MCQ", coding: "Coding" });
  const [selectedTopic, setSelectedTopic] = useState("");
  const [selectedMode, setSelectedMode] = useState("");
  const [question, setQuestion] = useState(null);
  const [questionError, setQuestionError] = useState("");
  const [answer, setAnswer] = useState("");
  const [loadingQuestion, setLoadingQuestion] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [showSolution, setShowSolution] = useState(false);
  const [bankSize, setBankSize] = useState(0);
  const [questionPosition, setQuestionPosition] = useState(0);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatHistory, setChatHistory] = useState([]);
  const [isChatOpen, setIsChatOpen] = useState(false);
  const userId = authUser?.user_id || "";
  const chatInputRef = useRef(null);
  const latestQuestionRequestRef = useRef(0);

  const formatAssistantText = (raw) => {
    let text = String(raw || "").replace(/\r\n/g, "\n").trim();
    if (!text) return "";

    if (text.startsWith("```")) {
      text = text.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/i, "").trim();
    }

    if (/^\s*\{/.test(text) && text.includes('"answer"')) {
      const match = text.match(/"answer"\s*:\s*"([\s\S]*)/);
      if (match) {
        text = match[1].split(/"\s*,\s*"related_suggestions"\s*:/)[0];
        text = text.replace(/"\s*}\s*$/, "").trim();
      }
    }

    text = text.replace(/\\n/g, "\n").replace(/\\"/g, '"').replace(/\\t/g, "    ");

    // Remove markdown bold markers.
    text = text.replace(/\*\*(.*?)\*\*/g, "$1");
    text = text.replace(/direct answer\s*:/gi, "");
    text = text.replace(/\bdirect answer\b/gi, "");

    // Ensure standard sections appear on separate lines.
    const sections = [
      "Syntax/Core Concept",
      "Example",
      "Common Mistakes",
      "When to Use",
    ];
    sections.forEach((title) => {
      const re = new RegExp(`\\s*${title}\\s*:?\\s*`, "gi");
      text = text.replace(re, `\n\n${title}:\n`);
    });

    // Cleanup repeated blank lines.
    text = text.replace(/\n{3,}/g, "\n\n").trim();
    return text;
  };

  const apiHeaders = { "Content-Type": "application/json" };

  const resetPracticeState = () => {
    setSelectedTopic("");
    setSelectedMode("");
    setQuestion(null);
    setQuestionError("");
    setAnswer("");
    setResult(null);
    setShowSolution(false);
    setBankSize(0);
    setQuestionPosition(0);
    setChatInput("");
    setChatHistory([]);
    setIsChatOpen(false);
    latestQuestionRequestRef.current += 1;
  };

  const updateAuthField = (field, value) => {
    setAuthForm((prev) => ({ ...prev, [field]: value }));
  };

  const switchAuthMode = (nextMode) => {
    setAuthMode(nextMode);
    setAuthError("");
    setAuthNotice("");
  };

  const handleAuthSubmit = async () => {
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
      const endpoint = authMode === "signup" ? "/api/auth/signup" : "/api/auth/login";
      const res = await fetch(endpoint, {
        method: "POST",
        headers: apiHeaders,
        body: JSON.stringify({ username, password }),
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || "Authentication failed.");
      }

      if (authMode === "signup") {
        setAuthNotice("Account created. Log in with the same username and password.");
        setAuthForm({ username, password: "" });
        setAuthMode("login");
        return;
      }

      persistAuthUser(data);
      localStorage.setItem("user_id", data.user_id);
      setAuthUser(data);
      setAuthForm({ username: data.username || username, password: "" });
    } catch (error) {
      setAuthError(error.message || "Authentication failed.");
    } finally {
      setAuthLoading(false);
    }
  };

  const logout = () => {
    clearStoredAuthUser();
    setAuthUser(null);
    setAuthMode("login");
    setAuthForm({ username: "", password: "" });
    setAuthError("");
    setAuthNotice("");
    resetPracticeState();
  };

  const loadMeta = async () => {
    const res = await fetch("/api/topics");
    const data = await res.json();
    setTopics(data.topics || {});
    setModes(data.modes || { mcq: "MCQ", coding: "Coding" });
  };

  const loadChatHistory = async () => {
    if (!userId) {
      setChatHistory([]);
      return;
    }
    const res = await fetch(`/api/chat/history?user_id=${encodeURIComponent(userId)}`);
    const data = await res.json();
    setChatHistory(data.history || []);
  };

  const clearChat = async () => {
    if (!userId) return;
    await fetch("/api/chat/clear", {
      method: "POST",
      headers: apiHeaders,
      body: JSON.stringify({ user_id: userId }),
    });
    setChatHistory([]);
    setChatInput("");
  };

  const focusChat = () => {
    setIsChatOpen(true);
    setTimeout(() => {
      if (chatInputRef.current) {
        chatInputRef.current.focus();
        chatInputRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }, 50);
  };

  const fetchQuestion = async (positionOverride = questionPosition) => {
    if (!authUser || !selectedTopic || !selectedMode) return;
    const requestedTopic = selectedTopic;
    const requestedMode = selectedMode;
    const requestId = latestQuestionRequestRef.current + 1;
    latestQuestionRequestRef.current = requestId;

    setLoadingQuestion(true);
    setResult(null);
    setShowSolution(false);
    setAnswer("");
    setQuestionError("");
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 8000);
      const res = await fetch(`/api/questions/random?topic=${selectedTopic}&mode=${selectedMode}&position=${positionOverride}`, {
        headers: apiHeaders,
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      if (!res.ok) {
        throw new Error("Question request failed");
      }
      const data = await res.json();

      // Ignore stale responses from a previous topic/mode switch.
      if (latestQuestionRequestRef.current !== requestId) {
        return;
      }
      if (data.topic !== requestedTopic || data.mode !== requestedMode) {
        return;
      }

      setQuestion(data);
      setBankSize(data.pool_size || 0);
      setQuestionPosition(data.position || 0);
    } catch (error) {
      if (latestQuestionRequestRef.current !== requestId) {
        return;
      }
      setQuestion(null);
      setQuestionError("Question is taking too long. Restart backend and try again.");
    } finally {
      if (latestQuestionRequestRef.current === requestId) {
        setLoadingQuestion(false);
      }
    }
  };

  const handleModeSelect = (topic, mode) => {
    setSelectedTopic(topic);
    setSelectedMode(mode);
    setQuestion(null);
    setResult(null);
    setShowSolution(false);
    setAnswer("");
    setBankSize(0);
    setQuestionPosition(0);
    latestQuestionRequestRef.current += 1;
  };

  const submitAnswer = async () => {
    if (!authUser || !question) return;
    if (!answer.trim()) return;

    setSubmitting(true);
    try {
      const res = await fetch("/api/attempts/submit", {
        method: "POST",
        headers: apiHeaders,
        body: JSON.stringify({
          user_id: userId,
          topic: selectedTopic,
          mode: selectedMode,
          question_id: question.id,
          answer,
        })
      });
      const data = await res.json();
      setResult(data);
      if (!data.is_correct) setShowSolution(false);
    } finally {
      setSubmitting(false);
    }
  };

  const sendChat = async () => {
    if (!authUser || !chatInput.trim()) return;
    setChatLoading(true);
    try {
      const message = chatInput;
      setChatInput("");
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: apiHeaders,
        body: JSON.stringify({
          user_id: userId,
          message,
          topic: selectedTopic || null,
          mode: selectedMode || null,
        })
      });
      const data = await res.json();
      setChatHistory((prev) => [...prev, {
        user_id: userId,
        user_message: message,
        assistant_message: data.answer,
        related_suggestions: data.related_suggestions || [],
        created_at: new Date().toISOString()
      }]);
    } finally {
      setChatLoading(false);
    }
  };

  useEffect(() => {
    if (!authUser) {
      setTopics({});
      setModes({ mcq: "MCQ", coding: "Coding" });
      return;
    }

    loadMeta();
    loadChatHistory();
  }, [authUser]);

  useEffect(() => {
    if (authUser && Object.keys(topics).length && selectedTopic && selectedMode) fetchQuestion();
  }, [authUser, selectedTopic, selectedMode, topics]);

  return (
    <div className="page">
      <header className="topbar">
        <div className="brand"><span>AI</span> Interview Prep</div>
        <div className="topbar-actions">
          {authUser ? (
            <>
              <div className="user-pill">{authUser.username}</div>
              <button className="top-btn chat-btn" onClick={focusChat} aria-label="Open chat">
                <span className="chat-icon" aria-hidden="true"></span>
                <span>Chat</span>
              </button>
              <button className="top-btn" onClick={logout}>Logout</button>
            </>
          ) : (
            <div className="auth-top-note">New users sign up first. Existing users can log in.</div>
          )}
        </div>
      </header>

      {!authUser ? (
        <section className="auth-stage">
          <div className="auth-copy">
            <p className="eyebrow">Welcome</p>
            <h1>Sign up first, then log in to enter your interview dashboard.</h1>
            <p>
              Create your account once and your practice history stays tied to that username.
              If you already have an account, switch to login and continue from there.
            </p>
            <div className="auth-points">
              <div className="auth-point">
                <strong>Step 1</strong>
                <span>Create a username and password with Sign up.</span>
              </div>
              <div className="auth-point">
                <strong>Step 2</strong>
                <span>Use the same details in Login.</span>
              </div>
              <div className="auth-point">
                <strong>Step 3</strong>
                <span>After login, the dashboard opens automatically.</span>
              </div>
            </div>
          </div>

          <form
            className="auth-card"
            onSubmit={(e) => {
              e.preventDefault();
              handleAuthSubmit();
            }}
          >
            <div className="auth-switch">
              <button type="button" className={authMode === "signup" ? "auth-tab active" : "auth-tab"} onClick={() => switchAuthMode("signup")}>Sign up</button>
              <button type="button" className={authMode === "login" ? "auth-tab active" : "auth-tab"} onClick={() => switchAuthMode("login")}>Login</button>
            </div>

            <h2>{authMode === "signup" ? "Create your account" : "Welcome back"}</h2>
            <p className="auth-subtext">
              {authMode === "signup"
                ? "New here? Register first. After signup, log in with the same details."
                : "Already have an account? Log in to continue to the dashboard."}
            </p>

            {authError ? <div className="auth-message error">{authError}</div> : null}
            {authNotice ? <div className="auth-message success">{authNotice}</div> : null}

            <label className="auth-label">
              Username
              <input
                className="auth-input"
                value={authForm.username}
                onChange={(e) => updateAuthField("username", e.target.value)}
                placeholder="Enter username"
                autoComplete="username"
              />
            </label>

            <label className="auth-label">
              Password
              <input
                className="auth-input"
                type="password"
                value={authForm.password}
                onChange={(e) => updateAuthField("password", e.target.value)}
                placeholder="Enter password"
                autoComplete={authMode === "signup" ? "new-password" : "current-password"}
              />
            </label>

            <button className="auth-submit" type="submit" disabled={authLoading}>
              {authLoading ? "Please wait..." : authMode === "signup" ? "Sign up" : "Login"}
            </button>
          </form>
        </section>
      ) : (
        <section className="layout">
          <div className="left-panel">
            <h1>Pick your topic and mode</h1>
            <div className="topic-grid">
              {Object.entries(topics).map(([slug, item], i) => (
                <article
                  className={`topic-card ${item.accent} ${selectedTopic === slug ? "active" : ""}`}
                  key={slug}
                  onClick={() => setSelectedTopic(slug)}
                >
                  <small>{i + 1}</small>
                  <h3>{item.name}</h3>
                  <p>{item.description}</p>
                  <div className="mode-row" onClick={(e) => e.stopPropagation()}>
                    <button className={selectedMode === "mcq" && selectedTopic === slug ? "mode active" : "mode"} onClick={() => handleModeSelect(slug, "mcq")}>MCQ</button>
                    <button className={selectedMode === "coding" && selectedTopic === slug ? "mode active" : "mode"} onClick={() => handleModeSelect(slug, "coding")}>Coding</button>
                  </div>
                </article>
              ))}
            </div>
          </div>

          <div className="right-panel">
            <div className="question-box">
              <div className="q-head">
                <div>
                  <strong>{selectedTopic && selectedMode ? `${topics[selectedTopic]?.name || "Topic"} - ${modes[selectedMode]}` : "Select topic + mode"}</strong>
                  {selectedTopic && selectedMode ? (
                    <p>
                      {bankSize ? `Question ${questionPosition + 1} of ${bankSize}` : `Preparing up to ${QUESTION_BANK_TARGET} questions for this section...`}
                    </p>
                  ) : null}
                </div>
                <button className="refresh" onClick={() => fetchQuestion(questionPosition + 1)} disabled={loadingQuestion || !selectedTopic || !selectedMode}>
                  {loadingQuestion ? "Loading..." : "Next"}
                </button>
              </div>

              {!selectedTopic || !selectedMode ? <p>Choose a topic and click MCQ or Coding to start.</p> : questionError ? <p>{questionError}</p> : !question ? <p>Loading question...</p> : (
                <>
                  <h2>{question.question}</h2>
                  {selectedMode === "mcq" ? (
                    <div className="options">
                      {(question.options || []).map((opt) => (
                        <label className="option" key={opt}>
                          <input type="radio" checked={answer === opt} onChange={() => setAnswer(opt)} />
                          <span>{opt}</span>
                        </label>
                      ))}
                    </div>
                  ) : (
                    <>
                      <div className="meta">
                        <p><b>Constraints:</b> {question.constraints}</p>
                        <p><b>Sample input:</b> {question.sample_input}</p>
                        <p><b>Sample output:</b> {question.sample_output}</p>
                      </div>
                      <textarea value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="Write your approach or code" />
                    </>
                  )}

                  <button className="submit" onClick={submitAnswer} disabled={submitting}>{submitting ? "Checking..." : "Submit"}</button>

                  {result && (
                    <div className={`result ${result.is_correct ? "good" : "bad"}`}>
                      <p><b>{result.is_correct ? "Correct" : "Wrong"}</b></p>
                      <p>{result.feedback}</p>
                      {!result.is_correct && (
                        <>
                          <button className="solution-toggle" onClick={() => setShowSolution((v) => !v)}>{showSolution ? "Hide solution" : "View solution"}</button>
                          {showSolution && (
                            <div className="solution">
                              {result.correct_answer ? <p><b>Correct answer:</b> {result.correct_answer}</p> : null}
                              {result.expected_approach ? <p><b>Expected approach:</b> {result.expected_approach}</p> : null}
                              <p><b>Solution:</b> {result.solution}</p>
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>

            {isChatOpen && <div className="chat-box">
              <div className="chat-head">
                <h3>AI Chatbot</h3>
                <div className="chat-head-actions">
                  <button className="clear-chat" onClick={clearChat}>New chat</button>
                  <button className="clear-chat" onClick={() => setIsChatOpen(false)}>Close</button>
                </div>
              </div>
              <div className="chat-log">
                {chatHistory.length === 0 ? <p className="empty">No messages yet.</p> : chatHistory.map((row, idx) => (
                  <div key={idx} className="chat-row">
                    <div className="msg user-msg">{row.user_message}</div>
                    <div className="msg ai-msg">{formatAssistantText(row.assistant_message)}</div>
                    {(row.related_suggestions || []).length > 0 && (
                      <div className="suggest-row">
                        {row.related_suggestions.map((s, i) => (
                          <button
                            key={`${idx}-${i}`}
                            className="suggest-chip"
                            onClick={() => setChatInput(s)}
                          >
                            {s}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <div className="chat-send">
                <textarea ref={chatInputRef} value={chatInput} onChange={(e) => setChatInput(e.target.value)} placeholder="Ask anything about interview prep" />
                <button onClick={sendChat} disabled={chatLoading}>{chatLoading ? "Sending..." : "Send"}</button>
              </div>
            </div>}
          </div>
        </section>
      )}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
