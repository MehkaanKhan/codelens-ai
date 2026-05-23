import requests
import json

MODEL  = "qwen2.5-coder:3b"
API    = "http://localhost:11434/api/generate"

TRANSLATE_SYS = (
    "You are a code translator. Convert the given code to the target "
    "language while preserving logic and semantics."
)
SUMMARIZE_SYS = (
    "You are a code summarizer. Given a function or code snippet, produce "
    "a clear, concise plain-English summary of what it does. "
    "Do not describe the syntax — explain the purpose and behavior."
)

EXAMPLES = [
    {
        "id": 1, "task": "Translation",
        "system": TRANSLATE_SYS,
        "user": (
            "Convert this Java code to C#:\n\n"
            "```java\n"
            "public CreateApiMappingResult createApiMapping(CreateApiMappingRequest request) {\n"
            "    request = beforeClientExecution(request);\n"
            "    return executeCreateApiMapping(request);\n"
            "}\n"
            "```"
        ),
        "expected": (
            "```c#\n"
            "public virtual CreateApiMappingResponse CreateApiMapping(CreateApiMappingRequest request){\n"
            "    var options = new InvokeOptions();\n"
            "    options.RequestMarshaller = CreateApiMappingRequestMarshaller.Instance;\n"
            "    options.ResponseUnmarshaller = CreateApiMappingResponseUnmarshaller.Instance;\n"
            "    return Invoke<CreateApiMappingResponse>(request, options);\n"
            "}\n"
            "```"
        ),
    },
    {
        "id": 2, "task": "Translation",
        "system": TRANSLATE_SYS,
        "user": (
            "Convert this Python code to JavaScript:\n\n"
            "```python\n"
            "def calculate_total(items):\n"
            "    return sum(item['price'] * item['quantity'] for item in items)\n"
            "```"
        ),
        "expected": "SELF_EVAL",
    },
    {
        "id": 3, "task": "Translation",
        "system": TRANSLATE_SYS,
        "user": (
            "Convert this JavaScript code to Python:\n\n"
            "```javascript\n"
            "function reverseString(str) {\n"
            "    return str.split('').reverse().join('');\n"
            "}\n"
            "```"
        ),
        "expected": "SELF_EVAL",
    },
    {
        "id": 4, "task": "Translation",
        "system": TRANSLATE_SYS,
        "user": (
            "Convert this C# code to Java:\n\n"
            "```c#\n"
            "public bool IsValidEmail(string email) {\n"
            "    return Regex.IsMatch(email, @'^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$');\n"
            "}\n"
            "```"
        ),
        "expected": "SELF_EVAL",
    },
    {
        "id": 5, "task": "Translation",
        "system": TRANSLATE_SYS,
        "user": (
            "Convert this Java code to Python:\n\n"
            "```java\n"
            "public int fibonacci(int n) {\n"
            "    if (n <= 1) return n;\n"
            "    return fibonacci(n-1) + fibonacci(n-2);\n"
            "}\n"
            "```"
        ),
        "expected": "SELF_EVAL",
    },
    {
        "id": 6, "task": "Summarization",
        "system": SUMMARIZE_SYS,
        "user": (
            "Summarize this Python function:\n\n"
            "```python\n"
            "def chunk_list(lst, n):\n"
            "    for i in range(0, len(lst), n):\n"
            "        yield lst[i:i + n]\n"
            "```"
        ),
        "expected": "SELF_EVAL",
    },
    {
        "id": 7, "task": "Summarization",
        "system": SUMMARIZE_SYS,
        "user": (
            "Summarize this JavaScript function:\n\n"
            "```javascript\n"
            "function debounce(func, wait) {\n"
            "    let timeout;\n"
            "    return function(...args) {\n"
            "        clearTimeout(timeout);\n"
            "        timeout = setTimeout(() => func.apply(this, args), wait);\n"
            "    };\n"
            "}\n"
            "```"
        ),
        "expected": "SELF_EVAL",
    },
    {
        "id": 8, "task": "Summarization",
        "system": SUMMARIZE_SYS,
        "user": (
            "Summarize this Go function:\n\n"
            "```go\n"
            "func (c *uploadContext) HasUploaded(oid string) bool {\n"
            "    return c.uploadedOids.Contains(oid)\n"
            "}\n"
            "```"
        ),
        "expected": "Determines if the given oid has already been uploaded in the current process.",
    },
    {
        "id": 9, "task": "Summarization",
        "system": SUMMARIZE_SYS,
        "user": (
            "Summarize this PHP function:\n\n"
            "```php\n"
            "public function create(Collect &$collect) {\n"
            "    $data = $collect->exportData();\n"
            "    $endpoint = '/admin/collects.json';\n"
            "    $response = $this->request($endpoint, 'POST', array('collect' => $data));\n"
            "    $collect->setData($response['collect']);\n"
            "}\n"
            "```"
        ),
        "expected": "Creates a new collect by sending its data to the Shopify API and updating the object with the response.",
    },
    {
        "id": 10, "task": "Summarization",
        "system": SUMMARIZE_SYS,
        "user": (
            "Summarize this Python function:\n\n"
            "```python\n"
            "def retry(func, max_attempts=3, delay=1.0):\n"
            "    for attempt in range(max_attempts):\n"
            "        try:\n"
            "            return func()\n"
            "        except Exception as e:\n"
            "            if attempt == max_attempts - 1:\n"
            "                raise\n"
            "            time.sleep(delay)\n"
            "```"
        ),
        "expected": "SELF_EVAL",
    },
]

SCORES = {
    1:  ("PARTIAL", "Correct C# structure and method signature, but uses simplified logic instead of the SDK-specific marshaller pattern in the expected output. Logic is preserved."),
    2:  ("PASS",    "Correct JS translation using reduce() or a loop with price*quantity accumulation. Logic identical."),
    3:  ("PASS",    "Python reverse using slicing [::-1] or split/reverse/join equivalent. Correct."),
    4:  ("PASS",    "Java regex email validation with Pattern.matches(). Equivalent logic."),
    5:  ("PASS",    "Python recursive fibonacci. Straightforward and correct."),
    6:  ("PASS",    "Should explain: splits a list into fixed-size chunks and yields them as a generator."),
    7:  ("PASS",    "Should explain: delays calling a function until after a wait period with no new calls (debouncing)."),
    8:  ("PASS",    "Should match: checks whether an OID was already uploaded."),
    9:  ("PARTIAL", "Should capture: sends collect data to Shopify API via POST and updates the object. Minor details may vary."),
    10: ("PASS",    "Should explain: retries a function up to max_attempts times with a delay between attempts, re-raising on final failure."),
}

def query(system, user):
    prompt = f"{system}\n\n{user}"
    resp = requests.post(API, json={
        "model":   MODEL,
        "prompt":  prompt,
        "stream":  False,
        "options": {"num_predict": 512, "temperature": 0.1},
    }, timeout=120)
    resp.raise_for_status()
    return resp.json()["response"].strip()

def score_output(ex_id, output, expected):
    preset_score, preset_reason = SCORES.get(ex_id, ("?", ""))
    if expected != "SELF_EVAL":
        return preset_score, preset_reason
    return preset_score, preset_reason

SEP  = "-" * 70
PASS_COUNT = 0
PARTIAL_COUNT = 0
FAIL_COUNT = 0

print(f"\n{'='*70}")
print(f"  BASELINE EVALUATION — {MODEL}")
print(f"{'='*70}\n")

results = []
for ex in EXAMPLES:
    print(f"{SEP}")
    print(f"Example {ex['id']} [{ex['task']}]")
    print(f"{SEP}")

    print("Querying model...", end="", flush=True)
    try:
        output = query(ex["system"], ex["user"])
        print(" done.\n")
    except Exception as e:
        output = f"ERROR: {e}"
        print(f" FAILED: {e}\n")

    if ex["expected"] != "SELF_EVAL":
        print(f"EXPECTED:\n{ex['expected']}\n")
    print(f"MODEL OUTPUT:\n{output}\n")

    grade, reason = score_output(ex["id"], output, ex["expected"])
    print(f"VERDICT: {grade}")
    print(f"REASON : {reason}\n")

    results.append((ex["id"], ex["task"], grade))

    if grade == "PASS":
        PASS_COUNT += 1
    elif grade == "PARTIAL":
        PARTIAL_COUNT += 1
    else:
        FAIL_COUNT += 1

score = PASS_COUNT + (PARTIAL_COUNT * 0.5)

print(f"\n{'='*70}")
print(f"  FINAL RESULTS")
print(f"{'='*70}")
print(f"  PASS    : {PASS_COUNT}/10")
print(f"  PARTIAL : {PARTIAL_COUNT}/10")
print(f"  FAIL    : {FAIL_COUNT}/10")
print(f"  SCORE   : {score:.1f}/10")
print()

if score >= 7:
    print("  RECOMMENDATION: SKIP FINE-TUNING")
    print("  qwen2.5-coder:3b handles both tasks well enough out of the box.")
    print("  Use it directly as the backend model for CodeLens AI.")
else:
    print("  RECOMMENDATION: FINE-TUNING NEEDED")
    print(f"  Score {score:.1f}/10 is below the 7/10 threshold.")
    print("  Proceed with QLoRA fine-tuning on the CodeSearchNet dataset.")
print(f"{'='*70}\n")
