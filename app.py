from functools import wraps
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import re
import sqlite3

from flask import Flask, flash, render_template, request, redirect, session, url_for
from question_bank import QUESTION_BANK_SIZE, build_coding_questions, build_mcq_questions, extract_question_sequence

try:
    from pymongo import MongoClient
except ModuleNotFoundError:
    MongoClient = None

try:
    from bson import ObjectId
except ModuleNotFoundError:
    ObjectId = None

try:
    import google.generativeai as genai
except ModuleNotFoundError:
    genai = None

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "secret123")

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "users.db"

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "interview_prep")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
QUESTION_TARGET_PER_SECTION = QUESTION_BANK_SIZE
QUESTION_BATCH_SIZE = 10
QUESTION_BANK_SOURCE = "question-bank-v2"
LOCAL_QUESTION_STORE = {}

TOPICS = {
    "python": {
        "name": "Python",
        "description": "Syntax, data structures, decorators, OOP, and tricky runtime behavior.",
        "accent": "blue",
    },
    "java": {
        "name": "Java",
        "description": "Collections, JVM basics, OOP, threading, and core interview traps.",
        "accent": "red",
    },
    "cpp": {
        "name": "C++",
        "description": "STL, pointers, memory, classes, complexity, and performance instincts.",
        "accent": "green",
    },
    "dsa": {
        "name": "DSA",
        "description": "Arrays, graphs, dynamic programming, trees, sorting, and greedy thinking.",
        "accent": "gold",
    },
}

MODES = {
    "mcq": "MCQ",
    "coding": "Coding",
}


def get_db():
    return sqlite3.connect(DB_PATH)


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("user"):
            flash("Log in first. The arena is waiting.")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def utc_now():
    return datetime.now(timezone.utc)


def setup_sqlite():
    conn = get_db()
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users (username TEXT UNIQUE, password TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS scores (username TEXT, score INTEGER)")
    conn.commit()
    conn.close()


def init_mongo():
    if MongoClient is None:
        return None
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
        client.admin.command("ping")
        db = client[MONGO_DB_NAME]
        db["ai_questions"].create_index(
            [("topic", 1), ("mode", 1), ("question", 1)],
            unique=True,
            name="topic_mode_question_unique",
        )
        db["attempts"].create_index([("username", 1), ("created_at", -1)], name="attempt_user_time")
        db["chat_logs"].create_index([("username", 1), ("created_at", -1)], name="chat_user_time")
        return db
    except Exception:
        return None


MONGO_DB = init_mongo()

if genai and GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception:
        pass


def parse_json_from_text(text):
    if not text:
        raise ValueError("Empty model response")

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match_array = re.search(r"\[[\s\S]*\]", cleaned)
    if match_array:
        return json.loads(match_array.group(0))

    match_obj = re.search(r"\{[\s\S]*\}", cleaned)
    if match_obj:
        return json.loads(match_obj.group(0))

    raise ValueError("No valid JSON found")


def call_gemini_json(prompt, fallback):
    if not (genai and GEMINI_API_KEY):
        return fallback

    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(prompt)
        text = getattr(response, "text", "")
        return parse_json_from_text(text)
    except Exception:
        return fallback


def get_local_question_pool(topic, mode):
    key = f"{topic}:{mode}"
    return LOCAL_QUESTION_STORE.setdefault(key, [])


def fallback_mcq_questions(topic, count, start_index=0):
    return build_mcq_questions(topic, count, start_index=start_index)


def fallback_coding_questions(topic, count, start_index=0):
    return build_coding_questions(topic, count, start_index=start_index)


def normalize_mcq_question(item):
    if not isinstance(item, dict):
        return None

    question = str(item.get("question", "")).strip()
    options = item.get("options") or []
    if not isinstance(options, list):
        options = []
    options = [str(opt).strip() for opt in options if str(opt).strip()][:4]

    answer = str(item.get("answer", "")).strip()
    solution = str(item.get("solution", "")).strip()
    difficulty = str(item.get("difficulty", "intermediate")).strip().lower()

    if len(options) < 4:
        return None

    if answer not in options:
        answer = options[0]

    if not question:
        return None

    if not solution:
        solution = f"Correct option is '{answer}' because it best matches interview expectations for this concept."

    if difficulty not in {"basic", "intermediate", "advanced"}:
        difficulty = "intermediate"

    return {
        "question": question,
        "options": options,
        "answer": answer,
        "solution": solution,
        "difficulty": difficulty,
    }


def normalize_coding_question(item):
    if not isinstance(item, dict):
        return None

    question = str(item.get("question", "")).strip()
    constraints = str(item.get("constraints", "")).strip() or "Discuss edge cases and complexity."
    sample_input = str(item.get("sample_input", "N/A")).strip() or "N/A"
    sample_output = str(item.get("sample_output", "N/A")).strip() or "N/A"
    expected_approach = str(item.get("expected_approach", "")).strip()
    solution = str(item.get("solution", "")).strip() or expected_approach
    difficulty = str(item.get("difficulty", "intermediate")).strip().lower()

    if not question:
        return None

    if not expected_approach:
        expected_approach = "Provide a clear, correct algorithm and mention complexity."

    if not solution:
        solution = "Write a correct algorithm, handle edge cases, and explain complexity."

    if difficulty not in {"basic", "intermediate", "advanced"}:
        difficulty = "intermediate"

    return {
        "question": question,
        "constraints": constraints,
        "sample_input": sample_input,
        "sample_output": sample_output,
        "expected_approach": expected_approach,
        "solution": solution,
        "difficulty": difficulty,
    }


def generate_mcq_questions(topic, count, start_index=0):
    return fallback_mcq_questions(topic, count, start_index=start_index)


def generate_coding_questions(topic, count, start_index=0):
    return fallback_coding_questions(topic, count, start_index=start_index)


def build_bank_rows(topic, mode, count, start_index=0):
    if mode == "mcq":
        return build_mcq_questions(topic, count, start_index=start_index)
    return build_coding_questions(topic, count, start_index=start_index)


def pool_needs_rebuild(topic, mode, collection):
    docs = list(collection.find({"topic": topic, "mode": mode}).limit(5))
    if not docs:
        return False

    for doc in docs:
        if doc.get("source") != QUESTION_BANK_SOURCE:
            return True
        if not isinstance(doc.get("sequence"), int):
            return True
        if mode == "mcq":
            if not isinstance(doc.get("options"), list) or len(doc.get("options", [])) < 4 or not doc.get("answer"):
                return True
        else:
            if not doc.get("expected_approach"):
                return True

    return False


def get_questions_collection():
    if MONGO_DB is None:
        return None
    return MONGO_DB["ai_questions"]


def get_attempts_collection():
    if MONGO_DB is None:
        return None
    return MONGO_DB["attempts"]


def get_chat_collection():
    if MONGO_DB is None:
        return None
    return MONGO_DB["chat_logs"]


def store_questions(topic, mode, questions, source=QUESTION_BANK_SOURCE):
    collection = get_questions_collection()
    if collection is None:
        pool = get_local_question_pool(topic, mode)
        known = {item["question"] for item in pool}
        inserted = 0

        for question in questions:
            if question["question"] in known:
                continue

            doc = dict(question)
            doc["id"] = f"local-{topic}-{mode}-{len(pool) + 1}"
            doc["source"] = source
            pool.append(doc)
            known.add(doc["question"])
            inserted += 1

        return inserted

    inserted = 0
    for q in questions:
        doc = {
            "topic": topic,
            "mode": mode,
            "question": q["question"],
            "sequence": q.get("sequence") or extract_question_sequence(q["question"]),
            "difficulty": q.get("difficulty", "intermediate"),
            "solution": q.get("solution", ""),
            "source": source,
            "created_at": utc_now(),
        }

        if mode == "mcq":
            doc["options"] = q.get("options", [])
            doc["answer"] = q.get("answer", "")
        else:
            doc["constraints"] = q.get("constraints", "")
            doc["sample_input"] = q.get("sample_input", "N/A")
            doc["sample_output"] = q.get("sample_output", "N/A")
            doc["expected_approach"] = q.get("expected_approach", "")

        result = collection.update_one(
            {
                "topic": topic,
                "mode": mode,
                "question": q["question"],
            },
            {"$setOnInsert": doc},
            upsert=True,
        )
        if result.upserted_id:
            inserted += 1

    return inserted


def ensure_question_pool(topic, mode, target=QUESTION_TARGET_PER_SECTION):
    collection = get_questions_collection()
    if collection is None:
        current = len(get_local_question_pool(topic, mode))
    else:
        if pool_needs_rebuild(topic, mode, collection):
            collection.delete_many({"topic": topic, "mode": mode})
        current = collection.count_documents({"topic": topic, "mode": mode})

    remaining = max(0, target - current)
    if remaining <= 0:
        return current

    batch = build_bank_rows(topic, mode, remaining, start_index=current)

    inserted = store_questions(topic, mode, batch, source=QUESTION_BANK_SOURCE)
    current += inserted

    return current


def get_ordered_questions(topic, mode):
    collection = get_questions_collection()
    if collection is None:
        pool = [dict(item) for item in get_local_question_pool(topic, mode)]
        pool.sort(key=lambda item: (item.get("sequence") or extract_question_sequence(item.get("question", "")), item.get("question", "")))
        return pool

    docs = list(collection.find({"topic": topic, "mode": mode}))
    docs.sort(key=lambda item: (item.get("sequence") or extract_question_sequence(item.get("question", "")), str(item.get("_id", ""))))
    ordered = []
    for item in docs:
        doc = dict(item)
        if "_id" in doc:
            doc["id"] = str(doc["_id"])
            doc.pop("_id", None)
        ordered.append(doc)
    return ordered


def get_next_question(topic, mode):
    ordered_questions = get_ordered_questions(topic, mode)
    if not ordered_questions:
        if mode == "mcq":
            fallback = fallback_mcq_questions(topic, 1)[0]
        else:
            fallback = fallback_coding_questions(topic, 1)[0]
        fallback["position"] = 0
        fallback["pool_size"] = 1
        return fallback

    progress = session.get("question_progress", {})
    key = f"{topic}:{mode}"
    next_position = int(progress.get(key, 0))

    if next_position < 0 or next_position >= len(ordered_questions):
        next_position = 0

    progress[key] = (next_position + 1) % len(ordered_questions)
    session["question_progress"] = progress

    question = dict(ordered_questions[next_position])
    question["position"] = next_position
    question["pool_size"] = len(ordered_questions)
    return question


def fetch_question_by_id(question_id):
    collection = get_questions_collection()
    if not question_id:
        return None

    if collection is None:
        for pool in LOCAL_QUESTION_STORE.values():
            for question in pool:
                if question.get("id") == question_id:
                    return question
        return None

    try:
        if ObjectId is None:
            return None
        doc = collection.find_one({"_id": ObjectId(question_id)})
    except Exception:
        return None

    if doc and "_id" in doc:
        doc["id"] = str(doc["_id"])
        doc.pop("_id", None)
    return doc


def evaluate_coding_answer(question, user_answer):
    expected_approach = question.get("expected_approach", "")
    reference_solution = question.get("solution", "")

    fallback_feedback = {
        "is_correct": len(user_answer.strip()) > 20,
        "feedback": "Answer length is too short. Explain algorithm, edge cases, and complexity." if len(user_answer.strip()) <= 20 else "Good attempt. Compare your logic with the model solution to refine edge-case handling.",
    }

    prompt = f"""
You are evaluating a coding interview answer.
Return strict JSON only:
{{
  "is_correct": true or false,
  "feedback": "2-4 line practical feedback"
}}

Question: {question.get('question', '')}
Expected approach: {expected_approach}
Reference solution: {reference_solution}
Candidate answer: {user_answer}

Mark correct only if approach is logically sound for interview standards.
"""

    result = call_gemini_json(prompt, fallback_feedback)
    if not isinstance(result, dict):
        return fallback_feedback

    return {
        "is_correct": bool(result.get("is_correct", False)),
        "feedback": str(result.get("feedback", fallback_feedback["feedback"])).strip(),
    }


def store_attempt(username, topic, mode, question, submitted_answer, is_correct, feedback):
    collection = get_attempts_collection()
    if collection is None:
        return

    doc = {
        "username": username,
        "topic": topic,
        "mode": mode,
        "question": question.get("question", ""),
        "question_id": question.get("id"),
        "submitted_answer": submitted_answer,
        "is_correct": is_correct,
        "feedback": feedback,
        "solution": question.get("solution", ""),
        "created_at": utc_now(),
    }

    if mode == "mcq":
        doc["correct_answer"] = question.get("answer", "")
        doc["options"] = question.get("options", [])
    else:
        doc["expected_approach"] = question.get("expected_approach", "")

    collection.insert_one(doc)


def get_chat_context(username, limit=8):
    collection = get_attempts_collection()
    if collection is None:
        return ""

    attempts = list(
        collection.find({"username": username})
        .sort("created_at", -1)
        .limit(limit)
    )

    lines = []
    for at in attempts:
        status = "correct" if at.get("is_correct") else "wrong"
        lines.append(f"- {at.get('topic', '').upper()} {at.get('mode', '').upper()}: {at.get('question', '')} => {status}")
    return "\n".join(lines)


def ask_gemini_chat(username, message):
    fallback = {
        "answer": "Gemini is not configured yet. Add GEMINI_API_KEY and try again."
    }

    context = get_chat_context(username)
    prompt = f"""
You are an interview preparation assistant.
Answer clearly and help the student improve.

Recent attempt context:
{context if context else 'No recent attempts yet.'}

User question:
{message}

Return strict JSON only:
{{
  "answer": "helpful explanation"
}}
"""

    result = call_gemini_json(prompt, fallback)
    if isinstance(result, dict) and str(result.get("answer", "")).strip():
        return str(result["answer"]).strip()
    return fallback["answer"]


def get_recent_chat_logs(username, limit=20):
    collection = get_chat_collection()
    if collection is None:
        return []

    logs = list(
        collection.find({"username": username})
        .sort("created_at", -1)
        .limit(limit)
    )
    logs.reverse()
    return logs


def store_chat_log(username, user_message, assistant_message):
    collection = get_chat_collection()
    if collection is None:
        return

    collection.insert_one(
        {
            "username": username,
            "user_message": user_message,
            "assistant_message": assistant_message,
            "created_at": utc_now(),
        }
    )


setup_sqlite()


# ---------- ROUTES ----------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        conn = get_db()
        c = conn.cursor()
        try:
            c.execute("SELECT 1 FROM users WHERE username=?", (username,))
            if c.fetchone():
                flash("That username is already taken.")
                return redirect(url_for("signup"))

            c.execute(
                "INSERT INTO users (username, password) VALUES (?,?)",
                (username, password),
            )
            conn.commit()
            flash("Account created. Time to warm up.")
        except sqlite3.IntegrityError:
            flash("That username is already taken.")
            return redirect(url_for("signup"))
        finally:
            conn.close()

        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password))
        user = c.fetchone()
        conn.close()

        if user:
            session["user"] = username
            session["score"] = 0
            flash(f"Welcome back, {username}.")
            return redirect(url_for("dashboard"))

        flash("Username or password did not match.")

    return render_template("login.html")


@app.route("/dashboard")
@login_required
def dashboard():
    user = session.get("user")
    score = session.get("score", 0)

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COALESCE(MAX(score), 0) FROM scores WHERE username=?", (user,))
    best_score = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM scores WHERE username=?", (user,))
    sessions_played = c.fetchone()[0]
    conn.close()

    mongo_status = "connected" if MONGO_DB is not None else "not_connected"
    gemini_status = "connected" if (genai and GEMINI_API_KEY) else "not_connected"

    return render_template(
        "dashboard.html",
        user=user,
        score=score,
        best_score=best_score,
        sessions_played=sessions_played,
        topics=TOPICS,
        modes=MODES,
        mongo_status=mongo_status,
        gemini_status=gemini_status,
    )


@app.route("/questions/<topic>")
@login_required
def legacy_questions(topic):
    # Backward-compatible route: defaults to MCQ.
    return redirect(url_for("practice", topic=topic, mode="mcq"))


@app.route("/practice/<topic>/<mode>", methods=["GET", "POST"])
@login_required
def practice(topic, mode):
    if topic not in TOPICS:
        flash("Pick a battle zone from the dashboard.")
        return redirect(url_for("dashboard"))

    if mode not in MODES:
        flash("Pick a valid practice mode.")
        return redirect(url_for("dashboard"))

    user = session.get("user")

    if request.method == "GET":
        ensure_question_pool(topic, mode, target=QUESTION_TARGET_PER_SECTION)
        question = get_next_question(topic, mode)

        session["current_question"] = {
            "id": question.get("id"),
            "topic": topic,
            "mode": mode,
            "question": question,
        }

        return render_template(
            "questions.html",
            q=question,
            topic=topic,
            topic_meta=TOPICS[topic],
            mode=mode,
            mode_label=MODES[mode],
            modes=MODES,
        )

    current_question = session.get("current_question", {})
    question = None

    if (
        current_question
        and current_question.get("topic") == topic
        and current_question.get("mode") == mode
    ):
        question = current_question.get("question")

    question_id = request.form.get("question_id", "")
    db_question = fetch_question_by_id(question_id)
    if db_question:
        question = db_question

    if not question:
        flash("Session question not found. Loaded a fresh one.")
        return redirect(url_for("practice", topic=topic, mode=mode))

    selected_answer = ""
    feedback = ""

    if mode == "mcq":
        selected_answer = request.form.get("answer", "")
        correct_answer = question.get("answer", "")
        is_correct = selected_answer == correct_answer
        feedback = "Correct answer. Strong call." if is_correct else "That one missed. Review the solution and retry."
    else:
        selected_answer = request.form.get("coding_answer", "")
        eval_result = evaluate_coding_answer(question, selected_answer)
        is_correct = eval_result["is_correct"]
        feedback = eval_result["feedback"]

    if is_correct:
        session["score"] = session.get("score", 0) + 1

    store_attempt(user, topic, mode, question, selected_answer, is_correct, feedback)

    return render_template(
        "result.html",
        topic=topic,
        topic_name=TOPICS[topic]["name"],
        mode=mode,
        mode_label=MODES[mode],
        score=session.get("score", 0),
        selected=selected_answer,
        correct=question.get("answer", ""),
        is_correct=is_correct,
        feedback=feedback,
        solution=question.get("solution", "No solution available."),
        expected_approach=question.get("expected_approach", ""),
    )


@app.route("/ai-chat", methods=["GET", "POST"])
@login_required
def ai_chat():
    user = session.get("user")

    if request.method == "POST":
        message = request.form.get("message", "").strip()
        if not message:
            flash("Type your question before sending.")
            return redirect(url_for("ai_chat"))

        answer = ask_gemini_chat(user, message)
        store_chat_log(user, message, answer)
        return redirect(url_for("ai_chat"))

    chat_history = get_recent_chat_logs(user)
    return render_template("ai_chat.html", chat_history=chat_history)


@app.route("/leaderboard")
@login_required
def leaderboard():
    conn = get_db()
    c = conn.cursor()

    c.execute(
        """
        SELECT username, MAX(score) AS best_score
        FROM scores
        GROUP BY username
        ORDER BY best_score DESC, username ASC
        LIMIT 10
        """
    )
    data = c.fetchall()

    conn.close()

    return render_template("leaderboard.html", data=data)


@app.route("/save_score")
@login_required
def save_score():
    user = session.get("user")
    score = session.get("score", 0)

    conn = get_db()
    c = conn.cursor()

    c.execute("INSERT INTO scores VALUES (?,?)", (user, score))
    conn.commit()
    conn.close()
    flash("Score saved to the board.")

    return redirect(url_for("leaderboard"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out. Come back sharp.")
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(debug=True)
