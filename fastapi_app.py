from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, desc, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cache import cache_backend_name, cache_get, cache_set, rate_limit_allowed
from database import Base, SessionLocal, database_label, engine, get_db
from llm_provider import LLMUnavailableError, default_provider_name, generate_text, provider_status
from models import Attempt, ChatLog, Question, User
from observability import ObservabilityMiddleware, logger, metrics_snapshot
from question_bank import QUESTION_BANK_SIZE, build_coding_questions, build_mcq_questions, extract_question_sequence
from rag_store import RagDocument, index_documents, search as rag_search
from security import TokenError, create_access_token, decode_access_token


BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"
QUESTION_TARGET = QUESTION_BANK_SIZE
QUESTION_BANK_SOURCE = "question-bank-v3-sqlalchemy"
CHAT_MAX_OUTPUT_TOKENS = 900
ADMIN_USERNAMES = {
    username.strip().lower()
    for username in os.getenv("ADMIN_USERNAMES", "").split(",")
    if username.strip()
}

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

app = FastAPI(title="Interview Prep AI Stack")
app.add_middleware(ObservabilityMiddleware)
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
    user_id: str
    topic: str
    mode: str
    question_id: str
    answer: str
    provider: str | None = None


class ChatRequest(BaseModel):
    user_id: str
    message: str
    topic: str | None = None
    mode: str | None = None
    provider: str | None = None


class ClearChatRequest(BaseModel):
    user_id: str


class RagIndexRequest(BaseModel):
    documents: list[str] = Field(min_length=1, max_length=50)
    source: str = Field(default="manual", max_length=60)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, stored_password: str) -> bool:
    if not stored_password:
        return False
    if stored_password.startswith("pbkdf2_sha256$"):
        try:
            _, salt, expected = stored_password.split("$", 2)
        except ValueError:
            return False
        candidate = hash_password(password, salt).split("$", 2)[2]
        return secrets.compare_digest(candidate, expected)
    return secrets.compare_digest(password, stored_password)


def normalize_username(username: str) -> str:
    return re.sub(r"\s+", "", username.strip().lower())


def auth_response(user: User) -> dict[str, str]:
    role = user.role or "user"
    return {
        "user_id": str(user.id),
        "username": user.username,
        "role": role,
        "access_token": create_access_token(user_id=str(user.id), username=user.username, role=role),
        "token_type": "bearer",
    }


def current_user(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> User:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_access_token(token)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user_id = str(payload.get("sub", ""))
    if not user_id.isdigit():
        raise HTTPException(status_code=401, detail="Invalid token subject.")
    user = db.get(User, int(user_id))
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if (user.role or "user") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required.")
    return user


def verify_payload_user(payload_user_id: str, user: User) -> None:
    if str(user.id) != str(payload_user_id):
        raise HTTPException(status_code=403, detail="Cannot access another user's data.")


def rate_limit_request(request: Request, user: User | None = None) -> None:
    identity = f"user:{user.id}" if user else f"ip:{request.client.host if request.client else 'unknown'}"
    if not rate_limit_allowed(identity):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again soon.")


def ensure_runtime_schema() -> None:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "role" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(24) DEFAULT 'user'"))


def index_question_bank_for_rag(db: Session) -> int:
    rows = db.execute(select(Question).limit(500)).scalars().all()
    documents = [
        RagDocument(
            id=f"question:{row.id}",
            text=" ".join(
                part
                for part in [
                    row.question,
                    row.solution or "",
                    row.expected_approach or "",
                    row.answer or "",
                ]
                if part
            ),
            metadata={"topic": row.topic, "mode": row.mode, "source": "question_bank"},
        )
        for row in rows
    ]
    return index_documents(documents)


def log_chat_created(user_id: str, provider: str) -> None:
    logger.info("chat_created user_id=%s provider=%s", user_id, provider)


def parse_json_from_text(text: str) -> Any:
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("Empty response")

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    for pattern in (r"\[[\s\S]*\]", r"\{[\s\S]*\}"):
        match = re.search(pattern, cleaned)
        if match:
            return json.loads(match.group(0))

    raise ValueError("No valid JSON in model response")


def normalize_chat_answer(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "answer" in parsed:
            return str(parsed.get("answer", "")).strip()
        if isinstance(parsed, dict) and any(
            key in parsed for key in ("direct_answer", "core_concept", "example", "common_mistakes", "when_to_use")
        ):
            return compose_structured_answer(parsed)
    except Exception:
        pass

    if re.match(r"^\s*\{", text) and '"answer"' in text:
        match = re.search(r'"answer"\s*:\s*"([\s\S]*)', text)
        if match:
            answer_text = match.group(1)
            answer_text = re.split(r'"\s*,\s*"related_suggestions"\s*:', answer_text, maxsplit=1)[0]
            answer_text = re.sub(r'"\s*}\s*$', "", answer_text).strip()
            answer_text = answer_text.replace("\\n", "\n").replace('\\"', '"').replace("\\t", "    ")
            if answer_text:
                return normalize_chat_answer(answer_text)

    recovered = {}
    for key in ("direct_answer", "core_concept", "example", "common_mistakes", "when_to_use", "answer"):
        pattern = rf'"{key}"\s*:\s*"([\s\S]*?)"(?=,\s*"[a-z_]+"|\s*}}|$)'
        match = re.search(pattern, text)
        if match:
            recovered[key] = match.group(1).replace('\\"', '"').strip()
    if recovered:
        if "answer" in recovered:
            return recovered["answer"]
        return compose_structured_answer(recovered)

    return text


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


def extract_primary_chat_query(question: str) -> str:
    lines = [line.strip() for line in str(question or "").splitlines() if line.strip()]
    if not lines:
        return ""

    first_line = lines[0]
    strong_topic_keywords = [
        "pointer",
        "reference",
        "linked list",
        "stack",
        "queue",
        "tree",
        "graph",
        "array",
        "recursion",
        "heap",
        "hash",
        "binary search",
        "oop",
        "class",
    ]
    first_lower = first_line.lower()
    if any(keyword in first_lower for keyword in strong_topic_keywords):
        return first_line

    collected = []
    for line in lines:
        lower = line.lower()
        if re.match(r"^(def |class |#include|int main|public:|private:|protected:)", line):
            break
        if lower == "chatbot fix":
            break
        collected.append(line)
        if len(" ".join(collected)) >= 220:
            break

    return " ".join(collected).strip() or first_line


def prefer_local_chat_answer(question: str) -> bool:
    primary = extract_primary_chat_query(question).lower()
    if not primary:
        return False
    topics = ["pointer", "reference", "linked list", "stack", "queue", "tree", "graph", "array"]
    return len(primary.split()) <= 24 and any(topic in primary for topic in topics)


def build_related_suggestions(question: str, answer: str = "") -> list[str]:
    question_source = str(question or "").lower()
    answer_source = str(answer or "").lower()
    rules = [
        (["pointer", "reference", "memory"], ["Show pointer example in C++.", "Explain pointer vs reference.", "Explain dangling and null pointers."]),
        (["array", "list"], ["Show array implementation in C++.", "Compare array vs linked list.", "Give an array interview problem."]),
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
        if any(keyword in question_source for keyword in keywords):
            return suggestions
    for keywords, suggestions in rules:
        if any(keyword in answer_source for keyword in keywords):
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


def build_local_structured_answer(question: str) -> str:
    q = extract_primary_chat_query(question)
    lower = q.lower()

    if "linked list" in lower:
        payload = {
            "direct_answer": "A linked list is a linear data structure where each node stores data and a reference to the next node instead of using contiguous memory like an array.",
            "core_concept": "Main types: singly linked list, doubly linked list, circular singly linked list, and circular doubly linked list. Insertion or deletion at a known node is O(1), but searching is O(n).",
            "example": "Example: 10 -> 20 -> 30 -> null is a singly linked list. If you insert 15 after 10, it becomes 10 -> 15 -> 20 -> 30.",
            "common_mistakes": "Forgetting to update links in the correct order, losing the head pointer, and assuming linked lists support O(1) random access like arrays.",
            "when_to_use": "Use a linked list when you need frequent insertions or deletions and do not need fast index-based access.",
        }
        return compose_structured_answer(payload)

    if "stack" in lower:
        payload = {
            "direct_answer": "A stack is a linear data structure that follows LIFO: Last In, First Out.",
            "core_concept": "Main operations are push, pop, peek/top, and isEmpty. Push and pop are usually O(1).",
            "example": "If you push 10, 20, 30, the top is 30. One pop removes 30 first, then 20 becomes the new top.",
            "common_mistakes": "Popping from an empty stack, confusing stack order with queue order, and forgetting recursion uses an implicit call stack.",
            "when_to_use": "Use a stack for expression evaluation, undo operations, DFS, and balanced-parentheses problems.",
        }
        return compose_structured_answer(payload)

    if "queue" in lower:
        payload = {
            "direct_answer": "A queue is a linear data structure that follows FIFO: First In, First Out.",
            "core_concept": "Main operations are enqueue, dequeue, front/peek, and isEmpty. Enqueue and dequeue are usually O(1).",
            "example": "If you enqueue 10, 20, 30, the first dequeue removes 10, then 20 becomes the front.",
            "common_mistakes": "Confusing queue behavior with stack behavior and using slow implementations that shift every remaining element.",
            "when_to_use": "Use a queue in BFS traversal, scheduling, buffering, and producer-consumer systems.",
        }
        return compose_structured_answer(payload)

    if "tree" in lower and "binary indexed tree" not in lower:
        payload = {
            "direct_answer": "A tree is a hierarchical data structure made of nodes connected by edges, with one root node and parent-child relationships.",
            "core_concept": "Common types include binary tree, binary search tree, AVL tree, heap, and trie. Important terms are root, parent, child, leaf, height, and subtree.",
            "example": "In a binary tree, node 10 can have left child 5 and right child 15. Traversals include preorder, inorder, postorder, and level order.",
            "common_mistakes": "Confusing BST rules with general binary trees, missing null/base cases in recursion, and mixing up traversal orders.",
            "when_to_use": "Use trees for hierarchical data, expression parsing, file systems, prefix lookup, and ordered search structures.",
        }
        return compose_structured_answer(payload)

    if "graph" in lower:
        payload = {
            "direct_answer": "A graph is a set of vertices and edges that connect pairs of vertices.",
            "core_concept": "Graphs can be directed or undirected, weighted or unweighted, cyclic or acyclic. Common representations are adjacency list and adjacency matrix.",
            "example": "If A is connected to B and C, the adjacency list is A:[B,C]. Traversals are BFS and DFS.",
            "common_mistakes": "Choosing the wrong representation, not tracking visited nodes, and assuming graph rules behave like tree rules.",
            "when_to_use": "Use graphs for routes, dependencies, networks, social relationships, and state transitions.",
        }
        return compose_structured_answer(payload)

    if "array" in lower:
        payload = {
            "direct_answer": "An array is a linear data structure that stores same-type elements in contiguous memory locations.",
            "core_concept": "Access is index-based, so reading or writing an element by index is O(1). Common forms are 1D arrays and 2D arrays.",
            "example": "Example: arr = [10, 20, 30], arr[1] gives 20. In C++: int arr[3] = {10, 20, 30};",
            "common_mistakes": "Index out of bounds, confusing index with position, and assuming fixed-size arrays can grow automatically.",
            "when_to_use": "Use arrays when you need fast index access, predictable memory layout, and ordered elements.",
        }
        return compose_structured_answer(payload)

    if "pointer" in lower or "reference" in lower:
        payload = {
            "direct_answer": "A pointer stores the memory address of another variable. Common pointer types in C/C++ include null pointer, void pointer, wild or uninitialized pointer, dangling pointer, function pointer, pointer to pointer, pointer to const, and constant pointer.",
            "core_concept": "Use '&' to get an address and '*' to dereference it. Pointer vs reference: a pointer can be null, reassigned, and needs dereferencing, while a reference is an alias that must be initialized and usually cannot be reseated. A null pointer points to no valid object. A dangling pointer points to memory that has already been deleted or gone out of scope.",
            "example": "C++ example:\n```cpp\nint x = 5;\nint* p = &x;\ncout << *p << \"\\n\";   // 5\n*p = 9;\ncout << x << \"\\n\";    // 9\n\nint* np = nullptr;\nint** pp = &p;\n```\nThis works because p stores the address of x, so changing *p changes x itself.",
            "common_mistakes": "Using an uninitialized pointer, dereferencing nullptr, keeping a dangling pointer after delete, and confusing `int* p` with `int &r` because pointers and references are not interchangeable.",
            "when_to_use": "Use pointers for dynamic memory, arrays and strings in low-level code, linked data structures, callbacks, and memory-oriented systems code. Prefer references when you only need a safer alias.",
        }
        return compose_structured_answer(payload)

    payload = {
        "direct_answer": f"Here is a concise technical explanation for: {q}",
        "core_concept": "Break the problem into definition, key operations, complexity, and edge cases.",
        "example": "Give one small input/output or code snippet and explain why it works.",
        "common_mistakes": "Typical issues are edge-case misses, wrong complexity assumptions, and off-by-one errors.",
        "when_to_use": "Choose the concept or approach when it gives correct logic with acceptable time and space complexity.",
    }
    return compose_structured_answer(payload)


def build_bank_rows(topic: str, mode: str, count: int, start_index: int = 0) -> list[dict[str, Any]]:
    if mode == "mcq":
        return build_mcq_questions(topic, count, start_index=start_index)
    return build_coding_questions(topic, count, start_index=start_index)


def question_is_stale(question: Question, mode: str) -> bool:
    if question.source != QUESTION_BANK_SOURCE:
        return True
    if not isinstance(question.sequence, int):
        return True
    if mode == "mcq":
        return not question.options or len(question.options) < 4 or not question.answer
    return not question.expected_approach


def question_count(db: Session, topic: str, mode: str) -> int:
    return int(
        db.scalar(select(func.count(Question.id)).where(Question.topic == topic, Question.mode == mode)) or 0
    )


def pool_needs_rebuild(db: Session, topic: str, mode: str) -> bool:
    rows = db.execute(
        select(Question).where(Question.topic == topic, Question.mode == mode).order_by(Question.sequence.asc()).limit(5)
    ).scalars().all()
    if not rows:
        return False
    return any(question_is_stale(row, mode) for row in rows)


def save_question_rows(db: Session, topic: str, mode: str, rows: list[dict[str, Any]]) -> int:
    inserted = 0
    for row in rows:
        question = Question(
            topic=topic,
            mode=mode,
            question=row["question"],
            sequence=row.get("sequence") or extract_question_sequence(row["question"]),
            difficulty=row.get("difficulty", "intermediate"),
            source=QUESTION_BANK_SOURCE,
            solution=row.get("solution", ""),
            options=row.get("options"),
            answer=row.get("answer"),
            constraints=row.get("constraints"),
            sample_input=row.get("sample_input"),
            sample_output=row.get("sample_output"),
            expected_approach=row.get("expected_approach"),
        )
        db.add(question)
        inserted += 1
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return inserted


def ensure_question_pool(db: Session, topic: str, mode: str, target: int = QUESTION_TARGET) -> int:
    if pool_needs_rebuild(db, topic, mode):
        db.execute(delete(Question).where(Question.topic == topic, Question.mode == mode))
        db.commit()

    current = question_count(db, topic, mode)
    needed = max(0, target - current)
    if needed:
        rows = build_bank_rows(topic, mode, needed, start_index=current)
        save_question_rows(db, topic, mode, rows)
    return question_count(db, topic, mode)


def seed_question_bank(db: Session) -> None:
    for topic in TOPICS:
        for mode in MODES:
            ensure_question_pool(db, topic, mode, target=QUESTION_TARGET)


def serialize_question(question: Question) -> dict[str, Any]:
    payload = {
        "id": str(question.id),
        "topic": question.topic,
        "mode": question.mode,
        "question": question.question,
        "sequence": question.sequence,
        "difficulty": question.difficulty,
        "solution": question.solution or "",
    }
    if question.mode == "mcq":
        payload["options"] = list(question.options or [])
        payload["answer"] = question.answer or ""
    else:
        payload["constraints"] = question.constraints or ""
        payload["sample_input"] = question.sample_input or "N/A"
        payload["sample_output"] = question.sample_output or "N/A"
        payload["expected_approach"] = question.expected_approach or ""
    return payload


def ordered_questions(db: Session, topic: str, mode: str) -> list[Question]:
    return db.execute(
        select(Question)
        .where(Question.topic == topic, Question.mode == mode)
        .order_by(Question.sequence.asc(), Question.id.asc())
    ).scalars().all()


def question_at_position(db: Session, topic: str, mode: str, position: int = 0) -> dict[str, Any] | None:
    rows = ordered_questions(db, topic, mode)
    if not rows:
        return None
    index = position % len(rows)
    payload = serialize_question(rows[index])
    payload["position"] = index
    payload["pool_size"] = len(rows)
    return payload


def find_question(db: Session, question_id: str, topic: str, mode: str) -> Question | None:
    try:
        numeric_id = int(question_id)
    except ValueError:
        return None
    question = db.get(Question, numeric_id)
    if not question:
        return None
    if question.topic != topic or question.mode != mode:
        return None
    return question


def serialize_chat_log(row: ChatLog) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "user_id": row.user_id,
        "user_message": row.user_message,
        "assistant_message": row.assistant_message,
        "provider": row.provider,
        "related_suggestions": list(row.related_suggestions or []),
        "created_at": row.created_at.isoformat(),
    }


def fetch_recent_attempts(db: Session, user_id: str, limit: int = 8) -> list[Attempt]:
    return db.execute(
        select(Attempt).where(Attempt.user_id == user_id).order_by(desc(Attempt.created_at)).limit(limit)
    ).scalars().all()


def chat_history(db: Session, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = db.execute(
        select(ChatLog).where(ChatLog.user_id == user_id).order_by(desc(ChatLog.created_at)).limit(limit)
    ).scalars().all()
    rows = list(reversed(rows))
    return [serialize_chat_log(row) for row in rows]


def save_chat_log(db: Session, user_id: str, user_message: str, assistant_message: str, related_suggestions: list[str], provider: str) -> None:
    db.add(
        ChatLog(
            user_id=user_id,
            user_message=user_message,
            assistant_message=assistant_message,
            related_suggestions=related_suggestions,
            provider=provider,
        )
    )
    db.commit()


def clear_chat_history(db: Session, user_id: str) -> None:
    db.execute(delete(ChatLog).where(ChatLog.user_id == user_id))
    db.commit()


def build_chat_prompt(
    message: str,
    context_lines: list[str],
    recent_chat_lines: list[str],
    rag_lines: list[str],
    topic_name: str,
    mode_name: str,
) -> str:
    return f"""
You are a coding interview mentor and technical Q&A assistant.
Answer the exact question the user asked, even if no topic or mode is selected.
Default to programming and coding interpretation unless the user explicitly asks for non-technical career advice.
Do not redirect the user to select a language. Just answer directly.
If the current message clearly names a topic like pointer, linked list, stack, queue, tree, graph, array, or reference, answer that topic directly and do not let previous chat context change the meaning.
For pointer questions, default to C or C++ style pointers unless the user explicitly asks about Python object references.

Response style requirements:
- Keep language simple and practical.
- Keep output concise and scannable.
- Prefer short sections rather than one long paragraph.
- No follow-up question at the end.
- Include 2 or 3 short related follow-up suggestions that are specific to the user's topic.
- Suggestions must not be generic.

Recent user context:
{chr(10).join(context_lines) if context_lines else 'No recent attempts'}

Recent chat context:
{chr(10).join(recent_chat_lines) if recent_chat_lines else 'No previous chat context'}

Retrieved reference context:
{chr(10).join(rag_lines) if rag_lines else 'No retrieved reference context'}

Current selected topic: {topic_name or 'Not selected'}
Current selected mode: {mode_name or 'Not selected'}

User question:
{message}

Return strict JSON:
{{
  "answer": "...",
  "related_suggestions": ["...", "..."]
}}
""".strip()


def evaluate_coding(question: Question, answer: str, provider: str | None) -> dict[str, Any]:
    fallback = {
        "is_correct": len(answer.strip()) > 20,
        "feedback": "Add algorithm logic, edge cases, and complexity details." if len(answer.strip()) <= 20 else "Reasonable attempt. Compare with solution and refine edge cases.",
    }
    prompt = f"""
Evaluate an interview-style coding answer and return strict JSON:
{{"is_correct": true, "feedback": "short practical feedback"}}
Question: {question.question}
Expected approach: {question.expected_approach or ""}
Reference solution: {question.solution or ""}
User answer: {answer}
""".strip()
    try:
        raw_text, _ = generate_text(prompt, provider=provider, max_tokens=250)
        parsed = parse_json_from_text(raw_text)
        if not isinstance(parsed, dict):
            return fallback
        return {
            "is_correct": bool(parsed.get("is_correct", False)),
            "feedback": str(parsed.get("feedback", fallback["feedback"])).strip() or fallback["feedback"],
        }
    except Exception:
        return fallback


def generate_chat_completion(payload: ChatRequest, db: Session) -> tuple[str, list[str], str]:
    message = payload.message.strip()
    primary_message = extract_primary_chat_query(message)
    requested_provider = (payload.provider or "").strip().lower() or None

    recent_attempts = fetch_recent_attempts(db, payload.user_id, limit=8)
    recent_chat_rows = chat_history(db, payload.user_id, limit=6)

    context_lines = []
    for row in recent_attempts:
        status = "correct" if row.is_correct else "wrong"
        context_lines.append(f"- {row.topic.upper()} {row.mode.upper()}: {row.question} => {status}")

    recent_chat_lines = []
    for row in recent_chat_rows:
        q = str(row.get("user_message", "")).strip()
        a = str(row.get("assistant_message", "")).strip()
        if q:
            recent_chat_lines.append(f"- User: {q}")
        if a:
            recent_chat_lines.append(f"- Assistant: {a[:220]}")

    rag_lines = [f"- {document.text[:260]}" for document in rag_search(primary_message or message, limit=3)]

    if prefer_local_chat_answer(message):
        answer = build_local_structured_answer(primary_message)
        return answer, build_related_suggestions(primary_message, answer), "local"

    topic = (payload.topic or "").lower().strip()
    mode = (payload.mode or "").lower().strip()
    prompt = build_chat_prompt(
        message,
        context_lines,
        recent_chat_lines,
        rag_lines,
        TOPICS.get(topic, {}).get("name", ""),
        MODES.get(mode, ""),
    )

    fallback_answer = build_local_structured_answer(primary_message or message)
    provider_used = "local"
    related_suggestions: list[str] = []

    try:
        raw_text, provider_used = generate_text(prompt, provider=requested_provider, max_tokens=CHAT_MAX_OUTPUT_TOKENS)
        parsed = parse_json_from_text(raw_text)
        if isinstance(parsed, dict) and any(
            key in parsed for key in ("direct_answer", "core_concept", "example", "common_mistakes", "when_to_use")
        ):
            answer = compose_structured_answer(parsed) or fallback_answer
        elif isinstance(parsed, dict):
            answer = normalize_chat_answer(parsed.get("answer", "")) or fallback_answer
            maybe_suggestions = parsed.get("related_suggestions", [])
            if isinstance(maybe_suggestions, list):
                related_suggestions = [str(item).strip() for item in maybe_suggestions if str(item).strip()][:3]
        else:
            answer = normalize_chat_answer(raw_text) or fallback_answer
    except (LLMUnavailableError, RuntimeError, ValueError, json.JSONDecodeError):
        answer = fallback_answer
        provider_used = "local"
    except Exception:
        answer = fallback_answer
        provider_used = "local"

    if "pointer" in primary_message.lower() and "python does not have explicit" in answer.lower() and "python" not in primary_message.lower():
        answer = build_local_structured_answer(primary_message)
        provider_used = "local"

    if use_local_suggestions(related_suggestions):
        related_suggestions = build_related_suggestions(primary_message or message, answer)

    return answer, related_suggestions, provider_used


def iter_answer_chunks(text: str) -> list[str]:
    parts = re.findall(r"\S+\s*", text)
    if not parts:
        return [text]
    chunks = []
    for index in range(0, len(parts), 6):
        chunks.append("".join(parts[index:index + 6]))
    return chunks


def frontend_not_built_response() -> HTMLResponse:
    return HTMLResponse(
        """
        <html>
          <head>
            <title>Frontend Not Built</title>
            <style>
              body { font-family: Segoe UI, sans-serif; background: #0b1220; color: #e5eef8; padding: 48px; }
              .card { max-width: 880px; margin: 0 auto; background: #111b2e; border: 1px solid #223453; border-radius: 16px; padding: 28px; }
              code { background: #0a1424; padding: 2px 6px; border-radius: 6px; }
              pre { background: #08111f; padding: 16px; border-radius: 12px; overflow-x: auto; }
            </style>
          </head>
          <body>
            <div class="card">
              <h1>Frontend build not found</h1>
              <p>This project now uses a Vite React + TypeScript + Tailwind frontend.</p>
              <p>Run one of these:</p>
              <pre>cd frontend
npm install
npm run dev</pre>
              <p>Or run Docker:</p>
              <pre>docker compose up --build</pre>
            </div>
          </body>
        </html>
        """.strip()
    )


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_runtime_schema()
    db = SessionLocal()
    try:
        seed_question_bank(db)
        indexed = index_question_bank_for_rag(db)
        logger.info("startup database=%s cache=%s rag_indexed=%s", database_label(), cache_backend_name(), indexed)
    finally:
        db.close()


@app.get("/api/status")
def api_status() -> dict[str, Any]:
    return {
        "database": database_label(),
        "database_url": engine.url.render_as_string(hide_password=True),
        "cache": cache_backend_name(),
        "providers": provider_status(),
        "default_provider": default_provider_name(),
        "frontend_built": (FRONTEND_DIST_DIR / "index.html").exists(),
    }


@app.get("/api/topics")
def api_topics() -> dict[str, Any]:
    cached = cache_get("topics:modes")
    if cached:
        return cached
    payload = {"topics": TOPICS, "modes": MODES}
    cache_set("topics:modes", payload, ttl_seconds=300)
    return payload


@app.get("/api/metrics")
def api_metrics(_: User = Depends(require_admin)) -> dict[str, object]:
    return metrics_snapshot()


@app.get("/api/me")
def api_me(user: User = Depends(current_user)) -> dict[str, str]:
    return {"user_id": str(user.id), "username": user.username, "role": user.role or "user"}


@app.post("/api/rag/index")
def api_rag_index(payload: RagIndexRequest, _: User = Depends(require_admin)) -> dict[str, int]:
    documents = [
        RagDocument(
            id=f"{payload.source}:{hashlib.sha256(document.encode('utf-8')).hexdigest()}",
            text=document,
            metadata={"source": payload.source},
        )
        for document in payload.documents
    ]
    return {"indexed": index_documents(documents)}


@app.post("/api/auth/signup")
def api_auth_signup(payload: AuthRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    normalized = normalize_username(payload.username)
    if not re.fullmatch(r"[a-z0-9_]{3,40}", normalized):
        raise HTTPException(status_code=400, detail="Username must be 3-40 characters using letters, numbers, or underscore.")
    if len(payload.password.strip()) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters.")

    existing = db.execute(select(User).where(User.username == normalized)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Account already exists. Use login instead.")

    role = "admin" if normalized in ADMIN_USERNAMES else "user"
    user = User(username=normalized, password_hash=hash_password(payload.password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return auth_response(user)


@app.post("/api/auth/login")
def api_auth_login(payload: AuthRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    normalized = normalize_username(payload.username)
    user = db.execute(select(User).where(User.username == normalized)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Account not found. Sign up first.")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect password.")

    user.last_login_at = utc_now()
    db.commit()
    return auth_response(user)


@app.post("/api/questions/generate")
def api_generate_questions(
    payload: GenerateQuestionsRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict[str, int]:
    topic = payload.topic.lower().strip()
    mode = payload.mode.lower().strip()
    if topic not in TOPICS:
        raise HTTPException(status_code=400, detail="Invalid topic")
    if mode not in MODES:
        raise HTTPException(status_code=400, detail="Invalid mode")
    count = ensure_question_pool(db, topic, mode, target=min(payload.count, QUESTION_TARGET))
    return {"stored_questions": count}


@app.get("/api/questions/random")
def api_random_question(
    topic: str = Query(...),
    mode: str = Query(...),
    position: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    _ = user
    topic = topic.lower().strip()
    mode = mode.lower().strip()
    if topic not in TOPICS:
        raise HTTPException(status_code=400, detail="Invalid topic")
    if mode not in MODES:
        raise HTTPException(status_code=400, detail="Invalid mode")

    ensure_question_pool(db, topic, mode)
    question = question_at_position(db, topic, mode, position=position)
    if not question:
        raise HTTPException(status_code=500, detail="Could not load question")
    return question


@app.post("/api/attempts/submit")
def api_submit_attempt(
    payload: SubmitAttemptRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    verify_payload_user(payload.user_id, user)
    rate_limit_request(request, user)
    topic = payload.topic.lower().strip()
    mode = payload.mode.lower().strip()
    if topic not in TOPICS or mode not in MODES:
        raise HTTPException(status_code=400, detail="Invalid topic or mode")

    question = find_question(db, payload.question_id, topic, mode)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    if mode == "mcq":
        is_correct = payload.answer == (question.answer or "")
        feedback = "Correct answer." if is_correct else "Wrong answer. Use the explanation and retry."
        correct_answer = question.answer or ""
    else:
        evaluation = evaluate_coding(question, payload.answer, payload.provider)
        is_correct = evaluation["is_correct"]
        feedback = evaluation["feedback"]
        correct_answer = ""

    db.add(
        Attempt(
            user_id=payload.user_id,
            topic=topic,
            mode=mode,
            question=question.question,
            question_id=str(question.id),
            submitted_answer=payload.answer,
            is_correct=is_correct,
            feedback=feedback,
            solution=question.solution or "",
            correct_answer=correct_answer,
            expected_approach=question.expected_approach or "",
        )
    )
    db.commit()

    return {
        "is_correct": is_correct,
        "feedback": feedback,
        "solution": question.solution or "",
        "correct_answer": correct_answer,
        "expected_approach": question.expected_approach or "",
    }


@app.get("/api/chat/history")
def api_chat_history(
    user_id: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    verify_payload_user(user_id, user)
    return {"history": chat_history(db, user_id)}


@app.post("/api/chat")
def api_chat(
    payload: ChatRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    verify_payload_user(payload.user_id, user)
    rate_limit_request(request, user)
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    answer, related_suggestions, provider_used = generate_chat_completion(payload, db)
    save_chat_log(db, payload.user_id, message, answer, related_suggestions, provider_used)
    background_tasks.add_task(log_chat_created, payload.user_id, provider_used)
    return {
        "answer": answer,
        "related_suggestions": related_suggestions,
        "provider": provider_used,
    }


@app.post("/api/chat/stream")
def api_chat_stream(
    payload: ChatRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> StreamingResponse:
    verify_payload_user(payload.user_id, user)
    rate_limit_request(request, user)
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    answer, related_suggestions, provider_used = generate_chat_completion(payload, db)
    save_chat_log(db, payload.user_id, message, answer, related_suggestions, provider_used)
    background_tasks.add_task(log_chat_created, payload.user_id, provider_used)

    def stream():
        for chunk in iter_answer_chunks(answer):
            yield json.dumps({"type": "token", "value": chunk}) + "\n"
        yield json.dumps(
            {
                "type": "done",
                "answer": answer,
                "related_suggestions": related_suggestions,
                "provider": provider_used,
            }
        ) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.post("/api/chat/clear")
def api_chat_clear(
    payload: ClearChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, bool]:
    verify_payload_user(payload.user_id, user)
    clear_chat_history(db, payload.user_id)
    return {"ok": True}


def serve_frontend_asset(full_path: str) -> FileResponse | HTMLResponse:
    index_path = FRONTEND_DIST_DIR / "index.html"
    if not index_path.exists():
        return frontend_not_built_response()

    if full_path:
        candidate = (FRONTEND_DIST_DIR / full_path).resolve()
        dist_root = FRONTEND_DIST_DIR.resolve()
        if candidate.exists() and candidate.is_file() and candidate.is_relative_to(dist_root):
            return FileResponse(candidate)
    return FileResponse(index_path)


@app.get("/", include_in_schema=False, response_model=None)
def home():
    return serve_frontend_asset("")


@app.get("/{full_path:path}", include_in_schema=False, response_model=None)
def frontend_routes(full_path: str):
    if full_path.startswith("api"):
        raise HTTPException(status_code=404, detail="Not found")
    return serve_frontend_asset(full_path)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("fastapi_app:app", host="127.0.0.1", port=8000, reload=True)
