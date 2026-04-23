from __future__ import annotations

import json
import os
import re
import hashlib
import secrets
import sqlite3
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
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

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"
DB_PATH = BASE_DIR / "users.db"

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "interview_prep")
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
QUESTION_TARGET = QUESTION_BANK_SIZE
QUESTION_READY_MINIMUM = 10
QUESTION_BANK_SOURCE = "question-bank-v2"
FALLBACK_GEMINI_MODELS = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-1.5-flash"]
CHAT_MAX_OUTPUT_TOKENS = 900

TOPICS = {
    "python": {
        "name": "Python",
        "description": "Syntax, data structures, decorators, OOP, and runtime behavior.",
        "accent": "blue",
    },
    "java": {
        "name": "Java",
        "description": "Collections, JVM basics, OOP, threading, and pitfalls.",
        "accent": "red",
    },
    "cpp": {
        "name": "C++",
        "description": "STL, memory, pointers, classes, and optimization.",
        "accent": "green",
    },
    "dsa": {
        "name": "DSA",
        "description": "Arrays, graphs, trees, DP, sorting, and greedy.",
        "accent": "gold",
    },
}

MODES = {"mcq": "MCQ", "coding": "Coding"}

MEMORY_STORE: dict[str, Any] = {
    "questions": {},
    "attempts": [],
    "chat_logs": [],
}

app = FastAPI(title="Interview Prep FastAPI")
app.state.last_gemini_error = ""
app.state.discovered_models = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateQuestionsRequest(BaseModel):
    topic: str
    mode: str
    count: int = Field(default=QUESTION_TARGET, ge=1, le=150)


class AuthRequest(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=4, max_length=128)


class SubmitAttemptRequest(BaseModel):
    user_id: str = "local-user"
    topic: str
    mode: str
    question_id: str
    answer: str


class ChatRequest(BaseModel):
    user_id: str = "local-user"
    message: str
    topic: str | None = None
    mode: str | None = None


class ClearChatRequest(BaseModel):
    user_id: str = "local-user"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def setup_auth_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT UNIQUE,
                password TEXT,
                created_at TEXT,
                last_login_at TEXT
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "created_at" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN created_at TEXT")
        if "last_login_at" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN last_login_at TEXT")


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, stored_password: str) -> bool:
    stored_password = stored_password or ""
    if stored_password.startswith("pbkdf2_sha256$"):
        try:
            _, salt, expected = stored_password.split("$", 2)
        except ValueError:
            return False
        candidate = hash_password(password, salt).split("$", 2)[2]
        return secrets.compare_digest(candidate, expected)

    # Backward compatibility with old local demo accounts stored as plain text.
    return secrets.compare_digest(password, stored_password)


def normalize_username(username: str) -> str:
    return re.sub(r"\s+", "", username.strip().lower())


def auth_response(username: str) -> dict[str, str]:
    return {"user_id": username, "username": username}


setup_auth_db()


def fetch_user(username: str) -> tuple[str, str] | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT username, password FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if not row:
        return None
    return row[0], row[1]


def create_user(username: str, password: str) -> dict[str, str]:
    normalized = normalize_username(username)
    if not re.fullmatch(r"[a-z0-9_]{3,40}", normalized):
        raise HTTPException(
            status_code=400,
            detail="Username must be 3-40 characters using letters, numbers, or underscore.",
        )

    if len(password.strip()) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters.")

    timestamp = utc_now().isoformat()
    hashed_password = hash_password(password)

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO users (username, password, created_at, last_login_at) VALUES (?, ?, ?, ?)",
                (normalized, hashed_password, timestamp, None),
            )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Account already exists. Use login instead.")

    return auth_response(normalized)


def login_user(username: str, password: str) -> dict[str, str]:
    normalized = normalize_username(username)
    user_row = fetch_user(normalized)
    if not user_row:
        raise HTTPException(status_code=404, detail="Account not found. Sign up first.")

    stored_username, stored_password = user_row
    if not verify_password(password, stored_password):
        raise HTTPException(status_code=401, detail="Incorrect password.")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE users SET last_login_at = ? WHERE username = ?",
            (utc_now().isoformat(), stored_username),
        )

    return auth_response(stored_username)


def parse_json_from_text(text: str) -> Any:
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("Empty response")

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    for pattern in (r"\[[\s\S]*\]", r"\{[\s\S]*\}"):
        m = re.search(pattern, cleaned)
        if m:
            return json.loads(m.group(0))

    raise ValueError("No valid JSON in model response")


def normalize_chat_answer(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    # Handle fenced output like ```json ... ```
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()

    # Remove rigid section labels for cleaner conversational rendering.
    text = re.sub(r"(?i)\bDirect Answer\s*:\s*", "", text)

    # If response is a JSON object string, extract `answer`.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "answer" in parsed:
            return str(parsed.get("answer", "")).strip()
        if isinstance(parsed, dict) and any(k in parsed for k in ["direct_answer", "core_concept", "example", "common_mistakes", "when_to_use"]):
            return compose_structured_answer(parsed)
    except Exception:
        pass

    # Recover when Gemini returns an incomplete JSON envelope like:
    # {"answer":"...","related_suggestions":[...]
    if re.match(r"^\s*\{", text) and '"answer"' in text:
        m = re.search(r'"answer"\s*:\s*"([\s\S]*)', text)
        if m:
            answer_text = m.group(1)
            answer_text = re.split(r'"\s*,\s*"related_suggestions"\s*:', answer_text, maxsplit=1)[0]
            answer_text = re.sub(r'"\s*}\s*$', "", answer_text).strip()
            answer_text = answer_text.replace("\\n", "\n").replace('\\"', '"').replace("\\t", "    ")
            if answer_text:
                return normalize_chat_answer(answer_text)

    # Recover structured fields even if JSON is partially malformed/truncated.
    recovered = {}
    for key in ["direct_answer", "core_concept", "example", "common_mistakes", "when_to_use", "answer"]:
        pattern = rf'"{key}"\s*:\s*"([\s\S]*?)"(?=,\s*"[a-z_]+"|\s*}}|$)'
        m = re.search(pattern, text)
        if m:
            recovered[key] = m.group(1).replace('\\"', '"').strip()
    if recovered:
        if "answer" in recovered:
            return recovered["answer"]
        return compose_structured_answer(recovered)

    return text


def build_related_suggestions(question: str, answer: str = "") -> list[str]:
    source = f"{question} {answer}".lower()
    rules = [
        (["array", "list"], ["Show array implementation in C++.", "Compare array vs linked list.", "Give an array interview problem."]),
        (["pointer", "reference", "memory"], ["Show pointer example in C++.", "Explain pointer vs reference.", "Explain dangling and null pointers."]),
        (["linked list", "node"], ["Show linked list code.", "Compare linked list vs array.", "Explain linked list time complexity."]),
        (["stack"], ["Show stack implementation.", "Explain stack applications.", "Give a stack interview problem."]),
        (["queue"], ["Show queue implementation.", "Explain queue vs stack.", "Give a queue interview problem."]),
        (["tree", "bst", "binary"], ["Explain tree traversal.", "Show binary tree code.", "Give a tree interview problem."]),
        (["graph"], ["Explain BFS and DFS.", "Show graph representation.", "Give a graph interview problem."]),
        (["dp", "dynamic programming"], ["Explain DP with an example.", "Show memoization vs tabulation.", "Give a beginner DP problem."]),
        (["python"], ["Show Python code example.", "Explain Python-specific mistakes.", "Give Python interview questions."]),
        (["java"], ["Show Java code example.", "Explain Java memory basics.", "Give Java interview questions."]),
        (["c++", "cpp"], ["Show C++ code example.", "Explain C++ memory handling.", "Give C++ interview questions."]),
    ]
    for keywords, suggestions in rules:
        if any(keyword in source for keyword in keywords):
            return suggestions
    return [
        "Show a simple code example.",
        "Explain with a dry run.",
        "Give an interview question on this.",
    ]


def use_local_suggestions(suggestions: list[str]) -> bool:
    if len(suggestions) < 2:
        return True
    joined = " ".join(suggestions).lower()
    generic_markers = [
        "show a code example for this",
        "explain time and space complexity",
        "ask again",
    ]
    return any(marker in joined for marker in generic_markers)


def configure_genai(api_key: str) -> bool:
    if not (genai and api_key):
        return False
    try:
        genai.configure(api_key=api_key)
        return True
    except Exception:
        return False


def resolve_gemini_key(header_key: str | None) -> str:
    if header_key and header_key.strip():
        return header_key.strip()
    return os.getenv("GEMINI_API_KEY", "").strip()


def unique_keep_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        val = (item or "").strip()
        if not val or val in seen:
            continue
        seen.add(val)
        out.append(val)
    return out


def discover_generate_models() -> list[str]:
    names = []
    try:
        for model in genai.list_models():
            supported = getattr(model, "supported_generation_methods", []) or []
            if "generateContent" not in supported:
                continue
            name = getattr(model, "name", "")
            if not name:
                continue
            if name.startswith("models/"):
                name = name.split("/", 1)[1]
            names.append(name)
    except Exception:
        return []
    return names


def compose_structured_answer(payload: dict[str, Any]) -> str:
    section_map = [
        ("direct_answer", "Direct Answer"),
        ("core_concept", "Syntax/Core Concept"),
        ("example", "Example"),
        ("common_mistakes", "Common Mistakes"),
        ("when_to_use", "When to Use"),
    ]
    lines = []
    for key, title in section_map:
        value = str(payload.get(key, "")).strip()
        if not value:
            continue
        lines.append(f"**{title}**")
        lines.append(value)
    return "\n\n".join(lines).strip()


def build_local_structured_answer(question: str) -> str:
    q = (question or "").strip()
    lower = q.lower()

    if "linked list" in lower:
        payload = {
            "direct_answer": "A linked list is a linear data structure where each node stores data and a reference to the next node instead of using contiguous memory like an array.",
            "core_concept": "Main types: singly linked list (next pointer only), doubly linked list (prev and next), circular singly linked list (last node points to first), and circular doubly linked list (both directions plus circular links). Insertion or deletion at a known node is O(1), but searching is O(n).",
            "example": "Example: 10 -> 20 -> 30 -> null is a singly linked list. If you insert 15 after 10, it becomes 10 -> 15 -> 20 -> 30 by changing pointers instead of shifting all elements.",
            "common_mistakes": "Forgetting to update links in the correct order, losing the head pointer, not handling empty or single-node lists, and assuming linked lists support O(1) random access like arrays.",
            "when_to_use": "Use a linked list when you need frequent insertions or deletions in the middle or front and do not need fast index-based access.",
        }
        return compose_structured_answer(payload)

    if "stack" in lower:
        payload = {
            "direct_answer": "A stack is a linear data structure that follows LIFO: Last In, First Out.",
            "core_concept": "Main operations are push, pop, peek/top, and isEmpty. Push and pop are usually O(1). Common implementations use arrays/lists or linked lists.",
            "example": "If you push 10, 20, 30, the top is 30. One pop removes 30 first, then 20 becomes the new top.",
            "common_mistakes": "Popping from an empty stack, confusing stack order with queue order, and forgetting that recursion also uses an implicit call stack.",
            "when_to_use": "Use a stack for expression evaluation, undo operations, backtracking, DFS, balanced parentheses, and function-call style behavior.",
        }
        return compose_structured_answer(payload)

    if "queue" in lower:
        payload = {
            "direct_answer": "A queue is a linear data structure that follows FIFO: First In, First Out.",
            "core_concept": "Main operations are enqueue, dequeue, front/peek, and isEmpty. Enqueue and dequeue are usually O(1) in a proper implementation.",
            "example": "If you enqueue 10, 20, 30, the first dequeue removes 10, then 20 becomes the front.",
            "common_mistakes": "Confusing queue behavior with stack behavior, using a slow array implementation that shifts elements, and not handling empty queue cases.",
            "when_to_use": "Use a queue in BFS traversal, scheduling, buffering, producer-consumer systems, and any problem where arrival order matters.",
        }
        return compose_structured_answer(payload)

    if "tree" in lower and "binary indexed tree" not in lower:
        payload = {
            "direct_answer": "A tree is a hierarchical data structure made of nodes connected by edges, with one root node and parent-child relationships.",
            "core_concept": "Common types include binary tree, binary search tree, AVL tree, heap, and trie. Important terms are root, parent, child, leaf, height, and subtree.",
            "example": "In a binary tree, node 10 can have left child 5 and right child 15. Traversals include preorder, inorder, postorder, and level order.",
            "common_mistakes": "Confusing BST rules with general binary trees, missing null/base cases in recursion, and mixing up traversal orders.",
            "when_to_use": "Use trees for hierarchical data, searching with ordering, expression parsing, file systems, priority handling, and prefix lookup.",
        }
        return compose_structured_answer(payload)

    if "graph" in lower:
        payload = {
            "direct_answer": "A graph is a set of vertices (nodes) and edges that connect pairs of vertices.",
            "core_concept": "Graphs can be directed or undirected, weighted or unweighted, cyclic or acyclic. Common representations are adjacency list and adjacency matrix.",
            "example": "If A is connected to B and C, the adjacency list is A:[B,C]. Traversals are BFS and DFS, and shortest-path algorithms include Dijkstra for weighted graphs.",
            "common_mistakes": "Choosing the wrong representation, not tracking visited nodes, and confusing tree properties with general graph behavior.",
            "when_to_use": "Use graphs for networks, routes, dependencies, social connections, prerequisites, and state transitions.",
        }
        return compose_structured_answer(payload)

    if "array" in lower:
        payload = {
            "direct_answer": "An array is a linear data structure that stores same-type elements in contiguous memory locations.",
            "core_concept": "Access is index-based (usually starting at 0), so reading/writing an element by index is O(1). Common types: 1D array and 2D array (matrix).",
            "example": "Example (Python): arr = [10, 20, 30]. arr[1] gives 20. Example (2D): mat = [[1,2],[3,4]], mat[1][0] gives 3.",
            "common_mistakes": "Index out of bounds, confusion between 0-based index and position, and assuming fixed-size arrays can grow automatically in all languages.",
            "when_to_use": "Use arrays when you need fast index access, predictable memory layout, and ordered elements.",
        }
        return compose_structured_answer(payload)

    if "pointer" in lower:
        payload = {
            "direct_answer": "A pointer stores the memory address of another variable (common in C/C++).",
            "core_concept": "Use '&' to get address and '*' to dereference. Example: int x=10; int* p=&x; *p reads/writes x.",
            "example": "C++: int x=5; int* p=&x; *p=9; // now x becomes 9",
            "common_mistakes": "Dereferencing null/uninitialized pointers, forgetting memory ownership, and using dangling pointers after free/delete.",
            "when_to_use": "Use pointers for dynamic memory, linked data structures, pass-by-reference style behavior, and low-level optimization.",
        }
        return compose_structured_answer(payload)

    payload = {
        "direct_answer": f"Here is a concise technical explanation for: {q}",
        "core_concept": "Break the problem into definition, key operations, complexity, and edge cases.",
        "example": "Give one small input/output or code snippet and explain why it works.",
        "common_mistakes": "Typical issues are edge-case misses, wrong complexity assumptions, and off-by-one errors.",
        "when_to_use": "Choose the concept/approach when it gives correct logic with acceptable time and space complexity.",
    }
    return compose_structured_answer(payload)


def call_gemini_json(prompt: str, fallback: Any, api_key: str) -> Any:
    if not configure_genai(api_key):
        app.state.last_gemini_error = "Gemini is not configured with an API key."
        return fallback

    model_candidates = unique_keep_order([DEFAULT_GEMINI_MODEL] + FALLBACK_GEMINI_MODELS)
    last_error = ""
    should_try_discovery = False

    for model_name in model_candidates:
        try:
            def _run_request():
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(
                    prompt,
                    generation_config={
                        "temperature": 0.2,
                        "max_output_tokens": CHAT_MAX_OUTPUT_TOKENS,
                    },
                )
                text = getattr(response, "text", "")
                try:
                    return parse_json_from_text(text)
                except Exception:
                    # Some Gemini responses are plain text instead of JSON.
                    # For chat fallback payloads, accept raw text as answer.
                    if isinstance(fallback, dict) and "answer" in fallback and text.strip():
                        return {"answer": text.strip()}
                    raise

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_run_request)
                result = future.result(timeout=12)
                app.state.last_gemini_error = ""
                return result
        except FuturesTimeout:
            last_error = f"Request timeout on model {model_name}"
            continue
        except Exception as exc:
            error_text = str(exc).lower()
            last_error = str(exc)
            if "certificate_verify_failed" in error_text or "certificate is not yet valid" in error_text:
                app.state.last_gemini_error = "SSL certificate validation failed. Fix system date/time."
                if isinstance(fallback, dict) and "answer" in fallback:
                    return {"answer": "Gemini SSL failed because system date/time is incorrect. Fix Windows date/time and restart backend."}
                return fallback
            if "model" in error_text or "not found" in error_text or "permission" in error_text:
                should_try_discovery = True
                continue
            break

    # Expensive discovery is attempted only when model name/access errors happen.
    if should_try_discovery:
        discovered = app.state.discovered_models
        if discovered is None:
            discovered = discover_generate_models()
            app.state.discovered_models = discovered
        discovered_candidates = unique_keep_order(discovered)
        for model_name in discovered_candidates:
            if model_name in model_candidates:
                continue
            try:
                def _run_request_discovered():
                    model = genai.GenerativeModel(model_name)
                    response = model.generate_content(
                        prompt,
                        generation_config={
                            "temperature": 0.2,
                            "max_output_tokens": CHAT_MAX_OUTPUT_TOKENS,
                        },
                    )
                    text = getattr(response, "text", "")
                    try:
                        return parse_json_from_text(text)
                    except Exception:
                        if isinstance(fallback, dict) and "answer" in fallback and text.strip():
                            return {"answer": text.strip()}
                        raise

                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(_run_request_discovered)
                    result = future.result(timeout=12)
                    app.state.last_gemini_error = ""
                    return result
            except Exception as exc:
                last_error = str(exc)
                continue

    app.state.last_gemini_error = last_error or "Unknown Gemini request error"
    if isinstance(fallback, dict) and "answer" in fallback:
        return {"answer": f"Gemini request failed: {app.state.last_gemini_error}"}
    return fallback


def get_mongo_db():
    if MongoClient is None:
        return None
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=1500)
        client.admin.command("ping")
        db = client[MONGO_DB_NAME]
        db["ai_questions"].create_index(
            [("topic", 1), ("mode", 1), ("question", 1)],
            unique=True,
            name="topic_mode_question_unique",
        )
        db["chat_logs"].create_index([("user_id", 1), ("created_at", -1)], name="chat_user_time")
        db["attempts"].create_index([("user_id", 1), ("created_at", -1)], name="attempt_user_time")
        return db
    except Exception:
        return None


def fallback_mcq(topic_name: str, count: int) -> list[dict[str, Any]]:
    topic_key = next((key for key, meta in TOPICS.items() if meta["name"] == topic_name), "dsa")
    return build_mcq_questions(topic_key, count)


def fallback_coding(topic_name: str, count: int) -> list[dict[str, Any]]:
    topic_key = next((key for key, meta in TOPICS.items() if meta["name"] == topic_name), "dsa")
    return build_coding_questions(topic_key, count)


def generate_questions(topic: str, mode: str, count: int, api_key: str) -> list[dict[str, Any]]:
    if mode == "mcq":
        return build_mcq_questions(topic, count)

    return build_coding_questions(topic, count)


def build_bank_rows(topic: str, mode: str, count: int, start_index: int = 0) -> list[dict[str, Any]]:
    if mode == "mcq":
        return build_mcq_questions(topic, count, start_index=start_index)
    return build_coding_questions(topic, count, start_index=start_index)


def pool_needs_rebuild(topic: str, mode: str, coll) -> bool:
    docs = list(coll.find({"topic": topic, "mode": mode}).limit(5))
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


def save_questions(topic: str, mode: str, rows: list[dict[str, Any]], db, source: str = QUESTION_BANK_SOURCE):
    if db is None:
        key = f"{topic}:{mode}"
        existing = MEMORY_STORE["questions"].setdefault(key, [])
        known = {q["question"] for q in existing}
        for row in rows:
            if row["question"] not in known:
                row = dict(row)
                row["id"] = f"mem-{topic}-{mode}-{len(existing)+1}"
                row["source"] = source
                existing.append(row)
                known.add(row["question"])
        return

    coll = db["ai_questions"]
    for row in rows:
        doc = {
            "topic": topic,
            "mode": mode,
            "question": row["question"],
            "sequence": row.get("sequence") or extract_question_sequence(row["question"]),
            "solution": row.get("solution", ""),
            "difficulty": row.get("difficulty", "intermediate"),
            "source": source,
            "created_at": utc_now(),
        }
        if mode == "mcq":
            doc["options"] = row.get("options", [])
            doc["answer"] = row.get("answer", "")
        else:
            doc["constraints"] = row.get("constraints", "")
            doc["sample_input"] = row.get("sample_input", "")
            doc["sample_output"] = row.get("sample_output", "")
            doc["expected_approach"] = row.get("expected_approach", "")

        coll.update_one(
            {"topic": topic, "mode": mode, "question": row["question"]},
            {"$setOnInsert": doc},
            upsert=True,
        )


def ensure_pool(topic: str, mode: str, db, api_key: str, target: int = QUESTION_TARGET):
    if db is None:
        key = f"{topic}:{mode}"
        current = len(MEMORY_STORE["questions"].get(key, []))
        needed = max(0, target - current)
        if needed:
            rows = build_bank_rows(topic, mode, needed, start_index=current)
            save_questions(topic, mode, rows, db, source=QUESTION_BANK_SOURCE)
        return len(MEMORY_STORE["questions"].get(key, []))

    coll = db["ai_questions"]
    if pool_needs_rebuild(topic, mode, coll):
        coll.delete_many({"topic": topic, "mode": mode})

    current = coll.count_documents({"topic": topic, "mode": mode})
    needed = max(0, target - current)
    if needed > 0:
        rows = build_bank_rows(topic, mode, needed, start_index=current)
        save_questions(topic, mode, rows, db, source=QUESTION_BANK_SOURCE)
    return coll.count_documents({"topic": topic, "mode": mode})


def ensure_question_available(topic: str, mode: str, db, api_key: str):
    return ensure_pool(topic, mode, db, api_key, target=QUESTION_TARGET)


def ordered_questions(topic: str, mode: str, db):
    if db is None:
        key = f"{topic}:{mode}"
        pool = [dict(question) for question in MEMORY_STORE["questions"].get(key, [])]
        pool.sort(key=lambda item: (item.get("sequence") or extract_question_sequence(item.get("question", "")), item.get("question", "")))
        return pool

    coll = db["ai_questions"]
    docs = list(coll.find({"topic": topic, "mode": mode}))
    docs.sort(key=lambda item: (item.get("sequence") or extract_question_sequence(item.get("question", "")), str(item.get("_id", ""))))

    ordered = []
    for item in docs:
        doc = dict(item)
        doc["id"] = str(doc.get("_id"))
        doc.pop("_id", None)
        ordered.append(doc)
    return ordered


def question_at_position(topic: str, mode: str, db, position: int = 0):
    ordered = ordered_questions(topic, mode, db)
    if not ordered:
        return None

    index = position % len(ordered)
    doc = dict(ordered[index])
    doc["position"] = index
    doc["pool_size"] = len(ordered)
    return doc


def find_question(question_id: str, topic: str, mode: str, db):
    if db is None:
        key = f"{topic}:{mode}"
        for q in MEMORY_STORE["questions"].get(key, []):
            if q.get("id") == question_id:
                return q
        return None

    if ObjectId is None:
        return None

    try:
        doc = db["ai_questions"].find_one({"_id": ObjectId(question_id), "topic": topic, "mode": mode})
    except Exception:
        return None
    if not doc:
        return None
    doc["id"] = str(doc.get("_id"))
    doc.pop("_id", None)
    return doc


def evaluate_coding(question: dict[str, Any], answer: str, api_key: str):
    fallback = {
        "is_correct": len(answer.strip()) > 20,
        "feedback": "Add algorithm logic, edge cases, and complexity details." if len(answer.strip()) <= 20 else "Reasonable attempt. Compare with solution and refine edge cases.",
    }
    prompt = f"""
Evaluate interview answer and return strict JSON:
{{"is_correct": true/false, "feedback": "short practical feedback"}}
Question: {question.get('question')}
Expected approach: {question.get('expected_approach')}
User answer: {answer}
"""
    result = call_gemini_json(prompt, fallback, api_key)
    if not isinstance(result, dict):
        return fallback
    return {
        "is_correct": bool(result.get("is_correct", False)),
        "feedback": str(result.get("feedback", fallback["feedback"])).strip(),
    }


def save_attempt(payload: dict[str, Any], db):
    if db is None:
        MEMORY_STORE["attempts"].append(payload)
        return
    db["attempts"].insert_one(payload)


def fetch_recent_attempts(user_id: str, db, limit: int = 8):
    if db is None:
        rows = [a for a in MEMORY_STORE["attempts"] if a.get("user_id") == user_id]
        rows.sort(key=lambda x: x.get("created_at", utc_now()), reverse=True)
        return rows[:limit]
    return list(db["attempts"].find({"user_id": user_id}).sort("created_at", -1).limit(limit))


def save_chat(payload: dict[str, Any], db):
    if db is None:
        MEMORY_STORE["chat_logs"].append(payload)
        return
    db["chat_logs"].insert_one(payload)


def chat_history(user_id: str, db, limit: int = 20):
    if db is None:
        rows = [x for x in MEMORY_STORE["chat_logs"] if x.get("user_id") == user_id]
        rows.sort(key=lambda x: x.get("created_at", utc_now()))
        return rows[-limit:]
    rows = list(db["chat_logs"].find({"user_id": user_id}).sort("created_at", -1).limit(limit))
    rows.reverse()
    for row in rows:
        row.pop("_id", None)
    return rows


def clear_chat_history(user_id: str, db):
    if db is None:
        MEMORY_STORE["chat_logs"] = [x for x in MEMORY_STORE["chat_logs"] if x.get("user_id") != user_id]
        return
    db["chat_logs"].delete_many({"user_id": user_id})


@app.get("/")
def home():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/status")
def api_status(x_gemini_key: str | None = Header(default=None)):
    db = get_mongo_db()
    gemini_key = resolve_gemini_key(x_gemini_key)
    gemini_ok = configure_genai(gemini_key)
    return {
        "mongo": db is not None,
        "gemini": gemini_ok,
        "model": DEFAULT_GEMINI_MODEL,
    }


@app.get("/api/topics")
def api_topics():
    return {
        "topics": TOPICS,
        "modes": MODES,
    }


@app.post("/api/auth/signup")
def api_auth_signup(payload: AuthRequest):
    return create_user(payload.username, payload.password)


@app.post("/api/auth/login")
def api_auth_login(payload: AuthRequest):
    return login_user(payload.username, payload.password)


@app.post("/api/questions/generate")
def api_generate_questions(payload: GenerateQuestionsRequest, x_gemini_key: str | None = Header(default=None)):
    topic = payload.topic.lower()
    mode = payload.mode.lower()
    if topic not in TOPICS:
        raise HTTPException(status_code=400, detail="Invalid topic")
    if mode not in MODES:
        raise HTTPException(status_code=400, detail="Invalid mode")

    db = get_mongo_db()
    key = resolve_gemini_key(x_gemini_key)
    count = ensure_pool(topic, mode, db, key, target=min(payload.count, QUESTION_TARGET))
    return {"stored_questions": count}


@app.get("/api/questions/random")
def api_random_question(
    topic: str = Query(...),
    mode: str = Query(...),
    position: int = Query(default=0, ge=0),
    x_gemini_key: str | None = Header(default=None),
):
    topic = topic.lower()
    mode = mode.lower()
    if topic not in TOPICS:
        raise HTTPException(status_code=400, detail="Invalid topic")
    if mode not in MODES:
        raise HTTPException(status_code=400, detail="Invalid mode")

    db = get_mongo_db()
    key = resolve_gemini_key(x_gemini_key)
    ensure_question_available(topic, mode, db, key)
    question = question_at_position(topic, mode, db, position=position)
    if not question:
        raise HTTPException(status_code=500, detail="Could not load question")
    question["topic"] = topic
    question["mode"] = mode
    return question


@app.post("/api/attempts/submit")
def api_submit_attempt(payload: SubmitAttemptRequest, x_gemini_key: str | None = Header(default=None)):
    topic = payload.topic.lower()
    mode = payload.mode.lower()
    if topic not in TOPICS or mode not in MODES:
        raise HTTPException(status_code=400, detail="Invalid topic or mode")

    db = get_mongo_db()
    question = find_question(payload.question_id, topic, mode, db)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    key = resolve_gemini_key(x_gemini_key)

    if mode == "mcq":
        is_correct = payload.answer == question.get("answer")
        feedback = "Correct answer." if is_correct else "Wrong answer. Use solution to improve."
        correct_answer = question.get("answer", "")
    else:
        eval_result = evaluate_coding(question, payload.answer, key)
        is_correct = eval_result["is_correct"]
        feedback = eval_result["feedback"]
        correct_answer = ""

    attempt = {
        "user_id": payload.user_id,
        "topic": topic,
        "mode": mode,
        "question": question.get("question", ""),
        "question_id": payload.question_id,
        "submitted_answer": payload.answer,
        "is_correct": is_correct,
        "feedback": feedback,
        "solution": question.get("solution", ""),
        "correct_answer": correct_answer,
        "expected_approach": question.get("expected_approach", ""),
        "created_at": utc_now(),
    }
    save_attempt(attempt, db)

    return {
        "is_correct": is_correct,
        "feedback": feedback,
        "solution": question.get("solution", ""),
        "correct_answer": correct_answer,
        "expected_approach": question.get("expected_approach", ""),
    }


@app.get("/api/chat/history")
def api_chat_history(user_id: str = Query("local-user")):
    db = get_mongo_db()
    return {"history": chat_history(user_id, db)}


@app.post("/api/chat")
def api_chat(payload: ChatRequest, x_gemini_key: str | None = Header(default=None)):
    user_id = payload.user_id
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    db = get_mongo_db()
    recent = fetch_recent_attempts(user_id, db, limit=8)
    recent_chats = chat_history(user_id, db, limit=6)
    context_lines = []
    for row in recent:
        status = "correct" if row.get("is_correct") else "wrong"
        context_lines.append(f"- {row.get('topic', '').upper()} {row.get('mode', '').upper()}: {row.get('question', '')} => {status}")
    recent_chat_lines = []
    for row in recent_chats:
        q = str(row.get("user_message", "")).strip()
        a = str(row.get("assistant_message", "")).strip()
        if q:
            recent_chat_lines.append(f"- User: {q}")
        if a:
            recent_chat_lines.append(f"- Assistant: {a[:220]}")

    key = resolve_gemini_key(x_gemini_key)
    if not key:
        answer = "Gemini API key is not configured on server. Set GEMINI_API_KEY and restart backend."
        related_suggestions = [
            "Set GEMINI_API_KEY and restart backend.",
            "Ask again after backend restart.",
        ]
        record = {
            "user_id": user_id,
            "user_message": message,
            "assistant_message": answer,
            "related_suggestions": related_suggestions,
            "created_at": utc_now(),
        }
        save_chat(record, db)
        return {"answer": answer, "related_suggestions": related_suggestions}

    fallback = {"answer": "Gemini request failed. Check API key, billing, and model access."}
    topic = (payload.topic or "").lower().strip()
    mode = (payload.mode or "").lower().strip()
    topic_name = TOPICS.get(topic, {}).get("name", "")
    mode_name = MODES.get(mode, "")

    prompt = f"""
You are a coding interview mentor and technical Q&A assistant.
Answer the exact question user asked, even if no topic/mode is selected.
Default to programming/coding interpretation unless user explicitly asks non-technical career/HR advice.
Do not redirect user to select C++/Java/Python/DSA; just answer directly.
You can answer theory, syntax, coding examples, DSA, debugging, complexity, interview questions, project questions, and follow-ups from previous chat.
If the user asks "this", "that", "same", "previous", or a short follow-up, infer the topic from recent chat context.

Response style requirements:
- Keep language simple and practical.
- Keep output concise and scannable.
- Prefer short sections rather than one long paragraph.
- No follow-up question at the end.
- Include 2 or 3 short related follow-up suggestions that are specific to the user's topic.
- Suggestions must not be generic. Avoid phrases like "show a code example for this" unless you name the concept.

Recent user context:
{chr(10).join(context_lines) if context_lines else 'No recent attempts'}

Recent chat context:
{chr(10).join(recent_chat_lines) if recent_chat_lines else 'No previous chat context'}

Current selected topic: {topic_name if topic_name else 'Not selected'}
Current selected mode: {mode_name if mode_name else 'Not selected'}

User question:
{message}

Return strict JSON:
{{
  "answer": "...",
  "related_suggestions": ["...", "..."]
}}
"""
    out = call_gemini_json(prompt, fallback, key)
    if isinstance(out, dict) and any(k in out for k in ["direct_answer", "core_concept", "example", "common_mistakes", "when_to_use"]):
        answer = compose_structured_answer(out) or fallback["answer"]
    else:
        answer = out.get("answer") if isinstance(out, dict) else fallback["answer"]
        answer = normalize_chat_answer(answer) or fallback["answer"]

    if answer.lower().startswith("gemini request failed"):
        answer = build_local_structured_answer(message)

    related_suggestions = []
    if isinstance(out, dict):
        maybe_suggestions = out.get("related_suggestions", [])
        if isinstance(maybe_suggestions, list):
            related_suggestions = [str(x).strip() for x in maybe_suggestions if str(x).strip()][:3]

    if use_local_suggestions(related_suggestions):
        related_suggestions = build_related_suggestions(message, answer)

    record = {
        "user_id": user_id,
        "user_message": message,
        "assistant_message": answer,
        "related_suggestions": related_suggestions,
        "created_at": utc_now(),
    }
    save_chat(record, db)

    return {"answer": answer, "related_suggestions": related_suggestions}


@app.post("/api/chat/clear")
def api_chat_clear(payload: ClearChatRequest):
    db = get_mongo_db()
    clear_chat_history(payload.user_id, db)
    return {"ok": True}


app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("fastapi_app:app", host="127.0.0.1", port=8000, reload=True)
