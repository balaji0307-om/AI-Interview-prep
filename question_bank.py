from __future__ import annotations

import re
from typing import Any

QUESTION_BANK_SIZE = 120


def extract_question_sequence(question: str, fallback: int = 10**9) -> int:
    match = re.search(r"\bQ(\d+):", str(question or ""))
    if not match:
        return fallback
    return int(match.group(1))


def _concept(subject: str, correct: str, distractors: list[str], solution: str) -> dict[str, Any]:
    return {
        "subject": subject,
        "correct": correct,
        "distractors": distractors,
        "solution": solution,
    }


def _challenge(
    statement: str,
    constraints: str,
    sample_input: str,
    sample_output: str,
    expected_approach: str,
    solution: str,
) -> dict[str, Any]:
    return {
        "statement": statement,
        "constraints": constraints,
        "sample_input": sample_input,
        "sample_output": sample_output,
        "expected_approach": expected_approach,
        "solution": solution,
    }


MCQ_SCENARIOS = [
    "An interviewer asks how you would reason about {subject} in production code. Which answer is strongest?",
    "During a code review focused on {subject}, which option best handles large-input constraints?",
    "You need to explain {subject} with clear tradeoff thinking. Which response fits best?",
    "A teammate introduced a bug around {subject}. Which answer best describes the safe fix?",
    "For a maintainability-focused solution involving {subject}, which option is most defensible?",
    "When edge cases matter for {subject}, which answer should you give?",
    "Which statement about {subject} best balances correctness and readability?",
    "If memory usage is under scrutiny for {subject}, which option is strongest?",
    "A follow-up asks for the interview caveat behind {subject}. Which answer is right?",
    "Which response about {subject} would most improve a code-review discussion?",
    "You are comparing two implementations that differ around {subject}. Which explanation is best?",
    "For a debugging round centered on {subject}, which option best explains the core idea?",
]


CODING_VARIANTS = [
    {
        "prompt": "Return the result in a deterministic order that is easy to test.",
        "constraints": "Define tie-breaking rules instead of relying on incidental ordering.",
        "expected": "Use stable ordering when multiple valid outputs exist.",
        "solution": "Make ordering explicit so repeated runs behave the same way.",
    },
    {
        "prompt": "Handle empty input, duplicates, and single-item inputs explicitly.",
        "constraints": "State what happens for empty collections before writing the happy path.",
        "expected": "Guard edge cases first so the main logic stays clean.",
        "solution": "Early returns and careful duplicate handling prevent boundary bugs.",
    },
    {
        "prompt": "Assume input size can reach 10^5, so the naive quadratic version is too slow.",
        "constraints": "Target linear or n log n performance where reasonable.",
        "expected": "Pick the data structure that removes repeated rescans.",
        "solution": "Use hashing, sorting, heaps, or window techniques instead of nested loops.",
    },
    {
        "prompt": "Avoid recursion if deep input could overflow the call stack.",
        "constraints": "Prefer iterative traversal when depth is unbounded.",
        "expected": "Use an explicit stack, queue, or loop-based state machine.",
        "solution": "An iterative design is safer when input depth can spike.",
    },
    {
        "prompt": "Structure the code as reusable helpers or classes instead of one giant function.",
        "constraints": "Keep parsing, state updates, and output formatting separate.",
        "expected": "Name the helper responsibilities before you start coding.",
        "solution": "Smaller units make the solution easier to test and explain.",
    },
    {
        "prompt": "Mention the tests you would run for the hardest edge cases.",
        "constraints": "Cover boundary values, duplicates, and invalid transitions.",
        "expected": "Pair the main algorithm with a short but concrete test plan.",
        "solution": "Interviewers want to see verification thinking, not just code generation.",
    },
    {
        "prompt": "Keep extra space low when practical instead of copying large intermediate results.",
        "constraints": "Call out which buffers are required and which can be avoided.",
        "expected": "Use in-place updates or rolling state when the algorithm allows it.",
        "solution": "Space-aware designs usually come from tracking only the state you truly need.",
    },
    {
        "prompt": "Separate input normalization from the core algorithm.",
        "constraints": "Clean malformed or mixed-case data before the main pass if needed.",
        "expected": "Normalize once, then keep the core logic simple and consistent.",
        "solution": "A small preprocessing step often removes branching from the main algorithm.",
    },
    {
        "prompt": "Explain your time and space complexity as part of the final answer.",
        "constraints": "Be explicit about the dominant operation in your complexity claim.",
        "expected": "Match the chosen data structure to the complexity target you describe.",
        "solution": "The best interview answers connect implementation choices to complexity clearly.",
    },
    {
        "prompt": "Make the solution safe for repeated calls in the same process.",
        "constraints": "Avoid hidden global state and reset mutable helpers between runs.",
        "expected": "Keep function-local state isolated unless shared state is intentional.",
        "solution": "Stateless or well-encapsulated state prevents flaky repeat execution.",
    },
    {
        "prompt": "Prefer a design that can be extended with one extra requirement later.",
        "constraints": "Do not hardcode assumptions that make the next change painful.",
        "expected": "Choose data structures that leave room for one more field or rule.",
        "solution": "Extensible structure beats brittle special-casing in interview follow-ups.",
    },
    {
        "prompt": "Call out how you would debug the first failing test quickly.",
        "constraints": "Identify the intermediate state or invariant you would print or assert.",
        "expected": "Keep one or two invariants in mind while writing the solution.",
        "solution": "Strong invariants make debugging and explanation much faster.",
    },
]


MCQ_BANKS = {
    "python": [
        _concept(
            "list vs tuple",
            "Use tuples for fixed, hashable records and lists when the contents must change.",
            [
                "Lists are always faster because they support more operations.",
                "Tuples should be avoided because they cannot store mixed data.",
                "Choose lists whenever you need dictionary keys.",
            ],
            "Tuples communicate immutability and can be used as dictionary keys when their members are hashable, while lists are the better choice for mutable sequences.",
        ),
        _concept(
            "dictionary and set lookup",
            "Average O(1) lookup comes from hashing, although worst-case performance can degrade under heavy collisions.",
            [
                "Dictionary lookup is O(1) in every possible case.",
                "Sets are faster because they sort values before lookup.",
                "Hash tables only help when the keys are integers.",
            ],
            "Hash-based containers provide average constant-time membership checks, but interview answers should still mention hashing assumptions and collision behavior.",
        ),
        _concept(
            "generators vs materialized lists",
            "Generators stream values lazily, which lowers peak memory when you do not need every result at once.",
            [
                "Generators always run faster because they skip iteration overhead.",
                "Lists are better for large pipelines because they force eager evaluation.",
                "Generators cannot be used inside for-loops.",
            ],
            "A generator is useful when you want sequential consumption instead of allocating the entire result upfront.",
        ),
        _concept(
            "shallow copy vs deep copy",
            "A shallow copy duplicates only the outer container, so nested mutable objects are still shared.",
            [
                "A shallow copy recursively clones every nested object.",
                "Deep copy is only needed for immutable values.",
                "Assignment and shallow copy behave the same for nested data.",
            ],
            "Interviewers expect you to mention that aliasing bugs often come from copying only the top-level container.",
        ),
        _concept(
            "mutable default arguments",
            "Default mutable objects are created once at function definition time, so a None sentinel is safer.",
            [
                "Mutable defaults reset every time the function is called.",
                "Using a list default is fine as long as the list starts empty.",
                "The fix is to convert the list into a tuple before mutating it.",
            ],
            "A classic Python trap is shared state across calls; the common fix is defaulting to None and allocating inside the function body.",
        ),
        _concept(
            "decorators",
            "Decorators wrap callable behavior without changing the call sites, which is useful for logging, retries, caching, or auth checks.",
            [
                "Decorators are only for class methods, not functions.",
                "A decorator must always return the original function unchanged.",
                "Decorators are mainly used to speed up loops automatically.",
            ],
            "A strong answer describes decorators as higher-order functions that add behavior while preserving the call contract.",
        ),
        _concept(
            "context managers",
            "Use a context manager to guarantee setup and teardown, even when an exception is raised.",
            [
                "Context managers only make code shorter; they do not affect safety.",
                "The with statement suppresses every exception automatically.",
                "Context managers are only useful for file handles.",
            ],
            "Context managers express resource lifetime directly and make cleanup deterministic.",
        ),
        _concept(
            "the GIL and concurrency",
            "Threads help most with I/O-bound work in CPython, while multiprocessing is better for CPU-bound parallelism.",
            [
                "Python threads fully parallelize CPU-heavy bytecode in CPython.",
                "Multiprocessing is slower in every case because processes are heavier than threads.",
                "The GIL prevents Python from doing concurrent I/O.",
            ],
            "A good interview answer separates I/O concurrency from CPU parallelism and ties that distinction back to the GIL.",
        ),
        _concept(
            "comprehensions vs loops",
            "Use comprehensions for simple transform/filter steps, but switch to loops when the logic becomes multi-step or side-effect heavy.",
            [
                "Comprehensions are always more readable because they are shorter.",
                "Loops should be avoided because they are less Pythonic.",
                "Comprehensions are required whenever you build a list.",
            ],
            "Readability matters more than cleverness; a short comprehension is great, but dense logic belongs in an explicit loop or helper.",
        ),
        _concept(
            "exception handling",
            "Catch the specific exception you expect, clean up if needed, and avoid swallowing errors with a bare except.",
            [
                "A bare except is safest because it prevents crashes.",
                "You should catch Exception around every function call.",
                "Specific exceptions are slower, so broad handlers are preferred.",
            ],
            "Interviewers look for precision here: specific handlers preserve debuggability and avoid hiding unrelated failures.",
        ),
    ],
    "java": [
        _concept(
            "ArrayList vs LinkedList",
            "ArrayList is usually better for cache-friendly random access, while LinkedList mainly helps when you already have the node position for insert or remove.",
            [
                "LinkedList is always faster because insertion is O(1).",
                "ArrayList should only be used for primitive types.",
                "LinkedList gives O(1) indexing by position.",
            ],
            "A practical Java answer notes that LinkedList theory often loses to ArrayList in real interview scenarios because traversal and cache behavior matter.",
        ),
        _concept(
            "equals and hashCode for HashMap keys",
            "Objects used as HashMap keys must keep equals and hashCode consistent and stable while they are in the map.",
            [
                "Overriding equals is enough because HashMap ignores hashCode.",
                "HashMap updates the hash bucket automatically when key fields change.",
                "Only immutable classes are allowed as keys.",
            ],
            "Stable equality and hashing are essential for correct key lookup; mutating key fields after insertion is a common interview gotcha.",
        ),
        _concept(
            "interface vs abstract class",
            "Use an interface for a capability contract and an abstract class when you need shared state or reusable partial implementation.",
            [
                "Interfaces are only for multiple inheritance tricks.",
                "Abstract classes are always better because they allow fields.",
                "Interfaces cannot have default methods.",
            ],
            "The strongest answer frames the choice around abstraction goals, not syntax trivia.",
        ),
        _concept(
            "String immutability and StringBuilder",
            "Repeated string concatenation in loops creates many temporary strings, so StringBuilder is usually the better tool.",
            [
                "String concatenation is always optimized into one allocation, even inside loops.",
                "StringBuilder is only useful when appending numbers.",
                "Strings are mutable, so concatenation updates the original object.",
            ],
            "Java strings are immutable, which is great for safety but expensive if you build them repeatedly in a loop.",
        ),
        _concept(
            "final, finally, and finalize",
            "final restricts reassignment or inheritance, finally runs for cleanup, and finalize is obsolete and should not be relied on.",
            [
                "finalize is the preferred cleanup mechanism in modern Java.",
                "finally only runs when no exception occurs.",
                "final and finally are interchangeable keywords.",
            ],
            "A clear answer separates compile-time intent, runtime cleanup, and legacy GC hooks.",
        ),
        _concept(
            "ExecutorService and task management",
            "Use ExecutorService, Future, or CompletableFuture for managed async work instead of creating raw threads everywhere.",
            [
                "Raw threads are preferred because they avoid pool overhead entirely.",
                "Executors are only useful for scheduled jobs, not parallel work.",
                "Future cannot report task completion or failure.",
            ],
            "Executors centralize lifecycle, limits, and error handling, which is exactly the kind of tradeoff interviewers want to hear.",
        ),
        _concept(
            "synchronized blocks vs concurrent collections",
            "Fine-grained concurrent collections usually scale better than synchronizing every access manually.",
            [
                "Concurrent collections remove the need to think about thread safety at all.",
                "synchronized makes each operation atomic across an entire workflow automatically.",
                "ConcurrentHashMap is only for read-only workloads.",
            ],
            "The right answer talks about contention, compound operations, and choosing the smallest correct synchronization scope.",
        ),
        _concept(
            "Optional usage",
            "Optional is best as a return type that signals absence, not as a field, method parameter, or serialization-heavy model property.",
            [
                "Optional should replace every nullable field in every class.",
                "Optional improves performance because it stores less data than null.",
                "Optional is required whenever a method may throw.",
            ],
            "Good Optional usage improves API clarity without spreading awkward wrappers through the object model.",
        ),
        _concept(
            "stack vs heap memory",
            "Local references live in stack frames, while the objects they point to are typically allocated on the heap.",
            [
                "Every local object is created entirely on the stack.",
                "The heap only stores primitive values, not objects.",
                "Java does not use stack frames for method calls.",
            ],
            "A solid answer keeps the model simple: call frames hold local variables, while managed objects usually live in heap memory.",
        ),
        _concept(
            "stream laziness",
            "Most intermediate stream operations are lazy, and evaluation starts only when a terminal operation runs.",
            [
                "Every stream pipeline executes immediately line by line.",
                "map is a terminal operation, so it ends the stream.",
                "Lazy streams cannot be parallelized.",
            ],
            "Interviewers often test whether you understand that stream pipelines describe work first and execute later.",
        ),
    ],
    "cpp": [
        _concept(
            "vector vs list",
            "Prefer vector by default because contiguous storage is cache-friendly; list only wins when stable iterators and node-local insert or erase dominate.",
            [
                "list is always faster because insertion is O(1).",
                "vector cannot support iteration after growth.",
                "list should be used whenever elements are large.",
            ],
            "Modern C++ interview answers should start from vector as the default and justify list only with a real access pattern.",
        ),
        _concept(
            "RAII and smart pointers",
            "RAII acquires a resource inside an object and releases it in the destructor, so smart pointers help prevent leaks automatically.",
            [
                "RAII is only relevant for heap memory, not files or locks.",
                "A smart pointer removes the need to think about ownership.",
                "Destructors only run when you call delete manually.",
            ],
            "The key idea is deterministic cleanup tied to object lifetime, which applies to memory, file handles, mutexes, and more.",
        ),
        _concept(
            "passing by const reference",
            "Pass large objects by const reference to avoid copies when you only need read access.",
            [
                "const reference is slower because indirection always costs more than copying.",
                "Pass-by-value is best for every user-defined type.",
                "const reference allows you to mutate the original object safely.",
            ],
            "This is a common performance and API-design interview topic: avoid unnecessary copies without giving up clarity.",
        ),
        _concept(
            "move semantics",
            "Move semantics transfer ownership from temporary or expiring objects instead of paying for a deep copy.",
            [
                "A move is just a faster kind of copy that leaves both objects fully independent.",
                "std::move physically moves bytes by itself.",
                "Move semantics only matter for primitive types.",
            ],
            "A strong answer explains that std::move enables moving, but the moved-from state must still remain valid.",
        ),
        _concept(
            "virtual destructors",
            "A base class used polymorphically should have a virtual destructor so derived cleanup runs correctly through a base pointer.",
            [
                "Virtual destructors are only needed when the class has virtual methods and no data.",
                "Deleting through a base pointer is always safe without a virtual destructor.",
                "A virtual destructor prevents object slicing.",
            ],
            "This is about correct destruction through base interfaces, not about slicing or inheritance style alone.",
        ),
        _concept(
            "map vs unordered_map",
            "unordered_map gives average O(1) lookup, while map keeps keys ordered with predictable O(log n) operations.",
            [
                "unordered_map is always faster and should replace map in every case.",
                "map is hash-based, so ordering is random.",
                "unordered_map keeps keys sorted automatically.",
            ],
            "The right choice depends on whether you need ordering, predictable iteration, or lower average lookup cost.",
        ),
        _concept(
            "templates vs macros",
            "Templates provide type-safe compile-time polymorphism, while macros are just textual substitution.",
            [
                "Macros are preferred because they understand C++ types better than templates.",
                "Templates run at runtime, while macros run at compile time.",
                "Templates and macros are interchangeable for debugging and overload resolution.",
            ],
            "Interviewers want to hear that templates preserve the language rules, while macros bypass them.",
        ),
        _concept(
            "pointers, references, and nullptr",
            "A reference must alias a valid object after binding, while a pointer can be null and can be reseated.",
            [
                "References are just pointers with different syntax and the same semantics.",
                "nullptr is the same as integer zero in overload resolution.",
                "Pointers cannot point to stack variables.",
            ],
            "A concise explanation of aliasing, nullability, and reseating is usually what the interviewer wants.",
        ),
        _concept(
            "emplace_back and copy elision",
            "Constructing objects in place and letting the compiler elide copies can reduce temporary allocations.",
            [
                "emplace_back is always faster even when it hurts readability.",
                "copy elision only applies to primitive return values.",
                "push_back cannot benefit from move semantics.",
            ],
            "The best answer is balanced: avoid unnecessary temporaries, but do not force in-place construction when a simple push is clearer.",
        ),
        _concept(
            "exception safety",
            "RAII and strong invariants make exception paths safe by preventing leaks and partially updated state.",
            [
                "Turning off exceptions is the only way to write safe C++ code.",
                "Exception safety only matters for constructors.",
                "If an exception is caught somewhere, resource leaks cannot happen.",
            ],
            "A strong C++ answer mentions basic or strong guarantees and ties them back to ownership and rollback behavior.",
        ),
    ],
    "dsa": [
        _concept(
            "hashing vs sorting for membership checks",
            "Hashing is usually better for repeated membership queries, while sorting helps when you also need ordered traversal or two-pointer logic.",
            [
                "Sorting is always faster because comparisons are cheap.",
                "Hashing only works for positive integers.",
                "You should sort first for every lookup problem.",
            ],
            "Interviewers want to see that you match the data structure to the operation pattern, not just quote complexity tables.",
        ),
        _concept(
            "two pointers",
            "Two pointers work when movement of one or both indices preserves progress, often on sorted arrays or shrinking windows.",
            [
                "Two pointers only apply to linked lists.",
                "Two pointers always require a nested loop.",
                "Any unsorted problem can be solved with two pointers directly.",
            ],
            "The technique depends on a monotonic property that lets you move pointers without revisiting every combination.",
        ),
        _concept(
            "sliding window",
            "Sliding window is useful when a contiguous range can be expanded and shrunk while maintaining an incremental state.",
            [
                "Sliding window is the same as prefix sums in every problem.",
                "The window must always stay a fixed size.",
                "Sliding window only works on sorted arrays.",
            ],
            "A strong explanation highlights the maintained state, such as counts or sums, and how updates stay efficient.",
        ),
        _concept(
            "BFS vs DFS",
            "Use BFS when shortest path in an unweighted graph matters, and DFS when you need depth-oriented traversal, backtracking, or cycle structure.",
            [
                "DFS always finds the shortest path faster than BFS.",
                "BFS cannot be implemented recursively.",
                "DFS and BFS differ only in memory usage, not behavior.",
            ],
            "This tradeoff appears constantly in interviews, so it helps to tie the traversal choice directly to the question goal.",
        ),
        _concept(
            "binary search on the answer",
            "Binary search applies when the search space is ordered by a monotonic feasibility check, not just when you search a sorted array directly.",
            [
                "Binary search only works when the original input array is already sorted.",
                "You need exact values in the array to use binary search.",
                "Binary search on answers requires O(1) feasibility checks.",
            ],
            "The core idea is to search over a valid range of answers while checking a monotonic predicate.",
        ),
        _concept(
            "heap for top-k problems",
            "A heap is useful when you need repeated access to the smallest or largest candidate without fully sorting everything.",
            [
                "A heap is always better than sorting, even when you need the full final order.",
                "Heaps only support max behavior, not min behavior.",
                "Heap insertion is O(1), so complexity is never a concern.",
            ],
            "A top-k answer should compare heap-based partial ordering with full sorting and explain the tradeoff.",
        ),
        _concept(
            "union-find",
            "Union-find is ideal for dynamic connectivity queries where you repeatedly merge sets and ask whether items share a component.",
            [
                "Union-find replaces BFS and DFS for every graph problem.",
                "Union-find is only useful on trees.",
                "Path compression changes correctness, so it should be avoided.",
            ],
            "The interviewer usually wants to hear about parent pointers, path compression, and union by rank or size.",
        ),
        _concept(
            "memoization vs tabulation",
            "Memoization follows the top-down recurrence you actually visit, while tabulation computes states bottom-up in dependency order.",
            [
                "Memoization is always slower because recursion is forbidden in interviews.",
                "Tabulation and memoization solve different classes of problems.",
                "Memoization cannot reduce repeated work.",
            ],
            "A strong DP answer compares recursion depth, state reachability, and implementation clarity.",
        ),
        _concept(
            "prefix sums",
            "Prefix sums precompute cumulative totals so range queries become O(1) after O(n) preprocessing.",
            [
                "Prefix sums only work when every number is positive.",
                "A prefix sum replaces the need for any index math.",
                "Range sums with prefix sums still require scanning the whole subarray.",
            ],
            "The common interview move is to trade one preprocessing pass for many faster range queries.",
        ),
        _concept(
            "greedy correctness",
            "A greedy algorithm needs a reason why each local choice can extend to a global optimum, not just a few passing examples.",
            [
                "If a greedy choice works on the sample input, the proof is done.",
                "Greedy algorithms do not need correctness arguments when they are fast.",
                "Dynamic programming and greedy differ only in syntax.",
            ],
            "Interviewers look for an exchange argument, invariant, or monotonic structure that justifies the greedy step.",
        ),
    ],
}


CODING_BANKS = {
    "python": [
        _challenge(
            "Implement `group_anagrams(words)` that groups strings sharing the same letters.",
            "Aim for O(n * k log k) or better, where k is the word length.",
            "['eat', 'tea', 'tan', 'ate', 'nat', 'bat']",
            "[['eat', 'tea', 'ate'], ['tan', 'nat'], ['bat']]",
            "Use a dictionary keyed by a sorted-character signature or frequency tuple, then collect the grouped words.",
            "Create a stable signature for each word, append into a hash map, and emit the grouped values at the end.",
        ),
        _challenge(
            "Write `flatten_nested_list(values)` for nested lists of integers without using recursion helpers from the standard library.",
            "Support deeply nested input and preserve left-to-right order.",
            "[1, [2, [3, 4]], 5]",
            "[1, 2, 3, 4, 5]",
            "Use an explicit stack of iterators or lists so you can flatten iteratively and preserve order.",
            "Traverse the nested structure with your own stack, expanding lists and appending integers in encounter order.",
        ),
        _challenge(
            "Create a retry decorator that retries a function up to `n` times for selected exceptions.",
            "Keep the wrapped function signature usable and stop retrying on success.",
            "retry(3) on a flaky function",
            "function eventually returns a value or raises after 3 failures",
            "Wrap the callable in a closure, catch only the configured exceptions, and retry until success or the retry budget is exhausted.",
            "The clean design is a decorator factory that stores retry policy and a wrapper that loops until the call succeeds or must re-raise.",
        ),
        _challenge(
            "Implement `merge_intervals(intervals)` for a list of inclusive integer ranges.",
            "Intervals may arrive unsorted.",
            "[[1, 3], [2, 6], [8, 10], [15, 18]]",
            "[[1, 6], [8, 10], [15, 18]]",
            "Sort by start time, then merge greedily while the current interval overlaps the last merged interval.",
            "Sorting creates the monotonic structure you need; after that, keep one merged output list and extend the last interval when overlap exists.",
        ),
        _challenge(
            "Implement `longest_unique_substring_length(text)`.",
            "Return the maximum length of a substring with no repeated characters.",
            "'abcabcbb'",
            "3",
            "Use a sliding window with a map from character to its latest index so the left pointer jumps instead of rescanning.",
            "Track the current window bounds and update the left boundary whenever a repeated character appears inside the active window.",
        ),
        _challenge(
            "Design an `LRUCache` class with `get(key)` and `put(key, value)` in O(1) average time.",
            "Evict the least recently used item when capacity is exceeded.",
            "capacity=2, put(1,1), put(2,2), get(1), put(3,3)",
            "cache evicts key 2",
            "Combine a hash map for lookup with a doubly linked list that tracks recency.",
            "A hash map gives O(1) node access, and the linked list lets you move touched items to the front and evict from the tail.",
        ),
        _challenge(
            "Implement `top_k_frequent_words(words, k)`.",
            "When frequencies tie, order the tied words lexicographically.",
            "words=['i','love','leetcode','i','love','coding'], k=2",
            "['i', 'love']",
            "Count word frequencies, then use sorting or a heap with a tie-break that favors lexical order.",
            "Build a frequency map first, then produce the top k with deterministic tie-breaking.",
        ),
        _challenge(
            "Write `deep_merge(left, right)` for nested dictionaries.",
            "If both sides contain dictionaries at the same key, merge recursively; otherwise, `right` wins.",
            "{'a': 1, 'b': {'x': 2}}, {'b': {'y': 3}, 'c': 4}",
            "{'a': 1, 'b': {'x': 2, 'y': 3}, 'c': 4}",
            "Traverse keys from both dictionaries, recurse only when both values are dictionaries, and copy primitives directly.",
            "A recursive structural merge works well here, but be clear about ownership so you do not mutate caller-owned nested objects unexpectedly.",
        ),
        _challenge(
            "Implement `aggregate_log_levels(lines)` that counts INFO, WARN, and ERROR entries from raw log lines.",
            "Ignore malformed lines that do not start with a known severity label.",
            "['INFO startup', 'WARN cache miss', 'ERROR boom', 'DEBUG trace']",
            "{'INFO': 1, 'WARN': 1, 'ERROR': 1}",
            "Parse each line once, validate the leading token, and update a counter map for recognized severities.",
            "Keep the parsing rule simple: extract the first token, check membership in the allowed severities, and increment the matching bucket.",
        ),
        _challenge(
            "Design a simple in-memory rate limiter for one user that allows at most `limit` requests per rolling minute.",
            "Implement `allow(timestamp)` returning true or false.",
            "limit=3, calls at [1, 10, 20, 50, 70]",
            "[true, true, true, false, true]",
            "Use a deque of accepted timestamps and discard entries older than 60 seconds before checking capacity.",
            "A queue or deque keeps only relevant timestamps, so each request does O(1) amortized work.",
        ),
    ],
    "java": [
        _challenge(
            "Design an `LRUCache<K, V>` with O(1) average `get` and `put`.",
            "Use standard Java collections plus your own node structure where needed.",
            "capacity=2, put(1,1), put(2,2), get(1), put(3,3)",
            "cache evicts key 2",
            "Combine a HashMap with a doubly linked list so lookups and recency updates stay O(1).",
            "Use the map for node lookup and a custom doubly linked list for ordering by recent use.",
        ),
        _challenge(
            "Implement `mergeIntervals(List<int[]>)` for unsorted closed intervals.",
            "Return a new list of merged intervals.",
            "[[1,3],[2,6],[8,10],[15,18]]",
            "[[1,6],[8,10],[15,18]]",
            "Sort by start value, then scan once and merge overlapping ranges greedily.",
            "The sorted order guarantees that only the last merged interval can overlap the current one.",
        ),
        _challenge(
            "Implement a `MinStack` supporting `push`, `pop`, `top`, and `getMin` in O(1).",
            "Do not scan the stack when returning the minimum.",
            "push(3), push(1), push(2), getMin()",
            "1",
            "Store each value with the minimum seen so far, or maintain a second stack of minimums.",
            "Track the running minimum alongside each element so the answer is always available at the top.",
        ),
        _challenge(
            "Build a bounded producer-consumer queue with blocking `put` and `take` semantics.",
            "Use core Java synchronization primitives, not external libraries.",
            "capacity=2 with multiple producers and consumers",
            "items are produced and consumed without overflow or underflow races",
            "Protect shared state with a monitor or lock, wait when the queue is full or empty, and notify when state changes.",
            "The key is a correct condition-variable pattern: wait in a loop, change state atomically, then notify waiting threads.",
        ),
        _challenge(
            "Implement `lengthOfLongestSubstring(String s)` for substrings without repeated characters.",
            "Aim for linear time.",
            "\"abcabcbb\"",
            "3",
            "Use a sliding window and remember the latest index of each character to jump the left boundary efficiently.",
            "A HashMap from character to last index removes the need to restart scanning from scratch.",
        ),
        _challenge(
            "Implement `topKFrequent(int[] nums, int k)`.",
            "Return the k most frequent values in any deterministic order.",
            "nums=[1,1,1,2,2,3], k=2",
            "[1,2]",
            "Count frequencies first, then use a heap or bucket-style grouping to extract the top k values.",
            "Frequency counting plus a top-k structure beats sorting the full array blindly in large inputs.",
        ),
        _challenge(
            "Sort a list of employees by department, then salary descending, then name ascending.",
            "Design the comparator cleanly and keep the code readable.",
            "[('Eng', 120, 'Ava'), ('Eng', 110, 'Noah'), ('HR', 90, 'Mia')]",
            "[('Eng', 120, 'Ava'), ('Eng', 110, 'Noah'), ('HR', 90, 'Mia')]",
            "Use Comparator chaining with explicit rules so the ordering logic is easy to audit.",
            "Comparator composition is the clean Java answer here because it keeps each ordering rule readable and testable.",
        ),
        _challenge(
            "Implement level-order traversal for a binary tree.",
            "Return node values grouped by level.",
            "root=[3,9,20,null,null,15,7]",
            "[[3],[9,20],[15,7]]",
            "Use a queue for BFS and process one level at a time based on the current queue size.",
            "A queue naturally models BFS; capturing the queue length before each level gives you clean grouping.",
        ),
        _challenge(
            "Evaluate a basic arithmetic expression containing non-negative integers, `+`, `-`, `*`, `/`, and spaces.",
            "Respect normal operator precedence.",
            "\"3+2*2\"",
            "7",
            "Scan once, build the current number, and use a stack or running totals so multiplication and division apply before addition and subtraction.",
            "The common interview strategy is to push signed terms and collapse multiplication or division immediately.",
        ),
        _challenge(
            "Design a thread-safe hit counter that returns the number of hits in the past five minutes.",
            "Implement `hit(timestamp)` and `getHits(timestamp)`.",
            "timestamps=[1,2,3,300,301]",
            "getHits(301)=4",
            "Store timestamps in a queue, evict hits older than 300 seconds, and synchronize access around updates.",
            "A rolling-window queue keeps only relevant timestamps, and synchronization protects correctness under concurrency.",
        ),
    ],
    "cpp": [
        _challenge(
            "Implement `kthLargest(vector<int>& nums, int k)`.",
            "Avoid fully sorting the array if you can do better.",
            "nums=[3,2,1,5,6,4], k=2",
            "5",
            "Use quickselect for average linear time or a min-heap of size k for predictable O(n log k).",
            "Both heap and quickselect are valid; explain why you picked one and what tradeoff you made.",
        ),
        _challenge(
            "Implement `mergeIntervals(vector<vector<int>> intervals)`.",
            "The input is unsorted and may contain touching intervals.",
            "[[1,3],[2,6],[8,10],[15,18]]",
            "[[1,6],[8,10],[15,18]]",
            "Sort by start value, then merge greedily while intervals overlap.",
            "Once intervals are ordered by start, a single pass with the last merged interval is enough.",
        ),
        _challenge(
            "Build a trie supporting `insert`, `search`, and `startsWith`.",
            "Use lowercase English letters.",
            "insert('cat'), insert('car'), search('cat'), startsWith('ca')",
            "true, true",
            "Represent each node with child pointers or arrays plus an end-of-word marker.",
            "A trie stores each prefix once, so lookup time scales with word length instead of dictionary size.",
        ),
        _challenge(
            "Design an `LRUCache` with O(1) average operations.",
            "Use STL containers where they help, but keep ownership and iterator validity clear.",
            "capacity=2, put(1,1), put(2,2), get(1), put(3,3)",
            "cache evicts key 2",
            "Combine `unordered_map` with a `list` so map lookups and recency updates stay efficient.",
            "Store list iterators in the hash map, move touched items to the front, and evict from the back when capacity is exceeded.",
        ),
        _challenge(
            "Return a valid topological ordering for a directed acyclic graph.",
            "If a cycle exists, report failure instead of returning a partial order.",
            "edges=[[0,1],[0,2],[1,3],[2,3]]",
            "[0,1,2,3] or [0,2,1,3]",
            "Use Kahn's algorithm with indegrees or DFS with cycle detection.",
            "Kahn's algorithm is often the clearest interview answer because indegree reduction makes cycle detection explicit.",
        ),
        _challenge(
            "Design a data structure that returns the median of a stream after each insertion.",
            "Support many inserts efficiently.",
            "insert 5, 2, 10, 4",
            "medians = 5, 3.5, 5, 4.5",
            "Maintain a max-heap for the lower half and a min-heap for the upper half, then rebalance after each insert.",
            "The two-heap pattern keeps the halves balanced so the median is always at one or two heap tops.",
        ),
        _challenge(
            "Implement `minWindow(string s, string t)` for the minimum substring of `s` containing all chars of `t`.",
            "Return an empty string when no valid window exists.",
            "s='ADOBECODEBANC', t='ABC'",
            "'BANC'",
            "Use a sliding window with frequency counts and shrink the left side while the window remains valid.",
            "Track required counts, expand until valid, then shrink aggressively to minimize the window.",
        ),
        _challenge(
            "Given edges of an undirected graph that started as a tree plus one extra edge, return the redundant connection.",
            "Nodes are labeled from 1 to n.",
            "edges=[[1,2],[1,3],[2,3]]",
            "[2,3]",
            "Use union-find and return the first edge whose endpoints are already connected.",
            "Union-find is ideal because each edge only needs a connectivity check plus a union operation.",
        ),
        _challenge(
            "Sort pairs `(x, y)` by `x` ascending and `y` descending when `x` ties.",
            "Write the comparator clearly and safely.",
            "[(1,2),(1,5),(0,9)]",
            "[(0,9),(1,5),(1,2)]",
            "Define a comparator that expresses both rules explicitly and keeps strict weak ordering intact.",
            "Comparator correctness matters in C++; a concise lambda with clear tie logic is usually enough.",
        ),
        _challenge(
            "Simplify a Unix-style file path.",
            "Handle `.`, `..`, and repeated slashes.",
            "\"/a/./b/../../c/\"",
            "\"/c\"",
            "Split by slash, ignore empty parts and `.`, pop on `..`, and join the remaining stack.",
            "A stack models directory traversal cleanly and avoids fragile string slicing tricks.",
        ),
    ],
    "dsa": [
        _challenge(
            "Solve Two Sum and return the indices of the two numbers that add up to the target.",
            "Assume exactly one solution exists.",
            "nums=[2,7,11,15], target=9",
            "[0,1]",
            "Use a hash map from value to index so each element can find its complement in O(1) average time.",
            "Store seen values as you scan; for each number, check whether the needed complement has already appeared.",
        ),
        _challenge(
            "Validate whether a string of brackets is balanced.",
            "Support `()`, `[]`, and `{}`.",
            "\"()[]{}\"",
            "true",
            "Use a stack to track opening brackets and verify each closing bracket matches the most recent open one.",
            "A stack is the natural fit because bracket matching is last-in, first-out.",
        ),
        _challenge(
            "Return the length of the longest consecutive sequence in an unsorted array.",
            "Aim for linear time.",
            "nums=[100,4,200,1,3,2]",
            "4",
            "Put values in a hash set, then start counting only from sequence starts whose predecessor is absent.",
            "The hash set removes repeated membership scans, and only starting from sequence heads keeps the total work linear.",
        ),
        _challenge(
            "Count the number of islands in a 2D grid of `'1'` and `'0'` cells.",
            "Cells connect horizontally and vertically.",
            "[['1','1','0'],['1','0','0'],['0','1','1']]",
            "2",
            "Traverse each unvisited land cell with BFS or DFS and mark the whole component visited.",
            "Each island is one connected component, so the answer is the number of component traversals you start.",
        ),
        _challenge(
            "Determine whether all courses can be finished given prerequisite pairs.",
            "Return true if the directed graph has no cycle.",
            "numCourses=2, prereqs=[[1,0]]",
            "true",
            "Model prerequisites as a directed graph and use topological sorting or DFS cycle detection.",
            "The problem reduces to checking whether the dependency graph is acyclic.",
        ),
        _challenge(
            "Find the minimum number of coins needed to make a target amount.",
            "Return -1 if the amount cannot be formed.",
            "coins=[1,2,5], amount=11",
            "3",
            "Use dynamic programming where each amount depends on smaller reachable amounts.",
            "Build the answer bottom-up and treat unreachable states with a large sentinel or infinity.",
        ),
        _challenge(
            "Merge k sorted linked lists into one sorted list.",
            "Optimize for many short lists as well as a few long ones.",
            "lists=[[1,4,5],[1,3,4],[2,6]]",
            "[1,1,2,3,4,4,5,6]",
            "Use a min-heap keyed by current node value so you always pull the next smallest head.",
            "A heap keeps the merge cost at O(n log k) instead of rescanning every list head repeatedly.",
        ),
        _challenge(
            "Find the lowest common ancestor of two nodes in a BST.",
            "Use the BST ordering property instead of storing full root-to-node paths.",
            "root=[6,2,8,0,4,7,9,null,null,3,5], p=2, q=8",
            "6",
            "Walk down from the root: if both targets are smaller go left, if both are larger go right, otherwise the current node is the answer.",
            "The BST property gives you a monotonic search path, so no extra storage is necessary.",
        ),
        _challenge(
            "Return the maximum value in each sliding window of size `k`.",
            "Aim for O(n) time.",
            "nums=[1,3,-1,-3,5,3,6,7], k=3",
            "[3,3,5,5,6,7]",
            "Use a deque that stores candidate indices in decreasing value order.",
            "The deque keeps the current maximum at the front while removing expired or dominated indices in O(1) amortized time.",
        ),
        _challenge(
            "Compute the shortest transformation length from `beginWord` to `endWord` by changing one letter at a time.",
            "Each intermediate word must exist in the dictionary.",
            "begin='hit', end='cog', words=['hot','dot','dog','lot','log','cog']",
            "5",
            "Use BFS because each valid one-letter transformation has equal cost, and generate neighbors efficiently.",
            "This is an unweighted shortest-path problem, so BFS is the right traversal.",
        ),
    ],
}


def _rotate(items: list[str], shift: int) -> list[str]:
    if not items:
        return []
    shift %= len(items)
    return items[shift:] + items[:shift]


def _difficulty(index: int) -> str:
    return ["basic", "intermediate", "advanced"][index % 3]


def build_mcq_questions(topic: str, count: int, start_index: int = 0) -> list[dict[str, Any]]:
    banks = MCQ_BANKS.get(topic, MCQ_BANKS["dsa"])
    rows = []

    for offset in range(count):
        absolute_index = start_index + offset
        concept = banks[absolute_index % len(banks)]
        scenario = MCQ_SCENARIOS[(absolute_index // len(banks)) % len(MCQ_SCENARIOS)]

        options = [concept["correct"], *concept["distractors"]]
        options = _rotate(options, absolute_index)

        rows.append(
            {
                "question": f"Q{absolute_index + 1}: {scenario.format(subject=concept['subject'])}",
                "sequence": absolute_index + 1,
                "options": options,
                "answer": concept["correct"],
                "solution": concept["solution"],
                "difficulty": _difficulty(absolute_index),
            }
        )

    return rows


def build_coding_questions(topic: str, count: int, start_index: int = 0) -> list[dict[str, Any]]:
    challenges = CODING_BANKS.get(topic, CODING_BANKS["dsa"])
    rows = []

    for offset in range(count):
        absolute_index = start_index + offset
        challenge = challenges[absolute_index % len(challenges)]
        variant = CODING_VARIANTS[(absolute_index // len(challenges)) % len(CODING_VARIANTS)]

        rows.append(
            {
                "question": f"Q{absolute_index + 1}: {challenge['statement']} {variant['prompt']}",
                "sequence": absolute_index + 1,
                "constraints": f"{challenge['constraints']} {variant['constraints']}",
                "sample_input": challenge["sample_input"],
                "sample_output": challenge["sample_output"],
                "expected_approach": f"{challenge['expected_approach']} {variant['expected']}",
                "solution": f"{challenge['solution']} {variant['solution']}",
                "difficulty": _difficulty(absolute_index),
            }
        )

    return rows
